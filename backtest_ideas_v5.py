# backtest_ideas_v5.py  (fixed)
# Ideas V5 — Genuinely untested ideas vs V35+I3 baseline
#
# Fixes vs original run:
#   1. put spread: removed ref_price reset on payout — was truncating crash payouts
#      and replaced O(n²) list.index() with a simple day counter
#   2. C_VIX_RSI: added diagnostic log of how many days VIX < 15 fires
#      and confirmed the re-check logic is correct (signal col uses RSI<20,
#      per-day re-check correctly tightens to RSI<15 on low-VIX days)
#   3. E_EARNINGS_EXT: confirmed blackout_days flows correctly throughout
#   4. B_TOM_SIZING: replaced calendar approximation with actual trading-date
#      list scan so TOM window is exact
#   5. Added H_COMBO_BCD: best non-A combo (TOM + VIX RSI + partial tune)

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

OUTPUT_DIR = Path("results_ideas_v5")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# V35 baseline parameters
# ---------------------------------------------------------------------------
START_DATE            = "2004-01-01"
END_DATE              = datetime.date.today().isoformat()
MIN_DOLLAR_VOLUME     = 5_000_000
MAX_POSITIONS         = 60
POSITION_SIZE         = 0.05
POSITION_SIZE_HIGH    = 0.09
POSITION_SIZE_EARNINGS = 0.03
MA_WINDOW             = 200
INITIAL_CAPITAL       = 100_000.0
RSI_PERIOD            = 2
RSI_THRESHOLD         = 20
ATR_PERIOD            = 14
ATR_MIN_PCT           = 0.01
VOL_MA_PERIOD         = 20
MIN_HOLD_BEFORE_EXIT  = 2
TIER1_MIN_DOWN        = 6
TIER1_TARGET          = 0.020
TIER1_HOLD_DAYS       = 8
TIER1_PARTIAL         = True
TIER1_PARTIAL_FRAC    = 0.50
TIER1_PARTIAL_TRIGGER = 0.010
TIER2_MIN_DOWN        = 5
TIER2_TARGET          = 0.020
TIER2_HOLD_DAYS       = 8
TIER3_MIN_DOWN        = 4
TIER3_TARGET          = 0.020
TIER3_HOLD_DAYS       = 8
MIN_CONSEC_DOWN       = TIER3_MIN_DOWN
VELOCITY_CRASH_5D_THRESHOLD = -0.12
VELOCITY_CRASH_PAUSE_DAYS   = 5
EARNINGS_BLACKOUT     = 3
GAP_DOWN_MAX          = -0.010
GAP_UP_MAX            = 0.020
SECTOR_MA_WINDOW      = 20
MAX_SECTOR_POSITIONS  = 3
VIX_LOW               = 25
VIX_SPIKE_PCT         = 0.30
VIX_SPIKE_PAUSE_DAYS  = 0
REENTRY_COOLDOWN_DAYS = 5
COMMISSION_RATE       = 0.005
COMMISSION_MIN        = 0.35
EARNINGS_MONTHS       = {1, 4, 7, 10}
TOP_SIGNAL_PCT        = 0.20
TOP_SIGNAL_MULTIPLIER = 1.30
TOP_SIGNAL_HARD_CAP   = 0.12
MIN_CANDIDATES_FOR_TOP = 5

# ---------------------------------------------------------------------------
# Test-specific parameters
# ---------------------------------------------------------------------------
A_TARGET_K    = 1.80
A_TARGET_MIN  = 0.015
A_TARGET_MAX  = 0.060
A_ATR_WINDOW  = 252
A_HOLD_LOW    = 6
A_HOLD_MID    = 8
A_HOLD_HIGH   = 12

B_TOM_MULT    = 1.15

C_VIX_THRESH  = 15.0
C_RSI_THRESH  = 15.0

D_PARTIAL_TRIGGER = 0.008

E_EARNINGS_BLACKOUT = 5

PUT_COST_PER_QUARTER = 0.015
PUT_LOWER_PCT        = 0.05
PUT_UPPER_PCT        = 0.15
PUT_MAX_PAYOUT_PCT   = 0.10
PUT_RENEW_DAYS       = 63

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
    extras = [
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
    tickers.update(extras)
    result = sorted(tickers)
    print(f"[Universe] Total: {len(result)} tickers")
    return result


# ---------------------------------------------------------------------------
# 2. Downloads
# ---------------------------------------------------------------------------
def download_prices(tickers):
    print(f"\n[Download] {len(tickers)} tickers ({START_DATE} -> {END_DATE})")
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
# 4. TOM window — exact trading-date scan
# ---------------------------------------------------------------------------
def build_tom_set(trading_dates):
    """
    Returns the set of trading dates in the TOM window:
    last trading day of each month + next 3 trading days.
    Uses actual trading date list, no calendar approximation.
    """
    tom = set()
    dates_list = list(trading_dates)
    n = len(dates_list)
    for i, d in enumerate(dates_list):
        ts = pd.Timestamp(d)
        is_month_end = (i == n - 1) or (pd.Timestamp(dates_list[i + 1]).month != ts.month)
        if is_month_end:
            tom.add(d)
            for j in range(1, 4):
                if i + j < n:
                    tom.add(dates_list[i + j])
    return tom


# ---------------------------------------------------------------------------
# 5. Signal generation
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

    df["rsi2"]    = _compute_rsi(df["Close"], RSI_PERIOD)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - df["Close"].shift(1)).abs(),
        (df["Low"]  - df["Close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["atr"]          = tr.rolling(ATR_PERIOD).mean()
    df["atr_pct"]      = df["atr"] / df["Close"]
    df["atr_pct_rank"] = df["atr_pct"].rolling(A_ATR_WINDOW, min_periods=60).rank(pct=True)
    df["vol_ma20"]     = df["Volume"].rolling(VOL_MA_PERIOD).mean()
    df["vol_confirm"]  = df["Volume"] > df["vol_ma20"]
    df["dollar_vol_ma20"] = (df["Close"] * df["Volume"]).rolling(VOL_MA_PERIOD).mean()

    # Signal uses baseline RSI_THRESHOLD=20; per-day tightening happens at runtime
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
# 6. Put spread simulation — FIXED
# ---------------------------------------------------------------------------
def simulate_put_spread(trading_dates, portfolio_by_date, spy_df):
    """
    FIX 1: Use day counter (O(1)) not list.index() (O(n²)).
    FIX 2: Payout fires at RENEWAL TIME based on where SPY is vs the
           opening ref_price. Do NOT reset ref_price after checking —
           the spread pays out at quarterly expiry, period.
    FIX 3: Separate premium payments from payout events cleanly.
    """
    spy_close = spy_df["Close"].squeeze()
    pnl_events    = {}
    premium_total = 0.0
    payout_total  = 0.0
    payout_log    = []

    days_since_renew = 0
    ref_price        = None
    portfolio_at_renew = INITIAL_CAPITAL
    open_spread      = False

    for date in trading_dates:
        if date not in spy_close.index:
            continue
        spy_px   = float(spy_close.loc[date])
        port_val = portfolio_by_date.get(date, INITIAL_CAPITAL)

        if not open_spread or days_since_renew >= PUT_RENEW_DAYS:
            # Close expiring spread: compute payout based on SPY vs ref at quarter open
            if open_spread and ref_price is not None:
                drop = (ref_price - spy_px) / ref_price
                if drop > PUT_LOWER_PCT:
                    payout_frac = min(drop - PUT_LOWER_PCT,
                                      PUT_UPPER_PCT - PUT_LOWER_PCT) / (PUT_UPPER_PCT - PUT_LOWER_PCT)
                    payout = portfolio_at_renew * PUT_MAX_PAYOUT_PCT * payout_frac
                    pnl_events[date] = pnl_events.get(date, 0.0) + payout
                    payout_total += payout
                    payout_log.append(
                        f"{date}: PAYOUT ${payout:,.0f} "
                        f"(ref={ref_price:.2f} -> now={spy_px:.2f}, drop={drop:.1%})"
                    )

            # Open new spread: pay premium
            premium = port_val * PUT_COST_PER_QUARTER
            pnl_events[date] = pnl_events.get(date, 0.0) - premium
            premium_total   += premium
            ref_price        = spy_px
            portfolio_at_renew = port_val
            days_since_renew = 0
            open_spread      = True
        else:
            days_since_renew += 1

    # Final expiry for last open spread
    if open_spread and ref_price is not None and trading_dates:
        last_date = trading_dates[-1]
        if last_date in spy_close.index:
            spy_px = float(spy_close.loc[last_date])
            drop   = (ref_price - spy_px) / ref_price
            if drop > PUT_LOWER_PCT:
                payout_frac = min(drop - PUT_LOWER_PCT,
                                  PUT_UPPER_PCT - PUT_LOWER_PCT) / (PUT_UPPER_PCT - PUT_LOWER_PCT)
                payout = portfolio_at_renew * PUT_MAX_PAYOUT_PCT * payout_frac
                pnl_events[last_date] = pnl_events.get(last_date, 0.0) + payout
                payout_total += payout
                payout_log.append(
                    f"{last_date}: FINAL PAYOUT ${payout:,.0f} "
                    f"(ref={ref_price:.2f} -> now={spy_px:.2f}, drop={drop:.1%})"
                )

    net = payout_total - premium_total
    print(f"  [PutSpread] Premiums: -${premium_total:,.0f} | "
          f"Payouts: +${payout_total:,.0f} | Net: ${net:,.0f}")
    for line in payout_log:
        print(f"    {line}")
    return pnl_events


# ---------------------------------------------------------------------------
# 7. Helpers
# ---------------------------------------------------------------------------
def calc_commission(shares, price):
    return max(shares * COMMISSION_RATE, COMMISSION_MIN)

def get_tier(consec_down, test_id, atr_pct=0.02, atr_rank=0.5):
    if consec_down >= TIER1_MIN_DOWN:
        ptrigger = D_PARTIAL_TRIGGER if test_id in ("D_PARTIAL_TUNE", "G_COMBO_ACD", "H_COMBO_BCD") else TIER1_PARTIAL_TRIGGER
        cfg = {"tier": 1, "profit_target": TIER1_TARGET, "hold_days": TIER1_HOLD_DAYS,
               "partial_enabled": True, "partial_frac": TIER1_PARTIAL_FRAC,
               "partial_trigger": ptrigger}
    elif consec_down >= TIER2_MIN_DOWN:
        cfg = {"tier": 2, "profit_target": TIER2_TARGET, "hold_days": TIER2_HOLD_DAYS,
               "partial_enabled": False, "partial_frac": 0.0, "partial_trigger": TIER2_TARGET}
    else:
        cfg = {"tier": 3, "profit_target": TIER3_TARGET, "hold_days": TIER3_HOLD_DAYS,
               "partial_enabled": False, "partial_frac": 0.0, "partial_trigger": TIER3_TARGET}

    if test_id in ("A_VOL_EXIT", "F_COMBO_ACB", "G_COMBO_ACD"):
        vol_tgt = float(np.clip(atr_pct * A_TARGET_K, A_TARGET_MIN, A_TARGET_MAX))
        cfg["profit_target"] = vol_tgt
        cfg["hold_days"]     = A_HOLD_LOW if atr_rank < 0.25 else (A_HOLD_HIGH if atr_rank > 0.75 else A_HOLD_MID)
        if cfg["partial_enabled"]:
            cfg["partial_trigger"] = vol_tgt * 0.5
    return cfg

def get_position_size(today, vix_df, size_multiplier=1.0):
    month = pd.Timestamp(today).month
    base  = POSITION_SIZE
    try:
        vc = vix_df["Close"].squeeze()
        if today in vc.index and float(vc.loc[today]) < VIX_LOW:
            base = POSITION_SIZE_HIGH
    except Exception:
        pass
    if month in EARNINGS_MONTHS and base > POSITION_SIZE_EARNINGS:
        base = POSITION_SIZE_EARNINGS
    return min(base * size_multiplier, TOP_SIGNAL_HARD_CAP)

def sector_ok(tkr, date, sector_data):
    etf = TICKER_TO_SECTOR.get(tkr)
    if etf is None or etf not in sector_data:
        return True
    df = sector_data[etf]
    return bool(df.loc[date, "ok"]) if date in df.index else True

def count_sector_pos(tkr, open_positions):
    etf = TICKER_TO_SECTOR.get(tkr)
    return 0 if etf is None else sum(1 for t in open_positions if TICKER_TO_SECTOR.get(t) == etf)

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

def get_vix(today, vix_df):
    try:
        vc = vix_df["Close"].squeeze()
        if today in vc.index:
            return float(vc.loc[today])
    except Exception:
        pass
    return 20.0

def near_earnings(tkr, date, earnings_map, blackout_days):
    if tkr not in earnings_map:
        return False
    d = pd.Timestamp(date).normalize()
    return any(abs((d - e).days) <= blackout_days for e in earnings_map[tkr])


# ---------------------------------------------------------------------------
# 8. Core backtest engine
# ---------------------------------------------------------------------------
def run_backtest(price_data, spy_df, vix_df, sector_data, earnings_map,
                 test_id="BASELINE_V35I3"):
    print(f"\n[Backtest] Running {test_id} ...")

    blackout_days = E_EARNINGS_BLACKOUT if test_id == "E_EARNINGS_EXT" else EARNINGS_BLACKOUT

    spy_regime = spy_df["spy_ok"].to_dict()
    all_dates: set = set()
    for df in price_data.values():
        all_dates.update(df.index)
    trading_dates = sorted(all_dates)

    tom_set = build_tom_set(trading_dates) if test_id in ("B_TOM_SIZING", "F_COMBO_ACB", "H_COMBO_BCD") else set()

    # Diagnostic: count low-VIX days for test C
    if test_id in ("C_VIX_RSI", "F_COMBO_ACB", "G_COMBO_ACD", "H_COMBO_BCD"):
        vix_close = vix_df["Close"].squeeze()
        low_vix_days = sum(1 for d in trading_dates
                           if d in vix_close.index and float(vix_close.loc[d]) < C_VIX_THRESH)
        print(f"  VIX < {C_VIX_THRESH} on {low_vix_days} days "
              f"({100*low_vix_days/max(len(trading_dates),1):.1f}% of all trading days)")

    signals = {}
    min_bars = MA_WINDOW + VOL_MA_PERIOD + ATR_PERIOD + MIN_CONSEC_DOWN + 5
    for tkr, df in price_data.items():
        if len(df) > min_bars:
            signals[tkr] = generate_signals(df)

    portfolio_value     = INITIAL_CAPITAL
    portfolio_peak      = None
    open_positions      = {}
    trades              = []
    cooldown_map        = {}
    last_vix_spike      = None
    last_velocity_crash = None
    portfolio_by_date   = {}

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
                if (pd.Timestamp(today) - pd.Timestamp(last_velocity_crash)).days <= VELOCITY_CRASH_PAUSE_DAYS:
                    velocity_paused = True
        except Exception:
            pass

        if portfolio_peak is None:
            if portfolio_value != INITIAL_CAPITAL:
                portfolio_peak = portfolio_value
        else:
            portfolio_peak = max(portfolio_peak, portfolio_value)

        # ---- Exits ----
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
                pnl  = (exit_price - entry_price) * shares_rem - comm - pos["entry_commission"]
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
        vix_now = get_vix(today, vix_df)
        rsi_thresh = (C_RSI_THRESH
                      if test_id in ("C_VIX_RSI", "F_COMBO_ACB", "G_COMBO_ACD", "H_COMBO_BCD")
                      and vix_now < C_VIX_THRESH
                      else RSI_THRESHOLD)
        tom_today = today in tom_set

        candidates = []
        for tkr, tkr_df in signals.items():
            if tkr in open_positions or today not in tkr_df.index:
                continue
            row = tkr_df.loc[today]
            if not row["signal"]:
                continue
            if float(row["rsi2"]) >= rsi_thresh:
                continue
            if tkr in cooldown_map:
                if (pd.Timestamp(today) - pd.Timestamp(cooldown_map[tkr])).days < REENTRY_COOLDOWN_DAYS:
                    continue
            if near_earnings(tkr, today, earnings_map, blackout_days):
                continue
            if not sector_ok(tkr, today, sector_data):
                continue
            if count_sector_pos(tkr, open_positions) >= MAX_SECTOR_POSITIONS:
                continue

            rsi2     = float(row["rsi2"])
            atr_pct  = float(row["atr_pct"])
            score    = rsi2 / atr_pct if atr_pct > 0 else rsi2 * 1000
            atr_rank = float(row.get("atr_pct_rank", 0.5))
            candidates.append((score, tkr, int(row["consec_down"]), rsi2, atr_pct, atr_rank))

        candidates.sort(key=lambda x: x[0])
        n     = len(candidates)
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

            tier_cfg  = get_tier(consec_val, test_id, atr_pct_val, atr_rank)
            size_mult = TOP_SIGNAL_MULTIPLIER if (n >= MIN_CANDIDATES_FOR_TOP and rank < top_n) else 1.0
            if tom_today:
                size_mult *= B_TOM_MULT

            pos_size   = get_position_size(today, vix_df, size_mult)
            shares     = (portfolio_value * pos_size) / entry_price
            entry_comm = calc_commission(shares, entry_price)

            open_positions[tkr] = {
                "entry_date":            tkr_df.index[today_idx + 1],
                "entry_price":           entry_price,
                "shares":                shares,
                "shares_remaining":      shares,
                "rsi2_at_entry":         rsi_val,
                "consec_down_at_entry":  consec_val,
                "profit_target":         tier_cfg["profit_target"],
                "hold_days":             tier_cfg["hold_days"],
                "partial_enabled":       tier_cfg["partial_enabled"],
                "partial_frac":          tier_cfg["partial_frac"],
                "partial_trigger":       tier_cfg["partial_trigger"],
                "partial_done":          False,
                "tier":                  tier_cfg["tier"],
                "entry_commission":      entry_comm,
            }

    print(f"[Backtest] {test_id}: {len(trades)} MR trades")
    trades_df = pd.DataFrame(trades)
    put_pnl   = simulate_put_spread(trading_dates, portfolio_by_date, spy_df) if not trades_df.empty else {}
    return trades_df, put_pnl


# ---------------------------------------------------------------------------
# 9. Metrics
# ---------------------------------------------------------------------------
def compute_metrics(trades_df, put_pnl, test_id):
    if trades_df.empty:
        return {"test": test_id, "error": "No trades"}

    trades_df = trades_df.sort_values("exit_date").reset_index(drop=True)

    # Merge MR + put spread events chronologically
    events = [(str(row["exit_date"]), float(row["pnl_usd"])) for _, row in trades_df.iterrows()]
    for d, pnl in put_pnl.items():
        events.append((str(d), float(pnl)))
    events.sort(key=lambda x: x[0])

    equity = INITIAL_CAPITAL
    eq_rows = []
    for d, pnl in events:
        equity += pnl
        eq_rows.append({"date": d, "equity": equity})

    eq_df = pd.DataFrame(eq_rows)
    eq_df["date"] = pd.to_datetime(eq_df["date"])
    eq_df = eq_df.sort_values("date").reset_index(drop=True)

    final_eq = equity
    start_dt = pd.to_datetime(trades_df["entry_date"].min())
    end_dt   = pd.to_datetime(trades_df["exit_date"].max())
    years    = max((end_dt - start_dt).days / 365.25, 1e-6)
    cagr     = (final_eq / INITIAL_CAPITAL) ** (1 / years) - 1

    winners  = trades_df[trades_df["pnl_usd"] > 0]
    losers   = trades_df[trades_df["pnl_usd"] <= 0]
    win_rate = len(winners) / len(trades_df) * 100

    eq_df["peak"] = eq_df["equity"].cummax()
    eq_df["dd"]   = (eq_df["equity"] - eq_df["peak"]) / eq_df["peak"] * 100
    max_dd = eq_df["dd"].min()

    gp = winners["pnl_usd"].sum()
    gl = abs(losers["pnl_usd"].sum())
    pf = gp / gl if gl > 0 else float("inf")

    eq_dt   = eq_df.set_index("date").sort_index()
    monthly = eq_dt["equity"].resample("ME").last().ffill().pct_change().dropna()
    sharpe  = monthly.mean() / monthly.std() * np.sqrt(12) if monthly.std() > 0 else 0
    down    = monthly[monthly < 0]
    sortino = monthly.mean() / down.std() * np.sqrt(12) if len(down) > 1 and down.std() > 0 else 0

    trades_df["exit_year"] = pd.to_datetime(trades_df["exit_date"]).dt.year
    year_stats = {}
    for yr in sorted(trades_df["exit_year"].unique()):
        y_df = trades_df[trades_df["exit_year"] == yr]
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
        "avg_win_pct":      round(winners["pnl_pct"].mean() if len(winners) else 0, 2),
        "avg_loss_pct":     round(losers["pnl_pct"].mean()  if len(losers)  else 0, 2),
        "avg_days_held":    round(trades_df["days_held"].mean(), 2),
        "put_spread_net":   round(sum(put_pnl.values()), 2),
        "year_stats":       year_stats,
    }


# ---------------------------------------------------------------------------
# 10. Save + print
# ---------------------------------------------------------------------------
TEST_DESCRIPTIONS = {
    "BASELINE_V35I3": "V35 + Idea3 put spread — control (target: 19.71% CAGR, $4,513k, -52.87% MaxDD)",
    "A_VOL_EXIT":     "Vol-adjusted exits: target=1.8xATR (1.5%-6%), hold=6/8/12d by ATR rank",
    "B_TOM_SIZING":   "Turn-of-month sizing: TOM window entries get 1.15x size (Lakonishok 1988)",
    "C_VIX_RSI":      "VIX<15 RSI tightening: require RSI<15 instead of RSI<20",
    "D_PARTIAL_TUNE": "Tier 1 partial trigger 1.0% -> 0.8%",
    "E_EARNINGS_EXT": "Earnings blackout 3 -> 5 days",
    "F_COMBO_ACB":    "Combo: vol exits + VIX RSI tight + TOM sizing",
    "G_COMBO_ACD":    "Combo: vol exits + VIX RSI tight + partial tune",
    "H_COMBO_BCD":    "Combo: TOM sizing + VIX RSI tight + partial tune (no vol exits)",
}

def save_outputs(all_metrics, all_trades):
    for test_id, df in all_trades.items():
        if not df.empty:
            df.to_csv(OUTPUT_DIR / f"trades_{test_id.lower()}.csv", index=False)

    result = {
        "run_date": datetime.date.today().isoformat(),
        "baseline": "V35+I3 (19.71% CAGR, $4,513,155, MaxDD -52.87%, Sharpe 0.74)",
        "suite":    "Ideas V5 (fixed)",
        "tests":    all_metrics,
    }
    with open(OUTPUT_DIR / "comparison.json", "w") as f:
        json.dump(result, f, indent=2, default=str)

    tests_order = ["BASELINE_V35I3","A_VOL_EXIT","B_TOM_SIZING","C_VIX_RSI",
                   "D_PARTIAL_TUNE","E_EARNINGS_EXT","F_COMBO_ACB","G_COMBO_ACD","H_COMBO_BCD"]
    by_test = {m["test"]: m for m in all_metrics}
    col_w   = 20
    n_cols  = sum(1 for t in tests_order if t in by_test)

    KEY = [
        ("cagr_pct",          "CAGR %"),
        ("final_equity",      "Final Equity"),
        ("max_drawdown_pct",  "Max DD %"),
        ("sharpe_ratio",      "Sharpe"),
        ("win_rate_pct",      "Win Rate %"),
        ("profit_factor",     "PF"),
        ("trades_per_year",   "Trades/yr"),
        ("avg_days_held",     "Avg Days"),
        ("put_spread_net",    "Put Net P&L"),
    ]

    print("\n" + "=" * 140)
    print("  IDEAS V5 (FIXED) — RESULTS vs V35+I3 BASELINE")
    print("=" * 140)
    for t in tests_order:
        if t in by_test:
            print(f"  {t:<18} {TEST_DESCRIPTIONS.get(t,'')}")
    print()

    hdr = f"  {'Metric':<22}" + "".join(f"{t:>{col_w}}" for t in tests_order if t in by_test)
    print(hdr)
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
                cell = f"${val:,.0f}" if key in ("final_equity", "put_spread_net") else f"{val:.2f}"
            row += f"{cell:>{col_w}}"
        print(row)

    print("=" * 140)
    print(f"\n  Saved to: {OUTPUT_DIR.resolve()}\n")

    all_years = sorted({yr for m in all_metrics for yr in m.get("year_stats", {}).keys()})
    print("  PER-YEAR P&L (MR trades only)")
    h2 = f"  {'Year':<8}" + "".join(f"{t:>{col_w}}" for t in tests_order if t in by_test)
    print(h2)
    print("  " + "-" * (8 + col_w * n_cols))
    for yr in all_years:
        row = f"  {yr:<8}"
        for t in tests_order:
            ys  = by_test.get(t, {}).get("year_stats", {}).get(yr, {})
            pnl = ys.get("pnl_usd")
            wr  = ys.get("win_rate")
            cell = "—" if pnl is None else f"${pnl:,.0f}({wr}%)"
            row += f"{cell:>{col_w}}"
        print(row)
    print("=" * 140 + "\n")
