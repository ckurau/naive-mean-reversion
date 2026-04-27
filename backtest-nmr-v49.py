# backtest-nmr-v49.py
# V49: V35 base (MR engine UNCHANGED) + 3 new external overlays tested on top
#
# Overlays (each independently additive to MR equity curve, using real yfinance data):
#   [OVL-A] GOLD  -- Long GLD when GLD > 200d MA + real rates falling (TLT slope)
#                    Allocation: 7% of portfolio equity per day while in position
#   [OVL-B] SECROT - Sector Rotation Momentum: long top-3 SPDR sectors by 3m momentum
#                    monthly rebalance, 3% per sector (9% total), bull regime only
#   [OVL-C] DIVCAP - Dividend Capture: long XLU + XLP around mid-month ex-div window
#                    2% per position, 3-day hold, calendar-driven
#
# Baseline reported for comparison: V48/Idea G combined ($18,323,346, CAGR 24.38%, MaxDD -56.91%)
# This script runs the full MR engine + all 3 overlays, reports each overlay's
# individual P&L and the combined impact on CAGR and MaxDD vs MR-only baseline.
#
# Run: push to GitHub, Actions -> Naive MR Backtest -> Run workflow
# Runtime: same as standard backtest (~90-120 min)

from backtest_nmr_lib_v49 import (
    get_universe, download_prices, download_reference_data,
    build_earnings_dates, run_backtest, compute_metrics, save_outputs,
)

if __name__ == "__main__":
    universe   = get_universe()
    price_data = download_prices(universe)
    spy_df, vix_df, sector_data = download_reference_data()
    earnings_map = build_earnings_dates(list(price_data.keys()))
    trades_df = run_backtest(price_data, spy_df, vix_df, sector_data, earnings_map)
    if trades_df.empty:
        print("[ERROR] No trades generated.")
    else:
        metrics, eq_df = compute_metrics(trades_df)
        save_outputs(trades_df, metrics, eq_df)
