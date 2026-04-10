# backtest-nmr-v37.py
# Runner: V34 baseline vs V37 volume peak filter
# Output: results/comparison_v37.txt

import json
from pathlib import Path
from backtest_nmr_lib_v37 import (
    EXPERIMENTS, get_universe, download_prices, download_reference_data,
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
    lines.append("=" * 90)
    lines.append("  V37 RESULTS -- Volume Peak Filter")
    lines.append("  Filter: entry only when today's volume is highest in the consecutive down streak")
    lines.append("  Hypothesis: capitulation volume on final down day = highest mean reversion probability")
    lines.append("=" * 90)
    names = [m["experiment"] for m in display]
    header = f"  {'Metric':<26}" + "".join(f"{n:>20}" for n in names)
    lines.append(header)
    lines.append("-" * 90)

    for key, label in keys:
        row = f"  {label:<26}"
        for m in display:
            val = m.get(key, "?")
            if isinstance(val, float):
                formatted = f"${val:,.0f}" if key == "final_equity" else f"{val:.2f}"
            elif isinstance(val, int) and key == "total_trades":
                formatted = f"{val:,}"
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
            row += f"{formatted:>20}"
        lines.append(row)

    lines.append("-" * 90)
    lines.append("  Key diagnostic: check 'Vol peak filter blocked: X entries' in the log.")
    lines.append("  If X < 10% of total trades: filter rarely fires, low impact expected.")
    lines.append("  If X > 30% of total trades: filter is aggressive -- check trade count drop.")
    lines.append("")
    lines.append("  Decision rules:")
    lines.append("    WR improves AND CAGR >= V34 AND trade count drop < 15% --> carry forward")
    lines.append("    WR improves AND CAGR drops > 1pp --> same crash-recovery problem, reject")
    lines.append("    WR unchanged AND trade count drops --> filter is noise, reject")
    lines.append("")

    if baseline_live and len(all_metrics) > 1:
        v37 = next((m for m in all_metrics if "vol" in m["experiment"].lower()), None)
        if v37 and "year_stats" in baseline_live and "year_stats" in v37:
            b_years = baseline_live["year_stats"]
            v_years = v37["year_stats"]
            lines.append("  Year-by-year P&L delta (V37 vs baseline):")
            lines.append(f"  {'Year':<6} {'Baseline':>14} {'V37':>14} {'Delta':>14} "
                         f"{'Base WR':>9} {'V37 WR':>9} {'Base Trades':>12} {'V37 Trades':>11}")
            lines.append(f"  {'-'*90}")
            for yr in sorted(b_years.keys()):
                if yr in v_years:
                    bp  = b_years[yr]["pnl_usd"]
                    vp  = v_years[yr]["pnl_usd"]
                    bw  = b_years[yr]["win_rate"]
                    vw  = v_years[yr]["win_rate"]
                    bt  = b_years[yr]["trades"]
                    vt  = v_years[yr]["trades"]
                    delta = vp - bp
                    sign = "+" if delta >= 0 else ""
                    lines.append(f"  {yr:<6} ${bp:>12,.0f}   ${vp:>12,.0f}   "
                                 f"{sign}${abs(int(delta)):>11,}   {bw:>7.1f}%   "
                                 f"{vw:>7.1f}%   {bt:>10,}   {vt:>10,}")

    lines.append("=" * 90)
    report = "\n".join(lines)
    print(report)
    out = OUTPUT_DIR / "comparison_v37.txt"
    out.write_text(report)
    print(f"\n  Saved: {out.resolve()}")
    with open(OUTPUT_DIR / "comparison_v37.json", "w") as f:
        json.dump(all_metrics, f, indent=2, default=str)


def main():
    print("=" * 60)
    print("  V37 RUNNER -- 2 experiments, single data download")
    print("  Volume peak filter: entry only when today = highest")
    print("  volume day in the consecutive down streak")
    print("=" * 60)

    universe     = get_universe()
    price_data   = download_prices(universe)
    spy_df, vix_df, sector_data = download_reference_data()
    earnings_map = build_earnings_dates(list(price_data.keys()))

    all_metrics = []
    for cfg in EXPERIMENTS:
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
              f"WR {metrics['win_rate_pct']}% | "
              f"Trades {metrics['total_trades']:,}")

    print(f"\n{'='*60}\n  FINAL COMPARISON\n{'='*60}\n")
    print_comparison(all_metrics)
    print("\n  Done. Share results/comparison_v37.txt")


if __name__ == "__main__":
    main()
