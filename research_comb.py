"""COMB-001: registered matched valuation/derivatives follow-up, development only."""
import json
import math
from datetime import date
from pathlib import Path
import numpy as np

from binance_minute import digest,json_write
from research_buy import ROOT as PRICE_ROOT,HASHES,DEV_END,DAY,WEEK,mondays,window,outcome,load_development,simulate
from research_buy_risk import features,logistic,interval
from research_buy_audit import evaluate,model_control,contiguous,MIN_SHIFT
from research_value import ROOT as VALUE_ROOT,valuation
from research_oi import ROOT as OI_ROOT,FIRST,EVAL_START,oi_feature,load_funding,FUND_HASH
from research_fund import ROOT as FUND_ROOT,funding_feature,labels

ROOT=Path(__file__).resolve().parent/"data"/"research"/"comb_v1"
VERSION="COMB-001-development-v1"
VALUE_HASH="2066c92e0d9001ddfd57e3c887988f1efa0fbe572fa20a750cb86e1df6fbf1cb"
OI_HASH="c1d6295a30717177eacf981cb0f046d03003641638551700025a00085ab7b113"
MODELS={"L1":[0],"L1_value":[0,4],"L1_deriv":[0,5,6],"L1_all":[0,4,5,6],
        "M2":[0,1,2,3],"M2_value":[0,1,2,3,4]}
RULES=("L1","L1_value","L1_deriv","L1_all")
PAIRS=(("L1_all","L1_deriv"),("L1_all","L1"),("L1_all","L1_value"),
       ("L1_deriv","L1"),("L1_value","L1"),("M2_value","M2"),("L1_all","frequency"))


def pinned(path,want):
    raw=Path(path).read_bytes()
    if digest(raw)!=want:
        raise ValueError("Snapshot changed: "+str(path))
    return json.loads(raw)


def load_inputs(value_root=VALUE_ROOT,oi_root=OI_ROOT,fund_root=FUND_ROOT):
    v=pinned(Path(value_root)/"mvrv_development_snapshot.json",VALUE_HASH)["values"]
    o=pinned(Path(oi_root)/"oi_snapshot.json",OI_HASH)
    def positive_dates(data):
        out={}
        for k,v in data.items():
            t=date.fromisoformat(k)
            if t>=DEV_END or not isinstance(v,(int,float)) or not math.isfinite(v) or v<=0:
                raise ValueError("Invalid development observation")
            out[t]=float(v)
        return out
    return positive_dates(v),positive_dates(o),load_funding(fund_root)


def predict(history,x):
    h=history[-104:]
    X=np.array([r[0] for r in h])
    p={m:{} for m in (*MODELS,"frequency","coinflip")}
    for k in ("up","loss_15"):
        y=np.array([r[1][k] for r in h])
        p["frequency"][k]=float((1+y.sum())/(len(y)+2))
        p["coinflip"][k]=.5
        for m,cols in MODELS.items():
            p[m][k]=logistic(X[:,cols],y,x[cols])
    return p


def replay(prices,values,oi,funding,end=DEV_END):
    if end>DEV_END:
        raise ValueError("Final data are not permitted")
    pending=[];history=[];signals={};missing=[]
    prior={m:[] for m in RULES}
    for t in mondays(FIRST,end):
        while pending and pending[0][0]+29*DAY<=t-DAY:
            d,x=pending.pop(0)
            y=outcome(prices,d)
            if y is not None:
                history.append((x,labels(y)))
        f=features(prices,t);v=valuation(values,t);o=oi_feature(oi,t);r=funding_feature(funding,t)
        eligible=t>=EVAL_START and t+29*DAY<=end
        if f is None or any(z is None for z in (v,o,r)):
            if eligible:
                missing.append({"date":t.isoformat(),"reason":"incomplete input"})
            continue
        s,x0=f
        x=np.r_[x0,v,o,r]
        pending.append((t,x))
        if len(history)<52:
            if eligible:
                missing.append({"date":t.isoformat(),"reason":"insufficient completed labels"})
            continue
        p=predict(history,x)
        thresholds={m:float(np.quantile(prior[m][-104:],.8)) if len(prior[m])>=26 else None for m in RULES}
        signals[t]={"state":s,"pred":p,"thresholds":thresholds,"n_train":min(len(history),104),
                    "features":[float(z) for z in x]}
        for m in RULES:
            prior[m].append(p[m]["loss_15"])
    out=[]
    for t,s in signals.items():
        if not EVAL_START<=t or t+29*DAY>end:
            continue
        y=outcome(prices,t)
        if y is None:
            missing.append({"date":t.isoformat(),"reason":"incomplete outcome"})
            continue
        out.append({"date":t.isoformat(),"actual":labels(y),"pred":s["pred"],
                    "n_train":s["n_train"],"features":s["features"],"thresholds":s["thresholds"]})
    return signals,out,missing


def score(rows,with_intervals=True):
    if not rows:
        return {"n":0}
    dates=[date.fromisoformat(r["date"]) for r in rows]
    out={"n":len(rows)}
    for k in ("up","loss_15"):
        y=np.array([r["actual"][k] for r in rows])
        models={};loss={}
        for m in (*MODELS,"frequency","coinflip"):
            p=np.array([r["pred"][m][k] for r in rows])
            loss[m]=(p-y)**2
            models[m]={"brier":float(loss[m].mean()),
                       "log_score":float(-np.mean(y*np.log(p)+(1-y)*np.log1p(-p))),
                       "mean_probability":float(p.mean())}
        pairs={}
        for a,b in PAIRS:
            d=loss[a]-loss[b]
            pairs[a+"_minus_"+b]={"mean_brier_delta":float(d.mean())}
            if with_intervals:
                pairs[a+"_minus_"+b]["conditional_interval90"]=interval(d,dates)
        out[k]={"actual_frequency":float(y.mean()),"models":models,"comparisons":pairs}
    return out


def purchases(prices,signals,end=DEV_END):
    if end>DEV_END:
        raise ValueError("Final data are not permitted")
    mapped={m:{t:{**v["state"],"models":{"M1":{"p_loss_15":v["pred"][m]["loss_15"]}},
                       "thresholds":{.8:v["thresholds"][m]}}
               for t,v in signals.items() if v["thresholds"][m] is not None}
            for m in RULES}
    dates=[];skipped=[];op=[];cl=[];units={m:[] for m in (*RULES,"dca","lump")}
    for t in mondays(EVAL_START,end):
        if t+8*WEEK>=end:
            break
        x=window(prices,t,t+8*WEEK+DAY)
        r={m:simulate(prices,mapped[m],t,"risk") for m in RULES}
        if x is None or any(v is None for v in r.values()):
            skipped.append(t.isoformat())
            continue
        dates.append(t);op.append(x[:56:7,0]);cl.append(np.r_[x[:56,3],x[56,0]])
        for m,v in r.items():
            units[m].append(v["allocations"])
        units["dca"].append([1]*8);units["lump"].append([8]+[0]*7)
    if not dates:
        return {"n":0,"skipped":skipped,"reason":"No complete purchase episodes"}
    op=np.array(op);cl=np.array(cl);units={m:np.array(v) for m,v in units.items()}
    evals={m:evaluate(op,cl,u) for m,u in units.items()}
    dca=evals["dca"][0];out={}
    for m,(q,dd,wait) in evals.items():
        g=np.log(q/dca)*100
        out[m]={"geometric_gain_vs_dca_pct":float(np.expm1(g.mean()/100)*100),
                "conditional_interval90_log_gain":interval(g,dates),
                "mean_drawdown_pct":float(dd.mean()*100),
                "mean_waiting_days":float(wait.mean()),
                "p05_gain_vs_dca_pct":float(np.quantile(q/dca-1,.05)*100)}
    direct={}
    for b in ("L1","L1_deriv","L1_value","lump"):
        d=np.log(evals["L1_all"][0]/evals[b][0])*100
        direct["L1_all_minus_"+b]={"mean_log_gain_pct":float(d.mean()),"conditional_interval90":interval(d,dates)}
    controls={};reason=None
    if len(dates)<=2*MIN_SHIFT:
        reason="Too few eligible dates for rotations"
    elif any(b-a!=WEEK for a,b in zip(dates,dates[1:])):
        reason="Noncontiguous dates; do not compress missing weeks"
    else:
        contiguous(dates)
        controls={m:model_control(dates,op,cl,units[m]) for m in RULES}
    used=sorted({t+i*WEEK for t in dates for i in range(8)})
    return {"n":len(dates),"dates":[t.isoformat() for t in dates],"skipped":skipped,
            "rules":out,"direct":direct,"rotations":controls,"rotation_unavailable":reason,
            "trigger_rates":{m:float(np.mean([signals[t]["pred"][m]["loss_15"]>signals[t]["thresholds"][m] for t in used])) for m in RULES}}


def run(root=ROOT,price_root=PRICE_ROOT):
    root=Path(root)
    target=root/"comb_development_report.json"
    if target.exists():
        raise ValueError("Report already exists; preserve original")
    values,oi,funding=load_inputs()
    markets={}
    for m in HASHES:
        print("COMB development:",m,flush=True)
        prices=load_development(Path(price_root),m)
        signals,rows,missing=replay(prices,values,oi,funding)
        if not rows:
            raise ValueError("No matched forecasts")
        markets[m]={"summary":score(rows),"missing":missing,"first":rows[0]["date"],"last":rows[-1]["date"],
                    "by_year":{str(y):score([r for r in rows if r["date"].startswith(str(y))],False)
                               for y in range(EVAL_START.year,DEV_END.year)},
                    "purchases":purchases(prices,signals),"predictions":rows}
    report={"protocol":VERSION,"price_hashes":HASHES,"snapshot_hashes":{"value":VALUE_HASH,"oi":OI_HASH,"fund":FUND_HASH},
            "test_numeric_values_parsed":False,"markets":markets,
            "limitations":["Post-screening follow-up on reused development dates, not independent validation.",
                           "Different training window from VALUE-001, all models use same 104/52 matched labels.",
                           "Historical reconstructed MVRV and OI; original publication/units not fully verified.",
                           "One derivatives market; overlapping outcomes and few regimes; intervals conditional.",
                           "Purchase rotation ranks descriptive, not p-values; fixed waiting controls do not establish causality.",
                           "No parameter search, no deployment, no final-period evaluation."]}
    json_write(target,report)
    print("Send",target,flush=True)
    return report


if __name__=="__main__":
    run()
