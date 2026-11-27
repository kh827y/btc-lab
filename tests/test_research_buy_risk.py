import unittest
from datetime import date
import numpy as np
from research_buy import DAY,DEV_END
from research_buy_risk import features,logistic,schedule,replay,purchases

T=date(2020,1,6)
def prices(n=800):
    return {T+i*DAY:(100.,110.,90.,105.,1.) for i in range(-200,n)}

class RiskTest(unittest.TestCase):
    def test_features_cutoff(self):
        p=prices()
        s,x=features(p,T)
        p[T-DAY]=(100,900,90,900,1)
        p[T]=(100,900,90,900,1)
        self.assertEqual(s,features(p,T)[0])
        np.testing.assert_array_equal(x,features(p,T)[1])

    def test_logistic(self):
        x=np.arange(100.).reshape(-1,1)
        y=(x[:,0]>50).astype(float)
        self.assertGreater(logistic(x,y,[90]),logistic(x,y,[10]))
        self.assertTrue(0<logistic(np.zeros((52,1)),np.zeros(52),[0])<1)

    def test_schedule(self):
        p=prices()
        a=schedule(p,T,[1]*8)
        b=schedule(p,T,[.5]+[1]*6+[1.5])
        self.assertAlmostEqual(a["btc"],b["btc"])
        self.assertAlmostEqual(b["waiting_days"]-a["waiting_days"],3.0625)
        self.assertGreater(schedule(p,T,[1]*8,.05)["btc"],a["btc"])
        with self.assertRaises(ValueError):
            schedule(p,T,[0]*8)

    def test_final_guard(self):
        with self.assertRaises(ValueError):
            replay({},T,DEV_END+DAY)
        with self.assertRaises(ValueError):
            purchases({}, {},DEV_END+DAY)

    def test_future_independence(self):
        p=prices(700)
        cut=T+500*DAY
        a,_=replay(p,T,T+650*DAY)
        q={d:v if d<cut else (200.,210.,190.,205.,1.) for d,v in p.items()}
        b,_=replay(q,T,T+650*DAY)
        keys=[d for d in a if d<cut]
        self.assertTrue(keys)
        self.assertEqual({d:a[d] for d in keys},{d:b[d] for d in keys})
