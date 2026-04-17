# backtest_ideas_v5_run.py (fixed)
# Ideas V5 runner — 8 tests vs V35+I3 baseline.
# Push both this file and backtest_ideas_v5.py to repo root.
# Trigger "Ideas V5 Backtest" workflow.

from backtest_ideas_v5 import (
    get_universe, download_prices, download_reference_data,
    build_earnings_dates, run_backtest, compute_metrics, save_outputs,
    TEST_DESCRIPTIONS,
)

TESTS = [
    "BASELINE_V35I3",
    "A_VOL_EXIT",
    "B_TOM_SIZING",
    "C_VIX_RSI",
    "D_PARTIAL_TUNE",
    "E_EARNINGS_EXT",
    "F_COMBO_ACB",
    "G_COMBO_ACD",
    "H_COMBO_BCD",
]

if __name__ == "__main__":
    print("\n" + "=" * 70)
    print("  Ideas V5 Backtest Suite (fixed)")
    print("  Baseline: V35+I3 (19.71% CAGR, $4,513,155, MaxDD -52.87%)")
    print("  Key fixes: put spread payout logic, TOM exact window, C/E overrides")
    print("=" * 70)
    for t, desc in TEST_DESCRIPTIONS.items():
        print(f"  {t:<18} {desc}")
    print("=" * 70 + "\n")

    universe     = get_universe()
    price_data   = download_prices(universe)
    spy_df, vix_df, sector_data = download_reference_data()
    earnings_map = build_earnings_dates(list(price_data.keys()))

    all_metrics = []
    all_trades  = {}

    for test_id in TESTS:
        trades_df, put_pnl = run_backtest(
            price_data, spy_df, vix_df, sector_data, earnings_map,
            test_id=test_id,
        )
        if trades_df.empty:
            print(f"[ERROR] {test_id}: no trades generated")
            continue
        metrics = compute_metrics(trades_df, put_pnl, test_id)
        all_metrics.append(metrics)
        all_trades[test_id] = trades_df
        print(f"  -> {test_id}: CAGR {metrics.get('cagr_pct','?')}%  "
              f"Equity ${metrics.get('final_equity',0):,.0f}  "
              f"MaxDD {metrics.get('max_drawdown_pct','?')}%  "
              f"Sharpe {metrics.get('sharpe_ratio','?')}  "
              f"PutNet ${metrics.get('put_spread_net',0):,.0f}")

    if all_metrics:
        save_outputs(all_metrics, all_trades)
    else:
        print("[ERROR] No tests produced results.")
