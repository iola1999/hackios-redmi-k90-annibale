#!/usr/bin/env python3
"""Copy one file off the iOS a held round is running, through annsh's "cat".

usage: tools/k90auto/fetch.py ROUND_DIR DEVICE_PATH OUT

Each "cat PATH OFFSET" answers as many 48-byte lines as fit in one command's output and says where
the next one starts ("cat end SIZE next AT"); this asks again from there until the whole file is
read. A line the console dropped shows up as a hole in the offsets, and the fetch stops rather than
write a file with a gap in it. Exit status: 0, or 1 when the file could not be read whole.
"""
import base64
import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main():
    if len(sys.argv) != 4:
        print(__doc__.strip())
        return 1
    round_dir, path, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    data = bytearray()
    while True:
        before = len(data)
        result = subprocess.run([sys.executable, str(HERE / "rsh.py"), round_dir, "cat", path, str(before)],
                                capture_output=True, text=True)
        if result.returncode != 0:
            print(f"fetch: rsh failed at offset {before} with exit {result.returncode}", file=sys.stderr)
            print(result.stdout, end="", file=sys.stderr)
            print(result.stderr, end="", file=sys.stderr)
            return 1
        answer = result.stdout
        size = after = None
        for line in answer.splitlines():
            m = re.match(r"\s*cat (\d+) (\S+)$", line)
            if m:
                if int(m.group(1)) != len(data):
                    print(f"fetch: expected offset {len(data)}, got {m.group(1)}: the console dropped a line")
                    return 1
                try:
                    data += base64.b64decode(m.group(2), validate=True)
                except ValueError as error:
                    print(f"fetch: invalid base64 at offset {len(data)}: {error}")
                    return 1
                continue
            m = re.match(r"\s*cat end (\d+) next (\d+)$", line)
            if m:
                size, after = int(m.group(1)), int(m.group(2))
        if size is None or after != len(data):
            print(f"fetch: no end line for offset {len(data)}:\n{answer[-400:]}")
            return 1
        if len(data) > size:
            print(f"fetch: received {len(data)} bytes, exceeding declared file size {size}")
            return 1
        if len(data) == size:
            break
        if len(data) == before:
            print(f"fetch: no progress at offset {before}, declared file size {size}")
            return 1
    out.write_bytes(bytes(data))
    print(f"fetch: {path}: {len(data)} bytes to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
