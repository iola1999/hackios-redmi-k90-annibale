#!/usr/bin/env python3
"""Check factory address export and release image verification without a connected phone."""
import contextlib
import io
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import assemble


class AssembleWifiTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.address = self.work / "factory.txt"
        # 00-00-5E-00-53 is reserved for documentation.
        self.example = bytes.fromhex("00005e0053ad").hex(":")
        self.serial = "fixture-device"

    def export(self, result):
        with patch.object(assemble.subprocess, "run", return_value=result) as adb:
            with contextlib.redirect_stdout(io.StringIO()) as output:
                assemble.export_wifi_mac(self.serial, self.address)
            self.assertNotIn(self.example, output.getvalue())
            self.assertNotIn(self.serial, output.getvalue())
            self.assertEqual(adb.call_args.args[0], ["adb", "-s", self.serial, "shell", "ethtool", "-P", "wlan0"])

    def test_export_is_canonical_and_private(self):
        self.address.write_text("old")
        self.address.chmod(0o644)
        reply = f"Permanent address: {self.example.upper()}\r\n".encode()
        self.export(subprocess.CompletedProcess([], 0, stdout=reply))
        self.assertEqual(self.address.read_text(), self.example + "\n")
        self.assertEqual(self.address.stat().st_mode & 0o777, 0o600)

    def test_bad_export_preserves_existing_file(self):
        self.address.write_text("original")
        one = f"Permanent address: {self.example}"
        for reply, code in [(one, 1), ("", 0), (one + "\n" + one, 0),
                            ("Permanent address: 02:00:00:00:00:00", 0),
                            ("Permanent address: ff:ff:ff:ff:ff:ff", 0)]:
            with self.subTest(reply=reply, code=code), self.assertRaises(SystemExit) as error:
                self.export(subprocess.CompletedProcess([], code, stdout=reply.encode(), stderr=self.serial.encode()))
            self.assertNotIn(self.serial, str(error.exception))
            self.assertNotIn(self.example, str(error.exception))
            self.assertEqual(self.address.read_text(), "original")

    def test_manifest_and_device_specific_boot(self):
        self.address.write_text(self.example + "\n")
        assemble.check_wifi_mac_input({}, None)
        with self.assertRaises(SystemExit):
            assemble.check_wifi_mac_input({}, self.address)
        with self.assertRaises(SystemExit):
            assemble.check_wifi_mac_input({"requires_factory_wifi_mac": True}, None)
        assemble.check_wifi_mac_input({"requires_factory_wifi_mac": True}, self.address)
        def write_image(command, **options):
            if str(command[1]).endswith("reseal-loader-img.py"):
                Path(command[-1]).write_bytes(b"test image")

        image = self.work / "boot"
        with patch.object(assemble, "run", side_effect=write_image) as run:
            assemble.seal_boot(self.work / "root", self.work / "payload", image, self.address)
        self.assertEqual(image.stat().st_mode & 0o777, 0o600)
        argv = run.call_args_list[0].args[0]
        self.assertEqual(argv[-2:], ["--wifi-mac-file", self.address])
        self.assertNotIn(self.example, " ".join(map(str, argv)))

    def test_build_checks_generic_reference_before_using_address(self):
        for name in assemble.DMGS:
            (self.work / f"{name}.dmg").write_bytes(b"x")
        self.address.write_text(self.example + "\n")
        output = self.work / "out"
        args = SimpleNamespace(ipsw=self.work, modem=self.address, bluetooth=self.address, zap=self.address,
                               iris=None, output=output, wifi_mac_file=self.address)
        empty = self.work / "empty"
        empty.mkdir()
        expected = dict(tree_sha256=assemble.localfiles.tree_digest(empty), root_sha256=assemble.localfiles.sha256(b"root"),
                        boot_sha256=assemble.localfiles.sha256(b"generic"), firmware_sha256={})
        manifest = {"requires_factory_wifi_mac": True, "root": {"entries": []}, "volume": "test",
                    "ios": {"dmg_bytes": dict.fromkeys(assemble.DMGS, 1)}, "expected": expected}
        def make_root(command, **kw):
            Path(command[command.index("-o") + 1]).write_bytes(b"root")
        def seal(root, payload, image, address=None):
            image.write_bytes(b"generic" if address is None else b"personal")
        with (patch.object(assemble, "load_release", return_value=(manifest, [])),
              patch.object(assemble, "seven_zip", return_value="7zz"), patch.object(assemble, "extract_ios"),
              patch.object(assemble, "var_skeleton"), patch.object(assemble, "firmware", return_value={}),
              patch.object(assemble, "run", side_effect=make_root), patch.object(assemble, "seal_boot", side_effect=seal) as sealer,
              contextlib.redirect_stdout(io.StringIO())):
            assemble.build(args)
            self.assertEqual(sealer.call_count, 2)
            self.assertEqual((output / "boot-ios.img").read_bytes(), b"personal")
            sealer.reset_mock()
            expected["boot_sha256"] = "invalid"
            with self.assertRaisesRegex(SystemExit, "generic boot image"):
                assemble.build(args)
            self.assertEqual(sealer.call_count, 1)
            self.assertEqual((output / "boot-ios.img").read_bytes(), b"personal")


if __name__ == "__main__":
    unittest.main()
