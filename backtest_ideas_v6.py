# backtest_ideas_v6.py
#
# Single test: V47 + Idea 3 put spread (confirmed best strategy).
# Architecture identical to backtest_ideas_v2.py — imports from
# backtest_nmr_lib_v47.py so all V47 parameters are active.
#
# Run via: python backtest_ideas_v6.py
# Or via GitHub Actions: V47+I3 Backtest workflow
# Output: results_ideas_v6/

import json
import warnings
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore")

from backtest_nmr_lib_v47 import (
    get_universe, download_prices, download_reference_data,
    build_earnings_dates, compute_metrics,
    generate_signals, get_position_size, get_tier, calc_commission,
    sector_ok, count_sector_positions, check_vix_spike, near_earnings,
    TICKER_TO_SECTOR, INITIAL_CAPITAL, MAX_POSITIONS, MA_WINDOW,
    VOL_MA_PERIOD, ATR_PERIOD, MIN_CONSEC_DOWN, MIN_HOLD_BEFORE_EXIT,
    VELOCITY_CRASH_5D_THRESHOLD, VELOCITY_CRASH_PAUSE_DAYS,
    VIX_SPIKE_PAUSE_DAYS, GAP_DOWN_MAX, GAP_UP_MAX,
    REENTRY_COOLDOWN_DAYS, MAX_SECTOR_POSITIONS, EARNINGS_BLACKOUT,
    TOP_SIGNAL_PCT, TOP_SIGNAL_MULTIPLIER, TOP_SIGNAL_HARD_CAP,
    MIN_CANDIDATES_FOR_C5,
    # V47-specific — already baked into run_backtest but we need
    # these for the manual loop below
    TOM_MULT, DOW_MULT, VIX_TIGHT_THRESH, RSI_TIGHT_THRESH,
    build_tom_set, get_vix_level,
)

OUTPUT_DIR = Path("results_ideas_v6")
OUTPUT_DIR.mkdir(exist_ok=True)

# Put spread parameters (identical to Ideas V2 Idea3)
PUT_SPREAD_LOWER_OTM      = 0.05
PUT_SPREAD_UPPER_OTM      = 0.15
PUT_SPREAD_QUARTERLY_COST = 0.0075
PUT_SPREAD_RENEW_DAYS     = 63

def compute_put_spread_intrinsic_pct(spy_ref, spy_worst):
    lower_strike = spy_ref * (1 - PUT_SPREAD_LOWER_OTM)
    spread_width = PUT_SPREAD_UPPER_OTM - PUT_SPREAD_LOWER_OTM
    if spy_worst >= lower_strike:
        return 0.0
    decline    = (spy_ref - spy_worst) / spy_ref
    payout_pct = max(0.0, min(decline - PUT_SPREAD_LOWER_OTM, spread_width))
    return payout_pct

def run_v47_i3(price_data, spy_df, vix_df, sector_data, earnings_map):
    print("\n" + "="*60)
    print("[Test] V47 + Idea3 Put Spread")
    print("="*60)

    spy_regime = spy_df["spy_ok"].to_dict()
    spy_close  = spy_df["Close"].squeeze()

    all_dates = set()
    for df in price_data.values():
        all_dates.update(df.index)
    trading_dates = sorted(all_dates)

    tom_set = build_tom_set(trading_dates)

    signals = {}
    min_bars = MA_WINDOW + VOL_MA_PERIOD + ATR_PERIOD + MIN_CONSEC_DOWN + 5
    for tkr, df in price_data.items():
        if len(df) > min_bars:
            signals[tkr] = generate_signals(df)

    portfolio_value     = INITIAL_CAPITAL
    portfolio_peak      = None
    current_drawdown    = 0.0
    open_positions      = {}
    trades              = []
    cooldown_map        = {}
    last_vix_spike      = None
    last_velocity_crash = None

    # Put spread state
    put_ref_price        = None
    put_ref_date         = None
    put_notional         = 0.0
    put_min_spy          = 9999.0
    put_days_since_renew = 0

    for today in trading_dates:
        spy_ok = spy_regime.get(today, True)
        paused, last_vix_spike = check_vix_spike(today, vix_df, last_vix_spike)

        velocity_paused = False
        try:
            if today in spy_df.index:
                spy_5d = float(spy_df.loc[today, "spy_5d_ret"])
                if not np.isnan(spy_5d) and spy_5d < VELOCITY_CRASH_5D_THRESHOLD:
                    last_velocity_crash = today
            if last_velocity_crash is not None:
                if (pd.Timestamp(today) - pd.Timestamp(last_velocity_crash)).days <= VELOCITY_CRASH_PAUSE_DAYS:
                    velocity_paused = True
        except Exception:
            pass

        if portfolio_peak is None:
            if portfolio_value != INITIAL_CAPITAL:
                portfolio_peak   = portfolio_value
                current_drawdown = 0.0
        else:
            if portfolio_value > portfolio_peak:
                portfolio_peak   = portfolio_value
                current_drawdown = 0.0
            else:
                current_drawdown = (portfolio_value - portfolio_peak) / portfolio_peak

        # ── Put spread ────────────────────────────────────────────────────────
        if today in spy_df.index:
            spy_px = float(spy_close.loc[today]) if today in spy_close.index else None
            if spy_px is not None:
                if put_ref_price is None or put_days_since_renew >= PUT_SPREAD_RENEW_DAYS:
                    premium = portfolio_value * PUT_SPREAD_QUARTERLY_COST
                    portfolio_value     -= premium
                    put_ref_price        = spy_px
                    put_ref_date         = today
                    put_notional         = portfolio_value
                    put_min_spy          = spy_px
                    put_days_since_renew = 0
                    trades.append({
                        "ticker": "SPY_PUT_SPREAD", "entry_date": today, "exit_date": today,
                        "entry_price": spy_px, "exit_price": spy_px, "shares": 0, "commission": 0,
                        "pnl_usd": -premium, "pnl_pct": -PUT_SPREAD_QUARTERLY_COST * 100,
                        "days_held": 0, "exit_reason": "put_premium",
                        "tier": 0, "consec_down": 0, "portfolio_val": portfolio_value,
                    })
                else:
                    put_days_since_renew += 1
                    put_min_spy = min(put_min_spy, spy_px)
                    if put_days_since_renew == PUT_SPREAD_RENEW_DAYS - 1:
                        payout_pct = compute_put_spread_intrinsic_pct(put_ref_price, put_min_spy)
                        if payout_pct > 0:
                            payout = put_notional * payout_pct
                            portfolio_value += payout
                            trades.append({
                                "ticker": "SPY_PUT_SPREAD", "entry_date": put_ref_date,
                                "exit_date": today, "entry_price": put_ref_price,
                                "exit_price": put_min_spy, "shares": 0, "commission": 0,
                                "pnl_usd": round(payout, 2), "pnl_pct": round(payout_pct * 100, 4),
                                "days_held": put_days_since_renew, "exit_reason": "put_payout",
                                "tier": 0, "consec_down": 0, "portfolio_val": portfolio_value,
                            })

        # ── MR Exits ──────────────────────────────────────────────────────────
        to_close = []
        for tkr, pos in open_positions.items():
            if tkr not in signals:
                continue
            tkr_df = signals[tkr]
            if today not in tkr_df.index:
                continue
            row        = tkr_df.loc[today]
            exit_price = float(row["Close"])
            entry_price = pos["entry_price"]
            days_held  = (pd.Timestamp(today) - pd.Timestamp(pos["entry_date"])).days
            pos_pct    = (exit_price - entry_price) / entry_price
            shares_rem = pos["shares_remaining"]
            early      = days_held < MIN_HOLD_BEFORE_EXIT
            time_stop  = days_held >= pos["hold_days"]
            profit_hit = (not early) and pos_pct >= pos["profit_target"]

            if (pos["partial_enabled"] and not pos["partial_done"]
                    and not early and pos_pct >= pos["partial_trigger"]):
                partial_sh = shares_rem * pos["partial_frac"]
                comm = calc_commission(partial_sh, exit_price)
                pnl  = (exit_price - entry_price) * partial_sh - comm
                trades.append({
                    "ticker": tkr, "entry_date": pos["entry_date"], "exit_date": today,
                    "entry_price": entry_price, "exit_price": exit_price,
                    "shares": partial_sh, "commission": round(comm, 4),
                    "pnl_usd": pnl, "pnl_pct": pos_pct * 100, "days_held": days_held,
                    "exit_reason": "partial_exit", "tier": pos["tier"],
                    "consec_down": pos["consec_down_at_entry"],
                    "portfolio_val": portfolio_value + pnl,
                })
                portfolio_value       += pnl
                pos["shares_remaining"] -= partial_sh
                pos["partial_done"]    = True
                pos["profit_target"]   = pos["profit_target"] * 2
                continue

            full_exit = (
                time_stop
                or (not pos["partial_enabled"] and profit_hit)
                or (pos["partial_enabled"] and pos["partial_done"] and profit_hit)
            )
            if full_exit:
                comm = calc_commission(shares_rem, exit_price)
                pnl  = (exit_price - entry_price) * shares_rem - comm - pos["entry_commission"]
                reason = "time_stop" if time_stop else "profit_target"
                trades.append({
                    "ticker": tkr, "entry_date": pos["entry_date"], "exit_date": today,
                    "entry_price": entry_price, "exit_price": exit_price,
                    "shares": shares_rem,
                    "commission": round(comm + pos["entry_commission"], 4),
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
        if len(open_positions) >= MAX_POSITIONS:
            continue

        # ── MR Entries (V47 sizing) ───────────────────────────────────────────
        vix_now   = get_vix_level(today, vix_df)
        tom_today = today in tom_set
        dow       = pd.Timestamp(today).dayofweek

        candidates = []
        for tkr, tkr_df in signals.items():
            if tkr in open_positions or today not in tkr_df.index:
                continue
            row = tkr_df.loc[today]
            if not row["signal"]:
                continue
            if vix_now < VIX_TIGHT_THRESH and float(row["rsi2"]) >= RSI_TIGHT_THRESH:
                continue
            if tkr in cooldown_map:
                if (pd.Timestamp(today) - pd.Timestamp(cooldown_map[tkr])).days < REENTRY_COOLDOWN_DAYS:
                    continue
            if near_earnings(tkr, today, earnings_map):
                continue
            if not sector_ok(tkr, today, sector_data):
                continue
            if count_sector_positions(tkr, open_positions) >= MAX_SECTOR_POSITIONS:
                continue
            rsi2    = float(row["rsi2"])
            atr_pct = float(row["atr_pct"])
            score   = rsi2 / atr_pct if atr_pct > 0 else rsi2 * 1000
            candidates.append((score, tkr, int(row["consec_down"]), rsi2))

        candidates.sort(key=lambda x: x[0])
        n_candidates = len(candidates)
        top_n        = max(1, int(n_candidates * TOP_SIGNAL_PCT))

        for rank, (score, tkr, consec_val, rsi_val) in enumerate(candidates):
            if len(open_positions) >= MAX_POSITIONS:
                break
            tkr_df    = signals[tkr]
            today_idx = tkr_df.index.get_loc(today)
            if today_idx + 1 >= len(tkr_df):
                continue
            next_row    = tkr_df.iloc[today_idx + 1]
            entry_price = float(next_row["Open"])
            if entry_price <= 0:
                continue
            prev_close = float(tkr_df.iloc[today_idx]["Close"])
            gap_pct    = (entry_price - prev_close) / prev_close
            if gap_pct < GAP_DOWN_MAX or gap_pct > GAP_UP_MAX:
                continue

            tier_cfg = get_tier(consec_val)

            size_multiplier = 1.0
            if n_candidates >= MIN_CANDIDATES_FOR_C5 and rank < top_n:
                size_multiplier = TOP_SIGNAL_MULTIPLIER
            if tom_today:
                size_multiplier *= TOM_MULT
            size_multiplier *= DOW_MULT.get(dow, 1.0)

            pos_size   = get_position_size(today, vix_df, current_drawdown,
                                           multiplier=size_multiplier,
                                           hard_cap=TOP_SIGNAL_HARD_CAP)
            shares     = (portfolio_value * pos_size) / entry_price
            entry_comm = calc_commission(shares, entry_price)

            open_positions[tkr] = {
                "entry_date":           tkr_df.index[today_idx + 1],
                "entry_price":          entry_price,
                "shares":               shares,
                "shares_remaining":     shares,
                "rsi2_at_entry":        rsi_val,
                "consec_down_at_entry": consec_val,
                "profit_target":        tier_cfg["profit_target"],
                "hold_days":            tier_cfg["hold_days"],
                "partial_enabled":      tier_cfg["partial_enabled"],
                "partial_frac":         tier_cfg["partial_frac"],
                "partial_trigger":      tier_cfg["partial_trigger"],
                "partial_done":         False,
                "tier":                 tier_cfg["tier"],
                "entry_commission":     entry_comm,
            }

    print(f"[V47+I3] Complete -- {len(trades)} total trade records.")
    return pd.DataFrame(trades)


def main():
    print("\n" + "="*60)
    print("  V47 + Idea3 Put Spread Backtest")
    print("  Confirms the definitive V47+I3 equity and CAGR figure")
    print("="*60)

    universe     = get_universe()
    price_data   = download_prices(universe)
    spy_df, vix_df, sector_data = download_reference_data()
    earnings_map = build_earnings_dates(list(price_data.keys()))

    trades_df = run_v47_i3(price_data, spy_df, vix_df, sector_data, earnings_map)
    if trades_df.empty:
        print("[ERROR] No trades generated.")
        return

    mr_trades = trades_df[trades_df["ticker"] != "SPY_PUT_SPREAD"].copy()
    metrics, eq_df = compute_metrics(mr_trades)

    put_pnl = trades_df[trades_df["ticker"] == "SPY_PUT_SPREAD"]["pnl_usd"].sum()
    put_premiums = trades_df[(trades_df["ticker"] == "SPY_PUT_SPREAD") &
                             (trades_df["exit_reason"] == "put_premium")]["pnl_usd"].sum()
    put_payouts  = trades_df[(trades_df["ticker"] == "SPY_PUT_SPREAD") &
                             (trades_df["exit_reason"] == "put_payout")]["pnl_usd"].sum()

    metrics["final_equity"]      = round(metrics["final_equity"] + put_pnl, 2)
    metrics["version"]           = "V47+I3"
    metrics["note_put_net_pnl"]  = round(put_pnl, 2)
    metrics["note_put_premiums"] = round(put_premiums, 2)
    metrics["note_put_payouts"]  = round(put_payouts, 2)

    # Save
    trades_df.to_csv(OUTPUT_DIR / "trades_all.csv", index=False)
    mr_trades.to_csv(OUTPUT_DIR / "trades_mr.csv", index=False)
    eq_df.to_csv(OUTPUT_DIR / "equity_curve.csv", index=False)
    with open(OUTPUT_DIR / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, default=str)

    print(f"\n{'='*60}")
    print(f"  V47 + Idea3 CONFIRMED RESULTS")
    print(f"{'='*60}")
    print(f"  CAGR (MR only)       : {metrics['cagr_pct']:.2f}%")
    print(f"  Final Equity (MR+put): ${metrics['final_equity']:,.0f}")
    print(f"  Max Drawdown         : {metrics['max_drawdown_pct']:.2f}%")
    print(f"  Sharpe Ratio         : {metrics['sharpe_ratio']:.2f}")
    print(f"  Win Rate             : {metrics['win_rate_pct']:.2f}%")
    print(f"  Profit Factor        : {metrics['profit_factor']:.2f}")
    print(f"  Put premiums paid    : ${put_premiums:,.0f}")
    print(f"  Put payouts received : ${put_payouts:,.0f}")
    print(f"  Put net P&L          : ${put_pnl:,.0f}")
    print(f"{'='*60}")
    print(f"\n  Results saved to: {OUTPUT_DIR.resolve()}")

    if "year_stats" in metrics:
        print(f"\n  Per-Year P&L (MR only):")
        for yr, yv in metrics["year_stats"].items():
            print(f"    {yr}: {yv['trades']:>5} trades  WR {yv['win_rate']:>5}%  "
                  f"P&L ${yv['pnl_usd']:>10,.0f}")


if __name__ == "__main__":
    main()
