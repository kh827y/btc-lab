import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import local_docker as d

class LocalDockerTest(unittest.TestCase):
    def test_fixed_offline_readonly_mounts(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            archive=root/"data"/"binance_1m"
            code=root/"job"/"code"
            with patch.object(d,"ROOT",root),patch.object(d,"ARCHIVE",archive):
                args=d.create_args("btc-lab-"+"a"*32,code,"sha256:"+"b"*64)
                self.assertEqual(args[args.index("--network")+1],"none")
                self.assertIn("--read-only",args)
                self.assertEqual(args[args.index("--user")+1],"65534:65534")
                self.assertEqual(args.count("--mount"),2)
                self.assertTrue(all(args[i+1].endswith(",readonly") for i,v in enumerate(args) if v=="--mount"))
                self.assertNotIn("--privileged",args)
                with self.assertRaises(ValueError):
                    d.create_args("other-container",code,"sha256:"+"b"*64)
                with self.assertRaises(ValueError):
                    d.create_args("btc-lab-"+"a"*32,root.parent/"outside","sha256:"+"b"*64)
