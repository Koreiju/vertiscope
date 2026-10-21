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
from .affine import AffineReport, score_arrow, score_dedup, score_order
from .groundtruth import read_page_truth

__all__ = ["Phases", "measure_page", "write_artifact"]

from .runs import stamp

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
    pairs = []
    for chunk in chunks:
        for line in chunk.lines:
            if line.address is None:
                continue
            pairs.append((line.address, line.text))
            # Addresses folded into this line by the inline-flow merge.
            #
            # A sentence with a link in it is ONE line and several
            # addresses. Counting only the first told the arrows that every
            # other fragment had never been rendered: page->markdown went
            # from 1,937 missed to 18,918 and dedup's over-collapse from 621
            # to 18,672, on a change that had not dropped a single unit.
            #
            # The line's text travels with each, which is what the scorer
            # wants -- it uses the text to confirm exactly this merge at
            # exactly this ancestor.
            for merged in line.inline:
                pairs.append((merged, line.text))
    return [a for a, _t in pairs], [t for _a, t in pairs]


def measure_page(driver, url: str, *, scrolls: int = 2,
                 context_window: int = 1200,
                 embedder=None, variants=None) -> AffineReport:
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

    # The sensor under test, which may be running a non-default
    # mechanism. Ground truth below is read from the page itself and is
    # unaffected, which is what keeps the comparison honest.
    sensor = Sensor(driver, url, budget=context_window,
                    variants=variants or {})
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
                         removed=snapshot.removed_addresses,
                         moved=snapshot.moved_addresses)
    phases.add("fold_ms", fold_ms)

    # One last drain, immediately before ground truth is read.
    #
    # The two sides of the map must be sampled at the same moment or the gap
    # between them is scored as capture loss. Ground truth used to be read
    # after the projections had been rendered and a geometry round trip had
    # crossed the boundary, and salesforce.com lazy-loads images on scroll --
    # so an <img> that arrived during that window was in the page, absent from
    # the trie, and counted against capture. It was never a capture defect;
    # it was a photograph taken after the subject moved.
    #
    # Writes into the trie, so what ground truth is compared against is the
    # trie as of the instant ground truth was taken.
    settling = sensor.drain(scrolls + 1)
    with phases.phase("trie_ms"):
        spine.absorb(settling.units, settling.passno,
                     removed=settling.removed_addresses,
                     moved=settling.moved_addresses)
    if isinstance((settling.stats or {}).get("repairMs"), (int, float)):
        phases.ms["fold_ms"] = float(settling.stats["repairMs"])
    snapshot = settling

    with phases.phase("groundtruth_ms"):
        truth = read_page_truth(driver, url)

    # Both projections are read back out of the trie.
    with phases.phase("markdown_ms"):
        chunks = render_trie(spine.trie, context_window=context_window)
    markdown_addresses, markdown_texts = _addresses_of_chunks(chunks)

    units = [(line.address, line.text, line.address.tag)
             for chunk in chunks for line in chunk.lines
             if line.address is not None and line.text.strip()]
    # What each drawn unit also stands for.
    #
    # A merged sentence is ONE box on the canvas and several addresses, and
    # the wireframe is built from the line list -- so the addresses folded in
    # were never placed and read as undrawn: page->wireframe went from 2,751
    # missed to 14,612 on a change that draws exactly the same picture.
    #
    # They are credited where their line was drawn, which is where they are:
    # a link inside a sentence is at the sentence.
    merged_at = {}
    for chunk in chunks:
        for line in chunk.lines:
            if line.address is not None and line.inline:
                merged_at[line.address.key()] = list(line.inline)
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
                # One entry per address the drawing places, not one per line
                # it occupies. A cell wrapped across four rows is four
                # `WireLine`s carrying the same address list -- one place on
                # the canvas, drawn on four rows -- and counting rows made a
                # wrapping layout look like a renderer drawing things twice:
                # injectivity read 67.8% on a drawing that repeats nothing.
                # The text of the continuation rows is joined back on, so the
                # merge check still sees the whole cell.
                seen: Dict[str, int] = {}
                for line in frame.lines:
                    for placed in (line.addresses or []):
                        # The address drawn, plus everything the merge folded
                        # into its line: one box, several addresses.
                        for a in [placed] + merged_at.get(placed.key(), []):
                            at = seen.get(a.xpath)
                            if at is None:
                                seen[a.xpath] = len(wire_addresses)
                                wire_addresses.append(a)
                                wire_texts.append(line.text)
                            else:
                                wire_texts[at] = (wire_texts[at] + " "
                                                  + line.text).strip()
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

    # Values travel with the addresses so the capture arrow can run the same
    # suspicion check the projections do. Without them its `all_drawn_text` is
    # empty and `suspect` is structurally 0 -- a self-check that cannot fire is
    # the same failure it was built to catch.
    trie_pairs = [(leaf.address, leaf.value or "")
                  for leaf in (spine.trie.leaves() if spine.trie else [])]
    trie_addresses = [a for a, _v in trie_pairs]
    trie_values = [v for _a, v in trie_pairs]

    report = AffineReport(url=url, page=truth)
    report.arrows = [
        score_arrow("page->trie", truth, trie_addresses, denominator="all",
                    texts=trie_values),
        # `drawn`, not `all`, and for the same reason the wireframe uses it.
        # Markdown is a projection *for a reader*: it collapses a select to
        # the value it shows, as a browser does. Scored against everything the
        # page holds, data.gov.uk's 1,511 collapsed options read as 3,015
        # units the projection lost, and its recall fell to 5.2% for behaving
        # correctly. Capture is answerable for everything the page holds; a
        # projection is answerable for what the page lays out.
        score_arrow("page->markdown", truth, markdown_addresses,
                    denominator="drawn", texts=markdown_texts),
        # The drawing is answerable for what the page draws and nothing else.
        # A link's coverage in the *drawing* is structural, not textual.
        # `visual_text` strips `](url)` on purpose -- a drawing shows where a
        # link is, not where it goes -- so a link unit's value, which is its
        # target, can never appear there. Scored by content it read 66.7% on
        # a page whose every link label is drawn.
        score_arrow("page->wireframe", truth, wire_addresses,
                    denominator="drawn", texts=wire_texts,
                    structural=("control", "link")),
    ]
    # Does it read in the page's order? Nothing else here asks. Coverage and
    # dedup are both satisfied by a page whose paragraphs come out shuffled,
    # and one of them was: see `affine.OrderScore`.
    #
    # Markdown only. The wireframe is the *visual* projection and its order is
    # the page's layout -- a right-hand sidebar is drawn beside the column it
    # sits next to, not after everything the walk met first. Scored against
    # walk order it reads 91% on a page it draws correctly, which is the
    # denominator mistake this project keeps making: a number is a claim about
    # the renderer AND about what it is scored against, and only one of those
    # tends to get checked. Its order is answerable to geometry, and geometry
    # is a peripheral here, so it is not scored rather than scored wrongly.
    report.order = [
        score_order("page->markdown", truth, markdown_addresses,
                    texts=markdown_texts),
    ]
    report.dedup = score_dedup(truth, markdown_addresses,
                               texts=markdown_texts)

    # The fold's own account of its chunking, hashing and dedup work.
    # `skipped` is the gate: a subtree whose digest and path both match what
    # was last sent is not sent again, and that is the mechanism the O(delta)
    # claim rests on. `folds` against `repairs` says how much of the tree the
    # cache spared. Read straight from the page rather than inferred.
    stats = dict(snapshot.stats or {})
    stats.pop("variants", None)
    stats.pop("search", None)
    emitted = float(stats.get("chunks") or 0)
    skipped = float(stats.get("skipped") or 0)
    report_algorithms = {
        "folds": float(stats.get("folds") or 0),
        "repairs": float(stats.get("repairs") or 0),
        "chunks_emitted": emitted,
        "gate_skipped": skipped,
        "gate_skip_rate": skipped / (skipped + emitted) if (skipped + emitted)
        else 0.0,
        "deduped": float(stats.get("deduped") or 0),
        "near_dups": float(stats.get("nearDups") or 0),
        "sketch_hits": float(stats.get("sketchHits") or 0),
        "merged": float(stats.get("merged") or 0),
        "pruned": float(stats.get("pruned") or 0),
        "deep_pruned": float(stats.get("deepPruned") or 0),
        "known_skips": float(stats.get("knownSkips") or 0),
        "span_hits": float(stats.get("spanHits") or 0),
        "closed_roots": float(stats.get("closedRoots") or 0),
        "errors": float(stats.get("errors") or 0),
    }

    # What reaches the trie, sized against the budget the reader set. A
    # renderer for small context windows is answerable for the size of its
    # units, and an over-budget chunk is one a small model cannot take whole.
    lengths = sorted(len(chunk.markdown) for chunk in chunks)
    if lengths:
        mid = lengths[len(lengths) // 2]
        over = sum(1 for n in lengths if n > context_window)
        report_chunking = {
            "chunks": float(len(lengths)),
            "chars_total": float(sum(lengths)),
            "chars_median": float(mid),
            "chars_max": float(lengths[-1]),
            "budget": float(context_window),
            "over_budget": float(over),
            "over_budget_rate": over / len(lengths),
            "lines_total": float(sum(len(c.lines) for c in chunks)),
        }
    else:
        report_chunking = {}

    phases.ms["total_ms"] = (time.perf_counter() - total_started) * 1000.0
    phases.ms["queue_pushed"] = float(queue.pushed)
    phases.ms["queue_queued"] = float(queue.queued)
    phases.ms["queue_skipped"] = float(queue.skipped)
    phases.ms["queue_embedded"] = float(queue.embedded)
    report.timings = phases.ms
    report.algorithms = report_algorithms
    # What the page said it was running. Taken from the report rather
    # than from the request because `shape` disables `pathdelta` in the
    # sensor, so a row that believed what was asked for would describe a
    # configuration that never ran.
    # From `snapshot.stats`, not from `stats`: the dict above has already had
    # `variants` popped out of it, so reading it there records {} for every
    # run and two configurations become indistinguishable in the artifact.
    report.variants = dict((snapshot.stats or {}).get('variants') or {})
    report.chunking = report_chunking
    return report


def write_artifact(report: AffineReport,
                   directory: Optional[pathlib.Path] = None) -> pathlib.Path:
    """Append one page's measurement to the analytics record."""
    directory = pathlib.Path(directory or DEFAULT_ARTIFACT_DIR)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "affine.jsonl"
    row = stamp(report.as_dict())
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
                f"{'TP':>7}{'FN':>6}{'FP':>5}{'TN':>6}{'coll':>6}{'susp':>6}")
    for arrow in report.arrows:
        c = arrow.overall
        rows.append(
            f"  {arrow.name:<17}{c.recall * 100:>7.1f}%{c.precision * 100:>7.1f}%"
            f"{c.injectivity * 100:>7.1f}%{c.tp:>7,}{c.fn:>6,}{c.fp:>5,}"
            f"{c.tn:>6,}{c.collapsed:>6,}{c.suspect:>6,}")
    rows.append("")
    rows.append("  by origin (recall), page->markdown / page->wireframe")
    for arrow in report.arrows[1:]:
        for origin in ("light", "shadow"):
            c = arrow.by_origin.get(origin)
            if c is None:
                continue
            rows.append(f"    {arrow.name:<17}{origin:<8}"
                        f"{c.recall * 100:>7.1f}%   of {c.tp + c.fn:>6,}")
    if report.order:
        rows.append("")
        rows.append("  reading order (against the page's own composed-tree "
                    "walk; headings excluded)")
        rows.append("    the wireframe is not scored here: its order is the "
                    "page's layout, not the walk's")
        for o in report.order:
            rows.append(f"    {o.name:<17}{o.monotone * 100:>7.1f}% in order"
                        f"   {o.inversions:>5,} inversions of {o.lines:>6,}")
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
    if report.algorithms:
        a = report.algorithms
        rows.append("  chunking / hashing / dedup, as the fold counted it")
        rows.append(f"    {'nodes folded':<24}{a.get('folds', 0):>10,.0f}"
                    f"   over {a.get('repairs', 0):>3,.0f} repair(s)")
        rows.append(f"    {'chunks emitted':<24}{a.get('chunks_emitted', 0):>10,.0f}")
        rows.append(f"    {'gate skipped':<24}{a.get('gate_skipped', 0):>10,.0f}"
                    f"   {a.get('gate_skip_rate', 0.0) * 100:>5.1f}% of candidates")
        for label, key in (("subsumed (dedup)", "deduped"),
                           ("near-duplicates", "near_dups"),
                           ("sketch hits", "sketch_hits"),
                           ("runs merged", "merged"),
                           ("subtrees pruned", "pruned"),
                           ("deep-gate pruned", "deep_pruned"),
                           ("known across pages", "known_skips"),
                           ("closed roots seen", "closed_roots"),
                           ("fold errors", "errors")):
            if a.get(key):
                rows.append(f"    {label:<24}{a.get(key, 0):>10,.0f}")
        rows.append("")
    if report.chunking:
        c = report.chunking
        rows.append("  what reaches the trie, against the reader's budget")
        rows.append(f"    {'chunks':<24}{c.get('chunks', 0):>10,.0f}")
        rows.append(f"    {'lines':<24}{c.get('lines_total', 0):>10,.0f}")
        rows.append(f"    {'chars total':<24}{c.get('chars_total', 0):>10,.0f}")
        rows.append(f"    {'chars median / max':<24}"
                    f"{c.get('chars_median', 0):>10,.0f}"
                    f" / {c.get('chars_max', 0):,.0f}")
        rows.append(f"    {'budget':<24}{c.get('budget', 0):>10,.0f}")
        rows.append(f"    {'over budget':<24}{c.get('over_budget', 0):>10,.0f}"
                    f"   {c.get('over_budget_rate', 0.0) * 100:>5.1f}%")
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


def qualify(driver, url: str, *, repeats: int = 5, scrolls: int = 1,
            context_window: int = 1200) -> dict:
    """Measure one page repeatedly and report the instrument's own spread.

    Nothing this harness says about the map is worth reading until this is
    known. A metric's movement between two commits is only evidence if it
    exceeds what the metric does when *nothing changes at all* -- and that
    floor has never been established here, while five separate defects in the
    instrument were found and fixed. Systematic error does not average out;
    more pages would only tighten the interval around a wrong value.

    Same page, same code, `repeats` times. What varies is the page itself
    (live documents drift), the scheduler, and any nondeterminism in the fold.
    The spread that produces is the resolution limit: a difference smaller
    than it is not a finding.

    Reads only from the patricia trie's scored arrows -- this adds no new
    measurement, it measures the existing one.
    """
    import statistics

    runs = [measure_page(driver, url, scrolls=scrolls,
                         context_window=context_window)
            for _ in range(max(2, repeats))]

    def series(pick) -> List[float]:
        return [float(pick(r)) for r in runs]

    tracked: Dict[str, List[float]] = {}
    for arrow in runs[0].arrows:
        name = arrow.name

        def by(nm):
            def pick(r):
                for a in r.arrows:
                    if a.name == nm:
                        return a.overall.recall
                return 0.0
            return pick
        tracked[f"{name} recall"] = series(by(name))
    tracked["page units"] = series(
        lambda r: len(r.page.units) if r.page else 0)
    tracked["dedup correctness"] = series(lambda r: r.dedup.correctness)
    for phase in ("fold_ms", "trie_ms", "markdown_ms", "wire_ms", "total_ms"):
        if phase in runs[0].timings:
            tracked[phase] = series(lambda r, p=phase: r.timings.get(p, 0.0))

    out: Dict[str, dict] = {}
    for key, values in tracked.items():
        mean = statistics.fmean(values)
        spread = max(values) - min(values)
        sd = statistics.pstdev(values) if len(values) > 1 else 0.0
        out[key] = {"mean": mean, "sd": sd, "range": spread,
                    "min": min(values), "max": max(values),
                    "rel_range": (spread / mean) if mean else 0.0}
    return {"url": url, "repeats": len(runs), "metrics": out}


def render_qualification(report: dict) -> str:
    rows = ["", f"  instrument qualification  {report['url']}",
            f"  {report['repeats']} repeats, same page, same code", "",
            f"  {'metric':<24}{'mean':>12}{'sd':>10}{'range':>10}{'rel':>9}"]
    for key, m in report["metrics"].items():
        rows.append(f"  {key:<24}{m['mean']:>12.3f}{m['sd']:>10.3f}"
                    f"{m['range']:>10.3f}{m['rel_range'] * 100:>8.1f}%")
    rows.append("")
    rows.append("  A difference smaller than `range` is not a finding.")
    rows.append("")
    return "\n".join(rows)
