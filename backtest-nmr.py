""" Naive Mean Reversion — V33d
==============================
Tests whether position ceiling is above 55.

Position count series results so far:
  V32e (40): CAGR 16.10% | Equity $2,454k | MaxDD -48.61% | Sharpe 0.73
  V33b (50): CAGR 16.83% | Equity $2,808k | MaxDD -51.73% | Sharpe 0.70
  V33c (55): CAGR 17.16% | Equity $2,982k | MaxDD -53.27% | Sharpe 0.69

Diminishing returns per 5 positions:
  40→50: +$354k equity, +0.73% CAGR, -3.12% DD, -0.03 Sharpe
  50→55: +$174k equity, +0.33% CAGR, -1.54% DD, -0.01 Sharpe
  55→60: expected ~+$120-150k equity, +0.2-0.3% CAGR, -1.5% DD

Stop criteria (60 is the ceiling if):
  CAGR gain < 0.2% vs V33c
  OR Sharpe drops below 0.67
  OR PF drops below 1.05
  OR MaxDD worse than -56%

Target: CAGR > 17.3% | Equity > $3,100k | Sharpe ≥ 0.68
"""

from backtest_nmr_lib import (
    get_universe, download_prices, download_reference_data,
    build_earnings_dates, run_backtest, compute_metrics, save_outputs,
    INITIAL_CAPITAL, START_DATE, END_DATE,
)
import backtest_nmr_lib as _lib
import warnings
warnings.filterwarnings("ignore")

_lib.MAX_POSITIONS = 60

_orig_compute_metrics = _lib.compute_metrics

def _v33d_compute_metrics(trades_df):
    metrics, eq_df = _orig_compute_metrics(trades_df)
    if isinstance(metrics, dict):
        metrics["version"] = "V33d"
        metrics["parameters"]["version"] = "V33d"
        metrics["parameters"]["max_positions"] = "60 (was 55 in V33c) [V33d]"
        metrics["parameters"]["v33d_changes"] = (
            "[V33d] MAX_POSITIONS raised 55→60 | "
            "testing ceiling above 55"
        )
    return metrics, eq_df

_lib.compute_metrics = _v33d_compute_metrics

def _v33d_save_outputs(trades_df, metrics, eq_df):
    import json
    from pathlib import Path
    OUTPUT_DIR = Path("results")
    OUTPUT_DIR.mkdir(exist_ok=True)
    trades_df.to_csv(OUTPUT_DIR / "trades.csv", index=False)
    eq_df.to_csv(OUTPUT_DIR / "equity_curve.csv", index=False)
    with open(OUTPUT_DIR / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    print("\n" + "=" * 70)
    print("  NAIVE MR BACKTEST — V33d")
    print("  MAX_POSITIONS raised 55 → 60")
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
    print("\n  Position count series:")
    print("  V32e (40): $2,454k | CAGR 16.10% | MaxDD -48.61% | Sharpe 0.73")
    print("  V33b (50): $2,808k | CAGR 16.83% | MaxDD -51.73% | Sharpe 0.70")
    print("  V33c (55): $2,982k | CAGR 17.16% | MaxDD -53.27% | Sharpe 0.69")
    print("  V33d (60): above  ^^^")
    print("  Stop if: CAGR gain < 0.2% OR Sharpe < 0.67 OR PF < 1.05 OR MaxDD < -56%")
    print("=" * 70)
    print(f"\n  Saved to: {OUTPUT_DIR.resolve()}")

_lib.save_outputs = _v33d_save_outputs

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
