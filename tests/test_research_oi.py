import io
import unittest
import zipfile
from datetime import date
from research_buy import DAY,WEEK,DEV_END
from research_oi import FIRST,name,parse_archive,unit_check,oi_feature,replay

def archive(d,lines):
    b=io.BytesIO()
    with zipfile.ZipFile(b,"w") as z:
        z.writestr(name(d)[:-4]+".csv","create_time,symbol,sum_open_interest,sum_open_interest_value\n"+lines)
    return b.getvalue()

class OITest(unittest.TestCase):
    def test_timed_row(self):
        d=FIRST
        r=parse_archive(archive(d,f"{d} 12:00:00,BTCUSDT,1,100\n{d} 23:55:00,BTCUSDT,2,200\n"),d)
        self.assertEqual(r["quantity"],2)
        self.assertTrue(unit_check(r,(100,110,90,105,1)))
        self.assertFalse(unit_check(r,(1000,1100,900,1050,1)))

    def test_date_only_and_duplicate(self):
        d=FIRST
        self.assertIsNone(parse_archive(archive(d,f"{d},BTCUSDT,1,100\n"),d)["timestamp"])
        with self.assertRaises(ValueError):
            parse_archive(archive(d,f"{d} 23:55:00,BTCUSDT,1,100\n"*2),d)
        with self.assertRaises(ValueError):
            parse_archive(archive(d,f"{d+DAY} 00:00:00,BTCUSDT,1,100\n"),d)

    def test_exact_history(self):
        t=date(2022,4,4);d=t-3*DAY
        oi={d-i*WEEK:100. for i in range(14)}
        oi[d]=200.;oi[d+WEEK]=10000.
        self.assertAlmostEqual(oi_feature(oi,t),__import__("math").log(2))
        del oi[d-3*WEEK]
        self.assertIsNone(oi_feature(oi,t))

    def test_guard(self):
        with self.assertRaises(ValueError):
            replay({}, {}, {}, DEV_END+DAY)
