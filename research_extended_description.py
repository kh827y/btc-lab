"""Descriptive extension of DD-001 and TREND-001 on verified same-venue history."""
import csv
import io
import math
from datetime import date
from pathlib import Path

from binance_minute import digest
from forecast_journal import new_file
from research_buy import DAY, DEV_END, FIRST, HASHES, days, load_development
from research_drawdown import build_rows, summarize, NAMES, START as OLD_DD_START
from research_trend_recovery import analyze as trend_analyze, PEAK_START
from research_early_usd import ROOT as EARLY_ROOT, START as EARLY_START, STOP as EARLY_STOP, DAILY_ROOT

ROOT=Path(__file__).resolve().parent/"data"/"research"/"extended_description_v1"
EARLY_SHA="b6a855543fd1cd69a7c4707fdc6fc271fe0b8e0f2cce76605a2f33af4b05950a"
FIRST_DATE=date(2012,1,1)
WEEK_START=date(2012,1,2)


def read_early(path):
    raw=Path(path).read_bytes()
    if digest(raw)!=EARLY_SHA:
        raise ValueError("Early Bitstamp snapshot hash mismatch")
    reader=csv.DictReader(io.StringIO(raw.decode("utf-8")))
    if reader.fieldnames!=["date_utc","open","high","low","close","volume_btc"]:
        raise ValueError("Unexpected early daily schema")
    result={};cursor=EARLY_START
    for r in reader:
        d=date.fromisoformat(r["date_utc"])
        if d!=cursor or d>=EARLY_STOP:
            raise ValueError("Unordered, duplicate or missing early date")
        cursor+=DAY
        v=tuple(float(r[k]) for k in reader.fieldnames[1:])
        op,hi,lo,cl,vol=v
        if not all(math.isfinite(x) for x in v) or not 0<lo<=min(op,cl)<=max(op,cl)<=hi or vol<0:
            raise ValueError("Invalid early OHLCV")
        result[d]=v
    if cursor!=EARLY_STOP:
        raise ValueError("Incomplete early snapshot")
    return result


def merge_same_venue(early,pinned,overlap_start=FIRST["bitstamp"],overlap_stop=EARLY_STOP):
    overlap=set(days(overlap_start,overlap_stop))
    if not overlap or set(early)&set(pinned)!=overlap:
        raise ValueError("Unexpected same-venue overlap")
    if any(early[d]!=pinned[d] for d in overlap):
        raise ValueError("Overlap values differ")
    return {**early,**pinned}


def compact_summary(rows):
    result=summarize(rows)
    # The extension needs distributions and counts, not thousands of curve points.
    result["recovery"].pop("curve",None)
    return result


def dd_extension(prices,first=FIRST_DATE,start=WEEK_START):
    rows,episodes,skips=build_rows(prices,first,start=start)
    valid=[r for r in rows if not r["gap_uncertainty"]]
    def bins(a):
        return {k:compact_summary([r for r in a if r["bin"]==k]) for k in NAMES}
    return {"weekly_origins":len(rows),"gap_uncertain_origins":len(rows)-len(valid),
            "by_depth_all":bins(rows),"by_depth_known_peak":bins(valid),
            "by_depth_early_origins":bins([r for r in rows if date.fromisoformat(r["date"])<OLD_DD_START]),
            "by_depth_later_origins":bins([r for r in rows if date.fromisoformat(r["date"])>=OLD_DD_START]),
            "episode_inventory_10pct_or_more":[e for e in episodes if e["max_depth"]>=.1-1e-12],
            "skipped":skips}


def run(root=ROOT,early_root=EARLY_ROOT,daily_root=DAILY_ROOT):
    root=Path(root)
    target=root/"extended_description_report.json"
    if target.exists():
        raise ValueError("Report already exists; preserve original")
    early=read_early(Path(early_root)/"bitstamp_early_daily.csv")
    pinned=load_development(Path(daily_root),"bitstamp")
    prices=merge_same_venue(early,pinned)
    if any(d>=DEV_END for d in prices):
        raise ValueError("Post-development data forbidden")
    # 2011 had 30 zero-volume days. Keep the archive, start peak history in 2012.
    prices={d:v for d,v in prices.items() if d>=FIRST_DATE}
    trend=trend_analyze(prices,first=FIRST_DATE)
    dd=dd_extension(prices)
    report={"version":"extended-description-v1","kind":"historical_descriptive_extension",
            "early_sha256":EARLY_SHA,"pinned_bitstamp_sha256":HASHES["bitstamp"],
            "peak_start":FIRST_DATE.isoformat(),"weekly_start":WEEK_START.isoformat(),
            "end_exclusive":DEV_END.isoformat(),"trend":trend,"drawdown":dd,
            "limitations":["Single venue; early history not independently verified.",
              "2011 excluded from evaluation; 2015 zero-volume gaps retained and uncertain peak origins shown separately.",
              "Same fixed TREND-001 and DD-001 definitions; different peak history/start can change later episode classification.",
              "Early and later origins overlap future outcome windows; not independent samples or a confirmation test.",
              "No changes to prior reports, journals or decision sheet; no optimization or post-2023 outcomes."]}
    root.mkdir(parents=True,exist_ok=True)
    new_file(target,report)
    print("Trend:",trend["summary"],flush=True)
    print("Drawdown weekly origins:",dd["weekly_origins"],flush=True)
    print("Send:",target,flush=True)
    return report


if __name__=="__main__":
    run()
