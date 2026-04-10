# backtest-nmr-v35.py
from backtest_nmr_lib_v35 import (
    get_universe,
    download_prices,
    download_reference_data,
    build_earnings_dates,
    run_backtest,
    compute_metrics,
    save_outputs,
)

if __name__ == "__main__":
    universe                    = get_universe()
    price_data                  = download_prices(universe)
    spy_df, vix_df, sector_data = download_reference_data()
    earnings_map                = build_earnings_dates(list(price_data.keys()))
    trades_df                   = run_backtest(price_data, spy_df, vix_df,
                                               sector_data, earnings_map)
    if trades_df.empty:
        print("[ERROR] No trades generated.")
    else:
        metrics, eq_df = compute_metrics(trades_df)
        save_outputs(trades_df, metrics, eq_df)
