import unittest
from datetime import date,timedelta
from research_buy import (DAY,WEEK,state,outcome,allocation,simulate,weekly_signals,
                          episodes,DEV_END,distributions,stats)

T=date(2020,1,6)
def prices(n=250):
    return {T+i*DAY:(100.,110.,90.,105.,1.) for i in range(-100,n)}
def sig():
    return {"close":100.,"ma":{20:110.},"drawdown":-.25,
            "models":{"M1":{"p_loss_15":.9}},"thresholds":{.8:.5}}


class BuyTest(unittest.TestCase):
    def test_state_ignores_sunday_and_future(self):
        p=prices()
        a=state(p,T)
        p[T-DAY]=(100,900,90,900,1)
        p[T]=(100,900,90,900,1)
        self.assertEqual(a,state(p,T))
        p[T-2*DAY]=(100,900,90,900,1)
        self.assertNotEqual(a,state(p,T))

    def test_zero_volume_and_endpoint_low(self):
        p=prices()
        p[T+28*DAY]=(100,110,1,105,1)
        self.assertAlmostEqual(outcome(p,T)["log_worst"],__import__("math").log(.9))
        p[T+DAY]=(100,110,90,105,0)
        self.assertIsNone(outcome(p,T))

    def test_budget_and_deadline(self):
        p=prices();s={T+i*WEEK:sig() for i in range(8)}
        for rule in ("lump","dca","trend","dip","risk"):
            r=simulate(p,s,T,rule)
            self.assertAlmostEqual(r["btc"],.00999)
            self.assertEqual(sum(r["allocations"]),8)
            self.assertEqual(len(r["allocations"]),8)
        self.assertEqual(simulate(p,s,T,"risk")["allocations"],[0]*7+[8])
        self.assertEqual(simulate(p,s,T,"dip")["allocations"],[2]*4+[0]*4)
        self.assertEqual(simulate(p,s,T,"dca")["waiting_days"],24.5)

    def test_no_test_windows(self):
        with self.assertRaises(ValueError):
            episodes({}, {},T,DEV_END+DAY)
        with self.assertRaises(ValueError):
            weekly_signals({},T,DEV_END+DAY)

    def test_risk_scale(self):
        hist=[{"sigma":.02,"y":{"log_return":.1,"log_worst":-.1,"variance":.0004}}]*52
        r=distributions(hist,.04)
        self.assertGreater(r["M1"]["p_loss_15"],r["M0"]["p_loss_15"])
        self.assertAlmostEqual(r["M1"]["variance"],.0016)

    def test_future_changes_do_not_change_earlier_signals(self):
        p=prices(950)
        cut=T+500*DAY
        a,_=weekly_signals(p,T,T+800*DAY)
        p2={d:(v if d<cut else (200.,210.,190.,205.,1.)) for d,v in p.items()}
        b,_=weekly_signals(p2,T,T+800*DAY)
        early=[d for d in a if d<cut]
        self.assertTrue(early)
        self.assertEqual({d:a[d] for d in early},{d:b[d] for d in early})
