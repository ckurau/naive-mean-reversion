# backtest_ideas_v7_2.py
#
# Ideas V7.2 — Combined equity MaxDD + CDaR retune + equity curve export
#
# Key changes vs V7.1:
#   1. MaxDD now computed on COMBINED equity (MR + all overlays), not MR-only.
#      This correctly reflects the full portfolio experience including put payouts
#      and VIX call payouts landing in the same account during crashes.
#   2. CDaR retuned: target 20% (was 15%), floor 75% (was 60%). More surgical.
#   3. Equity curves (combined) exported per test as CSV for external charting.
#   4. All 6 V7.1 ideas retained — none eliminated. Idea_C and Idea_E kept for
#      completeness (may interact differently with combined equity measurement).
#   5. Idea_B2 added: CDaR computed on combined equity curve (not MR-only), which
#      allows the scaling to see put payouts as portfolio recovery and avoid
#      over-compressing during crash-then-recovery periods.
#
# Tests:
#   Baseline  — V47+I3 (combined equity MaxDD)
#   Idea_A    — V47 + I3 + VIX call spread (combined equity MaxDD)
#   Idea_B    — V47 + I3 + CDaR scale (retuned: target 20%, floor 75%)
#   Idea_B2   — V47 + I3 + CDaR scale on combined equity (sees overlay payouts)
#   Idea_C    — V47 + I3 + VVIX-gated sizing
#   Idea_D    — V47 + Dynamic put spread strikes (combined equity MaxDD)
#   Idea_E    — V47 + I3 + Gap-behavior sizing (threshold 55%)
#   Idea_G    — V47 + Dynamic strikes + VIX call overlay (combined equity MaxDD)
#
# Baseline reference: V47+I3 = $9,915,308 | CAGR 22.40% | MaxDD -60.89% (MR-only)
# V7.1 reproduced:   V47+I3 = $9,938,977 | CAGR 22.42% | MaxDD -60.89%
#
# Run: python backtest_ideas_v7_2.py
# GitHub Actions: ideas_v7_2_backtest.yml

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
    get_universe, download_prices, download_reference_data,
    build_earnings_dates, compute_metrics, generate_signals,
    get_position_size, get_tier, calc_commission, sector_ok,
    count_sector_positions, check_vix_spike, near_earnings,
    TICKER_TO_SECTOR, INITIAL_CAPITAL, MAX_POSITIONS,
    MA_WINDOW, VOL_MA_PERIOD, ATR_PERIOD, MIN_CONSEC_DOWN,
    MIN_HOLD_BEFORE_EXIT, VELOCITY_CRASH_5D_THRESHOLD,
    VELOCITY_CRASH_PAUSE_DAYS, GAP_DOWN_MAX, GAP_UP_MAX,
    REENTRY_COOLDOWN_DAYS, MAX_SECTOR_POSITIONS,
    TOP_SIGNAL_PCT, TOP_SIGNAL_MULTIPLIER, TOP_SIGNAL_HARD_CAP,
    MIN_CANDIDATES_FOR_C5, TOM_MULT, DOW_MULT,
    VIX_TIGHT_THRESH, RSI_TIGHT_THRESH,
    build_tom_set, get_vix_level, START_DATE, END_DATE,
)

OUTPUT_DIR = Path("results_ideas_v7_2")
OUTPUT_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# SPY put spread — baseline parameters
# ---------------------------------------------------------------------------
PUT_SPREAD_LOWER_OTM  = 0.05
PUT_SPREAD_UPPER_OTM  = 0.15
PUT_SPREAD_COST_PCT   = 0.0075
PUT_SPREAD_RENEW_DAYS = 63

def _put_payout(spy_ref, spy_worst, lo, hi):
    if spy_worst >= spy_ref * (1 - lo):
        return 0.0
    decline = (spy_ref - spy_worst) / spy_ref
    return max(0.0, min(decline - lo, hi - lo))

def _get_put_strikes(vix):
    if vix < 15.0:   return 0.03, 0.13
    if vix <= 25.0:  return 0.05, 0.15
    return 0.08, 0.20

# ---------------------------------------------------------------------------
# VIX call spread — fixed payout model (from V7.1)
# ---------------------------------------------------------------------------
VIX_CALL_COST_PCT   = 0.003
VIX_CALL_LOWER      = 20.0
VIX_CALL_UPPER      = 40.0
VIX_CALL_RENEW_DAYS = 21
VIX_CALL_MAX_MULT   = 8.0

def _vix_call_mult(vix_ref, vix_peak):
    peak = max(vix_ref, vix_peak)
    if peak <= VIX_CALL_LOWER:
        return 0.0
    above = min(peak - VIX_CALL_LOWER, VIX_CALL_UPPER - VIX_CALL_LOWER)
    return (above / (VIX_CALL_UPPER - VIX_CALL_LOWER)) * VIX_CALL_MAX_MULT

# ---------------------------------------------------------------------------
# CDaR — V7.2 parameters (more surgical)
# ---------------------------------------------------------------------------
CDAR_WINDOW      = 63
CDAR_CONF        = 0.95
CDAR_TARGET      = 0.20    # was 0.15 in V7.1 — fires only in genuine sustained distress
CDAR_MIN_SCALE   = 0.75    # was 0.60 in V7.1 — lighter compression at worst

def _cdar(hist, window=63, conf=0.95):
    if len(hist) < window + 1:
        return 0.0
    recent = list(hist)[-(window * 2):]
    n = len(recent)
    dds = []
    for s in range(n - window):
        c = recent[s:s + window]
        pk = max(c); pi = c.index(pk)
        tr = min(c[pi:]) if pi < len(c) - 1 else pk
        dds.append(abs((tr - pk) / pk) if pk > 0 else 0.0)
    if not dds: return 0.0
    dds.sort(reverse=True)
    tail = max(1, int(len(dds) * (1 - conf)))
    return sum(dds[:tail]) / tail

def _cdar_scale(val):
    if val <= CDAR_TARGET: return 1.0
    excess = (val - CDAR_TARGET) / CDAR_TARGET
    return max(1.0 - excess * (1.0 - CDAR_MIN_SCALE), CDAR_MIN_SCALE)

# ---------------------------------------------------------------------------
# VVIX
# ---------------------------------------------------------------------------
VVIX_MOD = 120.0; VVIX_EXT = 140.0
VVIX_MOD_MULT = 0.70; VVIX_EXT_MULT = 0.50

def _dl_vvix():
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

def _vvix(today, df):
    if df.empty: return 100.0
    try:
        vc = df["Close"].squeeze()
        if today in vc.index: return float(vc.loc[today])
    except Exception: pass
    return 100.0

def _vm(level):
    if level >= VVIX_EXT: return VVIX_EXT_MULT
    if level >= VVIX_MOD: return VVIX_MOD_MULT
    return 1.0

# ---------------------------------------------------------------------------
# Gap behavior
# ---------------------------------------------------------------------------
GAP_BEH_WIN   = 3
GAP_BEH_THOLD = 0.55
GAP_BEH_MULT  = 0.60
GAP_DN_THOLD  = -0.005

# ---------------------------------------------------------------------------
# Combined equity curve computation for MaxDD
# ---------------------------------------------------------------------------
def _combined_equity_curve(trades_df: pd.DataFrame) -> pd.DataFrame:
    """
    Build a combined daily equity curve from ALL trades (MR + overlays).
    Sort by exit_date, accumulate P&L from INITIAL_CAPITAL.
    Returns DataFrame with columns: date, equity, peak, drawdown_pct
    """
    df = trades_df.copy()
    df["exit_date"] = pd.to_datetime(df["exit_date"])
    df = df.sort_values("exit_date").reset_index(drop=True)
    equity = INITIAL_CAPITAL
    rows = []
    for _, row in df.iterrows():
        equity += row["pnl_usd"]
        rows.append({"date": row["exit_date"], "equity": equity})
    eq = pd.DataFrame(rows)
    if eq.empty:
        return eq
    eq["peak"] = eq["equity"].cummax()
    eq["drawdown_pct"] = (eq["equity"] - eq["peak"]) / eq["peak"] * 100.0
    return eq

def _combined_metrics(trades_df: pd.DataFrame) -> dict:
    """
    Compute key metrics from combined equity curve (all trades).
    Returns: final_equity, max_drawdown_pct, equity_curve_df
    """
    eq = _combined_equity_curve(trades_df)
    if eq.empty:
        return {"final_equity_combined": INITIAL_CAPITAL,
                "max_drawdown_combined_pct": 0.0, "equity_curve": eq}
    final = float(eq["equity"].iloc[-1])
    max_dd = float(eq["drawdown_pct"].min())
    return {"final_equity_combined": round(final, 2),
            "max_drawdown_combined_pct": round(max_dd, 2),
            "equity_curve": eq}

# ---------------------------------------------------------------------------
# Shared helpers (identical to V7.1)
# ---------------------------------------------------------------------------
def _init_signals(price_data):
    signals = {}
    min_bars = MA_WINDOW + VOL_MA_PERIOD + ATR_PERIOD + MIN_CONSEC_DOWN + 5
    for tkr, df in price_data.items():
        if len(df) > min_bars:
            signals[tkr] = generate_signals(df)
    return signals

def _make_pos(tkr_df, idx, today, ep, cv, rv, pv, vix_df, dd, sm):
    tier = get_tier(cv)
    size = get_position_size(today, vix_df, dd, multiplier=sm, hard_cap=TOP_SIGNAL_HARD_CAP)
    sh = (pv * size) / ep
    ec = calc_commission(sh, ep)
    return {"entry_date": tkr_df.index[idx + 1], "entry_price": ep,
            "shares": sh, "shares_remaining": sh, "rsi2_at_entry": rv,
            "consec_down_at_entry": cv, "profit_target": tier["profit_target"],
            "hold_days": tier["hold_days"], "partial_enabled": tier["partial_enabled"],
            "partial_frac": tier["partial_frac"], "partial_trigger": tier["partial_trigger"],
            "partial_done": False, "tier": tier["tier"], "entry_commission": ec}

def _run_exits(today, signals, open_pos, trades, pv, cool):
    to_close = []
    for tkr, pos in open_pos.items():
        if tkr not in signals or today not in signals[tkr].index: continue
        row = signals[tkr].loc[today]
        ep = pos["entry_price"]; xp = float(row["Close"])
        dh = (pd.Timestamp(today) - pd.Timestamp(pos["entry_date"])).days
        pp = (xp - ep) / ep
        sr = pos["shares_remaining"]
        early = dh < MIN_HOLD_BEFORE_EXIT
        ts = dh >= pos["hold_days"]
        ph = (not early) and pp >= pos["profit_target"]

        if (pos["partial_enabled"] and not pos["partial_done"]
                and not early and pp >= pos["partial_trigger"]):
            psh = sr * pos["partial_frac"]
            cm = calc_commission(psh, xp)
            pnl = (xp - ep) * psh - cm
            trades.append({"ticker": tkr, "entry_date": pos["entry_date"],
                "exit_date": today, "entry_price": ep, "exit_price": xp,
                "shares": psh, "commission": round(cm, 4), "pnl_usd": pnl,
                "pnl_pct": pp * 100, "days_held": dh, "exit_reason": "partial_exit",
                "tier": pos["tier"], "consec_down": pos["consec_down_at_entry"],
                "portfolio_val": pv + pnl})
            pv += pnl; pos["shares_remaining"] -= psh
            pos["partial_done"] = True; pos["profit_target"] *= 2
            continue

        fx = ts or (not pos["partial_enabled"] and ph) or \
             (pos["partial_enabled"] and pos["partial_done"] and ph)
        if fx:
            cm = calc_commission(sr, xp)
            pnl = (xp - ep) * sr - cm - pos["entry_commission"]
            rsn = "time_stop" if ts else "profit_target"
            trades.append({"ticker": tkr, "entry_date": pos["entry_date"],
                "exit_date": today, "entry_price": ep, "exit_price": xp,
                "shares": sr, "commission": round(cm + pos["entry_commission"], 4),
                "pnl_usd": pnl, "pnl_pct": pp * 100, "days_held": dh,
                "exit_reason": rsn, "tier": pos["tier"],
                "consec_down": pos["consec_down_at_entry"], "portfolio_val": pv + pnl})
            pv += pnl
            if ts: cool[tkr] = today
            to_close.append(tkr)
    for tkr in to_close: del open_pos[tkr]
    return pv

def _build_cands(today, signals, open_pos, cool, earnings_map, sector_data, vix_now):
    cands = []
    for tkr, tkr_df in signals.items():
        if tkr in open_pos or today not in tkr_df.index: continue
        row = tkr_df.loc[today]
        if not row["signal"]: continue
        if vix_now < VIX_TIGHT_THRESH and float(row["rsi2"]) >= RSI_TIGHT_THRESH: continue
        if tkr in cool:
            if (pd.Timestamp(today) - pd.Timestamp(cool[tkr])).days < REENTRY_COOLDOWN_DAYS: continue
        if near_earnings(tkr, today, earnings_map): continue
        if not sector_ok(tkr, today, sector_data): continue
        if count_sector_positions(tkr, open_pos) >= MAX_SECTOR_POSITIONS: continue
        rsi2 = float(row["rsi2"]); atr = float(row["atr_pct"])
        score = rsi2 / atr if atr > 0 else rsi2 * 1000
        cands.append((score, tkr, int(row["consec_down"]), rsi2))
    return sorted(cands, key=lambda x: x[0])

def _enter(today, signals, cands, open_pos, cool, pv, vix_df, dd, tom_today, dow, xm=1.0):
    n = len(cands); top_n = max(1, int(n * TOP_SIGNAL_PCT))
    for rank, (score, tkr, cv, rv) in enumerate(cands):
        if len(open_pos) >= MAX_POSITIONS: break
        tkr_df = signals[tkr]
        idx = tkr_df.index.get_loc(today)
        if idx + 1 >= len(tkr_df): continue
        ep = float(tkr_df.iloc[idx + 1]["Open"])
        if ep <= 0: continue
        pc = float(tkr_df.iloc[idx]["Close"])
        gp = (ep - pc) / pc
        if gp < GAP_DOWN_MAX or gp > GAP_UP_MAX: continue
        sm = 1.0
        if n >= MIN_CANDIDATES_FOR_C5 and rank < top_n: sm = TOP_SIGNAL_MULTIPLIER
        if tom_today: sm *= TOM_MULT
        sm *= DOW_MULT.get(dow, 1.0)
        sm *= xm
        open_pos[tkr] = _make_pos(tkr_df, idx, today, ep, cv, rv, pv, vix_df, dd, sm)

def _vel(today, spy_df, last_vc):
    paused = False
    try:
        if today in spy_df.index:
            v = float(spy_df.loc[today, "spy_5d_ret"])
            if not np.isnan(v) and v < VELOCITY_CRASH_5D_THRESHOLD:
                last_vc = today
        if last_vc and (pd.Timestamp(today) - pd.Timestamp(last_vc)).days <= VELOCITY_CRASH_PAUSE_DAYS:
            paused = True
    except Exception: pass
    return paused, last_vc

def _dd_upd(pv, peak):
    if peak is None:
        return (pv, 0.0) if pv != INITIAL_CAPITAL else (None, 0.0)
    if pv > peak: return pv, 0.0
    return peak, (pv - peak) / peak

# ---------------------------------------------------------------------------
# Put spread helpers — inline (no shared function to avoid mutable state bugs)
# Returns updated (pv, pr, prd, pn, pms, pds, alo, ahi)
# dynamic=True uses VIX-conditional strike selection
# ---------------------------------------------------------------------------
def _put_tick(today, spy_df, spy_close, pv, trades, pr, prd, pn, pms, pds, alo, ahi,
              vix_df=None, dynamic=False):
    if today not in spy_df.index:
        return pv, pr, prd, pn, pms, pds, alo, ahi
    spx = float(spy_close.loc[today]) if today in spy_close.index else None
    if spx is None:
        return pv, pr, prd, pn, pms, pds, alo, ahi

    if pr is None or pds >= PUT_SPREAD_RENEW_DAYS:
        if dynamic and vix_df is not None:
            alo, ahi = _get_put_strikes(get_vix_level(today, vix_df))
        prem = pv * PUT_SPREAD_COST_PCT; pv -= prem
        pr = spx; prd = today; pn = pv; pms = spx; pds = 0
        trades.append({"ticker": "SPY_PUT_SPREAD", "entry_date": today, "exit_date": today,
            "entry_price": spx, "exit_price": spx, "shares": 0, "commission": 0,
            "pnl_usd": -prem, "pnl_pct": -PUT_SPREAD_COST_PCT * 100,
            "days_held": 0, "exit_reason": "put_premium", "tier": 0, "consec_down": 0,
            "portfolio_val": pv, "put_lo": alo, "put_hi": ahi})
    else:
        pds += 1; pms = min(pms, spx)
        if pds == PUT_SPREAD_RENEW_DAYS - 1:
            pay_pct = _put_payout(pr, pms, alo, ahi)
            if pay_pct > 0:
                pay = pn * pay_pct; pv += pay
                trades.append({"ticker": "SPY_PUT_SPREAD", "entry_date": prd, "exit_date": today,
                    "entry_price": pr, "exit_price": pms, "shares": 0, "commission": 0,
                    "pnl_usd": round(pay, 2), "pnl_pct": round(pay_pct * 100, 4),
                    "days_held": pds, "exit_reason": "put_payout", "tier": 0, "consec_down": 0,
                    "portfolio_val": pv, "put_lo": alo, "put_hi": ahi})
    return pv, pr, prd, pn, pms, pds, alo, ahi

# VIX call spread — inline
def _vxc_tick(today, vix_df, vix_close, pv, trades, vd, vr, vrd, vn, vpk, vpm):
    if today not in vix_df.index:
        return pv, vd, vr, vrd, vn, vpk, vpm
    vpx = float(vix_close.loc[today]) if today in vix_close.index else None
    if vpx is None:
        return pv, vd, vr, vrd, vn, vpk, vpm

    if vr is None or vd >= VIX_CALL_RENEW_DAYS:
        prem = pv * VIX_CALL_COST_PCT; pv -= prem
        vr = vpx; vrd = today; vn = pv; vpk = vpx; vpm = prem; vd = 0
        trades.append({"ticker": "VIX_CALL_SPREAD", "entry_date": today, "exit_date": today,
            "entry_price": vpx, "exit_price": vpx, "shares": 0, "commission": 0,
            "pnl_usd": -prem, "pnl_pct": -VIX_CALL_COST_PCT * 100,
            "days_held": 0, "exit_reason": "vix_call_premium", "tier": 0, "consec_down": 0,
            "portfolio_val": pv})
    else:
        vd += 1; vpk = max(vpk, vpx)
        if vd == VIX_CALL_RENEW_DAYS - 1:
            mult = _vix_call_mult(vr, vpk)
            if mult > 0:
                pay = vpm * mult; pv += pay
                trades.append({"ticker": "VIX_CALL_SPREAD", "entry_date": vrd, "exit_date": today,
                    "entry_price": vr, "exit_price": vpk, "shares": 0, "commission": 0,
                    "pnl_usd": round(pay, 2), "pnl_pct": round(mult * VIX_CALL_COST_PCT * 100, 4),
                    "days_held": vd, "exit_reason": "vix_call_payout", "tier": 0, "consec_down": 0,
                    "portfolio_val": pv})
    return pv, vd, vr, vrd, vn, vpk, vpm

# ===========================================================================
# TEST FUNCTIONS
# ===========================================================================

def _core_loop(price_data, spy_df, vix_df, signals, all_dates, tom_set,
               on_pre_entries=None, extra_state=None):
    """
    Core MR loop shared by all tests.
    on_pre_entries(today, state) -> extra_mult float
    Called just before entries; can modify state dict in place.
    Returns trades list.
    """
    spy_regime = spy_df["spy_ok"].to_dict()
    spy_close = spy_df["Close"].squeeze()
    pv = INITIAL_CAPITAL; peak = None; dd = 0.0
    open_pos = {}; trades = []; cool = {}
    last_vs = None; last_vc = None
    if extra_state is None: extra_state = {}

    for today in all_dates:
        spy_ok = spy_regime.get(today, True)
        paused, last_vs = check_vix_spike(today, vix_df, last_vs)
        vel_paused, last_vc = _vel(today, spy_df, last_vc)
        peak_new, dd = _dd_upd(pv, peak)
        peak = peak_new if peak_new is not None else peak

        # Let caller handle overlays and state updates
        if on_pre_entries:
            pv = on_pre_entries(today, spy_df, spy_close, vix_df, trades,
                                open_pos, cool, pv, dd, extra_state)

        pv = _run_exits(today, signals, open_pos, trades, pv, cool)

        if not spy_ok or paused or vel_paused or len(open_pos) >= MAX_POSITIONS:
            continue

        vix_now = get_vix_level(today, vix_df)
        tom_today = today in tom_set; dow = pd.Timestamp(today).dayofweek
        cands = _build_cands(today, signals, open_pos, cool,
                              extra_state.get("earnings_map", {}),
                              extra_state.get("sector_data", {}), vix_now)
        xm = extra_state.get("extra_mult", 1.0)
        _enter(today, signals, cands, open_pos, cool, pv, vix_df, dd, tom_today, dow, xm)
        extra_state["extra_mult"] = 1.0  # reset after each day

    return trades

# ---------------------------------------------------------------------------
# BASELINE — V47+I3
# ---------------------------------------------------------------------------
def run_baseline(price_data, spy_df, vix_df, sector_data, earnings_map):
    print("\n[Baseline] V47 + I3")
    all_dates = sorted(set().union(*[set(df.index) for df in price_data.values()]))
    tom_set = build_tom_set(all_dates)
    signals = _init_signals(price_data)
    spy_close = spy_df["Close"].squeeze()

    state = {"earnings_map": earnings_map, "sector_data": sector_data, "extra_mult": 1.0,
             "pr": None, "prd": None, "pn": 0.0, "pms": 9999.0, "pds": 0,
             "alo": PUT_SPREAD_LOWER_OTM, "ahi": PUT_SPREAD_UPPER_OTM}

    def hook(today, spy_df, spy_close, vix_df, trades, open_pos, cool, pv, dd, s):
        pv, s["pr"], s["prd"], s["pn"], s["pms"], s["pds"], s["alo"], s["ahi"] = \
            _put_tick(today, spy_df, spy_close, pv, trades,
                      s["pr"], s["prd"], s["pn"], s["pms"], s["pds"], s["alo"], s["ahi"])
        return pv

    spy_regime = spy_df["spy_ok"].to_dict()
    pv = INITIAL_CAPITAL; peak = None; dd = 0.0
    open_pos = {}; trades = []; cool = {}; last_vs = None; last_vc = None

    for today in sorted(set().union(*[set(df.index) for df in price_data.values()])):
        spy_ok = spy_regime.get(today, True)
        paused, last_vs = check_vix_spike(today, vix_df, last_vs)
        vel_paused, last_vc = _vel(today, spy_df, last_vc)
        peak_new, dd = _dd_upd(pv, peak)
        peak = peak_new if peak_new is not None else peak
        pv = hook(today, spy_df, spy_close, vix_df, trades, open_pos, cool, pv, dd, state)
        pv = _run_exits(today, signals, open_pos, trades, pv, cool)
        if not spy_ok or paused or vel_paused or len(open_pos) >= MAX_POSITIONS: continue
        vix_now = get_vix_level(today, vix_df)
        tom_today = today in tom_set; dow = pd.Timestamp(today).dayofweek
        cands = _build_cands(today, signals, open_pos, cool, earnings_map, sector_data, vix_now)
        _enter(today, signals, cands, open_pos, cool, pv, vix_df, dd, tom_today, dow)

    print(f"[Baseline] {len(trades)} records")
    return pd.DataFrame(trades)

# ---------------------------------------------------------------------------
# IDEA A — V47 + I3 + VIX call spread
# ---------------------------------------------------------------------------
def run_idea_a(price_data, spy_df, vix_df, sector_data, earnings_map):
    print("\n[Idea_A] V47 + I3 + VIX call spread")
    all_dates = sorted(set().union(*[set(df.index) for df in price_data.values()]))
    tom_set = build_tom_set(all_dates)
    signals = _init_signals(price_data)
    spy_regime = spy_df["spy_ok"].to_dict()
    spy_close = spy_df["Close"].squeeze()
    vix_close = vix_df["Close"].squeeze()

    pv = INITIAL_CAPITAL; peak = None; dd = 0.0
    open_pos = {}; trades = []; cool = {}; last_vs = None; last_vc = None
    pr = None; prd = None; pn = 0.0; pms = 9999.0; pds = 0
    alo = PUT_SPREAD_LOWER_OTM; ahi = PUT_SPREAD_UPPER_OTM
    vd = 0; vr = None; vrd = None; vn = 0.0; vpk = 0.0; vpm = 0.0

    for today in all_dates:
        spy_ok = spy_regime.get(today, True)
        paused, last_vs = check_vix_spike(today, vix_df, last_vs)
        vel_paused, last_vc = _vel(today, spy_df, last_vc)
        peak_new, dd = _dd_upd(pv, peak)
        peak = peak_new if peak_new is not None else peak
        pv, pr, prd, pn, pms, pds, alo, ahi = _put_tick(today, spy_df, spy_close, pv, trades, pr, prd, pn, pms, pds, alo, ahi)
        pv, vd, vr, vrd, vn, vpk, vpm = _vxc_tick(today, vix_df, vix_close, pv, trades, vd, vr, vrd, vn, vpk, vpm)
        pv = _run_exits(today, signals, open_pos, trades, pv, cool)
        if not spy_ok or paused or vel_paused or len(open_pos) >= MAX_POSITIONS: continue
        vix_now = get_vix_level(today, vix_df)
        tom_today = today in tom_set; dow = pd.Timestamp(today).dayofweek
        cands = _build_cands(today, signals, open_pos, cool, earnings_map, sector_data, vix_now)
        _enter(today, signals, cands, open_pos, cool, pv, vix_df, dd, tom_today, dow)

    print(f"[Idea_A] {len(trades)} records")
    return pd.DataFrame(trades)

# ---------------------------------------------------------------------------
# IDEA B — CDaR scale (target 20%, floor 75%), CDaR on MR-only equity
# ---------------------------------------------------------------------------
def run_idea_b(price_data, spy_df, vix_df, sector_data, earnings_map):
    print("\n[Idea_B] V47 + I3 + CDaR scale (target 20%, floor 75%)")
    all_dates = sorted(set().union(*[set(df.index) for df in price_data.values()]))
    tom_set = build_tom_set(all_dates)
    signals = _init_signals(price_data)
    spy_regime = spy_df["spy_ok"].to_dict()
    spy_close = spy_df["Close"].squeeze()

    pv = INITIAL_CAPITAL; peak = None; dd = 0.0
    open_pos = {}; trades = []; cool = {}; last_vs = None; last_vc = None
    pr = None; prd = None; pn = 0.0; pms = 9999.0; pds = 0
    alo = PUT_SPREAD_LOWER_OTM; ahi = PUT_SPREAD_UPPER_OTM
    mr_hist = deque(maxlen=CDAR_WINDOW * 2 + 10)
    mr_hist.append(INITIAL_CAPITAL)
    mr_equity = INITIAL_CAPITAL  # tracks MR-only for CDaR input

    for today in all_dates:
        spy_ok = spy_regime.get(today, True)
        paused, last_vs = check_vix_spike(today, vix_df, last_vs)
        vel_paused, last_vc = _vel(today, spy_df, last_vc)
        peak_new, dd = _dd_upd(pv, peak)
        peak = peak_new if peak_new is not None else peak
        mr_hist.append(mr_equity)
        cs = _cdar_scale(_cdar(list(mr_hist), CDAR_WINDOW, CDAR_CONF))
        pv, pr, prd, pn, pms, pds, alo, ahi = _put_tick(today, spy_df, spy_close, pv, trades, pr, prd, pn, pms, pds, alo, ahi)
        pv_before = pv
        pv = _run_exits(today, signals, open_pos, trades, pv, cool)
        mr_equity += (pv - pv_before)  # track MR P&L only
        if not spy_ok or paused or vel_paused or len(open_pos) >= MAX_POSITIONS: continue
        vix_now = get_vix_level(today, vix_df)
        tom_today = today in tom_set; dow = pd.Timestamp(today).dayofweek
        cands = _build_cands(today, signals, open_pos, cool, earnings_map, sector_data, vix_now)
        _enter(today, signals, cands, open_pos, cool, pv, vix_df, dd, tom_today, dow, xm=cs)

    print(f"[Idea_B] {len(trades)} records")
    return pd.DataFrame(trades)

# ---------------------------------------------------------------------------
# IDEA B2 — CDaR scale computed on COMBINED equity (sees put payouts)
# ---------------------------------------------------------------------------
def run_idea_b2(price_data, spy_df, vix_df, sector_data, earnings_map):
    print("\n[Idea_B2] V47 + I3 + CDaR scale on COMBINED equity (target 20%, floor 75%)")
    all_dates = sorted(set().union(*[set(df.index) for df in price_data.values()]))
    tom_set = build_tom_set(all_dates)
    signals = _init_signals(price_data)
    spy_regime = spy_df["spy_ok"].to_dict()
    spy_close = spy_df["Close"].squeeze()

    pv = INITIAL_CAPITAL; peak = None; dd = 0.0
    open_pos = {}; trades = []; cool = {}; last_vs = None; last_vc = None
    pr = None; prd = None; pn = 0.0; pms = 9999.0; pds = 0
    alo = PUT_SPREAD_LOWER_OTM; ahi = PUT_SPREAD_UPPER_OTM
    comb_hist = deque(maxlen=CDAR_WINDOW * 2 + 10)
    comb_hist.append(INITIAL_CAPITAL)

    for today in all_dates:
        spy_ok = spy_regime.get(today, True)
        paused, last_vs = check_vix_spike(today, vix_df, last_vs)
        vel_paused, last_vc = _vel(today, spy_df, last_vc)
        peak_new, dd = _dd_upd(pv, peak)
        peak = peak_new if peak_new is not None else peak
        # CDaR computed on combined portfolio value (which includes put payouts received)
        comb_hist.append(pv)
        cs = _cdar_scale(_cdar(list(comb_hist), CDAR_WINDOW, CDAR_CONF))
        pv, pr, prd, pn, pms, pds, alo, ahi = _put_tick(today, spy_df, spy_close, pv, trades, pr, prd, pn, pms, pds, alo, ahi)
        pv = _run_exits(today, signals, open_pos, trades, pv, cool)
        if not spy_ok or paused or vel_paused or len(open_pos) >= MAX_POSITIONS: continue
        vix_now = get_vix_level(today, vix_df)
        tom_today = today in tom_set; dow = pd.Timestamp(today).dayofweek
        cands = _build_cands(today, signals, open_pos, cool, earnings_map, sector_data, vix_now)
        _enter(today, signals, cands, open_pos, cool, pv, vix_df, dd, tom_today, dow, xm=cs)

    print(f"[Idea_B2] {len(trades)} records")
    return pd.DataFrame(trades)

# ---------------------------------------------------------------------------
# IDEA C — VVIX-gated sizing
# ---------------------------------------------------------------------------
def run_idea_c(price_data, spy_df, vix_df, sector_data, earnings_map, vvix_df):
    print("\n[Idea_C] V47 + I3 + VVIX-gated sizing")
    all_dates = sorted(set().union(*[set(df.index) for df in price_data.values()]))
    tom_set = build_tom_set(all_dates)
    signals = _init_signals(price_data)
    spy_regime = spy_df["spy_ok"].to_dict()
    spy_close = spy_df["Close"].squeeze()

    pv = INITIAL_CAPITAL; peak = None; dd = 0.0
    open_pos = {}; trades = []; cool = {}; last_vs = None; last_vc = None
    pr = None; prd = None; pn = 0.0; pms = 9999.0; pds = 0
    alo = PUT_SPREAD_LOWER_OTM; ahi = PUT_SPREAD_UPPER_OTM

    for today in all_dates:
        spy_ok = spy_regime.get(today, True)
        paused, last_vs = check_vix_spike(today, vix_df, last_vs)
        vel_paused, last_vc = _vel(today, spy_df, last_vc)
        peak_new, dd = _dd_upd(pv, peak)
        peak = peak_new if peak_new is not None else peak
        vm = _vm(_vvix(today, vvix_df))
        pv, pr, prd, pn, pms, pds, alo, ahi = _put_tick(today, spy_df, spy_close, pv, trades, pr, prd, pn, pms, pds, alo, ahi)
        pv = _run_exits(today, signals, open_pos, trades, pv, cool)
        if not spy_ok or paused or vel_paused or len(open_pos) >= MAX_POSITIONS: continue
        vix_now = get_vix_level(today, vix_df)
        tom_today = today in tom_set; dow = pd.Timestamp(today).dayofweek
        cands = _build_cands(today, signals, open_pos, cool, earnings_map, sector_data, vix_now)
        _enter(today, signals, cands, open_pos, cool, pv, vix_df, dd, tom_today, dow, xm=vm)

    print(f"[Idea_C] {len(trades)} records")
    return pd.DataFrame(trades)

# ---------------------------------------------------------------------------
# IDEA D — Dynamic put spread strikes
# ---------------------------------------------------------------------------
def run_idea_d(price_data, spy_df, vix_df, sector_data, earnings_map):
    print("\n[Idea_D] V47 + Dynamic put spread strikes")
    all_dates = sorted(set().union(*[set(df.index) for df in price_data.values()]))
    tom_set = build_tom_set(all_dates)
    signals = _init_signals(price_data)
    spy_regime = spy_df["spy_ok"].to_dict()
    spy_close = spy_df["Close"].squeeze()

    pv = INITIAL_CAPITAL; peak = None; dd = 0.0
    open_pos = {}; trades = []; cool = {}; last_vs = None; last_vc = None
    pr = None; prd = None; pn = 0.0; pms = 9999.0; pds = 0
    alo = PUT_SPREAD_LOWER_OTM; ahi = PUT_SPREAD_UPPER_OTM

    for today in all_dates:
        spy_ok = spy_regime.get(today, True)
        paused, last_vs = check_vix_spike(today, vix_df, last_vs)
        vel_paused, last_vc = _vel(today, spy_df, last_vc)
        peak_new, dd = _dd_upd(pv, peak)
        peak = peak_new if peak_new is not None else peak
        # dynamic=True: strikes chosen from VIX at renewal, stored in alo/ahi
        pv, pr, prd, pn, pms, pds, alo, ahi = _put_tick(today, spy_df, spy_close, pv, trades,
            pr, prd, pn, pms, pds, alo, ahi, vix_df=vix_df, dynamic=True)
        pv = _run_exits(today, signals, open_pos, trades, pv, cool)
        if not spy_ok or paused or vel_paused or len(open_pos) >= MAX_POSITIONS: continue
        vix_now = get_vix_level(today, vix_df)
        tom_today = today in tom_set; dow = pd.Timestamp(today).dayofweek
        cands = _build_cands(today, signals, open_pos, cool, earnings_map, sector_data, vix_now)
        _enter(today, signals, cands, open_pos, cool, pv, vix_df, dd, tom_today, dow)

    print(f"[Idea_D] {len(trades)} records")
    return pd.DataFrame(trades)

# ---------------------------------------------------------------------------
# IDEA E — Gap-behavior regime sizing (threshold 55%)
# ---------------------------------------------------------------------------
def run_idea_e(price_data, spy_df, vix_df, sector_data, earnings_map):
    print(f"\n[Idea_E] V47 + I3 + Gap-behavior sizing (threshold {GAP_BEH_THOLD:.0%})")
    all_dates = sorted(set().union(*[set(df.index) for df in price_data.values()]))
    tom_set = build_tom_set(all_dates)
    signals = _init_signals(price_data)
    spy_regime = spy_df["spy_ok"].to_dict()
    spy_close = spy_df["Close"].squeeze()

    pv = INITIAL_CAPITAL; peak = None; dd = 0.0
    open_pos = {}; trades = []; cool = {}; last_vs = None; last_vc = None
    pr = None; prd = None; pn = 0.0; pms = 9999.0; pds = 0
    alo = PUT_SPREAD_LOWER_OTM; ahi = PUT_SPREAD_UPPER_OTM
    gap_hist = deque(maxlen=GAP_BEH_WIN)

    for today in all_dates:
        spy_ok = spy_regime.get(today, True)
        paused, last_vs = check_vix_spike(today, vix_df, last_vs)
        vel_paused, last_vc = _vel(today, spy_df, last_vc)
        peak_new, dd = _dd_upd(pv, peak)
        peak = peak_new if peak_new is not None else peak
        pv, pr, prd, pn, pms, pds, alo, ahi = _put_tick(today, spy_df, spy_close, pv, trades, pr, prd, pn, pms, pds, alo, ahi)
        pv = _run_exits(today, signals, open_pos, trades, pv, cool)
        if not spy_ok or paused or vel_paused or len(open_pos) >= MAX_POSITIONS: continue

        vix_now = get_vix_level(today, vix_df)
        tom_today = today in tom_set; dow = pd.Timestamp(today).dayofweek
        # Measure gap behavior across today's candidates
        gdn = 0; tot = 0; cands_raw = []
        for tkr, tkr_df in signals.items():
            if tkr in open_pos or today not in tkr_df.index: continue
            row = tkr_df.loc[today]
            if not row["signal"]: continue
            if vix_now < VIX_TIGHT_THRESH and float(row["rsi2"]) >= RSI_TIGHT_THRESH: continue
            if tkr in cool:
                if (pd.Timestamp(today) - pd.Timestamp(cool[tkr])).days < REENTRY_COOLDOWN_DAYS: continue
            if near_earnings(tkr, today, earnings_map): continue
            if not sector_ok(tkr, today, sector_data): continue
            if count_sector_positions(tkr, open_pos) >= MAX_SECTOR_POSITIONS: continue
            rsi2 = float(row["rsi2"]); atr = float(row["atr_pct"])
            score = rsi2 / atr if atr > 0 else rsi2 * 1000
            cands_raw.append((score, tkr, int(row["consec_down"]), rsi2))
            tot += 1
            ci = tkr_df.index.get_loc(today)
            if ci >= 1:
                pc = float(tkr_df.iloc[ci - 1]["Close"])
                op = float(tkr_df.iloc[ci]["Open"])
                if pc > 0 and (op - pc) / pc < GAP_DN_THOLD: gdn += 1

        ratio = (gdn / tot) if tot > 0 else 0.0
        gap_hist.append(ratio)
        avg = sum(gap_hist) / len(gap_hist)
        gbm = GAP_BEH_MULT if avg > GAP_BEH_THOLD else 1.0
        cands = sorted(cands_raw, key=lambda x: x[0])
        _enter(today, signals, cands, open_pos, cool, pv, vix_df, dd, tom_today, dow, xm=gbm)

    print(f"[Idea_E] {len(trades)} records")
    return pd.DataFrame(trades)

# ---------------------------------------------------------------------------
# IDEA G — Dynamic strikes + VIX call overlay (best combo)
# ---------------------------------------------------------------------------
def run_idea_g(price_data, spy_df, vix_df, sector_data, earnings_map):
    print("\n[Idea_G] V47 + Dynamic strikes + VIX call overlay")
    all_dates = sorted(set().union(*[set(df.index) for df in price_data.values()]))
    tom_set = build_tom_set(all_dates)
    signals = _init_signals(price_data)
    spy_regime = spy_df["spy_ok"].to_dict()
    spy_close = spy_df["Close"].squeeze()
    vix_close = vix_df["Close"].squeeze()

    pv = INITIAL_CAPITAL; peak = None; dd = 0.0
    open_pos = {}; trades = []; cool = {}; last_vs = None; last_vc = None
    pr = None; prd = None; pn = 0.0; pms = 9999.0; pds = 0
    alo = PUT_SPREAD_LOWER_OTM; ahi = PUT_SPREAD_UPPER_OTM
    vd = 0; vr = None; vrd = None; vn = 0.0; vpk = 0.0; vpm = 0.0

    for today in all_dates:
        spy_ok = spy_regime.get(today, True)
        paused, last_vs = check_vix_spike(today, vix_df, last_vs)
        vel_paused, last_vc = _vel(today, spy_df, last_vc)
        peak_new, dd = _dd_upd(pv, peak)
        peak = peak_new if peak_new is not None else peak
        # Dynamic strikes (Idea_D) + VIX call (Idea_A)
        pv, pr, prd, pn, pms, pds, alo, ahi = _put_tick(today, spy_df, spy_close, pv, trades,
            pr, prd, pn, pms, pds, alo, ahi, vix_df=vix_df, dynamic=True)
        pv, vd, vr, vrd, vn, vpk, vpm = _vxc_tick(today, vix_df, vix_close, pv, trades, vd, vr, vrd, vn, vpk, vpm)
        pv = _run_exits(today, signals, open_pos, trades, pv, cool)
        if not spy_ok or paused or vel_paused or len(open_pos) >= MAX_POSITIONS: continue
        vix_now = get_vix_level(today, vix_df)
        tom_today = today in tom_set; dow = pd.Timestamp(today).dayofweek
        cands = _build_cands(today, signals, open_pos, cool, earnings_map, sector_data, vix_now)
        _enter(today, signals, cands, open_pos, cool, pv, vix_df, dd, tom_today, dow)

    print(f"[Idea_G] {len(trades)} records")
    return pd.DataFrame(trades)

# ===========================================================================
# METRICS & REPORTING
# ===========================================================================

def _extract(trades_df: pd.DataFrame, name: str) -> dict:
    """
    Extract metrics using COMBINED equity for MaxDD.
    MR CAGR still computed on MR-only trades (matches V47+I3 reference methodology).
    """
    overlay_tickers = {"SPY_PUT_SPREAD", "VIX_CALL_SPREAD"}
    mr = trades_df[~trades_df["ticker"].isin(overlay_tickers)].copy()
    puts = trades_df[trades_df["ticker"] == "SPY_PUT_SPREAD"].copy()
    vxc  = trades_df[trades_df["ticker"] == "VIX_CALL_SPREAD"].copy()

    if mr.empty:
        return {"test": name, "error": "No MR trades"}

    mr_metrics, _ = compute_metrics(mr)

    # Combined equity metrics — MaxDD on full portfolio
    comb = _combined_metrics(trades_df)

    put_net  = puts["pnl_usd"].sum() if not puts.empty else 0.0
    put_prem = puts[puts["exit_reason"] == "put_premium"]["pnl_usd"].sum() if not puts.empty else 0.0
    put_pay  = puts[puts["exit_reason"] == "put_payout"]["pnl_usd"].sum() if not puts.empty else 0.0
    vxc_net  = vxc["pnl_usd"].sum() if not vxc.empty else 0.0
    vxc_prem = vxc[vxc["exit_reason"] == "vix_call_premium"]["pnl_usd"].sum() if not vxc.empty else 0.0
    vxc_pay  = vxc[vxc["exit_reason"] == "vix_call_payout"]["pnl_usd"].sum() if not vxc.empty else 0.0

    return {
        "test": name,
        # MR-only (matches original reference methodology)
        "cagr_pct": mr_metrics["cagr_pct"],
        "sharpe_ratio": mr_metrics["sharpe_ratio"],
        "win_rate_pct": mr_metrics["win_rate_pct"],
        "profit_factor": mr_metrics["profit_factor"],
        "total_trades": mr_metrics["total_trades"],
        # Combined equity (true portfolio experience)
        "final_equity_combined": comb["final_equity_combined"],
        "max_drawdown_combined_pct": comb["max_drawdown_combined_pct"],
        "equity_curve": comb["equity_curve"],  # DataFrame — saved separately
        # Overlay breakdown
        "put_net": round(put_net, 2), "put_prem": round(put_prem, 2), "put_pay": round(put_pay, 2),
        "vxc_net": round(vxc_net, 2), "vxc_prem": round(vxc_prem, 2), "vxc_pay": round(vxc_pay, 2),
        "year_stats": mr_metrics.get("year_stats", {}),
    }


def _print_table(results):
    BL_EQ  = 9_915_308
    BL_DD  = -60.89   # MR-only MaxDD from original V47+I3 (for reference)
    BL_CAGR = 22.40

    # Baseline from our reproduced run (combined equity)
    bl = next((r for r in results if "Baseline" in r.get("test", "")), None)
    bl_eq_comb  = bl["final_equity_combined"] if bl else BL_EQ
    bl_dd_comb  = bl["max_drawdown_combined_pct"] if bl else BL_DD
    bl_cagr     = bl["cagr_pct"] if bl else BL_CAGR

    W = 130
    print("\n" + "="*W)
    print(f" IDEAS V7.2 — Combined Equity MaxDD | Reference V47+I3: ${BL_EQ:,.0f} | "
          f"CAGR {BL_CAGR}% | MaxDD {BL_DD}% (MR-only)")
    print(f" Reproduced baseline (combined): ${bl_eq_comb:,.0f} | "
          f"MaxDD {bl_dd_comb:.2f}% | CAGR {bl_cagr:.2f}%")
    print("="*W)
    print(f"{'Test':<26} {'CAGR%':>8} {'dCAGR':>9} {'Equity (comb)':>15} {'dEquity':>13} "
          f"{'MaxDD% (comb)':>14} {'dDD':>9} {'Sharpe':>8} {'WR%':>7} {'PF':>6}")
    print("-"*W)

    for r in results:
        if "error" in r:
            print(f"{r['test']:<26}  ERROR: {r['error']}")
            continue
        dc   = r["cagr_pct"] - bl_cagr
        de   = r["final_equity_combined"] - bl_eq_comb
        ddd  = r["max_drawdown_combined_pct"] - bl_dd_comb
        star = "★" if (ddd > 0 and "Baseline" not in r["test"]) else " "
        print(f"{star}{r['test']:<25} {r['cagr_pct']:>8.2f} {dc:>+9.2f}pp "
              f"${r['final_equity_combined']:>14,.0f} ${de:>+12,.0f} "
              f"{r['max_drawdown_combined_pct']:>14.2f} {ddd:>+9.2f}pp "
              f"{r['sharpe_ratio']:>8.2f} {r['win_rate_pct']:>7.2f} {r['profit_factor']:>6.2f}")

    print("="*W)
    print(" ★ = MaxDD improved vs reproduced baseline (combined equity). "
          "dDD > 0 = less negative = better.")
    print(" MaxDD = computed on COMBINED equity curve (MR P&L + put payouts + VIX call payouts).")
    print(" CAGR  = MR-only (matches original V47+I3 reference methodology).")
    print("="*W)

    print("\n Overlay P&L Breakdown:")
    print(f"{'Test':<26} {'Put Net':>12} {'Put Prem':>12} {'Put Pay':>12} "
          f"{'VXC Net':>12} {'VXC Prem':>10} {'VXC Pay':>10}")
    print("-"*94)
    for r in results:
        if "error" in r: continue
        print(f"{r['test']:<26} ${r['put_net']:>11,.0f} ${r['put_prem']:>11,.0f} "
              f"${r['put_pay']:>11,.0f} ${r['vxc_net']:>11,.0f} "
              f"${r['vxc_prem']:>9,.0f} ${r['vxc_pay']:>9,.0f}")
    print("="*94)


# ===========================================================================
# MAIN
# ===========================================================================

def main():
    print("\n" + "="*70)
    print(" IDEAS V7.2 — Combined equity MaxDD + CDaR retune + equity curves")
    print(" Reference: V47+I3 = $9,915,308 | CAGR 22.40% | MaxDD -60.89% (MR-only)")
    print("="*70)

    universe    = get_universe()
    price_data  = download_prices(universe)
    spy_df, vix_df, sector_data = download_reference_data()
    earnings_map = build_earnings_dates(list(price_data.keys()))
    vvix_df     = _dl_vvix()

    tests = [
        ("Baseline V47+I3",  lambda: run_baseline(price_data, spy_df, vix_df, sector_data, earnings_map)),
        ("Idea_A VIX calls", lambda: run_idea_a(price_data, spy_df, vix_df, sector_data, earnings_map)),
        ("Idea_B CDaR",      lambda: run_idea_b(price_data, spy_df, vix_df, sector_data, earnings_map)),
        ("Idea_B2 CDaR comb",lambda: run_idea_b2(price_data, spy_df, vix_df, sector_data, earnings_map)),
        ("Idea_C VVIX",      lambda: run_idea_c(price_data, spy_df, vix_df, sector_data, earnings_map, vvix_df)),
        ("Idea_D Dyn strike",lambda: run_idea_d(price_data, spy_df, vix_df, sector_data, earnings_map)),
        ("Idea_E Gap regime",lambda: run_idea_e(price_data, spy_df, vix_df, sector_data, earnings_map)),
        ("Idea_G D+A combo", lambda: run_idea_g(price_data, spy_df, vix_df, sector_data, earnings_map)),
    ]

    results = []
    eq_curves = {}

    for name, fn in tests:
        print(f"\n{'─'*50}\nRunning: {name}")
        try:
            t = fn()
            fname = name.lower().replace(" ", "_").replace("+", "_")
            t.to_csv(OUTPUT_DIR / f"{fname}_trades.csv", index=False)
            r = _extract(t, name)
            # Save equity curve separately
            if "equity_curve" in r and not r["equity_curve"].empty:
                eq_df = r["equity_curve"]
                eq_df.to_csv(OUTPUT_DIR / f"{fname}_equity_curve.csv", index=False)
                eq_curves[name] = eq_df
            r_out = {k: v for k, v in r.items() if k != "equity_curve"}
            results.append(r_out)
            results[-1]["equity_curve_saved"] = f"{fname}_equity_curve.csv"
            if "error" not in r_out:
                print(f"  → CAGR {r_out['cagr_pct']:.2f}% | "
                      f"Equity ${r_out['final_equity_combined']:,.0f} | "
                      f"MaxDD {r_out['max_drawdown_combined_pct']:.2f}% (combined)")
        except Exception as e:
            print(f"  [ERROR] {name}: {e}")
            import traceback; traceback.print_exc()
            results.append({"test": name, "error": str(e)})

    _print_table(results)

    # Save comparison CSV for charting equity curves
    if eq_curves:
        # Merge all equity curves into one wide CSV: date + one column per test
        # Resample to monthly for readability
        merged = None
        for name, eq in eq_curves.items():
            col = name.replace(" ", "_")
            eq_dt = eq.copy()
            eq_dt["date"] = pd.to_datetime(eq_dt["date"])
            eq_dt = eq_dt.set_index("date")[["equity"]].rename(columns={"equity": col})
            eq_monthly = eq_dt.resample("ME").last()
            if merged is None:
                merged = eq_monthly
            else:
                merged = merged.join(eq_monthly, how="outer")
        if merged is not None:
            merged = merged.ffill()
            merged.to_csv(OUTPUT_DIR / "all_equity_curves_monthly.csv")
            print(f"\n Monthly equity curves (all tests): "
                  f"{OUTPUT_DIR}/all_equity_curves_monthly.csv")
            print(f" Share this file to plot combined equity curves for each idea.")

    # Save summary JSON
    summary = {
        "run_date": datetime.date.today().isoformat(),
        "version": "V7.2",
        "key_change": "MaxDD now computed on combined equity (MR + all overlays)",
        "baseline_reference_original": {
            "strategy": "V47+I3 full history April 2026",
            "final_equity": 9_915_308, "cagr_pct": 22.40,
            "max_drawdown_pct_mr_only": -60.89,
        },
        "parameters": {
            "cdar": {"target": CDAR_TARGET, "min_scale": CDAR_MIN_SCALE,
                     "window": CDAR_WINDOW, "confidence": CDAR_CONF},
            "vix_call": {"cost_pct_monthly": VIX_CALL_COST_PCT,
                         "lower": VIX_CALL_LOWER, "upper": VIX_CALL_UPPER,
                         "max_mult": VIX_CALL_MAX_MULT, "renew_days": VIX_CALL_RENEW_DAYS},
            "dynamic_put_strikes": {"vix_lt_15": "3%/13%", "vix_15_25": "5%/15%",
                                     "vix_gt_25": "8%/20%"},
            "gap_behavior": {"window": GAP_BEH_WIN, "threshold": GAP_BEH_THOLD,
                             "mult": GAP_BEH_MULT},
            "vvix": {"mod_thresh": VVIX_MOD, "ext_thresh": VVIX_EXT,
                     "mod_mult": VVIX_MOD_MULT, "ext_mult": VVIX_EXT_MULT},
        },
        "results": results,
    }
    with open(OUTPUT_DIR / "ideas_v7_2_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\n All outputs → {OUTPUT_DIR.resolve()}")
    print(f" Share back: paste the IDEAS V7.2 table + overlay breakdown above.")
    print(f" Equity curves: results_ideas_v7_2/all_equity_curves_monthly.csv")


if __name__ == "__main__":
    main()
