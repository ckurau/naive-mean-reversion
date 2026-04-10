# backtest-nmr-v36cv2.py
# Runner: V34 baseline vs V36c-v2 (inverse ETF using underlying overbought signal)
# Output: results/comparison_v36cv2.txt

import json
from pathlib import Path
from backtest_nmr_lib_v36cv2 import (
    EXPERIMENTS, get_universe, download_prices, download_reference_data,
    download_sh, build_earnings_dates, run_backtest, compute_metrics, save_outputs,
)

OUTPUT_DIR = Path("results")
OUTPUT_DIR.mkdir(exist_ok=True)

V34_REF = {
    "experiment":       "V34_reference",
    "cagr_pct":         18.50,
    "final_equity":     3805846,
    "win_rate_pct":     60.14,
    "profit_factor":    1.07,
    "avg_win_pct":      3.09,
    "avg_loss_pct":     -3.61,
    "max_drawdown_pct": -54.50,
    "sharpe_ratio":     0.71,
    "total_trades":     21975,
    "trades_per_year":  1024.8,
    "inv_trades":       0,
    "inv_pnl_usd":      0,
    "inv_win_rate_pct": 0,
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
        ("inv_trades",         "SH Trades"),
        ("inv_pnl_usd",        "SH Total P&L $"),
        ("inv_win_rate_pct",   "SH Win Rate %"),
    ]

    display = [V34_REF] + all_metrics
    baseline_live = next((m for m in all_metrics if "baseline" in m["experiment"]), None)

    lines = []
    lines.append("=" * 85)
    lines.append("  V36c-v2 RESULTS -- Inverse ETF (SPY overbought in bear regime)")
    lines.append("  Signal: SPY 3+ consecutive up days AND RSI(2) > 75 while below 200d MA")
    lines.append("  Entry: buy SH (1x inverse S&P 500) | Exit: SPY resumes decline OR 5d time stop")
    lines.append("=" * 85)

    names = [m["experiment"] for m in display]
    header = f"  {'Metric':<26}" + "".join(f"{n:>19}" for n in names)
    lines.append(header)
    lines.append("-" * 85)

    for key, label in keys:
        row = f"  {label:<26}"
        for m in display:
            val = m.get(key, "?")
            if isinstance(val, float):
                if key in ("final_equity", "inv_pnl_usd"):
                    formatted = f"${val:,.0f}"
                else:
                    formatted = f"{val:.2f}"
            elif isinstance(val, int) and key in ("total_trades", "inv_trades"):
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
                    if key in ("final_equity", "inv_pnl_usd"):
                        formatted = f"{formatted}({sign}${abs(int(delta)):,})"
                    else:
                        formatted = f"{formatted}({sign}{delta:.2f})"
            row += f"{formatted:>19}"
        lines.append(row)

    lines.append("-" * 85)
    lines.append("  Decision rule:")
    lines.append("    SH P&L positive AND main CAGR unchanged --> carry forward as permanent")
    lines.append("    SH P&L negative OR main CAGR drops --> reject, add to do-not-retry table")
    lines.append("")

    if baseline_live and len(all_metrics) > 1:
        v36 = next((m for m in all_metrics if "v36" in m["experiment"].lower()), None)
        if v36 and "year_stats" in baseline_live and "year_stats" in v36:
            b_years = baseline_live["year_stats"]
            v_years = v36["year_stats"]
            lines.append("  Year-by-year P&L delta (V36cv2 vs baseline):")
            lines.append(f"  {'Year':<6} {'Baseline':>14} {'V36cv2':>14} {'Delta':>14} {'Base WR':>9} {'V36 WR':>9}")
            lines.append(f"  {'-'*68}")
            for yr in sorted(b_years.keys()):
                if yr in v_years:
                    bp = b_years[yr]["pnl_usd"]
                    vp = v_years[yr]["pnl_usd"]
                    bw = b_years[yr]["win_rate"]
                    vw = v_years[yr]["win_rate"]
                    delta = vp - bp
                    sign = "+" if delta >= 0 else ""
                    marker = " <-- bear yr" if bp < 0 else ""
                    lines.append(f"  {yr:<6} ${bp:>12,.0f}   ${vp:>12,.0f}   "
                                 f"{sign}${abs(int(delta)):>11,}   {bw:>7.1f}%   {vw:>7.1f}%{marker}")

    lines.append("=" * 85)
    report = "\n".join(lines)
    print(report)
    out = OUTPUT_DIR / "comparison_v36cv2.txt"
    out.write_text(report)
    print(f"\n  Saved: {out.resolve()}")
    with open(OUTPUT_DIR / "comparison_v36cv2.json", "w") as f:
        json.dump(all_metrics, f, indent=2, default=str)


def main():
    print("=" * 60)
    print("  V36c-v2 RUNNER -- 2 experiments, single data download")
    print("  New signal: SPY overbought in bear regime --> buy SH")
    print("=" * 60)

    universe     = get_universe()
    price_data   = download_prices(universe)
    spy_df, vix_df, sector_data = download_reference_data()
    earnings_map = build_earnings_dates(list(price_data.keys()))

    print("\n[Download] Fetching SH (inverse S&P 500 ETF)...")
    sh_data = download_sh()

    all_metrics = []
    for cfg in EXPERIMENTS:
        print(f"\n{'--'*30}")
        trades_df = run_backtest(
            price_data, spy_df, vix_df, sector_data, earnings_map,
            sh_data=sh_data, cfg=cfg,
        )
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
              f"SH trades={metrics['inv_trades']} P&L=${metrics['inv_pnl_usd']:,.0f} "
              f"WR={metrics['inv_win_rate_pct']}%")

    print(f"\n{'='*60}\n  FINAL COMPARISON\n{'='*60}\n")
    print_comparison(all_metrics)
    print("\n  Done. Share results/comparison_v36cv2.txt")


if __name__ == "__main__":
    main()
