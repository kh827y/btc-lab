"""OI source-readiness audit: latest 14 completed Fridays, no forecasts or outcomes."""
import csv
import io
import json
import math
import time
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urlencode

from binance_minute import fetch as archive_fetch,digest,expected_hash
from research_daily_usd import fetch as price_fetch,parse_page,seconds,date_at,LIMIT as PRICE_LIMIT
from research_oi import BASE,name,LIMIT,unit_check,oi_feature
from forecast_journal import new_file

ROOT=Path(__file__).resolve().parent/"data"/"research"/"oi_readiness_v1"
VERSION="OI-source-readiness-v1"
DAY=timedelta(days=1)
WEEK=7*DAY


def utcnow():
    return datetime.now(timezone.utc)


def fridays(now):
    if now.tzinfo is None:
        raise ValueError("Timezone-aware clock required")
    yesterday=now.astimezone(timezone.utc).date()-DAY
    latest=yesterday-timedelta(days=(yesterday.weekday()-4)%7)
    return [latest-i*WEEK for i in range(13,-1,-1)]


def parse_recent(raw,d):
    """Same timed Friday snapshot convention as OI-001, no date-only fallback.
    Kept separate so archived research code and cutoff are not changed.
    """
    if d.weekday()!=4 or len(raw)>LIMIT:
        raise ValueError("Invalid Friday archive")
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        es=z.infolist()
        if len(es)!=1 or es[0].filename!=name(d)[:-4]+".csv" or es[0].file_size>LIMIT:
            raise ValueError("Unexpected metrics ZIP")
        with z.open(es[0]) as f:
            rd=csv.DictReader(io.TextIOWrapper(f,encoding="utf-8-sig",newline=""))
            fields=rd.fieldnames or []
            if not {"create_time","symbol","sum_open_interest","sum_open_interest_value"}<=set(fields) or len(set(fields))!=len(fields):
                raise ValueError("Unexpected metrics columns")
            rows=list(rd)
    if not 0<len(rows)<=10000:
        raise ValueError("Unexpected metrics row count")
    seen={};eligible={};conflicts=set();duplicates=0;invalid=0
    for r in rows:
        if r["symbol"]!="BTCUSDT":
            raise ValueError("Wrong contract")
        if not isinstance(r["create_time"],str) or len(r["create_time"])<=10:
            raise ValueError("Explicit observation time required")
        stamp=datetime.fromisoformat(r["create_time"].replace("Z","+00:00"))
        if stamp.tzinfo is None:
            stamp=stamp.replace(tzinfo=timezone.utc)
        stamp=stamp.astimezone(timezone.utc)
        if stamp.date()!=d:
            raise ValueError("Timestamp outside archive date")
        try:
            q=float(r["sum_open_interest"]);v=float(r["sum_open_interest_value"])
        except (ValueError,TypeError):
            q=v=0.
        pair=(q,v) if all(math.isfinite(x) and x>0 for x in (q,v)) else None
        if pair is None:
            invalid+=1
        if stamp in seen:
            duplicates+=1
            if seen[stamp]!=pair:
                conflicts.add(stamp)
        else:
            seen[stamp]=pair
        if pair is not None and stamp.hour==23 and stamp.minute>=45:
            eligible[stamp]=pair
    if not eligible:
        raise ValueError("No positive OI observation in final 15 minutes")
    stamp=max(eligible)
    if stamp in conflicts:
        raise ValueError("Conflicting OI at selected timestamp")
    q,v=eligible[stamp]
    return {"date":d.isoformat(),"timestamp":stamp.isoformat(),"quantity":q,"notional":v,
            "rows":len(rows),"invalid_rows":invalid,"duplicate_rows":duplicates,
            "conflicting_timestamps":len(conflicts)}


def write_bytes(path,raw):
    with path.open("xb") as f:
        f.write(raw)


def error_record(exc):
    # No raw HTTP body, response-controlled text, local paths or secrets.
    out={"error_type":type(exc).__name__}
    if isinstance(exc,HTTPError):
        out["http_status"]=exc.code
    return out


def run(root=ROOT,fetcher=archive_fetch,prices_fetcher=price_fetch,clock=utcnow,pause=time.sleep):
    start=clock().astimezone(timezone.utc)
    dates=fridays(start)
    last=dates[-1];stop=last+DAY
    run_id=start.strftime("%Y%m%dT%H%M%S%fZ")
    folder=Path(root)/run_id
    folder.mkdir(parents=True,exist_ok=False)
    # Only the past window used for a contemporaneous unit check, never outcome candles.
    url="https://www.bitstamp.net/api/v2/ohlc/btcusd/?"+urlencode({
        "step":86400,"limit":(stop-dates[0]).days,"start":seconds(dates[0]),
        "end":seconds(stop)-1,"exclude_current_candle":"true"})
    price_info={"url":url,"status":"unavailable"}
    prices={}
    try:
        raw=prices_fetcher(url,PRICE_LIMIT)
        if len(raw)>PRICE_LIMIT:
            raise ValueError("Price response too large")
        write_bytes(folder/"bitstamp.json",raw)
        rows,outside=parse_page(raw,"bitstamp",dates[0],stop)
        prices={date_at(t):v for t,v in rows.items()}
        price_info={"url":url,"status":"received","sha256":digest(raw),
                    "retrieved_utc":clock().astimezone(timezone.utc).isoformat(),
                    "fridays_present":sum(d in prices and prices[d][4]>0 for d in dates),
                    "outside_rows":outside}
    except (OSError,ValueError,TypeError,KeyError,OverflowError) as exc:
        price_info.update(error_record(exc))
    entries=[];oi={}
    for d in dates:
        fn=name(d);source=BASE+fn
        e={"date":d.isoformat(),"url":source,"status":"unavailable"}
        stage="checksum"
        try:
            checksum=fetcher(source+".CHECKSUM",4096)
            want=expected_hash(checksum,fn)
            stage="archive"
            raw=fetcher(source,LIMIT)
            if len(raw)>LIMIT or digest(raw)!=want:
                raise ValueError("Archive checksum or size mismatch")
            write_bytes(folder/fn,raw)
            write_bytes(folder/(fn+".CHECKSUM"),checksum)
            e.update({"sha256":want,"retrieved_utc":clock().astimezone(timezone.utc).isoformat()})
            stage="parse"
            row=parse_recent(raw,d)
            e["observation"]=row
            stage="unit_check"
            if d not in prices or prices[d][4]<=0:
                e["status"]="parsed_price_unavailable"
            elif not unit_check(row,prices[d]):
                e["status"]="unit_check_failed"
            else:
                e["status"]="valid"
                oi[d]=row["quantity"]
        except (OSError,ValueError,TypeError,KeyError,OverflowError,zipfile.BadZipFile,csv.Error) as exc:
            e.update(error_record(exc))
            e["failed_stage"]=stage
        entries.append(e)
        print(d,e["status"],flush=True)
        pause(.1)
    finish=clock().astimezone(timezone.utc)
    origin=last+3*DAY
    feature=oi_feature(oi,origin)
    ready=len(oi)==14 and feature is not None
    report={"version":VERSION,"kind":"data_availability_only","started_utc":start.isoformat(),
            "finished_utc":finish.isoformat(),"reference_friday":last.isoformat(),
            "related_monday":origin.isoformat(),"complete_14_fridays":ready,
            "valid_count":len(oi),"expected_count":14,
            "oi_relative_log":feature if ready else None,
            "price_unit_check":price_info,"entries":entries,
            "completed_before_related_monday":finish.date()<origin,
            "confirmation_authorized":False,"forecast_issued":False,
            "limitations":["Latest completed Friday at actual UTC run time; not a historical backfill.",
                "Archive creation timestamps are observation times, not publication times.",
                "Retrieval timestamps are local-clock evidence, not independently anchored receipts.",
                "Original source bytes retained locally. A missing latest archive is not replaced.",
                "Binance BTCUSDT OI quantity is not leverage or direction. Bitstamp price-range check is approximate.",
                "No outcomes, scores, model fitting or API model calls. Does not alter BUY/RISK journals."]}
    target=folder/"oi_readiness_report.json"
    new_file(target,report)
    print("Send:",target,flush=True)
    return report


if __name__=="__main__":
    run()
