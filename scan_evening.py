"""
Naive MR - Evening Signal Scanner (Windows)
Runs every weekday at 6:00 PM PT via Windows Task Scheduler.

Workflow:
  1. Scans universe for entry signals using today's closing prices
  2. Applies gap filter using prior close as LOO limit price
  3. Submits Limit On Open (LOO) buy orders to IBKR
     - Limit = prior close * (1 + LOO_LIMIT_BUFFER)
     - Orders that gap up beyond limit won't fill -- matching backtest gap filter
  4. Saves pending entries to DB for morning script to confirm fills

Task Scheduler:
  Trigger : Daily, 6:00 PM PT, weekdays
  Action  : C:\\nmr-trader\\venv\\Scripts\\python.exe
  Argument: C:\\nmr-trader\\scan_evening.py
"""

import sqlite3
import datetime
import time
import logging
import io

import pandas as pd
import numpy as np
import yfinance as yf
import requests

from ib_async import IB, Stock, Order

# -- Config -------------------------------------------------------------------
IBKR_HOST      = '127.0.0.1'
IBKR_PORT      = 4002
IBKR_CLIENT_ID = 10          # Different client ID from morning script
DB_PATH        = r'C:\nmr-trader\positions.db'
LOG_PATH       = r'C:\nmr-trader\trade.log'

SENDGRID_API_KEY = ''
ALERT_FROM_EMAIL = 'ckurau@gmail.com'
ALERT_TO_EMAIL   = 'ckurau@gmail.com'

# -- LOO limit price ----------------------------------------------------------
# Entry limit = prior close * (1 + LOO_LIMIT_BUFFER)
# 0.005 = prior close + 0.5%
# Orders that gap up more than this overnight won't fill -- matching backtest
# GAP_UP_MAX = 2% behavior (we're conservative at 0.5% to avoid chasing gaps)
LOO_LIMIT_BUFFER = 0.005

# -- Strategy parameters (must match backtest V35) ----------------------------
MAX_POSITIONS               = 60
POSITION_SIZE               = 0.05
POSITION_SIZE_HIGH          = 0.09
POSITION_SIZE_EARNINGS      = 0.03
VIX_LOW                     = 25
EARNINGS_MONTHS             = {1, 4, 7, 10}
MIN_CONSEC_DOWN             = 4
RSI_PERIOD                  = 2
RSI_THRESHOLD               = 20
ATR_PERIOD                  = 14
ATR_MIN_PCT                 = 0.01
VOL_MA_PERIOD               = 20
MIN_DOLLAR_VOLUME           = 5_000_000
MA_WINDOW                   = 200
GAP_DOWN_MAX                = -0.010
GAP_UP_MAX                  = 0.020
MAX_SECTOR_POSITIONS        = 3
EARNINGS_BLACKOUT           = 3
REENTRY_COOLDOWN_DAYS       = 5
VELOCITY_CRASH_5D_THRESHOLD = -0.12
VELOCITY_CRASH_PAUSE_DAYS   = 5

TOP_SIGNAL_PCT        = 0.20
TOP_SIGNAL_MULTIPLIER = 1.30
TOP_SIGNAL_HARD_CAP   = 0.12
MIN_CANDIDATES_FOR_C5 = 5

TIER1_MIN_DOWN       = 6
TIER2_MIN_DOWN       = 5

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

TICKER_TO_SECTOR = {}
for _etf, _members in SECTOR_ETFS.items():
    for _t in _members:
        TICKER_TO_SECTOR[_t] = _etf

# -- Logging ------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s %(levelname)s %(message)s',
    handlers=[
        logging.FileHandler(LOG_PATH),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)

# -- Database helpers ---------------------------------------------------------
def get_db():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_db()
    conn.execute('''CREATE TABLE IF NOT EXISTS open_positions (
        ticker TEXT PRIMARY KEY,
        entry_date TEXT,
        entry_price REAL,
        shares REAL,
        shares_remaining REAL,
        tier INTEGER,
        hold_days INTEGER,
        profit_target REAL,
        partial_enabled INTEGER,
        partial_frac REAL,
        partial_trigger REAL,
        partial_done INTEGER,
        entry_commission REAL,
        consec_down_at_entry INTEGER,
        rsi2_at_entry REAL
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS trade_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        ticker TEXT,
        entry_date TEXT,
        exit_date TEXT,
        entry_price REAL,
        exit_price REAL,
        shares REAL,
        pnl_usd REAL,
        pnl_pct REAL,
        exit_reason TEXT,
        tier INTEGER
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS cooldown (
        ticker TEXT PRIMARY KEY,
        cooldown_until TEXT
    )''')
    conn.execute('''CREATE TABLE IF NOT EXISTS pending_entries (
        ticker TEXT PRIMARY KEY,
        signal_date TEXT,
        limit_price REAL,
        shares REAL,
        tier INTEGER,
        hold_days INTEGER,
        profit_target REAL,
        partial_enabled INTEGER,
        partial_frac REAL,
        partial_trigger REAL,
        consec_down INTEGER,
        rsi2 REAL,
        entry_commission REAL
    )''')
    conn.commit()
    conn.close()

def load_open_positions():
    conn = get_db()
    try:
        df = pd.read_sql('SELECT * FROM open_positions', conn)
    except Exception:
        df = pd.DataFrame()
    conn.close()
    return df

def save_pending_entry(entry):
    conn = get_db()
    conn.execute('''INSERT OR REPLACE INTO pending_entries VALUES
        (:ticker,:signal_date,:limit_price,:shares,:tier,:hold_days,
         :profit_target,:partial_enabled,:partial_frac,:partial_trigger,
         :consec_down,:rsi2,:entry_commission)''', entry)
    conn.commit()
    conn.close()

def clear_pending_entries():
    conn = get_db()
    conn.execute('DELETE FROM pending_entries')
    conn.commit()
    conn.close()

def is_on_cooldown(ticker):
    conn = get_db()
    row  = conn.execute(
        'SELECT cooldown_until FROM cooldown WHERE ticker=?', (ticker,)
    ).fetchone()
    conn.close()
    if not row:
        return False
    return datetime.date.today().isoformat() < row[0]

# -- Strategy helpers ---------------------------------------------------------
def compute_rsi(series, period=2):
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def get_tier(consec_down):
    if consec_down >= TIER1_MIN_DOWN:
        return {'tier': 1, 'hold_days': 8, 'profit_target': 0.02,
                'partial_enabled': 1, 'partial_frac': 0.5, 'partial_trigger': 0.01}
    elif consec_down >= TIER2_MIN_DOWN:
        return {'tier': 2, 'hold_days': 8, 'profit_target': 0.02,
                'partial_enabled': 0, 'partial_frac': 0.0, 'partial_trigger': 0.0}
    else:
        return {'tier': 3, 'hold_days': 8, 'profit_target': 0.02,
                'partial_enabled': 0, 'partial_frac': 0.0, 'partial_trigger': 0.0}

def get_position_size_pct(vix_value, rank=0, n_candidates=0):
    month = datetime.date.today().month
    base  = POSITION_SIZE_HIGH if vix_value < VIX_LOW else POSITION_SIZE
    if month in EARNINGS_MONTHS and base > POSITION_SIZE_EARNINGS:
        base = POSITION_SIZE_EARNINGS
    if n_candidates >= MIN_CANDIDATES_FOR_C5:
        top_n = max(1, int(n_candidates * TOP_SIGNAL_PCT))
        if rank < top_n:
            base = min(base * TOP_SIGNAL_MULTIPLIER, TOP_SIGNAL_HARD_CAP)
    return base

def sector_of(ticker):
    return TICKER_TO_SECTOR.get(ticker)

def count_sector_positions(ticker, open_tickers):
    etf = sector_of(ticker)
    if etf is None:
        return 0
    return sum(1 for t in open_tickers if TICKER_TO_SECTOR.get(t) == etf)

def get_universe():
    tickers = set()
    headers = {"User-Agent": "Mozilla/5.0"}
    for url, label in [
        ("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", "S&P 500"),
        ("https://en.wikipedia.org/wiki/List_of_S%26P_400_companies", "S&P 400"),
        ("https://en.wikipedia.org/wiki/List_of_S%26P_600_companies", "S&P 600"),
    ]:
        try:
            resp   = requests.get(url, headers=headers, timeout=30)
            tables = pd.read_html(io.StringIO(resp.text))
            for table in tables:
                for col in ["Symbol", "Ticker symbol", "Ticker"]:
                    if col in table.columns:
                        syms = table[col].dropna().astype(str).tolist()
                        if len(syms) >= 100:
                            tickers.update([s.replace(".", "-") for s in syms])
                            log.info(f"Universe: {label} {len(syms)} symbols")
                            break
                else:
                    continue
                break
        except Exception as e:
            log.warning(f"Universe fetch failed ({label}): {e}")
    tickers.update([
        "LEH","BSC","WB","WAMU","MER","C","AIG","FNM","FRE",
        "YHOO","SUNW","PALM","Q","NT","GLW","JDS","GE","GM","F",
        "XOM","CVX","IBM","MSFT","AAPL","AMZN","GOOG","GOOGL",
        "META","NVDA","TSLA","BRK-B","JPM","BAC","WFC","GS","MS",
        "HD","LOW","TGT","WMT","COST","KR","UNH","JNJ","PFE","MRK",
        "ABBV","BMY","AMGN","LLY","BA","LMT","RTX","CAT","DE","HON",
        "NEE","DUK","SO","AMT","PLD","SBUX","MCD","DIS","NFLX",
        "CMCSA","VZ","TMUS","PG","KO","PEP","CL","KMB",
    ])
    result = sorted(tickers)
    log.info(f"Universe total: {len(result)} tickers")
    return result

def send_alert(subject, body):
    if not SENDGRID_API_KEY:
        log.info(f"[Email not configured] {subject}")
        return
    try:
        import sendgrid
        from sendgrid.helpers.mail import Mail
        sg      = sendgrid.SendGridAPIClient(api_key=SENDGRID_API_KEY)
        message = Mail(from_email=ALERT_FROM_EMAIL, to_emails=ALERT_TO_EMAIL,
                       subject=subject, plain_text_content=body)
        sg.send(message)
        log.info("Alert email sent")
    except Exception as e:
        log.error(f"Email failed: {e}")

# -- Main ---------------------------------------------------------------------
def run():
    today = datetime.date.today()
    log.info(f"=== NMR Evening Scan: {today} ===")

    if today.weekday() >= 5:
        log.info("Weekend - skipping.")
        return

    init_db()
    clear_pending_entries()  # Clear any stale entries from prior run

    # Connect to IBKR
    ib        = IB()
    connected = False
    for attempt in range(1, 4):
        try:
            ib.connect(IBKR_HOST, IBKR_PORT, clientId=IBKR_CLIENT_ID)
            log.info(f"Connected to IBKR Gateway (attempt {attempt})")
            connected = True
            break
        except Exception as e:
            log.warning(f"Connection attempt {attempt}/3 failed: {e}")
            if attempt < 3:
                time.sleep(30)

    if not connected:
        log.error("Could not connect to IBKR Gateway")
        send_alert("NMR ERROR: Evening scan IBKR connection failed",
                   f"Could not connect on port {IBKR_PORT}. Log: {LOG_PATH}")
        return

    # Portfolio value
    portfolio_value = None
    for av in ib.accountValues():
        if av.tag == 'NetLiquidation' and av.currency == 'USD':
            portfolio_value = float(av.value)
            break
    if not portfolio_value:
        portfolio_value = 100_000.0
        log.warning("Could not read portfolio value - using $100,000 fallback")
    log.info(f"Portfolio value: ${portfolio_value:,.2f}")

    # Market regime
    try:
        vix_raw         = yf.download('^VIX', period='10d', progress=False, auto_adjust=True)
        vix_value       = float(vix_raw['Close'].squeeze().iloc[-1])
        spy_raw         = yf.download('SPY', period='400d', progress=False, auto_adjust=True)
        spy_close_s     = spy_raw['Close'].squeeze()
        spy_5d_ret      = float(spy_close_s.pct_change(5).iloc[-1])
        spy_ma200       = float(spy_close_s.rolling(200).mean().iloc[-1])
        spy_above_ma200 = float(spy_close_s.iloc[-1]) > spy_ma200

        # Sector ETF MA filter
        sector_ok = {}
        etf_list  = list(SECTOR_ETFS.keys())
        etf_raw   = yf.download(etf_list, period='60d', progress=False, auto_adjust=True)
        for etf in etf_list:
            try:
                if isinstance(etf_raw.columns, pd.MultiIndex):
                    etf_close = etf_raw['Close'][etf].squeeze()
                else:
                    etf_close = etf_raw['Close'].squeeze()
                sector_ok[etf] = float(etf_close.iloc[-1]) > float(
                    etf_close.rolling(20).mean().iloc[-1])
            except Exception:
                sector_ok[etf] = True  # Default allow if data missing

    except Exception as e:
        log.error(f"Market data download failed: {e}")
        ib.disconnect()
        return

    log.info(f"VIX: {vix_value:.1f} | SPY 5d: {spy_5d_ret:.1%} | SPY>200d: {spy_above_ma200}")

    velocity_paused = spy_5d_ret < VELOCITY_CRASH_5D_THRESHOLD
    entries_allowed = spy_above_ma200 and not velocity_paused

    if not entries_allowed:
        reason = ("SPY below 200d MA" if not spy_above_ma200
                  else f"velocity crash pause (SPY 5d: {spy_5d_ret:.1%})")
        log.info(f"Entries blocked: {reason} -- no orders will be submitted")
        ib.disconnect()
        send_alert(f"NMR Evening Scan {today} -- entries blocked",
                   f"Reason: {reason}\nNo LOO orders submitted.")
        return

    # Load open positions
    open_pos_df  = load_open_positions()
    open_tickers = set(open_pos_df['ticker'].tolist()) if not open_pos_df.empty else set()
    slots_available = MAX_POSITIONS - len(open_tickers)
    log.info(f"Open positions: {len(open_tickers)} | Slots: {slots_available}")

    if slots_available <= 0:
        log.info("No slots available -- skipping scan")
        ib.disconnect()
        return

    # Download price data
    log.info("Fetching universe and price data...")
    universe    = get_universe()
    start_date  = (today - datetime.timedelta(days=400)).isoformat()

    price_data = {}
    for i in range(0, len(universe), 100):
        chunk = universe[i:i+100]
        try:
            raw = yf.download(chunk, start=start_date, auto_adjust=True,
                              progress=False, threads=True)
            if raw.empty:
                continue
            if isinstance(raw.columns, pd.MultiIndex):
                for tkr in chunk:
                    try:
                        df = raw.xs(tkr, axis=1, level=1).dropna(how='all')
                        if not df.empty:
                            price_data[tkr] = df
                    except KeyError:
                        pass
            elif chunk:
                price_data[chunk[0]] = raw.dropna(how='all')
        except Exception as e:
            log.warning(f"Chunk error: {e}")
    log.info(f"Downloaded {len(price_data)} tickers")

    # -- Signal scan ----------------------------------------------------------
    candidates = []
    for ticker in universe:
        if ticker in open_tickers or is_on_cooldown(ticker):
            continue
        if ticker not in price_data:
            continue
        prices = price_data[ticker]
        if len(prices) < MA_WINDOW + VOL_MA_PERIOD + 10:
            continue
        close  = prices['Close'].squeeze()
        volume = prices['Volume'].squeeze()
        try:
            # MA200 filter
            ma200_val  = float(close.rolling(MA_WINDOW).mean().iloc[-1])
            last_close = float(close.iloc[-1])
            if last_close <= ma200_val:
                continue

            # Consecutive down days
            consec = 0
            closes = close.tolist()
            for j in range(len(closes)-1, 0, -1):
                if closes[j] < closes[j-1]:
                    consec += 1
                else:
                    break
            if consec < MIN_CONSEC_DOWN:
                continue

            # RSI filter
            rsi2 = float(compute_rsi(close, RSI_PERIOD).iloc[-1])
            if rsi2 >= RSI_THRESHOLD:
                continue

            # ATR filter
            tr = pd.concat([
                prices['High'].squeeze() - prices['Low'].squeeze(),
                (prices['High'].squeeze() - close.shift(1)).abs(),
                (prices['Low'].squeeze()  - close.shift(1)).abs(),
            ], axis=1).max(axis=1)
            atr_pct = float(tr.rolling(ATR_PERIOD).mean().iloc[-1] / last_close)
            if atr_pct <= ATR_MIN_PCT:
                continue

            # Volume filter
            vol_ma = float(volume.rolling(VOL_MA_PERIOD).mean().iloc[-1])
            if float(volume.iloc[-1]) <= vol_ma:
                continue

            # Dollar volume filter
            dollar_vol = float((close * volume).rolling(VOL_MA_PERIOD).mean().iloc[-1])
            if dollar_vol < MIN_DOLLAR_VOLUME:
                continue

            # Sector ETF filter
            etf = sector_of(ticker)
            if etf and not sector_ok.get(etf, True):
                continue

            # Sector concentration filter
            if count_sector_positions(ticker, open_tickers) >= MAX_SECTOR_POSITIONS:
                continue

            composite_score = rsi2 / atr_pct if atr_pct > 0 else rsi2 * 1000
            candidates.append((composite_score, ticker, consec,
                               last_close, rsi2, atr_pct))
        except Exception:
            continue

    candidates.sort(key=lambda x: x[0])
    log.info(f"Signal candidates: {len(candidates)} | Slots: {slots_available}")

    # -- Submit LOO orders ----------------------------------------------------
    n_cands         = len(candidates)
    orders_submitted = []

    for rank_i, (composite_score, ticker, consec, last_close, rsi2, atr_pct) in enumerate(
            candidates[:slots_available]):

        tier_cfg     = get_tier(consec)
        cur_pos_size = get_position_size_pct(vix_value, rank=rank_i, n_candidates=n_cands)
        shares       = round((portfolio_value * cur_pos_size) / last_close)
        if shares < 1:
            continue

        # LOO limit price = prior close + 0.5%
        # If stock gaps up more than 0.5% overnight it won't fill -- correct behavior
        limit_price = round(last_close * (1 + LOO_LIMIT_BUFFER), 2)

        log.info(f"SIGNAL: {ticker} | Tier {tier_cfg['tier']} | consec={consec} | "
                 f"RSI={rsi2:.1f} | ATR={atr_pct*100:.1f}% | "
                 f"close=${last_close:.2f} | limit=${limit_price:.2f} | {shares}sh")

        # Submit LOO order (Limit On Open)
        contract = Stock(ticker, 'SMART', 'USD')
        order    = Order(
            action       = 'BUY',
            totalQuantity = shares,
            orderType    = 'LOO',   # Limit On Open
            lmtPrice     = limit_price,
            tif          = 'OPG',   # Only valid at open
        )

        try:
            trade = ib.placeOrder(contract, order)
            log.info(f"LOO order submitted: {ticker} | {shares}sh @ limit ${limit_price:.2f}")

            # Save to pending_entries for morning script to confirm
            save_pending_entry({
                'ticker':           ticker,
                'signal_date':      today.isoformat(),
                'limit_price':      limit_price,
                'shares':           float(shares),
                'tier':             tier_cfg['tier'],
                'hold_days':        tier_cfg['hold_days'],
                'profit_target':    tier_cfg['profit_target'],
                'partial_enabled':  tier_cfg['partial_enabled'],
                'partial_frac':     tier_cfg['partial_frac'],
                'partial_trigger':  tier_cfg['partial_trigger'],
                'consec_down':      consec,
                'rsi2':             rsi2,
                'entry_commission': max(shares * 0.005, 0.35),
            })
            orders_submitted.append(
                f"LOO: {ticker} {shares}sh @ limit ${limit_price:.2f} | "
                f"Tier {tier_cfg['tier']} | RSI={rsi2:.1f} | {cur_pos_size:.0%}")
        except Exception as e:
            log.error(f"LOO order failed ({ticker}): {e}")

    ib.disconnect()
    log.info("Disconnected from IBKR")

    summary = f"""NMR Evening Scan - {today}

Portfolio Value  : ${portfolio_value:,.2f}
Open Positions   : {len(open_tickers)} / {MAX_POSITIONS}
Slots Available  : {slots_available}
VIX              : {vix_value:.1f}
SPY > 200d MA    : {spy_above_ma200}
Signal candidates: {len(candidates)}
LOO orders sent  : {len(orders_submitted)}

ORDERS ({len(orders_submitted)}):
{chr(10).join('  ' + s for s in orders_submitted) if orders_submitted else '  None'}

LOO limit buffer : +{LOO_LIMIT_BUFFER*100:.1f}% above prior close
(Orders gap up more than this overnight will not fill)

Log: {LOG_PATH}
"""
    log.info(summary)
    send_alert(
        f"NMR Scan {today} | {len(orders_submitted)} LOO orders | "
        f"{len(open_tickers)}/{MAX_POSITIONS} positions",
        summary)


if __name__ == '__main__':
    run()
