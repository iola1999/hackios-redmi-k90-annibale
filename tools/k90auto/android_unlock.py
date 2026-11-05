#!/usr/bin/env python3
"""One-shot automated unlock and stay-awake script for Android.

Wakes the screen, swipes up to reveal the PIN pad, types the PIN, sets power stay-on
while plugged in and extended display timeout, and verifies the resulting awake/unlocked state.

Usage:
    export ANDROID_SERIAL=...
    export ANDROID_UNLOCK_PIN=...
    python3 tools/k90auto/android_unlock.py [--pin PIN] [--serial SERIAL]
"""
import argparse
import os
import subprocess
import sys
import time


def adb_cmd(args, serial=None, timeout=15):
    cmd = ["adb"]
    if serial:
        cmd.extend(["-s", serial])
    cmd.extend(args)
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    return res.stdout.strip(), res.stderr.strip(), res.returncode


def main():
    parser = argparse.ArgumentParser(description="One-shot Android unlock and stay-awake script")
    parser.add_argument("--pin", default=os.environ.get("ANDROID_UNLOCK_PIN"), help="Lockscreen PIN (default: $ANDROID_UNLOCK_PIN)")
    parser.add_argument("--serial", default=os.environ.get("ANDROID_SERIAL", ""), help="Target device serial (default: $ANDROID_SERIAL)")
    args = parser.parse_args()

    serial = args.serial
    if not serial:
        sys.exit("Error: device serial not specified (set ANDROID_SERIAL or use --serial)")

    pin = args.pin
    if not pin:
        sys.exit("Error: PIN not specified (set ANDROID_UNLOCK_PIN or use --pin)")

    print(f"[*] Starting one-shot unlock sequence on device {serial}...", flush=True)

    # Shell script executed in a single ADB session to prevent intermediate timeouts
    shell_script = (
        "input keyevent 224 && "
        "sleep 0.3 && "
        "input swipe 540 2000 540 500 150 && "
        "sleep 0.5 && "
        f"input text {pin} && "
        "input keyevent 66 && "
        "sleep 0.5 && "
        "svc power stayon true && "
        "settings put global stay_on_while_plugged_in 3 && "
        "settings put system screen_off_timeout 1800000"
    )

    out, err, code = adb_cmd(["shell", shell_script], serial=serial, timeout=20)
    if code != 0:
        print(f"[!] Warning: unlock sequence command exited with {code}: {err}", flush=True)

    # Verification queries
    power_out, _, _ = adb_cmd(["shell", "dumpsys", "power"], serial=serial)
    wake_line = [l for l in power_out.splitlines() if "mWakefulness=" in l]
    wake_state = wake_line[0].strip() if wake_line else "unknown"

    window_out, _, _ = adb_cmd(["shell", "dumpsys", "window"], serial=serial)
    dream_line = [l for l in window_out.splitlines() if "mDreamingLockscreen=" in l]
    dream_state = dream_line[0].strip() if dream_line else "unknown"

    trust_out, _, _ = adb_cmd(["shell", "dumpsys", "trust"], serial=serial)
    locked_line = [l for l in trust_out.splitlines() if "deviceLocked=" in l]
    locked_state = locked_line[0].strip() if locked_line else "unknown"

    print(f"[*] Verification readings:\n    {wake_state}\n    {dream_state}\n    {locked_state}", flush=True)

    is_awake = "mWakefulness=Awake" in wake_state
    is_unlocked = "deviceLocked=0" in locked_state or "mDreamingLockscreen=false" in dream_state

    if is_awake and is_unlocked:
        print("[+] Screen unlocked and stay-on configured successfully.", flush=True)
        return 0
    elif is_awake:
        print("[*] Screen awake and stay-on configured; check lockscreen state.", flush=True)
        return 0
    else:
        print("[-] Unlock verification failed.", flush=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
