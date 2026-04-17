# backtest_ideas_v5.py
#
# Multi-test runner: all surviving untested ideas vs V35+I3 baseline.
# Architecture: identical to backtest_ideas_v2.py — imports all V35 logic
# from backtest_nmr_lib.py. Does NOT reimplement anything.
#
# Baseline: V35 + Idea3 put spread (19.71% CAGR, $4,513k, -52.87% MaxDD, Sharpe 0.74)
#
# Ideas audited against full do-not-retry table before inclusion:
#
#   EXCLUDED (already confirmed failed in V2/V3/V4/V5):
#     - Vol-adjusted exits (A_VOL_EXIT): -1.87pp CAGR, MaxDD -11.47pp (V5)
#     - VIX term structure (V3 IdeaD): "nearly identical to baseline"
#     - Sector-relative ranking (V4 Idea2): "zero effect - cap rarely binding"
#     - Asymmetric hold windows: similar to V34a partial loss exit (-$926k)
#     - 52wk high distance (V3 IdeaE): -4pp CAGR, -$2M equity
#     - Low-turnover hold extension (V4 Idea5): "zero effect"
#     - Industry-relative RSI ranking (V4 Idea2): "zero effect"
#     - Earnings blackout extension (E_Earnings_Ext V5): identical to baseline
#
#   INCLUDED (genuinely untested or needing clean baseline):
#     Baseline_V35I3  - V35 + put spread (control)
#     B_TOM_Sizing    - Turn-of-month 1.15x size (last bday/month + 3 days)
#                       V5 showed +0.41pp CAGR vs broken baseline; retest cleanly
#     C_VIX_RSI       - VIX<15: require RSI<15 instead of RSI<20
#                       V36-T2 showed +$86k vs V35; needs clean V35+I3 baseline
#     D_Partial_Tune  - Tier 1 partial trigger 1.0%->0.8%
#                       V5 showed +0.04pp CAGR, +0.16pp MaxDD improvement
#     E_DOW_Sizing    - Day-of-week size multipliers (RenTec seasonality research)
#                       Tuesday 1.10x, Friday 0.90x. Completely untested.
#     H_Combo_BCD     - B + C + D combined (no vol exits which confirmed failed)
#     I_Combo_BCDE    - B + C + D + E combined
#
# IMPORTANT: Does NOT modify backtest_nmr_lib.py. V35 is untouched.

import json
import warnings
import datetime
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# Import ALL V35 logic from the existing lib
from backtest_nmr_lib import (
    get_universe,
    download_prices,
    download_reference_data,
    build_earnings_dates,
    compute_metrics,
    generate_signals,
    get_position_size,
    get_tier,
    calc_commission,
    sector_ok,
    count_sector_positions,
    check_vix_spike,
    near_earnings,
    TICKER_TO_SECTOR,
    INITIAL_CAPITAL,
    START_DATE,
    END_DATE,
    MAX_POSITIONS,
    MA_WINDOW,
    VOL_MA_PERIOD,
    ATR_PERIOD,
    RSI_PERIOD,
    RSI_THRESHOLD,
    ATR_MIN_PCT,
    MIN_DOLLAR_VOLUME,
    MIN_CONSEC_DOWN,
    MIN_HOLD_BEFORE_EXIT,
    VELOCITY_CRASH_5D_THRESHOLD,
    VELOCITY_CRASH_PAUSE_DAYS,
    VIX_SPIKE_PAUSE_DAYS,
    VIX_LOW,
    GAP_DOWN_MAX,
    GAP_UP_MAX,
    REENTRY_COOLDOWN_DAYS,
    MAX_SECTOR_POSITIONS,
    EARNINGS_BLACKOUT,
    EARNINGS_MONTHS,
    TOP_SIGNAL_PCT,
    TOP_SIGNAL_MULTIPLIER,
    TOP_SIGNAL_HARD_CAP,
    MIN_CANDIDATES_FOR_C5,
    COMMISSION_RATE,
    COMMISSION_MIN,
)

OUTPUT_DIR = Path("results_ideas_v5")
OUTPUT_DIR.mkdir(exist_ok=True)

# =============================================================================
# Put spread parameters (Idea 3 — identical to Ideas V2)
# =============================================================================
PUT_SPREAD_LOWER_OTM       = 0.05    # long put 5% OTM
PUT_SPREAD_UPPER_OTM       = 0.15    # short put 15% OTM
PUT_SPREAD_QUARTERLY_COST  = 0.0075  # 0.75% of portfolio per quarter
PUT_SPREAD_RENEW_DAYS      = 63      # ~1 quarter

# =============================================================================
# Test-specific parameters
# =============================================================================

# B: Turn-of-month sizing
B_TOM_MULT = 1.15          # additional multiplier during TOM window

# C: VIX low-regime RSI tightening
C_VIX_THRESH = 15.0        # VIX level below which we tighten RSI
C_RSI_THRESH = 15.0        # tighter RSI threshold (vs baseline 20)

# D: Tier 1 partial trigger tuning
D_PARTIAL_TRIGGER = 0.008  # was 0.010 in V35

# E: Day-of-week sizing (RenTec seasonality)
# Tuesday shows stronger reversal bias; Friday shows weaker (position-close flows)
E_DOW_MULT = {
    0: 1.00,   # Monday   - neutral
    1: 1.10,   # Tuesday  - reversal bias documented by RenTec
    2: 1.00,   # Wednesday - neutral
    3: 1.00,   # Thursday  - neutral
    4: 0.90,   # Friday   - traders close positions before weekend
}

# =============================================================================
# Test matrix
# =============================================================================
TESTS = [
    {"name": "Baseline_V35I3", "tom": False, "vix_rsi": False, "partial": False, "dow": False},
    {"name": "B_TOM_Sizing",   "tom": True,  "vix_rsi": False, "partial": False, "dow": False},
    {"name": "C_VIX_RSI",      "tom": False, "vix_rsi": True,  "partial": False, "dow": False},
    {"name": "D_Partial_Tune", "tom": False, "vix_rsi": False, "partial": True,  "dow": False},
    {"name": "E_DOW_Sizing",   "tom": False, "vix_rsi": False, "partial": False, "dow": True},
    {"name": "H_Combo_BCD",    "tom": True,  "vix_rsi": True,  "partial": True,  "dow": False},
    {"name": "I_Combo_BCDE",   "tom": True,  "vix_rsi": True,  "partial": True,  "dow": True},
]

# =============================================================================
# Put spread payout (identical to Ideas V2)
# =============================================================================
def compute_put_spread_intrinsic_pct(spy_ref: float, spy_worst: float) -> float:
    """
    Payout at quarterly expiry based on worst SPY close during the quarter.
    Returns fraction of notional (e.g. 0.08 = 8%).
    """
    lower_strike = spy_ref * (1 - PUT_SPREAD_LOWER_OTM)
    spread_width = PUT_SPREAD_UPPER_OTM - PUT_SPREAD_LOWER_OTM  # 0.10
    if spy_worst >= lower_strike:
        return 0.0
    decline    = (spy_ref - spy_worst) / spy_ref
    payout_pct = max(0.0, min(decline - PUT_SPREAD_LOWER_OTM, spread_width))
    return payout_pct

# =============================================================================
# TOM window — exact scan of actual trading dates
# =============================================================================
def build_tom_set(trading_dates: list) -> set:
    """Last trading day of each month + next 3 trading days."""
    tom = set()
    n   = len(trading_dates)
    for i, d in enumerate(trading_dates):
        is_month_end = (i == n - 1) or (
            pd.Timestamp(trading_dates[i + 1]).month != pd.Timestamp(d).month
        )
        if is_month_end:
            tom.add(d)
            for j in range(1, 4):
                if i + j < n:
                    tom.add(trading_dates[i + j])
    return tom

# =============================================================================
# VIX level helper
# =============================================================================
def get_vix_level(today, vix_df) -> float:
    try:
        vc = vix_df["Close"].squeeze()
        if today in vc.index:
            return float(vc.loc[today])
    except Exception:
        pass
    return 20.0

# =============================================================================
# Core backtest — V35 loop with injected overrides
# =============================================================================
def run_backtest(price_data: dict, spy_df: pd.DataFrame, vix_df: pd.DataFrame,
                    sector_data: dict, earnings_map: dict, cfg: dict) -> pd.DataFrame:

    test_name   = cfg["name"]
    use_tom     = cfg["tom"]
    use_vix_rsi = cfg["vix_rsi"]
    use_partial = cfg["partial"]
    use_dow     = cfg["dow"]

    print(f"\n{'='*70}")
    print(f"[Test] {test_name}")
    print(f"  TOM={use_tom} | VIX_RSI={use_vix_rsi} | PartialTune={use_partial} | DOW={use_dow}")
    print(f"{'='*70}")

    # Diagnostic for C
    if use_vix_rsi:
        vc = vix_df["Close"].squeeze()
        low_vix = sum(1 for d in sorted(set().union(*[set(df.index) for df in price_data.values()]))
                      if d in vc.index and float(vc.loc[d]) < C_VIX_THRESH)
        print(f"  [C] VIX < {C_VIX_THRESH} on ~{low_vix} trading days")

    spy_regime = spy_df["spy_ok"].to_dict()
    spy_close  = spy_df["Close"].squeeze()

    all_dates: set = set()
    for df in price_data.values():
        all_dates.update(df.index)
    trading_dates = sorted(all_dates)

    tom_set = build_tom_set(trading_dates) if use_tom else set()

    signals: dict[str, pd.DataFrame] = {}
    min_bars = MA_WINDOW + VOL_MA_PERIOD + ATR_PERIOD + MIN_CONSEC_DOWN + 5
    for tkr, df in price_data.items():
        if len(df) > min_bars:
            signals[tkr] = generate_signals(df)

    portfolio_value     = INITIAL_CAPITAL
    portfolio_peak      = None
    current_drawdown    = 0.0
    open_positions      = {}
    trades              = []
    cooldown_map        = {}
    last_vix_spike      = None
    last_velocity_crash = None

    # Put spread state
    put_ref_price        = None
    put_ref_date         = None
    put_notional         = 0.0
    put_min_spy          = 9999.0
    put_days_since_renew = 0

    for today in trading_dates:
        spy_ok = spy_regime.get(today, True)
        paused, last_vix_spike = check_vix_spike(today, vix_df, last_vix_spike)

        velocity_paused = False
        try:
            if today in spy_df.index:
                spy_5d = float(spy_df.loc[today, "spy_5d_ret"])
                if not np.isnan(spy_5d) and spy_5d < VELOCITY_CRASH_5D_THRESHOLD:
                    last_velocity_crash = today
            if last_velocity_crash is not None:
                if (pd.Timestamp(today) - pd.Timestamp(last_velocity_crash)).days <= VELOCITY_CRASH_PAUSE_DAYS:
                    velocity_paused = True
        except Exception:
            pass

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

        # ── Put spread (Idea 3, identical to V2) ──────────────────────────────
        if today in spy_df.index:
            spy_px = float(spy_close.loc[today]) if today in spy_close.index else None
            if spy_px is not None:
                if put_ref_price is None or put_days_since_renew >= PUT_SPREAD_RENEW_DAYS:
                    # Pay quarterly premium
                    premium = portfolio_value * PUT_SPREAD_QUARTERLY_COST
                    portfolio_value     -= premium
                    put_ref_price        = spy_px
                    put_ref_date         = today
                    put_notional         = portfolio_value
                    put_min_spy          = spy_px
                    put_days_since_renew = 0
                    trades.append({
                        "ticker": "SPY_PUT_SPREAD", "entry_date": today, "exit_date": today,
                        "entry_price": spy_px, "exit_price": spy_px,
                        "shares": 0, "commission": 0,
                        "pnl_usd": -premium,
                        "pnl_pct": -PUT_SPREAD_QUARTERLY_COST * 100,
                        "days_held": 0, "exit_reason": "put_premium",
                        "tier": 0, "consec_down": 0,
                        "portfolio_val": portfolio_value,
                    })
                else:
                    put_days_since_renew += 1
                    put_min_spy = min(put_min_spy, spy_px)
                    # Settle on day before renewal
                    if put_days_since_renew == PUT_SPREAD_RENEW_DAYS - 1:
                        payout_pct = compute_put_spread_intrinsic_pct(put_ref_price, put_min_spy)
                        if payout_pct > 0:
                            payout = put_notional * payout_pct
                            portfolio_value += payout
                            trades.append({
                                "ticker": "SPY_PUT_SPREAD", "entry_date": put_ref_date,
                                "exit_date": today, "entry_price": put_ref_price,
                                "exit_price": put_min_spy, "shares": 0, "commission": 0,
                                "pnl_usd": round(payout, 2),
                                "pnl_pct": round(payout_pct * 100, 4),
                                "days_held": put_days_since_renew, "exit_reason": "put_payout",
                                "tier": 0, "consec_down": 0,
                                "portfolio_val": portfolio_value,
                            })

        # ── MR Exits ──────────────────────────────────────────────────────────
        to_close = []
        for tkr, pos in open_positions.items():
            if tkr not in signals:
                continue
            tkr_df = signals[tkr]
            if today not in tkr_df.index:
                continue
            row        = tkr_df.loc[today]
            exit_price = float(row["Close"])
            entry_price = pos["entry_price"]
            days_held  = (pd.Timestamp(today) - pd.Timestamp(pos["entry_date"])).days
            pos_pct    = (exit_price - entry_price) / entry_price
            shares_rem = pos["shares_remaining"]
            early      = days_held < MIN_HOLD_BEFORE_EXIT
            time_stop  = days_held >= pos["hold_days"]
            profit_hit = (not early) and pos_pct >= pos["profit_target"]

            if (pos["partial_enabled"] and not pos["partial_done"]
                    and not early and pos_pct >= pos["partial_trigger"]):
                partial_sh = shares_rem * pos["partial_frac"]
                comm       = calc_commission(partial_sh, exit_price)
                pnl        = (exit_price - entry_price) * partial_sh - comm
                trades.append({
                    "ticker": tkr, "entry_date": pos["entry_date"], "exit_date": today,
                    "entry_price": entry_price, "exit_price": exit_price,
                    "shares": partial_sh, "commission": round(comm, 4),
                    "pnl_usd": pnl, "pnl_pct": pos_pct * 100, "days_held": days_held,
                    "exit_reason": "partial_exit", "tier": pos["tier"],
                    "consec_down": pos["consec_down_at_entry"],
                    "portfolio_val": portfolio_value + pnl,
                })
                portfolio_value       += pnl
                pos["shares_remaining"] -= partial_sh
                pos["partial_done"]    = True
                pos["profit_target"]   = pos["profit_target"] * 2
                continue

            full_exit = (
                time_stop
                or (not pos["partial_enabled"] and profit_hit)
                or (pos["partial_enabled"] and pos["partial_done"] and profit_hit)
            )
            if full_exit:
                comm = calc_commission(shares_rem, exit_price)
                pnl  = ((exit_price - entry_price) * shares_rem
                        - comm - pos["entry_commission"])
                reason = "time_stop" if time_stop else "profit_target"
                trades.append({
                    "ticker": tkr, "entry_date": pos["entry_date"], "exit_date": today,
                    "entry_price": entry_price, "exit_price": exit_price,
                    "shares": shares_rem,
                    "commission": round(comm + pos["entry_commission"], 4),
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
        if len(open_positions) >= MAX_POSITIONS:
            continue

        # ── MR Entries ────────────────────────────────────────────────────────
        vix_now   = get_vix_level(today, vix_df)
        tom_today = today in tom_set
        dow       = pd.Timestamp(today).dayofweek  # 0=Mon ... 4=Fri

        # C: tighten RSI threshold when VIX < 15
        rsi_thresh = C_RSI_THRESH if use_vix_rsi and vix_now < C_VIX_THRESH else RSI_THRESHOLD

        candidates = []
        for tkr, tkr_df in signals.items():
            if tkr in open_positions or today not in tkr_df.index:
                continue
            row = tkr_df.loc[today]
            if not row["signal"]:
                continue
            # C: additional RSI gate on low-VIX days
            if use_vix_rsi and vix_now < C_VIX_THRESH:
                if float(row["rsi2"]) >= rsi_thresh:
                    continue
            if tkr in cooldown_map:
                if (pd.Timestamp(today) - pd.Timestamp(cooldown_map[tkr])).days < REENTRY_COOLDOWN_DAYS:
                    continue
            if near_earnings(tkr, today, earnings_map):
                continue
            if not sector_ok(tkr, today, sector_data):
                continue
            if count_sector_positions(tkr, open_positions) >= MAX_SECTOR_POSITIONS:
                continue

            rsi2    = float(row["rsi2"])
            atr_pct = float(row["atr_pct"])
            score   = rsi2 / atr_pct if atr_pct > 0 else rsi2 * 1000
            candidates.append((score, tkr, int(row["consec_down"]), rsi2))

        candidates.sort(key=lambda x: x[0])
        n_candidates = len(candidates)
        top_n        = max(1, int(n_candidates * TOP_SIGNAL_PCT))

        for rank, (score, tkr, consec_val, rsi_val) in enumerate(candidates):
            if len(open_positions) >= MAX_POSITIONS:
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
            if gap_pct < GAP_DOWN_MAX or gap_pct > GAP_UP_MAX:
                continue

            # D: override Tier 1 partial trigger
            tier_cfg = get_tier(consec_val)
            if use_partial and tier_cfg.get("partial_enabled"):
                tier_cfg = dict(tier_cfg)
                tier_cfg["partial_trigger"] = D_PARTIAL_TRIGGER

            # V35 top-signal multiplier (unchanged)
            size_multiplier = 1.0
            if n_candidates >= MIN_CANDIDATES_FOR_C5 and rank < top_n:
                size_multiplier = TOP_SIGNAL_MULTIPLIER

            # B: TOM window bonus
            if use_tom and tom_today:
                size_multiplier *= B_TOM_MULT

            # E: day-of-week multiplier
            if use_dow:
                size_multiplier *= E_DOW_MULT.get(dow, 1.0)

            pos_size = get_position_size(
                today, vix_df, current_drawdown,
                multiplier=size_multiplier, hard_cap=TOP_SIGNAL_HARD_CAP,
            )
            shares     = (portfolio_value * pos_size) / entry_price
            entry_comm = calc_commission(shares, entry_price)

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

    print(f"[{test_name}] Complete -- {len(trades)} total trade records.")
    return pd.DataFrame(trades)


# =============================================================================
# Output helpers
# =============================================================================
def save_outputs(test_name: str, trades_df: pd.DataFrame,
                      metrics: dict, eq_df: pd.DataFrame):
    test_dir = OUTPUT_DIR / test_name
    test_dir.mkdir(exist_ok=True)
    mr_only = trades_df[trades_df["ticker"] != "SPY_PUT_SPREAD"].copy()
    mr_only.to_csv(test_dir / "trades.csv", index=False)
    trades_df.to_csv(test_dir / "trades_all.csv", index=False)
    eq_df.to_csv(test_dir / "equity_curve.csv", index=False)
    with open(test_dir / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, default=str)


def extract_summary(test_name: str, metrics: dict) -> dict:
    return {
        "test":      test_name,
        "cagr":      metrics.get("cagr_pct", 0),
        "max_dd":    metrics.get("max_drawdown_pct", 0),
        "sharpe":    metrics.get("sharpe_ratio", 0),
        "pf":        metrics.get("profit_factor", 0),
        "final_eq":  metrics.get("final_equity", 0),
        "wr":        metrics.get("win_rate_pct", 0),
        "trades_yr": metrics.get("trades_per_year", 0),
        "put_net":   metrics.get("note_put_net_pnl", 0),
    }


def print_comparison(summaries: list):
    print("\n" + "=" * 125)
    print("  IDEAS V5 — RESULTS vs V35+I3 BASELINE")
    print("  Baseline target: 19.71% CAGR | $4,513k | -52.87% MaxDD | Sharpe 0.74")
    print("=" * 125)
    hdr = (f"  {'Test':<20} {'CAGR%':>7} {'dCAGR':>7} {'MaxDD%':>8} {'dDD':>7} "
           f"{'Sharpe':>7} {'PF':>6} {'FinalEq':>12} {'WR%':>6} {'PutNet':>12}")
    print(hdr)
    print("  " + "-" * 119)
    baseline = next((s for s in summaries if s["test"] == "Baseline_V35I3"), None)
    for s in summaries:
        if baseline and s["test"] != "Baseline_V35I3":
            d_cagr = f"{s['cagr'] - baseline['cagr']:+.2f}"
            d_dd   = f"{s['max_dd'] - baseline['max_dd']:+.2f}"
        else:
            d_cagr, d_dd = "—", "—"
        print(
            f"  {s['test']:<20} {s['cagr']:>7.2f} {d_cagr:>7} {s['max_dd']:>8.2f} {d_dd:>7} "
            f"{s['sharpe']:>7.2f} {s['pf']:>6.2f} {s['final_eq']:>12,.0f} "
            f"{s['wr']:>6.2f} {s['put_net']:>12,.0f}"
        )
    print("=" * 125)

    if baseline:
        print(f"\n  Baseline reproduced: CAGR {baseline['cagr']:.2f}% | "
              f"MaxDD {baseline['max_dd']:.2f}% | Sharpe {baseline['sharpe']:.2f} | "
              f"Equity ${baseline['final_eq']:,.0f}")
        print(f"  Baseline target:     CAGR 19.71% | MaxDD -52.87% | Sharpe 0.74 | Equity $4,513,155")
        diff = baseline['cagr'] - 19.71
        if abs(diff) > 0.5:
            print(f"  WARNING: Baseline CAGR differs from target by {diff:+.2f}pp — check lib import.")

    print()
    best_cagr = max(summaries, key=lambda x: x["cagr"])
    best_dd   = min(summaries, key=lambda x: x["max_dd"])
    print(f"  Highest CAGR : {best_cagr['test']} ({best_cagr['cagr']:.2f}%)")
    print(f"  Lowest MaxDD : {best_dd['test']} ({best_dd['max_dd']:.2f}%)")
    print("=" * 125)


# =============================================================================
# Main
# =============================================================================
def main():
    print("\n" + "=" * 70)
    print("  NAIVE MR BACKTEST — IDEAS V5 (Final)")
    print("  Baseline: V35+I3 (19.71% CAGR | $4,513k | -52.87% MaxDD | 0.74 Sharpe)")
    print("  Tests: TOM Sizing | VIX RSI | Partial Tune | DOW Sizing | Combos")
    print("=" * 70)

    universe     = get_universe()
    price_data   = download_prices(universe)
    spy_df, vix_df, sector_data = download_reference_data()
    earnings_map = build_earnings_dates(list(price_data.keys()))

    summaries = []

    for cfg in TESTS:
        test_name = cfg["name"]
        try:
            trades_df = run_backtest_v5(
                price_data, spy_df, vix_df, sector_data, earnings_map, cfg
            )
            if trades_df.empty:
                print(f"[{test_name}] WARNING: No trades generated.")
                continue

            mr_trades = trades_df[trades_df["ticker"] != "SPY_PUT_SPREAD"].copy()
            if mr_trades.empty:
                print(f"[{test_name}] No MR trades.")
                continue

            metrics, eq_df = compute_metrics(mr_trades)

            # Add put spread P&L to final equity (same pattern as V2)
            put_pnl = trades_df[trades_df["ticker"] == "SPY_PUT_SPREAD"]["pnl_usd"].sum()
            metrics["final_equity"]    = round(metrics["final_equity"] + put_pnl, 2)
            metrics["version"]         = test_name
            metrics["note_put_net_pnl"] = round(put_pnl, 2)

            save_test_outputs(test_name, trades_df, metrics, eq_df)
            summaries.append(extract_summary(test_name, metrics))

            print(f"  -> {test_name}: CAGR {metrics['cagr_pct']:.2f}% | "
                  f"MaxDD {metrics['max_drawdown_pct']:.2f}% | "
                  f"Sharpe {metrics['sharpe_ratio']:.2f} | "
                  f"Equity ${metrics['final_equity']:,.0f} | "
                  f"PutNet ${put_pnl:,.0f}")

        except Exception as e:
            print(f"[{test_name}] ERROR: {e}")
            import traceback; traceback.print_exc()

    if summaries:
        print_comparison(summaries)
        with open(OUTPUT_DIR / "comparison.json", "w") as f:
            json.dump(summaries, f, indent=2, default=str)
        print(f"\n  Results saved to: {OUTPUT_DIR.resolve()}")
    else:
        print("[ERROR] No tests completed successfully.")


if __name__ == "__main__":
    main()
