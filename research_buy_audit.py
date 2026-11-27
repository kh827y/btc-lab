"""BUY-001 audit controls, development only. Preserve both original reports."""
import json
from pathlib import Path
from datetime import date
import numpy as np

from binance_minute import digest,json_write
from research_buy import (ROOT,HASHES,FIRST,DEV_END,COMMON_START,DAY,WEEK,
                          mondays,window,load_development,simulate)
from research_buy_risk import replay,interval

MODELS=("M1","L1","M2")
MIN_SHIFT=13
VERSION="BUY-001-audit-controls-development-v1"


def contiguous(dates):
    if any(b-a!=WEEK for a,b in zip(dates,dates[1:])):
        raise ValueError("Calendar rotation requires consecutive eligible weeks")


def collect(prices,signals,end=DEV_END):
    if end>DEV_END:
        raise ValueError("Final data are not permitted")
    mapped={m:{t:{**v["state"],"models":{"M1":v["pred"][m]},
                  "thresholds":{.8:v["thresholds"][m]}}
               for t,v in signals.items() if v["thresholds"][m] is not None}
            for m in MODELS}
    dates=[];opens=[];closes=[];schedules={m:[] for m in MODELS}
    # Exact original extension dates, eligibility, and rule; no selection by outcome.
    for t in mondays(COMMON_START,end):
        if t+8*WEEK>=end:
            break
        x=window(prices,t,t+8*WEEK+DAY)
        if x is None:
            continue
        rr={m:simulate(prices,mapped[m],t,"risk") for m in MODELS}
        if any(v is None for v in rr.values()):
            continue
        dates.append(t)
        opens.append(x[:56:7,0])
        closes.append(np.r_[x[:56,3],x[56,0]])
        for m,r in rr.items():
            schedules[m].append(r["allocations"])
    contiguous(dates)
    if len(dates)<=2*MIN_SHIFT:
        raise ValueError("Insufficient contiguous episodes")
    return dates,np.array(opens),np.array(closes),{m:np.array(v) for m,v in schedules.items()}


def evaluate(opens,closes,units,fee=.001):
    """Same original close-based valuation and terminal open, vectorized."""
    u=np.asarray(units,dtype=float)
    if opens.shape!=u.shape or u.ndim!=2 or u.shape[1]!=8 or closes.shape!=(len(u),57):
        raise ValueError("Wrong purchase matrix")
    if np.any(u<0) or not np.allclose(u.sum(axis=1),8) or np.any(opens<=0) or np.any(closes<=0):
        raise ValueError("Invalid purchase matrix")
    qty=u/8*(1-fee)/opens
    cum=np.cumsum(qty,axis=1)
    cash=1-np.cumsum(u,axis=1)/8
    indices=np.minimum(np.arange(57)//7,7)
    v=cash[:,indices]+cum[:,indices]*closes
    v=np.column_stack([np.ones(len(u)),v])
    dd=np.min(v/np.maximum.accumulate(v,axis=1)-1,axis=1)
    return cum[:,-1],dd,u@np.arange(8)*7/8


def rotations(n):
    # All fixed non-nearby circular offsets; wrap is descriptive only.
    if n<=2*MIN_SHIFT:
        raise ValueError("Insufficient rotation history")
    return range(MIN_SHIFT,n-MIN_SHIFT+1)


def model_control(dates,opens,closes,units):
    contiguous(dates)
    n=len(dates)
    actual,dd,wait=evaluate(opens,closes,units)
    dca,dca_dd,_=evaluate(opens,closes,np.ones_like(units))
    observed=np.log(actual/dca)*100
    means=[];dd_means=[];placebo_log=np.zeros(n);placebo_dd=np.zeros(n)
    for offset in rotations(n):
        q,draw,waiting=evaluate(opens,closes,np.roll(units,offset,axis=0))
        if not np.isclose(waiting.mean(),wait.mean()):
            raise ValueError("Rotation changed cash waiting exposure")
        gain=np.log(q/dca)*100
        means.append(float(gain.mean()))
        dd_means.append(float(draw.mean()*100))
        placebo_log+=gain
        placebo_dd+=draw
    placebo_log/=len(means)
    placebo_dd/=len(means)
    delta=observed-placebo_log
    return {"n":n,"rotation_count":len(means),
            "actual_geometric_gain_vs_dca_pct":float(np.expm1(observed.mean()/100)*100),
            "mean_placebo_log_gain_vs_dca_pct":float(placebo_log.mean()),
            "actual_minus_mean_placebo_log_gain_pct":float(delta.mean()),
            "conditional_interval90_log_delta":interval(delta,dates),
            "rotation_mean_log_gain_quantiles":list(map(float,np.quantile(means,[.05,.5,.95]))),
            "fraction_rotations_below_actual":float(np.mean(np.array(means)<observed.mean())),
            "actual_mean_drawdown_pct":float(dd.mean()*100),
            "mean_placebo_drawdown_pct":float(placebo_dd.mean()*100),
            "dca_mean_drawdown_pct":float(dca_dd.mean()*100),
            "actual_minus_placebo_drawdown_pp":float((dd-placebo_dd).mean()*100),
            "rotation_mean_drawdown_quantiles_pct":list(map(float,np.quantile(dd_means,[.05,.5,.95]))),
            "mean_waiting_days_actual_and_all_rotations":float(wait.mean()),
            "zero_purchase_slots_fraction_excluding_forced_last":float(np.mean(units[:,:7]==0))}


def direct(dates,opens,closes,schedules):
    values={m:evaluate(opens,closes,schedules[m]) for m in MODELS}
    out={}
    for a,b in (("M2","L1"),("M1","L1")):
        qa,da,wa=values[a];qb,db,wb=values[b]
        delta=np.log(qa/qb)*100
        out[a+"_minus_"+b]={"mean_log_gain_pct":float(delta.mean()),
                           "conditional_interval90":interval(delta,dates),
                           "mean_drawdown_delta_pp":float((da-db).mean()*100),
                           "mean_waiting_delta_days":float((wa-wb).mean())}
    return out


def triggers(signals,dates):
    used=sorted({t+i*WEEK for t in dates for i in range(8)})
    return {m:{"n_unique_weeks":len(used),
               "above_threshold_fraction":float(np.mean([
                   signals[t]["pred"][m]["p_loss_15"]>signals[t]["thresholds"][m]
                   for t in used]))} for m in MODELS}


def analyze(prices,market,end=DEV_END):
    if end>DEV_END:
        raise ValueError("Final data are not permitted")
    sig,pred=replay(prices,FIRST[market],end)
    if any(r["pred"]["M0"]["p_up"]!=r["pred"]["M1"]["p_up"] for r in pred):
        raise ValueError("M0/M1 direction identity unexpectedly broken")
    dates,opens,closes,schedules=collect(prices,sig,end)
    return {"first":dates[0].isoformat(),"last":dates[-1].isoformat(),
            "forecast_n":len(pred),"purchase_n":len(dates),
            "m1_direction_identical_to_m0":True,"trigger_rates":triggers(sig,dates),
            "controls":{m:model_control(dates,opens,closes,schedules[m]) for m in MODELS},
            "direct_comparisons":direct(dates,opens,closes,schedules)}


def run(root=ROOT):
    root=Path(root)
    prior=root/"buy_risk_extension_report.json"
    old=json.loads(prior.read_bytes())
    if old["protocol"]!="BUY-001-risk-extension-development-v1" or old["input_hashes"]!=HASHES or old["test_numeric_values_parsed"] is not False:
        raise ValueError("Unexpected original extension report")
    results={}
    for m in HASHES:
        print("Audit controls:",m,flush=True)
        r=analyze(load_development(root,m),m)
        # Preserve exact prior matched sample and arithmetic.
        previous=old["markets"][m]
        if r["purchase_n"]!=previous["purchase_n"] or r["forecast_n"]!=previous["forecast_n"]:
            raise ValueError("Audit changed the evaluation sample")
        for model in MODELS:
            if not np.isclose(r["controls"][model]["actual_geometric_gain_vs_dca_pct"],
                              previous["cash0"][model]["geometric_gain_vs_dca_pct"],atol=1e-9,rtol=0):
                raise ValueError("Audit changed the original purchase result")
        results[m]=r
    report={"protocol":VERSION,"test_numeric_values_parsed":False,"input_hashes":HASHES,
            "extension_sha256":digest(prior.read_bytes()),"markets":results,
            "primary_block_weeks":52,
            "limitations":["Rotated allocation schedules are retrospective placebo, not tradable forecasts.",
               "Every rotation preserves the full distribution of purchase schedules and waiting days, not market-conditioned exposure.",
               "Circular shifts do not establish exchangeability; rank is descriptive, not a p-value.",
               "Conditional block intervals ignore some rotation/estimation uncertainty; nominal coverage not established.",
               "Model comparisons have unequal delay rates and overlapping market episodes.",
               "No new model, fit or tuning; M1 direction is a duplicate of M0."]}
    target=root/"buy_audit_controls_report.json"
    if target.exists():
        if json.loads(target.read_bytes())!=report:
            raise ValueError("Existing audit report differs; retain prior version")
    else:
        json_write(target,report)
    print("Send",target,flush=True)


if __name__=="__main__":
    run()
