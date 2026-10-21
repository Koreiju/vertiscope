"""What an index-agnostic xpath would buy, and what it would cost.

The goal asks whether the address could keep absolute structure while making
array indices agnostic for repeated fields -- menu items, paragraphs, search
results. This measures both sides of that on the real corpus rather than
arguing it.

The address today is `url : xpath : taxonomy : accessor`, and the xpath is
absolute with positional indices: `.../ol/li[11]/article/h3`. Dropping the
indices gives a SHAPE: `.../ol/li/article/h3`. Every repeat of one template
collapses onto one shape.

Two questions, and they pull in opposite directions:

* **What collapses.** How many addresses share a shape? A high number means
  the corpus really is mostly repeated templates, which is the premise.
* **What is lost.** An address is a *pointer*: the REPL presses it, `enact`
  resolves it against a live DOM, and the store keys chunks on it. Two
  elements that share a shape are two elements, so a shape cannot point at
  either of them. Whatever else changes, something has to keep saying which
  one.
"""

from __future__ import annotations

import argparse
import pathlib
import re
import statistics
import sys
from collections import Counter, defaultdict

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

_INDEX = re.compile(r"\[\d+\]")


def shape(xpath: str) -> str:
    """The xpath with positions dropped -- the template, not the instance."""
    return _INDEX.sub("", xpath or "")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", type=pathlib.Path, required=True)
    args = ap.parse_args(argv)

    from vertiscope.workspace import Workspace

    with Workspace(args.workspace) as ws:
        chunks = list(ws.store.chunks())

        # --- what the projector shows twice ------------------------------
        by_text = defaultdict(list)
        for c in chunks:
            key = " ".join((c.md or "").split())
            if key:
                by_text[key].append(c)
        repeats = {k: v for k, v in by_text.items() if len(v) > 1}
        repeated_chunks = sum(len(v) for v in repeats.values())

        # Of those, how many are the same SHAPE on the same page -- i.e. the
        # same template repeated, which is exactly what an agnostic index
        # would merge?
        same_shape = 0
        for group in repeats.values():
            shapes = {(c.url, shape(c.xpath)) for c in group}
            if len(shapes) == 1:
                same_shape += len(group)

        # --- what collapses at the address level -------------------------
        addresses = []
        for c in chunks:
            addresses.extend(a for a, _v in ws.store.addresses_of(c.cid))
        exact = {(a.url, a.xpath, a.tag, a.accessor) for a in addresses}
        shaped = {(a.url, shape(a.xpath), a.tag, a.accessor) for a in addresses}

        # How many DISTINCT elements hide behind one shape, where it collapses?
        per_shape = Counter((a.url, shape(a.xpath), a.tag, a.accessor)
                            for a in addresses)
        collapsed = {k: n for k, n in per_shape.items() if n > 1}

        # And do those siblings carry the SAME content, or different content?
        # This is the whole question: merging repeats of one template is only
        # lossless where the repeats say the same thing.
        by_shape_values = defaultdict(set)
        for c in chunks:
            for a, v in ws.store.addresses_of(c.cid):
                by_shape_values[(a.url, shape(a.xpath), a.tag, a.accessor)].add(
                    " ".join((v or "").split())[:120])
        differing = {k: vs for k, vs in by_shape_values.items()
                     if len(vs) > 1}

    print("index-agnostic xpaths, measured on %s" % args.workspace)
    print("=" * 74)
    print()
    print("chunks                     %6d" % len(chunks))
    print("chunks whose markdown is   %6d  (%.1f%%)  -- identical to another chunk"
          % (repeated_chunks, 100 * repeated_chunks / max(1, len(chunks))))
    print("  of those, same template  %6d  -- same url and same xpath SHAPE,"
          % same_shape)
    print("                                   which is what an agnostic index merges")
    print()
    print("addresses                  %6d" % len(addresses))
    print("  distinct, with indices   %6d" % len(exact))
    print("  distinct, shape only     %6d  (%.1f%% fewer)"
          % (len(shaped), 100 * (1 - len(shaped) / max(1, len(exact)))))
    print("  shapes covering >1       %6d" % len(collapsed))
    if collapsed:
        counts = sorted(collapsed.values())
        print("     elements per shape    median %d   p90 %d   max %d"
              % (counts[len(counts) // 2],
                 counts[int(0.9 * len(counts))], counts[-1]))
    print()
    print("THE COST, measured:")
    print("  shapes whose members     %6d of %6d  (%.1f%%)"
          % (len(differing), len(collapsed),
             100 * len(differing) / max(1, len(collapsed))))
    print("  hold DIFFERENT content           -- these cannot be merged without")
    print("                                      losing one of the two")
    if differing:
        sample = list(differing.items())[:3]
        for (url, shp, tag, acc), values in sample:
            print()
            print("     %s  %s" % (tag, shp[-58:]))
            for v in list(values)[:3]:
                print("        %s" % v[:64])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
