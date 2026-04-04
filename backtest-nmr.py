""" Naive Mean Reversion — V33b-d
================================
Combines V33b (50 positions) + V32d (Tier 3 hold 6d + VIX 80% sizing).
Goal: get V33b's equity with V32d's improved drawdown profile.

[V33bd-1] MAX_POSITIONS = 50 (from V33b)
  V33b result: CAGR 16.83% | Equity $2,808k | MaxDD -51.73% | Sharpe 0.70

[V33bd-2] TIER3_HOLD_DAYS = 6 (from V32b/V32d)
  Reduces avg loss on weakest signal tier
  Does not interact with position count — pure exit timing improvement

[V33bd-3] VIX 5d trend 80% sizing (from V32c/V32d)
  When VIX falling (below 5d MA) → 80% of normal size
  Directly reduces exposure on bad regime days
  This is where extra positions hurt most during drawdowns

Hypothesis: The VIX sizing reduces exposure on the ~50% of days when
VIX is falling. During 2022's drawdown, VIX was rising (good for the
filter — full size). During the recovery phases where V33b gave back
gains (2023, 2025, 2026 partial), VIX was often falling — the 80%
multiplier would have reduced those losses.

Expected: equity between V32d ($2,145k) and V33b ($2,808k)
          MaxDD between V32d (-39%) and V33b (-51%)
          Sharpe between V32d (0.77) and V33b (0.70)

Target: Equity > $2,400k | MaxDD < -46% | Sharpe > 0.72
Baselines:
  V33b:  $2,808k | CAGR 16.83% | MaxDD -51.73% | Sharpe 0.70
  V32d:  $2,145k | CAGR 15.37% | MaxDD -39.21% | Sharpe 0.77
  V32e:  $2,454k | CAGR 16.10% | MaxDD -48.61% | Sharpe 0.73
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

# ── Parameter overrides ───────────────────────────────────────────────────────
_lib.MAX_POSITIONS    = 50   # [V33bd-1]
_lib.TIER3_HOLD_DAYS  = 6    # [V33bd-2] was 8

VIX_TREND_MA          = 5
VIX_DOWN_MULTIPLIER   = 0.80

# ── Override download_reference_data to add VIX MA ───────────────────────────
_orig_download_reference_data = _lib.download_reference_data

def _v33bd_download_reference_data():
    spy, vix, sector_data = _orig_download_reference_data()
    vix_close = vix["Close"].squeeze()
    vix["vix_ma"] = vix_close.rolling(VIX_TREND_MA).mean()
    vix["vix_trending_up"] = vix_close > vix["vix_ma"]
    pct_reduced = (~vix["vix_trending_up"]).mean() * 100
    print(f"[V33b-d] VIX {VIX_TREND_MA}-day trend: size at "
          f"{VIX_DOWN_MULTIPLIER*100:.0f}% on ~{pct_reduced:.1f}% of days")
    return spy, vix, sector_data

_lib.download_reference_data = _v33bd_download_reference_data

# ── Override get_position_size to apply VIX trend multiplier ─────────────────
_orig_get_position_size = _lib.get_position_size

def _v33bd_get_position_size(today, vix_df, drawdown_pct: float = 0.0) -> float:
    base = _orig_get_position_size(today, vix_df, drawdown_pct)
    try:
        if today in vix_df.index and "vix_trending_up" in vix_df.columns:
            if not bool(vix_df.loc[today, "vix_trending_up"]):
                base = base * VIX_DOWN_MULTIPLIER
    except Exception:
        pass
    return base

_lib.get_position_size = _v33bd_get_position_size

# ── Labels ────────────────────────────────────────────────────────────────────
_orig_compute_metrics = _lib.compute_metrics

def _v33bd_compute_metrics(trades_df):
    metrics, eq_df = _orig_compute_metrics(trades_df)
    if isinstance(metrics, dict):
        metrics["version"] = "V33b-d"
        metrics["parameters"]["version"] = "V33b-d"
        metrics["parameters"]["max_positions"] = "50 [V33bd-1]"
        metrics["parameters"]["tier3_hold_days"] = "6 (was 8) [V33bd-2]"
        metrics["parameters"]["v33bd_changes"] = (
            "[V33bd-1] MAX_POSITIONS 40→50 | "
            "[V33bd-2] TIER3_HOLD_DAYS 8→6 | "
            f"[V33bd-3] VIX {VIX_TREND_MA}-day trend: falling → {VIX_DOWN_MULTIPLIER*100:.0f}% size"
        )
    return metrics, eq_df

_lib.compute_metrics = _v33bd_compute_metrics

def _v33bd_save_outputs(trades_df, metrics, eq_df):
    import json
    from pathlib import Path
    OUTPUT_DIR = Path("results")
    OUTPUT_DIR.mkdir(exist_ok=True)
    trades_df.to_csv(OUTPUT_DIR / "trades.csv", index=False)
    eq_df.to_csv(OUTPUT_DIR / "equity_curve.csv", index=False)
    with open(OUTPUT_DIR / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    print("\n" + "=" * 70)
    print("  NAIVE MR BACKTEST — V33b-d")
    print("  50 positions + Tier3 hold 6d + VIX 80% sizing")
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
    print("\n  V33b-d vs baselines:")
    print("  Target:  Equity > $2,400k | MaxDD < -46% | Sharpe > 0.72")
    print("  V33b:    $2,808k | CAGR 16.83% | MaxDD -51.73% | Sharpe 0.70")
    print("  V32d:    $2,145k | CAGR 15.37% | MaxDD -39.21% | Sharpe 0.77")
    print("  V32e:    $2,454k | CAGR 16.10% | MaxDD -48.61% | Sharpe 0.73")
    print("=" * 70)
    print(f"\n  Saved to: {OUTPUT_DIR.resolve()}")

_lib.save_outputs = _v33bd_save_outputs

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
