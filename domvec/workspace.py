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
        added = skipped = 0
        for chunk in self.store.chunks():
            if self.freq.row_of(chunk.cid) is not None:
                skipped += 1
                continue
            self.freq.add(chunk.cid, chunk.md or "")
            added += 1
            if progress and added % 2000 == 0:
                progress("lexical", "%d rows added" % added)
        if added:
            self.freq.save(self.path / "freq")
        self._index = None          # the ranking is stale by construction
        return {"added": added, "already_had_one": skipped}

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
    ) -> Tuple[List[MarkdownChunk], Dict[str, int]]:
        """Render, index and store one page's trie. The single write path.

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
        return self.ingest_chunks(url, chunks, addresses, title=title,
                                  root_hash=trie.root_hash, defer=defer)

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
        if any(job["url"] == url for job in self._pending):
            self.settle()
        store = self._store
        if complete:
            superseded = ({c.cid for c in store.chunks(url)}
                          - {c.cid for c in chunks})
        else:
            superseded = set(removed or ())
        for cid in superseded:
            self.freq.remove(cid)

        rows = {c.cid: self.freq.add(c.cid, c.markdown) for c in chunks}

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
        store.conn.execute(
            "MERGE (p:Page {url: $url}) SET p.title = $title",
            {"url": url, "title": title},
        )
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
            )
        # The mirror is rewritten only by a write that describes the whole
        # page. A delta names some chunks; writing those alone replaced the
        # file with a fragment of itself, and measured across 60 swept pages
        # 21 of them held fewer chunks on disk than in the store — one with
        # 16 against 537. The mirror is meant to be the checkpoint the store
        # can be rebuilt from, so a partial write must add to it, not define
        # it.
        mirror = self.mirror_path(url)
        if complete:
            write_jsonl(chunks, mirror)
        else:
            merged = {c.cid: c for c in read_jsonl(mirror)} if mirror.exists() else {}
            merged.update({c.cid: c for c in chunks})
            for cid in (removed or ()):
                merged.pop(cid, None)
            write_jsonl(list(merged.values()), mirror)
        self._index = None      # ranks are stale once the graph changed
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

    def index_note(self, text: str, rel_path: str, *, vault: str = "vault",
                   title: str = "") -> ScanResult:
        """A vault note into the trie — no browser, no DOM (`T-5`).

        The same three steps as `index_html`, with the first one swapped:
        markdown is parsed to addressed detections by `domvec.vault` instead of
        HTML being parsed and tagged. Everything after that — `from_tags`,
        `ingest`, the chunker, the frequency rows, the graph — is the page path
        untouched, which is the whole reason the addressing was defined to look
        like a page's (see `domvec/vault.py`).

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
        Python is parsed to addressed detections by `domvec.source` instead
        of markdown being parsed by `domvec.vault`. Everything after that —
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
            self._index = None       # scores are stale once vectors moved
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
        missing: List = []
        for chunk in self.store.chunks():
            if self.embeddings is not None and                     self.embeddings.row_of(chunk.cid) is not None:
                continue
            vector = self.store.embedding(chunk.cid)
            if vector and any(vector):
                if self.embeddings is None:
                    self.embeddings = EmbeddingMatrix()
                self.embeddings.set(chunk.cid, np.asarray(vector, dtype=np.float32))
                counts["loaded"] += 1
            else:
                missing.append(chunk)

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
            return self._index
        with self._index_lock:
            # Re-checked inside: the thread that waited here wants the index
            # the first one built, not a second one.
            if self._index is None:
                # Flush before hydrating: the queue holds chunks whose
                # markdown moved, and hydration only fills in chunks that
                # have no vector at all. Without this a *changed* chunk would
                # keep answering with the vector of what it used to say.
                self.flush_vectors()
                self._hydrate_embeddings()
                self._index = ThreeFormIndex(
                    self.store, self.freq, self.embeddings,
                    embedder=self.embedder,
                ).build()
        return self._index

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
    (`domvec.privacy.store_name`).

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
