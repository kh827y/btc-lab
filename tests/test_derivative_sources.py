import csv
import io
import unittest
import zipfile
from datetime import date
from research_derivative_sources import source, parse_hours, parse_metrics, ms, HOUR

D = date(2020, 9, 1)


def archive(family, rows):
    _, name = source(family, D)
    stream = io.StringIO()
    csv.writer(stream).writerows(rows)
    raw = io.BytesIO()
    with zipfile.ZipFile(raw, "w") as z:
        z.writestr(name[:-4]+".csv", stream.getvalue())
    return raw.getvalue()


def candle(t, price=100, total=1000, buy=250):
    return [t, price, price+1, price-1, price, 10, t+HOUR-1, total, 5, 2, buy, 0]


class DerivativeSourcesTest(unittest.TestCase):
    def test_flow_and_gap(self):
        t = ms(D)
        raw = archive("klines", [candle(t), candle(t+2*HOUR, buy=750)])
        bars = parse_hours(raw, "klines", D)
        self.assertEqual(bars[t]["signed_quote"], -500)
        self.assertEqual(bars[t+2*HOUR]["signed_quote"], 500)
        self.assertNotIn(t+HOUR, bars)

    def test_invalid_flow_and_duplicates(self):
        t = ms(D)
        for rows in ([candle(t, buy=1001)], [candle(t), candle(t)], [candle(t+1)]):
            with self.assertRaises(ValueError):
                parse_hours(archive("klines", rows), "klines", D)

    def test_signed_premium(self):
        t = ms(D)
        row = [t, -.002, .001, -.003, -.001, 0, t+HOUR-1, 0, 0, 0, 0, 0]
        self.assertEqual(parse_hours(archive("premiumIndexKlines", [row]), "premiumIndexKlines", D)[t]["close"], -.001)

    def test_metrics_units_conflicts_and_date_only(self):
        t = ms(D)
        bars = parse_hours(archive("klines", [candle(t), candle(t+HOUR)]), "klines", D)
        header = ["create_time","symbol","sum_open_interest","sum_open_interest_value"]
        def row(stamp, quantity, value):
            return [stamp,"BTCUSDT",quantity,value]
        rows = [header, row("2020-09-01 00:00:00",10,1000),
                row("2020-09-01 00:00:00",10,1000),
                row("2020-09-01 00:05:00",10,1000),
                row("2020-09-01 00:05:00",20,2000),
                row("2020-09-01 01:00:00",10,100000),
                row("2020-09-01",10,1000)]
        result = parse_metrics(archive("metrics", rows), D, bars)
        self.assertEqual(result["valid_timed"], 1)
        self.assertEqual(result["duplicates"], 2)
        self.assertEqual(result["conflicts"], 1)
        self.assertEqual(result["rejected"], 2)
        self.assertEqual(result["unit_or_hour_mismatch"], 1)
        self.assertEqual(result["hours_covered"], 1)
