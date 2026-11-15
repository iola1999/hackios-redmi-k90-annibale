#!/usr/bin/env python3
"""Run one command on the iOS that a round is running, and print its output.

usage: tools/k90auto/rsh.py ROUND_DIR COMMAND...
       tools/k90auto/rsh.py - COMMAND...

ROUND_DIR is the directory make-payload.py printed and run-auto.py is running. The round must carry
/annibale/bin/annsh in its rc.jobs and boot a kernel and loader with the command mailbox (kernel
loader_live magic3, loader "oem sh"). run-auto.py stays the only process that talks to the device:
this drops the command into ROUND_DIR/run/cmd-request-*.txt and waits for run-auto.py to send it
and to read the log into ROUND_DIR/run/cmd-SEQ.log. Later completion can also be read from
the latest periodic s*.log snapshot.

A round that run-auto.py left running on the device (cycle.py without --hold or --teardown; its
run/reboot.json says "left": "running-held") has no run-auto.py to relay commands. For it, and for
"-" in place of ROUND_DIR, this sends the command itself with fastboot oem sh and reads the
loader's log until the command ends. Use that only while no other process talks to the device.

The command is one line of at most 119 UTF-8 bytes, words split on blanks with no quoting; the
built-ins are listed in hackios-xnu-userland/userland/src/apps/annsh.c. annsh applies its own
command deadline, and a slow native call can also finish after the default output wait. Set
RSH_OUTPUT_TIMEOUT for callers that need a longer observation window.

Exit status: the command's own, 2 when it could not be sent, 3 when no end of its output arrived.
"""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

SEND_TIMEOUT = int(os.environ.get("RSH_SEND_TIMEOUT", "30"))  # run-auto.py looks at requests every half second
OUTPUT_TIMEOUT = int(os.environ.get("RSH_OUTPUT_TIMEOUT", "40"))  # Native calls and log snapshots can outlast the default wait


def end_pattern(seq):
    return re.compile(rf"^annsh {seq} exit (-?\d+) (\d+) ms$", re.M)


def finish(seq, text_seen, where):
    """Print the output lines of command SEQ and return its exit status, or 3 without its end."""
    line_mark = f"annsh {seq}| "
    for line in text_seen.splitlines():
        if line.startswith(line_mark):
            print(line[len(line_mark):])
        elif line.startswith(f"annsh {seq} dropped"):
            print(f"rsh: {line}", file=sys.stderr)
    done = end_pattern(seq).search(text_seen)
    if done is None:
        started = f"annsh {seq} start" in text_seen
        print(f"rsh: no end of the output in {where}"
              f"{'' if started else ', and annsh never started it (is /annibale/bin/annsh in rc.jobs?)'}; "
              f"later lines may be in the round's next s*.log", file=sys.stderr)
        return 3
    # Keep buffered native output before the completion record in merged logs.
    sys.stdout.flush()
    print(f"rsh: exit {done.group(1)} after {done.group(2)} ms", file=sys.stderr)
    return int(done.group(1)) & 0xff


def direct(text):
    """Send TEXT with fastboot oem sh and read the loader's log until the command ends."""
    sent = subprocess.run(["fastboot", "-s", "xnuloader", "oem", f"sh {text}"], capture_output=True, text=True)
    match = re.search(r"^\(bootloader\) (\d+)\s*$", sent.stdout + sent.stderr, re.M)
    if sent.returncode != 0 or match is None:
        print(f"rsh: the loader did not take the command:\n{sent.stdout}{sent.stderr}", file=sys.stderr)
        return 2
    seq = int(match.group(1))
    end = end_pattern(seq)
    log = Path(f"/tmp/rsh-direct-{seq}-{os.getpid()}.log")
    text_seen = ""
    deadline = time.monotonic() + OUTPUT_TIMEOUT
    try:
        while time.monotonic() < deadline:
            time.sleep(0.3)
            subprocess.run(["fastboot", "-s", "xnuloader", "oem", "log"], capture_output=True)
            pulled = subprocess.run(["fastboot", "-s", "xnuloader", "get_staged", str(log)], capture_output=True)
            if pulled.returncode == 0 and log.exists():
                text_seen = log.read_text(errors="replace")
                if end.search(text_seen):
                    break
    finally:
        log.unlink(missing_ok=True)
    return finish(seq, text_seen, "the loader log")


def via_round(run, text):
    """Hand TEXT to the run-auto.py of RUN and read its cmd-SEQ.log and snapshots."""
    name = f"cmd-request-{time.time_ns()}-{os.getpid()}"
    partial = run / f".{name}.tmp"
    partial.write_text(text + "\n")
    partial.rename(run / f"{name}.txt")

    reply = run / f"cmd-reply-{name[len('cmd-request-'):]}.json"
    deadline = time.monotonic() + SEND_TIMEOUT
    while not reply.exists():
        if time.monotonic() > deadline:
            print("rsh: run-auto.py did not pick the command up; is the round still running?", file=sys.stderr)
            return 2
        time.sleep(0.3)
    answer = json.loads(reply.read_text())
    if answer["seq"] is None:
        print(f"rsh: the loader did not take the command:\n{answer['output'].strip()}", file=sys.stderr)
        return 2
    seq = answer["seq"]

    log = run / f"cmd-{seq}.log"
    end = end_pattern(seq)
    deadline = time.monotonic() + OUTPUT_TIMEOUT
    text_seen = ""
    while time.monotonic() < deadline:
        logs = [log]
        snapshots = [path for path in run.glob("s*.log") if re.fullmatch(r"s[0-9]+\.log", path.name)]
        if snapshots:
            logs.append(max(snapshots, key=lambda path: int(path.stem[1:])))
        for source in logs:
            if source.exists():
                candidate = source.read_text(errors="replace")
                if source == log or end.search(candidate):
                    text_seen = candidate
            if end.search(text_seen):
                break
        if end.search(text_seen):
            break
        time.sleep(0.1)
    return finish(seq, text_seen, log.name)


def left_running(run):
    try:
        return json.loads((run / "reboot.json").read_text()).get("left") == "running-held"
    except (OSError, ValueError):
        return False


def main():
    if len(sys.argv) < 3:
        print(__doc__.strip())
        return 2
    target, text = sys.argv[1], " ".join(sys.argv[2:]).strip()
    if not text or len(text.encode("utf-8")) > 119 or "\n" in text or "\r" in text:
        print("rsh: the command must be one line of 1 to 119 UTF-8 bytes", file=sys.stderr)
        return 2
    if target == "-":
        return direct(text)
    run = Path(target) / "run"
    if run.is_dir() and not (run / "reboot.json").exists():
        return via_round(run, text)
    if run.is_dir() and left_running(run):
        return direct(text)
    print(f"rsh: {run} is not a running round", file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
