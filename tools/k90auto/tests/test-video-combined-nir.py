#!/usr/bin/env python3
"""Test production NV12 lowering using an existing native Mesa build and probe bitcode."""
import argparse
import json
from pathlib import Path
import shlex
import subprocess

ROOT = Path(__file__).resolve().parents[3]
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("build", type=Path, help="native Mesa build directory")
parser.add_argument("bitcode", type=Path, help="combined_sample.bc from video_combined_test.metallib")
parser.add_argument("output", type=Path, help="local test output directory")
args = parser.parse_args()
build, output = args.build.resolve(), args.output.resolve()
output.mkdir(parents=True, exist_ok=True)
commands = json.loads((build / "compile_commands.json").read_text())
compile_args = shlex.split(next(item["command"] for item in commands
                               if item["file"].endswith("/air_metal.c")))
old_object = compile_args[compile_args.index("-o") + 1]
compile_args[compile_args.index("-o") + 1] = str(output / "test.o")
compile_args[-1] = str(ROOT / "hackios-xnu-userland/tools/mesa/air/air_yuv_test.c")
compile_args += ["-fsanitize=address,undefined", "-g"]
with (output / "compile.log").open("w") as log:
    subprocess.run(compile_args, cwd=build, stdout=log, stderr=subprocess.STDOUT, check=True)
link_commands = subprocess.check_output(
    ["ninja", "-C", str(build), "-t", "commands",
     "src/gallium/drivers/freedreno/libannibaleair.dylib"], text=True).splitlines()
link_args = [str(output / "test.o") if item == old_object else item
             for item in shlex.split(link_commands[-1])
             if item not in ("-shared", "-dynamiclib")
             and not item.startswith(("-Wl,-install_name", "-Wl,-compatibility_version",
                                      "-Wl,-current_version"))]
link_args[link_args.index("-o") + 1] = str(output / "test")
link_args += ["-fsanitize=address,undefined"]
with (output / "link.log").open("w") as log:
    subprocess.run(link_args, cwd=build, stdout=log, stderr=subprocess.STDOUT, check=True)
result = subprocess.run([str(output / "test"), str(args.bitcode.resolve()),
                         str(args.bitcode.resolve().with_name("combined_fragment.bc"))],
                        capture_output=True, text=True)
(output / "run.log").write_text(result.stdout + result.stderr)
print(result.stdout + result.stderr, end="")
raise SystemExit(result.returncode)
