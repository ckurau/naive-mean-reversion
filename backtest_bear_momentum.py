# backtest_bear_momentum.py
#
# Bear Regime Strategy -- BTAL + GLD Fixed Allocation
#
# WHAT THIS TESTS:
#   When SPY is in a CONFIRMED bear regime (below 200d MA AND 200d MA slope declining),
#   deploy capital into:
#     25% BTAL  -- long low-beta / short high-beta (negative equity beta ~-0.4)
#     25% GLD   -- gold (safe haven, inflation hedge)
#     50% cash  -- T-bill equivalent (no yield modeled, conservative)
#
# WHY BTAL + GLD:
#   Per QuantSeeker research, BTAL and GLD are the two assets with the most
#   consistent positive Sharpe ratios below the 200d MA across all bear types.
#   BTAL is structural (negative beta by construction), not regime-dependent.
#   GLD covers inflationary bears. Together they cover:
#     - Deflationary bear (2008): BTAL + GLD both positive
#     - Inflationary bear (2022): GLD positive, BTAL somewhat positive
#     - Rate-hike bear: BTAL positive (TLT fails here -- excluded)
#     - COVID crash: Both held up during the acute phase
#
# WHY NOT TLT:
#   TLT is conditional -- works in deflation (2008) but lost heavily in 2022.
#
# WHY NOT XLE, USO, VIXY:
#   XLE: commodity play, only works in inflationary bears
#   USO: underperforms in bear markets per academic research
#   VIXY: structural decay, destroyed capital in prior backtests
#
# REGIME FILTER:
#   Confirmed bear = SPY below 200d MA AND 200d MA slope negative over 20 days.
#   Eliminates short whipsaw periods (1-8 days) that dominated prior results.
#
# PRIOR TEST COMPARISON:
#   Momentum rotation (no VIXY) : CAGR -0.05%, MaxDD -57.5%
#   MA slope + momentum         : CAGR -1.58%, MaxDD -61.0%
#   50% GLD + 50% cash          : CAGR +0.58%, MaxDD -54.0%
#   BTAL(25%) + GLD(25%) + cash : this run

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
START_DATE      = "2004-01-01"
END_DATE        = datetime.date.today().isoformat()
INITIAL_CAPITAL = 100_000.0

# Instruments to hold during bear regime + their target allocations
# Remaining cash = 1 - sum(allocations) = 50%
BEAR_HOLDINGS = {
    "BTAL": 0.25,   # 25% -- long low-beta / short high-beta ETF
    "GLD":  0.25,   # 25% -- gold
}

# Regime detection
SPY_MA_WINDOW   = 200
MA_SLOPE_WINDOW = 20    # 200d MA slope lookback -- negative slope = confirmed bear

OUTPUT_DIR = Path("results_bear")
OUTPUT_DIR.mkdir(exist_ok=True)

# =============================================================================
# Download
# =============================================================================
def download_all():
    tickers = ["SPY"] + list(BEAR_HOLDINGS.keys())
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
# Regime detection
# =============================================================================
def get_spy_regime(spy_df):
    close        = spy_df["Close"].squeeze()
    ma200        = close.rolling(SPY_MA_WINDOW).mean()
    above        = close > ma200
    ma_slope     = ma200 - ma200.shift(MA_SLOPE_WINDOW)
    ma_declining = ma_slope < 0
    # Confirmed bear: price below MA AND MA itself declining
    confirmed_bear = (~above) & ma_declining
    return ~confirmed_bear   # True = bull/neutral, False = confirmed bear

# =============================================================================
# Backtest
# =============================================================================
def run_backtest(data):
    spy_df    = data["SPY"]
    regime    = get_spy_regime(spy_df)
    spy_close = spy_df["Close"].squeeze()
    all_dates = sorted(spy_df.index)

    closes = {}
    for tkr in BEAR_HOLDINGS:
        if tkr in data:
            closes[tkr] = data[tkr]["Close"].squeeze()

    portfolio_value  = INITIAL_CAPITAL
    cash             = INITIAL_CAPITAL
    holdings         = {}
    in_bear          = False
    last_rebal_month = None
    trades           = []
    equity_curve     = []
    bear_periods     = []
    bear_start       = None

    cash_pct = 1.0 - sum(BEAR_HOLDINGS.values())
    alloc_str = " + ".join([f"{t}({p:.0%})" for t, p in BEAR_HOLDINGS.items()])
    print(f"\n[Backtest] Bear allocation: {alloc_str} + Cash({cash_pct:.0%})")
    print(f"[Backtest] Regime: SPY < 200d MA AND 200d MA slope negative\n")

    for today in tqdm(all_dates, desc="Simulating"):
        if today not in regime.index:
            continue

        spy_above = bool(regime.loc[today])
        spy_price = float(spy_close.loc[today]) if today in spy_close.index else None

        # Bear -> bull transition: exit all positions
        if spy_above and in_bear:
            in_bear  = False
            duration = (today - bear_start).days
            bear_periods.append({'start': bear_start, 'end': today, 'days': duration})
            print(f"  [BEAR END]   {today.date()} | Duration: {duration}d | "
                  f"Portfolio: ${portfolio_value:,.0f}")

            for tkr, shares in list(holdings.items()):
                if tkr in closes and today in closes[tkr].index:
                    price    = float(closes[tkr].loc[today])
                    proceeds = shares * price
                    cash    += proceeds
                    trades.append({'date': today, 'action': 'SELL', 'ticker': tkr,
                                   'shares': shares, 'price': price,
                                   'value': proceeds, 'reason': 'regime_exit'})
                    print(f"    EXIT: {tkr} {shares:.2f}sh @ ${price:.2f} = ${proceeds:,.0f}")
            holdings        = {}
            portfolio_value = cash

        # Bull -> bear transition
        if not spy_above and not in_bear:
            in_bear          = True
            bear_start       = today
            last_rebal_month = None
            print(f"  [BEAR START] {today.date()} | SPY: {spy_price:.2f}")

        # Monthly rebalance during bear
        current_month = pd.Timestamp(today).month
        if in_bear and current_month != last_rebal_month:
            last_rebal_month = current_month

            # Total portfolio value (cash + holdings)
            total_value = cash
            for tkr, shares in holdings.items():
                if tkr in closes and today in closes[tkr].index:
                    total_value += shares * float(closes[tkr].loc[today])

            print(f"  [REBAL] {today.date()} | {alloc_str} | Total: ${total_value:,.0f}")

            # Rebalance each instrument to target allocation
            for tkr, target_pct in BEAR_HOLDINGS.items():
                if tkr not in closes or today not in closes[tkr].index:
                    continue
                price         = float(closes[tkr].loc[today])
                target_value  = total_value * target_pct
                current_value = holdings.get(tkr, 0) * price
                diff          = target_value - current_value

                if abs(diff) < 100:
                    continue

                shares_diff   = diff / price
                cost          = shares_diff * price
                cash         -= cost
                holdings[tkr] = holdings.get(tkr, 0) + shares_diff
                action        = "BUY" if shares_diff > 0 else "SELL"
                trades.append({'date': today, 'action': action, 'ticker': tkr,
                               'shares': abs(shares_diff), 'price': price,
                               'value': abs(cost), 'reason': 'rebalance'})

        # Mark to market
        mtm = cash
        for tkr, shares in holdings.items():
            if tkr in closes and today in closes[tkr].index:
                mtm += shares * float(closes[tkr].loc[today])
        portfolio_value = mtm
        holding_str     = "+".join(holdings.keys()) if holdings else "CASH"
        equity_curve.append({'date': today, 'portfolio': portfolio_value,
                             'in_bear': in_bear, 'holdings': holding_str})

    # Close any open bear period at end of data
    if in_bear and bear_start is not None:
        bear_periods.append({'start': bear_start,
                             'end':   all_dates[-1],
                             'days':  (all_dates[-1] - bear_start).days})

    print(f"\n[Backtest] Complete.")
    return pd.DataFrame(trades), pd.DataFrame(equity_curve), bear_periods

# =============================================================================
# Metrics
# =============================================================================
def compute_metrics(trades_df, equity_df, bear_periods, data):
    spy_close = data["SPY"]["Close"].squeeze()

    if equity_df.empty:
        return {}, pd.DataFrame()

    bear_results = []
    for period in bear_periods:
        mask = ((equity_df["date"] >= period["start"]) &
                (equity_df["date"] <= period["end"]))
        sub  = equity_df[mask].copy()
        if sub.empty:
            continue

        start_val = float(sub.iloc[0]["portfolio"])
        end_val   = float(sub.iloc[-1]["portfolio"])
        ret       = (end_val / start_val - 1) * 100
        days      = period["days"]

        spy_slice = spy_close[(spy_close.index >= period["start"]) &
                              (spy_close.index <= period["end"])]
        spy_ret   = ((float(spy_slice.iloc[-1]) / float(spy_slice.iloc[0])) - 1) * 100 \
                    if len(spy_slice) >= 2 else 0

        bear_results.append({
            'start':     period["start"].date(),
            'end':       period["end"].date(),
            'days':      days,
            'strat_ret': round(ret, 2),
            'spy_ret':   round(spy_ret, 2),
            'vs_spy':    round(ret - spy_ret, 2),
            'vs_cash':   round(ret, 2),
        })

    results_df = pd.DataFrame(bear_results) if bear_results else pd.DataFrame()

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

    total_bear_days = sum(p["days"] for p in bear_periods)

    metrics = {
        "strategy":               "BTAL(25%) + GLD(25%) + Cash(50%) -- Confirmed Bear Only",
        "regime_filter":          f"SPY < 200d MA AND 200d MA slope negative ({MA_SLOPE_WINDOW}d)",
        "bear_holdings":          BEAR_HOLDINGS,
        "period":                 f"{START_DATE} to {END_DATE}",
        "initial_capital":        INITIAL_CAPITAL,
        "final_equity":           round(final_val, 2),
        "cagr_pct":               round(cagr * 100, 2),
        "sharpe":                 round(sharpe, 2),
        "max_drawdown_pct":       round(max_dd, 2),
        "bear_periods_count":     len(bear_periods),
        "total_bear_days":        total_bear_days,
        "bear_pct_of_time":       round(total_bear_days / ((end_dt - start_dt).days) * 100, 1),
        "avg_bear_duration_days": round(results_df["days"].mean(), 0) if not results_df.empty else 0,
        "profitable_periods":     int((results_df["strat_ret"] > 0).sum()) if not results_df.empty else 0,
        "avg_strat_return":       round(results_df["strat_ret"].mean(), 2) if not results_df.empty else 0,
        "avg_spy_return":         round(results_df["spy_ret"].mean(), 2) if not results_df.empty else 0,
        "avg_vs_spy":             round((results_df["strat_ret"] - results_df["spy_ret"]).mean(), 2) if not results_df.empty else 0,
    }

    return metrics, results_df

# =============================================================================
# Print results
# =============================================================================
def print_results(metrics, results_df):
    print("\n" + "=" * 65)
    print(f" BEAR REGIME STRATEGY -- BTAL + GLD + CASH")
    print("=" * 65)
    print(f"\n  Strategy    : {metrics['strategy']}")
    print(f"  Regime      : {metrics['regime_filter']}")
    print(f"  Period      : {metrics['period']}")
    print()
    print(f"  Full-period metrics (cash during bull, BTAL+GLD during bear):")
    print(f"    Final equity      : ${metrics['final_equity']:>12,.2f}")
    print(f"    CAGR              : {metrics['cagr_pct']:>+8.2f}%")
    print(f"    Sharpe            : {metrics['sharpe']:>8.2f}")
    print(f"    Max Drawdown      : {metrics['max_drawdown_pct']:>8.2f}%")
    print()
    print(f"  Bear regime summary:")
    print(f"    Bear periods      : {metrics['bear_periods_count']}")
    print(f"    Total bear days   : {metrics['total_bear_days']:,} ({metrics['bear_pct_of_time']}% of time)")
    print(f"    Avg duration      : {metrics['avg_bear_duration_days']:.0f} days")
    print(f"    Profitable periods: {metrics['profitable_periods']} / {metrics['bear_periods_count']}")
    print(f"    Avg strat return  : {metrics['avg_strat_return']:>+.2f}%")
    print(f"    Avg SPY return    : {metrics['avg_spy_return']:>+.2f}%")
    print(f"    Avg vs SPY        : {metrics['avg_vs_spy']:>+.2f}pp")
    print()

    if not results_df.empty:
        print(f"  Per-period breakdown:")
        print(f"  {'Start':<12} {'End':<12} {'Days':>5} {'Strategy':>10} "
              f"{'SPY':>8} {'vs SPY':>8} {'vs Cash':>8}")
        print(f"  {'-'*65}")
        for _, row in results_df.iterrows():
            print(f"  {str(row['start']):<12} {str(row['end']):<12} "
                  f"{row['days']:>5} {row['strat_ret']:>+9.1f}% "
                  f"{row['spy_ret']:>+7.1f}% {row['vs_spy']:>+7.1f}pp "
                  f"{row['vs_cash']:>+7.1f}pp")

    print()
    print("  --- Comparison vs all prior tests ---")
    print(f"  {'Strategy':<42} {'CAGR':>8} {'MaxDD':>8}")
    print(f"  {'-'*60}")
    print(f"  {'Momentum rotation (no VIXY)':<42} {'-0.05%':>8} {'-57.5%':>8}")
    print(f"  {'MA slope + momentum':<42} {'-1.58%':>8} {'-61.0%':>8}")
    print(f"  {'50% GLD + 50% cash':<42} {'+0.58%':>8} {'-54.0%':>8}")
    print(f"  {'BTAL(25%) + GLD(25%) + cash(50%)':<42} "
          f"{metrics['cagr_pct']:>+7.2f}% {metrics['max_drawdown_pct']:>+7.1f}%")
    print("=" * 65)

# =============================================================================
# Main
# =============================================================================
if __name__ == "__main__":
    data = download_all()

    missing = [t for t in list(BEAR_HOLDINGS.keys()) + ["SPY"] if t not in data]
    if missing:
        print(f"[ERROR] Missing data for: {missing}")
        exit(1)

    trades_df, equity_df, bear_periods = run_backtest(data)

    if equity_df.empty:
        print("[ERROR] No equity curve generated.")
        exit(1)

    metrics, results_df = compute_metrics(trades_df, equity_df, bear_periods, data)
    print_results(metrics, results_df)

    trades_df.to_csv(OUTPUT_DIR / "bear_trades.csv", index=False)
    equity_df.to_csv(OUTPUT_DIR / "bear_equity_curve.csv", index=False)
    if not results_df.empty:
        results_df.to_csv(OUTPUT_DIR / "bear_period_results.csv", index=False)
    with open(OUTPUT_DIR / "bear_metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, default=str)

    print(f"\n  Results saved to: {OUTPUT_DIR.resolve()}/")
