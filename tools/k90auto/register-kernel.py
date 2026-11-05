#!/usr/bin/env python3
"""Give an xnu-12377 kernel built by xnu26/build-macos.sh the name cycle.py and make-payload.py take.

usage: python3 tools/k90auto/register-kernel.py NAME [SRC]      (from the workspace root)
  NAME  a name of the 12377 line, e.g. 12377-local
  SRC   the kernel's build tree (default: $XNU26_SRC, else hackios-xnu-kernel/xnu-src/xnu-12377.121.6)

The kernel is copied to hackios-xnu-kernel/out/xnu<NAME>.bin, and <evidence>/kernel-<NAME>/kernel.json
records that path, its size and sha256, the kernel repository's commit ("-dirty" when its working
tree has uncommitted changes) and the build tree. A name that already has a record is refused, so a
round record always points at the kernel it ran.
"""
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

KERNEL_REPO = Path("hackios-xnu-kernel")
# build-macos.sh's defaults: MACHINE=BCM2837, KERNEL_CONFIG=DEVELOPMENT
BUILT = "BUILD/obj/DEVELOPMENT_ARM64_BCM2837/mach.development.bcm2837"


def main():
    if len(sys.argv) not in (2, 3) or not re.fullmatch(r"12377-[a-z0-9-]+", sys.argv[1]):
        sys.exit(__doc__)
    name = sys.argv[1]
    src = Path(sys.argv[2] if len(sys.argv) == 3 else
               os.environ.get("XNU26_SRC", KERNEL_REPO / "xnu-src/xnu-12377.121.6"))
    built = src / BUILT
    if not built.is_file():
        sys.exit(f"{built} does not exist: run xnu26/build-macos.sh in hackios-xnu-kernel first")
    evidence = Path(os.environ.get("K90_EVIDENCE", "docs/progress/evidence/k90auto")) / f"kernel-{name}"
    kernel = KERNEL_REPO / f"out/xnu{name}.bin"
    if evidence.exists() or kernel.exists():
        sys.exit(f"{evidence} or {kernel} already exists; pick another name")

    commit = subprocess.run(["git", "-C", str(KERNEL_REPO), "describe", "--always", "--dirty", "--abbrev=12"],
                            check=True, capture_output=True, text=True).stdout.strip()
    kernel.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(built, kernel)
    record = {"commit": commit,
              "kernel": {"path": str(kernel), "bytes": kernel.stat().st_size,
                         "sha256": hashlib.sha256(kernel.read_bytes()).hexdigest()},
              "build": {"tree": str(src), "command": "xnu26/build-macos.sh (from hackios-xnu-kernel/)"}}
    evidence.mkdir(parents=True)
    (evidence / "kernel.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(record, indent=2))


if __name__ == "__main__":
    main()
