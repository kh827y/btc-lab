"""RISK-journal-v1: prospective reference forecasts, separate from BUY journal."""
import argparse
import json
import math
from datetime import date,datetime,timezone
from pathlib import Path
import numpy as np

from binance_minute import digest
from forecast_journal import new_file
from buy_journal import origin_for,utcnow,live_prices,FIRST_ORIGIN,REPO
from research_daily_usd import ROOT as SNAPSHOT,STOP,fetch
from research_buy import HASHES,DAY,mondays,state,outcome
from research_risk_reference import (START,HORIZONS,MIN_TRAIN,QUANTILES,
                                    LOSS_THRESHOLD,distributions,score_distribution)

ROOT=REPO/"data"/"research"/"risk_journal"
LEDGER=REPO/"risk_journal_receipts.json"
VERSION="RISK-journal-v1"
MODELS=("empirical_expanding","scaled_expanding")
CODE_FILES=("risk_journal.py","research_risk_reference.py","research_buy.py",
            "buy_journal.py","research_daily_usd.py","forecast_journal.py")


def receipt_map(path=LEDGER):
    obj=json.loads(Path(path).read_bytes())
    if obj["version"]!=VERSION:
        raise ValueError("Wrong risk receipt ledger")
    rows={}
    for r in obj["receipts"]:
        d=date.fromisoformat(r["origin"])
        stamp=datetime.fromisoformat(r["created_utc"].replace("Z","+00:00"))
        h=r["sha256"]
        if (d<FIRST_ORIGIN or d.weekday()!=0 or d in rows or stamp.tzinfo is None
            or stamp.astimezone(timezone.utc).date()!=d-DAY
            or len(h)!=64 or any(c not in "0123456789abcdef" for c in h)
            or not r["comment_url"].startswith("https://github.com/kh827y/btc-lab/issues/")):
            raise ValueError("Invalid risk receipt")
        rows[d]=r
    return rows


def current(prices,t,first=START):
    cutoff=t-DAY
    if any(d>=cutoff for d in prices):
        raise ValueError("Current Sunday/future data supplied")
    s=state(prices,t)
    if s is None:
        raise ValueError("Missing current price state")
    result={}
    for h in HORIZONS:
        history=[]
        for d in mondays(first,cutoff):
            if d+(h+1)*DAY>cutoff:
                break
            st=state(prices,d)
            y=outcome(prices,d,h)
            if st is not None and y is not None:
                history.append({"date":d,"sigma":st["sigma"],**y})
        if len(history)<MIN_TRAIN:
            raise ValueError("Insufficient matured history")
        models=distributions(history,s["sigma"])
        forecasts={}
        for m in MODELS:
            a=models[m];ret=a["return"];worst=a["worst"];n=len(ret)
            forecasts[m]={"n_train":n,
                "p_up":float((1+np.sum(ret>0))/(n+2)),
                "p_loss_15":float((1+np.sum(worst<=LOSS_THRESHOLD))/(n+2)),
                "return_log_quantiles":np.quantile(ret,QUANTILES).tolist(),
                "worst_log_quantiles":np.quantile(worst,QUANTILES).tolist(),
                "daily_variance":a["variance"],
                "return_samples":ret.tolist(),"worst_samples":worst.tolist()}
        result[str(h)]={"latest_train_origin":history[-1]["date"].isoformat(),
                        "n_matured":len(history),
                        "models":forecasts,
                        "ewma_daily_variance":max(1e-12,s["sigma"]**2)}
    return {"state":s,"horizons":result}


def verify_record(p,d,receipt):
    raw=p.read_bytes()
    if digest(raw)!=receipt["sha256"]:
        raise ValueError("Risk forecast differs from external receipt")
    f=json.loads(raw)
    if f["version"]!=VERSION or f["origin"]!=d.isoformat():
        raise ValueError("Risk forecast identity mismatch")
    if digest((p.parent/"source.json").read_bytes())!=f["source_sha256"]:
        raise ValueError("Risk forecast source changed")
    if set(f["horizons"])!={str(h) for h in HORIZONS}:
        raise ValueError("Wrong risk horizons")
    return f


def issue(root=ROOT,ledger=LEDGER,snapshot=SNAPSHOT,fetcher=fetch,clock=utcnow):
    root=Path(root);t=origin_for(clock())
    receipts=receipt_map(ledger)
    folder=root/t.isoformat();target=folder/"risk_forecast.json"
    if t in receipts:
        verify_record(target,t,receipts[t])
        print("Already anchored:",target)
        return target
    if target.exists():
        print("Already issued locally; anchor exact file:",target)
        print("SHA256:",digest(target.read_bytes()))
        return target
    prices,pages=live_prices(t-DAY,snapshot,fetcher)
    pred=current(prices,t)
    now=clock()
    if origin_for(now)!=t:
        raise ValueError("Issuance window closed")
    folder.mkdir(parents=True,exist_ok=False)
    try:
        source=new_file(folder/"source.json",{
            "snapshot_sha256":HASHES["bitstamp"],
            "stop_exclusive":(t-DAY).isoformat(),"pages":pages})
        record={"version":VERSION,"origin":t.isoformat(),
                "origin_utc":t.isoformat()+"T00:00:00Z",
                "issued_utc":now.isoformat(),"market":"Bitstamp BTC/USD",
                "source_sha256":source,"code_sha256":{
                    k:digest((REPO/k).read_bytes()) for k in CODE_FILES},
                "kind":"prospective_reference_tracking_not_confirmation",
                **pred}
        sha=new_file(target,record)
    except BaseException:
        for k in ("source.json","risk_forecast.json"):
            (folder/k).unlink(missing_ok=True)
        folder.rmdir()
        raise
    print("Send before Monday 00:00 UTC:",target)
    print("SHA256:",sha)
    return target


def score_horizon(f,y,h):
    row=f["horizons"][str(h)]
    result={}
    for m in MODELS:
        a=row["models"][m]
        d={"return":np.array(a["return_samples"]),
           "worst":np.array(a["worst_samples"]),
           "variance":a["daily_variance"]}
        score=score_distribution(d,y)
        # Forecast was recorded before origin; do not silently accept
        # inconsistent summaries and samples even when file is anchored.
        for k in ("n_train","p_up","p_loss_15","return_log_quantiles",
                  "worst_log_quantiles","daily_variance"):
            if not np.allclose(score[k],a[k],rtol=1e-12,atol=1e-12):
                raise ValueError("Forecast sample/summary mismatch: "+k)
        result[m]=score["scores"]
    v=row["ewma_daily_variance"]
    return {"actual":y,"scores":result,
            "ewma_qlike":float(math.log(v)+y["variance"]/v),
            "coinflip_brier_up":.25}


def settle(root=ROOT,ledger=LEDGER,snapshot=SNAPSHOT,fetcher=fetch,clock=utcnow):
    root=Path(root);today=clock().astimezone(timezone.utc).date()
    receipts=receipt_map(ledger)
    records={d:verify_record(root/d.isoformat()/"risk_forecast.json",d,r)
             for d,r in receipts.items()}
    pending=[(d,h) for d in records for h in HORIZONS
             if d+(h+1)*DAY<=today and not
             (root/d.isoformat()/f"outcome_{h}d.json").exists()]
    if not pending:
        print("No new matured anchored risk outcomes")
        return 0
    prices,pages=live_prices(today,snapshot,fetcher)
    count=0
    for d,h in pending:
        y=outcome(prices,d,h)
        if y is None:
            print("Missing outcome:",d,h)
            continue
        new_file(root/d.isoformat()/f"outcome_{h}d.json",{
            "version":VERSION,"forecast_sha256":receipts[d]["sha256"],
            "origin":d.isoformat(),"horizon_days":h,
            "settled_utc":clock().isoformat(),
            "snapshot_sha256":HASHES["bitstamp"],
            "live_page_sha256":[p["sha256"] for p in pages],
            **score_horizon(records[d],y,h)})
        count+=1
    print("New settled risk outcomes:",count)
    return count


def status(ledger=LEDGER,clock=utcnow):
    rows=receipt_map(ledger)
    today=clock().astimezone(timezone.utc).date()
    for d in mondays(FIRST_ORIGIN,today+DAY):
        print(d,"anchored" if d in rows else "missed / unanchored")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("command",choices=("issue","settle","status"),nargs="?",default="issue")
    a=p.parse_args()
    {"issue":issue,"settle":settle,"status":status}[a.command]()
