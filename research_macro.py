"""MACRO-001: real yield and broad USD changes, development reconstruction only."""
import csv
import io
import json
import math
import time
from datetime import date,datetime,timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request,urlopen

import numpy as np

from binance_minute import digest,atomic_write,json_write
from research_buy import ROOT as PRICE_ROOT,DAY,DEV_END,HASHES,mondays,load_development,outcome,days
from research_buy_risk import features,logistic,interval
from research_fund import labels

ROOT=Path(__file__).resolve().parent/"data"/"research"/"macro_v1"
START=date(2019,2,4)
EVAL_START=date(2020,7,6)
SERIES=("DFII10","DTWEXBGS")
VERSION="MACRO-001-development-v1"
FALLBACK_VINTAGE=date(2026,11,25)
MODELS={"L1":[0],"L1_yield":[0,4],"L1_usd":[0,5],"L1_macro":[0,4,5],
        "M2":[0,1,2,3],"M2_macro":[0,1,2,3,4,5]}
PAIRS=(("L1_macro","L1"),("L1_yield","L1"),("L1_usd","L1"),("M2_macro","M2"),
       ("L1_macro","frequency"),("L1_macro","coinflip"))


def url(series):
    if series not in SERIES:
        raise ValueError("Unknown macro series")
    return "https://fred.stlouisfed.org/graph/fredgraph.csv?"+urlencode({
        "id":series,"cosd":START.isoformat(),"coed":(DEV_END-DAY).isoformat()})


def alternate_url(series):
    if series not in SERIES:
        raise ValueError("Unknown macro series")
    return "https://alfred.stlouisfed.org/graph/alfredgraph.csv?"+urlencode({
        "id":series,"vintage_date":FALLBACK_VINTAGE.isoformat(),
        "cosd":START.isoformat(),"coed":(DEV_END-DAY).isoformat()})


def download(address,limit=1024*1024):
    with urlopen(Request(address,headers={"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64)","Accept":"text/csv, */*;q=0.5"}),timeout=30) as r:
        raw=r.read(limit+1)
    if len(raw)>limit:
        raise ValueError("Macro CSV exceeds limit")
    return raw


def parse(raw,series,source="fred"):
    if series not in SERIES:
        raise ValueError("Unknown macro series")
    reader=csv.reader(io.StringIO(raw.decode("utf-8-sig")))
    header=next(reader,None)
    column=series if source=="fred" else series+"_"+FALLBACK_VINTAGE.strftime("%Y%m%d")
    if source not in ("fred","alfred") or header not in (["observation_date",column],["DATE",column]):
        raise ValueError("Unexpected FRED/ALFRED header: "+str(header))
    values={};missing=[];seen=set();last=None
    for row in reader:
        if len(row)!=2:
            raise ValueError("Unexpected FRED row")
        t=date.fromisoformat(row[0])
        if row[0]!=t.isoformat() or not START<=t<DEV_END:
            raise ValueError("FRED date outside requested development range")
        if t in seen or last is not None and t<=last:
            raise ValueError("Duplicate/unordered FRED dates")
        last=t;seen.add(t)
        if row[1].strip() in ("","."):
            missing.append(t.isoformat())
            continue
        v=float(row[1])
        if not math.isfinite(v) or (series=="DTWEXBGS" and v<=0):
            raise ValueError("Invalid FRED observation")
        values[t]=v
    if not values:
        raise ValueError("No macro values")
    expected=[d for d in days(START,DEV_END) if d.weekday()<5]
    by_year={}
    for d in expected:
        y=by_year.setdefault(str(d.year),{"weekdays":0,"valid":0})
        y["weekdays"]+=1;y["valid"]+=int(d in values)
    info={"valid":len(values),"missing_markers":missing,"first":min(values).isoformat(),
          "last":max(values).isoformat(),"by_year":by_year,
          "missing_weekdays":[d.isoformat() for d in expected if d not in values],
          "coverage_gate":all(y["valid"]>=.90*y["weekdays"] for y in by_year.values())}
    return values,info


def obtain(root,s,fetcher):
    errors=[]
    # Manual import only from an explicitly named official CSV, never from an
    # unlabelled file. Keep the original bytes; manual provenance is asserted,
    # not independently verified.
    for source, address, filename in (
            ("fred",url(s),s+".csv"),
            ("alfred",alternate_url(s),s+"_"+FALLBACK_VINTAGE.strftime("%Y%m%d")+".csv")):
        manual=root/"manual"/filename
        if manual.exists():
            raw=manual.read_bytes()
            if len(raw)>1024*1024:
                raise ValueError("Manual CSV exceeds limit")
            _,q=parse(raw,s,source)
            if not q["coverage_gate"]:
                raise ValueError("Manual CSV coverage insufficient: "+filename)
            return raw,{"url":address,"source":source,"sha256":digest(raw),
                        "retrieved_utc":None,"imported_utc":datetime.now(timezone.utc).isoformat(),
                        "manual_import":True,"manual_filename":filename,"failed_attempts":errors}
    for source,address in (("fred",url(s)),("alfred",alternate_url(s)),("fred",url(s))):
        print("Download",s,source,flush=True)
        try:
            raw=fetcher(address)
            if len(raw)>1024*1024:
                raise ValueError("Macro CSV exceeds limit")
            _,q=parse(raw,s,source)
            if not q["coverage_gate"]:
                raise ValueError("Insufficient weekday coverage")
            return raw,{"url":address,"source":source,"sha256":digest(raw),
                        "retrieved_utc":datetime.now(timezone.utc).isoformat(),
                        "manual_import":False,"failed_attempts":errors}
        except (OSError,ValueError) as e:
            errors.append({"source":source,"url":address,"error":str(e)})
            print("Unavailable",s,source,str(e),flush=True)
            time.sleep(1)
    return None,{"errors":errors,"coverage_gate":False,
                 "manual_urls":{"fred":url(s),"alfred":alternate_url(s)}}


def collect(root=ROOT,fetcher=download):
    root=Path(root);data={};quality={}
    for s in SERIES:
        path=root/"cache"/(s+".csv")
        meta=path.with_suffix(".json")
        if path.exists() and meta.exists():
            raw=path.read_bytes();info=json.loads(meta.read_bytes())
            source=info.get("source","fred")
            allowed={"fred":url(s),"alfred":alternate_url(s)}
            if info["url"]!=allowed.get(source) or info["sha256"]!=digest(raw):
                raise ValueError("Cached FRED data changed")
        elif path.exists() or meta.exists():
            raise ValueError("Incomplete macro cache pair: "+s)
        else:
            raw,info=obtain(root,s,fetcher)
            if raw is None:
                quality[s]=info
                continue
            atomic_write(path,raw);json_write(meta,info)
        data[s],q=parse(raw,s,info.get("source","fred"))
        quality[s]={**info,**q}
    json_write(root/"coverage.json",quality)
    if not all(q["coverage_gate"] for q in quality.values()):
        print("If automatic downloads failed, use the official CSV links in coverage.json.",flush=True)
        print("Save the CSVs under",root/"manual",flush=True)
        print("Names: DFII10.csv / DTWEXBGS.csv (FRED); or DFII10_20261125.csv / DTWEXBGS_20261125.csv (ALFRED).",flush=True)
        raise ValueError("Macro coverage insufficient; send coverage.json")
    return data,quality


def latest(values,t):
    # Weekend/holiday handling only: not an unbounded fill.
    for i in range(5):
        d=t-i*DAY
        if d in values:
            return values[d]
    return None


def macro_feature(data,t,lag=10):
    if lag not in (10,17):
        raise ValueError("Unregistered macro lag")
    # Monday origin, use Friday of the PREVIOUS business week before decision.
    # H.10 publishes the previous business week on Monday (holiday: next day).
    a=t-lag*DAY;b=a-28*DAY
    y1=latest(data["DFII10"],a);y0=latest(data["DFII10"],b)
    u1=latest(data["DTWEXBGS"],a);u0=latest(data["DTWEXBGS"],b)
    if any(v is None for v in (y1,y0,u1,u0)):
        return None
    return np.array([y1-y0,math.log(u1/u0)])


def predict(history,x):
    h=history[-104:]
    X=np.array([r[0] for r in h])
    out={m:{} for m in (*MODELS,"frequency","coinflip")}
    for k in ("up","loss_15"):
        y=np.array([r[1][k] for r in h])
        out["frequency"][k]=float((1+y.sum())/(len(y)+2))
        out["coinflip"][k]=.5
        for m,cols in MODELS.items():
            out[m][k]=logistic(X[:,cols],y,x[cols])
    return out


def replay(prices,data,end=DEV_END,lag=10):
    if end>DEV_END:
        raise ValueError("Final data are not permitted")
    pending=[];history=[];pred={};missing=[]
    for t in mondays(START,end):
        while pending and pending[0][0]+29*DAY<=t-DAY:
            d,x=pending.pop(0)
            y=outcome(prices,d)
            if y is not None:
                history.append((x,labels(y)))
        f=features(prices,t);v=macro_feature(data,t,lag)
        eligible=t>=EVAL_START and t+29*DAY<=end
        if f is None or v is None:
            if eligible:
                missing.append({"date":t.isoformat(),"reason":"missing features"})
            continue
        x=np.r_[f[1],v]
        pending.append((t,x))
        if not eligible:
            continue
        if len(history)<52:
            missing.append({"date":t.isoformat(),"reason":"insufficient completed labels"})
            continue
        pred[t]={"real_yield_change_pp":float(v[0]),"usd_log_change":float(v[1]),
                 "n_train":min(len(history),104),"pred":predict(history,x)}
    out=[]
    for t,r in pred.items():
        y=outcome(prices,t)
        if y is None:
            missing.append({"date":t.isoformat(),"reason":"missing outcome"})
            continue
        out.append({"date":t.isoformat(),"actual":labels(y),**r})
    return out,missing


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


def run(root=ROOT,price_root=PRICE_ROOT,fetcher=download):
    root=Path(root)
    target=root/"macro_development_report.json"
    if target.exists():
        raise ValueError("Report already exists; preserve original")
    data,quality=collect(root,fetcher)
    markets={}
    for m in HASHES:
        print("MACRO development:",m,flush=True)
        p=load_development(Path(price_root),m)
        a,am=replay(p,data);b,bm=replay(p,data,lag=17)
        if not a or not b:
            raise ValueError("No matched macro forecasts; send coverage.json")
        common={r["date"] for r in a}&{r["date"] for r in b}
        if not common:
            raise ValueError("No common dates for lag sensitivity")
        markets[m]={"summary":score(a),"first":a[0]["date"],"last":a[-1]["date"],
                    "missing":am,"lag17_missing":bm,
                    "lag10_common":score([r for r in a if r["date"] in common]),
                    "lag17_common":score([r for r in b if r["date"] in common]),
                    "by_year":{str(y):score([r for r in a if r["date"].startswith(str(y))],False)
                               for y in range(EVAL_START.year,DEV_END.year)},
                    "predictions":a}
    report={"protocol":VERSION,"price_hashes":HASHES,"quality":quality,
            "test_numeric_values_parsed":False,"markets":markets,
            "limitations":["Current FRED snapshot, not original ALFRED vintages; revisions may affect results.",
                           "H.10 publication lag addressed conservatively but historic release dates not verified.",
                           "Broad dollar methodology introduced February 2019; earlier retrospective data excluded.",
                           "Changes are not monetary shocks or causal evidence; yield/USD are endogenous.",
                           "Overlapping outcomes and few market cycles; conditional intervals not calibrated.",
                           "No parameter search, no trade recommendations, no new pristine holdout."]}
    json_write(target,report)
    print("Send",target,flush=True)
    return report


if __name__=="__main__":
    run()
