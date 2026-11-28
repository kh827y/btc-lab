"""Current public FRED observations, separate from upstream monitor. No historical vintage claims."""
import csv
import hashlib
import io
import json
import math
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

SERIES={"DFF":("percent",4),"DGS2":("percent",5),
        "DGS10":("percent",5),"DTWEXBGS":("index",10)}
LIMIT=128*1024

def address(series, day, alternate=False):
    if series not in SERIES:
        raise ValueError("Unknown series")
    params={"id":series,"cosd":(day-timedelta(days=45)).isoformat(),"coed":day.isoformat()}
    if alternate:
        params["vintage_date"]=day.isoformat()
    return ("https://alfred.stlouisfed.org/graph/alfredgraph.csv?" if alternate else
            "https://fred.stlouisfed.org/graph/fredgraph.csv?")+urlencode(params)

def fetch(url):
    with urlopen(Request(url,headers={"User-Agent":"BTC-Lab public data","Accept":"text/csv"}),timeout=12) as r:
        a,b=urlsplit(url),urlsplit(r.geturl())
        if (a.scheme,a.netloc,a.path)!=(b.scheme,b.netloc,b.path):
            raise ValueError("Unexpected macro redirect")
        raw=r.read(LIMIT+1)
    if len(raw)>LIMIT:
        raise ValueError("CSV exceeds limit")
    return raw

def parse(raw, series, day, alternate=False):
    if series not in SERIES or len(raw)>LIMIT:
        raise ValueError("Unexpected series/size")
    rows=csv.reader(io.StringIO(raw.decode("utf-8-sig")))
    name=series+"_"+day.strftime("%Y%m%d") if alternate else series
    if next(rows,None) not in (["observation_date",name],["DATE",name]):
        raise ValueError("Unexpected CSV header")
    values={}
    last=None
    for row in rows:
        if len(row)!=2:
            raise ValueError("Unexpected CSV row")
        d=date.fromisoformat(row[0])
        if row[0]!=d.isoformat() or not day-timedelta(days=45)<=d<=day or (last is not None and d<=last):
            raise ValueError("Invalid/duplicate/unordered observation date")
        last=d
        if row[1].strip() in ("","."):
            continue
        v=float(row[1])
        if not math.isfinite(v) or (series=="DTWEXBGS" and v<=0):
            raise ValueError("Invalid observation")
        values[d]=v
    if not values:
        raise ValueError("No numeric observations")
    return values

def summarize(values, series, day):
    latest=max(values)
    value=values[latest]
    unit,limit=SERIES[series]
    age=(day-latest).days
    ok=0<=age<=limit
    item={"id":series,"unit":unit,"value":value if ok else None,
          "status":"usable" if ok else "observation_older_than_limit",
          "observed_at":latest.isoformat(),"age_calendar_days":age,
          "max_age_calendar_days":limit,"time_precision":"date_only",
          "comparison_key":"FRED|"+series,"valid_observations":len(values),
          "changes":{}}
    for n in (7,28):
        target=latest-timedelta(days=n)
        previous=max((d for d in values if d<=target),default=None)
        good=ok and previous is not None and (target-previous).days<=4
        change=(100*(value/values[previous]-1) if unit=="index" else value-values[previous]) if good else None
        item["changes"][str(n)+"d"]={"value":change,"unit":"percent" if unit=="index" else "percentage_points",
                "from_date":previous.isoformat() if good else None,"to_date":latest.isoformat() if good else None,
                "target_date":target.isoformat(),"status":"usable" if good else "unavailable"}
    return item

def collect(root, fetcher=fetch, clock=lambda:datetime.now(timezone.utc)):
    root=Path(root)
    root.mkdir(parents=True,exist_ok=False)
    day=clock().date()
    records=[]
    for s,(unit,limit) in SERIES.items():
        errors=[]
        item=None
        for alternate in (False,True):
            url=address(s,day,alternate)
            try:
                raw=fetcher(url)
                received=clock()
                values=parse(raw,s,day,alternate)
                candidate=summarize(values,s,received.date())
                name=s+("_alfred" if alternate else "_fred")+".csv"
                with (root/name).open("xb") as f:
                    f.write(raw)
                candidate.update(source=url,retrieved_utc=received.isoformat(),
                    raw_path=name,raw_sha256=hashlib.sha256(raw).hexdigest(),
                    source_kind="alfred_requested_current_vintage" if alternate else "fred_current",
                    errors=list(errors))
                if item is None or candidate["observed_at"]>item["observed_at"]:
                    item=candidate
                if item["status"]=="usable":
                    break
            except (OSError,ValueError,TypeError,OverflowError) as exc:
                errors.append({"url":url,"error":str(exc)[:180]})
        if item is None:
            item={"id":s,"unit":unit,"value":None,"status":"unavailable","observed_at":None,
                  "comparison_key":"FRED|"+s,"changes":{}}
        item["errors"]=errors
        records.append(item)
    return {"version":"live-macro-v1","series":records,"limitations":[
        "Current published observations, not original release vintages. Retrieval time is not publication time.",
        "Calendar-day freshness caps (4/5/10 days) are provisional, not verification of scheduled releases.",
        "H.10 broad dollar index is published weekly; date-only observations can lag.",
        "7/28-day comparisons use the latest observed date and a previous available value at or before the target, up to four calendar days earlier.",
        "No interpolation, substitution or historical forecast use."]}
