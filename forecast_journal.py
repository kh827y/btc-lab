"""Manual prospective BTC forecast journal. No trading, credentials or agents."""
import argparse
import json
import math
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from binance_daily import URL, DAY, parse_klines
from extended_history import request_json
from binance_minute import digest

ROOT=Path(__file__).resolve().parent/"data"/"research"/"forecast"
TIME_URL="https://data-api.binance.vision/api/v3/time"
VERSION="journal-empirical-v1"
HORIZONS=(7,28,90)
LOOKBACK=1000
RISK=-.15
BUFFER=10*60_000


def iso(t):
    return datetime.fromtimestamp(t/1000,timezone.utc).isoformat()


def day(t):
    return iso(t)[:10]


def week(t):
    y,w,_=datetime.fromtimestamp(t/1000,timezone.utc).isocalendar()
    return f"{y}-W{w:02d}"


def server_time(fetch):
    t=fetch(TIME_URL)["serverTime"]
    if type(t) is not int or not 1_500_000_000_000<t<4_000_000_000_000:
        raise ValueError("Invalid exchange clock")
    return t


def encode(obj):
    return (json.dumps(obj,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+"\n").encode("utf-8")


def new_file(path,obj):
    """Never overwrite a journal record; clean only our own failed write."""
    raw=encode(obj)
    with path.open("xb") as f:
        try:
            f.write(raw)
            f.flush()
        except BaseException:
            f.close()
            path.unlink(missing_ok=True)
            raise
    return digest(raw)


def parse_prices(rows,start,stop):
    parse_klines(rows,start,stop)
    prices={}
    for r in rows:
        t=r[0]//1000 if r[0]>=10**14 else r[0]
        op,hi,lo,cl=map(float,r[1:5])
        if not all(math.isfinite(v) for v in (op,hi,lo,cl)) or not 0<lo<=min(op,cl)<=max(op,cl)<=hi:
            raise ValueError("Invalid OHLC")
        prices[t]=(op,hi,lo,cl)
    return prices


def candles(fetch,start,stop):
    n=(stop-start)//DAY
    if not 0<n<=1000 or start%DAY or stop%DAY:
        raise ValueError("Invalid candle request")
    rows=fetch(URL,{"symbol":"BTCUSDT","interval":"1d","startTime":start,
                    "endTime":stop-1,"limit":n,"timeZone":"0"})
    return rows,parse_prices(rows,start,stop)


def realized(prices,start,h):
    """Open-to-open return, daily log-return volatility and worst entry loss."""
    seq=[prices.get(start+i*DAY) for i in range(h+1)]
    if any(v is None for v in seq):
        return None
    opens=np.array([r[0] for r in seq])
    ret=float(opens[-1]/opens[0]-1)
    worst=min(0.,float(min(min(r[2] for r in seq[:-1]),opens[-1])/opens[0]-1))
    vol=float(np.std(np.diff(np.log(opens)),ddof=1))
    return {"return":ret,"worst_from_entry":worst,"daily_log_vol":vol,
            "up":int(ret>0),"loss_15":int(worst<=RISK)}


def empirical(prices,start,stop,h):
    # Only windows whose endpoint open is in the downloaded completed-day set.
    outcomes=[realized(prices,t,h) for t in range(start,stop-h*DAY,DAY)]
    good=[x for x in outcomes if x is not None]
    if len(good)<365 or len(good)<.9*len(outcomes):
        raise ValueError(f"Insufficient complete history for {h}d")
    n=len(good)
    y=[r["return"] for r in good]
    # Laplace smoothing prevents zero/one probabilities in finite history.
    return {"n":n,"candidate_n":len(outcomes),
            "p_up":(1+sum(r["up"] for r in good))/(n+2),
            "p_loss_15":(1+sum(r["loss_15"] for r in good))/(n+2),
            "return_quantiles":dict(zip(("0.1","0.5","0.9"),map(float,np.quantile(y,[.1,.5,.9])))),
            "daily_log_vol":float(np.mean([r["daily_log_vol"] for r in good]))}


def issue(root=ROOT,fetch=request_json):
    root=Path(root)
    before=server_time(fetch)
    stop=before//DAY*DAY
    origin=stop+DAY
    if origin-before<BUFFER:
        raise ValueError("Too close to next UTC midnight; retry after midnight")
    root.mkdir(parents=True,exist_ok=True)
    for p in sorted(root.glob("*/forecast.json")):
        record=json.loads(p.read_bytes())
        if record["iso_week"]==week(origin):
            print("Forecast already saved for this week:",p,flush=True)
            print("SHA256:",digest(p.read_bytes()),flush=True)
            return p
    start=stop-LOOKBACK*DAY
    raw,prices=candles(fetch,start,stop)
    if stop-DAY not in prices:
        raise ValueError("Latest closed day missing")
    models={str(h):empirical(prices,start,stop,h) for h in HORIZONS}
    after=server_time(fetch)
    if not before<=after<origin-BUFFER or after//DAY!=before//DAY:
        raise ValueError("Clock advanced beyond issuance window; no forecast saved")
    folder=root/day(origin)
    folder.mkdir(exist_ok=False)
    try:
        source={"source":URL,"market":"Binance BTCUSDT spot","start_ms":start,
                "stop_exclusive_ms":stop,"observed_before_ms":before,"observed_after_ms":after,
                "rows":raw}
        hsh=new_file(folder/"source.json",source)
        record={"version":VERSION,"market":"Binance BTCUSDT spot","iso_week":week(origin),
                "origin_ms":origin,"origin_utc":iso(origin),"issued_exchange_ms":after,
                "issued_exchange_utc":iso(after),"input_stop_exclusive_ms":stop,
                "source_sha256":hsh,"last_closed_price":prices[stop-DAY][3],
                "weekly_schedule":datetime.fromtimestamp(origin/1000,timezone.utc).weekday()==0,
                "models":{"empirical":models,"zero_return":{str(h):0. for h in HORIZONS}},
                "anchor_status":"not independently anchored by this script",
                "limitations":["Rolling overlapping windows, not independent observations.",
                               "Exchange clock is not proof of external receipt.",
                               "Baseline estimates, not trading recommendations."]}
        p=folder/"forecast.json"
        sha=new_file(p,record)
    except BaseException:
        # Only remove files created in this new directory on failed issuance.
        for name in ("source.json","forecast.json"):
            (folder/name).unlink(missing_ok=True)
        folder.rmdir()
        raise
    print("Forecast:",p,flush=True)
    print("SHA256:",sha,flush=True)
    print("External receipt must precede:",iso(origin),flush=True)
    print(json.dumps(record["models"]["empirical"],indent=2))
    return p


def score_model(model,y):
    result={"brier_up":(model["p_up"]-y["up"])**2,
            "brier_loss_15":(model["p_loss_15"]-y["loss_15"])**2,
            "median_abs_error":abs(model["return_quantiles"]["0.5"]-y["return"]),
            "zero_abs_error":abs(y["return"]),
            "vol_abs_error":abs(model["daily_log_vol"]-y["daily_log_vol"])}
    result["pinball"]={}
    for q,v in model["return_quantiles"].items():
        err=y["return"]-v
        a=float(q)
        result["pinball"][q]=max(a*err,(a-1)*err)
    result["interval_10_90_hit"]=int(model["return_quantiles"]["0.1"]<=y["return"]<=model["return_quantiles"]["0.9"])
    return result


def settle(root=ROOT,fetch=request_json):
    now=server_time(fetch)
    closed=now//DAY*DAY
    saved=0
    for p in sorted(Path(root).glob("*/forecast.json")):
        raw=p.read_bytes()
        f=json.loads(raw)
        if f["version"]!=VERSION or digest((p.parent/"source.json").read_bytes())!=f["source_sha256"]:
            raise ValueError("Unknown version or changed input: "+str(p))
        origin=f["origin_ms"]
        if not f["issued_exchange_ms"]<origin or origin%DAY:
            raise ValueError("Invalid forecast timing")
        for h in HORIZONS:
            target=p.parent/f"outcome_{h}d.json"
            if target.exists():
                if json.loads(target.read_bytes())["forecast_sha256"]!=digest(raw):
                    raise ValueError("Forecast changed after scoring")
                continue
            # Require the endpoint day to be fully closed. Scoring can be one day late,
            # but uses exactly the previously defined endpoint opening price.
            stop=origin+(h+1)*DAY
            if closed<stop:
                continue
            rows,prices=candles(fetch,origin,stop)
            y=realized(prices,origin,h)
            if y is None:
                print("Missing outcome candles:",p.parent.name,h,flush=True)
                continue
            result={"version":VERSION,"forecast_sha256":digest(raw),"horizon_days":h,
                    "observed_exchange_ms":server_time(fetch),"outcome":y,
                    "score":score_model(f["models"]["empirical"][str(h)],y),
                    "source_rows":rows,"anchor_status":"external receipt must be verified separately"}
            new_file(target,result)
            saved+=1
    print("New settled outcomes:",saved,flush=True)
    return saved


def status(root=ROOT):
    for p in sorted(Path(root).glob("*/forecast.json")):
        print(p.parent.name,digest(p.read_bytes()),"settled:",
              ",".join(str(h) for h in HORIZONS if (p.parent/f"outcome_{h}d.json").exists()) or "none")


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("command",choices=("issue","settle","status"),default="issue",nargs="?")
    a=p.parse_args()
    {"issue":issue,"settle":settle,"status":status}[a.command]()
