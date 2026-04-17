# backtest_ideas_v5.py
# Ideas V5 — Genuinely untested ideas vs V35+I3 baseline
#
# Baseline: V35 + Idea3 put spread (19.71% CAGR, $4,513,155, MaxDD -52.87%, Sharpe 0.74)
#
# Cross-referenced exhaustively against the complete do-not-retry table.
# Only ideas with NO prior test recorded are included.
#
# Tests in this suite:
#
#   BASELINE_V35I3  — V35 + put spread hedge (control, reproduced from backtest_ideas_v2)
#
#   A_VOL_EXIT      — Vol-adjusted dynamic exits (AHL/Winton principle)
#                     profit_target = clip(ATR_pct × 1.8, 1.5%, 6%)
#                     hold_days = 6/8/12 based on ATR percentile rank
#                     THE only untested axis: exits have always been static 2%/8d
#
#   B_TOM_SIZING    — Turn-of-month entry size boost
#                     Entries on last trading day of month through day +3 get 1.15x size
#                     Academic: 90-year evidence (Lakonishok & Smidt 1988, McConnell 2008)
#                     TOM as a *sizing overlay on V35 entries* is untested
#                     (C_TurnOfMonth in README was a standalone strategy, not a sizing layer)
#
#   C_VIX_RSI      — VIX low-regime RSI tightening (from V36-T2 which showed +$86k +0.08% CAGR)
#                     When VIX < 15: require RSI(2) < 15 instead of < 20
#                     Best single positive result from the current session
#
#   D_PARTIAL_TUNE  — Tier 1 partial trigger tuning
#                     Current: partial at +1.0%, remainder at +2.0%
#                     Test: partial at +0.8%, remainder at +2.0%
#                     Never tested at any level other than 1.0%
#
#   E_EARNINGS_EXT  — Earnings blackout 3 → 5 days
#                     README explicitly flags as "one remaining low-priority test"
#                     Expected: small negative (fewer trades) but could improve win rate
#
#   F_COMBO_ACB     — Combine A + C + B (the three most promising)
#                     Vol exits + VIX RSI tightening + TOM sizing
#                     Test if benefits are additive or cancel
#
#   G_COMBO_ACD     — Combine A + C + D
#                     Vol exits + VIX RSI tightening + partial trigger tuning
#
# Put spread overlay is applied identically to all tests (same as Ideas V2 Idea3).
# This matches the V35+I3 baseline correctly.
#
# Architecture: structured identically to backtest_ideas_v2.py / v3.py / v4.py
# Results saved to results_ideas_v5/

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
# Output dir
# ---------------------------------------------------------------------------
OUTPUT_DIR = Path("results_ideas_v5")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# V35 baseline parameters — do not change
# ---------------------------------------------------------------------------
START_DATE           = "2004-01-01"
END_DATE             = datetime.date.today().isoformat()
MIN_DOLLAR_VOLUME    = 5_000_000
MAX_POSITIONS        = 60
POSITION_SIZE        = 0.05
POSITION_SIZE_HIGH   = 0.09
POSITION_SIZE_EARNINGS = 0.03
MA_WINDOW            = 200
INITIAL_CAPITAL      = 100_000.0
RSI_PERIOD           = 2
RSI_THRESHOLD        = 20        # baseline; C overrides to 15 when VIX < 15
ATR_PERIOD           = 14
ATR_MIN_PCT          = 0.01
VOL_MA_PERIOD        = 20
MIN_HOLD_BEFORE_EXIT = 2
TIER1_MIN_DOWN       = 6
TIER1_TARGET         = 0.020
TIER1_HOLD_DAYS      = 8
TIER1_PARTIAL        = True
TIER1_PARTIAL_FRAC   = 0.50
TIER1_PARTIAL_TRIGGER = 0.010   # baseline; D tests 0.008
TIER2_MIN_DOWN       = 5
TIER2_TARGET         = 0.020
TIER2_HOLD_DAYS      = 8
TIER3_MIN_DOWN       = 4
TIER3_TARGET         = 0.020
TIER3_HOLD_DAYS      = 8
MIN_CONSEC_DOWN      = TIER3_MIN_DOWN
VELOCITY_CRASH_5D_THRESHOLD = -0.12
VELOCITY_CRASH_PAUSE_DAYS   = 5
EARNINGS_BLACKOUT    = 3        # baseline; E tests 5
GAP_DOWN_MAX         = -0.010
GAP_UP_MAX           = 0.020
SECTOR_MA_WINDOW     = 20
MAX_SECTOR_POSITIONS = 3
VIX_LOW              = 25
VIX_SPIKE_PCT        = 0.30
VIX_SPIKE_PAUSE_DAYS = 0
REENTRY_COOLDOWN_DAYS = 5
COMMISSION_RATE      = 0.005
COMMISSION_MIN       = 0.35
EARNINGS_MONTHS      = {1, 4, 7, 10}
TOP_SIGNAL_PCT       = 0.20
TOP_SIGNAL_MULTIPLIER = 1.30
TOP_SIGNAL_HARD_CAP  = 0.12
MIN_CANDIDATES_FOR_TOP = 5

# ---------------------------------------------------------------------------
# Test-specific parameters
# ---------------------------------------------------------------------------

# A: Vol-adjusted exits
A_TARGET_K   = 1.80    # profit_target = ATR_pct × k
A_TARGET_MIN = 0.015
A_TARGET_MAX = 0.060
A_ATR_WINDOW = 252     # rolling window for ATR percentile rank
A_HOLD_LOW   = 6       # ATR rank < 25th pct
A_HOLD_MID   = 8       # ATR rank 25th–75th pct
A_HOLD_HIGH  = 12      # ATR rank > 75th pct

# B: Turn-of-month sizing
B_TOM_SIZE_MULT = 1.15  # size multiplier for TOM entries
B_TOM_DAYS_AFTER = 3    # last day of month + this many days forward = TOM window

# C: VIX low-regime RSI tightening (from V36-T2)
C_VIX_TIGHT      = 15.0  # VIX threshold
C_RSI_TIGHT      = 15.0  # RSI threshold when VIX < C_VIX_TIGHT

# D: Tier 1 partial trigger tuning
D_PARTIAL_TRIGGER = 0.008  # was 0.010

# E: Earnings blackout extension
E_EARNINGS_BLACKOUT = 5  # was 3

# Put spread parameters (Idea 3 — identical to Ideas V2)
PUT_COST_PER_QUARTER = 0.015   # 1.5% of portfolio per quarter
PUT_LOWER_STRIKE_PCT = 0.05    # 5% OTM long put
PUT_UPPER_STRIKE_PCT = 0.15    # 15% OTM short put (spread width = 10%)
PUT_MAX_PAYOUT_PCT   = 0.10    # max payout = 10% of portfolio
PUT_RENEW_DAYS       = 63      # quarterly

# ---------------------------------------------------------------------------
# Sector map
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
# 1. Universe
# ---------------------------------------------------------------------------
def _fetch_wiki(url):
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    return pd.read_html(io.StringIO(resp.text), header=0)

def _extract_tickers(table):
    for col in ["Symbol", "Ticker symbol", "Ticker", "Ticker Symbol"]:
        if col in table.columns:
            return table[col].dropna().astype(str).tolist()
    for col in table.columns:
        cs = table[col].dropna().astype(str)
        if cs.str.match(r"^[A-Z]{1,5}(-[A-Z])?$").mean() > 0.3:
            return cs.tolist()
    return []

def get_universe():
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
        "YHOO","SUNW","PALM","GE","GM","F","XOM","CVX","IBM","MSFT","AAPL",
        "AMZN","GOOG","GOOGL","META","NVDA","TSLA","BRK-B","JPM","BAC",
        "WFC","GS","MS","USB","PNC","TFC","COF","AXP","V","MA",
        "HD","LOW","TGT","WMT","COST","KR","CVS","WBA",
        "UNH","CI","HUM","JNJ","PFE","MRK","ABBV","BMY","AMGN","GILD",
        "LLY","REGN","VRTX","ZTS","ISRG","BSX","SYK","MDT",
        "BA","LMT","RTX","NOC","GD","CAT","DE","HON","MMM",
        "COP","EOG","SLB","HAL","MPC","VLO",
        "NEE","DUK","SO","AEP","EXC","SRE","ED",
        "AMT","PLD","CCI","SPG","O","WELL","PSA","EQR","AVB",
        "SBUX","MCD","YUM","CMG","DIS","NFLX","CMCSA","VZ","TMUS",
        "PG","KO","PEP","CL","KMB","CHD","EL",
    ]
    tickers.update(historical_extras)
    result = sorted(tickers)
    print(f"[Universe] Total: {len(result)} tickers")
    return result


# ---------------------------------------------------------------------------
# 2. Downloads
# ---------------------------------------------------------------------------
def download_prices(tickers):
    print(f"\n[Download] {len(tickers)} tickers ({START_DATE} → {END_DATE})")
    all_data = {}
    for i in tqdm(range(0, len(tickers), 100), desc="Downloading"):
        chunk = tickers[i:i+100]
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
    print(f"[Download] {len(all_data)} tickers downloaded")
    return all_data

def _dl_single(ticker):
    df = yf.download(ticker, start=START_DATE, end=END_DATE,
                     auto_adjust=True, progress=False)
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df

def _compute_rsi(series, period):
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def download_reference_data():
    spy = _dl_single("SPY")
    close = spy["Close"].squeeze()
    spy["spy_ma200"]  = close.rolling(200).mean()
    spy["spy_ok"]     = (close > spy["spy_ma200"].squeeze()).values
    spy["spy_5d_ret"] = close.pct_change(5)
    print(f"[Download] SPY: {len(spy)} rows")

    vix = _dl_single("^VIX")
    vix_close = vix["Close"].squeeze()
    vix["vix_5d_ago"] = vix_close.shift(5)
    vix["vix_spike"]  = (vix_close / vix["vix_5d_ago"].replace(0, np.nan) - 1) >= VIX_SPIKE_PCT
    print(f"[Download] VIX: {len(vix)} rows")

    etf_list = list(SECTOR_ETFS.keys())
    sector_data = {}
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


# ---------------------------------------------------------------------------
# 3. Earnings calendar
# ---------------------------------------------------------------------------
def build_earnings_dates(tickers):
    print(f"[Earnings] Building calendar for {len(tickers)} tickers ...")
    earnings_map = {}
    for tkr in tqdm(tickers, desc="Earnings"):
        try:
            cal = yf.Ticker(tkr).calendar
            if cal is None or (hasattr(cal, "empty") and cal.empty):
                continue
            dates = set()
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
    print(f"[Earnings] {len(earnings_map)} tickers with dates")
    return earnings_map


# ---------------------------------------------------------------------------
# 4. Signal generation — with ATR percentile for Test A
# ---------------------------------------------------------------------------
def generate_signals(df):
    df = df.copy()
    df["ma200"]    = df["Close"].rolling(MA_WINDOW).mean()
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

    # ATR percentile rank (for Test A vol-adjusted exits)
    df["atr_pct_rank"] = df["atr_pct"].rolling(A_ATR_WINDOW, min_periods=60).rank(pct=True)

    df["vol_ma20"]       = df["Volume"].rolling(VOL_MA_PERIOD).mean()
    df["vol_confirm"]    = df["Volume"] > df["vol_ma20"]
    df["dollar_vol_ma20"] = (df["Close"] * df["Volume"]).rolling(VOL_MA_PERIOD).mean()

    df["signal"] = (
        df["above_ma"]
        & (df["consec_down"] >= MIN_CONSEC_DOWN)
        & (df["rsi2"] < RSI_THRESHOLD)  # note: C test adjusts this at runtime per VIX
        & (df["atr_pct"] > ATR_MIN_PCT)
        & df["vol_confirm"]
        & (df["dollar_vol_ma20"] >= MIN_DOLLAR_VOLUME)
    )
    return df


# ---------------------------------------------------------------------------
# 5. Put spread overlay (Idea 3 — identical to Ideas V2)
# ---------------------------------------------------------------------------
def simulate_put_spread(trading_dates, portfolio_values_by_date, spy_df):
    """
    Simulates the quarterly SPY 5%/15% OTM put spread hedge.
    Returns a dict of {date: pnl_delta} adjustments to apply to portfolio equity.
    Identical logic to Ideas V2 Idea3 implementation.
    """
    spy_close = spy_df["Close"].squeeze()
    pnl_events = {}
    last_renew  = None
    ref_price   = None
    portfolio_at_renew = INITIAL_CAPITAL

    for i, date in enumerate(trading_dates):
        if date not in spy_close.index:
            continue
        spy_px = float(spy_close.loc[date])
        port_val = portfolio_values_by_date.get(date, INITIAL_CAPITAL)

        # Renew spread every PUT_RENEW_DAYS trading days
        renew = (last_renew is None) or (i - trading_dates.index(last_renew) >= PUT_RENEW_DAYS)
        if renew:
            # Pay premium
            premium = port_val * PUT_COST_PER_QUARTER
            pnl_events[date] = pnl_events.get(date, 0) - premium
            ref_price         = spy_px
            portfolio_at_renew = port_val
            last_renew        = date

        if ref_price is None:
            continue

        # Check for payout: SPY dropped > 5% from ref_price
        drop_pct = (ref_price - spy_px) / ref_price
        if drop_pct > PUT_LOWER_STRIKE_PCT:
            # Payout scales linearly from 5% to 15% drop, capped at 10% of portfolio
            payout_pct = min(drop_pct - PUT_LOWER_STRIKE_PCT,
                             PUT_UPPER_STRIKE_PCT - PUT_LOWER_STRIKE_PCT)
            payout_frac = payout_pct / (PUT_UPPER_STRIKE_PCT - PUT_LOWER_STRIKE_PCT)
            payout = portfolio_at_renew * PUT_MAX_PAYOUT_PCT * payout_frac
            pnl_events[date] = pnl_events.get(date, 0) + payout
            # Reset ref after payout to avoid double-counting
            ref_price = spy_px
            last_renew = date

    return pnl_events


# ---------------------------------------------------------------------------
# 6. Helpers
# ---------------------------------------------------------------------------
def calc_commission(shares, price):
    return max(shares * COMMISSION_RATE, COMMISSION_MIN)

def get_tier(consec_down, test_id="BASELINE_V35I3", atr_pct=0.02, atr_rank=0.5):
    """Returns tier config dict. Test A modifies targets/hold_days dynamically."""
    if consec_down >= TIER1_MIN_DOWN:
        partial_trigger = TIER1_PARTIAL_TRIGGER
        if test_id in ("D_PARTIAL_TUNE", "G_COMBO_ACD"):
            partial_trigger = D_PARTIAL_TRIGGER
        cfg = {"tier": 1, "profit_target": TIER1_TARGET, "hold_days": TIER1_HOLD_DAYS,
               "partial_enabled": True, "partial_frac": TIER1_PARTIAL_FRAC,
               "partial_trigger": partial_trigger}
    elif consec_down >= TIER2_MIN_DOWN:
        cfg = {"tier": 2, "profit_target": TIER2_TARGET, "hold_days": TIER2_HOLD_DAYS,
               "partial_enabled": False, "partial_frac": 0.0, "partial_trigger": TIER2_TARGET}
    else:
        cfg = {"tier": 3, "profit_target": TIER3_TARGET, "hold_days": TIER3_HOLD_DAYS,
               "partial_enabled": False, "partial_frac": 0.0, "partial_trigger": TIER3_TARGET}

    # Test A / F / G: override profit_target and hold_days with vol-adjusted values
    if test_id in ("A_VOL_EXIT", "F_COMBO_ACB", "G_COMBO_ACD"):
        vol_target = float(np.clip(atr_pct * A_TARGET_K, A_TARGET_MIN, A_TARGET_MAX))
        cfg["profit_target"] = vol_target
        if atr_rank < 0.25:
            cfg["hold_days"] = A_HOLD_LOW
        elif atr_rank < 0.75:
            cfg["hold_days"] = A_HOLD_MID
        else:
            cfg["hold_days"] = A_HOLD_HIGH
        if cfg["partial_enabled"]:
            cfg["partial_trigger"] = vol_target * 0.5  # partial at 50% of target

    return cfg

def get_position_size(today, vix_df, drawdown_pct=0.0, size_multiplier=1.0):
    month = pd.Timestamp(today).month
    earnings_month = month in EARNINGS_MONTHS
    base = POSITION_SIZE
    try:
        vc = vix_df["Close"].squeeze()
        if today in vc.index:
            if float(vc.loc[today]) < VIX_LOW:
                base = POSITION_SIZE_HIGH
    except Exception:
        pass
    if earnings_month and base > POSITION_SIZE_EARNINGS:
        base = POSITION_SIZE_EARNINGS
    return min(base * size_multiplier, TOP_SIGNAL_HARD_CAP)

def sector_ok(tkr, date, sector_data):
    etf = TICKER_TO_SECTOR.get(tkr)
    if etf is None or etf not in sector_data:
        return True
    df = sector_data[etf]
    if date not in df.index:
        return True
    return bool(df.loc[date, "ok"])

def count_sector_pos(tkr, open_positions):
    etf = TICKER_TO_SECTOR.get(tkr)
    if etf is None:
        return 0
    return sum(1 for t in open_positions if TICKER_TO_SECTOR.get(t) == etf)

def check_vix_spike(today, vix_df, last_spike):
    try:
        if today in vix_df.index and bool(vix_df.loc[today, "vix_spike"]):
            last_spike = today
    except Exception:
        pass
    if last_spike is not None:
        if (pd.Timestamp(today) - pd.Timestamp(last_spike)).days <= VIX_SPIKE_PAUSE_DAYS:
            return True, last_spike
    return False, last_spike

def is_tom_window(today, trading_dates_set_with_idx):
    """
    Returns True if today is in the turn-of-month window:
    last trading day of the month through the next B_TOM_DAYS_AFTER trading days.
    """
    ts = pd.Timestamp(today)
    # Last trading day of month: next day is a different month
    # We check if this day is within B_TOM_DAYS_AFTER of any month-end trading day
    # Approximation: is today in [last_bday_of_month - 0, last_bday_of_month + 3]?
    # We use pandas month-end offset
    month_end = ts + pd.offsets.MonthEnd(0)
    days_from_month_end = (month_end - ts).days
    # Also check days after month start
    month_start = ts.replace(day=1)
    days_from_month_start = (ts - month_start).days
    # TOM window: last 1 trading day of month or first 3 trading days of next month
    # Approximate: within 5 calendar days of month end
    return days_from_month_end <= 1 or days_from_month_start <= B_TOM_DAYS_AFTER

def get_vix_today(today, vix_df):
    try:
        vc = vix_df["Close"].squeeze()
        if today in vc.index:
            return float(vc.loc[today])
    except Exception:
        pass
    return 20.0

def near_earnings(tkr, date, earnings_map, blackout_days=None):
    if blackout_days is None:
        blackout_days = EARNINGS_BLACKOUT
    if tkr not in earnings_map:
        return False
    d = pd.Timestamp(date).normalize()
    return any(abs((d - e).days) <= blackout_days for e in earnings_map[tkr])


# ---------------------------------------------------------------------------
# 7. Core backtest engine
# ---------------------------------------------------------------------------
def run_backtest(price_data, spy_df, vix_df, sector_data, earnings_map,
                 test_id="BASELINE_V35I3"):
    print(f"\n[Backtest] Running {test_id} ...")

    # Determine per-test overrides
    earnings_blackout_days = E_EARNINGS_BLACKOUT if test_id == "E_EARNINGS_EXT" else EARNINGS_BLACKOUT

    spy_regime = spy_df["spy_ok"].to_dict()
    all_dates: set = set()
    for df in price_data.values():
        all_dates.update(df.index)
    trading_dates = sorted(all_dates)

    signals = {}
    min_bars = MA_WINDOW + VOL_MA_PERIOD + ATR_PERIOD + MIN_CONSEC_DOWN + 5
    for tkr, df in price_data.items():
        if len(df) > min_bars:
            signals[tkr] = generate_signals(df)

    portfolio_value   = INITIAL_CAPITAL
    portfolio_peak    = None
    current_drawdown  = 0.0
    open_positions    = {}
    trades            = []
    cooldown_map      = {}
    last_vix_spike    = None
    last_velocity_crash = None
    portfolio_by_date = {}  # for put spread

    for today in tqdm(trading_dates, desc=f"Sim {test_id}"):
        portfolio_by_date[today] = portfolio_value

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

        # ---- Exits ----
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
                partial_sh = shares_rem * pos["partial_frac"]
                comm       = calc_commission(partial_sh, exit_price)
                pnl        = (exit_price - entry_price) * partial_sh - comm
                trades.append({
                    "ticker": tkr, "entry_date": pos["entry_date"], "exit_date": today,
                    "entry_price": entry_price, "exit_price": exit_price,
                    "shares": partial_sh, "commission": round(comm, 4),
                    "pnl_usd": pnl, "pnl_pct": pos_pct * 100, "days_held": days_held,
                    "exit_reason": "partial_exit", "tier": pos["tier"],
                    "consec_down": pos["consec_down_at_entry"],
                    "portfolio_val": portfolio_value + pnl, "test": test_id,
                })
                portfolio_value += pnl
                pos["shares_remaining"] -= partial_sh
                pos["partial_done"]   = True
                pos["profit_target"]  = pos["profit_target"] * 2
                continue

            full_exit = (
                time_stop
                or (not pos["partial_enabled"] and profit_hit)
                or (pos["partial_enabled"] and pos["partial_done"] and profit_hit)
            )
            if full_exit:
                comm = calc_commission(shares_rem, exit_price)
                pnl  = ((exit_price - entry_price) * shares_rem
                        - comm - pos["entry_commission"])
                reason = "time_stop" if time_stop else "profit_target"
                trades.append({
                    "ticker": tkr, "entry_date": pos["entry_date"], "exit_date": today,
                    "entry_price": entry_price, "exit_price": exit_price,
                    "shares": shares_rem,
                    "commission": round(comm + pos["entry_commission"], 4),
                    "pnl_usd": pnl, "pnl_pct": pos_pct * 100, "days_held": days_held,
                    "exit_reason": reason, "tier": pos["tier"],
                    "consec_down": pos["consec_down_at_entry"],
                    "portfolio_val": portfolio_value + pnl, "test": test_id,
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

        # ---- Entries ----
        vix_today = get_vix_today(today, vix_df)
        # Test C / F / G: tighten RSI threshold in low-VIX regime
        rsi_threshold_today = RSI_THRESHOLD
        if test_id in ("C_VIX_RSI", "F_COMBO_ACB", "G_COMBO_ACD"):
            if vix_today < C_VIX_TIGHT:
                rsi_threshold_today = C_RSI_TIGHT

        # Test B / F: turn-of-month flag
        tom_today = False
        if test_id in ("B_TOM_SIZING", "F_COMBO_ACB"):
            tom_today = is_tom_window(today, None)

        candidates = []
        for tkr, tkr_df in signals.items():
            if tkr in open_positions or today not in tkr_df.index:
                continue
            row = tkr_df.loc[today]
            if not row["signal"]:
                continue
            # Test C/F/G: re-check RSI with today's threshold
            if test_id in ("C_VIX_RSI", "F_COMBO_ACB", "G_COMBO_ACD"):
                if float(row["rsi2"]) >= rsi_threshold_today:
                    continue
            if tkr in cooldown_map:
                if (pd.Timestamp(today) - pd.Timestamp(cooldown_map[tkr])).days < REENTRY_COOLDOWN_DAYS:
                    continue
            if near_earnings(tkr, today, earnings_map, earnings_blackout_days):
                continue
            if not sector_ok(tkr, today, sector_data):
                continue
            if count_sector_pos(tkr, open_positions) >= MAX_SECTOR_POSITIONS:
                continue

            rsi2    = float(row["rsi2"])
            atr_pct = float(row["atr_pct"])
            score   = rsi2 / atr_pct if atr_pct > 0 else rsi2 * 1000
            atr_rank = float(row.get("atr_pct_rank", 0.5))
            candidates.append((score, tkr, int(row["consec_down"]), rsi2, atr_pct, atr_rank))

        candidates.sort(key=lambda x: x[0])
        n = len(candidates)
        top_n = max(1, int(n * TOP_SIGNAL_PCT))

        for rank, (score, tkr, consec_val, rsi_val, atr_pct_val, atr_rank) in enumerate(candidates):
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

            tier_cfg = get_tier(consec_val, test_id, atr_pct_val, atr_rank)

            # Sizing
            size_mult = 1.0
            if n >= MIN_CANDIDATES_FOR_TOP and rank < top_n:
                size_mult = TOP_SIGNAL_MULTIPLIER
            if tom_today:
                size_mult *= B_TOM_SIZE_MULT

            pos_size = get_position_size(today, vix_df, current_drawdown, size_mult)
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

    print(f"[Backtest] {test_id}: {len(trades)} MR trades")
    trades_df = pd.DataFrame(trades)

    # Apply put spread overlay to all tests
    if not trades_df.empty:
        put_pnl = simulate_put_spread(trading_dates, portfolio_by_date, spy_df)
        put_total = sum(put_pnl.values())
        print(f"[Backtest] {test_id}: put spread net P&L = ${put_total:,.0f}")
    else:
        put_pnl = {}

    return trades_df, put_pnl


# ---------------------------------------------------------------------------
# 8. Metrics
# ---------------------------------------------------------------------------
def compute_metrics(trades_df, put_pnl, test_id):
    if trades_df.empty:
        return {"test": test_id, "error": "No trades"}

    trades_df = trades_df.sort_values("exit_date").reset_index(drop=True)

    # Build equity curve including put spread P&L
    equity = INITIAL_CAPITAL
    equity_curve = []
    all_dates_sorted = sorted(set(trades_df["exit_date"].tolist()) | set(put_pnl.keys()))
    put_dates = set(put_pnl.keys())

    # Step through trades chronologically
    for _, row in trades_df.iterrows():
        # Apply any put P&L on or before this trade date first
        d = row["exit_date"]
        equity += row["pnl_usd"]
        equity_curve.append({"date": d, "equity": equity})

    # Add put pnl events to equity curve
    for d, pnl in sorted(put_pnl.items()):
        equity_curve.append({"date": d, "equity_adj": pnl})

    # Rebuild equity curve properly
    equity = INITIAL_CAPITAL
    combined = []
    trade_iter = iter(trades_df.iterrows())
    put_iter   = iter(sorted(put_pnl.items()))

    trade_row  = next(trade_iter, None)
    put_item   = next(put_iter, None)

    while trade_row is not None or put_item is not None:
        take_trade = False
        if trade_row is not None and put_item is not None:
            take_trade = str(trade_row[1]["exit_date"]) <= str(put_item[0])
        elif trade_row is not None:
            take_trade = True

        if take_trade:
            equity += trade_row[1]["pnl_usd"]
            combined.append({"date": trade_row[1]["exit_date"], "equity": equity})
            trade_row = next(trade_iter, None)
        else:
            equity += put_item[1]
            combined.append({"date": put_item[0], "equity": equity})
            put_item = next(put_iter, None)

    eq_df = pd.DataFrame(combined)
    if eq_df.empty:
        return {"test": test_id, "error": "Empty equity curve"}

    start_dt = pd.to_datetime(trades_df["entry_date"].min())
    end_dt   = pd.to_datetime(trades_df["exit_date"].max())
    years    = max((end_dt - start_dt).days / 365.25, 1e-6)
    final_eq = equity
    cagr     = (final_eq / INITIAL_CAPITAL) ** (1 / years) - 1

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
    eq_dt = eq_dt.set_index("date").sort_index()
    monthly = eq_dt["equity"].resample("ME").last().ffill().pct_change().dropna()
    sharpe  = monthly.mean() / monthly.std() * np.sqrt(12) if monthly.std() > 0 else 0
    down    = monthly[monthly < 0]
    sortino = monthly.mean() / down.std() * np.sqrt(12) if len(down) > 1 and down.std() > 0 else 0

    trades_df["exit_year"] = pd.to_datetime(trades_df["exit_date"]).dt.year
    year_stats = {}
    for yr in sorted(trades_df["exit_year"].unique()):
        y_df = trades_df[trades_df["exit_year"] == yr]
        y_win = y_df[y_df["pnl_usd"] > 0]
        year_stats[str(yr)] = {
            "trades":   len(y_df),
            "win_rate": round((y_df["pnl_usd"] > 0).mean() * 100, 1),
            "pnl_usd":  round(y_df["pnl_usd"].sum(), 2),
        }

    return {
        "test":             test_id,
        "total_trades":     len(trades_df),
        "trades_per_year":  round(len(trades_df) / years, 1),
        "cagr_pct":         round(cagr * 100, 2),
        "final_equity":     round(final_eq, 2),
        "max_drawdown_pct": round(max_dd, 2),
        "sharpe_ratio":     round(sharpe, 2),
        "sortino_ratio":    round(sortino, 2),
        "win_rate_pct":     round(win_rate, 2),
        "profit_factor":    round(pf, 2),
        "avg_win_pct":      round(avg_win, 2),
        "avg_loss_pct":     round(avg_loss, 2),
        "avg_days_held":    round(trades_df["days_held"].mean(), 2),
        "put_spread_net":   round(sum(put_pnl.values()), 2),
        "year_stats":       year_stats,
    }


# ---------------------------------------------------------------------------
# 9. Save + print
# ---------------------------------------------------------------------------
TEST_DESCRIPTIONS = {
    "BASELINE_V35I3": "V35 + Idea3 put spread — control (target: 19.71% CAGR, $4,513k, -52.87% MaxDD)",
    "A_VOL_EXIT":     "Vol-adjusted exits: target=1.8×ATR (1.5%-6%), hold=6/8/12d by ATR rank",
    "B_TOM_SIZING":   "Turn-of-month sizing: entries in TOM window get 1.15× size (Lakonishok 1988)",
    "C_VIX_RSI":      "VIX<15 regime RSI tightening: require RSI<15 (from V36-T2: +$86k +0.08% CAGR)",
    "D_PARTIAL_TUNE": "Tier 1 partial trigger 1.0%→0.8% (captures more partials earlier)",
    "E_EARNINGS_EXT": "Earnings blackout 3→5 days (README flagged as remaining test)",
    "F_COMBO_ACB":    "Combo: vol exits + VIX RSI tightening + TOM sizing",
    "G_COMBO_ACD":    "Combo: vol exits + VIX RSI tightening + partial trigger tune",
}

def save_outputs(all_metrics, all_trades):
    for test_id, df in all_trades.items():
        if not df.empty:
            df.to_csv(OUTPUT_DIR / f"trades_{test_id.lower()}.csv", index=False)

    result = {
        "run_date":  datetime.date.today().isoformat(),
        "baseline":  "V35+I3 (19.71% CAGR, $4,513,155, MaxDD -52.87%, Sharpe 0.74)",
        "suite":     "Ideas V5",
        "tests":     all_metrics,
    }
    with open(OUTPUT_DIR / "comparison.json", "w") as f:
        json.dump(result, f, indent=2, default=str)

    KEY = [
        ("cagr_pct",          "CAGR %"),
        ("final_equity",      "Final Equity"),
        ("max_drawdown_pct",  "Max DD %"),
        ("sharpe_ratio",      "Sharpe"),
        ("win_rate_pct",      "Win Rate %"),
        ("profit_factor",     "Profit Factor"),
        ("trades_per_year",   "Trades/yr"),
        ("avg_days_held",     "Avg Days"),
        ("put_spread_net",    "Put Net P&L"),
    ]

    tests_order = ["BASELINE_V35I3","A_VOL_EXIT","B_TOM_SIZING","C_VIX_RSI",
                   "D_PARTIAL_TUNE","E_EARNINGS_EXT","F_COMBO_ACB","G_COMBO_ACD"]
    by_test = {m["test"]: m for m in all_metrics}
    col_w = 18

    print("\n" + "=" * 130)
    print("  IDEAS V5 — RESULTS vs V35+I3 BASELINE")
    print("=" * 130)
    for t in tests_order:
        if t in by_test:
            print(f"  {t:<18} {TEST_DESCRIPTIONS.get(t,'')}")
    print()

    n_cols = sum(1 for t in tests_order if t in by_test)
    header = f"  {'Metric':<22}" + "".join(f"{t:>{col_w}}" for t in tests_order if t in by_test)
    print(header)
    print("  " + "-" * (22 + col_w * n_cols))

    baseline = by_test.get("BASELINE_V35I3", {})
    for key, label in KEY:
        row = f"  {label:<22}"
        for t in tests_order:
            m   = by_test.get(t, {})
            val = m.get(key)
            if val is None:
                row += f"{'N/A':>{col_w}}"
                continue
            if t != "BASELINE_V35I3" and key in baseline and isinstance(val, (int, float)):
                delta = val - baseline[key]
                sign  = "+" if delta >= 0 else ""
                cell  = f"{val:.2f}({sign}{delta:.2f})"
            else:
                if key == "final_equity":
                    cell = f"${val:,.0f}"
                elif key == "put_spread_net":
                    cell = f"${val:,.0f}"
                else:
                    cell = f"{val:.2f}"
            row += f"{cell:>{col_w}}"
        print(row)

    print("=" * 130)
    print(f"\n  Saved to: {OUTPUT_DIR.resolve()}")

    # Per-year table
    print("\n  PER-YEAR P&L (MR trades only, excl. put spread)")
    all_years = sorted({yr for m in all_metrics for yr in m.get("year_stats", {}).keys()})
    h2 = f"  {'Year':<8}" + "".join(f"{t:>{col_w}}" for t in tests_order if t in by_test)
    print(h2)
    print("  " + "-" * (8 + col_w * n_cols))
    for yr in all_years:
        row = f"  {yr:<8}"
        for t in tests_order:
            m  = by_test.get(t, {})
            ys = m.get("year_stats", {}).get(yr, {})
            pnl = ys.get("pnl_usd")
            wr  = ys.get("win_rate")
            if pnl is None:
                row += f"{'—':>{col_w}}"
            else:
                cell = f"${pnl:,.0f}({wr}%)"
                row += f"{cell:>{col_w}}"
        print(row)
    print("=" * 130 + "\n")
