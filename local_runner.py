"""Fixed Windows relay for cloud checks. Never execute remote project code locally."""
import base64
import ctypes
import getpass
import json
import os
import re
import secrets
import stat
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, build_opener, HTTPRedirectHandler

# -I excludes the script directory. Only the explicitly installed peer module is used.
if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
from local_relay import Relay, configure_bot

ROOT = Path(r"D:\Проекты\btc-lab")
CONTROL = ROOT / "data" / "local_runner"
OFFICIAL = "kh827y/btc-lab"
TASKS = {"market_state"}
WORKFLOW = "market_state_check.yml"
MAX_OUTPUT = 16 * 1024 * 1024
MAX_REPORT = 256 * 1024
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
SHA = re.compile(r"[0-9a-f]{40}")
REPO = re.compile(r"kh827y/btc-lab-bridge", re.I)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


OPENER = build_opener(NoRedirect())


def utc():
    return datetime.now(timezone.utc).isoformat()


def safe_path(path):
    """Reject symlinks, Windows junctions and all paths outside the fixed root."""
    path = Path(path)
    if path != ROOT and ROOT not in path.parents:
        raise ValueError("Path outside BTC-Lab")
    if not path.is_absolute() or ".." in path.parts:
        raise ValueError("Invalid local path")
    for p in [*reversed(path.parents), path]:
        try:
            s = p.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(s.st_mode) or getattr(s, "st_file_attributes", 0) & 0x400:
            raise ValueError("Symlink or junction is not allowed")
    return path


def new_bytes(path, raw):
    path = safe_path(path)
    safe_path(path.parent).mkdir(parents=True, exist_ok=True)
    with safe_path(path).open("xb") as f:
        f.write(raw)


def read_bytes(path, limit=MAX_OUTPUT):
    with safe_path(path).open("rb") as f:
        raw = f.read(limit+1)
    if len(raw)>limit:
        raise ValueError("Local file exceeds size limit")
    return raw


def encoded(obj):
    return (json.dumps(obj, ensure_ascii=False, indent=2, allow_nan=False)+"\n").encode("utf-8")


def dpapi(raw, decrypt=False):
    """Windows current-user DPAPI, no plaintext token file."""
    class Blob(ctypes.Structure):
        _fields_ = [("cbData", ctypes.c_ulong), ("pbData", ctypes.POINTER(ctypes.c_ubyte))]
    buf = (ctypes.c_ubyte * len(raw)).from_buffer_copy(raw)
    source = Blob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    dest = Blob()
    fn = ctypes.windll.crypt32.CryptUnprotectData if decrypt else ctypes.windll.crypt32.CryptProtectData
    if not fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(dest)):
        raise OSError("Windows DPAPI failed")
    free = ctypes.windll.kernel32.LocalFree
    free.argtypes = [ctypes.c_void_p]
    free.restype = ctypes.c_void_p
    try:
        return ctypes.string_at(dest.pbData,dest.cbData)
    finally:
        free(ctypes.cast(dest.pbData,ctypes.c_void_p))


def http(url, token=None, method="GET", body=None, limit=2*1024*1024):
    headers={"User-Agent":"BTC-Lab local runner","Accept":"application/vnd.github+json"}
    if token:
        if not url.startswith("https://api.github.com/repos/"):
            raise ValueError("Credential destination rejected")
        headers["Authorization"]="Bearer "+token
        headers["X-GitHub-Api-Version"]="2022-11-28"
    if body is not None:
        headers["Content-Type"]="application/json"
    req=Request(url, data=body, headers=headers, method=method)
    with OPENER.open(req,timeout=30) as r:
        raw=r.read(limit+1)
    if len(raw)>limit:
        raise ValueError("HTTP response exceeds limit")
    return raw


def private_repo(repo, token):
    if not REPO.fullmatch(repo) or repo.lower()==OFFICIAL:
        raise ValueError("Use a dedicated repository under kh827y, not BTC-Lab")
    info=json.loads(http("https://api.github.com/repos/"+repo,token))
    if info.get("private") is not True or info.get("full_name","").lower()!=repo.lower() or info.get("default_branch")!="main":
        raise ValueError("Mailbox must be PRIVATE and initialized with main")


def contents(repo, token, path):
    return "https://api.github.com/repos/"+repo+"/contents/"+path


def remote_read(repo, token, path):
    try:
        obj=json.loads(http(contents(repo,token,path)+"?ref=main",token))
    except HTTPError as exc:
        if exc.code==404:
            return None
        raise
    if obj.get("type")!="file" or obj.get("encoding")!="base64":
        raise ValueError("Mailbox entry is not a small regular file")
    raw=base64.b64decode(obj["content"].replace("\n",""),validate=True)
    if len(raw)>MAX_REPORT*2:
        raise ValueError("Mailbox file too large")
    return json.loads(raw)


def remote_create(repo, token, path, obj):
    private_repo(repo,token)
    existing=remote_read(repo,token,path)
    if existing is not None:
        if existing != obj:
            raise ValueError("Remote result already exists with different content")
        return
    body=encoded({"message":"Local runner result: "+path,
                  "content":base64.b64encode(encoded(obj)).decode("ascii"),"branch":"main"})
    http(contents(repo,token,path),token,"PUT",body)


def validate_job(job):
    if not isinstance(job,dict) or set(job)!={"id","commit","task"}:
        raise ValueError("Job must contain exactly id, commit and task")
    if not all(isinstance(job[k],str) for k in job):
        raise ValueError("Invalid job types")
    if not ID.fullmatch(job["id"]) or not SHA.fullmatch(job["commit"]) or job["task"] not in TASKS:
        raise ValueError("Job not on fixed allowlist")
    return job


def cloud_result(job, fetch=http):
    """Accept only completed push runs of the fixed workflow on official main."""
    url=("https://api.github.com/repos/"+OFFICIAL+"/actions/workflows/"+WORKFLOW+
         "/runs?event=push&branch=main&head_sha="+job["commit"]+"&per_page=20")
    doc=json.loads(fetch(url))
    runs=doc.get("workflow_runs")
    if not isinstance(runs,list):
        raise ValueError("Unexpected workflow response")
    matches=[x for x in runs if x.get("head_sha")==job["commit"]
             and x.get("head_branch")=="main" and x.get("event")=="push"
             and x.get("path","").split("@")[0]==".github/workflows/"+WORKFLOW]
    if not matches:
        return None
    run=max(matches,key=lambda x:x["id"])
    if run.get("status")!="completed":
        return None
    rid=run["id"]
    if type(rid) is not int or rid<=0:
        raise ValueError("Invalid run id")
    conclusion=run.get("conclusion")
    if not isinstance(conclusion,str):
        raise ValueError("Missing workflow conclusion")
    return {"version":"cloud-check-result-v1",**job,
            "status":"ok" if conclusion=="success" else "error",
            "conclusion":conclusion,"run_id":rid,
            "run_url":"https://github.com/"+OFFICIAL+"/actions/runs/"+str(rid),
            "finished_utc":run.get("updated_at"),
            "note":"Read workflow job logs and market-state artifact via GitHub. No local code executed."}


def handle(job,cfg,token,relay=None):
    job=validate_job(job)
    repo=cfg["repo"]
    result_path="results/"+job["id"]+".json"
    folder=safe_path(CONTROL/"jobs"/job["id"])
    local=folder/"result.json"
    existing=remote_read(repo,token,result_path)
    if existing is not None:
        if any(existing.get(k)!=v for k,v in job.items()):
            raise ValueError("Remote result ID collision")
        if relay and local.exists():
            if json.loads(read_bytes(local))!=existing:
                raise ValueError("Remote result differs from local")
            relay.publish(job,existing)
        return
    if local.exists():
        result=json.loads(read_bytes(local))
        if any(result.get(k)!=v for k,v in job.items()):
            raise ValueError("Local result ID collision")
    else:
        result=cloud_result(job)
        if result is None:
            return
        new_bytes(local,encoded(result))
    remote_create(repo,token,result_path,result)
    print("Cloud result:",job["id"],result["status"],flush=True)
    if relay:
        relay.publish(job,result)


def setup():
    safe_path(ROOT)
    if CONTROL.exists():
        raise ValueError("Controller already exists. Do not overwrite it automatically.")
    repo=input("Private mailbox repo (kh827y/btc-lab-bridge): ").strip()
    token=getpass.getpass("Fine-grained token for mailbox ONLY (hidden): ").strip()
    if not token.startswith("github_pat_"):
        raise ValueError("Use a fine-grained token, not a classic token")
    private_repo(repo,token)
    bot,chat=configure_bot(getpass.getpass)
    key=secrets.token_hex(32)
    CONTROL.mkdir(parents=True,exist_ok=False)
    new_bytes(CONTROL/"controller.py",Path(__file__).read_bytes())
    new_bytes(CONTROL/"local_relay.py",safe_path(ROOT/"local_relay.py").read_bytes())
    for name in ("manifest.json","popup.html","popup.js","worker.js"):
        new_bytes(CONTROL/"browser_bridge"/name,safe_path(ROOT/"browser_bridge"/name).read_bytes())
    new_bytes(CONTROL/"config.json",encoded({"repo":repo,"relay_key":key,"telegram_chat":chat}))
    new_bytes(CONTROL/"token.dpapi",dpapi(token.encode("utf-8")))
    if bot:
        new_bytes(CONTROL/"telegram.dpapi",dpapi(bot.encode("utf-8")))
    # This launcher is copied once into ignored local data and never auto-updated.
    new_bytes(CONTROL/"start.bat",b'@echo off\r\ncd /d "%~dp0..\\.."\r\n.venv\\Scripts\\python.exe -I "%~dp0controller.py" listen\r\npause\r\n')
    remote_create(repo,token,"ready.json",{"version":"cloud-relay-v1","status":"ready",
                  "tasks":list(TASKS),"created_utc":utc()})
    print("SETUP OK. Start data\\local_runner\\start.bat")
    print("Load unpacked in Brave:",CONTROL/"browser_bridge")
    print("Local extension pairing key (do not send to anyone):",key)


def listen():
    if Path(__file__).resolve()!=safe_path(CONTROL/"controller.py").resolve():
        raise ValueError("Start the fixed installed controller, not the Git version")
    cfg=json.loads(read_bytes(CONTROL/"config.json",8192))
    token=dpapi(read_bytes(CONTROL/"token.dpapi",8192),True).decode("utf-8")
    private_repo(cfg["repo"],token)
    # Single executor on Windows. No stale lock file after a crash.
    mutex=ctypes.windll.kernel32
    mutex.CreateMutexW.restype=ctypes.c_void_p
    mutex.CreateMutexW.argtypes=[ctypes.c_void_p,ctypes.c_int,ctypes.c_wchar_p]
    mutex.CloseHandle.argtypes=[ctypes.c_void_p]
    lock=mutex.CreateMutexW(None,False,"Local\\BTC-Lab-Local-Runner-v1")
    if not lock or mutex.GetLastError()==183:
        raise ValueError("Another executor is running")
    bot_path=CONTROL/"telegram.dpapi"
    bot=dpapi(read_bytes(bot_path,8192),True).decode("utf-8") if bot_path.exists() else None
    relay=Relay(cfg["relay_key"],cfg["repo"],CONTROL,new_bytes,encoded,utc,bot,cfg.get("telegram_chat"))
    server=relay.start()
    print("Listening for cloud results. No remote code runs on this PC. Ctrl+C stops polling.",flush=True)
    try:
        while True:
            try:
                private_repo(cfg["repo"],token)
                attention=relay.progress(remote_read(cfg["repo"],token,"progress.json"))
                if not attention and not relay.pending():
                    job=remote_read(cfg["repo"],token,"job.json")
                    if job is not None:
                        handle(job,cfg,token,relay)
            except (OSError,ValueError,KeyError,TypeError) as exc:
                print("Poll stopped for this iteration:",type(exc).__name__,str(exc)[:180],flush=True)
            time.sleep(90)
    finally:
        server.shutdown()
        server.server_close()
        mutex.CloseHandle(lock)


if __name__=="__main__":
    try:
        if os.name!="nt" or Path.cwd()!=ROOT:
            raise ValueError("Run from D:\\Проекты\\btc-lab on Windows")
        if sys.argv[1:]==["setup"]:
            setup()
        elif sys.argv[1:]==["listen"]:
            listen()
        else:
            raise ValueError("Expected setup or listen")
    except KeyboardInterrupt:
        print("Stopped.")
    except (OSError,ValueError,KeyError,TypeError) as exc:
        print("STOP:",type(exc).__name__,str(exc)[:300])
        sys.exit(1)
