# NOTE (vertiscope): the Kuzu Cypher IO (persist_trie / load_trie /
# get_latest_version_id / list_versions) was dropped in the extraction.
# This module is now a pure in-memory trie *builder*; persistence lives
# in vertiscope.store (SQLite).
"""
trie_persistence.py — Persist a content-tagged Patricia trie to KuzuDB.

The trie is the *single authoritative structural record* of a page. Each
``TrieVersion`` corresponds to one scan of one URL; each ``TriePattern``
is one unique generalized-xpath inside that version.

Key ideas
---------
* Pattern keys (``TriePattern.pattern``) are generalized xpaths — indices
  stripped. ``/div[2]/ul/li[3]`` and ``/div[5]/ul/li[9]`` collapse to the
  same pattern. The ``commutation_count`` tracks how many concrete xpaths
  instantiate the pattern.
* ``tag_set`` stores the union of content categories observed across all
  instances of a pattern (e.g. ``["text.visible", "media.images"]``).
* ``subtree_hash`` is a Merkle-style hash computed post-order:
  ``sha1(self_hash | sorted(child_subtree_hashes))``. Two versions that
  share a subtree hash are structurally identical for their whole subtree
  — this is what lets the diff skip unchanged regions.
* ``parent_pattern_id`` preserves trie structure so we can reconstitute
  the full trie with a single traversal query.

This module does **not** know about HTML or Selenium. It consumes the
nested dict produced by :class:`vertiscope.core.xpath_tree_builder.XPathTreeBuilder`
and emits Kuzu rows.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

from vertiscope.core.xpath_utils import generalize_xpath


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass
class PatternRow:
    """A single row destined for the TriePattern table."""

    pattern_id: str
    version_id: str
    pattern: str
    representative_xpath: str
    parent_pattern_id: str  # empty string for the root
    tag_set: List[str]
    commutation_count: int
    depth: int
    has_shadow_boundary: bool
    char_count: int
    self_hash: str
    subtree_hash: str
    member_xpaths: List[str] = field(default_factory=list)


@dataclass
class TrieVersionRow:
    """The TrieVersion row header."""

    version_id: str
    url: str
    snapshot_id: str
    parent_version_id: str
    pattern_count: int
    content_pattern_count: int
    total_char_count: int
    root_hash: str
    created_at: str


@dataclass
class BuiltTrie:
    """Everything needed to persist or compare a trie version."""

    version: TrieVersionRow
    patterns: List[PatternRow]
    root_pattern_id: str

    # Helper lookups populated by :func:`build_trie_from_tree`
    by_pattern_id: Dict[str, PatternRow] = field(default_factory=dict)
    by_pattern_key: Dict[str, PatternRow] = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Tree -> flattened rows
# ---------------------------------------------------------------------------


def _tag_set_stable(tags: Iterable[str]) -> List[str]:
    """Deterministic sorted, de-duplicated tag list."""
    seen = set()
    out: List[str] = []
    for t in tags:
        if t in seen:
            continue
        seen.add(t)
        out.append(t)
    out.sort()
    return out


def _self_hash(pattern: str, tag_set: List[str], commutation_count: int) -> str:
    """Hash of a single pattern node's intrinsic properties."""
    payload = json.dumps(
        {"p": pattern, "t": tag_set, "n": commutation_count},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha1(payload).hexdigest()[:16]


def _subtree_hash(self_hash: str, child_subtree_hashes: List[str]) -> str:
    """Merkle hash: self plus sorted children."""
    payload = self_hash + "|" + ",".join(sorted(child_subtree_hashes))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


def _pattern_id(version_id: str, pattern: str) -> str:
    return hashlib.sha1(f"{version_id}|{pattern}".encode("utf-8")).hexdigest()[:20]


_COLUMN_CACHE: Dict[Tuple[int, str], set] = {}


def _has_shadow_boundary(pattern: str) -> bool:
    """Whether the xpath crosses a shadow root boundary anywhere along its path."""
    return "#shadow-root" in pattern or "shadow::" in pattern


def build_trie_from_tree(
    tree: Dict[str, Any],
    url: str,
    snapshot_id: str,
    parent_version_id: str = "",
    version_id: Optional[str] = None,
    now: Optional[str] = None,
) -> BuiltTrie:
    """
    Flatten an ``XPathTreeBuilder`` output into a ``BuiltTrie`` of rows.

    The ``tree`` dict is the nested structure produced by
    ``XPathTreeBuilder.build()`` — keys are path segments, values are
    nested dicts that carry ``_xpath`` and (optionally) ``_content``.

    Each node in the nested tree corresponds to *one* generalized pattern.
    Siblings sharing a pattern are coalesced; their xpaths are recorded in
    ``commutation_count`` and one representative is kept in
    ``representative_xpath``.
    """

    version_id = version_id or _mk_version_id(url, snapshot_id)
    now = now or time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    # First pass: collect instance xpaths + tags per generalized pattern.
    # (pattern -> {xpaths, tags, parent_patterns, depth})
    pattern_bucket: Dict[str, Dict[str, Any]] = {}

    def _walk(node: Dict[str, Any], parent_pattern: str, depth: int) -> None:
        for key, child in node.items():
            if key.startswith("_") or not isinstance(child, dict):
                continue
            child_xp = child.get("_xpath", key)
            child_pat = generalize_xpath(child_xp)
            bucket = pattern_bucket.setdefault(
                child_pat,
                {
                    "xpaths": [],
                    "tags": set(),
                    "parent_patterns": set(),
                    "depth": depth,
                    "max_depth": depth,
                    "shadow": False,
                },
            )
            bucket["xpaths"].append(child_xp)
            for cat in child.get("_content", []) or []:
                bucket["tags"].add(cat)
            bucket["parent_patterns"].add(parent_pattern)
            bucket["max_depth"] = max(bucket["max_depth"], depth)
            if _has_shadow_boundary(child_xp):
                bucket["shadow"] = True
            _walk(child, child_pat, depth + 1)

    # Top-level: iterate the tree's real children
    synthetic_root_pattern = "/"
    _walk(tree, synthetic_root_pattern, depth=1)

    # Each pattern may have multiple parent patterns across instances
    # (rare but possible when the trie collapses differently for
    # different instances). We pick the *shallowest* parent pattern as
    # the canonical parent so the tree is well-founded.
    parent_depth: Dict[str, int] = {synthetic_root_pattern: 0}
    # Assign depths iteratively by fixed-point over parent relations.
    # We bound the loop by pattern count to guarantee termination.
    changed = True
    pass_count = 0
    while changed and pass_count < 16:
        changed = False
        pass_count += 1
        for pat, info in pattern_bucket.items():
            # Find the minimum known parent depth
            candidate_depth = None
            for pp in info["parent_patterns"]:
                if pp in parent_depth:
                    d = parent_depth[pp] + 1
                    if candidate_depth is None or d < candidate_depth:
                        candidate_depth = d
            if candidate_depth is not None:
                old = parent_depth.get(pat)
                if old is None or candidate_depth < old:
                    parent_depth[pat] = candidate_depth
                    changed = True
            elif pat not in parent_depth and synthetic_root_pattern in info["parent_patterns"]:
                parent_depth[pat] = 1
                changed = True

    # Sort patterns from deepest to shallowest so we can compute subtree hashes post-order.
    patterns_sorted = sorted(
        pattern_bucket.keys(),
        key=lambda p: (-parent_depth.get(p, 0), p),
    )

    # Build children map under the chosen canonical parent.
    children_map: Dict[str, List[str]] = {}
    canonical_parent: Dict[str, str] = {}
    for pat, info in pattern_bucket.items():
        # Pick the parent with the smallest recorded depth
        best_pp = synthetic_root_pattern
        best_d = None
        for pp in info["parent_patterns"]:
            d = parent_depth.get(pp)
            if d is None:
                continue
            if best_d is None or d < best_d:
                best_d = d
                best_pp = pp
        canonical_parent[pat] = best_pp
        children_map.setdefault(best_pp, []).append(pat)

    # Compute pattern IDs up front
    pat_ids: Dict[str, str] = {pat: _pattern_id(version_id, pat) for pat in pattern_bucket}

    # Post-order subtree hashes
    subtree_hashes: Dict[str, str] = {}
    self_hashes: Dict[str, str] = {}

    for pat in patterns_sorted:
        info = pattern_bucket[pat]
        tags = _tag_set_stable(info["tags"])
        commutation = len(info["xpaths"])
        s_hash = _self_hash(pat, tags, commutation)
        self_hashes[pat] = s_hash
        child_hashes = [subtree_hashes[c] for c in children_map.get(pat, []) if c in subtree_hashes]
        subtree_hashes[pat] = _subtree_hash(s_hash, child_hashes)

    # Build the rows
    rows: List[PatternRow] = []
    for pat, info in pattern_bucket.items():
        tags = _tag_set_stable(info["tags"])
        xpaths = sorted(info["xpaths"])
        rep_xp = xpaths[0]
        parent_pat = canonical_parent[pat]
        parent_id = pat_ids.get(parent_pat, "")
        rows.append(
            PatternRow(
                pattern_id=pat_ids[pat],
                version_id=version_id,
                pattern=pat,
                representative_xpath=rep_xp,
                parent_pattern_id=parent_id,
                tag_set=tags,
                commutation_count=len(info["xpaths"]),
                depth=parent_depth.get(pat, 0),
                has_shadow_boundary=info["shadow"],
                char_count=0,  # filled in by pipeline if a text provider is supplied
                self_hash=self_hashes[pat],
                subtree_hash=subtree_hashes[pat],
                member_xpaths=xpaths,
            )
        )

    # Root-of-trie hash: digest of the sorted children of the synthetic root.
    top_children = children_map.get(synthetic_root_pattern, [])
    root_hash = _subtree_hash("root", [subtree_hashes[c] for c in top_children if c in subtree_hashes])

    content_pattern_count = sum(1 for r in rows if r.tag_set)
    total_char_count = sum(r.char_count for r in rows)

    version = TrieVersionRow(
        version_id=version_id,
        url=url,
        snapshot_id=snapshot_id,
        parent_version_id=parent_version_id,
        pattern_count=len(rows),
        content_pattern_count=content_pattern_count,
        total_char_count=total_char_count,
        root_hash=root_hash,
        created_at=now,
    )

    # Pick the "root pattern" for traversal convenience — the shallowest.
    root_candidates = [r for r in rows if r.parent_pattern_id == ""]
    root_candidates.sort(key=lambda r: (r.depth, r.pattern))
    root_pattern_id = root_candidates[0].pattern_id if root_candidates else ""

    built = BuiltTrie(
        version=version,
        patterns=rows,
        root_pattern_id=root_pattern_id,
    )
    built.by_pattern_id = {r.pattern_id: r for r in rows}
    built.by_pattern_key = {r.pattern: r for r in rows}
    return built


def _mk_version_id(url: str, snapshot_id: str) -> str:
    """Deterministic-ish version id: url + snapshot + uuid4 tail for uniqueness."""
    salt = uuid.uuid4().hex[:8]
    return hashlib.sha1(f"{url}|{snapshot_id}|{salt}".encode("utf-8")).hexdigest()[:20]


# ---------------------------------------------------------------------------
# Kuzu persistence
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
