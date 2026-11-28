import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import sandbox_probe as p

class SandboxProbeTest(unittest.TestCase):
    def test_exact_readonly_mappings(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            with patch.object(p,"ROOT",root):
                dirs=[root/name for name in ("runtime","code","canary","archives","out")]
                xml=ET.fromstring(p.configuration(*dirs))
                self.assertEqual(xml.findtext("Networking"),"Disable")
                self.assertEqual(xml.findtext("ClipboardRedirection"),"Disable")
                self.assertEqual(xml.findtext("ProtectedClient"),"Enable")
                maps=xml.findall("MappedFolders/MappedFolder")
                self.assertEqual(len(maps),5)
                self.assertEqual([m.findtext("ReadOnly") for m in maps],["true","true","true","true","false"])
                self.assertEqual(maps[-1].findtext("HostFolder"),str(dirs[-1]))
                with self.assertRaises(ValueError):
                    p.under(root.parent/"outside")
                p.write(root/"new",b"probe")
                with self.assertRaises(FileExistsError):
                    p.write(root/"new",b"overwrite")

    def test_no_junction_or_symlink(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            original=root/"original"
            original.mkdir()
            link=root/"link"
            try:
                link.symlink_to(original,target_is_directory=True)
            except OSError:
                self.skipTest("Symlinks unsupported")
            with patch.object(p,"ROOT",root):
                with self.assertRaises(ValueError):
                    p.under(link/"child")
