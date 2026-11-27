"""TREND-002: fixed descriptive comparison after reviewed schedule preflight."""
import json
from datetime import date
from pathlib import Path
from statistics import median,mean

from binance_minute import digest
from forecast_journal import new_file
from research_buy import DAY,DEV_END,HASHES,days,load_development
from research_trend_break import (ROOT,DAILY_ROOT,EARLY_ROOT,EARLY_SHA,FIRST_DATE,
    COMMON_START,HORIZONS,analyze,clusters,read_early,merge_same_venue)

PREFLIGHT_SHA="f9f38050b2b3a2a82308c91f00446344af25461063dd15264aedd82227133727"
VERSION="TREND-002-descriptive-v1"
FEE=.001
RULES=("immediate","fixed7","split","recovery")


def schedules(t,recovery):
    return {"immediate":{t:1.},"fixed7":{t+7*DAY:1.},
            "split":{t:.5,t+7*DAY:.5},
            "recovery":{} if recovery is None else {recovery:1.}}


def simulate(prices,t,h,alloc,fee=FEE):
    terminal=t+h*DAY
    if not 0<=fee<1 or any(not t<=d<terminal or f<=0 for d,f in alloc.items()) or sum(alloc.values())>1:
        raise ValueError("Invalid allocation")
    if any(d not in prices or prices[d][4]<=0 for d in days(t,terminal+DAY)):
        raise ValueError("Incomplete common window")
    cash=1.;qty=0.;peak=1.;dd=0.;worst=1.;close_worst=1.;entries=[]
    def mark(value):
        nonlocal peak,dd,close_worst
        peak=max(peak,value)
        dd=min(dd,value/peak-1)
        close_worst=min(close_worst,value)
    for d in days(t,terminal):
        op,hi,lo,cl,_=prices[d]
        mark(cash+qty*op)
        if d in alloc:
            f=alloc[d]
            cash-=f
            qty+=f*(1-fee)/op
            entries.append({"date":d.isoformat(),"price":op,"fraction":f})
            mark(cash+qty*op)
        # Opening execution assumed; same day's low is after or at open.
        worst=min(worst,cash+qty*lo)
        mark(cash+qty*cl)
    wealth=cash+qty*prices[terminal][0]
    mark(wealth)
    return {"entries":entries,"btc_per_usd":qty,"cash":cash,
            "terminal_wealth":wealth,"terminal_return_pct":100*(wealth-1),
            "worst_initial_intraday_pct":100*(min(worst,close_worst)-1),
            "worst_initial_open_close_pct":100*(close_worst-1),
            "max_drawdown_open_close_pct":100*dd}


def compare(prices,preflight):
    rows=[]
    for ep in preflight["episodes"]:
        t=date.fromisoformat(ep["origin"])
        row={"origin":ep["origin"],"horizons":{}}
        for h in HORIZONS:
            key=str(h);a=ep["horizons"][key]
            if a["status"]!="eligible":
                row["horizons"][key]={"status":a["status"]}
                continue
            recovery=date.fromisoformat(a["recovery_entry"]) if a["recovery_entry"] else None
            rules={k:simulate(prices,t,h,v) for k,v in schedules(t,recovery).items()}
            for k,v in rules.items():
                for baseline in ("immediate","fixed7"):
                    b=rules[baseline]
                    v["vs_"+baseline]={
                        "terminal_delta_pp":100*(v["terminal_wealth"]-b["terminal_wealth"]),
                        "btc_delta_pct":100*(v["btc_per_usd"]/b["btc_per_usd"]-1),
                        "intraday_downside_delta_pp":v["worst_initial_intraday_pct"]-b["worst_initial_intraday_pct"],
                        "open_close_downside_delta_pp":v["worst_initial_open_close_pct"]-b["worst_initial_open_close_pct"],
                        "drawdown_delta_pp":v["max_drawdown_open_close_pct"]-b["max_drawdown_open_close_pct"]}
            row["horizons"][key]={"status":"eligible","schedule":a["recovery_vs_fixed7"],"rules":rules}
        rows.append(row)
    return rows


def stats(values):
    return {"n":len(values),"median":median(values),"mean":mean(values),
            "min":min(values),"max":max(values)} if values else {"n":0}


def paired(values):
    return {**stats(values),"better":sum(x>1e-9 for x in values),
            "worse":sum(x< -1e-9 for x in values),"equal":sum(abs(x)<=1e-9 for x in values)}


def summarize(rows,h):
    key=str(h)
    eligible=[r for r in rows if r["horizons"][key]["status"]=="eligible"]
    n=len(eligible)
    result={"eligible":n,"rules":{},"recovery_by_schedule":{}}
    metrics=("terminal_return_pct","worst_initial_intraday_pct","worst_initial_open_close_pct","max_drawdown_open_close_pct","btc_per_usd","cash")
    for k in RULES:
        values=[r["horizons"][key]["rules"][k] for r in eligible]
        result["rules"][k]={m:stats([v[m] for v in values]) for m in metrics}
        for baseline in ("immediate","fixed7"):
            result["rules"][k]["vs_"+baseline]={m:paired([v["vs_"+baseline][m] for v in values])
                for m in ("terminal_delta_pp","btc_delta_pct","intraday_downside_delta_pp","open_close_downside_delta_pp","drawdown_delta_pp")}
    def delta(r):
        return r["horizons"][key]["rules"]["recovery"]["vs_fixed7"]["terminal_delta_pp"]
    for category in ("same_as_fixed7","later_than_fixed7","cash"):
        group=[r for r in eligible if r["horizons"][key]["schedule"]==category]
        result["recovery_by_schedule"][category]={"terminal_delta_pp":paired([delta(r) for r in group]),
            "intraday_downside_delta_pp":paired([r["horizons"][key]["rules"]["recovery"]["vs_fixed7"]["intraday_downside_delta_pp"] for r in group])}
    groups=clusters([date.fromisoformat(r["origin"]) for r in eligible],h)
    # Report leave-one-connected-window-cluster-out sensitivity, not confidence intervals.
    sensitivity=[]
    for g in groups:
        inside=[r for r in eligible if g["first_origin"]<=r["origin"]<=g["last_terminal"]]
        outside=[r for r in eligible if not g["first_origin"]<=r["origin"]<=g["last_terminal"]]
        sensitivity.append({**g,"within":stats([delta(r) for r in inside]),
                            "remaining":stats([delta(r) for r in outside])})
    result["cluster_sensitivity"]=sensitivity
    result["recovery_vs_fixed7_by_year"]={y:paired([delta(r) for r in eligible if r["origin"].startswith(y)])
        for y in sorted({r["origin"][:4] for r in eligible})}
    return result


def checked_preflight(prices,first,expected):
    actual=analyze(prices,first)
    if json.loads(json.dumps(actual,sort_keys=True))!=expected:
        raise ValueError("Preflight replay mismatch")


def run(root=ROOT,daily_root=DAILY_ROOT,early_root=EARLY_ROOT):
    root=Path(root);target=root/"trend_break_comparison.json"
    if target.exists():
        raise ValueError("Comparison already exists; preserve original")
    raw=(root/"trend_break_preflight.json").read_bytes()
    if digest(raw)!=PREFLIGHT_SHA:
        raise ValueError("Reviewed preflight hash mismatch")
    pre=json.loads(raw)
    p={m:load_development(Path(daily_root),m) for m in HASHES}
    early=read_early(Path(early_root)/"bitstamp_early_daily.csv")
    full=merge_same_venue(early,p["bitstamp"])
    inputs={m:(v,COMMON_START,pre["markets"][m]) for m,v in p.items()}
    inputs["early_bitstamp"]=(full,FIRST_DATE,pre["early_bitstamp_sensitivity"])
    for prices,first,expected in inputs.values():
        checked_preflight(prices,first,expected)
    results={}
    for name,(prices,first,expected) in inputs.items():
        rows=compare(prices,expected)
        results[name]={"episodes":rows,"horizons":{str(h):summarize(rows,h) for h in HORIZONS}}
    common={}
    for h in HORIZONS:
        key=str(h)
        a,b=({r["origin"]:r for r in results[m]["episodes"] if r["horizons"][key]["status"]=="eligible"} for m in ("bitstamp","coinbase"))
        dates=sorted(a.keys()&b.keys())
        common[key]={"dates":dates,"bitstamp":summarize([a[d] for d in dates],h),
                     "coinbase":summarize([b[d] for d in dates],h)}
    report={"protocol":VERSION,"kind":"descriptive_not_confirmation","confirmation_authorized":False,
            "preflight_sha256":PREFLIGHT_SHA,"price_hashes":HASHES,"early_sha256":EARLY_SHA,
            "end_exclusive":DEV_END.isoformat(),"fee":FEE,"primary_horizon":28,
            "primary_comparison":"recovery_vs_fixed7","markets":results,"common_dates":common,
            "limitations":["No 2024+ numeric outcomes, no fitting, no optimization.",
                "Equal new budget only; actual whole-portfolio risks depend on existing holdings.",
                "Daily low risk and open/close risk separate; Coinbase 2017-04-15 extreme retained.",
                "No recovery by terminal means cash, not missing or forced purchase.",
                "BTC amount can be zero with cash still held; compare total wealth including cash.",
                "Monday open and 90-day terminal open are execution/valuation proxies, fixed fee, no yield or exit cost.",
                "Overlapping clusters and shared venue histories are not independent cycles; no inferential claim."]}
    root.mkdir(parents=True,exist_ok=True)
    new_file(target,report)
    for m,v in results.items():
        for h,s in v["horizons"].items():
            print(m,h,"days",s["eligible"],"recovery vs fixed7:",s["rules"]["recovery"]["vs_fixed7"]["terminal_delta_pp"],flush=True)
    print("Send:",target,flush=True)
    return report


if __name__=="__main__":
    run()
