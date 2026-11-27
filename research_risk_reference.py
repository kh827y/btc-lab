"""RISK-001: price-only calibration diagnostic on previously studied history."""
import math
from datetime import date
from pathlib import Path

import numpy as np

from binance_minute import json_write
from research_buy import (ROOT as PRICE_ROOT,HASHES,DAY,DEV_END,mondays,state,
                          outcome,load_development)

ROOT=Path(__file__).resolve().parent/"data"/"research"/"risk_reference_v1"
VERSION="RISK-001-reference-diagnostic-v1"
START=date(2016,7,4)
EVAL_START=date(2018,1,1)
HORIZONS=(7,28,90)
QUANTILES=(.1,.5,.9)
MIN_TRAIN=52
ROLL=104
MODELS=("empirical_expanding","empirical_104","scaled_expanding","scaled_104")
LOSS_THRESHOLD=math.log(.85)


def empirical_crps(samples,actual):
    """Exact CRPS for equally weighted empirical distribution, O(n log n)."""
    a=np.sort(np.asarray(samples,dtype=float))
    n=len(a)
    if n==0:
        raise ValueError("Empty distribution")
    # Half the expected absolute pairwise difference, including self pairs.
    spread=np.dot(2*np.arange(1,n+1)-n-1,a)/(n*n)
    return max(0.,float(np.mean(np.abs(a-actual))-spread))


def distributions(history,sigma):
    if len(history)<MIN_TRAIN or not math.isfinite(sigma) or sigma<=0:
        raise ValueError("Insufficient history or invalid volatility")
    x=np.array([[r["sigma"],r["log_return"],r["log_worst"],r["variance"]]
                for r in history],dtype=float)
    if (not np.all(np.isfinite(x)) or np.any(x[:,0]<=0)
            or np.any(x[:,2]>0) or np.any(x[:,3]<0)):
        raise ValueError("Invalid history")
    out={}
    for name in MODELS:
        a=x[-ROLL:] if name.endswith("_104") else x
        scale=sigma/a[:,0] if name.startswith("scaled") else np.ones(len(a))
        out[name]={"return":a[:,1]*scale,"worst":a[:,2]*scale,
                   "variance":max(1e-12,float(np.mean(a[:,3]*scale*scale)))}
    return out


def score_distribution(d,y):
    r=d["return"];w=d["worst"];n=len(r)
    p=float((1+np.sum(r>0))/(n+2))
    q=float((1+np.sum(w<=LOSS_THRESHOLD))/(n+2))
    v=d["variance"]
    ret=np.quantile(r,QUANTILES);worst=np.quantile(w,QUANTILES)
    def pinball(qs,actual):
        e=actual-qs;a=np.asarray(QUANTILES)
        return float(np.maximum(a*e,(a-1)*e).mean())
    return {"n_train":n,"p_up":p,"p_loss_15":q,
            "return_log_quantiles":list(map(float,ret)),
            "worst_log_quantiles":list(map(float,worst)),
            "daily_variance":v,
            "scores":{"brier_up":float((p-int(y["log_return"]>0))**2),
                "brier_loss_15":float((q-int(y["log_worst"]<=LOSS_THRESHOLD))**2),
                "crps_return":empirical_crps(r,y["log_return"]),
                "crps_worst":empirical_crps(w,y["log_worst"]),
                "pinball_return":pinball(ret,y["log_return"]),
                "pinball_worst":pinball(worst,y["log_worst"]),
                "qlike":float(math.log(v)+y["variance"]/v)}}


def replay(prices,h,end=DEV_END):
    if h not in HORIZONS or not START<end<=DEV_END:
        raise ValueError("Unregistered horizon/range")
    if any(d>=DEV_END for d in prices):
        raise ValueError("Post-development numeric prices supplied")
    pending=[];history=[];rows=[];missing=[]
    for t in mondays(START,end):
        cutoff=t-DAY
        while pending and pending[0][0]+(h+1)*DAY<=cutoff:
            old,sigma=pending.pop(0)
            y=outcome(prices,old,h)
            if y is not None:
                history.append({"date":old,"sigma":sigma,**y})
        eligible=t>=EVAL_START and t+(h+1)*DAY<=end
        s=state(prices,t)
        if s is None:
            if eligible:
                missing.append({"date":t.isoformat(),"reason":"invalid predecision state"})
            continue
        sigma=s["sigma"]
        pending.append((t,sigma))
        if not eligible:
            continue
        if len(history)<MIN_TRAIN:
            missing.append({"date":t.isoformat(),"reason":"insufficient matured history"})
            continue
        d=distributions(history,sigma)
        # Scoring is separate from construction of forecasts. No realized
        # outcome enters training until its endpoint day has closed.
        y=outcome(prices,t,h)
        if y is None:
            missing.append({"date":t.isoformat(),"reason":"invalid outcome"})
            continue
        ewma=max(1e-12,sigma*sigma)
        rows.append({"date":t.isoformat(),"latest_train_origin":history[-1]["date"].isoformat(),
                     "n_matured":len(history),"sigma":sigma,"actual":y,
                     "models":{k:score_distribution(v,y) for k,v in d.items()},
                     "ewma_variance":{"daily_variance":ewma,
                         "qlike":float(math.log(ewma)+y["variance"]/ewma)}})
    return rows,missing


def calibration(pred,actual):
    p=np.asarray(pred,dtype=float);y=np.asarray(actual,dtype=float)
    bins=[]
    for i in range(5):
        lo=i/5;hi=(i+1)/5
        mask=(p>=lo)&((p<=hi) if i==4 else (p<hi))
        n=int(mask.sum())
        bins.append({"lower":lo,"upper":hi,"n":n,
                     "mean_probability":float(p[mask].mean()) if n else None,
                     "actual_frequency":float(y[mask].mean()) if n else None})
    return {"mean_probability":float(p.mean()),"actual_frequency":float(y.mean()),
            "bins":bins}


def summarize(rows):
    if not rows:
        return {"n":0}
    up=np.array([r["actual"]["log_return"]>0 for r in rows],dtype=float)
    loss=np.array([r["actual"]["log_worst"]<=LOSS_THRESHOLD for r in rows],dtype=float)
    out={"n":len(rows),"up_frequency":float(up.mean()),"loss_15_frequency":float(loss.mean()),
         "coinflip_brier_up":.25,
         "ewma_mean_qlike":float(np.mean([r["ewma_variance"]["qlike"] for r in rows])),
         "models":{}}
    for m in MODELS:
        a=[r["models"][m] for r in rows]
        v={"scores":{k:float(np.mean([p["scores"][k] for p in a])) for k in a[0]["scores"]},
           "up_calibration":calibration([p["p_up"] for p in a],up),
           "loss_15_calibration":calibration([p["p_loss_15"] for p in a],loss)}
        for label,key in (("return","log_return"),("worst","log_worst")):
            q=np.array([p[label+"_log_quantiles"] for p in a])
            y=np.array([r["actual"][key] for r in rows])
            v[label+"_quantile_observed_cdf"]={str(int(t*100)):float(np.mean(y<=q[:,i]))
                                               for i,t in enumerate(QUANTILES)}
            v[label+"_central80_coverage"]=float(np.mean((y>=q[:,0])&(y<=q[:,2])))
        out["models"][m]=v
    return out


def run(root=ROOT,price_root=PRICE_ROOT):
    root=Path(root);target=root/"risk_reference_report.json"
    if target.exists():
        raise ValueError("Report already exists; preserve original")
    markets={}
    for m in HASHES:
        print("Risk reference:",m,flush=True)
        p=load_development(Path(price_root),m)
        horizons={}
        for h in HORIZONS:
            rows,missing=replay(p,h)
            if not rows:
                raise ValueError("No complete reference forecasts")
            horizons[str(h)]={"summary":summarize(rows),"first":rows[0]["date"],
                "last":rows[-1]["date"],"missing":missing,
                "by_year":{str(year):summarize([r for r in rows if r["date"].startswith(str(year))])
                           for year in range(EVAL_START.year,DEV_END.year)},
                "predictions":rows}
        markets[m]=horizons
    common={}
    for h in HORIZONS:
        a=markets["bitstamp"][str(h)]["predictions"];b=markets["coinbase"][str(h)]["predictions"]
        common[str(h)]={"common_origins":len({r["date"] for r in a}&{r["date"] for r in b}),
                        "bitstamp_origins":len(a),"coinbase_origins":len(b)}
    report={"protocol":VERSION,"price_hashes":HASHES,"end_exclusive":DEV_END.isoformat(),
            "test_numeric_values_parsed":False,"kind":"descriptive_calibration_diagnostic",
            "confirmation_authorized":False,"markets":markets,"cross_check":common,
            "limitations":["Previously studied historical outcomes; not fresh confirmation.",
                "GATE-001 did not pass; no claim of adequate power or profitable signal.",
                "Historical weekly outcomes overlap; years/exchanges are not independent replications.",
                "Scaled returns preserve sign; scaled/unscaled up probabilities duplicate each other on same history.",
                "Daily close-based EWMA predicts open-to-open variance proxy, not exact intraday risk.",
                "Calibration bins and quantile coverage descriptive, especially sparse groups.",
                "No model selection, trade rule, investor utility or data after 2023."]}
    json_write(target,report)
    print("Send",target,flush=True)
    return report


if __name__=="__main__":
    run()
