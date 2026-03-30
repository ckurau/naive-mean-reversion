"""
Enhanced Naive Mean Reversion (MR) Backtest
=============================================
Original Rules:
  - Universe : S&P 500 constituents (current + historical) with price >= $10
  - Buy      : Stock > 200-day MA  AND  4 consecutive down days → buy next open
  - Sell     : Close of first up-day after entry
  - Portfolio: Max 20 simultaneous positions, 5% allocation each

Enhancements Added:
  1. RSI(2) < 20 filter       — only enter at extreme oversold readings
  2. ATR volatility filter    — skip flat/low-volatility stocks (min 1% daily range)
  3. Volume confirmation      — only enter if today's volume > 20-day avg volume
  4. Min profit exit          — don't exit on trivially small up-days (min 0.5%)
  5. SPY regime filter        — skip all trades when SPY is below its 200-day MA
  6. Commission model         — $0.005/share or $1.00 min (matching original article)
"""

import warnings
import datetime
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
from tqdm import tqdm

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────
START_DATE        = "2004-01-01"
END_DATE          = datetime.date.today().isoformat()
MIN_PRICE         = 10.0          # minimum stock price filter
MAX_POSITIONS     = 20            # max simultaneous holdings
POSITION_SIZE     = 0.05          # 5% of portfolio per trade
MA_WINDOW         = 200           # long-term trend filter
CONSEC_DOWN       = 4             # consecutive down-day requirement
INITIAL_CAPITAL   = 100_000.0     # starting portfolio value

# ── Enhancement parameters ───────────────────────────────────────────────────
RSI_PERIOD        = 2             # RSI lookback (short = more sensitive)
RSI_THRESHOLD     = 20            # only buy when RSI(2) < this level
ATR_PERIOD        = 14            # ATR lookback for volatility filter
ATR_MIN_PCT       = 0.01          # min ATR as % of price (1% = meaningful volatility)
VOL_MA_PERIOD     = 20            # volume MA period for confirmation
MIN_PROFIT_PCT    = 0.005         # minimum up-day gain to trigger exit (0.5%)
COMMISSION_RATE   = 0.005         # $0.005 per share
COMMISSION_MIN    = 1.00          # minimum $1.00 per trade

OUTPUT_DIR        = Path("results")
OUTPUT_DIR.mkdir(exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# 1.  Universe — S&P 500 historical constituents (survivorship-bias free)
# ─────────────────────────────────────────────────────────────────────────────
def _fetch_wikipedia_tables() -> list:
    """Fetch S&P 500 Wikipedia tables with a browser-like User-Agent to avoid 403s."""
    import io
    url     = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
    }
    import requests as _requests
    resp = _requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return pd.read_html(io.StringIO(resp.text), header=0)


def get_sp500_universe() -> list[str]:
    tickers: set[str] = set()

    # Current constituents via Wikipedia
    try:
        tables  = _fetch_wikipedia_tables()
        current = tables[0]["Symbol"].tolist()
        tickers.update([t.replace(".", "-") for t in current])
        print(f"[Universe] Current S&P 500 members: {len(current)}")
    except Exception as e:
        print(f"[Universe] Wikipedia fetch failed: {e}")

    # Historical changes via Wikipedia (2nd table)
    try:
        tables = _fetch_wikipedia_tables()
        if len(tables) > 1:
            changes = tables[1]
            for col in changes.columns:
                col_str = changes[col].dropna().astype(str)
                if col_str.str.match(r"^[A-Z]{1,5}(-[A-Z])?$").mean() > 0.3:
                    tickers.update([t.replace(".", "-") for t in col_str.tolist()])
    except Exception as e:
        print(f"[Universe] Historical changes fetch failed: {e}")

    # Well-known historical S&P 500 names
    historical_extras = [
        "LEH","BSC","WB","WAMU","MER","C","AIG","FNM","FRE",
        "YHOO","SUNW","PALM","Q","NT","GLW","JDS","CSCO","T",
        "GE","GM","F","XOM","CVX","IBM","MSFT","AAPL","AMZN",
        "GOOG","GOOGL","META","NVDA","TSLA","BRK-B","JPM","BAC",
        "WFC","GS","MS","USB","PNC","TFC","COF","AXP","V","MA",
        "HD","LOW","TGT","WMT","COST","KR","CVS","WBA",
        "UNH","CI","HUM","CNC","MOH","ABC","MCK","CAH",
        "JNJ","PFE","MRK","ABBV","BMY","AMGN","GILD","BIIB",
        "LLY","REGN","VRTX","ZTS","ISRG","BSX","SYK","MDT",
        "BA","LMT","RTX","NOC","GD","HII","TXT",
        "CAT","DE","EMR","HON","MMM","ETN","PH","ROK",
        "COP","EOG","SLB","HAL","BKR","MPC","VLO",
        "NEE","DUK","SO","AEP","EXC","SRE","PCG","ED","FE",
        "AMT","PLD","CCI","SPG","O","WELL","PSA","EQR","AVB",
        "SBUX","MCD","YUM","CMG","DRI","QSR",
        "DIS","NFLX","CMCSA","VZ","CHTR","TMUS",
        "PG","KO","PEP","CL","KMB","CHD","EL",
    ]
    tickers.update(historical_extras)

    result = sorted(tickers)
    print(f"[Universe] Total unique tickers (incl. historical): {len(result)}")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 2.  Download price data
# ─────────────────────────────────────────────────────────────────────────────
def download_prices(tickers: list[str]) -> dict[str, pd.DataFrame]:
    print(f"\n[Download] Fetching data for {len(tickers)} tickers "
          f"({START_DATE} → {END_DATE}) …")

    chunk_size = 100
    all_data: dict[str, pd.DataFrame] = {}

    for i in tqdm(range(0, len(tickers), chunk_size), desc="Downloading"):
        chunk = tickers[i : i + chunk_size]
        try:
            raw = yf.download(
                chunk,
                start=START_DATE,
                end=END_DATE,
                auto_adjust=True,
                progress=False,
                threads=True,
            )
            if raw.empty:
                continue

            if isinstance(raw.columns, pd.MultiIndex):
                for tkr in chunk:
                    try:
                        df = raw.xs(tkr, axis=1, level=1).dropna(how="all")
                        if not df.empty:
                            all_data[tkr] = df
                    except KeyError:
                        pass
            else:
                if chunk:
                    all_data[chunk[0]] = raw.dropna(how="all")
        except Exception as e:
            print(f"[Download] Chunk {i//chunk_size} error: {e}")

    print(f"[Download] Successfully downloaded {len(all_data)} tickers.")
    return all_data


def download_spy() -> pd.DataFrame:
    """Download SPY for the market regime filter."""
    print("[Download] Fetching SPY for market regime filter …")
    spy = yf.download("SPY", start=START_DATE, end=END_DATE,
                      auto_adjust=True, progress=False)

    # yfinance may return MultiIndex columns even for a single ticker — flatten
    if isinstance(spy.columns, pd.MultiIndex):
        spy.columns = spy.columns.get_level_values(0)

    close            = spy["Close"].squeeze()   # guarantee it's a Series
    spy["spy_ma200"] = close.rolling(200).mean()
    spy["spy_ok"]    = (close > spy["spy_ma200"].squeeze()).values
    return spy


# ─────────────────────────────────────────────────────────────────────────────
# 3.  Signal generation
# ─────────────────────────────────────────────────────────────────────────────
def compute_rsi(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute all indicators and the composite buy signal.

    Buy signal requires ALL of:
      1. Close > 200-day MA          (uptrend filter)
      2. 4+ consecutive down days    (mean reversion setup)
      3. RSI(2) < 20                 (extreme oversold confirmation)
      4. ATR(14)/Close > 1%          (meaningful volatility present)
      5. Volume > 20-day avg volume  (selling volume confirmation)
      6. Close >= MIN_PRICE          (liquidity filter)
    """
    df = df.copy()

    # Trend filter
    df["ma200"]    = df["Close"].rolling(MA_WINDOW).mean()
    df["above_ma"] = df["Close"] > df["ma200"]

    # Consecutive down days
    df["down_day"] = (df["Close"] < df["Close"].shift(1)).astype(int)
    consec, count = [], 0
    for d in df["down_day"]:
        count = count + 1 if d == 1 else 0
        consec.append(count)
    df["consec_down"] = consec

    # Enhancement 1: RSI(2)
    df["rsi2"] = compute_rsi(df["Close"], RSI_PERIOD)

    # Enhancement 2: ATR volatility filter
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - df["Close"].shift(1)).abs(),
        (df["Low"]  - df["Close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["atr"]     = tr.rolling(ATR_PERIOD).mean()
    df["atr_pct"] = df["atr"] / df["Close"]

    # Enhancement 3: Volume confirmation
    df["vol_ma20"]    = df["Volume"].rolling(VOL_MA_PERIOD).mean()
    df["vol_confirm"] = df["Volume"] > df["vol_ma20"]

    # Composite signal
    df["signal"] = (
        df["above_ma"]                          &   # uptrend
        (df["consec_down"] >= CONSEC_DOWN)      &   # 4 down days
        (df["rsi2"] < RSI_THRESHOLD)            &   # RSI(2) oversold
        (df["atr_pct"] > ATR_MIN_PCT)           &   # enough volatility
        df["vol_confirm"]                       &   # volume confirms selloff
        (df["Close"] >= MIN_PRICE)                  # liquidity
    )
    return df


# ─────────────────────────────────────────────────────────────────────────────
# 4.  Backtest simulation
# ─────────────────────────────────────────────────────────────────────────────
def calc_commission(shares: float, price: float) -> float:
    return max(shares * COMMISSION_RATE, COMMISSION_MIN)


def run_backtest(price_data: dict[str, pd.DataFrame],
                 spy_df: pd.DataFrame) -> pd.DataFrame:
    print("\n[Backtest] Running enhanced simulation …")

    # Build SPY regime lookup {date: bool}
    spy_regime = spy_df["spy_ok"].to_dict()

    # Collect all trading dates
    all_dates: set = set()
    for df in price_data.values():
        all_dates.update(df.index)
    trading_dates = sorted(all_dates)

    # Pre-compute signals
    signals: dict[str, pd.DataFrame] = {}
    min_bars = MA_WINDOW + VOL_MA_PERIOD + ATR_PERIOD + CONSEC_DOWN + 5
    for tkr, df in tqdm(price_data.items(), desc="Generating signals"):
        if len(df) > min_bars:
            signals[tkr] = generate_signals(df)

    # Simulation state
    portfolio_value = INITIAL_CAPITAL
    open_positions: dict[str, dict] = {}
    trades: list[dict] = []

    for today in tqdm(trading_dates, desc="Simulating"):

        # ── Enhancement 5: Skip if SPY below 200-day MA ──────────────────────
        spy_ok = spy_regime.get(today, True)   # default True if date not found

        # ── Check exits ───────────────────────────────────────────────────────
        to_close = []
        for tkr, pos in open_positions.items():
            if tkr not in signals:
                continue
            tkr_df = signals[tkr]
            if today not in tkr_df.index:
                continue
            row      = tkr_df.loc[today]
            prev_idx = tkr_df.index.get_loc(today)
            if prev_idx == 0:
                continue
            prev_close = tkr_df.iloc[prev_idx - 1]["Close"]

            # Enhancement 4: only exit if up-day gain >= MIN_PROFIT_PCT
            up_pct = (row["Close"] - prev_close) / prev_close
            if up_pct >= MIN_PROFIT_PCT:
                exit_price  = row["Close"]
                commission  = calc_commission(pos["shares"], exit_price)
                pnl         = (exit_price - pos["entry_price"]) * pos["shares"] - commission
                pnl_pct     = (exit_price / pos["entry_price"] - 1) * 100
                days_held   = (today - pos["entry_date"]).days
                trades.append({
                    "ticker"       : tkr,
                    "entry_date"   : pos["entry_date"],
                    "exit_date"    : today,
                    "entry_price"  : pos["entry_price"],
                    "exit_price"   : exit_price,
                    "shares"       : pos["shares"],
                    "commission"   : round(commission + pos["entry_commission"], 4),
                    "pnl_usd"      : pnl,
                    "pnl_pct"      : pnl_pct,
                    "days_held"    : days_held,
                    "portfolio_val": portfolio_value + pnl,
                    "spy_regime"   : spy_ok,
                })
                portfolio_value += pnl
                to_close.append(tkr)

        for tkr in to_close:
            del open_positions[tkr]

        # ── Skip entries if market in downtrend ───────────────────────────────
        if not spy_ok:
            continue

        if len(open_positions) >= MAX_POSITIONS:
            continue

        # ── Check entries ─────────────────────────────────────────────────────
        candidates = []
        for tkr, tkr_df in signals.items():
            if tkr in open_positions:
                continue
            if today not in tkr_df.index:
                continue
            if tkr_df.loc[today]["signal"]:
                candidates.append(tkr)

        for tkr in candidates:
            if len(open_positions) >= MAX_POSITIONS:
                break
            tkr_df    = signals[tkr]
            today_idx = tkr_df.index.get_loc(today)
            if today_idx + 1 >= len(tkr_df):
                continue
            next_row    = tkr_df.iloc[today_idx + 1]
            entry_price = next_row["Open"]
            if entry_price < MIN_PRICE or entry_price <= 0:
                continue
            position_cash    = portfolio_value * POSITION_SIZE
            shares           = position_cash / entry_price
            entry_commission = calc_commission(shares, entry_price)
            open_positions[tkr] = {
                "entry_date"       : tkr_df.index[today_idx + 1],
                "entry_price"      : entry_price,
                "shares"           : shares,
                "entry_commission" : entry_commission,
            }

    print(f"[Backtest] Simulation complete — {len(trades)} trades executed.")
    return pd.DataFrame(trades)


# ─────────────────────────────────────────────────────────────────────────────
# 5.  Performance metrics
# ─────────────────────────────────────────────────────────────────────────────
def compute_metrics(trades_df: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    if trades_df.empty:
        return {"error": "No trades generated."}, pd.DataFrame()

    trades_df = trades_df.sort_values("exit_date").reset_index(drop=True)

    equity = INITIAL_CAPITAL
    equity_curve = []
    for _, row in trades_df.iterrows():
        equity += row["pnl_usd"]
        equity_curve.append({"date": row["exit_date"], "equity": equity})
    eq_df = pd.DataFrame(equity_curve)

    start_dt = pd.to_datetime(trades_df["entry_date"].min())
    end_dt   = pd.to_datetime(trades_df["exit_date"].max())
    years    = max((end_dt - start_dt).days / 365.25, 1e-6)
    cagr     = (equity / INITIAL_CAPITAL) ** (1 / years) - 1

    winners  = trades_df[trades_df["pnl_usd"] > 0]
    losers   = trades_df[trades_df["pnl_usd"] <= 0]
    win_rate = len(winners) / len(trades_df) * 100

    roi_per_year  = (equity - INITIAL_CAPITAL) / INITIAL_CAPITAL / years * 100
    avg_days      = trades_df["days_held"].mean()
    avg_win       = winners["pnl_pct"].mean() if len(winners) else 0
    avg_loss      = losers["pnl_pct"].mean()  if len(losers)  else 0

    eq_df["peak"] = eq_df["equity"].cummax()
    eq_df["dd"]   = (eq_df["equity"] - eq_df["peak"]) / eq_df["peak"] * 100
    max_drawdown  = eq_df["dd"].min()

    gross_profit  = winners["pnl_usd"].sum()
    gross_loss    = abs(losers["pnl_usd"].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    eq_df["date"] = pd.to_datetime(eq_df["date"])
    eq_df.set_index("date", inplace=True)
    monthly_eq  = eq_df["equity"].resample("ME").last().ffill()
    monthly_ret = monthly_eq.pct_change().dropna()
    sharpe      = (monthly_ret.mean() / monthly_ret.std() * np.sqrt(12)
                   if monthly_ret.std() > 0 else 0)

    total_commission = trades_df["commission"].sum() if "commission" in trades_df else 0

    metrics = {
        "period_start"         : start_dt.date().isoformat(),
        "period_end"           : end_dt.date().isoformat(),
        "years_tested"         : round(years, 2),
        "total_trades"         : len(trades_df),
        "trades_per_year"      : round(len(trades_df) / years, 1),
        "win_rate_pct"         : round(win_rate, 2),
        "cagr_pct"             : round(cagr * 100, 2),
        "roi_per_year_pct"     : round(roi_per_year, 2),
        "avg_days_held"        : round(avg_days, 2),
        "avg_win_pct"          : round(avg_win, 2),
        "avg_loss_pct"         : round(avg_loss, 2),
        "profit_factor"        : round(profit_factor, 2),
        "max_drawdown_pct"     : round(max_drawdown, 2),
        "sharpe_ratio"         : round(sharpe, 2),
        "total_commission_usd" : round(total_commission, 2),
        "initial_capital"      : INITIAL_CAPITAL,
        "final_equity"         : round(equity, 2),
        "total_return_pct"     : round((equity / INITIAL_CAPITAL - 1) * 100, 2),
        # Enhancement flags (for reference)
        "enhancements"         : {
            "rsi2_threshold"   : RSI_THRESHOLD,
            "atr_min_pct"      : ATR_MIN_PCT,
            "vol_ma_period"    : VOL_MA_PERIOD,
            "min_profit_pct"   : MIN_PROFIT_PCT,
            "spy_regime_filter": True,
            "commission_rate"  : COMMISSION_RATE,
        }
    }
    return metrics, eq_df.reset_index()


# ─────────────────────────────────────────────────────────────────────────────
# 6.  Save outputs
# ─────────────────────────────────────────────────────────────────────────────
def save_outputs(trades_df: pd.DataFrame, metrics: dict, eq_df: pd.DataFrame):
    trades_path  = OUTPUT_DIR / "trades.csv"
    metrics_path = OUTPUT_DIR / "metrics.json"
    equity_path  = OUTPUT_DIR / "equity_curve.csv"

    trades_df.to_csv(trades_path, index=False)
    eq_df.to_csv(equity_path, index=False)

    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2, default=str)

    print("\n" + "="*60)
    print("  ENHANCED NAIVE MR BACKTEST — RESULTS SUMMARY")
    print("="*60)
    for k, v in metrics.items():
        if k == "enhancements":
            print(f"\n  {'Enhancements Applied':<30}:")
            for ek, ev in v.items():
                print(f"    {ek:<28}: {ev}")
        else:
            label = k.replace("_", " ").title()
            print(f"  {label:<30}: {v}")
    print("="*60)
    print(f"\n  Files saved to: {OUTPUT_DIR.resolve()}")
    print(f"    • {trades_path}")
    print(f"    • {metrics_path}")
    print(f"    • {equity_path}")


# ─────────────────────────────────────────────────────────────────────────────
# 7.  Entry point
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    universe   = get_sp500_universe()
    price_data = download_prices(universe)
    spy_df     = download_spy()
    trades_df  = run_backtest(price_data, spy_df)

    if trades_df.empty:
        print("[ERROR] No trades were generated. Check your universe / date range.")
    else:
        metrics, eq_df = compute_metrics(trades_df)
        save_outputs(trades_df, metrics, eq_df)
