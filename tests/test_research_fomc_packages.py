import tempfile
import unittest
from pathlib import Path
from research_fomc_packages import extract,release,document,address

D="20230201"
BODY=("The Committee decided to raise the target range. "
      +"Economic conditions remain uncertain. "*10
      +"Voting for the monetary policy action were members.")

def statement(body=BODY):
    return ("<html><script>future data</script><p>February 01, 2023</p>"
            "<h3>Federal Reserve issues FOMC statement</h3>"
            "<p>For release at 2:00 p.m. EST</p><p>"+body+
            "</p><p>For media inquiries, contact us.</p><p>Later materials</p></html>").encode()


class FOMCPackageTests(unittest.TestCase):
    def test_extract_and_cutoff(self):
        self.assertEqual(extract(statement(),D,"statement"),BODY)
        self.assertEqual(release(D)[1],"2023-02-01T19:00:00+00:00")
        self.assertEqual(release("20230322")[1],"2023-03-22T18:00:00+00:00")
        with self.assertRaises(ValueError):
            extract(statement(),"20230322","statement")
        with self.assertRaises(ValueError):
            extract(statement().replace(b"EST",b"EDT"),D,"statement")

    def test_meeting_timing_only(self):
        raw=b"<p>FOMC Meeting Statement: PDF | HTML (Released February 01, 2023 at 2:00 p.m.)</p><p>Implementation Note (Released February 01, 2023 at 2:00 p.m.)</p><p>Later minutes</p>"
        x=extract(raw,D,"meeting")
        self.assertNotIn("Later minutes",str(x))
        with self.assertRaises(ValueError):
            extract(raw.replace(b"Implementation Note",b"Other note"),D,"meeting")

    def test_cache_replay(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            a=document(root,D,"statement",lambda url:statement())
            def fail(url):
                self.fail("Network not expected")
            self.assertEqual(a,document(root,D,"statement",fail))
            with self.assertRaises(ValueError):
                address("20240131","statement")
