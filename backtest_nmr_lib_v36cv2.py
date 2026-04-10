# backtest_nmr_lib_v36cv2.py
# V36c-v2 -- Inverse ETF mean reversion using UNDERLYING overbought signal
#
# PROBLEM WITH V36c-v1:
#   Required 4+ consecutive DOWN days on SH/PSQ/RWM directly.
#   Inverse ETFs trend UP during bear markets, so they rarely have
#   4+ consecutive down days. Only 57 trades in 21 years -- too few
#   to provide meaningful drawdown protection (+$29k total, ~$1.4k/year).
#
# V36c-v2 FIX -- invert the signal logic:
#   Instead of looking at the inverse ETF's price action, look at the
#   UNDERLYING index being overbought during a bear market.
#   Signal: SPY has 3+ consecutive UP days AND RSI(2) > 75
#   while SPY is still BELOW its 200d MA (bear regime active).
#   This means the underlying has bounced/rallied too far in a downtrend
#   -- a high-probability setup for mean reversion back down.
#   Entry: buy SH (inverse S&P 500) at next open.
#   Exit: SPY closes DOWN for 1 day (underlying has resumed decline)
#         OR 5-day time stop OR 2% profit target on SH.
#
# The signal logic is identical to the long side but applied in reverse:
#   Long side:  underlying has too many DOWN days --> buy (mean reversion up)
#   Short side: underlying has too many UP days during bear --> buy inverse (mean reversion down)
#
# V34 PERMANENT CHANGES CARRIED FORWARD:
#   [C3] GAP_DOWN_MAX = -0.010
#   [C5] Top 20% of signals get 1.2x size, hard cap 12%
#
# EXPERIMENTS:
#   V34_baseline    -- V34 unchanged (control)
#   V36cv2_inverse  -- V34 + inverse ETF using underlying overbought signal

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

    use_inverse_etf: bool = False

    # Underlying overbought signal parameters
    underlying_consec_up: int = 3       # SPY needs 3+ consecutive up days
    underlying_rsi_threshold: float = 75.0  # AND RSI(2) > 75 (overbought)

    # Inverse ETF trade parameters
    inverse_etf: str = "SH"            # 1x inverse S&P 500 -- liquid, low slippage
    inverse_position_size: float = 0.05
    inverse_profit_target: float = 0.020
    inverse_hold_days: int = 5
    inverse_max_positions: int = 1     # max 1 inverse position at a time


BASELINE = ExperimentConfig(
    name="V34_baseline",
    description="V34 -- no changes (control)",
    use_inverse_etf=False,
)

V36CV2 = ExperimentConfig(
    name="V36cv2_inverse",
    description="V36c-v2 -- buy SH when SPY has 3+ up days + RSI(2)>75 in bear regime",
    use_inverse_etf=True,
    underlying_consec_up=3,
    underlying_rsi_threshold=75.0,
    inverse_etf="SH",
    inverse_position_size=0.05,
    inverse_profit_target=0.020,
    inverse_hold_days=5,
    inverse_max_positions=1,
)

EXPERIMENTS = [BASELINE, V36CV2]


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
    # For inverse signal: consecutive UP days and RSI on SPY
    spy["up_day"]     = (close > close.shift(1)).astype(int)
    consec_up, count  = [], 0
    for d in spy["up_day"]:
        count = count + 1 if d == 1 else 0
        consec_up.append(count)
    spy["spy_consec_up"] = consec_up
    spy["spy_rsi2"]      = _compute_rsi(close, 2)
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


def download_sh(ticker: str = "SH") -> pd.DataFrame:
    """Download SH (inverse S&P 500 ETF) price data."""
    try:
        df = _dl_single(ticker)
        print(f"[Download] {ticker}: {len(df)} rows")
        return df
    except Exception as e:
        print(f"[Download] {ticker} failed: {e}")
        return pd.DataFrame()


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
# 4. Signal generation (main universe -- unchanged from V34)
# -----------------------------------------------------------------------------
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
                 sh_data: pd.DataFrame = None,
                 cfg: ExperimentConfig = BASELINE) -> pd.DataFrame:

    print(f"\n[Backtest] Running: {cfg.name}")
    print(f"[Backtest] {cfg.description}")

    spy_regime      = spy_df["spy_ok"].to_dict()
    spy_consec_up   = spy_df["spy_consec_up"].to_dict()
    spy_rsi2        = spy_df["spy_rsi2"].to_dict()

    all_dates: set = set()
    for df in price_data.values():
        all_dates.update(df.index)
    if sh_data is not None and not sh_data.empty:
        all_dates.update(sh_data.index)
    trading_dates = sorted(all_dates)

    signals: dict[str, pd.DataFrame] = {}
    min_bars = MA_WINDOW + VOL_MA_PERIOD + ATR_PERIOD + MIN_CONSEC_DOWN + 5
    for tkr, df in tqdm(price_data.items(), desc=f"Signals [{cfg.name}]"):
        if len(df) > min_bars:
            signals[tkr] = generate_signals(df)

    portfolio_value  = INITIAL_CAPITAL
    portfolio_peak   = None
    current_drawdown = 0.0
    open_positions: dict[str, dict] = {}
    open_inv: dict = {}   # at most 1 SH position at a time
    trades: list[dict] = []
    cooldown_map: dict = {}
    last_vix_spike      = None
    last_velocity_crash = None

    diag_inv_entries  = 0
    diag_inv_signals  = 0

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

        # ?? Exits: main long positions ??????????????????????????????????????
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
                    "experiment": cfg.name, "trade_type": "main",
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
                    "experiment": cfg.name, "trade_type": "main",
                })
                portfolio_value += pnl
                if time_stop:
                    cooldown_map[tkr] = today
                to_close.append(tkr)

        for tkr in to_close:
            del open_positions[tkr]

        # ?? Exits: SH inverse position ??????????????????????????????????????
        if "SH" in open_inv and sh_data is not None and not sh_data.empty:
            pos = open_inv["SH"]
            if today in sh_data.index:
                sh_close    = float(sh_data.loc[today, "Close"])
                entry_price = pos["entry_price"]
                days_held   = (pd.Timestamp(today) - pd.Timestamp(pos["entry_date"])).days
                pos_pct     = (sh_close - entry_price) / entry_price
                time_stop   = days_held >= cfg.inverse_hold_days
                profit_hit  = pos_pct >= cfg.inverse_profit_target
                # Also exit if SPY has a down day (underlying resumed decline --
                # inverse trade has served its purpose as a hedge)
                spy_down_today = (today in spy_df.index and
                                  float(spy_df.loc[today, "spy_5d_ret"]) < 0 and
                                  days_held >= 1)
                if time_stop or profit_hit or spy_down_today:
                    commission = calc_commission(pos["shares"], sh_close)
                    pnl        = ((sh_close - entry_price) * pos["shares"]
                                  - commission - pos["entry_commission"])
                    reason = ("time_stop" if time_stop
                              else "profit_target" if profit_hit
                              else "spy_resumed_decline")
                    trades.append({
                        "ticker": "SH", "entry_date": pos["entry_date"],
                        "exit_date": today, "entry_price": entry_price,
                        "exit_price": sh_close, "shares": pos["shares"],
                        "commission": round(commission + pos["entry_commission"], 4),
                        "pnl_usd": pnl, "pnl_pct": pos_pct * 100,
                        "days_held": days_held, "exit_reason": reason,
                        "tier": 0, "consec_down": 0,
                        "portfolio_val": portfolio_value + pnl,
                        "experiment": cfg.name, "trade_type": "inverse",
                    })
                    portfolio_value += pnl
                    del open_inv["SH"]

        # ?? Main entries (SPY above 200d) ????????????????????????????????????
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
                    c5_mult  = (TOP_SIGNAL_MULTIPLIER
                                if n_candidates >= MIN_CANDIDATES_FOR_C5 and rank < top_n
                                else 1.0)
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

        # ?? Inverse SH entry (SPY BELOW 200d -- bear regime) ????????????????
        if (cfg.use_inverse_etf and not spy_ok and not velocity_paused
                and "SH" not in open_inv
                and sh_data is not None and not sh_data.empty):

            # Check if SPY is overbought within the bear regime
            consec_up = spy_consec_up.get(today, 0)
            rsi2_spy  = spy_rsi2.get(today, 50.0)

            spy_overbought = (consec_up >= cfg.underlying_consec_up
                              and rsi2_spy > cfg.underlying_rsi_threshold)

            if spy_overbought:
                diag_inv_signals += 1
                # Buy SH at next open
                if today in sh_data.index:
                    today_idx = sh_data.index.get_loc(today)
                    if today_idx + 1 < len(sh_data):
                        next_sh    = sh_data.iloc[today_idx + 1]
                        sh_open    = float(next_sh["Open"])
                        if sh_open > 0:
                            shares     = (portfolio_value * cfg.inverse_position_size) / sh_open
                            entry_comm = calc_commission(shares, sh_open)
                            open_inv["SH"] = {
                                "entry_date":  sh_data.index[today_idx + 1],
                                "entry_price": sh_open,
                                "shares":      shares,
                                "entry_commission": entry_comm,
                            }
                            diag_inv_entries += 1

    print(f"[Backtest] {cfg.name} complete -- {len(trades)} trades.")
    if cfg.use_inverse_etf:
        print(f"[Backtest] Inverse signals fired: {diag_inv_signals} | "
              f"Entries taken: {diag_inv_entries}")
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
    full_exits  = (trades_df[trades_df["exit_reason"] != "partial_exit"]
                   if "exit_reason" in trades_df.columns else trades_df)
    time_stop_n  = exit_counts.get("time_stop", 0)
    time_stop_rt = round(time_stop_n / len(full_exits) * 100, 1) if len(full_exits) else 0

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

    inv_df     = trades_df[trades_df.get("trade_type", pd.Series(["main"]*len(trades_df))) == "inverse"] \
        if "trade_type" in trades_df.columns else pd.DataFrame()
    inv_trades = len(inv_df)
    inv_pnl    = round(inv_df["pnl_usd"].sum(), 2) if not inv_df.empty else 0.0
    inv_wr     = round((inv_df["pnl_usd"] > 0).mean() * 100, 1) if not inv_df.empty else 0.0

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
        "inv_trades":         inv_trades,
        "inv_pnl_usd":        inv_pnl,
        "inv_win_rate_pct":   inv_wr,
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
    "ExperimentConfig", "BASELINE", "V36CV2", "EXPERIMENTS",
    "get_universe", "download_prices", "download_reference_data",
    "download_sh", "build_earnings_dates",
    "run_backtest", "compute_metrics", "save_outputs",
    "INITIAL_CAPITAL", "START_DATE", "END_DATE",
]
