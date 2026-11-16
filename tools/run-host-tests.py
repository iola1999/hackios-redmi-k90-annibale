#!/usr/bin/env python3
"""Run the host tests of hackios-xnu-kernel and hackios-xnu-userland without a device.

Each test runs as its own process from its repository root. fastboot and adb on PATH are
replaced by stubs that fail and record the call, and ANDROID_SERIAL is cleared: a test
that reaches for a device is reported as failed. A test exits 0 on success and 77 when an
optional input is missing (reported as SKIP); any other status is a failure.

Tests that compare production code with external sources run only when the inputs are set:
  ADRENO8_GRAPHICS_DIR       graphics-kernel sources, pin in test-adreno8-gpu.py (gpu, hfi-layout,
                             vrb, and global-fault/halt/hwcg-inherited/sqe-halt/sqe-markers/ucode-mapping)
  ADRENO8_KGSL_MODULE        annibale msm_kgsl.ko, SHA-256 in test-adreno8-gpu.py (gpu and the six above)
  ADRENO8_VENDOR_KERNEL_DIR  vendor kernel tree containing drivers/clk/qcom (clock)
  ADRENO8_MICODE_DIR         MiCode Xiaomi_Kernel_OpenSource annibale-w-oss tree (aperture, early-tlb)
  ADRENO8_MAINLINE_DIR       Linux adreno sources, pin in test-adreno8-ordinary.py (ordinary)
  IR3_MESA_ARCHIVE           mesa-26.2.5.tar.xz (ir3 output contracts; Python packages and tools
                             are listed in hackios-xnu-userland/tools/mesa/tests/README.md)
The XNU source that xnu26/apply.sh fetches enables test-video-scroll.py, test-fsid-lookup.py
and the kernel-flag build of test_mc_ce_crypto.py; APFS_IMAGE enables the image steps of
tools/apfs/run-tests.sh.

Usage: python3 tools/run-host-tests.py [SUBSTRING ...]   (run the tests whose path contains one)
"""
import argparse
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KERNEL = ROOT / "hackios-xnu-kernel"
USERLAND = ROOT / "hackios-xnu-userland"
SKIP = 77
TIMEOUT = 600

GPU_INPUTS = [("ADRENO8_GRAPHICS_DIR", "--vendor-dir"), ("ADRENO8_KGSL_MODULE", "--kgsl-module")]
INPUTS = {
    **{name: GPU_INPUTS for name in (
        "test-adreno8-gpu.py", "test-adreno8-global-fault.py", "test-adreno8-halt.py",
        "test-adreno8-hwcg-inherited.py", "test-adreno8-sqe-halt.py", "test-adreno8-sqe-markers.py",
        "test-adreno8-ucode-mapping.py")},
    "test-adreno8-hfi-layout.py": [("ADRENO8_GRAPHICS_DIR", "--vendor-dir")],
    "test-adreno8-vrb.py": [("ADRENO8_GRAPHICS_DIR", "--vendor-dir")],
    "test-adreno8-clock.py": [("ADRENO8_VENDOR_KERNEL_DIR", "--vendor-dir")],
    "test-adreno8-aperture.py": [("ADRENO8_MICODE_DIR", "--micode-dir")],
    "test-adreno8-early-tlb.py": [("ADRENO8_MICODE_DIR", "--micode-dir")],
    "test-adreno8-ordinary.py": [("ADRENO8_MAINLINE_DIR", "--mainline-dir")],
    "test-ir3-output-contracts.py": [("IR3_MESA_ARCHIVE", "--archive")],
}
LONG = {"test-ir3-output-contracts.py": 3600}

DEVICE_STUB = """#!/bin/sh
echo "$(basename "$0") $*" >> "$HOST_TESTS_DEVICE_LOG"
echo "run-host-tests: $(basename "$0") is not available to host tests" >&2
exit 1
"""


def discover():
    tests = []
    for repo, patterns in (
        (KERNEL, ["tools/tests/test[-_]*.py", "xnuloader/test_*.py", "tools/tests/guard-test.sh",
                  "tools/tests/guard-volume-test.sh", "tools/qmi-test/run.sh", "tools/wpa-test/run.sh"]),
        (USERLAND, ["tools/tests/test-*.py", "userland/test_*.py", "tools/apfs/test_wfs_random.py",
                    "tools/apfs/run-tests.sh", "tools/mesa/tests/test-*.py"]),
    ):
        for pattern in patterns:
            tests += [(repo, path) for path in sorted(repo.glob(pattern))]
    return tests


def run(repo, path, scratch, env):
    command = ["bash", str(path)] if path.suffix == ".sh" else [sys.executable, str(path)]
    missing = []
    for variable, flag in INPUTS.get(path.name, []):
        if os.environ.get(variable):
            command += [flag, os.environ[variable]]
        else:
            missing.append(variable)
    if missing:
        return SKIP, "missing " + ", ".join(missing), 0.0
    if path.name == "test-ir3-output-contracts.py":
        command += ["--work-dir", str(scratch / "ir3-output-contracts")]
    log = scratch / "device-calls.log"
    log.unlink(missing_ok=True)
    started = time.monotonic()
    try:
        result = subprocess.run(command, cwd=repo, env={**env, "HOST_TESTS_DEVICE_LOG": str(log)},
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                timeout=LONG.get(path.name, TIMEOUT))
        status, output = result.returncode, result.stdout
    except subprocess.TimeoutExpired as exc:
        status, output = "timeout", (exc.stdout or b"").decode(errors="replace")
    elapsed = time.monotonic() - started
    if log.exists():
        status, output = "device", output + "\ndevice tool called:\n" + log.read_text()
    return status, output, elapsed


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("filters", nargs="*", metavar="SUBSTRING")
    args = parser.parse_args()
    tests = [(repo, path) for repo, path in discover()
             if not args.filters or any(f in str(path.relative_to(ROOT)) for f in args.filters)]
    counts = {"PASS": 0, "SKIP": 0, "FAIL": 0}
    failed = []
    with tempfile.TemporaryDirectory(prefix="host-tests-") as directory:
        scratch = Path(directory)
        stubs = scratch / "bin"
        stubs.mkdir()
        for tool in ("fastboot", "adb"):
            (stubs / tool).write_text(DEVICE_STUB)
            (stubs / tool).chmod(0o755)
        env = {key: value for key, value in os.environ.items() if key != "ANDROID_SERIAL"}
        env.update(PATH=f"{stubs}:{os.environ.get('PATH', '')}", PYTHONDONTWRITEBYTECODE="1")
        for repo, path in tests:
            name = str(path.relative_to(ROOT))
            status, output, elapsed = run(repo, path, scratch, env)
            verdict = "PASS" if status == 0 else "SKIP" if status == SKIP else "FAIL"
            counts[verdict] += 1
            detail = next((line for line in output.splitlines() if line.startswith(("SKIP", "missing"))),
                          "") if verdict == "SKIP" else ""
            print(f"{verdict} {elapsed:6.1f}s {name}" + (f"  ({detail})" if detail else ""), flush=True)
            if verdict == "FAIL":
                failed.append(name)
                print("\n".join(f"    {line}" for line in output.rstrip().splitlines()[-30:]), flush=True)
    print(f"\n{counts['PASS']} passed, {counts['SKIP']} skipped, {counts['FAIL']} failed")
    for name in failed:
        print(f"FAIL {name}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
