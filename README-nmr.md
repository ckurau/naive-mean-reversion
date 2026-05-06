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
backtest_ideas_v7_5.py        V7.5 research: 7 ideas × 12 tests, all vs V7.4 baseline
backtest_ideas_v7_4_final.py  V7.4 final backtest (V7.3 + TLT Bear + Factor Rotation + VIX Call Scaling)
backtest_ideas_v7_4.py        V7.4 research: 6 ideas × 10 tests, all vs V7.3 baseline
backtest_ideas_v7_3.py        V7.3 combined backtest (Idea G + GOLD + SECROT overlays, single combined equity)
backtest_ideas_v7_2.py        Idea G combined backtest (V47 + dynamic put spread + VIX calls)
backtest_nmr_lib_v47.py       All V47 backtest logic and parameters (unchanged)
backtest-nmr-v47.py           Thin wrapper for V47 MR-only backtest
walkforward_v47.py            Walk-forward validation for V47

scan_evening.py               Live: 6:00 PM PT Sun-Thu — MR signal scan, queues signals to DB (NO orders placed)
hedge_quarterly.py            Live: 6:05 PM PT Mon-Fri — SPY put spread (4-bucket: Idea P) + VIX call spread (Idea K)
overlay_etf.py                Live: 6:10 PM PT Mon-Fri — GOLD + SECROT + TLT Bear + Factor + PDBC + HYG + ZROZ via MOC
trade_morning.py              Live: 6:00 AM PT Mon-Fri — places MKT entry orders, submits exits, confirms fills, pushes to GitHub
intraday_update.py            Live: Every 30 min — connects IBKR, reads live portfolio, updates summary.json, pushes to GitHub
manual_enter.py               Manual: places MKT orders for pending entries (emergency use)
push_fills.py                 Manual: rewrites summary.json from DB and pushes to GitHub
check_ibkr_positions.py       Diagnostic: verifies IBKR positions vs DB, flags unexpected positions
check_positions.py            Diagnostic: audits every open position against V7.5 rules (exit status, ATR, earnings, etc.)
verify_all.py                 Diagnostic: 55+ checks across 10 categories — run after any change
reset_all.py                  Emergency: sells all MR positions, clears DB (use with caution)
fix_capital_cap.py            One-time patch: adds $100k portfolio cap to scan_evening.py and trade_morning.py
fix_capital_cap2.py           One-time patch: fixes None comparison bug in capital cap
fix_capital_deployed2.py      One-time patch: fixes capital deployed calculation in intraday_update.py
fix_earnings_blackout.py      One-time patch: (reverted — see Lessons Learned)
revert_earnings_fix.py        One-time patch: reverts earnings fix back to backtest-consistent behavior
```

**Four-script live execution:**
- `scan_evening.py`    — 6:00 PM PT Sun-Thu, scans universe, saves signal candidates to DB (no IBKR orders)
- `hedge_quarterly.py` — 6:05 PM PT Mon-Fri, manages SPY put spread + VIX call spread
- `overlay_etf.py`     — 6:10 PM PT Mon-Fri, manages all ETF overlays via MOC
- `trade_morning.py`   — 6:00 AM PT Mon-Fri, places MKT entry orders, exits, confirms fills, pushes to GitHub

**Critical timing note:** MOO/LOO (OPG) orders are only valid 7:00–9:28 AM ET. Orders submitted at 6 PM PT (9 PM ET) return ValidationError 321 and are silently dropped. scan_evening.py saves signals to DB only. trade_morning.py places MKT orders at 6:00 AM PT (9:00 AM ET) — within the valid window.

---

## Live Infrastructure

### File Locations

| Component | Path |
|---|---|
| Scripts | `C:\nmr-trader\` |
| Git repo (local) | `C:\naive-mean-reversion\` |
| Database | `C:\nmr-trader\positions.db` |
| Trade log | `C:\nmr-trader\trade.log` |
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

### Task Scheduler — Days of Week

| Task | Time (PT) | Sun | Mon | Tue | Wed | Thu | Fri | Sat |
|---|---|---|---|---|---|---|---|---|
| IBC Gateway | 6:00 AM | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| Scan Evening | 6:00 PM | ✓ | ✓ | ✓ | ✓ | ✓ | — | — |
| Hedge Quarterly | 6:05 PM | — | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| Overlay ETF | 6:10 PM | — | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| NMR Trader (trade_morning) | 6:00 AM | — | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| NMR Intraday Update | Every 30min | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ |

**Scan Evening runs Sunday** because it queues signals for Monday's open. Friday scan is skipped — Saturday market is closed.

---

## IBKR Gateway — Connectivity (CRITICAL)

### Daily Maintenance Window
IBKR disconnects all Gateway sessions every night for server maintenance: **11:45 PM – 12:45 AM ET (8:45 PM – 9:45 PM PT)**. Gateway must be manually logged in before this window or re-logged in after it ends.

### Current Setup (as of May 2026)
- **IBC auto-login is DISABLED** — `C:\IBC\StartGateway.bat` contains only `exit`
- **Reason:** IBC kept locking the IBKR account due to failed automated login attempts. Root cause was `IbPassword` in `C:\Users\bkcol\Documents\IBC\config.ini` containing a stale/wrong password. Even after fixing credentials, IBKR blocked automated logins for the paper account (`tlpxbr648`). IBC uses a different authentication endpoint than manual Gateway login, and IBKR's security model for paper accounts is unreliable with IBC automation.
- **Gateway auto-restart:** Set to 10:00 PM PT in Gateway → Configure → Settings → Lock and Exit. This fires after maintenance ends, but sometimes fails to reconnect without re-authentication.
- **Manual login required:** User goes to bed at 9:00 PM PT — before maintenance window ends at 9:45 PM PT. **Log in manually before 8:40 PM PT** each evening to ensure Gateway is connected before maintenance hits. After maintenance (10 PM PT auto-restart) Gateway sometimes reconnects automatically and sometimes doesn't.

### IBC config.ini — Key Settings (C:\Users\bkcol\Documents\IBC\config.ini)
```
IbLoginId=colbykurau          ← live account username (IBC uses live creds even for paper)
IbPassword=<current_password> ← must match current live account password
TradingMode=paper
ExistingSessionDetectedAction=primary
AutoLogoffTime=               ← blank = never auto-logoff
```

### VPS Migration Plan
The permanent solution is migrating to a Linux VPS where:
- IBC runs headlessly via Xvfb (virtual display)
- systemd manages Gateway as a service with auto-restart
- No Windows Update reboots
- No IBKR paper account authentication quirks
**Do not attempt to re-enable IBC on Windows until migrating to VPS.**

### Going Live — Three Changes Only
1. `IBKR_PORT = 4001` (was 4002 paper) — change in all four main scripts
2. Switch Gateway from Paper to Live account
3. Level 3 options approval on real account before running hedge_quarterly.py live

---

## Capital Deployment — Important Notes

### Paper Trading vs Real Account
In paper trading, the dashboard may show >100% capital deployed because:
- IBKR paper accounts have no real buying power constraints
- ETF overlays (~28% of capital) + MR positions (~45-75%) can sum to >100%
- This is a paper trading artifact only

**In a real cash account:** IBKR automatically rejects orders exceeding available cash. No code changes needed — IBKR enforces the limit. Overlays deploy first (evening MOC), MR entries deploy next morning, and any orders exceeding remaining cash are rejected.

### Capital Cap in Scripts
`scan_evening.py` and `trade_morning.py` both have `min(portfolio_value, 100000.0) if portfolio_value is not None else None` applied after fetching portfolio value from IBKR. This ensures position **sizing** is always calculated against $100k maximum, regardless of what the paper portfolio reports. This is critical during periods when stale/phantom positions inflate the IBKR portfolio value.

### Expected Live CAGR Impact of Cash Constraint
With ~28% in overlays, only ~72% of capital is available for MR positions. This costs roughly 1-2pp CAGR vs the backtest in the first 2-3 years, converging to backtest performance as the portfolio grows. This is within the optimism bias range from other sources (slippage, overfitting, etc.).

### Capital Deployed Calculation (intraday_update.py)
Sums market values of all positive IBKR positions. Excludes negative (short) positions. May temporarily show inflated values when reset/cleanup operations leave phantom positions in IBKR.

---

## Database Tables

| Table | Purpose |
|---|---|
| `open_positions` | Currently held MR positions (ticker, entry_date, entry_price, shares, tier, hold_days, etc.) |
| `pending_entries` | Signals queued by scan_evening.py for next morning's entry |
| `trade_log` | All closed MR trades (entry/exit price, P&L, reason) |
| `cooldown` | Tickers in re-entry cooldown after time-stop (5-day cooldown) |
| `gold_position` | GOLD overlay state |
| `secrot_positions` | SECROT sector ETF positions |
| `tlt_bear_position` | TLT Bear overlay state |
| `factor_position` | QQQ/IWM Factor rotation state |
| `pdbc_position` | PDBC commodity overlay state |
| `hyg_position` | HYG credit carry overlay state |
| `zroz_position` | ZROZ panic overlay state |

### open_positions Schema
Key columns: `ticker TEXT (PK)`, `entry_date TEXT`, `entry_price REAL`, `shares REAL`, `shares_remaining REAL`, `tier INTEGER`, `hold_days INTEGER`, `profit_target REAL`, `partial_enabled INTEGER`, `partial_frac REAL`, `partial_trigger REAL`, `partial_done INTEGER`, `entry_commission REAL`, `consec_down_at_entry INTEGER`, `rsi2_at_entry REAL`

**Note:** `hold_days` in the DB is NOT updated daily by trade_morning.py. Always calculate actual days held from `entry_date` using `pd.bdate_range(entry_date, today)` for accurate counts.

---

## Dashboard (GitHub Pages)

**URL:** https://ckurau.github.io/naive-mean-reversion/

**Data source:** `paper_trading/summary.json` in the repo, fetched via raw.githubusercontent.com

**Auto-refresh:** Every 5 minutes

**Mobile:** Open URL in Safari → Share → Add to Home Screen

**Key KPI fields in summary.json:**
- `portfolio_value` — total IBKR account value
- `open_positions` — count of MR positions in DB
- `capital_deployed_usd` — sum of positive IBKR position market values
- `capital_deployed_pct` — deployed / portfolio_value × 100
- `capital_cash_usd` — portfolio_value - capital_deployed_usd
- `unrealized_pnl_usd` — sum of unrealized P&L across DB positions
- `win_rate` — MR-only win rate from trade_log
- `scan_date` — date of last evening scan
- `scan_signals` — count of signals queued
- `positions_detail` — JSON string of open position details
- `last_intraday_update` — timestamp of last intraday push

**JSON corruption note:** `positions_detail` is stored as an escaped JSON string within JSON, making the file ~27kb. This is valid JSON but can cause parse errors in some contexts. The dashboard itself handles it correctly. The corruption seen in debugging was from the intraday script overwriting the file mid-read.

---

## GitHub Push — How It Works

**`scan_evening.py` pushes at ~6:10 PM PT** (after scan completes):
- Updates `summary.json` with tonight's scan candidates, VIX, regime flags, all overlay statuses

**`trade_morning.py` pushes at ~6:35 AM PT** (after fill confirmation):
1. Writes `paper_trading/summary.json`
2. Writes `paper_trading/trades.csv`
3. Writes `paper_trading/open_positions.csv`
4. Writes `paper_trading/rejections.csv`
5. Git commits and pushes to `origin main`

**`intraday_update.py` pushes every 30 minutes** (no git pull — prevents index.html corruption):
- Updates `summary.json` with live IBKR portfolio values
- Does NOT pull from GitHub before pushing

---

## Best Confirmed Results

### V7.5 — Full History Run (April 2026) — COMBINED EQUITY

| Metric | Value | Notes |
|---|---|---|
| CAGR (MR-only basis) | 28.88% | MR engine unchanged from V47 |
| CAGR (combined equity) | 34.75% | MR + all nine overlays |
| Final Equity (combined) | $77,488,411 | MR + SPY puts + VIX calls + GOLD + TLT + SECROT + Factor + PDBC + HYG + ZROZ |
| Max Drawdown (combined) | -57.25% | Virtually identical to V7.4 (-57.17%) — 0.08pp cost |
| Sharpe (combined) | 1.08 | Improved from 1.04 (V7.4) |
| Win Rate | 60.24% | MR-only, unchanged |
| Total MR trades | 22,041 | |
| MR trades P&L | +$77,388,411 | |
| SPY put net P&L | +$8,503,102 | |
| VIX call net P&L | +$18,762,734 | |
| GOLD overlay net P&L | +$6,304,696 | |
| TLT Bear net P&L | +$1,452,352 | |
| SECROT overlay net P&L | +$7,396,436 | |
| Factor rotation net P&L | +$3,789,082 | |
| PDBC Commodity net P&L | +$6,113,922 | NEW — Idea N |
| HYG Credit net P&L | +$613,872 | NEW — Idea O |
| ZROZ Panic net P&L | +$1,111,189 | NEW — Idea Q |
| Total overlay net P&L | +$54,047,384 | All nine overlays combined |

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

| Strategy | CAGR | Equity | MaxDD | Sharpe | Best For |
|---|---|---|---|---|---|
| **V7.5 (current, combined)** | **34.75%** | **$77.5M** | **-57.25%** | **1.08** | **Max wealth, nine-overlay stack** |
| V7.4 (previous best) | 32.85% | $57.0M | -57.17% | 1.04 | V7.4 overlays, no N/O/P/Q |
| V7.3 (previous best) | 29.30% | $30.9M | -56.62% | 0.96 | V7.3 overlays, no I/J/K |
| V48 / Idea G (previous best) | 24.38% | $18.3M | -56.91% | 0.74 | Idea G only, no ETF overlays |
| V47 + Idea 3 (previous benchmark) | 22.40% | $9.9M | -60.89%* | 0.74 | Previous recommended |
| V47 (no hedge) | 19.54% | $4.6M | -56.84% | 0.72 | Max wealth, taxable, no hedge |
| V32d | 15.37% | $2.1M | -39.21% | 0.77 | Roth IRA, lower DD tolerance |

---

## V7.5 Strategy Rules

### MR Rules (V47, unchanged)

| Rule | Detail |
|---|---|
| Universe | S&P 500 + S&P 400 MidCap + S&P 600 SmallCap (current + historical) |
| Trend filter | Stock must be above its 200-day SMA |
| Entry signal | 4+ consecutive down days AND RSI(2) < 20 AND ATR > 1% AND volume > 20-day avg AND dollar volume > $5M/day |
| Entry execution | Buy at open via MKT order placed at 6:00 AM PT (9:00 AM ET pre-market window) |
| Gap filters | Skip if next open gaps down > 1.0% OR gaps up > 2% |
| Exit — all tiers | 2% profit target OR 8-day time stop (checked on prior day's closing price) |
| Tier 1 partial | 6+ down days: 50% at 0.8%, remainder at 2% |
| Tier 2 | 5 down days: 2% target, 8-day window |
| Tier 3 | 4 down days: 2% target, 8-day window |
| Min hold | 2 trading days before profit exit (prevents immediate exit on gap-up opens) |
| Max positions | 60 simultaneous holdings |
| Position size base | VIX < 25 → 9%, VIX ≥ 25 → 5% |
| Tiered sizing | Top 20% of signals by composite score get 1.3x, hard cap 12% |
| TOM sizing | Last trading day of month + next 3: 1.15x multiplier |
| DOW sizing | Tuesday: 1.10x \| Friday: 0.90x |
| VIX RSI tight | When VIX < 15: require RSI(2) < 15 |
| Signal ranking | Composite score: RSI(2) / ATR_pct |
| Sector filter | Skip if stock's sector ETF below 20-day MA |
| Correlation cap | Max 3 open positions in same sector |
| Earnings blackout | Skip within ±3 days of earnings (confirmed dates only — see note below) |
| SPY regime | No new entries when SPY below 200-day MA |
| Re-entry cooldown | No re-entry for 5 days after time-stop |
| Velocity crash pause | SPY 5-day return < -12% → pause entries 5 days |
| Earnings month cap | Position size capped at 2.4% in Jan/Apr/Jul/Oct |

**Exit logic note:** Exit decisions are made on **prior day's closing price**, executed at next morning's open (MKT order). A stock closing at +2.01% triggers a sell order placed at 6 AM PT. If the stock gaps down -5% at open, the sell fills at the gap-down price. This gap risk is fully modeled in the backtest — every historical open price is used for execution. This is intentional and consistent with the 60.24% win rate and 34.75% CAGR.

**Earnings blackout note:** yfinance does NOT reliably return earnings calendar data for most stocks (~80% return no data). The original backtest behavior is preserved: only block entries when yfinance **confirms** an earnings date within the ±3 day blackout window. Missing earnings data = stock is allowed through. Excluding all stocks with missing earnings data would eliminate most signals and is not backtest-consistent. In May 2026, CENTA slipped through the earnings filter because yfinance returned no calendar data despite earnings on May 6 — this was a one-off data gap, not a systematic bug, and the behavior was intentionally left unchanged.

### Overlay Specifications

**SPY Put Spread (hedge_quarterly.py):**
Dynamic strikes per VIX regime: VIX<15 → 3%/13% OTM, VIX 15-25 → 5%/15%, VIX 25-35 → 8%/20%, VIX>35 → 8%/25% (Idea P). Target DTE: 63 trading days. Max debit: $15. Auto-rolls when ≤5 days to expiry.

**VIX Call Spread (hedge_quarterly.py):**
20/40-strike monthly spread. Standard: 0.3%/month. Idea K: 0.6%/month when VIX > VIX3M (backwardation). Max debit: $5. Auto-rolls every ~21 trading days.

**GOLD Overlay:** GLD when GLD > 200d MA AND TLT 20d slope ≥ 0. 7% allocation. MOC via overlay_etf.py.

**SECROT Overlay:** Top-3 SPDR sectors by 63d momentum. 3% each (9% total). Monthly rebalance. Bull regime only (SPY > 200d MA). MOC via overlay_etf.py.

**TLT Bear Overlay (Idea I):** TLT when SPY < 200d MA AND TLT > 50d MA. 8% allocation. Bear regime only. MOC via overlay_etf.py.

**Factor Rotation (Idea J):** QQQ or IWM (whichever has stronger 63d momentum). 6% allocation. Monthly rebalance. Bull regime only. MOC via overlay_etf.py.

**PDBC Commodity (Idea N):** PDBC when PDBC > 100d MA AND DBC 63d momentum > 0. 5% allocation. No regime filter. MOC via overlay_etf.py.

**HYG Credit Carry (Idea O):** HYG when HYG/LQD ratio > 20d MA. 5% allocation. Bull regime only. MOC via overlay_etf.py.

**ZROZ Panic (Idea Q):** ZROZ when VIX > 20 AND TLT 5d return > 0.5%. 6% allocation. Fires on acute panic events. MOC via overlay_etf.py.

---

## Paper Trading Lessons Learned (April–May 2026)

### Gateway Connectivity

**Problem:** IBKR's daily maintenance window (8:45–9:45 PM PT) disconnects Gateway every night. Without IBC auto-login, Gateway does not reconnect automatically.

**What was tried:**
1. IBC auto-login → Failed: "Unrecognized username or password" even with correct credentials. IBKR blocks automated login for paper accounts.
2. Gateway auto-restart at various times → Failed when fired during maintenance window (9:01 PM PT, 9:50 PM PT, 10:00 PM PT all failed because maintenance runs until 9:45 PM PT)
3. Gateway auto-restart at 10:00 PM PT → Partially works but sometimes fails to re-authenticate
4. Manual login before 8:40 PM PT → Works reliably. User goes to bed at 9 PM PT so this is the best option for now.

**Root cause of IBC failures:** `C:\Users\bkcol\Documents\IBC\config.ini` had `IbLoginId=colbykurau` and `IbPassword=<wrong_password>`. The config.ini credentials take priority over the bat file. Multiple failed login attempts locked the IBKR account twice. Even after correcting credentials, IBKR's paper account security model blocks IBC automation.

**Current solution:** Manual login before 8:40 PM PT nightly. Gateway auto-restart set to 10:00 PM PT as backup. IBC bat file contains only `exit`.

**Permanent solution:** Linux VPS migration with IBC running headlessly via Xvfb.

### Order Type Issues

**MOO vs MKT:** Initially `scan_evening.py` placed MOO (Market on Open) orders at 6 PM PT. MOO/OPG orders are only valid 7:00–9:28 AM ET. Orders placed outside this window return ValidationError 321 and are **silently dropped** — no error in logs, no IBKR notification. Fixed by moving order placement to `trade_morning.py` at 6:00 AM PT.

**Do NOT use MOO order type** — use `orderType='MKT', tif='DAY'` in trade_morning.py. MKT DAY orders placed pre-market execute at the open.

### Reset and Cleanup Issues

**Never run reset_all.py when positions are partially closed.** In April/May 2026, a full system reset was performed but IBKR had already closed some of the positions being sold, causing the reset sells to create **short positions** instead of closing longs. The short positions then required buyback orders, which again created temporary long positions, which then required selling again — a cycle that repeatedly inflated capital deployed and cluttered the IBKR account.

**Lesson:** Before running reset_all.py, verify via check_ibkr_positions.py that all positions are actually long (positive shares). Never manually sell positions outside of trade_morning.py and then also run a reset.

### DB Sync Issues

The DB (`open_positions`) can get out of sync with IBKR positions when:
- Manual orders are placed outside of trade_morning.py
- reset_all.py is run while IBKR has pending orders
- scan_evening.py writes stale signals to pending_entries that get deleted from DB but not from IBKR's order queue

**Always verify:** After any manual intervention, run `check_ibkr_positions.py` to compare DB vs IBKR and resolve discrepancies.

### Stale Pending Entries

When `pending_entries` DB is cleared but IBKR still has open orders from those signals (placed by a previous trade_morning.py run that didn't get to clean up), the orders will still execute at next market open. Monitor IBKR open orders separately from the DB.

### Days Held Tracking

The `hold_days` column in `open_positions` is NOT updated daily by trade_morning.py in the current implementation. Always calculate actual held days using `pd.bdate_range(entry_date, today)` rather than reading `hold_days` from the DB. The `entry_date` column IS reliably populated at entry.

### Capital Deployed Inflation

Capital deployed shows inflated values when:
1. Short positions exist in IBKR (their absolute market value counted)
2. ETF overlays are included (legitimate but makes MR capital hard to read)
3. Stale/phantom IBKR positions from manual operations

The dashboard `capital_deployed_usd` sums all positive IBKR position market values including overlays. In paper trading this routinely exceeds $100k — this is a paper trading artifact, not a real account problem.

### JSON Corruption

`summary.json` was intermittently showing as corrupted JSON (parse errors). The root cause was the file being read by the browser simultaneously with the intraday script writing to it. The file is 27kb due to `positions_detail` containing a large escaped JSON string. The file itself is valid — no actual corruption. Browser timing caused the apparent parse failures.

### Earnings Filter Reliability

yfinance's `.calendar` endpoint returns earnings dates for approximately 20% of stocks. For the remaining 80%, it returns None or an empty DataFrame. The earnings blackout filter in `scan_evening.py` only blocks entries when yfinance **confirms** an upcoming earnings date within ±3 days. This matches the backtest behavior.

An attempt was made to exclude all tickers with missing earnings data as a precaution (fix_earnings_blackout.py). This was **reverted** (revert_earnings_fix.py) because it would eliminate ~80% of signals and is not backtest-consistent. The CENTA situation (May 2026, bought 3 days before earnings that yfinance didn't detect) is an accepted risk of the strategy.

---

## Diagnostic Scripts — Usage Guide

### verify_all.py
Run after any script change or before leaving computer unattended:
```cmd
C:\nmr-trader\venv\Scripts\python.exe C:\nmr-trader\verify_all.py
```
Checks: files, IBC config, task scheduler, IBKR gateway, DB tables, git state, script content, dashboard data, trade log, Python dependencies. Expected: 55+ PASS, 0 FAIL.

### check_positions.py
Run after market close to audit every open position:
```cmd
C:\nmr-trader\venv\Scripts\python.exe C:\nmr-trader\check_positions.py
```
Checks per position: profit target hit, time stop, min hold, 200d MA, ATR, dollar volume, earnings. Shows accurate held days from `entry_date`.

### check_ibkr_positions.py
Run after any manual intervention to compare IBKR vs DB:
```cmd
C:\nmr-trader\venv\Scripts\python.exe C:\nmr-trader\check_ibkr_positions.py
```
Shows each IBKR stock position with status: OK (in DB), PENDING SELL, or unexpected.

### push_fills.py
Manually sync DB → summary.json → GitHub when intraday is showing stale data:
```cmd
C:\nmr-trader\venv\Scripts\python.exe C:\nmr-trader\push_fills.py
```

### Quick DB checks
```bat
:: Open positions
python -c "import sqlite3,pandas as pd; conn=sqlite3.connect(r'C:\nmr-trader\positions.db'); print(pd.read_sql('SELECT ticker,entry_date,entry_price,shares,tier FROM open_positions ORDER BY entry_date',conn).to_string()); conn.close()"

:: Pending entries
python -c "import sqlite3,pandas as pd; conn=sqlite3.connect(r'C:\nmr-trader\positions.db'); print(pd.read_sql('SELECT ticker,signal_date,shares,tier FROM pending_entries ORDER BY tier',conn).to_string()); conn.close()"

:: All overlay statuses
python -c "import sqlite3,pandas as pd; conn=sqlite3.connect(r'C:\nmr-trader\positions.db'); [print(f'\n=== {t} ==='); print(pd.read_sql(f'SELECT * FROM {t}',conn).to_string()) for t in ['gold_position','tlt_bear_position','factor_position','pdbc_position','hyg_position','zroz_position']]; conn.close()"
```

---

## VPS Migration Checklist

When migrating from Windows desktop to Linux VPS, the following must be transferred:

### Scripts to migrate (C:\nmr-trader\)
- `scan_evening.py`
- `trade_morning.py`
- `hedge_quarterly.py`
- `overlay_etf.py`
- `intraday_update.py`
- `manual_enter.py`
- `push_fills.py`
- `check_ibkr_positions.py`
- `check_positions.py`
- `verify_all.py`
- `positions.db` (SQLite database with all overlay state)

### Port changes for live account
Change `IBKR_PORT = 4002` → `IBKR_PORT = 4001` in all four main scripts.

### Linux-specific setup
1. Install IBC for Linux (uses Xvfb virtual display)
2. Configure IBC with `colbykurau` credentials and `TradingMode=paper` (then `live` when going live)
3. Set up systemd service for Gateway auto-restart
4. Install Python dependencies: `ib_async`, `yfinance`, `pandas`, `numpy`, `requests`
5. Configure cron jobs matching Task Scheduler schedule (all times in PT = UTC-7 or UTC-8)
6. Set up GitHub SSH key for push access
7. Clone `naive-mean-reversion` repo to Linux equivalent of `C:\naive-mean-reversion\`
8. Test Gateway connectivity: `netstat -an | grep 4002`

### Cron schedule (Linux, PT timezone)
```
# scan_evening — 6 PM PT Sun-Thu
0 18 * * 0,1,2,3,4 /path/to/venv/bin/python /path/to/scan_evening.py

# hedge_quarterly — 6:05 PM PT Mon-Fri
5 18 * * 1,2,3,4,5 /path/to/venv/bin/python /path/to/hedge_quarterly.py

# overlay_etf — 6:10 PM PT Mon-Fri
10 18 * * 1,2,3,4,5 /path/to/venv/bin/python /path/to/overlay_etf.py

# trade_morning — 6:00 AM PT Mon-Fri
0 6 * * 1,2,3,4,5 /path/to/venv/bin/python /path/to/trade_morning.py

# intraday_update — every 30 min
*/30 * * * * /path/to/venv/bin/python /path/to/intraday_update.py
```

### Pre-migration checklist
- [ ] Paper trading running cleanly for 3+ months with 100% script uptime
- [ ] Win rate 57–63% over 100+ closed MR trades
- [ ] Trades per month 65–90
- [ ] All overlay tables populated correctly in DB
- [ ] Gateway connectivity issue resolved via IBC on Linux

---

## Going Live — Pass Criteria

| Check | Target | Action if failing |
|---|---|---|
| Win rate | 57–63% over 100+ trades | Stop — review signal logic |
| Trades per month | 65–90 | Check universe fetch and signal parameters |
| Worst single month | Better than -15% | Review if repeated |
| Script ran every trading day | 100% | Fix Gateway startup |
| Slippage vs prior close | Under 0.6% avg | Higher for small-caps expected |
| Gateway connectivity | 0 missed mornings | VPS migration required |

---

## Bugs Fixed (April–May 2026)

**Bug 1 — Stray PowerShell line in trade_morning.py**
A PowerShell command was embedded as a Python line at line 405, causing a `NameError` crash before fill confirmation. Positions were never saved to DB for weeks.

**Bug 2 — ClientId mismatch**
`scan_evening.py` used clientId=10, `trade_morning.py` used clientId=1. IBKR only returns fills to the same clientId that placed the order.

**Bug 3 — LOO orders wiped by IBKR nightly session reset**
LOO orders at 6 PM PT were cancelled by IBKR's nightly reset. Fix: use pending_entries DB only at 6 PM, place MKT orders at 6 AM PT.

**Bug 4 — MOO/LOO ValidationError 321 at 6 PM PT**
OPG orders are only valid 7:00–9:28 AM ET. Fix: moved order placement to trade_morning.py at 6:00 AM PT.

**Bug 5 — trade_morning.py Task Scheduler at 6:15 AM PT**
Only 13 minutes before 9:28 AM ET OPG cutoff. Fix: changed to 6:00 AM PT.

**Bug 6 — capital cap crashing when portfolio_value is None**
`min(portfolio_value, 100000.0)` crashes when `portfolio_value` is None (initial declaration before IBKR fetch). Fix: `min(portfolio_value, 100000.0) if portfolio_value is not None else None`.

**Bug 7 — scan_evening.py crash after DB reset**
After clearing `open_positions` DB, scan_evening.py crashed at the capital cap line because `portfolio_value` was None. Same fix as Bug 6.

**Bug 8 — IBC config.ini overriding bat file credentials**
`C:\Users\bkcol\Documents\IBC\config.ini` contains `IbLoginId` and `IbPassword` which take priority over bat file credentials. IBC was using wrong password from config.ini, causing account lockouts. Always edit config.ini directly for credential changes.

**Bug 9 — intraday git pull corrupting index.html**
`intraday_update.py` was running `git pull` before pushing, which could overwrite index.html with an older version from GitHub. Fix: removed git pull from intraday_update.py. It now only pushes `summary.json`.

**Bug 10 — Unicode arrow characters in summary.json**
scan_evening.py was writing `→` characters into summary.json fields, causing JSON parse errors. Fix: removed all Unicode arrow characters from scan_evening.py log messages and output strings.

---

## Do-Not-Retry Table

| Approach | Why It Failed |
|---|---|
| Price-based stop-losses (-3%) | 22.6% hit stop then bounced |
| Portfolio-level halt at -10% DD | Fired permanently 2004–2006 |
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
| IBC auto-login on Windows paper account | Account lockouts — IBKR blocks automated login for paper accounts |
| MOO orders placed at 6 PM PT | ValidationError 321 — OPG window is 7:00–9:28 AM ET only |
| Excluding all tickers with missing yfinance earnings data | Eliminates ~80% of signals, not backtest-consistent |
| Running reset_all.py when IBKR has pending orders | Creates short positions that require cleanup |
| Manually selling positions then also running a system reset | Double-sell creates shorts |
| git pull in intraday_update.py | Overwrites index.html with stale version |
| Intraday exits (checking prices during market hours) | Different strategy than backtest — would require new backtest |

---

## Walk-Forward Validation

### V47 Walk-Forward (PASS — April 2026)

| Window | OOS Period | CAGR | MaxDD | Sharpe | Regime |
|---|---|---|---|---|---|
| W1 | 2009–2010 | 28.3% | -14.5% | 1.23 | Recovery |
| W2 | 2011–2012 | 26.0% | -35.4% | 0.73 | Chop/Dip |
| W3 | 2013–2014 | 41.2% | -34.1% | 1.27 | Bull |
| W4 | 2015–2016 | 15.8% | -18.3% | 0.84 | Chop |
| W5 | 2017–2018 | 12.0% | -31.5% | 0.47 | Low-Vol Bull |
| W6 | 2019–2020 | 51.8% | -36.3% | 1.19 | Bull+Crash |
| W7 | 2021–2022 | -12.7% | -48.0% | -0.36 | Bear Grind |
| W8 | 2023–2025 | 4.8% | -57.0% | 0.36 | AI Bull + Tariff Bear |

**OOS Positive CAGR windows: 7/8 — PASS**
**OOS Avg CAGR: 20.91%**

---

## Optimism Bias Warnings

V7.5's 34.75% combined CAGR is the in-sample ceiling, not the live expectation.

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
| Cash constraint (overlays use ~28% of $100k) | -1 to -2% in early years |
| **Realistic live estimate** | **~10–14% CAGR gross** |

Apply ~26% walk-forward decay: 34.75% × 0.74 = ~26% live gross (upper bound).
After short-term capital gains tax (32–37%), realistic net: ~10–12%.

**Cash constraint note:** The backtest assumes overlays and MR positions can be deployed simultaneously on the same capital base without constraint. In a real $100k cash account, IBKR rejects orders exceeding available cash — overlays (~28%) deploy first via MOC, leaving ~72% for MR positions. This costs approximately 1-2pp CAGR in the first 2-3 years, converging to backtest performance as the portfolio grows. No code changes are needed — IBKR enforces the limit automatically.

---

## The Honest Risk Picture

V7.5 with all overlays:
- -57.25% combined MaxDD means ~$47M paper loss peak-to-trough at $82M peak equity (2025)
- The SPY put spread fires when SPY drops 3–15% from quarterly reference
- The VIX call spread fires when VIX spikes above 20 intraday — catches early crash days
- 2022: MR lost ~$1.6M; puts paid $659k; VIX calls paid ~$1.2M — net drawdown significantly cushioned
- 2025: MR lost ~$777k; puts paid $1.13M; VIX calls paid ~$1.4M — combined portfolio was net positive
- Combined overlay carry cost: ~0.75%/quarter (puts) + ~0.30–0.60%/month (VIX calls) ≈ 6.6–9% annually

---

## Research History

| Ideas Session | Key Finding |
|---|---|
| Ideas V2 | Idea 3 SPY put spread confirmed |
| Ideas V3 | No ideas improved on V35+I3 |
| Ideas V4 | Ranking enhancements zero effect (60-position cap rarely binding) |
| Ideas V5 | TOM/DOW/VIX-RSI sizing → became V47 |
| Ideas V6 | V47+I3 confirmed ceiling at $9.9M / 22.40% CAGR |
| Ideas V7 | VIX call spread model bug fixed. Idea E dead. |
| Ideas V7.1 | Idea D dynamic strikes confirmed: +0.42pp CAGR |
| Ideas V7.2 | Idea G (D+A) confirmed: +1.94pp CAGR, +$8.35M. V48 chosen. |
| V49 research | GOLD, SECROT on V35 baseline — MaxDD worsened without crash protection |
| Ideas V7.3 | GOLD + SECROT on Idea G baseline — MaxDD improved +4.69pp. V7.3 chosen. |
| Live bugs found | MOO ValidationError at 6 PM PT. Fix: trade_morning.py at 6 AM PT. |
| Ideas V7.4 | I+J+K confirmed: 32.85% CAGR, $56.5M. Overlays exceed MR P&L. |
| Ideas V7.5 | N+O+P+Q confirmed: 34.75% CAGR, $77.5M. Nine overlays generate $54M. |
| Paper trading (Apr–May 2026) | Gateway connectivity is #1 operational risk. IBC unreliable on Windows paper accounts. VPS migration is the permanent solution. |

---

## Disclaimer

Educational and research purposes only. Past backtest performance does not guarantee future results. Not financial advice. The VIX call spread and dynamic SPY put spread require Level 3 options approval. Combined carry cost of ~6.6% annually is a real drag in flat markets. V7.5 is suitable only for those who understand and can hold through drawdowns of -57%+ on the combined portfolio.
