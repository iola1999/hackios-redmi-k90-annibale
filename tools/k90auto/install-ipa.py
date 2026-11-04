#!/usr/bin/env python3
"""Install an .ipa on the iOS a held round is running, over USB, without a new image.

usage: tools/k90auto/install-ipa.py ROUND_DIR FILE.ipa [--open]

The file goes to the phone in pieces of at most 15 MB, each through the kernel's 16 MB inbox
(run-auto.py's push request, then rwsh "pull PATH OFFSET" into /private/var/tmp/ipa/). appinst's
watcher, started at boot from rc.jobs.interactive, installs it once the whole archive is there;
this waits until "appinst list" names the application, and --open launches it.

An application from the App Store is encrypted (FairPlay) and will not run; this says so before it
sends anything. Exit status: 0 once installed, 1 otherwise.
"""
import json
import plistlib
import struct
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
PIECE = 15 << 20
REMOTE_DIR = "/private/var/tmp/ipa"


def rsh(round_dir, *words):
    return subprocess.run([sys.executable, str(HERE / "rsh.py"), str(round_dir), *words],
                          capture_output=True, text=True).stdout


def app_info(ipa):
    """(bundle identifier, name, whether the main executable is encrypted) of the .ipa."""
    with zipfile.ZipFile(ipa) as z:
        plist = next(n for n in z.namelist() if n.count("/") == 2 and n.startswith("Payload/")
                     and n.endswith(".app/Info.plist"))
        info = plistlib.loads(z.read(plist))
        binary = z.read(plist.rsplit("/", 1)[0] + "/" + info["CFBundleExecutable"])
    return info["CFBundleIdentifier"], info.get("CFBundleDisplayName") or info.get("CFBundleName"), encrypted(binary)


def encrypted(macho):
    """Whether any slice of the Mach-O has LC_ENCRYPTION_INFO(_64) with cryptid 1."""
    magic = struct.unpack_from(">I", macho)[0]
    if magic in (0xcafebabe, 0xcafebabf):                     # fat: big-endian slice table
        wide = magic == 0xcafebabf
        count = struct.unpack_from(">I", macho, 4)[0]
        slices = []
        for i in range(count):
            if wide:
                _, _, offset, size, _, _ = struct.unpack_from(">IIQQII", macho, 8 + i * 32)
            else:
                _, _, offset, size, _ = struct.unpack_from(">IIIII", macho, 8 + i * 20)
            slices.append(macho[offset:offset + size])
        return any(encrypted(s) for s in slices)
    if struct.unpack_from("<I", macho)[0] not in (0xfeedface, 0xfeedfacf):
        return False
    header = 32 if struct.unpack_from("<I", macho)[0] == 0xfeedfacf else 28
    ncmds = struct.unpack_from("<I", macho, 16)[0]
    at = header
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<II", macho, at)
        if cmd in (0x21, 0x2c) and struct.unpack_from("<I", macho, at + 16)[0] != 0:
            return True
        at += size
    return False


def push(round_dir, data):
    """One piece into the kernel's inbox through the running round's push request."""
    run = Path(round_dir) / "run"
    with tempfile.NamedTemporaryFile(delete=False, suffix=".piece") as f:
        f.write(data)
    name = f"push-request-{time.time_ns()}"
    (run / f".{name}.tmp").write_text(f.name + "\n")
    (run / f".{name}.tmp").rename(run / f"{name}.txt")
    reply = run / f"{name.replace('push-request-', 'push-reply-')}.json"
    deadline = time.monotonic() + 90
    while not reply.exists():
        if time.monotonic() > deadline:
            Path(f.name).unlink()
            return False
        time.sleep(0.3)
    Path(f.name).unlink()
    return json.loads(reply.read_text())["ok"]


def main():
    args = [a for a in sys.argv[1:] if a != "--open"]
    if len(args) != 2:
        print(__doc__.strip())
        return 1
    round_dir, ipa = Path(args[0]), Path(args[1])
    if not (round_dir / "run").is_dir() or (round_dir / "run/reboot.json").exists():
        print(f"install-ipa: {round_dir} is not a running round")
        return 1
    identifier, name, is_encrypted = app_info(ipa)
    if is_encrypted:
        print(f"install-ipa: {ipa.name} ({identifier}) is encrypted by the App Store and cannot run here; "
              f"a decrypted copy is needed")
        return 1
    data = ipa.read_bytes()
    remote = f"{REMOTE_DIR}/{int(time.time()) % 1000000}.ipa"
    print(f"install-ipa: {name} ({identifier}), {len(data) / 1e6:.1f} MB in {(len(data) + PIECE - 1) // PIECE} piece(s)")
    for at in range(0, len(data), PIECE):
        if not push(round_dir, data[at:at + PIECE]):
            print(f"install-ipa: the piece at {at} did not reach the phone")
            return 1
        answer = rsh(round_dir, "pull", remote, str(at))
        if f"to {remote} at {at}" not in answer or ": " in answer.split(f"at {at}", 1)[1].split("\n", 1)[0]:
            print(f"install-ipa: the phone did not write the piece at {at}:\n{answer[-300:]}")
            return 1
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        if identifier in rsh(round_dir, "/redwood/bin/appinst", "list"):
            print(f"install-ipa: {identifier} is installed")
            if "--open" in sys.argv:
                print(rsh(round_dir, "/redwood/bin/appinst", "open", identifier).strip().splitlines()[-1])
            return 0
        time.sleep(3)
    print(f"install-ipa: {identifier} did not show up in appinst list within 180 s; see appinst lines in the log")
    return 1


if __name__ == "__main__":
    sys.exit(main())
