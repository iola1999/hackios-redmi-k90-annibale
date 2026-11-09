#!/usr/bin/env python3
"""Make a desktop payload (kernel + root image + boot-args) for an unattended run.

usage: tools/k90auto/make-payload.py NAME LABEL RAMDISK "EXTRA BOOT-ARGS"

NAME is a registered kernel build; RAMDISK a root image under hackios-xnu-kernel/ (for an
unattended run one whose etc/rc.jobs is rc.jobs.desktop); EXTRA BOOT-ARGS are added after the fixed
ones (GPU stage 23 with the secure handover, two prime cores, the Goodix touch screen, the volume and
power keys, the battery gauge). Prints the run directory to give run-queue.sh. Run from the top of
the workspace.

env: K90_EVIDENCE (default docs/progress/evidence/k90auto), CPU_ARGS (default
"cpus=2 bootcpu=7 small_cores_after=0"), GPU_SPEED (adreno8_speed, default 3: up to 342 MHz with load;
kernels before 34209c1 need 1), GPU_STAGE (adreno8, default 23; 0 boots without the GPU),
BOOT_IMAGE (workspace-relative flashboot APFS image, default hackios-xnu-kernel/userland/flashboot.apfs),
MEMSIZE and IDENTITY (passed to mkpayload.py as --memsize and --identity; iOS 26 needs
300000000 and v57).
"""
from pathlib import Path
import hashlib
import json
import os
import re
import struct
import subprocess
import sys

name, label, ramdisk_arg, extra = sys.argv[1:5]
assert re.fullmatch(r"[a-z0-9-]+", label) and re.fullmatch(r"[A-Za-z0-9_=.,: -]*", extra)
evidence = Path(os.environ.get("K90_EVIDENCE", "docs/progress/evidence/k90auto"))
record = json.loads((evidence / ("kernel-" + name) / "kernel.json").read_text())
base = evidence / f"kernel-{name}-{label}"
# The round directory is what keeps two packs with the same label from sharing a record, so the
# collision is checked here. Creating it here instead left an empty directory behind whenever an
# assertion below fired (hit on 2026-10-28); it is created when the record is ready to write.
assert not base.exists(), f"{base} already exists: this label has a round record"
root = Path("hackios-xnu-kernel")
kernel = Path(record["kernel"]["path"])
ramdisk = root / ramdisk_arg
payload = root / f"out/handoff-{name}-{label}.bin"
def digest(path):
    """Hash build inputs without keeping the whole file in memory."""
    result = hashlib.sha256()
    with Path(path).open("rb") as source:
        for chunk in iter(lambda: source.read(1 << 20), b""):
            result.update(chunk)
    return result.hexdigest()


assert digest(kernel) == record["kernel"]["sha256"]


def kernel_top(path):
    """The end of the kernel's highest segment, as an offset from boot_args.virtBase."""
    data = Path(path).read_bytes()
    magic, _, _, _, ncmds, _, _, _ = struct.unpack_from("<IiiIIIII", data)
    assert magic == 0xfeedfacf, f"{path} is not a 64-bit Mach-O"
    at, top = 32, 0
    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<II", data, at)
        if cmd == 0x19:                                  # LC_SEGMENT_64
            vmaddr, vmsize = struct.unpack_from("<QQ", data, at + 24)
            if vmsize and vmaddr >= 0xFFFFFFF004000000:
                top = max(top, vmaddr + vmsize - 0xFFFFFFF004000000)
        at += size
    return top


# The loader places the helper root immediately after the kernel. Both must end below the resident
# boot image at 128 MiB (xnuloader: RESIDENT_RD_OFFSET).
page = 0x4000
room = 0x08000000 - (kernel_top(kernel) + page - 1) // page * page
assert (ramdisk.stat().st_size + page - 1) // page * page <= room, (
    f"{ramdisk} is {ramdisk.stat().st_size} bytes and only {room} fit between the kernel and the resident image")
boot_image = Path(os.environ.get("BOOT_IMAGE", "hackios-xnu-kernel/userland/flashboot.apfs"))
assert boot_image.is_file(), f"{boot_image} is missing; build with FLASHBOOT=1 CRYPTEXES=flash"
boot_bytes = boot_image.stat().st_size
MAX_BOOT_IMAGE_BYTES = 64 * 1024 * 1024
assert 0 < boot_bytes <= MAX_BOOT_IMAGE_BYTES, (
    f"{boot_image} is {boot_bytes} bytes; the resident boot image limit is {MAX_BOOT_IMAGE_BYTES}")
cpu_args = os.environ.get("CPU_ARGS", "cpus=2 bootcpu=7 small_cores_after=0")
gpu_speed = int(os.environ.get("GPU_SPEED", "3"))
# GPU_STAGE=0 boots without the GPU: the kernel can then return to the loader (with the GPU it waits
# for a cold reset, see adreno8_quiesce), which is what a file left in kern.annibale.outbox needs.
gpu_stage = int(os.environ.get("GPU_STAGE", "23"))
memsize = os.environ.get("MEMSIZE", "")       # iOS 26 needs the RAM it is staged into: 300000000
identity = os.environ.get("IDENTITY", "")     # and the loader identity of that iOS: v57
# rootdev=md0 keeps the initial root on the boot volume; rd=md0 would do the same for the kernel, but launchd
# reads it as a restore environment and skips its boot tasks. root_apfs=ufs_darwin makes init mount
# the iOS APFS volume from UFS and switch to it. launchd_unsecure_cache=1 lets iOS 26's launchd take its jobs
# and its 733 AppExtensions records from /System/Library/xpc/launchd.plist, and launchd_cache_loader
# hands that cache over only with this boot-arg (it otherwise has to verify Apple's signature). Without
# them launchd prints "Skipping boot-task" instead of "Using unsecure cache" and no extension record
# ever reaches it. Every run before this harness carried them; the desktop of 2026-10-27 12:40 on the
# same root image (15 icons, two named widgets, four Dock icons) is one of those runs.
cmdline = (f"debug=0x10e rootdev=md0 root_apfs=ufs_darwin ufs=2 ufs_native=1 launchd_unsecure_cache=1 {cpu_args} adreno8={gpu_stage} adreno8_pause=0 adreno8_fine=0 adreno8_watch=0 "
           f"adreno8_keep=1 adreno8_return=0 adreno8_speed={gpu_speed} adreno8_secure_preflight=4 touchscreen=2 buttons=1 battery=1 "
           f"{extra}").strip()
# Fail here rather than discover it 400 seconds into a run: a payload that boots into a desktop with
# two icons looks exactly like a registration problem, and it took two days to see that the cache
# never arrived. REQUIRED is recorded in the manifest so a later diff shows whether a run had them.
REQUIRED = ("rootdev=md0", "root_apfs=ufs_darwin", "launchd_unsecure_cache=1",
            f"adreno8_speed={gpu_speed}")
absent = [arg for arg in REQUIRED if arg not in cmdline.split()]
assert not absent, f"boot-args lost {absent}: iOS 26's launchd will run with no cache and no AppExtensions"
for key in ("rootdev", "root_apfs", "ufs", "ufs_native"):
    assert sum(arg.split("=", 1)[0] == key for arg in cmdline.split()) == 1, f"duplicate {key} boot-arg"
assert not any(arg.split("=", 1)[0] == "rd" for arg in cmdline.split()), "rd= makes launchd boot as a restore environment"
argv = ["python3", "xnuloader/mkpayload.py", "-o", str(payload.relative_to(root)),
        "kernel=" + str(kernel.relative_to(root)), "ramdisk=" + str(ramdisk.relative_to(root)),
        "--cmdline", cmdline, "--exact-cmd", cmdline, "--require", "kernel=" + digest(kernel),
        "--require", "ramdisk=" + digest(ramdisk), "--forbid-cmd", "loader_return_after",
        "--forbid-entry", "rdimage", "--forbid-entry", "rdfile", "--forbid-entry", "rdres"]
if memsize:
    assert re.fullmatch(r"[0-9a-fA-F]+", memsize), memsize      # mkpayload.py reads hex bytes
    argv += ["--memsize", memsize]
if identity:
    assert re.fullmatch(r"[a-z0-9]+", identity), identity
    argv += ["--identity", identity]
subprocess.run(argv, cwd=root, check=True)
# The pack manifest beside the packed root says what that pack put in: whether the probe was added,
# which skeleton lines had to be appended because the base root was older
# than userland/var.skel.extra, and which driver the round will run. Without copying it here the round
# record answers "which files were uploaded" but not "what was in them", and the only copy lives in
# out/, which the next pack overwrites.
pack_manifest = ramdisk.parent / "manifest.json"
assert pack_manifest.is_file(), f"{pack_manifest} is missing: without it a round cannot say what it ran"
pack_record = json.loads(pack_manifest.read_text())
# The whole record, not a chosen list. A list was here until 2026-10-28 and it silently dropped every
# field added to the pack after the list was written: the freeze round ran the current package.py,
# which writes jobs_source, probe_sources, air_sources and jobs_effective_count, and the round record
# carried none of them. Copying the record keeps a future field from needing a second edit here.
pack = dict(pack_record)
assert pack["root_sha256"] == digest(ramdisk), (
    f"the pack beside {ramdisk} records root {str(pack['root_sha256'])[:16]} but the file hashes to "
    f"{digest(ramdisk)[:16]}: this root is not the one that pack made")
# Patches that did not apply, written by mk-mesa.sh beside the build. Copied verbatim: the parsing
# that decides what is a patch belongs to the script that applies them, and a round that lists its
# rejected patches can be read the same way a month later.
patch_rejects = ""
patch_rejects_file = Path(__file__).resolve().parent.parent.parent / "out/patch-rejects.txt"
if patch_rejects_file.is_file():
    patch_rejects = patch_rejects_file.read_text()

if pack["gpu_speed"] is not None:
    assert int(pack["gpu_speed"]) == gpu_speed, (
        f"the pack ran adreno8_speed={pack['gpu_speed']} but this payload boots adreno8_speed={gpu_speed}")
record.update({"ramdisk": {"path": str(ramdisk), "bytes": ramdisk.stat().st_size, "sha256": digest(ramdisk)},
               "cmdline": cmdline, "boot_cmdline": cmdline, "gpu_speed": gpu_speed,
               "cpu_args": cpu_args, "extra_boot_args": extra, "argv": argv,
               "required_cmdline": list(REQUIRED),
               "root_apfs": "ufs_darwin",
               "resident_boot": {"path": str(boot_image), "bytes": boot_bytes,
                                 "sha256": digest(boot_image)},
               "payload": {"path": str(payload), "bytes": payload.stat().st_size, "sha256": digest(payload)},
               "pack": pack, "patch_rejects": patch_rejects})
base.mkdir()
(base / "manifest.json").write_text(json.dumps(record, indent=2) + "\n")
print(base)
# The GPU speed is the one setting whose default (3) differs from what almost every earlier round
# used (1), so a round that forgets GPU_SPEED silently runs a different clock than the one it is being
# compared with. Printing it with the directory makes the real value part of what the operator pastes
# back, and the manifest keeps it next to the full cmdline.
print(f"gpu_speed={gpu_speed}")
