# Naive Mean Reversion (NMR) Backtest

A survivorship-bias-free backtest of a Naive Mean Reversion strategy across all historical S&P 500 + S&P 400 MidCap + S&P 600 SmallCap constituents, automated via GitHub Actions.

---

## Current Version: V7.5 — Idea G + GOLD + SECROT + TLT Bear + Factor Rotation + VIX Call Scaling + PDBC + HYG + ZROZ

**Active strategy: V47 base logic + dynamic SPY put spread strikes (4-bucket: Idea P) + monthly VIX call spread (scaled in backwardation: Idea K) + GLD trend overlay + sector rotation momentum overlay + TLT bear overlay + QQQ/IWM factor rotation overlay + PDBC commodity overlay + HYG credit carry overlay + ZROZ panic overlay.**

V47 = V35 + four confirmed positive sizing overlays (TOM sizing, DOW sizing, partial trigger tuning, VIX RSI tightening).
Idea G = V47 + Idea D (VIX-regime-conditional put spread strikes) + Idea A (monthly VIX 20/40-call spread).
V7.3 = Idea G + GOLD overlay (7% GLD when GLD > 200d MA + rates falling) + SECROT overlay (top-3 SPDR sectors by 3m momentum, 3% each, bull regime only).
V7.4 = V7.3 + Idea I (TLT bear overlay, 8% when SPY < 200d MA + TLT > 50d MA) + Idea J (QQQ/IWM factor rotation, 6% monthly, bull regime) + Idea K (VIX call allocation doubles to 0.6% when VIX > VIX3M backwardation).
V7.5 = V7.4 + Idea N (PDBC commodity 5%, trend+momentum filtered) + Idea O (HYG credit carry 5%, ratio signal) + Idea P (SPY put 4th VIX bucket: VIX>35→25% OTM short) + Idea Q (ZROZ panic 6%, VIX>20 + TLT 5d rally).

Walk-forward validated through V47: 7/8 OOS windows positive, OOS avg CAGR 20.91%.
Idea G confirmed via backtest_ideas_v7_2.py (full history through April 2026).
V7.3 confirmed via backtest_ideas_v7_3.py (full history through April 2026).
V7.4 confirmed via backtest_ideas_v7_4_final.py (full history through April 2026).
V7.5 confirmed via backtest_ideas_v7_5_final.py (full history through April 2026).

---

## Architecture

```
backtest_ideas_v7_5_final.py  V7.5 final backtest (V7.4 + PDBC + HYG + WiderPut + ZROZ)
backtest_ideas_v7_5.py        V7.5 research: 7 ideas x 12 tests, all vs V7.4 baseline
backtest_ideas_v7_4_final.py  V7.4 final backtest (V7.3 + TLT Bear + Factor Rotation + VIX Call Scaling)
backtest_ideas_v7_4.py        V7.4 research: 6 ideas x 10 tests, all vs V7.3 baseline
backtest_ideas_v7_3.py        V7.3 combined backtest (Idea G + GOLD + SECROT overlays)
backtest_ideas_v7_2.py        Idea G combined backtest (V47 + dynamic put spread + VIX calls)
backtest_nmr_lib_v47.py       All V47 backtest logic and parameters (unchanged)
backtest-nmr-v47.py           Thin wrapper for V47 MR-only backtest
walkforward_v47.py            Walk-forward validation for V47

scan_evening.py               Live: 6:00 PM PT Sun-Thu — MR signal scan, queues signals to DB (NO orders placed)
hedge_quarterly.py            Live: 6:05 PM PT Mon-Fri — SPY put spread + VIX call spread (Idea K)
overlay_etf.py                Live: 12:30 PM PT Mon-Fri — GOLD + SECROT + TLT Bear + Factor + PDBC + HYG + ZROZ via MOC
trade_morning.py              Live: 6:00 AM PT Mon-Fri — places MKT entry orders, submits exits, confirms fills, pushes to GitHub
intraday_update.py            Live: Every 30 min — connects IBKR, reads live portfolio, updates summary.json, pushes to GitHub
manual_enter.py               Manual: places MKT orders for pending entries (emergency use)
push_fills.py                 Manual: rewrites summary.json from DB and pushes to GitHub
check_ibkr_positions.py       Diagnostic: verifies IBKR positions vs DB, flags unexpected positions
health_check.py               Diagnostic: UNIFIED health check — MR positions + overlays + system status (USE THIS DAILY)
check_positions.py            Diagnostic: MR position audit only (superseded by health_check.py)
check_overlays.py             Diagnostic: overlay P&L only (superseded by health_check.py)
verify_all.py                 Diagnostic: 55+ system checks — run after any script change
reconcile_db.py               Manual: interactive DB/IBKR reconciliation (removes stale, adds missing)
reset_all.py                  Emergency: sells all MR positions, clears DB (use with EXTREME caution)
reset_missing_overlays.py     One-time: resets overlay DB entries so overlay_etf.py re-buys them
reset_qqq.py                  One-time: resets QQQ factor_position when order was rejected by IBKR
fix_cvna_split.py             One-time: adjusted CVNA 5-for-1 split in DB (May 2026)
fix_capital_cap.py            One-time patch: adds $100k portfolio cap to scan_evening.py and trade_morning.py
fix_capital_cap2.py           One-time patch: adds buying power check to trade_morning.py entry loop
fix_capital_deployed2.py      One-time patch: fixes capital deployed calculation in intraday_update.py
fix_earnings_blackout.py      One-time patch: (reverted — see Lessons Learned)
revert_earnings_fix.py        One-time patch: reverts earnings fix back to backtest-consistent behavior
fix_intraday_unicode.py       One-time patch: removes Unicode box-drawing chars from intraday_update.py
fix_overlay_buying_power.py   One-time patch: adds buying power check to overlay_etf.py place_moc_order
fix_overlay_rejection.py      One-time patch: overlay_etf.py now returns False if IBKR rejects order
fix_auto_reconcile.py         One-time patch: adds auto DB reconciliation to trade_morning.py
fix_split_detection.py        One-time patch: adds stock split detection to trade_morning.py
fix_stale_port.py             One-time patch: removes stale _port reference from intraday_update.py
fix_overlay_port2.py          One-time patch: rewrites overlay live P&L block to use ibkr_positions dict
check_overlay_schemas.py      Diagnostic: prints all overlay DB table schemas and current data
```

**Four-script live execution:**
- `scan_evening.py`    — 6:00 PM PT Sun-Thu, scans universe, saves signal candidates to DB (no IBKR orders)
- `hedge_quarterly.py` — 6:05 PM PT Mon-Fri, manages SPY put spread + VIX call spread
- `overlay_etf.py`     — **12:30 PM PT Mon-Fri** (changed from 6:10 PM), manages all ETF overlays via MOC
- `trade_morning.py`   — 6:00 AM PT Mon-Fri, places MKT entry orders, exits, confirms fills, pushes to GitHub

**CRITICAL: overlay_etf.py runs at 12:30 PM PT (3:30 PM ET)** — 30 minutes before market close, within the valid MOC submission window. Previously ran at 6:10 PM PT which was after market close — MOC orders were accepted by IBKR but then cancelled overnight before execution. Changed via Task Scheduler in May 2026.

**overlay_etf.py writes to `C:\nmr-trader\overlay.log`** (separate from trade.log). Check this file when debugging overlay issues.

**Critical timing note:** MOO/LOO (OPG) orders are only valid 7:00–9:28 AM ET. MOC orders must be submitted before 3:45 PM ET. scan_evening.py saves signals to DB only. trade_morning.py places MKT orders at 6:00 AM PT (9:00 AM ET).

---

## Live Infrastructure

### File Locations

| Component | Path |
|---|---|
| Scripts | `C:\nmr-trader\` |
| Git repo (local) | `C:\naive-mean-reversion\` |
| Database | `C:\nmr-trader\positions.db` |
| Trade log | `C:\nmr-trader\trade.log` |
| Overlay log | `C:\nmr-trader\overlay.log` |
| IBC config | `C:\Users\bkcol\Documents\IBC\config.ini` |
| IBC bat file | `C:\IBC\StartGateway.bat` |
| Gateway exe | `C:\Jts\ibgateway\1037\ibgateway.exe` |
| Dashboard JSON | `C:\naive-mean-reversion\paper_trading\summary.json` |
| Dashboard URL | https://ckurau.github.io/naive-mean-reversion/ |

### IBKR Account

| Item | Detail |
|---|---|
| Paper account | DUP671219 |
| Paper username | `tlpxbr648` |
| Live username | `colbykurau` |
| Paper port | 4002 |
| Live port | 4001 |
| Starting equity | $100,000 |

### Task Scheduler — Current State

| Task | Time (PT) | Days | Status |
|---|---|---|---|
| IBC Gateway | 6:00 AM | Sun-Fri | DISABLED (bat file just runs exit — harmless) |
| Scan Evening | 6:00 PM | Sun-Thu | ACTIVE |
| Hedge Quarterly | 6:05 PM | Mon-Fri | ACTIVE |
| Overlay ETF | **12:30 PM** | Mon-Fri | ACTIVE (changed from 6:10 PM) |
| NMR Trader (trade_morning) | 6:00 AM | Mon-Fri | ACTIVE |
| NMR Intraday Update | Every 30min | Daily | ACTIVE |

**Scan Evening runs Sunday** because it queues signals for Monday's open. Friday scan is skipped.

---

## IBKR Gateway — Connectivity (CRITICAL)

### Daily Maintenance Window
IBKR disconnects all Gateway sessions every night: **11:45 PM – 12:45 AM ET (8:45 PM – 9:45 PM PT)**. Gateway must be manually logged in before this window.

### Current Setup (as of May 2026)
- **IBC auto-login is DISABLED** — `C:\IBC\StartGateway.bat` contains only `exit`
- **IBC Gateway Task Scheduler task is DISABLED**
- **Reason:** IBC kept locking the IBKR account. IBKR's paper account security model blocks automated logins.
- **Manual login required:** Log in before **8:40 PM PT** each evening.
- **Permanent solution:** Linux VPS migration with IBC running headlessly via Xvfb.

### Going Live — Three Changes Only
1. `IBKR_PORT = 4001` (was 4002 paper) in all four main scripts
2. Switch Gateway from Paper to Live account
3. Level 3 options approval on real account before running hedge_quarterly.py

---

## Daily Operations

### Daily Command (run after market close)
```cmd
C:\nmr-trader\venv\Scripts\python.exe C:\nmr-trader\health_check.py
```
This single command checks everything: Gateway, capital deployed, DB/IBKR sync, every MR position against strategy rules, every overlay IN/OUT status with P&L, pending signals for tomorrow, and summary of all issues.

### What to Expect Each Day
- **6:00 AM PT** — trade_morning.py runs: exits (profit target/time stop), new entries with buying power check, auto split detection, auto DB reconciliation
- **12:30 PM PT** — overlay_etf.py runs: checks overlay signals, places MOC buy/sell orders at 3:30 PM ET close
- **6:00 PM PT** — scan_evening.py runs: queues MR signals for tomorrow morning
- **Every 30 min** — intraday_update.py: live P&L, capital deployed, overlay P&L on dashboard
- **Before 8:40 PM PT** — manually log into Gateway before maintenance window

### Emergency Commands
```cmd
:: Check if Gateway is up
netstat -an | findstr "4002"

:: Force dashboard update
C:\nmr-trader\venv\Scripts\python.exe C:\nmr-trader\push_fills.py

:: Reconcile DB vs IBKR (interactive)
C:\nmr-trader\venv\Scripts\python.exe C:\nmr-trader\reconcile_db.py

:: Check IBKR positions vs DB
C:\nmr-trader\venv\Scripts\python.exe C:\nmr-trader\check_ibkr_positions.py

:: Run intraday update manually
C:\nmr-trader\venv\Scripts\python.exe C:\nmr-trader\intraday_update.py
```

---

## Capital Deployment — Important Notes

### Buying Power Enforcement (May 2026)
Both `trade_morning.py` and `overlay_etf.py` now check `AvailableFunds` from IBKR before placing any BUY order:
- `trade_morning.py` — fetches available cash before entry loop, estimates each order's cost using prior close, skips orders that would exceed remaining cash
- `overlay_etf.py` — checks available cash inside `place_moc_order()` for BUY orders only; if yfinance price fetch fails, uses conservative fallback (shares × $50 minimum) rather than $0
- Both: SELL orders always go through regardless of buying power

### Paper Trading vs Real Account
In paper trading, capital deployed may show inflated values. In a real cash account, IBKR auto-rejects orders exceeding buying power — no code changes needed.

### Capital Cap in Scripts
`scan_evening.py` and `trade_morning.py` cap position sizing at `min(portfolio_value, 100000.0)` so sizing never inflates beyond $100k even when paper portfolio shows higher values due to stale phantom positions.

---

## Database Tables

| Table | Purpose |
|---|---|
| `open_positions` | Currently held MR positions |
| `pending_entries` | Signals queued by scan_evening.py for next morning |
| `trade_log` | All closed MR trades (entry/exit price, P&L, reason) |
| `cooldown` | Tickers in re-entry cooldown after time-stop (5-day) |
| `gold_position` | GOLD overlay state |
| `secrot_positions` | SECROT sector ETF positions |
| `tlt_bear_position` | TLT Bear overlay state |
| `factor_position` | QQQ/IWM Factor rotation state |
| `pdbc_position` | PDBC commodity overlay state |
| `hyg_position` | HYG credit carry overlay state |
| `zroz_position` | ZROZ panic overlay state |

### open_positions Schema
Key columns: `ticker TEXT (PK)`, `entry_date TEXT`, `entry_price REAL`, `shares REAL`, `shares_remaining REAL`, `tier INTEGER`, `hold_days INTEGER`, `profit_target REAL`, `partial_enabled INTEGER`, `partial_frac REAL`, `partial_trigger REAL`, `partial_done INTEGER`, `entry_commission REAL`, `consec_down_at_entry INTEGER`, `rsi2_at_entry REAL`

**Note:** `hold_days` is NOT updated daily. Always calculate from `entry_date` using `pd.bdate_range(entry_date, today)`.

### Auto-Reconciliation (trade_morning.py — May 2026)
Every morning after fills are confirmed, trade_morning.py automatically:
1. **Detects stock splits** — compares IBKR share counts vs DB, adjusts shares and entry_price for known ratios (2x, 3x, 4x, 5x, 10x, 0.5x, 0.25x)
2. **Removes stale DB entries** — deletes positions where IBKR shows 0 shares
3. **Adds missing DB entries** — adds positions IBKR holds that aren't in DB
No manual intervention needed for these cases.

---

## Dashboard (GitHub Pages)

**URL:** https://ckurau.github.io/naive-mean-reversion/
**Auto-refresh:** Every 5 minutes
**Mobile:** Open URL in Safari → Share → Add to Home Screen

**Sections:**
- KPI cards: Portfolio, Positions, Win Rate, VIX, Today, Overlay 30d P&L, Unrealized P&L, Capital Deployed
- **Live Overlay P&L** — real-time overlay positions with entry/current price, unrealized P&L (updated every 30 min via intraday)
- Open MR Positions table
- Last Scan signals
- Trade log

**overlay_live field** in summary.json: written by intraday_update.py every 30 min using `ibkr_positions` dict (captured before disconnect). Shows SECROT, FACTOR, PDBC, HYG, GOLD, TLT, ZROZ each with IN/OUT status, shares, entry, price, P&L. SPY put spread legs preserved from previous push.

---

## Best Confirmed Results

### V7.5 — Full History Run (April 2026) — COMBINED EQUITY

| Metric | Value | Notes |
|---|---|---|
| CAGR (MR-only basis) | 28.88% | MR engine unchanged from V47 |
| CAGR (combined equity) | 34.75% | MR + all nine overlays |
| Final Equity (combined) | $77,488,411 | |
| Max Drawdown (combined) | -57.25% | |
| Sharpe (combined) | 1.08 | |
| Win Rate | 60.24% | MR-only, unchanged |
| Total MR trades | 22,041 | |
| SPY put net P&L | +$8,503,102 | |
| VIX call net P&L | +$18,762,734 | |
| GOLD overlay net P&L | +$6,304,696 | |
| TLT Bear net P&L | +$1,452,352 | |
| SECROT overlay net P&L | +$7,396,436 | |
| Factor rotation net P&L | +$3,789,082 | |
| PDBC Commodity net P&L | +$6,113,922 | NEW — Idea N |
| HYG Credit net P&L | +$613,872 | NEW — Idea O |
| ZROZ Panic net P&L | +$1,111,189 | NEW — Idea Q |
| Total overlay net P&L | +$54,047,384 | Nine overlays combined |

### V7.5 Year-by-Year (Combined Equity)

| Year | End Equity | P&L |
|---|---|---|
| 2004 | $122,105 | +$22,105 |
| 2005 | $169,133 | +$47,027 |
| 2006 | $238,997 | +$69,864 |
| 2007 | $324,737 | +$85,740 |
| 2008 | $520,758 | +$196,021 |
| 2009 | $975,484 | +$454,726 |
| 2010 | $1,422,964 | +$447,480 |
| 2011 | $2,336,017 | +$913,054 |
| 2012 | $2,995,440 | +$659,423 |
| 2013 | $5,168,634 | +$2,173,194 |
| 2014 | $6,089,778 | +$921,143 |
| 2015 | $8,066,881 | +$1,977,103 |
| 2016 | $9,671,046 | +$1,604,165 |
| 2017 | $14,623,112 | +$4,952,067 |
| 2018 | $13,506,421 | -$1,116,692 |
| 2019 | $25,623,334 | +$12,116,913 |
| 2020 | $46,110,071 | +$20,486,737 |
| 2021 | $57,944,450 | +$11,834,379 |
| 2022 | $51,442,999 | -$6,501,451 |
| 2023 | $55,257,161 | +$3,814,162 |
| 2024 | $74,950,100 | +$19,692,940 |
| 2025 | $82,229,032 | +$7,278,932 |
| 2026 | $77,488,411 | -$4,740,622 |

### Strategy Comparison

| Strategy | CAGR | Equity | MaxDD | Sharpe |
|---|---|---|---|---|
| **V7.5 (current)** | **34.75%** | **$77.5M** | **-57.25%** | **1.08** |
| V7.4 | 32.85% | $57.0M | -57.17% | 1.04 |
| V7.3 | 29.30% | $30.9M | -56.62% | 0.96 |
| V48 / Idea G | 24.38% | $18.3M | -56.91% | 0.74 |
| V47 + Idea 3 | 22.40% | $9.9M | -60.89% | 0.74 |
| V47 (no hedge) | 19.54% | $4.6M | -56.84% | 0.72 |
| V32d | 15.37% | $2.1M | -39.21% | 0.77 |

---

## V7.5 Strategy Rules

### MR Rules (V47, unchanged)

| Rule | Detail |
|---|---|
| Universe | S&P 500 + S&P 400 MidCap + S&P 600 SmallCap (current + historical) |
| Trend filter | Stock must be above its 200-day SMA |
| Entry signal | 4+ consecutive down days AND RSI(2) < 20 AND ATR > 1% AND volume > 20-day avg AND dollar volume > $5M/day |
| Entry execution | Buy at open via MKT order placed at 6:00 AM PT (9:00 AM ET) |
| Gap filters | Skip if next open gaps down > 1.0% OR gaps up > 2% |
| Exit — all tiers | 2% profit target OR 8-day time stop (checked on prior day's closing price) |
| Tier 1 partial | 6+ down days: 50% at 0.8%, remainder at 2% |
| Tier 2 | 5 down days: 2% target, 8-day window |
| Tier 3 | 4 down days: 2% target, 8-day window |
| Min hold | 2 trading days before profit exit |
| Max positions | 60 simultaneous holdings |
| Position size base | VIX < 25 → 9%, VIX >= 25 → 5% |
| Tiered sizing | Top 20% of signals by composite score get 1.3x, hard cap 12% |
| TOM sizing | Last trading day of month + next 3: 1.15x multiplier |
| DOW sizing | Tuesday: 1.10x, Friday: 0.90x |
| VIX RSI tight | When VIX < 15: require RSI(2) < 15 |
| Signal ranking | Composite score: RSI(2) / ATR_pct (NOT tier — backtest-consistent) |
| Sector filter | Skip if stock's sector ETF below 20-day MA |
| Correlation cap | Max 3 open positions in same sector |
| Earnings blackout | Skip within +/-3 days of earnings (confirmed dates only) |
| SPY regime | No new entries when SPY below 200-day MA |
| Re-entry cooldown | No re-entry for 5 days after time-stop |
| Velocity crash pause | SPY 5-day return < -12% → pause entries 5 days |
| Earnings month cap | Position size capped at 2.4% in Jan/Apr/Jul/Oct |

**Exit logic note:** Exit decision made on prior day's closing price, executed at next morning's open (MKT order). Gap risk (stock closes +2% then opens -5%) is fully modeled in the backtest and accepted.

**Signal ranking note:** Signals are ranked by composite score (RSI/ATR), NOT by tier. Tier 1 is NOT prioritized over Tier 3 for entry — this matches the backtest. Tier affects position size and partial exit logic only.

**Earnings blackout note:** yfinance returns no earnings data for ~80% of stocks. Only block when yfinance CONFIRMS an earnings date within +/-3 days. Missing data = allowed through. This matches backtest behavior. CENTA (May 2026) slipped through because yfinance returned no data despite earnings on May 6 — accepted risk, behavior intentionally unchanged.

### Overlay Specifications

**SPY Put Spread (hedge_quarterly.py):**
VIX<15: 3%/13% OTM | VIX 15-25: 5%/15% | VIX 25-35: 8%/20% | VIX>35: 8%/25% (Idea P). Target DTE: 63 trading days. Max debit: $15. Auto-rolls when <=5 days to expiry.

**VIX Call Spread (hedge_quarterly.py):**
20/40-strike monthly. Standard: 0.3%/month. Idea K: 0.6%/month when VIX > VIX3M (backwardation). Max debit: $5. Auto-rolls every ~21 trading days.

**GOLD:** GLD when GLD > 200d MA AND TLT 20d slope >= 0. 7% allocation. MOC via overlay_etf.py at 12:30 PM PT.

**SECROT:** Top-3 SPDR sectors by 63d momentum. 3% each (9% total). Monthly rebalance. Bull regime only. MOC via overlay_etf.py.

**TLT Bear (Idea I):** TLT when SPY < 200d MA AND TLT > 50d MA. 8% allocation. Bear regime only. MOC via overlay_etf.py.

**Factor Rotation (Idea J):** QQQ or IWM (stronger 63d momentum). 6% allocation. Monthly rebalance. Bull regime only. MOC via overlay_etf.py.

**PDBC Commodity (Idea N):** PDBC when PDBC > 100d MA AND DBC 63d momentum > 0. 5% allocation. No regime filter. MOC via overlay_etf.py.

**HYG Credit Carry (Idea O):** HYG when HYG/LQD ratio > 20d MA. 5% allocation. Bull regime only. MOC via overlay_etf.py.

**ZROZ Panic (Idea Q):** ZROZ when VIX > 20 AND TLT 5d return > 0.5%. 6% allocation. Fires on acute panic events. MOC via overlay_etf.py.

---

## Paper Trading Lessons Learned (April–May 2026)

### Gateway Connectivity

Manual login before 8:40 PM PT required every night. IBC disabled. See IBKR Gateway section.

### Order Type Issues

**MOC orders must be submitted before 3:45 PM ET.** overlay_etf.py was running at 6:10 PM PT (after close) — orders were accepted by IBKR but cancelled overnight before execution. Fixed by changing Task Scheduler to 12:30 PM PT.

**MKT DAY orders for MR entries** — placed at 6:00 AM PT, execute at 9:30 AM ET open.

### Stock Splits

**CVNA 5-for-1 split (May 7, 2026):** Dashboard showed -80% P&L because yfinance returned split-adjusted price while DB still had pre-split entry price. Fixed manually with fix_cvna_split.py. Going forward, trade_morning.py auto-detects splits by comparing IBKR share counts vs DB and adjusting shares/entry_price automatically.

### Reset and Cleanup Issues

**NEVER run reset_all.py when IBKR has pending orders or partially closed positions.** This creates short positions. In April/May 2026, a system reset created 8 short positions (ALGN, COHR, CYTK, GRMN, PCG, PLUS, TGTX, VFC) that required days to clean up, caused margin violation warnings, and triggered one IBKR auto-liquidation of 12 APH shares.

**Verify before any reset:** Run check_ibkr_positions.py first. Never manually sell positions and then also run a reset.

### DB/IBKR Sync

trade_morning.py now auto-reconciles DB vs IBKR every morning after fills:
- Removes stale DB entries (positions closed but still in DB)
- Adds missing DB entries (positions in IBKR but not in DB — e.g. GMED May 2026)
- Detects splits automatically

If you ever need manual reconciliation: run reconcile_db.py (interactive, asks confirmation before changes).

### Capital Over-Deployment

With 28 MR positions + overlays, paper account showed $168k+ deployed on a $99k portfolio. Root causes:
1. trade_morning.py had no buying power check — bought all queued signals regardless of cash
2. overlay_etf.py had no buying power check — placed MOC orders regardless of cash
3. Buying power check used est_cost=0 when yfinance failed, bypassing the check

All three fixed in May 2026. Both scripts now check AvailableFunds before each BUY order. overlay_etf.py also checks order status after placement and returns False (skips DB update) if IBKR rejects the order.

### Overlay Order Rejection

IBKR rejects overlay MOC orders when over margin. overlay_etf.py previously updated the DB to `in_position=1` before checking if IBKR accepted the order, leaving DB out of sync. Fixed: now waits 1.5 seconds after order placement, checks status, and returns False if status is Inactive/Cancelled — preventing DB update on rejection.

### Overlay Timing

overlay_etf.py previously ran at 6:10 PM PT after market close. MOC orders were accepted by IBKR but queued for next day's close, then expired/cancelled overnight. Fixed: changed to 12:30 PM PT (3:30 PM ET) — 30 minutes before 4:00 PM ET close.

### JSON Corruption

summary.json appeared corrupted due to browser reading file simultaneously with intraday write. File is valid — timing artifact. No fix needed.

### Earnings Filter Reliability

yfinance misses ~80% of earnings dates. Original backtest behavior preserved: only block confirmed dates. Do NOT exclude tickers with missing earnings data.

---

## Diagnostic Scripts — Usage Guide

### health_check.py (PRIMARY — use this daily)
```cmd
C:\nmr-trader\venv\Scripts\python.exe C:\nmr-trader\health_check.py
```
Checks: Gateway + capital + trade/overlay log errors + DB/IBKR sync + all MR positions (exit status, P&L, splits, earnings) + all overlays (IN/OUT, DB vs IBKR, P&L) + pending signals + summary of all issues.

### verify_all.py (run after any script change)
```cmd
C:\nmr-trader\venv\Scripts\python.exe C:\nmr-trader\verify_all.py
```
NOTE: "Task: IBC Gateway" FAIL is a false positive — task was intentionally disabled.

### Other Scripts
```cmd
:: After any manual intervention
C:\nmr-trader\venv\Scripts\python.exe C:\nmr-trader\check_ibkr_positions.py

:: Force dashboard update
C:\nmr-trader\venv\Scripts\python.exe C:\nmr-trader\push_fills.py

:: Interactive DB reconciliation
C:\nmr-trader\venv\Scripts\python.exe C:\nmr-trader\reconcile_db.py
```

### Quick DB checks (save as .py files, don't run inline in CMD)
CMD cannot handle multi-line Python. Always save to a .py file and run with venv Python.

---

## VPS Migration Checklist

### Scripts to migrate (C:\nmr-trader\)
- scan_evening.py, trade_morning.py, hedge_quarterly.py, overlay_etf.py
- intraday_update.py, manual_enter.py, push_fills.py
- check_ibkr_positions.py, health_check.py, verify_all.py, reconcile_db.py
- positions.db (SQLite — all overlay state, open positions, trade log)

### Port changes for live account
Change `IBKR_PORT = 4002` to `IBKR_PORT = 4001` in all four main scripts.

### Linux-specific setup
1. Install IBC for Linux (Xvfb virtual display)
2. systemd service for Gateway auto-restart
3. pip install ib_async yfinance pandas numpy requests
4. Cron jobs (PT timezone):

```
# scan_evening — 6 PM PT Sun-Thu
0 18 * * 0,1,2,3,4 /venv/bin/python /scripts/scan_evening.py

# hedge_quarterly — 6:05 PM PT Mon-Fri
5 18 * * 1,2,3,4,5 /venv/bin/python /scripts/hedge_quarterly.py

# overlay_etf — 12:30 PM PT Mon-Fri (3:30 PM ET, before market close)
30 12 * * 1,2,3,4,5 /venv/bin/python /scripts/overlay_etf.py

# trade_morning — 6:00 AM PT Mon-Fri
0 6 * * 1,2,3,4,5 /venv/bin/python /scripts/trade_morning.py

# intraday_update — every 30 min
*/30 * * * * /venv/bin/python /scripts/intraday_update.py
```

---

## Going Live — Pass Criteria

| Check | Target | Action if failing |
|---|---|---|
| Win rate | 57-63% over 100+ trades | Stop — review signal logic |
| Trades per month | 65-90 | Check universe fetch and signal parameters |
| Worst single month | Better than -15% | Review if repeated |
| Script ran every trading day | 100% | Fix Gateway startup |
| Slippage vs prior close | Under 0.6% avg | Higher for small-caps expected |
| Gateway connectivity | 0 missed mornings | VPS migration required |

---

## Bugs Fixed (April–May 2026)

**Bug 1 — Stray PowerShell line in trade_morning.py:** NameError crash before fill confirmation. Positions never saved to DB for weeks.

**Bug 2 — ClientId mismatch:** scan_evening.py used clientId=10, trade_morning.py used clientId=1. IBKR only returns fills to same clientId.

**Bug 3 — LOO orders wiped by IBKR nightly reset:** Fixed by moving to pending_entries DB at 6 PM, MKT orders at 6 AM.

**Bug 4 — MOO/LOO ValidationError 321 at 6 PM PT:** OPG orders only valid 7:00-9:28 AM ET. Fixed: order placement moved to trade_morning.py.

**Bug 5 — trade_morning.py Task Scheduler at 6:15 AM PT:** Only 13 min before OPG cutoff. Fixed: changed to 6:00 AM PT.

**Bug 6 — capital cap crashing when portfolio_value is None:** `min(portfolio_value, 100000.0)` crashes on None. Fixed with None check.

**Bug 7 — scan_evening.py crash after DB reset:** Same None issue. Same fix.

**Bug 8 — IBC config.ini overriding bat file credentials:** config.ini takes priority. Wrong password caused account lockouts.

**Bug 9 — intraday git pull corrupting index.html:** git pull overwrote dashboard with stale version. Removed git pull from intraday.

**Bug 10 — Unicode box-drawing chars in summary.json:** 468 Unicode chars in intraday_update.py comments leaked into JSON. Fixed by fix_intraday_unicode.py.

**Bug 11 — overlay_etf.py running at 6:10 PM PT (after market close):** MOC orders expired overnight. Fixed: changed to 12:30 PM PT via Task Scheduler.

**Bug 12 — overlay_etf.py updating DB to in_position=1 before confirming IBKR acceptance:** DB showed overlays as held when orders were rejected. Fixed: place_moc_order now waits 1.5s, checks status, returns False if rejected.

**Bug 13 — buying power check using est_cost=0 when yfinance fails:** Bypassed the check entirely. Fixed: conservative fallback of shares * $50 when yfinance unavailable.

**Bug 14 — trade_morning.py placing all queued signals regardless of available cash:** No buying power check. All 13 signals bought even with only $46k available. Fixed: fix_capital_cap2.py adds AvailableFunds check before each entry.

**Bug 15 — DB/IBKR sync after exits and resets:** Stale positions remained in DB after exit. Missing positions (GMED) not added to DB. Fixed: trade_morning.py auto-reconciles every morning.

**Bug 16 — Stock splits showing incorrect P&L:** CVNA 5-for-1 split showed -80% in dashboard because DB had pre-split price. Fixed: trade_morning.py auto-detects splits by comparing IBKR vs DB share counts.

**Bug 17 — _port reference error in intraday_update.py:** Stale `_port` variable on line 142 caused IBKR connection failure every intraday run. Fixed by fix_stale_port.py.

**Bug 18 — overlay live P&L showing $0 for all overlays:** intraday_update.py was calling ib.portfolio() after disconnect. Fixed: uses ibkr_positions dict (captured before disconnect) instead.

---

## Do-Not-Retry Table

| Approach | Why It Failed |
|---|---|
| Price-based stop-losses (-3%) | 22.6% hit stop then bounced |
| Portfolio-level halt at -10% DD | Fired permanently 2004-2006 |
| Streak filter (3 losses=50% size) | MaxDD -8pp but CAGR -4.72pp |
| Rolling WR adaptive sizing | MaxDD -7pp but CAGR -3.71pp |
| Equity curve trading | CAGR -3.30pp, MaxDD unchanged |
| Continuous vol-scaled sizing | CAGR -2.07pp, MaxDD -1pp |
| Friday entry filter | -$1,340k |
| Breadth filter | -$2,899k |
| Bond allocation in bear regime | -$2,113 |
| Gap filter tightening to -0.75% | CAGR -2.59pp |
| Idea_C VVIX-gated sizing | Dead |
| Idea_E Gap-behavior sizing | Dead |
| Idea_F Day-5 partial time-stop | CAGR -2.49pp |
| Idea_B CDaR scaling | Too much CAGR drag |
| Idea_H Convexity-adjusted exit | -0.65pp CAGR, -$3.3M |
| Idea_L DBC commodity tilt on SECROT | -0.06pp, -$315k |
| Idea_M Tier1 extended sizing (15% cap) | +$137k over 22 years — not worth complexity |
| Idea_R SPY OTM call in low-VIX | -0.91pp CAGR, -$8.1M |
| Idea_T USMV late-cycle defensive tilt | Zero effect |
| IBC auto-login on Windows paper account | Account lockouts |
| MOO orders placed at 6 PM PT | ValidationError 321 |
| MOC orders placed at 6:10 PM PT (after close) | Orders accepted then cancelled overnight |
| Excluding all tickers with missing yfinance earnings data | Eliminates ~80% of signals |
| Running reset_all.py when IBKR has pending orders | Creates short positions |
| Manually selling positions then running a reset | Double-sell creates shorts |
| git pull in intraday_update.py | Overwrites index.html |
| Intraday exits (checking prices during market hours) | Different strategy — requires new backtest |
| Prioritizing Tier 1 over Tier 3 for entry when funds are limited | Not backtest-consistent — signals ranked by score (RSI/ATR) not tier |
| Adding scan cap to limit number of signals queued | No cap added — paper trading benefits from more trades for win rate sample size; real account enforced by IBKR buying power rejection |

---

## Walk-Forward Validation

### V47 Walk-Forward (PASS — April 2026)

| Window | OOS Period | CAGR | MaxDD | Sharpe | Regime |
|---|---|---|---|---|---|
| W1 | 2009-2010 | 28.3% | -14.5% | 1.23 | Recovery |
| W2 | 2011-2012 | 26.0% | -35.4% | 0.73 | Chop/Dip |
| W3 | 2013-2014 | 41.2% | -34.1% | 1.27 | Bull |
| W4 | 2015-2016 | 15.8% | -18.3% | 0.84 | Chop |
| W5 | 2017-2018 | 12.0% | -31.5% | 0.47 | Low-Vol Bull |
| W6 | 2019-2020 | 51.8% | -36.3% | 1.19 | Bull+Crash |
| W7 | 2021-2022 | -12.7% | -48.0% | -0.36 | Bear Grind |
| W8 | 2023-2025 | 4.8% | -57.0% | 0.36 | AI Bull + Tariff Bear |

OOS Positive: 7/8 | OOS Avg CAGR: 20.91%

---

## Optimism Bias Warnings

| Source | Estimated CAGR Impact |
|---|---|
| Slippage on open prices | -2 to -3% |
| Survivorship bias | -1 to -2% |
| Overfitting across 70+ iterations | -2 to -3% |
| VIX call pricing vs model assumptions | -0.5 to -1% |
| TOM/DOW/VIX parameters tuned to history | -1 to -2% |
| GOLD/SECROT overlay parameter fitting | -0.5 to -1% |
| TLT/Factor/VIX3M overlay parameter fitting | -0.5 to -1% |
| PDBC/HYG/ZROZ overlay parameter fitting | -0.5 to -1% |
| Cash constraint (overlays use ~28% of $100k) | See cash-constrained backtest below |
| **Realistic live estimate (cash-constrained backtest)** | **~20% CAGR gross** |

## Cash-Constrained Backtest Results (May 2026)

The original V7.5 backtest used a **notional overlay model** — overlays earned percentage returns on the full portfolio value without deploying real cash, simultaneously with MR positions. This is not achievable in a real $100k cash account.

A corrected **cash-constrained backtest** (`backtest_v75_cash_constrained.py`) was run where:
- All overlays deploy real cash from the same pool as MR positions
- MR entries only use cash remaining after overlays are deployed
- No leverage — total deployment capped at $100k at all times

### Cash-Constrained Results vs Notional

| Metric | V7.5 Notional | Cash-Constrained | Delta |
|---|---|---|---|
| CAGR (MR-only) | 28.88% | **16.17%** | -12.71pp |
| CAGR (combined) | 34.75% | **20.25%** | -14.50pp |
| Final Equity | $77,488,411 | **$6,174,856** | — |
| Max Drawdown | -57.25% | **-13.32%** | +43.93pp better |
| Sharpe | 1.08 | **1.50** | +0.42 better |
| Win Rate (MR) | 60.24% | 60.91% | unchanged |
| Total MR trades | 22,041 | 10,832 | ~half (cash-limited) |

### Cash-Constrained Year-by-Year

| Year | End Equity | Annual P&L |
|---|---|---|
| 2004 | $107,995 | +$7,995 |
| 2005 | $116,852 | +$8,857 |
| 2006 | $143,168 | +$26,316 |
| 2007 | $156,198 | +$13,030 |
| 2008 | $236,967 | +$80,769 |
| 2009 | $385,680 | +$148,713 |
| 2010 | $440,251 | +$54,572 |
| 2011 | $605,296 | +$165,045 |
| 2012 | $710,139 | +$104,843 |
| 2013 | $938,972 | +$228,834 |
| 2014 | $1,009,381 | +$70,409 |
| 2015 | $1,123,685 | +$114,304 |
| 2016 | $1,305,653 | +$181,967 |
| 2017 | $1,373,748 | +$68,095 |
| 2018 | $1,581,552 | +$207,804 |
| 2019 | $1,709,458 | +$127,907 |
| 2020 | $2,741,682 | +$1,032,223 |
| 2021 | $3,304,493 | +$562,811 |
| 2022 | $3,444,871 | +$140,378 |
| 2023 | $4,056,020 | +$611,149 |
| 2024 | $5,143,604 | +$1,087,584 |
| 2025 | $6,111,752 | +$968,148 |
| 2026 | $6,174,856 | +$63,104 |

### Key Insights from Cash-Constrained Results

**20.25% CAGR is the realistic target** — not 34.75%. The notional model inflated results by allowing overlays to earn returns on the same capital as MR positions simultaneously.

**Max drawdown drops from -57% to -13%** — a major improvement. The cash constraint forces smaller MR positions during periods when overlays are deployed, naturally reducing risk.

**Sharpe improves from 1.08 to 1.50** — better risk-adjusted returns because the strategy is more selective about entries when cash is scarce.

**Only half the MR trades execute** (10,832 vs 22,041) — the primary cost of the cash constraint. Overlays occupy ~28% of capital in bull markets, leaving less room for MR entries.

**Overlays still add value** — $3.6M total vs $6.1M from MR alone. Each overlay dollar earns about the same as an MR dollar but with less correlation to the market.

**Realistic live expectations:**
- Gross CAGR: ~20% (cash-constrained backtest, pre-slippage/tax)
- After slippage (-2 to -3%): ~17-18%
- After short-term capital gains tax (32-37%): **~11-13% net**
- This is still excellent vs S&P 500 long-term average of ~10% gross / ~7-8% after tax

Overlay overfitting assessment: HYG (+$613k over 22 years) and ZROZ (+$1.1M) are marginal and most likely to underperform live. VIX calls, SPY puts, SECROT, and FACTOR have stronger economic rationale and academic support. Most durable: VIX calls and SPY puts.

---

## The Honest Risk Picture

- -57.25% combined MaxDD at peak equity
- Overlay carry cost: ~0.75%/quarter (puts) + ~0.30-0.60%/month (VIX calls) = ~6.6-9% annually
- 2022: MR lost ~$1.6M; puts paid $659k; VIX calls paid ~$1.2M — cushioned
- 2025: MR lost ~$777k; puts paid $1.13M; VIX calls paid ~$1.4M — net positive

---

## Research History

| Ideas Session | Key Finding |
|---|---|
| Ideas V2 | Idea 3 SPY put spread confirmed |
| Ideas V3 | No ideas improved on V35+I3 |
| Ideas V4 | Ranking enhancements zero effect (60-position cap) |
| Ideas V5 | TOM/DOW/VIX-RSI sizing — became V47 |
| Ideas V6 | V47+I3 confirmed ceiling at $9.9M / 22.40% CAGR |
| Ideas V7 | VIX call spread model bug fixed. Idea E dead. |
| Ideas V7.1 | Idea D dynamic strikes: +0.42pp CAGR |
| Ideas V7.2 | Idea G (D+A): +1.94pp CAGR, +$8.35M. V48 chosen. |
| V49 research | GOLD, SECROT on V35 — MaxDD worsened without crash protection |
| Ideas V7.3 | GOLD + SECROT on Idea G baseline — MaxDD +4.69pp. V7.3 chosen. |
| Live bugs found | MOO ValidationError. Fix: trade_morning.py at 6 AM PT. |
| Ideas V7.4 | I+J+K: 32.85% CAGR, $56.5M. Overlays exceed MR P&L. |
| Ideas V7.5 | N+O+P+Q: 34.75% CAGR, $77.5M. Nine overlays = $54M. |
| Paper trading (Apr-May 2026) | 18 bugs fixed. Gateway #1 operational risk. overlay_etf.py timing critical (must run before market close). Auto-reconcile, split detection, buying power checks all added. VPS migration is permanent solution. |

---

## Disclaimer

Educational and research purposes only. Past backtest performance does not guarantee future results. Not financial advice. Level 3 options approval required. Combined carry cost ~6.6% annually. V7.5 suitable only for those who can hold through -57%+ drawdowns.
