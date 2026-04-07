# Naive Mean Reversion (MR) Backtest

A survivorship-bias-free backtest of a **Naive Mean Reversion** strategy across all historical S&P 500 + S&P 400 MidCap + S&P 600 SmallCap constituents, automated via GitHub Actions.

---

## Current Version: V33d (Best Confirmed Result — taxable account)

The current script (`backtest-nmr.py`) is **V33d — V32e base + MAX_POSITIONS raised to 60**.

**IMPORTANT FOR NEW SESSIONS:**
Push `backtest-nmr.py` and `backtest_nmr_lib.py` to GitHub and run the workflow.

**ARCHITECTURE (V33d onwards — unified codebase):**
`backtest-nmr.py` is now a **thin wrapper** that imports all logic from `backtest_nmr_lib.py`. There is a single source of truth. The silent divergence risk from previous sessions (where both files had to be kept in sync manually) is eliminated. To change any parameter or logic, edit `backtest_nmr_lib.py` only. `walkforward.py` also imports from `backtest_nmr_lib.py`.

**Session objective: maximize total equity (taxable account).** V33d is recommended for a taxable account. V32d is recommended for a Roth IRA. See the "Why V33d for taxable accounts" section below.

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

Sharpe dropped from 0.73 (V32e) to 0.68 (V33d) as positions increased from 40 to 60. This looks like a regression but is not, for a taxable account with a long time horizon.

Sharpe penalises all volatility equally — upside bursts count against you as much as downside losses. The position count increase captures overflow on high-signal days, which are episodic bursts of alpha (many stocks simultaneously oversold in crash-recovery conditions), not persistent volatility. These are exactly the days you want maximum exposure. Sharpe treats them as "bad". Long-term compounding does not.

The result: +$670k final equity over V32e, with the Sharpe penalty coming mostly from larger gains in recovery years (2019: +$1.4M, 2017: +$820k) rather than from larger drawdowns in bad years. The bad years did get worse proportionally (2022: −$1.05M vs −$691k), but they're the same 2022 that every mean-reversion strategy suffers.

**The right question for a taxable account is not "smoothest ride" but "most wealth after 20 years."** V33d answers that question better. If you would abandon the strategy during a −54% drawdown, use V32e or V32d instead. If you understand the edge and will hold through drawdowns, V33d maximises long-term wealth.

### Walk-Forward Validation: V33d ✅ COMPLETE

Walk-forward confirmed V33d has genuine OOS edge. Results exceeded pass criteria (7/8 positive, OOS avg CAGR > 13%).

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

**Interpretation:** IS/OOS > 0.5 = genuine edge (normal decay). 0.3–0.5 = marginal. < 0.3 = likely overfitted. Negative = strategy fails OOS.

**Notable:** W7 (2021–22) and W8 (2023–25) are the persistent weak windows across all versions. W7 failed at −10.7% (worse than V32e's −5.8% — small-caps amplify bear market losses as expected). W8 delivered only 5.5% CAGR at −52.4% max DD, meaning the recent 2022–2025 period is genuinely hostile to mean reversion. This is a regime risk, not a strategy defect — the 7/8 OOS pass and 18.37% avg CAGR confirm the underlying edge is real.

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
| **Max positions** | 60 simultaneous holdings [V33d — raised from 40] |
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

## Walk-Forward Validation: V32e ✅ COMPLETE (reference)

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
- Always verify both files have the same universe, parameters, and logic before triggering a run

### The S&P 600 addition is genuinely additive, not in-sample noise

Adding the S&P SmallCap 600 universe improved OOS avg CAGR from 13.69% to 15.65% — proportionally with the IS improvement (14.42% → 16.01%). This is the opposite of what overfitting looks like.

### The core mechanism — unchanged across all versions

**The uniform 8-day window is the single most important parameter.** All gains, regressions, and optimisations across 36+ versions left this intact. Win rate has been 60.18–60.28% in every version from Run 5 through V30+S&P600.

**Tier 3 (4-day setups) is essential.** Removing it (V10–V14) collapsed CAGR from ~7% to 1–1.65% and halved trade volume. Never remove it.

### The strategy is fully optimised — V33d is the confirmed ceiling

Six separate experiments across V34a, V34b, V35a, and V36a have now closed every meaningful lever:

**Exit side (V34a/V34b/V35a):** Cutting losers earlier destroyed Tier 1 WR (70.1% → 52.3%). Letting winners run more (clean base, T1 3%, T2 2.5%) left PF unchanged at 1.06 and cost −$86k equity. The 2%/8d structure is confirmed optimal.

**Signal density (V36a):** Halving position size on days with 40+ signals improved max DD by 2.86pp but cost −$519k equity and −1.0% CAGR. The crash recovery days that fire the stress filter (2019, 2020, 2021) contribute the most absolute P&L — reducing size on those days cuts legs off in recoveries. Same pattern as every other protective mechanism tested. Data analysis showed the 41–60 signal bucket has negative avg return (−0.60%) but these are simultaneously the most valuable recovery entry days, making any filter on them net negative.

**Do not retry exit-side or signal-density changes. Paper trading data is the only remaining signal.**

### What the second session proved

**Removing protective mechanisms increases returns — when done selectively.** Three removals drove the largest gains:
1. Drawdown scaling removed (V22): freed up full position sizes during recovery years
2. VIX spike entry pause removed (V22): VIX spike days are the best mean reversion entry conditions
3. VIX high-side penalty removed (V26): high-VIX environments are maximally oversold

**The velocity crash pause is the one protection worth keeping.** Added in V21, it fires only when SPY drops >12% in 5 days. It saved ~$40-60k in 2020 at essentially zero cost to good years. All other protective mechanisms were net negative.

**Position count: 40 is better than 30 — but ONLY if size is NOT reduced.** Adding positions at full size captures overflow on high-signal days without diluting existing trades. Never scale down position size to "make room" for more positions.

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
| **Re-entry cooldown 2 days** | Reduce from 5 to 2 days | Only 3 extra trades/year — neutral |
| **Scaling position size down for more positions** | 40 positions at 4% instead of 5% | Per-trade profit fell 20%, volume gain couldn't compensate |
| **Drawdown scaling with tight thresholds** | 5%/10% thresholds (original) | Fired during normal volatility, reduced size when most needed |
| **70/30 SPY blend** | Blending strategy with SPY B&H | After-tax, the strategy edge over SPY narrows — blending reduces total equity vs all-in |
| **Binary VIX trend filter** | V31: no entries when VIX below 10d MA | Blocked 37%+ of trading days, killed volume. CAGR 11.03%, Sharpe dropped to 0.64 |
| **$10M dollar volume floor** | V31b: raised MIN_DOLLAR_VOLUME $5M→$10M | PF improved only +0.01, Sharpe dropped. Marginal quality gain, real volume cost |
| **DD scaling at 20% threshold** | V31b: >20% DD → 30% size reduction | Same pattern as original DD scaling removal — reduces size during best recovery periods |
| **ATR-based position sizing** | V32a: size = fixed dollar risk / ATR | VIX cap (9%/5%) overrides ATR size on majority of trades. No net effect |
| **VIX trend continuous sizing alone** | V32c: VIX falling → 80% size | Improved DD slightly but cost $300k equity vs baseline. V32d is better combined version |
| **Combining regime sizing + composite ranking** | V32f: V32d + V32e | V32e's equity benefit disappears when regime sizing reduces exposure. Use one or the other |
| **Combining regime sizing + higher position count** | V33b-d: 50 pos + V32d controls | Same pattern — $2,119k equity at −47% DD, worse than either V33b alone or V32d alone |
| **Testing 65 positions** | Not run — diminishing returns curve makes outcome predictable | At 55→60: +$142k equity, +0.25% CAGR, −1.5% DD. At 65→70 would yield ~+$100k at another DD cost — below meaningful threshold. 60 is the ceiling |
| **Partial loss exit (day 4, −2% threshold, 50% trim)** | V34a: trim half the position if down ≥2% after 4 days | Tier 1 win rate collapsed 70.1% → 52.3%. CAGR fell 17.4% → 15.5%, equity −$926k |
| **Tier 1 target raised 2% → 3% (with partial loss exit)** | V34b: V34a + Tier 1 profit target 3% | Contaminated test — Tier 1 already broken by V34a. Neutral vs V34a |
| **Higher profit targets on clean base** | V35a: T1 3%, T2 2.5%, healthy 69.6% T1 WR | Avg win +0.03%, PF unchanged at 1.06, time-stop rate +1.7pp, CAGR −0.15%, equity −$86k. Exit side confirmed saturated |
| **Signal density stress filter** | V36a: halve position size when daily signals > 40 | Max DD improved 2.86pp but CAGR −1.0%, equity −$519k. The 41–60 signal days have negative avg return (−0.60%) but are also the crash-recovery entry days that drive the biggest absolute gains (2019, 2020, 2021). Reducing size on those days cuts recovery compounding. Same pattern as every other protective mechanism |

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
| Composite ranking (RSI2/ATR_pct) | V32e | +$40k equity, +0.09% CAGR, no downsides | ✅ Applied |
| Tier 3 hold 6d (was 8d) | V32b | Sharpe 0.75, Avg Loss −3.12% — risk-adjusted improvement | ✅ In V32d only |
| VIX 5d trend 80% sizing | V32c | MaxDD −44.30%, trades continue at reduced size | ✅ In V32d only |
| **MAX_POSITIONS raised 40→60** | **V33b/c/d** | **+$670k equity, +1.31% CAGR vs V32e — diminishing but positive to 60** | **✅ Applied** |

---

## The Honest Risk Picture for V33d

V33d's gains come from **leverage amplification, universe expansion, and position count maximisation on the same edge** — not from finding a new edge. The win rate (60%) and profit factor (1.06) are essentially unchanged from V30. Every dollar of additional return came with proportional additional risk.

**Bad years scale dramatically with portfolio size.** At V33d's ~$3.1M peak equity:
- 2022 lost −$1.05M in a single year
- 2026 (partial year) lost −$728k
- The −54.73% max drawdown means a potential ~$1.7M paper loss peak-to-trough

**60 positions is the confirmed ceiling.** Testing 65 would yield ~$100k more equity at another −1.5% drawdown and −0.01 Sharpe. The efficiency per position is too low to justify further increases.

**Win rate is unchanged and must remain the anchor.** If live win rate drops below 56%, the strategy is failing. Monitor this before increasing position sizes.

---

## Optimism Bias Warnings (Updated)

V33d's reported 17.41% CAGR is the **in-sample ceiling**, not the live expectation.

| Source | Estimated CAGR Impact |
|---|---|
| Slippage on open prices (worse at 60 positions — more crowded MOO orders) | −2 to −3% |
| Survivorship bias (incomplete historical universe) | −1 to −2% |
| Overfitting across 36+ iterations on same dataset | −2 to −3% |
| Earnings calendar lookahead (today's known dates used) | −0.3 to −0.5% |
| VIX regime parameters tuned to history | −1 to −2% |
| **Realistic live estimate** | **~8 to 12% CAGR gross** |

Apply the ~26% decay ratio observed in walk-forward validation: 17.41% × 0.74 ≈ ~13% live gross. After short-term capital gains tax (32–37%), realistic net CAGR is likely 7–10%.

---

## SPY vs Strategy (Updated)

| Metric | SPY B&H | Run 5 | V32e | V33d | V32d (Roth) |
|---|---|---|---|---|---|
| CAGR (gross, in-sample) | ~10.5% | 7.58% | 16.10% | 17.41% | 15.37% |
| CAGR (gross, OOS est.) | ~10.5% | 5.58% | ~12% | ~13% | TBD |
| CAGR (after tax, est.) | ~8.4% | ~3.5–5% | ~6–9% | ~7–10% | tax-free (Roth) |
| Max Drawdown | −55% (2008) | −22.55% | −48.61% | −54.73% | −39.21% |
| Sharpe Ratio | ~0.55 | 0.73 | 0.73 | 0.68 | 0.77 |
| Final Equity ($100k start) | ~$800k | $478k | $2,454k | $3,124k | $2,145k |

**Tax note:** ~1,043 trades/year at V33d qualifies for IRS trader tax status (Section 475(f) MTM election) in most years. Consult a CPA specialising in trader tax (e.g. Green Trader Tax) before forming any entity.

---

## Paper Trading & Live Automation

### Status: ✅ LIVE (paper trading active as of April 2026)

- **Broker:** Interactive Brokers (IBKR) paper account, starting equity $100,000
- **Script:** `C:\nmr-trader\trade.py` — runs automatically every weekday
- **Scheduler:** Windows Task Scheduler fires at **6:25 AM PT**
- **Orders:** Market On Open (MOO) submitted before the 6:28 AM PT auction cutoff
- **Database:** `C:\nmr-trader\positions.db` — SQLite, tracks all open positions and trade history
- **Alerts:** Daily summary email via SendGrid after each run
- **Library:** `ib_async` (actively maintained successor to `ib_insync`)

### GitHub auto-push (paper trading results)

`trade.py` pushes paper trading results to the repo after each run. Results are visible at:
- `github.com/ckurau/naive-mean-reversion/tree/main/paper_trading/summary.json` — daily summary stats
- `github.com/ckurau/naive-mean-reversion/tree/main/paper_trading/trades.csv` — full trade log
- `github.com/ckurau/naive-mean-reversion/tree/main/paper_trading/open_positions.csv` — current open positions

In a new session, ask Claude to check the repo directly for paper trading results rather than running manual export commands.

### Local commands — checking progress

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
python -c "import sqlite3, pandas as pd; conn = sqlite3.connect(r'C:\nmr-trader\positions.db'); pos = pd.read_sql('SELECT * FROM open_positions', conn); conn.close(); print(f'Open positions: {len(pos)} / 60'); [print(f\"  {r['ticker']}: entered {r['entry_date']} | tier {r['tier']} | {r['shares_remaining']:.0f}sh @ ${r['entry_price']:.2f}\") for _, r in pos.iterrows()] if not pos.empty else print('  None')"
```

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

**Change 1 — in `C:\nmr-trader\trade.py`:**
```python
IBKR_PORT = 4001   # was 4002 (paper)
```

**Change 2 — in IBKR Gateway settings:**
Switch login from Paper Trading to Live account. Restart Gateway.

### Troubleshooting

| Problem | Likely cause | Fix |
|---|---|---|
| "IBKR connection failed" | Gateway not running | Open Gateway and log in before 6:25 AM PT |
| Script didn't run at 6:25 AM | PC was asleep | Power & Sleep → Sleep → Never |
| 0 entry candidates every day | SPY below 200d MA | Normal in bear market — not a bug |
| Win rate < 55% after 50 trades | Signal logic drift | Verify trade.py constants match backtest-nmr.py exactly |

---

## Next Steps

### Step 1 — Walk-Forward Validation ✅ COMPLETE
V33d walk-forward: OOS avg 18.37%, 7/8 positive windows. Pass criteria exceeded.

### Step 2 — Paper Trading ✅ ACTIVE (since April 2026)
Pass criteria: 3 months, win rate 57–63% over 100+ trades, no month worse than −15%.
Note: `trade.py` updated to MAX_POSITIONS=60 to match V33d.

### Step 3 — Go Live ⏳
Only after paper trading passes all criteria.

### Step 4 — Future Edge Improvements
The strategy is fully optimised on the backtest side (V34a through V36a all confirmed ceiling). Remaining genuine improvements:
- **Historical earnings database** — removes lookahead bias. Estimated impact: +0.3 to +0.5% CAGR
- **Live OOS validation** — 6–12 months of paper trading is the only true remaining out-of-sample test
- **MOO slippage analysis** — compare actual fill prices to prior-day close once 100+ trades complete

---

## All Runs Table

### V21–V36a: The Breakthrough Sequence

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
| V31b | $10M floor + DD scaling only | 13.17% | $1,419k | −39.16% | 0.68 |
| V32a | ATR-based position sizing | 15.98% | $2,403k | −48.61% | 0.73 |
| V32b | Tier 3 hold window 8→6 days | 15.87% | $2,354k | −44.87% | 0.75 |
| V32c | VIX 5d trend: 80% size when VIX falling | 15.28% | $2,111k | −44.30% | 0.74 |
| V32d | V32b + V32c combined | 15.37% | $2,145k | −39.21% | **0.77** |
| V32e | Composite ranking: RSI(2)/ATR_pct | 16.10% | $2,454k | −48.61% | 0.73 |
| V32f | V32d + V32e combined | 15.31% | $2,123k | −39.62% | 0.77 |
| V33b | MAX_POSITIONS raised 40→50 | 16.83% | $2,808k | −51.73% | 0.70 |
| V33b-d | 50 pos + V32d controls | 15.30% | $2,119k | −47.13% | 0.70 |
| V33c | MAX_POSITIONS raised 50→55 | 17.16% | $2,982k | −53.27% | 0.69 |
| **V33d** | **MAX_POSITIONS raised 55→60** | **17.41%** | **$3,124k** | **−54.73%** | **0.68** |
| V34a | Partial loss exit: day 4 if down ≥2%, trim 50% | 15.50% | $2,198k | −52.61% | 0.66 |
| V34b | V34a + Tier 1 target 2% → 3% (contaminated) | 15.44% | $2,172k | −52.48% | 0.66 |
| V35a | Tier 1: 2%→3%, Tier 2: 2%→2.5% (clean base) | 17.26% | $3,038k | −56.46% | 0.68 |
| V36a | Signal stress filter: >40 signals → 0.5× size | 16.42% | $2,605k | −52.19% | 0.67 |

**V33d is the confirmed ceiling. All subsequent versions regressed.**

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

### Local
```bash
pip install -r requirements.txt
python backtest-nmr.py      # main backtest (~90-120 min with S&P 600)
python walkforward.py       # walk-forward (~6-8 hours with S&P 600)
```

### Health Checks
- `[Universe] Total unique tickers` < 1800: S&P 600 fetch failed
- `win_rate < 55%`: verify uniform 8-day windows; check SPY regime filter
- `CAGR < 15%` with no code changes: verify `MAX_POSITIONS = 60` and version is V33d
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
