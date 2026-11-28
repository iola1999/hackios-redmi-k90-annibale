#!/usr/bin/env python3
"""Unit tests for variable-geometry and l10r K90 screenshot capture and decoding."""
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest

import numpy as np
from PIL import Image

K90 = Path(__file__).resolve().parents[1]
if str(K90) not in sys.path:
    sys.path.insert(0, str(K90))

import shotraw  # noqa: E402

spec_va = importlib.util.spec_from_file_location("visual_audit_under_test", str(K90 / "visual-audit.py"))
va = importlib.util.module_from_spec(spec_va)
spec_va.loader.exec_module(va)

spec_sum = importlib.util.spec_from_file_location("summary_under_test", str(K90 / "summary.py"))
summary = importlib.util.module_from_spec(spec_sum)
spec_sum.loader.exec_module(summary)

spec_tour = importlib.util.spec_from_file_location("tour_under_test", str(K90 / "tour.py"))
tour = importlib.util.module_from_spec(spec_tour)
spec_tour.loader.exec_module(tour)


def make_bgra_padded(width, height, stride, rgb_fn):
    buf = np.full((height, stride), 0xA5, dtype=np.uint8)
    for y in range(height):
        for x in range(width):
            r, g, b = rgb_fn(x, y)
            off = x * 4
            buf[y, off + 0] = b
            buf[y, off + 1] = g
            buf[y, off + 2] = r
            buf[y, off + 3] = 0xFF
    return buf.tobytes()


def make_l10r_padded(width, height, stride, words_fn):
    buf = np.full((height, stride), 0x5A, dtype=np.uint8)
    for y in range(height):
        row = np.array([words_fn(x, y) for x in range(width)], dtype="<u4").view(np.uint8)
        buf[y, : width * 4] = row
    return buf.tobytes()


class TestShotRaw(unittest.TestCase):
    def test_parse_getvar_screen(self):
        self.assertEqual(
            shotraw.parse_getvar_screen("screen: 1206 2622 4864 l10r\nFinished. Total time: 0.001s"),
            (1206, 2622, 4864, "l10r"),
        )
        self.assertEqual(
            shotraw.parse_getvar_screen("screen: 1156 2510 4624\n"),
            (1156, 2510, 4624, "bgra"),
        )
        self.assertIsNone(shotraw.parse_getvar_screen("screen: 1206 2622 4000 rgba"))
        self.assertIsNone(shotraw.parse_getvar_screen("Finished. Total time: 0.001s"))

    def test_decode_padded_stride_bgra_and_l10r(self):
        with tempfile.TemporaryDirectory() as td:
            d = Path(td)
            # 1) 1206x2622 stride 4864 known-size BGRA without sidecar
            row = np.zeros(4864, dtype=np.uint8)
            for x in range(1206):
                row[x * 4 + 0] = (x * 3) & 0xFF
                row[x * 4 + 1] = (x * 5) & 0xFF
                row[x * 4 + 2] = (x * 7) & 0xFF
                row[x * 4 + 3] = 0xFF
            bgra_raw = d / "shot-bgra.raw"
            bgra_raw.write_bytes(np.tile(row, (2622, 1)).tobytes())
            rgb = shotraw.decode_shot_rgb(bgra_raw)
            self.assertEqual(rgb.shape, (2622, 1206, 3))
            self.assertEqual(tuple(rgb[0, 10]), ((10 * 7) & 0xFF, (10 * 5) & 0xFF, (10 * 3) & 0xFF))
            self.assertEqual(tuple(rgb[2621, 1205]), ((1205 * 7) & 0xFF, (1205 * 5) & 0xFF, (1205 * 3) & 0xFF))

            # 2) Sidecar l10r (BGR10A2) with padded stride
            l10r_raw = d / "shot-l10r.raw"
            # (R=1023, G=512, B=0, A=3) -> R=255, G=128, B=0
            word_orange = (3 << 30) | (1023 << 20) | (512 << 10) | 0
            # (R=0, G=1023, B=1023, A=3) -> R=0, G=255, B=255
            word_cyan = (3 << 30) | (1023 << 10) | 1023
            raw_bytes = make_l10r_padded(16, 12, 80, lambda x, y: word_orange if y < 6 else word_cyan)
            l10r_raw.write_bytes(raw_bytes)
            shotraw.write_shot_meta(l10r_raw, 16, 12, 80, "l10r")
            lrgb = shotraw.decode_shot_rgb(l10r_raw)
            self.assertEqual(lrgb.shape, (12, 16, 3))
            self.assertEqual(tuple(lrgb[0, 0]), (255, 128, 0))
            self.assertEqual(tuple(lrgb[11, 15]), (0, 255, 255))

            # 3) visual-audit + tour.pixels + summary.screenshots consume variable raw shots cleanly
            va_rgb = va.load_image(str(l10r_raw))
            self.assertEqual(va_rgb.shape, (12, 16, 3))
            self.assertEqual(tuple(tour.pixels(l10r_raw)[0, 0]), (0, 128, 255))  # BGR for tour

            # 4) sheets.sh converts padded BGRA + l10r raw screenshots into exact WxH PNGs + contact sheet
            sheet_run = d / "sheet_run"
            sheet_run.mkdir()
            (sheet_run / "shot-00001.raw").write_bytes(bgra_raw.read_bytes())
            (sheet_run / "shot-00002.raw").write_bytes(raw_bytes)
            shotraw.write_shot_meta(sheet_run / "shot-00002.raw", 16, 12, 80, "l10r")
            subprocess.run(["bash", str(K90 / "sheets.sh"), str(sheet_run)], check=True, capture_output=True)
            with Image.open(sheet_run / "png/shot-00001.png") as im1:
                self.assertEqual(im1.size, (1206, 2622))
            with Image.open(sheet_run / "png/shot-00002.png") as im2:
                self.assertEqual(im2.size, (16, 12))
                arr = np.array(im2.convert("RGB"))
                self.assertEqual(tuple(arr[0, 0]), (255, 128, 0))
                self.assertEqual(tuple(arr[11, 15]), (0, 255, 255))
            self.assertFalse((sheet_run / "shot-00002.raw.json").exists())

    def test_summary_screenshots_scaled_and_png(self):
        with tempfile.TemporaryDirectory() as td:
            run = Path(td)
            (run / "png").mkdir()
            raw = run / "shot-00010.raw"
            # Fill BAND region (around y=616..672, x=41..458 for 480x1200) with BLUE=(9, 126, 201)
            raw_data = np.zeros((120, 48 * 4 + 16), dtype=np.uint8)
            # 48x120 BGR10A2 matching BLUE
            b10 = round(201 * 1023 / 255)
            g10 = round(126 * 1023 / 255)
            r10 = round(9 * 1023 / 255)
            blue_word = (3 << 30) | (r10 << 20) | (g10 << 10) | b10
            row_bytes = np.array([blue_word] * 48, dtype="<u4").view(np.uint8)
            for y in range(120):
                raw_data[y, : 48 * 4] = row_bytes
            raw.write_bytes(raw_data.tobytes())
            shotraw.write_shot_meta(raw, 48, 120, 48 * 4 + 16, "l10r")
            count, hits = summary.screenshots(str(run))
            self.assertEqual((count, hits), (1, 1))

    def test_tour_take_shot_accepts_sidecar_raw(self):
        with tempfile.TemporaryDirectory() as td:
            run = Path(td)
            raw = run / "shot-00001.raw"
            raw.write_bytes(make_l10r_padded(16, 12, 64, lambda x, y: (3 << 30) | (1023 << 20)))
            shotraw.write_shot_meta(raw, 16, 12, 64, "l10r")
            found = [p for p in run.glob("shot-*.raw") if tour._shot_complete(p)]
            self.assertEqual(found, [raw])


if __name__ == "__main__":
    unittest.main()
