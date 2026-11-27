"""VALUE-001: historical MVRV reconstruction, development only."""
import json
import math
from datetime import date
from pathlib import Path
import numpy as np

from binance_minute import digest,json_write
from extended_history import DATA
from research_buy import ROOT as PRICE_ROOT,DAY,DEV_END,FIRST,HASHES,days,mondays,outcome,load_development
from research_buy_risk import features,logistic,interval

ROOT=Path(__file__).resolve().parent/"data"/"research"/"value_v1"
SOURCE=DATA/"kote-mvrv.json"
VERSION="VALUE-001-development-v1"
START=date(2019,1,7)
HORIZONS=(28,90)
MODELS={"L1":[0],"L1_value":[0,4],"M2":[0,1,2,3],"M2_value":[0,1,2,3,4]}
PAIRS=(("L1_value","L1"),("M2_value","M2"),("L1_value","frequency"),("L1_value","coinflip"))
MIN_TRAIN=104
MAX_TRAIN=156


def load_values(path):
    raw=Path(path).read_bytes()
    d=json.loads(raw)
    if d.get("schema")!=1 or d.get("source")!="Kote Charts" or d.get("chart")!="mvrv" or set(d["series"])!={"mvrv"}:
        raise ValueError("Wrong MVRV archive")
    values={};rejected=[]
    for k,v in d["series"]["mvrv"].items():
        t=date.fromisoformat(k)
        if t.isoformat()!=k:
            raise ValueError("Invalid date")
        if t>=DEV_END:
            continue
        if type(v) not in (int,float) or not math.isfinite(v) or v<=0:
            rejected.append(k)
        else:
            values[t]=float(v)
    if not values:
        raise ValueError("No positive MVRV values")
    first=date(2014,1,1)
    expected=(DEV_END-first).days
    absent=[t.isoformat() for t in days(first,DEV_END) if t not in values]
    info={"source":"Kote Charts MVRV","source_sha256":digest(raw),
          "downloaded_utc":d.get("downloaded_utc"),"first_valid":min(values).isoformat(),
          "last_valid":max(values).isoformat(),"valid_2014_2023":expected-len(absent),
          "expected_2014_2023":expected,"missing_2014_2023":absent,"rejected":sorted(rejected),
          "attribution":"https://kotecharts.com/c/mvrv","vintage_verified":False}
    return values,info


def valuation(values,t,lag=3):
    # Sunday 00 UTC cutoff. Friday (t-3) has been closed for 24h.
    # Exact date, no stale carry-forward. Lag is a conservative assumption.
    v=values.get(t-lag*DAY)
    return None if v is None else math.log(v)


def labels(y):
    return {"up":int(y["log_return"]>0),"loss_15":int(y["log_worst"]<=math.log(.85))}


def predict(history,x):
    h=history[-MAX_TRAIN:]
    X=np.array([r[0] for r in h])
    result={m:{} for m in (*MODELS,"frequency","coinflip")}
    for k in ("up","loss_15"):
        y=np.array([r[1][k] for r in h])
        result["frequency"][k]=float((1+y.sum())/(len(y)+2))
        result["coinflip"][k]=.5
        for m,cols in MODELS.items():
            result[m][k]=logistic(X[:,cols],y,x[cols])
    return result


def replay(prices,values,first,h,end=DEV_END,lag=3):
    if end>DEV_END or h not in HORIZONS or lag not in (3,8):
        raise ValueError("Invalid research range")
    pending=[];history=[];pred={};missing=[]
    for t in mondays(first,end):
        while pending and pending[0][0]+(h+1)*DAY<=t-DAY:
            d,x=pending.pop(0)
            y=outcome(prices,d,h)
            if y is not None:
                history.append((x,labels(y)))
        f=features(prices,t);v=valuation(values,t,lag)
        eligible=t>=START and t+(h+1)*DAY<=end
        if f is None or v is None:
            if eligible:
                missing.append({"date":t.isoformat(),"reason":"missing input"})
            continue
        x=np.r_[f[1],v]
        pending.append((t,x))
        if not eligible:
            continue
        if len(history)<MIN_TRAIN:
            missing.append({"date":t.isoformat(),"reason":"insufficient completed labels"})
            continue
        pred[t]={"mvrv":math.exp(v),"n_train":min(len(history),MAX_TRAIN),"pred":predict(history,x)}
    rows=[]
    for t,r in pred.items():
        y=outcome(prices,t,h)
        if y is None:
            missing.append({"date":t.isoformat(),"reason":"missing outcome"})
            continue
        rows.append({"date":t.isoformat(),"actual":labels(y),
                     "return":math.expm1(y["log_return"]),"worst":math.expm1(y["log_worst"]),**r})
    return rows,missing


def score(rows,intervals=True):
    if not rows:
        return {"n":0}
    dates=[date.fromisoformat(r["date"]) for r in rows]
    result={"n":len(rows)}
    for k in ("up","loss_15"):
        y=np.array([r["actual"][k] for r in rows])
        losses={};models={}
        for m in (*MODELS,"frequency","coinflip"):
            p=np.array([r["pred"][m][k] for r in rows])
            losses[m]=(p-y)**2
            models[m]={"brier":float(losses[m].mean()),
                       "log_score":float(-np.mean(y*np.log(p)+(1-y)*np.log1p(-p))),
                       "mean_probability":float(p.mean())}
        deltas={}
        for a,b in PAIRS:
            d=losses[a]-losses[b]
            deltas[a+"_minus_"+b]={"mean_brier_delta":float(d.mean())}
            if intervals:
                deltas[a+"_minus_"+b]["conditional_interval90"]=interval(d,dates)
        result[k]={"actual_frequency":float(y.mean()),"models":models,"comparisons":deltas}
    return result


def bands(rows):
    # Fixed valuation bands, descriptive, no strategy or optimal threshold.
    out={}
    for name,lo,hi in (("below_1",0,1),("1_to_2_5",1,2.5),("at_least_2_5",2.5,float("inf"))):
        a=[r for r in rows if lo<=r["mvrv"]<hi]
        out[name]={"n":len(a)}
        if a:
            ret=np.array([r["return"] for r in a])
            out[name].update({"mean_return_pct":float(ret.mean()*100),
                              "median_return_pct":float(np.median(ret)*100),
                              "p05_return_pct":float(np.quantile(ret,.05)*100),
                              "up_frequency":float(np.mean([r["actual"]["up"] for r in a])),
                              "loss_15_frequency":float(np.mean([r["actual"]["loss_15"] for r in a]))})
    return out


def run(root=ROOT,source=SOURCE,price_root=PRICE_ROOT):
    root=Path(root)
    target=root/"value_development_report.json"
    if target.exists():
        raise ValueError("Report already exists; preserve original")
    values,quality=load_values(source)
    snapshot={"source_sha256":quality["source_sha256"],
              "values":{t.isoformat():v for t,v in sorted(values.items())}}
    path=root/"mvrv_development_snapshot.json"
    if path.exists():
        if json.loads(path.read_bytes())!=snapshot:
            raise ValueError("MVRV snapshot differs; retain original")
    else:
        json_write(path,snapshot)
    quality["snapshot_sha256"]=digest(path.read_bytes())
    json_write(root/"coverage.json",quality)
    if quality["valid_2014_2023"]<.95*quality["expected_2014_2023"]:
        raise ValueError("MVRV history coverage inadequate; send coverage.json")
    markets={}
    for m in HASHES:
        print("VALUE development:",m,flush=True)
        prices=load_development(Path(price_root),m)
        result={}
        for h in HORIZONS:
            a,am=replay(prices,values,FIRST[m],h)
            b,bm=replay(prices,values,FIRST[m],h,lag=8)
            if not a or not b:
                raise ValueError("No matched MVRV forecasts")
            common=set(r["date"] for r in a)&set(r["date"] for r in b)
            result[str(h)]={"primary_lag3":score(a),"missing":am,
                            "valuation_bands":bands(a),
                            "lag8_common":score([r for r in b if r["date"] in common]),
                            "lag3_common":score([r for r in a if r["date"] in common]),
                            "lag8_missing":bm,
                            "by_year":{str(y):score([r for r in a if r["date"].startswith(str(y))],False)
                                       for y in range(START.year,DEV_END.year)},
                            "predictions":a}
        markets[m]=result
    report={"protocol":VERSION,"price_hashes":HASHES,"quality":quality,
            "test_numeric_values_parsed":False,"markets":markets,
            "limitations":["Historical reconstruction of Kote MVRV; initial publication and revisions unverified.",
                "3/8-day offsets are assumed availability safeguards, not vintage proof.",
                "90-day overlapping labels, few independent cycles; conditional intervals descriptive.",
                "Both exchanges share valuation data and market episodes.",
                "MVRV contains current market price, does not measure intrinsic value.",
                "Valuation bands descriptive, not trading rules; no parameter search.",
                "2024+ already used by earlier research, not pristine holdout."]}
    json_write(target,report)
    print("Send",target,flush=True)


if __name__=="__main__":
    run()
