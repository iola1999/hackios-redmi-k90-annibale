#!/usr/bin/env python3
"""Make the K90 boot image out of a release, the user's IPSW and the user's phone (macOS or Linux).

usage: assemble.py ipsw DIR
           downloads os.dmg, systemos.dmg and appos.dmg of the release's iOS build from Apple
           into DIR and decrypts them (about 10.4 GB of downloads, 15 GB on disk)
       assemble.py build --ipsw DIR --modem IMG --bluetooth IMG --zap FILE [-o DIR]
           makes DIR/root.apfs and DIR/boot-ios.img (default DIR: ./out)

Run it from the unpacked release (hackios-k90-vX.Y.Z/tools/release/assemble.py). --modem and
--bluetooth are images of the phone's modem_a and bluetooth_a partitions (.img or .img.gz),
--zap is the phone's /odm/firmware/gen80000_zap.mbn; docs/user-guide.md says how to read them.

Needs Python 3.10 or newer and 7-Zip 23 or newer (7zz or 7z) on PATH; `ipsw` also needs the
Python package cryptography. Nothing here talks to the phone.
"""
import argparse
import json
import os
import plistlib
import shutil
import subprocess
import sys
import tempfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
RELEASE = HERE.parent.parent
sys.path.insert(0, str(HERE))
import localfiles  # noqa: E402
from localfiles import file_sha256 as digest  # noqa: E402

K = RELEASE / "hackios-xnu-kernel"
U = RELEASE / "hackios-xnu-userland"
DMGS = ("os", "systemos", "appos")
# the firmware files each partition image gives (mk-fw-wifi.py / mk-fw-bt.py extract)
FIRMWARE_TOOLS = {"modem": "mk-fw-wifi.py", "bluetooth": "mk-fw-bt.py"}


def run(cmd, **kw):
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def say(text):
    print(f"assemble: {text}", flush=True)


def seven_zip():
    for name in ("7zz", "7z"):
        path = shutil.which(name)
        if path:
            return path
    raise SystemExit("7-Zip is not on PATH: install 7-Zip 23 or newer (brew install sevenzip, apt install 7zip)")


def load_release():
    manifest = json.loads((RELEASE / "manifest.json").read_text())
    for rel, want in manifest["files"].items():
        if rel != "manifest.json" and digest(RELEASE / rel) != want:
            raise SystemExit(f"{rel}: SHA-256 differs from manifest.json; unpack the release again")
    recipes = plistlib.loads((RELEASE / "local-files.plist").read_bytes())
    if recipes["format"] != localfiles.FORMAT:
        raise SystemExit("local-files.plist is of another format than this assemble.py")
    return manifest, recipes["files"]


def fetch_ipsw(target):
    manifest, _ = load_release()
    ipsw = manifest["ios"]["ipsw"]
    target.mkdir(parents=True, exist_ok=True)
    for name in DMGS:
        member = ipsw["members"][name]
        out = target / f"{name}.dmg"
        if out.is_file() and out.stat().st_size == manifest["ios"]["dmg_bytes"][name]:
            say(f"{out} is there")
            continue
        raw = target / member
        say(f"downloading {member} ({name}.dmg)")
        run([sys.executable, RELEASE / "tools/ipsw/fetch.py", member, raw, ipsw["url"], ipsw["zip_bytes"]])
        if member.endswith(".aea"):
            say(f"decrypting {raw.name}")
            run([sys.executable, RELEASE / "tools/ipsw/aea.py", raw, out])
            raw.unlink()
        else:
            raw.rename(out)
    say(f"{target}: {', '.join(f'{n}.dmg' for n in DMGS)} ready")


def extract_ios(seven, ipsw, refs, work):
    """The iOS files the recipes name, read out of the DMGs with 7-Zip: ref -> path."""
    found = {}
    for volume in DMGS:
        paths = sorted({ref.split(":", 1)[1] for ref in refs if ref.startswith(volume + ":")})
        if not paths:
            continue
        listing = work / f"{volume}.list"
        listing.write_text("".join(p + "\n" for p in paths))
        out = work / volume
        run([seven, "x", "-y", "-bso0", "-bsp0", ipsw / f"{volume}.dmg", f"-o{out}", f"@{listing}"])
        for p in paths:
            if not (out / p).is_file():
                raise SystemExit(f"{volume}.dmg has no {p}: is it the release's iOS build?")
            found[f"{volume}:{p}"] = out / p
    return found


def var_skeleton(seven, ipsw, work):
    listing = work / "var.slt"
    with open(listing, "w") as out:
        run([seven, "l", "-slt", ipsw / "os.dmg", "private/var/*"], stdout=out, stderr=subprocess.DEVNULL)
    return run([sys.executable, U / "ios26/full-system.py", "skeleton", listing], capture_output=True, text=True).stdout


def firmware(args, recipes, work):
    """name -> bytes of every firmware file the recipes ask for."""
    images = {"modem": args.modem, "bluetooth": args.bluetooth}
    files = {}
    for source, tool in FIRMWARE_TOOLS.items():
        out = work / f"fw-{source}"
        run([sys.executable, K / "tools" / tool, "extract", images[source], out], stdout=subprocess.DEVNULL)
        for r in recipes:
            if r["kind"] == "firmware" and r["source"] == source:
                path = out / r["name"]
                if not path.is_file():
                    raise SystemExit(f"{images[source]} has no {r['name']}: is it this phone's {source}_a partition?")
                files[r["name"]] = path.read_bytes()
    for r in recipes:
        if r["kind"] == "firmware" and r["source"] == "zap":
            files[r["name"]] = args.zap.read_bytes()
    return files


def build(args):
    manifest, recipes = load_release()
    seven = seven_zip()
    for name in DMGS:
        dmg = args.ipsw / f"{name}.dmg"
        want = manifest["ios"]["dmg_bytes"][name]
        if not dmg.is_file() or dmg.stat().st_size != want:
            raise SystemExit(f"{dmg}: missing or not {want} bytes; run `assemble.py ipsw {args.ipsw}` first")
    for path in (args.modem, args.bluetooth, args.zap):
        if not path.is_file():
            raise SystemExit(f"{path}: not found")
    args.output.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="assemble-") as tmp:
        work = Path(tmp)
        say("reading the iOS files the release needs out of the IPSW")
        ios = extract_ios(seven, args.ipsw, {r["from"] for r in recipes if "from" in r}, work)
        skeleton = var_skeleton(seven, args.ipsw, work)
        say("extracting the phone's firmware")
        fw = firmware(args, recipes, work)

        say("making the root image")
        staging = work / "root"
        staging.mkdir()
        by_path = {r["path"]: r for r in recipes}
        entries = manifest["root"]["entries"]
        for rel, kind, mode, target in entries:
            dest = staging / rel
            if kind == "dir":
                dest.mkdir()
            elif kind == "link":
                os.symlink(target, dest)
            elif rel not in by_path:
                shutil.copyfile(RELEASE / "root" / rel, dest)
        jobs_dir = staging / "LaunchDaemons"
        order = sorted(recipes, key=lambda r: r["kind"] == "cache")  # the cache reads every finished job
        for r in order:
            jobs = {p.name: p.read_bytes() for p in jobs_dir.glob("*.plist")} if r["kind"] == "cache" else {}
            data = localfiles.make(r, lambda ref: ios[ref].read_bytes(), skeleton, jobs, lambda name: fw[name])
            (staging / r["path"]).write_bytes(data)
        for rel, kind, mode, _ in reversed(entries):
            if kind != "link":
                os.chmod(staging / rel, mode)
        tree_sha = localfiles.tree_digest(staging)
        root_image = args.output / "root.apfs"
        run([sys.executable, U / "tools/apfs/mkapfs.py", "-z", "--plain", "fw", "-o", root_image,
             f"{manifest['volume']}={staging}"], stdout=subprocess.DEVNULL)

        say("sealing the boot image")
        payload = work / "payload.bin"
        run([sys.executable, K / "xnuloader/mkstandalone.py", "--kernel", RELEASE / "payload/kernel.bin",
             "--ramdisk", root_image, "--boot-image", RELEASE / "payload/flashboot.apfs", "-o", payload, "--no-lz4"],
            stdout=subprocess.DEVNULL)
        boot = args.output / "boot-ios.img"
        run([sys.executable, K / "tools/reseal-loader-img.py", RELEASE / "payload/loader-shell.img", payload,
             "-o", boot], stdout=subprocess.DEVNULL)

    expected = manifest["expected"]
    same_fw = all(localfiles.sha256(fw[n]) == h for n, h in expected["firmware_sha256"].items())
    if same_fw and tree_sha != expected["tree_sha256"]:
        raise SystemExit("the firmware is the release's, but the root image's files differ from the release's; report this")
    root_sha, boot_sha = digest(root_image), digest(boot)
    say(f"{root_image}: {root_image.stat().st_size} bytes, SHA-256 {root_sha}")
    say(f"{boot}: {boot.stat().st_size} bytes, SHA-256 {boot_sha}")
    if not same_fw:
        changed = [n for n, h in expected["firmware_sha256"].items() if localfiles.sha256(fw[n]) != h]
        say(f"the phone's firmware differs from the tested version in {', '.join(changed)}; "
            "every other file of the root image is the release's")
    elif root_sha == expected["root_sha256"] and boot_sha == expected["boot_sha256"]:
        say("both images are byte for byte the release's")
    else:
        say(f"the root image holds exactly the release's files; its bytes differ because this Python's zlib "
            f"({zlib.ZLIB_RUNTIME_VERSION}) compresses differently from the release's ({expected['zlib']})")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("ipsw", help="download and decrypt the three iOS disk images")
    p.add_argument("dir", type=Path)
    p = sub.add_parser("build", help="make root.apfs and boot-ios.img")
    p.add_argument("--ipsw", type=Path, required=True)
    p.add_argument("--modem", type=Path, required=True)
    p.add_argument("--bluetooth", type=Path, required=True)
    p.add_argument("--zap", type=Path, required=True)
    p.add_argument("-o", "--output", type=Path, default=Path("out"))
    args = ap.parse_args()
    if sys.version_info < (3, 10):
        raise SystemExit("Python 3.10 or newer is needed")
    if args.command == "ipsw":
        fetch_ipsw(args.dir)
    else:
        build(args)


if __name__ == "__main__":
    main()
