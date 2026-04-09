""" backtest-nmr-v39a.py
========================
V39a — C3 baked in as permanent, C5 as the only variable.

Runs 2 experiments:
  V39a_baseline  — V33d + C3 permanent (GAP_DOWN_MAX -1.0%)
  V39a_c5        — V33d + C3 + C5 tiered sizing (top 20% get 1.2x)

The bar to beat:
  V33d original:    $3,124k  CAGR 17.41%  MaxDD -54.73%  Sharpe 0.68
  C3 standalone:    $3,425k  CAGR 17.92%  MaxDD -53.42%  Sharpe 0.71
  C5 standalone:    $3,367k  CAGR 17.82%  MaxDD -55.92%  Sharpe 0.68

If V39a_c5 beats V39a_baseline on equity AND holds MaxDD near -53%,
C5 is confirmed and gets carried into backtest_nmr_lib.py as permanent.

Output: results/comparison_v39a.txt
"""

import json
from pathlib import Path

from backtest_nmr_lib_v39a import (
    EXPERIMENTS,
    get_universe,
    download_prices,
    download_reference_data,
    build_earnings_dates,
    run_backtest,
    compute_metrics,
    save_outputs,
)

OUTPUT_DIR = Path("results")
OUTPUT_DIR.mkdir(exist_ok=True)


def print_comparison(all_metrics: list[dict]):
    v33d_ref = {
        "experiment":       "V33d_original_ref",
        "cagr_pct":         17.41,
        "final_equity":     3124041,
        "win_rate_pct":     59.98,
        "profit_factor":    1.06,
        "avg_win_pct":      3.11,
        "avg_loss_pct":     -3.63,
        "max_drawdown_pct": -54.73,
        "sharpe_ratio":     0.68,
        "total_trades":     21902,   # approx
        "trades_per_year":  1043,
        "time_stop_rate_pct": 59.5,
    }
    c3_ref = {
        "experiment":       "C3_standalone_ref",
        "cagr_pct":         17.92,
        "final_equity":     3424911,
        "win_rate_pct":     60.13,
        "profit_factor":    1.07,
        "avg_win_pct":      3.09,
        "avg_loss_pct":     -3.61,
        "max_drawdown_pct": -53.42,
        "sharpe_ratio":     0.71,
        "total_trades":     21989,
        "trades_per_year":  1025.5,
        "time_stop_rate_pct": 59.6,
    }

    display_metrics = [v33d_ref, c3_ref] + all_metrics

    keys = [
        ("cagr_pct",           "CAGR %"),
        ("final_equity",       "Final Equity"),
        ("win_rate_pct",       "Win Rate %"),
        ("profit_factor",      "Profit Factor"),
        ("avg_win_pct",        "Avg Win %"),
        ("avg_loss_pct",       "Avg Loss %"),
        ("max_drawdown_pct",   "Max Drawdown %"),
        ("sharpe_ratio",       "Sharpe"),
        ("total_trades",       "Total Trades"),
        ("trades_per_year",    "Trades/Year"),
        ("time_stop_rate_pct", "Time-Stop Rate %"),
    ]

    baseline_live = next((m for m in all_metrics if m["experiment"] == "V39a_baseline"), None)
    lines = []
    lines.append("=" * 100)
    lines.append("  V39a RESULTS — C3 permanent + C5 test")
    lines.append("  Reference columns: V33d original | C3 standalone (from V38a)")
    lines.append("=" * 100)

    names = [m["experiment"] for m in display_metrics]
    header = f"  {'Metric':<26}" + "".join(f"{n:>18}" for n in names)
    lines.append(header)
    lines.append("-" * 100)

    for key, label in keys:
        row = f"  {label:<26}"
        for m in display_metrics:
            val = m.get(key, "—")
            if isinstance(val, float):
                formatted = f"${val:,.0f}" if key == "final_equity" else f"{val:.2f}"
            else:
                formatted = str(val)
            # Delta vs V39a_baseline for live experiments
            if baseline_live and m["experiment"] not in ("V33d_original_ref", "C3_standalone_ref", "V39a_baseline"):
                b = baseline_live.get(key)
                c = m.get(key)
                if isinstance(b, (int, float)) and isinstance(c, (int, float)):
                    delta = c - b
                    if key == "max_drawdown_pct":
                        sign = "▲" if delta > 0 else "▼"
                    elif key == "avg_loss_pct":
                        sign = "▲" if delta > 0 else "▼"
                    else:
                        sign = "▲" if delta > 0 else "▼"
                    formatted = f"{formatted}{sign}"
            row += f"{formatted:>18}"
        lines.append(row)

    lines.append("-" * 100)
    lines.append("  ▲/▼ vs V39a_baseline | For MaxDD and AvgLoss: ▲ = less negative = better")
    lines.append("")
    lines.append("  Decision rule:")
    lines.append("    V39a_c5 CAGR > V39a_baseline AND MaxDD within 1% → carry C5 into lib permanently")
    lines.append("    V39a_c5 CAGR > V39a_baseline AND MaxDD worse >1% → risk/reward judgment call")
    lines.append("    V39a_c5 CAGR <= V39a_baseline → reject C5, ship C3 only as V34")
    lines.append("=" * 100)

    report = "\n".join(lines)
    print(report)
    out = OUTPUT_DIR / "comparison_v39a.txt"
    out.write_text(report)
    print(f"\n  Saved: {out.resolve()}")

    with open(OUTPUT_DIR / "comparison_v39a.json", "w") as f:
        json.dump(all_metrics, f, indent=2, default=str)


def main():
    print("=" * 60)
    print("  V39a RUNNER — 2 experiments, single data download")
    print("=" * 60)

    universe     = get_universe()
    price_data   = download_prices(universe)
    spy_df, vix_df, sector_data = download_reference_data()
    earnings_map = build_earnings_dates(list(price_data.keys()))

    all_metrics = []
    for cfg in EXPERIMENTS:
        print(f"\n{'─'*60}")
        trades_df = run_backtest(price_data, spy_df, vix_df, sector_data,
                                 earnings_map, cfg=cfg)
        if trades_df.empty:
            print(f"  [WARNING] {cfg.name}: no trades.")
            continue
        metrics, eq_df = compute_metrics(trades_df, cfg=cfg)
        save_outputs(trades_df, metrics, eq_df, cfg=cfg)
        all_metrics.append(metrics)
        print(f"\n  ✓ {cfg.name}: CAGR {metrics['cagr_pct']}% | "
              f"Equity ${metrics['final_equity']:,.0f} | "
              f"MaxDD {metrics['max_drawdown_pct']}% | "
              f"Sharpe {metrics['sharpe_ratio']}")

    print(f"\n{'='*60}\n  FINAL COMPARISON\n{'='*60}\n")
    print_comparison(all_metrics)
    print("\n  Done. Share results/comparison_v39a.txt")


if __name__ == "__main__":
    main()
