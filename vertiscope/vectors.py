"""The third phase: frequency vectors, PageRank, semantic vectors.

Three scores over the same objects, combined as a product. The objects are
markdown chunks, and every one of them carries a single **integer row** that
indexes all three:

    freq   FreqMatrix    row -> sparse tf-idf vector      (external, on disk)
    rank   ndarray       row -> PageRank score            (derived, cheap)
    embed  ndarray       row -> dense semantic vector     (stored with the chunk)

The integer row is what makes the product cheap: no joins, no dictionary
lookups per candidate, three array reads at the same index.

Why the frequency vectors live outside the graph
------------------------------------------------
A tf-idf vector is not a property of the chunk. Its `idf` component is a
function of the whole corpus (THEORY Prop. 14.6: `df` is determined by the
corpus), so the same chunk's vector changes when an unrelated page is added.
Storing it on the chunk would either be a lie that goes stale or would force
a rewrite of every row on every scan. It also shares one vocabulary across
all rows, so a per-row encoding repeats the term indirection `n` times.

A semantic vector is the opposite: it is a function of the chunk's own text
and nothing else, so it belongs with the chunk and travels with it.

That asymmetry, not storage convenience, is why one is external and the other
is not.

Persistence is `np.savez` over the CSR triple — `data`, `indices`, `indptr` —
which is exactly a pure numpy matrix with integer indexing. Dense would be
absurd here: 54 pages produce ~10^5 rows over ~10^6 terms, and the matrix is
about 0.01% populated.
"""

from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

import threading

import numpy as np
from scipy import sparse

__all__ = [
    "FreqMatrix",
    "pagerank",
    "EmbeddingMatrix",
    "VectorQueue",
    "tokens",
]

# --- tokenization -----------------------------------------------------------

_TOKEN_RE = re.compile(r"(?u)\b\w+\b")
_URL_SEP_RE = re.compile(r"[/\-_.]+")
_PERCENT_RE = re.compile(r"%[0-9A-Fa-f]{2}")


def _url_words(url: str) -> str:
    """A URL as searchable words: host and path, split on separators.

    Markdown chunks are dense with URLs — every link and every image is one —
    and an unsplit URL contributes a single term that matches nothing. Split,
    the host and path contribute the words a person would actually type:
    ``/wiki/Web_scraping`` becomes "wiki web scraping".

    The **query string is excluded**, which the first version got wrong. Query
    strings are machine parameters, and expanding them put terms like
    ``ctx_ver``, ``rft_val_fmt`` and tracking-widget parameters into the
    index. Measured on the corpus, that let link-soup chunks outrank prose:
    the top hit for "web scraping with python" was a Wikipedia citation's
    COinS metadata rather than the article. A query string can hold real words
    — ``?q=telescope`` — but it holds far more machine tokens, and the ones it
    holds are already present in the page's visible text when they matter.
    """
    try:
        parts = urlsplit(url)
    except ValueError:
        return ""
    if parts.scheme not in ("http", "https", ""):
        return ""
    body = " ".join(p for p in ((parts.hostname or "").replace(".", " "),
                                parts.path or "") if p)
    return re.sub(r"\s+", " ", _PERCENT_RE.sub(" ", _URL_SEP_RE.sub(" ", body))).strip()


#: Aliased on import: this module already exports a function called `tokens`,
#: and the two answer different questions -- that one makes lexical terms, this
#: one counts and trims a model's window.
from . import tokens as tokens_mod


def tokens(text: str, ngram_max: int = 2) -> List[str]:
    """Lowercase unigrams plus adjacent bigrams, URLs expanded to words.

    Bigrams are emitted *in addition to* their unigrams, never instead — that
    is THEORY Prop. 13.3's coherence condition, and it is what lets a vector
    be checked for internal consistency: a row holding "web scraping" without
    "web" and "scraping" is corrupt, and the invariant checker says so.
    """
    if not text:
        return []
    expanded = re.sub(r"(?:https?://|/)\S+",
                      lambda m: " " + _url_words(m.group(0)) + " ", text)
    unigrams = [m.group(0).lower() for m in _TOKEN_RE.finditer(expanded)]
    if ngram_max <= 1:
        return unigrams
    return unigrams + [
        unigrams[i] + " " + unigrams[i + 1] for i in range(len(unigrams) - 1)
    ]


# --- frequency ---------------------------------------------------------------



def _locked(fn):
    """Run under the matrix's own lock (re-entrant: derived reads nest)."""
    import functools

    @functools.wraps(fn)
    def run(self, *a, **k):
        if _PLANT_NO_LOCK[0]:
            return fn(self, *a, **k)
        with self._lock:
            return fn(self, *a, **k)
    return run


#: Planted: the matrix unlocked, as before (the shapes race).
_PLANT_NO_LOCK = [False]

@dataclass
class FreqMatrix:
    """Sparse tf-idf over chunk markdown, indexed by integer row.

    Rows are **never renumbered**: an index handed out once keeps pointing at
    the same chunk, because it is the key the embedding matrix and the
    PageRank vector are aligned on. Compacting on delete would move every row
    after the hole and silently re-point both.

    So :meth:`remove` empties a row and tombstones it, and the freed index
    goes on a list that :meth:`add` draws from before growing. Retirement is
    therefore neither a leak (a purge-and-rescan cycle reuses the same rows)
    nor a renumbering (surviving rows do not move). The free list is persisted
    with the matrix; without that, the leak returns on the next reopen.
    """

    vocab: Dict[str, int] = field(default_factory=dict)
    rows: List[str] = field(default_factory=list)          # row -> chunk id
    _row_of: Dict[str, int] = field(default_factory=dict)  # chunk id -> row
    _counts: List[Dict[int, int]] = field(default_factory=list)
    _free: List[int] = field(default_factory=list)   # retired rows, reusable
    _csr: Optional[sparse.csr_matrix] = None
    _df: Optional[np.ndarray] = None
    #: The weighted matrix, built once per mutation batch like `_csr`. It
    #: was rebuilt on EVERY query -- copy, log, idf, normalise over 62k rows
    #: -- and was the fixed ~0.8 s of every search, scoped or not
    #: (2026-10-17, `/search` timing: lexical 750-930 ms). A function of the
    #: counts and the vocabulary only, so `_invalidate` is its whole
    #: invalidation.
    _tfidf: Optional[sparse.csr_matrix] = None
    #: One lock for the counts and everything derived from them. A search
    #: built its tf-idf while a capture added vocabulary, and the term matrix
    #: and the document frequencies came from two moments: "inconsistent
    #: shapes", the search answered with a closed connection (2026-10-18).
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)

    # -- build -------------------------------------------------------------
    @_locked
    def add(self, cid: str, text: str) -> int:
        """Index one chunk. Returns its row. Re-adding replaces in place.

        Term counts are held per row as a dict and the sparse matrix is built
        only when something reads it. Writing into a growing sparse matrix
        directly is quadratic — every new term widens it, and widening copies
        every row written so far — which on the corpus meant the build never
        finished. Deferring costs one pass at read time and makes ingest
        linear in the number of tokens.
        """
        counts: Dict[int, int] = {}
        for tok in tokens(text):
            col = self.vocab.get(tok)
            if col is None:
                col = len(self.vocab)
                self.vocab[tok] = col
            counts[col] = counts.get(col, 0) + 1

        row = self._row_of.get(cid)
        if row is not None:
            self._counts[row] = counts
        else:
            # Reclaim a retired row before growing. Without this a workspace
            # that is purged and re-scanned — the normal cycle for a crawler
            # kept up to date — accumulates dead rows forever, and every
            # matrix operation pays for them.
            row = self._free.pop() if self._free else len(self.rows)
            if row == len(self.rows):
                self.rows.append(cid)
                self._counts.append(counts)
            else:
                self.rows[row] = cid
                self._counts[row] = counts
            self._row_of[cid] = row
        self._invalidate()
        return row

    def add_many(self, pairs: Iterable[Tuple[str, str]]) -> List[int]:
        return [self.add(cid, text) for cid, text in pairs]

    @_locked
    def remove(self, cid: str) -> bool:
        """Retire a chunk's row. Returns whether it was present.

        The row is emptied and *tombstoned*, not deleted: rows are the key the
        embedding matrix and the PageRank vector are aligned on, so removing
        one would renumber every row after it and silently re-point both. The
        emptied row scores zero on every query and contributes nothing to
        document frequency, which is the whole of what removal has to mean.

        Purging without this left the rows behind, so `idf` was computed over
        documents that no longer existed — a quiet drift in every score rather
        than a visible failure. `invariants.w1_graph_and_matrix_hold_the_same_chunks`
        is what caught it.
        """
        row = self._row_of.pop(cid, None)
        if row is None:
            return False
        self._counts[row] = {}
        self.rows[row] = ""          # tombstone
        self._free.append(row)       # reclaimable by the next add
        self._invalidate()
        return True

    @_locked
    def forget_vocabulary(self) -> int:
        """Drop terms no surviving row contains. Returns terms dropped.

        Emptying a row is enough to stop it being *retrieved*; it is not
        enough to stop it being *read*. The vocabulary is a list of every
        word the corpus has ever contained, it is persisted verbatim in
        `freq_meta.json`, and after a purge it went on naming the words of
        the page that was purged. Anyone with the file could recover the bag
        of words of a page the store had been told to forget, which makes the
        promise `forget` advertises one it does not keep.

        Columns are compacted here where rows never are, and the asymmetry is
        the point: rows are the key the semantic matrix and the rank vector
        are aligned on, so moving one silently re-points both. Nothing
        outside this class is aligned to a column — `query_vector` looks
        every term up through `vocab` on each call, `document_frequency` is
        derived, and the saved matrix is rebuilt from the same file it was
        written to. So a column can be renumbered and a row cannot.
        """
        live = set()
        for counts in self._counts:
            live.update(counts)
        if len(live) == len(self.vocab):
            return 0
        remap: Dict[int, int] = {}
        new_vocab: Dict[str, int] = {}
        for term, col in sorted(self.vocab.items(), key=lambda kv: kv[1]):
            if col in live:
                remap[col] = len(new_vocab)
                new_vocab[term] = remap[col]
        dropped = len(self.vocab) - len(new_vocab)
        self.vocab = new_vocab
        self._counts = [{remap[c]: n for c, n in counts.items() if c in remap}
                        for counts in self._counts]
        self._invalidate()
        return dropped

    @property
    def live_rows(self) -> int:
        """Rows still holding a chunk, tombstones excluded."""
        return sum(1 for cid in self.rows if cid)

    def _invalidate(self) -> None:
        # df is a corpus aggregate (THEORY Prop. 14.6) and the matrix is a
        # view of the counts; both are re-derived rather than patched.
        self._csr = None
        self._df = None
        self._tfidf = None
        #: Bumped on every mutation, so a long-running owner can save only
        #: when something changed. See `Workspace.save_lexical`.
        self.version = getattr(self, "version", 0) + 1

    @_locked
    def _matrix(self) -> sparse.csr_matrix:
        """Raw term counts as CSR, built once per mutation batch."""
        if self._csr is not None:
            return self._csr
        n_rows, n_cols = len(self._counts), max(len(self.vocab), 1)
        if not n_rows:
            self._csr = sparse.csr_matrix((0, n_cols), dtype=np.float32)
            return self._csr
        indptr = np.zeros(n_rows + 1, dtype=np.int64)
        indices: List[int] = []
        data: List[float] = []
        for i, counts in enumerate(self._counts):
            for col, n in counts.items():
                indices.append(col)
                data.append(float(n))
            indptr[i + 1] = len(indices)
        self._csr = sparse.csr_matrix(
            (np.asarray(data, dtype=np.float32),
             np.asarray(indices, dtype=np.int32), indptr),
            shape=(n_rows, n_cols),
        )
        return self._csr

    # -- read --------------------------------------------------------------
    def row_of(self, cid: str) -> Optional[int]:
        return self._row_of.get(cid)

    @property
    def shape(self) -> Tuple[int, int]:
        return (len(self._counts), max(len(self.vocab), 1) if self.vocab else 0)

    @_locked
    def document_frequency(self) -> np.ndarray:
        """Per-term document count, recomputed when stale.

        Derived rather than maintained. THEORY Prop. 14.6 says `df` is
        determined by the corpus, and ERRATA A4 notes that storing something
        derivable is what turns an identity into an invariant somebody has to
        police. Recomputing costs one pass over the nonzeros.
        """
        if self._df is None:
            csr = self._matrix()
            if not csr.shape[0]:
                return np.zeros(csr.shape[1], dtype=np.float32)
            self._df = np.bincount(
                csr.indices, minlength=csr.shape[1]
            ).astype(np.float32)
        return self._df

    @_locked
    def tfidf(self) -> sparse.csr_matrix:
        """L2-normalised sublinear-tf x idf. Cosine similarity is then a dot.

        Sublinear tf (`1 + log f`) because a term appearing ten times in a
        chunk is not ten times as much evidence; smoothed idf because an
        unseen term must not divide by zero.
        """
        if self._tfidf is not None:
            return self._tfidf
        csr = self._matrix().copy()
        if not csr.shape[0]:
            return csr
        n_docs = max(csr.shape[0], 1)
        df = self.document_frequency()
        idf = np.log((1.0 + n_docs) / (1.0 + df)).astype(np.float32) + 1.0
        csr.data = 1.0 + np.log(csr.data)
        csr = csr.multiply(sparse.csr_matrix(idf.reshape(1, -1))).tocsr()
        norms = np.sqrt(csr.multiply(csr).sum(axis=1)).A.ravel()
        norms[norms == 0] = 1.0
        inv = sparse.diags((1.0 / norms).astype(np.float32))
        self._tfidf = (inv @ csr).tocsr()
        return self._tfidf

    @_locked
    def query_vector(self, query: str) -> np.ndarray:
        """Dense query vector in the same space, L2-normalised.

        Dense because a query is one row: the sparse machinery would cost more
        than the ~10^6 floats it saves, and it is multiplied against the whole
        matrix exactly once.
        """
        n_cols = self.shape[1]
        vec = np.zeros(n_cols, dtype=np.float32)
        if not n_cols:
            return vec
        counts: Dict[int, int] = {}
        for tok in tokens(query):
            col = self.vocab.get(tok)
            if col is not None:
                counts[col] = counts.get(col, 0) + 1
        if not counts:
            return vec
        df = self.document_frequency()
        n_docs = max(self.shape[0], 1)
        for col, n in counts.items():
            idf = math.log((1.0 + n_docs) / (1.0 + float(df[col]))) + 1.0
            vec[col] = (1.0 + math.log(n)) * idf
        norm = float(np.linalg.norm(vec))
        return vec / norm if norm else vec

    @_locked
    def similarities(self, query: str) -> np.ndarray:
        """Cosine similarity of every row against the query."""
        if not self.shape[0]:
            return np.zeros(0, dtype=np.float32)
        # No columns is a different emptiness from no rows, and it is the one
        # `forget` produces: rows stay allocated as tombstones because the
        # semantic matrix and the rank vector are aligned on them, while
        # `forget_vocabulary` compacts the columns away entirely. Forgetting
        # the last page therefore leaves 8 rows and 0 terms.
        #
        # `query_vector` gets that right and returns a length-0 vector. The
        # sparse builder does not -- an empty CSR still reports one column --
        # so the two disagreed and the matmul raised instead of returning
        # nothing. A corpus with no terms matches no query, which is a real
        # answer and the one a reader who just forgot everything should get.
        if not self.shape[1]:
            return np.zeros(self.shape[0], dtype=np.float32)
        return np.asarray(self.tfidf() @ self.query_vector(query)).ravel()

    # -- persistence -------------------------------------------------------
    @_locked
    def save(self, directory) -> None:
        """CSR triple as raw numpy arrays, vocabulary and rows as JSON."""
        path = Path(directory)
        path.mkdir(parents=True, exist_ok=True)
        csr = self._matrix()
        # ATOMIC: written beside, then renamed over (2026-10-07: the sidecar
        # crashed natively mid-save and left `freq.npz` at 0 bytes; every
        # restart then died on "No data left in file" and the store would not
        # open). A rename either happened or did not.
        import os as _os
        tmp_npz = path / "freq.npz.tmp"
        with open(tmp_npz, "wb") as fh:
            np.savez_compressed(
                fh,
                data=csr.data.astype(np.float32),
                indices=csr.indices.astype(np.int32),
                indptr=csr.indptr.astype(np.int64),
                shape=np.asarray(csr.shape, dtype=np.int64),
            )
            fh.flush()
            _os.fsync(fh.fileno())
        tmp_meta = path / "freq_meta.json.tmp"
        tmp_meta.write_text(
            json.dumps({"vocab": self.vocab, "rows": self.rows,
                        "free": self._free}),
            encoding="utf-8",
        )
        # Both are complete on disk before either is swapped in.
        _os.replace(tmp_npz, path / "freq.npz")
        _os.replace(tmp_meta, path / "freq_meta.json")

    @classmethod
    def load(cls, directory) -> "FreqMatrix":
        path = Path(directory)
        meta_file = path / "freq_meta.json"
        if not meta_file.exists():
            return cls()
        meta = json.loads(meta_file.read_text(encoding="utf-8"))
        obj = cls(vocab=meta["vocab"], rows=meta["rows"])
        obj._free = list(meta.get("free", []))
        # Tombstones are empty entries and belong in neither index.
        obj._row_of = {cid: i for i, cid in enumerate(obj.rows) if cid}
        with np.load(path / "freq.npz") as npz:
            shape = tuple(int(x) for x in npz["shape"])
            csr = sparse.csr_matrix(
                (npz["data"], npz["indices"], npz["indptr"]), shape=shape
            )
        obj._csr = csr.astype(np.float32)
        # The per-row dicts are the authoritative form, so they are restored
        # too — otherwise a load-then-add would rebuild the matrix from an
        # empty count list and silently drop everything loaded.
        obj._counts = [
            dict(zip(csr.indices[csr.indptr[i]:csr.indptr[i + 1]].tolist(),
                     csr.data[csr.indptr[i]:csr.indptr[i + 1]].astype(int).tolist()))
            for i in range(csr.shape[0])
        ]
        return obj


# --- rank -------------------------------------------------------------------


def pagerank(
    n: int,
    edges: Sequence[Tuple[int, int]],
    *,
    damping: float = 0.85,
    tol: float = 1e-8,
    max_iter: int = 100,
) -> np.ndarray:
    """PageRank over integer-indexed nodes. Returns a length-`n` vector.

    Dangling nodes — chunks with no outgoing edge, which is most leaf content
    — have their mass redistributed uniformly rather than dropped. Dropping it
    silently rescales every score and makes the result depend on how much of
    the crawl happens to be complete, which is the opposite of what a
    structural prior should do.

    Power iteration, because the graph is sparse and n is around 10^5: an
    eigensolve would build a dense operator. Convergence is geometric in the
    damping factor, so ~50 iterations reach 1e-8 at 0.85.
    """
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    if not edges:
        return np.full(n, 1.0 / n, dtype=np.float32)

    src = np.fromiter((s for s, _ in edges), dtype=np.int64, count=len(edges))
    dst = np.fromiter((d for _, d in edges), dtype=np.int64, count=len(edges))
    keep = (src >= 0) & (src < n) & (dst >= 0) & (dst < n)
    src, dst = src[keep], dst[keep]
    if src.size == 0:
        return np.full(n, 1.0 / n, dtype=np.float32)

    out_degree = np.bincount(src, minlength=n).astype(np.float64)
    weights = 1.0 / out_degree[src]
    matrix = sparse.csr_matrix((weights, (dst, src)), shape=(n, n))
    dangling = out_degree == 0

    rank = np.full(n, 1.0 / n, dtype=np.float64)
    teleport = (1.0 - damping) / n
    for _ in range(max_iter):
        leaked = damping * rank[dangling].sum() / n
        nxt = damping * (matrix @ rank) + leaked + teleport
        if np.abs(nxt - rank).sum() < tol:
            rank = nxt
            break
        rank = nxt
    total = rank.sum()
    return (rank / total if total else rank).astype(np.float32)


# --- semantic ---------------------------------------------------------------


@dataclass
class EmbeddingMatrix:
    """Dense semantic vectors aligned to the same integer rows.

    Held in memory as one contiguous `(n, dim)` array rather than as a vector
    per chunk: scoring a query is then a single matrix-vector product instead
    of `n` dot products through `n` Python objects. The authoritative copy
    lives with the chunks in the graph store; this is the query-side view.
    """

    dim: int = 768
    rows: List[str] = field(default_factory=list)
    _row_of: Dict[str, int] = field(default_factory=dict)
    _matrix: Optional[np.ndarray] = None
    #: Row allocation and growth are a read-modify-write over shared state,
    #: and the sidecar is a `ThreadingHTTPServer` with an embedding worker
    #: beside it. Unlocked, two threads each grew a copy of the SAME stale
    #: matrix and the smaller assignment landed last, so the next write went
    #: past the end: `IndexError: index 13397 is out of bounds for axis 0
    #: with size 13397`, which took every `/search` down with it. Not
    #: hypothetical -- that is the traceback this lock was added for.
    _lock: "threading.RLock" = field(
        default_factory=threading.RLock, repr=False, compare=False)
    #: The allocation behind `_matrix`, which is a view of its used rows.
    _buf: Optional[np.ndarray] = field(default=None, repr=False, compare=False)

    def set(self, cid: str, vector: np.ndarray) -> int:
        vec = np.asarray(vector, dtype=np.float32).ravel()[: self.dim]
        norm = float(np.linalg.norm(vec))
        with self._lock:
            row = self._row_of.get(cid)
            if row is None:
                row = len(self.rows)
                self.rows.append(cid)
                self._row_of[cid] = row
            self._grow(row + 1)
            # Stored normalised so similarity is a plain dot product and a
            # zero vector (an un-embedded chunk) scores 0 rather than NaN.
            self._matrix[row, : vec.shape[0]] = vec / norm if norm else vec
        return row

    def _grow(self, n_rows: int) -> None:
        """Make room for `n_rows` rows, doubling the allocation.

        It grew by exactly the rows asked for, so every new chunk copied the
        whole matrix: O(n^2) over a load. Measured on 16k chunks, the query
        index's first build spent 146 s hydrating, and each vector embedded
        while browsing copied every row before it. `_matrix` stays a VIEW of
        the used rows, so `_matrix.shape[0]` still means rows in use and no
        reader changes.
        """
        used = 0 if self._matrix is None else self._matrix.shape[0]
        if n_rows <= used:
            return
        cap = 0 if self._buf is None else self._buf.shape[0]
        if n_rows > cap:
            grown = np.zeros((max(n_rows, 2 * cap, 1024), self.dim),
                             dtype=np.float32)
            if used:
                grown[:used] = self._matrix
            self._buf = grown
        self._matrix = self._buf[:n_rows]

    def forget(self, cids: Iterable[str]) -> int:
        """Zero and tombstone the rows of retired chunks. Returns how many.

        Zeroing alone was what a purge did, and it left the chunk id in
        `rows` and in `_row_of`. A chunk id is a hash of `(url, xpath, part)`,
        so anyone holding a url can recompute it and ask whether it is still
        there — a purged page answering "yes, I was here" is exactly the
        question a purge is supposed to make unanswerable. The row itself
        stays allocated, tombstoned like the frequency matrix's, because rows
        are the key the two matrices are aligned on.
        """
        gone = 0
        for cid in cids:
            row = self._row_of.pop(cid, None)
            if row is None:
                continue
            self.rows[row] = ""
            if self._matrix is not None and row < self._matrix.shape[0]:
                self._matrix[row] = 0.0
            gone += 1
        return gone

    def row_of(self, cid: str) -> Optional[int]:
        return self._row_of.get(cid)

    @property
    def matrix(self) -> np.ndarray:
        return (self._matrix if self._matrix is not None
                else np.zeros((0, self.dim), dtype=np.float32))

    def similarities(self, query_vector: np.ndarray) -> np.ndarray:
        """Cosine similarity of every row against a query vector."""
        if self._matrix is None or not self._matrix.shape[0]:
            return np.zeros(0, dtype=np.float32)
        vec = np.asarray(query_vector, dtype=np.float32).ravel()[: self.dim]
        norm = float(np.linalg.norm(vec))
        if not norm:
            return np.zeros(self._matrix.shape[0], dtype=np.float32)
        return self._matrix @ (vec / norm)


# --- the vectorisation queue ------------------------------------------------


@dataclass
class VectorQueue:
    """Streamed in per delta, flushed out in batches.

    Two prohibitions from OBJECT_MODEL 8 live here, and they are the whole
    reason this sits between the sensor and the embedder rather than the
    embedder being called where chunks arrive:

    * **Vectorisation may not run per delta.** A drain that changed one line
      of one chunk must not turn into an embedder call. Chunks are pushed by
      id and embedded when someone needs vectors, in batches.
    * **Markdown whose digest is unchanged may not be re-vectorised.** The
      chunk id is keyed on position, not content (`MarkdownChunk.cid`, ERRATA
      B10), so the same id legitimately carries different markdown over time
      and identity alone cannot answer this. The queue keeps the digest of
      what it last embedded and compares against that.

    Deduplication is by id with last write wins: a chunk rewritten five times
    between flushes is embedded once, with its final text. That is what makes
    the cost proportional to *settled* change rather than to churn -- a
    scrolling feed can rewrite a header on every frame and still cost one
    embedding.
    """

    pending: "OrderedDict[str, str]" = field(default_factory=OrderedDict)
    digests: Dict[str, str] = field(default_factory=dict)
    batch: int = 64

    # digest -> the vector that text embedded to, for text that arrives under
    # an id it has not worn before.
    #
    # The gate above is keyed on `cid`, and a cid is address-keyed (ERRATA
    # B12) precisely so that identity does not collapse where content is
    # absent -- a content key collapsed 18.8% of instances on the 54-page
    # corpus against the address's 0%. The cost of that correctness is churn:
    # an insertion shifts every address below it, so chunks arrive with new
    # ids carrying text embedded an hour ago, and the gate cannot recognise
    # them. Measured on an N-row list, an insertion left exactly one chunk
    # holding new text and still offered the whole page for embedding.
    #
    # Reuse resolves it without re-keying anything. An embedding is a function
    # of the text, so two chunks with the same markdown have the same vector,
    # and serving the second from the first is exact rather than approximate.
    vectors: "OrderedDict[str, object]" = field(default_factory=OrderedDict)
    # Bounded because it is a cache, not a store: the authoritative copy lives
    # with the chunks. Oldest out first, which keeps a page being edited
    # resident while a page left behind falls out.
    vector_cache: int = 4096
    reused: int = 0        # served from `vectors` instead of the embedder

    # counters, so the REPL can report the queue rather than infer it
    pushed: int = 0        # offered
    queued: int = 0        # accepted (digest moved)
    skipped: int = 0       # rejected by the digest gate
    embedded: int = 0      # actually sent to the embedder
    flushes: int = 0

    @staticmethod
    def digest(markdown: str) -> str:
        return hashlib.sha1(markdown.encode("utf-8")).hexdigest()[:16]

    def push(self, cid: str, markdown: str, *, url: str = "") -> bool:
        """Offer a chunk. True if it was queued, False if the gate stopped it.

        The chunk is embedded as **pure text with no link targets in it**.
        A rendered `[label](https://host/a/very/long/path)` puts an address
        into the sentence the encoder reads, and an address is not a sentence:
        over `build/vaultws256` those targets are 52.5% of every rendered
        token, so more than half of what the semantic encoder saw was machine
        addressing. The words of the label stay -- they are what the link
        means to a reader -- and the target is recoverable from the trie,
        which holds it under `url : xpath` and never needed a second copy in
        the prose.

        This is the SEMANTIC vector only. `vectors.tokens` deliberately
        expands a url into its path words for the frequency matrix, and that
        stays exactly as it is: a url tail is a legitimate TERM, and terms are
        what a lexical vector is made of. The two vectors want different
        strings out of one render, which is the whole reason there are two.

        Stripping here rather than at each caller means the digest gate keys
        on the string that is actually embedded, so a re-render that changed
        only an href correctly embeds nothing.
        """
        self.pushed += 1
        # `G-52`: a ``code://`` chunk gives the encoder its comments and
        # docstrings and not its code. `vertiscope.source` renders the file so
        # that this is a property of the render -- prose outside fences, code
        # inside -- so the whole of the requirement here is one flag.
        markdown = tokens_mod.for_model(
            markdown, drop_code=str(url or "").startswith("code://"))
        d = self.digest(markdown)
        if self.digests.get(cid) == d and cid not in self.pending:
            self.skipped += 1
            return False
        # Last write wins, and re-pushing moves nothing in the order: the
        # position of the first offer is kept so a long-lived chunk cannot be
        # starved by a churning neighbour.
        self.pending[cid] = markdown
        self.queued += 1
        return True

    def extend(self, chunks: Iterable) -> int:
        """Offer many chunks. Returns how many were queued."""
        return sum(1 for c in chunks
                   if self.push(c.cid, c.markdown,
                                url=getattr(c, "url", "")))

    def forget(self, cids: Iterable[str]) -> None:
        """Drop retired chunks, so a removed chunk is never embedded."""
        for cid in cids:
            self.pending.pop(cid, None)
            self.digests.pop(cid, None)

    def __len__(self) -> int:
        return len(self.pending)

    def prioritize(self, cids: Iterable[str]) -> int:
        """Move queued chunks to the FRONT, so the next flush embeds them
        first (`G-80`, hover-first). Returns how many were queued."""
        moved = 0
        for cid in reversed(list(cids)):
            if cid in self.pending:
                self.pending.move_to_end(cid, last=False)
                moved += 1
        return moved

    def flush(self, embedder, *, limit: Optional[int] = None
              ) -> Dict[str, np.ndarray]:
        """Embed what is queued, `batch` at a time. Returns cid -> vector.

        Nothing is marked as embedded until its vectors are actually in hand,
        so a failure mid-flush leaves the unfinished ids queued rather than
        silently dropping them.
        """
        if embedder is None or not self.pending:
            return {}
        return self.embed(embedder, self.take(limit))

    def take(self, limit: Optional[int] = None) -> List[Tuple[str, str]]:
        """Pop up to `limit` queued (cid, markdown) pairs, oldest first.

        Split from `embed` so a caller can hold its store lock for the pop
        and the write only -- not for the encoder, which is the slow part
        (D-35: a new page's capture waited 8.8 s behind the page left
        behind being encoded under the lock).
        """
        take = len(self.pending) if limit is None else min(limit, len(self.pending))
        return [self.pending.popitem(last=False) for _ in range(take)]

    def requeue(self, items: List[Tuple[str, str]]) -> None:
        """Put taken items back at the FRONT, unless a newer text was queued
        for the same chunk meanwhile (that one wins)."""
        for cid, md in reversed(items):
            if cid in self.pending:
                continue
            self.pending[cid] = md
            self.pending.move_to_end(cid, last=False)

    def embed(self, embedder, items: List[Tuple[str, str]]
              ) -> Dict[str, np.ndarray]:
        """Vectors for taken items. Touches the embedder and this queue's own
        digest cache, never `pending` -- safe outside the caller's lock while
        other threads queue more. On failure the items go back, then it raises."""
        if embedder is None or not items:
            return {}
        try:
            return self._embed(embedder, items)
        except Exception:
            self.requeue(items)
            raise

    def _embed(self, embedder, items: List[Tuple[str, str]]
               ) -> Dict[str, np.ndarray]:
        out: Dict[str, np.ndarray] = {}

        # Text already embedded under some other id needs a row, not a call.
        needed: List[Tuple[str, str]] = []
        for cid, md in items:
            digest = self.digest(md)
            known = self.vectors.get(digest)
            if known is None:
                needed.append((cid, md))
                continue
            out[cid] = known
            self.digests[cid] = digest
            self.vectors.move_to_end(digest)
            self.reused += 1

        for i in range(0, len(needed), self.batch):
            window = needed[i:i + self.batch]
            matrix = embedder.embed_texts([md for _cid, md in window])
            for (cid, md), vector in zip(window, matrix):
                digest = self.digest(md)
                out[cid] = vector
                self.digests[cid] = digest
                self.vectors[digest] = vector
                self.vectors.move_to_end(digest)
                self.embedded += 1
        while len(self.vectors) > self.vector_cache:
            self.vectors.popitem(last=False)
        self.flushes += 1
        return out

    def report(self) -> Dict[str, int]:
        return {"pending": len(self.pending), "pushed": self.pushed,
                "queued": self.queued, "skipped": self.skipped,
                "embedded": self.embedded, "reused": self.reused,
                "flushes": self.flushes}
