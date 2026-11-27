import io
import json
import unittest
import zipfile
from datetime import datetime,date,timezone
from pathlib import Path
from tempfile import TemporaryDirectory

from research_oi_readiness import fridays,parse_recent,run
from research_oi import parse_archive,name
from research_daily_usd import seconds
from binance_minute import digest


def archive(d,rows=None):
    if rows is None:
        rows=[("23:50:00",100,10000000),("23:55:00",110,11000000)]
    f=io.BytesIO()
    content="create_time,symbol,sum_open_interest,sum_open_interest_value\n"
    for stamp,q,v in rows:
        content+=f"{d} {stamp},BTCUSDT,{q},{v}\n"
    with zipfile.ZipFile(f,"w") as z:
        z.writestr(name(d)[:-4]+".csv",content)
    return f.getvalue()


class OIReadinessTest(unittest.TestCase):
    def test_latest_closed_friday(self):
        self.assertEqual(fridays(datetime(2026,11,27,23,59,tzinfo=timezone.utc))[-1],date(2026,11,20))
        self.assertEqual(fridays(datetime(2026,11,28,0,0,tzinfo=timezone.utc))[-1],date(2026,11,27))
        self.assertEqual(len(fridays(datetime(2026,11,29,tzinfo=timezone.utc))),14)

    def test_old_parser_parity(self):
        d=date(2023,11,24)
        raw=archive(d)
        self.assertEqual(parse_recent(raw,d),parse_archive(raw,d))
        self.assertEqual(parse_recent(raw,d)["quantity"],110)

    def test_conflict_no_fallback(self):
        d=date(2026,11,27)
        with self.assertRaisesRegex(ValueError,"Conflicting"):
            parse_recent(archive(d,[("23:50:00",100,10000000),("23:55:00",110,11000000),
                                    ("23:55:00",111,11100000)]),d)
        with self.assertRaises(ValueError):
            parse_recent(archive(d,[("23:40:00",100,10000000)]),d)

    def test_readiness_and_missing_last(self):
        now=datetime(2026,11,29,12,tzinfo=timezone.utc)
        dates=fridays(now);files={name(d):archive(d) for d in dates}
        prices=json.dumps({"data":{"pair":"BTC/USD","ohlc":[
            {"timestamp":str(seconds(d)),"open":"100000","high":"105000","low":"95000",
             "close":"100000","volume":"1"} for d in dates]}}).encode()
        def fetch(url,limit):
            fn=url.rsplit("/",1)[1]
            if fn.endswith(".CHECKSUM"):
                fn=fn[:-9]
                return (digest(files[fn])+" "+fn+"\n").encode()
            return files[fn]
        with TemporaryDirectory() as tmp:
            r=run(Path(tmp)/"full",fetcher=fetch,prices_fetcher=lambda *_:prices,clock=lambda:now,pause=lambda _:None)
            self.assertTrue(r["complete_14_fridays"])
            self.assertEqual(r["valid_count"],14)
            self.assertEqual(r["oi_relative_log"],0.)
            self.assertFalse(r["forecast_issued"])
            self.assertFalse(r["confirmation_authorized"])
            del files[name(dates[-1])]
            r=run(Path(tmp)/"missing",fetcher=fetch,prices_fetcher=lambda *_:prices,clock=lambda:now,pause=lambda _:None)
            self.assertFalse(r["complete_14_fridays"])
            self.assertEqual(r["valid_count"],13)
            self.assertIsNone(r["oi_relative_log"])
            self.assertEqual(r["entries"][-1]["status"],"unavailable")
