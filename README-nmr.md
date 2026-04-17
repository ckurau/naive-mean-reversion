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
backtest_ideas_v2.py      Multi-test runner: Ideas V2 (put spread, twin engine, port vol, sector streak)
backtest_ideas_v3.py      Multi-test runner: Ideas V3 (VIX TS, 52wk high, gap capture, analyst, calls)
backtest_ideas_v4.py      Multi-test runner: Ideas V4 (overnight, salience, dispersion, skew, turnover, corr, recycle)
ideas_v2_backtest.yml     GitHub Actions workflow for ideas_v2 tests
ideas_v3_backtest.yml     GitHub Actions workflow for ideas_v3 tests
ideas_v4_backtest.yml     GitHub Actions workflow for ideas_v4 tests
scan_evening.py           Live: evening signal scan + LOO order submission (6:00 PM PT)
trade_morning.py          Live: morning exit orders + fill confirmation (6:15 AM PT)
hedge_quarterly.py        Live: quarterly SPY put spread entry/roll (6:05 PM PT)
check_signals.py          Diagnostic: preview tonight's signals (read-only, no orders)
check_today.py            Diagnostic: show today's closed trades + open positions
check_log.py              Diagnostic: show today's trade.log entries
list_tasks.py             Diagnostic: show Windows Task Scheduler entries and trigger times
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

## Ideas V3: Full Research Results (April 2026)

Tested 6 new ideas (VIX term structure, 52wk high proximity, gap capture sub-tier, analyst dispersion, call spread overlay) against V35+I3 baseline. Run via `backtest_ideas_v3.py`. 17 total tests.

| Test | CAGR | MaxDD | Sharpe | Final Equity | Notes |
|---|---|---|---|---|---|
| Baseline V35 | 18.72% | -55.89% | 0.71 | $3,995,384 | Reference |
| **Baseline V35+I3** | **19.53%** | **-53.06%** | **0.73** | **$4,364,842** | **Current best** |
| IdeaD VixTS | 18.66% | -55.75% | 0.70 | $3,949,405 | Nearly identical to baseline |
| IdeaE 52wkHigh | 15.42% | -54.66% | 0.64 | $2,180,577 | -4pp CAGR for 1.2pp MaxDD gain |
| IdeaB GapCapture | 14.74% | -57.76% | 0.62 | $2,295,612 | Contaminates cooldown tracking |
| IdeaC Analyst | 18.72% | -55.89% | 0.71 | $3,995,384 | Zero effect (static data) |
| IdeaF CallSpread | 18.53% | -53.13% | 0.71 | $3,446,559 | -$548k equity for 2.76pp MaxDD |
| IdeaF+I3 | 19.29% | -51.49% | 0.74 | $3,759,789 | Best Sharpe, -$605k vs puts-only |
| IdeaD+E+I3 | 16.15% | -52.71% | 0.67 | $2,299,335 | Combination worse than either alone |
| Kitchen_Sink | 12.98% | -47.59% | 0.61 | $1,230,392 | Every idea combined — worst equity |

**Conclusion:** No V3 idea improves on V35+I3. The ranking enhancements (Ideas 1, 2, 4, 5 in V4) were identified as a root cause: with 60 positions and rarely more than 20–30 candidates, re-ranking has no effect. Idea 3 (put spread) remains the confirmed ceiling.

---

## Ideas V4: Full Research Results (April 2026)

Tested 7 signal quality ideas grounded in SSRN/academic research: overnight return decomposition, salience/sector-relative ranking, VVIX dispersion regime, return skewness filter, turnover-adjusted ranking, cross-asset correlation regime scaling, time-stop recycling. 24 total tests including combinations.

Core finding confirmed: **ranking enhancements (Ideas 1, 2, 4, 5) have zero effect when the 60-position cap is rarely binding.** On a typical day with 10–30 candidates and 60 slots, all candidates get filled regardless of rank. These ideas would require dropping the position cap to ~30 to have measurable impact.

| Test | CAGR | MaxDD | Sharpe | Final Equity | Notes |
|---|---|---|---|---|---|
| Baseline V35 | 18.88% | -55.89% | 0.71 | $4,112,818 | Reference |
| **Baseline V35+I3** | **19.69%** | **-52.86%** | **0.74** | **$4,492,222** | **Current best (confirmed)** |
| Idea1 Overnight | 18.87% | -55.89% | 0.71 | $4,101,836 | Identical to baseline |
| Idea2 Salience | 18.87% | -55.89% | 0.71 | $4,101,836 | Identical to baseline |
| Idea3 Dispersion | 18.49% | -59.89% | 0.69 | $3,831,462 | MaxDD worsens 4pp |
| Idea4 Skewness | 18.87% | -55.89% | 0.71 | $4,101,836 | Identical to baseline |
| Idea5 Turnover | 18.87% | -55.89% | 0.71 | $4,101,836 | Identical to baseline |
| Idea6 CorrRegime | 15.13% | -50.34% | 0.66 | $2,062,953 | 5.55pp MaxDD gain costs -$2M equity |
| Idea7 Recycle | 18.73% | -55.89% | 0.71 | $4,003,538 | Small net drag |
| Idea6+I3 (floor=0.70) | 18.37% | -51.08% | 0.72 | $3,540,958 | 1.78pp MaxDD, costs -$951k |
| SignalCombo+I3 | 19.67% | -52.87% | 0.74 | $4,479,092 | Identical to V35+I3 |
| Kitchen_Sink | 15.49% | -50.94% | 0.67 | $2,085,309 | Everything combined — not worth it |

**Conclusion:** V35 + Idea3 put spread is definitively confirmed as the research ceiling. The correlation regime scaling (Idea6) has a structurally correct mechanism but misses recovery entries at every calibration tested, converting MaxDD improvement into equity loss. No further signal/sizing research is warranted.

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
| VIX term structure scaling — any floor/sensitivity (Ideas V3 IdeaD) | Effect too gentle even at 0.25 floor; VIX rarely deeply inverted during grinds |
| 52-week high proximity filter — any threshold (Ideas V3 IdeaE) | -4pp CAGR, -$2M equity for 1.2pp MaxDD improvement; blocks too many good setups |
| Gap capture sub-tier (Ideas V3 IdeaB) | Contaminates MR cooldown tracking; worse CAGR and MaxDD |
| Analyst dispersion re-ranking (Ideas V3 IdeaC) | Requires historical data; static yfinance data has zero effect |
| Call spread overlay standalone (Ideas V3 IdeaF) | -$548k equity for 2.76pp MaxDD improvement; net drag in bull markets |
| Call spread + put spread collar (Ideas V3 IdeaF+I3) | Best Sharpe (0.74) but -$605k vs puts-only; complexity not justified |
| Overnight return decomposition ranking (Ideas V4 Idea1) | Zero effect — 60-position cap rarely binding; ranking doesn't matter |
| Salience/sector-relative ranking (Ideas V4 Idea2) | Zero effect — same reason as above |
| VVIX/VIX dispersion regime scaling (Ideas V4 Idea3) | MaxDD worsens 4pp; VVIX spikes during crashes regardless of dispersion |
| Return skewness ranking (Ideas V4 Idea4) | Zero effect — 60-position cap rarely binding |
| Turnover-adjusted ranking (Ideas V4 Idea5) | Zero effect — 60-position cap rarely binding |
| Cross-asset correlation regime scaling (Ideas V4 Idea6) | Correct mechanism, wrong magnitude at any calibration; 1.78pp MaxDD gain costs -$951k equity |
| Time-stop recycling (Ideas V4 Idea7) | Small net drag; exhausted sellers thesis fails at 1-2 day horizon |

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
├── backtest_ideas_v2.py          # Ideas V2 multi-test runner (14 tests)
├── backtest_ideas_v3.py          # Ideas V3 multi-test runner (17 tests)
├── backtest_ideas_v4.py          # Ideas V4 multi-test runner (24 tests)
├── backtest_ideas.py             # Original ideas test (equity curve, vol scaling, turn-of-month)
├── backtest_bear_momentum.py     # Bear regime overlay tests (all failed — abandoned)
├── walkforward.py                # Walk-forward validation runner
├── scan_evening.py               # Live: evening signal scan + LOO order submission
├── trade_morning.py              # Live: morning exit orders + fill confirmation
├── hedge_quarterly.py            # Live: quarterly SPY put spread entry/roll
├── check_signals.py              # Diagnostic: preview tonight's signals
├── check_today.py                # Diagnostic: today's closed trades + open positions
├── check_log.py                  # Diagnostic: today's trade.log entries
├── list_tasks.py                 # Diagnostic: Task Scheduler entries and trigger times
├── preflight.py                  # Pre-flight system check
├── positions_check.py            # CLI: view open/closed positions + P&L
├── diag.py                       # SPY regime / DB diagnostic
├── scan_debug.py                 # Signal scanner filter funnel debug
├── requirements.txt
├── README-nmr.md                 # This file
├── results/                      # V35 backtest outputs
├── results_ideas/                # Original ideas backtest outputs
├── results_ideas_v2/             # Ideas V2 outputs (14 tests)
├── results_ideas_v3/             # Ideas V3 outputs (17 tests)
├── results_ideas_v4/             # Ideas V4 outputs (24 tests)
│   └── comparison.json           # All test summary (each dir has trades.csv, metrics.json, equity_curve.csv)
└── .github/workflows/
    ├── backtest.yml              # Main V35 backtest workflow
    ├── ideas_backtest.yml        # Original ideas workflow
    ├── ideas_v2_backtest.yml     # Ideas V2 workflow (14 tests, tunable params)
    ├── ideas_v3_backtest.yml     # Ideas V3 workflow (17 tests, tunable params)
    └── ideas_v4_backtest.yml     # Ideas V4 workflow (24 tests, tunable params)
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

### Ideas V3 Backtest (GitHub Actions)
Actions → Ideas V3 Backtest → Run workflow

Tunable dispatch inputs:
- `put_cost` — put spread quarterly cost (default 0.015)
- `vix_ts_floor` — Idea D VIX term structure min scale (default 0.40)
- `high_proximity_pct` — Idea E 52wk high max distance (default 0.20)
- `call_vix_max` — Idea F max VIX to sell call spread (default 15.0)
- `tests_to_run` — comma-separated subset

### Ideas V4 Backtest (GitHub Actions)
Actions → Ideas V4 Backtest → Run workflow

Tunable dispatch inputs:
- `overnight_boost` — Idea1 score multiplier for high-overnight stocks (default 0.70)
- `salience_threshold` — Idea2 min sector underperformance (default 0.03)
- `skew_weight` — Idea4 skewness component weight (default 1.5)
- `turnover_weight` — Idea5 turnover component weight (default 1.5)
- `corr_floor` — Idea6 min size scale at peak correlation (default 0.70)
- `tests_to_run` — comma-separated subset

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
scipy>=1.11.0
requests>=2.31.0
tqdm>=4.66.0
lxml>=4.9.0
html5lib>=1.1
ib_async>=1.0.0
```

---

## Disclaimer

Educational and research purposes only. Past backtest performance does not guarantee future results. Not financial advice. Consult a licensed financial advisor and CPA before trading with real capital. V35's aggressive position sizing (60 positions, up to 11.7% each for top signals when VIX < 25) and the put spread hedge (Level 3 options required) are suitable only for those who understand and can hold through drawdowns of -53%+. V32d is the recommended alternative for Roth IRA accounts (MaxDD -39%, Sharpe 0.77).
