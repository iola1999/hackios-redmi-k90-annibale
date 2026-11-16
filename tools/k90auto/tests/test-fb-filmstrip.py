#!/usr/bin/env python3
"""Unit tests for tools/k90auto/fb_filmstrip.py (RWREC003 parsing, tl: correlation, and anomaly detectors)."""
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
TOOL = ROOT / "tools/k90auto/fb_filmstrip.py"


def write_rwrec(path: Path, frames: list[np.ndarray], times_ms: list[float], oldest: int = 0, began_s: float = 12.5):
    h, w, c = frames[0].shape
    assert c == 3
    out = bytearray(struct.pack("<8sIIIIQ", b"RWREC003", w, h, len(frames), oldest, int(began_s * 1e9)))
    for pic, ms in zip(frames, times_ms):
        out += struct.pack("<Q", int(ms * 1e6))
        out += np.ascontiguousarray(pic, dtype=np.uint8).tobytes()
    path.write_bytes(bytes(out))


def test_clean_and_ring_wrap():
    w, h = 96, 160
    frames = []
    for i in range(6):
        pic = np.full((h, w, 3), 120 + i * 4, dtype=np.uint8)
        frames.append(pic)
    # Store ring-wrapped at oldest=2: physical order is [4, 5, 0, 1, 2, 3] where logical order is [0..5]
    # Wait: in RWREC003, oldest=2 means physical[2..5] + physical[0..1] is logical [0..5].
    phys_frames = frames[4:] + frames[:4]
    phys_times = [64.0, 80.0, 0.0, 16.0, 32.0, 48.0]
    with tempfile.TemporaryDirectory() as tmp:
        td = Path(tmp)
        rec = td / "clean.bin"
        out_dir = td / "out"
        write_rwrec(rec, phys_frames, phys_times, oldest=2, began_s=10.0)
        subprocess.run([sys.executable, str(TOOL), "--recording", str(rec), "--out-dir", str(out_dir)], check=True)
        rep = json.loads((out_dir / "report.json").read_text())
        assert rep["frames"] == 6
        assert rep["anomaly_counts"] == {}, rep["anomalies"]
        assert [s["time_ms"] for s in rep["frame_stats"]] == [0.0, 16.0, 32.0, 48.0, 64.0, 80.0]
        assert (out_dir / "filmstrip.png").is_file()


def test_all_four_glitches_and_tl_correlation():
    w, h = 96, 192
    base = np.full((h, w, 3), 140, dtype=np.uint8)

    # Frame 0: clean home screen
    f0 = base.copy()
    # Frame 1: BLACK_FLASH (MISC-8 app open black frame)
    f1 = np.zeros((h, w, 3), dtype=np.uint8)
    # Frame 2: clean bright app
    f2 = base.copy()
    # Frame 3: HORIZ_BAND (MISC-8 App Switcher horizontal black band across middle rows 70..110)
    f3 = base.copy()
    f3[70:110, :, :] = 0
    # Frame 4: back to clean bright app
    f4 = base.copy()
    # Frame 5: FLICKER_ALT (MISC-7 Files whole-screen / half-screen alternating buffer jump)
    f5 = base.copy()
    f5[16:128, 16:80, :] = 230
    # Frame 6: reverts to f4 (completing f4 -> f5 -> f6 A->B->A flash)
    f6 = base.copy()
    # Frame 7: DARK_FRINGE (MISC-7 lifted icon with pure-black 2px border around bright interior)
    f7 = base.copy()
    f7[40:84, 24:68, :] = 0
    f7[42:82, 26:66, :] = 220

    frames = [f0, f1, f2, f3, f4, f5, f6, f7]
    times = [i * 16.67 for i in range(len(frames))]
    log_lines = [
        "MiniIOMobileFramebuffer: armed runtime recording for 3 s into 64 MB at 0x123400000 (scanout=0)",
        "tl: s 501 38 617 backboardd at 20016000",
        "tl: rec 0 swap 500 us 20000100 buf 1 drew 1 set 0x1 clr 0x0 sids 11,0,0,0 band 0..2400 bseq 0->1 all 1",
        "tl: rec 1 swap 501 us 20016700 buf 0 drew 1 set 0x1 clr 0x0 sids 0,0,0,0 band 0..2400 bseq 1->2 all 1",
        "tl: rec 3 swap 503 us 20050100 buf 0 drew 1 set 0x1 clr 0x0 sids 12,0,0,0 band 0..700 bseq 3->4 all 0",
        "annibalemetal[com.apple.MapKit.SnapshotService 331]: command buffer failed: sample error",
        "adreno8: no page table for GPU address 0x8f800000: a buffer of 28672 KB is refused",
        "2026-11-17 03:00:15.410984+0800 backboardd[38:488] [Metal] Failed to allocate [1206 x 2622] BGRA framebuffer",
    ]
    with tempfile.TemporaryDirectory() as tmp:
        td = Path(tmp)
        rec = td / "glitches.bin"
        log = td / "loader.log"
        out_dir = td / "out"
        write_rwrec(rec, frames, times, oldest=0, began_s=20.0)
        log.write_text("\n".join(log_lines) + "\n")
        subprocess.run(
            [sys.executable, str(TOOL), "--recording", str(rec), "--log", str(log), "--out-dir", str(out_dir)],
            check=True,
        )
        rep = json.loads((out_dir / "report.json").read_text())
        counts = rep["anomaly_counts"]
        assert counts.get("BLACK_FLASH") == 1, rep["anomalies"]
        assert counts.get("HORIZ_BAND") == 1, rep["anomalies"]
        assert counts.get("FLICKER_ALT") == 1, rep["anomalies"]
        assert counts.get("DARK_FRINGE") == 1, rep["anomalies"]
        assert rep["tl_correlated_frames"] == 3, rep
        assert rep["frame_stats"][1]["tl"]["submit"]["proc"] == "backboardd"
        assert len(rep["gpu_errors"]) == 3
        assert (out_dir / "filmstrip.png").is_file()


def main():
    test_clean_and_ring_wrap()
    test_all_four_glitches_and_tl_correlation()
    print("PASS: fb_filmstrip parsing, correlation, contact-sheet rendering, and anomaly detection")


if __name__ == "__main__":
    main()
