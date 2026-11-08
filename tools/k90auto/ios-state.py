#!/usr/bin/env python3
"""Collect read-only iOS state through the running round's existing rsh channel.

usage: tools/k90auto/ios-state.py ROUND_DIR [--ls PATH] [--sysctl NAME] [--threads PID]
       [--output FILE]

The default report includes ps, appinst list, /Applications and the standard IPA/download staging
directories. appinst list covers user-installed bundles; use appinst open and the home screen to check
system-registered applications. Extra queries are read-only. The JSON keeps each command's exit status and output so a
missing path stays distinguishable from a transport failure. This script never talks to fastboot
itself; run-auto.py remains the only device commander.
"""
import argparse
import datetime
import json
from pathlib import Path
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
DEFAULT_COMMANDS = (
    ("processes", ("ps",)),
    ("installed_apps", ("/annibale/bin/appinst", "list")),
    ("applications", ("ls", "/Applications")),
    ("downloads", ("ls", "/private/var/mobile/Library/Downloads")),
    ("ipa_staging", ("ls", "/private/var/tmp/ipa")),
)


def collect(round_dir, extra_ls=(), sysctls=(), thread_pids=(), output=None):
    run = round_dir / "run"
    if not run.is_dir() or (run / "reboot.json").exists():
        raise RuntimeError(f"{run} is not a running round")
    commands = list(DEFAULT_COMMANDS)
    commands.extend((f"ls:{path}", ("ls", path)) for path in extra_ls)
    commands.extend((f"sysctl:{name}", ("sysctl", name)) for name in sysctls)
    for pid in thread_pids:
        commands.append((f"threads:{pid}", ("threads", str(pid))))
        commands.append((f"thread_dump:{pid}", ("dump", str(pid))))

    report = {
        "round_dir": str(round_dir),
        "started_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "commands": [],
        "status": "collecting",
    }
    for name, words in commands:
        result = subprocess.run(
            [sys.executable, str(HERE / "rsh.py"), str(round_dir), *words],
            capture_output=True, text=True,
        )
        record = {
            "name": name,
            "command": list(words),
            "exit": result.returncode,
            "stdout": result.stdout,
            "stderr": result.stderr,
        }
        report["commands"].append(record)
        print(f"{name}: exit {result.returncode}, {len(result.stdout.splitlines())} output lines", flush=True)
        if result.returncode in (2, 3):
            report["status"] = "transport_failed"
            report["failed_command"] = name
            break
    else:
        report["status"] = "complete"
    report["finished_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
    destination = output or run / f"ios-state-{time.time_ns()}.json"
    destination.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"state: {report['status']}; report: {destination}")
    return report, destination


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("round_dir", type=Path)
    parser.add_argument("--ls", dest="extra_ls", action="append", default=[], metavar="PATH")
    parser.add_argument("--sysctl", action="append", default=[], metavar="NAME")
    parser.add_argument("--threads", action="append", type=int, default=[], metavar="PID")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report, _ = collect(args.round_dir, args.extra_ls, args.sysctls, args.threads, args.output)
    except (OSError, RuntimeError) as error:
        parser.exit(2, f"ios-state: {error}\n")
    return 2 if report["status"] == "transport_failed" else 0


if __name__ == "__main__":
    raise SystemExit(main())
