# backtest_ideas_v2.py
#
# Multi-test runner: 4 new drawdown-reduction ideas vs V35 baseline.
#
# ─────────────────────────────────────────────────────────────────────────────
# IDEA 1 — Twin-Engine (Bear Momentum Overlay)
#   During SPY bear regime (below 200d MA), instead of sitting in cash, allocate
#   a configurable slice of idle capital to a momentum strategy: buy the top-N
#   strongest 20-day performers from the same universe. This is the OPPOSITE
#   signal to MR. The hypothesis: momentum profits during grinding bear regimes
#   (W7/W8 failures) offset MR losses without blocking crash-recovery entries.
#   Key difference from prior bear overlay tests: this uses EQUITY momentum on
#   the same universe, NOT bonds/GLD/inverse ETFs which all failed.
#
# IDEA 2 — Portfolio-Level Volatility Targeting
#   Measure the realized 10-day volatility of the entire open book as a portfolio
#   (not per-stock). When portfolio vol exceeds a threshold (e.g., 20% annualized),
#   scale ALL new position sizes down proportionally. During calm periods, allow
#   up to the normal size. This captures the crash-correlation effect: 60 stocks
#   all fall together, making portfolio vol spike even if per-stock vol looks normal.
#   Key difference from Ideas Test B (per-stock vol scaling): this operates on
#   the PORTFOLIO return series, not individual ATR.
#
# IDEA 3 — Synthetic SPY Put Spread (Tail Hedge Simulation)
#   Simulate holding a rolling 5%/15% OTM SPY put spread, paid as a quarterly
#   premium drag (~0.75% of portfolio notional / quarter). When SPY drops more
#   than 5% from the spread entry price within the quarter, the spread pays out
#   linearly up to a cap at 15% SPY decline. This is insurance on the existing
#   strategy, not an overlay strategy. Models the structural impact without
#   requiring options infrastructure.
#
# IDEA 4 — Per-Sector Streak Filtering
#   Instead of portfolio-wide streak counting (which blocks crash-recovery entries),
#   track win/loss streaks PER SECTOR. When a specific sector is on a 3+ loss streak,
#   reduce position size for NEW entries in that sector only. Other sectors are
#   unaffected. The hypothesis: sector-specific distress (e.g., tech in 2022) is
#   the actual source of grinding losses, not market-wide regime failure.
#
# COMBINATIONS TESTED:
#   Baseline, Idea1, Idea2, Idea3, Idea4, Ideas1+2, Ideas1+3, Ideas2+3,
#   Ideas2+4, Ideas3+4, Ideas1+2+3, Ideas1+2+4, Ideas2+3+4, Ideas1+2+3+4
#
# OUTPUT: results_ideas_v2/ — per-test metrics.json + trades.csv + equity_curve.csv
#         + comparison table printed at end.
#
# IMPORTANT: Does NOT modify backtest_nmr_lib.py. V35 is untouched.
# ─────────────────────────────────────────────────────────────────────────────

import json
import warnings
import datetime
from pathlib import Path
from collections import defaultdict

import numpy as np
import pandas as pd
import yfinance as yf

warnings.filterwarnings("ignore")

# Import V35 infrastructure (universe, downloads, signals, metrics, etc.)
from backtest_nmr_lib import (
    get_universe,
    download_prices,
    download_reference_data,
    build_earnings_dates,
    compute_metrics,
    save_outputs,
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
    START_DATE,
    END_DATE,
    MAX_POSITIONS,
    POSITION_SIZE,
    POSITION_SIZE_HIGH,
    POSITION_SIZE_LOW,
    MA_WINDOW,
    VOL_MA_PERIOD,
    ATR_PERIOD,
    RSI_PERIOD,
    RSI_THRESHOLD,
    ATR_MIN_PCT,
    MIN_DOLLAR_VOLUME,
    MIN_CONSEC_DOWN,
    MIN_HOLD_BEFORE_EXIT,
    VELOCITY_CRASH_5D_THRESHOLD,
    VELOCITY_CRASH_PAUSE_DAYS,
    VIX_SPIKE_PAUSE_DAYS,
    VIX_LOW,
    GAP_DOWN_MAX,
    GAP_UP_MAX,
    REENTRY_COOLDOWN_DAYS,
    MAX_SECTOR_POSITIONS,
    EARNINGS_MONTHS,
    EARNINGS_BLACKOUT,
    TOP_SIGNAL_PCT,
    TOP_SIGNAL_MULTIPLIER,
    TOP_SIGNAL_HARD_CAP,
    MIN_CANDIDATES_FOR_C5,
    COMMISSION_RATE,
    COMMISSION_MIN,
)

OUTPUT_DIR = Path("results_ideas_v2")
OUTPUT_DIR.mkdir(exist_ok=True)

# =============================================================================
# Idea-specific parameters
# =============================================================================

# Idea 1: Twin-Engine bear momentum overlay
TWIN_ENGINE_BEAR_ALLOC   = 0.25   # fraction of IDLE capital allocated to momentum in bear
TWIN_ENGINE_TOP_N        = 10     # number of top momentum stocks to hold
TWIN_ENGINE_LOOKBACK     = 20     # days of return for momentum ranking
TWIN_ENGINE_HOLD_DAYS    = 10     # days before momentum position is re-evaluated
TWIN_ENGINE_MAX_SIZE     = 0.03   # max size per momentum position (of total portfolio)

# Idea 2: Portfolio-level vol targeting
PORT_VOL_TARGET          = 0.15   # 15% annualized target portfolio vol
PORT_VOL_LOOKBACK        = 10     # trading days of portfolio returns to measure
PORT_VOL_SCALE_FLOOR     = 0.40   # minimum scale factor (won't go below 40% of normal size)
PORT_VOL_SCALE_CAP       = 1.00   # maximum scale factor (don't lever up)
PORT_VOL_HIGH_THRESHOLD  = 0.20   # annualized vol above which we scale DOWN

# Idea 3: Synthetic SPY put spread
PUT_SPREAD_LOWER_OTM     = 0.05   # 5% OTM lower strike (protection starts here)
PUT_SPREAD_UPPER_OTM     = 0.15   # 15% OTM upper strike (max payout)
PUT_SPREAD_QUARTERLY_COST= 0.0075 # 0.75% of portfolio per quarter (premium drag)
PUT_SPREAD_RENEW_DAYS    = 63     # ~1 quarter in trading days

# Idea 4: Per-sector streak filtering
SECTOR_STREAK_TRIGGER    = 3      # consecutive sector losses to activate filter
SECTOR_STREAK_SIZE_MULT  = 0.50   # reduce to 50% size for that sector
SECTOR_STREAK_RESET_WIN  = 1      # wins needed to reset streak

# =============================================================================
# Test matrix
# =============================================================================

TESTS = [
    {"name": "Baseline_V35",       "twin": False, "pvol": False, "puts": False, "sector_streak": False},
    {"name": "Idea1_TwinEngine",   "twin": True,  "pvol": False, "puts": False, "sector_streak": False},
    {"name": "Idea2_PortVol",      "twin": False, "pvol": True,  "puts": False, "sector_streak": False},
    {"name": "Idea3_PutSpread",    "twin": False, "pvol": False, "puts": True,  "sector_streak": False},
    {"name": "Idea4_SectorStreak", "twin": False, "pvol": False, "puts": False, "sector_streak": True},
    {"name": "Ideas1+2",           "twin": True,  "pvol": True,  "puts": False, "sector_streak": False},
    {"name": "Ideas1+3",           "twin": True,  "pvol": False, "puts": True,  "sector_streak": False},
    {"name": "Ideas2+3",           "twin": False, "pvol": True,  "puts": True,  "sector_streak": False},
    {"name": "Ideas2+4",           "twin": False, "pvol": True,  "puts": False, "sector_streak": True},
    {"name": "Ideas3+4",           "twin": False, "pvol": False, "puts": True,  "sector_streak": True},
    {"name": "Ideas1+2+3",         "twin": True,  "pvol": True,  "puts": True,  "sector_streak": False},
    {"name": "Ideas1+2+4",         "twin": True,  "pvol": True,  "puts": False, "sector_streak": True},
    {"name": "Ideas2+3+4",         "twin": False, "pvol": True,  "puts": True,  "sector_streak": True},
    {"name": "Ideas1+2+3+4",       "twin": True,  "pvol": True,  "puts": True,  "sector_streak": True},
]


# =============================================================================
# Helper: compute portfolio realized vol from daily P&L history
# =============================================================================

def compute_portfolio_vol(daily_pnl_history: list, lookback: int = PORT_VOL_LOOKBACK) -> float:
    """
    Given a list of recent daily portfolio P&L values, compute annualized
    realized vol of the portfolio return series. Returns 0.0 if insufficient data.
    """
    if len(daily_pnl_history) < lookback + 1:
        return 0.0
    recent = daily_pnl_history[-lookback:]
    returns = np.diff(recent) / np.array(recent[:-1])
    if len(returns) < 2:
        return 0.0
    return float(np.std(returns) * np.sqrt(252))


def get_portfolio_vol_scale(port_vol: float) -> float:
    """
    Given current annualized portfolio vol, return a sizing scale factor.
    Above PORT_VOL_HIGH_THRESHOLD: scale down proportionally toward PORT_VOL_SCALE_FLOOR.
    Below threshold: full size (scale = 1.0).
    """
    if port_vol <= 0 or port_vol <= PORT_VOL_TARGET:
        return PORT_VOL_SCALE_CAP
    # Linear scale-down: at 2x threshold -> floor
    over = (port_vol - PORT_VOL_TARGET) / PORT_VOL_TARGET
    scale = 1.0 - over * (1.0 - PORT_VOL_SCALE_FLOOR)
    return float(np.clip(scale, PORT_VOL_SCALE_FLOOR, PORT_VOL_SCALE_CAP))


# =============================================================================
# Helper: momentum signal for twin-engine
# =============================================================================

def get_momentum_candidates(price_data: dict, today, signals: dict,
                             open_mr_positions: set,
                             open_mom_positions: set) -> list:
    """
    Returns list of (momentum_score, tkr) for stocks eligible for momentum entry:
    - Must be BELOW 200d MA (bear stocks, opposite of MR filter)
    - Not already in an MR or momentum position
    - Must have valid 20-day return
    - Sorted descending by 20-day return (strongest momentum first)
    """
    candidates = []
    for tkr, df in price_data.items():
        if tkr in open_mr_positions or tkr in open_mom_positions:
            continue
        if today not in df.index:
            continue
        loc = df.index.get_loc(today)
        if loc < TWIN_ENGINE_LOOKBACK + MA_WINDOW:
            continue
        close_today = float(df["Close"].iloc[loc])
        close_past = float(df["Close"].iloc[loc - TWIN_ENGINE_LOOKBACK])
        ma200 = float(df["Close"].iloc[max(0, loc - MA_WINDOW):loc].mean())
        if close_past <= 0 or ma200 <= 0:
            continue
        # Only momentum in stocks ABOVE their 200d (trending stocks, not beaten-down ones)
        # This avoids doubling down on the same fallen stocks MR targets
        if close_today <= ma200:
            continue
        mom_return = (close_today - close_past) / close_past
        if mom_return < 0.02:  # only genuinely positive momentum
            continue
        candidates.append((mom_return, tkr))
    candidates.sort(reverse=True)
    return candidates[:TWIN_ENGINE_TOP_N * 3]  # return top 3x for position limit buffer


# =============================================================================
# Helper: put spread payout on a given day
# =============================================================================

def compute_put_spread_intrinsic_pct(spy_ref_price: float, spy_today_price: float) -> float:
    """
    Compute the intrinsic value of the 5%/15% OTM SPY put spread at expiry,
    as a FRACTION of the reference (entry) SPY price.

    This is called ONCE at expiry (not every day), giving a single payout
    as a percentage of the notional protected.

    - Long put: strike = ref * (1 - PUT_SPREAD_LOWER_OTM)   [5% OTM]
    - Short put: strike = ref * (1 - PUT_SPREAD_UPPER_OTM)  [15% OTM]
    - Max payout: 10% of ref price (spread width)
    - Payout zone: SPY down 5-15% from ref

    Returns a fraction (e.g. 0.08 = 8% of notional). Zero if SPY above lower strike.
    """
    lower_strike = spy_ref_price * (1 - PUT_SPREAD_LOWER_OTM)
    upper_strike = spy_ref_price * (1 - PUT_SPREAD_UPPER_OTM)
    spread_width_pct = PUT_SPREAD_UPPER_OTM - PUT_SPREAD_LOWER_OTM  # 0.10 = 10%

    if spy_today_price >= lower_strike:
        return 0.0  # SPY hasn't fallen enough to trigger

    # How far through the spread are we?
    spy_decline_pct = (spy_ref_price - spy_today_price) / spy_ref_price
    payout_pct = spy_decline_pct - PUT_SPREAD_LOWER_OTM  # excess beyond lower strike
    payout_pct = max(0.0, min(payout_pct, spread_width_pct))  # cap at spread width
    return payout_pct


# =============================================================================
# Core backtest with idea injections
# =============================================================================

def run_backtest_ideas(price_data: dict, spy_df: pd.DataFrame, vix_df: pd.DataFrame,
                       sector_data: dict, earnings_map: dict, cfg: dict) -> pd.DataFrame:
    """
    V35 simulation loop with optional idea overlays injected.
    cfg keys: twin, pvol, puts, sector_streak
    """
    test_name = cfg["name"]
    use_twin         = cfg["twin"]
    use_pvol         = cfg["pvol"]
    use_puts         = cfg["puts"]
    use_sector_streak= cfg["sector_streak"]

    print(f"\n{'='*70}")
    print(f"[Test] {test_name}")
    print(f"  Twin-Engine={use_twin} | PortVol={use_pvol} | PutSpread={use_puts} | SectorStreak={use_sector_streak}")
    print(f"{'='*70}")

    spy_regime = spy_df["spy_ok"].to_dict()
    spy_close  = spy_df["Close"].squeeze()

    all_dates: set = set()
    for df in price_data.values():
        all_dates.update(df.index)
    trading_dates = sorted(all_dates)

    # Pre-generate MR signals
    signals: dict[str, pd.DataFrame] = {}
    min_bars = MA_WINDOW + VOL_MA_PERIOD + ATR_PERIOD + MIN_CONSEC_DOWN + 5
    for tkr, df in price_data.items():
        if len(df) > min_bars:
            signals[tkr] = generate_signals(df)

    # ── State ──────────────────────────────────────────────────────────────────
    portfolio_value   = INITIAL_CAPITAL
    portfolio_peak    = None
    current_drawdown  = 0.0
    open_positions    = {}          # MR positions
    open_mom_positions= {}          # momentum positions (Idea 1)
    trades            = []
    cooldown_map      = {}
    last_vix_spike    = None
    last_velocity_crash = None

    # Idea 2: portfolio vol tracking
    daily_portfolio_values = [INITIAL_CAPITAL]  # one value per trading day

    # Idea 3: put spread state
    put_ref_price       = None
    put_ref_date        = None
    put_notional        = 0.0    # portfolio value at spread inception (fixed)
    put_min_spy         = 9999.0 # worst SPY close seen in current quarter
    put_days_since_renew= 0
    put_cumulative_pnl  = 0.0

    # Idea 4: per-sector streak tracking
    sector_loss_streaks = defaultdict(int)   # sector etf -> consecutive losses
    sector_win_streaks  = defaultdict(int)

    # ── Main loop ──────────────────────────────────────────────────────────────
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
                days_since = (pd.Timestamp(today) - pd.Timestamp(last_velocity_crash)).days
                if days_since <= VELOCITY_CRASH_PAUSE_DAYS:
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

        # ── Idea 2: Compute portfolio vol scale ───────────────────────────────
        port_vol_scale = 1.0
        if use_pvol:
            daily_portfolio_values.append(portfolio_value)
            if len(daily_portfolio_values) > PORT_VOL_LOOKBACK + 10:
                daily_portfolio_values = daily_portfolio_values[-(PORT_VOL_LOOKBACK + 10):]
            pvol = compute_portfolio_vol(daily_portfolio_values, PORT_VOL_LOOKBACK)
            port_vol_scale = get_portfolio_vol_scale(pvol)

        # ── Idea 3: Put spread daily accounting ───────────────────────────────
        if use_puts and today in spy_df.index:
            spy_price_today = float(spy_close.loc[today]) if today in spy_close.index else None
            if spy_price_today is not None:
                # Renew spread quarterly
                if put_ref_price is None or put_days_since_renew >= PUT_SPREAD_RENEW_DAYS:
                    # Deduct premium on renew
                    quarterly_premium = portfolio_value * PUT_SPREAD_QUARTERLY_COST
                    portfolio_value  -= quarterly_premium
                    put_ref_price    = spy_price_today
                    put_ref_date     = today
                    put_notional     = portfolio_value   # fix notional at inception
                    put_min_spy      = spy_price_today   # track worst SPY for settlement
                    put_days_since_renew = 0
                    trades.append({
                        "ticker": "SPY_PUT_SPREAD", "entry_date": today, "exit_date": today,
                        "entry_price": spy_price_today, "exit_price": spy_price_today,
                        "shares": 0, "commission": 0,
                        "pnl_usd": -quarterly_premium,
                        "pnl_pct": -PUT_SPREAD_QUARTERLY_COST * 100,
                        "days_held": 0, "exit_reason": "put_premium",
                        "tier": 0, "consec_down": 0,
                        "portfolio_val": portfolio_value,
                    })
                else:
                    put_days_since_renew += 1
                    # Settle at expiry only (last day of the quarter window).
                    # Use the WORST SPY close during the quarter for max realism --
                    # track the minimum SPY price seen since spread inception.
                    put_min_spy = min(put_min_spy, spy_price_today)

                    # On the day BEFORE renewal, settle the expiring spread
                    if put_days_since_renew == PUT_SPREAD_RENEW_DAYS - 1:
                        payout_pct = compute_put_spread_intrinsic_pct(put_ref_price, put_min_spy)
                        if payout_pct > 0:
                            # Notional = portfolio value at spread inception (fixed, not growing)
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
                                "tier": 0, "consec_down": 0,
                                "portfolio_val": portfolio_value,
                            })

        # ── MR Exits ──────────────────────────────────────────────────────────
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
                    "consec_down": pos["consec_down_at_entry"],
                    "portfolio_val": portfolio_value + pnl,
                })
                portfolio_value += pnl
                pos["shares_remaining"] -= partial_shares
                pos["partial_done"] = True
                pos["profit_target"] = pos["profit_target"] * 2
                # Idea 4: update sector streak
                if use_sector_streak:
                    sec = TICKER_TO_SECTOR.get(tkr)
                    if sec:
                        sector_loss_streaks[sec] = 0
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
                    "consec_down": pos["consec_down_at_entry"],
                    "portfolio_val": portfolio_value + pnl,
                })
                portfolio_value += pnl
                if time_stop:
                    cooldown_map[tkr] = today
                # Idea 4: update sector streak on exit
                if use_sector_streak:
                    sec = TICKER_TO_SECTOR.get(tkr)
                    if sec:
                        if pnl > 0:
                            sector_loss_streaks[sec] = 0
                        else:
                            sector_loss_streaks[sec] = sector_loss_streaks[sec] + 1
                to_close.append(tkr)

        for tkr in to_close:
            del open_positions[tkr]

        # ── Momentum exits (Idea 1) ───────────────────────────────────────────
        mom_to_close = []
        if use_twin:
            for tkr, pos in open_mom_positions.items():
                if today not in price_data.get(tkr, pd.DataFrame()).index:
                    continue
                days_held = (pd.Timestamp(today) - pd.Timestamp(pos["entry_date"])).days
                if days_held >= TWIN_ENGINE_HOLD_DAYS:
                    df_t = price_data[tkr]
                    exit_price = float(df_t.loc[today, "Close"])
                    entry_price = pos["entry_price"]
                    shares = pos["shares"]
                    commission = calc_commission(shares, exit_price)
                    pnl = (exit_price - entry_price) * shares - commission - pos["entry_commission"]
                    portfolio_value += pnl
                    trades.append({
                        "ticker": tkr + "_MOM", "entry_date": pos["entry_date"], "exit_date": today,
                        "entry_price": entry_price, "exit_price": exit_price,
                        "shares": shares, "commission": round(commission, 4),
                        "pnl_usd": pnl, "pnl_pct": (exit_price / entry_price - 1) * 100,
                        "days_held": days_held, "exit_reason": "momentum_hold",
                        "tier": -1, "consec_down": 0,
                        "portfolio_val": portfolio_value,
                    })
                    mom_to_close.append(tkr)
            for tkr in mom_to_close:
                del open_mom_positions[tkr]

        # ── Guard: standard MR entry conditions ───────────────────────────────
        if not spy_ok or paused or velocity_paused:
            # Idea 1: in bear regime, run momentum overlay
            if use_twin and not spy_ok and not paused and not velocity_paused:
                # Only add momentum positions if we have idle capital
                n_total_positions = len(open_positions) + len(open_mom_positions)
                if n_total_positions < MAX_POSITIONS:
                    mom_candidates = get_momentum_candidates(
                        price_data, today, signals,
                        set(open_positions.keys()), set(open_mom_positions.keys())
                    )
                    slots_available = min(
                        TWIN_ENGINE_TOP_N - len(open_mom_positions),
                        MAX_POSITIONS - n_total_positions
                    )
                    for mom_score, tkr in mom_candidates[:slots_available]:
                        if tkr in open_mom_positions:
                            continue
                        df_t = price_data[tkr]
                        if today not in df_t.index:
                            continue
                        loc = df_t.index.get_loc(today)
                        if loc + 1 >= len(df_t):
                            continue
                        entry_price = float(df_t.iloc[loc + 1]["Open"])
                        if entry_price <= 0:
                            continue
                        # Size: fraction of idle capital, capped
                        pos_size = min(TWIN_ENGINE_MAX_SIZE, TWIN_ENGINE_BEAR_ALLOC / TWIN_ENGINE_TOP_N)
                        shares = (portfolio_value * pos_size) / entry_price
                        entry_comm = calc_commission(shares, entry_price)
                        open_mom_positions[tkr] = {
                            "entry_date": df_t.index[loc + 1],
                            "entry_price": entry_price,
                            "shares": shares,
                            "entry_commission": entry_comm,
                        }
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
            rsi2          = float(row["rsi2"])
            atr_pct       = float(row["atr_pct"])
            composite_score = rsi2 / atr_pct if atr_pct > 0 else rsi2 * 1000
            candidates.append((composite_score, tkr, int(row["consec_down"]), rsi2))

        candidates.sort(key=lambda x: x[0])
        n_candidates = len(candidates)
        top_n = max(1, int(n_candidates * TOP_SIGNAL_PCT))

        for rank, (composite_score, tkr, consec_val, rsi_val) in enumerate(candidates):
            if len(open_positions) >= MAX_POSITIONS:
                break
            tkr_df     = signals[tkr]
            today_idx  = tkr_df.index.get_loc(today)
            if today_idx + 1 >= len(tkr_df):
                continue
            next_row     = tkr_df.iloc[today_idx + 1]
            entry_price  = float(next_row["Open"])
            if entry_price <= 0:
                continue
            prev_close   = float(tkr_df.iloc[today_idx]["Close"])
            gap_pct      = (entry_price - prev_close) / prev_close
            if gap_pct < GAP_DOWN_MAX or gap_pct > GAP_UP_MAX:
                continue

            tier_cfg = get_tier(consec_val)

            # V35 signal multiplier
            size_multiplier = 1.0
            if n_candidates >= MIN_CANDIDATES_FOR_C5 and rank < top_n:
                size_multiplier = TOP_SIGNAL_MULTIPLIER

            # Idea 4: sector streak size reduction
            if use_sector_streak:
                sec = TICKER_TO_SECTOR.get(tkr)
                if sec and sector_loss_streaks[sec] >= SECTOR_STREAK_TRIGGER:
                    size_multiplier *= SECTOR_STREAK_SIZE_MULT

            pos_size = get_position_size(
                today, vix_df, current_drawdown,
                multiplier=size_multiplier, hard_cap=TOP_SIGNAL_HARD_CAP,
            )

            # Idea 2: apply portfolio vol scale to ALL new positions
            if use_pvol:
                pos_size = pos_size * port_vol_scale

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

    # Filter out synthetic trades (put spread) for metric display
    mr_trades = trades_df[~trades_df["ticker"].str.endswith("_MOM") &
                          (trades_df["ticker"] != "SPY_PUT_SPREAD")].copy()

    mr_trades.to_csv(test_dir / "trades.csv", index=False)
    trades_df.to_csv(test_dir / "trades_all.csv", index=False)
    eq_df.to_csv(test_dir / "equity_curve.csv", index=False)
    with open(test_dir / "metrics.json", "w") as f:
        json.dump(metrics, f, indent=2, default=str)


def extract_summary(test_name: str, metrics: dict) -> dict:
    return {
        "test":       test_name,
        "cagr":       metrics.get("cagr_pct", 0),
        "max_dd":     metrics.get("max_drawdown_pct", 0),
        "sharpe":     metrics.get("sharpe_ratio", 0),
        "pf":         metrics.get("profit_factor", 0),
        "final_eq":   metrics.get("final_equity", 0),
        "wr":         metrics.get("win_rate_pct", 0),
        "trades_yr":  metrics.get("trades_per_year", 0),
    }


def print_comparison(summaries: list):
    print("\n" + "=" * 110)
    print(" IDEAS V2 -- COMPARISON TABLE (all vs V35 Baseline)")
    print("=" * 110)
    hdr = (f"{'Test':<22} {'CAGR%':>7} {'MaxDD%':>8} {'Sharpe':>7} {'PF':>6} "
           f"{'FinalEq':>12} {'WR%':>6} {'Tr/Yr':>7}")
    print(hdr)
    print("-" * 110)
    baseline = next((s for s in summaries if s["test"] == "Baseline_V35"), None)
    for s in summaries:
        marker = ""
        if baseline and s["test"] != "Baseline_V35":
            dd_diff = s["max_dd"] - baseline["max_dd"]  # positive = LESS drawdown (better)
            cagr_diff = s["cagr"] - baseline["cagr"]
            if dd_diff > 2 and cagr_diff > -2:
                marker = " ★"   # better DD without much CAGR cost
            elif dd_diff > 5:
                marker = " ◆"   # significant DD improvement
        print(
            f"{s['test']:<22} {s['cagr']:>7.2f} {s['max_dd']:>8.2f} {s['sharpe']:>7.2f} "
            f"{s['pf']:>6.2f} {s['final_eq']:>12,.0f} {s['wr']:>6.2f} {s['trades_yr']:>7.0f}{marker}"
        )
    print("=" * 110)
    if baseline:
        print(f"\n  Baseline (V35): CAGR {baseline['cagr']:.2f}% | MaxDD {baseline['max_dd']:.2f}% | "
              f"Sharpe {baseline['sharpe']:.2f} | PF {baseline['pf']:.2f} | "
              f"Equity ${baseline['final_eq']:,.0f}")
        print(f"\n  ★ = Better MaxDD (>2pp improvement) without major CAGR cost (<2pp loss)")
        print(f"  ◆ = Significant MaxDD improvement (>5pp)")
    print()

    # Best results section
    print("─" * 110)
    print("  TOP RESULTS BY METRIC:")
    best_dd   = min(summaries, key=lambda x: x["max_dd"])
    best_cagr = max(summaries, key=lambda x: x["cagr"])
    best_sh   = max(summaries, key=lambda x: x["sharpe"])
    print(f"  Lowest MaxDD  : {best_dd['test']} ({best_dd['max_dd']:.2f}%)")
    print(f"  Highest CAGR  : {best_cagr['test']} ({best_cagr['cagr']:.2f}%)")
    print(f"  Highest Sharpe: {best_sh['test']} ({best_sh['sharpe']:.2f})")
    print("=" * 110)


# =============================================================================
# Main
# =============================================================================

def main():
    print("\n" + "=" * 70)
    print(" NAIVE MR BACKTEST -- IDEAS V2 (4 New Drawdown Ideas)")
    print(f" V35 Baseline: CAGR 18.81% | MaxDD -56.22% | Sharpe 0.71")
    print(" Ideas: Twin-Engine | Portfolio Vol Targeting | Put Spread | Sector Streak")
    print("=" * 70)

    # ── Load data once, reuse across all tests ─────────────────────────────────
    print("\n[Setup] Loading universe and data (shared across all tests)...")
    universe   = get_universe()
    price_data = download_prices(universe)
    spy_df, vix_df, sector_data = download_reference_data()
    earnings_map = build_earnings_dates(list(price_data.keys()))

    summaries = []

    for cfg in TESTS:
        test_name = cfg["name"]
        try:
            trades_df = run_backtest_ideas(
                price_data, spy_df, vix_df, sector_data, earnings_map, cfg
            )
            if trades_df.empty:
                print(f"[{test_name}] WARNING: No trades generated.")
                continue

            # Compute metrics on MR trades only (exclude put/momentum synthetic records)
            mr_trades = trades_df[
                ~trades_df["ticker"].str.endswith("_MOM") &
                (trades_df["ticker"] != "SPY_PUT_SPREAD")
            ].copy()

            # But equity curve should reflect ALL P&L (including put/momentum)
            # Recompute equity from all trades for final_equity
            if not mr_trades.empty:
                metrics, eq_df = compute_metrics(mr_trades)
            else:
                print(f"[{test_name}] No MR trades.")
                continue

            # Adjust final equity to include put/momentum P&L
            non_mr_pnl = trades_df[
                trades_df["ticker"].str.endswith("_MOM") |
                (trades_df["ticker"] == "SPY_PUT_SPREAD")
            ]["pnl_usd"].sum()
            metrics["final_equity"] = round(metrics["final_equity"] + non_mr_pnl, 2)
            metrics["version"]      = test_name
            metrics["note_non_mr_pnl"] = round(non_mr_pnl, 2)

            save_test_outputs(test_name, trades_df, metrics, eq_df)
            summaries.append(extract_summary(test_name, metrics))

            print(f"[{test_name}] CAGR: {metrics['cagr_pct']:.2f}% | "
                  f"MaxDD: {metrics['max_drawdown_pct']:.2f}% | "
                  f"Sharpe: {metrics['sharpe_ratio']:.2f} | "
                  f"FinalEq: ${metrics['final_equity']:,.0f}")

        except Exception as e:
            print(f"[{test_name}] ERROR: {e}")
            import traceback; traceback.print_exc()

    if summaries:
        print_comparison(summaries)

        # Save master comparison JSON
        with open(OUTPUT_DIR / "comparison.json", "w") as f:
            json.dump(summaries, f, indent=2, default=str)
        print(f"\n  Results saved to: {OUTPUT_DIR.resolve()}")
    else:
        print("[ERROR] No tests completed successfully.")


if __name__ == "__main__":
    main()
