""" Naive Mean Reversion — V33b
==============================
NEW: Adaptive MAX_POSITIONS raised from 40 to 50.

Context: V33a (close-based time stops) was identified as the first
priority but on inspection the current backtest ALREADY exits at
close of day 8 (not open of day 9). The time stop exits at
row["Close"] on the day when days_held >= hold_days. Close-based
exits are already implemented. V33a is therefore not needed.

V33b: Raise MAX_POSITIONS from 40 to 50.

Rationale (same logic that made V24 the first breakthrough):
  V24 raised positions 30→40 at UNCHANGED size = major improvement
  because it captured overflow on high-signal days.
  V33b raises 40→50 at UNCHANGED size for the same reason.

  Average simultaneous open positions: 8–15
  Max slots are only a constraint on high-signal days
  High-signal days = best MR days (many stocks oversold simultaneously)
  Currently leaving 10 entries on the table on those days

Position sizing unchanged:
  VIX < 25 → 9% per position (same)
  VIX ≥ 25 → 5% per position (same)
  Theoretical max exposure: 50 × 9% = 450% (vs current 360%)
  Practical: still 8–15 open at any time on average

Risk consideration:
  Sector cap (max 3) still applies — prevents hidden concentration
  Velocity crash pause still applies — extreme days fully protected
  The extra 10 slots only fire when genuine signal overflow exists

Expected effect:
  More trades on high-signal days (best MR conditions)
  Higher CAGR from capturing previously missed entries
  Drawdown may increase modestly on crowded-signal days
  Trade count: ~900–950/year (from 872)

Target: CAGR > 16.5% | Final Equity > $2,500k | Sharpe ≥ 0.73
Baseline (V32e): CAGR 16.10% | Final Equity $2,454k | Sharpe 0.73
"""

from backtest_nmr_lib import (
    get_universe, download_prices, download_reference_data,
    build_earnings_dates, run_backtest, compute_metrics, save_outputs,
    INITIAL_CAPITAL, START_DATE, END_DATE,
)
import backtest_nmr_lib as _lib
import warnings
warnings.filterwarnings("ignore")

# ── Single parameter change ───────────────────────────────────────────────────
_lib.MAX_POSITIONS = 50   # was 40

# ── Labels ────────────────────────────────────────────────────────────────────
_orig_compute_metrics = _lib.compute_metrics

def _v33b_compute_metrics(trades_df):
    metrics, eq_df = _orig_compute_metrics(trades_df)
    if isinstance(metrics, dict):
        metrics["version"] = "V33b"
        metrics["parameters"]["version"] = "V33b"
        metrics["parameters"]["max_positions"] = "50 (was 40) [V33b]"
        metrics["parameters"]["v33b_changes"] = (
            "[V33b] MAX_POSITIONS raised 40→50 | "
            "position sizing unchanged | "
            "sector cap (max 3) unchanged | "
            "note: V33a not needed — backtest already exits at close"
        )
    return metrics, eq_df

_lib.compute_metrics = _v33b_compute_metrics

def _v33b_save_outputs(trades_df, metrics, eq_df):
    import json
    from pathlib import Path
    OUTPUT_DIR = Path("results")
    OUTPUT_DIR.mkdir(exist_ok=True)
    trades_df.to_csv(OUTPUT_DIR / "trades.csv", index=False)
    eq_df.to_csv(OUTPUT_DIR / "equity_curve.csv", index=False)
    with open(OUTPUT_DIR / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    print("\n" + "=" * 70)
    print("  NAIVE MR BACKTEST — V33b")
    print("  MAX_POSITIONS raised 40 → 50")
    print("=" * 70)
    for k, v in metrics.items():
        if k == "tier_stats":
            print(f"\n  Per-Tier Statistics:")
            for tk, tv in v.items():
                print(f"    {tk}:")
                for sk, sv in tv.items():
                    print(f"      {sk:<16}: {sv}")
        elif k == "year_stats":
            print(f"\n  Per-Year Breakdown:")
            for yr, yv in v.items():
                print(f"    {yr}: {yv['trades']:>5} trades  WR {yv['win_rate']:>5}%  "
                      f"P&L ${yv['pnl_usd']:>10,.0f}")
        elif k in ("parameters", "exit_reasons"):
            label = "Parameters" if "param" in k else "Exit Reason Breakdown"
            print(f"\n  {label}:")
            for ek, ev in v.items():
                print(f"    {ek:<40}: {ev}")
        else:
            print(f"  {k.replace('_',' ').title():<36}: {v}")
    print("\n  V33b vs V32e baseline:")
    print("  Target:   CAGR > 16.5% | Equity > $2,500k | Sharpe ≥ 0.73")
    print("  Baseline: CAGR 16.10%  | Equity $2,454k   | Sharpe 0.73")
    print("  Note: V33a not needed — exits already close-based in current code")
    print("=" * 70)
    print(f"\n  Saved to: {OUTPUT_DIR.resolve()}")

_lib.save_outputs = _v33b_save_outputs

if __name__ == "__main__":
    universe = get_universe()
    price_data = download_prices(universe)
    spy_df, vix_df, sector_data = download_reference_data()
    earnings_map = build_earnings_dates(list(price_data.keys()))
    trades_df = _lib.run_backtest(price_data, spy_df, vix_df, sector_data, earnings_map)
    if trades_df.empty:
        print("[ERROR] No trades generated.")
    else:
        metrics, eq_df = _lib.compute_metrics(trades_df)
        _lib.save_outputs(trades_df, metrics, eq_df)
