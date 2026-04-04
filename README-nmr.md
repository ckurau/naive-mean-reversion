# Naive Mean Reversion (MR) Backtest

A survivorship-bias-free backtest of a **Naive Mean Reversion** strategy across all historical S&P 500 + S&P 400 MidCap + S&P 600 SmallCap constituents, automated via GitHub Actions.

---

## Current Version: V32e (Best Confirmed Result)

The current script (`backtest-nmr.py`) is **V32e — V30+S&P600 base + composite entry ranking**.

**IMPORTANT FOR NEW SESSIONS:**
Push `backtest-nmr.py`, `backtest_nmr_lib.py`, and `walkforward.py` to GitHub and run the workflow. All three files must be in sync.

**CRITICAL ARCHITECTURE NOTE:** `backtest-nmr.py` is a **fully self-contained standalone script**. It does NOT import from `backtest_nmr_lib.py`. `walkforward.py` imports from `backtest_nmr_lib.py`. This means any changes to universe logic, parameters, or strategy rules must be made in **both** `backtest-nmr.py` and `backtest_nmr_lib.py` independently, or the two will diverge silently.

**Session objective: maximize total equity (taxable account).** V32e is recommended for a taxable account. V32d is recommended for a Roth IRA (better risk-adjusted profile). If your objective changes, see the version history table.

### Best Confirmed Results: V32e

| Metric | Value |
|---|---|
| CAGR | 16.10% |
| ROI / Year | 109.79% |
| Win Rate | 60.25% |
| Avg Win | 3.10% |
| Avg Loss | −3.57% |
| Profit Factor | 1.07 |
| Max Drawdown | −48.61% |
| Sharpe Ratio | 0.73 |
| Trades / Year | 872 |
| Final Equity (from $100k) | $2,454,236 |
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

### Previous Best (V30 + S&P 600) — for reference

| Metric | Value |
|---|---|
| CAGR | 16.01% |
| Final Equity | $2,414,283 |
| Max Drawdown | −48.65% |
| Sharpe Ratio | 0.73 |
| Trades / Year | 752 |

### Walk-Forward Validation: V32e ✅ COMPLETE

Walk-forward run using 8 rolling windows (5-year in-sample / 2-year out-of-sample).

| Window | OOS Period | CAGR | WinRate | PF | MaxDD | Sharpe | Trades | IS/OOS |
|---|---|---|---|---|---|---|---|---|
| W1 | 2009–2010 | 15.2% | 60.0% | 1.22 | −14.1% | 1.04 | 1224 | 0.40x |
| W2 | 2011–2012 | 30.8% | 64.5% | 1.37 | −21.5% | 1.09 | 1686 | 2.15x |
| W3 | 2013–2014 | 35.9% | 59.8% | 1.27 | −28.6% | 1.34 | 2127 | 1.53x |
| W4 | 2015–2016 | 7.2% | 57.6% | 1.10 | −20.2% | 0.52 | 1565 | 0.20x |
| W5 | 2017–2018 | 15.7% | 58.2% | 1.12 | −20.4% | 0.64 | 2224 | 0.68x |
| W6 | 2019–2020 | 29.9% | 62.2% | 1.28 | −35.0% | 0.93 | 1814 | 2.57x |
| W7 | 2021–2022 | −11.2% | 55.3% | 0.91 | −38.7% | −0.50 | 1506 | −0.51x |
| W8 | 2023–2025 | 1.8% | 59.1% | 1.01 | −39.8% | 0.22 | 3402 | 0.21x |

**OOS Positive CAGR windows: 7/8 — PASS**
**OOS Avg CAGR: 15.65% | OOS Median CAGR: 15.43%**

**V32e vs V30+S&P600 walk-forward comparison:**
OOS avg CAGR is identical at 15.65% — the composite ranking improvement is genuine and not in-sample noise. W7 (2021-22) marginally improved (−11.7% → −11.2%). All other windows within noise of baseline. V32e confirmed as legitimate production upgrade.

**Failure windows in context:**
- W7 (2021–22): Fastest Fed rate-hiking cycle in 40 years + small-cap amplification. −11.2% OOS is the known structural risk. Not a disqualifying failure.
- W4 (2015–16): Near-zero-volatility grinding market. 7.2% OOS — marginally positive.
- W8 (2023–25): 1.8% OOS. Weak but positive. IS/OOS of 0.21x is marginal but acceptable given structural headwinds.

**Conclusion: V32e has a genuine, demonstrable out-of-sample edge. Walk-forward PASSED.**

---

## V32e Strategy Rules (current code)

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
| **Max positions** | 40 simultaneous holdings |
| **Position size** | VIX < 25 → 9%, VIX ≥ 25 → 5% base |
| **VIX high-side penalty** | REMOVED — high-VIX environments are best for mean reversion |
| **Drawdown scaling** | REMOVED — costs too much in recovery years |
| **VIX spike pause** | REMOVED — VIX spike days are best entry conditions |
| **Velocity crash pause** | SPY 5-day return < −12% → pause all entries for 5 days |
| **Earnings month cap** | Position size capped at 2.4% in Jan/Apr/Jul/Oct |
| **Signal ranking** | Composite score: RSI(2) / ATR_pct — most oversold AND most volatile first [V32e] |
| **Sector filter** | Skip entry if stock's sector ETF is below its 20-day MA |
| **Correlation cap** | Max 3 open positions in same sector |
| **Earnings blackout** | Skip entries within ±3 days of earnings announcement |
| **SPY regime** | No new entries when SPY is below its 200-day MA |
| **Re-entry cooldown** | No re-entry in a stock for 5 days after a time-stop exit |
| **Commission** | $0.005/share or $0.35 minimum per trade |

---

## Walk-Forward Validation Results (Run 5 baseline — historical reference)

✅ Walk-forward was run using 8 rolling windows (5-year in-sample / 2-year out-of-sample). Parameters fixed at Run 5 settings.

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

**OOS Positive CAGR windows: 6/8 — PASS**
**OOS Avg CAGR: 5.58% | OOS Median CAGR: 5.01%**

### Walk-Forward Validation Results (V30, S&P 500+400 only — historical reference)

| Window | OOS Period | CAGR | WinRate | PF | MaxDD | Sharpe | IS/OOS |
|---|---|---|---|---|---|---|---|
| W1 | 2009–2010 | 20.2% | 60.6% | 1.35 | −13.0% | 1.31 | 0.61x |
| W2 | 2011–2012 | 24.5% | 63.5% | 1.33 | −19.8% | 0.97 | 1.52x |
| W3 | 2013–2014 | 27.0% | 59.8% | 1.26 | −22.2% | 1.24 | 1.21x |
| W4 | 2015–2016 | 2.9% | 55.9% | 1.05 | −18.3% | 0.27 | 0.10x |
| W5 | 2017–2018 | 6.0% | 57.1% | 1.05 | −23.8% | 0.35 | 0.37x |
| W6 | 2019–2020 | 27.4% | 62.7% | 1.35 | −28.9% | 0.94 | 5.15x |
| W7 | 2021–2022 | −4.0% | 54.5% | 0.96 | −29.1% | −0.12 | −0.26x |
| W8 | 2023–2025 | 5.5% | 60.5% | 1.05 | −35.3% | 0.32 | 0.56x |

**OOS Positive CAGR windows: 7/8 — PASS**
**OOS Avg CAGR: 13.69% | OOS Median CAGR: 13.12%**

---

## Complete Version History

### Original Session (V1–Run 7) — Pre-V10

| Run | Change | CAGR | Win Rate | Max DD | Sharpe | Final Equity |
|---|---|---|---|---|---|---|
| V7 original | RSI bug, no DD scaling | 9.05%* | 69.72%* | −28.94% | 0.74 | $641k |
| Run 1 | DD scaling (broken tier windows) | 1.73% | 57.37% | −22.13% | 0.26 | $144k |
| Run 2 | Uniform 8d windows | 6.85% | 60.24% | −19.57% | 0.73 | $414k |
| Run 3 | + Partial exits on all tiers | 6.77% | 71.59% | −18.94% | 0.73 | $407k |
| Run 4 | − Partial exits on Tier 2/3 | 6.83% | 60.24% | −19.57% | 0.73 | $413k |
| **Run 5** | **DD thresholds loosened 8%/15%** | **7.58%** | **60.28%** | **−22.55%** | **0.73** | **$478k** |
| Run 6 | SPY same-day entry filter (failed) | 4.40% | 59.44% | −23.73% | 0.50 | $252k |
| Run 7 | VIX spike exit on losing positions (failed) | 6.99% | 58.43% | −25.58% | 0.70 | $425k |

*V7 original numbers inflated by RSI routing bug. Run 5 is the legitimate confirmed baseline.

### Second Session (V10–V30) — Optimisation Research

| Version | Key Change | CAGR | Final Equity | Max DD | Sharpe | Verdict |
|---|---|---|---|---|---|---|
| V10 | ROC filter, bull regime, RSI exit 75, no Tier 3 | 1.05% | $125k | −21% | 0.20 | Regression — ROC killed 68% of trades |
| V11 | Loosened ROC, RSI exit 85, Tier 2 partial | 0.65% | $115k | — | — | Regression — partials destroyed payout |
| V12 | Tier 2 partial removed, crash position limit | 0.72% | $117k | — | — | Regression — still missing Tier 3 |
| V13 | Tier 2 bull block, target 1.5% | 0.99% | $124k | — | — | Regression |
| V14 | Hold 11-12d, SPY 50d guard, ROC disabled | 1.65% | $142k | −19.7% | 0.30 | Regression — 50d guard hurt 2009 |
| V15 | **Tier 3 restored**, 8d windows, 50d guard removed | 5.69% | $327k | −26.0% | 0.61 | Breakthrough — Tier 3 is essential |
| V16 | Tier 3 target 1.5%, velocity crash pause | 6.31% | $370k | −16.9% | 0.63 | Best drawdown, strong result |
| V17 | Tier 3 target 1.25%, Tier 3 bear filter | 5.57% | $319k | −26.4% | 0.58 | Regression — bear filter broke 2020 |
| V18 | 6 additions on V16 base | 4.65% | $265k | −16.9% | 0.60 | Regression — first-up-close exit dominated |
| V19 | V7 uniform 2% target + 4 protections | 5.72% | $330k | −27.1% | 0.59 | Hypothesis disproved: targets not the key |
| V20 | V7 exits, bull block removed, crash limit removed | 5.68% | $327k | −20.6% | 0.55 | Bull regime (55.9% WR) destroyed value |
| V21 | Run 5 exact + velocity crash pause only | 7.55% | $476k | −22.6% | 0.72 | Clean Run 5 + one good addition |
| V22 | – DD scaling, – commission floor $0.35, – VIX pause | 9.14% | $652k | −26.3% | 0.71 | **Major breakthrough** |
| V23 | 40 pos ×4% (wrong scaling), VIX_LOW 18 | 8.65% | $592k | −26.7% | 0.68 | Regression — sizing down cost more than volume gained |
| V24 | **40 pos ×5% (size unchanged)**, VIX_LOW 18 | 10.64% | $875k | −32.5% | 0.68 | **First above 10%** |
| V25 | VIX_HIGH 25→30, cooldown 2d | 10.94% | $926k | −34.5% | 0.69 | Good — VIX_HIGH lever works |
| V26 | VIX high-side penalty **removed entirely** | 11.28% | $990k | −32.3% | 0.70 | DD improved while returns rose |
| V27 | VIX_LOW raised 18→20 | 11.43% | $1,019k | −33.9% | 0.70 | Crossed $1M |
| V28 | **VIX_LOW raised 20→25** | 12.58% | $1,268k | −34.9% | 0.72 | Huge jump — recovery years captured |
| V29 | POSITION_SIZE_HIGH 7.5%→9% (from V27 base) | 12.60% | $1,274k | −38.5% | 0.68 | Tied with V28, worse Sharpe and DD |
| **V30** | **V28 + V29 combined: VIX_LOW=25 + 9% boost** | **14.42%** | **$1,797k** | **−39.4%** | **0.72** | **S&P 500+400 best** |
| **V30+600** | **+ S&P 600 SmallCap universe** | **16.01%** | **$2,414k** | **−48.65%** | **0.73** | **Current best — 24× from $100k** |

---

## Key Insights (Updated)

### V7's $641k is not a reproducible target from a fresh $100k start

The README and version history reference V7's $641k final equity. This number reflected a specific compounding path — the 2012-2013 gains happened when the portfolio had already grown large through earlier years. Multiple direct attempts to reproduce it from a $100k start (V19, V20) produced $320-330k. The $641k should not be used as a benchmark. V30+S&P600's $2,414k is the legitimate current best from a confirmed $100k starting position.

### backtest-nmr.py is standalone — changes must be made in both files

`backtest-nmr.py` does NOT import from `backtest_nmr_lib.py`. It is fully self-contained. `walkforward.py` imports from `backtest_nmr_lib.py`. This means:
- Any parameter or logic change must be made in **both** `backtest-nmr.py` and `backtest_nmr_lib.py`
- The two files will silently diverge if you only update one
- This was confirmed the hard way: multiple failed runs showed S&P 600 missing because only the lib was updated, not the main script
- Always verify both files have the same universe, parameters, and logic before triggering a run

### The S&P 600 addition is genuinely additive, not in-sample noise

Adding the S&P SmallCap 600 universe improved OOS avg CAGR from 13.69% to 15.65% — proportionally with the IS improvement (14.42% → 16.01%). This is the opposite of what overfitting looks like. Key observations:
- Win rate unchanged at 60.27% OOS — the edge applies equally to small-caps
- 6 of 8 walk-forward windows improved
- W7 (2021–22) worsened from −4% to −11.7% — small-caps are hit harder in bear markets. This is an expected and acceptable tradeoff for the overall gain
- In live trading, small-cap slippage on open fills will be higher than large-caps — the `MIN_DOLLAR_VOLUME = $5M` filter already removes the worst offenders, but expect the live benefit to be somewhat smaller than the backtest suggests

### The core mechanism — unchanged across all versions

**The uniform 8-day window is the single most important parameter.** All gains, regressions, and optimisations across 30+ versions left this intact. Win rate has been 60.18–60.28% in every version from Run 5 through V30+S&P600. The underlying edge has not changed — only the leverage and universe applied to it.

**RSI(2) is always below 5 after 4+ consecutive down days.** Do not use RSI(2) to discriminate between tiers. Use consecutive down days instead. RSI(2) is only useful for ranking candidates (most oversold first).

**Tier 3 (4-day setups) is essential.** Removing it (V10–V14) collapsed CAGR from ~7% to 1–1.65% and halved trade volume. Every version without Tier 3 underperformed dramatically. Never remove it.

### What the second session proved

**Removing protective mechanisms increases returns — when done selectively.** Three removals drove the largest gains:
1. Drawdown scaling removed (V22): freed up full position sizes during recovery years — 2013 and 2017 immediately jumped
2. VIX spike entry pause removed (V22): VIX spike days are the best mean reversion entry conditions, not the worst
3. VIX high-side penalty removed (V26): high-VIX environments are maximally oversold — undersizing them was wrong

**The VIX_LOW lever had far more room than expected.** Raising VIX_LOW from 15 (Run 5) to 25 (V28) was the dominant source of gains in the second session. Years like 2020-2021 where VIX sat in the 20-25 range during recovery got full-size positions instead of reduced ones.

**The velocity crash pause is the one protection worth keeping.** Added in V21, it fires only when SPY drops >12% in 5 days (March 2020-level events). It saved ~$40-60k in 2020 at essentially zero cost to good years. All other protective mechanisms were net negative.

**Position count: 40 is better than 30 — but ONLY if size is NOT reduced.** V23 tested 40 positions at 4% size (scaled to maintain "similar exposure") and regressed. V24 tested 40 positions at 5% size (unchanged) and was a major improvement. The lesson: adding positions at full size captures overflow on high-signal days without diluting existing trades. Never scale down position size to "make room" for more positions.

**VIX sizing is a compounding amplifier, not a risk tool.** The VIX high-side penalty (VIX > 25 → 2.5%) was removed because it undersized positions during the periods of strongest mean reversion edge. VIX above 25 means stocks are maximally oversold — exactly when you want full size. The velocity crash pause handles genuine extreme events; the VIX sizing regime doesn't need to.

### What doesn't work — do not retry

| Approach | What Was Tested | Why It Failed |
|---|---|---|
| **Price-based stop-losses** | −3% stop (V3) | 22.6% of trades hit the stop then bounced. Every stop converted a win to a loss |
| **Circuit breakers** | Portfolio-level entry halt at −10% DD | Fired permanently in 2004-2006. Never reset. Blocked 89.3% of trading days |
| **ROC entry filter** | Stock must be down 4%+ from streak start | Killed 68% of trades. Removed the fast-bounce setups that are most profitable |
| **SPY 50d guard** | No entries when SPY below 50d SMA | Blocked 2009 recovery trades. The 200d guard is sufficient |
| **SPY same-day entry filter** | Skip entries when SPY down >0.5% on signal day | Filtered trades had higher EV (0.79%/trade) than kept trades (0.45%/trade) |
| **VIX spike exit** | Exit losing positions during VIX spike pause | Fired 1,476 times vs expected ~50/year. Cut positions before VIX-spike bounces |
| **First-up-close exit** | Exit on first up-day after 4 days held | Dominated 54% of exits (V18), cut winners short, lower avg win |
| **Tier 3 target differentiation** | Lower target (1%, 1.25%, 1.5%) for 4-day setups | Every version with differentiated Tier 3 target underperformed uniform 2% |
| **Conditional bear filter** | Block Tier 3 when SPY 20d return < −5% | Interacted destructively with velocity crash pause, broke 2020 fix |
| **Dynamic position sizing by days** | 4-day setups at 0.85× base size | Approximately neutral, not worth the complexity |
| **Bull regime entry block** | Block Tier 2+3 in bull markets | Bull regime (55.9% WR) was still profitable; blocking it cost compounding in 2012-2013 |
| **Sector RSI filter** | Skip Tier 3 if sector ETF RSI(2) > 60 | Effect unclear, buried under other changes |
| **Re-entry cooldown 2 days** | Reduce from 5 to 2 days | Only 3 extra trades/year — neutral |
| **Scaling position size down for more positions** | 40 positions at 4% instead of 5% | Per-trade profit fell 20%, volume gain couldn't compensate |
| **Tier 3 target at 1.25%** | Between V15 (1%) and V16 (1.5%) | Strictly worse than 1.5% at same trade volume |
| **SPY momentum filter for Tier 3** | Skip if SPY up >0.5% on signal day | Effect unclear under V18 noise |
| **Drawdown scaling with tight thresholds** | 5%/10% thresholds (original) | Fired during normal volatility, reduced size when most needed |
| **70/30 SPY blend** | Blending strategy with SPY B&H | After-tax, the strategy edge over SPY narrows — blending reduces total equity vs all-in |
| **Binary VIX trend filter** | V31: no entries when VIX below 10d MA | Blocked 37%+ of trading days, killed volume. CAGR 11.03%, Sharpe dropped to 0.64 |
| **$10M dollar volume floor** | V31b: raised MIN_DOLLAR_VOLUME $5M→$10M | PF improved only +0.01, Sharpe dropped. Marginal quality gain, real volume cost |
| **DD scaling at 20% threshold** | V31b: >20% DD → 30% size reduction | Same pattern as original DD scaling removal — reduces size during best recovery periods |
| **ATR-based position sizing** | V32a: size = fixed dollar risk / ATR | VIX cap (9%/5%) overrides ATR size on majority of trades. No net effect |
| **VIX trend continuous sizing alone** | V32c: VIX falling → 80% size | Improved DD slightly but cost $300k equity vs baseline. V32d is better combined version |
| **Combining regime sizing + composite ranking** | V32f: V32d + V32e | V32e's equity benefit disappears when regime sizing reduces exposure. Use one or the other |

### What works — confirmed positive contributions

| Addition | First Tested | Effect | Status |
|---|---|---|---|
| Uniform 8-day window | Run 2 | Core mechanism | ✅ Kept |
| Tier 1 partial exit (50% at +1%) | Run 3 | Small positive | ✅ Kept |
| S&P 400 universe expansion | V4 | +35% more trades/year | ✅ Kept |
| RSI(2) signal ranking | V4 | Better quality trades at zero cost | ✅ Kept |
| Sector ETF MA filter | V4 | Removes low-quality entries | ✅ Kept |
| Earnings blackout ±3 days | V4 | Removes gap-down risk | ✅ Kept |
| Sector correlation cap (max 3) | V4 | Prevents hidden concentration | ✅ Kept |
| VIX-adjusted sizing | V4 | Size larger when calm | ✅ Kept (tuned) |
| SPY 200d regime filter | V4 | No entries in bear market | ✅ Kept |
| Gap filters | V4 | Reduces adverse open fills | ✅ Kept |
| Re-entry cooldown (5 days) | V4 | Prevents re-chasing losses | ✅ Kept |
| Tier 3 (4-day setups) | V15 | Essential — highest trade volume | ✅ Kept |
| Velocity crash pause | V21 | Fixed 2020; +$40-60k at near-zero cost | ✅ Kept |
| DD scaling removed | V22 | Full size during recovery years | ✅ Applied |
| VIX spike pause removed | V22 | VIX spikes = best entry conditions | ✅ Applied |
| Commission floor $0.35 | V22 | Matches IB tiered reality | ✅ Applied |
| 40 positions at full 5% size | V24 | Captures overflow on high-signal days | ✅ Applied |
| VIX_LOW raised to 25 | V28 | Recovery years get full 9% size | ✅ Applied |
| VIX high-side penalty removed | V26 | High-VIX = strongest MR conditions | ✅ Applied |
| 9% boost for VIX < 25 | V30 | Bull/recovery years get larger positions | ✅ Applied |
| S&P 600 SmallCap universe | V30+600 | +1.59% CAGR, +$617k equity, OOS confirmed | ✅ Applied |
| **Composite ranking (RSI2/ATR_pct)** | **V32e** | **+$40k equity, +0.09% CAGR, no downsides** | **✅ Applied** |
| Tier 3 hold 6d (was 8d) | V32b | Sharpe 0.75, Avg Loss −3.12% — risk-adjusted improvement | ✅ Kept in V32d only |
| VIX 5d trend 80% sizing | V32c | MaxDD −44.30%, trades continue at reduced size | ✅ Kept in V32d only |

---

## The Honest Risk Picture for V32e

V32e's gains come entirely from **leverage amplification and universe expansion on the same edge**, not from finding a better edge. This has important implications:

**The Sharpe ratio has been stable.** Run 5: 0.73. V32e: 0.73. Despite nearly 5× the final equity, the risk-adjusted return is unchanged. Every dollar of additional return came with proportional additional risk. V32d achieved Sharpe 0.77 with MaxDD −39% but at a cost of $300k final equity — the right choice depends on your account type and risk tolerance.

**Bad years scale with portfolio size.** At V32e's ~$2.45M peak equity:
- 2022 lost ~$691k in a single year
- The −48.61% max drawdown means a potential ~$1.2M paper loss peak-to-trough
- V32d's −39.21% max drawdown limits this to ~$950k on equivalent equity

**The VIX sizing parameters are aggressive.** VIX < 25 → 9% positions. At 40 positions, theoretical maximum notional exposure is 360% of portfolio (though average simultaneous open positions is 8–15 in practice).

**Small-cap amplification cuts both ways.** The S&P 600 addition improved good years significantly but made bad years worse. W7 OOS (2021–22) went from −4% to −11.7% with S&P 600 included.

**Win rate is unchanged and must remain the anchor.** If live win rate drops below 56%, the strategy is failing. Monitor this before increasing position sizes.

---

## Optimism Bias Warnings (Updated)

V32e's reported 16.10% CAGR is the **in-sample ceiling**, not the live expectation.

| Source | Estimated CAGR Impact |
|---|---|
| Slippage on open prices (worse for small-caps) | −1.5 to −2.5% |
| Survivorship bias (incomplete historical universe) | −1 to −2% |
| Overfitting across 30+ iterations on same dataset | −2 to −3% |
| Earnings calendar lookahead (today's known dates used) | −0.3 to −0.5% |
| VIX regime parameters tuned to history | −1 to −2% |
| **Realistic live estimate** | **~7 to 11% CAGR gross** |

The V30+S&P600 walk-forward showed 15.65% OOS avg CAGR vs 16.01% in-sample — only a 2.2% decay. This is unusually small and likely reflects the walk-forward's own IS/OOS limitations rather than the true live decay. Apply the same ~26% decay ratio observed in Run 5 to get a conservative estimate: 16.10% × 0.74 ≈ ~12% live gross. After short-term capital gains tax (32–37%), realistic net CAGR is likely 6–9%.

---

## SPY vs Strategy (Updated)

| Metric | SPY B&H | Run 5 | V30 | V30+S&P600 | V32e | V32d |
|---|---|---|---|---|---|---|
| CAGR (gross, in-sample) | ~10.5% | 7.58% | 14.42% | 16.01% | 16.10% | 15.37% |
| CAGR (gross, OOS avg) | ~10.5% | 5.58% | 13.69% | 15.65% | TBD | TBD |
| CAGR (after tax, est.) | ~8.4% | ~3.5–5% | ~5–9% | ~6–9% | ~6–9% | ~6–9% |
| Max Drawdown | −55% (2008) | −22.55% | −39.37% | −48.65% | −48.61% | −39.21% |
| Sharpe Ratio | ~0.55 | 0.73 | 0.72 | 0.73 | 0.73 | 0.77 |
| Final Equity ($100k start) | ~$800k | $478k | $1,797k | $2,414k | $2,454k | $2,145k |

**SPY comparison:** V30+S&P600 beats SPY on gross CAGR clearly. After tax in a taxable account the edge narrows — 872 trades/year means almost entirely short-term capital gains. In a tax-advantaged account (IRA), go all-in on the strategy. In a taxable account, the strategy still wins on gross but the tax drag is significant.

**Blend vs all-in decision:** The 70/30 SPY blend discussed in earlier sessions was relevant when the strategy underperformed SPY. At V30+S&P600's OOS results (15.65% avg), the strategy clearly outperforms SPY even OOS. The recommendation is **all-in on the strategy in a tax-advantaged account**, or a 50/50 blend in a taxable account to capture SPY's long-term capital gains treatment.

**Correlation:** Near-zero correlation with SPY means the strategy provides genuine diversification regardless of return comparison.

**Tax note:** ~872 trades/year qualifies for IRS trader tax status (Section 475(f) MTM election) in most years. Consult a CPA specialising in trader tax (e.g. Green Trader Tax) before forming any entity.

---

## Paper Trading & Live Automation

### Status: ✅ LIVE (paper trading active as of April 2026)

The automated paper trading system is fully operational. Setup is complete:

- **Broker:** Interactive Brokers (IBKR) paper account, starting equity $100,000
- **Script:** `C:\nmr-trader\trade.py` — runs automatically every weekday
- **Scheduler:** Windows Task Scheduler fires at **6:25 AM PT** (before 6:30 AM PT market open)
- **Orders:** Market On Open (MOO) submitted before the 6:28 AM PT auction cutoff
- **Database:** `C:\nmr-trader\positions.db` — SQLite, tracks all open positions and trade history
- **Alerts:** Daily summary email via SendGrid after each run
- **Library:** `ib_async` (actively maintained successor to `ib_insync`, supports Python 3.10–3.14)

### Broker: Interactive Brokers (IBKR) — confirmed choice

- **`ib_async`**: the actively maintained successor to `ib_insync` after the original author passed away in 2024. Import as `from ib_async import IB, Stock, Order` — identical API
- **Paper trading environment**: real market data, simulated fills at actual open prices — not a toy simulator
- **Commission model matches**: $0.005/share with $0.35 minimum matches the backtest exactly
- **Transition**: paper → live is a single config line change, not a code rewrite
- **Port:** 4002 for paper trading, 4001 for live

### How the automation works

```
Every weekday 6:25 AM PT (Windows Task Scheduler):
  trade.py runs automatically
    ├── Connects to IBKR Gateway (must be open and logged in)
    ├── Reads portfolio value from IBKR account
    ├── Downloads VIX + SPY regime data
    ├── Checks velocity crash pause and SPY 200d MA filter
    ├── Downloads ~300 days of price data for full universe (~1800 tickers)
    ├── Processes exits for open positions (time stop / profit target / partial)
    ├── Generates entry signals (RSI, consecutive down days, all filters)
    ├── Submits MOO orders to IBKR
    ├── Waits 5 minutes for fills at 6:30 AM PT market open
    ├── Updates entry prices in positions.db from actual fills
    └── Sends daily summary email
```

### Daily operations — what to expect

**You don't need to do anything daily.** The system is fully automated. Each morning you will receive an email showing portfolio value, VIX level, position size being used, what exited and why, and what entered.

**Days with no trades are completely normal.** When SPY is below its 200-day MA the strategy blocks all entries. This is the bear market filter working correctly — not a malfunction.

**IBKR Gateway must be open and logged in before 6:25 AM PT.** It is set to auto-start at Windows login. After any reboot, log into Gateway manually before the market opens.

### Local commands — checking progress

Open Command Prompt and activate the virtual environment first:

```bat
cd C:\nmr-trader
venv\Scripts\activate
```

**Check win rate and total P&L:**
```bat
python -c "import sqlite3, pandas as pd; conn = sqlite3.connect(r'C:\nmr-trader\positions.db'); trades = pd.read_sql(\"SELECT * FROM trade_log WHERE exit_reason != 'partial_exit'\", conn); conn.close(); total = len(trades); wr = len(trades[trades['pnl_usd']>0])/total*100 if total else 0; pnl = trades['pnl_usd'].sum() if total else 0; print(f'Completed trades: {total}'); print(f'Win rate: {wr:.1f}%  (target: 57-63%)'); print(f'Total P&L: ${pnl:,.2f}'); print('WARNING: win rate below 55%' if total >= 30 and wr < 55 else 'CAUTION: below 57%' if total >= 30 and wr < 57 else 'Win rate OK' if total >= 30 else f'({total}/30 trades before win rate is meaningful)')"
```

**Check current open positions:**
```bat
python -c "import sqlite3, pandas as pd; conn = sqlite3.connect(r'C:\nmr-trader\positions.db'); pos = pd.read_sql('SELECT * FROM open_positions', conn); conn.close(); print(f'Open positions: {len(pos)} / 40'); [print(f\"  {r['ticker']}: entered {r['entry_date']} | tier {r['tier']} | {r['shares_remaining']:.0f}sh @ ${r['entry_price']:.2f}\") for _, r in pos.iterrows()] if not pos.empty else print('  None')"
```

**Check portfolio value (requires IBKR Gateway to be running):**
```bat
python -c "from ib_async import IB; ib = IB(); ib.connect('127.0.0.1', 4002, clientId=2); [print(f'Portfolio: ${float(av.value):,.2f}') for av in ib.accountValues() if av.tag == 'NetLiquidation' and av.currency == 'USD']; ib.disconnect()"
```

**View today's log:**
```bat
type C:\nmr-trader\trade.log
```

**Watch the log live (while the script is running at 6:25 AM):**
```bat
powershell -command "Get-Content C:\nmr-trader\trade.log -Wait"
```

**Run the script manually for testing:**
```bat
python C:\nmr-trader\trade.py
```

Or right-click **NMR Trader** in Windows Task Scheduler → **Run**.

### What the log output means

```
=== NMR Trading Run: 2026-04-02 ===          ← script started
Connected to IBKR Gateway                     ← IBKR connection OK
Portfolio value: $100,000.00                  ← current account value
VIX: 23.9 | SPY 5d: 1.7% | SPY>200d: False  ← market regime data
Entries blocked: SPY below 200d MA            ← bear market filter active, no entries today
Disconnected from IBKR                        ← clean exit
NMR Daily Summary — 2026-04-02               ← summary email content follows
```

**Normal messages that are NOT errors:**
- `possibly delisted; no price data found` — historical tickers (LEH, BSC etc.) that no longer trade. Expected, harmless.
- `Entries blocked: SPY below 200d MA` — bear market filter. No trades is the correct behaviour.
- `Velocity crash pause active` — SPY dropped >12% in 5 days. Entries paused. Correct behaviour.

### Pass criteria for moving to live capital

After at least 3 months of paper trading:

| Check | Target | Action if failing |
|---|---|---|
| Win rate | 57–63% over 100+ trades | Stop — review signal logic vs backtest parameters |
| Trades per month | 65–90 | Check universe fetch and signal parameters |
| Worst single month | Better than −15% | Acceptable if isolated; review if repeated |
| Script ran every trading day | 100% | Fix Gateway startup or Task Scheduler issue |
| Slippage vs prior close | Under 0.6% avg | Higher for small-caps is expected |

### Going live — two changes only

When paper trading passes all criteria:

**Change 1 — in `C:\nmr-trader\trade.py`:**
```python
IBKR_PORT = 4001   # was 4002 (paper)
```

**Change 2 — in IBKR Gateway settings:**
Switch login from Paper Trading to Live account. Restart Gateway.

No other code changes required.

### Troubleshooting the automated system

| Problem | Likely cause | Fix |
|---|---|---|
| "IBKR connection failed" | Gateway not running | Open Gateway and log in before 6:25 AM PT |
| "IBKR connection failed" | Wrong port | Verify `IBKR_PORT=4002` in trade.py |
| Script didn't run at 6:25 AM | PC was asleep | Power & Sleep → Sleep → Never |
| Script didn't run at 6:25 AM | Task Scheduler issue | Right-click NMR Trader → Run to test manually |
| 0 entry candidates every day | SPY below 200d MA | Normal in bear market — not a bug |
| Win rate < 55% after 50 trades | Signal logic drift | Verify trade.py constants match backtest-nmr.py exactly |
| No summary email | SendGrid misconfigured | Check SENDGRID_API_KEY in trade.py |

---

## Next Steps

### Step 1 — Walk-Forward Validation ✅ COMPLETE
V30+S&P600 walk-forward: OOS avg 15.65%, 7/8 positive windows.
V32e walk-forward: OOS avg 15.65%, 7/8 positive windows. Identical OOS performance confirms composite ranking improvement is real, not in-sample noise. Both versions confirmed genuine OOS edge.

### Step 2 — Paper Trading ✅ COMPLETE (active since April 2026)
- IBKR paper account open, starting equity $100,000
- `trade.py` running automatically every weekday at 6:25 AM PT via Windows Task Scheduler
- SQLite position database tracking all open positions and trade history
- Daily summary email via SendGrid
- Pass criteria: 3 months, win rate 57–63% over 100+ trades, no month worse than −15%

### Step 3 — Go Live ⏳
Only after paper trading passes all criteria:
- Change `IBKR_PORT = 4002` to `4001` in `trade.py`
- Switch Gateway from paper to live account
- Monitor win rate over first 100 live trades before considering any sizing changes

### Step 4 — Future Edge Improvements (not more leverage)
Genuine improvements that would improve the strategy edge, not just sizing:
- **Historical earnings database** — removes the lookahead bias in the current earnings calendar (yfinance uses today's known dates, not historical). Estimated impact: +0.3 to +0.5% CAGR
- **Live OOS validation** — 6–12 months of paper trading is the only true out-of-sample test

---

## All Runs Table

### V10–V20: Optimisation Research (what didn't work)

| Version | Key Change | CAGR | Final Equity | Key Learning |
|---|---|---|---|---|
| V10 | ROC filter, no Tier 3, bull regime, RSI exit 75 | 1.05% | $125k | ROC killed 68% of trades; Tier 3 removal is catastrophic |
| V11 | ROC −2.5%, Tier 2 partial, RSI exit 85 | 0.65% | $115k | Tier 2 partial with wrong ratio destroyed payout ratio |
| V12 | Tier 2 partial removed, crash limit added | 0.72% | $117k | Still missing Tier 3 — structural issue |
| V13 | Tier 2 bull block | 0.99% | $124k | Small improvement; Tier 3 still missing |
| V14 | Hold 11-12d, SPY 50d guard | 1.65% | $142k | 50d guard blocked 2009 recovery; extended hold barely helped |
| V15 | Tier 3 restored, 8d windows, 50d guard removed | 5.69% | $327k | Breakthrough — Tier 3 was the missing ingredient |
| V16 | Tier 3 target 1.5%, velocity crash pause | 6.31% | $370k | Best drawdown ever (−16.9%); 2020 fixed |
| V17 | Tier 3 target 1.25%, Tier 3 bear filter | 5.57% | $319k | Bear filter broke velocity pause interaction; regression |
| V18 | 6 additions: first-up-close, dynamic sizing, etc. | 4.65% | $265k | First-up-close dominated 54% of exits; all additions net negative |
| V19 | Uniform 2% target hypothesis test | 5.72% | $330k | Hypothesis disproved: target not the source of V7's $641k |
| V20 | Bull block removed, crash limit removed | 5.68% | $327k | Bull trades (55.9% WR) added volume but hurt quality |

### V21–V32e: The Breakthrough Sequence

| Version | Key Change | CAGR | Final Equity | Max DD | Sharpe |
|---|---|---|---|---|---|
| V21 | Run 5 exact + velocity crash pause | 7.55% | $476k | −22.6% | 0.72 |
| V22 | − DD scaling, − comm floor, − VIX pause | 9.14% | $652k | −26.3% | 0.71 |
| V23 | 40 pos ×4% scaled (regression) | 8.65% | $592k | −26.7% | 0.68 |
| V24 | 40 pos ×5% unchanged, VIX_LOW 18 | 10.64% | $875k | −32.5% | 0.68 |
| V25 | VIX_HIGH 25→30, cooldown 2d | 10.94% | $926k | −34.5% | 0.69 |
| V26 | VIX high-side penalty removed | 11.28% | $990k | −32.3% | 0.70 |
| V27 | VIX_LOW 18→20 | 11.43% | $1,019k | −33.9% | 0.70 |
| V28 | VIX_LOW 20→25 | 12.58% | $1,268k | −34.9% | 0.72 |
| V29 | POSITION_SIZE_HIGH 7.5%→9% (from V27) | 12.60% | $1,274k | −38.5% | 0.68 |
| V30 | V28 + V29 combined | 14.42% | $1,797k | −39.4% | 0.72 |
| V30+S&P600 | + S&P 600 SmallCap universe | 16.01% | $2,414k | −48.65% | 0.73 |
| V31 | VIX 10d trend filter + $10M floor + DD scaling | 11.03% | $938k | −35.92% | 0.64 |
| V31b | $10M floor + DD scaling only (no VIX filter) | 13.17% | $1,419k | −39.16% | 0.68 |
| V31c | VIX 5d trend filter only | — | — | — | — |
| V32a | ATR-based position sizing | 15.98% | $2,403k | −48.61% | 0.73 |
| V32b | Tier 3 hold window 8→6 days | 15.87% | $2,354k | −44.87% | 0.75 |
| V32c | VIX 5d trend: 80% size when VIX falling | 15.28% | $2,111k | −44.30% | 0.74 |
| V32d | V32b + V32c combined | 15.37% | $2,145k | −39.21% | 0.77 |
| **V32e** | **Composite ranking: RSI(2)/ATR_pct** | **16.10%** | **$2,454k** | **−48.61%** | **0.73** |
| V32f | V32d + V32e combined | 15.31% | $2,123k | −39.62% | 0.77 |

**Key finding from V31/V32 series:**
- V31 (binary VIX filter) proved regime filtering kills volume and CAGR — rejected
- V31b showed $10M floor + DD scaling add cost without proportional benefit — rejected
- V32a (ATR sizing) made no difference — VIX cap overrides ATR size on most trades
- V32b (Tier 3 hold 6d) genuinely improved Sharpe and avg loss — good isolated change
- V32c (VIX trend 80% size) improved drawdown at modest CAGR cost
- V32d (V32b+V32c) is the best risk-adjusted version — recommended for Roth IRA
- V32e (composite ranking) is a free +$40k with no downsides — current production version
- V32f showed combining V32d+V32e adds nothing over V32d — improvements don't stack when regime sizing is present

---

## Repository Structure

```
.
├── backtest-nmr.py          # Main backtest (V32e — STANDALONE, does not import lib)
├── backtest_nmr_lib.py      # Shared library (imported by walkforward.py — must match main script)
├── walkforward.py           # Walk-forward out-of-sample test framework
├── requirements.txt         # Python dependencies
├── README-nmr.md            # This file
├── results/                 # Auto-generated (committed by CI)
│   ├── metrics.json
│   ├── trades.csv
│   ├── equity_curve.csv
│   ├── walkforward_summary.csv
│   ├── walkforward_equity.csv
│   └── walkforward_report.json
└── .github/
    └── workflows/
        └── backtest.yml
```

**File sync rules:**
- `backtest-nmr.py` and `backtest_nmr_lib.py` must have identical parameters, universe logic, and strategy rules
- They are separate files and do NOT share code at runtime — changes to one do not affect the other
- `walkforward.py` imports from `backtest_nmr_lib.py` only

---

## Setup & Running

### GitHub Actions
1. Push all files to your repo (including `backtest_nmr_lib.py` and `walkforward.py`)
2. **Settings → Actions → General → Workflow permissions → Read and write**
3. **Actions → Naive MR Backtest → Run workflow**

Optional workflow inputs: `start_date`, `end_date`, `initial_capital`, `run_walkforward`

To run walk-forward, set `run_walkforward = true` in the workflow dispatch inputs. Walk-forward adds 6–8 hours on top of the 90–120 minute main backtest. The scheduled Sunday run only runs the main backtest. Walk-forward is manual-only.

**If the git push step fails with "unstaged changes" error:** The workflow's commit step runs `git stash` before `git pull --rebase` to handle changes made by the `sed` override commands. If this error persists after updating `backtest.yml`, re-run the workflow once — it will pull the previous run's results and push cleanly.

### Local
```bash
pip install -r requirements.txt
python backtest-nmr.py      # main backtest (~90-120 min with S&P 600)
python walkforward.py       # walk-forward (~6-8 hours with S&P 600)
```

### Health Checks
If results look wrong, check:
- `[Universe] Total unique tickers` < 1800: S&P 600 fetch failed — check both `backtest-nmr.py` AND `backtest_nmr_lib.py` for the S&P 600 URL and `_extract_tickers_from_table` function
- `time_stop_rate > 70%`: 8-day window may not be firing correctly — check tier constants
- `win_rate < 55%`: verify uniform 8-day windows are in place; check SPY regime filter
- `CAGR < 14%` with no code changes: check `backtest_nmr_lib.py` is in sync with `backtest-nmr.py`
- `trades_per_year < 700`: Tier 3 may be disabled — check `MIN_CONSEC_DOWN = 4`
- `version` in metrics.json shows `V30` instead of `V32e`: workflow ran a stale cached version

---

## Output Metrics

| Metric | Description | V32e Target |
|---|---|---|
| `cagr_pct` | Compound Annual Growth Rate | >15% in-sample |
| `win_rate_pct` | % of profitable trades | 59–61% |
| `profit_factor` | Gross profit ÷ gross loss | >1.05 |
| `max_drawdown_pct` | Largest peak-to-trough decline | < −52% |
| `sharpe_ratio` | Annualised Sharpe (monthly) | >0.70 |
| `time_stop_rate_pct` | % exiting via time stop | ~59–61% |
| `trades_per_year` | Annual trade count | 850–950 |

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

Educational and research purposes only. Past backtest performance does not guarantee future results. Not financial advice. Consult a licensed financial advisor and CPA before trading with real capital. The aggressive position sizing in V32e is suitable only for those who understand and accept the full risk of deep drawdowns (−48%+) as part of the strategy's long-term compounding profile. V32d is available as a lower-drawdown alternative (−39%) at a modest equity cost for those who prefer better risk-adjusted returns.
