#!/usr/bin/env python3
"""frame-split.py ROUND [HZ]: where each animation frame of a round spent its time (HZ: fb_hz, default 120).

Needs touch_lat=1. Per swap, from the panel driver's lines (tl: s, tl: v, tl: l:
MiniIOMobileFramebuffer.cpp) and backboardd's GPU submissions (tl: Q) between the swap before and this one:

  P        backboardd: SwapEnd of the frame before returned -> SwapEnd of this frame entered
  G        GPU: ready minus the later of the frame's first submission and the frame before being ready
  bw       ready -> the CPU copy beginning (the legacy `shown` field)
  C        copy beginning -> pixels in the panel's memory (done)
  panel_obs  done -> the observation of its hardware latch, an upper bound when tl: l is present
  blocked  how long SwapEnd waited for the frame before to be copied (fb_queue=1)

tl: l is emitted only after CTL_FLUSH reads clear. Its `at` field is the device-clock microsecond
observation, which can be later than the latch itself. Its `frame` field is INTF_FRAME_COUNT. A valid
counter delta determines both the beat count and the display interval (delta times the nominal beat);
`observed` retains the raw observation interval. Logs without latch lines retain the historical
copy-begin calculation, labelled `copy` here rather than being presented as measured display timing.

A frame is in an animation when it was shown less than 90 ms after the one before. The tables are
printed twice: for every animation frame, and for those in a gesture's main animation as gestures.py
takes it (from a touch down, 1.8 s for a Control Center pull, 600 ms for a swipe), which leaves out
the slow updates of a still screen that also come less than 90 ms apart. A frame of two beats or more
is put down to G over a beat, else P over a beat, else P + G + C over two beats (with fb_queue=1 one
frame's P waits for the copy of the frame before, so two frames share that budget). "serialized"
frames had the GPU done before SwapEnd: backboardd waited for the GPU first.
"""
import bisect
import collections
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import summary

PAUSE_US = 90000
BURST_GAP_US = 150000
MAX_COUNTER_SKIPS = 240


def q(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, int(p * len(xs)))] if xs else 0


def parse(text):
    swaps, shown, subs, latches = {}, {}, [], {}
    for m in re.finditer(r'tl: s (\d+) \d+ \d+ \S+ at (\d+)', text):
        swaps[int(m.group(1))] = int(m.group(2))
    for m in re.finditer(r'tl: v (\d+) ready (\d+) shown (\d+) done (\d+)', text):
        shown[int(m.group(1))] = tuple(int(x) for x in m.group(2, 3, 4))
    for m in re.finditer(r'tl: Q \d+ backboardd at (\d+): \d+ buffers, \d+ big, (\d+) words', text):
        subs.append((int(m.group(1)), int(m.group(2))))
    for m in re.finditer(r'tl: l (\d+) at (\d+) frame (\d+) source ctl_flush(?:\s|$)', text):
        latches[int(m.group(1))] = (int(m.group(2)), int(m.group(3)))
    subs = sorted(set(subs))
    return swaps, shown, subs, latches


def gesture_windows(text):
    """(from, to) device microseconds of each gesture's main animation, as gestures.py takes it."""
    downs = sorted({(int(m.group(3)), int(m.group(2))) for m in re.finditer(r'tl: p 1 \d+ (\d+) (\d+) at (\d+)', text)})
    return [(at, at + (1800000 if y / 65535 < 0.05 else 600000)) for at, y in downs]


def frames(swaps, shown, subs, latches, beat):
    times = [t for t, _ in subs]
    rows = []
    for n in sorted(shown):
        if n not in swaps or n - 1 not in swaps or n - 1 not in shown or n - 2 not in shown:
            continue
        ready, copy_at, done = shown[n]
        ready1, copy1, done1 = shown[n - 1]
        hardware = n in latches and n - 1 in latches
        counter = False
        if hardware:
            t, frame = latches[n]
            previous_t, previous_frame = latches[n - 1]
            observed = t - previous_t
            delta = (frame - previous_frame) & 0xffffffff
            counter = 0 < delta <= MAX_COUNTER_SKIPS
            interval = delta * beat if counter else observed
            slots = delta if counter else round(interval / beat)
        else:
            t = copy_at
            interval = observed = copy_at - copy1
            slots = round(interval / beat)
        if interval >= PAUSE_US:
            continue
        returned = max(swaps[n - 1], shown[n - 2][2])
        k0, k1 = bisect.bisect_right(times, returned), bisect.bisect_right(times, swaps[n])
        first = times[k0] if k1 > k0 else swaps[n]
        rows.append(dict(t=t, I=interval, observed=observed, P=swaps[n] - returned, G=ready - max(first, ready1),
                         bw=copy_at - ready, C=done - copy_at,
                         panel_obs=latches[n][0] - done if n in latches else 0,
                         blocked=max(0, done1 - swaps[n]), subs=k1 - k0,
                         words=sum(w for _, w in subs[k0:k1]), serialized=ready - swaps[n] < 500,
                         slots=slots, source='latch' if hardware else 'copy', counter=counter,
                         has_latch=n in latches))
    return rows


def table(name, group, total):
    if not group:
        return
    print(f"-- {name}: {len(group)} ({100 * len(group) / total:.0f}%)")
    for k in ('I', 'P', 'G', 'bw', 'C', 'blocked'):
        xs = [r[k] for r in group]
        print(f"   {k:8s} p10 {q(xs, .1) / 1e3:6.2f}  p50 {q(xs, .5) / 1e3:6.2f}  p90 {q(xs, .9) / 1e3:6.2f} ms")
    panel = [r['panel_obs'] for r in group if r['has_latch']]
    if panel:
        print(f"   panel_obs p10 {q(panel, .1) / 1e3:6.2f}  p50 {q(panel, .5) / 1e3:6.2f}  "
              f"p90 {q(panel, .9) / 1e3:6.2f} ms ({len(panel)} latched)")


def main():
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    beat = 1e6 / float(sys.argv[2]) if len(sys.argv) > 2 else 1e6 / 120
    text = summary.merged_log(summary.round_dir(sys.argv[1]) + '/run')
    rows = frames(*parse(text), beat)
    if not rows:
        raise SystemExit("no animation frames: was touch_lat=1 set?")
    windows = gesture_windows(text)
    report(rows, beat, f"{len(rows)} animation frames, beat {beat:.0f} us")
    touched = [r for r in rows if any(a < r['t'] <= b for a, b in windows)]
    if touched:
        report(touched, beat, f"\n{len(touched)} of them in {len(windows)} gesture windows", bursts=False)


def report(rows, beat, title, bursts=True):
    print(title)
    hardware = sum(r['source'] == 'latch' for r in rows)
    counter = sum(r['counter'] for r in rows)
    print(f"timing: {hardware} hardware-latch frames, {counter} frame-counter intervals, "
          f"{len(rows) - hardware} legacy copy-begin frames")
    table("1 beat", [r for r in rows if r['slots'] <= 1], len(rows))
    table("2 beats", [r for r in rows if r['slots'] == 2], len(rows))
    table("3+ beats", [r for r in rows if r['slots'] >= 3], len(rows))
    long = [r for r in rows if r['slots'] >= 2]
    cause = collections.Counter(
        'G over a beat' if r['G'] > beat else 'P over a beat' if r['P'] > beat else
        'P+G+C over two beats' if r['P'] + r['G'] + r['C'] > 2 * beat else 'other' for r in long)
    print("long frames:", ", ".join(f"{k} {v}" for k, v in cause.most_common()))
    print(f"serialized: {sum(r['serialized'] for r in rows)} frames, {sum(r['serialized'] for r in long)} of them long")
    print(f"G over a beat: {sum(r['G'] > beat for r in rows)} of {len(rows)} frames")
    print("by backboardd submissions in the frame: frames, G p50/p90 ms, words p50, long %")
    by = collections.defaultdict(list)
    for r in rows:
        by[min(r['subs'], 4)].append(r)
    for n, group in sorted(by.items()):
        print(f"   {n}{'+' if n == 4 else ' '} {len(group):5d}  {q([r['G'] for r in group], .5) / 1e3:5.2f} "
              f"{q([r['G'] for r in group], .9) / 1e3:5.2f}  {q([r['words'] for r in group], .5):6d}  "
              f"{100 * sum(r['slots'] >= 2 for r in group) / len(group):3.0f}")
    if not bursts:
        return
    print("animations of 40 frames or more: start s, frames, frames/s, P G50 G90 C bw p50 ms, 2-beat %, 3+ %")
    bursts, cur = [], []
    for r in rows:
        if cur and r['t'] - cur[-1]['t'] > BURST_GAP_US:
            bursts.append(cur)
            cur = []
        cur.append(r)
    bursts.append(cur)
    for b in (b for b in bursts if len(b) >= 40):
        f = lambda k, p: q([r[k] for r in b], p) / 1e3
        fps = len(b) / ((b[-1]['t'] - b[0]['t']) / 1e6)
        print(f"   {b[0]['t'] / 1e6:7.1f} {len(b):5d} {fps:6.1f}  {f('P', .5):5.2f} {f('G', .5):5.2f} {f('G', .9):5.2f} "
              f"{f('C', .5):5.2f} {f('bw', .5):5.2f}  {100 * sum(r['slots'] == 2 for r in b) / len(b):3.0f} "
              f"{100 * sum(r['slots'] >= 3 for r in b) / len(b):3.0f}")


if __name__ == '__main__':
    main()
