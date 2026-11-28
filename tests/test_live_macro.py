import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from live_macro import parse, summarize, collect

DAY=date(2026,11,28)
NOW=datetime(2026,11,28,14,tzinfo=timezone.utc)

class LiveMacroTest(unittest.TestCase):
    def test_exact_series_and_date_validation(self):
        raw=b"observation_date,DGS2\n2026-11-20,3.80\n2026-11-27,3.90\n2026-11-28,.\n"
        p=summarize(parse(raw,"DGS2",DAY),"DGS2",DAY)
        self.assertEqual(p["value"],3.9)
        self.assertAlmostEqual(p["changes"]["7d"]["value"],0.1)
        self.assertEqual(p["changes"]["7d"]["unit"],"percentage_points")
        self.assertIsNone(p["changes"]["28d"]["value"])
        for bad in (raw.replace(b"DGS2",b"DGS10"),raw+b"2026-11-29,4\n",
                    raw+b"2026-11-28,4\n",raw.replace(b"3.90",b"nan")):
            with self.assertRaises(ValueError):
                parse(bad,"DGS2",DAY)

    def test_weekly_publication_and_stale(self):
        raw=b"DATE,DTWEXBGS\n2026-11-13,100\n2026-11-20,101\n"
        v=parse(raw,"DTWEXBGS",DAY)
        self.assertEqual(summarize(v,"DTWEXBGS",DAY)["status"],"usable")
        self.assertAlmostEqual(summarize(v,"DTWEXBGS",DAY)["changes"]["7d"]["value"],1)
        self.assertIsNone(summarize(v,"DTWEXBGS",date(2026,12,2))["value"])

    def test_same_series_alternate_and_missing(self):
        def fetch(url):
            q=parse_qs(urlsplit(url).query)
            s=q["id"][0]
            if s=="DGS10":
                raise OSError("offline")
            if s=="DGS2" and "vintage_date" not in q:
                raise OSError("primary unavailable")
            name=s+"_20261128" if "vintage_date" in q else s
            return ("DATE,"+name+"\n2026-11-27,4\n").encode()
        with tempfile.TemporaryDirectory() as tmp:
            r=collect(Path(tmp)/"macro",fetch,lambda:NOW)
            p={x["id"]:x for x in r["series"]}
            self.assertEqual(p["DGS2"]["source_kind"],"alfred_requested_current_vintage")
            self.assertEqual(len(p["DGS2"]["errors"]),1)
            self.assertEqual(p["DGS10"]["status"],"unavailable")
            self.assertEqual(len(p["DGS10"]["errors"]),2)
            self.assertTrue((Path(tmp)/"macro"/p["DGS2"]["raw_path"]).is_file())
