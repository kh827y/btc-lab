import unittest
from datetime import date
import numpy as np
from research_buy import DAY,DEV_END
from research_flow import START,millis,parse_page,imbalance,replay,fit,score

T=date(2019,1,7)

def candle(d,total="100",buy="60"):
    t=millis(d)
    return [t,"100","110","90","105","1",t+86400000-1,total,10,".6",buy,"0"]

class FlowTest(unittest.TestCase):
    def test_flow_and_missing(self):
        a=T-8*DAY;b=T-DAY
        rows=[candle(a+i*DAY) for i in range(7)]
        flow,bad=parse_page(rows,a,b)
        self.assertEqual(bad,{})
        self.assertAlmostEqual(imbalance(flow,T),.2)
        flow[T-DAY]=(100,0)
        self.assertAlmostEqual(imbalance(flow,T),.2)
        del flow[a]
        self.assertIsNone(imbalance(flow,T))

    def test_weighted_not_daily_average(self):
        p={T-i*DAY:(100.,50.) for i in range(2,9)}
        p[T-2*DAY]=(1000.,1000.)
        self.assertAlmostEqual(imbalance(p,T),1000/1600)

    def test_bad_candle_and_duplicate(self):
        d=T-8*DAY
        p,bad=parse_page([candle(d,"100","101")],d,d+DAY)
        self.assertFalse(p)
        self.assertIn(d.isoformat(),bad)
        with self.assertRaises(ValueError):
            parse_page([candle(d),candle(d)],d,d+DAY)

    def test_guard(self):
        with self.assertRaises(ValueError):
            replay({}, {}, DEV_END+DAY)
        with self.assertRaises(ValueError):
            parse_page([],DEV_END,DEV_END+DAY)

    def test_constant_feature_no_change(self):
        h=[(np.array([i,0,0,0,.1]),{"up":i%2,"loss_15":int(i%3==0)}) for i in range(60)]
        r=fit(h,np.array([40,0,0,0,.1]))
        for k in ("up","loss_15"):
            self.assertAlmostEqual(r["L1"][k],r["L1_flow"][k],places=8)
            self.assertAlmostEqual(r["M2"][k],r["M2_flow"][k],places=8)

    def test_future_independence(self):
        end=T+100*DAY
        prices={START+i*DAY:(100.,110.,90.,105.,1.) for i in range((end-START).days)}
        flow={d:(100.,60.) for d in prices}
        a,_=replay(prices,flow,end)
        cut=T+21*DAY
        f={d:(v if d<cut else (100.,0.)) for d,v in flow.items()}
        b,_=replay(prices,f,end)
        aa=[r for r in a if r["date"]<=cut.isoformat()]
        bb=[r for r in b if r["date"]<=cut.isoformat()]
        self.assertTrue(aa)
        self.assertEqual(aa,bb)
