""" Naive Mean Reversion — V32b
==============================
NEW: Shorter hold window for Tier 3 only (6 days instead of 8).

Current: All tiers use uniform 8-day hold window.
The 8-day window is the core mechanism — proven across all versions.
This is NOT changing the core mechanism, just testing whether
the weakest signal tier (Tier 3: 4 consecutive down days) benefits
from a slightly shorter window.

Rationale:
  Tier 1 (6+ down days): strongest signal, 8 days makes sense
  Tier 2 (5 down days):  strong signal, 8 days makes sense
  Tier 3 (4 down days):  weakest signal, may mean-revert faster
                         and benefit from cutting losers sooner

What was previously tested (and failed — DO NOT confuse):
  - Lower PROFIT TARGETS for Tier 3 (1%, 1.25%, 1.5%) — all failed
  - Extended hold to 11-12 days — failed
  This test is about HOLD DAYS only, not profit targets.

V32b: TIER3_HOLD_DAYS = 6 (was 8), everything else unchanged.
Profit target remains 2% for all tiers.

Expected effect:
  - Losers in Tier 3 exit 2 days earlier → smaller avg loss
  - Some winners cut early if they haven't hit 2% by day 6
  - Net effect on PF uncertain — testing to find out
  - Trade volume unchanged

Target: PF > 1.09 | Avg Loss improvement | CAGR within 1%
Baseline (V30+S&P600): PF 1.07 | Avg Loss -3.58% | CAGR 16.01%
"""

from backtest_nmr_lib import (
    get_universe, download_prices, download_reference_data,
    build_earnings_dates, run_backtest, compute_metrics, save_outputs,
    INITIAL_CAPITAL, START_DATE, END_DATE,
)
import backtest_nmr_lib as _lib
import warnings
warnings.filterwarnings("ignore")

# ── Single parameter change ───────────────────────────────────────────────────
_lib.TIER3_HOLD_DAYS = 6   # was 8 — only Tier 3 (4-day setups) affected

# ── Labels ────────────────────────────────────────────────────────────────────
_orig_compute_metrics = _lib.compute_metrics

def _v32b_compute_metrics(trades_df):
    metrics, eq_df = _orig_compute_metrics(trades_df)
    if isinstance(metrics, dict):
        metrics["version"] = "V32b"
        metrics["parameters"]["version"] = "V32b"
        metrics["parameters"]["tier3_hold_days"] = "6 (was 8) — Tier 3 only"
        metrics["parameters"]["v32b_changes"] = (
            "[V32b] TIER3_HOLD_DAYS reduced 8→6 | "
            "Tier 1 and Tier 2 hold days unchanged at 8 | "
            "Profit targets unchanged (2% all tiers)"
        )
    return metrics, eq_df

_lib.compute_metrics = _v32b_compute_metrics

def _v32b_save_outputs(trades_df, metrics, eq_df):
    import json
    from pathlib import Path
    OUTPUT_DIR = Path("results")
    OUTPUT_DIR.mkdir(exist_ok=True)
    trades_df.to_csv(OUTPUT_DIR / "trades.csv", index=False)
    eq_df.to_csv(OUTPUT_DIR / "equity_curve.csv", index=False)
    with open(OUTPUT_DIR / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    print("\n" + "=" * 70)
    print("  NAIVE MR BACKTEST — V32b")
    print("  Tier 3 hold window: 6 days (was 8)")
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
    print("\n  V32b vs V30+S&P600 baseline:")
    print("  Target:   PF > 1.09 | Avg Loss improvement | CAGR within 1%")
    print("  Baseline: PF 1.07   | Avg Loss -3.58%       | CAGR 16.01%")
    print("  Note: Check tier_3 stats specifically — that is what changed")
    print("=" * 70)
    print(f"\n  Saved to: {OUTPUT_DIR.resolve()}")

_lib.save_outputs = _v32b_save_outputs

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
