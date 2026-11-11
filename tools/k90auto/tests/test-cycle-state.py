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

    def test_shared_recovery_is_followed_by_independent_state_checks(self):
        sent = []

        def run(argv, **kwargs):
            sent.append([str(x) for x in argv])
            self.assertTrue(str(argv[1]).endswith("recover-loader.py"))
            return subprocess.CompletedProcess(argv, 0, "recovered\n", "")

        with tempfile.TemporaryDirectory() as directory, \
                patch.object(cycle, "EVIDENCE", Path(directory)), \
                patch.object(cycle.subprocess, "run", side_effect=run), \
                patch.object(cycle, "loader_ready", return_value=None) as ready:
            self.assertIsNone(cycle.ensure_loader_idle())
            ready.assert_called_once()
        self.assertEqual(len(sent), 1)

    def test_successful_recovery_does_not_accept_invalid_final_state(self):
        recovered = subprocess.CompletedProcess([], 0, "recovered\n", "")
        for failure in ("no xnuloader in fastboot devices", "loader result is not idle",
                        "loader RAM disk is not empty", "loader product is not xnuloader"):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory, \
                    patch.object(cycle, "EVIDENCE", Path(directory)), \
                    patch.object(cycle.subprocess, "run", return_value=recovered), \
                    patch.object(cycle, "loader_ready", return_value=failure):
                self.assertEqual(cycle.ensure_loader_idle(), failure)

    def test_recovery_failure_stops_before_further_device_queries(self):
        failed = subprocess.CompletedProcess([], 1, "", "stop failed")
        with tempfile.TemporaryDirectory() as directory, \
                patch.object(cycle, "EVIDENCE", Path(directory)), \
                patch.object(cycle.subprocess, "run", return_value=failed) as run, \
                patch.object(cycle, "loader_ready") as ready:
            self.assertIsNotNone(cycle.ensure_loader_idle())
            ready.assert_not_called()
            run.assert_called_once()
            self.assertTrue(str(run.call_args.args[0][1]).endswith("recover-loader.py"))

    def test_recovery_exception_is_recorded(self):
        for error in (OSError("missing client"), subprocess.TimeoutExpired(["python3"], 180)):
            with self.subTest(error=type(error).__name__), tempfile.TemporaryDirectory() as directory, \
                    patch.object(cycle, "EVIDENCE", Path(directory)), \
                    patch.object(cycle.subprocess, "run", side_effect=error), \
                    patch.object(cycle, "loader_ready") as ready:
                self.assertIsNotNone(cycle.ensure_loader_idle())
                self.assertTrue((Path(directory) / "cycle-recovery.json").is_file())
                ready.assert_not_called()

    def test_checkpoint_uses_shared_native_recovery_after_verified_lk(self):
        with patch.dict(cycle.os.environ, {"ANDROID_SERIAL": "test-device"}), \
                patch.object(cycle, "run", return_value=subprocess.CompletedProcess([], 0)) as run, \
                patch.object(cycle, "ensure_loader_idle", return_value=None) as recover:
            self.assertIsNone(cycle.checkpoint())
            self.assertTrue(str(run.call_args.args[0][1]).endswith("reboot-lk.py"))
            recover.assert_called_once()

    def test_checkpoint_failure_never_attempts_slot_selection(self):
        with patch.dict(cycle.os.environ, {"ANDROID_SERIAL": "test-device"}), \
                patch.object(cycle, "run", return_value=subprocess.CompletedProcess([], 1)), \
                patch.object(cycle, "ensure_loader_idle") as recover:
            self.assertIsNotNone(cycle.checkpoint())
            recover.assert_not_called()

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
