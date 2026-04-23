# Naive Mean Reversion (NMR) Backtest

A survivorship-bias-free backtest of a Naive Mean Reversion strategy across all historical S&P 500 + S&P 400 MidCap + S&P 600 SmallCap constituents, automated via GitHub Actions.

---

## Current Version: V48 — Idea G (Dynamic Put Spread + VIX Call Overlay)

**Active strategy: V47 base logic + dynamic SPY put spread strikes + monthly VIX call spread.**

V47 = V35 + four confirmed positive sizing overlays (TOM sizing, DOW sizing, partial trigger tuning, VIX RSI tightening).
Idea G = V47 + Idea D (VIX-regime-conditional put spread strikes) + Idea A (monthly VIX 20/40-call spread).

Walk-forward validated through V47: 7/8 OOS windows positive, OOS avg CAGR 20.91%.
Idea G confirmed via backtest_ideas_v7_2.py (full history through April 2026).

---

## Architecture

```
backtest_ideas_v7_2.py    Idea G combined backtest (V47 + dynamic put spread + VIX calls)
backtest_nmr_lib_v47.py   All V47 backtest logic and parameters (unchanged)
backtest-nmr-v47.py       Thin wrapper for V47 MR-only backtest
walkforward_v47.py        Walk-forward validation for V47

scan_evening.py           Live: 6:00 PM PT — MR signal scan + LOO orders (V47 parameters)
hedge_quarterly.py        Live: 6:05 PM PT — SPY put spread (dynamic strikes) + VIX call spread
trade_morning.py          Live: 6:15 AM PT — exit orders + fill confirmation (unchanged from V47)
```

**Three-script live execution (unchanged schedule):**
- `scan_evening.py`    — 6:00 PM PT, scans universe, submits LOO buy orders
- `hedge_quarterly.py` — 6:05 PM PT, manages SPY put spread + VIX call spread
- `trade_morning.py`   — 6:15 AM PT, submits MOO exits, confirms LOO fills

---

## Best Confirmed Results

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
| **V48 / Idea G (current, combined)** | **24.38%** | **$18.3M** | **-56.91%** | **0.74** | **Max wealth, taxable, full overlay** |
| V47 + Idea 3 (previous benchmark) | 22.40% | $9.9M | -60.89%* | 0.74 | Previous recommended |
| V47 (no hedge) | 19.54% | $4.6M | -56.84% | 0.72 | Max wealth, taxable, no hedge |
| C_TurnOfMonth | 16.20% | $2.5M | -48.91% | 0.71 | Middle ground |
| V32d | 15.37% | $2.1M | -39.21% | 0.77 | Roth IRA, lower DD tolerance |

*V47+I3 MaxDD was MR-only. Combined equity MaxDD is -57.18% (also confirmed in V7.2 research).

---

## V48 Strategy Rules

All V47 rules apply unchanged. Idea G adds two overlay instruments managed by `hedge_quarterly.py`.

### MR Rules (V47, unchanged)

| Rule | Detail |
|---|---|
| Universe | S&P 500 + S&P 400 MidCap + S&P 600 SmallCap (current + historical) |
| Trend filter | Stock must be above its 200-day SMA |
| Entry signal | 4+ consecutive down days AND RSI(2) < 20 AND ATR > 1% AND volume > 20-day avg AND dollar volume > $5M/day |
| Entry execution | Buy at open of next day via LOO order (limit = prior close × 1.005) |
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

### Idea G: Dynamic SPY Put Spread (hedge_quarterly.py)

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

### Idea G: Monthly VIX Call Spread (hedge_quarterly.py, NEW)

| Parameter | Value |
|---|---|
| Long call | VIX 20-strike |
| Short call | VIX 40-strike |
| Target DTE | 21 trading days (~monthly) |
| Cost | ~0.3% of portfolio per month ($900/mo at $300k) |
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

**Total VIX call overlay (backtest, 2004–2026):**
- Premiums paid: -$4,935,793
- Payouts received: +$9,430,338
- Net P&L: **+$4,494,545**

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
| [all other V3/V4 ideas — see prior README versions] | Various — see research history |

---

## Critical Research Lessons

### Combined equity MaxDD is the correct measure for overlay strategies
When the portfolio holds both MR positions and put/call overlays simultaneously, MaxDD should be computed on the combined equity curve (MR P&L + overlay payouts). VIX call payouts received during crash months lift the combined equity through the trough — the MR-only MaxDD overstates the true investor experience. V48 reports combined equity MaxDD throughout.

### The 60-position cap is the key architectural constraint
With 60 positions and 10–30 candidates per day, all candidates fill regardless of rank. Any idea that works through signal re-ranking has zero effect. The only improvement axis is how much capital is deployed (sizing overlays) and insurance (hedge overlays). This eliminated 6+ ideas in V4/V5 and is why Idea G succeeds — it operates entirely outside the MR signal framework.

### The crash-recovery paradox
Loss streaks immediately preceding crash recoveries cannot be filtered without blocking the recoveries. 2009, 2020, and 2025 all began with loss clusters then reversed violently. Every filter that reduces streak exposure also reduces crash-recovery capture. The hedge overlay is the only tool that addresses crash risk without touching the signal framework.

### Always import from the same lib — never reimplement
A reimplemented backtest engine produced 17.11% baseline instead of 19.71%, invalidating all deltas. V2/V3/V4/V5/V6/V7.x all import from `backtest_nmr_lib.py` — same architecture is the only valid pattern.

---

## Paper Trading & Live Automation

**Status: LIVE (paper trading active as of April 2026)**

| Item | Detail |
|---|---|
| Broker | Interactive Brokers (IBKR) paper account |
| Starting equity | $100,000 |
| Scripts | scan_evening.py (6:00 PM) + hedge_quarterly.py (6:05 PM) + trade_morning.py (6:15 AM) |
| Scheduler | Windows Task Scheduler — three tasks |
| Entry orders | Limit On Open (LOO), limit = prior_close × 1.005 |
| Exit orders | MOO |
| SPY put spread | Dynamic strikes per VIX regime, quarterly renewal |
| VIX call spread | 20/40-strike, monthly renewal |
| Options approval | Level 3 required for both SPY puts and VIX calls |
| Database | C:\nmr-trader\positions.db — SQLite |
| Scripts location | C:\nmr-trader\ |
| Git repo (local) | C:\naive-mean-reversion\ |
| Dashboard | https://ckurau.github.io/naive-mean-reversion/ |

### Infrastructure Setup (completed April 2026)

| Component | Detail |
|---|---|
| Git repo location | `C:\naive-mean-reversion\` — cloned from GitHub, branch `main` |
| Scripts location | `C:\nmr-trader\` — separate folder, not a git repo |
| GitHub push | `trade_morning.py` writes to `C:\naive-mean-reversion\paper_trading\` and pushes after each run |
| Dashboard URL | https://ckurau.github.io/naive-mean-reversion/ (GitHub Pages, public) |
| Dashboard file | `index.html` in repo root — reads from `paper_trading/` via raw.githubusercontent.com |
| Mobile access | Bookmark dashboard URL in Safari → Share → Add to Home Screen |
| PC sleep | Disabled on AC power (`powercfg /change standby-timeout-ac 0`) |
| Gateway | Leave running 24/7 on paper account port 4002 |

### GitHub Push — How It Works

`trade_morning.py` runs at 6:15 AM PT and after confirming fills it:

1. Writes `C:\naive-mean-reversion\paper_trading\summary.json` — portfolio value, VIX, win rate, today's fills/misses, log entries
2. Writes `paper_trading\trades.csv` — full trade log from SQLite
3. Writes `paper_trading\open_positions.csv` — current open positions
4. Writes `paper_trading\rejections.csv` — LOO orders that didn't fill with gap % reason
5. Git commits and pushes to `origin main`

Dashboard at `https://ckurau.github.io/naive-mean-reversion/` auto-refreshes every 5 minutes.

**Key config in trade_morning.py:**
```python
GITHUB_PUSH      = True
GITHUB_REPO_PATH = r'C:\naive-mean-reversion'
OUTPUT_DIR       = r'C:\naive-mean-reversion\paper_trading'
GITHUB_BRANCH    = 'main'
```

### Critical Bug Fixed (April 2026)

A stray PowerShell command was embedded as a Python line in `trade_morning.py` at line 405, causing a `NameError` crash immediately before fill confirmation. This meant LOO orders were submitted every evening but never confirmed the next morning — positions were never saved to the DB, resulting in zero trades recorded despite orders being sent to IBKR for weeks.

**Fix:** Replaced with the correct sequence:
```python
ib.reqExecutions()
ib.sleep(3)
filled_syms = {f.contract.symbol: f for f in ib.fills()}
```

### Going Live — Three Changes Only

1. `IBKR_PORT = 4001` (was 4002 paper) — change in all three scripts
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

When a LOO order doesn't fill, `trade_morning.py` records:
- Ticker, date, limit price, actual open price
- Gap % (open price vs limit price)
- Reason string (e.g. "Gapped up 1.23% above LOO limit")

Visible in dashboard "Entry Rejections" panel and in `paper_trading/rejections.csv`.

---

## Gateway Schedule

| Time (PT) | Script | Action |
|---|---|---|
| 6:00 PM | scan_evening.py | Scans signals, submits LOO orders |
| 6:05 PM | hedge_quarterly.py | Manages SPY put spread + VIX call spread |
| 6:15 AM | trade_morning.py | Submits exits, confirms LOO fills, pushes to GitHub |

**Recommendation: leave Gateway running 24/7.**

Gateway auto-restarts at ~11:45 PM ET daily. IBC (StartGateway.bat) handles the restart automatically. Paper account port: 4002. Live account port: 4001.

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

V48's 24.38% CAGR is the in-sample ceiling, not the live expectation.

| Source | Estimated CAGR Impact |
|---|---|
| Slippage on open prices | -2 to -3% |
| Survivorship bias | -1 to -2% |
| Overfitting across 70+ iterations | -2 to -3% |
| VIX call pricing vs model assumptions | -0.5 to -1% |
| TOM/DOW/VIX parameters tuned to history | -1 to -2% |
| **Realistic live estimate** | **~10–14% CAGR gross** |

Apply ~26% walk-forward decay: 24.38% × 0.74 = ~18% live gross (upper bound).
After short-term capital gains tax (32–37%), realistic net: ~10–12%.

---

## The Honest Risk Picture

V48 with Idea G overlay:
- ~-57% combined MaxDD means ~$10.5M paper loss peak-to-trough at $18.3M equity
- The SPY put spread fires when SPY drops 3–15% from quarterly reference
- The VIX call spread fires when VIX spikes above 20 intraday — catches early crash days
- 2022: MR lost ~$1.6M; puts paid $659k; VIX calls paid ~$1.2M (multiple months) — net drawdown significantly cushioned
- 2025: MR lost ~$777k; puts paid $1.13M; VIX calls paid ~$1.4M — combined portfolio was net positive
- Combined overlay carry cost: ~0.75%/quarter (puts) + ~0.30%/month (VIX calls) ≈ 6.6% annually
- Overlay carry is offset by put payouts in good years and dramatically overcompensated in crash years

**VIX call carry cost reality:** The 0.3%/month model assumes stable pricing. In practice VIX calls are cheapest when VIX < 15 (exactly when you want them) and most expensive when VIX is already elevated. The $5/contract max debit cap in hedge_quarterly.py prevents paying up in expensive vol regimes. Expect some months with no VIX call position when calls are overpriced.

---

## Diagnostic Scripts

| Script | Command | Purpose |
|---|---|---|
| check_signals.py | `venv\Scripts\python.exe check_signals.py` | Preview tonight's signals |
| check_today.py | `venv\Scripts\python.exe check_today.py` | Today's trades + open positions |
| check_log.py | `venv\Scripts\python.exe check_log.py` | Today's trade.log entries |
| positions_check.py | `venv\Scripts\python.exe positions_check.py` | Open positions + P&L (includes hedge) |

**Quick DB check (run from C:\nmr-trader with venv active):**
```bat
python -c "import sqlite3, pandas as pd; conn = sqlite3.connect(r'C:\nmr-trader\positions.db'); print(pd.read_sql('SELECT ticker, entry_price, shares, tier FROM open_positions', conn).to_string()); conn.close()"
```

**Check pending LOO entries:**
```bat
python -c "import sqlite3, pandas as pd; conn = sqlite3.connect(r'C:\nmr-trader\positions.db'); print(pd.read_sql('SELECT ticker, limit_price, shares, tier FROM pending_entries', conn).to_string()); conn.close()"
```

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

---

## Disclaimer

Educational and research purposes only. Past backtest performance does not guarantee future results. Not financial advice. The VIX call spread and dynamic SPY put spread require Level 3 options approval. Combined carry cost of ~6.6% annually is a real drag in flat markets. V48 is suitable only for those who understand and can hold through drawdowns of -57%+ on the combined portfolio.
