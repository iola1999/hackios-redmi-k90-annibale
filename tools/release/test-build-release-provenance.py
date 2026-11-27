#!/usr/bin/env python3
"""Verify ENG-19 third-party license, provenance and submodule commit checks in build-release.py."""
import importlib.util
from pathlib import Path
import unittest

HERE = Path(__file__).resolve().parent
SPEC = importlib.util.spec_from_file_location("build_release", HERE / "build-release.py")
BR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BR)


class BuildReleaseProvenanceTest(unittest.TestCase):
    def test_licenses_exist_and_include_trollstore(self):
        self.assertIn("TrollStore.LICENSE", BR.LICENSES)
        self.assertIn("qualcomm-gpu-firmware.NOTICE.txt", BR.LICENSES)
        for name, path in BR.LICENSES.items():
            self.assertTrue(path.is_file(), f"missing license file for {name}: {path}")

    def test_sources_includes_trollstore(self):
        commits = BR.sources(allow_dirty=True)
        for repo in ("workspace", "hackios-xnu-kernel", "hackios-xnu-userland", "TrollStore"):
            self.assertIn(repo, commits)
            self.assertTrue(len(commits[repo]) >= 40, f"bad commit hash for {repo}: {commits[repo]}")

    def test_third_party_provenance_and_firmware_disjoint(self):
        self.assertTrue(set(BR.VENDOR_FIRMWARE).isdisjoint(BR.RELEASE_FIRMWARE))
        prov = BR.THIRD_PARTY_PROVENANCE
        for key in (
            "hackios-xnu-kernel/prebuilt/uefi/mkbootimg.py",
            "hackios-xnu-kernel/prebuilt/avb/avbtool.py",
            "TrollStore",
            "qualcomm-gpu-firmware",
            "apfs-tool",
            "vendor-firmware-local-extract",
        ):
            self.assertIn(key, prov)
        self.assertEqual(set(prov["apfs-tool"]["files"]), set(BR.APFS_TOOLS))
        self.assertEqual(set(prov["vendor-firmware-local-extract"]["files"]), set(BR.VENDOR_FIRMWARE))
        for item in prov.values():
            for field in ("license_file", "notice_file"):
                if field in item:
                    fname = Path(item[field]).name
                    self.assertIn(fname, BR.LICENSES)


if __name__ == "__main__":
    unittest.main()
