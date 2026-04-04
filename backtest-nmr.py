""" Naive Mean Reversion — V31b
==============================
Isolates: $10M dollar volume floor + modest DD scaling ONLY.
VIX trend filter REMOVED — testing whether PF/DD improvements
came from the floor and scaling rather than the VIX filter.

Changes vs V30+S&P600:
  [V31b-1] MIN_DOLLAR_VOLUME raised $5M → $10M
  [V31b-2] DD scaling: >20% DD → 30% size reduction
  NO VIX trend filter

Hypothesis: Most of V31's PF and DD improvement came from
these two changes, not from the VIX filter that killed volume.

Target: PF > 1.10 | MaxDD < -42% | CAGR > 14% | Sharpe > 0.73
Baseline (V30+S&P600): PF 1.07 | MaxDD -48.65% | CAGR 16.01% | Sharpe 0.73
"""

from backtest_nmr_lib import (
    get_universe, download_prices, download_reference_data,
    build_earnings_dates, compute_metrics, save_outputs,
    INITIAL_CAPITAL, START_DATE, END_DATE,
)
import backtest_nmr_lib as _lib
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

# ── Parameter overrides ───────────────────────────────────────────────────────
_lib.MIN_DOLLAR_VOLUME  = 10_000_000   # [V31b-1] was 5M
_lib.DD_SCALE_MILD      = 0.20         # [V31b-2] 20% DD threshold
_lib.DD_SCALE_SEVERE    = 9.99         # kept unreachable
_lib.POSITION_SIZE_DD_MILD = 0.063     # not used directly — see override below

_orig_get_position_size = _lib.get_position_size

def _v31b_get_position_size(today, vix_df, drawdown_pct: float = 0.0) -> float:
    base = _orig_get_position_size(today, vix_df, 0.0)
    month = pd.Timestamp(today).month
    if month in _lib.EARNINGS_MONTHS and base > _lib.POSITION_SIZE_EARNINGS:
        base = _lib.POSITION_SIZE_EARNINGS
    if drawdown_pct <= -_lib.DD_SCALE_MILD:
        base = base * 0.70
    return base

_lib.get_position_size = _v31b_get_position_size

# ── Override compute_metrics label ───────────────────────────────────────────
_orig_compute_metrics = _lib.compute_metrics

def _v31b_compute_metrics(trades_df):
    metrics, eq_df = _orig_compute_metrics(trades_df)
    if isinstance(metrics, dict):
        metrics["version"] = "V31b"
        metrics["parameters"]["version"] = "V31b"
        metrics["parameters"]["v31b_changes"] = (
            "[V31b-1] MIN_DOLLAR_VOLUME $5M→$10M | "
            "[V31b-2] DD>20% → 30% size reduction | "
            "NO VIX trend filter"
        )
    return metrics, eq_df

_lib.compute_metrics = _v31b_compute_metrics

# ── Override save_outputs label ───────────────────────────────────────────────
def _v31b_save_outputs(trades_df, metrics, eq_df):
    import json
    from pathlib import Path
    OUTPUT_DIR = Path("results")
    OUTPUT_DIR.mkdir(exist_ok=True)
    trades_df.to_csv(OUTPUT_DIR / "trades.csv", index=False)
    eq_df.to_csv(OUTPUT_DIR / "equity_curve.csv", index=False)
    with open(OUTPUT_DIR / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    print("\n" + "=" * 70)
    print("  NAIVE MR BACKTEST — V31b")
    print("  $10M floor + DD scaling | NO VIX trend filter")
    print("=" * 70)
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
        else:
            print(f"  {k.replace('_',' ').title():<36}: {v}")
    print("\n  V31b vs V30+S&P600 baseline:")
    print("  Target:   PF > 1.10 | MaxDD < -42% | CAGR > 14% | Sharpe > 0.73")
    print("  Baseline: PF 1.07   | MaxDD -48.65% | CAGR 16.01% | Sharpe 0.73")
    print("=" * 70)
    print(f"\n  Saved to: {OUTPUT_DIR.resolve()}")

_lib.save_outputs = _v31b_save_outputs

# ── Entry point ───────────────────────────────────────────────────────────────
if __name__ == "__main__":
    universe = get_universe()
    price_data = download_prices(universe)
    spy_df, vix_df, sector_data = download_reference_data()
    earnings_map = build_earnings_dates(list(price_data.keys()))
    trades_df = _lib.run_backtest(price_data, spy_df, vix_df, sector_data, earnings_map)
    if trades_df.empty:
        print("[ERROR] No trades generated.")
    else:
        metrics, eq_df = _lib.compute_metrics(trades_df)
        _lib.save_outputs(trades_df, metrics, eq_df)
