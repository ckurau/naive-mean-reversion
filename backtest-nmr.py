""" Naive Mean Reversion — V32d
==============================
Combines V32b + V32c — both changes target different mechanisms
and do not interact with each other.

[V32d-1] From V32b: Tier 3 hold window reduced 8 → 6 days
  Effect: Smaller avg loss on weakest signal tier, better Sharpe
  V32b result: Sharpe 0.75, Avg Loss -3.12%, CAGR 15.87%

[V32d-2] From V32c: VIX 5-day trend sizing multiplier
  When VIX falling (below 5d MA) → 80% of normal position size
  Effect: Reduced exposure in weaker regime conditions, better DD
  V32c result: Sharpe 0.74, MaxDD -44.30%, CAGR 15.28%

Hypothesis: Both improvements are additive since they target
different parts of the strategy:
  V32b → improves exit quality (Tier 3 time stops)
  V32c → improves entry sizing (regime awareness)
Combined target: Sharpe ~0.76 | MaxDD < -42% | CAGR > 14.5%

Baseline (V30+S&P600): Sharpe 0.73 | MaxDD -48.65% | CAGR 16.01%
V32b alone:            Sharpe 0.75 | MaxDD -44.87% | CAGR 15.87%
V32c alone:            Sharpe 0.74 | MaxDD -44.30% | CAGR 15.28%
"""

from backtest_nmr_lib import (
    get_universe, download_prices, download_reference_data,
    build_earnings_dates, run_backtest, compute_metrics, save_outputs,
    INITIAL_CAPITAL, START_DATE, END_DATE,
)
import backtest_nmr_lib as _lib
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

# ── [V32d-1] Tier 3 hold window ───────────────────────────────────────────────
_lib.TIER3_HOLD_DAYS = 6   # was 8

# ── [V32d-2] VIX trend sizing parameters ─────────────────────────────────────
VIX_TREND_MA        = 5
VIX_DOWN_MULTIPLIER = 0.80

# ── Override download_reference_data to add VIX MA ───────────────────────────
_orig_download_reference_data = _lib.download_reference_data

def _v32d_download_reference_data():
    spy, vix, sector_data = _orig_download_reference_data()
    vix_close = vix["Close"].squeeze()
    vix["vix_ma"] = vix_close.rolling(VIX_TREND_MA).mean()
    vix["vix_trending_up"] = vix_close > vix["vix_ma"]
    pct_reduced = (~vix["vix_trending_up"]).mean() * 100
    print(f"[V32d] VIX {VIX_TREND_MA}-day trend: size at "
          f"{VIX_DOWN_MULTIPLIER*100:.0f}% on ~{pct_reduced:.1f}% of days")
    return spy, vix, sector_data

_lib.download_reference_data = _v32d_download_reference_data

# ── Override get_position_size to apply VIX trend multiplier ─────────────────
_orig_get_position_size = _lib.get_position_size

def _v32d_get_position_size(today, vix_df, drawdown_pct: float = 0.0) -> float:
    base = _orig_get_position_size(today, vix_df, drawdown_pct)
    try:
        if today in vix_df.index and "vix_trending_up" in vix_df.columns:
            if not bool(vix_df.loc[today, "vix_trending_up"]):
                base = base * VIX_DOWN_MULTIPLIER
    except Exception:
        pass
    return base

_lib.get_position_size = _v32d_get_position_size

# ── Labels ────────────────────────────────────────────────────────────────────
_orig_compute_metrics = _lib.compute_metrics

def _v32d_compute_metrics(trades_df):
    metrics, eq_df = _orig_compute_metrics(trades_df)
    if isinstance(metrics, dict):
        metrics["version"] = "V32d"
        metrics["parameters"]["version"] = "V32d"
        metrics["parameters"]["tier3_hold_days"] = "6 (was 8) — Tier 3 only [V32b]"
        metrics["parameters"]["v32d_changes"] = (
            "[V32d-1] TIER3_HOLD_DAYS 8→6 (from V32b) | "
            f"[V32d-2] VIX {VIX_TREND_MA}-day trend: "
            f"falling VIX → {VIX_DOWN_MULTIPLIER*100:.0f}% size (from V32c)"
        )
    return metrics, eq_df

_lib.compute_metrics = _v32d_compute_metrics

def _v32d_save_outputs(trades_df, metrics, eq_df):
    import json
    from pathlib import Path
    OUTPUT_DIR = Path("results")
    OUTPUT_DIR.mkdir(exist_ok=True)
    trades_df.to_csv(OUTPUT_DIR / "trades.csv", index=False)
    eq_df.to_csv(OUTPUT_DIR / "equity_curve.csv", index=False)
    with open(OUTPUT_DIR / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    print("\n" + "=" * 70)
    print("  NAIVE MR BACKTEST — V32d")
    print("  V32b (Tier 3 hold 6d) + V32c (VIX trend 80% sizing)")
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
    print("\n  V32d vs baselines:")
    print("  Target:        Sharpe ~0.76 | MaxDD < -42% | CAGR > 14.5%")
    print("  V30+S&P600:    Sharpe 0.73  | MaxDD -48.65% | CAGR 16.01%")
    print("  V32b alone:    Sharpe 0.75  | MaxDD -44.87% | CAGR 15.87%")
    print("  V32c alone:    Sharpe 0.74  | MaxDD -44.30% | CAGR 15.28%")
    print("=" * 70)
    print(f"\n  Saved to: {OUTPUT_DIR.resolve()}")

_lib.save_outputs = _v32d_save_outputs

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
