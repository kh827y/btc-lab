import unittest
from datetime import date
import numpy as np
from research_buy import DAY,DEV_END
from research_macro import START,EVAL_START,parse,macro_feature,latest,predict,replay

class MacroTest(unittest.TestCase):
    def test_parse(self):
        a=START.isoformat();b=(START+DAY).isoformat()
        values,q=parse(f"observation_date,DFII10\n{a},-0.5\n{b},.\n".encode(),"DFII10")
        self.assertEqual(values,{START:-.5})
        self.assertEqual(q["missing_markers"],[b])
        self.assertFalse(q["coverage_gate"])
        for raw in (f"DATE,DFII10\n{a},1\n{a},2\n",
                    "DATE,DFII10\n2024-01-01,1\n","DATE,DFII10\n2018-01-01,1\n"):
            with self.assertRaises(ValueError):
                parse(raw.encode(),"DFII10")
        with self.assertRaises(ValueError):
            parse(f"DATE,DTWEXBGS\n{a},0\n".encode(),"DTWEXBGS")

    def test_cutoff_and_holiday(self):
        t=EVAL_START;a=t-10*DAY;b=a-28*DAY
        v={"DFII10":{a-DAY:1.,b:.5,a+DAY:999.},
           "DTWEXBGS":{a:110.,b-DAY:100.,a+DAY:999.}}
        np.testing.assert_allclose(macro_feature(v,t),[.5,np.log(1.1)])
        self.assertIsNone(macro_feature(v,t,17))
        self.assertIsNone(latest({a-5*DAY:1},a))

    def test_constant(self):
        h=[(np.array([i,0,0,0,.1,.2]),{"up":i%2,"loss_15":int(i%3==0)}) for i in range(60)]
        p=predict(h,np.array([40,0,0,0,.1,.2]))
        for k in ("up","loss_15"):
            self.assertAlmostEqual(p["L1"][k],p["L1_macro"][k],places=8)

    def test_guard(self):
        with self.assertRaises(ValueError):
            replay({}, {}, DEV_END+DAY)

    def test_future_independence(self):
        end=EVAL_START+100*DAY
        prices={START+i*DAY:(100.,110.,90.,105.,1.) for i in range(-200,(end-START).days)}
        data={s:{d:1. for d in prices if START<=d<end and d.weekday()<5}
              for s in ("DFII10","DTWEXBGS")}
        a,_=replay(prices,data,end)
        self.assertTrue(a)
        for v in data.values():
            for d in v:
                if d>EVAL_START-10*DAY:
                    v[d]=100.
        b,_=replay(prices,data,end)
        self.assertEqual(a[0],b[0])
