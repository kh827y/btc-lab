import unittest
from unittest.mock import patch
from pathlib import Path
import numpy as np

from research_cpi_diagnostics import effect, bootstrap, leave_one_score, alternative_rows, delayed_rows, enriched
from research_prices import DAY
from binance_minute import MINUTE


def row(i,y=0.1,a=0.0,b=0.05):
    return {"id":str(i),"y":y,"predictions":{"market_after":a,"market_plus_cpi":b}}


class DiagnosticsTest(unittest.TestCase):
    def test_identical_predictions_zero_effect_and_interval(self):
        rows=[row(i,y=.03*i,a=-.01,b=-.01) for i in range(12)]
        e=effect(rows)
        for key in ("delta_rmse_pp","delta_mae_pp","delta_purchase_gain_pp"):
            self.assertAlmostEqual(e[key],0)
            self.assertEqual(bootstrap(rows,3,resamples=50)[key],[0.,0.])

    def test_paired_bootstrap_deterministic(self):
        rows=[row(i,y=(-1)**i*.1,a=0,b=.02*i) for i in range(12)]
        a=bootstrap(rows,3,resamples=100)
        self.assertEqual(a,bootstrap(rows,3,resamples=100))
        self.assertTrue(all(np.isfinite(v).all() and v[0]<=v[1] for v in a.values()))

    def test_purchase_gain_and_cost(self):
        rows=[row(1,y=-.2,a=.01,b=-.01)]
        self.assertAlmostEqual(effect(rows)["delta_purchase_gain_pp"],25.)
        self.assertAlmostEqual(effect(rows,50)["delta_purchase_gain_pp"],24.375)

    def test_leave_one_does_not_change_input(self):
        rows=[row(1),row(2,y=-.3)]
        r=leave_one_score(rows)
        self.assertEqual(r[0]["excluded_event_id"],"1")
        self.assertEqual(r[0]["n"],1)
        self.assertEqual(r[1]["delta_rmse_pp"],effect(rows[:1])["delta_rmse_pp"])
        self.assertEqual(len(rows),2)

    def test_alternatives_and_delayed_no_mutation(self):
        e={"x":[.1,.2,.3,.4],"alternatives":[-.1,.4],
           "entry":0,"delayed_entry":1410*MINUTE,"delayed_reaction":.5,"delayed_y":-.2}
        self.assertEqual(alternative_rows([e],min)[0]["x"][3],-.1)
        d=delayed_rows([e])[0]
        self.assertEqual(d["known"],1409*MINUTE)
        self.assertEqual(d["exit"],1410*MINUTE+7*DAY)
        self.assertEqual(d["x"][2],.5)
        self.assertEqual(e["x"],[.1,.2,.3,.4])

    def test_reject_final_before_read(self):
        with patch("research_cpi_diagnostics.read_table") as read:
            with self.assertRaisesRegex(ValueError,"Final test"):
                enriched(Path("."),"test",{})
            read.assert_not_called()
