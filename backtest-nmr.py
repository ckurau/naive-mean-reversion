"""
Enhanced Naive Mean Reversion (MR) Backtest — V5
==================================================
Base Rules:
  - Universe : S&P 500 + S&P 400 MidCap (current + historical)
  - Buy      : Stock > 200-day MA AND 4 consecutive down days -> buy next open
  - Sell     : Tiered profit target OR time stop (5 days)
  - Portfolio: Max 30 simultaneous positions, VIX-adjusted sizing

V5 Changes vs V4:
  [Fixed]   Time stop 10d -> 5d          (free capital faster)
  [Fixed]   Sector MA 50d -> 20d         (faster sector trend detection)
  [New]     Tiered profit exit            (RSI<5->2%, RSI<10->1.5%, else->1%)
  [New]     Partial exits (50/50)         (lock profit, let rest run to 2x target)
  [New]     Max 30 positions              (more compounding)
  [New]     Re-entry filter (5d cooldown) (no re-entry after time stop)
  [New]     Dollar volume filter $5M      (liquidity screen replaces price filter)
  [New]     Gap-up skip >2%              (don't buy after overnight bounce)
  [New]     3-down-days if RSI(2)<5      (catch most extreme setups earlier)
  [New]     Earnings season size cut 3%  (Jan/Apr/Jul/Oct peak months)
  [New]     VIX spike pause (2 days)     (pause entries after VIX +30% in 5d)
  [New]     Correlation cap 3/sector     (max 3 open positions per sector)
"""

import io
import warnings
import datetime
import json
from collections import defaultdict
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
START_DATE              = "2004-01-01"
END_DATE                = datetime.date.today().isoformat()
MIN_DOLLAR_VOLUME       = 5_000_000   # $5M avg daily dollar volume
MAX_POSITIONS           = 30          # increased from 20
POSITION_SIZE           = 0.05        # base 5%
POSITION_SIZE_HIGH      = 0.075       # 7.5% when VIX < 15
POSITION_SIZE_LOW       = 0.025       # 2.5% when VIX > 25
POSITION_SIZE_EARNINGS  = 0.03        # 3% during peak earnings months
MA_WINDOW               = 200
CONSEC_DOWN_NORMAL      = 4           # standard requirement
CONSEC_DOWN_EXTREME     = 3           # if RSI(2) < 5, only need 3 down days
INITIAL_CAPITAL         = 100_000.0

RSI_PERIOD              = 2
RSI_THRESHOLD           = 20          # entry filter
RSI_EXTREME             = 5           # triggers 3-down-day rule + 2% target
RSI_MODERATE            = 10          # triggers 1.5% target
ATR_PERIOD              = 14
ATR_MIN_PCT             = 0.01
VOL_MA_PERIOD           = 20
MAX_HOLD_DAYS           = 5           # time stop (down from 10)
EARNINGS_BLACKOUT       = 3
GAP_DOWN_MAX            = -0.015      # skip entry if gap down > 1.5%
GAP_UP_MAX              = 0.02        # skip entry if gap up > 2% (bounced already)
SECTOR_MA_WINDOW        = 20          # sector trend filter (down from 50)
MAX_SECTOR_POSITIONS    = 3           # correlation cap
VIX_HIGH                = 25
VIX_LOW                 = 15
VIX_SPIKE_PCT           = 0.30        # pause entries if VIX up 30% in 5 days
VIX_SPIKE_PAUSE_DAYS    = 2           # pause duration after spike
REENTRY_COOLDOWN_DAYS   = 5           # no re-entry N days after time stop
COMMISSION_RATE         = 0.005
COMMISSION_MIN          = 1.00
EARNINGS_MONTHS         = {1, 4, 7, 10}  # peak earnings months

# Tiered profit targets based on RSI(2) at entry
PROFIT_TARGET_EXTREME   = 0.020       # RSI < 5  -> 2% target
PROFIT_TARGET_MODERATE  = 0.015       # RSI < 10 -> 1.5% target
PROFIT_TARGET_NORMAL    = 0.010       # RSI < 20 -> 1% target

# Partial exit: sell PARTIAL_EXIT_FRACTION at first target, rest at 2x target
PARTIAL_EXIT_FRACTION   = 0.50

OUTPUT_DIR              = Path("results")
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
    vix_close = vix["Close"].squeeze()
    vix["vix_ma5"]       = vix_close.rolling(5).mean()
    vix["vix_5d_ago"]    = vix_close.shift(5)
    vix["vix_spike"]     = (vix_close / vix["vix_5d_ago"].replace(0, np.nan) - 1) >= VIX_SPIKE_PCT
    print(f"[Download] VIX: {len(vix)} rows")

    # Sector ETFs
    etf_list    = list(SECTOR_ETFS.keys())
    sector_data : dict[str, pd.DataFrame] = {}
    raw = yf.download(etf_list, start=START_DATE, end=END_DATE,
                      auto_adjust=True, progress=False, threads=True)
    if not raw.empty:
        for etf in etf_list:
            try:
                df = raw.xs(etf, axis=1, level=1).dropna(how="all") \
                     if isinstance(raw.columns, pd.MultiIndex) else raw.copy()
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
    print(f"[Earnings] Done: {len(earnings_map)} tickers with dates.")
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

    # Trend
    df["ma200"]    = df["Close"].rolling(MA_WINDOW).mean()
    df["above_ma"] = df["Close"] > df["ma200"]

    # Consecutive down days
    df["down_day"] = (df["Close"] < df["Close"].shift(1)).astype(int)
    consec, count = [], 0
    for d in df["down_day"]:
        count = count + 1 if d == 1 else 0
        consec.append(count)
    df["consec_down"] = consec

    # RSI(2)
    df["rsi2"] = compute_rsi(df["Close"], RSI_PERIOD)

    # ATR
    tr = pd.concat([
        df["High"] - df["Low"],
        (df["High"] - df["Close"].shift(1)).abs(),
        (df["Low"]  - df["Close"].shift(1)).abs(),
    ], axis=1).max(axis=1)
    df["atr"]     = tr.rolling(ATR_PERIOD).mean()
    df["atr_pct"] = df["atr"] / df["Close"]

    # Volume
    df["vol_ma20"]    = df["Volume"].rolling(VOL_MA_PERIOD).mean()
    df["vol_confirm"] = df["Volume"] > df["vol_ma20"]

    # Dollar volume (liquidity filter — replaces simple price filter)
    df["dollar_vol"]     = df["Close"] * df["Volume"]
    df["dollar_vol_ma20"] = df["dollar_vol"].rolling(VOL_MA_PERIOD).mean()

    # Tiered down-day requirement: extreme RSI only needs 3 down days
    df["consec_req"] = df["rsi2"].apply(
        lambda r: CONSEC_DOWN_EXTREME if r < RSI_EXTREME else CONSEC_DOWN_NORMAL
    )

    # Composite signal
    df["signal"] = (
        df["above_ma"]                                    &
        (df["consec_down"] >= df["consec_req"])           &
        (df["rsi2"] < RSI_THRESHOLD)                      &
        (df["atr_pct"] > ATR_MIN_PCT)                     &
        df["vol_confirm"]                                 &
        (df["dollar_vol_ma20"] >= MIN_DOLLAR_VOLUME)
    )
    return df


# ─────────────────────────────────────────────────────────────────────────────
# 5.  Helpers
# ─────────────────────────────────────────────────────────────────────────────
def calc_commission(shares: float, price: float) -> float:
    return max(shares * COMMISSION_RATE, COMMISSION_MIN)


def get_profit_target(rsi_at_entry: float) -> tuple[float, float]:
    """Return (first_target, second_target) based on RSI at entry."""
    if rsi_at_entry < RSI_EXTREME:
        first  = PROFIT_TARGET_EXTREME      # 2%
        second = PROFIT_TARGET_EXTREME * 2  # 4%
    elif rsi_at_entry < RSI_MODERATE:
        first  = PROFIT_TARGET_MODERATE     # 1.5%
        second = PROFIT_TARGET_MODERATE * 2 # 3%
    else:
        first  = PROFIT_TARGET_NORMAL       # 1%
        second = PROFIT_TARGET_NORMAL * 2   # 2%
    return first, second


def get_position_size(today, vix_df: pd.DataFrame) -> float:
    """VIX-adjusted position size, with earnings-month reduction."""
    month = pd.Timestamp(today).month
    earnings_month = month in EARNINGS_MONTHS

    try:
        vc = vix_df["Close"].squeeze()
        if today in vc.index:
            v = float(vc.loc[today])
            if v > VIX_HIGH:
                base = POSITION_SIZE_LOW
            elif v < VIX_LOW:
                base = POSITION_SIZE_HIGH
            else:
                base = POSITION_SIZE
            # Further reduce during earnings months
            return POSITION_SIZE_EARNINGS if earnings_month and base > POSITION_SIZE_EARNINGS else base
    except Exception:
        pass
    return POSITION_SIZE_EARNINGS if earnings_month else POSITION_SIZE


def sector_ok(tkr: str, date, sector_data: dict[str, pd.DataFrame]) -> bool:
    etf = TICKER_TO_SECTOR.get(tkr)
    if etf is None or etf not in sector_data:
        return True
    df = sector_data[etf]
    if date not in df.index:
        return True
    return bool(df.loc[date, "ok"])


def count_sector_positions(tkr: str, open_positions: dict) -> int:
    """Count how many open positions share the same sector as tkr."""
    etf = TICKER_TO_SECTOR.get(tkr)
    if etf is None:
        return 0
    return sum(1 for t in open_positions if TICKER_TO_SECTOR.get(t) == etf)


def vix_spike_active(today, vix_df: pd.DataFrame,
                     last_spike_date) -> tuple[bool, object]:
    """Returns (pause_active, updated_last_spike_date)."""
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
# 6.  Backtest
# ─────────────────────────────────────────────────────────────────────────────
def run_backtest(price_data, spy_df, vix_df, sector_data, earnings_map) -> pd.DataFrame:
    print("\n[Backtest] Running V5 simulation ...")
    spy_regime = spy_df["spy_ok"].to_dict()

    all_dates: set = set()
    for df in price_data.values():
        all_dates.update(df.index)
    trading_dates = sorted(all_dates)

    signals: dict[str, pd.DataFrame] = {}
    min_bars = MA_WINDOW + VOL_MA_PERIOD + ATR_PERIOD + CONSEC_DOWN_NORMAL + 5
    for tkr, df in tqdm(price_data.items(), desc="Generating signals"):
        if len(df) > min_bars:
            signals[tkr] = generate_signals(df)

    portfolio_value  = INITIAL_CAPITAL
    # open_positions: tkr -> {entry_date, entry_price, shares, shares_remaining,
    #                          rsi2_at_entry, first_target, second_target,
    #                          partial_done, entry_commission}
    open_positions: dict[str, dict] = {}
    trades: list[dict] = []
    # re-entry cooldown: tkr -> date of last time_stop exit
    cooldown_map: dict[str, object] = {}
    last_vix_spike = None

    for today in tqdm(trading_dates, desc="Simulating"):
        spy_ok = spy_regime.get(today, True)

        # Update VIX spike tracker
        paused, last_vix_spike = vix_spike_active(today, vix_df, last_vix_spike)

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
            prev_close  = float(tkr_df.iloc[prev_idx - 1]["Close"])
            days_held   = (pd.Timestamp(today) - pd.Timestamp(pos["entry_date"])).days
            exit_price  = float(row["Close"])
            entry_price = pos["entry_price"]
            shares_rem  = pos["shares_remaining"]

            pos_pct     = (exit_price - entry_price) / entry_price
            up_pct      = (exit_price - prev_close) / prev_close
            time_stop   = days_held >= MAX_HOLD_DAYS

            # Partial exit: first target hit and not yet done
            if not pos["partial_done"] and pos_pct >= pos["first_target"]:
                partial_shares = shares_rem * PARTIAL_EXIT_FRACTION
                commission     = calc_commission(partial_shares, exit_price)
                pnl            = (exit_price - entry_price) * partial_shares - commission
                pnl_pct        = pos_pct * 100
                trades.append({
                    "ticker"       : tkr,
                    "entry_date"   : pos["entry_date"],
                    "exit_date"    : today,
                    "entry_price"  : entry_price,
                    "exit_price"   : exit_price,
                    "shares"       : partial_shares,
                    "commission"   : round(commission, 4),
                    "pnl_usd"      : pnl,
                    "pnl_pct"      : pnl_pct,
                    "days_held"    : days_held,
                    "exit_reason"  : "partial_exit",
                    "portfolio_val": portfolio_value + pnl,
                })
                portfolio_value      += pnl
                pos["shares_remaining"] -= partial_shares
                pos["partial_done"]   = True
                continue  # stay in position with remaining shares

            # Full exit: second target, time stop, or first up-day (if partial done)
            full_exit = (
                time_stop or
                (pos["partial_done"] and pos_pct >= pos["second_target"]) or
                (pos["partial_done"] and up_pct >= PROFIT_TARGET_NORMAL)
            )
            if full_exit:
                commission = calc_commission(shares_rem, exit_price)
                # Allocate entry commission to this leg
                pnl        = (exit_price - entry_price) * shares_rem - commission - pos.get("entry_commission", 0)
                pnl_pct    = pos_pct * 100
                reason     = "time_stop" if time_stop else "profit_target"
                trades.append({
                    "ticker"       : tkr,
                    "entry_date"   : pos["entry_date"],
                    "exit_date"    : today,
                    "entry_price"  : entry_price,
                    "exit_price"   : exit_price,
                    "shares"       : shares_rem,
                    "commission"   : round(commission, 4),
                    "pnl_usd"      : pnl,
                    "pnl_pct"      : pnl_pct,
                    "days_held"    : days_held,
                    "exit_reason"  : reason,
                    "portfolio_val": portfolio_value + pnl,
                })
                portfolio_value += pnl
                if time_stop:
                    cooldown_map[tkr] = today
                to_close.append(tkr)

        for tkr in to_close:
            del open_positions[tkr]

        # No entries if market in downtrend or VIX spiked
        if not spy_ok or paused:
            continue
        if len(open_positions) >= MAX_POSITIONS:
            continue

        # ── Entries ───────────────────────────────────────────────────────────
        candidates = []
        for tkr, tkr_df in signals.items():
            if tkr in open_positions or today not in tkr_df.index:
                continue
            if not tkr_df.loc[today]["signal"]:
                continue

            # Re-entry cooldown
            if tkr in cooldown_map:
                days_since = (pd.Timestamp(today) - pd.Timestamp(cooldown_map[tkr])).days
                if days_since < REENTRY_COOLDOWN_DAYS:
                    continue

            if near_earnings(tkr, today, earnings_map):
                continue
            if not sector_ok(tkr, today, sector_data):
                continue

            # Correlation cap — max 3 positions per sector
            if count_sector_positions(tkr, open_positions) >= MAX_SECTOR_POSITIONS:
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
            if entry_price <= 0:
                continue

            # Dollar volume check already in signal, but verify entry price valid
            prev_close_val = float(tkr_df.iloc[today_idx]["Close"])
            gap_pct = (entry_price - prev_close_val) / prev_close_val

            # Gap filters: skip large gap-downs AND stocks that already bounced big
            if gap_pct < GAP_DOWN_MAX or gap_pct > GAP_UP_MAX:
                continue

            pos_size       = get_position_size(today, vix_df)
            shares         = (portfolio_value * pos_size) / entry_price
            entry_comm     = calc_commission(shares, entry_price)
            first_t, sec_t = get_profit_target(rsi_val)

            open_positions[tkr] = {
                "entry_date"       : tkr_df.index[today_idx + 1],
                "entry_price"      : entry_price,
                "shares"           : shares,
                "shares_remaining" : shares,
                "rsi2_at_entry"    : rsi_val,
                "first_target"     : first_t,
                "second_target"    : sec_t,
                "partial_done"     : False,
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
    equity    = INITIAL_CAPITAL
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
    sharpe = monthly_ret.mean() / monthly_ret.std() * np.sqrt(12) \
             if monthly_ret.std() > 0 else 0

    total_comm  = trades_df["commission"].sum() if "commission" in trades_df else 0
    exit_counts = trades_df["exit_reason"].value_counts().to_dict() \
                  if "exit_reason" in trades_df.columns else {}

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
        "enhancements_v5"     : {
            "rsi2_threshold"        : RSI_THRESHOLD,
            "tiered_targets"        : f"RSI<{RSI_EXTREME}:{PROFIT_TARGET_EXTREME*100}%, "
                                       f"RSI<{RSI_MODERATE}:{PROFIT_TARGET_MODERATE*100}%, "
                                       f"else:{PROFIT_TARGET_NORMAL*100}%",
            "partial_exit_fraction" : PARTIAL_EXIT_FRACTION,
            "max_hold_days"         : MAX_HOLD_DAYS,
            "max_positions"         : MAX_POSITIONS,
            "max_sector_positions"  : MAX_SECTOR_POSITIONS,
            "reentry_cooldown_days" : REENTRY_COOLDOWN_DAYS,
            "dollar_vol_min"        : MIN_DOLLAR_VOLUME,
            "gap_down_max"          : GAP_DOWN_MAX,
            "gap_up_max"            : GAP_UP_MAX,
            "sector_ma_window"      : SECTOR_MA_WINDOW,
            "vix_spike_pct"         : VIX_SPIKE_PCT,
            "vix_spike_pause_days"  : VIX_SPIKE_PAUSE_DAYS,
            "earnings_months_size"  : POSITION_SIZE_EARNINGS,
            "universe"              : "S&P500 + S&P400",
            "commission_rate"       : COMMISSION_RATE,
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

    print("\n" + "="*64)
    print("  ENHANCED NAIVE MR BACKTEST V5 — RESULTS SUMMARY")
    print("="*64)
    for k, v in metrics.items():
        if k in ("enhancements_v5", "exit_reasons"):
            label = "V5 Enhancements" if "enhancement" in k else "Exit Reason Breakdown"
            print(f"\n  {label}:")
            for ek, ev in v.items():
                print(f"    {ek:<34}: {ev}")
        else:
            print(f"  {k.replace('_',' ').title():<34}: {v}")
    print("="*64)


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
