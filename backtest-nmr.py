"""
Enhanced Naive Mean Reversion (MR) Backtest — V4
==================================================
Base Rules (unchanged):
  - Universe : S&P 500 + S&P 400 MidCap constituents (current + historical)
  - Buy      : Stock > 200-day MA  AND  4 consecutive down days -> buy next open
  - Sell     : Close of first up-day (with min 1% gain)
  - Portfolio: Max 20 simultaneous positions, 5% allocation each

V4 Enhancements:
  1.  RSI(2) < 20               - oversold confirmation (reverted to 20)
  2.  ATR(14) > 1% of price     - volatility filter, skip flat stocks
  3.  Volume > 20-day avg       - volume confirmation of selloff
  4.  Min profit exit 1%        - hold for meaningful bounce
  5.  NO stop-loss              - removed; mean reversion + stops don't mix
  6.  SPY 200-day regime filter - no new entries in broad market downtrends
  7.  Commission model          - $0.005/share, $1.00 min
  8.  Signal ranking by RSI(2)  - most oversold stocks picked first
  9.  Time-based stop (10 days) - exit if no bounce within 10 calendar days
  10. Earnings blackout (+-3d)  - skip entries within 3 days of earnings
  11. Gap filter on entry       - skip if next-day open gaps down > 1.5%
  12. Expanded universe         - S&P 400 MidCap added
  13. Sector trend filter       - skip when stock's sector ETF < 50-day MA
  14. VIX regime sizing         - 2.5% when VIX>25, 7.5% when VIX<15, else 5%
"""

import io
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
START_DATE          = "2004-01-01"
END_DATE            = datetime.date.today().isoformat()
MIN_PRICE           = 10.0
MAX_POSITIONS       = 20
POSITION_SIZE       = 0.05        # base 5%
POSITION_SIZE_HIGH  = 0.075       # 7.5% when VIX < 15
POSITION_SIZE_LOW   = 0.025       # 2.5% when VIX > 25
MA_WINDOW           = 200
CONSEC_DOWN         = 4
INITIAL_CAPITAL     = 100_000.0

RSI_PERIOD          = 2
RSI_THRESHOLD       = 20
ATR_PERIOD          = 14
ATR_MIN_PCT         = 0.01
VOL_MA_PERIOD       = 20
MIN_PROFIT_PCT      = 0.010       # 1% min up-day to exit
MAX_HOLD_DAYS       = 10          # time stop
EARNINGS_BLACKOUT   = 3           # days around earnings to skip
GAP_DOWN_MAX        = -0.015      # skip entry if gap down > 1.5%
SECTOR_MA_WINDOW    = 50
VIX_HIGH            = 25
VIX_LOW             = 15
COMMISSION_RATE     = 0.005
COMMISSION_MIN      = 1.00

OUTPUT_DIR          = Path("results")
OUTPUT_DIR.mkdir(exist_ok=True)

SECTOR_ETFS = {
    "XLK": ["AAPL","MSFT","NVDA","AVGO","CSCO","ORCL","IBM","QCOM","TXN","INTC",
             "AMD","NOW","INTU","AMAT","ADI","MU","KLAC","LRCX","MCHP","CDNS"],
    "XLV": ["UNH","JNJ","LLY","ABBV","MRK","TMO","ABT","DHR","BMY","AMGN",
             "PFE","ISRG","MDT","GILD","VRTX","BSX","SYK","REGN","ZTS","CI"],
    "XLF": ["JPM","BAC","WFC","GS","MS","BLK","AXP","SPGI","V","MA",
             "USB","PNC","TFC","COF","CB","ICE","CME","MCO","AON","TRV"],
    "XLY": ["AMZN","TSLA","HD","MCD","NKE","LOW","SBUX","TGT","CMG","BKNG",
             "TJX","DHI","GM","F","ORLY","LEN","EBAY","ETSY","YUM","DRI"],
    "XLP": ["PG","KO","PEP","COST","WMT","PM","MO","MDLZ","CL","KMB",
             "EL","KR","STZ","GIS","HRL","SJM","CAG","K","CPB","CHD"],
    "XLE": ["XOM","CVX","COP","SLB","EOG","MPC","PSX","VLO","HAL","BKR",
             "FANG","DVN","HES","OXY","APA","MRO","CTRA","EQT","NOV","FTI"],
    "XLI": ["GE","HON","UPS","BA","CAT","RTX","DE","LMT","UNP","MMM",
             "ETN","EMR","NOC","GD","PH","ROK","IR","ITW","TT","CARR"],
    "XLB": ["LIN","APD","SHW","ECL","NEM","FCX","NUE","DOW","DD","PPG",
             "ALB","CF","MOS","CE","IFF","RPM","FMC","SON","SEE","AMCR"],
    "XLU": ["NEE","DUK","SO","D","AEP","EXC","SRE","PEG","ED","XEL",
             "ES","FE","ETR","PPL","CMS","NI","ATO","LNT","EVRG","PNW"],
    "XLRE": ["PLD","AMT","CCI","EQIX","PSA","O","WELL","DLR","EQR","AVB",
              "SPG","WY","ARE","MAA","UDR","CPT","ESS","AIV","IRM","VTR"],
    "XLC": ["META","GOOGL","GOOG","NFLX","DIS","CMCSA","T","VZ","TMUS","CHTR",
             "ATVI","EA","WBD","PARA","FOXA","FOX","NWS","NWSA","OMC","IPG"],
}
TICKER_TO_SECTOR: dict[str, str] = {}
for etf, members in SECTOR_ETFS.items():
    for tkr in members:
        TICKER_TO_SECTOR[tkr] = etf


# ─────────────────────────────────────────────────────────────────────────────
# 1.  Universe
# ─────────────────────────────────────────────────────────────────────────────
def _fetch_wiki(url: str) -> list:
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return pd.read_html(io.StringIO(resp.text), header=0)


def get_universe() -> list[str]:
    tickers: set[str] = set()

    for url, label in [
        ("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "S&P 500"),
        ("https://en.wikipedia.org/wiki/List_of_S%26P_400_companies", "S&P 400"),
    ]:
        try:
            tables = _fetch_wiki(url)
            for col in ["Symbol", "Ticker symbol", "Ticker"]:
                if col in tables[0].columns:
                    syms = tables[0][col].tolist()
                    tickers.update([s.replace(".", "-") for s in syms])
                    print(f"[Universe] {label}: {len(syms)} symbols")
                    break
            # historical changes (2nd table, S&P 500 only)
            if "500" in label and len(tables) > 1:
                for col in tables[1].columns:
                    cs = tables[1][col].dropna().astype(str)
                    if cs.str.match(r"^[A-Z]{1,5}(-[A-Z])?$").mean() > 0.3:
                        tickers.update([s.replace(".", "-") for s in cs])
        except Exception as e:
            print(f"[Universe] {label} fetch failed: {e}")

    historical_extras = [
        "LEH","BSC","WB","WAMU","MER","C","AIG","FNM","FRE",
        "YHOO","SUNW","PALM","Q","NT","GLW","JDS","CSCO","T",
        "GE","GM","F","XOM","CVX","IBM","MSFT","AAPL","AMZN",
        "GOOG","GOOGL","META","NVDA","TSLA","BRK-B","JPM","BAC",
        "WFC","GS","MS","USB","PNC","TFC","COF","AXP","V","MA",
        "HD","LOW","TGT","WMT","COST","KR","CVS","WBA",
        "UNH","CI","HUM","CNC","MOH","CAH","JNJ","PFE","MRK",
        "ABBV","BMY","AMGN","GILD","BIIB","LLY","REGN","VRTX",
        "ZTS","ISRG","BSX","SYK","MDT","BA","LMT","RTX","NOC",
        "GD","HII","TXT","CAT","DE","EMR","HON","MMM","ETN",
        "PH","ROK","COP","EOG","SLB","HAL","BKR","MPC","VLO",
        "NEE","DUK","SO","AEP","EXC","SRE","PCG","ED","FE",
        "AMT","PLD","CCI","SPG","O","WELL","PSA","EQR","AVB",
        "SBUX","MCD","YUM","CMG","DRI","QSR","DIS","NFLX",
        "CMCSA","VZ","CHTR","TMUS","PG","KO","PEP","CL","KMB","CHD","EL",
    ]
    tickers.update(historical_extras)
    result = sorted(tickers)
    print(f"[Universe] Total unique tickers: {len(result)}")
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 2.  Downloads
# ─────────────────────────────────────────────────────────────────────────────
def download_prices(tickers: list[str]) -> dict[str, pd.DataFrame]:
    print(f"\n[Download] Fetching {len(tickers)} tickers ({START_DATE} -> {END_DATE}) ...")
    all_data: dict[str, pd.DataFrame] = {}
    for i in tqdm(range(0, len(tickers), 100), desc="Downloading"):
        chunk = tickers[i : i + 100]
        try:
            raw = yf.download(chunk, start=START_DATE, end=END_DATE,
                              auto_adjust=True, progress=False, threads=True)
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
            elif chunk:
                all_data[chunk[0]] = raw.dropna(how="all")
        except Exception as e:
            print(f"[Download] Chunk error: {e}")
    print(f"[Download] Downloaded {len(all_data)} tickers.")
    return all_data


def _dl_single(ticker: str) -> pd.DataFrame:
    df = yf.download(ticker, start=START_DATE, end=END_DATE,
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df


def download_reference_data() -> tuple:
    # SPY
    spy   = _dl_single("SPY")
    close = spy["Close"].squeeze()
    spy["spy_ma200"] = close.rolling(200).mean()
    spy["spy_ok"]    = (close > spy["spy_ma200"].squeeze()).values
    print(f"[Download] SPY: {len(spy)} rows")

    # VIX
    vix = _dl_single("^VIX")
    print(f"[Download] VIX: {len(vix)} rows")

    # Sector ETFs
    etf_list = list(SECTOR_ETFS.keys())
    sector_data: dict[str, pd.DataFrame] = {}
    raw = yf.download(etf_list, start=START_DATE, end=END_DATE,
                      auto_adjust=True, progress=False, threads=True)
    if not raw.empty:
        for etf in etf_list:
            try:
                if isinstance(raw.columns, pd.MultiIndex):
                    df = raw.xs(etf, axis=1, level=1).dropna(how="all")
                else:
                    df = raw.copy()
                cs = df["Close"].squeeze()
                df = df.copy()
                df["ma50"] = cs.rolling(SECTOR_MA_WINDOW).mean()
                df["ok"]   = (cs > df["ma50"].squeeze()).values
                sector_data[etf] = df
            except Exception:
                pass
    print(f"[Download] Sector ETFs loaded: {len(sector_data)}")

    return spy, vix, sector_data


# ─────────────────────────────────────────────────────────────────────────────
# 3.  Earnings calendar
# ─────────────────────────────────────────────────────────────────────────────
def build_earnings_dates(tickers: list[str]) -> dict[str, set]:
    print(f"[Earnings] Building calendar for {len(tickers)} tickers ...")
    earnings_map: dict[str, set] = {}
    for tkr in tqdm(tickers, desc="Earnings"):
        try:
            cal = yf.Ticker(tkr).calendar
            if cal is None or (hasattr(cal, "empty") and cal.empty):
                continue
            dates: set = set()
            for col in cal.columns:
                for val in cal[col].dropna():
                    try:
                        dates.add(pd.Timestamp(val).normalize())
                    except Exception:
                        pass
            if dates:
                earnings_map[tkr] = dates
        except Exception:
            pass
    print(f"[Earnings] Calendar built: {len(earnings_map)} tickers with dates.")
    return earnings_map


def near_earnings(tkr: str, date, earnings_map: dict[str, set]) -> bool:
    if tkr not in earnings_map:
        return False
    d = pd.Timestamp(date).normalize()
    return any(abs((d - e).days) <= EARNINGS_BLACKOUT for e in earnings_map[tkr])


# ─────────────────────────────────────────────────────────────────────────────
# 4.  Signal generation
# ─────────────────────────────────────────────────────────────────────────────
def compute_rsi(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ma200"]    = df["Close"].rolling(MA_WINDOW).mean()
    df["above_ma"] = df["Close"] > df["ma200"]

    df["down_day"] = (df["Close"] < df["Close"].shift(1)).astype(int)
    consec, count = [], 0
    for d in df["down_day"]:
        count = count + 1 if d == 1 else 0
        consec.append(count)
    df["consec_down"] = consec

    df["rsi2"] = compute_rsi(df["Close"], RSI_PERIOD)

    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - df["Close"].shift(1)).abs(),
        (df["Low"]  - df["Close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["atr"]     = tr.rolling(ATR_PERIOD).mean()
    df["atr_pct"] = df["atr"] / df["Close"]

    df["vol_ma20"]    = df["Volume"].rolling(VOL_MA_PERIOD).mean()
    df["vol_confirm"] = df["Volume"] > df["vol_ma20"]

    df["signal"] = (
        df["above_ma"]                     &
        (df["consec_down"] >= CONSEC_DOWN) &
        (df["rsi2"] < RSI_THRESHOLD)       &
        (df["atr_pct"] > ATR_MIN_PCT)      &
        df["vol_confirm"]                  &
        (df["Close"] >= MIN_PRICE)
    )
    return df


# ─────────────────────────────────────────────────────────────────────────────
# 5.  Helpers
# ─────────────────────────────────────────────────────────────────────────────
def calc_commission(shares: float, price: float) -> float:
    return max(shares * COMMISSION_RATE, COMMISSION_MIN)


def get_position_size(today, vix_df: pd.DataFrame) -> float:
    try:
        vc = vix_df["Close"].squeeze()
        if today in vc.index:
            v = float(vc.loc[today])
            if v > VIX_HIGH:
                return POSITION_SIZE_LOW
            if v < VIX_LOW:
                return POSITION_SIZE_HIGH
    except Exception:
        pass
    return POSITION_SIZE


def sector_ok(tkr: str, date, sector_data: dict[str, pd.DataFrame]) -> bool:
    etf = TICKER_TO_SECTOR.get(tkr)
    if etf is None or etf not in sector_data:
        return True
    df = sector_data[etf]
    if date not in df.index:
        return True
    return bool(df.loc[date, "ok"])


# ─────────────────────────────────────────────────────────────────────────────
# 6.  Backtest
# ─────────────────────────────────────────────────────────────────────────────
def run_backtest(price_data, spy_df, vix_df, sector_data, earnings_map) -> pd.DataFrame:
    print("\n[Backtest] Running V4 simulation ...")
    spy_regime = spy_df["spy_ok"].to_dict()

    all_dates: set = set()
    for df in price_data.values():
        all_dates.update(df.index)
    trading_dates = sorted(all_dates)

    signals: dict[str, pd.DataFrame] = {}
    min_bars = MA_WINDOW + VOL_MA_PERIOD + ATR_PERIOD + CONSEC_DOWN + 5
    for tkr, df in tqdm(price_data.items(), desc="Generating signals"):
        if len(df) > min_bars:
            signals[tkr] = generate_signals(df)

    portfolio_value = INITIAL_CAPITAL
    open_positions: dict[str, dict] = {}
    trades: list[dict] = []

    for today in tqdm(trading_dates, desc="Simulating"):
        spy_ok = spy_regime.get(today, True)

        # ── Exits ─────────────────────────────────────────────────────────────
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
            days_held  = (today - pos["entry_date"]).days

            time_stop  = days_held >= MAX_HOLD_DAYS
            up_pct     = (row["Close"] - prev_close) / prev_close
            profit_hit = up_pct >= MIN_PROFIT_PCT

            if time_stop or profit_hit:
                exit_price = row["Close"]
                commission = calc_commission(pos["shares"], exit_price)
                pnl        = (exit_price - pos["entry_price"]) * pos["shares"] - commission
                pnl_pct    = (exit_price / pos["entry_price"] - 1) * 100
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
                    "exit_reason"  : "time_stop" if time_stop else "profit_target",
                    "portfolio_val": portfolio_value + pnl,
                })
                portfolio_value += pnl
                to_close.append(tkr)

        for tkr in to_close:
            del open_positions[tkr]

        if not spy_ok or len(open_positions) >= MAX_POSITIONS:
            continue

        # ── Entries ───────────────────────────────────────────────────────────
        candidates = []
        for tkr, tkr_df in signals.items():
            if tkr in open_positions or today not in tkr_df.index:
                continue
            if not tkr_df.loc[today]["signal"]:
                continue
            if near_earnings(tkr, today, earnings_map):
                continue
            if not sector_ok(tkr, today, sector_data):
                continue
            candidates.append((tkr, float(tkr_df.loc[today]["rsi2"])))

        # Rank by RSI(2) ascending — most oversold first
        candidates.sort(key=lambda x: x[1])

        for tkr, rsi_val in candidates:
            if len(open_positions) >= MAX_POSITIONS:
                break
            tkr_df    = signals[tkr]
            today_idx = tkr_df.index.get_loc(today)
            if today_idx + 1 >= len(tkr_df):
                continue
            next_row    = tkr_df.iloc[today_idx + 1]
            entry_price = float(next_row["Open"])
            if entry_price < MIN_PRICE or entry_price <= 0:
                continue

            # Gap filter
            gap_pct = (entry_price - float(tkr_df.iloc[today_idx]["Close"])) / \
                       float(tkr_df.iloc[today_idx]["Close"])
            if gap_pct < GAP_DOWN_MAX:
                continue

            pos_size      = get_position_size(today, vix_df)
            shares        = (portfolio_value * pos_size) / entry_price
            entry_comm    = calc_commission(shares, entry_price)

            open_positions[tkr] = {
                "entry_date"       : tkr_df.index[today_idx + 1],
                "entry_price"      : entry_price,
                "shares"           : shares,
                "entry_commission" : entry_comm,
            }

    print(f"[Backtest] Complete — {len(trades)} trades executed.")
    return pd.DataFrame(trades)


# ─────────────────────────────────────────────────────────────────────────────
# 7.  Metrics
# ─────────────────────────────────────────────────────────────────────────────
def compute_metrics(trades_df: pd.DataFrame) -> tuple:
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
    avg_win  = winners["pnl_pct"].mean() if len(winners) else 0
    avg_loss = losers["pnl_pct"].mean()  if len(losers)  else 0

    eq_df["peak"] = eq_df["equity"].cummax()
    eq_df["dd"]   = (eq_df["equity"] - eq_df["peak"]) / eq_df["peak"] * 100
    max_dd        = eq_df["dd"].min()

    gp = winners["pnl_usd"].sum()
    gl = abs(losers["pnl_usd"].sum())
    pf = gp / gl if gl > 0 else float("inf")

    eq_df["date"] = pd.to_datetime(eq_df["date"])
    eq_df.set_index("date", inplace=True)
    monthly_ret = eq_df["equity"].resample("ME").last().ffill().pct_change().dropna()
    sharpe = monthly_ret.mean() / monthly_ret.std() * np.sqrt(12) if monthly_ret.std() > 0 else 0

    total_comm  = trades_df["commission"].sum() if "commission" in trades_df else 0
    exit_counts = trades_df["exit_reason"].value_counts().to_dict() if "exit_reason" in trades_df.columns else {}

    metrics = {
        "period_start"        : start_dt.date().isoformat(),
        "period_end"          : end_dt.date().isoformat(),
        "years_tested"        : round(years, 2),
        "total_trades"        : len(trades_df),
        "trades_per_year"     : round(len(trades_df) / years, 1),
        "win_rate_pct"        : round(win_rate, 2),
        "cagr_pct"            : round(cagr * 100, 2),
        "roi_per_year_pct"    : round((equity - INITIAL_CAPITAL) / INITIAL_CAPITAL / years * 100, 2),
        "avg_days_held"       : round(trades_df["days_held"].mean(), 2),
        "avg_win_pct"         : round(avg_win, 2),
        "avg_loss_pct"        : round(avg_loss, 2),
        "profit_factor"       : round(pf, 2),
        "max_drawdown_pct"    : round(max_dd, 2),
        "sharpe_ratio"        : round(sharpe, 2),
        "exit_reasons"        : {k: int(v) for k, v in exit_counts.items()},
        "total_commission_usd": round(total_comm, 2),
        "initial_capital"     : INITIAL_CAPITAL,
        "final_equity"        : round(equity, 2),
        "total_return_pct"    : round((equity / INITIAL_CAPITAL - 1) * 100, 2),
        "enhancements"        : {
            "rsi2_threshold"     : RSI_THRESHOLD,
            "atr_min_pct"        : ATR_MIN_PCT,
            "min_profit_pct"     : MIN_PROFIT_PCT,
            "max_hold_days"      : MAX_HOLD_DAYS,
            "earnings_blackout"  : EARNINGS_BLACKOUT,
            "gap_down_max_pct"   : GAP_DOWN_MAX,
            "sector_ma_window"   : SECTOR_MA_WINDOW,
            "vix_high"           : VIX_HIGH,
            "vix_low"            : VIX_LOW,
            "spy_regime_filter"  : True,
            "signal_ranking"     : "RSI(2) ascending",
            "universe"           : "S&P500 + S&P400",
            "commission_rate"    : COMMISSION_RATE,
        }
    }
    return metrics, eq_df.reset_index()


# ─────────────────────────────────────────────────────────────────────────────
# 8.  Save + print
# ─────────────────────────────────────────────────────────────────────────────
def save_outputs(trades_df, metrics, eq_df):
    trades_df.to_csv(OUTPUT_DIR / "trades.csv", index=False)
    eq_df.to_csv(OUTPUT_DIR / "equity_curve.csv", index=False)
    with open(OUTPUT_DIR / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, default=str)

    print("\n" + "="*62)
    print("  ENHANCED NAIVE MR BACKTEST V4 — RESULTS SUMMARY")
    print("="*62)
    for k, v in metrics.items():
        if k in ("enhancements", "exit_reasons"):
            label = "Enhancements Applied" if k == "enhancements" else "Exit Reason Breakdown"
            print(f"\n  {label}:")
            for ek, ev in v.items():
                print(f"    {ek:<32}: {ev}")
        else:
            print(f"  {k.replace('_',' ').title():<32}: {v}")
    print("="*62)


# ─────────────────────────────────────────────────────────────────────────────
# 9.  Entry point
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    universe     = get_universe()
    price_data   = download_prices(universe)
    spy_df, vix_df, sector_data = download_reference_data()
    earnings_map = build_earnings_dates(list(price_data.keys()))
    trades_df    = run_backtest(price_data, spy_df, vix_df, sector_data, earnings_map)

    if trades_df.empty:
        print("[ERROR] No trades generated.")
    else:
        metrics, eq_df = compute_metrics(trades_df)
        save_outputs(trades_df, metrics, eq_df)
