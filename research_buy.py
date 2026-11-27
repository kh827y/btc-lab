"""BUY-001 development-only: weekly purchase decisions and price-risk baselines."""
import csv
import io
import json
import math
from datetime import date,timedelta
from pathlib import Path

import numpy as np

from binance_minute import digest,json_write
from research_daily_usd import ROOT

DEV_END=date(2024,1,1)
DAY=timedelta(days=1)
WEEK=7*DAY
HORIZON=28
HASHES={
    "bitstamp":"4b733feda6bd69c4810471440d2b53fba69ccdd3af47ca3caae593db75063bf9",
    "coinbase":"bc6282765d3e1638522e16422c0e833261c3058c6b7c4f6dbe869c2f3d36766e",
}
FIRST={"bitstamp":date(2014,1,1),"coinbase":date(2015,7,20)}
START=date(2016,7,4)
COMMON_START=date(2018,1,1)
RULES=("dca","lump","trend","dip","risk")
SEED=20261127
RESAMPLES=10000


def load_development(root,market):
    """Verify complete file identity, parse numeric values only before cutoff."""
    raw=(root/(market+"_daily.csv")).read_bytes()
    if digest(raw)!=HASHES[market]:
        raise ValueError("Daily snapshot changed: "+market)
    reader=csv.DictReader(io.StringIO(raw.decode("utf-8")))
    if reader.fieldnames!=["date_utc","open","high","low","close","volume_btc"]:
        raise ValueError("Unexpected daily schema")
    prices={}
    cursor=FIRST[market]
    for r in reader:
        d=date.fromisoformat(r["date_utc"])
        if d>=DEV_END:
            break
        if d!=cursor:
            raise ValueError("Missing, duplicated or unordered daily row")
        cursor+=DAY
        v=tuple(float(r[k]) for k in reader.fieldnames[1:])
        op,hi,lo,cl,vol=v
        if not all(math.isfinite(x) for x in v) or not 0<lo<=min(op,cl)<=max(op,cl)<=hi or vol<0:
            raise ValueError("Invalid daily OHLCV")
        prices[d]=v
    if cursor!=DEV_END:
        raise ValueError("Incomplete development history")
    return prices


def days(a,b):
    while a<b:
        yield a
        a+=DAY


def mondays(a,b):
    a+=timedelta(days=(-a.weekday())%7)
    while a<b:
        yield a
        a+=WEEK


def window(prices,a,b):
    rows=[prices.get(d) for d in days(a,b)]
    return np.array(rows) if rows and all(r is not None and r[4]>0 for r in rows) else None


def state(prices,t):
    # Sunday UTC decision, latest available input = Saturday close.
    # Never use Sunday close or Monday open when forming a decision.
    x=window(prices,t-91*DAY,t-DAY)
    if x is None or len(x)!=90:
        return None
    closes=x[:,3]
    r=np.diff(np.log(closes[-61:]))
    weights=.94**np.arange(len(r)-1,-1,-1)
    sigma=float(np.sqrt(np.average(r*r,weights=weights)))
    return {"sigma":max(sigma,1e-6),"close":float(closes[-1]),
            "ma":{n:float(closes[-n:].mean()) for n in (10,20,50)},
            "drawdown":float(closes[-1]/closes.max()-1)}


def outcome(prices,t,h=HORIZON):
    x=window(prices,t,t+(h+1)*DAY)
    if x is None:
        return None
    op=x[0,0];end=x[-1,0]
    return {"log_return":float(np.log(end/op)),
            "log_worst":min(0.,float(np.log(min(x[:-1,2].min(),end)/op))),
            "variance":float(np.mean(np.diff(np.log(x[:,0]))**2))}


def distributions(history,sigma):
    sig=np.array([x["sigma"] for x in history])
    y=np.array([x["y"]["log_return"] for x in history])
    w=np.array([x["y"]["log_worst"] for x in history])
    v=np.array([x["y"]["variance"] for x in history])
    result={}
    for name,scale in (("M0",np.ones(len(sig))),("M1",sigma/sig)):
        r=y*scale
        loss=w*scale<=np.log(.85)
        result[name]={"n":len(r),"p_up":float((1+np.sum(r>0))/(len(r)+2)),
                      "p_loss_15":float((1+loss.sum())/(len(r)+2)),
                      "quantiles":list(map(float,np.quantile(r,[.1,.5,.9]))),
                      "variance":max(1e-12,float(np.mean(v*scale**2)))}
    return result


def forecast_score(pred,y):
    up=int(y["log_return"]>0)
    loss=int(y["log_worst"]<=np.log(.85))
    p=pred["p_up"];q=pred["p_loss_15"]
    errors=y["log_return"]-np.array(pred["quantiles"])
    quant=np.array([.1,.5,.9])
    var=pred["variance"]
    return {"brier_up":(p-up)**2,"brier_loss_15":(q-loss)**2,
            "log_up":-math.log(p if up else 1-p),
            "log_loss_15":-math.log(q if loss else 1-q),
            "pinball":float(np.maximum(quant*errors,(quant-1)*errors).mean()),
            "qlike":float(np.log(var)+y["variance"]/var),
            "interval_hit":int(pred["quantiles"][0]<=y["log_return"]<=pred["quantiles"][2])}


def weekly_signals(prices,first,end=DEV_END):
    if end>DEV_END:
        raise ValueError("Final data are not permitted")
    # Keep past states; outcomes are computed only when already fully known.
    pending=[];history=[];risks=[];signals={};scored=[]
    for t in mondays(first,end):
        cutoff=t-DAY
        while pending and pending[0][0]+(HORIZON+1)*DAY<=cutoff:
            old,s=pending.pop(0)
            y=outcome(prices,old)
            if y is not None:
                history.append({"sigma":s["sigma"],"y":y})
        s=state(prices,t)
        if s is None:
            continue
        pending.append((t,s))
        if len(history)<52:
            continue
        models=distributions(history[-104:],s["sigma"])
        thresholds={p:float(np.quantile(risks[-104:],p)) for p in (.7,.8,.9)} if len(risks)>=26 else None
        signals[t]={**s,"models":models,"thresholds":thresholds}
        risks.append(models["M1"]["p_loss_15"])
    # Evaluate only after forecasts are fixed and only completed development windows.
    for t,s in signals.items():
        if t+(HORIZON+1)*DAY>end:
            continue
        y=outcome(prices,t)
        if y is not None:
            scored.append({"date":t.isoformat(),"models":{k:forecast_score(v,y) for k,v in s["models"].items()}})
    return signals,scored


def allocation(rule,i,n,remaining,s,ma=20,dip=.2,risk=.8):
    if i==n-1 or rule=="lump":
        return remaining
    if rule=="dca":
        return min(1,remaining)
    if rule=="trend":
        return remaining if s["close"]>s["ma"][ma] else 0
    if rule=="dip":
        return min(2 if s["drawdown"]<=-dip else 1,remaining)
    if rule=="risk":
        if s["models"]["M1"]["p_loss_15"]>s["thresholds"][risk]:
            return 0
        return min(i+1-(n-remaining),remaining)
    raise ValueError("Unknown rule")


def simulate(prices,signals,t,rule,n=8,ma=20,dip=.2,risk=.8,fee=0.001):
    end=t+n*WEEK
    x=window(prices,t,end+DAY)
    if x is None:
        return None
    dates=[t+i*WEEK for i in range(n)]
    if any(d not in signals or signals[d]["thresholds"] is None for d in dates):
        return None
    remaining=n;btc=0.;alloc=[];values=[1.];waiting=0.
    for j,d in enumerate(days(t,end)):
        if j%7==0:
            i=j//7
            units=allocation(rule,i,n,remaining,signals[d],ma,dip,risk)
            if not 0<=units<=remaining:
                raise ValueError("Invalid allocation")
            remaining-=units
            btc+=(units/n)*(1-fee)/prices[d][0]
            waiting+=units*i*7/n
            alloc.append(units)
        values.append(remaining/n+btc*prices[d][3])
    if remaining!=0 or btc<=0 or sum(alloc)!=n:
        raise ValueError("Budget not invested at deadline")
    values.append(btc*prices[end][0])
    v=np.asarray(values)
    dd=float(np.min(v/np.maximum.accumulate(v)-1))
    return {"btc":btc,"portfolio_drawdown":dd,"waiting_days":waiting,
            "allocations":alloc}


def episodes(prices,signals,start,end,n=8,ma=20,dip=.2,risk=.8,fee=.001):
    if end>DEV_END:
        raise ValueError("Final data are not permitted")
    rows=[];skipped=[]
    for t in mondays(start,end):
        if t+n*WEEK>=end:
            break
        r={k:simulate(prices,signals,t,k,n,ma,dip,risk,fee) for k in RULES}
        if any(v is None for v in r.values()):
            skipped.append(t.isoformat())
            continue
        rows.append({"date":t.isoformat(),"rules":r})
    return rows,skipped


def stats(rows,n=8,intervals=True):
    if not rows:
        return {"n":0}
    base=np.array([r["rules"]["dca"]["btc"] for r in rows])
    lump=np.array([r["rules"]["lump"]["btc"] for r in rows])
    out={}
    for k in RULES:
        rr=[r["rules"][k] for r in rows]
        qty=np.array([v["btc"] for v in rr])
        log=np.log(qty/base)
        gain=qty/base-1
        item={"mean_log_gain_vs_dca_pct":float(log.mean()*100),
              "geometric_gain_vs_dca_pct":float(np.expm1(log.mean())*100),
              "mean_gain_vs_lump_pct":float(np.mean(qty/lump-1)*100),
              "p05_gain_vs_dca_pct":float(np.quantile(gain,.05)*100),
              "worst_gain_vs_dca_pct":float(gain.min()*100),
              "fraction_loss_vs_dca_5pct":float((gain<-.05).mean()),
              "mean_portfolio_drawdown_pct":float(np.mean([v["portfolio_drawdown"] for v in rr])*100),
              "worst_portfolio_drawdown_pct":float(min(v["portfolio_drawdown"] for v in rr)*100),
              "mean_waiting_days":float(np.mean([v["waiting_days"] for v in rr]))}
        if intervals:
            item["paired_90pct_log_gain_intervals"]={}
            # Blocks sampled by calendar-week slots, not compressed surviving dates.
            # Reject gaps inside blocks; report if a block length has too few starts.
            dates=[date.fromisoformat(r["date"]) for r in rows]
            for b in (13,26,52):
                starts=np.array([i for i in range(len(rows)-b+1)
                                 if dates[i+b-1]-dates[i]==(b-1)*WEEK],dtype=int)
                if len(starts)<2:
                    item["paired_90pct_log_gain_intervals"][str(b)]=None
                    continue
                rng=np.random.default_rng(SEED)
                indices=(rng.choice(starts,size=(RESAMPLES,(len(rows)+b-1)//b))[:,:,None]+np.arange(b)).reshape(RESAMPLES,-1)[:,:len(rows)]
                item["paired_90pct_log_gain_intervals"][str(b)]=list(map(float,np.quantile(log[indices].mean(axis=1)*100,[.05,.95])))
        out[k]=item
    # Greedy disjoint windows, not an estimate of statistical independence.
    last=None;disjoint=0
    for r in rows:
        t=date.fromisoformat(r["date"])
        if last is None or t>last:
            disjoint+=1;last=t+n*WEEK
    return {"n":len(rows),"nonoverlap_windows":disjoint,"rules":out}


def risk_summary(scores,start):
    rows=[r for r in scores if date.fromisoformat(r["date"])>=start]
    return {"n":len(rows),"models":{m:{k:float(np.mean([r["models"][m][k] for r in rows]))
             for k in rows[0]["models"][m]} for m in ("M0","M1")} if rows else {}}


def analyze(prices,market):
    sig,scored=weekly_signals(prices,FIRST[market])
    start=START if market=="bitstamp" else COMMON_START
    rows,skipped=episodes(prices,sig,start,DEV_END)
    common=[r for r in rows if date.fromisoformat(r["date"])>=COMMON_START]
    variants={}
    for name,kw in (("4w",{"n":4}),("16w",{"n":16}),("ma10",{"ma":10}),
                    ("ma50",{"ma":50}),("dip10",{"dip":.1}),("dip30",{"dip":.3}),
                    ("risk70",{"risk":.7}),("risk90",{"risk":.9}),
                    ("fee50bp",{"fee":.005})):
        vr,vs=episodes(prices,sig,start,DEV_END,**kw)
        variants[name]={"stats":stats(vr,kw.get("n",8),False),"skipped_n":len(vs)}
    return {"primary":stats(rows),"common_period":stats(common),
            "skipped_dates":skipped,"risk_forecast":risk_summary(scored,start),
            "risk_common_period":risk_summary(scored,COMMON_START),
            "by_start_year":{str(y):stats([r for r in rows if r["date"].startswith(str(y))],intervals=False)
                             for y in range(start.year,DEV_END.year)},
            "variants":variants,"episode_rows":rows}


def run(root=ROOT):
    root=Path(root)
    m=json.loads((root/"coverage.json").read_bytes())
    if m.get("complete") is not True or m.get("version")!="daily-usd-v1" or any(
            m["markets"][k]["csv_sha256"]!=h for k,h in HASHES.items()):
        raise ValueError("Need verified daily snapshots")
    results={}
    for market in HASHES:
        print("Development:",market,flush=True)
        results[market]=analyze(load_development(root,market),market)
    report={"protocol":"BUY-001-development-v1","test_numeric_values_parsed":False,
            "input_hashes":HASHES,"development_end_exclusive":DEV_END.isoformat(),
            "markets":results,"limitations":["Overlapping weekly starts and few independent regimes.",
              "Open-price execution proxy, no order book, fixed fee, no cash yield.",
              "Portfolio drawdown uses daily closes and endpoint open, not intraday.",
              "Development only; intervals descriptive and no multiple-test significance claims.",
              "Coinbase replication shares the same market episodes. M2 deferred."]}
    target=root/"buy_development_report.json"
    if target.exists():
        if json.loads(target.read_bytes())!=report:
            raise ValueError("Existing development report differs; retain prior version")
    else:
        json_write(target,report)
    print("Send",target,flush=True)


if __name__=="__main__":
    run()
