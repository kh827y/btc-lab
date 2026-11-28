import copy
import unittest
from state_comparison import compare

def fixture():
    a={"assembled_utc":"2026-11-28T13:00:00Z","families":{"price":[
        {"id":"quote","status":"usable","value":100.0,"unit":"USDT/BTC",
         "scope":"Binance spot","source":"public Binance spot","source_field":"price",
         "comparison_key":None,"time_precision":"timestamp","observed_at":"2026-11-28T12:00:00Z"}]}}
    b=copy.deepcopy(a)
    b["assembled_utc"]="2026-11-28T14:00:00Z"
    b["families"]["price"][0].update(value=101.0,observed_at="2026-11-28T13:00:00Z")
    return a,b

class StateComparisonTest(unittest.TestCase):
    def test_new_observation(self):
        a,b=fixture()
        r=compare(a,b)["metrics"][0]
        self.assertEqual(r["status"],"new_observation")
        self.assertEqual(r["delta"],1.0)
        self.assertEqual(r["observation_gap_hours"],1.0)

    def test_repeat_revision_regression(self):
        for stamp,value,status in (("2026-11-28T12:00:00Z",100.0,"same_observation"),
             ("2026-11-28T12:00:00Z",101.0,"same_observation_revised"),
             ("2026-11-28T11:00:00Z",101.0,"observation_regressed")):
            a,b=fixture()
            b["families"]["price"][0].update(observed_at=stamp,value=value)
            r=compare(a,b)["metrics"][0]
            self.assertEqual(r["status"],status)
            self.assertIsNone(r["delta"])

    def test_incompatible_unavailable_and_order(self):
        for change,status in (({"comparison_key":"other"},"incompatible_identity"),
                              ({"source_field":"other"},"incompatible_identity"),
                              ({"status":"stale","value":None},"not_usable_in_both"),
                              ({"value":True},"invalid_value")):
            a,b=fixture()
            b["families"]["price"][0].update(change)
            r=compare(a,b)["metrics"][0]
            self.assertEqual(r["status"],status)
            self.assertIsNone(r["delta"])
        a,b=fixture()
        with self.assertRaises(ValueError):
            compare(b,a)
        b["families"]["price"].append(b["families"]["price"][0])
        with self.assertRaises(ValueError):
            compare(a,b)

    def test_date_only_and_new_metric(self):
        a,b=fixture()
        for p,day in ((a,"2026-11-26"),(b,"2026-11-27")):
            p["families"]["price"][0].update(time_precision="date_only",observed_at=day)
        b["families"]["new"]=[{"id":"new","status":"usable"}]
        r={x["id"]:x for x in compare(a,b)["metrics"]}
        self.assertEqual(r["quote"]["observation_gap_days"],1)
        self.assertIsNone(r["quote"]["observation_gap_hours"])
        self.assertEqual(r["new"]["status"],"metric_added_or_removed")

    def test_future_time(self):
        a,b=fixture()
        b["families"]["price"][0]["observed_at"]="2026-11-28T15:00:00Z"
        self.assertEqual(compare(a,b)["metrics"][0]["status"],"future_observation")
