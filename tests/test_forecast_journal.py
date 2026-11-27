import json
import tempfile
import unittest
from pathlib import Path
from datetime import datetime,timezone

from forecast_journal import (DAY, HORIZONS, TIME_URL, empirical, issue, realized,
                              settle, score_model, parse_prices)


def rows(start,n):
    return [[start+i*DAY,"100","110","90","105","1",start+(i+1)*DAY-1,
             "100",1,".5","50","0"] for i in range(n)]


class JournalTest(unittest.TestCase):
    def test_endpoint_and_missing(self):
        p={i*DAY:(100+i,120,80,105) for i in range(8)}
        p[7*DAY]=(107,120,1,105)
        y=realized(p,0,7)
        self.assertAlmostEqual(y["return"],.07)
        self.assertAlmostEqual(y["worst_from_entry"],-.2)
        del p[2*DAY]
        self.assertIsNone(realized(p,0,7))

    def test_completed_history_only(self):
        p={i*DAY:(100,110,90,105) for i in range(1000)}
        m=empirical(p,0,1000*DAY,90)
        self.assertEqual(m["n"],910)
        self.assertEqual(m["return_quantiles"]["0.5"],0)
        self.assertLess(m["p_up"],.01)

    def test_issue_duplicate_and_settle(self):
        now=[int(datetime(2026,11,29,12,tzinfo=timezone.utc).timestamp()*1000)]
        def fetch(url,params=None):
            if url==TIME_URL:return {"serverTime":now[0]}
            return rows(params["startTime"],params["limit"])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            p=issue(root,fetch)
            raw=p.read_bytes()
            f=json.loads(raw)
            self.assertEqual(f["origin_utc"],"2026-11-30T00:00:00+00:00")
            self.assertTrue(f["weekly_schedule"])
            self.assertEqual(issue(root,fetch),p)
            self.assertEqual(p.read_bytes(),raw)
            self.assertEqual(settle(root,fetch),0)
            now[0]=f["origin_ms"]+8*DAY
            self.assertEqual(settle(root,fetch),1)
            self.assertEqual(settle(root,fetch),0)
            self.assertTrue((p.parent/"outcome_7d.json").exists())
            self.assertFalse((p.parent/"outcome_28d.json").exists())
            self.assertEqual(p.read_bytes(),raw)

    def test_invalid_ohlc(self):
        r=rows(0,1)
        r[0][3]="120"
        with self.assertRaises(ValueError):
            parse_prices(r,0,DAY)

    def test_scores(self):
        m={"p_up":.8,"p_loss_15":.2,"return_quantiles":{"0.1":-.1,"0.5":0,"0.9":.1},
           "daily_log_vol":.03}
        y={"up":1,"loss_15":0,"return":.05,"daily_log_vol":.02}
        s=score_model(m,y)
        self.assertAlmostEqual(s["brier_up"],.04)
        self.assertEqual(s["interval_10_90_hit"],1)
        self.assertAlmostEqual(s["pinball"]["0.5"],.025)
