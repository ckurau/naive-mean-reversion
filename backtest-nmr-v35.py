# backtest-nmr-v35.py
# Runner: V34 baseline vs V35 streak filter Option C
# Accepts --experiment baseline|v35|both (default: both)

import json
import argparse
from pathlib import Path
from backtest_nmr_lib_v35 import (
    EXPERIMENTS, BASELINE, V35,
    get_universe, download_prices, download_reference_data,
    build_earnings_dates, run_backtest, compute_metrics, save_outputs,
)

OUTPUT_DIR = Path("results")
OUTPUT_DIR.mkdir(exist_ok=True)

V34_REF = {
    "experiment":         "V34_reference",
    "cagr_pct":           18.50,
    "final_equity":       3805846,
    "win_rate_pct":       60.14,
    "profit_factor":      1.07,
    "avg_win_pct":        3.09,
    "avg_loss_pct":       -3.61,
    "max_drawdown_pct":   -54.50,
    "sharpe_ratio":       0.71,
    "total_trades":       21975,
    "trades_per_year":    1024.8,
    "time_stop_rate_pct": 59.6,
}


def print_comparison(all_metrics):
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

    display = [V34_REF] + all_metrics
    baseline_live = next((m for m in all_metrics if "baseline" in m["experiment"]), None)

    lines = []
    lines.append("=" * 95)
    lines.append("  V35 RESULTS -- Streak Filter Option C vs V34")
    lines.append("=" * 95)
    names = [m["experiment"] for m in display]
    header = f"  {'Metric':<26}" + "".join(f"{n:>22}" for n in names)
    lines.append(header)
    lines.append("-" * 95)

    for key, label in keys:
        row = f"  {label:<26}"
        for m in display:
            val = m.get(key, "?")
            if isinstance(val, float):
                formatted = f"${val:,.0f}" if key == "final_equity" else f"{val:.2f}"
            else:
                formatted = str(val)
            if (baseline_live and m["experiment"] not in ("V34_reference",)
                    and m["experiment"] != baseline_live["experiment"]):
                b = baseline_live.get(key)
                c = m.get(key)
                if isinstance(b, (int, float)) and isinstance(c, (int, float)):
                    delta = c - b
                    sign = "+" if delta >= 0 else ""
                    if key == "final_equity":
                        formatted = f"{formatted}({sign}${abs(int(delta)):,})"
                    else:
                        formatted = f"{formatted}({sign}{delta:.2f})"
            row += f"{formatted:>22}"
        lines.append(row)

    lines.append("-" * 95)
    lines.append("  (+) vs V34_baseline control | MaxDD: less negative = better")
    lines.append("")
    lines.append("  Decision rule:")
    lines.append("    MaxDD improves AND CAGR >= V34 --> carry into backtest_nmr_lib.py as V35")
    lines.append("    MaxDD improves AND CAGR < 1% worse --> judgment call")
    lines.append("    MaxDD does not improve --> reject")
    lines.append("")

    if baseline_live and len(all_metrics) > 1:
        v35m = next((m for m in all_metrics if "streak" in m["experiment"]), None)
        if v35m and "year_stats" in baseline_live and "year_stats" in v35m:
            b_years = baseline_live["year_stats"]
            v_years = v35m["year_stats"]
            lines.append(f"  Year-by-year P&L:")
            lines.append(f"  {'Year':<6} {'Baseline':>14} {'V35':>14} {'Delta':>14} {'Base WR':>9} {'V35 WR':>9}")
            lines.append(f"  {'-'*68}")
            for yr in sorted(b_years.keys()):
                if yr in v_years:
                    bp = b_years[yr]["pnl_usd"]
                    vp = v_years[yr]["pnl_usd"]
                    bw = b_years[yr]["win_rate"]
                    vw = v_years[yr]["win_rate"]
                    delta = vp - bp
                    sign = "+" if delta >= 0 else ""
                    lines.append(f"  {yr:<6} ${bp:>12,.0f}   ${vp:>12,.0f}   {sign}${abs(int(delta)):>11,}   {bw:>7.1f}%   {vw:>7.1f}%")

    lines.append("=" * 95)
    report = "\n".join(lines)
    print(report)
    out = OUTPUT_DIR / "comparison_v35.txt"
    out.write_text(report)
    print(f"\n  Saved: {out.resolve()}")
    with open(OUTPUT_DIR / "comparison_v35.json", "w") as f:
        json.dump(all_metrics, f, indent=2, default=str)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", default="both",
                        choices=["baseline", "v35", "both"])
    args = parser.parse_args()

    if args.experiment == "baseline":
        to_run = [BASELINE]
    elif args.experiment == "v35":
        to_run = [V35]
    else:
        to_run = EXPERIMENTS

    print("=" * 60)
    print(f"  V35 RUNNER -- running: {[e.name for e in to_run]}")
    print("=" * 60)

    universe     = get_universe()
    price_data   = download_prices(universe)
    spy_df, vix_df, sector_data = download_reference_data()
    earnings_map = build_earnings_dates(list(price_data.keys()))

    all_metrics = []

    # If running v35 only, load existing baseline metrics for comparison
    if args.experiment == "v35":
        baseline_path = OUTPUT_DIR / "V34_baseline" / "metrics.json"
        if baseline_path.exists():
            with open(baseline_path) as f:
                all_metrics.append(json.load(f))
            print(f"  Loaded existing baseline from {baseline_path}")

    for cfg in to_run:
        print(f"\n{'--'*30}")
        trades_df = run_backtest(price_data, spy_df, vix_df, sector_data,
                                 earnings_map, cfg=cfg)
        if trades_df.empty:
            print(f"  [WARNING] {cfg.name}: no trades.")
            continue
        metrics, eq_df = compute_metrics(trades_df, cfg=cfg)
        save_outputs(trades_df, metrics, eq_df, cfg=cfg)
        all_metrics.append(metrics)
        print(f"\n  {cfg.name}: CAGR {metrics['cagr_pct']}% | "
              f"Equity ${metrics['final_equity']:,.0f} | "
              f"MaxDD {metrics['max_drawdown_pct']}% | "
              f"Sharpe {metrics['sharpe_ratio']} | "
              f"WR {metrics['win_rate_pct']}%")

    if len(all_metrics) >= 2:
        print(f"\n{'='*60}\n  FINAL COMPARISON\n{'='*60}\n")
        print_comparison(all_metrics)
    else:
        print(f"\n  Single experiment complete. Run with --experiment both for comparison.")

    print("\n  Done.")


if __name__ == "__main__":
    main()
