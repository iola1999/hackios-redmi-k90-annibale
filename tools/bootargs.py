#!/usr/bin/env python3
"""Write the catalog of boot-args the kernel reads, docs/analysis/boot-args.md, from the kernel sources.

usage: tools/bootargs.py [--check]

The sources are the tracked files of hackios-xnu-kernel under xnu/files/, xnu26/files/ and the added
lines of xnu26/patches/. A boot-arg is a string literal passed to PE_parse_boot_argn() or
PE_parse_boot_arg_str(); a name built at run time or read through a helper of its own is not found.
--check writes nothing and exits 1 when the catalog in the repository differs from the sources.
"""
import collections
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
KERNEL = ROOT / "hackios-xnu-kernel"
DOC = ROOT / "docs/analysis/boot-args.md"
CALL = re.compile(r'PE_parse_boot_arg(?:n|_str)\(\s*"([A-Za-z0-9_.\-]+)"')


def source_name(path):
    """xnu26/patches/42-osfmk%arm64%machine_routines.c.patch -> osfmk/arm64/machine_routines.c"""
    if path.startswith("xnu26/patches/"):
        return path.split("/")[-1].split("-", 1)[1][:-len(".patch")].replace("%", "/")
    return path.split("/", 2)[2]


def catalog():
    files = subprocess.run(["git", "-C", str(KERNEL), "ls-files", "xnu/files", "xnu26/files", "xnu26/patches"],
                           capture_output=True, text=True, check=True).stdout.split()
    readers = collections.defaultdict(set)
    for path in files:
        try:
            text = (KERNEL / path).read_text(errors="replace")
        except (IsADirectoryError, FileNotFoundError):
            continue
        for line in text.split("\n"):
            if path.endswith(".patch") and not line.startswith("+"):
                continue
            for match in CALL.finditer(line):
                readers[match.group(1)].add(source_name(path))
    lines = ["# 内核启动参数目录", "",
             "本文由 `tools/bootargs.py` 从 `hackios-xnu-kernel` 的 `xnu/files/`、`xnu26/files/` 与 "
             "`xnu26/patches/` 生成，不要手工修改。参数的取值与作用见「读取位置」列出的源文件。"
             "运行时拼出的参数名和经由其他封装函数读取的参数不在表内。", "",
             f"共 {len(readers)} 个参数。", "",
             "| 参数 | 读取位置 |", "|---|---|"]
    for name in sorted(readers):
        lines.append(f"| `{name}` | " + "、".join(f"`{p}`" for p in sorted(readers[name])) + " |")
    return "\n".join(lines) + "\n"


def main():
    text = catalog()
    if "--check" in sys.argv:
        if not DOC.is_file() or DOC.read_text() != text:
            print(f"{DOC.relative_to(ROOT)} is out of date: run tools/bootargs.py")
            return 1
        return 0
    DOC.write_text(text)
    print(f"{DOC.relative_to(ROOT)}: {text.count(chr(10)) - 8} boot-args")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
