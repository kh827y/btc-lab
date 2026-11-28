import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import local_runner as r


class LocalRunnerTest(unittest.TestCase):
    def test_allowlist(self):
        job={"id":"probe-1","commit":"a"*40,"task":"market_state"}
        self.assertEqual(r.validate_job(job),job)
        for invalid in ({**job,"args":["cmd"]},{**job,"task":"powershell"},
                        {**job,"commit":"main"},{**job,"id":"../escape"}):
            with self.assertRaises(ValueError):
                r.validate_job(invalid)

    def test_bounded_output(self):
        report={"version":"market-state-v2","families":{}}
        name="state/20261128T113000123456Z/market_state.json"
        payload={name:base64.b64encode(r.encoded(report)).decode("ascii")}
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with patch.object(r,"ROOT",root):
                folder=root/"job"
                folder.mkdir()
                out,digest=r.unpack(b"log"+r.MARKER+json.dumps(payload).encode(),folder)
                self.assertEqual(out,report)
                self.assertEqual(len(digest),64)
                self.assertTrue((folder/"output"/name).is_file())
                with self.assertRaises(FileExistsError):
                    r.new_bytes(folder/"output"/name,b"overwrite")
                for path in ("../outside.json","state/../market_state.json","C:/escape.json"):
                    with self.assertRaises(ValueError):
                        r.unpack(r.MARKER+json.dumps({path:payload[name]}).encode(),folder)
                with self.assertRaises(ValueError):
                    r.safe_path(root.parent/"outside")

    def test_reject_existing_result_collision(self):
        job={"id":"probe","commit":"a"*40,"task":"market_state"}
        with patch.object(r,"remote_read",return_value={**job,"commit":"b"*40}):
            with self.assertRaises(ValueError):
                r.handle(job,{"repo":"kh827y/private"},"token")
