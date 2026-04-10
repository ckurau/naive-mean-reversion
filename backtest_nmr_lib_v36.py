# backtest_nmr_lib_v36.py
# V36 -- three experiments on top of V34 baseline
#
# V36a -- Per-stock EWMA volatility filter
#   For each stock, compute a 20-day EWMA of daily return variance.
#   If current EWMA vol is in the top 20% of its own 252-day history,
#   skip the entry -- the stock is in a volatility spike where pullbacks
#   are more likely structural than mean-reverting.
#   Key difference from prior filters: per-stock, not market-level.
#   Does not fire broadly on crash-recovery days unless each specific
#   stock's own vol is elevated relative to its own history.
#
# V36c -- Inverse ETF mean reversion in bear regime
#   When SPY is below its 200d MA (existing bear filter already active),
#   apply the same RSI(2) + consecutive-days signal logic to inverse ETFs:
#   SH  (1x inverse S&P 500)
#   PSQ (1x inverse Nasdaq 100)
#   RWM (1x inverse Russell 2000)
#   Entry: inverse ETF has 4+ consecutive DOWN days (underlying up days)
#   AND RSI(2) < 20 (underlying overbought = inverse oversold).
#   Uses same 2% target / 8-day time stop structure.
#   Position size: 5% base (no VIX boost since we're in bear regime).
#   This converts dead cash periods into active return using the same edge.
#
# V36e -- Bond allocation in bear regime
#   When SPY is below its 200d MA, allocate idle capital to IEF
#   (7-10 year Treasury ETF) using a simple mean reversion signal:
#   IEF has 2+ consecutive down days AND RSI(2) < 40.
#   Exit when IEF closes above prior day high OR 5-day time stop.
#   Position size: 10% of portfolio per IEF entry, max 3 simultaneous.
#   Captures Treasury carry and flight-to-quality during equity bear markets.
#   Note: 2022 was bad for bonds too -- this may hurt that year specifically.
#
# V34 PERMANENT CHANGES CARRIED FORWARD:
#   [C3] GAP_DOWN_MAX = -0.010
#   [C5] Top 20% of signals get 1.2x size, hard cap 12%
#
# EXPERIMENTS:
#   V34_baseline  -- V34 unchanged (control)
#   V36a_ewma     -- V34 + per-stock EWMA vol filter
#   V36c_inverse  -- V34 + inverse ETF mean reversion in bear regime
#   V36e_bonds    -- V34 + bond allocation in bear regime

import io
import warnings
import datetime
import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
import requests
from tqdm import tqdm

warnings.filterwarnings("ignore")


# -----------------------------------------------------------------------------
# Experiment configuration
# -----------------------------------------------------------------------------
@dataclass
class ExperimentConfig:
    name: str = "V34_baseline"
    description: str = "V34 -- no changes"

    # V36a -- EWMA vol filter
    use_ewma_filter: bool = False
    ewma_lambda: float = 0.94          # RiskMetrics standard decay factor
    ewma_vol_lookback: int = 252       # days of history to rank current vol
    ewma_vol_percentile: float = 0.80  # skip if vol in top 20% of own history

    # V36c -- Inverse ETF entries in bear regime
    use_inverse_etf: bool = False
    inverse_etfs: tuple = ("SH", "PSQ", "RWM")
    inverse_consec_down: int = 4       # consecutive down days on inverse ETF
    inverse_rsi_threshold: float = 20.0
    inverse_profit_target: float = 0.020
    inverse_hold_days: int = 8
    inverse_position_size: float = 0.05

    # V36e -- Bond allocation in bear regime
    use_bonds: bool = False
    bond_etf: str = "IEF"
    bond_consec_down: int = 2
    bond_rsi_threshold: float = 40.0
    bond_profit_target: float = 0.010  # bonds move less, tighter target
    bond_hold_days: int = 5
    bond_position_size: float = 0.10
    bond_max_positions: int = 3


BASELINE = ExperimentConfig(
    name="V34_baseline",
    description="V34 -- no changes (control)",
)

V36A = ExperimentConfig(
    name="V36a_ewma",
    description="V36a -- per-stock EWMA vol filter (skip top 20% vol stocks)",
    use_ewma_filter=True,
)

V36C = ExperimentConfig(
    name="V36c_inverse",
    description="V36c -- inverse ETF mean reversion in bear regime (SH/PSQ/RWM)",
    use_inverse_etf=True,
)

V36E = ExperimentConfig(
    name="V36e_bonds",
    description="V36e -- bond allocation in bear regime (IEF mean reversion)",
    use_bonds=True,
)

EXPERIMENTS = [BASELINE, V36A, V36C, V36E]


# -----------------------------------------------------------------------------
# Config -- V34 permanent
# -----------------------------------------------------------------------------
START_DATE  = "2004-01-01"
END_DATE    = datetime.date.today().isoformat()

MIN_DOLLAR_VOLUME      = 5_000_000
MAX_POSITIONS          = 60
POSITION_SIZE          = 0.05
POSITION_SIZE_HIGH     = 0.09
POSITION_SIZE_EARNINGS = 0.03
MA_WINDOW              = 200
INITIAL_CAPITAL        = 100_000.0
RSI_PERIOD             = 2
RSI_THRESHOLD          = 20
ATR_PERIOD             = 14
ATR_MIN_PCT            = 0.01
VOL_MA_PERIOD          = 20
MIN_HOLD_BEFORE_EXIT   = 2
MIN_CONSEC_DOWN        = 4

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
TIER3_MIN_DOWN        = 4
TIER3_TARGET          = 0.020
TIER3_HOLD_DAYS       = 8
TIER3_PARTIAL         = False

DD_SCALE_MILD           = 9.99
DD_SCALE_SEVERE         = 9.99
POSITION_SIZE_DD_MILD   = 0.03
POSITION_SIZE_DD_SEVERE = 0.02

VELOCITY_CRASH_5D_THRESHOLD = -0.12
VELOCITY_CRASH_PAUSE_DAYS   = 5

EARNINGS_BLACKOUT     = 3
GAP_DOWN_MAX          = -0.010
GAP_UP_MAX            = 0.020
SECTOR_MA_WINDOW      = 20
MAX_SECTOR_POSITIONS  = 3
VIX_HIGH              = 999
VIX_LOW               = 25
VIX_SPIKE_PCT         = 0.30
VIX_SPIKE_PAUSE_DAYS  = 0
REENTRY_COOLDOWN_DAYS = 5
COMMISSION_RATE       = 0.005
COMMISSION_MIN        = 0.35
EARNINGS_MONTHS       = {1, 4, 7, 10}

TOP_SIGNAL_PCT        = 0.20
TOP_SIGNAL_MULTIPLIER = 1.20
TOP_SIGNAL_HARD_CAP   = 0.12
MIN_CANDIDATES_FOR_C5 = 5

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
                "partial_enabled": TIER2_PARTIAL, "partial_frac": 0.0,
                "partial_trigger": TIER2_TARGET}
    else:
        return {"tier": 3, "profit_target": TIER3_TARGET, "hold_days": TIER3_HOLD_DAYS,
                "partial_enabled": TIER3_PARTIAL, "partial_frac": 0.0,
                "partial_trigger": TIER3_TARGET}


# -----------------------------------------------------------------------------
# 1. Universe
# -----------------------------------------------------------------------------
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
                print(f"[Universe] {label}: WARNING - no valid ticker table found")
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


# -----------------------------------------------------------------------------
# 2. Downloads
# -----------------------------------------------------------------------------
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


def download_alternative_etfs(tickers: list) -> dict[str, pd.DataFrame]:
    """Download inverse ETFs and bond ETF for V36c and V36e."""
    result = {}
    for tkr in tickers:
        try:
            df = _dl_single(tkr)
            if not df.empty:
                result[tkr] = df
                print(f"[Download] {tkr}: {len(df)} rows")
        except Exception as e:
            print(f"[Download] {tkr} failed: {e}")
    return result


# -----------------------------------------------------------------------------
# 3. Earnings calendar
# -----------------------------------------------------------------------------
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


# -----------------------------------------------------------------------------
# 4. Signal generation
# -----------------------------------------------------------------------------
def _compute_ewma_vol(close: pd.Series, lam: float = 0.94) -> pd.Series:
    """EWMA variance using RiskMetrics approach."""
    ret = close.pct_change().fillna(0)
    sq  = ret ** 2
    ewma_var = sq.ewm(alpha=1 - lam, adjust=False).mean()
    return ewma_var.apply(np.sqrt)  # return as daily vol


def generate_signals(df: pd.DataFrame, cfg: ExperimentConfig) -> pd.DataFrame:
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

    # [V36a] EWMA volatility -- computed regardless, used only if flag on
    if cfg.use_ewma_filter:
        ewma_vol = _compute_ewma_vol(df["Close"], cfg.ewma_lambda)
        vol_rank = ewma_vol.rolling(cfg.ewma_vol_lookback).rank(pct=True)
        df["ewma_vol_ok"] = vol_rank <= cfg.ewma_vol_percentile
    else:
        df["ewma_vol_ok"] = True

    base_signal = (
        df["above_ma"]
        & (df["consec_down"] >= MIN_CONSEC_DOWN)
        & (df["rsi2"] < RSI_THRESHOLD)
        & (df["atr_pct"] > ATR_MIN_PCT)
        & df["vol_confirm"]
        & (df["dollar_vol_ma20"] >= MIN_DOLLAR_VOLUME)
        & df["ewma_vol_ok"]
    )
    df["signal"] = base_signal
    return df


def generate_inverse_signals(df: pd.DataFrame, cfg: ExperimentConfig) -> pd.DataFrame:
    """Generate mean reversion signals on inverse ETFs."""
    df = df.copy()
    df["down_day"] = (df["Close"] < df["Close"].shift(1)).astype(int)
    consec, count  = [], 0
    for d in df["down_day"]:
        count = count + 1 if d == 1 else 0
        consec.append(count)
    df["consec_down"] = consec
    df["rsi2"] = _compute_rsi(df["Close"], RSI_PERIOD)
    df["signal"] = (
        (df["consec_down"] >= cfg.inverse_consec_down)
        & (df["rsi2"] < cfg.inverse_rsi_threshold)
    )
    return df


def generate_bond_signals(df: pd.DataFrame, cfg: ExperimentConfig) -> pd.DataFrame:
    """Generate mean reversion signals on bond ETF."""
    df = df.copy()
    df["down_day"] = (df["Close"] < df["Close"].shift(1)).astype(int)
    consec, count  = [], 0
    for d in df["down_day"]:
        count = count + 1 if d == 1 else 0
        consec.append(count)
    df["consec_down"] = consec
    df["rsi2"] = _compute_rsi(df["Close"], RSI_PERIOD)
    df["prev_high"] = df["High"].shift(1)
    df["signal"] = (
        (df["consec_down"] >= cfg.bond_consec_down)
        & (df["rsi2"] < cfg.bond_rsi_threshold)
    )
    return df


# -----------------------------------------------------------------------------
# 5. Helpers
# -----------------------------------------------------------------------------
def calc_commission(shares: float, price: float) -> float:
    return max(shares * COMMISSION_RATE, COMMISSION_MIN)


def get_position_size(today, vix_df, drawdown_pct: float = 0.0,
                      multiplier: float = 1.0, hard_cap: float = 0.20) -> float:
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
    return min(base * multiplier, hard_cap)


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


# -----------------------------------------------------------------------------
# 6. Backtest simulation
# -----------------------------------------------------------------------------
def run_backtest(price_data, spy_df, vix_df, sector_data, earnings_map,
                 alt_etf_data: dict = None,
                 cfg: ExperimentConfig = BASELINE) -> pd.DataFrame:

    print(f"\n[Backtest] Running: {cfg.name}")
    print(f"[Backtest] {cfg.description}")

    spy_regime  = spy_df["spy_ok"].to_dict()
    all_dates: set = set()
    for df in price_data.values():
        all_dates.update(df.index)
    if alt_etf_data:
        for df in alt_etf_data.values():
            all_dates.update(df.index)
    trading_dates = sorted(all_dates)

    # Generate signals for main universe
    signals: dict[str, pd.DataFrame] = {}
    min_bars = MA_WINDOW + VOL_MA_PERIOD + ATR_PERIOD + MIN_CONSEC_DOWN + 5
    for tkr, df in tqdm(price_data.items(), desc=f"Signals [{cfg.name}]"):
        if len(df) > min_bars:
            signals[tkr] = generate_signals(df, cfg)

    # Generate signals for alt ETFs
    inv_signals: dict[str, pd.DataFrame] = {}
    bond_signals: dict[str, pd.DataFrame] = {}
    if alt_etf_data:
        if cfg.use_inverse_etf:
            for tkr in cfg.inverse_etfs:
                if tkr in alt_etf_data and len(alt_etf_data[tkr]) > 50:
                    inv_signals[tkr] = generate_inverse_signals(alt_etf_data[tkr], cfg)
        if cfg.use_bonds and cfg.bond_etf in alt_etf_data:
            bond_signals[cfg.bond_etf] = generate_bond_signals(
                alt_etf_data[cfg.bond_etf], cfg)

    portfolio_value  = INITIAL_CAPITAL
    portfolio_peak   = None
    current_drawdown = 0.0
    open_positions: dict[str, dict]     = {}  # main long positions
    open_inv_positions: dict[str, dict] = {}  # inverse ETF positions
    open_bond_positions: dict[str, dict]= {}  # bond positions
    trades: list[dict] = []
    cooldown_map: dict = {}
    last_vix_spike      = None
    last_velocity_crash = None

    # Diagnostics
    diag_ewma_blocked = 0
    diag_inv_entries  = 0
    diag_bond_entries = 0

    for today in tqdm(trading_dates, desc=f"Simulate [{cfg.name}]"):
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

        # ?? Exits: main positions ???????????????????????????????????????????
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
                    "portfolio_val": portfolio_value + pnl, "experiment": cfg.name,
                    "trade_type": "main",
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
                    "portfolio_val": portfolio_value + pnl, "experiment": cfg.name,
                    "trade_type": "main",
                })
                portfolio_value += pnl
                if time_stop:
                    cooldown_map[tkr] = today
                to_close.append(tkr)

        for tkr in to_close:
            del open_positions[tkr]

        # ?? Exits: inverse ETF positions ????????????????????????????????????
        inv_to_close = []
        for tkr, pos in open_inv_positions.items():
            if tkr not in inv_signals:
                continue
            tkr_df = inv_signals[tkr]
            if today not in tkr_df.index:
                continue
            exit_price  = float(tkr_df.loc[today, "Close"])
            entry_price = pos["entry_price"]
            days_held   = (pd.Timestamp(today) - pd.Timestamp(pos["entry_date"])).days
            pos_pct     = (exit_price - entry_price) / entry_price
            time_stop   = days_held >= cfg.inverse_hold_days
            profit_hit  = pos_pct >= cfg.inverse_profit_target
            if time_stop or profit_hit:
                commission = calc_commission(pos["shares"], exit_price)
                pnl        = ((exit_price - entry_price) * pos["shares"]
                              - commission - pos["entry_commission"])
                reason = "time_stop" if time_stop else "profit_target"
                trades.append({
                    "ticker": tkr, "entry_date": pos["entry_date"], "exit_date": today,
                    "entry_price": entry_price, "exit_price": exit_price,
                    "shares": pos["shares"],
                    "commission": round(commission + pos["entry_commission"], 4),
                    "pnl_usd": pnl, "pnl_pct": pos_pct * 100, "days_held": days_held,
                    "exit_reason": reason, "tier": 0,
                    "consec_down": pos.get("consec_down_at_entry", 0),
                    "portfolio_val": portfolio_value + pnl, "experiment": cfg.name,
                    "trade_type": "inverse",
                })
                portfolio_value += pnl
                inv_to_close.append(tkr)

        for tkr in inv_to_close:
            del open_inv_positions[tkr]

        # ?? Exits: bond positions ????????????????????????????????????????????
        bond_to_close = []
        for tkr, pos in open_bond_positions.items():
            if tkr not in bond_signals:
                continue
            tkr_df = bond_signals[tkr]
            if today not in tkr_df.index:
                continue
            row         = tkr_df.loc[today]
            exit_price  = float(row["Close"])
            entry_price = pos["entry_price"]
            days_held   = (pd.Timestamp(today) - pd.Timestamp(pos["entry_date"])).days
            pos_pct     = (exit_price - entry_price) / entry_price
            time_stop   = days_held >= cfg.bond_hold_days
            profit_hit  = pos_pct >= cfg.bond_profit_target
            # Also exit if price closes above prior day's high (mean reversion complete)
            prev_high   = float(row.get("prev_high", 0))
            mean_rev_exit = (exit_price > prev_high) if prev_high > 0 else False
            if time_stop or profit_hit or mean_rev_exit:
                commission = calc_commission(pos["shares"], exit_price)
                pnl        = ((exit_price - entry_price) * pos["shares"]
                              - commission - pos["entry_commission"])
                reason = "time_stop" if time_stop else ("mean_rev" if mean_rev_exit else "profit_target")
                trades.append({
                    "ticker": tkr, "entry_date": pos["entry_date"], "exit_date": today,
                    "entry_price": entry_price, "exit_price": exit_price,
                    "shares": pos["shares"],
                    "commission": round(commission + pos["entry_commission"], 4),
                    "pnl_usd": pnl, "pnl_pct": pos_pct * 100, "days_held": days_held,
                    "exit_reason": reason, "tier": 0,
                    "consec_down": pos.get("consec_down_at_entry", 0),
                    "portfolio_val": portfolio_value + pnl, "experiment": cfg.name,
                    "trade_type": "bond",
                })
                portfolio_value += pnl
                bond_to_close.append(tkr)

        for tkr in bond_to_close:
            del open_bond_positions[tkr]

        # ?? Main entries (long universe -- only when SPY above 200d) ????????
        if spy_ok and not paused and not velocity_paused:
            if len(open_positions) < MAX_POSITIONS:
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
                    # Track EWMA blocks for diagnostics
                    if cfg.use_ewma_filter and not bool(row.get("ewma_vol_ok", True)):
                        diag_ewma_blocked += 1
                    composite_score = rsi2 / atr_pct if atr_pct > 0 else rsi2 * 1000
                    candidates.append((composite_score, tkr, int(row["consec_down"]), rsi2))

                candidates.sort(key=lambda x: x[0])
                n_candidates = len(candidates)
                top_n = max(1, int(n_candidates * TOP_SIGNAL_PCT))

                for rank, (composite_score, tkr, consec_val, rsi_val) in enumerate(candidates):
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
                    tier_cfg = get_tier(consec_val)
                    c5_mult = TOP_SIGNAL_MULTIPLIER if (n_candidates >= MIN_CANDIDATES_FOR_C5
                                                         and rank < top_n) else 1.0
                    pos_size   = get_position_size(today, vix_df, current_drawdown,
                                                   multiplier=c5_mult,
                                                   hard_cap=TOP_SIGNAL_HARD_CAP)
                    shares     = (portfolio_value * pos_size) / entry_price
                    entry_comm = calc_commission(shares, entry_price)
                    open_positions[tkr] = {
                        "entry_date": tkr_df.index[today_idx + 1],
                        "entry_price": entry_price, "shares": shares,
                        "shares_remaining": shares, "rsi2_at_entry": rsi_val,
                        "consec_down_at_entry": consec_val,
                        "profit_target": tier_cfg["profit_target"],
                        "hold_days": tier_cfg["hold_days"],
                        "partial_enabled": tier_cfg["partial_enabled"],
                        "partial_frac": tier_cfg["partial_frac"],
                        "partial_trigger": tier_cfg["partial_trigger"],
                        "partial_done": False, "tier": tier_cfg["tier"],
                        "entry_commission": entry_comm,
                    }

        # ?? Inverse ETF entries (only when SPY BELOW 200d) ??????????????????
        if (cfg.use_inverse_etf and not spy_ok and not velocity_paused
                and inv_signals):
            for tkr, tkr_df in inv_signals.items():
                if tkr in open_inv_positions or today not in tkr_df.index:
                    continue
                row = tkr_df.loc[today]
                if not row["signal"]:
                    continue
                today_idx = tkr_df.index.get_loc(today)
                if today_idx + 1 >= len(tkr_df):
                    continue
                next_row    = tkr_df.iloc[today_idx + 1]
                entry_price = float(next_row["Open"])
                if entry_price <= 0:
                    continue
                shares     = (portfolio_value * cfg.inverse_position_size) / entry_price
                entry_comm = calc_commission(shares, entry_price)
                open_inv_positions[tkr] = {
                    "entry_date": tkr_df.index[today_idx + 1],
                    "entry_price": entry_price, "shares": shares,
                    "consec_down_at_entry": int(row["consec_down"]),
                    "entry_commission": entry_comm,
                }
                diag_inv_entries += 1

        # ?? Bond entries (only when SPY BELOW 200d) ??????????????????????????
        if (cfg.use_bonds and not spy_ok and not velocity_paused
                and bond_signals
                and len(open_bond_positions) < cfg.bond_max_positions):
            for tkr, tkr_df in bond_signals.items():
                if tkr in open_bond_positions or today not in tkr_df.index:
                    continue
                if len(open_bond_positions) >= cfg.bond_max_positions:
                    break
                row = tkr_df.loc[today]
                if not row["signal"]:
                    continue
                today_idx = tkr_df.index.get_loc(today)
                if today_idx + 1 >= len(tkr_df):
                    continue
                next_row    = tkr_df.iloc[today_idx + 1]
                entry_price = float(next_row["Open"])
                if entry_price <= 0:
                    continue
                shares     = (portfolio_value * cfg.bond_position_size) / entry_price
                entry_comm = calc_commission(shares, entry_price)
                open_bond_positions[tkr] = {
                    "entry_date": tkr_df.index[today_idx + 1],
                    "entry_price": entry_price, "shares": shares,
                    "consec_down_at_entry": int(row["consec_down"]),
                    "entry_commission": entry_comm,
                }
                diag_bond_entries += 1

    print(f"[Backtest] {cfg.name} complete -- {len(trades)} trades.")
    if cfg.use_ewma_filter:
        print(f"[Backtest] EWMA blocked entries (already filtered by signal): {diag_ewma_blocked}")
    if cfg.use_inverse_etf:
        print(f"[Backtest] Inverse ETF entries: {diag_inv_entries}")
    if cfg.use_bonds:
        print(f"[Backtest] Bond entries: {diag_bond_entries}")
    return pd.DataFrame(trades)


# -----------------------------------------------------------------------------
# 7. Metrics
# -----------------------------------------------------------------------------
def compute_metrics(trades_df: pd.DataFrame, cfg: ExperimentConfig = BASELINE) -> tuple:
    if trades_df.empty:
        return {"error": "No trades generated.", "experiment": cfg.name}, pd.DataFrame()

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

    main_trades = trades_df[trades_df.get("trade_type", "main") == "main"] \
        if "trade_type" in trades_df.columns else trades_df
    all_non_partial = trades_df[trades_df["exit_reason"] != "partial_exit"] \
        if "exit_reason" in trades_df.columns else trades_df

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

    eq_df_dt = eq_df.copy()
    eq_df_dt["date"] = pd.to_datetime(
        eq_df_dt["date"] if "date" in eq_df_dt.columns else eq_df_dt.index)
    eq_df_dt    = eq_df_dt.set_index("date")
    monthly_ret = eq_df_dt["equity"].resample("ME").last().ffill().pct_change().dropna()
    sharpe = (monthly_ret.mean() / monthly_ret.std() * np.sqrt(12)
              if monthly_ret.std() > 0 else 0)

    exit_counts = (trades_df["exit_reason"].value_counts().to_dict()
                   if "exit_reason" in trades_df.columns else {})
    time_stop_n  = exit_counts.get("time_stop", 0)
    time_stop_rt = round(time_stop_n / len(all_non_partial) * 100, 1) \
        if len(all_non_partial) else 0

    trades_df["exit_year"] = pd.to_datetime(trades_df["exit_date"]).dt.year
    year_stats = {}
    for yr in sorted(trades_df["exit_year"].unique()):
        y_df  = trades_df[trades_df["exit_year"] == yr]
        y_win = y_df[y_df["pnl_usd"] > 0]
        year_stats[str(yr)] = {
            "trades":   len(y_df),
            "win_rate": round((y_df["pnl_usd"] > 0).mean() * 100, 1),
            "pnl_usd":  round(y_df["pnl_usd"].sum(), 2),
        }

    # Alt trade breakdown
    alt_pnl = 0.0
    alt_trades = 0
    if "trade_type" in trades_df.columns:
        alt_df = trades_df[trades_df["trade_type"] != "main"]
        alt_pnl    = round(alt_df["pnl_usd"].sum(), 2)
        alt_trades = len(alt_df)

    metrics = {
        "experiment":         cfg.name,
        "description":        cfg.description,
        "total_trades":       len(trades_df),
        "trades_per_year":    round(len(trades_df) / years, 1),
        "cagr_pct":           round(cagr * 100, 2),
        "final_equity":       round(equity, 2),
        "win_rate_pct":       round(win_rate, 2),
        "profit_factor":      round(pf, 2),
        "avg_win_pct":        round(avg_win,  2),
        "avg_loss_pct":       round(avg_loss, 2),
        "max_drawdown_pct":   round(max_dd, 2),
        "sharpe_ratio":       round(sharpe, 2),
        "time_stop_rate_pct": time_stop_rt,
        "alt_trades":         alt_trades,
        "alt_pnl_usd":        alt_pnl,
        "exit_reasons":       {k: int(v) for k, v in exit_counts.items()},
        "year_stats":         year_stats,
    }
    return metrics, eq_df_dt.reset_index()


# -----------------------------------------------------------------------------
# 8. Save
# -----------------------------------------------------------------------------
def save_outputs(trades_df, metrics, eq_df, cfg: ExperimentConfig = BASELINE):
    exp_dir = OUTPUT_DIR / cfg.name
    exp_dir.mkdir(exist_ok=True)
    trades_df.to_csv(exp_dir / "trades.csv", index=False)
    eq_df.to_csv(exp_dir / "equity_curve.csv", index=False)
    with open(exp_dir / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    print(f"  Saved: {exp_dir.resolve()}")


__all__ = [
    "ExperimentConfig", "BASELINE", "V36A", "V36C", "V36E", "EXPERIMENTS",
    "get_universe", "download_prices", "download_reference_data",
    "download_alternative_etfs", "build_earnings_dates",
    "run_backtest", "compute_metrics", "save_outputs",
    "INITIAL_CAPITAL", "START_DATE", "END_DATE",
]
