#!/usr/bin/env python
"""LIVE end-to-end evidence: fresh pages, streaming snapshots, real O(delta).

Everything else in this repo measures against the frozen corpus, which is one
snapshot per page. That cannot exercise the incremental path at all: with one
snapshot there is no second one to diff against, so an O(delta) claim tested
there is a claim about synthetic mutations, not about scanning.

This probe runs the real thing:

    real Firefox -> real navigation -> real scroll/settle loop
      -> a full snapshot per settle pass
      -> tag, address, trie, diff against the previous pass
      -> re-render only the chunks the delta touched
      -> ingest into kuzu, index, and retrieve

and asserts the property that matters:

    **the work done per update tracks the change, not the page size**

Exits non-zero if that fails, so it is usable as a gate rather than as a
report. Every assertion names what it would falsify.

    python scripts/probe_live_delta.py
    python scripts/probe_live_delta.py --url https://news.ycombinator.com/ --headful
    python scripts/probe_live_delta.py --duration 30 --passes 8
"""

from __future__ import annotations

import argparse
import pathlib
import shutil
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _force_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


_force_utf8_stdio()

from vertiscope.address import addresses_of, collisions  # noqa: E402
from vertiscope.browser import browser_session  # noqa: E402
from vertiscope.capture import stream_snapshots  # noqa: E402
from vertiscope.config import load_config  # noqa: E402
from vertiscope.graphstore import GraphStore  # noqa: E402
from vertiscope.markdown import write_jsonl  # noqa: E402
from vertiscope.search import SearchDiagnostics, ThreeFormIndex  # noqa: E402
from vertiscope.stream import ScanUpdate, StreamingScan  # noqa: E402
from vertiscope.vectors import FreqMatrix  # noqa: E402

# Pages that *change while being driven*. This matters more than it looks:
# the first version of this probe pointed at Hacker News and reported a
# 1,946x saving, which was meaningless — HN settles on the first pass, so
# every later pass was unchanged and the "saving" was the cost of proving
# nothing had happened. A probe that cannot observe a delta cannot verify the
# delta property, however green it prints.
#
# These are purpose-built scraping-practice sites with real infinite scroll,
# so driving them produces genuine content growth pass over pass.
DEFAULT_URLS = [
    "https://quotes.toscrape.com/scroll",
    "https://quotes.toscrape.com/js-delayed/",
]


class ProbeFailure(AssertionError):
    pass


def _queries_from(freq, n: int = 4) -> list:
    """Pick discriminating terms out of the freq matrix to query with.

    Mid-document-frequency unigrams: a term in every chunk separates nothing,
    and a term in one chunk tests only that nothing crashed. Terms appearing
    in a middling share of chunks are the ones a ranking has to actually rank.
    """
    df = freq.document_frequency()
    rows = max(freq.shape[0], 1)
    scored = []
    for term, col in freq.vocab.items():
        if " " in term or len(term) < 4 or not term.isalpha():
            continue
        share = float(df[col]) / rows
        if 0.15 <= share <= 0.6:
            scored.append((abs(share - 0.35), term))
    scored.sort()
    return [term for _d, term in scored[:n]] or ["the"]


def check(condition: bool, message: str, detail: str = "") -> None:
    status = "PASS" if condition else "FAIL"
    print(f"  [{status}] {message}" + (f"  ({detail})" if detail else ""))
    if not condition:
        raise ProbeFailure(f"{message}: {detail}")


def scan_one(url: str, cfg, args, out: pathlib.Path) -> dict:
    print(f"\n{'=' * 78}\n{url}\n{'=' * 78}")
    scan = StreamingScan(url, context_window=args.window)
    started = time.perf_counter()

    print(ScanUpdate.header())
    with browser_session(cfg, headless=not args.headful) as driver:
        for passno, snapshot in stream_snapshots(
            driver, url,
            max_duration=args.duration,
            pause=args.pause,
            max_snapshots=args.passes,
            incremental=not args.full_transport,
        ):
            update = scan.push(snapshot, passno)
            dirty = scan.dirty_chunks(update)
            print(update.row() + f" {len(dirty):>6} dirty")

    elapsed = time.perf_counter() - started
    summary = scan.summary()
    if not summary:
        raise ProbeFailure(f"{url}: the scan produced no snapshot at all")
    print(f"\n  {summary}")
    print(f"  wall clock {elapsed:.1f}s")

    # --- the claims ------------------------------------------------------
    print("\n  claims")
    check(summary["passes"] >= 2,
          "the scan streamed more than one snapshot",
          f"{summary['passes']} passes — a single pass cannot exercise a delta")

    steady = scan.updates[1:]
    busy = [u for u in steady if u.changed > 0]
    quiet = [u for u in steady if u.changed == 0]

    # THE GATE. Everything below measures how cheaply change was handled, and
    # all of it is vacuous if nothing changed. A static page yields a huge
    # "saving" that is really the cost of confirming nothing happened, so a
    # run with no observed change is a failed probe, not a passing one.
    #
    # Scoped to the *probe*, not to each page. Whether a given page mutates
    # inside the scan window is a fact about that site's JavaScript, not about
    # this code: `quotes.toscrape.com/js-delayed/` races its own delay against
    # the first settle and had finished loading before pass 1, which failed a
    # run in which `/scroll` had exercised the incremental path perfectly well.
    # Requiring *every* listed page to change made the probe depend on a third
    # party's timing; requiring *some* page to change keeps the whole
    # anti-flattery guarantee — a run where nothing moved anywhere still
    # fails — and `main` enforces it across the results.
    if not busy:
        print(f"  [skip] {url} did not change during the scan "
              f"({len(steady)} steady pass(es)) — not exercised")
        return {"url": url, "scan": scan, "summary": summary,
                "exercised": False}

    grew = summary["final_leaves"] > len(scan.updates[0].delta.added)
    check(grew,
          "content arrived after the first snapshot",
          f"{len(scan.updates[0].delta.added):,} addresses on pass 1 -> "
          f"{summary['final_leaves']:,} at the end")

    rescan_cost = summary["total_nodes_if_rescanned"]
    incremental_cost = summary["total_visited"]
    check(incremental_cost < rescan_cost,
          "incremental indexing beat re-indexing from scratch",
          f"{incremental_cost:,} nodes visited vs {rescan_cost:,} re-scanned "
          f"({rescan_cost / max(incremental_cost, 1):.1f}x)")

    # On the passes that *did* change, the cost must stay well under a rescan.
    # This is the claim that matters and the one only a changing page can test.
    worst = max(u.visited / max(u.nodes, 1) for u in busy)
    check(worst < 0.75,
          "a changed pass visited well under the whole trie",
          f"worst {worst * 100:.1f}% of nodes visited across "
          f"{len(busy)} changed pass(es)")

    # Cost must track the change rather than the page. Compare the busiest
    # pass against the quietest: if visits were driven by page size they would
    # be similar, since the page is the same size in both.
    if quiet:
        loudest = max(u.visited for u in busy)
        quietest = max(u.visited for u in quiet)
        check(loudest > quietest,
              "a changed pass cost more than an unchanged pass of the same page",
              f"{loudest} vs {quietest} visits at ~{busy[-1].nodes:,} nodes")
        check(quietest <= 4,
              "an unchanged pass cost a constant number of comparisons",
              f"worst {quietest} visits over {len(quiet)} unchanged pass(es)")

    # The transport must shrink too, or the walker's hashing bought nothing.
    #
    # Compared against each pass's *own* document, not against the first pass.
    # The first version compared a later pass to pass one and failed on a page
    # that grew — correctly reporting "-106% saved" because the document had
    # doubled. Growth is the case this exists for, so the baseline has to be
    # the document that pass would otherwise have moved.
    if not args.full_transport and quiet:
        worst_quiet = max(u.wire_ratio for u in quiet)
        check(worst_quiet < 0.5,
              "an unchanged pass moved a fraction of its own document",
              f"worst {worst_quiet * 100:.1f}% of "
              f"{max(u.snapshot_bytes for u in quiet):,} bytes")
        pruned = max(u.pruned_subtrees for u in steady)
        check(pruned > 0,
              "the in-page walker pruned unchanged subtrees",
              f"max {pruned} subtree(s) replaced by a placeholder")
        saved = 1.0 - (sum(u.wire_bytes for u in steady)
                       / max(sum(u.snapshot_bytes for u in steady), 1))
        check(saved > 0.3,
              "the stream as a whole moved substantially fewer bytes",
              f"{saved * 100:.1f}% saved across {len(steady)} steady pass(es)")

    # Rendering must follow the delta too, or the diff bought nothing.
    check(max(len(u.dirty_chunks) for u in busy) > 0,
          "changed passes produced dirty chunks to re-render",
          f"max {max(len(u.dirty_chunks) for u in busy)} chunk(s) per pass")

    # And re-rendering must touch fewer chunks than the page has, or the
    # "only re-render what changed" claim is doing nothing.
    from vertiscope.markdown import render_trie

    total_chunks = len(render_trie(scan.trie, context_window=args.window))
    worst_dirty = max(len(u.dirty_chunks) for u in busy)
    check(worst_dirty < total_chunks,
          "a delta re-rendered a strict subset of the page's chunks",
          f"worst {worst_dirty} dirty of {total_chunks} total")

    # --- addressing still holds on live input ----------------------------
    final = scan.trie
    print("\n  addressing")
    check(len(final) > 0, "the final trie holds addresses", f"{len(final):,}")
    keys = [a.key() for a in final.addresses()]
    check(len(keys) == len(set(keys)),
          "every address in the live trie is distinct",
          f"{len(keys):,} addresses")

    return {
        "url": url,
        "summary": summary,
        "scan": scan,
        "elapsed": elapsed,
        "exercised": True,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", action="append", default=[])
    ap.add_argument("--duration", type=int, default=25,
                    help="seconds to keep driving each page")
    ap.add_argument("--pause", type=float, default=1.2,
                    help="settle pause between passes")
    ap.add_argument("--passes", type=int, default=6,
                    help="maximum snapshots per page")
    ap.add_argument("--window", type=int, default=1200)
    ap.add_argument("--headful", action="store_true")
    ap.add_argument("--full-transport", action="store_true",
                    help="disable subtree pruning, to measure against it")
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "build_live")
    args = ap.parse_args()

    urls = args.url or DEFAULT_URLS
    cfg = load_config()
    out = args.out
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)

    print(f"live delta probe — {len(urls)} url(s), "
          f"{args.duration}s each, up to {args.passes} passes")

    results = []
    try:
        for url in urls:
            results.append(scan_one(url, cfg, args, out))

        # THE GATE, at the scope where it belongs. Whether a *given* page
        # mutates inside the scan window is a fact about that site's
        # JavaScript; whether *any* did is a fact about this run, and it is
        # the one the O(delta) claim rests on. A run in which nothing moved
        # anywhere still fails, which is the whole anti-flattery property.
        exercised = [r for r in results if r.get("exercised")]
        check(bool(exercised),
              "some page changed while being driven",
              f"{len(exercised)} of {len(results)} page(s) exercised the "
              f"incremental path — a static run measures the cost of "
              f"confirming nothing happened")
    except ProbeFailure as exc:
        print(f"\nPROBE FAILED: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"\nPROBE ERROR: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
        return 2

    # --- end to end: store, index, retrieve ------------------------------
    print(f"\n{'=' * 78}\nend to end: store -> index -> retrieve\n{'=' * 78}")
    freq = FreqMatrix()
    try:
        with GraphStore(out / "graph.kuzu") as store:
            for result in results:
                store.conn.execute(
                    "MERGE (p:Page {url: $url}) SET p.title='', p.scanned_at=0.0,"
                    " p.root_hash='', p.chunk_count=0, p.address_count=0",
                    {"url": result["url"]},
                )
            for result in results:
                scan = result["scan"]
                from vertiscope.markdown import render_trie

                chunks = render_trie(scan.trie, context_window=args.window)
                addresses = [(n.address, n.value, n.content_hash)
                             for n in scan.trie.leaves() if n.address is not None]
                rows = {c.cid: freq.add(c.cid, c.markdown) for c in chunks}
                counts = store.ingest(result["url"], addresses, chunks, rows=rows,
                                      root_hash=scan.trie.root_hash)
                slug = result["url"].split("//")[-1].replace("/", "_")[:60]
                write_jsonl(chunks, out / f"{slug}.jsonl")
                print(f"  {result['url'][:52]:52s} {counts}")

            freq.save(out / "freq")
            index = ThreeFormIndex(store, freq).build()
            print(f"\n  graph {store.stats()}")
            print(f"  freq  {freq.shape[0]:,} x {freq.shape[1]:,}")

            # Queries drawn from what was actually indexed, not a fixed list.
            # The first version asked a quotes site about "software" and
            # "news" and reported a retrieval failure that was really a badly
            # chosen question. The property worth testing is that content just
            # indexed is findable, so the query has to come from the content.
            queries = _queries_from(freq, n=4)
            print(f"\n  retrieval  (queries drawn from the index: {queries})")
            found = 0
            for query in queries:
                diag = SearchDiagnostics()
                hits = index.search(query, k=2, diagnostics=diag)
                found += len(hits)
                for hit in hits:
                    print(f"    {query:10s} {hit.score:.2e} "
                          f"{hit.url.split('//')[-1][:34]:34s} "
                          f"{hit.preview(1)[:40]}")
                if not hits:
                    print(f"    {query:10s} (no hit)")

            print()
            check(found > 0,
                  "live-scanned content is retrievable end to end",
                  f"{found} hit(s) across 4 queries")

            # the navigational requirement, on live data
            any_chunk = store.chunks()[0]
            back = store.addresses_of(any_chunk.cid)
            check(bool(back),
                  "a stored chunk resolves back to its addresses",
                  f"{len(back)} address(es) on {any_chunk.cid}")
            aid = back[0][0].aid
            check(store.chunk_for_address(aid) is not None,
                  "an address resolves forward to its chunk",
                  aid)
    except ProbeFailure as exc:
        print(f"\nPROBE FAILED: {exc}")
        return 1

    print(f"\nwrote {out.relative_to(ROOT)}/")
    print("\nPROBE PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
