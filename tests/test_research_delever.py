import unittest
from research_delever import select, day_features, summary, HOUR
from binance_minute import ms
from research_derivative_sources import FIRST


def make_day(day, price_ratio=1.0, oi_ratio=1.0, missing_oi=False, missing_price=False):
    base = ms(FIRST) + day*24*HOUR
    out = []
    for h in range(24):
        bar = {"open":100, "close":100*price_ratio if h==23 else 100,
               "low":min(100,100*price_ratio), "quote":1000,"signed_quote":-200}
        out.append({"hour_open_utc_ms":base+h*HOUR,
                    "spot":None if missing_price and h==0 else bar,
                    "perpetual":bar,"premium":{"open":0.001,"close":-0.001},
                    "oi_start":100, "oi_last_55":None if missing_oi else 100*oi_ratio})
    return out


class DeleverPreflightTest(unittest.TestCase):
    def test_price_trigger_spacing_missing_oi(self):
        rows = []
        for i in range(20):
            rows.extend(make_day(i,.94 if i in (0,1,7,14) else 1, .94, missing_oi=i==0))
        events, missing, counts = select(rows)
        self.assertEqual(len(events),3)
        self.assertEqual([r["group"] for r in events],["unknown","contraction","contraction"])
        self.assertEqual([r["calendar_eligible7"] for r in events],[True,True,False])
        self.assertEqual(events[1]["entry_utc_ms"]-events[0]["entry_utc_ms"],168*HOUR)
        self.assertFalse(missing)

    def test_gap_censors_next_six_days(self):
        rows = []
        for i in range(16):
            rows.extend(make_day(i,.94,missing_price=i==0))
        events,missing,counts=select(rows)
        self.assertEqual(len(events),2)
        self.assertEqual(events[0]["entry_utc_ms"],ms(FIRST)+(7*24+25)*HOUR)
        self.assertEqual(counts["unknown_eligible_days"],1)
        self.assertEqual(len(missing),1)

    def test_interior_missing_flow_and_prior_context(self):
        rows=make_day(28,.95,.95)
        rows[3]["spot"]=None
        f=day_features(rows,[1.0]*28)
        self.assertEqual(f["group"],"contraction")
        self.assertIsNone(f["spot_flow_share"])
        self.assertEqual(f["perpetual_flow_share"],-.2)
        self.assertEqual(f["prior28_log_intraday_sum"],0)
        self.assertEqual(f["valid_hours"]["spot"],23)
        self.assertIsNone(day_features(rows,[1.0]*27+[None])["prior28_log_intraday_sum"])

    def test_reporting_floor_not_authorization(self):
        events=[]
        for i in range(10):
            for oi in (.94,1.0):
                events.append({"shock_date":"2021-01-01","calendar_eligible7":True,
                               **day_features(make_day(i,.94,oi),[1.0]*28)})
        result=summary(events)
        self.assertTrue(result["reporting_floor_met"])
        self.assertFalse(result["outcomes_authorized"])
        self.assertFalse(summary(events[:-1])["reporting_floor_met"])
