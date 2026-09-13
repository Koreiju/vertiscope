"""The unified store: trie addresses, markdown chunks and embeddings in one graph.

The requirement this exists to satisfy is navigational: *an address of the
trie must reach its markdown chunk and that chunk's embedding*. A relational
layout would answer it with a join per hop; a graph answers it with an edge,
and the hops are what the REPL walks.

Schema
------
::

    (Page   {url})              one scanned document
    (Chunk  {cid})              one markdown chunk + its semantic vector
    (Address{aid})              one content address (a trie leaf)

    (Page)  -[:HasChunk]->  (Chunk)
    (Chunk) -[:Anchors {ord}]-> (Address)     one per markdown line, in order
    (Chunk) -[:Contains]->  (Chunk)           xpath ancestry between chunks
    (Chunk) -[:LinksTo]->   (Page)            a urls.* address that resolves

Only trie **leaves** become nodes. The trie's internal structure is not
stored, because it is recoverable: ancestry is a prefix test on the absolute
xpath (THEORY Prop. 11.2), so the 2.69 internal nodes per leaf measured on the
corpus would be 179,000 rows encoding something a string comparison already
answers. `Contains` is stored only between *chunks*, where it is the traversal
the reader actually makes.

What lives where
----------------
The semantic vector sits on the chunk, because it is a function of that
chunk's text alone. The frequency vector does not, because its idf component
is a function of the corpus (THEORY Prop. 14.6) and would go stale on every
subsequent scan — it lives in :class:`domvec.vectors.FreqMatrix`, joined back
by the integer `row` stored here. See that module for the full argument.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlsplit, urlunsplit

from .address import ContentAddress
from .markdown import MarkdownChunk
from .privacy import redact_url

__all__ = ["GraphStore", "StoredChunk", "canonical_url"]

EMBED_DIM = 768

_SCHEMA = [
    """CREATE NODE TABLE IF NOT EXISTS Page(
        url STRING, title STRING, scanned_at DOUBLE, root_hash STRING,
        chunk_count INT64, address_count INT64, PRIMARY KEY(url))""",
    f"""CREATE NODE TABLE IF NOT EXISTS Chunk(
        cid STRING, url STRING, xpath STRING, part INT64, md STRING,
        chars INT64, line_count INT64, row INT64, embedding FLOAT[{EMBED_DIM}],
        dup_of STRING, dup_n INT64, group_of STRING, group_n INT64,
        group_embedding FLOAT[{EMBED_DIM}],
        PRIMARY KEY(cid))""",
    """CREATE NODE TABLE IF NOT EXISTS Address(
        aid STRING, akey STRING, url STRING, xpath STRING, tag STRING,
        accessor STRING, value STRING, content_hash STRING,
        PRIMARY KEY(aid))""",
    "CREATE REL TABLE IF NOT EXISTS HasChunk(FROM Page TO Chunk)",
    "CREATE REL TABLE IF NOT EXISTS Anchors(FROM Chunk TO Address, ord INT64)",
    "CREATE REL TABLE IF NOT EXISTS Contains(FROM Chunk TO Chunk)",
    "CREATE REL TABLE IF NOT EXISTS LinksTo(FROM Chunk TO Page)",
]

#: Columns added after stores already existed. Kuzu has no
#: `ADD COLUMN IF NOT EXISTS`, so these are run individually and their
#: "already exists" is swallowed -- the alternative is a store written
#: yesterday failing to open today.
_MIGRATIONS = [
    "ALTER TABLE Chunk ADD dup_of STRING",
    "ALTER TABLE Chunk ADD dup_n INT64",
    "ALTER TABLE Chunk ADD group_of STRING",
    "ALTER TABLE Chunk ADD group_n INT64",
    f"ALTER TABLE Chunk ADD group_embedding FLOAT[{EMBED_DIM}]",
]


def canonical_url(url: str, base: str = "") -> str:
    """Absolutise, redact, and strip the fragment, so link targets can match.

    The fragment is dropped because it addresses a position *within* a
    document and the graph's Page node is the document. Keeping it would make
    `a.html` and `a.html#top` two pages that are one page.

    The query is **not** dropped, and the reason is the same one: for a great
    many pages the query is the document. `?id=123`, `?v=<id>`, `?page=2` and
    `?query=university+library` all name which page this is, and a store that
    threw them away would answer with a different document than the one that
    was read.

    What is dropped is everything in the query that is not the document:
    campaign and click identifiers, which are attached by whoever sent you
    and change nothing the page says, and credential-shaped values, which a
    local database has no business holding. `domvec.privacy` owns those
    rules; this function is where they meet the store, so that a url looked
    *up* is redacted exactly as the url that was stored. Userinfo goes with
    them — `https://user:pass@host/` is a password in a database with no
    password on it.
    """
    if base:
        url = urljoin(base, url)
    url = redact_url(url)
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if parts.scheme not in ("http", "https"):
        return ""
    return urlunsplit((parts.scheme, parts.netloc, parts.path or "/",
                       parts.query, ""))


@dataclass
class StoredChunk:
    """A chunk read back out of the graph."""

    cid: str
    url: str
    xpath: str
    part: int
    md: str
    chars: int
    line_count: int
    row: int
    #: The cid of the chunk this one draws a byte-identical copy of, on the
    #: same page; empty when this chunk is the one that keeps the content.
    #: See `_same_content`.
    dup_of: str = ""
    #: How many chunks on the page draw this content, counting this one. 1
    #: unless this is the chunk the copies point at.
    dup_n: int = 1
    #: The cid leading the merge group this chunk belongs to (`G-26`), or ""
    #: when it belongs to none. Unlike `dup_of` this is NOT a claim that the
    #: chunks are the same -- it is a claim that they read as one thing.
    group_of: str = ""
    #: How many chunks are in that group, carried on the lead.
    group_n: int = 1

    @property
    def markdown(self) -> str:
        return self.md

    @property
    def redundant(self) -> bool:
        """True when another chunk on this page already draws this."""
        return bool(self.dup_of)

    @property
    def leads_group(self) -> bool:
        """True when this chunk is the one a merge group is filed under."""
        return self.group_of == self.cid and self.group_n > 1


def _same_content(chunks) -> tuple:
    """Which chunks on this page draw exactly what another chunk draws.

    Returns ``(canonical, copies)``: for every redundant chunk, the cid of the
    one chunk that keeps the content; and for every canonical chunk, how many
    chunks in total draw it. A chunk that is nobody's copy maps to ``""`` and
    to a count of 1.

    **Marked, not merged, and the anchors are why.** `Anchors {ord}` pairs a
    chunk's markdown lines with its addresses BY POSITION -- the docstring on
    `ingest_chunks` records what happened the last time that alignment slipped
    -- so one chunk holding 125 tiles' addresses would attribute one line to
    125 elements and the address-to-document link, the single guarantee the
    scheme exists to provide, would point at 124 wrong elements. Every chunk
    keeps its own node, its own anchors and its own addresses; the trie is
    untouched and still holds `url : xpath : markdown : content` for all of
    them. What is added is a fact ABOUT the chunks, which consumers may then
    ask for: draw one node instead of 125, embed one string instead of 125.

    Scoped to one page, because that is where redundancy means redundancy.
    Two pages sharing a cookie banner are two documents that happen to have
    the same sentence in them, and collapsing across pages would make a hit on
    one page point into another.

    Exact bytes, deliberately. This is the arm that needs no embeddings and no
    threshold, and it is not small: measured on `build/vaultws256`, 38 groups
    and 176 redundant chunks of 5,337, of which ONE group is 125 copies of
    "Press Down Arrow to preview item details" -- archive.org renders each
    search result as a `<tile-dispatcher>` custom element with its own shadow
    root, and every one of those roots carries the same accessibility hint.
    They are 125 distinct addresses drawing one string, which is exactly what
    `_dedupe` cannot see: it is element-scoped, grouping units by `addr.xpath`
    and comparing only within a group, so identical content at DIFFERENT
    xpaths has never been compared to itself.

    The near-duplicate case -- the same thing said slightly differently -- is
    a separate stage and needs the embeddings. This one does not, so it does
    not wait for them.
    """
    first: dict = {}
    canonical: dict = {}
    counts: dict = {}
    for chunk in chunks:
        key = chunk.markdown
        head = first.get(key)
        if head is None:
            first[key] = chunk.cid
            counts[chunk.cid] = 1
        else:
            canonical[chunk.cid] = head
            counts[head] = counts.get(head, 1) + 1
    return canonical, {cid: n for cid, n in counts.items() if n > 1}


class GraphStore:
    """Kuzu-backed unified store. Use as ``with GraphStore(path) as gs:``."""

    def __init__(self, path, *, read_only: bool = False) -> None:
        import kuzu

        self.path = Path(path)
        self.read_only = bool(read_only)
        if not self.read_only:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        # A second holder of this directory is a *conflict*, not a wait.
        # Kuzu takes an OS lock on the store, so two sweeps pointed at one
        # workspace would otherwise fail deep inside the first query with a
        # message that names neither the workspace nor the other holder.
        # Say which path, and say it at open time.
        #
        # `read_only` is what lets the sidecar and the MCP server look at one
        # workspace at the same time. Kuzu admits MANY readers or ONE writer:
        # measured, two read-only processes share a store and a single writer
        # excludes every other opener, read-only included. Both of those
        # servers are read-only in intent and were opening read-write, so the
        # first one started locked the second out of its own workspace.
        # Asking for the weaker mode is therefore not a precaution here; it
        # is the thing that makes them coexist.
        try:
            self.db = kuzu.Database(str(self.path), read_only=self.read_only)
        except Exception as exc:  # noqa: BLE001
            if "lock" in str(exc).lower():
                raise RuntimeError(
                    f"workspace {self.path} is held by another process — "
                    + ("a WRITER excludes readers too, so check for a scan or "
                       "an --enact sidecar on this store"
                       if self.read_only else
                       "close it, or give this run its own store "
                       "(--build <dir> for the repl, --workspace <dir> for "
                       "the cli)")
                ) from exc
            raise
        self.conn = kuzu.Connection(self.db)
        # DDL is a write. A read-only open of an existing store has nothing to
        # create, and running it would turn a shared read into a lock error.
        if not self.read_only:
            for statement in _SCHEMA:
                self.conn.execute(statement)
            for statement in _MIGRATIONS:
                try:
                    self.conn.execute(statement)
                except RuntimeError:
                    pass    # already there

    def __enter__(self) -> "GraphStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def close(self) -> None:
        """Release the connection *and* the database file lock.

        Closing only the connection leaves kuzu holding an OS lock on the
        directory, so reopening the same workspace in the same process fails
        with "Could not set lock on file". That makes scan-then-search, or
        any test that closes and reopens, impossible — and the failure comes
        from the second open, pointing away from the missing close.
        """
        try:
            self.conn.close()
        except Exception:
            pass
        try:
            self.db.close()
        except Exception:
            pass

    # -- writes ------------------------------------------------------------
    def ingest(
        self,
        url: str,
        addresses: Sequence[Tuple[ContentAddress, str, str]],
        chunks: Sequence[MarkdownChunk],
        *,
        rows: Optional[Dict[str, int]] = None,
        embeddings: Optional[Dict[str, Sequence[float]]] = None,
        title: str = "",
        root_hash: str = "",
        complete: bool = True,
    ) -> Dict[str, int]:
        """Write one page: its addresses, its chunks, and the edges between.

        ``addresses`` is ``(address, value, content_hash)``; ``rows`` maps a
        chunk id to its integer row in the frequency matrix; ``embeddings``
        maps a chunk id to its semantic vector.

        Idempotent by MERGE on the primary keys, so re-scanning a page updates
        rather than duplicating — and **reconciling**, so a re-scan of a page
        that lost content removes what is gone.

        The reconciliation is not tidiness. MERGE alone left a chunk's previous
        `Anchors` in place beside its new ones, so a chunk that shrank from 21
        lines to 7 kept 21 anchors. Both `MarkdownChunk.from_json` and the REPL
        pair markdown lines with anchors *by position*, so every line was then
        attributed to the wrong address — the address-to-document link, which
        is the one guarantee the whole scheme exists to provide, silently
        pointing at the wrong element.
        """
        rows = rows or {}
        embeddings = embeddings or {}
        counts = {"addresses": 0, "chunks": 0, "anchors": 0,
                  "contains": 0, "links": 0,
                  "chunks_removed": 0, "addresses_removed": 0}

        # Reconcile before writing: drop what this page no longer has, so the
        # rest of this method only ever adds. Doing it first means a chunk's
        # stale anchors are gone before its new ones are merged, which is the
        # ordering the alignment depends on.
        _t = time.perf_counter()
        counts.update(self._reconcile(url, chunks, addresses,
                                      complete=complete))
        counts["ms_reconcile"] = round((time.perf_counter() - _t) * 1000, 1)
        _t = time.perf_counter()

        self.conn.execute(
            "MERGE (p:Page {url: $url}) SET p.title = $title, "
            "p.scanned_at = $ts, p.root_hash = $rh, p.chunk_count = $nc, "
            "p.address_count = $na",
            {"url": url, "title": title, "ts": time.time(), "rh": root_hash,
             "nc": len(chunks), "na": len(addresses)},
        )

        # Everything below goes through UNWIND rather than a statement per
        # row. Measured on one page: 104 rows/s row-by-row against 27,000/s
        # batched, which is the difference between 17 minutes and 4 seconds
        # for the 54-page corpus. Each statement is still a single MERGE, so
        # idempotence is unchanged; only the trip count is.
        address_rows = [
            {"aid": a.aid, "akey": a.key(), "url": a.url, "xp": a.xpath,
             "tag": a.tag, "acc": a.accessor, "val": (v or "")[:2000],
             "ch": ch}
            for a, v, ch in addresses
        ]
        # Which chunk line anchors each address, so the address write can
        # create the edge while it still has the node bound. See the fused
        # statement below for why that is worth arranging.
        anchor_of = {}
        for chunk in chunks:
            for ordinal, line in enumerate(chunk.lines):
                if line.address is not None:
                    anchor_of[line.address.aid] = (chunk.cid, ordinal)
        counts["addresses"] = len(address_rows)
        counts["ms_addresses"] = round((time.perf_counter() - _t) * 1000, 1)
        _t = time.perf_counter()

        # A vector is written only when there is one to write.
        #
        # `ingest_chunks` never supplies embeddings -- `flush_vectors` computes
        # them afterwards, deliberately, so that vectorisation is a function of
        # settled change rather than of delta count. Every chunk write was
        # therefore materialising 768 zero floats and storing them, ~11,500
        # per page, for `flush_vectors` to overwrite. Measured on identical
        # rows, dropping `c.embedding` from the SET is **4.0x** on this
        # statement: 33.77 -> 8.36 ms/page.
        #
        # The absent vector is spelled NULL rather than zeros, and the reader
        # already means the same thing by both: `flush_vectors`' backfill asks
        # `if vector and any(vector)` and treats anything else as missing, for
        # which an all-zero vector already qualified. `embedding()` gains the
        # NULL guard, since `list(None)` raises.
        has_vectors = bool(embeddings)
        canonical, copies = _same_content(chunks)
        chunk_rows = []
        for chunk in chunks:
            row = {
                "cid": chunk.cid, "url": chunk.url, "xp": chunk.xpath,
                "part": chunk.part, "md": chunk.markdown, "chars": chunk.chars,
                "lines": len(chunk.lines), "row": int(rows.get(chunk.cid, -1)),
                "dup": canonical.get(chunk.cid, ""),
                "dupn": copies.get(chunk.cid, 1),
            }
            if has_vectors:
                vector = list(embeddings.get(chunk.cid) or [])[:EMBED_DIM]
                if len(vector) < EMBED_DIM:
                    vector = vector + [0.0] * (EMBED_DIM - len(vector))
                row["emb"] = vector
            chunk_rows.append(row)
        if chunk_rows:
            self._batch(
                "UNWIND $rows AS r MERGE (c:Chunk {cid: r.cid}) "
                "SET c.url = r.url, c.xpath = r.xp, c.part = r.part, "
                "c.md = r.md, c.chars = r.chars, c.line_count = r.lines, "
                "c.dup_of = r.dup, c.dup_n = r.dupn, "
                "c.row = r.row" + (", c.embedding = r.emb" if has_vectors else ""),
                chunk_rows,
            )
            self._batch(
                "UNWIND $rows AS r MATCH (p:Page {url: r.url}), "
                "(c:Chunk {cid: r.cid}) MERGE (p)-[:HasChunk]->(c)",
                [{"url": url, "cid": c.cid} for c in chunks],
            )
            counts["chunks"] = len(chunk_rows)
        counts["ms_chunks"] = round((time.perf_counter() - _t) * 1000, 1)
        _t = time.perf_counter()

        # Addresses and their anchors, in ONE statement.
        #
        # These were two: `MERGE (a:Address {aid})` to write the node, then
        # `MATCH (a:Address {aid})` moments later to hang an edge off it. The
        # second lookup is against a table with 329,712 rows in it and costs
        # 0.8ms every time -- and asking for the Chunk and the Address in one
        # pattern costs 6.5ms, eight times the sum of asking for each alone,
        # because the planner stops treating it as two key lookups.
        #
        # Measured on MDN's CSS index, 2,924 anchors over 191 dirty chunks:
        #
        #     comma MATCH, as shipped          19,136 ms   6.54 ms/row
        #     two MATCH clauses                10,964 ms   3.75 ms/row
        #     fused with the address MERGE      1,448 ms   0.50 ms/row
        #
        # The MERGE has already bound the node, so the fused form does not
        # look the address up at all. Only the Chunk is matched, and a Chunk
        # lookup is 0.045ms.
        #
        # Sound because the pairing is one to one: a line carries one address
        # and an address reaching two chunks is the defect
        # `test_the_page_is_still_partitioned` forbids. An anchor whose
        # address is not in this write -- which a caller passing a narrowed
        # address list can produce -- falls through to the two-lookup form
        # rather than being dropped.
        fused_rows, plain_rows = [], []
        for row in address_rows:
            hit = anchor_of.pop(row["aid"], None)
            if hit is None:
                plain_rows.append(row)
            else:
                fused_rows.append(dict(row, cid=hit[0], ord=hit[1]))

        if fused_rows:
            self._batch(
                "UNWIND $rows AS r MERGE (a:Address {aid: r.aid}) "
                "SET a.akey = r.akey, a.url = r.url, a.xpath = r.xp, "
                "a.tag = r.tag, a.accessor = r.acc, a.value = r.val, "
                "a.content_hash = r.ch "
                "WITH a, r MATCH (c:Chunk {cid: r.cid}) "
                "CREATE (c)-[:Anchors {ord: r.ord}]->(a)",
                fused_rows,
            )
        if plain_rows:
            self._batch(
                "UNWIND $rows AS r MERGE (a:Address {aid: r.aid}) "
                "SET a.akey = r.akey, a.url = r.url, a.xpath = r.xp, "
                "a.tag = r.tag, a.accessor = r.acc, a.value = r.val, "
                "a.content_hash = r.ch",
                plain_rows,
            )

        # Whatever is left in `anchor_of` is an anchor whose address this
        # write did not carry. Rare, and it still has to be created.
        anchor_rows = [
            {"cid": cid, "aid": aid, "ord": ordinal}
            for aid, (cid, ordinal) in anchor_of.items()
        ]
        if anchor_rows:
            # CREATE, not MERGE, and `_reconcile` is what makes that sound:
            # it has just cleared every anchor on every chunk in this batch,
            # so no edge can exist for MERGE to find. The check was not free
            # -- 19.1 seconds of a 22-second capture on a 191-chunk delta --
            # because a relationship MERGE scans the edges a node already has,
            # and a chunk on a reference page has hundreds.
            #
            # The safety here is the postcondition, not the statement. If the
            # delete above ever stops covering the written set, this starts
            # producing duplicate anchors, and duplicate anchors misattribute
            # every line after the first -- which is the failure
            # `ingest_chunks` was written to prevent. The two belong together
            # and this comment is the tie.
            self._batch(
                "UNWIND $rows AS r MATCH (c:Chunk {cid: r.cid}) "
                "MATCH (a:Address {aid: r.aid}) "
                "CREATE (c)-[:Anchors {ord: r.ord}]->(a)",
                anchor_rows,
            )
            counts["anchors"] = len(anchor_rows)
        counts["anchors"] = counts.get("anchors", 0) + len(fused_rows)
        counts["ms_anchors"] = round((time.perf_counter() - _t) * 1000, 1)
        _t = time.perf_counter()

        counts["contains"] = self._link_containment(chunks)
        counts["ms_contains"] = round((time.perf_counter() - _t) * 1000, 1)
        _t = time.perf_counter()
        counts["links"] = self._link_hyperlinks(url, addresses, chunks)
        counts["ms_links"] = round((time.perf_counter() - _t) * 1000, 1)
        return counts

    def _reconcile(
        self,
        url: str,
        chunks: Sequence[MarkdownChunk],
        addresses: Sequence[Tuple[ContentAddress, str, str]],
        complete: bool = True,
    ) -> Dict[str, int]:
        """Remove what this page used to have and no longer does.

        Three things go stale when a page shrinks or is restructured:

        * **chunk anchors** — a chunk keeps every anchor it ever had, and since
          lines are paired with anchors by position, one stale anchor
          misattributes every line after it. Cleared for the chunks being
          written, whether or not anything was removed, because a chunk that
          merely got *shorter* has the same problem.
        * **chunks** — a page that lost a section drops whole chunks, which
          otherwise stay retrievable forever.
        * **addresses** — nodes for elements that no longer exist.
        """
        removed = {"chunks_removed": 0, "addresses_removed": 0}

        keep_chunks = {c.cid for c in chunks}
        existing = [r[0] for r in self._rows(
            "MATCH (:Page {url: $url})-[:HasChunk]->(c:Chunk) RETURN c.cid",
            {"url": url})]

        # A partial write describes some of the page, not all of it. Only the
        # chunks actually being rewritten lose their anchors — the alignment
        # requirement is per chunk, not per page — and nothing is dropped for
        # being absent, because absence from a delta carries no information.
        # Treating a delta as complete deleted every chunk it did not mention:
        # a page whose last pass emitted one chunk kept one of its hundred.
        if not complete:
            existing = [cid for cid in existing if cid in keep_chunks]

        # Every chunk BEING WRITTEN loses its anchors, whether or not this
        # page currently claims it.
        #
        # This cleared `existing` -- the chunks the page is known to have --
        # which is the same set in every ordinary case and not in one that
        # matters: a chunk arriving for the first time is not in `existing`,
        # so nothing guaranteed it was anchor-free. `ingest` then had to
        # `MERGE` its anchors rather than `CREATE` them, and a MERGE on a
        # relationship pays an existence check per row against edges the
        # delete had already removed. Measured on MDN's CSS index, 191 dirty
        # chunks: 19.1 seconds of a 22-second capture, 87% of the whole
        # thing, spent proving edges absent that had just been deleted.
        #
        # Clearing by the written set makes "these chunks have no anchors" a
        # postcondition of this method, which is what lets the write CREATE.
        # Chunks being DROPPED are handled below by `DETACH DELETE`, which
        # takes their edges with them.
        if keep_chunks:
            self._batch(
                "UNWIND $rows AS r MATCH (:Chunk {cid: r.cid})-[e:Anchors]->() "
                "DELETE e",
                [{"cid": cid} for cid in keep_chunks],
            )

        gone = ([cid for cid in existing if cid not in keep_chunks]
                if complete else [])
        if gone:
            self._batch(
                "UNWIND $rows AS r MATCH (c:Chunk {cid: r.cid}) DETACH DELETE c",
                [{"cid": cid} for cid in gone],
            )
            removed["chunks_removed"] = len(gone)

        # Addresses follow the same rule as chunks: a partial write says
        # nothing about the addresses it does not mention. Guarding only the
        # chunk half left this deleting every address a delta omitted, so a
        # page ended with one Address node and one anchor edge for eighty-six
        # chunks — and the REPL, which pairs lines to anchors by position,
        # then refused every chunk it read back.
        keep_addresses = {a.aid for a, _v, _h in addresses}
        stale = [] if not complete else [r[0] for r in self._rows(
            "MATCH (a:Address {url: $url}) RETURN a.aid", {"url": url})
            if r[0] not in keep_addresses]
        if stale:
            self._batch(
                "UNWIND $rows AS r MATCH (a:Address {aid: r.aid}) DETACH DELETE a",
                [{"aid": aid} for aid in stale],
            )
            removed["addresses_removed"] = len(stale)
        return removed

    def _link_containment(self, chunks: Sequence[MarkdownChunk]) -> int:
        """Edge from a chunk to each chunk rooted strictly below it.

        Only the *nearest* enclosing chunk gets the edge. Linking every
        ancestor would make PageRank count a deep chunk once per level of
        nesting, so a chunk's score would measure how deeply the page happened
        to be wrapped in divs rather than how much points at it.
        """
        # Longest matching proper prefix, found by walking the candidate's own
        # ancestor paths rather than by comparing every pair. Pairwise is
        # O(n^2) in chunks per page and a long article reaches a few thousand.
        roots: Dict[str, str] = {}
        for chunk in chunks:
            roots.setdefault(chunk.xpath, chunk.cid)

        pairs = []
        for chunk in chunks:
            parts = chunk.xpath.strip("/").split("/")
            for cut in range(len(parts) - 1, 0, -1):
                ancestor = "/" + "/".join(parts[:cut])
                parent = roots.get(ancestor)
                if parent is not None and parent != chunk.cid:
                    pairs.append({"a": parent, "b": chunk.cid})
                    break
        if pairs:
            self._batch(
                "UNWIND $rows AS r MATCH (a:Chunk {cid: r.a}), "
                "(b:Chunk {cid: r.b}) MERGE (a)-[:Contains]->(b)",
                pairs,
            )
        return len(pairs)

    def _link_hyperlinks(
        self,
        url: str,
        addresses: Sequence[Tuple[ContentAddress, str, str]],
        chunks: Sequence[MarkdownChunk],
    ) -> int:
        """Edge from a chunk to any page its links resolve to.

        Only targets already present as a Page get an edge. An edge to a page
        we have not scanned would be a node with no content, and PageRank
        would hand it mass that nothing could ever justify.
        """
        chunk_of: Dict[str, str] = {}
        for chunk in chunks:
            for line in chunk.lines:
                chunk_of[line.address.aid] = chunk.cid
                # The addresses the line folded into itself count too.
                #
                # A link inside a sentence is drawn as part of that sentence,
                # so its url address rides on `line.inline` and never appears
                # as a line's own address. Reading only `line.address` here
                # left those links with no chunk to hang an edge on, and the
                # link graph emptied out -- `test_link_edges_reach_the_graph`
                # caught it, which is what it was written for after a
                # url-matching defect once dropped three quarters of the
                # resolvable edges unnoticed.
                #
                # Same principle as `MarkdownChunk.covered`: the chunk that
                # drew the line accounts for every address folded into it.
                for merged in line.inline:
                    chunk_of[merged.aid] = chunk.cid

        # And the spellings the collapse dropped, which are still THERE.
        #
        # `line.absorbed` names the addresses a line speaks for: an
        # `aria-label` beside the text it duplicates, an `href` hidden
        # because the anchor says the words. The element is drawn in this
        # chunk -- only that spelling of it is not -- so a url among them
        # resolves its edge from here exactly as a merged one does. Reading
        # only `address` and `inline` left 37,452 addresses over the corpus
        # with no chunk at all, 8,167 of them urls, and an edge they could
        # not hang on.
        #
        # A SECOND pass, and `setdefault`, for both halves of the reason.
        # `_name_the_collapse` attaches the absorbed set to EVERY line at an
        # element rather than the first, so a plain assignment would leave
        # whichever line came last holding the address -- and which line that
        # is moves with the context window. Filling gaps only, in document
        # order, makes the answer the first chunk that drew the element, and
        # keeps a real line's own address ahead of any spelling it absorbed.
        for chunk in chunks:
            for line in chunk.lines:
                for dropped in line.absorbed:
                    chunk_of.setdefault(dropped.aid, chunk.cid)

        # Both sides in the *stored* spelling: the Page node's primary key is
        # the url the page was scanned with, and `canonical_url` does not
        # always return that. See `resolve_page`.
        stored = self.page_urls()
        exact = set(stored)
        by_canonical: Dict[str, str] = {}
        for candidate in stored:
            by_canonical.setdefault(canonical_url(candidate) or candidate,
                                    candidate)

        seen: set = set()
        pairs = []
        for address, value, _ in addresses:
            if not address.is_url:
                continue
            target = canonical_url(value, url)
            if not target:
                continue
            resolved = target if target in exact else by_canonical.get(target)
            if resolved is None or resolved == url:
                continue
            cid = chunk_of.get(address.aid)
            if cid is None or (cid, resolved) in seen:
                continue
            seen.add((cid, resolved))
            pairs.append({"cid": cid, "url": resolved})
        if pairs:
            self._batch(
                "UNWIND $rows AS r MATCH (c:Chunk {cid: r.cid}), "
                "(p:Page {url: r.url}) MERGE (c)-[:LinksTo]->(p)",
                pairs,
            )
        return len(pairs)

    def _batch(self, query: str, rows: Sequence[dict], size: int = 5000) -> None:
        """Run an UNWIND statement in slices.

        Sliced because the whole parameter list is materialised in the query
        plan: a single 100,000-row UNWIND holds every string twice, once in
        Python and once in the plan, and pages of markdown are not small.
        """
        for start in range(0, len(rows), size):
            self.conn.execute(query, {"rows": list(rows[start:start + size])})

    # -- reads -------------------------------------------------------------
    def _rows(self, query: str, params: Optional[dict] = None) -> List[list]:
        result = self.conn.execute(query, params or {})
        out = []
        while result.has_next():
            out.append(result.get_next())
        return out

    def resolve_page(self, url: str) -> str:
        """The stored spelling of a page, or "" if it was never scanned.

        A page is stored under the url it was *scanned* with, and link
        targets are canonicalised before use — so `https://books.toscrape.com`
        on disk never matched `https://books.toscrape.com/` coming out of
        `canonical_url`. On a twenty-page workspace, five stored urls were in
        that state and **three of the four** same-host link targets that
        pointed at a scanned page were being dropped. Every one of those is a
        missing `LinksTo` edge, which is a missing PageRank contribution, on
        the factor that exists precisely to say which pages matter.

        Matching here rather than canonicalising at ingest is deliberate: the
        url is part of a `ContentAddress` key, so rewriting it would change
        every `aid` in every existing workspace to fix a comparison.

        Exact first, so a workspace holding both spellings resolves each to
        itself rather than collapsing them onto whichever was seen first.
        """
        if not url:
            return ""
        stored = self.page_urls()
        if url in stored:
            return url
        wanted = canonical_url(url) or url
        for candidate in stored:
            if (canonical_url(candidate) or candidate) == wanted:
                return candidate
        return ""

    def page_urls(self) -> List[str]:
        return [r[0] for r in self._rows("MATCH (p:Page) RETURN p.url")]

    def chunk(self, cid: str) -> Optional[StoredChunk]:
        rows = self._rows(
            "MATCH (c:Chunk {cid: $cid}) RETURN c.cid, c.url, c.xpath, "
            "c.part, c.md, c.chars, c.line_count, c.row, c.dup_of, "
            "c.dup_n, c.group_of, c.group_n", {"cid": cid})
        if not rows:
            return None
        r = rows[0]
        return StoredChunk(*r[:8], r[8] or "", r[9] or 1,
                           r[10] or "", r[11] or 1)

    def set_groups(self, url: str, groups) -> int:
        """Record stage two's verdict for one page (`G-26`).

        Marked, exactly as `G-24` marks exact duplicates, and for the same
        reason one level up: the 256-token chunks and their vectors stay
        underneath and remain what a retrieval hit resolves to. What a group
        adds is a fact ABOUT them -- that these read as one thing -- and the
        merged rendering is ASSEMBLED from the members in document order
        rather than stored a second time, so a member rewritten by the next
        drain cannot leave a stale copy of itself inside a merged chunk.

        Every chunk on the page is cleared first. A group that no longer holds
        after a re-scan must stop being claimed, and leaving the old marks in
        place would let a page accumulate groups it no longer has -- the same
        defect `_reconcile` exists to prevent for anchors.
        """
        self.conn.execute(
            "MATCH (p:Page {url: $url})-[:HasChunk]->(c:Chunk) "
            "SET c.group_of = '', c.group_n = 1", {"url": url})
        rows = []
        for group in groups or []:
            members = list(getattr(group, "members", group))
            if len(members) < 2:
                continue
            lead = getattr(group, "lead", members[0])
            for cid in members:
                rows.append({"cid": cid, "lead": lead,
                             "n": len(members) if cid == lead else 1})
        if rows:
            self._batch(
                "UNWIND $rows AS r MATCH (c:Chunk {cid: r.cid}) "
                "SET c.group_of = r.lead, c.group_n = r.n", rows)
        return len(rows)

    def chunk_count(self, url: str = "") -> int:
        """How many chunks, without reading any of them.

        `len(store.chunks())` materialises every `StoredChunk` -- markdown
        included -- to produce one integer. On a 14,000-chunk store that is
        most of the database, and `place_into` was doing it on EVERY live
        capture to decide whether the fit had gone stale: measured at 9.0
        seconds to place eight chunks, essentially none of it the encoder.
        """
        if url:
            rows = self._rows(
                "MATCH (p:Page {url: $url})-[:HasChunk]->(c:Chunk) "
                "RETURN count(c)", {"url": url})
        else:
            rows = self._rows("MATCH (c:Chunk) RETURN count(c)")
        return int(rows[0][0]) if rows else 0

    def set_group_embedding(self, lead: str, vector) -> None:
        """The vector for what a merge group SAYS, stored on its lead.

        Separate from `embedding` and not a replacement for it. The lead is
        still a 256-token chunk with its own vector, and that is what
        retrieval resolves to (`G-27`); this is the vector of the assembled
        text, which is a different string and means something different. One
        column would have made the projector and the retriever disagree about
        what the lead is.
        """
        row = list(vector or [])[:EMBED_DIM]
        if len(row) < EMBED_DIM:
            row = row + [0.0] * (EMBED_DIM - len(row))
        self.conn.execute(
            "MATCH (c:Chunk {cid: $cid}) SET c.group_embedding = $v",
            {"cid": lead, "v": [float(x) for x in row]})

    def group_embedding(self, lead: str) -> Optional[List[float]]:
        rows = self._rows(
            "MATCH (c:Chunk {cid: $cid}) RETURN c.group_embedding",
            {"cid": lead})
        if not rows or rows[0][0] is None:
            return None
        out = list(rows[0][0])
        return out if any(out) else None

    def group_members(self, lead: str) -> List[StoredChunk]:
        """A merge group's chunks, in document order.

        Ordered by `(xpath, part)` rather than by insertion: a merged chunk
        that reads out of order is not the page, and the store is the only
        place that still knows what the page's order was.
        """
        rows = self._rows(
            "MATCH (c:Chunk {group_of: $lead}) RETURN c.cid, c.url, c.xpath, "
            "c.part, c.md, c.chars, c.line_count, c.row, c.dup_of, c.dup_n, "
            "c.group_of, c.group_n", {"lead": lead})
        out = [StoredChunk(*r[:8], r[8] or "", r[9] or 1,
                           r[10] or "", r[11] or 1) for r in rows]
        out.sort(key=lambda c: (c.xpath, c.part))
        return out

    def chunks(self, url: str = "") -> List[StoredChunk]:
        if url:
            rows = self._rows(
                "MATCH (p:Page {url: $url})-[:HasChunk]->(c:Chunk) "
                "RETURN c.cid, c.url, c.xpath, c.part, c.md, c.chars, "
                "c.line_count, c.row, c.dup_of, c.dup_n, "
                "c.group_of, c.group_n", {"url": url})
        else:
            rows = self._rows(
                "MATCH (c:Chunk) RETURN c.cid, c.url, c.xpath, c.part, "
                "c.md, c.chars, c.line_count, c.row, c.dup_of, c.dup_n, "
                "c.group_of, c.group_n")
        # `or` rather than a default: a store written before these columns
        # existed answers NULL for both, and a NULL count would make every
        # chunk in it look like a copy of nothing with no copies.
        return [StoredChunk(*r[:8], r[8] or "", r[9] or 1,
                            r[10] or "", r[11] or 1) for r in rows]

    def embedding(self, cid: str) -> Optional[List[float]]:
        rows = self._rows(
            "MATCH (c:Chunk {cid: $cid}) RETURN c.embedding", {"cid": cid})
        if not rows or rows[0][0] is None:
            # A chunk written before `flush_vectors` reached it has no vector
            # rather than a zero one. `list(None)` raises; the caller reads
            # None the same way it read all-zeros.
            return None
        return list(rows[0][0])

    def addresses_of(self, cid: str) -> List[Tuple[ContentAddress, str]]:
        """The addresses a chunk anchors, in line order."""
        rows = self._rows(
            "MATCH (c:Chunk {cid: $cid})-[r:Anchors]->(a:Address) "
            "RETURN r.ord, a.akey, a.value ORDER BY r.ord", {"cid": cid})
        return [(ContentAddress.parse(key), value) for _, key, value in rows]

    def chunk_for_address(self, aid: str) -> Optional[StoredChunk]:
        """The navigational requirement: address -> its chunk and embedding."""
        rows = self._rows(
            "MATCH (c:Chunk)-[:Anchors]->(a:Address {aid: $aid}) "
            "RETURN c.cid, c.url, c.xpath, c.part, c.md, c.chars, "
            "c.line_count, c.row", {"aid": aid})
        return StoredChunk(*rows[0]) if rows else None

    def address(self, aid: str) -> Optional[Tuple[ContentAddress, str]]:
        rows = self._rows(
            "MATCH (a:Address {aid: $aid}) RETURN a.akey, a.value",
            {"aid": aid})
        if not rows:
            return None
        return ContentAddress.parse(rows[0][0]), rows[0][1]

    def addresses_at(self, xpath: str, url: str = "") -> List[
            Tuple[ContentAddress, str]]:
        """Every address at one element.

        An element yields several — its text, its href, each of its
        `srcset` candidates — so this returns a list rather than pretending
        an xpath names one thing. It is the lookup a person can actually
        perform: an xpath is readable and an `aid` is a hash.
        """
        query = "MATCH (a:Address {xpath: $xpath}) "
        params = {"xpath": xpath}
        if url:
            query += "WHERE a.url = $url "
            params["url"] = url
        rows = self._rows(query + "RETURN a.akey, a.value ORDER BY a.akey",
                          params)
        return [(ContentAddress.parse(key), value) for key, value in rows]

    def edges(self) -> List[Tuple[str, str]]:
        """Chunk-to-chunk edges for PageRank, as (source cid, target cid).

        Containment edges verbatim; hyperlink edges routed to the target
        page's first chunk, so a link contributes one edge rather than
        fanning out over every chunk of the page it points at.
        """
        out = [(a, b) for a, b in self._rows(
            "MATCH (a:Chunk)-[:Contains]->(b:Chunk) RETURN a.cid, b.cid")]
        first: Dict[str, str] = {}
        for cid, url, xpath in self._rows(
                "MATCH (p:Page)-[:HasChunk]->(c:Chunk) "
                "RETURN c.cid, c.url, c.xpath ORDER BY c.xpath"):
            first.setdefault(url, cid)
        for cid, url in self._rows(
                "MATCH (c:Chunk)-[:LinksTo]->(p:Page) RETURN c.cid, p.url"):
            target = first.get(url)
            if target and target != cid:
                out.append((cid, target))
        return out

    def stats(self) -> Dict[str, int]:
        one = lambda q: int(self._rows(q)[0][0])  # noqa: E731
        return {
            "pages": one("MATCH (p:Page) RETURN count(p)"),
            "chunks": one("MATCH (c:Chunk) RETURN count(c)"),
            "addresses": one("MATCH (a:Address) RETURN count(a)"),
            "anchors": one("MATCH ()-[r:Anchors]->() RETURN count(r)"),
            "contains": one("MATCH ()-[r:Contains]->() RETURN count(r)"),
            "links": one("MATCH ()-[r:LinksTo]->() RETURN count(r)"),
        }

    # -- deletes -----------------------------------------------------------
    def purge_page(self, url: str) -> int:
        """Remove a page, its chunks and its addresses. Returns chunks removed."""
        cids = [r[0] for r in self._rows(
            "MATCH (p:Page {url: $url})-[:HasChunk]->(c:Chunk) RETURN c.cid",
            {"url": url})]
        self.conn.execute(
            "MATCH (a:Address {url: $url}) DETACH DELETE a", {"url": url})
        self.conn.execute(
            "MATCH (c:Chunk {url: $url}) DETACH DELETE c", {"url": url})
        self.conn.execute(
            "MATCH (p:Page {url: $url}) DETACH DELETE p", {"url": url})
        return len(cids)
