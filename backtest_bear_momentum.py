# backtest_bear_momentum.py
#
# Dual Momentum Bear Regime Strategy -- Standalone Backtest
#
# WHAT THIS TESTS:
#   When SPY is below its 200-day MA (bear regime), instead of holding cash,
#   rotate monthly into the top-ranked instrument from a defensive universe
#   based on 3-month (63-day) momentum.
#
# UNIVERSE (6 instruments):
#   GLD  -- Gold ETF (inflation hedge, safe haven)
#   TLT  -- 20yr Treasury bonds (flight to safety -- BUT failed 2022)
#   SH   -- Inverse S&P 500 (1x short, no daily decay vs SPXU)
#   XLE  -- Energy sector (commodity inflation hedge)
#   XLU  -- Utilities (defensive, dividend income)
#   VIXY -- VIX short-term futures (volatility spike protection)
#
# RULES:
#   1. Check SPY vs 200d MA daily
#   2. When SPY crosses BELOW 200d MA: enter bear mode
#   3. In bear mode: on the 1st trading day of each month,
#      rank universe by 63-day return, buy top 1 instrument
#      (or top 2 equally weighted if TOP_N = 2)
#   4. When SPY crosses BACK ABOVE 200d MA: exit all positions, return to cash
#   5. No leverage. Long only (SH is already short exposure, no SPXU/SQQQ)
#
# WHY THIS DESIGN:
#   - Monthly rotation avoids daily rebalancing decay (kills inverse ETFs held daily)
#   - 63-day momentum is slow enough to avoid whipsaws, fast enough to adapt
#   - Universe chosen to be non-correlated: gold, bonds, short equity, energy,
#     defensive equity, volatility -- at least one tends to work in any bear type
#   - SH (1x inverse) not SPXU (3x) -- avoids leveraged decay
#   - TLT included but will rank last in rate-hike bears (2022) -- self-correcting
#
# HONEST LIMITATIONS:
#   - VIXY has significant decay even held monthly -- may underperform
#   - This is in-sample on 2004-2026. Walk-forward required before live use.
#   - Bear periods are short enough that results may have high variance
#   - Does NOT account for taxes on frequent rotation
#
# COMPARE AGAINST:
#   - Cash (0% return) during bear regime
#   - SPY buy-and-hold through bear regime (benchmark for how bad it gets)
#   - SH buy-and-hold through bear regime (simple alternative)

import datetime
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from tqdm import tqdm

# =============================================================================
# Config
# =============================================================================
START_DATE     = "2004-01-01"
END_DATE       = datetime.date.today().isoformat()
INITIAL_CAPITAL = 100_000.0

# Universe of instruments to rotate through during bear regime
UNIVERSE = ["GLD", "TLT", "SH", "XLE", "XLU", "VIXY"]

# Number of top-ranked instruments to hold (equal weight if > 1)
TOP_N = 1

# Momentum lookback in trading days
MOMENTUM_DAYS = 63   # ~3 months

# SPY 200d MA filter
SPY_MA_WINDOW = 200

# Minimum momentum to enter (don't buy something falling hard even if top-ranked)
# Set to None to disable. -0.05 means skip if 63d return < -5%.
MIN_MOMENTUM_TO_ENTER = None

OUTPUT_DIR = Path("results_bear")
OUTPUT_DIR.mkdir(exist_ok=True)

# =============================================================================
# Download
# =============================================================================
def download_all():
    tickers = ["SPY"] + UNIVERSE
    print(f"[Download] Fetching: {tickers}")
    raw = yf.download(tickers, start=START_DATE, end=END_DATE,
                      auto_adjust=True, progress=False, threads=True)
    data = {}
    if isinstance(raw.columns, pd.MultiIndex):
        for tkr in tickers:
            try:
                df = raw.xs(tkr, axis=1, level=1).dropna(how="all")
                if not df.empty:
                    data[tkr] = df
                    print(f"  {tkr}: {len(df)} rows")
            except KeyError:
                print(f"  {tkr}: NOT FOUND")
    else:
        data["SPY"] = raw
    return data

# =============================================================================
# Bear regime detection
# =============================================================================
def get_spy_regime(spy_df):
    close = spy_df["Close"].squeeze()
    ma200 = close.rolling(SPY_MA_WINDOW).mean()
    above = close > ma200
    return above   # True = bull, False = bear

# =============================================================================
# Backtest
# =============================================================================
def run_backtest(data):
    spy_df  = data["SPY"]
    regime  = get_spy_regime(spy_df)
    spy_close = spy_df["Close"].squeeze()

    # Align all dates
    all_dates = sorted(spy_df.index)

    # Precompute close series for universe
    closes = {}
    for tkr in UNIVERSE:
        if tkr in data:
            closes[tkr] = data[tkr]["Close"].squeeze()

    portfolio_value  = INITIAL_CAPITAL
    cash             = INITIAL_CAPITAL
    holdings         = {}    # {ticker: shares}
    in_bear          = False
    last_rebal_month = None
    trades           = []
    equity_curve     = []
    bear_periods     = []
    bear_start       = None

    # Benchmarks: track SPY B&H and SH B&H through same bear periods
    spy_bh_value     = INITIAL_CAPITAL
    sh_bh_value      = INITIAL_CAPITAL
    cash_value       = INITIAL_CAPITAL

    print(f"\n[Backtest] Running dual momentum bear regime strategy...")

    for today in tqdm(all_dates, desc="Simulating"):
        if today not in regime.index:
            continue

        spy_above = bool(regime.loc[today])
        spy_price = float(spy_close.loc[today]) if today in spy_close.index else None

        # --- Regime transition: bull -> bear ---
        if not spy_above and not in_bear:
            in_bear = True
            bear_start = today
            last_rebal_month = None
            print(f"  [BEAR START] {today.date()} | SPY: {spy_price:.2f}")

        # --- Regime transition: bear -> bull ---
        if spy_above and in_bear:
            in_bear = False
            duration = (today - bear_start).days
            bear_periods.append({'start': bear_start, 'end': today, 'days': duration})
            print(f"  [BEAR END]   {today.date()} | Duration: {duration}d | "
                  f"Portfolio: ${portfolio_value:,.0f}")

            # Exit all positions
            for tkr, shares in list(holdings.items()):
                if tkr in closes and today in closes[tkr].index:
                    price  = float(closes[tkr].loc[today])
                    proceeds = shares * price
                    cash += proceeds
                    trades.append({
                        'date': today, 'action': 'SELL', 'ticker': tkr,
                        'shares': shares, 'price': price,
                        'value': proceeds, 'reason': 'regime_exit'
                    })
                    print(f"    EXIT: {tkr} {shares:.2f}sh @ ${price:.2f} = ${proceeds:,.0f}")
            holdings = {}
            portfolio_value = cash

        # --- Monthly rebalance during bear ---
        current_month = today.month if hasattr(today, 'month') else pd.Timestamp(today).month

        if in_bear and current_month != last_rebal_month:
            last_rebal_month = current_month

            # Rank universe by 63-day momentum
            scores = {}
            for tkr in UNIVERSE:
                if tkr not in closes:
                    continue
                s = closes[tkr]
                if today not in s.index:
                    continue
                idx = s.index.get_loc(today)
                if idx < MOMENTUM_DAYS:
                    continue
                price_now  = float(s.iloc[idx])
                price_then = float(s.iloc[idx - MOMENTUM_DAYS])
                if price_then <= 0:
                    continue
                momentum = (price_now / price_then) - 1

                if MIN_MOMENTUM_TO_ENTER is not None and momentum < MIN_MOMENTUM_TO_ENTER:
                    continue

                scores[tkr] = momentum

            if not scores:
                # No valid signals -- stay in cash
                equity_curve.append({'date': today, 'portfolio': cash,
                                     'in_bear': True, 'holdings': 'CASH'})
                continue

            # Select top N
            ranked  = sorted(scores.items(), key=lambda x: -x[1])
            top     = [t for t, _ in ranked[:TOP_N]]
            top_str = ", ".join([f"{t}({scores[t]:+.1%})" for t in top])
            print(f"  [REBAL] {today.date()} | Top: {top_str}")

            # Exit current holdings not in top
            for tkr, shares in list(holdings.items()):
                if tkr not in top:
                    if tkr in closes and today in closes[tkr].index:
                        price    = float(closes[tkr].loc[today])
                        proceeds = shares * price
                        cash    += proceeds
                        trades.append({
                            'date': today, 'action': 'SELL', 'ticker': tkr,
                            'shares': shares, 'price': price,
                            'value': proceeds, 'reason': 'rebalance'
                        })
                    del holdings[tkr]

            # Allocate equally to top N
            alloc_per = cash / len(top) if cash > 0 else 0
            remaining_alloc = cash

            for i, tkr in enumerate(top):
                if tkr not in closes or today not in closes[tkr].index:
                    continue
                price  = float(closes[tkr].loc[today])
                alloc  = remaining_alloc / (len(top) - i)
                shares = alloc / price
                cost   = shares * price
                cash  -= cost
                remaining_alloc -= cost

                if tkr in holdings:
                    holdings[tkr] += shares
                else:
                    holdings[tkr] = shares

                trades.append({
                    'date': today, 'action': 'BUY', 'ticker': tkr,
                    'shares': shares, 'price': price,
                    'value': cost, 'reason': 'rebalance'
                })

        # --- Mark to market ---
        mtm = cash
        for tkr, shares in holdings.items():
            if tkr in closes and today in closes[tkr].index:
                mtm += shares * float(closes[tkr].loc[today])

        portfolio_value = mtm
        holding_str = "+".join(holdings.keys()) if holdings else "CASH"
        equity_curve.append({
            'date': today, 'portfolio': portfolio_value,
            'in_bear': in_bear, 'holdings': holding_str
        })

    print(f"\n[Backtest] Complete.")
    return pd.DataFrame(trades), pd.DataFrame(equity_curve), bear_periods

# =============================================================================
# Metrics
# =============================================================================
def compute_metrics(trades_df, equity_df, bear_periods, data):
    spy_close  = data["SPY"]["Close"].squeeze()

    # Only evaluate during bear periods
    bear_eq = equity_df[equity_df["in_bear"] == True].copy()

    if bear_eq.empty:
        print("[Metrics] No bear period data.")
        return {}

    # Strategy performance during bear periods only
    # Reset capital at start of each bear period for clean comparison
    bear_results = []
    for period in bear_periods:
        mask = ((equity_df["date"] >= period["start"]) &
                (equity_df["date"] <= period["end"]))
        sub  = equity_df[mask].copy()
        if sub.empty:
            continue

        start_val = sub.iloc[0]["portfolio"]
        end_val   = sub.iloc[-1]["portfolio"]
        ret       = (end_val / start_val - 1) * 100
        days      = period["days"]

        # SPY return over same period
        spy_start = float(spy_close.loc[spy_close.index >= period["start"]].iloc[0]) if any(spy_close.index >= period["start"]) else None
        spy_end   = float(spy_close.loc[spy_close.index <= period["end"]].iloc[-1])  if any(spy_close.index <= period["end"])  else None
        spy_ret   = (spy_end / spy_start - 1) * 100 if spy_start and spy_end else 0

        # SH return (inverse of SPY approximately)
        sh_ret = -spy_ret * 0.95  # approximate, SH has slight decay

        bear_results.append({
            'start':     period["start"].date(),
            'end':       period["end"].date(),
            'days':      days,
            'strat_ret': round(ret, 2),
            'spy_ret':   round(spy_ret, 2),
            'sh_approx': round(sh_ret, 2),
            'cash_ret':  0.0,
            'vs_cash':   round(ret, 2),
            'vs_spy':    round(ret - spy_ret, 2),
        })

    results_df = pd.DataFrame(bear_results)

    # Full-period metrics
    eq_df = equity_df.copy()
    eq_df["date"] = pd.to_datetime(eq_df["date"])
    eq_df = eq_df.set_index("date")

    final_val   = float(eq_df["portfolio"].iloc[-1])
    start_dt    = pd.to_datetime(equity_df["date"].iloc[0])
    end_dt      = pd.to_datetime(equity_df["date"].iloc[-1])
    years       = max((end_dt - start_dt).days / 365.25, 1e-6)
    cagr        = (final_val / INITIAL_CAPITAL) ** (1 / years) - 1

    monthly_ret = eq_df["portfolio"].resample("ME").last().ffill().pct_change().dropna()
    sharpe      = (monthly_ret.mean() / monthly_ret.std() * np.sqrt(12)
                   if monthly_ret.std() > 0 else 0)

    eq_df["peak"] = eq_df["portfolio"].cummax()
    eq_df["dd"]   = (eq_df["portfolio"] - eq_df["peak"]) / eq_df["peak"] * 100
    max_dd        = eq_df["dd"].min()

    # Bear-only metrics
    total_bear_days = sum(p["days"] for p in bear_periods)
    avg_strat_ret   = results_df["strat_ret"].mean()
    avg_spy_ret     = results_df["spy_ret"].mean()
    wins            = (results_df["strat_ret"] > 0).sum()

    metrics = {
        "strategy":              f"Dual Momentum Bear Regime (TOP_N={TOP_N})",
        "universe":              UNIVERSE,
        "momentum_days":         MOMENTUM_DAYS,
        "period":                f"{START_DATE} to {END_DATE}",
        "initial_capital":       INITIAL_CAPITAL,
        "final_equity":          round(final_val, 2),
        "cagr_full_period_pct":  round(cagr * 100, 2),
        "sharpe_full_period":    round(sharpe, 2),
        "max_drawdown_pct":      round(max_dd, 2),
        "bear_periods_count":    len(bear_periods),
        "total_bear_days":       total_bear_days,
        "bear_pct_of_time":      round(total_bear_days / ((end_dt - start_dt).days) * 100, 1),
        "avg_bear_duration_days": round(results_df["days"].mean(), 0),
        "strategy_positive_bear_periods": int(wins),
        "avg_strategy_return_per_bear":   round(avg_strat_ret, 2),
        "avg_spy_return_per_bear":        round(avg_spy_ret, 2),
        "avg_outperformance_vs_spy":      round(avg_strat_ret - avg_spy_ret, 2),
        "per_period_results":    results_df.to_dict(orient="records"),
    }

    return metrics, results_df

# =============================================================================
# Print results
# =============================================================================
def print_results(metrics, results_df):
    print("\n" + "=" * 65)
    print(f" DUAL MOMENTUM BEAR REGIME STRATEGY -- RESULTS")
    print("=" * 65)
    print(f"\n  Strategy      : {metrics['strategy']}")
    print(f"  Universe      : {', '.join(metrics['universe'])}")
    print(f"  Momentum      : {metrics['momentum_days']} trading days (~3 months)")
    print(f"  Period        : {metrics['period']}")
    print()
    print(f"  Full-period metrics (including bull periods in cash):")
    print(f"    Final equity      : ${metrics['final_equity']:>12,.2f}")
    print(f"    CAGR              : {metrics['cagr_full_period_pct']:>8.2f}%")
    print(f"    Sharpe            : {metrics['sharpe_full_period']:>8.2f}")
    print(f"    Max Drawdown      : {metrics['max_drawdown_pct']:>8.2f}%")
    print()
    print(f"  Bear regime summary:")
    print(f"    Bear periods      : {metrics['bear_periods_count']}")
    print(f"    Total bear days   : {metrics['total_bear_days']:,} ({metrics['bear_pct_of_time']}% of time)")
    print(f"    Avg duration      : {metrics['avg_bear_duration_days']:.0f} days")
    print(f"    Profitable periods: {metrics['strategy_positive_bear_periods']} / {metrics['bear_periods_count']}")
    print(f"    Avg strat return  : {metrics['avg_strategy_return_per_bear']:>+.2f}%")
    print(f"    Avg SPY return    : {metrics['avg_spy_return_per_bear']:>+.2f}%")
    print(f"    Avg vs SPY        : {metrics['avg_outperformance_vs_spy']:>+.2f}pp")
    print()
    print(f"  Per-period breakdown:")
    print(f"  {'Start':<12} {'End':<12} {'Days':>5} {'Strategy':>10} {'SPY':>8} {'vs SPY':>8} {'vs Cash':>8}")
    print(f"  {'-'*65}")
    for _, row in results_df.iterrows():
        vs_spy_str = f"{row['vs_spy']:>+.1f}pp"
        print(f"  {str(row['start']):<12} {str(row['end']):<12} "
              f"{row['days']:>5} {row['strat_ret']:>+9.1f}% "
              f"{row['spy_ret']:>+7.1f}% {vs_spy_str:>8} "
              f"{row['vs_cash']:>+7.1f}pp")
    print("=" * 65)

# =============================================================================
# Main
# =============================================================================
if __name__ == "__main__":
    data = download_all()

    if "SPY" not in data:
        print("[ERROR] Could not download SPY data.")
        exit(1)

    trades_df, equity_df, bear_periods = run_backtest(data)

    if equity_df.empty:
        print("[ERROR] No equity curve generated.")
        exit(1)

    result = compute_metrics(trades_df, equity_df, bear_periods, data)
    if isinstance(result, tuple):
        metrics, results_df = result
    else:
        print("[ERROR] Metrics computation failed.")
        exit(1)

    print_results(metrics, results_df)

    # Save outputs
    trades_df.to_csv(OUTPUT_DIR / "bear_trades.csv", index=False)
    equity_df.to_csv(OUTPUT_DIR / "bear_equity_curve.csv", index=False)
    results_df.to_csv(OUTPUT_DIR / "bear_period_results.csv", index=False)
    with open(OUTPUT_DIR / "bear_metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, default=str)

    print(f"\n  Results saved to: {OUTPUT_DIR.resolve()}/")
    print(f"  Files: bear_trades.csv, bear_equity_curve.csv, "
          f"bear_period_results.csv, bear_metrics.json")
