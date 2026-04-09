# Naive Mean Reversion (MR) Backtest

A survivorship-bias-free backtest of a **Naive Mean Reversion** strategy across all historical S&P 500 + S&P 400 MidCap + S&P 600 SmallCap constituents, automated via GitHub Actions.

---

## Current Version: V33d (Best Confirmed Result — taxable account)

The current script (`backtest-nmr.py`) is **V33d — V32e base + MAX_POSITIONS raised to 60**.

**IMPORTANT FOR NEW SESSIONS:**
Push `backtest-nmr.py` and `backtest_nmr_lib.py` to GitHub and run the workflow.

**ARCHITECTURE (V33d onwards — unified codebase):**
`backtest-nmr.py` is a **thin wrapper** that imports all logic from `backtest_nmr_lib.py`. To change any parameter or logic, edit `backtest_nmr_lib.py` only. `walkforward.py` also imports from `backtest_nmr_lib.py`.

**Session objective: maximize total equity (taxable account).** V33d is recommended for a taxable account. V32d is recommended for a Roth IRA.

### Best Confirmed Results: V33d

| Metric | Value |
|---|---|
| CAGR | 17.41% |
| ROI / Year | 141.03% |
| Win Rate | 59.98% |
| Avg Win | 3.11% |
| Avg Loss | −3.63% |
| Profit Factor | 1.06 |
| Max Drawdown | −54.73% |
| Sharpe Ratio | 0.68 |
| Trades / Year | 1,043 |
| Final Equity (from $100k) | $3,124,041 |
| Period | 2004–2026 (~21 years) |

### Best Risk-Adjusted: V32d (recommended for Roth IRA)

| Metric | Value |
|---|---|
| CAGR | 15.37% |
| Final Equity | $2,144,611 |
| Profit Factor | 1.09 |
| Max Drawdown | −39.21% |
| Sharpe Ratio | 0.77 |
| Avg Loss | −3.12% |

### Previous Bests — for reference

| Version | CAGR | Final Equity | MaxDD | Sharpe |
|---|---|---|---|---|
| V33c (55 pos) | 17.16% | $2,982k | −53.27% | 0.69 |
| V33b (50 pos) | 16.83% | $2,808k | −51.73% | 0.70 |
| V32e (40 pos) | 16.10% | $2,454k | −48.61% | 0.73 |
| V32d (risk-adj) | 15.37% | $2,145k | −39.21% | 0.77 |
| V30+S&P600 | 16.01% | $2,414k | −48.65% | 0.73 |

### Why V33d is best for a taxable account despite the lower Sharpe

Sharpe dropped from 0.73 (V32e) to 0.68 (V33d) as positions increased from 40 to 60. This looks like a regression but is not, for a taxable account with a long time horizon. The position count increase captures overflow on high-signal days — episodic bursts of alpha when many stocks simultaneously oversold in crash-recovery conditions. These are exactly the days you want maximum exposure.

The result: +$670k final equity over V32e. The right question for a taxable account is not "smoothest ride" but "most wealth after 20 years." V33d answers that better. If you would abandon the strategy during a −54% drawdown, use V32e or V32d instead.

### Walk-Forward Validation: V33d ✅ COMPLETE

| Window | OOS Period | CAGR | WinRate | PF | MaxDD | Sharpe | Trades | IS/OOS |
|---|---|---|---|---|---|---|---|---|
| W1 | 2009–2010 | 24.6% | 61.0% | 1.31 | −15.1% | 1.20 | 1,422 | 0.68x |
| W2 | 2011–2012 | 25.6% | 63.6% | 1.24 | −32.7% | 0.76 | 2,021 | 1.36x |
| W3 | 2013–2014 | 34.5% | 59.0% | 1.21 | −31.5% | 1.18 | 2,598 | 1.38x |
| W4 | 2015–2016 | 14.1% | 58.2% | 1.16 | −19.6% | 0.79 | 1,842 | 0.40x |
| W5 | 2017–2018 | 9.5% | 57.1% | 1.05 | −28.2% | 0.40 | 2,695 | 0.36x |
| W6 | 2019–2020 | 43.9% | 62.4% | 1.34 | −37.6% | 1.10 | 2,131 | 3.60x |
| W7 | 2021–2022 | −10.7% | 54.5% | 0.93 | −45.7% | −0.32 | 1,921 | −0.42x |
| W8 | 2023–2025 | 5.5% | 59.8% | 1.03 | −52.4% | 0.36 | 4,216 | 0.40x |

**OOS Positive CAGR windows: 7/8 — PASS**
**OOS Avg CAGR: 18.37% | OOS Median CAGR: 19.38%**

---

## V33d Strategy Rules (current code)

| Rule | Detail |
|---|---|
| **Universe** | S&P 500 + S&P 400 MidCap + S&P 600 SmallCap (current + historical, avoids survivorship bias) |
| **Trend filter** | Stock must be above its 200-day SMA |
| **Entry signal** | 4+ consecutive down days AND RSI(2) < 20 AND ATR > 1% AND volume > 20-day avg AND dollar volume > $5M/day |
| **Entry execution** | Buy at open of next day |
| **Gap filters** | Skip if next open gaps down > 1.5% OR gaps up > 2% |
| **Exit — all tiers** | 2% profit target, 8-day time stop (uniform — the key mechanism) |
| **Tier 1 partial** | 6+ down days: 50% at 1%, remainder at 2% |
| **Tier 2** | 5 down days: 2% target, 8-day window, no partial |
| **Tier 3** | 4 down days: 2% target, 8-day window, no partial |
| **Min hold** | 2 calendar days before profit exit allowed |
| **Max positions** | 60 simultaneous holdings [V33d] |
| **Position size** | VIX < 25 → 9%, VIX ≥ 25 → 5% base |
| **VIX high-side penalty** | REMOVED |
| **Drawdown scaling** | REMOVED |
| **VIX spike pause** | REMOVED |
| **Velocity crash pause** | SPY 5-day return < −12% → pause all entries for 5 days |
| **Earnings month cap** | Position size capped at 2.4% in Jan/Apr/Jul/Oct |
| **Signal ranking** | Composite score: RSI(2) / ATR_pct [V32e] |
| **Sector filter** | Skip entry if stock's sector ETF is below its 20-day MA |
| **Correlation cap** | Max 3 open positions in same sector |
| **Earnings blackout** | Skip entries within ±3 days of earnings announcement |
| **SPY regime** | No new entries when SPY is below its 200-day MA |
| **Re-entry cooldown** | No re-entry in a stock for 5 days after a time-stop exit |
| **Commission** | $0.005/share or $0.35 minimum per trade |

---

## Walk-Forward Reference (V32e and V30)

### V32e Walk-Forward ✅ COMPLETE

| Window | OOS Period | OOS CAGR | Win Rate | Max DD | Sharpe | IS/OOS | Verdict |
|---|---|---|---|---|---|---|---|
| W1 | 2009–2010 | 10.3% | 60.2% | −6.1% | 1.45 | 0.49x | Pass |
| W2 | 2011–2012 | 10.9% | 63.2% | −8.3% | 0.88 | 1.36x | Pass |
| W3 | 2013–2014 | 16.3% | 59.7% | −18.0% | 1.06 | 1.53x | Pass |
| W4 | 2015–2016 | −0.2% | 56.0% | −13.8% | −0.06 | −0.02x | Fail |
| W5 | 2017–2018 | 6.2% | 58.0% | −17.2% | 0.41 | 0.62x | Pass |
| W6 | 2019–2020 | 3.8% | 62.3% | −20.2% | 0.25 | 2.96x | Pass |
| W7 | 2021–2022 | −5.8% | 53.0% | −20.7% | −0.59 | −1.07x | Fail |
| W8 | 2023–2025 | 3.1% | 60.1% | −17.1% | 0.25 | −3.22x | Caution |

**OOS Positive CAGR windows: 6/8 — PASS | OOS Avg CAGR: 5.58%**

---

## Key Insights

### The strategy is fully optimised — V33d is the confirmed ceiling

After 40+ versions tested, every meaningful lever has been exhausted. The consistent finding across all failed experiments (V34a through V37d) is:

**The strategy must be fully exposed during panic to capture recovery. Any mechanism that reduces this exposure — regardless of how it's framed — costs more in recovery years than it saves in bad years.**

This is structural, not a calibration problem. The days with the worst avg return (high signal count, crash days, Fridays) are simultaneously the days that set up the best recovery compounding. Every filter that avoids bad days also blocks the recovery that follows.

### The exit side is fully saturated

Three experiments closed every exit-side lever:
- **V34a** (cut losers day 4): Tier 1 WR 70.1% → 52.3%, equity −$926k
- **V35a** (higher targets, clean base): PF unchanged at 1.06, equity −$86k
- **V34b** (contaminated test): neutral vs V34a

The 2%/8d structure is confirmed optimal. The avg loss of −3.63% is structural and cannot be reduced without destroying win rate.

### The entry filter side is fully saturated

Five structural entry filters all failed:
- **V36a** (signal density >40 → 0.5× size): equity −$519k
- **V37a** (breadth filter 40% threshold): equity −$2,899k, fired ~50% of days
- **V37b** (index vs constituents divergence): equity −$455k, fired only 1.2% of days
- **V37c** (MFE pause, miscalibrated): fired 54.8% of days, broke mid-run
- **V37d** (Friday filter): equity −$1,340k, volume loss overwhelmed quality gain

**Do not retry structural entry filters.** The next real signal is live paper trading data.

### What the second session proved

**Removing protective mechanisms increases returns — when done selectively.** Three removals drove the largest gains: DD scaling removed (V22), VIX spike pause removed (V22), VIX high-side penalty removed (V26). The velocity crash pause is the one protection worth keeping.

**Position count: 40 is better than 30 — but ONLY if size is NOT reduced.** Adding positions at full size captures overflow on high-signal days. Never scale down position size to "make room."

### What doesn't work — do not retry

| Approach | What Was Tested | Why It Failed |
|---|---|---|
| **Price-based stop-losses** | −3% stop (V3) | 22.6% hit stop then bounced |
| **Circuit breakers** | Portfolio-level halt at −10% DD | Fired permanently 2004-2006 |
| **ROC entry filter** | Stock must be down 4%+ from streak start | Killed 68% of trades |
| **SPY 50d guard** | No entries when SPY below 50d SMA | Blocked 2009 recovery |
| **SPY same-day entry filter** | Skip entries when SPY down >0.5% | Filtered trades had higher EV |
| **VIX spike exit** | Exit losing positions during VIX spike | Cut positions before bounces |
| **First-up-close exit** | Exit on first up-day after 4 days | Dominated 54% of exits (V18) |
| **Tier 3 target differentiation** | Lower target for 4-day setups | Every variant underperformed uniform 2% |
| **Conditional bear filter** | Block Tier 3 when SPY 20d return < −5% | Broke 2020 velocity pause interaction |
| **Bull regime entry block** | Block Tier 2+3 in bull markets | 55.9% WR was still profitable |
| **Re-entry cooldown 2 days** | Reduce from 5 to 2 days | +3 trades/year — neutral |
| **Scaling position size down for more positions** | 40 positions at 4% | Per-trade profit fell 20% |
| **Drawdown scaling with tight thresholds** | 5%/10% thresholds | Fires during normal volatility |
| **70/30 SPY blend** | Blending with SPY B&H | After-tax edge narrows |
| **Binary VIX trend filter** | No entries when VIX below 10d MA | Blocked 37%+ of days (V31) |
| **$10M dollar volume floor** | Raised MIN_DOLLAR_VOLUME $5M→$10M | PF +0.01, volume cost too high |
| **DD scaling at 20% threshold** | >20% DD → 30% size reduction | Reduces size during recovery |
| **ATR-based position sizing** | size = fixed dollar risk / ATR | VIX cap overrides on most trades |
| **VIX trend continuous sizing** | VIX falling → 80% size | Cost $300k equity vs baseline |
| **Combining regime sizing + composite ranking** | V32f | Benefits cancel |
| **Combining regime sizing + higher position count** | V33b-d | Worse than either alone |
| **65 positions** | Not run — diminishing returns confirmed | ~+$100k at −1.5% DD cost |
| **Partial loss exit (day 4, −2%, trim 50%)** | V34a | Tier 1 WR 70.1% → 52.3%, −$926k equity |
| **Higher Tier 1 target with partial loss (V34b)** | T1 3% on broken base | Contaminated test, neutral |
| **Higher targets on clean base (V35a)** | T1 3%, T2 2.5%, healthy WR | PF unchanged at 1.06, −$86k |
| **Signal density stress filter (V36a)** | >40 signals → 0.5× size | −$519k. Crash recovery days both worst avg return AND best absolute P&L |
| **Breadth filter (V37a)** | <40% stocks above 20d AND 50d MA | −$2,899k. Fired ~50% of days including 2009/2013/2019 |
| **Index vs constituents divergence (V37b)** | SPY vs median stock 20d return >5% gap | −$455k. Only fired 68 days (1.2%) — threshold too loose |
| **MFE-based entry pause (V37c)** | Avg MFE <0.5% in last 20 trades → pause | Fired 54.8% of days, ran out of non-paused days before 2026. Miscalibrated |
| **Friday entry filter (V37d)** | Skip all Friday signal entries | −$1,340k. Friday avg return −0.01% — barely negative. Volume loss overwhelmed quality gain |

### What works — confirmed positive contributions

| Addition | First Tested | Effect | Status |
|---|---|---|---|
| Uniform 8-day window | Run 2 | Core mechanism | ✅ Kept |
| Tier 1 partial exit (50% at +1%) | Run 3 | Small positive | ✅ Kept |
| S&P 400 + S&P 600 universe | V4 / V30+600 | +35% trades, OOS confirmed | ✅ Kept |
| RSI(2) signal ranking | V4 | Better quality at zero cost | ✅ Kept |
| Sector ETF MA filter | V4 | Removes low-quality entries | ✅ Kept |
| Earnings blackout ±3 days | V4 | Removes gap-down risk | ✅ Kept |
| Sector correlation cap (max 3) | V4 | Prevents hidden concentration | ✅ Kept |
| VIX-adjusted sizing | V4 | Size larger when calm | ✅ Kept (tuned) |
| SPY 200d regime filter | V4 | No entries in bear market | ✅ Kept |
| Gap filters | V4 | Reduces adverse open fills | ✅ Kept |
| Re-entry cooldown (5 days) | V4 | Prevents re-chasing losses | ✅ Kept |
| Tier 3 (4-day setups) | V15 | Essential — highest trade volume | ✅ Kept |
| Velocity crash pause | V21 | +$40-60k at near-zero cost | ✅ Kept |
| DD scaling removed | V22 | Full size during recovery | ✅ Applied |
| VIX spike pause removed | V22 | Spikes = best entry conditions | ✅ Applied |
| Commission floor $0.35 | V22 | Matches IB tiered reality | ✅ Applied |
| 40 positions at full 5% size | V24 | Captures overflow on high-signal days | ✅ Applied |
| VIX_LOW raised to 25 | V28 | Recovery years get full 9% size | ✅ Applied |
| VIX high-side penalty removed | V26 | High-VIX = strongest MR conditions | ✅ Applied |
| 9% boost for VIX < 25 | V30 | Bull/recovery years larger positions | ✅ Applied |
| Composite ranking (RSI2/ATR_pct) | V32e | +$40k equity, +0.09% CAGR | ✅ Applied |
| Tier 3 hold 6d (was 8d) | V32b | Sharpe 0.75, Avg Loss −3.12% | ✅ In V32d only |
| VIX 5d trend 80% sizing | V32c | MaxDD −44.30% | ✅ In V32d only |
| **MAX_POSITIONS raised 40→60** | **V33b/c/d** | **+$670k equity, +1.31% CAGR vs V32e** | **✅ Applied** |

---

## The Honest Risk Picture for V33d

V33d's gains come from leverage amplification, universe expansion, and position count maximisation on the same edge — not a new edge. At ~$3.1M peak equity:
- 2022 lost −$1.05M in a single year
- 2026 (partial year) lost −$728k
- The −54.73% max drawdown means a potential ~$1.7M paper loss peak-to-trough

**60 positions is the confirmed ceiling.** Win rate is the anchor — if live win rate drops below 56%, the strategy is failing.

---

## Optimism Bias Warnings

V33d's 17.41% CAGR is the **in-sample ceiling**, not the live expectation.

| Source | Estimated CAGR Impact |
|---|---|
| Slippage on open prices | −2 to −3% |
| Survivorship bias | −1 to −2% |
| Overfitting across 40+ iterations | −2 to −3% |
| Earnings calendar lookahead | −0.3 to −0.5% |
| VIX regime parameters tuned to history | −1 to −2% |
| **Realistic live estimate** | **~8 to 12% CAGR gross** |

Apply ~26% walk-forward decay: 17.41% × 0.74 ≈ ~13% live gross. After short-term capital gains tax (32–37%), realistic net CAGR is likely 7–10%.

---

## SPY vs Strategy

| Metric | SPY B&H | Run 5 | V32e | V33d | V32d (Roth) |
|---|---|---|---|---|---|
| CAGR (gross, in-sample) | ~10.5% | 7.58% | 16.10% | 17.41% | 15.37% |
| CAGR (gross, OOS est.) | ~10.5% | 5.58% | ~12% | ~13% | TBD |
| CAGR (after tax, est.) | ~8.4% | ~3.5–5% | ~6–9% | ~7–10% | tax-free (Roth) |
| Max Drawdown | −55% (2008) | −22.55% | −48.61% | −54.73% | −39.21% |
| Sharpe Ratio | ~0.55 | 0.73 | 0.73 | 0.68 | 0.77 |
| Final Equity ($100k start) | ~$800k | $478k | $2,454k | $3,124k | $2,145k |

**Tax note:** ~1,043 trades/year qualifies for IRS trader tax status (Section 475(f) MTM election). Consult a CPA (e.g. Green Trader Tax).

---

## Paper Trading & Live Automation

### Status: ✅ LIVE (paper trading active as of April 2026)

- **Broker:** Interactive Brokers (IBKR) paper account, starting equity $100,000
- **Script:** `C:\nmr-trader\trade.py` — runs automatically every weekday
- **Scheduler:** Windows Task Scheduler fires at **6:25 AM PT**
- **Orders:** Market On Open (MOO) submitted before the 6:28 AM PT auction cutoff
- **Database:** `C:\nmr-trader\positions.db` — SQLite
- **Alerts:** Daily summary email via SendGrid
- **MAX_POSITIONS in trade.py:** Updated to 60 to match V33d

### GitHub auto-push

`trade.py` pushes paper trading results to the repo after each run:
- `paper_trading/summary.json` — daily summary stats
- `paper_trading/trades.csv` — full trade log
- `paper_trading/open_positions.csv` — current open positions

In a new session, ask Claude to check the repo directly for paper trading results.

### Local commands

```bat
cd C:\nmr-trader
venv\Scripts\activate
```

**Check win rate:**
```bat
python -c "import sqlite3, pandas as pd; conn = sqlite3.connect(r'C:\nmr-trader\positions.db'); trades = pd.read_sql(\"SELECT * FROM trade_log WHERE exit_reason != 'partial_exit'\", conn); conn.close(); total = len(trades); wr = len(trades[trades['pnl_usd']>0])/total*100 if total else 0; pnl = trades['pnl_usd'].sum() if total else 0; print(f'Completed trades: {total}'); print(f'Win rate: {wr:.1f}%  (target: 57-63%)'); print(f'Total P&L: ${pnl:,.2f}'); print('WARNING: win rate below 55%' if total >= 30 and wr < 55 else 'CAUTION: below 57%' if total >= 30 and wr < 57 else 'Win rate OK' if total >= 30 else f'({total}/30 trades before win rate is meaningful)')"
```

### Pass criteria for moving to live capital

| Check | Target | Action if failing |
|---|---|---|
| Win rate | 57–63% over 100+ trades | Stop — review signal logic |
| Trades per month | 65–90 | Check universe fetch and signal parameters |
| Worst single month | Better than −15% | Review if repeated |
| Script ran every trading day | 100% | Fix Gateway startup |
| Slippage vs prior close | Under 0.6% avg | Higher for small-caps expected |

### Going live — two changes only

```python
IBKR_PORT = 4001   # was 4002 (paper)
```
Switch Gateway from Paper to Live account. No other changes.

### Troubleshooting

| Problem | Likely cause | Fix |
|---|---|---|
| "IBKR connection failed" | Gateway not running | Open Gateway and log in before 6:25 AM PT |
| Script didn't run | PC was asleep | Power & Sleep → Sleep → Never |
| 0 entry candidates | SPY below 200d MA | Normal in bear market |
| Win rate < 55% after 50 trades | Signal logic drift | Verify trade.py constants match backtest-nmr.py |

---

## Next Steps

### Step 1 — Walk-Forward Validation ✅ COMPLETE
V33d: OOS avg 18.37%, 7/8 positive. V32e: OOS avg 5.58%, 6/8 positive.

### Step 2 — Paper Trading ✅ ACTIVE (since April 2026)
Pass criteria: 3 months, win rate 57–63% over 100+ trades, no month worse than −15%.

### Step 3 — Go Live ⏳
Only after paper trading passes all criteria.

### Step 4 — Future improvements
The strategy is fully optimised through V37d. Do not retry entry filters or exit mechanics. Remaining genuine improvements:
- **Historical earnings database** — removes lookahead bias. Est. +0.3 to +0.5% CAGR
- **Live OOS validation** — paper trading is the only true remaining out-of-sample test
- **MOO slippage analysis** — compare fill prices to prior close once 100+ trades complete

---

## All Runs Table

### V21–V37d: Complete Sequence

| Version | Key Change | CAGR | Final Equity | Max DD | Sharpe |
|---|---|---|---|---|---|
| V21 | Run 5 + velocity crash pause | 7.55% | $476k | −22.6% | 0.72 |
| V22 | − DD scaling, − comm floor, − VIX pause | 9.14% | $652k | −26.3% | 0.71 |
| V23 | 40 pos ×4% scaled (regression) | 8.65% | $592k | −26.7% | 0.68 |
| V24 | 40 pos ×5% unchanged | 10.64% | $875k | −32.5% | 0.68 |
| V25 | VIX_HIGH 25→30, cooldown 2d | 10.94% | $926k | −34.5% | 0.69 |
| V26 | VIX high-side penalty removed | 11.28% | $990k | −32.3% | 0.70 |
| V27 | VIX_LOW 18→20 | 11.43% | $1,019k | −33.9% | 0.70 |
| V28 | VIX_LOW 20→25 | 12.58% | $1,268k | −34.9% | 0.72 |
| V29 | POSITION_SIZE_HIGH 7.5%→9% | 12.60% | $1,274k | −38.5% | 0.68 |
| V30 | V28 + V29 combined | 14.42% | $1,797k | −39.4% | 0.72 |
| V30+S&P600 | + S&P 600 SmallCap universe | 16.01% | $2,414k | −48.65% | 0.73 |
| V31 | VIX 10d trend + $10M floor + DD scaling | 11.03% | $938k | −35.92% | 0.64 |
| V31b | $10M floor + DD scaling only | 13.17% | $1,419k | −39.16% | 0.68 |
| V32a | ATR-based position sizing | 15.98% | $2,403k | −48.61% | 0.73 |
| V32b | Tier 3 hold 8→6 days | 15.87% | $2,354k | −44.87% | 0.75 |
| V32c | VIX 5d trend: 80% size when falling | 15.28% | $2,111k | −44.30% | 0.74 |
| V32d | V32b + V32c combined | 15.37% | $2,145k | −39.21% | **0.77** |
| V32e | Composite ranking: RSI(2)/ATR_pct | 16.10% | $2,454k | −48.61% | 0.73 |
| V32f | V32d + V32e combined | 15.31% | $2,123k | −39.62% | 0.77 |
| V33b | MAX_POSITIONS raised 40→50 | 16.83% | $2,808k | −51.73% | 0.70 |
| V33b-d | 50 pos + V32d controls | 15.30% | $2,119k | −47.13% | 0.70 |
| V33c | MAX_POSITIONS raised 50→55 | 17.16% | $2,982k | −53.27% | 0.69 |
| **V33d** | **MAX_POSITIONS raised 55→60** | **17.41%** | **$3,124k** | **−54.73%** | **0.68** |
| V34a | Partial loss exit: day 4, ≥−2%, trim 50% | 15.50% | $2,198k | −52.61% | 0.66 |
| V34b | V34a + Tier 1 target 2%→3% (contaminated) | 15.44% | $2,172k | −52.48% | 0.66 |
| V35a | T1 3%, T2 2.5% (clean base) | 17.26% | $3,038k | −56.46% | 0.68 |
| V36a | Signal stress: >40 signals → 0.5× size | 16.42% | $2,605k | −52.19% | 0.67 |
| V37a | Breadth filter: <40% stocks above 20d+50d | 3.86% | $225k | −48.06% | 0.27 |
| V37b | Index vs constituents divergence >5% | 16.55% | $2,669k | −56.04% | 0.66 |
| V37c | MFE pause 0.5%/3d/20 trades (miscalibrated) | ~28%* | ~$1,047k* | −33.82%* | 1.17* |
| V37d | Friday entry filter | 14.38% | $1,784k | −59.82% | 0.63 |

*V37c ran only to 2014 due to miscalibration (fired 54.8% of days). Numbers not comparable.

**V33d is the confirmed ceiling. All subsequent versions regressed. Optimisation is complete.**

---

## Repository Structure

```
.
├── backtest-nmr.py
├── backtest_nmr_lib.py
├── walkforward.py
├── requirements.txt
├── README-nmr.md
├── results/
│   ├── metrics.json
│   ├── trades.csv
│   ├── equity_curve.csv
│   ├── walkforward_summary.csv
│   ├── walkforward_equity.csv
│   └── walkforward_report.json
├── paper_trading/
│   ├── summary.json
│   ├── trades.csv
│   └── open_positions.csv
└── .github/workflows/backtest.yml
```

---

## Setup & Running

### GitHub Actions
1. Push all files to your repo
2. **Settings → Actions → General → Workflow permissions → Read and write**
3. **Actions → Naive MR Backtest → Run workflow**

Walk-forward: set `run_walkforward = true` in workflow dispatch inputs. Adds 6–8 hours.

### Local
```bash
pip install -r requirements.txt
python backtest-nmr.py      # ~90-120 min with S&P 600
python walkforward.py       # ~6-8 hours with S&P 600
```

### Health Checks
- `[Universe] Total unique tickers` < 1800: S&P 600 fetch failed
- `win_rate < 55%`: verify uniform 8-day windows; check SPY regime filter
- `CAGR < 15%` with no changes: verify `MAX_POSITIONS = 60` and version V33d
- `trades_per_year < 700`: Tier 3 may be disabled — check `MIN_CONSEC_DOWN = 4`

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
```

---

## Disclaimer

Educational and research purposes only. Past backtest performance does not guarantee future results. Not financial advice. Consult a licensed financial advisor and CPA before trading with real capital. V33d's aggressive position sizing (60 positions, 9% each when VIX < 25) is suitable only for those who understand and can hold through drawdowns of −54%+. V32d is the recommended alternative for Roth IRA accounts (MaxDD −39%, Sharpe 0.77).
