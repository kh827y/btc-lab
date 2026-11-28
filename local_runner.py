"""Owner-installed local controller. Never import or run downloaded Python on Windows."""
import base64
import ctypes
import getpass
import hashlib
import json
import os
import re
import secrets
import stat
import subprocess
import sys
import threading
import time
import uuid
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
DOCKER = Path(r"C:\Program Files\Docker\Docker\resources\bin\docker.exe")
IMAGE = "python:3.12-slim"
TASKS = {"market_state": ("market_state.py", "data_logic.py", "live_derivatives.py")}
MAX_OUTPUT = 16 * 1024 * 1024
MAX_REPORT = 256 * 1024
MARKER = b"\nBTC_LAB_RESULT_V1 "
ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
SHA = re.compile(r"[0-9a-f]{40}")
REPO = re.compile(r"kh827y/btc-lab-bridge", re.I)
STAMP = r"[0-9]{8}T[0-9]{12}Z"
OUTPUT_PATH = re.compile(r"state/"+STAMP+r"/(?:brief\.json|market_state\.json|binance_perpetual/"+STAMP+r"/(?:oi_[0-9]+\.json|mark\.json|premium\.json|derivatives_readiness\.json))")


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


def docker(*args, timeout=30):
    return subprocess.run([str(DOCKER),"--context","desktop-linux",*args],
        cwd=ROOT,check=True,capture_output=True,text=True,timeout=timeout).stdout.strip()


def local_docker():
    if not DOCKER.is_file():
        raise ValueError("Install Docker Desktop at its default location first")
    endpoint=docker("context","inspect","desktop-linux","--format","{{.Endpoints.docker.Host}}")
    if endpoint.lower()!="npipe:////./pipe/dockerdesktoplinuxengine":
        raise ValueError("Docker context is not the expected local Linux engine")
    if docker("version","--format","{{.Server.Os}}")!="linux":
        raise ValueError("Docker Desktop must run Linux containers")


# Only public, explicitly selected source files are staged. No git pull, no hooks,
# no existing worktree/data/venv/credentials are exposed to the container.
def stage(job, folder):
    compare=json.loads(http("https://api.github.com/repos/"+OFFICIAL+"/compare/"+job["commit"]+"...main",
                            limit=8*1024*1024))
    if compare.get("status") not in ("ahead","identical") or compare.get("merge_base_commit",{}).get("sha")!=job["commit"]:
        raise ValueError("Requested commit is not an ancestor of official main")
    code=folder/"code"
    safe_path(code).mkdir(exist_ok=False)
    for name in TASKS[job["task"]]:
        raw=http("https://raw.githubusercontent.com/"+OFFICIAL+"/"+job["commit"]+"/"+name,limit=256*1024)
        new_bytes(code/name,raw)
    return code


WRAPPER = r"""
import base64,json,sys
from pathlib import Path
sys.path.insert(0,"/app")
import market_state
market_state.run(root=Path("/scratch/state"))
files={}
total=0
for p in Path("/scratch/state").rglob("*"):
    if p.is_symlink():
        raise ValueError("Unexpected symlink")
    if p.is_file():
        raw=p.read_bytes()
        total+=len(raw)
        if total>10*1024*1024 or len(files)>=16:
            raise ValueError("Too much output")
        files[p.relative_to("/scratch").as_posix()]=base64.b64encode(raw).decode("ascii")
print("\nBTC_LAB_RESULT_V1 "+json.dumps(files,separators=(",",":")),flush=True)
"""


def container_run(code, image):
    local_docker()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}",image):
        raise ValueError("Expected pinned local Docker image")
    name="btc-lab-"+uuid.uuid4().hex
    cmd=[str(DOCKER),"--context","desktop-linux","run","--rm","--name",name,"--pull","never",
         "--read-only","--cap-drop","ALL","--security-opt","no-new-privileges",
         "--user","65534:65534","--pids-limit","64","--memory","384m","--cpus","1",
         "--log-driver","none","--network","bridge",
         "--tmpfs","/tmp:rw,noexec,nosuid,size=16m,mode=1777",
         "--tmpfs","/scratch:rw,noexec,nosuid,size=32m,mode=1777",
         "--mount","type=bind,source="+str(safe_path(code))+",target=/app,readonly",
         "--workdir","/app",image,"python","-I","-B","-u","-c",WRAPPER]
    p=subprocess.Popen(cmd,cwd=ROOT,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    buf=bytearray()
    overflow=threading.Event()
    def drain():
        while True:
            chunk=p.stdout.read(65536)
            if not chunk:
                return
            if len(buf)+len(chunk)>MAX_OUTPUT:
                overflow.set()
                return
            buf.extend(chunk)
    reader=threading.Thread(target=drain,daemon=True)
    reader.start()
    deadline=time.monotonic()+240
    try:
        while p.poll() is None:
            if overflow.is_set() or time.monotonic()>deadline:
                raise TimeoutError("Container exceeded output or time limit")
            time.sleep(.2)
        reader.join(5)
        if reader.is_alive() or overflow.is_set():
            raise ValueError("Container output exceeded limit")
        return p.returncode,bytes(buf)
    finally:
        if p.poll() is None:
            # Stop ONLY the unique container created by this invocation.
            try:
                docker("kill",name,timeout=15)
            except (OSError,subprocess.SubprocessError):
                pass
            p.kill()
            p.wait(timeout=10)
        p.stdout.close()


def unpack(raw, folder):
    log, marker, payload=raw.rpartition(MARKER)
    if not marker:
        raise ValueError("No result envelope")
    files=json.loads(payload)
    if not isinstance(files,dict) or not 1<=len(files)<=16:
        raise ValueError("Invalid result envelope")
    total=0
    decoded={}
    reports=[]
    for rel,b64 in files.items():
        if not isinstance(rel,str) or not OUTPUT_PATH.fullmatch(rel) or not isinstance(b64,str):
            raise ValueError("Unexpected output path")
        data=base64.b64decode(b64,validate=True)
        total+=len(data)
        if total>10*1024*1024:
            raise ValueError("Output limit exceeded")
        decoded[rel]=data
        if rel.endswith("/market_state.json"):
            reports.append(data)
    if len(reports)!=1 or len(reports[0])>MAX_REPORT:
        raise ValueError("Expected exactly one bounded market_state.json")
    report=json.loads(reports[0])
    if report.get("version") not in ("market-state-v1","market-state-v2") or not isinstance(report.get("families"),dict):
        raise ValueError("Unexpected market state schema")
    for rel,data in decoded.items():
        new_bytes(folder/"output"/rel,data)
    new_bytes(folder/"container.log",log[-65536:])
    return report,hashlib.sha256(reports[0]).hexdigest()


def execute(job, folder, image):
    result={"version":"local-runner-result-v1",**job,"started_utc":utc()}
    try:
        code=stage(job,folder)
        rc,raw=container_run(code,image)
        if rc!=0:
            new_bytes(folder/"container.log",raw[-65536:])
            result.update(status="error",stage="container",exit_code=rc,
                          log_tail=raw[-12000:].decode("utf-8","replace"))
        else:
            report,digest=unpack(raw,folder)
            result.update(status="ok",report=report,report_sha256=digest)
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
        # Host-side exceptions: never transmit tokens, full command lines or local files.
        result.update(status="error",stage="controller",error_type=type(exc).__name__,
                      http_status=exc.code if isinstance(exc,HTTPError) else None)
        print("Local error:",type(exc).__name__,str(exc)[:300],flush=True)
    result["finished_utc"]=utc()
    return result


def handle(job, cfg, token, relay=None):
    job=validate_job(job)
    repo=cfg["repo"]
    result_path="results/"+job["id"]+".json"
    existing=remote_read(repo,token,result_path)
    folder=safe_path(CONTROL/"jobs"/job["id"])
    local=folder/"result.json"
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
    elif folder.exists():
        # Crash/interruption: never rerun an already-started job automatically.
        result={"version":"local-runner-result-v1",**job,"status":"interrupted",
                "finished_utc":utc()}
        new_bytes(local,encoded(result))
    else:
        folder.mkdir(parents=True,exist_ok=False)
        print("Starting",job["id"],job["task"],job["commit"],flush=True)
        if relay:
            relay.notify("start-"+job["id"][:56],"🔧 BTC-Lab: запускаю "+job["task"]+".")
        result=execute(job,folder,cfg["image"])
        new_bytes(local,encoded(result))
    remote_create(repo,token,result_path,result)
    print("Uploaded",job["id"],result["status"],flush=True)
    if relay:
        relay.notify("done-"+job["id"][:56],("✅" if result["status"]=="ok" else "⚠️")+" BTC-Lab: "+job["task"]+" — "+result["status"]+".")
        relay.publish(job,result)


def setup():
    safe_path(ROOT)
    if CONTROL.exists():
        raise ValueError("Controller already exists. Do not overwrite it automatically.")
    local_docker()
    print("Preparing official Python image (one-time download).")
    docker("pull",IMAGE,timeout=600)
    image=docker("image","inspect",IMAGE,"--format","{{.Id}}")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}",image):
        raise ValueError("Unexpected image identity")
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
    new_bytes(CONTROL/"config.json",encoded({"repo":repo,"image":image,"relay_key":key,"telegram_chat":chat}))
    new_bytes(CONTROL/"token.dpapi",dpapi(token.encode("utf-8")))
    if bot:
        new_bytes(CONTROL/"telegram.dpapi",dpapi(bot.encode("utf-8")))
    # This launcher is copied once into ignored local data and never auto-updated.
    new_bytes(CONTROL/"start.bat",b'@echo off\r\ncd /d "%~dp0..\\.."\r\n.venv\\Scripts\\python.exe -I "%~dp0controller.py" listen\r\npause\r\n')
    remote_create(repo,token,"ready.json",{"version":"local-runner-v1","status":"ready",
                  "tasks":list(TASKS),"created_utc":utc()})
    print("SETUP OK. Start data\\local_runner\\start.bat")
    print("Load unpacked in Brave:",CONTROL/"browser_bridge")
    print("Local extension pairing key (do not send to anyone):",key)


def listen():
    if Path(__file__).resolve()!=safe_path(CONTROL/"controller.py").resolve():
        raise ValueError("Start the fixed installed controller, not the Git version")
    local_docker()
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
    print("Listening for approved jobs. Ctrl+C stops polling.",flush=True)
    relay.notify("listener-ready","✅ BTC-Lab: локальный исполнитель запущен.")
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
            time.sleep(30)
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
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
        print("STOP:",type(exc).__name__,str(exc)[:300])
        sys.exit(1)
