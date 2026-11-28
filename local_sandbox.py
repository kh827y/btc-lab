"""Fixed host-side Windows Sandbox controller. No downloaded code runs on host."""
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path

import sandbox_probe as probe

TASK="archive_check"
FILES=("sandbox_archive_task.py","binance_minute.py")
MAX_REPORT=128*1024
MAX_LOG=16*1024
MIN_D=512*1024**2
TIMEOUT=300
OFFICIAL="kh827y/btc-lab"
BOOT=(
    '@echo off\r\n'
    'echo Started>C:\\btc_output\\boot.log\r\n'
    'C:\\btc_python\\python.exe -I -S -B -X utf8 C:\\btc_code\\sandbox_guest_probe.py >>C:\\btc_output\\boot.log 2>&1\r\n'
    'if errorlevel 1 goto failed\r\n'
    'C:\\btc_python\\python.exe -I -S -B -X utf8 C:\\btc_code\\sandbox_archive_task.py >>C:\\btc_output\\boot.log 2>&1\r\n'
    'set "RC=%ERRORLEVEL%"\r\n'
    'goto done\r\n'
    ':failed\r\n'
    'set "RC=1"\r\n'
    ':done\r\n'
    'echo %RC%>C:\\btc_output\\boot.done\r\n'
)

def cli_path():
    # Windows system executable or the Microsoft Store execution alias only.
    if os.name!="nt":
        raise ValueError("Windows Sandbox requires Windows")
    system=Path(os.environ.get("SystemRoot",r"C:\Windows"))/"System32"/"wsb.exe"
    alias=Path(os.environ["LOCALAPPDATA"])/"Microsoft"/"WindowsApps"/"wsb.exe"
    for p in (system,alias):
        if p.is_file():
            return p
    raise ValueError("wsb.exe is unavailable; automatic session management requires the current Windows Sandbox app")

def cli(exe,*args,timeout=30):
    return subprocess.run([str(exe),*args],cwd=probe.ROOT,stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,stderr=subprocess.STDOUT,check=True,timeout=timeout)

def preflight():
    exe=cli_path()
    cli(exe,"list",timeout=20)
    if probe.free_c()<probe.MIN_START:
        raise ValueError("C: below 3 GiB free")
    if shutil.disk_usage(probe.ROOT).free<MIN_D:
        raise ValueError("Insufficient space on D:")
    if not probe.ARCHIVE.is_dir():
        raise ValueError("Binance minute archive unavailable")
    return exe

def install(control):
    # Fixed runtime and trusted probe source installed once, separate from jobs.
    rt=probe.under(control/"runtime")
    rt.mkdir(exist_ok=False)
    probe.runtime(rt)
    probe.write(control/"guest_probe.py",probe.under(probe.ROOT/"sandbox_guest_probe.py").read_bytes())

def stage(job,folder,control,fetch):
    # No branch names, paths, commands or parameters accepted from the job.
    commit=job["commit"]
    if not re.fullmatch(r"[0-9a-f]{40}",commit) or job["task"]!=TASK:
        raise ValueError("Invalid archive job")
    head=json.loads(fetch("https://api.github.com/repos/"+OFFICIAL+"/commits/main"))
    if head.get("sha")!=commit:
        raise ValueError("Archive job must target current official main")
    code=probe.under(folder/"code")
    code.mkdir(exist_ok=False)
    for name in FILES:
        raw=fetch("https://raw.githubusercontent.com/"+OFFICIAL+"/"+commit+"/"+name,limit=256*1024)
        probe.write(code/name,raw)
    probe.write(code/"sandbox_guest_probe.py",probe.under(control/"guest_probe.py").read_bytes())
    probe.write(code/"probe.cmd",BOOT.encode("ascii"))
    return code

def small(path,limit):
    path=probe.under(path)
    if not path.is_file():
        return None
    with path.open("rb") as f:
        data=f.read(limit+1)
    if len(data)>limit:
        raise ValueError("Sandbox output exceeds limit")
    return data

def disk_check(out):
    if probe.free_c()<probe.MIN_DURING:
        raise ValueError("C: below 2 GiB free")
    if shutil.disk_usage(probe.ROOT).free<MIN_D:
        raise ValueError("D: below 512 MiB free")
    # This is an operational guard, not a hard quota.
    total=0
    count=0
    for current,dirs,files in os.walk(probe.under(out),followlinks=False):
        for name in dirs+files:
            p=probe.under(Path(current)/name)
            count+=1
            if count>32:
                raise ValueError("Too many sandbox output entries")
            if p.is_file():
                total+=p.stat().st_size
                if total>4*1024**2:
                    raise ValueError("Sandbox output exceeds 4 MiB guard")

def run(job,folder,control,fetch,utc):
    result={"version":"sandbox-job-result-v1",**job,"started_utc":utc(),"status":"error"}
    owned_id=None
    connection=None
    exe=None
    out=folder/"output"
    phase="preflight"
    try:
        exe=preflight()
        probe.check_tree(probe.ARCHIVE)
        code=stage(job,folder,control,fetch)
        out.mkdir(exist_ok=False)
        canary=probe.under(folder/"canary")
        canary.mkdir(exist_ok=False)
        probe.write(canary/"read-me.txt",b"BTC-Lab isolation probe")
        xml=probe.configuration(control/"runtime",code,canary,probe.ARCHIVE,out)
        probe.write(folder/"session.wsb",xml)
        disk_check(out)
        phase="start"
        sid=str(uuid.uuid4())
        # Unique caller-selected session ID; never stop by process name, never
        # target any previously existing sandbox.
        listed=cli(exe,"list",timeout=20).stdout.decode("utf-8",errors="replace")
        if sid.replace("-","").lower() in listed.replace("-","").lower():
            raise ValueError("Unexpected Sandbox ID collision")
        probe.write(folder/"session_id.txt",sid.encode("ascii"))
        owned_id=sid
        start=cli(exe,"start","--id",sid,"--config",xml.decode("utf-8"),timeout=90)
        # Require acknowledgement of our ID before connecting.
        answer=start.stdout.decode("utf-8",errors="replace")
        if sid.replace("-","").lower() not in answer.replace("-","").lower():
            raise ValueError("Sandbox CLI did not acknowledge the requested session ID")
        phase="connect"
        connection=subprocess.Popen([str(exe),"connect","--id",sid],cwd=probe.ROOT,
            stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        phase="guest"
        deadline=time.monotonic()+TIMEOUT
        while time.monotonic()<deadline:
            disk_check(out)
            marker=small(out/"boot.done",64)
            if marker and re.fullmatch(rb"-?[0-9]+\s*",marker):
                result["guest_exit_code"]=int(marker.strip())
                break
            time.sleep(1)
        else:
            raise TimeoutError("Sandbox guest did not finish within 300 seconds")
        phase="result"
        raw=small(out/"report.json",MAX_REPORT)
        can=small(out/"probe.json",MAX_REPORT)
        if raw is None or can is None:
            raise ValueError("Expected guest reports missing")
        isolation=json.loads(can)
        if (isolation.get("status")!="ok" or isolation.get("readonly_canary") is not True
            or isolation.get("archive_read") is not True or isolation.get("archive_hash_match") is not True
            or (canary/"unexpected-write.txt").exists()):
            raise ValueError("Read-only or archive access check failed")
        report=json.loads(raw)
        if (not isinstance(report,dict) or report.get("version")!="sandbox-archive-v1"
            or report.get("status") not in ("ok","error")):
            raise ValueError("Unexpected archive report")
        result.update(report=report,report_sha256=hashlib.sha256(raw).hexdigest(),
                      isolation_verified=True,
                      status="ok" if report["status"]=="ok" and result["guest_exit_code"]==0 else "error")
    except (OSError,ValueError,TypeError,KeyError,subprocess.SubprocessError) as exc:
        result.update(status="error",stage=phase,error_type=type(exc).__name__)
        # Fixed controller errors are safe to print locally. No host paths or credentials
        # from exceptions are exported in a result.
        print("Sandbox:",phase,type(exc).__name__,str(exc)[:250],flush=True)
    finally:
        if owned_id is not None:
            try:
                cli(exe,"stop","--id",owned_id,timeout=30)
                result["session_stopped"]=True
            except (OSError,subprocess.SubprocessError):
                result["session_stopped"]=False
                result["requires_owner"]=True
                result["status"]="error"
        else:
            result["session_stopped"]=None
        if connection is not None and connection.poll() is None:
            # Only the CLI connection process we launched, no global taskkill.
            try:
                connection.terminate()
            except OSError:
                pass
        try:
            log=small(out/"boot.log",MAX_LOG)
            if log is not None:
                result["guest_log"]=log.decode("utf-8",errors="replace")
        except (OSError,ValueError):
            pass
        result["finished_utc"]=utc()
    return result
