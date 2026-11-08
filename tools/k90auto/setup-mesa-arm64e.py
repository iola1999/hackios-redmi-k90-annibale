#!/usr/bin/env python3
"""Create the arm64e Mesa build tree that build-air.py builds libannibaleair.dylib in.

The source is the tree `PREPARE=1 VERSION=26.2.5 SHA256=... REBASE=26 tools/mk-mesa.sh` leaves in
hackios-xnu-kernel/xnu-deps/build/mesa/mesa-26.2.5 (run in the hackios-dev container: the patch
step needs GNU patch). This program copies it, writes a cross file for Xcode's arm64e clang and the
iPhoneOS SDK, and runs meson setup with the options mk-mesa.sh uses. It refuses an existing
destination, so the tree a round was built from is never overwritten by accident.

usage: tools/k90auto/setup-mesa-arm64e.py [DEST]   (default hackios-xnu-kernel/out/ios26-resume/mesa-arm64e)
env:   AIR_VENV (meson 1.12.1, default /tmp/mesa-rebase/venv/bin), AIR_BISON (default homebrew bison)
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
KERNEL = HERE.parents[1] / "hackios-xnu-kernel"
SOURCE = KERNEL / "xnu-deps/build/mesa/mesa-26.2.5"
DEFAULT_DEST = KERNEL / "out/ios26-resume/mesa-arm64e"
VENV = Path(os.environ.get("AIR_VENV", "/tmp/mesa-rebase/venv/bin"))
BISON = Path(os.environ.get("AIR_BISON", "/opt/homebrew/opt/bison/bin")) / "bison"
# The same -D list as mk-mesa.sh's meson setup; only the cross file differs. shader-cache stays
# disabled: the libraries on the phone never had ir3's disk cache (patch 0015,
# /private/var/db/annibale-ir3cache), and with it on the second boot, the first one that reads the
# cache, was still all black about 1.5 minutes after unlock; whether the cache is why is not settled
# (docs/analysis/2026-11-09-ir3-disk-cache.md).
OPTIONS = ["--wrap-mode=nofallback", "--prefix=/annibale", "--libdir=lib", "--buildtype=release",
           "-Db_ndebug=true", "-Dplatforms=", "-Dgallium-drivers=softpipe,freedreno", "-Dfreedreno-kmds=msm",
           "-Dvulkan-drivers=", "-Dglx=disabled", "-Degl=disabled", "-Dgbm=disabled", "-Dosmesa=true",
           "-Dllvm=disabled", "-Dshared-glapi=enabled", "-Dgles1=disabled", "-Dgles2=enabled", "-Dopengl=true",
           "-Dzstd=disabled", "-Dxmlconfig=disabled", "-Dexpat=disabled", "-Dshader-cache=disabled",
           "-Dvalgrind=disabled", "-Dlibunwind=disabled", "-Dglvnd=disabled", "-Dvideo-codecs=", "-Dtools=",
           "-Dgallium-va=disabled", "-Dlmsensors=disabled", "-Dbuild-tests=false"]


def xcrun(*args):
    return subprocess.run(["/usr/bin/xcrun", *args], check=True, capture_output=True, text=True).stdout.strip()


def main():
    if len(sys.argv) > 2:
        sys.exit(__doc__)
    dest = Path(sys.argv[1]).resolve() if len(sys.argv) == 2 else DEFAULT_DEST
    if dest.exists():
        sys.exit(f"{dest} exists; move it away first (it may be the tree the current library was built in)")
    if not (SOURCE / "src/compiler/air").is_dir():
        sys.exit(f"{SOURCE} has no src/compiler/air: run PREPARE=1 REBASE=26 tools/mk-mesa.sh in the container first")
    for tool in (VENV / "meson", BISON):
        if not tool.exists():
            sys.exit(f"missing {tool} (set AIR_VENV / AIR_BISON)")

    sdk = xcrun("--sdk", "iphoneos", "--show-sdk-path")
    clang, clangxx = xcrun("--find", "clang"), xcrun("--find", "clang++")
    tools = {name: xcrun("--find", name) for name in ("ar", "ranlib", "strip")}
    target = ["-arch", "arm64e", "-isysroot", sdk, "-miphoneos-version-min=26.0"]

    dest.mkdir(parents=True)
    # mk-mesa.sh leaves the expected rejects of the old patches in its tree; they are not source
    shutil.copytree(SOURCE, dest / "mesa-26.2.5", symlinks=True, ignore=shutil.ignore_patterns("*.rej", "*.orig"))
    cross = dest / "cross.ini"
    cross.write_text(
        "[binaries]\n"
        f"bison = '{BISON}'\n"
        f"c = {[clang, *target]!r}\n"
        f"cpp = {[clangxx, *target, '-fuse-cxa-atexit']!r}\n"
        f"objc = {[clang, *target]!r}\n"
        f"ar = '{tools['ar']}'\nranlib = '{tools['ranlib']}'\nstrip = '{tools['strip']}'\n"
        "pkg-config = '/usr/bin/false'\n\n"
        "[host_machine]\nsystem = 'darwin'\nsubsystem = 'ios'\ncpu_family = 'aarch64'\ncpu = 'arm64e'\n"
        "endian = 'little'\n\n[properties]\nneeds_exe_wrapper = true\n")
    env = dict(os.environ, PATH=f"{VENV}:{BISON.parent}:{os.environ['PATH']}", PYTHONHASHSEED="0")
    with open(dest / "setup.log", "w") as log:
        subprocess.run([str(VENV / "meson"), "setup", str(dest / "build"), str(dest / "mesa-26.2.5"),
                        "--cross-file", str(cross), *OPTIONS], check=True, env=env, stdout=log, stderr=subprocess.STDOUT)
    print(f"setup-mesa-arm64e: {dest}; build the library with tools/k90auto/build-air.py")


if __name__ == "__main__":
    main()
