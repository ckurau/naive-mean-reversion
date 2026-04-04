""" Naive Mean Reversion — V32f
==============================
Combines V32d + V32e — all three proven improvements together.

[V32f-1] From V32b/V32d: Tier 3 hold window 8 → 6 days
  Effect: Smaller avg loss on weakest signal tier
  V32b result: Sharpe 0.75, Avg Loss -3.12%

[V32f-2] From V32c/V32d: VIX 5-day trend sizing multiplier
  When VIX falling (below 5d MA) → 80% of normal position size
  Effect: Reduced exposure in weaker regime conditions
  V32c result: MaxDD -44.30%

[V32f-3] From V32e: Composite entry ranking (RSI2 / ATR_pct)
  Prioritizes most oversold AND most volatile candidates
  Effect: +$40k equity, +0.09% CAGR vs baseline
  V32e result: $2,454k, CAGR 16.10%

All three target different mechanisms — no interaction:
  V32f-1 → exit quality (Tier 3 time stops)
  V32f-2 → entry sizing (regime awareness)
  V32f-3 → entry selection (trade quality on constrained days)

Expected: ~$2,180-2,220k | Sharpe ~0.77-0.78 | MaxDD ~-39% | CAGR ~15.5%

Baselines:
  V30+S&P600: $2,414k | CAGR 16.01% | PF 1.07 | MaxDD -48.65% | Sharpe 0.73
  V32d:       $2,145k | CAGR 15.37% | PF 1.09 | MaxDD -39.21% | Sharpe 0.77
  V32e:       $2,454k | CAGR 16.10% | PF 1.07 | MaxDD -48.61% | Sharpe 0.73
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

# ── [V32f-1] Tier 3 hold window ───────────────────────────────────────────────
_lib.TIER3_HOLD_DAYS = 6   # was 8

# ── [V32f-2] VIX trend sizing parameters ─────────────────────────────────────
VIX_TREND_MA        = 5
VIX_DOWN_MULTIPLIER = 0.80

# ── Override download_reference_data to add VIX MA ───────────────────────────
_orig_download_reference_data = _lib.download_reference_data

def _v32f_download_reference_data():
    spy, vix, sector_data = _orig_download_reference_data()
    vix_close = vix["Close"].squeeze()
    vix["vix_ma"] = vix_close.rolling(VIX_TREND_MA).mean()
    vix["vix_trending_up"] = vix_close > vix["vix_ma"]
    pct_reduced = (~vix["vix_trending_up"]).mean() * 100
    print(f"[V32f] VIX {VIX_TREND_MA}-day trend: size at "
          f"{VIX_DOWN_MULTIPLIER*100:.0f}% on ~{pct_reduced:.1f}% of days")
    return spy, vix, sector_data

_lib.download_reference_data = _v32f_download_reference_data

# ── Override get_position_size to apply VIX trend multiplier ─────────────────
_orig_get_position_size = _lib.get_position_size

def _v32f_get_position_size(today, vix_df, drawdown_pct: float = 0.0) -> float:
    base = _orig_get_position_size(today, vix_df, drawdown_pct)
    try:
        if today in vix_df.index and "vix_trending_up" in vix_df.columns:
            if not bool(vix_df.loc[today, "vix_trending_up"]):
                base = base * VIX_DOWN_MULTIPLIER
    except Exception:
        pass
    return base

_lib.get_position_size = _v32f_get_position_size

# ── Override run_backtest with composite ranking ──────────────────────────────
def _v32f_run_backtest(price_data, spy_df, vix_df, sector_data, earnings_map):
    print("\n[Backtest] Running V32f — Tier3 hold 6d + VIX trend sizing + composite ranking ...")

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
    composite_used = 0
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

        # Exits
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

        # Entries with composite ranking
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
            composite_score = rsi2 / atr_pct if atr_pct > 0 else rsi2 * 1000
            candidates.append((composite_score, tkr, int(row["consec_down"]), rsi2))

        if candidates:
            total_entry_days += 1
            slots_available = _lib.MAX_POSITIONS - len(open_positions)
            if len(candidates) > slots_available:
                rsi_order = set(x[1] for x in sorted(candidates, key=lambda x: x[3])[:slots_available])
                comp_order = set(x[1] for x in sorted(candidates, key=lambda x: x[0])[:slots_available])
                if rsi_order != comp_order:
                    composite_used += 1

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
        print(f"[V32f] Composite ranking changed selection on "
              f"{composite_used}/{total_entry_days} constrained days "
              f"({composite_used/total_entry_days*100:.1f}%)")
    return pd.DataFrame(trades)

_lib.run_backtest = _v32f_run_backtest

# ── Labels ────────────────────────────────────────────────────────────────────
_orig_compute_metrics = _lib.compute_metrics

def _v32f_compute_metrics(trades_df):
    metrics, eq_df = _orig_compute_metrics(trades_df)
    if isinstance(metrics, dict):
        metrics["version"] = "V32f"
        metrics["parameters"]["version"] = "V32f"
        metrics["parameters"]["tier3_hold_days"] = "6 (was 8) — Tier 3 only [V32f-1]"
        metrics["parameters"]["v32f_changes"] = (
            "[V32f-1] TIER3_HOLD_DAYS 8→6 | "
            f"[V32f-2] VIX {VIX_TREND_MA}-day trend: falling → {VIX_DOWN_MULTIPLIER*100:.0f}% size | "
            "[V32f-3] Composite ranking: RSI(2)/ATR_pct"
        )
    return metrics, eq_df

_lib.compute_metrics = _v32f_compute_metrics

def _v32f_save_outputs(trades_df, metrics, eq_df):
    import json
    from pathlib import Path
    OUTPUT_DIR = Path("results")
    OUTPUT_DIR.mkdir(exist_ok=True)
    trades_df.to_csv(OUTPUT_DIR / "trades.csv", index=False)
    eq_df.to_csv(OUTPUT_DIR / "equity_curve.csv", index=False)
    with open(OUTPUT_DIR / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, default=str)
    print("\n" + "=" * 70)
    print("  NAIVE MR BACKTEST — V32f")
    print("  Tier3 hold 6d + VIX trend 80% sizing + composite ranking")
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
    print("\n  V32f vs baselines:")
    print("  Target:     ~$2,200k | Sharpe ~0.78 | MaxDD ~-39% | CAGR ~15.5%")
    print("  V30+S&P600: $2,414k  | Sharpe 0.73  | MaxDD -48.65% | CAGR 16.01%")
    print("  V32d:       $2,145k  | Sharpe 0.77  | MaxDD -39.21% | CAGR 15.37%")
    print("  V32e:       $2,454k  | Sharpe 0.73  | MaxDD -48.61% | CAGR 16.10%")
    print("=" * 70)
    print(f"\n  Saved to: {OUTPUT_DIR.resolve()}")

_lib.save_outputs = _v32f_save_outputs

if __name__ == "__main__":
    universe = get_universe()
    price_data = download_prices(universe)
    spy_df, vix_df, sector_data = _lib.download_reference_data()
    earnings_map = build_earnings_dates(list(price_data.keys()))
    trades_df = _lib.run_backtest(price_data, spy_df, vix_df, sector_data, earnings_map)
    if trades_df.empty:
        print("[ERROR] No trades generated.")
    else:
        metrics, eq_df = _lib.compute_metrics(trades_df)
        _lib.save_outputs(trades_df, metrics, eq_df)
