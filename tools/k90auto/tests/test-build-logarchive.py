#!/usr/bin/env python3
"""Host tests for build-logarchive.py uuidtext, DSC hcsd, and /usr/bin/log show compatibility."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import plistlib
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import uuid

HERE = Path(__file__).resolve().parent.parent
REPO_ROOT = HERE.parent.parent
spec = importlib.util.spec_from_file_location("build_logarchive", HERE / "build-logarchive.py")
build_logarchive = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build_logarchive)

IOS_DSC_DIR = REPO_ROOT / "hackios-xnu-kernel" / "ios26" / "23G90__iPhone18,3"


def _build_synthetic_trace_inputs(diag_dir: Path, boot_uuid_bytes: bytes) -> None:
    """Create minimal timesync and Persist/*.tracev3 inputs."""
    ts_dir = diag_dir / "timesync"
    persist_dir = diag_dir / "Persist"
    ts_dir.mkdir(parents=True, exist_ok=True)
    persist_dir.mkdir(parents=True, exist_ok=True)

    boot_rec = struct.pack(
        "<II16sIIQq",
        0x0030BBB0,
        0,
        boot_uuid_bytes,
        125,
        3,
        1_795_000_000_000_000_000,
        0,
    )
    sync_rec = struct.pack(
        "<IIQQq",
        0x00207354,
        0,
        24_000_000,
        1_795_000_001_000_000_000,
        0,
    )
    (ts_dir / "0000000000000001.timesync").write_bytes(boot_rec + sync_rec)

    hdr_payload = struct.pack("<IIQQIi", 125, 3, 24_000_000, 1_795_000_001, 0, 0)
    hdr_payload = hdr_payload.ljust(208, b"\x00")
    hdr_chunk = struct.pack("<IIQ", 0x1000, 0x11, len(hdr_payload)) + hdr_payload
    (persist_dir / "0000000000000001.tracev3").write_bytes(hdr_chunk)


class BuildLogarchiveTest(unittest.TestCase):
    def test_macho_uuidtext_format_from_compiled_binary(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            src = root / "probe.c"
            bin_path = root / "probe"
            src.write_text(
                '#include <os/log.h>\n'
                'int main(void) {\n'
                '    const char *msg = "ENG24_CSTRING_MARKER";\n'
                '    os_log(OS_LOG_DEFAULT, "ENG24_OSLOG_MARKER %s", msg);\n'
                '    return 0;\n'
                '}\n'
            )
            subprocess.run(["cc", str(src), "-o", str(bin_path)], check=True)

            parsed = build_logarchive.parse_standalone_macho(bin_path)
            self.assertIsNotNone(parsed)
            uuid_bytes, entries = parsed
            self.assertEqual(len(uuid_bytes), 16)
            self.assertGreaterEqual(len(entries), 1)

            joined = b"".join(blob for _off, blob in entries)
            self.assertIn(b"ENG24_CSTRING_MARKER", joined)
            self.assertIn(b"ENG24_OSLOG_MARKER", joined)

            diag_dir = root / "diagnostics"
            _build_synthetic_trace_inputs(diag_dir, uuid.uuid4().bytes)
            out_arc = root / "out.logarchive"
            stats = build_logarchive.assemble_logarchive(
                diagnostics_dir=diag_dir,
                output_dir=out_arc,
                cache_dir=None,
                trees=[],
                extra_binaries=[("/usr/local/bin/probe", bin_path)],
            )
            self.assertEqual(stats["uuidtext_files"], 1)
            self.assertEqual(stats["trace_files"], 1)

            uuid_hex = uuid_bytes.hex().upper()
            ut_file = out_arc / uuid_hex[:2] / uuid_hex[2:]
            self.assertTrue(ut_file.is_file())
            raw = ut_file.read_bytes()

            magic, ver, subver, n_entries = struct.unpack_from("<4I", raw, 0)
            self.assertEqual((magic, ver, subver, n_entries), (0x66778899, 2, 1, len(entries)))
            cursor = 16
            parsed_table = []
            for _ in range(n_entries):
                rel_off, sz = struct.unpack_from("<II", raw, cursor)
                parsed_table.append((rel_off, sz))
                cursor += 8
            for (exp_off, exp_blob), (got_off, got_sz) in zip(entries, parsed_table):
                self.assertEqual(got_off, exp_off)
                self.assertEqual(got_sz, len(exp_blob))
                self.assertEqual(raw[cursor : cursor + got_sz], exp_blob)
                cursor += got_sz
            self.assertEqual(raw[cursor:], b"/usr/local/bin/probe\x00")

    def test_dsc_hcsd_v2_from_ios26_cache_subset(self):
        if not IOS_DSC_DIR.is_dir():
            self.skipTest(f"missing iOS DSC fixture: {IOS_DSC_DIR}")
        with tempfile.TemporaryDirectory() as td:
            out_dir = Path(td)
            targets = [
                "/usr/lib/libobjc.A.dylib",
                "/usr/lib/system/libsystem_c.dylib",
                "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation",
            ]
            dsc_path, n_ranges, n_uuids = build_logarchive.build_dsc_uuidtext(
                IOS_DSC_DIR, out_dir, image_filter=targets
            )
            self.assertTrue(dsc_path.is_file())
            self.assertEqual(n_uuids, len(targets))
            self.assertGreaterEqual(n_ranges, 3)

            raw = dsc_path.read_bytes()
            magic, ver, got_ranges, got_uuids = struct.unpack_from("<4sIII", raw, 0)
            self.assertEqual((magic, ver, got_ranges, got_uuids), (b"hcsd", 2, n_ranges, n_uuids))

            data_start = 16 + got_ranges * 24 + got_uuids * 32
            prev_dsc_off = -1
            expected_data_off = data_start
            for i in range(got_ranges):
                dsc_off, file_off, text_sz, uuid_idx = struct.unpack_from("<QIIQ", raw, 16 + i * 24)
                self.assertGreaterEqual(dsc_off, prev_dsc_off)
                prev_dsc_off = dsc_off
                self.assertEqual(file_off, expected_data_off)
                self.assertGreater(text_sz, 0)
                self.assertLess(uuid_idx, got_uuids)
                expected_data_off += text_sz

            seen_uuids = set()
            for j in range(got_uuids):
                img_off, img_sz, path_field, uuid_b = struct.unpack_from(
                    "<QII16s", raw, 16 + got_ranges * 24 + j * 32
                )
                self.assertGreater(img_sz, 0)
                self.assertGreater(img_off, 0)
                self.assertEqual(path_field, 0)
                seen_uuids.add(uuid_b)
            self.assertEqual(len(seen_uuids), got_uuids)

            trailing_paths = raw[expected_data_off:].split(b"\x00")[:-1]
            self.assertEqual(len(trailing_paths), got_uuids)
            decoded_paths = {p.decode("utf-8") for p in trailing_paths}
            self.assertEqual(decoded_paths, set(targets))

    def test_ios26_standalone_rootfs_binary_extraction(self):
        rootfs_dir = REPO_ROOT / "hackios-xnu-userland" / "ios26" / "rootfs"
        sample_bin = rootfs_dir / "usr" / "libexec" / "locationd"
        if not sample_bin.is_file():
            sample_bin = rootfs_dir / "usr" / "sbin" / "locationd"
        if not sample_bin.is_file():
            self.skipTest("iOS rootfs locationd binary not present")

        parsed = build_logarchive.parse_standalone_macho(sample_bin)
        self.assertIsNotNone(parsed)
        uuid_bytes, entries = parsed
        self.assertEqual(len(uuid_bytes), 16)
        self.assertGreater(len(entries), 0)

    def test_assembled_archive_readable_by_host_log_show(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            host_arc = root / "host_collect.logarchive"
            collect = subprocess.run(
                ["/usr/bin/log", "collect", "--last", "10s", "--output", str(host_arc)],
                capture_output=True,
                text=True,
            )
            if collect.returncode != 0:
                self.skipTest(f"/usr/bin/log collect unavailable: {collect.stderr.strip()}")

            # Strip Info.plist and host uuidtext to simulate raw /private/var/db/diagnostics pull.
            raw_diag = root / "diagnostics"
            raw_diag.mkdir()
            for sub in ("Persist", "Special", "Signpost", "HighVolume", "timesync"):
                src = host_arc / sub
                if src.is_dir():
                    shutil.copytree(src, raw_diag / sub)
            live = host_arc / "logdata.LiveData.tracev3"
            if live.is_file():
                shutil.copy2(live, raw_diag / "logdata.LiveData.tracev3")

            rebuilt = root / "rebuilt.logarchive"
            dsc_dir = IOS_DSC_DIR if IOS_DSC_DIR.is_dir() else None
            stats = build_logarchive.assemble_logarchive(
                diagnostics_dir=raw_diag,
                output_dir=rebuilt,
                cache_dir=dsc_dir,
                trees=[],
                image_filter=["/usr/lib/libobjc.A.dylib"] if dsc_dir else None,
            )
            self.assertGreaterEqual(stats["trace_files"], 1)

            # Copy host archive's real uuidtext/dsc entries in a separate copy? Here verify rebuilt alone passes log show!
            with open(rebuilt / "Info.plist", "rb") as stream:
                plist = plistlib.load(stream)
            self.assertEqual(plist["OSArchiveVersion"], 6)
            for key in ("PersistMetadata", "SpecialMetadata", "SignpostMetadata", "HighVolumeMetadata", "LiveMetadata"):
                self.assertIn("OldestTimeRef", plist[key])

            show = subprocess.run(
                ["/usr/bin/log", "show", "--archive", str(rebuilt), "--style", "json"],
                capture_output=True,
                text=True,
            )
            self.assertEqual(show.returncode, 0, msg=show.stderr)
            events = json.loads(show.stdout)
            self.assertIsInstance(events, list)
            self.assertGreater(len(events), 0)


if __name__ == "__main__":
    unittest.main()
