#!/usr/bin/env python3
"""覆盖手势统计的空样本、长间隔和验收边界。"""
import contextlib
import importlib.util
import io
from pathlib import Path
import tempfile
import unittest
from unittest import mock

spec = importlib.util.spec_from_file_location("gestures", Path(__file__).resolve().parent.parent / "gestures.py")
gestures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(gestures)


class PullReportTests(unittest.TestCase):
    def report(self, pulls, each=False):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            gestures.report_pulls(pulls, each)
        return output.getvalue()

    def assert_insufficient(self, output):
        self.assertIn("-> insufficient samples", output)
        self.assertNotIn("-> pass", output)
        self.assertNotIn("-> fail", output)

    def test_empty_pulls(self):
        output = self.report([])
        self.assert_insufficient(output)
        self.assertIn("pulls: 0, fps n/a", output)
        self.assertIn("median n/a", output)
        self.assertIn("longest interval n/a", output)

    def test_only_long_intervals_remain_visible(self):
        output = self.report([(3, 210, [90, 120])], each=True)
        self.assert_insufficient(output)
        self.assertIn("pull 1: 3 frames,  210 ms, 2 gap(s) >= 90 ms, n/a fps, longest   120 ms", output)
        self.assertIn("pulls: 1, fps n/a", output)
        self.assertIn("median n/a", output)
        self.assertIn("2 gaps >= 90 ms", output)
        self.assertIn("longest interval 120 ms", output)

    def test_long_intervals_are_reported_without_each(self):
        output = self.report([(4, 270, [90, 90, 90])])
        self.assert_insufficient(output)
        self.assertIn("3 gaps >= 90 ms", output)
        self.assertIn("longest interval 90 ms", output)

    def test_valid_pull_does_not_hide_a_pull_without_animation(self):
        output = self.report([(3, 32, [16, 16]), (3, 210, [90, 120])], each=True)
        self.assert_insufficient(output)
        self.assertIn("pulls: 2, fps 62.5 n/a", output)
        self.assertIn("at least 55: 1 of 2", output)
        self.assertIn("longest interval 120 ms", output)
        self.assertIn("pull 2:", output)

    def test_pull_without_intervals(self):
        output = self.report([(1, 0, [])], each=True)
        self.assert_insufficient(output)
        self.assertIn("n/a fps, longest n/a", output)
        self.assertIn("longest interval n/a", output)

    def test_one_interval_is_insufficient(self):
        output = self.report([(2, 16, [16])], each=True)
        self.assert_insufficient(output)
        self.assertIn("n/a fps, longest    16 ms", output)

    def test_valid_pull_does_not_hide_a_short_window(self):
        output = self.report([(3, 32, [16, 16]), (2, 16, [16])])
        self.assert_insufficient(output)
        self.assertIn("pulls: 2, fps 62.5 n/a", output)
        self.assertIn("at least 55: 1 of 2", output)

    def test_main_preserves_a_short_window_beside_a_valid_pull(self):
        with tempfile.TemporaryDirectory() as directory:
            lines = ["tl: p 1 1 32768 0 at 1000000", "tl: p 1 1 32768 0 at 4000000"]
            for index, done in enumerate((1010000, 1026000, 1042000, 4010000, 4026000)):
                lines.append(f"tl: v {index} ready {done} shown {done} done {done}")
            (Path(directory) / "s0.log").write_text("\n".join(lines) + "\n")
            output = io.StringIO()
            with mock.patch.object(gestures.sys, "argv", ["gestures.py", directory]), contextlib.redirect_stdout(output):
                gestures.main()
        self.assert_insufficient(output.getvalue())
        self.assertIn("pulls: 2, fps 62.5 n/a", output.getvalue())

    def test_zero_animation_duration(self):
        output = self.report([(3, 0, [0, 0])])
        self.assert_insufficient(output)
        self.assertIn("fps n/a", output)

    def test_existing_valid_pull_can_pass(self):
        output = self.report([(3, 32, [16, 16])], each=True)
        self.assertIn("62.5 fps", output)
        self.assertIn("at least 55: 1 of 1, median 62.5", output)
        self.assertIn("longest interval 16 ms", output)
        self.assertIn("-> pass", output)

    def test_long_interval_still_fails_despite_high_filtered_fps(self):
        output = self.report([(4, 152, [16, 120, 16])])
        self.assertIn("fps 62.5", output)
        self.assertIn("1 gaps >= 90 ms", output)
        self.assertIn("longest interval 120 ms", output)
        self.assertIn("-> fail", output)

    def test_pause_threshold_and_gap_target_are_unchanged(self):
        output = self.report([(4, 122, [16, 90, 16])])
        self.assertIn("fps 62.5", output)
        self.assertIn("1 gaps >= 90 ms", output)
        self.assertIn("longest interval 90 ms", output)
        self.assertIn("-> pass", output)

    def test_fps_and_median_targets_are_unchanged(self):
        for interval in (20, 1000 / 55.5):
            with self.subTest(interval=interval):
                output = self.report([(3, 2 * interval, [interval, interval])])
                self.assertIn("-> fail", output)


if __name__ == "__main__":
    unittest.main()
