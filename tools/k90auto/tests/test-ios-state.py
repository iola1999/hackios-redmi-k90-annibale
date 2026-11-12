#!/usr/bin/env python3
"""Offline tests for the structured rsh state collector."""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent.parent
SOURCE = Path(os.environ.get("K90_IOS_STATE_SOURCE", HERE / "ios-state.py"))
spec = importlib.util.spec_from_file_location("ios_state", SOURCE)
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
                self.round_dir, ("/tmp/custom",), ("kern.annibale.prof",), (17,), output)

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

    def test_main_keeps_default_queries_unchanged(self):
        output = self.round_dir / "run" / "defaults.json"
        with mock.patch.object(ios_state.subprocess, "run", return_value=
                               subprocess.CompletedProcess([], 0, "", "")) as run:
            code = ios_state.main([str(self.round_dir), "--output", str(output)])

        self.assertEqual(code, 0)
        self.assertEqual([call.args[0][3:] for call in run.call_args_list], [
            ["ps"], ["/annibale/bin/trollstorehelper", "list"],
            ["ls", "/Applications"], ["ls", "/private/var/mobile/Library/Downloads"],
            ["ls", "/private/var/tmp/ipa"],
        ])
        self.assertEqual(json.loads(output.read_text())["status"], "complete")

    def test_main_routes_requested_queries_in_existing_order_then_processes(self):
        output = self.round_dir / "run" / "requested.json"
        with mock.patch.object(ios_state.subprocess, "run", return_value=
                               subprocess.CompletedProcess([], 0, "process state", "")) as run:
            code = ios_state.main([
                str(self.round_dir), "--process", "31", "--ls", "/tmp/custom",
                "--sysctl", "kern.annibale.prof", "--threads", "17",
                "--process", "32", "--output", str(output),
            ])

        self.assertEqual(code, 0)
        commands = [call.args[0][3:] for call in run.call_args_list]
        self.assertEqual(len(commands), 11)
        self.assertEqual(commands[5:], [
            ["ls", "/tmp/custom"], ["sysctl", "kern.annibale.prof"],
            ["threads", "17"], ["dump", "17"], ["process", "31"], ["process", "32"],
        ])
        self.assertTrue(all(call.args[0][:3] == [ios_state.sys.executable,
                            str(ios_state.HERE / "rsh.py"), str(self.round_dir)]
                            for call in run.call_args_list))
        saved = json.loads(output.read_text())
        self.assertEqual(saved["commands"][-1]["name"], "process:32")
        self.assertEqual(saved["commands"][-1]["stdout"], "process state")

    def test_process_query_failure_is_saved_and_later_process_is_queried(self):
        def answer(argv, capture_output, text):
            if argv[3:] == ["process", "31"]:
                return subprocess.CompletedProcess(argv, 1, "partial state", "process: no such process")
            return subprocess.CompletedProcess(argv, 0, "ok", "")

        output = self.round_dir / "run" / "query-failed.json"
        with mock.patch.object(ios_state.subprocess, "run", side_effect=answer) as run:
            code = ios_state.main([str(self.round_dir), "--process", "31", "--process", "32",
                                   "--output", str(output)])

        self.assertEqual(code, 0)
        self.assertEqual(run.call_args.args[0][3:], ["process", "32"])
        saved = json.loads(output.read_text())
        self.assertEqual(saved["status"], "complete")
        self.assertEqual(saved["commands"][-2], {
            "name": "process:31", "command": ["process", "31"], "exit": 1,
            "stdout": "partial state", "stderr": "process: no such process",
        })
        self.assertEqual(saved["commands"][-1]["exit"], 0)

    def test_process_transport_failure_stops_later_process_queries(self):
        for failure in (2, 3):
            with self.subTest(returncode=failure):
                def answer(argv, capture_output, text):
                    code = failure if argv[3:] == ["process", "31"] else 0
                    return subprocess.CompletedProcess(argv, code, "partial", "transport unavailable")

                output = self.round_dir / "run" / f"transport-{failure}.json"
                with mock.patch.object(ios_state.subprocess, "run", side_effect=answer) as run:
                    code = ios_state.main([str(self.round_dir), "--process", "31", "--process", "32",
                                           "--output", str(output)])

                self.assertEqual(code, 2)
                self.assertEqual(run.call_count, 6)
                self.assertEqual(run.call_args.args[0][3:], ["process", "31"])
                saved = json.loads(output.read_text())
                self.assertEqual(saved["status"], "transport_failed")
                self.assertEqual(saved["failed_command"], "process:31")
                self.assertEqual(saved["commands"][-1]["exit"], failure)
                self.assertEqual(saved["commands"][-1]["stdout"], "partial")
                self.assertEqual(saved["commands"][-1]["stderr"], "transport unavailable")

    def test_main_rejects_invalid_process_pid_before_requests(self):
        for pid in ("0", "-1", "abc", "2147483648"):
            with self.subTest(pid=pid):
                with mock.patch.object(ios_state.subprocess, "run") as run:
                    with self.assertRaises(SystemExit) as error:
                        ios_state.main([str(self.round_dir), "--process", pid])
                self.assertEqual(error.exception.code, 2)
                run.assert_not_called()


if __name__ == "__main__":
    unittest.main()
