import unittest
from unittest.mock import patch
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

from research_credentials import approve,get_key,valid_key,CredentialError,ProjectVault
import research_provider
import research_metadata


class Vault:
    def __init__(self,key=None):
        self.key=key
        self.writes=0
    def read(self):
        return self.key
    def write(self,key):
        self.key=key
        self.writes+=1


class CredentialTest(unittest.TestCase):
    def test_confirmation(self):
        for value in ("y","Y"," y "):
            self.assertTrue(approve("test",ask=lambda _:value))
        for value in ("","n","YES","yes","1"):
            self.assertFalse(approve("test",ask=lambda _:value))

    def test_first_save_and_reuse(self):
        v=Vault()
        messages=[]
        self.assertEqual(get_key(vault=v,prompt=lambda:"fake-key",notify=messages.append),"fake-key")
        self.assertEqual(v.writes,1)
        def never():
            self.fail("Prompted despite saved key")
        self.assertEqual(get_key(vault=v,prompt=never,notify=messages.append),"fake-key")
        self.assertEqual(v.writes,1)
        self.assertNotIn("fake-key"," ".join(messages))

    def test_replace(self):
        v=Vault("old-key")
        self.assertEqual(get_key(vault=v,replace=True,prompt=lambda:"new-key",notify=lambda _:None),"new-key")
        self.assertEqual(v.key,"new-key")
        self.assertEqual(v.writes,1)

    def test_bad_key_not_saved(self):
        for key in ("","with space","with\nnewline","ключ","x"*2561):
            v=Vault()
            with self.assertRaises(CredentialError):
                get_key(vault=v,prompt=lambda:key,notify=lambda _:None)
            self.assertEqual(v.writes,0)

    def test_project_storage_and_delete(self):
        with TemporaryDirectory() as tmp:
            v=ProjectVault(Path(tmp))
            self.assertIsNone(v.read())
            v.write("fake-key")
            self.assertEqual(v.read(),"fake-key")
            self.assertEqual(v.path.read_bytes(),b"fake-key\n")
            v.write("replacement")
            self.assertEqual(v.read(),"replacement")
            self.assertTrue(v.delete())
            self.assertFalse(v.delete())
            self.assertIsNone(v.read())

    def test_redirected_key_rejected(self):
        with TemporaryDirectory() as tmp:
            v=ProjectVault(Path(tmp))
            v.path.parent.mkdir()
            outside=Path(tmp)/"other"
            outside.write_text("secret")
            try:
                v.path.symlink_to(outside)
            except OSError:
                self.skipTest("Symlinks unavailable")
            with self.assertRaises(CredentialError):
                v.read()
            with self.assertRaises(CredentialError):
                v.write("fake-key")
            self.assertEqual(outside.read_text(),"secret")

    def test_decline_never_reads_credential(self):
        for module,flag in ((research_provider,"--live-smoke"),(research_metadata,"--live-review")):
            with patch.object(sys,"argv",["test",flag]), \
                 patch.object(module,"approve",return_value=False), \
                 patch.object(module,"get_key",side_effect=AssertionError("credential accessed")), \
                 patch.object(module,"CheapTransport",side_effect=AssertionError("network created")):
                with self.assertRaises(SystemExit) as ctx:
                    module.main()
                self.assertEqual(ctx.exception.code,0)
