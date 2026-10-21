"""The live sweep: the whole product path, on live pages, scrolled.

For each url this runs `Workspace.scan` — the same path `vertiscope scan`
runs — with the in-page chunk engine injected, at least ten scroll
passes, and `incremental=True` so the Merkle-pruned transport is live.
Then it searches the store the scan just wrote. End to end means the
whole chain: browser -> in-page engine -> pruned transport -> trie ->
chunks -> store -> retrieval. No stage is stubbed and none is rebuilt
here.

An earlier version of this script measured a second pipeline instead:
full `deep_serialize` per scroll with no `known` hashes — the mode the
serializer's docstring calls the naive transport — re-diffed in Python.
It reported end-to-end latency as O(page). That was a property of the
opt-out, not of the design. Driven properly the same page saves 85.7%
of bytes on the wire and an unchanged pass visits one node.

Parallelism is by **browser**: one Firefox and one workspace per worker
process, reused across pages. A browser costs ~400 MB and seconds to
start, so sizing this pool like a parse pool would swap the machine.

    python scripts/sweep_live.py --limit 200 --browsers 4
    python scripts/sweep_live.py --report
"""

from __future__ import annotations

import argparse
import atexit
import collections
import json
import pathlib
import statistics as stats
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

from vertiscope.bench import run_pages, summarise  # noqa: E402

BUILD = ROOT / "build" / "sweep"
FRAME = BUILD / "frame.json"
RESULTS = BUILD / "live.jsonl"

# Minimum scrolls per page. Below this a page that lazy-loads in two or three
# steps looks settled when it is not, and its delta passes get recorded as
# no-change — which would quietly bias the latency distribution toward the
# cheap case.
MIN_SCROLLS = 10

_DRIVER = None


def _driver():
    """One browser per worker process, built lazily and reused.

    Starting Firefox costs seconds and hundreds of megabytes, so a per-page
    driver would spend most of the sweep in startup. Module-global because a
    worker process is the natural lifetime: `max_tasks_per_child` recycles the
    process, and the atexit hook closes the browser with it.
    """
    global _DRIVER
    if _DRIVER is None:
        from vertiscope.browser import build_driver
        from vertiscope.config import load_config
        _DRIVER = build_driver(load_config(), headless=True)
        atexit.register(_quit_driver)
    return _DRIVER


def _quit_driver() -> None:
    global _DRIVER
    if _DRIVER is not None:
        try:
            _DRIVER.quit()
        except Exception:  # noqa: BLE001 - teardown must not mask a result
            pass
        _DRIVER = None


_WORKSPACE = None


def _workspace():
    """One workspace per worker process, opened lazily and reused.

    The store is the far end of the chain, so the sweep has to write to a
    real one — an in-memory stand-in would sequester exactly the stage this
    is here to exercise. Per worker rather than shared: concurrent writers to
    one kuzu file is a different test than the one being run.
    """
    global _WORKSPACE
    if _WORKSPACE is None:
        import os
        from vertiscope.workspace import Workspace
        home = BUILD / "ws" / f"w{os.getpid()}"
        home.mkdir(parents=True, exist_ok=True)
        # Constructing it opens (and creates) it — the CLI does the same and
        # uses it as a context manager; here the lifetime is the worker
        # process, so the atexit hook is what closes it.
        _WORKSPACE = Workspace(home)
        atexit.register(_close_workspace)
    return _WORKSPACE


def _close_workspace() -> None:
    global _WORKSPACE
    if _WORKSPACE is not None:
        try:
            _WORKSPACE.close()
        except Exception:  # noqa: BLE001 - teardown must not mask a result
            pass
        _WORKSPACE = None


def measure_live(page: dict) -> dict:
    """Run the whole product path on one live page, then query what it stored.

    This calls `Workspace.scan`, which is the same code path `vertiscope scan`
    runs: inject the in-page chunk engine, drive the page for N passes, and
    fold each snapshot in with `incremental=True` so the Merkle-pruned
    transport is live and unchanged subtrees never cross the bridge. Then it
    searches the store, because a scan that persists nothing retrievable has
    not finished the job.

    The previous version of this function did none of that. It called
    `deep_serialize` with no `known` map — the mode the serializer's own
    docstring labels "the naive transport", kept for comparison — and rebuilt
    the diff in Python. It measured a second pipeline I had built beside the
    real one, and reported its O(page) latency as the design's. The whole
    point of the engine is that the unchanged bytes never move; opting out of
    that and then timing the result measures the opt-out.
    """
    from vertiscope.workspace import Workspace

    url = page["url"]
    passes = int(page.get("scrolls", MIN_SCROLLS)) + 1  # +1 for the cold pass
    started = time.perf_counter()

    ws = _workspace()
    result = ws.scan(url, passes=passes, pause=float(page.get("pause", 0.6)),
                     duration=int(page.get("duration", 30)),
                     incremental=True, driver=_driver())
    scan_ms = (time.perf_counter() - started) * 1000

    # Close the loop: retrieve from the store the scan just wrote. Query
    # drawn from the page's own text so a miss means the chain broke, not
    # that the query was unlucky.
    probe = ""
    for update in result.updates:
        for chunk in update.dirty_chunks:
            for line in chunk.lines:
                words = line.text.split()
                if len(words) >= 4:
                    probe = " ".join(words[:4])
                    break
            if probe:
                break
        if probe:
            break

    hits, retrieve_ms = [], 0.0
    if probe:
        t = time.perf_counter()
        hits = ws.search(probe, k=10)
        retrieve_ms = (time.perf_counter() - t) * 1000

    # --- the REPL, which is the actual terminus -------------------------
    # Same construction `vertiscope browse` uses: a Repl over the store the scan
    # just wrote, opened on this url. Not a Document built here from chunks
    # held in memory — that would skip the store round-trip and re-introduce
    # the parallel-pipeline mistake at the last stage, which is exactly the
    # stage whose correctness has been assumed all day rather than exercised.
    from vertiscope.repl.app import Repl

    repl_ms = repaint_bad = widgets = controls = 0
    screen_lines = 0
    opened = False
    t = time.perf_counter()
    try:
        repl = Repl(store=ws.store, index=ws.index)
        repl.state.rows, repl.state.cols = 40, 120
        opened = bool(repl.load_url_from_store(url))
        if opened:
            document = repl.state.document
            widgets = len(document.lines)
            controls = sum(1 for w in document.lines if w.interactive)
            # The repaint invariant, checked where it actually matters: a
            # widget must repaint to the line it was built from. Three real
            # defects hid here, and all three left the markdown correct, so
            # nothing upstream of the REPL could see them.
            #
            # The source lines come back out of the store the same way the
            # REPL got them, so this compares the screen against what was
            # persisted — not against chunks still held in memory.
            resolved = repl.store.resolve_page(url) or url
            source = []
            for row in sorted(repl.store.chunks(resolved),
                              key=lambda c: (c.xpath, c.part)):
                texts = row.md.split("\n")
                # Same skip the REPL applies: a chunk whose line count and
                # anchor count disagree is not rendered, so counting it here
                # would shift every comparison after it and report hundreds
                # of false repaint failures.
                if len(repl.store.addresses_of(row.cid)) != len(texts):
                    continue
                source.extend(texts)
            # The stored markdown carries its own indentation, so a widget
            # must repaint to the persisted line verbatim.
            repaint_bad = sum(1 for w, text in zip(document.lines, source)
                              if w.render() != text)
            screen_lines = len(repl.render().splitlines())
    except Exception as exc:  # noqa: BLE001 - a broken REPL is a result
        return {"page": url, "host": page.get("host", ""),
                "error": f"repl: {type(exc).__name__}: {exc}",
                "addresses": result.addresses, "chunks": result.chunks,
                "wire_saving": round(result.wire_saving, 4)}
    repl_ms = (time.perf_counter() - t) * 1000

    # Per-pass, straight off the ScanUpdate the scan already produced. No
    # parallel instrumentation: these are the columns `vertiscope scan` prints.
    passes_out = [{
        "pass": u.passno,
        "doc_bytes": u.snapshot_bytes,
        "wire_bytes": u.wire_bytes,
        "wire_ratio": round(u.wire_ratio, 4),
        "nodes": u.nodes,
        "changed": u.changed,
        "visited": u.visited,
        "prune_ratio": round(u.prune_ratio, 4),
        "tag_ms": round(u.tag_ms, 1),
        "trie_ms": round(u.trie_ms, 1),
        "diff_ms": round(u.diff_ms, 2),
        "total_ms": round(u.total_ms, 1),
    } for u in result.updates]
    moved = [p for p in passes_out if p["changed"]]
    still = [p for p in passes_out if not p["changed"]]

    return {
        "page": url,
        "host": page.get("host", ""),
        "seconds": round(time.perf_counter() - started, 2),
        "scan_ms": round(scan_ms, 1),
        # what the scan produced
        "addresses": result.addresses,
        "chunks": result.chunks,
        "lines": result.lines,
        "passes": result.passes,
        # the O(delta) claim, as the transport measures it
        "wire_saving": round(result.wire_saving, 4),
        "document_bytes": result.document_bytes,
        "wire_bytes": result.wire_bytes,
        "unchanged_passes": len(still),
        "unchanged_visited_max": max((p["visited"] for p in still), default=0),
        "unchanged_total_ms_p50": (round(stats.median(
            [p["total_ms"] for p in still]), 1) if still else 0.0),
        "changed_total_ms_p50": (round(stats.median(
            [p["total_ms"] for p in moved]), 1) if moved else 0.0),
        # the render accounting the scan already keeps
        "unaccounted": len(getattr(result.report, "unaccounted", []) or []),
        # and the far end of the chain
        "probe": probe,
        "hits": len(hits),
        "retrieve_ms": round(retrieve_ms, 1),
        # the REPL — the terminus, not an assumption
        "repl_opened": opened,
        "repl_ms": round(repl_ms, 1),
        "repl_widgets": widgets,
        "repl_controls": controls,
        "repl_screen_lines": screen_lines,
        "repaint_bad": repaint_bad,
        "passes_detail": passes_out,
    }


def report(rows: list) -> None:
    """What the chain did, stage by stage, over every page driven.

    Every number here is one the scan already produced — `wire_saving`,
    `visited`, `prune_ratio` come off `ScanUpdate`, `unaccounted` off the
    render report, and the hits off a real query against the store. Nothing
    is recomputed by this script, which is the point: a benchmark that
    reimplements the thing it measures ends up measuring the reimplementation.
    """
    good = [r for r in rows if "error" not in r]
    print("=" * 88)
    print(f"LIVE SWEEP — {len(rows):,} pages, {len(good):,} driven, "
          f"{len(rows) - len(good):,} failed")
    print("=" * 88)
    if not good:
        return

    print("\nTRANSPORT — what never crossed the bridge")
    saving = summarise(good, ["wire_saving", "document_bytes", "wire_bytes"])
    for key, label in (("wire_saving", "bytes saved"),
                       ("document_bytes", "document bytes"),
                       ("wire_bytes", "wire bytes")):
        v = saving.get(key)
        if v:
            print(f"    {label:18s} p50 {v['p50']:12,.0f}   "
                  f"p90 {v['p90']:12,.0f}   min {v['min']:12,.0f}")

    still = [r for r in good if r["unchanged_passes"]]
    if still:
        print("\nUNCHANGED PASSES — the O(delta) claim at its cleanest")
        v = summarise(still, ["unchanged_visited_max", "unchanged_total_ms_p50",
                              "changed_total_ms_p50"])
        for key, label in (("unchanged_visited_max", "nodes visited (max)"),
                           ("unchanged_total_ms_p50", "latency ms"),
                           ("changed_total_ms_p50", "latency ms when changed")):
            d = v.get(key)
            if d:
                print(f"    {label:24s} p50 {d['p50']:9.1f}   "
                      f"p90 {d['p90']:9.1f}   max {d['max']:9.1f}")

    print("\nTHE FAR END — the store, queried for text the scan just saw")
    retrieved = [r for r in good if r.get("probe")]
    missed = [r for r in retrieved if not r["hits"]]
    print(f"    pages queried        {len(retrieved):,} of {len(good):,}")
    print(f"    pages with no hit    {len(missed):,}"
          f"{'  <-- the chain broke here' if missed else ''}")
    v = summarise(retrieved, ["hits", "retrieve_ms", "addresses", "chunks"])
    for key, label in (("hits", "hits"), ("retrieve_ms", "retrieve ms"),
                       ("addresses", "addresses"), ("chunks", "chunks")):
        d = v.get(key)
        if d:
            print(f"    {label:20s} p50 {d['p50']:9.1f}   p90 {d['p90']:9.1f}")

    unaccounted = [r for r in good if r.get("unaccounted")]
    print(f"\nRENDER ACCOUNTING — pages with unaccounted content: "
          f"{len(unaccounted):,}"
          f"{'  <-- LOOK' if unaccounted else ''}")

    errors = collections.Counter(
        r["error"].split(":")[0] for r in rows if "error" in r)
    if errors:
        print("\nFAILURES by kind")
        for kind, count in errors.most_common(10):
            print(f"    {count:6d}  {kind}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--browsers", type=int, default=4,
                    help="parallel browsers (memory-bound, not core-bound)")
    ap.add_argument("--scrolls", type=int, default=MIN_SCROLLS)
    ap.add_argument("--pause", type=float, default=0.6,
                    help="seconds to settle after each scroll")
    ap.add_argument("--timeout", type=float, default=300.0)
    ap.add_argument("--frame", type=pathlib.Path)
    ap.add_argument("--results", type=pathlib.Path)
    ap.add_argument("--report", action="store_true")
    args = ap.parse_args()

    results_path = args.results or RESULTS
    if args.report:
        rows = [json.loads(l) for l in
                results_path.read_text(encoding="utf-8").splitlines()
                if l.strip()]
        report(rows)
        return 0

    if args.scrolls < MIN_SCROLLS:
        ap.error(f"--scrolls must be at least {MIN_SCROLLS}: fewer makes a "
                 f"lazy-loading page look settled when it is not")

    frame_path = args.frame or FRAME
    if not frame_path.exists():
        print("no frame; run scripts/sweep.py --build-frame")
        return 2
    frame = json.loads(frame_path.read_text(encoding="utf-8"))
    import random
    random.Random(20260815).shuffle(frame)
    if args.limit:
        frame = frame[: args.limit]

    work = [{"page": f["url"], "url": f["url"], "host": f["host"],
             "scrolls": args.scrolls, "pause": args.pause} for f in frame]

    print(f"driving {len(work):,} pages, {args.scrolls} scrolls each, "
          f"{args.browsers} browsers")
    started = time.perf_counter()
    done = 0
    for row in run_pages(work, measure_live, jobs=args.browsers,
                         timeout=args.timeout, results_path=results_path):
        done += 1
        if done % 10 == 0:
            rate = done / (time.perf_counter() - started)
            print(f"  {done:,}/{len(work):,}  {rate*60:.1f} pages/min",
                  flush=True)

    rows = [json.loads(l) for l in
            results_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    report(rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
