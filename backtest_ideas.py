# backtest_ideas.py
#
# Multi-test runner: 3 new ideas tested against V35 baseline in one workflow run.
#
# TESTS:
#   Baseline : V35 unchanged
#   Test A   : Equity curve trading (size down when equity below its 20d MA)
#   Test B   : Continuous volatility-scaled position sizing (replaces VIX binary)
#   Test C   : Turn-of-month sizing (full size days 1-5 + 26-31, 70% mid-month)
#   Test AB  : A + B combined
#   Test AC  : A + C combined
#   Test BC  : B + C combined
#   Test ABC : All three combined
#
# Each test runs the full 2004-2026 backtest and outputs to results_ideas/.
# Final comparison table printed at end.
#
# IMPORTANT: This imports from backtest_nmr_lib.py (V35 baseline).
# Push both files to repo root before running.
#
# GitHub Actions: Actions -> Naive MR Backtest -> Run workflow
# (uses existing workflow -- just runs this file instead of backtest-nmr.py)
# OR create a new workflow pointing to this file.

import json
import datetime
import warnings
from pathlib import Path
from collections import deque

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

# Import V35 baseline infrastructure
from backtest_nmr_lib import (
    get_universe,
    download_prices,
    download_reference_data,
    build_earnings_dates,
    compute_metrics,
    save_outputs,
    INITIAL_CAPITAL,
    START_DATE,
    END_DATE,
)

# Import V35 constants we need to replicate the simulation loop
import backtest_nmr_lib as lib

OUTPUT_DIR = Path("results_ideas")
OUTPUT_DIR.mkdir(exist_ok=True)

# =============================================================================
# Test flags -- each run passes a config dict
# =============================================================================

TESTS = [
    {
        "name":              "Baseline_V35",
        "equity_curve_ma":   False,
        "vol_scaled_sizing": False,
        "turn_of_month":     False,
    },
    {
        "name":              "A_EquityCurve",
        "equity_curve_ma":   True,
        "vol_scaled_sizing": False,
        "turn_of_month":     False,
    },
    {
        "name":              "B_VolScaling",
        "equity_curve_ma":   False,
        "vol_scaled_sizing": True,
        "turn_of_month":     False,
    },
    {
        "name":              "C_TurnOfMonth",
        "equity_curve_ma":   False,
        "vol_scaled_sizing": False,
        "turn_of_month":     True,
    },
]

# =============================================================================
# Test A: Equity curve trading
# =============================================================================
# Maintain a rolling equity series. When equity is below its 20-day MA,
# apply EC_SIZE_MULT to all new position sizes (default 0.5 = half size).
# When equity is above its 20-day MA, full size (mult = 1.0).
#
# Key difference from rolling WR test (which failed):
#   - Rolling WR fired during crash-recovery windows because win rate dropped
#     before the crash entries fired. The equity curve drops during crash too,
#     BUT recovers within 1-2 rebalance cycles as recovery entries generate
#     large positive P&L. This means the filter self-corrects faster.
#   - WR is binary (win/loss). Equity curve captures magnitude -- a small
#     number of large losses pulls the curve below MA but large recovery wins
#     pull it back above quickly.
EC_LOOKBACK  = 20    # Days for equity curve MA
EC_SIZE_MULT = 0.50  # Size multiplier when equity below its MA

# =============================================================================
# Test B: Continuous volatility-scaled position sizing
# =============================================================================
# Replace binary VIX threshold (VIX<25 -> 9%, else 5%) with continuous scaling.
# Formula: size = base_size * (TARGET_VOL / realized_vol)
# Where realized_vol = 20-day rolling annualized volatility of SPY daily returns.
# Capped at VOL_MAX_MULT to prevent runaway sizing in ultra-low-vol environments.
#
# Calibration: TARGET_VOL set so that at average SPY vol (~15% annualized),
# the resulting size matches V35's average position size (~7% midpoint of 5-9%).
VOL_LOOKBACK  = 20      # Days for realized vol calculation
TARGET_VOL    = 0.15    # Target annualized volatility (15% = historical SPY avg)
VOL_BASE_SIZE = 0.07    # Base size at target vol (midpoint of V35's 5-9% range)
VOL_MAX_MULT  = 1.30    # Cap multiplier (prevent > 130% of base at ultra-low vol)
VOL_MIN_MULT  = 0.40    # Floor multiplier (prevent < 40% of base at extreme vol)

# =============================================================================
# Test C: Turn-of-month sizing
# =============================================================================
# Research shows equity returns cluster at month boundaries (days 1-5, 26-31)
# and around OpEx. Mean reversion specifically benefits from this because
# selling pressure (which creates the entry signal) concentrates at month-end
# rebalancing and beginning-of-month repositioning.
# Mid-month trades in low-vol environments are structurally weaker.
# Full size on "active" days, reduced size mid-month.
TOM_ACTIVE_DAYS    = list(range(1, 6)) + list(range(26, 32))  # Days 1-5 and 26-31
TOM_MIDMONTH_MULT  = 0.70   # 70% size mid-month (days 6-25)


# =============================================================================
# Shared helpers
# =============================================================================
def _compute_rsi(series, period):
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def _calc_commission(shares, price):
    return max(shares * lib.COMMISSION_RATE, lib.COMMISSION_MIN)

def _get_tier(consec_down):
    return lib.get_tier(consec_down)

def _near_earnings(tkr, date, earnings_map):
    return lib.near_earnings(tkr, date, earnings_map)

def _sector_ok(tkr, date, sector_data):
    return lib.sector_ok(tkr, date, sector_data)

def _count_sector_positions(tkr, open_positions):
    return lib.count_sector_positions(tkr, open_positions)

def _check_vix_spike(today, vix_df, last_spike_date):
    return lib.check_vix_spike(today, vix_df, last_spike_date)

def _generate_signals(df):
    return lib.generate_signals(df)


# =============================================================================
# Modified position size function
# =============================================================================
def get_position_size_modified(today, vix_df, drawdown_pct=0.0,
                                multiplier=1.0, hard_cap=0.20,
                                spy_realized_vol=None, cfg=None):
    """
    V35 position sizing with optional Test B (vol-scaled) override.
    Test A and C multipliers are applied externally via combined_multiplier.
    """
    cfg = cfg or {}
    month = pd.Timestamp(today).month
    earnings_month = month in lib.EARNINGS_MONTHS

    if cfg.get("vol_scaled_sizing") and spy_realized_vol is not None and spy_realized_vol > 0:
        # Test B: continuous vol scaling
        raw_mult = TARGET_VOL / spy_realized_vol
        raw_mult = max(VOL_MIN_MULT, min(VOL_MAX_MULT, raw_mult))
        base = VOL_BASE_SIZE * raw_mult
        # Still respect earnings month cap
        if earnings_month and base > lib.POSITION_SIZE_EARNINGS:
            base = lib.POSITION_SIZE_EARNINGS
    else:
        # V35 baseline sizing
        base = lib.POSITION_SIZE
        try:
            vc = vix_df["Close"].squeeze()
            if today in vc.index:
                v = float(vc.loc[today])
                if v < lib.VIX_LOW:
                    base = lib.POSITION_SIZE_HIGH
        except Exception:
            pass
        if drawdown_pct <= -lib.DD_SCALE_SEVERE:
            base = min(base, lib.POSITION_SIZE_DD_SEVERE)
        elif drawdown_pct <= -lib.DD_SCALE_MILD:
            base = min(base, lib.POSITION_SIZE_DD_MILD)
        if earnings_month and base > lib.POSITION_SIZE_EARNINGS:
            base = lib.POSITION_SIZE_EARNINGS

    return min(base * multiplier, hard_cap)


# =============================================================================
# Core simulation (parameterized by test config)
# =============================================================================
def run_backtest_with_config(price_data, spy_df, vix_df, sector_data,
                              earnings_map, cfg):
    name = cfg["name"]
    print(f"\n{'='*60}")
    print(f" Running: {name}")
    print(f"  A(EquityCurve)={cfg['equity_curve_ma']} | "
          f"B(VolScale)={cfg['vol_scaled_sizing']} | "
          f"C(TurnOfMonth)={cfg['turn_of_month']}")
    print(f"{'='*60}")

    spy_regime  = spy_df["spy_ok"].to_dict()
    spy_returns = spy_df["Close"].squeeze().pct_change()

    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    trading_dates = sorted(all_dates)

    signals = {}
    min_bars = lib.MA_WINDOW + lib.VOL_MA_PERIOD + lib.ATR_PERIOD + lib.MIN_CONSEC_DOWN + 5
    for tkr, df in price_data.items():
        if len(df) > min_bars:
            signals[tkr] = _generate_signals(df)

    portfolio_value  = INITIAL_CAPITAL
    portfolio_peak   = None
    current_drawdown = 0.0
    open_positions   = {}
    trades           = []
    cooldown_map     = {}
    last_vix_spike   = None
    last_vel_crash   = None

    # Test A state: rolling equity curve
    equity_history   = deque(maxlen=EC_LOOKBACK + 5)
    equity_ma_val    = None

    # Test B state: pre-compute SPY realized vol series
    spy_vol_series = {}
    if cfg.get("vol_scaled_sizing"):
        spy_close = spy_df["Close"].squeeze()
        spy_ret   = spy_close.pct_change()
        spy_vol   = spy_ret.rolling(VOL_LOOKBACK).std() * np.sqrt(252)
        spy_vol_series = spy_vol.to_dict()

    for today in trading_dates:
        spy_ok = spy_regime.get(today, True)
        paused, last_vix_spike = _check_vix_spike(today, vix_df, last_vix_spike)

        velocity_paused = False
        try:
            if today in spy_df.index:
                spy_5d = float(spy_df.loc[today, "spy_5d_ret"])
                if not np.isnan(spy_5d) and spy_5d < lib.VELOCITY_CRASH_5D_THRESHOLD:
                    last_vel_crash = today
            if last_vel_crash is not None:
                if (pd.Timestamp(today) - pd.Timestamp(last_vel_crash)).days <= lib.VELOCITY_CRASH_PAUSE_DAYS:
                    velocity_paused = True
        except Exception:
            pass

        # Update equity curve history for Test A
        equity_history.append(portfolio_value)
        if cfg.get("equity_curve_ma") and len(equity_history) >= EC_LOOKBACK:
            equity_ma_val = np.mean(list(equity_history)[-EC_LOOKBACK:])
        else:
            equity_ma_val = None

        # Compute Test A multiplier
        def get_ec_mult():
            if not cfg.get("equity_curve_ma"):
                return 1.0
            if equity_ma_val is None:
                return 1.0
            return EC_SIZE_MULT if portfolio_value < equity_ma_val else 1.0

        # Compute Test C multiplier
        def get_tom_mult():
            if not cfg.get("turn_of_month"):
                return 1.0
            day_of_month = pd.Timestamp(today).day
            return 1.0 if day_of_month in TOM_ACTIVE_DAYS else TOM_MIDMONTH_MULT

        # Update drawdown
        if portfolio_peak is None:
            if portfolio_value != INITIAL_CAPITAL:
                portfolio_peak   = portfolio_value
                current_drawdown = 0.0
        else:
            if portfolio_value > portfolio_peak:
                portfolio_peak   = portfolio_value
                current_drawdown = 0.0
            else:
                current_drawdown = (portfolio_value - portfolio_peak) / portfolio_peak

        # ---- Exits ----
        to_close = []
        for tkr, pos in open_positions.items():
            if tkr not in signals:
                continue
            tkr_df = signals[tkr]
            if today not in tkr_df.index:
                continue
            row         = tkr_df.loc[today]
            exit_price  = float(row["Close"])
            entry_price = pos["entry_price"]
            days_held   = (pd.Timestamp(today) - pd.Timestamp(pos["entry_date"])).days
            pos_pct     = (exit_price - entry_price) / entry_price
            shares_rem  = pos["shares_remaining"]
            early       = days_held < lib.MIN_HOLD_BEFORE_EXIT
            time_stop   = days_held >= pos["hold_days"]
            profit_hit  = (not early) and pos_pct >= pos["profit_target"]

            if (pos["partial_enabled"] and not pos["partial_done"]
                    and not early and pos_pct >= pos["partial_trigger"]):
                partial_shares = shares_rem * pos["partial_frac"]
                commission     = _calc_commission(partial_shares, exit_price)
                pnl            = (exit_price - entry_price) * partial_shares - commission
                trades.append({
                    "ticker": tkr, "entry_date": pos["entry_date"], "exit_date": today,
                    "entry_price": entry_price, "exit_price": exit_price,
                    "shares": partial_shares, "commission": round(commission, 4),
                    "pnl_usd": pnl, "pnl_pct": pos_pct * 100, "days_held": days_held,
                    "exit_reason": "partial_exit", "tier": pos["tier"],
                    "consec_down": pos["consec_down_at_entry"],
                    "portfolio_val": portfolio_value + pnl,
                })
                portfolio_value         += pnl
                pos["shares_remaining"] -= partial_shares
                pos["partial_done"]      = True
                pos["profit_target"]     = pos["profit_target"] * 2
                continue

            full_exit = (
                time_stop
                or (not pos["partial_enabled"] and profit_hit)
                or (pos["partial_enabled"] and pos["partial_done"] and profit_hit)
            )
            if full_exit:
                commission = _calc_commission(shares_rem, exit_price)
                pnl        = ((exit_price - entry_price) * shares_rem
                              - commission - pos["entry_commission"])
                reason     = "time_stop" if time_stop else "profit_target"
                trades.append({
                    "ticker": tkr, "entry_date": pos["entry_date"], "exit_date": today,
                    "entry_price": entry_price, "exit_price": exit_price,
                    "shares": shares_rem,
                    "commission": round(commission + pos["entry_commission"], 4),
                    "pnl_usd": pnl, "pnl_pct": pos_pct * 100, "days_held": days_held,
                    "exit_reason": reason, "tier": pos["tier"],
                    "consec_down": pos["consec_down_at_entry"],
                    "portfolio_val": portfolio_value + pnl,
                })
                portfolio_value += pnl
                if time_stop:
                    cooldown_map[tkr] = today
                to_close.append(tkr)

        for tkr in to_close:
            del open_positions[tkr]

        if not spy_ok or paused or velocity_paused:
            continue
        if len(open_positions) >= lib.MAX_POSITIONS:
            continue

        # ---- Entries ----
        candidates = []
        for tkr, tkr_df in signals.items():
            if tkr in open_positions or today not in tkr_df.index:
                continue
            row = tkr_df.loc[today]
            if not row["signal"]:
                continue
            if tkr in cooldown_map:
                if (pd.Timestamp(today) - pd.Timestamp(cooldown_map[tkr])).days < lib.REENTRY_COOLDOWN_DAYS:
                    continue
            if _near_earnings(tkr, today, earnings_map):
                continue
            if not _sector_ok(tkr, today, sector_data):
                continue
            if _count_sector_positions(tkr, open_positions) >= lib.MAX_SECTOR_POSITIONS:
                continue
            rsi2    = float(row["rsi2"])
            atr_pct = float(row["atr_pct"])
            composite_score = rsi2 / atr_pct if atr_pct > 0 else rsi2 * 1000
            candidates.append((composite_score, tkr, int(row["consec_down"]), rsi2))

        candidates.sort(key=lambda x: x[0])
        n_candidates = len(candidates)
        top_n        = max(1, int(n_candidates * lib.TOP_SIGNAL_PCT))

        # Get realized vol for Test B
        spy_rvol = spy_vol_series.get(today, None) if cfg.get("vol_scaled_sizing") else None

        # Get Test A and C multipliers for today
        ec_mult  = get_ec_mult()
        tom_mult = get_tom_mult()

        for rank, (composite_score, tkr, consec_val, rsi_val) in enumerate(candidates):
            if len(open_positions) >= lib.MAX_POSITIONS:
                break
            tkr_df    = signals[tkr]
            today_idx = tkr_df.index.get_loc(today)
            if today_idx + 1 >= len(tkr_df):
                continue
            next_row    = tkr_df.iloc[today_idx + 1]
            entry_price = float(next_row["Open"])
            if entry_price <= 0:
                continue
            prev_close = float(tkr_df.iloc[today_idx]["Close"])
            gap_pct    = (entry_price - prev_close) / prev_close
            if gap_pct < lib.GAP_DOWN_MAX or gap_pct > lib.GAP_UP_MAX:
                continue

            tier_cfg = _get_tier(consec_val)

            # V35 top-signal multiplier
            signal_mult = 1.0
            if n_candidates >= lib.MIN_CANDIDATES_FOR_C5 and rank < top_n:
                signal_mult = lib.TOP_SIGNAL_MULTIPLIER

            # Combine all multipliers
            # Order: signal_mult (V35) * ec_mult (A) * tom_mult (C)
            # Test B modifies base size inside get_position_size_modified
            combined_mult = signal_mult * ec_mult * tom_mult

            pos_size = get_position_size_modified(
                today, vix_df, current_drawdown,
                multiplier=combined_mult,
                hard_cap=lib.TOP_SIGNAL_HARD_CAP,
                spy_realized_vol=spy_rvol,
                cfg=cfg,
            )

            shares     = (portfolio_value * pos_size) / entry_price
            entry_comm = _calc_commission(shares, entry_price)

            open_positions[tkr] = {
                "entry_date":           tkr_df.index[today_idx + 1],
                "entry_price":          entry_price,
                "shares":               shares,
                "shares_remaining":     shares,
                "rsi2_at_entry":        rsi_val,
                "consec_down_at_entry": consec_val,
                "profit_target":        tier_cfg["profit_target"],
                "hold_days":            tier_cfg["hold_days"],
                "partial_enabled":      tier_cfg["partial_enabled"],
                "partial_frac":         tier_cfg["partial_frac"],
                "partial_trigger":      tier_cfg["partial_trigger"],
                "partial_done":         False,
                "tier":                 tier_cfg["tier"],
                "entry_commission":     entry_comm,
            }

    print(f"  [{name}] Complete -- {len(trades)} trades.")
    return pd.DataFrame(trades)


# =============================================================================
# Summarize all results
# =============================================================================
def summarize(all_results):
    print("\n" + "=" * 90)
    print(" MULTI-TEST RESULTS SUMMARY")
    print("=" * 90)
    print(f"\n  {'Test':<35} {'CAGR':>8} {'Equity':>12} {'MaxDD':>8} "
          f"{'Sharpe':>8} {'WinRate':>8} {'PF':>6} {'Trades/yr':>10}")
    print(f"  {'-'*88}")

    for name, metrics in all_results.items():
        if "error" in metrics:
            print(f"  {name:<35} ERROR: {metrics['error']}")
            continue
        print(f"  {name:<35} "
              f"{metrics['cagr_pct']:>7.2f}% "
              f"${metrics['final_equity']:>11,.0f} "
              f"{metrics['max_drawdown_pct']:>7.2f}% "
              f"{metrics['sharpe_ratio']:>8.2f} "
              f"{metrics['win_rate_pct']:>7.2f}% "
              f"{metrics['profit_factor']:>6.2f} "
              f"{metrics['trades_per_year']:>10.0f}")

    print("=" * 90)
    print()
    print("  Key parameters:")
    print(f"  Test A (Equity Curve): EC_LOOKBACK={EC_LOOKBACK}d | "
          f"size_mult={EC_SIZE_MULT} when equity < {EC_LOOKBACK}d MA")
    print(f"  Test B (Vol Scaling):  TARGET_VOL={TARGET_VOL:.0%} | "
          f"BASE={VOL_BASE_SIZE:.0%} | "
          f"mult range [{VOL_MIN_MULT}-{VOL_MAX_MULT}]")
    print(f"  Test C (Turn-of-Month): full size days 1-5+26-31 | "
          f"{TOM_MIDMONTH_MULT:.0%} size days 6-25")
    print()
    print("  PASS CRITERIA vs Baseline:")
    baseline = all_results.get("Baseline_V35", {})
    b_cagr   = baseline.get("cagr_pct", 0)
    b_dd     = baseline.get("max_drawdown_pct", 0)
    for name, metrics in all_results.items():
        if name == "Baseline_V35" or "error" in metrics:
            continue
        cagr_delta = metrics["cagr_pct"] - b_cagr
        dd_delta   = metrics["max_drawdown_pct"] - b_dd
        verdict    = "PASS" if cagr_delta > -1.0 and dd_delta > -1.0 else \
                     "CAGR_FAIL" if cagr_delta <= -1.0 else "DD_WORSE"
        print(f"  {name:<35} CAGR {cagr_delta:>+6.2f}pp | "
              f"MaxDD {dd_delta:>+6.2f}pp | {verdict}")
    print("=" * 90)


# =============================================================================
# Main
# =============================================================================
if __name__ == "__main__":
    print("\n[Setup] Loading universe and market data (shared across all tests)...")
    universe     = get_universe()
    price_data   = download_prices(universe)
    spy_df, vix_df, sector_data = download_reference_data()
    earnings_map = build_earnings_dates(list(price_data.keys()))
    print(f"[Setup] Ready. Running {len(TESTS)} tests.\n")

    all_results  = {}
    all_trades   = {}

    for cfg in TESTS:
        name      = cfg["name"]
        trades_df = run_backtest_with_config(
            price_data, spy_df, vix_df, sector_data, earnings_map, cfg
        )
        all_trades[name] = trades_df

        if trades_df.empty:
            print(f"  [{name}] No trades generated.")
            all_results[name] = {"error": "No trades"}
            continue

        metrics, eq_df = compute_metrics(trades_df)
        all_results[name] = metrics

        # Save per-test outputs
        test_dir = OUTPUT_DIR / name
        test_dir.mkdir(exist_ok=True)
        trades_df.to_csv(test_dir / "trades.csv", index=False)
        eq_df.to_csv(test_dir / "equity_curve.csv", index=False)
        with open(test_dir / "metrics.json", "w") as f:
            json.dump(metrics, f, indent=2, default=str)

        print(f"  [{name}] CAGR: {metrics['cagr_pct']:.2f}% | "
              f"Equity: ${metrics['final_equity']:,.0f} | "
              f"MaxDD: {metrics['max_drawdown_pct']:.2f}% | "
              f"Sharpe: {metrics['sharpe_ratio']:.2f}")

    # Save combined summary
    with open(OUTPUT_DIR / "summary.json", "w") as f:
        json.dump(all_results, f, indent=2, default=str)

    summarize(all_results)
    print(f"\n  All results saved to: {OUTPUT_DIR.resolve()}/")
    print(f"  Per-test folders: " + ", ".join(cfg["name"] for cfg in TESTS))
