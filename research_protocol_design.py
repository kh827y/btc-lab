"""One bounded protocol-design task. No outcome data, execution or registration."""
import argparse
import json

from research_controller import Budget,STAGES,checked_text,require,ControllerError,encode
from research_credentials import approve,get_key,CredentialError
from research_provider import CheapTransport,MAX_BUDGET,save
from research_tools import ROOT

VERSION="OI-protocol-draft-v1"
REPORT_ROOT=ROOT/"data"/"research"/"agent_protocol"
DEFAULT_BUDGET=300000
TASK=("Разработай один проект протокола проверки добавочной ценности OI для риска "
      "падения BTC на горизонте 28 дней. Не запускай эксперимент, не меняй реестр. "
      "Сначала выясни, имеет ли смысл проверка с доступной историей; допустимо рекомендовать "
      "только перспективное наблюдение. Не придумывай предпочтения владельца.")
# Curated, static, reviewed research summaries. No runtime reads of registry, reports or secrets.
BRIEF={
    "E1":{"decision":"D3: risk of further decline / regime change, weeks to months",
          "OI-001":"Fixed feature log Friday Binance BTC OI quantity / median previous 13 Fridays. 86 matched weekly forecasts in 2022-23. Adding OI to weak volatility-only L1 reduced loss15 Brier by about .022 on Bitstamp; similar Coinbase, same market events. Exploratory, overlapping labels, no independent confirmation.",
          "COMB-001":"OI+funding improved weak L1 reference but overpredicted risk; all-factor combination worse. No meaningful purchase advantage."},
    "E2":{"GATE-001":"128 independent synthetic histories/scenario, 86/150 weekly origins; null detected 4/0, moderate 37/40, strong 102/111. Threshold .01 absolute Brier gain. Oracle moderate expected gain .00883/.00891 below threshold. Failed gate, cannot infer power for effect >=.01. Do not rerun or relax old gate to pass."},
    "E3":{"RISK-001":"Previously studied 2018-23: expanding empirical loss15 Brier .2323 (28d), scaled expanding .2303; rolling104 .2442/.2420. Risk calibration unstable across years. Stronger baseline must account for recent price moves; no winner selected. DVOL-001 139 overlapping 30d volatility forecasts; lower QLIKE, higher MAE, positive bias; not downside direction probability."},
    "E4":{"policy":"One primary comparison, all secondary comparisons fixed, no fresh historical holdout (2024+ exposed in other studies). Need a new study-specific null/planted diagnostic before market confirmation. Target provisional detection >=80%, false positive <=10% with MC uncertainty; separate useful effect from detection threshold, verify oracle effect before fitting. Fixed seeds, overlap/regime dependence, stopping rule. No personal risk tolerance or useful effect supplied. Existing BUY/RISK prospective journals separate; no backfill. No autonomous factor screening or execution."}
}
FIELDS=("decision_id","hypothesis","primary_comparison","baseline","target_and_horizon",
        "minimum_useful_effect_and_rationale","data_and_availability","evaluation_and_dependence",
        "synthetic_gate_spec_and_result","secondary_comparisons","stopping_rule",
        "evaluation_window","code_and_data_versions","limitations","recommendation")
CONTRACT={k:"short specific text" for k in FIELDS}
CONTRACT["decision_id"]="D3"
CONTRACT["recommendation"]="design_gate_only or prospective_only or defer"
CONTRACT["evidence"]=["E1","E2","E3","E4"]

def validate(obj):
    require(type(obj) is dict and set(obj)==set(CONTRACT),"Invalid protocol schema")
    require(obj["decision_id"]=="D3","Unexpected decision")
    require(obj["recommendation"] in ("design_gate_only","prospective_only","defer"),
            "Protocol cannot authorize confirmation")
    require(type(obj["evidence"]) is list and all(type(x) is str for x in obj["evidence"])
            and sorted(obj["evidence"])==sorted(BRIEF),"All four evidence summaries required")
    for k in FIELDS:
        checked_text(obj[k],1400)
    return obj

def design(transport):
    b=Budget()
    plan=b.model(transport,*STAGES[0][:2],{
        "task":TASK,"evidence":BRIEF,
        "output_contract":{"focus":"short methodological priority","pitfalls":["specific risk"]},
    },STAGES[0][2])
    require(set(plan)=={"focus","pitfalls"},"Invalid protocol plan")
    checked_text(plan["focus"],1000)
    require(type(plan["pitfalls"]) is list and 1<=len(plan["pitfalls"])<=5,"Invalid pitfalls")
    for x in plan["pitfalls"]:
        checked_text(x,600)
    draft=validate(b.model(transport,*STAGES[1][:2],{
        "task":TASK,"evidence":BRIEF,"plan":plan,"output_contract":CONTRACT,
        "instruction":"One hypothesis only; gate result must remain pending. No fabricated data."
    },STAGES[1][2]))
    final=validate(b.model(transport,*STAGES[2][:2],{
        "task":TASK,"evidence":BRIEF,"worker_draft":draft,"output_contract":CONTRACT,
        "review_instruction":"Correct flaws, especially power, price confounding, overlap and data leakage. "
                             "Reject unsupported claims. Do not authorize execution or tune to pass."
    },STAGES[2][2]))
    return {"kind":VERSION,"status":"draft_human_review_required","confirmation_authorized":False,
            "gate_executed":False,"evidence":BRIEF,"plan":plan,"worker_draft":draft,
            "final":final,"budget":b.summary(),"provider":transport.summary()}

def main():
    p=argparse.ArgumentParser(description=__doc__)
    modes=p.add_mutually_exclusive_group(required=True)
    modes.add_argument("--preview",action="store_true")
    modes.add_argument("--live-design",action="store_true")
    p.add_argument("--replace-key",action="store_true")
    p.add_argument("--budget-units",type=int,default=DEFAULT_BUDGET)
    a=p.parse_args()
    if not 0<a.budget_units<=MAX_BUDGET:
        p.error("Invalid budget")
    print(json.dumps({"task":TASK,"evidence":BRIEF,"output_contract":CONTRACT},ensure_ascii=True,indent=2))
    if a.preview:
        return 0
    print("Paid protocol draft. Three model calls, zero tools, no market data.")
    print("Estimated reservation cap:",a.budget_units,"base units, not a hard provider-side limit.")
    if not approve("Approve this data scope and paid run?"):
        return 0
    try:
        key=get_key(replace=a.replace_key)
        t=CheapTransport(key,a.budget_units)
        del key
    except (CredentialError,ControllerError):
        p.exit(1,"Local credential or budget error.\n")
    status=0
    try:
        report=design(t)
    except (ControllerError,KeyboardInterrupt):
        report={"kind":VERSION,"status":"stopped","confirmation_authorized":False,
                "provider":t.summary(),"note":"No retry. Check actual balance."}
        status=1
    print("Report:",save(report,REPORT_ROOT,prefix="agent_protocol_"))
    return status

if __name__=="__main__":
    raise SystemExit(main())
