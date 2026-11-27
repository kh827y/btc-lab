"""Registered development extension: incremental price-state risk and purchase timing."""
import json
from pathlib import Path
from datetime import date
import numpy as np

from binance_minute import digest,json_write
from research_buy import (ROOT,HASHES,FIRST,DAY,WEEK,DEV_END,COMMON_START,HORIZON,
                          SEED,RESAMPLES,mondays,window,state,outcome,distributions,
                          load_development,simulate)

LAMBDA=.1


def features(prices,t):
    s=state(prices,t)
    x=window(prices,t-181*DAY,t-DAY)
    if s is None or x is None:
        return None
    c=x[:,3]
    return s,np.array([np.log(s["sigma"]),np.log(c[-1]/s["ma"][50]),
                        np.log(c[-1]/c.max()),np.log(c[-1]/c[-29])])


def logistic(x,y,current):
    """Fixed ridge logistic regression with training-only standardization."""
    x=np.asarray(x,dtype=float);y=np.asarray(y,dtype=float)
    mean=x.mean(axis=0);sd=x.std(axis=0)
    sd=np.where(sd>1e-10,sd,1.)
    z=(x-mean)/sd
    a=np.column_stack([np.ones(len(x)),z])
    # Smoothed intercept; penalize intercept weakly to handle single-class windows.
    reg=np.diag([.001]+[LAMBDA]*x.shape[1])
    b=np.zeros(a.shape[1])
    # Fixed step from upper bound of Hessian; no hyperparameter search.
    step=1/(.25*np.linalg.norm(a,ord=2)**2/len(y)+LAMBDA)
    for _ in range(300):
        p=1/(1+np.exp(-np.clip(a@b,-35,35)))
        b-=step*(a.T@(p-y)/len(y)+reg@b)
    q=np.r_[1,(np.asarray(current)-mean)/sd]@b
    return float(1/(1+np.exp(-np.clip(q,-20,20))))


def replay(prices,first,end=DEV_END):
    if end>DEV_END:
        raise ValueError("Final data are not permitted")
    pending=[];history=[];prior={m:[] for m in ("M1","L1","M2")}
    signals={};predictions=[]
    for t in mondays(first,end):
        while pending and pending[0][0]+(HORIZON+1)*DAY<=t-DAY:
            d,s,x=pending.pop(0)
            y=outcome(prices,d)
            if y is not None:
                history.append({"sigma":s["sigma"],"x":x,"y":y})
        f=features(prices,t)
        if f is None:
            continue
        s,x=f
        pending.append((t,s,x))
        if len(history)<52:
            continue
        h=history[-104:]
        p=distributions(h,s["sigma"])
        xh=np.array([v["x"] for v in h])
        y={k:np.array([int(v["y"][field]>0) if k=="up" else
                       int(v["y"][field]<=np.log(.85)) for v in h])
           for k,field in (("up","log_return"),("loss_15","log_worst"))}
        for m,cols in (("L1",1),("M2",4)):
            p[m]={"p_"+k:logistic(xh[:,:cols],v,x[:cols]) for k,v in y.items()}
        p["coinflip"]={"p_up":.5,"p_loss_15":.5}
        thresholds={m:float(np.quantile(v[-104:],.8)) if len(v)>=26 else None
                    for m,v in prior.items()}
        signals[t]={"state":s,"pred":p,"thresholds":thresholds}
        for m in prior:
            prior[m].append(p[m]["p_loss_15"])
    for t,v in signals.items():
        if not COMMON_START<=t or t+(HORIZON+1)*DAY>end:
            continue
        y=outcome(prices,t)
        if y is None:
            continue
        predictions.append({"date":t.isoformat(),"actual":{"up":int(y["log_return"]>0),
                            "loss_15":int(y["log_worst"]<=np.log(.85))},
                            "pred":{m:{k:p[k] for k in ("p_up","p_loss_15")} for m,p in v["pred"].items()}})
    return signals,predictions


def interval(values,dates):
    values=np.asarray(values)
    out={}
    for b in (13,26,52):
        starts=[i for i in range(len(values)-b+1) if dates[i+b-1]-dates[i]==(b-1)*WEEK]
        if len(starts)<2:
            out[str(b)]=None
            continue
        rng=np.random.default_rng(SEED)
        ix=(rng.choice(starts,size=(RESAMPLES,(len(values)+b-1)//b))[:,:,None]+np.arange(b)).reshape(RESAMPLES,-1)[:,:len(values)]
        out[str(b)]=list(map(float,np.quantile(values[ix].mean(axis=1),[.05,.95])))
    return out


def assess(rows):
    dates=[date.fromisoformat(r["date"]) for r in rows]
    result={}
    for target in ("up","loss_15"):
        y=np.array([r["actual"][target] for r in rows])
        preds={m:np.array([r["pred"][m]["p_"+target] for r in rows]) for m in rows[0]["pred"]}
        loss={m:(p-y)**2 for m,p in preds.items()}
        result[target]={"actual_frequency":float(y.mean()),"models":{},"paired_brier_deltas":{}}
        for m,p in preds.items():
            bins=[]
            for lo in (0,.2,.4,.6,.8):
                mask=(p>=lo)&(p<lo+.2 if lo<.8 else p<=1)
                if mask.any():
                    bins.append({"n":int(mask.sum()),"p_mean":float(p[mask].mean()),
                                 "actual_frequency":float(y[mask].mean())})
            result[target]["models"][m]={"brier":float(loss[m].mean()),
                 "log_score":float(-np.mean(y*np.log(p)+(1-y)*np.log1p(-p))),
                 "mean_probability":float(p.mean()),"calibration_bins":bins}
        for a,b in (("M1","M0"),("L1","M1"),("M2","L1"),("M2","M0"),("M2","M1")):
            d=loss[a]-loss[b]
            result[target]["paired_brier_deltas"][a+"_minus_"+b]={"mean":float(d.mean()),
                                            "interval90":interval(d,dates)}
    return result


def schedule(prices,t,units,annual_cash=0.,fee=.001):
    """Eight fixed Monday slots; unspent tranches accrue stated hypothetical cash yield."""
    units=np.asarray(units,dtype=float)
    if len(units)!=8 or np.any(units<0) or not np.isclose(units.sum(),8):
        raise ValueError("Invalid allocation")
    end=t+8*WEEK
    btc=0.;remaining=8.;values=[1.]
    for j in range(56):
        d=t+j*DAY
        cash_factor=(1+annual_cash)**(j/365)
        if j%7==0:
            u=units[j//7]
            remaining-=u
            btc+=u/8*cash_factor*(1-fee)/prices[d][0]
        values.append(remaining/8*cash_factor+btc*prices[d][3])
    values.append(btc*prices[end][0])
    v=np.array(values)
    return {"btc":float(btc),"drawdown":float(np.min(v/np.maximum.accumulate(v)-1)),
            "waiting_days":float(np.dot(units,np.arange(8)*7)/8)}


def purchases(prices,signals,end=DEV_END):
    if end>DEV_END:
        raise ValueError("Final data are not permitted")
    mapped={m:{t:{**v["state"],"models":{"M1":v["pred"][m]},
                      "thresholds":{.8:v["thresholds"][m]}}
               for t,v in signals.items() if v["thresholds"][m] is not None}
            for m in ("M1","L1","M2")}
    rows=[]
    for t in mondays(COMMON_START,end):
        if t+8*WEEK>=end:
            break
        if window(prices,t,t+8*WEEK+DAY) is None:
            continue
        risk={m:simulate(prices,v,t,"risk") for m,v in mapped.items()}
        if any(v is None for v in risk.values()):
            continue
        allocations={"dca":[1]*8,"fixed_delay":[.5]+[1]*6+[1.5],
                     **{m:v["allocations"] for m,v in risk.items()}}
        # Fixed delay shifts half of each of first seven tranches one week later.
        rows.append({"date":t.isoformat(),"cash0":{k:schedule(prices,t,v) for k,v in allocations.items()},
                     "cash5":{k:schedule(prices,t,v,.05) for k,v in allocations.items()}})
    return rows


def purchase_summary(rows,scenario):
    dates=[date.fromisoformat(r["date"]) for r in rows]
    base=np.array([r[scenario]["dca"]["btc"] for r in rows])
    delay=np.array([r[scenario]["fixed_delay"]["btc"] for r in rows])
    out={}
    for m in rows[0][scenario]:
        rr=[r[scenario][m] for r in rows]
        qty=np.array([v["btc"] for v in rr])
        gain=np.log(qty/base)*100
        against_delay=np.log(qty/delay)*100
        out[m]={"geometric_gain_vs_dca_pct":float(np.expm1(gain.mean()/100)*100),
                "geometric_gain_vs_fixed_delay_pct":float(np.expm1(against_delay.mean()/100)*100),
                "interval90_log_gain":interval(gain,dates),
                "interval90_vs_fixed_delay":interval(against_delay,dates),
                "p05_vs_dca_pct":float(np.quantile(qty/base-1,.05)*100),
                "mean_drawdown_pct":float(np.mean([v["drawdown"] for v in rr])*100),
                "mean_waiting_days":float(np.mean([v["waiting_days"] for v in rr]))}
    return out


def run(root=ROOT):
    root=Path(root)
    old=root/"buy_development_report.json"
    prior=json.loads(old.read_bytes())
    if prior["input_hashes"]!=HASHES or prior["test_numeric_values_parsed"] is not False:
        raise ValueError("Unexpected baseline report")
    markets={}
    for m in HASHES:
        print("Risk extension:",m,flush=True)
        p=load_development(root,m)
        sig,pred=replay(p,FIRST[m])
        rows=purchases(p,sig)
        if not pred or not rows:
            raise ValueError("Insufficient matched sample")
        markets[m]={"forecast_n":len(pred),"risk":assess(pred),
                    "purchase_n":len(rows),"cash0":purchase_summary(rows,"cash0"),
                    "cash5":purchase_summary(rows,"cash5"),
                    "predictions":pred}
    report={"protocol":"BUY-001-risk-extension-development-v1","test_numeric_values_parsed":False,
            "input_hashes":HASHES,"baseline_sha256":digest(old.read_bytes()),
            "markets":markets,"limitations":["M2 only probability targets, not conditional quantiles or variance.",
                "Development exploration; same historical episodes across exchanges.",
                "Fixed delay is an approximate exposure control, not exact matching of all waiting times.",
                "5% cash yield is hypothetical, not historical rates or actual broker terms.",
                "Intervals conditional on realized predictions and blocks, no formal significance claims."]}
    target=root/"buy_risk_extension_report.json"
    if target.exists():
        if json.loads(target.read_bytes())!=report:
            raise ValueError("Existing report differs; retain prior version")
    else:
        json_write(target,report)
    print("Send",target,flush=True)


if __name__=="__main__":
    run()
