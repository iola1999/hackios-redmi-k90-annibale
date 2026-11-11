#!/usr/bin/env python3
"""Check loader recovery identity and RAM state without sending device commands."""
from pathlib import Path
import os
import runpy
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "recover-loader.py"


class RecoveryTests(unittest.TestCase):
    def invoke(self, devices, *, result="idle", ramdisk="idle 0 0 0", product="xnuloader"):
        sent = []
        state = {"ramdisk": ramdisk}

        def execute(argv, **kwargs):
            sent.append(argv)
            if argv == ["fastboot", "devices"]:
                out = devices
            elif argv == ["adb", "devices"]:
                out = "List of devices attached\n\tdevice\n"
            elif argv[:4] == ["fastboot", "-s", "xnuloader", "getvar"]:
                key = argv[-1]
                values = {"product": product, "result": result, "build-id": "test-build",
                          "ramdisk-state": state["ramdisk"]}
                out = f"(bootloader) {key}: {values[key]}\nFinished.\n"
            elif argv == ["fastboot", "-s", "xnuloader", "oem", "recovery"]:
                out = "OKAY\n"
            elif argv == ["fastboot", "-s", "xnuloader", "oem", "ramdisk", "none"]:
                state["ramdisk"] = "idle 0 0 0"
                out = "OKAY\n"
            else:
                self.fail(f"Unexpected device command: {argv}")
            return subprocess.CompletedProcess(argv, 0, out)

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(sys, "argv", [str(SOURCE), str(Path(directory) / "record")]), \
                patch.dict(os.environ, {"ANDROID_SERIAL": "test-android"}), \
                patch("subprocess.run", side_effect=execute), \
                patch("time.sleep"), patch("time.monotonic", side_effect=range(0, 10000, 50)):
            try:
                runpy.run_path(str(SOURCE), run_name="__main__")
            except SystemExit as error:
                outcome = error.code
            except AssertionError:
                outcome = 1
            else:
                outcome = 0
        return outcome, sent

    def test_idle_clears_staged_ram_and_verifies_it(self):
        rc, sent = self.invoke("xnuloader\tfastboot\n", ramdisk="ready 400000 400000 300000000")
        self.assertEqual(rc, 0)
        self.assertIn(["fastboot", "-s", "xnuloader", "oem", "ramdisk", "none"], sent)

    def test_empty_android_serial_only_polls(self):
        rc, sent = self.invoke("\tfastboot\n")
        self.assertEqual(rc, 1)
        self.assertTrue(all(argv in (["fastboot", "devices"], ["adb", "devices"]) for argv in sent))

    def test_duplicate_loader_stops_before_queries(self):
        rc, sent = self.invoke("xnuloader\tfastboot\nxnuloader\tfastboot\n")
        self.assertEqual(rc, 1)
        self.assertEqual(sent, [["fastboot", "devices"]])

    def test_wrong_identity_is_not_changed(self):
        rc, sent = self.invoke("xnuloader\tfastboot\n", product="annibale")
        self.assertEqual(rc, 1)
        self.assertFalse(any("oem" in argv for argv in sent))

    def test_invalid_idle_or_ramdisk_state_cannot_pass(self):
        for kwargs in ({"result": "idle 1 0"}, {"result": "idle\nresult: running"},
                       {"ramdisk": "unknown"}, {"ramdisk": "idle 0 0 0 extra"}):
            with self.subTest(kwargs=kwargs):
                self.assertEqual(self.invoke("xnuloader\tfastboot\n", **kwargs)[0], 1)


if __name__ == "__main__":
    unittest.main()
