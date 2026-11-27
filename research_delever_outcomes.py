"""One frozen descriptive DELEVER-001 outcome run after reviewed preflight."""
import json
import statistics
from pathlib import Path

from binance_minute import digest, ms
from forecast_journal import new_file
from research_delever import (ROOT, FIRST, END, HOUR, PANEL_SHA, COVERAGE_SHA,
                              VERSION, positive, select, summary)

PREFLIGHT_SHA = "e1f218b6eb4964934f34b237ac700974de071d0e6889b1c1851228535a116a13"


def read_checked(path, sha):
    raw = path.read_bytes()
    if digest(raw) != sha:
        raise ValueError("Reviewed byte hash mismatch: " + str(path))
    return json.loads(raw)


def price(row, field):
    bar = row.get("spot")
    v = bar.get(field) if bar else None
    return v if positive(v) else None


def measure(rows, index, days):
    """Price-only outcome. Terminal open belongs to the window, not its low."""
    end = index + days*24
    eligible = 0 <= index < end < len(rows)
    out = {"calendar_eligible": eligible, "entry": None, "terminal": None,
           "wait_cost": None, "worst_from_entry": None,
           "delayed_btc_relative": None, "split_btc_relative": None}
    if not eligible:
        return out
    a, b = price(rows[index], "open"), price(rows[end], "open")
    out.update(entry=a, terminal=b)
    if a is None or b is None:
        return out
    out.update(wait_cost=b/a-1, delayed_btc_relative=a/b,
               split_btc_relative=(1+a/b)/2)
    if days == 7:
        lows = [price(r, "low") for r in rows[index:end]]
        if all(x is not None for x in lows):
            out["worst_from_entry"] = min(0., min(lows+[b])/a-1)
    return out


def distribution(values):
    v = [x for x in values if x is not None]
    if not v:
        return {"n":0, "median":None, "mean":None, "q25":None,
                "q75":None, "min":None, "max":None, "share_positive":None}
    q = statistics.quantiles(v,n=4,method="inclusive") if len(v)>1 else [v[0]]*3
    return {"n":len(v),"median":statistics.median(v),"mean":statistics.mean(v),
            "q25":q[0],"q75":q[2],"min":min(v),"max":max(v),
            "share_positive":sum(x>0 for x in v)/len(v)}


def overlap(items, days):
    times = sorted(r["entry_utc_ms"] for r in items if r[str(days)]["wait_cost"] is not None)
    width = days*24*HOUR
    pairs = sum(b-a<width for i,a in enumerate(times) for b in times[i+1:])
    clusters = sum(i==0 or t-times[i-1]>=width for i,t in enumerate(times))
    return {"scored_windows":len(times),"overlapping_pairs":pairs,
            "overlap_clusters":clusters}


def group_stats(items):
    out = {"episodes":len(items)}
    for days in (7,28):
        key = str(days)
        eligible = [r[key] for r in items if r[key]["calendar_eligible"]]
        result = {"calendar_eligible":len(eligible),
                  "calendar_ineligible":len(items)-len(eligible),
                  "missing_wait_cost":sum(r["wait_cost"] is None for r in eligible)}
        fields = ["wait_cost","delayed_btc_relative","split_btc_relative"]
        if days==7:
            fields.append("worst_from_entry")
            result["missing_risk"] = sum(r["worst_from_entry"] is None for r in eligible)
        for field in fields:
            result[field] = distribution([r[field] for r in eligible])
        out[key] = result
    return out


def compare(items):
    groups = {"all_price_shocks":group_stats(items)}
    for g in ("contraction","other","unknown"):
        groups[g] = group_stats([r for r in items if r["group"]==g])
    diffs = {}
    for days in (7,28):
        key = str(days)
        a,b = (groups[g][key]["wait_cost"]["median"] for g in ("contraction","other"))
        diffs[key] = a-b if a is not None and b is not None else None
    return {"groups":groups,"median_wait_cost_difference":diffs,
            "overlap":{"7":overlap(items,7),"28":overlap(items,28)}}


def run(root=ROOT):
    root = Path(root)
    target = root/"delever_outcomes.json"
    if target.exists():
        raise ValueError("Outcome report already exists; do not rerun")
    pre = read_checked(root/"delever_preflight.json",PREFLIGHT_SHA)
    if (pre["protocol"]!=VERSION or pre["panel_sha256"]!=PANEL_SHA or
        pre["coverage_sha256"]!=COVERAGE_SHA or pre["forward_outcomes_computed"] is not False or
        not pre["summary"]["reporting_floor_met"]):
        raise ValueError("Unexpected reviewed preflight")
    read_checked(root/"panel_coverage.json",COVERAGE_SHA)
    panel = read_checked(root/"hourly_panel.json",PANEL_SHA)
    rows = panel["rows"]
    if panel["version"]!="derivative-hourly-v1" or len(rows)!=(END-FIRST).days*24:
        raise ValueError("Unexpected panel")
    start = ms(FIRST)
    for i,r in enumerate(rows):
        if r["hour_open_utc_ms"]!=start+i*HOUR:
            raise ValueError("Panel calendar changed")
    episodes,missing,counts = select(rows)
    if (episodes!=pre["episodes"] or counts!=pre["counts"] or
        missing!=pre["missing_boundary_dates"] or summary(episodes)!=pre["summary"]):
        raise ValueError("Frozen preflight replay mismatch")
    items = []
    for e in episodes:
        index = (e["entry_utc_ms"]-start)//HOUR
        item = {**e, "7":measure(rows,index,7), "28":measure(rows,index,28)}
        if item["7"]["calendar_eligible"]!=e["calendar_eligible7"]:
            raise ValueError("Outcome calendar mismatch")
        items.append(item)
    report = {"protocol":VERSION, "kind":"descriptive_outcomes",
              "panel_sha256":PANEL_SHA, "coverage_sha256":COVERAGE_SHA,
              "preflight_sha256":PREFLIGHT_SHA, "episodes":items,
              "primary":compare(items),
              "by_year":{y:compare([r for r in items if r["shock_date"][:4]==y])
                         for y in sorted({r["shock_date"][:4] for r in items})},
              "by_drop_band":{b:compare([r for r in items if r["drop_band"]==b])
                              for b in ("5to10","10plus")},
              "limitations":["Descriptive only; no causal or forecasting claim.",
                "Unequal shock severity, prior trend and year mix; no fitted adjustment.",
                "Same proportional fee cancels in relative BTC quantity; zero cash yield.",
                "28-day windows overlap; even nonoverlapping windows share market regimes.",
                "No alternative thresholds or post-outcome group selection.",
                "Historical original availability unverified; single venue."]}
    sha = new_file(target,report)
    print("Send:",target,"SHA-256:",sha,flush=True)


if __name__=="__main__":
    run()
