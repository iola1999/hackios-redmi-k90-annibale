#!/usr/bin/env python3
"""只读检查项目跟踪的 Markdown；显式文件参数可用于检查尚未入库的文档。"""

import argparse
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import unquote, urlsplit

from unwrap_md import Unwrapper


ROOT = Path(__file__).resolve().parents[1]
REPOS = (ROOT, ROOT / "hackios-xnu-kernel", ROOT / "hackios-xnu-userland")
LINK = re.compile(r"!?\[([^\]\n]*)\]\((<[^>\n]+>|(?:[^\s()]|\([^\s()]*\))+)(?:\s+\"[^\"]*\")?\)")
REFERENCE = re.compile(r"^\s{0,3}\[[^\]]+\]:\s*(<[^>]+>|\S+)")
INLINE_CODE = re.compile(r"(`+).*?\1")
HEADING = re.compile(r"^ {0,3}#{1,6}[ \t]+(.+?)(?:\s+#+)?\s*$")
FENCE = re.compile(r"^\s*(`{3,}|~{3,})(.*)$")


def prose(text):
    """保留行号；围栏内示例不参与标题、链接和段落检查。"""
    fence = None
    for number, line in enumerate(text.splitlines(), 1):
        match = FENCE.match(line)
        if match:
            delimiter = match[1]
            if fence is None:
                fence = delimiter
            elif delimiter[0] == fence[0] and len(delimiter) >= len(fence) and not match[2].strip():
                fence = None
            continue
        if fence is None:
            yield number, line


def anchors(text):
    result, counts = set(), {}
    for _, line in prose(text):
        result.update(re.findall(r'<a\s+(?:id|name)=[\"\']([^\"\']+)', line))
        match = HEADING.match(line)
        if not match:
            continue
        title = LINK.sub(lambda m: m[1], match[1])
        title = re.sub(r"<[^>]*>", "", title).lower()
        slug = re.sub(r"[^\w\- ]", "", title).replace(" ", "-")
        count = counts.get(slug, 0)
        counts[slug] = count + 1
        result.add(slug + (f"-{count}" if count else ""))
    return result


def destinations(text):
    for number, line in prose(text):
        line = INLINE_CODE.sub("", line)
        for match in LINK.finditer(line):
            yield number, match[2].strip("<>")
        match = REFERENCE.match(line)
        if match:
            yield number, match[1].strip("<>")


def tracked_documents(repo):
    output = subprocess.check_output(
        ["git", "-C", str(repo), "ls-files", "-z", "--", "*.md"],
    )
    return [repo / name.decode() for name in output.split(b"\0") if name]


def check(files, project_files, complete=False):
    problems, texts, heading_cache = [], {}, {}
    graph = {path: set() for path in files}
    links = 0

    def read(path):
        if path not in texts:
            if path.stat().st_size > 2 * 1024 * 1024:
                raise ValueError("Markdown 超过 2 MiB，请单独检查内容与拆分边界")
            texts[path] = path.read_text(encoding="utf-8")
        return texts[path]

    def report(path, line, message):
        problems.append(f"{path.relative_to(ROOT)}:{line}: {message}")

    for path in files:
        try:
            text = read(path)
        except (OSError, UnicodeError, ValueError) as error:
            report(path, 1, f"无法读取：{error}")
            continue
        if path in project_files:
            h2 = 0
            for number, line in prose(text):
                if re.match(r"^ {0,3}##[ \t]+", line):
                    h2 += 1
                    if not line.startswith(f"## {h2}. "):
                        report(path, number, f"二级标题应以「## {h2}. 」开头")
                if len(line) > 500 and not (line.lstrip().startswith("|") or HEADING.match(line)):
                    report(path, number, "段落或列表项超过 500 字符，请按独立事实拆分")
            lines = text.splitlines()
            if Unwrapper().feed(lines) != lines:
                report(path, 1, "存在硬换行或行尾空格；运行 tools/unwrap_md.py --check 查看")

        for number, target in destinations(text):
            url = urlsplit(target)
            if url.scheme or url.netloc:
                continue
            links += 1
            destination = (path.parent / unquote(url.path)).resolve()
            if not url.path:
                destination = path
            if not destination.is_relative_to(ROOT):
                report(path, number, "本地链接超出工作区，请使用项目相对路径或公开 URL")
                continue
            if not destination.exists():
                report(path, number, f"链接目标不存在：{target}")
                continue
            if destination in graph:
                graph[path].add(destination)
            if url.fragment and destination.suffix == ".md":
                try:
                    if destination not in heading_cache:
                        heading_cache[destination] = anchors(read(destination))
                    if unquote(url.fragment) not in heading_cache[destination]:
                        report(path, number, f"标题锚点不存在：{target}")
                except (OSError, UnicodeError, ValueError) as error:
                    report(path, number, f"无法检查链接目标：{error}")
    if complete:
        reached, pending = set(), [ROOT / "README.md"]
        while pending:
            path = pending.pop()
            if path not in reached:
                reached.add(path)
                pending.extend(graph.get(path, ()))
        for path in sorted(set(files) - reached):
            report(path, 1, "从仓库 README 无法通过文档链接访问，请补充相应入口")
    return problems, links


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("files", nargs="*", type=Path, help="默认检查三个仓库的跟踪 Markdown")
    args = parser.parse_args()
    try:
        project_files = set(tracked_documents(ROOT))
        if args.files:
            files = sorted({path.resolve() for path in args.files})
            if any(not path.is_relative_to(ROOT) for path in files):
                parser.error("文件必须位于工作区中")
            project_files.update(path for path in files if not any(path.is_relative_to(repo) for repo in REPOS[1:]))
        else:
            if any(not (repo / ".git").exists() for repo in REPOS[1:]):
                parser.error("全量检查需要先检出两个代码子模块")
            files = sorted(project_files.union(*(set(tracked_documents(repo)) for repo in REPOS[1:])))
        problems, links = check(files, project_files, complete=not args.files)
    except subprocess.CalledProcessError:
        print("无法枚举文档，请先检出顶层仓库与两个代码子模块。", file=sys.stderr)
        return 1
    for problem in problems:
        print(problem)
    print(f"检查 {len(files)} 份 Markdown、{links} 个本地链接，发现 {len(problems)} 项问题。")
    return bool(problems)


if __name__ == "__main__":
    raise SystemExit(main())
