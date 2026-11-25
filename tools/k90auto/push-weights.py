#!/usr/bin/env python3
"""Stage the espresso weights and mubb backbones into /private/var/annibale-weights on the phone.

usage: tools/k90auto/push-weights.py [--assemble-only] [--verify-only] [--force] [--only SUBSTR]
                                     [--round ROUND_DIR | -] [--sftp HOST [--key KEY] [--user USER]]

Two phases:

  assemble   hardlink the staging tree out of the batch's assets: the 22 weights of
             deploy/copy-map-final.json and the two mubb jit compile products, the latter
             laid out as universal.bundle (jit.e5 renamed universal.e5, e5-compile-harness.md
             section 6). The tree mirrors userland/weights.list, the same manifest init binds by.
             Default staging dir: out/goal-1124/batch5/staging/annibale-weights.

  transfer   oem push mode (default): every file goes in pieces of at most 15 MB through the
             kernel inbox ("oem push", then annsh "pull TEMP OFFSET"), and a final "mv" gives it
             its own name -- the pull lines must stay within one 119-byte "oem sh" command, the
             mv may be staged through the inbox because the binary pieces are already on disk.
             --sftp instead copies the tree over Wi-Fi SSH (docs/progress/2026-11-23-ssh-over-wifi.md),
             much faster, and needs the round to run sshd.

Files already at their size on the phone are skipped (--force re-pushes). Verification is a
remote size comparison of every file; init repeats it at boot against weights.list, and a
bit-flip inside a correctly sized file would surface as an espresso load error in the first
round -- USB transport is checksummed, so the residual risk is accepted and documented.

--only MRC5heads stages the one probe weight of weights-bind-impl.md layer 0 (4.4 MB, a single
piece; its 148-byte name exercises the APFS_SYNTH_NAMELEN patch as well as the file bind).
"""
import hashlib
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parent.parent
BATCH = WORKSPACE / "out/goal-1124/batch5"
USERLAND = WORKSPACE / "hackios-xnu-userland/userland"
STAGING = BATCH / "staging/annibale-weights"
REMOTE_ROOT = "/private/var/annibale-weights"
TEMP = "/private/var/tmp/annibale-wpiece"
PIECE = 15 << 20

spec = importlib.util.spec_from_file_location("install_ipa", HERE / "install-ipa.py")
ipa = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ipa)


def load_manifest():
    """The weights.list entries: (kind, size, staging-relative source, target)."""
    entries = []
    for line in (USERLAND / "weights.list").read_text().splitlines():
        fields = line.split("\t")
        if len(fields) >= 4 and fields[0] in ("f", "d"):
            entries.append((fields[0], int(fields[1]), fields[2], fields[3]))
    return entries


def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def link_or_copy(src, dst):
    if dst.exists():
        dst.unlink()
    dst.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.link(src, dst)
    except OSError:
        shutil.copyfile(src, dst)


def assemble(staging, only=None):
    """The staging tree out of the batch's assets; idempotent, sha256-verified."""
    entries = load_manifest()
    copy_map = {"/" + e["dst"]: e for e in json.loads((BATCH / "deploy/copy-map-final.json").read_text())}
    made, skipped = 0, 0
    for kind, size, rel, target in entries:
        if only and only not in rel:
            continue
        if kind == "f":
            asset = copy_map.get(target)
            if asset is None:
                print(f"assemble: {target} is not in copy-map-final.json")
                return False
            src = BATCH / "macos-weights/assets" / asset["src"]
            dst = staging / rel
            if not src.is_file():
                print(f"assemble: missing asset {src}")
                return False
            if dst.exists() and dst.stat().st_size == size and sha256(dst) == asset["sha256"]:
                skipped += 1
                continue
            link_or_copy(src, dst)
            if sha256(dst) != asset["sha256"]:
                print(f"assemble: {dst.name}: sha256 mismatch after copying")
                return False
            made += 1
        else:
            md = "md7" if "md7" in rel else "md8"
            tree = BATCH / "e5-build" / md / "jit.bundle"
            dst = staging / rel
            if dst.exists() and sum(f.stat().st_size for f in dst.rglob("*") if f.is_file()) == size:
                skipped += 1
                continue
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(tree, dst)
            (dst / "jit.e5").rename(dst / "universal.e5")
            made += 1
    total = sum(f.stat().st_size for f in staging.rglob("*") if f.is_file())
    print(f"assemble: {staging}: {made} entries staged, {skipped} already correct, {total / 1e6:.1f} MB total")
    return True


def staging_files(staging, only=None):
    """Every file of the staging tree as (relative posix path, size), weights before mubb."""
    files = []
    for f in sorted(staging.rglob("*")):
        if f.is_file() and not f.is_symlink():
            rel = f.relative_to(staging).as_posix()
            if only and only not in rel:
                continue
            files.append((rel, f.stat().st_size))
    return files


def remote_sizes(rshv, dirs):
    """relpath -> size of the files already on the phone, by listing each directory."""
    sizes = {}
    for d in sorted(dirs):
        answer = rshv("ls", f"{REMOTE_ROOT}/{d}" if d else REMOTE_ROOT)
        for line in answer.splitlines():
            parts = line.split()
            if len(parts) == 3 and parts[0] in ("f", "d"):
                name = parts[2]
                sizes[f"{d}/{name}".strip("/")] = int(parts[1]) if parts[0] == "f" else -1
    return sizes


def push_oem(round_dir, staging, files, force):
    needed_dirs = {str(Path(rel).parent) if "/" in rel else "" for rel, _ in files}
    rshv = lambda *words: ipa.rsh(round_dir, *words)

    existing = remote_sizes(rshv, needed_dirs)
    mkdir_lines = [f"mkdir -p {REMOTE_ROOT}"] + [f"mkdir -p {REMOTE_ROOT}/{d}" for d in sorted(needed_dirs) if d]
    rshv("\n".join(mkdir_lines))   # multi-line: staged through the inbox, no binary in flight yet

    done = skipped = 0
    started = time.monotonic()
    for rel, size in files:
        if not force and existing.get(rel) == size:
            skipped += 1
            continue
        remote = f"{REMOTE_ROOT}/{rel}"
        pieces = (size + PIECE - 1) // PIECE
        print(f"push-weights: {rel} ({size / 1e6:.1f} MB, {pieces} piece(s))")
        rshv("rm", TEMP)
        data = (staging / rel).read_bytes()
        for at in range(0, size, PIECE):
            if not ipa.push(round_dir, data[at:at + PIECE]):
                print(f"push-weights: the piece at {at} of {rel} did not reach the phone")
                return False
            answer = rshv("pull", TEMP, str(at))
            # the pull line always names path and offset, success or not; a failure appends ": <error>"
            if f"to {TEMP} at {at}" not in answer or ": " in answer.split(f"at {at}", 1)[1].split("\n", 1)[0]:
                print(f"push-weights: the phone did not write the piece at {at} of {rel}:\n{answer[-300:]}")
                return False
        answer = rshv("mv", TEMP, remote)
        if any(line.startswith("mv ") for line in answer.splitlines()):
            print(f"push-weights: the phone did not move {rel} into place:\n{answer[-300:]}")
            return False
        done += 1
    rate = sum(s for r, s in files if existing.get(r) != s or force) / 1e6 / max(time.monotonic() - started, 1)
    print(f"push-weights: {done} files pushed, {skipped} already in place ({rate:.1f} MB/s)")
    return True


def verify_oem(round_dir, files):
    dirs = {str(Path(rel).parent) if "/" in rel else "" for rel, _ in files}
    rshv = lambda *words: ipa.rsh(round_dir, *words)
    present = remote_sizes(rshv, dirs)
    missing = [(rel, size) for rel, size in files if present.get(rel) != size]
    if not missing:
        print(f"push-weights: verified: all {len(files)} files at their size in {REMOTE_ROOT}")
        return True
    print(f"push-weights: {len(missing)} of {len(files)} files missing or wrong-sized:")
    for rel, size in missing[:10]:
        print(f"  {rel}: {present.get(rel, 'absent')} vs {size}")
    return False


def all_parent_dirs(files):
    """Every directory the tree needs, intermediate ones included, shortest first for mkdir order."""
    dirs = set()
    for rel, _ in files:
        parts = Path(rel).parent.parts
        for i in range(1, len(parts) + 1):
            dirs.add("/".join(parts[:i]))
    return sorted(dirs, key=lambda d: (d.count("/"), d))


def sftp_batch(host, key, user, staging, files):
    dirs = all_parent_dirs(files)
    lines = [f"-mkdir {REMOTE_ROOT}"] + [f"-mkdir {REMOTE_ROOT}/{d}" for d in dirs]
    for rel, _ in files:
        lines.append(f"put {staging / rel} {REMOTE_ROOT}/{rel}")
    cmd = ["sftp", "-b", "-", "-o", "StrictHostKeyChecking=accept-new"]
    if key:
        cmd += ["-i", str(key)]
    cmd.append(f"{user}@{host}")
    result = subprocess.run(cmd, input="\n".join(lines) + "\n", capture_output=True, text=True)
    if result.returncode != 0:
        print(f"push-weights: sftp failed:\n{result.stdout[-500:]}\n{result.stderr[-500:]}")
        return False
    print(f"push-weights: {len(files)} files copied over sftp")
    return True


def verify_sftp(host, key, user, files):
    dirs = sorted({str(Path(rel).parent) for rel, _ in files if "/" in rel} | {""})
    lines = [f"ls -l {REMOTE_ROOT}/{d}".rstrip("/") for d in dirs]
    cmd = ["sftp", "-b", "-", "-o", "StrictHostKeyChecking=accept-new"]
    if key:
        cmd += ["-i", str(key)]
    cmd.append(f"{user}@{host}")
    result = subprocess.run(cmd, input="\n".join(lines) + "\n", capture_output=True, text=True)
    present = {}
    current = ""
    for line in result.stdout.splitlines():
        # batch commands echo as "sftp> ls -l REMOTE"; the listing follows until the next echo
        if line.strip().startswith("sftp>"):
            parts = line.split()
            for part in parts:
                if part.startswith(REMOTE_ROOT):
                    current = part[len(REMOTE_ROOT):].strip("/")
            continue
        parts = line.split()
        if len(parts) >= 9 and parts[0].startswith("-"):
            try:
                present[f"{current}/{parts[-1]}".strip("/")] = int(parts[4])
            except ValueError:
                pass
    missing = [(rel, size) for rel, size in files if present.get(rel) != size]
    if not missing:
        print(f"push-weights: verified: all {len(files)} files at their size in {REMOTE_ROOT}")
        return True
    print(f"push-weights: {len(missing)} of {len(files)} files missing or wrong-sized after sftp")
    for rel, size in missing[:10]:
        print(f"  {rel}: {present.get(rel, 'absent')} vs {size}")
    return False


def main():
    args = sys.argv[1:]
    only = None
    force = "--force" in args
    round_dir, sftp_host, key, user = None, None, None, "root"
    staging = STAGING
    i = 0
    while i < len(args):
        if args[i] == "--only" and i + 1 < len(args):
            only = args[i + 1]
            i += 2
        elif args[i] == "--round" and i + 1 < len(args):
            round_dir = args[i + 1]
            i += 2
        elif args[i] == "--sftp" and i + 1 < len(args):
            sftp_host = args[i + 1]
            i += 2
        elif args[i] == "--key" and i + 1 < len(args):
            key = args[i + 1]
            i += 2
        elif args[i] == "--user" and i + 1 < len(args):
            user = args[i + 1]
            i += 2
        else:
            i += 1
    assemble_only = "--assemble-only" in args
    verify_only = "--verify-only" in args

    if not assemble(staging, only):
        return 1
    if assemble_only:
        return 0

    files = staging_files(staging, only)
    if not files:
        print(f"push-weights: nothing staged in {staging}" + (f" for --only {only}" if only else ""))
        return 1
    total = sum(s for _, s in files)
    print(f"push-weights: {len(files)} files, {total / 1e6:.1f} MB")

    if sftp_host:
        if verify_only:
            return 0 if verify_sftp(sftp_host, key, user, files) else 1
        return 0 if sftp_batch(sftp_host, key, user, staging, files) and verify_sftp(sftp_host, key, user, files) else 1

    if round_dir is None:
        round_dir = ipa.find_running_round()
    if round_dir is None:
        print("push-weights: no running round found; pass --round ROUND_DIR (or '-' for direct fastboot) or --sftp HOST")
        return 1
    if verify_only:
        return 0 if verify_oem(round_dir, files) else 1
    if not push_oem(round_dir, staging, files, force):
        return 1
    return 0 if verify_oem(round_dir, files) else 1


if __name__ == "__main__":
    sys.exit(main())
