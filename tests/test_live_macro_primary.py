import json
import unittest
from datetime import date
from live_macro_primary import effr, treasury, broad

DAY=date(2026,11,28)

class PrimaryMacroTest(unittest.TestCase):
    def test_effr_exact_type_no_fill(self):
        row={"type":"EFFR","effectiveDate":"2026-11-25","percentRate":3.88}
        raw=lambda rows:json.dumps({"refRates":rows}).encode()
        self.assertEqual(effr(raw([row]),DAY),{date(2026,11,25):3.88})
        for rows in ([row,row],[dict(row,type="SOFR")],[dict(row,effectiveDate="2026-11-29")]):
            with self.assertRaises(ValueError):
                effr(raw(rows),DAY)

    def test_treasury_maturities(self):
        raw=b'''<feed xmlns="http://www.w3.org/2005/Atom" xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices" xmlns:m="http://schemas.microsoft.com/ado/2007/08/dataservices/metadata"><entry><content><m:properties><d:NEW_DATE>2026-11-27T00:00:00</d:NEW_DATE><d:BC_2YEAR>3.8</d:BC_2YEAR><d:BC_10YEAR>4.4</d:BC_10YEAR></m:properties></content></entry></feed>'''
        v=treasury(raw,2026,DAY)
        self.assertEqual(v["DGS2"],{date(2026,11,27):3.8})
        self.assertEqual(v["DGS10"],{date(2026,11,27):4.4})
        with self.assertRaises(ValueError):
            treasury(raw.replace(b"BC_2YEAR",b"BC_3YEAR"),2026,DAY)

    def test_broad_index_identity(self):
        raw=b'<h5>Nominal Broad Dollar Index - Daily Index</h5><table><tr><th>Date</th><th>Rate</th></tr><tr><td>20-NOV-26</td><td>121.5</td></tr></table>'
        self.assertEqual(broad(raw,DAY),{date(2026,11,20):121.5})
        with self.assertRaises(ValueError):
            broad(raw.replace(b"Broad",b"Advanced"),DAY)
        with self.assertRaises(ValueError):
            broad(raw.replace(b"20-NOV",b"29-NOV"),DAY)
