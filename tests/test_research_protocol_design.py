import json
import unittest
from unittest.mock import patch
from research_controller import ControllerError
from research_protocol_design import design,validate,CONTRACT,BRIEF

class Fake:
    def __init__(self,bad=False):
        self.calls=[]
        self.bad=bad
    def __call__(self,role,request,cap):
        self.calls.append(role)
        if request["stage"]=="plan":
            return json.dumps({"focus":"power","pitfalls":["overlap"]})
        obj={**CONTRACT,"recommendation":"design_gate_only"}
        if self.bad:
            obj["recommendation"]="execute"
        return json.dumps(obj)
    def summary(self):
        return {"fake":True}

class ProtocolTest(unittest.TestCase):
    def test_draft_only(self):
        t=Fake()
        with patch("research_tools.dispatch",side_effect=AssertionError("tool called")):
            r=design(t)
        self.assertEqual(t.calls,["supervisor","worker","supervisor"])
        self.assertFalse(r["confirmation_authorized"])
        self.assertFalse(r["gate_executed"])
        self.assertEqual(r["budget"]["tool_calls"],0)
        self.assertIn("worker_draft",r)
    def test_reject_execution(self):
        t=Fake(True)
        with self.assertRaises(ControllerError):
            design(t)
        self.assertEqual(len(t.calls),2)
    def test_require_evidence(self):
        with self.assertRaises(ControllerError):
            validate({**CONTRACT,"recommendation":"defer","evidence":["E1"]})
    def test_brief_no_raw_data(self):
        s=json.dumps(BRIEF)
        for k in ("sha256","github.com","data/research","forecast.json"):
            self.assertNotIn(k,s)
