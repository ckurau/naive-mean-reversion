# backtest_ideas_v7.py
#
# Ideas V7 — Drawdown Reduction Research vs V47+I3 baseline
#
# Tests 7 new ideas, each additive on V47+I3, comparable to:
#   Baseline: V47+I3, full history -> $9,915,308, CAGR 22.40%, MaxDD -60.89%
#
# Test matrix:
#   Baseline  — V47+I3 (reproduced for exact apples-to-apples comparison)
#   Idea_A    — VIX call spread overlay (monthly, long 20-strike short 40-strike)
#   Idea_B    — CDaR-based global leverage scaling (rolling 63-day CDaR-95)
#   Idea_C    — VVIX-gated position sizing (VVIX > 120 -> 0.7x, > 140 -> 0.5x)
#   Idea_D    — Regime-conditional put spread strikes (VIX-adaptive OTM selection)
#   Idea_E    — Cross-sectional gap-behavior regime sizing (rolling 3-day candidate gap ratio)
#   Idea_F    — Partial time-stop exit at day 5 for worst 50% by P&L
#   Idea_Best — Best individual idea + V47+I3 (stacked, to test highest-impact combo)
#
# Architecture:
#   - Imports from backtest_nmr_lib_v47.py (all V47 parameters active)
#   - Follows same pattern as backtest_ideas_v2.py, v3.py, v4.py, v5.py, v6.py
#   - Each test has its own run_* function with clear, isolated modifications
#   - Results saved to results_ideas_v7/ as JSON, CSV, and a summary comparison table
#
# Run: python backtest_ideas_v7.py
# GitHub Actions: ideas_v7_backtest.yml

import json
import warnings
import datetime
from pathlib import Path
from collections import deque

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

from backtest_nmr_lib_v47 import (
    get_universe,
    download_prices,
    download_reference_data,
    build_earnings_dates,
    compute_metrics,
    generate_signals,
    get_position_size,
    get_tier,
    calc_commission,
    sector_ok,
    count_sector_positions,
    check_vix_spike,
    near_earnings,
    TICKER_TO_SECTOR,
    INITIAL_CAPITAL,
    MAX_POSITIONS,
    MA_WINDOW,
    VOL_MA_PERIOD,
    ATR_PERIOD,
    MIN_CONSEC_DOWN,
    MIN_HOLD_BEFORE_EXIT,
    VELOCITY_CRASH_5D_THRESHOLD,
    VELOCITY_CRASH_PAUSE_DAYS,
    GAP_DOWN_MAX,
    GAP_UP_MAX,
    REENTRY_COOLDOWN_DAYS,
    MAX_SECTOR_POSITIONS,
    TOP_SIGNAL_PCT,
    TOP_SIGNAL_MULTIPLIER,
    TOP_SIGNAL_HARD_CAP,
    MIN_CANDIDATES_FOR_C5,
    TOM_MULT,
    DOW_MULT,
    VIX_TIGHT_THRESH,
    RSI_TIGHT_THRESH,
    build_tom_set,
    get_vix_level,
    START_DATE,
    END_DATE,
)

OUTPUT_DIR = Path("results_ideas_v7")
OUTPUT_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Baseline put spread parameters (identical to Ideas V2 Idea3 / V6)
# ---------------------------------------------------------------------------
PUT_SPREAD_LOWER_OTM = 0.05
PUT_SPREAD_UPPER_OTM = 0.15
PUT_SPREAD_QUARTERLY_COST = 0.0075
PUT_SPREAD_RENEW_DAYS = 63

# ---------------------------------------------------------------------------
# Idea_A: VIX call spread parameters
# Monthly: long VIX 20-strike call, short VIX 40-strike call
# Modelled as: pay premium each month, receive payout if VIX closes above 20
# ---------------------------------------------------------------------------
VIX_CALL_SPREAD_MONTHLY_COST_PCT = 0.003  # ~0.3% of portfolio per month (~$900/mo at $300k)
VIX_CALL_LOWER_STRIKE = 20.0
VIX_CALL_UPPER_STRIKE = 40.0
VIX_CALL_RENEW_DAYS = 21  # monthly (~21 trading days)

def compute_vix_call_spread_payout_pct(vix_ref, vix_peak):
    """Payout proportional to VIX exceeding 20, capped at 40. Max payout = 10x premium."""
    if vix_peak <= VIX_CALL_LOWER_STRIKE:
        return 0.0
    spread_width = VIX_CALL_UPPER_STRIKE - VIX_CALL_LOWER_STRIKE  # 20 points
    vix_above = min(vix_peak - VIX_CALL_LOWER_STRIKE, spread_width)
    # Rough model: 10x payoff at full spread width (40 VIX)
    # Linear interpolation: 0x at VIX=20, 10x at VIX=40
    payoff_multiplier = (vix_above / spread_width) * 10.0
    return payoff_multiplier  # multiplier on the premium paid

# ---------------------------------------------------------------------------
# Idea_B: CDaR-based global leverage scaling
# ---------------------------------------------------------------------------
CDAR_WINDOW_DAYS = 63
CDAR_CONFIDENCE = 0.95
CDAR_TARGET = 0.08  # target 8% CDaR — scale down if current CDaR exceeds this
CDAR_MIN_SCALE = 0.40  # floor — never go below 40% of normal position size

def compute_cdar(equity_history: list, window: int = 63, confidence: float = 0.95) -> float:
    """
    Compute rolling CDaR-95 from equity history.
    Returns the average of the worst (1-confidence)% of max drawdowns
    over overlapping windows of `window` days.
    """
    if len(equity_history) < window + 1:
        return 0.0
    recent = list(equity_history)[-window * 2:]  # use 2x window for stability
    drawdowns = []
    n = len(recent)
    for start in range(n - window):
        chunk = recent[start:start + window]
        peak = max(chunk)
        trough = min(chunk[chunk.index(peak):]) if peak in chunk else min(chunk)
        dd = (trough - peak) / peak if peak > 0 else 0.0
        drawdowns.append(abs(dd))
    if not drawdowns:
        return 0.0
    drawdowns.sort(reverse=True)
    tail_count = max(1, int(len(drawdowns) * (1 - confidence)))
    return sum(drawdowns[:tail_count]) / tail_count

def get_cdar_scale_factor(cdar_value: float) -> float:
    """Returns a size multiplier: 1.0 if CDaR is healthy, scaling down to CDAR_MIN_SCALE."""
    if cdar_value <= CDAR_TARGET:
        return 1.0
    # Linear scale: at 2x target, use CDAR_MIN_SCALE
    excess = (cdar_value - CDAR_TARGET) / CDAR_TARGET
    scale = 1.0 - excess * (1.0 - CDAR_MIN_SCALE)
    return max(scale, CDAR_MIN_SCALE)

# ---------------------------------------------------------------------------
# Idea_C: VVIX-gated position sizing
# ---------------------------------------------------------------------------
VVIX_MODERATE_THRESH = 120.0
VVIX_EXTREME_THRESH = 140.0
VVIX_MODERATE_MULT = 0.70
VVIX_EXTREME_MULT = 0.50

def download_vvix() -> pd.DataFrame:
    """Download VVIX (volatility of VIX) historical data."""
    print("[Download] Fetching VVIX (^VVIX) ...")
    try:
        df = yf.download("^VVIX", start=START_DATE, end=END_DATE, auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        print(f"[Download] VVIX: {len(df)} rows")
        return df
    except Exception as e:
        print(f"[Download] VVIX failed: {e}. Idea_C will use neutral multiplier.")
        return pd.DataFrame()

def get_vvix_level(today, vvix_df: pd.DataFrame) -> float:
    """Get VVIX level for a given date, default 100 (neutral) if unavailable."""
    if vvix_df.empty:
        return 100.0
    try:
        vc = vvix_df["Close"].squeeze()
        if today in vc.index:
            return float(vc.loc[today])
    except Exception:
        pass
    return 100.0

def get_vvix_size_mult(vvix_level: float) -> float:
    if vvix_level >= VVIX_EXTREME_THRESH:
        return VVIX_EXTREME_MULT
    elif vvix_level >= VVIX_MODERATE_THRESH:
        return VVIX_MODERATE_MULT
    return 1.0

# ---------------------------------------------------------------------------
# Idea_D: Regime-conditional put spread strikes
# VIX < 15  -> tight:  3% / 13% OTM
# VIX 15-25 -> normal: 5% / 15% OTM  (baseline)
# VIX > 25  -> wide:   8% / 20% OTM
# ---------------------------------------------------------------------------
def get_put_spread_strikes(vix_level: float) -> tuple:
    """Returns (lower_otm, upper_otm) based on VIX regime."""
    if vix_level < 15.0:
        return 0.03, 0.13
    elif vix_level <= 25.0:
        return 0.05, 0.15
    else:
        return 0.08, 0.20

def compute_put_spread_intrinsic_pct(spy_ref, spy_worst, lower_otm, upper_otm):
    """Generic version accepting dynamic strike levels."""
    lower_strike = spy_ref * (1 - lower_otm)
    spread_width = upper_otm - lower_otm
    if spy_worst >= lower_strike:
        return 0.0
    decline = (spy_ref - spy_worst) / spy_ref
    payout_pct = max(0.0, min(decline - lower_otm, spread_width))
    return payout_pct

# ---------------------------------------------------------------------------
# Idea_E: Cross-sectional gap-behavior regime sizing
# ---------------------------------------------------------------------------
GAP_BEHAVIOR_WINDOW = 3       # rolling 3 scan days
GAP_BEHAVIOR_THRESHOLD = 0.60 # if >60% of candidates gapped down >0.5%, compress sizing
GAP_BEHAVIOR_MULT = 0.60      # 60% of normal position size when firing
GAP_DOWN_SIGNAL_THRESH = -0.005  # 0.5% gap down in candidate set

# ---------------------------------------------------------------------------
# Idea_F: Day-5 partial time-stop exit for worst 50% by P&L
# ---------------------------------------------------------------------------
DAY5_EXIT_FRACTION = 0.50     # exit this fraction of positions at day 5
DAY5_TRIGGER_DAYS = 5         # trigger day
DAY5_WORST_FRACTION = 0.50    # exit the worst-performing 50% by current P&L

# ---------------------------------------------------------------------------
# Core MR loop — shared logic, modular hooks for each idea
# ---------------------------------------------------------------------------

def _make_position(tkr_df, today_idx, today, entry_price, prev_close, consec_val,
                   rsi_val, portfolio_value, vix_df, current_drawdown, size_multiplier,
                   n_candidates, rank):
    """Create a position dict — used by all test variants."""
    tier_cfg = get_tier(consec_val)
    sm = size_multiplier  # may be further modified by caller
    pos_size = get_position_size(
        today, vix_df, current_drawdown,
        multiplier=sm,
        hard_cap=TOP_SIGNAL_HARD_CAP,
    )
    shares = (portfolio_value * pos_size) / entry_price
    entry_comm = calc_commission(shares, entry_price)
    return {
        "entry_date": tkr_df.index[today_idx + 1],
        "entry_price": entry_price,
        "shares": shares,
        "shares_remaining": shares,
        "rsi2_at_entry": rsi_val,
        "consec_down_at_entry": consec_val,
        "profit_target": tier_cfg["profit_target"],
        "hold_days": tier_cfg["hold_days"],
        "partial_enabled": tier_cfg["partial_enabled"],
        "partial_frac": tier_cfg["partial_frac"],
        "partial_trigger": tier_cfg["partial_trigger"],
        "partial_done": False,
        "tier": tier_cfg["tier"],
        "entry_commission": entry_comm,
    }


def _process_put_spread(
    today, spy_df, spy_close, portfolio_value, trades,
    put_ref_price, put_ref_date, put_notional, put_min_spy, put_days_since_renew,
    lower_otm=PUT_SPREAD_LOWER_OTM, upper_otm=PUT_SPREAD_UPPER_OTM,
    vix_df=None  # used by Idea_D for dynamic strike selection
):
    """
    Processes one day of put spread logic. Returns updated state tuple:
    (portfolio_value, put_ref_price, put_ref_date, put_notional,
     put_min_spy, put_days_since_renew)
    """
    if today not in spy_df.index:
        return (portfolio_value, put_ref_price, put_ref_date,
                put_notional, put_min_spy, put_days_since_renew)

    spy_px = float(spy_close.loc[today]) if today in spy_close.index else None
    if spy_px is None:
        return (portfolio_value, put_ref_price, put_ref_date,
                put_notional, put_min_spy, put_days_since_renew)

    # If Idea_D, get dynamic strikes at renewal time
    if put_ref_price is None or put_days_since_renew >= PUT_SPREAD_RENEW_DAYS:
        if vix_df is not None:
            vix_now = get_vix_level(today, vix_df)
            lower_otm, upper_otm = get_put_spread_strikes(vix_now)
        premium = portfolio_value * PUT_SPREAD_QUARTERLY_COST
        portfolio_value -= premium
        put_ref_price = spy_px
        put_ref_date = today
        put_notional = portfolio_value
        put_min_spy = spy_px
        put_days_since_renew = 0
        trades.append({
            "ticker": "SPY_PUT_SPREAD",
            "entry_date": today,
            "exit_date": today,
            "entry_price": spy_px,
            "exit_price": spy_px,
            "shares": 0, "commission": 0,
            "pnl_usd": -premium,
            "pnl_pct": -PUT_SPREAD_QUARTERLY_COST * 100,
            "days_held": 0,
            "exit_reason": "put_premium",
            "tier": 0, "consec_down": 0,
            "portfolio_val": portfolio_value,
            "put_lower_otm": lower_otm,
            "put_upper_otm": upper_otm,
        })
    else:
        put_days_since_renew += 1
        put_min_spy = min(put_min_spy, spy_px)

        if put_days_since_renew == PUT_SPREAD_RENEW_DAYS - 1:
            payout_pct = compute_put_spread_intrinsic_pct(
                put_ref_price, put_min_spy, lower_otm, upper_otm)
            if payout_pct > 0:
                payout = put_notional * payout_pct
                portfolio_value += payout
                trades.append({
                    "ticker": "SPY_PUT_SPREAD",
                    "entry_date": put_ref_date,
                    "exit_date": today,
                    "entry_price": put_ref_price,
                    "exit_price": put_min_spy,
                    "shares": 0, "commission": 0,
                    "pnl_usd": round(payout, 2),
                    "pnl_pct": round(payout_pct * 100, 4),
                    "days_held": put_days_since_renew,
                    "exit_reason": "put_payout",
                    "tier": 0, "consec_down": 0,
                    "portfolio_val": portfolio_value,
                    "put_lower_otm": lower_otm,
                    "put_upper_otm": upper_otm,
                })

    return (portfolio_value, put_ref_price, put_ref_date,
            put_notional, put_min_spy, put_days_since_renew)


# ---------------------------------------------------------------------------
# TEST 0: Baseline — V47 + Idea3 (exact reproduction of backtest_ideas_v6.py)
# ---------------------------------------------------------------------------
def run_baseline(price_data, spy_df, vix_df, sector_data, earnings_map):
    """V47 + I3 Put Spread — exact reproduction for apples-to-apples comparison."""
    print("\n[Baseline] V47 + I3 (Put Spread) — reproduction")
    spy_regime = spy_df["spy_ok"].to_dict()
    spy_close = spy_df["Close"].squeeze()
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

    portfolio_value = INITIAL_CAPITAL
    portfolio_peak = None
    current_drawdown = 0.0
    open_positions = {}
    trades = []
    cooldown_map = {}
    last_vix_spike = None
    last_velocity_crash = None
    put_ref_price = None; put_ref_date = None
    put_notional = 0.0; put_min_spy = 9999.0; put_days_since_renew = 0

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
                portfolio_peak = portfolio_value; current_drawdown = 0.0
        else:
            if portfolio_value > portfolio_peak:
                portfolio_peak = portfolio_value; current_drawdown = 0.0
            else:
                current_drawdown = (portfolio_value - portfolio_peak) / portfolio_peak

        # Put spread
        (portfolio_value, put_ref_price, put_ref_date, put_notional,
         put_min_spy, put_days_since_renew) = _process_put_spread(
            today, spy_df, spy_close, portfolio_value, trades,
            put_ref_price, put_ref_date, put_notional, put_min_spy, put_days_since_renew)

        # Exits
        to_close = []
        for tkr, pos in open_positions.items():
            if tkr not in signals or today not in signals[tkr].index:
                continue
            row = signals[tkr].loc[today]
            exit_price = float(row["Close"])
            entry_price = pos["entry_price"]
            days_held = (pd.Timestamp(today) - pd.Timestamp(pos["entry_date"])).days
            pos_pct = (exit_price - entry_price) / entry_price
            shares_rem = pos["shares_remaining"]
            early = days_held < MIN_HOLD_BEFORE_EXIT
            time_stop = days_held >= pos["hold_days"]
            profit_hit = (not early) and pos_pct >= pos["profit_target"]

            if (pos["partial_enabled"] and not pos["partial_done"] and
                    not early and pos_pct >= pos["partial_trigger"]):
                partial_sh = shares_rem * pos["partial_frac"]
                comm = calc_commission(partial_sh, exit_price)
                pnl = (exit_price - entry_price) * partial_sh - comm
                trades.append({"ticker": tkr, "entry_date": pos["entry_date"],
                    "exit_date": today, "entry_price": entry_price, "exit_price": exit_price,
                    "shares": partial_sh, "commission": round(comm, 4), "pnl_usd": pnl,
                    "pnl_pct": pos_pct * 100, "days_held": days_held,
                    "exit_reason": "partial_exit", "tier": pos["tier"],
                    "consec_down": pos["consec_down_at_entry"], "portfolio_val": portfolio_value + pnl})
                portfolio_value += pnl
                pos["shares_remaining"] -= partial_sh
                pos["partial_done"] = True
                pos["profit_target"] = pos["profit_target"] * 2
                continue

            full_exit = (time_stop or (not pos["partial_enabled"] and profit_hit) or
                        (pos["partial_enabled"] and pos["partial_done"] and profit_hit))
            if full_exit:
                comm = calc_commission(shares_rem, exit_price)
                pnl = (exit_price - entry_price) * shares_rem - comm - pos["entry_commission"]
                reason = "time_stop" if time_stop else "profit_target"
                trades.append({"ticker": tkr, "entry_date": pos["entry_date"],
                    "exit_date": today, "entry_price": entry_price, "exit_price": exit_price,
                    "shares": shares_rem, "commission": round(comm + pos["entry_commission"], 4),
                    "pnl_usd": pnl, "pnl_pct": pos_pct * 100, "days_held": days_held,
                    "exit_reason": reason, "tier": pos["tier"],
                    "consec_down": pos["consec_down_at_entry"], "portfolio_val": portfolio_value + pnl})
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

        vix_now = get_vix_level(today, vix_df)
        tom_today = today in tom_set
        dow = pd.Timestamp(today).dayofweek
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
            rsi2 = float(row["rsi2"]); atr_pct = float(row["atr_pct"])
            score = rsi2 / atr_pct if atr_pct > 0 else rsi2 * 1000
            candidates.append((score, tkr, int(row["consec_down"]), rsi2))

        candidates.sort(key=lambda x: x[0])
        n_candidates = len(candidates)
        top_n = max(1, int(n_candidates * TOP_SIGNAL_PCT))

        for rank, (score, tkr, consec_val, rsi_val) in enumerate(candidates):
            if len(open_positions) >= MAX_POSITIONS:
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
            if gap_pct < GAP_DOWN_MAX or gap_pct > GAP_UP_MAX:
                continue
            sm = 1.0
            if n_candidates >= MIN_CANDIDATES_FOR_C5 and rank < top_n:
                sm = TOP_SIGNAL_MULTIPLIER
            if tom_today:
                sm *= TOM_MULT
            sm *= DOW_MULT.get(dow, 1.0)
            pos = _make_position(tkr_df, today_idx, today, entry_price, prev_close,
                                 consec_val, rsi_val, portfolio_value, vix_df,
                                 current_drawdown, sm, n_candidates, rank)
            open_positions[tkr] = pos

    print(f"[Baseline] {len(trades)} total trade records")
    return pd.DataFrame(trades)


# ---------------------------------------------------------------------------
# TEST A: V47 + I3 + VIX Call Spread Overlay
# ---------------------------------------------------------------------------
def run_idea_a(price_data, spy_df, vix_df, sector_data, earnings_map):
    """Idea_A: Add monthly VIX call spread (long 20, short 40) on top of V47+I3."""
    print("\n[Idea_A] V47 + I3 + VIX Call Spread overlay")
    spy_regime = spy_df["spy_ok"].to_dict()
    spy_close = spy_df["Close"].squeeze()
    vix_close = vix_df["Close"].squeeze()
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

    portfolio_value = INITIAL_CAPITAL
    portfolio_peak = None
    current_drawdown = 0.0
    open_positions = {}
    trades = []
    cooldown_map = {}
    last_vix_spike = None
    last_velocity_crash = None
    put_ref_price = None; put_ref_date = None
    put_notional = 0.0; put_min_spy = 9999.0; put_days_since_renew = 0
    # VIX call spread state
    vix_call_days_since_renew = 0
    vix_call_ref_vix = None
    vix_call_ref_date = None
    vix_call_notional = 0.0
    vix_call_peak_vix = 0.0
    vix_call_premium_paid = 0.0

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
                portfolio_peak = portfolio_value; current_drawdown = 0.0
        else:
            if portfolio_value > portfolio_peak:
                portfolio_peak = portfolio_value; current_drawdown = 0.0
            else:
                current_drawdown = (portfolio_value - portfolio_peak) / portfolio_peak

        # SPY Put spread (baseline)
        (portfolio_value, put_ref_price, put_ref_date, put_notional,
         put_min_spy, put_days_since_renew) = _process_put_spread(
            today, spy_df, spy_close, portfolio_value, trades,
            put_ref_price, put_ref_date, put_notional, put_min_spy, put_days_since_renew)

        # VIX call spread overlay
        if today in vix_df.index:
            vix_px = float(vix_close.loc[today]) if today in vix_close.index else None
            if vix_px is not None:
                if vix_call_ref_vix is None or vix_call_days_since_renew >= VIX_CALL_RENEW_DAYS:
                    # Renew: pay premium
                    premium = portfolio_value * VIX_CALL_SPREAD_MONTHLY_COST_PCT
                    portfolio_value -= premium
                    vix_call_ref_vix = vix_px
                    vix_call_ref_date = today
                    vix_call_notional = portfolio_value
                    vix_call_peak_vix = vix_px
                    vix_call_premium_paid = premium
                    vix_call_days_since_renew = 0
                    trades.append({
                        "ticker": "VIX_CALL_SPREAD",
                        "entry_date": today, "exit_date": today,
                        "entry_price": vix_px, "exit_price": vix_px,
                        "shares": 0, "commission": 0,
                        "pnl_usd": -premium,
                        "pnl_pct": -VIX_CALL_SPREAD_MONTHLY_COST_PCT * 100,
                        "days_held": 0, "exit_reason": "vix_call_premium",
                        "tier": 0, "consec_down": 0, "portfolio_val": portfolio_value,
                    })
                else:
                    vix_call_days_since_renew += 1
                    vix_call_peak_vix = max(vix_call_peak_vix, vix_px)

                    if vix_call_days_since_renew == VIX_CALL_RENEW_DAYS - 1:
                        # Settle: check payout
                        payoff_mult = compute_vix_call_spread_payout_pct(
                            vix_call_ref_vix, vix_call_peak_vix)
                        if payoff_mult > 0:
                            payout = vix_call_premium_paid * payoff_mult
                            portfolio_value += payout
                            trades.append({
                                "ticker": "VIX_CALL_SPREAD",
                                "entry_date": vix_call_ref_date, "exit_date": today,
                                "entry_price": vix_call_ref_vix, "exit_price": vix_call_peak_vix,
                                "shares": 0, "commission": 0,
                                "pnl_usd": round(payout, 2),
                                "pnl_pct": round(payoff_mult * VIX_CALL_SPREAD_MONTHLY_COST_PCT * 100, 4),
                                "days_held": vix_call_days_since_renew,
                                "exit_reason": "vix_call_payout",
                                "tier": 0, "consec_down": 0, "portfolio_val": portfolio_value,
                            })

        # Exits (identical to baseline)
        to_close = []
        for tkr, pos in open_positions.items():
            if tkr not in signals or today not in signals[tkr].index:
                continue
            row = signals[tkr].loc[today]
            exit_price = float(row["Close"])
            entry_price = pos["entry_price"]
            days_held = (pd.Timestamp(today) - pd.Timestamp(pos["entry_date"])).days
            pos_pct = (exit_price - entry_price) / entry_price
            shares_rem = pos["shares_remaining"]
            early = days_held < MIN_HOLD_BEFORE_EXIT
            time_stop = days_held >= pos["hold_days"]
            profit_hit = (not early) and pos_pct >= pos["profit_target"]

            if (pos["partial_enabled"] and not pos["partial_done"] and
                    not early and pos_pct >= pos["partial_trigger"]):
                partial_sh = shares_rem * pos["partial_frac"]
                comm = calc_commission(partial_sh, exit_price)
                pnl = (exit_price - entry_price) * partial_sh - comm
                trades.append({"ticker": tkr, "entry_date": pos["entry_date"],
                    "exit_date": today, "entry_price": entry_price, "exit_price": exit_price,
                    "shares": partial_sh, "commission": round(comm, 4), "pnl_usd": pnl,
                    "pnl_pct": pos_pct * 100, "days_held": days_held,
                    "exit_reason": "partial_exit", "tier": pos["tier"],
                    "consec_down": pos["consec_down_at_entry"], "portfolio_val": portfolio_value + pnl})
                portfolio_value += pnl
                pos["shares_remaining"] -= partial_sh
                pos["partial_done"] = True
                pos["profit_target"] = pos["profit_target"] * 2
                continue

            full_exit = (time_stop or (not pos["partial_enabled"] and profit_hit) or
                        (pos["partial_enabled"] and pos["partial_done"] and profit_hit))
            if full_exit:
                comm = calc_commission(shares_rem, exit_price)
                pnl = (exit_price - entry_price) * shares_rem - comm - pos["entry_commission"]
                reason = "time_stop" if time_stop else "profit_target"
                trades.append({"ticker": tkr, "entry_date": pos["entry_date"],
                    "exit_date": today, "entry_price": entry_price, "exit_price": exit_price,
                    "shares": shares_rem, "commission": round(comm + pos["entry_commission"], 4),
                    "pnl_usd": pnl, "pnl_pct": pos_pct * 100, "days_held": days_held,
                    "exit_reason": reason, "tier": pos["tier"],
                    "consec_down": pos["consec_down_at_entry"], "portfolio_val": portfolio_value + pnl})
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

        vix_now = get_vix_level(today, vix_df)
        tom_today = today in tom_set
        dow = pd.Timestamp(today).dayofweek
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
            rsi2 = float(row["rsi2"]); atr_pct = float(row["atr_pct"])
            score = rsi2 / atr_pct if atr_pct > 0 else rsi2 * 1000
            candidates.append((score, tkr, int(row["consec_down"]), rsi2))

        candidates.sort(key=lambda x: x[0])
        n_candidates = len(candidates)
        top_n = max(1, int(n_candidates * TOP_SIGNAL_PCT))

        for rank, (score, tkr, consec_val, rsi_val) in enumerate(candidates):
            if len(open_positions) >= MAX_POSITIONS:
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
            if gap_pct < GAP_DOWN_MAX or gap_pct > GAP_UP_MAX:
                continue
            sm = 1.0
            if n_candidates >= MIN_CANDIDATES_FOR_C5 and rank < top_n:
                sm = TOP_SIGNAL_MULTIPLIER
            if tom_today:
                sm *= TOM_MULT
            sm *= DOW_MULT.get(dow, 1.0)
            pos = _make_position(tkr_df, today_idx, today, entry_price, prev_close,
                                 consec_val, rsi_val, portfolio_value, vix_df,
                                 current_drawdown, sm, n_candidates, rank)
            open_positions[tkr] = pos

    print(f"[Idea_A] {len(trades)} total trade records")
    return pd.DataFrame(trades)


# ---------------------------------------------------------------------------
# TEST B: V47 + I3 + CDaR leverage scaling
# ---------------------------------------------------------------------------
def run_idea_b(price_data, spy_df, vix_df, sector_data, earnings_map):
    """Idea_B: CDaR-95 based global leverage scaling on top of V47+I3."""
    print("\n[Idea_B] V47 + I3 + CDaR leverage scaling")
    spy_regime = spy_df["spy_ok"].to_dict()
    spy_close = spy_df["Close"].squeeze()
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

    portfolio_value = INITIAL_CAPITAL
    portfolio_peak = None
    current_drawdown = 0.0
    open_positions = {}
    trades = []
    cooldown_map = {}
    last_vix_spike = None
    last_velocity_crash = None
    put_ref_price = None; put_ref_date = None
    put_notional = 0.0; put_min_spy = 9999.0; put_days_since_renew = 0
    equity_history = deque(maxlen=CDAR_WINDOW_DAYS * 2 + 10)
    equity_history.append(INITIAL_CAPITAL)

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
                portfolio_peak = portfolio_value; current_drawdown = 0.0
        else:
            if portfolio_value > portfolio_peak:
                portfolio_peak = portfolio_value; current_drawdown = 0.0
            else:
                current_drawdown = (portfolio_value - portfolio_peak) / portfolio_peak

        equity_history.append(portfolio_value)

        # CDaR scale factor
        cdar_val = compute_cdar(list(equity_history), CDAR_WINDOW_DAYS, CDAR_CONFIDENCE)
        cdar_scale = get_cdar_scale_factor(cdar_val)

        # Put spread
        (portfolio_value, put_ref_price, put_ref_date, put_notional,
         put_min_spy, put_days_since_renew) = _process_put_spread(
            today, spy_df, spy_close, portfolio_value, trades,
            put_ref_price, put_ref_date, put_notional, put_min_spy, put_days_since_renew)

        # Exits
        to_close = []
        for tkr, pos in open_positions.items():
            if tkr not in signals or today not in signals[tkr].index:
                continue
            row = signals[tkr].loc[today]
            exit_price = float(row["Close"])
            entry_price = pos["entry_price"]
            days_held = (pd.Timestamp(today) - pd.Timestamp(pos["entry_date"])).days
            pos_pct = (exit_price - entry_price) / entry_price
            shares_rem = pos["shares_remaining"]
            early = days_held < MIN_HOLD_BEFORE_EXIT
            time_stop = days_held >= pos["hold_days"]
            profit_hit = (not early) and pos_pct >= pos["profit_target"]

            if (pos["partial_enabled"] and not pos["partial_done"] and
                    not early and pos_pct >= pos["partial_trigger"]):
                partial_sh = shares_rem * pos["partial_frac"]
                comm = calc_commission(partial_sh, exit_price)
                pnl = (exit_price - entry_price) * partial_sh - comm
                trades.append({"ticker": tkr, "entry_date": pos["entry_date"],
                    "exit_date": today, "entry_price": entry_price, "exit_price": exit_price,
                    "shares": partial_sh, "commission": round(comm, 4), "pnl_usd": pnl,
                    "pnl_pct": pos_pct * 100, "days_held": days_held,
                    "exit_reason": "partial_exit", "tier": pos["tier"],
                    "consec_down": pos["consec_down_at_entry"], "portfolio_val": portfolio_value + pnl})
                portfolio_value += pnl
                pos["shares_remaining"] -= partial_sh
                pos["partial_done"] = True
                pos["profit_target"] = pos["profit_target"] * 2
                continue

            full_exit = (time_stop or (not pos["partial_enabled"] and profit_hit) or
                        (pos["partial_enabled"] and pos["partial_done"] and profit_hit))
            if full_exit:
                comm = calc_commission(shares_rem, exit_price)
                pnl = (exit_price - entry_price) * shares_rem - comm - pos["entry_commission"]
                reason = "time_stop" if time_stop else "profit_target"
                trades.append({"ticker": tkr, "entry_date": pos["entry_date"],
                    "exit_date": today, "entry_price": entry_price, "exit_price": exit_price,
                    "shares": shares_rem, "commission": round(comm + pos["entry_commission"], 4),
                    "pnl_usd": pnl, "pnl_pct": pos_pct * 100, "days_held": days_held,
                    "exit_reason": reason, "tier": pos["tier"],
                    "consec_down": pos["consec_down_at_entry"], "portfolio_val": portfolio_value + pnl})
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

        vix_now = get_vix_level(today, vix_df)
        tom_today = today in tom_set
        dow = pd.Timestamp(today).dayofweek
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
            rsi2 = float(row["rsi2"]); atr_pct = float(row["atr_pct"])
            score = rsi2 / atr_pct if atr_pct > 0 else rsi2 * 1000
            candidates.append((score, tkr, int(row["consec_down"]), rsi2))

        candidates.sort(key=lambda x: x[0])
        n_candidates = len(candidates)
        top_n = max(1, int(n_candidates * TOP_SIGNAL_PCT))

        for rank, (score, tkr, consec_val, rsi_val) in enumerate(candidates):
            if len(open_positions) >= MAX_POSITIONS:
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
            if gap_pct < GAP_DOWN_MAX or gap_pct > GAP_UP_MAX:
                continue
            sm = 1.0
            if n_candidates >= MIN_CANDIDATES_FOR_C5 and rank < top_n:
                sm = TOP_SIGNAL_MULTIPLIER
            if tom_today:
                sm *= TOM_MULT
            sm *= DOW_MULT.get(dow, 1.0)
            sm *= cdar_scale   # <-- CDaR scaling applied here
            pos = _make_position(tkr_df, today_idx, today, entry_price, prev_close,
                                 consec_val, rsi_val, portfolio_value, vix_df,
                                 current_drawdown, sm, n_candidates, rank)
            open_positions[tkr] = pos

    print(f"[Idea_B] {len(trades)} total trade records")
    return pd.DataFrame(trades)


# ---------------------------------------------------------------------------
# TEST C: V47 + I3 + VVIX-gated sizing
# ---------------------------------------------------------------------------
def run_idea_c(price_data, spy_df, vix_df, sector_data, earnings_map, vvix_df):
    """Idea_C: VVIX-gated position sizing on top of V47+I3."""
    print("\n[Idea_C] V47 + I3 + VVIX-gated sizing")
    spy_regime = spy_df["spy_ok"].to_dict()
    spy_close = spy_df["Close"].squeeze()
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

    portfolio_value = INITIAL_CAPITAL
    portfolio_peak = None
    current_drawdown = 0.0
    open_positions = {}
    trades = []
    cooldown_map = {}
    last_vix_spike = None
    last_velocity_crash = None
    put_ref_price = None; put_ref_date = None
    put_notional = 0.0; put_min_spy = 9999.0; put_days_since_renew = 0

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
                portfolio_peak = portfolio_value; current_drawdown = 0.0
        else:
            if portfolio_value > portfolio_peak:
                portfolio_peak = portfolio_value; current_drawdown = 0.0
            else:
                current_drawdown = (portfolio_value - portfolio_peak) / portfolio_peak

        # VVIX multiplier
        vvix_level = get_vvix_level(today, vvix_df)
        vvix_mult = get_vvix_size_mult(vvix_level)

        # Put spread
        (portfolio_value, put_ref_price, put_ref_date, put_notional,
         put_min_spy, put_days_since_renew) = _process_put_spread(
            today, spy_df, spy_close, portfolio_value, trades,
            put_ref_price, put_ref_date, put_notional, put_min_spy, put_days_since_renew)

        # Exits
        to_close = []
        for tkr, pos in open_positions.items():
            if tkr not in signals or today not in signals[tkr].index:
                continue
            row = signals[tkr].loc[today]
            exit_price = float(row["Close"])
            entry_price = pos["entry_price"]
            days_held = (pd.Timestamp(today) - pd.Timestamp(pos["entry_date"])).days
            pos_pct = (exit_price - entry_price) / entry_price
            shares_rem = pos["shares_remaining"]
            early = days_held < MIN_HOLD_BEFORE_EXIT
            time_stop = days_held >= pos["hold_days"]
            profit_hit = (not early) and pos_pct >= pos["profit_target"]

            if (pos["partial_enabled"] and not pos["partial_done"] and
                    not early and pos_pct >= pos["partial_trigger"]):
                partial_sh = shares_rem * pos["partial_frac"]
                comm = calc_commission(partial_sh, exit_price)
                pnl = (exit_price - entry_price) * partial_sh - comm
                trades.append({"ticker": tkr, "entry_date": pos["entry_date"],
                    "exit_date": today, "entry_price": entry_price, "exit_price": exit_price,
                    "shares": partial_sh, "commission": round(comm, 4), "pnl_usd": pnl,
                    "pnl_pct": pos_pct * 100, "days_held": days_held,
                    "exit_reason": "partial_exit", "tier": pos["tier"],
                    "consec_down": pos["consec_down_at_entry"], "portfolio_val": portfolio_value + pnl})
                portfolio_value += pnl
                pos["shares_remaining"] -= partial_sh
                pos["partial_done"] = True
                pos["profit_target"] = pos["profit_target"] * 2
                continue

            full_exit = (time_stop or (not pos["partial_enabled"] and profit_hit) or
                        (pos["partial_enabled"] and pos["partial_done"] and profit_hit))
            if full_exit:
                comm = calc_commission(shares_rem, exit_price)
                pnl = (exit_price - entry_price) * shares_rem - comm - pos["entry_commission"]
                reason = "time_stop" if time_stop else "profit_target"
                trades.append({"ticker": tkr, "entry_date": pos["entry_date"],
                    "exit_date": today, "entry_price": entry_price, "exit_price": exit_price,
                    "shares": shares_rem, "commission": round(comm + pos["entry_commission"], 4),
                    "pnl_usd": pnl, "pnl_pct": pos_pct * 100, "days_held": days_held,
                    "exit_reason": reason, "tier": pos["tier"],
                    "consec_down": pos["consec_down_at_entry"], "portfolio_val": portfolio_value + pnl})
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

        vix_now = get_vix_level(today, vix_df)
        tom_today = today in tom_set
        dow = pd.Timestamp(today).dayofweek
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
            rsi2 = float(row["rsi2"]); atr_pct = float(row["atr_pct"])
            score = rsi2 / atr_pct if atr_pct > 0 else rsi2 * 1000
            candidates.append((score, tkr, int(row["consec_down"]), rsi2))

        candidates.sort(key=lambda x: x[0])
        n_candidates = len(candidates)
        top_n = max(1, int(n_candidates * TOP_SIGNAL_PCT))

        for rank, (score, tkr, consec_val, rsi_val) in enumerate(candidates):
            if len(open_positions) >= MAX_POSITIONS:
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
            if gap_pct < GAP_DOWN_MAX or gap_pct > GAP_UP_MAX:
                continue
            sm = 1.0
            if n_candidates >= MIN_CANDIDATES_FOR_C5 and rank < top_n:
                sm = TOP_SIGNAL_MULTIPLIER
            if tom_today:
                sm *= TOM_MULT
            sm *= DOW_MULT.get(dow, 1.0)
            sm *= vvix_mult   # <-- VVIX gate
            pos = _make_position(tkr_df, today_idx, today, entry_price, prev_close,
                                 consec_val, rsi_val, portfolio_value, vix_df,
                                 current_drawdown, sm, n_candidates, rank)
            open_positions[tkr] = pos

    print(f"[Idea_C] {len(trades)} total trade records")
    return pd.DataFrame(trades)


# ---------------------------------------------------------------------------
# TEST D: V47 + Regime-conditional put spread strikes (replaces baseline I3)
# ---------------------------------------------------------------------------
def run_idea_d(price_data, spy_df, vix_df, sector_data, earnings_map):
    """Idea_D: V47 + dynamic put spread strikes (VIX-regime-conditional OTM selection)."""
    print("\n[Idea_D] V47 + Dynamic Put Spread Strikes (regime-conditional)")
    spy_regime = spy_df["spy_ok"].to_dict()
    spy_close = spy_df["Close"].squeeze()
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

    portfolio_value = INITIAL_CAPITAL
    portfolio_peak = None
    current_drawdown = 0.0
    open_positions = {}
    trades = []
    cooldown_map = {}
    last_vix_spike = None
    last_velocity_crash = None
    put_ref_price = None; put_ref_date = None
    put_notional = 0.0; put_min_spy = 9999.0; put_days_since_renew = 0
    put_lower_otm = PUT_SPREAD_LOWER_OTM; put_upper_otm = PUT_SPREAD_UPPER_OTM

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
                portfolio_peak = portfolio_value; current_drawdown = 0.0
        else:
            if portfolio_value > portfolio_peak:
                portfolio_peak = portfolio_value; current_drawdown = 0.0
            else:
                current_drawdown = (portfolio_value - portfolio_peak) / portfolio_peak

        # Dynamic put spread (passes vix_df for strike selection)
        (portfolio_value, put_ref_price, put_ref_date, put_notional,
         put_min_spy, put_days_since_renew) = _process_put_spread(
            today, spy_df, spy_close, portfolio_value, trades,
            put_ref_price, put_ref_date, put_notional, put_min_spy, put_days_since_renew,
            lower_otm=put_lower_otm, upper_otm=put_upper_otm, vix_df=vix_df)

        # Exits
        to_close = []
        for tkr, pos in open_positions.items():
            if tkr not in signals or today not in signals[tkr].index:
                continue
            row = signals[tkr].loc[today]
            exit_price = float(row["Close"])
            entry_price = pos["entry_price"]
            days_held = (pd.Timestamp(today) - pd.Timestamp(pos["entry_date"])).days
            pos_pct = (exit_price - entry_price) / entry_price
            shares_rem = pos["shares_remaining"]
            early = days_held < MIN_HOLD_BEFORE_EXIT
            time_stop = days_held >= pos["hold_days"]
            profit_hit = (not early) and pos_pct >= pos["profit_target"]

            if (pos["partial_enabled"] and not pos["partial_done"] and
                    not early and pos_pct >= pos["partial_trigger"]):
                partial_sh = shares_rem * pos["partial_frac"]
                comm = calc_commission(partial_sh, exit_price)
                pnl = (exit_price - entry_price) * partial_sh - comm
                trades.append({"ticker": tkr, "entry_date": pos["entry_date"],
                    "exit_date": today, "entry_price": entry_price, "exit_price": exit_price,
                    "shares": partial_sh, "commission": round(comm, 4), "pnl_usd": pnl,
                    "pnl_pct": pos_pct * 100, "days_held": days_held,
                    "exit_reason": "partial_exit", "tier": pos["tier"],
                    "consec_down": pos["consec_down_at_entry"], "portfolio_val": portfolio_value + pnl})
                portfolio_value += pnl
                pos["shares_remaining"] -= partial_sh
                pos["partial_done"] = True
                pos["profit_target"] = pos["profit_target"] * 2
                continue

            full_exit = (time_stop or (not pos["partial_enabled"] and profit_hit) or
                        (pos["partial_enabled"] and pos["partial_done"] and profit_hit))
            if full_exit:
                comm = calc_commission(shares_rem, exit_price)
                pnl = (exit_price - entry_price) * shares_rem - comm - pos["entry_commission"]
                reason = "time_stop" if time_stop else "profit_target"
                trades.append({"ticker": tkr, "entry_date": pos["entry_date"],
                    "exit_date": today, "entry_price": entry_price, "exit_price": exit_price,
                    "shares": shares_rem, "commission": round(comm + pos["entry_commission"], 4),
                    "pnl_usd": pnl, "pnl_pct": pos_pct * 100, "days_held": days_held,
                    "exit_reason": reason, "tier": pos["tier"],
                    "consec_down": pos["consec_down_at_entry"], "portfolio_val": portfolio_value + pnl})
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

        vix_now = get_vix_level(today, vix_df)
        tom_today = today in tom_set
        dow = pd.Timestamp(today).dayofweek
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
            rsi2 = float(row["rsi2"]); atr_pct = float(row["atr_pct"])
            score = rsi2 / atr_pct if atr_pct > 0 else rsi2 * 1000
            candidates.append((score, tkr, int(row["consec_down"]), rsi2))

        candidates.sort(key=lambda x: x[0])
        n_candidates = len(candidates)
        top_n = max(1, int(n_candidates * TOP_SIGNAL_PCT))

        for rank, (score, tkr, consec_val, rsi_val) in enumerate(candidates):
            if len(open_positions) >= MAX_POSITIONS:
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
            if gap_pct < GAP_DOWN_MAX or gap_pct > GAP_UP_MAX:
                continue
            sm = 1.0
            if n_candidates >= MIN_CANDIDATES_FOR_C5 and rank < top_n:
                sm = TOP_SIGNAL_MULTIPLIER
            if tom_today:
                sm *= TOM_MULT
            sm *= DOW_MULT.get(dow, 1.0)
            pos = _make_position(tkr_df, today_idx, today, entry_price, prev_close,
                                 consec_val, rsi_val, portfolio_value, vix_df,
                                 current_drawdown, sm, n_candidates, rank)
            open_positions[tkr] = pos

    print(f"[Idea_D] {len(trades)} total trade records")
    return pd.DataFrame(trades)


# ---------------------------------------------------------------------------
# TEST E: V47 + I3 + Cross-sectional gap-behavior regime sizing
# ---------------------------------------------------------------------------
def run_idea_e(price_data, spy_df, vix_df, sector_data, earnings_map):
    """Idea_E: Gap-behavior sizing — if >60% of candidates gapped down >0.5% over 3 days, 0.6x size."""
    print("\n[Idea_E] V47 + I3 + Cross-sectional gap-behavior sizing")
    spy_regime = spy_df["spy_ok"].to_dict()
    spy_close = spy_df["Close"].squeeze()
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

    portfolio_value = INITIAL_CAPITAL
    portfolio_peak = None
    current_drawdown = 0.0
    open_positions = {}
    trades = []
    cooldown_map = {}
    last_vix_spike = None
    last_velocity_crash = None
    put_ref_price = None; put_ref_date = None
    put_notional = 0.0; put_min_spy = 9999.0; put_days_since_renew = 0
    gap_ratio_history = deque(maxlen=GAP_BEHAVIOR_WINDOW)

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
                portfolio_peak = portfolio_value; current_drawdown = 0.0
        else:
            if portfolio_value > portfolio_peak:
                portfolio_peak = portfolio_value; current_drawdown = 0.0
            else:
                current_drawdown = (portfolio_value - portfolio_peak) / portfolio_peak

        # Put spread
        (portfolio_value, put_ref_price, put_ref_date, put_notional,
         put_min_spy, put_days_since_renew) = _process_put_spread(
            today, spy_df, spy_close, portfolio_value, trades,
            put_ref_price, put_ref_date, put_notional, put_min_spy, put_days_since_renew)

        # Exits
        to_close = []
        for tkr, pos in open_positions.items():
            if tkr not in signals or today not in signals[tkr].index:
                continue
            row = signals[tkr].loc[today]
            exit_price = float(row["Close"])
            entry_price = pos["entry_price"]
            days_held = (pd.Timestamp(today) - pd.Timestamp(pos["entry_date"])).days
            pos_pct = (exit_price - entry_price) / entry_price
            shares_rem = pos["shares_remaining"]
            early = days_held < MIN_HOLD_BEFORE_EXIT
            time_stop = days_held >= pos["hold_days"]
            profit_hit = (not early) and pos_pct >= pos["profit_target"]

            if (pos["partial_enabled"] and not pos["partial_done"] and
                    not early and pos_pct >= pos["partial_trigger"]):
                partial_sh = shares_rem * pos["partial_frac"]
                comm = calc_commission(partial_sh, exit_price)
                pnl = (exit_price - entry_price) * partial_sh - comm
                trades.append({"ticker": tkr, "entry_date": pos["entry_date"],
                    "exit_date": today, "entry_price": entry_price, "exit_price": exit_price,
                    "shares": partial_sh, "commission": round(comm, 4), "pnl_usd": pnl,
                    "pnl_pct": pos_pct * 100, "days_held": days_held,
                    "exit_reason": "partial_exit", "tier": pos["tier"],
                    "consec_down": pos["consec_down_at_entry"], "portfolio_val": portfolio_value + pnl})
                portfolio_value += pnl
                pos["shares_remaining"] -= partial_sh
                pos["partial_done"] = True
                pos["profit_target"] = pos["profit_target"] * 2
                continue

            full_exit = (time_stop or (not pos["partial_enabled"] and profit_hit) or
                        (pos["partial_enabled"] and pos["partial_done"] and profit_hit))
            if full_exit:
                comm = calc_commission(shares_rem, exit_price)
                pnl = (exit_price - entry_price) * shares_rem - comm - pos["entry_commission"]
                reason = "time_stop" if time_stop else "profit_target"
                trades.append({"ticker": tkr, "entry_date": pos["entry_date"],
                    "exit_date": today, "entry_price": entry_price, "exit_price": exit_price,
                    "shares": shares_rem, "commission": round(comm + pos["entry_commission"], 4),
                    "pnl_usd": pnl, "pnl_pct": pos_pct * 100, "days_held": days_held,
                    "exit_reason": reason, "tier": pos["tier"],
                    "consec_down": pos["consec_down_at_entry"], "portfolio_val": portfolio_value + pnl})
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

        vix_now = get_vix_level(today, vix_df)
        tom_today = today in tom_set
        dow = pd.Timestamp(today).dayofweek

        # Build candidate list AND compute gap behavior ratio simultaneously
        candidates = []
        gap_down_count = 0
        total_candidates = 0
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
            rsi2 = float(row["rsi2"]); atr_pct = float(row["atr_pct"])
            score = rsi2 / atr_pct if atr_pct > 0 else rsi2 * 1000
            candidates.append((score, tkr, int(row["consec_down"]), rsi2))
            # Check today's gap behavior for this candidate
            total_candidates += 1
            today_idx_c = tkr_df.index.get_loc(today)
            if today_idx_c >= 1:
                prev_c = float(tkr_df.iloc[today_idx_c - 1]["Close"])
                open_c = float(tkr_df.iloc[today_idx_c]["Open"])
                if prev_c > 0:
                    gap_c = (open_c - prev_c) / prev_c
                    if gap_c < GAP_DOWN_SIGNAL_THRESH:
                        gap_down_count += 1

        # Update gap ratio history
        today_gap_ratio = (gap_down_count / total_candidates) if total_candidates > 0 else 0.0
        gap_ratio_history.append(today_gap_ratio)
        avg_gap_ratio = sum(gap_ratio_history) / len(gap_ratio_history)
        gap_behavior_mult = GAP_BEHAVIOR_MULT if avg_gap_ratio > GAP_BEHAVIOR_THRESHOLD else 1.0

        candidates.sort(key=lambda x: x[0])
        n_candidates = len(candidates)
        top_n = max(1, int(n_candidates * TOP_SIGNAL_PCT))

        for rank, (score, tkr, consec_val, rsi_val) in enumerate(candidates):
            if len(open_positions) >= MAX_POSITIONS:
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
            if gap_pct < GAP_DOWN_MAX or gap_pct > GAP_UP_MAX:
                continue
            sm = 1.0
            if n_candidates >= MIN_CANDIDATES_FOR_C5 and rank < top_n:
                sm = TOP_SIGNAL_MULTIPLIER
            if tom_today:
                sm *= TOM_MULT
            sm *= DOW_MULT.get(dow, 1.0)
            sm *= gap_behavior_mult  # <-- gap-behavior regime gate
            pos = _make_position(tkr_df, today_idx, today, entry_price, prev_close,
                                 consec_val, rsi_val, portfolio_value, vix_df,
                                 current_drawdown, sm, n_candidates, rank)
            open_positions[tkr] = pos

    print(f"[Idea_E] {len(trades)} total trade records")
    return pd.DataFrame(trades)


# ---------------------------------------------------------------------------
# TEST F: V47 + I3 + Day-5 partial time-stop exit
# ---------------------------------------------------------------------------
def run_idea_f(price_data, spy_df, vix_df, sector_data, earnings_map):
    """Idea_F: At day 5, exit the worst-performing 50% of open positions (by current P&L)."""
    print("\n[Idea_F] V47 + I3 + Day-5 partial time-stop exit (worst 50% by P&L)")
    spy_regime = spy_df["spy_ok"].to_dict()
    spy_close = spy_df["Close"].squeeze()
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

    portfolio_value = INITIAL_CAPITAL
    portfolio_peak = None
    current_drawdown = 0.0
    open_positions = {}
    trades = []
    cooldown_map = {}
    last_vix_spike = None
    last_velocity_crash = None
    put_ref_price = None; put_ref_date = None
    put_notional = 0.0; put_min_spy = 9999.0; put_days_since_renew = 0

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
                portfolio_peak = portfolio_value; current_drawdown = 0.0
        else:
            if portfolio_value > portfolio_peak:
                portfolio_peak = portfolio_value; current_drawdown = 0.0
            else:
                current_drawdown = (portfolio_value - portfolio_peak) / portfolio_peak

        # Put spread
        (portfolio_value, put_ref_price, put_ref_date, put_notional,
         put_min_spy, put_days_since_renew) = _process_put_spread(
            today, spy_df, spy_close, portfolio_value, trades,
            put_ref_price, put_ref_date, put_notional, put_min_spy, put_days_since_renew)

        # Exits — including day-5 partial time-stop
        to_close = []
        # Find positions at exactly day 5 for potential early partial exit
        day5_candidates = []
        for tkr, pos in open_positions.items():
            if tkr not in signals or today not in signals[tkr].index:
                continue
            days_held = (pd.Timestamp(today) - pd.Timestamp(pos["entry_date"])).days
            if days_held == DAY5_TRIGGER_DAYS and not pos.get("day5_done", False):
                exit_price = float(signals[tkr].loc[today]["Close"])
                pos_pct = (exit_price - pos["entry_price"]) / pos["entry_price"]
                day5_candidates.append((pos_pct, tkr, exit_price))

        # Sort by P&L, worst first; exit the bottom half
        if len(day5_candidates) >= 2:
            day5_candidates.sort(key=lambda x: x[0])
            n_exit = max(1, int(len(day5_candidates) * DAY5_WORST_FRACTION))
            for pos_pct_val, tkr, exit_price in day5_candidates[:n_exit]:
                pos = open_positions[tkr]
                shares_rem = pos["shares_remaining"]
                days_held = (pd.Timestamp(today) - pd.Timestamp(pos["entry_date"])).days
                comm = calc_commission(shares_rem, exit_price)
                pnl = (exit_price - pos["entry_price"]) * shares_rem - comm - pos["entry_commission"]
                trades.append({"ticker": tkr, "entry_date": pos["entry_date"],
                    "exit_date": today, "entry_price": pos["entry_price"], "exit_price": exit_price,
                    "shares": shares_rem, "commission": round(comm + pos["entry_commission"], 4),
                    "pnl_usd": pnl, "pnl_pct": pos_pct_val * 100, "days_held": days_held,
                    "exit_reason": "day5_timestop_partial", "tier": pos["tier"],
                    "consec_down": pos["consec_down_at_entry"], "portfolio_val": portfolio_value + pnl})
                portfolio_value += pnl
                cooldown_map[tkr] = today
                to_close.append(tkr)
            # Mark survivors as day5-done
            for _, tkr, _ in day5_candidates[n_exit:]:
                open_positions[tkr]["day5_done"] = True

        for tkr in set(to_close):
            if tkr in open_positions:
                del open_positions[tkr]
        to_close = []

        # Normal exit loop
        for tkr, pos in open_positions.items():
            if tkr not in signals or today not in signals[tkr].index:
                continue
            row = signals[tkr].loc[today]
            exit_price = float(row["Close"])
            entry_price = pos["entry_price"]
            days_held = (pd.Timestamp(today) - pd.Timestamp(pos["entry_date"])).days
            pos_pct = (exit_price - entry_price) / entry_price
            shares_rem = pos["shares_remaining"]
            early = days_held < MIN_HOLD_BEFORE_EXIT
            time_stop = days_held >= pos["hold_days"]
            profit_hit = (not early) and pos_pct >= pos["profit_target"]

            if (pos["partial_enabled"] and not pos["partial_done"] and
                    not early and pos_pct >= pos["partial_trigger"]):
                partial_sh = shares_rem * pos["partial_frac"]
                comm = calc_commission(partial_sh, exit_price)
                pnl = (exit_price - entry_price) * partial_sh - comm
                trades.append({"ticker": tkr, "entry_date": pos["entry_date"],
                    "exit_date": today, "entry_price": entry_price, "exit_price": exit_price,
                    "shares": partial_sh, "commission": round(comm, 4), "pnl_usd": pnl,
                    "pnl_pct": pos_pct * 100, "days_held": days_held,
                    "exit_reason": "partial_exit", "tier": pos["tier"],
                    "consec_down": pos["consec_down_at_entry"], "portfolio_val": portfolio_value + pnl})
                portfolio_value += pnl
                pos["shares_remaining"] -= partial_sh
                pos["partial_done"] = True
                pos["profit_target"] = pos["profit_target"] * 2
                continue

            full_exit = (time_stop or (not pos["partial_enabled"] and profit_hit) or
                        (pos["partial_enabled"] and pos["partial_done"] and profit_hit))
            if full_exit:
                comm = calc_commission(shares_rem, exit_price)
                pnl = (exit_price - entry_price) * shares_rem - comm - pos["entry_commission"]
                reason = "time_stop" if time_stop else "profit_target"
                trades.append({"ticker": tkr, "entry_date": pos["entry_date"],
                    "exit_date": today, "entry_price": entry_price, "exit_price": exit_price,
                    "shares": shares_rem, "commission": round(comm + pos["entry_commission"], 4),
                    "pnl_usd": pnl, "pnl_pct": pos_pct * 100, "days_held": days_held,
                    "exit_reason": reason, "tier": pos["tier"],
                    "consec_down": pos["consec_down_at_entry"], "portfolio_val": portfolio_value + pnl})
                portfolio_value += pnl
                if time_stop:
                    cooldown_map[tkr] = today
                to_close.append(tkr)
        for tkr in to_close:
            if tkr in open_positions:
                del open_positions[tkr]

        if not spy_ok or paused or velocity_paused:
            continue
        if len(open_positions) >= MAX_POSITIONS:
            continue

        vix_now = get_vix_level(today, vix_df)
        tom_today = today in tom_set
        dow = pd.Timestamp(today).dayofweek
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
            rsi2 = float(row["rsi2"]); atr_pct = float(row["atr_pct"])
            score = rsi2 / atr_pct if atr_pct > 0 else rsi2 * 1000
            candidates.append((score, tkr, int(row["consec_down"]), rsi2))

        candidates.sort(key=lambda x: x[0])
        n_candidates = len(candidates)
        top_n = max(1, int(n_candidates * TOP_SIGNAL_PCT))

        for rank, (score, tkr, consec_val, rsi_val) in enumerate(candidates):
            if len(open_positions) >= MAX_POSITIONS:
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
            if gap_pct < GAP_DOWN_MAX or gap_pct > GAP_UP_MAX:
                continue
            sm = 1.0
            if n_candidates >= MIN_CANDIDATES_FOR_C5 and rank < top_n:
                sm = TOP_SIGNAL_MULTIPLIER
            if tom_today:
                sm *= TOM_MULT
            sm *= DOW_MULT.get(dow, 1.0)
            pos = _make_position(tkr_df, today_idx, today, entry_price, prev_close,
                                 consec_val, rsi_val, portfolio_value, vix_df,
                                 current_drawdown, sm, n_candidates, rank)
            pos["day5_done"] = False
            open_positions[tkr] = pos

    print(f"[Idea_F] {len(trades)} total trade records")
    return pd.DataFrame(trades)


# ---------------------------------------------------------------------------
# Metrics extraction helper — handles put spread + VIX call spread trades
# ---------------------------------------------------------------------------
def extract_metrics_with_overlays(trades_df: pd.DataFrame, test_name: str) -> dict:
    """
    Compute metrics for a test. MR-only metrics from compute_metrics(),
    then add overlay P&L to final equity. Returns a clean summary dict.
    """
    # Separate MR trades from overlay trades
    overlay_tickers = {"SPY_PUT_SPREAD", "VIX_CALL_SPREAD"}
    mr_trades = trades_df[~trades_df["ticker"].isin(overlay_tickers)].copy()
    put_trades = trades_df[trades_df["ticker"] == "SPY_PUT_SPREAD"].copy()
    vix_call_trades = trades_df[trades_df["ticker"] == "VIX_CALL_SPREAD"].copy()

    if mr_trades.empty:
        return {"test": test_name, "error": "No MR trades"}

    metrics, eq_df = compute_metrics(mr_trades)

    put_net = put_trades["pnl_usd"].sum() if not put_trades.empty else 0.0
    put_premiums = put_trades[put_trades["exit_reason"] == "put_premium"]["pnl_usd"].sum() if not put_trades.empty else 0.0
    put_payouts = put_trades[put_trades["exit_reason"] == "put_payout"]["pnl_usd"].sum() if not put_trades.empty else 0.0
    vix_call_net = vix_call_trades["pnl_usd"].sum() if not vix_call_trades.empty else 0.0
    vix_call_premiums = vix_call_trades[vix_call_trades["exit_reason"] == "vix_call_premium"]["pnl_usd"].sum() if not vix_call_trades.empty else 0.0
    vix_call_payouts = vix_call_trades[vix_call_trades["exit_reason"] == "vix_call_payout"]["pnl_usd"].sum() if not vix_call_trades.empty else 0.0

    total_overlay_net = put_net + vix_call_net
    final_equity_with_overlays = metrics["final_equity"] + total_overlay_net

    return {
        "test": test_name,
        "cagr_pct": metrics["cagr_pct"],
        "final_equity_mr_only": metrics["final_equity"],
        "final_equity_total": round(final_equity_with_overlays, 2),
        "max_drawdown_pct": metrics["max_drawdown_pct"],
        "sharpe_ratio": metrics["sharpe_ratio"],
        "win_rate_pct": metrics["win_rate_pct"],
        "profit_factor": metrics["profit_factor"],
        "total_trades": metrics["total_trades"],
        "put_net_pnl": round(put_net, 2),
        "put_premiums": round(put_premiums, 2),
        "put_payouts": round(put_payouts, 2),
        "vix_call_net_pnl": round(vix_call_net, 2),
        "vix_call_premiums": round(vix_call_premiums, 2),
        "vix_call_payouts": round(vix_call_payouts, 2),
        "overlay_net_total": round(total_overlay_net, 2),
        "year_stats": metrics.get("year_stats", {}),
    }


# ---------------------------------------------------------------------------
# Print comparison table
# ---------------------------------------------------------------------------
def print_comparison_table(results: list[dict]):
    BASELINE_EQUITY = 9_915_308
    BASELINE_DD = -60.89
    BASELINE_CAGR = 22.40

    print("\n" + "="*110)
    print(f" IDEAS V7 — Drawdown Reduction Research | Baseline: V47+I3 = ${BASELINE_EQUITY:,.0f} | CAGR {BASELINE_CAGR}% | MaxDD {BASELINE_DD}%")
    print("="*110)
    print(f"{'Test':<20} {'CAGR%':>8} {'dCAGR':>8} {'Final Equity':>14} {'dEquity':>12} {'MaxDD%':>9} {'dDD':>8} {'Sharpe':>8} {'WR%':>7} {'PF':>6}")
    print("-"*110)

    for r in results:
        if "error" in r:
            print(f"{r['test']:<20}  ERROR: {r['error']}")
            continue
        dcagr = r["cagr_pct"] - BASELINE_CAGR
        dequity = r["final_equity_total"] - BASELINE_EQUITY
        ddd = r["max_drawdown_pct"] - BASELINE_DD
        dcagr_s = f"{dcagr:+.2f}pp"
        dequity_s = f"${dequity:+,.0f}"
        ddd_s = f"{ddd:+.2f}pp"
        is_baseline = "Baseline" in r["test"]
        prefix = "★" if (ddd > 0 and not is_baseline) else " "
        print(f"{prefix}{r['test']:<19} {r['cagr_pct']:>8.2f} {dcagr_s:>8} "
              f"${r['final_equity_total']:>13,.0f} {dequity_s:>12} "
              f"{r['max_drawdown_pct']:>9.2f} {ddd_s:>8} "
              f"{r['sharpe_ratio']:>8.2f} {r['win_rate_pct']:>7.2f} {r['profit_factor']:>6.2f}")

    print("="*110)
    print(" dDD > 0 = MaxDD IMPROVED (less negative). ★ = improves both CAGR and MaxDD vs baseline.")
    print(" All equity figures include MR P&L + all overlay P&L (put spreads, VIX calls, etc.)")
    print(" CAGR is computed on MR trades only (same methodology as V47+I3 reference).")
    print("="*110)

    # Overlay breakdown
    print("\n Overlay P&L Breakdown:")
    print(f"{'Test':<20} {'Put Net':>12} {'Premiums':>12} {'Payouts':>12} {'VIX Call Net':>13} {'VX Prem':>10} {'VX Pay':>10}")
    print("-"*90)
    for r in results:
        if "error" in r:
            continue
        print(f"{r['test']:<20} ${r.get('put_net_pnl',0):>11,.0f} "
              f"${r.get('put_premiums',0):>11,.0f} ${r.get('put_payouts',0):>11,.0f} "
              f"${r.get('vix_call_net_pnl',0):>12,.0f} "
              f"${r.get('vix_call_premiums',0):>9,.0f} ${r.get('vix_call_payouts',0):>9,.0f}")
    print("="*90)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("\n" + "="*70)
    print(" IDEAS V7 — Drawdown Reduction Backtest")
    print(" All tests: V47+I3 baseline + 6 new drawdown-reduction ideas")
    print(" Comparable to: V47+I3 full history = $9,915,308 (22.40% CAGR, -60.89% MaxDD)")
    print("="*70)

    # Download shared data once
    universe = get_universe()
    price_data = download_prices(universe)
    spy_df, vix_df, sector_data = download_reference_data()
    earnings_map = build_earnings_dates(list(price_data.keys()))
    vvix_df = download_vvix()

    all_results = []
    all_trades = {}

    # --- Baseline ---
    print("\n" + "-"*50)
    print("Running: Baseline (V47+I3 reproduction)")
    t = run_baseline(price_data, spy_df, vix_df, sector_data, earnings_map)
    all_trades["Baseline"] = t
    r = extract_metrics_with_overlays(t, "Baseline V47+I3")
    all_results.append(r)
    t.to_csv(OUTPUT_DIR / "baseline_trades.csv", index=False)

    # --- Idea A: VIX call spread ---
    print("\n" + "-"*50)
    print("Running: Idea_A (VIX call spread overlay)")
    t = run_idea_a(price_data, spy_df, vix_df, sector_data, earnings_map)
    all_trades["Idea_A"] = t
    r = extract_metrics_with_overlays(t, "Idea_A VIX calls")
    all_results.append(r)
    t.to_csv(OUTPUT_DIR / "idea_a_trades.csv", index=False)

    # --- Idea B: CDaR leverage scaling ---
    print("\n" + "-"*50)
    print("Running: Idea_B (CDaR-95 leverage scaling)")
    t = run_idea_b(price_data, spy_df, vix_df, sector_data, earnings_map)
    all_trades["Idea_B"] = t
    r = extract_metrics_with_overlays(t, "Idea_B CDaR scale")
    all_results.append(r)
    t.to_csv(OUTPUT_DIR / "idea_b_trades.csv", index=False)

    # --- Idea C: VVIX-gated sizing ---
    print("\n" + "-"*50)
    print("Running: Idea_C (VVIX-gated sizing)")
    t = run_idea_c(price_data, spy_df, vix_df, sector_data, earnings_map, vvix_df)
    all_trades["Idea_C"] = t
    r = extract_metrics_with_overlays(t, "Idea_C VVIX gate")
    all_results.append(r)
    t.to_csv(OUTPUT_DIR / "idea_c_trades.csv", index=False)

    # --- Idea D: Dynamic put spread strikes ---
    print("\n" + "-"*50)
    print("Running: Idea_D (Regime-conditional put spread strikes)")
    t = run_idea_d(price_data, spy_df, vix_df, sector_data, earnings_map)
    all_trades["Idea_D"] = t
    r = extract_metrics_with_overlays(t, "Idea_D Dyn strikes")
    all_results.append(r)
    t.to_csv(OUTPUT_DIR / "idea_d_trades.csv", index=False)

    # --- Idea E: Gap-behavior regime sizing ---
    print("\n" + "-"*50)
    print("Running: Idea_E (Cross-sectional gap-behavior sizing)")
    t = run_idea_e(price_data, spy_df, vix_df, sector_data, earnings_map)
    all_trades["Idea_E"] = t
    r = extract_metrics_with_overlays(t, "Idea_E Gap regime")
    all_results.append(r)
    t.to_csv(OUTPUT_DIR / "idea_e_trades.csv", index=False)

    # --- Idea F: Day-5 partial time-stop ---
    print("\n" + "-"*50)
    print("Running: Idea_F (Day-5 partial time-stop exit)")
    t = run_idea_f(price_data, spy_df, vix_df, sector_data, earnings_map)
    all_trades["Idea_F"] = t
    r = extract_metrics_with_overlays(t, "Idea_F Day5 stop")
    all_results.append(r)
    t.to_csv(OUTPUT_DIR / "idea_f_trades.csv", index=False)

    # Print results
    print_comparison_table(all_results)

    # Save summary JSON
    summary = {
        "run_date": datetime.date.today().isoformat(),
        "baseline_reference": {
            "strategy": "V47+I3 full history through April 2026",
            "final_equity": 9_915_308,
            "cagr_pct": 22.40,
            "max_drawdown_pct": -60.89,
            "sharpe_ratio": 0.74,
        },
        "parameters": {
            "vix_call_spread": {
                "monthly_cost_pct": VIX_CALL_SPREAD_MONTHLY_COST_PCT,
                "lower_strike": VIX_CALL_LOWER_STRIKE,
                "upper_strike": VIX_CALL_UPPER_STRIKE,
                "renew_days": VIX_CALL_RENEW_DAYS,
            },
            "cdar": {
                "window_days": CDAR_WINDOW_DAYS,
                "confidence": CDAR_CONFIDENCE,
                "target": CDAR_TARGET,
                "min_scale": CDAR_MIN_SCALE,
            },
            "vvix": {
                "moderate_thresh": VVIX_MODERATE_THRESH,
                "extreme_thresh": VVIX_EXTREME_THRESH,
                "moderate_mult": VVIX_MODERATE_MULT,
                "extreme_mult": VVIX_EXTREME_MULT,
            },
            "gap_behavior": {
                "window_days": GAP_BEHAVIOR_WINDOW,
                "threshold": GAP_BEHAVIOR_THRESHOLD,
                "size_mult": GAP_BEHAVIOR_MULT,
            },
            "day5_stop": {
                "trigger_days": DAY5_TRIGGER_DAYS,
                "worst_fraction_exited": DAY5_WORST_FRACTION,
            },
        },
        "results": all_results,
    }
    with open(OUTPUT_DIR / "ideas_v7_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\n All results saved to: {OUTPUT_DIR.resolve()}")
    print(f" Key file to share: results_ideas_v7/ideas_v7_summary.json")
    print(f" To paste results back: share the console output above (the comparison table)")


if __name__ == "__main__":
    main()
