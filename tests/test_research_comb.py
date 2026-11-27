import unittest
from datetime import date
import numpy as np
from research_buy import DAY,WEEK,DEV_END
from research_comb import FIRST,EVAL_START,predict,replay,purchases
from research_fund import ms,STEP

class CombTest(unittest.TestCase):
    def test_constant_extra(self):
        h=[(np.array([i,0,0,0,.1,.2,.3]),{"up":i%2,"loss_15":int(i%3==0)}) for i in range(60)]
        p=predict(h,np.array([40,0,0,0,.1,.2,.3]))
        for k in ("up","loss_15"):
            self.assertAlmostEqual(p["L1"][k],p["L1_all"][k],places=8)

    def test_guard(self):
        with self.assertRaises(ValueError):
            replay({}, {}, {}, {}, DEV_END+DAY)
        with self.assertRaises(ValueError):
            purchases({}, {}, DEV_END+DAY)

    def test_boundary_and_prior_threshold(self):
        end=EVAL_START+100*DAY
        p={FIRST+i*DAY:(100.,110.,90.,105.,1.) for i in range(-200,(end-FIRST).days)}
        v={d:1.5 for d in p}
        oi={FIRST+i*WEEK:100. for i in range((end-FIRST).days//7+1)}
        funding={s:(s,.0001) for s in range(ms(FIRST),ms(end),STEP)}
        sig,a,_=replay(p,v,oi,funding,end)
        self.assertTrue(a)
        t=date.fromisoformat(a[0]["date"])
        prior=[s["pred"]["L1_all"]["loss_15"] for d,s in sig.items() if d<t]
        self.assertEqual(sig[t]["thresholds"]["L1_all"],float(np.quantile(prior[-104:],.8)) if len(prior)>=26 else None)
        v[t-2*DAY]=999.
        oi[t+4*DAY]=999.
        b,_,_=replay(p,v,oi,funding,end)
        self.assertEqual(sig[t],b[t])

    def test_purchase_uses_same_budget(self):
        t=EVAL_START;end=t+45*WEEK
        p={t+i*DAY:(100.,110.,90.,105.,1.) for i in range((end-t).days)}
        sig={}
        for i in range(45):
            sig[t+i*WEEK]={"state":{},"pred":{m:{"loss_15":.9 if i%3==0 else .1} for m in ("L1","L1_value","L1_deriv","L1_all")},
                          "thresholds":{m:.5 for m in ("L1","L1_value","L1_deriv","L1_all")}}
        r=purchases(p,sig,end)
        self.assertEqual(r["n"],37)
        self.assertAlmostEqual(r["rules"]["L1_all"]["geometric_gain_vs_dca_pct"],0.)
        self.assertAlmostEqual(r["rotations"]["L1_all"]["actual_minus_mean_placebo_log_gain_pct"],0.)
