#!/usr/bin/env python3
"""Verify that a failed tour step cannot execute later device actions."""
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


SOURCE = Path(sys.argv.pop(1)) if len(sys.argv) > 1 else Path(__file__).parents[1] / "tour.py"
spec = importlib.util.spec_from_file_location("tour_under_test", SOURCE)
tour = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tour)


class TourFailures(unittest.TestCase):
    def exercise(self, steps, command_results, shot_results, old_entries=None):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            run = base / "run"
            run.mkdir()
            if old_entries is not None:
                (run / "tour.json").write_text(json.dumps(old_entries))
            shots = [run / name if name else None for name in shot_results]
            output = io.StringIO()
            with patch.object(sys, "argv", [str(SOURCE), str(base), *steps]), \
                 patch.object(tour.subprocess, "run", side_effect=command_results) as commands, \
                 patch.object(tour, "take_shot", side_effect=shots) as capture, \
                 patch.object(tour.time, "sleep") as sleep, \
                 patch.object(tour, "sheet") as sheet, \
                 patch.object(tour, "compare", return_value=(.1, [1, 2, 3, 4])), \
                 contextlib.redirect_stdout(output):
                status = tour.main()
            return (status, json.loads((run / "tour.json").read_text()),
                    commands.call_args_list, capture.call_count, sleep.call_count,
                    sheet.call_args_list, output.getvalue())

    @staticmethod
    def completed(code):
        return subprocess.CompletedProcess([], code, "command output", "command error")

    def test_command_failure_stops_before_screenshot_and_next_action(self):
        for code in (1, 2, 3):
            with self.subTest(code=code):
                result = self.exercise(["first=first@0", "later=later@0"],
                                       [self.completed(code), self.completed(0)], ["later.raw"])
                status, entries, commands, shots, sleeps, sheets, output = result
                self.assertEqual((status, entries, len(commands), shots, sleeps, len(sheets)),
                                 (1, [], 1, 0, 0, 0))
                self.assertIn(f"first: command exited {code}", output)

    def test_prior_entries_survive_command_failure(self):
        previous = [{"label": "old", "shot": "old.raw", "command": ""}]
        status, entries, commands, shots, _, sheets, _ = self.exercise(
            ["first=first@0", "failed=bad@0", "later=later@0"],
            [self.completed(0), self.completed(1), self.completed(0)],
            ["first.raw", "unexpected.raw"], previous)
        self.assertEqual((status, len(commands), shots), (1, 2, 1))
        self.assertEqual([entry["label"] for entry in entries], ["old", "first"])
        self.assertEqual(sheets[0].args[1], entries)

    def test_timeout_preserves_prior_capture_and_stops(self):
        status, entries, commands, shots, _, _, output = self.exercise(
            ["first=first@0", "failed=bad@0", "later=later@0"],
            [self.completed(0), subprocess.TimeoutExpired(["rsh.py"], 90), self.completed(0)],
            ["first.raw", "unexpected.raw"])
        self.assertEqual((status, len(commands), shots), (1, 2, 1))
        self.assertEqual([entry["label"] for entry in entries], ["first"])
        self.assertIn("device-side completion is unknown", output)

    def test_missing_screenshot_preserves_received_shots(self):
        status, entries, commands, shots, _, sheets, output = self.exercise(
            ["first=first@0*3", "later=later@0"], [self.completed(0), self.completed(0)],
            ["first.raw", None, "unexpected.raw"])
        self.assertEqual((status, len(commands), shots), (1, 1, 2))
        self.assertEqual([entry["shot"] for entry in entries], ["first.raw"])
        self.assertEqual(sheets[0].args[1], entries)
        self.assertIn("first: no screenshot came back", output)

    def test_command_launch_error_preserves_prior_capture(self):
        status, entries, commands, shots, _, _, output = self.exercise(
            ["first@0", "failed=bad@0", "later=later@0"],
            [OSError("unable to spawn"), self.completed(0)], ["first.raw", "unexpected.raw"])
        self.assertEqual((status, len(commands), shots), (1, 1, 1))
        self.assertEqual([entry["label"] for entry in entries], ["first"])
        self.assertIn("failed: could not start command", output)

    def test_missing_first_screenshot_stops_later_action(self):
        status, entries, commands, shots, _, sheets, _ = self.exercise(
            ["baseline@0", "later=later@0"], [self.completed(0)], [None, "unexpected.raw"])
        self.assertEqual((status, entries, len(commands), shots, len(sheets)), (1, [], 0, 1, 0))

    def test_success_runs_all_steps_and_retains_comparisons(self):
        status, entries, commands, shots, sleeps, sheets, _ = self.exercise(
            ["first=first@0*2", "last=last@0"], [self.completed(0), self.completed(0)],
            ["one.raw", "two.raw", "three.raw"])
        self.assertEqual((status, len(commands), shots, sleeps, len(sheets)), (0, 2, 3, 2, 1))
        self.assertEqual([entry["label"] for entry in entries], ["first-1", "first-2", "last"])
        self.assertEqual(entries[1]["changed_share"], .1)
        self.assertEqual(commands[1].args[0][-1], "last")


if __name__ == "__main__":
    unittest.main()
