#!/usr/bin/env python
"""Dump the live content-detection vocabulary.

`docs/CONTENT_EXTRACTION_RULES.md` claims to enumerate the complete detectable
content space. This script is the ground truth that claim is checked against:
it prints every constant set from the tagger, the declared category space, and
the buckets actually populated over the sample pages. If the document and this
output disagree, the document is wrong.

    python scripts/dump_extraction_rules.py
    python scripts/dump_extraction_rules.py --page some.html
"""

from __future__ import annotations

import argparse
import dataclasses
import pathlib
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vertiscope.core import content_tagger as ct  # noqa: E402
from vertiscope.core.shadow_html_parser import ShadowDOM  # noqa: E402

# Ordered to mirror the document's section order.
CONSTANTS = [
    ("§3.2 text.accessible attributes", "_TEXT_ATTRS"),
    ("§3.3 text.metadata attributes", "_META_TEXT_ATTRS"),
    ("§4.1 URL pattern", "_URL_PATTERN"),
    ("§4.1 CSS url() pattern", "_CSS_URL_PATTERN"),
    ("§4.3 URL-bearing attributes", "_URL_BEARING_ATTRS"),
    ("§4.4 never-scanned-for-URLs attributes", "_NON_URL_ATTRS"),
    ("§4.4 never-scanned-for-URLs prefixes", "_NON_URL_ATTR_PREFIXES"),
    ("§5 extension pattern", "_EXT_PATTERN"),
    ("§5 image extensions", "_IMAGE_EXTS"),
    ("§5 video extensions", "_VIDEO_EXTS"),
    ("§5 audio extensions", "_AUDIO_EXTS"),
    ("§5 archive extensions", "_ARCHIVE_EXTS"),
    ("§6 input tags", "_INPUT_TAGS"),
    ("§6 button tags", "_BUTTON_TAGS"),
    ("§6 form tags", "_FORM_TAGS"),
    ("§6 interactive roles", "_INTERACTIVE_ROLES"),
    ("§7 JSON script types", "_JSON_SCRIPT_TYPES"),
    ("§7 JSON pre-filter", "_JSON_HEURISTIC"),
    ("§8.1 never-content attributes", "_SKIP_ATTRS"),
    ("§8.2 never-content prefixes", "_SKIP_ATTR_PREFIXES"),
    ("§8.3 inline tags", "_INLINE_TAGS"),
]

DEFAULT_PAGES = [
    ROOT / "tests" / "fixtures" / "catalog.html",
    pathlib.Path.home() / "Documents" / "Daniel Bulford - Wikipedia.html",
]


def _render(value) -> str:
    if hasattr(value, "pattern"):
        return "(regex) " + " ".join(value.pattern.split())
    if isinstance(value, (frozenset, set)):
        items = sorted(value)
        return f"({len(items)}) " + ", ".join(items)
    if isinstance(value, tuple):
        return f"({len(value)}) " + ", ".join(map(str, value))
    return repr(value)


def dump_constants() -> None:
    print("=" * 72)
    print("CONSTANT SETS")
    print("=" * 72)
    missing = []
    for label, name in CONSTANTS:
        value = getattr(ct, name, None)
        if value is None:
            missing.append(name)
            print(f"\n{label}  [{name}]\n  ABSENT")
            continue
        print(f"\n{label}  [{name}]\n  {_render(value)}")
    if missing:
        print(f"\n!! {len(missing)} constant(s) absent — the document is stale: {missing}")


def dump_space() -> list[str]:
    print("\n" + "=" * 72)
    print("DECLARED CATEGORY SPACE")
    print("=" * 72)
    tc = ct.TaggedContent()
    buckets: list[str] = []
    for field in dataclasses.fields(tc):
        value = getattr(tc, field.name)
        if isinstance(value, dict):
            keys = sorted(value)
            buckets += [f"{field.name}.{k}" for k in keys]
            print(f"  {field.name:14s} ({len(keys)}) {', '.join(keys)}")
    print(f"\n  categories: {len({b.split('.')[0] for b in buckets})}"
          f"   subcategories: {len(buckets)}")
    return buckets


def dump_observed(pages: list[pathlib.Path], declared: list[str]) -> None:
    print("\n" + "=" * 72)
    print("OBSERVED OVER SAMPLE PAGES")
    print("=" * 72)
    seen: Counter[str] = Counter()
    attrs: Counter[str] = Counter()
    used = []
    for page in pages:
        if not page.exists():
            print(f"  (missing, skipped) {page}")
            continue
        used.append(page)
        dom = ShadowDOM(page.read_text(encoding="utf-8", errors="replace"))
        result = ct.ContentTagger(dom).tag()
        for field in dataclasses.fields(result):
            value = getattr(result, field.name)
            if isinstance(value, dict):
                for key, items in value.items():
                    if items:
                        seen[f"{field.name}.{key}"] += len(items)
        for tag in result.all_tags:
            attrs[tag.source_attr or "(text node)"] += 1

    print(f"  pages: {len(used)}")
    for page in used:
        print(f"    {page.name}")

    print("\n  buckets populated:")
    for bucket in sorted(seen):
        print(f"    {bucket:32s} {seen[bucket]:6d}")

    never = [b for b in declared if b not in seen]
    print(f"\n  declared but NOT populated ({len(never)}):")
    for bucket in never:
        print(f"    {bucket}")

    print("\n  source attributes yielding content:")
    for attr, n in attrs.most_common():
        print(f"    {attr:32s} {n:6d}")

    listed = set()
    for name in ("_URL_BEARING_ATTRS", "_TEXT_ATTRS", "_META_TEXT_ATTRS"):
        listed |= set(getattr(ct, name, ()) or ())
    agnostic = [
        a for a in attrs
        if a not in listed and not a.startswith(("(", "ld_json:", "text()"))
    ]
    print("\n  reached only by the attribute-agnostic scan "
          f"({len(agnostic)}): {', '.join(sorted(agnostic)) or '(none)'}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--page", action="append", type=pathlib.Path,
                    help="sample page to scan (repeatable); defaults to the fixture set")
    args = ap.parse_args()

    dump_constants()
    declared = dump_space()
    dump_observed(args.page or DEFAULT_PAGES, declared)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
