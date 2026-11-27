#!/usr/bin/env python3
"""Assemble a macOS-readable .logarchive bundle from pulled HackiOS diagnostics."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import plistlib
import shutil
import struct
import sys
import uuid

REPO_ROOT = Path(__file__).resolve().parents[2]
DSC_TOOLS_DIR = REPO_ROOT / "hackios-xnu-kernel" / "tools" / "dsc"

MH_MAGIC_64 = 0xFEEDFACF
FAT_MAGIC = 0xCAFEBABE
FAT_CIGAM = 0xBEBAFECA
FAT_MAGIC_64 = 0xCAFEBABF
FAT_CIGAM_64 = 0xBFBAFECA
CPU_TYPE_ARM64 = 0x0100000C
CPU_SUBTYPE_ARM64E = 2

LC_SEGMENT_64 = 0x19
LC_UUID = 0x1B

UUIDTEXT_MAGIC = 0x66778899
UUIDTEXT_VERSION = 2
UUIDTEXT_SUBVERSION = 1

DSC_MAGIC = b"hcsd"
DSC_VERSION = 2

TIMESYNC_BOOT_SIG = 0xBBB0
TIMESYNC_SYNC_TAG = 0x00207354
TRACEV3_HEADER_TAG = 0x1000
TRACEV3_HEADER_SUBTAG = 0x11

DIAGNOSTIC_SUBDIRS = ("Persist", "Special", "Signpost", "HighVolume", "Extra", "timesync")
TEXT_STRING_SECTIONS = ("__cstring", "__oslogstring")

MACHO_HEAD_MAGICS = (
    b"\xcf\xfa\xed\xfe",
    b"\xca\xfe\xba\xbe",
    b"\xbe\xba\xfe\xca",
    b"\xca\xfe\xba\xbf",
    b"\xbf\xba\xfe\xca",
)


def _import_dsc_tools():
    dsc_str = str(DSC_TOOLS_DIR)
    if dsc_str not in sys.path:
        sys.path.insert(0, dsc_str)
    import cache as dsc_cache
    import macho as dsc_macho

    return dsc_cache, dsc_macho


def _cstr(raw: bytes) -> str:
    return raw.split(b"\x00", 1)[0].decode("utf-8", "replace")


def _select_macho_slice(raw: bytes) -> tuple[int, int] | None:
    """Return (slice_offset, slice_size) for a 64-bit little-endian Mach-O image."""
    if len(raw) < 32:
        return None
    le_magic = struct.unpack_from("<I", raw, 0)[0]
    if le_magic == MH_MAGIC_64:
        return 0, len(raw)
    be_magic = struct.unpack_from(">I", raw, 0)[0]
    if be_magic not in (FAT_MAGIC, FAT_MAGIC_64):
        return None
    is_64 = be_magic == FAT_MAGIC_64
    nfat = struct.unpack_from(">I", raw, 4)[0]
    entry_size = 32 if is_64 else 20
    if 8 + nfat * entry_size > len(raw):
        return None
    candidates: list[tuple[int, int, int, int]] = []
    for idx in range(nfat):
        base = 8 + idx * entry_size
        if is_64:
            cputype, cpusubtype, off, size = struct.unpack_from(">IIQQ", raw, base)
        else:
            cputype, cpusubtype, off, size, _align = struct.unpack_from(">IIIII", raw, base)
        if off + size > len(raw) or size < 32:
            continue
        if struct.unpack_from("<I", raw, off)[0] != MH_MAGIC_64:
            continue
        candidates.append((cputype, cpusubtype & 0x00FFFFFF, off, size))
    if not candidates:
        return None
    for cputype, subtype, off, size in candidates:
        if cputype == CPU_TYPE_ARM64 and subtype == CPU_SUBTYPE_ARM64E:
            return off, size
    for cputype, _subtype, off, size in candidates:
        if cputype == CPU_TYPE_ARM64:
            return off, size
    return candidates[0][2], candidates[0][3]


def parse_standalone_macho(path: Path) -> tuple[bytes, list[tuple[int, bytes]]] | None:
    """Extract (lc_uuid_16b, [(text_rel_offset, section_bytes), ...]) from a Mach-O file."""
    try:
        with open(path, "rb") as stream:
            head = stream.read(4)
            if head not in MACHO_HEAD_MAGICS:
                return None
            raw = head + stream.read()
    except OSError:
        return None
    selected = _select_macho_slice(raw)
    if selected is None:
        return None
    slice_off, slice_size = selected
    slice_view = memoryview(raw)[slice_off : slice_off + slice_size]
    magic, _cpu, _sub, _ft, ncmds, sizeofcmds, _flags, _res = struct.unpack_from("<IiiIIIII", slice_view, 0)
    if magic != MH_MAGIC_64 or 32 + sizeofcmds > len(slice_view):
        return None

    uuid_bytes: bytes | None = None
    text_vmaddr: int | None = None
    sections: list[tuple[int, int, int]] = []
    pos = 32
    end = 32 + sizeofcmds
    for _ in range(ncmds):
        if pos + 8 > end:
            return None
        cmd, cmdsize = struct.unpack_from("<II", slice_view, pos)
        if cmdsize < 8 or pos + cmdsize > end:
            return None
        if cmd == LC_UUID and cmdsize >= 24:
            uuid_bytes = bytes(slice_view[pos + 8 : pos + 24])
        elif cmd == LC_SEGMENT_64 and cmdsize >= 72:
            segname = _cstr(bytes(slice_view[pos + 8 : pos + 24]))
            if segname == "__TEXT":
                text_vmaddr = struct.unpack_from("<Q", slice_view, pos + 24)[0]
                nsects = struct.unpack_from("<I", slice_view, pos + 64)[0]
                sec_pos = pos + 72
                for _ in range(nsects):
                    if sec_pos + 80 > pos + cmdsize:
                        break
                    sectname = _cstr(bytes(slice_view[sec_pos : sec_pos + 16]))
                    if sectname in TEXT_STRING_SECTIONS:
                        addr, sec_size = struct.unpack_from("<QQ", slice_view, sec_pos + 32)
                        sec_off = struct.unpack_from("<I", slice_view, sec_pos + 48)[0]
                        if sec_size > 0 and sec_off + sec_size <= slice_size:
                            sections.append((addr, sec_off, sec_size))
                    sec_pos += 80
        pos += cmdsize

    if uuid_bytes is None:
        return None
    if text_vmaddr is None:
        return uuid_bytes, []
    blobs: list[tuple[int, bytes]] = []
    for addr, sec_off, sec_size in sections:
        if addr < text_vmaddr:
            continue
        blobs.append((addr - text_vmaddr, bytes(slice_view[sec_off : sec_off + sec_size])))
    return uuid_bytes, blobs


def encode_uuidtext_blob(entries: list[tuple[int, bytes]], runtime_path: str) -> bytes:
    """Encode a standalone Mach-O uuidtext file (magic 0x66778899 v2.1)."""
    parts = [struct.pack("<4I", UUIDTEXT_MAGIC, UUIDTEXT_VERSION, UUIDTEXT_SUBVERSION, len(entries))]
    for text_rel_off, data in entries:
        parts.append(struct.pack("<II", text_rel_off, len(data)))
    for _text_rel_off, data in entries:
        parts.append(data)
    parts.append(runtime_path.encode("utf-8") + b"\x00")
    return b"".join(parts)


def write_standalone_uuidtext(
    out_dir: Path,
    trees: list[tuple[str, Path]],
    extra_binaries: list[tuple[str, Path]],
) -> int:
    """Populate <XX>/<30HEX> uuidtext files from rootfs trees and explicit binaries."""
    written: set[str] = set()

    def emit(runtime_path: str, host_path: Path) -> None:
        parsed = parse_standalone_macho(host_path)
        if parsed is None:
            return
        uuid_bytes, entries = parsed
        uuid_hex = uuid_bytes.hex().upper()
        if uuid_hex in written:
            return
        written.add(uuid_hex)
        dest_dir = out_dir / uuid_hex[:2]
        dest_dir.mkdir(parents=True, exist_ok=True)
        (dest_dir / uuid_hex[2:]).write_bytes(encode_uuidtext_blob(entries, runtime_path))

    for prefix, tree_root in trees:
        if not tree_root.is_dir():
            continue
        norm_prefix = prefix.rstrip("/")
        for dirpath, dirnames, filenames in os.walk(tree_root, followlinks=False):
            dirnames.sort()
            filenames.sort()
            rel_dir = Path(dirpath).relative_to(tree_root)
            for name in filenames:
                fp = Path(dirpath) / name
                if fp.is_symlink() or not fp.is_file():
                    continue
                rel = (rel_dir / name).as_posix()
                runtime_path = f"{norm_prefix}/{rel}" if norm_prefix else f"/{rel}"
                emit(runtime_path, fp)

    for runtime_path, bin_path in extra_binaries:
        if bin_path.is_file():
            emit(runtime_path, bin_path)

    return len(written)


def build_dsc_uuidtext(
    cache_dir: Path,
    out_dir: Path,
    image_filter: list[str] | None = None,
) -> tuple[Path, int, int]:
    """Build dsc/<DSC_UUID> ('hcsd' v2) from a split dyld_shared_cache directory."""
    dsc_cache, dsc_macho = _import_dsc_tools()
    cache = dsc_cache.Cache(str(cache_dir))

    selected_images = cache.images
    if image_filter:
        wanted = set(image_filter)
        selected_images = [
            img for img in cache.images
            if img.path in wanted or Path(img.path).name in wanted
        ]

    uuid_records: list[tuple[int, int, bytes, str]] = []
    range_records: list[tuple[int, int, bytes]] = []

    for img in selected_images:
        macho_obj = dsc_macho.MachO(cache, img.address)
        found_uuid = macho_obj.find_command(LC_UUID)
        if found_uuid is None:
            continue
        uuid_off, uuid_sz = found_uuid
        if uuid_sz < 24:
            continue
        uuid_bytes = bytes(macho_obj.body[uuid_off + 8 : uuid_off + 24])
        text_seg = macho_obj.segment("__TEXT")
        text_size = img.text_size or (text_seg.vmsize if text_seg else 0)
        img_text_off = img.address - cache.shared_region_start
        uuid_idx = len(uuid_records)
        uuid_records.append((img_text_off, text_size, uuid_bytes, img.path))

        if text_seg is None:
            continue
        for sec in text_seg.sections:
            if sec.name not in TEXT_STRING_SECTIONS or sec.size <= 0:
                continue
            blob = cache.read(sec.addr, sec.size)
            range_records.append((sec.addr - cache.shared_region_start, uuid_idx, blob))

    range_records.sort(key=lambda item: item[0])

    n_ranges = len(range_records)
    n_uuids = len(uuid_records)
    data_cursor = 16 + n_ranges * 24 + n_uuids * 32

    chunks = [struct.pack("<4sIII", DSC_MAGIC, DSC_VERSION, n_ranges, n_uuids)]
    for dsc_text_off, uuid_idx, blob in range_records:
        chunks.append(struct.pack("<QIIQ", dsc_text_off, data_cursor, len(blob), uuid_idx))
        data_cursor += len(blob)

    for img_text_off, text_size, uuid_bytes, _path in uuid_records:
        chunks.append(struct.pack("<QII16s", img_text_off, text_size, 0, uuid_bytes))

    for _dsc_text_off, _uuid_idx, blob in range_records:
        chunks.append(blob)

    for _img_text_off, _text_size, _uuid_bytes, img_path in uuid_records:
        chunks.append(img_path.encode("utf-8") + b"\x00")

    dsc_out_dir = out_dir / "dsc"
    dsc_out_dir.mkdir(parents=True, exist_ok=True)
    dsc_out_path = dsc_out_dir / cache.uuid.upper()
    dsc_out_path.write_bytes(b"".join(chunks))
    return dsc_out_path, n_ranges, n_uuids


def _parse_timesync_refs(timesync_dir: Path) -> list[tuple[int, str, int, int, int]]:
    """Return [(continuous_time, boot_uuid_str, wall_ns, numer, denom), ...] from timesync files."""
    refs: list[tuple[int, str, int, int, int]] = []
    if not timesync_dir.is_dir():
        return refs
    for ts_file in sorted(timesync_dir.glob("*.timesync")):
        data = ts_file.read_bytes()
        off = 0
        cur_uuid: str | None = None
        cur_numer = 125
        cur_denom = 3
        while off + 16 <= len(data):
            tag = struct.unpack_from("<I", data, off)[0]
            sig = tag & 0xFFFF
            rec_size = (tag >> 16) & 0xFFFF
            if rec_size == 0 or off + rec_size > len(data):
                break
            if sig == TIMESYNC_BOOT_SIG and rec_size >= 48:
                _t, _f, uuid_b, numer, denom, wall_ns, _tz = struct.unpack_from("<II16sIIQq", data, off)
                cur_uuid = str(uuid.UUID(bytes=uuid_b)).upper()
                cur_numer = numer or 125
                cur_denom = denom or 3
                refs.append((0, cur_uuid, wall_ns, cur_numer, cur_denom))
            elif tag == TIMESYNC_SYNC_TAG and rec_size >= 32 and cur_uuid is not None:
                _t, _f, ct, wall_ns, _tz = struct.unpack_from("<IIQQq", data, off)
                refs.append((ct, cur_uuid, wall_ns, cur_numer, cur_denom))
            off += rec_size
    return refs


def _parse_tracev3_header_refs(diag_dir: Path) -> list[tuple[int, str, int, int, int]]:
    """Fallback time reference scan from tracev3 0x1000/0x11 file headers."""
    refs: list[tuple[int, str, int, int, int]] = []
    trace_files: list[Path] = []
    for sub in ("Persist", "Special", "Signpost", "HighVolume"):
        sub_dir = diag_dir / sub
        if sub_dir.is_dir():
            trace_files.extend(sorted(sub_dir.glob("*.tracev3")))
    live = diag_dir / "logdata.LiveData.tracev3"
    if live.is_file():
        trace_files.append(live)
    for tf in trace_files:
        head = tf.read_bytes()[:64]
        if len(head) < 48:
            continue
        tag, subtag, _paylen = struct.unpack_from("<IIQ", head, 0)
        if tag != TRACEV3_HEADER_TAG or subtag != TRACEV3_HEADER_SUBTAG:
            continue
        numer, denom, mach_ct, tv_sec, tv_usec = struct.unpack_from("<IIQQI", head, 16)
        wall_ns = tv_sec * 1_000_000_000 + tv_usec * 1_000
        refs.append((mach_ct, str(uuid.UUID(int=0)).upper(), wall_ns, numer or 125, denom or 3))
    return refs


def compute_time_bounds(diag_dir: Path) -> tuple[dict[str, object], dict[str, object]]:
    """Compute (oldest_ref, end_ref) metadata dictionaries for Info.plist."""
    refs = _parse_timesync_refs(diag_dir / "timesync")
    if not refs:
        refs = _parse_tracev3_header_refs(diag_dir)
    if not refs:
        zero_ref = {"ContinuousTime": 0, "UUID": str(uuid.UUID(int=0)).upper(), "WallTime": 0}
        return zero_ref, dict(zero_ref)

    first_ct, first_uuid, first_wall, _n0, _d0 = refs[0]
    last_ct, last_uuid, last_wall, last_numer, last_denom = refs[-1]
    # Advance EndTimeRef beyond the last periodic timesync checkpoint so events written before pull stay in range.
    pad_ns = 60_000_000_000
    pad_ticks = (pad_ns * last_denom) // (last_numer or 1)
    oldest_ref = {
        "ContinuousTime": int(first_ct),
        "UUID": first_uuid,
        "WallTime": int(first_wall),
    }
    end_ref = {
        "ContinuousTime": int(last_ct + pad_ticks),
        "UUID": last_uuid,
        "WallTime": int(last_wall + pad_ns),
    }
    return oldest_ref, end_ref


def build_info_plist(diag_dir: Path) -> bytes:
    """Build binary Info.plist (OSArchiveVersion 6) required by /usr/bin/log show."""
    oldest_ref, end_ref = compute_time_bounds(diag_dir)
    info = {
        "ArchiveIdentifier": str(uuid.uuid4()).upper(),
        "EndTimeRef": end_ref,
        "HighVolumeMetadata": {"OldestTimeRef": dict(oldest_ref)},
        "LiveMetadata": {"OldestTimeRef": dict(oldest_ref)},
        "OSArchiveVersion": 6,
        "PersistMetadata": {"OldestTimeRef": dict(oldest_ref)},
        "SignpostMetadata": {"OldestTimeRef": dict(oldest_ref)},
        "SourceIdentifier": str(uuid.uuid4()).upper(),
        "SpecialMetadata": {"OldestTimeRef": dict(oldest_ref)},
    }
    return plistlib.dumps(info, fmt=plistlib.FMT_BINARY)


def copy_diagnostics_tree(diag_dir: Path, out_dir: Path) -> int:
    """Copy tracev3/timesync data into out_dir and return total copied tracev3 count."""
    trace_count = 0
    for sub in DIAGNOSTIC_SUBDIRS:
        src = diag_dir / sub
        if src.is_dir():
            dst = out_dir / sub
            shutil.copytree(src, dst)
            if sub != "timesync":
                trace_count += sum(1 for p in dst.rglob("*.tracev3") if p.is_file())
    live = diag_dir / "logdata.LiveData.tracev3"
    if live.is_file():
        shutil.copy2(live, out_dir / "logdata.LiveData.tracev3")
        trace_count += 1
    return trace_count


def _default_trees() -> list[tuple[str, Path]]:
    base = REPO_ROOT / "hackios-xnu-userland" / "ios26"
    candidates = [
        ("/", base / "rootfs"),
        ("/System/Cryptexes/OS", base / "cryptex"),
        ("/System/Cryptexes/App", base / "cryptex-app"),
    ]
    return [(prefix, path) for prefix, path in candidates if path.is_dir()]


def _parse_tree_spec(spec: str) -> tuple[str, Path]:
    if "=" in spec:
        prefix, _, path_str = spec.partition("=")
        return prefix or "/", Path(path_str)
    return "/", Path(spec)


def _parse_binary_spec(spec: str) -> tuple[str, Path]:
    if "=" in spec:
        runtime_path, _, path_str = spec.partition("=")
        return runtime_path, Path(path_str)
    p = Path(spec)
    return f"/{p.name}", p


def assemble_logarchive(
    diagnostics_dir: Path,
    output_dir: Path,
    cache_dir: Path | None = None,
    trees: list[tuple[str, Path]] | None = None,
    extra_binaries: list[tuple[str, Path]] | None = None,
    image_filter: list[str] | None = None,
    overwrite: bool = False,
) -> dict[str, int | str]:
    """Build a complete .logarchive directory and return summary statistics."""
    if output_dir.suffix != ".logarchive":
        raise ValueError(f"output path must end with .logarchive: {output_dir}")
    if not diagnostics_dir.is_dir():
        raise FileNotFoundError(f"diagnostics directory not found: {diagnostics_dir}")

    if output_dir.exists():
        if not overwrite:
            raise FileExistsError(f"output already exists (pass --overwrite): {output_dir}")
        shutil.rmtree(output_dir)

    output_dir.mkdir(parents=True, exist_ok=True)
    trace_count = copy_diagnostics_tree(diagnostics_dir, output_dir)
    (output_dir / "Info.plist").write_bytes(build_info_plist(diagnostics_dir))

    dsc_ranges = 0
    dsc_uuids = 0
    dsc_path = ""
    if cache_dir is not None:
        if not cache_dir.is_dir():
            raise FileNotFoundError(f"shared cache directory not found: {cache_dir}")
        written_dsc, dsc_ranges, dsc_uuids = build_dsc_uuidtext(cache_dir, output_dir, image_filter)
        dsc_path = str(written_dsc)

    uuidtext_count = write_standalone_uuidtext(
        output_dir,
        trees or [],
        extra_binaries or [],
    )

    return {
        "trace_files": trace_count,
        "uuidtext_files": uuidtext_count,
        "dsc_ranges": dsc_ranges,
        "dsc_uuids": dsc_uuids,
        "dsc_path": dsc_path,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build a .logarchive from pulled iOS diagnostics and Mach-O/DSC inputs.")
    parser.add_argument("--diagnostics", required=True, type=Path, help="Pulled /private/var/db/diagnostics directory")
    parser.add_argument("--output", required=True, type=Path, help="Output .logarchive directory path")
    parser.add_argument(
        "--cache",
        type=Path,
        default=REPO_ROOT / "hackios-xnu-kernel" / "ios26" / "23G90__iPhone18,3",
        help="Split dyld_shared_cache directory",
    )
    parser.add_argument("--no-dsc", action="store_true", help="Skip generating dsc/<UUID> uuidtext table")
    parser.add_argument(
        "--tree",
        action="append",
        default=[],
        help="Root tree to scan ([PREFIX=]PATH); overrides default ios26/{rootfs,cryptex,cryptex-app}",
    )
    parser.add_argument("--no-rootfs", action="store_true", help="Skip scanning default ios26 rootfs/cryptex trees")
    parser.add_argument("--binary", action="append", default=[], help="Standalone Mach-O binary ([RUNTIME_PATH=]PATH)")
    parser.add_argument("--image", action="append", default=[], help="Restrict DSC extraction to specific image names/paths")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing output .logarchive")
    args = parser.parse_args(argv)

    cache_dir = None if args.no_dsc else args.cache
    if args.tree:
        trees = [_parse_tree_spec(item) for item in args.tree]
    elif args.no_rootfs:
        trees = []
    else:
        trees = _default_trees()

    binaries = [_parse_binary_spec(item) for item in args.binary]
    stats = assemble_logarchive(
        diagnostics_dir=args.diagnostics,
        output_dir=args.output,
        cache_dir=cache_dir,
        trees=trees,
        extra_binaries=binaries,
        image_filter=args.image or None,
        overwrite=args.overwrite,
    )
    print(
        f"built {args.output}: tracev3={stats['trace_files']} "
        f"uuidtext={stats['uuidtext_files']} dsc_uuids={stats['dsc_uuids']} "
        f"dsc_ranges={stats['dsc_ranges']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
