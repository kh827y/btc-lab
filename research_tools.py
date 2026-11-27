"""Bounded, read-only local research interface. No model calls or execution tools."""
import argparse
import hashlib
import json
import re
from datetime import date,datetime,timedelta,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parent
VERSION="research-tools-v1"
REPORTS={
    "DD-001":"data/research/drawdown_v1/drawdown_report.json",
    "GATE-001":"data/research/gate_v1/synthetic_gate_report.json",
    "RISK-001":"data/research/risk_reference_v1/risk_reference_report.json",
    "DVOL-001":"data/research/dvol_v1/dvol_report.json",
}
JOURNALS={
    "buy":("buy_journal_receipts.json","BUY-001-journal-v1",
           "data/research/buy_journal","forecast.json"),
    "risk":("risk_journal_receipts.json","RISK-journal-v1",
            "data/research/risk_journal","risk_forecast.json"),
}
FIRST=date(2026,11,30)
DAY=timedelta(days=1)
WEEK=7*DAY
MAX_JSON=2*1024*1024
MAX_REPORT=64*1024*1024
HEX=re.compile(r"[0-9a-f]{64}\Z")
ID=re.compile(r"[A-Z][A-Z0-9-]{1,40}\Z")
OPERATIONS={"registry":set(),"study":{"id"},"report_integrity":{"id"},"journals":set()}


def fixed_file(root,relative):
    # No path supplied by a model. Reject links/junctions escaping the root.
    root=Path(root).resolve()
    p=root/relative
    if not p.resolve().is_relative_to(root):
        raise ValueError("Path escapes workspace")
    return p


def read_json(root,relative):
    p=fixed_file(root,relative)
    with p.open("rb") as f:
        raw=f.read(MAX_JSON+1)
    if len(raw)>MAX_JSON:
        raise ValueError("Metadata exceeds size limit")
    return json.loads(raw)


def sha_file(root,relative,limit=MAX_REPORT):
    p=fixed_file(root,relative)
    h=hashlib.sha256();n=0
    with p.open("rb") as f:
        while True:
            b=f.read(65536)
            if not b:
                break
            n+=len(b)
            if n>limit:
                raise ValueError("File exceeds size limit")
            h.update(b)
    return h.hexdigest()


def registry(root):
    obj=read_json(root,"RESEARCH_REGISTRY.json")
    if obj["schema"]!=1:
        raise ValueError("Unknown registry schema")
    policy=obj["new_study_policy"]
    studies={}
    for row in obj["studies"]+policy["new_studies"]:
        k=row["id"]
        if not ID.fullmatch(k) or k in studies:
            raise ValueError("Invalid/duplicate study ID")
        studies[k]=row
    return obj,studies


def overview(root):
    obj,studies=registry(root)
    p=obj["new_study_policy"]
    return {"policy_status":p["status"],"required_registration_fields":p["required"],
            "comparison_budget":p["comparison_budget"],"gate_policy":p["gate"],
            "confirmation_authorized":False,
            "historical_period_policy":obj["historical_period_policy"],
            "studies":[{"id":k,"kind":v.get("kind","legacy"),"status":v["status"]}
                       for k,v in studies.items()],
            "prospective":[{"id":v["id"],"status":v["status"]}
                           for v in obj["prospective"]],
            "note":"Registry inventory, not independently verified market evidence."}


def study(root,k):
    _,rows=registry(root)
    if k not in rows:
        raise ValueError("Unknown registered study")
    r=rows[k]
    fields=("id","kind","status","decision_id","target_and_horizon","evaluation_window",
            "evaluation_period","baseline","primary","primary_comparison",
            "secondary_comparisons","stopping_rule","synthetic_gate_spec_and_result",
            "result","next","minimum_useful_effect_and_rationale")
    return {**{f:r[f] for f in fields if f in r},
            "attempts":[{f:a[f] for f in ("status","summary","interpretation","report_sha256")
                         if f in a} for a in r.get("attempts",[])],
            "confirmation_authorized":False,
            "note":"Registered descriptions and summaries only; no raw outcomes."}


def integrity(root,k):
    if k not in REPORTS:
        raise ValueError("Report not on integrity allowlist")
    _,rows=registry(root)
    attempts=rows[k].get("attempts",[])
    expected=[a["report_sha256"] for a in attempts if "report_sha256" in a]
    if len(expected)!=1 or not HEX.fullmatch(expected[0]):
        return {"id":k,"status":"no_unique_registered_hash"}
    try:
        actual=sha_file(root,REPORTS[k])
    except FileNotFoundError:
        return {"id":k,"status":"missing_local_file"}
    return {"id":k,"status":"matches_registered_hash" if actual==expected[0] else "hash_mismatch",
            "expected_sha256":expected[0],"actual_sha256":actual,
            "note":"Byte identity only; not source validity or permission to run."}


def ledger_rows(root,name):
    ledger,version,_,_=JOURNALS[name]
    obj=read_json(root,ledger)
    if obj["version"]!=version:
        raise ValueError("Unexpected ledger version")
    out={}
    for r in obj["receipts"]:
        d=date.fromisoformat(r["origin"])
        ts=datetime.fromisoformat(r["created_utc"].replace("Z","+00:00"))
        if (d<FIRST or d.weekday()!=0 or d in out or ts.tzinfo is None
            or ts.astimezone(timezone.utc).date()!=d-DAY
            or not HEX.fullmatch(r["sha256"])
            or not re.fullmatch(r"https://github\.com/kh827y/btc-lab/issues/[0-9]+#issuecomment-[0-9]+",r["comment_url"])):
            raise ValueError("Invalid ledger entry")
        out[d]=r["sha256"]
    return out


def journals(root,today):
    result={}
    for name,(_,_,folder,filename) in JOURNALS.items():
        receipts=ledger_rows(root,name)
        if any(d>today+DAY for d in receipts):
            raise ValueError("Unexpected future ledger origin")
        counts={"anchored_matching":0,"anchored_missing":0,"anchored_mismatch":0,
                "unanchored_local":0,"missed":0}
        d=FIRST
        while d<=today:
            rel=f"{folder}/{d.isoformat()}/{filename}"
            if d in receipts:
                try:
                    actual=sha_file(root,rel,MAX_JSON)
                    key="anchored_matching" if actual==receipts[d] else "anchored_mismatch"
                except FileNotFoundError:
                    key="anchored_missing"
            else:
                key="unanchored_local" if fixed_file(root,rel).is_file() else "missed"
            counts[key]+=1
            d+=WEEK
        next_origin=max(FIRST,today+timedelta(days=7-today.weekday()))
        pending="not_issued"
        if today==next_origin-DAY:
            rel=f"{folder}/{next_origin.isoformat()}/{filename}"
            if next_origin in receipts:
                try:
                    pending="anchored_matching" if sha_file(root,rel,MAX_JSON)==receipts[next_origin] else "anchored_mismatch"
                except FileNotFoundError:
                    pending="anchored_missing"
            elif fixed_file(root,rel).is_file():
                pending="awaiting_receipt"
        result[name]={"past_origin_counts":counts,"next_origin":next_origin.isoformat(),
                      "next_issue_date_utc":(next_origin-DAY).isoformat(),
                      "next_origin_status":pending}
    return {"as_of_utc_date":today.isoformat(),"journals":result,
            "note":"Local receipt/file hash checks only; no server timestamp, source or outcome verification."}


def dispatch(operation,args=None,*,root=ROOT,today=None):
    """Only this interface may be exposed to a future model controller.
    root/today are trusted host-only test parameters, never model arguments."""
    if not isinstance(operation,str) or operation not in OPERATIONS:
        raise ValueError("Unknown operation")
    args={} if args is None else args
    if not isinstance(args,dict) or set(args)!=OPERATIONS[operation]:
        raise ValueError("Unexpected operation arguments")
    if "id" in args and (not isinstance(args["id"],str) or not ID.fullmatch(args["id"])):
        raise ValueError("Invalid study ID")
    if operation=="registry":
        out=overview(root)
    elif operation=="study":
        out=study(root,args["id"])
    elif operation=="report_integrity":
        out=integrity(root,args["id"])
    else:
        out=journals(root,today or datetime.now(timezone.utc).date())
    # Prevent accidentally sending long source material to a model.
    result={"version":VERSION,"operation":operation,"result":out}
    if len(json.dumps(result,ensure_ascii=False,allow_nan=False).encode("utf-8"))>24000:
        raise ValueError("Response exceeds interface limit")
    return result


if __name__=="__main__":
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("operation",choices=tuple(OPERATIONS))
    p.add_argument("id",nargs="?")
    a=p.parse_args()
    print(json.dumps(dispatch(a.operation,{"id":a.id} if a.id is not None else {}),
                     ensure_ascii=True,indent=2,allow_nan=False))
