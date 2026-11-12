#!/usr/bin/env python3
"""Offline command failures and AX freshness checks; K90_UI_SOURCE selects an older ui.py."""
import contextlib
import io
import os
from pathlib import Path
import runpy
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent.parent
SOURCE = Path(os.environ.get("K90_UI_SOURCE", HERE / "ui.py"))
sys.path.insert(0, str(HERE))

OLD = "# Demo pid 41 screen 100 200\n10 20 20 40\tUIButton\tOld\t\n"
CURRENT = "# Demo pid 42 screen 100 200\n10 20 20 40\tUIButton\tTarget\t\n"


class UICommandTests(unittest.TestCase):
    def test_usage_runs_without_screenshot_dependencies(self):
        result = subprocess.run([sys.executable, "-S", str(SOURCE)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        self.assertIn("usage:", result.stdout)
        self.assertEqual(result.stderr, "")

    def invoke(self, command, *, fail_at=None, missing_download=False, old=OLD):
        calls = []
        with tempfile.TemporaryDirectory() as directory:
            round_dir = Path(directory)
            ax = round_dir / "run" / "ax"
            ax.mkdir(parents=True)
            local = ax / "ax-Demo.txt"
            if old is not None:
                local.write_text(old)

            def run(argv, **kwargs):
                tool = Path(argv[1]).name
                words = tuple(map(str, argv[3:]))
                calls.append((tool, words))
                status = 2 if len(calls) == fail_at else 0
                output = ""
                if tool == "rsh.py":
                    if words == ("ls", "/private/var/tmp"):
                        output = "f 80 ax-Demo.txt\n"
                    elif words[0] not in ("rm", "notify", "/annibale/bin/anntouch"):
                        self.fail(f"unexpected rsh command: {words}")
                elif tool == "fetch.py":
                    if status == 0 and not missing_download:
                        Path(argv[-1]).write_text(CURRENT)
                else:
                    self.fail(f"unexpected tool: {tool}")
                result = subprocess.CompletedProcess(argv, status, output,
                                                     "transport failed\n" if status else "")
                if kwargs.get("check"):
                    result.check_returncode()
                return result

            output, errors = io.StringIO(), io.StringIO()
            with patch.object(sys, "argv", [str(SOURCE), str(round_dir), *command]), \
                    patch("subprocess.run", side_effect=run), patch("time.sleep"), \
                    patch.dict(sys.modules, {"tour": types.ModuleType("tour")}), \
                    contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                with self.assertRaises(SystemExit) as exited:
                    runpy.run_path(str(SOURCE), run_name="__main__")
            data = local.read_text() if local.exists() else None
            return exited.exception.code, output.getvalue(), errors.getvalue(), data, calls

    def test_fetch_failure_preserves_old_file_and_rejects_old_result(self):
        status, output, errors, data, calls = self.invoke(["dump"], fail_at=5)
        self.assertEqual(status, 1)
        self.assertNotIn("Old", output)
        self.assertIn("transport failed", errors)
        self.assertEqual(data, OLD)
        self.assertEqual(len(calls), 5)

    def test_fetch_failure_does_not_tap_old_target(self):
        status, output, errors, data, calls = self.invoke(["tap", "Old"], fail_at=5)
        self.assertEqual(status, 1)
        self.assertIn("transport failed", errors)
        self.assertEqual(data, OLD)
        self.assertEqual(len(calls), 5)

    def test_rsh_failures_stop_before_fetch_or_tap(self):
        for failed_step in (1, 2, 3, 4):
            with self.subTest(failed_step=failed_step):
                status, _, errors, data, calls = self.invoke(["tap", "Target"], fail_at=failed_step)
                self.assertEqual(status, 1)
                self.assertIn("transport failed", errors)
                self.assertEqual(data, OLD)
                self.assertEqual(len(calls), failed_step)

    def test_failed_tap_returns_failure(self):
        status, _, errors, data, calls = self.invoke(["tap", "Target"], fail_at=6)
        self.assertEqual(status, 1)
        self.assertIn("transport failed", errors)
        self.assertEqual(data, CURRENT)
        self.assertEqual(len(calls), 6)

    def test_accessibility_notify_failure_returns_failure(self):
        status, output, errors, _, calls = self.invoke(["accessibility"], fail_at=1)
        self.assertEqual(status, 1)
        self.assertNotIn("asked for", output)
        self.assertIn("transport failed", errors)
        self.assertEqual(len(calls), 1)

    def test_wait_stops_after_failed_query(self):
        status, _, errors, _, calls = self.invoke(["wait", "Old", "30"], fail_at=5)
        self.assertEqual(status, 1)
        self.assertIn("transport failed", errors)
        self.assertEqual(len(calls), 5)

    def test_successful_dump_uses_new_download(self):
        status, output, errors, data, calls = self.invoke(["dump"])
        self.assertEqual(status, 0)
        self.assertIn("Target", output)
        self.assertNotIn("Old", output)
        self.assertEqual(errors, "")
        self.assertEqual(data, CURRENT)
        self.assertEqual(calls[:4], [
            ("rsh.py", ("ls", "/private/var/tmp")),
            ("rsh.py", ("rm", "/private/var/tmp/ax-Demo.txt")),
            ("rsh.py", ("notify", "com.annibale.ax")),
            ("rsh.py", ("ls", "/private/var/tmp")),
        ])

    def test_successful_tap_uses_current_coordinates(self):
        status, output, errors, data, calls = self.invoke(["tap", "Target", "--exact"])
        self.assertEqual(status, 0)
        self.assertIn("'Target'", output)
        self.assertEqual(errors, "")
        self.assertEqual(data, CURRENT)
        self.assertEqual(calls[-1], ("rsh.py", ("/annibale/bin/anntouch", "tap", "0.2000", "0.2000")))

    def test_missing_download_is_reported(self):
        status, _, errors, data, calls = self.invoke(["dump"], old=None, missing_download=True)
        self.assertEqual(status, 1)
        self.assertIn("ax-Demo.txt", errors)
        self.assertIsNone(data)
        self.assertEqual(len(calls), 5)


if __name__ == "__main__":
    unittest.main()
