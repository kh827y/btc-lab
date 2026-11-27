"""Frozen BUY-001 historical final. Explicit local command; no network or LLM."""
import json
import subprocess
from datetime import date
from pathlib import Path

import numpy as np

from binance_minute import digest,json_write
import research_buy as base
import research_buy_risk as risk
import research_buy_audit as audit

REPO=Path(__file__).resolve().parent
VERSION="BUY-001-final-v1"
LOCK="BUY_FINAL_LOCK.json"
START=base.DEV_END
END=date(2026,11,27)
REPORT="buy_final_report.json"
FROZEN={"BUY_FINAL.md","BUY_PROTOCOL.md","research_buy_final.py","research_buy.py",
        "research_buy_risk.py","research_buy_audit.py","research_daily_usd.py",
        "binance_minute.py","buy_journal.py","forecast_journal.py","requirements.txt"}
OLD={
    "buy_development_report.json":"fa91497fed3a8601b7951b39a80e1bf26a2cb87cd489126c9ef25ba77eb97c92",
    "buy_risk_extension_report.json":"a567f3e1917f4036ae038d520b7ab29f03b23cb0a4f07d53aad164bb8398ac2c",
    "buy_audit_controls_report.json":"9328840c43b806d44797b44e3d3060d5159dc6697e5ec34358a5a2227ab488a4",
}


def git(repo,*args):
    return subprocess.check_output(["git",*args],cwd=repo,stderr=subprocess.PIPE)


def norm(raw):
    return raw.replace(b"\r\n",b"\n")


def gate(repo=REPO):
    commit=git(repo,"rev-parse","HEAD").decode().strip()
    raw=git(repo,"show",commit+":"+LOCK)
    if norm(raw)!=norm((repo/LOCK).read_bytes()):
        raise ValueError("Uncommitted BUY lock")
    lock=json.loads(raw)
    if (lock["protocol"]!=VERSION or lock["input_hashes"]!=base.HASHES
        or lock["development_report_hashes"]!=OLD or set(lock["blobs"])!=FROZEN):
        raise ValueError("Invalid BUY lock")
    for path,sha in lock["blobs"].items():
        if git(repo,"rev-parse",commit+":"+path).decode().strip()!=sha:
            raise ValueError("Frozen Git blob changed: "+path)
        if norm((repo/path).read_bytes())!=norm(git(repo,"cat-file","blob",sha)):
            raise ValueError("Local frozen file changed: "+path)
    return {"commit":commit,"lock_sha256":digest(raw),"blobs":lock["blobs"]}


def verify_previous(root):
    for name,h in OLD.items():
        if digest((root/name).read_bytes())!=h:
            raise ValueError("Original development report changed: "+name)


def forecast_rows(prices,sig,ext,start,end):
    rows=[];scored=[];skipped=[]
    for t in base.mondays(start,end):
        if t+(base.HORIZON+1)*base.DAY>end:
            break
        y=base.outcome(prices,t)
        if t not in sig or t not in ext or y is None:
            skipped.append(t.isoformat())
            continue
        scored.append({"date":t.isoformat(),"models":{k:base.forecast_score(v,y)
                       for k,v in sig[t]["models"].items()}})
        rows.append({"date":t.isoformat(),"actual":{"up":int(y["log_return"]>0),
                     "loss_15":int(y["log_worst"]<=np.log(.85))},
                     "pred":{k:{f:v[f] for f in ("p_up","p_loss_15")}
                             for k,v in ext[t]["pred"].items()}})
    return rows,scored,skipped


def evidence(effect,interval):
    # Descriptive practical orientation, not a significance test.
    if interval is None:
        return "insufficient_interval"
    if effect>=1 and interval[0]>0:
        return "candidate_positive_not_confirmed"
    if effect<=-1 and interval[1]<0:
        return "candidate_negative_not_confirmed"
    return "inconclusive_or_small"


def primary_controls(controls,direct):
    a=controls["M1"]
    out={"M1_vs_rotated_M1":{"mean_log_gain_pct":a["actual_minus_mean_placebo_log_gain_pct"],
                            "conditional_interval90":a["conditional_interval90_log_delta"]},
         **direct}
    for v in out.values():
        v["descriptive_orientation"]=evidence(v["mean_log_gain_pct"],v["conditional_interval90"]["52"])
    return out


def analyze(prices,market,start=START,end=END):
    if not START<=start<end<=END:
        raise ValueError("Invalid final period")
    sig=base.build_signals(prices,base.FIRST[market],end)
    ext=risk.build_signals(prices,base.FIRST[market],end)
    pred,scored,missing=forecast_rows(prices,sig,ext,start,end)
    if not pred:
        raise ValueError("No completed forecast outcomes")
    rows,skipped=base.purchase_episodes(prices,sig,start,end)
    ext_rows=risk.purchase_rows(prices,ext,start,end)
    dates,op,cl,schedules=audit.collect_schedules(prices,ext,start,end)
    if [d.isoformat() for d in dates]!=[r["date"] for r in ext_rows]:
        raise ValueError("Rotation and extension samples differ")
    if [r["date"] for r in rows]!=[r["date"] for r in ext_rows]:
        raise ValueError("Base and extension samples differ")
    controls={m:audit.model_control(dates,op,cl,schedules[m]) for m in audit.MODELS}
    direct=audit.direct(dates,op,cl,schedules)
    variants={}
    for name,kw in (("4w",{"n":4}),("16w",{"n":16}),("ma10",{"ma":10}),
                    ("ma50",{"ma":50}),("dip10",{"dip":.1}),("dip30",{"dip":.3}),
                    ("risk70",{"risk":.7}),("risk90",{"risk":.9})):
        rr,ss=base.purchase_episodes(prices,sig,start,end,**kw)
        variants[name]={"stats":base.stats(rr,kw.get("n",8),False),"skipped":ss}
    # Fixed cash yield sensitivity; identical funding and fee.
    cash={}
    for scenario,rate in (("cash0",0.),("cash5",.05)):
        cash_rows=[]
        for r in rows:
            t=date.fromisoformat(r["date"])
            values={k:risk.schedule(prices,t,v["allocations"],annual_cash=rate)
                    for k,v in r["rules"].items()}
            cash_rows.append({"date":r["date"],scenario:{**values,
                "fixed_delay":risk.schedule(prices,t,[.5]+[1]*6+[1.5],annual_cash=rate)}})
        cash[scenario]=risk.purchase_summary(cash_rows,scenario)
    baseline=base.stats(rows)
    return {"first_purchase_origin":dates[0].isoformat(),"last_purchase_origin":dates[-1].isoformat(),
            "forecast_n":len(pred),"purchase_n":len(rows),"missing_forecast_dates":missing,
            "skipped_purchase_dates":skipped,"baseline":baseline,"baseline_forecast":base.risk_summary(scored,start),
            "extension_forecast":risk.assess(pred),"extension_cash0":risk.purchase_summary(ext_rows,"cash0"),
            "extension_cash5":risk.purchase_summary(ext_rows,"cash5"),"baseline_cash":cash,
            "rotation_controls":controls,"primary_comparisons":primary_controls(controls,direct),
            "trigger_rates":audit.triggers(ext,dates),"variants":variants,
            "by_year":{str(y):base.stats([r for r in rows if r["date"].startswith(str(y))],intervals=False)
                        for y in range(start.year,end.year+1)},
            "tail_guardrail_vs_dca":{k:v["p05_gain_vs_dca_pct"]>=-10
                                      for k,v in baseline["rules"].items()},
            "prediction_rows":pred,"purchase_rows":rows,"extension_purchase_rows":ext_rows}


def run(root=base.ROOT,repo=REPO):
    root=Path(root)
    frozen=gate(repo)
    target=root/REPORT
    if target.exists():
        raise ValueError("Final report already exists; do not rerun or overwrite")
    verify_previous(root)
    marker=root/"buy_final_running.tmp"
    with marker.open("x") as f:
        f.write(frozen["commit"])
    try:
        if target.exists():
            raise ValueError("Final report already exists")
        markets={}
        for m in base.HASHES:
            print("Final evaluation:",m,flush=True)
            prices=base.load_prefix(root,m,END)
            markets[m]=analyze(prices,m)
        report={"protocol":VERSION,"frozen":frozen,"input_hashes":base.HASHES,
                "development_report_hashes":OLD,"start":START.isoformat(),
                "end_exclusive":END.isoformat(),"test_numeric_values_parsed":True,
                "primary_market":"bitstamp","primary_block_weeks":52,"markets":markets,
                "limitations":["Historical holdout, not guaranteed unknown to humans or models.",
                    "No parameter tuning, all fixed variants reported, primary family descriptive only.",
                    "Rotation rank not a p-value; no valid Holm significance claim.",
                    "52-week conditional intervals not calibrated; few independent regimes.",
                    "M1 direction identical to M0; M2 negative result pertains to this estimator only.",
                    "Coinbase shares the same market episodes.",
                    "Opening prices are execution proxies, close-based portfolio drawdown; no actual trades.",
                    "Identical proportional fee cancels in BTC ratios; cash 5% hypothetical.",
                    "No automatic trading recommendation regardless of historical result."]}
        json_write(target,report)
        print("Send",target,flush=True)
        return report
    finally:
        marker.unlink(missing_ok=True)


if __name__=="__main__":
    run()
