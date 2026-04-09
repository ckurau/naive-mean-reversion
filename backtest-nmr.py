""" backtest-nmr-v38a.py
========================
Runs all 7 experiments (V33d baseline + 5 individual changes + all combined)
using a single download pass. Produces a side-by-side comparison report.

Usage:
    python backtest-nmr-v38a.py

Output:
    results/V33d_baseline/        — baseline (V33d unchanged)
    results/C1_ibs_only/          — IBS < 0.35 filter only
    results/C2_ema_only/          — EMA 20/50 downtrend block only
    results/C3_gap_only/          — Gap down tightened to -1.0% only
    results/C4_cooldown/          — Double time-stop cooldown only
    results/C5_sizing/            — Top-20% signal size multiplier only
    results/V38a_all/             — All 5 changes combined
    results/comparison_v38a.json  — Side-by-side metrics table
    results/comparison_v38a.txt   — Human-readable summary

Runtime: same as a single V33d run (~90-120 min with S&P 600).
Data is downloaded ONCE and reused across all 7 experiments.
Signal generation is re-run per experiment (C1/C2 change signals).
Experiments C3/C4/C5 only change simulation logic, not signals.
"""

import json
from pathlib import Path
import pandas as pd

from backtest_nmr_lib_v38a import (
    ExperimentConfig,
    EXPERIMENTS,
    get_universe,
    download_prices,
    download_reference_data,
    build_earnings_dates,
    run_backtest,
    compute_metrics,
    save_outputs,
    INITIAL_CAPITAL,
)

OUTPUT_DIR = Path("results")
OUTPUT_DIR.mkdir(exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# Comparison report
# ─────────────────────────────────────────────────────────────────────────────
def print_comparison(all_metrics: list[dict]):
    """Print a clean side-by-side table to stdout and save as .txt"""

    # Key metrics to compare
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

    baseline = next((m for m in all_metrics if m["experiment"] == "V33d_baseline"), None)

    lines = []
    lines.append("=" * 110)
    lines.append("  V38a EXPERIMENT COMPARISON — V33d Baseline vs 5 Changes vs All Combined")
    lines.append("=" * 110)

    # Header row
    exp_names = [m["experiment"] for m in all_metrics]
    header = f"  {'Metric':<26}" + "".join(f"{n:>14}" for n in exp_names)
    lines.append(header)
    lines.append("-" * 110)

    for key, label in keys:
        row = f"  {label:<26}"
        for m in all_metrics:
            val = m.get(key, "—")
            if isinstance(val, float):
                if key == "final_equity":
                    formatted = f"${val:,.0f}"
                else:
                    formatted = f"{val:.2f}"
            else:
                formatted = str(val)

            # Delta vs baseline (green/red indicator)
            if baseline and key != "description" and m["experiment"] != "V33d_baseline":
                b_val = baseline.get(key)
                c_val = m.get(key)
                if isinstance(b_val, (int, float)) and isinstance(c_val, (int, float)):
                    delta = c_val - b_val
                    # For drawdown, negative delta is better
                    if key == "max_drawdown_pct":
                        sign = "▲" if delta > 0 else "▼" if delta < 0 else " "
                        # drawdown more negative = worse, so flip sign meaning
                        better = delta > 0  # less negative = better
                    elif key in ("avg_loss_pct",):
                        better = delta > 0  # less negative avg loss = better
                        sign = "▲" if delta > 0 else "▼" if delta < 0 else " "
                    else:
                        better = delta > 0
                        sign = "▲" if delta > 0 else "▼" if delta < 0 else " "
                    formatted = f"{formatted}{sign}"
            row += f"{formatted:>14}"
        lines.append(row)

    lines.append("-" * 110)
    lines.append(f"  ▲ = better than baseline  ▼ = worse than baseline  (for MaxDD: ▲ = less negative = better)")
    lines.append("")

    # Flags row
    lines.append("  Feature Flags Active:")
    flag_keys = ["C1_ibs", "C2_ema_stack", "C3_gap_tighter", "C4_cooldown", "C5_sizing"]
    for m in all_metrics:
        flags = m.get("flags", {})
        active = [k for k in flag_keys if flags.get(k)]
        lines.append(f"    {m['experiment']:<20}: {', '.join(active) if active else 'none (baseline)'}")

    lines.append("")
    lines.append("  Descriptions:")
    for m in all_metrics:
        lines.append(f"    {m['experiment']:<20}: {m.get('description','')}")

    lines.append("=" * 110)

    report = "\n".join(lines)
    print(report)

    out_path = OUTPUT_DIR / "comparison_v38a.txt"
    out_path.write_text(report)
    print(f"\n  Comparison saved: {out_path.resolve()}")


def save_comparison_json(all_metrics: list[dict]):
    out_path = OUTPUT_DIR / "comparison_v38a.json"
    with open(out_path, "w") as f:
        json.dump(all_metrics, f, indent=2, default=str)
    print(f"  JSON saved:       {out_path.resolve()}")


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────
def main():
    print("=" * 70)
    print("  V38a MULTI-EXPERIMENT RUNNER")
    print(f"  Running {len(EXPERIMENTS)} experiments with single data download")
    print("=" * 70)

    # ── Download once ──────────────────────────────────────────────────────────
    universe     = get_universe()
    price_data   = download_prices(universe)
    spy_df, vix_df, sector_data = download_reference_data()
    earnings_map = build_earnings_dates(list(price_data.keys()))

    # ── Run each experiment ────────────────────────────────────────────────────
    all_metrics: list[dict] = []

    for cfg in EXPERIMENTS:
        print(f"\n{'─'*70}")
        trades_df = run_backtest(price_data, spy_df, vix_df, sector_data,
                                 earnings_map, cfg=cfg)
        if trades_df.empty:
            print(f"  [WARNING] {cfg.name}: no trades generated.")
            all_metrics.append({"experiment": cfg.name, "description": cfg.description,
                                 "error": "no trades", "flags": {}})
            continue

        metrics, eq_df = compute_metrics(trades_df, cfg=cfg)
        save_outputs(trades_df, metrics, eq_df, cfg=cfg)
        all_metrics.append(metrics)

        # Quick summary line
        print(f"\n  ✓ {cfg.name}: CAGR {metrics.get('cagr_pct','?')}% | "
              f"Equity ${metrics.get('final_equity',0):,.0f} | "
              f"WR {metrics.get('win_rate_pct','?')}% | "
              f"MaxDD {metrics.get('max_drawdown_pct','?')}% | "
              f"Sharpe {metrics.get('sharpe_ratio','?')}")

    # ── Comparison report ──────────────────────────────────────────────────────
    print(f"\n{'='*70}")
    print("  FINAL COMPARISON")
    print(f"{'='*70}\n")
    print_comparison(all_metrics)
    save_comparison_json(all_metrics)

    print("\n  Done. Share results/comparison_v38a.txt for analysis.")


if __name__ == "__main__":
    main()
