"""
Enhanced Naive Mean Reversion (MR) Backtest — V10
==================================================
Changes from V7 Final + Drawdown Scaling:

  [1] MINIMUM 5 CONSECUTIVE DOWN DAYS — Tier 3 (4-day) eliminated.
      Only Tier 1 (6+ days) and Tier 2 (5 days) remain.
      Rationale: Tier 3 had ~61% win rate, barely profitable after commissions.

  [2] BULL REGIME FILTER — Two-condition check. When either fires, position
      size is capped at 2% (strategy never stops trading — learned from
      circuit breaker failure).
        Condition A: SPY trailing 12-month return > 20%
        Condition B: SPY more than 12% above its 200-day SMA
      Both conditions computed daily with no lookahead.

  [3] AGGRESSIVE SIZING TRIGGER (Connor TPS / Sweet-Spot Rule) — When weekly
      SPY is above its 20-week SMA AND below its 52-week high by > 3%,
      base position size scales to 7.5% regardless of VIX level. This is
      the mean reversion sweet spot: healthy trend, not extended.

  [4] SPY CO-OVERSOLD BOOST (Larry Connors TPS) — When SPY RSI(2) < 15
      on signal day, entries get 6% base size and are prioritized first
      in candidate sort (best market conditions = biggest bets).

  [5] RATE OF CHANGE FILTER — Stock must be down at least 4% from the
      close on the day before the consecutive down streak began.
      Eliminates slow-bleed setups with no real bounce energy.

  [6] DISTANCE FROM 50-DAY SMA — Used as secondary ranking factor
      (further below 50d SMA = ranked higher, after RSI(2) primary sort).
      Optional hard filter available via DIST_MA50_HARD_FILTER flag.

  [7] TRAILING STOP ON REMAINING SHARES — After partial exit trigger (+1%),
      remaining shares carry a trailing stop at +0.5% from entry price.
      Prevents spike-then-reverse losses on the second half.

  [8] RSI(2) OVERBOUGHT EXIT — After min hold period, if RSI(2) crosses
      above RSI_EXIT_OVERBOUGHT (default 75), exit regardless of time stop.
      Captures the bounce peak dynamically.

  [9] OPTIMIZATION REPORT — metrics.json now includes per-year breakdown,
      regime analysis (bull vs neutral vs bear SPY years), and a parameter
      log for comparison across runs. Saved to results/optimization_report.json.

V7 Best Confirmed Results (30 positions, no drawdown management):
  CAGR 9.05% | ROI/yr 25.23% | Win Rate 69.72% | Avg Win 3.34%
  Avg Loss -3.31% | PF 1.14 | Max DD -28.94% | Sharpe 0.74

Strategy Rules (V10):
  Universe  : S&P 500 + S&P 400 MidCap (current + historical, no survivorship bias)
  Trend     : Stock > 200-day SMA
  Entry     : 5+ consecutive down days AND RSI(2) < 20 AND ATR > 1%
              AND volume > 20-day avg AND dollar volume > $5M/day
              AND stock down >= 4% from streak start (rate-of-change filter)
  Entry exec: Buy at open of next day
  Gap filter: Skip if next open gaps down > 1.5% OR gaps up > 2%
  Exit Tier1: 6+ down days — 2% target, 8d window, partial exit (50% at 1%)
              After partial: trailing stop at +0.5% from entry on remainder
  Exit Tier2: 5 down days — 2% target, 8d window
  RSI exit  : Exit if RSI(2) > 75 after min hold (overbought signal)
  Min hold  : 2 calendar days before any profit exit
  Positions : Max 30 simultaneous
  Sizing    : Base 5% | VIX-adjusted 2.5/5/7.5%
              Sweet-spot (SPY above 20wk MA, not extended): 7.5% override
              SPY co-oversold RSI(2)<15: 6% override
              Bull regime cap (SPY +12% above 200d or 12m return >20%): 2% cap
              Drawdown mild (8-15%): 3% cap | severe (15%+): 2% cap
              Earnings months: 3% cap
  Ranking   : Primary RSI(2) ascending, secondary distance-from-50MA descending
  Other     : SPY 200d regime, sector 20d MA, earnings blackout ±3d,
              correlation cap 3/sector, VIX spike pause 2d, cooldown 5d
  Commission: $0.005/share or $1.00 minimum
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
START_DATE            = "2004-01-01"
END_DATE              = datetime.date.today().isoformat()
MIN_DOLLAR_VOLUME     = 5_000_000
MAX_POSITIONS         = 30
POSITION_SIZE         = 0.05           # base 5%
POSITION_SIZE_HIGH    = 0.075          # VIX < 15
POSITION_SIZE_LOW     = 0.025          # VIX > 25
POSITION_SIZE_EARNINGS = 0.03          # Jan/Apr/Jul/Oct
MA_WINDOW             = 200
INITIAL_CAPITAL       = 100_000.0
RSI_PERIOD            = 2
RSI_THRESHOLD         = 20
RSI_EXIT_OVERBOUGHT   = 75             # [V10] exit if RSI(2) crosses above this
ATR_PERIOD            = 14
ATR_MIN_PCT           = 0.01
VOL_MA_PERIOD         = 20
MIN_HOLD_BEFORE_EXIT  = 2

# ── Tier system ───────────────────────────────────────────────────────────────
# Tier 3 (4 down days) REMOVED in V10. Min entry = 5 consecutive down days.
TIER1_MIN_DOWN        = 6
TIER1_TARGET          = 0.020
TIER1_HOLD_DAYS       = 8
TIER1_PARTIAL         = True
TIER1_PARTIAL_FRAC    = 0.50
TIER1_PARTIAL_TRIGGER = 0.010

TIER2_MIN_DOWN        = 5              # [V10] was 4 (Tier3), now minimum is 5
TIER2_TARGET          = 0.020
TIER2_HOLD_DAYS       = 8
TIER2_PARTIAL         = False
TIER2_PARTIAL_FRAC    = 0.0
TIER2_PARTIAL_TRIGGER = 0.0

MIN_CONSEC_DOWN       = TIER2_MIN_DOWN  # global minimum — 5 days

# ── [V10] Rate-of-change filter ───────────────────────────────────────────────
# Stock must be down at least this % from the close the day before the streak.
ROC_MIN_DROP          = -0.04          # -4% minimum total drop over streak

# ── [V10] Distance from 50-day SMA ranking ────────────────────────────────────
MA50_WINDOW           = 50
# Hard filter option: set True to require stock >= DIST_MA50_MIN below 50d SMA
DIST_MA50_HARD_FILTER = False
DIST_MA50_MIN_DROP    = -0.05          # only used if hard filter is True

# ── [V10] Bull regime filter ──────────────────────────────────────────────────
# When either condition is active, position size is CAPPED at 2%.
# Strategy never stops trading (circuit breaker lesson).
BULL_REGIME_12M_RETURN    = 0.20       # SPY trailing 12-month return threshold
BULL_REGIME_ABOVE_MA200   = 0.12       # SPY % above 200d SMA threshold
POSITION_SIZE_BULL_CAP    = 0.02       # size cap when bull regime active

# ── [V10] Aggressive sizing trigger (Connor TPS / sweet-spot) ─────────────────
# SPY above 20-week SMA AND below 52-week high by > 3% → sweet spot
SWEET_SPOT_SIZE           = 0.075      # 7.5% in sweet-spot regime
SWEET_SPOT_BELOW_ATH_MIN  = 0.03      # SPY must be this far below 52-week high

# ── [V10] SPY co-oversold boost (Larry Connors TPS) ──────────────────────────
SPY_CO_OVERSOLD_RSI       = 15         # SPY RSI(2) threshold for boost
POSITION_SIZE_CO_OVERSOLD = 0.06       # 6% when SPY also deeply oversold

# ── [V10] Trailing stop on remainder after partial ────────────────────────────
TRAILING_STOP_FROM_ENTRY  = 0.005      # +0.5% from entry — lock in some profit

# ── Filters ───────────────────────────────────────────────────────────────────
EARNINGS_BLACKOUT     = 3
GAP_DOWN_MAX          = -0.015
GAP_UP_MAX            = 0.020
SECTOR_MA_WINDOW      = 20
MAX_SECTOR_POSITIONS  = 3
VIX_HIGH              = 25
VIX_LOW               = 15
VIX_SPIKE_PCT         = 0.30
VIX_SPIKE_PAUSE_DAYS  = 2
REENTRY_COOLDOWN_DAYS = 5
COMMISSION_RATE       = 0.005
COMMISSION_MIN        = 1.00
EARNINGS_MONTHS       = {1, 4, 7, 10}

# ── Drawdown-based position sizing ────────────────────────────────────────────
DD_SCALE_MILD          = 0.08
DD_SCALE_SEVERE        = 0.15
POSITION_SIZE_DD_MILD  = 0.03
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
    else:  # 5 days (Tier 2 — minimum)
        return {
            "tier":            2,
            "profit_target":   TIER2_TARGET,
            "hold_days":       TIER2_HOLD_DAYS,
            "partial_enabled": TIER2_PARTIAL,
            "partial_frac":    TIER2_PARTIAL_FRAC,
            "partial_trigger": TIER2_TARGET,
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


def download_reference_data() -> tuple:
    # ── SPY ──────────────────────────────────────────────────────────────────
    spy = _dl_single("SPY")
    close = spy["Close"].squeeze()

    spy["spy_ma200"]       = close.rolling(200).mean()
    spy["spy_ok"]          = (close > spy["spy_ma200"].squeeze()).values

    # [V10] Bull regime computations
    spy["spy_12m_ret"]     = close.pct_change(252)           # trailing 12-month return
    spy["spy_pct_above_ma"] = (close / spy["spy_ma200"].squeeze()) - 1

    # [V10] Sweet-spot regime: SPY above 20-week MA and below 52-week high by >3%
    spy["spy_ma20w"]       = close.rolling(100).mean()       # ~20 trading weeks
    spy["spy_52w_high"]    = close.rolling(252).max()
    spy["spy_below_ath"]   = (spy["spy_52w_high"].squeeze() - close) / spy["spy_52w_high"].squeeze()
    spy["spy_sweet_spot"]  = (
        (close > spy["spy_ma20w"].squeeze()) &
        (spy["spy_below_ath"].squeeze() >= SWEET_SPOT_BELOW_ATH_MIN)
    )

    # [V10] SPY RSI(2) for co-oversold boost
    spy["spy_rsi2"]        = _compute_rsi(close, 2)

    # [V10] Bull regime flag (either condition)
    bull_a = spy["spy_12m_ret"].squeeze() > BULL_REGIME_12M_RETURN
    bull_b = spy["spy_pct_above_ma"].squeeze() > BULL_REGIME_ABOVE_MA200
    spy["spy_bull_regime"] = (bull_a | bull_b)

    print(f"[Download] SPY: {len(spy)} rows")

    # ── VIX ───────────────────────────────────────────────────────────────────
    vix = _dl_single("^VIX")
    vix_close = vix["Close"].squeeze()
    vix["vix_5d_ago"] = vix_close.shift(5)
    vix["vix_spike"]  = (
        vix_close / vix["vix_5d_ago"].replace(0, np.nan) - 1
    ) >= VIX_SPIKE_PCT
    print(f"[Download] VIX: {len(vix)} rows")

    # ── Sector ETFs ───────────────────────────────────────────────────────────
    etf_list = list(SECTOR_ETFS.keys())
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


def _compute_rsi(series: pd.Series, period: int) -> pd.Series:
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


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

    # Trend and base indicators
    df["ma200"]      = df["Close"].rolling(MA_WINDOW).mean()
    df["ma50"]       = df["Close"].rolling(MA50_WINDOW).mean()           # [V10]
    df["above_ma"]   = df["Close"] > df["ma200"]
    df["dist_ma50"]  = (df["Close"] - df["ma50"]) / df["ma50"]           # [V10] negative = below

    # Consecutive down days
    df["down_day"] = (df["Close"] < df["Close"].shift(1)).astype(int)
    consec, count = [], 0
    for d in df["down_day"]:
        count = count + 1 if d == 1 else 0
        consec.append(count)
    df["consec_down"] = consec

    # [V10] Rate-of-change filter: close at streak start vs today
    # streak_start_close = close N days ago where N = consec_down
    # Vectorized approximation: use rolling to find close before streak began
    streak_start_close = pd.Series(index=df.index, dtype=float)
    closes = df["Close"].values
    consec_arr = df["consec_down"].values
    for i in range(len(df)):
        n = int(consec_arr[i])
        if n > 0 and i >= n:
            streak_start_close.iloc[i] = closes[i - n]
        else:
            streak_start_close.iloc[i] = np.nan
    df["streak_start_close"] = streak_start_close
    df["roc_from_streak"]    = (df["Close"] - df["streak_start_close"]) / df["streak_start_close"]

    # RSI(2)
    df["rsi2"] = _compute_rsi(df["Close"], RSI_PERIOD)

    # ATR
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - df["Close"].shift(1)).abs(),
        (df["Low"]  - df["Close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["atr"]     = tr.rolling(ATR_PERIOD).mean()
    df["atr_pct"] = df["atr"] / df["Close"]

    # Volume
    df["vol_ma20"]       = df["Volume"].rolling(VOL_MA_PERIOD).mean()
    df["vol_confirm"]    = df["Volume"] > df["vol_ma20"]
    df["dollar_vol_ma20"] = (df["Close"] * df["Volume"]).rolling(VOL_MA_PERIOD).mean()

    # Base signal (5+ consecutive down days)
    base_signal = (
        df["above_ma"] &
        (df["consec_down"] >= MIN_CONSEC_DOWN) &
        (df["rsi2"] < RSI_THRESHOLD) &
        (df["atr_pct"] > ATR_MIN_PCT) &
        df["vol_confirm"] &
        (df["dollar_vol_ma20"] >= MIN_DOLLAR_VOLUME) &
        (df["roc_from_streak"] <= ROC_MIN_DROP)        # [V10] rate-of-change filter
    )

    # [V10] Optional hard distance-from-MA50 filter
    if DIST_MA50_HARD_FILTER:
        base_signal = base_signal & (df["dist_ma50"] <= DIST_MA50_MIN_DROP)

    df["signal"] = base_signal
    return df


# ─────────────────────────────────────────────────────────────────────────────
# 5. Helpers
# ─────────────────────────────────────────────────────────────────────────────
def calc_commission(shares: float, price: float) -> float:
    return max(shares * COMMISSION_RATE, COMMISSION_MIN)


def get_position_size(
    today,
    vix_df: pd.DataFrame,
    spy_df: pd.DataFrame,
    drawdown_pct: float = 0.0,
) -> float:
    """
    Position size priority (smallest cap wins, except sweet-spot/co-oversold
    which are boosts that still respect the bull-regime and drawdown caps):

      1. Base 5%
      2. VIX adjustment (2.5 / 5 / 7.5%)
      3. Sweet-spot boost → 7.5% (overrides VIX sizing upward)
      4. SPY co-oversold boost → 6%
      5. Bull regime cap → 2% (hard ceiling)
      6. Drawdown cap → 3% mild / 2% severe
      7. Earnings month cap → 3%
    """
    month          = pd.Timestamp(today).month
    earnings_month = month in EARNINGS_MONTHS
    base           = POSITION_SIZE

    # VIX adjustment
    try:
        vc = vix_df["Close"].squeeze()
        if today in vc.index:
            v = float(vc.loc[today])
            if v > VIX_HIGH:
                base = POSITION_SIZE_LOW    # 2.5%
            elif v < VIX_LOW:
                base = POSITION_SIZE_HIGH   # 7.5%
    except Exception:
        pass

    # [V10] Sweet-spot boost (Connor TPS regime)
    try:
        if today in spy_df.index and bool(spy_df.loc[today, "spy_sweet_spot"]):
            base = SWEET_SPOT_SIZE          # 7.5% in sweet-spot
    except Exception:
        pass

    # [V10] SPY co-oversold boost
    try:
        if today in spy_df.index:
            spy_rsi = float(spy_df.loc[today, "spy_rsi2"])
            if spy_rsi < SPY_CO_OVERSOLD_RSI:
                base = max(base, POSITION_SIZE_CO_OVERSOLD)  # at least 6%
    except Exception:
        pass

    # [V10] Bull regime cap — overrides boosts downward
    try:
        if today in spy_df.index and bool(spy_df.loc[today, "spy_bull_regime"]):
            base = min(base, POSITION_SIZE_BULL_CAP)  # hard cap at 2%
    except Exception:
        pass

    # Drawdown cap
    if drawdown_pct <= -DD_SCALE_SEVERE:
        base = min(base, POSITION_SIZE_DD_SEVERE)
    elif drawdown_pct <= -DD_SCALE_MILD:
        base = min(base, POSITION_SIZE_DD_MILD)

    # Earnings month cap
    if earnings_month and base > POSITION_SIZE_EARNINGS:
        base = POSITION_SIZE_EARNINGS

    return base


def sector_ok(tkr: str, date, sector_data: dict[str, pd.DataFrame]) -> bool:
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


def check_vix_spike(today, vix_df: pd.DataFrame, last_spike_date) -> tuple[bool, object]:
    try:
        if today in vix_df.index:
            if bool(vix_df.loc[today, "vix_spike"]):
                last_spike_date = today
    except Exception:
        pass
    if last_spike_date is not None:
        days_since = (pd.Timestamp(today) - pd.Timestamp(last_spike_date)).days
        if days_since <= VIX_SPIKE_PAUSE_DAYS:
            return True, last_spike_date
    return False, last_spike_date


# ─────────────────────────────────────────────────────────────────────────────
# 6. Backtest simulation
# ─────────────────────────────────────────────────────────────────────────────
def run_backtest(price_data, spy_df, vix_df, sector_data, earnings_map) -> pd.DataFrame:
    print("\n[Backtest] Running V10 simulation ...")
    spy_regime   = spy_df["spy_ok"].to_dict()

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
        spy_ok         = spy_regime.get(today, True)
        paused, last_vix_spike = check_vix_spike(today, vix_df, last_vix_spike)

        # ── Drawdown tracking ──────────────────────────────────────────────
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
            row        = tkr_df.loc[today]
            exit_price = float(row["Close"])
            entry_price = pos["entry_price"]
            days_held   = (pd.Timestamp(today) - pd.Timestamp(pos["entry_date"])).days
            pos_pct     = (exit_price - entry_price) / entry_price
            shares_rem  = pos["shares_remaining"]
            current_rsi = float(row["rsi2"]) if not np.isnan(row["rsi2"]) else 50.0

            time_stop   = days_held >= pos["hold_days"]
            early       = days_held < MIN_HOLD_BEFORE_EXIT
            profit_hit  = (not early) and pos_pct >= pos["profit_target"]

            # [V10] RSI(2) overbought exit signal
            rsi_exit    = (not early) and (current_rsi > RSI_EXIT_OVERBOUGHT)

            # [V10] Trailing stop on remainder (after partial done)
            trailing_stop_hit = (
                pos.get("partial_done", False) and
                pos_pct < TRAILING_STOP_FROM_ENTRY and
                not early
            )

            # Partial exit (Tier 1 only)
            if (pos["partial_enabled"] and
                    not pos["partial_done"] and
                    not early and
                    pos_pct >= pos["partial_trigger"]):
                partial_shares = shares_rem * pos["partial_frac"]
                commission     = calc_commission(partial_shares, exit_price)
                pnl            = (exit_price - entry_price) * partial_shares - commission
                trades.append({
                    "ticker":       tkr,
                    "entry_date":   pos["entry_date"],
                    "exit_date":    today,
                    "entry_price":  entry_price,
                    "exit_price":   exit_price,
                    "shares":       partial_shares,
                    "commission":   round(commission, 4),
                    "pnl_usd":      pnl,
                    "pnl_pct":      pos_pct * 100,
                    "days_held":    days_held,
                    "exit_reason":  "partial_exit",
                    "tier":         pos["tier"],
                    "consec_down":  pos["consec_down_at_entry"],
                    "portfolio_val": portfolio_value + pnl,
                    "regime":       pos.get("regime", "neutral"),
                })
                portfolio_value        += pnl
                pos["shares_remaining"] -= partial_shares
                pos["partial_done"]     = True
                pos["profit_target"]    = pos["profit_target"] * 2
                continue

            # Full exit conditions
            full_exit = (
                time_stop or
                rsi_exit or
                trailing_stop_hit or
                (not pos["partial_enabled"] and profit_hit) or
                (pos["partial_enabled"] and pos["partial_done"] and profit_hit)
            )
            if full_exit:
                commission = calc_commission(shares_rem, exit_price)
                pnl        = (exit_price - entry_price) * shares_rem - commission - pos["entry_commission"]
                if time_stop:
                    reason = "time_stop"
                elif rsi_exit:
                    reason = "rsi_overbought"
                elif trailing_stop_hit:
                    reason = "trailing_stop"
                else:
                    reason = "profit_target"
                trades.append({
                    "ticker":       tkr,
                    "entry_date":   pos["entry_date"],
                    "exit_date":    today,
                    "entry_price":  entry_price,
                    "exit_price":   exit_price,
                    "shares":       shares_rem,
                    "commission":   round(commission + pos["entry_commission"], 4),
                    "pnl_usd":      pnl,
                    "pnl_pct":      pos_pct * 100,
                    "days_held":    days_held,
                    "exit_reason":  reason,
                    "tier":         pos["tier"],
                    "consec_down":  pos["consec_down_at_entry"],
                    "portfolio_val": portfolio_value + pnl,
                    "regime":       pos.get("regime", "neutral"),
                })
                portfolio_value += pnl
                if time_stop:
                    cooldown_map[tkr] = today
                to_close.append(tkr)

        for tkr in to_close:
            del open_positions[tkr]

        if not spy_ok or paused:
            continue
        if len(open_positions) >= MAX_POSITIONS:
            continue

        # ── Determine today's SPY regime context for sizing ────────────────
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
                days_since = (pd.Timestamp(today) - pd.Timestamp(cooldown_map[tkr])).days
                if days_since < REENTRY_COOLDOWN_DAYS:
                    continue
            if near_earnings(tkr, today, earnings_map):
                continue
            if not sector_ok(tkr, today, sector_data):
                continue
            if count_sector_positions(tkr, open_positions) >= MAX_SECTOR_POSITIONS:
                continue
            rsi_val    = float(row["rsi2"])
            consec_val = int(row["consec_down"])
            dist_ma50  = float(row["dist_ma50"]) if not np.isnan(row["dist_ma50"]) else 0.0
            # [V10] SPY co-oversold entries get priority (sort first)
            priority   = 0 if spy_co_oversold else 1
            candidates.append((priority, rsi_val, -dist_ma50, tkr, consec_val))

        # Sort: co-oversold first, then RSI(2) ascending, then dist_ma50 descending
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
            prev_close_val = float(tkr_df.iloc[today_idx]["Close"])
            gap_pct        = (entry_price - prev_close_val) / prev_close_val
            if gap_pct < GAP_DOWN_MAX or gap_pct > GAP_UP_MAX:
                continue

            tier_cfg  = get_tier(consec_val)
            pos_size  = get_position_size(today, vix_df, spy_df, current_drawdown)
            shares    = (portfolio_value * pos_size) / entry_price
            entry_comm = calc_commission(shares, entry_price)

            # Determine regime label for analysis
            try:
                bull   = bool(spy_df.loc[today, "spy_bull_regime"]) if today in spy_df.index else False
                sweet  = bool(spy_df.loc[today, "spy_sweet_spot"])  if today in spy_df.index else False
                regime = "bull" if bull else ("sweet_spot" if sweet else ("co_oversold" if spy_co_oversold else "neutral"))
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

    total_comm    = trades_df["commission"].sum() if "commission" in trades_df else 0
    exit_counts   = (trades_df["exit_reason"].value_counts().to_dict()
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

    # [V10] Regime breakdown
    regime_stats = {}
    if "regime" in trades_df.columns:
        for reg in trades_df["regime"].unique():
            r_df  = trades_df[trades_df["regime"] == reg]
            r_win = r_df[r_df["pnl_usd"] > 0]
            r_los = r_df[r_df["pnl_usd"] <= 0]
            regime_stats[reg] = {
                "trades":   len(r_df),
                "win_rate": round((r_df["pnl_usd"] > 0).mean() * 100, 1),
                "avg_win":  round(r_win["pnl_pct"].mean(), 2) if len(r_win) else 0,
                "avg_loss": round(r_los["pnl_pct"].mean(), 2) if len(r_los) else 0,
                "pct_of_trades": round(len(r_df) / len(trades_df) * 100, 1),
            }

    # [V10] Per-year breakdown
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

    full_exits    = (trades_df[trades_df["exit_reason"] != "partial_exit"]
                     if "exit_reason" in trades_df.columns else trades_df)
    time_stop_n   = exit_counts.get("time_stop", 0)
    time_stop_rt  = round(time_stop_n / len(full_exits) * 100, 1) if len(full_exits) else 0

    metrics = {
        "version":             "V10",
        "period_start":        start_dt.date().isoformat(),
        "period_end":          end_dt.date().isoformat(),
        "years_tested":        round(years, 2),
        "total_trades":        len(trades_df),
        "trades_per_year":     round(len(trades_df) / years, 1),
        "win_rate_pct":        round(win_rate, 2),
        "cagr_pct":            round(cagr * 100, 2),
        "roi_per_year_pct":    round((equity - INITIAL_CAPITAL) / INITIAL_CAPITAL / years * 100, 2),
        "avg_days_held":       round(trades_df["days_held"].mean(), 2),
        "avg_win_pct":         round(avg_win, 2),
        "avg_loss_pct":        round(avg_loss, 2),
        "profit_factor":       round(pf, 2),
        "max_drawdown_pct":    round(max_dd, 2),
        "sharpe_ratio":        round(sharpe, 2),
        "time_stop_rate_pct":  time_stop_rt,
        "exit_reasons":        {k: int(v) for k, v in exit_counts.items()},
        "tier_stats":          tier_stats,
        "regime_stats":        regime_stats,
        "year_stats":          year_stats,
        "total_commission_usd": round(total_comm, 2),
        "initial_capital":     INITIAL_CAPITAL,
        "final_equity":        round(equity, 2),
        "total_return_pct":    round((equity / INITIAL_CAPITAL - 1) * 100, 2),
        "parameters": {
            "version":                   "V10",
            "min_consec_down":           MIN_CONSEC_DOWN,
            "tier1_6plus_days":          "2% target, 8d window, partial at 1% + trailing stop",
            "tier2_5_days":              "2% target, 8d window, no partial",
            "tier3_removed":             "4-day setups eliminated (V10)",
            "roc_min_drop":              f"{ROC_MIN_DROP*100:.0f}% from streak start",
            "dist_ma50_hard_filter":     DIST_MA50_HARD_FILTER,
            "dist_ma50_min_drop":        f"{DIST_MA50_MIN_DROP*100:.0f}%" if DIST_MA50_HARD_FILTER else "ranking only",
            "bull_regime_12m":           f">{BULL_REGIME_12M_RETURN*100:.0f}% SPY 12m return → 2% cap",
            "bull_regime_above_ma200":   f">{BULL_REGIME_ABOVE_MA200*100:.0f}% above 200d → 2% cap",
            "sweet_spot_size":           f"{SWEET_SPOT_SIZE*100:.1f}% when SPY above 20wk MA + below ATH 3%+",
            "spy_co_oversold_rsi":       f"SPY RSI(2)<{SPY_CO_OVERSOLD_RSI} → {POSITION_SIZE_CO_OVERSOLD*100:.0f}% size",
            "trailing_stop_from_entry":  f"+{TRAILING_STOP_FROM_ENTRY*100:.1f}% from entry on remainder",
            "rsi_exit_overbought":       RSI_EXIT_OVERBOUGHT,
            "max_positions":             MAX_POSITIONS,
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

    # [V10] Separate optimization report
    opt_report = {
        "run_date":      datetime.date.today().isoformat(),
        "version":       "V10",
        "summary": {
            "cagr_pct":         metrics["cagr_pct"],
            "win_rate_pct":     metrics["win_rate_pct"],
            "profit_factor":    metrics["profit_factor"],
            "sharpe_ratio":     metrics["sharpe_ratio"],
            "max_drawdown_pct": metrics["max_drawdown_pct"],
            "avg_win_pct":      metrics["avg_win_pct"],
            "avg_loss_pct":     metrics["avg_loss_pct"],
            "trades_per_year":  metrics["trades_per_year"],
            "final_equity":     metrics["final_equity"],
        },
        "regime_breakdown":  metrics.get("regime_stats", {}),
        "year_breakdown":    metrics.get("year_stats", {}),
        "tier_breakdown":    metrics.get("tier_stats", {}),
        "exit_breakdown":    metrics.get("exit_reasons", {}),
        "parameters":        metrics["parameters"],
    }
    with open(OUTPUT_DIR / "optimization_report.json", "w") as f:
        json.dump(opt_report, f, indent=2, default=str)

    print("\n" + "=" * 70)
    print("  NAIVE MR BACKTEST — V10")
    print("=" * 70)
    for k, v in metrics.items():
        if k == "tier_stats":
            print(f"\n  Per-Tier Statistics:")
            for tk, tv in v.items():
                print(f"    {tk}:")
                for sk, sv in tv.items():
                    print(f"      {sk:<16}: {sv}")
        elif k == "regime_stats":
            print(f"\n  Regime Breakdown (V10):")
            for rk, rv in v.items():
                print(f"    {rk}:")
                for sk, sv in rv.items():
                    print(f"      {sk:<16}: {sv}")
        elif k == "year_stats":
            print(f"\n  Per-Year Breakdown (V10):")
            for yr, yv in v.items():
                wr  = yv.get("win_rate", "?")
                pnl = yv.get("pnl_usd", "?")
                cnt = yv.get("trades", "?")
                print(f"    {yr}: {cnt:>5} trades  WR {wr:>5}%  P&L ${pnl:>10,.0f}")
        elif k in ("parameters", "exit_reasons"):
            label = "Parameters" if "param" in k else "Exit Reason Breakdown"
            print(f"\n  {label}:")
            for ek, ev in v.items():
                print(f"    {ek:<40}: {ev}")
        else:
            print(f"  {k.replace('_',' ').title():<36}: {v}")
    print("=" * 70)
    print(f"\n  Saved to: {OUTPUT_DIR.resolve()}")
    print(f"  Optimization report: {(OUTPUT_DIR / 'optimization_report.json').resolve()}")


# ─────────────────────────────────────────────────────────────────────────────
# 9. Entry point
# ─────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    universe    = get_universe()
    price_data  = download_prices(universe)
    spy_df, vix_df, sector_data = download_reference_data()
    earnings_map = build_earnings_dates(list(price_data.keys()))
    trades_df   = run_backtest(price_data, spy_df, vix_df, sector_data, earnings_map)
    if trades_df.empty:
        print("[ERROR] No trades generated.")
    else:
        metrics, eq_df = compute_metrics(trades_df)
        save_outputs(trades_df, metrics, eq_df)
