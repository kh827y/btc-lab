"""Fixed Windows controller for offline Docker jobs; no downloaded code on host."""
import hashlib
import io
import json
import os
import re
import shutil
import stat
import subprocess
import threading
import time
import uuid
import zipfile
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
TEST_PACKAGES=('streamlit==1.67.0','plotly==6.9.0','pandas==3.1.1','tzdata==2026.6','numpy==2.5.5')
TEST_IMAGE_FILE='test_image.txt'
TEST_TAG='btc-lab-unit:v1'
BASE_TAG='btc-lab-test-base:v1'
MAX_CODE=16*1024*1024

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

def preflight(archive=True):
    space()
    if not DOCKER.is_file():
        raise ValueError("Docker Desktop must be installed at D:\\Docker")
    if docker("version","--format","{{.Server.Os}}")!="linux":
        raise ValueError("Start Docker Desktop with Linux containers")
    if archive:
        check_tree(ARCHIVE)

def install(control):
    preflight()
    print("Downloading official Python container image to Docker storage...",flush=True)
    docker("pull",IMAGE,timeout=900)
    image=docker("image","inspect",IMAGE,"--format","{{.Id}}")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}",image):
        raise ValueError("Expected pinned image ID")
    write(control/"docker_image.txt",image.encode("ascii"))

def prepare_test_image(control):
    """Owner-run only; fixed dependency installation, no project or secret build context."""
    preflight(archive=False)
    pin=under(control/TEST_IMAGE_FILE)
    if pin.is_file():
        image=pin.read_text(encoding="ascii").strip()
        if re.fullmatch(r"sha256:[0-9a-f]{64}",image) and docker("image","inspect",image,"--format","{{.Id}}")==image:
            return
        raise ValueError("Existing test image pin is invalid; owner review required")
    base=under(control/"docker_image.txt").read_text(encoding="ascii").strip()
    if not re.fullmatch(r"sha256:[0-9a-f]{64}",base) or docker("image","inspect",base,"--format","{{.Id}}")!=base:
        raise ValueError("Expected installed pinned Python base")
    docker("tag",base,BASE_TAG)
    context=under(control/"test_build"/uuid.uuid4().hex)
    context.mkdir(parents=True,exist_ok=False)
    # Only this fixed Dockerfile enters the build; no host files, tokens or remote code.
    spec=("FROM "+BASE_TAG+"\nRUN python -m pip install --disable-pip-version-check --no-cache-dir --only-binary=:all: "
          +" ".join(TEST_PACKAGES)+" && python -m pip check\n")
    write(context/"Dockerfile",spec.encode("ascii"))
    print("Preparing one-time test image (public Python wheels, no project data)...",flush=True)
    subprocess.run(command("build","--pull=false","--tag",TEST_TAG,str(context)),
                   cwd=ROOT,stdin=subprocess.DEVNULL,check=True,timeout=900)
    image=docker("image","inspect",TEST_TAG,"--format","{{.Id}}")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}",image):
        raise ValueError("Expected pinned test image ID")
    write(pin,image.encode("ascii"))

def unpack_code(raw,code,commit):
    """Extract only regular public repo files into a new job folder, never run on host."""
    if len(raw)>8*1024*1024:
        raise ValueError("Code ZIP too large")
    expected="btc-lab-"+commit
    seen=set()
    total=0
    with zipfile.ZipFile(io.BytesIO(raw)) as z:
        infos=z.infolist()
        if len(infos)>500:
            raise ValueError("Too many ZIP members")
        for info in infos:
            parts=info.filename.rstrip("/").split("/")
            if parts[0]!=expected or any(not re.fullmatch(r"[A-Za-z0-9_.-]+",p) or p in (".","..") or p.endswith(".")
                or re.fullmatch(r"(?i:CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(?:\..*)?",p) for p in parts):
                raise ValueError("Unexpected ZIP path")
            mode=stat.S_IFMT(info.external_attr>>16)
            if mode not in (0,stat.S_IFREG,stat.S_IFDIR):
                raise ValueError("Nonregular ZIP member")
            if info.is_dir():
                continue
            if len(parts)<2 or ".git" in parts or len(parts)>8:
                raise ValueError("Unexpected code path")
            key="/".join(parts[1:]).casefold()
            if key in seen:
                raise ValueError("Duplicate ZIP path")
            seen.add(key)
            total+=info.file_size
            if info.file_size>2*1024*1024 or total>MAX_CODE:
                raise ValueError("Uncompressed code limit")
            dest=under(code.joinpath(*parts[1:]))
            dest.parent.mkdir(parents=True,exist_ok=True)
            write(dest,z.read(info))
    if not (code/"docker_unit_task.py").is_file() or not (code/"tests").is_dir():
        raise ValueError("Incomplete test source")

def stage(job,folder,fetch):
    commit=job["commit"]
    if job["task"] not in ("archive_check","unit_tests") or not re.fullmatch(r"[0-9a-f]{40}",commit):
        raise ValueError("Invalid job")
    head=json.loads(fetch("https://api.github.com/repos/"+OFFICIAL+"/commits/main"))
    if head.get("sha")!=commit:
        raise ValueError("Docker job must target current official main")
    code=under(folder/"code")
    code.mkdir(exist_ok=False)
    if job["task"]=="unit_tests":
        raw=fetch("https://codeload.github.com/"+OFFICIAL+"/zip/"+commit,limit=8*1024*1024)
        unpack_code(raw,code,commit)
        return code
    for name in FILES:
        raw=fetch("https://raw.githubusercontent.com/"+OFFICIAL+"/"+commit+"/"+name,limit=256*1024)
        write(code/name,raw)
    return code

def create_args(name,code,image,task="archive_check"):
    if not re.fullmatch(r"btc-lab-[0-9a-f]{32}",name) or not re.fullmatch(r"sha256:[0-9a-f]{64}",image):
        raise ValueError("Invalid fixed container identity")
    if task not in ("archive_check","unit_tests"):
        raise ValueError("Invalid Docker task")
    args=["create","--name",name,"--pull","never","--network","none",
        "--read-only","--cap-drop","ALL","--security-opt","no-new-privileges",
        "--user","65534:65534","--pids-limit","64","--memory","2g","--memory-swap","2g",
        "--cpus","2","--log-driver","none","--tmpfs","/tmp:rw,noexec,nosuid,size="+("128m" if task=="unit_tests" else "32m")+",mode=1777",
        "--mount","type=bind,source="+str(under(code))+",target=/app,readonly",
        ]
    if task=="archive_check":
        return args+["--mount","type=bind,source="+str(under(ARCHIVE))+",target=/archive,readonly",
                     "--workdir","/app",image,"python","-I","-S","-B","-u","/app/docker_archive_task.py"]
    return args+["--env","OPENBLAS_NUM_THREADS=1","--env","OMP_NUM_THREADS=1",
                 "--workdir","/app",image,"python","-I","-B","-u","/app/docker_unit_task.py"]

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
        preflight(archive=job["task"]=="archive_check")
        pin=TEST_IMAGE_FILE if job["task"]=="unit_tests" else "docker_image.txt"
        image=under(control/pin).read_text(encoding="ascii").strip()
        result["image_id"]=image
        code=stage(job,folder,fetch)
        name="btc-lab-"+uuid.uuid4().hex
        phase="create"
        creating=True
        value=docker(*create_args(name,code,image,job["task"]),timeout=60)
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
            if (not isinstance(report,dict) or report.get("version")!=("docker-unit-v1" if job["task"]=="unit_tests" else "docker-archive-v1")
                or report.get("status") not in ("ok","error")):
                raise ValueError("Unexpected report")
            write(folder/"report.json",payload)
            result.update(report=report,report_sha256=hashlib.sha256(payload).hexdigest(),
                          status=report["status"],exit_code=rc)
            if report["status"]=="error":
                result["log_tail"]=raw[-12000:].decode("utf-8","replace")
    except (OSError,ValueError,KeyError,TypeError,zipfile.BadZipFile,subprocess.SubprocessError) as exc:
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
