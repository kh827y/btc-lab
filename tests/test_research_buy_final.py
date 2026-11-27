import json
import subprocess
import tempfile
import unittest
from datetime import date
from pathlib import Path
from unittest.mock import patch

import research_buy as base
import research_buy_risk as risk
import research_buy_audit as audit
from research_buy_final import (START,END,FROZEN,LOCK,OLD,VERSION,gate,run,
                                forecast_rows,evidence,primary_controls)


class FinalBuyTest(unittest.TestCase):
    def test_gate_precedes_price_read(self):
        with patch("research_buy_final.gate",side_effect=ValueError("locked")), \
             patch("research_buy_final.base.load_prefix") as load:
            with self.assertRaisesRegex(ValueError,"locked"):
                run()
            load.assert_not_called()

    def test_existing_development_guards(self):
        for fn,args in ((base.episodes,({}, {},START,END)),(risk.purchases,({}, {},END)),
                        (audit.collect,({}, {},END))):
            with self.assertRaises(ValueError):
                fn(*args)

    def test_completed_labels_only(self):
        t=START
        end=t+29*base.DAY
        p={t+i*base.DAY:(100.,110.,90.,105.,1.) for i in range(29)}
        m={"p_up":.5,"p_loss_15":.5,"quantiles":[-.1,0,.1],"variance":.01}
        sig={t:{"models":{"M0":m,"M1":m}}}
        ext={t:{"pred":{"M0":m,"M1":m}}}
        self.assertEqual(len(forecast_rows(p,sig,ext,t,end)[0]),1)
        self.assertEqual(len(forecast_rows(p,sig,ext,t,end-base.DAY)[0]),0)

    def test_orientation_not_significance(self):
        self.assertEqual(evidence(1.5,[.1,3]),"candidate_positive_not_confirmed")
        self.assertEqual(evidence(1.5,[-.1,3]),"inconclusive_or_small")
        self.assertEqual(evidence(.1,None),"insufficient_interval")

    def test_lock_rejects_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)
            def g(*a):
                return subprocess.check_output(["git",*a],cwd=p,stderr=subprocess.PIPE).decode().strip()
            g("init");g("config","user.name","test");g("config","user.email","test@example.invalid")
            blobs={}
            for name in FROZEN:
                (p/name).write_bytes(b"fixture\n")
                blobs[name]=g("hash-object",name)
            (p/LOCK).write_text(json.dumps({"protocol":VERSION,"input_hashes":base.HASHES,
                                 "development_report_hashes":OLD,"blobs":blobs}))
            g("add",".");g("commit","-m","fixture")
            self.assertEqual(gate(p)["blobs"],blobs)
            (p/"BUY_FINAL.md").write_text("changed")
            with self.assertRaisesRegex(ValueError,"Local frozen file changed"):
                gate(p)
