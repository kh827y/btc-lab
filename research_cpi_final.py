"""Single frozen historical CPI-001 evaluation. No final CSVs, no LLM calls."""
import argparse
import json
import math
import subprocess
from pathlib import Path
from urllib.error import URLError
import zipfile

import numpy as np

from binance_minute import ROOT, MINUTE, digest, json_write
from research_prices import DAY, MinutePrices
from research_cpi import (BASE, OUT, CPI_HASH, PRICE_HASH, read_cpi, frozen_snapshot,
                          stamp, millis, split_name, prepare_event, verify_development)
from research_cpi_development import FEATURES, replay, summary
from research_cpi_diagnostics import (enriched, diagnostics, paired_arrays, BLOCKS,
                                      SEED, RESAMPLES)
from research_cpi_coinbase import CandleCache, independent_event, differences

REPO=Path(__file__).resolve().parent
LOCK="CPI_FINAL_LOCK.json"
REPORT="final_report.json"
FROZEN_FILES={"CPI_FINAL.md","research_cpi_final.py","research_cpi.py",
              "research_prices.py","binance_minute.py","research_cpi_development.py",
              "research_cpi_diagnostics.py","research_cpi_coinbase.py",
              "requirements.txt"}
FINAL_CUTOFF=millis(stamp("2026-11-27T00:00:00Z"))


def git(repo,*args):
    return subprocess.check_output(["git",*args],cwd=repo,stderr=subprocess.PIPE)


def normalized(raw):
    # Git checkout may convert LF to CRLF on Windows.
    return raw.replace(b"\r\n",b"\n")


def gate(repo=REPO):
    """Require committed, unchanged frozen protocol and calculation files."""
    commit=git(repo,"rev-parse","HEAD").decode().strip()
    committed=git(repo,"show",commit+":"+LOCK)
    if normalized((repo/LOCK).read_bytes())!=normalized(committed):
        raise ValueError("Uncommitted final lock")
    lock=json.loads(committed)
    if lock.get("protocol")!="CPI-001-final-v1" or set(lock["blobs"])!=FROZEN_FILES:
        raise ValueError("Unexpected final lock")
    if lock.get("price_snapshot_sha256")!=PRICE_HASH or lock.get("cpi_sha256")!=CPI_HASH:
        raise ValueError("Unexpected frozen data identifiers")
    for name,sha in lock["blobs"].items():
        if git(repo,"rev-parse",commit+":"+name).decode().strip()!=sha:
            raise ValueError("Frozen Git blob changed: "+name)
        if normalized((repo/name).read_bytes())!=normalized(git(repo,"cat-file","blob",sha)):
            raise ValueError("Local frozen file changed: "+name)
    return {"git_commit":commit,"lock_sha256":digest(committed),
            "protocol_blob":lock["blobs"]["CPI_FINAL.md"],"frozen_blobs":lock["blobs"]}


def optional(value):
    if value is None:
        return None
    x=float(value)
    if not math.isfinite(x):
        raise ValueError("Nonfinite value")
    return x


def final_events(events,alternatives,prices):
    reserved=[e for e in events if split_name(stamp(e["release_time_utc"]))=="test"]
    if len(reserved)!=34:
        raise ValueError("Unexpected reserved count")
    out=[];excluded=[];secondary=[]
    for e in reserved:
        f,o,_,d=prepare_event(e,alternatives[e["event_id"]],prices)
        eid=f["event_id"]
        if not o["primary_standard_sample_eligible"]:
            reason=[]
            if not f["standard_intraday_timing"]:
                reason.append("nonstandard_or_missing_paired_surprise")
            reason.extend(k for k in FEATURES if f[k] is None)
            reason.extend(k for k in ("entry_open","return_7d") if o[k] is None)
            excluded.append({"event_id":eid,"reason":reason,"event_note":f["event_note"]})
            continue
        t=f["entry_utc_ms"]
        x=[optional(f[k]) for k in FEATURES]
        y=optional(o["return_7d"])
        alt=sorted(set(float(v) for v in f["alternative_core_surprises_pp"].split("|") if v))
        if (y<=-1 or t+7*DAY>=FINAL_CUTOFF or t!=millis(stamp(f["release_time_utc"]))+31*MINUTE
                or d["entry_utc_ms"]!=t+1410*MINUTE or x[3] not in alt):
            raise ValueError("Invalid final event")
        out.append({"id":eid,"entry":t,"known":t-MINUTE,"exit":t+7*DAY,"x":x,"y":y,
                    "alternatives":alt,"recent":bool(f["core_mom_forecast_within_24h"]),
                    "delayed_entry":d["entry_utc_ms"],"delayed_reaction":optional(d["reaction_24h"]),
                    "delayed_y":optional(o["delayed_return_7d"])})
        secondary.append({"event_id":eid,"return_28d":o["return_28d"],"worst_7d":o["worst_7d"],
                          "worst_28d":o["worst_28d"],"headline_core_opposite_sign":
                          bool(f["headline_mom_surprise_pp"]*x[3]<0)})
    if len(out)!=32 or len({r["id"] for r in out})!=32:
        raise ValueError("Unexpected final eligible sample")
    return out,excluded,secondary


def mse_diagnostic(rows):
    ea,eb,*_=paired_arrays(rows)
    delta=(eb-ea)*10000
    n=len(delta)
    intervals={}
    for block in BLOCKS:
        if block>n:continue
        rng=np.random.default_rng(SEED)
        starts=rng.integers(0,n-block+1,size=(RESAMPLES,(n+block-1)//block))
        ix=(starts[:,:,None]+np.arange(block)).reshape(RESAMPLES,-1)[:,:n]
        intervals[str(block)]=[float(v) for v in np.quantile(delta[ix].mean(axis=1),[.025,.975])]
    return {"delta_mse_pp_squared":float(delta.mean()),
            "paired_95pct_intervals":intervals}


def describe_secondary(rows):
    out={}
    for key in ("return_28d","worst_7d","worst_28d"):
        x=[r[key] for r in rows if r[key] is not None]
        out[key]={"n":len(x),"missing":len(rows)-len(x),
                  "mean_pct":float(np.mean(x)*100) if x else None,
                  "min_pct":float(min(x)*100) if x else None}
    out["opposite_surprise_sign_n"]=sum(r["headline_core_opposite_sign"] for r in rows)
    return out


def replicate(history,final,root):
    cache=CandleCache(root/"coinbase_cache",cutoff=FINAL_CUTOFF)
    pairs=[];missing=[]
    for label,events in (("history",history),("final",final)):
        b,c=[],[]
        for e in events:
            r,reason=independent_event(e,cache,cutoff=FINAL_CUTOFF)
            if r is None:
                missing.append({"event_id":e["id"],"missing":reason})
            else:
                b.append(e);c.append(r)
        pairs.append((b,c))
    (bh,ch),(bf,cf)=pairs
    out={"status":"complete","history_matched":len(bh),"final_matched":len(bf),
         "missing":missing,"response_hashes":cache.used,
         "differences_final":differences(bf,cf) if bf else None,"same_dates_replay":None}
    if len(bh)>=30 and bf:
        out["same_dates_replay"]={"binance":summary(replay(bh,bf)),
                                  "coinbase":summary(replay(ch,cf))}
    return out


def find_archive():
    candidates=list(BASE.glob("BTC-Lab_US_CPI_2018-01_2026-11*.zip"))
    candidates+=list((Path.home()/"Downloads").glob("BTC-Lab_US_CPI_2018-01_2026-11*.zip"))
    for p in candidates:
        if p.stat().st_size<=2_000_000 and digest(p.read_bytes())==CPI_HASH:
            return p
    raise ValueError("Original CPI ZIP not found; drag it onto run_cpi_final.bat")


def run(archive=None,root=OUT,minute_root=ROOT,repo=REPO):
    root=Path(root)
    # No outcome reads until the committed specification passes.
    frozen=gate(repo)
    target=root/REPORT
    if target.exists():
        raise ValueError("Final report already exists; do not rerun or overwrite")
    m=verify_development(root,json.loads((root/"coverage.json").read_bytes()))
    hist=[enriched(root,s,m["file_sha256"]) for s in ("train","development")]
    if tuple(map(len,hist))!=(46,24):
        raise ValueError("Unexpected training coverage")
    history=hist[0]+hist[1]
    events,alternatives,h=read_cpi(archive or find_archive())
    if h!=CPI_HASH:
        raise ValueError("Wrong CPI archive")
    # Exclusive marker only for simultaneous runs; no metrics shown on failure.
    marker=root/"final_running.tmp"
    with marker.open("x") as stream:
        stream.write(frozen["git_commit"])
    try:
        if target.exists():
            raise ValueError("Final report already exists")
        prices=MinutePrices.load(minute_root,frozen=frozen_snapshot(minute_root,root))
        final,excluded,secondary=final_events(events,alternatives,prices)
        del prices
        rows=replay(history,final)
        detail=diagnostics(history,final)
        detail["limitations"][0]="Historical final sample, fixed descriptive sensitivities; not a prospective holdout."
        print("Primary calculation complete. Checking independent Coinbase prices.",flush=True)
        try:
            independent=replicate(history,final,root)
        except (OSError,ValueError,KeyError,URLError) as exc:
            independent={"status":"unavailable","error":str(exc),
                         "note":"Primary Binance result retained; independent final replication incomplete."}
        report={"protocol":"CPI-001-final-v1","frozen":frozen,
                "cpi_sha256":h,"price_snapshot_sha256":PRICE_HASH,
                "historical_training_n":len(history),"test_reserved":34,"test_eligible":32,
                "test_read":True,"excluded":excluded,"predictions":rows,
                "diagnostics":detail,"mse":mse_diagnostic(rows),
                "secondary_outcomes":describe_secondary(secondary),"secondary_events":secondary,
                "independent_coinbase":independent,
                "limitations":["Historical holdout, not guaranteed unknown to humans or LLMs.",
                               "All results conditional on available standard paired CPI events; no fallback evaluation on excluded dates.",
                               "Part A remains development-only descriptive calendar screen; no causal identification.",
                               "28-day returns and excursion are descriptive, not separately trained forecasts; later events can contribute.",
                               "No per-portfolio return claim, no model tuning, no actual trade."]}
        json_write(target,report)
        return report
    finally:
        marker.unlink(missing_ok=True)


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("archive",nargs="?",type=Path)
    args=p.parse_args()
    run(args.archive)
    print("Final report saved. Send data/research/cpi/final_report.json. Do not rerun.")
