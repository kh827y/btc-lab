import unittest
from datetime import datetime, timezone
import numpy as np
from binance_minute import MINUTE
from research_prices import DAY, MinutePrices
from research_cpi import split_name, bounded_outcome, prepare_event

class ResearchPricesTest(unittest.TestCase):
    def setUp(self):
        self.start = int(datetime(2021,1,1,tzinfo=timezone.utc).timestamp()*1000)
        self.stop = self.start+70*DAY
        self.x = np.full((70*1440,4),100.0)
        self.p = MinutePrices(self.start,self.stop,self.x)
        self.t = self.start+30*DAY+13*60*MINUTE

    def ix(self,t):
        return (t-self.start)//MINUTE

    def test_exact_reaction_no_future_leak(self):
        t=self.t
        self.x[self.ix(t+29*MINUTE),3]=110
        self.x[self.ix(t+30*MINUTE),3]=900
        self.assertAlmostEqual(self.p.reaction(t),0.1)
        self.x[self.ix(t+30*MINUTE):,3]=200
        self.assertAlmostEqual(self.p.reaction(t),0.1)
        self.x[self.ix(t+5*MINUTE)]=np.nan
        self.assertIsNone(self.p.reaction(t))

    def test_daily_state_uses_previous_utc_close(self):
        t=self.t
        midnight=t//DAY*DAY
        self.x[self.ix(midnight-MINUTE),3]=110
        self.x[self.ix(midnight):,3]=999
        r,v=self.p.prior_state(t)
        self.assertAlmostEqual(r,0.1)
        self.assertGreater(v,0)
        self.x[self.ix(midnight-DAY-MINUTE),3]=np.nan
        self.assertEqual(self.p.prior_state(t),(None,None))

    def test_gap_does_not_shift_exit(self):
        t=self.t
        self.x[self.ix(t+7*DAY),0]=110
        self.x[self.ix(t+3*DAY),2]=80
        r,w=self.p.outcome(t,7)
        self.assertAlmostEqual(r,0.1);self.assertAlmostEqual(w,-0.2)
        self.x[self.ix(t+DAY)]=np.nan
        r,w=self.p.outcome(t,7)
        self.assertAlmostEqual(r,0.1);self.assertIsNone(w)
        self.x[self.ix(t+7*DAY)]=np.nan
        self.assertEqual(self.p.outcome(t,7),(None,None))

    def test_boundary_and_dst(self):
        t=int(datetime(2021,12,26,tzinfo=timezone.utc).timestamp()*1000)
        self.assertEqual(bounded_outcome(self.p,t,7,"train"),(None,None))
        self.assertEqual(split_name(datetime(2024,1,1,tzinfo=timezone.utc)),"test")
        e={"event_id":"x","release_time_utc":"2024-03-12T12:30:00Z",
           "core_mom_surprise_pp":"0.0","headline_mom_surprise_pp":"0.0",
           "core_mom_first_pct":"0.3","core_mom_forecast_id":"f",
           "core_mom_forecast_within_24h":"1","standard_intraday_timing_and_pair":"1",
           "event_note":""}
        f,o,controls=prepare_event(e,[],self.p)
        self.assertEqual(f["core_mom_surprise_pp"],0.0)
        self.assertEqual(f["primary_standard_sample_eligible"],0)
        self.assertEqual(controls[0]["control_utc"],"2024-03-05T13:30:00+00:00")

if __name__=="__main__":
    unittest.main()
