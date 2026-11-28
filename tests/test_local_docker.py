import io
import zipfile
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


    def test_unit_tests_mount_only_code(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch.object(d,"ROOT",root):
                args=d.create_args("btc-lab-"+"a"*32,root/"code","sha256:"+"b"*64,"unit_tests")
                self.assertEqual(args.count("--mount"),1)
                self.assertIn("target=/app,readonly",args[args.index("--mount")+1])
                self.assertEqual(args[args.index("--network")+1],"none")
                self.assertIn("--read-only",args)
                self.assertEqual(args[-1],"/app/docker_unit_task.py")
                self.assertNotIn("-S",args)
                with self.assertRaises(ValueError):
                    d.create_args("btc-lab-"+"a"*32,root/"code","sha256:"+"b"*64,"shell")

    def test_exact_commit_archive_and_path_rejection(self):
        commit="a"*40
        prefix="btc-lab-"+commit+"/"
        def archive(extra=None):
            buf=io.BytesIO()
            with zipfile.ZipFile(buf,"w") as z:
                z.writestr(prefix+"docker_unit_task.py","pass")
                z.writestr(prefix+"tests/test_example.py","pass")
                if extra is not None:
                    z.writestr(extra,"bad")
            return buf.getvalue()
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch.object(d,"ROOT",root):
                code=root/"valid"
                code.mkdir()
                d.unpack_code(archive(),code,commit)
                self.assertTrue((code/"tests/test_example.py").is_file())
                for i,bad in enumerate(("../escape",prefix+"../escape",prefix+"CON.txt",prefix+"TESTS/TEST_EXAMPLE.py",prefix+".git/config")):
                    code=root/str(i)
                    code.mkdir()
                    with self.assertRaises(ValueError):
                        d.unpack_code(archive(bad),code,commit)
