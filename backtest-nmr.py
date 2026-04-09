""" Naive Mean Reversion (MR) Backtest — V33d
=============================================
This file is a thin entry-point wrapper. All strategy logic, parameters,
signal generation, simulation, metrics, and output live in backtest_nmr_lib.py.
This eliminates the silent divergence risk that caused multiple debugging
sessions where backtest-nmr.py and backtest_nmr_lib.py fell out of sync.

V33d CHANGES vs V32e:
  [V33d] MAX_POSITIONS raised 40 → 60 (via V33b=50, V33c=55, V33d=60)
  [V33d] Expanded metrics: Sortino, MaxDD duration, rolling Sharpe/Sortino,
         median hold time, return std/skewness/kurtosis

RESULTS HISTORY:
  Run 5:      CAGR  7.58% | $478k
  V30:        CAGR 14.42% | $1,797k  (S&P 500+400)
  V30+S&P600: CAGR 16.01% | $2,414k
  V32e:       CAGR 16.10% | $2,454k  (composite ranking)
  V33b:       CAGR 16.83% | $2,808k  (50 positions)
  V33c:       CAGR 17.16% | $2,982k  (55 positions)
  V33d:       CAGR 17.41% | $3,124k  ← current best (taxable account)
  V32d:       CAGR 15.37% | $2,145k  ← best risk-adjusted (Roth IRA)

WHY V33d IS BEST FOR A TAXABLE ACCOUNT (despite lower Sharpe):
  Sharpe dropped from 0.73 (V32e) to 0.68 (V33d) as positions increased.
  In isolation that looks like a regression. But Sharpe measures risk-adjusted
  return per unit of total volatility — it penalises upside volatility equally
  with downside. In a taxable account compounding over 20+ years, the relevant
  question is not "smoothest ride" but "most wealth after tax".
  The position count increase captures overflow on high-signal days — the exact
  days when mean reversion edge is strongest (many stocks simultaneously oversold).
  These are episodic bursts of alpha, not persistent volatility. Sharpe penalises
  them. But the compounding effect of capturing 60 signals on a crash-recovery day
  vs 40 is +$670k over 21 years.
  The Sharpe tradeoff is real: V33d's worst years are proportionally worse
  (2022: -$1.05M vs -$691k in V32e). If you would abandon the strategy during
  a -54% drawdown, V32d or V32e is better for you. If you understand the
  strategy edge and will hold through drawdowns, V33d maximises long-term wealth.
  For a Roth IRA where drawdown management matters more: use V32d (Sharpe 0.77,
  MaxDD -39.21%).
"""
from backtest_nmr_lib import (
    get_universe,
    download_prices,
    download_reference_data,
    build_earnings_dates,
    run_backtest,
    compute_metrics,
    save_outputs,
)

if __name__ == "__main__":
    universe                     = get_universe()
    price_data                   = download_prices(universe)
    spy_df, vix_df, sector_data  = download_reference_data()
    earnings_map                 = build_earnings_dates(list(price_data.keys()))
    trades_df                    = run_backtest(price_data, spy_df, vix_df, sector_data, earnings_map)
    if trades_df.empty:
        print("[ERROR] No trades generated.")
    else:
        metrics, eq_df = compute_metrics(trades_df)
        save_outputs(trades_df, metrics, eq_df)
