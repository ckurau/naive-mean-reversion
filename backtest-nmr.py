""" Naive Mean Reversion — V32c
==============================
NEW: Continuous VIX trend regime sizing.

Current: VIX level determines size tier (9% or 5%).
         No response to VIX direction (rising vs falling).

V31 attempt: Binary block — no entries when VIX falling.
             Result: Blocked too many days, killed volume and CAGR.

V32c approach: When VIX is falling (below its 5-day MA),
               reduce all position sizes by 20% instead of blocking.
               Trading continues — just at reduced size.

  VIX rising (above 5d MA) → normal VIX regime sizing (9% or 5%)
  VIX falling (below 5d MA) → 80% of normal sizing (7.2% or 4%)

Rationale:
  VIX falling = volatility contracting = weaker MR conditions
  Still worth trading, just with less conviction
  Keeps compounding alive unlike the binary block in V31
  Responds to VIX direction, not just level

Expected effect:
  Modest reduction in position size on ~40-50% of trading days
  (VIX is below its 5d MA roughly half the time)
  Slight CAGR reduction, possible Sharpe improvement
  Trade volume completely unchanged

Target: Sharpe > 0.74 | MaxDD improvement | CAGR > 15%
Baseline (V30+S&P600): Sharpe 0.73 | MaxDD -48.65% | CAGR 16.01%
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

VIX_TREND_MA      = 5     # 5-day VIX MA for trend direction
VIX_DOWN_MULTIPLIER = 0.80  # reduce size to 80% when VIX is falling

# ── Override download_reference_data to add VIX MA ───────────────────────────
_orig_download_reference_data = _lib.download_reference_data

def _v32c_download_reference_data():
    spy, vix, sector_data = _orig_download_reference_data()
    vix_close = vix["Close"].squeeze()
    vix["vix_ma"] = vix_close.rolling(VIX_TREND_MA).mean()
    vix["vix_trending_up"] = vix_close > vix["vix_ma"]
    pct_reduced = (~vix["vix_trending_up"]).mean() * 100
    print(f"[V32c] VIX {VIX_TREND_MA}-day trend: size reduced on "
          f"~{pct_reduced:.1f}% of days (VIX falling → {VIX_DOWN_MULTIPLIER*100:.0f}% of normal size)")
    return spy, vix, sector_data

_lib.download_reference_data = _v32c_download_reference_data

# ── Override get_position_size to apply VIX trend multiplier ─────────────────
_orig_get_position_size = _lib.get_position_size

def _v32c_get_position_size(today, vix_df, drawdown_pct: float = 0.0) -> float:
    base = _orig_get_position_size(today, vix_df, drawdown_pct)
    # [V32c] Apply VIX trend multiplier
    try:
        if today in vix_df.index and "vix_trending_up" in vix_df.columns:
            vix_up = bool(vix_df.loc[today, "vix_trending_up"])
            if not vix_up:
                base = base * VIX_DOWN_MULTIPLIER
    except Exception:
        pass
    return base

_lib.get_position_size = _v32c_get_position_size

# ── Labels ────────────────────────────────────────────────────────────────────
_orig_compute_metrics = _lib.compute_metrics

def _v32c_compute_metrics(trades_df):
    metrics, eq_df = _orig_compute_metrics(trades_df)
    if isinstance(metrics, dict):
        metrics["version"] = "V32c"
        metrics["parameters"]["version"] = "V32c"
        metrics["parameters"]["v32c_changes"] = (
            f"[V32c] VIX {VIX_TREND_MA}-day trend multiplier: "
            f"falling VIX → {VIX_DOWN_MULTIPLIER*100:.0f}% of normal size | "
            "no binary blocking | all trades execute"
        )
    return metrics, eq_df

_lib.compute_metrics = _v32c_compute_metrics

def _v32c_save_outputs(trades_df, metrics, eq_df):
    import json
    from pathlib import Path
    OUTPUT_DIR = Path("results")
    OUTPUT_DIR.mkdir(exist_ok=True)
    trades_df.to_csv(OUTPUT_DIR / "trades.csv", index=False)
    eq_df.to_csv(OUTPUT_DIR / "equity_curve.csv", index=False)
    with open(OUTPUT_DIR / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    print("\n" + "=" * 70)
    print("  NAIVE MR BACKTEST — V32c")
    print(f"  VIX {VIX_TREND_MA}-day trend: {VIX_DOWN_MULTIPLIER*100:.0f}% size when VIX falling")
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
    print("\n  V32c vs V30+S&P600 baseline:")
    print("  Target:   Sharpe > 0.74 | MaxDD improvement | CAGR > 15%")
    print("  Baseline: Sharpe 0.73   | MaxDD -48.65%     | CAGR 16.01%")
    print("=" * 70)
    print(f"\n  Saved to: {OUTPUT_DIR.resolve()}")

_lib.save_outputs = _v32c_save_outputs

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
