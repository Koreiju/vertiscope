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
subsequent scan — it lives in :class:`vertiscope.vectors.FreqMatrix`, joined back
by the integer `row` stored here. See that module for the full argument.
"""

from __future__ import annotations

import time
import hashlib
import json
import os
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urljoin, urlsplit, urlunsplit

from .address import ContentAddress
from .markdown import MarkdownChunk
from .privacy import redact_url

__all__ = ["GraphStore", "StoredChunk", "canonical_url"]


def open_kuzu(path, pool_bytes: int):
    """A database and a connection on `path`, for a caller that needs the
    store as FILES (`obsidian/compact.py`'s EXPORT/IMPORT) -- so this module
    stays the only one that imports kuzu (`test_architecture`)."""
    import kuzu
    db = kuzu.Database(str(path), buffer_pool_size=pool_bytes)
    return db, kuzu.Connection(db)


class StorePoisoned(RuntimeError):
    """The connection must not be used again (see `GraphStore.poisoned`)."""


#: What kuzu says when its buffer pool cannot serve a statement. After it, the
#: NEXT statement on that connection segfaulted (2026-10-18: a COPY refused
#: with "Unable to allocate memory! The buffer pool is full and no memory
#: could be freed!", and the fallback statement that followed it crashed the
#: process -- every restart, ~50 times, until the store was rebuilt).
_POISON_MARKS = ("Buffer manager exception", "buffer pool is full")


def _close(result) -> None:
    """Release a kuzu QueryResult now, on this thread, under the caller's
    lock -- not whenever the garbage collector gets to it. Never raises."""
    try:
        if result is not None and hasattr(result, "close"):
            result.close()
    except Exception:                               # noqa: BLE001
        pass

EMBED_DIM = 768

#: How much memory kuzu may hold for its buffer pool, in bytes (`D-23`).
#:
#: **Bounded, because the default is a share of PHYSICAL memory** and this
#: process is not alone on the machine: Obsidian and its Electron guest, an
#: encoder, and UMAP fits that are themselves gigabytes. Left at the default
#: the sidecar segfaulted six times under a full confirmation suite, always
#: inside `Connection.execute` on a write, and always with the same shape --
#:
#:     15:01:55  sidecar 1935 MB
#:     15:02:05  sidecar 2199 MB
#:     15:02:16  sidecar 4767 MB
#:     15:02:26  SIDECAR GONE
#:
#: -- a step of two and a half gigabytes in one statement. The parameter
#: list was not the cause: the slice was already down to 200 rows, about
#: 600 KB of floats, and the step was unchanged.
#:
#: Overridable, because the right number depends on the machine and on what
#: else is running. 2 GiB is comfortable for a 4.9 GB store at this access
#: pattern and leaves the encoder and the fits their room.
_BUFFER_POOL = int(os.environ.get("VERTISCOPE_KUZU_BUFFER_BYTES",
                                  str(2 * 1024 * 1024 * 1024)))


def _pool_for(path) -> int:
    """The buffer pool for a store of this size (D-48, 2026-10-07).

    2 GiB was chosen for a 4.9 GB store; at 32 GB a CHECKPOINT failed with
    "the buffer pool is full and no memory could be freed", and the sidecar
    had died natively in Kuzu minutes earlier. Without an explicit
    `VERTISCOPE_KUZU_BUFFER_BYTES`: a sixth of the store, at least 2 GiB, at most
    a quarter of physical memory."""
    if os.environ.get("VERTISCOPE_KUZU_BUFFER_BYTES"):
        return _BUFFER_POOL
    # 4 GiB, not 2: on 2026-10-18 a CHECKPOINT folding a 72 MB WAL into a
    # 1.9 GB store segfaulted in a 2 GiB pool (and a 201 MB one twice); the
    # same folds in the compaction's 6 GiB pool did not. Still capped at a
    # quarter of physical memory below.
    floor = 4 * 1024 * 1024 * 1024
    try:
        size = os.path.getsize(str(path)) if os.path.exists(str(path)) else 0
    except OSError:
        size = 0
    try:
        import psutil
        cap = psutil.virtual_memory().total // 4
    except Exception:                               # noqa: BLE001
        cap = 4 * floor
    return int(max(floor, min(cap, size // 6)))

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
    # `G-12`: a fitted layout, kept so the pane can ask for one
    # instead of paying for it. A TABLE rather than columns on
    # `Chunk`: the payload belongs to a fit, not to a chunk, and two
    # fits of the same corpus (page and chunk level, euclidean and
    # S3) are four answers that would not fit in one column each.
    """CREATE NODE TABLE IF NOT EXISTS Layout(
        key STRING, payload STRING, fitted_at DOUBLE,
        n INT64, PRIMARY KEY(key))""",
    # `G-235`: the code property graph. A node is a code address
    # (`url|xpath`: module, class, function, statement); an edge is one of
    # AST / CFG / DFG / CALLS / INHERITS (`vertiscope/cpg.py`). Its own tables:
    # the trie's chunks are what a reader opens, these are how code relates.
    # A special FILE a page links to (PLUGIN_GOAL 186k): a .gguf, .csv, .json,
    # archive... detected at the link's trie address, drawn as its own node
    # with a panel for its kind. Keyed by the page and the destination.
    """CREATE NODE TABLE IF NOT EXISTS FileRef(
        key STRING, url STRING, cid STRING, xpath STRING, href STRING,
        name STRING, ext STRING, kind STRING, label STRING, PRIMARY KEY(key))""",
    """CREATE NODE TABLE IF NOT EXISTS CodeNode(
        key STRING, url STRING, xpath STRING, kind STRING, name STRING,
        qname STRING, line INT64, end_line INT64,
        calls_out STRING[], bases_out STRING[], PRIMARY KEY(key))""",
    "CREATE REL TABLE IF NOT EXISTS Cpg(FROM CodeNode TO CodeNode, kind STRING, var STRING, line INT64, label STRING)",
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
    # The chunk's page form as scanned: the hash of its saved snapshot blob
    # (`snapshots/`), so a panel renders it with the page gone (2026-10-10).
    "ALTER TABLE Chunk ADD snap STRING",
    # Where chunk view DRAWS the chunk and the fit point it was drawn from
    # (PLUGIN_GOAL 108, 2026-10-11: "we should be persisting these layouts to
    # the entities in our database"): [x, y, z, fit x, fit y, fit z].
    "ALTER TABLE Chunk ADD drawn DOUBLE[]",
    # The hash of the chunk's address list, line by line (2026-10-12): the
    # capture path skips a chunk whose markdown is unchanged, and a sibling
    # shift that leaves every line's TEXT the same left its anchors stale for
    # good -- arXiv's "View HTML" keyed to `a[3]`, which is the pdf link.
    "ALTER TABLE Chunk ADD asig STRING",
]


#: Schemes this store invents for things that are not fetched. `urljoin`
#: refuses to do relative resolution for a scheme it does not know -- it
#: hands back `Lattice.md` unchanged against a `vault://` base -- so these
#: are joined by hand. Without it a note that links to another note produced
#: an address that resolved to nothing, and the vault had no edges at all.
_LOCAL_SCHEMES = ("vault://", "code://")


def _join_local(base: str, rel: str) -> str:
    """Resolve `rel` against a `vault://` or `code://` base, POSIX-style."""
    import posixpath

    head, _, tail = base.partition("://")
    origin, _, path = tail.partition("/")
    if rel.startswith("/"):
        joined = rel
    else:
        joined = posixpath.join(posixpath.dirname("/" + path), rel)
    joined = posixpath.normpath(joined).lstrip("/")
    return "%s://%s/%s" % (head, origin, joined)


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
    local database has no business holding. `vertiscope.privacy` owns those
    rules; this function is where they meet the store, so that a url looked
    *up* is redacted exactly as the url that was stored. Userinfo goes with
    them — `https://user:pass@host/` is a password in a database with no
    password on it.
    """
    if base:
        low = base.lower()
        if any(low.startswith(scheme) for scheme in _LOCAL_SCHEMES) \
                and "://" not in url:
            url = _join_local(base, url)
        else:
            url = urljoin(base, url)
    url = redact_url(url)
    try:
        parts = urlsplit(url)
    except ValueError:
        return url
    if parts.scheme in ("code", "vault"):
        # **Identity, not rejection.** A local address has no query, no
        # fragment and no userinfo, so there is nothing to canonicalise --
        # but returning "" here meant `_link_pages` skipped every one of
        # them, and an IMPORT is a link the same way a hyperlink is
        # (`G-8`, `G-51`). Passing it through is what lets the existing
        # resolver, `edges()` and PageRank treat a dependency as an edge
        # without learning a second vocabulary.
        return urlunsplit((parts.scheme, parts.netloc, parts.path or "/",
                           "", ""))
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


def _index_spellings(url: str):
    """The other ways a directory index is written.

    Only the pair that is genuinely one resource: a url ending in `/` and the
    same url with `index.html` on it. Nothing else is assumed equivalent --
    `/a` and `/a/` are different resources on plenty of servers and guessing
    there would invent edges.
    """
    if not url:
        return ()
    if url.endswith("/"):
        return (url + "index.html",)
    for suffix in ("/index.html", "/index.htm", "/index.php"):
        if url.endswith(suffix):
            return (url[: -len(suffix) + 1],)
    return ()


#: Planted (2026-10-11): containment read from the STORED edges, which a page
#: streamed in drains holds only within each drain.
PLANT_STORED_CONTAINMENT = [False]
#: Planted (2026-10-11): parents by render ROOT xpath, not by trie node.
PLANT_ROOT_CONTAINMENT = [False]
#: Planted (PLUGIN_GOAL 110): every page's trie nodes read fresh, every call.
PLANT_NO_TNODE_MEMO = [False]

def anchor_sig(chunk) -> str:
    """A chunk's addresses, line by line, hashed: what says its anchors are
    the ones stored, when its markdown alone cannot."""
    import hashlib
    keys = [line.address.key() if line.address is not None else "" for line in chunk.lines]
    return hashlib.sha1(chr(10).join(keys).encode("utf-8")).hexdigest()[:16]


#: Planted (G-186): stale anchors deleted by (chunk, address), any line.
PLANT_STALE_BY_PAIR = [False]

#: Planted (2026-10-12): one anchor per ADDRESS, the last line drawing it --
#: a second line drawing the same address got no anchor.
PLANT_ONE_ANCHOR_PER_ADDRESS = [False]

#: How many times each chunk has been written in this process: what a cache
#: of facts read from a chunk's markdown checks before it trusts them.
CHUNK_WRITES: Dict[str, int] = {}


def _steps(xpath: str) -> List[str]:
    """An address's ELEMENT steps: the text node and attribute dropped."""
    x = xpath.split("/text()")[0].split("/@")[0]
    return [p for p in x.split("/") if p]


def _trie_nodes(addresses) -> Dict[str, Tuple[str, ...]]:
    """Each chunk's node in the patricia trie: the longest element prefix its
    addresses share (P-B7's `chunkNode`). `addresses` is (cid, xpath) rows."""
    nodes: Dict[str, Tuple[str, ...]] = {}
    for cid, xpath in addresses:
        st = tuple(_steps(xpath or ""))
        if not st:
            continue
        was = nodes.get(cid)
        if was is None:
            nodes[cid] = st
            continue
        i = 0
        while i < len(was) and i < len(st) and was[i] == st[i]:
            i += 1
        nodes[cid] = was[:i]
    return nodes


def _nearest_enclosing(nodes, order=None) -> List[Tuple[str, str]]:
    """(parent cid, child cid): each chunk under the chunk whose trie node is
    the LONGEST PROPER PREFIX of its own -- the patricia trie's parent,
    restricted to chunks. `nodes` maps cid -> node (a tuple of element steps)
    or, for the render-root form, rows of (cid, root xpath). Several chunks on
    one node (an element cut in parts): the first in `order` stands for it.
    """
    if not isinstance(nodes, dict):
        rows = list(nodes)
        order = [c for c, _ in rows]
        nodes = {c: tuple(p for p in x.strip("/").split("/") if p) for c, x in rows}
    order = order or list(nodes)
    owner: Dict[Tuple[str, ...], str] = {}
    for cid in order:
        if cid in nodes:
            owner.setdefault(nodes[cid], cid)
    pairs: List[Tuple[str, str]] = []
    for cid in order:
        node = nodes.get(cid)
        if node is None:
            continue
        for cut in range(len(node) - 1, 0, -1):
            parent = owner.get(node[:cut])
            if parent is not None and parent != cid:
                pairs.append((parent, cid))
                break
    return pairs


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
            self.db = kuzu.Database(str(self.path),
                                    read_only=self.read_only,
                                    buffer_pool_size=_pool_for(self.path))
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
        #: **One connection, many request threads (`D-23`).**
        #:
        #: A kuzu connection is not built to be used from several
        #: threads at once, and the sidecar is a `ThreadingHTTPServer`.
        #: `_WORK_LOCK` there serialises WRITES, which left every read
        #: free to run against a connection mid-write: the process
        #: segfaulted four times under a full confirmation suite --
        #: native, no Python traceback, and at a different check each
        #: time (G-71, G-16, G-12), which is what a data race looks
        #: like rather than a bug in any one of them.
        #:
        #: Re-entrant, because the read paths call each other.
        self._db_lock = threading.RLock()
        self.conn = kuzu.Connection(self.db)
        #: READS on a connection of their own (2026-10-10: "retrieval
        #: breakdown during a scan over a large page"). One shared connection
        #: made every search wait out the write in progress -- a 100.6 s
        #: capture of legislation.gov.uk, 77.9 s of it one class of statement.
        #: Kuzu serves a reader on another connection from a snapshot while
        #: one writer works (`scripts/store_read_concurrency.py`:
        #: reads p50 15.7 ms beside the writes vs p95 4.9 s on the shared
        #: connection). One thread at a time on it, as on the writer's.
        #:
        #: Two conditions make it safe, both measured on scratch: auto-
        #: checkpointing OFF (a commit's own checkpoint timed out waiting for
        #: the readers and FAILED the write, 1 of 14), and every checkpoint
        #: taken holding the readers' lock (30 writes, 7 checkpoints, 4,473
        #: reads, 0 errors). The sidecar checkpoints in quiet periods.
        self._read_lock = threading.Lock()
        self._read_conn = None
        #: Why this store's connection is no longer safe to use, or "". Set by
        #: a buffer-pool exception; every later statement refuses rather than
        #: segfault, and the sidecar's watchdog restarts the process.
        self.poisoned = ""
        self.read_stats = {"split": 0, "fallback": 0, "last_error": ""}
        if not self.read_only and os.environ.get("VERTISCOPE_SHARED_READS", "") != "1":
            try:
                self.conn.execute("CALL auto_checkpoint=false")
                self._read_conn = kuzu.Connection(self.db)
                self._read_conn.set_query_timeout(15000)
            except Exception:                       # noqa: BLE001
                self._read_conn = None
        # DDL is a write. A read-only open of an existing store has nothing to
        # create, and running it would turn a shared read into a lock error.
        if not self.read_only:
            for statement in _SCHEMA:
                self._execute(statement)
            for statement in _MIGRATIONS:
                try:
                    self._execute(statement)
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
            if self._read_conn is not None:
                self._read_conn.close()
        except Exception:
            pass
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
        removed: Optional[Sequence[str]] = None,
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
        # The page's trie nodes are re-read on its next layout (PLUGIN_GOAL 110),
        # and what was read from these chunks' markdown is stale.
        self._tnode_forget(url)
        for c in chunks or ():
            CHUNK_WRITES[c.cid] = CHUNK_WRITES.get(c.cid, 0) + 1
        rows = rows or {}
        embeddings = embeddings or {}
        # Everything from here to `_reconcile` -- the anchor `before` set and
        # the `held` address lookup -- ran before any timer started, so no
        # bucket saw it. Timed as `ms_prequery`.
        _t_pre = time.perf_counter()
        counts = {"addresses": 0, "chunks": 0, "anchors": 0,
                  "contains": 0, "links": 0,
                  "chunks_removed": 0, "addresses_removed": 0}

        # Reconcile before writing: drop what this page no longer has, so the
        # rest of this method only ever adds. Doing it first means a chunk's
        # stale anchors are gone before its new ones are merged, which is the
        # ordering the alignment depends on.
        # How much of this write is actually NEW.
        #
        # A delta rewrites whole chunks, but a chunk that changed in one line
        # keeps every other line's address and ordinal. If most anchors come
        # out identical to what is already stored, then deleting and
        # recreating them is work done to reach the state already held -- and
        # that delete plus recreate is 1.9 seconds of a 3.1 second capture.
        #
        # Counted BEFORE `_reconcile`, which is the thing that deletes them.
        # Placed after it the first time, where it faithfully reported zero
        # unchanged anchors on every page, because they had just been removed.
        stale_anchors = []
        fresh_anchors = set()
        if chunks:
            before = {
                (cid, aid, int(ordinal))
                for cid, aid, ordinal in self._rows(
                    "MATCH (c:Chunk)-[e:Anchors]->(a:Address) "
                    "WHERE list_contains($cids, c.cid) "
                    "RETURN c.cid, a.aid, e.ord",
                    {"cids": [c.cid for c in chunks]})}
            incoming = {
                (chunk.cid, line.address.aid, ordinal)
                for chunk in chunks
                for ordinal, line in enumerate(chunk.lines)
                if line.address is not None}
            counts["anchors_unchanged"] = len(before & incoming)
            counts["anchors_incoming"] = len(incoming)
            # Only what actually moved. Re-indexing an unchanged page found
            # 5,841 of 5,841 anchors identical to what was stored, so the
            # delete-and-recreate was reaching a state already held.
            # By the exact (chunk, address, LINE): an anchor at an old line
            # number goes, the same address at its new line stays. Keyed on
            # (chunk, address) it took both or left a line's old address
            # beside its new one -- 25 of 27 arXiv chunks held lines anchored
            # twice (2026-10-12, G-186).
            stale_anchors = [{"cid": cid, "aid": aid, "ord": int(o)}
                             for cid, aid, o in (before - incoming)]
            fresh_anchors = incoming - before
            counts["anchors_before"] = len(before)
            counts["anchors_stale"] = len(stale_anchors)
            counts["anchors_fresh"] = len(fresh_anchors)

        # The same question for the addresses, which are the larger half of
        # the cost: the MERGE and its seven SETs is ~1,300ms of a 1,477ms
        # anchor phase. An address whose content hash has not moved is a row
        # being written to the value it already has.
        if addresses:
            wanted = {a.aid: (ch, a.key()) for a, _v, ch in addresses}
            # **The guard reads `akey` as well as `content_hash`, and that is
            # not belt-and-braces.**
            #
            # The write this skips is one statement setting six columns:
            # `akey`, `url`, `xpath`, `tag`, `accessor`, `value`. Keying the
            # skip on `content_hash` alone made it a claim about the VALUE
            # standing in for a claim about the ROW, so a row that was
            # missing its key was judged current and left that way -- and
            # permanently, because re-scanning the page cannot move a content
            # hash that never changed. This is `CLAUDE.md` 5c applied to a
            # row: a cached verdict has to name what it is a function of.
            #
            # Measured in the live corpus before the fix: **118,180 of
            # 331,242 addresses** held a blank `akey`, all-or-nothing per
            # page -- 29 of 74 sampled pages at 100% and the rest at 0%. A
            # blank key will not parse, so `addresses_of` drops the row and
            # every line on that page is served with `key: ""`: no handle on
            # the page, no affordances, nothing for `resolve_address`. That
            # is D-26, and it was filed as a missing ANCHOR when the anchors
            # were there all along.
            #
            # `akey` is the one extra column checked because it is derived
            # from the other four -- `url|xpath|tag|accessor` is exactly what
            # `ContentAddress.key()` spells -- so comparing it covers them
            # without five more comparisons. `value` stays governed by the
            # content hash, which is what that hash is for.
            # Primary-key lookups, not a scan (2026-10-07): `list_contains`
            # read the whole Address table, ~500k rows in the working store,
            # for every capture -- the pre-query was 0.4-1.2 s. Measured on a
            # 300k-address scratch store, 800 aids: scan 631 ms, UNWIND over
            # the key 70 ms, identical rows. (The comment at
            # `_PLACEMENT_SCAN_AT` predicted the crossover moves with size.)
            held = {aid: (ch, akey) for aid, ch, akey in self._rows(
                "UNWIND $aids AS x MATCH (a:Address {aid: x}) "
                "RETURN a.aid, a.content_hash, a.akey",
                {"aids": list(wanted)})}
            counts["addresses_incoming"] = len(wanted)
            unchanged_addresses = {
                aid for aid, (ch, key) in wanted.items()
                if aid in held and held[aid][0] == ch and held[aid][1] == key}
            counts["addresses_unchanged"] = len(unchanged_addresses)
            # Reported so a corpus repairing itself is visible rather than
            # inferred from a timing that got slower.
            counts["addresses_rekeyed"] = sum(
                1 for aid, (ch, key) in wanted.items()
                if aid in held and held[aid][0] == ch and held[aid][1] != key)
        else:
            unchanged_addresses = set()

        counts["ms_prequery"] = round((time.perf_counter() - _t_pre) * 1000, 1)
        _t = time.perf_counter()
        counts.update(self._reconcile(url, chunks, addresses,
                                      complete=complete,
                                      stale_anchors=stale_anchors,
                                      removed=removed))
        counts["ms_reconcile"] = round((time.perf_counter() - _t) * 1000, 1)
        _t = time.perf_counter()

        self._execute(
            # Kept when the writer has no title -- see `workspace._KEEP_TITLE`.
            "MERGE (p:Page {url: $url}) SET "
            "p.title = CASE WHEN $title = '' THEN p.title ELSE $title END, "
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
        # EVERY line drawing an address, not the last one: keyed by address
        # alone, two lines drawing one address kept one anchor, and the other
        # line's slot became a gap (2026-10-12, arXiv's listing -- with the
        # positional read, every later line took its neighbour's address).
        anchor_of: Dict[str, List[Tuple[str, int]]] = {}
        for chunk in chunks:
            for ordinal, line in enumerate(chunk.lines):
                if line.address is not None:
                    hits = anchor_of.setdefault(line.address.aid, [])
                    if PLANT_ONE_ANCHOR_PER_ADDRESS[0]:
                        hits[:] = [(chunk.cid, ordinal)]
                    else:
                        hits.append((chunk.cid, ordinal))
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
                "asig": anchor_sig(chunk),
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
                "c.dup_of = r.dup, c.dup_n = r.dupn, c.asig = r.asig, "
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
        # Three questions per row, and each may be answered "nothing to do":
        # does this address's VALUE need writing, and does its anchor need
        # creating? An unchanged page answers no to both for every row, which
        # is why it used to cost as much as a new one.
        fused_rows, plain_rows, edge_rows = [], [], []
        for row in address_rows:
            hits = anchor_of.pop(row["aid"], None) or []
            needs_value = row["aid"] not in unchanged_addresses
            fresh = [h for h in hits if (h[0], row["aid"], h[1]) in fresh_anchors]
            if needs_value and fresh:
                fused_rows.append(dict(row, cid=fresh[0][0], ord=fresh[0][1]))
                fresh = fresh[1:]
            elif needs_value:
                plain_rows.append(row)
            # The address is current and only the edge is missing (or a second
            # line draws it), so there is nothing to MERGE -- just the two
            # lookups. Rare, and the expensive shape, which is why it is the
            # last case rather than the general one.
            for h in fresh:
                edge_rows.append({"cid": h[0], "aid": row["aid"], "ord": h[1]})

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

        if edge_rows:
            self._create_anchors(edge_rows)

        # Whatever is left in `anchor_of` is an anchor whose address this
        # write did not carry. Rare, and it still has to be created.
        anchor_rows = [
            {"cid": cid, "aid": aid, "ord": ordinal}
            for aid, hits in anchor_of.items()
            for cid, ordinal in hits
            if (cid, aid, ordinal) in fresh_anchors
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
            self._create_anchors(anchor_rows)
            counts["anchors"] = len(anchor_rows)
        counts["anchors"] = (counts.get("anchors", 0)
                             + len(fused_rows) + len(edge_rows))
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
        stale_anchors: Optional[Sequence[dict]] = None,
        removed: Optional[Sequence[str]] = None,
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
            "MATCH (c:Chunk {url: $url}) RETURN c.cid",
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
        # Only the anchors that actually moved, which the caller worked out
        # by diffing what is stored against what is arriving.
        #
        # This cleared every anchor on every chunk being written, so the write
        # then had to recreate all of them. On an unchanged page that is 5,841
        # deletes and 5,841 creates to arrive back where it started, and the
        # two together were most of a capture. `stale_anchors` is usually
        # empty; when it is not, it is small.
        if stale_anchors:
            # FORWARD from the chunk, the address matched by a filter the
            # planner cannot turn into a key lookup (`+ ''`), ONE STATEMENT A
            # ROW. Bound by key at both ends -- and in an UNWIND, which plans
            # the join from the address side -- the pattern matched NOTHING
            # on the working store for anchors its walk from the chunk finds:
            # the address-side adjacency lacks them. Every stale anchor
            # survived its delete: 56 anchors on a 12-line arXiv chunk, three
            # per line, and 741 "stale" deleted on each capture without one
            # going (2026-10-12, G-186). Stale anchors are few in an ordinary
            # write, so a statement each is cheap. Planted: the batched pair.
            if PLANT_STALE_BY_PAIR[0]:
                self._batch(
                    "UNWIND $rows AS r "
                    "MATCH (:Chunk {cid: r.cid})-[e:Anchors]->(:Address {aid: r.aid}) DELETE e",
                    list(stale_anchors))
            else:
                for r in stale_anchors:
                    self._execute(
                        "MATCH (:Chunk {cid: $c})-[e:Anchors]->(a:Address) "
                        "WHERE e.ord = $o AND a.aid + '' = $a DELETE e",
                        {"c": r["cid"], "a": r["aid"], "o": int(r["ord"])})

        # A partial write retires exactly what its diff NAMES (2026-10-04,
        # the central diff: `retired` -- in this session's previous render
        # and not in the current one). Absence from a delta still carries no
        # information; a name does.
        gone = ([cid for cid in existing if cid not in keep_chunks]
                if complete else
                [cid for cid in dict.fromkeys(removed or ()) if cid not in keep_chunks])
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

    #: How many rows go in one UNWIND when a row carries an EMBEDDING.
    #:
    #: **A slice size is a memory budget, and 5,000 is one only for light
    #: rows.** A chunk row with a `FLOAT[768]` vector is about two orders of
    #: magnitude heavier than one without, and the parameter list is
    #: materialised twice -- once in Python, once in the query plan. At
    #: 5,000 rows that is roughly 3.8 million floats per statement, twice
    #: over, and the process died:
    #:
    #:     14:56:34  sidecar 1843 MB
    #:     14:56:55  sidecar 1908 MB
    #:     14:57:06  sidecar 2640 MB
    #:     14:57:17  sidecar 4662 MB
    #:     14:57:27  SIDECAR GONE
    #:
    #: Five segfaults under a full confirmation suite, native and with no
    #: Python traceback, until `-X faulthandler` named the frame: kuzu's
    #: `execute`, under `_batch`, under `ingest`, under a live capture. Two
    #: earlier guesses -- concurrent UMAP, then a connection race -- were
    #: both wrong, and both locks stayed because they guard real hazards;
    #: neither was this one.
    _HEAVY_BATCH = 200

    #: What counts as heavy: a list-valued field this long or longer.
    _HEAVY_WIDTH = 64

    def _batch(self, query: str, rows: Sequence[dict], size: int = 5000) -> None:
        """Run an UNWIND statement in slices.

        Sliced because the whole parameter list is materialised in the query
        plan: a single 100,000-row UNWIND holds every string twice, once in
        Python and once in the plan, and pages of markdown are not small.

        The slice SHRINKS for rows carrying a vector, measured rather than
        declared per call site: a caller that adds embeddings to a payload
        should not have to remember to change a number somewhere else.
        """
        if rows:
            first = rows[0]
            if isinstance(first, dict) and any(
                    isinstance(v, (list, tuple)) and len(v) >= self._HEAVY_WIDTH
                    for v in first.values()):
                size = min(size, self._HEAVY_BATCH)
        for start in range(0, len(rows), size):
            self._execute(query, {"rows": list(rows[start:start + size])})

    # -- reads -------------------------------------------------------------
    def _execute(self, query: str, params: Optional[dict] = None):
        """Every statement this store runs, serialised (`D-23`).

        The one place the connection is touched, so that "is this safe from
        another thread" has a single answer instead of twelve.
        """
        with self._db_lock:
            self._guard()
            self._breadcrumb(query, params)
            try:
                result = self.conn.execute(query, params or {})
            except Exception as exc:                # noqa: BLE001
                self._poison_check(exc)
                raise
            # **Closed inside the lock, never returned.** The live QueryResult
            # used to be handed back to a caller that dropped it at once --
            # so its native destructor ran on that thread OUTSIDE the lock,
            # possibly while another thread was inside `execute` on the same
            # connection. Both faulthandler traces of the D-23 segfault show
            # exactly one Python thread in kuzu, which a destructor racing it
            # from C would explain. No caller used the result.
            _close(result)
            return None

    #: Planted: anchors created by the two-lookup statement, as before.
    _PLANT_ANCHOR_MATCH = [os.environ.get("VERTISCOPE_PLANT_ANCHOR_MATCH") == "1"]
    #: COPY for anchors is OPT-IN (`VERTISCOPE_ANCHOR_COPY=1`). It is 33x faster
    #: a batch (447 ms vs 14.9 s for 290 anchors on a copy of the compacted
    #: 4.3 GB store, reads alongside, 0 MB grown after a checkpoint --
    #: `scripts/store_anchor_copy_trial.py`). Tried as the default on
    #: 2026-10-18 and withdrawn within the hour: the live store took a full
    #: buffer pool (poisoned, supervised compaction) seven minutes in. Not
    #: shown to be COPY's -- the store had grown ~1.1 GB a checkpoint all
    #: afternoon with COPY off (embedding SETs, `store_growth.log`) -- but not
    #: shown not to be, so the default stays the form that ran for weeks.
    #: Earlier: a 2 GiB pool refused 41 rows on a 5.1 GB store and the refusal
    #: crashed the process. When on, COPY holds the readers' lock (its commit
    #: checkpoints, and unlocked 3 of 30 timed out waiting on reads).
    _ANCHOR_COPY = [os.environ.get("VERTISCOPE_ANCHOR_COPY") == "1"]
    #: Planted: COPY without the readers' lock (its checkpoint then waits on
    #: open reads: 3 of 30 timed out, one for 172 s).
    _PLANT_COPY_NO_READ_LOCK = [False]

    def _create_anchors(self, rows: Sequence[dict]) -> None:
        """Anchors (Chunk -> Address, `ord`) for rows whose two endpoints
        exist, by kuzu's BULK path: `COPY Anchors FROM` a frame.

        The statement form -- `MATCH (c:Chunk {cid}) MATCH (a:Address {aid})
        CREATE ...` -- cost 23 ms a row on the rebuilt store (1,000 edges in
        23.0 s; COPY of the same 1,000: 0.37 s), and archive.org's in-place
        rewrites send most anchors down it (the address is current, only its
        edge is new): 201 s of 321 s of store time in ten minutes of
        scrolling, captures queued 10-50 s behind it (2026-10-18, PLUGIN_GOAL
        155). Falls back to the statement if COPY refuses (an endpoint gone
        meanwhile), which skips a missing endpoint where COPY would fail.
        """
        if not rows:
            return
        if self._ANCHOR_COPY[0] and not self._PLANT_ANCHOR_MATCH[0] and len(rows) >= 8:
            try:
                import pandas as pd
                df = pd.DataFrame({"from": [r["cid"] for r in rows], "to": [r["aid"] for r in rows],
                                   "ord": [int(r["ord"]) for r in rows]})
                # COPY into a populated rel table checkpoints at its commit
                # whatever `auto_checkpoint` says, and a checkpoint waits for
                # the reader connection's transactions: 3 of 30 COPYs timed out
                # that way on a 4.3 GB store (one took 172 s before falling
                # back). Held under the READERS' lock too, as every checkpoint
                # here is; reads wait the half second it takes.
                rl = self._read_lock if (self._read_conn is not None and not self._PLANT_COPY_NO_READ_LOCK[0]) else None
                if rl is not None:
                    rl.acquire()
                try:
                    with self._db_lock:
                        self._breadcrumb("COPY Anchors FROM df", {"rows": rows[:1]})
                        _close(self.conn.execute("COPY Anchors FROM df"))
                finally:
                    if rl is not None:
                        rl.release()
                return
            except Exception as exc:                # noqa: BLE001
                self._poison_check(exc)
                self.copy_errors.append("%s: %s" % (type(exc).__name__, str(exc)[:200]))
                del self.copy_errors[:-20]
                if self._DUMP_ROWS:
                    try:
                        with open(self._DUMP_ROWS, "a", encoding="utf-8") as fh:
                            fh.write(json.dumps({"at": time.time(), "copy_error": self.copy_errors[-1]}) + chr(10))
                    except OSError:
                        pass
                self._guard()                       # never the fallback after a refused pool
        self._batch(
            "UNWIND $rows AS r MATCH (c:Chunk {cid: r.cid}) "
            "MATCH (a:Address {aid: r.aid}) "
            "CREATE (c)-[:Anchors {ord: r.ord}]->(a)",
            rows,
        )

    _WRITES = re.compile(r"\b(CREATE|MERGE|SET|DELETE|DETACH|DROP|ALTER|COPY|CALL|CHECKPOINT|INSTALL|LOAD|REMOVE)\b", re.I)

    def _rows(self, query: str, params: Optional[dict] = None) -> List[list]:
        self._guard()                               # both connections share the pool
        rc = self._read_conn
        if rc is not None and not self._WRITES.search(query):
            try:
                with self._read_lock:
                    result = rc.execute(query, params or {})
                    out = []
                    while result.has_next():
                        out.append(result.get_next())
                    _close(result)
                self.read_stats["split"] += 1
                return out
            except Exception as exc:                # noqa: BLE001
                # A timeout or anything else: the shared path still answers --
                # unless the buffer pool refused, which is the DATABASE's, not
                # this connection's, and poisons both.
                self._poison_check(exc)
                self.read_stats["fallback"] += 1
                self.read_stats["last_error"] = str(exc)[:160]
        # The result is drained INSIDE the lock. A kuzu QueryResult is a
        # cursor over the connection, so iterating it after releasing lets
        # another thread execute against the connection being read -- which
        # is the same race by a longer route. And closed inside it, for the
        # destructor reason given in `_execute`.
        with self._db_lock:
            self._guard()
            self._breadcrumb(query, params)
            try:
                result = self.conn.execute(query, params or {})
            except Exception as exc:                # noqa: BLE001
                self._poison_check(exc)
                raise
            out = []
            while result.has_next():
                out.append(result.get_next())
            _close(result)
        return out

    def upsert_cpg(self, g: Dict, scope: str = "") -> Dict[str, int]:
        """One file's code property graph, replacing what the store held for
        it (`G-235`; the per-file `incremental_update` the reader named).

        Calls and bases into OTHER files resolve by qualified name both ways:
        this file's outgoing ones against the nodes the store holds, and the
        store's pending ones (`calls_out` / `bases_out` of other files) that
        name a symbol this file defines -- the edges its DETACH DELETE just
        removed come back, and a file indexed after its callers still gets
        their edges. Statement form throughout (no COPY: see `_ANCHOR_COPY`).
        """
        url = g["url"]
        out = {"nodes": 0, "edges": 0, "cross_out": 0, "cross_in": 0}
        # A web page holds many code blocks and a capture carries some of
        # them: a block replaces ITS nodes (`scope`, a key prefix), never the
        # page's others.
        if scope:
            self._execute("MATCH (n:CodeNode) WHERE n.url = $u AND n.key STARTS WITH $k DETACH DELETE n",
                          {"u": url, "k": scope})
        else:
            self._execute("MATCH (n:CodeNode {url: $u}) DETACH DELETE n", {"u": url})
        if g["nodes"]:
            self._batch("UNWIND $rows AS r CREATE (:CodeNode {key: r.key, url: r.url, xpath: r.xpath, kind: r.kind, "
                        "name: r.name, qname: r.qname, line: r.line, end_line: r.end_line, "
                        "calls_out: r.calls_out, bases_out: r.bases_out})", g["nodes"], size=500)
            out["nodes"] = len(g["nodes"])
        if g["edges"]:
            self._batch("UNWIND $rows AS r MATCH (a:CodeNode {key: r.src}), (b:CodeNode {key: r.dst}) "
                        "CREATE (a)-[:Cpg {kind: r.kind, var: r.var, line: r.line, label: r.label}]->(b)",
                        g["edges"], size=500)
            out["edges"] = len(g["edges"])
        outgoing = [{"src": n["key"], "q": q, "kind": kind}
                    for n in g["nodes"] for kind, field in (("CALLS", "calls_out"), ("INHERITS", "bases_out"))
                    for q in n[field]]
        if outgoing:
            got = self._rows("UNWIND $rows AS r MATCH (a:CodeNode {key: r.src}), (b:CodeNode {qname: r.q}) "
                             "WHERE b.url <> $u AND b.kind IN ['function', 'class'] "
                             "CREATE (a)-[:Cpg {kind: r.kind, var: '', line: 0, label: ''}]->(b) RETURN count(*)",
                             {"rows": outgoing, "u": url})
            out["cross_out"] = int(got[0][0]) if got else 0
        defined = [n["qname"] for n in g["nodes"] if n["kind"] in ("function", "class") and n["qname"]]
        if defined:
            got_c = self._rows("UNWIND $qs AS q MATCH (a:CodeNode), (b:CodeNode {qname: q}) "
                               "WHERE a.url <> $u AND b.url = $u AND list_contains(a.calls_out, q) "
                               "CREATE (a)-[:Cpg {kind: 'CALLS', var: '', line: 0, label: ''}]->(b) RETURN count(*)",
                               {"qs": defined, "u": url})
            got_b = self._rows("UNWIND $qs AS q MATCH (a:CodeNode), (b:CodeNode {qname: q}) "
                               "WHERE a.url <> $u AND b.url = $u AND list_contains(a.bases_out, q) "
                               "CREATE (a)-[:Cpg {kind: 'INHERITS', var: '', line: 0, label: ''}]->(b) RETURN count(*)",
                               {"qs": defined, "u": url})
            out["cross_in"] = (int(got_c[0][0]) if got_c else 0) + (int(got_b[0][0]) if got_b else 0)
        return out

    def upsert_files(self, url: str, rows: List[Dict], cids: Sequence[str] = ()) -> int:
        """The special files a page's chunks link to, replacing what the
        chunks `cids` held before (scoped: a delta capture carries some
        chunks, and the page's others keep their files)."""
        cids = sorted(set(cids) | {r["cid"] for r in rows})
        if cids:
            self._execute("MATCH (f:FileRef) WHERE f.url = $u AND list_contains($cids, f.cid) DELETE f",
                          {"u": url, "cids": cids})
        if rows:
            self._batch("UNWIND $rows AS r MERGE (f:FileRef {key: r.key}) SET f.url = r.url, f.cid = r.cid, "
                        "f.xpath = r.xpath, f.href = r.href, f.name = r.name, f.ext = r.ext, f.kind = r.kind, "
                        "f.label = r.label", rows)
        return len(rows)

    def files_of(self, url: str) -> List[Dict]:
        cols = ("key", "url", "cid", "xpath", "href", "name", "ext", "kind", "label")
        return [dict(zip(cols, r)) for r in self._rows(
            "MATCH (f:FileRef {url: $u}) RETURN f.key, f.url, f.cid, f.xpath, f.href, f.name, f.ext, f.kind, f.label "
            "ORDER BY f.kind, f.name", {"u": url})]

    def cpg_of(self, url: str) -> Dict:
        """One file's CPG as stored: its nodes, its edges, and the edges that
        cross to or from other files (with those ends' addresses)."""
        nodes = [dict(zip(("key", "xpath", "kind", "name", "qname", "line", "end_line", "calls_out", "bases_out"), r))
                 for r in self._rows(
            "MATCH (n:CodeNode {url: $u}) RETURN n.key, n.xpath, n.kind, n.name, n.qname, n.line, n.end_line, "
            "n.calls_out, n.bases_out", {"u": url})]
        edges = [dict(zip(("src", "dst", "kind", "var", "line", "label", "src_url", "dst_url"), r)) for r in self._rows(
            "MATCH (a:CodeNode)-[e:Cpg]->(b:CodeNode) WHERE a.url = $u OR b.url = $u "
            "RETURN a.key, b.key, e.kind, e.var, e.line, e.label, a.url, b.url", {"u": url})]
        return {"url": url, "nodes": nodes, "edges": edges}

    def _poison_check(self, exc: BaseException) -> None:
        text = str(exc)
        if any(m in text for m in _POISON_MARKS) and not self._PLANT_NO_POISON[0]:
            self.poisoned = "%s: %s" % (type(exc).__name__, text[:200])

    def _guard(self) -> None:
        if self.poisoned:
            raise StorePoisoned(self.poisoned)

    #: Planted: a buffer-pool refusal leaves the connection in use, as before.
    _PLANT_NO_POISON = [os.environ.get("VERTISCOPE_PLANT_NO_POISON") == "1"]

    #: A fixed-size record of the statement about to run, rewritten in place
    #: before every statement: when kuzu segfaults (D-23) no Python frame can
    #: say WHICH statement did it, and this file can. Microseconds per write.
    _CRUMB_SIZE = 512

    def _breadcrumb(self, query: str, params: Optional[dict]) -> None:
        fd = getattr(self, "_crumb_fd", None)
        if fd is None:
            return
        try:
            rows = (params or {}).get("rows")
            head = "%.3f n=%s %s" % (time.time(),
                                     len(rows) if isinstance(rows, list) else "-",
                                     " ".join(query.split())[:400])
            data = head.encode("utf-8", "replace")[:self._CRUMB_SIZE]
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, data.ljust(self._CRUMB_SIZE, b" "))
            # Diagnosis only (`VERTISCOPE_DUMP_ROWS=1`): EVERY statement and its
            # rows, in order, so a native crash can be replayed offline exactly
            # (2026-10-18: the anchor crash could not be reproduced from the
            # 512-byte head alone).
            if self._DUMP_ROWS:
                with open(self._DUMP_ROWS, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps({"at": time.time(), "query": query, "params": params or {}}, default=str) + chr(10))
                    fh.flush(); os.fsync(fh.fileno())
        except Exception:                           # noqa: BLE001
            pass

    _DUMP_ROWS = ""
    #: Why each refused COPY refused (the fallback statement runs after it).
    copy_errors: List[str] = []

    def enable_breadcrumb(self, path) -> None:
        """Record each statement's head to `path` before it runs (`D-23`)."""
        try:
            self._crumb_fd = os.open(str(path), os.O_RDWR | os.O_CREAT, 0o600)
        except OSError:
            self._crumb_fd = None
        if os.environ.get("VERTISCOPE_DUMP_ROWS") == "1":
            self._DUMP_ROWS = str(Path(str(path)).with_name("statements.jsonl"))

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

    def chunk_sigs(self, cids) -> Dict[str, Tuple[str, str, int]]:
        """Each stored chunk's (markdown, address signature, anchor count) by
        cid: a write may skip only when the first two are unchanged AND the
        chunk holds exactly one anchor per addressed line -- a chunk carrying
        stale anchors is rewritten, which is what deletes them."""
        cids = [c for c in dict.fromkeys(cids) if c]
        if not cids:
            return {}
        return {cid: (md or "", sig or "", int(n or 0)) for cid, md, sig, n in self._rows(
            "UNWIND $cids AS x MATCH (c:Chunk {cid: x}) "
            "OPTIONAL MATCH (c)-[e:Anchors]->(:Address) "
            "RETURN c.cid, c.md, c.asig, count(e)", {"cids": cids})}

    def chunk_mds(self, cids) -> Dict[str, str]:
        """Each stored chunk's markdown by cid, by primary-key lookups (the
        shape G-121 measured at 70 ms for 800 keys, against 631 for a scan)."""
        cids = [c for c in dict.fromkeys(cids) if c]
        if not cids:
            return {}
        return {cid: (md or "") for cid, md in self._rows(
            "UNWIND $cids AS x MATCH (c:Chunk {cid: x}) RETURN c.cid, c.md", {"cids": cids})}

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

    #: Below this many cids, one lookup per cid is cheaper than one scan.
    #:
    #: Measured on a 14,488-chunk store, placement's read, median of 5:
    #:
    #:        n    per-cid    UNWIND   list_contains
    #:        1      1.1 ms   55.8 ms     16.7 ms
    #:        4      4.3      56.8        19.8
    #:       16     19.2      54.2        17.3
    #:       64     73.9      58.6        20.6
    #:      151    337.1      60.2        25.3
    #:
    #: Per-cid grows linearly at ~1.1-2.2 ms a cid; the scan is nearly flat
    #: but pays for the whole table; `UNWIND ... MATCH {cid: id}` is never
    #: best -- a flat ~55 ms that looks like plan cost, not lookup cost. The
    #: crossover is near 16. **The scan's cost grows with the CORPUS**, so
    #: this threshold is a fact about a store of this size and should be
    #: re-measured when the store is an order of magnitude larger.
    _PLACEMENT_SCAN_AT = 12

    def chunks_for_placement(self, cids: Sequence[str]):
        """Each cid's chunk and the vector placement should use, in `cids` order.

        Returns ``[(cid, StoredChunk or None, vector or None)]``. The vector is
        the group embedding for a group lead with more than one member, else
        the chunk's own -- the same substitution `place_into` made with two
        or three separate queries per cid, which on a 151-chunk page was 337
        ms of placement's time spent on round trips.
        """
        cids = [c for c in dict.fromkeys(cids) if c]
        if not cids:
            return []
        if len(cids) < self._PLACEMENT_SCAN_AT:
            out = []
            for cid in cids:
                chunk = self.chunk(cid)
                vector = (self.group_embedding(cid)
                          if chunk is not None and chunk.group_n > 1 else None)
                if not vector and chunk is not None:
                    vector = self.embedding(cid)
                out.append((cid, chunk, vector))
            return out
        rows = self._rows(
            "MATCH (c:Chunk) WHERE list_contains($cids, c.cid) RETURN "
            "c.cid, c.url, c.xpath, c.part, c.md, c.chars, c.line_count, "
            "c.row, c.dup_of, c.dup_n, c.group_of, c.group_n, "
            "c.embedding, c.group_embedding", {"cids": cids})
        found = {}
        for r in rows:
            chunk = StoredChunk(*r[:8], r[8] or "", r[9] or 1,
                                r[10] or "", r[11] or 1)
            group = list(r[13]) if r[13] is not None else None
            # `group_embedding()` treats an all-zero vector as absent; so
            # does this, or a lead with an unset group vector would be placed
            # at the origin instead of by its own embedding.
            if group is not None and not any(group):
                group = None
            own = list(r[12]) if r[12] is not None else None
            vector = group if (chunk.group_n > 1 and group) else own
            found[r[0]] = (chunk, vector)
        return [(cid,) + found.get(cid, (None, None)) for cid in cids]

    def chunks_many(self, cids: Sequence[str]) -> Dict[str, StoredChunk]:
        """Several chunks in one read: a lookup per cid below
        `_PLACEMENT_SCAN_AT`, one scan above (measured flat at ~20 ms where
        per-cid grows ~1-2 ms a cid warm, ~100-200 ms cold). Search read its
        hits one query each, twice -- 50-117 reads for a 50-hit page, 9-50 s
        against a cold buffer pool (2026-10-17)."""
        cids = [c for c in dict.fromkeys(cids) if c]
        if not cids:
            return {}
        # Keyed lookups below the scan threshold, the scan above: tried at
        # 200 keyed lookups, they cost ~250 ms each on the reader's busy 63 GB
        # store (13-140 s a search, 2026-10-17) against 0.9-3.3 s for the scan.
        if len(cids) < self._PLACEMENT_SCAN_AT:
            return {c: ch for c in cids for ch in [self.chunk(c)] if ch is not None}
        rows = self._rows(
            "MATCH (c:Chunk) WHERE list_contains($cids, c.cid) RETURN c.cid, c.url, c.xpath, "
            "c.part, c.md, c.chars, c.line_count, c.row, c.dup_of, "
            "c.dup_n, c.group_of, c.group_n", {"cids": cids})
        return {r[0]: StoredChunk(*r[:8], r[8] or "", r[9] or 1, r[10] or "", r[11] or 1) for r in rows}

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
        self._execute(
            "MATCH (c:Chunk {url: $url}) "
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

    def embeddings_for(self, url: str) -> Dict[str, List[float]]:
        """Every vector on one page, in one query.

        Keyed on `c.url`, like every other per-page read here. Going
        through `(:Page {url})-[:HasChunk]->` missed 3,033 of 14,169
        edges, because a Page node does not always carry the same url
        its chunks do -- percent-encoding on the wikipedia pages, a
        trailing slash on five others. See `chunks`.

        `aggregate` read them one at a time -- `store.embedding(cid)` per
        chunk -- which is a query per chunk and the reason stage two looked
        expensive. Measured on `build/corpus123`: a 835-chunk page spent
        330ms reading and 78ms clustering, so the clustering was never the
        cost and an incremental DBSCAN would have been machinery bought to
        speed up the wrong half.

        Only chunks that HAVE a vector come back. A missing one is normal for
        a chunk seconds old, since embedding is asynchronous by design, and
        the caller already treats absence as "not yet".
        """
        rows = self._rows(
            "MATCH (c:Chunk {url: $url}) "
            "RETURN c.cid, c.embedding", {"url": url})
        out: Dict[str, List[float]] = {}
        for cid, vector in rows:
            if vector is None:
                continue
            values = list(vector)
            if any(values):
                out[cid] = values
        return out

    def checkpoint(self) -> float:
        """Fold the write-ahead log into the database now; returns ms.

        Kuzu checkpoints on its own only when the WAL passes a size threshold.
        A native crash then loses everything since the last one: on
        2026-10-07 a ~17 MB WAL was set aside unreplayable (D-48). Called when
        a page SETTLES, so a crash costs at most the page in progress.
        """
        t0 = time.perf_counter()
        # No read may be open across it (see `_read_conn`).
        with self._read_lock:
            self._execute("CHECKPOINT")
        return round((time.perf_counter() - t0) * 1000, 1)

    def _tnode_memo(self) -> Dict[str, Dict[str, Tuple[str, ...]]]:
        memo = getattr(self, "_tnodes", None)
        if memo is None:
            memo = self._tnodes = {}
            self.tnode_stats = {"computed": 0, "reused": 0, "dropped": 0}
        return memo

    def _tnode_forget(self, url: str) -> None:
        memo = self._tnode_memo()
        memo.pop(("rows", url), None)
        if memo.pop(url, None) is not None:
            self.tnode_stats["dropped"] += 1

    def contains_within(self, url: str, among=None):
        """The containment edges among one page's chunks, as (cid, cid).

        The patricia structure, restricted to a page (`G-6`). `edges()`
        answers the same question for the whole corpus and routes hyperlinks
        as well, which is what PageRank wants and not what a pane unfolding
        one page wants.

        **Read from the page's chunk roots, not the stored edges** (2026-10-11:
        "it looks like a shortcut where there's just all the recursive chunks
        linked to their root URL node"). `_link_containment` links a chunk to
        its nearest enclosing chunk only among the chunks of ONE write, and a
        streamed page is written a drain at a time: RFC 9110's 1,172 chunks
        held 0 Contains edges between them although a chunk is rooted at
        `/html/body`, above every one, so the pane hung all 1,172 off the url
        node. Here each chunk's parent is the chunk rooted at the longest
        proper prefix of its root xpath, over the page's chunks as they stand
        -- whatever order the drains brought them in. One read, nothing
        written. Planted (`PLANT_STORED_CONTAINMENT`): the stored edges.
        """
        if PLANT_STORED_CONTAINMENT[0]:
            return [(a, b) for a, b in self._rows(
                "MATCH (a:Chunk {url: $url})-[:Contains]->(b:Chunk {url: $url}) "
                "RETURN a.cid, b.cid", {"url": url}) if a and b]
        # In PART order, so the first part of an element cut in several stands
        # for its root -- as on the write path, which sees them in document
        # order. By cid (random) children hung from an arbitrary part: Dril's
        # agreement with the trie fell 261 -> 134 of 263 (2026-10-11).
        # Kept with the page's trie nodes, and dropped with them when the page
        # is written: one query per page per layout was 3.2 s over 330 pages.
        rmemo = self._tnode_memo()
        rkey = ("rows", url)
        rows = None if PLANT_NO_TNODE_MEMO[0] else rmemo.get(rkey)
        if rows is None:
            rows = [(c, x) for c, x in self._rows(
                "MATCH (c:Chunk {url: $url}) RETURN c.cid, c.xpath ORDER BY c.part, c.cid",
                {"url": url}) if c and x]
            rmemo[rkey] = rows
        rows = list(rows)
        # Among the chunks actually DRAWN, when the caller says which: a node
        # owned by a chunk that is never placed (a duplicate copy) otherwise
        # took the edge, the edge was dropped as undrawn, and the child fell to
        # the url node -- 22 of Monarch_butterfly's 655 (2026-10-11).
        keep = set(among) if among is not None else None
        if keep is not None:
            rows = [(c, x) for c, x in rows if c in keep]
        if PLANT_ROOT_CONTAINMENT[0]:
            return _nearest_enclosing(rows)
        # By TRIE NODE -- the common prefix of a chunk's own addresses, the node
        # P-B7 outlines -- not by render root: a long element cut in parts has
        # one root and many nodes (RFC 9110's 269 parts of `/html/body`), and by
        # root they hung from the url node or from each other.
        # Kept per page until the page is next written (PLUGIN_GOAL 110): read
        # fresh for every page on every chunk-view layout, this was every
        # anchor in the store -- 42-66 s a layout over 294 pages, holding the
        # read lock every capture also needs (a drain waited 21 s in
        # transport behind one). A page's nodes change only when its anchors
        # are written, and `ingest`/`purge_page` drop its entry when they are.
        memo = self._tnode_memo()
        got = None if PLANT_NO_TNODE_MEMO[0] else memo.get(url)
        if got is None:
            got = _trie_nodes(self._rows(
                "MATCH (c:Chunk {url: $url})-[:Anchors]->(a:Address) RETURN c.cid, a.xpath",
                {"url": url}))
            memo[url] = got
            self.tnode_stats["computed"] += 1
        else:
            self.tnode_stats["reused"] += 1
        nodes = dict(got)
        if keep is not None:
            nodes = {c: n for c, n in nodes.items() if c in keep}
        # A chunk with no anchored address keeps its root as its node -- and so
        # does one whose addresses reach ABOVE its root: a line can carry an
        # address folded in from elsewhere, and the common prefix then climbed
        # to `html`, where no chunk lives (Monarch_butterfly: 22 chunks under
        # `section[N]` drawn off the url node). A chunk renders its root's
        # subtree, so its node is never shallower than that root.
        for c, x in rows:
            root = tuple(p for p in x.strip("/").split("/") if p)
            got = nodes.get(c)
            if got is None or len(got) < len(root):
                nodes[c] = root
        return _nearest_enclosing(nodes, [c for c, _ in rows])

    def page_vectors(self):
        """Everything the page-level fit needs, in ONE query.

        Assembling it from `chunks()` plus `embeddings_for()` per page plus
        `group_embedding()` per lead took 15.5 seconds over 98 pages -- most
        of it loading 14,000 chunks' MARKDOWN, which the fit never looks at,
        and a lookup per merge-group lead on top. This asks for the columns
        that matter and nothing else.

        Returns ``(by_page, counts)``: url -> the vectors that speak for that
        page, and url -> how many chunks it holds. A merge group contributes
        its group vector once and its members contribute nothing, because the
        members are inside what the group says (`G-27`).
        """
        by_page: Dict[str, List[List[float]]] = {}
        counts: Dict[str, int] = {}
        rows = self._rows(
            "MATCH (p:Page)-[:HasChunk]->(c:Chunk) "
            "RETURN c.url, c.cid, c.dup_of, c.group_of, c.group_n, "
            "c.embedding, c.group_embedding")
        for url, cid, dup, group_of, group_n, emb, gemb in rows:
            if not url:
                continue
            counts[url] = counts.get(url, 0) + 1
            if dup:
                continue                    # `G-24` resolved it already
            if group_of and group_of != cid:
                continue                    # a member speaks through its lead
            vector = None
            if group_n and int(group_n) > 1 and gemb is not None:
                values = list(gemb)
                if any(values):
                    vector = values
            if vector is None and emb is not None:
                values = list(emb)
                if any(values):
                    vector = values
            if vector is not None:
                by_page.setdefault(url, []).append(vector)
        return by_page, counts

    def lead_vectors(self):
        """Every DRAWABLE chunk with the vector that speaks for it, in one query.

        ``[(cid, url, vector)]``: the rows the chunk projector is fitted on
        and places. The same substitution as `page_vectors` -- a duplicate is
        resolved to its original, a merge-group member speaks through its
        lead, a lead with members through its group vector -- but keyed by
        chunk rather than folded into a page mean, because the projector's
        points ARE chunks.
        """
        out = []
        rows = self._rows(
            "MATCH (p:Page)-[:HasChunk]->(c:Chunk) "
            "RETURN c.url, c.cid, c.dup_of, c.group_of, c.group_n, "
            "c.embedding, c.group_embedding")
        for url, cid, dup, group_of, group_n, emb, gemb in rows:
            if not url or dup:
                continue
            if group_of and group_of != cid:
                continue
            vector = None
            if group_n and int(group_n) > 1 and gemb is not None:
                values = list(gemb)
                if any(values):
                    vector = values
            if vector is None and emb is not None:
                values = list(emb)
                if any(values):
                    vector = values
            if vector is not None:
                out.append((cid, url, vector))
        return out

    def page_titles(self) -> Dict[str, str]:
        """Every page's title, in one query."""
        out = {}
        for url, title in self._rows("MATCH (p:Page) RETURN p.url, p.title"):
            out[url] = title or ""
        return out

    def group_count(self, url: str) -> int:
        """How many merge groups this page currently has (`G-65`).

        Counted rather than listed, and reported on every capture, because
        live aggregation is otherwise invisible: stage two runs on a
        background thread after the reader pauses, and without a number
        moving there is no way to tell it ran from outside the process.
        """
        rows = self._rows(
            "MATCH (c:Chunk {url: $url}) "
            "WHERE c.group_of = c.cid AND c.group_n > 1 RETURN count(c)",
            {"url": url})
        return int(rows[0][0]) if rows else 0

    def corpus_fingerprint(self) -> str:
        """Which pages this store holds, not how many chunks -- `D-22`.

        **A count is not an identity.** The layout cache and the persisted
        fit were keyed on `chunk_count()`, on the reasoning that a fit is a
        function of the chunks it saw. It is, but a count does not name
        them: delete twenty pages and capture twenty chunks elsewhere and
        the key is unchanged, so a stored fit comes back for a corpus it
        never saw. Measured live -- a page layout served from the store
        still carried nodes for `live_mutate.html` fixtures that had been
        purged, and unfolding one of its pages anchored **643 units** away
        against a ball of radius 90, because the page had been drawn by a
        fit over a different set of documents.

        This is the same shape as the other discriminators this repo has
        had to fix: `[n]` blanked from two xpaths, a cumulative `repairMs`
        read as a per-delta cost. A number that two different states share
        cannot tell them apart.

        Cheap enough to run per request: one indexed scan of the Page
        table, 99 rows on this corpus, hashed. `chunk_count` is already
        paid on the same path.
        """
        rows = self._rows(
            "MATCH (p:Page) RETURN p.url, p.chunk_count ORDER BY p.url")
        digest = hashlib.blake2b(digest_size=16)
        for url, n in rows:
            digest.update(str(url).encode("utf-8", "replace"))
            digest.update(b"\x00")
            digest.update(str(int(n or 0)).encode("ascii"))
            digest.update(b"\x00")
        return digest.hexdigest()

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
                "MATCH (c:Chunk {url: $url}) "
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
        self._execute(
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
        """A page's chunks, matched on the CHUNK's url.

        **Not through the `Page` node, which does not always agree with it.**
        Measured on `build/corpus123`: 3,033 of 14,169 `HasChunk` edges join
        a page to chunks carrying a different url, over 8 pages, in two
        classes -- percent-encoding (`ar.wikipedia.org/wiki/<arabic>` on the
        page, `%D9%81...` on the chunks) and a trailing slash
        (`https://books.toscrape.com` against `https://books.toscrape.com/`).

        Matching through the page therefore returned ZERO chunks for the
        largest page in the corpus, 801 of them, so unfolding it drew nothing
        and aggregating it was skipped as under the gate. The chunk carries
        its own url and is what every other read here keys on --
        `embeddings_for`, `contains_within`, `page_vectors` all use `c.url`
        -- so this one now agrees with them.
        """
        if url:
            rows = self._rows(
                "MATCH (c:Chunk {url: $url}) "
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

    #: Address rows whose key could not be parsed, since the store opened.
    #:
    #: Counted rather than raised. One malformed row used to take the whole
    #: chunk with it: `ContentAddress.parse('')` throws, `addresses_of`
    #: propagated it, and `GET /chunk/<cid>` answered with a dead connection
    #: -- so the chunk panel, the markdown face and the affordance list all
    #: showed nothing for that chunk, with the cause visible only in the
    #: sidecar's stderr. A chunk that cannot be fetched cannot surface in
    #: the UI at all, which is the most expensive way for one bad row to
    #: fail.
    unreadable_addresses: int = 0

    def relink_pages(self, batch: int = 20000) -> dict:
        """Recompute `LinksTo` across the whole corpus.

        **Why this is not a repair of bad data.** Every edge
        `_link_hyperlinks` wrote is correct; the ones it never wrote are the
        problem, and it never wrote them because the target had not been
        scanned yet. A link graph is a property of the corpus as a WHOLE, and
        it was being computed per page at ingest time against whatever
        happened to exist. Running it again with every page present is the
        same rule applied to the complete set.

        Reads only what the store already holds: a url-valued address, and
        the chunk anchored to it. `MERGE` so existing edges are untouched and
        a second run costs nothing.

        Returns the counts that matter for judging it: how many url addresses
        were considered, how many resolved to a page the store actually has,
        and how many edges exist afterwards. An address pointing off-corpus
        is not a failure and is counted separately, because that number is
        mostly what a link graph over a hundred unrelated pages should be.
        """
        from .address import ContentAddress

        stored = list(self.page_urls())
        exact = set(stored)
        by_canonical: Dict[str, str] = {}
        for candidate in stored:
            by_canonical.setdefault(canonical_url(candidate) or candidate,
                                    candidate)
            # **`/` and `/index.html` are the same page, and the store keeps
            # whichever one it was scanned with.** A relative `../index.html`
            # resolves to the second spelling while the page is stored under
            # the first, so the edge was dropped as off-corpus -- 78 of them
            # on books.toscrape alone, a site whose pages link almost only to
            # each other. Registering both spellings costs one dict entry and
            # is the difference between a site that draws as a connected
            # component and one that draws as dust.
            canonical = canonical_url(candidate) or candidate
            for spelling in _index_spellings(canonical):
                by_canonical.setdefault(spelling, candidate)

        rows = self._rows(
            "MATCH (c:Chunk)-[:Anchors]->(a:Address) "
            "RETURN c.cid, c.url, a.akey, a.value")
        out = {"url_addresses": 0, "off_corpus": 0, "self_links": 0,
               "unreadable": 0, "pairs": 0, "before": 0, "after": 0}
        out["before"] = self._rows(
            "MATCH (:Chunk)-[r:LinksTo]->(:Page) RETURN count(r)")[0][0]

        seen = set()
        pairs = []
        for cid, curl, akey, value in rows:
            if not akey or not value:
                continue
            try:
                address = ContentAddress.parse(akey)
            except Exception:                       # noqa: BLE001
                out["unreadable"] += 1
                continue
            if not address.is_url:
                continue
            out["url_addresses"] += 1
            target = canonical_url(value, curl)
            if not target:
                continue
            resolved = target if target in exact else by_canonical.get(target)
            if resolved is None:
                out["off_corpus"] += 1
                # **What it failed to match, not just how often.** A link to
                # a page the store HAS, spelled differently, is
                # indistinguishable from a link to the open web unless the
                # misses are looked at -- and the two want opposite fixes.
                host = target.split("/")[2] if "//" in target else ""
                out.setdefault("_hosts", {})
                out["_hosts"][host] = out["_hosts"].get(host, 0) + 1
                if len(out.setdefault("miss_sample", [])) < 12:
                    out["miss_sample"].append(target)
                continue
            if resolved == curl:
                out["self_links"] += 1
                continue
            key = (cid, resolved)
            if key in seen:
                continue
            seen.add(key)
            pairs.append({"cid": cid, "url": resolved})

        for i in range(0, len(pairs), batch):
            self._batch(
                "UNWIND $rows AS r MATCH (c:Chunk {cid: r.cid}), "
                "(p:Page {url: r.url}) MERGE (c)-[:LinksTo]->(p)",
                pairs[i:i + batch],
            )
        out["pairs"] = len(pairs)
        out["after"] = self._rows(
            "MATCH (:Chunk)-[r:LinksTo]->(:Page) RETURN count(r)")[0][0]
        # Hosts we hold pages for, that links to them still missed: the
        # near-misses, which are a spelling defect rather than the open web.
        held_hosts = {u.split("/")[2] for u in stored if "//" in u}
        hosts = out.pop("_hosts", {})
        out["missed_on_a_host_we_hold"] = sum(
            n for h, n in hosts.items() if h in held_hosts)
        out["missed_hosts_top"] = sorted(
            hosts.items(), key=lambda kv: -kv[1])[:6]
        return out

    def repair_blank_keys(self, batch: int = 20000) -> dict:
        """Rebuild `akey` in place for every address that lost it.

        **No re-scan, because the key is derived, not captured.**
        `ContentAddress.key()` is `url|xpath|tag|accessor` with `%` and `|`
        escaped, and all four of those are already columns on the row. So an
        address with a blank key is not missing information; it is missing a
        string that can be recomputed from what is beside it.

        That matters because re-scanning would not have fixed it anyway: the
        guard in `ingest` is now a function of `akey`, so a fresh scan does
        repair a page -- but only a page someone thinks to visit, and the
        live corpus had 29 of 74 sampled pages affected across sites that
        need a browser each. This repairs the store it is pointed at.

        Idempotent: it only touches rows whose key is null or empty.
        """
        from .address import _esc, _SEP

        rows = self._rows(
            "MATCH (a:Address) WHERE a.akey IS NULL OR a.akey = '' "
            "RETURN a.aid, a.url, a.xpath, a.tag, a.accessor")
        out = {"blank": len(rows), "repaired": 0, "unrepairable": 0}
        fixed = []
        for aid, url, xpath, tag, accessor in rows:
            # A row missing its url or xpath cannot be spelled back, and
            # inventing a key for it would put a handle on the page that
            # points nowhere. Counted, not guessed.
            if not url or not xpath:
                out["unrepairable"] += 1
                continue
            fixed.append({"aid": aid, "akey": _SEP.join(
                _esc(part or "") for part in (url, xpath, tag, accessor))})
        for i in range(0, len(fixed), batch):
            self._batch(
                "UNWIND $rows AS r MATCH (a:Address {aid: r.aid}) "
                "SET a.akey = r.akey",
                fixed[i:i + batch])
        out["repaired"] = len(fixed)
        return out

    def heal_anchors(self, limit: int = 200, step=None) -> Dict[str, int]:
        """Delete stale anchors, chunk by chunk (G-186; the reader: "Clean them
        now", 2026-10-12).

        A chunk holding more anchors than lines carries anchors its earlier
        renders left: an anchor at a line number past its last line goes; where
        a line holds several, the one whose address's stored VALUE best matches
        the line's text stays and the rest go (a tie stays as it is, counted).
        Deleted forward from the chunk, one statement a row -- the only form
        that removes them on a store whose address-side adjacency lacks them.
        `limit` chunks per call; `step` runs before each (stand aside).
        """
        out = {"chunks": 0, "deleted": 0, "beyond_last_line": 0, "duplicates_resolved": 0, "ties": 0}
        rows = self._rows(
            "MATCH (c:Chunk) OPTIONAL MATCH (c)-[e:Anchors]->(:Address) "
            "WITH c, count(e) AS k WHERE k > c.line_count "
            "RETURN c.cid, c.md, c.line_count LIMIT $n", {"n": int(limit)})
        words = lambda t: set(re.findall(r"[0-9A-Za-z\u00C0-\uffff]{2,}", (t or "").lower()))
        for cid, md, n_lines in rows:
            if step is not None:
                step(cid)
            lines = (md or "").split(chr(10))
            n = int(n_lines or len(lines))
            held: Dict[int, List[Tuple[str, str]]] = {}
            for o, aid, value in self._rows(
                    "MATCH (c:Chunk {cid: $c})-[e:Anchors]->(a:Address) RETURN e.ord, a.aid, a.value",
                    {"c": cid}):
                held.setdefault(int(o), []).append((str(aid), str(value or "")))
            drop: List[Tuple[int, str]] = []
            for o, anchors in held.items():
                if o >= n:
                    drop.extend((o, a) for a, _v in anchors)
                    out["beyond_last_line"] += len(anchors)
                    continue
                if len(anchors) < 2:
                    continue
                lw = words(lines[o] if o < len(lines) else "")
                scored = sorted(((len(words(v) & lw) / max(1, len(words(v))), a) for a, v in anchors), reverse=True)
                if scored[0][0] == scored[1][0]:
                    out["ties"] += 1
                    continue
                drop.extend((o, a) for _s, a in scored[1:])
                out["duplicates_resolved"] += 1
            for o, a in drop:
                self._execute(
                    "MATCH (:Chunk {cid: $c})-[e:Anchors]->(x:Address) "
                    "WHERE e.ord = $o AND x.aid + '' = $a DELETE e",
                    {"c": cid, "a": a, "o": int(o)})
            out["deleted"] += len(drop)
            out["chunks"] += 1
        return out

    def anchors_by_line(self, cid: str) -> Dict[int, Tuple[ContentAddress, str]]:
        """The addresses a chunk anchors, BY LINE INDEX (`ord`).

        A line that draws no address has no anchor, so `addresses_of`'s list,
        read in order, has no slot for it -- and a caller zipping that list
        with the lines gives every later line its neighbour's address. arXiv's
        listing, 2026-10-12: "Total of 341 entries" keyed to the `h1` that
        reads "Machine Learning", one line off for the rest of the chunk.
        """
        out: Dict[int, Tuple[ContentAddress, str]] = {}
        seen: Dict[int, int] = {}
        keys_at: Dict[int, List[str]] = {}
        for ordinal, key, value in self._rows(
                "MATCH (c:Chunk {cid: $cid})-[r:Anchors]->(a:Address) "
                "RETURN r.ord, a.akey, a.value ORDER BY r.ord", {"cid": cid}):
            seen[int(ordinal)] = seen.get(int(ordinal), 0) + 1
            keys_at.setdefault(int(ordinal), []).append(str(key or ""))
            try:
                out[int(ordinal)] = (ContentAddress.parse(key), value)
            except Exception:                       # noqa: BLE001
                continue
        #: Lines anchored more than once: stale anchors never deleted (G-186).
        self.last_duplicate_ords = sum(1 for n in seen.values() if n > 1)
        self.last_duplicates = {o: ks for o, ks in keys_at.items() if len(ks) > 1}
        return out

    def addresses_of(self, cid: str) -> List[Tuple[ContentAddress, str]]:
        """The addresses a chunk anchors, in line order.

        Rows that will not parse are SKIPPED and counted. Dropping a line's
        address costs that line its handle on the page; dropping the whole
        chunk costs the reader the chunk.
        """
        rows = self._rows(
            "MATCH (c:Chunk {cid: $cid})-[r:Anchors]->(a:Address) "
            "RETURN r.ord, a.akey, a.value ORDER BY r.ord", {"cid": cid})
        out: List[Tuple[ContentAddress, str]] = []
        for _, key, value in rows:
            try:
                out.append((ContentAddress.parse(key), value))
            except Exception:                       # noqa: BLE001
                GraphStore.unreadable_addresses += 1
        return out

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

    def addresses_at_many(self, xpaths, url: str) -> Dict[str, List[Tuple[ContentAddress, str]]]:
        """`addresses_at` for many elements of ONE page, in one query.

        A chunk asks for every element it draws; one query per element made a
        chunk payload cost 0.36-2.0 s on a 500k-address store (2026-10-07: a
        panel's first paint waited for it, "Rendering on the billboards can
        definitely still be sped up more"). One scan, filtered by url and the
        element list, answers them all.
        """
        xs = sorted({x for x in xpaths if x})
        out: Dict[str, List[Tuple[ContentAddress, str]]] = {x: [] for x in xs}
        if not xs:
            return out
        rows = self._rows(
            "MATCH (a:Address) WHERE a.url = $url AND a.xpath IN $xs "
            "RETURN a.xpath, a.akey, a.value ORDER BY a.akey",
            {"url": url, "xs": xs})
        for xpath, key, value in rows:
            out.setdefault(xpath, []).append((ContentAddress.parse(key), value))
        return out

    def save_drawn(self, rows) -> int:
        """Each chunk's drawn place in chunk view, on the chunk (PLUGIN_GOAL 108).

        `rows` is [(cid, [x, y, z, fx, fy, fz, half?])]: the place the relax
        settled on, the fit point it was relaxed FROM -- which is what makes
        the place reusable only while the fit still puts the chunk there --
        and the drawn radius it was relaxed AT (a place spaced for another
        size is not this size's place).
        """
        data = [{"cid": str(c), "d": [float(v) for v in d][:7]} for c, d in rows
                if c and d is not None and len(d) >= 6]
        if not data:
            return 0
        self._batch("UNWIND $rows AS r MATCH (c:Chunk {cid: r.cid}) SET c.drawn = r.d", data)
        return len(data)

    def save_layout(self, key: str, payload: str, n: int = 0) -> None:
        """Keep a fitted layout under `key` (`G-12`).

        The key names everything the fit is a function of -- the corpus size,
        the dimensions, the space and the level -- so a stored answer is
        returned only to the question it answered. That is the same
        discipline `Projection.stale` applies in memory, written down.
        """
        import time

        self._execute(
            "MERGE (l:Layout {key: $key}) "
            "SET l.payload = $payload, l.fitted_at = $at, l.n = $n",
            {"key": key, "payload": payload, "at": time.time(), "n": int(n)})

    def load_layout(self, key: str) -> Optional[str]:
        """The stored layout for `key`, or None.

        None is the ordinary answer for a corpus that has changed, and the
        caller refits. Nothing here decides whether a fit is stale: the key
        does, by naming what the fit depends on.
        """
        rows = self._rows(
            "MATCH (l:Layout {key: $key}) RETURN l.payload", {"key": key})
        if not rows or not rows[0][0]:
            return None
        return str(rows[0][0])

    def forget_layouts(self) -> int:
        """Drop every stored fit. Returns how many.

        For a caller that changed something the KEY does not name -- a
        different seed, a new `min_dist`, a changed vector space. A key that
        named those too would be honest and unusable, since nothing calling
        `/layout` knows them.
        """
        rows = self._rows("MATCH (l:Layout) RETURN count(l)")
        n = int(rows[0][0]) if rows and rows[0] else 0
        self._execute("MATCH (l:Layout) DETACH DELETE l")
        return n

    def relink(self) -> Dict[str, int]:
        """Re-resolve every url address against the pages held NOW.

        **A link is resolved once, at ingest, against the pages the store
        happened to hold at that moment.** A corpus scanned page by page
        therefore ends with almost no link edges: when the first page was
        written, none of the others existed to point at. Measured on
        `build/corpus123` -- 96 pages, 14,129 chunks, 29,186 url-valued
        addresses, and **2** `LinksTo` edges in the whole store.

        Nothing is re-fetched or re-rendered. The addresses already hold the
        targets; what was missing is a second look once the corpus stopped
        growing. 103 of those 29,186 point at a page this corpus actually
        holds, over 13 distinct pages -- the ceiling is low because these are
        mostly unrelated pages rather than a crawl, and the ceiling is the
        point: the axis is sparse, and it should be sparse rather than empty.

        Returns what it found, so a caller can see the ceiling as well as the
        gain.
        """
        stored = self.page_urls()
        exact = set(stored)
        by_canonical: Dict[str, str] = {}
        for candidate in stored:
            by_canonical.setdefault(canonical_url(candidate) or candidate,
                                    candidate)

        # Which chunk draws which address, for the whole store this time.
        chunk_of: Dict[str, str] = {}
        for cid, aid in self._rows(
                "MATCH (c:Chunk)-[:Anchors]->(a:Address) RETURN c.cid, a.aid"):
            if cid and aid:
                chunk_of.setdefault(aid, cid)

        seen: set = set()
        pairs = []
        considered = 0
        # Every LINK-shaped value, not only the web ones. An import is a
        # link (`G-8`, `G-51`) and carries a `code://` target, so an
        # http-only filter silently made `relink` a no-op for the whole
        # codebase corpus -- it reported `url_addresses: 0` over a store
        # holding 102 modules.
        for aid, src, value in self._rows(
                "MATCH (a:Address) WHERE starts_with(a.value, 'http') "
                "OR starts_with(a.value, 'code://') "
                "OR starts_with(a.value, 'vault://') "
                # A link inside a NOTE is relative -- `Lattice.md`, or a
                # wikilink with no extension at all -- so it carries no
                # prefix to match on. Selected by where it LIVES instead.
                "OR starts_with(a.url, 'vault://') "
                "RETURN a.aid, a.url, a.value"):
            if not value:
                continue
            considered += 1
            target = canonical_url(value, src or "")
            if not target:
                continue
            resolved = target if target in exact else by_canonical.get(target)
            if resolved is None and not target.endswith(".md") \
                    and str(src or "").startswith("vault://"):
                # `[[Lattice]]` names a NOTE, and the note is a file. The
                # store's own rule still decides -- this only offers the
                # spelling a vault uses.
                with_md = target + ".md"
                resolved = (with_md if with_md in exact
                            else by_canonical.get(with_md))
            if resolved is None or resolved == src:
                continue
            cid = chunk_of.get(aid)
            if cid is None or (cid, resolved) in seen:
                continue
            seen.add((cid, resolved))
            pairs.append({"cid": cid, "url": resolved})

        before = self._rows("MATCH ()-[r:LinksTo]->() RETURN count(r)")[0][0]
        if pairs:
            self._batch(
                "UNWIND $rows AS r MATCH (c:Chunk {cid: r.cid}), "
                "(p:Page {url: r.url}) MERGE (c)-[:LinksTo]->(p)",
                pairs,
            )
        after = self._rows("MATCH ()-[r:LinksTo]->() RETURN count(r)")[0][0]
        return {"url_addresses": considered,
                "resolvable": len(pairs),
                "edges_before": int(before),
                "edges_after": int(after)}

    def page_links(self) -> List[Tuple[str, str]]:
        """Page-to-page links, as (source url, target url).

        The edge set the collapsed view draws (`G-53`). `edges()` routes a
        hyperlink to the target page's FIRST chunk so that one link is one
        edge for PageRank; at page level there is nothing to route, because
        the page is the node.
        """
        return [(a, b) for a, b in self._rows(
            "MATCH (c:Chunk)-[:LinksTo]->(p:Page) RETURN c.url, p.url")
            if a and b]

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
        self._tnode_forget(url)
        cids = [r[0] for r in self._rows(
            "MATCH (c:Chunk {url: $url}) RETURN c.cid",
            {"url": url})]
        self._execute(
            "MATCH (a:Address {url: $url}) DETACH DELETE a", {"url": url})
        self._execute(
            "MATCH (c:Chunk {url: $url}) DETACH DELETE c", {"url": url})
        self._execute(
            "MATCH (p:Page {url: $url}) DETACH DELETE p", {"url": url})
        return len(cids)
