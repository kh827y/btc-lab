"""One bounded protocol-design task. No outcome data, execution or registration."""
import argparse
import json

from research_controller import Budget,checked_text,require,ControllerError,encode
from research_credentials import approve,get_key,CredentialError
from research_provider import CheapTransport,MAX_BUDGET,save,PROTOCOL_STAGES,payload,units,INPUT_MARGIN
from research_tools import ROOT

VERSION="OI-protocol-draft-v2"
REPORT_ROOT=ROOT/"data"/"research"/"agent_protocol"
DEFAULT_BUDGET=200000
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

REVIEW_CONTRACT={"verdict":"revise or defer or suitable_for_human_review",
                 "issues":[{"field":"one existing protocol field","critique":"specific defect",
                            "suggested_change":"concise correction"}],
                 "limitations":"concise residual uncertainty"}

def validate_review(obj):
    require(type(obj) is dict and set(obj)==set(REVIEW_CONTRACT),"Invalid review schema")
    require(obj["verdict"] in ("revise","defer","suitable_for_human_review"),
            "Invalid review verdict")
    issues=obj["issues"]
    require(type(issues) is list and len(issues)<=4,"Invalid review issue count")
    for issue in issues:
        require(type(issue) is dict and set(issue)=={"field","critique","suggested_change"},
                "Invalid review issue schema")
        require(issue["field"] in FIELDS,"Unknown protocol field")
        checked_text(issue["critique"],900)
        checked_text(issue["suggested_change"],900)
    require(obj["verdict"]!="revise" or bool(issues),"Revision requires an issue")
    checked_text(obj["limitations"],1000)
    return obj

def review_data(draft):
    return {"task":"Critique the draft only. Do not reproduce the protocol. "
                   "Return at most four consequential issues and short corrections. "
                   "No execution or confirmation; assess power, price confounding and leakage.",
            "evidence":BRIEF,"worker_draft":draft,"output_contract":REVIEW_CONTRACT}

def design(transport,*,approve_review=lambda _:False):
    """Fixed task needs no model planning. Keep a valid draft even if review is declined or fails."""
    b=Budget()
    report={"kind":VERSION,"status":"stopped","confirmation_authorized":False,
            "gate_executed":False,"evidence":BRIEF,"review":None}
    stage="worker_draft"
    try:
        draft=validate(b.model(transport,*PROTOCOL_STAGES[0][:2],{
            "task":TASK,"evidence":BRIEF,"output_contract":CONTRACT,
            "instruction":"Return exactly these keys; each field concise, no repeated text. "
                          "One hypothesis only; gate result must remain pending. No fabricated data."
        },PROTOCOL_STAGES[0][2]))
        report["worker_draft"]=draft
        report["status"]="draft_human_review_required"
        stage="review_approval"
        if approve_review(draft):
            stage="supervisor_review"
            report["review"]=validate_review(b.model(transport,*PROTOCOL_STAGES[1][:2],
                                                    review_data(draft),PROTOCOL_STAGES[1][2]))
            report["status"]="reviewed_draft_human_review_required"
        else:
            report["review_status"]="declined"
    except ControllerError as exc:
        report["failed_stage"]=stage
        # ControllerError strings are host-authored diagnostics, not model payloads.
        report["controller_error"]=str(exc)
        if "worker_draft" in report:
            report["status"]="draft_saved_review_failed"
    except KeyboardInterrupt:
        report["failed_stage"]=stage
        report["controller_error"]="Interrupted; attempted request may have been billed."
        if "worker_draft" in report:
            report["status"]="draft_saved_review_interrupted"
    report["budget"]=b.summary()
    report["provider"]=transport.summary()
    return report

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
    print(json.dumps({"task":TASK,"evidence":BRIEF,"output_contract":CONTRACT,"optional_review_contract":REVIEW_CONTRACT},ensure_ascii=True,indent=2))
    if a.preview:
        return 0
    print("Paid protocol draft. One DeepSeek request, optional separate Sol review, zero tools.")
    print("Estimated reservation cap:",a.budget_units,"base units, not a hard provider-side limit.")
    if not approve("Approve this data scope and paid run?"):
        return 0
    try:
        key=get_key(replace=a.replace_key)
        t=CheapTransport(key,a.budget_units,stages=PROTOCOL_STAGES)
        del key
    except (CredentialError,ControllerError):
        p.exit(1,"Local credential or budget error.\n")
    def ask_review(draft):
        # Show the actual draft and a conservative reservation before the optional charge.
        from research_controller import SYSTEM_RULES
        req={"system":SYSTEM_RULES,"stage":"review","data":review_data(draft)}
        cap=PROTOCOL_STAGES[1][2]
        reserve=units("supervisor",len(payload("supervisor",req,cap))+INPUT_MARGIN+cap)
        print("DeepSeek estimated debit:",t.estimated)
        print(json.dumps(draft,ensure_ascii=True,indent=2))
        print("Optional Sol review estimated reservation:",reserve,"base units (not actual charge).")
        if t.reserved+reserve>t.budget:
            print("Remaining estimated budget insufficient. Keeping draft without review.")
            return False
        return approve("Run optional paid Sol critique?")
    report=design(t,approve_review=ask_review)
    print("Report:",save(report,REPORT_ROOT,prefix="agent_protocol_"))
    return 1 if "failed_stage" in report else 0

if __name__=="__main__":
    raise SystemExit(main())
