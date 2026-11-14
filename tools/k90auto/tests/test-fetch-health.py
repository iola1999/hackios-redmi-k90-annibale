#!/usr/bin/env python3
"""Offline tests for file-transfer validation and frame-counter reports."""
import base64
import contextlib
import importlib.util
import io
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent.parent


def load(name):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


fetch = load("fetch")
health = load("health")


def reply(body, status=0, error=""):
    return subprocess.CompletedProcess(["rsh.py"], status, body, error)


class FetchTests(unittest.TestCase):
    def invoke(self, replies, previous=None):
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / "received.bin"
            partial = target.with_name(target.name + ".partial")
            if previous is not None:
                target.write_bytes(previous)
            output, errors = io.StringIO(), io.StringIO()
            with patch.object(fetch.sys, "argv", ["fetch.py", "test-round", "/test", str(target)]), \
                    patch.object(fetch.subprocess, "run", side_effect=replies) as run, \
                    contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
                status = fetch.main()
            return status, target.read_bytes() if target.exists() else None, \
                partial.read_bytes() if partial.exists() else None, \
                output.getvalue() + errors.getvalue(), run.call_args_list

    def assert_rejected(self, response, diagnostic):
        for previous in (None, b"existing artifact"):
            with self.subTest(previous=previous):
                status, data, partial, output, calls = self.invoke([response], previous)
                self.assertEqual(status, 1)
                self.assertEqual(data, previous)
                self.assertEqual(partial, b"")
                self.assertIn(diagnostic, output)
                self.assertIn("incomplete", output)
                self.assertEqual(len(calls), 1)

    def test_command_failure_preserves_diagnostics_and_target(self):
        for status in (1, 2, 3):
            with self.subTest(status=status):
                response = reply("cat 0 YWJj\ncat end 3 next 3\n", status,
                                 "rsh: command did not complete\n")
                self.assert_rejected(response, "rsh: command did not complete")

    def test_bytes_beyond_advertised_size_are_rejected(self):
        self.assert_rejected(reply("cat 0 YWJj\ncat end 2 next 3\n"), "size 2")

    def test_no_progress_stops_before_another_request(self):
        self.assert_rejected(reply("cat end 1 next 0\n"), "no progress")

    def test_invalid_base64_is_reported(self):
        for encoded in ("YWJj!", "YQ", "!!!!", "YWJj\ufffd"):
            with self.subTest(encoded=encoded):
                self.assert_rejected(reply(f"cat 0 {encoded}\ncat end 3 next 3\n"), "base64")

    def test_missing_footer_is_rejected(self):
        self.assert_rejected(reply("cat 0 YWJj\n"), "no end line")

    def test_missing_chunk_is_rejected(self):
        self.assert_rejected(reply("cat 3 YWJj\ncat end 6 next 6\n"), "expected offset 0")

    def test_missing_chunk_preserves_contiguous_prefix(self):
        for previous in (None, b"existing artifact"):
            with self.subTest(previous=previous):
                status, data, partial, output, calls = self.invoke([
                    reply("cat 0 YWJj\ncat end 12 next 3\n"),
                    reply("cat 3 ZGVm\ncat 9 amts\ncat end 12 next 12\n")], previous)
                self.assertEqual(status, 1)
                self.assertEqual(data, previous)
                self.assertEqual(partial, b"abcdef")
                self.assertIn("expected offset 6, got 9", output)
                self.assertIn("incomplete: saved 6 verified bytes", output)
                self.assertIn("received.bin.partial", output)
                self.assertEqual([c.args[0][-1] for c in calls], ["0", "3"])

    def test_invalid_base64_preserves_contiguous_prefix(self):
        for previous in (None, b"existing artifact"):
            with self.subTest(previous=previous):
                status, data, partial, output, calls = self.invoke([
                    reply("cat 0 YWJj\ncat end 9 next 3\n"),
                    reply("cat 3 ZGVm\ncat 6 !!!!\ncat end 9 next 9\n")], previous)
                self.assertEqual(status, 1)
                self.assertEqual(data, previous)
                self.assertEqual(partial, b"abcdef")
                self.assertIn("invalid base64 at offset 6", output)
                self.assertIn("incomplete: saved 6 verified bytes", output)
                self.assertEqual([c.args[0][-1] for c in calls], ["0", "3"])

    def test_failure_after_progress_keeps_existing_target(self):
        for previous in (None, b"existing artifact"):
            with self.subTest(previous=previous):
                status, data, partial, output, calls = self.invoke([
                    reply("cat 0 YWJj\ncat end 6 next 3\n"),
                    reply("cat 3 ZGVm\ncat end 6 next 6\n", 2,
                          "rsh: loader refused command\n")], previous)
                self.assertEqual(status, 1)
                self.assertEqual(data, previous)
                self.assertEqual(partial, b"abc")
                self.assertIn("rsh: loader refused command", output)
                self.assertIn("incomplete: saved 3 verified bytes", output)
                self.assertEqual([c.args[0][-1] for c in calls], ["0", "3"])

    def test_invalid_footer_preserves_only_completed_responses(self):
        responses = (
            ("cat 3 ZGVm\n", "no end line"),
            ("cat 3 ZGVm\ncat end 9 next 7\n", "no end line"),
            ("cat 3 ZGVm\ncat end 5 next 6\n", "size 5"),
            ("cat end 9 next 3\n", "no progress"),
        )
        for body, diagnostic in responses:
            for previous in (None, b"existing artifact"):
                with self.subTest(body=body, previous=previous):
                    status, data, partial, output, calls = self.invoke([
                        reply("cat 0 YWJj\ncat end 9 next 3\n"), reply(body)], previous)
                    self.assertEqual(status, 1)
                    self.assertEqual(data, previous)
                    self.assertEqual(partial, b"abc")
                    self.assertIn(diagnostic, output)
                    self.assertIn("incomplete: saved 3 verified bytes", output)
                    self.assertEqual([c.args[0][-1] for c in calls], ["0", "3"])

    def test_partial_write_failure_keeps_original_diagnostic_and_status(self):
        with patch.object(fetch.Path, "write_bytes", side_effect=OSError("write denied")):
            status, data, partial, output, calls = self.invoke([reply("cat 3 YWJj\n")])
        self.assertEqual(status, 1)
        self.assertIsNone(data)
        self.assertIsNone(partial)
        self.assertIn("expected offset 0", output)
        self.assertIn("incomplete: could not write", output)
        self.assertIn("write denied", output)
        self.assertEqual(len(calls), 1)

    def test_successful_file_uses_contiguous_chunk_offsets(self):
        payload = bytes(range(100))
        replies = []
        for offset in (0, 48, 96):
            chunk = payload[offset:offset + 48]
            encoded = base64.b64encode(chunk).decode("ascii")
            replies.append(reply(f"cat {offset} {encoded}\ncat end 100 next {offset + len(chunk)}\n"))
        status, data, partial, output, calls = self.invoke(replies, b"older file")
        self.assertEqual(status, 0)
        self.assertEqual(data, payload)
        self.assertIsNone(partial)
        self.assertNotIn("incomplete", output)
        self.assertEqual([c.args[0][-1] for c in calls], ["0", "48", "96"])

    def test_empty_file_is_valid(self):
        status, data, partial, output, calls = self.invoke([reply("cat end 0 next 0\n")])
        self.assertEqual(status, 0)
        self.assertEqual(data, b"")
        self.assertIsNone(partial)
        self.assertNotIn("incomplete", output)
        self.assertEqual(len(calls), 1)


class CounterResetTests(unittest.TestCase):
    def resets(self, numbers):
        text = "\n".join(f"tl: s {number} backboardd at {second * 1000000}"
                         for second, number in enumerate(numbers, 1))
        return health.restarts(text)

    def test_counter_is_compared_with_immediately_previous_value(self):
        self.assertEqual(self.resets([1, 100, 2]), [3.0])

    def test_each_reset_is_reported_after_the_counter_grows_again(self):
        self.assertEqual(self.resets([1, 100, 2, 50, 3]), [3.0, 5.0])

    def test_growth_duplicates_and_empty_input_have_no_resets(self):
        for numbers in ([], [1], [1, 2, 100], [1, 100, 100, 101]):
            with self.subTest(numbers=numbers):
                self.assertEqual(self.resets(numbers), [])


if __name__ == "__main__":
    unittest.main()
