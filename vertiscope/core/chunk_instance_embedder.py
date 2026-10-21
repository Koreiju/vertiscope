"""
chunk_instance_embedder.py — Batch embedding of per-instance renders.

The user's plan:

* Apply the quantized nomic model (``nomic-embed-text-v1.f16.gguf``,
  GPU-default) to every :class:`ChunkInstanceRender` on a page.
* **Dedup rendered text first** — repeat visits / templated pages
  generate the same ``rendered_text`` many times; we embed each unique
  string once and reuse the vector.
* Compute a **page-level embedding** as the L2-normalized mean of all
  instance embeddings. That's what feeds URL-level semantic search.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

import numpy as np

from vertiscope.core.chunk_render import ChunkInstanceRender
from vertiscope.core.embedding_service import (
    EmbeddingService,
    mean_pool,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Embedder
# ---------------------------------------------------------------------------


@dataclass
class EmbeddingBatchResult:
    """Summary of one batch run — useful for logging and progress UIs."""

    embedded_count: int
    unique_text_count: int
    page_embedding: Optional[np.ndarray]


class ChunkInstanceEmbedder:
    """Batch-embed :class:`ChunkInstanceRender` objects in place.

    The default model is ``nomic-embed-text-v1.f16.gguf`` running on
    GPU, matching the snippet the user pasted:

    .. code-block:: python

        from gpt4all import Embed4All
        embedder = Embed4All('nomic-embed-text-v1.f16.gguf', device='gpu')
        output = embedder.embed(text, prefix='search_document')

    Callers can swap in a different model or device via the
    ``embedder`` kwarg (used by tests that mock the encoder).
    """

    def __init__(
        self,
        embedder: Optional[EmbeddingService] = None,
        *,
        model_name: str = EmbeddingService.V1_MODEL,
        device: str = EmbeddingService.DEFAULT_DEVICE,
    ):
        self._embedder = embedder or EmbeddingService(
            model_name=model_name, device=device,
        )

    # ------------------------------------------------------------------
    # Dedup-aware batch embed
    # ------------------------------------------------------------------

    @staticmethod
    def _text_key(text: str) -> str:
        """Stable dedup key — same text → same key → one embed call."""
        return hashlib.sha1(text.encode("utf-8", errors="replace")).hexdigest()

    def embed_instances(
        self,
        instances: Sequence[ChunkInstanceRender],
    ) -> EmbeddingBatchResult:
        """Assign ``embedding`` to every instance, deduplicating repeats.

        Mutates ``instances`` in place (each gets its ``.embedding``
        set to a list of floats). Returns a summary including the
        page-level mean vector suitable for :class:`PageEmbedding`.
        """
        if not instances:
            return EmbeddingBatchResult(0, 0, None)

        # Bucket indices by deduped text.
        unique_texts: List[str] = []
        key_to_idx: Dict[str, int] = {}
        per_instance_key: List[str] = []

        for inst in instances:
            k = self._text_key(inst.rendered_text)
            per_instance_key.append(k)
            if k not in key_to_idx:
                key_to_idx[k] = len(unique_texts)
                unique_texts.append(inst.rendered_text)

        # One batched embed call for the unique set.
        vectors = self._embedder.embed_texts(unique_texts, prefix="search_document")
        # embed_texts returns (N, dim). Pull rows back out.
        unique_vecs: List[np.ndarray] = [vectors[i] for i in range(vectors.shape[0])]

        # Distribute back to instances.
        for inst, k in zip(instances, per_instance_key):
            v = unique_vecs[key_to_idx[k]]
            inst.embedding = list(map(float, v.tolist()))

        page_vec = mean_pool(unique_vecs)

        logger.info(
            "Embedded %d instance(s) via %d unique text(s); page vec %s",
            len(instances), len(unique_texts),
            "ok" if page_vec is not None else "empty",
        )

        return EmbeddingBatchResult(
            embedded_count=len(instances),
            unique_text_count=len(unique_texts),
            page_embedding=page_vec,
        )

    # ------------------------------------------------------------------
    # Query-side helper
    # ------------------------------------------------------------------

    def embed_query(self, query: str) -> np.ndarray:
        """Encode a search query with the ``search_query: `` prefix."""
        return self._embedder.embed_query(query)
