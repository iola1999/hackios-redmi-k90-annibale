#!/usr/bin/env python3
"""Copy one file off the iOS a round is running.

usage: tools/k90auto/fetch.py ROUND_DIR DEVICE_PATH OUT     (ROUND_DIR "-": the running iOS, no round)

When nothing else talks to the device (a round left running-held, or "-"), annsh "outbox PATH" copies
the file into one physical piece of kernel memory, whose address the kernel logs ("outbox: N bytes for
the host at 0x..."); "oem stage ADDRESS LENGTH" and "get_staged" read it at USB speed (71 KB in
0.07 s on 2026-11-15, against about 10 KB/s for "cat"). While run-auto.py still runs the round, or
when the outbox fails, the file comes through "cat" instead: each "cat PATH OFFSET" answers as many
48-byte lines as fit in one command's output and says where the next one starts ("cat end SIZE next
AT"); this asks again from there until the whole file is read. OUT is written only after all offset,
Base64, footer and size checks pass. A failed read preserves its verified prefix in OUT.partial.
Exit status: 0 for a complete file, 1 for a failed read.
"""
import base64
import json
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAX_RETRIES = 3   # re-reads of one chunk after a dropped console line or a missing footer


def fastboot(*args, timeout=60):
    return subprocess.run(["fastboot", "-s", "xnuloader", *args], capture_output=True, text=True, timeout=timeout)


def via_outbox(round_dir, path, out):
    """The file through kern.annibale.outbox, or None when that way does not work here."""
    if round_dir != "-":
        try:
            held = json.loads((Path(round_dir) / "run/reboot.json").read_text()).get("left") == "running-held"
        except (OSError, ValueError):
            held = False
        if not held:
            return None   # run-auto.py owns the USB channel and stages its own logs in between
    result = subprocess.run([sys.executable, str(HERE / "rsh.py"), round_dir, "outbox", path],
                            capture_output=True, text=True)
    m = re.search(r"outbox \S+: (\d+) of \1 bytes", result.stdout)
    if result.returncode != 0 or m is None:
        print(f"fetch: outbox failed ({result.stdout.strip() or result.stderr.strip()}); using cat", file=sys.stderr)
        return None
    size = int(m.group(1))
    log = out.with_name(out.name + ".log")
    try:
        fastboot("oem", "log")
        fastboot("get_staged", str(log))
        found = re.findall(rf"outbox: {size} bytes for the host at (0x[0-9a-f]+)", log.read_text(errors="replace"))
    finally:
        log.unlink(missing_ok=True)
    if not found:
        print("fetch: the kernel log has no outbox address; using cat", file=sys.stderr)
        return None
    staged = out.with_name(out.name + ".staged")
    if (fastboot("oem", f"stage {found[-1][2:]} {size:x}").returncode != 0
            or fastboot("get_staged", str(staged)).returncode != 0 or staged.stat().st_size != size):
        staged.unlink(missing_ok=True)
        print("fetch: staging the outbox failed; using cat", file=sys.stderr)
        return None
    staged.replace(out)
    print(f"fetch: {path}: {size} bytes to {out} (outbox)")
    return 0


def incomplete(out, data):
    partial = out.with_name(out.name + ".partial")
    try:
        partial.write_bytes(data)
    except OSError as error:
        print(f"fetch: incomplete: could not write {partial}: {error}", file=sys.stderr)
    else:
        print(f"fetch: incomplete: saved {len(data)} verified bytes to {partial}", file=sys.stderr)
    return 1


def main():
    if len(sys.argv) != 4:
        print(__doc__.strip())
        return 1
    round_dir, path, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    done = via_outbox(round_dir, path, out)
    if done is not None:
        return done
    data = bytearray()
    retries = 0
    while True:
        before = len(data)
        result = subprocess.run([sys.executable, str(HERE / "rsh.py"), round_dir, "cat", path, str(before)],
                                capture_output=True, text=True)
        if result.returncode != 0:
            if retries < MAX_RETRIES:
                retries += 1
                print(f"fetch: rsh exit {result.returncode} at offset {before}, retry {retries}/{MAX_RETRIES}",
                      file=sys.stderr)
                continue
            print(f"fetch: rsh failed at offset {before} with exit {result.returncode}", file=sys.stderr)
            print(result.stdout, end="", file=sys.stderr)
            print(result.stderr, end="", file=sys.stderr)
            return incomplete(out, data)
        answer = result.stdout
        size = after = None
        dropped_msg = None
        for line in answer.splitlines():
            m = re.match(r"\s*cat (\d+) (\S+)$", line)
            if m:
                if int(m.group(1)) != len(data):
                    dropped_msg = f"fetch: expected offset {len(data)}, got {m.group(1)}: the console dropped a line"
                    break
                try:
                    data += base64.b64decode(m.group(2), validate=True)
                except ValueError as error:
                    del data[before:]
                    print(f"fetch: invalid base64 at offset {before}: {error}")
                    return incomplete(out, data)
                continue
            m = re.match(r"\s*cat end (\d+) next (\d+)$", line)
            if m:
                size, after = int(m.group(1)), int(m.group(2))
        if dropped_msg is not None or size is None or after != len(data):
            err_offset = len(data)
            del data[before:]
            if retries < MAX_RETRIES:
                retries += 1
                reason = dropped_msg or f"fetch: no end line for offset {err_offset}"
                print(f"{reason} (retry {retries}/{MAX_RETRIES} from {before})", file=sys.stderr)
                continue
            if dropped_msg is not None:
                print(dropped_msg)
            else:
                print(f"fetch: no end line for offset {err_offset}:\n{answer[-400:]}")
            return incomplete(out, data)
        if len(data) > size:
            print(f"fetch: received {len(data)} bytes, exceeding declared file size {size}")
            return incomplete(out, data[:before])
        retries = 0
        if len(data) == size:
            break
        if len(data) == before:
            print(f"fetch: no progress at offset {before}, declared file size {size}")
            return incomplete(out, data)
    out.write_bytes(bytes(data))
    print(f"fetch: {path}: {len(data)} bytes to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
