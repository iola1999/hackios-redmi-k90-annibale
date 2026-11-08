#!/usr/bin/env python3
"""Tests of tools/release/localfiles.py: edit lists made back into the same bytes, and the checks."""
import importlib.util
import os
import plistlib
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("localfiles", HERE / "localfiles.py")
localfiles = importlib.util.module_from_spec(spec)
spec.loader.exec_module(localfiles)


class TestEdits(unittest.TestCase):
    def test_plist_round_trip(self):
        base = {"Label": "com.example.job", "RunAtLoad": True, "KeepAlive": 1,
                "ProgramArguments": ["/usr/libexec/job", "-v"],
                "MachServices": {"com.example.a": True, "com.example.b": True}, "Data": b"\x00\x01"}
        wanted = {"Label": "com.example.job", "KeepAlive": True,
                  "ProgramArguments": ["/usr/local/bin/job"],
                  "MachServices": {"com.example.a": True}, "StandardErrorPath": "/dev/console", "Data": b"\x00\x01"}
        edits = localfiles.plist_edits(base, wanted)
        made = localfiles.apply_edits(plistlib.loads(localfiles.dump_plist(base)), edits)
        self.assertEqual(localfiles.dump_plist(made), localfiles.dump_plist(wanted))
        # 1 and True compare equal in Python; the edit list must still carry the change of type
        self.assertIn(["set", ["KeepAlive"], True], edits)
        # only the changed parts are carried, not the untouched values of the base
        self.assertNotIn("Label", str(edits))

    def test_whole_value_replaced(self):
        self.assertEqual(localfiles.apply_edits({"a": 1}, localfiles.plist_edits({"a": 1}, [1, 2])), [1, 2])

    def test_skeleton_round_trip(self):
        base = "d\t755\t0\t0\t/private/var/a\nl\t/x\t/private/var/b\nd\t755\t0\t0\t/private/var/c\n"
        wanted = "d\t755\t0\t0\t/private/var/a\nl\t/y\t/private/var/b\nd\t755\t0\t0\t/private/var/c\nf\t644\t0\t0\t/p\t/q\n"
        edits = localfiles.skeleton_edits(base, wanted)
        self.assertEqual(localfiles.apply_skeleton(base, edits), wanted)
        self.assertNotIn("/private/var/a", str([e for e in edits if e[0] == "insert"]))


class TestMake(unittest.TestCase):
    def test_wrong_source_is_refused(self):
        source = localfiles.dump_plist({"Label": "x"})
        recipe = {"path": "LaunchDaemons/x.plist", "kind": "plist", "from": "os:x.plist",
                  "edits": [["set", ["RunAtLoad"], False]]}
        recipe["sha256"] = localfiles.sha256(localfiles.dump_plist({"Label": "x", "RunAtLoad": False}))
        made = localfiles.make(recipe, lambda ref: source, "", {}, None)
        self.assertEqual(plistlib.loads(made), {"Label": "x", "RunAtLoad": False})
        with self.assertRaises(ValueError):
            localfiles.make(recipe, lambda ref: localfiles.dump_plist({"Label": "y"}), "", {}, None)

    def test_cache_takes_the_image_jobs(self):
        apple = localfiles.dump_plist({"LaunchDaemons": {"/System/Library/LaunchDaemons/old.plist": {}},
                                       "VersionNumber": 1})
        jobs = {"new.plist": localfiles.dump_plist({"Label": "new"})}
        wanted = {"LaunchDaemons": {"/System/Library/LaunchDaemons/new.plist": {"Label": "new"}}, "VersionNumber": 1}
        recipe = {"path": "xpc/launchd.plist", "kind": "cache", "from": "os:launchd.plist", "edits": [],
                  "sha256": localfiles.sha256(localfiles.dump_plist(wanted))}
        self.assertEqual(plistlib.loads(localfiles.make(recipe, lambda ref: apple, "", jobs, None)), wanted)


class TestTree(unittest.TestCase):
    def test_digest_sees_modes_and_links(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "bin").mkdir()
            (root / "bin/tool").write_bytes(b"tool")
            os.chmod(root / "bin/tool", 0o755)
            os.symlink("/usr/local/lib/x", root / "link")
            first = localfiles.tree_digest(root)
            os.chmod(root / "bin/tool", 0o644)
            self.assertNotEqual(localfiles.tree_digest(root), first)
            os.chmod(root / "bin/tool", 0o755)
            self.assertEqual(localfiles.tree_digest(root), first)
            os.unlink(root / "link")
            os.symlink("/usr/local/lib/y", root / "link")
            self.assertNotEqual(localfiles.tree_digest(root), first)


if __name__ == "__main__":
    unittest.main()
