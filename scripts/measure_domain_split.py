#!/usr/bin/env python
"""Quantify the DOMAIN split of CONTENT_EXTRACTION_RULES §9.1.

That section records that the host tagger and the in-page engine detect
different spaces, citing set sizes. A size difference is not the quantity that
matters: what matters is whether the two vocabularies *disagree on attributes
that actually carry content*, and by how much on real pages.

This extracts both vocabularies — the host's from the live module, the in-page
engine's by parsing its constant declarations — and reports the symmetric
difference, then weights it by observed yield.

    python scripts/measure_domain_split.py
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vertiscope.core import content_tagger as ct           # noqa: E402
from vertiscope.core.shadow_html_parser import ShadowDOM   # noqa: E402

JS = ROOT / "vertiscope" / "core" / "js" / "wfh_chunk_engine.js"

SAMPLES = [
    ROOT / "tests" / "fixtures" / "catalog.html",
    pathlib.Path.home() / "Documents" / "Daniel Bulford - Wikipedia.html",
]


def js_set(name: str) -> set[str]:
    """Extract `const NAME = new Set([...])` from the in-page engine."""
    text = JS.read_text(encoding="utf-8")
    m = re.search(rf"const\s+{name}\s*=\s*new Set\(\[(.*?)\]\)", text, re.S)
    if not m:
        return set()
    return set(re.findall(r"'([^']+)'", m.group(1)))


def report(label: str, host: set[str], page: set[str]) -> dict:
    only_host = sorted(host - page)
    only_page = sorted(page - host)
    both = host & page
    print(f"\n{label}")
    print(f"  host {len(host):3d}   in-page {len(page):3d}   shared {len(both):3d}")
    print(f"  host only ({len(only_host)}): {', '.join(only_host) or '-'}")
    print(f"  page only ({len(only_page)}): {', '.join(only_page) or '-'}")
    return {"host_only": only_host, "page_only": only_page, "shared": sorted(both)}


def main() -> int:
    print("=" * 72)
    print("DOMAIN SPLIT — host tagger vs in-page engine")
    print("=" * 72)

    findings = {}

    findings["url_attrs"] = report(
        "URL-bearing attributes",
        set(ct._URL_BEARING_ATTRS), js_set("URL_ATTRS"))

    findings["text_attrs"] = report(
        "text-bearing attributes (host: accessible + metadata)",
        set(ct._TEXT_ATTRS) | set(ct._META_TEXT_ATTRS), js_set("TEXT_ATTRS"))

    findings["skip_attrs"] = report(
        "never-content attributes",
        set(ct._SKIP_ATTRS), js_set("SKIP_ATTRS"))

    # --- weight the disagreement by observed yield --------------------------
    print("\n" + "=" * 72)
    print("WEIGHTED BY OBSERVED YIELD")
    print("=" * 72)
    yields: Counter[str] = Counter()
    used = []
    for path in SAMPLES:
        if not path.exists():
            continue
        used.append(path.name)
        dom = ShadowDOM(path.read_text(encoding="utf-8", errors="replace"))
        for tag in ct.ContentTagger(dom).tag().all_tags:
            if tag.source_attr:
                yields[tag.source_attr] += 1

    print(f"  pages: {', '.join(used) or '(none)'}")
    total = sum(yields.values())

    contested = set()
    for key, f in findings.items():
        contested |= set(f["host_only"]) | set(f["page_only"])

    at_risk = {a: n for a, n in yields.items() if a in contested}
    n_risk = sum(at_risk.values())
    print(f"  detections from attributes the two sides disagree about: "
          f"{n_risk} / {total}"
          + (f"  ({100 * n_risk / total:.1f}%)" if total else ""))
    for attr, n in sorted(at_risk.items(), key=lambda kv: -kv[1]):
        side = "host only" if any(attr in f["host_only"] for f in findings.values()) \
               else "in-page only"
        print(f"    {attr:24s} {n:6d}   ({side})")

    print("\n  -> the split is not merely a difference in list length: these")
    print("     detections exist under one detector and not the other.")

    out = ROOT / "notes" / "observations" / "_domain_split.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"findings": findings, "yield_at_risk": at_risk, "total_detections": total},
        indent=2), encoding="utf-8")
    print(f"\nwrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
