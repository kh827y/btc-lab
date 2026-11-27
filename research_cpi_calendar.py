"""CPI part A: conservative date screening of development control windows.

ALFRED release dates may include revisions or first FRED availability.
This is a scoped screen, NOT a comprehensive intraday news calendar.
No final-period prices/outcomes are read.
"""
import json
import re
from collections import Counter, defaultdict
from datetime import date
from pathlib import Path

import numpy as np

from binance_minute import digest, json_write, fetch
from research_cpi import OUT, NY, stamp, verify_development
from research_cpi_development import read_table, number

# Release IDs and exact names checked against ALFRED download pages.
RELEASES = {
    10: ("CPI", "Consumer Price Index", 11),
    46: ("PPI", "Producer Price Index", 11),
    50: ("NFP", "Employment Situation", 11),
    180: ("claims", "Unemployment Insurance Weekly Claims Report", 50),
    9: ("retail", "Advance Monthly Sales for Retail and Food Services", 10),
    53: ("GDP", "Gross Domestic Product", 10),
    54: ("PCE", "Personal Income and Outlays", 10),
}
START=date(2017,12,1)
STOP=date(2024,1,1)
LIMIT=512*1024


def url(rid):
    if rid not in RELEASES:
        raise ValueError("Unknown release ID")
    return f"https://alfred.stlouisfed.org/release/downloaddates?ff=txt&rid={rid}"


def parse(raw,rid):
    label,name,minimum=RELEASES[rid]
    s=raw.decode("utf-8-sig")
    if "Release: "+name not in s or "Release Dates:" not in s:
        raise ValueError("Unexpected ALFRED response: "+label)
    body=s.split("Release Dates:",1)[1]
    dates=[]
    for line in body.splitlines():
        line=line.strip()
        if not line or set(line)=={"-"}:
            continue
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}",line):
            raise ValueError("Unexpected release date line: "+label)
        dates.append(date.fromisoformat(line))
    if not dates:
        raise ValueError("Empty dates: "+label)
    # Calendar membership is per unique day, not per publication or revision.
    # ALFRED can repeat dates. Preserve raw bytes and report duplicate counts.
    duplicates=len(dates)-len(set(dates))
    selected={d for d in dates if START<=d<STOP}
    counts=Counter(d.year for d in selected)
    # Sanity floor, NOT proof of complete announcement coverage.
    if any(counts[y]<minimum for y in range(2018,2024)) or counts[2017]<1:
        raise ValueError("Incomplete date coverage: "+label)
    return selected,dict(sorted(counts.items())),duplicates


def calendar(root,fetcher=fetch):
    root=Path(root)
    dates=defaultdict(set)
    sources={}
    for rid,(label,name,_) in RELEASES.items():
        u=url(rid)
        p=root/f"{rid}.json"
        if p.exists():
            obj=json.loads(p.read_bytes())
            raw=obj["raw"].encode("utf-8")
            if obj["url"]!=u or digest(raw)!=obj["sha256"]:
                raise ValueError("ALFRED cache integrity failure")
            selected,counts,duplicates=parse(raw,rid)
        else:
            raw=fetcher(u,LIMIT)
            if len(raw)>LIMIT:
                raise ValueError("ALFRED response exceeds limit")
            selected,counts,duplicates=parse(raw,rid)
            obj={"url":u,"sha256":digest(raw),"raw":raw.decode("utf-8")}
            json_write(p,obj)
        sources[label]={"url":u,"sha256":obj["sha256"],"year_counts":counts,"duplicate_date_rows":duplicates}
        for d in selected:
            dates[d].add(label)
    return dates,sources


def local_day(value):
    return stamp(value).astimezone(NY).date()


def screen(features,controls,dates):
    # Use all standard paired CPI releases with an observed 30m return, not
    # the weekly-outcome eligibility flag. Missing prior state is disclosed.
    events={f["event_id"]:f for f in features}
    if len(events)!=len(features):
        raise ValueError("Duplicate CPI event")
    known={local_day(f["release_time_utc"]) for f in features}
    missing_cpi=sorted(d.isoformat() for d in known if "CPI" not in dates.get(d,set()))
    # The original CPI archive is authoritative for its own release dates.
    dates={d:set(v) for d,v in dates.items()}
    for d in known:
        dates.setdefault(d,set()).add("CPI")
    grouped=defaultdict(list)
    seen=set()
    for c in controls:
        eid=c["event_id"]
        if eid not in events:
            raise ValueError("Unmatched control")
        key=(eid,c["control_utc"])
        if key in seen:
            raise ValueError("Duplicate control")
        seen.add(key)
        t=stamp(c["control_utc"]).astimezone(NY)
        release=stamp(events[eid]["release_time_utc"]).astimezone(NY)
        days=(release.date()-t.date()).days
        if days not in (7,14,21,28) or t.time()!=release.time() or t.date()<START:
            raise ValueError("Invalid control date/time")
        grouped[eid].append(c)
    if any(len(grouped[eid])!=4 for eid in events):
        raise ValueError("Expected four candidates per release")
    exclusions=Counter()
    control_total=0
    surviving=0
    results=[]
    audit=[]
    for eid,f in events.items():
        release_day=local_day(f["release_time_utc"])
        other=sorted(dates.get(release_day,set())-{"CPI"})
        matched=[]
        for c in grouped[eid]:
            day=local_day(c["control_utc"])
            flags=sorted(dates.get(day,set()))
            control_total+=1
            if flags:
                exclusions.update(flags)
            elif not c["reaction_30m"]:
                exclusions["missing_price"]+=1
            else:
                matched.append(c)
                surviving+=1
            audit.append({"event_id":eid,"control_utc":c["control_utc"],
                          "same_day_release_flags":flags,"price_available":bool(c["reaction_30m"])})
        if f["standard_intraday_timing"]!="1" or not f["reaction_30m"] or not matched:
            continue
        a=number(f["reaction_30m"])
        b=[number(c["reaction_30m"]) for c in matched]
        results.append({"event_id":eid,"year":release_day.year,"event_day_other_flags":other,
                        "event_reaction_pp":100*a,"mean_control_reaction_pp":100*float(np.mean(b)),
                        "event_abs_reaction_pp":100*abs(a),"mean_control_abs_reaction_pp":100*float(np.mean(np.abs(b))),
                        "control_count":len(matched),"control_utc":[c["control_utc"] for c in matched],
                        "prior_return_28d":number(f["prior_return_28d"]) if f["prior_return_28d"] else None,
                        "prior_vol_28d":number(f["prior_vol_28d"]) if f["prior_vol_28d"] else None,
                        "control_prior_return_28d":[number(c["prior_return_28d"]) if c["prior_return_28d"] else None for c in matched],
                        "control_prior_vol_28d":[number(c["prior_vol_28d"]) if c["prior_vol_28d"] else None for c in matched]})
    return results,{"candidate_count":control_total,"surviving_count":surviving,
                    "exclusion_flags_not_mutually_exclusive":dict(exclusions),
                    "known_cpi_dates_absent_in_alfred":missing_cpi,
                    "control_audit":audit}


def summarize(rows):
    if not rows:
        return {"events":0}
    signed=np.asarray([r["event_reaction_pp"]-r["mean_control_reaction_pp"] for r in rows])
    absdiff=np.asarray([r["event_abs_reaction_pp"]-r["mean_control_abs_reaction_pp"] for r in rows])
    usage=Counter(t for r in rows for t in r["control_utc"])
    balance={}
    for k in ("prior_return_28d","prior_vol_28d"):
        pairs=[(r[k],np.mean(r["control_"+k])) for r in rows
               if r[k] is not None and all(v is not None for v in r["control_"+k])]
        balance[k]={"n":len(pairs),"mean_difference_pp":float(100*np.mean([a-b for a,b in pairs])) if pairs else None}
    return {"events":len(rows),"unique_control_windows":len(usage),
            "reused_control_windows":sum(n>1 for n in usage.values()),
            "mean_event_abs_reaction_pp":float(np.mean([r["event_abs_reaction_pp"] for r in rows])),
            "mean_control_abs_reaction_pp":float(np.mean([r["mean_control_abs_reaction_pp"] for r in rows])),
            "mean_abs_reaction_difference_pp":float(absdiff.mean()),
            "mean_signed_reaction_difference_pp":float(signed.mean()),
            "fraction_event_larger_abs":float((absdiff>0).mean()),"prior_state_balance":balance}


def run(root=OUT,fetcher=fetch):
    root=Path(root)
    m=verify_development(root,json.loads((root/"coverage.json").read_bytes()))
    manifest=m["file_sha256"]
    # Read only train/development event and control files.
    features=[];controls=[]
    for split in ("train","development"):
        features.extend(read_table(root,split+"_features.csv",manifest))
        controls.extend(read_table(root,split+"_controls.csv",manifest))
    if any(not 2018<=local_day(f["release_time_utc"]).year<=2023 for f in features):
        raise ValueError("Unexpected split")
    dates,sources=calendar(root/"alfred_calendar_cache",fetcher)
    rows,audit=screen(features,controls,dates)
    report={"protocol":"CPI-001-part-A-date-screen-v1","test_read":False,
            "calendar_scope":"Seven ALFRED release families; whole local date, not intraday.",
            "sources":sources,"input_hashes":manifest,"price_snapshot_sha256":m["price_provenance"]["snapshot_sha256"],
            "coverage":{k:v for k,v in audit.items() if k!="control_audit"},
            "all_matched":summarize(rows),
            "no_other_listed_release_on_event_day":summarize([r for r in rows if not r["event_day_other_flags"]]),
            "by_year":{str(y):summarize([r for r in rows if r["year"]==y]) for y in range(2018,2024)},
            "events":rows,"control_audit":audit["control_audit"],
            "limitations":["Date-level screening may exclude unrelated revisions or later releases; ALFRED dates are not all verified original announcements.",
                           "No assurance of a clean news-free window: ECB, Fed speeches, FOMC, other scheduled and unscheduled news not comprehensively covered.",
                           "Thursday claims can remove most matched Thursday windows, changing sample composition.",
                           "Descriptive only; reused controls and changing regimes preclude naive independent-event significance.",
                           "No pre-release placebo or causal attribution; Part B weekly prediction sample unchanged."]}
    json_write(root/"calendar_development_report.json",report)
    return report


if __name__=="__main__":
    r=run()
    print(json.dumps({k:r[k] for k in ("coverage","all_matched","no_other_listed_release_on_event_day")},indent=2))
    print("Send calendar_development_report.json. Final data not read.")
