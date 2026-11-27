import unittest
from datetime import date,timedelta
from research_cpi_calendar import parse,screen,summarize,RELEASES

class CalendarTest(unittest.TestCase):
    def test_parse_scope_and_coverage(self):
        # Synthetic monthly records across full years and December 2017.
        name=RELEASES[10][1]
        dates=["2017-12-12"]+[f"{y}-{m:02d}-12" for y in range(2018,2024) for m in range(1,13)]+["2024-01-12"]
        raw=("Release: "+name+"\nRelease Dates:\n-----\n"+"\n".join(dates)).encode()
        got,counts=parse(raw,10)
        self.assertEqual(len(got),73)
        self.assertEqual(counts[2018],12)
        with self.assertRaises(ValueError):
            parse(b"Release: Consumer Price Index\nRelease Dates:\n2018-01-01",10)

    def test_control_overlap_and_event_weight(self):
        f={"event_id":"x","release_time_utc":"2023-03-14T12:30:00Z",
           "standard_intraday_timing":"1","reaction_30m":".03",
           "prior_return_28d":".05","prior_vol_28d":".02"}
        controls=[{"event_id":"x","control_utc":t,"reaction_30m":v,
                   "prior_return_28d":".01","prior_vol_28d":".01"}
                  for t,v in [("2023-03-07T13:30:00Z",".01"),("2023-02-28T13:30:00Z",".01"),
                              ("2023-02-21T13:30:00Z","-.02"),("2023-02-14T13:30:00Z",".99")]]
        dates={date(2023,2,14):{"CPI"},date(2023,3,14):{"PPI"},date(2023,3,7):{"claims"}}
        rows,a=screen([f],controls,dates)
        self.assertEqual(a["surviving_count"],2)
        self.assertEqual(rows[0]["event_day_other_flags"],["PPI"])
        self.assertEqual(a["known_cpi_dates_absent_in_alfred"],["2023-03-14"])
        self.assertAlmostEqual(summarize(rows)["mean_abs_reaction_difference_pp"],1.5)
        self.assertEqual(summarize([]),{"events":0})
