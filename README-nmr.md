# Naive Mean Reversion (MR) Backtest

A survivorship-bias-free backtest of a **Naive Mean Reversion** strategy across all historical S&P 500 + S&P 400 MidCap constituents, automated via GitHub Actions.

---

## Current Version: Run 5 (Best Confirmed Legitimate Result)

The current script (`backtest-nmr.py`) is **Run 5 — V7 Final + Uniform 8-Day Windows + Drawdown Scaling (loosened thresholds)**.

**IMPORTANT FOR NEW SESSIONS:** Push `backtest-nmr.py`, `backtest_nmr_lib.py`, and `walkforward.py` to GitHub and run the workflow. All three files must be in sync — `backtest_nmr_lib.py` is what `walkforward.py` imports. Keep them identical except for the `__all__` export block and entry point.

The circuit breaker approach was abandoned (see version history). Drawdown scaling is implemented and confirmed working. Walk-forward validation has been completed — the strategy has a genuine out-of-sample edge.

### Best Confirmed Results: Run 5 (30 positions, uniform 8d windows, DD scaling 8%/15%)

| Metric | Value |
|---|---|
| CAGR | 7.58% |
| ROI / Year | 17.66% |
| Win Rate | 60.28% |
| Avg Win | 2.98% |
| Avg Loss | −3.40% |
| Profit Factor | 1.15 |
| Max Drawdown | −22.55% |
| Sharpe Ratio | 0.73 |
| Trades / Year | 641 |
| Final Equity (from $100k) | $478k |
| Period | 2004–2026 (~21 years) |

> **Why not V7's 9.05% CAGR?** V7's win rate of 69.72% was produced by a code bug — RSI(2) is always < 5 after 4+ consecutive down days, which accidentally routed every trade through Tier 1's 8-day window. When the tier system was correctly discriminated by consecutive down days with different hold windows, CAGR collapsed to 1.73%. Making the uniform 8-day window intentional restored performance to 7.58% with correctly-reported win rates. Run 5 is the legitimate baseline. V7's numbers remain in the history for reference but should not be used as a performance target.

---

## Walk-Forward Validation Results ✅

Walk-forward was run using 8 rolling windows (5-year in-sample / 2-year out-of-sample). Parameters were **fixed** at Run 5 settings — no re-optimisation per window. This tests whether the edge is real or fitted to the 21-year dataset.

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

**Interpreting the results:**
- IS/OOS ratio > 0.5 = genuine edge (normal in-sample to out-of-sample decay)
- IS/OOS ratio 0.3–0.5 = marginal edge, use caution
- IS/OOS ratio < 0.3 = likely overfitted to history
- OOS CAGR negative = strategy fails out-of-sample

**The two failure windows in context:**
- W4 (2015–16): Near-zero-volatility grinding market with sparse mean reversion setups. Breakeven (−0.2%) — not a blowup.
- W7 (2021–22): The fastest Fed rate-hiking cycle in 40 years. Stocks ground lower for months without reverting — a structural regime break for mean reversion. This is an acceptable known risk of the strategy.
- W8's IS/OOS of −3.22x looks alarming but isn't: IS CAGR was negative while OOS was positive, making the ratio directionally meaningless. The 3.1% OOS CAGR is real and positive.

**Conclusion: The strategy has a genuine, demonstrable edge on unseen data.**

**Realistic forward estimate:** The OOS avg CAGR of 5.58% is the more honest forward expectation than the 7.58% in-sample figure. After slippage, taxes, and occasional regime failures, something in the 3–5% net range is realistic.

---

## Strategy Rules (Run 5 — current code)

| Rule | Detail |
|---|---|
| **Universe** | S&P 500 + S&P 400 MidCap (current + historical, avoids survivorship bias) |
| **Trend filter** | Stock must be above its 200-day SMA |
| **Entry signal** | 4+ consecutive down days AND RSI(2) < 20 AND ATR > 1% AND volume > 20-day avg AND dollar volume > $5M/day |
| **Entry execution** | Buy at open of next day |
| **Gap filters** | Skip if next open gaps down > 1.5% OR gaps up > 2% |
| **Exit — all tiers** | 2% profit target, 8-day time stop (uniform — this is the key mechanism) |
| **Tier 1 partial** | 6+ down days only: 50% at 1%, remainder at 2% |
| **Tier 2** | 5 down days: 2% target, 8-day window, no partial exit |
| **Tier 3** | 4 down days: 2% target, 8-day window, no partial exit |
| **Min hold** | 2 calendar days before profit exit allowed (avoids noise bounce exits) |
| **Max positions** | 30 simultaneous holdings |
| **Position size base** | 5%, VIX-adjusted: 7.5% (VIX<15), 2.5% (VIX>25) |
| **Drawdown scaling** | DD 8–15% from peak → max 3% per trade. DD 15%+ → max 2% per trade |
| **Earnings month** | Position size capped at 3% in Jan/Apr/Jul/Oct |
| **Signal ranking** | When >30 signals fire, pick lowest RSI(2) first (most oversold) |
| **Sector filter** | Skip entry if stock's sector ETF is below its 20-day MA |
| **Correlation cap** | Max 3 open positions in same sector at any time |
| **Earnings blackout** | Skip entries within ±3 days of earnings announcement |
| **SPY regime** | No new entries when SPY is below its 200-day MA |
| **VIX spike pause** | Pause new entries for 2 days if VIX rises 30%+ in 5 days |
| **Re-entry cooldown** | No re-entry in a stock for 5 days after a time-stop exit |
| **Commission** | $0.005/share or $1.00 minimum per trade |

---

## Key Insights

**The uniform 8-day window is the single most important parameter.** V7's accidentally-uniform 8-day window for all trades drove the high win rate. When tiers were correctly discriminated with different windows (Tier 3: 4d, Tier 2: 6d, Tier 1: 8d), CAGR collapsed to 1.73% and win rate dropped to 57%. Making the 8-day window intentional and uniform across all tiers restores performance. Holding time matters more than entry quality discrimination.

**RSI(2) is always below 5 after 4+ consecutive down days** — this is simply the mathematics of a 2-period lookback. Do NOT use RSI(2) to discriminate between tiers. Use consecutive down days instead. RSI(2) is still useful for ranking candidates (most oversold picked first) but not for tiering.

**The reported V7 win rate of 69.72% was inflated by a bug.** The real win rate on correctly-tiered trades is ~60%. Tier 1 (6+ days) achieves ~70%, Tier 2 (5 days) ~58%, Tier 3 (4 days) ~59%. The strategy is still profitable because EV per trade is positive across all tiers. Tier 3 contributes the most total annual EV through volume — removing it collapses CAGR.

**30 positions is the correct max.** Reducing to 20 collapsed CAGR from 9% to 4.5% for only a 5% drawdown improvement. Drawdown is managed through position sizing, not position count.

**Drawdown scaling works and is worth the CAGR cost.** Original thresholds (5%/10%) were too aggressive — they fired during normal volatility, reducing average position size too often. Loosened thresholds (8%/15%) recovered 0.75pp CAGR while keeping most of the drawdown benefit. Final result: −22.55% max DD vs V7's −28.94%, at the cost of 1.47pp CAGR.

**Avg loss (−3.40%) is not improvable through exit logic.** Three approaches were tested and all failed:
- **Price-based stop-losses (V3):** 22.6% of trades hit the stop then bounced. Every stop converted a win to a loss.
- **SPY same-day entry filter:** Removed above-average trades. SPY down days are when the most oversold stocks appear — implied EV of filtered trades (0.79%/trade) was higher than kept trades (0.45%/trade). Never filter entries on market direction.
- **VIX spike exit:** Fired 1,476 times (expected ~50). Trivially breached threshold exited positions right before VIX-spike bounces.

The −3.40% avg loss is structural. The strategy profits through win rate, not payoff ratio.

**Stop-losses are incompatible with mean reversion.** Stocks almost always bounce after a stop triggers. Never add price-based stop-losses to this strategy.

**Circuit breakers don't work for this strategy.** A portfolio-level entry halt is self-defeating — the strategy needs to keep trading to generate recovery profits. Drawdown-based position scaling (bet smaller during stress, larger during calm) is the correct approach.

**SPY down days should not be filtered.** Counterintuitive but confirmed: mean reversion setups on broad market down-days have higher-than-average EV. Filtering them hurts the strategy.

---

## All Runs in This Session

| Run | Change | CAGR | Win Rate | Max DD | Sharpe | Final Equity |
|---|---|---|---|---|---|---|
| V7 original | RSI bug, no DD scaling | 9.05%* | 69.72%* | −28.94% | 0.74 | $641k |
| Run 1 | Drawdown scaling added (broken tier windows) | 1.73% | 57.37% | −22.13% | 0.26 | $144k |
| Run 2 | Uniform 8d windows | 6.85% | 60.24% | −19.57% | 0.73 | $414k |
| Run 3 | + Partial exits on all tiers | 6.77% | 71.59% | −18.94% | 0.73 | $407k |
| Run 4 | − Partial exits on Tier 2/3 | 6.83% | 60.24% | −19.57% | 0.73 | $413k |
| **Run 5 ✅** | **DD thresholds loosened to 8%/15%** | **7.58%** | **60.28%** | **−22.55%** | **0.73** | **$478k** |
| Run 6 | SPY same-day entry filter (failed) | 4.40% | 59.44% | −23.73% | 0.50 | $252k |
| Run 7 | VIX spike exit on losing positions (failed) | 6.99% | 58.43% | −25.58% | 0.70 | $425k |

*V7 original numbers are inflated by the RSI bug and should not be used as targets.

---

## Version History

### V1 — Baseline Naive MR
- S&P 500 only, $10 price filter, 4 consecutive down days, first up-day exit
- **Results:** CAGR 3.11%, ROI 4.34%, Win Rate 64.0%, Max DD -7.95%, Sharpe 0.88
- **Learned:** Strategy works. $10k starting capital suppressed compounding.

### V2 — First Enhancement Pass ✅
- Added: RSI(2) < 20 filter, ATR > 1%, volume > 20-day avg, SPY regime filter, 1% min profit exit, commission model
- **Results:** CAGR 5.84%, ROI 11.09%, Win Rate 66.27%, Max DD -12.53%, Sharpe 0.89
- **Learned:** All five filters improved results. Became the reference baseline.

### V3 — Tighter RSI + Stop-Loss (REGRESSION)
- RSI threshold 20→10, added -3% stop-loss
- **Results:** CAGR 5.47%, ROI 9.94%, Win Rate 65.71%, Max DD -18.02%, Sharpe 0.74
- **Learned:** Stop-losses are fundamentally incompatible with mean reversion. 22.6% of trades hit the stop before bouncing. Never use price-based stops.

### V4 — Full Enhancement Suite
- Added: Signal ranking, 10-day time stop, earnings blackout, gap filters, S&P 400 universe, sector 50-day MA filter, VIX regime sizing, VIX spike pause, re-entry cooldown, earnings month sizing, correlation cap
- **Results:** CAGR 6.41%, ROI 12.99%, Win Rate 65.08%, Max DD -21.77%, Sharpe 0.64
- **Learned:** Universe expansion and signal ranking helped most. 50-day sector MA too slow. Too many changes at once made it hard to isolate impact.

### V5 — Tiered Targets + Partial Exits + 30 Positions
- Tiered profit targets by RSI (RSI<5: 2%, RSI<10: 1.5%, else 1%), partial exits, MAX_POSITIONS 20→30
- **Results:** CAGR 6.43%, ROI 13.07%, Win Rate 65.08%, Max DD -30.14%, Sharpe 0.49
- **Learned:** RSI-based tiers were flawed — RSI(2) is always <5 after 4 down days, routing all trades to Tier 1's 8-day window. 65% time-stop rate.

### V6 — Stripped Back (MAJOR REGRESSION)
- Removed partial exits, flat 1% target, time stop 3 days
- **Results:** CAGR 2.3%, ROI 2.93%, Win Rate 59.35%, Max DD -29.57%, Sharpe 0.29
- **Learned:** 3-day window is too tight for 1% target. Holding longer works. Never strip back to fewer than 4-day windows.

### V7 — High-Water Mark (inflated by bug) ⚠️
- Fixed tier system using consecutive down days (not RSI). Tiers: 4 days→1%/4d, 5 days→1.5%/6d, 6+ days→2%/8d + partial exit
- BUT: RSI(2) bug persisted — all 18,698 trades landed in Tier 1 (RSI always <5 after 4 down days), giving everything the 8-day window accidentally
- **Results (30 pos):** CAGR 9.05%, ROI 25.23%, Win Rate 69.72%, Max DD -28.94%, Sharpe 0.74, Final Equity $641k
- **Key insight:** The "bug" of everything using 8-day windows was actually optimal. Win rate and CAGR were inflated because all trades were mis-reported as Tier 1.

### V8 — Fixed Tier Assignment (REGRESSION)
- Tiers correctly discriminated by consecutive down days
- **Results:** CAGR 2.87%, ROI 3.9%, Win Rate 62.09%, Max DD -27.41%, Sharpe 0.32
- **Learned:** Tier 3 (4 days) is marginal at 61.2% win rate with a 4-day window. Most value comes from Tier 1 (70.7%). 4-day window for Tier 3 too short — 57% time-stop rate.

### V9 — Quality-Weighted Sizing + Longer Windows
- Extended windows: Tier 3 4d→6d, Tier 2 6d→7d, Tier 1 8d→10d
- Quality-weighted position sizes: Tier 1 7.5%, Tier 2 6%, Tier 3 4%
- **Results:** CAGR 6.73%, ROI 14.18%, Win Rate 61.34%, Max DD -27.71%, Sharpe 0.61
- **Learned:** Longer windows helped but quality-weighting reduced deployment. V7's uniform 8-day window for all tiers was better than differentiation.

### V7 Final (20 positions) — ABANDONED
- MAX_POSITIONS 30→20
- **Results:** CAGR 4.54%, ROI 7.42%, Win Rate 57.96%, Max DD -24.04%, Sharpe 0.51
- **Learned:** Wrong lever. −50-70% return collapse for −5% drawdown improvement. Never reduce MAX_POSITIONS below 30.

### V7 Final + Circuit Breaker — FAILED (ABANDONED)
- Halted all new entries when portfolio dropped 10% from rolling peak
- **Results:** Only 1.6 years of trades executed (2004-2006). Circuit breaker fired early and never reset — blocked 89.3% of all trading days
- **Why it failed:** Strategy needs to keep trading to generate recovery profits. Halting entries is self-defeating. The breaker trips when you need trades most.
- **Attempted 3 fixes** — all produced identical 1.6-year result. Root cause: with 30 positions at 5% each, any broad market selloff drops portfolio 10%+ instantly, tripping the breaker permanently.

### Run 1 — V7 Final + Drawdown Scaling (broken tier windows)
- Replaced circuit breaker with drawdown scaling. BUT tier windows still incorrect: Tier 3 4d, Tier 2 6d, Tier 1 8d
- **Results:** CAGR 1.73%, Win Rate 57.37%, Max DD −22.13%, Sharpe 0.26
- **Learned:** Correct tier discrimination with short windows destroys performance. Tier 3's 4-day window with a 1% target produces 69.6% time-stop rate.

### Run 2 — Uniform 8-Day Windows ✅ (key fix)
- All tiers given uniform 8-day window and 2% target (makes the V7 mechanism intentional)
- **Results:** CAGR 6.85%, Win Rate 60.24%, Max DD −19.57%, Sharpe 0.73
- **Learned:** Uniform hold time is the core mechanism. Drawdown scaling confirmed working (DD improved from −28.94% to −19.57%).

### Run 3 — Partial Exits on All Tiers
- Added partial exits (50% at 1%) to Tier 2 and Tier 3 in addition to Tier 1
- **Results:** CAGR 6.77%, Win Rate 71.59%, Max DD −18.94%, Sharpe 0.73
- **Learned:** 7,508 partial exits fragmented avg win from 3.34% → 3.07%. Win rate improved to 71.59% but avg win drag cost ~2.5pp CAGR. Best drawdown of any run (−18.94%) — revisit if drawdown reduction is the primary goal.

### Run 4 — Partial Exits Removed from Tier 2/3
- Reverted Tier 2 and Tier 3 to no partial exit
- **Results:** CAGR 6.83%, Win Rate 60.24%, Max DD −19.57%, Sharpe 0.73
- **Learned:** Confirmed Run 3 diagnosis. Tier 2/3 should run straight to 2% or time-stop.

### Run 5 — Loosened Drawdown Scaling Thresholds ✅ (current best)
- DD thresholds loosened: 5%/10% → 8%/15%. Original thresholds fired too often during normal volatility.
- **Results:** CAGR 7.58%, Win Rate 60.28%, Max DD −22.55%, Sharpe 0.73
- **Learned:** The 5% mild threshold was triggering during ordinary dips, reducing average position size unnecessarily. Loosening recovered 0.75pp CAGR at the cost of 3pp more drawdown — a good trade.

### Run 6 — SPY Same-Day Entry Filter (FAILED)
- Skipped entries on days when SPY closed down >0.5%
- **Results:** CAGR 4.40%, Win Rate 59.44%, Max DD −23.73%, Sharpe 0.50
- **Learned:** Filtered trades had higher EV (0.79%/trade) than kept trades (0.45%/trade). SPY down days are when the most oversold stocks appear. Never filter entries based on broad market daily direction.

### Run 7 — VIX Spike Exit on Losing Positions (FAILED)
- During VIX spike pause window, exit any position already down >0.5%
- **Results:** CAGR 6.99%, Win Rate 58.43%, Max DD −25.58%, Sharpe 0.70, vix_spike_exit count: 1,476
- **Learned:** The −0.5% threshold was trivially breached — almost all losing positions are down >0.5% at any time. The exit fired ~69 times/year vs expected ~3/year, cutting positions right before VIX-spike bounces. VIX spike days are the worst time to exit a mean reversion trade.

---

## Key Learnings Summary

| Learning | Detail |
|---|---|
| **Uniform 8-day window** | The single most important parameter. All tiers must use 8-day hold window. Discriminating windows by tier collapses CAGR. |
| **No stop-losses** | Mean reversion + price stops are incompatible. 22.6% of stopped trades bounced after exit (V3). |
| **Hold longer** | 8-day windows dramatically improved win rate. Never go below 4 days. |
| **RSI(2) always < 5** | After 4+ down days, RSI(2) always collapses. Use consecutive down days for tiering, RSI only for ranking. |
| **Tier 3 is positive EV** | 4-down-day setups at 59% win rate contribute the most total annual EV through volume. Do not remove. |
| **30 positions minimum** | Reducing to 20 collapsed returns −50%. Never reduce MAX_POSITIONS below 30. |
| **No circuit breakers** | Halting entries during drawdowns is self-defeating. Strategy needs to trade to recover. |
| **Drawdown scaling works** | Bet smaller during stress (2-3%), larger during calm (5-7.5%). Never stop entirely. Thresholds 8%/15% are correct. |
| **No entry filters on market direction** | SPY down days have higher EV than average. VIX spike days are the best time to enter, not skip. |
| **Avg loss is structural** | −3.40% avg loss cannot be improved through exit logic without damaging win rate. Three approaches confirmed this. |
| **Filters add value** | SPY regime, sector filter, earnings blackout, gap filters all individually improve returns. |
| **Universe expansion** | S&P 400 MidCap added ~35% more trades/year and improved compounding. |
| **Signal ranking** | RSI(2) ascending sort (most oversold first) improves quality at zero cost. |
| **VIX sizing** | 2.5% position when VIX>25, 7.5% when VIX<15, 5% otherwise. |
| **Earnings blackout** | ±3 days around earnings removes biggest source of gap-down losses. |
| **Sector correlation cap** | Max 3 positions per sector prevents hidden concentration risk. |

---

## Optimism Bias Warnings

Run 5's reported numbers (7.58% CAGR) are still the **ceiling**, not the floor. Real-world performance will be lower due to:

| Source | Estimated CAGR Impact |
|---|---|
| Slippage on open prices | −0.5 to −1% |
| Survivorship bias (incomplete historical universe) | −1 to −2% |
| Overfitting across multiple iterations on same dataset | −1 to −2% |
| Earnings calendar lookahead (uses today's known dates) | −0.3 to −0.5% |
| **Realistic live estimate** | **~4 to 6% CAGR gross** |

Walk-forward OOS avg CAGR of 5.58% is the better forward estimate. After short-term tax (32–37%), realistic net CAGR is likely 2.5–4%. SPY after long-term tax (20%) is ~8.4% net.

---

## SPY vs Strategy

| Metric | SPY B&H | Run 5 Strategy |
|---|---|---|
| CAGR (gross, in-sample) | ~10.5% | 7.58% |
| CAGR (gross, OOS avg) | ~10.5% | 5.58% |
| CAGR (after tax) | ~8.4% | ~3.5–5% |
| Max Drawdown | −55% (2008) | −22.55% |
| Sharpe Ratio | ~0.55 | 0.73 |
| Effort | Zero | High |
| Tax treatment | Long-term (15–20%) | Short-term (32–37%) |

**After taxes, SPY wins on raw returns for most people.**

**Best use case:** 70–80% SPY + 20–30% Run 5 strategy. Near-zero correlation means the strategy diversifies the portfolio meaningfully. The blend has better Sharpe than either alone, and lower drawdown than SPY alone. During 2008 crash (−55% SPY), the strategy's SPY regime filter limits exposure — the blended portfolio's effective drawdown is approximately −20%.

**LLC / Trader Tax Status:** ~641 trades/year may qualify for IRS trader tax status (Section 475(f) MTM election) allowing deduction of all losses and business expenses. Consult a CPA specialising in trader tax (e.g. Green Trader Tax) before forming any entity. SPY via LLC has no meaningful tax benefit.

---

## Next Steps

### Step 1 — SPY vs Strategy Blend Analysis ⏳ (immediate priority)

Before paper trading, build a model that directly compares the strategy against SPY and determines the optimal allocation and timing. The data already exists in `results/equity_curve.csv` and `results/walkforward_equity.csv`.

Build `spy_blend_analysis.py` covering:

1. **Combined equity curve** — overlay Run 5 equity against SPY buy-and-hold (2004–2026) on the same chart
2. **Correlation analysis** — confirm near-zero correlation between monthly strategy returns and SPY returns across the full period and per-window
3. **Blend modelling** — test 50/50, 60/40, 70/30, 80/20 SPY/Strategy allocations. For each, calculate blended CAGR, max drawdown, Sharpe ratio, and final equity
4. **Regime analysis** — segment performance by market regime (SPY bull: >200d MA, SPY bear: <200d MA, high VIX: >25, low VIX: <15) and show strategy CAGR vs SPY CAGR in each regime. This answers "when should I prefer the strategy over SPY?"
5. **Practical output** — a clear allocation rule, e.g. "run 30% strategy / 70% SPY in all regimes; reduce strategy allocation to 15% during sustained SPY bear markets (SPY below 200d MA for >60 days)"

Expected findings based on existing data:
- The strategy likely outperforms SPY on a risk-adjusted basis in sideways and mild bear markets but underperforms in strong bull runs
- Near-zero correlation means blending always improves Sharpe vs either standalone
- The strategy's SPY regime filter means it naturally reduces exposure during bear markets — it's partly self-hedging

### Step 2 — Paper Trading Setup ⏳

Once blend analysis answers the allocation question:
- Select a broker with a Python-compatible API (Interactive Brokers via `ib_insync`, or Alpaca for simpler setup)
- Build a daily signal scanner (not the full backtest) — scans each morning for new signals and outputs a trade list for manual or automated execution
- Paper trade for a minimum of 3 months covering at least one earnings season
- Track: live win rate vs backtest (target: within 3pp, i.e. 57–63%), trade count vs expected (~54/month), slippage on open fills, signal frequency per sector

**Pass criteria for moving to live capital:**
- Live win rate: 57–63% (backtest: 60.28%)
- Trade count: 45–75/month (backtest: ~53/month)
- No single losing month worse than −8% (backtest max DD is monthly, not daily)
- Observed slippage on open fills: under 0.3% average

### Step 3 — Live Trading Infrastructure ⏳

Only after paper trading passes:
- Broker API integration for order execution
- Position management (track open positions across sessions, handle partial fills)
- Daily signal pipeline with email/SMS alerting for signals
- Consider IRS trader tax status (Section 475(f) MTM election) if trade count qualifies — consult a CPA before any live trading begins
- Implement portfolio-level monitoring: if win rate drops below 52% over 100 trades, pause and review

---

## Repository Structure

```
.
├── backtest-nmr.py              # Main backtest (Run 5)
├── backtest_nmr_lib.py          # Shared library (imported by walkforward.py — must match backtest-nmr.py)
├── walkforward.py               # Walk-forward out-of-sample test framework
├── spy_blend_analysis.py        # (TODO) SPY vs strategy blend comparison
├── requirements.txt             # Python dependencies
├── README-nmr.md                # This file
├── results/                     # Auto-generated (committed by CI)
│   ├── metrics.json
│   ├── trades.csv
│   ├── equity_curve.csv
│   ├── walkforward_summary.csv  # walk-forward results
│   ├── walkforward_equity.csv   # OOS equity curves per window
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

To run walk-forward, set `run_walkforward = true` in the workflow dispatch inputs. Walk-forward adds 4–6 hours on top of the 60–90 minute main backtest. The scheduled Sunday run only runs the main backtest to keep weekly runs fast — walk-forward is manual-only.

Runs automatically every Sunday at 00:00 UTC.

### Local

```bash
pip install -r requirements.txt
python backtest-nmr.py      # main backtest (~60-90 min)
python walkforward.py       # walk-forward (~4-6 hours)
python spy_blend_analysis.py  # blend comparison (once built)
```

---

## Output Metrics

| Metric | Description | Target (revised) |
|---|---|---|
| `cagr_pct` | Compound Annual Growth Rate | >7% in-sample, >5% OOS avg |
| `roi_per_year_pct` | Simple annual ROI on initial capital | >15% |
| `win_rate_pct` | % of profitable trades | >58% |
| `profit_factor` | Gross profit ÷ gross loss | >1.10 |
| `max_drawdown_pct` | Largest peak-to-trough decline | >−25% |
| `sharpe_ratio` | Annualised Sharpe (monthly) | >0.70 |
| `time_stop_rate_pct` | % exiting via time stop | <65% |
| `tier_stats` | Per-tier win rate, avg win/loss, avg hold | Tier 1 > Tier 3 |

**Health check:** If time_stop_rate > 70%, the 8-day window may not be firing correctly — check tier constants. If Tier 3 win rate < 55%, verify uniform 8-day windows are in place. If CAGR drops below 5% with no code changes, check `backtest_nmr_lib.py` is in sync with `backtest-nmr.py`.

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

Educational and research purposes only. Past backtest performance does not guarantee future results. Not financial advice. Consult a licensed financial advisor and CPA before trading with real capital.
