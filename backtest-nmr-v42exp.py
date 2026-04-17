# backtest-nmr-v42exp.py
# V42 Experimental Suite — Second batch of 4 ideas vs V35 baseline.
#
# Push both this file and backtest_nmr_lib_v42exp.py to repo root.
# Trigger "Naive MR Backtest" workflow pointing at this script.
# Results land in results/v42exp/.

from backtest_nmr_lib_v42exp import (
    get_universe, download_prices, download_reference_data,
    build_earnings_dates, run_backtest, compute_metrics, save_outputs,
    VARIANT_DESCRIPTIONS,
)

VARIANTS = ["BASELINE", "EXP_E", "EXP_F", "EXP_G", "EXP_H"]

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  V42 Experimental Suite — Second Batch")
    print("=" * 60)
    for v, desc in VARIANT_DESCRIPTIONS.items():
        print(f"  {v:<10} {desc}")
    print("=" * 60 + "\n")

    # --- 1. Download data once, shared across all variants ---
    universe     = get_universe()
    price_data   = download_prices(universe)
    spy_df, vix_df, sector_data, sector_rsi = download_reference_data()
    earnings_map = build_earnings_dates(list(price_data.keys()))

    # --- 2. Run each variant ---
    all_metrics = []
    all_trades  = {}

    for variant in VARIANTS:
        trades_df = run_backtest(
            price_data, spy_df, vix_df, sector_data, earnings_map, sector_rsi,
            variant=variant,
        )
        if trades_df.empty:
            print(f"[ERROR] {variant}: No trades generated.")
            continue
        metrics = compute_metrics(trades_df, variant)
        all_metrics.append(metrics)
        all_trades[variant] = trades_df

    # --- 3. Print comparison + save ---
    if all_metrics:
        save_outputs(all_metrics, all_trades)
    else:
        print("[ERROR] No variants produced results.")
