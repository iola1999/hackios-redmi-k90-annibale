#!/usr/bin/env python3
"""Capture or analyze RWREC003 framebuffer recordings, correlate tl: logs, and stitch filmstrips.

Usage:
  Live capture:
    python3 tools/k90auto/fb_filmstrip.py --arm 4 --cmd $'open com.apple.Preferences\\nsleep 1500' --out-dir out/rec-prefs
  Offline analysis:
    python3 tools/k90auto/fb_filmstrip.py --recording out/rec-prefs/recording.bin --log out/rec-prefs/loader.log --out-dir out/rec-prefs
"""
import argparse
import json
from pathlib import Path
import re
import struct
import subprocess
import sys
import time

import numpy as np
from PIL import Image, ImageDraw

HERE = Path(__file__).resolve().parent
RSH = HERE / "rsh.py"

RE_TL_REC = re.compile(
    r"tl: rec (\d+) swap (\d+) us (\d+) buf (-?\d+) drew (\d+) "
    r"set (0x[0-9a-fA-F]+) clr (0x[0-9a-fA-F]+) sids ([\d,]+) "
    r"band (-?\d+)\.\.(-?\d+) bseq (\d+)->(\d+) all (\d+)"
)
RE_TL_SWAP = re.compile(r"tl: s (\d+) (\d+) (\d+) (\S+) at (\d+)")
RE_GPU_ERR = re.compile(
    r"(command buffer failed: .*|the draw failed: .*|"
    r"no page table for GPU address .*|no GPU addresses for a buffer .*|"
    r"AnnibaleGPU: no (?:addresses|handles|memory) .*|"
    r"the GPU driver would not allocate .*|\[Metal\] Failed to allocate .*)"
)


def load_rwrec(path: Path):
    data = path.read_bytes()
    if len(data) < 32:
        raise ValueError(f"{path}: truncated header ({len(data)} bytes)")
    magic, w, h, count, oldest, began_ns = struct.unpack_from("<8sIIIIQ", data, 0)
    if magic != b"RWREC003":
        raise ValueError(f"{path}: unexpected magic {magic!r}")
    fbytes = w * h * 3
    times_s, pics = [], []
    at = 32
    for _ in range(count):
        if at + 8 + fbytes > len(data):
            break
        ns = struct.unpack_from("<Q", data, at)[0]
        times_s.append(ns / 1e9)
        pics.append(np.frombuffer(data, np.uint8, fbytes, at + 8).reshape(h, w, 3).copy())
        at += 8 + fbytes
    if 0 < oldest < len(times_s):
        times_s = times_s[oldest:] + times_s[:oldest]
        pics = pics[oldest:] + pics[:oldest]
    return {
        "began_s": began_ns / 1e9,
        "width": w,
        "height": h,
        "times_s": times_s,
        "pics": pics,
    }


def parse_logs(log_text: str, began_s: float, duration_s: float):
    rec_meta = {}
    swaps = {}
    gpu_errors = []
    start_us = int(began_s * 1e6) - 200_000
    end_us = int((began_s + max(duration_s, 0.0) + 1.0) * 1e6)
    # Keep the latest recording session in log_text if multiple rec_arm runs exist.
    sessions = [[]]
    for line in log_text.splitlines():
        if "armed runtime recording" in line or "recording begins at" in line:
            if sessions[-1]:
                sessions.append([])
        m = RE_TL_REC.search(line)
        if m:
            sessions[-1].append(m)
            continue
        ms = RE_TL_SWAP.search(line)
        if ms:
            swaps[int(ms.group(1))] = {
                "pid": int(ms.group(2)),
                "tid": int(ms.group(3)),
                "proc": ms.group(4),
                "submit_us": int(ms.group(5)),
            }
        me = RE_GPU_ERR.search(line)
        if me:
            gpu_errors.append(me.group(1).strip())
    chosen = sessions[-1] if sessions[-1] else (sessions[-2] if len(sessions) >= 2 else [])
    for m in chosen:
        idx = int(m.group(1))
        us = int(m.group(3))
        if began_s > 0 and not (start_us <= us <= end_us):
            continue
        swap_id = int(m.group(2))
        rec_meta[idx] = {
            "swap": swap_id,
            "us": us,
            "buf": int(m.group(4)),
            "drew": int(m.group(5)),
            "set": m.group(6),
            "clr": m.group(7),
            "sids": m.group(8),
            "band": [int(m.group(9)), int(m.group(10))],
            "bseq": [int(m.group(11)), int(m.group(12))],
            "all": int(m.group(13)),
            "submit": swaps.get(swap_id),
        }
    return rec_meta, gpu_errors[-20:]


def cell_mad(a: np.ndarray, b: np.ndarray, cell: int = 16) -> np.ndarray:
    h, w, _ = a.shape
    hh, ww = (h // cell) * cell, (w // cell) * cell
    if hh == 0 or ww == 0:
        return np.zeros((1, 1), dtype=np.float32)
    ca = a[:hh, :ww].astype(np.int16).reshape(hh // cell, cell, ww // cell, cell, 3)
    cb = b[:hh, :ww].astype(np.int16).reshape(hh // cell, cell, ww // cell, cell, 3)
    return np.abs(ca - cb).mean(axis=(1, 3, 4))


def detect_horiz_band(pic: np.ndarray):
    h, w, _ = pic.shape
    y_lo, y_hi = max(2, int(h * 0.08)), min(h - 2, int(h * 0.92))
    if y_hi - y_lo < 12:
        return None
    row_luma = pic.mean(axis=(1, 2))
    row_dark_frac = (pic.max(axis=2) <= 10).mean(axis=1)
    min_band = max(8, h // 28)
    y = y_lo
    while y < y_hi:
        if row_luma[y] < 6.0 and row_dark_frac[y] >= 0.90:
            y0 = y
            while y < y_hi and row_luma[y] < 6.0 and row_dark_frac[y] >= 0.90:
                y += 1
            y1 = y
            if y1 - y0 >= min_band:
                above = row_luma[max(0, y0 - 8):y0].mean() if y0 > 0 else 0.0
                below = row_luma[y1:min(h, y1 + 8)].mean() if y1 < h else 0.0
                if above >= 28.0 and below >= 28.0:
                    return {"y0": int(y0), "y1": int(y1), "above_luma": round(float(above), 1), "below_luma": round(float(below), 1)}
        else:
            y += 1
    return None


def detect_dark_fringe(prev_pic: np.ndarray, pic: np.ndarray):
    diff = np.abs(pic.astype(np.int16) - prev_pic.astype(np.int16)).max(axis=2)
    changed = diff > 24
    h, w = changed.shape
    changed_frac = float(changed.mean())
    if changed_frac < 0.005 or changed_frac > 0.45:
        return None
    ys, xs = np.nonzero(changed)
    y0, y1 = int(ys.min()), int(ys.max()) + 1
    x0, x1 = int(xs.min()), int(xs.max()) + 1
    if (y1 - y0) < 16 or (x1 - x0) < 16:
        return None
    roi = pic[y0:y1, x0:x1]
    bright = roi.mean(axis=2) >= 60.0
    if bright.sum() < 64:
        return None
    # 1-pixel dilated perimeter around bright interior inside ROI
    pad = np.pad(bright, 2, mode="constant", constant_values=False)
    dil = (
        pad[1:-3, 2:-2] | pad[3:-1, 2:-2] | pad[2:-2, 1:-3] | pad[2:-2, 3:-1]
        | pad[0:-4, 2:-2] | pad[4:, 2:-2] | pad[2:-2, 0:-4] | pad[2:-2, 4:]
    )
    ring = dil & ~bright
    if ring.sum() < 24:
        return None
    prev_roi = prev_pic[y0:y1, x0:x1]
    was_bright_bg = prev_roi.mean(axis=2) >= 40.0
    active_ring = ring & was_bright_bg
    if active_ring.sum() < 20:
        return None
    pure_black = (roi.max(axis=2) <= 6) & active_ring
    black_ratio = float(pure_black.sum()) / float(active_ring.sum())
    if black_ratio >= 0.30:
        return {
            "bbox": [x0, y0, x1, y1],
            "black_ring_ratio": round(black_ratio, 3),
            "ring_pixels": int(active_ring.sum()),
        }
    return None


def analyze_recording(rec: dict, rec_meta: dict = None, cell: int = 16):
    rec_meta = rec_meta or {}
    pics = rec["pics"]
    times = rec["times_s"]
    nframes = len(pics)
    anomalies = []
    frame_stats = []

    lumas = [float(p.mean()) for p in pics]
    dark_fracs = [float((p.max(axis=2) <= 12).mean()) for p in pics]

    for i, pic in enumerate(pics):
        step_diff = float(np.abs(pic.astype(np.int16) - pics[i - 1].astype(np.int16)).mean()) if i > 0 else 0.0
        identical_prev = bool(i > 0 and np.array_equal(pic, pics[i - 1]))
        frame_stats.append({
            "frame": i,
            "time_ms": round(times[i] * 1000.0, 2),
            "luma": round(lumas[i], 2),
            "dark_frac": round(dark_fracs[i], 3),
            "mad_prev": round(step_diff, 2),
            "identical_prev": identical_prev,
            "tl": rec_meta.get(i),
            "flags": [],
        })

    # 1. BLACK_FLASH: transient near-black frame surrounded by bright content within <= 4 frames
    for i in range(nframes):
        if lumas[i] < 8.0 and dark_fracs[i] >= 0.85:
            before_bright = any(lumas[j] >= 25.0 for j in range(max(0, i - 4), i))
            after_bright = any(lumas[j] >= 25.0 for j in range(i + 1, min(nframes, i + 5)))
            if before_bright or after_bright:
                detail = {"kind": "BLACK_FLASH", "frame": i, "time_ms": frame_stats[i]["time_ms"], "luma": frame_stats[i]["luma"]}
                anomalies.append(detail)
                frame_stats[i]["flags"].append("BLACK_FLASH")

    # 2. HORIZ_BAND: transient dark horizontal band bounded by bright content above and below
    for i in range(nframes):
        hb = detect_horiz_band(pics[i])
        if hb is not None:
            # Verify it is transient (absent on at least one neighbor within +-4 frames, or whole clip short)
            neighbors = [j for j in range(max(0, i - 4), min(nframes, i + 5)) if j != i]
            if not neighbors or any(detect_horiz_band(pics[j]) is None for j in neighbors):
                detail = {"kind": "HORIZ_BAND", "frame": i, "time_ms": frame_stats[i]["time_ms"], **hb}
                anomalies.append(detail)
                frame_stats[i]["flags"].append("HORIZ_BAND")

    # 3. FLICKER_ALT: cell-level A -> B -> A oscillation (1 or 2 frame return)
    for i in range(1, nframes - 1):
        if frame_stats[i]["flags"] or "BLACK_FLASH" in frame_stats[i - 1]["flags"]:
            continue
        d_in = cell_mad(pics[i], pics[i - 1], cell)
        moved = d_in > 35.0
        if not moved.any():
            continue
        for k in (1, 2):
            if i + k >= nframes:
                break
            d_back = cell_mad(pics[i + k], pics[i - 1], cell)
            flash = moved & (d_back < 8.5)
            count = int(flash.sum())
            if count >= 4:
                ys, xs = np.nonzero(flash)
                detail = {
                    "kind": "FLICKER_ALT",
                    "frame": i,
                    "span_frames": k,
                    "time_ms": frame_stats[i]["time_ms"],
                    "cells": count,
                    "rows": [int(ys.min() * cell), int((ys.max() + 1) * cell)],
                    "cols": [int(xs.min() * cell), int((xs.max() + 1) * cell)],
                }
                anomalies.append(detail)
                frame_stats[i]["flags"].append("FLICKER_ALT")
                break

    # 4. DARK_FRINGE: pure-black halo appearing around newly drawn/lifted bright element
    for i in range(1, nframes):
        fringe = detect_dark_fringe(pics[i - 1], pics[i])
        if fringe is not None:
            detail = {"kind": "DARK_FRINGE", "frame": i, "time_ms": frame_stats[i]["time_ms"], **fringe}
            anomalies.append(detail)
            frame_stats[i]["flags"].append("DARK_FRINGE")

    return {"frame_stats": frame_stats, "anomalies": anomalies}


def select_display_frames(frame_stats: list, max_tiles: int = 48):
    n = len(frame_stats)
    if n == 0:
        return []
    keep = []
    i = 0
    while i < n:
        j = i + 1
        while j < n and frame_stats[j]["identical_prev"] and not frame_stats[j]["flags"]:
            j += 1
        keep.append((i, j - i))
        if j - i > 2 and (j < n and frame_stats[j]["flags"]):
            keep.append((j - 1, 1))
        i = j
    if len(keep) <= max_tiles:
        return keep
    pinned = {idx for idx, (fidx, _) in enumerate(keep) if frame_stats[fidx]["flags"] or idx in (0, len(keep) - 1)}
    step = max(1, len(keep) // max_tiles)
    sampled = [item for idx, item in enumerate(keep) if idx in pinned or idx % step == 0]
    return sampled[:max_tiles]


def render_filmstrip(rec: dict, analysis: dict, out_png: Path, cols: int = 6, max_tiles: int = 48):
    pics = rec["pics"]
    stats = analysis["frame_stats"]
    selected = select_display_frames(stats, max_tiles=max_tiles)
    if not selected:
        return
    h, w, _ = pics[0].shape
    scale = 1 if w <= 240 else (0.5 if w > 400 else 1)
    tw, th = max(1, int(w * scale)), max(1, int(h * scale))
    hdr_h = 44
    pad = 8
    ncols = min(cols, len(selected))
    nrows = (len(selected) + ncols - 1) // ncols
    canvas = Image.new("RGB", (ncols * (tw + pad) + pad, nrows * (th + hdr_h + pad) + pad), (24, 26, 30))
    draw = ImageDraw.Draw(canvas)

    for tile_idx, (fidx, repeat) in enumerate(selected):
        r, c = divmod(tile_idx, ncols)
        x0 = pad + c * (tw + pad)
        y0 = pad + r * (th + hdr_h + pad)
        st = stats[fidx]
        flags = st["flags"]
        border = (235, 64, 52) if flags else (70, 76, 88)
        draw.rectangle([x0 - 2, y0 - 2, x0 + tw + 1, y0 + hdr_h + th + 1], outline=border, width=2 if flags else 1)
        tl = st.get("tl") or {}
        swap_txt = f"sw={tl['swap']} b={tl['buf']}" if "swap" in tl else f"L={st['luma']:.0f}"
        rep_txt = f" x{repeat}" if repeat > 1 else ""
        line1 = f"#{fidx}{rep_txt} +{st['time_ms']:.0f}ms {swap_txt}"
        line2 = ",".join(flags) if flags else (f"sids={tl.get('sids', '-')} d={st['mad_prev']:.1f}")
        draw.text((x0 + 3, y0 + 2), line1[:34], fill=(235, 238, 245))
        draw.text((x0 + 3, y0 + 20), line2[:34], fill=(255, 120, 110) if flags else (165, 175, 190))
        im = Image.fromarray(np.ascontiguousarray(pics[fidx]))
        if (tw, th) != (w, h):
            im = im.resize((tw, th), Image.Resampling.BILINEAR)
        canvas.paste(im, (x0, y0 + hdr_h))

    out_png.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_png)


def run_rsh(round_arg: str, command: str) -> str:
    res = subprocess.run([sys.executable, str(RSH), round_arg, command], capture_output=True, text=True)
    if res.returncode != 0:
        raise RuntimeError(f"rsh failed ({res.returncode}): {res.stderr.strip()}")
    return res.stdout.strip()


def capture_live(args, out_dir: Path):
    round_arg = str(args.round_dir) if args.round_dir else "-"
    arm_val = -abs(args.arm) if args.scanout else abs(args.arm)
    run_rsh(round_arg, f"sysctl kern.annibale.rec_arm={arm_val}")
    try:
        if args.cmd:
            run_rsh(round_arg, args.cmd)
        else:
            time.sleep(abs(args.arm))
    finally:
        run_rsh(round_arg, "sysctl kern.annibale.rec_arm=0")
    info = run_rsh(round_arg, "sysctl kern.annibale.rec_info")
    # Expected format: "kern.annibale.rec_info = 0xPA USED FRAMES W H ACTIVE" (or ":")
    vals = re.split(r"[:=]", info.splitlines()[0], maxsplit=1)[-1].strip().split()
    if len(vals) < 5 or vals[0] == "0x0" or int(vals[1]) <= 32:
        raise RuntimeError(f"recording empty or unavailable: {info!r}")
    pa_hex = vals[0].lower().removeprefix("0x")
    used_hex = f"{int(vals[1]):x}"
    rec_bin = out_dir / "recording.bin"
    log_file = out_dir / "loader.log"
    out_dir.mkdir(parents=True, exist_ok=True)
    st = subprocess.run(["fastboot", "-s", "xnuloader", "oem", "stage", pa_hex, used_hex], capture_output=True, text=True)
    if st.returncode != 0 or "FAILED" in st.stdout + st.stderr:
        raise RuntimeError(f"oem stage failed: {st.stdout}{st.stderr}")
    dl = subprocess.run(["fastboot", "-s", "xnuloader", "get_staged", str(rec_bin)], capture_output=True, text=True)
    if dl.returncode != 0 or not rec_bin.is_file():
        raise RuntimeError(f"get_staged recording failed: {dl.stdout}{dl.stderr}")
    subprocess.run(["fastboot", "-s", "xnuloader", "oem", "log"], capture_output=True, text=True)
    subprocess.run(["fastboot", "-s", "xnuloader", "get_staged", str(log_file)], capture_output=True, text=True)
    return rec_bin, (log_file if log_file.is_file() else None)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--arm", type=int, default=0, help="arm live kernel screen recording for N seconds")
    ap.add_argument("--scanout", action="store_true", help="sample physical DPU scanout buffer directly")
    ap.add_argument("--cmd", default="", help="annsh script to run while recording is armed")
    ap.add_argument("--round-dir", type=Path, default=None, help="active run-auto round dir (omit for '-')")
    ap.add_argument("--recording", type=Path, default=None, help="existing RWREC003 .bin file")
    ap.add_argument("--log", type=Path, default=None, help="optional loader/kernel log with tl: lines")
    ap.add_argument("--out-dir", type=Path, required=True, help="directory for filmstrip.png and report.json")
    ap.add_argument("--cols", type=int, default=6)
    ap.add_argument("--max-tiles", type=int, default=48)
    args = ap.parse_args()

    if args.arm > 0:
        rec_path, log_path = capture_live(args, args.out_dir)
    elif args.recording is not None:
        rec_path, log_path = args.recording, args.log
    else:
        ap.error("provide either --arm SECS or --recording FILE.bin")

    rec = load_rwrec(rec_path)
    duration_s = rec["times_s"][-1] if rec["times_s"] else 0.0
    rec_meta, gpu_errors = ({}, [])
    if log_path is not None and log_path.is_file():
        rec_meta, gpu_errors = parse_logs(log_path.read_text(errors="replace"), rec["began_s"], duration_s)

    analysis = analyze_recording(rec, rec_meta=rec_meta)
    filmstrip_png = args.out_dir / "filmstrip.png"
    render_filmstrip(rec, analysis, filmstrip_png, cols=args.cols, max_tiles=args.max_tiles)

    counts = {}
    for item in analysis["anomalies"]:
        counts[item["kind"]] = counts.get(item["kind"], 0) + 1
    report = {
        "recording": str(rec_path),
        "width": rec["width"],
        "height": rec["height"],
        "frames": len(rec["pics"]),
        "duration_ms": round(duration_s * 1000.0, 2),
        "began_s": round(rec["began_s"], 3),
        "tl_correlated_frames": len(rec_meta),
        "gpu_errors": gpu_errors,
        "anomaly_counts": counts,
        "anomalies": analysis["anomalies"],
        "filmstrip": str(filmstrip_png),
        "frame_stats": analysis["frame_stats"],
    }
    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(
        f"fb_filmstrip: {report['frames']} frames ({report['duration_ms']:.1f} ms), "
        f"tl_matched={report['tl_correlated_frames']}, anomalies={counts or 'none'} -> {filmstrip_png}"
    )


if __name__ == "__main__":
    main()
