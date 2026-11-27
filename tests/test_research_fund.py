import io
import unittest
import zipfile
from datetime import date
import numpy as np
from research_buy import DAY,DEV_END
from research_fund import START,EVAL_START,STEP,ms,month_name,parse_archive,funding_feature,predict,replay

def archive(a,lines):
    b=io.BytesIO()
    with zipfile.ZipFile(b,"w") as z:
        z.writestr(month_name(a)[:-4]+".csv","calc_time,funding_interval_hours,last_funding_rate\n"+lines)
    return b.getvalue()

class FundTest(unittest.TestCase):
    def test_archive(self):
        a=START;b=date(2020,2,1);t=ms(a)
        raw=archive(a,f"{t+1},8,0.0001\n{t+STEP},4,-0.0001\n")
        v,bad=parse_archive(raw,a,b)
        self.assertEqual(v,{t:(t+1,.0001)})
        self.assertEqual(len(bad),1)
        with self.assertRaises(ValueError):
            parse_archive(archive(a,f"{t},8,0.001\n{t+1},8,0.001\n"),a,b)

    def test_complete_week_and_cutoff(self):
        t=EVAL_START;end=ms(t-DAY)
        v={s:(s+1,.0001) for s in range(end-21*STEP,end,STEP)}
        v[end]=(end,.5)
        self.assertAlmostEqual(funding_feature(v,t),.0001)
        del v[end-STEP]
        self.assertIsNone(funding_feature(v,t))
        v[end-STEP]=(end,.0001)
        self.assertIsNone(funding_feature(v,t))

    def test_constant(self):
        h=[(np.array([i,0,0,0,.0001]),{"up":i%2,"loss_15":int(i%3==0)}) for i in range(60)]
        p=predict(h,np.array([40,0,0,0,.0001]))
        for k in ("up","loss_15"):
            self.assertAlmostEqual(p["L1"][k],p["L1_fund"][k],places=8)

    def test_guard(self):
        with self.assertRaises(ValueError):
            replay({}, {}, DEV_END+DAY)

    def test_future_independence(self):
        end=EVAL_START+100*DAY
        p={START+i*DAY:(100.,110.,90.,105.,1.) for i in range(-200,(end-START).days)}
        v={s:(s,.0001) for s in range(ms(START),ms(end),STEP)}
        a,_=replay(p,v,end)
        cut=ms(EVAL_START-DAY)
        w={s:(s,.001 if s>=cut else rate) for s,(_,rate) in v.items()}
        b,_=replay(p,w,end)
        self.assertTrue(a)
        self.assertEqual(a[0],b[0])
