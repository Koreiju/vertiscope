import logging
import os
import time
from collections import defaultdict
from threading import Lock
from typing import Dict, List, Set

_DEDUP_LOGGER = None

def get_dedup_logger() -> logging.Logger:
    global _DEDUP_LOGGER
    if _DEDUP_LOGGER is not None:
        return _DEDUP_LOGGER

    logger = logging.getLogger("dedup")
    logger.setLevel(logging.DEBUG)
    # Avoid propagation to root logger to prevent noise
    logger.propagate = False

    log_dir = os.environ.get("WFH_DEDUP_LOG_DIR", "logs")
    os.makedirs(log_dir, exist_ok=True)
    
    handler = logging.FileHandler(
        os.path.join(log_dir, "dedup.log"), mode="a", encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(process)d] %(levelname)s %(message)s"
    ))
    logger.addHandler(handler)
    _DEDUP_LOGGER = logger
    return logger

logger_stats = logging.getLogger("dedup_stats")

class DedupStatsCollector:
    """Accumulates chunk lifecycle events and writes aggregated stats every second.

    Enhanced to track unique patterns and provide a final summary."""

    def __init__(self, log_file: str = "logs/dedup_stats.log"):
        self._lock = Lock()
        self._last_flush = time.time()
        self._events = []                       # (timestamp, type, chunk_id, hash)
        self._chunks = {}                       # chunk_id -> chunk dict
        self._content_hash_index = defaultdict(set)  # content_hash -> set(chunk_id)
        self._pattern_set: Set[str] = set()     # all patterns seen
        self._setup_file_logger(log_file)

    def _setup_file_logger(self, path: str):
        import os
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        h = logging.FileHandler(path, mode="a")
        h.setFormatter(logging.Formatter("%(asctime)s %(message)s"))
        logger_stats.addHandler(h)
        logger_stats.setLevel(logging.DEBUG)
        logger_stats.propagate = False

    def record_event(self, event_type: str, chunk_id: str, content_hash: int):
        with self._lock:
            self._events.append((time.time(), event_type, chunk_id, content_hash))
            # Keep chunk index up to date
            if event_type in ("chunk_added", "chunk_replaced"):
                # The chunk dict is passed via record_chunk separately
                pass
            elif event_type == "chunk_removed":
                self._chunks.pop(chunk_id, None)
                # Also remove from content hash index
                for h, ids in list(self._content_hash_index.items()):
                    ids.discard(chunk_id)
                    if not ids:
                        del self._content_hash_index[h]

    def record_chunk(self, chunk: dict):
        """Register the full chunk dict; used after add/replace."""
        cid = chunk.get("chunk_id")
        rhash = chunk.get("content_hash")
        pattern = chunk.get("pattern", "")
        if cid and rhash is not None:
            with self._lock:
                self._chunks[cid] = chunk
                self._content_hash_index[rhash].add(cid)
                if pattern:
                    self._pattern_set.add(pattern)

    def flush_if_due(self):
        """Called from the main loop; prints stats every second."""
        now = time.time()
        if now - self._last_flush < 1.0:
            return
        with self._lock:
            if not self._events:
                return
            added = sum(1 for _, t, _, _ in self._events if t == "chunk_added")
            replaced = sum(1 for _, t, _, _ in self._events if t == "chunk_replaced")
            removed = sum(1 for _, t, _, _ in self._events if t == "chunk_removed")
            n_chunks = len(self._chunks)
            n_hashes = len(self._content_hash_index)
            n_patterns = len(self._pattern_set)
            collisions = sum(1 for ids in self._content_hash_index.values() if len(ids) > 1)
            logger_stats.info(
                "STATS chunks=%d hashes=%d patterns=%d collisions=%d +added=%d ~replaced=%d -removed=%d",
                n_chunks, n_hashes, n_patterns, collisions, added, replaced, removed
            )
            self._events.clear()
            self._last_flush = now

    def log_final_summary(self):
        """Write a final breakdown of every pattern and its chunks to the stats log."""
        with self._lock:
            # Build per-pattern aggregation
            pattern_to_chunks: Dict[str, List[dict]] = {}
            for cid, chunk in self._chunks.items():
                pat = chunk.get("pattern", "?")
                pattern_to_chunks.setdefault(pat, []).append(chunk)

            logger_stats.info("FINAL PATTERN SUMMARY (%d patterns)", len(pattern_to_chunks))
            for pat in sorted(pattern_to_chunks.keys()):
                chunks_for_pat = pattern_to_chunks[pat]
                total_members = sum(c.get("commutation_count", 0) for c in chunks_for_pat)
                logger_stats.info(
                    "  PATTERN %s -> %d chunks, %d total members",
                    pat, len(chunks_for_pat), total_members
                )

    def audit_collisions(self):
        """Log every content hash that appears in multiple chunks, with nesting analysis."""
        with self._lock:
            for h, cids in self._content_hash_index.items():
                if len(cids) < 2:
                    continue
                # Gather chunk dicts
                chunks = [self._chunks[cid] for cid in cids if cid in self._chunks]
                if len(chunks) < 2:
                    continue
                # Check nesting
                nested_info = []
                for i in range(len(chunks)):
                    for j in range(i+1, len(chunks)):
                        a, b = chunks[i], chunks[j]
                        a_members = set(a.get("member_xpaths", []))
                        b_members = set(b.get("member_xpaths", []))
                        a_in_b = _all_members_inside(a_members, b_members)
                        b_in_a = _all_members_inside(b_members, a_members)
                        if a_in_b or b_in_a:
                            nested_info.append(f"{a['chunk_id']} nested in {b['chunk_id']}" if a_in_b else f"{b['chunk_id']} nested in {a['chunk_id']}")
                        else:
                            # Not nested – suspect depth guard or different branches
                            depth_a = _xpath_depth(next(iter(a_members))) if a_members else 0
                            depth_b = _xpath_depth(next(iter(b_members))) if b_members else 0
                            nested_info.append(f"{a['chunk_id']} NOT NESTED with {b['chunk_id']} (depths {depth_a},{depth_b})")
                logger_stats.warning("COLLISION hash=%s chunks=%s | %s", h, cids, "; ".join(nested_info))


def _all_members_inside(inner: Set[str], outer: Set[str]) -> bool:
    for xp in inner:
        if not any(xp.startswith(ox + "/") or xp == ox for ox in outer):
            return False
    return True

def _xpath_depth(xpath: str) -> int:
    return xpath.count('/')