"""Read existing L2 archives; never join clocks, markets or partial bands."""
from datetime import date
import pandas as pd
from data_logic import is_real_number

BYBIT="btc-liquidity/data/bybit_independent_history.json"
HFT="btc-liquidity/data/hft_history.json"
MARKETS={
    "bybit_independent_spot":("Bybit · спот · 00 UTC","BTCUSDT","spot"),
    "bybit_independent_linear":("Bybit · perpetual · 00 UTC","BTCUSDT","perpetual"),
    "binance_spot":("Binance · спот · около 12 UTC","BTCUSDT","spot"),
    "bybit_spot":("Bybit · спот · около 12 UTC","BTCUSDT","spot"),
    "bitget_spot":("Bitget · спот · около 12 UTC","BTCUSDT","spot"),
    "okx_spot":("OKX · спот · около 12 UTC","BTC-USDT","spot"),
    "binance_futures":("Binance · perpetual · около 12 UTC","BTCUSDT","perpetual"),
    "bybit":("Bybit · perpetual · около 12 UTC","BTCUSDT","perpetual"),
    "okx_futures":("OKX · perpetual · около 12 UTC","BTC-USDT-SWAP","perpetual"),
}
BANDS=("0.01","0.05","0.2","1.0")

def archive_path(market):
    return BYBIT if market.startswith("bybit_independent_") else HFT

def depth_frame(doc,market,band,now=None):
    if market not in MARKETS or band not in BANDS:raise ValueError("Неизвестный рынок или полоса")
    independent=archive_path(market)==BYBIT
    if not isinstance(doc,dict) or doc.get("schema_version")!=(1 if independent else 2):raise ValueError("Неверная версия архива L2")
    section=doc.get("records" if independent else "markets",{})
    raw=section.get(market) if isinstance(section,dict) else None
    if not isinstance(raw,dict):raise ValueError("Рынок отсутствует")
    _,symbol,kind=MARKETS[market]
    now=pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now).tz_convert("UTC")
    result={}
    for day,entry in raw.items():
        try:
            if not isinstance(day,str) or date.fromisoformat(day).isoformat()!=day:continue
            anchor=pd.Timestamp(day,tz="UTC")
        except (TypeError,ValueError):continue
        if anchor>=now.floor("D"):continue
        row={"bid":None,"ask":None,"share":None,"snapshot":None,"status":"нет подтверждённого снимка"}
        result[anchor]=row
        if not isinstance(entry,dict):continue
        if independent:
            data=entry
            if data.get("source_type")!="independent Bybit daily native snapshot":continue
            expected_depth=500 if kind=="perpetual" and day<="2025-08-20" else 200
            if data.get("ob_levels_declared")!=expected_depth:continue
        else:
            if entry.get("status")!="ok" or not isinstance(entry.get("data"),dict):continue
            data=entry["data"]
            if data.get("source")!="CryptoHFTData historical verified L2 snapshot" or data.get("method")!="first genuine complete vendor snapshot in UTC file (may follow unanchored updates); not a daily median":continue
            if data.get("quote")!="USDT" or not str(data.get("file_path","")).startswith(f"{market}/{day}/"):continue
        if (data.get("venue"),data.get("symbol"),data.get("market"))!=(market,symbol,kind):continue
        try:
            ts=pd.Timestamp(data["time"])
            if ts.tzinfo is None:continue
            ts=ts.tz_convert("UTC")
            if ts.floor("D")!=anchor or ts>now:continue
            row["snapshot"]=ts.isoformat()
            offset=(ts-anchor).total_seconds()
            if independent:
                comparable=0<=offset<=180
            else:
                comparable=abs(offset-43200)<=1800 and data.get("sample_utc_hour")==ts.hour
            if not comparable:
                row["status"]="другое время снимка"
                continue
        except (KeyError,TypeError,ValueError,OverflowError):continue
        bands=data.get("bands")
        b=bands.get(band) if isinstance(bands,dict) else None
        if not isinstance(b,dict) or b.get("bid_coverage_complete") is not True or b.get("ask_coverage_complete") is not True:
            row["status"]="неполная глубина"
            continue
        bid,ask=b.get("bid_usd"),b.get("ask_usd")
        if not all(is_real_number(v) and v>=0 for v in (bid,ask)) or bid+ask<=0:
            row["status"]="некорректные значения"
            continue
        share=b.get("bid_share")
        if not is_real_number(share) or not 0<=share<=1 or abs(share-bid/(bid+ask))>.0001:
            row["status"]="не совпадает доля"
            continue
        row.update(bid=float(bid),ask=float(ask),share=100*bid/(bid+ask),status="есть наблюдение")
    columns=["bid","ask","share","snapshot","status"]
    if not result:return pd.DataFrame(columns=columns,index=pd.DatetimeIndex([],tz="UTC"))
    df=pd.DataFrame.from_dict(result,orient="index").sort_index()
    df=df.reindex(pd.date_range(df.index.min(),df.index.max(),freq="D"))
    df["status"]=df["status"].fillna("нет даты в архиве")
    return df
