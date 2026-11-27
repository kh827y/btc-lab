"""FLOW-001: development-only incremental spot taker imbalance study."""
import json
import math
from datetime import date,datetime,timezone
from pathlib import Path

import numpy as np

from binance_daily import URL,DAY as MS_DAY,parse_klines
from extended_history import request_json
from binance_minute import digest,json_write
from research_buy import ROOT as PRICE_ROOT,DAY,DEV_END,FIRST,HASHES,days,mondays,load_development,outcome
from research_buy_risk import features,logistic,interval

ROOT=Path(__file__).resolve().parent/"data"/"research"/"flow_v1"
START=date(2017,8,17)
EVAL_START=date(2019,1,7)
VERSION="FLOW-001-development-v1"
MODELS=("frequency","coinflip","L1","L1_flow","M2","M2_flow")


def millis(d):
    return int(datetime(d.year,d.month,d.day,tzinfo=timezone.utc).timestamp()*1000)


def page_ranges():
    start=START
    while start<DEV_END:
        stop=min(start+900*DAY,DEV_END)
        yield start,stop
        start=stop


def canonical(obj):
    return json.dumps(obj,sort_keys=True,separators=(",",":"),allow_nan=False).encode("utf-8")


def parse_page(rows,start,stop):
    if not isinstance(rows,list) or len(rows)>900:
        raise ValueError("Invalid kline page")
    if not START<=start<stop<=DEV_END:
        raise ValueError("Invalid development range")
    result={};rejected={};seen=set()
    a,b=millis(start),millis(stop)
    for r in rows:
        if not isinstance(r,list) or not r or type(r[0]) is not int:
            raise ValueError("Unidentifiable candle")
        t=r[0]//1000 if r[0]>=10**14 else r[0]
        if not a<=t<b:
            raise ValueError("Out-of-range candle")
        d=datetime.fromtimestamp(t/1000,timezone.utc).date()
        if d in seen:
            raise ValueError("Duplicate calendar day")
        seen.add(d)
        try:
            parse_klines([r],a,b)
            total,buy=map(float,(r[7],r[10]))
            if not math.isfinite(total) or not math.isfinite(buy) or not 0<=buy<=total or total<=0:
                raise ValueError("Invalid or zero quote volume")
            result[d]=(total,buy)
        except (ValueError,TypeError,OverflowError) as exc:
            rejected[d.isoformat()]=str(exc)
    for d in days(start,stop):
        if d not in seen:
            rejected[d.isoformat()]="No candle"
    return result,rejected


def load_flow(root=ROOT,fetch=request_json):
    root=Path(root)
    root.mkdir(parents=True,exist_ok=True)
    combined={};bad={};pages=[]
    for a,b in page_ranges():
        params={"symbol":"BTCUSDT","interval":"1d","startTime":millis(a),
                "endTime":millis(b)-1,"limit":(b-a).days,"timeZone":"0"}
        path=root/"cache"/(a.isoformat()+".json")
        if path.exists():
            obj=json.loads(path.read_bytes())
            if obj["url"]!=URL or obj["params"]!=params or obj["rows_sha256"]!=digest(canonical(obj["rows"])):
                raise ValueError("Cached page mismatch")
        else:
            raw=fetch(URL,params)
            parse_page(raw,a,b)
            obj={"url":URL,"params":params,"rows":raw,"rows_sha256":digest(canonical(raw)),
                 "retrieved_utc":datetime.now(timezone.utc).isoformat()}
            json_write(path,obj)
        values,rejected=parse_page(obj["rows"],a,b)
        if set(values)&set(combined):
            raise ValueError("Overlapping pages")
        combined.update(values);bad.update(rejected)
        pages.append({"start":a.isoformat(),"stop_exclusive":b.isoformat(),
                      "rows_sha256":obj["rows_sha256"],"retrieved_utc":obj["retrieved_utc"],
                      "valid_days":len(values)})
    expected=(DEV_END-START).days
    by_year={}
    for d in days(START,DEV_END):
        v=by_year.setdefault(str(d.year),{"expected":0,"valid":0})
        v["expected"]+=1
        v["valid"]+=int(d in combined)
    info={"pages":pages,"expected":expected,"valid":len(combined),"by_year":by_year,
          "rejected_days":bad,"source":"Binance BTCUSDT spot, daily klines, public REST",
          "snapshot_sha256":digest(canonical({d.isoformat():v for d,v in combined.items()})),
          "coverage_gate":len(combined)>=.95*expected and all(
              v["valid"]>=.90*v["expected"] for v in by_year.values())}
    path=root/"coverage.json"
    if path.exists():
        if json.loads(path.read_bytes())!=info:
            raise ValueError("Existing flow snapshot differs; retain it")
    else:
        json_write(path,info)
    if not info["coverage_gate"]:
        raise ValueError("Flow coverage inadequate; send coverage.json")
    return combined,info


def imbalance(flow,t):
    # Monday origin: Sunday decision; only Sat and preceding six closed days.
    rows=[flow.get(d) for d in days(t-8*DAY,t-DAY)]
    if len(rows)!=7 or any(v is None for v in rows):
        return None
    total=sum(v[0] for v in rows)
    buy=sum(v[1] for v in rows)
    if total<=0:
        return None
    return 2*buy/total-1


def targets(y):
    return {"up":int(y["log_return"]>0),"loss_15":int(y["log_worst"]<=math.log(.85))}


def fit(history,x):
    h=history[-104:]
    X=np.array([r[0] for r in h])
    result={m:{} for m in MODELS}
    for k in ("up","loss_15"):
        y=np.array([r[1][k] for r in h])
        result["frequency"][k]=float((1+y.sum())/(len(y)+2))
        result["coinflip"][k]=.5
        for m,cols in (("L1",[0]),("L1_flow",[0,4]),("M2",[0,1,2,3]),("M2_flow",[0,1,2,3,4])):
            result[m][k]=logistic(X[:,cols],y,x[cols])
    return result


def replay(prices,flow,end=DEV_END):
    if end>DEV_END:
        raise ValueError("Final data are not permitted")
    pending=[];history=[];pred={};missing=[]
    for t in mondays(START,end):
        while pending and pending[0][0]+29*DAY<=t-DAY:
            d,x=pending.pop(0)
            y=outcome(prices,d)
            if y is not None:
                history.append((x,targets(y)))
        f=features(prices,t)
        v=imbalance(flow,t)
        if f is None or v is None:
            if t>=EVAL_START and t+29*DAY<=end:
                missing.append({"date":t.isoformat(),"reason":"incomplete price or flow features"})
            continue
        x=np.r_[f[1],v]
        pending.append((t,x))
        if len(history)<52:
            if t>=EVAL_START and t+29*DAY<=end:
                missing.append({"date":t.isoformat(),"reason":"insufficient training labels"})
            continue
        if t>=EVAL_START:
            pred[t]={"n_train":min(len(history),104),"flow":v,"pred":fit(history,x)}
    rows=[]
    for t,r in pred.items():
        if t+29*DAY>end:
            continue
        y=outcome(prices,t)
        if y is None:
            missing.append({"date":t.isoformat(),"reason":"incomplete outcome"})
            continue
        rows.append({"date":t.isoformat(),"actual":targets(y),**r})
    return rows,missing


def score(rows,with_intervals=True):
    if not rows:
        return {"n":0}
    dates=[date.fromisoformat(r["date"]) for r in rows]
    result={"n":len(rows)}
    for k in ("up","loss_15"):
        y=np.array([r["actual"][k] for r in rows])
        losses={};models={}
        for m in MODELS:
            p=np.array([r["pred"][m][k] for r in rows])
            losses[m]=(p-y)**2
            models[m]={"brier":float(losses[m].mean()),
                       "log_score":float(-np.mean(y*np.log(p)+(1-y)*np.log1p(-p))),
                       "mean_probability":float(p.mean())}
        deltas={}
        for a,b in (("L1_flow","L1"),("M2_flow","M2"),("L1_flow","frequency"),("L1_flow","coinflip")):
            d=losses[a]-losses[b]
            deltas[a+"_minus_"+b]={"mean_brier_delta":float(d.mean())}
            if with_intervals:
                deltas[a+"_minus_"+b]["conditional_interval90"]=interval(d,dates)
        result[k]={"actual_frequency":float(y.mean()),"models":models,"comparisons":deltas}
    return result


def run(root=ROOT,price_root=PRICE_ROOT,fetch=request_json):
    root=Path(root)
    target=root/"flow_development_report.json"
    if target.exists():
        raise ValueError("Report already exists; preserve original results")
    flow,quality=load_flow(root,fetch)
    markets={}
    for m in HASHES:
        print("FLOW development:",m,flush=True)
        p=load_development(Path(price_root),m)
        rows,missing=replay(p,flow)
        if not rows:
            raise ValueError("No matched forecasts")
        markets[m]={"summary":score(rows),"first":rows[0]["date"],"last":rows[-1]["date"],
                    "missing":missing,"by_year":{str(y):score([r for r in rows if r["date"].startswith(str(y))],False)
                    for y in range(EVAL_START.year,DEV_END.year)},"predictions":rows}
    report={"protocol":VERSION,"price_hashes":HASHES,"flow_quality":quality,
            "test_numeric_values_parsed":False,"evaluation_start":EVAL_START.isoformat(),
            "stop_exclusive":DEV_END.isoformat(),"markets":markets,
            "limitations":["Single Binance BTCUSDT market, not consolidated spot demand or capital inflows.",
                 "Historical daily data retrieved today; original point-in-time vintages not proved.",
                 "2024+ already evaluated for other hypotheses; no claim of new pristine historical holdout.",
                 "All models use identical complete training and evaluation dates.",
                 "Overlapping 28d labels; conditional block intervals descriptive, no significance claim.",
                 "No purchase simulation or tuning in this stage."]}
    json_write(target,report)
    print("Send",target,flush=True)
    return report


if __name__=="__main__":
    run()
