#!/usr/bin/env python3
"""Make the K90 boot image out of a release, the user's IPSW and the user's phone (macOS or Linux).

usage: assemble.py ipsw DIR
           downloads os.dmg, systemos.dmg and appos.dmg of the release's iOS build from Apple
           into DIR and decrypts them (about 10.4 GB of downloads, 15 GB on disk)
       assemble.py wifi-mac --serial SERIAL -o FILE
           saves wlan0's permanent address from the phone running Android
       assemble.py build --ipsw DIR --modem IMG --bluetooth IMG --zap FILE [--iris FILE] [--camera DIR]
                         [--wifi-mac-file FILE] [-o DIR]
           makes DIR/root.apfs and DIR/boot-ios.img (default DIR: ./out)

Run it from the unpacked release (hackios-k90-vX.Y.Z/tools/release/assemble.py). --modem and
--bluetooth are images of the phone's modem_a and bluetooth_a partitions (.img or .img.gz),
--zap is the phone's /odm/firmware/gen80000_zap.mbn, --camera a directory with the phone's camera
sensor modules (/odm/lib64/camera/com.qti.sensormodule.annibale_*.bin) and colour tuning files
(com.qti.tuned.annibale_*.bin, in the same directory); docs/user-guide.md says
how to read them.

Needs Python 3.10 or newer and 7-Zip 23 or newer (7zz or 7z) on PATH; `ipsw` also needs the
Python package cryptography. The wifi-mac command uses adb to read wlan0 on stock Android.
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
sys.path.insert(0, str(K / "xnuloader"))
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
        if r["kind"] == "firmware" and r["source"] == "iris":
            if args.iris is None:
                raise SystemExit("this release requires --iris FILE (the phone's vpu35_4v.mbn)")
            files[r["name"]] = args.iris.read_bytes()
        if r["kind"] == "firmware" and r["source"] == "camera":
            module = (args.camera or Path()) / r["module"]
            if args.camera is None or not module.is_file():
                raise SystemExit(f"this release requires --camera DIR with the phone's {r['module']}")
            out = work / r["name"]
            run([sys.executable, K / "tools/camsensor.py", "--profile", module, r["mode"], out], stdout=subprocess.DEVNULL)
            files[r["name"]] = out.read_bytes()
        if r["kind"] == "firmware" and r["source"] == "camera-tuning":
            tuned, module = (args.camera or Path()) / r["tuned"], (args.camera or Path()) / r["module"]
            for f in (tuned, module):
                if args.camera is None or not f.is_file():
                    raise SystemExit(f"this release requires --camera DIR with the phone's {f.name}")
            out = work / r["name"]
            run([sys.executable, K / "tools/camtuning.py", tuned, out, module, r["mode"]], stdout=subprocess.DEVNULL)
            files[r["name"]] = out.read_bytes()
    return files


def export_wifi_mac(serial, output):
    from wifi_mac import normalize_factory_mac

    if not serial.strip():
        raise SystemExit("an Android device serial is required")
    try:
        result = subprocess.run(["adb", "-s", serial, "shell", "ethtool", "-P", "wlan0"],
                                capture_output=True, timeout=20, check=False)
    except (OSError, subprocess.TimeoutExpired):
        raise SystemExit("could not query the selected Android device with adb") from None
    if result.returncode:
        raise SystemExit("could not read the permanent wlan0 address from the selected Android device")
    try:
        line = result.stdout.decode("ascii").strip()
        prefix = "Permanent address: "
        if not line.startswith(prefix) or len(line.splitlines()) != 1:
            raise ValueError
        address = normalize_factory_mac(line[len(prefix):])
    except ValueError:
        raise SystemExit("Android did not return one valid permanent wlan0 address") from None

    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=output.parent, mode="w", encoding="ascii", delete=False) as f:
            temporary = Path(f.name)
            os.fchmod(f.fileno(), 0o600)
            f.write(address + "\n")
        os.replace(temporary, output)
    except OSError:
        raise SystemExit("could not save the factory address file") from None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)
    say("saved the permanent wlan0 address")


def seal_boot(root_image, payload, image, wifi_mac_file=None):
    command = [sys.executable, K / "xnuloader/mkstandalone.py", "--kernel", RELEASE / "payload/kernel.bin",
               "--ramdisk", root_image, "--boot-image", RELEASE / "payload/flashboot.apfs", "-o", payload, "--no-lz4"]
    if wifi_mac_file is not None:
        command.extend(["--wifi-mac-file", wifi_mac_file])
    run(command, stdout=subprocess.DEVNULL)
    reseal = [sys.executable, K / "tools/reseal-loader-img.py", RELEASE / "payload/loader-shell.img", payload, "-o"]
    if wifi_mac_file is None:
        run([*reseal, image], stdout=subprocess.DEVNULL)
        return
    with tempfile.TemporaryDirectory(dir=image.parent) as private:
        staged = Path(private) / image.name
        run([*reseal, staged], stdout=subprocess.DEVNULL, umask=0o077)
        staged.chmod(0o600)
        os.replace(staged, image)


def check_wifi_mac_input(manifest, path):
    if manifest.get("requires_factory_wifi_mac", False):
        if path is None:
            raise SystemExit("this release requires --wifi-mac-file FILE from the phone's Android installation")
        from wifi_mac import read_factory_mac

        try:
            read_factory_mac(path)
        except ValueError:
            raise SystemExit("cannot read a single valid factory address from --wifi-mac-file") from None
    elif path is not None:
        raise SystemExit("this release predates factory Wi-Fi address import")


def build(args):
    manifest, recipes = load_release()
    check_wifi_mac_input(manifest, args.wifi_mac_file)
    seven = seven_zip()
    for name in DMGS:
        dmg = args.ipsw / f"{name}.dmg"
        want = manifest["ios"]["dmg_bytes"][name]
        if not dmg.is_file() or dmg.stat().st_size != want:
            raise SystemExit(f"{dmg}: missing or not {want} bytes; run `assemble.py ipsw {args.ipsw}` first")
    for path in (args.modem, args.bluetooth, args.zap, *([args.iris] if args.iris else [])):
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

        expected = manifest["expected"]
        same_fw = all(localfiles.sha256(fw[n]) == h for n, h in expected["firmware_sha256"].items())
        if same_fw and tree_sha != expected["tree_sha256"]:
            raise SystemExit("the firmware is the release's, but the root image's files differ from the release's")
        root_sha = digest(root_image)
        say("sealing the boot image")
        payload = work / "payload.bin"
        boot = args.output / "boot-ios.img"
        if root_sha == expected["root_sha256"]:
            reference = work / "reference.img"
            seal_boot(root_image, payload, reference)
            if digest(reference) != expected["boot_sha256"]:
                raise SystemExit("generic boot image SHA-256 differs from the release reference")
            if args.wifi_mac_file is None:
                shutil.copyfile(reference, boot)
            else:
                seal_boot(root_image, payload, boot, args.wifi_mac_file)
        else:
            seal_boot(root_image, payload, boot, args.wifi_mac_file)

    say(f"{root_image}: {root_image.stat().st_size} bytes, SHA-256 {root_sha}")
    say(f"{boot}: {boot.stat().st_size} bytes, SHA-256 {digest(boot)}")
    if not same_fw:
        changed = [n for n, h in expected["firmware_sha256"].items() if localfiles.sha256(fw[n]) != h]
        say(f"the phone's firmware differs from the tested version in {', '.join(changed)}")
    elif root_sha != expected["root_sha256"]:
        say(f"the root tree matches the release; this Python's zlib is {zlib.ZLIB_RUNTIME_VERSION}, "
            f"the release used {expected['zlib']}")
    elif args.wifi_mac_file is None:
        say("both images are byte for byte the release's")
    else:
        say("the root image and generic boot image match the release reference")
    if args.wifi_mac_file is not None:
        say("boot-ios.img includes the phone's factory Wi-Fi address")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    p = sub.add_parser("ipsw", help="download and decrypt the three iOS disk images")
    p.add_argument("dir", type=Path)
    p = sub.add_parser("wifi-mac", help="save wlan0's factory address from stock Android")
    p.add_argument("--serial", required=True, help="Android device serial for adb")
    p.add_argument("-o", "--output", type=Path, required=True, help="local address file, created with mode 0600")
    p = sub.add_parser("build", help="make root.apfs and boot-ios.img")
    p.add_argument("--ipsw", type=Path, required=True)
    p.add_argument("--wifi-mac-file", type=Path, help="file containing the phone's factory Wi-Fi address")
    p.add_argument("--modem", type=Path, required=True)
    p.add_argument("--bluetooth", type=Path, required=True)
    p.add_argument("--zap", type=Path, required=True)
    p.add_argument("--iris", type=Path, help="the phone's signed vpu35_4v.mbn, required by releases with Iris")
    p.add_argument("--camera", type=Path, help="directory with the phone's camera sensor modules and tuning "
                                                "files, required by releases with the camera")
    p.add_argument("-o", "--output", type=Path, default=Path("out"))
    args = ap.parse_args()
    if sys.version_info < (3, 10):
        raise SystemExit("Python 3.10 or newer is needed")
    if args.command == "ipsw":
        fetch_ipsw(args.dir)
    elif args.command == "wifi-mac":
        export_wifi_mac(args.serial, args.output)
    else:
        build(args)


if __name__ == "__main__":
    main()
