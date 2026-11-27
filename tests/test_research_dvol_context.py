import json
import math
import tempfile
import unittest
from datetime import date,datetime,timezone
from research_dvol import ms
from research_dvol_context import context_record,snapshot,validate


class DVOLContextTests(unittest.TestCase):
    day=date(2026,11,27)
    now=datetime(2026,11,28,12,tzinfo=timezone.utc)

    def raw(self,rows=None,cursor=None):
        if rows is None:
            rows=[[ms(self.day),60,65,55,62]]
        return json.dumps({"jsonrpc":"2.0","result":{"data":rows,"continuation":cursor}}).encode()

    def test_units_and_time(self):
        r=context_record(self.raw(),self.day,self.now)
        self.assertEqual(r["annualized_percent"],62)
        self.assertAlmostEqual(r["implied_30d_log_vol_percent"],62*math.sqrt(30/365))
        with self.assertRaises(ValueError):
            context_record(self.raw(),self.day,datetime(2026,11,27,12,tzinfo=timezone.utc))

    def test_missing_or_future_data_rejected(self):
        for rows in ([],[[ms(date(2026,11,28)),60,65,55,62]],[[ms(self.day),.6,.65,.55,.62]]):
            with self.assertRaises(ValueError):
                validate(self.raw(rows),self.day)

    def test_cache_replay_no_network(self):
        with tempfile.TemporaryDirectory() as root:
            r=snapshot(self.day,root,lambda:self.now,lambda u,l:self.raw())
            def fail(*args):
                self.fail("Unexpected network request")
            self.assertEqual(snapshot(self.day,root,lambda:self.now,fail),r)
