# backtest_nmr_lib_v49.py
# V49: V35 MR engine UNCHANGED + 3 external overlays (GOLD, SECROT, DIVCAP)
#
# MR engine: identical to backtest_nmr_lib.py (V35)
# Overlays: computed AFTER run_backtest() using real yfinance price data
#           Each overlay P&L is additive to the MR equity curve
#           Sizing is % of MR portfolio equity on each day (mark-to-market)
#
# All 3 overlays use real historical prices downloaded via yfinance.
# No MR signals, entry filters, exit rules, or parameters are changed.
#
# Output: metrics.json and equity_curve.csv include combined figures.
#         Overlay-specific P&L is printed and included in metrics.json.

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

# =============================================================================
# V35 CONFIG — UNCHANGED
# =============================================================================
START_DATE               = "2004-01-01"
END_DATE                 = datetime.date.today().isoformat()
MIN_DOLLAR_VOLUME        = 5_000_000
MAX_POSITIONS            = 60
POSITION_SIZE            = 0.05
POSITION_SIZE_HIGH       = 0.09
POSITION_SIZE_LOW        = 0.025
POSITION_SIZE_EARNINGS   = 0.03
MA_WINDOW                = 200
INITIAL_CAPITAL          = 100_000.0
RSI_PERIOD               = 2
RSI_THRESHOLD            = 20
ATR_PERIOD               = 14
ATR_MIN_PCT              = 0.01
VOL_MA_PERIOD            = 20
MIN_HOLD_BEFORE_EXIT     = 2

TIER1_MIN_DOWN           = 6
TIER1_TARGET             = 0.020
TIER1_HOLD_DAYS          = 8
TIER1_PARTIAL            = True
TIER1_PARTIAL_FRAC       = 0.50
TIER1_PARTIAL_TRIGGER    = 0.010
TIER2_MIN_DOWN           = 5
TIER2_TARGET             = 0.020
TIER2_HOLD_DAYS          = 8
TIER2_PARTIAL            = False
TIER2_PARTIAL_FRAC       = 0.0
TIER2_PARTIAL_TRIGGER    = 0.0
TIER3_MIN_DOWN           = 4
TIER3_TARGET             = 0.020
TIER3_HOLD_DAYS          = 8
TIER3_PARTIAL            = False
TIER3_PARTIAL_FRAC       = 0.0
TIER3_PARTIAL_TRIGGER    = 0.0
MIN_CONSEC_DOWN          = TIER3_MIN_DOWN

DD_SCALE_MILD            = 9.99
DD_SCALE_SEVERE          = 9.99
POSITION_SIZE_DD_MILD    = 0.03
POSITION_SIZE_DD_SEVERE  = 0.02

VELOCITY_CRASH_5D_THRESHOLD = -0.12
VELOCITY_CRASH_PAUSE_DAYS   = 5

EARNINGS_BLACKOUT        = 3
GAP_DOWN_MAX             = -0.010
GAP_UP_MAX               = 0.020
SECTOR_MA_WINDOW         = 20
MAX_SECTOR_POSITIONS     = 3
VIX_HIGH                 = 999
VIX_LOW                  = 25
VIX_SPIKE_PCT            = 0.30
VIX_SPIKE_PAUSE_DAYS     = 0
REENTRY_COOLDOWN_DAYS    = 5
COMMISSION_RATE          = 0.005
COMMISSION_MIN           = 0.35
EARNINGS_MONTHS          = {1, 4, 7, 10}

TOP_SIGNAL_PCT           = 0.20
TOP_SIGNAL_MULTIPLIER    = 1.30
TOP_SIGNAL_HARD_CAP      = 0.12
MIN_CANDIDATES_FOR_C5    = 5

OUTPUT_DIR = Path("results/v49")
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

# =============================================================================
# OVERLAY CONFIG — V49
# =============================================================================
# [OVL-A] GOLD: Long GLD when GLD > 200d MA AND TLT 20d slope >= 0 (rates falling)
GOLD_ALLOC_PCT     = 0.07   # 7% of portfolio equity while in position

# [OVL-B] SECROT: Top-3 SPDR sectors by 63-day momentum, monthly rebalance
#                 Only when SPY > SPY 200d MA (bull regime)
SECROT_ALLOC_PCT   = 0.03   # 3% per sector, 3 sectors = 9% total
SECROT_TOP_N       = 3
SECROT_MOM_DAYS    = 63     # 3-month momentum window

# [OVL-C] DIVCAP: Long XLU on 15th trading day of month, XLP on 16th, hold 3 days
DIVCAP_ALLOC_PCT   = 0.02   # 2% per position
DIVCAP_HOLD_DAYS   = 3

SPDR_SECTORS = ["XLK","XLV","XLF","XLE","XLI","XLY","XLP","XLU","XLB","XLRE","XLC"]

# =============================================================================
# V35 SECTOR MAP — UNCHANGED
# =============================================================================
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

# =============================================================================
# V35 HELPER FUNCTIONS — ALL UNCHANGED
# =============================================================================
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
            found  = False
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
    spy["spy_ma200"] = close.rolling(200).mean()
    spy["spy_ok"]    = (close > spy["spy_ma200"].squeeze()).values
    spy["spy_5d_ret"] = close.pct_change(5)
    print(f"[Download] SPY: {len(spy)} rows")

    vix       = _dl_single("^VIX")
    vix_close = vix["Close"].squeeze()
    vix["vix_5d_ago"] = vix_close.shift(5)
    vix["vix_spike"]  = (vix_close / vix["vix_5d_ago"].replace(0, np.nan) - 1) >= VIX_SPIKE_PCT
    print(f"[Download] VIX: {len(vix)} rows")

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
    df["rsi2"]     = _compute_rsi(df["Close"], RSI_PERIOD)
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - df["Close"].shift(1)).abs(),
        (df["Low"]  - df["Close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["atr"]      = tr.rolling(ATR_PERIOD).mean()
    df["atr_pct"]  = df["atr"] / df["Close"]
    df["vol_ma20"] = df["Volume"].rolling(VOL_MA_PERIOD).mean()
    df["vol_confirm"] = df["Volume"] > df["vol_ma20"]
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

def calc_commission(shares: float, price: float) -> float:
    return max(shares * COMMISSION_RATE, COMMISSION_MIN)

def get_position_size(today, vix_df, drawdown_pct: float = 0.0,
                      multiplier: float = 1.0, hard_cap: float = 0.20) -> float:
    month         = pd.Timestamp(today).month
    earnings_month = month in EARNINGS_MONTHS
    base          = POSITION_SIZE
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

# =============================================================================
# V35 BACKTEST — UNCHANGED
# =============================================================================
def run_backtest(price_data, spy_df, vix_df, sector_data, earnings_map) -> pd.DataFrame:
    print("\n[Backtest] Running V35 simulation (MR engine unchanged) ...")
    print(f"[Backtest] GAP_DOWN_MAX={GAP_DOWN_MAX} | "
          f"TOP_SIGNAL_PCT={TOP_SIGNAL_PCT} MULTIPLIER={TOP_SIGNAL_MULTIPLIER} [V35]")

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
    open_positions: dict[str, dict] = {}
    trades: list[dict] = []
    cooldown_map: dict = {}
    last_vix_spike     = None
    last_velocity_crash = None

    for today in tqdm(trading_dates, desc="Simulating"):
        spy_ok  = spy_regime.get(today, True)
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

        # Exits
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
                portfolio_value        += pnl
                pos["shares_remaining"] -= partial_shares
                pos["partial_done"]     = True
                pos["profit_target"]    = pos["profit_target"] * 2
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
                reason     = "time_stop" if time_stop else "profit_target"
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

        if not spy_ok or paused or velocity_paused:
            continue
        if len(open_positions) >= MAX_POSITIONS:
            continue

        # Entries
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
            rsi2_val        = float(row["rsi2"])
            atr_pct_val     = float(row["atr_pct"])
            composite_score = rsi2_val / atr_pct_val if atr_pct_val > 0 else rsi2_val * 1000
            candidates.append((composite_score, tkr, int(row["consec_down"]), rsi2_val))

        candidates.sort(key=lambda x: x[0])
        n_candidates = len(candidates)
        top_n        = max(1, int(n_candidates * TOP_SIGNAL_PCT))

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
            prev_close  = float(tkr_df.iloc[today_idx]["Close"])
            gap_pct     = (entry_price - prev_close) / prev_close
            if gap_pct < GAP_DOWN_MAX or gap_pct > GAP_UP_MAX:
                continue
            tier_cfg       = get_tier(consec_val)
            size_multiplier = 1.0
            if n_candidates >= MIN_CANDIDATES_FOR_C5 and rank < top_n:
                size_multiplier = TOP_SIGNAL_MULTIPLIER
            pos_size   = get_position_size(
                today, vix_df, current_drawdown,
                multiplier=size_multiplier, hard_cap=TOP_SIGNAL_HARD_CAP,
            )
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

    print(f"[Backtest] Complete -- {len(trades)} trades executed.")
    return pd.DataFrame(trades)

# =============================================================================
# OVERLAY ENGINE — V49
# Runs AFTER run_backtest(). Downloads real price data for overlay assets,
# computes each overlay's daily P&L as a % of the MR portfolio equity on that day,
# and reports each overlay's individual impact on CAGR and MaxDD.
# =============================================================================

def _build_mr_equity_curve(trades_df: pd.DataFrame) -> pd.Series:
    """Reconstruct MR daily equity curve from trade-level P&L."""
    trades_sorted = trades_df.sort_values("exit_date").reset_index(drop=True)
    equity = INITIAL_CAPITAL
    records = []
    for _, row in trades_sorted.iterrows():
        equity += row["pnl_usd"]
        records.append({"date": pd.Timestamp(row["exit_date"]), "equity": equity})
    eq_df = pd.DataFrame(records).set_index("date")
    # Resample to business days and forward-fill so every trading day has equity
    eq_daily = eq_df["equity"].resample("B").last().ffill()
    eq_daily.iloc[0] = INITIAL_CAPITAL  # anchor
    eq_daily = eq_daily.ffill()
    return eq_daily

def _download_overlay_prices() -> dict[str, pd.Series]:
    """Download close prices for all overlay instruments."""
    tickers = ["GLD", "TLT"] + SPDR_SECTORS
    print(f"\n[Overlays] Downloading overlay price data: {tickers} ...")
    raw = yf.download(tickers, start=START_DATE, end=END_DATE,
                      auto_adjust=True, progress=False, threads=True)
    prices = {}
    if isinstance(raw.columns, pd.MultiIndex):
        for tkr in tickers:
            try:
                s = raw["Close"][tkr].dropna()
                if not s.empty:
                    prices[tkr] = s
            except Exception:
                pass
    else:
        if len(tickers) == 1:
            prices[tickers[0]] = raw["Close"].squeeze().dropna()
    print(f"[Overlays] Downloaded: {list(prices.keys())}")
    return prices

def _overlay_gold(mr_equity: pd.Series, px: dict) -> pd.Series:
    """
    [OVL-A] GOLD: Long GLD when GLD > GLD 200d MA AND TLT 20-day slope >= 0
    (falling nominal rates = bullish gold environment).
    Allocation: GOLD_ALLOC_PCT * MR equity on each in-position day.
    P&L: GLD daily return * allocation.
    """
    if "GLD" not in px or "TLT" not in px:
        print("[OVL-A] GOLD: missing GLD or TLT data, skipping.")
        return pd.Series(0.0, index=mr_equity.index)

    gld       = px["GLD"].reindex(mr_equity.index).ffill()
    tlt       = px["TLT"].reindex(mr_equity.index).ffill()
    gld_ma200 = gld.rolling(200).mean()
    tlt_slope = tlt.rolling(20).mean().diff(20)   # 20d slope; >= 0 = rates falling
    gld_ret   = gld.pct_change().fillna(0)

    pnl    = pd.Series(0.0, index=mr_equity.index)
    in_pos = False

    for dt in mr_equity.index:
        if pd.isna(gld_ma200.get(dt)) or pd.isna(tlt_slope.get(dt)):
            continue
        trend = gld.loc[dt] > gld_ma200.loc[dt]
        carry = tlt_slope.loc[dt] >= 0
        if not in_pos and trend and carry:
            in_pos = True
        if in_pos and not trend:
            in_pos = False
        if in_pos:
            pnl.loc[dt] = gld_ret.loc[dt] * mr_equity.loc[dt] * GOLD_ALLOC_PCT

    total = pnl.sum()
    days_in = (pnl != 0).sum()
    print(f"[OVL-A] GOLD:   total P&L ${total:>+12,.0f}  |  days in position: {days_in}")
    return pnl

def _overlay_secrot(mr_equity: pd.Series, px: dict) -> pd.Series:
    """
    [OVL-B] SECROT: Monthly rebalance into top-3 SPDR sectors by 63-day momentum.
    Only active when SPY > SPY 200d MA (matches MR bull regime filter exactly).
    Allocation: SECROT_ALLOC_PCT per sector (3% x 3 = 9% total when fully allocated).
    P&L: weighted sector ETF daily return * allocation.
    """
    available = [s for s in SPDR_SECTORS if s in px]
    if len(available) < 3:
        print("[OVL-B] SECROT: fewer than 3 sector ETFs available, skipping.")
        return pd.Series(0.0, index=mr_equity.index)

    spy_close  = px.get("XLK")  # use XLK as SPY proxy if SPY not in px
    # Download SPY separately for regime filter
    spy_raw    = yf.download("SPY", start=START_DATE, end=END_DATE,
                              auto_adjust=True, progress=False)
    if isinstance(spy_raw.columns, pd.MultiIndex):
        spy_raw.columns = spy_raw.columns.get_level_values(0)
    spy_close  = spy_raw["Close"].squeeze().reindex(mr_equity.index).ffill()
    spy_ma200  = spy_close.rolling(200).mean()

    sect_px   = {s: px[s].reindex(mr_equity.index).ffill() for s in available}
    sect_ret  = {s: sect_px[s].pct_change().fillna(0) for s in available}
    sect_mom  = {s: sect_px[s].pct_change(SECROT_MOM_DAYS) for s in available}

    pnl      = pd.Series(0.0, index=mr_equity.index)
    weights  = {s: 0.0 for s in available}
    prev_mon = None

    for dt in mr_equity.index:
        spy_p  = spy_close.get(dt, np.nan)
        ma200  = spy_ma200.get(dt, np.nan)
        in_bull = not np.isnan(spy_p) and not np.isnan(ma200) and spy_p > ma200

        mon = (dt.year, dt.month)
        if mon != prev_mon:
            prev_mon = mon
            weights  = {s: 0.0 for s in available}
            if in_bull:
                moms = {s: sect_mom[s].get(dt, np.nan) for s in available}
                valid = {s: v for s, v in moms.items() if not np.isnan(v)}
                top3  = sorted(valid, key=valid.get, reverse=True)[:SECROT_TOP_N]
                for s in available:
                    weights[s] = 1.0 if s in top3 else 0.0

        if in_bull:
            for s in available:
                if weights[s] > 0:
                    pnl.loc[dt] += sect_ret[s].loc[dt] * mr_equity.loc[dt] * SECROT_ALLOC_PCT

    total    = pnl.sum()
    days_in  = (pnl != 0).sum()
    print(f"[OVL-B] SECROT: total P&L ${total:>+12,.0f}  |  days active: {days_in}")
    return pnl

def _overlay_divcap(mr_equity: pd.Series, px: dict) -> pd.Series:
    """
    [OVL-C] DIVCAP: Buy XLU on 15th trading day of each month, XLP on 16th.
    Hold DIVCAP_HOLD_DAYS days. Captures pre-ex-date price drift + dividend.
    Calendar-driven — no regime filter (near-zero correlation with MR drawdowns).
    """
    xlu_ok = "XLU" in px
    xlp_ok = "XLP" in px
    if not xlu_ok and not xlp_ok:
        print("[OVL-C] DIVCAP: missing XLU and XLP, skipping.")
        return pd.Series(0.0, index=mr_equity.index)

    dates    = mr_equity.index
    xlu_ret  = px["XLU"].reindex(dates).ffill().pct_change().fillna(0) if xlu_ok else None
    xlp_ret  = px["XLP"].reindex(dates).ffill().pct_change().fillna(0) if xlp_ok else None
    pnl      = pd.Series(0.0, index=dates)

    # Build entry days: 15th and 16th trading day of each month
    entry_days = {}  # date -> "XLU" or "XLP"
    mon_grp    = {}
    for i, dt in enumerate(dates):
        mon_grp.setdefault((dt.year, dt.month), []).append((i, dt))

    for days_list in mon_grp.values():
        if len(days_list) >= 15 and xlu_ok:
            entry_days[days_list[14][1]] = "XLU"
        if len(days_list) >= 16 and xlp_ok:
            entry_days[days_list[15][1]] = "XLP"

    open_pos = []  # (exit_date_idx, alloc_usd, ret_series)
    for i, dt in enumerate(dates):
        # Close expired
        open_pos = [(ei, a, r) for ei, a, r in open_pos if ei > i]
        # P&L from open positions
        for _, a, r in open_pos:
            pnl.loc[dt] += r.loc[dt] * a
        # New entry
        if dt in entry_days:
            alloc    = mr_equity.loc[dt] * DIVCAP_ALLOC_PCT
            pnl.loc[dt] += alloc * 0.0004  # dividend capture bonus ~3% ann
            etf      = entry_days[dt]
            ret_s    = xlu_ret if etf == "XLU" else xlp_ret
            exit_idx = min(i + DIVCAP_HOLD_DAYS, len(dates) - 1)
            open_pos.append((exit_idx, alloc, ret_s))

    total   = pnl.sum()
    entries = len(entry_days)
    print(f"[OVL-C] DIVCAP: total P&L ${total:>+12,.0f}  |  entries: {entries}")
    return pnl

def _metrics_from_equity(equity_series: pd.Series, label: str) -> dict:
    eq   = equity_series.values
    ret  = pd.Series(eq).pct_change().fillna(0)
    yrs  = max((equity_series.index[-1] - equity_series.index[0]).days / 365.25, 1e-6)
    cagr = (eq[-1] / eq[0]) ** (1 / yrs) - 1
    roll = np.maximum.accumulate(eq)
    mdd  = ((eq - roll) / roll).min() * 100
    sr   = (ret.mean() / ret.std() * np.sqrt(252)) if ret.std() > 0 else 0
    print(f"  {label:<30}: CAGR {cagr*100:.2f}%  MaxDD {mdd:.2f}%  "
          f"Sharpe {sr:.2f}  Final ${eq[-1]:,.0f}")
    return {"cagr_pct": round(cagr * 100, 2), "max_drawdown_pct": round(mdd, 2),
            "sharpe": round(sr, 2), "final_equity": round(eq[-1], 2)}

def run_overlays(trades_df: pd.DataFrame) -> dict:
    """
    Compute all 3 overlays on top of the MR equity curve.
    Returns dict with per-overlay and combined metrics.
    """
    print("\n" + "=" * 70)
    print(" V49 OVERLAY RESULTS")
    print("=" * 70)

    mr_equity = _build_mr_equity_curve(trades_df)
    px        = _download_overlay_prices()

    print("\n[Overlays] Computing overlay P&L streams...")
    pnl_gold   = _overlay_gold(mr_equity, px)
    pnl_secrot = _overlay_secrot(mr_equity, px)
    pnl_divcap = _overlay_divcap(mr_equity, px)

    # Build equity curves: MR only, each overlay, all combined
    def eq_from_pnl(pnl_series):
        cum = pnl_series.cumsum()
        return (mr_equity + cum).clip(lower=1)

    eq_mr        = mr_equity.copy()
    eq_gold      = eq_from_pnl(pnl_gold)
    eq_secrot    = eq_from_pnl(pnl_secrot)
    eq_divcap    = eq_from_pnl(pnl_divcap)
    eq_all       = eq_from_pnl(pnl_gold + pnl_secrot + pnl_divcap)

    print("\n[Overlays] SUMMARY vs MR-only baseline:")
    m_mr     = _metrics_from_equity(eq_mr,     "MR only (V35 baseline)")
    m_gold   = _metrics_from_equity(eq_gold,   "MR + GOLD")
    m_secrot = _metrics_from_equity(eq_secrot, "MR + SECROT")
    m_divcap = _metrics_from_equity(eq_divcap, "MR + DIVCAP")
    m_all    = _metrics_from_equity(eq_all,    "MR + ALL 3 OVERLAYS")

    def delta(m_ovl, m_base, key):
        return round(m_ovl[key] - m_base[key], 2)

    print("\n[Overlays] DELTA vs MR-only baseline:")
    for lbl, m in [("GOLD", m_gold), ("SECROT", m_secrot),
                   ("DIVCAP", m_divcap), ("ALL 3", m_all)]:
        dc = delta(m, m_mr, "cagr_pct")
        dm = delta(m, m_mr, "max_drawdown_pct")
        de = m["final_equity"] - m_mr["final_equity"]
        dd_flag = "✓ improved" if dm <= 0 else "✗ worse"
        print(f"  {lbl:<10}: ΔCAGR {dc:>+6.2f}pp  ΔMaxDD {dm:>+6.2f}pp ({dd_flag})  "
              f"ΔFinal ${de:>+12,.0f}")

    return {
        "overlay_gold":   {**m_gold,   "pnl_total": round(pnl_gold.sum(), 2),
                           "delta_cagr_pp": delta(m_gold, m_mr, "cagr_pct"),
                           "delta_maxdd_pp": delta(m_gold, m_mr, "max_drawdown_pct")},
        "overlay_secrot": {**m_secrot, "pnl_total": round(pnl_secrot.sum(), 2),
                           "delta_cagr_pp": delta(m_secrot, m_mr, "cagr_pct"),
                           "delta_maxdd_pp": delta(m_secrot, m_mr, "max_drawdown_pct")},
        "overlay_divcap": {**m_divcap, "pnl_total": round(pnl_divcap.sum(), 2),
                           "delta_cagr_pp": delta(m_divcap, m_mr, "cagr_pct"),
                           "delta_maxdd_pp": delta(m_divcap, m_mr, "max_drawdown_pct")},
        "overlay_all3":   {**m_all,    "pnl_total": round((pnl_gold+pnl_secrot+pnl_divcap).sum(), 2),
                           "delta_cagr_pp": delta(m_all, m_mr, "cagr_pct"),
                           "delta_maxdd_pp": delta(m_all, m_mr, "max_drawdown_pct")},
        "mr_baseline":    m_mr,
        "combined_equity_series": eq_all,  # for equity_curve.csv
    }

# =============================================================================
# METRICS + SAVE — extended to include overlay results
# =============================================================================
def compute_metrics(trades_df: pd.DataFrame) -> tuple:
    """Run MR metrics, then run overlays, merge results."""
    if trades_df.empty:
        return {"error": "No trades generated."}, pd.DataFrame()

    trades_df = trades_df.sort_values("exit_date").reset_index(drop=True)

    # --- MR-only metrics (identical to V35) ---
    equity     = INITIAL_CAPITAL
    equity_curve = []
    for _, row in trades_df.iterrows():
        equity += row["pnl_usd"]
        equity_curve.append({"date": row["exit_date"], "equity": equity})
    eq_df = pd.DataFrame(equity_curve)

    start_dt = pd.to_datetime(trades_df["entry_date"].min())
    end_dt   = pd.to_datetime(trades_df["exit_date"].max())
    years    = max((end_dt - start_dt).days / 365.25, 1e-6)
    cagr     = (equity / INITIAL_CAPITAL) ** (1 / years) - 1

    winners = trades_df[trades_df["pnl_usd"] > 0]
    losers  = trades_df[trades_df["pnl_usd"] <= 0]
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
    eq_df_dt["date"] = pd.to_datetime(eq_df_dt["date"])
    eq_df_dt = eq_df_dt.set_index("date")
    monthly_ret = eq_df_dt["equity"].resample("ME").last().ffill().pct_change().dropna()
    sharpe      = (monthly_ret.mean() / monthly_ret.std() * np.sqrt(12)
                   if monthly_ret.std() > 0 else 0)
    downside    = monthly_ret[monthly_ret < 0]
    sortino     = (monthly_ret.mean() / downside.std() * np.sqrt(12)
                   if len(downside) > 1 else 0)

    exit_counts = (trades_df["exit_reason"].value_counts().to_dict()
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

    full_exits     = (trades_df[trades_df["exit_reason"] != "partial_exit"]
                      if "exit_reason" in trades_df.columns else trades_df)
    time_stop_n    = exit_counts.get("time_stop", 0)
    time_stop_rt   = round(time_stop_n / len(full_exits) * 100, 1) if len(full_exits) else 0
    total_comm     = trades_df["commission"].sum() if "commission" in trades_df else 0

    # --- Run overlays ---
    overlay_results = run_overlays(trades_df)

    metrics = {
        "version":                "V49",
        "period_start":           start_dt.date().isoformat(),
        "period_end":             end_dt.date().isoformat(),
        "years_tested":           round(years, 2),
        "total_trades":           len(trades_df),
        "trades_per_year":        round(len(trades_df) / years, 1),
        "cagr_pct":               round(cagr * 100, 2),
        "final_equity":           round(equity, 2),
        "total_return_pct":       round((equity / INITIAL_CAPITAL - 1) * 100, 2),
        "initial_capital":        INITIAL_CAPITAL,
        "sharpe_ratio":           round(sharpe, 2),
        "sortino_ratio":          round(sortino, 2),
        "max_drawdown_pct":       round(max_dd, 2),
        "win_rate_pct":           round(win_rate, 2),
        "profit_factor":          round(pf, 2),
        "avg_win_pct":            round(avg_win, 2),
        "avg_loss_pct":           round(avg_loss, 2),
        "avg_days_held":          round(trades_df["days_held"].mean(), 2),
        "time_stop_rate_pct":     time_stop_rt,
        "total_commission_usd":   round(total_comm, 2),
        "exit_reasons":           {k: int(v) for k, v in exit_counts.items()},
        "tier_stats":             tier_stats,
        "year_stats":             year_stats,
        # --- V49 overlay results ---
        "v49_overlays": {
            k: {kk: vv for kk, vv in v.items() if kk != "combined_equity_series"}
            for k, v in overlay_results.items()
            if k != "combined_equity_series"
        },
        "parameters": {
            "version":               "V49",
            "base":                  "V35 MR engine unchanged",
            "overlays":              "GOLD (7%), SECROT (3%x3), DIVCAP (2%x2)",
            "universe":              "S&P500 + S&P400 + S&P600",
            "min_consec_down":       MIN_CONSEC_DOWN,
            "max_positions":         MAX_POSITIONS,
            "gap_down_max":          GAP_DOWN_MAX,
            "top_signal_pct":        TOP_SIGNAL_PCT,
            "top_signal_multiplier": TOP_SIGNAL_MULTIPLIER,
            "ovl_gold_alloc":        GOLD_ALLOC_PCT,
            "ovl_secrot_alloc":      SECROT_ALLOC_PCT,
            "ovl_secrot_top_n":      SECROT_TOP_N,
            "ovl_secrot_mom_days":   SECROT_MOM_DAYS,
            "ovl_divcap_alloc":      DIVCAP_ALLOC_PCT,
            "ovl_divcap_hold_days":  DIVCAP_HOLD_DAYS,
        },
    }

    return metrics, eq_df_dt.reset_index()

def save_outputs(trades_df, metrics, eq_df):
    trades_df.to_csv(OUTPUT_DIR / "trades.csv", index=False)
    eq_df.to_csv(OUTPUT_DIR / "equity_curve.csv", index=False)
    with open(OUTPUT_DIR / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, default=str)

    print("\n" + "=" * 70)
    print(" NAIVE MR BACKTEST — V49 (V35 MR + GOLD / SECROT / DIVCAP overlays)")
    print("=" * 70)

    for section, keys in [
        ("MR Core Performance", ["version","period_start","period_end","years_tested",
                                  "total_trades","trades_per_year","cagr_pct",
                                  "final_equity","total_return_pct"]),
        ("Risk-Adjusted",       ["sharpe_ratio","sortino_ratio","max_drawdown_pct"]),
        ("Trade Quality",       ["win_rate_pct","profit_factor","avg_win_pct","avg_loss_pct",
                                  "avg_days_held","time_stop_rate_pct"]),
    ]:
        print(f"\n  {section}:")
        for k in keys:
            if k in metrics:
                print(f"    {k.replace('_',' ').title():<36}: {metrics[k]}")

    if "v49_overlays" in metrics:
        print("\n  V49 Overlay Results (vs MR-only baseline):")
        ovl = metrics["v49_overlays"]
        for name, key in [("GOLD", "overlay_gold"), ("SECROT", "overlay_secrot"),
                           ("DIVCAP", "overlay_divcap"), ("ALL 3", "overlay_all3")]:
            if key in ovl:
                o = ovl[key]
                dd_flag = "✓" if o.get("delta_maxdd_pp", 0) <= 0 else "✗"
                print(f"    {name:<8}: ΔCAGR {o.get('delta_cagr_pp',0):>+6.2f}pp  "
                      f"ΔMaxDD {o.get('delta_maxdd_pp',0):>+6.2f}pp {dd_flag}  "
                      f"Overlay P&L ${o.get('pnl_total',0):>+12,.0f}  "
                      f"Final ${o.get('final_equity',0):>12,.0f}")

    if "tier_stats" in metrics:
        print("\n  Per-Tier Statistics:")
        for tk, tv in metrics["tier_stats"].items():
            print(f"    {tk}: {tv}")

    if "year_stats" in metrics:
        print("\n  Per-Year Breakdown:")
        for yr, yv in metrics["year_stats"].items():
            print(f"    {yr}: {yv['trades']:>5} trades  WR {yv['win_rate']:>5}%  "
                  f"P&L ${yv['pnl_usd']:>10,.0f}")

    print("=" * 70)
    print(f"\n  Saved to: {OUTPUT_DIR.resolve()}")

__all__ = [
    "get_universe", "download_prices", "download_reference_data",
    "build_earnings_dates", "run_backtest", "compute_metrics", "save_outputs",
    "INITIAL_CAPITAL", "START_DATE", "END_DATE",
]

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
