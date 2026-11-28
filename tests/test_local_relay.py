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
