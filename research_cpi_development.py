"""CPI development replay: only train and development data, never test CSVs."""
import csv
import io
import json
import math
from pathlib import Path

import numpy as np

from binance_minute import digest, json_write
from research_cpi import OUT, stamp, millis, verify_development
from research_prices import DAY

FEATURES = ("prior_return_28d", "prior_vol_28d", "reaction_30m", "core_mom_surprise_pp")
MODELS = {"zero": None, "historical_mean": 0, "market_before": 2,
          "market_after": 3, "market_plus_cpi": 4}


def read_table(root, name, manifest):
    raw = (root/name).read_bytes()
    if digest(raw) != manifest[name]:
        raise ValueError("Prepared file hash mismatch: "+name)
    return list(csv.DictReader(io.StringIO(raw.decode("utf-8"))))


def number(value):
    x = float(value)
    if not math.isfinite(x):
        raise ValueError("Nonfinite feature/outcome")
    return x


def load_split(root, split, manifest):
    if split not in ("train", "development"):
        raise ValueError("Final test data are not permitted")
    f = read_table(root,split+"_features.csv",manifest)
    o = read_table(root,split+"_outcomes.csv",manifest)
    om = {r["event_id"]:r for r in o}
    if len(om)!=len(o) or len({r["event_id"] for r in f})!=len(f) or set(om)!={r["event_id"] for r in f}:
        raise ValueError("Nonunique or unmatched event IDs")
    events=[]
    for row in f:
        dt=stamp(row["release_time_utc"])
        if row["split"]!=split or not (2018<=dt.year<=2021 if split=="train" else 2022<=dt.year<=2023):
            raise ValueError("Wrong chronological partition")
        outcome=om[row["event_id"]]
        if outcome["primary_standard_sample_eligible"] not in ("0","1"):
            raise ValueError("Invalid eligibility flag")
        if outcome["primary_standard_sample_eligible"]=="0":
            continue
        if row["standard_intraday_timing"]!="1":
            raise ValueError("Inconsistent eligibility flag")
        entry=int(row["entry_utc_ms"])
        if entry!=millis(dt)+31*60_000:
            raise ValueError("Incorrect entry")
        y=number(outcome["return_7d"])
        if y<=-1:
            raise ValueError("Invalid return")
        events.append({"id":row["event_id"],"entry":entry,
                       "known":entry-60_000,"exit":entry+7*DAY,
                       "x":[number(row[k]) for k in FEATURES],"y":y})
    if len({e["entry"] for e in events})!=len(events):
        raise ValueError("Duplicate decision times")
    return sorted(events,key=lambda e:e["entry"])


def predict(past, row, columns):
    if columns is None:
        return 0.0
    y=np.asarray([e["y"] for e in past],dtype=float)
    if columns==0:
        return float(y.mean())
    x=np.asarray([e["x"][:columns] for e in past],dtype=float)
    center=x.mean(axis=0)
    scale=x.std(axis=0)
    # Fixed policy: a constant training column contributes zero.
    scale=np.where(scale==0,1.0,scale)
    design=np.column_stack([np.ones(len(x)),(x-center)/scale])
    beta,_,_,_=np.linalg.lstsq(design,y,rcond=None)
    z=np.r_[1.,(np.asarray(row["x"][:columns])-center)/scale]
    return float(z@beta)


def replay(train, development):
    history=list(train)
    results=[]
    for event in development:
        # Outcome must have been realized by the prediction cutoff, not merely
        # a preceding release. Do not use the execution bar as a predictor.
        past=[r for r in history if r["exit"]<=event["known"] and r["entry"]<event["entry"]]
        if len(past)<30:
            raise ValueError("Insufficient completed training episodes")
        predictions={name:predict(past,event,cols) for name,cols in MODELS.items()}
        results.append({"id":event["id"],"training_count":len(past),"y":event["y"],
                        "predictions":predictions})
        history.append(event)
    return results


def summary(rows):
    if not rows:
        raise ValueError("No development episodes")
    y=np.asarray([r["y"] for r in rows])
    scores={}
    for name in MODELS:
        pred=np.asarray([r["predictions"][name] for r in rows])
        err=(y-pred)**2
        delay=pred<0
        # One identical notional purchase in each scenario, same proportional
        # costs; BTC quantity ratio (wait/now) = 1/(1+y).
        gains=np.where(delay,1/(1+y)-1,0.0)
        scores[name]={"rmse_pp":float(np.sqrt(err.mean())*100),
                      "mae_pp":float(np.abs(y-pred).mean()*100),
                      "delayed_count":int(delay.sum()),
                      "mean_btc_quantity_gain_vs_buy_now_pct":float(gains.mean()*100),
                      "worst_btc_quantity_gain_vs_buy_now_pct":float(gains.min()*100)}
    a,b=scores["market_after"],scores["market_plus_cpi"]
    return {"n":len(rows),"scores":scores,
            "delta_rmse_pp_cpi_minus_market":b["rmse_pp"]-a["rmse_pp"],
            "delta_mean_btc_quantity_gain_pp":b["mean_btc_quantity_gain_vs_buy_now_pct"]-a["mean_btc_quantity_gain_vs_buy_now_pct"]}


def run(root=OUT):
    root=Path(root)
    manifest=json.loads((root/"coverage.json").read_text(encoding="utf-8"))
    verify_development(root,manifest)
    train,dev=[load_split(root,s,manifest["file_sha256"]) for s in ("train","development")]
    if (len(train),len(dev))!=(46,24):
        raise ValueError("Unexpected eligible counts")
    if set(e["id"] for e in train)&set(e["id"] for e in dev):
        raise ValueError("Duplicate cross-partition event")
    rows=replay(train,dev)
    report={"protocol":"CPI-001-development-v1","preparation":manifest["protocol"],"price_snapshot_sha256":manifest["price_provenance"]["snapshot_sha256"],"train_n":len(train),
            "development":summary(rows),"test_read":False,
            "training_count_first":rows[0]["training_count"],"training_count_last":rows[-1]["training_count"],
            "data_hashes":{k:v for k,v in manifest["file_sha256"].items()
                           if k in ("train_features.csv","train_outcomes.csv","development_features.csv","development_outcomes.csv")},
            "limitations":["Development only; not independent evidence of predictive value.",
                           "No cross-exchange price check or calendar audit yet.",
                           "No confidence intervals in development smoke test.",
                           "Common proportional buy costs cancel in the BTC-quantity ratio; variable costs/cash yield not modeled."]}
    json_write(root/"development_report.json",report)
    json_write(root/"development_predictions.json",rows)
    return report


if __name__=="__main__":
    print(json.dumps(run(),indent=2))
    print("Send development_report.json only. Final test not read.")
