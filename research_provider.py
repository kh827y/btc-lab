"""Owner-launched CheapVibeCode smoke test, fictional evidence only."""
import argparse
import getpass
import json
import ssl
from datetime import datetime,timezone
from pathlib import Path
from urllib.request import Request,build_opener,HTTPSHandler,HTTPRedirectHandler,ProxyHandler
from urllib.error import HTTPError

from research_controller import run,encode,ControllerError,require,STAGES,strict_object

ENDPOINT="https://ru.cheapvibecode.ru/v1/chat/completions"
MODELS={"supervisor":"gpt-6.2-sol","worker":"deepseek-v4.1-flash-1017"}
# Account-specific observed tariff: 1.5 Sol, 0.19 DeepSeek, x5 if output > input.
# Reserve x5 unconditionally for BOTH roles until scope of surcharge is confirmed.
BASE_WEIGHTS={"supervisor":150,"worker":19}
SURCHARGE=5
WEIGHTS={k:v*SURCHARGE for k,v in BASE_WEIGHTS.items()}
TARIFF_VERSION="cheap-account-x5-20261127"
INPUT_MARGIN=2048
MAX_HTTP_BYTES=512*1024
TIMEOUT=240
TASK="На искусственных данных оцени готовность к подтверждению, целостность отчёта и состояние журналов. Не запускай исследования. Используй registry, study GATE-001, report_integrity DVOL-001 и journals."
MAX_BUDGET=500000
DEFAULT_BUDGET=200000
REPORT_ROOT=Path(__file__).resolve().parent/"data"/"research"/"agent_smoke"


class ProviderError(ControllerError):
    pass


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):
        raise ProviderError("Redirect rejected")


def opener():
    return build_opener(ProxyHandler({}),NoRedirect(),HTTPSHandler(context=ssl.create_default_context()))


def units(role,n):
    return (WEIGHTS[role]*n+99)//100


def estimated_debit(role,prompt_tokens,completion_tokens):
    """Account rule reported by owner; no cache discounts or hidden-token assumptions."""
    weight=BASE_WEIGHTS[role]*(SURCHARGE if completion_tokens>prompt_tokens else 1)
    return (weight*(prompt_tokens+completion_tokens)+99)//100


def payload(role,request,cap):
    body={"model":MODELS[role],"messages":[
        {"role":"system","content":request["system"]},
        {"role":"user","content":encode({"stage":request["stage"],"data":request["data"]}).decode("utf-8")}],
        "reasoning_effort":"high","max_tokens":cap,"stream":False}
    if role=="worker":
        body["thinking"]={"type":"enabled"}
    return encode(body)


def contains_credential(obj,key):
    """Check decoded JSON as well as raw text; escaped credentials must not reach logs."""
    if isinstance(obj,str):
        return key in obj
    if isinstance(obj,list):
        return any(contains_credential(v,key) for v in obj)
    if isinstance(obj,dict):
        return any(key in k or contains_credential(v,key) for k,v in obj.items())
    return False


def integer(x):
    return type(x) is int and x>=0


def usage_from(obj):
    u=obj.get("usage")
    require(type(u) is dict,"Missing provider usage")
    p,c,t=(u.get(k) for k in ("prompt_tokens","completion_tokens","total_tokens"))
    require(all(integer(x) for x in (p,c,t)) and t==p+c and p>0 and c>0,
            "Invalid provider usage")
    detail=u.get("completion_tokens_details")
    reasoning=detail.get("reasoning_tokens") if isinstance(detail,dict) else None
    require(reasoning is None or integer(reasoning) and reasoning<=c,"Invalid reasoning usage")
    return {"prompt_tokens":p,"completion_tokens":c,"total_tokens":t,
            "reasoning_tokens_reported":reasoning}


class CheapTransport:
    def __init__(self,key,budget,send=None):
        require(type(key) is str and 0<len(key)<=4096 and key.isascii() and
                all(33<=ord(ch)<=126 for ch in key),"Invalid API key format")
        require(type(budget) is int and 0<budget<=MAX_BUDGET,"Invalid base-unit budget")
        self._key=key
        self.budget=budget
        self.send=send if send is not None else opener().open
        self.reserved=0
        self.estimated=0
        self.records=[]
        self.stopped=False
        self.stop_reason=None

    def __call__(self,role,request,cap):
        require(not self.stopped,"Transport stopped")
        try:
            return self._call(role,request,cap)
        except ControllerError as exc:
            self.stopped=True
            self.stop_reason=str(exc)
            raise
        except Exception:
            self.stopped=True
            self.stop_reason="Unexpected transport error"
            raise ProviderError(self.stop_reason) from None

    def _call(self,role,request,cap):
        i=len(self.records)
        require(i<len(STAGES) and (role,request["stage"],cap)==STAGES[i],
                "Unapproved stage or output cap")
        raw=payload(role,request,cap)
        input_reserve=len(raw)+INPUT_MARGIN
        reservation=units(role,input_reserve+cap)
        require(self.reserved+reservation<=self.budget,"Estimated reservation exceeds approved budget")
        self.reserved+=reservation
        rec={"role":role,"stage":request["stage"],"model_requested":MODELS[role],
             "request_bytes":len(raw),"max_tokens":cap,"reserved_base_units":reservation,
             "status":"attempted_usage_unknown"}
        self.records.append(rec)
        req=Request(ENDPOINT,data=raw,method="POST",headers={
            "Authorization":"Bearer "+self._key,"Content-Type":"application/json",
            "Accept":"application/json","User-Agent":"BTC-Lab pilot"})
        try:
            with self.send(req,timeout=TIMEOUT) as response:
                require(response.geturl()==ENDPOINT and response.status==200,"Unexpected HTTP response")
                data=response.read(MAX_HTTP_BYTES+1)
                require(len(data)<=MAX_HTTP_BYTES,"HTTP response too large")
        except HTTPError as exc:
            rec["http_status"]=exc.code
            exc.close()
            raise ProviderError("Provider HTTP error; no retry") from None
        except ControllerError:
            raise
        except Exception:
            raise ProviderError("Network or response error; no retry") from None
        try:
            obj=json.loads(data)
        except (ValueError,RecursionError):
            raise ProviderError("Invalid provider JSON") from None
        require(type(obj) is dict and not obj.get("error"),"Provider returned error")
        u=usage_from(obj)
        rec["usage"]=u
        observed=estimated_debit(role,u["prompt_tokens"],u["completion_tokens"])
        worst_case=units(role,u["total_tokens"])
        self.estimated+=observed
        rec["estimated_base_units"]=observed
        rec["conservative_base_units_x5"]=worst_case
        rec["status"]="usage_received"
        require(u["prompt_tokens"]<=input_reserve and u["completion_tokens"]<=cap and
                worst_case<=reservation,"Reported usage exceeds reservation")
        require(obj.get("model")==MODELS[role],"Returned model ID mismatch")
        choices=obj.get("choices")
        require(isinstance(choices,list) and len(choices)==1 and isinstance(choices[0],dict),
                "Unexpected choices")
        ch=choices[0]
        require(ch.get("finish_reason")=="stop","Incomplete or nonstandard completion")
        msg=ch.get("message")
        require(type(msg) is dict and not msg.get("tool_calls") and not msg.get("function_call"),
                "Unexpected model tool call")
        content=msg.get("content")
        require(type(content) is str and bool(content.strip()),"Missing content")
        require(self._key not in content,"Credential appeared in response")
        decoded=strict_object(content)
        require(not contains_credential(decoded,self._key),"Credential appeared in decoded response")
        rec["status"]="response_received"
        return content

    def summary(self):
        return {"approved_estimated_base_units":self.budget,
                "reserved_base_units":self.reserved,
                "tariff_version":TARIFF_VERSION,
                "estimated_reported_usage_base_units":self.estimated,
                "attempts":self.records,"unknown_usage_attempts":sum("usage" not in x for x in self.records),
                "stop_reason":self.stop_reason,
                "note":"Owner-reported x5 surcharge when output exceeds input; reserves x5 on both routes. "
                       "Actual charge not independently verified. Hidden billing, "
                       "rate changes and provider limit violations possible. No hard spending guarantee."}


def fixture_tool(op,args):
    # No actual registry, report or journal file is opened.
    require(type(args) is dict,"Invalid fixture args")
    data={
        ("registry",None):{"policy_status":"screening_frozen","confirmation_authorized":False,
            "studies":[{"id":"GATE-001","status":"closed_not_passed"},
                       {"id":"DVOL-001","status":"closed_descriptive"}]},
        ("study","GATE-001"):{"id":"GATE-001","status":"closed_not_passed",
            "result":"Fictional positive control detected 30% of effects, required 80%.",
            "confirmation_authorized":False},
        ("study","DVOL-001"):{"id":"DVOL-001","status":"closed_descriptive",
            "result":"Fictional lower QLIKE but higher MAE; not confirmation."},
        ("report_integrity","DVOL-001"):{"id":"DVOL-001","status":"hash_mismatch",
            "note":"Deliberate fictional mismatch. Cannot verify identity."},
        ("journals",None):{"journals":{"buy":{"next_origin_status":"awaiting_receipt"},
                                       "risk":{"next_origin_status":"not_issued"}}},
    }
    k=(op,args.get("id"))
    require(k in data,"Not available in synthetic pilot")
    return {"version":"research-tools-v1","operation":op,
            "result":{"synthetic":True,**data[k]}}


def smoke(transport):
    result=run(TASK,transport,tool_runner=fixture_tool)
    return {"synthetic_evidence_only":True,"result":result,"provider":transport.summary()}


def save(report,root=REPORT_ROOT,*,prefix="agent_smoke_"):
    root.mkdir(parents=True,exist_ok=True)
    stamp=datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path=root/(prefix+stamp+".json")
    with path.open("x",encoding="utf-8") as f:
        json.dump(report,f,ensure_ascii=False,indent=2,allow_nan=False)
        f.write("\n")
    return path


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--live-smoke",action="store_true",required=True)
    p.add_argument("--budget-units",type=int,default=DEFAULT_BUDGET)
    a=p.parse_args()
    if not 0<a.budget_units<=MAX_BUDGET:
        p.error("Budget must be 1..500000 estimated base units")
    print("Paid synthetic pilot, max 3 calls. Estimated base-unit cap:",a.budget_units)
    print("Not a provider-side spending limit. Check balance before/after.")
    if input("Type YES to approve this paid pilot: ")!="YES":
        p.exit(0,"Cancelled\n")
    # getpass may fall back to echoed input on incompatible terminals;
    # refuse that fallback instead of exposing the key.
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("error",getpass.GetPassWarning)
        try:
            key=getpass.getpass("CheapVibeCode API key: ")
        except getpass.GetPassWarning:
            p.exit(1,"Hidden key input unavailable; use a normal terminal.\n")
    try:
        t=CheapTransport(key,a.budget_units)
    except ControllerError:
        p.exit(1,"Invalid API key or budget.\n")
    del key
    status=0
    try:
        report=smoke(t)
    except ControllerError:
        report={"synthetic_evidence_only":True,"status":"stopped",
                "provider":t.summary(),"note":"Controller or transport stopped; no retry. Check actual balance."}
        status=1
    except KeyboardInterrupt:
        report={"synthetic_evidence_only":True,"status":"interrupted",
                "provider":t.summary(),"note":"In-flight charge may be unknown; no retry."}
        status=1
    path=save(report)
    print("Report:",path)
    return status


if __name__=="__main__":
    raise SystemExit(main())
