#!/usr/bin/env python3
"""Record the K90's screen into an mp4 for as long as a test takes, while the kernel runs.

usage: tools/k90auto/screenrec.py ROUND_DIR start [--fps N] [--name NAME]
       tools/k90auto/screenrec.py ROUND_DIR stop [--name NAME]
       tools/k90auto/screenrec.py - record SECONDS [--fps N] [--out DIR]

The kernel (12377-rec1 and later) keeps every frame it shows, at most N a second (default 10, at most
30), at a third of the panel's size (385x836) in its 96 MiB recording buffer, over the oldest once the buffer is full, and flushes
each one as written (kern.annibale.rec_stream). The host reads the new frames from that buffer with
`oem stage` while the kernel runs, before the kernel goes over them: the buffer holds about 104 frames,
about 10 seconds at 10 frames a second.

A round: "start" arms the stream through rsh.py and writes ROUND_DIR/run/rec-NAME/stream.json;
run-auto.py, the only process that talks to the device during a round, reads the new frames on every
pass of its loop (serve()) and writes them to screen.mp4. "stop" disarms the stream and waits for
run-auto.py to read the last frames and close the file. Commands, taps and log snapshots go on as
usual meanwhile.

"-" record: no round, the phone running something else (a release, a round left running): this
process arms, reads and disarms by itself for SECONDS, and nothing else may talk to the device then.

Output in REC_DIR: screen.mp4 (constant rate N; a frame is repeated while the screen does not change),
each frame stamped with its estimated wall-clock time and the kernel's time in seconds; frames.jsonl
with one line per recorded frame (kernel nanoseconds, the estimated wall clock); stream.json. The wall
clock is the host's time of a read minus how long before it the newest frame was recorded, at most one
read interval late. To look at a stretch:
  ffmpeg -ss 12 -t 4 -i REC_DIR/screen.mp4 -vf fps=4,scale=201:-1,tile=8x2 sheet.png
"""
import argparse
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import queue
import tempfile
import threading
import time

HERE = Path(__file__).resolve().parent
HEADER = struct.Struct("<8sIIIIQ")      # MiniIOMobileFramebuffer.cpp struct rec_header
DEFAULT_BUFFER = 96 << 20               # kernels before rec_info's seventh field


def fastboot(*args, timeout=20):
    try:
        result = subprocess.run(["fastboot", "-s", "xnuloader", *map(str, args)], capture_output=True, text=True,
                                timeout=timeout)
        return result.returncode == 0 and "FAILED" not in result.stdout + result.stderr, result.stdout + result.stderr
    except subprocess.TimeoutExpired:
        return False, "timeout"


def stamp(rgb, width, height, text):
    """The text in the top left corner, white on black, so a frame read from the video says when it was."""
    from PIL import Image, ImageDraw

    image = Image.frombytes("RGB", (width, height), rgb)
    draw = ImageDraw.Draw(image)
    box = draw.textbbox((2, 2), text)
    draw.rectangle((0, 0, box[2] + 2, box[3] + 2), fill=(0, 0, 0))
    draw.text((2, 2), text, fill=(255, 255, 255))
    return image.tobytes()


class Stream:
    """One recording: reads the frames the kernel wrote since the last read and encodes them."""

    def __init__(self, rec_dir):
        self.dir = Path(rec_dir)
        info = json.loads((self.dir / "stream.json").read_text())
        self.address, self.fps = info["address"], info["fps"]
        self.width, self.height = info["width"], info["height"]
        self.frame_size = 8 + self.width * self.height * 3
        self.capacity = (info.get("buffer", DEFAULT_BUFFER) - HEADER.size) // self.frame_size
        self.next_slot = 0
        self.last_ns = -1
        self.began = None
        self.offset = None          # wall clock minus kernel seconds, the smallest seen
        self.previous = None        # (ns, stamped frame) waiting for the next frame to know how long it lasts
        self.start_ns = None
        self.ticks = 0
        self.count = 0
        self.index = (self.dir / "frames.jsonl").open("a")
        self.errors = (self.dir / "errors.log").open("a")
        self.encoder = subprocess.Popen(
            ["ffmpeg", "-loglevel", "error", "-y", "-f", "rawvideo", "-pixel_format", "rgb24",
             "-video_size", f"{self.width}x{self.height}", "-framerate", str(self.fps), "-i", "-",
             "-vf", "crop=trunc(iw/2)*2:trunc(ih/2)*2", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", "-pix_fmt", "yuv420p",
             "-movflags", "+frag_keyframe+empty_moov+default_base_moof", str(self.dir / "screen.mp4")],
            stdin=subprocess.PIPE, stderr=(self.dir / "ffmpeg.log").open("w"))
        # Encoding runs beside the caller's loop: after a long still stretch one new frame means many
        # repeated ones, and run-auto.py's commands and log reads must not wait for them.
        self.frames = queue.Queue()
        self.worker = threading.Thread(target=self.encode_all, daemon=True)
        self.worker.start()

    def read(self, offset, length, run=fastboot):
        with tempfile.NamedTemporaryFile(prefix="screenrec-", suffix=".bin") as staged:
            ok, output = run("oem", "stage", f"{self.address + offset:x}", f"{length:x}")
            if ok:
                ok, output = run("get_staged", staged.name)
            if not ok:
                self.errors.write(f"{time.time():.3f} read {offset:#x}+{length:#x}: {output.strip()[-200:]}\n")
                self.errors.flush()
                return None
            data = Path(staged.name).read_bytes()
            return data if len(data) == length else None

    def poll(self, run=fastboot):
        """Read and encode what is new; the number of frames read, or None when the header could not be read."""
        polled_at = time.time()
        header = self.read(0, HEADER.size, run)
        if header is None:
            return None
        magic, width, height, frames, oldest, began = HEADER.unpack(header)
        if magic != b"RWREC003" or (width, height) != (self.width, self.height):
            self.errors.write(f"{polled_at:.3f} header {magic!r} {width}x{height}\n")
            return None
        self.began = began
        wrapped = frames >= self.capacity
        current = oldest if wrapped else frames
        new = (current - self.next_slot) % self.capacity if wrapped else current - self.next_slot
        if new == 0 and self.last_ns < 0:
            return 0
        if self.last_ns >= 0:
            # The slot read last still holds that frame unless the kernel went round the whole buffer since.
            last = self.read(HEADER.size + ((self.next_slot - 1) % self.capacity) * self.frame_size, 8, run)
            if last is None:
                return None
            if struct.unpack("<Q", last)[0] != self.last_ns:
                new = self.capacity
                self.next_slot = current % self.capacity
                self.errors.write(f"{polled_at:.3f} the buffer went round before it was read: frames may be lost\n")
                self.errors.flush()
            elif new == 0:
                return 0
        slots, start = [], self.next_slot
        while new > 0:
            run_length = min(new, self.capacity - start)
            data = self.read(HEADER.size + start * self.frame_size, run_length * self.frame_size, run)
            if data is None:
                return None
            slots += [data[i * self.frame_size:(i + 1) * self.frame_size] for i in range(run_length)]
            start = (start + run_length) % self.capacity
            new -= run_length
        self.next_slot = current % self.capacity
        fresh = [(struct.unpack_from("<Q", slot)[0], slot[8:]) for slot in slots]
        fresh = [frame for frame in fresh if frame[0] > self.last_ns]
        if not fresh:
            return 0
        offset = polled_at - (began + fresh[-1][0]) / 1e9
        self.offset = offset if self.offset is None else min(self.offset, offset)
        for ns, rgb in fresh:
            self.frames.put((ns, rgb, began, self.offset))
        self.last_ns = fresh[-1][0]
        return len(fresh)

    def encode_all(self):
        failed = False
        while True:
            item = self.frames.get()
            if item is None:
                break
            if failed:
                continue
            try:
                self.encode(*item)
            except (OSError, ValueError) as error:     # ffmpeg gone: keep draining, say why once
                failed = True
                self.errors.write(f"{time.time():.3f} encoding stopped: {error!r}; see ffmpeg.log\n")
                self.errors.flush()
        try:
            if self.previous is not None and not failed:
                self.emit_until(self.previous[0] + 1)
            self.encoder.stdin.close()
        except OSError:
            pass
        self.encoder.wait()

    def encode(self, ns, rgb, began, offset):
        kernel_s = (began + ns) / 1e9
        wall = offset + kernel_s
        text = time.strftime("%H:%M:%S", time.localtime(wall)) + f".{int(wall * 10) % 10}  k{kernel_s:.2f}  #{self.count}"
        frame = stamp(rgb, self.width, self.height, text)
        self.index.write(json.dumps({"n": self.count, "ns": ns, "kernel_s": round(kernel_s, 4),
                                     "wall": round(wall, 2)}) + "\n")
        self.count += 1
        self.emit_until(ns)
        self.previous = (ns, frame)

    def emit_until(self, ns):
        """The previous frame for every output tick before NS (a constant frame rate out of irregular frames)."""
        if self.previous is None:
            return
        if self.start_ns is None:
            self.start_ns = self.previous[0]
        while self.start_ns + self.ticks * 1e9 / self.fps < ns:
            self.encoder.stdin.write(self.previous[1])
            self.ticks += 1

    def close(self):
        self.frames.put(None)
        self.worker.join()
        self.index.close()
        self.errors.close()
        (self.dir / "closed").write_text(json.dumps({"frames": self.count, "seconds": self.ticks / self.fps}) + "\n")


streams = {}


def serve(run_dir, run=fastboot):
    """For run-auto.py's loop: read every open recording of the round, and close the ones asked to stop."""
    for info in Path(run_dir).glob("rec-*/stream.json"):
        rec_dir = info.parent
        if (rec_dir / "closed").exists():
            continue
        stream = streams.get(rec_dir)
        if stream is None:
            stream = streams[rec_dir] = Stream(rec_dir)
        stopping = (rec_dir / "stop").exists()
        stream.poll(run)
        if stopping:
            stream.poll(run)
            stream.close()
            del streams[rec_dir]


def rsh(target, text):
    result = subprocess.run([sys.executable, str(HERE / "rsh.py"), target, text], capture_output=True, text=True)
    if result.returncode != 0:
        sys.exit(f"screenrec: {text}: {result.stdout}{result.stderr}")
    return result.stdout


def arm(target, fps, rec_dir):
    rsh(target, f"sysctl kern.annibale.rec_stream={fps}")
    info = rsh(target, "sysctl kern.annibale.rec_info")
    values = re.split(r"[:=]", info.strip().splitlines()[0], maxsplit=1)[-1].split()
    if len(values) < 6 or values[0] == "0x0" or values[5] != "1":
        rsh(target, "sysctl kern.annibale.rec_stream=0")
        sys.exit(f"screenrec: the stream did not start: {info.strip()}")
    rec_dir.mkdir(parents=True, exist_ok=False)
    stream = {"address": int(values[0], 16), "width": int(values[3]), "height": int(values[4]), "fps": fps,
              "started": time.time()}
    if len(values) >= 7:
        stream["buffer"] = int(values[6])
    (rec_dir / "stream.json").write_text(json.dumps(stream) + "\n")
    print(f"screenrec: {fps} frames a second into {rec_dir}", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("target", help="ROUND_DIR, or - for a phone no round is talking to")
    parser.add_argument("action", choices=["start", "stop", "record"])
    parser.add_argument("seconds", nargs="?", type=float)
    parser.add_argument("--fps", type=int, default=10)
    parser.add_argument("--name", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    if not 1 <= args.fps <= 30:
        sys.exit("screenrec: --fps is 1 to 30")
    if args.target == "-":
        if args.action != "record" or not args.seconds:
            sys.exit("screenrec: without a round, only 'record SECONDS'")
        rec_dir = Path(args.out or f"out/screenrec-{time.strftime('%m%d-%H%M%S')}")
        arm("-", args.fps, rec_dir)
        stream = Stream(rec_dir)
        end = time.monotonic() + args.seconds
        try:
            while time.monotonic() < end and not (rec_dir / "stop").exists():
                stream.poll()
                time.sleep(0.3)
        finally:
            rsh("-", "sysctl kern.annibale.rec_stream=0")
            stream.poll()
            stream.close()
        print(f"screenrec: {stream.count} frames, {stream.ticks / args.fps:.1f} s in {rec_dir / 'screen.mp4'}")
        return 0
    run = Path(args.target) / "run"
    if args.action == "start":
        arm(args.target, args.fps, run / f"rec-{args.name or time.strftime('%H%M%S')}")
        return 0
    if args.action != "stop":
        sys.exit("screenrec: with a round, 'start' or 'stop'")
    open_dirs = [d for d in sorted(run.glob("rec-*")) if (d / "stream.json").exists() and not (d / "closed").exists()]
    if args.name:
        open_dirs = [d for d in open_dirs if d.name == f"rec-{args.name}"]
    if not open_dirs:
        sys.exit("screenrec: no open recording in this round")
    rsh(args.target, "sysctl kern.annibale.rec_stream=0")
    for rec_dir in open_dirs:
        (rec_dir / "stop").write_text("\n")
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline and not all((d / "closed").exists() for d in open_dirs):
        time.sleep(0.5)
    for rec_dir in open_dirs:
        closed = rec_dir / "closed"
        print(f"screenrec: {rec_dir / 'screen.mp4'}: {closed.read_text().strip() if closed.exists() else 'not closed'}")
    return 0 if all((d / "closed").exists() for d in open_dirs) else 1


if __name__ == "__main__":
    sys.exit(main())
