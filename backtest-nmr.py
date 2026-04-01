"""
Enhanced Naive Mean Reversion (MR) Backtest — V15
==================================================
Return to V7's core structure. Keep only the four changes proven to help
across V10–V14. Strip everything that didn't move avg win or CAGR.

── V10–V14 CONCLUSIONS ───────────────────────────────────────────────────────
  After 5 versions of targeted iteration, the data proves:
  - Avg win is stuck at 2.83-2.85% in every post-V7 version
  - V7's 3.34% avg win came from Tier 3 (4-day) fast-bounce setups
  - Removing Tier 3 (V10+) is the root cause of the CAGR collapse
  - Hold window extension (V14) barely moved avg win (+0.02%)
  - SPY 50d guard (V14) destroyed 2009 recovery trades (-$22k swing)
  - ROC filter (V10-V13) selected slower-bounce setups, hurting avg win
  - Regime-aware sizing IS working (sweet spot, co-oversold, bull cap)
  - Tier 2 bull regime block (V13) DID improve bull WR 56%→63%
  - Crash position limit (V12) is sound risk management, keep it

── V15 CHANGES FROM V14 ──────────────────────────────────────────────────────
  [V15-1] Restore Tier 3 (4-day setups): MIN_CONSEC_DOWN = 4
      Tier 3 is the missing ingredient. V7 ran 4-day setups at 1% target,
      4-day window. Restored here with 1% target, 8-day window (the V7
      mechanism that accidentally gave everything 8 days and drove 69.72%
      WR). 4-day setups are fast bouncers — they need the short window.

  [V15-2] Hold windows back to 8 days (all tiers)
      Extended windows (V14: 11-12d) hurt 2018/2021 by holding through
      crashes. Avg win barely improved (+0.02%). Back to 8 days for all.
      The 8-day window was V7's key insight — keep it.

  [V15-3] Remove SPY 50d SMA entry guard
      Destroyed 2009 recovery trades. The 200d guard is sufficient.
      50d is too reactive — blocks entries at exactly the wrong time
      (post-crash recovery phase when mean reversion edge is highest).

  [V15-4] Tier 3 target: 1% (matching V7 mechanism)
      4-day setups are lower quality. 1% target maximises their win rate.
      Partial exit at +0.5% (50% of position, proportional to Tier 1's
      1% partial on 2% target ratio).

── KEPT FROM V10–V14 (proven to help) ────────────────────────────────────────
  [KEEP] ROC filter disabled (V14-3) — don't re-add it
  [KEEP] Tier 2 bull regime block (V13-1) — improved bull WR 56%→63%
  [KEEP] Bull regime thresholds 18%/25%, 3% cap (V11 FIX2)
  [KEEP] Regime-aware sizing: sweet spot 7.5%, co-oversold 6% (V10)
  [KEEP] Crash position limit: SPY 20d < -8% → max 5 positions (V12)
  [KEEP] SPY regime break 4d hold shortcut on 200d break only
  [KEEP] RSI exit at 85 (V11 FIX3)
  [KEEP] Tier 2: no partial exit, 1.5% target, 8d, blocked in bull (V12/V13)
  [KEEP] Tier 1: 2% target, 8d, partial at +1%

── RESULTS HISTORY ───────────────────────────────────────────────────────────
  V7  (best): CAGR 9.05% | WR 69.72% | PF 1.14 | Sharpe 0.74 | 872/yr
  V10:        CAGR 1.05% | WR 63.11% | PF 1.07 | Sharpe 0.20 | 283/yr
  V14:        CAGR 1.65% | WR 63.74% | PF 1.10 | Sharpe 0.30 | 273/yr
  V15 target: CAGR >6%   | WR >67%   | PF >1.12 | Sharpe >0.60 | 600+/yr
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
START_DATE             = "2004-01-01"
END_DATE               = datetime.date.today().isoformat()
MIN_DOLLAR_VOLUME      = 5_000_000
MAX_POSITIONS          = 30
POSITION_SIZE          = 0.05
POSITION_SIZE_HIGH     = 0.075          # VIX < 15
POSITION_SIZE_LOW      = 0.025          # VIX > 25
POSITION_SIZE_EARNINGS = 0.03
MA_WINDOW              = 200
INITIAL_CAPITAL        = 100_000.0
RSI_PERIOD             = 2
RSI_THRESHOLD          = 20
RSI_EXIT_OVERBOUGHT    = 85             # [FIX 3] was 75
ATR_PERIOD             = 14
ATR_MIN_PCT            = 0.01
VOL_MA_PERIOD          = 20
MIN_HOLD_BEFORE_EXIT   = 2

# ── Tier system ───────────────────────────────────────────────────────────────
TIER1_MIN_DOWN         = 6
TIER1_TARGET           = 0.020
TIER1_HOLD_DAYS        = 8              # [V15-2] restored to 8 (12d hurt 2018/2021)
TIER1_PARTIAL          = True
TIER1_PARTIAL_FRAC     = 0.50
TIER1_PARTIAL_TRIGGER  = 0.010         # 50% out at +1%

TIER2_MIN_DOWN         = 5
TIER2_TARGET           = 0.015         # 1.5% target
TIER2_HOLD_DAYS        = 8              # [V15-2] restored to 8
TIER2_PARTIAL          = False         # no partial
TIER2_PARTIAL_FRAC     = 0.0
TIER2_PARTIAL_TRIGGER  = 0.0

# [V15-1] Tier 3 restored — 4-day setups, fast-bounce, 1% target
TIER3_MIN_DOWN         = 4
TIER3_TARGET           = 0.010         # [V15-4] 1% — achievable for fast-bounce 4-day setups
TIER3_HOLD_DAYS        = 8
TIER3_PARTIAL          = True          # 50% partial at +0.5% (same ratio as Tier1: trigger=50% of target)
TIER3_PARTIAL_FRAC     = 0.50
TIER3_PARTIAL_TRIGGER  = 0.005         # +0.5% trigger

MIN_CONSEC_DOWN        = TIER3_MIN_DOWN  # [V15-1] back to 4 (was 5 since V10)

# ── [FIX 1] Rate-of-change filter ────────────────────────────────────────────
ROC_MIN_DROP           = 0.0            # [V14-3] disabled (was -2.5%) — restores fast-bounce shallow setups

# ── Distance from 50-day SMA (ranking only) ───────────────────────────────────
MA50_WINDOW            = 50
DIST_MA50_HARD_FILTER  = False

# ── [FIX 2] Bull regime filter ────────────────────────────────────────────────
BULL_REGIME_12M_RETURN   = 0.25        # was 0.20
BULL_REGIME_ABOVE_MA200  = 0.18        # was 0.12
POSITION_SIZE_BULL_CAP   = 0.03        # was 0.02

# ── Aggressive sizing (Connor TPS sweet-spot) ─────────────────────────────────
SWEET_SPOT_SIZE          = 0.075
SWEET_SPOT_BELOW_ATH_MIN = 0.03

# ── SPY co-oversold boost (Larry Connors) ─────────────────────────────────────
SPY_CO_OVERSOLD_RSI      = 15
POSITION_SIZE_CO_OVERSOLD = 0.06

# ── [FIX C] Severe crash position limit ──────────────────────────────────────
# If SPY 20-day return < threshold, cap open positions at CRASH_MAX_POSITIONS.
# Does NOT halt trading — keeps compounding for recovery, just at tiny exposure.
# Addresses 2011 (-$21k) and 2022 (38% WR) where 30-position exposure in a
# crash amplified losses dramatically.
CRASH_SPY_20D_THRESHOLD = -0.08        # SPY down 8%+ over 20 days = crash mode
CRASH_MAX_POSITIONS     = 5            # max open positions during crash

# ── SPY regime break: shorten hold for open positions (from V11) ──────────────
SPY_BREAK_HOLD_DAYS      = 4

# ── Filters ───────────────────────────────────────────────────────────────────
EARNINGS_BLACKOUT      = 3
GAP_DOWN_MAX           = -0.015
GAP_UP_MAX             = 0.020
SECTOR_MA_WINDOW       = 20
MAX_SECTOR_POSITIONS   = 3
VIX_HIGH               = 25
VIX_LOW                = 15
VIX_SPIKE_PCT          = 0.30
VIX_SPIKE_PAUSE_DAYS   = 2
REENTRY_COOLDOWN_DAYS  = 5
COMMISSION_RATE        = 0.005
COMMISSION_MIN         = 1.00
EARNINGS_MONTHS        = {1, 4, 7, 10}

# ── Drawdown scaling ──────────────────────────────────────────────────────────
DD_SCALE_MILD           = 0.08
DD_SCALE_SEVERE         = 0.15
POSITION_SIZE_DD_MILD   = 0.03
POSITION_SIZE_DD_SEVERE = 0.02

OUTPUT_DIR = Path("results")
OUTPUT_DIR.mkdir(exist_ok=True)

SECTOR_ETFS = {
    "XLK":  ["AAPL","MSFT","NVDA","AVGO","CSCO","ORCL","IBM","QCOM","TXN","INTC",
              "AMD","NOW","INTU","AMAT","ADI","MU","KLAC","LRCX","MCHP","CDNS"],
    "XLV":  ["UNH","JNJ","LLY","ABBV","MRK","TMO","ABT","DHR","BMY","AMGN",
              "PFE","ISRG","MDT","GILD","VRTX","BSX","SYK","REGN","ZTS","CI"],
    "XLF":  ["JPM","BAC","WFC","GS","MS","BLK","AXP","SPGI","V","MA",
              "USB","PNC","TFC","COF","CB","ICE","CME","MCO","AON","TRV"],
    "XLY":  ["AMZN","TSLA","HD","MCD","NKE","LOW","SBUX","TGT","CMG","BKNG",
              "TJX","DHI","GM","F","ORLY","LEN","EBAY","ETSY","YUM","DRI"],
    "XLP":  ["PG","KO","PEP","COST","WMT","PM","MO","MDLZ","CL","KMB",
              "EL","KR","STZ","GIS","HRL","SJM","CAG","K","CPB","CHD"],
    "XLE":  ["XOM","CVX","COP","SLB","EOG","MPC","PSX","VLO","HAL","BKR",
              "FANG","DVN","HES","OXY","APA","MRO","CTRA","EQT","NOV","FTI"],
    "XLI":  ["GE","HON","UPS","BA","CAT","RTX","DE","LMT","UNP","MMM",
              "ETN","EMR","NOC","GD","PH","ROK","IR","ITW","TT","CARR"],
    "XLB":  ["LIN","APD","SHW","ECL","NEM","FCX","NUE","DOW","DD","PPG",
              "ALB","CF","MOS","CE","IFF","RPM","FMC","SON","SEE","AMCR"],
    "XLU":  ["NEE","DUK","SO","D","AEP","EXC","SRE","PEG","ED","XEL",
              "ES","FE","ETR","PPL","CMS","NI","ATO","LNT","EVRG","PNW"],
    "XLRE": ["PLD","AMT","CCI","EQIX","PSA","O","WELL","DLR","EQR","AVB",
              "SPG","WY","ARE","MAA","UDR","CPT","ESS","AIV","IRM","VTR"],
    "XLC":  ["META","GOOGL","GOOG","NFLX","DIS","CMCSA","T","VZ","TMUS","CHTR",
              "ATVI","EA","WBD","PARA","FOXA","FOX","NWS","NWSA","OMC","IPG"],
}

TICKER_TO_SECTOR: dict[str, str] = {}
for _etf, _members in SECTOR_ETFS.items():
    for _t in _members:
        TICKER_TO_SECTOR[_t] = _etf


def get_tier(consec_down: int) -> dict:
    if consec_down >= TIER1_MIN_DOWN:
        return {
            "tier":            1,
            "profit_target":   TIER1_TARGET,
            "hold_days":       TIER1_HOLD_DAYS,
            "partial_enabled": TIER1_PARTIAL,
            "partial_frac":    TIER1_PARTIAL_FRAC,
            "partial_trigger": TIER1_PARTIAL_TRIGGER,
        }
    elif consec_down >= TIER2_MIN_DOWN:
        return {
            "tier":            2,
            "profit_target":   TIER2_TARGET,
            "hold_days":       TIER2_HOLD_DAYS,
            "partial_enabled": TIER2_PARTIAL,
            "partial_frac":    TIER2_PARTIAL_FRAC,
            "partial_trigger": TIER2_PARTIAL_TRIGGER,
        }
    else:  # 4 days - Tier 3 [V15-1]
        return {
            "tier":            3,
            "profit_target":   TIER3_TARGET,
            "hold_days":       TIER3_HOLD_DAYS,
            "partial_enabled": TIER3_PARTIAL,
            "partial_frac":    TIER3_PARTIAL_FRAC,
            "partial_trigger": TIER3_PARTIAL_TRIGGER,
        }


# ─────────────────────────────────────────────────────────────────────────────
# 1. Universe
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
            if "500" in label and len(tables) > 1:
                for col in tables[1].columns:
                    cs = tables[1][col].dropna().astype(str)
                    if cs.str.match(r"^[A-Z]{1,5}(-[A-Z])?$").mean() > 0.3:
                        tickers.update([s.replace(".", "-") for s in cs])
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


def download_reference_data() -> tuple:
    spy   = _dl_single("SPY")
    close = spy["Close"].squeeze()

    spy["spy_ma200"]        = close.rolling(200).mean()
    spy["spy_ok"]           = (close > spy["spy_ma200"].squeeze()).values
    spy["spy_ma50"]         = close.rolling(50).mean()                   # [V14-2] fast bear guard
    spy["spy_ok_50"]        = (close > spy["spy_ma50"].squeeze()).values  # [V14-2] True when above 50d SMA
    spy["spy_12m_ret"]      = close.pct_change(252)
    spy["spy_20d_ret"]      = close.pct_change(20)                   # [FIX C] crash detection
    spy["spy_pct_above_ma"] = (close / spy["spy_ma200"].squeeze()) - 1
    spy["spy_ma20w"]        = close.rolling(100).mean()
    spy["spy_52w_high"]     = close.rolling(252).max()
    spy["spy_below_ath"]    = (spy["spy_52w_high"].squeeze() - close) / spy["spy_52w_high"].squeeze()
    spy["spy_sweet_spot"]   = (
        (close > spy["spy_ma20w"].squeeze()) &
        (spy["spy_below_ath"].squeeze() >= SWEET_SPOT_BELOW_ATH_MIN)
    )
    spy["spy_rsi2"]         = _compute_rsi(close, 2)
    bull_a = spy["spy_12m_ret"].squeeze()      > BULL_REGIME_12M_RETURN
    bull_b = spy["spy_pct_above_ma"].squeeze() > BULL_REGIME_ABOVE_MA200
    spy["spy_bull_regime"]  = (bull_a | bull_b)
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
    df["ma50"]      = df["Close"].rolling(MA50_WINDOW).mean()
    df["above_ma"]  = df["Close"] > df["ma200"]
    df["dist_ma50"] = (df["Close"] - df["ma50"]) / df["ma50"]

    df["down_day"] = (df["Close"] < df["Close"].shift(1)).astype(int)
    consec, count = [], 0
    for d in df["down_day"]:
        count = count + 1 if d == 1 else 0
        consec.append(count)
    df["consec_down"] = consec

    closes     = df["Close"].values
    consec_arr = df["consec_down"].values
    streak_start = np.full(len(df), np.nan)
    for i in range(len(df)):
        n = int(consec_arr[i])
        if n > 0 and i >= n:
            streak_start[i] = closes[i - n]
    df["streak_start_close"] = streak_start
    df["roc_from_streak"]    = (df["Close"] - df["streak_start_close"]) / df["streak_start_close"]

    df["rsi2"] = _compute_rsi(df["Close"], RSI_PERIOD)

    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - df["Close"].shift(1)).abs(),
        (df["Low"]  - df["Close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["atr"]     = tr.rolling(ATR_PERIOD).mean()
    df["atr_pct"] = df["atr"] / df["Close"]

    df["vol_ma20"]        = df["Volume"].rolling(VOL_MA_PERIOD).mean()
    df["vol_confirm"]     = df["Volume"] > df["vol_ma20"]
    df["dollar_vol_ma20"] = (df["Close"] * df["Volume"]).rolling(VOL_MA_PERIOD).mean()

    roc_ok = (df["roc_from_streak"] <= ROC_MIN_DROP) if ROC_MIN_DROP < 0 else True

    df["signal"] = (
        df["above_ma"] &
        (df["consec_down"] >= MIN_CONSEC_DOWN) &
        (df["rsi2"] < RSI_THRESHOLD) &
        (df["atr_pct"] > ATR_MIN_PCT) &
        df["vol_confirm"] &
        (df["dollar_vol_ma20"] >= MIN_DOLLAR_VOLUME) &
        roc_ok
    )
    return df


# ─────────────────────────────────────────────────────────────────────────────
# 5. Helpers
# ─────────────────────────────────────────────────────────────────────────────
def calc_commission(shares: float, price: float) -> float:
    return max(shares * COMMISSION_RATE, COMMISSION_MIN)


def get_position_size(today, vix_df, spy_df, drawdown_pct: float = 0.0) -> float:
    month          = pd.Timestamp(today).month
    earnings_month = month in EARNINGS_MONTHS
    base           = POSITION_SIZE

    try:
        vc = vix_df["Close"].squeeze()
        if today in vc.index:
            v = float(vc.loc[today])
            if v > VIX_HIGH:
                base = POSITION_SIZE_LOW
            elif v < VIX_LOW:
                base = POSITION_SIZE_HIGH
    except Exception:
        pass

    try:
        if today in spy_df.index and bool(spy_df.loc[today, "spy_sweet_spot"]):
            base = SWEET_SPOT_SIZE
    except Exception:
        pass

    try:
        if today in spy_df.index:
            if float(spy_df.loc[today, "spy_rsi2"]) < SPY_CO_OVERSOLD_RSI:
                base = max(base, POSITION_SIZE_CO_OVERSOLD)
    except Exception:
        pass

    try:
        if today in spy_df.index and bool(spy_df.loc[today, "spy_bull_regime"]):
            base = min(base, POSITION_SIZE_BULL_CAP)
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
    print("\n[Backtest] Running V15 simulation ...")
    spy_regime    = spy_df["spy_ok"].to_dict()
    spy_regime_50 = spy_df["spy_ok_50"].to_dict()   # [V14-2] 50d SMA fast bear guard

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
    open_positions:  dict[str, dict] = {}
    trades:          list[dict]      = []
    cooldown_map:    dict            = {}
    last_vix_spike   = None

    for today in tqdm(trading_dates, desc="Simulating"):
        spy_ok    = spy_regime.get(today, True)
        spy_ok_50 = spy_regime_50.get(today, True)   # [V14-2] False when SPY below 50d SMA
        paused, last_vix_spike = check_vix_spike(today, vix_df, last_vix_spike)

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

        # ── Exits ──────────────────────────────────────────────────────────
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
            rsi_now     = float(row["rsi2"]) if not np.isnan(float(row["rsi2"])) else 50.0

            # [V14-2] Shorten hold window if SPY broke below 200d or 50d SMA
            effective_hold = pos["hold_days"]
            if not spy_ok:  # [V15-3] 50d guard removed from hold shortcut too
                effective_hold = min(effective_hold, SPY_BREAK_HOLD_DAYS)

            early      = days_held < MIN_HOLD_BEFORE_EXIT
            time_stop  = days_held >= effective_hold
            profit_hit = (not early) and pos_pct >= pos["profit_target"]
            rsi_exit   = (not early) and (rsi_now > RSI_EXIT_OVERBOUGHT)  # [FIX 3]

            # Partial exit — Tier 1 and Tier 2 [NEW 7]
            if (pos["partial_enabled"] and
                    not pos["partial_done"] and
                    not early and
                    pos_pct >= pos["partial_trigger"]):
                partial_shares = shares_rem * pos["partial_frac"]
                commission     = calc_commission(partial_shares, exit_price)
                pnl            = (exit_price - entry_price) * partial_shares - commission
                trades.append({
                    "ticker":        tkr,
                    "entry_date":    pos["entry_date"],
                    "exit_date":     today,
                    "entry_price":   entry_price,
                    "exit_price":    exit_price,
                    "shares":        partial_shares,
                    "commission":    round(commission, 4),
                    "pnl_usd":       pnl,
                    "pnl_pct":       pos_pct * 100,
                    "days_held":     days_held,
                    "exit_reason":   "partial_exit",
                    "tier":          pos["tier"],
                    "consec_down":   pos["consec_down_at_entry"],
                    "portfolio_val": portfolio_value + pnl,
                    "regime":        pos.get("regime", "neutral"),
                })
                portfolio_value         += pnl
                pos["shares_remaining"] -= partial_shares
                pos["partial_done"]      = True
                # Tier 1: double target after partial. Tier 2: target stays at 1.5%.
                if pos["tier"] == 1:
                    pos["profit_target"] = pos["profit_target"] * 2
                continue

            # Full exit
            full_exit = (
                time_stop or
                rsi_exit or
                (not pos["partial_enabled"] and profit_hit) or
                (pos["partial_enabled"] and pos["partial_done"] and profit_hit)
            )
            if full_exit:
                commission = calc_commission(shares_rem, exit_price)
                pnl        = ((exit_price - entry_price) * shares_rem
                              - commission - pos["entry_commission"])
                reason = ("time_stop" if time_stop else
                          "rsi_overbought" if rsi_exit else
                          "profit_target")
                trades.append({
                    "ticker":        tkr,
                    "entry_date":    pos["entry_date"],
                    "exit_date":     today,
                    "entry_price":   entry_price,
                    "exit_price":    exit_price,
                    "shares":        shares_rem,
                    "commission":    round(commission + pos["entry_commission"], 4),
                    "pnl_usd":       pnl,
                    "pnl_pct":       pos_pct * 100,
                    "days_held":     days_held,
                    "exit_reason":   reason,
                    "tier":          pos["tier"],
                    "consec_down":   pos["consec_down_at_entry"],
                    "portfolio_val": portfolio_value + pnl,
                    "regime":        pos.get("regime", "neutral"),
                })
                portfolio_value += pnl
                if time_stop:
                    cooldown_map[tkr] = today
                to_close.append(tkr)

        for tkr in to_close:
            del open_positions[tkr]

        if not spy_ok or paused:   # [V15-3] 50d guard removed — hurts post-crash recovery
            continue

        # [FIX C] Crash mode: cap max positions when SPY is down hard over 20 days
        effective_max_positions = MAX_POSITIONS
        try:
            if today in spy_df.index:
                spy_20d = float(spy_df.loc[today, "spy_20d_ret"])
                if not np.isnan(spy_20d) and spy_20d < CRASH_SPY_20D_THRESHOLD:
                    effective_max_positions = CRASH_MAX_POSITIONS
        except Exception:
            pass

        if len(open_positions) >= effective_max_positions:
            continue

        spy_co_oversold = False
        try:
            if today in spy_df.index:
                spy_co_oversold = float(spy_df.loc[today, "spy_rsi2"]) < SPY_CO_OVERSOLD_RSI
        except Exception:
            pass

        # ── Entries ────────────────────────────────────────────────────────
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
            rsi_val    = float(row["rsi2"])
            consec_val = int(row["consec_down"])
            dist_ma50  = float(row["dist_ma50"]) if not np.isnan(float(row["dist_ma50"])) else 0.0

            # [V13-1 + V15] Block Tier 2 and Tier 3 entries in bull regime
            # Only Tier 1 (6+ days, 68%+ WR) has edge in bull regime
            tier_would_be = 1 if consec_val >= TIER1_MIN_DOWN else (2 if consec_val >= TIER2_MIN_DOWN else 3)
            try:
                in_bull = bool(spy_df.loc[today, "spy_bull_regime"]) if today in spy_df.index else False
            except Exception:
                in_bull = False
            if tier_would_be in (2, 3) and in_bull:
                continue

            priority   = 0 if spy_co_oversold else 1
            candidates.append((priority, rsi_val, -dist_ma50, tkr, consec_val))

        candidates.sort(key=lambda x: (x[0], x[1], x[2]))

        for priority, rsi_val, neg_dist, tkr, consec_val in candidates:
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
            pos_size   = get_position_size(today, vix_df, spy_df, current_drawdown)
            shares     = (portfolio_value * pos_size) / entry_price
            entry_comm = calc_commission(shares, entry_price)

            try:
                bull   = bool(spy_df.loc[today, "spy_bull_regime"]) if today in spy_df.index else False
                sweet  = bool(spy_df.loc[today, "spy_sweet_spot"])  if today in spy_df.index else False
                regime = ("bull" if bull else
                          "sweet_spot" if sweet else
                          "co_oversold" if spy_co_oversold else
                          "neutral")
            except Exception:
                regime = "neutral"

            open_positions[tkr] = {
                "entry_date":           tkr_df.index[today_idx + 1],
                "entry_price":          entry_price,
                "shares":               shares,
                "shares_remaining":     shares,
                "rsi2_at_entry":        rsi_val,
                "consec_down_at_entry": consec_val,
                "profit_target":        tier_cfg["profit_target"],
                "hold_days":            tier_cfg["hold_days"],
                "partial_enabled":      tier_cfg["partial_enabled"],
                "partial_frac":         tier_cfg["partial_frac"],
                "partial_trigger":      tier_cfg["partial_trigger"],
                "partial_done":         False,
                "tier":                 tier_cfg["tier"],
                "entry_commission":     entry_comm,
                "regime":               regime,
            }

    print(f"[Backtest] Complete — {len(trades)} trades executed.")
    return pd.DataFrame(trades)


# ─────────────────────────────────────────────────────────────────────────────
# 7. Metrics + Optimization Report
# ─────────────────────────────────────────────────────────────────────────────
def compute_metrics(trades_df: pd.DataFrame) -> tuple:
    if trades_df.empty:
        return {"error": "No trades generated."}, pd.DataFrame()

    trades_df = trades_df.sort_values("exit_date").reset_index(drop=True)

    equity       = INITIAL_CAPITAL
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

    gp = winners["pnl_usd"].sum()
    gl = abs(losers["pnl_usd"].sum())
    pf = gp / gl if gl > 0 else float("inf")

    eq_df["date"] = pd.to_datetime(eq_df["date"])
    eq_df.set_index("date", inplace=True)
    monthly_ret   = eq_df["equity"].resample("ME").last().ffill().pct_change().dropna()
    sharpe        = (monthly_ret.mean() / monthly_ret.std() * np.sqrt(12)
                     if monthly_ret.std() > 0 else 0)

    total_comm   = trades_df["commission"].sum() if "commission" in trades_df else 0
    exit_counts  = (trades_df["exit_reason"].value_counts().to_dict()
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

    regime_stats = {}
    if "regime" in trades_df.columns:
        for reg in trades_df["regime"].unique():
            r_df  = trades_df[trades_df["regime"] == reg]
            r_win = r_df[r_df["pnl_usd"] > 0]
            r_los = r_df[r_df["pnl_usd"] <= 0]
            regime_stats[reg] = {
                "trades":        len(r_df),
                "win_rate":      round((r_df["pnl_usd"] > 0).mean() * 100, 1),
                "avg_win":       round(r_win["pnl_pct"].mean(), 2) if len(r_win) else 0,
                "avg_loss":      round(r_los["pnl_pct"].mean(), 2) if len(r_los) else 0,
                "pct_of_trades": round(len(r_df) / len(trades_df) * 100, 1),
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
        "version":              "V15",
        "period_start":         start_dt.date().isoformat(),
        "period_end":           end_dt.date().isoformat(),
        "years_tested":         round(years, 2),
        "total_trades":         len(trades_df),
        "trades_per_year":      round(len(trades_df) / years, 1),
        "win_rate_pct":         round(win_rate, 2),
        "cagr_pct":             round(cagr * 100, 2),
        "roi_per_year_pct":     round((equity - INITIAL_CAPITAL) / INITIAL_CAPITAL / years * 100, 2),
        "avg_days_held":        round(trades_df["days_held"].mean(), 2),
        "avg_win_pct":          round(avg_win, 2),
        "avg_loss_pct":         round(avg_loss, 2),
        "profit_factor":        round(pf, 2),
        "max_drawdown_pct":     round(max_dd, 2),
        "sharpe_ratio":         round(sharpe, 2),
        "time_stop_rate_pct":   time_stop_rt,
        "exit_reasons":         {k: int(v) for k, v in exit_counts.items()},
        "tier_stats":           tier_stats,
        "regime_stats":         regime_stats,
        "year_stats":           year_stats,
        "total_commission_usd": round(total_comm, 2),
        "initial_capital":      INITIAL_CAPITAL,
        "final_equity":         round(equity, 2),
        "total_return_pct":     round((equity / INITIAL_CAPITAL - 1) * 100, 2),
        "parameters": {
            "version":                   "V15",
            "min_consec_down":           MIN_CONSEC_DOWN,
            "tier1_6plus_days":          f"2% target, {TIER1_HOLD_DAYS}d, partial at +1% — all regimes [V15-2]",
            "tier2_5_days":              f"1.5% target, {TIER2_HOLD_DAYS}d, no partial — blocked in bull regime",
            "tier3_4_days":              f"1.0% target, {TIER3_HOLD_DAYS}d, partial at +0.5% — RESTORED [V15-1], blocked in bull regime",
            "roc_filter":                "DISABLED — fast-bounce shallow setups restored [V14-3]",
            "spy_50d_guard":             "REMOVED [V15-3] — was blocking post-crash recovery trades",
            "spy_200d_guard":            "No entries when SPY below 200-day SMA (existing)",
            "bull_regime_12m":           f">{BULL_REGIME_12M_RETURN*100:.0f}% SPY 12m → {POSITION_SIZE_BULL_CAP*100:.0f}% cap (Tier1 only)",
            "bull_regime_above_ma200":   f">{BULL_REGIME_ABOVE_MA200*100:.0f}% above 200d → {POSITION_SIZE_BULL_CAP*100:.0f}% cap (Tier1 only)",
            "tier2_3_bull_block":        "Tier 2 and 3 entries blocked in bull regime — Tier 1 only there",
            "rsi_exit_overbought":       f"{RSI_EXIT_OVERBOUGHT}",
            "spy_break_hold_days":       f"{SPY_BREAK_HOLD_DAYS}d max hold when SPY below 200d SMA",
            "crash_limit":               f"SPY 20d ret <{CRASH_SPY_20D_THRESHOLD*100:.0f}% → max {CRASH_MAX_POSITIONS} positions",
            "sweet_spot_size":           f"{SWEET_SPOT_SIZE*100:.1f}% (SPY above 20wk + below ATH {SWEET_SPOT_BELOW_ATH_MIN*100:.0f}%+)",
            "spy_co_oversold_rsi":       f"SPY RSI(2)<{SPY_CO_OVERSOLD_RSI} → {POSITION_SIZE_CO_OVERSOLD*100:.0f}% + priority",
            "dist_ma50":                 "secondary ranking (not hard filter)",
            "max_positions":             MAX_POSITIONS,
            "crash_max_positions":       CRASH_MAX_POSITIONS,
            "min_hold_before_exit":      MIN_HOLD_BEFORE_EXIT,
            "rsi2_entry_threshold":      RSI_THRESHOLD,
            "dollar_vol_min":            MIN_DOLLAR_VOLUME,
            "gap_filters":               f"down>{GAP_DOWN_MAX*100}%, up<{GAP_UP_MAX*100}%",
            "sector_ma_window":          SECTOR_MA_WINDOW,
            "max_sector_positions":      MAX_SECTOR_POSITIONS,
            "reentry_cooldown_days":     REENTRY_COOLDOWN_DAYS,
            "vix_sizing":                f"<{VIX_LOW}VIX:{POSITION_SIZE_HIGH*100}%, >{VIX_HIGH}VIX:{POSITION_SIZE_LOW*100}%",
            "earnings_month_cap":        f"{POSITION_SIZE_EARNINGS*100}%",
            "universe":                  "S&P500 + S&P400",
            "commission":                f"${COMMISSION_RATE}/share, ${COMMISSION_MIN} min",
            "dd_scale_mild_pct":         DD_SCALE_MILD,
            "dd_size_mild":              POSITION_SIZE_DD_MILD,
            "dd_scale_severe_pct":       DD_SCALE_SEVERE,
            "dd_size_severe":            POSITION_SIZE_DD_SEVERE,
        },
    }
    return metrics, eq_df.reset_index()


# ─────────────────────────────────────────────────────────────────────────────
# 8. Save + print
# ─────────────────────────────────────────────────────────────────────────────
def save_outputs(trades_df, metrics, eq_df):
    trades_df.to_csv(OUTPUT_DIR / "trades.csv", index=False)
    eq_df.to_csv(OUTPUT_DIR / "equity_curve.csv", index=False)
    with open(OUTPUT_DIR / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, default=str)

    opt_report = {
        "run_date":         datetime.date.today().isoformat(),
        "version":          "V15",
        "summary":          {k: metrics[k] for k in [
            "cagr_pct","win_rate_pct","profit_factor","sharpe_ratio",
            "max_drawdown_pct","avg_win_pct","avg_loss_pct",
            "trades_per_year","final_equity","time_stop_rate_pct",
        ]},
        "regime_breakdown": metrics.get("regime_stats", {}),
        "year_breakdown":   metrics.get("year_stats", {}),
        "tier_breakdown":   metrics.get("tier_stats", {}),
        "exit_breakdown":   metrics.get("exit_reasons", {}),
        "parameters":       metrics["parameters"],
    }
    with open(OUTPUT_DIR / "optimization_report.json", "w") as f:
        json.dump(opt_report, f, indent=2, default=str)

    print("\n" + "=" * 70)
    print("  NAIVE MR BACKTEST — V15")
    print("=" * 70)
    for k, v in metrics.items():
        if k == "tier_stats":
            print(f"\n  Per-Tier Statistics:")
            for tk, tv in v.items():
                print(f"    {tk}:")
                for sk, sv in tv.items():
                    print(f"      {sk:<16}: {sv}")
        elif k == "regime_stats":
            print(f"\n  Regime Breakdown:")
            for rk, rv in v.items():
                print(f"    {rk}:")
                for sk, sv in rv.items():
                    print(f"      {sk:<16}: {sv}")
        elif k == "year_stats":
            print(f"\n  Per-Year Breakdown:")
            for yr, yv in v.items():
                wr  = yv.get("win_rate", "?")
                pnl = yv.get("pnl_usd", "?")
                cnt = yv.get("trades", "?")
                print(f"    {yr}: {cnt:>5} trades  WR {wr:>5}%  P&L ${pnl:>10,.0f}")
        elif k in ("parameters", "exit_reasons"):
            label = "Parameters" if "param" in k else "Exit Reason Breakdown"
            print(f"\n  {label}:")
            for ek, ev in v.items():
                print(f"    {ek:<44}: {ev}")
        else:
            print(f"  {k.replace('_',' ').title():<36}: {v}")
    print("=" * 70)
    print(f"\n  Saved to: {OUTPUT_DIR.resolve()}")
    print(f"  Optimization report: {(OUTPUT_DIR / 'optimization_report.json').resolve()}")


# ─────────────────────────────────────────────────────────────────────────────
# 9. Entry point
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
