#!/usr/bin/env python3
"""hitch.py ROUND [--all] [--labels N:NAME,...] [--top N]: display intervals while a finger moves.

Needs touch_lat=1. For every interval between two swaps the panel latched (tl: l, INTF_FRAME_COUNT),
taken while a finger was down and had moved since the swap before (or within 300 ms of its lifting):
how many beats of the panel it lasted. gestures.py and frame-split.py leave out every interval of
90 ms or more as a pause; under a moving finger such an interval is a picture that stood still, and
it is counted here. --all takes every interval under a finger, moving or not (a held finger shows a
still picture, so long intervals there are not stalls).

--labels names the finger-down periods in order, "6:page-fast,6:page-slow": the first six periods are
page-fast, the next six page-slow; the table is then printed for each name as well, and periods after
the named ones are left out.

For intervals of three beats or more: which of P (backboardd, from the swap before returning to
SwapEnd), G (GPU) and C (the copy into the panel's memory) was over a beat, as frame-split.py takes
them, and the other programs that submitted to the GPU meanwhile.
"""
import bisect, collections, os, re, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import summary

BEAT = 1e6 / 120


def load(round_arg, moving=True):
    text = summary.merged_log(summary.round_dir(round_arg) + '/run')
    swaps = {int(m.group(1)): int(m.group(2)) for m in re.finditer(r'tl: s (\d+) \d+ \d+ \S+ at (\d+)', text)}
    shown = {int(m.group(1)): tuple(int(x) for x in m.group(2, 3, 4))
             for m in re.finditer(r'tl: v (\d+) ready (\d+) shown (\d+) done (\d+)', text)}
    latch = {int(m.group(1)): (int(m.group(2)), int(m.group(3)))
             for m in re.finditer(r'tl: l (\d+) at (\d+) frame (\d+) source ctl_flush', text)}
    subs = sorted({(int(m.group(3)), m.group(2), int(m.group(4)))
                   for m in re.finditer(r'tl: Q (\d+) (\S+) at (\d+): \d+ buffers, \d+ big, (\d+) words', text)})
    sub_t = [s[0] for s in subs]
    touches = sorted({(int(m.group(5)), int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)))
                      for m in re.finditer(r'tl: p (\d+) (\d+) (\d+) (\d+) at (\d+)', text)})
    periods, down = [], {}
    for at, typ, finger, x, y in touches:
        if typ == 1:
            down[finger] = at
        elif typ == 3 and finger in down:
            periods.append((down.pop(finger), at))
    starts = [p[0] for p in periods]
    moves = [(at, x, y) for at, typ, finger, x, y in touches if typ in (1, 2)]
    move_t = [m[0] for m in moves]

    def period_of(t):
        i = bisect.bisect_right(starts, t) - 1
        return i if i >= 0 and periods[i][0] <= t <= periods[i][1] + 300000 else None

    rows = []
    for n in sorted(latch):
        if n - 1 not in latch or n not in shown or n - 1 not in shown or n not in swaps or n - 1 not in swaps:
            continue
        t, frame = latch[n]
        t0, frame0 = latch[n - 1]
        delta = (frame - frame0) & 0xffffffff
        period = period_of(t)
        if not 0 < delta <= 1200 or period is None or period_of(t0) != period:
            continue
        if moving:
            # (the last sample at or before each end of the interval: where the finger was then)
            a, b = bisect.bisect_right(move_t, t0) - 1, bisect.bisect_right(move_t, t) - 1
            if a < 0 or b <= a or moves[a][1:] == moves[b][1:] or t - moves[b][0] > 30000:
                continue
        ready, copy_at, done = shown[n]
        returned = max(swaps[n - 1], shown[n - 2][2]) if n - 2 in shown else swaps[n - 1]
        k0, k1 = bisect.bisect_right(sub_t, returned), bisect.bisect_right(sub_t, swaps[n])
        mine = [s for s in subs[k0:k1] if s[1] == 'backboardd']
        first = mine[0][0] if mine else swaps[n]
        others = collections.Counter(s[1] for s in subs[bisect.bisect_right(sub_t, t0):bisect.bisect_right(sub_t, t)]
                                     if s[1] != 'backboardd')
        rows.append(dict(n=n, t0=t0, t=t, beats=delta, period=period, P=swaps[n] - returned,
                         G=ready - max(first, shown[n - 1][0]), C=done - copy_at, subs=len(mine), others=others))
    return text, periods, rows


def table(name, rows):
    total = len(rows)
    if not total:
        print(f'{name}: no intervals')
        return
    seconds = sum(r['beats'] for r in rows) * BEAT / 1e6
    share = lambda f: 100 * sum(1 for r in rows if f(r['beats'])) / total
    late = lambda limit: [r for r in rows if r['beats'] >= limit]
    every = lambda limit: f'{seconds / len(late(limit)):5.1f} s' if late(limit) else '   none'
    print(f'{name:16s} {total:5d} intervals {seconds:5.1f} s  {total / seconds:5.1f} fps  1 beat {share(lambda b: b == 1):4.0f}%  '
          f'2 {share(lambda b: b == 2):4.0f}%  3+ {share(lambda b: b >= 3):4.1f}%  '
          f'one of 25 ms+ every {every(3)}, 50 ms+ every {every(6)}, 92 ms+ every {every(11)}; '
          f'{sum(r["beats"] for r in late(3)) * BEAT / 1e6:4.1f} s in 25 ms+ ones')


def main():
    args = sys.argv[1:]
    moving = '--all' not in args
    labels, top = [], 12
    rounds = []
    i = 0
    while i < len(args):
        if args[i] == '--labels':
            for part in args[i + 1].split(','):
                count, _, name = part.partition(':')
                labels.extend([name] * int(count))
            i += 2
        elif args[i] == '--top':
            top = int(args[i + 1])
            i += 2
        elif args[i] == '--all':
            i += 1
        else:
            rounds.append(args[i])
            i += 1
    for round_arg in rounds:
        text, periods, rows = load(round_arg, moving)
        print(f'{os.path.basename(round_arg.rstrip("/"))}: {len(periods)} finger-down periods, '
              f'{sum(b - a for a, b in periods) / 1e6:.1f} s; intervals {"while the finger moved" if moving else "under a finger"}')
        if labels:
            rows = [r for r in rows if r['period'] < len(labels)]      # (touches after the named ones are another test's)
        table('all', rows)
        if labels:
            for name in dict.fromkeys(labels):
                table(name, [r for r in rows if labels[r['period']] == name])
        long = [r for r in rows if r['beats'] >= 3]
        cause = collections.Counter('+'.join(k for k in 'PGC' if r[k] > BEAT) or 'none over a beat' for r in long)
        print('  25 ms+ intervals by what was over a beat:', dict(cause.most_common()))
        others = sum((r['others'] for r in long), collections.Counter())
        print(f'  {sum(1 for r in long if r["others"])} of {len(long)} had other programs submit to the GPU:', dict(others.most_common(6)))
        for r in sorted(long, key=lambda r: -r['beats'])[:top]:
            label = labels[r['period']] if labels else ''
            print(f"    swap {r['n']:6d} at {r['t0'] / 1e6:8.2f} s {r['beats']:3d} beats  P {r['P'] / 1e3:7.1f} G {r['G'] / 1e3:6.1f} "
                  f"C {r['C'] / 1e3:5.1f} ms  {r['subs']} subs  {label:14s} {dict(r['others'])}")


main()
