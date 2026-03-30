"""
Walk-Forward Test Framework for Naive MR Backtest
===================================================
Purpose: Validate that V7's edge is genuine and not overfitted to history.

Method:
  Split the full 2004-2026 period into rolling windows:
    - In-sample  (IS):  First N years — used to confirm parameters are working
    - Out-of-sample (OOS): Following M years — blind test, never seen before

  We do NOT re-optimise parameters in each window — the parameters are fixed
  from V7 Final. Walk-forward here tests whether the SAME parameters produce
  consistent, positive results across different time periods.

  If OOS results are consistently 30-50% below IS results but still positive,
  that is normal and expected (in-sample always looks better).
  If OOS results are negative or near zero, the strategy is likely overfit.

Windows tested (rolling, 5-year IS / 2-year OOS):
  Window 1:  IS 2004-2009  OOS 2010-2011
  Window 2:  IS 2006-2011  OOS 2012-2013
  Window 3:  IS 2008-2013  OOS 2014-2015
  Window 4:  IS 2010-2015  OOS 2016-2017
  Window 5:  IS 2012-2017  OOS 2018-2019
  Window 6:  IS 2014-2019  OOS 2020-2021
  Window 7:  IS 2016-2021  OOS 2022-2023
  Window 8:  IS 2018-2023  OOS 2024-2026

Usage:
  python walkforward.py

Output:
  results/walkforward_summary.csv   — per-window IS vs OOS metrics
  results/walkforward_equity.csv    — OOS equity curves concatenated
  results/walkforward_report.json   — full results dict
"""

import json
import warnings
import datetime
from pathlib import Path

import pandas as pd
import numpy as np

# Import everything from the main backtest module
from backtest_nmr_lib import (
    get_universe, download_prices, download_reference_data,
    build_earnings_dates, run_backtest, compute_metrics,
    INITIAL_CAPITAL
)

warnings.filterwarnings("ignore")

OUTPUT_DIR = Path("results")
OUTPUT_DIR.mkdir(exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# Walk-forward window definitions
# ─────────────────────────────────────────────────────────────────────────────
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


def slice_price_data(price_data: dict, start: str, end: str) -> dict:
    """Filter price data to a specific date range."""
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    sliced = {}
    for tkr, df in price_data.items():
        mask = (df.index >= s) & (df.index <= e)
        if mask.sum() > 220:   # need at least 200-day MA worth of data
            sliced[tkr] = df[mask]
    return sliced


def slice_reference(ref_df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    s, e = pd.Timestamp(start), pd.Timestamp(end)
    return ref_df[(ref_df.index >= s) & (ref_df.index <= e)]


def extract_key_metrics(metrics: dict) -> dict:
    """Pull just the headline numbers for the summary table."""
    return {
        "cagr_pct"          : metrics.get("cagr_pct", 0),
        "roi_per_year_pct"  : metrics.get("roi_per_year_pct", 0),
        "win_rate_pct"      : metrics.get("win_rate_pct", 0),
        "profit_factor"     : metrics.get("profit_factor", 0),
        "max_drawdown_pct"  : metrics.get("max_drawdown_pct", 0),
        "sharpe_ratio"      : metrics.get("sharpe_ratio", 0),
        "total_trades"      : metrics.get("total_trades", 0),
        "trades_per_year"   : metrics.get("trades_per_year", 0),
        "avg_win_pct"       : metrics.get("avg_win_pct", 0),
        "avg_loss_pct"      : metrics.get("avg_loss_pct", 0),
        "time_stop_rate_pct": metrics.get("time_stop_rate_pct", 0),
        "final_equity"      : metrics.get("final_equity", INITIAL_CAPITAL),
        "total_return_pct"  : metrics.get("total_return_pct", 0),
    }


def print_window_result(name: str, period: str, metrics: dict, label: str):
    m = extract_key_metrics(metrics)
    print(f"\n  [{name}] {label} ({period})")
    print(f"    CAGR: {m['cagr_pct']:>7.2f}%  |  "
          f"Win Rate: {m['win_rate_pct']:>6.2f}%  |  "
          f"Profit Factor: {m['profit_factor']:>5.2f}  |  "
          f"Max DD: {m['max_drawdown_pct']:>7.2f}%  |  "
          f"Sharpe: {m['sharpe_ratio']:>5.2f}  |  "
          f"Trades: {m['total_trades']:>5}")


def run_walk_forward(price_data, spy_df, vix_df, sector_data, earnings_map):
    print("\n" + "="*72)
    print("  WALK-FORWARD TEST — 8 WINDOWS (5yr IS / 2yr OOS)")
    print("="*72)

    all_results = []
    oos_equity_curves = []

    for w in WINDOWS:
        name = w["name"]
        print(f"\n{'─'*60}")
        print(f"  {name}: IS {w['is_start'][:4]}-{w['is_end'][:4]}  |  "
              f"OOS {w['oos_start'][:4]}-{w['oos_end'][:4]}")
        print(f"{'─'*60}")

        # Slice data for IS period
        is_prices  = slice_price_data(price_data, w["is_start"], w["is_end"])
        is_spy     = slice_reference(spy_df,  w["is_start"], w["is_end"])
        is_vix     = slice_reference(vix_df,  w["is_start"], w["is_end"])
        is_sectors = {etf: slice_reference(df, w["is_start"], w["is_end"])
                      for etf, df in sector_data.items()}

        # Slice data for OOS period (need extra MA warmup — start 200 days early)
        oos_warmup = (pd.Timestamp(w["oos_start"]) -
                      pd.DateOffset(days=300)).strftime("%Y-%m-%d")
        oos_prices_full = slice_price_data(price_data, oos_warmup, w["oos_end"])
        oos_spy    = slice_reference(spy_df,  oos_warmup, w["oos_end"])
        oos_vix    = slice_reference(vix_df,  oos_warmup, w["oos_end"])
        oos_sectors = {etf: slice_reference(df, oos_warmup, w["oos_end"])
                       for etf, df in sector_data.items()}

        # Run IS backtest
        print(f"  Running IS backtest ({len(is_prices)} tickers)...")
        try:
            is_trades = run_backtest(is_prices, is_spy, is_vix,
                                     is_sectors, earnings_map)
            if is_trades.empty:
                print(f"  [{name}] IS: No trades generated, skipping window.")
                continue
            is_metrics, _ = compute_metrics(is_trades)
            print_window_result(name,
                                f"{w['is_start'][:4]}-{w['is_end'][:4]}",
                                is_metrics, "IS ")
        except Exception as e:
            print(f"  [{name}] IS error: {e}")
            continue

        # Run OOS backtest
        print(f"  Running OOS backtest ({len(oos_prices_full)} tickers)...")
        try:
            oos_trades = run_backtest(oos_prices_full, oos_spy, oos_vix,
                                      oos_sectors, earnings_map)
            # Filter trades to actual OOS period (exclude warmup)
            if not oos_trades.empty:
                oos_trades = oos_trades[
                    oos_trades["entry_date"] >= pd.Timestamp(w["oos_start"])
                ].reset_index(drop=True)

            if oos_trades.empty:
                print(f"  [{name}] OOS: No trades in OOS window.")
                oos_metrics = {"error": "no trades"}
                oos_key = {k: 0 for k in extract_key_metrics({}).keys()}
            else:
                oos_metrics, oos_eq = compute_metrics(oos_trades)
                oos_key = extract_key_metrics(oos_metrics)
                print_window_result(name,
                                    f"{w['oos_start'][:4]}-{w['oos_end'][:4]}",
                                    oos_metrics, "OOS")
                # Tag equity curve with window name
                oos_eq["window"] = name
                oos_equity_curves.append(oos_eq)
        except Exception as e:
            print(f"  [{name}] OOS error: {e}")
            oos_key = {k: 0 for k in extract_key_metrics({}).keys()}

        # Compute IS/OOS decay ratios
        is_key = extract_key_metrics(is_metrics)
        decay = {}
        for k in ["cagr_pct", "win_rate_pct", "profit_factor", "sharpe_ratio"]:
            if is_key.get(k, 0) != 0:
                decay[f"{k}_oos_is_ratio"] = round(oos_key.get(k, 0) /
                                                    is_key.get(k, 1), 2)

        all_results.append({
            "window"    : name,
            "is_period" : f"{w['is_start'][:4]}-{w['is_end'][:4]}",
            "oos_period": f"{w['oos_start'][:4]}-{w['oos_end'][:4]}",
            **{f"is_{k}": v for k, v in is_key.items()},
            **{f"oos_{k}": v for k, v in oos_key.items()},
            **decay,
        })

    return all_results, oos_equity_curves


def save_walkforward_results(all_results, oos_equity_curves):
    if not all_results:
        print("\n[Walk-Forward] No results to save.")
        return

    summary_df = pd.DataFrame(all_results)
    summary_path = OUTPUT_DIR / "walkforward_summary.csv"
    summary_df.to_csv(summary_path, index=False)

    if oos_equity_curves:
        eq_df = pd.concat(oos_equity_curves, ignore_index=True)
        eq_df.to_csv(OUTPUT_DIR / "walkforward_equity.csv", index=False)

    with open(OUTPUT_DIR / "walkforward_report.json", "w") as f:
        json.dump(all_results, f, indent=2, default=str)

    # ── Print summary table ────────────────────────────────────────────────
    print("\n\n" + "="*72)
    print("  WALK-FORWARD SUMMARY")
    print("="*72)
    print(f"  {'Window':<6} {'OOS Period':<12} {'CAGR':>7} {'WinRate':>8} "
          f"{'PF':>6} {'MaxDD':>8} {'Sharpe':>7} {'Trades':>7} {'IS/OOS':>8}")
    print(f"  {'-'*6} {'-'*12} {'-'*7} {'-'*8} {'-'*6} {'-'*8} {'-'*7} {'-'*7} {'-'*8}")

    oos_cagrs = []
    for r in all_results:
        ratio = r.get("cagr_pct_oos_is_ratio", 0)
        cagr  = r.get("oos_cagr_pct", 0)
        oos_cagrs.append(cagr)
        print(f"  {r['window']:<6} {r['oos_period']:<12} "
              f"{cagr:>6.1f}% "
              f"{r.get('oos_win_rate_pct', 0):>7.1f}% "
              f"{r.get('oos_profit_factor', 0):>6.2f} "
              f"{r.get('oos_max_drawdown_pct', 0):>7.1f}% "
              f"{r.get('oos_sharpe_ratio', 0):>7.2f} "
              f"{r.get('oos_total_trades', 0):>7} "
              f"{ratio:>7.2f}x")

    print(f"  {'-'*72}")
    pos_windows = sum(1 for c in oos_cagrs if c > 0)
    print(f"\n  OOS Positive CAGR windows: {pos_windows}/{len(all_results)}")
    print(f"  OOS Avg CAGR:              {np.mean(oos_cagrs):.2f}%")
    print(f"  OOS Median CAGR:           {np.median(oos_cagrs):.2f}%")
    print(f"\n  Interpretation guide:")
    print(f"    IS/OOS ratio > 0.5  = strategy has genuine edge (normal decay)")
    print(f"    IS/OOS ratio 0.3-0.5 = marginal edge, use caution")
    print(f"    IS/OOS ratio < 0.3  = likely overfitted to history")
    print(f"    OOS CAGR negative   = strategy fails out-of-sample")
    print(f"\n  Results saved to: {OUTPUT_DIR.resolve()}")
    print("="*72)


if __name__ == "__main__":
    print("[Walk-Forward] Loading data (shared with backtest)...")
    universe     = get_universe()
    price_data   = download_prices(universe)
    spy_df, vix_df, sector_data = download_reference_data()
    earnings_map = build_earnings_dates(list(price_data.keys()))

    print(f"[Walk-Forward] Running {len(WINDOWS)} windows...")
    all_results, oos_eq = run_walk_forward(
        price_data, spy_df, vix_df, sector_data, earnings_map
    )
    save_walkforward_results(all_results, oos_eq)
