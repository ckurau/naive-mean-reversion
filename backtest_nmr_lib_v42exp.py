# backtest_nmr_lib_v42exp.py
# V42 Experimental Suite — Second batch of 4 ideas vs V35 baseline
#
# Research sources:
#   - RenTec: day-of-week seasonality (Tuesday reversal bias, Monday/Friday correlations)
#   - NBER "Reversals and Returns to Liquidity Provision" (Novy-Marx & Medhat 2022):
#       industry-relative reversal is far more profitable than raw reversal
#   - Journal of Empirical Finance 2024: 52-week-high distance amplifies reversal strength
#   - Academic: low-turnover stocks have longer-lived, larger reversals
#   - AHL/Winton: signal confidence weighting by historical hit-rate per setup type
#
# Variants tested:
#   BASELINE  — V35 unchanged (control — should reproduce ~18.81% CAGR)
#   EXP_E     — Day-of-week bias: Tuesday entries get 1.15x size (RenTec seasonality)
#   EXP_F     — 52-week-high distance filter: prefer stocks far from 52wk high
#               (academic: larger reversals when price is far from 52wk anchor)
#   EXP_G     — Low-turnover amplification: stocks with below-median 20d turnover
#               get longer hold window (research: reversals are longer-lived)
#   EXP_H     — Industry-relative RSI: rank candidates by RSI(2) relative to their
#               sector ETF's RSI(2), not raw RSI(2) (NBER industry-adjusted reversal)
#
# Architecture: identical to V41exp — shared data download, one signal pass,
# five independent simulations. Results to results/v42exp/comparison.json.

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

# ---------------------------------------------------------------------------
# Shared config — V35 baseline (do not change)
# ---------------------------------------------------------------------------
START_DATE          = "2004-01-01"
END_DATE            = datetime.date.today().isoformat()
MIN_DOLLAR_VOLUME   = 5_000_000
MAX_POSITIONS       = 60
POSITION_SIZE       = 0.05
POSITION_SIZE_HIGH  = 0.09
POSITION_SIZE_EARNINGS = 0.03
MA_WINDOW           = 200
INITIAL_CAPITAL     = 100_000.0
RSI_PERIOD          = 2
RSI_THRESHOLD       = 20
ATR_PERIOD          = 14
ATR_MIN_PCT         = 0.01
VOL_MA_PERIOD       = 20
MIN_HOLD_BEFORE_EXIT = 2

TIER1_MIN_DOWN      = 6;  TIER1_TARGET = 0.020; TIER1_HOLD_DAYS = 8
TIER1_PARTIAL       = True; TIER1_PARTIAL_FRAC = 0.50; TIER1_PARTIAL_TRIGGER = 0.010
TIER2_MIN_DOWN      = 5;  TIER2_TARGET = 0.020; TIER2_HOLD_DAYS = 8
TIER3_MIN_DOWN      = 4;  TIER3_TARGET = 0.020; TIER3_HOLD_DAYS = 8
MIN_CONSEC_DOWN     = TIER3_MIN_DOWN

DD_SCALE_MILD       = 9.99
DD_SCALE_SEVERE     = 9.99
POSITION_SIZE_DD_MILD   = 0.03
POSITION_SIZE_DD_SEVERE = 0.02

VELOCITY_CRASH_5D_THRESHOLD = -0.12
VELOCITY_CRASH_PAUSE_DAYS   = 5
EARNINGS_BLACKOUT   = 3
GAP_DOWN_MAX        = -0.010
GAP_UP_MAX          = 0.020
SECTOR_MA_WINDOW    = 20
MAX_SECTOR_POSITIONS = 3

VIX_LOW             = 25
VIX_SPIKE_PCT       = 0.30
VIX_SPIKE_PAUSE_DAYS = 0
REENTRY_COOLDOWN_DAYS = 5
COMMISSION_RATE     = 0.005
COMMISSION_MIN      = 0.35
EARNINGS_MONTHS     = {1, 4, 7, 10}
TOP_SIGNAL_PCT      = 0.20
TOP_SIGNAL_MULTIPLIER = 1.30
TOP_SIGNAL_HARD_CAP = 0.12
MIN_CANDIDATES_FOR_C5 = 5

OUTPUT_DIR = Path("results/v42exp")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# EXP_E: Day-of-week sizing (RenTec seasonality research)
# Tuesday shows stronger reversal bias historically; scale size on it
# ---------------------------------------------------------------------------
EXP_E_DOW_MULTIPLIERS = {
    0: 1.00,  # Monday
    1: 1.15,  # Tuesday — reversal bias (RenTec documented)
    2: 1.00,  # Wednesday
    3: 0.95,  # Thursday — slightly weaker setup historically
    4: 0.90,  # Friday — commodity/fund positioning effects (traders close)
}

# ---------------------------------------------------------------------------
# EXP_F: 52-week-high distance (academic: reversals amplified far from 52wk anchor)
# Stocks whose price is in the bottom 30% of their 52-week range get a bonus
# ---------------------------------------------------------------------------
EXP_F_52WK_WINDOW       = 252
EXP_F_LOW_RANGE_THRESHOLD = 0.35  # price-to-52wk-high must be BELOW this to qualify
EXP_F_SIZE_BONUS        = 1.20    # 1.20x position size for qualifying stocks

# ---------------------------------------------------------------------------
# EXP_G: Low-turnover hold extension (NBER: low-turnover reversals are longer-lived)
# Stocks with below-median 20d average turnover ratio get +3 extra hold days
# ---------------------------------------------------------------------------
EXP_G_TURNOVER_WINDOW   = 20     # days for average daily turnover (vol/shares outstanding proxy)
EXP_G_EXTRA_HOLD_DAYS   = 3      # extra days added to hold_days at entry
# Turnover proxy: Volume / dollar_vol_ma20 * Close (we use vol/vol_ma20 as ratio)
EXP_G_LOW_TURNOVER_THRESHOLD = 0.80  # vol_ratio < this = "low turnover"

# ---------------------------------------------------------------------------
# EXP_H: Industry-relative RSI ranking (NBER industry-adjusted reversal)
# Rank by (stock RSI2 - sector_RSI2) rather than raw RSI2 / ATR
# More negative = stock is MORE oversold relative to its sector
# ---------------------------------------------------------------------------
EXP_H_SECTOR_RSI_WEIGHT = 0.50  # blend: score = raw_score × (1 - w) + industry_adj × w

# ---------------------------------------------------------------------------
# Sector map (identical to V35)
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Tier config helper
# ---------------------------------------------------------------------------
def get_tier(consec_down: int) -> dict:
    if consec_down >= TIER1_MIN_DOWN:
        return {"tier": 1, "profit_target": TIER1_TARGET, "hold_days": TIER1_HOLD_DAYS,
                "partial_enabled": TIER1_PARTIAL, "partial_frac": TIER1_PARTIAL_FRAC,
                "partial_trigger": TIER1_PARTIAL_TRIGGER}
    elif consec_down >= TIER2_MIN_DOWN:
        return {"tier": 2, "profit_target": TIER2_TARGET, "hold_days": TIER2_HOLD_DAYS,
                "partial_enabled": False, "partial_frac": 0.0, "partial_trigger": TIER2_TARGET}
    else:
        return {"tier": 3, "profit_target": TIER3_TARGET, "hold_days": TIER3_HOLD_DAYS,
                "partial_enabled": False, "partial_frac": 0.0, "partial_trigger": TIER3_TARGET}


# ---------------------------------------------------------------------------
# 1. Universe (identical to V35 / V41)
# ---------------------------------------------------------------------------
def _fetch_wiki(url: str) -> list:
    headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
               "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return pd.read_html(io.StringIO(resp.text), header=0)

def _extract_tickers(table: pd.DataFrame) -> list[str]:
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
            for i, table in enumerate(tables):
                syms = _extract_tickers(table)
                if len(syms) >= 100:
                    tickers.update([s.replace(".", "-") for s in syms])
                    print(f"[Universe] {label}: {len(syms)} symbols (table {i})")
                    break
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


# ---------------------------------------------------------------------------
# 2. Downloads
# ---------------------------------------------------------------------------
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
    """Returns (spy_df, vix_df, sector_data, sector_rsi_df)."""
    spy = _dl_single("SPY")
    close = spy["Close"].squeeze()
    spy["spy_ma200"] = close.rolling(200).mean()
    spy["spy_ok"]    = (close > spy["spy_ma200"].squeeze()).values
    spy["spy_5d_ret"] = close.pct_change(5)
    print(f"[Download] SPY: {len(spy)} rows")

    vix = _dl_single("^VIX")
    vix_close = vix["Close"].squeeze()
    vix["vix_5d_ago"] = vix_close.shift(5)
    vix["vix_spike"]  = (vix_close / vix["vix_5d_ago"].replace(0, np.nan) - 1) >= VIX_SPIKE_PCT
    print(f"[Download] VIX: {len(vix)} rows")

    etf_list = list(SECTOR_ETFS.keys())
    sector_data: dict[str, pd.DataFrame] = {}
    sector_rsi: dict[str, pd.Series] = {}

    raw = yf.download(etf_list, start=START_DATE, end=END_DATE,
                      auto_adjust=True, progress=False, threads=True)
    if not raw.empty:
        for etf in etf_list:
            try:
                df = (raw.xs(etf, axis=1, level=1).dropna(how="all")
                      if isinstance(raw.columns, pd.MultiIndex) else raw.copy())
                cs = df["Close"].squeeze()
                df = df.copy()
                df["ma"]   = cs.rolling(SECTOR_MA_WINDOW).mean()
                df["ok"]   = (cs > df["ma"].squeeze()).values
                df["rsi2"] = _compute_rsi(cs, RSI_PERIOD)  # EXP_H
                sector_data[etf] = df
                sector_rsi[etf]  = df["rsi2"]
            except Exception:
                pass
    print(f"[Download] Sector ETFs: {len(sector_data)}")
    return spy, vix, sector_data, sector_rsi


# ---------------------------------------------------------------------------
# 3. Earnings calendar
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# 4. Signal generation — includes extras for EXP_F and EXP_G
# ---------------------------------------------------------------------------
def generate_signals(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["ma200"]   = df["Close"].rolling(MA_WINDOW).mean()
    df["above_ma"] = df["Close"] > df["ma200"]
    df["down_day"] = (df["Close"] < df["Close"].shift(1)).astype(int)

    consec, count = [], 0
    for d in df["down_day"]:
        count = count + 1 if d == 1 else 0
        consec.append(count)
    df["consec_down"] = consec

    df["rsi2"] = _compute_rsi(df["Close"], RSI_PERIOD)

    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - df["Close"].shift(1)).abs(),
        (df["Low"]  - df["Close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["atr"]     = tr.rolling(ATR_PERIOD).mean()
    df["atr_pct"] = df["atr"] / df["Close"]

    df["vol_ma20"]      = df["Volume"].rolling(VOL_MA_PERIOD).mean()
    df["vol_confirm"]   = df["Volume"] > df["vol_ma20"]
    df["vol_ratio"]     = df["Volume"] / df["vol_ma20"].replace(0, np.nan)  # EXP_G
    df["dollar_vol_ma20"] = (df["Close"] * df["Volume"]).rolling(VOL_MA_PERIOD).mean()

    # EXP_F: price-to-52-week-high ratio
    df["high_52wk"]    = df["High"].rolling(EXP_F_52WK_WINDOW, min_periods=60).max()
    df["price_to_52h"] = df["Close"] / df["high_52wk"].replace(0, np.nan)

    df["signal"] = (
        df["above_ma"]
        & (df["consec_down"] >= MIN_CONSEC_DOWN)
        & (df["rsi2"] < RSI_THRESHOLD)
        & (df["atr_pct"] > ATR_MIN_PCT)
        & df["vol_confirm"]
        & (df["dollar_vol_ma20"] >= MIN_DOLLAR_VOLUME)
    )
    return df


# ---------------------------------------------------------------------------
# 5. Shared helpers
# ---------------------------------------------------------------------------
def calc_commission(shares: float, price: float) -> float:
    return max(shares * COMMISSION_RATE, COMMISSION_MIN)

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

def get_position_size_base(today, vix_df, drawdown_pct: float = 0.0) -> float:
    month = pd.Timestamp(today).month
    earnings_month = month in EARNINGS_MONTHS
    base = POSITION_SIZE
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

def get_sector_rsi(tkr: str, date, sector_rsi: dict) -> float:
    """EXP_H: returns the sector ETF's RSI(2) on the given date."""
    etf = TICKER_TO_SECTOR.get(tkr)
    if etf is None or etf not in sector_rsi:
        return 50.0  # neutral if unknown
    rsi_series = sector_rsi[etf]
    if date not in rsi_series.index:
        return 50.0
    val = rsi_series.loc[date]
    return float(val) if not np.isnan(val) else 50.0


# ---------------------------------------------------------------------------
# 6. Core backtest engine
# ---------------------------------------------------------------------------
def run_backtest(
    price_data, spy_df, vix_df, sector_data, earnings_map, sector_rsi,
    variant: str = "BASELINE",
) -> pd.DataFrame:
    print(f"\n[Backtest] Running variant={variant} ...")

    spy_regime  = spy_df["spy_ok"].to_dict()
    all_dates: set = set()
    for df in price_data.values():
        all_dates.update(df.index)
    trading_dates = sorted(all_dates)

    signals: dict[str, pd.DataFrame] = {}
    min_bars = MA_WINDOW + VOL_MA_PERIOD + ATR_PERIOD + MIN_CONSEC_DOWN + 5
    for tkr, df in price_data.items():
        if len(df) > min_bars:
            signals[tkr] = generate_signals(df)

    portfolio_value  = INITIAL_CAPITAL
    portfolio_peak   = None
    current_drawdown = 0.0
    open_positions: dict[str, dict] = {}
    trades: list[dict] = []
    cooldown_map: dict  = {}
    last_vix_spike      = None
    last_velocity_crash = None

    for today in tqdm(trading_dates, desc=f"Sim {variant}"):
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

        # ---- Exits --------------------------------------------------------
        to_close = []
        for tkr, pos in open_positions.items():
            if tkr not in signals:
                continue
            tkr_df = signals[tkr]
            if today not in tkr_df.index:
                continue
            row        = tkr_df.loc[today]
            exit_price = float(row["Close"])
            entry_price = pos["entry_price"]
            days_held  = (pd.Timestamp(today) - pd.Timestamp(pos["entry_date"])).days
            pos_pct    = (exit_price - entry_price) / entry_price
            shares_rem = pos["shares_remaining"]
            early      = days_held < MIN_HOLD_BEFORE_EXIT

            time_stop  = days_held >= pos["hold_days"]
            profit_hit = (not early) and pos_pct >= pos["profit_target"]

            if (pos["partial_enabled"] and not pos["partial_done"]
                    and not early and pos_pct >= pos["partial_trigger"]):
                partial_shares = shares_rem * pos["partial_frac"]
                commission = calc_commission(partial_shares, exit_price)
                pnl = (exit_price - entry_price) * partial_shares - commission
                trades.append({
                    "ticker": tkr, "entry_date": pos["entry_date"], "exit_date": today,
                    "entry_price": entry_price, "exit_price": exit_price,
                    "shares": partial_shares, "commission": round(commission, 4),
                    "pnl_usd": pnl, "pnl_pct": pos_pct * 100, "days_held": days_held,
                    "exit_reason": "partial_exit", "tier": pos["tier"],
                    "consec_down": pos["consec_down_at_entry"],
                    "portfolio_val": portfolio_value + pnl, "variant": variant,
                })
                portfolio_value += pnl
                pos["shares_remaining"] -= partial_shares
                pos["partial_done"] = True
                pos["profit_target"] = pos["profit_target"] * 2
                continue

            full_exit = (
                time_stop
                or (not pos["partial_enabled"] and profit_hit)
                or (pos["partial_enabled"] and pos["partial_done"] and profit_hit)
            )
            if full_exit:
                commission = calc_commission(shares_rem, exit_price)
                pnl = ((exit_price - entry_price) * shares_rem
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
                    "portfolio_val": portfolio_value + pnl, "variant": variant,
                })
                portfolio_value += pnl
                if time_stop:
                    cooldown_map[tkr] = today
                to_close.append(tkr)

        for tkr in to_close:
            del open_positions[tkr]

        if not spy_ok or paused or velocity_paused:
            continue
        if len(open_positions) >= MAX_POSITIONS:
            continue

        # ---- Entries ------------------------------------------------------
        today_dow = pd.Timestamp(today).dayofweek  # EXP_E

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

            # EXP_H: blend in industry-relative RSI score
            if variant == "EXP_H":
                sector_rsi_val = get_sector_rsi(tkr, today, sector_rsi)
                # Relative RSI: how much more oversold is this stock vs its sector?
                # More negative = better reversal candidate
                relative_rsi = rsi2 - sector_rsi_val
                # Convert to a score in the same direction as composite_score (lower = better)
                # raw composite: lower is better. relative_rsi: more negative = better.
                industry_adj_score = relative_rsi / atr_pct if atr_pct > 0 else relative_rsi * 1000
                composite_score = (composite_score * (1 - EXP_H_SECTOR_RSI_WEIGHT)
                                   + industry_adj_score * EXP_H_SECTOR_RSI_WEIGHT)

            price_to_52h = float(row.get("price_to_52h", 1.0))
            vol_ratio    = float(row.get("vol_ratio", 1.0))
            candidates.append((composite_score, tkr, int(row["consec_down"]),
                                rsi2, atr_pct, price_to_52h, vol_ratio))

        candidates.sort(key=lambda x: x[0])
        n_candidates = len(candidates)
        top_n = max(1, int(n_candidates * TOP_SIGNAL_PCT))

        for rank, (composite_score, tkr, consec_val, rsi_val, atr_pct_val,
                   price_to_52h, vol_ratio) in enumerate(candidates):
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

            # EXP_G: extend hold window for low-turnover stocks
            if variant == "EXP_G":
                if vol_ratio < EXP_G_LOW_TURNOVER_THRESHOLD:
                    tier_cfg["hold_days"] = tier_cfg["hold_days"] + EXP_G_EXTRA_HOLD_DAYS

            # ---- Position sizing -------------------------------------------
            base_size = get_position_size_base(today, vix_df, current_drawdown)

            size_multiplier = 1.0
            if n_candidates >= MIN_CANDIDATES_FOR_C5 and rank < top_n:
                size_multiplier = TOP_SIGNAL_MULTIPLIER  # 1.30

            # EXP_E: day-of-week multiplier on top
            if variant == "EXP_E":
                size_multiplier *= EXP_E_DOW_MULTIPLIERS.get(today_dow, 1.0)

            # EXP_F: 52-week-high distance bonus
            if variant == "EXP_F":
                if price_to_52h < EXP_F_LOW_RANGE_THRESHOLD:
                    size_multiplier *= EXP_F_SIZE_BONUS

            pos_size = min(base_size * size_multiplier, TOP_SIGNAL_HARD_CAP)
            shares   = (portfolio_value * pos_size) / entry_price
            entry_comm = calc_commission(shares, entry_price)

            open_positions[tkr] = {
                "entry_date": tkr_df.index[today_idx + 1],
                "entry_price": entry_price,
                "shares": shares,
                "shares_remaining": shares,
                "rsi2_at_entry": rsi_val,
                "consec_down_at_entry": consec_val,
                "profit_target": tier_cfg["profit_target"],
                "hold_days": tier_cfg["hold_days"],
                "partial_enabled": tier_cfg["partial_enabled"],
                "partial_frac": tier_cfg["partial_frac"],
                "partial_trigger": tier_cfg["partial_trigger"],
                "partial_done": False,
                "tier": tier_cfg["tier"],
                "entry_commission": entry_comm,
            }

    print(f"[Backtest] {variant}: {len(trades)} trades.")
    return pd.DataFrame(trades)


# ---------------------------------------------------------------------------
# 7. Metrics (identical to V41)
# ---------------------------------------------------------------------------
def compute_metrics(trades_df: pd.DataFrame, variant: str) -> dict:
    if trades_df.empty:
        return {"variant": variant, "error": "No trades generated."}

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
    max_dd = eq_df["dd"].min()

    gp = winners["pnl_usd"].sum()
    gl = abs(losers["pnl_usd"].sum())
    pf = gp / gl if gl > 0 else float("inf")

    eq_dt = eq_df.copy()
    eq_dt["date"] = pd.to_datetime(eq_dt["date"])
    eq_dt = eq_dt.set_index("date")
    monthly_ret = eq_dt["equity"].resample("ME").last().ffill().pct_change().dropna()
    sharpe  = (monthly_ret.mean() / monthly_ret.std() * np.sqrt(12)
               if monthly_ret.std() > 0 else 0)
    downside = monthly_ret[monthly_ret < 0]
    downside_std = downside.std() if len(downside) > 1 else 0
    sortino = (monthly_ret.mean() / downside_std * np.sqrt(12)
               if downside_std > 0 else 0)

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

    return {
        "variant": variant,
        "total_trades":     len(trades_df),
        "trades_per_year":  round(len(trades_df) / years, 1),
        "cagr_pct":         round(cagr * 100, 2),
        "final_equity":     round(equity, 2),
        "total_return_pct": round((equity / INITIAL_CAPITAL - 1) * 100, 2),
        "sharpe_ratio":     round(sharpe, 2),
        "sortino_ratio":    round(sortino, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "win_rate_pct":     round(win_rate, 2),
        "profit_factor":    round(pf, 2),
        "avg_win_pct":      round(avg_win, 2),
        "avg_loss_pct":     round(avg_loss, 2),
        "avg_days_held":    round(trades_df["days_held"].mean(), 2),
        "total_commission_usd": round(trades_df["commission"].sum(), 2),
        "exit_reasons":     (trades_df["exit_reason"].value_counts().to_dict()
                             if "exit_reason" in trades_df.columns else {}),
        "year_stats":       year_stats,
    }


# ---------------------------------------------------------------------------
# 8. Save + print
# ---------------------------------------------------------------------------
VARIANT_DESCRIPTIONS = {
    "BASELINE": "V35 unchanged — control",
    "EXP_E":    "Day-of-week sizing: Tue ×1.15, Thu ×0.95, Fri ×0.90 (RenTec seasonality)",
    "EXP_F":    "52wk-high distance: price-to-52wkH < 35% gets ×1.20 size (anchoring bias)",
    "EXP_G":    "Low-turnover hold extension: vol_ratio < 0.80 gets +3 hold days (NBER)",
    "EXP_H":    "Industry-relative RSI ranking: RSI(2) vs sector ETF RSI(2) (NBER IRR)",
}

def save_outputs(all_metrics: list[dict], all_trades: dict[str, pd.DataFrame]):
    for variant, df in all_trades.items():
        if not df.empty:
            df.to_csv(OUTPUT_DIR / f"trades_{variant.lower()}.csv", index=False)

    result = {
        "run_date": datetime.date.today().isoformat(),
        "baseline_version": "V35",
        "batch": "V42 — second idea batch",
        "variants": all_metrics,
    }
    with open(OUTPUT_DIR / "comparison.json", "w") as f:
        json.dump(result, f, indent=2, default=str)

    KEY_METRICS = [
        ("cagr_pct",          "CAGR %"),
        ("final_equity",      "Final Equity $"),
        ("max_drawdown_pct",  "Max DD %"),
        ("sharpe_ratio",      "Sharpe"),
        ("win_rate_pct",      "Win Rate %"),
        ("profit_factor",     "Profit Factor"),
        ("trades_per_year",   "Trades/yr"),
        ("avg_days_held",     "Avg Days Held"),
    ]

    col_w = 18
    variants_order = ["BASELINE", "EXP_E", "EXP_F", "EXP_G", "EXP_H"]
    metrics_by_variant = {m["variant"]: m for m in all_metrics}

    print("\n" + "=" * 120)
    print("  V42 EXPERIMENTAL SUITE — SECOND BATCH — COMPARISON RESULTS")
    print("=" * 120)
    for v in variants_order:
        if v in metrics_by_variant:
            print(f"  {v:<10} {VARIANT_DESCRIPTIONS.get(v,'')}")
    print()

    header = f"  {'Metric':<28}" + "".join(f"{v:>{col_w}}" for v in variants_order
                                            if v in metrics_by_variant)
    print(header)
    print("  " + "-" * (28 + col_w * sum(1 for v in variants_order if v in metrics_by_variant)))

    baseline = metrics_by_variant.get("BASELINE", {})
    for key, label in KEY_METRICS:
        row = f"  {label:<28}"
        for v in variants_order:
            m   = metrics_by_variant.get(v, {})
            val = m.get(key)
            if val is None:
                row += f"{'N/A':>{col_w}}"
                continue
            if v != "BASELINE" and key in baseline and isinstance(val, (int, float)):
                delta = val - baseline[key]
                sign  = "+" if delta >= 0 else ""
                cell  = f"{val:.2f} ({sign}{delta:.2f})"
            else:
                cell = f"{val:.2f}" if isinstance(val, float) else str(val)
            row += f"{cell:>{col_w}}"
        print(row)

    print("=" * 120)
    print(f"\n  Results saved to: {OUTPUT_DIR.resolve()}")
    print("  Files: comparison.json + trades_<variant>.csv\n")

    print("\n  PER-YEAR P&L BY VARIANT")
    print("  " + "-" * 100)
    all_years = sorted({yr for m in all_metrics for yr in m.get("year_stats", {}).keys()})
    header2 = f"  {'Year':<8}" + "".join(
        f"{v:>{col_w}}" for v in variants_order if v in metrics_by_variant
    )
    print(header2)
    print("  " + "-" * (8 + col_w * sum(1 for v in variants_order if v in metrics_by_variant)))
    for yr in all_years:
        row = f"  {yr:<8}"
        for v in variants_order:
            m  = metrics_by_variant.get(v, {})
            ys = m.get("year_stats", {}).get(yr, {})
            pnl = ys.get("pnl_usd")
            wr  = ys.get("win_rate")
            if pnl is None:
                row += f"{'—':>{col_w}}"
            else:
                cell = f"${pnl:,.0f} ({wr}%)"
                row += f"{cell:>{col_w}}"
        print(row)
    print("=" * 120 + "\n")


__all__ = [
    "get_universe", "download_prices", "download_reference_data",
    "build_earnings_dates", "run_backtest", "compute_metrics", "save_outputs",
    "INITIAL_CAPITAL", "START_DATE", "END_DATE", "VARIANT_DESCRIPTIONS",
]
