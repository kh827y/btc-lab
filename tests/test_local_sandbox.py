import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import local_sandbox as s

class LocalSandboxTest(unittest.TestCase):
    def test_stage_only_fixed_sources_at_exact_main(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            control=root/"control"
            control.mkdir()
            (control/"guest_probe.py").write_bytes(b"trusted probe")
            job={"id":"one","task":"archive_check","commit":"a"*40}
            folder=root/"job"
            folder.mkdir()
            calls=[]
            def fetch(url,limit=0):
                calls.append(url)
                if url.endswith("/commits/main"):
                    return json.dumps({"sha":job["commit"]}).encode()
                return b"# source"
            with patch.object(s.probe,"ROOT",root):
                code=s.stage(job,folder,control,fetch)
                self.assertEqual({p.name for p in code.iterdir()},
                    {"sandbox_archive_task.py","binance_minute.py","sandbox_guest_probe.py","probe.cmd"})
                self.assertEqual((code/"sandbox_guest_probe.py").read_bytes(),b"trusted probe")
                self.assertEqual(len(calls),3)
                self.assertTrue(all(job["commit"] in x for x in calls[1:]))
                with self.assertRaises(ValueError):
                    s.stage({**job,"commit":"b"*40},root/"bad",control,fetch)
                with self.assertRaises(ValueError):
                    s.stage({**job,"task":"powershell"},root/"bad",control,fetch)

    def test_report_limit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            p=root/"report.json"
            p.write_bytes(b"123456")
            with patch.object(s.probe,"ROOT",root):
                self.assertEqual(s.small(p,6),b"123456")
                with self.assertRaises(ValueError):
                    s.small(p,5)
