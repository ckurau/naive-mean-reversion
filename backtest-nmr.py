""" Naive Mean Reversion — V32e
==============================
NEW: Composite entry ranking.

Current ranking: Sort candidates by RSI(2) alone — lowest RSI first.
Problem: Two stocks with identical RSI(2) of 5 are treated equally,
even if one has 0.5% ATR (mild pullback) and one has 3% ATR
(violent selloff). The high-ATR stock has more mean reversion energy.

V32e: Composite score = RSI(2) / ATR_pct
  Lower score = more oversold AND more volatile = better MR candidate
  This prioritizes stocks that are both deeply oversold AND
  experiencing high volatility — the strongest mean reversion setups.

Why this is different from ATR sizing (V32a which failed):
  V32a changed HOW MUCH capital per trade → VIX cap overrode it
  V32e changes WHICH TRADES get priority → no cap can override ranking
  On days with 20+ signals but only 5 open slots, V32e picks better.

Trade volume: Identical to V30+S&P600 on average.
  Only affects which trades are selected on high-signal days.
  On low-signal days (fewer candidates than slots) — no effect at all.

Expected effect:
  Slightly higher avg win (better quality entries selected)
  Slightly better PF
  CAGR and trade count essentially unchanged
  Biggest improvement on high-volatility days with many signals

Target: PF > 1.08 | Avg Win improvement | CAGR within 0.5%
Baseline (V30+S&P600): PF 1.07 | Avg Win 3.10% | CAGR 16.01%
"""

from backtest_nmr_lib import (
    get_universe, download_prices, download_reference_data,
    build_earnings_dates, run_backtest, compute_metrics, save_outputs,
    INITIAL_CAPITAL, START_DATE, END_DATE,
)
import backtest_nmr_lib as _lib
import numpy as np
import pandas as pd
import warnings
from tqdm import tqdm
warnings.filterwarnings("ignore")

# ── Override run_backtest with composite ranking ──────────────────────────────
def _v32e_run_backtest(price_data, spy_df, vix_df, sector_data, earnings_map):
    print("\n[Backtest] Running V32e — composite entry ranking (RSI2 / ATR_pct) ...")

    spy_regime = spy_df["spy_ok"].to_dict()

    all_dates: set = set()
    for df in price_data.values():
        all_dates.update(df.index)
    trading_dates = sorted(all_dates)

    signals = {}
    min_bars = _lib.MA_WINDOW + _lib.VOL_MA_PERIOD + _lib.ATR_PERIOD + _lib.MIN_CONSEC_DOWN + 5
    for tkr, df in tqdm(price_data.items(), desc="Generating signals"):
        if len(df) > min_bars:
            signals[tkr] = _lib.generate_signals(df)

    portfolio_value = _lib.INITIAL_CAPITAL
    portfolio_peak = None
    current_drawdown = 0.0
    open_positions = {}
    trades = []
    cooldown_map = {}
    last_vix_spike = None
    last_velocity_crash = None

    composite_used = 0    # days where composite ranking differed from RSI-only
    total_entry_days = 0

    for today in tqdm(trading_dates, desc="Simulating"):
        spy_ok = spy_regime.get(today, True)
        paused, last_vix_spike = _lib.check_vix_spike(today, vix_df, last_vix_spike)

        velocity_paused = False
        try:
            if today in spy_df.index:
                spy_5d = float(spy_df.loc[today, "spy_5d_ret"])
                if not np.isnan(spy_5d) and spy_5d < _lib.VELOCITY_CRASH_5D_THRESHOLD:
                    last_velocity_crash = today
            if last_velocity_crash is not None:
                days_since = (pd.Timestamp(today) - pd.Timestamp(last_velocity_crash)).days
                if days_since <= _lib.VELOCITY_CRASH_PAUSE_DAYS:
                    velocity_paused = True
        except Exception:
            pass

        if portfolio_peak is None:
            if portfolio_value != _lib.INITIAL_CAPITAL:
                portfolio_peak = portfolio_value
                current_drawdown = 0.0
        else:
            if portfolio_value > portfolio_peak:
                portfolio_peak = portfolio_value
                current_drawdown = 0.0
            else:
                current_drawdown = (portfolio_value - portfolio_peak) / portfolio_peak

        # Exits — unchanged
        to_close = []
        for tkr, pos in open_positions.items():
            if tkr not in signals:
                continue
            tkr_df = signals[tkr]
            if today not in tkr_df.index:
                continue
            row = tkr_df.loc[today]
            exit_price = float(row["Close"])
            entry_price = pos["entry_price"]
            days_held = (pd.Timestamp(today) - pd.Timestamp(pos["entry_date"])).days
            pos_pct = (exit_price - entry_price) / entry_price
            shares_rem = pos["shares_remaining"]
            early = days_held < _lib.MIN_HOLD_BEFORE_EXIT
            time_stop = days_held >= pos["hold_days"]
            profit_hit = (not early) and pos_pct >= pos["profit_target"]

            if (pos["partial_enabled"] and not pos["partial_done"]
                    and not early and pos_pct >= pos["partial_trigger"]):
                partial_shares = shares_rem * pos["partial_frac"]
                commission = _lib.calc_commission(partial_shares, exit_price)
                pnl = (exit_price - entry_price) * partial_shares - commission
                trades.append({
                    "ticker": tkr, "entry_date": pos["entry_date"], "exit_date": today,
                    "entry_price": entry_price, "exit_price": exit_price,
                    "shares": partial_shares, "commission": round(commission, 4),
                    "pnl_usd": pnl, "pnl_pct": pos_pct * 100, "days_held": days_held,
                    "exit_reason": "partial_exit", "tier": pos["tier"],
                    "consec_down": pos["consec_down_at_entry"],
                    "portfolio_val": portfolio_value + pnl,
                })
                portfolio_value += pnl
                pos["shares_remaining"] -= partial_shares
                pos["partial_done"] = True
                pos["profit_target"] = pos["profit_target"] * 2
                continue

            full_exit = (
                time_stop
                or (not pos["partial_enabled"] and profit_hit)
                or (pos["partial_enabled"] and pos["partial_done"] and profit_hit)
            )
            if full_exit:
                commission = _lib.calc_commission(shares_rem, exit_price)
                pnl = ((exit_price - entry_price) * shares_rem
                       - commission - pos["entry_commission"])
                reason = "time_stop" if time_stop else "profit_target"
                trades.append({
                    "ticker": tkr, "entry_date": pos["entry_date"], "exit_date": today,
                    "entry_price": entry_price, "exit_price": exit_price,
                    "shares": shares_rem,
                    "commission": round(commission + pos["entry_commission"], 4),
                    "pnl_usd": pnl, "pnl_pct": pos_pct * 100, "days_held": days_held,
                    "exit_reason": reason, "tier": pos["tier"],
                    "consec_down": pos["consec_down_at_entry"],
                    "portfolio_val": portfolio_value + pnl,
                })
                portfolio_value += pnl
                if time_stop:
                    cooldown_map[tkr] = today
                to_close.append(tkr)

        for tkr in to_close:
            del open_positions[tkr]

        if not spy_ok or paused or velocity_paused:
            continue
        if len(open_positions) >= _lib.MAX_POSITIONS:
            continue

        # Entries — composite ranking
        candidates = []
        for tkr, tkr_df in signals.items():
            if tkr in open_positions or today not in tkr_df.index:
                continue
            row = tkr_df.loc[today]
            if not row["signal"]:
                continue
            if tkr in cooldown_map:
                if (pd.Timestamp(today) - pd.Timestamp(cooldown_map[tkr])).days < _lib.REENTRY_COOLDOWN_DAYS:
                    continue
            if _lib.near_earnings(tkr, today, earnings_map):
                continue
            if not _lib.sector_ok(tkr, today, sector_data):
                continue
            if _lib.count_sector_positions(tkr, open_positions) >= _lib.MAX_SECTOR_POSITIONS:
                continue

            rsi2 = float(row["rsi2"])
            atr_pct = float(row["atr_pct"])

            # [V32e] Composite score: RSI2 / ATR_pct
            # Lower = more oversold AND more volatile = better candidate
            # Guard against zero ATR (shouldn't happen given ATR filter but safety check)
            if atr_pct > 0:
                composite_score = rsi2 / atr_pct
            else:
                composite_score = rsi2 * 1000  # penalize zero-ATR entries to back of queue

            candidates.append((composite_score, tkr, int(row["consec_down"]), rsi2))

        if candidates:
            total_entry_days += 1
            slots_available = _lib.MAX_POSITIONS - len(open_positions)
            # Check if composite ranking would differ from RSI-only on constrained days
            if len(candidates) > slots_available:
                rsi_order = sorted(candidates, key=lambda x: x[3])[:slots_available]
                composite_order = sorted(candidates, key=lambda x: x[0])[:slots_available]
                if set(c[1] for c in rsi_order) != set(c[1] for c in composite_order):
                    composite_used += 1

        # Sort by composite score (ascending = best first)
        candidates.sort(key=lambda x: x[0])

        for composite_score, tkr, consec_val, rsi_val in candidates:
            if len(open_positions) >= _lib.MAX_POSITIONS:
                break
            tkr_df = signals[tkr]
            today_idx = tkr_df.index.get_loc(today)
            if today_idx + 1 >= len(tkr_df):
                continue
            next_row = tkr_df.iloc[today_idx + 1]
            entry_price = float(next_row["Open"])
            if entry_price <= 0:
                continue
            prev_close = float(tkr_df.iloc[today_idx]["Close"])
            gap_pct = (entry_price - prev_close) / prev_close
            if gap_pct < _lib.GAP_DOWN_MAX or gap_pct > _lib.GAP_UP_MAX:
                continue
            tier_cfg = _lib.get_tier(consec_val)
            pos_size = _lib.get_position_size(today, vix_df, current_drawdown)
            shares = (portfolio_value * pos_size) / entry_price
            entry_comm = _lib.calc_commission(shares, entry_price)
            open_positions[tkr] = {
                "entry_date": tkr_df.index[today_idx + 1],
                "entry_price": entry_price, "shares": shares,
                "shares_remaining": shares, "rsi2_at_entry": rsi_val,
                "consec_down_at_entry": consec_val,
                "profit_target": tier_cfg["profit_target"],
                "hold_days": tier_cfg["hold_days"],
                "partial_enabled": tier_cfg["partial_enabled"],
                "partial_frac": tier_cfg["partial_frac"],
                "partial_trigger": tier_cfg["partial_trigger"],
                "partial_done": False, "tier": tier_cfg["tier"],
                "entry_commission": entry_comm,
            }

    print(f"[Backtest] Complete — {len(trades)} trades executed.")
    if total_entry_days > 0:
        print(f"[V32e] Composite ranking changed selection on "
              f"{composite_used}/{total_entry_days} constrained days "
              f"({composite_used/total_entry_days*100:.1f}% of days with entries)")
    return pd.DataFrame(trades)

_lib.run_backtest = _v32e_run_backtest

# ── Labels ────────────────────────────────────────────────────────────────────
_orig_compute_metrics = _lib.compute_metrics

def _v32e_compute_metrics(trades_df):
    metrics, eq_df = _orig_compute_metrics(trades_df)
    if isinstance(metrics, dict):
        metrics["version"] = "V32e"
        metrics["parameters"]["version"] = "V32e"
        metrics["parameters"]["v32e_changes"] = (
            "[V32e] Composite ranking: sort by RSI(2)/ATR_pct instead of RSI(2) alone | "
            "prioritizes oversold + high-volatility setups | "
            "no change to sizing, exits, or filters"
        )
    return metrics, eq_df

_lib.compute_metrics = _v32e_compute_metrics

def _v32e_save_outputs(trades_df, metrics, eq_df):
    import json
    from pathlib import Path
    OUTPUT_DIR = Path("results")
    OUTPUT_DIR.mkdir(exist_ok=True)
    trades_df.to_csv(OUTPUT_DIR / "trades.csv", index=False)
    eq_df.to_csv(OUTPUT_DIR / "equity_curve.csv", index=False)
    with open(OUTPUT_DIR / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    print("\n" + "=" * 70)
    print("  NAIVE MR BACKTEST — V32e")
    print("  Composite ranking: RSI(2) / ATR_pct")
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
    print("\n  V32e vs V30+S&P600 baseline:")
    print("  Target:   PF > 1.08 | Avg Win improvement | CAGR within 0.5%")
    print("  Baseline: PF 1.07   | Avg Win 3.10%        | CAGR 16.01%")
    print("  Note: Check the composite_used diagnostic in the run log")
    print("  If <10% of days were constrained, ranking had minimal impact")
    print("=" * 70)
    print(f"\n  Saved to: {OUTPUT_DIR.resolve()}")

_lib.save_outputs = _v32e_save_outputs

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
