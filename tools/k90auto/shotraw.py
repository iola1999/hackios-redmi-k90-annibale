#!/usr/bin/env python3
"""Inspect and decode raw K90 scanout screenshots (.raw + optional .raw.json sidecar)."""
import json
from pathlib import Path
import re
import subprocess
import sys

DEFAULT_WIDTH, DEFAULT_HEIGHT, DEFAULT_STRIDE = 1156, 2510, 1156 * 4
KNOWN_SIZES = {
    1156 * 2510 * 4: (1156, 2510, 1156 * 4, "bgra"),
    2622 * 4864: (1206, 2622, 4864, "bgra"),
    1206 * 2622 * 4: (1206, 2622, 1206 * 4, "bgra"),
}
VALID_FORMATS = ("bgra", "l10r")
SCREEN_RE = re.compile(
    r"(?:^|\n)\s*(?:screen:\s*)?(\d+)\s+(\d+)\s+(\d+)(?:\s+(bgra|l10r))?(?:\s|$)",
    re.I,
)


def meta_path(raw_path):
    """Sidecar JSON path storing width, height, stride, and format for RAW_PATH."""
    return Path(f"{raw_path}.json")


def parse_getvar_screen(output):
    """Parse fastboot `getvar screen` output into (width, height, stride, fmt), or None."""
    match = SCREEN_RE.search(output or "")
    if not match:
        return None
    width, height, stride = int(match.group(1)), int(match.group(2)), int(match.group(3))
    fmt = (match.group(4) or "bgra").lower()
    if width <= 0 or height <= 0 or stride < width * 4 or fmt not in VALID_FORMATS:
        return None
    return width, height, stride, fmt


def write_shot_meta(raw_path, width, height, stride, fmt="bgra"):
    """Persist scanout geometry metadata next to RAW_PATH."""
    meta_path(raw_path).write_text(
        json.dumps({"width": int(width), "height": int(height), "stride": int(stride), "format": fmt}) + "\n"
    )


def inspect_shot(raw_path):
    """Return (width, height, stride, fmt) for RAW_PATH, validating exact byte length."""
    path = Path(raw_path)
    size = path.stat().st_size
    sidecar = meta_path(path)
    if sidecar.is_file():
        info = json.loads(sidecar.read_text())
        width = info.get("width")
        height = info.get("height")
        stride = info.get("stride")
        fmt = str(info.get("format", "bgra")).lower()
        if (
            not isinstance(width, int)
            or not isinstance(height, int)
            or not isinstance(stride, int)
            or width <= 0
            or height <= 0
            or stride < width * 4
            or fmt not in VALID_FORMATS
            or size != stride * height
        ):
            raise ValueError(f"{path}: sidecar geometry {info!r} does not match {size} bytes")
        return width, height, stride, fmt
    if size in KNOWN_SIZES:
        return KNOWN_SIZES[size]
    raise ValueError(f"{path}: unrecognized raw screenshot size {size}")


def decode_shot_rgb(raw_path):
    """Decode RAW_PATH (BGRA8888 or BGR10A2 l10r, padded stride supported) to (H, W, 3) uint8 RGB."""
    import numpy as np

    path = Path(raw_path)
    width, height, stride, fmt = inspect_shot(path)
    data = path.read_bytes()
    if len(data) != stride * height:
        raise ValueError(f"{path}: expected {stride * height} bytes, got {len(data)}")
    rows = np.frombuffer(data, dtype=np.uint8).reshape((height, stride))[:, : width * 4]
    if fmt == "bgra":
        return rows.reshape((height, width, 4))[:, :, 2::-1].copy()
    u32 = np.ascontiguousarray(rows).view("<u4").reshape((height, width))
    b = (((u32 & 0x3FF) * 255 + 511) // 1023).astype(np.uint8)
    g = ((((u32 >> 10) & 0x3FF) * 255 + 511) // 1023).astype(np.uint8)
    r = ((((u32 >> 20) & 0x3FF) * 255 + 511) // 1023).astype(np.uint8)
    return np.stack((r, g, b), axis=-1)


def to_png(raw_path, png_path):
    """Decode RAW_PATH and encode lossless PNG via ffmpeg."""
    rgb = decode_shot_rgb(raw_path)
    height, width = rgb.shape[:2]
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-y",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "rgb24",
            "-s",
            f"{width}x{height}",
            "-i",
            "-",
            str(png_path),
        ],
        input=rgb.tobytes(),
        check=True,
    )


def main(argv=None):
    args = sys.argv[1:] if argv is None else argv
    if len(args) == 3 and args[0] == "to-png":
        to_png(args[1], args[2])
        return 0
    if len(args) == 2 and args[0] == "info":
        width, height, stride, fmt = inspect_shot(args[1])
        print(f"{width} {height} {stride} {fmt}")
        return 0
    raise SystemExit("usage: shotraw.py to-png SRC.raw DST.png | info SRC.raw")


if __name__ == "__main__":
    sys.exit(main())
