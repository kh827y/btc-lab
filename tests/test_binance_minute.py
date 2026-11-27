import hashlib
import io
import tempfile
import unittest
import zipfile
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import Mock

from binance_minute import (MINUTE, download, ensure_archive, filename, inspect,
                            iter_klines, ms, periods, expected_hash)

DAY = date(2024, 1, 1)
NEXT = DAY + timedelta(days=1)
LABEL = DAY.isoformat()


def candle(t, micro=False):
    close = t + MINUTE - 1
    if micro:
        t, close = t * 1000, close * 1000 + 999
    return ",".join(map(str, [t, 10, 12, 9, 11, 2, close, 20, 3, 1, 10, 0]))


def archive(rows, label=LABEL):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(filename(label).replace(".zip", ".csv"), "\n".join(rows)+"\n")
    return buf.getvalue()


class TestMinuteArchives(unittest.TestCase):
    def test_exact_microsecond_conversion_and_gap(self):
        raw = archive([candle(ms(DAY), True), candle(ms(DAY)+2*MINUTE)])
        rows = list(iter_klines(raw,LABEL,DAY,NEXT))
        self.assertEqual(int(rows[0][6]), ms(DAY)+MINUTE-1)
        result = inspect(raw,LABEL,DAY,NEXT)
        self.assertEqual(result["rows"],2)
        self.assertEqual(result["missing"],1438)
        self.assertEqual(result["gaps_utc_ms"][0], [ms(DAY)+MINUTE,ms(DAY)+2*MINUTE])

    def test_reject_duplicate_order_date_invalid_ohlc(self):
        t = ms(DAY)
        cases = [[candle(t),candle(t)], [candle(t+MINUTE),candle(t)],
                 [candle(ms(NEXT))], [candle(t+1)], [candle(t).replace(",12,9,",",8,9,")],
                 [candle(t).replace(",20,3,",",NaN,3,")]]
        for rows in cases:
            with self.subTest(rows=rows), self.assertRaises(ValueError):
                inspect(archive(rows),LABEL,DAY,NEXT)

    def test_checksum_and_cache(self):
        raw = archive([candle(ms(DAY))])
        check = (hashlib.sha256(raw).hexdigest()+"  "+filename(LABEL)).encode()
        fetcher = Mock(side_effect=[check,raw])
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = ensure_archive(root,"daily",LABEL,DAY,NEXT,fetcher)
            self.assertFalse(first["cached"])
            self.assertTrue(ensure_archive(root,"daily",LABEL,DAY,NEXT,fetcher)["cached"])
            self.assertEqual(fetcher.call_count,2)
            with self.assertRaisesRegex(ValueError,"SHA-256"):
                ensure_archive(root,"daily",LABEL,DAY,NEXT,Mock(side_effect=[check,b"bad"]),True)
            self.assertEqual((root/"daily"/filename(LABEL)).read_bytes(),raw)
            with self.assertRaises(ValueError):
                expected_hash(check,"wrong.zip")

    def test_calendar_and_report(self):
        first = date(2017,8,17)
        self.assertEqual(list(periods(first,date(2017,9,2))),[
            ("monthly","2017-08",first,date(2017,9,1)),
            ("daily","2017-09-01",date(2017,9,1),date(2017,9,2))])
        with tempfile.TemporaryDirectory() as tmp:
            report = download(tmp,DAY,NEXT,Mock(side_effect=OSError("offline")))
            self.assertEqual(report["errors"],1)
            self.assertEqual(report["missing_or_unavailable"],1440)


if __name__ == "__main__":
    unittest.main()
