"""OI-GATE-001: predeclared synthetic design diagnostic, no real market data."""
import math
from functools import lru_cache
from pathlib import Path
import numpy as np

from binance_minute import json_write
from research_gate import batch_logistic,wilson

ROOT=Path(__file__).resolve().parent/"data"/"research"/"oi_gate_v1"
VERSION="OI-GATE-001-synthetic-v1"
REPS=256
SIZES=(86,156,260)
WARM=136
FIRST=26
TRAIN=104
MIN_TRAIN=52
H=4
REGIME_FLIP=.06
SIGNAL_FLIP=.20
BARRIER=math.log(.85)
ILLUSTRATIVE_GAIN=.01
SEEDS={"calibration_null":2026112901,"validation_null":2026112902,
       "planted":2026112903,"strong":2026112904}
EFFECTS={"calibration_null":0.,"validation_null":0.,"planted":.16,"strong":.22}
# Three stylized weekly paths, with fixed daily lows and flat Sat/Sun closes.
TOTAL=np.log([.86,.99,1.10])
PATHS=TOTAL[:,None]*np.array([[.10,.25,.40,-.10,.35,0.,0.],
                              [.50,-1.,1.50,-.50,.50,0.,0.],
                              [.30,-.15,.45,.10,.30,0.,0.]])
WICK=.005
MINIMUM=np.min(np.cumsum(PATHS,axis=1)-np.maximum(PATHS,0)-WICK,axis=1)


def probs(regime,signal,effect):
    d=.28+.22*regime+effect*signal
    return np.stack([d,np.full_like(d,.18,dtype=float),.82-d],axis=-1)


@lru_cache(maxsize=None)
def oracle(regime,signal,effect,counts=(0,0,0)):
    """Exact crossing probability conditional on known state and surviving path."""
    if sum(counts)==H:
        return 0.
    start=float(np.dot(counts,TOTAL))
    answer=0.
    for k,p in enumerate(probs(regime,signal,effect)):
        if start+MINIMUM[k]<=BARRIER:
            answer+=p
            continue
        new=list(counts);new[k]+=1;new=tuple(new)
        if sum(new)==H:
            continue
        for r,pr in ((regime,1-REGIME_FLIP),(1-regime,REGIME_FLIP)):
            for x,px in ((signal,1-SIGNAL_FLIP),(-signal,SIGNAL_FLIP)):
                answer+=p*pr*px*oracle(r,x,effect,new)
    return float(answer)


def price_features(closes,t):
    """Exact synthetic counterparts of legacy four price features plus 7d return."""
    end=t*7-1 # exclusive: Sunday not known
    if end<180:
        raise ValueError("Insufficient price history")
    c=closes[:,end-180:end]
    last=c[:,-1]
    returns=np.diff(c[:,-61:],axis=1)
    w=.94**np.arange(59,-1,-1)
    sigma=np.maximum(1e-6,np.sqrt(np.average(returns**2,axis=1,weights=w)))
    return np.column_stack([np.log(sigma),
        -np.log(np.exp(c[:,-50:]-last[:,None]).mean(axis=1)),
        last-c.max(axis=1),last-c[:,-29],last-c[:,-8]])


def world(seed,effect,reps=REPS,n=WARM+max(SIZES)+H):
    if n<=FIRST+H or reps<1 or not 0<=effect<=.22:
        raise ValueError("Invalid synthetic design")
    rng=np.random.default_rng(seed)
    r=np.zeros((reps,n),dtype=int);x=np.zeros_like(r);k=np.zeros_like(r)
    r[:,0]=rng.integers(0,2,reps);x[:,0]=2*rng.integers(0,2,reps)-1
    prior=np.full(reps,.5);base=np.empty((reps,n));full=np.empty_like(base)
    lookup=np.array([[oracle(j,s,effect) for s in (-1,1)] for j in (0,1)])
    for t in range(n):
        base[:,t]=(1-prior)*lookup[r[:,t],0]+prior*lookup[r[:,t],1]
        full[:,t]=lookup[r[:,t],(x[:,t]+1)//2]
        p=probs(r[:,t],x[:,t],effect)
        u=rng.random(reps)
        k[:,t]=(u>=p[:,0]).astype(int)+(u>=p[:,0]+p[:,1]).astype(int)
        # Price+regime oracle filters signal using past observed price categories.
        pp=probs(r[:,t],1,effect)[np.arange(reps),k[:,t]]
        pm=probs(r[:,t],-1,effect)[np.arange(reps),k[:,t]]
        post=prior*pp/(prior*pp+(1-prior)*pm)
        prior=SIGNAL_FLIP+(1-2*SIGNAL_FLIP)*post
        if t+1<n:
            r[:,t+1]=np.where(rng.random(reps)<REGIME_FLIP,1-r[:,t],r[:,t])
            x[:,t+1]=np.where(rng.random(reps)<SIGNAL_FLIP,-x[:,t],x[:,t])
    ret=PATHS[k].reshape(reps,n*7)
    closes=np.cumsum(ret,axis=1)
    opens=np.concatenate([np.zeros((reps,1)),closes],axis=1)
    lows=np.minimum(opens[:,:-1],closes)-WICK
    X=np.zeros((reps,n,6))
    worst=np.zeros((reps,n-H+1))
    for t in range(FIRST,n):
        f=price_features(closes,t)
        # Feature-level proxy: persistent incremental signal + past Friday price move.
        # Sat/Sun returns are zero, so last 7-day move is known by Friday close.
        X[:,t,:5]=f
        X[:,t,5]=x[:,t]+.8*f[:,4]/.12
    for t in range(n-H+1):
        a=t*7;b=a+28
        worst[:,t]=np.minimum(0,np.minimum(lows[:,a:b].min(axis=1),opens[:,b])-opens[:,a])
    return {"features":X,"worst":worst,"labels":(worst<=BARRIER).astype(float),
            "base_oracle":base,"full_oracle":full}


def mature_bounds(t):
    # Same calendar maturity as BUY: endpoint day closed by Sunday 00 UTC.
    # t_old+29d <= t-1d, therefore at weekly origins t_old <= t-5 weeks.
    stop=t-4
    return max(FIRST,stop-TRAIN),stop


def preflight(w,n=max(SIZES)):
    sl=slice(WARM,WARM+n)
    d=(w["base_oracle"][:,sl]-w["full_oracle"][:,sl])**2
    return {"oracle_expected_gain":float(d.mean()),
            "oracle_gain_by_size":{str(k):float(d[:,:k].mean()) for k in SIZES if k<=n},
            "event_frequency":float(w["labels"][:,sl].mean())}


def replay(w,warm=WARM,n=max(SIZES)):
    X=w["features"];y=w["labels"];worst=w["worst"]
    out={k:[] for k in ("gain","baseline_loss","challenger_loss","frequency_loss",
                        "scaled_loss","oracle_gain","oracle_expected")}
    for t in range(warm,warm+n):
        a,b=mature_bounds(t)
        if b-a<MIN_TRAIN:
            raise ValueError("Insufficient matured history")
        hist=X[:,a:b];actual=y[:,a:b]
        p=batch_logistic(hist[:,:,:5],actual,X[:,t,:5])
        q=batch_logistic(hist,actual,X[:,t,:])
        yy=y[:,t]
        freq=(1+y[:,FIRST:b].sum(axis=1))/(b-FIRST+2)
        scale=np.exp(X[:,t,0,None]-X[:,FIRST:b,0])
        scaled=(1+(worst[:,FIRST:b]*scale<=BARRIER).sum(axis=1))/(b-FIRST+2)
        bl=(p-yy)**2;cl=(q-yy)**2
        po=w["base_oracle"][:,t];qo=w["full_oracle"][:,t]
        for k,v in (("gain",bl-cl),("baseline_loss",bl),("challenger_loss",cl),
                    ("frequency_loss",(freq-yy)**2),("scaled_loss",(scaled-yy)**2),
                    ("oracle_gain",(po-yy)**2-(qo-yy)**2),("oracle_expected",(po-qo)**2)):
            out[k].append(v)
    return {k:np.stack(v,axis=1) for k,v in out.items()}


def evaluate(samples,sizes=SIZES):
    result={}
    for n in sizes:
        null=samples["calibration_null"]["gain"][:,:n].mean(axis=1)
        # Detection threshold deliberately separate from illustrative .01 gain.
        threshold=max(0.,float(np.quantile(null,.95)))
        scenarios={}
        for name,s in samples.items():
            if name=="calibration_null":
                continue
            a=s["gain"][:,:n].mean(axis=1)
            k=int(np.sum(a>threshold))
            row={"effect":EFFECTS[name],"histories":len(a),"detected":k,
                 "detection_fraction":k/len(a),"wilson95":wilson(k,len(a)),
                 "mean_brier_gain":float(a.mean()),
                 "fraction_gain_ge_illustrative":float(np.mean(a>=ILLUSTRATIVE_GAIN)),
                 "gain_quantiles_05_50_95":np.quantile(a,[.05,.5,.95]).tolist(),
                 "per_history_gain":a.tolist()}
            row.update({key:float(s[key][:,:n].mean()) for key in
                        ("baseline_loss","challenger_loss","frequency_loss","scaled_loss",
                         "oracle_gain","oracle_expected")})
            row["baseline_reference_check"]=bool(row["baseline_loss"]<=min(row["frequency_loss"],row["scaled_loss"]))
            scenarios[name]=row
        f=scenarios["validation_null"];p=scenarios["planted"]
        oracle_valid=p["oracle_expected"]>=ILLUSTRATIVE_GAIN
        reference_ok=f["baseline_reference_check"] and p["baseline_reference_check"]
        detection_ok=f["wilson95"][1]<=.10 and p["wilson95"][0]>=.80
        result[str(n)]={"threshold":threshold,"calibration_null_gain":null.tolist(),
                        "scenarios":scenarios,"oracle_size_check":bool(oracle_valid),
                        "baseline_reference_check":bool(reference_ok),
                        "detection_check":bool(detection_ok),
                        "mean_gain_check":bool(p["mean_brier_gain"]>=ILLUSTRATIVE_GAIN),
                        "synthetic_diagnostic_pass":bool(oracle_valid and reference_ok and detection_ok
                                                         and p["mean_brier_gain"]>=ILLUSTRATIVE_GAIN)}
    return result


def run(root=ROOT):
    root=Path(root);target=root/"oi_gate_report.json"
    if target.exists():
        raise ValueError("Report already exists; preserve original")
    worlds={};checks={}
    for name,seed in SEEDS.items():
        worlds[name]=world(seed,EFFECTS[name])
        checks[name]=preflight(worlds[name])
        print("Oracle preflight:",name,checks[name],flush=True)
    # Effects are fixed, never adjusted to pass. Save prefit checks separately.
    root.mkdir(parents=True,exist_ok=True)
    pre=root/"oracle_preflight.json"
    if pre.exists():
        raise ValueError("Preflight already exists; preserve original and inspect before retry")
    with pre.open("x",encoding="utf-8") as f:
        import json
        json.dump({"version":VERSION,"seeds":SEEDS,"effects":EFFECTS,"checks":checks},f,indent=2)
    samples={}
    for name,w in worlds.items():
        print("Fitting fixed synthetic world:",name,flush=True)
        samples[name]=replay(w)
    report={"protocol":VERSION,"market_data_used":False,"confirmation_authorized":False,
            "seeds":SEEDS,"effects":EFFECTS,"replications":REPS,"sizes":list(SIZES),
            "illustrative_gain_not_owner_utility":ILLUSTRATIVE_GAIN,
            "primary_size":86,"preflight":checks,"results":evaluate(samples),
            "limitations":["Stylized three-pattern daily paths with fixed wick and flat weekends, not realistic BTC generator.",
                "OI is a price-correlated feature-level proxy, not reconstructed raw 14-Friday quantities.",
                "Oracle conditions on synthetic regime and full category history; not a real observable price model.",
                "Oracle gain describes its conditional information set, not a universal upper bound on fitted-model gain.",
                "One family of synthetic worlds, fixed positive effect sizes; actual oracle gain may exceed .01 substantially.",
                "Nested sample sizes are descriptive planning scenarios, not independent confirmations.",
                "No personal utility, live data, real-data power estimate or authorization of market confirmation."]}
    json_write(target,report)
    print("Send:",target,flush=True)
    return report


if __name__=="__main__":
    run()
