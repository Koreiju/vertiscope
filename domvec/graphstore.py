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

    @property
    def markdown(self) -> str:
        return self.md


class GraphStore:
    """Kuzu-backed unified store. Use as ``with GraphStore(path) as gs:``."""

    def __init__(self, path) -> None:
        import kuzu

        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # A second holder of this directory is a *conflict*, not a wait.
        # Kuzu takes an OS lock on the store, so two sweeps pointed at one
        # workspace would otherwise fail deep inside the first query with a
        # message that names neither the workspace nor the other holder.
        # Say which path, and say it at open time.
        try:
            self.db = kuzu.Database(str(self.path))
        except Exception as exc:  # noqa: BLE001
            if "lock" in str(exc).lower():
                raise RuntimeError(
                    f"workspace {self.path} is held by another process — "
                    "close it, or give this run its own store "
                    "(--build <dir> for the repl, --workspace <dir> for the "
                    "cli)"
                ) from exc
            raise
        self.conn = kuzu.Connection(self.db)
        for statement in _SCHEMA:
            self.conn.execute(statement)

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
        counts.update(self._reconcile(url, chunks, addresses,
                                      complete=complete))

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
        if address_rows:
            self._batch(
                "UNWIND $rows AS r MERGE (a:Address {aid: r.aid}) "
                "SET a.akey = r.akey, a.url = r.url, a.xpath = r.xp, "
                "a.tag = r.tag, a.accessor = r.acc, a.value = r.val, "
                "a.content_hash = r.ch",
                address_rows,
            )
            counts["addresses"] = len(address_rows)

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
        chunk_rows = []
        for chunk in chunks:
            row = {
                "cid": chunk.cid, "url": chunk.url, "xp": chunk.xpath,
                "part": chunk.part, "md": chunk.markdown, "chars": chunk.chars,
                "lines": len(chunk.lines), "row": int(rows.get(chunk.cid, -1)),
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
                "c.row = r.row" + (", c.embedding = r.emb" if has_vectors else ""),
                chunk_rows,
            )
            self._batch(
                "UNWIND $rows AS r MATCH (p:Page {url: r.url}), "
                "(c:Chunk {cid: r.cid}) MERGE (p)-[:HasChunk]->(c)",
                [{"url": url, "cid": c.cid} for c in chunks],
            )
            counts["chunks"] = len(chunk_rows)

        anchor_rows = [
            {"cid": chunk.cid, "aid": line.address.aid, "ord": ordinal}
            for chunk in chunks
            for ordinal, line in enumerate(chunk.lines)
        ]
        if anchor_rows:
            self._batch(
                "UNWIND $rows AS r MATCH (c:Chunk {cid: r.cid}), "
                "(a:Address {aid: r.aid}) MERGE (c)-[e:Anchors]->(a) "
                "SET e.ord = r.ord",
                anchor_rows,
            )
            counts["anchors"] = len(anchor_rows)

        counts["contains"] = self._link_containment(chunks)
        counts["links"] = self._link_hyperlinks(url, addresses, chunks)
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

        # Every chunk this page currently has loses its anchors: the ones
        # being rewritten are about to get fresh ones, and the ones being
        # dropped are going away entirely.
        if existing:
            self._batch(
                "UNWIND $rows AS r MATCH (:Chunk {cid: r.cid})-[e:Anchors]->() "
                "DELETE e",
                [{"cid": cid} for cid in existing],
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
            "c.part, c.md, c.chars, c.line_count, c.row", {"cid": cid})
        return StoredChunk(*rows[0]) if rows else None

    def chunks(self, url: str = "") -> List[StoredChunk]:
        if url:
            rows = self._rows(
                "MATCH (p:Page {url: $url})-[:HasChunk]->(c:Chunk) "
                "RETURN c.cid, c.url, c.xpath, c.part, c.md, c.chars, "
                "c.line_count, c.row", {"url": url})
        else:
            rows = self._rows(
                "MATCH (c:Chunk) RETURN c.cid, c.url, c.xpath, c.part, "
                "c.md, c.chars, c.line_count, c.row")
        return [StoredChunk(*r) for r in rows]

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
