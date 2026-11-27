"""Host-only CheapVibeCode credential storage, Windows Credential Manager.

Never expose these functions as model tools. No plaintext file fallback.
"""
import argparse
import ctypes
from ctypes import wintypes as w
import getpass
import sys
import warnings

TARGET="BTC-Lab/CheapVibeCode"
CRED_TYPE_GENERIC=1
CRED_PERSIST_LOCAL_MACHINE=2
ERROR_NOT_FOUND=1168
MAX_KEY=2560  # CRED_MAX_CREDENTIAL_BLOB_SIZE on supported Windows versions.


class CredentialError(ValueError):
    pass


def valid_key(key):
    if (type(key) is not str or not 0<len(key)<=MAX_KEY or not key.isascii()
            or not all(33<=ord(c)<=126 for c in key)):
        raise CredentialError("Invalid API key format.")
    return key


class Credential(ctypes.Structure):
    _fields_=[
        ("Flags",w.DWORD),("Type",w.DWORD),("TargetName",w.LPWSTR),
        ("Comment",w.LPWSTR),("LastWritten",w.FILETIME),
        ("CredentialBlobSize",w.DWORD),("CredentialBlob",ctypes.POINTER(ctypes.c_ubyte)),
        ("Persist",w.DWORD),("AttributeCount",w.DWORD),("Attributes",ctypes.c_void_p),
        ("TargetAlias",w.LPWSTR),("UserName",w.LPWSTR),
    ]


class WindowsVault:
    def __init__(self):
        if sys.platform!="win32":
            raise CredentialError("Windows Credential Manager is unavailable on this OS.")
        try:
            lib=ctypes.WinDLL("Advapi32.dll",use_last_error=True)
            self.read_fn=lib.CredReadW
            self.read_fn.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD,ctypes.POINTER(ctypes.POINTER(Credential))]
            self.read_fn.restype=w.BOOL
            self.write_fn=lib.CredWriteW
            self.write_fn.argtypes=[ctypes.POINTER(Credential),w.DWORD]
            self.write_fn.restype=w.BOOL
            self.delete_fn=lib.CredDeleteW
            self.delete_fn.argtypes=[w.LPCWSTR,w.DWORD,w.DWORD]
            self.delete_fn.restype=w.BOOL
            self.free_fn=lib.CredFree
            self.free_fn.argtypes=[ctypes.c_void_p]
            self.free_fn.restype=None
        except (OSError,AttributeError):
            raise CredentialError("Cannot open Windows Credential Manager.") from None

    def read(self):
        ptr=ctypes.POINTER(Credential)()
        if not self.read_fn(TARGET,CRED_TYPE_GENERIC,0,ctypes.byref(ptr)):
            if ctypes.get_last_error()==ERROR_NOT_FOUND:
                return None
            raise CredentialError("Cannot read saved credential.")
        try:
            if not ptr or not 0<ptr.contents.CredentialBlobSize<=MAX_KEY or not ptr.contents.CredentialBlob:
                raise CredentialError("Invalid saved credential; replace it.")
            try:
                key=ctypes.string_at(ptr.contents.CredentialBlob,
                                     ptr.contents.CredentialBlobSize).decode("ascii")
            except UnicodeError:
                raise CredentialError("Invalid saved credential; replace it.") from None
            return valid_key(key)
        finally:
            if ptr:
                self.free_fn(ptr)

    def write(self,key):
        raw=valid_key(key).encode("ascii")
        blob=(ctypes.c_ubyte*len(raw)).from_buffer_copy(raw)
        cred=Credential()
        cred.Type=CRED_TYPE_GENERIC
        cred.TargetName=TARGET
        cred.CredentialBlobSize=len(raw)
        cred.CredentialBlob=ctypes.cast(blob,ctypes.POINTER(ctypes.c_ubyte))
        cred.Persist=CRED_PERSIST_LOCAL_MACHINE
        cred.UserName="CheapVibeCode"
        try:
            if not self.write_fn(ctypes.byref(cred),0):
                raise CredentialError("Cannot save credential in Windows.")
        finally:
            ctypes.memset(blob,0,len(raw))

    def delete(self):
        if self.delete_fn(TARGET,CRED_TYPE_GENERIC,0):
            return True
        if ctypes.get_last_error()==ERROR_NOT_FOUND:
            return False
        raise CredentialError("Cannot remove saved credential.")


def approve(message,*,ask=input):
    return ask(message+" [y/N]: ").strip().lower()=="y"


def hidden_prompt():
    with warnings.catch_warnings():
        warnings.simplefilter("error",getpass.GetPassWarning)
        try:
            return getpass.getpass("CheapVibeCode API key (hidden): ")
        except getpass.GetPassWarning:
            raise CredentialError("Hidden key input unavailable; use a normal terminal.") from None


def get_key(*,replace=False,vault=None,prompt=hidden_prompt,notify=print):
    """Called by the local CLI only after paid-run approval."""
    vault=WindowsVault() if vault is None else vault
    if not replace:
        saved=vault.read()
        if saved is not None:
            key=valid_key(saved)
            notify("Using saved CheapVibeCode credential.")
            return key
    key=valid_key(prompt())
    vault.write(key)
    notify("Saved in Windows Credential Manager.")
    return key


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--forget",action="store_true",required=True)
    p.parse_args()
    try:
        removed=WindowsVault().delete()
    except CredentialError as exc:
        p.exit(1,str(exc)+"\n")
    print("Saved credential removed." if removed else "No saved credential.")
    return 0


if __name__=="__main__":
    raise SystemExit(main())
