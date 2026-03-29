# Naive Mean-Reversion (MR) Backtest

A survivorship-bias-free backtest of the **Naive MR** strategy across all historical S&P 500 constituents, automated via GitHub Actions.

---

## Strategy Rules

| Rule | Detail |
|---|---|
| **Universe** | All S&P 500 stocks (current + historical) trading ≥ $10/share |
| **Trend filter** | Stock must be **above its 200-day SMA** |
| **Entry signal** | Price has declined **4 consecutive days** |
| **Entry execution** | Buy at the **open of the next day** |
| **Exit rule** | Sell at the **close of the first up-day** |
| **Max positions** | 20 simultaneous holdings |
| **Position size** | 5% of portfolio per trade |
| **Starting capital** | $100,000 (configurable) |
| **Backtest period** | 2004-01-01 → today (~20 years) |

---

## Repository Structure

```
.
├── backtest.py                   # Core backtest engine
├── requirements.txt              # Python dependencies
├── results/                      # Auto-generated output (committed by CI)
│   ├── metrics.json              # Key performance metrics
│   ├── trades.csv                # Individual trade log
│   └── equity_curve.csv         # Daily equity curve
└── .github/
    └── workflows/
        └── backtest.yml          # GitHub Actions workflow
```

---

## Setup

### 1. Fork / clone this repository

```bash
git clone https://github.com/<your-username>/<your-repo>.git
cd <your-repo>
```

### 2. Enable Actions

Go to **Settings → Actions → General** and set permissions to  
*"Read and write permissions"* so the workflow can commit results back.

### 3. Run the backtest

**Option A — Manual trigger (recommended first run)**  
Go to **Actions → Naive MR Backtest → Run workflow**.  
You can optionally override the start date, end date, or capital.

**Option B — Scheduled**  
The workflow runs automatically every **Sunday at 00:00 UTC**.

**Option C — Local**
```bash
pip install -r requirements.txt
python backtest.py
```

---

## Output Metrics

After a successful run, `results/metrics.json` contains:

| Metric | Description |
|---|---|
| `cagr_pct` | Compound Annual Growth Rate |
| `win_rate_pct` | Percentage of winning trades |
| `roi_per_year_pct` | Average annual return on initial capital |
| `avg_days_held` | Average holding period in calendar days |
| `avg_win_pct` | Average gain on winning trades |
| `avg_loss_pct` | Average loss on losing trades |
| `profit_factor` | Gross profit ÷ gross loss |
| `max_drawdown_pct` | Largest peak-to-trough equity decline |
| `sharpe_ratio` | Annualised Sharpe ratio (monthly returns) |
| `total_trades` | Total number of round-trip trades |
| `trades_per_year` | Average trades executed per year |
| `final_equity` | Portfolio value at end of backtest |

---

## Survivorship Bias Mitigation

The universe loader pulls **both** the current S&P 500 member table **and** the historical additions/removals table from Wikipedia, then supplements with a curated list of well-known historical constituents (e.g., Lehman Brothers `LEH`, Bear Stearns `BSC`, Yahoo `YHOO`). Tickers with no available price data are silently skipped.

> **Note**: Perfect survivorship-bias elimination is difficult with free data sources.  
> For institutional-grade analysis, consider a paid data provider such as Norgate Data or Compustat.

---

## Customisation

All key parameters live at the top of `backtest.py`:

```python
START_DATE      = "2004-01-01"
END_DATE        = datetime.date.today().isoformat()
MIN_PRICE       = 10.0
MAX_POSITIONS   = 20
POSITION_SIZE   = 0.05
MA_WINDOW       = 200
CONSEC_DOWN     = 4
INITIAL_CAPITAL = 100_000.0
```

They can also be overridden at runtime via the `workflow_dispatch` inputs.

---

## Disclaimer

This code is for **educational and research purposes only**.  
Past backtest performance does not guarantee future results.  
This is not financial advice.
