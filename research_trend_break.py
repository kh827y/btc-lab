"""TREND-002 preflight: count actionable schedules, never score price outcomes."""
from collections import Counter
from datetime import date
from pathlib import Path

from forecast_journal import new_file
from research_buy import DAY,WEEK,DEV_END,HASHES,FIRST,ROOT as DAILY_ROOT,days,mondays,window,load_development
from research_extended_description import EARLY_ROOT,EARLY_SHA,FIRST_DATE,read_early,merge_same_venue

ROOT=Path(__file__).resolve().parent/"data"/"research"/"trend_break_v1"
VERSION="TREND-002-feasibility-v1"
COMMON_START=max(FIRST.values())
HORIZONS=(28,90)


def weekly_states(prices,first,end):
    if not first<end<=DEV_END or any(d>=end for d in prices):
        raise ValueError("Only development-period prices permitted")
    # Monday origin; Saturday close is the last allowed signal input.
    states={}
    for t in mondays(first,end):
        stop=t-DAY
        if stop-50*DAY<first:
            continue
        a=window(prices,stop-50*DAY,stop)
        states[t]=None if a is None else bool(a[-1,3]>a[:,3].mean())
    return states


def episodes(states):
    rows=[];invalid=[];left=[];previous=None;active=None
    for t,s in sorted(states.items()):
        if s is None:
            invalid.append(t.isoformat())
            if active is not None:
                active.update(status="gap_censored",gap=t)
                active=None
            previous=None
            continue
        if s:
            if active is not None:
                active.update(status="recovered",recovery=t)
                active=None
        elif previous is True:
            active={"origin":t,"status":"end_censored","recovery":None,"gap":None}
            rows.append(active)
        elif previous is None:
            left.append(t.isoformat())
        previous=s
    return rows,invalid,left


def availability(prices,ep,h,end):
    t=ep["origin"];terminal=t+h*DAY
    if terminal>=end:
        return {"status":"cutoff_censored"}
    # Check existence/volume only. Do not compute any outcome metric.
    if any(d not in prices or prices[d][4]<=0 for d in days(t,terminal+DAY)):
        return {"status":"price_gap"}
    if ep["gap"] is not None and ep["gap"]<terminal:
        return {"status":"signal_gap"}
    r=ep["recovery"]
    delay=(r-t).days if r is not None and r<terminal else None
    category="cash" if delay is None else ("same_as_fixed7" if delay==7 else "later_than_fixed7")
    return {"status":"eligible","recovery_entry":(t+delay*DAY).isoformat() if delay is not None else None,
            "wait_days":delay,"recovery_vs_fixed7":category}


def clusters(origins,h):
    # Connected components of inclusive observation windows, not independent samples.
    groups=[]
    for t in sorted(origins):
        terminal=t+h*DAY
        if not groups or t>groups[-1]["last_terminal"]:
            groups.append({"first_origin":t,"last_terminal":terminal,"origins":1})
        else:
            groups[-1]["last_terminal"]=max(groups[-1]["last_terminal"],terminal)
            groups[-1]["origins"]+=1
    return [{"first_origin":g["first_origin"].isoformat(),
             "last_terminal":g["last_terminal"].isoformat(),"origins":g["origins"]} for g in groups]


def analyze(prices,first,end=DEV_END):
    states=weekly_states(prices,first,end)
    eps,invalid,left=episodes(states)
    rows=[]
    for e in eps:
        rows.append({"origin":e["origin"].isoformat(),"status":e["status"],
                     "recovery_origin":e["recovery"].isoformat() if e["recovery"] else None,
                     "gap_origin":e["gap"].isoformat() if e["gap"] else None,
                     "horizons":{str(h):availability(prices,e,h,end) for h in HORIZONS}})
    result={}
    for h in HORIZONS:
        key=str(h)
        complete=[r for r in rows if r["horizons"][key]["status"]=="eligible"]
        diff=[r for r in complete if r["horizons"][key]["recovery_vs_fixed7"]!="same_as_fixed7"]
        origins=[date.fromisoformat(r["origin"]) for r in complete]
        diff_origins=[date.fromisoformat(r["origin"]) for r in diff]
        groups=clusters(diff_origins,h)
        result[key]={"eligibility":dict(Counter(r["horizons"][key]["status"] for r in rows)),
            "eligible":len(complete),"recovery_vs_fixed7":dict(Counter(r["horizons"][key]["recovery_vs_fixed7"] for r in complete)),
            "different_from_fixed7":len(diff),"different_by_year":dict(Counter(d.year for d in diff_origins)),
            "all_overlap_clusters":clusters(origins,h),"different_overlap_clusters":groups,
            "minimum_variation_present":len(groups)>=2}
    return {"history_start":first.isoformat(),"weekly_states":len(states),"invalid_state_origins":invalid,
            "left_unobserved_below_starts":left,"episode_count":len(rows),
            "episode_status_counts":dict(Counter(r["status"] for r in rows)),"episodes":rows,"horizons":result}


def run(root=ROOT,daily_root=DAILY_ROOT,early_root=EARLY_ROOT):
    root=Path(root);target=root/"trend_break_preflight.json"
    if target.exists():
        raise ValueError("Preflight already exists; preserve original")
    p={m:load_development(Path(daily_root),m) for m in HASHES}
    markets={m:analyze(v,COMMON_START) for m,v in p.items()}
    early=read_early(Path(early_root)/"bitstamp_early_daily.csv")
    full=merge_same_venue(early,p["bitstamp"])
    sensitivity=analyze(full,FIRST_DATE)
    a,b=({r["origin"] for r in markets[m]["episodes"]} for m in ("bitstamp","coinbase"))
    report={"protocol":VERSION,"kind":"schedule_feasibility_only",
            "confirmation_authorized":False,"outcomes_scored":False,"post_2023_numeric_values_parsed":False,
            "price_hashes":HASHES,"early_sha256":EARLY_SHA,"end_exclusive":DEV_END.isoformat(),
            "ma_days":50,"markets":markets,"early_bitstamp_sensitivity":sensitivity,
            "exact_common_trigger_dates":sorted(a&b),"bitstamp_only":sorted(a-b),"coinbase_only":sorted(b-a),
            "limitations":["Only state and schedule dates, no entry price, return, or risk metrics.",
              "Overlapping windows and shared market cycles are not independent observations.",
              "Early Bitstamp is sensitivity only, no independent validation.",
              "Variation flag is descriptive, not power or permission to score outcomes."]}
    root.mkdir(parents=True,exist_ok=True)
    new_file(target,report)
    for name,item in list(markets.items())+[("early_bitstamp",sensitivity)]:
        print(name,"episodes",item["episode_count"],flush=True)
        for h,r in item["horizons"].items():
            print(h,"days: eligible",r["eligible"],"different vs fixed7",r["different_from_fixed7"],
                  "clusters",len(r["different_overlap_clusters"]),flush=True)
    print("Send:",target,flush=True)
    return report


if __name__=="__main__":
    run()
