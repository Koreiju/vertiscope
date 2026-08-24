"""
embedding_service.py — GPT4All-backed nomic embeddings.

Two supported models — both 768-dim nomic:

* ``nomic-embed-text-v1.5.f16.gguf`` — kept as the default to avoid
  silently changing embeddings for existing consumers (segment embedder,
  pattern embedder, ontology fields).
* ``nomic-embed-text-v1.f16.gguf``   — used by the per-instance chunk
  embedder (Phase 5). Loaded on demand.

Device
------
Defaults to ``gpu``; callers can override with ``device='cpu'`` when a
GPU is unavailable. On import-time failure to allocate the GPU backend
we log and fall back to CPU so unit tests on headless CI boxes don't
break.

Task prefixes
-------------
Nomic models distinguish document vs. query semantics via the prefixes
``search_document: ...`` for documents and ``search_query: ...`` for
queries (see the Nomic Embedding Guide).  Expose both via separate
methods so callers don't have to remember the convention.
"""

from __future__ import annotations

import logging
import threading
from typing import Iterable, List, Optional, Sequence

import numpy as np

logger = logging.getLogger(__name__)


# Module-level cache keyed by (model_name, device) so the same model
# isn't reloaded per request. Embed4All is expensive to instantiate.
_MODEL_CACHE: dict = {}

# Per-model-name lock. llama.cpp (the backend under GPT4All's Embed4All)
# is NOT thread-safe: concurrent embed() calls on the same model handle
# scramble the ggml compute graph and reliably produce
#   OSError: exception: access violation reading 0x...
# followed a call or two later by
#   GGML_ASSERT: llama.cpp:14823: backend_embd != nullptr
# (the latter abort()s the process). The fix is structural — serialize
# every embed() that targets the same model so llama.cpp only ever sees
# one in-flight call per handle. We key by model_name (not by device,
# not by instance) because swapping GPU↔CPU during recovery still
# touches the same model file and potentially shared kernels. The lock
# is re-entrant so the crash-recovery branch can reload + retry from
# inside an already-held critical section.
_MODEL_LOCKS: dict = {}
_MODEL_LOCKS_GUARD = threading.Lock()


def _get_model_lock(model_name: str) -> threading.RLock:
    """Return (creating on first call) the RLock that protects ``model_name``.

    Using a dict of locks (rather than one global lock) lets two DIFFERENT
    models run in parallel — e.g. a retrieval query on nomic-v1 can proceed
    while a chunker background job is hitting nomic-v1.5 — while still
    serializing calls against any single model handle.
    """
    lock = _MODEL_LOCKS.get(model_name)
    if lock is not None:
        return lock
    with _MODEL_LOCKS_GUARD:
        lock = _MODEL_LOCKS.get(model_name)
        if lock is None:
            lock = threading.RLock()
            _MODEL_LOCKS[model_name] = lock
    return lock

# Nomic v1/v1.5 have a 512-token context window. Task-prefix adds ~4 tokens,
# so we leave generous headroom. 2000 characters is a conservative upper
# bound (~500 tokens for English). Long inputs have been correlated with
# an access-violation crash in llmodel_embed; hard-truncating before
# handing the string to GPT4All keeps the native side happy.
_MAX_INPUT_CHARS = 2000


class _FakeEmbedModel:
    """Hash-deterministic 768-dim fake embedder for testing.

    Enabled via ``WFH_FAKE_EMBEDDER=1`` so the harness (and pytest CI
    boxes without GPU + GGUF weights) can exercise the full concept-
    create / index / apparitions / retrieval surface without paying
    the 60-300s nomic load on first call.

    Vectors are SHA256-hash → signed-float over 768 dims. Same input
    always produces the same output, so cosine relationships between
    similar inputs are nonsensical but stable — tests that assert on
    "X exists in candidate set" still pass, tests that assert on
    "X ranks higher than Y" would not.
    """

    def __init__(self, dim: int = 768) -> None:
        self.dim = int(dim)

    def embed(self, texts):
        # GPT4All Embed4All.embed signature: returns a single list[float]
        # for a single str input, or list[list[float]] for an iterable.
        import hashlib
        if isinstance(texts, str):
            return self._one(texts)
        return [self._one(t) for t in texts]

    def _one(self, text: str):
        import hashlib
        if not text:
            text = " "
        h = hashlib.sha256(text.encode("utf-8")).digest()
        out: List[float] = []
        # Stretch 32 hash bytes → 768 dims by repeated hashing with index.
        rounds = (self.dim + 31) // 32
        for r in range(rounds):
            hr = hashlib.sha256(h + r.to_bytes(2, "big")).digest()
            for b in hr:
                out.append((b - 128) / 128.0)
                if len(out) >= self.dim:
                    return out
        return out[: self.dim]


def _load_model(model_name: str, device: str):
    """Load an :class:`Embed4All` model, falling back to CPU on GPU error.

    Respects the ``WFH_FAKE_EMBEDDER`` env var: when set (to anything
    truthy: ``1``, ``true``, ``yes``), returns a :class:`_FakeEmbedModel`
    instead of touching gpt4all / downloading the GGUF. The fake model
    has the same ``embed()`` surface so callers don't care.
    """
    import os
    if os.environ.get("WFH_FAKE_EMBEDDER", "").lower() in ("1", "true", "yes"):
        key = (model_name, "fake")
        if key in _MODEL_CACHE:
            return _MODEL_CACHE[key]
        fake = _FakeEmbedModel()
        _MODEL_CACHE[key] = fake
        logger.info("EmbeddingService: WFH_FAKE_EMBEDDER set — using fake model for %s.",
                    model_name)
        return fake

    key = (model_name, device)
    if key in _MODEL_CACHE:
        return _MODEL_CACHE[key]

    # Imported lazily so CI boxes without gpt4all still import this module.
    from gpt4all import Embed4All

    try:
        model = Embed4All(model_name, device=device)
        _MODEL_CACHE[key] = model
        return model
    except Exception as exc:
        if device != "cpu":
            logger.warning(
                "EmbeddingService: %s on %r failed (%s); falling back to CPU.",
                model_name, device, exc,
            )
            cpu_key = (model_name, "cpu")
            if cpu_key in _MODEL_CACHE:
                return _MODEL_CACHE[cpu_key]
            model = Embed4All(model_name, device="cpu")
            _MODEL_CACHE[cpu_key] = model
            return model
        raise


def _truncate(text: str) -> str:
    """Hard-cap one string to ``_MAX_INPUT_CHARS``.

    The native llmodel_embed will fault on unexpectedly long inputs
    (observed as an access violation on Windows). Cap before handing
    anything off.
    """
    if not text:
        return " "
    if len(text) <= _MAX_INPUT_CHARS:
        return text
    return text[:_MAX_INPUT_CHARS]


class EmbeddingService:
    """Wrapper for GPT4All on-device embeddings.

    Parameters
    ----------
    model_name:
        Nomic GGUF filename. v1.5 is the default (keeps existing
        embeddings stable); pass ``'nomic-embed-text-v1.f16.gguf'`` to
        use the v1 model for the per-instance chunk path.
    device:
        ``'gpu'`` (default) or ``'cpu'``. GPU is the default because the
        per-instance embedder runs over hundreds of rendered chunks per
        page — CPU is too slow in practice. Falls back to CPU if GPU
        allocation fails.
    truncate_dim:
        Optional hard cap on embedding dimensionality. Nomic v1/v1.5
        both emit 768-dim vectors; we only truncate if a downstream
        table is narrower.
    """

    #: Default model: keep existing consumers on v1.5.
    DEFAULT_MODEL = "nomic-embed-text-v1.5.f16.gguf"
    #: Alternative: user-specified v1 for per-instance chunks.
    V1_MODEL = "nomic-embed-text-v1.f16.gguf"
    #: Default device — CUDA when an NVIDIA GPU is available, unless
    #: WFH_EMBEDDER_DEVICE overrides (set to "cpu" on systems without
    #: a CUDA backend, or "kompute" / "gpu" for Vulkan/Kompute). The
    #: _load_model path falls back to CPU on failure within the same
    #: real backend (still nomic; just on CPU) per §8D.46.
    @staticmethod
    def _default_device() -> str:
        import os
        return (os.environ.get("WFH_EMBEDDER_DEVICE", "") or "cuda").lower()
    DEFAULT_DEVICE = "cuda"

    def __init__(
        self,
        model_name: str = DEFAULT_MODEL,
        device: Optional[str] = None,
        truncate_dim: int = 768,
    ):
        self.model_name = model_name
        # Resolve the device: explicit ctor arg → env var → "gpu" default.
        self.device = device or self._default_device()
        self.dim = truncate_dim
        self.model = _load_model(model_name, self.device)

    # ------------------------------------------------------------------
    # Introspection (§8D.46 no-mocks contract)
    # ------------------------------------------------------------------

    def status(self) -> dict:
        """Report whether the real nomic model is bound.

        Returns ``{"backend": "nomic" | "fake", "model": <name>,
        "device": <str>, "fake_env": bool}`` so callers can verify
        the production embedding path is in use.
        """
        import os
        is_fake = isinstance(self.model, _FakeEmbedModel)
        return {
            "backend":  "fake" if is_fake else "nomic",
            "model":    self.model_name,
            "device":   self.device,
            "fake_env": os.environ.get("WFH_FAKE_EMBEDDER", "").lower() in ("1", "true", "yes"),
        }

    # ------------------------------------------------------------------
    # Documents (search_document: prefix)
    # ------------------------------------------------------------------

    def _safe_embed(self, prefixed: List[str]):
        """Invoke ``self.model.embed`` with crash-recovery AND a per-model lock.

        The native GPT4All embedder is not thread-safe. Without
        serialization, concurrent retrieval / chunker calls against the
        same ``Embed4All`` handle corrupt llama.cpp's compute graph and
        trigger an access violation (recoverable) or GGML_ASSERT (aborts
        the process). We take a per-``model_name`` RLock for every
        ``embed()`` call — the RLock is re-entrant so the recovery path
        can reload and retry from inside the same critical section.

        On OSError (typical fault signature) we evict every cached
        handle for this model, reload on CPU (GPU is the more common
        culprit on Windows), and retry exactly once. If THAT also fails
        we raise :class:`ValueError` so FastAPI can return a clean 503
        with a useful message instead of leaking an unhandled traceback.
        """
        lock = _get_model_lock(self.model_name)
        with lock:
            try:
                return self.model.embed(prefixed)
            except Exception as exc:
                # OSError on Windows == access violation in the native
                # library; other Exception types (ValueError from the
                # wrapper, etc.) we also treat as recoverable-once. We do
                # NOT broaden this to BaseException because KeyboardInterrupt
                # / SystemExit shouldn't silently trigger a reload.
                logger.error(
                    "EmbeddingService: embed() raised %s (%s); resetting model.",
                    type(exc).__name__, exc,
                )
                # Evict every cached handle for THIS model — GPU and CPU
                # handles for the same model file can both be corrupt once
                # llama.cpp's shared library state is disturbed.
                for k in list(_MODEL_CACHE.keys()):
                    if k[0] == self.model_name:
                        _MODEL_CACHE.pop(k, None)
                try:
                    self.model = _load_model(self.model_name, "cpu")
                    self.device = "cpu"
                    return self.model.embed(prefixed)
                except Exception as retry_exc:
                    raise ValueError(
                        f"Embedding backend failed even after CPU fallback: {retry_exc}"
                    ) from retry_exc

    def embed_texts(
        self,
        texts: Sequence[str],
        *,
        prefix: str = "search_document",
    ) -> np.ndarray:
        """Embed a batch of documents. Returns a ``(N, dim)`` float array.

        Empty list → empty array. Empty strings are replaced with a
        single space so the model doesn't throw.
        """
        if not texts:
            return np.zeros((0, self.dim), dtype=np.float32)
        safe = [_truncate(t) if (t and t.strip()) else " " for t in texts]
        prefixed = [f"{prefix}: {t}" for t in safe]
        raw = self._safe_embed(prefixed)
        arr = np.asarray(raw, dtype=np.float32)
        if arr.ndim == 1:
            arr = arr.reshape(1, -1)
        if self.dim and arr.shape[1] > self.dim:
            arr = arr[:, : self.dim]
        return arr

    # ------------------------------------------------------------------
    # Queries (search_query: prefix)
    # ------------------------------------------------------------------

    def embed_query(self, query: str) -> np.ndarray:
        """Embed a single query string with the ``search_query: `` prefix."""
        safe = _truncate(query) if (query and query.strip()) else " "
        raw = self._safe_embed([f"search_query: {safe}"])
        arr = np.asarray(raw, dtype=np.float32).reshape(-1)
        if self.dim and arr.shape[0] > self.dim:
            arr = arr[: self.dim]
        return arr


def get_default_service(
    model_name: str = EmbeddingService.DEFAULT_MODEL,
    device: str = EmbeddingService.DEFAULT_DEVICE,
) -> EmbeddingService:
    """Shared-instance accessor backed by :data:`_MODEL_CACHE`.

    Callers that want a process-wide embedder without threading one
    through every function should use this. Each ``(model, device)``
    pair caches exactly one underlying GPT4All model.
    """
    return EmbeddingService(model_name=model_name, device=device)


def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
    """Plain cosine similarity for two 1-D arrays."""
    if a.ndim != 1 or b.ndim != 1:
        raise ValueError("cosine_similarity expects 1-D vectors")
    na = float(np.linalg.norm(a))
    nb = float(np.linalg.norm(b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return float(np.dot(a, b) / (na * nb))


def mean_pool(vectors: Iterable[np.ndarray]) -> Optional[np.ndarray]:
    """Return the L2-normalized mean of a set of embedding vectors.

    Used to derive a page-level embedding from all chunk-instance
    embeddings on that page. Normalization keeps cosine similarity
    comparable with the component embeddings.
    """
    stack: List[np.ndarray] = [v for v in vectors if v is not None]
    if not stack:
        return None
    mat = np.asarray(stack, dtype=np.float32)
    if mat.ndim == 1:
        mat = mat.reshape(1, -1)
    avg = mat.mean(axis=0)
    norm = float(np.linalg.norm(avg))
    if norm > 0.0:
        avg = avg / norm
    return avg.astype(np.float32)
