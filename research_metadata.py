"""Owner-reviewed, minimized real metadata pilot. No model-directed filesystem reads."""
import argparse
import json
import math
from pathlib import Path

from research_credentials import approve,get_key,CredentialError
from research_controller import run,encode,require,ControllerError
from research_provider import CheapTransport,DEFAULT_BUDGET,MAX_BUDGET,save
from research_tools import ROOT,registry,dispatch

VERSION="metadata-review-v1"
REPORT_ROOT=ROOT/"data"/"research"/"agent_review"
TASK=("Оцени готовность BTC-Lab к новому подтверждающему исследованию. "
      "Используй все четыре разрешённых операции: registry, study GATE-001, "
      "report_integrity DVOL-001, journals. Различай зарегистрированный результат, "
      "совпадение байтов и состояние локальных журналов. "
      "Предложи один полезный следующий шаг без запуска исследования.")
STUDY_IDS=("CPI-001","BUY-001","FLOW-001","VALUE-001","FUND-001","OI-001",
           "MACRO-001","COMB-001","DD-001","GATE-001","RISK-001","DVOL-001")
STUDY_STATUS={"closed","closed_descriptive","closed_not_passed","registered_pending_run"}
INTEGRITY_STATUS={"matches_registered_hash","hash_mismatch","missing_local_file","no_unique_registered_hash"}
JOURNAL_STATUS={"not_issued","awaiting_receipt","anchored_matching","anchored_missing","anchored_mismatch"}
COUNT_KEYS=("anchored_matching","anchored_missing","anchored_mismatch","unanchored_local","missed")
MAX_SNAPSHOT_BYTES=8000


def allowed(value,choices):
    require(type(value) is str and value in choices,"Unexpected metadata enum")
    return value


def count(value,limit=10000):
    require(type(value) is int and 0<=value<=limit,"Invalid metadata count")
    return value


def probability(value):
    require(type(value) in (int,float) and math.isfinite(value) and 0<=value<=1,
            "Invalid numeric metadata")
    return value


def pair(values,validator):
    require(type(values) is list and len(values)==2,"Invalid gate result shape")
    return [validator(x) for x in values]


def boolean(value):
    require(type(value) is bool,"Invalid gate flag")
    return value


def capture(root=ROOT):
    """Trusted local step before approval/network. Export only the original approved study IDs."""
    obj,rows=registry(root)
    require(set(STUDY_IDS)<=set(rows),"Approved study missing; review export allowlist")
    require(obj["new_study_policy"]["status"]=="screening_frozen","Research policy changed")
    gate=rows["GATE-001"]
    require(gate["status"]=="closed_not_passed" and len(gate["attempts"])==1,
            "Unexpected gate state")
    a=gate["attempts"][0]
    require(a["status"]=="completed_not_passed","Unexpected gate attempt")
    g=a["result"]
    require(g["sizes"]==[86,150] and g["histories_per_scenario"]==128,
            "Unexpected gate design")
    gate_data={
        "id":"GATE-001","status":"closed_not_passed","source":"registered_synthetic_summary",
        "weekly_origins":[86,150],"histories_per_scenario":128,
        "minimum_useful_brier_gain":.01,
        "null_detected":pair(g["null_detected"],lambda x:count(x,128)),
        "moderate_detected":pair(g["moderate_detected"],lambda x:count(x,128)),
        "strong_detected":pair(g["strong_detected"],lambda x:count(x,128)),
        "moderate_oracle_expected_gain":pair(g["moderate_oracle_expected_gain"],probability),
        "point_pass":pair(g["point_pass"],boolean),
        "uncertainty_pass":pair(g["uncertainty_pass"],boolean),
        "confirmation_authorized":False,
        "limitation":"Registered synthetic summary, not independently reproduced here. No market outcome access."
    }
    integrity=dispatch("report_integrity",{"id":"DVOL-001"},root=root)["result"]
    journal=dispatch("journals",{},root=root)["result"]["journals"]
    require(set(journal)=={"buy","risk"},"Unexpected journal inventory")
    j={}
    for k in ("buy","risk"):
        x=journal[k]
        c=x["past_origin_counts"]
        require(set(c)==set(COUNT_KEYS),"Unexpected journal counts")
        j[k]={"past_origin_counts":{s:count(c[s]) for s in COUNT_KEYS},
              "next_origin_status":allowed(x["next_origin_status"],JOURNAL_STATUS)}
    snapshot={
        "registry":{"policy_status":"screening_frozen","confirmation_authorized":False,
                    "studies":[{"id":k,"status":allowed(rows[k]["status"],STUDY_STATUS)} for k in STUDY_IDS],
                    "limitation":"Registered statuses only. No claim of confirmed market skill."},
        "study":gate_data,
        "report_integrity":{"id":"DVOL-001","status":allowed(integrity["status"],INTEGRITY_STATUS),
                            "limitation":"Local byte identity check only; no hash values or report content exported."},
        "journals":{"journals":j,
                    "limitation":"Local status counts only; no forecasts, dates, receipts or outcome content exported."}
    }
    raw=encode(snapshot)
    require(len(raw)<=MAX_SNAPSHOT_BYTES,"Export too large")
    return raw


class FrozenTools:
    """No path/clock/provider access. Each operation returns an approved in-memory projection."""
    def __init__(self,raw):
        require(type(raw) is bytes and len(raw)<=MAX_SNAPSHOT_BYTES,"Invalid snapshot")
        self._raw=raw

    def __call__(self,op,args):
        require(type(op) is str and op in ("registry","study","report_integrity","journals"),
                "Operation outside approved snapshot")
        expected={"study":{"id":"GATE-001"},"report_integrity":{"id":"DVOL-001"}}
        require(type(args) is dict and args==expected.get(op,{}),"Request outside approved snapshot")
        return {"version":"research-tools-v1","operation":op,
                "result":json.loads(self._raw)[op]}


def review(raw,transport):
    result=run(TASK,transport,tool_runner=FrozenTools(raw))
    return {"kind":VERSION,"synthetic_evidence_only":False,"approved_snapshot":json.loads(raw),
            "result":result,"provider":transport.summary()}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    modes=p.add_mutually_exclusive_group(required=True)
    modes.add_argument("--preview",action="store_true")
    modes.add_argument("--live-review",action="store_true")
    p.add_argument("--budget-units",type=int,default=DEFAULT_BUDGET)
    p.add_argument("--replace-key",action="store_true",help="Replace the saved local key")
    a=p.parse_args()
    if not 0<a.budget_units<=MAX_BUDGET:
        p.error("Budget must be 1..500000 estimated base units")
    try:
        raw=capture()
    except Exception:
        p.exit(1,"Local metadata capture failed. No network request made.\n")
    print("Exact local evidence eligible for export (subset may be used):")
    print(json.dumps(json.loads(raw),ensure_ascii=True,indent=2))
    print("Task:",TASK)
    print("Provider: CheapVibeCode. No files or keys in model messages; model-generated text may be passed between stages.")
    if a.preview:
        return 0
    print("Paid review, max 3 requests. Estimated base-unit cap:",a.budget_units)
    print("Provider may retain the above metadata. Budget is not a provider-side hard limit.")
    if not approve("Approve this data scope and paid run?"):
        p.exit(0,"Cancelled. No network request made.\n")
    try:
        key=get_key(replace=a.replace_key)
    except CredentialError as exc:
        p.exit(1,str(exc)+"\n")
    try:
        t=CheapTransport(key,a.budget_units)
    except ControllerError:
        p.exit(1,"Invalid API key or budget.\n")
    del key
    status=0
    try:
        report=review(raw,t)
    except (ControllerError,KeyboardInterrupt):
        report={"kind":VERSION,"status":"stopped","approved_snapshot":json.loads(raw),
                "provider":t.summary(),"note":"No retry. Check actual balance."}
        status=1
    path=save(report,REPORT_ROOT,prefix="agent_review_")
    print("Report:",path)
    return status


if __name__=="__main__":
    raise SystemExit(main())
