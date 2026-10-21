#!/usr/bin/env python
"""Mirror the vertiscope docs into the Obsidian vault.

The vault is discovered from Obsidian's own registry
(`%APPDATA%/obsidian/obsidian.json`) rather than assumed. A directory being
readable as markdown does not make it a vault — Obsidian only shows folders it
has actually opened, which are exactly the ones listed there and which carry a
`.obsidian/` config directory.

Obsidian's indexer does not follow directory junctions, so the docs must exist
as real files inside the vault. Copies are byte-for-byte — no frontmatter, no
link rewriting — so the mirror is either identical to source or reported as
drifted. The mirror is a *view*; the vertiscope project stays canonical.

    python scripts/sync_to_vault.py            # report drift only
    python scripts/sync_to_vault.py --write    # copy source -> vault
    python scripts/sync_to_vault.py --list     # show registered vaults
"""

from __future__ import annotations

import argparse
import filecmp
import json
import os
import pathlib
import shutil

SRC = pathlib.Path(__file__).resolve().parent.parent
SUBFOLDER = "vertiscope"          # destination folder inside the vault


def registered_vaults() -> list[pathlib.Path]:
    """Vaults Obsidian actually knows about, most recently used first."""
    appdata = os.environ.get("APPDATA")
    candidates = []
    if appdata:
        candidates.append(pathlib.Path(appdata) / "obsidian" / "obsidian.json")
    candidates += [
        pathlib.Path.home() / ".config" / "obsidian" / "obsidian.json",
        pathlib.Path.home() / "Library" / "Application Support"
        / "obsidian" / "obsidian.json",
    ]
    for path in candidates:
        if not path.exists():
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        vaults = data.get("vaults", {}).values()
        ordered = sorted(vaults, key=lambda v: v.get("ts", 0), reverse=True)
        return [pathlib.Path(v["path"]) for v in ordered if v.get("path")]
    return []


def resolve_vault(explicit: pathlib.Path | None) -> pathlib.Path | None:
    if explicit:
        return explicit
    for vault in registered_vaults():
        if (vault / ".obsidian").exists():
            return vault
    return None

# (source path relative to vertiscope, destination path relative to DEST)
TREES = [
    ("docs", "docs"),
    ("notes", "notes"),
]


def iter_pairs(dest: pathlib.Path):
    for src_rel, dst_rel in TREES:
        src_dir = SRC / src_rel
        if not src_dir.exists():
            continue
        for path in sorted(src_dir.rglob("*.md")):
            yield path, dest / dst_rel / path.relative_to(src_dir)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--write", action="store_true",
                    help="perform the copy (default is a dry-run drift report)")
    ap.add_argument("--list", action="store_true",
                    help="list the vaults Obsidian has registered, then exit")
    ap.add_argument("--vault", type=pathlib.Path,
                    help="override vault auto-detection")
    args = ap.parse_args()

    if args.list:
        found = registered_vaults()
        if not found:
            print("Obsidian has no registered vaults on this machine.")
            return 1
        for vault in found:
            mark = "ok " if (vault / ".obsidian").exists() else "!! "
            print(f"  {mark}{vault}")
        print("\n'!!' = listed but has no .obsidian/ — never actually opened")
        return 0

    vault = resolve_vault(args.vault)
    if vault is None:
        print("no Obsidian vault found; pass --vault, or --list to inspect")
        return 1
    if not vault.exists():
        print(f"vault path does not exist: {vault}")
        return 1
    dest = vault / SUBFOLDER

    new, drifted, same = [], [], []
    for src, dst in iter_pairs(dest):
        if not dst.exists():
            new.append((src, dst))
        elif not filecmp.cmp(src, dst, shallow=False):
            drifted.append((src, dst))
        else:
            same.append((src, dst))

    # Files in the mirror with no source — deletions upstream.
    orphans = []
    if dest.exists():
        wanted = {dst for _, dst in iter_pairs(dest)}
        for path in sorted(dest.rglob("*.md")):
            if path not in wanted:
                orphans.append(path)

    print(f"source: {SRC}")
    print(f"vault : {vault}")
    print(f"mirror: {dest}\n")
    for label, group in (("new", new), ("drifted", drifted), ("unchanged", same)):
        print(f"  {label:10s} {len(group)}")
        if label != "unchanged":
            for src, dst in group:
                print(f"      {dst.relative_to(dest)}")
    if orphans:
        print(f"  orphaned  {len(orphans)}  (in mirror, absent from source)")
        for path in orphans:
            print(f"      {path.relative_to(dest)}")

    if not args.write:
        if new or drifted:
            print("\ndry run — pass --write to copy")
        return 0

    for src, dst in new + drifted:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    print(f"\ncopied {len(new) + len(drifted)} file(s)")
    if orphans:
        print("orphans left in place; remove by hand if the source deletion was intended")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
