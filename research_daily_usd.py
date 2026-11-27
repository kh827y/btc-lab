"""Fixed daily BTC/USD research snapshot; data collection and quality only."""
import csv
import io
import json
import math
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode

import numpy as np

from binance_minute import atomic_write, digest, fetch, json_write

ROOT=Path(__file__).resolve().parent/"data"/"research"/"daily_usd_v1"
STOP=date(2026,11,27)  # Exclusive; no incomplete current day.
DAY=86400
LIMIT=512*1024
MARKETS={
    "bitstamp":("https://www.bitstamp.net/api/v2/ohlc/btcusd/",date(2014,1,1),365),
    "coinbase":("https://api.exchange.coinbase.com/products/BTC-USD/candles",date(2015,7,20),180),
}
VERSION="daily-usd-v1"


def seconds(d):
    return int(datetime.combine(d,datetime.min.time(),timezone.utc).timestamp())


def date_at(t):
    return datetime.fromtimestamp(t,timezone.utc).date()


def windows(start,stop,size):
    while start<stop:
        end=min(start+timedelta(days=size),stop)
        yield start,end
        start=end


def page_url(market,start,stop):
    base,first,size=MARKETS[market]
    n=(stop-start).days
    if not first<=start<stop<=STOP or not 0<n<=size:
        raise ValueError("Invalid daily history range")
    if market=="bitstamp":
        params={"step":DAY,"limit":n,"start":seconds(start),
                "end":seconds(stop)-1,"exclude_current_candle":"true"}
    else:
        params={"granularity":DAY,"start":start.isoformat()+"T00:00:00Z",
                "end":stop.isoformat()+"T00:00:00Z"}
    return base+"?"+urlencode(params)


def parse_page(raw,market,start,stop):
    obj=json.loads(raw)
    if market=="bitstamp":
        data=obj["data"]
        if data.get("pair")!="BTC/USD" or data.get("market","BTC/USD")!="BTC/USD":
            raise ValueError("Wrong Bitstamp pair")
        rows=data["ohlc"]
        max_rows=1000
    elif market=="coinbase":
        rows=obj
        max_rows=300
    else:
        raise ValueError("Unknown market")
    if not isinstance(rows,list) or len(rows)>max_rows:
        raise ValueError("Invalid daily response")
    out={};seen=set();outside=0
    for r in rows:
        if market=="bitstamp":
            if not isinstance(r,dict) or not isinstance(r.get("timestamp"),str) or not r["timestamp"].isdigit():
                raise ValueError("Invalid Bitstamp timestamp")
            t=int(r["timestamp"])
            values=[r[k] for k in ("open","high","low","close","volume")]
            if any(type(v) is not str for v in values):
                raise ValueError("Invalid Bitstamp numeric type")
        else:
            if not isinstance(r,list) or len(r)!=6 or type(r[0]) is not int:
                raise ValueError("Invalid Coinbase candle")
            t,lo,hi,op,cl,vol=r
            values=[op,hi,lo,cl,vol]
            if any(type(v) not in (int,float) for v in values):
                raise ValueError("Invalid Coinbase numeric type")
        if t%DAY or t in seen:
            raise ValueError("Unaligned or duplicate daily candle")
        seen.add(t)
        op,hi,lo,cl,vol=map(float,values)
        if not all(math.isfinite(v) for v in (op,hi,lo,cl,vol)) or not (
                0<lo<=min(op,cl)<=max(op,cl)<=hi and vol>=0):
            raise ValueError("Invalid daily OHLCV")
        if not seconds(start)<=t<seconds(stop):
            outside+=1
            continue
        out[t]=(op,hi,lo,cl,vol)
    if not out:
        raise ValueError("No candles within requested range")
    return out,outside


def download(url,fetcher):
    for attempt in range(3):
        try:
            time.sleep(.35)
            return fetcher(url,LIMIT)
        except HTTPError as exc:
            if exc.code not in (429,500,502,503,504) or attempt==2:
                raise
        except (URLError,TimeoutError):
            if attempt==2:
                raise
        time.sleep(2**(attempt+1))


def cached_page(root,market,start,stop,fetcher):
    url=page_url(market,start,stop)
    p=root/"cache"/market/(start.isoformat()+".json")
    if p.exists():
        doc=json.loads(p.read_bytes())
        raw=doc["raw"].encode("utf-8")
        if doc["url"]!=url or doc["sha256"]!=digest(raw):
            raise ValueError("Cache hash or URL mismatch: "+str(p))
        rows,outside=parse_page(raw,market,start,stop)
    else:
        raw=download(url,fetcher)
        if len(raw)>LIMIT:
            raise ValueError("Daily response exceeds size limit")
        rows,outside=parse_page(raw,market,start,stop)
        doc={"url":url,"sha256":digest(raw),"raw":raw.decode("utf-8"),
             "retrieved_utc":datetime.now(timezone.utc).isoformat()}
        json_write(p,doc)
    return rows,{"start":start.isoformat(),"stop_exclusive":stop.isoformat(),
                 "url":url,"sha256":doc["sha256"],"rows":len(rows),
                 "outside_range_rows":outside}


def coverage(rows,start,stop):
    expected=Counter();observed=Counter();missing=[]
    for d,_ in windows(start,stop,1):
        expected[d.year]+=1
        if seconds(d) in rows:
            observed[d.year]+=1
        else:
            missing.append(d.isoformat())
    by_year={str(y):{"expected":n,"observed":observed[y],
                     "fraction":observed[y]/n} for y,n in expected.items()}
    return {"expected":(stop-start).days,"observed":len(rows),
            "first":date_at(min(rows)).isoformat() if rows else None,
            "last":date_at(max(rows)).isoformat() if rows else None,
            "missing_dates":missing,"zero_volume_days":sum(v[4]==0 for v in rows.values()),
            "by_year":by_year,"fraction":len(rows)/(stop-start).days}


def csv_bytes(rows):
    buf=io.StringIO(newline="")
    w=csv.writer(buf,lineterminator="\n")
    w.writerow(["date_utc","open","high","low","close","volume_btc"])
    for t,v in sorted(rows.items()):
        w.writerow([date_at(t).isoformat(),*v])
    return buf.getvalue().encode("utf-8")


def save_snapshot(path,raw):
    # A completed snapshot is immutable; a new date range needs a new version.
    if path.exists():
        if path.read_bytes()!=raw:
            raise ValueError("Existing snapshot differs; refusing overwrite: "+str(path))
    else:
        atomic_write(path,raw)
    return digest(raw)


def collect(root,market,fetcher):
    _,start,size=MARKETS[market]
    combined={};pages=[];errors=[]
    for a,b in windows(start,STOP,size):
        print(market,a,b,flush=True)
        try:
            rows,page=cached_page(root,market,a,b,fetcher)
        except (OSError,ValueError,TypeError,KeyError,OverflowError) as exc:
            errors.append({"start":a.isoformat(),"stop_exclusive":b.isoformat(),
                           "error":str(exc)})
            # Avoid hammering an unavailable endpoint. Cached completed pages
            # remain usable on a later retry.
            break
        if set(combined)&set(rows):
            raise ValueError("Overlapping daily pages")
        combined.update(rows);pages.append(page)
    quality=coverage(combined,start,STOP)
    complete=not errors
    usable=(complete and quality["fraction"]>=.98 and
            all(v["fraction"]>=.95 for v in quality["by_year"].values()) and
            quality["last"]==(STOP-timedelta(days=1)).isoformat())
    info={"market":market+" BTC/USD spot","start_requested":start.isoformat(),
          "stop_exclusive":STOP.isoformat(),"complete_requests":complete,
          "coverage_gate":usable,"pages":pages,"errors":errors,**quality,
          "csv_sha256":None}
    if complete:
        info["csv_sha256"]=save_snapshot(root/(market+"_daily.csv"),csv_bytes(combined))
    return combined,info


def cross_check(a,b):
    common=sorted(set(a)&set(b))
    if not common:
        return None
    # Compare only the same UTC-day price measurements, no forward returns.
    def stats(ts):
        x=np.asarray([abs(b[t][3]/a[t][3]-1)*100 for t in ts])
        return {"days":len(ts),"median_abs_close_diff_pct":float(np.median(x)),
                "p95_abs_close_diff_pct":float(np.quantile(x,.95)),
                "max_abs_close_diff_pct":float(x.max())}
    return {**stats(common),"by_year":{str(y):stats([t for t in common if date_at(t).year==y])
                   for y in sorted({date_at(t).year for t in common})}}


def run(root=ROOT,fetcher=fetch):
    root=Path(root)
    root.mkdir(parents=True,exist_ok=True)
    pairs={m:collect(root,m,fetcher) for m in MARKETS}
    report={"version":VERSION,"stop_exclusive":STOP.isoformat(),
            "markets":{m:pairs[m][1] for m in MARKETS},
            "cross_check":cross_check(pairs["bitstamp"][0],pairs["coinbase"][0]),
            "note":"Coverage gates are preliminary, not proof of accurate prices. No gap filling, no source splicing, no research outcomes or model fitting.",
            "complete":all(pairs[m][1]["complete_requests"] for m in MARKETS)}
    json_write(root/"coverage.json",report)
    print(json.dumps({"complete":report["complete"],
         "markets":{m:{k:info[k] for k in ("observed","expected","coverage_gate","errors")}
                    for m,info in report["markets"].items()}},indent=2),flush=True)
    print("Send",root/"coverage.json",flush=True)
    return report


if __name__=="__main__":
    run()
