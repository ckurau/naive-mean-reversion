# backtest_ideas_v7_5.py
#
# Ideas V7.5 — Seven new ideas tested against V7.4 baseline
#
# Baseline: V7.4 combined equity
#   $56,457,642 | CAGR 32.85% (combined) | MaxDD -57.17% | Sharpe 1.04
#
# Ideas (all vs V7.4 baseline = V7.3 + Idea_I + Idea_J + Idea_K):
#
#   Idea_N — PDBC Commodity Overlay
#             5% allocation in PDBC (diversified commodity ETF) when PDBC > 100d MA
#             AND DBC 3-month momentum > 0. Additive commodity exposure, no K-1.
#             Not in DNR: Idea_L tilted SECROT composition toward XLE/XLB. This adds
#             direct commodity ETF exposure independently. Never tested as standalone.
#
#   Idea_O — HYG/LQD Credit Carry Overlay
#             5% allocation in HYG when HYG/LQD ratio is rising (credit tightening,
#             risk-on credit). Exit when ratio turns down. Bull regime only (SPY>200d).
#             Not in DNR: all prior bond work was TLT/IEF (duration/rates). Credit
#             spread carry is orthogonal — harvests credit risk premium, not rate beta.
#
#   Idea_P — SPY Put Spread 4th Strike Bucket (VIX > 35: 8%/25% OTM)
#             Extends Idea_D's 3 VIX buckets to 4: when VIX > 35 (extreme fear),
#             use 8% long / 25% short OTM (wider than current 8%/20%). Pays out
#             deeper into the tail in catastrophic crashes (2008, 2020).
#             Not in DNR: Idea_D tested 3 buckets (<15, 15-25, >25). The >35
#             sub-bucket within >25 has never been tested — strictly additive.
#
#   Idea_Q — ZROZ Deflation/Panic Overlay
#             6% allocation in ZROZ (25yr zero-coupon Treasury, max duration) when
#             VIX > 20 AND TLT 5-day return > 0.5% (rates actively falling in panic).
#             Fires during acute panic events, not the entire bear regime like TLT Bear.
#             Not in DNR: TLT Bear fires on SPY<200d MA (bear regime). ZROZ fires on
#             VIX>20 + active rate rally — a much tighter, higher-intensity trigger.
#             Different instrument (max duration), different signal, different use case.
#
#   Idea_R — SPY OTM Call Overlay in Low-VIX Regime
#             0.2% of portfolio monthly to buy synthetic 30-DTE SPY call at 5% OTM
#             when VIX < 13 (cheapest options regime). Participates in bull melt-ups
#             when premiums are minimal. Never tested — all options work is puts/VIX.
#             Not in DNR: VRP harvest (selling puts) is DNR. This BUYS calls. Opposite.
#
#   Idea_S — DBMF Managed Futures Overlay
#             5% allocation in DBMF (iMGP DBi Managed Futures Strategy ETF, replicates
#             SG CTA trend index — goes long AND short across equity/bond/commodity/FX).
#             Not in DNR: V49 TSMOM used long-only ETF proxies (GLD, TLT, USO, UUP, DBC).
#             DBMF is a proper managed futures replicator (available 2019+, long+short).
#             For pre-2019, proxy via 60% TLT + 40% SH (inverse SPY) to approximate
#             the long-bond / short-equity bias typical of managed futures in crises.
#             DBMF returned +27% in 2022 — strongest structural MaxDD hedge.
#
#   Idea_T — USMV Late-Cycle Defensive Tilt
#             When VIX has been trending up for 10+ days (vol expansion, late bull cycle)
#             AND SPY still above 200d MA, replace SECROT allocation with equivalent
#             in USMV (iShares MSCI Min Volatility USA ETF). Exits when VIX trend
#             reverses OR SPY breaks 200d MA (SECROT resumes).
#             Not in DNR: SECROT uses sector momentum. USMV replaces it with a
#             min-volatility factor in a specific sub-regime. No min-vol factor tested.
#
# All MaxDD computed on COMBINED equity (MR + ALL overlays simultaneously).
# All ideas tested against the REPRODUCED V7.4 baseline (same run = fair comparison).
# Import from backtest_nmr_lib_v47.py — no reimplementation.
#
# Run: python backtest_ideas_v7_5.py
# GitHub Actions: ideas_v7_5_backtest.yml

import json
import warnings
import datetime
from pathlib import Path

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

OUTPUT_DIR = Path("results_ideas_v7_5")
OUTPUT_DIR.mkdir(exist_ok=True)

# ── V7.4 BASELINE REFERENCE ────────────────────────────────────────────────
V74_FINAL  = 56_457_642
V74_CAGR   = 32.85
V74_MAXDD  = -57.17
V74_SHARPE = 1.04

# ── V7.4 CARRY-OVER OVERLAY PARAMS (all unchanged) ────────────────────────
PUT_SPREAD_LOWER_OTM  = 0.05
PUT_SPREAD_UPPER_OTM  = 0.15
PUT_SPREAD_COST_PCT   = 0.0075
PUT_SPREAD_RENEW_DAYS = 63

def _get_put_strikes_v74(vix):
    """V7.4 dynamic strikes: 3 buckets."""
    if vix < 15.0:  return 0.03, 0.13
    if vix <= 25.0: return 0.05, 0.15
    return 0.08, 0.20

def _get_put_strikes_idea_p(vix):
    """Idea_P: 4th bucket — VIX > 35 → 8%/25% OTM (wider short strike)."""
    if vix < 15.0:  return 0.03, 0.13
    if vix <= 25.0: return 0.05, 0.15
    if vix <= 35.0: return 0.08, 0.20   # same as V7.4
    return 0.08, 0.25                    # NEW: VIX > 35 → extend short to 25% OTM

def _put_payout(spy_ref, spy_worst, lo, hi):
    if spy_worst >= spy_ref * (1 - lo): return 0.0
    return max(0.0, min((spy_ref - spy_worst) / spy_ref - lo, hi - lo))

VIX_CALL_COST_NORMAL        = 0.003
VIX_CALL_COST_BACKWARDATION = 0.006
VIX_CALL_LOWER      = 20.0
VIX_CALL_UPPER      = 40.0
VIX_CALL_RENEW_DAYS = 21
VIX_CALL_MAX_MULT   = 8.0

def _vix_call_mult(vix_ref, vix_peak):
    peak = max(vix_ref, vix_peak)
    if peak <= VIX_CALL_LOWER: return 0.0
    return (min(peak - VIX_CALL_LOWER, VIX_CALL_UPPER - VIX_CALL_LOWER) /
            (VIX_CALL_UPPER - VIX_CALL_LOWER)) * VIX_CALL_MAX_MULT

GOLD_ALLOC_PCT  = 0.07
TLT_ALLOC_PCT   = 0.08
TLT_MA_WINDOW   = 50
SECROT_ALLOC    = 0.03
SECROT_TOP_N    = 3
SECROT_MOM_DAYS = 63
FACTOR_ALLOC    = 0.06
FACTOR_MOM_DAYS = 63
SPDR_SECTORS    = ["XLK","XLV","XLF","XLE","XLI","XLY","XLP","XLU","XLB","XLRE","XLC"]

# ── V7.5 NEW OVERLAY PARAMS ────────────────────────────────────────────────
# Idea_N: PDBC commodity overlay
PDBC_ALLOC_PCT   = 0.05
PDBC_MA_WINDOW   = 100
DBC_MOM_DAYS     = 63

# Idea_O: HYG/LQD credit carry
HYG_ALLOC_PCT    = 0.05
HYG_RATIO_WINDOW = 20   # 20d MA of HYG/LQD ratio

# Idea_Q: ZROZ deflation/panic overlay
ZROZ_ALLOC_PCT   = 0.06
ZROZ_VIX_THRESH  = 20.0
ZROZ_TLT_5D_MIN  = 0.005   # TLT must be up >0.5% in 5 days

# Idea_R: SPY call in low-VIX
SPY_CALL_COST_PCT = 0.002   # 0.2% of portfolio per monthly call purchase
SPY_CALL_VIX_MAX  = 13.0   # only buy when VIX < 13
SPY_CALL_OTM      = 0.05   # 5% OTM call
# Synthetic call payout: if SPY gains > OTM level within 30d, earn 3× premium
SPY_CALL_RENEW_DAYS = 21

# Idea_S: DBMF managed futures
DBMF_ALLOC_PCT   = 0.05
# DBMF available from 2019; pre-2019 proxy = 0.6*TLT + 0.4*SH (SH = -1x SPY)
DBMF_PROXY_TLT   = 0.60
DBMF_PROXY_SH    = 0.40   # SH not in yfinance, use -1 * SPY return as proxy

# Idea_T: USMV late-cycle tilt
VIX_TREND_WINDOW = 10      # days of consecutive VIX rising
VIX_TREND_THRESH = 0.005   # each day VIX rises > 0.5% counts


# ── DOWNLOAD OVERLAY PRICES ────────────────────────────────────────────────
def download_overlay_data():
    tickers = (["GLD","TLT","QQQ","IWM","PDBC","DBC","HYG","LQD","ZROZ","DBMF",
                "USMV","SPY","^VIX","^VIX3M"] + SPDR_SECTORS)
    print(f"\n[Overlays] Downloading {len(tickers)} tickers ...")
    raw = yf.download(tickers, start=START_DATE, end=END_DATE,
                      auto_adjust=True, progress=False, threads=True)
    px = {}
    if isinstance(raw.columns, pd.MultiIndex):
        for t in tickers:
            try:
                s = raw["Close"][t].dropna()
                if not s.empty: px[t] = s
            except Exception: pass
    missing = [t for t in tickers if t not in px]
    if missing: print(f"[Overlays] Not available: {missing}")
    print(f"[Overlays] Got: {sorted(px.keys())}")
    return px


# ── COMBINED METRICS ───────────────────────────────────────────────────────
def _combined_metrics(trades_df):
    df = trades_df.copy()
    df["exit_date"] = pd.to_datetime(df["exit_date"])
    df = df.sort_values("exit_date").reset_index(drop=True)
    eq = INITIAL_CAPITAL
    rows = []
    for _, row in df.iterrows():
        eq += row["pnl_usd"]
        rows.append({"date": row["exit_date"], "equity": eq})
    eq_df = pd.DataFrame(rows)
    if eq_df.empty:
        return {"final_equity": INITIAL_CAPITAL, "max_dd": 0.0,
                "cagr": 0.0, "sharpe": 0.0, "equity_curve": eq_df}
    eq_df["peak"] = eq_df["equity"].cummax()
    eq_df["dd"]   = (eq_df["equity"] - eq_df["peak"]) / eq_df["peak"] * 100
    start = pd.to_datetime(df["entry_date"].min())
    end   = pd.to_datetime(df["exit_date"].max())
    yrs   = max((end - start).days / 365.25, 1e-6)
    cagr  = (eq_df["equity"].iloc[-1] / INITIAL_CAPITAL) ** (1 / yrs) - 1
    monthly = (eq_df.set_index("date")["equity"]
               .resample("ME").last().ffill().pct_change().dropna())
    sharpe  = (monthly.mean() / monthly.std() * np.sqrt(12)
               if monthly.std() > 0 else 0)
    return {
        "final_equity": round(float(eq_df["equity"].iloc[-1]), 2),
        "max_dd":       round(float(eq_df["dd"].min()), 2),
        "cagr":         round(cagr * 100, 2),
        "sharpe":       round(sharpe, 2),
        "equity_curve": eq_df,
    }


# ── SHARED MR HELPERS (identical to V7.4) ─────────────────────────────────
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

def _run_exits(today, signals, open_pos, trades, pv, cool):
    to_close = []
    for tkr, pos in open_pos.items():
        if tkr not in signals or today not in signals[tkr].index: continue
        row = signals[tkr].loc[today]
        ep = pos["entry_price"]; xp = float(row["Close"])
        dh = (pd.Timestamp(today) - pd.Timestamp(pos["entry_date"])).days
        pp = (xp - ep) / ep; sr = pos["shares_remaining"]
        early = dh < MIN_HOLD_BEFORE_EXIT
        ts = dh >= pos["hold_days"]
        ph = (not early) and pp >= pos["profit_target"]
        if (pos["partial_enabled"] and not pos["partial_done"]
                and not early and pp >= pos["partial_trigger"]):
            psh = sr * pos["partial_frac"]; cm = calc_commission(psh, xp)
            pnl = (xp - ep) * psh - cm
            trades.append({"ticker": tkr, "entry_date": pos["entry_date"],
                "exit_date": today, "entry_price": ep, "exit_price": xp,
                "shares": psh, "commission": round(cm, 4), "pnl_usd": pnl,
                "pnl_pct": pp * 100, "days_held": dh, "exit_reason": "partial_exit",
                "tier": pos["tier"], "consec_down": pos["consec_down_at_entry"],
                "portfolio_val": pv + pnl})
            pv += pnl; pos["shares_remaining"] -= psh
            pos["partial_done"] = True; pos["profit_target"] *= 2; continue
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
        cands.append((rsi2 / atr if atr > 0 else rsi2 * 1000, tkr,
                      int(row["consec_down"]), rsi2))
    return sorted(cands, key=lambda x: x[0])

def _enter(today, signals, cands, open_pos, cool, pv, vix_df, dd, tom_today, dow):
    n = len(cands); top_n = max(1, int(n * TOP_SIGNAL_PCT))
    for rank, (score, tkr, cv, rv) in enumerate(cands):
        if len(open_pos) >= MAX_POSITIONS: break
        tkr_df = signals[tkr]; idx = tkr_df.index.get_loc(today)
        if idx + 1 >= len(tkr_df): continue
        ep = float(tkr_df.iloc[idx + 1]["Open"])
        if ep <= 0: continue
        gp = (ep - float(tkr_df.iloc[idx]["Close"])) / float(tkr_df.iloc[idx]["Close"])
        if gp < GAP_DOWN_MAX or gp > GAP_UP_MAX: continue
        sm = 1.0
        if n >= MIN_CANDIDATES_FOR_C5 and rank < top_n: sm = TOP_SIGNAL_MULTIPLIER
        if tom_today: sm *= TOM_MULT
        sm *= DOW_MULT.get(dow, 1.0)
        tier = get_tier(cv)
        size = get_position_size(today, vix_df, dd, multiplier=sm, hard_cap=TOP_SIGNAL_HARD_CAP)
        sh = (pv * size) / ep; ec = calc_commission(sh, ep)
        open_pos[tkr] = {
            "entry_date": tkr_df.index[idx + 1], "entry_price": ep,
            "shares": sh, "shares_remaining": sh, "rsi2_at_entry": rv,
            "consec_down_at_entry": cv, "profit_target": tier["profit_target"],
            "hold_days": tier["hold_days"], "partial_enabled": tier["partial_enabled"],
            "partial_frac": tier["partial_frac"], "partial_trigger": tier["partial_trigger"],
            "partial_done": False, "tier": tier["tier"], "entry_commission": ec,
        }


# ── CARRY-OVER OVERLAY TICKS (V7.4 — unchanged) ────────────────────────────
def _put_tick(today, spy_df, spy_close, pv, trades, pr, prd, pn, pms, pds, alo, ahi,
              vix_df, use_idea_p=False):
    if today not in spy_df.index: return pv, pr, prd, pn, pms, pds, alo, ahi
    spx = float(spy_close.loc[today]) if today in spy_close.index else None
    if spx is None: return pv, pr, prd, pn, pms, pds, alo, ahi
    if pr is None or pds >= PUT_SPREAD_RENEW_DAYS:
        vix_now = get_vix_level(today, vix_df)
        alo, ahi = (_get_put_strikes_idea_p(vix_now) if use_idea_p
                    else _get_put_strikes_v74(vix_now))
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
                trades.append({"ticker": "SPY_PUT_SPREAD", "entry_date": prd,
                    "exit_date": today, "entry_price": pr, "exit_price": pms,
                    "shares": 0, "commission": 0, "pnl_usd": round(pay, 2),
                    "pnl_pct": round(pay_pct * 100, 4), "days_held": pds,
                    "exit_reason": "put_payout", "tier": 0, "consec_down": 0,
                    "portfolio_val": pv})
    return pv, pr, prd, pn, pms, pds, alo, ahi

def _vxc_tick(today, vix_df, vix_close, pv, trades, vd, vr, vrd, vn, vpk, vpm, ovl_px):
    if today not in vix_df.index: return pv, vd, vr, vrd, vn, vpk, vpm
    vpx = float(vix_close.loc[today]) if today in vix_close.index else None
    if vpx is None: return pv, vd, vr, vrd, vn, vpk, vpm
    cost_pct = VIX_CALL_COST_NORMAL
    if "^VIX3M" in ovl_px and today in ovl_px["^VIX3M"].index:
        vix3m = float(ovl_px["^VIX3M"].loc[today])
        if vpx > vix3m: cost_pct = VIX_CALL_COST_BACKWARDATION
    if vr is None or vd >= VIX_CALL_RENEW_DAYS:
        prem = pv * cost_pct; pv -= prem
        vr = vpx; vrd = today; vn = pv; vpk = vpx; vpm = prem; vd = 0
        trades.append({"ticker": "VIX_CALL_SPREAD", "entry_date": today, "exit_date": today,
            "entry_price": vpx, "exit_price": vpx, "shares": 0, "commission": 0,
            "pnl_usd": -prem, "pnl_pct": -cost_pct * 100, "days_held": 0,
            "exit_reason": "vix_call_premium", "tier": 0, "consec_down": 0,
            "portfolio_val": pv})
    else:
        vd += 1; vpk = max(vpk, vpx)
        if vd == VIX_CALL_RENEW_DAYS - 1:
            mult = _vix_call_mult(vr, vpk)
            if mult > 0:
                pay = vpm * mult; pv += pay
                trades.append({"ticker": "VIX_CALL_SPREAD", "entry_date": vrd,
                    "exit_date": today, "entry_price": vr, "exit_price": vpk,
                    "shares": 0, "commission": 0, "pnl_usd": round(pay, 2),
                    "pnl_pct": round(mult * cost_pct * 100, 4), "days_held": vd,
                    "exit_reason": "vix_call_payout", "tier": 0, "consec_down": 0,
                    "portfolio_val": pv})
    return pv, vd, vr, vrd, vn, vpk, vpm

def _gold_tick(today, pv, trades, in_pos, ovl_px):
    if "GLD" not in ovl_px or "TLT" not in ovl_px or today not in ovl_px["GLD"].index:
        return pv, in_pos
    gld = ovl_px["GLD"]; tlt = ovl_px["TLT"]
    ma200 = float(gld.rolling(200).mean().loc[today]) if today in gld.rolling(200).mean().index else np.nan
    if np.isnan(ma200): return pv, in_pos
    slope = float(tlt.rolling(20).mean().diff(20).loc[today]) if today in tlt.index else np.nan
    trend = float(gld.loc[today]) > ma200
    carry = np.isnan(slope) or slope >= 0
    if not in_pos and trend and carry: in_pos = True
    if in_pos and not trend: in_pos = False
    if in_pos:
        ret = float(gld.pct_change().loc[today]) if today in gld.index else 0.0
        if not np.isnan(ret):
            pnl = ret * pv * GOLD_ALLOC_PCT; pv += pnl
            if abs(pnl) > 0.01:
                trades.append({"ticker": "OVL_GOLD", "entry_date": today, "exit_date": today,
                    "entry_price": float(gld.loc[today]), "exit_price": float(gld.loc[today]),
                    "shares": 0, "commission": 0, "pnl_usd": round(pnl, 4),
                    "pnl_pct": ret * 100, "days_held": 1, "exit_reason": "gold_daily",
                    "tier": 0, "consec_down": 0, "portfolio_val": pv})
    return pv, in_pos

def _tlt_tick(today, pv, trades, in_pos, ovl_px, spy_above):
    if "TLT" not in ovl_px or today not in ovl_px["TLT"].index: return pv, in_pos
    tlt = ovl_px["TLT"]; price = float(tlt.loc[today])
    ma50 = tlt.rolling(TLT_MA_WINDOW).mean()
    ma50v = float(ma50.loc[today]) if today in ma50.index else np.nan
    if np.isnan(ma50v): return pv, in_pos
    should = (not spy_above) and price > ma50v
    if not in_pos and should: in_pos = True
    if in_pos and not should: in_pos = False
    if in_pos:
        ret = float(tlt.pct_change().loc[today]) if today in tlt.index else 0.0
        if not np.isnan(ret):
            pnl = ret * pv * TLT_ALLOC_PCT; pv += pnl
            if abs(pnl) > 0.01:
                trades.append({"ticker": "OVL_TLT_BEAR", "entry_date": today, "exit_date": today,
                    "entry_price": price, "exit_price": price, "shares": 0, "commission": 0,
                    "pnl_usd": round(pnl, 4), "pnl_pct": ret * 100, "days_held": 1,
                    "exit_reason": "tlt_bear_daily", "tier": 0, "consec_down": 0,
                    "portfolio_val": pv})
    return pv, in_pos

def _secrot_tick(today, pv, trades, weights, ovl_px, spy_above, prev_mon,
                 use_usmv=False, usmv_active=False):
    """SECROT or USMV (Idea_T) depending on flags."""
    available = [s for s in SPDR_SECTORS if s in ovl_px]
    mon = (pd.Timestamp(today).year, pd.Timestamp(today).month)
    if mon != prev_mon:
        prev_mon = mon; weights = {s: 0.0 for s in available}
        if spy_above:
            if use_usmv and usmv_active and "USMV" in ovl_px:
                # Idea_T: replace SECROT with USMV in late-cycle VIX expansion
                weights = {s: 0.0 for s in available}
            else:
                moms = {s: float(ovl_px[s].pct_change(SECROT_MOM_DAYS).loc[today])
                        for s in available if today in ovl_px[s].index and
                        not np.isnan(ovl_px[s].pct_change(SECROT_MOM_DAYS).loc[today])}
                top = sorted(moms, key=moms.get, reverse=True)[:SECROT_TOP_N]
                for s in available: weights[s] = 1.0 if s in top else 0.0
    if spy_above:
        if use_usmv and usmv_active and "USMV" in ovl_px:
            # Idea_T active: use USMV instead of sectors
            if today in ovl_px["USMV"].index:
                ret = float(ovl_px["USMV"].pct_change().loc[today])
                if not np.isnan(ret):
                    pnl = ret * pv * (SECROT_ALLOC * SECROT_TOP_N); pv += pnl
                    if abs(pnl) > 0.01:
                        trades.append({"ticker": "OVL_USMV", "entry_date": today,
                            "exit_date": today, "entry_price": float(ovl_px["USMV"].loc[today]),
                            "exit_price": float(ovl_px["USMV"].loc[today]), "shares": 0,
                            "commission": 0, "pnl_usd": round(pnl, 4), "pnl_pct": ret * 100,
                            "days_held": 1, "exit_reason": "usmv_daily",
                            "tier": 0, "consec_down": 0, "portfolio_val": pv})
        else:
            for s in available:
                if weights.get(s, 0) == 0 or today not in ovl_px[s].index: continue
                ret = float(ovl_px[s].pct_change().loc[today])
                if np.isnan(ret): continue
                pnl = ret * pv * SECROT_ALLOC; pv += pnl
                if abs(pnl) > 0.01:
                    trades.append({"ticker": f"OVL_SECROT_{s}", "entry_date": today,
                        "exit_date": today, "entry_price": float(ovl_px[s].loc[today]),
                        "exit_price": float(ovl_px[s].loc[today]), "shares": 0,
                        "commission": 0, "pnl_usd": round(pnl, 4), "pnl_pct": ret * 100,
                        "days_held": 1, "exit_reason": "secrot_daily",
                        "tier": 0, "consec_down": 0, "portfolio_val": pv})
    return pv, weights, prev_mon

def _factor_tick(today, pv, trades, fw, ovl_px, spy_above, prev_mon):
    if "QQQ" not in ovl_px or "IWM" not in ovl_px: return pv, fw, prev_mon
    mon = (pd.Timestamp(today).year, pd.Timestamp(today).month)
    if mon != prev_mon:
        prev_mon = mon; fw = {"QQQ": 0.0, "IWM": 0.0}
        if spy_above:
            qm = float(ovl_px["QQQ"].pct_change(FACTOR_MOM_DAYS).loc[today]) \
                 if today in ovl_px["QQQ"].index else np.nan
            im = float(ovl_px["IWM"].pct_change(FACTOR_MOM_DAYS).loc[today]) \
                 if today in ovl_px["IWM"].index else np.nan
            if not np.isnan(qm) and not np.isnan(im):
                fw["QQQ" if qm >= im else "IWM"] = 1.0
    if spy_above:
        for etf, w in fw.items():
            if w == 0 or today not in ovl_px[etf].index: continue
            ret = float(ovl_px[etf].pct_change().loc[today])
            if np.isnan(ret): continue
            pnl = ret * pv * FACTOR_ALLOC; pv += pnl
            if abs(pnl) > 0.01:
                trades.append({"ticker": f"OVL_FACTOR_{etf}", "entry_date": today,
                    "exit_date": today, "entry_price": float(ovl_px[etf].loc[today]),
                    "exit_price": float(ovl_px[etf].loc[today]), "shares": 0,
                    "commission": 0, "pnl_usd": round(pnl, 4), "pnl_pct": ret * 100,
                    "days_held": 1, "exit_reason": "factor_daily",
                    "tier": 0, "consec_down": 0, "portfolio_val": pv})
    return pv, fw, prev_mon


# ── NEW V7.5 OVERLAY TICKS ─────────────────────────────────────────────────
def _pdbc_tick(today, pv, trades, in_pos, ovl_px):
    """Idea_N: PDBC commodity overlay — 5% when PDBC > 100d MA + DBC momentum > 0."""
    # Use DBC as proxy if PDBC not available (similar diversified commodity)
    ticker = "PDBC" if "PDBC" in ovl_px else ("DBC" if "DBC" in ovl_px else None)
    if ticker is None or today not in ovl_px[ticker].index: return pv, in_pos
    s = ovl_px[ticker]
    price = float(s.loc[today])
    ma100 = float(s.rolling(PDBC_MA_WINDOW).mean().loc[today]) \
            if today in s.rolling(PDBC_MA_WINDOW).mean().index else np.nan
    if np.isnan(ma100): return pv, in_pos
    # DBC 3m momentum
    dbc_s = ovl_px.get("DBC", s)
    dbc_mom = float(dbc_s.pct_change(DBC_MOM_DAYS).loc[today]) \
              if today in dbc_s.index else np.nan
    trend = price > ma100
    mom_ok = np.isnan(dbc_mom) or dbc_mom > 0
    if not in_pos and trend and mom_ok: in_pos = True
    if in_pos and not (trend and mom_ok): in_pos = False
    if in_pos:
        ret = float(s.pct_change().loc[today]) if today in s.index else 0.0
        if not np.isnan(ret):
            pnl = ret * pv * PDBC_ALLOC_PCT; pv += pnl
            if abs(pnl) > 0.01:
                trades.append({"ticker": "OVL_PDBC", "entry_date": today,
                    "exit_date": today, "entry_price": price, "exit_price": price,
                    "shares": 0, "commission": 0, "pnl_usd": round(pnl, 4),
                    "pnl_pct": ret * 100, "days_held": 1, "exit_reason": "pdbc_daily",
                    "tier": 0, "consec_down": 0, "portfolio_val": pv})
    return pv, in_pos

def _hyg_tick(today, pv, trades, in_pos, ovl_px, spy_above):
    """Idea_O: HYG/LQD credit carry — 5% HYG when ratio rising + bull regime."""
    if not spy_above: return pv, False   # always exit in bear
    if "HYG" not in ovl_px or "LQD" not in ovl_px: return pv, in_pos
    if today not in ovl_px["HYG"].index or today not in ovl_px["LQD"].index:
        return pv, in_pos
    hyg = ovl_px["HYG"]; lqd = ovl_px["LQD"]
    ratio = hyg / lqd
    ratio_ma = ratio.rolling(HYG_RATIO_WINDOW).mean()
    if today not in ratio_ma.index or np.isnan(ratio_ma.loc[today]):
        return pv, in_pos
    # Rising ratio = credit tightening = risk-on credit environment
    ratio_now = float(ratio.loc[today])
    ratio_ma_now = float(ratio_ma.loc[today])
    signal_in = ratio_now > ratio_ma_now
    if not in_pos and signal_in: in_pos = True
    if in_pos and not signal_in: in_pos = False
    if in_pos:
        ret = float(hyg.pct_change().loc[today]) if today in hyg.index else 0.0
        if not np.isnan(ret):
            pnl = ret * pv * HYG_ALLOC_PCT; pv += pnl
            if abs(pnl) > 0.01:
                trades.append({"ticker": "OVL_HYG", "entry_date": today,
                    "exit_date": today, "entry_price": float(hyg.loc[today]),
                    "exit_price": float(hyg.loc[today]), "shares": 0, "commission": 0,
                    "pnl_usd": round(pnl, 4), "pnl_pct": ret * 100, "days_held": 1,
                    "exit_reason": "hyg_daily", "tier": 0, "consec_down": 0,
                    "portfolio_val": pv})
    return pv, in_pos

def _zroz_tick(today, pv, trades, in_pos, ovl_px, vix_value):
    """Idea_Q: ZROZ panic overlay — 6% when VIX>20 AND TLT actively rallying."""
    # ZROZ = 25yr zero-coupon. Proxy with TLT * 2.5 return if ZROZ unavailable
    ticker = "ZROZ" if "ZROZ" in ovl_px else ("TLT" if "TLT" in ovl_px else None)
    amp = 1.0 if ticker == "ZROZ" else 2.5   # TLT proxy amplified for duration
    if ticker is None or today not in ovl_px[ticker].index: return pv, in_pos
    s = ovl_px[ticker]
    # TLT 5-day return check (rates actively falling = flight to quality panic)
    tlt_s = ovl_px.get("TLT", s)
    tlt_5d = float(tlt_s.pct_change(5).loc[today]) \
             if today in tlt_s.index and len(tlt_s) >= 5 else np.nan
    vix_ok = vix_value > ZROZ_VIX_THRESH
    tlt_ok = not np.isnan(tlt_5d) and tlt_5d > ZROZ_TLT_5D_MIN
    signal_in = vix_ok and tlt_ok
    if not in_pos and signal_in: in_pos = True
    if in_pos and not vix_ok: in_pos = False   # exit when VIX normalizes
    if in_pos:
        ret = float(s.pct_change().loc[today]) if today in s.index else 0.0
        if not np.isnan(ret):
            pnl = ret * amp * pv * ZROZ_ALLOC_PCT; pv += pnl
            if abs(pnl) > 0.01:
                trades.append({"ticker": f"OVL_ZROZ", "entry_date": today,
                    "exit_date": today, "entry_price": float(s.loc[today]),
                    "exit_price": float(s.loc[today]), "shares": 0, "commission": 0,
                    "pnl_usd": round(pnl, 4), "pnl_pct": ret * amp * 100,
                    "days_held": 1, "exit_reason": "zroz_daily",
                    "tier": 0, "consec_down": 0, "portfolio_val": pv})
    return pv, in_pos

def _spy_call_tick(today, pv, trades, call_d, call_ref_pv, call_prem, call_entry_spy,
                   vix_value, ovl_px):
    """
    Idea_R: synthetic SPY call in low-VIX regime.
    Buy synthetic 30-DTE 5% OTM call for 0.2% of portfolio when VIX < 13.
    Payout: if SPY rises > 5% from entry price within 30 days → earn 4x premium.
    If SPY doesn't reach target within 30 days → lose premium paid.
    """
    if "SPY" not in ovl_px or today not in ovl_px["SPY"].index:
        return pv, call_d, call_ref_pv, call_prem, call_entry_spy
    spy_price = float(ovl_px["SPY"].loc[today])

    # Manage existing call position
    if call_prem > 0:
        call_d += 1
        # Check if target reached
        target_price = call_entry_spy * (1 + SPY_CALL_OTM)
        if spy_price >= target_price:
            # Payout: 4x premium (conservative BSM approximation)
            pay = call_prem * 4; pv += pay
            trades.append({"ticker": "OVL_SPY_CALL", "entry_date": today,
                "exit_date": today, "entry_price": call_entry_spy, "exit_price": spy_price,
                "shares": 0, "commission": 0, "pnl_usd": round(pay - call_prem, 2),
                "pnl_pct": 300.0, "days_held": call_d, "exit_reason": "call_payout",
                "tier": 0, "consec_down": 0, "portfolio_val": pv})
            call_prem = 0; call_d = 0; call_ref_pv = 0; call_entry_spy = 0
        elif call_d >= SPY_CALL_RENEW_DAYS:
            # Expired worthless — premium already deducted at purchase
            trades.append({"ticker": "OVL_SPY_CALL", "entry_date": today,
                "exit_date": today, "entry_price": call_entry_spy, "exit_price": spy_price,
                "shares": 0, "commission": 0, "pnl_usd": 0,
                "pnl_pct": -100.0, "days_held": call_d, "exit_reason": "call_expired",
                "tier": 0, "consec_down": 0, "portfolio_val": pv})
            call_prem = 0; call_d = 0; call_ref_pv = 0; call_entry_spy = 0

    # Open new call if VIX low and no active position
    if call_prem == 0 and vix_value < SPY_CALL_VIX_MAX:
        # Only open on first trading day of each month (matched to other monthly overlays)
        prem = pv * SPY_CALL_COST_PCT; pv -= prem
        call_prem = prem; call_d = 0; call_ref_pv = pv; call_entry_spy = spy_price
        trades.append({"ticker": "OVL_SPY_CALL", "entry_date": today, "exit_date": today,
            "entry_price": spy_price, "exit_price": spy_price, "shares": 0, "commission": 0,
            "pnl_usd": -prem, "pnl_pct": -SPY_CALL_COST_PCT * 100, "days_held": 0,
            "exit_reason": "call_premium", "tier": 0, "consec_down": 0, "portfolio_val": pv})

    return pv, call_d, call_ref_pv, call_prem, call_entry_spy

def _dbmf_tick(today, pv, trades, in_pos, ovl_px, spy_above):
    """
    Idea_S: DBMF managed futures overlay — 5% always (no regime filter,
    managed futures is intentionally uncorrelated to equity regimes).
    Pre-2019: proxy via TLT return * 0.6 + (-SPY return) * 0.4.
    Post-2019: use DBMF directly if available.
    """
    if today not in ovl_px.get("SPY", pd.Series()).index: return pv, in_pos
    # Check if DBMF is available for this date
    use_dbmf = "DBMF" in ovl_px and today in ovl_px["DBMF"].index
    if use_dbmf:
        ret = float(ovl_px["DBMF"].pct_change().loc[today])
    else:
        # Pre-DBMF proxy: 60% TLT + 40% short SPY (trend following crisis profile)
        tlt_ret = float(ovl_px["TLT"].pct_change().loc[today]) \
                  if "TLT" in ovl_px and today in ovl_px["TLT"].index else 0.0
        spy_ret = float(ovl_px["SPY"].pct_change().loc[today]) \
                  if today in ovl_px["SPY"].index else 0.0
        ret = DBMF_PROXY_TLT * tlt_ret + DBMF_PROXY_SH * (-spy_ret)
    if np.isnan(ret): return pv, in_pos
    pnl = ret * pv * DBMF_ALLOC_PCT; pv += pnl
    if abs(pnl) > 0.01:
        trades.append({"ticker": "OVL_DBMF", "entry_date": today, "exit_date": today,
            "entry_price": 0, "exit_price": 0, "shares": 0, "commission": 0,
            "pnl_usd": round(pnl, 4), "pnl_pct": ret * 100, "days_held": 1,
            "exit_reason": "dbmf_daily", "tier": 0, "consec_down": 0,
            "portfolio_val": pv})
    return pv, True   # always "in position"

def _is_vix_trending_up(today, ovl_px, window=10, daily_thresh=0.005):
    """Idea_T helper: True if VIX has been rising for `window` consecutive days."""
    if "^VIX" not in ovl_px or today not in ovl_px["^VIX"].index: return False
    vix = ovl_px["^VIX"]
    if today not in vix.index: return False
    idx = vix.index.get_loc(today)
    if idx < window: return False
    vix_slice = vix.iloc[idx - window:idx + 1].values
    # Count consecutive up days at end of slice
    up_count = 0
    for j in range(len(vix_slice) - 1, 0, -1):
        if vix_slice[j] > vix_slice[j - 1] * (1 + daily_thresh):
            up_count += 1
        else:
            break
    return up_count >= window


# ── CORE SIMULATION LOOP ───────────────────────────────────────────────────
def run_simulation(price_data, spy_df, vix_df, sector_data, earnings_map, ovl_px, label,
                   idea_n=False, idea_o=False, idea_p=False, idea_q=False,
                   idea_r=False, idea_s=False, idea_t=False):
    print(f"\n[{label}]")

    all_dates = sorted(set().union(*[set(df.index) for df in price_data.values()]))
    tom_set   = build_tom_set(all_dates)
    min_bars  = MA_WINDOW + VOL_MA_PERIOD + ATR_PERIOD + MIN_CONSEC_DOWN + 5
    signals   = {t: generate_signals(df) for t, df in price_data.items() if len(df) > min_bars}

    spy_regime  = spy_df["spy_ok"].to_dict()
    spy_close   = spy_df["Close"].squeeze()
    spy_ma200_s = spy_df["Close"].squeeze().rolling(200).mean()
    vix_close   = vix_df["Close"].squeeze()

    pv = INITIAL_CAPITAL; peak = None; dd = 0.0
    open_pos = {}; trades = []; cool = {}; last_vs = None; last_vc = None

    # V7.4 overlay state
    pr=None; prd=None; pn=0.0; pms=9999.0; pds=0
    alo=PUT_SPREAD_LOWER_OTM; ahi=PUT_SPREAD_UPPER_OTM
    vd=0; vr=None; vrd=None; vn=0.0; vpk=0.0; vpm=0.0
    gold_in=False; tlt_in=False
    secrot_w={}; prev_secrot_mon=None
    factor_w={"QQQ":0.0,"IWM":0.0}; prev_factor_mon=None

    # V7.5 new overlay state
    pdbc_in=False; hyg_in=False; zroz_in=False; dbmf_in=False
    call_d=0; call_ref_pv=0.0; call_prem=0.0; call_entry_spy=0.0

    from tqdm import tqdm
    for today in tqdm(all_dates, desc=label):
        spy_ok = spy_regime.get(today, True)
        paused, last_vs = check_vix_spike(today, vix_df, last_vs)
        vel_paused, last_vc = _vel(today, spy_df, last_vc)
        peak_new, dd = _dd_upd(pv, peak)
        peak = peak_new if peak_new is not None else peak

        ma200v = spy_ma200_s.loc[today] if today in spy_ma200_s.index else np.nan
        spyp   = float(spy_close.loc[today]) if today in spy_close.index else np.nan
        spy_above = not np.isnan(ma200v) and not np.isnan(spyp) and spyp > ma200v
        vix_now = get_vix_level(today, vix_df)

        # ── SPY put spread (Idea_P modifies strikes) ──────────────────────
        pv,pr,prd,pn,pms,pds,alo,ahi = _put_tick(
            today, spy_df, spy_close, pv, trades, pr, prd, pn, pms, pds, alo, ahi,
            vix_df, use_idea_p=idea_p)

        # ── VIX call spread (Idea_K always on) ───────────────────────────
        pv,vd,vr,vrd,vn,vpk,vpm = _vxc_tick(
            today, vix_df, vix_close, pv, trades, vd, vr, vrd, vn, vpk, vpm, ovl_px)

        # ── GOLD ─────────────────────────────────────────────────────────
        pv, gold_in = _gold_tick(today, pv, trades, gold_in, ovl_px)

        # ── TLT Bear (Idea_I always on) ───────────────────────────────────
        pv, tlt_in = _tlt_tick(today, pv, trades, tlt_in, ovl_px, spy_above)

        # ── Idea_Q: ZROZ panic overlay ────────────────────────────────────
        if idea_q:
            pv, zroz_in = _zroz_tick(today, pv, trades, zroz_in, ovl_px, vix_now)

        # ── SECROT / USMV (Idea_T replaces SECROT in VIX expansion) ──────
        usmv_active = idea_t and _is_vix_trending_up(today, ovl_px)
        pv, secrot_w, prev_secrot_mon = _secrot_tick(
            today, pv, trades, secrot_w, ovl_px, spy_above, prev_secrot_mon,
            use_usmv=idea_t, usmv_active=usmv_active)

        # ── Factor rotation (Idea_J always on) ───────────────────────────
        pv, factor_w, prev_factor_mon = _factor_tick(
            today, pv, trades, factor_w, ovl_px, spy_above, prev_factor_mon)

        # ── Idea_N: PDBC commodity ────────────────────────────────────────
        if idea_n:
            pv, pdbc_in = _pdbc_tick(today, pv, trades, pdbc_in, ovl_px)

        # ── Idea_O: HYG/LQD credit carry ──────────────────────────────────
        if idea_o:
            pv, hyg_in = _hyg_tick(today, pv, trades, hyg_in, ovl_px, spy_above)

        # ── Idea_R: SPY call in low-VIX ───────────────────────────────────
        if idea_r:
            pv, call_d, call_ref_pv, call_prem, call_entry_spy = _spy_call_tick(
                today, pv, trades, call_d, call_ref_pv, call_prem, call_entry_spy,
                vix_now, ovl_px)

        # ── Idea_S: DBMF managed futures ──────────────────────────────────
        if idea_s:
            pv, dbmf_in = _dbmf_tick(today, pv, trades, dbmf_in, ovl_px, spy_above)

        # ── MR exits ─────────────────────────────────────────────────────
        pv = _run_exits(today, signals, open_pos, trades, pv, cool)

        if not spy_ok or paused or vel_paused or len(open_pos) >= MAX_POSITIONS:
            continue

        # ── MR entries ───────────────────────────────────────────────────
        tom_today = today in tom_set; dow = pd.Timestamp(today).dayofweek
        cands = _build_cands(today, signals, open_pos, cool,
                              earnings_map, sector_data, vix_now)
        _enter(today, signals, cands, open_pos, cool, pv, vix_df, dd, tom_today, dow)

    return pd.DataFrame(trades)


# ── EXTRACT & REPORT ───────────────────────────────────────────────────────
def _extract(trades_df, name):
    OVL_TICKERS = {"SPY_PUT_SPREAD","VIX_CALL_SPREAD"}
    mr   = trades_df[~trades_df["ticker"].isin(OVL_TICKERS) &
                     ~trades_df["ticker"].str.startswith("OVL_")]
    if mr.empty: return {"test": name, "error": "No MR trades",
                         **{k:0 for k in ["put_net","vxc_net","gold_net","tlt_net",
                                          "secrot_net","factor_net","pdbc_net",
                                          "hyg_net","zroz_net","call_net","dbmf_net","usmv_net"]}}
    mr_m, _ = compute_metrics(mr)
    comb    = _combined_metrics(trades_df)

    def s(pat): return trades_df[trades_df["ticker"].str.startswith(pat)]["pnl_usd"].sum() \
                       if not trades_df.empty else 0.0

    return {
        "test":          name,
        "cagr_mr":       mr_m["cagr_pct"],
        "sharpe_mr":     mr_m["sharpe_ratio"],
        "win_rate":      mr_m["win_rate_pct"],
        "pf":            mr_m["profit_factor"],
        "trades":        mr_m["total_trades"],
        "cagr_comb":     comb["cagr"],
        "final_equity":  comb["final_equity"],
        "max_dd":        comb["max_dd"],
        "sharpe_comb":   comb["sharpe"],
        "equity_curve":  comb["equity_curve"],
        "put_net":    round(s("SPY_PUT"),   2),
        "vxc_net":    round(s("VIX_CALL"),  2),
        "gold_net":   round(s("OVL_GOLD"),  2),
        "tlt_net":    round(s("OVL_TLT"),   2),
        "secrot_net": round(s("OVL_SECROT"),2),
        "factor_net": round(s("OVL_FACTOR"),2),
        "pdbc_net":   round(s("OVL_PDBC"),  2),
        "hyg_net":    round(s("OVL_HYG"),   2),
        "zroz_net":   round(s("OVL_ZROZ"),  2),
        "call_net":   round(s("OVL_SPY_CALL"),2),
        "dbmf_net":   round(s("OVL_DBMF"),  2),
        "usmv_net":   round(s("OVL_USMV"),  2),
        "year_stats": mr_m.get("year_stats", {}),
    }

def _print_table(results):
    W = 145
    print("\n" + "="*W)
    print(f" IDEAS V7.5 | Baseline V7.4: ${V74_FINAL:,.0f} | "
          f"CAGR {V74_CAGR}% | MaxDD {V74_MAXDD}% | Sharpe {V74_SHARPE}")
    print("="*W)
    hdr = (f"{'Test':<28} {'MR%':>7} {'Comb%':>8} {'ΔComb':>8} "
           f"{'Equity':>15} {'ΔEquity':>14} {'MaxDD%':>8} {'ΔDD':>8} "
           f"{'Sharpe':>7} {'WR%':>6}")
    print(hdr); print("-"*W)

    bl = next((r for r in results if "Baseline" in r.get("test","")), None)
    bl_eq  = bl["final_equity"] if bl else V74_FINAL
    bl_dd  = bl["max_dd"]       if bl else V74_MAXDD
    bl_cag = bl["cagr_comb"]    if bl else V74_CAGR

    for r in results:
        if "error" in r:
            print(f"  {r['test']:<26} ERROR: {r['error']}"); continue
        dc  = r["cagr_comb"] - bl_cag
        de  = r["final_equity"] - bl_eq
        ddd = r["max_dd"] - bl_dd
        # ★ = MaxDD improved (less negative), ✗ = worse
        flag = "★" if (ddd > 0 and "Baseline" not in r["test"]) else " "
        print(f"{flag} {r['test']:<27} {r['cagr_mr']:>7.2f} {r['cagr_comb']:>8.2f} "
              f"{dc:>+8.2f}pp ${r['final_equity']:>14,.0f} ${de:>+13,.0f} "
              f"{r['max_dd']:>8.2f} {ddd:>+8.2f}pp {r['sharpe_comb']:>7.2f} "
              f"{r['win_rate']:>6.2f}")

    print("="*W)
    print(" ★ = MaxDD improved vs V7.4 baseline. dDD > 0 = less negative = better.")

    print(f"\n{'Overlay P&L (all-time $k)':}")
    print(f"{'Test':<28} {'Put':>8} {'VXC':>8} {'Gold':>7} {'TLT':>7} "
          f"{'SECROT':>8} {'Factor':>8} {'PDBC':>7} {'HYG':>7} "
          f"{'ZROZ':>7} {'Call':>7} {'DBMF':>8} {'USMV':>7}")
    print("-"*135)
    for r in results:
        if "error" in r: continue
        def f(k): return f"${r.get(k,0)/1000:>6.0f}k"
        print(f"  {r['test']:<26} {f('put_net')} {f('vxc_net')} {f('gold_net')} "
              f"{f('tlt_net')} {f('secrot_net')} {f('factor_net')} "
              f"{f('pdbc_net')} {f('hyg_net')} {f('zroz_net')} "
              f"{f('call_net')} {f('dbmf_net')} {f('usmv_net')}")
    print("="*135)


# ── MAIN ───────────────────────────────────────────────────────────────────
def main():
    print("\n" + "="*70)
    print(" IDEAS V7.5 — 7 New Ideas vs V7.4 Baseline")
    print(f" Baseline: ${V74_FINAL:,.0f} | CAGR {V74_CAGR}% | MaxDD {V74_MAXDD}%")
    print("="*70)

    universe     = get_universe()
    price_data   = download_prices(universe)
    spy_df, vix_df, sector_data = download_reference_data()
    earnings_map = build_earnings_dates(list(price_data.keys()))
    ovl_px       = download_overlay_data()

    # Test matrix: (label, n, o, p, q, r, s, t)
    tests = [
        ("Baseline V7.4",     False,False,False,False,False,False,False),
        ("Idea_N PDBC Commod",True, False,False,False,False,False,False),
        ("Idea_O HYG Credit", False,True, False,False,False,False,False),
        ("Idea_P WiderPut",   False,False,True, False,False,False,False),
        ("Idea_Q ZROZ Panic", False,False,False,True, False,False,False),
        ("Idea_R SPY Call",   False,False,False,False,True, False,False),
        ("Idea_S DBMF MgdFut",False,False,False,False,False,True, False),
        ("Idea_T USMV LateCyc",False,False,False,False,False,False,True),
        # Combinations of the best ideas
        ("N+O+P+Q",           True, True, True, True, False,False,False),
        ("P+Q+S",             False,False,True, True, False,True, False),
        ("N+P+Q+S",           True, False,True, True, False,True, False),
        ("All 7 combined",    True, True, True, True, True, True, True),
    ]

    results = []; eq_curves = {}

    for label, n, o, p, q, r, s, t in tests:
        print(f"\n{'─'*55}\nRunning: {label}")
        try:
            df = run_simulation(
                price_data, spy_df, vix_df, sector_data, earnings_map, ovl_px, label,
                idea_n=n, idea_o=o, idea_p=p, idea_q=q,
                idea_r=r, idea_s=s, idea_t=t)
            fname = label.lower().replace(" ","_").replace("/","_").replace("+","_")
            df.to_csv(OUTPUT_DIR / f"{fname}_trades.csv", index=False)
            res = _extract(df, label)
            if "equity_curve" in res and not res["equity_curve"].empty:
                res["equity_curve"].to_csv(
                    OUTPUT_DIR / f"{fname}_equity_curve.csv", index=False)
                eq_curves[label] = res["equity_curve"]
            r_out = {k: v for k, v in res.items() if k not in ("equity_curve","year_stats")}
            results.append(r_out)
            if "error" not in r_out:
                print(f"  → Comb CAGR {r_out['cagr_comb']:.2f}% | "
                      f"Equity ${r_out['final_equity']:,.0f} | "
                      f"MaxDD {r_out['max_dd']:.2f}%")
        except Exception as e:
            import traceback; traceback.print_exc()
            results.append({"test": label, "error": str(e),
                            **{k:0 for k in ["put_net","vxc_net","gold_net","tlt_net",
                                             "secrot_net","factor_net","pdbc_net",
                                             "hyg_net","zroz_net","call_net",
                                             "dbmf_net","usmv_net"]}})

    _print_table(results)

    # Monthly equity comparison
    if eq_curves:
        merged = None
        for nm, eq in eq_curves.items():
            col = nm.replace(" ", "_")
            em  = (eq.set_index(pd.to_datetime(eq["date"]))["equity"]
                   .resample("ME").last().rename(col))
            merged = em.to_frame() if merged is None else merged.join(em, how="outer")
        if merged is not None:
            merged.ffill().to_csv(OUTPUT_DIR / "all_equity_curves_monthly.csv")
            print(f"\n Monthly curves → {OUTPUT_DIR}/all_equity_curves_monthly.csv")

    summary = {
        "run_date":  datetime.date.today().isoformat(),
        "version":   "V7.5",
        "baseline":  {"v74_final": V74_FINAL, "v74_cagr": V74_CAGR,
                      "v74_maxdd": V74_MAXDD},
        "ideas": {
            "N": "PDBC commodity overlay 5% — trend+momentum filter",
            "O": "HYG/LQD credit carry 5% — ratio rising + bull regime",
            "P": "SPY put 4th VIX bucket — VIX>35 → 8%/25% OTM short",
            "Q": "ZROZ panic overlay 6% — VIX>20 + TLT 5d rally",
            "R": "SPY call 0.2%/mo — VIX<13 regime, 5% OTM 30d",
            "S": "DBMF managed futures 5% — long+short SG CTA proxy",
            "T": "USMV late-cycle tilt — replaces SECROT when VIX trending up 10d",
        },
        "results": [{k:v for k,v in r.items()
                     if k not in ("equity_curve","year_stats")} for r in results],
    }
    with open(OUTPUT_DIR / "ideas_v7_5_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)
    print(f"\n All outputs → {OUTPUT_DIR.resolve()}")
    print(" Paste back: full table + overlay P&L breakdown above.")


if __name__ == "__main__":
    main()
