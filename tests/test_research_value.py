import json
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from datetime import date
import numpy as np
from research_buy import DAY,DEV_END
from research_value import valuation,load_values,replay,predict,START

class ValueTest(unittest.TestCase):
    def test_lags(self):
        t=START
        v={t-3*DAY:2.,t-8*DAY:1.,t-2*DAY:99.}
        self.assertAlmostEqual(valuation(v,t),np.log(2))
        self.assertEqual(valuation(v,t,8),0.)
        del v[t-3*DAY]
        self.assertIsNone(valuation(v,t))

    def test_snapshot_filter(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/"mvrv.json"
            p.write_text(json.dumps({"schema":1,"source":"Kote Charts","chart":"mvrv",
                "series":{"mvrv":{"2023-12-30":2,"2023-12-31":0,"2024-01-01":"not parsed"}}}))
            values,info=load_values(p)
            self.assertEqual(values,{date(2023,12,30):2.})
            self.assertEqual(info["rejected"],["2023-12-31"])

    def test_constant_feature(self):
        h=[(np.array([i,0,0,0,.1]),{"up":i%2,"loss_15":int(i%3==0)}) for i in range(104)]
        r=predict(h,np.array([40,0,0,0,.1]))
        for k in ("up","loss_15"):
            self.assertAlmostEqual(r["L1"][k],r["L1_value"][k],places=8)

    def test_guard(self):
        with self.assertRaises(ValueError):
            replay({}, {},START,90,DEV_END+DAY)

    def test_future_value_not_used(self):
        first=date(2015,1,1);end=START+110*DAY
        p={first+i*DAY:(100.,110.,90.,105.,1.) for i in range((end-first).days)}
        v={d:1.5 for d in p}
        a,_=replay(p,v,first,90,end)
        v[START-2*DAY]=99.
        b,_=replay(p,v,first,90,end)
        self.assertTrue(a)
        self.assertEqual(a[0],b[0])
