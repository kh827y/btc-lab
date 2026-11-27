import json
import tempfile
import unittest
from datetime import date,timedelta
from pathlib import Path
from unittest.mock import Mock,patch

from research_daily_usd import (DAY,seconds,windows,page_url,parse_page,coverage,
                                cached_page,save_snapshot,cross_check)


class DailyUSDTest(unittest.TestCase):
    def setUp(self):
        self.a=date(2018,1,1)
        self.b=self.a+timedelta(days=3)
        self.t=seconds(self.a)

    def bitstamp(self,ts):
        return json.dumps({"data":{"pair":"BTC/USD","ohlc":[
            {"timestamp":str(t),"open":"100","high":"110","low":"90","close":"105","volume":"2"}
            for t in ts]}}).encode()

    def test_windows(self):
        self.assertEqual(list(windows(self.a,self.b,2)),[(self.a,self.a+timedelta(days=2)),
                          (self.a+timedelta(days=2),self.b)])
        self.assertIn("limit=3",page_url("bitstamp",self.a,self.b))
        self.assertIn("granularity=86400",page_url("coinbase",self.a,self.b))

    def test_missing_day_not_filled(self):
        rows,outside=parse_page(self.bitstamp([self.t,self.t+2*DAY]),"bitstamp",self.a,self.b)
        self.assertEqual(outside,0)
        self.assertEqual(coverage(rows,self.a,self.b)["missing_dates"],["2018-01-02"])
        self.assertEqual(rows[self.t],(100.,110.,90.,105.,2.))

    def test_coinbase_order_and_bounds(self):
        rows,outside=parse_page(json.dumps([[self.t+3*DAY,90,110,100,105,2],
              [self.t+DAY,90,110,100,105,2],[self.t,90,110,100,105,2]]).encode(),
              "coinbase",self.a,self.b)
        self.assertEqual(outside,1)
        self.assertEqual(len(rows),2)
        self.assertEqual(rows[self.t],(100.,110.,90.,105.,2.))

    def test_bad_data(self):
        for ts in ([self.t,self.t],[self.t+1],[]):
            with self.assertRaises(ValueError):
                parse_page(self.bitstamp(ts),"bitstamp",self.a,self.b)
        with self.assertRaises(ValueError):
            parse_page(json.dumps([[self.t,120,110,100,105,2]]).encode(),
                       "coinbase",self.a,self.b)

    def test_cache_and_immutable_csv(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            f=Mock(return_value=self.bitstamp([self.t]))
            with patch("research_daily_usd.time.sleep"):
                a,info=cached_page(root,"bitstamp",self.a,self.b,f)
                b,_=cached_page(root,"bitstamp",self.a,self.b,f)
            self.assertEqual(a,b)
            f.assert_called_once()
            p=next(root.rglob("*.json"))
            obj=json.loads(p.read_bytes());obj["raw"]="{}"
            p.write_text(json.dumps(obj))
            with self.assertRaisesRegex(ValueError,"Cache hash"):
                cached_page(root,"bitstamp",self.a,self.b,f)
            target=root/"test.csv"
            self.assertEqual(save_snapshot(target,b"a"),save_snapshot(target,b"a"))
            with self.assertRaisesRegex(ValueError,"refusing overwrite"):
                save_snapshot(target,b"b")

    def test_cross_check(self):
        a={self.t:(100,110,90,100,2)}
        b={self.t:(100,110,90,101,2)}
        self.assertAlmostEqual(cross_check(a,b)["median_abs_close_diff_pct"],1)
        self.assertIsNone(cross_check(a,{}))
