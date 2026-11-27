"""Independent BTC/USD check on the frozen CPI train/development dates only.

Public Coinbase Exchange historical candles. No keys, no full-history download.
No final-period market data, no source splicing, no gap filling.
"""
import copy
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import numpy as np

from binance_minute import MINUTE, digest, json_write
from research_prices import DAY
from research_cpi import OUT, verify_development
from research_cpi_development import load_split, replay, summary

API = "https://api.exchange.coinbase.com/products/BTC-USD/candles"
LIMIT = 256 * 1024
CUTOFF = int(datetime(2024,1,1,tzinfo=timezone.utc).timestamp())*1000


def iso(t):
    return datetime.fromtimestamp(t/1000,tz=timezone.utc).isoformat().replace("+00:00","Z")


def request_url(start, stop, step, *, cutoff=CUTOFF):
    if step not in (MINUTE,DAY) or start%step or stop%step or not start<stop<=cutoff or (stop-start)//step>299:
        raise ValueError("Invalid or final-period candle request")
    return API+"?"+urlencode({"start":iso(start),"end":iso(stop),"granularity":step//1000})


def parse(raw, start, stop, step):
    rows=json.loads(raw)
    if not isinstance(rows,list) or len(rows)>300:
        raise ValueError("Unexpected Coinbase response")
    data={}
    for r in rows:
        if not isinstance(r,list) or len(r)!=6 or type(r[0]) is not int:
            raise ValueError("Unexpected Coinbase candle schema")
        t=r[0]*1000
        if t%step:
            raise ValueError("Unaligned Coinbase candle")
        # Endpoint may return earlier or end-inclusive candles.
        if not start<=t<stop:
            continue
        if t in data or any(type(x) not in (int,float) for x in r[1:]):
            raise ValueError("Duplicate or nonnumeric Coinbase candle")
        low,high,op,close,vol=map(float,r[1:])
        if not all(math.isfinite(x) for x in (low,high,op,close,vol)) or not (0<low<=min(op,close)<=max(op,close)<=high and vol>=0):
            raise ValueError("Invalid Coinbase OHLCV")
        data[t]=(op,close)
    return data


def fetch(url):
    # Fixed URL from request_url; no authentication, low request frequency.
    for i in range(3):
        time.sleep(.4)
        try:
            req=Request(url,headers={"User-Agent":"BTC-Lab research","Accept":"application/json"})
            with urlopen(req,timeout=25) as response:
                if response.geturl()!=url:
                    raise ValueError("Unexpected redirect")
                raw=response.read(LIMIT+1)
            if len(raw)>LIMIT:
                raise ValueError("Coinbase response too large")
            return raw
        except HTTPError as exc:
            if exc.code not in (429,500,502,503,504) or i==2:
                raise
        except (URLError,TimeoutError):
            if i==2:
                raise
        time.sleep(2**(i+1))


class CandleCache:
    def __init__(self, root, fetcher=fetch, *, cutoff=CUTOFF):
        self.cutoff=cutoff
        self.root=Path(root)
        self.fetcher=fetcher
        self.used={}

    def get(self,start,stop,step):
        url=request_url(start,stop,step,cutoff=self.cutoff)
        key=digest(url.encode())
        p=self.root/(key+".json")
        if p.exists():
            obj=json.loads(p.read_bytes())
            raw=obj["raw"].encode("utf-8")
            if obj["url"]!=url or obj["sha256"]!=digest(raw):
                raise ValueError("Coinbase cache integrity failure: "+key)
            data=parse(raw,start,stop,step)
        else:
            raw=self.fetcher(url)
            if len(raw)>LIMIT:
                raise ValueError("Coinbase response too large")
            data=parse(raw,start,stop,step)
            obj={"url":url,"sha256":digest(raw),"raw":raw.decode("utf-8"),
                 "retrieved_utc":datetime.now(timezone.utc).isoformat()}
            json_write(p,obj)
        self.used[key]=obj["sha256"]
        return data


def independent_event(e, cache, *, cutoff=CUTOFF):
    t=e["entry"]-31*MINUTE
    if e["exit"]!=e["entry"]+7*DAY or e["exit"]+MINUTE>cutoff:
        raise ValueError("Unexpected event or final-period request")
    midnight=t//DAY*DAY
    daily=cache.get(midnight-29*DAY,midnight,DAY)
    reaction=cache.get(t-MINUTE,e["entry"]+MINUTE,MINUTE)
    exit_rows=cache.get(e["exit"],e["exit"]+MINUTE,MINUTE)
    closes=[daily.get(k) for k in range(midnight-29*DAY,midnight,DAY)]
    response=[reaction.get(k) for k in range(t-MINUTE,t+30*MINUTE,MINUTE)]
    entry= reaction.get(e["entry"])
    exit_=exit_rows.get(e["exit"])
    missing=[]
    if any(x is None for x in closes):
        missing.append("daily_close")
    if any(x is None for x in response):
        missing.append("reaction_minute")
    if entry is None:
        missing.append("entry")
    if exit_ is None:
        missing.append("exit")
    if missing:
        return None,missing
    x=np.asarray([r[1] for r in closes])
    r=copy.deepcopy(e)
    r["x"]=[float(x[-1]/x[0]-1),float(np.std(x[1:]/x[:-1]-1,ddof=1)),
            float(response[-1][1]/response[0][1]-1),e["x"][3]]
    r["y"]=exit_[0]/entry[0]-1
    return r,[]


def differences(binance, coinbase):
    if not binance or [r["id"] for r in binance]!=[r["id"] for r in coinbase]:
        raise ValueError("Need matched dates")
    fields=("prior_return_28d","prior_vol_28d","reaction_30m","return_7d")
    a=np.asarray([r["x"][:3]+[r["y"]] for r in binance])
    b=np.asarray([r["x"][:3]+[r["y"]] for r in coinbase])
    delta=(b-a)*100
    out={}
    for i,name in enumerate(fields):
        ab=np.abs(delta[:,i])
        out[name]={"median_abs_difference_pp":float(np.median(ab)),
                   "p95_abs_difference_pp":float(np.quantile(ab,.95)),
                   "max_abs_difference_pp":float(ab.max()),
                   "largest_difference_event_id":binance[int(ab.argmax())]["id"]}
    out["return_direction_agreement_fraction"]=float((np.sign(a[:,3])==np.sign(b[:,3])).mean())
    return out


def run(root=OUT, fetcher=fetch):
    root=Path(root)
    manifest=verify_development(root,json.loads((root/"coverage.json").read_bytes()))
    train,dev=[load_split(root,s,manifest["file_sha256"]) for s in ("train","development")]
    if (len(train),len(dev))!=(46,24):
        raise ValueError("Unexpected sample")
    cache=CandleCache(root/"coinbase_cache",fetcher)
    pairs={}
    missing=[]
    for split,events in (("train",train),("development",dev)):
        b,c=[],[]
        for i,e in enumerate(events,1):
            print(f"Coinbase {split}: {i}/{len(events)}",flush=True)
            r,reason=independent_event(e,cache)
            if r is None:
                missing.append({"event_id":e["id"],"missing":reason})
                continue
            b.append(e);c.append(r)
        pairs[split]=(b,c)
    bt,ct=pairs["train"]
    bd,cd=pairs["development"]
    report={"protocol":"CPI-001-independent-development-v1","market":"Coinbase BTC-USD spot",
            "source":API,"test_read":False,"train_matched":len(bt),"development_matched":len(bd),
            "expected_train":46,"expected_development":24,"missing":missing,
            "price_snapshot_sha256":manifest["price_provenance"]["snapshot_sha256"],
            "input_hashes":manifest["file_sha256"],"response_hashes":cache.used,
            "differences":differences(bt+bd,ct+cd) if bt+bd else None,
            "same_dates_replay":None,
            "limitations":["Separate USD market; BTC/USDT basis and exchange differences are real.",
                           "Coinbase historical candles can be incomplete; no gap filling.",
                           "Daily candles replace exact prior minute closes only for independent replication.",
                           "Development only; no final inference. Cache hashes identify received data, not official signed checksums."]}
    if len(bt)>=30 and bd:
        report["same_dates_replay"]={"binance":summary(replay(bt,bd)),
                                     "coinbase":summary(replay(ct,cd))}
    json_write(root/"coinbase_development_report.json",report)
    return report


if __name__=="__main__":
    r=run()
    print(json.dumps({k:r[k] for k in ("train_matched","development_matched","differences","same_dates_replay")},indent=2))
    print("Send coinbase_development_report.json. No final data read.")
