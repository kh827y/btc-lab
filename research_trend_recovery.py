"""TREND-001: descriptive episode-level cost of waiting for MA confirmation."""
import math
from datetime import date
from pathlib import Path
from statistics import median

from research_buy import ROOT as PRICE_ROOT,HASHES,FIRST,DEV_END,DAY,days,window,load_development
from research_drawdown import peak_history
from forecast_journal import new_file

ROOT=Path(__file__).resolve().parent/"data"/"research"/"trend_recovery_v1"
VERSION="TREND-001-descriptive-v1"
PEAK_START=max(FIRST.values())
THRESHOLD=.20
H=90
FEE=.001
RULES=("immediate","ma50","ma200")


def valid(prices,d):
    r=prices.get(d)
    return r is not None and r[4]>0


def choose(prices,trigger,terminal,n):
    """First known close above MA, next-day open; no purchase at terminal."""
    for d in days(trigger,terminal-DAY):
        if not valid(prices,d):
            return {"status":"censored","reason":"missing_signal_day","date":d.isoformat()}
        if n is not None:
            a=window(prices,d-(n-1)*DAY,d+DAY)
            if a is None:
                return {"status":"censored","reason":"missing_ma_history","date":d.isoformat()}
            if not a[-1,3]>a[:,3].mean():
                continue
        entry=d+DAY
        if not valid(prices,entry):
            return {"status":"censored","reason":"missing_entry_day","date":entry.isoformat()}
        return {"status":"bought","signal_date":d.isoformat(),"entry_date":entry.isoformat(),
                "already_above_at_trigger":bool(n is not None and d==trigger),
                "entry_open":float(prices[entry][0]),"wait_days":(d-trigger).days}
    return {"status":"cash_no_signal","wait_days":None}


def evaluate_rule(prices,trigger,episode_start,terminal,end,n):
    rule=choose(prices,trigger,terminal,n)
    if rule["status"]=="censored":
        return rule
    if rule["status"]=="cash_no_signal":
        rule.update({"terminal_wealth":1.,"worst_from_initial":0.,"btc_per_usd":0.})
        return rule
    entry=date.fromisoformat(rule["entry_date"])
    prior=window(prices,episode_start,entry)
    if prior is None:
        raise ValueError("Incomplete known episode before signal")
    known_low=float(prior[:,2].min())
    op=rule["entry_open"]
    rule["known_low_before_entry"]=known_low
    rule["premium_to_known_low_pct"]=100*(op/known_low-1)
    q=(1-FEE)/op
    rule["btc_per_usd"]=q
    a=window(prices,entry,terminal+DAY)
    if a is None:
        raise ValueError("Incomplete common terminal window")
    rule["terminal_wealth"]=float(q*a[-1,0])
    rule["worst_from_initial"]=float(min(0.,q*min(a[:-1,2].min(),a[-1,0])-1))
    # Separate follow-up clock: 90 days after actual purchase, not trigger.
    # If an observed new low occurs before censoring it remains a known event.
    follow=entry+H*DAY
    event=None;observed=0;low=op
    for d in days(entry,min(follow,end)):
        if not valid(prices,d):
            break
        low=min(low,float(prices[d][2]))
        if low<known_low and event is None:
            event=d.isoformat()
        observed+=1
    complete=observed==H and follow<end and valid(prices,follow)
    if complete:
        low=min(low,float(prices[follow][0]))
        if low<known_low and event is None:
            event=follow.isoformat()
    rule["post_entry_90"]={"complete":complete,"days_observed":observed,
        "new_low":True if event is not None else (False if complete else None),
        "first_new_low_date":event,
        "worst_from_entry_pct":100*(low/op-1) if complete else None}
    return rule


def analyze(prices,first=PEAK_START,end=DEV_END):
    if not first<end<=DEV_END or any(d>=end for d in prices):
        raise ValueError("Only development-period prices allowed")
    states,episodes=peak_history(prices,first,end)
    triggers={}
    for d,s in states.items():
        ep=s["episode"]
        if ep is not None and ep not in triggers and s["depth"]>=THRESHOLD-1e-12:
            triggers[ep]=d
    rows=[]
    for ep in episodes:
        trigger=triggers.get(ep["id"])
        if trigger is None:
            continue
        entry=trigger+DAY
        terminal=entry+H*DAY
        row={"episode_id":ep["id"],"peak_date":ep["peak_date"],
             "peak_close":ep["peak_close"],"trigger_date":trigger.isoformat(),
             "trigger_close":float(prices[trigger][3]),
             "trigger_depth":states[trigger]["depth"],"terminal_date":terminal.isoformat(),
             "episode_status":ep["status"],"status":"eligible","rules":{}}
        # The peak must be observed after common start, with no unresolved gaps.
        # The sample is determined at threshold crossing, not by eventual trough depth.
        if ep["left_truncated_or_gap"] or states[trigger]["gap_uncertainty"]:
            row.update({"status":"excluded","reason":"uncertain_peak"})
        elif trigger-(200-1)*DAY<first or window(prices,trigger-199*DAY,trigger+DAY) is None:
            row.update({"status":"excluded","reason":"insufficient_common_ma_history"})
        elif terminal>=end or window(prices,entry,terminal+DAY) is None:
            row.update({"status":"censored","reason":"incomplete_common_90d_window"})
        else:
            for name,n in zip(RULES,(None,50,200)):
                row["rules"][name]=evaluate_rule(prices,trigger,date.fromisoformat(ep["start_date"]),
                                                  terminal,end,n)
            base=row["rules"]["immediate"]
            if base["status"]!="bought":
                raise ValueError("Invalid immediate comparison")
            for a in row["rules"].values():
                if a["status"]=="censored":
                    continue
                a["terminal_wealth_delta_pct"]=100*(a["terminal_wealth"]-base["terminal_wealth"])
                a["btc_delta_pct"]=100*(a["btc_per_usd"]/base["btc_per_usd"]-1)
                a["entry_vs_immediate_pct"]=(100*(a["entry_open"]/base["entry_open"]-1)
                                              if a["status"]=="bought" else None)
        rows.append(row)
    return {"episodes":rows,"summary":summarize(rows)}


def med(values):
    return float(median(values)) if values else None


def summarize(rows):
    eligible=[r for r in rows if r["status"]=="eligible"]
    # All three policies compared on identical complete, uncensored episodes.
    common=[r for r in eligible if all(r["rules"][k]["status"]!="censored" for k in RULES)]
    out={"threshold_episodes":len(rows),"eligible_episodes":len(eligible),
         "excluded_or_censored":len(rows)-len(eligible),"common_policy_episodes":len(common),
         "rules":{}}
    for k in RULES:
        a=[r["rules"][k] for r in common];b=[x for x in a if x["status"]=="bought"]
        follow=[x["post_entry_90"] for x in b]
        known=[x for x in follow if x["new_low"] is not None]
        complete=[x for x in follow if x["complete"]]
        out["rules"][k]={"n":len(a),"bought":len(b),"cash_no_signal":len(a)-len(b),
            "already_above_at_trigger":sum(x["already_above_at_trigger"] for x in b),
            "median_wait_days":med([x["wait_days"] for x in b]),
            "median_entry_vs_immediate_pct":med([x["entry_vs_immediate_pct"] for x in b]),
            "median_premium_to_known_low_pct":med([x["premium_to_known_low_pct"] for x in b]),
            "median_terminal_return_pct":med([100*(x["terminal_wealth"]-1) for x in a]),
            "median_worst_from_initial_pct":med([100*x["worst_from_initial"] for x in a]),
            "median_terminal_wealth_delta_pct":med([x["terminal_wealth_delta_pct"] for x in a]),
            "median_btc_delta_pct":med([x["btc_delta_pct"] for x in a]),
            "outperformed_immediate":sum(x["terminal_wealth_delta_pct"]>1e-10 for x in a),
            "underperformed_immediate":sum(x["terminal_wealth_delta_pct"]< -1e-10 for x in a),
            "post_entry_complete":len(complete),
            "post_entry_known_new_low":sum(x["new_low"] is True for x in known),
            "post_entry_unknown_new_low":len(follow)-len(known),
            "post_entry_new_low_complete":sum(x["new_low"] is True for x in complete),
            "median_post_entry_worst_pct":med([x["worst_from_entry_pct"] for x in complete])}
    return out


def run(root=ROOT,price_root=PRICE_ROOT):
    root=Path(root);target=root/"trend_recovery_report.json"
    if target.exists():
        raise ValueError("Report already exists; preserve original")
    markets={}
    for m in HASHES:
        markets[m]=analyze(load_development(Path(price_root),m))
        print(m,markets[m]["summary"],flush=True)
    a={r["trigger_date"] for r in markets["bitstamp"]["episodes"]}
    b={r["trigger_date"] for r in markets["coinbase"]["episodes"]}
    report={"protocol":VERSION,"kind":"descriptive_episode_comparison",
            "confirmation_authorized":False,"test_numeric_values_parsed":False,
            "price_hashes":HASHES,"peak_start":PEAK_START.isoformat(),
            "end_exclusive":DEV_END.isoformat(),"threshold":THRESHOLD,
            "common_horizon_days":H,"fee":FEE,"markets":markets,
            "cross_check":{"exact_common_trigger_dates":sorted(a&b),
                           "bitstamp_only_trigger_dates":sorted(a-b),
                           "coinbase_only_trigger_dates":sorted(b-a)},
            "limitations":["One first 20% closing drawdown trigger per observed peak-to-recovery episode; not all local swings.",
                "MA50/200 close above level, not crossover or confirmed trend; may already be above on trigger day.",
                "Daily signals, next UTC open proxy, no slippage, 0.1% entry fee, cash yield zero, no taxes or existing portfolio.",
                "Equal budget and common terminal 90 days after immediate entry; no signal means cash, not omitted.",
                "Known-low premium uses only lows through signal close, not hindsight episode bottom.",
                "Separate post-entry 90d new-low metric is relative to pre-entry episode low; censored non-events unknown.",
                "Common complete policy sample and exclusions reported; episodes and exchanges not independent cycles.",
                "No optimal threshold, fitted model, forward prediction or 2024+ outcomes."]}
    root.mkdir(parents=True,exist_ok=True)
    new_file(target,report)
    print("Send:",target,flush=True)
    return report


if __name__=="__main__":
    run()
