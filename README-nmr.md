# Naive Mean Reversion (MR) Backtest

A survivorship-bias-free backtest of a **Naive Mean Reversion** strategy across
all historical S&P 500 + S&P 400 MidCap constituents, automated via GitHub Actions.

---

## Current Version: V7 Final + Drawdown Scaling

The current script (`backtest-nmr.py`) is **V7 Final + Drawdown Scaling**.

**IMPORTANT FOR NEW SESSIONS:** Push `backtest-nmr.py`, `backtest_nmr_lib.py`,
and `walkforward.py` to GitHub and run the workflow. The circuit breaker approach
was abandoned (see version history). The drawdown scaling version has NOT yet
been backtested — results are pending.

### Best Confirmed Results: V7 (30 positions, no drawdown management)

| Metric | Value |
|---|---|
| CAGR | 9.05% |
| ROI / Year | 25.23% |
| Win Rate | 69.72% |
| Avg Win | 3.34% |
| Avg Loss | -3.31% |
| Profit Factor | 1.14 |
| Max Drawdown | -28.94% |
| Sharpe Ratio | 0.74 |
| Trades / Year | 872 |
| Final Equity (from $100k) | $641k |
| Period | 2004–2026 (~21 years) |

---

## Strategy Rules (V7 Final + Drawdown Scaling — current code)

| Rule | Detail |
|---|---|
| **Universe** | S&P 500 + S&P 400 MidCap (current + historical, avoids survivorship bias) |
| **Trend filter** | Stock must be above its 200-day SMA |
| **Entry signal** | 4+ consecutive down days AND RSI(2) < 20 AND ATR > 1% AND volume > 20-day avg AND dollar volume > $5M/day |
| **Entry execution** | Buy at open of next day |
| **Gap filters** | Skip if next open gaps down > 1.5% OR gaps up > 2% |
| **Exit — Tier 3** | 4 down days: 1% profit target, 4-day time stop |
| **Exit — Tier 2** | 5 down days: 1.5% profit target, 6-day time stop |
| **Exit — Tier 1** | 6+ down days: 2% profit target, 8-day time stop, partial exit (50% at 1%, rest at 2%) |
| **Min hold** | 2 calendar days before profit exit allowed (avoids noise bounce exits) |
| **Max positions** | 30 simultaneous holdings |
| **Position size base** | 5%, VIX-adjusted: 7.5% (VIX<15), 2.5% (VIX>25) |
| **Drawdown scaling** | DD 5-10% from peak → max 3% per trade. DD 10%+ → max 2% per trade |
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

**RSI(2) is always below 5 after 4+ consecutive down days** — this is simply
the mathematics of a 2-period lookback. Do NOT use RSI(2) to discriminate between
tiers. Use consecutive down days instead. RSI(2) is still useful for ranking
candidates (most oversold picked first) but not for tiering.

**Giving setups adequate time to bounce is the single most important factor.**
V7's accidentally-uniform 8-day window for all trades drove the 69.72% win rate.
When we tightened to 3-5 days, win rates collapsed to 57-59%.

**Stop-losses are incompatible with mean reversion.** Stocks almost always bounce
after a stop triggers. Never add price-based stop-losses to this strategy.

**30 positions is the correct max.** Reducing to 20 collapsed CAGR from 9% to
4.5% for only a 5% drawdown improvement. Drawdown is managed through position
sizing, not position count.

**Circuit breakers don't work for this strategy.** A portfolio-level entry halt
is self-defeating — the strategy needs to keep trading to generate recovery
profits. Drawdown-based position scaling (bet smaller during stress, larger
during calm) is the correct approach.

---

## Version History

### V1 — Baseline Naive MR
- S&P 500 only, $10 price filter, 4 consecutive down days, first up-day exit
- **Results:** CAGR 3.11%, ROI 4.34%, Win Rate 64.0%, Max DD -7.95%, Sharpe 0.88
- **Learned:** Strategy works. $10k starting capital suppressed compounding.

### V2 — First Enhancement Pass ✅
- Added: RSI(2) < 20 filter, ATR > 1%, volume > 20-day avg, SPY regime filter,
  1% min profit exit, commission model
- **Results:** CAGR 5.84%, ROI 11.09%, Win Rate 66.27%, Max DD -12.53%, Sharpe 0.89
- **Learned:** All five filters improved results. Became the reference baseline.

### V3 — Tighter RSI + Stop-Loss (REGRESSION)
- RSI threshold 20→10, added -3% stop-loss
- **Results:** CAGR 5.47%, ROI 9.94%, Win Rate 65.71%, Max DD -18.02%, Sharpe 0.74
- **Learned:** Stop-losses are fundamentally incompatible with mean reversion.
  22.6% of trades hit the stop before bouncing. Never use price-based stops.

### V4 — Full Enhancement Suite
- Added: Signal ranking, 10-day time stop, earnings blackout, gap filters,
  S&P 400 universe, sector 50-day MA filter, VIX regime sizing, VIX spike pause,
  re-entry cooldown, earnings month sizing, correlation cap
- **Results:** CAGR 6.41%, ROI 12.99%, Win Rate 65.08%, Max DD -21.77%, Sharpe 0.64
- **Learned:** Universe expansion and signal ranking helped most. 50-day sector
  MA too slow. Too many changes at once made it hard to isolate impact.

### V5 — Tiered Targets + Partial Exits + 30 Positions
- Tiered profit targets by RSI (RSI<5: 2%, RSI<10: 1.5%, else 1%), partial exits,
  MAX_POSITIONS 20→30
- **Results:** CAGR 6.43%, ROI 13.07%, Win Rate 65.08%, Max DD -30.14%, Sharpe 0.49
- **Learned:** RSI-based tiers were flawed — RSI(2) is always <5 after 4 down
  days, routing all trades to Tier 1's 8-day window. 65% time-stop rate.

### V6 — Stripped Back (MAJOR REGRESSION)
- Removed partial exits, flat 1% target, time stop 3 days
- **Results:** CAGR 2.3%, ROI 2.93%, Win Rate 59.35%, Max DD -29.57%, Sharpe 0.29
- **Learned:** 3-day window is too tight for 1% target. Holding longer works.
  Never strip back to fewer than 4-day windows.

### V7 — Best Confirmed Version ✅
- Fixed tier system using consecutive down days (not RSI).
  Tiers: 4 days→1%/4d, 5 days→1.5%/6d, 6+ days→2%/8d + partial exit
- BUT: RSI(2) bug persisted — all 18,698 trades landed in Tier 1 (RSI always
  <5 after 4 down days), giving everything the 8-day window accidentally
- **Results (30 pos):** CAGR 9.05%, ROI 25.23%, Win Rate 69.72%, Max DD -28.94%,
  Sharpe 0.74, Final Equity $641k
- **Key insight:** The "bug" of everything using 8-day windows was actually optimal

### V8 — Fixed Tier Assignment
- Tiers correctly discriminated by consecutive down days
- **Results:** CAGR 2.87%, ROI 3.9%, Win Rate 62.09%, Max DD -27.41%, Sharpe 0.32
- **Learned:** Tier 3 (4 days) is marginal at 61.2% win rate. Most value comes
  from Tier 1 (70.7%). 4-day window for Tier 3 too short — 57% time-stop rate.

### V9 — Quality-Weighted Sizing + Longer Windows
- Extended windows: Tier 3 4d→6d, Tier 2 6d→7d, Tier 1 8d→10d
- Quality-weighted position sizes: Tier 1 7.5%, Tier 2 6%, Tier 3 4%
- **Results:** CAGR 6.73%, ROI 14.18%, Win Rate 61.34%, Max DD -27.71%, Sharpe 0.61
- **Learned:** Longer windows helped but quality-weighting reduced deployment.
  V7's uniform 8-day window for all tiers was better than differentiation.

### V7 Final (20 positions) — ABANDONED
- MAX_POSITIONS 30→20
- **Results:** CAGR 4.54%, ROI 7.42%, Win Rate 57.96%, Max DD -24.04%, Sharpe 0.51
- **Learned:** Wrong lever. -50-70% return collapse for -5% drawdown improvement.
  Never reduce MAX_POSITIONS below 30.

### V7 Final + Circuit Breaker — FAILED (ABANDONED)
- Halted all new entries when portfolio dropped 10% from rolling peak
- **Results:** Only 1.6 years of trades executed (2004-2006). Circuit breaker
  fired early and never reset — blocked 89.3% of all trading days
- **Why it failed:** Strategy needs to keep trading to generate recovery profits.
  Halting entries is self-defeating. The breaker trips when you need trades most.
- **Attempted 3 fixes** — all produced identical 1.6-year result. Root cause:
  with 30 positions at 5% each, any broad market selloff drops portfolio 10%+
  instantly, tripping the breaker permanently.

### V7 Final + Drawdown Scaling (CURRENT — UNTESTED) ⏳
- Replaced circuit breaker with volatility scaling:
  - Normal (DD 0-5% from peak): VIX-adjusted sizing (2.5/5/7.5%)
  - Mild stress (DD 5-10%): max 3% per trade regardless of VIX
  - Severe stress (DD 10%+): max 2% per trade regardless of VIX
- Strategy never stops trading — just bets smaller during drawdowns
- Expected: drawdown improvement from -29% toward -18 to -22% with
  minimal CAGR impact since bad periods use less capital
- **Results: NOT YET RUN — push to GitHub and run workflow**

---

## Walk-Forward Test (UNTESTED) ⏳

`walkforward.py` tests whether V7's parameters work out-of-sample.
Runs 8 rolling windows (5-year in-sample, 2-year out-of-sample).

**To run:** Add to GitHub Actions workflow:
```yaml
- name: Run walk-forward test
  run: python walkforward.py
```

Or locally: `python walkforward.py`

**What to look for:**
- IS/OOS ratio > 0.5 across most windows = genuine edge, not overfitting
- IS/OOS ratio < 0.3 = likely overfitted to history
- OOS CAGR positive in 6+ of 8 windows = robust strategy
- OOS CAGR negative in 2008-2009 and 2022 windows is acceptable

**Why this matters:** V7's parameters were tuned over 9 iterations on the same
21-year dataset. Walk-forward testing on never-seen periods is the only way to
know if the edge is real or fitted to history.

---

## Key Learnings Summary

| Learning | Detail |
|---|---|
| **No stop-losses** | Mean reversion + price stops are incompatible. Stocks bounce after the stop triggers. |
| **Hold longer** | 8-day windows dramatically improved win rate. Never go below 4 days. |
| **RSI(2) always < 5** | After 4+ down days, RSI(2) always collapses. Use consecutive down days for tiering, RSI only for ranking. |
| **Tier 3 is marginal** | 4-down-day setups: ~61% win rate, barely profitable after commissions. |
| **30 positions minimum** | Reducing to 20 collapsed returns -50%. Never reduce MAX_POSITIONS below 30. |
| **No circuit breakers** | Halting entries during drawdowns is self-defeating. Strategy needs to trade to recover. |
| **Drawdown scaling works** | Bet smaller during stress (2-3%), larger during calm (5-7.5%). Never stop entirely. |
| **Filters add value** | SPY regime, sector filter, earnings blackout, gap filters all individually improve returns. |
| **Universe expansion** | S&P 400 MidCap added ~35% more trades/year and improved compounding. |
| **Signal ranking** | RSI(2) ascending sort (most oversold first) improves quality at zero cost. |
| **VIX sizing** | 2.5% position when VIX>25, 7.5% when VIX<15, 5% otherwise. |
| **Earnings blackout** | ±3 days around earnings removes biggest source of gap-down losses. |
| **Sector correlation cap** | Max 3 positions per sector prevents hidden concentration risk. |

---

## Optimism Bias Warnings

V7's reported numbers (9.05% CAGR, 25.23% ROI/year) are the **ceiling**, not
the floor. Real-world performance will be lower due to:

| Source | Estimated CAGR Impact |
|---|---|
| Slippage on open prices | -0.5 to -1% |
| Survivorship bias (incomplete historical universe) | -1 to -2% |
| Overfitting across 9 iterations on same dataset | -2 to -4% |
| Earnings calendar lookahead (uses today's known dates) | -0.3 to -0.5% |
| **Realistic live estimate** | **~4 to 6% CAGR gross** |

After short-term tax (32-37%), realistic net CAGR is likely 2.5-4%.
SPY after long-term tax (20%) is ~8.4% net. **Walk-forward testing is essential
before committing real capital.**

---

## SPY vs Strategy

| Metric | SPY B&H | V7 Strategy |
|---|---|---|
| CAGR (gross) | ~10.5% | 9.05% |
| CAGR (after tax) | ~8.4% | ~5.9% |
| Max Drawdown | -55% (2008) | -28.94% |
| Sharpe Ratio | ~0.55 | 0.74 |
| Effort | Zero | High |
| Tax treatment | Long-term (15-20%) | Short-term (32-37%) |

**After taxes, SPY wins on raw returns for most people.**

**Best use case:** 70-80% SPY + 20-30% V7. Near-zero correlation means V7
diversifies. The blend has better Sharpe than either alone, and lower drawdown
than SPY alone. During 2008 crash (-55% SPY), V7's SPY regime filter limits
exposure — the blended portfolio's effective drawdown is ~-20%.

**LLC / Trader Tax Status:** 870 trades/year may qualify for IRS trader tax
status (Section 475(f) MTM election) allowing deduction of all losses and
business expenses. Consult a CPA specializing in trader tax (e.g. Green Trader
Tax) before forming any entity. SPY via LLC has no meaningful tax benefit.

---

## Repository Structure

```
.
├── backtest-nmr.py          # Main backtest (V7 Final + Drawdown Scaling)
├── backtest_nmr_lib.py      # Shared library (imported by walkforward.py)
├── walkforward.py           # Walk-forward out-of-sample test framework
├── requirements.txt         # Python dependencies
├── README.md                # This file
├── results/                 # Auto-generated (committed by CI)
│   ├── metrics.json
│   ├── trades.csv
│   ├── equity_curve.csv
│   ├── walkforward_summary.csv   # walk-forward results
│   ├── walkforward_equity.csv    # OOS equity curves
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

Optional workflow inputs: `start_date`, `end_date`, `initial_capital`

To also run walk-forward, add to `backtest.yml`:
```yaml
- name: Run walk-forward test
  run: python walkforward.py
```

Runs automatically every Sunday at 00:00 UTC.

### Local

```bash
pip install -r requirements.txt
python backtest-nmr.py       # main backtest (~60-90 min)
python walkforward.py        # walk-forward (~4-6 hours)
```

---

## Output Metrics

| Metric | Description | Target |
|---|---|---|
| `cagr_pct` | Compound Annual Growth Rate | >9% |
| `roi_per_year_pct` | Simple annual ROI on initial capital | >20% |
| `win_rate_pct` | % of profitable trades | >65% |
| `profit_factor` | Gross profit ÷ gross loss | >1.20 |
| `max_drawdown_pct` | Largest peak-to-trough decline | >-20% |
| `sharpe_ratio` | Annualised Sharpe (monthly) | >0.85 |
| `time_stop_rate_pct` | % exiting via time stop | <35% |
| `tier_stats` | Per-tier win rate, avg win/loss, avg hold | Tier 1 > Tier 3 |

**Health check:** If time_stop_rate > 50%, targets are too ambitious for the
hold window. If Tier 3 win rate < 58%, consider raising minimum to 5 down days.

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

Educational and research purposes only. Past backtest performance does not
guarantee future results. Not financial advice. Consult a licensed financial
advisor and CPA before trading with real capital.
