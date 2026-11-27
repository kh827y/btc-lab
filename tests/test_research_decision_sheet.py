import math
import unittest
from research_decision_sheet import context,PEAK_START,risk_range
from research_buy import DAY

class DecisionSheetTest(unittest.TestCase):
    def test_peak_and_trend(self):
        t=PEAK_START+201*DAY
        p={PEAK_START+i*DAY:(100.,100.,100.,100.,1.) for i in range(200)}
        p[t-2*DAY]=(70.,70.,70.,70.,1.)
        c=context(p,t)
        self.assertEqual(c["bin"],"20_to_40")
        self.assertAlmostEqual(c["depth"],.3)
        self.assertGreater(c["ma50"],c["close"])
        p[t-DAY]=(100.,100.,100.,100.,1.)
        with self.assertRaises(ValueError):
            context(p,t)
    def test_return_units(self):
        self.assertEqual(risk_range({"r":[math.log(.8),0,math.log(1.2)]},"r"),"-20.0% / +0.0% / +20.0%")
        with self.assertRaises(ValueError):
            risk_range({"r":[0,-1,1]},"r")
