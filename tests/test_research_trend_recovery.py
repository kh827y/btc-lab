import unittest
from datetime import date
from research_buy import DAY
from research_trend_recovery import choose,analyze,evaluate_rule,THRESHOLD,H

FIRST=date(2020,1,1)

def bar(c,o=None,lo=None):
    o=c if o is None else o
    return (o,max(c,o),min(c,o) if lo is None else lo,c,1.)

def path(n=450):
    return {FIRST+i*DAY:bar(100+i*.01) for i in range(n)}

class TrendTest(unittest.TestCase):
    def test_trigger_wait_and_equal_terminal(self):
        p=path()
        d=FIRST+220*DAY
        peak=p[d-DAY][3]
        for i in range(20):
            p[d+i*DAY]=bar(peak*.75)
        for i in range(20,100):
            p[d+i*DAY]=bar(peak*.95)
        end=FIRST+450*DAY
        a=analyze(p,FIRST,end)
        rows=[r for r in a["episodes"] if r["status"]=="eligible"]
        self.assertEqual(len(rows),1)
        r=rows[0]
        self.assertEqual(r["trigger_date"],d.isoformat())
        base=r["rules"]["immediate"]
        self.assertEqual(base["entry_date"],(d+DAY).isoformat())
        self.assertEqual(base["terminal_wealth_delta_pct"],0)
        self.assertEqual(r["terminal_date"],(d+91*DAY).isoformat())
        m=r["rules"]["ma50"]
        self.assertEqual(m["status"],"bought")
        self.assertGreater(m["wait_days"],0)
        self.assertGreater(m["entry_vs_immediate_pct"],0)
        self.assertLess(m["terminal_wealth_delta_pct"],0)
        self.assertEqual(r["rules"]["ma200"]["status"],"cash_no_signal")
        self.assertEqual(r["rules"]["ma200"]["terminal_wealth"],1.)

    def test_already_above_and_gap(self):
        p=path()
        d=FIRST+220*DAY;t=d+91*DAY
        m=choose(p,d,t,50)
        self.assertTrue(m["already_above_at_trigger"])
        self.assertEqual(m["wait_days"],0)
        del p[d+DAY]
        self.assertEqual(choose(p,d,t,50)["status"],"censored")

    def test_no_future_signal_and_new_low_censor(self):
        p=path(330)
        d=FIRST+220*DAY
        p[d]=bar(75)
        p[d+DAY]=bar(76)
        t=d+91*DAY
        a=evaluate_rule(p,d,d,t,FIRST+330*DAY,None)
        self.assertFalse(a["post_entry_90"]["new_low"])
        self.assertTrue(a["post_entry_90"]["complete"])
        # A late entry can have a complete common endpoint but censored own follow-up.
        for i in range(1,70):
            p[d+i*DAY]=bar(70)
        p[d+70*DAY]=bar(99)
        a=evaluate_rule(p,d,d,t,FIRST+330*DAY,50)
        self.assertEqual(a["status"],"bought")
        self.assertFalse(a["post_entry_90"]["complete"])
        self.assertIsNone(a["post_entry_90"]["new_low"])
        self.assertIsNone(a["post_entry_90"]["worst_from_entry_pct"])

    def test_no_post_cutoff_and_censored_episode(self):
        p=path(260);d=FIRST+220*DAY;p[d]=bar(70)
        a=analyze(p,FIRST,FIRST+260*DAY)
        self.assertEqual(a["episodes"][0]["status"],"censored")
        with self.assertRaises(ValueError):
            analyze(p,FIRST,FIRST+259*DAY)
