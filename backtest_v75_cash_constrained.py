"""
backtest_v75_cash_constrained.py
=================================
Capital-constrained version of V7.5 backtest.

KEY DIFFERENCE from original:
- Original: overlays use NOTIONAL exposure (earn % return on pv without deploying cash)
- This version: overlays deploy REAL CASH from the same pool as MR positions
- Cash available for MR entries = pv - cash_in_overlays - put_spread_cost - vix_call_cost
- MR position sizing uses available cash, not full pv
- Overlays are bought/sold at start/end of period (monthly rebalance or signal change)

This gives a REALISTIC estimate of live CAGR with $100k starting capital.

Run: python backtest_v75_cash_constrained.py
(Requires backtest_nmr_lib_v47.py in same directory or installed)
"""

import json
import warnings
import datetime
from pathlib import Path
import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# ── Try to import from lib ──────────────────────────────────────────────────
try:
    from backtest_nmr_lib_v47 import (
        get_universe, download_prices, download_reference_data,
        build_earnings_dates, compute_metrics, generate_signals,
        get_position_size, get_tier, calc_commission, sector_ok,
        count_sector_positions, check_vix_spike, near_earnings,
        TICKER_TO_SECTOR, INITIAL_CAPITAL, MAX_POSITIONS, MA_WINDOW,
        VOL_MA_PERIOD, ATR_PERIOD, MIN_CONSEC_DOWN, MIN_HOLD_BEFORE_EXIT,
        VELOCITY_CRASH_5D_THRESHOLD, VELOCITY_CRASH_PAUSE_DAYS,
        GAP_DOWN_MAX, GAP_UP_MAX, REENTRY_COOLDOWN_DAYS,
        MAX_SECTOR_POSITIONS, TOP_SIGNAL_PCT, TOP_SIGNAL_MULTIPLIER,
        TOP_SIGNAL_HARD_CAP, MIN_CANDIDATES_FOR_C5, TOM_MULT, DOW_MULT,
        VIX_TIGHT_THRESH, RSI_TIGHT_THRESH, build_tom_set, get_vix_level,
        START_DATE, END_DATE,
    )
    print("[OK] Imported from backtest_nmr_lib_v47")
except ImportError as e:
    print(f"[ERROR] Cannot import lib: {e}")
    print("Place backtest_nmr_lib_v47.py in the same directory and retry.")
    raise

OUTPUT_DIR = Path("results_v75_cash_constrained")
OUTPUT_DIR.mkdir(exist_ok=True)

# ── Overlay parameters (same as V7.5) ──────────────────────────────────────
PUT_SPREAD_COST_PCT   = 0.0075
PUT_SPREAD_RENEW_DAYS = 63
VIX_CALL_COST_NORMAL       = 0.003
VIX_CALL_COST_BACKWARDATION = 0.006
VIX_CALL_RENEW_DAYS   = 21
VIX_CALL_LOWER = 20.0
VIX_CALL_UPPER = 40.0
VIX_CALL_MAX_MULT = 8.0

GOLD_ALLOC_PCT   = 0.07
TLT_ALLOC_PCT    = 0.08
SECROT_ALLOC     = 0.03
SECROT_TOP_N     = 3
SECROT_MOM_DAYS  = 63
FACTOR_ALLOC     = 0.06
FACTOR_MOM_DAYS  = 63
PDBC_ALLOC_PCT   = 0.05
PDBC_MA_WINDOW   = 100
DBC_MOM_DAYS     = 63
HYG_ALLOC_PCT    = 0.05
HYG_RATIO_WINDOW = 20
ZROZ_ALLOC_PCT   = 0.06
ZROZ_VIX_THRESH  = 20.0
ZROZ_TLT_5D_MIN  = 0.005
SPDR_SECTORS = ["XLK","XLV","XLF","XLE","XLI","XLY","XLP","XLU","XLB","XLRE","XLC"]

# ── Total overlay allocation (used for cash reservation) ───────────────────
# In bull regime max deployed: GOLD(7) + SECROT(9) + FACTOR(6) + PDBC(5) + HYG(5) = 32%
# In bear regime: TLT(8) + PDBC(5) = 13%
# ZROZ(6) only fires during panic — rare
# SPY puts & VIX calls are COSTS (not equity deployments)

def _get_put_strikes(vix):
    if vix < 15.0:  return 0.03, 0.13
    if vix <= 25.0: return 0.05, 0.15
    if vix <= 35.0: return 0.08, 0.20
    return 0.08, 0.25

def _put_payout(spy_ref, spy_worst, lo, hi):
    if spy_worst >= spy_ref * (1 - lo): return 0.0
    return max(0.0, min((spy_ref - spy_worst) / spy_ref - lo, hi - lo))

def _vix_call_mult(vix_ref, vix_peak):
    peak = max(vix_ref, vix_peak)
    if peak <= VIX_CALL_LOWER: return 0.0
    return (min(peak - VIX_CALL_LOWER, VIX_CALL_UPPER - VIX_CALL_LOWER) /
            (VIX_CALL_UPPER - VIX_CALL_LOWER)) * VIX_CALL_MAX_MULT

def download_overlay_data():
    tickers = (["GLD","TLT","QQQ","IWM","PDBC","DBC","HYG","LQD","ZROZ",
                "SPY","^VIX","^VIX3M"] + SPDR_SECTORS)
    print(f"\n[Overlays] Downloading {len(tickers)} tickers...")
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
    sharpe = (monthly.mean() / monthly.std() * np.sqrt(12)
              if monthly.std() > 0 else 0)
    return {
        "final_equity": round(float(eq_df["equity"].iloc[-1]), 2),
        "max_dd":       round(float(eq_df["dd"].min()), 2),
        "cagr":         round(cagr * 100, 2),
        "sharpe":       round(sharpe, 2),
        "equity_curve": eq_df,
    }

# ── MR helpers (identical to V7.5) ─────────────────────────────────────────
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
        if (pos["partial_enabled"] and not pos["partial_done"] and
                not early and pp >= pos["partial_trigger"]):
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
            cm  = calc_commission(sr, xp)
            pnl = (xp - ep) * sr - cm - pos["entry_commission"]
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

def _build_cands(today, signals, open_pos, cool, earnings_map,
                 sector_data, vix_now):
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
        rsi2 = float(row["rsi2"]); atr = float(row["atr_pct"])
        cands.append((rsi2/atr if atr > 0 else rsi2*1000, tkr,
                      int(row["consec_down"]), rsi2))
    return sorted(cands, key=lambda x: x[0])

# ── CASH-CONSTRAINED entry (KEY CHANGE) ────────────────────────────────────
def _enter_constrained(today, signals, cands, open_pos, cool, pv,
                       cash_available, vix_df, dd, tom_today, dow, trades):
    """
    Like _enter but:
    - sizes positions off cash_available (not full pv)
    - tracks cash deployed in MR positions
    - skips if not enough cash for a position
    """
    n = len(cands); top_n = max(1, int(n * TOP_SIGNAL_PCT))
    cash_remaining = cash_available

    for rank, (score, tkr, cv, rv) in enumerate(cands):
        if len(open_pos) >= MAX_POSITIONS: break
        if cash_remaining <= 1000: break  # need at least $1k to enter

        tkr_df = signals[tkr]; idx = tkr_df.index.get_loc(today)
        if idx + 1 >= len(tkr_df): continue
        ep = float(tkr_df.iloc[idx+1]["Open"])
        if ep <= 0: continue
        gp = (ep - float(tkr_df.iloc[idx]["Close"])) / float(tkr_df.iloc[idx]["Close"])
        if gp < GAP_DOWN_MAX or gp > GAP_UP_MAX: continue

        sm = 1.0
        if n >= MIN_CANDIDATES_FOR_C5 and rank < top_n:
            sm = TOP_SIGNAL_MULTIPLIER
        if tom_today: sm *= TOM_MULT
        sm *= DOW_MULT.get(dow, 1.0)

        tier = get_tier(cv)
        # KEY CHANGE: size off pv but cap at cash_remaining
        size = get_position_size(today, vix_df, dd, multiplier=sm,
                                 hard_cap=TOP_SIGNAL_HARD_CAP)
        target_cash = pv * size  # ideal position size in dollars
        actual_cash = min(target_cash, cash_remaining * 0.95)  # leave 5% buffer
        if actual_cash < 500: continue  # too small to bother

        sh = actual_cash / ep
        ec = calc_commission(sh, ep)
        actual_cost = sh * ep + ec

        open_pos[tkr] = {
            "entry_date":        tkr_df.index[idx+1],
            "entry_price":       ep,
            "shares":            sh,
            "shares_remaining":  sh,
            "rsi2_at_entry":     rv,
            "consec_down_at_entry": cv,
            "profit_target":     tier["profit_target"],
            "hold_days":         tier["hold_days"],
            "partial_enabled":   tier["partial_enabled"],
            "partial_frac":      tier["partial_frac"],
            "partial_trigger":   tier["partial_trigger"],
            "partial_done":      False,
            "tier":              tier["tier"],
            "entry_commission":  ec,
        }
        cash_remaining -= actual_cost

# ── MAIN SIMULATION ────────────────────────────────────────────────────────
def run_cash_constrained(price_data, spy_df, vix_df, sector_data,
                         earnings_map, ovl_px):
    print("\n[CASH-CONSTRAINED V7.5]")
    print("All overlays and MR positions compete for the same $100k cash pool.")

    all_dates = sorted(set().union(*[set(df.index) for df in price_data.values()]))
    tom_set = build_tom_set(all_dates)
    min_bars = MA_WINDOW + VOL_MA_PERIOD + ATR_PERIOD + MIN_CONSEC_DOWN + 5
    signals = {t: generate_signals(df) for t, df in price_data.items()
               if len(df) > min_bars}
    spy_regime = spy_df["spy_ok"].to_dict()
    spy_close  = spy_df["Close"].squeeze()
    spy_ma200_s = spy_df["Close"].squeeze().rolling(200).mean()
    vix_close  = vix_df["Close"].squeeze()

    pv = INITIAL_CAPITAL
    open_pos = {}; trades = []; cool = {}
    last_vs = None; last_vc = None

    # Hedge state
    pr = None; prd = None; pn = 0.0; pms = 9999.0; pds = 0
    alo = 0.05; ahi = 0.15
    vd = 0; vr = None; vrd = None; vn = 0.0; vpk = 0.0; vpm = 0.0

    # Overlay state (cash deployed in each)
    overlay_cash = {  # tracks current cash deployed in each overlay
        "gold": 0.0, "tlt": 0.0, "secrot": 0.0,
        "factor": 0.0, "pdbc": 0.0, "hyg": 0.0, "zroz": 0.0,
    }
    gold_in = False; tlt_in = False; pdbc_in = False
    hyg_in  = False; zroz_in = False
    secrot_sectors = set(); factor_etf = None
    prev_secrot_mon = None; prev_factor_mon = None

    peak = None; dd = 0.0

    from tqdm import tqdm

    for today in tqdm(all_dates, desc="Cash-Constrained V7.5"):
        spy_ok  = spy_regime.get(today, True)
        paused, last_vs  = check_vix_spike(today, vix_df, last_vs)
        vel_paused, last_vc = _vel(today, spy_df, last_vc)

        if peak is None:
            peak = pv if pv != INITIAL_CAPITAL else None
        elif pv > peak:
            peak = pv
        dd = (pv - peak) / peak if peak else 0.0

        ma200v = spy_ma200_s.loc[today] if today in spy_ma200_s.index else np.nan
        spyp   = float(spy_close.loc[today]) if today in spy_close.index else np.nan
        spy_above = not np.isnan(ma200v) and not np.isnan(spyp) and spyp > ma200v
        vix_now = get_vix_level(today, vix_df)

        # ── SPY put spread cost (deducted from pv, not tracked as deployed) ──
        vpx = float(vix_close.loc[today]) if today in vix_close.index else None
        spx = float(spy_close.loc[today]) if today in spy_close.index else None
        if spx:
            if pr is None or pds >= PUT_SPREAD_RENEW_DAYS:
                alo, ahi = _get_put_strikes(vix_now)
                prem = pv * PUT_SPREAD_COST_PCT; pv -= prem
                pr = spx; prd = today; pn = pv; pms = spx; pds = 0
                trades.append({"ticker":"SPY_PUT_SPREAD","entry_date":today,
                    "exit_date":today,"entry_price":spx,"exit_price":spx,
                    "shares":0,"commission":0,"pnl_usd":-prem,
                    "pnl_pct":-PUT_SPREAD_COST_PCT*100,"days_held":0,
                    "exit_reason":"put_premium","tier":0,"consec_down":0,
                    "portfolio_val":pv})
            else:
                pds += 1; pms = min(pms, spx)
                if pds == PUT_SPREAD_RENEW_DAYS - 1:
                    pay_pct = _put_payout(pr, pms, alo, ahi)
                    if pay_pct > 0:
                        pay = pn * pay_pct; pv += pay
                        trades.append({"ticker":"SPY_PUT_SPREAD","entry_date":prd,
                            "exit_date":today,"entry_price":pr,"exit_price":pms,
                            "shares":0,"commission":0,"pnl_usd":round(pay,2),
                            "pnl_pct":round(pay_pct*100,4),"days_held":pds,
                            "exit_reason":"put_payout","tier":0,"consec_down":0,
                            "portfolio_val":pv})

        # ── VIX call spread cost ──────────────────────────────────────────
        if vpx:
            cost_pct = VIX_CALL_COST_NORMAL
            if "^VIX3M" in ovl_px and today in ovl_px["^VIX3M"].index:
                if vpx > float(ovl_px["^VIX3M"].loc[today]):
                    cost_pct = VIX_CALL_COST_BACKWARDATION
            if vr is None or vd >= VIX_CALL_RENEW_DAYS:
                prem = pv * cost_pct; pv -= prem
                vr = vpx; vrd = today; vn = pv; vpk = vpx; vpm = prem; vd = 0
                trades.append({"ticker":"VIX_CALL_SPREAD","entry_date":today,
                    "exit_date":today,"entry_price":vpx,"exit_price":vpx,
                    "shares":0,"commission":0,"pnl_usd":-prem,
                    "pnl_pct":-cost_pct*100,"days_held":0,
                    "exit_reason":"vix_call_premium","tier":0,"consec_down":0,
                    "portfolio_val":pv})
            else:
                vd += 1; vpk = max(vpk, vpx)
                if vd == VIX_CALL_RENEW_DAYS - 1:
                    mult = _vix_call_mult(vr, vpk)
                    if mult > 0:
                        pay = vpm * mult; pv += pay
                        trades.append({"ticker":"VIX_CALL_SPREAD","entry_date":vrd,
                            "exit_date":today,"entry_price":vr,"exit_price":vpk,
                            "shares":0,"commission":0,"pnl_usd":round(pay,2),
                            "pnl_pct":round(mult*cost_pct*100,4),"days_held":vd,
                            "exit_reason":"vix_call_payout","tier":0,"consec_down":0,
                            "portfolio_val":pv})

        # ── Compute current MR cash deployed ─────────────────────────────
        mr_deployed = sum(
            pos["shares_remaining"] * signals[t].loc[today, "Close"]
            if t in signals and today in signals[t].index
            else pos["shares_remaining"] * pos["entry_price"]
            for t, pos in open_pos.items()
        )

        # ── Overlay daily P&L (mark existing positions to market) ─────────
        # GOLD
        if "GLD" in ovl_px and "TLT" in ovl_px and today in ovl_px["GLD"].index:
            gld = ovl_px["GLD"]; tlt_s = ovl_px["TLT"]
            ma200 = float(gld.rolling(200).mean().loc[today]) if today in gld.index else np.nan
            slope = (float(tlt_s.rolling(20).mean().diff(20).loc[today])
                     if today in tlt_s.index else np.nan)
            trend = not np.isnan(ma200) and float(gld.loc[today]) > ma200
            carry = np.isnan(slope) or slope >= 0
            should_be_in = trend and carry

            if gold_in and not should_be_in:
                # Exit: return cash to pv
                gold_in = False
                pv += overlay_cash["gold"]
                overlay_cash["gold"] = 0.0
            elif not gold_in and should_be_in:
                # Entry: deploy cash
                deploy = pv * GOLD_ALLOC_PCT
                if deploy <= (pv - mr_deployed - sum(overlay_cash.values())) * 0.9:
                    gold_in = True
                    overlay_cash["gold"] = deploy
                    pv -= deploy  # cash leaves portfolio, tracked separately
            elif gold_in and today in gld.index:
                # Mark to market daily
                ret = float(gld.pct_change().loc[today])
                if not np.isnan(ret):
                    pnl = overlay_cash["gold"] * ret
                    overlay_cash["gold"] += pnl
                    pv += pnl
                    if abs(pnl) > 0.01:
                        trades.append({"ticker":"OVL_GOLD","entry_date":today,
                            "exit_date":today,"entry_price":float(gld.loc[today]),
                            "exit_price":float(gld.loc[today]),"shares":0,
                            "commission":0,"pnl_usd":round(pnl,4),
                            "pnl_pct":ret*100,"days_held":1,
                            "exit_reason":"gold_daily","tier":0,
                            "consec_down":0,"portfolio_val":pv})

        # TLT Bear
        if "TLT" in ovl_px and today in ovl_px["TLT"].index:
            tlt_s = ovl_px["TLT"]; price = float(tlt_s.loc[today])
            ma50  = float(tlt_s.rolling(50).mean().loc[today]) \
                    if today in tlt_s.index else np.nan
            should_be_in = (not spy_above) and not np.isnan(ma50) and price > ma50
            if tlt_in and not should_be_in:
                tlt_in = False
                ret = float(tlt_s.pct_change().loc[today]) if today in tlt_s.index else 0.0
                if not np.isnan(ret):
                    pnl = overlay_cash["tlt"] * ret
                    overlay_cash["tlt"] += pnl; pv += pnl
                pv += overlay_cash["tlt"]
                overlay_cash["tlt"] = 0.0
            elif not tlt_in and should_be_in:
                deploy = pv * TLT_ALLOC_PCT
                avail  = pv - mr_deployed - sum(overlay_cash.values())
                if deploy <= avail * 0.9:
                    tlt_in = True; overlay_cash["tlt"] = deploy; pv -= deploy
            elif tlt_in:
                ret = float(tlt_s.pct_change().loc[today])
                if not np.isnan(ret):
                    pnl = overlay_cash["tlt"] * ret
                    overlay_cash["tlt"] += pnl; pv += pnl
                    if abs(pnl) > 0.01:
                        trades.append({"ticker":"OVL_TLT_BEAR","entry_date":today,
                            "exit_date":today,"entry_price":price,"exit_price":price,
                            "shares":0,"commission":0,"pnl_usd":round(pnl,4),
                            "pnl_pct":ret*100,"days_held":1,
                            "exit_reason":"tlt_bear_daily","tier":0,
                            "consec_down":0,"portfolio_val":pv})

        # SECROT (simplified: monthly rebalance, top-3 sectors, 3% each)
        if spy_above:
            available = [s for s in SPDR_SECTORS if s in ovl_px]
            mon = (pd.Timestamp(today).year, pd.Timestamp(today).month)
            if mon != prev_secrot_mon:
                prev_secrot_mon = mon
                # Rebalance: compute new top-3
                moms = {}
                for s in available:
                    if today in ovl_px[s].index:
                        m = float(ovl_px[s].pct_change(SECROT_MOM_DAYS).loc[today])
                        if not np.isnan(m): moms[s] = m
                new_top = set(sorted(moms, key=moms.get, reverse=True)[:SECROT_TOP_N])
                # On rebalance: liquidate ALL secrot, redeploy into new top-3
                # This simplifies accounting and matches live behavior
                if overlay_cash["secrot"] > 0:
                    pv += overlay_cash["secrot"]
                    overlay_cash["secrot"] = 0.0
                # Redeploy into new top-3 if bull regime
                avail_cash = pv - mr_deployed - sum(overlay_cash.values())
                new_deploy = pv * SECROT_ALLOC * len(new_top)
                if new_top and new_deploy <= avail_cash * 0.9:
                    overlay_cash["secrot"] = new_deploy
                    pv -= new_deploy
                secrot_sectors = new_top

            # Daily mark-to-market for held sectors
            for s in secrot_sectors:
                if s in ovl_px and today in ovl_px[s].index:
                    ret = float(ovl_px[s].pct_change().loc[today])
                    if np.isnan(ret): continue
                    pnl = (overlay_cash["secrot"] / max(1,len(secrot_sectors))) * ret
                    overlay_cash["secrot"] += pnl; pv += pnl
                    if abs(pnl) > 0.01:
                        trades.append({"ticker":f"OVL_SECROT_{s}","entry_date":today,
                            "exit_date":today,"entry_price":float(ovl_px[s].loc[today]),
                            "exit_price":float(ovl_px[s].loc[today]),"shares":0,
                            "commission":0,"pnl_usd":round(pnl,4),"pnl_pct":ret*100,
                            "days_held":1,"exit_reason":"secrot_daily","tier":0,
                            "consec_down":0,"portfolio_val":pv})
        else:
            # Bear regime: exit all SECROT
            if secrot_sectors and overlay_cash["secrot"] > 0:
                pv += overlay_cash["secrot"]
                overlay_cash["secrot"] = 0.0
                secrot_sectors = set()
                prev_secrot_mon = None

        # FACTOR
        if spy_above and "QQQ" in ovl_px and "IWM" in ovl_px:
            mon = (pd.Timestamp(today).year, pd.Timestamp(today).month)
            if mon != prev_factor_mon:
                prev_factor_mon = mon
                qm = float(ovl_px["QQQ"].pct_change(FACTOR_MOM_DAYS).loc[today]) \
                     if today in ovl_px["QQQ"].index else np.nan
                im = float(ovl_px["IWM"].pct_change(FACTOR_MOM_DAYS).loc[today]) \
                     if today in ovl_px["IWM"].index else np.nan
                new_etf = None
                if not np.isnan(qm) and not np.isnan(im):
                    new_etf = "QQQ" if qm >= im else "IWM"
                if new_etf != factor_etf:
                    # Return old
                    if factor_etf and overlay_cash["factor"] > 0:
                        pv += overlay_cash["factor"]
                        overlay_cash["factor"] = 0.0
                    # Deploy new
                    if new_etf:
                        deploy = pv * FACTOR_ALLOC
                        avail  = pv - mr_deployed - sum(overlay_cash.values())
                        if deploy <= avail * 0.9:
                            overlay_cash["factor"] = deploy; pv -= deploy
                    factor_etf = new_etf
            if factor_etf and factor_etf in ovl_px and today in ovl_px[factor_etf].index:
                ret = float(ovl_px[factor_etf].pct_change().loc[today])
                if not np.isnan(ret) and overlay_cash["factor"] > 0:
                    pnl = overlay_cash["factor"] * ret
                    overlay_cash["factor"] += pnl; pv += pnl
                    if abs(pnl) > 0.01:
                        trades.append({"ticker":f"OVL_FACTOR_{factor_etf}",
                            "entry_date":today,"exit_date":today,
                            "entry_price":float(ovl_px[factor_etf].loc[today]),
                            "exit_price":float(ovl_px[factor_etf].loc[today]),
                            "shares":0,"commission":0,"pnl_usd":round(pnl,4),
                            "pnl_pct":ret*100,"days_held":1,
                            "exit_reason":"factor_daily","tier":0,
                            "consec_down":0,"portfolio_val":pv})
        elif not spy_above and overlay_cash["factor"] > 0:
            pv += overlay_cash["factor"]
            overlay_cash["factor"] = 0.0
            factor_etf = None

        # PDBC
        if "PDBC" in ovl_px and today in ovl_px["PDBC"].index:
            s = ovl_px["PDBC"]; price = float(s.loc[today])
            ma100 = float(s.rolling(PDBC_MA_WINDOW).mean().loc[today]) \
                    if today in s.index else np.nan
            dbc_s = ovl_px.get("DBC", s)
            dbc_mom = float(dbc_s.pct_change(DBC_MOM_DAYS).loc[today]) \
                      if today in dbc_s.index else np.nan
            trend = not np.isnan(ma100) and price > ma100
            mom_ok = np.isnan(dbc_mom) or dbc_mom > 0
            should_be_in = trend and mom_ok
            if pdbc_in and not should_be_in:
                pdbc_in = False; pv += overlay_cash["pdbc"]
                overlay_cash["pdbc"] = 0.0
            elif not pdbc_in and should_be_in:
                deploy = pv * PDBC_ALLOC_PCT
                avail  = pv - mr_deployed - sum(overlay_cash.values())
                if deploy <= avail * 0.9:
                    pdbc_in = True; overlay_cash["pdbc"] = deploy; pv -= deploy
            elif pdbc_in:
                ret = float(s.pct_change().loc[today])
                if not np.isnan(ret):
                    pnl = overlay_cash["pdbc"] * ret
                    overlay_cash["pdbc"] += pnl; pv += pnl
                    if abs(pnl) > 0.01:
                        trades.append({"ticker":"OVL_PDBC","entry_date":today,
                            "exit_date":today,"entry_price":price,"exit_price":price,
                            "shares":0,"commission":0,"pnl_usd":round(pnl,4),
                            "pnl_pct":ret*100,"days_held":1,
                            "exit_reason":"pdbc_daily","tier":0,
                            "consec_down":0,"portfolio_val":pv})

        # HYG
        if spy_above and "HYG" in ovl_px and "LQD" in ovl_px and \
                today in ovl_px["HYG"].index and today in ovl_px["LQD"].index:
            hyg_s = ovl_px["HYG"]; lqd_s = ovl_px["LQD"]
            ratio = hyg_s / lqd_s
            ratio_ma = ratio.rolling(HYG_RATIO_WINDOW).mean()
            if today in ratio_ma.index and not np.isnan(ratio_ma.loc[today]):
                signal_in = float(ratio.loc[today]) > float(ratio_ma.loc[today])
                if hyg_in and not signal_in:
                    hyg_in = False; pv += overlay_cash["hyg"]
                    overlay_cash["hyg"] = 0.0
                elif not hyg_in and signal_in:
                    deploy = pv * HYG_ALLOC_PCT
                    avail  = pv - mr_deployed - sum(overlay_cash.values())
                    if deploy <= avail * 0.9:
                        hyg_in = True; overlay_cash["hyg"] = deploy; pv -= deploy
                elif hyg_in:
                    ret = float(hyg_s.pct_change().loc[today])
                    if not np.isnan(ret):
                        pnl = overlay_cash["hyg"] * ret
                        overlay_cash["hyg"] += pnl; pv += pnl
                        if abs(pnl) > 0.01:
                            trades.append({"ticker":"OVL_HYG","entry_date":today,
                                "exit_date":today,
                                "entry_price":float(hyg_s.loc[today]),
                                "exit_price":float(hyg_s.loc[today]),
                                "shares":0,"commission":0,"pnl_usd":round(pnl,4),
                                "pnl_pct":ret*100,"days_held":1,
                                "exit_reason":"hyg_daily","tier":0,
                                "consec_down":0,"portfolio_val":pv})
        elif not spy_above and hyg_in:
            hyg_in = False; pv += overlay_cash["hyg"]
            overlay_cash["hyg"] = 0.0

        # ZROZ
        if "ZROZ" in ovl_px and today in ovl_px["ZROZ"].index:
            tlt_s2 = ovl_px.get("TLT", ovl_px["ZROZ"])
            tlt_5d = float(tlt_s2.pct_change(5).loc[today]) \
                     if today in tlt_s2.index else np.nan
            vix_ok = vix_now > ZROZ_VIX_THRESH
            tlt_ok = not np.isnan(tlt_5d) and tlt_5d > ZROZ_TLT_5D_MIN
            should_be_in = vix_ok and tlt_ok
            if zroz_in and not vix_ok:
                zroz_in = False; pv += overlay_cash["zroz"]
                overlay_cash["zroz"] = 0.0
            elif not zroz_in and should_be_in:
                deploy = pv * ZROZ_ALLOC_PCT
                avail  = pv - mr_deployed - sum(overlay_cash.values())
                if deploy <= avail * 0.9:
                    zroz_in = True; overlay_cash["zroz"] = deploy; pv -= deploy
            elif zroz_in:
                ret = float(ovl_px["ZROZ"].pct_change().loc[today])
                if not np.isnan(ret):
                    pnl = overlay_cash["zroz"] * ret
                    overlay_cash["zroz"] += pnl; pv += pnl
                    if abs(pnl) > 0.01:
                        trades.append({"ticker":"OVL_ZROZ","entry_date":today,
                            "exit_date":today,
                            "entry_price":float(ovl_px["ZROZ"].loc[today]),
                            "exit_price":float(ovl_px["ZROZ"].loc[today]),
                            "shares":0,"commission":0,"pnl_usd":round(pnl,4),
                            "pnl_pct":ret*100,"days_held":1,
                            "exit_reason":"zroz_daily","tier":0,
                            "consec_down":0,"portfolio_val":pv})

        # ── MR exits (return cash) ────────────────────────────────────────
        pv = _run_exits(today, signals, open_pos, trades, pv, cool)

        # ── MR entries (constrained by available cash) ────────────────────
        if not spy_ok or paused or vel_paused or len(open_pos) >= MAX_POSITIONS:
            continue

        # Recompute available cash after exits and overlay updates
        mr_deployed_now = sum(
            pos["shares_remaining"] * (
                float(signals[t].loc[today, "Close"])
                if t in signals and today in signals[t].index
                else pos["entry_price"]
            )
            for t, pos in open_pos.items()
        )
        total_overlay_deployed = sum(overlay_cash.values())
        cash_free = pv - mr_deployed_now - total_overlay_deployed

        if cash_free < 500:
            continue  # No cash available

        tom_today = today in tom_set
        dow = pd.Timestamp(today).dayofweek
        cands = _build_cands(today, signals, open_pos, cool,
                             earnings_map, sector_data, vix_now)
        _enter_constrained(today, signals, cands, open_pos, cool, pv,
                          cash_free, vix_df, dd, tom_today, dow, trades)

    return pd.DataFrame(trades)


def report(trades_df, label="CASH-CONSTRAINED V7.5"):
    OVL = {"SPY_PUT_SPREAD", "VIX_CALL_SPREAD"}
    mr = trades_df[~trades_df["ticker"].isin(OVL) &
                   ~trades_df["ticker"].str.startswith("OVL_")]
    mr_m, _ = compute_metrics(mr)
    comb = _combined_metrics(trades_df)

    def s(p): return trades_df[trades_df["ticker"].str.startswith(p)]["pnl_usd"].sum() \
               if not trades_df.empty else 0.0

    # Comparison targets
    V75_NOTIONAL_EQ   = 77_488_411
    V75_NOTIONAL_CAGR = 34.75

    W = 72
    print("\n" + "="*W)
    print(f" {label}")
    print(f" Overlays and MR positions compete for the same ${INITIAL_CAPITAL:,.0f} cash pool")
    print("="*W)
    dc = comb["cagr"] - V75_NOTIONAL_CAGR
    de = comb["final_equity"] - V75_NOTIONAL_EQ
    print(f"\n {'Metric':<38} {'V7.5 Notional':>16} {'Cash-Constrained':>16}")
    print(" "+"-"*(W-2))
    print(f" {'CAGR (MR-only)':<38} {'28.88%':>16} {mr_m['cagr_pct']:>15.2f}%")
    print(f" {'CAGR (combined)':<38} {V75_NOTIONAL_CAGR:>15.2f}% {comb['cagr']:>15.2f}%  ({dc:>+.2f}pp)")
    print(f" {'Final Equity':<38} ${V75_NOTIONAL_EQ:>14,.0f} ${comb['final_equity']:>14,.0f}")
    print(f" {'Max Drawdown':<38} {'-57.25%':>16} {comb['max_dd']:>15.2f}%")
    print(f" {'Sharpe':<38} {'1.08':>16} {comb['sharpe']:>16.2f}")
    print(f" {'Win Rate (MR-only)':<38} {'60.24%':>16} {mr_m['win_rate_pct']:>15.2f}%")
    print(f" {'Total MR trades':<38} {'22,041':>16} {mr_m['total_trades']:>16,}")

    print(f"\n Overlay P&L (cash-constrained):")
    rows = [
        ("SPY put spread",     "SPY_PUT"),
        ("VIX call spread",    "VIX_CALL"),
        ("GOLD",               "OVL_GOLD"),
        ("TLT Bear",           "OVL_TLT"),
        ("SECROT",             "OVL_SECROT"),
        ("Factor",             "OVL_FACTOR"),
        ("PDBC",               "OVL_PDBC"),
        ("HYG",                "OVL_HYG"),
        ("ZROZ",               "OVL_ZROZ"),
    ]
    total_ovl = 0
    for lbl, prefix in rows:
        net = round(s(prefix), 2); total_ovl += net
        print(f"  {lbl:<24}: ${net:>+14,.0f}")
    print(f"  {'TOTAL overlays':<24}: ${total_ovl:>+14,.0f}")
    mr_pnl = round(s(''), 2)
    print(f"  {'MR trades P&L':<24}: ${mr_pnl:>+14,.0f}")

    # Year-by-year
    eq_df = comb["equity_curve"].copy()
    eq_df["year"] = pd.to_datetime(eq_df["date"]).dt.year
    print(f"\n Year-by-Year (cash-constrained):")
    print(f" {'Year':<5} {'End Equity':>16} {'Annual P&L':>14}")
    print(" "+"-"*38)
    prev_eq = INITIAL_CAPITAL
    for yr in sorted(eq_df["year"].unique()):
        yr_eq = eq_df[eq_df["year"]==yr]["equity"].iloc[-1]
        print(f" {yr:<5} ${yr_eq:>14,.0f} ${yr_eq-prev_eq:>+13,.0f}")
        prev_eq = yr_eq
    print("="*W)

    return {
        "cagr_mr":        mr_m["cagr_pct"],
        "cagr_comb":      comb["cagr"],
        "final_equity":   comb["final_equity"],
        "max_dd":         comb["max_dd"],
        "sharpe":         comb["sharpe"],
        "win_rate":       mr_m["win_rate_pct"],
        "total_trades":   mr_m["total_trades"],
        "vs_notional_cagr_delta": round(dc, 2),
        "vs_notional_equity_delta": round(de, 2),
    }


def main():
    print("\n" + "="*70)
    print(" V7.5 CASH-CONSTRAINED BACKTEST")
    print(" All overlays compete with MR positions for the same cash pool")
    print(" This models a real $100k cash account accurately")
    print("="*70)

    universe    = get_universe()
    price_data  = download_prices(universe)
    spy_df, vix_df, sector_data = download_reference_data()
    earnings_map = build_earnings_dates(list(price_data.keys()))
    ovl_px      = download_overlay_data()

    trades_df = run_cash_constrained(
        price_data, spy_df, vix_df, sector_data, earnings_map, ovl_px)

    trades_df.to_csv(OUTPUT_DIR / "trades_cash_constrained.csv", index=False)

    metrics = report(trades_df)
    comb    = _combined_metrics(trades_df)
    comb["equity_curve"].to_csv(OUTPUT_DIR / "equity_curve_cash_constrained.csv", index=False)

    summary = {
        "run_date": datetime.date.today().isoformat(),
        "version":  "V7.5-CashConstrained",
        "description": (
            "All overlays deploy real cash from the same pool as MR positions. "
            "Cash available for MR = pv - overlay_deployed - put/vix costs. "
            "This models a real $100k brokerage account."
        ),
        "v75_notional": {"final_equity": 77_488_411, "cagr_comb": 34.75,
                         "max_dd": -57.25},
        "results": metrics,
    }
    with open(OUTPUT_DIR / "summary_cash_constrained.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\n All outputs → {OUTPUT_DIR.resolve()}")
    print(" Key question answered: what CAGR is realistic with $100k cash account?")


if __name__ == "__main__":
    main()
