#!/usr/bin/env python3
"""Offline tests for the structured rsh state collector."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("ios_state", HERE / "ios-state.py")
ios_state = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ios_state)


class StateCollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.round_dir = Path(self.temp.name)
        (self.round_dir / "run").mkdir()

    def tearDown(self):
        self.temp.cleanup()

    def test_collects_default_and_requested_read_only_state(self):
        calls = []

        def answer(argv, capture_output, text):
            calls.append(argv)
            words = argv[3:]
            return subprocess.CompletedProcess(argv, 1 if words[0] == "ls" else 0,
                                               "output for " + " ".join(words), "rsh: exit 0 after 1 ms")

        output = self.round_dir / "run" / "state.json"
        with mock.patch.object(ios_state.subprocess, "run", side_effect=answer):
            report, destination = ios_state.collect(
                self.round_dir, extra_ls=("/tmp/custom",), sysctls=("kern.annibale.prof",),
                thread_pids=(17,), output=output)

        self.assertEqual(report["status"], "complete")
        self.assertEqual(destination, output)
        self.assertEqual(len(report["commands"]), 9)
        self.assertEqual(calls[0][3:], ["ps"])
        self.assertIn("/annibale/bin/trollstorehelper", calls[1])
        self.assertEqual(calls[-2][3:], ["threads", "17"])
        self.assertEqual(calls[-1][3:], ["dump", "17"])
        self.assertTrue(all(Path(call[1]).name == "rsh.py" for call in calls))
        self.assertTrue(all("fastboot" not in call for call in calls))
        saved = json.loads(output.read_text())
        self.assertEqual(saved["commands"][0]["stdout"], "output for ps")
        self.assertEqual(saved["commands"][2]["exit"], 1)

    def test_transport_failure_stops_later_queries_and_saves_report(self):
        calls = []

        def answer(argv, capture_output, text):
            calls.append(argv)
            code = 2 if len(calls) == 2 else 0
            return subprocess.CompletedProcess(argv, code, "", "rsh: transport failure")

        with mock.patch.object(ios_state.subprocess, "run", side_effect=answer):
            report, destination = ios_state.collect(
                self.round_dir, extra_ls=("/tmp/not-sent",),
                output=self.round_dir / "run" / "failed.json")

        self.assertEqual(report["status"], "transport_failed")
        self.assertEqual(report["failed_command"], "installed_apps")
        self.assertEqual(len(calls), 2)
        self.assertEqual(len(report["commands"]), 2)
        self.assertTrue(destination.is_file())

    def test_finished_round_is_rejected_without_calling_rsh(self):
        (self.round_dir / "run" / "reboot.json").write_text("{}")
        with mock.patch.object(ios_state.subprocess, "run") as run:
            with self.assertRaises(RuntimeError):
                ios_state.collect(self.round_dir)
        run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
