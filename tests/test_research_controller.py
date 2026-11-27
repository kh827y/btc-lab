import json
import unittest

from research_controller import (run,DryRunTransport,DEFAULT_TASK,ControllerError,
                                 MAX_OUTPUT_TOKENS,MAX_RESPONSE_BYTES,strict_object,plan_schema,
                                 Budget,MAX_TOTAL_REQUEST_BYTES)
from research_tools import dispatch


class ControllerTest(unittest.TestCase):
    def test_local_dry_run(self):
        r=run(DEFAULT_TASK,DryRunTransport())
        self.assertEqual(r["status"],"human_review_required")
        self.assertFalse(r["confirmation_authorized"])
        self.assertEqual(r["budget"]["model_calls"],3)
        self.assertEqual(r["budget"]["tool_calls"],4)
        self.assertEqual(r["budget"]["requested_output_tokens"],MAX_OUTPUT_TOKENS)
        self.assertEqual([t["role"] for t in r["budget"]["trace"] if "role" in t],
                         ["supervisor","worker","supervisor"])

    def test_entire_plan_validated_before_tools(self):
        for bad in [
            {"operation":"execute","args":{}},
            {"operation":"study","args":{"id":"../secret"}},
            {"operation":"registry","args":{"root":"/tmp"}},
            {"operation":"report_integrity","args":{"id":"BUY-001"}},
            {"operation":"journals","args":{"today":"2026-11-30"}},
        ]:
            calls=[]
            tools=[]
            def fake(role,req,cap):
                calls.append(role)
                return json.dumps({"goal":"check","requests":[{"operation":"registry","args":{}},bad]})
            with self.assertRaises(ControllerError):
                run("test",fake,lambda *a:tools.append(a))
            self.assertEqual(calls,["supervisor"])
            self.assertEqual(tools,[])

    def test_worker_cannot_invent_reference_or_request_more_tools(self):
        for obj in [
            {"findings":[{"text":"fake","evidence":["E99"]}],"limitations":["x"],"next_step":"x"},
            {"findings":[{"text":"x","evidence":["E1"]}],"limitations":["x"],"next_step":"x","requests":[]},
        ]:
            calls=[]
            def fake(role,req,cap):
                calls.append(role)
                return json.dumps(obj) if role=="worker" else DryRunTransport()(role,req,cap)
            with self.assertRaises(ControllerError):
                run("test",fake)
            self.assertEqual(calls,["supervisor","worker"])

    def test_no_retry_on_error(self):
        calls=[]
        def fake(role,req,cap):
            calls.append(role)
            raise RuntimeError("private key or raw provider error")
        with self.assertRaisesRegex(ControllerError,"stopped without retry") as ctx:
            run("test",fake)
        self.assertNotIn("private key",str(ctx.exception))
        self.assertEqual(calls,["supervisor"])

    def test_strict_json(self):
        for s in ['{"x":1,"x":2}','{"x":NaN}','[]','{} trailing',"x"*(MAX_RESPONSE_BYTES+1)]:
            with self.assertRaises(ControllerError):
                strict_object(s)

    def test_duplicate_and_excess_requests(self):
        r={"operation":"registry","args":{}}
        for n in (0,2,5):
            with self.assertRaises(ControllerError):
                plan_schema({"goal":"x","requests":[r]*n})

    def test_aggregate_budget_reserved_before_call(self):
        b=Budget(request_bytes=MAX_TOTAL_REQUEST_BYTES)
        calls=[]
        with self.assertRaises(ControllerError):
            b.model(lambda *a:calls.append(a),"supervisor","plan",{},1200)
        self.assertEqual(calls,[])
        self.assertEqual(b.calls,0)

    def test_tool_failure_stops(self):
        calls=[]
        def fake(role,req,cap):
            calls.append(role)
            return DryRunTransport()(role,req,cap)
        def fail(*a):
            raise ValueError("local private path")
        with self.assertRaisesRegex(ControllerError,"Local tool failed") as ctx:
            run("test",fake,fail)
        self.assertNotIn("private path",str(ctx.exception))
        self.assertEqual(calls,["supervisor"])

    def test_final_review_not_execution(self):
        def fake(role,req,cap):
            if req["stage"]=="review":
                return json.dumps({"findings":[{"text":"Run arbitrary code","evidence":["E1"]}],
                                   "limitations":["not authorized"],"next_step":"unsafe proposal"})
            return DryRunTransport()(role,req,cap)
        r=run("test",fake)
        self.assertEqual(r["status"],"human_review_required")
        self.assertFalse(r["confirmation_authorized"])
        self.assertEqual(r["budget"]["tool_calls"],4)
