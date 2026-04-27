# backtest_ideas_v7_5_final.py
#
# Ideas V7.5 FINAL — Confirmed winning combination: N + O + P + Q
#
# Research summary (backtest_ideas_v7_5.py, full history April 2026):
#   Idea_N PDBC Commodity : +0.73pp, +$7.5M, MaxDD +0.09pp ✓  → CONFIRMED
#   Idea_O HYG Credit     : +0.46pp, +$4.6M, MaxDD -0.02pp    → CONFIRMED
#   Idea_P Wider Put      : +0.07pp, +$722k, MaxDD neutral     → CONFIRMED (free insurance)
#   Idea_Q ZROZ Panic     : +0.61pp, +$6.2M, MaxDD -0.13pp    → CONFIRMED
#   Idea_R SPY Call       : -0.91pp, -$8.1M                   → DEAD (added to DNR)
#   Idea_S DBMF MgdFut    : +0.21pp, +$2.0M, marginal         → KEPT in combo N+O+P+Q supersedes
#   Idea_T USMV LateCyc   : +0.00pp, $0     zero effect       → DEAD (added to DNR)
#   N+O+P+Q combined      : +1.89pp, +$21.2M, MaxDD -0.04pp   → BEST (virtually free)
#
# V7.5 = V7.4 + Idea_N (PDBC 5%) + Idea_O (HYG 5%) + Idea_P (wider put) + Idea_Q (ZROZ 6%)
#
# Expected: ~$78M | ~34.80% CAGR | ~-57.21% MaxDD | Sharpe ~1.08
#
# Run: python backtest_ideas_v7_5_final.py
# GitHub Actions: ideas_v7_5_final_backtest.yml

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

OUTPUT_DIR = Path("results_ideas_v7_5_final")
OUTPUT_DIR.mkdir(exist_ok=True)

# ── V7.4 CARRY-OVER PARAMS (all unchanged) ────────────────────────────────
PUT_SPREAD_LOWER_OTM  = 0.05
PUT_SPREAD_UPPER_OTM  = 0.15
PUT_SPREAD_COST_PCT   = 0.0075
PUT_SPREAD_RENEW_DAYS = 63

def _get_put_strikes(vix):
    """Idea_P: 4-bucket dynamic strikes (VIX>35 → 8%/25% OTM)."""
    if vix < 15.0:   return 0.03, 0.13
    if vix <= 25.0:  return 0.05, 0.15
    if vix <= 35.0:  return 0.08, 0.20
    return 0.08, 0.25   # NEW: extreme fear — wider short strike

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

# ── V7.5 NEW OVERLAY PARAMS ───────────────────────────────────────────────
PDBC_ALLOC_PCT   = 0.05   # Idea_N
PDBC_MA_WINDOW   = 100
DBC_MOM_DAYS     = 63

HYG_ALLOC_PCT    = 0.05   # Idea_O
HYG_RATIO_WINDOW = 20

ZROZ_ALLOC_PCT   = 0.06   # Idea_Q
ZROZ_VIX_THRESH  = 20.0
ZROZ_TLT_5D_MIN  = 0.005


def download_overlay_data():
    tickers = (["GLD","TLT","QQQ","IWM","PDBC","DBC","HYG","LQD","ZROZ",
                "SPY","^VIX","^VIX3M"] + SPDR_SECTORS)
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
    print(f"[Overlays] Got: {sorted(px.keys())}")
    return px


def _combined_metrics(trades_df):
    df = trades_df.copy()
    df["exit_date"] = pd.to_datetime(df["exit_date"])
    df = df.sort_values("exit_date").reset_index(drop=True)
    eq = INITIAL_CAPITAL; rows = []
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


# ── MR HELPERS ────────────────────────────────────────────────────────────
def _vel(today, spy_df, last_vc):
    paused = False
    try:
        if today in spy_df.index:
            v = float(spy_df.loc[today, "spy_5d_ret"])
            if not np.isnan(v) and v < VELOCITY_CRASH_5D_THRESHOLD: last_vc = today
        if last_vc and (pd.Timestamp(today) - pd.Timestamp(last_vc)).days <= VELOCITY_CRASH_PAUSE_DAYS:
            paused = True
    except Exception: pass
    return paused, last_vc

def _dd_upd(pv, peak):
    if peak is None: return (pv, 0.0) if pv != INITIAL_CAPITAL else (None, 0.0)
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
        early = dh < MIN_HOLD_BEFORE_EXIT; ts = dh >= pos["hold_days"]
        ph = (not early) and pp >= pos["profit_target"]
        if (pos["partial_enabled"] and not pos["partial_done"]
                and not early and pp >= pos["partial_trigger"]):
            psh = sr * pos["partial_frac"]; cm = calc_commission(psh, xp)
            pnl = (xp - ep) * psh - cm
            trades.append({"ticker": tkr, "entry_date": pos["entry_date"],
                "exit_date": today, "entry_price": ep, "exit_price": xp,
                "shares": psh, "commission": round(cm,4), "pnl_usd": pnl,
                "pnl_pct": pp*100, "days_held": dh, "exit_reason": "partial_exit",
                "tier": pos["tier"], "consec_down": pos["consec_down_at_entry"],
                "portfolio_val": pv+pnl})
            pv += pnl; pos["shares_remaining"] -= psh
            pos["partial_done"] = True; pos["profit_target"] *= 2; continue
        fx = ts or (not pos["partial_enabled"] and ph) or \
             (pos["partial_enabled"] and pos["partial_done"] and ph)
        if fx:
            cm = calc_commission(sr, xp)
            pnl = (xp-ep)*sr - cm - pos["entry_commission"]
            rsn = "time_stop" if ts else "profit_target"
            trades.append({"ticker": tkr, "entry_date": pos["entry_date"],
                "exit_date": today, "entry_price": ep, "exit_price": xp,
                "shares": sr, "commission": round(cm+pos["entry_commission"],4),
                "pnl_usd": pnl, "pnl_pct": pp*100, "days_held": dh,
                "exit_reason": rsn, "tier": pos["tier"],
                "consec_down": pos["consec_down_at_entry"], "portfolio_val": pv+pnl})
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
            if (pd.Timestamp(today)-pd.Timestamp(cool[tkr])).days < REENTRY_COOLDOWN_DAYS: continue
        if near_earnings(tkr, today, earnings_map): continue
        if not sector_ok(tkr, today, sector_data): continue
        if count_sector_positions(tkr, open_pos) >= MAX_SECTOR_POSITIONS: continue
        rsi2=float(row["rsi2"]); atr=float(row["atr_pct"])
        cands.append((rsi2/atr if atr>0 else rsi2*1000, tkr, int(row["consec_down"]), rsi2))
    return sorted(cands, key=lambda x: x[0])

def _enter(today, signals, cands, open_pos, cool, pv, vix_df, dd, tom_today, dow):
    n=len(cands); top_n=max(1,int(n*TOP_SIGNAL_PCT))
    for rank,(score,tkr,cv,rv) in enumerate(cands):
        if len(open_pos)>=MAX_POSITIONS: break
        tkr_df=signals[tkr]; idx=tkr_df.index.get_loc(today)
        if idx+1>=len(tkr_df): continue
        ep=float(tkr_df.iloc[idx+1]["Open"])
        if ep<=0: continue
        gp=(ep-float(tkr_df.iloc[idx]["Close"]))/float(tkr_df.iloc[idx]["Close"])
        if gp<GAP_DOWN_MAX or gp>GAP_UP_MAX: continue
        sm=1.0
        if n>=MIN_CANDIDATES_FOR_C5 and rank<top_n: sm=TOP_SIGNAL_MULTIPLIER
        if tom_today: sm*=TOM_MULT
        sm*=DOW_MULT.get(dow,1.0)
        tier=get_tier(cv)
        size=get_position_size(today,vix_df,dd,multiplier=sm,hard_cap=TOP_SIGNAL_HARD_CAP)
        sh=(pv*size)/ep; ec=calc_commission(sh,ep)
        open_pos[tkr]={
            "entry_date":tkr_df.index[idx+1],"entry_price":ep,
            "shares":sh,"shares_remaining":sh,"rsi2_at_entry":rv,
            "consec_down_at_entry":cv,"profit_target":tier["profit_target"],
            "hold_days":tier["hold_days"],"partial_enabled":tier["partial_enabled"],
            "partial_frac":tier["partial_frac"],"partial_trigger":tier["partial_trigger"],
            "partial_done":False,"tier":tier["tier"],"entry_commission":ec}


# ── OVERLAY TICKS ─────────────────────────────────────────────────────────
def _put_tick(today, spy_df, spy_close, pv, trades, pr, prd, pn, pms, pds, alo, ahi, vix_df):
    if today not in spy_df.index: return pv,pr,prd,pn,pms,pds,alo,ahi
    spx=float(spy_close.loc[today]) if today in spy_close.index else None
    if spx is None: return pv,pr,prd,pn,pms,pds,alo,ahi
    if pr is None or pds>=PUT_SPREAD_RENEW_DAYS:
        alo,ahi=_get_put_strikes(get_vix_level(today,vix_df))  # Idea_P 4 buckets
        prem=pv*PUT_SPREAD_COST_PCT; pv-=prem
        pr=spx; prd=today; pn=pv; pms=spx; pds=0
        trades.append({"ticker":"SPY_PUT_SPREAD","entry_date":today,"exit_date":today,
            "entry_price":spx,"exit_price":spx,"shares":0,"commission":0,
            "pnl_usd":-prem,"pnl_pct":-PUT_SPREAD_COST_PCT*100,"days_held":0,
            "exit_reason":"put_premium","tier":0,"consec_down":0,"portfolio_val":pv})
    else:
        pds+=1; pms=min(pms,spx)
        if pds==PUT_SPREAD_RENEW_DAYS-1:
            pay_pct=_put_payout(pr,pms,alo,ahi)
            if pay_pct>0:
                pay=pn*pay_pct; pv+=pay
                trades.append({"ticker":"SPY_PUT_SPREAD","entry_date":prd,"exit_date":today,
                    "entry_price":pr,"exit_price":pms,"shares":0,"commission":0,
                    "pnl_usd":round(pay,2),"pnl_pct":round(pay_pct*100,4),"days_held":pds,
                    "exit_reason":"put_payout","tier":0,"consec_down":0,"portfolio_val":pv})
    return pv,pr,prd,pn,pms,pds,alo,ahi

def _vxc_tick(today, vix_df, vix_close, pv, trades, vd, vr, vrd, vn, vpk, vpm, ovl_px):
    if today not in vix_df.index: return pv,vd,vr,vrd,vn,vpk,vpm
    vpx=float(vix_close.loc[today]) if today in vix_close.index else None
    if vpx is None: return pv,vd,vr,vrd,vn,vpk,vpm
    cost_pct=VIX_CALL_COST_NORMAL
    if "^VIX3M" in ovl_px and today in ovl_px["^VIX3M"].index:
        if vpx>float(ovl_px["^VIX3M"].loc[today]): cost_pct=VIX_CALL_COST_BACKWARDATION
    if vr is None or vd>=VIX_CALL_RENEW_DAYS:
        prem=pv*cost_pct; pv-=prem
        vr=vpx; vrd=today; vn=pv; vpk=vpx; vpm=prem; vd=0
        trades.append({"ticker":"VIX_CALL_SPREAD","entry_date":today,"exit_date":today,
            "entry_price":vpx,"exit_price":vpx,"shares":0,"commission":0,
            "pnl_usd":-prem,"pnl_pct":-cost_pct*100,"days_held":0,
            "exit_reason":"vix_call_premium","tier":0,"consec_down":0,"portfolio_val":pv})
    else:
        vd+=1; vpk=max(vpk,vpx)
        if vd==VIX_CALL_RENEW_DAYS-1:
            mult=_vix_call_mult(vr,vpk)
            if mult>0:
                pay=vpm*mult; pv+=pay
                trades.append({"ticker":"VIX_CALL_SPREAD","entry_date":vrd,"exit_date":today,
                    "entry_price":vr,"exit_price":vpk,"shares":0,"commission":0,
                    "pnl_usd":round(pay,2),"pnl_pct":round(mult*cost_pct*100,4),"days_held":vd,
                    "exit_reason":"vix_call_payout","tier":0,"consec_down":0,"portfolio_val":pv})
    return pv,vd,vr,vrd,vn,vpk,vpm

def _gold_tick(today, pv, trades, in_pos, ovl_px):
    if "GLD" not in ovl_px or "TLT" not in ovl_px or today not in ovl_px["GLD"].index:
        return pv,in_pos
    gld=ovl_px["GLD"]; tlt=ovl_px["TLT"]
    ma200=float(gld.rolling(200).mean().loc[today]) if today in gld.rolling(200).mean().index else np.nan
    if np.isnan(ma200): return pv,in_pos
    slope=float(tlt.rolling(20).mean().diff(20).loc[today]) if today in tlt.index else np.nan
    trend=float(gld.loc[today])>ma200; carry=np.isnan(slope) or slope>=0
    if not in_pos and trend and carry: in_pos=True
    if in_pos and not trend: in_pos=False
    if in_pos:
        ret=float(gld.pct_change().loc[today]) if today in gld.index else 0.0
        if not np.isnan(ret):
            pnl=ret*pv*GOLD_ALLOC_PCT; pv+=pnl
            if abs(pnl)>0.01:
                trades.append({"ticker":"OVL_GOLD","entry_date":today,"exit_date":today,
                    "entry_price":float(gld.loc[today]),"exit_price":float(gld.loc[today]),
                    "shares":0,"commission":0,"pnl_usd":round(pnl,4),"pnl_pct":ret*100,
                    "days_held":1,"exit_reason":"gold_daily","tier":0,"consec_down":0,"portfolio_val":pv})
    return pv,in_pos

def _tlt_tick(today, pv, trades, in_pos, ovl_px, spy_above):
    if "TLT" not in ovl_px or today not in ovl_px["TLT"].index: return pv,in_pos
    tlt=ovl_px["TLT"]; price=float(tlt.loc[today])
    ma50v=float(tlt.rolling(TLT_MA_WINDOW).mean().loc[today]) \
          if today in tlt.rolling(TLT_MA_WINDOW).mean().index else np.nan
    if np.isnan(ma50v): return pv,in_pos
    should=(not spy_above) and price>ma50v
    if not in_pos and should: in_pos=True
    if in_pos and not should: in_pos=False
    if in_pos:
        ret=float(tlt.pct_change().loc[today]) if today in tlt.index else 0.0
        if not np.isnan(ret):
            pnl=ret*pv*TLT_ALLOC_PCT; pv+=pnl
            if abs(pnl)>0.01:
                trades.append({"ticker":"OVL_TLT_BEAR","entry_date":today,"exit_date":today,
                    "entry_price":price,"exit_price":price,"shares":0,"commission":0,
                    "pnl_usd":round(pnl,4),"pnl_pct":ret*100,"days_held":1,
                    "exit_reason":"tlt_bear_daily","tier":0,"consec_down":0,"portfolio_val":pv})
    return pv,in_pos

def _secrot_tick(today, pv, trades, weights, ovl_px, spy_above, prev_mon):
    available=[s for s in SPDR_SECTORS if s in ovl_px]
    mon=(pd.Timestamp(today).year,pd.Timestamp(today).month)
    if mon!=prev_mon:
        prev_mon=mon; weights={s:0.0 for s in available}
        if spy_above:
            moms={s:float(ovl_px[s].pct_change(SECROT_MOM_DAYS).loc[today])
                  for s in available if today in ovl_px[s].index and
                  not np.isnan(ovl_px[s].pct_change(SECROT_MOM_DAYS).loc[today])}
            top=sorted(moms,key=moms.get,reverse=True)[:SECROT_TOP_N]
            for s in available: weights[s]=1.0 if s in top else 0.0
    if spy_above:
        for s in available:
            if weights.get(s,0)==0 or today not in ovl_px[s].index: continue
            ret=float(ovl_px[s].pct_change().loc[today])
            if np.isnan(ret): continue
            pnl=ret*pv*SECROT_ALLOC; pv+=pnl
            if abs(pnl)>0.01:
                trades.append({"ticker":f"OVL_SECROT_{s}","entry_date":today,"exit_date":today,
                    "entry_price":float(ovl_px[s].loc[today]),"exit_price":float(ovl_px[s].loc[today]),
                    "shares":0,"commission":0,"pnl_usd":round(pnl,4),"pnl_pct":ret*100,
                    "days_held":1,"exit_reason":"secrot_daily","tier":0,"consec_down":0,"portfolio_val":pv})
    return pv,weights,prev_mon

def _factor_tick(today, pv, trades, fw, ovl_px, spy_above, prev_mon):
    if "QQQ" not in ovl_px or "IWM" not in ovl_px: return pv,fw,prev_mon
    mon=(pd.Timestamp(today).year,pd.Timestamp(today).month)
    if mon!=prev_mon:
        prev_mon=mon; fw={"QQQ":0.0,"IWM":0.0}
        if spy_above:
            qm=float(ovl_px["QQQ"].pct_change(FACTOR_MOM_DAYS).loc[today]) \
               if today in ovl_px["QQQ"].index else np.nan
            im=float(ovl_px["IWM"].pct_change(FACTOR_MOM_DAYS).loc[today]) \
               if today in ovl_px["IWM"].index else np.nan
            if not np.isnan(qm) and not np.isnan(im):
                fw["QQQ" if qm>=im else "IWM"]=1.0
    if spy_above:
        for etf,w in fw.items():
            if w==0 or today not in ovl_px[etf].index: continue
            ret=float(ovl_px[etf].pct_change().loc[today])
            if np.isnan(ret): continue
            pnl=ret*pv*FACTOR_ALLOC; pv+=pnl
            if abs(pnl)>0.01:
                trades.append({"ticker":f"OVL_FACTOR_{etf}","entry_date":today,"exit_date":today,
                    "entry_price":float(ovl_px[etf].loc[today]),"exit_price":float(ovl_px[etf].loc[today]),
                    "shares":0,"commission":0,"pnl_usd":round(pnl,4),"pnl_pct":ret*100,
                    "days_held":1,"exit_reason":"factor_daily","tier":0,"consec_down":0,"portfolio_val":pv})
    return pv,fw,prev_mon

# ── V7.5 NEW OVERLAY TICKS ────────────────────────────────────────────────
def _pdbc_tick(today, pv, trades, in_pos, ovl_px):
    """Idea_N: PDBC/DBC commodity overlay — 5%, 100d MA + DBC 63d momentum > 0."""
    ticker="PDBC" if "PDBC" in ovl_px else ("DBC" if "DBC" in ovl_px else None)
    if ticker is None or today not in ovl_px[ticker].index: return pv,in_pos
    s=ovl_px[ticker]; price=float(s.loc[today])
    ma100_s=s.rolling(PDBC_MA_WINDOW).mean()
    ma100=float(ma100_s.loc[today]) if today in ma100_s.index else np.nan
    if np.isnan(ma100): return pv,in_pos
    dbc_s=ovl_px.get("DBC",s)
    dbc_mom_s=dbc_s.pct_change(DBC_MOM_DAYS)
    dbc_mom=float(dbc_mom_s.loc[today]) if today in dbc_mom_s.index else np.nan
    trend=price>ma100; mom_ok=np.isnan(dbc_mom) or dbc_mom>0
    if not in_pos and trend and mom_ok: in_pos=True
    if in_pos and not (trend and mom_ok): in_pos=False
    if in_pos:
        ret=float(s.pct_change().loc[today]) if today in s.index else 0.0
        if not np.isnan(ret):
            pnl=ret*pv*PDBC_ALLOC_PCT; pv+=pnl
            if abs(pnl)>0.01:
                trades.append({"ticker":"OVL_PDBC","entry_date":today,"exit_date":today,
                    "entry_price":price,"exit_price":price,"shares":0,"commission":0,
                    "pnl_usd":round(pnl,4),"pnl_pct":ret*100,"days_held":1,
                    "exit_reason":"pdbc_daily","tier":0,"consec_down":0,"portfolio_val":pv})
    return pv,in_pos

def _hyg_tick(today, pv, trades, in_pos, ovl_px, spy_above):
    """Idea_O: HYG/LQD credit carry — 5% when ratio rising + bull regime."""
    if not spy_above: return pv,False
    if "HYG" not in ovl_px or "LQD" not in ovl_px: return pv,in_pos
    if today not in ovl_px["HYG"].index or today not in ovl_px["LQD"].index: return pv,in_pos
    hyg=ovl_px["HYG"]; lqd=ovl_px["LQD"]
    ratio=hyg/lqd; ratio_ma=ratio.rolling(HYG_RATIO_WINDOW).mean()
    if today not in ratio_ma.index or np.isnan(ratio_ma.loc[today]): return pv,in_pos
    signal_in=float(ratio.loc[today])>float(ratio_ma.loc[today])
    if not in_pos and signal_in: in_pos=True
    if in_pos and not signal_in: in_pos=False
    if in_pos:
        ret=float(hyg.pct_change().loc[today]) if today in hyg.index else 0.0
        if not np.isnan(ret):
            pnl=ret*pv*HYG_ALLOC_PCT; pv+=pnl
            if abs(pnl)>0.01:
                trades.append({"ticker":"OVL_HYG","entry_date":today,"exit_date":today,
                    "entry_price":float(hyg.loc[today]),"exit_price":float(hyg.loc[today]),
                    "shares":0,"commission":0,"pnl_usd":round(pnl,4),"pnl_pct":ret*100,
                    "days_held":1,"exit_reason":"hyg_daily","tier":0,"consec_down":0,"portfolio_val":pv})
    return pv,in_pos

def _zroz_tick(today, pv, trades, in_pos, ovl_px, vix_value):
    """Idea_Q: ZROZ panic overlay — 6% when VIX>20 AND TLT 5d rally > 0.5%."""
    ticker="ZROZ" if "ZROZ" in ovl_px else ("TLT" if "TLT" in ovl_px else None)
    amp=1.0 if ticker=="ZROZ" else 2.5
    if ticker is None or today not in ovl_px[ticker].index: return pv,in_pos
    s=ovl_px[ticker]; tlt_s=ovl_px.get("TLT",s)
    tlt_5d_s=tlt_s.pct_change(5)
    tlt_5d=float(tlt_5d_s.loc[today]) if today in tlt_5d_s.index else np.nan
    vix_ok=vix_value>ZROZ_VIX_THRESH; tlt_ok=not np.isnan(tlt_5d) and tlt_5d>ZROZ_TLT_5D_MIN
    signal_in=vix_ok and tlt_ok
    if not in_pos and signal_in: in_pos=True
    if in_pos and not vix_ok: in_pos=False
    if in_pos:
        ret=float(s.pct_change().loc[today]) if today in s.index else 0.0
        if not np.isnan(ret):
            pnl=ret*amp*pv*ZROZ_ALLOC_PCT; pv+=pnl
            if abs(pnl)>0.01:
                trades.append({"ticker":"OVL_ZROZ","entry_date":today,"exit_date":today,
                    "entry_price":float(s.loc[today]),"exit_price":float(s.loc[today]),
                    "shares":0,"commission":0,"pnl_usd":round(pnl,4),"pnl_pct":ret*amp*100,
                    "days_held":1,"exit_reason":"zroz_daily","tier":0,"consec_down":0,"portfolio_val":pv})
    return pv,in_pos


# ── MAIN SIMULATION: V7.5 = V7.4 + N + O + P + Q ─────────────────────────
def run_v75(price_data, spy_df, vix_df, sector_data, earnings_map, ovl_px):
    print("\n[V7.5] V7.4 + Idea_N (PDBC) + Idea_O (HYG) + Idea_P (wider put) + Idea_Q (ZROZ)")

    all_dates=sorted(set().union(*[set(df.index) for df in price_data.values()]))
    tom_set=build_tom_set(all_dates)
    min_bars=MA_WINDOW+VOL_MA_PERIOD+ATR_PERIOD+MIN_CONSEC_DOWN+5
    signals={t:generate_signals(df) for t,df in price_data.items() if len(df)>min_bars}

    spy_regime=spy_df["spy_ok"].to_dict()
    spy_close=spy_df["Close"].squeeze()
    spy_ma200_s=spy_df["Close"].squeeze().rolling(200).mean()
    vix_close=vix_df["Close"].squeeze()

    pv=INITIAL_CAPITAL; peak=None; dd=0.0
    open_pos={}; trades=[]; cool={}; last_vs=None; last_vc=None

    pr=None; prd=None; pn=0.0; pms=9999.0; pds=0
    alo=PUT_SPREAD_LOWER_OTM; ahi=PUT_SPREAD_UPPER_OTM
    vd=0; vr=None; vrd=None; vn=0.0; vpk=0.0; vpm=0.0

    gold_in=False; tlt_in=False; pdbc_in=False; hyg_in=False; zroz_in=False
    secrot_w={}; prev_secrot_mon=None
    factor_w={"QQQ":0.0,"IWM":0.0}; prev_factor_mon=None

    from tqdm import tqdm
    for today in tqdm(all_dates, desc="V7.5"):
        spy_ok=spy_regime.get(today,True)
        paused,last_vs=check_vix_spike(today,vix_df,last_vs)
        vel_paused,last_vc=_vel(today,spy_df,last_vc)
        peak_new,dd=_dd_upd(pv,peak)
        peak=peak_new if peak_new is not None else peak

        ma200v=spy_ma200_s.loc[today] if today in spy_ma200_s.index else np.nan
        spyp=float(spy_close.loc[today]) if today in spy_close.index else np.nan
        spy_above=not np.isnan(ma200v) and not np.isnan(spyp) and spyp>ma200v
        vix_now=get_vix_level(today,vix_df)

        pv,pr,prd,pn,pms,pds,alo,ahi=_put_tick(
            today,spy_df,spy_close,pv,trades,pr,prd,pn,pms,pds,alo,ahi,vix_df)
        pv,vd,vr,vrd,vn,vpk,vpm=_vxc_tick(
            today,vix_df,vix_close,pv,trades,vd,vr,vrd,vn,vpk,vpm,ovl_px)
        pv,gold_in=_gold_tick(today,pv,trades,gold_in,ovl_px)
        pv,tlt_in=_tlt_tick(today,pv,trades,tlt_in,ovl_px,spy_above)
        pv,secrot_w,prev_secrot_mon=_secrot_tick(
            today,pv,trades,secrot_w,ovl_px,spy_above,prev_secrot_mon)
        pv,factor_w,prev_factor_mon=_factor_tick(
            today,pv,trades,factor_w,ovl_px,spy_above,prev_factor_mon)
        pv,pdbc_in=_pdbc_tick(today,pv,trades,pdbc_in,ovl_px)
        pv,hyg_in=_hyg_tick(today,pv,trades,hyg_in,ovl_px,spy_above)
        pv,zroz_in=_zroz_tick(today,pv,trades,zroz_in,ovl_px,vix_now)
        pv=_run_exits(today,signals,open_pos,trades,pv,cool)

        if not spy_ok or paused or vel_paused or len(open_pos)>=MAX_POSITIONS: continue
        tom_today=today in tom_set; dow=pd.Timestamp(today).dayofweek
        cands=_build_cands(today,signals,open_pos,cool,earnings_map,sector_data,vix_now)
        _enter(today,signals,cands,open_pos,cool,pv,vix_df,dd,tom_today,dow)

    return pd.DataFrame(trades)


# ── REPORT ────────────────────────────────────────────────────────────────
def report(trades_df):
    OVL={"SPY_PUT_SPREAD","VIX_CALL_SPREAD"}
    mr=trades_df[~trades_df["ticker"].isin(OVL)&~trades_df["ticker"].str.startswith("OVL_")]
    mr_m,_=compute_metrics(mr)
    comb=_combined_metrics(trades_df)

    def s(p): return trades_df[trades_df["ticker"].str.startswith(p)]["pnl_usd"].sum() \
                     if not trades_df.empty else 0.0
    def sp(p,r): return trades_df[(trades_df["ticker"].str.startswith(p))&
                                  (trades_df["exit_reason"]==r)]["pnl_usd"].sum()

    V74_EQ=57_022_512; V74_CAGR=32.91; V74_DD=-57.17; V74_SH=1.04

    W=70
    print("\n"+"="*W)
    print(" V7.5 FINAL RESULTS")
    print(" V7.4 + Idea_N (PDBC) + Idea_O (HYG) + Idea_P (wider put) + Idea_Q (ZROZ)")
    print("="*W)
    dc=comb["cagr"]-V74_CAGR; de=comb["final_equity"]-V74_EQ; dm=comb["max_dd"]-V74_DD
    print(f"\n  {'Metric':<36} {'V7.4 Baseline':>16} {'V7.5':>16} {'Delta':>10}")
    print("  "+"-"*(W-2))
    print(f"  {'CAGR (MR-only)':<36} {mr_m['cagr_pct']:>15.2f}%  —")
    print(f"  {'CAGR (combined)':<36} {V74_CAGR:>15.2f}% {comb['cagr']:>15.2f}%  {dc:>+8.2f}pp")
    print(f"  {'Final Equity (combined)':<36} ${V74_EQ:>14,.0f} ${comb['final_equity']:>14,.0f}  ${de:>+9,.0f}")
    print(f"  {'Max Drawdown (combined)':<36} {V74_DD:>15.2f}% {comb['max_dd']:>15.2f}%  {dm:>+8.2f}pp")
    print(f"  {'Sharpe (combined)':<36} {V74_SH:>16.2f} {comb['sharpe']:>16.2f}")
    print(f"  {'Win Rate (MR-only)':<36} {'60.25%':>16} {mr_m['win_rate_pct']:>15.2f}%")
    print(f"  {'Total MR trades':<36} {'—':>16} {mr_m['total_trades']:>16,}")

    print(f"\n  Overlay P&L (all-time):")
    rows=[
        ("SPY put spread",   "SPY_PUT", "put_premium", "put_payout"),
        ("VIX call spread",  "VIX_CALL","vix_call_premium","vix_call_payout"),
        ("GOLD",             "OVL_GOLD",None,None),
        ("TLT Bear (I)",     "OVL_TLT", None,None),
        ("SECROT",           "OVL_SECROT",None,None),
        ("Factor (J)",       "OVL_FACTOR",None,None),
        ("PDBC Commod (N)",  "OVL_PDBC",None,None),
        ("HYG Credit (O)",   "OVL_HYG",None,None),
        ("ZROZ Panic (Q)",   "OVL_ZROZ",None,None),
    ]
    total_ovl=0
    for lbl,prefix,pr_rsn,pay_rsn in rows:
        net=round(s(prefix),2)
        total_ovl+=net
        extra=""
        if pr_rsn and pay_rsn:
            extra=f"  (prem ${sp(prefix,pr_rsn):>+12,.0f}  pay ${sp(prefix,pay_rsn):>+12,.0f})"
        flag=" ← NEW" if prefix in ("OVL_PDBC","OVL_HYG","OVL_ZROZ") else ""
        print(f"    {lbl:<24}: ${net:>+14,.0f}{extra}{flag}")
    print(f"    {'TOTAL overlays':<24}: ${total_ovl:>+14,.0f}")
    print(f"    {'MR trades P&L':<24}: ${s(''):>+14,.0f}")

    # Year-by-year
    eq_df=comb["equity_curve"].copy()
    eq_df["year"]=pd.to_datetime(eq_df["date"]).dt.year
    print(f"\n  Year-by-Year (combined):")
    print(f"  {'Year':<5} {'End Equity':>16} {'Annual P&L':>14}")
    print("  "+"-"*38)
    prev_eq=INITIAL_CAPITAL
    for yr in sorted(eq_df["year"].unique()):
        yr_eq=eq_df[eq_df["year"]==yr]["equity"].iloc[-1]
        print(f"  {yr:<5} ${yr_eq:>14,.0f}  ${yr_eq-prev_eq:>+13,.0f}")
        prev_eq=yr_eq
    print("="*W)

    return {
        "cagr_mr":        mr_m["cagr_pct"],
        "cagr_comb":      comb["cagr"],
        "final_equity":   comb["final_equity"],
        "max_dd":         comb["max_dd"],
        "sharpe":         comb["sharpe"],
        "win_rate":       mr_m["win_rate_pct"],
        "total_trades":   mr_m["total_trades"],
        "delta_cagr":     round(dc,2),
        "delta_equity":   round(de,2),
        "delta_maxdd":    round(dm,2),
        "total_overlay":  round(total_ovl,2),
    }


def main():
    print("\n"+"="*70)
    print(" V7.5 FINAL CONFIRMATION BACKTEST")
    print(" V7.4 + Idea_N (PDBC Commodity) + Idea_O (HYG Credit)")
    print("        + Idea_P (Wider Put) + Idea_Q (ZROZ Panic)")
    print("="*70)

    universe=get_universe()
    price_data=download_prices(universe)
    spy_df,vix_df,sector_data=download_reference_data()
    earnings_map=build_earnings_dates(list(price_data.keys()))
    ovl_px=download_overlay_data()

    trades_df=run_v75(price_data,spy_df,vix_df,sector_data,earnings_map,ovl_px)
    trades_df.to_csv(OUTPUT_DIR/"trades.csv",index=False)

    metrics=report(trades_df)
    comb=_combined_metrics(trades_df)
    comb["equity_curve"].to_csv(OUTPUT_DIR/"equity_curve.csv",index=False)
    (comb["equity_curve"].set_index(pd.to_datetime(comb["equity_curve"]["date"]))["equity"]
     .resample("ME").last().ffill()
     .to_csv(OUTPUT_DIR/"equity_curve_monthly.csv"))

    summary={
        "run_date":     datetime.date.today().isoformat(),
        "version":      "V7.5",
        "strategy":     "V7.4 + PDBC(N) + HYG(O) + WiderPut(P) + ZROZ(Q)",
        "v74_baseline": {"final_equity":57_022_512,"cagr_comb":32.91,"max_dd":-57.17},
        "overlay_config":{
            "pdbc_alloc_pct":PDBC_ALLOC_PCT,"pdbc_ma_window":PDBC_MA_WINDOW,
            "hyg_alloc_pct":HYG_ALLOC_PCT,"hyg_ratio_window":HYG_RATIO_WINDOW,
            "put_4th_bucket":"VIX>35 → 8%/25% OTM (was 8%/20%)",
            "zroz_alloc_pct":ZROZ_ALLOC_PCT,"zroz_vix_thresh":ZROZ_VIX_THRESH,
            "zroz_tlt_5d_min":ZROZ_TLT_5D_MIN,
        },
        "results":metrics,
    }
    with open(OUTPUT_DIR/"v7_5_final_summary.json","w") as f:
        json.dump(summary,f,indent=2,default=str)
    print(f"\n  All outputs → {OUTPUT_DIR.resolve()}")
    print("  Paste back results table + year-by-year above.")


if __name__=="__main__":
    main()
