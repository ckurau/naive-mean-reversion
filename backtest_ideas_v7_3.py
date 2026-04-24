# backtest_ideas_v7_3.py
#
# Ideas V7.3 — Idea G (V48 baseline) + GOLD overlay + SECROT overlay
#              Reported as ONE combined equity curve and ONE combined MaxDD.
#
# Baseline: Idea G = V47 + dynamic SPY put spread strikes + monthly VIX call spread
#           This is the confirmed V48 best result:
#           $18,323,346 final equity | CAGR 24.38% (MR-only) | MaxDD -56.91% (combined)
#
# New overlays (additive P&L on top of Idea G combined equity):
#   [OVL-GOLD]   Long GLD when GLD > 200d MA AND TLT 20d slope >= 0 (rates falling)
#                Allocation: 7% of CURRENT combined portfolio equity per in-position day
#   [OVL-SECROT] Top-3 SPDR sector ETFs by 63d momentum, monthly rebalance
#                Only when SPY > SPY 200d MA. 3% per sector (9% total).
#                Allocation: 3% of CURRENT combined portfolio equity per active day
#
# Output: single combined equity (MR + SPY puts + VIX calls + GOLD + SECROT)
#         MaxDD and final equity reflect ALL overlays working simultaneously.
#
# Comparison targets:
#   V48/Idea G baseline (combined): $18,323,346 | CAGR 24.38% | MaxDD -56.91%
#   V49 MR+GOLD+SECROT (separate):  $5,424,055  | CAGR 20.42% | MaxDD -50.12%
#
# Run: python backtest_ideas_v7_3.py
# GitHub Actions: ideas_v7_3_backtest.yml

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

OUTPUT_DIR = Path("results_ideas_v7_3")
OUTPUT_DIR.mkdir(exist_ok=True)

# ---------------------------------------------------------------------------
# Overlay config
# ---------------------------------------------------------------------------
# [OVL-GOLD]
GOLD_ALLOC_PCT   = 0.07    # 7% of combined portfolio equity while in position

# [OVL-SECROT]
SECROT_ALLOC_PCT = 0.03    # 3% per sector
SECROT_TOP_N     = 3       # top-3 sectors by momentum
SECROT_MOM_DAYS  = 63      # 3-month momentum window

SPDR_SECTORS = ["XLK","XLV","XLF","XLE","XLI","XLY","XLP","XLU","XLB","XLRE","XLC"]

# ---------------------------------------------------------------------------
# Idea G: SPY put spread parameters (dynamic strikes = Idea D)
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
    """Dynamic strikes based on VIX regime (Idea D)."""
    if vix < 15.0:   return 0.03, 0.13
    if vix <= 25.0:  return 0.05, 0.15
    return 0.08, 0.20

# ---------------------------------------------------------------------------
# Idea G: VIX call spread parameters (Idea A)
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
# Overlay price download
# ---------------------------------------------------------------------------
def download_overlay_prices() -> dict:
    tickers = ["GLD", "TLT", "SPY"] + SPDR_SECTORS
    print(f"\n[Overlays] Downloading: {tickers} ...")
    raw = yf.download(tickers, start=START_DATE, end=END_DATE,
                      auto_adjust=True, progress=False, threads=True)
    prices = {}
    if isinstance(raw.columns, pd.MultiIndex):
        for t in tickers:
            try:
                s = raw["Close"][t].dropna()
                if not s.empty:
                    prices[t] = s
            except Exception:
                pass
    print(f"[Overlays] Downloaded: {list(prices.keys())}")
    return prices

# ---------------------------------------------------------------------------
# Combined equity MaxDD helper
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
                "max_drawdown_combined_pct": 0.0, "equity_curve": eq}
    eq["peak"] = eq["equity"].cummax()
    eq["drawdown_pct"] = (eq["equity"] - eq["peak"]) / eq["peak"] * 100.0
    start = pd.to_datetime(df["entry_date"].min())
    end   = pd.to_datetime(df["exit_date"].max())
    years = max((end - start).days / 365.25, 1e-6)
    # CAGR on combined equity
    cagr  = (eq["equity"].iloc[-1] / INITIAL_CAPITAL) ** (1 / years) - 1
    # Sharpe on combined equity daily-ish returns
    eq_s  = eq.set_index("date")["equity"]
    eq_monthly = eq_s.resample("ME").last().ffill().pct_change().dropna()
    sharpe = (eq_monthly.mean() / eq_monthly.std() * np.sqrt(12)
              if eq_monthly.std() > 0 else 0)
    return {
        "final_equity_combined":      round(float(eq["equity"].iloc[-1]), 2),
        "max_drawdown_combined_pct":  round(float(eq["drawdown_pct"].min()), 2),
        "cagr_combined_pct":          round(cagr * 100, 2),
        "sharpe_combined":            round(sharpe, 2),
        "equity_curve":               eq,
    }

# ---------------------------------------------------------------------------
# MR exits helper (identical to v7.2)
# ---------------------------------------------------------------------------
def _run_exits(today, signals, open_pos, trades, pv, cool):
    to_close = []
    for tkr, pos in open_pos.items():
        if tkr not in signals or today not in signals[tkr].index:
            continue
        row = signals[tkr].loc[today]
        ep  = pos["entry_price"]; xp = float(row["Close"])
        dh  = (pd.Timestamp(today) - pd.Timestamp(pos["entry_date"])).days
        pp  = (xp - ep) / ep
        sr  = pos["shares_remaining"]
        early = dh < MIN_HOLD_BEFORE_EXIT
        ts    = dh >= pos["hold_days"]
        ph    = (not early) and pp >= pos["profit_target"]

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
            pv += pnl
            pos["shares_remaining"] -= psh
            pos["partial_done"]   = True
            pos["profit_target"] *= 2
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
            if ts:
                cool[tkr] = today
            to_close.append(tkr)
    for tkr in to_close:
        del open_pos[tkr]
    return pv

def _vel(today, spy_df, last_vc):
    paused = False
    try:
        if today in spy_df.index:
            v = float(spy_df.loc[today, "spy_5d_ret"])
            if not np.isnan(v) and v < VELOCITY_CRASH_5D_THRESHOLD:
                last_vc = today
        if last_vc and (pd.Timestamp(today) - pd.Timestamp(last_vc)).days <= VELOCITY_CRASH_PAUSE_DAYS:
            paused = True
    except Exception:
        pass
    return paused, last_vc

def _dd_upd(pv, peak):
    if peak is None:
        return (pv, 0.0) if pv != INITIAL_CAPITAL else (None, 0.0)
    if pv > peak:
        return pv, 0.0
    return peak, (pv - peak) / peak

def _build_cands(today, signals, open_pos, cool, earnings_map, sector_data, vix_now):
    cands = []
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
        rsi2 = float(row["rsi2"]); atr = float(row["atr_pct"])
        score = rsi2 / atr if atr > 0 else rsi2 * 1000
        cands.append((score, tkr, int(row["consec_down"]), rsi2))
    return sorted(cands, key=lambda x: x[0])

def _enter(today, signals, cands, open_pos, cool, pv, vix_df, dd, tom_today, dow):
    n = len(cands); top_n = max(1, int(n * TOP_SIGNAL_PCT))
    for rank, (score, tkr, cv, rv) in enumerate(cands):
        if len(open_pos) >= MAX_POSITIONS:
            break
        tkr_df = signals[tkr]
        idx    = tkr_df.index.get_loc(today)
        if idx + 1 >= len(tkr_df):
            continue
        ep = float(tkr_df.iloc[idx + 1]["Open"])
        if ep <= 0:
            continue
        pc = float(tkr_df.iloc[idx]["Close"])
        gp = (ep - pc) / pc
        if gp < GAP_DOWN_MAX or gp > GAP_UP_MAX:
            continue
        sm = 1.0
        if n >= MIN_CANDIDATES_FOR_C5 and rank < top_n:
            sm = TOP_SIGNAL_MULTIPLIER
        if tom_today:
            sm *= TOM_MULT
        sm *= DOW_MULT.get(dow, 1.0)
        tier = get_tier(cv)
        size = get_position_size(today, vix_df, dd, multiplier=sm,
                                 hard_cap=TOP_SIGNAL_HARD_CAP)
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
# GOLD overlay P&L — computed daily against combined portfolio value
# ---------------------------------------------------------------------------
def compute_gold_overlay(all_dates, ovl_px, combined_pv_by_date):
    """
    Generates daily SPY trade records for GOLD overlay.
    Sizing = GOLD_ALLOC_PCT * combined portfolio value on that day.
    combined_pv_by_date: dict {date -> portfolio value after MR+put+vxc on that day}
    """
    if "GLD" not in ovl_px or "TLT" not in ovl_px:
        print("[OVL-GOLD] Missing GLD or TLT — skipping")
        return []

    gld     = ovl_px["GLD"]
    tlt     = ovl_px["TLT"]
    gld_ma200 = gld.rolling(200).mean()
    tlt_slope = tlt.rolling(20).mean().diff(20)   # positive = TLT rising = rates falling
    gld_ret   = gld.pct_change()

    trades = []
    in_pos = False

    for dt in all_dates:
        if dt not in gld.index or dt not in tlt.index:
            continue
        ma200 = gld_ma200.get(dt, np.nan)
        slope = tlt_slope.get(dt, np.nan)
        if pd.isna(ma200):
            continue
        trend = float(gld.loc[dt]) > float(ma200)
        carry = pd.isna(slope) or float(slope) >= 0

        if not in_pos and trend and carry:
            in_pos = True
        if in_pos and not trend:
            in_pos = False

        if in_pos and dt in gld_ret.index and not pd.isna(gld_ret.loc[dt]):
            pv_today = combined_pv_by_date.get(dt, INITIAL_CAPITAL)
            alloc    = pv_today * GOLD_ALLOC_PCT
            pnl      = float(gld_ret.loc[dt]) * alloc
            trades.append({
                "ticker": "OVL_GOLD", "entry_date": dt, "exit_date": dt,
                "entry_price": float(gld.loc[dt]), "exit_price": float(gld.loc[dt]),
                "shares": 0, "commission": 0,
                "pnl_usd": round(pnl, 4), "pnl_pct": float(gld_ret.loc[dt]) * 100,
                "days_held": 1, "exit_reason": "gold_daily",
                "tier": 0, "consec_down": 0,
                "portfolio_val": pv_today + pnl,
            })
    total = sum(t["pnl_usd"] for t in trades)
    print(f"[OVL-GOLD]   {len(trades)} daily records | total P&L ${total:+,.0f}")
    return trades

# ---------------------------------------------------------------------------
# SECROT overlay P&L
# ---------------------------------------------------------------------------
def compute_secrot_overlay(all_dates, ovl_px, combined_pv_by_date):
    """
    Monthly rebalance into top-3 SPDR sectors by 63d momentum.
    Only when SPY > SPY 200d MA. 3% per sector = 9% total when fully allocated.
    Sizing = SECROT_ALLOC_PCT * combined portfolio value on each active day.
    """
    available = [s for s in SPDR_SECTORS if s in ovl_px]
    if len(available) < 3:
        print("[OVL-SECROT] Fewer than 3 sector ETFs — skipping")
        return []

    spy_close  = ovl_px.get("SPY")
    spy_ma200  = spy_close.rolling(200).mean() if spy_close is not None else None
    sect_ret   = {s: ovl_px[s].pct_change() for s in available}
    sect_mom   = {s: ovl_px[s].pct_change(SECROT_MOM_DAYS) for s in available}

    trades    = []
    weights   = {s: 0.0 for s in available}
    prev_mon  = None

    for dt in all_dates:
        if spy_close is None or dt not in spy_close.index:
            continue
        spy_p  = float(spy_close.loc[dt])
        ma200  = float(spy_ma200.loc[dt]) if spy_ma200 is not None and dt in spy_ma200.index else np.nan
        in_bull = not np.isnan(ma200) and spy_p > ma200

        mon = (pd.Timestamp(dt).year, pd.Timestamp(dt).month)
        if mon != prev_mon:
            prev_mon = mon
            weights  = {s: 0.0 for s in available}
            if in_bull:
                moms  = {s: float(sect_mom[s].loc[dt])
                          for s in available
                          if dt in sect_mom[s].index and not pd.isna(sect_mom[s].loc[dt])}
                top3  = sorted(moms, key=moms.get, reverse=True)[:SECROT_TOP_N]
                for s in available:
                    weights[s] = 1.0 if s in top3 else 0.0

        if not in_bull:
            continue

        pv_today = combined_pv_by_date.get(dt, INITIAL_CAPITAL)
        for s in available:
            if weights[s] == 0:
                continue
            if dt not in sect_ret[s].index or pd.isna(sect_ret[s].loc[dt]):
                continue
            pnl = float(sect_ret[s].loc[dt]) * pv_today * SECROT_ALLOC_PCT
            trades.append({
                "ticker": f"OVL_SECROT_{s}", "entry_date": dt, "exit_date": dt,
                "entry_price": float(ovl_px[s].loc[dt]), "exit_price": float(ovl_px[s].loc[dt]),
                "shares": 0, "commission": 0,
                "pnl_usd": round(pnl, 4), "pnl_pct": float(sect_ret[s].loc[dt]) * 100,
                "days_held": 1, "exit_reason": "secrot_daily",
                "tier": 0, "consec_down": 0,
                "portfolio_val": pv_today + pnl,
            })

    total = sum(t["pnl_usd"] for t in trades)
    print(f"[OVL-SECROT] {len(trades)} daily records | total P&L ${total:+,.0f}")
    return trades

# ---------------------------------------------------------------------------
# MAIN: Idea G loop then GOLD + SECROT overlays
# ---------------------------------------------------------------------------
def run_idea_g_plus_overlays(price_data, spy_df, vix_df, sector_data,
                              earnings_map, ovl_px):
    print("\n[V7.3] Running Idea G (V48 baseline) + GOLD + SECROT overlays ...")
    print("       Combined equity = MR + SPY puts + VIX calls + GOLD + SECROT")

    all_dates = sorted(set().union(*[set(df.index) for df in price_data.values()]))
    tom_set   = build_tom_set(all_dates)
    min_bars  = MA_WINDOW + VOL_MA_PERIOD + ATR_PERIOD + MIN_CONSEC_DOWN + 5
    signals   = {tkr: generate_signals(df)
                 for tkr, df in price_data.items() if len(df) > min_bars}

    spy_regime  = spy_df["spy_ok"].to_dict()
    spy_close   = spy_df["Close"].squeeze()
    vix_close   = vix_df["Close"].squeeze()

    # Portfolio state
    pv   = INITIAL_CAPITAL
    peak = None; dd = 0.0
    open_pos = {}; trades = []; cool = {}
    last_vs = None; last_vc = None

    # SPY put spread state (dynamic strikes = Idea D)
    pr = None; prd = None; pn = 0.0; pms = 9999.0; pds = 0
    alo = PUT_SPREAD_LOWER_OTM; ahi = PUT_SPREAD_UPPER_OTM

    # VIX call spread state (Idea A)
    vd = 0; vr = None; vrd = None; vn = 0.0; vpk = 0.0; vpm = 0.0

    # Track combined portfolio value by date for overlay sizing
    combined_pv_by_date = {}

    print("[V7.3] Running main MR + Idea G loop ...")
    from tqdm import tqdm
    for today in tqdm(all_dates, desc="Idea G"):
        spy_ok = spy_regime.get(today, True)
        paused, last_vs = check_vix_spike(today, vix_df, last_vs)
        vel_paused, last_vc = _vel(today, spy_df, last_vc)
        peak_new, dd = _dd_upd(pv, peak)
        peak = peak_new if peak_new is not None else peak

        # ── SPY PUT SPREAD TICK (dynamic strikes) ───────────────────────────
        if today in spy_df.index:
            spx = float(spy_close.loc[today]) if today in spy_close.index else None
            if spx is not None:
                if pr is None or pds >= PUT_SPREAD_RENEW_DAYS:
                    alo, ahi = _get_put_strikes(get_vix_level(today, vix_df))
                    prem = pv * PUT_SPREAD_COST_PCT; pv -= prem
                    pr = spx; prd = today; pn = pv; pms = spx; pds = 0
                    trades.append({"ticker": "SPY_PUT_SPREAD", "entry_date": today,
                        "exit_date": today, "entry_price": spx, "exit_price": spx,
                        "shares": 0, "commission": 0, "pnl_usd": -prem,
                        "pnl_pct": -PUT_SPREAD_COST_PCT * 100, "days_held": 0,
                        "exit_reason": "put_premium", "tier": 0, "consec_down": 0,
                        "portfolio_val": pv, "put_lo": alo, "put_hi": ahi})
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
                                "portfolio_val": pv, "put_lo": alo, "put_hi": ahi})

        # ── VIX CALL SPREAD TICK ─────────────────────────────────────────────
        if today in vix_df.index:
            vpx = float(vix_close.loc[today]) if today in vix_close.index else None
            if vpx is not None:
                if vr is None or vd >= VIX_CALL_RENEW_DAYS:
                    prem = pv * VIX_CALL_COST_PCT; pv -= prem
                    vr = vpx; vrd = today; vn = pv; vpk = vpx; vpm = prem; vd = 0
                    trades.append({"ticker": "VIX_CALL_SPREAD", "entry_date": today,
                        "exit_date": today, "entry_price": vpx, "exit_price": vpx,
                        "shares": 0, "commission": 0, "pnl_usd": -prem,
                        "pnl_pct": -VIX_CALL_COST_PCT * 100, "days_held": 0,
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
                                "pnl_pct": round(mult * VIX_CALL_COST_PCT * 100, 4),
                                "days_held": vd, "exit_reason": "vix_call_payout",
                                "tier": 0, "consec_down": 0, "portfolio_val": pv})

        # ── MR EXITS ─────────────────────────────────────────────────────────
        pv = _run_exits(today, signals, open_pos, trades, pv, cool)

        # Record combined PV after MR + overlays (used for GOLD/SECROT sizing)
        combined_pv_by_date[today] = pv

        if not spy_ok or paused or vel_paused or len(open_pos) >= MAX_POSITIONS:
            continue

        # ── MR ENTRIES ───────────────────────────────────────────────────────
        vix_now   = get_vix_level(today, vix_df)
        tom_today = today in tom_set
        dow       = pd.Timestamp(today).dayofweek
        cands     = _build_cands(today, signals, open_pos, cool,
                                  earnings_map, sector_data, vix_now)
        _enter(today, signals, cands, open_pos, cool, pv, vix_df, dd, tom_today, dow)

    mr_put_vxc_df = pd.DataFrame(trades)
    print(f"[V7.3] Idea G loop complete — {len(trades)} records "
          f"(MR trades + put/VIX call records)")

    # ── GOLD + SECROT overlays (additive, sized on combined PV) ──────────────
    print("[V7.3] Computing GOLD overlay ...")
    gold_trades   = compute_gold_overlay(all_dates, ovl_px, combined_pv_by_date)

    print("[V7.3] Computing SECROT overlay ...")
    secrot_trades = compute_secrot_overlay(all_dates, ovl_px, combined_pv_by_date)

    # Combine everything
    all_trades_df = pd.concat(
        [mr_put_vxc_df,
         pd.DataFrame(gold_trades),
         pd.DataFrame(secrot_trades)],
        ignore_index=True
    )

    return all_trades_df, mr_put_vxc_df

# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------
def _overlay_breakdown(all_trades_df):
    """Print P&L split by overlay type."""
    overlay_tickers = {"SPY_PUT_SPREAD", "VIX_CALL_SPREAD"}
    mr_df    = all_trades_df[~all_trades_df["ticker"].str.startswith("OVL_")
                              & ~all_trades_df["ticker"].isin(overlay_tickers)]
    put_df   = all_trades_df[all_trades_df["ticker"] == "SPY_PUT_SPREAD"]
    vxc_df   = all_trades_df[all_trades_df["ticker"] == "VIX_CALL_SPREAD"]
    gold_df  = all_trades_df[all_trades_df["ticker"] == "OVL_GOLD"]
    sec_df   = all_trades_df[all_trades_df["ticker"].str.startswith("OVL_SECROT")]

    put_prem = put_df[put_df["exit_reason"] == "put_premium"]["pnl_usd"].sum()
    put_pay  = put_df[put_df["exit_reason"] == "put_payout"]["pnl_usd"].sum()
    vxc_prem = vxc_df[vxc_df["exit_reason"] == "vix_call_premium"]["pnl_usd"].sum()
    vxc_pay  = vxc_df[vxc_df["exit_reason"] == "vix_call_payout"]["pnl_usd"].sum()

    print(f"\n  Overlay P&L Breakdown:")
    print(f"    MR trades P&L:          ${mr_df['pnl_usd'].sum():>+15,.0f}  ({len(mr_df)} trades)")
    print(f"    SPY put premiums paid:   ${put_prem:>+15,.0f}")
    print(f"    SPY put payouts recv:    ${put_pay:>+15,.0f}")
    print(f"    SPY put net P&L:         ${put_prem+put_pay:>+15,.0f}")
    print(f"    VIX call premiums paid:  ${vxc_prem:>+15,.0f}")
    print(f"    VIX call payouts recv:   ${vxc_pay:>+15,.0f}")
    print(f"    VIX call net P&L:        ${vxc_prem+vxc_pay:>+15,.0f}")
    print(f"    GOLD overlay net P&L:    ${gold_df['pnl_usd'].sum():>+15,.0f}  ({len(gold_df)} days in pos)")
    print(f"    SECROT overlay net P&L:  ${sec_df['pnl_usd'].sum():>+15,.0f}  ({len(sec_df)} day-sector records)")
    total_ovl = (put_prem+put_pay+vxc_prem+vxc_pay+
                 gold_df['pnl_usd'].sum()+sec_df['pnl_usd'].sum())
    print(f"    TOTAL overlay net P&L:   ${total_ovl:>+15,.0f}")

def main():
    print("\n" + "="*70)
    print(" IDEAS V7.3 — Idea G (V48 baseline) + GOLD + SECROT")
    print(" Single combined equity: MR + SPY puts + VIX calls + GOLD + SECROT")
    print(" Baseline (V48/Idea G): $18,323,346 | CAGR 24.38% | MaxDD -56.91%")
    print("="*70)

    universe     = get_universe()
    price_data   = download_prices(universe)
    spy_df, vix_df, sector_data = download_reference_data()
    earnings_map = build_earnings_dates(list(price_data.keys()))
    ovl_px       = download_overlay_prices()

    all_trades_df, mr_put_vxc_df = run_idea_g_plus_overlays(
        price_data, spy_df, vix_df, sector_data, earnings_map, ovl_px
    )

    # ── MR-only CAGR (matches V48 reference methodology) ─────────────────────
    overlay_tickers = {"SPY_PUT_SPREAD", "VIX_CALL_SPREAD"}
    mr_only = all_trades_df[
        ~all_trades_df["ticker"].str.startswith("OVL_") &
        ~all_trades_df["ticker"].isin(overlay_tickers)
    ]
    mr_metrics, _ = compute_metrics(mr_only)

    # ── Combined equity metrics (everything together) ─────────────────────────
    comb = _combined_metrics(all_trades_df)

    # ── Idea G only (without GOLD/SECROT) for delta comparison ───────────────
    idea_g_only = all_trades_df[
        ~all_trades_df["ticker"].str.startswith("OVL_GOLD") &
        ~all_trades_df["ticker"].str.startswith("OVL_SECROT")
    ]
    comb_g_only = _combined_metrics(idea_g_only)

    # ── Print results ─────────────────────────────────────────────────────────
    W = 70
    print("\n" + "="*W)
    print(" V7.3 RESULTS")
    print("="*W)

    BASELINE_EQ   = 18_323_346
    BASELINE_DD   = -56.91
    BASELINE_CAGR = 24.38

    dc_mr   = mr_metrics["cagr_pct"]      - BASELINE_CAGR
    dc_comb = comb["cagr_combined_pct"]   - BASELINE_CAGR
    de_comb = comb["final_equity_combined"] - BASELINE_EQ
    dd_comb = comb["max_drawdown_combined_pct"] - BASELINE_DD

    print(f"\n  {'Metric':<38} {'Baseline (V48/Idea G)':>22} {'V7.3 (+ GOLD + SECROT)':>24}")
    print("  " + "-"*(W-2))
    print(f"  {'CAGR (MR-only basis)':<38} {BASELINE_CAGR:>21.2f}% {mr_metrics['cagr_pct']:>23.2f}%  ({dc_mr:+.2f}pp)")
    print(f"  {'CAGR (combined equity)':<38} {'—':>22} {comb['cagr_combined_pct']:>23.2f}%")
    print(f"  {'Final Equity (combined)':<38} ${BASELINE_EQ:>21,.0f} ${comb['final_equity_combined']:>22,.0f}  ({de_comb:>+,.0f})")
    print(f"  {'Max Drawdown (combined)':<38} {BASELINE_DD:>21.2f}% {comb['max_drawdown_combined_pct']:>23.2f}%  ({dd_comb:>+.2f}pp)")
    print(f"  {'Sharpe (combined)':<38} {'0.74':>22} {comb['sharpe_combined']:>24.2f}")
    print(f"  {'Win Rate (MR-only)':<38} {'60.25':>21}% {mr_metrics['win_rate_pct']:>23.2f}%")
    print(f"  {'Profit Factor (MR-only)':<38} {'1.06':>22} {mr_metrics['profit_factor']:>24.2f}")
    print(f"  {'Total MR Trades':<38} {'—':>22} {mr_metrics['total_trades']:>24,}")

    # Idea G only combined (for intermediate comparison)
    print(f"\n  Idea G only (no GOLD/SECROT) combined:")
    print(f"    Final equity: ${comb_g_only['final_equity_combined']:,.0f}  "
          f"MaxDD: {comb_g_only['max_drawdown_combined_pct']:.2f}%  "
          f"CAGR(comb): {comb_g_only['cagr_combined_pct']:.2f}%")

    print(f"\n  Delta (V7.3 vs V48/Idea G baseline):")
    dd_flag = "✓ IMPROVED" if dd_comb > 0 else "✗ WORSE"
    print(f"    ΔCAGR (MR-only):  {dc_mr:>+.2f}pp")
    print(f"    ΔFinal Equity:    ${de_comb:>+,.0f}")
    print(f"    ΔMaxDD:           {dd_comb:>+.2f}pp  {dd_flag}")
    print(f"    (positive ΔMaxDD = less negative = drawdown improved)")

    _overlay_breakdown(all_trades_df)

    # Year-by-year (combined)
    print(f"\n  Year-by-Year (combined equity):")
    eq_df = comb["equity_curve"].copy()
    eq_df["year"] = pd.to_datetime(eq_df["date"]).dt.year
    print(f"  {'Year':<6} {'End Equity':>16} {'P&L':>14}")
    print("  " + "-"*38)
    prev_eq = INITIAL_CAPITAL
    for yr in sorted(eq_df["year"].unique()):
        yr_eq = eq_df[eq_df["year"] == yr]["equity"].iloc[-1]
        yr_pnl = yr_eq - prev_eq
        print(f"  {yr:<6} ${yr_eq:>14,.0f}  ${yr_pnl:>+13,.0f}")
        prev_eq = yr_eq

    print("="*W)

    # ── Save outputs ──────────────────────────────────────────────────────────
    all_trades_df.to_csv(OUTPUT_DIR / "all_trades.csv", index=False)
    comb["equity_curve"].to_csv(OUTPUT_DIR / "combined_equity_curve.csv", index=False)

    # Monthly equity curve for charting
    eq_monthly = (comb["equity_curve"]
                  .set_index(pd.to_datetime(comb["equity_curve"]["date"]))["equity"]
                  .resample("ME").last().ffill())
    eq_monthly.to_csv(OUTPUT_DIR / "combined_equity_monthly.csv")

    summary = {
        "run_date":  datetime.date.today().isoformat(),
        "version":   "V7.3",
        "strategy":  "Idea G (V48 = V47 + dynamic put strikes + VIX calls) + GOLD + SECROT",
        "baseline_v48": {
            "final_equity":   BASELINE_EQ,
            "cagr_mr_pct":    BASELINE_CAGR,
            "max_drawdown_pct": BASELINE_DD,
        },
        "v7_3_results": {
            "cagr_mr_pct":              mr_metrics["cagr_pct"],
            "cagr_combined_pct":        comb["cagr_combined_pct"],
            "final_equity_combined":    comb["final_equity_combined"],
            "max_drawdown_combined_pct": comb["max_drawdown_combined_pct"],
            "sharpe_combined":          comb["sharpe_combined"],
            "win_rate_pct":             mr_metrics["win_rate_pct"],
            "profit_factor":            mr_metrics["profit_factor"],
            "total_mr_trades":          mr_metrics["total_trades"],
            "delta_cagr_mr_pp":         round(dc_mr, 2),
            "delta_final_equity":       round(de_comb, 2),
            "delta_maxdd_pp":           round(dd_comb, 2),
        },
        "overlay_config": {
            "gold_alloc_pct":    GOLD_ALLOC_PCT,
            "secrot_alloc_pct":  SECROT_ALLOC_PCT,
            "secrot_top_n":      SECROT_TOP_N,
            "secrot_mom_days":   SECROT_MOM_DAYS,
            "put_spread_cost":   PUT_SPREAD_COST_PCT,
            "vix_call_cost":     VIX_CALL_COST_PCT,
        },
    }
    with open(OUTPUT_DIR / "v7_3_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)

    print(f"\n  All outputs → {OUTPUT_DIR.resolve()}")
    print(f"  Paste back: combined equity table + overlay breakdown above.")
    print(f"  Equity curve: results_ideas_v7_3/combined_equity_monthly.csv")


if __name__ == "__main__":
    main()
