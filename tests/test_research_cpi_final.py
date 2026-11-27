import unittest
import tempfile
import subprocess
from pathlib import Path
from unittest.mock import patch
import json

from research_cpi_final import gate, FROZEN_FILES, LOCK, mse_diagnostic, run
from research_cpi import CPI_HASH, PRICE_HASH


class FinalTest(unittest.TestCase):
    def test_gate_before_any_input(self):
        with patch("research_cpi_final.gate",side_effect=ValueError("locked")), \
             patch("research_cpi_final.read_cpi") as read:
            with self.assertRaisesRegex(ValueError,"locked"):
                run()
            read.assert_not_called()

    def test_mse_units(self):
        r={"y":.1,"predictions":{"market_after":0.,"market_plus_cpi":.1}}
        m=mse_diagnostic([r]*6)
        self.assertAlmostEqual(m["delta_mse_pp_squared"],-100.)
        for x in m["paired_95pct_intervals"].values():
            self.assertAlmostEqual(x[0],-100.)
            self.assertAlmostEqual(x[1],-100.)

    def test_committed_lock_and_local_edit(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            def git(*a):
                return subprocess.check_output(["git",*a],cwd=root,stderr=subprocess.PIPE).decode().strip()
            git("init")
            git("config","user.name","fixture")
            git("config","user.email","fixture@example.invalid")
            blobs={}
            for name in FROZEN_FILES:
                (root/name).write_bytes(b"fixture\n")
                blobs[name]=git("hash-object",name)
            (root/LOCK).write_text(json.dumps({"protocol":"CPI-001-final-v1",
                   "price_snapshot_sha256":PRICE_HASH,"cpi_sha256":CPI_HASH,"blobs":blobs}))
            git("add",".");git("commit","-m","fixture")
            self.assertEqual(gate(root)["frozen_blobs"],blobs)
            (root/"CPI_FINAL.md").write_text("changed")
            with self.assertRaisesRegex(ValueError,"Local frozen file changed"):
                gate(root)
