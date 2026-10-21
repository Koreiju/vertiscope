"""End-to-end latency of the incremental loop, per pass, per phase.

The delta machinery has always been measured in *work*: nodes visited, prune
ratio, wire bytes. Those say the diff is doing the right thing. They do not
say what a consumer waits through, and that is the number that decides whether
"incremental" means anything outside a benchmark.

So this replays every capture in `tests/snapshots/` and times the whole path:

    tag     re-tag the DOM, reusing subtrees whose hash is unchanged
    trie    build the address trie from the tagged result
    diff    compare against the previous trie
    chunk   re-render the chunks the delta touched

`total_ms` is their sum — snapshot in, re-rendered chunks out. `ms_per_changed`
is that divided by the size of the delta, which is the O(delta) claim in the
units that can falsify it: work proportional to change means it stays roughly
flat as a page grows.

Measured 2026-08-15 over 12 passes that changed something:

    chunk render  79.9%      diff  0.7%      tag+trie  19.4%
    corr(total_ms, nodes)   = +0.992
    corr(total_ms, changed) = +0.928

The diff is 0.7% of the time it costs to use it. Everything around it scales
with the page, so end-to-end the loop is O(page) and the incrementality is
real only in the stage that is nearly free already. The sharpest single case:
archive.org's search page, pass 3 — **three** addresses changed, 218 ms spent,
because `dirty_chunks` renders the whole trie and then filters.

    python scripts/audit_delta_latency.py
    python scripts/audit_delta_latency.py --slug archive-org-search
"""

from __future__ import annotations

import argparse
import pathlib
import statistics as stats
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _force_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


_force_utf8_stdio()

from vertiscope.snapshots import available, load  # noqa: E402
from vertiscope.stream import StreamingScan  # noqa: E402


def _corr(xs, ys) -> float:
    if len(xs) < 2:
        return 0.0
    mx, my = stats.mean(xs), stats.mean(ys)
    num = sum((a - mx) * (b - my) for a, b in zip(xs, ys))
    den = (sum((a - mx) ** 2 for a in xs) * sum((b - my) ** 2 for b in ys)) ** 0.5
    return num / den if den else 0.0


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--slug", help="substring of a capture slug")
    ap.add_argument("--window", type=int, default=1200)
    args = ap.parse_args()

    slugs = available()
    if args.slug:
        slugs = [s for s in slugs if args.slug in s]
    if not slugs:
        print("no captures; run scripts/snapshot_pages.py")
        return 2

    print("=" * 96)
    print("DELTA LATENCY — snapshot in, re-rendered chunks out")
    print("=" * 96)
    print(f"{'capture':30s} {'pass':>4} {'nodes':>7} {'chg':>6} {'tag':>6} "
          f"{'trie':>6} {'diff':>6} {'chunk':>7} {'TOTAL':>8} {'ms/chg':>8}")
    print("-" * 96)

    rows = []
    for slug in slugs:
        meta, htmls = load(slug)
        scan = StreamingScan(meta["url"], context_window=args.window)
        for passno, html in enumerate(htmls):
            update = scan.push(html, passno=passno)
            scan.dirty_chunks(update)
            print(f"{slug[:30]:30s} {passno:>4} {update.nodes:>7} "
                  f"{update.changed:>6} {update.tag_ms:>6.0f} "
                  f"{update.trie_ms:>6.0f} {update.diff_ms:>6.1f} "
                  f"{update.chunk_ms:>7.0f} {update.total_ms:>8.0f} "
                  f"{update.ms_per_changed:>8.1f}")
            rows.append(update)

    # Passes where nothing changed are dropped. Averaging their zero
    # `ms_per_changed` in would make any implementation look better the more
    # often it was handed an unchanged page, which measures the capture
    # cadence rather than the code.
    moved = [r for r in rows if r.changed]
    if not moved:
        print("\nno pass changed anything; nothing to say about latency")
        return 0

    total = sum(r.total_ms for r in moved)
    chunk = sum(r.chunk_ms for r in moved)
    diff = sum(r.diff_ms for r in moved)
    print("-" * 96)
    print(f"{len(moved)} passes that changed something\n")
    print("  where the time goes")
    print(f"    chunk render {chunk/total:6.1%}    diff {diff/total:6.1%}"
          f"    tag+trie {(total-chunk-diff)/total:6.1%}")

    print("\n  what latency tracks  (1.0 = moves exactly with it)")
    print(f"    page size (nodes)  {_corr([r.nodes for r in moved], [r.total_ms for r in moved]):+.3f}")
    print(f"    change  (changed)  {_corr([r.changed for r in moved], [r.total_ms for r in moved]):+.3f}")

    per = sorted(r.ms_per_changed for r in moved)
    print(f"\n  ms per changed address   p50 {stats.median(per):.2f}   "
          f"max {per[-1]:.2f}")

    worst = max(moved, key=lambda r: r.ms_per_changed)
    print(f"    worst: {worst.changed} addresses changed, "
          f"{worst.total_ms:.0f} ms, over {worst.nodes:,} nodes")

    print("\n  The diff is the cheap part. If chunk render dominates and "
          "latency\n  tracks page size, the loop is O(page) end to end "
          "however good the\n  diff is — which is a statement about the "
          "design, not a slow function.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
