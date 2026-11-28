"""Owner-run readiness probe; no remote code, deletion, elevation or Windows changes."""
import ctypes
import json
import os
import shutil
import stat
import sys
import time
import uuid
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT=Path(r"D:\Проекты\btc-lab")
BASE=ROOT/"data"/"sandbox_probe"
ARCHIVE=ROOT/"data"/"binance_1m"
GIB=1024**3
MIN_START=3*GIB
MIN_DURING=2*GIB
MAX_RUNTIME=384*1024**2

def plain(path):
    path=Path(path)
    for p in [*reversed(path.parents),path]:
        try:
            st=p.lstat()
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(st.st_mode) or getattr(st,"st_file_attributes",0)&0x400:
            raise ValueError("Reparse point rejected: "+str(p))
    return path

def under(path):
    p=Path(path)
    if not p.is_absolute() or ".." in p.parts or (p!=ROOT and ROOT not in p.parents):
        raise ValueError("Path outside work folder")
    return plain(p)

def write(path,raw):
    p=under(path)
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open("xb") as f:
        f.write(raw)

def free_c():
    return shutil.disk_usage("C:\\").free

def check_tree(folder):
    # Do not expose junctions or symlinks that may lead outside the archive.
    for current,dirs,files in os.walk(under(folder),followlinks=False):
        for name in dirs+files:
            under(Path(current)/name)

def runtime(dest):
    # Copy only runtime from this already-installed interpreter, not its
    # site-packages, user config, credentials, venv or scripts.
    src=plain(Path(sys.base_prefix))
    if sys.version_info[:2] not in ((3,11),(3,12),(3,13),(3,14)) or sys.maxsize<=2**32:
        raise ValueError("Expected installed 64-bit Python 3.11-3.14")
    files=[]
    for p in src.iterdir():
        if p.is_file() and (p.name=="python.exe" or p.name.lower().startswith(("python3","vcruntime","ucrtbase")) and p.suffix.lower() in (".dll",".zip")):
            files.append(p)
    for folder in ("DLLs","Lib"):
        d=src/folder
        if not d.is_dir():
            continue
        for current,dirs,names in os.walk(plain(d),followlinks=False):
            dirs[:]=[n for n in dirs if n not in ("site-packages","__pycache__","test","tests","tkinter","idlelib","turtledemo","ensurepip")]
            for n in dirs:
                plain(Path(current)/n)
            for n in names:
                p=plain(Path(current)/n)
                if p.suffix.lower() not in (".pyc",".pyo",".pth"):
                    files.append(p)
    if src/"python.exe" not in files or not files:
        raise ValueError("Full installed Python runtime not found")
    total=0
    for p in files:
        plain(p)
        total+=p.stat().st_size
        if total>MAX_RUNTIME:
            raise ValueError("Runtime copy exceeds 384 MiB")
    if shutil.disk_usage(ROOT).free<total+512*1024**2:
        raise ValueError("Not enough free space on D")
    for p in files:
        target=under(dest/p.relative_to(src))
        target.parent.mkdir(parents=True,exist_ok=True)
        with p.open("rb") as f,target.open("xb") as g:
            shutil.copyfileobj(f,g)
    return total

def configuration(runtime_dir,code,canary,archive,out):
    config=ET.Element("Configuration")
    for key,val in (("VGpu","Disable"),("Networking","Disable"),
                    ("AudioInput","Disable"),("VideoInput","Disable"),
                    ("PrinterRedirection","Disable"),("ClipboardRedirection","Disable"),
                    ("ProtectedClient","Enable"),("MemoryInMB","2048")):
        ET.SubElement(config,key).text=val
    maps=ET.SubElement(config,"MappedFolders")
    for source,guest,ro in ((runtime_dir,r"C:\btc_python",True),(code,r"C:\btc_code",True),
        (canary,r"C:\btc_canary",True),(archive,r"C:\btc_archive",True),(out,r"C:\btc_output",False)):
        m=ET.SubElement(maps,"MappedFolder")
        ET.SubElement(m,"HostFolder").text=str(under(source))
        ET.SubElement(m,"SandboxFolder").text=guest
        ET.SubElement(m,"ReadOnly").text="true" if ro else "false"
    command=ET.SubElement(config,"LogonCommand")
    ET.SubElement(command,"Command").text=r"C:\btc_python\python.exe -I -B C:\btc_code\sandbox_guest_probe.py"
    return ET.tostring(config,encoding="utf-8",xml_declaration=True)

def run():
    if os.name!="nt" or Path.cwd()!=ROOT:
        raise ValueError("Run on Windows from D:\\Проекты\\btc-lab")
    before=free_c()
    if before<MIN_START:
        raise ValueError("C: needs at least 3 GiB free before this probe")
    if not ARCHIVE.is_dir():
        raise ValueError("Expected existing data/binance_1m archive directory")
    check_tree(ARCHIVE)
    session=under(BASE/uuid.uuid4().hex)
    session.mkdir(parents=True,exist_ok=False)
    rt,code,canary,out=(session/n for n in ("runtime","code","canary","output"))
    for p in (rt,code,canary,out):
        under(p).mkdir(exist_ok=False)
    size=runtime(rt)
    write(code/"sandbox_guest_probe.py",under(ROOT/"sandbox_guest_probe.py").read_bytes())
    write(canary/"read-me.txt",b"BTC-Lab isolation probe")
    config=session/"probe.wsb"
    write(config,configuration(rt,code,canary,ARCHIVE,out))
    before_launch=free_c()
    if before_launch<MIN_START:
        raise ValueError("C: below 3 GiB; sandbox not launched")
    print("C: free before launch:",round(before_launch/GIB,2),"GiB",flush=True)
    print("Sandbox opens offline. Close it after the result. Do not start other sandbox sessions.",flush=True)
    # Windows file association, fixed local .wsb; no remotely supplied command.
    os.startfile(str(config))
    deadline=time.monotonic()+180
    minimum=before_launch
    result=out/"probe.json"
    while time.monotonic()<deadline:
        free=free_c()
        minimum=min(minimum,free)
        if free<MIN_DURING:
            print("WARNING: C: below 2 GiB. CLOSE WINDOWS SANDBOX NOW.",flush=True)
            ctypes.windll.user32.MessageBoxW(None,"Less than 2 GiB free on C:. Close Windows Sandbox now.","BTC-Lab",0x30|0x40000)
            break
        if result.is_file():
            try:
                if under(result).stat().st_size>16384:
                    raise ValueError("Unexpected report size")
                obj=json.loads(result.read_text(encoding="utf-8"))
                if obj.get("version")!="sandbox-probe-v1":
                    raise ValueError("Unexpected report version")
                print("Sandbox report received:",obj.get("status"),flush=True)
                break
            except json.JSONDecodeError:
                pass
        time.sleep(1)
    else:
        print("Probe timed out. Close Sandbox manually. No automatic retry.",flush=True)
    # Check only the disposable canary, never create/modify an archive file.
    host={"version":"sandbox-host-probe-v1","runtime_bytes":size,
          "c_free_before_bytes":before,"c_free_before_launch_bytes":before_launch,
          "c_min_during_bytes":minimum,"c_free_at_end_bytes":free_c(),
          "canary_unexpected_write":(canary/"unexpected-write.txt").exists(),
          "guest_report":None}
    if result.is_file() and under(result).stat().st_size<=16384:
        try:
            host["guest_report"]=json.loads(result.read_text(encoding="utf-8"))
        except (OSError,ValueError):
            pass
    target=session/"sandbox_readiness.json"
    write(target,(json.dumps(host,indent=2,ensure_ascii=False)+"\n").encode("utf-8"))
    print("CLOSE SANDBOX manually after the probe.",flush=True)
    print("Send:",target,flush=True)

if __name__=="__main__":
    try:
        run()
    except (OSError,ValueError) as exc:
        print("STOP:",type(exc).__name__,str(exc)[:300])
        sys.exit(1)
