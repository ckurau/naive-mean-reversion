# backtest-nmr-v36.py
# Runner: V34 baseline + V36a (EWMA) + V36c (inverse ETF) + V36e (bonds)
# Single data download, all 4 experiments run sequentially.
# Output: results/comparison_v36.txt

import json
from pathlib import Path
from backtest_nmr_lib_v36 import (
    EXPERIMENTS, BASELINE, V36A, V36C, V36E,
    get_universe, download_prices, download_reference_data,
    download_alternative_etfs, build_earnings_dates,
    run_backtest, compute_metrics, save_outputs,
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
    "alt_trades":         0,
    "alt_pnl_usd":        0,
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
        ("alt_trades",         "Alt Trades"),
        ("alt_pnl_usd",        "Alt P&L $"),
    ]

    display = [V34_REF] + all_metrics
    baseline_live = next((m for m in all_metrics if "baseline" in m["experiment"]), None)

    lines = []
    lines.append("=" * 115)
    lines.append("  V36 RESULTS -- EWMA Filter | Inverse ETF | Bond Allocation")
    lines.append("=" * 115)
    names = [m["experiment"] for m in display]
    header = f"  {'Metric':<26}" + "".join(f"{n:>21}" for n in names)
    lines.append(header)
    lines.append("-" * 115)

    for key, label in keys:
        row = f"  {label:<26}"
        for m in display:
            val = m.get(key, "?")
            if isinstance(val, float):
                if key == "final_equity":
                    formatted = f"${val:,.0f}"
                elif key == "alt_pnl_usd":
                    formatted = f"${val:,.0f}"
                else:
                    formatted = f"{val:.2f}"
            elif isinstance(val, int) and key in ("total_trades", "alt_trades"):
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
                    if key in ("final_equity", "alt_pnl_usd"):
                        formatted = f"{formatted}({sign}${abs(int(delta)):,})"
                    else:
                        formatted = f"{formatted}({sign}{delta:.2f})"
            row += f"{formatted:>21}"
        lines.append(row)

    lines.append("-" * 115)
    lines.append("  (+/-) vs V34_baseline control | MaxDD: less negative = better")
    lines.append("  Alt Trades = inverse ETF or bond trades (additional to main universe)")
    lines.append("")
    lines.append("  Decision rules:")
    lines.append("    V36a EWMA: CAGR neutral AND MaxDD improves --> carry forward")
    lines.append("    V36a EWMA: Trade count drops >10% --> likely blocking crash-recovery, reject")
    lines.append("    V36c Inverse: Alt P&L positive AND main strategy CAGR unchanged --> carry forward")
    lines.append("    V36e Bonds:   Alt P&L positive AND main strategy CAGR unchanged --> carry forward")
    lines.append("")

    # Year breakdown
    if baseline_live and len(all_metrics) > 1:
        lines.append("  Year-by-year P&L (delta vs V34_baseline):")
        b_years = baseline_live.get("year_stats", {})
        year_cols = [(m["experiment"], m.get("year_stats", {}))
                     for m in all_metrics if "baseline" not in m["experiment"]]
        header_yr = f"  {'Year':<6} {'Baseline':>14}" + "".join(f"{n[:12]:>14}" for n, _ in year_cols)
        lines.append(header_yr)
        lines.append(f"  {'-'*80}")
        for yr in sorted(b_years.keys()):
            bp = b_years[yr]["pnl_usd"]
            row_yr = f"  {yr:<6} ${bp:>12,.0f}"
            for name, ys in year_cols:
                if yr in ys:
                    vp = ys[yr]["pnl_usd"]
                    delta = vp - bp
                    sign = "+" if delta >= 0 else ""
                    row_yr += f"  {sign}${abs(int(delta)):>10,}"
                else:
                    row_yr += f"  {'N/A':>12}"
            lines.append(row_yr)

    lines.append("=" * 115)
    report = "\n".join(lines)
    print(report)
    out = OUTPUT_DIR / "comparison_v36.txt"
    out.write_text(report)
    print(f"\n  Saved: {out.resolve()}")
    with open(OUTPUT_DIR / "comparison_v36.json", "w") as f:
        json.dump(all_metrics, f, indent=2, default=str)


def main():
    print("=" * 65)
    print("  V36 RUNNER -- 4 experiments, single data download")
    print("  V36a: per-stock EWMA vol filter")
    print("  V36c: inverse ETF mean reversion in bear regime")
    print("  V36e: bond ETF mean reversion in bear regime")
    print("=" * 65)

    universe     = get_universe()
    price_data   = download_prices(universe)
    spy_df, vix_df, sector_data = download_reference_data()
    earnings_map = build_earnings_dates(list(price_data.keys()))

    # Download alternative ETFs for V36c and V36e
    alt_tickers = list(V36C.inverse_etfs) + [V36E.bond_etf]
    print(f"\n[Download] Fetching alternative ETFs: {alt_tickers}")
    alt_etf_data = download_alternative_etfs(alt_tickers)

    all_metrics = []
    for cfg in EXPERIMENTS:
        print(f"\n{'--'*32}")
        trades_df = run_backtest(
            price_data, spy_df, vix_df, sector_data, earnings_map,
            alt_etf_data=alt_etf_data, cfg=cfg,
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
              f"WR {metrics['win_rate_pct']}% | "
              f"Alt trades={metrics['alt_trades']} Alt P&L=${metrics['alt_pnl_usd']:,.0f}")

    print(f"\n{'='*65}\n  FINAL COMPARISON\n{'='*65}\n")
    print_comparison(all_metrics)
    print("\n  Done. Share results/comparison_v36.txt")


if __name__ == "__main__":
    main()
