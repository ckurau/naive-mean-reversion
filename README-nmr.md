# Naive Mean Reversion (MR) Backtest

A survivorship-bias-free backtest of a **Naive Mean Reversion** strategy across all historical S&P 500 + S&P 400 MidCap + S&P 600 SmallCap constituents, automated via GitHub Actions.

---

## Current Version: V35 (Best Confirmed Result -- taxable account)

The current script (`backtest-nmr.py`) is **V35 -- V34 base + C6 tiered sizing multiplier raised 1.20x -> 1.30x**.

**IMPORTANT FOR NEW SESSIONS:** Push `backtest-nmr.py` and `backtest_nmr_lib.py` to GitHub and run the workflow.

**ARCHITECTURE (V33d onwards -- unified codebase):** `backtest-nmr.py` is a thin wrapper that imports all logic from `backtest_nmr_lib.py`. To change any parameter or logic, edit `backtest_nmr_lib.py` only. `walkforward.py` also imports from `backtest_nmr_lib.py`.

**Session objective: maximize total equity (taxable account).** V35 is recommended for a taxable account. V32d is recommended for a Roth IRA.

### Best Confirmed Results: V35

| Metric | Value |
| --- | --- |
| CAGR | 18.81% |
| Win Rate | 60.15% |
| Avg Win | 3.09% |
| Avg Loss | -3.61% |
| Profit Factor | 1.06 |
| Max Drawdown | -56.22% |
| Sharpe Ratio | 0.71 |
| Trades / Year | 1,025 |
| Final Equity (from $100k) | $4,028,420 |
| Period | 2004-2026 (~21 years) |

### Best Risk-Adjusted: V32d (recommended for Roth IRA)

| Metric | Value |
| --- | --- |
| CAGR | 15.37% |
| Final Equity | $2,144,611 |
| Profit Factor | 1.09 |
| Max Drawdown | -39.21% |
| Sharpe Ratio | 0.77 |
| Avg Loss | -3.12% |

### Previous Bests -- for reference

| Version | CAGR | Final Equity | MaxDD | Sharpe |
| --- | --- | --- | --- | --- |
| **V35 (current)** | **18.81%** | **$4,028k** | **-56.22%** | **0.71** |
| V34 | 18.50% | $3,806k | -54.50% | 0.71 |
| V33d | 17.41% | $3,124k | -54.73% | 0.68 |
| V33c (55 pos) | 17.16% | $2,982k | -53.27% | 0.69 |
| V33b (50 pos) | 16.83% | $2,808k | -51.73% | 0.70 |
| V32e (40 pos) | 16.10% | $2,454k | -48.61% | 0.73 |
| V32d (risk-adj) | 15.37% | $2,145k | -39.21% | 0.77 |
| V30+S&P600 | 16.01% | $2,414k | -48.65% | 0.73 |

### V35 Changes vs V34

**C6 -- Tiered sizing multiplier raised (1.20x -> 1.30x):** Top 20% of signals by composite score now receive a 1.30x position size multiplier (was 1.20x in V34). Hard cap of 12% per position unchanged. Zero change to trade count or win rate. Tested as V40c: +$222k equity, +0.31% CAGR vs V34. Sharpe unchanged at 0.71. MaxDD worsens marginally by 1.72pp -- consistent with the original 1.2x addition pattern (small CAGR gain, small DD cost).

**V35 gain vs V34: +$222k final equity, +0.31% CAGR.**

### Walk-Forward Validation: V34 Confirmed PASS (V35 not separately walk-forwarded -- same signals, sizing change only)

| Window | OOS Period | CAGR | WinRate | PF | MaxDD | Sharpe | Trades | IS/OOS | Regime | Verdict |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| W1 | 2009-2010 | 24.9% | 61.3% | 1.31 | -14.6% | 1.17 | 1,402 | 0.70x | Recovery | STRONG |
| W2 | 2011-2012 | 25.9% | 63.9% | 1.23 | -33.5% | 0.75 | 2,003 | 1.32x | Chop/Dip | STRONG |
| W3 | 2013-2014 | 39.6% | 59.3% | 1.23 | -32.1% | 1.31 | 2,575 | 1.57x | Bull | BEST |
| W4 | 2015-2016 | 15.0% | 58.4% | 1.17 | -18.1% | 0.83 | 1,801 | 0.40x | Chop | WEAK |
| W5 | 2017-2018 | 9.3% | 57.0% | 1.05 | -29.5% | 0.39 | 2,645 | 0.32x | Low-Vol Bull | WEAK |
| W6 | 2019-2020 | 47.5% | 62.7% | 1.37 | -36.3% | 1.16 | 2,074 | 3.73x | Bull+Crash+Recover | BEST |
| W7 | 2021-2022 | -11.7% | 54.6% | 0.93 | -46.3% | -0.34 | 1,887 | -0.44x | Bear Grind | FAIL |
| W8 | 2023-2025 | 5.1% | 60.0% | 1.03 | -54.6% | 0.35 | 4,134 | 0.34x | AI Bull + Tariff Bear | WEAK |

**OOS Positive CAGR windows: 7/8 -- PASS**
**OOS Avg CAGR: 19.45% | OOS Median CAGR: 19.99%**

### Walk-Forward Root Cause Analysis (April 2026)

Strong windows (W1, W2, W3, W6) share two traits: crash-recovery events present, and IS/OOS ratio >= 1.0 in three cases -- the opposite of overfit behavior. The strategy found untrained environments where it worked even better.

Weak/failing windows cluster into three regime types:

- **W7 (2021-2022): Slow grinding bear.** 2022 was a 12-month grind with repeated false bottoms. Win rate fell to 54.6% (below sustainable threshold). SPY oscillated around the 200d MA, triggering entries that caught falling knives with no snap-back within 8 days.
- **W5 (2017-2018): Low-volatility drought.** Historically low VIX meant 4+ consecutive down days barely fired. When they did, the 9% position size in a low-vol environment created poor risk/reward (PF 1.05 -- barely covering commissions).
- **W8 (2023-2025): Regime split.** Win rate held at 60% (healthy) but profit factor collapsed to 1.03. Average wins shrank relative to losses -- not a signal quality problem but a market structure problem: winners reverting partially then re-trending before hitting the 2% target.

**Structural conclusion:** The edge is regime-conditional, not overfit. 3 of 4 regime types work. The only structural failure is slow-grinding bear markets where reversions don't complete within 8 days.

---

## V35 Strategy Rules (current code)

| Rule | Detail |
| --- | --- |
| **Universe** | S&P 500 + S&P 400 MidCap + S&P 600 SmallCap (current + historical, avoids survivorship bias) |
| **Trend filter** | Stock must be above its 200-day SMA |
| **Entry signal** | 4+ consecutive down days AND RSI(2) < 20 AND ATR > 1% AND volume > 20-day avg AND dollar volume > $5M/day |
| **Entry execution** | Buy at open of next day |
| **Gap filters** | Skip if next open gaps down > 1.0% [V34] OR gaps up > 2% |
| **Exit -- all tiers** | 2% profit target, 8-day time stop (uniform -- the key mechanism) |
| **Tier 1 partial** | 6+ down days: 50% at 1%, remainder at 2% |
| **Tier 2** | 5 down days: 2% target, 8-day window, no partial |
| **Tier 3** | 4 down days: 2% target, 8-day window, no partial |
| **Min hold** | 2 calendar days before profit exit allowed |
| **Max positions** | 60 simultaneous holdings |
| **Position size** | VIX < 25 -> 9%, VIX >= 25 -> 5% base |
| **Tiered sizing** | Top 20% of signals by composite score get 1.3x size, hard cap 12% [V35] |
| **Signal ranking** | Composite score: RSI(2) / ATR\_pct [V32e] |
| **Sector filter** | Skip entry if stock's sector ETF is below its 20-day MA |
| **Correlation cap** | Max 3 open positions in same sector |
| **Earnings blackout** | Skip entries within +/-3 days of earnings announcement |
| **SPY regime** | No new entries when SPY is below its 200-day MA |
| **Re-entry cooldown** | No re-entry in a stock for 5 days after a time-stop exit |
| **Velocity crash pause** | SPY 5-day return < -12% -> pause all entries for 5 days |
| **Earnings month cap** | Position size capped at 2.4% in Jan/Apr/Jul/Oct (earnings months) |
| **Commission** | $0.005/share or $0.35 minimum per trade |

---

## The Honest Risk Picture for V35

V35's gains come from the same structural edge as V34 -- leverage amplification, universe expansion, and position count maximisation -- plus one additional parametric improvement to the top-signal sizing multiplier. At ~$4.0M peak equity:

* The -56.22% max drawdown means a potential ~$2.25M paper loss peak-to-trough
* 2022 lost ~$1.2M in a single year at that equity level
* 2025 and 2026 YTD remain the current live drawdown environment
* The 1.30x sizing multiplier concentrates slightly more capital on top-ranked trades, modestly amplifying both wins and losses on those positions

**60 positions is the confirmed ceiling.** Win rate is the anchor -- if live win rate drops below 56%, the strategy is failing.

---

## Drawdown Research: Confirmed Structural -- Do Not Retry

After exhaustive testing across V35-V40 sessions, the following conclusion is definitive:

**The max drawdown cannot be reduced without sacrificing CAGR.**

Every mechanism tested either blocks crash-recovery entries (costing more in good years than it saves in bad years) or adds a losing overlay. This is structural, not a calibration problem.

### What the streak analysis proved

From V34 trade data (18,775 trades after excluding partials):

| Streak | Next Trade WR | vs Baseline 58.6% |
| --- | --- | --- |
| After 3 consecutive losses | 26.6% (n=3,423) | -32pp |
| After 4 consecutive losses | 23.1% (n=2,511) | -35.5pp |
| After 5 consecutive losses | 20.9% (n=1,930) | -37.7pp |
| After 6 consecutive losses | 18.9% (n=1,526) | -39.7pp |
| After 10 consecutive losses | 13.9% (n=718) | -44.7pp |

Loss streak trades (45.8% of all trades) account for -$13.98M total P&L. Non-streak trades (54.2%) account for +$14.65M. The edge is entirely in non-streak periods.

**Why reducing streak exposure fails:** After 3+ consecutive losses, the strategy is in a market regime where entries are catching falling knives. BUT these same clustered-loss windows are immediately followed by the largest recovery periods. Every filter that reduces streak exposure also reduces crash-recovery entries. 2019, 2020, and 2021 -- the three best years -- each began with a loss cluster that triggered streak filters, then recovered violently. Blocking entries during that window costs more than the streak losses saved.

### SPY bear regime analysis

SPY RSI(2) distribution during bear regime (1,079 days, 19.3% of all trading days):

* Mean RSI(2): 30.0 | Median: 19.6 | 90th pct: 78.7
* 1 up day AND RSI(2) > 65: 88 signals over 21 years (~4/year)
* RSI(2) resets so fast that 2+ consecutive up days always produce NaN -- the signal must fire on day 1 only

---

## What Doesn't Work -- Complete Do-Not-Retry Table

| Approach | What Was Tested | Why It Failed |
| --- | --- | --- |
| **Price-based stop-losses** | -3% stop (V3) | 22.6% hit stop then bounced |
| **Circuit breakers** | Portfolio-level halt at -10% DD | Fired permanently 2004-2006 |
| **ROC entry filter** | Stock must be down 4%+ from streak start | Killed 68% of trades |
| **SPY 50d guard** | No entries when SPY below 50d SMA | Blocked 2009 recovery |
| **SPY same-day entry filter** | Skip entries when SPY down >0.5% | Filtered trades had higher EV |
| **VIX spike exit** | Exit losing positions during VIX spike | Cut positions before bounces |
| **First-up-close exit** | Exit on first up-day after 4 days | Dominated 54% of exits (V18) |
| **Tier 3 target differentiation** | Lower target for 4-day setups | Every variant underperformed uniform 2% |
| **Conditional bear filter** | Block Tier 3 when SPY 20d return < -5% | Broke 2020 velocity pause interaction |
| **Bull regime entry block** | Block Tier 2+3 in bull markets | 55.9% WR was still profitable |
| **Re-entry cooldown 2 days** | Reduce from 5 to 2 days | +3 trades/year -- neutral |
| **Scaling position size down for more positions** | 40 positions at 4% | Per-trade profit fell 20% |
| **Drawdown scaling with tight thresholds** | 5%/10% thresholds | Fires during normal volatility |
| **70/30 SPY blend** | Blending with SPY B&H | After-tax edge narrows |
| **Binary VIX trend filter** | No entries when VIX below 10d MA | Blocked 37%+ of days (V31) |
| **$10M dollar volume floor** | Raised MIN\_DOLLAR\_VOLUME $5M->$10M | PF +0.01, volume cost too high |
| **DD scaling at 20% threshold** | >20% DD -> 30% size reduction | Reduces size during recovery |
| **ATR-based position sizing** | size = fixed dollar risk / ATR | VIX cap overrides on most trades |
| **VIX trend continuous sizing** | VIX falling -> 80% size | Cost $300k equity vs baseline |
| **Combining regime sizing + composite ranking** | V32f | Benefits cancel |
| **Combining regime sizing + higher position count** | V33b-d | Worse than either alone |
| **65 positions** | Not run -- diminishing returns confirmed | ~+$100k at -1.5% DD cost |
| **Partial loss exit (day 4, -2%, trim 50%)** | V34a | Tier 1 WR 70.1% -> 52.3%, -$926k equity |
| **Higher Tier 1 target with partial loss (V34b)** | T1 3% on broken base | Contaminated test, neutral |
| **Higher targets on clean base (V35a)** | T1 3%, T2 2.5%, healthy WR | PF unchanged at 1.06, -$86k |
| **Signal density stress filter (V36a-old)** | >40 signals -> 0.5x size | -$519k. Crash recovery days blocked |
| **Breadth filter (V37a)** | <40% stocks above 20d AND 50d MA | -$2,899k. Fired ~50% of days |
| **Index vs constituents divergence (V37b)** | SPY vs median stock 20d return >5% gap | -$455k. Only fired 68 days (1.2%) |
| **MFE-based entry pause (V37c)** | Avg MFE <0.5% in last 20 trades -> pause | Fired 54.8% of days, miscalibrated |
| **Friday entry filter (V37d)** | Skip all Friday signal entries | -$1,340k. Volume loss overwhelmed quality gain |
| **IBS < 0.35 filter (V38a-C1)** | (Close-Low)/(High-Low) < 0.35 | -$2,150k. Killed crash-recovery entries |
| **EMA 20/50 downtrend block (V38a-C2)** | Skip entries when Close < EMA20 < EMA50 | -$1,470k. Blocked crash-recovery AND worsened MaxDD |
| **Double time-stop cooldown (V38a-C4)** | 15d cooldown if stock time-stops twice in 30d | Neutral -- fires too rarely |
| **Streak filter Option C (V35)** | 3 losses=50% size, 5 losses=pause 3d, reset on win | MaxDD -54.5%->-46.2% (+8pp) but CAGR -4.72pp, equity -$2.2M. Structural -- streak trades immediately precede crash-recovery entries. |
| **Rolling WR adaptive sizing (V36 Test 1)** | Last 20 trades WR < 55% -> halve position size | MaxDD -56.22%->-49.28% (+7pp) but CAGR -3.71pp, equity -$2.0M. Same structural failure as streak filter -- trigger fires during crash-recovery windows. Reduced-size trades had HIGHER WR (62%) than full-size trades (59%). |
| **RSI tightening in low-VIX (V36 Test 2)** | RSI(2) < 15 when VIX < 15 | Filtered 1 trade across 21 years. VIX rarely below 15 post-2017. Dead end. |
| **Per-stock EWMA vol filter (V36a)** | Skip entries when stock EWMA vol in top 20% of own 252d history | CAGR -4.74pp, MaxDD worse (-0.42pp). Same failure as streak filter. |
| **Inverse ETF v1 -- direct signal (V36c-v1)** | Buy SH/PSQ/RWM when inverse ETF has 4+ consecutive down days + RSI<20 | 57 signals in 21 years -- too rare (~2.7/year). +$29k total (not meaningful). |
| **Bond allocation in bear regime (V36e)** | Buy IEF when 2+ consecutive down days + RSI<40, during SPY below 200d MA | Alt P&L -$2,113 across 146 trades. 2022 bonds fell with equities. |
| **Inverse ETF v2 -- underlying overbought (V36cv2)** | Buy SH when SPY has 1 up day + RSI(2)>65 in bear regime | SH P&L -$10,075 (45.8% WR). Structural daily rebalancing decay. |
| **Volume peak on final down day (V37)** | Entry only when today's volume is highest day in the consecutive down streak | Blocked 50% of signals. WR unchanged at 59.9%. CAGR -6.33pp. |
| **Gap filter further tightening -- -0.75% (V40a)** | GAP\_DOWN\_MAX = -0.0075 | CAGR -2.59pp, equity -$1,433k, MaxDD worse -3.72pp. Gap ceiling confirmed at -1.0%. |
| **Gap filter further tightening -- -0.50% (V40b)** | GAP\_DOWN\_MAX = -0.005 | CAGR -4.53pp, equity -$2,154k, MaxDD worse -4.30pp. Strongly negative. |
| **Tier multiplier 1.5x or 2.0x** | Not tested | Trend from 1.2x->1.3x shows diminishing CAGR gain with growing DD cost. Do not test. |

### Final structural conclusion on drawdown

The strategy must be fully exposed during panic to capture recovery. The drawdown is the price of the edge. Every mechanism that reduces this exposure costs more in recovery years than it saves in bad years. The max drawdown is confirmed structural and not improvable within the current strategy design without meaningful CAGR sacrifice.

**For investors who cannot tolerate -56% drawdown: use V32d (MaxDD -39%, Sharpe 0.77, CAGR 15.37%).**

---

## What Works -- Confirmed Positive Contributions

| Addition | First Tested | Effect | Status |
| --- | --- | --- | --- |
| Uniform 8-day window | Run 2 | Core mechanism | Kept |
| Tier 1 partial exit (50% at +1%) | Run 3 | Small positive | Kept |
| S&P 400 + S&P 600 universe | V4 / V30+600 | +35% trades, OOS confirmed | Kept |
| RSI(2) signal ranking | V4 | Better quality at zero cost | Kept |
| Sector ETF MA filter | V4 | Removes low-quality entries | Kept |
| Earnings blackout +/-3 days | V4 | Removes gap-down risk | Kept |
| Sector correlation cap (max 3) | V4 | Prevents hidden concentration | Kept |
| VIX-adjusted sizing | V4 | Size larger when calm | Kept (tuned) |
| SPY 200d regime filter | V4 | No entries in bear market | Kept |
| Gap filters | V4 | Reduces adverse open fills | Kept |
| Re-entry cooldown (5 days) | V4 | Prevents re-chasing losses | Kept |
| Tier 3 (4-day setups) | V15 | Essential -- highest trade volume | Kept |
| Velocity crash pause | V21 | +$40-60k at near-zero cost | Kept |
| DD scaling removed | V22 | Full size during recovery | Applied |
| VIX spike pause removed | V22 | Spikes = best entry conditions | Applied |
| Commission floor $0.35 | V22 | Matches IB tiered reality | Applied |
| 40 positions at full 5% size | V24 | Captures overflow on high-signal days | Applied |
| VIX\_LOW raised to 25 | V28 | Recovery years get full 9% size | Applied |
| VIX high-side penalty removed | V26 | High-VIX = strongest MR conditions | Applied |
| 9% boost for VIX < 25 | V30 | Bull/recovery years larger positions | Applied |
| Composite ranking (RSI2/ATR\_pct) | V32e | +$40k equity, +0.09% CAGR | Applied |
| MAX\_POSITIONS raised 40->60 | V33b/c/d | +$670k equity, +1.31% CAGR vs V32e | Applied |
| Gap filter tightened -1.5%->-1.0% | V38a-C3 / V34 | +$413k equity, +0.68% CAGR | Applied |
| Tiered sizing: top 20% get 1.2x | V38a-C5 / V34 | +$337k equity, +0.51% CAGR | Applied |
| **Tiered sizing multiplier 1.2x->1.3x** | **V40c / V35** | **+$222k equity, +0.31% CAGR** | **Applied** |

---

## Optimism Bias Warnings

V35's 18.81% CAGR is the **in-sample ceiling**, not the live expectation.

| Source | Estimated CAGR Impact |
| --- | --- |
| Slippage on open prices | -2 to -3% |
| Survivorship bias | -1 to -2% |
| Overfitting across 50+ iterations | -2 to -3% |
| Earnings calendar lookahead | -0.3 to -0.5% |
| VIX regime parameters tuned to history | -1 to -2% |
| **Realistic live estimate** | **~8 to 12% CAGR gross** |

Apply ~26% walk-forward decay: 18.81% x 0.74 = ~13.9% live gross. After short-term capital gains tax (32-37%), realistic net CAGR is likely 8-10%.

---

## SPY vs Strategy

| Metric | SPY B&H | V35 | V32d (Roth) |
| --- | --- | --- | --- |
| CAGR (gross, in-sample) | ~10.5% | 18.81% | 15.37% |
| CAGR (gross, OOS est.) | ~10.5% | ~14% | TBD |
| CAGR (after tax, est.) | ~8.4% | ~8-10% | tax-free (Roth) |
| Max Drawdown | -55% (2008) | -56.22% | -39.21% |
| Sharpe Ratio | ~0.55 | 0.71 | 0.77 |
| Final Equity ($100k start) | ~$800k | $4,028k | $2,145k |

**Tax note:** ~1,025 trades/year qualifies for IRS trader tax status (Section 475(f) MTM election). Consult a CPA (e.g. Green Trader Tax).

---

## Paper Trading & Live Automation

### Status: LIVE (paper trading active as of April 2026)

* **Broker:** Interactive Brokers (IBKR) paper account, starting equity $100,000
* **Scripts:** `scan_evening.py` (6:00 PM PT) + `trade_morning.py` (6:15 AM PT)
* **Scheduler:** Windows Task Scheduler -- two tasks (see below)
* **Orders:** Limit On Open (LOO) entries submitted evening before; MOO exits submitted morning of
* **Database:** `C:\nmr-trader\positions.db` -- SQLite (4 tables)
* **Alerts:** Daily summary email via SendGrid (optional)
* **MAX\_POSITIONS:** 60 (matches V35)

### Two-Script Architecture (April 2026 redesign)

The original single `trade.py` (MOO entries at 6:25 AM) was replaced with a two-script system that more accurately implements the backtest's gap filter logic.

**Why LOO instead of MOO for entries:**
The backtest applies `GAP_DOWN_MAX = -1%` and `GAP_UP_MAX = +2%` filters using the next-day open price. MOO orders accept any open price regardless of overnight gap -- diverging from what the backtest actually tested. LOO (Limit On Open) orders with a limit of `prior_close * 1.005` implement the gap-up filter in live execution: stocks that bounce hard overnight won't fill, matching backtest behavior. No backtesting of this change is required -- it only affects live execution fidelity, not backtest parameters.

**Exit orders remain MOO:** Selling at market open on exit is standard -- you're already in the position and accepting the open price is correct. No gap filter applies to exits.

| Script | Trigger | Does |
| --- | --- | --- |
| `scan_evening.py` | 6:00 PM PT daily | Scans universe, applies all filters, submits LOO buy orders, saves pending entries to DB |
| `trade_morning.py` | 6:15 AM PT daily | Submits MOO exit orders, holds until 6:35 AM, confirms fills on LOO entries and exits |

### Task Scheduler Setup

**Evening scan task:**
- Program: `C:\nmr-trader\venv\Scripts\python.exe`
- Argument: `C:\nmr-trader\scan_evening.py`
- Start in: `C:\nmr-trader`
- Trigger: Daily, 6:00 PM PT

**Morning run task:**
- Program: `C:\nmr-trader\venv\Scripts\python.exe`
- Argument: `C:\nmr-trader\trade_morning.py`
- Start in: `C:\nmr-trader`
- Trigger: Daily, 6:15 AM PT

### Database Tables

| Table | Purpose |
| --- | --- |
| `open_positions` | Current live positions with entry price, shares, tier, exit parameters |
| `pending_entries` | LOO orders submitted by evening scan, awaiting morning fill confirmation |
| `trade_log` | Completed trades with P&L |
| `cooldown` | Re-entry cooldown tracker per ticker |

Tables are created automatically on first run via `init_db()`. No manual setup required.

### CRITICAL: Scripts run locally, not from GitHub

Scripts run from `C:\nmr-trader\` on your local PC. They do NOT pull updated files from GitHub automatically. Backtest files in GitHub are completely separate.

### LOO Limit Price

Entry limit = `prior_close * 1.005` (prior close + 0.5%). Orders that gap up more than 0.5% overnight will not fill. This is intentional -- it matches the backtest's gap filter behavior. Not-filled orders are logged as `NOT FILLED (gapped up)` in the morning summary and are expected behavior, not errors.

### Parameter Sync Checklist (V35)

| Parameter | Value | File |
| --- | --- | --- |
| GAP\_DOWN\_MAX | -0.010 | scan\_evening.py |
| TOP\_SIGNAL\_MULTIPLIER | 1.30 | scan\_evening.py |
| LOO\_LIMIT\_BUFFER | 0.005 | scan\_evening.py |
| MAX\_POSITIONS | 60 | both scripts |
| Price history window | 400 days | both scripts |
| IBKR\_PORT (paper) | 4002 | both scripts |
| IBKR\_PORT (live) | 4001 | both scripts |

### Universe Verification

```
cd C:\nmr-trader
venv\Scripts\activate
python -c "import io, requests, pandas as pd; tickers=set(); [tickers.update(pd.read_html(io.StringIO(requests.get(u,headers={'User-Agent':'Mozilla/5.0'},timeout=30).text))[0]['Symbol'].tolist()) for u in ['https://en.wikipedia.org/wiki/List_of_S%26P_500_companies']]; print(f'S&P500 tickers: {len(tickers)}')"
```

Expected: 500-503 tickers from S&P 500 alone; full universe (500+400+600) should be 1,400-1,600.

### Pre-Flight Check

Run before each new deployment or after any changes:

```
cd C:\nmr-trader
venv\Scripts\activate
python preflight.py
```

Checks: file existence, syntax, DB tables, IBKR Gateway connection, portfolio value readable, market data downloads, signal scan on 20-ticker sample.

### Paper Trading Win Rate Check

```
cd C:\nmr-trader
venv\Scripts\activate
python -c "
import sqlite3, pandas as pd
conn = sqlite3.connect(r'C:\nmr-trader\positions.db')
trades = pd.read_sql(\"SELECT * FROM trade_log WHERE exit_reason != 'partial_exit'\", conn)
conn.close()
total = len(trades)
wr = len(trades[trades['pnl_usd']>0])/total*100 if total else 0
pnl = trades['pnl_usd'].sum() if total else 0
print(f'Completed trades: {total}')
print(f'Win rate: {wr:.1f}% (target: 57-63%)')
print(f'Total P&L: \${pnl:,.2f}')
if total >= 30:
    if wr < 55: print('WARNING: win rate below 55% -- review signal logic')
    elif wr < 57: print('CAUTION: below 57% target')
    else: print('Win rate OK')
else:
    print(f'({total}/30 trades before win rate is meaningful)')
"
```

### Pass Criteria for Moving to Live Capital

| Check | Target | Action if failing |
| --- | --- | --- |
| Win rate | 57-63% over 100+ trades | Stop -- review signal logic |
| Trades per month | 65-90 | Check universe fetch and signal parameters |
| Worst single month | Better than -15% | Review if repeated |
| Script ran every trading day | 100% | Fix Gateway startup |
| LOO fill rate | >70% of orders fill | Increase LOO\_LIMIT\_BUFFER if too many missed |
| Slippage vs prior close | Under 0.6% avg | Higher for small-caps expected |

### Going Live -- Two Changes Only

```python
IBKR_PORT = 4001  # was 4002 (paper) -- change in BOTH scripts
```

Switch Gateway from Paper to Live account. No other changes.

### Troubleshooting

| Problem | Likely cause | Fix |
| --- | --- | --- |
| "IBKR connection failed" (morning) | Gateway not running | Open Gateway and log in before 6:15 AM PT |
| "IBKR connection failed" (evening) | Gateway not running at 6 PM | Leave Gateway running all day or use IBC for auto-login |
| 0 entry candidates | SPY below 200d MA | Normal in bear market -- no action needed |
| All LOO orders not filling | LOO\_LIMIT\_BUFFER too tight | Increase from 0.005 to 0.010 in scan\_evening.py |
| Downloaded 123 tickers | Universe fetch broken | `pip install lxml` |
| Win rate < 55% after 50 trades | Signal logic drift | Verify parameter sync checklist above |
| positions error: no such table | DB not initialized | Run `python preflight.py` to create tables |
| PC asleep at trigger time | Windows sleep settings | Power & Sleep -> Sleep -> Never |

---

## Next Steps

### Step 1 -- Walk-Forward Validation COMPLETE

V34: OOS avg 19.45%, 7/8 positive. V35 sizing change does not alter signal selection, walk-forward conclusion carries forward.

### Step 2 -- Paper Trading ACTIVE (since April 2026)

Pass criteria: 3 months, win rate 57-63% over 100+ trades, no month worse than -15%, LOO fill rate >70%.

### Step 3 -- Go Live

Only after paper trading passes all criteria. Change `IBKR_PORT` to 4001 in both scripts.

### Step 4 -- Optimisation is complete

V35 is the confirmed ceiling. Do not retry entry filters, drawdown filters, or exit mechanics. The drawdown is structural and cannot be reduced without sacrificing CAGR. See the "Do Not Retry" table above for the complete list of exhausted approaches.

**One remaining low-priority test:** Earnings blackout extension (3 -> 5 days). Expected impact small given ~6 day avg hold.

---

## All Runs Table

| Version | Key Change | CAGR | Final Equity | Max DD | Sharpe |
| --- | --- | --- | --- | --- | --- |
| V21 | Run 5 + velocity crash pause | 7.55% | $476k | -22.6% | 0.72 |
| V22 | - DD scaling, - comm floor, - VIX pause | 9.14% | $652k | -26.3% | 0.71 |
| V23 | 40 pos x4% scaled (regression) | 8.65% | $592k | -26.7% | 0.68 |
| V24 | 40 pos x5% unchanged | 10.64% | $875k | -32.5% | 0.68 |
| V25 | VIX\_HIGH 25->30, cooldown 2d | 10.94% | $926k | -34.5% | 0.69 |
| V26 | VIX high-side penalty removed | 11.28% | $990k | -32.3% | 0.70 |
| V27 | VIX\_LOW 18->20 | 11.43% | $1,019k | -33.9% | 0.70 |
| V28 | VIX\_LOW 20->25 | 12.58% | $1,268k | -34.9% | 0.72 |
| V29 | POSITION\_SIZE\_HIGH 7.5%->9% | 12.60% | $1,274k | -38.5% | 0.68 |
| V30 | V28 + V29 combined | 14.42% | $1,797k | -39.4% | 0.72 |
| V30+S&P600 | + S&P 600 SmallCap universe | 16.01% | $2,414k | -48.65% | 0.73 |
| V31 | VIX 10d trend + $10M floor + DD scaling | 11.03% | $938k | -35.92% | 0.64 |
| V31b | $10M floor + DD scaling only | 13.17% | $1,419k | -39.16% | 0.68 |
| V32a | ATR-based position sizing | 15.98% | $2,403k | -48.61% | 0.73 |
| V32b | Tier 3 hold 8->6 days | 15.87% | $2,354k | -44.87% | 0.75 |
| V32c | VIX 5d trend: 80% size when falling | 15.28% | $2,111k | -44.30% | 0.74 |
| V32d | V32b + V32c combined | 15.37% | $2,145k | -39.21% | 0.77 |
| V32e | Composite ranking: RSI(2)/ATR\_pct | 16.10% | $2,454k | -48.61% | 0.73 |
| V32f | V32d + V32e combined | 15.31% | $2,123k | -39.62% | 0.77 |
| V33b | MAX\_POSITIONS raised 40->50 | 16.83% | $2,808k | -51.73% | 0.70 |
| V33b-d | 50 pos + V32d controls | 15.30% | $2,119k | -47.13% | 0.70 |
| V33c | MAX\_POSITIONS raised 50->55 | 17.16% | $2,982k | -53.27% | 0.69 |
| V33d | MAX\_POSITIONS raised 55->60 | 17.41% | $3,124k | -54.73% | 0.68 |
| V34a | Partial loss exit: day 4, >=-2%, trim 50% | 15.50% | $2,198k | -52.61% | 0.66 |
| V34b | V34a + Tier 1 target 2%->3% (contaminated) | 15.44% | $2,172k | -52.48% | 0.66 |
| V35a | T1 3%, T2 2.5% (clean base) | 17.26% | $3,038k | -56.46% | 0.68 |
| V36a-old | Signal stress: >40 signals -> 0.5x size | 16.42% | $2,605k | -52.19% | 0.67 |
| V37a | Breadth filter: <40% stocks above 20d+50d | 3.86% | $225k | -48.06% | 0.27 |
| V37b | Index vs constituents divergence >5% | 16.55% | $2,669k | -56.04% | 0.66 |
| V37d | Friday entry filter | 14.38% | $1,784k | -59.82% | 0.63 |
| V38a-C1 | IBS < 0.35 entry filter | 11.07% | $949k | -56.03% | 0.55 |
| V38a-C2 | EMA 20/50 downtrend block | 13.91% | $1,633k | -58.44% | 0.60 |
| V38a-C3 | Gap filter -1.5%->-1.0% (standalone) | 17.92% | $3,425k | -53.42% | 0.71 |
| V38a-C4 | Double time-stop cooldown | 17.25% | $3,036k | -54.72% | 0.68 |
| V38a-C5 | Tiered sizing top 20% x1.2 (standalone) | 17.82% | $3,367k | -55.92% | 0.68 |
| V39a-baseline | C3 permanent new baseline | 18.09% | $3,538k | -52.57% | 0.71 |
| V34 (V39a-c5) | C3 + C5 combined | 18.50% | $3,806k | -54.50% | 0.71 |
| V35 streak-C | 3 losses=50% size, 5=pause 3d, reset on win | 13.78% | $1,592k | -46.21% | 0.60 |
| V36 Test 1 | Rolling WR < 55% -> 50% size | 15.14% | $2,065k | -49.28% | 0.67 |
| V36 Test 2 | RSI(2) < 15 when VIX < 15 | 18.86% | $4,094k | -56.22% | 0.71 |
| V36 Test 1+2 | Both combined | 15.11% | $2,053k | -49.30% | 0.67 |
| V36a EWMA | Per-stock EWMA vol filter top 20% | 13.75% | $1,543k | -54.92% | 0.59 |
| V36c-v1 | Inverse ETF: SH/PSQ/RWM 4+ down days | 18.69% | $3,938k | -54.57% | 0.71 |
| V36e bonds | IEF mean reversion in bear regime | 17.93% | $3,884k | -54.64% | 0.70 |
| V36cv2 | Inverse ETF: SPY 1 up day + RSI2>65 in bear | CAGR neutral | Alt P&L -$10k | -54.50% | 0.71 |
| V37 vol peak | Volume must peak on final down day of streak | 6.24% | $366k | -40.76% | 0.50 |
| V40a | Gap filter -1.0%->-0.75% | 15.91% | $2,373k | -58.22% | 0.64 |
| V40b | Gap filter -1.0%->-0.50% | 13.97% | $1,652k | -58.80% | 0.59 |
| **V35 (V40c)** | **Tier multiplier 1.20x->1.30x** | **18.81%** | **$4,028k** | **-56.22%** | **0.71** |

**V35 is the confirmed ceiling. Optimisation is complete.**

---

## Repository Structure

```
.
+-- backtest-nmr.py              # Thin wrapper -- imports from backtest_nmr_lib.py
+-- backtest_nmr_lib.py          # All backtest logic, parameters, simulation (V35)
+-- backtest_nmr_lib_v36_tests.py  # Test build: rolling WR + VIX-RSI (both failed -- archived)
+-- walkforward.py               # Walk-forward validation runner
+-- scan_evening.py              # Live: evening signal scan + LOO order submission
+-- trade_morning.py             # Live: morning exit orders + fill confirmation
+-- preflight.py                 # Pre-flight system check (run before deployment)
+-- diag.py                      # SPY regime / DB diagnostic
+-- scan_debug.py                # Signal scanner debug (filter funnel)
+-- requirements.txt
+-- README-nmr.md
+-- results/
|   +-- metrics.json
|   +-- trades.csv
|   +-- equity_curve.csv
|   +-- walkforward_summary.csv
|   +-- walkforward_report.json
+-- paper_trading/
|   +-- summary.json
|   +-- trades.csv
|   +-- open_positions.csv
+-- .github/workflows/backtest.yml
```

---

## Setup & Running

### GitHub Actions (backtest only)

1. Push all files to your repo
2. **Settings -> Actions -> General -> Workflow permissions -> Read and write**
3. **Actions -> Naive MR Backtest -> Run workflow**

Walk-forward: set `run_walkforward = true` in workflow dispatch inputs. Adds 6-8 hours.

To run test variants: edit `ENABLE_TEST1_ROLLING_WR` and `ENABLE_TEST2_VIX_RSI` flags in `backtest_nmr_lib_v36_tests.py` and update the import in `backtest-nmr.py` to point to that file.

### Local Backtest

```
pip install -r requirements.txt
python backtest-nmr.py   # ~90-120 min with S&P 600
python walkforward.py    # ~6-8 hours with S&P 600
```

### Live Trading Setup (local PC)

```
cd C:\nmr-trader
python preflight.py      # Verify everything before first run
```

Ensure Gateway is running before both script trigger times.

### Health Checks

* `[Universe] Total unique tickers` < 1400: Wikipedia fetch may have failed
* `win_rate < 55%`: verify uniform 8-day windows; check SPY regime filter
* `CAGR < 17%` with no changes: verify `MAX_POSITIONS = 60` and version V35
* `trades_per_year < 700`: Tier 3 may be disabled -- check `MIN_CONSEC_DOWN = 4`
* `LOO fill rate < 50%`: LOO\_LIMIT\_BUFFER may be too tight -- increase to 0.010

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

Educational and research purposes only. Past backtest performance does not guarantee future results. Not financial advice. Consult a licensed financial advisor and CPA before trading with real capital. V35's aggressive position sizing (60 positions, up to 11.7% each for top signals when VIX < 25) is suitable only for those who understand and can hold through drawdowns of -56%+. V32d is the recommended alternative for Roth IRA accounts (MaxDD -39%, Sharpe 0.77).
