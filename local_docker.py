"""Fixed Windows controller for offline Docker jobs; no downloaded code on host."""
import hashlib
import json
import os
import re
import shutil
import stat
import subprocess
import threading
import time
import uuid
from pathlib import Path

ROOT=Path(r"D:\Проекты\btc-lab")
ARCHIVE=ROOT/"data"/"binance_1m"
DOCKER=Path(r"D:\Docker\resources\bin\docker.exe")
HOST="npipe:////./pipe/dockerDesktopLinuxEngine"
IMAGE="python:3.12-slim"
FILES=("docker_archive_task.py","binance_minute.py")
OFFICIAL="kh827y/btc-lab"
MAX_REPORT=128*1024
MIN_C=2*1024**3
MIN_D=512*1024**2
TIMEOUT=300

def under(path):
    p=Path(path)
    if not p.is_absolute() or ".." in p.parts or (p!=ROOT and ROOT not in p.parents):
        raise ValueError("Path outside work folder")
    for q in [*reversed(p.parents),p]:
        try:
            st=q.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(st.st_mode) or getattr(st,"st_file_attributes",0)&0x400:
            raise ValueError("Reparse point rejected")
    return p

def write(path,raw):
    with under(path).open("xb") as f:
        f.write(raw)

def space():
    if shutil.disk_usage("C:\\").free<MIN_C:
        raise ValueError("C: below 2 GiB free")
    if shutil.disk_usage(ROOT).free<MIN_D:
        raise ValueError("D: below 512 MiB free")

def check_tree(folder):
    if not under(folder).is_dir():
        raise ValueError("Expected archive folder")
    for current,dirs,files in os.walk(folder,followlinks=False):
        for n in dirs+files:
            under(Path(current)/n)

def command(*args):
    # No shell, no remote Docker context.
    return [str(DOCKER),"--host",HOST,*args]

def docker(*args,timeout=30):
    return subprocess.run(command(*args),cwd=ROOT,stdin=subprocess.DEVNULL,
        capture_output=True,check=True,timeout=timeout).stdout.decode("utf-8").strip()

def preflight():
    space()
    if not DOCKER.is_file():
        raise ValueError("Docker Desktop must be installed at D:\\Docker")
    if docker("version","--format","{{.Server.Os}}")!="linux":
        raise ValueError("Start Docker Desktop with Linux containers")
    check_tree(ARCHIVE)

def install(control):
    preflight()
    print("Downloading official Python container image to Docker storage...",flush=True)
    docker("pull",IMAGE,timeout=900)
    image=docker("image","inspect",IMAGE,"--format","{{.Id}}")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}",image):
        raise ValueError("Expected pinned image ID")
    write(control/"docker_image.txt",image.encode("ascii"))

def stage(job,folder,fetch):
    commit=job["commit"]
    if job["task"]!="archive_check" or not re.fullmatch(r"[0-9a-f]{40}",commit):
        raise ValueError("Invalid job")
    head=json.loads(fetch("https://api.github.com/repos/"+OFFICIAL+"/commits/main"))
    if head.get("sha")!=commit:
        raise ValueError("Archive job must target current official main")
    code=under(folder/"code")
    code.mkdir(exist_ok=False)
    for name in FILES:
        raw=fetch("https://raw.githubusercontent.com/"+OFFICIAL+"/"+commit+"/"+name,limit=256*1024)
        write(code/name,raw)
    return code

def create_args(name,code,image):
    if not re.fullmatch(r"btc-lab-[0-9a-f]{32}",name) or not re.fullmatch(r"sha256:[0-9a-f]{64}",image):
        raise ValueError("Invalid fixed container identity")
    return ["create","--name",name,"--pull","never","--network","none",
        "--read-only","--cap-drop","ALL","--security-opt","no-new-privileges",
        "--user","65534:65534","--pids-limit","64","--memory","2g","--memory-swap","2g",
        "--cpus","2","--log-driver","none","--tmpfs","/tmp:rw,noexec,nosuid,size=32m,mode=1777",
        "--mount","type=bind,source="+str(under(code))+",target=/app,readonly",
        "--mount","type=bind,source="+str(under(ARCHIVE))+",target=/archive,readonly",
        "--workdir","/app",image,"python","-I","-S","-B","-u","/app/docker_archive_task.py"]

def attach(cid):
    p=subprocess.Popen(command("start","--attach",cid),cwd=ROOT,stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
    buf=bytearray()
    overflow=threading.Event()
    def drain():
        while True:
            chunk=p.stdout.read(4096)
            if not chunk:
                return
            if len(buf)+len(chunk)>MAX_REPORT*2:
                overflow.set()
                return
            buf.extend(chunk)
    reader=threading.Thread(target=drain,daemon=True)
    reader.start()
    deadline=time.monotonic()+TIMEOUT
    try:
        while p.poll() is None:
            space()
            if overflow.is_set() or time.monotonic()>deadline:
                raise TimeoutError("Container exceeded time/output limit")
            time.sleep(.25)
        reader.join(3)
        if reader.is_alive() or overflow.is_set():
            raise ValueError("Container output incomplete or oversized")
        return p.returncode,bytes(buf)
    finally:
        if p.poll() is None:
            p.kill()
            p.wait(timeout=10)
        p.stdout.close()

def run(job,folder,control,fetch,utc):
    result={"version":"docker-job-result-v1",**job,"started_utc":utc(),"status":"error"}
    cid=None
    creating=False
    phase="preflight"
    try:
        preflight()
        image=under(control/"docker_image.txt").read_text(encoding="ascii").strip()
        code=stage(job,folder,fetch)
        name="btc-lab-"+uuid.uuid4().hex
        phase="create"
        creating=True
        value=docker(*create_args(name,code,image),timeout=60)
        if not re.fullmatch(r"[0-9a-f]{64}",value):
            raise ValueError("Container ID not acknowledged")
        cid=value
        creating=False
        write(folder/"container_id.txt",cid.encode("ascii"))
        phase="execute"
        rc,raw=attach(cid)
        write(folder/"container.log",raw)
        if rc:
            result.update(exit_code=rc,log_tail=raw[-8000:].decode("utf-8","replace"))
        else:
            phase="report"
            _,marker,payload=raw.rpartition(b"BTC_LAB_REPORT ")
            if not marker or len(payload)>MAX_REPORT:
                raise ValueError("Missing or oversized report")
            report=json.loads(payload)
            if (not isinstance(report,dict) or report.get("version")!="docker-archive-v1"
                or report.get("status") not in ("ok","error")):
                raise ValueError("Unexpected report")
            write(folder/"report.json",payload)
            result.update(report=report,report_sha256=hashlib.sha256(payload).hexdigest(),
                          status=report["status"],exit_code=rc)
    except (OSError,ValueError,KeyError,TypeError,subprocess.SubprocessError) as exc:
        result.update(stage=phase,error_type=type(exc).__name__)
        print("Docker:",phase,type(exc).__name__,str(exc)[:220],flush=True)
    finally:
        if cid is not None:
            try:
                # Remove only this newly created, disposable container by full ID.
                docker("rm","--force",cid,timeout=30)
                result["container_removed"]=True
            except (OSError,subprocess.SubprocessError):
                result.update(container_removed=False,requires_owner=True,status="error")
        elif creating:
            result.update(requires_owner=True,status="error")
        result["finished_utc"]=utc()
    return result
