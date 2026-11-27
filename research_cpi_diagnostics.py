"""Paired uncertainty and sensitivity checks for CPI development only."""
import copy
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from binance_minute import json_write, MINUTE
from research_cpi import OUT, verify_development, split_end
from research_cpi_development import load_split, read_table, number, replay, summary
from research_prices import DAY

SEED = 20261127
RESAMPLES = 10000
BLOCKS = (1, 3, 6)
BASE = "market_after"
CPI = "market_plus_cpi"


def paired_arrays(rows, wait_extra_cost_bp=0):
    """Losses and gains on identical events. Extra cost applies only to waiting."""
    if not rows:
        raise ValueError("Empty evaluation")
    y = np.asarray([r["y"] for r in rows], dtype=float)
    a = np.asarray([r["predictions"][BASE] for r in rows], dtype=float)
    b = np.asarray([r["predictions"][CPI] for r in rows], dtype=float)
    if not all(np.isfinite(x).all() for x in (y,a,b)) or (y<=-1).any():
        raise ValueError("Invalid evaluation values")
    gain = (1-wait_extra_cost_bp/10000)/(1+y)-1
    return (y-a)**2, (y-b)**2, np.abs(y-b)-np.abs(y-a), np.where(a<0,gain,0), np.where(b<0,gain,0), gain


def effect(rows, wait_extra_cost_bp=0):
    ea,eb,ma,ga,gb,gw=paired_arrays(rows,wait_extra_cost_bp)
    return {"n":len(rows),
            "delta_rmse_pp":float((np.sqrt(eb.mean())-np.sqrt(ea.mean()))*100),
            "delta_mae_pp":float(ma.mean()*100),
            "delta_purchase_gain_pp":float((gb-ga).mean()*100),
            "cpi_gain_vs_buy_now_pct":float(gb.mean()*100),
            "market_gain_vs_buy_now_pct":float(ga.mean()*100),
            "always_wait_gain_vs_buy_now_pct":float(gw.mean()*100),
            "cpi_worst_gain_pct":float(gb.min()*100),
            "cpi_gain_below_minus_5pct_fraction":float((gb<-.05).mean())}


def bootstrap(rows, block, seed=SEED, resamples=RESAMPLES):
    """Paired moving blocks of chronologically ordered evaluation events.

    Conditions on realized walk-forward predictions: not a full refit bootstrap.
    Calendar regimes/nonstationarity can invalidate nominal coverage.
    """
    n=len(rows)
    if not 1<=block<=n or resamples<1:
        raise ValueError("Invalid bootstrap dimensions")
    ea,eb,ma,ga,gb,_=paired_arrays(rows)
    rng=np.random.default_rng(seed)
    starts=rng.integers(0,n-block+1,size=(resamples,(n+block-1)//block))
    ix=(starts[:,:,None]+np.arange(block)).reshape(resamples,-1)[:,:n]
    stats={
        "delta_rmse_pp":(np.sqrt(eb[ix].mean(axis=1))-np.sqrt(ea[ix].mean(axis=1)))*100,
        "delta_mae_pp":ma[ix].mean(axis=1)*100,
        "delta_purchase_gain_pp":(gb-ga)[ix].mean(axis=1)*100,
        "cpi_gain_vs_buy_now_pct":gb[ix].mean(axis=1)*100,
    }
    return {key:[float(v) for v in np.quantile(x,[.025,.975])] for key,x in stats.items()}


def leave_one_score(rows):
    """Influence on scored results, keeping all original fitted predictions fixed."""
    if len(rows)<2:
        raise ValueError("Need two or more scored rows")
    return [{"excluded_event_id":r["id"],**effect(rows[:i]+rows[i+1:])}
            for i,r in enumerate(rows)]


def enriched(root, split, manifest):
    """Supplement immutable primary rows with already prepared alternative data."""
    primary=load_split(root,split,manifest)
    def indexed(name):
        rows=read_table(root,split+"_"+name+".csv",manifest)
        out={r["event_id"]:r for r in rows}
        if len(out)!=len(rows):
            raise ValueError("Duplicate supplemental event IDs")
        return out
    f=indexed("features")
    o=indexed("outcomes")
    d=indexed("delayed_features")
    for e in primary:
        eid=e["id"]
        row=f[eid]
        alternatives=sorted(set(number(x) for x in row["alternative_core_surprises_pp"].split("|") if x))
        if not alternatives or e["x"][3] not in alternatives:
            raise ValueError("Selected CPI surprise absent from alternatives")
        if row["core_mom_forecast_within_24h"] not in ("0","1"):
            raise ValueError("Invalid forecast recency")
        delayed=d[eid]
        late_entry=int(delayed["entry_utc_ms"])
        if late_entry!=e["entry"]+1410*MINUTE:
            raise ValueError("Unexpected delayed entry")
        e.update(alternatives=alternatives,recent=row["core_mom_forecast_within_24h"]=="1",
                 delayed_entry=late_entry,
                 delayed_reaction=None if not delayed["reaction_24h"] else number(delayed["reaction_24h"]),
                 delayed_y=None if not o[eid]["delayed_return_7d"] else number(o[eid]["delayed_return_7d"]))
    return primary


def alternative_rows(events, choose):
    # Use the same deterministic selection in training and evaluation. Extreme
    # published forecasts are stress scenarios, not substitute consensus estimates.
    out=copy.deepcopy(events)
    for e in out:
        e["x"][3]=choose(e["alternatives"])
    return out


def delayed_rows(events):
    out=[]
    for e in events:
        if e["delayed_reaction"] is None or e["delayed_y"] is None:
            continue
        r=copy.deepcopy(e)
        r["entry"]=e["delayed_entry"]
        r["known"]=r["entry"]-MINUTE
        r["exit"]=r["entry"]+7*DAY
        r["x"][2]=e["delayed_reaction"]
        r["y"]=e["delayed_y"]
        if r["y"]<=-1:
            raise ValueError("Invalid delayed return")
        out.append(r)
    return out


def historical_year(e):
    return datetime.fromtimestamp(e["entry"]/1000,tz=timezone.utc).year


def diagnostics(train, dev):
    rows=replay(train,dev)
    main=effect(rows)
    intervals={str(b):bootstrap(rows,b) for b in BLOCKS if b<=len(rows)}
    recent_ids={e["id"] for e in dev if e["recent"]}
    recent=[r for r in rows if r["id"] in recent_ids]
    # Recent forecast subset uses exactly the same predictions. No sample-driven
    # refitting or model selection.
    years={str(y):effect([r for r,e in zip(rows,dev) if historical_year(e)==y])
           for y in sorted({historical_year(e) for e in dev})}
    variants={}
    for name,choose in (("minimum_published_surprise",min),("maximum_published_surprise",max)):
        variants[name]=effect(replay(alternative_rows(train,choose),alternative_rows(dev,choose)))
    late_train,late_dev=delayed_rows(train),delayed_rows(dev)
    late_ids={e["id"] for e in late_dev}
    late={"n":len(late_dev),"train_n":len(late_train),"effect":None,"primary_same_dates":None}
    if len(late_train)>=30 and late_dev:
        late["effect"]=effect(replay(late_train,late_dev))
        late["primary_same_dates"]=effect([r for r in rows if r["id"] in late_ids])
    # Stress the initial training sample separately from evaluation influence.
    # These are not independent trials, and are never used to select a model.
    training_influence=[]
    for i,e in enumerate(train):
        reduced=train[:i]+train[i+1:]
        result=effect(replay(reduced,dev))
        training_influence.append({"excluded_training_event_id":e["id"],**result})
    return {"primary":main,"paired_95pct_intervals":intervals,"scores":summary(rows),
            "recent_forecast_eval_subset":effect(recent) if recent else None,
            "by_year_fixed_predictions":years,"alternative_surprise_replays":variants,
            "delayed_decision":late,"leave_one_evaluation_event":leave_one_score(rows),
            "leave_one_initial_training_event_refit":training_influence,
            "waiting_cost_sensitivity_bp":{str(b):effect(rows,b) for b in (-50,-25,-10,0,10,25,50)},
            "settings":{"seed":SEED,"resamples":RESAMPLES,"primary_block_events":3,
                        "sensitivity_block_events":[1,6]},
            "limitations":["Development only, all checks descriptive; no selection or final-test access.",
                           "Intervals condition on the realized predictions, not full refit or regime uncertainty.",
                           "Few releases and changing regimes make nominal coverage approximate.",
                           "Late-entry outcomes use a different forward window, not an identical trade comparison.",
                           "Forecast extrema are stress scenarios, not corrected consensus.",
                           "Costs are hypothetical differences between waiting and immediate buying."]}


def run(root=OUT):
    root=Path(root)
    coverage=verify_development(root,json.loads((root/"coverage.json").read_bytes()))
    manifest=coverage["file_sha256"]
    train,dev=[enriched(root,s,manifest) for s in ("train","development")]
    if (len(train),len(dev))!=(46,24):
        raise ValueError("Unexpected development sample")
    report={"protocol":"CPI-001-development-diagnostics-v1",
            "price_snapshot_sha256":coverage["price_provenance"]["snapshot_sha256"],
            "input_hashes":manifest,"train_n":len(train),"development_n":len(dev),
            "test_read":False,**diagnostics(train,dev)}
    json_write(root/"development_diagnostics.json",report)
    return report


if __name__=="__main__":
    r=run()
    print(json.dumps({k:r[k] for k in ("primary","paired_95pct_intervals","recent_forecast_eval_subset","delayed_decision")},indent=2))
    print("Send development_diagnostics.json. Final data not read.")
