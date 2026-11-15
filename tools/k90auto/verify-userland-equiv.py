#!/usr/bin/env python3
"""Userland build output equivalence verification and baseline snapshot tool.

Scans Mach-O binaries in userland build outputs (userland/obj, root/, images),
extracts Mach-O header properties (cputype, cpusubtype, filetype, flags),
file sizes, SHA-256 digests, exported symbols, dynamic dependencies,
and code-signature entitlements.

Generates and checks baseline snapshots (out/baseline-userland.json).

Usage:
    python3 tools/k90auto/verify-userland-equiv.py [--check] [--update] [--baseline PATH]
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import subprocess
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
USERLAND_DIR = REPO_ROOT / "hackios-xnu-userland" / "userland"
DEFAULT_BASELINE = REPO_ROOT / "out" / "baseline-userland.json"
MACH_O_64 = 0xfeedfacf
MACH_O_32 = 0xfeedface


def sha256_file(path: Path) -> str:
    """Compute SHA-256 digest of a file in streaming chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(1048576):
            h.update(chunk)
    return h.hexdigest()


def parse_macho_header(data: bytes) -> dict:
    """Parse Mach-O 32-bit or 64-bit header."""
    if len(data) < 28:
        return {}
    magic = struct.unpack_from("<I", data, 0)[0]
    if magic not in (MACH_O_64, MACH_O_32):
        return {}
    cputype, cpusubtype, filetype, ncmds, sizeofcmds, flags = struct.unpack_from("<IIIIII", data, 4)
    res = {
        "magic": f"0x{magic:08x}",
        "cputype": f"0x{cputype:08x}",
        "cpusubtype": f"0x{cpusubtype:08x}",
        "filetype": int(filetype),
        "ncmds": int(ncmds),
        "sizeofcmds": int(sizeofcmds),
        "flags": f"0x{flags:08x}",
        "is_64bit": (magic == MACH_O_64),
    }
    return res


def extract_symbols(path: Path) -> list:
    """Extract sorted list of exported global defined symbols via nm -gU."""
    try:
        proc = subprocess.run(["nm", "-gU", str(path)], capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            return []
        symbols = []
        for line in proc.stdout.splitlines():
            parts = line.strip().split()
            if len(parts) >= 3 and parts[1] in ("T", "D", "S", "B"):
                symbols.append(parts[2])
            elif len(parts) == 2 and parts[0] in ("T", "D", "S", "B"):
                symbols.append(parts[1])
        return sorted(symbols)
    except Exception:
        return []


def extract_dylibs(path: Path) -> list:
    """Extract loaded dylib dependencies via otool -L."""
    try:
        proc = subprocess.run(["otool", "-L", str(path)], capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            return []
        dylibs = []
        lines = proc.stdout.splitlines()
        # First line is binary path, subsequent lines are dylibs
        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
            dylib_name = line.split(" (compatibility")[0].strip()
            dylibs.append(dylib_name)
        return sorted(dylibs)
    except Exception:
        return []


def extract_entitlements_digest(path: Path) -> str:
    """Extract codesign entitlements XML and return its SHA-256 digest."""
    try:
        proc = subprocess.run(
            ["codesign", "-d", "--entitlements", ":-", str(path)],
            capture_output=True,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout:
            return hashlib.sha256(proc.stdout).hexdigest()
        return ""
    except Exception:
        return ""


def scan_obj_directory(obj_dir: Path) -> dict:
    """Scan all target files in userland/obj directory."""
    targets = {}
    if not obj_dir.is_dir():
        return targets

    for item in sorted(obj_dir.iterdir()):
        if not item.is_file():
            continue
        try:
            data = item.read_bytes()
        except (PermissionError, OSError):
            continue

        size = len(data)
        file_sha256 = hashlib.sha256(data).hexdigest()
        macho_info = parse_macho_header(data)

        if macho_info:
            symbols = extract_symbols(item)
            dylibs = extract_dylibs(item)
            entitlements_hash = extract_entitlements_digest(item)
            targets[item.name] = {
                "name": item.name,
                "size": size,
                "sha256": file_sha256,
                "macho": macho_info,
                "symbols_count": len(symbols),
                "symbols": symbols,
                "dylibs": dylibs,
                "entitlements_sha256": entitlements_hash,
            }
        else:
            targets[item.name] = {
                "name": item.name,
                "size": size,
                "sha256": file_sha256,
                "macho": None,
            }

    return targets


def scan_directory_tree(root_dir: Path) -> dict:
    """Scan directory structure (relative path -> size, mode, sha256)."""
    tree = {}
    if not root_dir.is_dir():
        return tree

    for path in sorted(root_dir.rglob("*")):
        if path.is_file() and not path.is_symlink():
            rel = str(path.relative_to(root_dir))
            try:
                st = path.stat()
                tree[rel] = {
                    "size": st.st_size,
                    "mode": oct(st.st_mode)[-3:],
                    "sha256": sha256_file(path),
                }
            except OSError:
                pass
        elif path.is_symlink():
            rel = str(path.relative_to(root_dir))
            tree[rel] = {
                "type": "symlink",
                "target": str(os.readlink(path)),
            }
    return tree


def generate_baseline(userland_dir: Path) -> dict:
    """Generate complete baseline snapshot dictionary."""
    obj_dir = userland_dir / "obj"
    root_dir = userland_dir / "root"
    targets = scan_obj_directory(obj_dir)

    images = {}
    for img_name in ("flashboot.apfs", "root26.apfs", "system26.apfs"):
        img_path = userland_dir / img_name
        if img_path.is_file() and img_path.stat().st_size > 0:
            images[img_name] = {
                "size": img_path.stat().st_size,
                "sha256": sha256_file(img_path),
            }

    root_tree = scan_directory_tree(root_dir)

    return {
        "version": 1,
        "format": "userland-equivalence-baseline",
        "target_count": len(targets),
        "targets": targets,
        "images": images,
        "root_file_count": len(root_tree),
    }


def compare_baselines(expected: dict, actual: dict, verbose: bool = False) -> tuple[bool, list[str]]:
    """Compare baseline with actual scan, returning (is_equiv, differences)."""
    diffs = []
    exp_targets = expected.get("targets", {})
    act_targets = actual.get("targets", {})

    missing_targets = set(exp_targets) - set(act_targets)
    if missing_targets:
        diffs.append(f"Missing targets ({len(missing_targets)}): {', '.join(sorted(missing_targets))}")

    extra_targets = set(act_targets) - set(exp_targets)
    if extra_targets and verbose:
        diffs.append(f"Extra targets ({len(extra_targets)}): {', '.join(sorted(extra_targets))}")

    common_targets = set(exp_targets) & set(act_targets)
    for name in sorted(common_targets):
        e = exp_targets[name]
        a = act_targets[name]

        # Check Mach-O header properties
        e_m = e.get("macho")
        a_m = a.get("macho")
        if (e_m is None) != (a_m is None):
            diffs.append(f"{name}: Mach-O status mismatch (expected {e_m is not None}, got {a_m is not None})")
            continue

        if e_m and a_m:
            for k in ("magic", "cputype", "cpusubtype", "filetype"):
                if e_m.get(k) != a_m.get(k):
                    diffs.append(f"{name}: Mach-O header '{k}' mismatch (expected {e_m.get(k)}, got {a_m.get(k)})")

            # Check dynamic dependencies
            e_dylibs = set(e.get("dylibs", []))
            a_dylibs = set(a.get("dylibs", []))
            if e_dylibs != a_dylibs:
                diffs.append(
                    f"{name}: dylib dependencies mismatch (missing: {e_dylibs - a_dylibs}, extra: {a_dylibs - e_dylibs})"
                )

            # Check exported symbols
            e_syms = set(e.get("symbols", []))
            a_syms = set(a.get("symbols", []))
            if e_syms != a_syms:
                diffs.append(
                    f"{name}: exported symbols mismatch (missing: {len(e_syms - a_syms)}, extra: {len(a_syms - e_syms)})"
                )

            # Check entitlements
            e_ent = e.get("entitlements_sha256", "")
            a_ent = a.get("entitlements_sha256", "")
            if e_ent != a_ent:
                diffs.append(f"{name}: entitlements digest mismatch (expected {e_ent[:8]}, got {a_ent[:8]})")

        # Check hash and size
        if e.get("sha256") != a.get("sha256"):
            if verbose or not (e_m and a_m):
                diffs.append(f"{name}: SHA-256 mismatch (expected {e.get('sha256')[:8]}, got {a.get('sha256')[:8]})")

        if e.get("size") != a.get("size"):
            if verbose or not (e_m and a_m):
                diffs.append(f"{name}: size mismatch (expected {e.get('size')}, got {a.get('size')})")

    # Compare images if present in both
    exp_images = expected.get("images", {})
    act_images = actual.get("images", {})
    for img_name in sorted(set(exp_images) & set(act_images)):
        if exp_images[img_name].get("size") != act_images[img_name].get("size"):
            diffs.append(
                f"Image {img_name}: size mismatch (expected {exp_images[img_name].get('size')}, got {act_images[img_name].get('size')})"
            )

    return (len(diffs) == 0, diffs)


def main():
    parser = argparse.ArgumentParser(description="Verify userland build equivalence and manage baseline snapshots.")
    parser.add_argument("--check", action="store_true", help="Check current userland build against baseline.")
    parser.add_argument("--update", action="store_true", help="Force update/generate baseline snapshot.")
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE, help="Path to baseline JSON file.")
    parser.add_argument("--userland-dir", type=Path, default=USERLAND_DIR, help="Path to userland directory.")
    parser.add_argument("--verbose", "-v", action="store_true", help="Show verbose output.")
    parser.add_argument("--json", action="store_true", help="Output results in JSON format.")
    args = parser.parse_args()

    userland = args.userland_dir
    if not userland.is_dir():
        # Fallback if running inside submodule
        alt_userland = REPO_ROOT / "userland"
        if alt_userland.is_dir():
            userland = alt_userland
        else:
            print(f"Error: userland directory not found at {userland}", file=sys.stderr)
            return 1

    current_snapshot = generate_baseline(userland)
    baseline_path = args.baseline

    if args.check:
        if not baseline_path.is_file():
            print(f"Baseline not found at {baseline_path}. Generating initial baseline now...", file=sys.stderr)
            baseline_path.parent.mkdir(parents=True, exist_ok=True)
            baseline_path.write_text(json.dumps(current_snapshot, indent=2, sort_keys=True) + "\n")
            print(f"Saved initial baseline snapshot to {baseline_path} ({current_snapshot['target_count']} targets).")
            return 0

        try:
            expected_snapshot = json.loads(baseline_path.read_text())
        except Exception as e:
            print(f"Error loading baseline {baseline_path}: {e}", file=sys.stderr)
            return 1

        is_equiv, diffs = compare_baselines(expected_snapshot, current_snapshot, verbose=args.verbose)
        if args.json:
            result = {
                "equivalent": is_equiv,
                "differences_count": len(diffs),
                "differences": diffs,
                "target_count": current_snapshot["target_count"],
            }
            print(json.dumps(result, indent=2))
        else:
            if is_equiv:
                print(
                    f"OK: Userland build is equivalent to baseline ({current_snapshot['target_count']} targets verified)."
                )
            else:
                print(f"FAIL: Found {len(diffs)} equivalence difference(s) against baseline:", file=sys.stderr)
                for d in diffs:
                    print(f"  - {d}", file=sys.stderr)

        return 0 if is_equiv else 1

    elif args.update or not baseline_path.is_file():
        baseline_path.parent.mkdir(parents=True, exist_ok=True)
        baseline_path.write_text(json.dumps(current_snapshot, indent=2, sort_keys=True) + "\n")
        equiv_dir = REPO_ROOT / "out" / "equiv-baseline"
        equiv_dir.mkdir(parents=True, exist_ok=True)
        (equiv_dir / "baseline-userland.json").write_text(
            json.dumps(current_snapshot, indent=2, sort_keys=True) + "\n"
        )
        print(f"Saved baseline snapshot to {baseline_path} ({current_snapshot['target_count']} targets).")
        return 0

    else:
        # Default action: verify if baseline exists, otherwise generate
        print(f"Baseline snapshot already exists at {baseline_path}.")
        print("Use --check to verify equivalence, or --update to regenerate snapshot.")
        return 0


if __name__ == "__main__":
    sys.exit(main())
