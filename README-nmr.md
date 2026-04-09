# V38a Experiment README
## What these files are

Two files to drop alongside your existing backtest code:

- `backtest_nmr_lib_v38a.py` — modified lib with 5 experimental changes, all togglable
- `backtest-nmr-v38a.py` — runner that executes all 7 permutations in one session

Your existing `backtest_nmr_lib.py` and `backtest-nmr.py` are **untouched**.

---

## How to run

```bash
# From your project directory, alongside existing files:
python backtest-nmr-v38a.py
```

Data downloads **once**. All 7 experiments reuse it. Runtime is ~same as a single
V33d run (~90–120 min). Signal generation re-runs per experiment (C1/C2 modify
signals); C3/C4/C5 only change simulation logic so they're faster.

---

## What runs

| Experiment      | Change                                        |
|-----------------|-----------------------------------------------|
| V33d_baseline   | No changes — pure V33d for comparison         |
| C1_ibs_only     | IBS < 0.35 entry filter only                  |
| C2_ema_only     | EMA 20/50 downtrend block only                |
| C3_gap_only     | Gap-down threshold tightened -1.5% → -1.0%   |
| C4_cooldown     | 15-day cooldown if stock time-stops twice/30d |
| C5_sizing       | Top 20% signals by score get 1.2× size        |
| V38a_all        | All 5 changes combined                        |

---

## The 5 changes in plain English

### C1 — IBS filter
**What:** Internal Bar Strength = (Close − Low) / (High − Low). Only enter when
IBS < 0.35, meaning the close was in the bottom 35% of the day's range.
**Why:** Confirms the stock actually closed weak, not just technically down for
the day but near its high. Aligned with the existing RSI(2) signal.
**Risk:** Reduces trade count. If it blocks crash-recovery entries, costs equity.
**Watch:** If win rate rises but trades/year drops significantly → net wash.

### C2 — EMA 20/50 downtrend block
**What:** Skip entries where Close < EMA20 < EMA50 with at least 0.5% separation
between the two EMAs. Uptrends and neutral markets still allowed.
**Why:** Mean reversion works best when a stock is pulling back within an uptrend
or consolidation, not accelerating downward in a confirmed trend.
**Risk:** The 200-day SMA already filters bear markets. This adds a per-stock
layer that may also block good crash-recovery setups.
**Watch:** If trades/year drops >15%, the filter is too aggressive.

### C3 — Gap filter tightened
**What:** GAP_DOWN_MAX changes from −1.5% to −1.0%. Skips entries where the next
open is more than 1.0% below prior close (was 1.5%).
**Why:** A larger gap down on entry day slightly reduces mean reversion probability.
Tighter filter = fewer adverse fills accepted.
**Risk:** Lowest-risk of all 5 changes. Small reduction in trades, minor quality lift.
**Watch:** If trades/year barely changes, the gap filter was rarely binding.

### C4 — Double time-stop cooldown
**What:** If a stock gets a time-stop exit, then signals again and time-stops a
second time within 30 days, it goes on a 15-day cooldown instead of the standard
5-day cooldown.
**Why:** Surgical — doesn't touch crash-day exposure. Only affects stocks that
are failing their 8-day window repeatedly, suggesting they're in structural trouble.
**Risk:** Minimal. If a stock rarely double-time-stops, this fires very infrequently.
**Watch:** Check exit_reasons in trades.csv for how often extended cooldowns trigger.

### C5 — Tiered size multiplier
**What:** On days with 5+ entry candidates, the top 20% by composite score
(RSI2/ATR_pct) get a 1.2× size multiplier. Hard cap at 12% per position.
**Why:** You already rank and prioritize signals. This asks whether the top-ranked
signals actually outperform lower-ranked ones enough to justify larger size.
**Risk:** If composite score ranking is not predictive at the trade level, this
adds volatility without return benefit. Similar risk profile to position count increases.
**Watch:** If CAGR rises but MaxDD rises proportionally, the score isn't discriminating.

---

## How to read results

Share `results/comparison_v38a.txt` — that's the key output.

### Decision framework for each change

| Condition | Decision |
|-----------|----------|
| CAGR ▲ AND MaxDD neutral or ▲ | Strong keep |
| CAGR neutral AND MaxDD ▲ (less negative) | Keep if drawdown matters to you |
| CAGR ▲ AND MaxDD ▼ proportionally | Risk/return tradeoff — check Sharpe |
| CAGR ▼ AND anything | Reject, do not carry forward |
| Trades/year drops >15% vs baseline | Flag — likely blocking crash-recovery days |

### The one number that matters most for V33d's goal
**Final equity > $3,124,041** (V33d baseline) — that's the bar.

### Secondary check: win rate
If win rate drops below **57%** on any experiment, that change is failing regardless
of what the CAGR says — it means the filtered/modified trades are lower quality.

### For V38a_all (combined):
If combined is worse than baseline but some individual changes are positive,
it means changes are interfering with each other (likely C1 + C2 both reducing
crash-recovery trades at the same time). In that case, take only the best
individual change and re-run.

---

## Tuning the parameters (optional)

All tuneable values are in `ExperimentConfig` at the top of `backtest_nmr_lib_v38a.py`:

```python
ibs_threshold: float = 0.35          # C1: raise to 0.40 to be more permissive
ema_separation_pct: float = 0.005    # C2: raise to 0.01 for stronger confirmation
gap_down_tighter: float = -0.010     # C3: try -0.020 for more permissive variant
double_cooldown_window_days: int = 30  # C4: window to check for second time-stop
double_cooldown_days: int = 15       # C4: cooldown length on second time-stop
top_signal_pct: float = 0.20         # C5: top 20% get boost
top_signal_multiplier: float = 1.20  # C5: size multiplier
top_signal_hard_cap: float = 0.12    # C5: never exceed 12% per position
min_candidates_for_ranking: int = 5  # C5: only boost when 5+ candidates on a day
```

To run a single experiment in isolation for faster testing:
```python
from backtest_nmr_lib_v38a import *

# Example: test only C1 with a looser threshold
cfg = ExperimentConfig(
    name="C1_loose",
    description="C1 IBS at 0.40",
    c1_ibs_filter=True,
    ibs_threshold=0.40
)
# ... then call run_backtest with this cfg
```

---

## Files produced

```
results/
├── V33d_baseline/
│   ├── trades.csv
│   ├── equity_curve.csv
│   └── metrics.json
├── C1_ibs_only/     (same structure)
├── C2_ema_only/     (same structure)
├── C3_gap_only/     (same structure)
├── C4_cooldown/     (same structure)
├── C5_sizing/       (same structure)
├── V38a_all/        (same structure)
├── comparison_v38a.txt   ← share this
└── comparison_v38a.json  ← machine-readable
```
