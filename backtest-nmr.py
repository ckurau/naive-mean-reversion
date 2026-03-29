"""
Naive Mean Reversion (MR) Backtest
====================================
Strategy Rules:
  - Universe : S&P 500 constituents (current + historical) with price >= $10
  - Buy      : Stock > 200-day MA  AND  4 consecutive down days → buy next open
  - Sell     : Close of first up-day after entry
  - Portfolio: Max 20 simultaneous positions, 5% allocation each
  - Period   : ~20 years (configurable via START_DATE / END_DATE)
"""

import os
import warnings
import datetime
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
import requests
from tqdm import tqdm

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────────────────────
# Config
# ─────────────────────────────────────────────────────────────────────────────
START_DATE      = "2004-01-01"
END_DATE        = datetime.date.today().isoformat()
MIN_PRICE       = 10.0          # minimum stock price filter
MAX_POSITIONS   = 20            # max simultaneous holdings
POSITION_SIZE   = 0.05          # 5 % of portfolio per trade
MA_WINDOW       = 200           # long-term trend filter
CONSEC_DOWN     = 4             # consecutive down-day requirement
INITIAL_CAPITAL = 100_000.0     # starting portfolio value
OUTPUT_DIR      = Path("results")
OUTPUT_DIR.mkdir(exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# 1.  Universe — S&P 500 historical constituents (survivorship-bias free)
# ─────────────────────────────────────────────────────────────────────────────
def get_sp500_universe() -> list[str]:
    """
    Return a deduplicated list of tickers that have ever been in the S&P 500.
    Primary source  : Wikipedia current table
    Supplementary   : A curated list of well-known historical additions/removals
                      so we capture delisted / replaced names back to ~2000.
    """
    tickers: set[str] = set()

    # --- current constituents via Wikipedia ---
    try:
        tables = pd.read_html(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", header=0
        )
        current = tables[0]["Symbol"].tolist()
        tickers.update([t.replace(".", "-") for t in current])
        print(f"[Universe] Current S&P 500 members: {len(current)}")
    except Exception as e:
        print(f"[Universe] Wikipedia fetch failed: {e}")

    # --- historical changes via Wikipedia (2nd table) ---
    try:
        tables = pd.read_html(
            "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", header=0
        )
        if len(tables) > 1:
            changes = tables[1]
            for col in changes.columns:
                col_str = changes[col].dropna().astype(str)
                # look for columns that look like ticker symbols
                if col_str.str.match(r"^[A-Z]{1,5}(-[A-Z])?$").mean() > 0.3:
                    tickers.update([t.replace(".", "-") for t in col_str.tolist()])
    except Exception as e:
        print(f"[Universe] Historical changes fetch failed: {e}")

    # --- well-known historical S&P 500 names (additions guarantee coverage) ---
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
        "BA","LMT","RTX","NOC","GD","HII","L3H","TXT",
        "CAT","DE","EMR","HON","MMM","GE","ETN","PH","ROK",
        "XOM","CVX","COP","EOG","SLB","HAL","BKR","MPC","VLO",
        "NEE","DUK","SO","AEP","EXC","SRE","PCG","ED","FE",
        "AMT","PLD","CCI","SPG","O","WELL","PSA","EQR","AVB",
        "SBUX","MCD","YUM","CMG","DRI","QSR",
        "DIS","NFLX","CMCSA","VZ","T","CHTR","TMUS",
        "PG","KO","PEP","UL","CL","KMB","CHD","EL","COTY",
    ]
    tickers.update(historical_extras)

    result = sorted(tickers)
    print(f"[Universe] Total unique tickers (incl. historical): {len(result)}")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 2.  Download price data
# ─────────────────────────────────────────────────────────────────────────────
def download_prices(tickers: list[str]) -> dict[str, pd.DataFrame]:
    """
    Download adjusted OHLC for every ticker.  Returns a dict {ticker: df}.
    Uses yfinance batch download then splits by ticker.
    """
    print(f"\n[Download] Fetching data for {len(tickers)} tickers "
          f"({START_DATE} → {END_DATE}) …")

    # Batch in chunks of 100 to stay within yfinance limits
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

            # yfinance returns MultiIndex columns when >1 ticker
            if isinstance(raw.columns, pd.MultiIndex):
                for tkr in chunk:
                    try:
                        df = raw.xs(tkr, axis=1, level=1).dropna(how="all")
                        if not df.empty:
                            all_data[tkr] = df
                    except KeyError:
                        pass
            else:
                # Single ticker returned
                if chunk:
                    all_data[chunk[0]] = raw.dropna(how="all")
        except Exception as e:
            print(f"[Download] Chunk {i//chunk_size} error: {e}")

    print(f"[Download] Successfully downloaded {len(all_data)} tickers.")
    return all_data


# ─────────────────────────────────────────────────────────────────────────────
# 3.  Signal generation & trade simulation
# ─────────────────────────────────────────────────────────────────────────────
def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    """
    Given OHLC dataframe for one ticker, compute:
      - ma200        : 200-day SMA of Close
      - above_ma     : Close > ma200
      - daily_ret    : 1-day return sign
      - consec_down  : rolling count of consecutive negative days
      - signal       : True on day where all buy conditions are met
    """
    df = df.copy()
    df["ma200"]       = df["Close"].rolling(MA_WINDOW).mean()
    df["above_ma"]    = df["Close"] > df["ma200"]
    df["down_day"]    = (df["Close"] < df["Close"].shift(1)).astype(int)

    # Rolling consecutive down days
    consec = []
    count = 0
    for d in df["down_day"]:
        if d == 1:
            count += 1
        else:
            count = 0
        consec.append(count)
    df["consec_down"] = consec

    df["signal"] = (
        df["above_ma"] &
        (df["consec_down"] >= CONSEC_DOWN) &
        (df["Close"] >= MIN_PRICE)
    )
    return df


def run_backtest(price_data: dict[str, pd.DataFrame]) -> pd.DataFrame:
    """
    Event-driven simulation.
    Returns a DataFrame of individual trades.
    """
    print("\n[Backtest] Running simulation …")

    # Collect all trading dates
    all_dates: set = set()
    for df in price_data.values():
        all_dates.update(df.index)
    trading_dates = sorted(all_dates)

    # Pre-compute signals
    signals: dict[str, pd.DataFrame] = {}
    for tkr, df in tqdm(price_data.items(), desc="Generating signals"):
        if len(df) > MA_WINDOW + CONSEC_DOWN + 5:
            signals[tkr] = generate_signals(df)

    # Simulation state
    portfolio_value = INITIAL_CAPITAL
    open_positions: dict[str, dict] = {}   # tkr -> {entry_date, entry_price, shares}
    trades: list[dict] = []

    for today in tqdm(trading_dates, desc="Simulating"):
        # ── Check exits first (sell at today's close on first up-day) ──
        to_close = []
        for tkr, pos in open_positions.items():
            if tkr not in signals:
                continue
            tkr_df = signals[tkr]
            if today not in tkr_df.index:
                continue
            row = tkr_df.loc[today]
            # "First up-day": today's close > yesterday's close
            prev_idx = tkr_df.index.get_loc(today)
            if prev_idx == 0:
                continue
            prev_close = tkr_df.iloc[prev_idx - 1]["Close"]
            if row["Close"] > prev_close:
                exit_price = row["Close"]
                pnl = (exit_price - pos["entry_price"]) * pos["shares"]
                pnl_pct = (exit_price / pos["entry_price"] - 1) * 100
                days_held = (today - pos["entry_date"]).days
                trades.append({
                    "ticker"       : tkr,
                    "entry_date"   : pos["entry_date"],
                    "exit_date"    : today,
                    "entry_price"  : pos["entry_price"],
                    "exit_price"   : exit_price,
                    "shares"       : pos["shares"],
                    "pnl_usd"      : pnl,
                    "pnl_pct"      : pnl_pct,
                    "days_held"    : days_held,
                    "portfolio_val": portfolio_value + pnl,
                })
                portfolio_value += pnl
                to_close.append(tkr)

        for tkr in to_close:
            del open_positions[tkr]

        # ── Check entries (buy at next day's open, so we look at signal on today) ──
        if len(open_positions) >= MAX_POSITIONS:
            continue

        candidates = []
        for tkr, tkr_df in signals.items():
            if tkr in open_positions:
                continue
            if today not in tkr_df.index:
                continue
            row = tkr_df.loc[today]
            if row["signal"]:
                candidates.append(tkr)

        # For each candidate, enter at next day's open
        for tkr in candidates:
            if len(open_positions) >= MAX_POSITIONS:
                break
            tkr_df = signals[tkr]
            today_idx = tkr_df.index.get_loc(today)
            if today_idx + 1 >= len(tkr_df):
                continue
            next_row = tkr_df.iloc[today_idx + 1]
            entry_price = next_row["Open"]
            if entry_price < MIN_PRICE or entry_price <= 0:
                continue
            position_cash = portfolio_value * POSITION_SIZE
            shares = position_cash / entry_price
            open_positions[tkr] = {
                "entry_date"  : tkr_df.index[today_idx + 1],
                "entry_price" : entry_price,
                "shares"      : shares,
            }

    print(f"[Backtest] Simulation complete — {len(trades)} trades executed.")
    return pd.DataFrame(trades)


# ─────────────────────────────────────────────────────────────────────────────
# 4.  Performance metrics
# ─────────────────────────────────────────────────────────────────────────────
def compute_metrics(trades_df: pd.DataFrame) -> dict:
    if trades_df.empty:
        return {"error": "No trades generated."}

    trades_df = trades_df.sort_values("exit_date").reset_index(drop=True)

    # Reconstruct equity curve from trades
    equity = INITIAL_CAPITAL
    equity_curve = []
    for _, row in trades_df.iterrows():
        equity += row["pnl_usd"]
        equity_curve.append({"date": row["exit_date"], "equity": equity})
    eq_df = pd.DataFrame(equity_curve)

    # CAGR
    start_dt = pd.to_datetime(trades_df["entry_date"].min())
    end_dt   = pd.to_datetime(trades_df["exit_date"].max())
    years    = max((end_dt - start_dt).days / 365.25, 1e-6)
    cagr     = (equity / INITIAL_CAPITAL) ** (1 / years) - 1

    # Win rate
    winners  = trades_df[trades_df["pnl_usd"] > 0]
    losers   = trades_df[trades_df["pnl_usd"] <= 0]
    win_rate = len(winners) / len(trades_df) * 100

    # ROI per year
    roi_per_year = (equity - INITIAL_CAPITAL) / INITIAL_CAPITAL / years * 100

    # Avg days held
    avg_days = trades_df["days_held"].mean()

    # Avg win / avg loss
    avg_win  = winners["pnl_pct"].mean() if len(winners) else 0
    avg_loss = losers["pnl_pct"].mean()  if len(losers)  else 0

    # Max drawdown
    eq_df["peak"]    = eq_df["equity"].cummax()
    eq_df["dd"]      = (eq_df["equity"] - eq_df["peak"]) / eq_df["peak"] * 100
    max_drawdown     = eq_df["dd"].min()

    # Profit factor
    gross_profit = winners["pnl_usd"].sum()
    gross_loss   = abs(losers["pnl_usd"].sum())
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

    # Sharpe (annualised, using monthly returns for stability)
    eq_df["date"]    = pd.to_datetime(eq_df["date"])
    eq_df.set_index("date", inplace=True)
    monthly_eq       = eq_df["equity"].resample("ME").last().ffill()
    monthly_ret      = monthly_eq.pct_change().dropna()
    sharpe           = (monthly_ret.mean() / monthly_ret.std() * np.sqrt(12)
                        if monthly_ret.std() > 0 else 0)

    # Trades per year
    trades_per_year  = len(trades_df) / years

    metrics = {
        "period_start"         : start_dt.date().isoformat(),
        "period_end"           : end_dt.date().isoformat(),
        "years_tested"         : round(years, 2),
        "total_trades"         : len(trades_df),
        "trades_per_year"      : round(trades_per_year, 1),
        "win_rate_pct"         : round(win_rate, 2),
        "cagr_pct"             : round(cagr * 100, 2),
        "roi_per_year_pct"     : round(roi_per_year, 2),
        "avg_days_held"        : round(avg_days, 2),
        "avg_win_pct"          : round(avg_win, 2),
        "avg_loss_pct"         : round(avg_loss, 2),
        "profit_factor"        : round(profit_factor, 2),
        "max_drawdown_pct"     : round(max_drawdown, 2),
        "sharpe_ratio"         : round(sharpe, 2),
        "initial_capital"      : INITIAL_CAPITAL,
        "final_equity"         : round(equity, 2),
        "total_return_pct"     : round((equity / INITIAL_CAPITAL - 1) * 100, 2),
    }
    return metrics, eq_df.reset_index()


# ─────────────────────────────────────────────────────────────────────────────
# 5.  Save outputs
# ─────────────────────────────────────────────────────────────────────────────
def save_outputs(trades_df: pd.DataFrame, metrics: dict, eq_df: pd.DataFrame):
    trades_path  = OUTPUT_DIR / "trades.csv"
    metrics_path = OUTPUT_DIR / "metrics.json"
    equity_path  = OUTPUT_DIR / "equity_curve.csv"

    trades_df.to_csv(trades_path, index=False)
    eq_df.to_csv(equity_path, index=False)

    with open(metrics_path, "w") as f:
        json.dump(metrics, f, indent=2, default=str)

    # Pretty-print summary
    print("\n" + "="*60)
    print("  NAIVE MEAN REVERSION BACKTEST — RESULTS SUMMARY")
    print("="*60)
    for k, v in metrics.items():
        label = k.replace("_", " ").title()
        print(f"  {label:<30}: {v}")
    print("="*60)
    print(f"\n  Files saved to:  {OUTPUT_DIR.resolve()}")
    print(f"    • {trades_path}")
    print(f"    • {metrics_path}")
    print(f"    • {equity_path}")


# ─────────────────────────────────────────────────────────────────────────────
# 6.  Entry point
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    universe   = get_sp500_universe()
    price_data = download_prices(universe)
    trades_df  = run_backtest(price_data)

    if trades_df.empty:
        print("[ERROR] No trades were generated. Check your universe / date range.")
    else:
        metrics, eq_df = compute_metrics(trades_df)
        save_outputs(trades_df, metrics, eq_df)
