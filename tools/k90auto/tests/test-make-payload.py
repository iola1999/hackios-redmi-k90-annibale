#!/usr/bin/env python3
"""Offline unit tests for make-payload.py runtime --identity/--memsize validation and XNUP output."""
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

WORKSPACE = Path(__file__).resolve().parents[3]
MAKE_PAYLOAD = WORKSPACE / "tools/k90auto/make-payload.py"
MKPAYLOAD = WORKSPACE / "hackios-xnu-kernel/xnuloader/mkpayload.py"


def make_min_macho64():
    """Build a minimal 64-bit Mach-O with one LC_SEGMENT_64 fitting below RESIDENT_RD_OFFSET."""
    header = struct.pack("<IiiIIIII", 0xFEEDFACF, 0x0100000C, 0, 2, 1, 72, 0, 0)
    seg = struct.pack(
        "<II16sQQQQiiii",
        0x19,               # LC_SEGMENT_64
        72,                 # cmdsize
        b"__TEXT",
        0xFFFFFFF004000000, # vmaddr
        0x4000,             # vmsize (16 KiB)
        0,                  # fileoff
        0,                  # filesize
        5, 5, 0, 0,
    )
    return header + seg


def parse_xnup_entries(blob):
    """Parse XNUP payload header and return a dict of {entry_name: raw_bytes}."""
    magic, body_size = struct.unpack_from("<II", blob, 0)
    assert magic == 0x50554E58, f"unexpected magic {magic:#x}"
    assert len(blob) == 8 + body_size
    entries = {}
    pos = 8
    while pos < len(blob):
        raw_name, size, _ = struct.unpack_from("<16sII", blob, pos)
        pos += 24
        name = raw_name.split(b"\0", 1)[0].decode("ascii")
        if not name:
            break
        entries[name] = blob[pos:pos + size]
        pos += size + (-size % 16)
    return entries


def prepare_fake_workspace(root):
    """Create a minimal workspace tree with a dummy kernel, ramdisk, manifest, and flashboot."""
    kernel_repo = root / "hackios-xnu-kernel"
    (kernel_repo / "xnuloader").mkdir(parents=True)
    (kernel_repo / "out").mkdir(parents=True)
    (kernel_repo / "userland").mkdir(parents=True)
    (kernel_repo / "xnuloader/mkpayload.py").symlink_to(MKPAYLOAD)

    kernel_path = kernel_repo / "out/xnu12377-test.bin"
    kernel_bytes = make_min_macho64()
    kernel_path.write_bytes(kernel_bytes)
    kernel_sha = hashlib.sha256(kernel_bytes).hexdigest()

    ramdisk_dir = kernel_repo / "out/pack"
    ramdisk_dir.mkdir(parents=True)
    ramdisk_path = ramdisk_dir / "root.apfs"
    ramdisk_bytes = b"R" * 4096
    ramdisk_path.write_bytes(ramdisk_bytes)
    ramdisk_sha = hashlib.sha256(ramdisk_bytes).hexdigest()
    (ramdisk_dir / "manifest.json").write_text(json.dumps({
        "root_sha256": ramdisk_sha,
        "gpu_speed": 3,
    }))

    boot_path = kernel_repo / "userland/flashboot.apfs"
    boot_path.write_bytes(b"B" * 4096)

    evidence = root / "evidence"
    kdir = evidence / "kernel-12377-test"
    kdir.mkdir(parents=True)
    (kdir / "kernel.json").write_text(json.dumps({
        "kernel": {
            "path": "hackios-xnu-kernel/out/xnu12377-test.bin",
            "bytes": len(kernel_bytes),
            "sha256": kernel_sha,
        }
    }))
    return evidence


class MakePayloadValidationTests(unittest.TestCase):
    def invoke(self, args, env_overrides=None, cwd=None):
        env = {k: v for k, v in os.environ.items() if k not in ("MEMSIZE", "IDENTITY", "K90_WIFI_MAC_FILE")}
        if env_overrides:
            env.update(env_overrides)
        return subprocess.run(
            [sys.executable, str(MAKE_PAYLOAD), *args],
            cwd=cwd or WORKSPACE,
            env=env,
            capture_output=True,
            text=True,
        )

    def test_missing_both_memsize_and_identity_fails_fast(self):
        res = self.invoke(["12377-test", "r1", "out/pack/root.apfs", ""])
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("missing MEMSIZE and IDENTITY", res.stderr)

    def test_missing_only_memsize_or_identity(self):
        r1 = self.invoke(["12377-test", "r1", "out/pack/root.apfs", ""], {"IDENTITY": "v57"})
        self.assertNotEqual(r1.returncode, 0)
        self.assertIn("missing MEMSIZE", r1.stderr)

        r2 = self.invoke(["12377-test", "r1", "out/pack/root.apfs", ""], {"MEMSIZE": "300000000"})
        self.assertNotEqual(r2.returncode, 0)
        self.assertIn("missing IDENTITY", r2.stderr)

    def test_invalid_identity_rejected(self):
        for bad in ("v58", "V57", "iphone17", "d22 "):
            res = self.invoke(
                ["12377-test", "r1", "out/pack/root.apfs", ""],
                {"MEMSIZE": "300000000", "IDENTITY": bad},
            )
            self.assertNotEqual(res.returncode, 0, bad)
            self.assertIn("invalid IDENTITY", res.stderr)

    def test_invalid_memsize_format_range_and_alignment_rejected(self):
        cases = [
            ("0x300000000", "expected bare hex"),
            ("nothex", "expected bare hex"),
            ("0", "must be within"),
            ("10000000", "must be within"),
            ("400000000", "must be within"),
            ("300000001", "must be aligned"),
            ("301000000", "must be aligned"),
        ]
        for bad, snippet in cases:
            res = self.invoke(
                ["12377-test", "r1", "out/pack/root.apfs", ""],
                {"MEMSIZE": bad, "IDENTITY": "v57"},
            )
            self.assertNotEqual(res.returncode, 0, bad)
            self.assertIn(snippet, res.stderr)

    def test_conflicting_cli_and_env_rejected(self):
        r1 = self.invoke(
            ["--identity", "d22", "12377-test", "r1", "out/pack/root.apfs", ""],
            {"MEMSIZE": "300000000", "IDENTITY": "v57"},
        )
        self.assertNotEqual(r1.returncode, 0)
        self.assertIn("conflicting identity", r1.stderr)

        r2 = self.invoke(
            ["--memsize=180000000", "12377-test", "r1", "out/pack/root.apfs", ""],
            {"MEMSIZE": "300000000", "IDENTITY": "v57"},
        )
        self.assertNotEqual(r2.returncode, 0)
        self.assertIn("conflicting memsize", r2.stderr)

    def test_end_to_end_env_and_cli_flags_embed_entries_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            evidence = prepare_fake_workspace(root)

            r_env = self.invoke(
                ["12377-test", "r-env", "out/pack/root.apfs", "gpu_tl=1"],
                {"K90_EVIDENCE": str(evidence), "MEMSIZE": "300000000", "IDENTITY": "v57"},
                cwd=root,
            )
            self.assertEqual(r_env.returncode, 0, r_env.stderr)
            manifest_env = json.loads((evidence / "kernel-12377-test-r-env/manifest.json").read_text())
            self.assertEqual(manifest_env["memsize"], "300000000")
            self.assertEqual(manifest_env["identity"], "v57")
            entries_env = parse_xnup_entries((root / manifest_env["payload"]["path"]).read_bytes())
            self.assertEqual(entries_env["memsize"], b"300000000\0")
            self.assertEqual(entries_env["identity"], b"v57\0")

            r_cli = self.invoke(
                ["--memsize", "300000000", "--identity=v57", "12377-test", "r-cli", "out/pack/root.apfs", "-v"],
                {"K90_EVIDENCE": str(evidence)},
                cwd=root,
            )
            self.assertEqual(r_cli.returncode, 0, r_cli.stderr)
            manifest_cli = json.loads((evidence / "kernel-12377-test-r-cli/manifest.json").read_text())
            self.assertEqual(manifest_cli["memsize"], "300000000")
            self.assertEqual(manifest_cli["identity"], "v57")
            self.assertIn("-v", manifest_cli["cmdline"].split())
            entries_cli = parse_xnup_entries((root / manifest_cli["payload"]["path"]).read_bytes())
            self.assertEqual(entries_cli["memsize"], b"300000000\0")
            self.assertEqual(entries_cli["identity"], b"v57\0")


if __name__ == "__main__":
    unittest.main()
