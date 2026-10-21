"""Query → ranked chunk instances.

Two ranking surfaces, matching the original design's separation:

* **TF-IDF** over ``rendered_text`` — always on, no model needed, fast.
* **nomic embeddings** (optional, ``--semantic``) — reranks the TF-IDF
  candidate pool by cosine similarity. Requires the GPT4All nomic GGUF;
  if it can't load we say so and fall back rather than silently degrading.

The rerank is deliberately a *rerank*, not a second index: embedding the
whole corpus on every scan costs seconds per page for a retrieval quality
gain that only matters near the top of the list.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import List, Optional, Sequence

from .store import InstanceRecord, Store

logger = logging.getLogger(__name__)


@dataclass
class Hit:
    """One ranked retrieval result."""

    rank: int
    instance_id: str
    url: str
    score: float
    lexical_score: float
    semantic_score: Optional[float]
    pattern: str
    text: str
    record: Optional[InstanceRecord] = None

    def preview(self, width: int = 160) -> str:
        flat = " ".join((self.text or "").split())
        return flat[:width] + ("…" if len(flat) > width else "")


class SemanticUnavailable(RuntimeError):
    """The nomic embedder could not be loaded."""


class Retriever:
    """Ranked retrieval over an indexed :class:`~vertiscope.store.Store`."""

    def __init__(self, store: Store):
        self.store = store
        self._embedder = None

    # -- lexical ----------------------------------------------------------
    def search(
        self,
        query: str,
        k: int = 10,
        urls: Optional[Sequence[str]] = None,
        *,
        semantic: bool = False,
        candidate_factor: int = 4,
    ) -> List[Hit]:
        """Return up to ``k`` hits, most relevant first.

        With ``semantic=True`` the TF-IDF stage retrieves ``k *
        candidate_factor`` candidates which are then reranked by embedding
        cosine — so the embedder only ever sees a few dozen texts.
        """
        if not (query or "").strip():
            return []

        pool = k * candidate_factor if semantic else k
        raw = self.store.search(query, k=max(pool, k), urls=urls)
        if not raw:
            return []

        records = self.store.get_instances([h.chunk_id for h in raw])

        hits: List[Hit] = []
        for h in raw:
            rec = records.get(h.chunk_id)
            text = rec.rendered_text if rec else (h.meta.text_preview or "")
            hits.append(
                Hit(
                    rank=0,
                    instance_id=h.chunk_id,
                    url=(rec.url if rec else h.meta.url),
                    score=float(h.score),
                    lexical_score=float(h.score),
                    semantic_score=None,
                    pattern=(rec.pattern if rec else h.meta.pattern),
                    text=text,
                    record=rec,
                )
            )

        if semantic:
            hits = self._rerank(query, hits)

        hits = hits[:k]
        for i, hit in enumerate(hits, 1):
            hit.rank = i
        return hits

    # -- semantic ---------------------------------------------------------
    def _load_embedder(self):
        if self._embedder is None:
            try:
                from .core.embedding_service import EmbeddingService

                self._embedder = EmbeddingService(
                    device=self.store.cfg.embed_device
                )
            except Exception as exc:  # noqa: BLE001
                raise SemanticUnavailable(
                    f"nomic embedder unavailable ({type(exc).__name__}: {exc}). "
                    "Run without --semantic for TF-IDF ranking."
                ) from exc
        return self._embedder

    def _rerank(self, query: str, hits: List[Hit]) -> List[Hit]:
        """Rerank by embedding cosine, blended with the lexical score."""
        import numpy as np

        embedder = self._load_embedder()
        texts = [h.text or "" for h in hits]
        doc_vecs = embedder.embed_texts(texts)
        q_vec = embedder.embed_query(query)

        doc_arr = np.asarray(doc_vecs, dtype=np.float32)
        if doc_arr.ndim != 2 or doc_arr.shape[0] != len(hits):
            logger.warning("embedder returned unexpected shape; skipping rerank")
            return hits

        q = np.asarray(q_vec, dtype=np.float32).ravel()
        q_norm = np.linalg.norm(q) or 1.0
        doc_norms = np.linalg.norm(doc_arr, axis=1)
        doc_norms[doc_norms == 0] = 1.0
        cos = (doc_arr @ q) / (doc_norms * q_norm)

        # Blend: the lexical score already encodes exact-term evidence the
        # embedding is blind to, so keep both rather than replacing.
        lex = np.array([h.lexical_score for h in hits], dtype=np.float32)
        lex_max = float(lex.max()) or 1.0
        blended = 0.5 * (lex / lex_max) + 0.5 * cos

        for hit, c, b in zip(hits, cos, blended):
            hit.semantic_score = float(c)
            hit.score = float(b)

        return sorted(hits, key=lambda h: h.score, reverse=True)
