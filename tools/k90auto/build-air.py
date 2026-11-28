#!/usr/bin/env python3
"""Build libannibaleair.dylib from the kernel repo's AIR sources, for the arm64e iOS 26 tree.

The arm64e build only reads its own copy of the sources, at
out/ios26-resume/mesa-arm64e/mesa-26.2.5/src/compiler/air/, so an edit under
tools/mesa/air/ does nothing until it is copied there. Nothing warns when it is not
copied: the build succeeds, the library is a valid library, and the only sign is a
field missing from a log 420 seconds later. So this program copies first, refuses to
build when the two sides disagree after the copy, and records both source hashes and
the library hash.

usage: tools/k90auto/build-air.py [--check]

--check only reports whether the two source trees agree and what the library holds.
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
WORKSPACE = REPO / "hackios-xnu-kernel"
SRC = (WORKSPACE / "tools/mesa/air") if (WORKSPACE / "tools/mesa/air").is_dir() else (REPO / "hackios-xnu-userland/tools/mesa/air")
TREE = WORKSPACE / "out/ios26-resume/mesa-arm64e"
MESA = TREE / "mesa-26.2.5/src/compiler/air"
BUILD = TREE / "build"
LIB = BUILD / "src/gallium/drivers/freedreno/libannibaleair.dylib"
OUT = WORKSPACE / "out/ios26-resume/bbmetal-device/libannibaleair.dylib"
RECORD = TREE / "air-build-record.json"
TARGET = "src/gallium/drivers/freedreno/libannibaleair.dylib"
# The header a driver-side change is allowed to touch, the C file itself and the two files it
# includes that carry library entry points (copies and compute). Everything else in tools/mesa/air/
# is shared with the iOS 16.5 line and is not part of this library.
# Copied into the build tree and recorded by digest. air_to_nir.c is here because a change to it is
# what fixes the refused fragment pipeline: any file the build reads from this directory that is not
# listed would be copied by hand and silently left out of the library.
FILES = ["air_metal.c", "air_metal.h", "air_metal_render.h", "air_clear_plan.h", "air_metal_clear.inc",
         "air_to_nir.c", "air_globals.inc", "air_instruction.inc", "air_entry.inc", "air_private.h",
         "air_cfg.inc", "air_interface.inc", "air_ops.inc", "air_sampler.inc",
         "air_bitcode.c", "air_bitcode.h", "air_layout.c", "air_metallib.c",
         "air_module.c", "air_module.h", "air_module_function.inc", "air_module_metadata.inc", "air_print.c",
         "air_metal_copy.inc", "air_metal_copy.h", "air_metal_compute.inc", "air_intrinsics.c",
         "air_math_private.h", "air_metal_lowering.inc", "air_metal_resource_private.h",
         "air_link.inc", "air_stitch.inc", "air_stitch_test.c", "air_stitch_test.metal",
         "air_stitch_link_test.c", "nir_air.h", "air_call.inc",
         "air_metal_purgeable.h", "air_metal_purgeable.inc",
         "air_metal_texture.inc", "air_metal_texels.inc", "air_metal_fence.inc", "air_metal_state.inc",
         "air_metal_dispatch.inc", "air_metal_diag.inc", "air_metal_argbuf.inc", "air_metal_bind.inc",
         "air_metal_sampler.inc", "air_metal_reflect_vertex.inc", "air_metal_render_create.inc",
         "air_metal_render_draw.inc", "air_texture.inc", "air_llvm.inc", "air_argbuf.inc",
         "air_metal_depth_stencil.inc", "air_ptr_slot.inc", "air_ptr_phi.inc", "air_debug.inc",
         "air_run_gallium.inc", "air_run_compute.inc", "air_run.c",
         "air_metal_vertex_cache.inc", "air_metal_yuv.h", "air_metal_yuv.inc",
         "air_metal_formats.inc", "air_metal_allocation.inc", "air_yuv_test.c", "air_gep.inc",
         "air_metal_rgb2p.h", "air_metal_rgb2p.inc", "air_metal_rgb2p_private.h", "air_metal_bicubic.inc",
         "air_metal_nircache.inc", "air_reflection.c", "air_reflection.h", "air_metal_reflection.h",
         "air_simd.inc", "air_imageblock.inc", "air_metal_blend.inc",
         "air_metal_test.c", "air_metal_test_argbuf.inc", "air_metal_test_attrib.inc",
         "air_metal_test_blend.inc", "air_metal_test_depth.inc", "air_metal_test_draw.inc",
         "air_metal_test_index.inc", "air_metal_test_ms.inc",
         "air_reflection_test.c", "air_copy_test.c", "air_compute_limits_test.c", "air2nir.c", "meson.build"]

# The toolchain: a venv with meson 1.12.1 and the ninja from homebrew, with bison ahead of the
# system one because the frontend's parser needs it. The paths are part of the host image, not of
# the repository, so an environment that already has them can override all three.
VENV = os.environ.get("AIR_VENV", "/tmp/mesa-rebase/venv/bin")
BISON = os.environ.get("AIR_BISON", "/opt/homebrew/opt/bison/bin")
NINJA = os.environ.get("AIR_NINJA", "ninja")


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def strings(path):
    out = subprocess.run(["/usr/bin/strings", str(path)], capture_output=True, text=True).stdout
    return out


def main():
    check_only = "--check" in sys.argv
    record = {}
    # The tree has to be the one tools/mesa's patches make (mk-mesa.sh PREPARE=1, then
    # setup-mesa-arm64e.py, about a minute): a patch added or changed after the tree was made never
    # reaches the library otherwise, and nothing in the build shows it. mk-mesa.sh stamps the tree.
    patches = sorted(SRC.parent.glob("*.patch")) + sorted((SRC.parent / "rebase-26").glob("*.patch"))
    patches_sha = hashlib.sha256(b"".join(p.read_bytes() for p in patches)).hexdigest()
    stamp = MESA.parents[2] / ".annibale-patches"
    if not stamp.is_file() or stamp.read_text().strip() != patches_sha:
        message = (f"{TREE} was made from other patches than tools/mesa's: move it away, run PREPARE=1 "
                   "REBASE=26 tools/mk-mesa.sh in the container and tools/k90auto/setup-mesa-arm64e.py")
        if not check_only:
            raise SystemExit(message)
        print("out of sync: " + message)
    record["patches_sha256"] = patches_sha
    for name in FILES:
        src, tree = SRC / name, MESA / name
        assert src.is_file(), f"{src} is missing"
        same = tree.is_file() and digest(src) == digest(tree)
        record[f"source_sha256:{name}"] = digest(src)
        if not same:
            if check_only:
                print(f"out of sync: {name} (source {digest(src)[:16]}, tree "
                      f"{(digest(tree)[:16] if tree.exists() else 'absent')})")
            else:
                tree.parent.mkdir(parents=True, exist_ok=True)
                tree.write_bytes(src.read_bytes())
                print(f"copied {name} into the arm64e tree")

    if check_only:
        if LIB.is_file():
            print(f"library {LIB.stat().st_size} bytes, sha256 {digest(LIB)[:16]}")
        return 0

    for name in FILES:      # the copy above is what the build reads; prove it took
        assert digest(SRC / name) == digest(MESA / name), f"{name} did not reach the build tree"
        # Read back after the copy, so the record names the file the compiler read. Taken before it,
        # every build that had to copy recorded the previous version as the one compiled.
        record[f"tree_sha256:{name}"] = digest(MESA / name)

    # Every other file here is copied by hand when it changes, so an edit can reach tools/mesa/air
    # and never the build tree, and the library would be built from stale sources without a word.
    drifted = [path.name for path in sorted(SRC.iterdir())
               if path.is_file() and path.suffix != ".py"
               and (not (MESA / path.name).is_file() or digest(path) != digest(MESA / path.name))]
    assert not drifted, ("these files differ from the build tree: " + ", ".join(drifted) +
                         "; add them to FILES so the copy is automatic")

    env = dict(os.environ)
    env["PATH"] = f"{BISON}:{VENV}:" + env.get("PATH", "")
    # Mesa's isaspec generator writes encode.h in set iteration order, which follows Python's
    # per-process hash seed: without a fixed seed two builds of the same tree order its
    # statements differently and the library bytes differ.
    env["PYTHONHASHSEED"] = "0"
    built = subprocess.run([NINJA, "-C", str(BUILD), "-j8", TARGET], capture_output=True, text=True, env=env)
    if built.returncode != 0:
        sys.stderr.write(built.stdout[-4000:] + built.stderr[-2000:])
        raise SystemExit(f"ninja failed with {built.returncode}")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_bytes(LIB.read_bytes())
    sign = subprocess.run(["/usr/bin/codesign", "--force", "--sign", "-", str(OUT)],
                          capture_output=True, text=True)
    assert sign.returncode == 0, sign.stderr

    exports = subprocess.run(["/usr/bin/nm", "-gU", str(OUT)],
                             capture_output=True, text=True, check=True).stdout
    assert any(line.split()[-1:] == ["_rwa_compute_get_reflection"]
               for line in exports.splitlines()), "compute reflection query is missing from the AIR library"

    text = strings(OUT)
    record.update({
        "library": str(OUT.relative_to(WORKSPACE)),
        "library_bytes": OUT.stat().st_size,
        "library_sha256": digest(OUT),
        "signed": "adhoc",
        # every field the current instrumentation prints once somewhere in its format strings; a
        # caller that expects one checks it here rather than in a log 420 seconds later
        "holds": {name: name in text for name in (
            "resolve %llu", "batch cuts", "verts %llu", "calls %llu in", "clock pair adds",
            "perf flush totals", "phase marks off", "perf draw: timing on", "rwa draw:",
            "rwa shadow:", "ir3 cache[", "tl: x", "tl: y", "tl: z", "tl: z2", "tl: z3", "tl: z4", "tl: z5", "tl: z6", "tl: z7", "tl: z8", "tl: z9", "tl: za", "tl: zb", "tl: zc")},
    })
    RECORD.write_text(json.dumps(record, indent=2) + "\n")
    print(f"{OUT.relative_to(WORKSPACE)}: {record['library_bytes']} bytes, "
          f"sha256 {record['library_sha256'][:16]}")
    for name, held in record["holds"].items():
        print(f"  {'yes' if held else 'no '}  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
