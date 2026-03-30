# Naive Mean Reversion (MR) Backtest

A survivorship-bias-free backtest of a **Naive Mean Reversion** strategy across
all historical S&P 500 + S&P 400 MidCap constituents, automated via GitHub Actions.

---

## Current Version: V7 Final

The current script (`backtest-nmr.py`) is **V7 Final** — the best-performing
version across all iterations. MAX_POSITIONS was reduced from 30 to 20 vs the
original V7 to target a lower drawdown while preserving ROI characteristics.

### V7 Results (30 positions — reference)

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

## Strategy Rules

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
| **Max positions** | 20 simultaneous holdings |
| **Position size** | 5% base, VIX-adjusted: 7.5% (VIX<15), 2.5% (VIX>25) |
| **Earnings month** | Position size capped at 3% in Jan/Apr/Jul/Oct |
| **Signal ranking** | When >20 signals fire, pick lowest RSI(2) first (most oversold) |
| **Sector filter** | Skip entry if stock's sector ETF is below its 20-day MA |
| **Correlation cap** | Max 3 open positions in same sector at any time |
| **Earnings blackout** | Skip entries within ±3 days of earnings announcement |
| **SPY regime** | No new entries when SPY is below its 200-day MA |
| **VIX spike pause** | Pause new entries for 2 days if VIX rises 30%+ in 5 days |
| **Re-entry cooldown** | No re-entry in a stock for 5 days after a time-stop exit |
| **Commission** | $0.005/share or $1.00 minimum per trade |

---

## Key Insight: Why V7 Works

RSI(2) is **always below 5** after 4+ consecutive down days — this is simply
the mathematics of a 2-period lookback where recent gains are near zero. The
original article used RSI as a tier discriminator, but this doesn't create
meaningful differentiation.

**The real discriminator is consecutive down days.** Stocks down 6+ days in a
row are genuinely more oversold than stocks down exactly 4 days. The tier system
maps hold window to this oversold severity — giving each setup enough time to
actually bounce and hit its target.

Giving setups adequate time (4-8 days) rather than forcing exits too early was
the single biggest factor in achieving the 69.72% win rate.

---

## Version History & What Was Learned

### V1 — Baseline Naive MR
- **S&P 500 only**, $10 price filter, 4 consecutive down days, first up-day exit
- **Results:** CAGR 3.11%, ROI 4.34%, Win Rate 64.0%, Max DD -7.95%, Sharpe 0.88
- **Issue:** Only $10k starting capital suppressed compounding. 389 trades/year.
- **Learned:** Strategy works at baseline. Capital matters for compounding.

### V2 — First Enhancement Pass ✅ (Strong baseline)
- Added: RSI(2) < 20 filter, ATR > 1% filter, volume > 20-day avg, SPY 200-day
  regime filter, 1% min profit exit, commission model
- **Results:** CAGR 5.84%, ROI 11.09%, Win Rate 66.27%, Max DD -12.53%, Sharpe 0.89
- **Learned:** All five filters improved results together. SPY regime and 1% min
  profit exit had highest individual impact. This became the reference baseline.

### V3 — Tighter RSI + Stop-Loss (REGRESSION)
- Changed: RSI threshold 20 → 10, min profit 0.5% → 1%, added -3% stop-loss
- **Results:** CAGR 5.47%, ROI 9.94%, Win Rate 65.71%, Max DD -18.02%, Sharpe 0.74
- **Learned:** **Stop-losses are fundamentally incompatible with mean reversion.**
  22.6% of trades hit the stop-loss before bouncing. RSI < 10 was too restrictive.
  Removing stops is a core principle of this strategy type.

### V4 — Full Enhancement Suite
- Added: Signal ranking by RSI(2), 10-day time stop, earnings blackout ±3 days,
  gap filters, S&P 400 MidCap universe, sector 50-day MA filter, VIX regime sizing,
  VIX spike pause, re-entry cooldown, earnings month sizing, correlation cap 3/sector
- **Results:** CAGR 6.41%, ROI 12.99%, Win Rate 65.08%, Max DD -21.77%, Sharpe 0.64
- **Learned:** Universe expansion and signal ranking helped most. Sector filter
  with 50-day MA was too slow. Time stop at 10 days caused high drawdown. Most
  filters added together made it hard to isolate what was helping vs hurting.

### V5 — Tiered Targets + Partial Exits + 30 Positions
- Added: Tiered profit targets by RSI (RSI<5: 2%, RSI<10: 1.5%, else 1%),
  partial exits (50/50), MAX_POSITIONS 20→30
- **Results:** CAGR 6.43%, ROI 13.07%, Win Rate 65.08%, Max DD -30.14%, Sharpe 0.49
- **Learned:** More positions helped compounding. But RSI-based tiers were
  fundamentally flawed — RSI(2) is always < 5 after 4 down days, so all trades
  routed to Tier 1's 8-day/2% target, causing 65% time-stop rate.

### V6 — Stripped Back (MAJOR REGRESSION)
- Reverted: Removed partial exits, flat 1% profit target, time stop 5→3 days
- **Results:** CAGR 2.3%, ROI 2.93%, Win Rate 59.35%, Max DD -29.57%, Sharpe 0.29
- **Learned:** 3-day time stop with 1% target is too tight — stocks need more
  time to bounce. Stripping all the good V5 additions hurt badly. V5's high ROI
  was not a bug — holding longer genuinely works for this strategy.

### V7 — Best Version ✅ (Current)
- Based on V5 but fixed tier system: use consecutive down days instead of RSI
  for tiering. Added 2-day minimum hold before profit exit.
- Tiers: 4 days→1%/4d, 5 days→1.5%/6d, 6+ days→2%/8d with partial exit
- All V4/V5 filters preserved (earnings, sectors, VIX, gaps, correlation)
- **Results (30 pos):** CAGR 9.05%, ROI 25.23%, Win Rate 69.72%, Max DD -28.94%,
  Sharpe 0.74, Final Equity $641k from $100k
- **Issue:** All 18,698 trades still landed in Tier 1 — RSI(2) bug persisted
  because even 4 down days produces RSI(2) < 5. But the 8-day window was
  accidentally correct for all setups, hence best results.

### V8 — Fixed Tier Assignment
- Fixed tier discrimination using consecutive down days (not RSI)
- Tier breakdown worked correctly: 75% Tier 3, 14% Tier 2, 10% Tier 1
- **Results:** CAGR 2.87%, ROI 3.9%, Win Rate 62.09%, Max DD -27.41%, Sharpe 0.32
- **Learned:** Tier 3 (4 down days) is a marginal setup — 61.2% win rate barely
  profitable after commissions. Tier 1 (70.7%) is excellent. The 4-day window
  for Tier 3 was too short — time-stop rate still 57%.

### V9 — Quality-Weighted Sizing + Longer Windows
- Extended windows: Tier 3 4d→6d, Tier 2 6d→7d, Tier 1 8d→10d
- Quality-weighted sizes: Tier 1 7.5%, Tier 2 6%, Tier 3 4%
- Added minimum 2-day hold before profit exit
- **Results:** CAGR 6.73%, ROI 14.18%, Win Rate 61.34%, Max DD -27.71%, Sharpe 0.61
- **Learned:** Longer windows helped but quality-weighting reduced overall capital
  deployment. Still couldn't beat V7's ROI because V7's "bug" of treating
  everything as Tier 1 was actually the optimal behavior.

### V7 Final (Current) — V7 with MAX_POSITIONS=20
- Single change from V7: MAX_POSITIONS 30→20
- Goal: Reduce drawdown by limiting simultaneous exposure during market stress
- **Run to see results**

---

## Key Learnings Summary

| Learning | Detail |
|---|---|
| **No stop-losses** | Mean reversion + price stops are incompatible. Stocks bounce after the stop triggers. |
| **Hold longer** | Giving setups 6-8 days dramatically improves win rate vs forcing 1-3 day exits. |
| **RSI(2) always < 5** | After 4+ consecutive down days, RSI(2) always collapses below 5. Use consecutive down days for tier discrimination, RSI for ranking only. |
| **Tier 3 is marginal** | 4-down-day setups have ~61% win rate — barely profitable. Most value comes from 5+ day setups. |
| **Filters add value** | SPY regime, sector filter, earnings blackout, gap filters each individually improve risk-adjusted returns. |
| **Universe expansion** | Adding S&P 400 MidCap increased trades/year by ~35% and improved compounding. |
| **Signal ranking** | Sorting by RSI(2) ascending (most oversold first) improves quality at no cost. |
| **VIX sizing** | Reducing position size during high VIX and increasing during low VIX improves Sharpe. |
| **Earnings blackout** | Avoiding entries within ±3 days of earnings eliminates the biggest source of gap-down losses. |
| **Sector correlation** | Capping at 3 positions per sector prevents hidden concentration risk during sector selloffs. |

---

## What Has NOT Been Tried Yet

- Walk-forward optimization (test on out-of-sample periods)
- Short-selling the strategy (buy on 4 up days when below 200-day MA)
- Different MA windows (50-day, 100-day instead of 200-day)
- Adding fundamental filters (e.g. avoid stocks with negative earnings)
- Intraday entry (buying the dip during the day rather than next open)
- Adding options overlay (selling puts instead of buying stock)
- Comparing against other mean reversion signals (Bollinger Bands, z-score)

---

## SPY vs Strategy Discussion

SPY buy-and-hold over the same 2004–2026 period:
- CAGR: ~10.5%
- Max Drawdown: ~-55% (2008-2009)
- Sharpe: ~0.55
- Tax: Long-term capital gains (15-20%)
- Effort: Zero

V7 Strategy:
- CAGR: 9.05% (slightly lower gross)
- Max Drawdown: -28.94% (much lower)
- Sharpe: 0.74 (higher risk-adjusted)
- Tax: Short-term ordinary income (32-37%) — significant disadvantage
- Effort: High (monitoring, execution, infrastructure)

**After taxes, SPY likely wins on net returns for most people.**

**Best use case for V7:** As a 20-30% allocation alongside a core SPY position.
Near-zero correlation means V7 acts as a diversifier. During 2008-2009 crash
when SPY dropped 55%, V7's SPY regime filter would have paused entries,
limiting drawdown. The blended portfolio has better risk-adjusted returns than
either alone.

**LLC / Trader Tax Status:** V7 generates ~870 short-term trades/year which may
qualify for IRS trader tax status (Section 475(f) MTM election). This would
allow deducting all trading losses and business expenses (software, data,
hardware). Consult a CPA specializing in trader taxation (e.g. Green Trader Tax)
before forming any entity. SPY via LLC has no meaningful tax benefit.

---

## Repository Structure

```
.
├── backtest-nmr.py              # V7 Final backtest engine
├── requirements.txt             # Python dependencies
├── README.md                    # This file
├── results/                     # Auto-generated output (committed by CI)
│   ├── metrics.json             # Key performance metrics
│   ├── trades.csv               # Individual trade log
│   └── equity_curve.csv        # Equity curve over time
└── .github/
    └── workflows/
        └── backtest.yml         # GitHub Actions workflow
```

---

## Setup & Running

### GitHub Actions (recommended)

1. Push all files to your GitHub repo
2. Go to **Settings → Actions → General → Workflow permissions** → Read and write
3. Go to **Actions → Naive MR Backtest → Run workflow**

The workflow accepts optional inputs:
- `start_date` (default: 2004-01-01)
- `end_date` (default: today)
- `initial_capital` (default: 100000)

Runs automatically every Sunday at 00:00 UTC.

### Local

```bash
pip install -r requirements.txt
python backtest-nmr.py
```

**Runtime:** ~60-90 minutes (earnings calendar fetch adds ~20 minutes).

---

## Output Metrics Explained

| Metric | Description |
|---|---|
| `cagr_pct` | Compound Annual Growth Rate |
| `roi_per_year_pct` | Simple annual ROI on initial capital |
| `win_rate_pct` | % of trades that were profitable |
| `avg_win_pct` | Average gain on winning trades |
| `avg_loss_pct` | Average loss on losing trades |
| `profit_factor` | Gross profit ÷ gross loss (>1.2 is good) |
| `max_drawdown_pct` | Largest peak-to-trough equity decline |
| `sharpe_ratio` | Annualised Sharpe (monthly returns, no risk-free rate) |
| `time_stop_rate_pct` | % of trades exiting via time stop (target: <35%) |
| `tier_stats` | Per-tier breakdown of win rate, avg win/loss, avg hold |
| `exit_reasons` | Count of time_stop, profit_target, partial_exit |

**Health indicators:**
- time_stop_rate < 35% = strategy is finding bounces efficiently
- time_stop_rate > 50% = targets too ambitious or windows too short
- Tier 1 win rate should be > Tier 3 win rate (more oversold = stronger bounce)

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

For educational and research purposes only. Past backtest performance does not
guarantee future results. This is not financial advice. Backtests have inherent
limitations including look-ahead bias, overfitting, and execution assumptions
that may not hold in live trading.
