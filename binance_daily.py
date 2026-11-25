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
        t=row[0]
        if not start<=t<end or t%DAY or row[6]!=t+DAY-1 or row[6]>=end or (previous is not None and t<=previous):raise ValueError("Invalid Binance UTC day/order")
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
    start=START
    combined={"net_quote_usdt":{},"close_usdt":{}}
    for _ in range(20):
        if start>=end:break
        rows=fetch(URL,{"symbol":"BTCUSDT","interval":"1d","startTime":start,"endTime":end-1,"limit":1000})
        part,last=parse_klines(rows,start,end)
        if last is None:break
        for k,v in part.items():combined[k].update(v)
        start=last+DAY
    if len(combined["close_usdt"])<365 or start<end:raise ValueError("Incomplete Binance download; old archive retained")
    return make_doc("Binance Spot",combined,market="Binance BTCUSDT spot",interval="daily",url="https://developers.binance.com/docs/binance-spot-api-docs/rest-api/market-data-endpoints#klinecandlestick-data")
