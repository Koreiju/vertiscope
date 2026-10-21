"""
global_tfidf_store.py — Incremental, append-only TF-IDF index.

Vocabulary policy: TOKEN-COMPLETE. Every token from every chunk
gets a permanent column index — no max_features cap, no min_df
filter, no stopwords. URL slugs are tokenized via ``tokenize_url``
so ``/blog/space-flowers`` contributes "space flowers" to the
vocabulary. Sparse tokens (those appearing in only a handful of
docs across the corpus) are kept too — the matrix is sparse so
their RAM cost is per-row not per-vocab.

Cross-DOM content dedup: the store keys rows by a SHA-1 hash of the
rendered text (``content_hash``), not by per-URL instance ids. So a
nav fragment that appears on every page in a site collapses to a
single row with the union of URLs that carry it. This both shrinks
the matrix (faster matvec) and prevents the user from seeing the
same menu item N times in retrieval.

Replaces the per-snapshot ``.npz`` files written by
``ChunkInstanceVectorizer.save_sparse_index`` with ONE global store
that:

* maintains a single vocabulary that grows monotonically — every
  token from every scanned DOM gets a permanent column index
* stores RAW per-chunk term-frequency rows (not IDF-weighted, not
  L2-normalized) so adding new chunks doesn't require re-touching
  the old ones
* recomputes the IDF vector on each ``add_chunks`` call (cheap —
  one ``log`` per vocab term) and applies it lazily at query time
* supports per-chunk replacement keyed on ``chunk_id`` so a re-scan
  of the same snapshot updates rows in place instead of inflating
  the index with duplicates

The user's ask, restated:

  > accumulate and dynamically update our vocabulary with more tokens
  > and compute the global tfidf vectors for *all* scanned DOMs such
  > that we can update the minimal variables necessary while not
  > re-processing full for all DOM chunks

Persistence layout (a single directory):

    <store_dir>/
        vocab.json        {token: column_index}     monotonic
        df.npy            np.int32[V]               document freq per term
        tf.npz            scipy CSR (N, V)          raw term-frequencies
        chunk_ids.json    [chunk_id, ...]           aligned with TF rows
        chunk_meta.json   [{chunk_id, url, snapshot_id, …}, ...]

Atomic save: writes to a sibling ``.tmp/`` directory then renames
into place so a partial save can't corrupt the index.

Thread-safety: NOT internally locked. Callers (mapper at scan-end,
query endpoint) coordinate via a single instance + external lock.
The mapper holds the index for the duration of one ``add_chunks``
call, then releases. Query is read-only and works against an
on-disk reload, so concurrent reads are fine.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shutil
import threading
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Tuple, Set
from urllib.parse import urlsplit

import numpy as np
from scipy import sparse as sp

from vertiscope.core.dedup_logging import get_dedup_logger


def _content_hash(text: str) -> str:
    """Stable content fingerprint for cross-DOM dedup.

    Hashes the FULL text, not a preview slice. Earlier versions
    hashed only the first 160 chars (the persisted ``text_preview``
    is bounded to that length to save disk), which made two chunks
    that shared a first sentence collide. We now compute over the
    whole rendered text and persist the digest on ``ChunkMeta``
    itself, so the dedup index is consistent across save → load
    cycles even though the preview stays length-bounded.
    """
    return hashlib.sha1((text or "").encode("utf-8", errors="replace")).hexdigest()[:16]

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Tokenization (mirrors the per-snapshot TfidfService rules)
# ---------------------------------------------------------------------------

_TOKEN_RE = re.compile(r"(?u)\b\w+\b")
_URL_SEP_RE = re.compile(r"[/\-_.]+")
_PERCENT_RE = re.compile(r"%[0-9A-Fa-f]{2}")


def _tokenize_url_for_text(url: str) -> str:
    if not url:
        return ""
    try:
        parts = urlsplit(url)
    except Exception:
        return ""
    if parts.scheme not in ("http", "https", ""):
        return ""
    host = (parts.hostname or "").replace(".", " ")
    body = " ".join(p for p in (host, parts.path or "", parts.query or "") if p)
    body = _URL_SEP_RE.sub(" ", body)
    body = _PERCENT_RE.sub(" ", body)
    return re.sub(r"\s+", " ", body).strip()


def _expand_urls_in_text(text: str) -> str:
    if not text:
        return text
    return re.sub(
        r"(?:https?://|/)\S+",
        lambda m: " " + _tokenize_url_for_text(m.group(0)) + " ",
        text,
    )


def _tokens(text: str, ngram_max: int = 2) -> List[str]:
    r"""Lowercase unigrams + bigrams. Same shape sklearn's
    TfidfVectorizer(ngram_range=(1,2), token_pattern=r"(?u)\b\w+\b")
    produces, but reimplemented so the global store doesn't depend on
    sklearn at query time (faster cold-load + smaller deployment)."""
    if not text:
        return []
    expanded = _expand_urls_in_text(text)
    unigrams = [m.group(0).lower() for m in _TOKEN_RE.finditer(expanded)]
    if ngram_max <= 1:
        return unigrams
    out: List[str] = list(unigrams)
    for i in range(len(unigrams) - 1):
        out.append(unigrams[i] + " " + unigrams[i + 1])
    return out


# ---------------------------------------------------------------------------
# Public dataclass for the API layer
# ---------------------------------------------------------------------------


@dataclass
class ChunkMeta:
    """One row of metadata for a stored chunk.

    ``urls`` accumulates every URL where this content was seen so
    duplicate menu items / nav fragments collapse to a single row
    in the store with the union of URLs that carry them. ``url``
    is kept as the FIRST-seen URL for backward-compat with callers
    that read ``meta.url`` directly.
    """

    chunk_id: str
    url: str
    snapshot_id: str
    absolute_xpath: str = ""
    instance_idx: int = 0
    pattern: str = ""
    text_preview: str = ""
    urls: List[str] = None  # type: ignore[assignment]
    # Persisted full-text content hash. Populated on first add_chunks
    # call; the load path back-fills from text_preview for old rows
    # that pre-date this field (one-time migration cost, then stable).
    content_hash: str = ""

    def __post_init__(self) -> None:
        if self.urls is None:
            self.urls = [self.url] if self.url else []


@dataclass
class SearchHit:
    chunk_id: str
    score: float
    meta: ChunkMeta


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class GlobalTfidfStore:
    """Append-only TF-IDF index across every snapshot ever scanned.

    Designed for write-side speed: one ``add_chunks`` call walks N
    new chunks, hashes their tokens against the running vocabulary
    (adding entries on miss), and vstacks N new rows onto the TF
    matrix. No re-tokenization or re-vectorization of old chunks.

    Read-side speed: query is one sparse matvec plus an
    ``argpartition`` over the result vector. Sub-millisecond on
    thousand-row corpora.
    """

    # Format version stamped into ``meta.json`` so a future schema
    # change can detect old layouts and rebuild rather than crash.
    FORMAT_VERSION = 1

    #: Tokens with df < ``MIN_QUERY_DF`` get a zero IDF weight at query
    #: time so they don't dominate retrieval scores. Writes stay
    #: token-complete (every token gets a vocab column) — the filter
    #: only affects scoring. ``1`` allows all tokens in small corpora,
    #: which is critical when scanning only a few pages.
    MIN_QUERY_DF = 1

    def __init__(self, store_dir: str):
        self.store_dir = os.path.abspath(store_dir)
        # token → column index. Order of insertion = column id.
        self._vocab: Dict[str, int] = {}
        # Document frequency per column (np.int32). Grows with vocab.
        self._df: np.ndarray = np.zeros(0, dtype=np.int32)
        # CSR of shape (N_chunks, V). Raw term-frequencies (int32).
        # Reusing scipy sparse means the in-RAM cost is O(nnz) which
        # is ~per-chunk-token-count summed, NOT N×V. That's the whole
        # point of using sparse — IDF arrays grow without bound while
        # the matrix doesn't waste storage on zeros.
        self._tf: sp.csr_matrix = sp.csr_matrix((0, 0), dtype=np.int32)
        self._chunk_ids: List[str] = []
        self._chunk_id_to_row: Dict[str, int] = {}
        self._chunk_meta: List[ChunkMeta] = []
        # Persistent content_hash → row_idx index. Mutated in place on
        # append/replace; populated from meta on ``load()``. Replaces a
        # per-call O(N) rebuild that dominated the streaming write path.
        self._content_to_row: Dict[str, int] = {}

        self._lock = threading.RLock()  # caller-side coordination
        self._dirty = False
        # Query-time cache: (idf_vector, tf_idf_norm CSR). Built lazily
        # on first ``search()``, reused across queries until the next
        # ``add_chunks`` mutates the index. Without this every query
        # paid O(nnz) to rebuild ``tf_idf_norm`` — fine on a 100-doc
        # corpus, ruinous past 10k. Invalidation is a single
        # assignment so the write-side stays O(new tokens).
        self._idf_cache: Optional[np.ndarray] = None
        # Lazy per-row L2 norms used by ``search()`` to compute cosine
        # similarity on the fly. Replaces the prior fully-normalized
        # ``tf_idf_norm`` CSR — see ``_ensure_query_cache``.
        self._row_norms_cache: Optional[np.ndarray] = None
        self._cache_doc_count: int = 0
        self._cache_vocab_size: int = 0

        os.makedirs(self.store_dir, exist_ok=True)
        try:
            self.load()
        except FileNotFoundError:
            # First-time use; nothing to load.
            pass

    # ------------------------------------------------------------------
    # Load / save
    # ------------------------------------------------------------------

    def _path(self, name: str) -> str:
        return os.path.join(self.store_dir, name)

    def load(self) -> None:
        with self._lock:
            vocab_p = self._path("vocab.json")
            tf_p = self._path("tf.npz")
            df_p = self._path("df.npy")
            ids_p = self._path("chunk_ids.json")
            meta_p = self._path("chunk_meta.json")

            if not os.path.exists(vocab_p):
                raise FileNotFoundError(vocab_p)

            with open(vocab_p, "r", encoding="utf-8") as f:
                self._vocab = json.load(f)
            self._df = np.load(df_p) if os.path.exists(df_p) else np.zeros(
                len(self._vocab), dtype=np.int32,
            )
            if os.path.exists(tf_p):
                self._tf = sp.load_npz(tf_p).tocsr().astype(np.int32)
            else:
                self._tf = sp.csr_matrix((0, len(self._vocab)), dtype=np.int32)
            with open(ids_p, "r", encoding="utf-8") as f:
                self._chunk_ids = json.load(f)
            self._chunk_id_to_row = {cid: i for i, cid in enumerate(self._chunk_ids)}
            with open(meta_p, "r", encoding="utf-8") as f:
                meta_raw = json.load(f)
            self._chunk_meta = [ChunkMeta(**m) for m in meta_raw]
            # Rebuild the content_hash → row index from persisted meta.
            # For rows that pre-date the ``content_hash`` field, fall
            # back to hashing ``text_preview`` (the legacy behavior) so
            # old stores still benefit from incremental dedup, even if
            # an early-collision risk remains for those specific rows
            # until they're rewritten by a re-scan.
            self._content_to_row = {}
            for i, m in enumerate(self._chunk_meta):
                key = m.content_hash or _content_hash(m.text_preview or "")
                if not m.content_hash:
                    m.content_hash = key  # back-fill so the next save persists it
                self._content_to_row.setdefault(key, i)
            self._dirty = False

    def save(self) -> None:
        """Atomic save: write to a tmp dir, then rename into place."""
        with self._lock:
            if not self._dirty:
                return
            tmp = self.store_dir + ".tmp"
            if os.path.exists(tmp):
                shutil.rmtree(tmp)
            os.makedirs(tmp, exist_ok=True)

            with open(os.path.join(tmp, "vocab.json"), "w", encoding="utf-8") as f:
                json.dump(self._vocab, f)
            np.save(os.path.join(tmp, "df.npy"), self._df)
            sp.save_npz(os.path.join(tmp, "tf.npz"), self._tf)
            with open(os.path.join(tmp, "chunk_ids.json"), "w", encoding="utf-8") as f:
                json.dump(self._chunk_ids, f)
            with open(os.path.join(tmp, "chunk_meta.json"), "w", encoding="utf-8") as f:
                json.dump(
                    [m.__dict__ for m in self._chunk_meta], f,
                )
            with open(os.path.join(tmp, "meta.json"), "w", encoding="utf-8") as f:
                json.dump({
                    "format_version": self.FORMAT_VERSION,
                    "vocab_size": len(self._vocab),
                    "doc_count": len(self._chunk_ids),
                    "saved_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
                }, f)

            # Move into place by directory rename. On Windows
            # ``os.replace`` won't blow away an existing target dir,
            # so swap atomically by renaming current → .old, tmp →
            # current, then dropping .old.
            old = self.store_dir + ".old"
            if os.path.exists(old):
                shutil.rmtree(old)
            if os.path.exists(self.store_dir):
                os.rename(self.store_dir, old)
            os.rename(tmp, self.store_dir)
            if os.path.exists(old):
                shutil.rmtree(old, ignore_errors=True)
            self._dirty = False

    def remove_chunks(self, chunk_ids: Sequence[str], match_prefix: bool = False) -> int:
        """Delete rows by chunk_id. If ``match_prefix=True``, delete every row
        whose stored id starts with ``chunk_id + '_'`` — this supports removal
        of per‑member instance keys that were created by ``_DeltaInstanceLight``."""
        if not chunk_ids:
            return 0
        with self._lock:
            to_remove: Set[str] = set()
            if match_prefix:
                # Collect all stored ids that share a given chunk‑id prefix
                for cid in chunk_ids:
                    prefix = cid + "_"
                    for stored in self._chunk_ids:
                        if stored.startswith(prefix):
                            to_remove.add(stored)
            else:
                to_remove = {cid for cid in chunk_ids if cid in self._chunk_id_to_row}

            if not to_remove:
                return 0
            
            logger_dedup = get_dedup_logger()
            logger_dedup.debug("TFIDF_REMOVE chunk_ids=%s", list(to_remove)[:10])
            
            keep_rows = [i for i in range(self._tf.shape[0])
                         if self._chunk_ids[i] not in to_remove]
            if len(keep_rows) == self._tf.shape[0]:
                return 0

            # Subtract df contributions of removed rows
            for r in range(len(self._chunk_ids)):
                if r not in keep_rows:
                    old_cols = self._tf.indices[
                        self._tf.indptr[r]:self._tf.indptr[r + 1]
                    ]
                    if old_cols.size:
                        self._df[np.unique(old_cols)] -= 1

            # Rebuild CSR from kept rows
            new_data = []
            new_indices = []
            new_indptr = [0]
            for r in keep_rows:
                row = self._tf.getrow(r).tocoo()
                new_indices.append(row.col.astype(np.int32))
                new_data.append(row.data.astype(np.int32))
                new_indptr.append(new_indptr[-1] + len(row.col))
            V = self._tf.shape[1]
            self._tf = sp.csr_matrix(
                (
                    np.concatenate(new_data) if new_data else np.zeros(0, dtype=np.int32),
                    np.concatenate(new_indices) if new_indices else np.zeros(0, dtype=np.int32),
                    np.asarray(new_indptr, dtype=np.int32),
                ),
                shape=(len(keep_rows), V),
                dtype=np.int32,
            )
            # Rebuild metadata
            self._chunk_ids = [self._chunk_ids[i] for i in keep_rows]
            self._chunk_meta = [self._chunk_meta[i] for i in keep_rows]
            self._chunk_id_to_row = {cid: i for i, cid in enumerate(self._chunk_ids)}
            self._content_to_row = {}
            for i, m in enumerate(self._chunk_meta):
                if m.content_hash:
                    self._content_to_row.setdefault(m.content_hash, i)
            self._idf_cache = None
            self._row_norms_cache = None
            self._dirty = True
            return len(to_remove)

    def clear_all(self) -> int:
        """§6.5 / §16.5 — drop EVERY row: scanner-emitted instance rows
        (URL-keyed kuzu instance ids) AND ``graph__``-prefixed compute
        outputs. A FULL-workspace purge calls this — on the single-user
        on-device app the workspace IS the chunk pool, and the §16.5
        cleanup contract requires ``chunk_search`` to return nothing at
        baseline. (``remove_workspace`` alone only matched the
        ``graph__<ws>__`` prefix, so scanner-emitted rows survived purges
        as ghost hits — score + preview with their ChunkInstance gone.)
        Returns the number of rows removed."""
        with self._lock:
            all_ids = list(self._chunk_ids)
        if not all_ids:
            return 0
        return self.remove_chunks(all_ids, match_prefix=False)

    def remove_workspace(self, workspace_id: str) -> int:
        """§1.8 / persistence.md — drop every TF-IDF row belonging to ONE
        workspace. ``output_projection`` mints chunk ids as
        ``graph__<ws>__<concept_id>__<sample>``, so a workspace's rows all
        share the ``graph__<ws>__`` prefix. ``purge_workspace`` calls this so
        a purge can't leave ghost chunks behind: this is a single GLOBAL,
        ever-growing store, so without an explicit removal the purged
        workspace's rows would still surface in ``chunk_search`` with a score
        + preview but an empty ``html_raw`` (their Kuzu ``ChunkInstance`` was
        deleted) — violating the §18.4 cleanup + §1.10 isolation contracts.
        Cheap CSR rebuild (delegates to ``remove_chunks``); never loads an
        embedder, so it's safe in the perf-tuned purge path. Returns the
        number of rows removed."""
        ws = workspace_id or "_default"
        prefix = f"graph__{ws}__"
        with self._lock:
            matching = [cid for cid in self._chunk_ids if cid.startswith(prefix)]
        if not matching:
            return 0
        # RLock is re-entrant, but collecting first then delegating keeps the
        # critical section minimal and the removal logic in one place (DRY).
        return self.remove_chunks(matching, match_prefix=False)

    # ------------------------------------------------------------------
    # Add / replace chunks (the hot path the mapper calls)
    # ------------------------------------------------------------------

    def add_chunks(
        self,
        texts: Sequence[str],
        metas: Sequence[ChunkMeta],
    ) -> int:
        """Add or merge chunks in the index.

        Three cases per (text, meta) pair:

          1. ``content_hash(text)`` not seen before  → APPEND a new
             row. The store's ``chunk_id`` for this row is the input
             ``meta.chunk_id`` (typically the URL-keyed kuzu
             ``instance_id``) so the API can echo it back into
             ``/api/chunk_details/{id}`` calls.

          2. ``content_hash(text)`` matches an EXISTING row — the
             same nav fragment / footer / repeated card on a
             different URL. We DO NOT add a new row; instead we
             append ``meta.url`` to that row's ``urls`` list. The
             matrix grows much slower than the document count
             grows on multi-page sites, which keeps query matvec
             fast even after dozens of scans.

          3. ``meta.chunk_id`` matches an existing row but the
             content has CHANGED — the URL was re-scanned and the
             content shifted. We replace the row's TF / meta in
             place via direct CSR-array manipulation (no LIL
             roundtrip). df is adjusted by subtracting the prior
             row's unique-token contributions and adding the new
             ones.

        Returns the number of rows actually touched (sum of new +
        replaced; merges don't count because they don't change the
        TF matrix at all).
        """
        if len(texts) != len(metas):
            raise ValueError("texts and metas must align")
        if not texts:
            return 0

        with self._lock:
            # The ``self._content_to_row`` dict is maintained incrementally
            # on every append/replace below; no per-call rebuild needed.
            # On load it's populated from persisted meta. This drops the
            # streaming write path's per-batch cost from O(N_total) to
            # O(batch_size).

            # --- Phase 1: classify each input ---------------------------
            # Any input whose content_hash matches an existing row
            # is a MERGE. Anything else is either an APPEND or an
            # in-place REPLACE keyed on chunk_id.
            new_tokens_per_doc: List[List[str]] = [_tokens(t or "") for t in texts]
            # Hash the FULL text of the new input — the persisted preview
            # is length-capped (160 chars) and would falsely collide
            # chunks that share a first sentence. The hash is then
            # written onto each row's meta below so future load() calls
            # see the same key without needing to re-tokenize.
            content_hashes: List[str] = [
                _content_hash(texts[i] or "")
                for i in range(len(texts))
            ]

            actions: List[Tuple[str, int, Optional[int]]] = []
            # Each entry is ``(action, batch_idx, target_row)``:
            #   ('merge',  i, row)  → append meta.url to row's urls
            #   ('replace', i, row) → overwrite TF + meta of row
            #   ('append', i, None) → append new row
            seen_in_batch_hash: Dict[str, int] = {}
            for i, (m, ch) in enumerate(zip(metas, content_hashes)):
                # Persist the hash on the incoming meta so any later
                # save() round-trip carries the digest forward.
                m.content_hash = ch
                # Within-batch dedup so two identical chunks in the
                # same scan don't both append.
                if ch in seen_in_batch_hash:
                    actions.append(('merge', i, seen_in_batch_hash[ch]))
                    continue

                row_by_id = self._chunk_id_to_row.get(m.chunk_id)
                if row_by_id is not None:
                    actions.append(('replace', i, row_by_id))
                else:
                    actions.append(('append', i, None))
                    # Mark for dedup against later items in this batch.
                    seen_in_batch_hash[ch] = -1  # placeholder until row index known

            logger_dedup = get_dedup_logger()
            for act, i, row in actions:
                if act == "append":
                    logger_dedup.debug("TFIDF_APPEND chunk_id=%s content_hash=%s", metas[i].chunk_id, metas[i].content_hash)
                elif act == "replace":
                    logger_dedup.debug("TFIDF_REPLACE chunk_id=%s content_hash=%s", metas[i].chunk_id, metas[i].content_hash)
                elif act == "merge":
                    logger_dedup.debug("TFIDF_MERGE chunk_id=%s merged_url=%s", metas[i].chunk_id, metas[i].url)

            # --- Phase 2: vocab + df bookkeeping ------------------------
            # Intern vocab from BOTH appends and replaces (merges
            # don't change the matrix so their tokens are already
            # in vocab — the matching row contributed them).
            for i, (action, _, _) in enumerate(actions):
                if action == 'merge':
                    continue
                for tok in new_tokens_per_doc[i]:
                    if tok not in self._vocab:
                        self._vocab[tok] = len(self._vocab)
            V = len(self._vocab)

            # Pad ``df`` to the new vocab width.
            if self._df.shape[0] < V:
                pad = np.zeros(V - self._df.shape[0], dtype=np.int32)
                self._df = np.concatenate([self._df, pad])

            # Pad existing TF matrix to V columns.
            if self._tf.shape[1] < V:
                self._tf = sp.csr_matrix(
                    (self._tf.data, self._tf.indices, self._tf.indptr),
                    shape=(self._tf.shape[0], V),
                )

            # --- Phase 3: build per-row TF (cols + vals) ---------------
            row_cols: List[np.ndarray] = []
            row_vals: List[np.ndarray] = []
            for i in range(len(texts)):
                if actions[i][0] == 'merge':
                    row_cols.append(np.zeros(0, dtype=np.int32))
                    row_vals.append(np.zeros(0, dtype=np.int32))
                    continue
                    
                counts: Dict[int, int] = {}
                for tok in new_tokens_per_doc[i]:
                    col = self._vocab[tok]
                    counts[col] = counts.get(col, 0) + 1
                if not counts:
                    row_cols.append(np.zeros(0, dtype=np.int32))
                    row_vals.append(np.zeros(0, dtype=np.int32))
                    continue
                cols = np.fromiter(counts.keys(), dtype=np.int32)
                vals = np.fromiter(counts.values(), dtype=np.int32)
                order = np.argsort(cols)
                row_cols.append(cols[order])
                row_vals.append(vals[order])

            # --- Phase 4: apply MERGE actions first --------------------
            # Merge URLs into existing meta. No matrix touch.
            for action, batch_idx, target_row in actions:
                if action != 'merge':
                    continue
                if target_row is None or target_row < 0:
                    continue
                m_in = metas[batch_idx]
                existing = self._chunk_meta[target_row]
                if m_in.url and m_in.url not in existing.urls:
                    existing.urls.append(m_in.url)

            # --- Phase 5: REPLACE actions (in-place CSR manipulation) -
            # Subtract old row's df contribution, splice in new
            # data/indices, fix indptr if length changed.
            replaces = [(b, r) for action, b, r in actions if action == 'replace']
            if replaces:
                self._tf = self._tf.tocsr()
                # Build a NEW CSR by walking rows in order. Cheaper
                # than per-row LIL twiddling for any non-tiny matrix.
                new_data = []
                new_indices = []
                new_indptr = [0]
                replace_map = {r: b for b, r in replaces}
                for r in range(self._tf.shape[0]):
                    if r in replace_map:
                        b = replace_map[r]
                        # Subtract old df contributions.
                        old_cols = self._tf.indices[self._tf.indptr[r]:self._tf.indptr[r + 1]]
                        if old_cols.size:
                            self._df[np.unique(old_cols)] -= 1
                        # Splice new row.
                        new_indices.append(row_cols[b])
                        new_data.append(row_vals[b])
                        # Add new df contributions.
                        if row_cols[b].size:
                            self._df[np.unique(row_cols[b])] += 1
                        # Update meta in place. Preserve accumulated
                        # urls from any prior merges, but include the
                        # incoming url too.
                        new_meta = metas[b]
                        existing_urls = list(self._chunk_meta[r].urls)
                        if new_meta.url and new_meta.url not in existing_urls:
                            existing_urls.append(new_meta.url)
                        new_meta.urls = existing_urls
                        # Update the persistent content_hash → row map.
                        # If the prior row's hash differed (genuine
                        # content shift), drop the stale entry first so
                        # a future input matching the OLD content
                        # doesn't merge into the row that now has new
                        # content.
                        old_hash = self._chunk_meta[r].content_hash
                        if old_hash and old_hash != new_meta.content_hash:
                            if self._content_to_row.get(old_hash) == r:
                                self._content_to_row.pop(old_hash, None)
                        if new_meta.content_hash:
                            self._content_to_row.setdefault(new_meta.content_hash, r)
                        self._chunk_meta[r] = new_meta
                    else:
                        idx_slice = self._tf.indices[self._tf.indptr[r]:self._tf.indptr[r + 1]]
                        data_slice = self._tf.data[self._tf.indptr[r]:self._tf.indptr[r + 1]]
                        new_indices.append(idx_slice)
                        new_data.append(data_slice)
                    new_indptr.append(new_indptr[-1] + len(new_indices[-1]))
                self._tf = sp.csr_matrix(
                    (
                        np.concatenate(new_data) if new_data else np.zeros(0, dtype=np.int32),
                        np.concatenate(new_indices) if new_indices else np.zeros(0, dtype=np.int32),
                        np.asarray(new_indptr, dtype=np.int32),
                    ),
                    shape=(self._tf.shape[0], V),
                    dtype=np.int32,
                )

            # --- Phase 6: APPEND new rows ------------------------------
            appends = [b for action, b, _ in actions if action == 'append']
            if appends:
                a_data = []
                a_indices = []
                a_indptr = [0]
                for b in appends:
                    a_indices.append(row_cols[b])
                    a_data.append(row_vals[b])
                    a_indptr.append(a_indptr[-1] + len(row_cols[b]))
                    if row_cols[b].size:
                        self._df[np.unique(row_cols[b])] += 1

                append_csr = sp.csr_matrix(
                    (
                        np.concatenate(a_data) if a_data else np.zeros(0, dtype=np.int32),
                        np.concatenate(a_indices) if a_indices else np.zeros(0, dtype=np.int32),
                        np.asarray(a_indptr, dtype=np.int32),
                    ),
                    shape=(len(appends), V),
                    dtype=np.int32,
                )
                base = len(self._chunk_ids)
                self._tf = sp.vstack([self._tf, append_csr], format="csr").astype(np.int32)
                for offset, b in enumerate(appends):
                    m = metas[b]
                    row_idx = base + offset
                    self._chunk_ids.append(m.chunk_id)
                    self._chunk_id_to_row[m.chunk_id] = row_idx
                    self._chunk_meta.append(m)
                    # Mirror the new row in the content_hash index so
                    # the next batch's classify phase sees this content
                    # immediately as a merge candidate.
                    if m.content_hash:
                        self._content_to_row.setdefault(m.content_hash, row_idx)

            self._dirty = True
            # Any of MERGE/REPLACE/APPEND can shift df or row count, so
            # the cached IDF + row-norms are stale. One-line invalidation
            # — the rebuild happens lazily on the next ``search()`` call.
            self._idf_cache = None
            self._row_norms_cache = None
            return sum(1 for a, _, _ in actions if a in ("append", "replace"))

    # ------------------------------------------------------------------
    # Query
    # ------------------------------------------------------------------

    def _idf(self) -> np.ndarray:
        """Smoothed IDF: ``log((N + 1) / (df + 1)) + 1`` (sklearn's
        default). Recomputed on demand — O(V) which is small even
        at million-vocab scale.

        Tokens with ``df < MIN_QUERY_DF`` get IDF=0 so genuinely
        sparse vocabulary (typos, hex hashes, one-off ids) doesn't
        dominate retrieval. Vocab itself is still token-complete on
        the write side — this is a read-only filter.
        """
        N = self._tf.shape[0]
        df = self._df.astype(np.float64)
        idf = (np.log((N + 1.0) / (df + 1.0)) + 1.0).astype(np.float32)
        if self.MIN_QUERY_DF > 1:
            idf[df < self.MIN_QUERY_DF] = 0.0
        return idf

    def _ensure_query_cache(self) -> Tuple[np.ndarray, np.ndarray]:
        """Build (and cache) the IDF vector + per-row L2 norms.

        The cache is invalidated by ``add_chunks`` (one-line reset).
        Search uses the RAW ``self._tf`` matrix directly + this norm
        vector to compute cosine similarity on the fly, instead of
        materializing a fully-normalized ``tf_idf_norm`` matrix on
        every cache miss. That earlier path allocated two full sparse
        copies of ``self._tf`` per rebuild (one for ``tf*idf`` and
        another for the row-scaled normalization), which dominated
        cost as the corpus grew. With lazy normalization we only
        allocate a small dense ``row_norms`` vector of length N — the
        sparse matrix itself is never copied.
        """
        if (
            self._row_norms_cache is not None
            and self._idf_cache is not None
            and self._cache_doc_count == self._tf.shape[0]
            and self._cache_vocab_size == self._tf.shape[1]
        ):
            return self._idf_cache, self._row_norms_cache

        idf = self._idf()
        # row_norms[i] = sqrt(sum_j (tf[i,j] * idf[j])^2)
        # We compute this without materializing tf*idf: walk each
        # nonzero entry once, accumulating squared contributions per
        # row via ``np.add.at`` (segment sum keyed by repeated row
        # index). O(nnz) work, O(N) extra memory — far cheaper than
        # building a second sparse matrix.
        N = self._tf.shape[0]
        if N == 0:
            row_norms = np.zeros(0, dtype=np.float32)
        else:
            data = self._tf.data.astype(np.float32, copy=False)
            indices = self._tf.indices
            indptr = self._tf.indptr
            idf_at = idf[indices].astype(np.float32, copy=False)
            squared_contrib = (data * idf_at) ** 2
            row_norm_sq = np.zeros(N, dtype=np.float32)
            # Repeat each row index by its nnz count so np.add.at
            # accumulates contributions per-row in one vectorized pass.
            row_idx = np.repeat(np.arange(N), np.diff(indptr))
            np.add.at(row_norm_sq, row_idx, squared_contrib)
            row_norms = np.sqrt(np.maximum(row_norm_sq, 1e-12)).astype(np.float32)

        self._idf_cache = idf
        self._row_norms_cache = row_norms
        self._cache_doc_count = N
        self._cache_vocab_size = self._tf.shape[1]
        return idf, row_norms

    def search(
        self,
        query: str,
        k: int = 10,
        urls: Optional[Sequence[str]] = None,
    ) -> List[SearchHit]:
        """Return the top-``k`` chunks for ``query``.

        ``urls`` filters to chunks from that set of URLs (used by
        the per-page panels in the GUI).
        """
        with self._lock:
            if self._tf.shape[0] == 0 or len(self._vocab) == 0:
                return []

            q_tokens = _tokens(query or "")
            if not q_tokens:
                return []
            q_counts: Dict[int, int] = {}
            for tok in q_tokens:
                col = self._vocab.get(tok)
                if col is None:
                    continue
                q_counts[col] = q_counts.get(col, 0) + 1
            if not q_counts:
                return []

            idf, row_norms = self._ensure_query_cache()

            # Build query weighted vector. Drop columns with idf==0
            # (rare-token filter) so the matvec doesn't waste work.
            cols = np.fromiter(q_counts.keys(), dtype=np.int32)
            vals = np.fromiter(q_counts.values(), dtype=np.float32)
            kept = idf[cols] > 0
            cols = cols[kept]
            vals = vals[kept]
            if cols.size == 0:
                return []
            # Cosine derivation: row vector r_j = tf[i,j] * idf[j],
            # query vector q_j = vals[j] * idf[j]. Cosine = (r·q)/(||r||·||q||)
            # = sum_j (tf[i,j] * vals[j] * idf[j]^2) / (row_norms[i] * q_norm).
            # We bake idf^2 into the per-column weight passed to the
            # sparse matvec so it returns the unnormalized score
            # numerator directly.
            q_norm = float(np.linalg.norm(vals * idf[cols]))
            if q_norm <= 0:
                return []
            q_weighted = vals * (idf[cols] ** 2)

            # Sparse query column-vector. Sort columns so CSR
            # construction validates without resort overhead.
            order = np.argsort(cols)
            cols_sorted = cols[order]
            q_weighted_sorted = q_weighted[order]
            q_sparse = sp.csr_matrix(
                (q_weighted_sorted, cols_sorted, np.array([0, len(cols_sorted)], dtype=np.int32)),
                shape=(1, len(self._vocab)),
            )

            # Single sparse matvec against the raw TF matrix — no
            # full normalized copy materialized. The result is the
            # unnormalized cosine numerator; we divide by the per-row
            # norm and the query norm to get cosine in [0, 1].
            raw_scores = (self._tf @ q_sparse.T).toarray().ravel().astype(np.float32)
            sims = raw_scores / (row_norms * q_norm + 1e-12)

            if urls is not None:
                url_set = {u.rstrip("/") for u in urls}
                mask = np.array(
                    [any((u or "").rstrip("/") in url_set for u in m.urls) for m in self._chunk_meta], dtype=bool,
                )
                sims = np.where(mask, sims, -1.0)

            kk = min(k, sims.size)
            if kk <= 0:
                return []
            cut = np.argpartition(-sims, kk - 1)[:kk]
            # Canonical tie-break (THEORY PROP-10.8). Ordering by score alone
            # leaves ties resolved by row index, which makes insertion order
            # observable: the same corpus inserted in a different order returns
            # equally-scoring hits in a different order. That falsified MODEL
            # §4.1's quotient by row permutation.
            #
            # Breaking ties on chunk_id makes the result a function of the
            # multiset of (score, id) pairs, so row order cannot leak through
            # the ranking. The output now factors through the intended
            # equivalence instead of merely being asserted to.
            order = sorted(cut, key=lambda i: (-float(sims[i]), self._chunk_ids[i]))
            return [
                SearchHit(
                    chunk_id=self._chunk_ids[i],
                    score=float(sims[i]),
                    meta=self._chunk_meta[i],
                )
                for i in order
                if sims[i] > 0
            ]

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    @property
    def vocab_size(self) -> int:
        return len(self._vocab)

    @property
    def doc_count(self) -> int:
        return self._tf.shape[0]


# Module-level singleton so the mapper and the API both touch the
# same in-memory copy. The store is keyed by directory; pass an
# explicit ``store_dir`` to ``get_default_store`` to override the
# location for tests.

_DEFAULT_DIR = os.path.normpath(
    os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        "..", "..", "snapshots", "global_tfidf",
    )
)
_default_store: Optional[GlobalTfidfStore] = None
_default_lock = threading.Lock()


def get_default_store(store_dir: Optional[str] = None) -> GlobalTfidfStore:
    global _default_store
    if store_dir is None:
        store_dir = os.environ.get("WFH_TFIDF_DIR", _DEFAULT_DIR)
    with _default_lock:
        if _default_store is None or _default_store.store_dir != os.path.abspath(store_dir):
            _default_store = GlobalTfidfStore(store_dir)
        return _default_store
