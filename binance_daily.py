"""Binance public daily spot klines: price and actual taker quote flow."""
from datetime import datetime, timezone, timedelta
from decimal import Decimal, InvalidOperation
from extended_history import request_json, make_doc, today

URL="https://data-api.binance.vision/api/v3/klines"
DAY=86_400_000
START=int(datetime(2017,8,17,tzinfo=timezone.utc).timestamp()*1000)

def parse_klines(rows,start,end):
    if not isinstance(rows,list) or len(rows)>1000:raise ValueError("Invalid Binance kline response")
    out={"net_quote_usdt":{},"close_usdt":{}}
    previous=None
    for row in rows:
        if not isinstance(row,list) or len(row)!=12 or type(row[0]) is not int or type(row[6]) is not int:raise ValueError("Invalid Binance kline schema")
        t,close_time=row[0],row[6]
        # Some public Binance data use microseconds. Normalize only exact boundaries.
        if t>=10**14 and close_time>=10**14 and t%1000==0 and close_time%1000==999:
            t,close_time=t//1000,close_time//1000
        if not start<=t<end or t%DAY or close_time!=t+DAY-1 or close_time>=end or (previous is not None and t<=previous):raise ValueError(f"Invalid Binance UTC day/order: open={row[0]} close={row[6]} normalized={t} request={start}..{end}")
        previous=t
        try:total,buy,close=(Decimal(str(row[i])) for i in (7,10,4))
        except InvalidOperation:raise ValueError("Invalid Binance numeric field") from None
        if not all(v.is_finite() for v in (total,buy,close)) or not 0<=buy<=total or close<=0:raise ValueError("Invalid Binance volume/price")
        day=datetime.fromtimestamp(t/1000,timezone.utc).date().isoformat()
        out["net_quote_usdt"][day]=float(2*buy-total)
        out["close_usdt"][day]=float(close)
    return out,previous

def download_daily(fetch=request_json,now=None):
    now=now or today()
    end=int(datetime.combine(now,datetime.min.time(),timezone.utc).timestamp()*1000)
    combined={"net_quote_usdt":{},"close_usdt":{}}
    rejected={}
    # Fixed calendar windows, not a cursor based on the last returned candle.
    # Isolate malformed days instead of throwing away the entire history.
    for start in range(START,end,DAY*1000):
        stop=min(start+DAY*1000,end)
        rows=fetch(URL,{"symbol":"BTCUSDT","interval":"1d","startTime":start,"endTime":stop-1,"limit":1000,"timeZone":"0"})
        if not isinstance(rows,list) or len(rows)>1000:raise ValueError("Invalid Binance page")
        seen=set()
        for row in rows:
            if not isinstance(row,list) or not row or type(row[0]) is not int:raise ValueError("Unidentifiable Binance day")
            t=row[0]//1000 if row[0]>=10**14 else row[0]
            if not start<=t<stop:raise ValueError(f"Binance returned date outside request: {row[0]}")
            day=datetime.fromtimestamp(t/1000,timezone.utc).date().isoformat()
            try:
                if day in seen:raise ValueError("Duplicate UTC day")
                part,_=parse_klines([row],start,stop)
                for k,v in part.items():combined[k].update(v)
            except ValueError as exc:
                rejected[day]=str(exc)
                for k in combined:combined[k][day]=None
            seen.add(day)
        # Missing days are explicit; never invent zero volume.
        for t in range(start,stop,DAY):
            day=datetime.fromtimestamp(t/1000,timezone.utc).date().isoformat()
            if day not in seen:
                rejected[day]="No candle returned"
                for k in combined:combined[k][day]=None
    count=sum(v is not None for v in combined["close_usdt"].values())
    if count<365 or count<.95*len(combined["close_usdt"]):raise ValueError(f"Binance coverage too low: {count}/{len(combined['close_usdt'])}; old archive retained")
    if rejected:
        print(f"Binance: {len(rejected)} rejected/missing days; shown as gaps. Examples: {list(rejected.items())[:3]}",flush=True)
    return make_doc("Binance Spot",combined,market="Binance BTCUSDT spot",interval="daily",url="https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints#klinecandlestick-data",rejected_days=rejected)
