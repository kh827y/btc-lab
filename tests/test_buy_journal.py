import unittest
from datetime import date,datetime,timezone
from pathlib import Path
from tempfile import TemporaryDirectory
import json
from research_buy import DAY,weekly_signals,build_signals
from research_buy_risk import replay,build_signals as extended
from buy_journal import origin_for,receipt_map,verify_record,VERSION,current

T=date(2020,1,6)
class JournalBuyTest(unittest.TestCase):
    def test_shared_paths(self):
        p={T+i*DAY:(100.,110.,90.,105.,1.) for i in range(-200,950)}
        end=T+800*DAY
        self.assertEqual(weekly_signals(p,T,end)[0],build_signals(p,T,end))
        self.assertEqual(replay(p,T,end)[0],extended(p,T,end))

    def test_sunday_only(self):
        self.assertEqual(origin_for(datetime(2026,11,29,12,tzinfo=timezone.utc)),date(2026,11,30))
        for d in (28,30):
            with self.assertRaises(ValueError):
                origin_for(datetime(2026,11,d,12,tzinfo=timezone.utc))
        with self.assertRaises(ValueError):
            origin_for(datetime(2026,11,29,23,51,tzinfo=timezone.utc))

    def test_deleted_anchored_record_rejected(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/"forecast.json"
            with self.assertRaises(FileNotFoundError):
                verify_record(p,date(2026,11,30),{"sha256":"0"*64})

    def test_duplicate_receipt(self):
        with TemporaryDirectory() as tmp:
            p=Path(tmp)/"ledger.json"
            r={"origin":"2026-11-30","sha256":"0"*64,"created_utc":"2026-11-29T12:00:00Z",
               "comment_url":"https://github.com/kh827y/btc-lab/issues/2#issuecomment-1"}
            p.write_text(json.dumps({"version":VERSION,"receipts":[r,r]}))
            with self.assertRaises(ValueError):
                receipt_map(p)

    def test_current_rejects_future(self):
        with self.assertRaises(ValueError):
            current({T-DAY:(100,110,90,105,1)},T)
