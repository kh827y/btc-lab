"""Historical archive adapters. No UI, network, or trading recommendations."""
from datetime import datetime, timezone
import pandas as pd
from data_logic import at, is_real_number

PRICE="btc-price/data/history.json"
OI="btc-derivatives/data/latest.json"
CVD="btc-spot-cvd/data/state.json"
BITVIEW="btc-onchain/data/bitview_history.json"
ONCHAIN="btc-onchain/data/history.json"
FRED="btc-macro/data/fred_history.json"
OPTIONS="btc-options/data/derived_history.json"
ETF="btc-macro/data/latest.json"
FULL_ETF="local/tftc.json"
COINALYZE="local/coinalyze.json"
OI_VENUES={"Binance","Bybit","OKX","Gate.io","Hyperliquid"}
CVD_VENUES=("binance","coinbase","okx","bybit","kraken")

# label: file, path, frequency, unit, note
METRICS={
    "ETF США · полная история TFTC": (FULL_ETF,"series.net_flow_usd",None,"USD","The Commoner Bitcoin ETF Tracker by TFTC, CC BY 4.0; опубликованные сессии, возможны ревизии"),
    "OI · Binance BTCUSDT · Coinalyze": (COINALYZE,"series.open-interest-history.c","D","USD","Один бессрочный контракт Binance BTCUSDT, USD close дневного интервала; не корзина пяти бирж"),
    "Funding · Binance BTCUSDT · Coinalyze": (COINALYZE,"series.funding-rate-history.c","D","ед. API","Дневное close ряда funding от Coinalyze; не сумма расчётов за день и не подтверждённая нормализация 8h"),
    "Ликвидации LONG · Binance · Coinalyze": (COINALYZE,"series.liquidation-history.l","D","USD","Binance BTCUSDT perpetual; наблюдаемые дневные ликвидации LONG"),
    "Ликвидации SHORT · Binance · Coinalyze": (COINALYZE,"series.liquidation-history.s","D","USD","Binance BTCUSDT perpetual; наблюдаемые дневные ликвидации SHORT"),
    "MVRV · Kote Charts": ("local/kote-mvrv.json","series.mvrv","D","отношение","Kote Charts; отдельная UTXO-методика, личное исследование"),
    "MVRV Z-Score · Kote Charts": ("local/kote-mvrv-z-score.json","series.mvrvZ","D","z-score","Kote Charts; отдельная UTXO-методика"),
    "NUPL · Kote Charts": ("local/kote-nupl.json","series.nupl","D","доля","Kote Charts; отдельная UTXO-методика"),
    "STH SOPR · Kote Charts": ("local/kote-sth-lth-sopr.json","series.sthSopr","D","отношение","Kote Charts; UTXO 155 дней, не Bitview 150 дней"),
    "LTH SOPR · Kote Charts": ("local/kote-sth-lth-sopr.json","series.lthSopr","D","отношение","Kote Charts; UTXO 155 дней, не Bitview 150 дней"),
    "Цена BTC · закрытие дня": (PRICE,"daily_closed","D","USDT","Binance BTCUSDT spot; закрытые дневные свечи"),
    "Объём спота Binance": (PRICE,"daily_closed","D","BTC","Объём закрытой дневной свечи"),
    "Открытый интерес · 5 бирж": (OI,"results.open_interest.daily_history","D","USD","Binance, Bybit, OKX, Gate.io, Hyperliquid; 23:00 UTC, только закрытые дни"),
    "CVD · нетто за час · 5 бирж": (CVD,"hourly","h","USD ≈ USDT","Binance, Coinbase, OKX, Bybit, Kraken; время сделки/получения смешано; каждый час требует все 5 площадок и ID proof Coinbase. Не накопительная сумма."),
    "ETF США · последние 5 сессий": (ETF,"etf.last_five_sessions",None,"USD","TFTC; только 5 опубликованных сессий, не полный архив; CC BY 4.0"),
    "Себестоимость сети · Bitview": (BITVIEW,"realized_price_bitview","D","USD","Bitview UTXO; отдельная методика"),
    "Себестоимость STH · Bitview": (BITVIEW,"sth_realized_price_150d","D","USD","Bitview UTXO <150 дней"),
    "Себестоимость LTH · Bitview": (BITVIEW,"lth_realized_price_150d","D","USD","Bitview UTXO ≥150 дней"),
    "Запас LTH · Bitview": (BITVIEW,"lth_supply_150d","D","BTC","Bitview UTXO ≥150 дней"),
    "NUPL STH · Bitview": (BITVIEW,"sth_nupl_150d","D","доля","Bitview UTXO <150 дней"),
    "NUPL LTH · Bitview": (BITVIEW,"lth_nupl_150d","D","доля","Bitview UTXO ≥150 дней"),
    "MVRV · исходный ончейн": (ONCHAIN,"mvrv","D","отношение","Исторический ряд агрегатора; задержки поставщика, не смешивать с Bitview"),
    "NUPL · исходный ончейн": (ONCHAIN,"nupl","D","доля","Исторический ряд агрегатора; задержки поставщика"),
    "STH SOPR · исходный ончейн": (ONCHAIN,"sth_sopr","D","отношение","Исторический ряд агрегатора; задержки поставщика"),
    "LTH SOPR · исходный ончейн": (ONCHAIN,"lth_sopr","D","отношение","Исторический ряд агрегатора; задержки поставщика"),
    "Резервы бирж · Coin Metrics": (ONCHAIN,"exchange_reserves_btc","D","BTC","Исторический ряд агрегатора; состав адресов по источнику"),
    "UST 2Y · FRED": (FRED,"series.DGS2",None,"%","Дни публикации/наблюдения различаются; выходные и праздники без котировки"),
    "UST 10Y · FRED": (FRED,"series.DGS10",None,"%","Дни публикации/наблюдения различаются; выходные и праздники без котировки"),
    "Эффективная ставка ФРС": (FRED,"series.DFF","D","%","FRED DFF; возможны ревизии"),
    "Широкий индекс доллара · FRED": (FRED,"series.DTWEXBGS",None,"индекс","Не ICE DXY; только наблюдения, без заполнения выходных"),
    "Баланс ФРС · FRED": (FRED,"series.WALCL",None,"млн USD","Недельные наблюдения, даты публикации могут отличаться"),
    "Опционы · ATM IV 1M": (OPTIONS,"atm_iv_pct","h","%","Deribit; исторические почасовые снимки, пропуски не заполняются"),
    "Опционы · 25Δ RR 1M": (OPTIONS,"rr25_volpts","h","п.п.","Deribit; IV call минус put, исторические снимки"),
}

def stamp(value, daily=False):
    """Accept exact UTC day labels or explicitly zoned timestamps."""
    if not isinstance(value,str):
        return None
    try:
        if daily:
            if len(value)!=10 or datetime.strptime(value,"%Y-%m-%d").strftime("%Y-%m-%d")!=value:
                return None
            return pd.Timestamp(value,tz="UTC")
        v=datetime.fromisoformat(value.replace("Z","+00:00"))
        if v.tzinfo is None:
            return None
        return pd.Timestamp(v.astimezone(timezone.utc))
    except (ValueError, TypeError, OverflowError):
        return None

def number(v, positive=False):
    if not is_real_number(v) or (positive and v<=0):
        return None
    return float(v)

def series_for(label, doc, now=None):
    """Return UTC-indexed observations with null gaps. Never interpolate."""
    path,key,freq,unit,note=METRICS[label]
    if not isinstance(doc,dict):
        raise ValueError("Архив не является JSON-объектом")
    now=pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now).tz_convert("UTC")
    rows=[]
    def add(t,v,daily=False):
        ts=stamp(t,daily)
        if ts is None or ts>now or (freq=="h" and ts!=ts.floor("h")):
            return
        rows.append((ts,number(v)))
    raw=at(doc,key)
    if path==PRICE:
        instrument=doc.get("instrument") or {}
        if not isinstance(instrument,dict) or (instrument.get("venue"),instrument.get("symbol"),instrument.get("market"))!=("Binance","BTCUSDT","spot"):
            raise ValueError("Не совпадает инструмент цены")
        if not isinstance(raw,list): raise ValueError("Нет дневных свечей")
        field="close" if label.startswith("Цена") else "volume_btc"
        for row in raw:
            if isinstance(row,dict):
                ts=stamp(row.get("day"),True)
                if ts is not None and ts<now.floor("D"):
                    v=number(row.get(field),positive=field=="close")
                    add(row["day"],v if v is not None and v>=0 else None,True)
    elif path==OI:
        if not isinstance(raw,dict): raise ValueError("Нет дневной истории OI")
        if set(at(doc,"results.open_interest.venues",[]) or [])!=OI_VENUES:
            raise ValueError("Изменился состав корзины OI")
        for day,row in raw.items():
            ts=stamp(day,True)
            if ts is None or ts>=now.floor("D"):continue
            v=None
            if isinstance(row,dict):
                hour=stamp(row.get("hour"))
                venues=row.get("venues")
                total=number(row.get("five_venue_usd"),positive=True)
                if hour==ts+pd.Timedelta(hours=23) and isinstance(venues,dict) and set(venues)==OI_VENUES and all(number(x,positive=True) is not None for x in venues.values()) and total is not None and abs(sum(venues.values())-total)<=max(1,total*1e-7):
                    v=total
            add(day,v,True)
    elif path==CVD:
        if not isinstance(raw,dict) or not all(isinstance(raw.get(v),dict) for v in CVD_VENUES):
            raise ValueError("Нет полной структуры фиксированной корзины CVD")
        hours=set().union(*(raw[v].keys() for v in CVD_VENUES))
        for hour in hours:
            ts=stamp(hour)
            if ts is None or ts+pd.Timedelta(hours=1)>now:continue
            values=[]
            for venue in CVD_VENUES:
                r=raw[venue].get(hour)
                if not isinstance(r,dict) or r.get("complete") is not True or r.get("hour")!=hour:break
                if venue=="coinbase" and r.get("integrity")!="id_continuous_verified":break
                if r.get("quote") not in ("USD","USDT"):break
                buy,sell,net=(number(r.get(k)) for k in ("buy","sell","net"))
                if None in (buy,sell,net) or min(buy,sell)<0 or abs(buy-sell-net)>max(.05,abs(net)*1e-8):break
                values.append(net)
            add(hour,sum(values) if len(values)==len(CVD_VENUES) else None)
    elif path.startswith("local/"):
        expected="TFTC" if path==FULL_ETF else "Coinalyze" if path==COINALYZE else "Kote Charts"
        if doc.get("schema")!=1 or doc.get("source")!=expected or not isinstance(raw,dict):raise ValueError("Неверный источник локального архива")
        if path==COINALYZE and (doc.get("market")!="Binance BTCUSDT perpetual" or doc.get("interval")!="daily"):raise ValueError("Неверный рынок/интервал Coinalyze")
        if expected=="Kote Charts" and doc.get("chart")!=path.removeprefix("local/kote-").removesuffix(".json"):raise ValueError("Неверный график Kote")
        for day,value in raw.items():
            ts=stamp(day,True)
            if ts is not None and (path==FULL_ETF or ts<now.floor("D")):add(day,value,True)
    elif path==ETF:
        if not isinstance(raw,list):raise ValueError("Нет истории сессий ETF")
        for row in raw:
            if isinstance(row,dict):add(row.get("date"),row.get("net_flow_usd"),True)
    elif path==OPTIONS:
        for hour,row in doc.items():
            add(hour,at(row,"1M."+key) if isinstance(row,dict) else None)
    else:
        if not isinstance(raw,dict):raise ValueError("Нет ряда в архиве")
        for day,value in raw.items():add(day,value,True)
    if not rows:
        return pd.Series(dtype=float,index=pd.DatetimeIndex([],tz="UTC"),name=label)
    df=pd.DataFrame(rows,columns=["time","value"])
    # Duplicate timestamps cannot be silently resolved by taking the last row.
    dup=df["time"].duplicated(keep=False)
    df.loc[dup,"value"]=None
    s=df.drop_duplicates("time").set_index("time")["value"].astype(float).sort_index()
    if freq:
        s=s.reindex(pd.date_range(s.index.min(),s.index.max(),freq=freq))
    s.name=label
    return s

def period_slice(s, days, now=None):
    if days is None or s.empty:return s
    now=pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now).tz_convert("UTC")
    # Calendar days ending today, not the latest stale observation.
    return s.loc[s.index>=now.floor("D")-pd.Timedelta(days=days-1)]
