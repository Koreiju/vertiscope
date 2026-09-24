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
        for chunk in self.store.chunks():
            row = row_of.get(chunk.cid)
            if row is not None:
                self._meta[row] = (chunk.cid, chunk.url, chunk.xpath)

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
    ) -> List[Hit]:
        """Rank chunks by the triple product.

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

        lexical = self.freq.similarities(query)
        lexical = _fit(lexical, rows)

        semantic, available = self._semantic(query, rows)
        diag.semantic_available = available

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
            for row, meta in self._meta.items():
                if meta and meta[1] == scope_url and 0 <= int(row) < rows:
                    mask[int(row)] = 1.0
            score = score * mask

        diag.survivors = int(np.sum(score > 0))
        if diag.survivors == 0:
            return []

        # Take more than k before collapsing duplicates: identical content at
        # different addresses scores identically, so an uncollapsed top-k can
        # be the same text k times. Observed on the corpus — the top three
        # hits for one query were three copies of "<https://schema.org/Book>".
        order = np.argsort(-score)
        hits: List[Hit] = []
        seen_content: set = set()
        for row in order:
            if score[row] <= 0 or len(hits) >= max(k, 0):
                break
            meta = self._meta.get(int(row))
            cid = meta[0] if meta else self.freq.rows[int(row)]
            url, xpath = (meta[1], meta[2]) if meta else ("", "")
            stored = self.store.chunk(cid) if (include_markdown or collapse) else None
            markdown = stored.md if stored else ""
            if collapse:
                # Keyed on the text, not on an embedding: the spec is explicit
                # that deduplication must not use embeddings, and it does not
                # need to — identical renderings are identical strings.
                fingerprint = content_hash(markdown)
                if fingerprint in seen_content:
                    diag.collapsed += 1
                    continue
                seen_content.add(fingerprint)
            hits.append(Hit(
                cid=cid, url=url, xpath=xpath,
                score=float(score[row]), rank=float(ranks[row]),
                lexical=float(lexical[row]), semantic=float(semantic[row]),
                markdown=markdown if include_markdown else "",
            ))
        return hits

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
