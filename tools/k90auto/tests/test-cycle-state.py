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

    def test_missing_loader_records_stop_without_android_recovery(self):
        with tempfile.TemporaryDirectory() as directory, patch.object(cycle, "EVIDENCE", Path(directory)), \
                patch.object(cycle, "loader_ready", return_value="no xnuloader in fastboot devices"), \
                patch.object(cycle.subprocess, "run") as run, patch.object(sys, "argv", ["cycle.py", "test"]):
            self.assertEqual(cycle.main(), 1)
            run.assert_not_called()
            self.assertTrue((Path(directory) / "cycle-stop.json").is_file())

    def test_command_errors_and_timeouts_stop(self):
        devices = subprocess.CompletedProcess(["fastboot", "devices"], 0, "xnuloader\tfastboot\n", "")
        for failure in (OSError("missing client"), subprocess.TimeoutExpired(["fastboot"], 5)):
            for before_query in (False, True):
                with self.subTest(failure=type(failure).__name__, before_query=before_query):
                    replies = [devices, failure] if before_query else [failure]
                    with patch.object(cycle.subprocess, "run", side_effect=replies):
                        self.assertIsNotNone(cycle.loader_ready())


if __name__ == "__main__":
    unittest.main()
