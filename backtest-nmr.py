""" Naive Mean Reversion — V32a
==============================
NEW: ATR-based position sizing.

Current sizing: VIX regime only (9% or 5% of portfolio).
Problem: All stocks get the same size regardless of individual volatility.
A stock with 0.5% ATR and one with 3% ATR both get 9% of portfolio —
the high-ATR stock carries 6x more dollar risk per trade.

V32a fix: Size each position to target a fixed dollar risk per trade.
Formula: shares = (portfolio * RISK_PER_TRADE) / (ATR * entry_price)
Where RISK_PER_TRADE = 0.005 (0.5% of portfolio per trade, risking 1 ATR)

VIX regime still applies as a cap:
  VIX < 25: max position = 9% of portfolio (unchanged)
  VIX >= 25: max position = 5% of portfolio (unchanged)
ATR sizing can only reduce below the VIX cap, never exceed it.

Expected effect:
  - High-ATR stocks (volatile small-caps) get smaller positions
  - Low-ATR stocks (stable large-caps) get larger positions
  - More uniform dollar risk per trade → better PF and Sharpe
  - Trade volume unchanged (no filtering)

Target: PF > 1.10 | Sharpe > 0.75 | CAGR within 1% of baseline
Baseline (V30+S&P600): PF 1.07 | Sharpe 0.73 | CAGR 16.01%
"""

from backtest_nmr_lib import (
    get_universe, download_prices, download_reference_data,
    build_earnings_dates, compute_metrics, save_outputs,
    INITIAL_CAPITAL, START_DATE, END_DATE,
)
import backtest_nmr_lib as _lib
import numpy as np
import pandas as pd
import warnings
warnings.filterwarnings("ignore")

# ── ATR sizing parameters ─────────────────────────────────────────────────────
ATR_RISK_PER_TRADE = 0.005   # risk 0.5% of portfolio per 1 ATR move
ATR_SIZING_MULTIPLIER = 1.0  # how many ATRs we're willing to risk (1 ATR = typical daily range)

# ── Override run_backtest to use ATR-based sizing ─────────────────────────────
from tqdm import tqdm

def _v32a_run_backtest(price_data, spy_df, vix_df, sector_data, earnings_map):
    print("\n[Backtest] Running V32a — ATR-based position sizing ...")

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

    atr_size_used = []   # track ATR sizing vs VIX cap for diagnostics

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

        # Exits (unchanged)
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

        # Entries with ATR-based sizing
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
            candidates.append((float(row["rsi2"]), tkr, int(row["consec_down"])))

        candidates.sort(key=lambda x: x[0])

        for rsi_val, tkr, consec_val in candidates:
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

            # [V32a] ATR-based sizing
            # VIX regime gives the maximum allowed position size
            vix_cap_pct = _lib.get_position_size(today, vix_df, current_drawdown)

            # Earnings month cap
            month = pd.Timestamp(today).month
            if month in _lib.EARNINGS_MONTHS:
                vix_cap_pct = min(vix_cap_pct, _lib.POSITION_SIZE_EARNINGS)

            # ATR-based size: target fixed dollar risk per trade
            atr_pct = float(tkr_df.iloc[today_idx]["atr_pct"])  # ATR as % of price
            if atr_pct > 0:
                # shares = dollar_risk / (ATR_in_dollars)
                # dollar_risk = portfolio * ATR_RISK_PER_TRADE
                # ATR_in_dollars = entry_price * atr_pct * ATR_SIZING_MULTIPLIER
                dollar_risk = portfolio_value * ATR_RISK_PER_TRADE
                atr_dollars = entry_price * atr_pct * ATR_SIZING_MULTIPLIER
                atr_based_shares = dollar_risk / atr_dollars
                atr_based_pct = (atr_based_shares * entry_price) / portfolio_value
            else:
                atr_based_pct = vix_cap_pct

            # Use ATR size but cap at VIX regime maximum
            final_pct = min(atr_based_pct, vix_cap_pct)
            # Also enforce a minimum — don't go below 1% (avoid tiny positions)
            final_pct = max(final_pct, 0.01)

            atr_size_used.append({
                "atr_pct": atr_pct,
                "atr_based_pct": atr_based_pct,
                "vix_cap_pct": vix_cap_pct,
                "final_pct": final_pct,
                "capped": atr_based_pct > vix_cap_pct,
            })

            shares = (portfolio_value * final_pct) / entry_price
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
    if atr_size_used:
        atr_df = pd.DataFrame(atr_size_used)
        avg_final = atr_df["final_pct"].mean() * 100
        pct_capped = atr_df["capped"].mean() * 100
        avg_atr_based = atr_df["atr_based_pct"].mean() * 100
        print(f"[V32a] ATR sizing: avg ATR-based size {avg_atr_based:.1f}% | "
              f"avg final size {avg_final:.1f}% | "
              f"VIX-capped {pct_capped:.1f}% of entries")
    return pd.DataFrame(trades)

_lib.run_backtest = _v32a_run_backtest

# ── Labels ────────────────────────────────────────────────────────────────────
_orig_compute_metrics = _lib.compute_metrics

def _v32a_compute_metrics(trades_df):
    metrics, eq_df = _orig_compute_metrics(trades_df)
    if isinstance(metrics, dict):
        metrics["version"] = "V32a"
        metrics["parameters"]["version"] = "V32a"
        metrics["parameters"]["v32a_changes"] = (
            f"[V32a] ATR-based sizing: risk {ATR_RISK_PER_TRADE*100:.1f}% portfolio per ATR | "
            "VIX regime remains as cap | no filtering changes"
        )
    return metrics, eq_df

_lib.compute_metrics = _v32a_compute_metrics

def _v32a_save_outputs(trades_df, metrics, eq_df):
    import json
    from pathlib import Path
    OUTPUT_DIR = Path("results")
    OUTPUT_DIR.mkdir(exist_ok=True)
    trades_df.to_csv(OUTPUT_DIR / "trades.csv", index=False)
    eq_df.to_csv(OUTPUT_DIR / "equity_curve.csv", index=False)
    with open(OUTPUT_DIR / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    print("\n" + "=" * 70)
    print("  NAIVE MR BACKTEST — V32a")
    print("  ATR-based position sizing")
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
    print("\n  V32a vs V30+S&P600 baseline:")
    print("  Target:   PF > 1.10 | Sharpe > 0.75 | CAGR within 1% of baseline")
    print("  Baseline: PF 1.07   | Sharpe 0.73   | CAGR 16.01%")
    print("=" * 70)
    print(f"\n  Saved to: {OUTPUT_DIR.resolve()}")

_lib.save_outputs = _v32a_save_outputs

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
