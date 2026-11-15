#!/usr/bin/env python3
"""Copy one file off the iOS a held round is running, through annsh's "cat".

usage: tools/k90auto/fetch.py ROUND_DIR DEVICE_PATH OUT

Each "cat PATH OFFSET" answers as many 48-byte lines as fit in one command's output and says where
the next one starts ("cat end SIZE next AT"); this asks again from there until the whole file is
read. OUT is written only after all offset, Base64, footer and size checks pass. A failed read
preserves its verified prefix in OUT.partial. Exit status: 0 for a complete file, 1 for a failed read.
"""
import base64
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
MAX_RETRIES = 3   # re-reads of one chunk after a dropped console line or a missing footer


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
