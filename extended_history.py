"""Free history providers. Local private use; no credentials or datasets in Git."""
import json
import math
import os
import time
from datetime import datetime, timezone, timedelta
from getpass import getpass
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen, build_opener, HTTPRedirectHandler
from urllib.error import HTTPError

ROOT=Path(__file__).resolve().parent
DATA=ROOT/"data"/"extended"
KEYS=ROOT/"data"/"provider_keys.json"
TFTC_URL="https://www.tftc.io/bitcoin-etf-flows/data.json"
KOTE_BASE="https://kotecharts.com/api/v1/public/charts/"
COIN_BASE="https://api.coinalyze.net/v1/"
KOTE_FIELDS={"mvrv":("mvrv",),"mvrv-z-score":("mvrvZ",),"nupl":("nupl",),"sth-lth-sopr":("sthSopr","lthSopr")}
COIN_FIELDS={"open-interest-history":("c",),"funding-rate-history":("c",),"liquidation-history":("l","s")}
LOCAL_FILES={"local/tftc.json","local/coinalyze.json","local/binance-spot.json"}|{"local/kote-"+c+".json" for c in KOTE_FIELDS}

class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None

def request_json(url, params=None, headers=None):
    if params:url+="?"+urlencode(params)
    req=Request(url,headers={"User-Agent":"btc-lab/1.0","Accept":"application/json",**(headers or {})})
    # Never forward API credentials on redirects.
    opener=build_opener(NoRedirect()) if headers else build_opener()
    try:
        with opener.open(req,timeout=40) as response:
            raw=response.read(12_000_001)
    except HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}") from None
    if len(raw)>12_000_000:raise ValueError("Response too large")
    return json.loads(raw.decode("utf-8-sig"))

def numeric(v):
    return isinstance(v,(int,float)) and not isinstance(v,bool) and math.isfinite(v)

def day_key(s):
    if not isinstance(s,str) or len(s)!=10:return None
    try:
        d=datetime.strptime(s,"%Y-%m-%d").date()
        return d.isoformat() if d.isoformat()==s else None
    except ValueError:return None

def today():
    return datetime.now(timezone.utc).date()

def make_doc(source, series, **meta):
    return {"schema":1,"source":source,"downloaded_utc":datetime.now(timezone.utc).isoformat(),"series":series,**meta}

def parse_etf(doc, now=None):
    now=now or today()
    if not isinstance(doc,dict) or doc.get("units")!="USD" or "spot bitcoin" not in str(doc.get("name","")).lower() or not str(doc.get("license","")).endswith("/by/4.0/"):
        raise ValueError("Wrong ETF scope, units or licence")
    candidates=[doc[k] for k in ("days","sessions","daily","data","rows","history","dailyFlows") if isinstance(doc.get(k),list) and any(isinstance(r,dict) and "netFlowUsd" in r for r in doc[k])]
    if len(candidates)!=1:raise ValueError("Ambiguous or missing ETF rows")
    result={}
    for row in candidates[0]:
        if not isinstance(row,dict):continue
        d=day_key(row.get("date") or row.get("day"))
        if d is None or d>now.isoformat() or datetime.fromisoformat(d).weekday()>4:continue
        v=row.get("netFlowUsd")
        if d in result:raise ValueError("Duplicate ETF session")
        result[d]=float(v) if numeric(v) else None
    if sum(v is not None for v in result.values())<21:raise ValueError("Insufficient ETF sessions")
    return make_doc("TFTC",{"net_flow_usd":result},attribution="The Commoner Bitcoin ETF Tracker by TFTC",url=TFTC_URL,license="CC BY 4.0")

def point_arrays(obj, fields):
    if isinstance(obj,list):
        if obj and all(isinstance(r,dict) and "t" in r for r in obj):
            if any(all(k in r for k in fields) for r in obj):yield obj
        else:
            for v in obj:yield from point_arrays(v,fields)
    elif isinstance(obj,dict):
        for v in obj.values():yield from point_arrays(v,fields)

def parse_kote(doc, chart, now=None):
    now=now or today()
    fields=KOTE_FIELDS[chart]
    if not isinstance(doc,dict) or doc.get("success") is not True:raise ValueError("Kote request unsuccessful")
    candidates=list(point_arrays(doc.get("data"),fields))
    if len(candidates)!=1:raise ValueError("Missing or ambiguous Kote chart fields")
    result={k:{} for k in fields}
    for row in candidates[0]:
        t=row["t"]
        if isinstance(t,str):
            d=day_key(t)
            if d is None:
                try:
                    ts=datetime.fromisoformat(t.replace("Z","+00:00"))
                    if ts.tzinfo is None or ts.astimezone(timezone.utc).time()!=datetime.min.time():continue
                    d=ts.astimezone(timezone.utc).date().isoformat()
                except ValueError:continue
        elif numeric(t):
            try:
                ts=datetime.fromtimestamp(t/1000 if t>1e11 else t,timezone.utc)
                if ts.time()!=datetime.min.time():continue
                d=ts.date().isoformat()
            except (ValueError,OverflowError,OSError):continue
        else:continue
        if d>=now.isoformat() or row.get("partial") is True:continue
        for k in fields:
            if d in result[k]:raise ValueError("Duplicate Kote day")
            v=row.get(k)
            result[k][d]=float(v) if numeric(v) else None
    if any(sum(v is not None for v in r.values())<7 for r in result.values()):raise ValueError("Insufficient Kote history")
    return make_doc("Kote Charts",result,chart=chart,url="https://kotecharts.com/c/"+chart,license="https://kotecharts.com/license")

def select_binance(exchanges, markets):
    if not isinstance(exchanges,list) or not isinstance(markets,list):raise ValueError("Invalid market catalog")
    codes={x.get("code") for x in exchanges if isinstance(x,dict) and str(x.get("name","")).lower() in ("binance","binance futures","binance usdt-m","binance usd-m")}
    candidates=[m for m in markets if isinstance(m,dict) and m.get("exchange") in codes and m.get("symbol_on_exchange")=="BTCUSDT" and m.get("base_asset")=="BTC" and m.get("quote_asset")=="USDT" and m.get("is_perpetual") is True and m.get("margined")=="STABLE" and isinstance(m.get("symbol"),str)]
    if len(candidates)!=1:raise ValueError("Cannot uniquely identify Binance BTCUSDT perpetual")
    return candidates[0]["symbol"]

def parse_coin(doc, symbol, endpoint, now=None):
    now=now or today()
    if not isinstance(doc,list) or len(doc)!=1 or not isinstance(doc[0],dict) or doc[0].get("symbol")!=symbol or not isinstance(doc[0].get("history"),list):raise ValueError("Unexpected Coinalyze market")
    out={k:{} for k in COIN_FIELDS[endpoint]}
    for row in doc[0]["history"]:
        if not isinstance(row,dict) or not isinstance(row.get("t"),int) or isinstance(row["t"],bool) or row["t"]%86400:continue
        try:d=datetime.fromtimestamp(row["t"],timezone.utc).date().isoformat()
        except (ValueError,OverflowError,OSError):continue
        if d>=now.isoformat():continue
        for k in out:
            if d in out[k]:raise ValueError("Duplicate Coinalyze day")
            v=row.get(k)
            if endpoint!="funding-rate-history" and numeric(v) and v<0:v=None
            out[k][d]=float(v) if numeric(v) else None
    if any(sum(v is not None for v in r.values())<7 for r in out.values()):raise ValueError("Insufficient Coinalyze history")
    return out

def write_local(path, doc):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(".tmp")
    temp.write_text(json.dumps(doc,ensure_ascii=False,allow_nan=False),encoding="utf-8")
    temp.replace(path)

def read_local(path):
    if path not in LOCAL_FILES:raise ValueError("Unknown local history")
    return json.loads((DATA/path.split("/")[-1]).read_text(encoding="utf-8"))

def load_keys():
    old={}
    if KEYS.exists():
        old=json.loads(KEYS.read_text(encoding="utf-8"))
        if not isinstance(old,dict):raise ValueError("Invalid local key file")
    for name in ("KOTE_API_KEY","COINALYZE_API_KEY"):
        if os.environ.get(name):old[name]=os.environ[name]
        elif not old.get(name):
            value=getpass(name+" (Enter to skip): ").strip()
            if value:old[name]=value
    if old:write_local(KEYS,old)
    return old

def merge_local(old,new):
    """Keep dates outside the new provider window; revisions replace overlaps."""
    identity=("schema","source","chart","market","symbol","interval","url")
    if any(old.get(k)!=new.get(k) for k in identity):raise ValueError("Archive identity changed; old file retained")
    if set(old["series"])!=set(new["series"]):raise ValueError("Archive fields changed; old file retained")
    return {**new,"series":{k:{**old["series"][k],**new["series"][k]} for k in new["series"]}}

def sync():
    # Only local data; no git commands or credential output.
    keys=load_keys()
    errors=[]
    def job(name,filename,fn):
        try:
            doc=fn()
            target=DATA/filename
            if target.exists():doc=merge_local(json.loads(target.read_text(encoding="utf-8")),doc)
            write_local(target,doc)
            counts={k:sum(v is not None for v in r.values()) for k,r in doc["series"].items()}
            print(name,"OK",counts,flush=True)
        except Exception as exc:
            print(name,"FAILED",type(exc).__name__,str(exc) if isinstance(exc,(ValueError,RuntimeError)) else "",flush=True)
            errors.append(name)
    job("ETF","tftc.json",lambda:parse_etf(request_json(TFTC_URL)))
    from binance_daily import download_daily
    job("Binance daily price/CVD","binance-spot.json",download_daily)
    if keys.get("KOTE_API_KEY"):
        for chart in KOTE_FIELDS:
            job("Kote "+chart,"kote-"+chart+".json",lambda chart=chart:parse_kote(request_json(KOTE_BASE+chart,{"from":"2013-01-01","granularity":"day"},{"X-API-Key":keys["KOTE_API_KEY"]}),chart))
            time.sleep(.5)
    else:print("Kote skipped: no key")
    if keys.get("COINALYZE_API_KEY"):
        def coin():
            headers={"api_key":keys["COINALYZE_API_KEY"]}
            symbol=select_binance(request_json(COIN_BASE+"exchanges",headers=headers),request_json(COIN_BASE+"future-markets",headers=headers))
            end=int(datetime.combine(today(),datetime.min.time(),timezone.utc).timestamp())
            start=int(datetime(2019,1,1,tzinfo=timezone.utc).timestamp())
            combined={}
            for endpoint in COIN_FIELDS:
                params={"symbols":symbol,"interval":"daily","from":start,"to":end-1}
                if endpoint!="funding-rate-history":params["convert_to_usd"]="true"
                values=parse_coin(request_json(COIN_BASE+endpoint,params,headers),symbol,endpoint)
                for k,v in values.items():combined[endpoint+"."+k]=v
                time.sleep(.2)
            return make_doc("Coinalyze",combined,market="Binance BTCUSDT perpetual",symbol=symbol,url="https://api.coinalyze.net/v1/doc/",interval="daily")
        job("Coinalyze","coinalyze.json",coin)
    else:print("Coinalyze skipped: no key")
    print("Done. Existing files are kept if a download fails.")
    return bool(errors)

if __name__=="__main__":
    raise SystemExit(int(sync()))
