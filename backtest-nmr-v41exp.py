# backtest-nmr-v41exp.py
# V41 Experimental Suite runner — tests all 4 ideas vs V35 baseline in one run.
#
# Push both this file and backtest_nmr_lib_v41exp.py to the repo and trigger
# your normal GitHub Actions workflow. Results land in results/v41exp/.

from backtest_nmr_lib_v41exp import (
    get_universe, download_prices, download_reference_data,
    build_earnings_dates, run_backtest, compute_metrics, save_outputs,
    VARIANT_DESCRIPTIONS,
)

VARIANTS = ["BASELINE", "EXP_A", "EXP_B", "EXP_C", "EXP_D"]

if __name__ == "__main__":
    print("\n" + "=" * 60)
    print("  V41 Experimental Suite")
    print("=" * 60)
    for v, desc in VARIANT_DESCRIPTIONS.items():
        print(f"  {v:<10} {desc}")
    print("=" * 60 + "\n")

    # --- 1. Download data once, shared across all variants ---
    universe    = get_universe()
    price_data  = download_prices(universe)
    spy_df, vix_df, sector_data, vix9d_df = download_reference_data(download_vix9d=True)
    earnings_map = build_earnings_dates(list(price_data.keys()))

    # --- 2. Run each variant ---
    all_metrics = []
    all_trades  = {}

    for variant in VARIANTS:
        trades_df = run_backtest(
            price_data, spy_df, vix_df, sector_data, earnings_map, vix9d_df,
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
