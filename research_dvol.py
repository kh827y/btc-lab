"""DVOL-001: public Deribit data audit and descriptive 30-day variance reference."""
import json
import math
from datetime import date,datetime,timezone
from pathlib import Path
from urllib.parse import urlencode
import numpy as np

from binance_minute import atomic_write,digest,json_write
from research_daily_usd import seconds,date_at,windows,fetch,download
from research_buy import ROOT as PRICE_ROOT,HASHES,DEV_END,DAY,mondays,state,outcome,load_development

ROOT=Path(__file__).resolve().parent/"data"/"research"/"dvol_v1"
VERSION="DVOL-001-reference-v1"
START=date(2021,4,1)
BASE="https://www.deribit.com/api/v2/public/get_volatility_index_data"
MS_DAY=86400000
H=30
PAGE_DAYS=90

def ms(d):
    return seconds(d)*1000

def url(a,end_ms):
    return BASE+"?"+urlencode({"currency":"BTC","start_timestamp":ms(a),
                              "end_timestamp":end_ms,"resolution":"1D"})

def parse_page(raw,a,b,end_ms):
    obj=json.loads(raw)
    if obj.get("jsonrpc")!="2.0" or obj.get("error") is not None:
        raise ValueError("Deribit error: "+str(obj.get("error"))[:300])
    result=obj["result"]
    rows=result["data"];cursor=result["continuation"]
    if not isinstance(rows,list) or len(rows)>PAGE_DAYS+1:
        raise ValueError("Unexpected DVOL page size")
    if cursor is not None and (type(cursor) is not int or not ms(a)<=cursor<end_ms):
        raise ValueError("Invalid/non-progressing Deribit continuation")
    out={}
    for r in rows:
        if not isinstance(r,list) or len(r)!=5 or type(r[0]) is not int:
            raise ValueError("Invalid DVOL candle")
        t=r[0]
        if t%MS_DAY or not ms(a)<=t<ms(b) or t>end_ms:
            raise ValueError("DVOL timestamp outside requested UTC day range")
        if any(type(v) not in (int,float) or not math.isfinite(v) for v in r[1:]):
            raise ValueError("Invalid DVOL numeric field")
        op,hi,lo,cl=map(float,r[1:])
        if not 0<lo<=min(op,cl)<=max(op,cl)<=hi<=1000:
            raise ValueError("Invalid DVOL OHLC or percent scale")
        d=date_at(t//1000)
        if d in out:
            raise ValueError("Duplicate date in DVOL page")
        out[d]=(op,hi,lo,cl)
    return out,cursor

def get_page(root,a,b,end_ms,fetcher):
    address=url(a,end_ms)
    path=root/"cache"/f"{a}_{end_ms}.json"
    meta=path.with_suffix(".meta.json")
    if path.exists() and meta.exists():
        raw=path.read_bytes();info=json.loads(meta.read_bytes())
        if info["url"]!=address or info["sha256"]!=digest(raw):
            raise ValueError("Cached DVOL response changed")
    elif path.exists() or meta.exists():
        raise ValueError("Incomplete DVOL cache pair")
    else:
        raw=download(address,fetcher)
        parse_page(raw,a,b,end_ms)
        info={"url":address,"sha256":digest(raw),
              "retrieved_utc":datetime.now(timezone.utc).isoformat()}
        atomic_write(path,raw);json_write(meta,info)
    rows,cursor=parse_page(raw,a,b,end_ms)
    return rows,cursor,info

def collect(root,fetcher=fetch):
    out={};errors=[];pages=[]
    for a,b in windows(START,DEV_END,PAGE_DAYS):
        print("DVOL:",a,b,flush=True)
        end_ms=ms(b)-1
        segment={}
        try:
            for _ in range(PAGE_DAYS+1):
                rows,cursor,info=get_page(root,a,b,end_ms,fetcher)
                pages.append(info)
                for d,r in rows.items():
                    if d in segment and segment[d]!=r:
                        raise ValueError("Conflicting overlapping DVOL candles")
                    segment[d]=r
                if cursor is None:
                    break
                end_ms=cursor
            else:
                raise ValueError("DVOL pagination limit exceeded")
            if set(segment)&set(out):
                raise ValueError("Overlapping DVOL windows")
            out.update(segment)
        except (OSError,ValueError,KeyError,TypeError,OverflowError) as e:
            errors.append({"start":a.isoformat(),"end_exclusive":b.isoformat(),"reason":str(e)})
    expected=[START+i*DAY for i in range((DEV_END-START).days)]
    by_year={}
    for d in expected:
        z=by_year.setdefault(str(d.year),{"expected":0,"valid":0})
        z["expected"]+=1;z["valid"]+=int(d in out)
    # Percent vs fraction is defined by Deribit methodology, but detect a
    # gross scale anomaly before using this archive as annualized percent.
    med=float(np.median([r[3] for r in out.values()])) if out else None
    gate=(not errors and len(out)>=.95*len(expected)
          and all(z["valid"]>=.90*z["expected"] for z in by_year.values())
          and med is not None and 5<=med<=300)
    q={"source":"Deribit BTC DVOL","expected":len(expected),"valid":len(out),
       "missing_dates":[d.isoformat() for d in expected if d not in out],
       "by_year":by_year,"errors":errors,"pages":pages,"median_close":med,
       "coverage_gate":bool(gate),"first":min(out).isoformat() if out else None,
       "last":max(out).isoformat() if out else None}
    if gate:
        target=root/"dvol_snapshot.json"
        snapshot={"schema":1,"unit":"annualized_volatility_percent","rows":{
            d.isoformat():list(r) for d,r in sorted(out.items())}}
        if target.exists() and json.loads(target.read_bytes())!=snapshot:
            raise ValueError("DVOL snapshot changed; retain original")
        if not target.exists():
            json_write(target,snapshot)
        q["snapshot_sha256"]=digest(target.read_bytes())
    json_write(root/"coverage.json",q)
    if not gate:
        raise ValueError("DVOL coverage/scale gate failed; send coverage.json")
    return out,q

def compare(prices,values,end=DEV_END):
    if end>DEV_END or any(d>=DEV_END for d in prices) or any(d>=DEV_END for d in values):
        raise ValueError("Post-development numeric data not allowed")
    rows=[];missing=[]
    # Sunday 00 UTC origin, matching the Saturday DVOL close and price
    # information cutoff. No Monday execution proxy for this variance task.
    for t in mondays(START,end):
        sunday=t-DAY;saturday=t-2*DAY
        if saturday<START or sunday+(H+1)*DAY>end:
            continue
        s=state(prices,t);r=values.get(saturday)
        y=outcome(prices,sunday,H)
        if s is None or r is None or y is None:
            missing.append(sunday.isoformat());continue
        implied=(r[3]/100)**2/365
        ewma=max(1e-12,s["sigma"]**2)
        actual=y["variance"]
        rows.append({"origin":sunday.isoformat(),"dvol_date":saturday.isoformat(),
                     "dvol_annual_pct":r[3],"ewma_annual_pct":100*math.sqrt(365*ewma),
                     "realized_annual_pct":100*math.sqrt(365*actual),
                     "daily_variance":{"dvol":implied,"ewma":ewma,"actual":actual},
                     "qlike":{"dvol":math.log(implied)+actual/implied,
                              "ewma":math.log(ewma)+actual/ewma}})
    return rows,missing

def summarize(rows):
    if not rows:
        return {"n":0}
    actual=np.array([r["realized_annual_pct"] for r in rows])
    out={"n":len(rows),"mean_realized_annual_pct":float(actual.mean()),"models":{}}
    for model in ("dvol","ewma"):
        p=np.array([r[model+"_annual_pct"] for r in rows])
        out["models"][model]={"mean_annual_pct":float(p.mean()),
            "mean_error_volatility_pp":float((p-actual).mean()),
            "mae_volatility_pp":float(np.abs(p-actual).mean()),
            "mean_qlike":float(np.mean([r["qlike"][model] for r in rows]))}
    return out

def run(root=ROOT,price_root=PRICE_ROOT,fetcher=fetch):
    root=Path(root);target=root/"dvol_report.json"
    if target.exists():
        raise ValueError("Report already exists; preserve original")
    v,quality=collect(root,fetcher)
    markets={}
    for m in HASHES:
        p=load_development(Path(price_root),m)
        rows,missing=compare(p,v)
        if not rows:
            raise ValueError("No matched DVOL/price observations")
        markets[m]={"summary":summarize(rows),"first":rows[0]["origin"],
                    "last":rows[-1]["origin"],"missing":missing,
                    "by_year":{str(y):summarize([r for r in rows if r["origin"].startswith(str(y))])
                               for y in range(START.year,DEV_END.year)},
                    "observations":rows}
    report={"protocol":VERSION,"kind":"data_audit_and_descriptive_reference",
            "confirmation_authorized":False,"price_hashes":HASHES,"quality":quality,
            "markets":markets,"test_numeric_values_parsed":False,
            "limitations":["DVOL is annualized option-implied volatility, not physical probability.",
                "Daily OHLC UTC alignment validated; original index vintage and exact publication lag not independently verified.",
                "Saturday close assumed available Sunday cutoff; no historical PIT proof.",
                "30-day daily open-to-open mean squared log returns approximate realized variance; option index methodology and underlying differ.",
                "Variance risk premium, jumps and bid/ask may cause systematic differences.",
                "Weekly windows overlap, exchanges share episodes; no inference, fit, trade rule or selection.",
                "No skew or term structure reconstructed, no 2024+ numeric data."]}
    json_write(target,report)
    print("Send",target,flush=True)
    return report

if __name__=="__main__":
    run()
