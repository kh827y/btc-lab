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

    def test_cloud_exact_run(self):
        job={"id":"probe","commit":"a"*40,"task":"market_state"}
        run={"id":123,"head_sha":job["commit"],"head_branch":"main","event":"push",
             "path":".github/workflows/market_state_check.yml","status":"completed",
             "conclusion":"failure"}
        def fetch(url):
            self.assertIn(job["commit"],url)
            return json.dumps({"workflow_runs":[run]}).encode()
        self.assertEqual(r.cloud_result(job,fetch)["status"],"error")
        self.assertEqual(r.cloud_result(job,fetch)["run_id"],123)
        run["status"]="in_progress"
        self.assertIsNone(r.cloud_result(job,fetch))
        run["status"]="completed"
        run["head_sha"]="b"*40
        self.assertIsNone(r.cloud_result(job,fetch))

    def test_local_paths_and_collision(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch.object(r,"ROOT",root),patch.object(r,"CONTROL",root/"control"):
                f=root/"control"/"new.json"
                r.new_bytes(f,b"test")
                with self.assertRaises(FileExistsError):
                    r.new_bytes(f,b"overwrite")
                with self.assertRaises(ValueError):
                    r.safe_path(root.parent/"outside")
                job={"id":"probe","commit":"a"*40,"task":"market_state"}
                with patch.object(r,"remote_read",return_value={**job,"commit":"b"*40}):
                    with self.assertRaises(ValueError):
                        r.handle(job,{"repo":"kh827y/btc-lab-bridge"},"token")
