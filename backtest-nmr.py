""" Naive Mean Reversion — V33c
==============================
Tests whether position ceiling is above 50.

V33b (50 positions) result:
  CAGR 16.83% | Equity $2,808k | MaxDD -51.73% | Sharpe 0.70

V33c raises to 55 positions to find the optimum.
Same logic as V24 (30→40) and V33b (40→50):
  Adding positions at full size on high-signal days = more compounding
  The optimum is where CAGR gains stop outpacing drawdown costs

If V33c regresses vs V33b (Sharpe < 0.68, PF < 1.05, or CAGR gain
< 0.3%) → 50 is the ceiling, stop here.
If V33c improves → try 60 in V33d.

Target: CAGR > 17% | Equity > $2,900k | Sharpe ≥ 0.69
Baseline (V33b): CAGR 16.83% | Equity $2,808k | Sharpe 0.70
"""

from backtest_nmr_lib import (
    get_universe, download_prices, download_reference_data,
    build_earnings_dates, run_backtest, compute_metrics, save_outputs,
    INITIAL_CAPITAL, START_DATE, END_DATE,
)
import backtest_nmr_lib as _lib
import warnings
warnings.filterwarnings("ignore")

_lib.MAX_POSITIONS = 55   # was 40 (V32e), was 50 (V33b)

_orig_compute_metrics = _lib.compute_metrics

def _v33c_compute_metrics(trades_df):
    metrics, eq_df = _orig_compute_metrics(trades_df)
    if isinstance(metrics, dict):
        metrics["version"] = "V33c"
        metrics["parameters"]["version"] = "V33c"
        metrics["parameters"]["max_positions"] = "55 (was 50 in V33b) [V33c]"
        metrics["parameters"]["v33c_changes"] = (
            "[V33c] MAX_POSITIONS raised 50→55 | "
            "testing whether position ceiling is above 50"
        )
    return metrics, eq_df

_lib.compute_metrics = _v33c_compute_metrics

def _v33c_save_outputs(trades_df, metrics, eq_df):
    import json
    from pathlib import Path
    OUTPUT_DIR = Path("results")
    OUTPUT_DIR.mkdir(exist_ok=True)
    trades_df.to_csv(OUTPUT_DIR / "trades.csv", index=False)
    eq_df.to_csv(OUTPUT_DIR / "equity_curve.csv", index=False)
    with open(OUTPUT_DIR / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    print("\n" + "=" * 70)
    print("  NAIVE MR BACKTEST — V33c")
    print("  MAX_POSITIONS raised 50 → 55")
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
    print("\n  V33c vs baselines:")
    print("  Target:  CAGR > 17%   | Equity > $2,900k | Sharpe ≥ 0.69")
    print("  V33b:    CAGR 16.83%  | Equity $2,808k   | Sharpe 0.70 | MaxDD -51.73%")
    print("  V32e:    CAGR 16.10%  | Equity $2,454k   | Sharpe 0.73 | MaxDD -48.61%")
    print("  Decision: if CAGR gain < 0.3% or Sharpe < 0.68 → 50 is the ceiling")
    print("=" * 70)
    print(f"\n  Saved to: {OUTPUT_DIR.resolve()}")

_lib.save_outputs = _v33c_save_outputs

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
