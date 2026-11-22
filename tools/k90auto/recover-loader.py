#!/usr/bin/env python3
"""Converge to idle loader from its runtime, identified LK, or B-slot Android."""
import json, os, re, subprocess, sys, time
from pathlib import Path
# The only argument is a new directory, and every run sends device commands: an option is refused here
# before it becomes a directory name and a running kernel gets `oem stop'.
if len(sys.argv)!=2 or sys.argv[1].startswith("-"):
    sys.exit("usage: recover-loader.py NEW_DIR   (records commands and saved logs in NEW_DIR)\n"+__doc__)
base=Path(sys.argv[1]);base.mkdir()
records=[]
# Bound enumeration, empty-serial polling, and Android boot-completion waits.
ADB_WAIT=40
def call(argv,limit=8,check=True):
    started=time.monotonic()
    try:
        r=subprocess.run(argv,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,text=True,timeout=limit)
        rc,out=r.returncode,r.stdout
    except subprocess.TimeoutExpired as error:
        rc,out=124,error.stdout or ""
        if isinstance(out,bytes):out=out.decode(errors="replace")
    except OSError as error:
        rc,out=127,str(error)
    item={"argv":argv,"rc":rc,"output":out,"at":started,"seconds":time.monotonic()-started}
    records.append(item);(base/"commands.json").write_text(json.dumps(records,indent=2)+"\n")
    if check:assert rc==0 and "FAILED" not in out,item
    return out

def device_serials(command,mode):
    deadline=time.monotonic()+ADB_WAIT
    while True:
        out=call(command,1.5,False)
        if records[-1]["rc"]==0 and "FAILED" not in out:
            rows=[line.split() for line in out.splitlines()]
            if [mode] not in rows:
                return [parts[0] for parts in rows if len(parts)==2 and parts[1]==mode]
        assert time.monotonic()<deadline,"empty or timed-out device enumeration persisted; only enumeration was performed"
        time.sleep(0.05)
def fastboots():
    return device_serials(["fastboot","devices"],"fastboot")
def adb_devices():
    return device_serials(["adb","devices"],"device")
def value(reply,key):
    values=re.findall(r"^(?:\(bootloader\)[ \t]*)?"+re.escape(key)+r":[ \t]*([^\r\n]*?)[ \t\r]*$",reply,re.M)
    assert len(values)==1 and values[0],"missing or ambiguous "+key
    return values[0]
def idle():
    # Record build-id; product, runtime state, and resident RAM are checked independently.
    pre=["fastboot","-s","xnuloader"]
    assert value(call(pre+["getvar","product"]),"product")=="xnuloader"
    build_id=call(pre+["getvar","build-id"]).strip().splitlines()[0]
    assert re.fullmatch(r"idle(?: 0 0)?",value(call(pre+["getvar","result"]),"result"))
    ramdisk=value(call(pre+["getvar","ramdisk-state"]),"ramdisk-state")
    if re.fullmatch(r"(?:ready|staging) [0-9a-fA-F]+ [0-9a-fA-F]+ [0-9a-fA-F]+",ramdisk):
        call(pre+["oem","ramdisk","none"])
        ramdisk=value(call(pre+["getvar","ramdisk-state"]),"ramdisk-state")
    assert re.fullmatch(r"idle 0 0 [0-9a-fA-F]+",ramdisk),"loader RAM disk is not empty"
    return build_id
def native_to_loader(from_start=False):
    deadline=time.monotonic()+60
    while True:
        found=fastboots()
        assert found.count("xnuloader")<=1,"duplicate loader enumeration"
        if configured and configured in found:
            assert found.count(configured)==1 and "xnuloader" not in found,"ambiguous native Fastboot enumeration"
            serial=configured
            break
        if found==["xnuloader"] and from_start:
            # Nothing was on USB at the start (a reset under way) and the loader came up: converge from it.
            return converge_runtime()
        assert not found or found==["xnuloader"],"native Fastboot requires the identified ANDROID_SERIAL"
        android=adb_devices() if not found else []
        if android:
            selected=[]
            for candidate in android:
                if configured and candidate!=configured:continue
                pre=["adb","-s",candidate,"shell","getprop"]
                if call(pre+["ro.product.device"]).strip()=="annibale":
                    assert call(pre+["ro.boot.slot_suffix"]).strip()=="_b"
                    selected.append(candidate)
            assert len(selected)==1,"exactly one annibale Android B slot required"
            serial=selected[0]
            boot_deadline=time.monotonic()+ADB_WAIT
            while call(["adb","-s",serial,"shell","getprop","sys.boot_completed"]).strip()!="1":
                assert time.monotonic()<boot_deadline,"Android B did not complete boot; reboot not sent"
                time.sleep(2)
            call(["adb","-s",serial,"reboot","bootloader"])
            lk_deadline=time.monotonic()+45
            while serial not in fastboots():
                assert time.monotonic()<lk_deadline,"LK did not enumerate"
                time.sleep(1)
            break
        assert time.monotonic()<deadline,"neither identified LK nor Android B enumerated within 60 seconds"
        time.sleep(0.5)
    pre=["fastboot","-s",serial]
    assert value(call(pre+["getvar","product"]),"product")=="annibale","destination product is not annibale"
    assert value(call(pre+["getvar","is-userspace"]),"is-userspace")=="no","destination is not LK Fastboot"
    for variable in ("current-slot","slot-retry-count:a","slot-unbootable:a","slot-successful:a",
                     "slot-successful:b","slot-unbootable:b"):
        reply=call(pre+["getvar",variable])
        if variable=="slot-successful:b":assert value(reply,variable)=="yes","Android B is not successful"
        if variable=="slot-unbootable:b":assert value(reply,variable)=="no","Android B is unbootable"
    call(pre+["set_active","a"])
    assert value(call(pre+["getvar","current-slot"]),"current-slot")=="a"
    assert value(call(pre+["getvar","slot-retry-count:a"]),"slot-retry-count:a")=="7"
    assert value(call(pre+["getvar","slot-unbootable:a"]),"slot-unbootable:a")=="no"
    if os.environ.get("LOADER_IMAGE"):
        call(pre+["boot",os.environ["LOADER_IMAGE"]],60)
    else:
        call(pre+["reboot"])
    deadline=time.monotonic()+60
    while True:
        found=fastboots()
        if "xnuloader" in found:
            assert found==["xnuloader"],"ambiguous loader enumeration"
            break
        assert not found or found==[serial],"unexpected Fastboot identity after native boot"
        assert time.monotonic()<deadline,"the loader did not re-enumerate"
        # As after a runtime reset: the host sees the loader near the end of its boot-menu window.
        time.sleep(0.05)
    call(["fastboot","-s","xnuloader","oem","recovery"])
    return idle()
def converge_runtime():
    pre=["fastboot","-s","xnuloader"]
    assert value(call(pre+["getvar","product"]),"product")=="xnuloader"
    state=value(call(pre+["getvar","result"]),"result")
    if re.fullmatch(r"idle(?: 0 0)?",state):
        call(pre+["oem","recovery"])
        return idle()
    original_build=value(call(pre+["getvar","build-id"]),"build-id")
    assert value(call(pre+["getvar","ramdisk-protocol"]),"ramdisk-protocol")=="1"
    if re.fullmatch(r"running [0-9a-fA-F]+ [0-9a-fA-F]+",state):
        call(pre+["oem","stop"],20,False)
        deadline=time.monotonic()+int(os.environ.get("K90_STOP_WAIT","70"))
        while time.monotonic()<deadline:
            # (the loader can be off USB for some seconds while it takes the kernel down: no answer is not a state)
            out=call(pre+["getvar","result"],8,False)
            if records[-1]["rc"]!=0 or "FAILED" in out:
                time.sleep(1);continue
            state=value(out,"result")
            if not re.fullmatch(r"running [0-9a-fA-F]+ [0-9a-fA-F]+",state):break
            time.sleep(1)
        if re.fullmatch(r"idle(?: 0 0)?",state):
            # (a kernel the loader started on its own from its slot came back through a reset: a fresh loader)
            call(pre+["oem","recovery"])
            return idle()
    terminal=r"(?:returned|returned-held|hung|hung-held)(?: [0-9a-fA-F]+ 0)?"
    name=state.split()[0]
    if not re.fullmatch(terminal,state):
        call(pre+["oem","log"],8,False)
        call(pre+["get_staged",str(base/"unresolved.log")],40,False)
        raise AssertionError("kernel did not reach a supported quiescent state; reset not sent")
    # Terminal logs may already be staged. Save them before oem log replaces the staging area.
    call(pre+["get_staged",str(base/(name+".log"))],40)
    call(pre+["oem","log"],8)
    call(pre+["get_staged",str(base/(name+"-serial.log"))],40)
    assert re.fullmatch(terminal,value(call(pre+["getvar","result"]),"result")),"kernel state changed before reset"
    if os.environ.get("LOADER_IMAGE"):
        assert configured,"runtime recovery with LOADER_IMAGE requires ANDROID_SERIAL"
        # Held resources forbid Android slot writes; reset into LK before selecting the slot.
        if name in ("returned-held","hung-held"):
            call(pre+["reboot-bootloader"])
        else:
            call(pre+["oem","android"])
        return native_to_loader()
    fast_reset=call(pre+["oem","reboot-fastboot"],10,False)
    if fast_reset.startswith("FAILED") or "FAILED" in fast_reset or records[-1]["rc"]!=0:
        call(pre+["reboot"],10,False)
    deadline=time.monotonic()+60
    while time.monotonic()<deadline:
        found=fastboots()
        assert found.count("xnuloader")<=1,"duplicate loader enumeration after reset"
        if "xnuloader" in found:
            assert found==["xnuloader"],"ambiguous loader enumeration after reset"
            call(pre+["oem","recovery"])
            assert value(call(pre+["getvar","build-id"]),"build-id")==original_build,"loader build changed after reset"
            return idle()
        # oem recovery must land inside the loader's boot-menu window, which the host sees near its end.
        time.sleep(0.05)
    raise AssertionError("loader did not enumerate after runtime reset")
configured=os.environ.get("ANDROID_SERIAL")
assert not configured or (configured!="xnuloader" and not any(c.isspace() for c in configured)),"invalid ANDROID_SERIAL"
found=fastboots()
assert found.count("xnuloader")<=1,"duplicate loader enumeration"
if "xnuloader" in found:
    assert found==["xnuloader"],"ambiguous loader enumeration"
    print("loader Fastboot idle and empty RAM verified (%s)"%converge_runtime());sys.exit(0)
print("identified native boot to idle loader; %s"%native_to_loader(True))
