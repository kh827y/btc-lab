"""Host-only local API key file. Never expose to model tools."""
import argparse
import getpass
import os
import stat
import tempfile
import warnings
from pathlib import Path

ROOT=Path(__file__).resolve().parent
KEY_FILE=ROOT/"data"/".cheapvibecode_key"
MAX_KEY=2560

class CredentialError(ValueError):
    pass

def valid_key(key):
    if (type(key) is not str or not 0<len(key)<=MAX_KEY or not key.isascii()
            or not all(33<=ord(c)<=126 for c in key)):
        raise CredentialError("Invalid API key format.")
    return key

class ProjectVault:
    def __init__(self,root=ROOT):
        self.root=Path(root).resolve()
        self.path=self.root/"data"/".cheapvibecode_key"

    def check(self):
        p=self.path
        if p.parent.resolve()!=self.root/"data" or p.resolve()!=p:
            raise CredentialError("Credential path must not be redirected.")
        if p.exists() and not stat.S_ISREG(p.stat().st_mode):
            raise CredentialError("Invalid credential file.")

    def read(self):
        try:
            self.check()
            with self.path.open("rb") as f:
                raw=f.read(MAX_KEY+2)
            return valid_key(raw.decode("ascii").removesuffix("\n"))
        except FileNotFoundError:
            return None
        except (OSError,UnicodeError,RuntimeError):
            raise CredentialError("Cannot read local key file.") from None

    def write(self,key):
        raw=valid_key(key).encode("ascii")+b"\n"
        tmp=None
        try:
            self.check()
            self.path.parent.mkdir(parents=True,exist_ok=True)
            self.check()
            fd,name=tempfile.mkstemp(prefix=".key_",suffix=".tmp",dir=self.path.parent)
            tmp=Path(name)
            with os.fdopen(fd,"wb") as f:
                f.write(raw)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp,self.path)
        except (OSError,RuntimeError):
            raise CredentialError("Cannot save local key file.") from None
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)

    def delete(self):
        try:
            self.check()
            self.path.unlink()
            return True
        except FileNotFoundError:
            return False
        except (OSError,RuntimeError):
            raise CredentialError("Cannot remove local key file.") from None

def approve(message,*,ask=input):
    return ask(message+" [1=confirm / 0=cancel]: ").strip()=="1"

def hidden_prompt():
    with warnings.catch_warnings():
        warnings.simplefilter("error",getpass.GetPassWarning)
        try:
            return getpass.getpass("CheapVibeCode API key (hidden): ")
        except getpass.GetPassWarning:
            raise CredentialError("Hidden key input unavailable; use a normal terminal.") from None

def get_key(*,replace=False,vault=None,prompt=hidden_prompt,notify=print):
    """Only after local paid-run approval. No Windows credential access."""
    vault=ProjectVault() if vault is None else vault
    if not replace:
        saved=vault.read()
        if saved is not None:
            key=valid_key(saved)
            notify("Using saved local CheapVibeCode key.")
            return key
    notify("Key will be stored in plaintext in data/.cheapvibecode_key (Git ignored).")
    key=valid_key(prompt())
    vault.write(key)
    notify("Saved local key. Do not share or upload this file.")
    return key

def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--forget",action="store_true",required=True)
    p.parse_args()
    try:
        removed=ProjectVault().delete()
    except CredentialError as exc:
        p.exit(1,str(exc)+"\n")
    print("Local key removed." if removed else "No local key.")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
