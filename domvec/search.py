"""Three-form retrieval: PageRank x frequency x semantic.

The mortegon ranking rule is the **triple product**

    score(c) = pagerank(c) * tfidf_cos(q, c) * nomic_cos(q, c)

with the two vector axes kept apart on purpose: the frequency axis runs over
the rendered text and the semantic axis over meaning, and mixing them into one
vector would let a lexical match dilute a semantic one and vice versa. Keeping
them as separate factors means each retains a veto.

That veto is the rule's whole character, and it is sharp. A product is zero if
any factor is zero, so a chunk with no term in common with the query scores
zero *however* well it matches semantically. That is sometimes right — it is
what stops a general-purpose embedding from dragging in loosely-related
content — and sometimes wrong, since it makes pure paraphrase unfindable.

Rather than quietly soften it, this module:

* computes the strict product as specified;
* records how many candidates each factor zeroed, in
  :class:`SearchDiagnostics`, so the veto's cost is visible per query;
* offers ``floor`` as an explicit, off-by-default smoothing term, so choosing
  to soften it is a decision someone made rather than a default nobody saw.

Alignment
---------
All three factors are arrays indexed by the same integer row: the frequency
matrix hands out the row, the embedding matrix and the PageRank vector are
built against it. Scoring a query is three array reads and a multiply, with no
per-candidate lookup.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from .graphstore import GraphStore
from .trie import content_hash
from .vectors import EmbeddingMatrix, FreqMatrix, pagerank

__all__ = ["Hit", "SearchDiagnostics", "ThreeFormIndex"]


@dataclass
class Hit:
    """One ranked chunk, with the three factors that produced its score."""

    cid: str
    url: str
    xpath: str
    score: float
    rank: float
    lexical: float
    semantic: float
    markdown: str = ""

    def preview(self, lines: int = 3) -> str:
        return "\n".join(self.markdown.split("\n")[:lines])


#: Planted: duplicates keyed on the stored markdown (empty for chunks the
#: store lost, so they all collapse into one).
_PLANT_MD_DIGEST = [False]


@dataclass
class SearchDiagnostics:
    """What each factor did to the candidate set.

    A ranking whose factors are multiplied can return nothing for reasons that
    look identical from the outside — no match, or one factor vetoing every
    match. These counts distinguish them.
    """

    candidates: int = 0
    zeroed_by_lexical: int = 0
    zeroed_by_semantic: int = 0
    zeroed_by_rank: int = 0
    survivors: int = 0
    collapsed: int = 0
    semantic_available: bool = False
    #: The code pre-filter (R-6): partitions total and kept, rows masked.
    code_partitions: Optional[dict] = None
    #: Where a search's time went, ms per phase, and how many store reads the
    #: selection made (2026-10-17: "retrieval takes quite a long time" --
    #: ~1 s whether ranking the corpus or one page).
    ms: Optional[dict] = None
    select_reads: int = 0
    #: The chunks the selection read, by cid -- handed on so the caller does
    #: not read them again.
    read_chunks: Optional[dict] = None
    #: The fused score per row, kept by a ``count_only`` search so tier 1 can
    #: rank pages by what they actually hold.
    score: Optional[object] = None

    def summary(self) -> Dict[str, object]:
        return {
            "candidates": self.candidates,
            "zeroed_by_lexical": self.zeroed_by_lexical,
            "zeroed_by_semantic": self.zeroed_by_semantic,
            "zeroed_by_rank": self.zeroed_by_rank,
            "survivors": self.survivors,
            "collapsed": self.collapsed,
            "semantic_available": self.semantic_available,
        }


class ThreeFormIndex:
    """Query surface over a graph store, a frequency matrix and embeddings."""

    def __init__(
        self,
        store: GraphStore,
        freq: FreqMatrix,
        embeddings: Optional[EmbeddingMatrix] = None,
        *,
        embedder=None,
    ) -> None:
        self.store = store
        self.freq = freq
        self.embeddings = embeddings
        self.embedder = embedder
        self._ranks: Optional[np.ndarray] = None
        self._meta: Dict[int, Tuple[str, str, str]] = {}
        self._live: Optional[np.ndarray] = None

    # -- build -------------------------------------------------------------
    def build(self) -> "ThreeFormIndex":
        """Compute PageRank and cache row metadata. Call after ingest."""
        row_of = {cid: i for i, cid in enumerate(self.freq.rows)}
        n = len(self.freq.rows)

        edges = [
            (row_of[a], row_of[b])
            for a, b in self.store.edges()
            if a in row_of and b in row_of
        ]
        self._ranks = pagerank(n, edges)

        self._meta = {}
        self._cid_row = None
        # Each row's content hash, from the markdown this build reads anyway:
        # the duplicate collapse needs only this, so a search reads the store
        # for the hits it KEEPS and nothing else (it read every candidate --
        # 50-117 reads a query, seconds to minutes on a 65k-chunk store,
        # 2026-10-17).
        self._digests = {}
        for chunk in self.store.chunks():
            row = row_of.get(chunk.cid)
            if row is not None:
                self._meta[row] = (chunk.cid, chunk.url, chunk.xpath)
                self._digests[row] = self._row_digest(row, getattr(chunk, "md", "") or "")

        # Rows that describe nothing. A retired row (see FreqMatrix.remove)
        # keeps its slot so the other rows are not renumbered, and it scores
        # zero on the lexical factor — which hides it only while the product
        # is strict. Under `floor` every factor gets a positive term, so a
        # tombstone came back as a hit with an empty cid, empty url and empty
        # markdown: a phantom result pointing at nothing, produced by the
        # option a user reaches for when they are already getting too few
        # answers. Masking here removes them from every path at once.
        self._live = np.ones(n, dtype=np.float32)
        for row in range(n):
            if not self.freq.rows[row] or row not in self._meta:
                self._live[row] = 0.0
        return self

    def apply_delta(self, cids) -> Dict[str, int]:
        """Bring the index up to date for the chunks a capture wrote or
        retired -- O(delta), not O(corpus).

        Every capture used to throw the index away, and the next search
        rebuilt it: every chunk read back from the store for its metadata,
        PageRank over every edge -- 2-9 s of wall time on each search while a
        page streamed (2026-10-18, PLUGIN_GOAL 152: "retrieval is also back to
        a slow response"). The trie's change is the delta: only those rows are
        re-read. A row new to the index takes the mean PageRank until the next
        full build (a zero would veto it under the product); the full build
        runs off the request path.
        """
        if self._ranks is None:
            self.build()
            return {"rebuilt": 1}
        n = len(self.freq.rows)
        if n > len(self._ranks):
            pos = self._ranks[self._ranks > 0]
            fill = float(pos.mean()) if pos.size else 1.0 / max(n, 1)
            self._ranks = np.concatenate([self._ranks, np.full(n - len(self._ranks), fill, dtype=self._ranks.dtype)])
        if self._live is None or n > len(self._live):
            grow = n - (0 if self._live is None else len(self._live))
            self._live = np.concatenate([self._live if self._live is not None else np.zeros(0, dtype=np.float32),
                                         np.zeros(grow, dtype=np.float32)])
        cid_row = getattr(self, "_cid_row", None)
        if cid_row is None:
            cid_row = self._cid_row = {m[0]: r for r, m in self._meta.items() if m}
        cids = [c for c in set(cids or ()) if c]
        many = getattr(self.store, "chunks_many", None)
        got = many(cids) if (many and cids) else {c: self.store.chunk(c) for c in cids}
        pos = self._ranks[self._ranks > 0]
        fill = float(pos.mean()) if pos.size else 1.0 / max(n, 1)
        added = retired = 0
        for cid in cids:
            old = cid_row.pop(cid, None)
            # Only while the row still names THIS chunk: a freed row reused by
            # another chunk in the same delta must not be wiped by the retired
            # one (the order of a set decided it).
            if old is not None and old < n and (self._meta.get(old) or ("",))[0] == cid:
                self._meta.pop(old, None); self._digests.pop(old, None); self._live[old] = 0.0
            row = self.freq._row_of.get(cid)
            chunk = got.get(cid) if got else None
            if row is None or chunk is None or not self.freq.rows[row]:
                retired += 1
                continue
            self._meta[row] = (chunk.cid, chunk.url, chunk.xpath)
            self._digests[row] = self._row_digest(row, getattr(chunk, "md", "") or "")
            self._live[row] = 1.0
            if self._ranks[row] <= 0:
                self._ranks[row] = fill
            cid_row[cid] = row
            added += 1
        self._emb_rows = None                       # a reused row may map elsewhere now
        return {"rows": added, "retired": retired}

    def _row_digest(self, row: int, md: str) -> str:
        """The duplicate key of a row: its token multiset, as `content_hash`
        means -- read from the lexical row the index already holds, which
        exists for every indexed chunk. Hashing the STORED markdown keyed
        every chunk whose markdown the store lost (67,040 of 70,083,
        2026-10-18) on the empty string, so all of them were one "duplicate"
        and a page with 457 matches returned 1 (PLUGIN_GOAL 152/154). A row
        with no tokens and no markdown is unique: nothing is not a copy of
        nothing. Planted `_PLANT_MD_DIGEST`: the stored markdown, as before.
        """
        if _PLANT_MD_DIGEST[0]:
            return content_hash(md)
        counts = self.freq._counts[row] if 0 <= row < len(self.freq._counts) else None
        if counts:
            import hashlib
            return "t:" + hashlib.blake2b(repr(sorted(counts.items())).encode(), digest_size=12).hexdigest()
        if md.strip():
            return content_hash(md)
        return "row:%d" % row

    @property
    def ranks(self) -> np.ndarray:
        if self._ranks is None:
            self.build()
        return self._ranks if self._ranks is not None else np.zeros(0)

    # -- query -------------------------------------------------------------
    def search(
        self,
        query: str,
        k: int = 10,
        *,
        floor: float = 0.0,
        weights: Tuple[float, float, float] = (1.0, 1.0, 1.0),
        diagnostics: Optional[SearchDiagnostics] = None,
        include_markdown: bool = True,
        collapse: bool = True,
        fuse: str = "product",
        scope_url: str = "",
        count_only: bool = False,
    ) -> List[Hit]:
        """Rank chunks by the triple product.

        ``count_only`` stops once the corpus-wide match count is known
        (``diagnostics.survivors``) and reads no chunk: tier 1 of a tiered
        search reports it as the k/n fields' bound (PLUGIN_GOAL 154).


        ``weights`` are exponents, not coefficients: the product is
        ``rank**wr * lexical**wl * semantic**ws``. Exponents because the
        factors are on incomparable scales — PageRank sums to one over the
        corpus while a cosine is bounded by one per query — so adding a
        coefficient would just rescale a factor that is already dominated,
        whereas an exponent changes how sharply it discriminates.

        ``floor`` is added to each factor before multiplying. At 0.0 the rule
        is the strict product, and every factor keeps its veto.
        """
        rows = len(self.freq.rows)
        diag = diagnostics if diagnostics is not None else SearchDiagnostics()
        diag.candidates = rows
        if not rows:
            return []

        import time as _time
        _t = _time.perf_counter()
        ms = diag.ms = {}
        def _lap(name):
            nonlocal _t
            now = _time.perf_counter()
            ms[name] = round((now - _t) * 1000, 1)
            _t = now
        # The query's two factors over every row, memoised per QUERY: a tiered
        # search asks one query scoped to page after page (G-210), and each
        # scoped call recomputed both over all 62k rows only to mask to one
        # page. A function of the query, the counts (`freq.version`) and the
        # vectors (the matrix's size) -- named in the key, so a change in any
        # recomputes (CLAUDE.md 5c).
        emb_n = int(self.embeddings.matrix.shape[0]) if (self.embeddings is not None
                                                          and self.embeddings.matrix is not None) else 0
        fkey = (query, rows, getattr(self.freq, "version", 0), emb_n, id(self.embedder))
        memo = getattr(self, "_factor_memo", None)
        if memo is not None and memo[0] == fkey and not getattr(self, "plant_no_factor_memo", False):
            lexical, semantic, available = memo[1]
            ms["memo"] = 1
        else:
            lexical = self.freq.similarities(query)
            lexical = _fit(lexical, rows)
            _lap("lexical")
            semantic, available = self._semantic(query, rows)
            self._factor_memo = (fkey, (lexical, semantic, available))
        diag.semantic_available = available
        _lap("semantic")

        ranks = _fit(self.ranks, rows)

        diag.zeroed_by_lexical = int(np.sum(lexical <= 0))
        diag.zeroed_by_semantic = int(np.sum(semantic <= 0)) if available else 0
        diag.zeroed_by_rank = int(np.sum(ranks <= 0))

        wr, wl, ws = weights
        # `fuse` is the retrieval side's first axis. The product is the
        # design's rule and keeps every factor's veto — a zero anywhere is a
        # zero overall, which is correct when all three factors are
        # trustworthy and catastrophic when one is merely missing. `sum` and
        # `rrf` are the two standard alternatives, so the choice can be
        # measured rather than defended.
        if fuse == "sum":
            # No vetoes: a factor that is merely missing costs its share
            # instead of the whole hit.
            score = wr * (ranks + floor) + wl * (lexical + floor)
            if available:
                score = score + ws * (semantic + floor)
        elif fuse == "rrf":
            # Reciprocal rank fusion: position, not magnitude, so factors on
            # incomparable scales need no exponent to be comparable.
            def _rr(v):
                return 1.0 / (60.0 + np.argsort(np.argsort(-v)) + 1.0)
            score = wr * _rr(ranks) + wl * _rr(lexical)
            if available:
                score = score + ws * _rr(semantic)
        else:
            score = (np.power(ranks + floor, wr)
                     * np.power(lexical + floor, wl))
            if available:
                score = score * np.power(semantic + floor, ws)
        score = np.asarray(score, dtype=np.float64)
        # Retired rows describe nothing and must never be returned, whatever
        # the floor makes their factors look like.
        score = score * _fit(self._live if self._live is not None
                             else np.ones(rows, dtype=np.float32), rows)
        _lap("fuse")

        # `scope_url` ranks WITHIN a page, which a filter cannot do.
        #
        # Scoping used to be a post-filter over a global top-k, widened to
        # `chunk_count(url) * 3` and bounded at 4,000 so that scoping a large
        # page did not rank the corpus end to end. On a 14,169-chunk corpus
        # that bound is the defect: RFC 9110's 1,173 chunks rank below 3,519
        # globally, so scoping to it returned **0 hits for every query**
        # while the page is the largest in the store. Masking the score
        # instead is exact and costs one pass -- the ranking is over the
        # page's own chunks, which is what "scoped" means.
        if scope_url:
            mask = np.zeros(rows, dtype=np.float32)
            mask[self._rows_of_url(scope_url, rows)] = 1.0
            score = score * mask

        # **Package retrieval: a vector-centroid pre-filter, then partition-wise
        # ranking** (R-6). Each code root -- `code://pypi/<package>`,
        # `code://repo` -- is a partition, its centroid the mean of its rows'
        # embeddings; the query keeps the `CODE_PARTITIONS` partitions whose
        # centroids are nearest it and ranks code only within those. Web and
        # vault rows are untouched, and it is a mask inside THIS ranking: the
        # filter is not a second interface.
        if available and self.code_partitions > 0 and not scope_url:
            score = self._prefilter_code(score, rows, diag)

        _lap("scope_and_code")
        diag.survivors = int(np.sum(score > 0))
        if count_only:
            diag.score = score
            return []
        if diag.survivors == 0:
            return []

        # Take more than k before collapsing duplicates: identical content at
        # different addresses scores identically, so an uncollapsed top-k can
        # be the same text k times. Observed on the corpus — the top three
        # hits for one query were three copies of "<https://schema.org/Book>".
        order = np.argsort(-score)
        hits: List[Hit] = []
        seen_content: set = set()
        digests = getattr(self, "_digests", None) or {}
        # The rows KEPT (collapse by the build's content hashes -- no reads),
        # then ONE read of just those, when markdown is wanted.
        kept_rows = []
        for row in order:
            if score[row] <= 0 or len(kept_rows) >= max(k, 0):
                break
            if collapse:
                fp = digests.get(int(row))
                if fp is None:
                    meta = self._meta.get(int(row))
                    got = self.store.chunk(meta[0] if meta else self.freq.rows[int(row)])
                    diag.select_reads += 1
                    fp = content_hash(got.md if got else "")
                if fp in seen_content:
                    diag.collapsed += 1
                    continue
                seen_content.add(fp)
            kept_rows.append(int(row))
        block: Dict[str, object] = {}
        if include_markdown and kept_rows:
            cids = [(self._meta.get(r) or (self.freq.rows[r],))[0] for r in kept_rows]
            many = getattr(self.store, "chunks_many", None)
            block = many(cids) if many else {c: self.store.chunk(c) for c in cids}
            diag.select_reads += 1
            diag.read_chunks = dict(block)
        for row in kept_rows:
            meta = self._meta.get(int(row))
            cid = meta[0] if meta else self.freq.rows[int(row)]
            url, xpath = (meta[1], meta[2]) if meta else ("", "")
            stored = block.get(cid) if include_markdown else None
            markdown = stored.md if stored else ""
            # (Collapsed above, keyed on the text's hash, not on an embedding:
            # the spec is explicit that deduplication must not use embeddings.)
            hits.append(Hit(
                cid=cid, url=url, xpath=xpath,
                score=float(score[row]), rank=float(ranks[row]),
                lexical=float(lexical[row]), semantic=float(semantic[row]),
                markdown=markdown if include_markdown else "",
            ))
        _lap("select")
        return hits

    #: How many code partitions a query ranks within (R-6); 0 = no pre-filter.
    code_partitions = 3

    def _code_partitions(self, rows: int):
        """row -> partition index, and each partition's unit centroid: cached
        against both matrices' sizes, like `_embedding_rows`."""
        key = (rows, int(self.embeddings.matrix.shape[0]) if self.embeddings.matrix is not None else 0)
        got = getattr(self, "_code_parts", None)
        if got is not None and got[0] == key:
            return got[1], got[2], got[3]
        part = np.full(rows, -1, dtype=np.int64)
        names: List[str] = []
        index: Dict[str, int] = {}
        for row, meta in self._meta.items():
            r = int(row)
            if not meta or not (0 <= r < rows):
                continue
            url = meta[1] or ""
            if not url.startswith("code://"):
                continue
            rest = url[len("code://"):].split("/")
            root = "code://" + (rest[0] + "/" + rest[1] if rest[0] == "pypi" and len(rest) > 1 else rest[0])
            if root not in index:
                index[root] = len(names)
                names.append(root)
            part[r] = index[root]
        cents = None
        if names and self.embeddings.matrix is not None:
            emb = self._embedding_rows(rows)
            M = self.embeddings.matrix
            dim = M.shape[1]
            sums = np.zeros((len(names), dim), dtype=np.float64)
            for r in np.nonzero(part >= 0)[0]:
                e = emb[r]
                if 0 <= e < M.shape[0]:
                    v = np.asarray(M[e], dtype=np.float64)
                    nrm = np.linalg.norm(v)
                    if nrm > 1e-12:
                        sums[part[r]] += v / nrm
            nrm = np.linalg.norm(sums, axis=1, keepdims=True)
            cents = sums / np.maximum(nrm, 1e-12)
        self._code_parts = (key, part, names, cents)
        return part, names, cents

    def _prefilter_code(self, score: np.ndarray, rows: int, diag) -> np.ndarray:
        part, names, cents = self._code_partitions(rows)
        qv = getattr(self, "_last_query_vector", None)
        if cents is None or qv is None or len(names) <= self.code_partitions:
            diag.code_partitions = {"total": len(names), "kept": len(names)}
            return score
        q = np.asarray(qv, dtype=np.float64)
        q = q / max(np.linalg.norm(q), 1e-12)
        sims = cents @ q
        keep = set(np.argsort(-sims)[: self.code_partitions].tolist())
        mask = np.ones(rows, dtype=np.float32)
        drop = (part >= 0) & ~np.isin(part, list(keep))
        mask[drop] = 0.0
        diag.code_partitions = {"total": len(names), "kept": len(keep),
                                "kept_names": [names[i] for i in sorted(keep)],
                                "rows_masked": int(np.sum(drop))}
        return score * mask

    def _semantic(self, query: str, rows: int) -> Tuple[np.ndarray, bool]:
        """Semantic similarities, and whether they are real.

        Returns ``available=False`` rather than a plausible-looking array of
        zeros when no embedder is configured. A caller that cannot tell the
        difference would report a two-factor ranking as a three-factor one,
        which is the quiet degradation this codebase treats as the
        anti-pattern.
        """
        if self.embeddings is None or self.embedder is None:
            return np.zeros(rows, dtype=np.float32), False
        try:
            vector = self.embedder.embed_query(query)
        except Exception:
            return np.zeros(rows, dtype=np.float32), False
        self._last_query_vector = vector
        sims = self.embeddings.similarities(vector)
        # **Joined on cid, not on row number.** `similarities` answers in
        # the EMBEDDING matrix's row order -- the order vectors arrived in --
        # and every other factor here is in FREQUENCY-row order. They agree
        # on a corpus built in one pass and nowhere else: the frequency
        # matrix reclaims retired rows and gains rows from repair, while the
        # embedding matrix appends. Read positionally, a chunk was scored
        # with another chunk's similarity -- measured live, 4,724 rows
        # repaired in one start-up and pages captured that afternoon
        # unreachable by their own name.
        emb_rows = self._embedding_rows(rows)
        out = np.zeros(rows, dtype=np.float32)
        have = emb_rows >= 0
        have &= emb_rows < sims.shape[0]
        out[have] = sims[emb_rows[have]]
        # cosine is in [-1, 1]; a negative similarity is not "less relevant
        # than nothing", it is opposition, and raising a negative to a
        # fractional exponent is undefined. Clamp at zero and let the veto
        # apply.
        return np.maximum(out, 0.0), True

    def _embedding_rows(self, rows: int) -> np.ndarray:
        """For each frequency row, its row in the embedding matrix, or -1.

        Cached against both matrices' sizes: either growing means new rows
        whose mapping is not known yet.
        """
        key = (rows, int(self.embeddings.matrix.shape[0])
               if self.embeddings.matrix is not None else 0)
        cached = getattr(self, "_emb_rows", None)
        if cached is not None and cached[0] == key:
            return cached[1]
        mapping = np.full(rows, -1, dtype=np.int64)
        for i, cid in enumerate(self.freq.rows[:rows]):
            if cid:
                got = self.embeddings.row_of(cid)
                if got is not None:
                    mapping[i] = got
        self._emb_rows = (key, mapping)
        return mapping

    def _rows_of_url(self, url: str, rows: int) -> np.ndarray:
        """A url's frequency rows, from an index built once per content
        change -- not a loop over every row per scoped search."""
        key = (rows, len(self._meta), getattr(self.freq, "version", 0))
        got = getattr(self, "_url_rows", None)
        if got is None or got[0] != key:
            by: Dict[str, List[int]] = {}
            for row, meta in self._meta.items():
                if meta and 0 <= int(row) < rows:
                    by.setdefault(meta[1], []).append(int(row))
            got = self._url_rows = (key, {u: np.asarray(r, dtype=np.int64) for u, r in by.items()})
        return got[1].get(url, np.zeros(0, dtype=np.int64))

    # -- tier 1: url nodes (G-210) ----------------------------------------
    def search_pages_matching(self, query: str, k: int = 10, *,
                              diagnostics: Optional[SearchDiagnostics] = None) -> List[Tuple[str, float]]:
        """Tier 1 ranked by what each page HOLDS for this query: a page's
        best fused chunk score -- the very ranking tier 2 runs per page -- and
        the corpus-wide match count in ``diagnostics.survivors``. One pass over
        the rows, no chunk read.

        The centroid ranking (`search_pages`) chose pages near the query in
        meaning that held no chunk the product lets through: for "the", a
        Cloudflare challenge and an mp3 stream, each answering 0 in tier 2, and
        37 results retrieved of 5,000 asked (2026-10-18, PLUGIN_GOAL 154).
        """
        diag = diagnostics if diagnostics is not None else SearchDiagnostics()
        self.search(query, 1, diagnostics=diag, count_only=True)
        score = getattr(diag, "score", None)
        if score is None or not diag.survivors:
            return []
        rows = int(len(score))
        best: Dict[str, float] = {}
        count: Dict[str, int] = {}
        hit_rows = np.nonzero(score > 0)[0]
        for row in hit_rows:
            meta = self._meta.get(int(row))
            if not meta or not meta[1]:
                continue
            v = float(score[int(row)])
            count[meta[1]] = count.get(meta[1], 0) + 1
            if v > best.get(meta[1], 0.0):
                best[meta[1]] = v
        top = sorted(best.items(), key=lambda kv: -kv[1])[:max(1, int(k))]
        diag.score = None
        # Each page's own match count rides along: a caller asking for n
        # results takes pages until their counts cover n (for "the", 31,413
        # matches spread one or two a page -- twelve pages gave 18).
        self.last_page_counts = {u: count[u] for u, _ in top}
        return top

    def page_centroids(self):
        """Each url's semantic centroid: the normalised mean of its chunks'
        unit vectors -- the url node a tiered search ranks first (2026-10-17,
        PLUGIN_GOAL 137/142: "retrieval new URL nodes and re-rank, then
        retrieve their containing chunks and re-rank"). Cached against both
        matrices' sizes and the lexical version: content changing anywhere
        changes one of the three."""
        rows = len(self.freq.rows)
        emb = self.embeddings.matrix if self.embeddings is not None else None
        key = (rows, int(emb.shape[0]) if emb is not None else 0, getattr(self.freq, "version", 0))
        got = getattr(self, "_page_cent", None)
        if got is not None and got[0] == key:
            return got[1], got[2]
        if emb is None or not rows:
            self._page_cent = (key, [], np.zeros((0, 0), dtype=np.float32))
            return [], self._page_cent[2]
        emb_rows = self._embedding_rows(rows)
        url_of_row = {}
        for row, meta in self._meta.items():
            if meta and 0 <= int(row) < rows and emb_rows[int(row)] >= 0 and meta[1]:
                url_of_row[int(row)] = meta[1]
        urls = sorted(set(url_of_row.values()))
        index = {u: i for i, u in enumerate(urls)}
        if not urls:
            self._page_cent = (key, [], np.zeros((0, emb.shape[1]), dtype=np.float32))
            return [], self._page_cent[2]
        sel = np.fromiter(url_of_row.keys(), dtype=np.int64)
        which = np.fromiter((index[url_of_row[int(r)]] for r in sel), dtype=np.int64)
        vecs = np.asarray(emb[emb_rows[sel]], dtype=np.float32)
        norms = np.linalg.norm(vecs, axis=1, keepdims=True)
        vecs = vecs / np.maximum(norms, 1e-9)
        cent = np.zeros((len(urls), emb.shape[1]), dtype=np.float32)
        np.add.at(cent, which, vecs)
        cent /= np.maximum(np.linalg.norm(cent, axis=1, keepdims=True), 1e-9)
        self._page_cent = (key, urls, cent)
        return urls, cent

    def search_pages(self, query: str, k: int = 10) -> List[Tuple[str, float]]:
        """Tier 1: the url nodes nearest the query, by their centroid -- one
        query embedding and one product over the pages, not a ranking of
        every chunk."""
        if self.embeddings is None or self.embedder is None:
            return []
        urls, cent = self.page_centroids()
        if not urls:
            return []
        qv = np.asarray(self.embedder.embed_query(query), dtype=np.float32).ravel()
        qv = qv / max(float(np.linalg.norm(qv)), 1e-9)
        sims = cent @ qv
        top = np.argsort(-sims)[:max(1, int(k))]
        return [(urls[int(i)], float(sims[int(i)])) for i in top]

    # -- navigation --------------------------------------------------------
    def addresses_for(self, cid: str):
        """The addresses a hit covers — the link back into the document."""
        return self.store.addresses_of(cid)


def _fit(values: np.ndarray, rows: int) -> np.ndarray:
    """Pad or trim to the row count, so the three factors always align.

    They can drift apart legitimately — a chunk indexed but not yet embedded,
    or a PageRank computed before the last ingest — and a silent length
    mismatch would either raise deep inside numpy or, worse, broadcast.
    """
    values = np.asarray(values, dtype=np.float32).ravel()
    if values.shape[0] == rows:
        return values
    out = np.zeros(rows, dtype=np.float32)
    n = min(rows, values.shape[0])
    out[:n] = values[:n]
    return out
