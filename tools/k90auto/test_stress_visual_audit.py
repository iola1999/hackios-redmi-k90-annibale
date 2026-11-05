#!/usr/bin/env python3
"""Adversarial stress testing and empirical accuracy verification for tools/k90auto/visual-audit.py.

Evaluates edge/corner cases, error handling, exit codes, and real frame false-positive/negative rates.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
PROJECT_ROOT = HERE.parent.parent
sys.path.insert(0, str(HERE))

import importlib.util
spec = importlib.util.spec_from_file_location("visual_audit", str(HERE / "visual-audit.py"))
va = importlib.util.module_from_spec(spec)
spec.loader.exec_module(va)


class TestStressVisualAudit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scratch_dir = Path(tempfile.mkdtemp(prefix="k90auto_challenger_"))
        cls.evidence_dir = PROJECT_ROOT / "docs/progress/evidence/k90auto/kernel-12377-st4-r2/run"

    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(cls.scratch_dir, ignore_errors=True)

    # -------------------------------------------------------------------------
    # 1. Edge & Corner Cases: Dimensions & Solid Color Fill
    # -------------------------------------------------------------------------
    def test_edge_case_1x1_image(self):
        """1x1 image should not crash, should report PASS (no defects)."""
        p = self.scratch_dir / "edge_1x1.png"
        Image.new("RGB", (1, 1), (0, 0, 0)).save(p)
        res = va.audit_screenshot(p)
        self.assertFalse(res["defect_detected"])
        self.assertEqual(len(res["pure_black_blocks"]), 0)
        self.assertEqual(len(res["bar_punch_through"]), 0)

    def test_edge_case_pure_white(self):
        """1156x2510 pure white image should report PASS."""
        p = self.scratch_dir / "pure_white.png"
        Image.new("RGB", (1156, 2510), (255, 255, 255)).save(p)
        res = va.audit_screenshot(p)
        self.assertFalse(res["defect_detected"])
        self.assertEqual(len(res["pure_black_blocks"]), 0)

    def test_edge_case_pure_black(self):
        """1156x2510 pure black image should report pure_black_block defect."""
        p = self.scratch_dir / "pure_black.png"
        Image.new("RGB", (1156, 2510), (0, 0, 0)).save(p)
        res = va.audit_screenshot(p)
        self.assertTrue(res["defect_detected"])
        self.assertGreaterEqual(len(res["pure_black_blocks"]), 1)
        blk = res["pure_black_blocks"][0]
        self.assertGreaterEqual(blk["width"], 1000)
        self.assertGreaterEqual(blk["height"], 2000)
        self.assertGreaterEqual(blk["black_ratio"], 0.99)

    def test_edge_case_nonstandard_dimensions(self):
        """Images with non-standard dimensions must be processed without unhandled exceptions."""
        dims = [(10, 10), (100, 100), (1156, 100), (100, 2510), (2000, 2000)]
        for w, h in dims:
            p = self.scratch_dir / f"dim_{w}x{h}.png"
            Image.new("RGB", (w, h), (128, 128, 128)).save(p)
            res = va.audit_screenshot(p)
            self.assertFalse(res["defect_detected"], f"Unexpected defect for gray {w}x{h}")
            self.assertEqual(res["width"], w)
            self.assertEqual(res["height"], h)

    # -------------------------------------------------------------------------
    # 2. Corrupt / Truncated / Missing Files and Exit Codes
    # -------------------------------------------------------------------------
    def test_corrupt_truncated_raw_exit_code(self):
        """Truncated or corrupted raw files must exit with non-zero exit code."""
        bad_files = [
            ("empty.raw", b""),
            ("truncated_100.raw", b"X" * 100),
            ("half_raw.raw", b"\x00" * (1156 * 2510 * 2)),
            ("empty.png", b""),
            ("corrupt.png", b"INVALID_HEADER_GARBAGE"),
        ]
        for name, data in bad_files:
            p = self.scratch_dir / name
            p.write_bytes(data)
            cmd = [sys.executable, str(HERE / "visual-audit.py"), str(p)]
            proc = subprocess.run(cmd, capture_output=True, text=True)
            self.assertNotEqual(proc.returncode, 0, f"Expected non-zero exit code for {name}, got {proc.returncode}")

    def test_missing_file_exit_code(self):
        """Non-existent file (e.g. shot-00001.raw) must exit with code 1 and FileNotFoundError."""
        cmd = [sys.executable, str(HERE / "visual-audit.py"), str(self.scratch_dir / "shot-00001.raw")]
        proc = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(proc.returncode, 1)
        self.assertIn("FileNotFoundError", proc.stderr)

    # -------------------------------------------------------------------------
    # 3. Empirical Accuracy & False-Positive / False-Negative Verification on Real Frames
    # -------------------------------------------------------------------------
    def test_real_frame_shot_00321_widget_black_defect(self):
        """shot-00321.raw must detect both weather and calendar widget black blocks."""
        p = self.evidence_dir / "shot-00321.raw"
        if not p.exists():
            self.skipTest(f"{p} not found")

        res = va.audit_screenshot(p)
        self.assertTrue(res["defect_detected"])
        blocks = res["pure_black_blocks"]
        self.assertGreaterEqual(len(blocks), 2, f"Expected at least 2 widget black blocks, got {len(blocks)}")

        # Verify coordinates of weather widget (left, x~80) and calendar widget (right, x~624)
        boxes = [b["box"] for b in blocks]
        has_weather = any(abs(b[0] - 80) <= 40 and 200 <= b[1] <= 300 for b in boxes)
        has_calendar = any(abs(b[0] - 624) <= 40 and 200 <= b[1] <= 300 for b in boxes)
        self.assertTrue(has_weather, f"Weather widget black block missing in {boxes}")
        self.assertTrue(has_calendar, f"Calendar widget black block missing in {boxes}")

        # Check false positive: no bar punch-through defect should be detected on desktop home
        self.assertEqual(len(res["bar_punch_through"]), 0, "No bar punch-through should be flagged on desktop home")

    def test_real_frame_shot_00604_clean_settings_pass(self):
        """shot-00604.raw (unscrolled clean Settings) must PASS with zero defects (no false positives)."""
        p = self.evidence_dir / "shot-00604.raw"
        if not p.exists():
            self.skipTest(f"{p} not found")

        res = va.audit_screenshot(p)
        self.assertFalse(res["defect_detected"], f"Clean Settings shot-00604 flagged with false positive: {res}")
        self.assertEqual(len(res["pure_black_blocks"]), 0)
        self.assertEqual(len(res["bar_punch_through"]), 0)

    def test_real_frame_shot_00614_clean_settings_pass(self):
        """shot-00614.raw (second clean Settings frame) must PASS with zero defects."""
        p = self.evidence_dir / "shot-00614.raw"
        if not p.exists():
            self.skipTest(f"{p} not found")

        res = va.audit_screenshot(p, baseline_path=str(self.evidence_dir / "shot-00604.raw"))
        self.assertFalse(res["defect_detected"], f"Clean Settings shot-00614 flagged with false positive: {res}")

    def test_real_frame_shot_00838_scrolled_settings_punch_through(self):
        """shot-00838.raw (scrolled Settings) must detect top navigation bar punch-through."""
        p = self.evidence_dir / "shot-00838.raw"
        baseline = self.evidence_dir / "shot-00604.raw"
        if not p.exists() or not baseline.exists():
            self.skipTest("Required shots not found")

        res = va.audit_screenshot(p, baseline_path=str(baseline))
        self.assertTrue(res["defect_detected"], "Failed to detect punch-through defect on shot-00838")
        pts = res["bar_punch_through"]
        self.assertGreaterEqual(len(pts), 1)

        top_pts = [pt for pt in pts if pt["bar"] == "top_bar"]
        self.assertEqual(len(top_pts), 1)
        pt = top_pts[0]
        self.assertTrue(pt["double_text_detected"] or pt["color_std"] > 15.0)
        self.assertGreaterEqual(pt["baseline_diff"], 8.0)

    def test_real_frame_shot_00847_scrolled_settings_punch_through(self):
        """shot-00847.raw (second scrolled Settings frame) must detect top navigation bar punch-through."""
        p = self.evidence_dir / "shot-00847.raw"
        baseline = self.evidence_dir / "shot-00604.raw"
        if not p.exists() or not baseline.exists():
            self.skipTest("Required shots not found")

        res = va.audit_screenshot(p, baseline_path=str(baseline))
        self.assertTrue(res["defect_detected"])
        top_pts = [pt for pt in res["bar_punch_through"] if pt["bar"] == "top_bar"]
        self.assertEqual(len(top_pts), 1)

    def test_real_frame_shot_00991_control_center_analysis(self):
        """shot-00991.raw (Control Center) must be audited without crashes and inspect defect state."""
        p = self.evidence_dir / "shot-00991.raw"
        if not p.exists():
            self.skipTest(f"{p} not found")

        res = va.audit_screenshot(p)
        self.assertEqual(res["width"], 1156)
        self.assertEqual(res["height"], 2510)
        # Note: Control center buttons have deep dark backgrounds, check whether pure_black_blocks flags them or not
        # If pure_black_blocks is tuned to R<=2, G<=2, B<=2, check the result:
        print(f"\n[Empirical Check] shot-00991 (Control Center) defects found: {len(res['pure_black_blocks'])} black blocks, {len(res['bar_punch_through'])} punch through")

    # -------------------------------------------------------------------------
    # 4. Temporal Dirty Region Ghosting Detector Stress
    # -------------------------------------------------------------------------
    def test_temporal_ghosting_identical_frames_no_false_positive(self):
        """Three identical frames must never trigger dirty region ghosting."""
        f0 = np.full((2510, 1156, 3), 120, dtype=np.uint8)
        ghosts = va.detect_dirty_region_ghosting([f0, f0, f0])
        self.assertEqual(len(ghosts), 0)

    def test_temporal_ghosting_detection(self):
        """Frame sequence where a region moves then leaves a lingering boundary must trigger ghosting."""
        f0 = np.full((2510, 1156, 3), 50, dtype=np.uint8)
        f1 = np.full((2510, 1156, 3), 50, dtype=np.uint8)
        f2 = np.full((2510, 1156, 3), 50, dtype=np.uint8)

        # Region y=500..800, x=300..600 turns white in f1, lingers in f2
        f1[500:800, 300:600] = 250
        f2[500:800, 300:600] = 245

        ghosts = va.detect_dirty_region_ghosting([f0, f1, f2])
        self.assertGreaterEqual(len(ghosts), 1)
        self.assertEqual(ghosts[0]["type"], "dirty_region_ghosting")


if __name__ == "__main__":
    unittest.main()
