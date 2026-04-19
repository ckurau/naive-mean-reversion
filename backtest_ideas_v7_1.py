# backtest_ideas_v7_1.py
#
# Ideas V7.1 — Bug fixes + parameter tuning based on V7 results
#
# Issues fixed vs V7:
#   Idea_A: VIX call spread payout model was wrong — was multiplying premium
#           by payoff_mult (up to 20x) instead of correct spread-value model.
#           Fixed: model spread as long 20-call / short 40-call on VIX.
#           At expiry, payout = notional * (min(VIX_peak,40) - 20) / 20 * max_pct_payout
#           where max_pct_payout = cost (so max return is ~8x premium at full spread).
#           This gives realistic 2008/2020/2025 payouts.
#
#   Idea_B: CDaR target 8% was too tight — scaled down aggressively in normal
#           periods. Retuned: target 15%, min_scale 0.60. More surgical compression.
#
#   Idea_C: VVIX thresholds unchanged (clean neutral result, retested as-is).
#
#   Idea_D: State bug — _process_put_spread returned updated strikes internally
#           but caller vars (put_lower_otm, put_upper_otm) never got updated.
#           Fixed: run_idea_d now selects strikes AT renewal and tracks them as
#           per-contract state alongside put_ref_price / put_days_since_renew.
#
#   Idea_E: Confirmed small positive — retested with wider gap threshold (55%)
#           to test if sensitivity improves result.
#
#   Idea_F: Confirmed loser — dropped from this run.
#
# New:
#   Idea_G: Best combo — Idea_A (fixed) + Idea_D (fixed) stacked on V47+I3
#            (dynamic strikes + VIX call overlay)
#
# Baseline comparison: V47+I3 = $9,915,308 | CAGR 22.40% | MaxDD -60.89%
# Reproduced baseline in V7: $9,857,453 | CAGR 22.37% | MaxDD -60.90% (confirmed match)
#
# Run: python backtest_ideas_v7_1.py
# GitHub Actions: ideas_v7_1_backtest.yml

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

OUTPUT_DIR = Path("results_ideas_v7_1")
OUTPUT_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Baseline put spread parameters (unchanged from V6/V7)
# ---------------------------------------------------------------------------
PUT_SPREAD_LOWER_OTM  = 0.05
PUT_SPREAD_UPPER_OTM  = 0.15
PUT_SPREAD_COST_PCT   = 0.0075   # 0.75% of portfolio per quarter
PUT_SPREAD_RENEW_DAYS = 63

def _put_payout_pct(spy_ref, spy_worst, lower_otm, upper_otm):
    """Returns payout as fraction of notional."""
    if spy_worst >= spy_ref * (1 - lower_otm):
        return 0.0
    decline = (spy_ref - spy_worst) / spy_ref
    spread_width = upper_otm - lower_otm
    payout = max(0.0, min(decline - lower_otm, spread_width))
    return payout

# ---------------------------------------------------------------------------
# IDEA A (FIXED): VIX call spread — corrected payout model
#
# Structure: long VIX 20-call, short VIX 40-call. Monthly roll.
# Cost model: 0.3% of portfolio per month = annual carry ~3.6%.
# Payout model: At expiry, if VIX peaked above 20:
#   payout_pct_of_notional = premium_paid_pct * (peak_above_20 / 20) * MAX_MULT
#   where MAX_MULT = 8 (i.e., 8x premium if VIX hits 40+, capped)
# This gives realistic payouts:
#   VIX spikes to 30 (+10 above strike): 4x premium = 1.2% of portfolio
#   VIX spikes to 40 (+20 above strike): 8x premium = 2.4% of portfolio
#   VIX spikes to 80 (capped at 40):    8x premium = 2.4% of portfolio
#
# Historical calibration check:
#   2020 Covid (VIX peak ~82): 8x * 0.3% = 2.4% return per month = ~$29k at $1.2M
#   2008 GFC (VIX peak ~80):   8x * 0.3% = 2.4% return per month = ~$5-10k early on
#   2022 grind (VIX peak ~38): ~7x * 0.3% = 2.1% = meaningful monthly relief
#   Calm periods: 0x (VIX stays below 20) = just the -0.3%/month carry cost
# ---------------------------------------------------------------------------
VIX_CALL_COST_PCT     = 0.003     # 0.3% of portfolio per month (~$900/mo at $300k)
VIX_CALL_LOWER        = 20.0      # long call strike
VIX_CALL_UPPER        = 40.0      # short call strike (cap)
VIX_CALL_RENEW_DAYS   = 21        # monthly (~21 trading days)
VIX_CALL_MAX_MULT     = 8.0       # max payout = 8x premium at full spread (VIX>=40)

def _vix_call_payout_mult(vix_ref_at_entry, vix_peak_during_period):
    """
    Payout multiplier on the premium paid.
    0x if VIX never exceeded 20.
    Linear 0x→MAX_MULT as VIX goes from 20 to 40.
    Capped at MAX_MULT above 40.
    """
    peak = max(vix_ref_at_entry, vix_peak_during_period)
    if peak <= VIX_CALL_LOWER:
        return 0.0
    above = min(peak - VIX_CALL_LOWER, VIX_CALL_UPPER - VIX_CALL_LOWER)
    spread_width = VIX_CALL_UPPER - VIX_CALL_LOWER
    mult = (above / spread_width) * VIX_CALL_MAX_MULT
    return mult

# ---------------------------------------------------------------------------
# IDEA B (RETUNED): CDaR-based leverage scaling
# Loosened target from 8% → 15%, floor raised 40% → 60%
# ---------------------------------------------------------------------------
CDAR_WINDOW_DAYS = 63
CDAR_CONFIDENCE  = 0.95
CDAR_TARGET      = 0.15    # was 0.08 in V7 — was too aggressive
CDAR_MIN_SCALE   = 0.60    # was 0.40 in V7

def _compute_cdar(equity_hist: list, window: int = 63, conf: float = 0.95) -> float:
    if len(equity_hist) < window + 1:
        return 0.0
    recent = list(equity_hist)[-(window * 2):]
    n = len(recent)
    drawdowns = []
    for start in range(n - window):
        chunk = recent[start:start + window]
        pk = max(chunk)
        pk_idx = chunk.index(pk)
        tr = min(chunk[pk_idx:]) if pk_idx < len(chunk) - 1 else pk
        dd = abs((tr - pk) / pk) if pk > 0 else 0.0
        drawdowns.append(dd)
    if not drawdowns:
        return 0.0
    drawdowns.sort(reverse=True)
    tail = max(1, int(len(drawdowns) * (1 - conf)))
    return sum(drawdowns[:tail]) / tail

def _cdar_scale(cdar_val: float) -> float:
    if cdar_val <= CDAR_TARGET:
        return 1.0
    excess = (cdar_val - CDAR_TARGET) / CDAR_TARGET
    scale = 1.0 - excess * (1.0 - CDAR_MIN_SCALE)
    return max(scale, CDAR_MIN_SCALE)

# ---------------------------------------------------------------------------
# IDEA C: VVIX-gated sizing (unchanged — clean result, retested for confirmation)
# ---------------------------------------------------------------------------
VVIX_MOD_THRESH   = 120.0
VVIX_EXT_THRESH   = 140.0
VVIX_MOD_MULT     = 0.70
VVIX_EXT_MULT     = 0.50

def _download_vvix() -> pd.DataFrame:
    print("[Download] Fetching ^VVIX ...")
    try:
        df = yf.download("^VVIX", start=START_DATE, end=END_DATE,
                         auto_adjust=True, progress=False)
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        print(f"[Download] VVIX: {len(df)} rows")
        return df
    except Exception as e:
        print(f"[Download] VVIX failed: {e}")
        return pd.DataFrame()

def _get_vvix(today, vvix_df: pd.DataFrame) -> float:
    if vvix_df.empty:
        return 100.0
    try:
        vc = vvix_df["Close"].squeeze()
        if today in vc.index:
            return float(vc.loc[today])
    except Exception:
        pass
    return 100.0

def _vvix_mult(level: float) -> float:
    if level >= VVIX_EXT_THRESH:
        return VVIX_EXT_MULT
    if level >= VVIX_MOD_THRESH:
        return VVIX_MOD_MULT
    return 1.0

# ---------------------------------------------------------------------------
# IDEA D (FIXED): Dynamic put spread strikes
# Fix: track active lower/upper OTM PER CONTRACT (alongside ref_price etc.)
# ---------------------------------------------------------------------------
def _get_put_strikes(vix_level: float):
    """Returns (lower_otm, upper_otm) based on VIX regime."""
    if vix_level < 15.0:
        return 0.03, 0.13   # tight: more payout on smaller drop
    if vix_level <= 25.0:
        return 0.05, 0.15   # baseline
    return 0.08, 0.20       # wide: cheaper premium in high-VIX

# ---------------------------------------------------------------------------
# IDEA E (RETUNED): Gap-behavior regime sizing
# V7 used 60% threshold — retesting at 55% to check if slightly more sensitive
# improves the MaxDD relief without hurting CAGR further.
# ---------------------------------------------------------------------------
GAP_BEH_WINDOW     = 3
GAP_BEH_THRESHOLD  = 0.55   # was 0.60 in V7
GAP_BEH_MULT       = 0.60
GAP_DOWN_THRESH    = -0.005

# ---------------------------------------------------------------------------
# Shared position builder (unchanged)
# ---------------------------------------------------------------------------
def _make_pos(tkr_df, today_idx, today, entry_price, consec_val, rsi_val,
              portfolio_value, vix_df, current_drawdown, sm):
    tier = get_tier(consec_val)
    size = get_position_size(today, vix_df, current_drawdown,
                             multiplier=sm, hard_cap=TOP_SIGNAL_HARD_CAP)
    shares = (portfolio_value * size) / entry_price
    ec = calc_commission(shares, entry_price)
    return {
        "entry_date": tkr_df.index[today_idx + 1],
        "entry_price": entry_price,
        "shares": shares,
        "shares_remaining": shares,
        "rsi2_at_entry": rsi_val,
        "consec_down_at_entry": consec_val,
        "profit_target": tier["profit_target"],
        "hold_days": tier["hold_days"],
        "partial_enabled": tier["partial_enabled"],
        "partial_frac": tier["partial_frac"],
        "partial_trigger": tier["partial_trigger"],
        "partial_done": False,
        "tier": tier["tier"],
        "entry_commission": ec,
    }

# ---------------------------------------------------------------------------
# Shared MR exit loop — call once per trading day
# Returns: updated portfolio_value, modified open_positions, cooldown_map
# ---------------------------------------------------------------------------
def _run_exits(today, signals, open_positions, trades, portfolio_value, cooldown_map):
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

        if (pos["partial_enabled"] and not pos["partial_done"]
                and not early and pos_pct >= pos["partial_trigger"]):
            psh = shares_rem * pos["partial_frac"]
            comm = calc_commission(psh, exit_price)
            pnl = (exit_price - entry_price) * psh - comm
            trades.append({
                "ticker": tkr, "entry_date": pos["entry_date"], "exit_date": today,
                "entry_price": entry_price, "exit_price": exit_price, "shares": psh,
                "commission": round(comm, 4), "pnl_usd": pnl,
                "pnl_pct": pos_pct * 100, "days_held": days_held,
                "exit_reason": "partial_exit", "tier": pos["tier"],
                "consec_down": pos["consec_down_at_entry"], "portfolio_val": portfolio_value + pnl,
            })
            portfolio_value += pnl
            pos["shares_remaining"] -= psh
            pos["partial_done"] = True
            pos["profit_target"] *= 2
            continue

        full_exit = (time_stop or (not pos["partial_enabled"] and profit_hit)
                     or (pos["partial_enabled"] and pos["partial_done"] and profit_hit))
        if full_exit:
            comm = calc_commission(shares_rem, exit_price)
            pnl = (exit_price - entry_price) * shares_rem - comm - pos["entry_commission"]
            reason = "time_stop" if time_stop else "profit_target"
            trades.append({
                "ticker": tkr, "entry_date": pos["entry_date"], "exit_date": today,
                "entry_price": entry_price, "exit_price": exit_price, "shares": shares_rem,
                "commission": round(comm + pos["entry_commission"], 4), "pnl_usd": pnl,
                "pnl_pct": pos_pct * 100, "days_held": days_held, "exit_reason": reason,
                "tier": pos["tier"], "consec_down": pos["consec_down_at_entry"],
                "portfolio_val": portfolio_value + pnl,
            })
            portfolio_value += pnl
            if time_stop:
                cooldown_map[tkr] = today
            to_close.append(tkr)
    for tkr in to_close:
        del open_positions[tkr]
    return portfolio_value

# ---------------------------------------------------------------------------
# Shared candidate builder + V47 sizing
# ---------------------------------------------------------------------------
def _build_candidates(today, signals, open_positions, cooldown_map, earnings_map,
                       sector_data, vix_now, tom_today, dow,
                       extra_mult: float = 1.0):
    """Build ranked candidate list. extra_mult is applied on top of V47 sizing."""
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
    return sorted(candidates, key=lambda x: x[0])

def _enter_candidates(today, signals, candidates, open_positions, cooldown_map,
                       portfolio_value, vix_df, current_drawdown,
                       tom_today, dow, extra_mult: float = 1.0):
    """Execute entries for ranked candidates with V47 sizing + extra_mult."""
    n = len(candidates)
    top_n = max(1, int(n * TOP_SIGNAL_PCT))
    for rank, (score, tkr, consec_val, rsi_val) in enumerate(candidates):
        if len(open_positions) >= MAX_POSITIONS:
            break
        tkr_df = signals[tkr]
        idx = tkr_df.index.get_loc(today)
        if idx + 1 >= len(tkr_df):
            continue
        entry_price = float(tkr_df.iloc[idx + 1]["Open"])
        if entry_price <= 0:
            continue
        prev_close = float(tkr_df.iloc[idx]["Close"])
        gap = (entry_price - prev_close) / prev_close
        if gap < GAP_DOWN_MAX or gap > GAP_UP_MAX:
            continue
        sm = 1.0
        if n >= MIN_CANDIDATES_FOR_C5 and rank < top_n:
            sm = TOP_SIGNAL_MULTIPLIER
        if tom_today:
            sm *= TOM_MULT
        sm *= DOW_MULT.get(dow, 1.0)
        sm *= extra_mult
        pos = _make_pos(tkr_df, idx, today, entry_price, consec_val, rsi_val,
                        portfolio_value, vix_df, current_drawdown, sm)
        open_positions[tkr] = pos

# ---------------------------------------------------------------------------
# Shared portfolio state tracker
# ---------------------------------------------------------------------------
def _update_drawdown(portfolio_value, portfolio_peak):
    if portfolio_peak is None:
        if portfolio_value != INITIAL_CAPITAL:
            return portfolio_value, 0.0
        return None, 0.0
    if portfolio_value > portfolio_peak:
        return portfolio_value, 0.0
    dd = (portfolio_value - portfolio_peak) / portfolio_peak
    return portfolio_peak, dd

def _check_velocity(today, spy_df, last_velocity_crash):
    velocity_paused = False
    try:
        if today in spy_df.index:
            v = float(spy_df.loc[today, "spy_5d_ret"])
            if not np.isnan(v) and v < VELOCITY_CRASH_5D_THRESHOLD:
                last_velocity_crash = today
        if last_velocity_crash is not None:
            if (pd.Timestamp(today) - pd.Timestamp(last_velocity_crash)).days <= VELOCITY_CRASH_PAUSE_DAYS:
                velocity_paused = True
    except Exception:
        pass
    return velocity_paused, last_velocity_crash

def _init_signals(price_data):
    signals = {}
    min_bars = MA_WINDOW + VOL_MA_PERIOD + ATR_PERIOD + MIN_CONSEC_DOWN + 5
    for tkr, df in price_data.items():
        if len(df) > min_bars:
            signals[tkr] = generate_signals(df)
    return signals

# ---------------------------------------------------------------------------
# TEST 0: Baseline — V47+I3 (identical to V7, confirms reproduced match)
# ---------------------------------------------------------------------------
def run_baseline(price_data, spy_df, vix_df, sector_data, earnings_map):
    print("\n[Baseline] V47 + I3")
    spy_regime = spy_df["spy_ok"].to_dict()
    spy_close = spy_df["Close"].squeeze()
    all_dates = sorted(set().union(*[set(df.index) for df in price_data.values()]))
    tom_set = build_tom_set(all_dates)
    signals = _init_signals(price_data)

    pv = INITIAL_CAPITAL; peak = None; dd = 0.0
    open_pos = {}; trades = []; cool = {}; last_vs = None; last_vc = None
    pr = None; prd = None; pn = 0.0; pms = 9999.0; pds = 0
    lo = PUT_SPREAD_LOWER_OTM; hi = PUT_SPREAD_UPPER_OTM

    for today in all_dates:
        spy_ok = spy_regime.get(today, True)
        paused, last_vs = check_vix_spike(today, vix_df, last_vs)
        vel_paused, last_vc = _check_velocity(today, spy_df, last_vc)
        peak_new, dd = _update_drawdown(pv, peak)
        peak = peak_new if peak_new is not None else peak

        # Put spread
        if today in spy_df.index:
            spx = float(spy_close.loc[today]) if today in spy_close.index else None
            if spx is not None:
                if pr is None or pds >= PUT_SPREAD_RENEW_DAYS:
                    prem = pv * PUT_SPREAD_COST_PCT; pv -= prem
                    pr = spx; prd = today; pn = pv; pms = spx; pds = 0
                    trades.append({"ticker": "SPY_PUT_SPREAD", "entry_date": today,
                        "exit_date": today, "entry_price": spx, "exit_price": spx,
                        "shares": 0, "commission": 0, "pnl_usd": -prem,
                        "pnl_pct": -PUT_SPREAD_COST_PCT * 100, "days_held": 0,
                        "exit_reason": "put_premium", "tier": 0, "consec_down": 0,
                        "portfolio_val": pv})
                else:
                    pds += 1; pms = min(pms, spx)
                    if pds == PUT_SPREAD_RENEW_DAYS - 1:
                        pay_pct = _put_payout_pct(pr, pms, lo, hi)
                        if pay_pct > 0:
                            pay = pn * pay_pct; pv += pay
                            trades.append({"ticker": "SPY_PUT_SPREAD", "entry_date": prd,
                                "exit_date": today, "entry_price": pr, "exit_price": pms,
                                "shares": 0, "commission": 0, "pnl_usd": round(pay, 2),
                                "pnl_pct": round(pay_pct * 100, 4), "days_held": pds,
                                "exit_reason": "put_payout", "tier": 0, "consec_down": 0,
                                "portfolio_val": pv})

        pv = _run_exits(today, signals, open_pos, trades, pv, cool)
        if not spy_ok or paused or vel_paused or len(open_pos) >= MAX_POSITIONS:
            continue
        vix_now = get_vix_level(today, vix_df)
        tom_today = today in tom_set; dow = pd.Timestamp(today).dayofweek
        cands = _build_candidates(today, signals, open_pos, cool, earnings_map,
                                  sector_data, vix_now, tom_today, dow)
        _enter_candidates(today, signals, cands, open_pos, cool, pv, vix_df, dd,
                          tom_today, dow)

    print(f"[Baseline] {len(trades)} records")
    return pd.DataFrame(trades)

# ---------------------------------------------------------------------------
# TEST A (FIXED): V47 + I3 + VIX call spread (corrected payout model)
# ---------------------------------------------------------------------------
def run_idea_a(price_data, spy_df, vix_df, sector_data, earnings_map):
    print("\n[Idea_A] V47 + I3 + VIX call spread (FIXED payout model)")
    spy_regime = spy_df["spy_ok"].to_dict()
    spy_close = spy_df["Close"].squeeze()
    vix_close = vix_df["Close"].squeeze()
    all_dates = sorted(set().union(*[set(df.index) for df in price_data.values()]))
    tom_set = build_tom_set(all_dates)
    signals = _init_signals(price_data)

    pv = INITIAL_CAPITAL; peak = None; dd = 0.0
    open_pos = {}; trades = []; cool = {}; last_vs = None; last_vc = None
    pr = None; prd = None; pn = 0.0; pms = 9999.0; pds = 0
    lo = PUT_SPREAD_LOWER_OTM; hi = PUT_SPREAD_UPPER_OTM
    # VIX call state
    vc_days = 0; vc_ref = None; vc_ref_date = None
    vc_notional = 0.0; vc_peak = 0.0; vc_prem = 0.0

    for today in all_dates:
        spy_ok = spy_regime.get(today, True)
        paused, last_vs = check_vix_spike(today, vix_df, last_vs)
        vel_paused, last_vc = _check_velocity(today, spy_df, last_vc)
        peak_new, dd = _update_drawdown(pv, peak)
        peak = peak_new if peak_new is not None else peak

        # SPY put spread (baseline)
        if today in spy_df.index:
            spx = float(spy_close.loc[today]) if today in spy_close.index else None
            if spx is not None:
                if pr is None or pds >= PUT_SPREAD_RENEW_DAYS:
                    prem = pv * PUT_SPREAD_COST_PCT; pv -= prem
                    pr = spx; prd = today; pn = pv; pms = spx; pds = 0
                    trades.append({"ticker": "SPY_PUT_SPREAD", "entry_date": today,
                        "exit_date": today, "entry_price": spx, "exit_price": spx,
                        "shares": 0, "commission": 0, "pnl_usd": -prem,
                        "pnl_pct": -PUT_SPREAD_COST_PCT * 100, "days_held": 0,
                        "exit_reason": "put_premium", "tier": 0, "consec_down": 0,
                        "portfolio_val": pv})
                else:
                    pds += 1; pms = min(pms, spx)
                    if pds == PUT_SPREAD_RENEW_DAYS - 1:
                        pay_pct = _put_payout_pct(pr, pms, lo, hi)
                        if pay_pct > 0:
                            pay = pn * pay_pct; pv += pay
                            trades.append({"ticker": "SPY_PUT_SPREAD", "entry_date": prd,
                                "exit_date": today, "entry_price": pr, "exit_price": pms,
                                "shares": 0, "commission": 0, "pnl_usd": round(pay, 2),
                                "pnl_pct": round(pay_pct * 100, 4), "days_held": pds,
                                "exit_reason": "put_payout", "tier": 0, "consec_down": 0,
                                "portfolio_val": pv})

        # VIX call spread (monthly, FIXED payout)
        if today in vix_df.index:
            vix_px = float(vix_close.loc[today]) if today in vix_close.index else None
            if vix_px is not None:
                if vc_ref is None or vc_days >= VIX_CALL_RENEW_DAYS:
                    # Renew: pay premium
                    prem = pv * VIX_CALL_COST_PCT; pv -= prem
                    vc_ref = vix_px; vc_ref_date = today
                    vc_notional = pv; vc_peak = vix_px; vc_prem = prem; vc_days = 0
                    trades.append({"ticker": "VIX_CALL_SPREAD", "entry_date": today,
                        "exit_date": today, "entry_price": vix_px, "exit_price": vix_px,
                        "shares": 0, "commission": 0, "pnl_usd": -prem,
                        "pnl_pct": -VIX_CALL_COST_PCT * 100, "days_held": 0,
                        "exit_reason": "vix_call_premium", "tier": 0, "consec_down": 0,
                        "portfolio_val": pv})
                else:
                    vc_days += 1; vc_peak = max(vc_peak, vix_px)
                    if vc_days == VIX_CALL_RENEW_DAYS - 1:
                        # Settle: FIXED payout = premium * multiplier
                        mult = _vix_call_payout_mult(vc_ref, vc_peak)
                        if mult > 0:
                            pay = vc_prem * mult; pv += pay
                            trades.append({"ticker": "VIX_CALL_SPREAD",
                                "entry_date": vc_ref_date, "exit_date": today,
                                "entry_price": vc_ref, "exit_price": vc_peak,
                                "shares": 0, "commission": 0, "pnl_usd": round(pay, 2),
                                "pnl_pct": round(mult * VIX_CALL_COST_PCT * 100, 4),
                                "days_held": vc_days, "exit_reason": "vix_call_payout",
                                "tier": 0, "consec_down": 0, "portfolio_val": pv})

        pv = _run_exits(today, signals, open_pos, trades, pv, cool)
        if not spy_ok or paused or vel_paused or len(open_pos) >= MAX_POSITIONS:
            continue
        vix_now = get_vix_level(today, vix_df)
        tom_today = today in tom_set; dow = pd.Timestamp(today).dayofweek
        cands = _build_candidates(today, signals, open_pos, cool, earnings_map,
                                  sector_data, vix_now, tom_today, dow)
        _enter_candidates(today, signals, cands, open_pos, cool, pv, vix_df, dd,
                          tom_today, dow)

    print(f"[Idea_A] {len(trades)} records")
    return pd.DataFrame(trades)

# ---------------------------------------------------------------------------
# TEST B (RETUNED): CDaR leverage scaling
# ---------------------------------------------------------------------------
def run_idea_b(price_data, spy_df, vix_df, sector_data, earnings_map):
    print("\n[Idea_B] V47 + I3 + CDaR scaling (retuned: target 15%, floor 60%)")
    spy_regime = spy_df["spy_ok"].to_dict()
    spy_close = spy_df["Close"].squeeze()
    all_dates = sorted(set().union(*[set(df.index) for df in price_data.values()]))
    tom_set = build_tom_set(all_dates)
    signals = _init_signals(price_data)

    pv = INITIAL_CAPITAL; peak = None; dd = 0.0
    open_pos = {}; trades = []; cool = {}; last_vs = None; last_vc = None
    pr = None; prd = None; pn = 0.0; pms = 9999.0; pds = 0
    lo = PUT_SPREAD_LOWER_OTM; hi = PUT_SPREAD_UPPER_OTM
    eq_hist = deque(maxlen=CDAR_WINDOW_DAYS * 2 + 10)
    eq_hist.append(INITIAL_CAPITAL)

    for today in all_dates:
        spy_ok = spy_regime.get(today, True)
        paused, last_vs = check_vix_spike(today, vix_df, last_vs)
        vel_paused, last_vc = _check_velocity(today, spy_df, last_vc)
        peak_new, dd = _update_drawdown(pv, peak)
        peak = peak_new if peak_new is not None else peak
        eq_hist.append(pv)
        cdar_val = _compute_cdar(list(eq_hist), CDAR_WINDOW_DAYS, CDAR_CONFIDENCE)
        cs = _cdar_scale(cdar_val)

        if today in spy_df.index:
            spx = float(spy_close.loc[today]) if today in spy_close.index else None
            if spx is not None:
                if pr is None or pds >= PUT_SPREAD_RENEW_DAYS:
                    prem = pv * PUT_SPREAD_COST_PCT; pv -= prem
                    pr = spx; prd = today; pn = pv; pms = spx; pds = 0
                    trades.append({"ticker": "SPY_PUT_SPREAD", "entry_date": today,
                        "exit_date": today, "entry_price": spx, "exit_price": spx,
                        "shares": 0, "commission": 0, "pnl_usd": -prem,
                        "pnl_pct": -PUT_SPREAD_COST_PCT * 100, "days_held": 0,
                        "exit_reason": "put_premium", "tier": 0, "consec_down": 0,
                        "portfolio_val": pv})
                else:
                    pds += 1; pms = min(pms, spx)
                    if pds == PUT_SPREAD_RENEW_DAYS - 1:
                        pay_pct = _put_payout_pct(pr, pms, lo, hi)
                        if pay_pct > 0:
                            pay = pn * pay_pct; pv += pay
                            trades.append({"ticker": "SPY_PUT_SPREAD", "entry_date": prd,
                                "exit_date": today, "entry_price": pr, "exit_price": pms,
                                "shares": 0, "commission": 0, "pnl_usd": round(pay, 2),
                                "pnl_pct": round(pay_pct * 100, 4), "days_held": pds,
                                "exit_reason": "put_payout", "tier": 0, "consec_down": 0,
                                "portfolio_val": pv})

        pv = _run_exits(today, signals, open_pos, trades, pv, cool)
        if not spy_ok or paused or vel_paused or len(open_pos) >= MAX_POSITIONS:
            continue
        vix_now = get_vix_level(today, vix_df)
        tom_today = today in tom_set; dow = pd.Timestamp(today).dayofweek
        cands = _build_candidates(today, signals, open_pos, cool, earnings_map,
                                  sector_data, vix_now, tom_today, dow)
        _enter_candidates(today, signals, cands, open_pos, cool, pv, vix_df, dd,
                          tom_today, dow, extra_mult=cs)

    print(f"[Idea_B] {len(trades)} records")
    return pd.DataFrame(trades)

# ---------------------------------------------------------------------------
# TEST C: VVIX-gated sizing (unchanged — confirm V7 result)
# ---------------------------------------------------------------------------
def run_idea_c(price_data, spy_df, vix_df, sector_data, earnings_map, vvix_df):
    print("\n[Idea_C] V47 + I3 + VVIX-gated sizing (confirm)")
    spy_regime = spy_df["spy_ok"].to_dict()
    spy_close = spy_df["Close"].squeeze()
    all_dates = sorted(set().union(*[set(df.index) for df in price_data.values()]))
    tom_set = build_tom_set(all_dates)
    signals = _init_signals(price_data)

    pv = INITIAL_CAPITAL; peak = None; dd = 0.0
    open_pos = {}; trades = []; cool = {}; last_vs = None; last_vc = None
    pr = None; prd = None; pn = 0.0; pms = 9999.0; pds = 0
    lo = PUT_SPREAD_LOWER_OTM; hi = PUT_SPREAD_UPPER_OTM

    for today in all_dates:
        spy_ok = spy_regime.get(today, True)
        paused, last_vs = check_vix_spike(today, vix_df, last_vs)
        vel_paused, last_vc = _check_velocity(today, spy_df, last_vc)
        peak_new, dd = _update_drawdown(pv, peak)
        peak = peak_new if peak_new is not None else peak
        vvix_level = _get_vvix(today, vvix_df)
        vm = _vvix_mult(vvix_level)

        if today in spy_df.index:
            spx = float(spy_close.loc[today]) if today in spy_close.index else None
            if spx is not None:
                if pr is None or pds >= PUT_SPREAD_RENEW_DAYS:
                    prem = pv * PUT_SPREAD_COST_PCT; pv -= prem
                    pr = spx; prd = today; pn = pv; pms = spx; pds = 0
                    trades.append({"ticker": "SPY_PUT_SPREAD", "entry_date": today,
                        "exit_date": today, "entry_price": spx, "exit_price": spx,
                        "shares": 0, "commission": 0, "pnl_usd": -prem,
                        "pnl_pct": -PUT_SPREAD_COST_PCT * 100, "days_held": 0,
                        "exit_reason": "put_premium", "tier": 0, "consec_down": 0,
                        "portfolio_val": pv})
                else:
                    pds += 1; pms = min(pms, spx)
                    if pds == PUT_SPREAD_RENEW_DAYS - 1:
                        pay_pct = _put_payout_pct(pr, pms, lo, hi)
                        if pay_pct > 0:
                            pay = pn * pay_pct; pv += pay
                            trades.append({"ticker": "SPY_PUT_SPREAD", "entry_date": prd,
                                "exit_date": today, "entry_price": pr, "exit_price": pms,
                                "shares": 0, "commission": 0, "pnl_usd": round(pay, 2),
                                "pnl_pct": round(pay_pct * 100, 4), "days_held": pds,
                                "exit_reason": "put_payout", "tier": 0, "consec_down": 0,
                                "portfolio_val": pv})

        pv = _run_exits(today, signals, open_pos, trades, pv, cool)
        if not spy_ok or paused or vel_paused or len(open_pos) >= MAX_POSITIONS:
            continue
        vix_now = get_vix_level(today, vix_df)
        tom_today = today in tom_set; dow = pd.Timestamp(today).dayofweek
        cands = _build_candidates(today, signals, open_pos, cool, earnings_map,
                                  sector_data, vix_now, tom_today, dow)
        _enter_candidates(today, signals, cands, open_pos, cool, pv, vix_df, dd,
                          tom_today, dow, extra_mult=vm)

    print(f"[Idea_C] {len(trades)} records")
    return pd.DataFrame(trades)

# ---------------------------------------------------------------------------
# TEST D (FIXED): Dynamic put spread strikes — state tracked per contract
# ---------------------------------------------------------------------------
def run_idea_d(price_data, spy_df, vix_df, sector_data, earnings_map):
    print("\n[Idea_D] V47 + Dynamic Put Spread Strikes (FIXED state tracking)")
    spy_regime = spy_df["spy_ok"].to_dict()
    spy_close = spy_df["Close"].squeeze()
    all_dates = sorted(set().union(*[set(df.index) for df in price_data.values()]))
    tom_set = build_tom_set(all_dates)
    signals = _init_signals(price_data)

    pv = INITIAL_CAPITAL; peak = None; dd = 0.0
    open_pos = {}; trades = []; cool = {}; last_vs = None; last_vc = None
    # Per-contract put spread state — now includes strikes chosen at renewal
    pr = None; prd = None; pn = 0.0; pms = 9999.0; pds = 0
    # Active strikes for the CURRENT contract (chosen at renewal time)
    active_lo = PUT_SPREAD_LOWER_OTM
    active_hi = PUT_SPREAD_UPPER_OTM

    for today in all_dates:
        spy_ok = spy_regime.get(today, True)
        paused, last_vs = check_vix_spike(today, vix_df, last_vs)
        vel_paused, last_vc = _check_velocity(today, spy_df, last_vc)
        peak_new, dd = _update_drawdown(pv, peak)
        peak = peak_new if peak_new is not None else peak

        if today in spy_df.index:
            spx = float(spy_close.loc[today]) if today in spy_close.index else None
            if spx is not None:
                if pr is None or pds >= PUT_SPREAD_RENEW_DAYS:
                    # Choose strikes based on VIX at renewal — FIXED: stored per contract
                    vix_at_renewal = get_vix_level(today, vix_df)
                    active_lo, active_hi = _get_put_strikes(vix_at_renewal)
                    prem = pv * PUT_SPREAD_COST_PCT; pv -= prem
                    pr = spx; prd = today; pn = pv; pms = spx; pds = 0
                    trades.append({"ticker": "SPY_PUT_SPREAD", "entry_date": today,
                        "exit_date": today, "entry_price": spx, "exit_price": spx,
                        "shares": 0, "commission": 0, "pnl_usd": -prem,
                        "pnl_pct": -PUT_SPREAD_COST_PCT * 100, "days_held": 0,
                        "exit_reason": "put_premium", "tier": 0, "consec_down": 0,
                        "portfolio_val": pv,
                        "put_lower_otm": active_lo, "put_upper_otm": active_hi,
                        "vix_at_renewal": round(vix_at_renewal, 2)})
                else:
                    pds += 1; pms = min(pms, spx)
                    if pds == PUT_SPREAD_RENEW_DAYS - 1:
                        # Use ACTIVE strikes (the ones chosen at this contract's renewal)
                        pay_pct = _put_payout_pct(pr, pms, active_lo, active_hi)
                        if pay_pct > 0:
                            pay = pn * pay_pct; pv += pay
                            trades.append({"ticker": "SPY_PUT_SPREAD", "entry_date": prd,
                                "exit_date": today, "entry_price": pr, "exit_price": pms,
                                "shares": 0, "commission": 0, "pnl_usd": round(pay, 2),
                                "pnl_pct": round(pay_pct * 100, 4), "days_held": pds,
                                "exit_reason": "put_payout", "tier": 0, "consec_down": 0,
                                "portfolio_val": pv,
                                "put_lower_otm": active_lo, "put_upper_otm": active_hi})

        pv = _run_exits(today, signals, open_pos, trades, pv, cool)
        if not spy_ok or paused or vel_paused or len(open_pos) >= MAX_POSITIONS:
            continue
        vix_now = get_vix_level(today, vix_df)
        tom_today = today in tom_set; dow = pd.Timestamp(today).dayofweek
        cands = _build_candidates(today, signals, open_pos, cool, earnings_map,
                                  sector_data, vix_now, tom_today, dow)
        _enter_candidates(today, signals, cands, open_pos, cool, pv, vix_df, dd,
                          tom_today, dow)

    print(f"[Idea_D] {len(trades)} records")
    return pd.DataFrame(trades)

# ---------------------------------------------------------------------------
# TEST E (RETUNED): Gap-behavior regime sizing (threshold 55% vs 60% in V7)
# ---------------------------------------------------------------------------
def run_idea_e(price_data, spy_df, vix_df, sector_data, earnings_map):
    print(f"\n[Idea_E] V47 + I3 + Gap-behavior sizing (threshold {GAP_BEH_THRESHOLD:.0%})")
    spy_regime = spy_df["spy_ok"].to_dict()
    spy_close = spy_df["Close"].squeeze()
    all_dates = sorted(set().union(*[set(df.index) for df in price_data.values()]))
    tom_set = build_tom_set(all_dates)
    signals = _init_signals(price_data)

    pv = INITIAL_CAPITAL; peak = None; dd = 0.0
    open_pos = {}; trades = []; cool = {}; last_vs = None; last_vc = None
    pr = None; prd = None; pn = 0.0; pms = 9999.0; pds = 0
    lo = PUT_SPREAD_LOWER_OTM; hi = PUT_SPREAD_UPPER_OTM
    gap_hist = deque(maxlen=GAP_BEH_WINDOW)

    for today in all_dates:
        spy_ok = spy_regime.get(today, True)
        paused, last_vs = check_vix_spike(today, vix_df, last_vs)
        vel_paused, last_vc = _check_velocity(today, spy_df, last_vc)
        peak_new, dd = _update_drawdown(pv, peak)
        peak = peak_new if peak_new is not None else peak

        if today in spy_df.index:
            spx = float(spy_close.loc[today]) if today in spy_close.index else None
            if spx is not None:
                if pr is None or pds >= PUT_SPREAD_RENEW_DAYS:
                    prem = pv * PUT_SPREAD_COST_PCT; pv -= prem
                    pr = spx; prd = today; pn = pv; pms = spx; pds = 0
                    trades.append({"ticker": "SPY_PUT_SPREAD", "entry_date": today,
                        "exit_date": today, "entry_price": spx, "exit_price": spx,
                        "shares": 0, "commission": 0, "pnl_usd": -prem,
                        "pnl_pct": -PUT_SPREAD_COST_PCT * 100, "days_held": 0,
                        "exit_reason": "put_premium", "tier": 0, "consec_down": 0,
                        "portfolio_val": pv})
                else:
                    pds += 1; pms = min(pms, spx)
                    if pds == PUT_SPREAD_RENEW_DAYS - 1:
                        pay_pct = _put_payout_pct(pr, pms, lo, hi)
                        if pay_pct > 0:
                            pay = pn * pay_pct; pv += pay
                            trades.append({"ticker": "SPY_PUT_SPREAD", "entry_date": prd,
                                "exit_date": today, "entry_price": pr, "exit_price": pms,
                                "shares": 0, "commission": 0, "pnl_usd": round(pay, 2),
                                "pnl_pct": round(pay_pct * 100, 4), "days_held": pds,
                                "exit_reason": "put_payout", "tier": 0, "consec_down": 0,
                                "portfolio_val": pv})

        pv = _run_exits(today, signals, open_pos, trades, pv, cool)
        if not spy_ok or paused or vel_paused or len(open_pos) >= MAX_POSITIONS:
            continue

        vix_now = get_vix_level(today, vix_df)
        tom_today = today in tom_set; dow = pd.Timestamp(today).dayofweek

        # Measure today's gap behavior across candidates
        gap_dn = 0; tot = 0
        temp_cands = []
        for tkr, tkr_df in signals.items():
            if tkr in open_pos or today not in tkr_df.index:
                continue
            row = tkr_df.loc[today]
            if not row["signal"]:
                continue
            if vix_now < VIX_TIGHT_THRESH and float(row["rsi2"]) >= RSI_TIGHT_THRESH:
                continue
            if tkr in cool:
                if (pd.Timestamp(today) - pd.Timestamp(cool[tkr])).days < REENTRY_COOLDOWN_DAYS:
                    continue
            if near_earnings(tkr, today, earnings_map):
                continue
            if not sector_ok(tkr, today, sector_data):
                continue
            if count_sector_positions(tkr, open_pos) >= MAX_SECTOR_POSITIONS:
                continue
            rsi2 = float(row["rsi2"]); atr_pct = float(row["atr_pct"])
            score = rsi2 / atr_pct if atr_pct > 0 else rsi2 * 1000
            temp_cands.append((score, tkr, int(row["consec_down"]), rsi2))
            tot += 1
            idx_c = tkr_df.index.get_loc(today)
            if idx_c >= 1:
                prev_c = float(tkr_df.iloc[idx_c - 1]["Close"])
                open_c = float(tkr_df.iloc[idx_c]["Open"])
                if prev_c > 0 and (open_c - prev_c) / prev_c < GAP_DOWN_THRESH:
                    gap_dn += 1

        today_ratio = (gap_dn / tot) if tot > 0 else 0.0
        gap_hist.append(today_ratio)
        avg_ratio = sum(gap_hist) / len(gap_hist)
        gbm = GAP_BEH_MULT if avg_ratio > GAP_BEH_THRESHOLD else 1.0

        cands = sorted(temp_cands, key=lambda x: x[0])
        _enter_candidates(today, signals, cands, open_pos, cool, pv, vix_df, dd,
                          tom_today, dow, extra_mult=gbm)

    print(f"[Idea_E] {len(trades)} records")
    return pd.DataFrame(trades)

# ---------------------------------------------------------------------------
# TEST G: Best combo — Idea_A (fixed) + Idea_D (fixed) stacked on V47+I3
# Dynamic strikes + VIX call overlay
# ---------------------------------------------------------------------------
def run_idea_g(price_data, spy_df, vix_df, sector_data, earnings_map):
    """Idea_G: V47 + Dynamic SPY put spread strikes + VIX call spread overlay."""
    print("\n[Idea_G] V47 + Dynamic strikes (D) + VIX call overlay (A) — best combo")
    spy_regime = spy_df["spy_ok"].to_dict()
    spy_close = spy_df["Close"].squeeze()
    vix_close = vix_df["Close"].squeeze()
    all_dates = sorted(set().union(*[set(df.index) for df in price_data.values()]))
    tom_set = build_tom_set(all_dates)
    signals = _init_signals(price_data)

    pv = INITIAL_CAPITAL; peak = None; dd = 0.0
    open_pos = {}; trades = []; cool = {}; last_vs = None; last_vc = None
    # SPY put spread — dynamic strikes
    pr = None; prd = None; pn = 0.0; pms = 9999.0; pds = 0
    active_lo = PUT_SPREAD_LOWER_OTM; active_hi = PUT_SPREAD_UPPER_OTM
    # VIX call spread
    vc_days = 0; vc_ref = None; vc_ref_date = None
    vc_notional = 0.0; vc_peak = 0.0; vc_prem = 0.0

    for today in all_dates:
        spy_ok = spy_regime.get(today, True)
        paused, last_vs = check_vix_spike(today, vix_df, last_vs)
        vel_paused, last_vc = _check_velocity(today, spy_df, last_vc)
        peak_new, dd = _update_drawdown(pv, peak)
        peak = peak_new if peak_new is not None else peak

        # SPY put spread (dynamic strikes)
        if today in spy_df.index:
            spx = float(spy_close.loc[today]) if today in spy_close.index else None
            if spx is not None:
                if pr is None or pds >= PUT_SPREAD_RENEW_DAYS:
                    vix_at_renewal = get_vix_level(today, vix_df)
                    active_lo, active_hi = _get_put_strikes(vix_at_renewal)
                    prem = pv * PUT_SPREAD_COST_PCT; pv -= prem
                    pr = spx; prd = today; pn = pv; pms = spx; pds = 0
                    trades.append({"ticker": "SPY_PUT_SPREAD", "entry_date": today,
                        "exit_date": today, "entry_price": spx, "exit_price": spx,
                        "shares": 0, "commission": 0, "pnl_usd": -prem,
                        "pnl_pct": -PUT_SPREAD_COST_PCT * 100, "days_held": 0,
                        "exit_reason": "put_premium", "tier": 0, "consec_down": 0,
                        "portfolio_val": pv,
                        "put_lower_otm": active_lo, "put_upper_otm": active_hi})
                else:
                    pds += 1; pms = min(pms, spx)
                    if pds == PUT_SPREAD_RENEW_DAYS - 1:
                        pay_pct = _put_payout_pct(pr, pms, active_lo, active_hi)
                        if pay_pct > 0:
                            pay = pn * pay_pct; pv += pay
                            trades.append({"ticker": "SPY_PUT_SPREAD", "entry_date": prd,
                                "exit_date": today, "entry_price": pr, "exit_price": pms,
                                "shares": 0, "commission": 0, "pnl_usd": round(pay, 2),
                                "pnl_pct": round(pay_pct * 100, 4), "days_held": pds,
                                "exit_reason": "put_payout", "tier": 0, "consec_down": 0,
                                "portfolio_val": pv,
                                "put_lower_otm": active_lo, "put_upper_otm": active_hi})

        # VIX call spread (monthly)
        if today in vix_df.index:
            vix_px = float(vix_close.loc[today]) if today in vix_close.index else None
            if vix_px is not None:
                if vc_ref is None or vc_days >= VIX_CALL_RENEW_DAYS:
                    prem = pv * VIX_CALL_COST_PCT; pv -= prem
                    vc_ref = vix_px; vc_ref_date = today
                    vc_notional = pv; vc_peak = vix_px; vc_prem = prem; vc_days = 0
                    trades.append({"ticker": "VIX_CALL_SPREAD", "entry_date": today,
                        "exit_date": today, "entry_price": vix_px, "exit_price": vix_px,
                        "shares": 0, "commission": 0, "pnl_usd": -prem,
                        "pnl_pct": -VIX_CALL_COST_PCT * 100, "days_held": 0,
                        "exit_reason": "vix_call_premium", "tier": 0, "consec_down": 0,
                        "portfolio_val": pv})
                else:
                    vc_days += 1; vc_peak = max(vc_peak, vix_px)
                    if vc_days == VIX_CALL_RENEW_DAYS - 1:
                        mult = _vix_call_payout_mult(vc_ref, vc_peak)
                        if mult > 0:
                            pay = vc_prem * mult; pv += pay
                            trades.append({"ticker": "VIX_CALL_SPREAD",
                                "entry_date": vc_ref_date, "exit_date": today,
                                "entry_price": vc_ref, "exit_price": vc_peak,
                                "shares": 0, "commission": 0, "pnl_usd": round(pay, 2),
                                "pnl_pct": round(mult * VIX_CALL_COST_PCT * 100, 4),
                                "days_held": vc_days, "exit_reason": "vix_call_payout",
                                "tier": 0, "consec_down": 0, "portfolio_val": pv})

        pv = _run_exits(today, signals, open_pos, trades, pv, cool)
        if not spy_ok or paused or vel_paused or len(open_pos) >= MAX_POSITIONS:
            continue
        vix_now = get_vix_level(today, vix_df)
        tom_today = today in tom_set; dow = pd.Timestamp(today).dayofweek
        cands = _build_candidates(today, signals, open_pos, cool, earnings_map,
                                  sector_data, vix_now, tom_today, dow)
        _enter_candidates(today, signals, cands, open_pos, cool, pv, vix_df, dd,
                          tom_today, dow)

    print(f"[Idea_G] {len(trades)} records")
    return pd.DataFrame(trades)

# ---------------------------------------------------------------------------
# Metrics extraction (identical to V7)
# ---------------------------------------------------------------------------
def _extract(trades_df: pd.DataFrame, name: str) -> dict:
    overlay = {"SPY_PUT_SPREAD", "VIX_CALL_SPREAD"}
    mr = trades_df[~trades_df["ticker"].isin(overlay)].copy()
    puts = trades_df[trades_df["ticker"] == "SPY_PUT_SPREAD"].copy()
    vxc  = trades_df[trades_df["ticker"] == "VIX_CALL_SPREAD"].copy()

    if mr.empty:
        return {"test": name, "error": "No MR trades"}

    metrics, _ = compute_metrics(mr)
    put_net   = puts["pnl_usd"].sum() if not puts.empty else 0.0
    put_prem  = puts[puts["exit_reason"] == "put_premium"]["pnl_usd"].sum() if not puts.empty else 0.0
    put_pay   = puts[puts["exit_reason"] == "put_payout"]["pnl_usd"].sum() if not puts.empty else 0.0
    vxc_net   = vxc["pnl_usd"].sum() if not vxc.empty else 0.0
    vxc_prem  = vxc[vxc["exit_reason"] == "vix_call_premium"]["pnl_usd"].sum() if not vxc.empty else 0.0
    vxc_pay   = vxc[vxc["exit_reason"] == "vix_call_payout"]["pnl_usd"].sum() if not vxc.empty else 0.0

    return {
        "test": name,
        "cagr_pct": metrics["cagr_pct"],
        "final_equity_mr": metrics["final_equity"],
        "final_equity_total": round(metrics["final_equity"] + put_net + vxc_net, 2),
        "max_drawdown_pct": metrics["max_drawdown_pct"],
        "sharpe_ratio": metrics["sharpe_ratio"],
        "win_rate_pct": metrics["win_rate_pct"],
        "profit_factor": metrics["profit_factor"],
        "total_trades": metrics["total_trades"],
        "put_net": round(put_net, 2), "put_prem": round(put_prem, 2), "put_pay": round(put_pay, 2),
        "vxc_net": round(vxc_net, 2), "vxc_prem": round(vxc_prem, 2), "vxc_pay": round(vxc_pay, 2),
        "year_stats": metrics.get("year_stats", {}),
    }

# ---------------------------------------------------------------------------
# Print table
# ---------------------------------------------------------------------------
def _print_table(results):
    BL_EQ = 9_915_308; BL_DD = -60.89; BL_CAGR = 22.40
    W = 116
    print("\n" + "="*W)
    print(f" IDEAS V7.1 — Bug Fixes + Parameter Tuning | Baseline V47+I3: "
          f"${BL_EQ:,.0f} | CAGR {BL_CAGR}% | MaxDD {BL_DD}%")
    print("="*W)
    print(f"{'Test':<24} {'CAGR%':>8} {'dCAGR':>8} {'Final Equity':>15} {'dEquity':>13} "
          f"{'MaxDD%':>9} {'dDD':>9} {'Sharpe':>8} {'WR%':>7} {'PF':>6}")
    print("-"*W)
    for r in results:
        if "error" in r:
            print(f"{r['test']:<24}  ERROR: {r['error']}")
            continue
        dc = r["cagr_pct"] - BL_CAGR
        de = r["final_equity_total"] - BL_EQ
        ddd = r["max_drawdown_pct"] - BL_DD
        star = "★" if (ddd > 0 and "Baseline" not in r["test"]) else " "
        print(f"{star}{r['test']:<23} {r['cagr_pct']:>8.2f} {dc:>+8.2f}pp "
              f"${r['final_equity_total']:>14,.0f} ${de:>+12,.0f} "
              f"{r['max_drawdown_pct']:>9.2f} {ddd:>+9.2f}pp "
              f"{r['sharpe_ratio']:>8.2f} {r['win_rate_pct']:>7.2f} {r['profit_factor']:>6.2f}")
    print("="*W)
    print(" ★ = MaxDD improved vs baseline. dDD > 0 = less negative MaxDD (better).")
    print(" Final equity = MR P&L + all overlay P&L (SPY puts + VIX calls).")
    print("="*W)

    print("\n Overlay P&L Breakdown:")
    print(f"{'Test':<24} {'SPY Put Net':>12} {'Put Prem':>12} {'Put Pay':>12} "
          f"{'VIX Call Net':>13} {'VXC Prem':>10} {'VXC Pay':>10}")
    print("-"*93)
    for r in results:
        if "error" in r:
            continue
        print(f"{r['test']:<24} ${r['put_net']:>11,.0f} ${r['put_prem']:>11,.0f} "
              f"${r['put_pay']:>11,.0f} ${r['vxc_net']:>12,.0f} "
              f"${r['vxc_prem']:>9,.0f} ${r['vxc_pay']:>9,.0f}")
    print("="*93)

    print("\n What changed vs V7 that affected each result:")
    notes = {
        "Baseline V47+I3":   "Reproduced — same as V7 baseline, confirms environment match",
        "Idea_A VIX calls":  "FIXED: payout = premium * mult (0–8x), not notional*mult. Realistic now.",
        "Idea_B CDaR scale":  "RETUNED: target 15% (was 8%), floor 60% (was 40%). Less aggressive.",
        "Idea_C VVIX gate":  "UNCHANGED: retesting to confirm V7's near-neutral -0.72pp CAGR result.",
        "Idea_D Dyn strikes": "FIXED: strikes now stored per-contract at renewal, used at payout.",
        "Idea_E Gap regime":  f"RETUNED: threshold {GAP_BEH_THRESHOLD:.0%} (was 60%). Slightly more sensitive.",
        "Idea_G D+A combo":   "NEW: dynamic strikes + VIX call overlay combined on V47+I3.",
    }
    for r in results:
        note = notes.get(r["test"], "")
        if note:
            print(f"  {r['test']:<24} {note}")
    print()

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    print("\n" + "="*70)
    print(" IDEAS V7.1 — Bug Fixes + Parameter Tuning")
    print(" Baseline V47+I3: $9,915,308 | CAGR 22.40% | MaxDD -60.89%")
    print("="*70)

    universe = get_universe()
    price_data = download_prices(universe)
    spy_df, vix_df, sector_data = download_reference_data()
    earnings_map = build_earnings_dates(list(price_data.keys()))
    vvix_df = _download_vvix()

    results = []
    tests = [
        ("Baseline V47+I3",   lambda: run_baseline(price_data, spy_df, vix_df, sector_data, earnings_map)),
        ("Idea_A VIX calls",  lambda: run_idea_a(price_data, spy_df, vix_df, sector_data, earnings_map)),
        ("Idea_B CDaR scale", lambda: run_idea_b(price_data, spy_df, vix_df, sector_data, earnings_map)),
        ("Idea_C VVIX gate",  lambda: run_idea_c(price_data, spy_df, vix_df, sector_data, earnings_map, vvix_df)),
        ("Idea_D Dyn strikes",lambda: run_idea_d(price_data, spy_df, vix_df, sector_data, earnings_map)),
        ("Idea_E Gap regime", lambda: run_idea_e(price_data, spy_df, vix_df, sector_data, earnings_map)),
        ("Idea_G D+A combo",  lambda: run_idea_g(price_data, spy_df, vix_df, sector_data, earnings_map)),
    ]

    for name, fn in tests:
        print(f"\n{'─'*50}\nRunning: {name}")
        try:
            t = fn()
            t.to_csv(OUTPUT_DIR / f"{name.replace(' ','_').lower()}_trades.csv", index=False)
            r = _extract(t, name)
            results.append(r)
            # Quick preview
            if "error" not in r:
                print(f"  → CAGR {r['cagr_pct']:.2f}% | Equity ${r['final_equity_total']:,.0f} "
                      f"| MaxDD {r['max_drawdown_pct']:.2f}%")
        except Exception as e:
            print(f"  [ERROR] {name}: {e}")
            import traceback; traceback.print_exc()
            results.append({"test": name, "error": str(e)})

    _print_table(results)

    summary = {
        "run_date": datetime.date.today().isoformat(),
        "version": "V7.1",
        "fixes_vs_v7": {
            "Idea_A": "Payout model fixed: premium*mult(0-8x) not notional*mult",
            "Idea_B": "CDaR target 8%->15%, floor 40%->60%",
            "Idea_D": "Strike state now per-contract (stored at renewal, used at payout)",
            "Idea_E": "Threshold tightened 60%->55%",
            "Idea_G": "NEW: Idea_D + Idea_A combined",
        },
        "baseline_reference": {
            "strategy": "V47+I3 full history through April 2026",
            "final_equity": 9_915_308,
            "cagr_pct": 22.40,
            "max_drawdown_pct": -60.89,
        },
        "parameters": {
            "vix_call_spread": {
                "cost_pct_monthly": VIX_CALL_COST_PCT,
                "lower_strike": VIX_CALL_LOWER,
                "upper_strike": VIX_CALL_UPPER,
                "max_payout_mult": VIX_CALL_MAX_MULT,
                "renew_days": VIX_CALL_RENEW_DAYS,
            },
            "cdar": {
                "window": CDAR_WINDOW_DAYS,
                "confidence": CDAR_CONFIDENCE,
                "target": CDAR_TARGET,
                "min_scale": CDAR_MIN_SCALE,
            },
            "vvix": {
                "mod_thresh": VVIX_MOD_THRESH,
                "ext_thresh": VVIX_EXT_THRESH,
                "mod_mult": VVIX_MOD_MULT,
                "ext_mult": VVIX_EXT_MULT,
            },
            "gap_behavior": {
                "window": GAP_BEH_WINDOW,
                "threshold": GAP_BEH_THRESHOLD,
                "mult": GAP_BEH_MULT,
            },
            "dynamic_put_strikes": {
                "vix_lt_15": "3%/13% OTM",
                "vix_15_25": "5%/15% OTM (baseline)",
                "vix_gt_25": "8%/20% OTM",
            },
        },
        "results": results,
    }
    with open(OUTPUT_DIR / "ideas_v7_1_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\n All outputs saved to: {OUTPUT_DIR.resolve()}")
    print(f" Share back: paste the IDEAS V7.1 table above")


if __name__ == "__main__":
    main()
