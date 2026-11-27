"""Prospective BUY-001 journal. Sunday issuance, Monday origin, Bitstamp only."""
import argparse
import json
import math
from datetime import date,datetime,timezone
from pathlib import Path
from urllib.parse import urlencode

import numpy as np

from binance_minute import digest
from forecast_journal import new_file
from research_daily_usd import ROOT as SNAPSHOT,STOP,LIMIT,seconds,date_at,windows,fetch,parse_page
from research_buy import (DAY,WEEK,FIRST,HASHES,load_prefix,build_signals as base_signals,
                          mondays,allocation,outcome,forecast_score,window)
from research_buy_risk import build_signals as risk_signals,schedule

REPO=Path(__file__).resolve().parent
ROOT=REPO/"data"/"research"/"buy_journal"
LEDGER=REPO/"buy_journal_receipts.json"
VERSION="BUY-001-journal-v1"
FIRST_ORIGIN=date(2026,11,30)
RULES=("dca","lump","trend","dip","risk","risk_M1","risk_L1","risk_M2")


def utcnow():
    return datetime.now(timezone.utc)


def origin_for(now):
    if now.tzinfo is None:
        raise ValueError("UTC-aware clock required")
    now=now.astimezone(timezone.utc)
    if now.weekday()!=6 or now.hour==23 and now.minute>=50:
        raise ValueError("Issue only on Sunday UTC before 23:50")
    t=now.date()+DAY
    if t<FIRST_ORIGIN:
        raise ValueError("Journal has not started")
    return t


def receipt_map(path=LEDGER):
    obj=json.loads(Path(path).read_bytes())
    if obj["version"]!=VERSION:
        raise ValueError("Unexpected receipt ledger")
    rows={}
    for r in obj["receipts"]:
        d=date.fromisoformat(r["origin"])
        if d<FIRST_ORIGIN or d.weekday()!=0 or d in rows:
            raise ValueError("Duplicate or invalid receipt date")
        stamp=datetime.fromisoformat(r["created_utc"].replace("Z","+00:00"))
        h=r["sha256"]
        if (stamp.tzinfo is None or stamp.astimezone(timezone.utc).date()!=d-DAY or
                len(h)!=64 or any(c not in "0123456789abcdef" for c in h)
                or not r["comment_url"].startswith("https://github.com/kh827y/btc-lab/issues/")):
            raise ValueError("Invalid receipt")
        rows[d]=r
    return rows


def live_prices(stop,snapshot=SNAPSHOT,fetcher=fetch):
    if not STOP<=stop<=utcnow().date():
        raise ValueError("Only closed daily candles allowed")
    p=load_prefix(Path(snapshot),"bitstamp",STOP)
    raw_pages=[]
    for a,b in windows(STOP,stop,365):
        url="https://www.bitstamp.net/api/v2/ohlc/btcusd/?"+urlencode({
             "step":86400,"limit":(b-a).days,"start":seconds(a),
             "end":seconds(b)-1,"exclude_current_candle":"true"})
        raw=fetcher(url,LIMIT)
        rows,_=parse_page(raw,"bitstamp",a,b)
        if len(rows)!=(b-a).days:
            raise ValueError("Missing live Bitstamp candle")
        p.update({date_at(t):v for t,v in rows.items()})
        raw_pages.append({"url":url,"sha256":digest(raw),"raw":raw.decode("utf-8")})
    return p,raw_pages


def current(prices,t):
    if any(d>=t-DAY for d in prices):
        raise ValueError("Future/current Sunday price supplied")
    a=base_signals(prices,FIRST["bitstamp"],t+DAY).get(t)
    b=risk_signals(prices,FIRST["bitstamp"],t+DAY).get(t)
    if a is None or b is None or a["thresholds"] is None or any(v is None for v in b["thresholds"].values()):
        raise ValueError("Insufficient eligible history")
    states={"dca":a,"lump":a,"trend":a,"dip":a,"risk":a}
    for m in ("M1","L1","M2"):
        states["risk_"+m]={**b["state"],"models":{"M1":b["pred"][m]},
                            "thresholds":{.8:b["thresholds"][m]}}
    # Record all feasible remaining-budget states before execution. Later
    # reconstruct overlapping paper cohorts using only their own weekly records.
    decisions={}
    for k,s in states.items():
        rule="risk" if k.startswith("risk_") else k
        decisions[k]=[[allocation(rule,i,8,r,s) if r>=8-i or rule!="risk"
                       else max(0,allocation(rule,i,8,r,s))
                       for r in range(9)] for i in range(8)]
    return {"base":a,"extension":b,"decisions":decisions}


def verify_record(p,d,receipt):
    raw=p.read_bytes()
    if digest(raw)!=receipt["sha256"]:
        raise ValueError("Forecast differs from external ledger: "+str(d))
    f=json.loads(raw)
    if f["version"]!=VERSION or f["origin"]!=d.isoformat():
        raise ValueError("Forecast identity mismatch")
    if digest((p.parent/"source.json").read_bytes())!=f["source_sha256"]:
        raise ValueError("Forecast input changed")
    return f


def issue(root=ROOT,ledger=LEDGER,snapshot=SNAPSHOT,fetcher=fetch,clock=utcnow):
    root=Path(root)
    t=origin_for(clock())
    receipts=receipt_map(ledger)
    folder=root/t.isoformat()
    target=folder/"forecast.json"
    if t in receipts:
        verify_record(target,t,receipts[t]) # Missing anchored file fails; never reissue.
        print("Already anchored:",target)
        return target
    if target.exists():
        print("Already issued locally; anchor this exact file:",target)
        print("SHA256:",digest(target.read_bytes()))
        return target
    p,raw=live_prices(t-DAY,snapshot,fetcher)
    s=current(p,t)
    now=clock()
    if origin_for(now)!=t:
        raise ValueError("Issuance window closed")
    folder.mkdir(parents=True,exist_ok=False)
    try:
        h=new_file(folder/"source.json",{"snapshot_sha256":HASHES["bitstamp"],
                                        "stop_exclusive":(t-DAY).isoformat(),"pages":raw})
        record={"version":VERSION,"origin":t.isoformat(),"origin_utc":t.isoformat()+"T00:00:00Z",
                "issued_utc":now.isoformat(),"market":"Bitstamp BTC/USD",
                "horizon_days":28,"source_sha256":h,
                "code_sha256":{k:digest((REPO/k).read_bytes()) for k in
                    ("research_buy.py","research_buy_risk.py","buy_journal.py")},
                **s}
        sha=new_file(target,record)
    except BaseException:
        for k in ("source.json","forecast.json"):
            (folder/k).unlink(missing_ok=True)
        folder.rmdir()
        raise
    print("Send before Monday 00:00 UTC:",target)
    print("SHA256:",sha)
    return target


def settle(root=ROOT,ledger=LEDGER,snapshot=SNAPSHOT,fetcher=fetch,clock=utcnow):
    root=Path(root)
    now=clock().astimezone(timezone.utc).date()
    receipts=receipt_map(ledger)
    records={d:verify_record(root/d.isoformat()/"forecast.json",d,r) for d,r in receipts.items()}
    if not records:
        print("No externally anchored BUY forecasts")
        return 0
    p,_=live_prices(now,snapshot,fetcher)
    count=0
    for d,f in sorted(records.items()):
        folder=root/d.isoformat()
        if now>=d+29*DAY and not (folder/"outcome_28d.json").exists():
            y=outcome(p,d)
            if y is not None:
                actual={"up":int(y["log_return"]>0),"loss_15":int(y["log_worst"]<=math.log(.85))}
                ext={}
                for m,v in f["extension"]["pred"].items():
                    ext[m]={}
                    for k,b in actual.items():
                        q=v["p_"+k]
                        ext[m]["brier_"+k]=(q-b)**2
                        ext[m]["log_"+k]=-math.log(q if b else 1-q)
                new_file(folder/"outcome_28d.json",{"forecast_sha256":receipts[d]["sha256"],
                         "actual":y,"base_scores":{m:forecast_score(v,y) for m,v in f["base"]["models"].items()},
                         "extension_binary_scores":ext})
                count+=1
        if now>=d+57*DAY and not (folder/"purchase_8w.json").exists():
            dates=[d+i*WEEK for i in range(8)]
            if any(t not in records for t in dates):
                print("Incomplete anchored cohort:",d)
                continue
            if window(p,d,d+57*DAY) is None:
                continue
            allocations={}
            for k in RULES:
                r=8;u=[]
                for i,t in enumerate(dates):
                    a=records[t]["decisions"][k][i][r]
                    if type(a) is not int or not 0<=a<=r:
                        raise ValueError("Invalid recorded allocation")
                    u.append(a);r-=a
                if r:
                    raise ValueError("Incomplete budget")
                allocations[k]=u
            new_file(folder/"purchase_8w.json",{"receipts":[receipts[t]["sha256"] for t in dates],
                     "allocations":allocations,
                     "results":{k:schedule(p,d,u) for k,u in allocations.items()}})
            count+=1
    print("New settled records:",count)
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
