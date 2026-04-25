# backtest_ideas_v7_4.py
#
# Ideas V7.4 — Six new ideas tested against V7.3 baseline
#
# Baseline: V7.3 combined equity
#   $23,116,132 | CAGR 27.64% (combined) | MaxDD -52.22% | Sharpe 0.97
#
# Ideas tested (all against V7.3 baseline = Idea G + GOLD + SECROT):
#
#   Idea_H — Convexity-Adjusted Exit: profit target scales by days held
#             Days 1-3: 1.5% target | Days 4-6: 2.0% (standard) | Days 7-8: 1.0%
#             Not in DNR: DNR has Idea_F (day-5 partial trigger on exit);
#             this is continuous target scaling across all days, not a binary trigger.
#
#   Idea_I — TLT Bear Regime Overlay: long TLT (8% alloc) when SPY below 200d MA
#             AND TLT above its 50d MA. Exits when SPY re-enters bull OR TLT breaks 50d.
#             Not in DNR: DNR "bond allocation in bear" was MR-signal-based IEF trades.
#             This is a pure trend-follow on TLT activated only in MR's dead zone.
#
#   Idea_J — QQQ/IWM Factor Rotation: monthly, long whichever of QQQ or IWM has
#             stronger 3-month momentum. 6% allocation, bull regime only.
#             Not in DNR: SECROT rotates among 11 sectors; this rotates between
#             market cap/style factors (growth vs value) — different signal dimension.
#
#   Idea_K — VIX Call Size Scaling: double VIX call allocation (0.3% → 0.6%) when
#             VIX term structure is in backwardation (VIX > VIX3M = stress regime).
#             Not in DNR: no dynamic sizing of the VIX call has ever been tested.
#             The existing call is fixed-size; this scales it in stressed periods.
#
#   Idea_L — DBC Commodity Tilt on SECROT: when DBC 63d momentum > 5%, replace
#             2 of 3 SECROT sectors with XLE + XLB (commodity-sensitive sectors).
#             Not in DNR: SECROT parameter change within existing framework,
#             not a new overlay. Targets 2021-2022 inflation regime underperformance.
#
#   Idea_M — Tier 1 Extended Sizing: when consec_down >= 6 AND RSI(2) < 10 AND
#             gap < 0.5%, raise hard cap from 12% to 15% for that specific entry.
#             Not in DNR: all DNR sizing was portfolio-level or regime-based.
#             This is signal-quality-specific sizing for the rarest, best-performing tier.
#
# All MaxDD computed on COMBINED equity (MR + all overlays simultaneously).
# All ideas import from backtest_nmr_lib_v47.py — same engine, zero reimplementation.
#
# Run: python backtest_ideas_v7_4.py
# GitHub Actions: ideas_v7_4_backtest.yml

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

OUTPUT_DIR = Path("results_ideas_v7_4")
OUTPUT_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# V7.3 baseline overlay parameters (Idea G + GOLD + SECROT)
# All ideas inherit these — unchanged unless the idea specifically modifies one
# ---------------------------------------------------------------------------

# Idea G: SPY put spread
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
    if vix < 15.0:  return 0.03, 0.13
    if vix <= 25.0: return 0.05, 0.15
    return 0.08, 0.20

# Idea G: VIX call spread (standard sizing)
VIX_CALL_COST_PCT_BASE = 0.003
VIX_CALL_LOWER      = 20.0
VIX_CALL_UPPER      = 40.0
VIX_CALL_RENEW_DAYS = 21
VIX_CALL_MAX_MULT   = 8.0

def _vix_call_mult(vix_ref, vix_peak):
    peak = max(vix_ref, vix_peak)
    if peak <= VIX_CALL_LOWER: return 0.0
    above = min(peak - VIX_CALL_LOWER, VIX_CALL_UPPER - VIX_CALL_LOWER)
    return (above / (VIX_CALL_UPPER - VIX_CALL_LOWER)) * VIX_CALL_MAX_MULT

# GOLD overlay
GOLD_ALLOC_PCT = 0.07

# SECROT overlay
SECROT_ALLOC_PCT = 0.03
SECROT_TOP_N     = 3
SECROT_MOM_DAYS  = 63
SPDR_SECTORS     = ["XLK","XLV","XLF","XLE","XLI","XLY","XLP","XLU","XLB","XLRE","XLC"]

# Idea_I: TLT bear overlay
TLT_ALLOC_PCT    = 0.08
TLT_TREND_WINDOW = 50   # TLT must be above 50d MA

# Idea_J: QQQ/IWM factor rotation
FACTOR_ALLOC_PCT = 0.06
FACTOR_MOM_DAYS  = 63

# Idea_K: VIX call scaling in backwardation
VIX_CALL_COST_BACKWARDATION = 0.006  # 2x when VIX > VIX3M

# Idea_L: DBC commodity tilt threshold
DBC_TILT_THRESHOLD = 0.05   # DBC 63d momentum > 5% triggers tilt
DBC_MOM_DAYS       = 63

# Idea_M: Tier 1 extended sizing
TIER1_EXTENDED_RSI_THRESH = 10.0    # RSI(2) < 10 for extended sizing
TIER1_EXTENDED_GAP_THRESH = 0.005   # gap < 0.5%
TIER1_EXTENDED_HARD_CAP   = 0.15    # raise from 12% to 15%
TIER1_EXTENDED_MIN_DOWN   = 6       # 6+ consecutive down days

# ---------------------------------------------------------------------------
# Reference V7.3 baseline results
# ---------------------------------------------------------------------------
V73_FINAL_EQ  = 23_116_132
V73_CAGR      = 27.64   # combined
V73_MAXDD     = -52.22
V73_SHARPE    = 0.97

# ---------------------------------------------------------------------------
# Download overlay price data (used by all ideas)
# ---------------------------------------------------------------------------
def download_overlay_data():
    tickers = ["GLD","TLT","QQQ","IWM","DBC","SPY","^VIX","^VIX3M"] + SPDR_SECTORS
    print(f"\n[Overlays] Downloading: {tickers} ...")
    raw = yf.download(tickers, start=START_DATE, end=END_DATE,
                      auto_adjust=True, progress=False, threads=True)
    px = {}
    if isinstance(raw.columns, pd.MultiIndex):
        for t in tickers:
            try:
                s = raw["Close"][t].dropna()
                if not s.empty: px[t] = s
            except Exception: pass
    print(f"[Overlays] Downloaded: {sorted(px.keys())}")
    return px

# ---------------------------------------------------------------------------
# Combined equity curve + metrics (identical to V7.2/V7.3)
# ---------------------------------------------------------------------------
def _combined_metrics(trades_df: pd.DataFrame) -> dict:
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
        return {"final_equity_combined": INITIAL_CAPITAL,
                "max_drawdown_combined_pct": 0.0, "equity_curve": eq,
                "cagr_combined_pct": 0.0, "sharpe_combined": 0.0}
    eq["peak"]         = eq["equity"].cummax()
    eq["drawdown_pct"] = (eq["equity"] - eq["peak"]) / eq["peak"] * 100.0
    start = pd.to_datetime(df["entry_date"].min())
    end   = pd.to_datetime(df["exit_date"].max())
    years = max((end - start).days / 365.25, 1e-6)
    cagr  = (eq["equity"].iloc[-1] / INITIAL_CAPITAL) ** (1 / years) - 1
    eq_s  = eq.set_index("date")["equity"]
    monthly = eq_s.resample("ME").last().ffill().pct_change().dropna()
    sharpe  = (monthly.mean() / monthly.std() * np.sqrt(12)
               if monthly.std() > 0 else 0)
    return {
        "final_equity_combined":     round(float(eq["equity"].iloc[-1]), 2),
        "max_drawdown_combined_pct": round(float(eq["drawdown_pct"].min()), 2),
        "cagr_combined_pct":         round(cagr * 100, 2),
        "sharpe_combined":           round(sharpe, 2),
        "equity_curve":              eq,
    }

# ---------------------------------------------------------------------------
# Shared helpers (identical to V7.2)
# ---------------------------------------------------------------------------
def _init_signals(price_data):
    signals = {}
    min_bars = MA_WINDOW + VOL_MA_PERIOD + ATR_PERIOD + MIN_CONSEC_DOWN + 5
    for tkr, df in price_data.items():
        if len(df) > min_bars:
            signals[tkr] = generate_signals(df)
    return signals

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

def _run_exits(today, signals, open_pos, trades, pv, cool, idea_h=False):
    """Standard exit loop. If idea_h=True, uses day-scaled profit targets."""
    to_close = []
    for tkr, pos in open_pos.items():
        if tkr not in signals or today not in signals[tkr].index: continue
        row = signals[tkr].loc[today]
        ep  = pos["entry_price"]; xp = float(row["Close"])
        dh  = (pd.Timestamp(today) - pd.Timestamp(pos["entry_date"])).days
        pp  = (xp - ep) / ep
        sr  = pos["shares_remaining"]
        early = dh < MIN_HOLD_BEFORE_EXIT

        # Idea_H: scale profit target by days held
        if idea_h:
            if dh <= 3:
                effective_target = 0.015    # exit earlier on fast reversals
            elif dh <= 6:
                effective_target = pos["profit_target"]  # standard
            else:
                effective_target = 0.010    # take what's there near time stop
        else:
            effective_target = pos["profit_target"]

        ts = dh >= pos["hold_days"]
        ph = (not early) and pp >= effective_target

        if (pos["partial_enabled"] and not pos["partial_done"]
                and not early and pp >= pos["partial_trigger"]):
            psh = sr * pos["partial_frac"]
            cm  = calc_commission(psh, xp)
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
            cm  = calc_commission(sr, xp)
            pnl = (xp - ep) * sr - cm - pos["entry_commission"]
            rsn = "time_stop" if ts else "profit_target"
            trades.append({"ticker": tkr, "entry_date": pos["entry_date"],
                "exit_date": today, "entry_price": ep, "exit_price": xp,
                "shares": sr, "commission": round(cm + pos["entry_commission"], 4),
                "pnl_usd": pnl, "pnl_pct": pp * 100, "days_held": dh,
                "exit_reason": rsn, "tier": pos["tier"],
                "consec_down": pos["consec_down_at_entry"],
                "portfolio_val": pv + pnl})
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

def _enter(today, signals, cands, open_pos, cool, pv, vix_df, dd, tom_today, dow,
           idea_m=False):
    """Standard entry loop. If idea_m=True, applies extended sizing for Tier 1 ultra-signals."""
    n = len(cands); top_n = max(1, int(n * TOP_SIGNAL_PCT))
    for rank, (score, tkr, cv, rv) in enumerate(cands):
        if len(open_pos) >= MAX_POSITIONS: break
        tkr_df = signals[tkr]
        idx    = tkr_df.index.get_loc(today)
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

        # Idea_M: Tier 1 ultra-signal — extend hard cap
        hard_cap = TOP_SIGNAL_HARD_CAP
        if idea_m and cv >= TIER1_EXTENDED_MIN_DOWN and rv < TIER1_EXTENDED_RSI_THRESH:
            gap_abs = abs(gp)
            if gap_abs < TIER1_EXTENDED_GAP_THRESH:
                hard_cap = TIER1_EXTENDED_HARD_CAP  # 15% instead of 12%

        tier = get_tier(cv)
        size = get_position_size(today, vix_df, dd, multiplier=sm, hard_cap=hard_cap)
        sh   = (pv * size) / ep
        ec   = calc_commission(sh, ep)
        open_pos[tkr] = {
            "entry_date":           tkr_df.index[idx + 1],
            "entry_price":          ep,
            "shares":               sh,
            "shares_remaining":     sh,
            "rsi2_at_entry":        rv,
            "consec_down_at_entry": cv,
            "profit_target":        tier["profit_target"],
            "hold_days":            tier["hold_days"],
            "partial_enabled":      tier["partial_enabled"],
            "partial_frac":         tier["partial_frac"],
            "partial_trigger":      tier["partial_trigger"],
            "partial_done":         False,
            "tier":                 tier["tier"],
            "entry_commission":     ec,
        }

# ---------------------------------------------------------------------------
# SPY put spread tick — inline (same as V7.2/V7.3)
# ---------------------------------------------------------------------------
def _put_tick(today, spy_df, spy_close, pv, trades, pr, prd, pn, pms, pds, alo, ahi,
              vix_df=None):
    if today not in spy_df.index: return pv, pr, prd, pn, pms, pds, alo, ahi
    spx = float(spy_close.loc[today]) if today in spy_close.index else None
    if spx is None: return pv, pr, prd, pn, pms, pds, alo, ahi
    if pr is None or pds >= PUT_SPREAD_RENEW_DAYS:
        alo, ahi = _get_put_strikes(get_vix_level(today, vix_df) if vix_df is not None else 20.0)
        prem = pv * PUT_SPREAD_COST_PCT; pv -= prem
        pr = spx; prd = today; pn = pv; pms = spx; pds = 0
        trades.append({"ticker": "SPY_PUT_SPREAD", "entry_date": today, "exit_date": today,
            "entry_price": spx, "exit_price": spx, "shares": 0, "commission": 0,
            "pnl_usd": -prem, "pnl_pct": -PUT_SPREAD_COST_PCT * 100, "days_held": 0,
            "exit_reason": "put_premium", "tier": 0, "consec_down": 0, "portfolio_val": pv})
    else:
        pds += 1; pms = min(pms, spx)
        if pds == PUT_SPREAD_RENEW_DAYS - 1:
            pay_pct = _put_payout(pr, pms, alo, ahi)
            if pay_pct > 0:
                pay = pn * pay_pct; pv += pay
                trades.append({"ticker": "SPY_PUT_SPREAD", "entry_date": prd, "exit_date": today,
                    "entry_price": pr, "exit_price": pms, "shares": 0, "commission": 0,
                    "pnl_usd": round(pay, 2), "pnl_pct": round(pay_pct * 100, 4), "days_held": pds,
                    "exit_reason": "put_payout", "tier": 0, "consec_down": 0, "portfolio_val": pv})
    return pv, pr, prd, pn, pms, pds, alo, ahi

# ---------------------------------------------------------------------------
# VIX call spread tick — with optional Idea_K scaling
# ---------------------------------------------------------------------------
def _vxc_tick(today, vix_df, vix_close, pv, trades, vd, vr, vrd, vn, vpk, vpm,
               idea_k=False, ovl_px=None):
    """If idea_k=True, doubles allocation when VIX > VIX3M (backwardation)."""
    if today not in vix_df.index: return pv, vd, vr, vrd, vn, vpk, vpm
    vpx = float(vix_close.loc[today]) if today in vix_close.index else None
    if vpx is None: return pv, vd, vr, vrd, vn, vpk, vpm

    # Idea_K: scale cost pct based on term structure
    if idea_k and ovl_px is not None and "^VIX3M" in ovl_px:
        vix3m_s = ovl_px["^VIX3M"]
        vix3m   = float(vix3m_s.loc[today]) if today in vix3m_s.index else vpx * 1.05
        in_backwardation = vpx > vix3m
        cost_pct = VIX_CALL_COST_BACKWARDATION if in_backwardation else VIX_CALL_COST_PCT_BASE
    else:
        cost_pct = VIX_CALL_COST_PCT_BASE

    if vr is None or vd >= VIX_CALL_RENEW_DAYS:
        prem = pv * cost_pct; pv -= prem
        vr = vpx; vrd = today; vn = pv; vpk = vpx; vpm = prem; vd = 0
        trades.append({"ticker": "VIX_CALL_SPREAD", "entry_date": today, "exit_date": today,
            "entry_price": vpx, "exit_price": vpx, "shares": 0, "commission": 0,
            "pnl_usd": -prem, "pnl_pct": -cost_pct * 100, "days_held": 0,
            "exit_reason": "vix_call_premium", "tier": 0, "consec_down": 0, "portfolio_val": pv})
    else:
        vd += 1; vpk = max(vpk, vpx)
        if vd == VIX_CALL_RENEW_DAYS - 1:
            mult = _vix_call_mult(vr, vpk)
            if mult > 0:
                pay = vpm * mult; pv += pay
                trades.append({"ticker": "VIX_CALL_SPREAD", "entry_date": vrd, "exit_date": today,
                    "entry_price": vr, "exit_price": vpk, "shares": 0, "commission": 0,
                    "pnl_usd": round(pay, 2), "pnl_pct": round(mult * cost_pct * 100, 4),
                    "days_held": vd, "exit_reason": "vix_call_payout", "tier": 0,
                    "consec_down": 0, "portfolio_val": pv})
    return pv, vd, vr, vrd, vn, vpk, vpm

# ---------------------------------------------------------------------------
# GOLD overlay tick (same as V7.3)
# ---------------------------------------------------------------------------
def _gold_tick(today, pv, trades, gold_in_pos, ovl_px):
    if "GLD" not in ovl_px or "TLT" not in ovl_px: return pv, gold_in_pos
    gld     = ovl_px["GLD"]
    tlt     = ovl_px["TLT"]
    if today not in gld.index: return pv, gold_in_pos
    gld_ma200 = float(gld.rolling(200).mean().loc[today]) if today in gld.index else np.nan
    tlt_slope = float(tlt.rolling(20).mean().diff(20).loc[today]) if today in tlt.index else np.nan
    if np.isnan(gld_ma200): return pv, gold_in_pos
    gld_price  = float(gld.loc[today])
    trend      = gld_price > gld_ma200
    carry      = np.isnan(tlt_slope) or tlt_slope >= 0
    was_in     = gold_in_pos
    if not was_in and trend and carry:
        gold_in_pos = True
    if was_in and not trend:
        gold_in_pos = False
    if gold_in_pos:
        gld_ret = float(gld.pct_change().loc[today]) if today in gld.index else 0.0
        if not np.isnan(gld_ret):
            pnl = gld_ret * pv * GOLD_ALLOC_PCT
            pv += pnl
            if abs(pnl) > 0.01:
                trades.append({"ticker": "OVL_GOLD", "entry_date": today, "exit_date": today,
                    "entry_price": gld_price, "exit_price": gld_price, "shares": 0,
                    "commission": 0, "pnl_usd": round(pnl, 4), "pnl_pct": gld_ret * 100,
                    "days_held": 1, "exit_reason": "gold_daily", "tier": 0,
                    "consec_down": 0, "portfolio_val": pv})
    return pv, gold_in_pos

# ---------------------------------------------------------------------------
# SECROT overlay tick — standard version (same as V7.3)
# ---------------------------------------------------------------------------
def _secrot_tick(today, pv, trades, secrot_weights, ovl_px, spy_above_ma200,
                 prev_secrot_mon, idea_l=False, dbc_tilt=False):
    """
    Standard SECROT. If idea_l=True and dbc_tilt=True, replaces 2 sectors with XLE+XLB.
    Returns (pv, secrot_weights, prev_secrot_mon)
    """
    available = [s for s in SPDR_SECTORS if s in ovl_px]
    mon = (pd.Timestamp(today).year, pd.Timestamp(today).month)

    if mon != prev_secrot_mon:
        prev_secrot_mon = mon
        secrot_weights = {s: 0.0 for s in available}
        if spy_above_ma200:
            if idea_l and dbc_tilt:
                # Commodity tilt: force XLE + XLB into top selection,
                # then fill remaining slot with top momentum sector
                forced = [s for s in ["XLE", "XLB"] if s in available]
                moms   = {s: float(ovl_px[s].pct_change(SECROT_MOM_DAYS).loc[today])
                          for s in available
                          if today in ovl_px[s].index and
                          not np.isnan(ovl_px[s].pct_change(SECROT_MOM_DAYS).loc[today])}
                remaining_top = [s for s in sorted(moms, key=moms.get, reverse=True)
                                 if s not in forced]
                selected = forced + remaining_top[:max(0, SECROT_TOP_N - len(forced))]
            else:
                moms = {s: float(ovl_px[s].pct_change(SECROT_MOM_DAYS).loc[today])
                        for s in available
                        if today in ovl_px[s].index and
                        not np.isnan(ovl_px[s].pct_change(SECROT_MOM_DAYS).loc[today])}
                selected = sorted(moms, key=moms.get, reverse=True)[:SECROT_TOP_N]
            for s in available:
                secrot_weights[s] = 1.0 if s in selected else 0.0

    if spy_above_ma200:
        for s in available:
            if secrot_weights.get(s, 0) == 0: continue
            if today not in ovl_px[s].index: continue
            ret = float(ovl_px[s].pct_change().loc[today])
            if np.isnan(ret): continue
            pnl = ret * pv * SECROT_ALLOC_PCT
            pv += pnl
            if abs(pnl) > 0.01:
                trades.append({"ticker": f"OVL_SECROT_{s}", "entry_date": today,
                    "exit_date": today, "entry_price": float(ovl_px[s].loc[today]),
                    "exit_price": float(ovl_px[s].loc[today]), "shares": 0, "commission": 0,
                    "pnl_usd": round(pnl, 4), "pnl_pct": ret * 100, "days_held": 1,
                    "exit_reason": "secrot_daily", "tier": 0, "consec_down": 0,
                    "portfolio_val": pv})

    return pv, secrot_weights, prev_secrot_mon

# ---------------------------------------------------------------------------
# TLT bear overlay tick (Idea_I)
# ---------------------------------------------------------------------------
def _tlt_tick(today, pv, trades, tlt_in_pos, ovl_px, spy_above_ma200):
    """Long TLT (8% alloc) when SPY below 200d MA AND TLT above its 50d MA."""
    if "TLT" not in ovl_px: return pv, tlt_in_pos
    tlt      = ovl_px["TLT"]
    if today not in tlt.index: return pv, tlt_in_pos
    tlt_price = float(tlt.loc[today])
    tlt_ma50  = tlt.rolling(TLT_TREND_WINDOW).mean()
    tlt_ma50v = float(tlt_ma50.loc[today]) if today in tlt_ma50.index else np.nan
    if np.isnan(tlt_ma50v): return pv, tlt_in_pos

    tlt_above = tlt_price > tlt_ma50v
    should_be_in = (not spy_above_ma200) and tlt_above

    if not tlt_in_pos and should_be_in:
        tlt_in_pos = True
    if tlt_in_pos and not should_be_in:
        tlt_in_pos = False

    if tlt_in_pos:
        tlt_ret = float(tlt.pct_change().loc[today]) if today in tlt.index else 0.0
        if not np.isnan(tlt_ret):
            pnl = tlt_ret * pv * TLT_ALLOC_PCT
            pv += pnl
            if abs(pnl) > 0.01:
                trades.append({"ticker": "OVL_TLT_BEAR", "entry_date": today, "exit_date": today,
                    "entry_price": tlt_price, "exit_price": tlt_price, "shares": 0,
                    "commission": 0, "pnl_usd": round(pnl, 4), "pnl_pct": tlt_ret * 100,
                    "days_held": 1, "exit_reason": "tlt_bear_daily", "tier": 0,
                    "consec_down": 0, "portfolio_val": pv})
    return pv, tlt_in_pos

# ---------------------------------------------------------------------------
# QQQ/IWM factor rotation tick (Idea_J)
# ---------------------------------------------------------------------------
def _factor_tick(today, pv, trades, factor_weights, ovl_px, spy_above_ma200,
                 prev_factor_mon):
    """Monthly factor rotation: long QQQ or IWM (whichever has stronger 3m momentum)."""
    if "QQQ" not in ovl_px or "IWM" not in ovl_px:
        return pv, factor_weights, prev_factor_mon

    mon = (pd.Timestamp(today).year, pd.Timestamp(today).month)
    if mon != prev_factor_mon:
        prev_factor_mon = mon
        factor_weights  = {"QQQ": 0.0, "IWM": 0.0}
        if spy_above_ma200:
            qqq_mom = float(ovl_px["QQQ"].pct_change(FACTOR_MOM_DAYS).loc[today]) \
                      if today in ovl_px["QQQ"].index else np.nan
            iwm_mom = float(ovl_px["IWM"].pct_change(FACTOR_MOM_DAYS).loc[today]) \
                      if today in ovl_px["IWM"].index else np.nan
            if not np.isnan(qqq_mom) and not np.isnan(iwm_mom):
                winner = "QQQ" if qqq_mom >= iwm_mom else "IWM"
                factor_weights[winner] = 1.0

    if spy_above_ma200:
        for etf, w in factor_weights.items():
            if w == 0 or today not in ovl_px[etf].index: continue
            ret = float(ovl_px[etf].pct_change().loc[today])
            if np.isnan(ret): continue
            pnl = ret * pv * FACTOR_ALLOC_PCT
            pv += pnl
            if abs(pnl) > 0.01:
                trades.append({"ticker": f"OVL_FACTOR_{etf}", "entry_date": today,
                    "exit_date": today, "entry_price": float(ovl_px[etf].loc[today]),
                    "exit_price": float(ovl_px[etf].loc[today]), "shares": 0, "commission": 0,
                    "pnl_usd": round(pnl, 4), "pnl_pct": ret * 100, "days_held": 1,
                    "exit_reason": "factor_daily", "tier": 0, "consec_down": 0,
                    "portfolio_val": pv})

    return pv, factor_weights, prev_factor_mon

# ---------------------------------------------------------------------------
# DBC contango/tilt helper (Idea_L)
# ---------------------------------------------------------------------------
def _dbc_tilt_active(today, ovl_px):
    """Returns True if DBC 63d momentum > DBC_TILT_THRESHOLD."""
    if "DBC" not in ovl_px or today not in ovl_px["DBC"].index:
        return False
    mom = ovl_px["DBC"].pct_change(DBC_MOM_DAYS).loc[today]
    return not np.isnan(mom) and float(mom) > DBC_TILT_THRESHOLD

# ===========================================================================
# CORE SIMULATION LOOP
# Parameterized for all 6 ideas — flags enable/disable each idea.
# V7.3 baseline = all flags False.
# ===========================================================================
def run_simulation(price_data, spy_df, vix_df, sector_data, earnings_map,
                   ovl_px, label,
                   idea_h=False, idea_i=False, idea_j=False,
                   idea_k=False, idea_l=False, idea_m=False):
    print(f"\n[{label}] Running...")

    all_dates = sorted(set().union(*[set(df.index) for df in price_data.values()]))
    tom_set   = build_tom_set(all_dates)
    min_bars  = MA_WINDOW + VOL_MA_PERIOD + ATR_PERIOD + MIN_CONSEC_DOWN + 5
    signals   = {t: generate_signals(df) for t, df in price_data.items() if len(df) > min_bars}

    spy_regime  = spy_df["spy_ok"].to_dict()
    spy_close   = spy_df["Close"].squeeze()
    spy_ma200_s = spy_df["Close"].squeeze().rolling(200).mean()
    vix_close   = vix_df["Close"].squeeze()

    pv   = INITIAL_CAPITAL
    peak = None; dd = 0.0
    open_pos = {}; trades = []; cool = {}
    last_vs = None; last_vc = None

    # Put spread state
    pr = None; prd = None; pn = 0.0; pms = 9999.0; pds = 0
    alo = PUT_SPREAD_LOWER_OTM; ahi = PUT_SPREAD_UPPER_OTM

    # VIX call state
    vd = 0; vr = None; vrd = None; vn = 0.0; vpk = 0.0; vpm = 0.0

    # GOLD state
    gold_in_pos = False

    # TLT bear state (Idea_I)
    tlt_in_pos = False

    # SECROT state
    secrot_weights  = {}
    prev_secrot_mon = None

    # Factor rotation state (Idea_J)
    factor_weights  = {"QQQ": 0.0, "IWM": 0.0}
    prev_factor_mon = None

    from tqdm import tqdm
    for today in tqdm(all_dates, desc=label):
        spy_ok = spy_regime.get(today, True)
        paused, last_vs = check_vix_spike(today, vix_df, last_vs)
        vel_paused, last_vc = _vel(today, spy_df, last_vc)
        peak_new, dd = _dd_upd(pv, peak)
        peak = peak_new if peak_new is not None else peak

        spy_ma200_today = spy_ma200_s.loc[today] if today in spy_ma200_s.index else np.nan
        spy_price_today = float(spy_close.loc[today]) if today in spy_close.index else np.nan
        spy_above_ma200 = (not np.isnan(spy_ma200_today) and
                           not np.isnan(spy_price_today) and
                           spy_price_today > spy_ma200_today)

        # ── SPY PUT SPREAD (dynamic strikes = Idea D, standard for all) ──────
        pv, pr, prd, pn, pms, pds, alo, ahi = _put_tick(
            today, spy_df, spy_close, pv, trades, pr, prd, pn, pms, pds, alo, ahi,
            vix_df=vix_df)

        # ── VIX CALL SPREAD (Idea_K: scaled in backwardation) ────────────────
        pv, vd, vr, vrd, vn, vpk, vpm = _vxc_tick(
            today, vix_df, vix_close, pv, trades, vd, vr, vrd, vn, vpk, vpm,
            idea_k=idea_k, ovl_px=ovl_px)

        # ── GOLD overlay ──────────────────────────────────────────────────────
        pv, gold_in_pos = _gold_tick(today, pv, trades, gold_in_pos, ovl_px)

        # ── TLT bear overlay (Idea_I) ─────────────────────────────────────────
        if idea_i:
            pv, tlt_in_pos = _tlt_tick(today, pv, trades, tlt_in_pos, ovl_px, spy_above_ma200)

        # ── SECROT overlay (with optional Idea_L DBC tilt) ───────────────────
        dbc_tilt = _dbc_tilt_active(today, ovl_px) if idea_l else False
        pv, secrot_weights, prev_secrot_mon = _secrot_tick(
            today, pv, trades, secrot_weights, ovl_px, spy_above_ma200,
            prev_secrot_mon, idea_l=idea_l, dbc_tilt=dbc_tilt)

        # ── QQQ/IWM factor rotation (Idea_J) ──────────────────────────────────
        if idea_j:
            pv, factor_weights, prev_factor_mon = _factor_tick(
                today, pv, trades, factor_weights, ovl_px, spy_above_ma200, prev_factor_mon)

        # ── MR EXITS (Idea_H: convexity-adjusted targets) ─────────────────────
        pv = _run_exits(today, signals, open_pos, trades, pv, cool, idea_h=idea_h)

        if not spy_ok or paused or vel_paused or len(open_pos) >= MAX_POSITIONS:
            continue

        # ── MR ENTRIES (Idea_M: extended sizing for Tier 1 ultra-signals) ─────
        vix_now   = get_vix_level(today, vix_df)
        tom_today = today in tom_set
        dow       = pd.Timestamp(today).dayofweek
        cands     = _build_cands(today, signals, open_pos, cool,
                                  earnings_map, sector_data, vix_now)
        _enter(today, signals, cands, open_pos, cool, pv, vix_df, dd,
               tom_today, dow, idea_m=idea_m)

    t_df = pd.DataFrame(trades)
    print(f"[{label}] {len(t_df)} records")
    return t_df

# ===========================================================================
# EXTRACT METRICS + REPORT
# ===========================================================================
def _extract(trades_df: pd.DataFrame, name: str) -> dict:
    overlay_tickers = {"SPY_PUT_SPREAD","VIX_CALL_SPREAD"}
    mr = trades_df[~trades_df["ticker"].isin(overlay_tickers) &
                   ~trades_df["ticker"].str.startswith("OVL_")].copy()
    puts = trades_df[trades_df["ticker"] == "SPY_PUT_SPREAD"]
    vxc  = trades_df[trades_df["ticker"] == "VIX_CALL_SPREAD"]
    gold = trades_df[trades_df["ticker"] == "OVL_GOLD"]
    tlt  = trades_df[trades_df["ticker"] == "OVL_TLT_BEAR"]
    sec  = trades_df[trades_df["ticker"].str.startswith("OVL_SECROT")]
    fac  = trades_df[trades_df["ticker"].str.startswith("OVL_FACTOR")]

    if mr.empty: return {"test": name, "error": "No MR trades"}

    mr_metrics, _ = compute_metrics(mr)
    comb          = _combined_metrics(trades_df)

    def s(df): return df["pnl_usd"].sum() if not df.empty else 0.0
    def sp(df, r): return df[df["exit_reason"]==r]["pnl_usd"].sum() if not df.empty else 0.0

    return {
        "test":                     name,
        "cagr_pct":                 mr_metrics["cagr_pct"],
        "sharpe_ratio":             mr_metrics["sharpe_ratio"],
        "win_rate_pct":             mr_metrics["win_rate_pct"],
        "profit_factor":            mr_metrics["profit_factor"],
        "total_trades":             mr_metrics["total_trades"],
        "final_equity_combined":    comb["final_equity_combined"],
        "max_drawdown_combined_pct":comb["max_drawdown_combined_pct"],
        "cagr_combined_pct":        comb["cagr_combined_pct"],
        "sharpe_combined":          comb["sharpe_combined"],
        "equity_curve":             comb["equity_curve"],
        "put_net":   round(s(puts), 2),
        "put_prem":  round(sp(puts,"put_premium"), 2),
        "put_pay":   round(sp(puts,"put_payout"), 2),
        "vxc_net":   round(s(vxc), 2),
        "vxc_prem":  round(sp(vxc,"vix_call_premium"), 2),
        "vxc_pay":   round(sp(vxc,"vix_call_payout"), 2),
        "gold_net":  round(s(gold), 2),
        "tlt_net":   round(s(tlt), 2),
        "secrot_net":round(s(sec), 2),
        "factor_net":round(s(fac), 2),
        "year_stats":mr_metrics.get("year_stats", {}),
    }

def _print_table(results):
    BL_EQ   = V73_FINAL_EQ
    BL_DD   = V73_MAXDD
    BL_CAGR = V73_CAGR

    W = 140
    print("\n" + "="*W)
    print(f" IDEAS V7.4 | Baseline V7.3: ${BL_EQ:,.0f} | "
          f"CAGR {BL_CAGR}% (combined) | MaxDD {BL_DD}%")
    print("="*W)
    hdr = (f"{'Test':<32} {'MR CAGR%':>9} {'Comb CAGR%':>11} {'dCombCAGR':>10} "
           f"{'Equity':>14} {'dEquity':>13} {'MaxDD%':>8} {'dDD':>8} "
           f"{'Sharpe':>7} {'WR%':>6} {'PF':>5}")
    print(hdr)
    print("-"*W)

    bl = next((r for r in results if "Baseline" in r.get("test","")), None)
    bl_eq   = bl["final_equity_combined"] if bl else BL_EQ
    bl_dd   = bl["max_drawdown_combined_pct"] if bl else BL_DD
    bl_cagr = bl["cagr_combined_pct"] if bl else BL_CAGR

    for r in results:
        if "error" in r:
            print(f"  {r['test']:<30} ERROR: {r['error']}")
            continue
        dc  = r["cagr_combined_pct"] - bl_cagr
        de  = r["final_equity_combined"] - bl_eq
        ddd = r["max_drawdown_combined_pct"] - bl_dd
        star = "★" if (ddd > 0 and "Baseline" not in r["test"]) else " "
        print(f"{star} {r['test']:<31} {r['cagr_pct']:>9.2f} {r['cagr_combined_pct']:>11.2f} "
              f"{dc:>+10.2f}pp ${r['final_equity_combined']:>13,.0f} ${de:>+12,.0f} "
              f"{r['max_drawdown_combined_pct']:>8.2f} {ddd:>+8.2f}pp "
              f"{r['sharpe_combined']:>7.2f} {r['win_rate_pct']:>6.2f} {r['profit_factor']:>5.2f}")

    print("="*W)
    print(" ★ = MaxDD improved vs V7.3 baseline (combined equity). dDD > 0 = less negative = better.")
    print(" Comb CAGR = combined equity CAGR (MR + all overlays). MR CAGR = MR-only basis.")

    print("\n Overlay P&L Breakdown (all-time):")
    print(f"{'Test':<32} {'SPY Put':>10} {'VIX Call':>10} {'GOLD':>10} "
          f"{'TLT Bear':>10} {'SECROT':>10} {'Factor':>10}")
    print("-"*94)
    for r in results:
        if "error" in r: continue
        print(f"  {r['test']:<30} ${r['put_net']:>9,.0f} ${r['vxc_net']:>9,.0f} "
              f"${r['gold_net']:>9,.0f} ${r['tlt_net']:>9,.0f} "
              f"${r['secrot_net']:>9,.0f} ${r['factor_net']:>9,.0f}")
    print("="*94)

# ===========================================================================
# MAIN
# ===========================================================================
def main():
    print("\n" + "="*70)
    print(" IDEAS V7.4 — Six ideas tested against V7.3 baseline")
    print(f" Baseline: ${V73_FINAL_EQ:,.0f} | CAGR {V73_CAGR}% | MaxDD {V73_MAXDD}%")
    print("="*70)

    universe     = get_universe()
    price_data   = download_prices(universe)
    spy_df, vix_df, sector_data = download_reference_data()
    earnings_map = build_earnings_dates(list(price_data.keys()))
    ovl_px       = download_overlay_data()

    tests = [
        # (label, idea_h, idea_i, idea_j, idea_k, idea_l, idea_m)
        ("Baseline V7.3",      False, False, False, False, False, False),
        ("Idea_H ConvexExit",  True,  False, False, False, False, False),
        ("Idea_I TLT Bear",    False, True,  False, False, False, False),
        ("Idea_J QQQ/IWM",     False, False, True,  False, False, False),
        ("Idea_K VIX ScaleUp", False, False, False, True,  False, False),
        ("Idea_L DBC Tilt",    False, False, False, False, True,  False),
        ("Idea_M Tier1 Size",  False, False, False, False, False, True),
        # Combined: best ideas together (add after seeing individual results)
        ("Ideas H+I+K",        True,  True,  False, True,  False, False),
        ("Ideas H+I+J+K",      True,  True,  True,  True,  False, False),
        ("All 6 combined",     True,  True,  True,  True,  True,  True),
    ]

    results    = []
    eq_curves  = {}

    for label, h, i, j, k, l, m in tests:
        print(f"\n{'─'*55}\nRunning: {label}")
        try:
            t_df = run_simulation(
                price_data, spy_df, vix_df, sector_data, earnings_map,
                ovl_px, label,
                idea_h=h, idea_i=i, idea_j=j,
                idea_k=k, idea_l=l, idea_m=m)

            fname = label.lower().replace(" ","_").replace("/","_").replace("+","_")
            t_df.to_csv(OUTPUT_DIR / f"{fname}_trades.csv", index=False)

            r = _extract(t_df, label)
            if "equity_curve" in r and not r["equity_curve"].empty:
                r["equity_curve"].to_csv(
                    OUTPUT_DIR / f"{fname}_equity_curve.csv", index=False)
                eq_curves[label] = r["equity_curve"]
            r_out = {k2: v for k2, v in r.items() if k2 != "equity_curve"}
            results.append(r_out)
            if "error" not in r_out:
                print(f"  → Comb CAGR {r_out['cagr_combined_pct']:.2f}% | "
                      f"Equity ${r_out['final_equity_combined']:,.0f} | "
                      f"MaxDD {r_out['max_drawdown_combined_pct']:.2f}%")
        except Exception as e:
            import traceback; traceback.print_exc()
            results.append({"test": label, "error": str(e),
                            "put_net":0,"vxc_net":0,"gold_net":0,
                            "tlt_net":0,"secrot_net":0,"factor_net":0})

    _print_table(results)

    # Monthly equity curve comparison
    if eq_curves:
        merged = None
        for name, eq in eq_curves.items():
            col  = name.replace(" ","_")
            eq_t = eq.copy()
            eq_t["date"] = pd.to_datetime(eq_t["date"])
            eq_m = eq_t.set_index("date")[["equity"]].rename(
                columns={"equity": col}).resample("ME").last()
            merged = eq_m if merged is None else merged.join(eq_m, how="outer")
        if merged is not None:
            merged.ffill().to_csv(OUTPUT_DIR / "all_equity_curves_monthly.csv")
            print(f"\n Monthly curves: {OUTPUT_DIR}/all_equity_curves_monthly.csv")

    summary = {
        "run_date": datetime.date.today().isoformat(),
        "version":  "V7.4",
        "baseline": {"strategy":"V7.3","final_equity":V73_FINAL_EQ,
                     "cagr_combined_pct":V73_CAGR,"max_drawdown_pct":V73_MAXDD},
        "ideas": {
            "H": "Convexity-adjusted exit: 1.5% d1-3, 2.0% d4-6, 1.0% d7-8",
            "I": "TLT bear overlay 8% alloc when SPY<200d MA + TLT>50d MA",
            "J": "QQQ/IWM factor rotation 6% monthly, bull regime only",
            "K": "VIX call 2x allocation (0.6%) when VIX > VIX3M (backwardation)",
            "L": "DBC commodity tilt on SECROT: force XLE+XLB when DBC mom>5%",
            "M": "Tier1 extended sizing to 15% hard cap for 6+day/RSI<10/gap<0.5%",
        },
        "results": [{k2:v for k2,v in r.items() if k2 not in ("equity_curve","year_stats")}
                    for r in results],
    }
    with open(OUTPUT_DIR / "ideas_v7_4_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\n All outputs → {OUTPUT_DIR.resolve()}")
    print(" Paste back: full table + overlay breakdown above.")


if __name__ == "__main__":
    main()
