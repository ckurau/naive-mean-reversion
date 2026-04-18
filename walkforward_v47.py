# walkforward_v47.py
#
# Walk-forward validation for V47.
# Identical window structure and methodology as walkforward.py (V34/V35).
# Imports run_backtest from backtest_nmr_lib_v47 so all V47 parameters
# (TOM, VIX RSI, partial trigger, DOW) are active in every window.
#
# V34 walk-forward result for reference:
#   OOS positive CAGR windows: 7/8 — PASS
#   OOS Avg CAGR: 19.45% | OOS Median CAGR: 19.99%
#
# V47 changes don't alter signal selection (same RSI<20/consec_down/ATR
# entry filters) — only sizing is affected. The WF therefore tests whether
# the sizing overlays are robust across regimes.
#
# Windows (identical to V34/V35 WF):
#   W1: IS 2004-2008  OOS 2009-2010
#   W2: IS 2006-2010  OOS 2011-2012
#   W3: IS 2008-2012  OOS 2013-2014
#   W4: IS 2010-2014  OOS 2015-2016
#   W5: IS 2012-2016  OOS 2017-2018
#   W6: IS 2014-2018  OOS 2019-2020
#   W7: IS 2016-2020  OOS 2021-2022  <- weak window historically
#   W8: IS 2018-2022  OOS 2023-2025  <- weak window historically
#
# Usage: python walkforward_v47.py
# Output: results/v47/walkforward_summary.csv
#         results/v47/walkforward_report.json

import json
import warnings
import datetime
from pathlib import Path

import pandas as pd
import numpy as np

from backtest_nmr_lib_v47 import (
    get_universe,
    download_prices,
    download_reference_data,
    build_earnings_dates,
    run_backtest,
    compute_metrics,
    INITIAL_CAPITAL,
    VERSION_TAG,
)

warnings.filterwarnings("ignore")

OUTPUT_DIR = Path("results/v47")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# Walk-forward windows (identical to V34/V35)
# ---------------------------------------------------------------------------
WINDOWS = [
    {"name": "W1", "is_start": "2004-01-01", "is_end": "2008-12-31", "oos_start": "2009-01-01", "oos_end": "2010-12-31"},
    {"name": "W2", "is_start": "2006-01-01", "is_end": "2010-12-31", "oos_start": "2011-01-01", "oos_end": "2012-12-31"},
    {"name": "W3", "is_start": "2008-01-01", "is_end": "2012-12-31", "oos_start": "2013-01-01", "oos_end": "2014-12-31"},
    {"name": "W4", "is_start": "2010-01-01", "is_end": "2014-12-31", "oos_start": "2015-01-01", "oos_end": "2016-12-31"},
    {"name": "W5", "is_start": "2012-01-01", "is_end": "2016-12-31", "oos_start": "2017-01-01", "oos_end": "2018-12-31"},
    {"name": "W6", "is_start": "2014-01-01", "is_end": "2018-12-31", "oos_start": "2019-01-01", "oos_end": "2020-12-31"},
    {"name": "W7", "is_start": "2016-01-01", "is_end": "2020-12-31", "oos_start": "2021-01-01", "oos_end": "2022-12-31"},
    {"name": "W8", "is_start": "2018-01-01", "is_end": "2022-12-31", "oos_start": "2023-01-01", "oos_end": "2025-12-31"},
]

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def slice_price_data(price_data: dict, start: str, end: str) -> dict:
    s, e    = pd.Timestamp(start), pd.Timestamp(end)
    sliced  = {}
    for tkr, df in price_data.items():
        mask = (df.index >= s) & (df.index <= e)
        if mask.sum() > 220:
            sliced[tkr] = df[mask]
    return sliced

def slice_reference(ref_df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    return ref_df[(ref_df.index >= s) & (ref_df.index <= e)]

def extract_key_metrics(metrics: dict) -> dict:
    return {
        "cagr_pct":          metrics.get("cagr_pct", 0),
        "win_rate_pct":      metrics.get("win_rate_pct", 0),
        "profit_factor":     metrics.get("profit_factor", 0),
        "max_drawdown_pct":  metrics.get("max_drawdown_pct", 0),
        "sharpe_ratio":      metrics.get("sharpe_ratio", 0),
        "total_trades":      metrics.get("total_trades", 0),
        "trades_per_year":   metrics.get("trades_per_year", 0),
        "avg_win_pct":       metrics.get("avg_win_pct", 0),
        "avg_loss_pct":      metrics.get("avg_loss_pct", 0),
        "final_equity":      metrics.get("final_equity", INITIAL_CAPITAL),
    }

def print_window_result(name: str, period: str, metrics: dict, label: str):
    m = extract_key_metrics(metrics)
    print(f"\n  [{name}] {label} ({period})")
    print(f"    CAGR: {m['cagr_pct']:>7.2f}% | "
          f"WR: {m['win_rate_pct']:>6.2f}% | "
          f"PF: {m['profit_factor']:>5.2f} | "
          f"MaxDD: {m['max_drawdown_pct']:>7.2f}% | "
          f"Sharpe: {m['sharpe_ratio']:>5.2f} | "
          f"Trades: {m['total_trades']:>5}")

# ---------------------------------------------------------------------------
# Main walk-forward loop
# ---------------------------------------------------------------------------
def run_walk_forward(price_data, spy_df, vix_df, sector_data, earnings_map):
    print("\n" + "=" * 72)
    print(f" {VERSION_TAG} WALK-FORWARD — 8 WINDOWS (5yr IS / 2yr OOS)")
    print("=" * 72)

    all_results       = []
    oos_equity_curves = []

    for w in WINDOWS:
        name = w["name"]
        print(f"\n{'─'*60}")
        print(f"  {name}: IS {w['is_start'][:4]}-{w['is_end'][:4]} | "
              f"OOS {w['oos_start'][:4]}-{w['oos_end'][:4]}")
        print(f"{'─'*60}")

        # IS slice
        is_prices  = slice_price_data(price_data, w["is_start"], w["is_end"])
        is_spy     = slice_reference(spy_df, w["is_start"], w["is_end"])
        is_vix     = slice_reference(vix_df, w["is_start"], w["is_end"])
        is_sectors = {etf: slice_reference(df, w["is_start"], w["is_end"])
                      for etf, df in sector_data.items()}

        # OOS slice (300-day warmup for MA calculations)
        oos_warmup     = (pd.Timestamp(w["oos_start"]) - pd.DateOffset(days=300)).strftime("%Y-%m-%d")
        oos_prices_full = slice_price_data(price_data, oos_warmup, w["oos_end"])
        oos_spy        = slice_reference(spy_df, oos_warmup, w["oos_end"])
        oos_vix        = slice_reference(vix_df, oos_warmup, w["oos_end"])
        oos_sectors    = {etf: slice_reference(df, oos_warmup, w["oos_end"])
                          for etf, df in sector_data.items()}

        # IS backtest
        print(f"  Running IS ({len(is_prices)} tickers)...")
        try:
            is_trades = run_backtest(is_prices, is_spy, is_vix, is_sectors, earnings_map)
            if is_trades.empty:
                print(f"  [{name}] IS: No trades, skipping window.")
                continue
            is_metrics, _ = compute_metrics(is_trades)
            print_window_result(name, f"{w['is_start'][:4]}-{w['is_end'][:4]}", is_metrics, "IS ")
        except Exception as e:
            print(f"  [{name}] IS error: {e}")
            continue

        # OOS backtest
        print(f"  Running OOS ({len(oos_prices_full)} tickers)...")
        try:
            oos_trades = run_backtest(oos_prices_full, oos_spy, oos_vix, oos_sectors, earnings_map)
            if not oos_trades.empty:
                oos_trades = oos_trades[
                    oos_trades["entry_date"] >= pd.Timestamp(w["oos_start"])
                ].reset_index(drop=True)

            if oos_trades.empty:
                print(f"  [{name}] OOS: No trades in window.")
                oos_key = {k: 0 for k in extract_key_metrics({}).keys()}
            else:
                oos_metrics, oos_eq = compute_metrics(oos_trades)
                oos_key = extract_key_metrics(oos_metrics)
                print_window_result(name, f"{w['oos_start'][:4]}-{w['oos_end'][:4]}", oos_metrics, "OOS")
                oos_eq["window"] = name
                oos_equity_curves.append(oos_eq)

        except Exception as e:
            print(f"  [{name}] OOS error: {e}")
            oos_key = {k: 0 for k in extract_key_metrics({}).keys()}

        is_key = extract_key_metrics(is_metrics)
        decay  = {}
        for k in ["cagr_pct", "win_rate_pct", "profit_factor", "sharpe_ratio"]:
            if is_key.get(k, 0) != 0:
                decay[f"{k}_oos_is_ratio"] = round(oos_key.get(k, 0) / is_key.get(k, 1), 2)

        all_results.append({
            "window":     name,
            "is_period":  f"{w['is_start'][:4]}-{w['is_end'][:4]}",
            "oos_period": f"{w['oos_start'][:4]}-{w['oos_end'][:4]}",
            **{f"is_{k}":  v for k, v in is_key.items()},
            **{f"oos_{k}": v for k, v in oos_key.items()},
            **decay,
        })

    return all_results, oos_equity_curves

# ---------------------------------------------------------------------------
# Save and print
# ---------------------------------------------------------------------------
def save_walkforward_results(all_results, oos_equity_curves):
    if not all_results:
        print("\n[Walk-Forward] No results to save.")
        return

    summary_df = pd.DataFrame(all_results)
    summary_df.to_csv(OUTPUT_DIR / "walkforward_summary.csv", index=False)

    if oos_equity_curves:
        eq_df = pd.concat(oos_equity_curves, ignore_index=True)
        eq_df.to_csv(OUTPUT_DIR / "walkforward_equity.csv", index=False)

    with open(OUTPUT_DIR / "walkforward_report.json", "w") as f:
        json.dump(all_results, f, indent=2, default=str)

    # Print summary table
    print("\n\n" + "=" * 80)
    print(f" {VERSION_TAG} WALK-FORWARD SUMMARY")
    print("=" * 80)
    print(f"  {'Window':<6} {'OOS Period':<12} {'OOS CAGR':>9} {'OOS WR':>8} "
          f"{'OOS PF':>7} {'OOS MaxDD':>9} {'OOS Sharpe':>10} {'Trades':>7} {'IS/OOS':>8}")
    print(f"  {'-'*6} {'-'*12} {'-'*9} {'-'*8} {'-'*7} {'-'*9} {'-'*10} {'-'*7} {'-'*8}")

    oos_cagrs = []
    for r in all_results:
        ratio = r.get("cagr_pct_oos_is_ratio", 0)
        cagr  = r.get("oos_cagr_pct", 0)
        oos_cagrs.append(cagr)
        print(f"  {r['window']:<6} {r['oos_period']:<12} "
              f"{cagr:>8.1f}% "
              f"{r.get('oos_win_rate_pct', 0):>7.1f}% "
              f"{r.get('oos_profit_factor', 0):>7.2f} "
              f"{r.get('oos_max_drawdown_pct', 0):>8.1f}% "
              f"{r.get('oos_sharpe_ratio', 0):>10.2f} "
              f"{r.get('oos_total_trades', 0):>7} "
              f"{ratio:>7.2f}x")

    print(f"  {'─'*80}")
    pos_windows = sum(1 for c in oos_cagrs if c > 0)
    print(f"\n  OOS Positive CAGR windows: {pos_windows}/{len(all_results)}")
    print(f"  OOS Avg CAGR:    {np.mean(oos_cagrs):.2f}%")
    print(f"  OOS Median CAGR: {np.median(oos_cagrs):.2f}%")
    print(f"\n  V34/V35 reference: 7/8 positive | Avg 19.45% | Median 19.99%")
    print(f"\n  Pass criteria: ≥7/8 positive OOS windows")
    print(f"  IS/OOS ratio >0.5 = genuine edge | 0.3-0.5 = marginal | <0.3 = overfit")
    print(f"\n  Results saved to: {OUTPUT_DIR.resolve()}")
    print("=" * 80)

# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print(f"[Walk-Forward] {VERSION_TAG} — loading data...")
    universe     = get_universe()
    price_data   = download_prices(universe)
    spy_df, vix_df, sector_data = download_reference_data()
    earnings_map = build_earnings_dates(list(price_data.keys()))

    print(f"[Walk-Forward] Running {len(WINDOWS)} windows...")
    all_results, oos_eq = run_walk_forward(
        price_data, spy_df, vix_df, sector_data, earnings_map
    )
    save_walkforward_results(all_results, oos_eq)
