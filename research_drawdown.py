"""DD-001: descriptive drawdown and recovery distributions, development only."""
import json
import math
from datetime import date
from pathlib import Path

import numpy as np

from binance_minute import digest,json_write
from research_buy import ROOT as PRICE_ROOT,HASHES,FIRST,DEV_END,DAY,WEEK,days,mondays,window,outcome,load_development

ROOT=Path(__file__).resolve().parent/"data"/"research"/"drawdown_v1"
VERSION="DD-001-descriptive-v1"
START=date(2016,7,4)
HORIZONS=(7,28,90)
BINS=((0,.1),(.1,.2),(.2,.4),(.4,.6),(.6,float("inf")))
NAMES=("0_to_10","10_to_20","20_to_40","40_to_60","60_plus")
QUANTILES=(.05,.1,.25,.5,.75,.9,.95)
FRACTIONS=(0.,.25,.5,.75,1.)


def group(depth):
    if not math.isfinite(depth) or not 0<=depth<1:
        raise ValueError("Invalid drawdown")
    # Suppress floating-point boundary error for exact decimal thresholds.
    depth=round(depth,12)
    for name,(lo,hi) in zip(NAMES,BINS):
        if lo<=depth<hi:
            return name
    raise ValueError("Unclassified drawdown")


def peak_history(prices,first,end):
    """Observed closing high, never intraday high; do not invent prehistory.
    Gaps censor active episodes; a subsequent valid close may establish a
    new observed high, but the true peak during the gap is unknown.
    """
    peak=None;peak_date=None;active=None;uncertain=False
    states={};episodes=[]
    for d in days(first,end):
        r=prices.get(d)
        if r is None or r[4]<=0:
            if active is not None:
                active["end_date"]=d.isoformat()
                active["status"]="gap_censored"
                active=None
            uncertain=True
            continue
        c=r[3]
        if peak is None or c>=peak:
            if active is not None:
                active["end_date"]=d.isoformat()
                active["status"]="recovered"
                active=None
            peak=c;peak_date=d
            uncertain=False
        else:
            depth=1-c/peak
            if active is None:
                active={"id":d.isoformat(),"start_date":d.isoformat(),
                        "peak_date":peak_date.isoformat(),"peak_close":peak,
                        "max_depth":depth,"trough_date":d.isoformat(),
                        "left_truncated_or_gap":uncertain or peak_date==first,
                        "end_date":None,"status":"open"}
                episodes.append(active)
            elif depth>active["max_depth"]:
                active["max_depth"]=depth
                active["trough_date"]=d.isoformat()
        states[d]={"close":c,"peak":peak,"peak_date":peak_date.isoformat(),
                   "depth":max(0.,1-c/peak),
                   "episode":active["id"] if active else None,
                   "gap_uncertainty":uncertain}
    if active is not None:
        active["status"]="end_censored";active["end_date"]=end.isoformat()
    return states,episodes


def recovery(prices,t,peak,end):
    """First daily close >= the predecision reference high, from entry.
    Time 1 means the entry day's closing price. Censor at first invalid day
    or exclusive study cutoff. No inference about the interval before entry.
    """
    n=0
    for d in days(t,end):
        r=prices.get(d)
        if r is None or r[4]<=0:
            return {"days":n,"event":False,"reason":"gap"}
        n+=1
        if r[3]>=peak:
            return {"days":n,"event":True,"reason":"recovered"}
    return {"days":n,"event":False,"reason":"cutoff"}


def survival(rows):
    """Descriptive Kaplan-Meier on weekly origins; correlated observations.
    Events at a time precede censoring at that time.
    """
    if not rows:
        return {"n":0}
    n=len(rows);at_risk=n;s=1.;median=None;curve=[]
    for t in sorted({r["days"] for r in rows}):
        events=sum(r["days"]==t and r["event"] for r in rows)
        censored=sum(r["days"]==t and not r["event"] for r in rows)
        if events:
            s*=1-events/at_risk
            if median is None and s<=.5:
                median=t
        curve.append({"days":t,"at_risk":at_risk,"events":events,
                      "censored":censored,"unrecovered_fraction":float(s)})
        at_risk-=events+censored
    probs={}
    for h in (7,28,90,180,365):
        # With no subjects observed to h and surviving unrecovered subjects,
        # the curve is not supported beyond the last follow-up.
        if max(r["days"] for r in rows)<h and s>0:
            probs[str(h)]=None
        else:
            probs[str(h)]=float(1-next((r["unrecovered_fraction"] for r in reversed(curve) if r["days"]<=h),1.))
    return {"n":n,"recovered":sum(r["event"] for r in rows),
            "censored":sum(not r["event"] for r in rows),
            "median_days":median,"recovered_by_day_km":probs,"curve":curve}


def quantiles(values):
    a=np.asarray(values,dtype=float)
    return {"mean":float(a.mean()),
            "quantiles":{str(int(q*100)):float(x) for q,x in zip(QUANTILES,np.quantile(a,QUANTILES))}}


def portfolio(prices,t,h,f):
    """Illustrative static exposure to BTC, rest in cash, no subsequent buys.
    Same starting budget; cash 0% yield; 0.1% fee on initial buy.
    Daily closing marks, initial capital and endpoint open for portfolio DD.
    """
    op=prices[t][0]
    q=f*.999/op
    marks=np.array([1.]+[1-f+q*prices[d][3] for d in days(t,t+h*DAY)]
                   +[1-f+q*prices[t+h*DAY][0]])
    low=min(prices[d][2] for d in days(t,t+h*DAY))
    worst=min(1.,1-f+q*min(low,prices[t+h*DAY][0]))
    return {"terminal_return_pct":float(100*(marks[-1]-1)),
            "worst_from_initial_pct":float(100*(worst-1)),
            "portfolio_drawdown_pct":float(100*np.min(marks/np.maximum.accumulate(marks)-1))}


def build_rows(prices,first,start=START,end=DEV_END):
    if end>DEV_END or not first<=start<end:
        raise ValueError("Invalid descriptive range")
    if any(d>=DEV_END for d in prices):
        raise ValueError("Post-development price supplied")
    states,episodes=peak_history(prices,first,end)
    rows=[];skips=[]
    for t in mondays(start,end):
        s=states.get(t-2*DAY)
        if s is None or t not in prices or prices[t][4]<=0:
            skips.append({"date":t.isoformat(),"reason":"missing decision close or entry"})
            continue
        r={"date":t.isoformat(),**s,"bin":group(s["depth"]),
           "recovery":recovery(prices,t,s["peak"],end),"outcomes":{}}
        for h in HORIZONS:
            if t+(h+1)*DAY>end:
                continue
            y=outcome(prices,t,h)
            if y is None:
                continue
            r["outcomes"][str(h)]={"return_pct":100*math.expm1(y["log_return"]),
                                  "worst_from_entry_pct":100*math.expm1(y["log_worst"])}
            if h in (28,90):
                r["outcomes"][str(h)]["illustrative_exposure"]={
                    str(int(f*100)):portfolio(prices,t,h,f) for f in FRACTIONS}
        rows.append(r)
    return rows,episodes,skips


def episode_medians(rows,h,key):
    # A sensitivity, not independent samples: one median for each distinct
    # observed peak-to-recovery episode (excluding high-water origins).
    buckets={}
    for r in rows:
        if r["episode"] is not None:
            buckets.setdefault(r["episode"],[]).append(r["outcomes"][str(h)][key])
    return {"n":len(buckets),"median_of_episode_medians":float(np.median(
            [np.median(v) for v in buckets.values()])) if buckets else None}


def summarize(rows):
    result={"n_weekly_origins":len(rows),
            "distinct_drawdown_episodes":len({r["episode"] for r in rows if r["episode"] is not None}),
            "at_observed_high_origins":sum(r["episode"] is None for r in rows),
            "gap_uncertain_origins":sum(r["gap_uncertainty"] for r in rows),
            "recovery":survival([r["recovery"] for r in rows]),"horizons":{}}
    for h in HORIZONS:
        a=[r for r in rows if str(h) in r["outcomes"]]
        n=len(a)
        if not n:
            result["horizons"][str(h)]={"n":0,"excluded":len(rows)}
            continue
        ret=np.array([r["outcomes"][str(h)]["return_pct"] for r in a])
        worst=np.array([r["outcomes"][str(h)]["worst_from_entry_pct"] for r in a])
        v={"n":n,"excluded":len(rows)-n,
           "distinct_drawdown_episodes":len({r["episode"] for r in a if r["episode"] is not None}),
           "return_pct":quantiles(ret),"worst_from_entry_pct":quantiles(worst),
           "positive_return_fraction":float(np.mean(ret>0)),
           "further_loss_fraction":{str(k):float(np.mean(worst<=-k+1e-10)) for k in (10,15,20,30)},
           "episode_weight_sensitivity":{k:episode_medians(a,h,k) for k in ("return_pct","worst_from_entry_pct")}}
        if h in (28,90):
            v["illustrative_exposure"]={}
            for f in FRACTIONS:
                k=str(int(f*100))
                z=[r["outcomes"][str(h)]["illustrative_exposure"][k] for r in a]
                v["illustrative_exposure"][k]={m:quantiles([r[m] for r in z]) for m in
                      ("terminal_return_pct","worst_from_initial_pct","portfolio_drawdown_pct")}
        result["horizons"][str(h)]=v
    return result


def analyze(prices,first,end=DEV_END):
    rows,episodes,skips=build_rows(prices,first,end=end)
    if not rows:
        raise ValueError("No valid weekly origins")
    return {"first_origin":rows[0]["date"],"last_origin":rows[-1]["date"],
            "peak_history_start":first.isoformat(),"unconditional":summarize(rows),
            "by_depth":{k:summarize([r for r in rows if r["bin"]==k]) for k in NAMES},
            "episode_inventory_10pct_or_more":[e for e in episodes if e["max_depth"]>=.1-1e-12],
            "all_drawdown_episodes_count":len(episodes),
            "skipped":skips,"rows":rows}


def run(root=ROOT,price_root=PRICE_ROOT):
    root=Path(root);target=root/"drawdown_report.json"
    if target.exists():
        raise ValueError("Report already exists; preserve original")
    markets={}
    # Same observed peak start and evaluation origins for price cross-check.
    first=max(FIRST.values())
    for m in HASHES:
        print("DD descriptive:",m,flush=True)
        prices=load_development(Path(price_root),m)
        markets[m]=analyze(prices,first)
    a={r["date"]:r for r in markets["bitstamp"]["rows"]}
    b={r["date"]:r for r in markets["coinbase"]["rows"]}
    common=sorted(set(a)&set(b))
    cross={"common_origins":len(common),"bin_disagreements":[t for t in common if a[t]["bin"]!=b[t]["bin"]],
           "bitstamp_only":sorted(set(a)-set(b)),"coinbase_only":sorted(set(b)-set(a))}
    report={"protocol":VERSION,"price_hashes":HASHES,"test_numeric_values_parsed":False,
            "start":START.isoformat(),"end_exclusive":DEV_END.isoformat(),
            "markets":markets,"price_cross_check":cross,
            "limitations":["Observed high since 2015-07-20, not lifetime ATH; 2014 crash excluded.",
                "Weekly origins overlap, episodes are not independent cycles; no confidence or forecast claims.",
                "Bin at Saturday close; Monday open execution proxy, not same price.",
                "Recovery to frozen reference closing high, not return to entry or later peak; right censoring.",
                "Kaplan-Meier descriptive; non-independent and potentially informative censoring.",
                "Static exposure examples exclude existing portfolio, future deposits, cash yield, taxes and slippage.",
                "No optimization, no trade rule, no personal risk preference; no 2024+ data used."]}
    json_write(target,report)
    print("Send",target,flush=True)
    return report


if __name__=="__main__":
    run()
