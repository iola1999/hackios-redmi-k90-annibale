#!/usr/bin/env python3
"""Offline checks for k90auto/frame-split.py's hardware-latch and legacy timing paths."""
import bisect
import contextlib
import importlib.util
import io
from pathlib import Path

TOOL = Path(__file__).resolve().parents[2] / "tools/k90auto/frame-split.py"
SPEC = importlib.util.spec_from_file_location("frame_split", TOOL)
frame_split = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(frame_split)
BEAT = 1e6 / 120


def synthetic_log():
    lines = []
    swaps = [5000, 9000, 19000, 37000, 54000]
    ready = [7000, 15000, 33000, 52000, 70000]
    copies = [8000, 16000, 34000, 53000, 71000]
    done = [8500, 18000, 36000, 55000, 73000]
    latched = [9000, 20000, 37000, 60000, 80000]
    frames = [99, 100, 102, 103, 105]
    for n in range(0, 5):
        lines.append(f"tl: Q {n} backboardd at {swaps[n] - 4000}: 1 buffers, 0 big, 100 words")
        lines.append(f"tl: s {n} 100 200 backboardd at {swaps[n]}")
        lines.append(f"tl: v {n} ready {ready[n]} shown {copies[n]} done {done[n]}")
        lines.append(f"tl: l {n} at {latched[n]} frame {frames[n]} source ctl_flush")
    return "\n".join(lines)


def parsed_rows(text):
    return frame_split.frames(*frame_split.parse(text), BEAT)


def legacy_frames(swaps, shown, subs, beat):
    """The pre-latch algorithm, retained here as the ablation reference."""
    times = [t for t, _ in subs]
    rows = []
    for n in sorted(shown):
        if n not in swaps or n - 1 not in swaps or n - 1 not in shown or n - 2 not in shown:
            continue
        ready, beat_at, done = shown[n]
        ready1, beat1, done1 = shown[n - 1]
        interval = beat_at - beat1
        if interval >= frame_split.PAUSE_US:
            continue
        returned = max(swaps[n - 1], shown[n - 2][2])
        k0, k1 = bisect.bisect_right(times, returned), bisect.bisect_right(times, swaps[n])
        first = times[k0] if k1 > k0 else swaps[n]
        rows.append(dict(t=beat_at, I=interval, P=swaps[n] - returned, G=ready - max(first, ready1),
                         bw=beat_at - ready, C=done - beat_at, blocked=max(0, done1 - swaps[n]),
                         subs=k1 - k0, words=sum(w for _, w in subs[k0:k1]),
                         serialized=ready - swaps[n] < 500, slots=round(interval / beat)))
    return rows


def without_latches(text):
    return "\n".join(line for line in text.splitlines() if not line.startswith("tl: l"))


def test_hardware_counter_and_units():
    rows = parsed_rows(synthetic_log())
    assert len(rows) == 3
    assert [r["slots"] for r in rows] == [2, 1, 2]
    assert all(r["source"] == "latch" and r["counter"] for r in rows)
    assert abs(rows[0]["I"] - 2 * BEAT) < 0.001 and rows[0]["observed"] == 17000
    # The observations span 23 ms, but the panel advanced once. The display interval is one nominal beat.
    assert abs(rows[1]["I"] - BEAT) < 0.001 and rows[1]["observed"] == 23000
    assert rows[1]["slots"] == 1
    assert rows[1]["panel_obs"] == 5000
    assert rows[1]["C"] == 2000 and rows[1]["bw"] == 1000


def test_counter_wrap_and_invalid_counter():
    text = synthetic_log().replace("frame 100 source", "frame 4294967294 source").replace(
        "frame 102 source", "frame 1 source")
    rows = parsed_rows(text)
    assert rows[0]["slots"] == 3 and rows[0]["counter"]
    text = synthetic_log().replace("frame 102 source", "frame 100 source")
    rows = parsed_rows(text)
    assert not rows[0]["counter"] and rows[0]["slots"] == 2


def test_legacy_copy_is_not_hardware_latch():
    text = without_latches(synthetic_log())
    text += "\ntl: l 4 at 90000 frame 106 source timer"
    rows = parsed_rows(text)
    assert len(rows) == 3
    assert all(r["source"] == "copy" and not r["counter"] for r in rows)
    assert [r["slots"] for r in rows] == [2, 2, 2]
    assert rows[-1]["panel_obs"] == 0 and not rows[-1]["has_latch"]

    reference = legacy_frames(*frame_split.parse(text)[:3], BEAT)
    legacy_keys = ("t", "I", "P", "G", "bw", "C", "blocked", "subs", "words", "serialized", "slots")
    for actual, expected in zip(rows, reference):
        assert {k: actual[k] for k in legacy_keys} == {k: expected[k] for k in legacy_keys}


def test_latch_ablation_preserves_pipeline_stages():
    latched = parsed_rows(synthetic_log())
    copy = parsed_rows(without_latches(synthetic_log()))
    for hardware, legacy in zip(latched, copy):
        for key in ("P", "G", "bw", "C", "blocked", "subs", "words", "serialized"):
            assert hardware[key] == legacy[key]
    assert [r["slots"] for r in latched] == [2, 1, 2]
    assert [r["slots"] for r in copy] == [2, 2, 2]


def test_report_names_timing_source():
    rows = parsed_rows(synthetic_log())
    out = io.StringIO()
    with contextlib.redirect_stdout(out):
        frame_split.report(rows, BEAT, "synthetic", bursts=False)
    text = out.getvalue()
    assert "3 hardware-latch frames, 3 frame-counter intervals, 0 legacy copy-begin frames" in text
    assert "panel_obs" in text and "(2 latched)" in text and "(1 latched)" in text


def main():
    test_hardware_counter_and_units()
    test_counter_wrap_and_invalid_counter()
    test_legacy_copy_is_not_hardware_latch()
    test_latch_ablation_preserves_pipeline_stages()
    test_report_names_timing_source()
    print("frame-split: hardware counter, microsecond intervals, legacy fallback and report: ok")


if __name__ == "__main__":
    main()
