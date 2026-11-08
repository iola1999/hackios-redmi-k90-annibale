#!/usr/bin/env python3
"""Drive a held round's iOS by what is on the screen instead of by coordinates.

usage: tools/k90auto/ui.py ROUND_DIR dump
       tools/k90auto/ui.py ROUND_DIR tap TEXT [--nth N] [--exact]
       tools/k90auto/ui.py ROUND_DIR shot NAME
       tools/k90auto/ui.py ROUND_DIR wait TEXT [SECONDS]
       tools/k90auto/ui.py ROUND_DIR accessibility

dump    posts com.annibale.ax: every process with libannibale-ax.dylib (package.py AX) writes the
        labels and frames of what it shows to /tmp/ax-NAME.txt; this fetches those files into
        ROUND_DIR/run/ax/ and prints them.
tap     dumps, picks the element whose label or value contains TEXT (case-insensitive; --exact for
        the whole label), from an application in front before SpringBoard, the N-th match from the
        top (default 0), and touches its middle with rwtouch.
shot    one screenshot, ROUND_DIR/run/NAME.png.
wait    dumps every 2 s until TEXT is on the screen or SECONDS (default 30) passed.
accessibility
        turns application accessibility on (com.annibale.ax.on): SwiftUI screens such as Settings'
        lists and Weather list their elements only in applications started after it.

The touch panel and the screen have the same proportions, so a point's share of the screen is its
share of the panel. Exit status 1 when no element matched or a step did not come back.
"""
import re
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import tour  # noqa: E402


def rsh(round_dir, *words):
    return subprocess.run([sys.executable, str(HERE / "rsh.py"), str(round_dir), *words],
                          capture_output=True, text=True).stdout


def dump(round_dir):
    """{process: (screen_w, screen_h, [(x, y, w, h, cls, label, value)])} of the latest dump."""
    out = Path(round_dir) / "run/ax"
    out.mkdir(exist_ok=True)
    names = lambda: re.findall(r"\bf\s+\d+\s+(ax-\S+\.txt)", rsh(round_dir, "ls", "/private/var/tmp"))
    for name in names():
        rsh(round_dir, "rm", f"/private/var/tmp/{name}")
    rsh(round_dir, "notify", "com.annibale.ax")
    time.sleep(1.5)
    screens = {}
    for name in names():
        local = out / name
        subprocess.run([sys.executable, str(HERE / "fetch.py"), str(round_dir), f"/private/var/tmp/{name}", str(local)],
                       capture_output=True, text=True)
        if not local.exists():
            continue
        lines = local.read_text(errors="replace").splitlines()
        m = re.match(r"# (\S+) pid \d+ screen (\d+) (\d+)", lines[0]) if lines else None
        if not m:
            continue
        items = []
        for row in lines[1:]:
            if row.startswith("#"):
                continue
            parts = row.split("\t")
            if len(parts) != 4:
                continue
            x, y, w, h = (float(v) for v in parts[0].split())
            items.append((x, y, w, h, parts[1], parts[2], parts[3]))
        screens[m.group(1)] = (float(m.group(2)), float(m.group(3)), items)
    return screens


def find(screens, text, exact=False):
    """Matches as (process, item, screen_w, screen_h), applications before SpringBoard, top to bottom."""
    needle = text.lower()
    found = []
    for process, (sw, sh, items) in screens.items():
        for item in items:
            label, value = item[5].lower(), item[6].lower()
            hit = needle in (label, value) if exact else (needle in label or needle in value)
            x, y, w, h = item[:4]
            on_screen = 0 <= x + w / 2 <= sw and 0 <= y + h / 2 <= sh
            if hit and on_screen:
                found.append((process, item, sw, sh))
    found.sort(key=lambda f: (f[0] == "SpringBoard", f[1][1], f[1][0]))
    return found


def main():
    if len(sys.argv) < 3:
        print(__doc__.strip())
        return 2
    round_dir, command, rest = Path(sys.argv[1]), sys.argv[2], sys.argv[3:]
    if command == "dump":
        for process, (sw, sh, items) in dump(round_dir).items():
            print(f"== {process} ({sw:.0f}x{sh:.0f} points, {len(items)} elements)")
            for x, y, w, h, cls, label, value in items:
                print(f"  {x:5.0f} {y:5.0f} {w:5.0f} {h:5.0f}  {cls:32.32s} {label!r} {value!r}" if value else
                      f"  {x:5.0f} {y:5.0f} {w:5.0f} {h:5.0f}  {cls:32.32s} {label!r}")
        return 0
    if command == "tap" and rest:
        nth = int(rest[rest.index("--nth") + 1]) if "--nth" in rest else 0
        found = find(dump(round_dir), rest[0], exact="--exact" in rest)
        if len(found) <= nth:
            print(f"ui: nothing on the screen says {rest[0]!r}")
            return 1
        process, (x, y, w, h, cls, label, value), sw, sh = found[nth]
        nx, ny = (x + w / 2) / sw, (y + h / 2) / sh
        print(f"ui: tap {label or value!r} ({cls} in {process}) at {nx:.3f} {ny:.3f}")
        rsh(round_dir, "/annibale/bin/rwtouch", "tap", f"{nx:.4f}", f"{ny:.4f}")
        return 0
    if command == "accessibility":
        rsh(round_dir, "notify", "com.annibale.ax.on")
        print("ui: application accessibility asked for; applications started from now on list SwiftUI elements")
        return 0
    if command == "wait" and rest:
        deadline = time.monotonic() + (float(rest[1]) if len(rest) > 1 else 30)
        while time.monotonic() < deadline:
            if find(dump(round_dir), rest[0]):
                print(f"ui: {rest[0]!r} is on the screen")
                return 0
            time.sleep(2)
        print(f"ui: {rest[0]!r} did not appear")
        return 1
    if command == "shot" and rest:
        run = round_dir / "run"
        raw = tour.take_shot(run)
        if raw is None:
            print("ui: no screenshot came back")
            return 1
        rgb = tour.pixels(raw)[:, :, ::-1].copy()
        png = run / f"{rest[0]}.png"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s",
                        f"{tour.WIDTH}x{tour.HEIGHT}", "-i", "-", str(png)], input=rgb.tobytes(), check=True)
        print(f"ui: {png}")
        return 0
    print(__doc__.strip())
    return 2


if __name__ == "__main__":
    sys.exit(main())
