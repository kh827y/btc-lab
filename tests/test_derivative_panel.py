import unittest
from datetime import datetime, timezone, timedelta
from research_derivative_panel import oi_hour, join_hour, hidx
from research_derivative_sources import parse_metrics
from test_derivative_sources import archive, D, candle
from research_derivative_sources import parse_hours, ms, HOUR

class DerivativePanelTest(unittest.TestCase):
    def test_exact_oi_boundaries(self):
        t = datetime(2020, 9, 1, tzinfo=timezone.utc)
        stamp = int(t.timestamp()*1000)
        samples = {t:(10,1000), t+timedelta(minutes=50):(8,800),
                   t+timedelta(hours=1):(6,600)}
        r = oi_hour(samples, stamp)
        self.assertEqual(r["oi_start"], 10)
        self.assertIsNone(r["oi_last_55"])
        samples[t+timedelta(minutes=55)] = (7,700)
        self.assertEqual(oi_hour(samples, stamp)["oi_last_55"], 7)

    def test_samples_and_quality_are_consistent(self):
        fut = parse_hours(archive("klines",[candle(ms(D))]), "klines", D)
        rows = [["create_time","symbol","sum_open_interest","sum_open_interest_value"],
                ["2020-09-01 00:00:00","BTCUSDT",10,1000],
                ["2020-09-01 00:55:00","BTCUSDT",8,800],
                ["2020-09-01 00:55:00","BTCUSDT",9,900]]
        raw = archive("metrics", rows)
        q, samples = parse_metrics(raw,D,fut,include_samples=True)
        self.assertEqual(q,parse_metrics(raw,D,fut))
        self.assertEqual(q["conflicts"],1)
        self.assertEqual(len(samples),1)
        self.assertIsNone(oi_hour(samples,ms(D))["oi_last_55"])

    def test_missing_spot_is_not_zero(self):
        t=ms(D)
        i=hidx(datetime.fromtimestamp(t/1000,timezone.utc))
        r=join_hour(t,{"valid":[False]*(i+1)}, {}, {}, {})
        self.assertIsNone(r["spot"])
        self.assertIsNone(r["perpetual"])
        self.assertIsNone(r["premium"])
        self.assertIsNone(r["oi_start"])
