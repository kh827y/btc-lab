import unittest
from datetime import date
from research_early_usd import early_url, early_overlap, extreme_audit, START, STOP
from research_daily_usd import seconds


class EarlyHistoryTests(unittest.TestCase):
    def test_url_uses_explicit_utc_end(self):
        d=date(2011,8,19)
        url=early_url(START,d)
        self.assertIn("limit=1",url)
        self.assertIn("start="+str(seconds(START)),url)
        self.assertIn("end="+str(seconds(d)-1),url)
        with self.assertRaises(ValueError):
            early_url(START,STOP)

    def test_overlap_detects_low_change_without_close_change(self):
        d=date(2014,1,1)
        a=(100,110,90,105,1)
        b=(100,110,1,105,1)
        result=early_overlap({seconds(d):a},{d:b})
        self.assertEqual(result["common_days"],1)
        self.assertEqual(result["exact_matches"],0)
        self.assertEqual(result["different_rows"][0]["relative_close_diff"],0)

    def test_venue_anomaly_is_flagged_and_not_repaired(self):
        d=date(2017,3,25)
        e=date(2017,3,26)
        a=(1000,1100,900,1050,1)
        b=(1000,1100,.06,1050,1)
        bitstamp={d:a,e:a};coinbase={d:b,e:a}
        result=extreme_audit(bitstamp,coinbase)
        self.assertEqual(result["common_days"],2)
        self.assertEqual(result["flagged_days"],1)
        self.assertEqual(result["rows"][0]["coinbase_ohlcv"],b)
        self.assertIn("coinbase_low_vs_body",result["rows"][0]["flags"])
        self.assertEqual(coinbase[d],b)

    def test_shared_extreme_is_still_flagged(self):
        d=date(2017,3,25)
        a=(1000,1100,100,1050,1)
        result=extreme_audit({d:a},{d:a})
        self.assertEqual(result["flagged_days"],1)
        self.assertIn("bitstamp_low_vs_body",result["rows"][0]["flags"])
