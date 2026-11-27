"""GATE-001: synthetic risk-detection diagnostic; no market data."""
import math
from functools import lru_cache
from pathlib import Path
import numpy as np

from binance_minute import json_write
from research_buy_risk import LAMBDA

ROOT=Path(__file__).resolve().parent/"data"/"research"/"gate_v1"
VERSION="GATE-001-synthetic-v1"
REPS=128
SIZES=(86,150)
TRAIN=104
MIN_TRAIN=52
WARM=110
H=4
REGIME_FLIP=.04
SIGNAL_FLIP=.15
DOWN=math.log(.88)
UP=math.log(1.08)
BARRIER=math.log(.85)
MIN_GAIN=.01
SEEDS={"calibration_null":2026112801,"validation_null":2026112802,
       "moderate":2026112803,"strong":2026112804}
EFFECTS={"calibration_null":0.,"validation_null":0.,"moderate":.10,"strong":.20}


def down_probability(regime,signal,effect):
    return .25+.30*regime+effect*signal


@lru_cache(maxsize=None)
def oracle(regime,signal,effect,steps=H,losses=0,total_steps=0):
    """Exact risk under the specified weekly process. State includes current
    cumulative return until the barrier is crossed, not future realized states."""
    if losses*DOWN+(total_steps-losses)*UP<=BARRIER:
        return 1.
    if steps==0:
        return 0.
    p=down_probability(regime,signal,effect)
    answer=0.
    for down,prob in ((1,p),(0,1-p)):
        for r,pr in ((regime,1-REGIME_FLIP),(1-regime,REGIME_FLIP)):
            for x,px in ((signal,1-SIGNAL_FLIP),(-signal,SIGNAL_FLIP)):
                answer+=prob*pr*px*oracle(r,x,effect,steps-1,losses+down,total_steps+1)
    return answer


def world(seed,effect,reps=REPS,n=WARM+max(SIZES)+H):
    rng=np.random.default_rng(seed)
    r=np.zeros((reps,n),dtype=int);x=np.zeros_like(r);down=np.zeros_like(r)
    r[:,0]=rng.integers(0,2,reps);x[:,0]=2*rng.integers(0,2,reps)-1
    prior=np.full(reps,.5);base=np.empty((reps,n));full=np.empty_like(base)
    lookup=np.array([[oracle(j,k,effect) for k in (-1,1)] for j in (0,1)])
    for t in range(n):
        base[:,t]=(1-prior)*lookup[r[:,t],0]+prior*lookup[r[:,t],1]
        full[:,t]=lookup[r[:,t],(x[:,t]+1)//2]
        down[:,t]=(rng.random(reps)<down_probability(r[:,t],x[:,t],effect))
        # Filter latent signal using only observed previous weekly returns and
        # the current synthetic regime. The comparator does not observe x.
        pp=down_probability(r[:,t],1,effect);pm=down_probability(r[:,t],-1,effect)
        lp=np.where(down[:,t],pp,1-pp);lm=np.where(down[:,t],pm,1-pm)
        post=prior*lp/(prior*lp+(1-prior)*lm)
        prior=SIGNAL_FLIP+(1-2*SIGNAL_FLIP)*post
        if t+1<n:
            r[:,t+1]=np.where(rng.random(reps)<REGIME_FLIP,1-r[:,t],r[:,t])
            x[:,t+1]=np.where(rng.random(reps)<SIGNAL_FLIP,-x[:,t],x[:,t])
    ret=np.where(down,DOWN,UP)
    y=np.zeros((reps,n-H+1),dtype=float)
    for t in range(n-H+1):
        y[:,t]=(np.min(np.cumsum(ret[:,t:t+H],axis=1),axis=1)<=BARRIER)
    past=np.zeros_like(ret)
    for t in range(4,n):
        past[:,t]=ret[:,t-4:t].sum(axis=1)
    X=np.stack([r,past,x],axis=2).astype(float)
    return X,y,base,full


def batch_logistic(x,y,current):
    """Same fixed standardized ridge objective/gradient steps as BUY logistic.
    Independent simulated histories batched numerically, not parallel agents."""
    mean=x.mean(axis=1,keepdims=True);sd=x.std(axis=1,keepdims=True)
    sd=np.where(sd>1e-10,sd,1.)
    z=(x-mean)/sd
    a=np.concatenate([np.ones((*z.shape[:2],1)),z],axis=2)
    n=y.shape[1];at=np.swapaxes(a,1,2)
    gram=at@a
    step=1/(.25*np.linalg.eigvalsh(gram)[:,-1]/n+LAMBDA)
    reg=np.array([.001]+[LAMBDA]*x.shape[2])
    b=np.zeros((len(x),a.shape[2]))
    for _ in range(300):
        p=1/(1+np.exp(-np.clip((a@b[:,:,None])[:,:,0],-35,35)))
        grad=(at@(p-y)[:,:,None])[:,:,0]/n+reg*b
        b-=step[:,None]*grad
    cur=np.concatenate([np.ones((len(x),1)),(current-mean[:,0,:])/sd[:,0,:]],axis=1)
    q=np.sum(cur*b,axis=1)
    return 1/(1+np.exp(-np.clip(q,-20,20)))


def replay(X,y,base,full,warm=WARM,n=max(SIZES)):
    gains=[];oracle_gains=[];oracle_expected=[];baseline_losses=[];challenger_losses=[]
    for t in range(warm,warm+n):
        # t-H is the latest origin whose 4-week outcome ended before
        # decision t. No label containing week t or later can enter training.
        stop=t-H+1;start=max(4,stop-TRAIN)
        if stop-start<MIN_TRAIN:
            raise ValueError("Insufficient synthetic history")
        hist=X[:,start:stop,:];actual=y[:,start:stop]
        p=batch_logistic(hist[:,:,:2],actual,X[:,t,:2])
        q=batch_logistic(hist,actual,X[:,t,:])
        yy=y[:,t];bl=(p-yy)**2;cl=(q-yy)**2
        gains.append(bl-cl);baseline_losses.append(bl);challenger_losses.append(cl)
        oracle_gains.append((base[:,t]-yy)**2-(full[:,t]-yy)**2)
        oracle_expected.append((base[:,t]-full[:,t])**2)
    return {k:np.stack(v,axis=1) for k,v in (
        ("gain",gains),("oracle_gain",oracle_gains),("oracle_expected",oracle_expected),
        ("baseline_loss",baseline_losses),("challenger_loss",challenger_losses))}


def wilson(k,n):
    z=1.96;p=k/n;den=1+z*z/n
    center=(p+z*z/(2*n))/den
    half=z*math.sqrt(p*(1-p)/n+z*z/(4*n*n))/den
    return [max(0.,center-half),min(1.,center+half)]


def evaluate(samples,sizes=SIZES):
    results={}
    for n in sizes:
        null=samples["calibration_null"]["gain"][:,:n].mean(axis=1)
        threshold=max(MIN_GAIN,float(np.quantile(null,.90)))
        scenarios={}
        for name,s in samples.items():
            if name=="calibration_null":
                continue
            a=s["gain"][:,:n].mean(axis=1);k=int(np.sum(a>=threshold))
            scenarios[name]={"effect":EFFECTS[name],"n_histories":len(a),
                "mean_brier_gain":float(a.mean()),
                "gain_quantiles_05_50_95":list(map(float,np.quantile(a,[.05,.5,.95]))),
                "mean_baseline_brier":float(s["baseline_loss"][:,:n].mean()),
                "mean_challenger_brier":float(s["challenger_loss"][:,:n].mean()),
                "oracle_realized_gain":float(s["oracle_gain"][:,:n].mean()),
                "oracle_expected_gain":float(s["oracle_expected"][:,:n].mean()),
                "detected":k,"detection_fraction":k/len(a),"wilson95":wilson(k,len(a)),
                "per_history_gain":a.tolist()}
        f=scenarios["validation_null"];p=scenarios["moderate"]
        # A moderate planted effect must actually be big enough in the
        # oracle, otherwise this is the wrong positive-control world.
        meaningful=p["oracle_expected_gain"]>=MIN_GAIN
        results[str(n)]={"threshold":threshold,"calibration_null_gain":null.tolist(),
            "scenarios":scenarios,"moderate_oracle_meets_minimum":bool(meaningful),
            "point_diagnostic_pass":bool(meaningful and f["detection_fraction"]<=.10
                                         and p["detection_fraction"]>=.80),
            "uncertainty_qualified_pass":bool(meaningful and f["wilson95"][1]<=.10
                                             and p["wilson95"][0]>=.80)}
    return results


def run(root=ROOT):
    target=Path(root)/"synthetic_gate_report.json"
    if target.exists():
        raise ValueError("Report already exists; preserve original")
    samples={}
    for name,seed in SEEDS.items():
        print("Synthetic world:",name,flush=True)
        samples[name]=replay(*world(seed,EFFECTS[name]))
    report={"protocol":VERSION,"seeds":SEEDS,"replications":REPS,
            "minimum_absolute_brier_gain":MIN_GAIN,"sizes":list(SIZES),
            "results":evaluate(samples),"market_data_used":False,
            "limitations":["Stylized weekly paths; no intraday lows, actual BTC features, or execution.",
                "Observed synthetic regime is not an available perfect real market regime label.",
                "Same legacy ridge objective, not yet the actual OI confirmation estimator.",
                "Diagnostic threshold calibrated on independent synthetic null only; not market p-value.",
                "No decision-utility gate, no confirmed real-market power, no permission to open new outcomes.",
                "Nested 86/150 origin samples share histories; not independent tests."]}
    json_write(target,report)
    print("Send",target,flush=True)
    return report


if __name__=="__main__":
    run()
