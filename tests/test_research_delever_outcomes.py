import unittest
from research_delever_outcomes import measure, distribution, overlap, compare, HOUR


def bars(n):
    return [{"spot":{"open":100,"low":98}} for _ in range(n)]


class DeleverOutcomesTest(unittest.TestCase):
    def test_cost_and_risk(self):
        rows=bars(169)
        rows[168]["spot"]={"open":125,"low":1}
        rows[7]["spot"]["low"]=80
        x=measure(rows,0,7)
        self.assertAlmostEqual(x["wait_cost"],.25)
        self.assertAlmostEqual(x["worst_from_entry"],-.2)
        self.assertAlmostEqual(x["delayed_btc_relative"],.8)
        self.assertAlmostEqual(x["split_btc_relative"],.9)

    def test_terminal_open_in_risk_and_missing(self):
        rows=bars(169)
        rows[-1]["spot"]["open"]=75
        self.assertEqual(measure(rows,0,7)["worst_from_entry"],-.25)
        rows[3]["spot"]=None
        self.assertIsNone(measure(rows,0,7)["worst_from_entry"])
        self.assertEqual(measure(rows,0,7)["wait_cost"],-.25)
        rows[-1]["spot"]=None
        self.assertIsNone(measure(rows,0,7)["wait_cost"])
        self.assertFalse(measure(rows[:-1],0,7)["calendar_eligible"])

    def test_distribution_and_overlap(self):
        self.assertIsNone(distribution([None])["median"])
        self.assertEqual(distribution([1,None])["n"],1)
        self.assertEqual(distribution([-1,1])["share_positive"],.5)
        items=[{"entry_utc_ms":d*24*HOUR,"28":{"wait_cost":0}} for d in (0,7,35)]
        self.assertEqual(overlap(items,28)["overlapping_pairs"],1)
        self.assertEqual(overlap(items,28)["overlap_clusters"],2)

    def test_comparison_direction(self):
        rows=bars(673)
        rows[168]["spot"]["open"]=120
        a={"group":"contraction","entry_utc_ms":0,"7":measure(rows,0,7),"28":measure(rows,0,28)}
        # The second window starts at 120 and ends at 108 (-10%).
        rows[336]["spot"]["open"]=108
        b={"group":"other","entry_utc_ms":168*HOUR,"7":measure(rows,0,7),"28":measure(rows,0,28)}
        self.assertAlmostEqual(compare([a,b])["median_wait_cost_difference"]["7"],.3)
