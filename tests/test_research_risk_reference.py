import unittest
from datetime import date
import numpy as np

from research_buy import DAY,DEV_END
from research_risk_reference import (START,EVAL_START,distributions,empirical_crps,
                                      replay,calibration,summarize)


class RiskReferenceTest(unittest.TestCase):
    def test_crps(self):
        self.assertAlmostEqual(empirical_crps([0.,2.],1.),.5)
        self.assertAlmostEqual(empirical_crps([0.,0.],2.),2.)
        self.assertAlmostEqual(empirical_crps([3.],3.),0.)

    def test_scaling(self):
        h=[{"sigma":.02,"log_return":.1,"log_worst":-.1,"variance":.0004} for _ in range(120)]
        d=distributions(h,.04)
        self.assertEqual(len(d["empirical_104"]["return"]),104)
        self.assertEqual(len(d["scaled_expanding"]["return"]),120)
        np.testing.assert_allclose(d["scaled_expanding"]["return"],.2)
        np.testing.assert_allclose(d["scaled_expanding"]["worst"],-.2)
        self.assertAlmostEqual(d["scaled_expanding"]["variance"],.0016)

    def test_calibration_boundaries(self):
        c=calibration([0.,.2,.4,.6,.8,1.],[0,0,1,0,1,1])
        self.assertEqual([b["n"] for b in c["bins"]],[1,1,1,1,2])
        self.assertAlmostEqual(c["actual_frequency"],.5)

    def test_maturity_and_future_independence(self):
        start=START-100*DAY;end=EVAL_START+120*DAY
        p={start+i*DAY:(100.,104.,96.,101.,1.) for i in range((end-start).days)}
        a,_=replay(p,28,end)
        self.assertTrue(a)
        t=date.fromisoformat(a[0]["date"])
        self.assertLessEqual(date.fromisoformat(a[0]["latest_train_origin"])+29*DAY,t-DAY)
        q=dict(p)
        q[t-DAY]=(100.,200.,50.,150.,1.) # Sunday excluded from state
        q[t+DAY]=(100.,200.,50.,150.,1.) # outcome changes, forecast must not
        b,_=replay(q,28,end)
        for m,x in a[0]["models"].items():
            self.assertEqual({k:v for k,v in x.items() if k!="scores"},
                             {k:v for k,v in b[0]["models"][m].items() if k!="scores"})
        self.assertEqual(summarize(a)["n"],len(a))

    def test_guard(self):
        with self.assertRaises(ValueError):
            replay({},28,DEV_END+DAY)
        with self.assertRaises(ValueError):
            replay({DEV_END:(1,1,1,1,1)},28)
        with self.assertRaises(ValueError):
            replay({},14)
