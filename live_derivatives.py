"""Read-only readiness check of Binance BTCUSDT perpetual quantity and premium."""
import hashlib
import json
import math
import statistics
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode
from urllib.request import Request, urlopen

BASE = "https://fapi.binance.com"
HOUR = 3600000
ROOT = Path(__file__).resolve().parent / "data/research/live_derivatives"
SYMBOL = "BTCUSDT"


def iso(t):
    return datetime.fromtimestamp(t/1000, timezone.utc).isoformat()


def number(x):
    if isinstance(x, bool):
        raise ValueError("Boolean numeric field")
    v = float(x)
    if not math.isfinite(v):
        raise ValueError("Nonfinite numeric field")
    return v


def parse_oi(rows, start, end):
    if not isinstance(rows, list):
        raise ValueError("Invalid OI response")
    out = {}
    for r in rows:
        t = r["timestamp"]
        if (r["symbol"] != SYMBOL or type(t) is not int or t % HOUR or
                not start <= t <= end or t in out):
            raise ValueError("Wrong OI symbol, time or duplicate")
        q, v = number(r["sumOpenInterest"]), number(r["sumOpenInterestValue"])
        if q <= 0 or v <= 0:
            raise ValueError("Nonpositive OI")
        out[t] = (q,v)
    return out


def parse_bars(rows, start, end, positive=False):
    if not isinstance(rows, list):
        raise ValueError("Invalid kline response")
    out = {}
    for r in rows:
        if not isinstance(r,list) or len(r)!=12:
            raise ValueError("Wrong kline shape")
        t = r[0]
        if (type(t) is not int or t % HOUR or not start <= t < end or
                t in out or r[6] != t+HOUR-1):
            raise ValueError("Wrong kline time or duplicate")
        o,h,l,c = map(number,r[1:5])
        if not l <= min(o,c) <= max(o,c) <= h or (positive and l <= 0):
            raise ValueError("Invalid OHLC")
        out[t] = (o,h,l,c)
    return out


def summarize(oi, mark, premium, end):
    checked = {}
    rejected = []
    # Price sanity only: verify valuation per reported quantity against previous
    # mark-price hour, with a 2% tolerance for valuation convention/timing.
    # No division of aggregate USD OI to manufacture a quantity.
    for t,(q,v) in oi.items():
        bar = mark.get(t-HOUR)
        if bar is None or not .98*bar[2] <= v/q <= 1.02*bar[1]:
            rejected.append(iso(t))
        else:
            checked[t] = q
    result = {}
    for d in (1,7,28):
        start = end-d*24*HOUR
        times = range(start,end+HOUR,HOUR)
        p_times = range(start,end,HOUR)
        n = sum(t in checked for t in times)
        values = [premium[t][3] for t in p_times if t in premium]
        a,b = checked.get(start),checked.get(end)
        result[str(d)] = {
            "oi_expected_points":d*24+1,"oi_checked_points":n,
            "oi_start_btc":a,"oi_end_btc":b,
            "oi_change_pct":100*(b/a-1) if a is not None and b is not None else None,
            "premium_expected_hours":d*24,"premium_valid_hours":len(values),
            "premium_mean_close_fraction":statistics.mean(values) if len(values)==d*24 else None,
            "premium_negative_hour_share":sum(v<0 for v in values)/len(values) if len(values)==d*24 else None}
    return {"observed_end_utc":iso(end),"oi_unit_check_rejected":sorted(rejected),
            "windows":result,"oi_latest_checked_btc":checked.get(end),
            "premium_last_closed_fraction":premium[end-HOUR][3] if end-HOUR in premium else None}


def fetch(url):
    with urlopen(Request(url,headers={"User-Agent":"BTC-Lab public market data"}),timeout=30) as r:
        raw=r.read(2*1024*1024+1)
    if len(raw)>2*1024*1024:
        raise ValueError("Response too large")
    return raw


def run(root=ROOT, request=fetch):
    now=datetime.now(timezone.utc)
    # One full hour buffer, not proof of historical publication.
    end=(int(now.timestamp()*1000)//HOUR-1)*HOUR
    start=end-28*24*HOUR
    folder=Path(root)/now.strftime("%Y%m%dT%H%M%S%fZ")
    folder.mkdir(parents=True,exist_ok=False)
    sources=[]
    errors={}
    def get(name,path,params,parser):
        url=BASE+path+"?"+urlencode({"symbol":SYMBOL,**params})
        try:
            raw=request(url)
            (folder/(name+".json")).write_bytes(raw)
            sources.append({"name":name,"url":url,"sha256":hashlib.sha256(raw).hexdigest(),
                            "retrieved_utc":datetime.now(timezone.utc).isoformat()})
            return parser(json.loads(raw))
        except (OSError,ValueError,KeyError,TypeError,IndexError,OverflowError) as exc:
            errors[name]=str(exc)[:300]
            return {}
    oi={}
    for a,b in ((start,start+399*HOUR),(start+400*HOUR,end)):
        oi.update(get("oi_"+str(a),"/futures/data/openInterestHist",
            {"period":"1h","startTime":a,"endTime":b,"limit":400},
            lambda rows,a=a,b=b:parse_oi(rows,a,b)))
    mark=get("mark","/fapi/v1/markPriceKlines",
        {"interval":"1h","startTime":start-HOUR,"endTime":end-1,"limit":673},
        lambda rows:parse_bars(rows,start-HOUR,end,True))
    premium=get("premium","/fapi/v1/premiumIndexKlines",
        {"interval":"1h","startTime":start,"endTime":end-1,"limit":672},
        lambda rows:parse_bars(rows,start,end))
    report={"version":"live-derivatives-readiness-v1","market":"Binance USD-M BTCUSDT perpetual",
            "requested_utc":now.isoformat(),"retrieved_utc":datetime.now(timezone.utc).isoformat(),
            "sources":sources,"errors":errors,**summarize(oi,mark,premium,end),
            "limitations":["One contract, not the five-venue USD OI basket.",
                "Quantity checked by implied valuation vs mark range; does not measure leverage per trader or liquidation.",
                "Exact endpoint comparisons may survive interior gaps; coverage shown separately.",
                "Premium is an index, not realized trade basis or funding; mean of hourly closes.",
                "One-hour lag buffer, original publication time unknown. No forecast or signal."]}
    target=folder/"derivatives_readiness.json"
    with target.open("x",encoding="utf-8") as f:
        json.dump(report,f,indent=2,allow_nan=False)
    print("Send:",target,"SHA-256:",hashlib.sha256(target.read_bytes()).hexdigest())


if __name__=="__main__":
    run()
