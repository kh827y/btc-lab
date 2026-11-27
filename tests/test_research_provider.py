import json
import unittest
from research_controller import ControllerError,STAGES
from research_provider import CheapTransport,fixture_tool,smoke,ENDPOINT,MODELS,usage_from,units,estimated_debit,NoRedirect

class Response:
    status=200
    def __init__(self,obj,url=ENDPOINT):
        self.raw=json.dumps(obj).encode()
        self.url=url
    def geturl(self):
        return self.url
    def read(self,n):
        return self.raw[:n]
    def __enter__(self):
        return self
    def __exit__(self,*a):
        pass

def plan():
    return {"goal":"check","requests":[{"operation":"registry","args":{}},
            {"operation":"study","args":{"id":"GATE-001"}},
            {"operation":"report_integrity","args":{"id":"DVOL-001"}},
            {"operation":"journals","args":{}}]}

def answer():
    return {"findings":[{"text":"Fictional gate failed","evidence":["E2"]}],
            "limitations":["Synthetic only"],"next_step":"Manual review"}

def envelope(role,content):
    return {"model":MODELS[role],"usage":{"prompt_tokens":100,"completion_tokens":100,
                "total_tokens":200,"completion_tokens_details":{"reasoning_tokens":25}},
            "choices":[{"finish_reason":"stop","message":{"content":json.dumps(content)}}]}

class ProviderTest(unittest.TestCase):
    def test_three_calls_and_usage(self):
        sent=[]
        def send(req,timeout):
            b=json.loads(req.data)
            sent.append(b)
            role="worker" if b["model"]==MODELS["worker"] else "supervisor"
            self.assertEqual(req.full_url,ENDPOINT)
            self.assertEqual(b["reasoning_effort"],"high")
            self.assertFalse(b["stream"])
            self.assertEqual("thinking" in b,role=="worker")
            self.assertNotIn("test-key",req.data.decode())
            self.assertEqual(b["max_tokens"],STAGES[len(sent)-1][2])
            return Response(envelope(role,plan() if len(sent)==1 else answer()))
        t=CheapTransport("test-key",200000,send)
        r=smoke(t)
        self.assertEqual(len(sent),3)
        self.assertTrue(r["synthetic_evidence_only"])
        self.assertEqual(t.estimated,2*estimated_debit("supervisor",100,100)+estimated_debit("worker",100,100))
        self.assertEqual(t.summary()["unknown_usage_attempts"],0)
        self.assertLessEqual(t.reserved,t.budget)
        self.assertNotIn("test-key",json.dumps(r))

    def test_budget_before_network(self):
        sent=[]
        t=CheapTransport("key",1,lambda *a,**k:sent.append(a))
        with self.assertRaises(ControllerError):
            smoke(t)
        self.assertEqual(sent,[])
        self.assertTrue(t.stopped)

    def test_errors_stop_without_retry(self):
        for kind in ("missing_usage","over_cap","truncated","wrong_model","redirect","network","key_echo","escaped_key_echo"):
            sent=[]
            def send(req,timeout):
                sent.append(req)
                x=envelope("supervisor",plan())
                if kind=="missing_usage":
                    del x["usage"]
                elif kind=="over_cap":
                    c=STAGES[0][2]+1
                    x["usage"]={"prompt_tokens":100,"completion_tokens":c,"total_tokens":100+c}
                elif kind=="truncated":
                    x["choices"][0]["finish_reason"]="length"
                elif kind=="wrong_model":
                    x["model"]="other"
                elif kind=="network":
                    raise OSError("secret")
                elif kind=="key_echo":
                    x["choices"][0]["message"]["content"]='{"secret":"key-test"}'
                elif kind=="escaped_key_echo":
                    x["choices"][0]["message"]["content"]='{"secret":"\\u006bey-test"}'
                return Response(x,"https://other.invalid/" if kind=="redirect" else ENDPOINT)
            t=CheapTransport("key-test",200000,send)
            with self.assertRaises(ControllerError):
                smoke(t)
            self.assertEqual(len(sent),1)
            self.assertTrue(t.stopped)
            self.assertGreater(t.reserved,0)
            self.assertNotIn("key-test",json.dumps(t.summary()))

    def test_redirect_handler_rejects(self):
        with self.assertRaises(ControllerError):
            NoRedirect().redirect_request(None,None,302,None,None,"https://other.invalid/")

    def test_usage_validation(self):
        for u in ({"prompt_tokens":1,"completion_tokens":2,"total_tokens":4},
                  {"prompt_tokens":True,"completion_tokens":2,"total_tokens":3},
                  {"prompt_tokens":1,"completion_tokens":2,"total_tokens":3,
                   "completion_tokens_details":{"reasoning_tokens":3}}):
            with self.assertRaises(ControllerError):
                usage_from({"usage":u})
        self.assertIsNone(usage_from({"usage":{"prompt_tokens":1,"completion_tokens":2,
                                             "total_tokens":3}})["reasoning_tokens_reported"])

    def test_account_tariff_and_reservation(self):
        self.assertEqual(estimated_debit("supervisor",256,216),708)
        self.assertEqual(estimated_debit("worker",554,1375),1833)
        self.assertEqual(estimated_debit("supervisor",1009,491),2250)
        self.assertEqual(estimated_debit("worker",100,100),38)
        self.assertEqual(estimated_debit("worker",100,101),191)
        self.assertEqual(estimated_debit("supervisor",100,101),1508)
        self.assertEqual(units("supervisor",472),3540)
        self.assertEqual(units("worker",1929),1833)

    def test_fictional_only(self):
        r=fixture_tool("report_integrity",{"id":"DVOL-001"})
        self.assertTrue(r["result"]["synthetic"])
        self.assertEqual(r["result"]["status"],"hash_mismatch")
        with self.assertRaises(ControllerError):
            fixture_tool("study",{"id":"BUY-001"})
