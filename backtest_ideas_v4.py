# backtest_ideas_v4.py
#
# Multi-test runner: 7 new signal quality ideas vs V35+I3 confirmed baseline.
#
# BASELINES (always run):
#   Baseline_V35     : Pure V35. Reference.
#   Baseline_V35_I3  : V35 + put spread @ 1.5%/qtr. Confirmed best.
#                      CAGR ~19.5% | MaxDD ~-53% | Sharpe ~0.73
#
# THE KEY INSIGHT behind all 7 ideas:
#   Your current signal treats all 4-day declines identically. But the
#   CAUSE of the decline predicts whether it will revert. Four independent
#   dimensions distinguish noise-driven (good MR) from informed (bad MR):
#     1. Was the decline overnight or intraday? (Idea1 -- overnight = noise)
#     2. Is it idiosyncratic vs the sector? (Idea2 -- idiosyncratic = good)
#     3. What is the skewness of recent returns? (Idea4 -- neg skew = good)
#     4. What was volume doing? (Idea5 -- low turnover = noise-driven)
#     5. How correlated is the open book? (Idea6 -- low correl = good regime)
#   Plus two orthogonal mechanisms:
#     6. Dispersion regime via DSPX proxy (Idea3)
#     7. Position recycling on time-stops (Idea7)
#
# NEW IDEAS:
#
#   Idea1  Overnight Return Decomposition
#          For each MR candidate, compute what fraction of the 4-day decline
#          happened overnight (close→open) vs intraday (open→close).
#          overnight_frac = sum(abs(open_t - close_{t-1})) / total_decline
#          HIGH overnight fraction = noise-driven = better MR candidate.
#          Used as a RANKING BOOST in composite score: candidates with
#          overnight_frac > 0.5 get their composite score scaled down by
#          OVERNIGHT_BOOST_MULT (lower score = better rank = entered first).
#          Source: QuantReturns CO-OC research, SSRN day/night decomposition.
#
#   Idea2  Salience-Adjusted Re-ranking (Sector-Relative Return)
#          sector_relative_return = stock_5d_return - sector_ETF_5d_return
#          Candidates with strongly negative sector_relative (underperforming
#          peers by > SALIENCE_THRESHOLD) are salient, idiosyncratic moves.
#          These revert fastest (Chen, Wang, Yu SSRN 2023).
#          Used as ranking component: add abs(sector_rel_return) to composite
#          score denominator so idiosyncratic underperformers rank higher.
#
#   Idea3  Dispersion Regime Proxy
#          Approximate market dispersion via VVIX/VIX ratio (CBOE volatility
#          of VIX / VIX itself). High VVIX/VIX = market expects idiosyncratic
#          vol > index vol = high dispersion = MR-friendly regime.
#          Low VVIX/VIX = stocks moving together = bad MR regime.
#          Used as portfolio-level sizing scalar:
#          scalar = clip(VVIX/VIX / DISPERSION_NEUTRAL, 0.5, 1.2)
#          Downloads ^VVIX from yfinance (available from 2007).
#
#   Idea4  Return Skewness Filter
#          For each candidate, compute scipy.stats.skew of 20-day returns.
#          Negatively skewed = one large down day + small moves = noise spike.
#          Positively skewed or symmetric = gradual decline = potential trend.
#          skew_score = max(0, -skew_20d)  [positive when skew is negative]
#          Used as ranking component added to composite score denominator.
#          Source: Swiss Finance Institute 2024 "Smoothing Out Momentum."
#
#   Idea5  Turnover-Adjusted Re-ranking
#          Low volume during decline = liquidity gap = noise-driven = good MR.
#          High volume during decline = real sellers = informed = bad MR.
#          turnover_ratio = avg_vol_last_4d / vol_ma_252d
#          Low turnover ratio (<0.8) boosts rank; high (>1.5) penalises.
#          turnover_score = max(0, 1.0 - turnover_ratio)  [0 to ~0.5]
#          Source: Medhat & Schmeling RFS 2021 (high-turnover = momentum).
#
#   Idea6  Cross-Asset Correlation Regime Scaling
#          Compute rolling 20-day pairwise correlation of open positions.
#          When book correlation is high (>0.4), stocks are moving together
#          and MR is more likely to fail. Scale new position sizes down.
#          scalar = max(CORR_FLOOR, 1 - CORR_SENSITIVITY * (corr - CORR_TARGET))
#          Targets 2022 directly: high-correlation grinding bear = smaller bets.
#          Uses only data already in memory (position returns from price_data).
#
#   Idea7  Time-Stop Recycling
#          When a time-stop fires at a loss, check if the stock has a FRESH
#          signal the next day (new 4-day streak, RSI < 20). If yes, re-enter
#          immediately at half size with 5-day hold, 1.5% target, overriding
#          the normal 5-day cooldown. The second bounce attempt after a 12+
#          day decline is a distinct setup with exhausted sellers.
#
# COMBINATIONS:
#   Each idea standalone + combined with I3 (put spread).
#   Best-of combos: Idea1+2, Idea1+4+5, Idea2+4+5, full signal combo,
#   everything+I3.
#
# TOTAL: 2 baselines + 7 individual + 7 w/I3 + 8 combos = 24 tests
#
# OUTPUT: results_ideas_v4/ with comparison.json
# Does NOT modify backtest_nmr_lib.py.

import json
import warnings
import datetime
from pathlib import Path
from scipy import stats as scipy_stats

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
    TICKER_TO_SECTOR, SECTOR_ETFS, INITIAL_CAPITAL, START_DATE, END_DATE,
    MAX_POSITIONS, POSITION_SIZE, POSITION_SIZE_HIGH,
    MA_WINDOW, VOL_MA_PERIOD, ATR_PERIOD,
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

OUTPUT_DIR = Path("results_ideas_v4")
OUTPUT_DIR.mkdir(exist_ok=True)

# =============================================================================
# Idea-specific parameters
# =============================================================================

# Idea 1: Overnight decomposition
OVERNIGHT_BOOST_MULT  = 0.70   # scale score down by 30% for high-overnight stocks
OVERNIGHT_FRAC_THRESH = 0.50   # fraction of decline that must be overnight to qualify

# Idea 2: Salience / sector-relative
SALIENCE_THRESHOLD    = 0.03   # stock must underperform sector by >3% over 5d
SALIENCE_WEIGHT       = 2.0    # weight of salience component in composite score

# Idea 3: Dispersion regime (VVIX/VIX proxy)
DISPERSION_NEUTRAL    = 5.0    # VVIX/VIX ratio at which scale = 1.0 (~typical)
DISPERSION_FLOOR      = 0.50   # minimum scale factor in low-dispersion regime
DISPERSION_CAP        = 1.10   # maximum scale factor (slight boost in high-disp)

# Idea 4: Return skewness
SKEW_LOOKBACK         = 20     # days of returns for skewness calculation
SKEW_WEIGHT           = 1.5    # weight of skewness component in composite score

# Idea 5: Turnover-adjusted ranking
TURNOVER_LOOKBACK     = 252    # long-run volume average window
TURNOVER_STREAK       = 4      # days of streak volume to average
TURNOVER_WEIGHT       = 1.5    # weight of turnover component in composite score

# Idea 6: Cross-asset correlation regime
CORR_LOOKBACK         = 20     # days of returns for correlation computation
CORR_TARGET           = 0.20   # neutral correlation level
CORR_FLOOR            = 0.70   # minimum scale when correlation spikes
CORR_SENSITIVITY      = 0.5    # aggressiveness of scaling

# Idea 7: Time-stop recycling
RECYCLE_SIZE_FRAC     = 0.50   # half-size for recycled entries
RECYCLE_HOLD_DAYS     = 5      # shorter hold
RECYCLE_TARGET        = 0.015  # tighter profit target

# Idea 3 put spread (unchanged from V2/V3)
PUT_SPREAD_LOWER_OTM      = 0.05
PUT_SPREAD_UPPER_OTM      = 0.15
PUT_SPREAD_QUARTERLY_COST = 0.015
PUT_SPREAD_RENEW_DAYS     = 63

# =============================================================================
# Test matrix
# =============================================================================
TESTS = [
    # ── Baselines ──────────────────────────────────────────────────────────────
    {"name": "Baseline_V35",         "puts": False, "i1": False, "i2": False, "i3d": False, "i4": False, "i5": False, "i6": False, "i7": False},
    {"name": "Baseline_V35_I3",      "puts": True,  "i1": False, "i2": False, "i3d": False, "i4": False, "i5": False, "i6": False, "i7": False},
    # ── Individual ideas (no puts) ─────────────────────────────────────────────
    {"name": "Idea1_Overnight",      "puts": False, "i1": True,  "i2": False, "i3d": False, "i4": False, "i5": False, "i6": False, "i7": False},
    {"name": "Idea2_Salience",       "puts": False, "i1": False, "i2": True,  "i3d": False, "i4": False, "i5": False, "i6": False, "i7": False},
    {"name": "Idea3_Dispersion",     "puts": False, "i1": False, "i2": False, "i3d": True,  "i4": False, "i5": False, "i6": False, "i7": False},
    {"name": "Idea4_Skewness",       "puts": False, "i1": False, "i2": False, "i3d": False, "i4": True,  "i5": False, "i6": False, "i7": False},
    {"name": "Idea5_Turnover",       "puts": False, "i1": False, "i2": False, "i3d": False, "i4": False, "i5": True,  "i6": False, "i7": False},
    {"name": "Idea6_CorrRegime",     "puts": False, "i1": False, "i2": False, "i3d": False, "i4": False, "i5": False, "i6": True,  "i7": False},
    {"name": "Idea7_Recycle",        "puts": False, "i1": False, "i2": False, "i3d": False, "i4": False, "i5": False, "i6": False, "i7": True},
    # ── Each + I3 ──────────────────────────────────────────────────────────────
    {"name": "Idea1+I3",             "puts": True,  "i1": True,  "i2": False, "i3d": False, "i4": False, "i5": False, "i6": False, "i7": False},
    {"name": "Idea2+I3",             "puts": True,  "i1": False, "i2": True,  "i3d": False, "i4": False, "i5": False, "i6": False, "i7": False},
    {"name": "Idea3+I3",             "puts": True,  "i1": False, "i2": False, "i3d": True,  "i4": False, "i5": False, "i6": False, "i7": False},
    {"name": "Idea4+I3",             "puts": True,  "i1": False, "i2": False, "i3d": False, "i4": True,  "i5": False, "i6": False, "i7": False},
    {"name": "Idea5+I3",             "puts": True,  "i1": False, "i2": False, "i3d": False, "i4": False, "i5": True,  "i6": False, "i7": False},
    {"name": "Idea6+I3",             "puts": True,  "i1": False, "i2": False, "i3d": False, "i4": False, "i5": False, "i6": True,  "i7": False},
    {"name": "Idea7+I3",             "puts": True,  "i1": False, "i2": False, "i3d": False, "i4": False, "i5": False, "i6": False, "i7": True},
    # ── Signal quality combos ──────────────────────────────────────────────────
    {"name": "Idea1+2",              "puts": False, "i1": True,  "i2": True,  "i3d": False, "i4": False, "i5": False, "i6": False, "i7": False},
    {"name": "Idea1+4+5",            "puts": False, "i1": True,  "i2": False, "i3d": False, "i4": True,  "i5": True,  "i6": False, "i7": False},
    {"name": "Idea2+4+5",            "puts": False, "i1": False, "i2": True,  "i3d": False, "i4": True,  "i5": True,  "i6": False, "i7": False},
    {"name": "SignalCombo",          "puts": False, "i1": True,  "i2": True,  "i3d": False, "i4": True,  "i5": True,  "i6": False, "i7": False},
    {"name": "SignalCombo+I3",       "puts": True,  "i1": True,  "i2": True,  "i3d": False, "i4": True,  "i5": True,  "i6": False, "i7": False},
    {"name": "SignalCombo+I3+I6",    "puts": True,  "i1": True,  "i2": True,  "i3d": False, "i4": True,  "i5": True,  "i6": True,  "i7": False},
    {"name": "BestGuess",            "puts": True,  "i1": True,  "i2": True,  "i3d": False, "i4": True,  "i5": True,  "i6": True,  "i7": True},
    {"name": "Kitchen_Sink",         "puts": True,  "i1": True,  "i2": True,  "i3d": True,  "i4": True,  "i5": True,  "i6": True,  "i7": True},
]

# =============================================================================
# Reference data downloads
# =============================================================================
def download_vvix() -> pd.Series:
    """Download ^VVIX (volatility of VIX). Available from ~2007."""
    try:
        raw = yf.download("^VVIX", start=START_DATE, end=END_DATE,
                          auto_adjust=True, progress=False)
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)
        s = raw["Close"].squeeze()
        print(f"[VVIX] Downloaded {len(s)} rows")
        return s
    except Exception as e:
        print(f"[VVIX] Download failed: {e} -- Idea3 dispersion will use scale=1.0")
        return pd.Series(dtype=float)


# =============================================================================
# Pre-computation: augment signal DataFrames with new features
# =============================================================================
def augment_signals(signals: dict, price_data: dict, sector_data: dict) -> dict:
    """
    Add overnight_frac, sector_rel_5d, skew_20d, turnover_ratio to each
    signal DataFrame. Done once at startup, reused across all tests.
    """
    print("[Augment] Computing signal quality features (overnight, salience, skew, turnover)...")
    augmented = {}

    # Build sector ETF return series for Idea 2
    sector_returns = {}
    for etf, df in sector_data.items():
        try:
            c = df["Close"].squeeze()
            sector_returns[etf] = c.pct_change(5)
        except Exception:
            pass

    for tkr, df in signals.items():
        try:
            raw = price_data[tkr]
            close = raw["Close"].squeeze()
            open_ = raw["Open"].squeeze()
            vol   = raw["Volume"].squeeze()
            df    = df.copy()

            n = len(df)

            # ── Idea 1: Overnight fraction of decline ──────────────────────
            overnight_fracs = np.full(n, 0.5)
            for i in range(MIN_CONSEC_DOWN, n):
                consec = int(df["consec_down"].iloc[i])
                if consec < MIN_CONSEC_DOWN:
                    overnight_fracs[i] = 0.5
                    continue
                k = min(consec, i)
                overnight_moves = 0.0
                total_decline   = 0.0
                for j in range(1, k + 1):
                    idx = i - k + j
                    if idx <= 0:
                        continue
                    try:
                        day_open  = float(open_.iloc[idx])
                        prev_close= float(close.iloc[idx - 1])
                        day_close = float(close.iloc[idx])
                        overnight = abs(day_open - prev_close)
                        intraday  = abs(day_close - day_open)
                        overnight_moves += overnight
                        total_decline   += overnight + intraday
                    except Exception:
                        pass
                overnight_fracs[i] = (overnight_moves / total_decline
                                      if total_decline > 0 else 0.5)
            df["overnight_frac"] = overnight_fracs

            # ── Idea 2: Sector-relative 5-day return ──────────────────────
            etf = TICKER_TO_SECTOR.get(tkr)
            if etf and etf in sector_returns:
                stock_ret5 = close.pct_change(5)
                sect_ret5  = sector_returns[etf].reindex(df.index)
                df["sector_rel_5d"] = (stock_ret5 - sect_ret5).reindex(df.index).fillna(0.0)
            else:
                df["sector_rel_5d"] = 0.0

            # ── Idea 4: 20-day return skewness ────────────────────────────
            rets = close.pct_change().reindex(df.index)
            skew_vals = np.zeros(n)
            for i in range(SKEW_LOOKBACK, n):
                window = rets.iloc[i - SKEW_LOOKBACK: i].dropna()
                if len(window) >= 10:
                    try:
                        skew_vals[i] = float(scipy_stats.skew(window))
                    except Exception:
                        skew_vals[i] = 0.0
            df["skew_20d"] = skew_vals

            # ── Idea 5: Volume turnover ratio ─────────────────────────────
            vol_252 = vol.rolling(TURNOVER_LOOKBACK).mean()
            vol_4d  = vol.rolling(TURNOVER_STREAK).mean()
            turnover = (vol_4d / vol_252.replace(0, np.nan)).fillna(1.0)
            df["turnover_ratio"] = turnover.reindex(df.index).fillna(1.0)

            augmented[tkr] = df

        except Exception:
            augmented[tkr] = signals[tkr]

    print(f"[Augment] Done: {len(augmented)} tickers augmented")
    return augmented


# =============================================================================
# Put spread helpers (unchanged from V2/V3)
# =============================================================================
def compute_put_spread_intrinsic_pct(spy_ref: float, spy_low: float) -> float:
    lower_strike   = spy_ref * (1 - PUT_SPREAD_LOWER_OTM)
    spread_width   = PUT_SPREAD_UPPER_OTM - PUT_SPREAD_LOWER_OTM
    if spy_low >= lower_strike:
        return 0.0
    payout = (spy_ref - spy_low) / spy_ref - PUT_SPREAD_LOWER_OTM
    return float(np.clip(payout, 0.0, spread_width))


# =============================================================================
# Idea 3: Dispersion regime scale
# =============================================================================
def get_dispersion_scale(today, vix_close: float, vvix_series: pd.Series) -> float:
    if vvix_series.empty or today not in vvix_series.index:
        return 1.0
    vvix = float(vvix_series.loc[today])
    if vvix <= 0 or vix_close <= 0:
        return 1.0
    ratio = vvix / vix_close
    # ratio > DISPERSION_NEUTRAL = high dispersion = good for MR = scale up slightly
    # ratio < DISPERSION_NEUTRAL = low dispersion = bad for MR = scale down
    scale = ratio / DISPERSION_NEUTRAL
    return float(np.clip(scale, DISPERSION_FLOOR, DISPERSION_CAP))


# =============================================================================
# Idea 6: Cross-asset correlation regime
# =============================================================================
def compute_book_correlation(open_positions: dict, price_data: dict,
                              today, lookback: int = CORR_LOOKBACK) -> float:
    """
    Compute average pairwise return correlation of all open positions
    over the last `lookback` trading days. Returns 0.0 if < 3 positions.
    """
    tickers = list(open_positions.keys())
    if len(tickers) < 3:
        return CORR_TARGET  # not enough positions to measure

    ret_matrix = []
    for tkr in tickers:
        df = price_data.get(tkr)
        if df is None or today not in df.index:
            continue
        loc = df.index.get_loc(today)
        if loc < lookback:
            continue
        window_close = df["Close"].iloc[loc - lookback: loc + 1].squeeze()
        rets = window_close.pct_change().dropna()
        if len(rets) >= lookback - 2:
            ret_matrix.append(rets.values[-lookback:])

    if len(ret_matrix) < 3:
        return CORR_TARGET

    try:
        mat = np.array(ret_matrix)
        corr = np.corrcoef(mat)
        # Average of upper triangle (excluding diagonal)
        n = corr.shape[0]
        upper = corr[np.triu_indices(n, k=1)]
        return float(np.mean(upper))
    except Exception:
        return CORR_TARGET


def get_correlation_scale(book_corr: float) -> float:
    scale = 1.0 - CORR_SENSITIVITY * (book_corr - CORR_TARGET)
    return float(np.clip(scale, CORR_FLOOR, 1.0))


# =============================================================================
# Core backtest
# =============================================================================
def run_backtest_v4(price_data: dict, spy_df: pd.DataFrame, vix_df: pd.DataFrame,
                    sector_data: dict, earnings_map: dict,
                    vvix_series: pd.Series, augmented_signals: dict,
                    cfg: dict) -> pd.DataFrame:

    test_name = cfg["name"]
    use_puts  = cfg["puts"]
    use_i1    = cfg["i1"]   # overnight decomposition
    use_i2    = cfg["i2"]   # salience
    use_i3d   = cfg["i3d"]  # dispersion regime
    use_i4    = cfg["i4"]   # skewness
    use_i5    = cfg["i5"]   # turnover
    use_i6    = cfg["i6"]   # correlation regime
    use_i7    = cfg["i7"]   # time-stop recycling

    print(f"\n{'='*70}")
    print(f"[Test] {test_name}")
    print(f"  Puts={use_puts} I1={use_i1} I2={use_i2} I3d={use_i3d} "
          f"I4={use_i4} I5={use_i5} I6={use_i6} I7={use_i7}")
    print(f"{'='*70}")

    spy_regime = spy_df["spy_ok"].to_dict()
    spy_close  = spy_df["Close"].squeeze()
    try:
        vix_close_series = vix_df["Close"].squeeze()
    except Exception:
        vix_close_series = pd.Series(dtype=float)

    all_dates: set = set()
    for df in price_data.values():
        all_dates.update(df.index)
    trading_dates = sorted(all_dates)

    # Use augmented signals (have overnight_frac, sector_rel_5d, skew_20d, turnover_ratio)
    signals = augmented_signals

    # ── State ────────────────────────────────────────────────────────────────
    portfolio_value    = INITIAL_CAPITAL
    portfolio_peak     = None
    current_drawdown   = 0.0
    open_positions     = {}
    recycle_candidates = {}  # Idea 7: {tkr: day_of_timestop} for recycling check
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

        # Drawdown
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

        # VIX for dispersion scale
        vix_today = 20.0
        try:
            if today in vix_close_series.index:
                vix_today = float(vix_close_series.loc[today])
        except Exception:
            pass

        # Idea 3d: dispersion scale
        dispersion_scale = 1.0
        if use_i3d:
            dispersion_scale = get_dispersion_scale(today, vix_today, vvix_series)

        # Idea 6: correlation regime scale (compute once per day)
        corr_scale = 1.0
        if use_i6:
            book_corr  = compute_book_correlation(open_positions, price_data, today)
            corr_scale = get_correlation_scale(book_corr)

        # ── Put spread ───────────────────────────────────────────────────────
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
                            trades.append({
                                "ticker": "SPY_PUT_SPREAD", "entry_date": put_ref_date, "exit_date": today,
                                "entry_price": put_ref_price, "exit_price": put_min_spy,
                                "shares": 0, "commission": 0,
                                "pnl_usd": round(payout, 2),
                                "pnl_pct": round(payout_pct * 100, 4),
                                "days_held": put_days_since_renew, "exit_reason": "put_payout",
                                "tier": 0, "consec_down": 0, "portfolio_val": portfolio_value,
                            })

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
                    # Idea 7: flag for potential recycling tomorrow
                    if use_i7 and pnl < 0:
                        recycle_candidates[tkr] = today
                to_close.append(tkr)

        for tkr in to_close:
            del open_positions[tkr]

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

            # Idea 7: check if this is a recycle candidate (override cooldown)
            is_recycle = False
            if use_i7 and tkr in recycle_candidates:
                days_since_stop = (pd.Timestamp(today) - pd.Timestamp(recycle_candidates[tkr])).days
                if 1 <= days_since_stop <= 2:
                    is_recycle = True  # fresh signal within 2 days of time-stop

            if not is_recycle:
                if tkr in cooldown_map:
                    if (pd.Timestamp(today) - pd.Timestamp(cooldown_map[tkr])).days < REENTRY_COOLDOWN_DAYS:
                        continue

            if near_earnings(tkr, today, earnings_map):
                continue
            if not sector_ok(tkr, today, sector_data):
                continue
            if count_sector_positions(tkr, open_positions) >= MAX_SECTOR_POSITIONS:
                continue

            rsi2     = float(row["rsi2"])
            atr_pct  = float(row["atr_pct"])

            # Base composite score (same as V35)
            base_score = rsi2 / atr_pct if atr_pct > 0 else rsi2 * 1000

            # Enrich score denominator with signal quality dimensions
            # Lower score = better rank = entered first
            quality_denom = 1.0

            # Idea 1: overnight fraction boost
            if use_i1:
                overnight_frac = float(row.get("overnight_frac", 0.5))
                if overnight_frac > OVERNIGHT_FRAC_THRESH:
                    quality_denom *= (1.0 / OVERNIGHT_BOOST_MULT)  # boosts rank

            # Idea 2: salience (idiosyncratic underperformance vs sector)
            if use_i2:
                sector_rel = float(row.get("sector_rel_5d", 0.0))
                if sector_rel < -SALIENCE_THRESHOLD:
                    # More negative = more salient = better -- add positive component
                    salience_component = abs(sector_rel) * SALIENCE_WEIGHT
                    quality_denom *= (1.0 + salience_component)  # boosts rank

            # Idea 4: negative skewness = better candidate
            if use_i4:
                skew = float(row.get("skew_20d", 0.0))
                skew_score = max(0.0, -skew) * SKEW_WEIGHT
                quality_denom *= (1.0 + skew_score)

            # Idea 5: low turnover = noise-driven = better
            if use_i5:
                turnover = float(row.get("turnover_ratio", 1.0))
                turnover_score = max(0.0, 1.0 - turnover) * TURNOVER_WEIGHT
                quality_denom *= (1.0 + turnover_score)

            score = base_score / quality_denom

            candidates.append((score, tkr, int(row["consec_down"]), rsi2, is_recycle))

        candidates.sort(key=lambda x: x[0])
        n_candidates = len(candidates)
        top_n = max(1, int(n_candidates * TOP_SIGNAL_PCT))

        for rank, (score, tkr, consec_val, rsi_val, is_recycle) in enumerate(candidates):
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
            prev_close = float(tkr_df.iloc[today_idx]["Close"])
            gap_pct    = (entry_price - prev_close) / prev_close

            if gap_pct < GAP_DOWN_MAX or gap_pct > GAP_UP_MAX:
                continue

            # Idea 7: recycled entries get special sizing
            if is_recycle:
                shares     = (portfolio_value * POSITION_SIZE * RECYCLE_SIZE_FRAC) / entry_price
                entry_comm = calc_commission(shares, entry_price)
                open_positions[tkr] = {
                    "entry_date":           tkr_df.index[today_idx + 1],
                    "entry_price":          entry_price,
                    "shares":               shares,
                    "shares_remaining":     shares,
                    "rsi2_at_entry":        rsi_val,
                    "consec_down_at_entry": consec_val,
                    "profit_target":        RECYCLE_TARGET,
                    "hold_days":            RECYCLE_HOLD_DAYS,
                    "partial_enabled":      False,
                    "partial_frac":         0.0,
                    "partial_trigger":      RECYCLE_TARGET,
                    "partial_done":         False,
                    "tier":                 -1,  # recycle tier
                    "entry_commission":     entry_comm,
                }
                del recycle_candidates[tkr]
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

            # Idea 3d: dispersion scale
            if use_i3d:
                pos_size = pos_size * dispersion_scale

            # Idea 6: correlation regime scale
            if use_i6:
                pos_size = pos_size * corr_scale

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
    synthetic = {"SPY_PUT_SPREAD"}
    mr_trades = trades_df[~trades_df["ticker"].isin(synthetic)].copy()
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
        "non_mr_pnl": metrics.get("note_non_mr_pnl", 0),
    }


def print_comparison(summaries: list):
    b35  = next((s for s in summaries if s["test"] == "Baseline_V35"), None)
    bi3  = next((s for s in summaries if s["test"] == "Baseline_V35_I3"), None)

    print("\n" + "=" * 120)
    print(" IDEAS V4 -- COMPARISON TABLE")
    if b35:
        print(f" Baseline V35:    CAGR {b35['cagr']:.2f}% | MaxDD {b35['max_dd']:.2f}% | "
              f"Sharpe {b35['sharpe']:.2f} | Equity ${b35['final_eq']:,.0f}")
    if bi3:
        print(f" Baseline V35+I3: CAGR {bi3['cagr']:.2f}% | MaxDD {bi3['max_dd']:.2f}% | "
              f"Sharpe {bi3['sharpe']:.2f} | Equity ${bi3['final_eq']:,.0f}")
    print("=" * 120)
    hdr = (f"{'Test':<24} {'CAGR%':>7} {'MaxDD%':>8} {'Sharpe':>7} {'PF':>6} "
           f"{'FinalEq':>13} {'WR%':>6} {'Tr/Yr':>7} {'NonMR P&L':>12}")
    print(hdr)
    print("-" * 120)

    for s in summaries:
        marker = ""
        if bi3 and s["test"] not in ("Baseline_V35", "Baseline_V35_I3"):
            dd_better  = s["max_dd"] - bi3["max_dd"]
            eq_better  = s["final_eq"] - bi3["final_eq"]
            cagr_delta = s["cagr"] - bi3["cagr"]
            if dd_better > 2 and cagr_delta > -2:
                marker = " ★"
            elif dd_better > 5 or eq_better > 200_000:
                marker = " ◆"
            if eq_better > 500_000 and cagr_delta > 0:
                marker = " ★★"  # both equity AND better DD or CAGR

        print(f"{s['test']:<24} {s['cagr']:>7.2f} {s['max_dd']:>8.2f} {s['sharpe']:>7.2f} "
              f"{s['pf']:>6.2f} {s['final_eq']:>13,.0f} {s['wr']:>6.2f} {s['trades_yr']:>7.0f} "
              f"{s['non_mr_pnl']:>12,.0f}{marker}")

    print("=" * 120)
    print(f"\n  ★★ = Higher equity AND better risk vs V35+I3 -- adopt immediately")
    print(f"  ★  = Better MaxDD (>2pp) without major CAGR cost (<2pp)")
    print(f"  ◆  = Significant improvement on one metric")
    print()

    best_dd  = min(summaries, key=lambda x: x["max_dd"])
    best_cagr= max(summaries, key=lambda x: x["cagr"])
    best_sh  = max(summaries, key=lambda x: x["sharpe"])
    best_eq  = max(summaries, key=lambda x: x["final_eq"])
    print(f"  Lowest MaxDD  : {best_dd['test']}  ({best_dd['max_dd']:.2f}%)")
    print(f"  Highest CAGR  : {best_cagr['test']}  ({best_cagr['cagr']:.2f}%)")
    print(f"  Highest Sharpe: {best_sh['test']}  ({best_sh['sharpe']:.2f})")
    print(f"  Highest Equity: {best_eq['test']}  (${best_eq['final_eq']:,.0f})")
    print("=" * 120)


# =============================================================================
# Main
# =============================================================================
def main():
    print("\n" + "=" * 70)
    print(" NAIVE MR BACKTEST -- IDEAS V4")
    print(" 7 signal quality ideas: Overnight | Salience | Dispersion |")
    print("   Skewness | Turnover | Correlation Regime | Time-Stop Recycling")
    print(" Baseline: V35+I3 (put spread @ 1.5%/qtr)")
    print("=" * 70)

    print("\n[Setup] Loading universe and data...")
    universe     = get_universe()
    price_data   = download_prices(universe)
    spy_df, vix_df, sector_data = download_reference_data()
    earnings_map = build_earnings_dates(list(price_data.keys()))

    # Download VVIX for Idea 3 dispersion
    vvix_series = download_vvix()

    # Generate base signals
    print("[Setup] Generating and augmenting signals...")
    min_bars = MA_WINDOW + VOL_MA_PERIOD + ATR_PERIOD + MIN_CONSEC_DOWN + 5
    base_signals = {}
    for tkr, df in price_data.items():
        if len(df) > min_bars:
            base_signals[tkr] = generate_signals(df)

    # Augment with all signal quality features (done once, reused across tests)
    augmented_signals = augment_signals(base_signals, price_data, sector_data)

    summaries = []

    for cfg in TESTS:
        test_name = cfg["name"]
        try:
            trades_df = run_backtest_v4(
                price_data, spy_df, vix_df, sector_data, earnings_map,
                vvix_series, augmented_signals, cfg
            )
            if trades_df.empty:
                print(f"[{test_name}] WARNING: No trades generated.")
                continue

            synthetic = {"SPY_PUT_SPREAD"}
            mr_trades = trades_df[~trades_df["ticker"].isin(synthetic)].copy()

            if mr_trades.empty:
                print(f"[{test_name}] No MR trades.")
                continue

            metrics, eq_df = compute_metrics(mr_trades)

            non_mr_pnl = trades_df[
                trades_df["ticker"].isin(synthetic)
            ]["pnl_usd"].sum()

            metrics["final_equity"]    = round(metrics["final_equity"] + non_mr_pnl, 2)
            metrics["version"]         = test_name
            metrics["note_non_mr_pnl"] = round(non_mr_pnl, 2)

            save_test_outputs(test_name, trades_df, metrics, eq_df)
            summaries.append(extract_summary(test_name, metrics))

            print(f"[{test_name}] CAGR: {metrics['cagr_pct']:.2f}% | "
                  f"MaxDD: {metrics['max_drawdown_pct']:.2f}% | "
                  f"Sharpe: {metrics['sharpe_ratio']:.2f} | "
                  f"FinalEq: ${metrics['final_equity']:,.0f} | "
                  f"NonMR: ${non_mr_pnl:,.0f}")

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
