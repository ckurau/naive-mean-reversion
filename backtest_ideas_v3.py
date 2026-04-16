# backtest_ideas_v3.py
#
# Multi-test runner: 6 new ideas tested against V35 and V35+Idea3 baselines.
#
# BASELINES (always run, never skip):
#   Baseline_V35     : Pure V35, no modifications. Reference point.
#   Baseline_V35_I3  : V35 + Idea3 put spread at 1.5%/qtr. Current best.
#                      CAGR 19.71% | MaxDD -52.87% | Sharpe 0.74 | $4.51M
#
# NEW IDEAS (each tested standalone AND combined with Idea3):
#
#   IdeaD  VIX Term Structure Scaling
#          Download ^VIX3M (90-day implied vol) alongside ^VIX (30-day).
#          size_scalar = clip(VIX3M / VIX, 0.40, 1.0)
#          When VIX > VIX3M (inverted term structure = acute fear), positions
#          shrink. Normal backwardation = full size. Forward-looking signal vs
#          realized vol. Specifically targets 2022 grind where VIX was
#          persistently inverted while 200d MA filter stayed "on".
#
#   IdeaE  52-Week High Proximity Filter
#          Only enter if stock is within HIGH_PROXIMITY_PCT (20%) of its
#          52-week high. Blocks deeply distressed names that are in structural
#          downtrend. KO/PEP/NEE-type setups pass; 40%-below-peak names fail.
#          Does NOT reduce position sizing -- pure entry filter.
#
#   IdeaB  Overnight Gap Capture Sub-Tier
#          Stocks with 4+ down days that gap UP 0.5-2% at open (currently
#          rejected by GAP_UP logic as "gapped above limit") enter at CLOSE
#          of the gap-up day instead of LOO. Shorter 4-5 day hold, 1.5%
#          target. Reversion already in progress -- higher quality entries.
#          Adds trade count without touching existing tiers.
#
#   IdeaC  Analyst Dispersion Re-ranking
#          Pulls analyst recommendation count from yfinance as a proxy for
#          coverage breadth (more analysts = lower dispersion = clearer fair
#          value). Re-weights composite score: score / (1 + 1/analyst_count).
#          High-coverage stocks rank higher. Falls back gracefully if data
#          unavailable (uses original score). Runs once at startup, cached.
#
#   IdeaF  Call Spread Overlay
#          When VIX < VIX_CALM_THRESHOLD (15), sell 5%/15% OTM SPY call
#          spread quarterly, collecting ~CALL_SPREAD_QUARTERLY_REVENUE (0.6%)
#          premium. Pays out (costs money) if SPY rallies >5% that quarter.
#          Offsets put spread drag in calm bull markets. Combined with Idea3.
#          Tested standalone (no puts) and combined with Idea3.
#
#   IdeaD+E   VIX term structure + 52wk proximity together
#   IdeaD+I3  VIX term structure + put spread
#   IdeaE+I3  52wk proximity + put spread
#   IdeaB+I3  Gap capture + put spread
#   IdeaC+I3  Analyst dispersion + put spread
#   IdeaF+I3  Call spread + put spread (full collar)
#   IdeaD+E+I3  Best two new ideas + put spread
#   IdeaD+E+B+I3 Three ideas + put spread
#   Kitchen_Sink  All 6 ideas + Idea3
#
# TOTAL TESTS: 2 baselines + 6 individual + 9 combinations = 17 tests
#
# OUTPUT: results_ideas_v3/ -- per-test subdirs + comparison.json
#
# DOES NOT modify backtest_nmr_lib.py. V35 is untouched.
# Idea3 put spread uses same implementation as backtest_ideas_v2.py but with
# PUT_SPREAD_QUARTERLY_COST = 0.015 (1.5%/qtr = realistic market pricing).

import json
import warnings
import datetime
from pathlib import Path
from collections import defaultdict

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

from backtest_nmr_lib import (
    get_universe, download_prices, download_reference_data,
    build_earnings_dates, compute_metrics,
    generate_signals, get_position_size, get_tier,
    calc_commission, sector_ok, count_sector_positions,
    check_vix_spike, near_earnings,
    TICKER_TO_SECTOR, INITIAL_CAPITAL, START_DATE, END_DATE,
    MAX_POSITIONS, POSITION_SIZE, POSITION_SIZE_HIGH,
    MA_WINDOW, VOL_MA_PERIOD, ATR_PERIOD, RSI_PERIOD,
    RSI_THRESHOLD, ATR_MIN_PCT, MIN_DOLLAR_VOLUME,
    MIN_CONSEC_DOWN, MIN_HOLD_BEFORE_EXIT,
    VELOCITY_CRASH_5D_THRESHOLD, VELOCITY_CRASH_PAUSE_DAYS,
    VIX_SPIKE_PAUSE_DAYS, VIX_LOW,
    GAP_DOWN_MAX, GAP_UP_MAX,
    REENTRY_COOLDOWN_DAYS, MAX_SECTOR_POSITIONS,
    EARNINGS_MONTHS, EARNINGS_BLACKOUT,
    TOP_SIGNAL_PCT, TOP_SIGNAL_MULTIPLIER, TOP_SIGNAL_HARD_CAP,
    MIN_CANDIDATES_FOR_C5, COMMISSION_RATE, COMMISSION_MIN,
)

OUTPUT_DIR = Path("results_ideas_v3")
OUTPUT_DIR.mkdir(exist_ok=True)

# =============================================================================
# Idea-specific parameters
# =============================================================================

# Idea D: VIX term structure
VIX_TS_FLOOR         = 0.40    # minimum scale factor when deeply inverted
VIX_TS_CAP           = 1.00    # maximum (don't lever up)

# Idea E: 52-week high proximity
HIGH_PROXIMITY_PCT   = 0.20    # only enter if within 20% of 52-week high

# Idea B: overnight gap capture
GAP_CAPTURE_MIN      = 0.005   # min gap-up to qualify (0.5%)
GAP_CAPTURE_MAX      = 0.020   # max gap-up for gap capture (2%)
GAP_CAPTURE_TARGET   = 0.015   # profit target for gap captures (1.5%)
GAP_CAPTURE_HOLD     = 5       # max hold days

# Idea C: analyst dispersion proxy
ANALYST_FALLBACK     = True    # fall back to original score if no data

# Idea F: call spread
CALL_SPREAD_VIX_MAX          = 15.0   # only sell calls when VIX < 15
CALL_SPREAD_LOWER_OTM        = 0.05   # 5% OTM short call (we sell this)
CALL_SPREAD_UPPER_OTM        = 0.15   # 15% OTM long call (we buy this, cap risk)
CALL_SPREAD_QUARTERLY_REVENUE= 0.006  # +0.6%/qtr collected when VIX < 15
CALL_SPREAD_RENEW_DAYS       = 63

# Idea 3 (put spread, same as v2 but at realistic cost)
PUT_SPREAD_LOWER_OTM    = 0.05
PUT_SPREAD_UPPER_OTM    = 0.15
PUT_SPREAD_QUARTERLY_COST = 0.015   # 1.5%/qtr (realistic, confirmed in v2 run)
PUT_SPREAD_RENEW_DAYS   = 63

# =============================================================================
# Test matrix
# =============================================================================
TESTS = [
    # Baselines
    {"name": "Baseline_V35",      "puts": False, "calls": False, "vix_ts": False, "high52": False, "gap_cap": False, "analyst": False},
    {"name": "Baseline_V35_I3",   "puts": True,  "calls": False, "vix_ts": False, "high52": False, "gap_cap": False, "analyst": False},
    # Individual new ideas (no puts)
    {"name": "IdeaD_VixTS",       "puts": False, "calls": False, "vix_ts": True,  "high52": False, "gap_cap": False, "analyst": False},
    {"name": "IdeaE_52wkHigh",    "puts": False, "calls": False, "vix_ts": False, "high52": True,  "gap_cap": False, "analyst": False},
    {"name": "IdeaB_GapCapture",  "puts": False, "calls": False, "vix_ts": False, "high52": False, "gap_cap": True,  "analyst": False},
    {"name": "IdeaC_Analyst",     "puts": False, "calls": False, "vix_ts": False, "high52": False, "gap_cap": False, "analyst": True},
    {"name": "IdeaF_CallSpread",  "puts": False, "calls": True,  "vix_ts": False, "high52": False, "gap_cap": False, "analyst": False},
    # Each new idea + Idea3 put spread
    {"name": "IdeaD+I3",          "puts": True,  "calls": False, "vix_ts": True,  "high52": False, "gap_cap": False, "analyst": False},
    {"name": "IdeaE+I3",          "puts": True,  "calls": False, "vix_ts": False, "high52": True,  "gap_cap": False, "analyst": False},
    {"name": "IdeaB+I3",          "puts": True,  "calls": False, "vix_ts": False, "high52": False, "gap_cap": True,  "analyst": False},
    {"name": "IdeaC+I3",          "puts": True,  "calls": False, "vix_ts": False, "high52": False, "gap_cap": False, "analyst": True},
    {"name": "IdeaF+I3",          "puts": True,  "calls": True,  "vix_ts": False, "high52": False, "gap_cap": False, "analyst": False},
    # Combinations
    {"name": "IdeaD+E",           "puts": False, "calls": False, "vix_ts": True,  "high52": True,  "gap_cap": False, "analyst": False},
    {"name": "IdeaD+E+I3",        "puts": True,  "calls": False, "vix_ts": True,  "high52": True,  "gap_cap": False, "analyst": False},
    {"name": "IdeaD+E+B+I3",      "puts": True,  "calls": False, "vix_ts": True,  "high52": True,  "gap_cap": True,  "analyst": False},
    {"name": "IdeaD+E+F+I3",      "puts": True,  "calls": True,  "vix_ts": True,  "high52": True,  "gap_cap": False, "analyst": False},
    {"name": "Kitchen_Sink",      "puts": True,  "calls": True,  "vix_ts": True,  "high52": True,  "gap_cap": True,  "analyst": True},
]

# =============================================================================
# VIX3M download (Idea D)
# =============================================================================
def download_vix3m() -> pd.Series:
    """Download ^VIX3M (CBOE 3-month VIX). Returns Close series."""
    try:
        raw = yf.download("^VIX3M", start=START_DATE, end=END_DATE,
                          auto_adjust=True, progress=False)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        s = raw["Close"].squeeze()
        print(f"[VIX3M] Downloaded {len(s)} rows")
        return s
    except Exception as e:
        print(f"[VIX3M] Download failed: {e} -- Idea D will use scale=1.0 fallback")
        return pd.Series(dtype=float)


def get_vix_ts_scale(today, vix_close: float, vix3m_series: pd.Series) -> float:
    """
    Returns size scalar based on VIX term structure.
    scalar = clip(VIX3M / VIX, floor, cap)
    Inverted (VIX > VIX3M): scalar < 1 -- shrink positions.
    Normal (VIX < VIX3M): scalar = 1.0 -- full size.
    """
    if vix3m_series.empty or today not in vix3m_series.index:
        return 1.0
    vix3m = float(vix3m_series.loc[today])
    if vix3m <= 0 or vix_close <= 0:
        return 1.0
    return float(np.clip(vix3m / vix_close, VIX_TS_FLOOR, VIX_TS_CAP))


# =============================================================================
# 52-week high proximity (Idea E)
# =============================================================================
def passes_52wk_filter(tkr: str, today, price_data: dict) -> bool:
    """
    Returns True if stock is within HIGH_PROXIMITY_PCT of its 52-week high.
    Falls back to True (pass) if data unavailable.
    """
    df = price_data.get(tkr)
    if df is None or today not in df.index:
        return True
    loc = df.index.get_loc(today)
    lookback = min(252, loc)
    if lookback < 20:
        return True
    window_high = float(df["High"].iloc[loc - lookback: loc + 1].max())
    last_close = float(df["Close"].iloc[loc])
    if window_high <= 0:
        return True
    distance = (window_high - last_close) / window_high
    return distance <= HIGH_PROXIMITY_PCT


# =============================================================================
# Analyst coverage proxy (Idea C)
# =============================================================================
def build_analyst_coverage(tickers: list) -> dict:
    """
    Returns {ticker: coverage_score} where higher = more analysts = lower
    dispersion proxy. Uses recommendationKey count from yfinance.
    Falls back to 0 (neutral) if unavailable.
    Runs once at startup, cached for full backtest.
    """
    print(f"[AnalystCoverage] Fetching for {len(tickers)} tickers...")
    coverage = {}
    for tkr in tickers:
        try:
            info = yf.Ticker(tkr).info
            # numberOfAnalystOpinions is the best proxy available
            n = info.get("numberOfAnalystOpinions", 0) or 0
            coverage[tkr] = float(n)
        except Exception:
            coverage[tkr] = 0.0
    filled = sum(1 for v in coverage.values() if v > 0)
    print(f"[AnalystCoverage] Done: {filled}/{len(tickers)} tickers with data")
    return coverage


def get_analyst_score_multiplier(tkr: str, coverage: dict) -> float:
    """
    Returns a score divisor: 1 + 1/(analyst_count+1).
    More analysts = divisor closer to 1.0 = higher rank (lower composite score).
    Zero analysts = divisor = 2.0 = lower rank.
    Applied to composite score so low-dispersion stocks sort higher.
    """
    n = coverage.get(tkr, 0.0)
    return 1.0 + 1.0 / (n + 1.0)


# =============================================================================
# Put spread helpers (same as backtest_ideas_v2.py)
# =============================================================================
def compute_put_spread_intrinsic_pct(spy_ref: float, spy_low: float) -> float:
    lower_strike = spy_ref * (1 - PUT_SPREAD_LOWER_OTM)
    spread_width_pct = PUT_SPREAD_UPPER_OTM - PUT_SPREAD_LOWER_OTM
    if spy_low >= lower_strike:
        return 0.0
    spy_decline_pct = (spy_ref - spy_low) / spy_ref
    payout_pct = spy_decline_pct - PUT_SPREAD_LOWER_OTM
    return float(np.clip(payout_pct, 0.0, spread_width_pct))


# =============================================================================
# Call spread helpers (Idea F)
# =============================================================================
def compute_call_spread_cost_pct(spy_ref: float, spy_high: float) -> float:
    """
    Cost of call spread at expiry if SPY rallied above short call strike.
    short call: strike = ref * (1 + CALL_SPREAD_LOWER_OTM) [5% OTM, we SOLD]
    long call:  strike = ref * (1 + CALL_SPREAD_UPPER_OTM) [15% OTM, we BOUGHT]
    We collected premium upfront. This returns the cost (loss) at expiry.
    Max loss = spread width (10% of ref) - premium collected.
    """
    short_strike = spy_ref * (1 + CALL_SPREAD_LOWER_OTM)
    spread_width_pct = CALL_SPREAD_UPPER_OTM - CALL_SPREAD_LOWER_OTM
    if spy_high <= short_strike:
        return 0.0  # SPY didn't rally enough, we keep full premium
    rally_pct = (spy_high - spy_ref) / spy_ref
    cost_pct = rally_pct - CALL_SPREAD_LOWER_OTM
    return float(np.clip(cost_pct, 0.0, spread_width_pct))


# =============================================================================
# Core backtest
# =============================================================================
def run_backtest_v3(price_data: dict, spy_df: pd.DataFrame, vix_df: pd.DataFrame,
                    sector_data: dict, earnings_map: dict,
                    vix3m_series: pd.Series, analyst_coverage: dict,
                    cfg: dict) -> pd.DataFrame:

    test_name  = cfg["name"]
    use_puts   = cfg["puts"]
    use_calls  = cfg["calls"]
    use_vix_ts = cfg["vix_ts"]
    use_high52 = cfg["high52"]
    use_gap    = cfg["gap_cap"]
    use_analyst= cfg["analyst"]

    print(f"\n{'='*70}")
    print(f"[Test] {test_name}")
    print(f"  Puts={use_puts} Calls={use_calls} VixTS={use_vix_ts} "
          f"52wk={use_high52} Gap={use_gap} Analyst={use_analyst}")
    print(f"{'='*70}")

    spy_regime = spy_df["spy_ok"].to_dict()
    spy_close  = spy_df["Close"].squeeze()

    # Get VIX close series for term structure
    try:
        vix_close_series = vix_df["Close"].squeeze()
    except Exception:
        vix_close_series = pd.Series(dtype=float)

    all_dates: set = set()
    for df in price_data.values():
        all_dates.update(df.index)
    trading_dates = sorted(all_dates)

    signals: dict[str, pd.DataFrame] = {}
    min_bars = MA_WINDOW + VOL_MA_PERIOD + ATR_PERIOD + MIN_CONSEC_DOWN + 5
    for tkr, df in price_data.items():
        if len(df) > min_bars:
            signals[tkr] = generate_signals(df)

    # ── State ────────────────────────────────────────────────────────────────
    portfolio_value    = INITIAL_CAPITAL
    portfolio_peak     = None
    current_drawdown   = 0.0
    open_positions     = {}
    gap_positions      = {}   # Idea B gap capture positions
    trades             = []
    cooldown_map       = {}
    last_vix_spike     = None
    last_velocity_crash= None

    # Put spread state
    put_ref_price      = None
    put_ref_date       = None
    put_notional       = 0.0
    put_min_spy        = 9999.0
    put_days_since_renew = 0
    put_cumulative_pnl = 0.0

    # Call spread state
    call_active        = False
    call_ref_price     = None
    call_ref_date      = None
    call_notional      = 0.0
    call_max_spy       = 0.0
    call_days_since_renew = 0

    # ── Main loop ─────────────────────────────────────────────────────────────
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

        # Drawdown tracking
        if portfolio_peak is None:
            if portfolio_value != INITIAL_CAPITAL:
                portfolio_peak = portfolio_value
                current_drawdown = 0.0
        else:
            if portfolio_value > portfolio_peak:
                portfolio_peak = portfolio_value
                current_drawdown = 0.0
            else:
                current_drawdown = (portfolio_value - portfolio_peak) / portfolio_peak

        # Get today's VIX for term structure scaling
        vix_today = 20.0
        try:
            if today in vix_close_series.index:
                vix_today = float(vix_close_series.loc[today])
        except Exception:
            pass

        # Idea D: VIX term structure scale
        vix_ts_scale = 1.0
        if use_vix_ts:
            vix_ts_scale = get_vix_ts_scale(today, vix_today, vix3m_series)

        # ── Put spread (Idea 3) ───────────────────────────────────────────────
        if use_puts and today in spy_df.index:
            spy_price_today = float(spy_close.loc[today]) if today in spy_close.index else None
            if spy_price_today is not None:
                if put_ref_price is None or put_days_since_renew >= PUT_SPREAD_RENEW_DAYS:
                    quarterly_premium = portfolio_value * PUT_SPREAD_QUARTERLY_COST
                    portfolio_value  -= quarterly_premium
                    put_ref_price    = spy_price_today
                    put_ref_date     = today
                    put_notional     = portfolio_value
                    put_min_spy      = spy_price_today
                    put_days_since_renew = 0
                    trades.append({
                        "ticker": "SPY_PUT_SPREAD", "entry_date": today, "exit_date": today,
                        "entry_price": spy_price_today, "exit_price": spy_price_today,
                        "shares": 0, "commission": 0,
                        "pnl_usd": round(-quarterly_premium, 2),
                        "pnl_pct": -PUT_SPREAD_QUARTERLY_COST * 100,
                        "days_held": 0, "exit_reason": "put_premium",
                        "tier": 0, "consec_down": 0, "portfolio_val": portfolio_value,
                    })
                else:
                    put_days_since_renew += 1
                    put_min_spy = min(put_min_spy, spy_price_today)
                    if put_days_since_renew == PUT_SPREAD_RENEW_DAYS - 1:
                        payout_pct = compute_put_spread_intrinsic_pct(put_ref_price, put_min_spy)
                        if payout_pct > 0:
                            payout = put_notional * payout_pct
                            portfolio_value += payout
                            put_cumulative_pnl += payout
                            trades.append({
                                "ticker": "SPY_PUT_SPREAD", "entry_date": put_ref_date, "exit_date": today,
                                "entry_price": put_ref_price, "exit_price": put_min_spy,
                                "shares": 0, "commission": 0,
                                "pnl_usd": round(payout, 2),
                                "pnl_pct": round(payout_pct * 100, 4),
                                "days_held": put_days_since_renew, "exit_reason": "put_payout",
                                "tier": 0, "consec_down": 0, "portfolio_val": portfolio_value,
                            })

        # ── Call spread (Idea F) ──────────────────────────────────────────────
        if use_calls and today in spy_df.index:
            spy_price_today = float(spy_close.loc[today]) if today in spy_close.index else None
            if spy_price_today is not None:
                # Only sell calls when VIX is calm
                if (not call_active) and vix_today < CALL_SPREAD_VIX_MAX:
                    # Collect premium upfront
                    quarterly_revenue = portfolio_value * CALL_SPREAD_QUARTERLY_REVENUE
                    portfolio_value  += quarterly_revenue
                    call_ref_price    = spy_price_today
                    call_ref_date     = today
                    call_notional     = portfolio_value
                    call_max_spy      = spy_price_today
                    call_days_since_renew = 0
                    call_active       = True
                    trades.append({
                        "ticker": "SPY_CALL_SPREAD", "entry_date": today, "exit_date": today,
                        "entry_price": spy_price_today, "exit_price": spy_price_today,
                        "shares": 0, "commission": 0,
                        "pnl_usd": round(quarterly_revenue, 2),
                        "pnl_pct": CALL_SPREAD_QUARTERLY_REVENUE * 100,
                        "days_held": 0, "exit_reason": "call_premium",
                        "tier": 0, "consec_down": 0, "portfolio_val": portfolio_value,
                    })
                elif call_active:
                    call_days_since_renew += 1
                    call_max_spy = max(call_max_spy, spy_price_today)
                    # Settle at expiry
                    if call_days_since_renew == CALL_SPREAD_RENEW_DAYS - 1:
                        cost_pct = compute_call_spread_cost_pct(call_ref_price, call_max_spy)
                        if cost_pct > 0:
                            cost = call_notional * cost_pct
                            portfolio_value -= cost
                            trades.append({
                                "ticker": "SPY_CALL_SPREAD", "entry_date": call_ref_date, "exit_date": today,
                                "entry_price": call_ref_price, "exit_price": call_max_spy,
                                "shares": 0, "commission": 0,
                                "pnl_usd": round(-cost, 2),
                                "pnl_pct": round(-cost_pct * 100, 4),
                                "days_held": call_days_since_renew, "exit_reason": "call_cost",
                                "tier": 0, "consec_down": 0, "portfolio_val": portfolio_value,
                            })
                        call_active = False  # Reset -- only sell again if VIX calm

        # ── MR Exits ─────────────────────────────────────────────────────────
        to_close = []
        for tkr, pos in open_positions.items():
            if tkr not in signals:
                continue
            tkr_df = signals[tkr]
            if today not in tkr_df.index:
                continue
            row = tkr_df.loc[today]
            exit_price  = float(row["Close"])
            entry_price = pos["entry_price"]
            days_held   = (pd.Timestamp(today) - pd.Timestamp(pos["entry_date"])).days
            pos_pct     = (exit_price - entry_price) / entry_price
            shares_rem  = pos["shares_remaining"]
            early       = days_held < MIN_HOLD_BEFORE_EXIT
            time_stop   = days_held >= pos["hold_days"]
            profit_hit  = (not early) and pos_pct >= pos["profit_target"]

            if (pos["partial_enabled"] and not pos["partial_done"]
                    and not early and pos_pct >= pos["partial_trigger"]):
                partial_shares = shares_rem * pos["partial_frac"]
                commission = calc_commission(partial_shares, exit_price)
                pnl = (exit_price - entry_price) * partial_shares - commission
                trades.append({
                    "ticker": tkr, "entry_date": pos["entry_date"], "exit_date": today,
                    "entry_price": entry_price, "exit_price": exit_price,
                    "shares": partial_shares, "commission": round(commission, 4),
                    "pnl_usd": pnl, "pnl_pct": pos_pct * 100, "days_held": days_held,
                    "exit_reason": "partial_exit", "tier": pos["tier"],
                    "consec_down": pos["consec_down_at_entry"], "portfolio_val": portfolio_value + pnl,
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
                commission = calc_commission(shares_rem, exit_price)
                pnl = ((exit_price - entry_price) * shares_rem
                       - commission - pos["entry_commission"])
                reason = "time_stop" if time_stop else "profit_target"
                trades.append({
                    "ticker": tkr, "entry_date": pos["entry_date"], "exit_date": today,
                    "entry_price": entry_price, "exit_price": exit_price,
                    "shares": shares_rem, "commission": round(commission + pos["entry_commission"], 4),
                    "pnl_usd": pnl, "pnl_pct": pos_pct * 100, "days_held": days_held,
                    "exit_reason": reason, "tier": pos["tier"],
                    "consec_down": pos["consec_down_at_entry"], "portfolio_val": portfolio_value + pnl,
                })
                portfolio_value += pnl
                if time_stop:
                    cooldown_map[tkr] = today
                to_close.append(tkr)

        for tkr in to_close:
            del open_positions[tkr]

        # ── Idea B: Gap capture exits ─────────────────────────────────────────
        gap_to_close = []
        if use_gap:
            for tkr, pos in gap_positions.items():
                df_t = price_data.get(tkr)
                if df_t is None or today not in df_t.index:
                    continue
                exit_price  = float(df_t.loc[today, "Close"])
                entry_price = pos["entry_price"]
                days_held   = (pd.Timestamp(today) - pd.Timestamp(pos["entry_date"])).days
                pos_pct     = (exit_price - entry_price) / entry_price
                if pos_pct >= GAP_CAPTURE_TARGET or days_held >= GAP_CAPTURE_HOLD:
                    commission = calc_commission(pos["shares"], exit_price)
                    pnl = (exit_price - entry_price) * pos["shares"] - commission - pos["entry_commission"]
                    reason = "gap_profit" if pos_pct >= GAP_CAPTURE_TARGET else "gap_timestop"
                    trades.append({
                        "ticker": tkr + "_GAP", "entry_date": pos["entry_date"], "exit_date": today,
                        "entry_price": entry_price, "exit_price": exit_price,
                        "shares": pos["shares"], "commission": round(commission, 4),
                        "pnl_usd": pnl, "pnl_pct": pos_pct * 100, "days_held": days_held,
                        "exit_reason": reason, "tier": -2, "consec_down": pos["consec_down"],
                        "portfolio_val": portfolio_value + pnl,
                    })
                    portfolio_value += pnl
                    gap_to_close.append(tkr)
            for tkr in gap_to_close:
                del gap_positions[tkr]

        if not spy_ok or paused or velocity_paused:
            continue
        if len(open_positions) >= MAX_POSITIONS:
            continue

        # ── MR Entries ────────────────────────────────────────────────────────
        candidates = []
        for tkr, tkr_df in signals.items():
            if tkr in open_positions or today not in tkr_df.index:
                continue
            row = tkr_df.loc[today]
            if not row["signal"]:
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
            # Idea E: 52-week high proximity filter
            if use_high52 and not passes_52wk_filter(tkr, today, price_data):
                continue
            rsi2        = float(row["rsi2"])
            atr_pct     = float(row["atr_pct"])
            raw_score   = rsi2 / atr_pct if atr_pct > 0 else rsi2 * 1000
            # Idea C: analyst dispersion re-ranking
            if use_analyst:
                divisor   = get_analyst_score_multiplier(tkr, analyst_coverage)
                score     = raw_score * divisor   # higher divisor = lower rank = worse
            else:
                score     = raw_score
            candidates.append((score, tkr, int(row["consec_down"]), rsi2))

        candidates.sort(key=lambda x: x[0])
        n_candidates = len(candidates)
        top_n = max(1, int(n_candidates * TOP_SIGNAL_PCT))

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
            prev_close  = float(tkr_df.iloc[today_idx]["Close"])
            gap_pct     = (entry_price - prev_close) / prev_close

            # Standard gap filters
            if gap_pct < GAP_DOWN_MAX:
                continue

            # Idea B: intercept gap-up stocks (0.5% - 2%) for gap capture tier
            if use_gap and GAP_CAPTURE_MIN <= gap_pct <= GAP_CAPTURE_MAX:
                if tkr not in gap_positions:
                    # Enter at close of next day (approximated as next row Close)
                    gap_entry = float(next_row["Close"])
                    if gap_entry > 0:
                        pos_size   = get_position_size(today, vix_df, current_drawdown) * 0.5
                        shares     = (portfolio_value * pos_size) / gap_entry
                        entry_comm = calc_commission(shares, gap_entry)
                        gap_positions[tkr] = {
                            "entry_date":       tkr_df.index[today_idx + 1],
                            "entry_price":      gap_entry,
                            "shares":           shares,
                            "entry_commission": entry_comm,
                            "consec_down":      consec_val,
                        }
                continue  # Don't double-enter as standard MR

            # Standard gap-up rejection
            if gap_pct > GAP_UP_MAX:
                continue

            tier_cfg = get_tier(consec_val)

            # V35 signal multiplier
            size_multiplier = 1.0
            if n_candidates >= MIN_CANDIDATES_FOR_C5 and rank < top_n:
                size_multiplier = TOP_SIGNAL_MULTIPLIER

            pos_size = get_position_size(
                today, vix_df, current_drawdown,
                multiplier=size_multiplier, hard_cap=TOP_SIGNAL_HARD_CAP,
            )

            # Idea D: apply VIX term structure scale
            if use_vix_ts:
                pos_size = pos_size * vix_ts_scale

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

    print(f"[{test_name}] Complete -- {len(trades)} total trade records.")
    return pd.DataFrame(trades)


# =============================================================================
# Output helpers
# =============================================================================
def save_test_outputs(test_name: str, trades_df: pd.DataFrame, metrics: dict, eq_df: pd.DataFrame):
    test_dir = OUTPUT_DIR / test_name
    test_dir.mkdir(exist_ok=True)
    synthetic = {"SPY_PUT_SPREAD", "SPY_CALL_SPREAD"}
    mr_trades = trades_df[
        ~trades_df["ticker"].str.endswith("_GAP") &
        ~trades_df["ticker"].isin(synthetic)
    ].copy()
    mr_trades.to_csv(test_dir / "trades.csv", index=False)
    trades_df.to_csv(test_dir / "trades_all.csv", index=False)
    eq_df.to_csv(test_dir / "equity_curve.csv", index=False)
    with open(test_dir / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, default=str)


def extract_summary(test_name: str, metrics: dict) -> dict:
    return {
        "test":      test_name,
        "cagr":      metrics.get("cagr_pct", 0),
        "max_dd":    metrics.get("max_drawdown_pct", 0),
        "sharpe":    metrics.get("sharpe_ratio", 0),
        "pf":        metrics.get("profit_factor", 0),
        "final_eq":  metrics.get("final_equity", 0),
        "wr":        metrics.get("win_rate_pct", 0),
        "trades_yr": metrics.get("trades_per_year", 0),
        "non_mr_pnl": metrics.get("note_non_mr_pnl", 0),
    }


def print_comparison(summaries: list):
    baseline_v35 = next((s for s in summaries if s["test"] == "Baseline_V35"), None)
    baseline_i3  = next((s for s in summaries if s["test"] == "Baseline_V35_I3"), None)

    print("\n" + "=" * 120)
    print(" IDEAS V3 -- COMPARISON TABLE")
    print(f" Baseline V35:     CAGR {baseline_v35['cagr']:.2f}% | MaxDD {baseline_v35['max_dd']:.2f}% | "
          f"Sharpe {baseline_v35['sharpe']:.2f} | Equity ${baseline_v35['final_eq']:,.0f}")
    print(f" Baseline V35+I3:  CAGR {baseline_i3['cagr']:.2f}% | MaxDD {baseline_i3['max_dd']:.2f}% | "
          f"Sharpe {baseline_i3['sharpe']:.2f} | Equity ${baseline_i3['final_eq']:,.0f}")
    print("=" * 120)
    hdr = (f"{'Test':<22} {'CAGR%':>7} {'MaxDD%':>8} {'Sharpe':>7} {'PF':>6} "
           f"{'FinalEq':>13} {'WR%':>6} {'Tr/Yr':>7} {'NonMR P&L':>12}")
    print(hdr)
    print("-" * 120)

    for s in summaries:
        marker = ""
        if baseline_i3 and s["test"] not in ("Baseline_V35", "Baseline_V35_I3"):
            dd_better   = s["max_dd"] - baseline_i3["max_dd"]   # positive = less DD
            cagr_better = s["cagr"]   - baseline_i3["cagr"]
            eq_better   = s["final_eq"] - baseline_i3["final_eq"]
            if dd_better > 2 and cagr_better > -2:
                marker = " ★"
            elif dd_better > 5 or eq_better > 200_000:
                marker = " ◆"
        print(
            f"{s['test']:<22} {s['cagr']:>7.2f} {s['max_dd']:>8.2f} {s['sharpe']:>7.2f} "
            f"{s['pf']:>6.2f} {s['final_eq']:>13,.0f} {s['wr']:>6.2f} {s['trades_yr']:>7.0f} "
            f"{s['non_mr_pnl']:>12,.0f}{marker}"
        )

    print("=" * 120)
    print(f"\n  ★ = Beats V35+I3 baseline on MaxDD (>2pp) without major CAGR loss (<2pp)")
    print(f"  ◆ = Significant improvement on MaxDD (>5pp) OR equity (>$200k vs V35+I3)")
    print(f"  NonMR P&L = combined put/call/gap-capture P&L (separate from MR trades)")
    print()

    best_dd  = min(summaries, key=lambda x: x["max_dd"])
    best_cagr= max(summaries, key=lambda x: x["cagr"])
    best_sh  = max(summaries, key=lambda x: x["sharpe"])
    best_eq  = max(summaries, key=lambda x: x["final_eq"])
    print("  TOP RESULTS:")
    print(f"    Lowest MaxDD  : {best_dd['test']} ({best_dd['max_dd']:.2f}%)")
    print(f"    Highest CAGR  : {best_cagr['test']} ({best_cagr['cagr']:.2f}%)")
    print(f"    Highest Sharpe: {best_sh['test']} ({best_sh['sharpe']:.2f})")
    print(f"    Highest Equity: {best_eq['test']} (${best_eq['final_eq']:,.0f})")
    print("=" * 120)


# =============================================================================
# Main
# =============================================================================
def main():
    print("\n" + "=" * 70)
    print(" NAIVE MR BACKTEST -- IDEAS V3")
    print(" 6 new ideas vs V35 and V35+Idea3 (put spread @ 1.5%/qtr) baselines")
    print(" Ideas: VIX Term Structure | 52wk High | Gap Capture | Analyst | Call Spread")
    print("=" * 70)

    # ── Load data once ────────────────────────────────────────────────────────
    print("\n[Setup] Loading universe and price data...")
    universe   = get_universe()
    price_data = download_prices(universe)
    spy_df, vix_df, sector_data = download_reference_data()
    earnings_map = build_earnings_dates(list(price_data.keys()))

    # Idea D: download VIX3M
    vix3m_series = download_vix3m()

    # Idea C: fetch analyst coverage once (slow, do once)
    # Only fetch if any test uses analyst -- avoids 30-min fetch when not needed
    uses_analyst = any(cfg["analyst"] for cfg in TESTS)
    if uses_analyst:
        analyst_coverage = build_analyst_coverage(list(price_data.keys()))
    else:
        analyst_coverage = {}

    summaries = []

    for cfg in TESTS:
        test_name = cfg["name"]
        try:
            trades_df = run_backtest_v3(
                price_data, spy_df, vix_df, sector_data, earnings_map,
                vix3m_series, analyst_coverage, cfg
            )
            if trades_df.empty:
                print(f"[{test_name}] WARNING: No trades generated.")
                continue

            synthetic_tickers = {"SPY_PUT_SPREAD", "SPY_CALL_SPREAD"}
            mr_trades = trades_df[
                ~trades_df["ticker"].str.endswith("_GAP") &
                ~trades_df["ticker"].isin(synthetic_tickers)
            ].copy()

            if mr_trades.empty:
                print(f"[{test_name}] No MR trades.")
                continue

            metrics, eq_df = compute_metrics(mr_trades)

            # Adjust final equity for non-MR P&L
            non_mr_pnl = trades_df[
                trades_df["ticker"].str.endswith("_GAP") |
                trades_df["ticker"].isin(synthetic_tickers)
            ]["pnl_usd"].sum()
            metrics["final_equity"]     = round(metrics["final_equity"] + non_mr_pnl, 2)
            metrics["version"]          = test_name
            metrics["note_non_mr_pnl"]  = round(non_mr_pnl, 2)

            save_test_outputs(test_name, trades_df, metrics, eq_df)
            summaries.append(extract_summary(test_name, metrics))

            print(f"[{test_name}] CAGR: {metrics['cagr_pct']:.2f}% | "
                  f"MaxDD: {metrics['max_drawdown_pct']:.2f}% | "
                  f"Sharpe: {metrics['sharpe_ratio']:.2f} | "
                  f"FinalEq: ${metrics['final_equity']:,.0f} | "
                  f"NonMR P&L: ${non_mr_pnl:,.0f}")

        except Exception as e:
            print(f"[{test_name}] ERROR: {e}")
            import traceback; traceback.print_exc()

    if summaries:
        print_comparison(summaries)
        with open(OUTPUT_DIR / "comparison.json", "w") as f:
            json.dump(summaries, f, indent=2, default=str)
        print(f"\n  Results saved to: {OUTPUT_DIR.resolve()}")
    else:
        print("[ERROR] No tests completed.")


if __name__ == "__main__":
    main()
