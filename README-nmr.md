# Naive Mean Reversion (MR) Backtest

A survivorship-bias-free backtest of a **Naive Mean Reversion** strategy across all historical S&P 500 + S&P 400 MidCap constituents, automated via GitHub Actions.

---

## Current Version: V30 (Best Confirmed Result)

The current script (`backtest-nmr.py`) is **V30 — Run 5 base + full VIX sizing optimisation + 40 positions**.

**IMPORTANT FOR NEW SESSIONS:** Push `backtest-nmr.py`, `backtest_nmr_lib.py`, and `walkforward.py` to GitHub and run the workflow. All three files must be in sync — `backtest_nmr_lib.py` is what `walkforward.py` imports. Keep them identical except for the `__all__` export block and entry point.

**Session objective: maximize total equity.** All optimisation decisions in V10–V30 were made on this basis. If your objective changes (e.g. prioritising drawdown protection or Sharpe), re-evaluate the VIX sizing aggressiveness — V16 or V22 are better starting points for capital-preservation goals.

### Best Confirmed Results: V30

| Metric | Value |
|---|---|
| CAGR | 14.42% |
| ROI / Year | 79.16% |
| Win Rate | 60.18% |
| Avg Win | 2.98% |
| Avg Loss | −3.44% |
| Profit Factor | 1.10 |
| Max Drawdown | −39.37% |
| Sharpe Ratio | 0.72 |
| Trades / Year | 752 |
| Final Equity (from $100k) | $1,797,462 |
| Period | 2004–2026 (~21 years) |

### Walk-Forward Validation — PENDING on V30

Walk-forward was previously validated on Run 5. V30 walk-forward is next to run. To run it, trigger the workflow with `run_walkforward = true`. See the Walk-Forward section below for Run 5 results as the baseline reference.

---

## V30 Strategy Rules (current code)

| Rule | Detail |
|---|---|
| **Universe** | S&P 500 + S&P 400 MidCap (current + historical, avoids survivorship bias) |
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
| **Position size** | VIX < 20 → 9%, VIX 20–25 → 7.5%, VIX ≥ 25 → 5% base |
| **VIX high-side penalty** | REMOVED — high-VIX environments are best for mean reversion |
| **Drawdown scaling** | REMOVED — costs too much in recovery years |
| **VIX spike pause** | REMOVED — VIX spike days are best entry conditions |
| **Velocity crash pause** | SPY 5-day return < −12% → pause all entries for 5 days |
| **Earnings month cap** | Position size capped at 2.4% in Jan/Apr/Jul/Oct |
| **Signal ranking** | Lowest RSI(2) first (most oversold) |
| **Sector filter** | Skip entry if stock's sector ETF is below its 20-day MA |
| **Correlation cap** | Max 3 open positions in same sector |
| **Earnings blackout** | Skip entries within ±3 days of earnings announcement |
| **SPY regime** | No new entries when SPY is below its 200-day MA |
| **Re-entry cooldown** | No re-entry in a stock for 5 days after a time-stop exit |
| **Commission** | $0.005/share or $0.35 minimum per trade |

---

## Walk-Forward Validation Results (Run 5 baseline) ✅

Walk-forward was run using 8 rolling windows (5-year in-sample / 2-year out-of-sample). Parameters fixed at Run 5 settings. V30 walk-forward is pending.

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

**Failure windows in context:**
- W4 (2015–16): Near-zero-volatility grinding market. Breakeven (−0.2%) — not a blowup.
- W7 (2021–22): Fastest Fed rate-hiking cycle in 40 years. Acceptable known risk.
- W8's IS/OOS of −3.22x is misleading: IS CAGR was negative while OOS was positive. The 3.1% OOS CAGR is real.

**Conclusion: The strategy has a genuine, demonstrable out-of-sample edge.**

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
| **V30** | **V28 + V29 combined: VIX_LOW=25 + 9% boost** | **14.42%** | **$1,797k** | **−39.4%** | **0.72** | **Current best — 18× from $100k** |

---

## Key Insights (Updated)

### V7's $641k is not a reproducible target from a fresh $100k start

The README and version history reference V7's $641k final equity. This number reflected a specific compounding path — the 2012-2013 gains happened when the portfolio had already grown large through earlier years. Multiple direct attempts to reproduce it from a $100k start (V19, V20) produced $320-330k. The $641k should not be used as a benchmark. V30's $1,797k is the legitimate current best from a confirmed $100k starting position.

### The core mechanism — unchanged across all versions

**The uniform 8-day window is the single most important parameter.** All gains, regressions, and optimisations across 30 versions left this intact. Win rate has been 60.18–60.28% in every version from Run 5 through V30. The underlying edge has not changed — only the leverage applied to it.

**RSI(2) is always below 5 after 4+ consecutive down days.** Do not use RSI(2) to discriminate between tiers. Use consecutive down days instead. RSI(2) is only useful for ranking candidates (most oversold first).

**Tier 3 (4-day setups) is essential.** Removing it (V10–V14) collapsed CAGR from ~7% to 1–1.65% and halved trade volume. Every version without Tier 3 underperformed dramatically. Never remove it.

### What the second session proved

**Removing protective mechanisms increases returns — when done selectively.** Three removals drove the largest gains:
1. Drawdown scaling removed (V22): freed up full position sizes during recovery years — 2013 and 2017 immediately jumped
2. VIX spike entry pause removed (V22): VIX spike days are the best mean reversion entry conditions, not the worst
3. VIX high-side penalty removed (V26): high-VIX environments are maximally oversold — undersizing them was wrong

**The VIX_LOW lever had far more room than expected.** Raising VIX_LOW from 15 (Run 5) to 25 (V28) was the dominant source of gains in the second session. Years like 2020-2021 where VIX sat in the 20-25 range during recovery got full-size positions instead of reduced ones. The lever worked because mean reversion edge is actually strongest in moderately elevated VIX environments.

**The velocity crash pause is the one protection worth keeping.** Added in V21, it fires only when SPY drops >12% in 5 days (March 2020-level events). It saved ~$40-60k in 2020 at essentially zero cost to good years. All other protective mechanisms were net negative.

**Position count: 40 is better than 30 — but ONLY if size is NOT reduced.** V23 tested 40 positions at 4% size (scaled to maintain "similar exposure") and regressed. V24 tested 40 positions at 5% size (unchanged) and was a major improvement. The lesson: adding positions at full size captures overflow on high-signal days without diluting existing trades. Never scale down position size to "make room" for more positions.

**VIX sizing is a compounding amplifier, not a risk tool.** The VIX high-side penalty (VIX > 25 → 2.5%) was removed because it undersized positions during the periods of strongest mean reversion edge. VIX above 25 means stocks are maximally oversold — exactly when you want full size. The velocity crash pause handles genuine extreme events (VIX > 50 territory in March 2020); the VIX sizing regime doesn't need to.

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

### What works — confirmed positive contributions

| Addition | First Tested | Effect | Status in V30 |
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
| VIX_LOW raised to 25 | V28 | Recovery years get full 7.5% size | ✅ Applied |
| VIX high-side penalty removed | V26 | High-VIX = strongest MR conditions | ✅ Applied |
| 9% boost for VIX < 20 | V30 | Bull years get larger positions | ✅ Applied |

---

## The Honest Risk Picture for V30

V30's gains come entirely from **leverage amplification on the same edge**, not from finding a better edge. This has important implications:

**The Sharpe ratio has been stable.** Run 5: 0.73. V30: 0.72. Despite nearly 4× the final equity, the risk-adjusted return is unchanged. Every dollar of additional return came with proportional additional risk.

**Bad years scale with portfolio size.** At V30's ~$1.8M peak equity:
- 2022 lost −$342k (a single year)
- 2018 lost −$318k (a single year)
- The −39.4% max drawdown means a potential ~$700k paper loss peak-to-trough

**The VIX sizing parameters are now very aggressive.** VIX < 20 → 9% positions, VIX 20-25 → 7.5%. At 40 positions, theoretical maximum notional exposure is 360% of portfolio (though average simultaneous open positions is 8-15 in practice). This is a leveraged approach in all but name.

**Win rate is unchanged and must remain the anchor.** If live win rate drops below 56%, the strategy is failing. Monitor this before increasing position sizes.

---

## Optimism Bias Warnings (Updated)

V30's reported 14.42% CAGR is the **in-sample ceiling**, not the live expectation.

| Source | Estimated CAGR Impact |
|---|---|
| Slippage on open prices | −1 to −2% (larger at V30's position sizes) |
| Survivorship bias (incomplete historical universe) | −1 to −2% |
| Overfitting across 30+ iterations on same dataset | −2 to −3% |
| Earnings calendar lookahead (today's known dates used) | −0.3 to −0.5% |
| VIX regime parameters tuned to history | −1 to −2% |
| **Realistic live estimate** | **~6 to 9% CAGR gross** |

The Run 5 walk-forward showed 5.58% OOS avg CAGR vs 7.58% in-sample — roughly a 26% decay. Applying that same decay ratio to V30's 14.42% suggests ~10-11% live. But V30 has significantly more parameter tuning than Run 5, so the decay may be larger. After short-term capital gains tax (32–37%), realistic net CAGR is likely 4–7%.

---

## SPY vs Strategy (Updated)

| Metric | SPY B&H | Run 5 | V30 |
|---|---|---|---|
| CAGR (gross, in-sample) | ~10.5% | 7.58% | 14.42% |
| CAGR (gross, OOS estimate) | ~10.5% | 5.58% | ~8-11% |
| CAGR (after tax) | ~8.4% | ~3.5–5% | ~5–9% |
| Max Drawdown | −55% (2008) | −22.55% | −39.37% |
| Sharpe Ratio | ~0.55 | 0.73 | 0.72 |
| Worst single year | −55% (2008) | ~−25% | −$342k (2022) |

**SPY comparison at V30:** V30's aggressive VIX sizing means its drawdown profile is now closer to SPY's than Run 5's. The primary advantage is diversification (near-zero correlation with SPY) rather than the drawdown protection that Run 5 offered.

**Tax note:** ~752 trades/year qualifies for IRS trader tax status (Section 475(f) MTM election) in most years. Consult a CPA specialising in trader tax (e.g. Green Trader Tax) before forming any entity.

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

### V21–V30: The Breakthrough Sequence

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
| **V30** | **V28 + V29 combined** | **14.42%** | **$1,797k** | **−39.4%** | **0.72** |

---

## Next Steps

### Step 1 — Walk-Forward Validation on V30 ⏳ (immediate priority)

Run `walkforward.py` with V30's parameters to get out-of-sample validation. Expected finding: OOS CAGR will likely be 8-11% (the same ~26% IS/OOS decay ratio as Run 5 applied to V30's 14.42%). If OOS CAGR is below 7%, the additional parameters (VIX thresholds, position sizing) are overfitted to history and V26 or V28 should be used instead.

To run: trigger the workflow with `run_walkforward = true`. Takes 4-6 hours.

### Step 2 — Paper Trading Setup ⏳

Once walk-forward confirms OOS edge:
- Select a broker with a Python-compatible API (Interactive Brokers via `ib_insync`, or Alpaca)
- Build a daily signal scanner — scans each morning for new signals, outputs a trade list
- Paper trade for minimum 3 months covering at least one earnings season

**Pass criteria for moving to live capital:**
- Live win rate: 57–63% (backtest: 60.18%)
- Trade count: 55–80/month (backtest: ~63/month at V30)
- Observed slippage on open fills: under 0.5% average (higher tolerance at V30's sizes)
- No single losing month worse than −12% (V30's drawdown is deeper than Run 5's)

### Step 3 — Live Trading Infrastructure ⏳

Only after paper trading passes:
- Broker API integration for order execution
- Position management across sessions, handle partial fills
- Daily signal pipeline with email/SMS alerting
- Portfolio-level monitoring: if live win rate drops below 55% over 100 trades, pause and review

### Step 4 — Future Edge Improvements (not more leverage)

The remaining improvements that would genuinely improve the strategy edge (not just sizing) are:
- **Historical earnings database** — removes the lookahead bias in the current earnings calendar (yfinance uses today's known dates, not historical)
- **S&P 600 SmallCap universe** — adds ~600 more names with stronger mean reversion characteristics
- **Live OOS validation** — 6-12 months of paper trading is the only true out-of-sample test

---

## Repository Structure

```
.
├── backtest-nmr.py          # Main backtest (V30 — current)
├── backtest_nmr_lib.py      # Shared library (imported by walkforward.py — must match)
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

---

## Setup & Running

### GitHub Actions

1. Push all files to your repo (including `backtest_nmr_lib.py` and `walkforward.py`)
2. **Settings → Actions → General → Workflow permissions → Read and write**
3. **Actions → Naive MR Backtest → Run workflow**

Optional workflow inputs: `start_date`, `end_date`, `initial_capital`, `run_walkforward`

To run walk-forward, set `run_walkforward = true` in the workflow dispatch inputs. Walk-forward adds 4–6 hours on top of the 60–90 minute main backtest.

The scheduled Sunday run only runs the main backtest. Walk-forward is manual-only.

### Local

```bash
pip install -r requirements.txt
python backtest-nmr.py    # main backtest (~60-90 min)
python walkforward.py     # walk-forward (~4-6 hours)
```

### Health Checks

If results look wrong, check:
- `time_stop_rate > 70%`: 8-day window may not be firing correctly — check tier constants
- `win_rate < 55%`: verify uniform 8-day windows are in place; check SPY regime filter
- `CAGR < 8%` with no code changes: check `backtest_nmr_lib.py` is in sync with `backtest-nmr.py`
- `trades_per_year < 600`: Tier 3 may be disabled — check `MIN_CONSEC_DOWN = 4`
- `version` in metrics.json: must match what you pushed — if stale, the workflow ran old code

---

## Output Metrics

| Metric | Description | V30 Target |
|---|---|---|
| `cagr_pct` | Compound Annual Growth Rate | >12% in-sample |
| `win_rate_pct` | % of profitable trades | 59–61% |
| `profit_factor` | Gross profit ÷ gross loss | >1.08 |
| `max_drawdown_pct` | Largest peak-to-trough decline | < −42% |
| `sharpe_ratio` | Annualised Sharpe (monthly) | >0.68 |
| `time_stop_rate_pct` | % exiting via time stop | ~60% |
| `trades_per_year` | Annual trade count | 700–800 |

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

Educational and research purposes only. Past backtest performance does not guarantee future results. Not financial advice. Consult a licensed financial advisor and CPA before trading with real capital. The aggressive position sizing in V30 is suitable only for those who understand and accept the full risk of deep drawdowns (−39%+) as part of the strategy's long-term compounding profile.
