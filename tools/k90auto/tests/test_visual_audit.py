#!/usr/bin/env python3
"""Unit and integration tests for tools/k90auto/visual-audit.py."""

import json
import os
import subprocess
import sys
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

# Import visual-audit modules
HERE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(HERE))
import importlib.util

spec = importlib.util.spec_from_file_location("visual_audit", str(HERE / "visual-audit.py"))
va = importlib.util.module_from_spec(spec)
spec.loader.exec_module(va)


class TestVisualAudit(unittest.TestCase):
    def setUp(self):
        self.evidence_dir = Path("docs/progress/evidence/k90auto/kernel-12377-st4-r2/run")
        self.shot321 = self.evidence_dir / "shot-00321.raw"
        self.shot604 = self.evidence_dir / "shot-00604.raw"
        self.shot838 = self.evidence_dir / "shot-00838.raw"

    def test_synthetic_pure_black_detection(self):
        """Test pure black block detection on synthetic image."""
        # Create 1156x2510 image with gray background
        img = np.full((2510, 1156, 3), 128, dtype=np.uint8)
        # Add a 320x224 pure black block at y=480..704, x=288..608 (grid-aligned)
        img[480:704, 288:608] = 0

        blocks = va.detect_pure_black_blocks(img)
        self.assertGreaterEqual(len(blocks), 1)
        found = any(b["width"] >= 300 and b["height"] >= 200 and b["black_ratio"] >= 0.95 for b in blocks)
        self.assertTrue(found, f"Expected black block not found in {blocks}")

    def test_synthetic_clean_image_has_no_black_defects(self):
        """Test clean image with varied colors has no pure black defects."""
        img = np.full((2510, 1156, 3), 180, dtype=np.uint8)
        blocks = va.detect_pure_black_blocks(img)
        self.assertEqual(len(blocks), 0)

    def test_genuine_shot_00321_widgets(self):
        """Test pure black block detection on genuine shot-00321.raw (desktop widgets)."""
        if not self.shot321.exists():
            self.skipTest(f"{self.shot321} not found")

        rgb = va.load_image(str(self.shot321))
        blocks = va.detect_pure_black_blocks(rgb)
        self.assertGreaterEqual(len(blocks), 2, "Should detect at least 2 pure black widget blocks")

        # Verify left widget (weather) and right widget (calendar)
        boxes = [b["box"] for b in blocks]
        # x coordinates: left card is around 80, right card is around 624
        has_left = any(abs(bx[0] - 80) <= 32 and bx[1] >= 200 and bx[1] <= 300 for bx in boxes)
        has_right = any(abs(bx[0] - 624) <= 32 and bx[1] >= 200 and bx[1] <= 300 for bx in boxes)
        self.assertTrue(has_left, f"Left widget block missing in {boxes}")
        self.assertTrue(has_right, f"Right widget block missing in {boxes}")

    def test_genuine_shot_00838_punch_through(self):
        """Test bar punch-through detection on genuine shot-00838.raw against shot-00604.raw."""
        if not self.shot838.exists() or not self.shot604.exists():
            self.skipTest("Shots 838 or 604 not found")

        rgb838 = va.load_image(str(self.shot838))
        rgb604 = va.load_image(str(self.shot604))

        results = va.detect_bar_punch_through(rgb838, baseline_rgb=rgb604)
        top_bar_defect = [r for r in results if r["bar"] == "top_bar" and r["defect"]]
        self.assertGreaterEqual(len(top_bar_defect), 1, "Should detect top_bar punch-through defect")
        self.assertGreater(top_bar_defect[0]["color_std"], 20.0)

    def test_synthetic_dirty_region_ghosting(self):
        """Test dirty region ghosting detector with 3 temporal frames."""
        f0 = np.full((2510, 1156, 3), 100, dtype=np.uint8)
        f1 = np.full((2510, 1156, 3), 100, dtype=np.uint8)
        f2 = np.full((2510, 1156, 3), 100, dtype=np.uint8)

        # Region y=800..1000, x=300..600 moves to white in f1, but lingers in f2 with partial residual
        f1[800:1000, 300:600] = 240
        f2[800:1000, 300:600] = 230  # lingering stop/residual boundary

        ghosts = va.detect_dirty_region_ghosting([f0, f1, f2])
        self.assertGreaterEqual(len(ghosts), 1)

    def test_cli_execution_and_json(self):
        """Test visual-audit.py end-to-end via CLI invocation."""
        if not self.shot321.exists():
            self.skipTest(f"{self.shot321} not found")

        json_out = Path("/tmp/test-audit-cli.json")
        if json_out.exists():
            json_out.unlink()

        cmd = [
            sys.executable,
            str(HERE / "visual-audit.py"),
            str(self.shot321),
            "--json",
            str(json_out),
            "--visual-debug",
            "--debug-dir",
            "/tmp",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        self.assertEqual(res.returncode, 0, f"CLI failed: {res.stderr}")
        self.assertTrue(json_out.exists(), "JSON output file was not created")

        data = json.loads(json_out.read_text())
        self.assertTrue(data.get("defect_detected"))
        self.assertGreaterEqual(len(data.get("pure_black_blocks", [])), 2)


if __name__ == "__main__":
    unittest.main()
