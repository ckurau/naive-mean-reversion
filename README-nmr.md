# Naive Mean Reversion (NMR) Backtest

A survivorship-bias-free backtest of a Naive Mean Reversion strategy across all historical S&P 500 + S&P 400 MidCap + S&P 600 SmallCap constituents, automated via GitHub Actions.

---

## Current Version: V7.4 — Idea G + GOLD + SECROT + TLT Bear + Factor Rotation + VIX Call Scaling

**Active strategy: V47 base logic + dynamic SPY put spread strikes + monthly VIX call spread (scaled in backwardation) + GLD trend overlay + sector rotation momentum overlay + TLT bear overlay + QQQ/IWM factor rotation overlay.**

V47 = V35 + four confirmed positive sizing overlays (TOM sizing, DOW sizing, partial trigger tuning, VIX RSI tightening).
Idea G = V47 + Idea D (VIX-regime-conditional put spread strikes) + Idea A (monthly VIX 20/40-call spread).
V7.3 = Idea G + GOLD overlay (7% GLD when GLD > 200d MA + rates falling) + SECROT overlay (top-3 SPDR sectors by 3m momentum, 3% each, bull regime only).
V7.4 = V7.3 + Idea I (TLT bear overlay, 8% when SPY < 200d MA + TLT > 50d MA) + Idea J (QQQ/IWM factor rotation, 6% monthly, bull regime) + Idea K (VIX call allocation doubles to 0.6% when VIX > VIX3M backwardation).

Walk-forward validated through V47: 7/8 OOS windows positive, OOS avg CAGR 20.91%.
Idea G confirmed via backtest_ideas_v7_2.py (full history through April 2026).
V7.3 confirmed via backtest_ideas_v7_3.py (full history through April 2026).
V7.4 confirmed via backtest_ideas_v7_4_final.py (full history through April 2026).

---

## Architecture

```
backtest_ideas_v7_4_final.py  V7.4 final backtest (V7.3 + TLT Bear + Factor Rotation + VIX Call Scaling)
backtest_ideas_v7_4.py        V7.4 research: 6 ideas × 10 tests, all vs V7.3 baseline
backtest_ideas_v7_3.py        V7.3 combined backtest (Idea G + GOLD + SECROT overlays, single combined equity)
backtest_ideas_v7_2.py        Idea G combined backtest (V47 + dynamic put spread + VIX calls)
backtest_nmr_lib_v47.py   All V47 backtest logic and parameters (unchanged)
backtest-nmr-v47.py       Thin wrapper for V47 MR-only backtest
walkforward_v47.py        Walk-forward validation for V47

scan_evening.py           Live: 6:00 PM PT — MR signal scan, queues signals to DB (NO orders placed)
hedge_quarterly.py        Live: 6:05 PM PT — SPY put spread (dynamic strikes) + VIX call spread (Idea K: scaled in backwardation)
overlay_etf.py            Live: 6:10 PM PT — GOLD + SECROT + TLT Bear (Idea I) + Factor Rotation (Idea J) via MOC
trade_morning.py          Live: 6:00 AM PT — places MOO entry orders, submits exits, confirms fills
```

**Four-script live execution:**
- `scan_evening.py`    — 6:00 PM PT, scans universe, saves signal candidates to DB (no IBKR orders)
- `hedge_quarterly.py` — 6:05 PM PT, manages SPY put spread + VIX call spread (Idea K: 2x allocation in backwardation)
- `overlay_etf.py`     — 6:10 PM PT, manages GLD, SPDR sectors, TLT bear (Idea I), QQQ/IWM factor (Idea J) via MOC
- `trade_morning.py`   — 6:00 AM PT, places MOO entry orders, submits MOO exits, confirms fills, pushes to GitHub

**Critical timing note:** MOO/LOO (OPG) orders are only valid 7:00–9:28 AM ET. Orders submitted at 6 PM PT (9 PM ET) return ValidationError 321 and are silently dropped. scan_evening.py saves signals to DB only. trade_morning.py places MOO orders at 6:00 AM PT (9:00 AM ET) — within the valid window.

---

## Best Confirmed Results

### V7.4 — Full History Run (April 2026) — COMBINED EQUITY

| Metric | Value | Notes |
|---|---|---|
| CAGR (MR-only basis) | 28.08% | MR engine unchanged from V47 |
| CAGR (combined equity) | 32.85% | MR + all six overlays |
| Final Equity (combined) | $56,457,642 | MR + SPY puts + VIX calls + GOLD + TLT + SECROT + Factor |
| Max Drawdown (combined) | -57.17% | Full portfolio including all overlay payouts |
| Sharpe (combined) | 1.04 | Improved from 0.96 (V7.3) |
| Win Rate | 60.25% | MR-only, unchanged |
| Profit Factor | 1.04 | MR-only |
| Total MR trades | 22,043 | |
| MR trades P&L | +$20,412,295 | |
| SPY put premiums paid | -$10,435,993 | |
| SPY put payouts received | +$17,111,851 | |
| SPY put net P&L | +$6,675,858 | |
| VIX call premiums paid | -$12,888,479 | Idea K: higher in backwardation periods |
| VIX call payouts received | +$27,413,214 | |
| VIX call net P&L | +$14,524,734 | **+$7.7M vs V7.3 from Idea K alone** |
| GOLD overlay net P&L | +$4,830,514 | |
| TLT bear net P&L | +$1,161,625 | **NEW — Idea I** |
| SECROT overlay net P&L | +$5,732,218 | |
| Factor rotation net P&L | +$3,020,396 | **NEW — Idea J** |
| Total overlay net P&L | +$35,945,346 | All six overlays combined |

**V7.4 vs V7.3 baseline:**

| Metric | V7.3 | V7.4 | Delta |
|---|---|---|---|
| CAGR (combined) | 29.30% | 32.85% | **+3.55pp** |
| Final Equity | $30,877,877 | $56,457,642 | **+$25,579,765** |
| Max Drawdown | -56.62% | -57.17% | -0.55pp |
| Sharpe | 0.96 | 1.04 | +0.08 |

**MaxDD note:** The -0.55pp MaxDD widening vs V7.3 is acceptable given +$25.6M in additional equity. The absolute dollar drawdown at the trough is larger because the portfolio is 83% larger — the percentage is nearly unchanged. Overlays now generate more P&L ($35.9M) than the core MR strategy ($20.4M).

### V7.4 Year-by-Year (Combined Equity)

| Year | End Equity | P&L |
|---|---|---|
| 2004 | $122,105 | +$22,105 |
| 2005 | $169,179 | +$47,074 |
| 2006 | $239,063 | +$69,883 |
| 2007 | $322,834 | +$83,771 |
| 2008 | $517,855 | +$195,021 |
| 2009 | $946,488 | +$428,634 |
| 2010 | $1,344,101 | +$397,613 |
| 2011 | $2,128,785 | +$784,684 |
| 2012 | $2,685,557 | +$556,772 |
| 2013 | $4,612,802 | +$1,927,246 |
| 2014 | $5,390,288 | +$777,486 |
| 2015 | $7,084,455 | +$1,694,167 |
| 2016 | $8,227,720 | +$1,143,265 |
| 2017 | $12,320,854 | +$4,093,135 |
| 2018 | $11,192,565 | -$1,128,290 |
| 2019 | $20,796,187 | +$9,603,623 |
| 2020 | $36,569,372 | +$15,773,185 |
| 2021 | $44,523,220 | +$7,953,848 |
| 2022 | $39,725,356 | -$4,797,864 |
| 2023 | $42,095,340 | +$2,369,983 |
| 2024 | $56,303,659 | +$14,208,319 |
| 2025 | $61,124,702 | +$4,821,043 |
| 2026 | $56,457,642 | -$4,667,060 |

### V7.3 — Full History Run (April 2026) — COMBINED EQUITY

| Metric | Value | Notes |
|---|---|---|
| CAGR (MR-only basis) | 24.51% | Consistent with V48 MR-only |
| CAGR (combined equity) | 27.64% | MR + all overlays |
| Final Equity (combined) | $23,116,132 | MR + SPY puts + VIX calls + GOLD + SECROT |
| Max Drawdown (combined) | -52.22% | **Improved +4.69pp vs V48** |
| Sharpe (combined) | 0.97 | Improved from 0.74 (V48) |
| Win Rate | 60.26% | MR-only |
| Profit Factor | 1.05 | MR-only |
| MR trades P&L | +$11,066,347 | 22,035 trades |
| SPY put premiums paid | -$4,337,433 | |
| SPY put payouts received | +$7,302,370 | |
| SPY put net P&L | +$2,964,937 | |
| VIX call premiums paid | -$5,019,365 | |
| VIX call payouts received | +$9,733,200 | |
| VIX call net P&L | +$4,713,835 | |
| GOLD overlay net P&L | +$1,861,720 | 3,288 days in position |
| SECROT overlay net P&L | +$2,409,293 | 12,510 day-sector records |
| Total overlay net P&L | +$11,949,785 | SPY puts + VIX calls + GOLD + SECROT |

**V7.3 vs V48/Idea G baseline:**

| Metric | V48/Idea G | V7.3 | Delta |
|---|---|---|---|
| CAGR (MR-only) | 24.38% | 24.51% | +0.13pp |
| CAGR (combined) | — | 27.64% | — |
| Final Equity | $18,323,346 | $23,116,132 | **+$4,792,786** |
| Max Drawdown | -56.91% | -52.22% | **+4.69pp ✓ IMPROVED** |
| Sharpe | 0.74 | 0.97 | +0.23 |

### V7.3 Year-by-Year (Combined Equity)

| Year | End Equity | P&L |
|---|---|---|
| 2004 | $120,315 | +$20,315 |
| 2005 | $165,216 | +$44,902 |
| 2006 | $229,553 | +$64,337 |
| 2007 | $296,237 | +$66,683 |
| 2008 | $415,916 | +$119,679 |
| 2009 | $703,183 | +$287,267 |
| 2010 | $935,109 | +$231,926 |
| 2011 | $1,352,028 | +$416,919 |
| 2012 | $1,671,619 | +$319,591 |
| 2013 | $2,733,317 | +$1,061,698 |
| 2014 | $3,166,651 | +$433,334 |
| 2015 | $4,061,752 | +$895,101 |
| 2016 | $4,603,014 | +$541,262 |
| 2017 | $6,646,103 | +$2,043,089 |
| 2018 | $6,032,276 | -$613,828 |
| 2019 | $10,672,344 | +$4,640,069 |
| 2020 | $16,734,584 | +$6,062,240 |
| 2021 | $19,874,931 | +$3,140,347 |
| 2022 | $17,600,653 | -$2,274,279 |
| 2023 | $18,040,759 | +$440,106 |
| 2024 | $23,589,167 | +$5,548,409 |
| 2025 | $24,551,699 | +$962,532 |
| 2026 | $23,116,132 | -$1,435,567 |

### V48 / Idea G — Full History Run (April 2026) — COMBINED EQUITY

| Metric | Value | Notes |
|---|---|---|
| CAGR | 24.38% | MR-only CAGR; combined includes overlay P&L |
| Final Equity (combined) | $18,323,346 | MR + SPY put spread + VIX call spread |
| Max Drawdown (combined) | -56.91% | Full portfolio including overlay payouts |
| Sharpe Ratio | 0.74 | MR-only basis |
| Win Rate | 60.25% | |
| Profit Factor | 1.06 | |
| SPY put premiums paid | -$4,313,802 | |
| SPY put payouts received | +$7,262,321 | |
| SPY put net P&L | +$2,948,519 | |
| VIX call premiums paid | -$4,935,793 | |
| VIX call payouts received | +$9,430,338 | |
| VIX call net P&L | +$4,494,545 | |
| Total overlay net P&L | +$7,443,064 | SPY puts + VIX calls combined |

**Combined equity MaxDD note:** The -56.91% combined MaxDD reflects the full portfolio including overlay payouts received during crash events. VIX call payouts during 2008, 2020, and 2025 land in the account simultaneously with worst MR drawdown months, visibly lifting the combined equity curve through the crash trough.

### V47 + Idea G vs Baseline (Idea G research, April 2026)

| Metric | Baseline V47+I3 | Idea G (V48) | Delta |
|---|---|---|---|
| CAGR | 22.44% | 24.38% | **+1.94pp** |
| Final Equity (combined) | $9,972,142 | $18,323,346 | **+$8,351,204** |
| Max Drawdown (combined) | -57.18% | -56.91% | **+0.27pp better** |
| Sharpe | 0.74 | 0.74 | 0 |

### V47 + Idea 3 (Previous Recommended — reference benchmark)

| Metric | Value |
|---|---|
| CAGR | 22.40% |
| Max Drawdown (MR-only) | -60.89% |
| Sharpe Ratio | 0.74 |
| Profit Factor | 1.06 |
| Final Equity (from $100k) | $9,915,308 |
| Period | 2004–2026 benchmark date |

### V47 Baseline (No Hedge)

| Metric | Value |
|---|---|
| CAGR | 19.54% |
| Max Drawdown | -56.84% |
| Sharpe Ratio | 0.72 |
| Final Equity (from $100k) | $4,637,314 |

### V32d (Roth IRA / Lower Drawdown Tolerance)

| Metric | Value |
|---|---|
| CAGR | 15.37% |
| Max Drawdown | -39.21% |
| Sharpe Ratio | 0.77 |
| Final Equity (from $100k) | $2,144,611 |

---

## Strategy Comparison

| Strategy | CAGR | Equity | MaxDD | Sharpe | Best For |
|---|---|---|---|---|---|
| **V7.4 (current, combined)** | **32.85%** | **$56.5M** | **-57.17%** | **1.04** | **Max wealth, full overlay stack** |
| V7.3 (previous best) | 29.30% | $30.9M | -56.62% | 0.96 | V7.3 overlays, no I/J/K |
| V48 / Idea G (previous best) | 24.38% | $18.3M | -56.91% | 0.74 | Idea G only, no ETF overlays |
| V47 + Idea 3 (previous benchmark) | 22.40% | $9.9M | -60.89%* | 0.74 | Previous recommended |
| V47 (no hedge) | 19.54% | $4.6M | -56.84% | 0.72 | Max wealth, taxable, no hedge |
| C_TurnOfMonth | 16.20% | $2.5M | -48.91% | 0.71 | Middle ground |
| V32d | 15.37% | $2.1M | -39.21% | 0.77 | Roth IRA, lower DD tolerance |

*V47+I3 MaxDD was MR-only. Combined equity MaxDD is -57.18% (also confirmed in V7.2 research).

---

## V7.4 Strategy Rules

All V47 and Idea G rules apply unchanged. V7.4 adds three new overlays on top of V7.3.

### MR Rules (V47, unchanged)

| Rule | Detail |
|---|---|
| Universe | S&P 500 + S&P 400 MidCap + S&P 600 SmallCap (current + historical) |
| Trend filter | Stock must be above its 200-day SMA |
| Entry signal | 4+ consecutive down days AND RSI(2) < 20 AND ATR > 1% AND volume > 20-day avg AND dollar volume > $5M/day |
| Entry execution | Buy at open via MOO order placed at 6:00 AM PT (9:00 AM ET pre-market window) |
| Gap filters | Skip if next open gaps down > 1.0% OR gaps up > 2% |
| Exit — all tiers | 2% profit target, 8-day time stop |
| Tier 1 partial | 6+ down days: 50% at **0.8%**, remainder at 2% |
| Tier 2 | 5 down days: 2% target, 8-day window |
| Tier 3 | 4 down days: 2% target, 8-day window |
| Min hold | 2 calendar days before profit exit |
| Max positions | 60 simultaneous holdings |
| Position size base | VIX < 25 → 9%, VIX ≥ 25 → 5% |
| Tiered sizing | Top 20% of signals by composite score get 1.3x, hard cap 12% |
| TOM sizing | Last trading day of month + next 3: 1.15x multiplier |
| DOW sizing | Tuesday: 1.10x \| Friday: 0.90x |
| VIX RSI tight | When VIX < 15: require RSI(2) < 15 |
| Signal ranking | Composite score: RSI(2) / ATR_pct |
| Sector filter | Skip if stock's sector ETF below 20-day MA |
| Correlation cap | Max 3 open positions in same sector |
| Earnings blackout | Skip within ±3 days of earnings |
| SPY regime | No new entries when SPY below 200-day MA |
| Re-entry cooldown | No re-entry for 5 days after time-stop |
| Velocity crash pause | SPY 5-day return < -12% → pause entries 5 days |
| Earnings month cap | Position size capped at 2.4% in Jan/Apr/Jul/Oct |

### Idea G: Dynamic SPY Put Spread (hedge_quarterly.py, unchanged)

| Parameter | Value |
|---|---|
| Long put | **VIX-conditional** (see table below) |
| Short put | **VIX-conditional** (see table below) |
| Target DTE | 63 trading days (~quarterly) |
| Contracts | 1 (appropriate for $100k–$300k account) |
| Max debit | $15/contract (refuses if too expensive) |
| Auto-roll | Yes — closes and reopens when ≤5 days to expiry |

**Dynamic strike selection (Idea D / Idea G):**

| VIX Regime | Long put OTM | Short put OTM | Rationale |
|---|---|---|---|
| VIX < 15 (cheap options) | 3% OTM | 13% OTM | Tight strikes = more payout per dollar |
| VIX 15–25 (baseline) | 5% OTM | 15% OTM | Same as V47+I3 (unchanged) |
| VIX > 25 (expensive options) | 8% OTM | 20% OTM | Wide strikes = stay under $15 debit cap |

### Idea G: Monthly VIX Call Spread (hedge_quarterly.py) + Idea K Scaling (NEW V7.4)

| Parameter | Value |
|---|---|
| Long call | VIX 20-strike |
| Short call | VIX 40-strike |
| Target DTE | 21 trading days (~monthly) |
| Cost (standard) | ~0.3% of portfolio per month ($900/mo at $300k) |
| Cost (Idea K) | ~0.6% of portfolio per month when VIX > VIX3M (backwardation) |
| Max payout | 8× premium at VIX ≥ 40 (linear from VIX 20→40) |
| Max debit | $5/contract (refuses if too expensive) |
| Auto-roll | Yes — renews every ~21 trading days |

**Why VIX calls complement SPY puts:**
The quarterly SPY put spread fires when SPY drops 3–15% from its quarterly reference price. The monthly VIX call spread fires when VIX spikes rapidly — including early crash days before the SPY put spread is in-the-money, and during the 2022-style slow bear grind where SPY never drops 15%+ in one quarter.

**Historical VIX call payout events (backtest):**

| Event | VIX Peak | Est. Monthly Payout |
|---|---|---|
| 2008 GFC | ~80 | 8× premium (~$5k early / $35k+ late) |
| 2011 sovereign crisis | ~48 | ~7× premium |
| 2018 Volmageddon | ~37 | ~4× premium |
| 2020 COVID | ~82 | 8× premium |
| 2022 bear grind | ~38 | ~5× premium (multiple months) |
| 2025 tariff crash | ~52 | 8× premium |

**Idea K: VIX Call Scaling in Backwardation (NEW V7.4)**
When VIX spot > VIX 3-month (backwardation), the term structure signals elevated stress — the market is pricing near-term risk higher than future risk. In these periods, doubling the VIX call allocation means dramatically larger payouts when the spike materializes. `hedge_quarterly.py` fetches `^VIX3M` from yfinance at each renewal and sets cost_pct to 0.6% if in backwardation, 0.3% if in contango.

**V7.4 VIX call overlay (backtest, 2004–2026):**
- Premiums paid: -$12,888,479
- Payouts received: +$27,413,214
- Net P&L: **+$14,524,734** (+$7.7M vs fixed 0.3% allocation)

**V7.3 VIX call overlay (reference, fixed 0.3%):**
- Premiums paid: -$4,935,793
- Payouts received: +$9,430,338
- Net P&L: +$4,494,545

### V7.3: GOLD Overlay (overlay_etf.py, NEW)

| Parameter | Value |
|---|---|
| Instrument | GLD (SPDR Gold ETF) |
| Allocation | 7% of portfolio equity while in position |
| Entry signal | GLD > GLD 200-day MA AND TLT 20-day slope ≥ 0 (nominal rates falling) |
| Exit signal | GLD breaks below 200-day MA |
| Order type | MOC (Market on Close) via overlay_etf.py at 6:10 PM PT |
| Sizing reference | Current combined portfolio value (mark-to-market) |
| Backtest P&L | +$1,861,720 over full history (3,288 days in position) |

**Why GOLD complements MR:** Gold's negative correlation with equities during drawdowns (2008: +5.5%, 2020: +24.5%) provides partial hedging when MR is most exposed. The TLT slope filter prevents entering during rising rate environments where gold underperforms. Completely orthogonal to MR signals — fires on different triggers, different assets, different timeframe.

### V7.3: SECROT Overlay (overlay_etf.py, NEW)

| Parameter | Value |
|---|---|
| Instruments | Top-3 SPDR sector ETFs (XLK, XLV, XLF, XLE, XLI, XLY, XLP, XLU, XLB, XLRE, XLC) |
| Allocation | 3% per sector (9% total when fully allocated) |
| Signal | Rank all 11 SPDR sectors by 63-day (3-month) momentum, long top 3 |
| Rebalance | Monthly (first trading day of each month) |
| Regime filter | Only active when SPY > SPY 200-day MA (matches MR bull regime filter) |
| Exit to cash | When SPY breaks below 200-day MA |
| Order type | MOC (Market on Close) via overlay_etf.py at 6:10 PM PT |
| Backtest P&L | +$2,409,293 over full history (12,510 day-sector records) |

**Why SECROT complements MR:** Sector momentum captures systematic rotation between sectors that MR doesn't exploit. The bull regime filter means SECROT exits to cash exactly when MR stops entering — they share the same SPY 200d MA gating logic. Combined MaxDD improved +4.69pp vs V48 despite adding long equity exposure, because sector momentum's regime exit removes equity beta during the worst drawdown periods.
### V7.4: TLT Bear Overlay (overlay_etf.py — Idea I, NEW)

| Parameter | Value |
|---|---|
| Instrument | TLT (iShares 20yr Treasury ETF) |
| Allocation | 8% of portfolio equity while in position |
| Entry signal | SPY < SPY 200-day MA (bear regime) AND TLT > TLT 50-day MA |
| Exit signal | SPY re-enters bull regime OR TLT breaks below 50d MA |
| Order type | MOC (Market on Close) via overlay_etf.py at 6:10 PM PT |
| Sizing reference | Current combined portfolio value (mark-to-market) |
| Backtest P&L | +$1,161,625 over full history (V7.4 combined) |

**Why TLT Bear complements MR:** When SPY breaks below its 200d MA, MR stops entering new positions — the strategy goes into a dead zone. TLT activates exactly in this dead zone: flight-to-quality buying in Treasuries during equity bear markets generates return while MR is idle. The TLT 50d MA filter prevents entering during TLT downtrends (critical for 2022, when both bonds and equities fell). This is structurally different from the prior DNR "bond allocation in bear" which used IEF via mean-reversion signals — this is pure trend-following on TLT activated only when MR is already blocked.

**DB tables added:** `tlt_bear_position` — tracks current TLT position state.

### V7.4: QQQ/IWM Factor Rotation (overlay_etf.py — Idea J, NEW)

| Parameter | Value |
|---|---|
| Instruments | QQQ (Nasdaq 100) or IWM (Russell 2000 small cap) |
| Allocation | 6% of portfolio equity in the winner |
| Signal | Monthly: long whichever has stronger 63-day (3-month) momentum |
| Rebalance | First trading day of each month |
| Regime filter | Only active when SPY > SPY 200-day MA (bull regime) |
| Exit to cash | When SPY breaks below 200-day MA |
| Order type | MOC (Market on Close) via overlay_etf.py at 6:10 PM PT |
| Backtest P&L | +$3,020,396 over full history (V7.4 combined) |

**Why Factor Rotation complements MR:** SECROT rotates among 11 SPDR sectors by momentum — it captures within-equity rotation at the sector level. Factor rotation (QQQ vs IWM) operates on a different dimension: market cap and growth vs value factor cycles. In 2017, QQQ massively outperformed IWM (mega-cap tech dominance). In early 2022, IWM briefly led. These cycles are uncorrelated with both MR signals and SECROT rotation, making the P&L streams genuinely additive.

**DB tables added:** `factor_position` — tracks current QQQ/IWM position state.



---

## V7.4 Overlay Research

### V7.4 Research (backtest_ideas_v7_4.py) — 6 Ideas × 10 Tests

| Test | Comb CAGR | ΔvV7.3 | Final Equity | MaxDD | Verdict |
|---|---|---|---|---|---|
| Baseline V7.3 | 29.30% | — | $30,877,877 | -56.62% | Reference |
| Idea_H ConvexExit | 28.65% | -0.65pp | $27,581,038 | -56.44% | **DEAD** |
| Idea_I TLT Bear | 30.08% | +0.78pp | $35,289,192 | -56.59% | ✓ CONFIRMED |
| Idea_J QQQ/IWM | 30.52% | +1.22pp | $38,041,529 | -56.95% | ✓ CONFIRMED |
| Idea_K VIX Scale | 30.84% | +1.54pp | $40,174,832 | -56.80% | ✓ CONFIRMED (strongest) |
| Idea_L DBC Tilt | 29.24% | -0.06pp | $30,562,680 | -56.82% | **DEAD** |
| Idea_M Tier1 Size | 29.33% | +0.03pp | $31,014,871 | -56.64% | **NEGLIGIBLE** |
| Ideas H+I+K | 30.96% | +1.66pp | $41,012,771 | -56.55% | ✓ |
| Ideas H+I+J+K | 32.19% | +2.89pp | $50,569,905 | -56.89% | ✓ BEST COMBO |
| All 6 combined | 32.16% | +2.86pp | $50,270,089 | -56.91% | ✓ |

**Winner: I + J + K** (H added no value individually; L and M dead).

### V7.4 Final Confirmation (backtest_ideas_v7_4_final.py) — I + J + K on full history

### Methodology
All overlays tested as purely additive P&L streams on top of the V7.3 combined equity curve. Sizing references current combined portfolio value at each date (mark-to-market). This is the correct approach — overlays sized on combined equity compound properly with the underlying MR+hedge portfolio.

### Result vs V49 (Separate Baseline Test)

A separate V49 backtest tested GOLD, SECROT, and DIVCAP on top of V35 MR-only (no Idea G hedges). That test showed MaxDD worsening because the overlays added linear long exposure without the crash protection of SPY puts and VIX calls. When V7.3 adds the same overlays on top of Idea G (which already has crash protection), the combined MaxDD improves — the overlays' long equity exposure is hedged by the existing put/call overlays. This is the correct architecture.

### V7.4 Overlay P&L Summary (backtest, 2004–2026)

| Overlay | Backtest Net P&L | Notes |
|---|---|---|
| SPY put spread | +$6,675,858 | Dynamic strikes (Idea D) |
| VIX call spread | +$14,524,734 | 20/40 monthly + Idea K scaling |
| GOLD (GLD) | +$4,830,514 | 7% alloc, trend+carry signal |
| TLT Bear | +$1,161,625 | 8% alloc, bear regime — **NEW** |
| SECROT (sectors) | +$5,732,218 | 3%×3, monthly rebalance |
| Factor rotation | +$3,020,396 | 6% QQQ/IWM monthly — **NEW** |
| **Total overlays** | **+$35,945,346** | vs MR-only $20,412,295 |

**Key insight:** Overlays now generate more P&L than the core MR strategy. This is the intended architecture — diversified, structurally uncorrelated streams compounding together on top of the same capital base.

### V7.3 Overlay P&L Summary (reference)

| Overlay | Backtest Net P&L | Notes |
|---|---|---|
| SPY put spread | +$2,964,937 | Dynamic strikes (Idea D) |
| VIX call spread | +$4,713,835 | 20/40 monthly |
| GOLD (GLD) | +$1,861,720 | 7% alloc, trend+carry signal |
| SECROT (sectors) | +$2,409,293 | 3%×3, monthly rebalance |
| **Total overlays** | **+$11,949,785** | vs MR-only $11,066,347 |

---

## Idea G Research Summary (V7.2 Backtest)

Full results from `backtest_ideas_v7_2.py`. All MaxDD figures on combined equity.

| Test | CAGR | Final Equity | MaxDD (combined) | vs Baseline |
|---|---|---|---|---|
| Baseline V47+I3 | 22.44% | $9,972,142 | -57.18% | — |
| Idea_A VIX calls | 23.95% | $17,421,990 | -56.91% | +$7.4M |
| Idea_B CDaR | 21.58% | $8,544,455 | -53.38% | -$1.4M |
| Idea_D Dyn strikes | 22.84% | $10,432,502 | -57.18% | +$460k |
| **Idea_G D+A combo** | **24.38%** | **$18,323,346** | **-56.91%** | **+$8.35M** |

---

## Do-Not-Retry Table

| Approach | Why It Failed |
|---|---|
| Price-based stop-losses (-3%) | 22.6% hit stop then bounced |
| Portfolio-level halt at -10% DD | Fired permanently 2004–2006 |
| Streak filter (3 losses=50% size) | MaxDD -8pp but CAGR -4.72pp |
| Rolling WR adaptive sizing | MaxDD -7pp but CAGR -3.71pp |
| Equity curve trading | CAGR -3.30pp, MaxDD unchanged |
| Continuous vol-scaled sizing | CAGR -2.07pp, MaxDD -1pp |
| Friday entry filter | -$1,340k |
| Breadth filter (40% stocks above 20/50d MA) | -$2,899k |
| Bond allocation in bear regime | -$2,113 |
| Gap filter tightening to -0.75% | CAGR -2.59pp |
| Idea_C — VVIX-gated sizing | Confirmed dead V7 + V7.1. Add to DNR. |
| Idea_E — Gap-behavior sizing | Confirmed dead V7 + V7.1. Fires during crash-recovery. Add to DNR. |
| Idea_F — Day-5 partial time-stop | CAGR -2.49pp, MaxDD worsened |
| Idea_B CDaR scaling | Too much CAGR drag (-1.95pp) for MaxDD gain (+3.80pp) |
| TSMOM (multi-asset trend following) | Tested in V49 research on V35 baseline. Minimal CAGR add, MaxDD worsened on MR-only basis due to correlated long exposure without crash hedges. Valid concept — test again layered on Idea G if revisited. |
| VRP harvest (sell SPY puts monthly) | Tested in V49 research. Requires options pricing model not available in standard yfinance backtest. Synthetic results unreliable. May be worth testing with real options data. |
| VIX term structure carry (SVXY) | Tested in V49 research. SVXY structural decay periods hard to model accurately with synthetic data; 2018 SVXY restructuring creates survivorship issues. DNR in current framework. |
| Earnings Announcement Drift | Tested in V49 research using SPY gap days as proxy — too crude. Real EAD requires individual earnings dates and post-gap continuation data not available in bulk yfinance. |
| MR Short Book (short overbought sectors) | Tested in V49 research. RSI(2) > 80 + 4 consecutive up days on sector ETFs fires too rarely to generate meaningful P&L. |
| DIVCAP (dividend capture XLU/XLP) | Tested in V49 research on V35. +$20,301 over full history — not worth the complexity. |
| Idea_H — Convexity-adjusted exit | Tested in V7.4 research. -0.65pp CAGR, -$3.3M. Scaling profit target down on days 1-3 (1.5%) rushed exits that would have recovered; scaling down on days 7-8 (1.0%) missed full reversals. Net negative despite intuitive logic. |
| Idea_L — DBC commodity tilt on SECROT | Tested in V7.4 research. -0.06pp CAGR, -$315k. Forcing XLE+XLB into the SECROT basket overrides better momentum choices — when DBC is strong, those sectors are usually already in the top-3 anyway. |
| Idea_M — Tier 1 extended sizing (15% cap) | Tested in V7.4 research. +0.03pp CAGR, +$137k over 22 years. Tier 1 fires only ~105 times/year; at this portfolio size the extra sizing is too infrequent to move the needle. Not worth the complexity. |
| [all other V3/V4 ideas — see prior README versions] | Various — see research history |

---

## Critical Research Lessons

### Combined equity MaxDD is the correct measure for overlay strategies
When the portfolio holds both MR positions and put/call overlays simultaneously, MaxDD should be computed on the combined equity curve (MR P&L + overlay payouts). VIX call payouts received during crash months lift the combined equity through the trough — the MR-only MaxDD overstates the true investor experience. V48 and V7.3 report combined equity MaxDD throughout.

### ETF overlays must be layered on top of crash-protected baseline
V49 tested GOLD and SECROT on top of V35 MR-only and found MaxDD worsened (long equity exposure without hedges). V7.3 layers the same overlays on top of Idea G (SPY puts + VIX calls already present) and MaxDD improved +4.69pp. The lesson: additive long overlays need the underlying crash protection to work as intended. Always test overlays on the most complete baseline.

### The 60-position cap is the key architectural constraint
With 60 positions and 10–30 candidates per day, all candidates fill regardless of rank. Any idea that works through signal re-ranking has zero effect. The only improvement axis is how much capital is deployed (sizing overlays) and insurance (hedge overlays). This eliminated 6+ ideas in V4/V5 and is why Idea G succeeds — it operates entirely outside the MR signal framework.

### The crash-recovery paradox
Loss streaks immediately preceding crash recoveries cannot be filtered without blocking the recoveries. 2009, 2020, and 2025 all began with loss clusters then reversed violently. Every filter that reduces streak exposure also reduces crash-recovery capture. The hedge overlay is the only tool that addresses crash risk without touching the signal framework.

### Overlay stack P&L can exceed core strategy P&L — this is correct
At V7.4, overlay P&L ($35.9M) exceeds MR strategy P&L ($20.4M). This is not a sign of overfitting — it reflects the correct architectural principle: multiple uncorrelated return streams on the same capital base. Each overlay fires in different regimes (TLT in bear, SECROT/Factor in bull, VIX calls in spikes, GOLD in rate-falling trends), so they don't cannibalize each other. The MR engine remains the signal source; overlays are pure capital efficiency improvements.

### Always import from the same lib — never reimplement
A reimplemented backtest engine produced 17.11% baseline instead of 19.71%, invalidating all deltas. V2/V3/V4/V5/V6/V7.x all import from `backtest_nmr_lib.py` — same architecture is the only valid pattern.

---

## Paper Trading & Live Automation

**Status: LIVE (paper trading active as of April 2026)**

| Item | Detail |
|---|---|
| Broker | Interactive Brokers (IBKR) paper account |
| Starting equity | $100,000 |
| Scripts | scan_evening.py (6:00 PM) + hedge_quarterly.py (6:05 PM) + overlay_etf.py (6:10 PM) + trade_morning.py (6:00 AM) |
| Scheduler | Windows Task Scheduler — four tasks |
| Entry order queuing | scan_evening.py saves signals to DB at 6:00 PM PT (no IBKR orders) |
| Entry order execution | trade_morning.py places MOO orders at 6:00 AM PT (9:00 AM ET, within OPG window) |
| Exit orders | MOO (Market on Open) |
| ETF overlays | MOC (Market on Close) via overlay_etf.py at 6:10 PM PT |
| SPY put spread | Dynamic strikes per VIX regime, quarterly renewal |
| VIX call spread | 20/40-strike, monthly renewal |
| Options approval | Level 3 required for both SPY puts and VIX calls |
| Database | C:\nmr-trader\positions.db — SQLite |
| Scripts location | C:\nmr-trader\ |
| Git repo (local) | C:\naive-mean-reversion\ |
| Dashboard | https://ckurau.github.io/naive-mean-reversion/ |

### Task Scheduler — Days of Week

| Task | Time (PT) | Sun | Mon | Tue | Wed | Thu | Fri | Sat |
|---|---|---|---|---|---|---|---|---|
| IBC Gateway | 6:00 AM | ✓ | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| Scan Evening | 6:00 PM | ✓ | ✓ | ✓ | ✓ | ✓ | — | — |
| Hedge Quarterly | 6:05 PM | — | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| Overlay ETF | 6:10 PM | — | ✓ | ✓ | ✓ | ✓ | ✓ | — |
| NMR Trader (trade_morning) | 6:00 AM | — | ✓ | ✓ | ✓ | ✓ | ✓ | — |

**Scan Evening runs Sunday** because it queues signals for Monday's open. Friday scan is skipped — Saturday market is closed.

### Infrastructure Setup (completed April 2026)

| Component | Detail |
|---|---|
| Git repo location | `C:\naive-mean-reversion\` — cloned from GitHub, branch `main` |
| Scripts location | `C:\nmr-trader\` — separate folder, not a git repo |
| GitHub push | `trade_morning.py` writes to `C:\naive-mean-reversion\paper_trading\` and pushes after each run |
| Dashboard URL | https://ckurau.github.io/naive-mean-reversion/ (GitHub Pages, public) |
| Dashboard file | `index.html` in repo root — reads from `paper_trading/` via raw.githubusercontent.com |
| Mobile access | Open dashboard URL in Safari → Share → Add to Home Screen (works as home screen app) |
| PC sleep | Disabled on AC power (`powercfg /change standby-timeout-ac 0`) |
| Gateway | Leave running 24/7 on paper account port 4002 |

### GitHub Push — How It Works

Both `scan_evening.py` and `trade_morning.py` push to GitHub.

**`scan_evening.py` pushes at ~6:10 PM PT** (after scan completes):
- Updates `summary.json` with tonight's scan candidates, VIX, regime flags, signal count, GOLD overlay status, SECROT overlay status (active sectors + 3m momentum), TLT bear status (in/out, SPY vs MA200, TLT vs MA50), Factor rotation status (QQQ vs IWM winner, 63d momentum), VIX3M vs VIX (backwardation flag for Idea K)
- Dashboard "Last Scan" and overlay panels populate immediately after evening run

**`trade_morning.py` pushes at ~6:35 AM PT** (after fill confirmation):
1. Writes `paper_trading/summary.json` — portfolio value, VIX, win rate, today's fills/misses, log entries, hedge positions, GOLD/SECROT/TLT/Factor P&L breakdown (30d + all-time)
2. Writes `paper_trading/trades.csv` — full trade log from SQLite (includes OVL_GOLD, OVL_SECROT_*, OVL_TLT_BEAR, OVL_FACTOR_* tickers)
3. Writes `paper_trading/open_positions.csv` — current open MR positions
4. Writes `paper_trading/rejections.csv` — entry orders that didn't fill
5. Git commits and pushes to `origin main`

Dashboard at `https://ckurau.github.io/naive-mean-reversion/` auto-refreshes every 5 minutes.

**Key config in both scripts:**
```python
GITHUB_PUSH      = True
GITHUB_REPO_PATH = r'C:\naive-mean-reversion'
OUTPUT_DIR       = r'C:\naive-mean-reversion\paper_trading'
GITHUB_BRANCH    = 'main'
```

### Bugs Fixed (April 2026)

**Bug 1 — Stray PowerShell line in trade_morning.py (root cause of zero trades)**
A PowerShell command was embedded as a Python line at line 405, causing a `NameError` crash immediately before fill confirmation. LOO orders were submitted every evening but never confirmed the next morning — positions were never saved to the DB for weeks.

Fix:
```python
ib.reqExecutions()
ib.sleep(3)
filled_syms = {f.contract.symbol: f for f in ib.fills()}
```

**Bug 2 — ClientId mismatch between scan_evening.py and trade_morning.py**
`scan_evening.py` submits LOO orders with `clientId=10`. IBKR only returns fills to the same clientId that placed the order. `trade_morning.py` was connecting with `clientId=1`, so `ib.fills()` always returned empty even when orders genuinely filled.

Fix: set `IBKR_CLIENT_ID = 10` in `trade_morning.py` to match `scan_evening.py`.

**Bug 3 — LOO orders wiped by IBKR nightly session reset**
LOO orders submitted by `scan_evening.py` at 6 PM PT were cancelled by IBKR's nightly reset at ~11:45 PM ET, so no orders were present at the 9:30 AM ET open. Confirmed by checking `ib.openOrders()` the morning after — always returned 0.

Fix: add `outsideRth=True` to the LOO order in `scan_evening.py`:
```python
order = Order(
    action='BUY', totalQuantity=shares,
    orderType='LOO', lmtPrice=limit_price, tif='OPG',
    outsideRth=True,
)
```

**Bug 4 — LOO and MOO orders return ValidationError 321 at 6 PM PT**
Both LOO (Limit on Open) and MOO (Market on Open) use the OPG time-in-force, which is only valid during the pre-market window: **7:00 AM to 9:28 AM ET**. Submitting OPG orders at 6 PM PT (9 PM ET) causes `ValidationError: 'bF': cause - Invalid order type was entered` on every single order. Orders are silently dropped — no fill, no error in logs, no IBKR notification. This was the root cause of zero trades for weeks.

Diagnosis: `verify_all.py` MOO order test returned `ValidationError` at 6 PM PT. Same error for LOO. Confirmed via IBKR API documentation: OPG orders require 7:00–9:28 AM ET submission window.

Fix: **Moved order placement from `scan_evening.py` to `trade_morning.py`.**
- `scan_evening.py` (6:00 PM PT) — saves signal candidates to `pending_entries` DB only, places no IBKR orders
- `trade_morning.py` (6:00 AM PT = 9:00 AM ET) — reads pending signals, places MOO orders within the valid OPG window, waits until 6:35 AM PT for fills

**Bug 5 — trade_morning.py Task Scheduler set to 6:15 AM PT (too late)**
Task Scheduler was triggering `trade_morning.py` at 6:15 AM PT (9:15 AM ET), leaving only 13 minutes before the 9:28 AM ET OPG cutoff. Connection, portfolio read, exit processing, and MOO placement could easily exceed 13 minutes.

Fix: Change Task Scheduler trigger to **6:00 AM PT (9:00 AM ET)**, giving 28 minutes of buffer within the valid OPG window.

### Verify Script

Run `verify_all.py` after any script change to confirm everything works before market open:

```cmd
C:\nmr-trader\venv\Scripts\python.exe C:\nmr-trader\verify_all.py
```

Expected output: 8 PASS, 0 WARN, 0 FAIL.

Checks performed:
1. All imports (ib_async, yfinance, pandas, numpy, sqlite3, requests)
2. Market regime (SPY price vs 200d MA, 5d velocity, VIX)
3. IBKR Gateway connection + portfolio value read
4. Order API test (LMT DAY order placed and immediately cancelled — confirms API works at any time of day)
5. Database state (open positions, pending entries, cooldowns, trade log, rejections)
6. Task Scheduler entries found and last-run status
7. Signal dry run (28 large-cap test tickers, no orders)
8. Trade log readable + last 30 lines

**Note on order test timing:** The verify script tests with a LMT DAY order (valid at any time). MOO/OPG orders will ValidationError if tested outside 7:00–9:28 AM ET — this is expected and normal. Do not test MOO orders in the verify script outside market hours.

### Going Live — Three Changes Only

1. `IBKR_PORT = 4001` (was 4002 paper) — change in all four scripts
2. Switch Gateway from Paper to Live account
3. Level 3 options approval on real account before running hedge_quarterly.py live

### Pass Criteria for Moving to Live Capital

| Check | Target | Action if failing |
|---|---|---|
| Win rate | 57–63% over 100+ trades | Stop — review signal logic |
| Trades per month | 65–90 | Check universe fetch and signal parameters |
| Worst single month | Better than -15% | Review if repeated |
| Script ran every trading day | 100% | Fix Gateway startup |
| Slippage vs prior close | Under 0.6% avg | Higher for small-caps expected |

### Rejection Logging

When a MOO entry order fills at a price that gapped significantly vs the prior close, `trade_morning.py` records:
- Ticker, date, prior close (stored as reference price), actual open price
- Gap % (open price vs prior close)
- Reason string

Visible in dashboard "Entry Rejections" panel and in `paper_trading/rejections.csv`.

---

## Gateway Schedule

| Time (PT) | Script | Action |
|---|---|---|
| 6:00 PM | scan_evening.py | Scans signals, saves candidates to DB, pushes overlay status to dashboard |
| 6:05 PM | hedge_quarterly.py | Manages SPY put spread + VIX call spread |
| 6:10 PM | overlay_etf.py | Manages GOLD + SECROT + TLT Bear (Idea I) + QQQ/IWM Factor (Idea J) via MOC orders |
| 6:00 AM | trade_morning.py | Places MOO entry orders, submits exit orders, confirms fills, pushes to GitHub |

**Recommendation: leave Gateway running 24/7.**

Gateway auto-restarts at ~11:45 PM ET daily. IBC (StartGateway.bat) handles the restart automatically. Paper account port: 4002. Live account port: 4001.

**IBKR Gateway auto-logoff:** Disable auto-logoff in Gateway settings (Settings → Lock and Exit → uncheck auto-logoff or set to never). Gateway must be live at 6:00 PM PT Sunday for the evening scan and at 6:00 AM PT Monday for trade_morning. If Gateway logs off, scripts cannot connect and no trades occur.

---

## Diagnostic Scripts

| Script | Command | Purpose |
|---|---|---|
| verify_all.py | `venv\Scripts\python.exe verify_all.py` | Full system check — run after any change |
| check_signals.py | `venv\Scripts\python.exe check_signals.py` | Preview tonight's signals |
| check_today.py | `venv\Scripts\python.exe check_today.py` | Today's trades + open positions |
| check_log.py | `venv\Scripts\python.exe check_log.py` | Today's trade.log entries |
| positions_check.py | `venv\Scripts\python.exe positions_check.py` | Open positions + P&L (includes hedge) |

**Check pending MOO entries (run morning of, after scan_evening queued signals):**
```bat
python -c "import sqlite3, pandas as pd; conn = sqlite3.connect(r'C:\nmr-trader\positions.db'); print(pd.read_sql('SELECT ticker, limit_price, shares, tier FROM pending_entries', conn).to_string()); conn.close()"
```

**Quick DB check (open positions):**
```bat
python -c "import sqlite3, pandas as pd; conn = sqlite3.connect(r'C:\nmr-trader\positions.db'); print(pd.read_sql('SELECT ticker, entry_price, shares, tier FROM open_positions', conn).to_string()); conn.close()"
```

**Check GOLD overlay state:**
```bat
python -c "import sqlite3, pandas as pd; conn = sqlite3.connect(r'C:\nmr-trader\positions.db'); print(pd.read_sql('SELECT * FROM gold_position', conn).to_string()); conn.close()"
```

**Check SECROT positions:**
```bat
python -c "import sqlite3, pandas as pd; conn = sqlite3.connect(r'C:\nmr-trader\positions.db'); print(pd.read_sql('SELECT * FROM secrot_positions', conn).to_string()); conn.close()"
```

**Check TLT Bear position (Idea I):**
```bat
python -c "import sqlite3, pandas as pd; conn = sqlite3.connect(r'C:\nmr-trader\positions.db'); print(pd.read_sql('SELECT * FROM tlt_bear_position', conn).to_string()); conn.close()"
```

**Check Factor rotation position (Idea J — QQQ/IWM):**
```bat
python -c "import sqlite3, pandas as pd; conn = sqlite3.connect(r'C:\nmr-trader\positions.db'); print(pd.read_sql('SELECT * FROM factor_position', conn).to_string()); conn.close()"
```

**Check VIX3M (for Idea K backwardation detection):**
```bat
python -c "import yfinance as yf; raw = yf.download(['^VIX','^VIX3M'], period='5d', progress=False); print(raw['Close'].tail(3))"
```

---

## Walk-Forward Validation

### V47 Walk-Forward (PASS — April 2026)

| Window | OOS Period | CAGR | MaxDD | Sharpe | Regime |
|---|---|---|---|---|---|
| W1 | 2009–2010 | 28.3% | -14.5% | 1.23 | Recovery |
| W2 | 2011–2012 | 26.0% | -35.4% | 0.73 | Chop/Dip |
| W3 | 2013–2014 | 41.2% | -34.1% | 1.27 | Bull |
| W4 | 2015–2016 | 15.8% | -18.3% | 0.84 | Chop |
| W5 | 2017–2018 | 12.0% | -31.5% | 0.47 | Low-Vol Bull |
| W6 | 2019–2020 | 51.8% | -36.3% | 1.19 | Bull+Crash |
| W7 | 2021–2022 | -12.7% | -48.0% | -0.36 | Bear Grind |
| W8 | 2023–2025 | 4.8% | -57.0% | 0.36 | AI Bull + Tariff Bear |

**OOS Positive CAGR windows: 7/8 — PASS**
**OOS Avg CAGR: 20.91%**

---

## Optimism Bias Warnings

V7.4's 32.85% combined CAGR is the in-sample ceiling, not the live expectation.

| Source | Estimated CAGR Impact |
|---|---|
| Slippage on open prices | -2 to -3% |
| Survivorship bias | -1 to -2% |
| Overfitting across 70+ iterations | -2 to -3% |
| VIX call pricing vs model assumptions | -0.5 to -1% |
| TOM/DOW/VIX parameters tuned to history | -1 to -2% |
| GOLD/SECROT overlay parameter fitting | -0.5 to -1% |
| TLT/Factor/VIX3M overlay parameter fitting | -0.5 to -1% |
| **Realistic live estimate** | **~10–14% CAGR gross** |

Apply ~26% walk-forward decay: 32.85% × 0.74 = ~24% live gross (upper bound).
After short-term capital gains tax (32–37%), realistic net: ~10–12%.

---

## The Honest Risk Picture

V7.4 with all overlays:
- -57.17% combined MaxDD means ~$35M paper loss peak-to-trough at $61M peak equity (2025)
- In dollar terms this is a larger trough than V7.3, but the portfolio is 2× larger
- The SPY put spread fires when SPY drops 3–15% from quarterly reference
- The VIX call spread fires when VIX spikes above 20 intraday — catches early crash days
- GOLD overlay adds +7% GLD exposure during trend — adds positive return in most crash years
- TLT Bear (Idea I) adds +8% TLT exposure in bear regime — earns flight-to-quality return while MR is blocked
- SECROT adds up to +9% sector ETF exposure in bull regime — exits to cash in bear
- Factor Rotation (Idea J) adds +6% QQQ/IWM in bull regime — captures growth/value cycle premium
- 2022: MR lost ~$1.6M; puts paid $659k; VIX calls paid ~$1.2M (multiple months) — net drawdown significantly cushioned
- 2025: MR lost ~$777k; puts paid $1.13M; VIX calls paid ~$1.4M — combined portfolio was net positive
- Combined overlay carry cost: ~0.75%/quarter (puts) + ~0.30–0.60%/month (VIX calls, Idea K) ≈ 6.6–9% annually
- GOLD, TLT, SECROT, and Factor carry no explicit premium cost — P&L depends on asset performance
- Overlay carry is offset by put payouts in good years and dramatically overcompensated in crash years

**VIX call carry cost reality:** The 0.3%/month model assumes stable pricing. In practice VIX calls are cheapest when VIX < 15 (exactly when you want them) and most expensive when VIX is already elevated. The $5/contract max debit cap in hedge_quarterly.py prevents paying up in expensive vol regimes. Expect some months with no VIX call position when calls are overpriced.

---

## Research History

| Ideas Session | Key Finding |
|---|---|
| Ideas V2 | Idea 3 SPY put spread confirmed — only idea improving CAGR, MaxDD, Sharpe simultaneously |
| Ideas V3 | No ideas improved on V35+I3 |
| Ideas V4 | Ranking enhancements zero effect (60-position cap rarely binding) |
| Ideas V5 | TOM/DOW/VIX-RSI sizing → became V47 |
| Ideas V6 | V47+I3 confirmed ceiling at $9.9M / 22.40% CAGR |
| Ideas V7 | VIX call spread model bug (payout overflow). CDaR too aggressive. Idea E gap-behavior confirmed dead. |
| Ideas V7.1 | Fixed VIX call model. CDaR retuned. Idea D dynamic strikes confirmed: +0.42pp CAGR, +$460k, +0.67pp MaxDD. |
| Ideas V7.2 | Combined equity MaxDD (correct measure). Idea G (D+A) confirmed: +1.94pp CAGR, +$8.35M, +0.27pp MaxDD. **V48 chosen.** |
| V49 research | 8 external overlays tested on V35 MR baseline. GOLD (+0.66pp), SECROT (+0.85pp) showed best individual CAGR add. MaxDD worsened on MR-only baseline (no crash protection). Added to DNR table with notes. |
| Ideas V7.3 | GOLD + SECROT tested on Idea G baseline (correct: crash protection already present). MaxDD improved +4.69pp, CAGR +0.13pp MR-only / +3.26pp combined, Final equity +$4.79M. **V7.3 chosen as current strategy.** |
| Live bugs found | LOO/MOO ValidationError 321 at 6 PM PT (OPG window closed). Fix: move order placement to trade_morning.py at 6:00 AM PT. Verify with verify_all.py (8/8 PASS confirmed April 2026). |
| Ideas V7.4 research | 6 ideas × 10 tests vs V7.3 baseline. Idea H (convex exit) dead -$3.3M. Idea L (DBC tilt) dead -$315k. Idea M (Tier1 extended size) negligible +$137k. Idea I (TLT bear) +$4.4M. Idea J (factor rotation) +$7.2M. Idea K (VIX call scaling) +$9.3M strongest. H+I+J+K combined: +$19.7M +2.89pp CAGR. |
| Ideas V7.4 final | I+J+K confirmed on full history: $56,457,642 final equity \| 32.85% CAGR (combined) \| -57.17% MaxDD \| Sharpe 1.04. Overlays generate $35.9M vs MR $20.4M. **V7.4 is current strategy.** |

---

## Disclaimer

Educational and research purposes only. Past backtest performance does not guarantee future results. Not financial advice. The VIX call spread and dynamic SPY put spread require Level 3 options approval. Combined carry cost of ~6.6% annually is a real drag in flat markets. V7.4 is suitable only for those who understand and can hold through drawdowns of -57%+ on the combined portfolio.
