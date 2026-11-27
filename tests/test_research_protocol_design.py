import json
import unittest
from unittest.mock import patch
from research_controller import ControllerError
from research_protocol_design import design,validate,validate_review,CONTRACT,BRIEF
from research_provider import CheapTransport,PROTOCOL_STAGES

class Fake:
    def __init__(self,bad=False,review_bad=False):
        self.calls=[]
        self.bad=bad
        self.review_bad=review_bad
    def __call__(self,role,request,cap):
        self.calls.append((role,request["stage"],cap))
        if request["stage"]=="review":
            return json.dumps({"verdict":"execute" if self.review_bad else "revise",
                               "issues":[{"field":"baseline","critique":"weak",
                                          "suggested_change":"control recent returns"}],
                               "limitations":"No validation"})
        obj={**CONTRACT,"recommendation":"execute" if self.bad else "design_gate_only"}
        return json.dumps(obj)
    def summary(self):
        return {"fake":True}

class ProtocolTest(unittest.TestCase):
    def test_default_one_call(self):
        t=Fake()
        with patch("research_tools.dispatch",side_effect=AssertionError("tool called")):
            r=design(t)
        self.assertEqual(t.calls,[PROTOCOL_STAGES[0]])
        self.assertFalse(r["confirmation_authorized"])
        self.assertFalse(r["gate_executed"])
        self.assertEqual(r["budget"]["tool_calls"],0)
        self.assertIn("worker_draft",r)
        self.assertEqual(r["review_status"],"declined")
    def test_optional_review(self):
        t=Fake()
        r=design(t,approve_review=lambda _:True)
        self.assertEqual(t.calls,list(PROTOCOL_STAGES))
        self.assertEqual(r["review"]["verdict"],"revise")
        self.assertIn("worker_draft",r)
    def test_review_failure_preserves_draft_and_reason(self):
        t=Fake(review_bad=True)
        r=design(t,approve_review=lambda _:True)
        self.assertEqual(t.calls,list(PROTOCOL_STAGES))
        self.assertIn("worker_draft",r)
        self.assertEqual(r["failed_stage"],"supervisor_review")
        self.assertEqual(r["controller_error"],"Invalid review verdict")
        self.assertEqual(r["status"],"draft_saved_review_failed")
    def test_reject_execution(self):
        t=Fake(True)
        r=design(t,approve_review=lambda _:True)
        self.assertEqual(t.calls,[PROTOCOL_STAGES[0]])
        self.assertNotIn("worker_draft",r)
        self.assertEqual(r["failed_stage"],"worker_draft")
    def test_require_evidence(self):
        with self.assertRaises(ControllerError):
            validate({**CONTRACT,"recommendation":"defer","evidence":["E1"]})
    def test_review_requires_known_fields(self):
        with self.assertRaises(ControllerError):
            validate_review({"verdict":"revise","issues":[{"field":"execute","critique":"x",
                             "suggested_change":"x"}],"limitations":"x"})
    def test_no_new_transport_routes(self):
        with self.assertRaises(ControllerError):
            CheapTransport("test-key",200000,send=lambda *a,**k:None,
                           stages=(("worker","analyze",999999),))
    def test_brief_no_raw_data(self):
        s=json.dumps(BRIEF)
        for k in ("sha256","github.com","data/research","forecast.json"):
            self.assertNotIn(k,s)
