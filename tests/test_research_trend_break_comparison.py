import unittest
from datetime import date
from research_buy import DAY,days
from research_trend_break_comparison import simulate,schedules,compare,summarize


class TrendBreakComparisonTests(unittest.TestCase):
    def setUp(self):
        self.t=date(2020,3,2)
        self.p={d:(100,100,100,100,1) for d in days(self.t,self.t+29*DAY)}

    def test_two_contrast_paths_and_split(self):
        t=self.t
        for price,expected in ((80,(1,1.25,1.125)),(120,(1,100/120,.5+.5*100/120))):
            self.p[t+7*DAY]=(price,price,price,price,1)
            a=schedules(t,t+7*DAY)
            values=[simulate(self.p,t,28,a[k],fee=0) for k in ("immediate","fixed7","split")]
            for v,w in zip(values,expected):
                self.assertAlmostEqual(v["terminal_wealth"],w)
            self.assertAlmostEqual(simulate(self.p,t,28,a["recovery"],fee=0)["terminal_wealth"],expected[1])

    def test_fee_cash_and_terminal_exclusion(self):
        t=self.t
        self.p[t+28*DAY]=(100,1000,1,1,1)
        cash=simulate(self.p,t,28,{})
        self.assertEqual(cash["cash"],1)
        self.assertEqual(cash["btc_per_usd"],0)
        self.assertEqual(cash["worst_initial_intraday_pct"],0)
        v=simulate(self.p,t,28,{t:1})
        self.assertAlmostEqual(v["terminal_wealth"],.999)
        self.assertAlmostEqual(v["worst_initial_intraday_pct"],-.1)
        self.assertAlmostEqual(v["max_drawdown_open_close_pct"],-.1)
        with self.assertRaises(ValueError):
            simulate(self.p,t,28,{t+28*DAY:1})

    def test_low_only_affects_intraday_risk(self):
        t=self.t
        self.p[t+2*DAY]=(100,100,.06,100,1)
        a=schedules(t,t+7*DAY)
        v=simulate(self.p,t,28,a["immediate"],fee=0)
        self.assertAlmostEqual(v["worst_initial_intraday_pct"],-99.94)
        self.assertEqual(v["worst_initial_open_close_pct"],0)
        self.assertEqual(v["max_drawdown_open_close_pct"],0)
        self.assertEqual(simulate(self.p,t,28,a["fixed7"],fee=0)["worst_initial_intraday_pct"],0)

    def test_paired_summary_includes_cash_and_ties(self):
        t=self.t
        pre={"episodes":[{"origin":t.isoformat(),"horizons":{
            "28":{"status":"eligible","recovery_entry":(t+7*DAY).isoformat(),"recovery_vs_fixed7":"same_as_fixed7"},
            "90":{"status":"cutoff_censored"}}}]}
        rows=compare(self.p,pre)
        s=summarize(rows,28)
        self.assertEqual(s["rules"]["recovery"]["vs_fixed7"]["terminal_delta_pp"]["equal"],1)
        self.assertEqual(summarize(rows,90)["eligible"],0)
        pre["episodes"][0]["horizons"]["28"].update(recovery_entry=None,recovery_vs_fixed7="cash")
        s=summarize(compare(self.p,pre),28)
        self.assertEqual(s["rules"]["recovery"]["cash"]["median"],1)
        self.assertEqual(s["rules"]["recovery"]["btc_per_usd"]["median"],0)
        self.assertEqual(s["rules"]["recovery"]["vs_fixed7"]["terminal_delta_pp"]["better"],1)
