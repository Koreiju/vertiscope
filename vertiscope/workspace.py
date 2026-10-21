"""The workspace: one object owning every persistent piece.

The pipeline's parts each persist somewhere different, and for good reasons —
the graph holds what is linked, the frequency matrix holds what is corpus-wide,
the JSONL holds what is streamable. Those reasons are internal, though. From
outside there is one thing: a directory you scan into and search out of.

    ws = Workspace("build")
    ws.scan("https://example.com")          # live, streaming, incremental
    ws.index_html(html, url)                # offline, same destination
    ws.search("query")

    build/
      graph.kuzu     addresses, chunks, embeddings and the edges between
      freq/          the frequency matrix, as numpy arrays
      chunks/*.jsonl the markdown checkpoint, one file per page

Keeping the three in one object is what makes them consistent: every write
path goes through :meth:`Workspace.ingest`, so a page cannot land in the graph
without a frequency row, and the integer row that aligns the three vector
factors is issued in exactly one place.
"""

from __future__ import annotations

import json

import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

import threading

import numpy as np

from .address import ContentAddress
from .graphstore import GraphStore
from .markdown import (DEFAULT_CONTEXT_WINDOW, MarkdownChunk, RenderReport,
                       read_jsonl, render_trie, write_jsonl)
from .privacy import STORE_NAME_RE, redact_url, store_name
from .tokens import sensor_budget
from .search import Hit, SearchDiagnostics, ThreeFormIndex
from .stream import ScanUpdate, StreamingScan
from .trie import AddressTrie
from .vectors import EmbeddingMatrix, FreqMatrix, VectorQueue

__all__ = ["Workspace", "ScanResult"]

#: `SET p.title` that keeps the stored title when the writer has none.
_KEEP_TITLE = "CASE WHEN $title = '' THEN p.title ELSE $title END"
#: Planted (G-233): a web code block is read from its one-line markdown, not
#: from the trie's value -- as before 2026-10-18, when none was graphed.
_PLANT_CODE_FROM_LINE = bool(os.environ.get("VERTISCOPE_PLANT_CODE_FROM_LINE"))
#: Planted (186k): no special file is detected.
_PLANT_NO_FILES = bool(os.environ.get("VERTISCOPE_PLANT_NO_FILES"))
#: Planted (186k): a Hugging Face `/blob/` viewer link is taken as the file.
_PLANT_HF_BLOB = bool(os.environ.get("VERTISCOPE_PLANT_HF_BLOB"))

ProgressFn = Callable[[str, str], None]


@dataclass
class ScanResult:
    """What one page's scan produced."""

    url: str
    addresses: int = 0
    chunks: int = 0
    lines: int = 0
    passes: int = 0
    wire_bytes: int = 0
    document_bytes: int = 0
    updates: List[ScanUpdate] = field(default_factory=list)
    report: RenderReport = field(default_factory=RenderReport)

    @property
    def wire_saving(self) -> float:
        return 1.0 - (self.wire_bytes / self.document_bytes) \
            if self.document_bytes else 0.0

    def summary(self) -> Dict[str, object]:
        return {
            "url": self.url,
            "addresses": self.addresses,
            "chunks": self.chunks,
            "lines": self.lines,
            "passes": self.passes,
            "wire_saving": round(self.wire_saving, 4),
        }


class Workspace:
    """A scanned corpus on disk. Use as ``with Workspace(path) as ws:``."""

    def __init__(self, path, *, context_window: int = DEFAULT_CONTEXT_WINDOW,
                 embedder=None, read_only: bool = False) -> None:
        self.path = Path(path)
        self.read_only = bool(read_only)
        if self.read_only:
            # A read-only open must not CREATE the thing it claims to read.
            # Creating it would hand back an empty workspace that answers
            # every query with nothing, which reads as "the corpus is gone"
            # rather than "that path is wrong".
            if not self.path.is_dir():
                raise FileNotFoundError(
                    f"no workspace at {self.path} (opened read-only, so it "
                    "will not be created)")
        else:
            self.path.mkdir(parents=True, exist_ok=True)
        self.chunks_dir = self.path / "chunks"
        if not self.read_only:
            self.chunks_dir.mkdir(exist_ok=True)
        self.context_window = context_window

        self._store = GraphStore(self.path / "graph.kuzu",
                                 read_only=self.read_only)
        #: Graph writes queued by `ingest(..., defer=True)`, in order.
        #: Drained by `settle()`, which every reader goes through.
        self._pending: List[dict] = []
        self._settling = False
        # After the store, never before. `GraphStore` takes an exclusive OS
        # lock on the workspace, so reaching this line is the proof that no
        # other process is writing these files -- which is what makes it safe
        # to rename them. A workspace someone else holds raises above and is
        # never touched.
        # Skipped when read-only, and the reason is the comment above: the
        # exclusive lock was the PROOF that no one else is writing these
        # files, and that proof is what made renaming them safe. A read-only
        # open shares the store with other readers and possibly a writer, so
        # it no longer holds. The migration is idempotent and the next
        # writable open runs it.
        if not self.read_only:
            self._retire_readable_names()
        self.freq = FreqMatrix.load(self.path / "freq")
        self.embeddings = EmbeddingMatrix() if embedder is not None else None
        self.embedder = embedder
        # Chunks are queued for vectorisation here and embedded in batches;
        # nothing on the write path calls the embedder directly.
        self.vectors = VectorQueue()
        self._index: Optional[ThreeFormIndex] = None
        #: `index` is a LAZY property read from request threads of a
        #: `ThreadingHTTPServer`. Two concurrent searches both found
        #: it None, both hydrated into one shared `EmbeddingMatrix`,
        #: and the growth raced -- every `/search` died on an
        #: `IndexError` out of `vectors.set`. Built once, here.
        self._index_lock = threading.RLock()
        #: Whether building the query index may run the encoder. True for a
        #: script, which has no one else to embed for it. A server with an
        #: embedding worker sets it False: that worker owns the encoder, and
        #: a search that embedded inline waited 38 s behind it (measured).
        #: A chunk not embedded yet is simply not ranked semantically until
        #: the worker reaches it.
        self.embed_inline = True

    # -- on-disk naming ---------------------------------------------------
    def mirror_path(self, url: str) -> Path:
        """Where one page's markdown checkpoint lives.

        Named by digest rather than by url. The mirror has to be findable
        from a url — `forget` finds it that way, and so does every rewrite —
        but it must not be readable *as* a url, because the directory it
        lives in is listable by anything on the machine and a listing that
        names the pages is the browsing history in plain sight.

        The digest is taken over the redacted url, so the same page reached
        with and without a campaign tag is one file rather than two.
        """
        return self.chunks_dir / f"{store_name(url)}.jsonl"

    def _retire_readable_names(self) -> int:
        """Rename any legacy human-readable mirror to its digest name.

        A migration and not an opt-in, because an opt-in leaves the leak in
        place in every workspace that already exists — and those are the ones
        with the history in them. It is cheap (a rename, no rewrite), it is
        idempotent, and it is driven by the url *inside* each file rather
        than by parsing the filename, so a name that was truncated or
        collided in the old scheme still lands in the right place.

        Every failure is skipped rather than raised. A file another process
        has open, a name that no longer parses, a directory that is read-only
        — none of those is a reason to refuse to open a workspace, and the
        next open tries again.
        """
        renamed = 0
        try:
            entries = sorted(self.chunks_dir.glob("*.jsonl"))
        except OSError:
            return 0
        for legacy in entries:
            if STORE_NAME_RE.match(legacy.stem):
                continue
            try:
                first = next(iter(read_jsonl(legacy)), None)
            except Exception:  # noqa: BLE001 - an unreadable mirror is skipped
                continue
            url = getattr(first, "url", "") if first is not None else ""
            if not url:
                continue
            target = self.mirror_path(url)
            try:
                if target.exists():
                    # Two spellings of one page, or a re-scan that already
                    # wrote the new name. The digest file is the current one;
                    # the legacy file is the copy that must not survive.
                    legacy.unlink()
                else:
                    legacy.replace(target)
                renamed += 1
            except OSError:
                continue
        return renamed

    def __enter__(self) -> "Workspace":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        # **A READ-ONLY workspace writes nothing, including here.**
        #
        # This saved `freq.npz` unconditionally, so every reader rewrote it
        # on exit -- the sidecar, an MCP server, a diagnostic script. Found
        # by noticing that `freq.npz` was dated today on a store last written
        # six days ago, and every one of those dates was a reader closing.
        # Nothing observed was corrupted by it, and that is luck rather than
        # design: anything that pruned the matrix in memory would have been
        # persisted by a process that had promised not to write.
        if self.read_only:
            self.store.close()
            return
        # The queue is in memory, so anything still in it at close is work
        # that would be lost — and lost invisibly, because hydration only
        # backfills chunks with *no* vector and would leave a changed chunk
        # answering with the vector of what it used to say.
        try:
            self.flush_vectors()
        except Exception:  # noqa: BLE001 - closing must still save the rest
            pass
        try:
            self.freq.save(self.path / "freq")
        finally:
            self.store.close()

    def rebuild_lexical(self, *, progress=None) -> Dict[str, int]:
        """Give every stored chunk a frequency row (`G-3`).

        **Why this is needed at all.** 7,955 of 14,129 chunks in
        `build/corpus123` had an embedding and NO lexical row -- 56.3% of the
        corpus, and 28 of 96 pages with no coverage whatever, RFC 9110 and
        the Rust `Vec` docs among them. Retrieval is a strict triple product,
        so a zero on the lexical factor is a veto: those chunks could not be
        returned by any query, scoped or global. Scoping to RFC 9110 answered
        0 hits for every query put to it, which is how this was found.

        The rows are derivable from the markdown the store already holds, so
        this is a repair and not a re-scan.
        """
        # **And a row that exists but says nothing.** A chunk indexed while
        # its markdown was empty got a row with no terms; `restore_markdown`
        # later refilled the markdown and left that row empty, so the chunk
        # had a lexical row and a veto at once. Re-derived from the markdown
        # the store holds now, in place (`add` replaces a row, never
        # renumbers it).
        from .vectors import tokens as _tokens
        added = refreshed = skipped = 0
        for chunk in self.store.chunks():
            row = self.freq.row_of(chunk.cid)
            if row is not None:
                if not self.freq._counts[row] and any(True for _ in _tokens(chunk.md or "")):
                    self.freq.add(chunk.cid, chunk.md or "")
                    refreshed += 1
                else:
                    skipped += 1
                continue
            self.freq.add(chunk.cid, chunk.md or "")
            added += 1
            if progress and added % 2000 == 0:
                progress("lexical", "%d rows added" % added)
        if added or refreshed:
            self.freq.save(self.path / "freq")
            self._lexical_saved = self.freq.version
        self._index = None          # the ranking is stale by construction
        return {"added": added, "refreshed": refreshed,
                "already_had_one": skipped}

    def save_lexical(self) -> bool:
        """Write the frequency matrix if it changed since the last write.

        **Why this exists.** The matrix was written only by `close()` and by
        `rebuild_lexical()`. A sidecar ended any other way -- a hard kill, a
        crash, a machine going to sleep for good -- lost every lexical row
        added since it opened, while the chunks themselves were already in
        the graph. Retrieval is a strict product, so each of those chunks came
        back from a restart with a vetoed lexical factor: a page captured live
        that afternoon answered nothing to any query, its own name included.
        """
        if self.read_only:
            return False             # a reader never writes (see `close`)
        version = getattr(self.freq, "version", 0)
        if version == getattr(self, "_lexical_saved", None):
            return False
        self.freq.save(self.path / "freq")
        self._lexical_saved = version
        return True

    # -- writing ----------------------------------------------------------
    @property
    def store(self) -> GraphStore:
        """The graph, with every queued write already in it.

        Deferral is only safe if it is invisible, and the way to make it
        invisible is to put the settling on the path every reader already
        takes. `ws.store` is that path: 17 call sites in this file and 20
        outside it -- tests, the REPL, `live`, analytics -- all reach the
        graph through this attribute, so making it a property catches them
        without any of them knowing.

        The write path itself uses `_store`, which does not settle, or
        queueing a write would immediately drain the queue.
        """
        self.settle()
        return self._store

    def settle(self) -> int:
        """Apply every queued graph write. Returns how many pages were written.

        Ordering is preserved: a delta queued after a complete write must not
        overtake it, because `_reconcile` reads what the page currently has.

        `_settling` guards re-entry, since `GraphStore.ingest` is reached via
        `_store` but anything it calls that touches `self.store` would
        otherwise recurse.
        """
        if not self._pending or self._settling:
            return 0
        self._settling = True
        try:
            queued, self._pending = self._pending, []
            for job in queued:
                self._store.ingest(
                    job["url"], job["addresses"], job["chunks"],
                    rows=job["rows"], embeddings=job["embeddings"],
                    title=job["title"], root_hash=job["root_hash"],
                    complete=job["complete"],
                )
            return len(queued)
        finally:
            self._settling = False

    def ingest(
        self,
        url: str,
        trie: AddressTrie,
        *,
        report: Optional[RenderReport] = None,
        title: str = "",
        defer: bool = False,
        complete: bool = True,
    ) -> Tuple[List[MarkdownChunk], Dict[str, int]]:
        """Render, index and store one page's trie. The single write path.

        `complete=False` writes the trie's chunks without retiring the page's
        others: a page whose visit SAW more than its last DOM holds (a list
        that recycles as it scrolls) keeps the union (G-216).

        Every caller — live scan, offline file, REPL re-scan — comes through
        here, so there is one place where a chunk gets its frequency row and
        one place where the graph and the matrix can fall out of step. They
        cannot fall out of step, because neither is written without the other.
        """
        chunks = render_trie(trie, context_window=self.context_window,
                             report=report)
        addresses = [
            (node.address, node.value, node.content_hash)
            for node in trie.leaves() if node.address is not None
        ]
        def held(a, _t=trie):
            n = _t.find(a)
            return n.value if n is not None else None
        return self.ingest_chunks(url, chunks, addresses, title=title,
                                  root_hash=trie.root_hash, defer=defer, complete=complete,
                                  raw_values=held)

    def ingest_chunks(
        self,
        url: str,
        chunks: List[MarkdownChunk],
        addresses=None,
        *,
        title: str = "",
        root_hash: str = "",
        complete: bool = True,
        removed: Optional[Sequence[str]] = None,
        raw_values=None,
        defer: bool = False,
    ) -> Tuple[List[MarkdownChunk], Dict[str, int]]:
        """Write already-rendered chunks. The single write path's body.

        `defer` queues the graph write instead of performing it. The page is
        still fully described -- frequency rows, vector queue and mirror are
        written -- and `settle()` applies the graph part, which every reader
        triggers by reaching the store through `Workspace.store`.

        It buys latency, not work: the same rows are written either way, at
        ~0.12 ms each, so this takes a page off the ingest critical path
        rather than making it cheaper. Measured, the ingest path goes from
        198.6 to ~62 ms/page; the remaining floor is render (39) plus trie
        (11) plus tag and parse (6).

        `ingest` renders a whole trie and delegates here; the live path
        delegates here too, with the chunks `render_trie` produced for the
        subtrees a drain touched. Both are the same renderer over the same
        structure — the sensor path used to arrive with chunks a second
        serialiser in JS had built, which meant the markdown a page got
        depended on which path had read it.

        Both entry points share every line below, so frequency rows,
        embeddings, the graph and the JSONL checkpoint cannot fall out of
        step between them.

        `addresses` may be omitted, in which case it is taken from the chunks'
        own line anchors — which is what a delta carries.

        `complete` says whether `chunks` is the whole page or a delta. It
        governs retirement, and the distinction is not cosmetic: retiring
        "every stored chunk not in this batch" is right for a full write and
        destroys the index on a partial one. A delta names what it removed;
        it never implies removal by omission.
        """
        # The url reaches this store redacted or it does not reach it at all.
        # Every caller above already redacts -- the scan paths at the point
        # they take the address off the browser, `Sensor.url` on the sensor
        # path -- and this line is the one that makes that a property of the
        # store rather than a habit of its callers. It is a no-op on every
        # path in this file, and it is what a fifth path added later will
        # hit.
        url = redact_url(url)
        if addresses is None:
            addresses = [
                (line.address, line.text, "")
                for chunk in chunks for line in chunk.lines
                if line.address is not None
            ]
        # Retire the rows of chunks this page no longer produces, before
        # issuing rows for the ones it does. The graph reconciles the same set
        # (GraphStore._reconcile); doing it here too is what keeps the two
        # stores coupled — a row left behind would go on inflating document
        # frequency for a chunk that no longer exists.
        # Settle only what this page depends on.
        #
        # Reconciliation reads the store as part of writing to it, and going
        # through `self.store` would drain the whole queue on every page --
        # which is exactly what the first version of this did: it queued a
        # write and immediately settled it, for 0.9x and no benefit.
        #
        # What reconciliation needs is this url's current chunks, so a queued
        # write for a DIFFERENT page cannot affect the answer. Only a pending
        # write to this same url has to be applied first.
        _timed: Dict[str, float] = {}
        _t = time.perf_counter()
        if any(job["url"] == url for job in self._pending):
            self.settle()
        _timed["ms_settle"] = round((time.perf_counter() - _t) * 1000, 1)
        _t = time.perf_counter()
        store = self._store
        if complete:
            superseded = ({c.cid for c in store.chunks(url)}
                          - {c.cid for c in chunks})
        else:
            superseded = set(removed or ())
        for cid in superseded:
            self.freq.remove(cid)

        rows = {c.cid: self.freq.add(c.cid, c.markdown) for c in chunks}
        _timed["ms_freq"] = round((time.perf_counter() - _t) * 1000, 1)

        # Queued, not embedded. This is a write path — the sensor calls it
        # once per drain, so embedding here made vectorisation a per-delta
        # cost, which OBJECT_MODEL 8 forbids outright. The queue also drops
        # chunks whose markdown digest has not moved, so a page that re-emits
        # a settled chunk costs nothing. Vectors are computed in batches by
        # `flush_vectors`, which the query surface calls before it answers.
        self.vectors.forget(superseded)
        self.vectors.extend(chunks)
        vectors: Dict[str, Sequence[float]] = {}

        # The page node must exist before links can resolve to it.
        # The page node is written now even when the rest is queued: it is
        # one row, and the edges the deferred write creates resolve to it.
        _t = time.perf_counter()
        # Through the store's serialised entry point (`D-23`), never the raw
        # connection. This was the ONE statement that bypassed `_db_lock`: it
        # held the sidecar's work lock, which the GET handlers do not take, so
        # a read could be inside kuzu on the same connection at the same time
        # -- and its result was never drained.
        store._execute(
            # A write that does not know the title must not erase it: every
            # live drain arrives without one, and 121 of 130 pages had been
            # blanked to their url this way.
            "MERGE (p:Page {url: $url}) SET p.title = %s" % _KEEP_TITLE,
            {"url": url, "title": title},
        )
        _timed["ms_page"] = round((time.perf_counter() - _t) * 1000, 1)
        job = {"url": url, "addresses": addresses, "chunks": chunks,
               "rows": rows, "embeddings": vectors or None, "title": title,
               "root_hash": root_hash, "complete": complete}
        if defer:
            # The graph write is the only deferred part. Frequency rows, the
            # vector queue and the jsonl mirror all stay synchronous: they
            # are cheap -- `freq.add` measures ~6 ms/page against the graph's
            # 141 -- and deferring them would split one page's state across
            # two moments for no gain.
            #
            # The counts are what this page WILL write. They are a report of
            # the work, and the work is certain; only its timing is not.
            self._pending.append(job)
            counts = {"addresses": len(addresses), "chunks": len(chunks),
                      "anchors": sum(len(c.lines) for c in chunks),
                      "contains": 0, "links": 0,
                      "chunks_removed": 0, "addresses_removed": 0}
        else:
            counts = self.store.ingest(
                url, addresses, chunks, rows=rows,
                embeddings=vectors or None, title=title,
                root_hash=root_hash, complete=complete,
                removed=None if complete else removed,
            )
        # The mirror is rewritten only by a write that describes the whole
        # page. A delta names some chunks; writing those alone replaced the
        # file with a fragment of itself, and measured across 60 swept pages
        # 21 of them held fewer chunks on disk than in the store — one with
        # 16 against 537. The mirror is meant to be the checkpoint the store
        # can be rebuilt from, so a partial write must add to it, not define
        # it.
        _t = time.perf_counter()
        mirror = self.mirror_path(url)
        if complete:
            write_jsonl(chunks, mirror)
        else:
            merged = {c.cid: c for c in read_jsonl(mirror)} if mirror.exists() else {}
            merged.update({c.cid: c for c in chunks})
            for cid in (removed or ()):
                merged.pop(cid, None)
            write_jsonl(list(merged.values()), mirror)
        # **The mirror is O(page) on every delta.** It re-reads the page's
        # whole checkpoint, folds the changed chunks in and writes the whole
        # thing back -- 1,097 rows rewritten to record 6 on a long page. It
        # is timed on its own so the profile can say how much of `store` that
        # is, rather than it hiding inside the database's number.
        _timed["ms_mirror"] = round((time.perf_counter() - _t) * 1000, 1)
        _timed["mirror_rows_written"] = (
            len(chunks) if complete else len(merged))
        # The index takes the DELTA (the rows this write touched), not a
        # rebuild on the next search (PLUGIN_GOAL 152). Planted
        # `_PLANT_INDEX_REBUILD`: thrown away, as before.
        self._index_changed(set(rows) | set(superseded))
        # A write that describes a whole page is a settled unit, and flushing
        # it is a batch — one embedder call for the page, which is what the
        # design asks for. A delta is not settled and stays queued. This is
        # the line the prohibition actually draws: batch, not per-delta.
        if complete:
            self.flush_vectors()
            # Stage two, at the settle (`G-31`). This is the one point where
            # the page is finished AND its vectors exist, which is what
            # aggregation needs -- a delta is neither. Putting it here rather
            # than in each caller is why the live scan, the browser cell's
            # capture and the offline `index_html` all get it without three
            # copies of the decision.
            #
            # Non-fatal on purpose. A page whose clustering failed is a page
            # with no merge groups, which is the state every page starts in;
            # it is not a reason to lose the write that just succeeded.
            try:
                self.aggregate(url)
            except Exception:                       # noqa: BLE001
                pass
        if isinstance(counts, dict):
            counts.update(_timed)
        # PLUGIN_GOAL 186k: the special files a page links to.
        try:
            self.last_files = self.special_files(url, chunks)
        except Exception as exc:                    # noqa: BLE001 -- never fails a capture
            self.last_files = {"error": str(exc)[:160]}
        # G-233/G-235: a page's Python code blocks join the code graph.
        try:
            self.last_web_cpg = self.web_code_cpg(url, chunks, raw=raw_values)
        except Exception as exc:                    # noqa: BLE001 -- never fails a capture
            self.last_web_cpg = {"error": str(exc)[:160]}
        return chunks, counts

    def page_url(self, url: str) -> str:
        """The spelling to *look a page up* by, given the caller's spelling.

        An already-stored spelling wins, so a caller who types
        `https://a.test/` reaches the page stored as `https://a.test`.
        Otherwise the canonical form, which is what makes it usable as a
        dedup key for pages not yet scanned. Otherwise the url as given — a
        `file://` uri has no canonical http form.

        Reads only. Normalising what gets *written* was tried and reverted:
        it would have changed the url component of every address key, and the
        duplication it guards against measured **zero** on a real workspace
        (`pages that canonicalise together: none`). `resolve_page` fixes the
        defect that was actually measured — three of four link edges dropped
        — without rewriting anything on disk.
        """
        from .graphstore import canonical_url

        return self.store.resolve_page(url) or canonical_url(url) or url

    def restore_markdown(self, batch: int = 2000) -> Dict[str, int]:
        """Refill chunk markdown the graph lost, from the JSONL checkpoint.

        **What was lost, measured.** 11,542 of 14,313 stored chunks had EMPTY
        `c.md`, and 85 of 102 pages had every chunk empty. The checkpoint
        beside the store held markdown for **100% of its 16,194 rows, 2,391 of
        them with an image**, against 228 chunks with an image in the graph.
        So the content was captured and rendered correctly and then did not
        survive into the database -- which is the whole of "a lot of missing
        images where there should be a lot": a node shows a picture only if
        its markdown contains one, and most of the markdown was gone.

        **Not a re-render, and not a guess.** The checkpoint is written from
        the same `MarkdownChunk` the graph row is, at the same ingest; this
        copies a recorded value back into the column it came from, matched
        on `cid`.

        **Fills only what is empty.** A chunk whose graph markdown is present
        is never touched, because that value may be newer than any checkpoint
        row. Where the checkpoint holds several rows for one cid -- it is
        appended to -- the last non-empty one wins, which is the latest write
        that carried content.

        The live settle path does NOT cause this: re-capturing a page with
        intact markdown was measured before and after, 26 chunks, 0 empty, 20
        with an image, identical. The empty pages came from an earlier
        ingest, and this recovers them; it does not claim to explain them.
        """
        store = self.store
        empty = {cid for cid, md in store._rows(
            "MATCH (c:Chunk) RETURN c.cid, c.md") if not (md or "").strip()}
        out = {"empty_before": len(empty), "restored": 0,
               "not_in_checkpoint": 0, "files_read": 0}
        if not empty:
            return out
        found: Dict[str, dict] = {}
        for path in sorted(self.chunks_dir.glob("*.jsonl")):
            out["files_read"] += 1
            try:
                with path.open(encoding="utf-8", errors="replace") as fh:
                    for line in fh:
                        try:
                            row = json.loads(line)
                        except Exception:              # noqa: BLE001
                            continue
                        if not isinstance(row, dict):
                            continue
                        cid = row.get("cid")
                        md = row.get("md") or ""
                        if cid in empty and md.strip():
                            found[cid] = row           # last non-empty wins
            except OSError:
                continue
        rows = [{"cid": cid, "md": r.get("md") or "",
                 "chars": int(r.get("chars") or len(r.get("md") or "")),
                 # The checkpoint spells `lines` as a COUNT; the first run of
                 # this died on `len(int)`. Either form, else count the md.
                 "lines": (r.get("lines") if isinstance(r.get("lines"), int)
                           else len(r.get("lines") or []) or
                           (r.get("md") or "").count(chr(10)) + 1)}
                for cid, r in found.items()]
        for i in range(0, len(rows), batch):
            store._batch(
                "UNWIND $rows AS r MATCH (c:Chunk {cid: r.cid}) "
                "WHERE c.md IS NULL OR size(c.md) = 0 "
                "SET c.md = r.md, c.chars = r.chars, c.line_count = r.lines",
                rows[i:i + batch])
        out["restored"] = len(rows)
        out["not_in_checkpoint"] = len(empty) - len(rows)
        out["empty_after"] = sum(1 for _c, md in store._rows(
            "MATCH (c:Chunk) RETURN c.cid, c.md") if not (md or "").strip())
        return out

    def index_html(self, html: str, url: str, *, title: str = "") -> ScanResult:
        """Offline path: one snapshot, no browser."""
        from .core.content_tagger import ContentTagger
        from .core.shadow_html_parser import ShadowDOM

        url = redact_url(url)
        tagged = ContentTagger(ShadowDOM(html)).tag()
        trie = AddressTrie.from_tagged(tagged, url)
        report = RenderReport()
        chunks, _counts = self.ingest(url, trie, report=report, title=title)
        return ScanResult(
            url=url, addresses=len(trie), chunks=len(chunks),
            lines=sum(len(c.lines) for c in chunks), passes=1,
            wire_bytes=len(html), document_bytes=len(html), report=report,
        )

    #: Special files by extension (PLUGIN_GOAL 186k). A PDF is one too
    #: (2026-10-18: "downloads for special files should include .pdf"); once
    #: fetched it is chunked by its own pipeline (`index_pdf`, G-248).
    SPECIAL_FILES = {
        ".gguf": "model", ".safetensors": "weights", ".csv": "table", ".tsv": "table", ".parquet": "table",
        ".json": "json", ".jsonl": "json", ".zip": "archive", ".tar": "archive", ".tgz": "archive",
        ".tar.gz": "archive", ".7z": "archive", ".pdf": "pdf",
    }

    def special_files(self, url: str, chunks) -> Dict[str, int]:
        """The special files a page links to, each at the address of the line
        that links it: a link destination whose path ends in one of
        `SPECIAL_FILES` (a query or fragment ignored -- Hugging Face's
        `.../resolve/main/x.gguf?download=true`). Stored per chunk
        (`GraphStore.upsert_files`); drawn as nodes by the plugin.
        Planted `VERTISCOPE_PLANT_NO_FILES`: nothing detected."""
        import re as _re
        from urllib.parse import urljoin, urlsplit, unquote

        out = {"files": 0}
        if not url or url.startswith(("code://", "vault://")) or _PLANT_NO_FILES:
            return out
        # Absolute or page-relative (`/org/repo/resolve/main/x.gguf` on a
        # Hugging Face file list), resolved against the page.
        link = _re.compile(r"\]\(((?:https?://|/)[^)\s]+)\)|<(https?://[^>\s]+)>|\((https?://[^)\s]+)\)")
        rows, seen, carried = [], set(), set()
        for chunk in chunks:
            carried.add(chunk.cid)
            for line in getattr(chunk, "lines", []) or []:
                text = str(getattr(line, "text", "") or "")
                for m in link.finditer(text):
                    href = urljoin(url, m.group(1) or m.group(2) or m.group(3))
                    # Hugging Face lists each file twice -- `/blob/` (a viewer
                    # PAGE) and `/resolve/` (the file). The file is the one
                    # meant: its HEAD read 198 KB, the viewer's, for a 5.63 GB
                    # GGUF (2026-10-18). Planted `_PLANT_HF_BLOB`.
                    if not _PLANT_HF_BLOB and urlsplit(href).netloc.endswith("huggingface.co") and "/blob/" in href:
                        href = href.replace("/blob/", "/resolve/", 1)
                    raw_path = unquote(urlsplit(href).path)
                    path = raw_path.lower()
                    ext = next((e for e in sorted(self.SPECIAL_FILES, key=len, reverse=True) if path.endswith(e)), "")
                    if not ext:
                        continue
                    name = raw_path.rsplit("/", 1)[-1]
                    key = "%s|%s" % (url, href.split("?")[0])
                    if key in seen:
                        continue
                    seen.add(key)
                    addr = getattr(line, "address", None)
                    lm = _re.match(r"^\s*\[([^\]]*)\]", text)
                    rows.append({"key": key, "url": url, "cid": chunk.cid, "xpath": getattr(addr, "xpath", "") or "",
                                 "href": href, "name": name, "ext": ext, "kind": self.SPECIAL_FILES[ext],
                                 "label": (lm.group(1) if lm else name)[:120]})
        if carried:
            self.store.upsert_files(url, rows, sorted(carried))
        real = rows
        out["files"] = len(real)
        return out

    def web_code_cpg(self, url: str, chunks, raw=None) -> Dict[str, int]:
        """The code blocks of a web page in the code property graph (G-233,
        G-235: "then web code blocks"). A line drawn at a `<pre>` whose text
        is Python (it parses, two lines or more) gets its graph BELOW that
        address; calls into libraries resolve by qualified name against the
        packages the store holds, as a `code://` file's do. Anything that
        does not parse -- shell, JSON, another language -- is left alone.

        `raw(address)` is the code AS THE PAGE HOLDS IT: the trie's value,
        newlines kept. A chunk's markdown line is the block on one line (its
        lines zip one-to-one with addresses, so it cannot hold several), and
        read from that the quicktour's 17 blocks graphed none (2026-10-18).
        Planted `VERTISCOPE_PLANT_CODE_FROM_LINE`: the markdown line only."""
        import ast as _ast
        import re as _re
        from .cpg import build_cpg

        out = {"blocks": 0, "python": 0, "nodes": 0, "edges": 0, "cross_out": 0}
        if not url or url.startswith(("code://", "vault://")):
            return out
        seen = set()
        for chunk in chunks:
            for line in getattr(chunk, "lines", []) or []:
                addr = getattr(line, "address", None)
                xp = getattr(addr, "xpath", "") if addr is not None else ""
                if not xp or not _re.search(r"/pre(\[\d+\])?$", xp) or xp in seen:
                    continue
                seen.add(xp)
                held = None
                if raw is not None and not _PLANT_CODE_FROM_LINE:
                    try:
                        held = raw(addr)
                    except Exception:                    # noqa: BLE001
                        held = None
                code = str(held or getattr(line, "text", "") or "").strip("\n")
                code = _re.sub(r"^\s*```[^\n]*\n", "", code)
                code = _re.sub(r"\n```\s*$", "", code)
                out["blocks"] += 1
                if code.count("\n") < 1:
                    continue
                # Unchanged since it was graphed: nothing to rewrite. Every
                # capture re-renders the page's dirty chunks, and each one
                # deleted and re-wrote the same block's nodes -- a read
                # between the two saw a block with edges and no nodes.
                cache = self.__dict__.setdefault("_web_cpg_digest", {})
                digest = hash(code)
                if cache.get((url, xp)) == digest:
                    out["unchanged"] = out.get("unchanged", 0) + 1
                    continue
                try:
                    _ast.parse(code)
                except SyntaxError:
                    continue
                prefix = xp
                g = build_cpg(code, url, prefix=prefix, qname="web")
                got = self.store.upsert_cpg(g, scope="%s|%s/" % (url, prefix))
                cache[(url, xp)] = digest
                if len(cache) > 20000:
                    cache.clear()
                out["python"] += 1
                for k in ("nodes", "edges", "cross_out"):
                    out[k] += got.get(k, 0)
        return out

    def index_pdf(self, data: bytes, url: str) -> Dict:
        """A PDF the reader reached, kept and chunked like a page (`G-248`).

        The file is kept as `pdfs/<sha1>.pdf` in the workspace -- the download
        -- and its text laid out as addressable HTML (`vertiscope.pdf`) goes
        through `index_html`: the same chunker, vector queue and graph."""
        from .pdf import pdf_to_html

        page_html, info = pdf_to_html(data, url)
        keep = self.path / "pdfs"
        keep.mkdir(exist_ok=True)
        f = keep / (info["sha1"] + ".pdf")
        if not f.exists():
            f.write_bytes(data)
        got = self.index_html(page_html, url, title=info.get("title") or "")
        info.update(url=got.url, chunks=got.chunks, lines=got.lines, addresses=got.addresses,
                    kept=str(f.relative_to(self.path)), bytes=len(data))
        return info

    def index_note(self, text: str, rel_path: str, *, vault: str = "vault",
                   title: str = "") -> ScanResult:
        """A vault note into the trie — no browser, no DOM (`T-5`).

        The same three steps as `index_html`, with the first one swapped:
        markdown is parsed to addressed detections by `vertiscope.vault` instead of
        HTML being parsed and tagged. Everything after that — `from_tags`,
        `ingest`, the chunker, the frequency rows, the graph — is the page path
        untouched, which is the whole reason the addressing was defined to look
        like a page's (see `vertiscope/vault.py`).

        `redact_url` is deliberately NOT applied. It strips campaign tags,
        userinfo and credential-shaped query values from *web* urls; a note url
        has no query and no userinfo, and putting a local path through a
        web-url redactor is how a path with a `?` in its name would quietly
        become a different note.
        """
        from .vault import note_url, tag_note

        url = note_url(vault, rel_path)
        tags = tag_note(text)
        trie = AddressTrie.from_tags(tags, url)
        report = RenderReport()
        chunks, _counts = self.ingest(url, trie, report=report,
                                      title=title or PurePosixPath(
                                          str(rel_path).replace("\\", "/")).stem)
        return ScanResult(
            url=url, addresses=len(trie), chunks=len(chunks),
            lines=sum(len(c.lines) for c in chunks), passes=1,
            # A note is not fetched, so there is no wire to compare against the
            # document. Reporting the document size for both says "nothing was
            # saved because nothing was sent", which is true, rather than
            # leaving `wire_saving` to divide by zero into a fake 0%.
            wire_bytes=len(text), document_bytes=len(text), report=report,
        )

    def index_source(self, text: str, rel_path: str, *,
                     root: str = "repo", title: str = "") -> ScanResult:
        """A source file into the trie — no browser, no DOM (`G-49`).

        The same three steps as `index_note`, with the first one swapped:
        Python is parsed to addressed detections by `vertiscope.source` instead
        of markdown being parsed by `vertiscope.vault`. Everything after that —
        `from_tags`, `ingest`, the chunker, the frequency rows, the graph — is
        the page path untouched, which is the whole reason the addressing was
        defined to look like a page's.

        What separates this from a note is only what reaches the ENCODER:
        `G-52` gives it the comments and docstrings and not the code, and
        that happens in `vectors.VectorQueue.push` off the `code://` scheme,
        not here. The trie holds the code either way, and so does the chunk a
        reader opens.
        """
        from .source import source_url, tag_source

        url = source_url(root, rel_path)
        tags = tag_source(text, root=root, rel_path=str(rel_path))
        trie = AddressTrie.from_tags(tags, url)
        report = RenderReport()
        chunks, _counts = self.ingest(
            url, trie, report=report,
            title=title or PurePosixPath(
                str(rel_path).replace("\\", "/")).name)
        # `G-235`: the file's code property graph beside its chunks, by the
        # same addresses. A file that does not parse has no graph, and its
        # chunks are indexed regardless (`tag_source`'s rule).
        self.last_cpg = None
        if str(rel_path).endswith(".py"):
            try:
                from .cpg import build_cpg
                g = build_cpg(text, url, str(rel_path).replace("\\", "/"))
                self.last_cpg = {**g["stats"], **self.store.upsert_cpg(g)}
            except SyntaxError:
                self.last_cpg = {"error": "does not parse"}
        return ScanResult(
            url=url, addresses=len(trie), chunks=len(chunks),
            lines=sum(len(c.lines) for c in chunks), passes=1,
            # Nothing was fetched, so nothing was saved: the same honest zero
            # `index_note` reports rather than dividing by a wire that does
            # not exist.
            wire_bytes=len(text), document_bytes=len(text), report=report,
        )

    def scan(
        self,
        url: str,
        *,
        config=None,
        duration: int = 25,
        pause: float = 1.2,
        passes: int = 6,
        headless: bool = True,
        incremental: bool = True,
        driver=None,
        progress: Optional[ProgressFn] = None,
    ) -> ScanResult:
        """Live path: drive the page, folding each snapshot in as it arrives.

        The store is written once, at the end, from the final trie. The
        per-pass deltas are what make the *scan* incremental — they say which
        chunks would need rewriting — but committing every pass would write
        the same rows repeatedly for a page still settling.

        Pass ``driver`` to reuse an open browser; :meth:`crawl` does, because
        starting Firefox costs several seconds and a crawl would otherwise pay
        it once per page.
        """
        from .browser import browser_session
        from .capture import stream_snapshots
        from .config import load_config

        cfg = config or load_config()
        # Two spellings, deliberately. `visit` is what the browser is pointed
        # at and is the reader's own url, whole: a page reached through a
        # link with a token in it needs that token to render the page that
        # was meant. `url` is what the store records, and the store has no
        # use for the token. Dropping it before navigation would have fetched
        # a different document; keeping it after would have filed the
        # reader's credentials under a page title.
        visit, url = url, redact_url(url)
        scan = StreamingScan(url, context_window=self.context_window)

        def drive(active) -> None:
            for passno, snapshot in stream_snapshots(
                active, visit, max_duration=duration, pause=pause,
                max_snapshots=passes, incremental=incremental,
            ):
                update = scan.push(snapshot, passno)
                scan.dirty_chunks(update)
                if progress:
                    progress("pass", update.row())

        if driver is not None:
            drive(driver)
        else:
            with browser_session(cfg, headless=headless) as owned:
                drive(owned)

        if scan.trie is None:
            raise RuntimeError(f"scan of {url} produced no snapshot")

        report = RenderReport()
        chunks, _counts = self.ingest(url, scan.trie, report=report)
        summary = scan.summary()
        return ScanResult(
            url=url,
            addresses=len(scan.trie),
            chunks=len(chunks),
            lines=sum(len(c.lines) for c in chunks),
            passes=int(summary.get("passes", 0)),
            wire_bytes=int(summary.get("wire_bytes", 0)),
            document_bytes=int(summary.get("snapshot_bytes", 0)),
            updates=scan.updates,
            report=report,
        )

    def sense(
        self,
        url: str,
        *,
        config=None,
        scrolls: int = 10,
        pause: float = 0.6,
        headless: bool = True,
        driver=None,
        variants: Optional[Dict[str, bool]] = None,
        progress: Optional[ProgressFn] = None,
    ) -> ScanResult:
        """Live path via the in-page sensor: the page keeps the fold.

        The peer of :meth:`scan`. That one serialises a settled snapshot per
        pass and folds it here; this one folds in the page and receives only
        the chunks whose digest moved. Both end at `ingest_chunks`, so the
        store, the index, the mirror and the REPL cannot tell them apart —
        which is what makes them comparable on the same pages.
        """
        from .browser import browser_session
        from .config import load_config
        from .sensing import Sensor

        cfg = config or load_config()
        # Navigate with the url as given, store the url redacted. See `scan`.
        visit, url = url, redact_url(url)
        passes: List[ScanUpdate] = []
        totals = {"lines": 0, "chunks": 0, "addresses": 0,
                  "wire": 0, "document": 0}
        # One trie for the page, fed by every drain. `scan` holds the same
        # structure for the snapshot path; holding it here is what makes the
        # two paths one pipeline instead of two.
        spine = StreamingScan(url, context_window=self.context_window)

        def drive(active) -> None:
            # The sensor's budget is in CHARACTERS -- it pre-splits in the
            # browser, before anything is rendered to markdown, and a
            # tokeniser is not something to ship into a page. The window is
            # in tokens, so it is converted rather than passed through: the
            # two are meant to cut at the same granularity, and handing a
            # token count to a character budget makes the browser-side split
            # three times finer than the renderer's.
            sensor = Sensor(active, visit,
                            budget=sensor_budget(self.context_window),
                            variants=variants)
            active.set_page_load_timeout(40)
            active.get(visit)
            time.sleep(pause)
            # The document, once, as the baseline the deltas are measured
            # against. Without it `wire_saving` divided by zero and reported
            # a flat 0.0% on every sensor run — a number that looked like a
            # measurement and was only an absent one.
            try:
                totals["document"] = len(active.page_source or "")
            except Exception:  # noqa: BLE001
                totals["document"] = 0
            sensor.boot()
            time.sleep(pause)
            for passno in range(scrolls + 1):
                if passno:
                    sensor.scroll()
                    time.sleep(pause)
                sp = sensor.drain(passno)
                # Through the trie, not around it. The sensor supplies
                # addressed units; the trie holds the page's structure and
                # `render_trie` partitions it, so the live path and the
                # snapshot path produce chunks the same way. Removal is
                # address-level: the sensor names departures by its own chunk
                # grouping, which the trie does not share.
                update = spine.absorb(sp.units, sp.passno,
                                      removed=sp.removed_addresses,
                                      moved=sp.moved_addresses)
                dirty = spine.dirty_chunks(update)
                if dirty:
                    self.ingest_chunks(url, dirty, complete=False)
                totals["lines"] += sp.lines
                totals["chunks"] += sp.changed
                totals["addresses"] += sp.addresses
                totals["wire"] += sp.wire_bytes
                if progress:
                    progress("pass", f"{sp.passno:>4} {sp.changed:>5} chunks "
                                     f"{sp.lines:>6} lines "
                                     f"{sp.drain_ms:>7.1f} drain "
                                     f"{sp.store_ms:>8.1f} store")

        if driver is not None:
            drive(driver)
        else:
            with browser_session(cfg, headless=headless) as owned:
                drive(owned)

        # One complete write from the settled trie. Per-pass writes keep the
        # store current while the page is being read, but they are deltas, so
        # they never retire a chunk that re-partitioning has replaced. The
        # snapshot path settles the same way, at the same point.
        if spine.trie is not None and len(spine.trie):
            self.ingest(url, spine.trie)

        stored = list(self.store.chunks(url))
        return ScanResult(
            url=url,
            addresses=totals["addresses"],
            chunks=len(stored),
            lines=totals["lines"],
            passes=scrolls + 1,
            wire_bytes=totals["wire"],
            document_bytes=totals["document"],
        )

    def links_from(self, url: str, *, same_host: bool = True) -> List[str]:
        """Documents this one links to, taken from its stored addresses.

        No separate link extractor: a link is a `urls.*` address, which the
        trie already holds, so the crawl frontier falls out of the same
        structure retrieval uses.

        Non-documents are filtered by extension. The extractor is deliberately
        attribute-agnostic — it takes URLs from *any* attribute, which is what
        makes it survive sites that invent their own — so a stylesheet's
        `href` is a `urls.internal` address just like an anchor's. That is
        right for extraction and wrong for a crawl frontier: without the
        filter, a six-page budget was spending two pages on `main.css` and
        `bootstrap.min.css`, which chunk to two lines of nothing.
        """
        from urllib.parse import urlsplit

        from .graphstore import canonical_url

        url = self.page_url(url)
        host = urlsplit(url).netloc
        out: List[str] = []
        # Seeded with the page's own canonical form, so a self-link does not
        # enter its own frontier under a second spelling.
        seen = {canonical_url(url) or url}
        for chunk in self.store.chunks(url):
            for address, value in self.store.addresses_of(chunk.cid):
                if not address.is_url:
                    continue
                target = canonical_url(value, url)
                if not target or target in seen or target == url:
                    continue
                if same_host and urlsplit(target).netloc != host:
                    continue
                if not _is_document(target):
                    continue
                seen.add(target)
                out.append(target)
        return out

    def crawl(
        self,
        seed: str,
        *,
        max_pages: int = 10,
        depth: int = 2,
        same_host: bool = True,
        config=None,
        headless: bool = True,
        legacy: bool = False,
        variants: Optional[Dict[str, bool]] = None,
        progress: Optional[ProgressFn] = None,
        **scan_kwargs,
    ) -> List[ScanResult]:
        """Breadth-first crawl from a seed, reusing one browser session.

        Exists because the rank factor needs a graph. Measured over the frozen
        corpus — 54 pages across 47 hosts — there were **six** resolvable
        cross-page links in total, so PageRank ran over containment edges
        alone and came out near-uniform: it contributed nothing to ranking
        while appearing to. A single-site crawl is what puts real edges in.

        Breadth-first rather than depth-first, so a shallow wide site is
        covered evenly when the page budget runs out instead of the budget
        disappearing down one branch.
        """
        from .browser import browser_session
        from .config import load_config

        from .graphstore import canonical_url

        cfg = config or load_config()
        results: List[ScanResult] = []
        frontier: List[Tuple[str, int]] = [(seed, 0)]
        # Keyed on the canonical form. `links_from` returns canonical targets
        # while the seed is whatever was typed, so a bare-host seed met its
        # own home page again as `https://a.test/` — a different string, never
        # in `visited`, and the crawl spent a page from its budget re-scanning
        # the page it started on.
        #
        # `canonical_url` and not `page_url`: the latter prefers a spelling
        # already in the store, so it *changes* for a url once that page has
        # been scanned — which is precisely the wrong property for a set that
        # records what has been scanned. A dedup key has to be a function of
        # the url alone.
        visited: set = set()

        # Directory-index aliases collapse too. A four-page crawl of
        # books.toscrape.com spent two of its pages on `https://books.toscrape.com`
        # and `https://books.toscrape.com/index.html` — the same document, byte
        # for byte (501 addresses, 20 chunks, 366 lines, twice). `canonical_url`
        # does not collapse them because they are genuinely different urls; for
        # a *crawl budget* they are one page, and the budget is the scarce
        # thing. Dedup key only: nothing is stored under a rewritten url.
        _INDEX_FILES = ("/index.html", "/index.htm", "/index.php",
                        "/default.html", "/default.htm", "/index.asp")

        def key_of(url: str) -> str:
            key = canonical_url(url) or url
            lowered = key.lower()
            for suffix in _INDEX_FILES:
                if lowered.endswith(suffix):
                    return key[: -len(suffix)] + "/"
            return key

        with browser_session(cfg, headless=headless) as driver:
            while frontier and len(results) < max_pages:
                url, level = frontier.pop(0)
                key = key_of(url)
                if key in visited:
                    continue
                visited.add(key)
                if progress:
                    progress("page", f"[{len(results) + 1}/{max_pages}] "
                                     f"depth {level}  {url}")
                try:
                    # Everything above this line — the frontier, the canonical
                    # keys, the index-file collapsing, the depth budget — is
                    # independent of how a page is read. Only this call knew
                    # about the extraction path, which is why crawling was the
                    # last thing keeping the snapshot-per-pass route alive.
                    if legacy:
                        result = self.scan(url, config=cfg, driver=driver,
                                           progress=progress, **scan_kwargs)
                    else:
                        result = self.sense(
                            url, config=cfg, driver=driver,
                            scrolls=scan_kwargs.get("passes", 10),
                            pause=scan_kwargs.get("pause", 0.6),
                            variants=variants, progress=progress)
                except Exception as exc:  # noqa: BLE001 — one bad page is data
                    if progress:
                        progress("error", f"{url}: {type(exc).__name__}: {exc}")
                    continue
                results.append(result)

                if level < depth:
                    for target in self.links_from(url, same_host=same_host):
                        if key_of(target) not in visited:
                            frontier.append((target, level + 1))
        return results

    # -- vectorisation ----------------------------------------------------
    def aggregate(self, url: str, **options):
        """Stage two of chunking for one page (`G-26`, `G-31`).

        Runs after the vectors exist, because it is decided on them. Exact
        duplicates are excluded first: `G-24` already resolved those in the
        database with no threshold, and feeding them in would let a page's
        repeated furniture dominate its own merge radius.

        Coarse-to-fine and localised to one shadow DOM, which is the design
        rather than a shortcut -- a corpus-wide clustering would merge a
        paragraph on one site with a paragraph on another and call the result
        a chunk of nothing.

        Returns the `Aggregation`, whose `skipped` says so when the page was
        under the significance gate. Writes nothing in that case: a page with
        nineteen chunks has nineteen nearest-neighbour distances, and a radius
        derived from their maximum is a radius derived from one number.
        """
        from .aggregate import aggregate_page

        stored = [c for c in self.store.chunks(url) if not c.redundant]
        # Document order, the same key `group_members` reads back by.
        stored.sort(key=lambda c: (c.xpath, c.part))
        # One query for the page's vectors, not one per chunk. The N+1 read
        # was most of what stage two cost -- see `embeddings_for`.
        vectors_by_cid = self.store.embeddings_for(url)
        cids, mds, vectors = [], [], []
        for chunk in stored:
            vector = vectors_by_cid.get(chunk.cid)
            if not vector:
                continue
            cids.append(chunk.cid)
            mds.append(chunk.md or "")
            vectors.append(vector)

        result = aggregate_page(cids, vectors, mds, url, **options)
        if not result.skipped:
            self._lexically_verify(result)
            self.store.set_groups(url, result.groups)
            self._vectorise_groups(result.groups)
        return result

    def _lexically_verify(self, result) -> int:
        """The frequency side's second opinion on each merge (`G-30`).

        A separate step after the semantic decision, never mixed into it.
        Two chunks the encoder called close that share almost no vocabulary
        are worth a second look -- and the look is all this is: the merge
        STANDS and the doubt is recorded, because tf-idf is the wrong
        instrument to overrule a meaning judgement with.

        **Restricted to each group's own nonzero columns.** The tf-idf matrix
        is sparse over a corpus-wide vocabulary and densifying a page of it
        would be hundreds of megabytes; cosine is unchanged by dropping
        columns that are zero in every row being compared, so the small dense
        block is exact rather than approximate.
        """
        from .aggregate import verify_with_lexical

        if not result.groups:
            return 0
        try:
            tfidf = self.freq.tfidf()
        except Exception:                               # noqa: BLE001
            return 0
        flagged = 0
        for group in result.groups:
            rows, keep = [], set()
            for cid in group.members:
                r = self.freq.row_of(cid)
                if r is None or r >= tfidf.shape[0]:
                    rows = []
                    break
                row = tfidf.getrow(r)
                rows.append(row)
                keep.update(row.indices.tolist())
            if len(rows) < 2 or not keep:
                continue
            cols = sorted(keep)
            block = {cid: np.asarray(row[:, cols].todense()).ravel()
                     for cid, row in zip(group.members, rows)}
            reason = verify_with_lexical(group, block)
            if reason:
                result.lexical_warnings.append((group.lead, reason))
                flagged += 1
        return flagged

    def _vectorise_groups(self, groups) -> int:
        """Give each merge group a vector for what it SAYS.

        A group's node in the projector stands for the merged text, so its
        position has to come from the merged text. Using the lead member's own
        vector would place a node for eight chunks wherever the first of them
        happened to land, which is not where the thing it draws belongs.

        **Re-vectorised when there is an embedder, averaged when there is
        not.** The assembled markdown is a real string and the encoder is the
        only thing that can say what it means -- an average of the members is
        a point in the convex hull of what they meant separately, which is
        close but is not the same claim, and on a group whose members are two
        halves of one sentence it is not even close. The average is kept as
        the fallback rather than dropping the group, because a workspace
        opened without an embedder should still draw its groups somewhere
        defensible.

        The members' own vectors are untouched. They remain what retrieval
        resolves to at 256 (`G-27`).
        """
        done = 0
        for group in groups or []:
            members = list(getattr(group, "members", group))
            lead = getattr(group, "lead", members[0] if members else "")
            if not lead or len(members) < 2:
                continue
            vector = None
            if self.embedder is not None:
                text = self.merged_markdown(lead)
                if text:
                    try:
                        # `embed_texts`, the method the rest of this file
                        # and `vectors.flush` both call. `embed` is not it.
                        vector = list(self.embedder.embed_texts([text])[0])
                    except Exception:               # noqa: BLE001
                        vector = None
            if vector is None:
                rows = [self.store.embedding(c) for c in members]
                rows = [r for r in rows if r and any(r)]
                if not rows:
                    continue
                block = np.asarray(rows, dtype=np.float32)
                mean = block.mean(axis=0)
                norm = float(np.linalg.norm(mean))
                # Re-normalised: the members are unit vectors and their mean
                # is not, and a shorter vector would read as a weaker one
                # everywhere a cosine is taken.
                vector = (mean / norm).tolist() if norm > 1e-9 else mean.tolist()
            self.store.set_group_embedding(lead, vector)
            done += 1
        return done

    def merged_markdown(self, lead: str) -> str:
        """A merge group rendered as one chunk, assembled not stored.

        The members joined in document order. Assembled on read so that a
        member rewritten by the next drain cannot leave a stale copy of itself
        inside a merged chunk -- the same reason the projections read from the
        trie instead of caching their own text.
        """
        members = self.store.group_members(lead)
        separator = chr(10) + chr(10)
        return separator.join(c.md for c in members if c.md)

    def flush_vectors(self, *, limit: Optional[int] = None,
                      progress: Optional[ProgressFn] = None) -> Dict[str, int]:
        """Embed everything queued, in batches, and write the vectors back.

        The single place the embedder is called on the write side. Splitting
        it out from ingest is what makes vectorisation a function of *settled*
        change rather than of delta count: a chunk rewritten on every frame of
        a scroll is embedded once, when someone asks a question.
        """
        if self.embedder is None or self.embeddings is None:
            return self.vectors.report()
        if progress and len(self.vectors):
            progress("embed", f"{len(self.vectors)} chunk(s) queued")
        produced = self.vectors.flush(self.embedder, limit=limit)
        return self.store_vectors(produced)

    # The same flush in three steps, for a caller that must not hold its lock
    # across the encoder: take (locked), encode (unlocked), store (locked).
    def take_vectors(self, limit: Optional[int] = None):
        if self.embedder is None or self.embeddings is None:
            return []
        return self.vectors.take(limit)

    def encode_taken(self, items) -> Dict[str, np.ndarray]:
        if not items or self.embedder is None:
            return {}
        return self.vectors.embed(self.embedder, items)

    def store_vectors(self, produced) -> Dict[str, int]:
        #: Which chunks this flush gave a vector, so a consumer downstream --
        #: the sidecar's chunk projector -- is handed exactly the delta.
        self.last_embedded = list(produced or ())
        if produced:
            rows = []
            for cid, vector in produced.items():
                self.embeddings.set(cid, vector)
                rows.append({"cid": cid, "emb": np.asarray(vector).tolist()})
            self.store._batch(
                "UNWIND $rows AS r MATCH (c:Chunk {cid: r.cid}) "
                "SET c.embedding = r.emb",
                rows,
            )
            # The embedding matrix is read live by the index: new vectors
            # need no rebuild, only a fresh row mapping.
            self._index_changed(set(produced))
        return self.vectors.report()

    # -- reading ----------------------------------------------------------
    def _hydrate_embeddings(self, *, backfill: bool = True,
                            progress: Optional[ProgressFn] = None) -> Dict[str, int]:
        """Make the query-side matrix reflect every chunk in the store.

        Two failures this exists to prevent, both of which present as "no
        results" under the strict triple product, where a zero is a veto:

        * vectors are **stored but not loaded** — they live on the Chunk
          nodes, which is the whole point of putting them there, but a freshly
          opened workspace starts with an empty matrix and scores every row 0;
        * vectors were **never computed**, because the page was indexed
          without an embedder. Asking for semantic search then vetoed
          everything and reported it as an absence of matches.

        The second is backfilled rather than reported: the chunks are present,
        embedding them is well defined, and the result is written back so the
        cost is paid once. Rows already set in this session are left alone.
        """
        counts = {"loaded": 0, "embedded": 0}

        # The matrix is created HERE when the store turns out to hold vectors,
        # rather than in `__init__` from whether an embedder was passed.
        #
        # Those are two different questions and conflating them cost the
        # semantic half of everything downstream. `__init__` says
        # `self.embeddings = EmbeddingMatrix() if embedder is not None else
        # None`, so a workspace opened to READ -- the sidecar, the 3D view,
        # any query -- had no matrix at all, and this method returned on its
        # first line. The vectors were on the Chunk nodes the whole time,
        # written by a build that did pass an embedder. Reading them back
        # needs no model.
        #
        # What it looked like: `build_layout` reported `spaces:
        # ['frequency']` and `equalised: false` on a workspace whose store
        # held 793 x 768 embeddings, and the 3D view said "not equalised" --
        # indistinguishable from a workspace that had never been embedded.
        #
        # Still None when the store holds nothing, which is what keeps the
        # behaviour for a genuinely unembedded workspace unchanged: an empty
        # matrix would score every chunk 0 on the semantic axis, and under
        # the strict triple product a zero is a veto, so search would answer
        # nothing and call it an absence of matches.
        # In bulk: which chunks are not loaded yet (a light query), then
        # their vectors in one read, and markdown only for those a backfill
        # will embed. It was one query per chunk inside a loop that loaded
        # every chunk's markdown first.
        loaded = (lambda c: self.embeddings is not None
                  and self.embeddings.row_of(c) is not None)
        todo = [c for (c,) in self.store._rows("MATCH (c:Chunk) RETURN c.cid")
                if c and not loaded(c)]
        missing: List = []
        if todo:
            got = dict(self.store._rows(
                "MATCH (c:Chunk) WHERE list_contains($cids, c.cid) "
                "RETURN c.cid, c.embedding", {"cids": todo}))
            empty = []
            for cid in todo:
                vector = got.get(cid)
                if vector is not None and any(vector):
                    if self.embeddings is None:
                        self.embeddings = EmbeddingMatrix()
                    self.embeddings.set(cid, np.asarray(vector, dtype=np.float32))
                    counts["loaded"] += 1
                else:
                    empty.append(cid)
            if empty and backfill and self.embedder is not None:
                wanted = set(empty)
                missing = [c for c in self.store.chunks() if c.cid in wanted]

        if self.embeddings is None:
            # Nothing stored and nothing to backfill into.
            return counts

        if missing and backfill and self.embedder is not None:
            if progress:
                progress("embed", f"{len(missing)} chunk(s) without a vector")
            matrix = self.embedder.embed_texts([c.md for c in missing])
            rows = []
            for chunk, vector in zip(missing, matrix):
                self.embeddings.set(chunk.cid, vector)
                rows.append({"cid": chunk.cid, "emb": vector.tolist()})
                counts["embedded"] += 1
            if rows:
                self.store._batch(
                    "UNWIND $rows AS r MATCH (c:Chunk {cid: r.cid}) "
                    "SET c.embedding = r.emb",
                    rows,
                )
        return counts

    @property
    def index(self) -> ThreeFormIndex:
        """The query surface, rebuilt when the graph has changed under it.

        **Built under a lock, because this is a lazy property in a threaded
        server.** Two concurrent `/search` requests both saw `None` here and
        both ran the hydration, which writes into one shared
        `EmbeddingMatrix`; the growth raced and search died with an
        `IndexError` out of `vectors.set`. The matrix is now safe on its own
        account, and this stops the expensive build happening twice as well.
        """
        if self._index is not None:
            if getattr(self, "_index_delta", None):
                with self._index_lock:
                    delta, self._index_delta = self._index_delta, set()
                    if delta and self._index is not None:
                        import time as _time
                        t0 = _time.perf_counter()
                        got = self._index.apply_delta(delta)
                        self.index_builds = (getattr(self, "index_builds", []) + [{
                            "delta": len(delta), **got,
                            "ms_delta": round((_time.perf_counter() - t0) * 1000, 1),
                            "at": round(_time.time(), 3)}])[-16:]
            if self._index is not None:
                return self._index
        with self._index_lock:
            # Re-checked inside: the thread that waited here wants the index
            # the first one built, not a second one.
            if self._index is None:
                # Flush before hydrating: the queue holds chunks whose
                # markdown moved, and hydration only fills in chunks that
                # have no vector at all. Without this a *changed* chunk would
                # keep answering with the vector of what it used to say.
                #
                # Each phase timed: a rebuild was measured at over a minute
                # live and lands on the first query after any embed batch.
                import time as _time
                t0 = _time.perf_counter()
                if self.embed_inline:
                    self.flush_vectors()
                t1 = _time.perf_counter()
                self._hydrate_embeddings(backfill=self.embed_inline)
                t2 = _time.perf_counter()
                self._index = ThreeFormIndex(
                    self.store, self.freq, self.embeddings,
                    embedder=self.embedder,
                ).build()
                t3 = _time.perf_counter()
                self.index_builds = (getattr(self, "index_builds", []) + [{
                    "ms_flush": round((t1 - t0) * 1000, 1),
                    "ms_hydrate": round((t2 - t1) * 1000, 1),
                    "ms_build": round((t3 - t2) * 1000, 1),
                    "at": round(_time.time(), 3)}])[-16:]
        return self._index

    #: Planted: every write throws the index away (a full rebuild per search).
    _PLANT_INDEX_REBUILD = [os.environ.get("VERTISCOPE_PLANT_INDEX_REBUILD") == "1"]
    #: After this long with no write, the full index is rebuilt off the
    #: request path (PageRank over the new edges) and swapped in.
    INDEX_QUIET_REBUILD_S = 30.0

    def _index_changed(self, cids) -> None:
        if self._PLANT_INDEX_REBUILD[0] or getattr(self, "_index", None) is None:
            self._index = None
            return
        with self._index_lock:
            pending = getattr(self, "_index_delta", None)
            if pending is None:
                pending = self._index_delta = set()
            pending.update(cids)
            self._index_written_at = time.time()
        self._schedule_index_rebuild()

    def _schedule_index_rebuild(self) -> None:
        """One background thread: once writes have been quiet for
        `INDEX_QUIET_REBUILD_S`, build a fresh index, apply what was written
        meanwhile, and swap it in."""
        import threading
        t = getattr(self, "_index_rebuilder", None)
        if t is not None and t.is_alive():
            return
        def run():
            while True:
                time.sleep(2.0)
                quiet = time.time() - getattr(self, "_index_written_at", 0)
                if quiet < self.INDEX_QUIET_REBUILD_S:
                    continue
                started = time.time()
                try:
                    fresh = ThreeFormIndex(self.store, self.freq, self.embeddings, embedder=self.embedder).build()
                except Exception:                    # noqa: BLE001
                    return
                with self._index_lock:
                    late = [c for c in (getattr(self, "_index_delta", None) or ())]
                    if getattr(self, "_index_written_at", 0) >= started and late:
                        fresh.apply_delta(late)
                    self._index = fresh
                    self._index_delta = set()
                    self.index_builds = (getattr(self, "index_builds", []) + [{
                        "background": True, "ms_build": round((time.time() - started) * 1000, 1),
                        "at": round(time.time(), 3)}])[-16:]
                if time.time() - getattr(self, "_index_written_at", 0) >= self.INDEX_QUIET_REBUILD_S:
                    return
        self._index_rebuilder = threading.Thread(target=run, name="vertiscope-index-rebuild", daemon=True)
        self._index_rebuilder.start()

    def search(self, query: str, k: int = 10, **kwargs) -> List[Hit]:
        return self.index.search(query, k=k, **kwargs)

    def addresses_for(self, cid: str):
        return self.store.addresses_of(cid)

    def pages(self) -> List[str]:
        return self.store.page_urls()

    def stats(self) -> Dict[str, object]:
        stats = dict(self.store.stats())
        stats["freq_rows"] = self.freq.shape[0]
        stats["freq_terms"] = self.freq.shape[1]
        stats["path"] = str(self.path)
        return stats

    def purge(self, url: str = "") -> None:
        """Unrecord a page, everywhere it is recorded.

        A purge that leaves residue is worse than no purge, because it
        advertises a guarantee it does not keep. There are five places one
        page lives, and every one of them is a way to answer "was this read?"

        * the **graph** — page, chunks, addresses and every edge on them;
        * the **frequency matrix** — the row, *and* the words: a vocabulary
          is a bag of words of the corpus and it is written to disk as plain
          json, so a page's terms outlived the page until `forget_vocabulary`;
        * the **semantic matrix** — zeroed rows still carried the chunk id,
          which is a hash of the url and so a yes/no oracle for anyone
          holding one;
        * the **queue** — chunks waiting to be vectorised hold their markdown
          in memory. Nothing dropped them, so a page purged before the next
          flush was purged from the store and then written back into it;
        * the **mirror** on disk.

        Retire the frequency rows *before* dropping the chunks, while the
        graph can still say which rows they were. Doing it after leaves rows
        with no chunk: idf then counts documents that no longer exist, which
        shifts every score without failing anything.

        **What this does not do.** Content that has been *checkpointed* into
        `graph.kuzu` survives a single-page purge as bytes in that file: the
        rows are gone from every query and every index, and the text is still
        findable with `grep`. Kuzu has no `VACUUM`, and `CHECKPOINT` was
        measured not to reclaim the pages, so the only scrub is to write the
        store out again from scratch. `purge()` with no url does exactly that
        -- it removes the directory -- and is therefore complete; per-page
        compaction is a rebuild and is not attempted here.

        This used to say that anything written and purged inside one session
        leaves nothing, "because it was never checkpointed". **That premise is
        not ours to make.** Kuzu checkpoints on its own schedule, and a
        checkpoint inside the session is enough: forcing one leaves residue
        every time, and waiting for kuzu to choose one left residue in 4 runs
        out of 40. So a same-session purge is *usually* a scrub and not
        reliably one, and the honest statement is that **no single-page purge
        scrubs bytes; only `purge()` with no url does.**
        `tests/test_privacy.py` pins both halves, the second one
        deterministically rather than one run in ten.
        """
        # Through the stored spelling, so `--url https://a.test/` purges the
        # page held as `https://a.test` instead of silently purging nothing.
        url = self.page_url(url) if url else ""
        if url:
            cids = [chunk.cid for chunk in self.store.chunks(url)]
            for cid in cids:
                self.freq.remove(cid)
            if self.embeddings is not None:
                self.embeddings.forget(cids)
            self.vectors.forget(cids)
            self.store.purge_page(url)
            self.freq.forget_vocabulary()
            jsonl = self.mirror_path(url)
            if jsonl.exists():
                jsonl.unlink()
            # Written through immediately. Everything above is in memory
            # until `close`, so a forget followed by a crash -- or by a
            # session the reader simply never closed cleanly -- left the
            # words and the rows of the forgotten page on disk. A forget has
            # to survive the process it was asked in.
            self.freq.save(self.path / "freq")
        else:
            self.close()
            shutil.rmtree(self.path, ignore_errors=True)
            self.__init__(self.path, context_window=self.context_window,
                          embedder=self.embedder)
        self._index = None


# Extensions that are never a document worth chunking. An allowlist would be
# wrong here: most real pages have no extension at all (`/tag/life/`), so
# requiring one would reject exactly the links a crawl wants.
_NON_DOCUMENT_EXTENSIONS = frozenset({
    ".css", ".js", ".mjs", ".json", ".xml", ".rss", ".atom", ".map",
    ".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp", ".avif", ".ico", ".bmp",
    ".woff", ".woff2", ".ttf", ".otf", ".eot",
    ".mp4", ".webm", ".ogg", ".mp3", ".wav", ".m4a", ".mov", ".avi",
    ".pdf", ".zip", ".gz", ".tar", ".rar", ".7z", ".exe", ".dmg", ".iso",
    ".csv", ".xlsx", ".doc", ".docx", ".ppt", ".pptx",
})


def _is_document(url: str) -> bool:
    """Whether a URL plausibly leads to a page rather than an asset."""
    from urllib.parse import urlsplit

    path = urlsplit(url).path.lower()
    dot = path.rfind(".")
    slash = path.rfind("/")
    if dot <= slash:            # no extension in the final segment
        return True
    return path[dot:] not in _NON_DOCUMENT_EXTENSIONS


def _slug(url: str) -> str:
    """The old, readable mirror name. Kept only to recognise its own output.

    `ls build/chunks/` printed a browsing history: `en.wikipedia.org-wiki-
    Insomnia.jsonl` says everything about a page without opening it, and a
    directory listing is available to anything that can read the disk and to
    every backup that ever ran. The name is a digest now
    (`vertiscope.privacy.store_name`).

    This function survives so that :meth:`Workspace._retire_readable_names`
    can tell a legacy file from a migrated one without a manifest — a
    manifest mapping digests back to urls would have re-created the leak in a
    second file.
    """
    import hashlib

    body = url.split("//")[-1]
    safe = "".join(c if (c.isalnum() or c in "-_.") else "-" for c in body)
    if len(safe) <= 60:
        return safe
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:8]
    return f"{safe[:50]}-{digest}"
