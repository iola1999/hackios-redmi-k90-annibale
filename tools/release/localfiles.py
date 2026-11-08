"""The files of the root image that a release does not carry, and how they are made again.

A release holds what this project wrote. The rest of the root image comes from the user's own
IPSW and phone, and is described here as recipes (local-files.plist in the release):

  copy      an iOS file as it is (iOS path)
  plist     an iOS property list with this project's edits applied (iOS path, edit list)
  cache     iOS's launchd cache with its LaunchDaemons replaced by the image's LaunchDaemons/
            (what userland/mkcache.py does), then the edit list
  skeleton  the /private/var template: ios26/full-system.py skeleton of the root volume listing,
            with this project's lines inserted
  firmware  a file read out of the phone's partitions

An edit list holds only the project's changes: ["del", keys] and ["set", keys, value], keys being
the path of dictionary keys from the top. Every recipe records the SHA-256 of the file it has to
produce, and make() checks it, so a different IPSW or a changed recipe stops the build.
"""
import difflib
import hashlib
import os
import plistlib
import stat
from pathlib import Path

FORMAT = 1
CACHE_JOB_PREFIX = "/System/Library/LaunchDaemons/"


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def file_sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def plist_edits(base, wanted, keys=()):
    if type(base) is type(wanted) and base == wanted:
        return []
    if isinstance(base, dict) and isinstance(wanted, dict):
        edits = [["del", [*keys, k]] for k in sorted(base.keys() - wanted.keys())]
        for k in sorted(wanted):
            if k in base:
                edits += plist_edits(base[k], wanted[k], (*keys, k))
            else:
                edits.append(["set", [*keys, k], wanted[k]])
        return edits
    return [["set", list(keys), wanted]]


def apply_edits(value, edits):
    for edit in edits:
        keys = edit[1]
        if not keys:
            value = edit[2]
            continue
        node = value
        for k in keys[:-1]:
            node = node[k]
        if edit[0] == "del":
            del node[keys[-1]]
        else:
            node[keys[-1]] = edit[2]
    return value


def dump_plist(value):
    # every property list of the root image is written by plistlib in binary form (mkjobs.py,
    # mkcache.py, package.py), so the same value gives the same bytes
    return plistlib.dumps(value, fmt=plistlib.FMT_BINARY)


def cache_base(apple_cache, jobs):
    """iOS's launchd cache with the jobs of the image, as userland/mkcache.py builds it."""
    cache = plistlib.loads(apple_cache)
    cache["LaunchDaemons"] = {CACHE_JOB_PREFIX + name: plistlib.loads(data) for name, data in sorted(jobs.items())}
    return cache


def skeleton_edits(base_text, wanted_text):
    base, wanted = base_text.splitlines(keepends=True), wanted_text.splitlines(keepends=True)
    edits = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, base, wanted, autojunk=False).get_opcodes():
        if tag == "equal":
            edits.append(["copy", i1, i2])
        elif tag in ("insert", "replace"):
            edits.append(["insert", "".join(wanted[j1:j2])])
    return edits


def apply_skeleton(base_text, edits):
    base = base_text.splitlines(keepends=True)
    return "".join("".join(base[e[1]:e[2]]) if e[0] == "copy" else e[1] for e in edits)


def make(recipe, ios_file, skeleton_text, jobs, firmware_file):
    """The bytes of one recipe's file.

    ios_file(path) reads an iOS file ("os:", "systemos:" or "appos:" and the path in that volume),
    skeleton_text is full-system.py's skeleton of the root volume, jobs maps every LaunchDaemons/
    name of the image to its bytes (needed by "cache" only), firmware_file(name) reads a firmware
    file. Raises ValueError when the result is not the file the release was made with.
    """
    kind = recipe["kind"]
    if kind == "copy":
        data = ios_file(recipe["from"])
    elif kind == "plist":
        data = dump_plist(apply_edits(plistlib.loads(ios_file(recipe["from"])), recipe["edits"]))
    elif kind == "cache":
        data = dump_plist(apply_edits(cache_base(ios_file(recipe["from"]), jobs), recipe["edits"]))
    elif kind == "skeleton":
        data = apply_skeleton(skeleton_text, recipe["edits"]).encode()
    elif kind == "firmware":
        data = firmware_file(recipe["name"])
        return data  # the phone's own firmware may be another version than the release's
    else:
        raise ValueError(f"{recipe['path']}: unknown recipe kind {kind}")
    if sha256(data) != recipe["sha256"]:
        raise ValueError(f"{recipe['path']}: made from {recipe.get('from', 'the listing')}, "
                         f"SHA-256 {sha256(data)} instead of {recipe['sha256']}")
    return data


def tree(root):
    """Every entry under root, in a fixed order: (relative path, kind, mode, link target)."""
    entries = []
    for directory, dirs, files in os.walk(root):
        dirs.sort()
        for name in sorted(dirs + files):
            path = Path(directory) / name
            st = path.lstat()
            rel = path.relative_to(root).as_posix()
            if stat.S_ISLNK(st.st_mode):
                entries.append((rel, "link", 0o755, os.readlink(path)))
            elif stat.S_ISDIR(st.st_mode):
                entries.append((rel, "dir", stat.S_IMODE(st.st_mode), ""))
            elif stat.S_ISREG(st.st_mode):
                entries.append((rel, "file", stat.S_IMODE(st.st_mode), ""))
            else:
                raise ValueError(f"{path}: not a file, directory or symbolic link")
    return entries


def tree_digest(root):
    """SHA-256 of what mkapfs.py packs from root: names, kinds, permission bits, links and contents.

    The root image itself is compared only where the same zlib made it: mkapfs.py -z compresses
    with Python's zlib, and another zlib version stores the same files in other bytes.
    """
    h = hashlib.sha256()
    for rel, kind, mode, target in tree(root):
        h.update(f"{rel}\0{kind}\0{mode:o}\0{target}\0".encode())
        if kind == "file":
            h.update(hashlib.sha256((Path(root) / rel).read_bytes()).digest())
    return h.hexdigest()
