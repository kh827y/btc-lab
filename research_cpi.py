"""Prepare the frozen CPI event dataset locally. No model calls or backtest."""
import argparse
import csv
import io
import json
import math
import sys
import zipfile
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from binance_minute import MINUTE, ROOT, atomic_write, digest, json_write
from research_prices import DAY, MinutePrices

BASE = Path(__file__).resolve().parent / "data"
OUT = BASE / "research" / "cpi"
# Pin the original Astra archive's manifest, not a mutable copy from a website.
MANIFEST_HASH = "29a5bf0f907b1b5b05323fa3e13fe37c32fcd322405a67afbf9221ede7463b6d"
MEMBERS = {"README.md","bls_first_prints.csv","cpi_expectations.csv",
           "cpi_releases.csv","excluded_sources.csv","quality.json","validate.py"}
METRICS = ("headline_mom","core_mom","headline_yoy","core_yoy")
NY = ZoneInfo("America/New_York")
UTC = timezone.utc


def stamp(s):
    dt = datetime.fromisoformat(s.replace("Z","+00:00"))
    if dt.tzinfo is None:
        raise ValueError("Naive timestamp")
    return dt.astimezone(UTC)


def millis(dt):
    return int(dt.timestamp()*1000)


def require(ok, message):
    if not ok:
        raise ValueError(message)


def read_cpi(path):
    """Read only known members; never execute supplied validate.py."""
    raw = Path(path).read_bytes()
    require(len(raw) <= 2_000_000,"CPI ZIP too large")
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        infos = z.infolist()
        require(len(infos)==len(MEMBERS)+1 and {x.filename for x in infos}==MEMBERS|{"SHA256SUMS"}
                and all(x.file_size <= 2_000_000 for x in infos),"Unexpected CPI ZIP members")
        manifest = z.read("SHA256SUMS")
        require(digest(manifest)==MANIFEST_HASH,"Not the verified Astra CPI archive")
        hashes = dict((name,h) for h,name in
                      (line.split("  ",1) for line in manifest.decode().splitlines()))
        require(set(hashes)==MEMBERS,"Unexpected CPI manifest")
        files = {name:z.read(name) for name in MEMBERS}
        require(all(digest(files[n])==h for n,h in hashes.items()),"CPI checksum mismatch")
    def table(name):
        return list(csv.DictReader(io.StringIO(files[name].decode("utf-8-sig"))))
    events, forecasts, official = [table(name) for name in
                                   ("cpi_releases.csv","cpi_expectations.csv","bls_first_prints.csv")]
    by_event = {r["event_id"]:r for r in events}
    by_forecast = {r["forecast_id"]:r for r in forecasts}
    require(len(events)==len(by_event)==len(official)==106 and
            len({r["event_id"] for r in official})==106,"CPI event count")
    require(len(forecasts)==len(by_forecast)==324,"CPI forecast count")
    require(len({r["release_time_utc"] for r in events})==106,"Duplicate release time")
    alternatives = defaultdict(list)
    for f in forecasts:
        e = by_event[f["event_id"]]
        require(stamp(f["published_earliest_utc"])<=stamp(f["published_latest_utc"])<
                stamp(e["forecast_cutoff_utc"]),"Post-release forecast")
        alternatives[e["event_id"]].append(f)
    for r in official:
        require(all(by_event[r["event_id"]][k]==v for k,v in r.items()),"Official fact mismatch")
    for e in events:
        t = stamp(e["release_time_utc"])
        require(t.astimezone(NY).isoformat()==e["release_time_et"] and
                t.second==t.microsecond==0 and t.astimezone(NY).date().isoformat()==e["release_date_et"],
                "Invalid release time")
        require(e["forecast_cutoff_utc"]==(e["early_partial_time_utc"] or e["release_time_utc"]),
                "Invalid forecast cutoff")
        for m in METRICS:
            a,b,s,fid = [e[m+"_"+k] for k in ("first_pct","expected_pct","surprise_pp","forecast_id")]
            if b:
                f=by_forecast[fid]
                require(f["event_id"]==e["event_id"] and f[m+"_pct"]==b,"Forecast mismatch")
            else:
                require(not fid,"Unexpected forecast ID")
            if a and b:
                require(Decimal(a)-Decimal(b)==Decimal(s),"CPI surprise mismatch")
            else:
                require(not s,"Missing value turned into surprise")
        paired = bool(e["core_mom_surprise_pp"] and e["headline_mom_surprise_pp"])
        require(int(paired)==int(e["monthly_pair_available"]) and
                int(paired and not e["early_partial_time_utc"])==int(e["standard_intraday_timing_and_pair"]),
                "CPI inclusion flags mismatch")
    require(sum(int(e["monthly_pair_available"]) for e in events)==105 and
            sum(int(e["standard_intraday_timing_and_pair"]) for e in events)==104,"CPI coverage mismatch")
    return sorted(events,key=lambda e:e["release_time_utc"]), alternatives, digest(raw)


def split_name(t):
    return "train" if t.year<=2021 else "development" if t.year<=2023 else "test"


def split_end(split):
    if split=="train":
        return millis(datetime(2022,1,1,tzinfo=UTC))
    if split=="development":
        return millis(datetime(2024,1,1,tzinfo=UTC))
    return None


def bounded_outcome(prices, entry, days, split):
    end = split_end(split)
    # No label whose exit crosses the next partition boundary.
    if end is not None and entry+days*DAY >= end:
        return None,None
    return prices.outcome(entry,days)


def prepare_event(e, alternatives, prices):
    dt = stamp(e["release_time_utc"])
    t, split = millis(dt),split_name(dt)
    ret28,vol28 = prices.prior_state(t)
    response = prices.reaction(t,30)
    entry = t+31*MINUTE
    surprise = e["core_mom_surprise_pp"]
    standard = bool(int(e["standard_intraday_timing_and_pair"]))
    # Alternative forecasts kept as a set of possible surprise values for sensitivity.
    alt = sorted({Decimal(e["core_mom_first_pct"])-Decimal(f["core_mom_pct"])
                  for f in alternatives if e["core_mom_first_pct"] and f["core_mom_pct"]})
    features = {"event_id":e["event_id"],"release_time_utc":e["release_time_utc"],
                "entry_utc_ms":entry,"split":split,
                "core_mom_surprise_pp":float(surprise) if surprise else None,
                "headline_mom_surprise_pp":float(e["headline_mom_surprise_pp"]) if e["headline_mom_surprise_pp"] else None,
                "core_mom_forecast_id":e["core_mom_forecast_id"],
                "core_mom_forecast_within_24h":int(e["core_mom_forecast_within_24h"]),
                "alternative_core_surprises_pp":"|".join(str(x) for x in alt),
                "standard_intraday_timing":int(standard),"event_note":e["event_note"],
                "prior_return_28d":ret28,"prior_vol_28d":vol28,
                "reaction_30m":response,"entry_open":prices.point(entry,"open"),
                "reaction_24h":prices.reaction(t,1440),
                "delayed_entry_utc_ms":t+1441*MINUTE}
    r7,w7=bounded_outcome(prices,entry,7,split)
    r28,w28=bounded_outcome(prices,entry,28,split)
    late7,lateworst=bounded_outcome(prices,t+1441*MINUTE,7,split)
    outcomes={"event_id":e["event_id"],"return_7d":r7,"worst_7d":w7,
              "return_28d":r28,"worst_28d":w28,"delayed_return_7d":late7,
              "delayed_worst_7d":lateworst}
    # Candidate windows only. A calendar is still needed to exclude other news.
    controls=[]
    for weeks in range(1,5):
        control_dt=dt.astimezone(NY)-timedelta(weeks=weeks)
        ct=millis(control_dt)
        pr,pv=prices.prior_state(ct)
        controls.append({"event_id":e["event_id"],"control_utc":control_dt.astimezone(UTC).isoformat(),
                         "weeks_before":weeks,"reaction_30m":prices.reaction(ct,30),
                         "prior_return_28d":pr,"prior_vol_28d":pv,
                         "calendar_checked":0})
    eligible = standard and all(features[k] is not None for k in
                     ("prior_return_28d","prior_vol_28d","reaction_30m","entry_open")) and r7 is not None
    features["primary_standard_sample_eligible"]=int(eligible)
    return features,outcomes,controls


def write_csv(path, rows):
    require(bool(rows),"Empty output "+str(path))
    buf=io.StringIO(newline="")
    w=csv.DictWriter(buf,fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)
    atomic_write(path,buf.getvalue().encode("utf-8"))


def build(cpi_path, minute_root=ROOT, out=OUT):
    events, alternatives, cpi_hash=read_cpi(cpi_path)
    prices=MinutePrices.load(minute_root)
    groups=defaultdict(lambda:{"features":[],"outcomes":[],"controls":[]})
    coverage=defaultdict(Counter)
    for e in events:
        f,o,c=prepare_event(e,alternatives[e["event_id"]],prices)
        split=f["split"]
        g=groups[split]
        g["features"].append(f);g["outcomes"].append(o);g["controls"].extend(c)
        q=coverage[split]
        q["events"]+=1
        q["standard"]+=f["standard_intraday_timing"]
        q["primary_eligible"]+=f["primary_standard_sample_eligible"]
        for k in ("prior_return_28d","prior_vol_28d","reaction_30m","entry_open"):
            q["missing_"+k]+=f[k] is None
        for k,v in o.items():
            if k!="event_id":
                q["missing_"+k]+=v is None
        q["candidate_controls"]+=len(c)
        q["controls_with_prices"]+=sum(x["reaction_30m"] is not None for x in c)
    out=Path(out)
    # Mark incomplete until all split files have been replaced.
    json_write(out/"coverage.json",{"complete":False})
    files={}
    for split,g in groups.items():
        for name,rows in g.items():
            path=out/f"{split}_{name}.csv"
            write_csv(path,rows)
            files[path.name]=digest(path.read_bytes())
    report={"complete":True,"protocol":"cpi-v1-preparation","cpi_sha256":cpi_hash,
            "price_provenance":prices.provenance,"coverage":dict(coverage),
            "file_sha256":files,"control_calendar_checked":False,
            "independent_price_check":False,"test_results_opened_by_researcher":False,
            "note":"Coverage only; no performance, no fitted models. Test files are local and not access-controlled."}
    json_write(out/"coverage.json",report)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive",nargs="?",type=Path)
    args=p.parse_args()
    path=args.archive
    if path is None:
        candidates=list(BASE.glob("BTC-Lab_US_CPI_2018-01_2026-11*.zip"))
        candidates+=list((Path.home()/"Downloads").glob("BTC-Lab_US_CPI_2018-01_2026-11*.zip"))
        for candidate in candidates:
            try:
                read_cpi(candidate)
            except (OSError,ValueError,KeyError,zipfile.BadZipFile):
                continue
            path=candidate
            break
    if path is None:
        p.error("Place the original CPI ZIP in data/ or Downloads, or drag it onto prepare_cpi.bat")
    print("Preparing local CPI dataset; no API calls.",flush=True)
    r=build(path)
    print(json.dumps(r["coverage"],indent=2),flush=True)
    print("Send coverage.json only, not the test CSVs:",OUT/"coverage.json",flush=True)
    return 0


if __name__=="__main__":
    sys.exit(main())
