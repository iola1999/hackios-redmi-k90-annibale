#!/usr/bin/env python3
"""Automatic visual defect audit tool for HackiOS K90.

Audits screenshots for:
1. Pure black block defects (e.g. broken widget background).
2. Top/bottom bar punch-through defects (e.g. unblurred text bleeding through navigation bars).
3. Dirty region ghosting / lingering rectangular artifacts across frames.

Usage:
  tools/k90auto/visual-audit.py SHOT [SHOT ...] [OPTIONS]

Options:
  --baseline PATH       Reference baseline screenshot for diff & punch-through comparison.
  --json PATH           Output audit results to structured JSON file.
  --visual-debug        Save annotated debug images with highlighted defect bounding boxes.
  --debug-dir DIR       Directory to save visual debug images (defaults to current directory).
  --threshold-black F   Minimum black pixel ratio to flag a black block (default: 0.80).
  --threshold-var F     Minimum color standard deviation for bar punch-through (default: 15.0).
"""

import argparse
import json
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

WIDTH, HEIGHT = 1156, 2510
RAW_BYTES = WIDTH * HEIGHT * 4
STATUS_BAR_ROWS = 150
GRID_CELL = 16


def load_image(path):
    """Load screenshot from .raw (1156x2510 BGRA) or standard image file (.png, .jpg)."""
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(f"File not found: {path}")

    data = p.read_bytes()
    if len(data) == RAW_BYTES and p.suffix.lower() == ".raw":
        raw = np.frombuffer(data, dtype=np.uint8).reshape((HEIGHT, WIDTH, 4))
        # Convert BGRA to RGB
        return raw[:, :, :3][:, :, ::-1].copy()

    # Fallback to PIL for PNG / other formats
    img = Image.open(path).convert("RGB")
    return np.array(img, dtype=np.uint8)


def detect_pure_black_blocks(rgb, min_width=200, min_height=150, threshold_black=0.80):
    """Detect large rectangular regions of pure black pixels.

    Divides image into 16x16 grid cells, marks cells with >= threshold_black pure black pixels,
    connects adjacent marked cells into components, and checks bounding box >= min_width x min_height.
    """
    h, w, _ = rgb.shape
    cell = GRID_CELL
    gh, gw = h // cell, w // cell

    # Pure black definition: R <= 2, G <= 2, B <= 2
    is_pure_black = (rgb <= 2).all(axis=2)

    grid = np.zeros((gh, gw), dtype=bool)
    for r in range(gh):
        y = r * cell
        # Skip status bar
        if y < STATUS_BAR_ROWS:
            continue
        # Skip bottom home bar
        if y >= h - 40:
            continue
        for c in range(gw):
            x = c * cell
            # Skip curved display corners (top corners & bottom corners)
            if (y < 220 or y > h - 220) and (x < 80 or x > w - 80):
                continue

            cell_mask = is_pure_black[y : y + cell, x : x + cell]
            if cell_mask.mean() >= threshold_black:
                grid[r, c] = True

    # Connected component labeling (4-connectivity)
    visited = np.zeros_like(grid, dtype=bool)
    blocks = []

    for r in range(gh):
        for c in range(gw):
            if not grid[r, c] or visited[r, c]:
                continue
            queue = [(r, c)]
            visited[r, c] = True
            cells_in_comp = []
            while queue:
                curr_r, curr_c = queue.pop(0)
                cells_in_comp.append((curr_r, curr_c))
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nr, nc = curr_r + dr, curr_c + dc
                    if 0 <= nr < gh and 0 <= nc < gw and grid[nr, nc] and not visited[nr, nc]:
                        visited[nr, nc] = True
                        queue.append((nr, nc))

            # Bounding box of component in pixels
            rs = [p[0] for p in cells_in_comp]
            cs = [p[1] for p in cells_in_comp]
            box_y1 = min(rs) * cell
            box_y2 = (max(rs) + 1) * cell
            box_x1 = min(cs) * cell
            box_x2 = (max(cs) + 1) * cell
            box_w = box_x2 - box_x1
            box_h = box_y2 - box_y1

            if box_w >= min_width and box_h >= min_height:
                patch = is_pure_black[box_y1:box_y2, box_x1:box_x2]
                actual_ratio = float(patch.mean())
                if actual_ratio >= threshold_black:
                    blocks.append(
                        {
                            "box": [int(box_x1), int(box_y1), int(box_w), int(box_h)],
                            "bounds": [int(box_x1), int(box_y1), int(box_x2), int(box_y2)],
                            "width": int(box_w),
                            "height": int(box_h),
                            "black_ratio": round(actual_ratio, 4),
                            "cell_count": len(cells_in_comp),
                            "defect": True,
                            "type": "pure_black_block",
                        }
                    )

    return blocks


def detect_bar_punch_through(rgb, baseline_rgb=None, threshold_var=15.0):
    """Detect unblurred content punching through top navigation bar or bottom bar.

    Computes edge gradient magnitude and color standard deviation.
    Identifies double row / overlapping text patterns against backdrop.
    """
    h, w, _ = rgb.shape
    results = []

    # Regions to inspect: top navigation bar and bottom bar
    bars = [
        {"name": "top_bar", "y1": 140, "y2": 320, "x1": 60, "x2": min(w - 60, 1096)},
        {"name": "bottom_bar", "y1": max(0, min(2350, h - 160)), "y2": min(2510, h), "x1": 60, "x2": min(w - 60, 1096)},
    ]

    for bar in bars:
        y1, y2, x1, x2 = bar["y1"], bar["y2"], bar["x1"], bar["x2"]
        if y2 > h or x2 > w or y1 >= y2 or x1 >= x2:
            continue

        # Bottom bar without baseline reference cannot be reliably distinguished from normal dock/table content
        if bar["name"] == "bottom_bar" and baseline_rgb is None:
            continue

        patch = rgb[y1:y2, x1:x2].astype(np.float32)

        # Color standard deviation across the bar
        color_std = float(patch.std(axis=(0, 1)).mean())

        # Convert to grayscale luminance (0.299*R + 0.587*G + 0.114*B) before gradient calculation
        gray = 0.299 * patch[:, :, 0] + 0.587 * patch[:, :, 1] + 0.114 * patch[:, :, 2]
        gy, gx = np.gradient(gray)
        grad_mag = np.sqrt(gx**2 + gy**2)
        grad_mean = float(grad_mag.mean())
        grad_std = float(grad_mag.std())

        # Horizontal edge projection for text row detection
        row_edges = grad_mag.mean(axis=1)
        peaks = []
        for i in range(1, len(row_edges) - 1):
            if row_edges[i] > row_edges[i - 1] and row_edges[i] > row_edges[i + 1] and row_edges[i] > 2.5:
                peaks.append((y1 + i, float(row_edges[i])))

        # Double text / overlay detection: multiple prominent edge peaks separated by text spacing
        double_text = len(peaks) >= 3

        baseline_diff_mean = None
        if baseline_rgb is not None:
            bh, bw, _ = baseline_rgb.shape
            if bh == h and bw == w:
                base_patch = baseline_rgb[y1:y2, x1:x2].astype(np.float32)
                diff = np.abs(patch - base_patch)
                baseline_diff_mean = float(diff.mean())

        # Defect criteria
        is_defect = False
        reasons = []

        if baseline_rgb is not None:
            # When baseline is provided, significant baseline difference is a mandatory prerequisite
            if baseline_diff_mean is not None and baseline_diff_mean >= 6.0:
                if grad_std > 8.0:
                    is_defect = True
                    reasons.append(f"significant unblurred deviation from baseline (diff={baseline_diff_mean:.1f}, grad_std={grad_std:.1f})")
                elif double_text or color_std > threshold_var:
                    is_defect = True
                    reasons.append(f"overlay text or high variance with baseline change (diff={baseline_diff_mean:.1f})")
        else:
            if color_std > threshold_var and grad_std > 8.0:
                is_defect = True
                reasons.append(f"high color variance ({color_std:.1f} > {threshold_var}) with sharp gradients")

            if double_text and grad_std > 6.0:
                is_defect = True
                reasons.append(f"double text rows detected ({len(peaks)} edge peaks)")

        if is_defect:
            results.append(
                {
                    "bar": bar["name"],
                    "box": [int(x1), int(y1), int(x2 - x1), int(y2 - y1)],
                    "bounds": [int(x1), int(y1), int(x2), int(y2)],
                    "color_std": round(color_std, 2),
                    "grad_mean": round(grad_mean, 2),
                    "grad_std": round(grad_std, 2),
                    "row_peaks": len(peaks),
                    "double_text_detected": double_text,
                    "baseline_diff": round(baseline_diff_mean, 2) if baseline_diff_mean is not None else None,
                    "reasons": reasons,
                    "defect": True,
                    "type": "bar_punch_through",
                }
            )

    return results


def detect_dirty_region_ghosting(frames, threshold_diff=24):
    """Detect dirty region ghosting / lingering rectangular artifacts across 3 temporal frames."""
    if len(frames) < 3:
        return []

    shape0 = frames[0].shape
    if len(shape0) < 3 or any(f.shape != shape0 for f in frames[:3]):
        return []
    h, w, _ = shape0
    if h < 32 or w < 32:
        return []

    f_prev = frames[0].astype(np.int16)
    f_curr = frames[1].astype(np.int16)
    f_next = frames[2].astype(np.int16)

    h, w, _ = f_curr.shape
    cell = GRID_CELL
    gh, gw = h // cell, w // cell

    # Temporal differences
    diff_in = np.abs(f_curr - f_prev).max(axis=2) > threshold_diff
    diff_out = np.abs(f_next - f_curr).max(axis=2) > threshold_diff
    diff_residual = np.abs(f_next - f_prev).max(axis=2) > threshold_diff

    # Skip status bar
    diff_in[:STATUS_BAR_ROWS] = False
    diff_out[:STATUS_BAR_ROWS] = False
    diff_residual[:STATUS_BAR_ROWS] = False

    grid = np.zeros((gh, gw), dtype=bool)
    for r in range(gh):
        y = r * cell
        for c in range(gw):
            x = c * cell
            in_ratio = diff_in[y : y + cell, x : x + cell].mean()
            res_ratio = diff_residual[y : y + cell, x : x + cell].mean()
            out_ratio = diff_out[y : y + cell, x : x + cell].mean()
            # Moved in current frame, but lingering boundary remains in next frame with partial stop
            if in_ratio > 0.30 and res_ratio > 0.25 and out_ratio < 0.20:
                grid[r, c] = True

    # Connected component analysis for ghosting patches
    visited = np.zeros_like(grid, dtype=bool)
    ghosts = []

    for r in range(gh):
        for c in range(gw):
            if not grid[r, c] or visited[r, c]:
                continue
            queue = [(r, c)]
            visited[r, c] = True
            comp = []
            while queue:
                curr_r, curr_c = queue.pop(0)
                comp.append((curr_r, curr_c))
                for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    nr, nc = curr_r + dr, curr_c + dc
                    if 0 <= nr < gh and 0 <= nc < gw and grid[nr, nc] and not visited[nr, nc]:
                        visited[nr, nc] = True
                        queue.append((nr, nc))

            if len(comp) >= 4:  # At least 4 contiguous grid cells
                rs = [p[0] for p in comp]
                cs = [p[1] for p in comp]
                by1, by2 = min(rs) * cell, (max(rs) + 1) * cell
                bx1, bx2 = min(cs) * cell, (max(cs) + 1) * cell
                persistence = float(diff_residual[by1:by2, bx1:bx2].mean())
                ghosts.append(
                    {
                        "box": [int(bx1), int(by1), int(bx2 - bx1), int(by2 - by1)],
                        "bounds": [int(bx1), int(by1), int(bx2), int(by2)],
                        "width": int(bx2 - bx1),
                        "height": int(by2 - by1),
                        "persistence_score": round(persistence, 4),
                        "cell_count": len(comp),
                        "defect": True,
                        "type": "dirty_region_ghosting",
                    }
                )

    return ghosts


def generate_visual_debug(rgb, defects, output_path):
    """Draw bounding boxes and labels over the image for defects."""
    img = Image.fromarray(rgb)
    draw = ImageDraw.Draw(img)

    colors = {
        "pure_black_block": (255, 50, 50),       # Red
        "bar_punch_through": (255, 165, 0),      # Orange
        "dirty_region_ghosting": (0, 220, 255),   # Cyan
    }

    for defect in defects:
        dtype = defect.get("type", "unknown")
        color = colors.get(dtype, (255, 0, 255))
        b = defect["bounds"]
        x1, y1, x2, y2 = b[0], b[1], b[2], b[3]

        # Draw thick rectangle
        for offset in range(3):
            draw.rectangle([x1 - offset, y1 - offset, x2 + offset, y2 + offset], outline=color)

        label = f"{dtype}"
        if dtype == "pure_black_block":
            label += f" ({defect['black_ratio']*100:.1f}%)"
        elif dtype == "bar_punch_through":
            label += f" std={defect['color_std']}"

        # Draw text background banner
        draw.rectangle([x1, max(0, y1 - 22), x1 + len(label) * 9 + 8, y1], fill=(0, 0, 0))
        draw.text((x1 + 4, max(0, y1 - 20)), label, fill=color)

    img.save(output_path)


def audit_screenshot(path, baseline_path=None, temporal_frames=None, visual_debug=False,
                     debug_dir=None, threshold_black=0.80, threshold_var=15.0):
    """Audit a single screenshot (with optional baseline or temporal frames)."""
    rgb = load_image(path)
    baseline_rgb = load_image(baseline_path) if baseline_path else None

    pure_black = detect_pure_black_blocks(rgb, threshold_black=threshold_black)
    punch_through = detect_bar_punch_through(rgb, baseline_rgb=baseline_rgb, threshold_var=threshold_var)

    ghosting = []
    if temporal_frames and len(temporal_frames) >= 3:
        loaded_frames = [load_image(f) for f in temporal_frames]
        ghosting = detect_dirty_region_ghosting(loaded_frames)

    all_defects = pure_black + punch_through + ghosting
    has_defect = len(all_defects) > 0

    debug_image_path = None
    if visual_debug:
        out_dir = Path(debug_dir) if debug_dir else Path(path).parent
        out_dir.mkdir(parents=True, exist_ok=True)
        debug_image_path = str(out_dir / f"{Path(path).stem}-audit-debug.png")
        generate_visual_debug(rgb, all_defects, debug_image_path)

    return {
        "file": str(path),
        "baseline": str(baseline_path) if baseline_path else None,
        "width": int(rgb.shape[1]),
        "height": int(rgb.shape[0]),
        "defect_detected": has_defect,
        "pure_black_blocks": pure_black,
        "bar_punch_through": punch_through,
        "ghosting_regions": ghosting,
        "debug_image": debug_image_path,
    }


def main():
    parser = argparse.ArgumentParser(description="Audit screenshots for visual rendering defects.")
    parser.add_argument("shots", nargs="+", help="Screenshot path(s) to audit (.raw or .png)")
    parser.add_argument("--baseline", help="Baseline screenshot to compare against")
    parser.add_argument("--json", dest="json_path", help="Save structured audit results to JSON file")
    parser.add_argument("--visual-debug", action="store_true", help="Generate annotated visual debug image")
    parser.add_argument("--debug-dir", help="Directory to save visual debug images")
    parser.add_argument("--threshold-black", type=float, default=0.80, help="Black pixel ratio threshold")
    parser.add_argument("--threshold-var", type=float, default=15.0, help="Color variance threshold")

    args = parser.parse_args()

    results = []
    print(f"Auditing {len(args.shots)} screenshot(s)...")

    # If exactly 3 shots provided and no baseline, treat as temporal sequence for ghosting check
    temporal_frames = args.shots if len(args.shots) == 3 and not args.baseline else None

    for shot_path in args.shots:
        res = audit_screenshot(
            shot_path,
            baseline_path=args.baseline,
            temporal_frames=temporal_frames,
            visual_debug=args.visual_debug,
            debug_dir=args.debug_dir,
            threshold_black=args.threshold_black,
            threshold_var=args.threshold_var,
        )
        results.append(res)

        status_str = "DEFECT DETECTED" if res["defect_detected"] else "PASS"
        print(f"\n--- {shot_path} [{status_str}] ---")
        if res["pure_black_blocks"]:
            print(f"  [!] Pure Black Blocks ({len(res['pure_black_blocks'])}):")
            for b in res["pure_black_blocks"]:
                bx = b["box"]
                print(f"      - Box [{bx[0]}, {bx[1]}, {bx[2]}, {bx[3]}], black ratio: {b['black_ratio']*100:.1f}%")

        if res["bar_punch_through"]:
            print(f"  [!] Bar Punch-Through ({len(res['bar_punch_through'])}):")
            for pt in res["bar_punch_through"]:
                bx = pt["box"]
                reasons = ", ".join(pt["reasons"])
                print(f"      - {pt['bar']} [{bx[0]}, {bx[1]}, {bx[2]}, {bx[3]}]: std={pt['color_std']}, {reasons}")

        if res["ghosting_regions"]:
            print(f"  [!] Ghosting Regions ({len(res['ghosting_regions'])}):")
            for gh in res["ghosting_regions"]:
                bx = gh["box"]
                print(f"      - Box [{bx[0]}, {bx[1]}, {bx[2]}, {bx[3]}]: persistence={gh['persistence_score']}")

        if res["debug_image"]:
            print(f"  [>] Debug visual output saved to: {res['debug_image']}")

    if args.json_path:
        out_json = results[0] if len(results) == 1 else {"results": results}
        Path(args.json_path).write_text(json.dumps(out_json, indent=2))
        print(f"\nJSON report saved to: {args.json_path}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
