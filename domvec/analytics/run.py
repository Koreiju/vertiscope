"""Measure one page, end to end, and write the result as its own artifact.

This is deliberately not a REPL command. The REPL is the browser; analytics
are a separate instrument with a separate output, because a measurement that
only exists inside the tool it measures cannot be re-read, diffed across
commits, or trusted after the tool changes underneath it.

The phases, and why they are timed apart
----------------------------------------
The trie is built by a synchronous recursion over what the page reports
changed; vectorisation consumes the trie afterwards. Those are different
questions with different answers, and one total hides both:

  fold_ms      the mutation-chunking phase *inside the page* -- reported by
               the sensor as `repairMs`. This is the O(delta) algorithm
               itself, and it is a small fraction of the crossing, so a
               variant that sends less can look like a variant that computes
               faster unless the two are kept apart.
  drain_ms     the whole round trip: WebDriver toll, serialisation, transport.
  decode_ms    payload -> addressed units, on this side.
  trie_ms      units -> patricia trie. The recursion the goal names, and the
               one that must stay O(delta): a positional shift costs 1, not
               N+1.
  markdown_ms  trie -> the semantic projection.
  wire_ms      trie -> the visual projection (plus the geometry crossing,
               which is reported separately because it is a round trip, not
               a computation).
  embed_ms     the asynchronous phase. Chunks are pushed by id and embedded
               in batches behind a digest gate, so this is expected to be
               decoupled from the delta path -- and it is measured to show
               that rather than to assert it.
"""

from __future__ import annotations

import json
import pathlib
import time
from contextlib import contextmanager
from typing import Dict, Iterator, List, Optional, Sequence

from ..address import ContentAddress
from .affine import AffineReport, score_arrow, score_dedup
from .groundtruth import read_page_truth

__all__ = ["Phases", "measure_page", "write_artifact"]

DEFAULT_ARTIFACT_DIR = pathlib.Path("build_analytics")


class Phases:
    """Wall-clock per named phase, in milliseconds."""

    def __init__(self) -> None:
        self.ms: Dict[str, float] = {}

    @contextmanager
    def phase(self, name: str) -> Iterator[None]:
        started = time.perf_counter()
        try:
            yield
        finally:
            self.ms[name] = self.ms.get(name, 0.0) + (
                time.perf_counter() - started) * 1000.0

    def add(self, name: str, milliseconds: float) -> None:
        self.ms[name] = self.ms.get(name, 0.0) + float(milliseconds)


def _addresses_of_chunks(chunks):
    """(addresses, texts) for every rendered markdown line.

    The text travels beside the address because inline merging makes the
    address alone insufficient: a sentence broken across `<em>` and `<a>` is
    rejoined into one line addressed at the flow's owner, and the fragments'
    own addresses are then legitimately absent. The scorer uses the text only
    to confirm that specific merge at a specific ancestor.
    """
    pairs = [(line.address, line.text) for chunk in chunks
             for line in chunk.lines if line.address is not None]
    return [a for a, _t in pairs], [t for _a, t in pairs]


def measure_page(driver, url: str, *, scrolls: int = 2,
                 context_window: int = 1200,
                 embedder=None) -> AffineReport:
    """Load, read, render, and score one page against its own DOM.

    Every arrow scored here is an arrow through the patricia trie: the sensor
    writes addressed units *into* it, and both projections are read *out* of
    it. Nothing is compared renderer-to-renderer, because two renderers that
    are wrong in the same way agree perfectly.
    """
    from ..markdown import render_trie
    from ..sensing import Sensor
    from ..stream import StreamingScan
    from ..style import StyleMap
    from ..vectors import VectorQueue
    from ..wireframe import render_wireframe

    phases = Phases()
    total_started = time.perf_counter()

    driver.set_page_load_timeout(45)
    with phases.phase("load_ms"):
        driver.get(url)
        time.sleep(1.0)

    sensor = Sensor(driver, url, budget=context_window)
    sensor.boot()
    time.sleep(0.6)

    spine = StreamingScan(url, context_window=context_window)
    fold_ms = 0.0
    for passno in range(scrolls + 1):
        if passno:
            with phases.phase("scroll_ms"):
                sensor.scroll()
                time.sleep(0.4)
        snapshot = sensor.drain(passno)
        phases.add("drain_ms", snapshot.drain_ms)
        phases.add("decode_ms", snapshot.decode_ms)
        # The in-page mutation-chunking cost, reported by the fold itself.
        # Cumulative in the page, so the last reading is the running total.
        reported = (snapshot.stats or {}).get("repairMs")
        if isinstance(reported, (int, float)):
            fold_ms = float(reported)
        # Units into the trie. This is the write side of the map.
        with phases.phase("trie_ms"):
            spine.absorb(snapshot.units, snapshot.passno,
                         removed=snapshot.removed_addresses)
    phases.add("fold_ms", fold_ms)

    # Both projections are read back out of the trie.
    with phases.phase("markdown_ms"):
        chunks = render_trie(spine.trie, context_window=context_window)
    markdown_addresses, markdown_texts = _addresses_of_chunks(chunks)

    units = [(line.address, line.text, line.address.tag)
             for chunk in chunks for line in chunk.lines
             if line.address is not None and line.text.strip()]
    styles = StyleMap()
    wire_addresses: List[ContentAddress] = []
    wire_texts: List[str] = []
    if units:
        wanted = styles.missing(a.xpath for a, _t, _k in units)
        if wanted:
            with phases.phase("geometry_ms"):
                try:
                    styles.absorb(wanted, sensor.styles(
                        [type("A", (), {"xpath": x})() for x in wanted]))
                except Exception:  # noqa: BLE001 - no geometry, no wireframe
                    pass
        with phases.phase("wire_ms"):
            try:
                frame = render_wireframe(units, styles, width=200)
                for line in frame.lines:
                    for a in (line.addresses or []):
                        wire_addresses.append(a)
                        wire_texts.append(line.text)
            except Exception:  # noqa: BLE001
                wire_addresses, wire_texts = [], []

    # The asynchronous phase, measured rather than asserted. With no embedder
    # this reports the queue's own cost and an `embedded` count of zero, which
    # is the honest reading of "decoupled": the delta path did not wait.
    queue = VectorQueue()
    with phases.phase("embed_queue_ms"):
        for chunk in chunks:
            queue.push(chunk.cid, chunk.markdown)
    with phases.phase("embed_ms"):
        queue.flush(embedder)

    with phases.phase("groundtruth_ms"):
        truth = read_page_truth(driver, url)

    trie_addresses = [leaf.address for leaf in
                      (spine.trie.leaves() if spine.trie else [])]

    report = AffineReport(url=url, page=truth)
    report.arrows = [
        score_arrow("page->trie", truth, trie_addresses, denominator="all"),
        score_arrow("page->markdown", truth, markdown_addresses,
                    denominator="all", texts=markdown_texts),
        # The drawing is answerable for what the page draws and nothing else.
        score_arrow("page->wireframe", truth, wire_addresses,
                    denominator="drawn", texts=wire_texts),
    ]
    report.dedup = score_dedup(truth, markdown_addresses,
                               texts=markdown_texts)

    phases.ms["total_ms"] = (time.perf_counter() - total_started) * 1000.0
    phases.ms["queue_pushed"] = float(queue.pushed)
    phases.ms["queue_queued"] = float(queue.queued)
    phases.ms["queue_skipped"] = float(queue.skipped)
    phases.ms["queue_embedded"] = float(queue.embedded)
    report.timings = phases.ms
    return report


def write_artifact(report: AffineReport,
                   directory: Optional[pathlib.Path] = None) -> pathlib.Path:
    """Append one page's measurement to the analytics record."""
    directory = pathlib.Path(directory or DEFAULT_ARTIFACT_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "affine.jsonl"
    row = report.as_dict()
    row["t"] = time.time()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, separators=(",", ":")) + "\n")
    return path


def render_table(report: AffineReport) -> str:
    """The measurement, as a page of text a person can read."""
    page = report.page
    rows: List[str] = ["", f"  affine map  {report.url}", ""]
    if page is not None:
        rows.append(
            f"  page: {len(page.units):,} units "
            f"({len(page.drawn):,} drawn), {page.elements:,} elements, "
            f"{page.shadow_hosts} shadow host(s), "
            f"{page.opaque_hosts} opaque")
        rows.append("")
    rows.append(f"  {'arrow':<17}{'recall':>8}{'prec':>8}{'inject':>8}"
                f"{'TP':>7}{'FN':>6}{'FP':>5}{'TN':>6}{'dup':>5}")
    for arrow in report.arrows:
        c = arrow.overall
        rows.append(
            f"  {arrow.name:<17}{c.recall * 100:>7.1f}%{c.precision * 100:>7.1f}%"
            f"{c.injectivity * 100:>7.1f}%{c.tp:>7,}{c.fn:>6,}{c.fp:>5,}"
            f"{c.tn:>6,}{c.duplicated:>5,}")
    rows.append("")
    rows.append("  by origin (recall), page->markdown / page->wireframe")
    for arrow in report.arrows[1:]:
        for origin in ("light", "shadow"):
            c = arrow.by_origin.get(origin)
            if c is None:
                continue
            rows.append(f"    {arrow.name:<17}{origin:<8}"
                        f"{c.recall * 100:>7.1f}%   of {c.tp + c.fn:>6,}")
    rows.append("")
    d = report.dedup
    rows.append("  deduplication")
    rows.append(f"    {'redundant page units':<26}{d.redundant_pairs:>8,}")
    rows.append(f"    {'collapsed correctly':<26}{d.collapsed:>8,}")
    rows.append(f"    {'under-dedup (noise)':<26}{d.under_dedup:>8,}")
    rows.append(f"    {'over-dedup (loss)':<26}{d.over_dedup:>8,}")
    rows.append(f"    {'distinct kept':<26}{d.distinct_kept:>8,}")
    rows.append(f"    {'correctness':<26}{d.correctness * 100:>7.1f}%")
    rows.append("")
    rows.append("  phases (ms)")
    order = ("fold_ms", "drain_ms", "decode_ms", "trie_ms", "markdown_ms",
             "geometry_ms", "wire_ms", "embed_queue_ms", "embed_ms",
             "groundtruth_ms", "load_ms", "scroll_ms", "total_ms")
    for name in order:
        if name in report.timings:
            rows.append(f"    {name:<18}{report.timings[name]:>10.1f}")
    rows.append("")
    return "\n".join(rows)
