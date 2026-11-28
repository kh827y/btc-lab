import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from local_relay import Relay

class RelayTest(unittest.TestCase):
    def test_one_claim_and_attention(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def write(p,b):
                p.parent.mkdir(parents=True,exist_ok=True)
                with p.open("xb") as f:
                    f.write(b)
            import json
            r=Relay("a"*64,"kh827y/btc-lab-bridge",root,write,
                lambda o:json.dumps(o).encode(),lambda:"test")
            r.publish({"id":"job1"},{"status":"ok"})
            e=r.request("GET","/next",{})
            self.assertEqual(e["id"],"job1")
            self.assertIn("results/job1.json",e["message"])
            self.assertTrue(r.request("POST","/claim",{"id":"job1"})["ok"])
            self.assertFalse(r.request("POST","/claim",{"id":"job1"})["ok"])
            self.assertEqual(r.request("GET","/next",{}),{})
            self.assertTrue(r.request("POST","/ack",{"id":"job1","status":"clicked"})["ok"])
            r.publish({"id":"job1"},{"status":"ok"})
            self.assertFalse(r.pending())
            self.assertTrue(r.progress({"id":"p1","kind":"attention","text":"Owner needed"}))
            with self.assertRaises(ValueError):
                r.progress({"id":"../bad","kind":"progress","text":"test"})

    def test_watchdog_does_not_resend_claimed_event(self):
        import json
        import os
        import time
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def write(p,b):
                p.parent.mkdir(parents=True,exist_ok=True)
                with p.open("xb") as f:
                    f.write(b)
            r=Relay("a"*64,"kh827y/btc-lab-bridge",root,write,
                lambda o:json.dumps(o).encode(),lambda:"test")
            job={"id":"job2"}
            r.publish(job,{"status":"ok"})
            self.assertTrue(r.request("POST","/claim",{"id":"job2"})["ok"])
            claim=root/"claims"/"job2.json"
            old=time.time()-301
            os.utime(claim,(old,old))
            with patch.object(r,"notify") as notify:
                r.publish(job,{"status":"ok"})
                self.assertEqual(notify.call_args.args[0],"ack-job2")
                self.assertEqual(r.request("GET","/next",{}),{})
            r.request("POST","/ack",{"id":"job2","status":"clicked"})
            old=time.time()-5401
            os.utime(claim,(old,old))
            with patch.object(r,"notify") as notify:
                r.publish(job,{"status":"ok"})
                self.assertEqual(notify.call_args.args[0],"idle-job2")
                self.assertEqual(r.request("GET","/next",{}),{})

    def test_explicit_new_job_supersedes_unclaimed_delivery(self):
        import json
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def write(p,b):
                p.parent.mkdir(parents=True,exist_ok=True)
                with p.open("xb") as f:
                    f.write(b)
            r=Relay("a"*64,"kh827y/btc-lab-bridge",root,write,
                lambda o:json.dumps(o).encode(),lambda:"test")
            r.publish({"id":"old"},{"status":"ok"})
            self.assertTrue(r.pending("old"))
            self.assertFalse(r.pending("new"))
            self.assertEqual(r.request("GET","/next",{}),{})
            self.assertEqual(json.loads((root/"claims"/"old.json").read_text())["state"],"superseded")
            self.assertFalse(r.request("POST","/claim",{"id":"old"})["ok"])
            r.publish({"id":"old"},{"status":"ok"})
            self.assertFalse(r.pending())
            r.publish({"id":"new"},{"status":"ok"})
            self.assertEqual(r.request("GET","/next",{})["id"],"new")
