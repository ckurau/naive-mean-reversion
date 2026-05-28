# Naive Mean Reversion (NMR) Backtest

A survivorship-bias-free backtest of a Naive Mean Reversion strategy across all historical S&P 500 + S&P 400 MidCap + S&P 600 SmallCap constituents, automated via GitHub Actions.

---

## Current Version: V7.5 — Idea G + GOLD + SECROT + Factor Rotation + VIX Call Scaling + PDBC

**Active strategy: V47 base logic + dynamic SPY put spread strikes (4-bucket: Idea P) + monthly VIX call spread (scaled in backwardation: Idea K) + GLD trend overlay + sector rotation momentum overlay + QQQ/IWM factor rotation overlay + PDBC commodity overlay.**

**REMOVED overlays (2026-05-22):** TLT Bear (Idea I), HYG Credit Carry (Idea O), ZROZ Panic (Idea Q) — all three removed after overlay comparison backtest showed +0.61pp CAGR improvement without them, freeing ~19% capital for MR trades.

V47 = V35 + four confirmed positive sizing overlays (TOM sizing, DOW sizing, partial trigger tuning, VIX RSI tightening).
Idea G = V47 + Idea D (VIX-regime-conditional put spread strikes) + Idea A (monthly VIX 20/40-call spread).
V7.3 = Idea G + GOLD overlay (7% GLD when GLD > 200d MA + rates falling) + SECROT overlay (top-3 SPDR sectors by 3m momentum, 3% each, bull regime only).
V7.4 = V7.3 + Idea I (TLT bear overlay, 8% when SPY < 200d MA + TLT > 50d MA) + Idea J (QQQ/IWM factor rotation, 6% monthly, bull regime) + Idea K (VIX call allocation doubles to 0.6% when VIX > VIX3M backwardation).
V7.5 = V7.4 + Idea N (PDBC commodity 5%, trend+momentum filtered) + Idea O (HYG credit carry 5%, ratio signal) + Idea P (SPY put 4th VIX bucket: VIX>35→25% OTM short) + Idea Q (ZROZ panic 6%, VIX>20 + TLT 5d rally).

**Live deployment (May 2026):** TLT Bear, HYG, ZROZ disabled. Active overlays: SPY put spread, VIX calls, GOLD, SECROT, FACTOR, PDBC.

Walk-forward validated through V47: 7/8 OOS windows positive, OOS avg CAGR 20.91%.

---

## Architecture

```
backtest_v75_cash_constrained.py  AUTHORITATIVE BACKTEST — cash-constrained, realistic $100k account
backtest_ideas_v7_5_final.py      V7.5 final backtest (notional model — do not use for live targets)
backtest_overlay_comparison.py    Overlay removal comparison: Remove ZROZ+TLT+HYG = +0.61pp CAGR
backtest_bear_secrot.py           Bear SECROT + tier priority backtest — both rejected
backtest_ideas_v7_4_final.py      V7.4 final backtest
backtest_ideas_v7_3.py            V7.3 combined backtest
backtest_nmr_lib_v47.py           All V47 backtest logic and parameters (unchanged)
walkforward_v47.py                Walk-forward validation for V47

scan_evening.py               Live: 6:00 PM PT Sun-Thu — MR signal scan, queues signals to DB (NO orders placed)
hedge_quarterly.py            Live: 6:05 PM PT Mon-Fri — SPY put spread + VIX call spread (Idea K)
overlay_etf.py                Live: 12:30 PM PT Mon-Fri — GOLD + SECROT + Factor + PDBC via MOC (TLT/HYG/ZROZ disabled)
trade_morning.py              Live: 6:00 AM PT Mon-Fri — places MKT entry orders, submits exits, confirms fills, pushes to GitHub
intraday_update.py            Live: Every 30 min — connects IBKR, reads live portfolio, updates summary.json, pushes to GitHub
push_fills.py                 Manual: rewrites summary.json from DB and pushes to GitHub
health_check.py               Diagnostic: UNIFIED health check — MR positions + overlays + system status (USE THIS DAILY)
reconcile_db.py               Manual: interactive DB/IBKR reconciliation (removes stale, adds missing)
reset_all.py                  Emergency: sells all MR positions, clears DB (use with EXTREME caution)
rebuild_trades_csv.py         Manual: rebuilds trades.csv from DB trade_log
```

**Four-script live execution:**
- `scan_evening.py`    — 6:00 PM PT Sun-Thu
- `hedge_quarterly.py` — 6:05 PM PT Mon-Fri
- `overlay_etf.py`     — **12:30 PM PT Mon-Fri** (CRITICAL — must run before 3:45 PM ET for MOC orders)
- `trade_morning.py`   — 6:00 AM PT Mon-Fri

**Holiday check:** trade_morning.py uses `exchange_calendars` library (auto-maintained, no manual updates ever needed) to skip NYSE holidays and weekends. Falls back to static list through 2027 if library unavailable.

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
| Dashboard JSON | `C:\naive-mean-reversion\paper_trading\summary.json` |
| Dashboard URL | https://ckurau.github.io/naive-mean-reversion/ |

### IBKR Account

| Item | Detail |
|---|---|
| Paper account | DUP671219 |
| Paper port | 4002 |
| Live port | 4001 |
| Starting equity | $100,000 |

### Task Scheduler — Current State

| Task | Time (PT) | Days | Status |
|---|---|---|---|
| IBC Gateway | 6:00 AM | Sun-Fri | DISABLED |
| Scan Evening | 6:00 PM | Sun-Thu | ACTIVE |
| Hedge Quarterly | 6:05 PM | Mon-Fri | ACTIVE |
| Overlay ETF | **12:30 PM** | Mon-Fri | ACTIVE |
| NMR Trader (trade_morning) | 6:00 AM | Mon-Fri | ACTIVE |
| NMR Intraday Update | Every 30min | Daily | ACTIVE |

---

## IBKR Gateway — Connectivity (CRITICAL)

IBKR disconnects all Gateway sessions every night: **11:45 PM – 12:45 AM ET (8:45 PM – 9:45 PM PT)**. Gateway must be manually logged in before this window.

- **IBC auto-login is DISABLED** — kept locking the IBKR paper account
- **Manual login required:** Log in before **8:40 PM PT** each evening
- **Permanent solution:** Linux VPS migration with IBC running headlessly via Xvfb

### Going Live — Three Changes Only
1. `IBKR_PORT = 4001` in all four main scripts
2. Switch Gateway from Paper to Live account
3. Level 3 options approval on real account before running hedge_quarterly.py

---

## Daily Operations

### Daily Command
```cmd
C:\nmr-trader\venv\Scripts\python.exe C:\nmr-trader\health_check.py
```

### Emergency Commands
```cmd
C:\nmr-trader\venv\Scripts\python.exe C:\nmr-trader\push_fills.py
C:\nmr-trader\venv\Scripts\python.exe C:\nmr-trader\reconcile_db.py
C:\nmr-trader\venv\Scripts\python.exe C:\nmr-trader\intraday_update.py
netstat -an | findstr "4002"
```

---

## Capital Deployment

- `trade_morning.py` checks `AvailableFunds` from IBKR before each BUY order
- `overlay_etf.py` checks `AvailableFunds` inside `place_moc_order()` for BUY orders; uses conservative fallback (shares × $50) when yfinance fails
- SELL orders always go through regardless of buying power
- **Signal-based overlay reserve:** trade_morning.py only reserves capital for overlays currently signaling IN — not a flat percentage. Changed from flat 32% reserve in May 2026.

---

## Database Tables

| Table | Purpose |
|---|---|
| `open_positions` | Currently held MR positions |
| `pending_entries` | Signals queued by scan_evening.py |
| `trade_log` | All closed MR trades — columns: id, ticker, entry_date, exit_date, entry_price, exit_price, shares, pnl_usd, pnl_pct, exit_reason, tier |
| `cooldown` | Tickers in re-entry cooldown (5-day after time-stop) |
| `gold_position` | GOLD overlay state |
| `secrot_positions` | SECROT sector ETF positions |
| `tlt_bear_position` | TLT Bear state (disabled — in_position=0) |
| `factor_position` | QQQ/IWM Factor rotation state |
| `pdbc_position` | PDBC commodity state |
| `hyg_position` | HYG credit carry state (disabled — in_position=0) |
| `zroz_position` | ZROZ panic state (disabled — in_position=0) |

**Note:** `hold_days` in open_positions is NOT updated daily. Always calculate from `entry_date` using `pd.bdate_range(entry_date, today)`.

### Auto-Reconciliation (trade_morning.py)
Every morning after fills: removes stale DB entries, adds missing DB entries, detects splits (yfinance-validated), caps exit orders to IBKR share count to prevent accidental shorts.

---

## Dashboard (GitHub Pages)

**URL:** https://ckurau.github.io/naive-mean-reversion/

**Backtest bar:** Cash-constrained results (20.2% CAGR, $6,097,937 final equity, -13.3% MaxDD, Sharpe 1.51).

**Active overlay panels:** GOLD, SECROT, Factor, PDBC, SPY Put Spread, VIX Calls. TLT Bear, HYG, ZROZ panels removed May 2026.

**NaN handling:** intraday_update.py sanitizes all NaN/Infinity to null before writing summary.json — prevents JSON parse failures.

**JS null-safety:** All removed element IDs are null-safed with `|| {}` to prevent "Cannot set properties of null" errors.

---

## Authoritative Backtest Results

### ⚠️ Cash-Constrained Backtest is the ONLY valid live performance reference

Script: `backtest_v75_cash_constrained.py` — run locally (GitHub Actions gives wrong ~13% due to yfinance rate-limiting).

The notional V7.5 backtest (34.75% CAGR) used a model where overlays earned returns without deploying real cash simultaneously with MR positions. This is not achievable in a real $100k account. The cash-constrained backtest correctly models capital competition between MR positions and overlays.

### Cash-Constrained Results (May 2026)

| Metric | Value |
|---|---|
| CAGR (combined) | **20.2%** |
| CAGR (MR-only) | 16.2% |
| Final Equity | $6,097,937 |
| Max Drawdown | -13.3% |
| Sharpe | 1.51 |
| Win Rate (MR) | 60.8% |
| Total MR trades | 10,889 |
| Overlays net P&L | +$3.6M (real cash) |

**Realistic live expectations:**
- Gross CAGR: ~20.2%
- After slippage (-2 to -3%): ~17-18%
- After short-term capital gains tax (32-37%): **~11-13% net**

### Overlay Comparison Backtest (May 2026)

| Config | CAGR | MaxDD | MR Trades |
|---|---|---|---|
| All overlays (TLT+HYG+ZROZ active) | 18.52% | -14.49% | 10,684 |
| Remove ZROZ only | 18.75% | -14.70% | 10,720 |
| **Remove ZROZ+TLT+HYG (current live)** | **19.13%** | -15.05% | 10,855 |
| MR+Hedges only | 18.09% | -16.34% | 12,140 |

### Bear SECROT + Tier Priority Backtest (May 2026)

| Config | CAGR |
|---|---|
| Baseline (RSI/ATR rank, no bear SECROT) | 19.01% |
| Bear SECROT | 18.27% |
| Tier priority only | 17.94% |

Both rejected. RSI/ATR composite ranking confirmed optimal.

### Dollar Volume Filter Backtest (May 2026)
Tested $5M/$10M/$15M/$20M — no meaningful difference. Current $5M filter retained.

---

## V7.5 Strategy Rules

### MR Rules (V47, unchanged)

| Rule | Detail |
|---|---|
| Universe | S&P 500 + S&P 400 MidCap + S&P 600 SmallCap (current + historical) |
| Trend filter | Stock above 200-day SMA |
| Entry signal | 4+ consecutive down days AND RSI(2) < 20 AND ATR > 1% AND volume > 20-day avg AND dollar volume > $5M/day |
| Entry execution | MKT order at 6:00 AM PT (9:00 AM ET open) |
| Gap filters | Skip if open gaps down > 1.0% OR up > 2% |
| Exit | 2% profit target OR 8-day time stop (prior day close) |
| Tier 1 partial | 6+ down days: 50% at 0.8%, remainder at 2% |
| Max positions | 60 |
| Position size | VIX < 25 → 9%, VIX >= 25 → 5% |
| Signal ranking | RSI(2) / ATR_pct composite score (NOT tier — backtest-consistent) |
| SPY regime | No new entries when SPY below 200d MA |
| Re-entry cooldown | 5 days after time-stop |

### Active Overlay Specifications

| Overlay | Signal | Allocation | Script |
|---|---|---|---|
| SPY Put Spread | Always | VIX-bucketed strikes | hedge_quarterly.py |
| VIX Calls | Always | 0.3% or 0.6% (backwardation) | hedge_quarterly.py |
| GOLD | GLD > 200d MA AND TLT slope >= 0 | 7% | overlay_etf.py |
| SECROT | Top-3 sectors by 63d mom, bull regime | 3% each (9% total) | overlay_etf.py |
| FACTOR | QQQ or IWM (stronger 63d mom), bull regime | 6% | overlay_etf.py |
| PDBC | PDBC > 100d MA AND DBC 63d mom > 0 | 5% | overlay_etf.py |

### Disabled Overlays (removed May 2026)

| Overlay | Reason |
|---|---|
| TLT Bear (Idea I) | Backtest showed net negative vs removing; DB cleared |
| HYG Credit Carry (Idea O) | Marginal contribution, frees capital; DB cleared |
| ZROZ Panic (Idea Q) | Marginal contribution, frees capital; DB cleared |

---

## Live Trade Statistics (May 2026)

| Metric | Value |
|---|---|
| Total closed trades | 54 |
| Win rate | 61.1% |
| Status | Need 100+ trades for statistical confidence (~2-3 more months) |

---

## Paper Trading Lessons Learned (April–May 2026)

**Holiday handling:** trade_morning.py runs on NYSE holidays by default (Task Scheduler doesn't know market calendar). On Memorial Day 2026, orders placed on holiday queued in IBKR for next open, but DB was updated as if filled — causing DB/IBKR mismatch. Fixed: `exchange_calendars` holiday check exits script immediately on closed days. Always run reconcile_db.py after any holiday where trade_morning ran before the fix.

**Duplicate trade_log entries:** Holiday-queued orders execute next day, creating duplicate closed trade records (once on queue date, once on fill date). Delete phantom entries via SQL and correct exit_reason. Verify trade count after any DB sync issue.

**False split detection:** Split detection can fire on DB sync errors (not real splits). Fixed: yfinance validation before applying any split. LUV/NLY affected in May 2026.

**NaN in summary.json:** yfinance returns NaN for VIX3M/VIX3M-related fields when market is closed. NaN breaks JSON parsing entirely, causing blank dashboard. Fixed: intraday_update.py sanitizes before writing.

**JS null errors from removed elements:** Removing HTML elements while leaving JS getElementById references causes "Cannot set properties of null" errors that stop all JS execution below the error. Fix by null-safing all removed IDs with `|| {}`.

**Flat overlay reserve:** Reserving a flat 32% for overlays blocked MR entries when overlays were OUT. Changed to signal-based reserve.

**CMD vs PowerShell:** CMD cannot handle multi-line Python inline. Always save to .py file. PowerShell needed for `irm` (Claude Code install). Use PowerShell for Claude Code, CMD for .py script execution.

---

## VPS Migration Checklist

### Linux setup
```bash
pip install ib_async yfinance pandas numpy requests exchange_calendars

# Cron (PT timezone)
0 18 * * 0,1,2,3,4 python /scripts/scan_evening.py     # Sun-Thu 6PM
5 18 * * 1,2,3,4,5 python /scripts/hedge_quarterly.py   # Mon-Fri 6:05PM
30 12 * * 1,2,3,4,5 python /scripts/overlay_etf.py      # Mon-Fri 12:30PM
0 6 * * 1,2,3,4,5 python /scripts/trade_morning.py      # Mon-Fri 6AM
*/30 * * * * python /scripts/intraday_update.py          # Every 30min
```

---

## Going Live — Pass Criteria

| Check | Target |
|---|---|
| Win rate | 57-63% over 100+ trades |
| Trades per month | 65-90 |
| Script uptime | 100% (0 missed mornings) |
| Gateway connectivity | VPS migration required |

**Current status (May 2026):** 54 trades, ~2-3 more months needed. Gateway reliability unresolved without VPS.

---

## Bugs Fixed (April–May 2026)

1. Stray PowerShell line in trade_morning.py — NameError crash, positions never saved for weeks
2. ClientId mismatch — IBKR only returns fills to same clientId
3. LOO orders wiped by IBKR nightly reset — moved to pending_entries DB
4. MOO/LOO ValidationError 321 at 6 PM PT — OPG orders only valid 7-9:28 AM ET
5. Task Scheduler at 6:15 AM PT — only 13 min before OPG cutoff, changed to 6:00 AM
6. capital cap crashing on None portfolio_value
7. scan_evening.py same None crash
8. IBC config.ini overriding bat file credentials — account lockouts
9. git pull in intraday corrupting index.html
10. Unicode box-drawing chars leaking into summary.json
11. overlay_etf.py at 6:10 PM PT — MOC orders expired overnight, changed to 12:30 PM
12. overlay_etf.py updating DB before confirming IBKR acceptance
13. Buying power check using est_cost=0 when yfinance fails
14. trade_morning.py placing all signals regardless of available cash
15. DB/IBKR sync after exits and resets
16. Stock splits showing incorrect P&L — CVNA 5-for-1 May 2026
17. _port reference error in intraday_update.py
18. Overlay live P&L showing $0 — called ib.portfolio() after disconnect
19. NaN in summary.json breaking dashboard — yfinance returns NaN for VIX3M when market closed
20. Dashboard JS null errors from removed overlay HTML elements
21. trade_morning.py running on NYSE holidays — caused DB/IBKR mismatch
22. False split detection on LUV/NLY — yfinance validation added
23. Exit orders not capped to IBKR share count — could create shorts
24. Duplicate trade_log entries from holiday-queued orders
25. Flat overlay reserve (32%) blocking MR capital — changed to signal-based

---

## Do-Not-Retry Table

| Approach | Why |
|---|---|
| Price-based stop-losses (-3%) | 22.6% hit stop then bounced |
| Portfolio halt at -10% DD | Fired permanently 2004-2006 |
| Streak / rolling WR adaptive sizing | CAGR -3 to -5pp |
| TLT Bear overlay live | Net negative in backtest vs removing |
| HYG Credit Carry live | Marginal, frees capital |
| ZROZ Panic live | Marginal, frees capital |
| Bear SECROT | -0.74pp CAGR |
| Tier priority signal ranking | -1.07pp CAGR (RSI/ATR optimal) |
| Dollar volume filter > $5M | No improvement at $10M-$20M |
| Notional backtest CAGR (34.75%) as live target | Not achievable; cash-constrained (20.2%) is realistic |
| IBC auto-login on Windows paper account | Account lockouts |
| MOC orders at 6:10 PM PT | Cancelled overnight |
| Flat overlay capital reserve | Blocks MR when overlays OUT |
| git pull in intraday_update.py | Overwrites index.html |
| Running reset_all.py with pending orders | Creates shorts |
| Excluding tickers with missing yfinance earnings | Eliminates ~80% of signals |

---

## Walk-Forward Validation (V47)

| Window | OOS Period | CAGR | Result |
|---|---|---|---|
| W1 | 2009-2010 | 28.3% | PASS |
| W2 | 2011-2012 | 26.0% | PASS |
| W3 | 2013-2014 | 41.2% | PASS |
| W4 | 2015-2016 | 15.8% | PASS |
| W5 | 2017-2018 | 12.0% | PASS |
| W6 | 2019-2020 | 51.8% | PASS |
| W7 | 2021-2022 | -12.7% | FAIL |
| W8 | 2023-2025 | 4.8% | PASS |

OOS Positive: 7/8 | OOS Avg CAGR: 20.91%

---

## Disclaimer

Educational and research purposes only. Past backtest performance does not guarantee future results. Not financial advice. Level 3 options approval required. Realistic live target: ~20% CAGR gross, ~11-13% net after slippage and taxes. Cash-constrained backtest (`backtest_v75_cash_constrained.py`) is the only valid performance reference.
