"""OI-001: weekly Binance USD-M open interest reconstruction."""
import csv
import io
import json
import math
import time
import zipfile
from datetime import date,datetime,timezone
from pathlib import Path

import numpy as np

from binance_minute import fetch,digest,expected_hash,atomic_write,json_write
from research_buy import ROOT as PRICE_ROOT,DAY,WEEK,DEV_END,HASHES,mondays,load_development,outcome
from research_buy_risk import features,logistic,interval
from research_fund import ROOT as FUND_ROOT,funding_feature,labels

ROOT=Path(__file__).resolve().parent/"data"/"research"/"oi_v1"
BASE="https://data.binance.vision/data/futures/um/daily/metrics/BTCUSDT/"
FIRST=date(2020,9,4)
EVAL_START=date(2022,4,4)
LIMIT=2*1024*1024
VERSION="OI-001-development-v1"
FUND_HASH="80b2346eebc93691361d025f9eb113462b58f0e7c6431344a5609668db030d5e"
MODELS={"L1":[0],"L1_oi":[0,4],"L1_fund":[0,5],"L1_oi_fund":[0,4,5],
        "M2":[0,1,2,3],"M2_oi":[0,1,2,3,4],"M2_oi_fund":[0,1,2,3,4,5]}
PAIRS=(("L1_oi","L1"),("L1_oi_fund","L1_fund"),("L1_oi_fund","L1_oi"),
       ("M2_oi","M2"),("M2_oi_fund","M2_oi"),("L1_oi_fund","frequency"))


def friday_dates():
    d=FIRST
    while d<DEV_END:
        yield d
        d+=WEEK


def name(d):
    return "BTCUSDT-metrics-"+d.isoformat()+".zip"


def parse_archive(raw,d):
    """Use Friday's explicitly timed last snapshot near end of day.
    Accept a sole date-only row separately, with uncertain timing flagged.
    Never use Sunday data or shift the observation date.
    """
    if not FIRST<=d<DEV_END or d.weekday()!=4:
        raise ValueError("Invalid Friday")
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        es=z.infolist()
        if len(es)!=1 or es[0].filename!=name(d)[:-4]+".csv" or es[0].file_size>LIMIT:
            raise ValueError("Unexpected metrics ZIP")
        with z.open(es[0]) as f:
            reader=csv.DictReader(io.TextIOWrapper(f,encoding="utf-8-sig",newline=""))
            required={"create_time","symbol","sum_open_interest","sum_open_interest_value"}
            if not required<=set(reader.fieldnames or []) or len(set(reader.fieldnames))!=len(reader.fieldnames):
                raise ValueError("Unexpected metrics header")
            rows=list(reader)
    if not rows or len(rows)>10000:
        raise ValueError(f"Unexpected metrics row count: {len(rows)}")
    # The ZIP byte limit remains in force. Older archives can have a denser
    # sampling cadence; row count alone says nothing about the Friday close.
    seen={};eligible={};invalid=0;duplicates=0;conflicts=set()
    for r in rows:
        s=r["create_time"]
        if r["symbol"]!="BTCUSDT":
            raise ValueError("Wrong contract")
        if len(s)==10:
            if len(rows)!=1 or s!=d.isoformat():
                raise ValueError("Ambiguous date-only row")
            stamp=None
        else:
            stamp=datetime.fromisoformat(s.replace("Z","+00:00"))
            if stamp.tzinfo is None:
                stamp=stamp.replace(tzinfo=timezone.utc)
            stamp=stamp.astimezone(timezone.utc)
            if stamp.date()!=d:
                raise ValueError("Timestamp outside archive date")
        try:
            q=float(r["sum_open_interest"]);v=float(r["sum_open_interest_value"])
        except (ValueError,TypeError):
            q=v=None
        pair=(q,v) if q is not None and all(math.isfinite(x) and x>0 for x in (q,v)) else None
        if pair is None:
            invalid+=1
        if stamp in seen:
            duplicates+=1
            if seen[stamp]!=pair:
                conflicts.add(stamp)
        else:
            seen[stamp]=pair
        if pair is not None and (stamp is None or (stamp.hour==23 and stamp.minute>=45)):
            eligible[stamp]=pair
    if not eligible:
        raise ValueError("No positive OI snapshot in final 15 minutes")
    stamp=max(eligible,key=lambda s:s or datetime.min.replace(tzinfo=timezone.utc))
    # Do not pick a conflicting value or silently fall back to an earlier time.
    if stamp in conflicts:
        raise ValueError("Conflicting OI values at selected timestamp: "+str(stamp))
    q,v=eligible[stamp]
    return {"date":d.isoformat(),"timestamp":stamp.isoformat() if stamp else None,
            "quantity":q,"notional":v,"invalid_rows":invalid,"rows":len(rows),
            "duplicate_rows":duplicates,"conflicting_timestamps":len(conflicts)}


def get_archive(root,d,fetcher):
    fn=name(d);url=BASE+fn
    p=root/"cache"/fn;meta=p.with_suffix(".json")
    if p.exists() and meta.exists():
        raw=p.read_bytes();info=json.loads(meta.read_bytes())
        if info["url"]!=url or digest(raw)!=info["sha256"]:
            raise ValueError("Cached OI ZIP mismatch")
    else:
        want=expected_hash(fetcher(url+".CHECKSUM",4096),fn)
        raw=fetcher(url,LIMIT)
        if digest(raw)!=want:
            raise ValueError("OI checksum mismatch")
        # Retain checksum-verified source bytes even if schema validation fails.
        # Never use them for research until parse_archive and unit_check pass.
        info={"url":url,"sha256":want,"retrieved_utc":datetime.now(timezone.utc).isoformat()}
        atomic_write(p,raw);json_write(meta,info)
    return parse_archive(raw,d),info


def unit_check(row,price):
    # Not a proof of contractual unit history. Reject large unit mismatches.
    implied=row["notional"]/row["quantity"]
    return .9*price[2]<=implied<=1.1*price[1]


def collect(root,prices,fetcher=fetch):
    result={};errors=[];files=[];date_only=[]
    prior_path=root/"coverage.json"
    original=root/"coverage_before_parser_repair.json"
    if prior_path.exists() and not original.exists():
        prior=json.loads(prior_path.read_bytes())
        if prior.get("coverage_gate") is False:
            atomic_write(original,prior_path.read_bytes())
    prior_valid={}
    if original.exists():
        prior_valid={r["date"]:r for r in json.loads(original.read_bytes())["files"]}
    dates=list(friday_dates())
    for d in dates:
        try:
            row,info=get_archive(root,d,fetcher)
            if d not in prices or not unit_check(row,prices[d]):
                raise ValueError("Implied OI valuation outside BTC daily range +/-10%")
            old=prior_valid.get(d.isoformat())
            if old is not None and any(old[k]!=row[k] for k in ("timestamp","quantity","notional")):
                raise ValueError("Previously accepted observation changed")
            result[d]=row["quantity"]
            if row["timestamp"] is None:
                date_only.append(d.isoformat())
            files.append({**row,**info})
        except (OSError,ValueError,TypeError,KeyError,zipfile.BadZipFile) as e:
            errors.append({"date":d.isoformat(),"reason":str(e)})
        if len(files)%20==0 or d==dates[-1]:
            print("OI:",d,len(files),"valid,",len(errors),"rejected",flush=True)
        time.sleep(.1)
    quality={"source":"Binance BTCUSDT USD-M daily metrics; Friday observations",
             "expected":len(dates),"valid":len(result),"files":files,"errors":errors,
             "date_only":date_only,"coverage_gate":len(result)>=.90*len(dates),
             "parser_revision":2,"previously_valid":len(prior_valid),
             "previously_valid_retained":sum(d.isoformat() in prior_valid for d in result)}
    p=root/"oi_snapshot.json"
    snapshot={d.isoformat():v for d,v in sorted(result.items())}
    if quality["coverage_gate"]:
        if p.exists() and json.loads(p.read_bytes())!=snapshot:
            raise ValueError("OI snapshot changed; retain original")
        if not p.exists():
            json_write(p,snapshot)
        quality["snapshot_sha256"]=digest(p.read_bytes())
    json_write(root/"coverage.json",quality)
    if not quality["coverage_gate"]:
        raise ValueError("OI coverage insufficient; send coverage.json")
    return result,quality


def oi_feature(oi,t):
    # Last Friday is t-3. Previous 13 exact Fridays, no stale carry.
    d=t-3*DAY
    v=[oi.get(d-i*WEEK) for i in range(14)]
    if any(x is None or not math.isfinite(x) or x<=0 for x in v):
        return None
    return float(math.log(v[0]/np.median(v[1:])))


def load_funding(root=FUND_ROOT):
    raw=(Path(root)/"funding_snapshot.json").read_bytes()
    if digest(raw)!=FUND_HASH:
        raise ValueError("Funding snapshot mismatch")
    return {int(k):tuple(v) for k,v in json.loads(raw).items()}


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


def replay(prices,oi,funding,end=DEV_END):
    if end>DEV_END:
        raise ValueError("Final data are not permitted")
    pending=[];history=[];pred={};missing=[]
    for t in mondays(FIRST,end):
        while pending and pending[0][0]+29*DAY<=t-DAY:
            d,x=pending.pop(0)
            y=outcome(prices,d)
            if y is not None:
                history.append((x,labels(y)))
        f=features(prices,t);v=oi_feature(oi,t);r=funding_feature(funding,t)
        eligible=t>=EVAL_START and t+29*DAY<=end
        if f is None or v is None or r is None:
            if eligible:
                missing.append({"date":t.isoformat(),"reason":"incomplete input"})
            continue
        x=np.r_[f[1],v,r]
        pending.append((t,x))
        if not eligible:
            continue
        if len(history)<52:
            missing.append({"date":t.isoformat(),"reason":"insufficient completed training labels"})
            continue
        pred[t]={"oi_relative_log":v,"mean_funding_8h":r,
                 "n_train":min(len(history),104),"pred":predict(history,x)}
    out=[]
    for t,r in pred.items():
        y=outcome(prices,t)
        if y is None:
            missing.append({"date":t.isoformat(),"reason":"incomplete outcome"})
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


def run(root=ROOT,price_root=PRICE_ROOT,fund_root=FUND_ROOT,fetcher=fetch):
    root=Path(root)
    target=root/"oi_development_report.json"
    if target.exists():
        raise ValueError("Report already exists")
    funding=load_funding(fund_root)
    p=load_development(Path(price_root),"bitstamp")
    oi,quality=collect(root,p,fetcher)
    markets={}
    for m in HASHES:
        prices=p if m=="bitstamp" else load_development(Path(price_root),m)
        rows,missing=replay(prices,oi,funding)
        if not rows:
            raise ValueError("No matched OI forecasts; send coverage.json")
        markets[m]={"summary":score(rows),"first":rows[0]["date"],"last":rows[-1]["date"],
                    "missing":missing,"by_year":{str(y):score([r for r in rows if r["date"].startswith(str(y))],False)
                          for y in range(EVAL_START.year,DEV_END.year)},"predictions":rows}
    report={"protocol":VERSION,"price_hashes":HASHES,"funding_snapshot_sha256":FUND_HASH,
            "quality":quality,"test_numeric_values_parsed":False,"markets":markets,
            "limitations":["Single perpetual, OI quantity not trader leverage or net directional exposure.",
                "Implied valuation check supports but cannot prove historical unit conventions.",
                "Historical reconstruction, original publication and timestamp convention not proven.",
                "Friday cutoff buffer, date-only rows flagged; no missing weeks imputed.",
                "Short, overlapping evaluation period; descriptive intervals, no significance claims.",
                "Conditional interval may be unavailable with gaps. No trading or parameter search."]}
    json_write(target,report)
    print("Send",target,flush=True)


if __name__=="__main__":
    run()
