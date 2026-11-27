import hashlib
import json
import unittest
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory

from research_tools import dispatch,ROOT,REPORTS,JOURNALS


class ResearchToolsTest(unittest.TestCase):
    def test_real_registry(self):
        r=dispatch("registry")["result"]
        self.assertFalse(r["confirmation_authorized"])
        self.assertIn("DVOL-001",[x["id"] for x in r["studies"]])
        self.assertEqual(dispatch("study",{"id":"GATE-001"})["result"]["status"],"closed_not_passed")

    def test_reject_unsupported(self):
        for op,args in [("execute",{}),("study",{"id":"../secret"}),
                        ("registry",{"root":"/tmp"}),("study",{"id":"UNKNOWN"}),
                        ("report_integrity",{"id":"BUY-001"}),("journals",{"today":"2026-11-30"})]:
            with self.assertRaises(ValueError):
                dispatch(op,args)

    def test_integrity(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)
            raw=b'{"not":"read by tool"}'
            h=hashlib.sha256(raw).hexdigest()
            r={"schema":1,"studies":[],"new_study_policy":{"new_studies":[
                {"id":"DVOL-001","attempts":[{"report_sha256":h}]}]}}
            (p/"RESEARCH_REGISTRY.json").write_text(json.dumps(r))
            args={"id":"DVOL-001"}
            self.assertEqual(dispatch("report_integrity",args,root=p)["result"]["status"],"missing_local_file")
            target=p/REPORTS["DVOL-001"];target.parent.mkdir(parents=True)
            target.write_bytes(raw)
            self.assertEqual(dispatch("report_integrity",args,root=p)["result"]["status"],"matches_registered_hash")
            target.write_bytes(b"changed")
            self.assertEqual(dispatch("report_integrity",args,root=p)["result"]["status"],"hash_mismatch")

    def test_journal_pending_and_missed(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)
            for _,(ledger,version,_,_) in JOURNALS.items():
                (p/ledger).write_text(json.dumps({"version":version,"receipts":[]}))
            def status(d):
                return dispatch("journals",root=p,today=d)["result"]["journals"]["buy"]
            self.assertEqual(status(date(2026,11,27))["next_origin"],"2026-11-30")
            self.assertEqual(status(date(2026,11,29))["next_origin_status"],"not_issued")
            ledger,version,folder,filename=JOURNALS["buy"]
            f=p/folder/"2026-11-30"/filename
            f.parent.mkdir(parents=True);f.write_bytes(b"forecast")
            self.assertEqual(status(date(2026,11,29))["next_origin_status"],"awaiting_receipt")
            self.assertEqual(status(date(2026,11,30))["past_origin_counts"]["unanchored_local"],1)
            r={"origin":"2026-11-30","created_utc":"2026-11-29T12:00:00Z",
               "sha256":hashlib.sha256(b"forecast").hexdigest(),
               "comment_url":"https://github.com/kh827y/btc-lab/issues/2#issuecomment-123"}
            (p/ledger).write_text(json.dumps({"version":version,"receipts":[r]}))
            self.assertEqual(status(date(2026,11,29))["next_origin_status"],"anchored_matching")
            self.assertEqual(status(date(2026,11,30))["past_origin_counts"]["anchored_matching"],1)
            f.unlink()
            self.assertEqual(status(date(2026,11,30))["past_origin_counts"]["anchored_missing"],1)
