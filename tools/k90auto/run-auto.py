#!/usr/bin/env python3
"""Run a payload, collect logs, take screenshots only when asked, then leave the loader idle again.

usage: tools/k90auto/run-auto.py RUN_DIR [SECONDS] [SHOT_EVERY,SHOT_FROM,LOG_EVERY]

RUN_DIR is what make-payload.py printed. Its manifest.json names the payload, helper root and small
resident boot image. The iOS system APFS volume stays on UFS and is mounted by init.

The third argument defaults to 0,100,20: no periodic screenshots, log snapshots every 20 seconds.
A periodic screenshot costs the USB channel a 11.6 MB transfer, and the log is what a round is read
from, so the default spends the channel on logs. SHOT_EVERY>0 still takes a shot every that many
seconds from SHOT_FROM on, for a round that wants a time series instead of the log.

Commands for the running iOS go the same way: tools/k90auto/rsh.py drops RUN_DIR/run/cmd-request-*.txt,
the run sends each one with `oem sh` (to /annibale/bin/rwsh, which must be in the round's rc.jobs),
writes the loader's answer to cmd-reply-*.json and reads the log a few times over the next 18 s
into cmd-SEQ.log, which is where rsh.py finds the output. A file for the running iOS goes the same
way: RUN_DIR/run/push-request-*.txt names a host file of at most 16 MB, the run sends it with
`oem push` and `stage` into the kernel's inbox and writes push-reply-*.json; rwsh "pull" then writes
it on the phone (tools/k90auto/install-ipa.py).

Screenshots are otherwise on demand. A run watches RUN_DIR/shot-request; whoever performed an action
worth recording writes that file (tools/k90auto/shot-now.py does it), and the run takes exactly one
shot when it next looks, named by the elapsed second the shot was taken at, so the file name still
reads the same way as in the rounds taken with a fixed interval. Set SHOT_ON_ACTION=0 to ignore the
request file.

Teardown saves logs before resetting a returned or hung kernel. Unsupported or malformed states
preserve the device state and stop the queue.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import time

WORKSPACE = Path(__file__).resolve().parents[2]
def digest(path):
    result = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            result.update(chunk)
    return result.hexdigest()


def payload_entries(path):
    """Read XNUP entry names and hashes without loading the whole payload into memory."""
    entries = {}
    total = path.stat().st_size
    with path.open("rb") as source:
        header = source.read(8)
        if len(header) != 8:
            raise SystemExit(f"refusing to run: {path} has no complete XNUP header")
        magic, body_size = struct.unpack("<II", header)
        if magic != 0x50554E58 or body_size != total - 8:
            raise SystemExit(f"refusing to run: {path} has an invalid XNUP size or signature")
        offset, ended = 8, False
        while offset < total:
            raw = source.read(24)
            if len(raw) != 24:
                break
            offset += 24
            if not any(raw):
                ended = offset == total
                break
            name_raw, size, _reserved = struct.unpack("<16sII", raw)
            try:
                name = name_raw.split(b"\0", 1)[0].decode("ascii")
            except UnicodeDecodeError as error:
                raise SystemExit(f"refusing to run: {path} has a non-ASCII entry name") from error
            if not name or name in entries or b"\0" not in name_raw:
                raise SystemExit(f"refusing to run: {path} has an invalid or duplicate entry name")
            hasher = hashlib.sha256()
            value = bytearray() if name in ("cmdline", "memsize") else None
            if value is not None and size > 4096:
                raise SystemExit(f"refusing to run: oversized {name} entry")
            remaining = size
            while remaining:
                chunk = source.read(min(1 << 20, remaining))
                if not chunk:
                    raise SystemExit(f"refusing to run: {path} ends inside entry {name}")
                hasher.update(chunk)
                if value is not None:
                    value.extend(chunk)
                remaining -= len(chunk)
            offset += size
            padding = (-size) % 16
            if len(source.read(padding)) != padding:
                raise SystemExit(f"refusing to run: {path} ends inside entry padding")
            offset += padding
            entries[name] = {"bytes": size, "sha256": hasher.hexdigest()}
            if value is not None:
                if not value.endswith(b"\0") or b"\0" in value[:-1]:
                    raise SystemExit(f"refusing to run: invalid {name} terminator")
                entries[name]["text"] = value[:-1].decode("ascii")
    if not ended:
        raise SystemExit(f"refusing to run: {path} has no final XNUP terminator")
    return entries


base = Path(sys.argv[1])
duration = int(sys.argv[2]) if len(sys.argv) > 2 else 240
shot_every, shot_from, log_every = (int(x) for x in (sys.argv[3] if len(sys.argv) > 3 else "0,100,20").split(","))
# A request file is how an action taken outside this process asks for one shot. The run unlinks it
# before shooting, so a request that arrives while the shot is being staged is served next time.
shot_on_action = os.environ.get("SHOT_ON_ACTION", "1") != "0"
# A desktop that stops producing frames never ends a fixed-length round by itself: the kernel keeps
# logging and the loader keeps answering running until the clock runs out. The round therefore ends
# early once frames have stopped for this many seconds, which is about one snapshot interval plus
# the snapshot cadence. K90_FREEZE_SECONDS=0 or K90_FREEZE_OFF=1 keeps the old fixed-length behaviour.
freeze_seconds = int(os.environ.get("K90_FREEZE_SECONDS", "20"))
freeze_watch = freeze_seconds > 0 and os.environ.get("K90_FREEZE_OFF", "0") != "1"
manifest = json.loads((base / "manifest.json").read_text())
# A failed pack leaves no new payload behind, and the queue used to run whatever directory it was
# handed: on 2026-10-28 make-payload.py stopped on an existing directory and the round ran the first
# version of the payload instead, with none of that round's changes in it. The run therefore starts
# only when both files still hash to what the manifest recorded, and when they also match what the
# operator says they should be. The two hashes go into the run log so a later reader can tell which
# payload a round actually booted without asking anyone.
payload_path = WORKSPACE / manifest["payload"]["path"]
ramdisk_path = WORKSPACE / manifest["ramdisk"]["path"]
resident_boot = manifest.get("resident_boot")
if (manifest.get("root_apfs") != "ufs_darwin" or not isinstance(resident_boot, dict)
        or not {"path", "bytes", "sha256"} <= resident_boot.keys()
        or type(resident_boot.get("bytes")) is not int):
    raise SystemExit(f"refusing to run: {base}/manifest.json uses the old resident system-image format")
boot_image = WORKSPACE / resident_boot["path"]
if not 0 < resident_boot["bytes"] <= 64 * 1024 * 1024:
    raise SystemExit(f"refusing to run: resident boot image is {resident_boot['bytes']} bytes; limit is 67108864")
if not boot_image.is_file():
    raise SystemExit(f"refusing to run: the resident boot image {boot_image} named by {base}/manifest.json is gone")
if boot_image.stat().st_size != resident_boot["bytes"]:
    raise SystemExit(f"refusing to run: resident boot image size is {boot_image.stat().st_size}, "
                     f"manifest records {resident_boot['bytes']}")
for what, path, stated in (("payload", payload_path, manifest["payload"]["sha256"]),
                           ("packed root", ramdisk_path, manifest["ramdisk"]["sha256"]),
                           ("resident boot image", boot_image, resident_boot["sha256"])):
    if not path.is_file():
        raise SystemExit(f"refusing to run: the {what} {path} named by {base}/manifest.json is gone")
    actual = digest(path)
    if actual != stated:
        raise SystemExit(f"refusing to run: the {what} {path} hashes to {actual[:16]} but its manifest "
                         f"recorded {stated[:16]}; this directory does not describe the file in it")
expected = {"payload": manifest["payload"]["sha256"], "root": manifest["ramdisk"]["sha256"]}
for name, key in (("payload", "EXPECT_PAYLOAD_SHA256"), ("root", "EXPECT_ROOT_SHA256"),
                  ("boot", "EXPECT_BOOT_SHA256")):
    wanted = os.environ.get(key)
    actual = resident_boot["sha256"] if name == "boot" else expected[name]
    if wanted and wanted != actual:
        raise SystemExit(f"refusing to run: {key}={wanted[:16]} but this payload's {name} is "
                         f"{actual[:16]}; the pack that was meant to produce it did not")
entries = payload_entries(payload_path)
if {"kernel", "ramdisk", "cmdline"} - entries.keys():
    raise SystemExit(f"refusing to run: payload entries are incomplete: {sorted(entries)}")
if {"rdimage", "rdfile", "rdres"} & entries.keys():
    raise SystemExit("refusing to run: unattended payload contains a resident-image entry")
if entries["ramdisk"] != {"bytes": ramdisk_path.stat().st_size, "sha256": manifest["ramdisk"]["sha256"]}:
    raise SystemExit("refusing to run: payload helper root does not match its manifest")
cmdline = entries["cmdline"]["text"]
if cmdline != manifest.get("cmdline"):
    raise SystemExit("refusing to run: payload cmdline differs from its manifest")
for key, value in (("rootdev", "md0"), ("root_apfs", "ufs_darwin"), ("ufs", "2"), ("ufs_native", "1")):
    if [arg for arg in cmdline.split() if arg.split("=", 1)[0] == key] != [f"{key}={value}"]:
        raise SystemExit(f"refusing to run: payload requires exactly one {key}={value}")
if any(arg.split("=", 1)[0] == "rd" for arg in cmdline.split()):
    raise SystemExit("refusing to run: rd= makes launchd boot as a restore environment")
window_bytes = int(entries.get("memsize", {}).get("text", "180000000"), 16)
if window_bytes <= 0 or window_bytes % 0x2000000 or window_bytes > 0x380000000:
    raise SystemExit("refusing to run: invalid payload memory window")
print(f"GUARD payload={expected['payload'][:16]} root={expected['root'][:16]} dir={base.name}")
run = base / "run"
# A run directory is one run's record: files left by an earlier attempt would be read as this one's.
assert not run.exists() or not any(run.iterdir()), f"{run} is not empty"
run.mkdir(exist_ok=True)
shot_request = run / "shot-request"

# The loader calls a kernel that stopped answering hung-held once it has been silent for its own
# SILENCE_SECONDS (50 in loader_02_platform_cpu_ufs_survey.inc); a stop is only answered before that.
# K90_STOP_WAIT shortens the wait, which the offline tests use.
STOP_WAIT_SECONDS = int(os.environ.get("K90_STOP_WAIT", "70"))


def call(args, cap=10, check=True):
    start = time.monotonic()
    try:
        result = subprocess.run(["fastboot", "-s", "xnuloader", *map(str, args)], stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, text=True, timeout=cap)
        rc, output = result.returncode, result.stdout
    except subprocess.TimeoutExpired as error:
        rc, output = 124, str(error.stdout or "")
    record = {"args": list(map(str, args)), "rc": rc, "output": output, "host_monotonic": start,
              "seconds": time.monotonic() - start}
    with (run / "commands.jsonl").open("a") as stream:
        stream.write(json.dumps(record) + "\n")
    if check:
        assert rc == 0 and "FAILED" not in output, record
    return record


def state():
    """Return the loader state; an unanswered or ambiguous query stops teardown without reset."""
    return variable("result", check=False).split()[0]


def fresh_loader():
    """Idle over an empty RAM disk: the state a run starts from, and the state a reset ends in."""
    return (variable("product", check=False) == "xnuloader" and
            re.fullmatch(r"idle(?: 0 0)?", variable("result", check=False)) is not None and
            re.fullmatch(r"idle 0 0 [0-9a-fA-F]+", variable("ramdisk-state", check=False)) is not None)


def variable(key, check=True):
    """One getvar's value. fastboot prints the bootloader's answer among its own progress lines,
    sometimes with a "(bootloader) " prefix, so the value is what follows the key on its line."""
    reply = call(["getvar", key], 8, check)
    output = reply["output"]
    values = re.findall(r"^(?:\(bootloader\)[ \t]*)?" + re.escape(key) + r":[ \t]*([^\r\n]*?)[ \t\r]*$", output, re.M)
    if reply["rc"] == 0 and "FAILED" not in output and len(values) == 1 and values[0]:
        return values[0]
    assert not check, f"loader did not report {key}: {output}"
    return "unknown"


payload = payload_path
# The loader's build-id says which build is resident; a build without the RAM disk protocol would
# silently mis-stage, so the capability is what this checks and the identity is what it records.
loader_build_id = variable("build-id")
assert variable("ramdisk-protocol") == "1", "the loader does not offer the RAM disk protocol"
assert fresh_loader(), "loader is not idle over an empty RAM disk; refusing to overwrite resident data"
call(["stage", payload], 25)
call(["oem", "ramdisk"])
call(["stage", boot_image], 120)
ready = call(["getvar", "ramdisk-state"])["output"]
match = re.search(r"ramdisk-state:\s*ready\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)\s+([0-9a-fA-F]+)", ready)
assert match and int(match.group(1), 16) == resident_boot["bytes"] and \
    int(match.group(2), 16) == resident_boot["bytes"] and int(match.group(3), 16) == window_bytes, ready
start = time.monotonic()
call(["oem", "run"])
print("RUN_STARTED", flush=True)


FRAME_LINE = re.compile(r"^tl: v (\d+) ready (\d+) shown (\d+) done (\d+)", re.M)
TL_LINE = re.compile(r"^tl: .+ (\d+)$", re.M)
STILL_NO_FRAMES = re.compile(r"framewatch: still no frames, (\d+) s")


def frame_progress(path):
    """What a snapshot says about frames: highest id, when that frame finished, the newest tl:
    timestamp anywhere in it, and the largest gap between consecutive frames' `done` values. A
    snapshot that does not exist yet reads as no frames, which the caller treats as no progress."""
    if not path.is_file():
        return None
    text = path.read_text(errors="replace")
    quiet = max((int(x) for x in STILL_NO_FRAMES.findall(text)), default=0)
    frames = FRAME_LINE.findall(text)
    if not frames:
        # A snapshot with no frame lines at all still carries framewatch's own count of quiet
        # seconds, which is the only freeze signal once the ring has aged every frame line out.
        return {"frame_id": None, "frame_done_us": None, "newest_tl_us": None,
                "max_gap_seconds": 0.0, "quiet_seconds": quiet}
    ids = [int(f[0]) for f in frames]
    done = [int(f[3]) for f in frames]
    newest_tl = max((int(x) for x in TL_LINE.findall(text)), default=0)
    gaps = [(b - a) / 1e6 for a, b in zip(done, done[1:]) if b >= a]
    last = max(range(len(frames)), key=lambda i: done[i])
    return {"frame_id": ids[last], "frame_done_us": done[last], "newest_tl_us": newest_tl,
            "max_gap_seconds": round(max(gaps), 3) if gaps else 0.0, "quiet_seconds": quiet}


# Seconds after `oem sh` at which the log is read into cmd-SEQ.log: a built-in answers within the
# first, a program rwsh spawns is killed after 15 s.
CMD_FOLLOW_SECONDS = (2, 5, 10, 18)
command_reads = []      # (host time due, seq)


def serve_commands():
    """Send the commands rsh.py left, oldest first, and read the log when their output is due."""
    for request in sorted(run.glob("cmd-request-*.txt")):
        text = request.read_text().strip()
        request.unlink()
        record = call(["oem", "sh", text], 8, False)
        # fastboot prints the loader's INFO answer, the new sequence number, as "(bootloader) N"
        match = re.search(r"^\(bootloader\) (\d+)\s*$", record["output"], re.M)
        seq = int(match.group(1)) if match and record["rc"] == 0 and "FAILED" not in record["output"] else None
        reply = run / request.name.replace("cmd-request-", "cmd-reply-").replace(".txt", ".json")
        reply.write_text(json.dumps({"text": text, "seq": seq, "rc": record["rc"],
                                     "output": record["output"]}) + "\n")
        if seq is not None:
            command_reads.extend((time.monotonic() + after, seq) for after in CMD_FOLLOW_SECONDS)
    for due in sorted(item for item in command_reads if item[0] <= time.monotonic()):
        command_reads.remove(due)
        if call(["oem", "log"], 8, False)["rc"] == 0:
            call(["get_staged", run / f"cmd-{due[1]}.log"], 20, False)


def serve_pushes():
    """Put each file a push request names into the running kernel's inbox, oldest first."""
    for request in sorted(run.glob("push-request-*.txt")):
        path = request.read_text().strip()
        request.unlink()
        pushed = call(["oem", "push"], 8, False)
        staged = call(["stage", path], 60, False) if pushed["rc"] == 0 and "FAILED" not in pushed["output"] else pushed
        ok = staged["rc"] == 0 and "FAILED" not in staged["output"]
        reply = run / request.name.replace("push-request-", "push-reply-").replace(".txt", ".json")
        reply.write_text(json.dumps({"path": path, "ok": ok, "output": staged["output"][-300:]}) + "\n")


def take_shot(elapsed):
    """One screenshot at the given elapsed second. The name keeps the fixed-interval format so a
    reader converts a file name to a moment the same way it did for the earlier rounds."""
    if call(["oem", "screenshot"], 8, False)["rc"] == 0:
        call(["get_staged", run / f"shot-{int(elapsed * 10):05d}.raw"], 30, False)


index = 0
failed = None
last_shot = -1e9
shots = 0
progress = None          # the newest snapshot's frame reading
progress_wall = None    # host time that reading was taken at
last_frame_id = -1
frozen = None
while duration <= 0 or time.monotonic() - start < duration:
    elapsed = time.monotonic() - start
    # RUN_DIR/run/stop-request ends a long interactive round early, through the normal teardown.
    if (run / "stop-request").exists():
        (run / "stop-request").unlink()
        print("STOP_REQUESTED", round(elapsed, 1), flush=True)
        break
    name = state()
    if name != "running":
        failed = {"state": name, "elapsed_seconds": elapsed}
        print("NOT_RUNNING", name, flush=True)
        break
    if elapsed >= log_every * index:
        if call(["oem", "log"], 8, False)["rc"] == 0:
            call(["get_staged", run / f"s{index:03d}.log"], 20, False)
        snap_path = run / f"s{index:03d}.log"
        index += 1
        if freeze_watch:
            reading = frame_progress(snap_path)
            if reading is not None:
                if reading["frame_id"] is not None and reading["frame_id"] != last_frame_id:
                    last_frame_id = reading["frame_id"]
                    progress_wall = time.monotonic()
                no_new = None if progress_wall is None else time.monotonic() - progress_wall
                # Three independent readings of the same stop: frames did not advance since the
                # last snapshot, the newest frame already trails the newest line by the threshold,
                # or framewatch itself has counted that many quiet seconds.
                if reading["frame_done_us"] is None:
                    trailing = 0.0
                else:
                    trailing = (reading["newest_tl_us"] - reading["frame_done_us"]) / 1e6
                quiet = reading["quiet_seconds"]
                if (no_new is not None and no_new >= freeze_seconds) or trailing >= freeze_seconds \
                        or quiet >= freeze_seconds:
                    progress = reading
                    frozen = {"elapsed_seconds": elapsed, "snapshot": snap_path.name,
                              "last_frame_id": last_frame_id,
                              "no_new_frame_seconds": None if no_new is None else round(no_new, 2),
                              "frame_trailing_seconds": round(trailing, 2),
                              "framewatch_quiet_seconds": quiet,
                              "max_frame_gap_seconds": reading["max_gap_seconds"]}
                    print(f"FROZEN_AT {elapsed:.1f}", flush=True)
                    failed = {"state": "frozen", "elapsed_seconds": elapsed}
                    break
                progress = reading
    if shot_every > 0 and elapsed >= shot_from and elapsed - last_shot >= shot_every:
        last_shot = elapsed
        take_shot(elapsed)
        shots += 1
    if shot_on_action and shot_request.exists():
        shot_request.unlink()
        take_shot(elapsed)
        shots += 1
    serve_commands()
    serve_pushes()
    time.sleep(0.5)
print("SAMPLED_SECONDS", time.monotonic() - start, "failed_call", failed, flush=True)


FETCH_LINE = re.compile(rb"fetch: (\w+) 0x([0-9a-f]+) 0x([0-9a-f]+)")


def fetch_regions():
    """What the kernel kept in its window for the host, by the "fetch: NAME ADDRESS LENGTH" lines of
    the logs saved so far (the Wi-Fi card's RAM dump with pcie_rddm=1): the last line per name."""
    found = {}
    for path in sorted(run.glob("*.log")):
        for match in FETCH_LINE.finditer(path.read_bytes()):
            found[match.group(1).decode()] = (match.group(2).decode(), match.group(3).decode())
    return found


def teardown():
    """Save available logs and reset only supported terminal states. Return the final observed
    state and whether the reset command was acknowledged.

    Every action re-reads the state. `oem stop` only asks: a kernel that held the GPU stops
    answering, and the loader reports hung-held once that kernel has been silent for its own 50 s,
    which is far longer than the stop takes to be acknowledged. A reboot is refused while a kernel
    is running, so a state that never leaves running is reported instead of reset."""
    stopped = False
    for _ in range(3):
        name = state()
        if name == "unknown":
            return name, False
        if name == "idle":
            return name, False
        if name == "running":
            if stopped:
                call(["oem", "log"], 8, False)
                call(["get_staged", run / "running.log"], 40, False)
                return name, False
            stopped = True
            call(["oem", "stop"], 20, False)
            deadline = time.monotonic() + STOP_WAIT_SECONDS
            while time.monotonic() < deadline and state() == "running":
                time.sleep(1)
            continue
        # The HUNG branch composed the kernel log into the staging area already; "oem log" would
        # compose the loader's own serial log over it (32,767 bytes, `log_buf`), which is how the
        # 2026-10-27 rounds lost the stop-side lines. Take that snapshot first and keep both.
        call(["get_staged", run / f"{name}.log"], 40, False)
        call(["oem", "log"], 8, False)
        call(["get_staged", run / f"{name}-serial.log"], 40, False)
        if name not in ("returned", "returned-held", "hung", "hung-held"):
            return name, False
        if re.fullmatch(re.escape(name) + r"(?: [0-9]+ 0)?", variable("result", check=False)) is None:
            return "unknown", False
        # the reset below clears what the kernel kept for the host, so it is saved first, as NAME.bin
        for label, (address, length) in fetch_regions().items():
            staged = call(["oem", "stage", address, length], 8, False)
            if staged["rc"] == 0 and "FAILED" not in staged["output"]:
                call(["get_staged", run / f"{label}.bin"], 120, False)
        # A kernel that came back ("returned"; one that held the GPU never does) leaves its file for
        # the host (rwsh "outbox", kern.annibale.outbox) as the run's recording; without one: FAIL.
        staged = call(["oem", "recording"], 8, False) if name == "returned" else None
        if staged and staged["rc"] == 0 and "FAILED" not in staged["output"]:
            call(["get_staged", run / "outbox.bin"], 300, False)
        reply = call(["reboot"], 10, False)
        return name, reply["rc"] == 0 and "FAILED" not in reply["output"]
    return state(), False


left, reset = teardown()
off_seen, mode, seconds = False, "unknown", 0.0
if left == "idle":
    mode = "loader"               # nothing was reset, so the loader never went away
elif reset:
    watch = time.monotonic()
    while time.monotonic() - watch < 90:
        devices = subprocess.run(["fastboot", "devices"], capture_output=True, text=True, timeout=3).stdout
        if "xnuloader" in devices:
            # A reset can finish between two polls, so the gap is recorded rather than required:
            # a loader that answers idle over an empty RAM disk is the fresh one the next run needs.
            if fresh_loader():
                mode = "loader"
                break
        else:
            off_seen = True
            android = subprocess.run(["adb", "devices"], capture_output=True, text=True, timeout=3).stdout
            if "\tdevice" in android:
                mode = "android"
                break
        time.sleep(1)
    seconds = time.monotonic() - watch
summary = {"off_seen": off_seen, "mode": mode, "seconds": seconds, "left": left, "reset": reset,
           "failed": failed, "samples": index, "loader_build_id": loader_build_id,
           "payload_sha256": manifest["payload"]["sha256"],
           "resident_boot_sha256": resident_boot["sha256"],
           "status": call(["getvar", "result"], 8, False)["output"] if mode == "loader" else None,
           # the daily evidence for "the device never stays somewhere only a person can leave it":
           # after every round the loader must still identify as xnuloader and answer idle.
           "product": call(["getvar", "product"], 8, False)["output"] if mode == "loader" else None}
# Log sizes are what the round's coverage claim rests on, so the teardown records them instead of
# leaving the reader to stat the directory.
summary["shots"] = shots
if frozen is not None:
    summary["frozen"] = frozen
summary["logs"] = {path.name: path.stat().st_size
                   for path in sorted(run.glob("*.log"))}
summary["ready_for_next_run"] = mode == "loader" and fresh_loader()
(run / "reboot.json").write_text(json.dumps(summary, indent=2) + "\n")
print("REBOOT_END", summary, flush=True)
if failed is not None or not summary["ready_for_next_run"]:
    sys.exit(1)
