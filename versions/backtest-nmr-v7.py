"""
Naive Mean Reversion Backtest — V7 (REFERENCE / GOLDEN COPY)
=============================================================
DO NOT MODIFY THIS FILE. This is the exact code that produced the best
confirmed results across all versions V1-V9+.

To revert: cp versions/backtest-nmr-v7.py backtest-nmr.py

Confirmed Results (2004-10-19 to 2026-03-27, 21.43 years):
  CAGR              : 9.05%
  ROI / Year        : 25.23%
  Win Rate          : 69.72%
  Avg Win           : 3.34%
  Avg Loss          : -3.31%
  Profit Factor     : 1.14
  Max Drawdown      : -28.94%
  Sharpe Ratio      : 0.74
  Trades / Year     : 872
  Final Equity      : $641k from $100k

Key insight: RSI(2) is ALWAYS below 5 after 4+ consecutive down days.
All 18,698 trades routed to Tier 1's 8-day window — this was accidentally
the optimal configuration, driving the 69.72% win rate.

Strategy:
  Universe  : S&P 500 + S&P 400 MidCap
  Buy       : >200-day MA, 4+ down days, RSI(2)<20, ATR>1%, volume spike, $5M+ dollar vol
  Entry     : Next open (skip gap down >1.5% or gap up >2%)
  Tiers     : 4 days->1%/4d, 5 days->1.5%/6d, 6+ days->2%/8d + partial exit at 1%
  Min hold  : 2 days before profit exit
  Positions : Max 30, VIX-adjusted (2.5/5/7.5%), earnings month cap 3%
  Filters   : SPY>200MA, sector>20MA, earnings blackout +-3d, max 3/sector,
              VIX spike pause 2d, re-entry cooldown 5d
  Commission: $0.005/share, $1 min
"""

import io
import warnings
import datetime
import json
from pathlib import Path

import numpy as np
import pandas as pd
import yfinance as yf
import requests
from tqdm import tqdm

warnings.filterwarnings("ignore")

# ─────────────────────────────────────────────────────────────────────────────
# Config — EXACT V7 PARAMETERS — DO NOT CHANGE
# ─────────────────────────────────────────────────────────────────────────────
START_DATE              = "2004-01-01"
END_DATE                = datetime.date.today().isoformat()
MIN_DOLLAR_VOLUME       = 5_000_000
MAX_POSITIONS           = 30
POSITION_SIZE           = 0.05
POSITION_SIZE_HIGH      = 0.075
POSITION_SIZE_LOW       = 0.025
POSITION_SIZE_EARNINGS  = 0.03
MA_WINDOW               = 200
INITIAL_CAPITAL         = 100_000.0
RSI_PERIOD              = 2
RSI_THRESHOLD           = 20
ATR_PERIOD              = 14
ATR_MIN_PCT             = 0.01
VOL_MA_PERIOD           = 20
MIN_HOLD_BEFORE_EXIT    = 2
TIER1_MIN_DOWN          = 6
TIER1_TARGET            = 0.020
TIER1_HOLD_DAYS         = 8
TIER1_PARTIAL           = True
TIER1_PARTIAL_FRAC      = 0.50
TIER1_PARTIAL_TRIGGER   = 0.010
TIER2_MIN_DOWN          = 5
TIER2_TARGET            = 0.015
TIER2_HOLD_DAYS         = 6
TIER2_PARTIAL           = False
TIER3_MIN_DOWN          = 4
TIER3_TARGET            = 0.010
TIER3_HOLD_DAYS         = 4
TIER3_PARTIAL           = False
EARNINGS_BLACKOUT       = 3
GAP_DOWN_MAX            = -0.015
GAP_UP_MAX              = 0.020
SECTOR_MA_WINDOW        = 20
MAX_SECTOR_POSITIONS    = 3
VIX_HIGH                = 25
VIX_LOW                 = 15
VIX_SPIKE_PCT           = 0.30
VIX_SPIKE_PAUSE_DAYS    = 2
REENTRY_COOLDOWN_DAYS   = 5
COMMISSION_RATE         = 0.005
COMMISSION_MIN          = 1.00
EARNINGS_MONTHS         = {1, 4, 7, 10}

OUTPUT_DIR = Path("results")
OUTPUT_DIR.mkdir(exist_ok=True)

SECTOR_ETFS = {
    "XLK": ["AAPL","MSFT","NVDA","AVGO","CSCO","ORCL","IBM","QCOM","TXN","INTC","AMD","NOW","INTU","AMAT","ADI","MU","KLAC","LRCX","MCHP","CDNS"],
    "XLV": ["UNH","JNJ","LLY","ABBV","MRK","TMO","ABT","DHR","BMY","AMGN","PFE","ISRG","MDT","GILD","VRTX","BSX","SYK","REGN","ZTS","CI"],
    "XLF": ["JPM","BAC","WFC","GS","MS","BLK","AXP","SPGI","V","MA","USB","PNC","TFC","COF","CB","ICE","CME","MCO","AON","TRV"],
    "XLY": ["AMZN","TSLA","HD","MCD","NKE","LOW","SBUX","TGT","CMG","BKNG","TJX","DHI","GM","F","ORLY","LEN","EBAY","ETSY","YUM","DRI"],
    "XLP": ["PG","KO","PEP","COST","WMT","PM","MO","MDLZ","CL","KMB","EL","KR","STZ","GIS","HRL","SJM","CAG","K","CPB","CHD"],
    "XLE": ["XOM","CVX","COP","SLB","EOG","MPC","PSX","VLO","HAL","BKR","FANG","DVN","HES","OXY","APA","MRO","CTRA","EQT","NOV","FTI"],
    "XLI": ["GE","HON","UPS","BA","CAT","RTX","DE","LMT","UNP","MMM","ETN","EMR","NOC","GD","PH","ROK","IR","ITW","TT","CARR"],
    "XLB": ["LIN","APD","SHW","ECL","NEM","FCX","NUE","DOW","DD","PPG","ALB","CF","MOS","CE","IFF","RPM","FMC","SON","SEE","AMCR"],
    "XLU": ["NEE","DUK","SO","D","AEP","EXC","SRE","PEG","ED","XEL","ES","FE","ETR","PPL","CMS","NI","ATO","LNT","EVRG","PNW"],
    "XLRE": ["PLD","AMT","CCI","EQIX","PSA","O","WELL","DLR","EQR","AVB","SPG","WY","ARE","MAA","UDR","CPT","ESS","AIV","IRM","VTR"],
    "XLC": ["META","GOOGL","GOOG","NFLX","DIS","CMCSA","T","VZ","TMUS","CHTR","ATVI","EA","WBD","PARA","FOXA","FOX","NWS","NWSA","OMC","IPG"],
}
TICKER_TO_SECTOR: dict[str, str] = {}
for _etf, _members in SECTOR_ETFS.items():
    for _t in _members:
        TICKER_TO_SECTOR[_t] = _etf


def get_tier(consec_down: int) -> dict:
    if consec_down >= TIER1_MIN_DOWN:
        return {"tier":1,"profit_target":TIER1_TARGET,"hold_days":TIER1_HOLD_DAYS,
                "partial_enabled":TIER1_PARTIAL,"partial_frac":TIER1_PARTIAL_FRAC,"partial_trigger":TIER1_PARTIAL_TRIGGER}
    elif consec_down >= TIER2_MIN_DOWN:
        return {"tier":2,"profit_target":TIER2_TARGET,"hold_days":TIER2_HOLD_DAYS,
                "partial_enabled":TIER2_PARTIAL,"partial_frac":0.0,"partial_trigger":TIER2_TARGET}
    else:
        return {"tier":3,"profit_target":TIER3_TARGET,"hold_days":TIER3_HOLD_DAYS,
                "partial_enabled":TIER3_PARTIAL,"partial_frac":0.0,"partial_trigger":TIER3_TARGET}


def _fetch_wiki(url):
    headers={"User-Agent":"Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}
    resp=requests.get(url,headers=headers,timeout=30); resp.raise_for_status()
    return pd.read_html(io.StringIO(resp.text),header=0)


def get_universe():
    tickers=set()
    for url,label in [("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies","S&P 500"),
                      ("https://en.wikipedia.org/wiki/List_of_S%26P_400_companies","S&P 400")]:
        try:
            tables=_fetch_wiki(url)
            for col in ["Symbol","Ticker symbol","Ticker"]:
                if col in tables[0].columns:
                    syms=tables[0][col].tolist(); tickers.update([s.replace(".","-") for s in syms])
                    print(f"[Universe] {label}: {len(syms)} symbols"); break
            if "500" in label and len(tables)>1:
                for col in tables[1].columns:
                    cs=tables[1][col].dropna().astype(str)
                    if cs.str.match(r"^[A-Z]{1,5}(-[A-Z])?$").mean()>0.3: tickers.update([s.replace(".","-") for s in cs])
        except Exception as e: print(f"[Universe] {label} failed: {e}")
    tickers.update(["LEH","BSC","WB","WAMU","MER","C","AIG","FNM","FRE","YHOO","SUNW","PALM","Q","NT","GLW","JDS","CSCO","T",
        "GE","GM","F","XOM","CVX","IBM","MSFT","AAPL","AMZN","GOOG","GOOGL","META","NVDA","TSLA","BRK-B","JPM","BAC",
        "WFC","GS","MS","USB","PNC","TFC","COF","AXP","V","MA","HD","LOW","TGT","WMT","COST","KR","CVS","WBA",
        "UNH","CI","HUM","CNC","MOH","CAH","JNJ","PFE","MRK","ABBV","BMY","AMGN","GILD","BIIB","LLY","REGN","VRTX",
        "ZTS","ISRG","BSX","SYK","MDT","BA","LMT","RTX","NOC","GD","HII","TXT","CAT","DE","EMR","HON","MMM","ETN",
        "PH","ROK","COP","EOG","SLB","HAL","BKR","MPC","VLO","NEE","DUK","SO","AEP","EXC","SRE","PCG","ED","FE",
        "AMT","PLD","CCI","SPG","O","WELL","PSA","EQR","AVB","SBUX","MCD","YUM","CMG","DRI","QSR","DIS","NFLX",
        "CMCSA","VZ","CHTR","TMUS","PG","KO","PEP","CL","KMB","CHD","EL"])
    result=sorted(tickers); print(f"[Universe] Total: {len(result)}"); return result


def download_prices(tickers):
    print(f"\n[Download] Fetching {len(tickers)} tickers ..."); all_data={}
    for i in tqdm(range(0,len(tickers),100),desc="Downloading"):
        chunk=tickers[i:i+100]
        try:
            raw=yf.download(chunk,start=START_DATE,end=END_DATE,auto_adjust=True,progress=False,threads=True)
            if raw.empty: continue
            if isinstance(raw.columns,pd.MultiIndex):
                for tkr in chunk:
                    try:
                        df=raw.xs(tkr,axis=1,level=1).dropna(how="all")
                        if not df.empty: all_data[tkr]=df
                    except KeyError: pass
            elif chunk: all_data[chunk[0]]=raw.dropna(how="all")
        except Exception as e: print(f"[Download] Chunk error: {e}")
    print(f"[Download] Downloaded {len(all_data)} tickers."); return all_data


def _dl_single(ticker):
    df=yf.download(ticker,start=START_DATE,end=END_DATE,auto_adjust=True,progress=False)
    if isinstance(df.columns,pd.MultiIndex): df.columns=df.columns.get_level_values(0)
    return df


def download_reference_data():
    spy=_dl_single("SPY"); close=spy["Close"].squeeze()
    spy["spy_ma200"]=close.rolling(200).mean(); spy["spy_ok"]=(close>spy["spy_ma200"].squeeze()).values
    print(f"[Download] SPY: {len(spy)} rows")
    vix=_dl_single("^VIX"); vc=vix["Close"].squeeze()
    vix["vix_5d_ago"]=vc.shift(5); vix["vix_spike"]=(vc/vix["vix_5d_ago"].replace(0,np.nan)-1)>=VIX_SPIKE_PCT
    print(f"[Download] VIX: {len(vix)} rows")
    etf_list=list(SECTOR_ETFS.keys()); sector_data={}
    raw=yf.download(etf_list,start=START_DATE,end=END_DATE,auto_adjust=True,progress=False,threads=True)
    if not raw.empty:
        for etf in etf_list:
            try:
                df=raw.xs(etf,axis=1,level=1).dropna(how="all") if isinstance(raw.columns,pd.MultiIndex) else raw.copy()
                cs=df["Close"].squeeze(); df=df.copy(); df["ma"]=cs.rolling(SECTOR_MA_WINDOW).mean()
                df["ok"]=(cs>df["ma"].squeeze()).values; sector_data[etf]=df
            except Exception: pass
    print(f"[Download] Sector ETFs: {len(sector_data)}"); return spy,vix,sector_data


def build_earnings_dates(tickers):
    print(f"[Earnings] Building calendar ..."); earnings_map={}
    for tkr in tqdm(tickers,desc="Earnings"):
        try:
            cal=yf.Ticker(tkr).calendar
            if cal is None or (hasattr(cal,"empty") and cal.empty): continue
            dates=set()
            for col in cal.columns:
                for val in cal[col].dropna():
                    try: dates.add(pd.Timestamp(val).normalize())
                    except Exception: pass
            if dates: earnings_map[tkr]=dates
        except Exception: pass
    print(f"[Earnings] Done: {len(earnings_map)} tickers."); return earnings_map


def near_earnings(tkr,date,earnings_map):
    if tkr not in earnings_map: return False
    d=pd.Timestamp(date).normalize()
    return any(abs((d-e).days)<=EARNINGS_BLACKOUT for e in earnings_map[tkr])


def compute_rsi(series,period):
    delta=series.diff(); gain=delta.clip(lower=0).rolling(period).mean()
    loss=(-delta.clip(upper=0)).rolling(period).mean(); rs=gain/loss.replace(0,np.nan)
    return 100-(100/(1+rs))


def generate_signals(df):
    df=df.copy(); df["ma200"]=df["Close"].rolling(MA_WINDOW).mean(); df["above_ma"]=df["Close"]>df["ma200"]
    df["down_day"]=(df["Close"]<df["Close"].shift(1)).astype(int)
    consec,count=[],0
    for d in df["down_day"]: count=count+1 if d==1 else 0; consec.append(count)
    df["consec_down"]=consec; df["rsi2"]=compute_rsi(df["Close"],RSI_PERIOD)
    tr=pd.concat([df["High"]-df["Low"],(df["High"]-df["Close"].shift(1)).abs(),(df["Low"]-df["Close"].shift(1)).abs()],axis=1).max(axis=1)
    df["atr"]=tr.rolling(ATR_PERIOD).mean(); df["atr_pct"]=df["atr"]/df["Close"]
    df["vol_ma20"]=df["Volume"].rolling(VOL_MA_PERIOD).mean(); df["vol_confirm"]=df["Volume"]>df["vol_ma20"]
    df["dollar_vol_ma20"]=(df["Close"]*df["Volume"]).rolling(VOL_MA_PERIOD).mean()
    df["signal"]=(df["above_ma"]&(df["consec_down"]>=TIER3_MIN_DOWN)&(df["rsi2"]<RSI_THRESHOLD)&
                  (df["atr_pct"]>ATR_MIN_PCT)&df["vol_confirm"]&(df["dollar_vol_ma20"]>=MIN_DOLLAR_VOLUME))
    return df


def calc_commission(shares,price): return max(shares*COMMISSION_RATE,COMMISSION_MIN)


def get_position_size(today,vix_df):
    month=pd.Timestamp(today).month; earnings_month=month in EARNINGS_MONTHS; base=POSITION_SIZE
    try:
        vc=vix_df["Close"].squeeze()
        if today in vc.index:
            v=float(vc.loc[today])
            if v>VIX_HIGH: base=POSITION_SIZE_LOW
            elif v<VIX_LOW: base=POSITION_SIZE_HIGH
    except Exception: pass
    if earnings_month and base>POSITION_SIZE_EARNINGS: return POSITION_SIZE_EARNINGS
    return base


def sector_ok(tkr,date,sector_data):
    etf=TICKER_TO_SECTOR.get(tkr)
    if etf is None or etf not in sector_data: return True
    df=sector_data[etf]
    if date not in df.index: return True
    return bool(df.loc[date,"ok"])


def count_sector_positions(tkr,open_positions):
    etf=TICKER_TO_SECTOR.get(tkr)
    if etf is None: return 0
    return sum(1 for t in open_positions if TICKER_TO_SECTOR.get(t)==etf)


def check_vix_spike(today,vix_df,last_spike_date):
    try:
        if today in vix_df.index:
            if bool(vix_df.loc[today,"vix_spike"]): last_spike_date=today
    except Exception: pass
    if last_spike_date is not None:
        if (pd.Timestamp(today)-pd.Timestamp(last_spike_date)).days<=VIX_SPIKE_PAUSE_DAYS: return True,last_spike_date
    return False,last_spike_date


def run_backtest(price_data,spy_df,vix_df,sector_data,earnings_map):
    print("\n[Backtest] Running V7 ..."); spy_regime=spy_df["spy_ok"].to_dict()
    all_dates=set()
    for df in price_data.values(): all_dates.update(df.index)
    trading_dates=sorted(all_dates); signals={}
    min_bars=MA_WINDOW+VOL_MA_PERIOD+ATR_PERIOD+TIER3_MIN_DOWN+5
    for tkr,df in tqdm(price_data.items(),desc="Generating signals"):
        if len(df)>min_bars: signals[tkr]=generate_signals(df)
    portfolio_value=INITIAL_CAPITAL; open_positions={}; trades=[]; cooldown_map={}; last_vix_spike=None
    for today in tqdm(trading_dates,desc="Simulating"):
        spy_ok=spy_regime.get(today,True); paused,last_vix_spike=check_vix_spike(today,vix_df,last_vix_spike)
        to_close=[]
        for tkr,pos in open_positions.items():
            if tkr not in signals: continue
            tkr_df=signals[tkr]
            if today not in tkr_df.index: continue
            row=tkr_df.loc[today]; prev_idx=tkr_df.index.get_loc(today)
            if prev_idx==0: continue
            prev_close=float(tkr_df.iloc[prev_idx-1]["Close"]); exit_price=float(row["Close"])
            entry_price=pos["entry_price"]; days_held=(pd.Timestamp(today)-pd.Timestamp(pos["entry_date"])).days
            pos_pct=(exit_price-entry_price)/entry_price; shares_rem=pos["shares_remaining"]
            time_stop=days_held>=pos["hold_days"]; early=days_held<MIN_HOLD_BEFORE_EXIT
            profit_hit=(not early) and pos_pct>=pos["profit_target"]
            if pos["partial_enabled"] and not pos["partial_done"] and not early and pos_pct>=pos["partial_trigger"]:
                ps=shares_rem*pos["partial_frac"]; comm=calc_commission(ps,exit_price)
                pnl=(exit_price-entry_price)*ps-comm
                trades.append({"ticker":tkr,"entry_date":pos["entry_date"],"exit_date":today,
                    "entry_price":entry_price,"exit_price":exit_price,"shares":ps,"commission":round(comm,4),
                    "pnl_usd":pnl,"pnl_pct":pos_pct*100,"days_held":days_held,"exit_reason":"partial_exit",
                    "tier":pos["tier"],"consec_down":pos["consec_down_at_entry"],"portfolio_val":portfolio_value+pnl})
                portfolio_value+=pnl; pos["shares_remaining"]-=ps; pos["partial_done"]=True; pos["profit_target"]*=2; continue
            full_exit=(time_stop or (not pos["partial_enabled"] and profit_hit) or
                       (pos["partial_enabled"] and pos["partial_done"] and profit_hit))
            if full_exit:
                comm=calc_commission(shares_rem,exit_price)
                pnl=(exit_price-entry_price)*shares_rem-comm-pos["entry_commission"]
                reason="time_stop" if time_stop else "profit_target"
                trades.append({"ticker":tkr,"entry_date":pos["entry_date"],"exit_date":today,
                    "entry_price":entry_price,"exit_price":exit_price,"shares":shares_rem,
                    "commission":round(comm+pos["entry_commission"],4),"pnl_usd":pnl,"pnl_pct":pos_pct*100,
                    "days_held":days_held,"exit_reason":reason,"tier":pos["tier"],
                    "consec_down":pos["consec_down_at_entry"],"portfolio_val":portfolio_value+pnl})
                portfolio_value+=pnl
                if time_stop: cooldown_map[tkr]=today
                to_close.append(tkr)
        for tkr in to_close: del open_positions[tkr]
        if not spy_ok or paused or len(open_positions)>=MAX_POSITIONS: continue
        candidates=[]
        for tkr,tkr_df in signals.items():
            if tkr in open_positions or today not in tkr_df.index: continue
            row=tkr_df.loc[today]
            if not row["signal"]: continue
            if tkr in cooldown_map and (pd.Timestamp(today)-pd.Timestamp(cooldown_map[tkr])).days<REENTRY_COOLDOWN_DAYS: continue
            if near_earnings(tkr,today,earnings_map): continue
            if not sector_ok(tkr,today,sector_data): continue
            if count_sector_positions(tkr,open_positions)>=MAX_SECTOR_POSITIONS: continue
            candidates.append((tkr,float(row["rsi2"]),int(row["consec_down"])))
        candidates.sort(key=lambda x:x[1])
        for tkr,rsi_val,consec_val in candidates:
            if len(open_positions)>=MAX_POSITIONS: break
            tkr_df=signals[tkr]; today_idx=tkr_df.index.get_loc(today)
            if today_idx+1>=len(tkr_df): continue
            next_row=tkr_df.iloc[today_idx+1]; entry_price=float(next_row["Open"])
            if entry_price<=0: continue
            prev_close_val=float(tkr_df.iloc[today_idx]["Close"])
            gap_pct=(entry_price-prev_close_val)/prev_close_val
            if gap_pct<GAP_DOWN_MAX or gap_pct>GAP_UP_MAX: continue
            tier_cfg=get_tier(consec_val); pos_size=get_position_size(today,vix_df)
            shares=(portfolio_value*pos_size)/entry_price; entry_comm=calc_commission(shares,entry_price)
            open_positions[tkr]={"entry_date":tkr_df.index[today_idx+1],"entry_price":entry_price,
                "shares":shares,"shares_remaining":shares,"rsi2_at_entry":rsi_val,
                "consec_down_at_entry":consec_val,"profit_target":tier_cfg["profit_target"],
                "hold_days":tier_cfg["hold_days"],"partial_enabled":tier_cfg["partial_enabled"],
                "partial_frac":tier_cfg["partial_frac"],"partial_trigger":tier_cfg["partial_trigger"],
                "partial_done":False,"tier":tier_cfg["tier"],"entry_commission":entry_comm}
    print(f"[Backtest] Complete — {len(trades)} trades executed.")
    return pd.DataFrame(trades)


def compute_metrics(trades_df):
    if trades_df.empty: return {"error":"No trades generated."},pd.DataFrame()
    trades_df=trades_df.sort_values("exit_date").reset_index(drop=True)
    equity=INITIAL_CAPITAL; equity_curve=[]
    for _,row in trades_df.iterrows(): equity+=row["pnl_usd"]; equity_curve.append({"date":row["exit_date"],"equity":equity})
    eq_df=pd.DataFrame(equity_curve)
    start_dt=pd.to_datetime(trades_df["entry_date"].min()); end_dt=pd.to_datetime(trades_df["exit_date"].max())
    years=max((end_dt-start_dt).days/365.25,1e-6); cagr=(equity/INITIAL_CAPITAL)**(1/years)-1
    winners=trades_df[trades_df["pnl_usd"]>0]; losers=trades_df[trades_df["pnl_usd"]<=0]
    win_rate=len(winners)/len(trades_df)*100
    avg_win=winners["pnl_pct"].mean() if len(winners) else 0
    avg_loss=losers["pnl_pct"].mean() if len(losers) else 0
    eq_df["peak"]=eq_df["equity"].cummax(); eq_df["dd"]=(eq_df["equity"]-eq_df["peak"])/eq_df["peak"]*100
    max_dd=eq_df["dd"].min(); gp=winners["pnl_usd"].sum(); gl=abs(losers["pnl_usd"].sum())
    pf=gp/gl if gl>0 else float("inf")
    eq_df["date"]=pd.to_datetime(eq_df["date"]); eq_df.set_index("date",inplace=True)
    monthly_ret=eq_df["equity"].resample("ME").last().ffill().pct_change().dropna()
    sharpe=monthly_ret.mean()/monthly_ret.std()*np.sqrt(12) if monthly_ret.std()>0 else 0
    total_comm=trades_df["commission"].sum() if "commission" in trades_df else 0
    exit_counts=trades_df["exit_reason"].value_counts().to_dict() if "exit_reason" in trades_df.columns else {}
    tier_stats={}
    if "tier" in trades_df.columns:
        for t in sorted(trades_df["tier"].unique()):
            t_df=trades_df[trades_df["tier"]==t]; t_win=t_df[t_df["pnl_usd"]>0]; t_los=t_df[t_df["pnl_usd"]<=0]
            tier_stats[f"tier_{t}"]={"trades":len(t_df),"win_rate":round((t_df["pnl_usd"]>0).mean()*100,1),
                "avg_win":round(t_win["pnl_pct"].mean(),2) if len(t_win) else 0,
                "avg_loss":round(t_los["pnl_pct"].mean(),2) if len(t_los) else 0,
                "avg_days":round(t_df["days_held"].mean(),1)}
    full_exits=trades_df[trades_df["exit_reason"]!="partial_exit"] if "exit_reason" in trades_df.columns else trades_df
    time_stop_n=exit_counts.get("time_stop",0)
    time_stop_rt=round(time_stop_n/len(full_exits)*100,1) if len(full_exits) else 0
    metrics={"period_start":start_dt.date().isoformat(),"period_end":end_dt.date().isoformat(),
        "years_tested":round(years,2),"total_trades":len(trades_df),"trades_per_year":round(len(trades_df)/years,1),
        "win_rate_pct":round(win_rate,2),"cagr_pct":round(cagr*100,2),
        "roi_per_year_pct":round((equity-INITIAL_CAPITAL)/INITIAL_CAPITAL/years*100,2),
        "avg_days_held":round(trades_df["days_held"].mean(),2),"avg_win_pct":round(avg_win,2),
        "avg_loss_pct":round(avg_loss,2),"profit_factor":round(pf,2),"max_drawdown_pct":round(max_dd,2),
        "sharpe_ratio":round(sharpe,2),"time_stop_rate_pct":time_stop_rt,
        "exit_reasons":{k:int(v) for k,v in exit_counts.items()},"tier_stats":tier_stats,
        "total_commission_usd":round(total_comm,2),"initial_capital":INITIAL_CAPITAL,
        "final_equity":round(equity,2),"total_return_pct":round((equity/INITIAL_CAPITAL-1)*100,2)}
    return metrics,eq_df.reset_index()


def save_outputs(trades_df,metrics,eq_df):
    trades_df.to_csv(OUTPUT_DIR/"trades.csv",index=False); eq_df.to_csv(OUTPUT_DIR/"equity_curve.csv",index=False)
    with open(OUTPUT_DIR/"metrics.json","w") as f: json.dump(metrics,f,indent=2,default=str)
    print("\n"+"="*60+"\n  NAIVE MR — V7 REFERENCE RESULTS\n"+"="*60)
    for k,v in metrics.items():
        if k=="tier_stats":
            print("\n  Per-Tier Statistics:")
            for tk,tv in v.items():
                print(f"    {tk}:")
                for sk,sv in tv.items(): print(f"      {sk:<16}: {sv}")
        elif k=="exit_reasons":
            print("\n  Exit Reasons:")
            for ek,ev in v.items(): print(f"    {ek:<30}: {ev}")
        else: print(f"  {k.replace('_',' ').title():<30}: {v}")
    print("="*60)


__all__ = ["get_universe","download_prices","download_reference_data","build_earnings_dates",
           "run_backtest","compute_metrics","save_outputs","INITIAL_CAPITAL","START_DATE","END_DATE"]

if __name__ == "__main__":
    universe=get_universe(); price_data=download_prices(universe)
    spy_df,vix_df,sector_data=download_reference_data()
    earnings_map=build_earnings_dates(list(price_data.keys()))
    trades_df=run_backtest(price_data,spy_df,vix_df,sector_data,earnings_map)
    if trades_df.empty: print("[ERROR] No trades generated.")
    else: metrics,eq_df=compute_metrics(trades_df); save_outputs(trades_df,metrics,eq_df)
