#!/usr/bin/env python3
"""Resolve raw user pcs of a thread dump against the split dyld cache, offline.

usage: tools/k90auto/tdsym.py --slide HEX [--exec-base HEX] [--cache DIR] [--no-symbols] [PC ...]

The kernel's thread dump ("dump PID" through annsh, or a freeze/flow-gap dump) prints per-thread
pcs and "bt" frames as raw hex. The pcs live in the shared cache, which is slid per boot; the dump
carries the slide on its "tl: td PID slide 0x..." line and the main binary's load base on its
"tl: td PID exec 0x..." line. Given those two values this resolver turns each pc into
image+0xOFFSET, the form that resolves against the cache files without any further input:

  - a pc whose unslid value (pc - slide) lands in the shared region prints as
    `image+0xOFFSET`, with `(export+0xNN)` appended when the image exports a symbol at or
    below it (--no-symbols skips that);
  - a pc above the cache but within EXEC_SPAN of the exec base prints as `exec+0xOFFSET`
    (the main binary; dyld-mapped libraries in the same span cannot be told apart without
    the process's own image list, so the label is a best effort);
  - anything else prints unchanged.

Input is either pcs as arguments (one resolution per line) or text on stdin, which is rewritten
token by token: every hex token, 0x-prefixed or bare, is replaced by its resolution and the rest
of the line passes through as it was, so a dump can be annotated in place:

  grep "tl: td 29 " merged.log | python3 tools/k90auto/tdsym.py --slide 0x1504c000 --exec-base 0x10205c000

The method is the cache-slide one of out/goal-1124/batch5/symbolicate_tlt.py; prof.py does the
same resolution inside a round's logs, this script is the standalone form of it.
"""
import argparse
import bisect
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
WORKSPACE = HERE.parents[1]
sys.path.insert(0, str(WORKSPACE / "hackios-xnu-kernel/tools/dsc"))
import cache as dsc_cache  # noqa: E402
import macho  # noqa: E402

CACHE_DIR = WORKSPACE / "hackios-xnu-kernel/ios26/23G90__iPhone18,3"
EXEC_SPAN = 64 << 20      # how far above the exec base a main-binary frame is still believed

HEXTOKEN = re.compile(r"\b(?:0x)?[0-9a-fA-F]{6,16}\b")


class Resolver:
    def __init__(self, slide, exec_base=None, cache_dir=CACHE_DIR, symbols=True):
        self.cache = dsc_cache.Cache(str(cache_dir))
        self.slide = slide
        self.exec_base = exec_base
        self.symbols = symbols
        self.exports = {}

    def export_line(self, image, address):
        if not self.symbols:
            return None
        if image.path not in self.exports:
            table = []
            try:
                for name, kind, value, _extra in macho.exports(self.cache, image):
                    if kind == "regular" and value:
                        table.append((value, name))
            except Exception:
                pass
            table.sort()
            starts = []
            try:
                starts = macho.function_starts(self.cache, image)
            except Exception:
                pass
            self.exports[image.path] = (table, starts)
        table, starts = self.exports[image.path]
        i = bisect.bisect_right(table, (address, "￿")) - 1
        if i < 0:
            return None
        # A function start closer than the export means the frame is inside a private
        # function, which the export's name only neighbours (the cache's own names are redacted).
        note = ""
        j = bisect.bisect_right(starts, address) - 1
        if j >= 0 and starts[j] > table[i][0]:
            note = " private-fn"
        return f"{table[i][1]}+{address - table[i][0]:#x}{note}"

    def resolve(self, pc):
        """One pc to its image+0xOFFSET form, or None when neither cache nor exec claims it."""
        unslid = pc - self.slide
        if self.cache.shared_region_start <= unslid < self.cache.shared_region_start + self.cache.shared_region_size:
            try:
                image = self.cache.image_of(unslid)
            except Exception:
                image = None
            if image is not None:
                offset = unslid - image.address
                out = f"{image.name}+{offset:#x}"
                sym = self.export_line(image, unslid)
                return f"{out} ({sym})" if sym else out
        if self.exec_base is not None and self.exec_base <= pc < self.exec_base + EXEC_SPAN:
            return f"exec+{pc - self.exec_base:#x}"
        return None

    def resolve_token(self, token):
        try:
            pc = int(token, 16)
        except ValueError:
            return token
        return self.resolve(pc) or token


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--slide", type=lambda s: int(s, 16), required=True,
                    help="the boot's shared cache slide, from the dump's \"tl: td PID slide\" line")
    ap.add_argument("--exec-base", type=lambda s: int(s, 16),
                    help="the main binary's load base, from the dump's \"tl: td PID exec\" line")
    ap.add_argument("--cache", type=Path, default=CACHE_DIR)
    ap.add_argument("--no-symbols", action="store_true", help="image+offset only, no export names")
    ap.add_argument("pcs", nargs="*", help="pcs as hex; with none, stdin is rewritten token by token")
    args = ap.parse_args()
    if not args.cache.is_dir():
        print(f"tdsym: no cache at {args.cache}", file=sys.stderr)
        return 1
    resolver = Resolver(args.slide, args.exec_base, args.cache, not args.no_symbols)
    if args.pcs:
        for token in args.pcs:
            pc = int(token, 16)
            print(f"{pc:#x}  {resolver.resolve(pc) or '(not in the cache, nor the exec span)'}")
        return 0
    for line in sys.stdin:
        print(HEXTOKEN.sub(lambda m: resolver.resolve_token(m.group(0)), line), end="")
    return 0


if __name__ == "__main__":
    sys.exit(main())
