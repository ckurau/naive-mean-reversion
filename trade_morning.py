"""
Naive MR - Morning Execution Script (Windows)
Runs every weekday at 6:15 AM PT via Windows Task Scheduler.

Workflow:
  1. Processes exits for open positions (MOO sell orders)
  2. Holds connection until 6:35 AM PT for market open
  3. Confirms fills on LOO entry orders placed by evening scan
  4. Updates DB with actual fill prices
  5. Sends daily summary

Task Scheduler:
  Trigger : Daily, 6:15 AM PT, weekdays
  Action  : C:\\nmr-trader\\venv\\Scripts\\python.exe
  Argument: C:\\nmr-trader\\trade_morning.py
"""

import sqlite3
import datetime
import time
import logging

import pandas as pd
import numpy as np
import yfinance as yf

from ib_async import IB, Stock, Order

# -- Config -------------------------------------------------------------------
IBKR_HOST      = '127.0.0.1'
IBKR_PORT      = 4002
IBKR_CLIENT_ID = 1
DB_PATH        = r'C:\nmr-trader\positions.db'
LOG_PATH       = r'C:\nmr-trader\trade.log'

SENDGRID_API_KEY = ''
ALERT_FROM_EMAIL = 'ckurau@gmail.com'
ALERT_TO_EMAIL   = 'ckurau@gmail.com'

# -- Timing -------------------------------------------------------------------
FILL_WAIT_UNTIL_HOUR   = 6
FILL_WAIT_UNTIL_MINUTE = 35

# -- Strategy parameters ------------------------------------------------------
MAX_POSITIONS        = 60
MIN_HOLD_BEFORE_EXIT = 2
VIX_LOW              = 25
EARNINGS_MONTHS      = {1, 4, 7, 10}
POSITION_SIZE        = 0.05
POSITION_SIZE_HIGH   = 0.09
POSITION_SIZE_EARNINGS = 0.03
REENTRY_COOLDOWN_DAYS  = 5

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

def load_pending_entries():
    conn = get_db()
    try:
        df = pd.read_sql('SELECT * FROM pending_entries', conn)
    except Exception:
        df = pd.DataFrame()
    conn.close()
    return df

def save_position(pos):
    conn = get_db()
    conn.execute('''INSERT OR REPLACE INTO open_positions VALUES
        (:ticker,:entry_date,:entry_price,:shares,:shares_remaining,:tier,
         :hold_days,:profit_target,:partial_enabled,:partial_frac,
         :partial_trigger,:partial_done,:entry_commission,
         :consec_down_at_entry,:rsi2_at_entry)''', pos)
    conn.commit()
    conn.close()

def remove_position(ticker):
    conn = get_db()
    conn.execute('DELETE FROM open_positions WHERE ticker=?', (ticker,))
    conn.commit()
    conn.close()

def remove_pending_entry(ticker):
    conn = get_db()
    conn.execute('DELETE FROM pending_entries WHERE ticker=?', (ticker,))
    conn.commit()
    conn.close()

def update_partial(ticker, new_shares_remaining, new_profit_target):
    conn = get_db()
    conn.execute(
        'UPDATE open_positions SET shares_remaining=?, partial_done=1, profit_target=? WHERE ticker=?',
        (new_shares_remaining, new_profit_target, ticker))
    conn.commit()
    conn.close()

def log_trade(trade):
    conn = get_db()
    conn.execute('''INSERT INTO trade_log
        (ticker,entry_date,exit_date,entry_price,exit_price,
         shares,pnl_usd,pnl_pct,exit_reason,tier)
        VALUES (:ticker,:entry_date,:exit_date,:entry_price,:exit_price,
         :shares,:pnl_usd,:pnl_pct,:exit_reason,:tier)''', trade)
    conn.commit()
    conn.close()

def set_cooldown(ticker, days=5):
    until = (datetime.date.today() + datetime.timedelta(days=days)).isoformat()
    conn  = get_db()
    conn.execute('INSERT OR REPLACE INTO cooldown VALUES (?,?)', (ticker, until))
    conn.commit()
    conn.close()

def get_position_size_pct(vix_value):
    month = datetime.date.today().month
    base  = POSITION_SIZE_HIGH if vix_value < VIX_LOW else POSITION_SIZE
    if month in EARNINGS_MONTHS and base > POSITION_SIZE_EARNINGS:
        base = POSITION_SIZE_EARNINGS
    return base

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
        log.info("Summary email sent")
    except Exception as e:
        log.error(f"Email failed: {e}")

def wait_until_fill_window():
    """Hold connection until 6:35 AM PT for MOO/LOO fills."""
    now    = datetime.datetime.now()
    target = now.replace(hour=FILL_WAIT_UNTIL_HOUR,
                         minute=FILL_WAIT_UNTIL_MINUTE,
                         second=0, microsecond=0)
    if now >= target:
        log.info("Already past fill window -- checking fills immediately.")
        return
    wait_secs = int((target - now).total_seconds())
    log.info(f"Holding until {target.strftime('%I:%M %p')} PT for fills ({wait_secs}s)...")
    while True:
        now = datetime.datetime.now()
        if now >= target:
            break
        remaining = int((target - now).total_seconds())
        if remaining % 60 < 5:
            log.info(f"Waiting for market open... {remaining}s remaining")
        time.sleep(5)
    log.info("Fill window reached.")

# -- Main ---------------------------------------------------------------------
def run():
    today = datetime.date.today()
    log.info(f"=== NMR Morning Run: {today} ===")

    if today.weekday() >= 5:
        log.info("Weekend - skipping.")
        return

    init_db()

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
        log.error("All 3 connection attempts failed")
        send_alert("NMR ERROR: Morning IBKR connection failed",
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

    # VIX for summary
    try:
        vix_raw   = yf.download('^VIX', period='5d', progress=False, auto_adjust=True)
        vix_value = float(vix_raw['Close'].squeeze().iloc[-1])
    except Exception:
        vix_value = 0.0
    pos_size_pct = get_position_size_pct(vix_value)

    # Load positions and pending entries
    open_pos_df   = load_open_positions()
    pending_df    = load_pending_entries()
    open_tickers  = set(open_pos_df['ticker'].tolist()) if not open_pos_df.empty else set()
    pending_tickers = set(pending_df['ticker'].tolist()) if not pending_df.empty else set()

    log.info(f"Open positions: {len(open_tickers)} | Pending LOO entries: {len(pending_tickers)}")

    # Download price data for open positions only (exits need current prices)
    exits_summary  = []
    exited_tickers = set()
    exit_orders    = []

    if not open_pos_df.empty:
        log.info("Downloading prices for open positions...")
        start_date = (today - datetime.timedelta(days=400)).isoformat()
        price_data = {}
        pos_tickers = list(open_tickers)
        for i in range(0, len(pos_tickers), 100):
            chunk = pos_tickers[i:i+100]
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
                log.warning(f"Price download error: {e}")

        # -- Process exits ----------------------------------------------------
        for _, pos in open_pos_df.iterrows():
            ticker = pos['ticker']
            if ticker not in price_data or pos['entry_price'] <= 0:
                log.warning(f"Skipping exit check for {ticker} -- no price data or entry_price=0")
                continue

            prices      = price_data[ticker]
            close_today = float(prices['Close'].iloc[-1])
            entry_price = pos['entry_price']
            days_held   = (today - datetime.date.fromisoformat(pos['entry_date'])).days
            pos_pct     = (close_today - entry_price) / entry_price
            shares_rem  = pos['shares_remaining']
            early       = days_held < MIN_HOLD_BEFORE_EXIT
            time_stop   = days_held >= pos['hold_days']
            profit_hit  = (not early) and pos_pct >= pos['profit_target']

            log.info(f"Position check: {ticker} | held={days_held}d | "
                     f"pct={pos_pct:+.1%} | target={pos['profit_target']:.1%} | "
                     f"time_stop={time_stop} | profit_hit={profit_hit}")

            # Partial exit (Tier 1)
            if (pos['partial_enabled'] and not pos['partial_done']
                    and not early and pos_pct >= pos['partial_trigger']):
                partial_shares = round(shares_rem * pos['partial_frac'])
                if partial_shares >= 1:
                    log.info(f"PARTIAL EXIT: {ticker} | {pos_pct:+.1%} | {partial_shares}sh")
                    exit_orders.append((Stock(ticker, 'SMART', 'USD'),
                                        Order(action='SELL', totalQuantity=partial_shares,
                                              orderType='MOO', tif='OPG')))
                    exits_summary.append(
                        f"PARTIAL EXIT: {ticker} {partial_shares}sh | {pos_pct:+.1%}")
                    update_partial(ticker, shares_rem - partial_shares,
                                   pos['profit_target'] * 2)
                continue

            if time_stop or profit_hit:
                reason = "time_stop" if time_stop else "profit_target"
                pnl    = (close_today - entry_price) * shares_rem
                log.info(f"EXIT: {ticker} | {reason} | {pos_pct:+.1%} | P&L: ${pnl:+,.0f}")
                exit_orders.append((Stock(ticker, 'SMART', 'USD'),
                                    Order(action='SELL', totalQuantity=round(shares_rem),
                                          orderType='MOO', tif='OPG')))
                exits_summary.append(
                    f"{reason.upper()}: {ticker} {round(shares_rem)}sh | "
                    f"{pos_pct:+.1%} | est. P&L: ${pnl:+,.0f}")
                log_trade({
                    'ticker':      ticker,
                    'entry_date':  pos['entry_date'],
                    'exit_date':   today.isoformat(),
                    'entry_price': entry_price,
                    'exit_price':  close_today,
                    'shares':      shares_rem,
                    'pnl_usd':     pnl,
                    'pnl_pct':     pos_pct * 100,
                    'exit_reason': reason,
                    'tier':        pos['tier'],
                })
                remove_position(ticker)
                exited_tickers.add(ticker)
                if reason == 'time_stop':
                    set_cooldown(ticker, REENTRY_COOLDOWN_DAYS)

    # Submit exit orders
    for contract, order in exit_orders:
        try:
            ib.placeOrder(contract, order)
            log.info(f"Exit order submitted: {contract.symbol}")
        except Exception as e:
            log.error(f"Exit order failed ({contract.symbol}): {e}")

    log.info(f"Exit orders submitted: {len(exit_orders)}")

    # -- Wait for market open -------------------------------------------------
    has_activity = exit_orders or pending_tickers
    if has_activity:
        wait_until_fill_window()
        ib.sleep(2)

        # -- Confirm LOO entry fills ------------------------------------------
        entries_confirmed = []
        entries_missed    = []
        filled_syms       = {f.contract.symbol: f for f in ib.fills()}

        for _, pending in pending_df.iterrows():
            ticker = pending['ticker']
            if ticker in filled_syms:
                fill         = filled_syms[ticker]
                actual_price = fill.execution.avgPrice
                log.info(f"LOO fill confirmed: {ticker} @ ${actual_price:.2f} "
                         f"(limit was ${pending['limit_price']:.2f})")
                save_position({
                    'ticker':               ticker,
                    'entry_date':           today.isoformat(),
                    'entry_price':          actual_price,
                    'shares':               pending['shares'],
                    'shares_remaining':     pending['shares'],
                    'tier':                 pending['tier'],
                    'hold_days':            pending['hold_days'],
                    'profit_target':        pending['profit_target'],
                    'partial_enabled':      pending['partial_enabled'],
                    'partial_frac':         pending['partial_frac'],
                    'partial_trigger':      pending['partial_trigger'],
                    'partial_done':         0,
                    'entry_commission':     pending['entry_commission'],
                    'consec_down_at_entry': pending['consec_down'],
                    'rsi2_at_entry':        pending['rsi2'],
                })
                remove_pending_entry(ticker)
                entries_confirmed.append(
                    f"FILLED: {ticker} {int(pending['shares'])}sh @ ${actual_price:.2f} "
                    f"(limit ${pending['limit_price']:.2f})")
            else:
                # Order did not fill -- stock gapped up past limit, or no signal today
                log.info(f"LOO did not fill: {ticker} "
                         f"(limit ${pending['limit_price']:.2f} -- likely gapped up)")
                remove_pending_entry(ticker)
                entries_missed.append(
                    f"NOT FILLED: {ticker} limit ${pending['limit_price']:.2f} "
                    f"(gapped up or cancelled)")

        # Confirm exit fills
        for contract, _ in exit_orders:
            sym = contract.symbol
            if sym in filled_syms:
                actual_exit = filled_syms[sym].execution.avgPrice
                log.info(f"Exit fill confirmed: {sym} @ ${actual_exit:.2f}")
            else:
                log.warning(f"Exit fill not confirmed for {sym} -- check IBKR manually")
    else:
        log.info("No pending entries or exits -- skipping fill wait")
        entries_confirmed = []
        entries_missed    = []

    # Final portfolio value
    for av in ib.accountValues():
        if av.tag == 'NetLiquidation' and av.currency == 'USD':
            portfolio_value = float(av.value)
            break

    ib.disconnect()
    log.info("Disconnected from IBKR")

    # Daily summary
    open_count = len(load_open_positions())
    summary = f"""NMR Morning Run - {today}

Portfolio Value : ${portfolio_value:,.2f}
Open Positions  : {open_count} / {MAX_POSITIONS}
VIX             : {vix_value:.1f}  (position size: {pos_size_pct:.0%})

EXITS ({len(exits_summary)}):
{chr(10).join('  ' + s for s in exits_summary) if exits_summary else '  None'}

ENTRIES FILLED ({len(entries_confirmed)}):
{chr(10).join('  ' + s for s in entries_confirmed) if entries_confirmed else '  None'}

ENTRIES NOT FILLED ({len(entries_missed)}):
{chr(10).join('  ' + s for s in entries_missed) if entries_missed else '  None'}
(Not filled = stock gapped up past limit overnight -- correct behavior)

Log: {LOG_PATH}
"""
    log.info(summary)
    send_alert(
        f"NMR {today} | ${portfolio_value:,.0f} | "
        f"{len(exits_summary)} exits | {len(entries_confirmed)} entries filled | "
        f"{len(entries_missed)} not filled",
        summary)


if __name__ == '__main__':
    run()
