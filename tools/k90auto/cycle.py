#!/usr/bin/env python3
"""One unattended desktop round from the working tree: pack, boot, tour, render report.

usage: tools/k90auto/cycle.py LABEL [--baseline ROUND_DIR] [--seconds N] [--kernel NAME] [--hold | --teardown]
                              [--tour STEP ...]

  1. package.py with the interactive jobs and annsh (the caller's environment goes through, so
     ICON_METAL=1 and the other package switches work as they do there), then make-payload.py
     for kernel NAME (default KERNEL) with four cores.
  2. ensure_loader_idle() uses recover-loader.py to reach an enumerated, idle xnuloader with an
     empty resident boot image, then checks that state independently.
     When LOADER_IMAGE or CYCLE_CHECKPOINT=1 is set with ANDROID_SERIAL,
     checkpoint() resets slot A's retry count at LK and boots the requested loader image.
  3. round-run.py in the background; once SpringBoard reports the boot unlock, tour.py runs TOUR or --tour
     (only its first step when the GPU has already stopped). By default run-auto.py is then asked to
     leave iOS running (run/leave-running) and the device stays on the home screen, unless unhealthy()
     finds a stopped GPU or a restarting SpringBoard in the round's logs. --teardown asks
     the round to stop instead (run/stop-request). With --hold the round runs until respin.py --stop
     or the N seconds, and respin.py changes settings and restarts processes in it meanwhile. No boot
     unlock within UNLOCK_WAIT skips the tour and stops the round.
  4. render-health.py, against --baseline when given, into ROUND_DIR/render-report.txt.
  5. With --teardown, or when unhealthy() kept iOS from being left running, ensure_loader_idle() again.

Exit code: 0 when the round ran (and, with --teardown, the loader came back idle), 1 otherwise.
"""
import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[1]
EVIDENCE = WORKSPACE / "docs/progress/evidence/k90auto"
UNLOCK_LINE = "sb26: boot unlock done"
GPU_STOP = "submissions closed"   # after this the compositor draws in software, so the tour is cut short
UNLOCK_WAIT = 420           # boot to the home screen
SETTINGS_ICON = (0.385, 0.70)   # second column, fifth row; 0.616 is the empty space beside it
# Kernel record used unless --kernel selects another build.
KERNEL = "12377-st5"
# Additional host-built programs to copy into /annibale/bin; trollstorehelper and annsh are already built into
# userland/root/bin by userland/build.sh and verified by package.py.
BOOT_PROGRAMS = []
# The boot-args every round has (CYCLE_FIXED_ARGS replaces all of them, for a round whose variable is
# one of them: the kernel takes the first of two). Diagnostics stay out of here and go in --boot-args.
FIXED_ARGS = " ".join([
    "gpu_log=1 metal=1 cpufreq=1 fb_threads=2 touch_lat=1 gpu_coherent=1 autounlock=1",
    # The 120 Hz path measured on 2026-11-02 (docs/analysis/2026-11-01-120hz-gesture-bottleneck.md): page
    # flips at the panel's refresh with no beat of the driver's own on top (fb_flip=2 fb_beat=0), 120 Hz
    # reported to CoreAnimation (fb_hz, fb_ca_hz) and UIKit's in-process animations left at the display's
    # rate (dl_max=1).
    "fb_flip=2 fb_beat=0 fb_hz=120 fb_ca_hz=120 dl_max=1",
    # The touch screen read every 4 ms instead of 8 (annibale_goodix.c), as in every round since bo63.
    "touch_poll_us=4000",
    # Wi-Fi as in kernel-12377-cmd83-wd32 (docs/progress/2026-11-01-wifi-ath12k-driver.md §1): ath12k on
    # the WCN7850, wifid joins the networks picked in Settings (wifi_station=1). The address is a locally
    # administered one of ours; the card's firmware carries none. package.py puts the firmware in.
    "pcie=10 pcie_power=1 pcie_sleep_clock=board pcie_bdf=bd_p11.elf pcie_smps_hpm=1 pcie_bt_en=1 pcie_aop_pdc=1",
    "pcie_rddm=1 wifi_mlo=1 wifi_station=1",
    # UFS writes /private/var to darwin_var, bt=4 selects SE14 UART / WCN7850, and cam=5 exposes
    # /arm-io/isp (camera-rear) & /product/camera so MobileGestalt still-camera stays true and
    # SpringBoard keeps Camera.app on the home screen (matches release mkstandalone.py DEFAULT_CMDLINE).
    "ufs_write=1 bt=4 cam=5",
])
TOUR = [
    "home@3*2",
    "icons-layers=notify com.annibale.layers.Icon@4*0",
    "wallpaper-layers=notify com.annibale.layers.Wallpaper@4*0",
    "statusbar-layers=notify com.annibale.layers.StatusBar@4*0",
    "full-layers=notify com.annibale.layers.full@4*0",
    "settings=/annibale/bin/trollstorehelper open com.apple.Preferences@4*2",
    "settings-scrolled=/annibale/bin/anntouch swipe 0.5 0.7 0.5 0.35 300@3*2",
    "home-again=/annibale/bin/anntouch swipe 0.5 0.995 0.5 0.55 200@4*1",
    "control-center=/annibale/bin/anntouch swipe 0.9 0.005 0.9 0.6 300@3*2",
    "cc-closed=/annibale/bin/anntouch swipe 0.5 0.995 0.5 0.55 200@3*1",
    "notifications=/annibale/bin/anntouch swipe 0.3 0.005 0.3 0.7 300@3*1",
    "nc-closed=/annibale/bin/anntouch swipe 0.5 0.995 0.5 0.55 200@3*1",
]


def run(args, **kw):
    print("+", " ".join(str(a) for a in args), flush=True)
    return subprocess.run([str(a) for a in args], cwd=WORKSPACE, **kw)


def fastboot(*args, serial="xnuloader", timeout=20):
    if not serial or any(c.isspace() for c in serial):
        raise RuntimeError("fastboot serial is empty or contains whitespace")
    devices = subprocess.run(["fastboot", "devices"], capture_output=True, text=True, timeout=5)
    found = [line.split() for line in devices.stdout.splitlines()]
    if devices.returncode or "FAILED" in devices.stdout + devices.stderr or found.count([serial, "fastboot"]) != 1:
        raise RuntimeError("requested fastboot serial is not uniquely enumerated")
    result = subprocess.run(["fastboot", "-s", serial, *args], capture_output=True, text=True,
                            timeout=timeout)
    output = result.stdout + result.stderr
    if result.returncode or "FAILED" in output:
        raise RuntimeError(f"fastboot {args[0]} failed (exit {result.returncode})")
    return output


def loader_enumerated():
    try:
        devices = subprocess.run(["fastboot", "devices"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.TimeoutExpired):
        return None
    found = [line.split() for line in devices.stdout.splitlines()]
    if devices.returncode or "FAILED" in devices.stdout + devices.stderr:
        return None
    if found.count(["xnuloader", "fastboot"]) != 1:
        return False
    return True


def loader_var(key):
    try:
        output = fastboot("getvar", key, timeout=8)
    except (OSError, subprocess.SubprocessError, RuntimeError):
        return ""
    values = re.findall(r"^(?:\(bootloader\)[ \t]*)?" + re.escape(key) +
                        r":[ \t]*([^\r\n]*?)[ \t\r]*$", output, re.M)
    return values[0] if len(values) == 1 else ""


def loader_ready():
    enum = loader_enumerated()
    if enum is None:
        return "fastboot enumeration failed"
    if not enum:
        return "no xnuloader in fastboot devices"
    if loader_var("product") != "xnuloader":
        return "loader product is not xnuloader"
    if re.fullmatch(r"idle(?: 0 0)?", loader_var("result")) is None:
        return "loader result is not idle"
    if re.fullmatch(r"idle 0 0 [0-9a-fA-F]+", loader_var("ramdisk-state")) is None:
        return "loader RAM disk is not empty"
    return None


def ensure_loader_idle():
    """Converge a running/held xnuloader or B-slot Android session to an idle xnuloader."""
    try:
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        rec_dir = EVIDENCE / f"loader-recover-{time.time_ns()}"
        rec = run([sys.executable, HERE / "recover-loader.py", rec_dir], capture_output=True, text=True)
        if rec.returncode:
            return "recover-loader.py failed; see its command records"
        return loader_ready()
    except (OSError, subprocess.SubprocessError, RuntimeError, ValueError) as error:
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        (EVIDENCE / "cycle-recovery.json").write_text(json.dumps({"error": str(error)}) + "\n")
        return str(error)


def checkpoint():
    """LK step of the reset: through reboot-lk.py to LK, set_active a, reboot to the loader."""
    serial = os.environ.get("ANDROID_SERIAL")
    if not serial or serial == "xnuloader" or any(c.isspace() for c in serial):
        return "ANDROID_SERIAL is not set, and LK is addressed by it"
    out = EVIDENCE / f"reboot-lk-cycle-{time.time_ns()}"
    prepare = WORKSPACE / "hackios-xnu-kernel/out/ios26-resume/reboot-lk-prepare/annibale-reboot-lk-prepare.bin"
    sha = "6b81e800ae789cf30adbaaa9c98768012e264c66a4e56110c6449cecf93fb7d7"
    if run([sys.executable, HERE / "reboot-lk.py", out, "--payload", prepare, "--sha256", sha,
            "--serial", serial], capture_output=True, text=True).returncode != 0:
        return "reboot-lk.py failed"
    # The shared recovery entry verifies slot B and restores A's retry count at LK.
    return ensure_loader_idle()


def slot_preflight():
    """Read the A-slot budget and reset it through LK below the three-try floor."""
    retry = loader_var("slot-retry-count:a")
    if not re.fullmatch(r"[0-7]", retry):
        return "loader did not report a valid slot A retry count"
    if int(retry) >= 3:
        return None
    print("slot A retry count is below 3; resetting through LK", flush=True)
    try:
        return checkpoint()
    except (OSError, subprocess.SubprocessError, RuntimeError) as error:
        return str(error)


def newest_log(run_dir):
    logs = sorted(run_dir.glob("s[0-9]*.log"))
    return logs[-1].read_bytes().decode("utf-8", "replace") if logs else ""


SHELL_LINE = re.compile(rb"System shell connected: <BKSystemShellClient: 0x[0-9a-f]+; SpringBoard\.(\d+);")


def unhealthy(run_dir):
    """Why iOS should not be left running after this round, or None.

    A stopped GPU refuses every new client, so SpringBoard dies whenever it next needs Metal, and backboardd
    turns the backlight off and on with each death: the whole screen flashes until the kernel is stopped
    (cam3-trace2, 2026-11-18). Both show in the round's logs: the GPU_STOP line, or SpringBoard connecting to
    backboardd as more than one process.
    """
    springboards = set()
    for log in sorted(run_dir.glob("s[0-9]*.log")):
        data = log.read_bytes()
        if GPU_STOP.encode() in data:
            return "the GPU stopped"
        springboards.update(SHELL_LINE.findall(data))
    if len(springboards) > 1:
        return f"SpringBoard ran as {len(springboards)} processes"
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("label")
    ap.add_argument("--baseline")
    ap.add_argument("--seconds", type=int, default=900)
    ap.add_argument("--kernel", default=KERNEL)
    ap.add_argument("--boot-args", default="", help="observation boot-args added after the fixed ones")
    ap.add_argument("--hold", action="store_true", help="keep the round up after the tour, for respin.py")
    ap.add_argument("--teardown", action="store_true", help="explicitly teardown and return to xnuloader after the round")
    ap.add_argument("--tour", nargs="+", help="tour.py steps instead of TOUR")
    args = ap.parse_args()
    if args.hold and "--seconds" not in sys.argv:
        args.seconds = 0
    if "ufs_write=1" not in FIXED_ARGS and "ufs_write=1" not in args.boot_args:
        args.boot_args = " ".join([args.boot_args, "ufs_write=1"]).strip()

    try:
        import numpy  # noqa: F401  (tour.py, summary.py and the screen tools read shots with it)
    except ImportError:
        print(f"{sys.executable} has no numpy: run cycle.py with an interpreter that has numpy and Pillow")
        return 1
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    # GPU up to 1100 MHz (speed 14; kernels from 12377-rate6 lower it to what the bin has, older ones
    # stop the GPU bring-up when asked for more than they list: 7 up to rate1, 10 for rate2 to rate4).
    gpu_speed = os.environ.get("GPU_SPEED", "14")
    # CYCLE_PROGRAMS=path[:path] puts more files into /annibale/bin of the image beside the ones
    # userland/build.sh stages there.
    env = dict(os.environ, GPU_SPEED=gpu_speed,
               JOBS_SOURCE=os.environ.get("JOBS_SOURCE", "tools/k90auto/jobs/rc.jobs.interactive"),
               PAYLOAD_PROGRAMS=":".join([*[p for p in BOOT_PROGRAMS if (WORKSPACE / p).exists()],
                                          *[p for p in os.environ.get("CYCLE_PROGRAMS", "").split(":") if p]]))
    with open(EVIDENCE / f"pack-{args.label}.log", "w") as log:
        if run([sys.executable, HERE / "package.py"], env=env, stdout=log, stderr=subprocess.STDOUT).returncode:
            print(f"package.py failed, see {log.name}")
            return 1
    # CYCLE_CPU_ARGS replaces the processor boot-args, as CYCLE_FIXED_ARGS does FIXED_ARGS.
    # The screen is the v57 identity's own, 1206 x 2622 at 460 ppi (from 2026-11-02): MobileGestalt then
    # picks screen class 36 and the status bar its Dynamic Island layout. The kernel's default 1125 x 2436
    # is screen class 15, the iPhone X notch layout, which puts the clock and the battery near the corners
    # (docs/analysis/2026-11-02-status-bar-layout.md). These come after --boot-args, so a round can still
    # set its own fbwidth=, fbheight= and fbpitch=.
    default_boot = ("hackios-xnu-userland/userland/flashboot.apfs"
                    if not (WORKSPACE / "hackios-xnu-kernel/userland/flashboot.apfs").is_file()
                    and (WORKSPACE / "hackios-xnu-userland/userland/flashboot.apfs").is_file()
                    else "hackios-xnu-kernel/userland/flashboot.apfs")
    payload_env = dict(os.environ, GPU_SPEED=gpu_speed,
                       CPU_ARGS=os.environ.get("CYCLE_CPU_ARGS", "cpus=4 bootcpu=7 small_cores_after=0"),
                       BOOT_IMAGE=os.environ.get("BOOT_IMAGE", default_boot),
                       MEMSIZE="300000000", IDENTITY="v57")
    made = run([sys.executable, HERE / "make-payload.py", args.kernel, args.label,
                "out/ios26-resume/bbmetal-device/root.apfs",
                " ".join(part for part in [os.environ.get("CYCLE_FIXED_ARGS", FIXED_ARGS), args.boot_args,
                                           "fbwidth=1206 fbheight=2622 fbpitch=460"] if part)],
               env=payload_env, capture_output=True, text=True)
    if made.returncode:
        print(f"make-payload.py failed: {made.stdout[-400:]}{made.stderr[-400:]}")
        return 1
    round_dir = EVIDENCE / f"kernel-{args.kernel}-{args.label}"

    problem = ensure_loader_idle()
    if problem:
        print(f"loader not ready before the round: {problem}")
        return 1
    if os.environ.get("LOADER_IMAGE") or os.environ.get("CYCLE_CHECKPOINT") == "1":
        try:
            problem = checkpoint()
        except (OSError, subprocess.SubprocessError, RuntimeError) as error:
            problem = str(error)
        if problem:
            print(f"checkpoint failed: {problem}")
            return 1
    problem = slot_preflight()
    if problem:
        print(f"slot preflight failed: {problem}")
        return 1
    out = open(EVIDENCE / f"cycle-{args.label}.out", "w")
    teardown = args.teardown
    rounder = subprocess.Popen([sys.executable, str(HERE / "round-run.py"), str(round_dir), str(args.seconds),
                                "0,0,5"], cwd=WORKSPACE, stdout=out, stderr=subprocess.STDOUT,
                               env=dict(os.environ, K90_FREEZE_OFF="1"))
    begun = time.monotonic()
    while (rounder.poll() is None and not (round_dir / "run" / "boot-unlocked").exists()
           and UNLOCK_LINE not in newest_log(round_dir / "run")):
        if time.monotonic() - begun > UNLOCK_WAIT:
            print("no boot unlock seen; the tour is skipped")
            (round_dir / "run" / "stop-request").write_text("")
            break
        time.sleep(0.5)
    if rounder.poll() is None and ((round_dir / "run" / "boot-unlocked").exists()
                                   or UNLOCK_LINE in newest_log(round_dir / "run")):
        gpu_stopped = GPU_STOP in newest_log(round_dir / "run")
        if gpu_stopped:
            print("the GPU stopped before the tour; only the home screen is taken")
        tour = args.tour or TOUR
        run([sys.executable, HERE / "tour.py", round_dir, *(tour[:1] if gpu_stopped else tour)])
        if args.hold:
            report = run([sys.executable, HERE / "render-health.py", round_dir,
                          *(["--baseline", args.baseline] if args.baseline else [])], capture_output=True, text=True)
            (round_dir / "render-report.txt").write_text(report.stdout)
            print(f"report: {round_dir / 'render-report.txt'}  sheet: {round_dir / 'run/tour-sheet.png'}")
            print(f"held: tools/k90auto/respin.py {round_dir} ... (--stop ends it)", flush=True)
        elif args.teardown:
            (round_dir / "run" / "stop-request").write_text("")
        elif (problem := unhealthy(round_dir / "run")):
            print(f"not left running: {problem}; the round is torn down instead")
            (round_dir / "run" / "stop-request").write_text("")
            teardown = True
        else:
            (round_dir / "run" / "leave-running").write_text("")
    rounder.wait()

    if not (round_dir / "render-report.txt").exists():
        report = run([sys.executable, HERE / "render-health.py", round_dir,
                      *(["--baseline", args.baseline] if args.baseline else [])], capture_output=True, text=True)
        (round_dir / "render-report.txt").write_text(report.stdout)
        print(f"report: {round_dir / 'render-report.txt'}  sheet: {round_dir / 'run/tour-sheet.png'}")

    # The round is over: its raw screenshots (11.6 MB each) become lossless PNGs in run/png, which
    # summary.py and visual-audit.py read as well; one round's 13 shots go from 171 MB to 46 MB in 6 s.
    run(["bash", HERE / "sheets.sh", round_dir / "run"], stdout=subprocess.DEVNULL)

    if teardown:
        problem = ensure_loader_idle()
        if problem:
            print(f"loader not ready after the round: {problem}")
            return 1
    return 0 if rounder.returncode == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
