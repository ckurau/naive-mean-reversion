""" Enhanced Naive Mean Reversion (MR) Backtest — V37a
==================================================
Base: V33d — $3,124,041 final equity, 17.41% CAGR. Current best.

V37a CHANGE vs V33d (1 addition — no other changes):
  [V37a-1] Breadth filter: block new entries when market breadth is weak.
           Breadth = % of S&P 500 stocks simultaneously above their 20d MA
           AND above their 50d MA.
           If breadth < BREADTH_THRESHOLD (40%), no new entries that day.
           Existing positions continue to their normal exits unchanged.

RATIONALE:
  In grind-down regimes, market breadth collapses before SPY hits its 200d MA.
  The 200d filter is too slow — it blocks entries only after significant damage.
  Breadth measures internals directly: if fewer than 40% of stocks are above
  both their 20d and 50d MA simultaneously, the market is in broad deterioration,
  not a temporary dislocation. Mean reversion edge degrades in this environment.

  This is different from all previous failed filters because:
  - It does NOT react to P&L, drawdown, or win rate (outcome-based)
  - It reacts to market structure (orthogonal signal class)
  - It does NOT exit existing positions (no cutting winners)
  - It only gates new entries

WHAT TO LOOK FOR:
  Pass (improvement):
    Max DD improves meaningfully (>3pp)
    CAGR drops less than 1% (breadth filter should rarely fire in good regimes)
    Win rate unchanged or slightly higher (fewer bad entries)
    Check 2022 P&L specifically — should improve
  Fail (not worth keeping):
    CAGR drops >1.5% (filter firing too often in good regimes)
    2019/2020 P&L damaged (filter blocking recovery entries)
    Win rate unchanged and DD unchanged (filter not firing when needed)

RESULTS HISTORY:
  V33d:    CAGR 17.41% | $3.12M  ← baseline
  V34a:    CAGR 15.50% | $2.20M  ← partial loss exit (rejected)
  V35a:    CAGR 17.26% | $3.04M  ← higher targets (rejected)
  V36a:    CAGR 16.42% | $2.60M  ← signal density filter (rejected)
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
START_DATE  = "2004-01-01"
END_DATE    = datetime.date.today().isoformat()

MIN_DOLLAR_VOLUME      = 5_000_000
MAX_POSITIONS          = 60
POSITION_SIZE          = 0.05
POSITION_SIZE_HIGH     = 0.09
POSITION_SIZE_LOW      = 0.025
POSITION_SIZE_EARNINGS = 0.03
MA_WINDOW              = 200
INITIAL_CAPITAL        = 100_000.0
RSI_PERIOD             = 2
RSI_THRESHOLD          = 20
ATR_PERIOD             = 14
ATR_MIN_PCT            = 0.01
VOL_MA_PERIOD          = 20
MIN_HOLD_BEFORE_EXIT   = 2

# ── Tier system ───────────────────────────────────────────────────────────────
TIER1_MIN_DOWN        = 6
TIER1_TARGET          = 0.020
TIER1_HOLD_DAYS       = 8
TIER1_PARTIAL         = True
TIER1_PARTIAL_FRAC    = 0.50
TIER1_PARTIAL_TRIGGER = 0.010

TIER2_MIN_DOWN        = 5
TIER2_TARGET          = 0.020
TIER2_HOLD_DAYS       = 8
TIER2_PARTIAL         = False
TIER2_PARTIAL_FRAC    = 0.0
TIER2_PARTIAL_TRIGGER = 0.0

TIER3_MIN_DOWN        = 4
TIER3_TARGET          = 0.020
TIER3_HOLD_DAYS       = 8
TIER3_PARTIAL         = False
TIER3_PARTIAL_FRAC    = 0.0
TIER3_PARTIAL_TRIGGER = 0.0

MIN_CONSEC_DOWN = TIER3_MIN_DOWN

# ── [V22-1] Drawdown scaling REMOVED ─────────────────────────────────────────
DD_SCALE_MILD          = 9.99
DD_SCALE_SEVERE        = 9.99
POSITION_SIZE_DD_MILD  = 0.03
POSITION_SIZE_DD_SEVERE = 0.02

# ── [V21] Velocity crash pause ────────────────────────────────────────────────
VELOCITY_CRASH_5D_THRESHOLD = -0.12
VELOCITY_CRASH_PAUSE_DAYS   = 5

# ── Filters ───────────────────────────────────────────────────────────────────
EARNINGS_BLACKOUT    = 3
GAP_DOWN_MAX         = -0.015
GAP_UP_MAX           = 0.020
SECTOR_MA_WINDOW     = 20
MAX_SECTOR_POSITIONS = 3
VIX_HIGH             = 999
VIX_LOW              = 25
VIX_SPIKE_PCT        = 0.30
VIX_SPIKE_PAUSE_DAYS = 0
REENTRY_COOLDOWN_DAYS = 5
COMMISSION_RATE      = 0.005
COMMISSION_MIN       = 0.35
EARNINGS_MONTHS      = {1, 4, 7, 10}

# ── [V37a] Breadth filter ─────────────────────────────────────────────────────
# Block new entries when fewer than BREADTH_THRESHOLD of S&P 500 stocks
# are simultaneously above their 20d MA AND 50d MA.
BREADTH_THRESHOLD    = 0.40   # 40% of stocks must be above both MAs
BREADTH_MA_SHORT     = 20     # short MA window for breadth
BREADTH_MA_LONG      = 50     # long MA window for breadth

OUTPUT_DIR = Path("results")
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
for _etf, _members in SECTOR_ETFS.items():
    for _t in _members:
        TICKER_TO_SECTOR[_t] = _etf


def get_tier(consec_down: int) -> dict:
    if consec_down >= TIER1_MIN_DOWN:
        return {"tier": 1, "profit_target": TIER1_TARGET, "hold_days": TIER1_HOLD_DAYS,
                "partial_enabled": TIER1_PARTIAL, "partial_frac": TIER1_PARTIAL_FRAC,
                "partial_trigger": TIER1_PARTIAL_TRIGGER}
    elif consec_down >= TIER2_MIN_DOWN:
        return {"tier": 2, "profit_target": TIER2_TARGET, "hold_days": TIER2_HOLD_DAYS,
                "partial_enabled": TIER2_PARTIAL, "partial_frac": TIER2_PARTIAL_FRAC,
                "partial_trigger": TIER2_TARGET}
    else:
        return {"tier": 3, "profit_target": TIER3_TARGET, "hold_days": TIER3_HOLD_DAYS,
                "partial_enabled": TIER3_PARTIAL, "partial_frac": TIER3_PARTIAL_FRAC,
                "partial_trigger": TIER3_TARGET}


# ─────────────────────────────────────────────────────────────────────────────
# 1. Universe
# ─────────────────────────────────────────────────────────────────────────────
def _fetch_wiki(url: str) -> list:
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                              "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return pd.read_html(io.StringIO(resp.text), header=0)


def _extract_tickers_from_table(table: pd.DataFrame) -> list[str]:
    for col in ["Symbol", "Ticker symbol", "Ticker", "Ticker Symbol"]:
        if col in table.columns:
            return table[col].dropna().astype(str).tolist()
    for col in table.columns:
        cs = table[col].dropna().astype(str)
        if cs.str.match(r"^[A-Z]{1,5}(-[A-Z])?$").mean() > 0.3:
            return cs.tolist()
    return []


def get_universe() -> list[str]:
    tickers: set[str] = set()
    for url, label in [
        ("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "S&P 500"),
        ("https://en.wikipedia.org/wiki/List_of_S%26P_400_companies", "S&P 400"),
        ("https://en.wikipedia.org/wiki/List_of_S%26P_600_companies", "S&P 600"),
    ]:
        try:
            tables = _fetch_wiki(url)
            found = False
            for i, table in enumerate(tables):
                syms = _extract_tickers_from_table(table)
                if len(syms) >= 100:
                    tickers.update([s.replace(".", "-") for s in syms])
                    print(f"[Universe] {label}: {len(syms)} symbols (table {i})")
                    found = True
                    break
            if not found:
                print(f"[Universe] {label}: WARNING — no valid ticker table found")
        except Exception as e:
            print(f"[Universe] {label} failed: {e}")

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
# 2. Downloads
# ─────────────────────────────────────────────────────────────────────────────
def download_prices(tickers: list[str]) -> dict[str, pd.DataFrame]:
    print(f"\n[Download] Fetching {len(tickers)} tickers ({START_DATE} -> {END_DATE}) ...")
    all_data: dict[str, pd.DataFrame] = {}
    for i in tqdm(range(0, len(tickers), 100), desc="Downloading"):
        chunk = tickers[i: i + 100]
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


def _compute_rsi(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def build_breadth_series(price_data: dict[str, pd.DataFrame]) -> pd.Series:
    """
    [V37a] Compute daily breadth: fraction of stocks simultaneously above
    their BREADTH_MA_SHORT (20d) AND BREADTH_MA_LONG (50d) moving averages.
    Uses only S&P 500 tickers (sp500_tickers) to keep breadth measurement
    consistent — breadth of the S&P 500 is a well-established market indicator.
    Falls back to all available tickers if S&P 500 subset is too small.
    """
    print("[Breadth] Computing breadth series ...")

    # Collect close prices for all tickers into a single DataFrame
    closes = {}
    for tkr, df in price_data.items():
        if "Close" in df.columns:
            closes[tkr] = df["Close"].squeeze()

    if not closes:
        print("[Breadth] WARNING: no close data available, breadth disabled")
        return pd.Series(dtype=float)

    close_df = pd.DataFrame(closes)

    # Compute 20d and 50d MAs, then check if price > both
    ma_short = close_df.rolling(BREADTH_MA_SHORT).mean()
    ma_long  = close_df.rolling(BREADTH_MA_LONG).mean()
    above_both = (close_df > ma_short) & (close_df > ma_long)

    # Daily breadth = fraction of stocks above both MAs
    breadth = above_both.mean(axis=1)
    print(f"[Breadth] Computed {len(breadth)} days. "
          f"Avg breadth: {breadth.mean():.2%}, "
          f"Min: {breadth.min():.2%}, Max: {breadth.max():.2%}")
    return breadth


def download_reference_data() -> tuple:
    spy       = _dl_single("SPY")
    close     = spy["Close"].squeeze()
    spy["spy_ma200"]  = close.rolling(200).mean()
    spy["spy_ok"]     = (close > spy["spy_ma200"].squeeze()).values
    spy["spy_5d_ret"] = close.pct_change(5)
    print(f"[Download] SPY: {len(spy)} rows")

    vix       = _dl_single("^VIX")
    vix_close = vix["Close"].squeeze()
    vix["vix_5d_ago"] = vix_close.shift(5)
    vix["vix_spike"]  = (vix_close / vix["vix_5d_ago"].replace(0, np.nan) - 1) >= VIX_SPIKE_PCT
    print(f"[Download] VIX: {len(vix)} rows")

    etf_list    = list(SECTOR_ETFS.keys())
    sector_data: dict[str, pd.DataFrame] = {}
    raw = yf.download(etf_list, start=START_DATE, end=END_DATE,
                      auto_adjust=True, progress=False, threads=True)
    if not raw.empty:
        for etf in etf_list:
            try:
                df = (raw.xs(etf, axis=1, level=1).dropna(how="all")
                      if isinstance(raw.columns, pd.MultiIndex) else raw.copy())
                cs = df["Close"].squeeze()
                df = df.copy()
                df["ma"] = cs.rolling(SECTOR_MA_WINDOW).mean()
                df["ok"] = (cs > df["ma"].squeeze()).values
                sector_data[etf] = df
            except Exception:
                pass
    print(f"[Download] Sector ETFs: {len(sector_data)}")
    return spy, vix, sector_data


# ─────────────────────────────────────────────────────────────────────────────
# 3. Earnings calendar
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
    print(f"[Earnings] Done: {len(earnings_map)} tickers with dates.")
    return earnings_map


def near_earnings(tkr: str, date, earnings_map: dict[str, set]) -> bool:
    if tkr not in earnings_map:
        return False
    d = pd.Timestamp(date).normalize()
    return any(abs((d - e).days) <= EARNINGS_BLACKOUT for e in earnings_map[tkr])


# ─────────────────────────────────────────────────────────────────────────────
# 4. Signal generation
# ─────────────────────────────────────────────────────────────────────────────
def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ma200"]     = df["Close"].rolling(MA_WINDOW).mean()
    df["above_ma"]  = df["Close"] > df["ma200"]
    df["down_day"]  = (df["Close"] < df["Close"].shift(1)).astype(int)
    consec, count   = [], 0
    for d in df["down_day"]:
        count = count + 1 if d == 1 else 0
        consec.append(count)
    df["consec_down"] = consec
    df["rsi2"]        = _compute_rsi(df["Close"], RSI_PERIOD)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - df["Close"].shift(1)).abs(),
        (df["Low"]  - df["Close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["atr"]             = tr.rolling(ATR_PERIOD).mean()
    df["atr_pct"]         = df["atr"] / df["Close"]
    df["vol_ma20"]        = df["Volume"].rolling(VOL_MA_PERIOD).mean()
    df["vol_confirm"]     = df["Volume"] > df["vol_ma20"]
    df["dollar_vol_ma20"] = (df["Close"] * df["Volume"]).rolling(VOL_MA_PERIOD).mean()
    df["signal"] = (
        df["above_ma"]
        & (df["consec_down"] >= MIN_CONSEC_DOWN)
        & (df["rsi2"] < RSI_THRESHOLD)
        & (df["atr_pct"] > ATR_MIN_PCT)
        & df["vol_confirm"]
        & (df["dollar_vol_ma20"] >= MIN_DOLLAR_VOLUME)
    )
    return df


# ─────────────────────────────────────────────────────────────────────────────
# 5. Helpers
# ─────────────────────────────────────────────────────────────────────────────
def calc_commission(shares: float, price: float) -> float:
    return max(shares * COMMISSION_RATE, COMMISSION_MIN)


def get_position_size(today, vix_df, drawdown_pct: float = 0.0) -> float:
    month          = pd.Timestamp(today).month
    earnings_month = month in EARNINGS_MONTHS
    base           = POSITION_SIZE
    try:
        vc = vix_df["Close"].squeeze()
        if today in vc.index:
            v = float(vc.loc[today])
            if v < VIX_LOW:
                base = POSITION_SIZE_HIGH
    except Exception:
        pass
    if drawdown_pct <= -DD_SCALE_SEVERE:
        base = min(base, POSITION_SIZE_DD_SEVERE)
    elif drawdown_pct <= -DD_SCALE_MILD:
        base = min(base, POSITION_SIZE_DD_MILD)
    if earnings_month and base > POSITION_SIZE_EARNINGS:
        base = POSITION_SIZE_EARNINGS
    return base


def sector_ok(tkr: str, date, sector_data: dict) -> bool:
    etf = TICKER_TO_SECTOR.get(tkr)
    if etf is None or etf not in sector_data:
        return True
    df = sector_data[etf]
    if date not in df.index:
        return True
    return bool(df.loc[date, "ok"])


def count_sector_positions(tkr: str, open_positions: dict) -> int:
    etf = TICKER_TO_SECTOR.get(tkr)
    if etf is None:
        return 0
    return sum(1 for t in open_positions if TICKER_TO_SECTOR.get(t) == etf)


def check_vix_spike(today, vix_df, last_spike_date) -> tuple:
    try:
        if today in vix_df.index and bool(vix_df.loc[today, "vix_spike"]):
            last_spike_date = today
    except Exception:
        pass
    if last_spike_date is not None:
        if (pd.Timestamp(today) - pd.Timestamp(last_spike_date)).days <= VIX_SPIKE_PAUSE_DAYS:
            return True, last_spike_date
    return False, last_spike_date


# ─────────────────────────────────────────────────────────────────────────────
# 6. Backtest simulation
# ─────────────────────────────────────────────────────────────────────────────
def run_backtest(price_data, spy_df, vix_df, sector_data, earnings_map) -> pd.DataFrame:
    print("\n[Backtest] Running V37a simulation (V33d + breadth filter) ...")

    # [V37a] Build breadth series from price data
    breadth_series = build_breadth_series(price_data)
    breadth_dict   = breadth_series.to_dict() if not breadth_series.empty else {}

    spy_regime  = spy_df["spy_ok"].to_dict()
    all_dates: set = set()
    for df in price_data.values():
        all_dates.update(df.index)
    trading_dates = sorted(all_dates)

    signals: dict[str, pd.DataFrame] = {}
    min_bars = MA_WINDOW + VOL_MA_PERIOD + ATR_PERIOD + MIN_CONSEC_DOWN + 5
    for tkr, df in tqdm(price_data.items(), desc="Generating signals"):
        if len(df) > min_bars:
            signals[tkr] = generate_signals(df)

    portfolio_value  = INITIAL_CAPITAL
    portfolio_peak   = None
    current_drawdown = 0.0
    open_positions: dict[str, dict] = {}
    trades: list[dict] = []
    cooldown_map: dict = {}
    last_vix_spike      = None
    last_velocity_crash = None

    breadth_blocked_days = 0  # diagnostic counter

    for today in tqdm(trading_dates, desc="Simulating"):
        spy_ok = spy_regime.get(today, True)
        paused, last_vix_spike = check_vix_spike(today, vix_df, last_vix_spike)

        velocity_paused = False
        try:
            if today in spy_df.index:
                spy_5d = float(spy_df.loc[today, "spy_5d_ret"])
                if not np.isnan(spy_5d) and spy_5d < VELOCITY_CRASH_5D_THRESHOLD:
                    last_velocity_crash = today
            if last_velocity_crash is not None:
                days_since = (pd.Timestamp(today) - pd.Timestamp(last_velocity_crash)).days
                if days_since <= VELOCITY_CRASH_PAUSE_DAYS:
                    velocity_paused = True
        except Exception:
            pass

        # [V37a] Breadth check
        breadth_ok = True
        if breadth_dict:
            b = breadth_dict.get(today, None)
            if b is not None and not np.isnan(b) and b < BREADTH_THRESHOLD:
                breadth_ok = False
                breadth_blocked_days += 1

        # Drawdown tracking
        if portfolio_peak is None:
            if portfolio_value != INITIAL_CAPITAL:
                portfolio_peak   = portfolio_value
                current_drawdown = 0.0
        else:
            if portfolio_value > portfolio_peak:
                portfolio_peak   = portfolio_value
                current_drawdown = 0.0
            else:
                current_drawdown = (portfolio_value - portfolio_peak) / portfolio_peak

        # ── Exits (unchanged) ──────────────────────────────────────────────────
        to_close = []
        for tkr, pos in open_positions.items():
            if tkr not in signals:
                continue
            tkr_df = signals[tkr]
            if today not in tkr_df.index:
                continue
            row         = tkr_df.loc[today]
            exit_price  = float(row["Close"])
            entry_price = pos["entry_price"]
            days_held   = (pd.Timestamp(today) - pd.Timestamp(pos["entry_date"])).days
            pos_pct     = (exit_price - entry_price) / entry_price
            shares_rem  = pos["shares_remaining"]
            early       = days_held < MIN_HOLD_BEFORE_EXIT
            time_stop   = days_held >= pos["hold_days"]
            profit_hit  = (not early) and pos_pct >= pos["profit_target"]

            if (pos["partial_enabled"] and not pos["partial_done"]
                    and not early and pos_pct >= pos["partial_trigger"]):
                partial_shares = shares_rem * pos["partial_frac"]
                commission     = calc_commission(partial_shares, exit_price)
                pnl            = (exit_price - entry_price) * partial_shares - commission
                trades.append({
                    "ticker": tkr, "entry_date": pos["entry_date"], "exit_date": today,
                    "entry_price": entry_price, "exit_price": exit_price,
                    "shares": partial_shares, "commission": round(commission, 4),
                    "pnl_usd": pnl, "pnl_pct": pos_pct * 100, "days_held": days_held,
                    "exit_reason": "partial_exit", "tier": pos["tier"],
                    "consec_down": pos["consec_down_at_entry"],
                    "portfolio_val": portfolio_value + pnl,
                })
                portfolio_value         += pnl
                pos["shares_remaining"] -= partial_shares
                pos["partial_done"]      = True
                pos["profit_target"]     = pos["profit_target"] * 2
                continue

            full_exit = (
                time_stop
                or (not pos["partial_enabled"] and profit_hit)
                or (pos["partial_enabled"] and pos["partial_done"] and profit_hit)
            )
            if full_exit:
                commission = calc_commission(shares_rem, exit_price)
                pnl        = ((exit_price - entry_price) * shares_rem
                              - commission - pos["entry_commission"])
                reason = "time_stop" if time_stop else "profit_target"
                trades.append({
                    "ticker": tkr, "entry_date": pos["entry_date"], "exit_date": today,
                    "entry_price": entry_price, "exit_price": exit_price,
                    "shares": shares_rem,
                    "commission": round(commission + pos["entry_commission"], 4),
                    "pnl_usd": pnl, "pnl_pct": pos_pct * 100, "days_held": days_held,
                    "exit_reason": reason, "tier": pos["tier"],
                    "consec_down": pos["consec_down_at_entry"],
                    "portfolio_val": portfolio_value + pnl,
                })
                portfolio_value += pnl
                if time_stop:
                    cooldown_map[tkr] = today
                to_close.append(tkr)

        for tkr in to_close:
            del open_positions[tkr]

        # [V37a] Block entries if breadth weak (in addition to existing filters)
        if not spy_ok or paused or velocity_paused or not breadth_ok:
            continue
        if len(open_positions) >= MAX_POSITIONS:
            continue

        # ── Entries (unchanged) ────────────────────────────────────────────────
        candidates = []
        for tkr, tkr_df in signals.items():
            if tkr in open_positions or today not in tkr_df.index:
                continue
            row = tkr_df.loc[today]
            if not row["signal"]:
                continue
            if tkr in cooldown_map:
                if (pd.Timestamp(today) - pd.Timestamp(cooldown_map[tkr])).days < REENTRY_COOLDOWN_DAYS:
                    continue
            if near_earnings(tkr, today, earnings_map):
                continue
            if not sector_ok(tkr, today, sector_data):
                continue
            if count_sector_positions(tkr, open_positions) >= MAX_SECTOR_POSITIONS:
                continue
            rsi2    = float(row["rsi2"])
            atr_pct = float(row["atr_pct"])
            composite_score = rsi2 / atr_pct if atr_pct > 0 else rsi2 * 1000
            candidates.append((composite_score, tkr, int(row["consec_down"]), rsi2))

        candidates.sort(key=lambda x: x[0])

        for composite_score, tkr, consec_val, rsi_val in candidates:
            if len(open_positions) >= MAX_POSITIONS:
                break
            tkr_df    = signals[tkr]
            today_idx = tkr_df.index.get_loc(today)
            if today_idx + 1 >= len(tkr_df):
                continue
            next_row    = tkr_df.iloc[today_idx + 1]
            entry_price = float(next_row["Open"])
            if entry_price <= 0:
                continue
            prev_close = float(tkr_df.iloc[today_idx]["Close"])
            gap_pct    = (entry_price - prev_close) / prev_close
            if gap_pct < GAP_DOWN_MAX or gap_pct > GAP_UP_MAX:
                continue
            tier_cfg   = get_tier(consec_val)
            pos_size   = get_position_size(today, vix_df, current_drawdown)
            shares     = (portfolio_value * pos_size) / entry_price
            entry_comm = calc_commission(shares, entry_price)
            open_positions[tkr] = {
                "entry_date": tkr_df.index[today_idx + 1], "entry_price": entry_price,
                "shares": shares, "shares_remaining": shares,
                "rsi2_at_entry": rsi_val, "consec_down_at_entry": consec_val,
                "profit_target": tier_cfg["profit_target"], "hold_days": tier_cfg["hold_days"],
                "partial_enabled": tier_cfg["partial_enabled"],
                "partial_frac": tier_cfg["partial_frac"],
                "partial_trigger": tier_cfg["partial_trigger"],
                "partial_done": False, "tier": tier_cfg["tier"],
                "entry_commission": entry_comm,
            }

    print(f"[Backtest] Complete — {len(trades)} trades executed.")
    print(f"[V37a] Breadth blocked entry on {breadth_blocked_days} days "
          f"({breadth_blocked_days/len(trading_dates)*100:.1f}% of trading days)")
    return pd.DataFrame(trades)


# ─────────────────────────────────────────────────────────────────────────────
# 7. Metrics
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

    eq_df    = pd.DataFrame(equity_curve)
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

    max_dd_duration_days = 0
    try:
        max_dur = 0; cur_dur = 0; prev_peak = INITIAL_CAPITAL
        for i, row in eq_df.iterrows():
            if row["equity"] >= row["peak"] and row["equity"] >= prev_peak:
                cur_dur = 0; prev_peak = row["equity"]
            else:
                cur_dur += 1
                if cur_dur > max_dur:
                    max_dur = cur_dur
        max_dd_duration_days = max_dur
    except Exception:
        pass

    gp = winners["pnl_usd"].sum()
    gl = abs(losers["pnl_usd"].sum())
    pf = gp / gl if gl > 0 else float("inf")

    eq_df_dt = eq_df.copy()
    eq_df_dt["date"] = pd.to_datetime(eq_df_dt["date"] if "date" in eq_df_dt.columns else eq_df_dt.index)
    eq_df_dt    = eq_df_dt.set_index("date")
    monthly_ret = eq_df_dt["equity"].resample("ME").last().ffill().pct_change().dropna()

    sharpe = (monthly_ret.mean() / monthly_ret.std() * np.sqrt(12) if monthly_ret.std() > 0 else 0)
    downside     = monthly_ret[monthly_ret < 0]
    downside_std = downside.std() if len(downside) > 1 else 0
    sortino      = (monthly_ret.mean() / downside_std * np.sqrt(12) if downside_std > 0 else 0)
    ret_std  = monthly_ret.std() * np.sqrt(12) * 100
    ret_skew = float(monthly_ret.skew()) if len(monthly_ret) > 3 else 0
    ret_kurt = float(monthly_ret.kurt()) if len(monthly_ret) > 3 else 0

    rolling_sharpe_vals, rolling_sortino_vals = [], []
    if len(monthly_ret) >= 12:
        for i in range(11, len(monthly_ret)):
            window = monthly_ret.iloc[i-11:i+1]
            ws  = window.mean() / window.std() * np.sqrt(12) if window.std() > 0 else 0
            rolling_sharpe_vals.append(ws)
            wd  = window[window < 0]
            wds = wd.std() if len(wd) > 1 else 0
            wso = window.mean() / wds * np.sqrt(12) if wds > 0 else 0
            rolling_sortino_vals.append(wso)

    rolling_sharpe_avg  = round(float(np.mean(rolling_sharpe_vals)),  2) if rolling_sharpe_vals else 0
    rolling_sharpe_min  = round(float(np.min(rolling_sharpe_vals)),   2) if rolling_sharpe_vals else 0
    rolling_sortino_avg = round(float(np.mean(rolling_sortino_vals)), 2) if rolling_sortino_vals else 0
    rolling_sortino_min = round(float(np.min(rolling_sortino_vals)),  2) if rolling_sortino_vals else 0

    median_days_held = float(trades_df["days_held"].median())
    total_comm       = trades_df["commission"].sum() if "commission" in trades_df else 0
    exit_counts      = (trades_df["exit_reason"].value_counts().to_dict()
                        if "exit_reason" in trades_df.columns else {})

    tier_stats = {}
    if "tier" in trades_df.columns:
        for t in sorted(trades_df["tier"].unique()):
            t_df  = trades_df[trades_df["tier"] == t]
            t_win = t_df[t_df["pnl_usd"] > 0]
            t_los = t_df[t_df["pnl_usd"] <= 0]
            tier_stats[f"tier_{t}"] = {
                "trades":   len(t_df),
                "win_rate": round((t_df["pnl_usd"] > 0).mean() * 100, 1),
                "avg_win":  round(t_win["pnl_pct"].mean(), 2) if len(t_win) else 0,
                "avg_loss": round(t_los["pnl_pct"].mean(), 2) if len(t_los) else 0,
                "avg_days": round(t_df["days_held"].mean(), 1),
            }

    trades_df["exit_year"] = pd.to_datetime(trades_df["exit_date"]).dt.year
    year_stats = {}
    for yr in sorted(trades_df["exit_year"].unique()):
        y_df  = trades_df[trades_df["exit_year"] == yr]
        y_win = y_df[y_df["pnl_usd"] > 0]
        year_stats[str(yr)] = {
            "trades":   len(y_df),
            "win_rate": round((y_df["pnl_usd"] > 0).mean() * 100, 1),
            "pnl_usd":  round(y_df["pnl_usd"].sum(), 2),
            "avg_win":  round(y_win["pnl_pct"].mean(), 2) if len(y_win) else 0,
        }

    full_exits   = (trades_df[trades_df["exit_reason"] != "partial_exit"]
                    if "exit_reason" in trades_df.columns else trades_df)
    time_stop_n  = exit_counts.get("time_stop", 0)
    time_stop_rt = round(time_stop_n / len(full_exits) * 100, 1) if len(full_exits) else 0

    metrics = {
        "version":         "V37a",
        "period_start":    start_dt.date().isoformat(),
        "period_end":      end_dt.date().isoformat(),
        "years_tested":    round(years, 2),
        "total_trades":    len(trades_df),
        "trades_per_year": round(len(trades_df) / years, 1),
        "cagr_pct":         round(cagr * 100, 2),
        "roi_per_year_pct": round((equity - INITIAL_CAPITAL) / INITIAL_CAPITAL / years * 100, 2),
        "final_equity":     round(equity, 2),
        "total_return_pct": round((equity / INITIAL_CAPITAL - 1) * 100, 2),
        "initial_capital":  INITIAL_CAPITAL,
        "sharpe_ratio":            round(sharpe,  2),
        "sortino_ratio":           round(sortino, 2),
        "rolling_sharpe_avg_12m":  rolling_sharpe_avg,
        "rolling_sharpe_min_12m":  rolling_sharpe_min,
        "rolling_sortino_avg_12m": rolling_sortino_avg,
        "rolling_sortino_min_12m": rolling_sortino_min,
        "max_drawdown_pct":             round(max_dd, 2),
        "max_drawdown_duration_trades": max_dd_duration_days,
        "win_rate_pct":  round(win_rate, 2),
        "profit_factor": round(pf, 2),
        "avg_win_pct":   round(avg_win,  2),
        "avg_loss_pct":  round(avg_loss, 2),
        "avg_days_held":    round(trades_df["days_held"].mean(), 2),
        "median_days_held": round(median_days_held, 2),
        "annual_return_std_pct":   round(ret_std,  2),
        "monthly_return_skewness": round(ret_skew, 3),
        "monthly_return_kurtosis": round(ret_kurt, 3),
        "time_stop_rate_pct":   time_stop_rt,
        "total_commission_usd": round(total_comm, 2),
        "exit_reasons":         {k: int(v) for k, v in exit_counts.items()},
        "tier_stats":           tier_stats,
        "year_stats":           year_stats,
        "parameters": {
            "version":            "V37a",
            "base":               "V33d + breadth filter (20d AND 50d MA, threshold 40%)",
            "universe":           "S&P500 + S&P400 + S&P600",
            "breadth_threshold":  f"{BREADTH_THRESHOLD:.0%}",
            "breadth_ma_short":   BREADTH_MA_SHORT,
            "breadth_ma_long":    BREADTH_MA_LONG,
            "min_consec_down":    MIN_CONSEC_DOWN,
            "max_positions":      MAX_POSITIONS,
            "tier1_6plus":        "2% target, 8d, partial at +1%",
            "tier2_5days":        "2% target, 8d, no partial",
            "tier3_4days":        "2% target, 8d, no partial",
            "entry_ranking":      "Composite RSI(2)/ATR_pct [V32e]",
            "velocity_crash_pause": f"SPY 5d <{VELOCITY_CRASH_5D_THRESHOLD*100:.0f}% → pause {VELOCITY_CRASH_PAUSE_DAYS}d",
            "vix_sizing":         f"<{VIX_LOW}VIX: {POSITION_SIZE_HIGH*100:.1f}%, base: {POSITION_SIZE*100:.1f}%",
            "commission":         f"${COMMISSION_RATE}/share, ${COMMISSION_MIN:.2f} min",
            "dd_scale":           "REMOVED — thresholds set unreachable [V22]",
        },
    }
    return metrics, eq_df_dt.reset_index()


# ─────────────────────────────────────────────────────────────────────────────
# 8. Save + print
# ─────────────────────────────────────────────────────────────────────────────
def save_outputs(trades_df, metrics, eq_df):
    trades_df.to_csv(OUTPUT_DIR / "trades.csv", index=False)
    eq_df.to_csv(OUTPUT_DIR / "equity_curve.csv", index=False)
    with open(OUTPUT_DIR / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, default=str)

    print("\n" + "=" * 70)
    print("  NAIVE MR BACKTEST — V37a (S&P 500 + 400 + 600)")
    print("=" * 70)

    for section, keys in [
        ("Core Performance", ["version","period_start","period_end","years_tested",
                              "total_trades","trades_per_year","cagr_pct",
                              "roi_per_year_pct","final_equity","total_return_pct"]),
        ("Risk-Adjusted Ratios", ["sharpe_ratio","sortino_ratio",
                                   "rolling_sharpe_avg_12m","rolling_sharpe_min_12m",
                                   "rolling_sortino_avg_12m","rolling_sortino_min_12m"]),
        ("Drawdown", ["max_drawdown_pct","max_drawdown_duration_trades"]),
        ("Trade Quality", ["win_rate_pct","profit_factor","avg_win_pct","avg_loss_pct",
                           "avg_days_held","median_days_held","time_stop_rate_pct"]),
        ("Return Distribution", ["annual_return_std_pct","monthly_return_skewness",
                                  "monthly_return_kurtosis"]),
    ]:
        print(f"\n  {section}:")
        for k in keys:
            if k in metrics:
                print(f"    {k.replace('_',' ').title():<36}: {metrics[k]}")

    if "tier_stats" in metrics:
        print(f"\n  Per-Tier Statistics:")
        for tk, tv in metrics["tier_stats"].items():
            print(f"    {tk}:")
            for sk, sv in tv.items():
                print(f"      {sk:<16}: {sv}")

    if "year_stats" in metrics:
        print(f"\n  Per-Year Breakdown:")
        for yr, yv in metrics["year_stats"].items():
            print(f"    {yr}: {yv['trades']:>5} trades  WR {yv['win_rate']:>5}%  "
                  f"P&L ${yv['pnl_usd']:>10,.0f}")

    if "parameters" in metrics:
        print(f"\n  Parameters:")
        for ek, ev in metrics["parameters"].items():
            print(f"    {ek:<40}: {ev}")

    for k in ["total_commission_usd","exit_reasons"]:
        if k in metrics:
            print(f"  {k.replace('_',' ').title():<36}: {metrics[k]}")

    print("=" * 70)
    print(f"\n  Saved to: {OUTPUT_DIR.resolve()}")


# ─────────────────────────────────────────────────────────────────────────────
__all__ = [
    "get_universe", "download_prices", "download_reference_data",
    "build_earnings_dates", "run_backtest", "compute_metrics", "save_outputs",
    "INITIAL_CAPITAL", "START_DATE", "END_DATE",
]

if __name__ == "__main__":
    universe   = get_universe()
    price_data = download_prices(universe)
    spy_df, vix_df, sector_data = download_reference_data()
    earnings_map = build_earnings_dates(list(price_data.keys()))
    trades_df    = run_backtest(price_data, spy_df, vix_df, sector_data, earnings_map)
    if trades_df.empty:
        print("[ERROR] No trades generated.")
    else:
        metrics, eq_df = compute_metrics(trades_df)
        save_outputs(trades_df, metrics, eq_df)
