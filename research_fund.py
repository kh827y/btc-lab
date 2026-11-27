"""FUND-001: settled Binance USD-M BTCUSDT funding, development-only."""
import csv
import io
import json
import math
import time
import zipfile
from datetime import date,datetime,timezone
from pathlib import Path

import numpy as np

from binance_minute import fetch,digest,expected_hash,atomic_write,json_write,ms,next_month
from research_buy import ROOT as PRICE_ROOT,DAY,DEV_END,HASHES,mondays,load_development,outcome
from research_buy_risk import features,logistic,interval

ROOT=Path(__file__).resolve().parent/"data"/"research"/"fund_v1"
BASE="https://data.binance.vision/data/futures/um/monthly/fundingRate/BTCUSDT/"
START=date(2020,1,1)
EVAL_START=date(2021,7,5)
STEP=8*3600*1000
LIMIT=1024*1024
VERSION="FUND-001-development-v1"
MODELS={"L1":[0],"L1_fund":[0,4],"M2":[0,1,2,3],"M2_fund":[0,1,2,3,4]}
PAIRS=(("L1_fund","L1"),("M2_fund","M2"),("L1_fund","frequency"),("L1_fund","coinflip"))


def month_name(a):
    return "BTCUSDT-fundingRate-"+a.isoformat()[:7]+".zip"


def parse_archive(raw,a,b):
    if not START<=a<b<=DEV_END or a.day!=1 or b!=next_month(a):
        raise ValueError("Invalid development month")
    result={};bad=[];seen=set()
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        entries=z.infolist()
        if len(entries)!=1 or entries[0].filename!=month_name(a)[:-4]+".csv" or entries[0].file_size>LIMIT:
            raise ValueError("Unexpected funding ZIP")
        with z.open(entries[0]) as member:
            reader=csv.reader(io.TextIOWrapper(member,encoding="utf-8-sig",newline=""))
            if next(reader,None)!=["calc_time","funding_interval_hours","last_funding_rate"]:
                raise ValueError("Unexpected funding CSV header")
            for row in reader:
                if len(row)!=3:
                    raise ValueError("Unexpected funding row")
                t=int(row[0]);hours=float(row[1]);rate=float(row[2])
                if not ms(a)<=t<ms(b) or t in seen or not math.isfinite(hours) or not math.isfinite(rate):
                    raise ValueError("Invalid timestamp/rate or duplicate")
                seen.add(t)
                # Slot is only for continuity checks, not the time of availability.
                # Accept a recorded settlement up to 60s after its scheduled 8h boundary.
                slot=t-t%STEP
                if hours!=8 or t-slot>60_000:
                    bad.append({"timestamp_ms":t,"reason":"nonstandard interval or settlement time"})
                    continue
                if slot in result:
                    raise ValueError("Duplicate scheduled settlement")
                result[slot]=(t,rate)
    return result,bad


def get_month(root,a,b,fetcher):
    name=month_name(a)
    path=root/"cache"/name
    meta=path.with_suffix(".json")
    url=BASE+name
    if path.exists() and meta.exists():
        raw=path.read_bytes();info=json.loads(meta.read_bytes())
        if info["url"]!=url or digest(raw)!=info["sha256"]:
            raise ValueError("Cached funding ZIP mismatch")
        rows,bad=parse_archive(raw,a,b)
        return rows,bad,info
    want=expected_hash(fetcher(url+".CHECKSUM",4096),name)
    raw=fetcher(url,LIMIT)
    if digest(raw)!=want:
        raise ValueError("Funding checksum mismatch")
    rows,bad=parse_archive(raw,a,b)
    info={"url":url,"sha256":want,"retrieved_utc":datetime.now(timezone.utc).isoformat()}
    atomic_write(path,raw);json_write(meta,info)
    return rows,bad,info


def collect(root=ROOT,fetcher=fetch):
    root=Path(root)
    combined={};months=[];errors=[];rejected=[];a=START
    while a<DEV_END:
        b=next_month(a)
        try:
            rows,bad,info=get_month(root,a,b,fetcher)
            if set(rows)&set(combined):
                raise ValueError("Overlapping funding months")
            combined.update(rows);rejected.extend(bad)
            months.append({"month":a.isoformat()[:7],"valid":len(rows),"expected":(ms(b)-ms(a))//STEP,**info})
            print("Funding",a.isoformat()[:7],len(rows),flush=True)
        except (OSError,ValueError,KeyError,TypeError,zipfile.BadZipFile) as e:
            errors.append({"month":a.isoformat()[:7],"reason":str(e)})
            print("Funding unavailable",a.isoformat()[:7],str(e),flush=True)
        a=b
        time.sleep(.1)
    expected=(ms(DEV_END)-ms(START))//STEP
    by_year={}
    for y in range(START.year,DEV_END.year):
        lo,hi=ms(date(y,1,1)),ms(date(y+1,1,1))
        by_year[str(y)]={"valid":sum(lo<=t<hi for t in combined),"expected":(hi-lo)//STEP}
    missing=[t for t in range(ms(START),ms(DEV_END),STEP) if t not in combined]
    snapshot={str(t):list(v) for t,v in sorted(combined.items())}
    info={"source":"Binance USD-M BTCUSDT perpetual settled funding",
          "valid":len(combined),"expected":expected,"by_year":by_year,"months":months,
          "errors":errors,"rejected":rejected,"missing_slots_utc_ms":missing,
          "coverage_gate":len(combined)>=.95*expected and all(v["valid"]>=.9*v["expected"] for v in by_year.values())}
    if info["coverage_gate"]:
        p=root/"funding_snapshot.json"
        if p.exists() and json.loads(p.read_bytes())!=snapshot:
            raise ValueError("Funding snapshot changed; retain original")
        if not p.exists():
            json_write(p,snapshot)
        info["snapshot_sha256"]=digest(p.read_bytes())
    json_write(root/"coverage.json",info)
    if not info["coverage_gate"]:
        raise ValueError("Funding coverage insufficient; send coverage.json")
    return combined,info


def funding_feature(rows,t):
    # Sunday 00 UTC cutoff; all 21 completed scheduled settlements from
    # previous Sunday 00 through Saturday 16 UTC, using actual timestamps.
    end=ms(t-DAY);start=end-21*STEP
    r=[rows.get(s) for s in range(start,end,STEP)]
    if len(r)!=21 or any(v is None or not start<=v[0]<end for v in r):
        return None
    return float(np.mean([v[1] for v in r]))


def labels(y):
    return {"up":int(y["log_return"]>0),"loss_15":int(y["log_worst"]<=math.log(.85))}


def predict(history,x):
    h=history[-104:]
    X=np.array([r[0] for r in h])
    result={m:{} for m in (*MODELS,"frequency","coinflip")}
    for k in ("up","loss_15"):
        y=np.array([r[1][k] for r in h])
        result["frequency"][k]=float((1+y.sum())/(len(y)+2))
        result["coinflip"][k]=.5
        for m,cols in MODELS.items():
            result[m][k]=logistic(X[:,cols],y,x[cols])
    return result


def replay(prices,rows,end=DEV_END):
    if end>DEV_END:
        raise ValueError("Final data are not permitted")
    pending=[];history=[];pred={};missing=[]
    for t in mondays(START,end):
        while pending and pending[0][0]+29*DAY<=t-DAY:
            d,x=pending.pop(0)
            y=outcome(prices,d)
            if y is not None:
                history.append((x,labels(y)))
        f=features(prices,t);v=funding_feature(rows,t)
        eligible=t>=EVAL_START and t+29*DAY<=end
        if f is None or v is None:
            if eligible:
                missing.append({"date":t.isoformat(),"reason":"missing input"})
            continue
        x=np.r_[f[1],v]
        pending.append((t,x))
        if not eligible:
            continue
        if len(history)<52:
            missing.append({"date":t.isoformat(),"reason":"insufficient completed labels"})
            continue
        pred[t]={"mean_funding_8h":v,"n_train":min(len(history),104),"pred":predict(history,x)}
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


def run(root=ROOT,price_root=PRICE_ROOT,fetcher=fetch):
    root=Path(root)
    target=root/"fund_development_report.json"
    if target.exists():
        raise ValueError("Report already exists; preserve original")
    funding,quality=collect(root,fetcher)
    markets={}
    for m in HASHES:
        print("FUND development:",m,flush=True)
        prices=load_development(Path(price_root),m)
        rows,missing=replay(prices,funding)
        if not rows:
            raise ValueError("No matched funding forecasts")
        markets[m]={"summary":score(rows),"first":rows[0]["date"],"last":rows[-1]["date"],
                    "missing":missing,"by_year":{str(y):score([r for r in rows if r["date"].startswith(str(y))],False)
                     for y in range(EVAL_START.year,DEV_END.year)},"predictions":rows}
    report={"protocol":VERSION,"price_hashes":HASHES,"quality":quality,
            "test_numeric_values_parsed":False,"markets":markets,
            "limitations":["One USD-M perpetual market, not aggregate leverage, open interest or liquidation risk.",
                "Historical archive checksums verify today's files, not original publication/revisions.",
                "Only complete 8-hour settlement weeks; no interpolation.",
                "Short development sample and overlapping 28d outcomes; descriptive intervals, not significance tests.",
                "2024+ already evaluated for other hypotheses, not pristine holdout. No trading or parameter optimization."]}
    json_write(target,report)
    print("Send",target,flush=True)


if __name__=="__main__":
    run()
