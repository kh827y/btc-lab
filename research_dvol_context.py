"""Fresh closed-day DVOL context. Separate from frozen forecast journals."""
import json
import math
from datetime import datetime, timezone
from pathlib import Path

from binance_minute import digest
from forecast_journal import new_file
from research_buy import DAY
from research_daily_usd import fetch,LIMIT
from research_dvol import ms,url,parse_page

ROOT=Path(__file__).resolve().parent/"data"/"research"/"dvol_context"


def utcnow():
    return datetime.now(timezone.utc)


def validate(raw,day):
    rows,cursor=parse_page(raw,day,day+DAY,ms(day+DAY)-1)
    if cursor is not None or set(rows)!={day}:
        raise ValueError("Missing or incomplete requested DVOL day")
    value=rows[day][3]
    if not 5<=value<=300:
        raise ValueError("DVOL scale outside conservative sanity range")
    return value


def context_record(raw,day,now):
    if now.tzinfo is None or now.astimezone(timezone.utc).date()!=day+DAY:
        raise ValueError("Only the latest closed UTC day may be captured")
    value=validate(raw,day)
    return {"version":"dvol-context-v1","source":"Deribit BTC DVOL",
            "date_utc":day.isoformat(),"retrieved_utc":now.astimezone(timezone.utc).isoformat(),
            "url":url(day,ms(day+DAY)-1),"raw":raw.decode("utf-8"),"sha256":digest(raw),
            "annualized_percent":value,
            "implied_30d_log_vol_percent":value*math.sqrt(30/365)}


def snapshot(day,root=ROOT,clock=utcnow,fetcher=fetch):
    now=clock()
    if now.tzinfo is None or now.astimezone(timezone.utc).date()!=day+DAY:
        raise ValueError("Requested DVOL day is not the latest closed UTC day")
    target=Path(root)/day.isoformat()/"dvol.json"
    if target.exists():
        obj=json.loads(target.read_bytes())
        raw=obj["raw"].encode("utf-8")
        then=datetime.fromisoformat(obj["retrieved_utc"])
        if then.tzinfo is None or then>now or obj!=context_record(raw,day,then):
            raise ValueError("Saved DVOL context identity mismatch")
        return obj
    raw=fetcher(url(day,ms(day+DAY)-1),LIMIT)
    if len(raw)>LIMIT:
        raise ValueError("DVOL response too large")
    obj=context_record(raw,day,clock())
    target.parent.mkdir(parents=True,exist_ok=True)
    new_file(target,obj)
    return obj


def describe(obj):
    return (f"DVOL Deribit, закрытие {obj['date_utc']} UTC: "
            f"{obj['annualized_percent']:.1f}% годовых; "
            f"масштаб 30-дневной логарифмической волатильности "
            f"{obj['implied_30d_log_vol_percent']:.1f}%. "
            "Не направление, не границы цены и не вероятность падения. "
            f"Получено {obj['retrieved_utc']}; SHA256 ответа {obj['sha256']}.")


if __name__=="__main__":
    day=utcnow().date()-DAY
    obj=snapshot(day)
    print(describe(obj),flush=True)
    print("Send:",ROOT/day.isoformat()/"dvol.json",flush=True)
