"""Owner-run update of installed bridge and rotation of its local pairing key."""
import ctypes
import json
import os
import secrets
import sys
import subprocess
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parent))
from local_runner import ROOT, CONTROL, safe_path, new_bytes, read_bytes, encoded, START_BAT
from local_docker import prepare_test_image

def main():
    if os.name!="nt" or Path.cwd()!=ROOT:
        raise ValueError("Run in the BTC-Lab folder on Windows")
    k=ctypes.windll.kernel32
    k.CreateMutexW.restype=ctypes.c_void_p
    k.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_wchar_p]
    k.CloseHandle.argtypes=[ctypes.c_void_p]
    h=k.CreateMutexW(None,False,"Local\\BTC-Lab-Local-Runner-v1")
    err=k.GetLastError()
    if not h or err==183:
        if h:
            k.CloseHandle(h)
        raise ValueError("Stop start.bat before updating the bridge")
    try:
        cfg=json.loads(read_bytes(CONTROL/"config.json",8192))
        if cfg.get("repo")!="kh827y/btc-lab-bridge":
            raise ValueError("Unexpected installed configuration")
        prepare_test_image(CONTROL)
        cfg["relay_key"]=secrets.token_hex(32)
        nonce=secrets.token_hex(8)
        files=[("local_relay.py",read_bytes(ROOT/"local_relay.py",128*1024)),
               ("controller.py",read_bytes(ROOT/"local_runner.py",128*1024)),
               ("local_docker.py",read_bytes(ROOT/"local_docker.py",128*1024)),
               ("start.bat",START_BAT),
               ("browser_bridge/worker.js",read_bytes(ROOT/"browser_bridge"/"worker.js",128*1024)),
               ("browser_bridge/popup.js",read_bytes(ROOT/"browser_bridge"/"popup.js",128*1024)),
               ("browser_bridge/popup.html",read_bytes(ROOT/"browser_bridge"/"popup.html",128*1024))]
        for name,raw in files:
            if name.endswith(".py"):
                compile(raw,name,"exec")
        backup=CONTROL/"bridge_backups"/nonce
        staged=[]
        for name,raw in files+[("config.json",encoded(cfg))]:
            dst=safe_path(CONTROL/name)
            previous=read_bytes(dst,128*1024)
            if name!="config.json":
                new_bytes(backup/name,previous)
            tmp=dst.with_name(dst.name+"."+nonce+".new")
            new_bytes(tmp,raw)
            staged.append((tmp,dst))
        for tmp,dst in staged:
            os.replace(safe_path(tmp),safe_path(dst))
        print("BRIDGE UPDATED. GitHub and Telegram credentials unchanged.")
        print("Reload the fixed Brave extension and bind this chat again.")
        print("New local pairing key (do not share):",cfg["relay_key"])
    finally:
        k.CloseHandle(h)

if __name__=="__main__":
    try:
        main()
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as e:
        print("STOP:",type(e).__name__,str(e)[:180])
        sys.exit(1)
