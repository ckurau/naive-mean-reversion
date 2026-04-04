""" Enhanced Naive Mean Reversion (MR) Backtest — V31
==================================================
Base: V30+S&P600 — $2,414,283 final equity, 16.01% CAGR.

V31 CHANGES (3 additions, targeting PF / Sharpe / DD improvements):

[V31-1] VIX TREND REGIME FILTER
  Only enter when VIX is ABOVE its 10-day moving average.
  Rationale: VIX rising = volatility expanding = mean reversion conditions
  improving. VIX falling into calm = momentum/trend regime = MR edge weakens.
  This directly targets the 2021-22 failure window where VIX was elevated but
  falling, indicating a regime shift rather than a true MR environment.
  Expected effect: Fewer trades in low-quality regime periods → higher PF,
  better Sharpe. Possible small CAGR reduction from lost volume.

[V31-2] MODEST DRAWDOWN SIZE REDUCTION
  If portfolio drawdown exceeds 20%, reduce position size by 30%.
  (e.g. 9% → 6.3%, 5% → 3.5%)
  Rationale: Not the old circuit breaker (which fired at 10% and blocked all
  trading permanently). This is a single-step size reduction at a high
  threshold — trading continues but at lower risk during deep drawdowns.
  Only fires in severe drawdown periods (2022-style). Resets when new equity
  peak is reached.
  Expected effect: Reduced max drawdown, slightly lower CAGR in bad years.

[V31-3] HIGHER DOLLAR VOLUME FLOOR FOR SMALL-CAPS
  MIN_DOLLAR_VOLUME raised from $5M to $10M.
  Rationale: S&P 600 small-caps with $5-10M/day dollar volume have wide
  bid-ask spreads and poor MOO fill quality. Raising the floor removes the
  worst execution-quality names. The critique correctly identifies this as
  the most likely source of real-world slippage degradation.
  Expected effect: Fewer trades (mainly small-cap Tier 3), higher PF from
  better fill quality, slightly lower CAGR from lost volume.

CODE UNIFICATION [V31-4]:
  backtest-nmr.py now imports shared functions from backtest_nmr_lib.py
  instead of duplicating them. Single source of truth for all logic.
  universe fetch, downloads, signal generation, and simulation all live
  in backtest_nmr_lib.py and are imported here.

RESULTS HISTORY:
  Run 5:     CAGR  7.58% | $478k
  V30:       CAGR 14.42% | $1,797k  (S&P 500+400)
  V30+S&P600 CAGR 16.01% | $2,414k  ← baseline for V31
  V31 target: improved PF (>1.10), Sharpe (>0.75), DD (<-42%) with
              minimal CAGR sacrifice
"""

# V31 imports all shared logic from backtest_nmr_lib.py
# Only V31-specific parameter overrides are defined here.
from backtest_nmr_lib import (
    get_universe, download_prices, download_reference_data,
    build_earnings_dates, run_backtest, compute_metrics, save_outputs,
    INITIAL_CAPITAL, START_DATE, END_DATE,
)
import backtest_nmr_lib as _lib
import json
from pathlib import Path

# ── V31 parameter overrides (applied by patching the lib module) ─────────────

# [V31-3] Higher dollar volume floor — filters worst fill-quality small-caps
_lib.MIN_DOLLAR_VOLUME = 10_000_000   # was 5_000_000

# [V31-2] Modest DD scaling — fires at 20% DD, reduces size 30%
# Set thresholds to realistic values (replaces the unreachable 9.99)
_lib.DD_SCALE_MILD   = 0.20           # 20% portfolio drawdown triggers mild scaling
_lib.DD_SCALE_SEVERE = 9.99           # severe tier kept unreachable (one-step only)
_lib.POSITION_SIZE_DD_MILD = 0.063    # 30% reduction: 9% → 6.3% (VIX<25 regime)
# Note: base POSITION_SIZE (5%) → 3.5% under DD, handled proportionally in get_position_size

# [V31-1] VIX trend filter — added in download_reference_data and run_backtest below
VIX_TREND_MA = 10   # VIX must be above its 10-day MA to allow entries

# ── Override get_position_size to handle proportional DD reduction ────────────
import numpy as np
import pandas as pd

_orig_get_position_size = _lib.get_position_size

def _v31_get_position_size(today, vix_df, drawdown_pct: float = 0.0) -> float:
    """V31: adds proportional 30% size reduction when DD > 20%."""
    base = _orig_get_position_size(today, vix_df, 0.0)  # get base without DD
    month = pd.Timestamp(today).month
    # Re-apply earnings month cap (already in orig, but we bypassed DD path)
    if month in _lib.EARNINGS_MONTHS and base > _lib.POSITION_SIZE_EARNINGS:
        base = _lib.POSITION_SIZE_EARNINGS
    # [V31-2] Modest DD reduction — 30% size cut at 20% drawdown
    if drawdown_pct <= -_lib.DD_SCALE_MILD:
        base = base * 0.70   # proportional 30% reduction regardless of VIX regime
    return base

_lib.get_position_size = _v31_get_position_size


# ── Override download_reference_data to add VIX MA calculation ───────────────
import yfinance as yf
import warnings
warnings.filterwarnings("ignore")

_orig_download_reference_data = _lib.download_reference_data

def _v31_download_reference_data() -> tuple:
    """V31: adds VIX 10-day MA trend column for regime filter."""
    spy, vix, sector_data = _orig_download_reference_data()
    # [V31-1] Add VIX trend column
    vix_close = vix["Close"].squeeze()
    vix["vix_ma10"] = vix_close.rolling(VIX_TREND_MA).mean()
    vix["vix_trending_up"] = vix_close > vix["vix_ma10"]
    print(f"[V31] VIX trend filter: entries only when VIX > {VIX_TREND_MA}-day MA")
    return spy, vix, sector_data

_lib.download_reference_data = _v31_download_reference_data


# ── Override run_backtest to apply VIX trend filter in entry logic ────────────
_orig_run_backtest = _lib.run_backtest

def _v31_run_backtest(price_data, spy_df, vix_df, sector_data, earnings_map) -> pd.DataFrame:
    """V31: injects VIX trend regime check before entry generation."""
    print("\n[Backtest] Running V31 simulation (V30+S&P600 + regime filter + DD scaling + $10M floor) ...")

    spy_regime = spy_df["spy_ok"].to_dict()

    # Build VIX trend lookup
    vix_trend_ok = {}
    if "vix_trending_up" in vix_df.columns:
        vix_trend_ok = vix_df["vix_trending_up"].to_dict()

    all_dates: set = set()
    for df in price_data.values():
        all_dates.update(df.index)
    trading_dates = sorted(all_dates)

    signals: dict[str, pd.DataFrame] = {}
    min_bars = _lib.MA_WINDOW + _lib.VOL_MA_PERIOD + _lib.ATR_PERIOD + _lib.MIN_CONSEC_DOWN + 5
    from tqdm import tqdm
    for tkr, df in tqdm(price_data.items(), desc="Generating signals"):
        if len(df) > min_bars:
            signals[tkr] = _lib.generate_signals(df)

    portfolio_value = _lib.INITIAL_CAPITAL
    portfolio_peak = None
    current_drawdown = 0.0
    open_positions: dict[str, dict] = {}
    trades: list[dict] = []
    cooldown_map: dict = {}
    last_vix_spike = None
    last_velocity_crash = None

    vix_blocked_days = 0
    dd_scaled_days = 0

    for today in tqdm(trading_dates, desc="Simulating"):
        spy_ok = spy_regime.get(today, True)
        paused, last_vix_spike = _lib.check_vix_spike(today, vix_df, last_vix_spike)

        velocity_paused = False
        try:
            if today in spy_df.index:
                spy_5d = float(spy_df.loc[today, "spy_5d_ret"])
                if not np.isnan(spy_5d) and spy_5d < _lib.VELOCITY_CRASH_5D_THRESHOLD:
                    last_velocity_crash = today
            if last_velocity_crash is not None:
                days_since = (pd.Timestamp(today) - pd.Timestamp(last_velocity_crash)).days
                if days_since <= _lib.VELOCITY_CRASH_PAUSE_DAYS:
                    velocity_paused = True
        except Exception:
            pass

        # [V31-1] VIX trend regime filter
        vix_regime_ok = vix_trend_ok.get(today, True)  # default True if no data
        if not vix_regime_ok:
            vix_blocked_days += 1

        # Drawdown tracking
        if portfolio_peak is None:
            if portfolio_value != _lib.INITIAL_CAPITAL:
                portfolio_peak = portfolio_value
                current_drawdown = 0.0
        else:
            if portfolio_value > portfolio_peak:
                portfolio_peak = portfolio_value
                current_drawdown = 0.0
            else:
                current_drawdown = (portfolio_value - portfolio_peak) / portfolio_peak

        if current_drawdown <= -_lib.DD_SCALE_MILD:
            dd_scaled_days += 1

        # ── Exits (unchanged) ──────────────────────────────────────────────
        to_close = []
        for tkr, pos in open_positions.items():
            if tkr not in signals:
                continue
            tkr_df = signals[tkr]
            if today not in tkr_df.index:
                continue
            row = tkr_df.loc[today]
            exit_price = float(row["Close"])
            entry_price = pos["entry_price"]
            days_held = (pd.Timestamp(today) - pd.Timestamp(pos["entry_date"])).days
            pos_pct = (exit_price - entry_price) / entry_price
            shares_rem = pos["shares_remaining"]
            early = days_held < _lib.MIN_HOLD_BEFORE_EXIT
            time_stop = days_held >= pos["hold_days"]
            profit_hit = (not early) and pos_pct >= pos["profit_target"]

            if (pos["partial_enabled"] and not pos["partial_done"]
                    and not early and pos_pct >= pos["partial_trigger"]):
                partial_shares = shares_rem * pos["partial_frac"]
                commission = _lib.calc_commission(partial_shares, exit_price)
                pnl = (exit_price - entry_price) * partial_shares - commission
                trades.append({
                    "ticker": tkr, "entry_date": pos["entry_date"], "exit_date": today,
                    "entry_price": entry_price, "exit_price": exit_price,
                    "shares": partial_shares, "commission": round(commission, 4),
                    "pnl_usd": pnl, "pnl_pct": pos_pct * 100, "days_held": days_held,
                    "exit_reason": "partial_exit", "tier": pos["tier"],
                    "consec_down": pos["consec_down_at_entry"],
                    "portfolio_val": portfolio_value + pnl,
                })
                portfolio_value += pnl
                pos["shares_remaining"] -= partial_shares
                pos["partial_done"] = True
                pos["profit_target"] = pos["profit_target"] * 2
                continue

            full_exit = (
                time_stop
                or (not pos["partial_enabled"] and profit_hit)
                or (pos["partial_enabled"] and pos["partial_done"] and profit_hit)
            )
            if full_exit:
                commission = _lib.calc_commission(shares_rem, exit_price)
                pnl = ((exit_price - entry_price) * shares_rem
                       - commission - pos["entry_commission"])
                reason = "time_stop" if time_stop else "profit_target"
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

        # [V31-1] Block entries when VIX is in downtrend (falling volatility)
        if not spy_ok or paused or velocity_paused or not vix_regime_ok:
            continue
        if len(open_positions) >= _lib.MAX_POSITIONS:
            continue

        # ── Entries ────────────────────────────────────────────────────────
        candidates = []
        for tkr, tkr_df in signals.items():
            if tkr in open_positions or today not in tkr_df.index:
                continue
            row = tkr_df.loc[today]
            if not row["signal"]:
                continue
            if tkr in cooldown_map:
                if (pd.Timestamp(today) - pd.Timestamp(cooldown_map[tkr])).days < _lib.REENTRY_COOLDOWN_DAYS:
                    continue
            if _lib.near_earnings(tkr, today, earnings_map):
                continue
            if not _lib.sector_ok(tkr, today, sector_data):
                continue
            if _lib.count_sector_positions(tkr, open_positions) >= _lib.MAX_SECTOR_POSITIONS:
                continue
            candidates.append((float(row["rsi2"]), tkr, int(row["consec_down"])))

        candidates.sort(key=lambda x: x[0])

        for rsi_val, tkr, consec_val in candidates:
            if len(open_positions) >= _lib.MAX_POSITIONS:
                break
            tkr_df = signals[tkr]
            today_idx = tkr_df.index.get_loc(today)
            if today_idx + 1 >= len(tkr_df):
                continue
            next_row = tkr_df.iloc[today_idx + 1]
            entry_price = float(next_row["Open"])
            if entry_price <= 0:
                continue
            prev_close = float(tkr_df.iloc[today_idx]["Close"])
            gap_pct = (entry_price - prev_close) / prev_close
            if gap_pct < _lib.GAP_DOWN_MAX or gap_pct > _lib.GAP_UP_MAX:
                continue
            tier_cfg = _lib.get_tier(consec_val)
            pos_size = _lib.get_position_size(today, vix_df, current_drawdown)
            shares = (portfolio_value * pos_size) / entry_price
            entry_comm = _lib.calc_commission(shares, entry_price)
            open_positions[tkr] = {
                "entry_date": tkr_df.index[today_idx + 1],
                "entry_price": entry_price,
                "shares": shares,
                "shares_remaining": shares,
                "rsi2_at_entry": rsi_val,
                "consec_down_at_entry": consec_val,
                "profit_target": tier_cfg["profit_target"],
                "hold_days": tier_cfg["hold_days"],
                "partial_enabled": tier_cfg["partial_enabled"],
                "partial_frac": tier_cfg["partial_frac"],
                "partial_trigger": tier_cfg["partial_trigger"],
                "partial_done": False,
                "tier": tier_cfg["tier"],
                "entry_commission": entry_comm,
            }

    total_days = len(trading_dates)
    print(f"[Backtest] Complete — {len(trades)} trades executed.")
    print(f"[V31] VIX trend blocked entries on {vix_blocked_days} days "
          f"({vix_blocked_days/total_days*100:.1f}% of trading days)")
    print(f"[V31] DD scaling active on {dd_scaled_days} days "
          f"({dd_scaled_days/total_days*100:.1f}% of trading days)")
    return pd.DataFrame(trades)

_lib.run_backtest = _v31_run_backtest


# ── Override compute_metrics to label this as V31 ────────────────────────────
_orig_compute_metrics = _lib.compute_metrics

def _v31_compute_metrics(trades_df):
    metrics, eq_df = _orig_compute_metrics(trades_df)
    if isinstance(metrics, dict) and "version" in metrics:
        metrics["version"] = "V31"
        metrics["parameters"]["version"] = "V31"
        metrics["parameters"]["base"] = "V30+S&P600 ($2.41M, 16.01% CAGR)"
        metrics["parameters"]["v31_changes"] = (
            "[V31-1] VIX trend filter: entries only when VIX > 10d MA | "
            "[V31-2] DD scaling: >20% DD → 30% size reduction | "
            "[V31-3] MIN_DOLLAR_VOLUME raised $5M→$10M"
        )
    return metrics, eq_df

_lib.compute_metrics = _v31_compute_metrics


# ── Override save_outputs to label V31 ───────────────────────────────────────
_orig_save_outputs = _lib.save_outputs

def _v31_save_outputs(trades_df, metrics, eq_df):
    import json
    from pathlib import Path
    OUTPUT_DIR = Path("results")
    OUTPUT_DIR.mkdir(exist_ok=True)
    trades_df.to_csv(OUTPUT_DIR / "trades.csv", index=False)
    eq_df.to_csv(OUTPUT_DIR / "equity_curve.csv", index=False)
    with open(OUTPUT_DIR / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, default=str)

    print("\n" + "=" * 70)
    print("  NAIVE MR BACKTEST — V31")
    print("  V30+S&P600 + VIX regime filter + DD scaling + $10M floor")
    print("=" * 70)
    print(f"  {'Version':<36}: {metrics.get('version','V31')}")
    for k, v in metrics.items():
        if k == "tier_stats":
            print(f"\n  Per-Tier Statistics:")
            for tk, tv in v.items():
                print(f"    {tk}:")
                for sk, sv in tv.items():
                    print(f"      {sk:<16}: {sv}")
        elif k == "year_stats":
            print(f"\n  Per-Year Breakdown:")
            for yr, yv in v.items():
                print(f"    {yr}: {yv['trades']:>5} trades  WR {yv['win_rate']:>5}%  "
                      f"P&L ${yv['pnl_usd']:>10,.0f}")
        elif k in ("parameters", "exit_reasons"):
            label = "Parameters" if "param" in k else "Exit Reason Breakdown"
            print(f"\n  {label}:")
            for ek, ev in v.items():
                print(f"    {ek:<40}: {ev}")
        elif k == "version":
            pass  # already printed above
        else:
            print(f"  {k.replace('_',' ').title():<36}: {v}")

    print("\n  V31 vs V30+S&P600 baseline:")
    print("  Target: PF > 1.10 | Sharpe > 0.75 | MaxDD < -42%")
    print("  Baseline: PF 1.07 | Sharpe 0.73 | MaxDD -48.65% | CAGR 16.01%")
    print("=" * 70)
    print(f"\n  Saved to: {OUTPUT_DIR.resolve()}")

_lib.save_outputs = _v31_save_outputs


# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    universe = get_universe()
    price_data = download_prices(universe)
    spy_df, vix_df, sector_data = _lib.download_reference_data()
    earnings_map = build_earnings_dates(list(price_data.keys()))
    trades_df = _lib.run_backtest(price_data, spy_df, vix_df, sector_data, earnings_map)
    if trades_df.empty:
        print("[ERROR] No trades generated.")
    else:
        metrics, eq_df = _lib.compute_metrics(trades_df)
        _lib.save_outputs(trades_df, metrics, eq_df)
