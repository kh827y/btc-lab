import unittest
from datetime import date
from research_buy import DAY,WEEK,days
from research_trend_break import weekly_states,episodes,availability,clusters,analyze


class TrendBreakTests(unittest.TestCase):
    def test_weekly_information_cutoff_and_gap(self):
        t=date(2020,3,2)
        first=t-51*DAY
        end=t+WEEK
        p={d:(100,100,100,100,1) for d in days(first,end)}
        p[t-2*DAY]=(90,90,90,90,1)
        p[t-DAY]=(1000,1000,1000,1000,1)
        p[t]=(1000,1000,1000,1000,1)
        self.assertIs(weekly_states(p,first,end)[t],False)
        p[t-3*DAY]=(100,100,100,100,0)
        self.assertIsNone(weekly_states(p,first,end)[t])

    def test_gap_censors_and_does_not_create_false_break(self):
        t=date(2020,3,2)
        states={t+i*WEEK:v for i,v in enumerate([False,True,False,None,False,True,False,True,False])}
        rows,invalid,left=episodes(states)
        self.assertEqual(len(rows),3)
        self.assertEqual([r["status"] for r in rows],["gap_censored","recovered","end_censored"])
        self.assertEqual(rows[0]["gap"],t+3*WEEK)
        self.assertEqual(rows[1]["recovery"],t+7*WEEK)
        self.assertEqual(len(left),2)
        self.assertEqual(len(invalid),1)

    def test_terminal_and_censoring(self):
        t=date(2020,3,2)
        end=t+100*DAY
        p={d:(100,100,100,100,1) for d in days(t,end)}
        ep={"origin":t,"recovery":t+7*DAY,"gap":None}
        self.assertEqual(availability(p,ep,28,end)["recovery_vs_fixed7"],"same_as_fixed7")
        ep["recovery"]=t+14*DAY
        self.assertEqual(availability(p,ep,28,end)["recovery_vs_fixed7"],"later_than_fixed7")
        ep["recovery"]=t+28*DAY
        self.assertEqual(availability(p,ep,28,end)["recovery_vs_fixed7"],"cash")
        self.assertEqual(availability(p,ep,90,end)["wait_days"],28)
        ep["recovery"]=None
        ep["gap"]=t+14*DAY
        self.assertEqual(availability(p,ep,28,end)["status"],"signal_gap")
        self.assertEqual(availability(p,ep,90,t+90*DAY)["status"],"cutoff_censored")
        del p[t+3*DAY]
        self.assertEqual(availability(p,ep,28,end)["status"],"price_gap")

    def test_overlap_components(self):
        t=date(2020,3,2)
        result=clusters([t,t+28*DAY,t+56*DAY,t+91*DAY],28)
        self.assertEqual([r["origins"] for r in result],[3,1])

    def test_no_cross_is_not_an_episode(self):
        first=date(2020,1,1)
        end=first+100*DAY
        p={d:(100,100,100,100,1) for d in days(first,end)}
        result=analyze(p,first,end)
        self.assertEqual(result["episode_count"],0)
        self.assertFalse(result["horizons"]["28"]["minimum_variation_present"])
