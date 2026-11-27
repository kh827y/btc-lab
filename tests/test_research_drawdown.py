import unittest
from datetime import date
from research_buy import DAY,DEV_END
from research_drawdown import group,peak_history,recovery,survival,portfolio,build_rows,START

def candle(c):
    return (c,c,c,c,1.)

class DrawdownTest(unittest.TestCase):
    def test_bins(self):
        for x,k in [(0,"0_to_10"),(.1,"10_to_20"),(.2,"20_to_40"),(.4,"40_to_60"),(.6,"60_plus")]:
            self.assertEqual(group(x),k)

    def test_episode_and_gap(self):
        d=START
        p={d+i*DAY:candle(c) for i,c in enumerate([100,80,70,100,90,80,100])}
        del p[d+5*DAY]
        s,e=peak_history(p,d,d+7*DAY)
        self.assertAlmostEqual(s[d+2*DAY]["depth"],.3)
        self.assertEqual(e[0]["status"],"recovered")
        self.assertEqual(e[1]["status"],"gap_censored")
        self.assertIsNone(s[d+6*DAY]["episode"])
        self.assertEqual(s[d+6*DAY]["peak"],100)

    def test_recovery_censor(self):
        d=START;p={d:candle(80),d+DAY:candle(90),d+2*DAY:candle(100)}
        self.assertEqual(recovery(p,d,100,d+3*DAY)["days"],3)
        self.assertFalse(recovery(p,d,100,d+2*DAY)["event"])
        del p[d+DAY]
        self.assertEqual(recovery(p,d,100,d+3*DAY),{"days":1,"event":False,"reason":"gap"})

    def test_survival(self):
        q=survival([{"days":1,"event":True},{"days":2,"event":False},{"days":3,"event":True}])
        self.assertEqual(q["median_days"],3)
        self.assertAlmostEqual(q["curve"][0]["unrecovered_fraction"],2/3)
        self.assertEqual(q["recovered_by_day_km"]["90"],1.)
        self.assertIsNone(survival([{"days":1,"event":False}])["recovered_by_day_km"]["90"])

    def test_portfolio(self):
        d=START;p={d:candle(100),d+DAY:candle(50),d+2*DAY:candle(120)}
        r=portfolio(p,d,2,.5)
        self.assertAlmostEqual(r["terminal_return_pct"],9.94)
        self.assertAlmostEqual(r["worst_from_initial_pct"],-25.025)
        self.assertEqual(portfolio(p,d,2,0.)["portfolio_drawdown_pct"],0.)

    def test_decision_cutoff_and_tail(self):
        d=START;first=d-7*DAY;end=d+8*DAY
        p={first+i*DAY:candle(100) for i in range((end-first).days)}
        p[d-2*DAY]=candle(80);p[d-DAY]=candle(200)
        rows,_,_=build_rows(p,first,d,end)
        self.assertEqual(rows[0]["bin"],"20_to_40")
        self.assertEqual(rows[0]["peak"],100)
        self.assertIn("7",rows[0]["outcomes"])
        self.assertNotIn("28",rows[0]["outcomes"])
        with self.assertRaises(ValueError):
            build_rows(p,first,d,DEV_END+DAY)
