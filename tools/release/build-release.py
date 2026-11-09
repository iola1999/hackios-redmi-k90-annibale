#!/usr/bin/env python3
"""Make a GitHub release of the K90 port out of a built workspace (maintainer side, macOS).

usage: build-release.py VERSION --kernel FILE --loader-image FILE [-o DIR] [--expect-boot FILE]
                        [--allow-dirty]

The workspace has to be built first, as docs/development.md describes: the 12377 kernel, the
userland and the AIR library, `tools/k90auto/package.py` (its root tree and root.apfs), the boot
volume flashboot.apfs, xnuloader/loader-phone.efi, tools/android/build.sh, and ios26/fetch.sh's
extraction of the IPSW. --loader-image is any loader image whose UEFI, device tree and ramdisk the
release keeps (out/handoff-loader-vN.img, or a boot image made from one); --expect-boot is a boot
image made from the same inputs, for a byte-for-byte comparison.

The root tree is split into what this project wrote (the release's root/) and recipes for the rest
(local-files.plist, see localfiles.py): files identical to an iOS file, launchd jobs and the launchd
cache made from iOS's, the /private/var template, and the phone's firmware. Before anything is
written, the split is checked by making every recipe again from the local extraction and packing
the root image, which has to come out as the root.apfs package.py made.

Output: DIR/hackios-k90-VERSION/ (the bundle, with assemble.py and the scripts it runs at the same
paths as in the workspace) and DIR/hackios-k90-VERSION.tar.gz with its .sha256.
"""
import argparse
import datetime
import json
import os
import plistlib
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent.parent
K = REPO / "hackios-xnu-kernel"
sys.path.insert(0, str(HERE))
import localfiles  # noqa: E402
from localfiles import file_sha256 as digest  # noqa: E402

PACKED = K / "out/ios26-resume/bbmetal-device"
IOS = REPO / "hackios-xnu-userland/ios26"
IOS_VOLUMES = {"os": IOS / "rootfs", "systemos": IOS / "cryptex", "appos": IOS / "cryptex-app"}
IPSW = K / "out/ipsw/v57/26"
# where assemble.py downloads the three disk images from: iPhone 17's IPSW of the extracted build
IPSW_SOURCE = {"url": "https://updates.cdn-apple.com/2026SummerFCS/c2f9fa07-0acc-4038-99f4-d7a4b1ac9c06/"
                      "iPhone18,3_26.6.2_23G90_Restore.ipsw",
               "zip_bytes": 11481186987,
               "members": {"os": "094-96558-090.dmg.aea", "systemos": "094-95851-092.dmg.aea",
                           "appos": "094-96441-094.dmg"}}
# the phone's own firmware: which partition image each file is extracted from
VENDOR_FIRMWARE = {"gen80000_zap.mbn": "zap",
                   "amss20.bin": "modem", "regdb.bin": "modem", "bd_p11.elf": "modem", "phy_ucode20.elf": "modem",
                   "hmtbtfw20.tlv": "bluetooth", "hmtbtfw20.ver": "bluetooth", "hmtnv20.bin": "bluetooth"}
# fw/ files a release may carry: the GPU firmware of firmware-gen8/ (Qualcomm's redistribution
# licence beside it) and package.py's own InterfaceNamer preference
RELEASE_FIRMWARE = {"gen80000_aqe.fw", "gen80000_gmu.bin", "gen80000_sqe.fw", "LICENSE.qcom.txt", "NOTICE.qcom.txt",
                    "com.apple.InterfaceNamer.control.plist"}
# the scripts assemble.py runs, at their workspace paths
BUNDLED_TOOLS = ["tools/release/assemble.py", "tools/release/localfiles.py",
                 "tools/ipsw/fetch.py", "tools/ipsw/aea-key.py", "tools/ipsw/aea.py",
                 "hackios-xnu-kernel/xnuloader/mkstandalone.py", "hackios-xnu-kernel/xnuloader/mkpayload.py",
                 "hackios-xnu-kernel/xnuloader/loader-phone.efi",
                 "hackios-xnu-kernel/tools/reseal-loader-img.py", "hackios-xnu-kernel/prebuilt/uefi/mkbootimg.py",
                 "hackios-xnu-kernel/tools/mk-fw-wifi.py", "hackios-xnu-kernel/tools/mk-fw-bt.py",
                 "hackios-xnu-kernel/tools/userdata-dual-carve.py",
                 "hackios-xnu-userland/tools/apfs/mkapfs.py", "hackios-xnu-userland/ios26/full-system.py"]
LICENSES = {"hackios-xnu-kernel.LICENSE": K / "LICENSE", "hackios-xnu-kernel.NOTICES.md": K / "NOTICES.md",
            "hackios-xnu-userland.LICENSE": REPO / "hackios-xnu-userland/LICENSE",
            "qualcomm-gpu-firmware.LICENSE.txt": REPO / "hackios-xnu-userland/firmware-gen8/LICENSE.qcom.txt"}
ANDROID_TOOLS = ["f2fs-resize", "blkpg-tool"]


def git(directory, *args):
    return subprocess.run(["git", "-C", str(directory), *args], check=True, capture_output=True,
                          text=True).stdout.strip()


def sources(allow_dirty):
    """The commits the build came from; a dirty tree is refused unless asked for."""
    trees = {"workspace": (REPO, ["git", "-C", str(REPO)]),
             "hackios-xnu-kernel": (K, ["git", "-C", str(K)]),
             "hackios-xnu-userland": (REPO / "hackios-xnu-userland", ["git", "-C", str(REPO / "hackios-xnu-userland")])}
    commits = {}
    for name, (cwd, cmd) in trees.items():
        run = lambda *a: subprocess.run([*cmd, *a], cwd=cwd, check=True, capture_output=True, text=True).stdout
        commits[name] = run("rev-parse", "HEAD").strip()
        dirty = run("status", "--porcelain", "--untracked-files=no").strip()
        if dirty and not allow_dirty:
            raise SystemExit(f"{name} has uncommitted changes; a release is built from commits (--allow-dirty for a trial)")
        if dirty:
            commits[name] += "+dirty"
    return commits


def ios_index(sizes):
    """iOS files with one of the given sizes: size -> [(volume, path)]."""
    found = {}
    for volume, base in IOS_VOLUMES.items():
        for directory, _, files in os.walk(base):
            for name in files:
                path = Path(directory) / name
                try:
                    st = path.lstat()
                except OSError:
                    continue
                if stat.S_ISREG(st.st_mode) and st.st_size in sizes:
                    found.setdefault(st.st_size, []).append((volume, path.relative_to(base).as_posix()))
    return found


def read_ios(ref):
    volume, path = ref.split(":", 1)
    return (IOS_VOLUMES[volume] / path).read_bytes()


def split(root):
    """(recipes, review): the recipe of every root file a release does not carry."""
    files = {rel: root / rel for rel, kind, _, _ in localfiles.tree(root) if kind == "file"}
    sizes = {p.stat().st_size for p in files.values() if p.stat().st_size > 8}  # PkgInfo's 8 bytes are not iOS's
    index = ios_index(sizes)
    recipes, review = {}, []
    for rel, path in files.items():
        data = path.read_bytes()
        name = path.name
        if rel.startswith("fw/") and name not in RELEASE_FIRMWARE:
            if name not in VENDOR_FIRMWARE:
                raise SystemExit(f"{rel}: firmware this script does not know; add it to VENDOR_FIRMWARE or RELEASE_FIRMWARE")
            recipes[rel] = {"kind": "firmware", "name": name, "source": VENDOR_FIRMWARE[name]}
            continue
        same = [ref for ref in index.get(len(data), []) if read_ios(":".join(ref)) == data] if len(data) > 8 else []
        if same:
            recipes[rel] = {"kind": "copy", "from": ":".join(same[0])}
        elif rel == "xpc/launchd.plist":
            recipes[rel] = {"kind": "cache", "from": "os:System/Library/xpc/launchd.plist"}
        elif rel == "etc/var.skel":
            recipes[rel] = {"kind": "skeleton"}
        elif rel.startswith("LaunchDaemons/"):
            for kind in ("LaunchDaemons", "LaunchAngels"):
                if (IOS_VOLUMES["os"] / "System/Library" / kind / name).is_file():
                    recipes[rel] = {"kind": "plist", "from": f"os:System/Library/{kind}/{name}"}
                    break
        # what package.py writes under an Apple name besides the jobs: worth a look before publishing
        if rel not in recipes and name.startswith("com.apple.") and not rel.startswith("var/") \
                and name not in RELEASE_FIRMWARE:
            review.append(rel)
    return recipes, review


def fill_edits(root, recipes, skeleton_text):
    """The edit lists, then every recipe made again and compared with the root tree."""
    jobs = {p.name: p.read_bytes() for p in sorted((root / "LaunchDaemons").glob("*.plist"))}
    for rel, recipe in recipes.items():
        wanted = (root / rel).read_bytes()
        recipe["path"] = rel
        recipe["sha256"] = localfiles.sha256(wanted)
        if recipe["kind"] == "plist":
            recipe["edits"] = localfiles.plist_edits(plistlib.loads(read_ios(recipe["from"])), plistlib.loads(wanted))
        elif recipe["kind"] == "cache":
            base = localfiles.cache_base(read_ios(recipe["from"]), jobs)
            recipe["edits"] = localfiles.plist_edits(base, plistlib.loads(wanted))
        elif recipe["kind"] == "skeleton":
            recipe["edits"] = localfiles.skeleton_edits(skeleton_text, wanted.decode())
    for rel, recipe in recipes.items():
        made = localfiles.make(recipe, read_ios, skeleton_text, jobs, lambda name: (root / "fw" / name).read_bytes())
        if made != (root / rel).read_bytes():
            raise SystemExit(f"{rel}: the recipe does not make the file back")


def run(cmd, **kw):
    return subprocess.run([str(c) for c in cmd], check=True, **kw)


def volume_name():
    log = (PACKED / "root-build.log").read_text()
    match = re.search(r'volume 0 "([^"]+)"', log)
    if not match:
        raise SystemExit(f"{PACKED / 'root-build.log'}: no volume name; run tools/k90auto/package.py")
    return match.group(1)


def boot_image(work, kernel, root_image, flashboot, loader_image, name):
    payload = work / f"{name}-payload.bin"
    run([sys.executable, K / "xnuloader/mkstandalone.py", "--kernel", kernel, "--ramdisk", root_image,
         "--boot-image", flashboot, "-o", payload, "--no-lz4"], stdout=subprocess.DEVNULL)
    out = work / f"{name}.img"
    run([sys.executable, K / "tools/reseal-loader-img.py", loader_image, payload, "-o", out], stdout=subprocess.DEVNULL)
    return out


def private(bundle):
    """Refuse a bundle with an ssh key (userland/build.sh without SHARE=1) or this machine's home path."""
    home = str(Path.home()).encode()
    for path in bundle.rglob("*"):
        if ".ssh" in path.parts or path.name.startswith("ssh_host_"):
            raise SystemExit(f"{path}: an ssh key; build the userland with SHARE=1")
        if path.is_file() and not path.is_symlink() and home in path.read_bytes():
            raise SystemExit(f"{path}: carries this machine's home directory path")


def write_tar(bundle, archive):
    def clean(info):
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        info.mtime = 0
        return info
    with tarfile.open(archive, "w:gz", format=tarfile.PAX_FORMAT) as tar:
        tar.add(bundle, arcname=bundle.name, filter=clean)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("version", help="vMAJOR.MINOR.PATCH, see docs/development.md")
    ap.add_argument("--kernel", type=Path, required=True)
    ap.add_argument("--loader-image", type=Path, required=True)
    ap.add_argument("--expect-boot", type=Path)
    ap.add_argument("-o", "--output", type=Path, default=REPO / "out/release")
    ap.add_argument("--allow-dirty", action="store_true")
    args = ap.parse_args()
    if not re.fullmatch(r"v\d+\.\d+\.\d+", args.version):
        raise SystemExit("version must look like v0.1.0")

    commits = sources(args.allow_dirty)
    root, root_image = PACKED / "root", PACKED / "root.apfs"
    flashboot, loader_efi = REPO / "hackios-xnu-userland/userland/flashboot.apfs", K / "xnuloader/loader-phone.efi"
    android = [K / "tools/android" / n for n in ANDROID_TOOLS]
    for path in [root_image, args.kernel, args.loader_image, flashboot, loader_efi, IOS / "rootfs.slt", *android]:
        if not path.is_file():
            raise SystemExit(f"{path}: missing; build it first (docs/development.md)")
    volume = volume_name()
    system = plistlib.loads((IOS_VOLUMES["os"] / "System/Library/CoreServices/SystemVersion.plist").read_bytes())

    print("build-release: splitting the root tree")
    recipes, review = split(root)
    skeleton_text = run([sys.executable, IOS / "full-system.py", "skeleton", IOS / "rootfs.slt"],
                        capture_output=True, text=True).stdout
    fill_edits(root, recipes, skeleton_text)
    entries = localfiles.tree(root)

    bundle = args.output / f"hackios-k90-{args.version}"
    if bundle.exists():
        shutil.rmtree(bundle)
    (bundle / "root").mkdir(parents=True)
    for rel, kind, mode, target in entries:
        dest = bundle / "root" / rel
        if kind == "dir":
            dest.mkdir()
        elif kind == "link":
            os.symlink(target, dest)
        elif rel not in recipes:
            shutil.copyfile(root / rel, dest)
            os.chmod(dest, mode)
    for rel, kind, mode, _ in reversed(entries):
        if kind == "dir":
            os.chmod(bundle / "root" / rel, mode)

    with tempfile.TemporaryDirectory(prefix="release-") as tmp:
        work = Path(tmp)
        # the expected hashes come from root.apfs and the recipes from the root tree: they must be one build
        run([sys.executable, REPO / "hackios-xnu-userland/tools/apfs/mkapfs.py", "-z", "--plain", "fw",
             "-o", work / "root.apfs", f"{volume}={root}"], stdout=subprocess.DEVNULL)
        if digest(work / "root.apfs") != digest(root_image):
            raise SystemExit("the root tree does not pack into root.apfs: run tools/k90auto/package.py again")

        print("build-release: the loader image without its payload")
        minimal = work / "loader-only.bin"
        run([sys.executable, K / "xnuloader/mkpayload.py", "-o", minimal, f"loader.efi={loader_efi}",
             "--identity", "v57", "--usb"], stdout=subprocess.DEVNULL)
        (bundle / "payload").mkdir()
        shell = bundle / "payload/loader-shell.img"
        run([sys.executable, K / "tools/reseal-loader-img.py", args.loader_image, minimal, "-o", shell],
            stdout=subprocess.DEVNULL)
        boot = boot_image(work, args.kernel, root_image, flashboot, shell, "boot")
        reference = boot_image(work, args.kernel, root_image, flashboot, args.loader_image, "reference")
        if digest(boot) != digest(reference):
            raise SystemExit("a boot image sealed in the loader shell differs from one sealed in --loader-image")
        if args.expect_boot and digest(boot) != digest(args.expect_boot):
            raise SystemExit(f"the boot image made here differs from {args.expect_boot}")
        boot_sha = digest(boot)

    shutil.copyfile(args.kernel, bundle / "payload/kernel.bin")
    shutil.copyfile(flashboot, bundle / "payload/flashboot.apfs")
    (bundle / "android").mkdir()
    for path in android:
        shutil.copyfile(path, bundle / "android" / path.name)
        os.chmod(bundle / "android" / path.name, 0o755)
    for rel in BUNDLED_TOOLS:
        (bundle / rel).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO / rel, bundle / rel)
    (bundle / "LICENSES").mkdir()
    for name, path in LICENSES.items():
        shutil.copyfile(path, bundle / "LICENSES" / name)
    (bundle / "local-files.plist").write_bytes(plistlib.dumps(
        {"format": localfiles.FORMAT, "files": [recipes[rel] for rel in sorted(recipes)]}, fmt=plistlib.FMT_BINARY))

    manifest = {
        "version": args.version,
        "built": datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "commits": commits,
        "ios": {"version": system["ProductVersion"], "build": system["ProductBuildVersion"], "device": "iPhone18,3",
                "ipsw": IPSW_SOURCE,
                "dmg_bytes": {n: (IPSW / f"{n}.dmg").stat().st_size for n in ("os", "systemos", "appos")}},
        "volume": volume,
        "root": {"entries": [list(e) for e in entries]},
        "expected": {"tree_sha256": localfiles.tree_digest(root), "root_sha256": digest(root_image),
                     "boot_sha256": boot_sha, "zlib": zlib.ZLIB_RUNTIME_VERSION,
                     "firmware_sha256": {r["name"]: r["sha256"] for r in recipes.values() if r["kind"] == "firmware"}},
        "files": {},
    }
    for path in sorted(p for p in bundle.rglob("*") if p.is_file() and not p.is_symlink()):
        manifest["files"][path.relative_to(bundle).as_posix()] = digest(path)
    (bundle / "manifest.json").write_text(json.dumps(manifest, indent=1) + "\n")

    private(bundle)
    archive = args.output / f"{bundle.name}.tar.gz"
    write_tar(bundle, archive)
    (args.output / f"{archive.name}.sha256").write_text(f"{digest(archive)}  {archive.name}\n")
    sizes = {}
    for r in recipes.values():
        sizes[r["kind"]] = sizes.get(r["kind"], 0) + 1
    # bytes of the values the edit lists publish, to review what a release carries of iOS's files
    published = sum(len(localfiles.dump_plist({"v": e[2]})) for r in recipes.values() if r["kind"] in ("plist", "cache")
                    for e in r["edits"] if e[0] == "set")
    print(f"build-release: {archive} ({archive.stat().st_size} bytes)")
    print(f"build-release: local files by kind {sizes}; property list edits carry {published} bytes of values")
    print(f"build-release: expected root.apfs {manifest['expected']['root_sha256']}, boot image {boot_sha}")
    for rel in review:
        print(f"build-release: review: {rel} is in the release under an Apple name")


if __name__ == "__main__":
    main()
