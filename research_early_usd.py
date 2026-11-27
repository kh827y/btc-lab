"""Separate early Bitstamp snapshot and cross-venue OHLC audit; no outcome scoring."""
import json
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

from binance_minute import digest, json_write
from research_daily_usd import (DAY, LIMIT, seconds, date_at, windows, parse_page,
    coverage, csv_bytes, save_snapshot, download, fetch, ROOT as DAILY_ROOT)
from research_buy import load_development

ROOT=Path(__file__).resolve().parent/"data"/"research"/"early_usd_v1"
START=date(2011,8,18)
STOP=date(2015,1,1)  # 2014 overlap with pinned Bitstamp snapshot.
BASE="https://www.bitstamp.net/api/v2/ohlc/btcusd/"


def early_url(a,b):
    n=(b-a).days
    if not START<=a<b<=STOP or not 0<n<=365:
        raise ValueError("Invalid early window")
    return BASE+"?"+urlencode({"step":DAY,"limit":n,"start":seconds(a),
        "end":seconds(b)-1,"exclude_current_candle":"true"})


def early_page(root,a,b,fetcher):
    url=early_url(a,b)
    p=root/"cache"/(a.isoformat()+".json")
    if p.exists():
        doc=json.loads(p.read_bytes())
        raw=doc["raw"].encode("utf-8")
        if doc["url"]!=url or doc["sha256"]!=digest(raw):
            raise ValueError("Early cache identity mismatch")
    else:
        raw=download(url,fetcher)
        if len(raw)>LIMIT:
            raise ValueError("Early page too large")
        # Validate before saving, preserving raw exchange response.
        parse_page(raw,"bitstamp",a,b)
        doc={"url":url,"sha256":digest(raw),"raw":raw.decode("utf-8"),
             "retrieved_utc":datetime.now(timezone.utc).isoformat()}
        json_write(p,doc)
    rows,outside=parse_page(raw,"bitstamp",a,b)
    return rows,{"start":a.isoformat(),"end_exclusive":b.isoformat(),
        "url":url,"sha256":doc["sha256"],"retrieved_utc":doc["retrieved_utc"],
        "rows":len(rows),"outside_range_rows":outside}


def early_overlap(early,pinned):
    common=sorted(t for t in early if date_at(t) in pinned)
    differences=[]
    for t in common:
        a,b=early[t],pinned[date_at(t)]
        if a!=b:
            differences.append({"date":date_at(t).isoformat(),"early":a,"pinned":b,
                "relative_close_diff":a[3]/b[3]-1})
    return {"common_days":len(common),"exact_matches":len(common)-len(differences),
        "different_rows":differences}


def extreme_audit(bitstamp,coinbase):
    # Screening thresholds only; not a rule to repair or discard candles.
    rows=[]
    for d in sorted(set(bitstamp)&set(coinbase)):
        a,b=bitstamp[d],coinbase[d]
        ratios={"coinbase_to_bitstamp_low":b[2]/a[2],
                "coinbase_to_bitstamp_high":b[1]/a[1],
                "coinbase_to_bitstamp_close":b[3]/a[3]}
        flags=[k for k,v in ratios.items() if not .8<=v<=1.25]
        for name,x in (("bitstamp",a),("coinbase",b)):
            if x[2]<.5*min(x[0],x[3]):
                flags.append(name+"_low_vs_body")
            if x[1]>2*max(x[0],x[3]):
                flags.append(name+"_high_vs_body")
        if flags:
            rows.append({"date":d.isoformat(),"bitstamp_ohlcv":a,
                "coinbase_ohlcv":b,"ratios":ratios,"flags":flags})
    return {"common_days":len(set(bitstamp)&set(coinbase)),
        "flagged_days":len(rows),"rows":rows}


def run(root=ROOT,daily_root=DAILY_ROOT,fetcher=fetch):
    root=Path(root)
    root.mkdir(parents=True,exist_ok=True)
    pinned={m:load_development(Path(daily_root),m) for m in ("bitstamp","coinbase")}
    early={};pages=[];errors=[]
    for a,b in windows(START,STOP,365):
        print("Early Bitstamp",a,b,flush=True)
        try:
            rows,page=early_page(root,a,b,fetcher)
            if set(early)&set(rows):
                raise ValueError("Overlapping early candles")
            early.update(rows);pages.append(page)
        except (OSError,ValueError,TypeError,KeyError,OverflowError) as exc:
            errors.append({"start":a.isoformat(),"end_exclusive":b.isoformat(),"error":str(exc)})
    quality=coverage(early,START,STOP)
    snapshot_hash=None
    if early and not errors:
        snapshot_hash=save_snapshot(root/"bitstamp_early_daily.csv",csv_bytes(early))
    report={"version":"early-usd-audit-v1","requested_start":START.isoformat(),
        "end_exclusive":STOP.isoformat(),"requests_complete":not errors,
        "pages":pages,"errors":errors,"coverage":quality,"csv_sha256":snapshot_hash,
        "overlap":early_overlap(early,pinned["bitstamp"]),
        "extremes":extreme_audit(pinned["bitstamp"],pinned["coinbase"]),
        "limitations":["Earlier Bitstamp is the same venue, not independent verification.",
          "All candles retained. Flags are diagnostic, not deletion or correction.",
          "Daily OHLC cannot distinguish real isolated trades from source errors.",
          "No splicing, no outcome scoring, no post-2023 numeric prices, no model fitting."]}
    json_write(root/"early_history_report.json",report)
    print("Send:",root/"early_history_report.json",flush=True)
    print("Observed:",quality["observed"],"of",quality["expected"],
          "flagged common days:",report["extremes"]["flagged_days"],flush=True)
    return report


if __name__=="__main__":
    run()
