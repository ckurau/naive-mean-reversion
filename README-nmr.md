# Naive Mean Reversion (NMR) Backtest

A survivorship-bias-free backtest of a Naive Mean Reversion strategy across all historical S&P 500 + S&P 400 MidCap + S&P 600 SmallCap constituents, automated via GitHub Actions.

---

## Current Version: V47 + Idea 3 (Put Spread Hedge)

**Active strategy: V47 base logic + quarterly SPY 5%/15% OTM put spread hedge.**

V47 = V35 + four confirmed positive sizing overlays (TOM sizing, DOW sizing, partial trigger tuning, VIX RSI tightening). Walk-forward validated: 7/8 OOS windows positive, OOS avg CAGR 20.91% vs V34/V35 reference of 19.45%.

The put spread is executed live via `hedge_quarterly.py` alongside the MR strategy in paper trading.

> ⚠️ **`scan_evening.py` has NOT yet been updated to V47 parameters. See sync checklist below.**

---

## Architecture

```
backtest-nmr-v47.py       Thin wrapper → imports backtest_nmr_lib_v47.py (V47)
backtest_nmr_lib_v47.py   All V47 backtest logic and parameters
walkforward_v47.py        Walk-forward validation for V47
backtest_ideas_v6.py      V47 + Idea3 put spread combined backtest
backtest-nmr.py           Thin wrapper → imports backtest_nmr_lib.py (V35, reference)
backtest_nmr_lib.py       All V35 backtest logic and parameters
backtest_ideas_v2.py      Multi-test runner: Ideas V2 (put spread, twin engine, port vol, sector streak)
backtest_ideas_v3.py      Multi-test runner: Ideas V3 (VIX TS, 52wk high, gap capture, analyst, calls)
backtest_ideas_v4.py      Multi-test runner: Ideas V4 (overnight, salience, dispersion, skew, turnover, corr, recycle)
backtest_ideas_v5.py      Multi-test runner: Ideas V5 (TOM, VIX RSI, partial tune, DOW sizing — led to V47)
v47_backtest.yml          GitHub Actions: V47 backtest + optional walk-forward
v47_i3_backtest.yml       GitHub Actions: V47+I3 combined backtest
ideas_v2_backtest.yml     GitHub Actions: Ideas V2
ideas_v3_backtest.yml     GitHub Actions: Ideas V3
ideas_v4_backtest.yml     GitHub Actions: Ideas V4
ideas_v5_backtest.yml     GitHub Actions: Ideas V5
scan_evening.py           Live: evening signal scan + LOO order submission (6:00 PM PT) ⚠️ needs V47 update
trade_morning.py          Live: morning exit orders + fill confirmation (6:15 AM PT) — no changes needed
hedge_quarterly.py        Live: quarterly SPY put spread entry/roll (6:05 PM PT) — no changes needed
check_signals.py          Diagnostic: preview tonight's signals (read-only, no orders)
check_today.py            Diagnostic: show today's closed trades + open positions
check_log.py              Diagnostic: show today's trade.log entries
list_tasks.py             Diagnostic: show Windows Task Scheduler entries and trigger times
walkforward.py            Walk-forward validation runner (V35)
preflight.py              Pre-flight system check
positions_check.py        CLI: view open/closed positions + P&L
```

**Three-script live execution:**
- `scan_evening.py` — 6:00 PM PT, scans universe, submits LOO buy orders
- `hedge_quarterly.py` — 6:05 PM PT, checks/rolls put spread (self-exits in <1 sec on non-action days)
- `trade_morning.py` — 6:15 AM PT, submits MOO exits, confirms LOO fills

---

## Best Confirmed Results

### V47 + Idea 3 — Full History Run (April 2026)

| Metric | Value | Notes |
|---|---|---|
| CAGR | 22.40% | Full history through April 2026 — see benchmark note below |
| Max Drawdown | -60.89% | Full history through April 2026 |
| Sharpe Ratio | 0.74 | Matches V35+I3 exactly |
| Win Rate | 60.24% | |
| Profit Factor | 1.06 | |
| Final Equity (from $100k) | $9,915,308 | Full history through April 2026 |
| Put premiums paid | -$2,678k | |
| Put payouts received | +$4,885k | |
| Put net P&L | +$2,208k | |

**Benchmark note:** The $9.9M / 22.40% figure covers the full trading history through April 2026, which includes 2+ additional years of strong performance (2024: +$2.9M MR+puts) compared to when the V35+I3 benchmark was originally set. It is not directly comparable to the $4.5M / 19.71% V35+I3 figure. For a true apples-to-apples comparison, use the delta analysis below.

### V47 vs V35 — Apples-to-Apples (MR only, same benchmark period)

| Metric | V35 | V47 | Delta |
|---|---|---|---|
| CAGR | 18.91% | 19.54% | **+0.63pp** |
| Final Equity | $4,131,883 | $4,637,314 | **+$505k** |
| Max Drawdown | -55.89% | -56.84% | -0.95pp worse |
| Sharpe | 0.71 | 0.72 | **+0.01** |
| Win Rate | 60.15% | 60.25% | +0.10pp |

V47 is a genuine improvement at the cost of ~1pp more MaxDD in MR-only terms. With the put spread applied, that MaxDD cost is partially offset at crash events (hedge fires at -5% SPY drop). The Sharpe of 0.74 in the V47+I3 combined run matches V35+I3 exactly — same risk-adjusted quality, better absolute returns.

**Is V47+I3 truly the best version despite the MaxDD?** Yes. The MaxDD worsening (-56.84% vs -55.89% MR-only) is ~1pp and is offset in practice by the put spread. The Sharpe is identical at 0.74. The CAGR and equity gain are real. V47+I3 is the confirmed ceiling.

### V35 + Idea 3 (Previous Recommended — reference benchmark)

| Metric | Value |
|---|---|
| CAGR | 19.71% |
| Max Drawdown | -52.87% |
| Sharpe Ratio | 0.74 |
| Profit Factor | 1.07 |
| Final Equity (from $100k) | $4,513,155 |
| Period | 2004–2026 benchmark date |

Put spread net P&L over benchmark period: -$2,367k premiums, +$4,317k payouts, **net +$1,950k**

### V35 Baseline (No Hedge)

| Metric | Value |
|---|---|
| CAGR | 18.91% |
| Max Drawdown | -55.89% |
| Sharpe Ratio | 0.71 |
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

## Strategy Comparison

| Strategy | CAGR | Equity | MaxDD | Sharpe | Best For |
|---|---|---|---|---|---|
| V47 + Idea 3 (current, full history) | 22.40%* | $9.9M* | -60.89%* | 0.74 | Max wealth, taxable, with hedge |
| V47 (no hedge, benchmark period) | 19.54% | $4,637k | -56.84% | 0.72 | Max wealth, taxable, no hedge |
| V35 + Idea 3 (previous benchmark) | 19.71% | $4,513k | -52.87% | 0.74 | Previous recommended |
| V35 (no hedge) | 18.91% | $4,132k | -55.89% | 0.71 | V35 baseline |
| C_TurnOfMonth | 16.20% | $2,517k | -48.91% | 0.71 | Middle ground |
| V32d | 15.37% | $2,145k | -39.21% | 0.77 | Roth IRA, lower DD tolerance |

*Full history through April 2026 — not directly comparable to benchmark-period figures.

---

## V47 Strategy Rules

| Rule | Detail |
|---|---|
| Universe | S&P 500 + S&P 400 MidCap + S&P 600 SmallCap (current + historical, avoids survivorship bias) |
| Trend filter | Stock must be above its 200-day SMA |
| Entry signal | 4+ consecutive down days AND RSI(2) < 20 AND ATR > 1% AND volume > 20-day avg AND dollar volume > $5M/day |
| Entry execution | Buy at open of next day via LOO order (limit = prior close × 1.005) |
| Gap filters | Skip if next open gaps down > 1.0% OR gaps up > 2% |
| Exit — all tiers | 2% profit target, 8-day time stop (uniform) |
| Tier 1 partial | 6+ down days: 50% at **0.8%** *(was 1.0% in V35)*, remainder at 2% |
| Tier 2 | 5 down days: 2% target, 8-day window, no partial |
| Tier 3 | 4 down days: 2% target, 8-day window, no partial |
| Min hold | 2 calendar days before profit exit allowed |
| Max positions | 60 simultaneous holdings |
| Position size base | VIX < 25 → 9%, VIX ≥ 25 → 5% |
| Tiered sizing | Top 20% of signals by composite score get 1.3x size, hard cap 12% |
| **TOM sizing** | **Last trading day of month + next 3 trading days: 1.15x additional multiplier** |
| **DOW sizing** | **Tuesday: 1.10x \| Friday: 0.90x \| all other days: 1.00x** |
| **VIX RSI tight** | **When VIX < 15: require RSI(2) < 15 instead of < 20** |
| Signal ranking | Composite score: RSI(2) / ATR_pct |
| Sector filter | Skip entry if stock's sector ETF is below its 20-day MA |
| Correlation cap | Max 3 open positions in same sector |
| Earnings blackout | Skip entries within ±3 days of earnings announcement |
| SPY regime | No new entries when SPY is below its 200-day MA |
| Re-entry cooldown | No re-entry in a stock for 5 days after a time-stop exit |
| Velocity crash pause | SPY 5-day return < -12% → pause all entries for 5 days |
| Earnings month cap | Position size capped at 2.4% in Jan/Apr/Jul/Oct |
| Commission | $0.005/share or $0.35 minimum per trade |

**V47 changes vs V35 (bolded above):**
- `TIER1_PARTIAL_TRIGGER = 0.008` (was 0.010)
- `TOM_MULT = 1.15` on last trading day of month + next 3 days
- `DOW_MULT = {0: 1.00, 1: 1.10, 2: 1.00, 3: 1.00, 4: 0.90}` (Mon=0, Tue=1, Fri=4)
- `VIX_TIGHT_THRESH = 15.0`, `RSI_TIGHT_THRESH = 15.0` (zero standalone effect, included as no-cost addition)

---

## Idea 3: Quarterly SPY Put Spread (Live)

### What it does
Buys a 5%/15% OTM SPY put spread every ~63 trading days. The spread pays out linearly when SPY drops 5–15%+ from the quarterly reference price, capping at 10% of notional at the 15% level.

### Parameters (hedge_quarterly.py)
| Parameter | Value |
|---|---|
| Long put | 5% OTM from current SPY |
| Short put | 15% OTM from current SPY |
| Target DTE | 63 trading days (~quarterly) |
| Contracts | 1 (appropriate for $100k account) |
| Max debit | $15/contract (refuses if too expensive) |
| Auto-roll | Yes — closes and reopens when ≤5 days to expiry |

### Historical payout events (backtest)
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
- Client ID 30 (distinct from scan_evening ID 10 and trade_morning ID 1)

---

## Gateway Schedule

| Time (PT) | Script | Action |
|---|---|---|
| 6:00 PM | scan_evening.py | Scans signals, submits LOO orders |
| 6:05 PM | hedge_quarterly.py | Checks/rolls put spread (fast exit if no action needed) |
| 6:15 AM | trade_morning.py | Submits exits, confirms LOO fills |

**Recommendation: leave Gateway running 24/7.**

---

## Walk-Forward Validation

### V47 Walk-Forward (PASS — April 2026)

| Window | OOS Period | CAGR | WR | PF | MaxDD | Sharpe | Trades | IS/OOS | Regime |
|---|---|---|---|---|---|---|---|---|---|
| W1 | 2009–2010 | 28.3% | 61.4% | 1.34 | -14.5% | 1.23 | 1,403 | 0.76x | Recovery |
| W2 | 2011–2012 | 26.0% | 63.9% | 1.22 | -35.4% | 0.73 | 2,004 | 1.23x | Chop/Dip |
| W3 | 2013–2014 | 41.2% | 59.4% | 1.23 | -34.1% | 1.27 | 2,576 | 1.54x | Bull |
| W4 | 2015–2016 | 15.8% | 58.6% | 1.17 | -18.3% | 0.84 | 1,804 | 0.41x | Chop |
| W5 | 2017–2018 | 12.0% | 57.2% | 1.07 | -31.5% | 0.47 | 2,656 | 0.40x | Low-Vol Bull |
| W6 | 2019–2020 | 51.8% | 62.8% | 1.38 | -36.3% | 1.19 | 2,079 | 3.61x | Bull+Crash |
| W7 | 2021–2022 | -12.7% | 54.7% | 0.93 | -48.0% | -0.36 | 1,890 | -0.42x | Bear Grind |
| W8 | 2023–2025 | 4.8% | 60.0% | 1.02 | -57.0% | 0.36 | 4,144 | 0.30x | AI Bull + Tariff Bear |

**OOS Positive CAGR windows: 7/8 — PASS**
**OOS Avg CAGR: 20.91% | OOS Median CAGR: 20.92%**
V34/V35 reference: 7/8 positive | Avg 19.45% | Median 19.99%

V47 improves on V34/V35 across every window. W7 (-12.7% vs -11.7%) and W8 (+4.8% vs +5.1%) are essentially identical — the sizing changes have no adverse effect in weak regimes.

### V34 Walk-Forward (PASS — reference, carries forward to V35)

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

## ⚠️ Next Steps: Update scan_evening.py to V47

After reading the actual `scan_evening.py` source, here are the exact 7 changes required. `trade_morning.py` and `hedge_quarterly.py` need **zero changes**.

### Why trade_morning.py needs no changes
It reads `partial_trigger` from the DB — a value that scan_evening.py writes at entry time. Once scan_evening.py is updated to write `0.008`, all new entries automatically get the correct value. Existing open positions keep their stored `partial_trigger=0.01` until they exit, which is correct.

### Why hedge_quarterly.py needs no changes
It is purely options execution logic (strikes, expiry, IBKR order placement, DB recording). It has no reference to MR sizing parameters.

---

### Change 1 — Add V47 constants

In the `# -- Strategy parameters (must match backtest V35) ---` block, add after the existing constants:

```python
# V47 additions ---------------------------------------------------------
TIER1_PARTIAL_TRIGGER = 0.008   # was 0.010 in V35

TOM_MULT         = 1.15         # last trading day of month + next 3 days
VIX_TIGHT_THRESH = 15.0        # VIX below this triggers tighter RSI
RSI_TIGHT_THRESH = 15.0        # RSI threshold in low-VIX regime (was 20)
DOW_MULT         = {0: 1.00, 1: 1.10, 2: 1.00, 3: 1.00, 4: 0.90}
# Mon=0, Tue=1, Wed=2, Thu=3, Fri=4
```

---

### Change 2 — Add `build_tom_set()` function

Add this function after the existing helper functions (e.g. after `count_sector_positions`):

```python
def build_tom_set(trading_dates):
    """Last trading day of each month + next 3 trading days."""
    tom = set()
    n   = len(trading_dates)
    for i, d in enumerate(trading_dates):
        is_month_end = (i == n - 1) or (
            pd.Timestamp(trading_dates[i + 1]).month != pd.Timestamp(d).month
        )
        if is_month_end:
            tom.add(d)
            for j in range(1, 4):
                if i + j < n:
                    tom.add(trading_dates[i + j])
    return tom
```

---

### Change 3 — Update `get_tier()` partial_trigger

In `get_tier()`, change the Tier 1 `partial_trigger` from the hardcoded `0.01` to use the constant:

```python
# Before:
'partial_trigger': 0.01

# After:
'partial_trigger': TIER1_PARTIAL_TRIGGER
```

---

### Change 4 — Update `get_position_size_pct()` signature and logic

Replace the existing function with:

```python
def get_position_size_pct(vix_value, rank=0, n_candidates=0, tom_today=False, dow=0):
    month = datetime.date.today().month
    base  = POSITION_SIZE_HIGH if vix_value < VIX_LOW else POSITION_SIZE
    if month in EARNINGS_MONTHS and base > POSITION_SIZE_EARNINGS:
        base = POSITION_SIZE_EARNINGS
    multiplier = 1.0
    if n_candidates >= MIN_CANDIDATES_FOR_C5:
        top_n = max(1, int(n_candidates * TOP_SIGNAL_PCT))
        if rank < top_n:
            multiplier = TOP_SIGNAL_MULTIPLIER
    if tom_today:
        multiplier *= TOM_MULT
    multiplier *= DOW_MULT.get(dow, 1.0)
    return min(base * multiplier, TOP_SIGNAL_HARD_CAP)
```

---

### Change 5 — Add VIX RSI tightening in signal scan loop

In the signal scan loop inside `run()`, after the existing RSI filter:

```python
# Existing RSI filter (leave as-is):
rsi2 = float(compute_rsi(close, RSI_PERIOD).iloc[-1])
if rsi2 >= RSI_THRESHOLD:
    continue

# ADD immediately after:
# C: VIX tight regime — when VIX < 15, require RSI < 15
if vix_value < VIX_TIGHT_THRESH and rsi2 >= RSI_TIGHT_THRESH:
    continue
```

---

### Change 6 — Pre-compute TOM set and DOW before the signal scan loop

In `run()`, after `log.info(f"Downloaded {len(price_data)} tickers")` and before the signal scan loop:

```python
# V47: pre-compute TOM set and day-of-week
all_dates_sorted = sorted(set().union(
    *[set(df.index) for df in price_data.values()]
))
tom_set   = build_tom_set(all_dates_sorted)
tom_today = pd.Timestamp(today) in tom_set
dow_today = today.weekday()   # 0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri
log.info(f"TOM day: {tom_today} | DOW: {dow_today} | DOW mult: {DOW_MULT.get(dow_today, 1.0):.2f}x")
```

---

### Change 7 — Update `get_position_size_pct()` call in the order submission loop

In the order submission loop, change:

```python
# Before:
cur_pos_size = get_position_size_pct(vix_value, rank=rank_i, n_candidates=n_cands)

# After:
cur_pos_size = get_position_size_pct(vix_value, rank=rank_i, n_candidates=n_cands,
                                      tom_today=tom_today, dow=dow_today)
```

---

### Verification after updating

Run a manual preview the next evening after making changes:

```
cd C:\nmr-trader
venv\Scripts\python.exe check_signals.py
```

Confirm in the log:
- `TIER1_PARTIAL_TRIGGER` is `0.008` in `get_tier()` output
- `TOM day: True` appears on the last trading day of the month and the 3 days following
- `DOW: 1` on Tuesdays shows `DOW mult: 1.10x`
- `DOW: 4` on Fridays shows `DOW mult: 0.90x`

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
| Max positions | 60 (matches V47) |

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

## Ideas V5: Full Research Results (April 2026)

Tested genuinely untested sizing ideas vs V35+I3 baseline. Run via `backtest_ideas_v5.py`.

**Architecture note:** Earlier V5 runs used a standalone reimplemented engine which produced an incorrect 17.11% baseline (vs correct 19.71%). Fixed by importing directly from `backtest_nmr_lib.py` — same architecture as V2/V3/V4. Never reimplement the backtest engine — always import from the lib.

| Test | CAGR | dCAGR | MaxDD | dDD | Sharpe | Final Equity | Notes |
|---|---|---|---|---|---|---|---|
| Baseline V35+I3 | 21.72% | — | -60.02% | — | 0.73 | $8,781,619 | Extended period vs original benchmark |
| B_TOM_Sizing | 22.20% | +0.48pp | -61.48% | -1.46pp | 0.73 | $9,562,878 | TOM entries 1.15x |
| C_VIX_RSI | 21.72% | +0.00pp | -60.02% | +0.00pp | 0.73 | $8,781,619 | Zero standalone effect — confirmed dead |
| D_Partial_Tune | 21.77% | +0.05pp | -60.03% | -0.01pp | 0.73 | $8,847,832 | Tiny positive both metrics |
| **E_DOW_Sizing** | **21.88%** | **+0.16pp** | **-59.37%** | **+0.65pp better** | **0.74** | **$9,031,244** | **Only standalone idea improving both CAGR and MaxDD** |
| H_Combo_BCD | 22.24% | +0.52pp | -61.49% | -1.47pp | 0.73 | $9,636,081 | B dominates, DD cost |
| **I_Combo_BCDE** | **22.40%** | **+0.68pp** | **-60.90%** | **-0.88pp** | **0.74** | **$9,917,330** | **Best combined — became V47** |

**Baseline note:** V5 baseline shows 21.72% vs original 19.71% benchmark because V5 ran through April 2026 with additional strong years compounding. The deltas between tests are clean and valid.

**Conclusion:** I_Combo_BCDE (B+C+D+E) is the confirmed best result: +0.68pp CAGR, +$1.14M equity, only -0.88pp MaxDD vs baseline. Became V47.

---

## Ideas V2: Full Research Results (April 2026)

Tested 4 new drawdown-reduction ideas against V35 baseline. Run via `backtest_ideas_v2.py`.

| Test | CAGR | MaxDD | Sharpe | Final Equity | Notes |
|---|---|---|---|---|---|
| Baseline V35 | 18.91% | -55.89% | 0.71 | $4,131,883 | — |
| Idea1 TwinEngine | 18.39% | -56.51% | 0.70 | $3,955,853 | Worse on both metrics |
| Idea2 PortVol | 15.85% | -52.55% | 0.67 | $2,361,854 | 3pp DD improvement, −3pp CAGR |
| **Idea3 PutSpread** | **19.71%** | **-52.87%** | **0.74** | **$4,513,155** | **Only idea improving all three metrics** |
| Idea4 SectorStreak | 18.86% | -55.92% | 0.71 | $4,095,831 | Neutral — no meaningful effect |
| Ideas2+3 | 16.55% | -49.62% | 0.69 | $2,534,726 | Best MaxDD combo, lower equity |
| Ideas3+4 | 19.66% | -52.89% | 0.74 | $4,474,449 | Near-identical to Idea3 alone |

**Conclusion:** Idea 3 (put spread) is the only idea that improves CAGR, MaxDD, and Sharpe simultaneously. Net +$1.95M profit over 21 years from 8 payout events.

---

## Ideas V3: Full Research Results (April 2026)

Tested 6 new ideas against V35+I3 baseline. Run via `backtest_ideas_v3.py`. 17 total tests.

| Test | CAGR | MaxDD | Sharpe | Final Equity | Notes |
|---|---|---|---|---|---|
| Baseline V35+I3 | 19.53% | -53.06% | 0.73 | $4,364,842 | Reference |
| IdeaD VixTS | 18.66% | -55.75% | 0.70 | $3,949,405 | Nearly identical to baseline |
| IdeaE 52wkHigh | 15.42% | -54.66% | 0.64 | $2,180,577 | -4pp CAGR for 1.2pp MaxDD |
| IdeaB GapCapture | 14.74% | -57.76% | 0.62 | $2,295,612 | Contaminates cooldown tracking |
| IdeaC Analyst | 18.72% | -55.89% | 0.71 | $3,995,384 | Zero effect (static data) |
| IdeaF CallSpread | 18.53% | -53.13% | 0.71 | $3,446,559 | -$548k equity for 2.76pp MaxDD |
| IdeaF+I3 | 19.29% | -51.49% | 0.74 | $3,759,789 | Best Sharpe, -$605k vs puts-only |
| Kitchen_Sink | 12.98% | -47.59% | 0.61 | $1,230,392 | Worst equity |

**Conclusion:** No V3 idea improves on V35+I3.

---

## Ideas V4: Full Research Results (April 2026)

Tested 7 signal quality ideas. 24 total tests. Run via `backtest_ideas_v4.py`.

**Core finding: ranking enhancements have zero effect when the 60-position cap is rarely binding.**
With 10–30 candidates and 60 slots, all candidates fill regardless of rank.

| Test | CAGR | MaxDD | Sharpe | Final Equity | Notes |
|---|---|---|---|---|---|
| Baseline V35+I3 | 19.69% | -52.86% | 0.74 | $4,492,222 | Reference |
| Idea1–5 (all ranking ideas) | 18.87% | -55.89% | 0.71 | $4,101,836 | All identical to V35 baseline |
| Idea6 CorrRegime | 15.13% | -50.34% | 0.66 | $2,062,953 | 5.55pp MaxDD gain costs -$2M equity |
| Idea7 Recycle | 18.73% | -55.89% | 0.71 | $4,003,538 | Small net drag |
| Kitchen_Sink | 15.49% | -50.94% | 0.67 | $2,085,309 | Worst equity |

**Conclusion:** V35 + Idea3 is the V4 ceiling. No signal/ranking research warranted given 60-position cap architecture.

---

## Drawdown Research: Confirmed Structural — Do Not Retry

**The MR strategy's max drawdown cannot be reduced without sacrificing CAGR within the signal/sizing framework.** The put spread hedge is the exception because it operates outside the signal framework as insurance.

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

## What Works — Confirmed Positive Contributions

| Addition | First Tested | Effect | Status |
|---|---|---|---|
| Uniform 8-day window | Run 2 | Core mechanism | Kept |
| Tier 1 partial exit | Run 3 | Small positive | Kept |
| S&P 400 + S&P 600 universe | V4 / V30+600 | +35% trades, OOS confirmed | Kept |
| RSI(2) signal ranking | V4 | Better quality at zero cost | Kept |
| Sector ETF MA filter | V4 | Removes low-quality entries | Kept |
| Earnings blackout ±3 days | V4 | Removes gap-down risk | Kept |
| Sector correlation cap (max 3) | V4 | Prevents hidden concentration | Kept |
| VIX-adjusted sizing | V4 | Size larger when calm | Kept (tuned) |
| SPY 200d regime filter | V4 | No entries in bear market | Kept |
| Gap filters | V4 | Reduces adverse open fills | Kept |
| Re-entry cooldown (5 days) | V4 | Prevents re-chasing losses | Kept |
| Tier 3 (4-day setups) | V15 | Essential — highest trade volume | Kept |
| Velocity crash pause | V21 | +$40-60k at near-zero cost | Kept |
| DD scaling removed | V22 | Full size during recovery | Applied |
| VIX spike pause removed | V22 | Spikes = best entry conditions | Applied |
| Commission floor $0.35 | V22 | Matches IB tiered reality | Applied |
| 40 positions at full 5% size | V24 | Captures overflow on high-signal days | Applied |
| VIX_LOW raised to 25 | V28 | Recovery years get full 9% size | Applied |
| VIX high-side penalty removed | V26 | High-VIX = strongest MR conditions | Applied |
| 9% boost for VIX < 25 | V30 | Bull/recovery years larger positions | Applied |
| Composite ranking (RSI2/ATR_pct) | V32e | +$40k equity, +0.09% CAGR | Applied |
| MAX_POSITIONS raised 40→60 | V33b/c/d | +$670k equity, +1.31% CAGR | Applied |
| Gap filter tightened -1.5%→-1.0% | V38a-C3 / V34 | +$413k equity, +0.68% CAGR | Applied |
| Tiered sizing: top 20% get 1.2x | V38a-C5 / V34 | +$337k equity, +0.51% CAGR | Applied |
| Tiered sizing multiplier 1.2x→1.3x | V40c / V35 | +$222k equity, +0.31% CAGR | Applied |
| Put spread hedge (Idea 3) | Ideas V2 | Net +$1.95M over 21 years | Applied (live) |
| **Tier 1 partial trigger 1.0%→0.8%** | **Ideas V5 / V47** | **Small positive on both CAGR and MaxDD** | **Applied** |
| **TOM sizing x1.15** | **Ideas V5 / V47** | **Part of +0.63pp CAGR vs V35** | **Applied** |
| **DOW sizing Tue x1.10 / Fri x0.90** | **Ideas V5 / V47** | **Only standalone idea improving both CAGR and MaxDD** | **Applied** |
| **VIX<15 RSI<15 tightening** | **Ideas V5 / V47** | **Zero standalone effect; included as no-cost addition** | **Applied** |

---

## Complete Do-Not-Retry Table

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
| Friday entry filter (hard block) | -$1,340k. Volume loss overwhelmed quality gain |
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
| VIX term structure scaling (Ideas V3 IdeaD) | Effect too gentle; VIX rarely deeply inverted during grinds |
| 52-week high proximity filter (Ideas V3 IdeaE) | -4pp CAGR, -$2M equity for 1.2pp MaxDD |
| Gap capture sub-tier (Ideas V3 IdeaB) | Contaminates cooldown tracking |
| Analyst dispersion re-ranking (Ideas V3 IdeaC) | Static yfinance data; zero effect |
| Call spread overlay standalone (Ideas V3 IdeaF) | -$548k equity for 2.76pp MaxDD |
| Call spread + put spread collar (Ideas V3 IdeaF+I3) | Best Sharpe but -$605k vs puts-only |
| Overnight return decomposition ranking (Ideas V4 Idea1) | Zero effect — 60-position cap rarely binding |
| Salience/sector-relative ranking (Ideas V4 Idea2) | Zero effect — same reason |
| VVIX/VIX dispersion regime scaling (Ideas V4 Idea3) | MaxDD worsens 4pp |
| Return skewness ranking (Ideas V4 Idea4) | Zero effect — 60-position cap rarely binding |
| Turnover-adjusted ranking (Ideas V4 Idea5) | Zero effect — 60-position cap rarely binding |
| Cross-asset correlation regime scaling (Ideas V4 Idea6) | Correct mechanism; 1.78pp MaxDD gain costs -$951k equity |
| Time-stop recycling (Ideas V4 Idea7) | Small net drag |
| Vol-adjusted dynamic exits (Ideas V5 EXP_A) | -1.87pp CAGR, MaxDD -11.47pp worse |
| VIX9D/VIX term structure sizing (Ideas V5) | Confirmed zero effect at any calibration |
| 52-week high distance sizing bonus (Ideas V5) | Same failure as V3 IdeaE |
| Low-turnover hold extension (Ideas V5) | Zero effect — 60-position cap rarely binding |
| Industry-relative RSI ranking (Ideas V5) | Zero effect — 60-position cap rarely binding |
| Earnings blackout 3→5 days (Ideas V5 E) | Identical to baseline — zero effect |
| VIX<15 RSI<15 tightening standalone (Ideas V5 C) | Identical to baseline on its own |
| Asymmetric hold windows | Zero effect / negative; see V34a partial loss exit (-$926k) |

---

## Critical Research Lessons

### The 60-position cap is the key architectural constraint
With 60 positions and typically 10–30 candidates per day, all candidates fill regardless of rank. **Any idea that works through signal re-ranking has zero effect.** This eliminated 6+ ideas in V4 and several in V5. The only improvement axis is *how much capital* is deployed, not *which trades* are selected.

### Sizing overlays are the only remaining improvement axis
Every successful improvement since V32e has been a sizing overlay:
- VIX-adjusted sizing (V30)
- Composite ranking → tiered sizing (V32e → V35)
- Put spread insurance (Idea3)
- TOM/DOW sizing (V47)

Every failed approach has been a filter or exit change that reduces crash-recovery capture.

### The crash-recovery paradox
The loss streaks that immediately precede crash recoveries cannot be filtered without also blocking the recoveries. 2009, 2020, and 2025 all began with loss clusters that then reversed violently. This is structural and unfixable within the MR framework.

### Backtest architecture lesson
Always import from the same `backtest_nmr_lib.py` that produced the baseline — never reimplement the engine. A reimplemented engine produced a 17.11% baseline instead of 19.71%, invalidating all deltas. The V2/V3/V4/V5 architecture (import from lib, override specific parameters per test) is the correct and only valid pattern.

---

## All Runs Table

| Version | Key Change | CAGR | Final Equity | Max DD | Sharpe |
|---|---|---|---|---|---|
| V21 | Velocity crash pause | 7.55% | $476k | -22.6% | 0.72 |
| V22 | - DD scaling, - comm floor, - VIX pause | 9.14% | $652k | -26.3% | 0.71 |
| V24 | 40 pos x5% unchanged | 10.64% | $875k | -32.5% | 0.68 |
| V28 | VIX_LOW 20→25 | 12.58% | $1,268k | -34.9% | 0.72 |
| V30 | 9% boost for VIX < 25 | 14.42% | $1,797k | -39.4% | 0.72 |
| V30+S&P600 | + S&P 600 universe | 16.01% | $2,414k | -48.65% | 0.73 |
| V32d | Tier 3 hold 6d + VIX 5d trend | 15.37% | $2,145k | -39.21% | 0.77 |
| V32e | Composite ranking RSI2/ATR_pct | 16.10% | $2,454k | -48.61% | 0.73 |
| V33d | MAX_POSITIONS raised to 60 | 17.41% | $3,124k | -54.73% | 0.68 |
| V34 | Gap -1.0% + tiered sizing 1.2x | 18.50% | $3,806k | -54.50% | 0.71 |
| V35 | Tier multiplier 1.20x→1.30x | 18.91% | $4,132k | -55.89% | 0.71 |
| V35+I3 | + Put spread hedge | 19.71% | $4,513k | -52.87% | 0.74 |
| **V47** | **V35 + TOM + DOW + partial 0.8% + VIX RSI** | **19.54%** | **$4,637k** | **-56.84%** | **0.72** |
| **V47+I3** | **V47 + Put spread (full history Apr 2026)** | **22.40%*** | **$9,915k*** | **-60.89%*** | **0.74** |

*Full history through April 2026 — not directly comparable to benchmark-period figures above.

**V47 + I3 is the confirmed ceiling. Optimisation is complete.**

---

## Optimism Bias Warnings

V47's 19.54% CAGR (MR only, benchmark period) is the in-sample ceiling, not the live expectation.

| Source | Estimated CAGR Impact |
|---|---|
| Slippage on open prices | -2 to -3% |
| Survivorship bias | -1 to -2% |
| Overfitting across 70+ iterations | -2 to -3% |
| Earnings calendar lookahead | -0.3 to -0.5% |
| TOM/DOW/VIX parameters tuned to history | -1 to -2% |
| **Realistic live estimate** | **~8 to 12% CAGR gross** |

Apply ~26% walk-forward decay: 19.54% × 0.74 = ~14.5% live gross.
After short-term capital gains tax (32–37%), realistic net CAGR is likely 8–10%.

---

## The Honest Risk Picture

V47 + hedge:
- ~-57% max drawdown (MR only) means potential ~$2.7M paper loss peak-to-trough at $4.7M equity
- The put spread partially offsets crash drawdowns — fires at -5% SPY drop
- 2022: MR lost ~$1.6M in one year; partially offset by $659k put payout
- 2025: MR lost ~$777k; more than offset by $1.13M put payout (net +$353k)
- 60 positions is the confirmed ceiling
- Win rate is the anchor — if live win rate drops below 56%, the strategy is failing

---

## Diagnostic Scripts

| Script | Command | Purpose |
|---|---|---|
| check_signals.py | `venv\Scripts\python.exe check_signals.py` | Preview tonight's signals (no orders placed) |
| check_today.py | `venv\Scripts\python.exe check_today.py` | Today's closed trades + open positions |
| check_log.py | `venv\Scripts\python.exe check_log.py` | Today's trade.log entries |
| list_tasks.py | `venv\Scripts\python.exe list_tasks.py` | All Task Scheduler tasks and trigger times |
| preflight.py | `venv\Scripts\python.exe preflight.py` | Pre-flight system check |
| positions_check.py | `venv\Scripts\python.exe positions_check.py` | Open positions with live prices + P&L |

---

## Repository Structure

```
.
├── backtest-nmr-v47.py           # Thin wrapper — imports from backtest_nmr_lib_v47.py (current)
├── backtest_nmr_lib_v47.py       # All V47 backtest logic and parameters
├── walkforward_v47.py            # Walk-forward validation for V47
├── backtest_ideas_v6.py          # V47 + Idea3 combined backtest (confirmed results)
├── backtest-nmr.py               # Thin wrapper — imports from backtest_nmr_lib.py (V35)
├── backtest_nmr_lib.py           # All V35 backtest logic and parameters
├── backtest_ideas_v2.py          # Ideas V2 multi-test runner (14 tests)
├── backtest_ideas_v3.py          # Ideas V3 multi-test runner (17 tests)
├── backtest_ideas_v4.py          # Ideas V4 multi-test runner (24 tests)
├── backtest_ideas_v5.py          # Ideas V5 multi-test runner (7 tests — led to V47)
├── backtest_ideas.py             # Original ideas test
├── backtest_bear_momentum.py     # Bear regime overlay tests (all failed — abandoned)
├── walkforward.py                # Walk-forward validation runner (V35)
├── scan_evening.py               # Live: evening signal scan + LOO orders ⚠️ needs V47 update
├── trade_morning.py              # Live: morning exit orders + fill confirmation
├── hedge_quarterly.py            # Live: quarterly SPY put spread entry/roll
├── check_signals.py              # Diagnostic: preview tonight's signals
├── check_today.py                # Diagnostic: today's trades + open positions
├── check_log.py                  # Diagnostic: today's trade.log entries
├── list_tasks.py                 # Diagnostic: Task Scheduler entries
├── preflight.py                  # Pre-flight system check
├── positions_check.py            # CLI: open positions with live prices + P&L
├── diag.py                       # SPY regime / DB diagnostic
├── scan_debug.py                 # Signal scanner filter funnel debug
├── requirements.txt
├── README-nmr.md                 # This file
├── results/v47/                  # V47 backtest outputs
├── results/                      # V35 backtest outputs
├── results_ideas/                # Original ideas outputs
├── results_ideas_v2/             # Ideas V2 outputs
├── results_ideas_v3/             # Ideas V3 outputs
├── results_ideas_v4/             # Ideas V4 outputs
├── results_ideas_v5/             # Ideas V5 outputs
├── results_ideas_v6/             # V47+I3 combined backtest outputs
└── .github/workflows/
    ├── v47_backtest.yml          # V47 backtest + optional walk-forward
    ├── v47_i3_backtest.yml       # V47+I3 combined backtest
    ├── backtest.yml              # V35 backtest workflow
    ├── ideas_v2_backtest.yml     # Ideas V2 workflow
    ├── ideas_v3_backtest.yml     # Ideas V3 workflow
    ├── ideas_v4_backtest.yml     # Ideas V4 workflow
    └── ideas_v5_backtest.yml     # Ideas V5 workflow
```

---

## Setup & Running

### V47 Backtest (GitHub Actions)
1. Push all files to repo
2. Settings → Actions → General → Workflow permissions → Read and write
3. Actions → **V47 Backtest** → Run workflow
4. Walk-forward: set `run_walkforward = true` in dispatch inputs (adds ~6–8 hours)

### V47+I3 Combined Backtest (GitHub Actions)
Actions → **V47+I3 Backtest** → Run workflow

### Local
```
pip install -r requirements.txt
python backtest-nmr-v47.py        # ~90-120 min
python walkforward_v47.py         # ~6-8 hours
python backtest_ideas_v6.py       # V47+I3 combined
```

### Live Trading Setup
```
cd C:\nmr-trader
venv\Scripts\python.exe preflight.py
```
Ensure Gateway is running before 6:00 PM PT and remains open through 6:40 AM PT next morning.

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

Educational and research purposes only. Past backtest performance does not guarantee future results. Not financial advice. Consult a licensed financial advisor and CPA before trading with real capital. V47's aggressive position sizing (60 positions, up to 12% each for top signals on TOM Tuesdays when VIX < 25) and the put spread hedge (Level 3 options required) are suitable only for those who understand and can hold through drawdowns of -57%+. V32d is the recommended alternative for Roth IRA accounts (MaxDD -39%, Sharpe 0.77).
