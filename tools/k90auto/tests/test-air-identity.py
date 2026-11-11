#!/usr/bin/env python3
"""Exercise the package's AIR library and reflection ABI checks without building an image."""
import ast
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

SOURCE = Path(__file__).resolve().parents[1] / "package.py"


class AirIdentityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tree = ast.parse(SOURCE.read_text())
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
        start = next(i for i, node in enumerate(main.body)
                     if any(isinstance(part, ast.Name) and part.id == "AIR_RECORD" for part in ast.walk(node)))
        statements = []
        for node in main.body[start:]:
            statements.append(node)
            if any(isinstance(part, ast.Name) and isinstance(part.ctx, ast.Store) and part.id == "air_sources"
                   for part in ast.walk(node)):
                break
        else:
            raise AssertionError("AIR source record assignment is missing")
        cls.check = compile(ast.Module(body=statements, type_ignores=[]), str(SOURCE), "exec")

    def invoke(self, *, missing_record=False, library_mismatch=False, missing_abi=False, abi_mismatch=False):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            air = root / "libannibaleair.dylib"
            air.write_bytes(b"test AIR library")
            header = root / "tools/userland-driver/air_metal_reflection.h"
            header.parent.mkdir(parents=True)
            header.write_bytes(b"test reflection ABI")
            digest = lambda path: hashlib.sha256(Path(path).read_bytes()).hexdigest()
            record = {"library_sha256": "0" * 64 if library_mismatch else digest(air),
                      "source_sha256:air_metal.c": "test-source",
                      "tree_sha256:air_metal_reflection.h": "0" * 64 if abi_mismatch else digest(header)}
            if missing_abi:
                del record["tree_sha256:air_metal_reflection.h"]
            record_path = root / "air-build-record.json"
            if not missing_record:
                record_path.write_text(json.dumps(record))
            namespace = {"AIR_RECORD": record_path, "air": air, "SRC_ROOT": root,
                         "sha": digest, "json": json, "hashlib": hashlib}
            try:
                exec(self.check, namespace)
            except AssertionError:
                return False, namespace
            return True, namespace

    def test_matching_library_and_abi_keep_source_record(self):
        accepted, values = self.invoke()
        self.assertTrue(accepted)
        self.assertEqual(values["air_source"], "test-source")
        self.assertIn("tree_sha256:air_metal_reflection.h", values["air_sources"])

    def test_missing_build_record_is_rejected(self):
        self.assertFalse(self.invoke(missing_record=True)[0])

    def test_mismatched_library_is_rejected(self):
        self.assertFalse(self.invoke(library_mismatch=True)[0])

    def test_missing_reflection_abi_is_rejected(self):
        self.assertFalse(self.invoke(missing_abi=True)[0])

    def test_mismatched_reflection_abi_is_rejected(self):
        self.assertFalse(self.invoke(abi_mismatch=True)[0])


if __name__ == "__main__":
    unittest.main()
