#!/usr/bin/env python3
"""Check cycle startup against complete fastboot replies without a device."""
import importlib.util
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

SOURCE = Path(__file__).resolve().parents[1] / "cycle.py"
spec = importlib.util.spec_from_file_location("cycle", SOURCE)
cycle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cycle)


class LoaderStateTests(unittest.TestCase):
    def check_state(self, **overrides):
        replies = {"devices": "xnuloader\tfastboot\n", "product": "xnuloader",
                   "result": "idle", "ramdisk-state": "idle 0 0 0"}
        replies.update(overrides)
        calls = []

        def run(argv, **kwargs):
            calls.append(argv)
            key = "devices" if argv == ["fastboot", "devices"] else argv[-1]
            self.assertTrue(argv == ["fastboot", "devices"] or
                            argv[:4] == ["fastboot", "-s", "xnuloader", "getvar"])
            value = replies[key]
            output = value if key == "devices" else f"(bootloader) {key}: {value}\nFinished. Total time: 0.003s\n"
            return subprocess.CompletedProcess(argv, overrides.get("rc", 0), output, "")

        with patch.object(cycle.subprocess, "run", side_effect=run):
            result = cycle.loader_ready()
        return result, calls

    def test_valid_idle_forms_and_unallocated_window(self):
        for state in ("idle", "idle 0 0"):
            for window in ("0", "300000000"):
                with self.subTest(state=state, window=window):
                    self.assertIsNone(self.check_state(**{"result": state, "ramdisk-state": "idle 0 0 " + window})[0])

    def test_missing_exact_serial_stops_before_queries(self):
        for devices in ("", "\tfastboot\n", "xnuloader-other\tfastboot\n", "xnuloader\tfastboot\nxnuloader\tfastboot\n"):
            with self.subTest(devices=devices):
                result, calls = self.check_state(devices=devices)
                self.assertIsNotNone(result)
                self.assertEqual(calls, [["fastboot", "devices"]])

    def test_nonzero_fields_duplicate_responses_and_failure_stop(self):
        for config in ({"result": "idle 1 0"}, {"result": "idle 0 1"},
                       {"result": "idle 0 0 0"}, {"result": "idle\nresult: running"},
                       {"result": "idle\nFAILED (remote: query failed)"},
                       {"ramdisk-state": "ready 400000 400000 300000000"},
                       {"ramdisk-state": "idle 0 0 0 extra"}, {"product": "annibale"}, {"rc": 1}):
            with self.subTest(config=config):
                self.assertIsNotNone(self.check_state(**config)[0])

    def test_running_session_stops_reboots_and_locks_fastboot_idle(self):
        state = {"result": "running 0 0", "ramdisk-state": "ready 400000 400000 300000000", "off": False}
        sent = []

        def fake_run(argv, **kwargs):
            sent.append(list(argv))
            if argv == ["fastboot", "devices"]:
                if state["off"]:
                    state["off"] = False
                    return subprocess.CompletedProcess(argv, 0, "", "")
                return subprocess.CompletedProcess(argv, 0, "xnuloader\tfastboot\n", "")
            if argv == ["adb", "devices"]:
                return subprocess.CompletedProcess(argv, 0, "List of devices attached\n\n", "")
            if argv[:4] == ["fastboot", "-s", "xnuloader", "getvar"]:
                key = argv[4]
                val = "xnuloader" if key == "product" else state[key]
                return subprocess.CompletedProcess(argv, 0, f"(bootloader) {key}: {val}\nFinished.\n", "")
            if argv == ["fastboot", "-s", "xnuloader", "oem", "stop"]:
                state["result"] = "hung-held"
                return subprocess.CompletedProcess(argv, 0, "OKAY\n", "")
            if argv == ["fastboot", "-s", "xnuloader", "reboot"]:
                state["off"] = True
                state["result"] = "idle"
                state["ramdisk-state"] = "idle 0 0 0"
                return subprocess.CompletedProcess(argv, 0, "OKAY\n", "")
            if argv == ["fastboot", "-s", "xnuloader", "oem", "recovery"]:
                return subprocess.CompletedProcess(argv, 0, "OKAY\n", "")
            if argv == ["fastboot", "-s", "xnuloader", "oem", "ramdisk", "none"]:
                state["ramdisk-state"] = "idle 0 0 0"
                return subprocess.CompletedProcess(argv, 0, "OKAY\n", "")
            raise AssertionError(f"unexpected command: {argv}")

        with patch.object(cycle.subprocess, "run", side_effect=fake_run), \
                patch.object(cycle.time, "sleep"):
            self.assertIsNone(cycle.ensure_loader_idle())
        self.assertIn(["fastboot", "-s", "xnuloader", "oem", "stop"], sent)
        self.assertIn(["fastboot", "-s", "xnuloader", "reboot"], sent)
        self.assertIn(["fastboot", "-s", "xnuloader", "oem", "recovery"], sent)

    def test_idle_with_staged_ramdisk_clears_ramdisk_in_place(self):
        state = {"result": "idle", "ramdisk-state": "ready 400000 400000 300000000"}
        sent = []

        def fake_run(argv, **kwargs):
            sent.append(list(argv))
            if argv == ["fastboot", "devices"]:
                return subprocess.CompletedProcess(argv, 0, "xnuloader\tfastboot\n", "")
            if argv == ["adb", "devices"]:
                return subprocess.CompletedProcess(argv, 0, "List of devices attached\n\n", "")
            if argv[:4] == ["fastboot", "-s", "xnuloader", "getvar"]:
                key = argv[4]
                val = "xnuloader" if key == "product" else state[key]
                return subprocess.CompletedProcess(argv, 0, f"(bootloader) {key}: {val}\nFinished.\n", "")
            if argv == ["fastboot", "-s", "xnuloader", "oem", "recovery"]:
                return subprocess.CompletedProcess(argv, 0, "OKAY\n", "")
            if argv == ["fastboot", "-s", "xnuloader", "oem", "ramdisk", "none"]:
                state["ramdisk-state"] = "idle 0 0 300000000"
                return subprocess.CompletedProcess(argv, 0, "OKAY\n", "")
            raise AssertionError(f"unexpected command: {argv}")

        with patch.object(cycle.subprocess, "run", side_effect=fake_run):
            self.assertIsNone(cycle.ensure_loader_idle())
        self.assertIn(["fastboot", "-s", "xnuloader", "oem", "ramdisk", "none"], sent)

    def test_unenumerated_loader_invokes_recover_loader(self):
        state = {"enumerated": False}
        sent = []

        def fake_run(argv, **kwargs):
            argv = [str(x) for x in argv]
            sent.append(argv)
            if argv == ["fastboot", "devices"]:
                out = "xnuloader\tfastboot\n" if state["enumerated"] else ""
                return subprocess.CompletedProcess(argv, 0, out, "")
            if len(argv) >= 2 and argv[1].endswith("recover-loader.py"):
                state["enumerated"] = True
                return subprocess.CompletedProcess(argv, 0, "recovered\n", "")
            if argv == ["adb", "devices"]:
                return subprocess.CompletedProcess(argv, 0, "List of devices attached\n\n", "")
            if argv[:4] == ["fastboot", "-s", "xnuloader", "getvar"]:
                key = argv[4]
                vals = {"product": "xnuloader", "result": "idle", "ramdisk-state": "idle 0 0 0"}
                return subprocess.CompletedProcess(argv, 0, f"(bootloader) {key}: {vals[key]}\nFinished.\n", "")
            if argv == ["fastboot", "-s", "xnuloader", "oem", "recovery"]:
                return subprocess.CompletedProcess(argv, 0, "OKAY\n", "")
            raise AssertionError(f"unexpected command: {argv}")

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(cycle, "EVIDENCE", Path(directory)), \
                patch.object(cycle.subprocess, "run", side_effect=fake_run):
            self.assertIsNone(cycle.ensure_loader_idle())
        self.assertTrue(any(len(cmd) >= 2 and cmd[1].endswith("recover-loader.py") for cmd in sent))

    def test_command_errors_and_timeouts_stop(self):
        devices = subprocess.CompletedProcess(["fastboot", "devices"], 0, "xnuloader\tfastboot\n", "")
        for failure in (OSError("missing client"), subprocess.TimeoutExpired(["fastboot"], 5)):
            for before_query in (False, True):
                with self.subTest(failure=type(failure).__name__, before_query=before_query):
                    replies = [devices, failure] if before_query else [failure]
                    with patch.object(cycle.subprocess, "run", side_effect=replies):
                        self.assertIsNotNone(cycle.loader_ready())

    def test_slot_budget_resets_only_below_three_and_rejects_missing_reading(self):
        for reading in ("3", "5", "6", "7"):
            with patch.object(cycle, "loader_var", return_value=reading), patch.object(cycle, "checkpoint") as reset:
                self.assertIsNone(cycle.slot_preflight())
                reset.assert_not_called()
        for reading in ("0", "1", "2"):
            with patch.object(cycle, "loader_var", return_value=reading), \
                    patch.object(cycle, "checkpoint", return_value=None) as reset:
                self.assertIsNone(cycle.slot_preflight())
                reset.assert_called_once()
        for reading in ("", "8", "-1", "7\nslot-retry-count:a: 0"):
            with patch.object(cycle, "loader_var", return_value=reading), patch.object(cycle, "checkpoint") as reset:
                self.assertIsNotNone(cycle.slot_preflight())
                reset.assert_not_called()

    def test_failed_stop_does_not_send_reboot_or_clear_ram(self):
        sent = []

        def run(argv, **kwargs):
            sent.append(argv)
            if argv == ["fastboot", "devices"]:
                return subprocess.CompletedProcess(argv, 0, "xnuloader\tfastboot\n", "")
            if argv[:4] == ["fastboot", "-s", "xnuloader", "getvar"]:
                value = "xnuloader" if argv[-1] == "product" else "running 0 0"
                return subprocess.CompletedProcess(argv, 0, f"{argv[-1]}: {value}\n", "")
            if argv == ["fastboot", "-s", "xnuloader", "oem", "stop"]:
                return subprocess.CompletedProcess(argv, 0, "FAILED (remote: refused)\n", "")
            self.fail(f"Unexpected command after failed stop: {argv}")

        with tempfile.TemporaryDirectory() as directory, patch.object(cycle, "EVIDENCE", Path(directory)), \
                patch.object(cycle.subprocess, "run", side_effect=run):
            self.assertIsNotNone(cycle.ensure_loader_idle())
            self.assertTrue((Path(directory) / "cycle-recovery.json").is_file())
        self.assertEqual(sent[-1], ["fastboot", "-s", "xnuloader", "oem", "stop"])

    def test_fastboot_requires_valid_and_enumerated_serial(self):
        for serial in ("", " ", "test serial"):
            with self.subTest(serial=serial), patch.object(cycle.subprocess, "run") as run:
                with self.assertRaises(RuntimeError):
                    cycle.fastboot("reboot", serial=serial)
                run.assert_not_called()
        enumeration = subprocess.CompletedProcess(["fastboot", "devices"], 0, "\tfastboot\n", "")
        with patch.object(cycle.subprocess, "run", return_value=enumeration) as run:
            with self.assertRaises(RuntimeError):
                cycle.fastboot("reboot")
            run.assert_called_once_with(["fastboot", "devices"], capture_output=True, text=True, timeout=5)


if __name__ == "__main__":
    unittest.main()
