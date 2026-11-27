import unittest
from datetime import date
import numpy as np
from research_buy import DAY,WEEK,DEV_END,distributions
from research_buy_risk import schedule,features,replay
from research_buy_audit import evaluate,model_control,contiguous,rotations,collect

T=date(2020,1,6)

class AuditControlsTest(unittest.TestCase):
    def test_original_accounting(self):
        prices={T+i*DAY:(100+i,120+i,90+i,105+i,1.) for i in range(57)}
        u=np.array([[0,2,1,0,2,0,1,2]])
        a=schedule(prices,T,u[0])
        op=np.array([[prices[T+i*WEEK][0] for i in range(8)]])
        cl=np.array([[prices[T+i*DAY][3] for i in range(56)]+[prices[T+56*DAY][0]]])
        q,dd,w=evaluate(op,cl,u)
        self.assertAlmostEqual(q[0],a["btc"])
        self.assertAlmostEqual(dd[0],a["drawdown"])
        self.assertAlmostEqual(w[0],a["waiting_days"])

    def test_rotations_preserve_waiting_and_constant_price(self):
        n=60
        dates=[T+i*WEEK for i in range(n)]
        u=np.tile([1]*8,(n,1))
        u[::2]=[0,2,0,2,0,2,0,2]
        op=np.full((n,8),100.)
        cl=np.full((n,57),100.)
        a=model_control(dates,op,cl,u)
        b=model_control(dates,op,cl,u)
        self.assertEqual(a,b)
        self.assertAlmostEqual(a["actual_minus_mean_placebo_log_gain_pct"],0)
        self.assertAlmostEqual(a["actual_minus_placebo_drawdown_pp"],0)
        self.assertEqual(a["rotation_count"],35)
        self.assertEqual(list(rotations(n))[0],13)
        self.assertEqual(list(rotations(n))[-1],47)

    def test_gap_rejected(self):
        with self.assertRaises(ValueError):
            contiguous([T,T+2*WEEK])

    def test_m1_direction_identity(self):
        h=[{"sigma":.02,"y":{"log_return":r,"log_worst":-.1,"variance":.0004}}
           for r in (-.2,.1,.4)]
        p=distributions(h,.06)
        self.assertEqual(p["M0"]["p_up"],p["M1"]["p_up"])
        self.assertNotEqual(p["M0"]["p_loss_15"],p["M1"]["p_loss_15"])

    def test_last_available_day(self):
        p={T+i*DAY:(100.,110.,90.,105.,1.) for i in range(-200,2)}
        a=features(p,T)
        p[T-DAY]=(100.,900.,90.,900.,1.)
        p[T]=(100.,900.,90.,900.,1.)
        np.testing.assert_array_equal(a[1],features(p,T)[1])
        p[T-2*DAY]=(100.,900.,90.,900.,1.)
        self.assertFalse(np.array_equal(a[1],features(p,T)[1]))

    def test_final_guard(self):
        with self.assertRaises(ValueError):
            collect({}, {}, DEV_END+DAY)
