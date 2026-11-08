#!/usr/bin/env python3
"""Install an .ipa on the iOS a held round is running, over USB, without a new image.

usage: tools/k90auto/install-ipa.py [ROUND_DIR] [FILE.ipa] [--open]

The file goes to the phone in pieces of at most 15 MB, each through the kernel's 16 MB inbox
(run-auto.py's push request, then rwsh "pull PATH OFFSET" into /private/var/tmp/ipa/). appinst's
watcher, started at boot from rc.jobs.interactive, installs it once the whole archive is there;
this waits until "appinst list" names the application, and --open launches it.

Before uploading, Mach-O binaries in Payload (main executable, frameworks, dylibs, appex plugins)
are recursively signed with ad-hoc signatures and necessary entitlements (get-task-allow, application-groups).
Once registered, com.annibale.var_save is posted to persist installed state immediately into dsu_store.

Arbitrary IPA paths can be supplied via argument or through the IPA_PATH or K90_IPA environment variable.
Exit status: 0 once installed, 1 otherwise.
"""
import hashlib
import io
import json
import os
import plistlib
import shutil
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


def is_macho(path):
    """Whether the file at path is a Mach-O binary."""
    try:
        with open(path, "rb") as f:
            head = f.read(4)
        if len(head) < 4:
            return False
        magic_le = struct.unpack("<I", head)[0]
        magic_be = struct.unpack(">I", head)[0]
        return magic_le in (0xfeedface, 0xfeedfacf) or magic_be in (0xcafebabe, 0xcafebabf)
    except OSError:
        return False


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


def adhoc_sign_python(path, ent_path):
    """Pure-python fallback ad-hoc Mach-O signer embedding entitlements."""
    data = bytearray(path.read_bytes())
    if len(data) < 32:
        return False
    magic = struct.unpack_from("<I", data, 0)[0]
    if magic != 0xfeedfacf:
        return False

    ncmds, sizeofcmds = struct.unpack_from("<II", data, 16)
    at = 32
    cs_cmd_at = -1
    linkedit_at = -1
    first_fileoff = len(data)
    orig_dataoff = 0

    for _ in range(ncmds):
        cmd, size = struct.unpack_from("<II", data, at)
        if cmd == 0x19:
            segname = struct.unpack_from("<16s", data, at + 8)[0].split(b"\x00", 1)[0]
            fileoff = struct.unpack_from("<Q", data, at + 40)[0]
            if segname == b"__LINKEDIT":
                linkedit_at = at
            if fileoff > 0 and fileoff < first_fileoff:
                first_fileoff = fileoff
        elif cmd == 0x1d:
            cs_cmd_at = at
            orig_dataoff = struct.unpack_from("<II", data, at + 8)[0]
        at += size

    if linkedit_at == -1:
        return False

    ent_bytes = ent_path.read_bytes()
    ent_blob = struct.pack(">II", 0xfade7171, 8 + len(ent_bytes)) + ent_bytes
    req_blob = struct.pack(">III", 0xfade0c01, 12, 0)
    sig_blob = struct.pack(">II", 0xfade0b01, 8)

    ent_hash = hashlib.sha256(ent_blob).digest()
    req_hash = hashlib.sha256(req_blob).digest()

    code_limit = orig_dataoff if cs_cmd_at != -1 else len(data)
    if len(data) > code_limit:
        del data[code_limit:]
    while code_limit % 16 != 0:
        data.extend(b"\x00")
        code_limit += 1

    page_size = 4096
    n_code_slots = (code_limit + page_size - 1) // page_size
    n_special_slots = 5

    ident = path.stem.encode("utf-8") + b"\x00"
    ident_offset = 88
    hash_offset = ident_offset + len(ident)
    while hash_offset % 4 != 0:
        ident += b"\x00"
        hash_offset = ident_offset + len(ident)

    actual_hash_offset = hash_offset + n_special_slots * 32
    cd_length = actual_hash_offset + n_code_slots * 32

    cd_data = bytearray(cd_length)
    struct.pack_into(">IIIIIIIIIBBBBIIIIQQQQ", cd_data, 0,
        0xfade0c02, cd_length, 0x20400, 0x00000006, actual_hash_offset, ident_offset,
        n_special_slots, n_code_slots, code_limit, 32, 2, 0, 12,
        0, 0, 0, 0, 0, 0, 0, 0
    )
    cd_data[ident_offset:ident_offset+len(ident)] = ident
    cd_data[actual_hash_offset - 2 * 32 : actual_hash_offset - 1 * 32] = req_hash
    cd_data[actual_hash_offset - 5 * 32 : actual_hash_offset - 4 * 32] = ent_hash

    for i in range(n_code_slots):
        start = i * page_size
        end = min(start + page_size, code_limit)
        cd_data[actual_hash_offset + i * 32 : actual_hash_offset + (i + 1) * 32] = hashlib.sha256(data[start:end]).digest()

    sb_index_size = 12 + 4 * 8
    cd_offset = (sb_index_size + 15) & ~15
    req_offset = (cd_offset + len(cd_data) + 15) & ~15
    ent_offset = (req_offset + len(req_blob) + 15) & ~15
    sig_offset = (ent_offset + len(ent_blob) + 15) & ~15
    sb_total_size = (sig_offset + len(sig_blob) + 15) & ~15

    superblob = bytearray(sb_total_size)
    struct.pack_into(">III", superblob, 0, 0xfade0cc0, sb_total_size, 4)
    struct.pack_into(">II", superblob, 12, 0, cd_offset)
    struct.pack_into(">II", superblob, 20, 2, req_offset)
    struct.pack_into(">II", superblob, 28, 5, ent_offset)
    struct.pack_into(">II", superblob, 36, 0x10000, sig_offset)

    superblob[cd_offset:cd_offset+len(cd_data)] = cd_data
    superblob[req_offset:req_offset+len(req_blob)] = req_blob
    superblob[ent_offset:ent_offset+len(ent_blob)] = ent_blob
    superblob[sig_offset:sig_offset+len(sig_blob)] = sig_blob

    data.extend(superblob)

    if cs_cmd_at != -1:
        struct.pack_into("<II", data, cs_cmd_at + 8, code_limit, sb_total_size)
    else:
        if first_fileoff < 32 + sizeofcmds + 16:
            return False
        cs_cmd = struct.pack("<IIII", 0x1d, 16, code_limit, sb_total_size)
        data[32 + sizeofcmds : 32 + sizeofcmds + 16] = cs_cmd
        struct.pack_into("<II", data, 16, ncmds + 1, sizeofcmds + 16)

    linkedit_fileoff = struct.unpack_from("<Q", data, linkedit_at + 40)[0]
    new_filesize = (code_limit + sb_total_size) - linkedit_fileoff
    new_vmsize = (new_filesize + 0x3fff) & ~0x3fff
    struct.pack_into("<QQ", data, linkedit_at + 32, new_vmsize, new_filesize)

    path.write_bytes(data)
    path.chmod(0o755)
    return True


def sign_binary(path, ent_path):
    """Signs a single Mach-O binary using codesign utility or python fallback."""
    if shutil.which("codesign"):
        res = subprocess.run(["codesign", "--force", "--sign", "-", "--entitlements", str(ent_path), str(path)],
                             capture_output=True, text=True)
        if res.returncode == 0:
            return True
    return adhoc_sign_python(path, ent_path)


def prepare_ipa(ipa_path):
    """Unpack IPA, recursively sign all Mach-O binaries with entitlements, and return repacked IPA bytes."""
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        with zipfile.ZipFile(ipa_path, "r") as z:
            z.extractall(tmp)

        ent_dict = {
            "get-task-allow": True,
            "com.apple.private.security.no-sandbox": True,
            "com.apple.security.application-groups": [
                "group.com.SideStore.SideStore",
                "group.com.rileytestut.AltStore",
            ]
        }
        ent_path = tmp / "entitlements.plist"
        with open(ent_path, "wb") as f:
            plistlib.dump(ent_dict, f)

        payload_dir = tmp / "Payload"
        if not payload_dir.is_dir():
            raise RuntimeError(f"{ipa_path.name} contains no Payload/ directory")

        signed = 0
        for root, _, files in os.walk(payload_dir):
            for f in files:
                p = Path(root) / f
                if is_macho(p):
                    p.chmod(0o755)
                    if sign_binary(p, ent_path):
                        signed += 1
                        print(f"install-ipa: signed {p.relative_to(payload_dir)}")

        print(f"install-ipa: prepared {signed} Mach-O binary/binaries with AppGroup entitlements")

        out_buf = io.BytesIO()
        with zipfile.ZipFile(out_buf, "w", compression=zipfile.ZIP_DEFLATED) as zout:
            for root, _, files in os.walk(tmp):
                for f in files:
                    file_path = Path(root) / f
                    if file_path == ent_path:
                        continue
                    arcname = file_path.relative_to(tmp).as_posix()
                    zout.write(file_path, arcname)
        return out_buf.getvalue()


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


def find_running_round():
    evidence = Path(os.environ.get("K90_EVIDENCE", HERE.parent.parent / "docs/progress/evidence/k90auto"))
    if not evidence.is_dir():
        return None
    candidates = sorted(evidence.glob("kernel-*"), key=lambda p: p.stat().st_mtime, reverse=True)
    for c in candidates:
        run = c / "run"
        if run.is_dir() and not (run / "reboot.json").exists():
            return c
    return None


def main():
    args = [a for a in sys.argv[1:] if a != "--open"]
    open_after = "--open" in sys.argv

    round_dir = None
    ipa_path = None

    if len(args) == 2:
        round_dir = Path(args[0])
        ipa_path = Path(args[1])
    elif len(args) == 1:
        p = Path(args[0])
        if p.is_file() or p.suffix.lower() == ".ipa":
            ipa_path = p
            round_dir = find_running_round()
        else:
            round_dir = p
            env_ipa = os.environ.get("IPA_PATH") or os.environ.get("K90_IPA") or os.environ.get("LOCAL_IPA")
            if env_ipa:
                ipa_path = Path(env_ipa)
    elif len(args) == 0:
        env_round = os.environ.get("ROUND_DIR")
        round_dir = Path(env_round) if env_round else find_running_round()
        env_ipa = os.environ.get("IPA_PATH") or os.environ.get("K90_IPA") or os.environ.get("LOCAL_IPA")
        if env_ipa:
            ipa_path = Path(env_ipa)

    if not ipa_path or not ipa_path.is_file():
        print("install-ipa: IPA path must be provided via argument or IPA_PATH/K90_IPA environment variable")
        print(__doc__.strip())
        return 1

    if not round_dir or not (round_dir / "run").is_dir() or (round_dir / "run/reboot.json").exists():
        print(f"install-ipa: {round_dir} is not a running round (specify running ROUND_DIR or start cycle.py)")
        return 1

    identifier, name, is_encrypted = app_info(ipa_path)
    if is_encrypted:
        print(f"install-ipa: {ipa_path.name} ({identifier}) is encrypted by the App Store and cannot run here; "
              f"a decrypted copy is needed")
        return 1

    print(f"install-ipa: preparing and ad-hoc signing {ipa_path.name}...")
    data = prepare_ipa(ipa_path)
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
        installed_list = rsh(round_dir, "/annibale/bin/appinst", "list")
        if identifier in installed_list:
            print(f"install-ipa: {identifier} is installed")
            # Post var_save notification to persist immediately
            rsh(round_dir, "/annibale/bin/rwsh", "notify", "com.annibale.var_save")
            if open_after:
                print(rsh(round_dir, "/annibale/bin/appinst", "open", identifier).strip().splitlines()[-1])
            return 0
        time.sleep(3)

    print(f"install-ipa: {identifier} did not show up in appinst list within 180 s; see appinst lines in the log")
    return 1


if __name__ == "__main__":
    sys.exit(main())
