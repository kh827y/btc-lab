import json
import unittest
import math
from datetime import date
from research_buy import DAY,DEV_END
from research_dvol import START,ms,parse_page,compare,summarize

class DvolTest(unittest.TestCase):
    def raw(self,rows,cursor=None):
        return json.dumps({"jsonrpc":"2.0","result":{"data":rows,"continuation":cursor}}).encode()

    def test_daily_schema(self):
        a=START;b=a+2*DAY
        row=[ms(a),60,70,50,65]
        self.assertEqual(parse_page(self.raw([row]),a,b,ms(b)-1)[0][a],(60,70,50,65))
        for rows in ([row,row],[[ms(a)+1,60,70,50,65]],[[ms(b),60,70,50,65]],
                     [[ms(a),60,50,40,65]],[[ms(a),True,70,50,65]]):
            with self.assertRaises(ValueError):
                parse_page(self.raw(rows),a,b,ms(b)-1)
        with self.assertRaises(ValueError):
            parse_page(self.raw([row],ms(b)-1),a,b,ms(b)-1)

    def test_aligned_origin(self):
        t=date(2021,4,5);end=t+40*DAY
        p={t+i*DAY:(100.,110.,90.,105.,1.) for i in range(-100,40)}
        v={t-2*DAY:(60.,60.,60.,60.),t-DAY:(900.,900.,900.,900.)}
        rows,_=compare(p,v,end)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]["origin"],(t-DAY).isoformat())
        self.assertEqual(rows[0]["dvol_annual_pct"],60.)
        self.assertAlmostEqual(rows[0]["daily_variance"]["dvol"],.36/365)
        self.assertAlmostEqual(rows[0]["qlike"]["dvol"],math.log(.36/365))
        self.assertEqual(summarize(rows)["n"],1)
        with self.assertRaises(ValueError):
            compare(p,v,DEV_END+DAY)
