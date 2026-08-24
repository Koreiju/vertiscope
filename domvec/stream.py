"""Incremental scanning: successive snapshots into successive trie deltas.

A page does not arrive all at once. A feed lazily loads as it scrolls, a
single-page app swaps its main region, an infinite list appends. The batch
path (`pipeline.run_pipeline` over one final snapshot) cannot see any of that:
it produces one answer at the end and nothing before it.

This is the incremental path. Each snapshot is tagged, addressed and turned
into a trie; consecutive tries are diffed; the diff is the update. What makes
it worth doing is that the diff prunes on Merkle hashes, so an unchanged
region costs one comparison however large it is — the cost of an update
tracks the change, not the page.

Where the delta property does and does not reach
------------------------------------------------
**Transport: incremental.** The in-page walker hashes every subtree and takes
the set of hashes the caller already holds, returning unchanged subtrees as
placeholders that :func:`domvec.capture.deep_serialize` splices back. So the
bytes crossing the bridge track the change. :class:`ScanUpdate` records the
wire bytes and the spliced size separately, so the saving is a measured number
rather than a claim.

**Indexing: incremental.** Consecutive tries are diffed on Merkle hashes, so
an unchanged region costs one comparison.

**Rendering: incremental.** Only chunks holding a changed address are
re-rendered.

**Tagging: incremental.** A subtree whose ``(xpath, hash)`` is unchanged is
not re-examined; its detections are spliced from the previous pass. The walk
still visits every node, because sibling order is not recoverable from the
addresses (THEORY Prop. 11.3.1) and the visit is what records it — but the
attribute sweep, the URL regexes and the text extraction are skipped, which is
where the time goes.

**Parsing: not incremental.** The spliced document arrives as HTML and has to
be parsed into a tree before anything can look at it, so one term stays
proportional to page size. :class:`ScanUpdate` times tagging separately from
the trie work so that term stays visible rather than hiding inside a total.
Removing it would mean splicing into the previous *tree* rather than into the
previous HTML, which is a larger change than it sounds and is not done.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Iterator, List, Optional, Sequence, Tuple

from .address import ContentAddress
from .markdown import MarkdownChunk, render_trie
from .trie import AddressTrie, TrieDelta, diff

__all__ = ["ScanUpdate", "StreamingScan"]


@dataclass
class ScanUpdate:
    """One snapshot's worth of change, with the cost of computing it."""

    passno: int
    snapshot_bytes: int
    trie: AddressTrie
    delta: TrieDelta

    # What actually crossed the bridge, before splicing. Equal to
    # snapshot_bytes on a full transfer, far smaller once pruning engages.
    wire_bytes: int = 0
    pruned_subtrees: int = 0
    reused_subtrees: int = 0
    reused_tags: int = 0

    nodes: int = 0
    leaves: int = 0
    tag_ms: float = 0.0
    trie_ms: float = 0.0
    diff_ms: float = 0.0
    # Re-rendering the chunks the delta touched. Filled in by
    # :meth:`StreamingScan.dirty_chunks`, because that is a separate call a
    # consumer makes — and it is still latency the consumer waits through, so
    # leaving it out of the total would flatter every measurement by exactly
    # the part that scales with how much changed.
    chunk_ms: float = 0.0

    # Chunks touched by this delta — the ones a store would have to rewrite.
    dirty_chunks: List[MarkdownChunk] = field(default_factory=list)
    # Every chunk the page currently renders to. The filter computes this on
    # the way to the dirty set, and a caller holding live chunks needs it to
    # retire the ones a removal emptied — recomputing it would be a second
    # full render for a set already in hand.
    all_chunks: List[MarkdownChunk] = field(default_factory=list)

    @property
    def changed(self) -> int:
        return self.delta.size

    @property
    def visited(self) -> int:
        return self.delta.visited

    @property
    def total_ms(self) -> float:
        """End-to-end latency: snapshot in, re-rendered chunks out.

        The number a consumer actually waits through. The per-phase figures
        say where the time went; this says whether the loop keeps up, and it
        is the one that has to stay flat as a page grows for "incremental" to
        mean anything to a user rather than only to a benchmark.
        """
        return self.tag_ms + self.trie_ms + self.diff_ms + self.chunk_ms

    @property
    def ms_per_changed(self) -> float:
        """Latency divided by the size of the change it processed.

        The O(delta) claim in the units that can falsify it. Work proportional
        to change means this stays roughly flat while page size grows; if it
        climbs with the document, the cost is tracking the page and the
        incremental path is only nominally incremental.

        Undefined when nothing changed — reported as 0.0, and a caller
        aggregating these must drop the no-change passes rather than average
        the zeros in, which would make any implementation look better the more
        often it was handed an unchanged page.
        """
        return self.total_ms / self.changed if self.changed else 0.0

    @property
    def prune_ratio(self) -> float:
        """Nodes not visited, as a fraction. 1.0 means everything was pruned."""
        return 1.0 - (self.delta.visited / self.nodes) if self.nodes else 0.0

    @property
    def wire_ratio(self) -> float:
        """Wire bytes as a fraction of the full document."""
        return self.wire_bytes / self.snapshot_bytes if self.snapshot_bytes else 1.0

    def row(self) -> str:
        return (f"{self.passno:>4} {self.snapshot_bytes/1024:>7.0f}K "
                f"{self.wire_bytes/1024:>7.0f}K {self.wire_ratio*100:>6.1f}% "
                f"{self.nodes:>7,} {self.changed:>6,} "
                f"{self.visited:>7,} {self.prune_ratio*100:>7.2f}% "
                f"{self.tag_ms:>6.0f} {self.trie_ms:>6.0f} {self.diff_ms:>6.1f}")

    @staticmethod
    def header() -> str:
        return (f"{'pass':>4} {'doc':>8} {'wire':>8} {'wire%':>7} "
                f"{'nodes':>7} {'delta':>6} {'visited':>7} {'pruned':>8} "
                f"{'tag':>6} {'trie':>6} {'diff':>6}")


class StreamingScan:
    """Holds the current trie and turns each new snapshot into a delta."""

    def __init__(self, url: str, *, context_window: int = 1200) -> None:
        self.url = url
        self.context_window = context_window
        self.trie: Optional[AddressTrie] = None
        self.updates: List[ScanUpdate] = []
        # (xpath, subtree hash) -> that subtree's detections, from the last
        # pass. Makes tagging incremental; see ContentTagger.reuse_cache.
        self._reuse: dict = {}

    def push(self, html, passno: int = 0) -> ScanUpdate:
        """Fold one snapshot in. Returns what changed and what it cost.

        Accepts either a raw html string or a :class:`domvec.capture.Snapshot`;
        the snapshot form additionally carries what the transfer cost, which a
        bare string cannot report.
        """
        wire_bytes = 0
        pruned = 0
        if not isinstance(html, str):
            snapshot = html
            html = snapshot.html
            wire_bytes = snapshot.wire_bytes
            pruned = snapshot.pruned_subtrees
        from .core.content_tagger import ContentTagger
        from .core.shadow_html_parser import ShadowDOM

        t0 = time.perf_counter()
        tagger = ContentTagger(ShadowDOM(html), reuse=self._reuse)
        tagged = tagger.tag()
        self._reuse = tagger.reuse_cache()
        reuse_stats = dict(tagger.reuse_stats)
        t1 = time.perf_counter()
        fresh = AddressTrie.from_tagged(tagged, self.url)
        t2 = time.perf_counter()

        if self.trie is None:
            # The first snapshot is all addition. Recording it as such rather
            # than diffing against an empty trie keeps the cost columns
            # honest: there is no pruning to be had on a first pass, and
            # reporting a 100% prune ratio there would be flattering nonsense.
            delta = TrieDelta(added=list(fresh.addresses()), visited=0)
        else:
            delta = diff(self.trie, fresh)
        t3 = time.perf_counter()

        self.trie = fresh
        stats = fresh.stats()
        update = ScanUpdate(
            passno=passno or len(self.updates) + 1,
            snapshot_bytes=len(html),
            wire_bytes=wire_bytes or len(html),
            pruned_subtrees=pruned,
            reused_subtrees=reuse_stats.get("subtrees", 0),
            reused_tags=reuse_stats.get("tags_reused", 0),
            trie=fresh,
            delta=delta,
            nodes=int(stats["nodes"]),
            leaves=int(stats["leaves"]),
            tag_ms=(t1 - t0) * 1000,
            trie_ms=(t2 - t1) * 1000,
            diff_ms=(t3 - t2) * 1000,
        )
        self.updates.append(update)
        return update

    def absorb(self, units, passno: int = 0, removed=()) -> ScanUpdate:
        """Fold in already-addressed units from the in-page sensor.

        The peer of :meth:`push`. That one receives a whole snapshot and has
        to tag it to find out what is in it; this one receives detections that
        are *already* addressed, because the fold in the page did that work.
        Both end at the same trie and the same renderer, which is the point:
        live navigation and a full scan are one pipeline, not two.

        The sensor path used to skip the trie entirely and hand rendered
        chunks straight to storage, so the markdown on that path came from a
        second serialiser in JS. Everything downstream — chunk boundaries,
        anchors, dedup, the graph's structure — was therefore produced by
        whichever path happened to have read the page.

        No diff is taken. `push` must diff because a snapshot does not say
        what changed; the sensor does say, so the delta is *observed* rather
        than recovered, and the cost is proportional to the change by
        construction rather than by filtering afterwards.
        """
        t0 = time.perf_counter()
        if self.trie is None:
            self.trie = AddressTrie()
        delta = self.trie.apply(units, removed=removed)
        t1 = time.perf_counter()
        t2 = t1

        stats = self.trie.stats()
        update = ScanUpdate(
            passno=passno or len(self.updates) + 1,
            snapshot_bytes=0,
            wire_bytes=0,
            trie=self.trie,
            delta=delta,
            nodes=int(stats["nodes"]),
            leaves=int(stats["leaves"]),
            trie_ms=(t1 - t0) * 1000,
            diff_ms=(t2 - t1) * 1000,
        )
        self.updates.append(update)
        return update

    def dirty_chunks(self, update: ScanUpdate) -> List[MarkdownChunk]:
        """Only the chunks containing a changed address.

        Re-rendering the whole page per pass would make the render cost
        proportional to page size and throw away everything the diff bought.
        Filtering by the delta's addresses keeps it proportional to the change.
        """
        started = time.perf_counter()
        # Movement counts here even though it is not counted as change. A
        # node that merely moved renders in a different place, so the chunk
        # holding it says something different and has to be rewritten; only
        # the *cost accounting* and the vectoriser get to treat a move as
        # free. Filtering on change alone would leave a pure reorder — a
        # re-sorted table, a reshuffled feed — stored in its old order.
        touched = {a.key() for a in
                   update.delta.added + update.delta.changed
                   + update.delta.removed + update.delta.moved}
        if not touched:
            update.chunk_ms = (time.perf_counter() - started) * 1000
            return []
        chunks = render_trie(update.trie, context_window=self.context_window)
        dirty = [c for c in chunks if touched.intersection(c.anchors)]
        update.all_chunks = chunks
        update.dirty_chunks = dirty
        update.chunk_ms = (time.perf_counter() - started) * 1000
        return dirty

    def summary(self) -> dict:
        """Totals across the stream, for asserting the property held."""
        if not self.updates:
            return {}
        steady = self.updates[1:]      # the first pass has nothing to prune
        return {
            "passes": len(self.updates),
            "first_pass_addresses": len(self.updates[0].delta.added),
            "final_nodes": self.updates[-1].nodes,
            "final_leaves": self.updates[-1].leaves,
            "total_changed": sum(u.changed for u in steady),
            "total_visited": sum(u.visited for u in steady),
            "total_nodes_if_rescanned": sum(u.nodes for u in steady),
            "worst_prune_ratio": min((u.prune_ratio for u in steady), default=0.0),
            "mean_prune_ratio": (sum(u.prune_ratio for u in steady) / len(steady)
                                 if steady else 0.0),
            "snapshot_bytes": sum(u.snapshot_bytes for u in self.updates),
            "wire_bytes": sum(u.wire_bytes for u in self.updates),
            "wire_saving": 1.0 - (
                sum(u.wire_bytes for u in self.updates)
                / max(sum(u.snapshot_bytes for u in self.updates), 1)
            ),
        }
