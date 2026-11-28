"""Current spot demand breadth from the existing hourly archive, not a predictor."""
import hashlib
import json
import math
from datetime import timedelta
from urllib.request import Request, urlopen
from data_logic import parse_utc, is_real_number

URL="https://raw.githubusercontent.com/kh827y/btc-market-data/main/btc-spot-cvd/data/state.json"
LIMIT=4*1024*1024
BASKETS={"original_five":("binance","coinbase","okx","bybit","kraken"),
         "ex_coinbase":("binance","okx","bybit","kraken","bitget")}
SYMBOLS={"binance":("BTCUSDT","USDT"),"coinbase":("BTC-USD","USD"),
         "okx":("BTC-USDT","USDT"),"bybit":("BTCUSDT","USDT"),
         "kraken":("BTC_USD","USD"),"bitget":("BTCUSDT","USDT")}

def fetch():
    with urlopen(Request(URL,headers={"User-Agent":"BTC-Lab spot context"}),timeout=20) as r:
        raw=r.read(LIMIT+1)
    if len(raw)>LIMIT:
        raise ValueError("Hourly spot archive too large")
    return raw

def valid(row,venue,key):
    if not isinstance(row,dict) or row.get("complete") is not True or row.get("hour")!=key:
        return False
    buy,sell,net=(row.get(k) for k in ("buy","sell","net"))
    if not all(is_real_number(x) for x in (buy,sell,net)) or min(buy,sell)<0 or abs(buy-sell-net)>.021:
        return False
    symbol,quote=SYMBOLS[venue]
    source=row.get("source")
    if venue=="coinbase":
        return (source=="Coinbase Exchange public REST BTC-USD validated ID-continuous scan" and
                row.get("symbol")==symbol and row.get("quote")==quote and
                row.get("integrity")=="id_continuous_verified" and
                row.get("time_basis")=="exchange_trade_time")
    if venue=="kraken" and source=="Kraken official public REST Trades":
        symbol="XBTUSD"
    elif venue=="binance" and source=="Binance official SPOT closed 1h kline":
        if row.get("integrity")!="closed_1h_quote_and_taker_buy_quote_verified":
            return False
    elif source!="CryptoHFTData":
        return False
    return row.get("symbol")==symbol and row.get("quote")==quote

def signs(values):
    return {"positive":sum(v>0 for v in values),"negative":sum(v<0 for v in values),
            "zero":sum(v==0 for v in values)}

def calculate(state,demand,now):
    """Reconcile exact nested 24/168h totals to the already usable brief."""
    hourly=state.get("hourly",{})
    out={"version":"spot-breadth-v1","baskets":{},"limitations":[
        "Fixed selected venues, not global demand. Baskets overlap.",
        "UTC rolling 24h blocks, not calendar trading days. Mixed trade/receive time conventions.",
        "Direction counts are descriptive, not independent votes or probability estimates.",
        "Reconciled to published net totals; underlying trades not independently re-audited."]}
    for name,venues in BASKETS.items():
        context=demand.get("spot",{}).get(name,{})
        end=parse_utc(context.get("observed_end_utc"))
        result={"status":"unavailable","venues":list(venues),"observed_end_utc":None,
                "invalid_hours":{}}
        out["baskets"][name]=result
        if (context.get("status")!="usable" or end is None or not timedelta(0)<=now-end<=timedelta(hours=4)
            or end.minute or end.second or end.microsecond or context.get("venues")!=list(venues)):
            result["reason"]="brief_window_unavailable_or_stale"
            continue
        times=[(end-timedelta(hours=i)).strftime("%Y-%m-%dT%H:00:00Z") for i in range(168,0,-1)]
        series={}
        basis={}
        for venue in venues:
            archive=hourly.get(venue,{})
            rows=[archive.get(key) for key in times]
            bad=sum(not valid(row,venue,key) for row,key in zip(rows,times))
            result["invalid_hours"][venue]=bad
            if bad:
                continue
            series[venue]=[round(math.fsum(r["net"] for r in rows[i:i+24]),2) for i in range(0,168,24)]
            basis[venue]=sorted({r["source"] for r in rows})
        if len(series)!=len(venues):
            result["reason"]="incomplete_or_invalid_hourly_archive"
            continue
        daily=[round(math.fsum(series[v][i] for v in venues),2) for i in range(7)]
        latest=context.get("last_24h_usd_approx")
        prior=context.get("prior_144h_usd_approx")
        if (not is_real_number(latest) or not is_real_number(prior) or
            abs(daily[-1]-latest)>.05 or abs(math.fsum(daily[:-1])-prior)>.1):
            result["reason"]="hourly_totals_disagree_with_brief"
            continue
        result.update(status="usable",observed_end_utc=end.isoformat(),
            daily_net_usd_approx=daily,venue_daily_net_usd_approx=series,
            source_types_by_venue=basis,days=signs(daily),
            last_24h_venue_signs=signs([v[-1] for v in series.values()]),
            full_168h_venue_signs=signs([round(math.fsum(v),2) for v in series.values()]))
    return out

def collect(folder,demand,now):
    raw=fetch()
    from datetime import datetime, timezone
    received=datetime.now(timezone.utc)
    path=folder/"spot_hourly.json"
    with path.open("xb") as f:
        f.write(raw)
    report=calculate(json.loads(raw),demand,max(now,received))
    report.update(source=URL,raw_path=path.name,raw_sha256=hashlib.sha256(raw).hexdigest(),
                  retrieved_utc=received.isoformat())
    return report
