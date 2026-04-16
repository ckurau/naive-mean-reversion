# Naive Mean Reversion (NMR) Backtest

A survivorship-bias-free backtest of a Naive Mean Reversion strategy across all historical S&P 500 + S&P 400 MidCap + S&P 600 SmallCap constituents, automated via GitHub Actions.

---

## Current Version: V35 + Idea 3 (Put Spread Hedge)

**Active strategy: V35 base logic + quarterly SPY 5%/15% OTM put spread hedge.**

The put spread is not a backtest variant — it is executed live via `hedge_quarterly.py` and runs alongside the MR strategy in paper trading.

---

## Architecture (V35 + hedge)

```
backtest-nmr.py           Thin wrapper → imports backtest_nmr_lib.py (V35)
backtest_nmr_lib.py       All V35 backtest logic and parameters
backtest_ideas_v2.py      Multi-test runner: 4 new drawdown ideas vs V35
ideas_v2_backtest.yml     GitHub Actions workflow for ideas_v2 tests
scan_evening.py           Live: evening signal scan + LOO order submission (6:00 PM PT)
trade_morning.py          Live: morning exit orders + fill confirmation (6:15 AM PT)
hedge_quarterly.py        Live: quarterly SPY put spread entry/roll (6:05 PM PT)
check_signals.py          Diagnostic: preview tonight's signals (read-only, no orders)
check_today.py            Diagnostic: show today's closed trades + open positions
check_log.py              Diagnostic: show today's trade.log entries
walkforward.py            Walk-forward validation runner
preflight.py              Pre-flight system check
positions_check.py        CLI: view open/closed positions + P&L
```

**Two-script live execution (unchanged from V35):**
- `scan_evening.py` — 6:00 PM PT, scans universe using today's closing prices, submits LOO buy orders
- `trade_morning.py` — 6:15 AM PT, submits MOO exit orders, holds until 6:35 AM for fill confirmation

**Third script added (hedge):**
- `hedge_quarterly.py` — 6:05 PM PT daily, self-exits in <1 second on non-action days, opens/rolls SPY put spread quarterly

---

## Best Confirmed Results

### V35 + Idea 3 (Current Recommended — Taxable Account)

| Metric | Value |
|---|---|
| CAGR | 19.71% |
| Max Drawdown | -52.87% |
| Sharpe Ratio | 0.74 |
| Profit Factor | 1.07 |
| Final Equity (from $100k) | $4,513,155 |
| Period | 2004–2026 (~21 years) |

**Put spread net P&L over 21 years:**
- Premiums paid: -$2,367k (88 quarterly renewals at ~1.5%/quarter)
- Payouts received: +$4,317k (25 events)
- Net profit from hedge: +$1,950k

### V35 Baseline (Max Wealth, No Hedge)

| Metric | Value |
|---|---|
| CAGR | 18.91% |
| Max Drawdown | -55.89% |
| Sharpe Ratio | 0.71 |
| Profit Factor | 1.06 |
| Final Equity (from $100k) | $4,131,883 |

### V32d (Roth IRA / Lower Drawdown Tolerance)

| Metric | Value |
|---|---|
| CAGR | 15.37% |
| Max Drawdown | -39.21% |
| Sharpe Ratio | 0.77 |
| Final Equity (from $100k) | $2,144,611 |

### C_TurnOfMonth (Middle Ground)

| Metric | Value |
|---|---|
| CAGR | 16.20% |
| Max Drawdown | -48.91% |
| Sharpe Ratio | 0.71 |
| Final Equity (from $100k) | $2,516,582 |

---

## Four-Way Comparison

| Strategy | CAGR | Equity | MaxDD | Sharpe | Best For |
|---|---|---|---|---|---|
| V35 + Idea 3 | 19.71% | $4.51M | -52.9% | 0.74 | Max wealth, taxable, with hedge |
| V35 | 18.91% | $4.13M | -55.9% | 0.71 | Max wealth, taxable, no hedge |
| C_TurnOfMonth | 16.20% | $2.52M | -48.9% | 0.71 | Middle ground |
| V32d | 15.37% | $2.15M | -39.2% | 0.77 | Roth IRA, lower DD tolerance |

---

## V35 Strategy Rules

| Rule | Detail |
|---|---|
| Universe | S&P 500 + S&P 400 MidCap + S&P 600 SmallCap (current + historical, avoids survivorship bias) |
| Trend filter | Stock must be above its 200-day SMA |
| Entry signal | 4+ consecutive down days AND RSI(2) < 20 AND ATR > 1% AND volume > 20-day avg AND dollar volume > $5M/day |
| Entry execution | Buy at open of next day via LOO order (limit = prior close × 1.005) |
| Gap filters | Skip if next open gaps down > 1.0% OR gaps up > 2% |
| Exit — all tiers | 2% profit target, 8-day time stop (uniform) |
| Tier 1 partial | 6+ down days: 50% at 1%, remainder at 2% |
| Tier 2 | 5 down days: 2% target, 8-day window, no partial |
| Tier 3 | 4 down days: 2% target, 8-day window, no partial |
| Min hold | 2 calendar days before profit exit allowed |
| Max positions | 60 simultaneous holdings |
| Position size | VIX < 25 → 9%, VIX ≥ 25 → 5% base |
| Tiered sizing | Top 20% of signals by composite score get 1.3x size, hard cap 12% |
| Signal ranking | Composite score: RSI(2) / ATR_pct |
| Sector filter | Skip entry if stock's sector ETF is below its 20-day MA |
| Correlation cap | Max 3 open positions in same sector |
| Earnings blackout | Skip entries within ±3 days of earnings announcement |
| SPY regime | No new entries when SPY is below its 200-day MA |
| Re-entry cooldown | No re-entry in a stock for 5 days after a time-stop exit |
| Velocity crash pause | SPY 5-day return < -12% → pause all entries for 5 days |
| Earnings month cap | Position size capped at 2.4% in Jan/Apr/Jul/Oct |
| Commission | $0.005/share or $0.35 minimum per trade |

---

## Idea 3: Quarterly SPY Put Spread (Live)

### What it does
Buys a 5%/15% OTM SPY put spread every ~63 trading days. The spread pays out linearly when SPY drops 5–15%+ from the quarterly reference price, capping at 10% of notional at the 15% level. Premium is ~1.5% of portfolio per quarter at current VIX.

### Parameters (hedge_quarterly.py)
| Parameter | Value |
|---|---|
| Long put | 5% OTM from current SPY |
| Short put | 15% OTM from current SPY |
| Target DTE | 63 trading days (~quarterly) |
| Contracts | 1 (appropriate for $100k account) |
| Max debit | $15/contract (refuses if too expensive) |
| Auto-roll | Yes — closes and reopens 5 days before expiry |

### Historical payout events (21-year backtest)
| Date | SPY ref | SPY low | Pct | Payout |
|---|---|---|---|---|
| 2008-10-28 | $91.47 | $60.90 | 10.0% | $32k |
| 2009-01-30 | $69.86 | $54.73 | 10.0% | $35k |
| 2009-05-04 | $61.24 | $49.81 | 10.0% | $38k |
| 2011-08-15 | $102.04 | $86.44 | 10.0% | $90k |
| 2018-12-31 | $260.13 | $210.18 | 10.0% | $446k |
| 2020-04-08 | $298.51 | $204.94 | 10.0% | $622k |
| 2022-07-22 | $403.15 | $346.95 | 8.9% | $659k |
| 2025-05-13 | $594.73 | $490.85 | 10.0% | $1.13M |

### IBKR requirements
- Level 3 options approval required (Settings → Trading → Trading Permissions)
- Paper account has unrestricted options access for testing without approval
- Script uses same IB Gateway connection as MR scripts (port 4002 paper / 4001 live)
- Client ID 30 (distinct from scan_evening ID 10 and trade_morning ID 20)

---

## Gateway Schedule

IB Gateway must be running at these times daily (weekdays):

| Time (PT) | Script | Action |
|---|---|---|
| 6:00 PM | scan_evening.py | Scans signals, submits LOO orders |
| 6:05 PM | hedge_quarterly.py | Checks/rolls put spread (fast exit if no action needed) |
| 6:15 AM | trade_morning.py | Submits exits, confirms LOO fills |

**Recommendation: leave Gateway running 24/7.** It is lightweight when idle and occasional re-authentication prompts are the only maintenance needed.

---

## Walk-Forward Validation: V34 (Confirmed PASS — applies to V35)

| Window | OOS Period | CAGR | WR | PF | MaxDD | Sharpe | Regime |
|---|---|---|---|---|---|---|---|
| W1 | 2009–2010 | 24.9% | 61.3% | 1.31 | -14.6% | 1.17 | Recovery |
| W2 | 2011–2012 | 25.9% | 63.9% | 1.23 | -33.5% | 0.75 | Chop/Dip |
| W3 | 2013–2014 | 39.6% | 59.3% | 1.23 | -32.1% | 1.31 | Bull |
| W4 | 2015–2016 | 15.0% | 58.4% | 1.17 | -18.1% | 0.83 | Chop |
| W5 | 2017–2018 | 9.3% | 57.0% | 1.05 | -29.5% | 0.39 | Low-Vol Bull |
| W6 | 2019–2020 | 47.5% | 62.7% | 1.37 | -36.3% | 1.16 | Bull+Crash |
| W7 | 2021–2022 | -11.7% | 54.6% | 0.93 | -46.3% | -0.34 | Bear Grind |
| W8 | 2023–2025 | 5.1% | 60.0% | 1.03 | -54.6% | 0.35 | AI Bull + Tariff Bear |

OOS positive CAGR windows: 7/8 — **PASS**

---

## Ideas V2: Full Research Results (April 2026)

Tested 4 new drawdown-reduction ideas against V35 baseline. Run via `backtest_ideas_v2.py`.

| Test | CAGR | MaxDD | Sharpe | Final Equity | Notes |
|---|---|---|---|---|---|
| Baseline V35 | 18.91% | -55.89% | 0.71 | $4,131,883 | — |
| Idea1 TwinEngine | 18.39% | -56.51% | 0.70 | $3,955,853 | Worse on both metrics |
| Idea2 PortVol | 15.85% | -52.55% | 0.67 | $2,361,854 | 3pp DD improvement, −3pp CAGR |
| **Idea3 PutSpread** | **19.71%** | **-52.87%** | **0.74** | **$4,513,155** | **Only idea that improves all three metrics** |
| Idea4 SectorStreak | 18.86% | -55.92% | 0.71 | $4,095,831 | Neutral — no meaningful effect |
| Ideas2+3 | 16.55% | -49.62% | 0.69 | $2,534,726 | Best MaxDD combo, lower equity |
| Ideas3+4 | 19.66% | -52.89% | 0.74 | $4,474,449 | Near-identical to Idea3 alone |

**Conclusion:** Idea 3 (put spread) is the only idea that improves CAGR, MaxDD, and Sharpe simultaneously. At realistic 1.5%/quarter cost, the hedge generates net +$1.95M profit over 21 years because SPY experienced four max-payout events (2008, 2020, 2022, 2025).

---

## Drawdown Research: Confirmed Structural — Do Not Retry

After exhaustive testing across V35–V40 sessions and April 2026 research, the following conclusion is definitive: **the MR strategy's max drawdown cannot be reduced without sacrificing CAGR within the signal/sizing framework.** The put spread hedge is the exception because it operates outside the signal framework as insurance.

### What the streak analysis proved

From V34 trade data (18,775 trades after excluding partials):

| Streak | Next Trade WR | vs Baseline 58.6% |
|---|---|---|
| After 3 consecutive losses | 26.6% (n=3,423) | -32pp |
| After 4 consecutive losses | 23.1% (n=2,511) | -35.5pp |
| After 5 consecutive losses | 20.9% (n=1,930) | -37.7pp |
| After 10 consecutive losses | 13.9% (n=718) | -44.7pp |

Loss streak trades (45.8% of all trades) account for -$13.98M total P&L. Non-streak trades (54.2%) account for +$14.65M. **The edge is entirely in non-streak periods.** Every filter that reduces streak exposure also reduces crash-recovery entries.

---

## Complete Do-Not-Retry Table

Every approach below has been tested and confirmed to reduce equity or fail to improve the risk/return profile.

| Approach | Why It Failed |
|---|---|
| Price-based stop-losses (-3%) | 22.6% hit stop then bounced |
| Portfolio-level halt at -10% DD | Fired permanently 2004–2006 |
| ROC entry filter (down 4%+ from streak start) | Killed 68% of trades |
| SPY 50d guard | Blocked 2009 recovery |
| SPY same-day entry filter | Filtered trades had higher EV |
| VIX spike exit | Cut positions before bounces |
| First-up-close exit | Dominated 54% of exits (V18) |
| Tier 3 target differentiation | Every variant underperformed uniform 2% |
| Conditional bear filter | Broke 2020 velocity pause interaction |
| Bull regime entry block | 55.9% WR was still profitable |
| Streak filter (3 losses=50% size) | MaxDD -8pp but CAGR -4.72pp, equity -$2.2M |
| Rolling WR adaptive sizing | MaxDD -7pp but CAGR -3.71pp; trigger fires during crash-recovery |
| Equity curve trading (size down < 20d MA) | CAGR -3.30pp, MaxDD unchanged |
| Continuous vol-scaled sizing (per-stock) | CAGR -2.07pp, MaxDD -1pp |
| Per-stock EWMA vol filter | CAGR -4.74pp, MaxDD worse |
| Signal density stress filter (>40 signals → 0.5x) | -$519k. Crash recovery days blocked |
| Breadth filter (<40% stocks above 20d/50d MA) | -$2,899k. Fired ~50% of days |
| Index vs constituents divergence | -$455k. Only fired 68 days |
| MFE-based entry pause | Fired 54.8% of days, miscalibrated |
| Friday entry filter | -$1,340k. Volume loss overwhelmed quality gain |
| IBS < 0.35 filter | -$2,150k. Killed crash-recovery entries |
| EMA 20/50 downtrend block | -$1,470k. Blocked crash-recovery AND worsened MaxDD |
| Inverse ETF v1 (direct signal) | 57 signals in 21 years — too rare |
| Bond allocation in bear regime | -$2,113 across 146 trades; 2022 bonds fell with equities |
| Inverse ETF v2 (SPY overbought) | SH P&L -$10,075. Structural daily rebalancing decay |
| Volume peak on final down day | CAGR -6.33pp |
| Gap filter tightening to -0.75% | CAGR -2.59pp, equity -$1,433k |
| Gap filter tightening to -0.50% | CAGR -4.53pp, equity -$2,154k |
| Tier multiplier 1.5x or 2.0x | Diminishing CAGR gain, growing DD cost |
| Bear regime overlays (GLD/TLT/SH/XLE/XLU/BTAL) | Best result: +0.58% CAGR over 22 years. Capital sits idle 77% of time |
| Twin-engine bear momentum (Ideas V2 Idea 1) | MaxDD worse (-56.51%), CAGR lower |
| Portfolio-level vol targeting (Ideas V2 Idea 2) | 3pp DD improvement but 3pp CAGR cost; structural tension |
| Per-sector streak filtering (Ideas V2 Idea 4) | Neutral — statistically zero effect |
| Ideas 2+3 combo | MaxDD -49.6% but CAGR -2.4pp and $1.6M less equity vs Idea3 alone |

---

## Optimism Bias Warnings

V35's 18.91% CAGR is the in-sample ceiling, not the live expectation.

| Source | Estimated CAGR Impact |
|---|---|
| Slippage on open prices | -2 to -3% |
| Survivorship bias | -1 to -2% |
| Overfitting across 50+ iterations | -2 to -3% |
| Earnings calendar lookahead | -0.3 to -0.5% |
| VIX regime parameters tuned to history | -1 to -2% |
| **Realistic live estimate** | **~8 to 12% CAGR gross** |

Apply ~26% walk-forward decay: 18.91% × 0.74 = ~14.0% live gross.
After short-term capital gains tax (32–37%), realistic net CAGR is likely 8–10%.

---

## The Honest Risk Picture

V35 + hedge at ~$4.5M peak equity:
- The -52.87% max drawdown means a potential ~$2.4M paper loss peak-to-trough
- 2022 lost ~$1.2M in a single year at that equity level (partially offset by put payouts)
- 60 positions is the confirmed ceiling
- Win rate is the anchor — if live win rate drops below 56%, the strategy is failing

---

## Paper Trading & Live Automation

**Status: LIVE (paper trading active as of April 2026)**

| Item | Detail |
|---|---|
| Broker | Interactive Brokers (IBKR) paper account |
| Starting equity | $100,000 |
| Scripts | scan_evening.py (6:00 PM PT) + hedge_quarterly.py (6:05 PM PT) + trade_morning.py (6:15 AM PT) |
| Scheduler | Windows Task Scheduler — three tasks |
| Entry orders | Limit On Open (LOO), limit = prior_close × 1.005 |
| Exit orders | MOO |
| Database | C:\nmr-trader\positions.db — SQLite (4 tables + hedge_positions table) |
| Max positions | 60 (matches V35) |

### Pass Criteria for Moving to Live Capital

| Check | Target | Action if failing |
|---|---|---|
| Win rate | 57–63% over 100+ trades | Stop — review signal logic |
| Trades per month | 65–90 | Check universe fetch and signal parameters |
| Worst single month | Better than -15% | Review if repeated |
| Script ran every trading day | 100% | Fix Gateway startup |
| LOO fill rate | >70% of orders fill | Increase LOO_LIMIT_BUFFER to 0.010 |
| Slippage vs prior close | Under 0.6% avg | Higher for small-caps expected |

### Going Live — Three Changes Only
1. `IBKR_PORT = 4001` (was 4002 paper) — change in scan_evening.py, trade_morning.py, hedge_quarterly.py
2. Switch Gateway from Paper to Live account
3. Apply for Level 3 options approval on real account before running hedge_quarterly.py live

---

## Diagnostic Scripts

| Script | Command | Purpose |
|---|---|---|
| check_signals.py | `venv\Scripts\python.exe check_signals.py` | Preview tonight's signals (no orders placed) |
| check_today.py | `venv\Scripts\python.exe check_today.py` | Today's closed trades + open positions |
| check_log.py | `venv\Scripts\python.exe check_log.py` | Today's trade.log entries |
| list_tasks.py | `venv\Scripts\python.exe list_tasks.py` | All Task Scheduler tasks and trigger times |
| preflight.py | `venv\Scripts\python.exe preflight.py` | Pre-flight system check before first run |
| positions_check.py | `venv\Scripts\python.exe positions_check.py` | Open positions with live prices + P&L |

---

## Repository Structure

```
.
├── backtest-nmr.py               # Thin wrapper — imports from backtest_nmr_lib.py
├── backtest_nmr_lib.py           # All V35 backtest logic and parameters
├── backtest_ideas_v2.py          # Ideas V2 multi-test runner (4 ideas)
├── backtest_ideas.py             # Original ideas test (equity curve, vol scaling, turn-of-month)
├── backtest_bear_momentum.py     # Bear regime overlay tests (all failed — abandoned)
├── walkforward.py                # Walk-forward validation runner
├── scan_evening.py               # Live: evening signal scan + LOO order submission
├── trade_morning.py              # Live: morning exit orders + fill confirmation
├── hedge_quarterly.py            # Live: quarterly SPY put spread entry/roll
├── check_signals.py              # Diagnostic: preview tonight's signals
├── check_today.py                # Diagnostic: today's closed trades + open positions
├── check_log.py                  # Diagnostic: today's trade.log entries
├── list_tasks.py                 # Diagnostic: Task Scheduler entries
├── preflight.py                  # Pre-flight system check
├── positions_check.py            # CLI: view open/closed positions + P&L
├── diag.py                       # SPY regime / DB diagnostic
├── scan_debug.py                 # Signal scanner filter funnel debug
├── requirements.txt
├── README-nmr.md                 # This file
├── results/                      # V35 backtest outputs
├── results_ideas/                # Original ideas backtest outputs
├── results_ideas_v2/             # Ideas V2 backtest outputs (14 tests)
│   ├── comparison.json
│   └── Idea3_PutSpread/
│       ├── metrics.json
│       ├── trades.csv
│       ├── trades_all.csv        # Includes SPY_PUT_SPREAD rows
│       └── equity_curve.csv
└── .github/workflows/
    ├── backtest.yml              # Main V35 backtest workflow
    ├── ideas_backtest.yml        # Original ideas workflow
    └── ideas_v2_backtest.yml     # Ideas V2 workflow (14 tests, tunable params)
```

---

## Setup & Running

### GitHub Actions (backtest)
1. Push all files to repo
2. Settings → Actions → General → Workflow permissions → Read and write
3. Actions → Naive MR Backtest → Run workflow

### Ideas V2 Backtest (GitHub Actions)
Actions → Ideas V2 Backtest → Run workflow

Tunable dispatch inputs:
- `put_cost` — quarterly premium fraction (default 0.015 = 1.5% of portfolio)
- `twin_alloc` — bear momentum allocation (default 0.25)
- `pvol_target` — portfolio vol target (default 0.15)
- `sector_streak_trigger` — losses before sector size cut (default 3)
- `tests_to_run` — comma-separated test names to run subset (e.g. `Baseline_V35,Idea3_PutSpread`)

### Local Backtest
```
pip install -r requirements.txt
venv\Scripts\python.exe backtest-nmr.py
venv\Scripts\python.exe walkforward.py
```

### Live Trading Setup
```
cd C:\nmr-trader
venv\Scripts\python.exe preflight.py
```
Ensure Gateway is running before 6:00 PM PT (evening scan) and remains open through 6:40 AM PT next morning.

---

## Dependencies

```
yfinance>=0.2.40
pandas>=2.1.0
numpy>=1.26.0
requests>=2.31.0
tqdm>=4.66.0
lxml>=4.9.0
html5lib>=1.1
ib_async>=1.0.0
```

---

## Disclaimer

Educational and research purposes only. Past backtest performance does not guarantee future results. Not financial advice. Consult a licensed financial advisor and CPA before trading with real capital. V35's aggressive position sizing (60 positions, up to 11.7% each for top signals when VIX < 25) and the put spread hedge (Level 3 options required) are suitable only for those who understand and can hold through drawdowns of -53%+. V32d is the recommended alternative for Roth IRA accounts (MaxDD -39%, Sharpe 0.77).
