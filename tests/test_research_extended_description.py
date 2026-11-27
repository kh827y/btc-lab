import unittest
from datetime import date
from research_extended_description import merge_same_venue, compact_summary


class ExtendedDescriptionTests(unittest.TestCase):
    def test_identical_overlap_only(self):
        d=date(2014,1,1)
        e=date(2014,1,2)
        p=date(2013,12,31)
        a=(100,110,90,105,1)
        self.assertEqual(merge_same_venue({p:a,d:a},{d:a,e:a},d,e),{p:a,d:a,e:a})
        with self.assertRaises(ValueError):
            merge_same_venue({p:a,d:a},{d:(100,110,1,105,1),e:a},d,e)
        with self.assertRaises(ValueError):
            merge_same_venue({p:a},{d:a,e:a},d,e)

    def test_empty_bin_is_safe(self):
        result=compact_summary([])
        self.assertEqual(result["n_weekly_origins"],0)
        self.assertEqual(result["horizons"]["90"]["n"],0)
