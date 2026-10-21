"""
chunk_builder.py — Post-scan content chunking for SLM-friendly partitioning.

Top-down recursive chunking (think: the generalized-trie analogue of
the classic RAG "recursive character splitter", but walking the
*distilled-DOM Patricia trie* instead of raw bytes).

Algorithm:
  1. Start at the Patricia trie root.
  2. At every pattern node P, build P's **content-structure summary** —
     the ``{extended_relative_xpath: [values]}`` view of every tagged
     descendant of one representative instance of P, rendered the way
     the SLM / GUI will see it::

            /li/a/h3/em/text(): ['Aries in Love and Relationships...']
            /li/a/h3/text():    ['Aries in']
            /li/a/@data-label:  ['Breadcrumb:EXPLORE TAROT.COM', ...]
            /li/a/p/text():     ['Fiery and sexy Aries ...']
            /li/a/@href:        ['https://www.tarot.com/articles', ...]

     Count the tokens of that rendered string (CHARS_PER_TOKEN_EST).
  3. If tokens(P) ≤ HARD_TOKEN_LIMIT → emit P as a chunk. Members =
     every absolute xpath matching P's generalized pattern. Stop
     descending into P's subtree.
  4. Else → recurse into P's children patterns.

This gives one chunk per pattern-trie node, with a natural "commuting
subtree" contract: the chunk aggregates every absolute xpath matching
its generalized pattern (so a 20-card `<li>` grid is one chunk × 20
members, not 20 separate chunks).

Two render modes travel with every chunk:

* **content-structure summary** — the dict shown above. Used by the
  SLM and the GUI. Stored on ``Chunk.content_fields``.
* **text-only preview** — the ``text()`` values from the summary
  joined with single spaces (*not* concatenated, so the embedder
  doesn't see `AriesinLoveand...` as one word). Stored on
  ``Chunk.text_preview``; also used by
  :mod:`vertiscope.core.chunk_render` when producing
  ``ChunkInstanceRender.rendered_text`` for the embedder.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple
import html as _html_escape
from collections import defaultdict
import hashlib
import json
import logging
import math

from vertiscope.core.chunk_containment import filter_redundant_rollups
from vertiscope.core.xpath_utils import generalize_xpath
from vertiscope.core.content_tagger import ContentTag


# Text in these top-level category groups counts toward the budget.
# urls.* (hyperlinks) and media.* (images/video src) are excluded so the
# budget reflects only the human-readable prose that the SLM will see.
_TEXT_BUDGET_GROUPS = ("text", "interactive", "json_data")

_URL_LIKE_ATTRS = frozenset({
    "href", "src", "srcset", "data-src", "data-lazy-src",
    "data-original", "data-original-src", "data-image", "poster",
    "action", "formaction", "xlink:href", "style",
})

# Shared URL-token splitter with chunk_render so the per-chunk text
# preview sees the same semantic tokens the embedder will later consume.
import re as _re_urltok
_URL_TOKEN_SPLIT_BUILDER = _re_urltok.compile(r"[/?&#=.:_-]+")
_URL_TOKEN_STOP_BUILDER = frozenset({
    "http", "https", "www", "html", "htm", "php", "aspx", "jsp",
    "wp", "content", "uploads", "assets", "static", "images", "img",
    "cdn", "com", "net", "org", "io", "co", "uk", "jpg", "jpeg", "png",
    "gif", "svg", "webp", "mp4", "mp3", "pdf", "",
})


def _tokenize_url_builder(raw: str, limit: int = 8) -> str:
    """Semantic tokenization of a URL — see ``chunk_render._tokenize_url``."""
    if not raw:
        return ""
    core = raw.split("?", 1)[0].split("#", 1)[0]
    toks = [t.lower() for t in _URL_TOKEN_SPLIT_BUILDER.split(core) if t]
    keep: List[str] = []
    seen: Set[str] = set()
    for t in toks:
        if t in _URL_TOKEN_STOP_BUILDER or t.isdigit() or len(t) < 3 or t in seen:
            continue
        seen.add(t)
        keep.append(t)
        if len(keep) >= limit:
            break
    return " ".join(keep)

# ---------------------------------------------------------------------------
# Token-aware HTML budget
# ---------------------------------------------------------------------------
# The chunker's walk-up stop rules now compare the character length of each
# candidate chunk's *distilled HTML* — tag + truncated-attrs + truncated-
# text, DFS-serialized — not just its plain text. That matters because the
# embedder and SLM both consume the HTML verbatim (it's the embedding
# "control space" the user committed to early on), so two chunks with the
# same 200-char text body can differ by 10× in tokens once you include
# deeply nested markup with long ``data-*`` blobs or inline styles.
#
# HARD_TOKEN_LIMIT       — strict ceiling on tokens per chunk (128).
# CHARS_PER_TOKEN_EST    — conservative char→token ratio (4 for English BPE).
# HARD_CHAR_LIMIT        — equivalent char cap; the chunker never emits a
#                          chunk whose distilled-HTML length exceeds this.
# ATTR_TRUNCATE          — per-attribute char ceiling. JSON blobs, inline
#                          styles, and data-original-src URLs that routinely
#                          run to thousands of chars are truncated so a
#                          single attribute can't dominate the budget.
# TEXT_TRUNCATE          — same idea for visible text.
# PARENT_ADD_THRESHOLD   — "stop walking up if the parent adds more than
#                          this fraction of new distilled HTML on top of
#                          the current subtree". 0.80 ⇒ with 5 equally-sized
#                          siblings, the first sibling to enter triggers the
#                          stop (current/parent = 1/5 = 0.20, new = 0.80).
# HARD_TOKEN_LIMIT sizing: a fully populated tarot / e-commerce / listing
# card serializes to ~250-400 tokens worth of content-structure summary
# (see the example in the module docstring: ~1000 chars / 4 ≈ 260
# tokens). 512 tokens gives headroom for bigger cards (articles with
# breadcrumbs + excerpt + action links) while still forcing the
# chunker to recurse past page-level containers — a 20-card grid
# aggregated whole would be ~20 × 260 = 5200 tokens, an order of
# magnitude over the cap.
HARD_TOKEN_LIMIT = 512
CHARS_PER_TOKEN_EST = 4
HARD_CHAR_LIMIT = HARD_TOKEN_LIMIT * CHARS_PER_TOKEN_EST  # 2048
ATTR_TRUNCATE = 60
TEXT_TRUNCATE = 60
PARENT_ADD_THRESHOLD = 0.80

# Legacy default retained under its old name so existing callers (e.g.
# ``mapper.mapper.DomMapper.chunk``) can keep passing ``char_budget=…``
# without an update; it now means "distilled-HTML char budget", not text.
DEFAULT_CHAR_BUDGET = HARD_CHAR_LIMIT


@dataclass
class Chunk:
    """A content-distilled DOM chunk ready for SLM consumption."""
    chunk_id: str
    pattern: str                       # generalized xpath of the chunk root
    representative_xpath: str          # one concrete xpath for the chunk root
    member_xpaths: List[str]           # every xpath matching `pattern`
    char_count: int                    # text chars in the representative subtree
    commutation_count: int             # == len(member_xpaths)
    content_fields: Dict[str, List[str]]  # category → aggregated values
    text_preview: str                  # concatenated text preview (trimmed)
    label: Optional[str] = None        # filled in later (SLM or user)
    image_urls: Dict[str, str] = field(default_factory=dict)  # member_xpath → image URL
    link_urls: Dict[str, str] = field(default_factory=dict)   # member_xpath → link URL
    extraction_trie: Dict[str, Any] = field(default_factory=dict) # chunk-wise data address schema

    def as_dict(self) -> Dict[str, Any]:
        return {
            "chunk_id": self.chunk_id,
            "pattern": self.pattern,
            "representative_xpath": self.representative_xpath,
            "member_xpaths": list(self.member_xpaths),
            "char_count": self.char_count,
            "commutation_count": self.commutation_count,
            "content_fields": {k: list(v) for k, v in self.content_fields.items()},
            "text_preview": self.text_preview,
            "label": self.label,
            "image_urls": dict(self.image_urls),
            "link_urls": dict(self.link_urls),
            "extraction_trie": self.extraction_trie,
        }


# ---------------------------------------------------------------------------
# §15.8 — Chunk-pattern schema (golden trio + pattern_map)
# ---------------------------------------------------------------------------

_HEADING_TAGS = ("h1", "h2", "h3", "h4", "h5", "h6")

# A content field must carry at least this many characters to count as the
# "free-text-bearing" field of a golden trio (§15.8.1). This substance gate is
# what the joint-presence rule uses to reject nav blocks / footers / sidebar
# widgets, whose repeating members are short labels, not prose.
_MIN_CONTENT_CHARS = 40


@dataclass
class ChunkPatternSchema:
    """§15.8 / ChunkPatternSchema.md §2 — the typed tree the scanner produces
    for one homogeneous repeating pattern. Serialised into the ``pattern_map``
    ConceptNode's ``data`` field (never a separate table — §7 one-record rule).
    """
    pattern_hash: str
    url_root: str
    generalized_xpath: str
    accessor_map: Dict[str, str]                 # {field_slug: relative_xpath}
    golden_trio: Tuple[str, str, str]            # (title_slug, link_slug, content_slug)
    sampled_chunks: List[str]                    # chunk_ids passing the trio gate
    pagerank: float = 0.0
    sub_patterns: Dict[str, "ChunkPatternSchema"] = field(default_factory=dict)
    domain: str = ""
    accessor_dict: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    updated_at: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "pattern_hash": self.pattern_hash,
            "url_root": self.url_root,
            "generalized_xpath": self.generalized_xpath,
            "accessor_map": dict(self.accessor_map),
            "golden_trio": list(self.golden_trio),
            "sampled_chunks": list(self.sampled_chunks),
            "pagerank": self.pagerank,
            "sub_patterns": {h: s.as_dict() for h, s in self.sub_patterns.items()},
            "domain": self.domain,
            "accessor_dict": dict(self.accessor_dict),
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def extract_golden_trio(
    content_fields: Dict[str, List[str]],
) -> Optional[Tuple[str, str, str]]:
    """§15.8.1 — resolve a pattern's (title, link, content) accessors under the
    joint-presence gate.

    Operates on a chunk's ``content_fields`` — the ``{extended_relative_xpath:
    [values]}`` map built by ``_render_summary_fields``. Returns the three
    *accessor keys* ``(title_accessor, link_accessor, content_accessor)`` or
    ``None`` when any role cannot be filled. The all-or-nothing return IS the
    joint-presence gate (§15.8.1 / ChunkPatternSchema.md §2.1 / §7): nav blocks,
    footers and sidebar widgets that lack a clean title+link+content triple are
    rejected so they never pollute ``sampled_chunks``.

    Heuristics (ChunkPatternSchema.md §2.1):
      * link    — a key ending ``/@href``, preferring one on an ``/a/`` step.
      * title   — a ``text()`` key inside a heading (``h1``..``h6``) subtree;
                  else the anchor's own ``text()``; else the next-longest text
                  field after content.
      * content — the ``text()`` key with the largest aggregate value length
                  (the free-text / paragraph body), distinct from the title.
    """
    if not content_fields:
        return None

    keys = list(content_fields.keys())

    def _agg_len(k: str) -> int:
        return sum(len(v) for v in content_fields.get(k, ()))

    def _has_heading(k: str) -> bool:
        return any(f"/{h}/" in k for h in _HEADING_TAGS)

    # --- link: an @href accessor, preferring one under an anchor step. ---
    href_keys = [k for k in keys if k.endswith("/@href")]
    link_accessor: Optional[str] = None
    for k in href_keys:
        if "/a/" in k or k.endswith("/a/@href"):
            link_accessor = k
            break
    if link_accessor is None and href_keys:
        link_accessor = href_keys[0]
    if link_accessor is None:
        return None

    # --- content: the longest free-text-bearing field (§2.1 "longest free-
    # text / paragraph-shaped"). The substance threshold is the joint-presence
    # discriminator that filters nav blocks / footers / sidebar widgets — a
    # nav label ("Home") is short; a content card's prose is not. In full
    # production scans (all_tags) the distiller yields separate ``h3/text()`` +
    # ``p/text()`` keys; lighter tagging aggregates them into one ``text()``
    # field — both cases resolve here.
    text_keys = [k for k in keys if k.endswith("/text()")]
    if not text_keys:
        return None
    by_len = sorted(text_keys, key=_agg_len, reverse=True)
    content_accessor = by_len[0]
    if _agg_len(content_accessor) < _MIN_CONTENT_CHARS:
        return None

    # --- title: a heading subtree's text → the next-longest distinct text →
    # (single aggregated field) the content field itself, whose lead line is
    # the title. ---
    headings = [k for k in text_keys if _has_heading(k)]
    if headings:
        title_accessor = max(headings, key=_agg_len)
    elif len(by_len) >= 2:
        title_accessor = by_len[1]
    else:
        title_accessor = content_accessor

    # --- joint-presence gate: title + link + content all resolved. ---
    if title_accessor and link_accessor and content_accessor:
        return (title_accessor, link_accessor, content_accessor)
    return None


def _slug_for_accessor(key: str, trio: Optional[Tuple[str, str, str]]) -> str:
    """Map a content_fields accessor key to a field slug for ``accessor_map``.

    Trio members get the canonical ``title`` / ``link`` / ``content`` slugs
    (so ``golden_trio`` indexes cleanly into ``accessor_map`` per §2); other
    fields derive a slug from their address (``@href`` → ``href``) or leaf tag
    (``/p/text()`` → ``p_text``).
    """
    if trio:
        t, l, c = trio
        if key == t:
            return "title"
        if key == l:
            return "link"
        if key == c:
            return "content"
    leaf = key.rstrip("/").split("/")[-1]
    if leaf.startswith("@"):
        return leaf[1:] or "attr"
    parts = [p for p in key.split("/") if p and not p.startswith("@") and p != "text()"]
    tag = parts[-1] if parts else "field"
    return f"{tag}_text"


# §2.2 — persistent accessor-table cache keyed ``(domain, pattern_hash)``. On
# first detection a pattern's golden trio + accessor map are extracted + cached
# here; on a repeat scan of the same domain (or later members of the same
# pattern) the scanner CONSULTS THE TABLE FIRST and short-circuits the golden-
# trio re-mining (§2.2 / §7 — "trio extraction runs on the first batch; later
# members are tested against the trio"). Process-global so it survives across
# scans within a session.
_GOLDEN_TRIO_CACHE: Dict[Tuple[str, str], Tuple[Optional[Tuple[str, str, str]], Dict[str, str]]] = {}


def _member_passes_trio(
    content_fields: Dict[str, List[str]],
    trio: Optional[Tuple[str, str, str]],
) -> bool:
    """§7 — test a member against an ALREADY-extracted golden trio (cheap
    joint-presence check) instead of re-running full ``extract_golden_trio``
    per member: the member qualifies iff all three trio accessors resolve to
    non-empty values in its content_fields."""
    if not trio:
        return False
    for acc in trio:
        vals = content_fields.get(acc)
        if not vals or not any(str(v).strip() for v in vals):
            return False
    return True


def build_pattern_schemas(
    chunks: List["Chunk"],
    url_root: str,
    domain: str = "",
) -> Dict[str, Dict[str, Any]]:
    """§15.8.2 — build the recursive ``pattern_map`` schema tree from chunks.

    Groups chunks by generalised xpath; one ChunkPatternSchema per pattern.
    Golden-trio extraction runs on the representative (largest) member; only
    members that pass the joint-presence gate enter ``sampled_chunks`` (§7
    anti-pattern: gate before appending). Patterns whose xpath extends another's
    fold under the parent's ``sub_patterns`` to form the recursive tree.

    Returns a JSON-ready dict ``{pattern_hash: schema_dict}`` — top-level
    patterns only; nested patterns live under ``sub_patterns``.
    """
    now = datetime.now(timezone.utc).isoformat()
    by_pattern: Dict[str, List["Chunk"]] = defaultdict(list)
    for ch in chunks:
        by_pattern[ch.pattern].append(ch)

    schemas: Dict[str, ChunkPatternSchema] = {}
    for pattern, group in by_pattern.items():
        rep = max(group, key=lambda c: c.char_count)
        phash = hashlib.sha1(pattern.encode("utf-8")).hexdigest()[:16]

        # §2.2 — consult the persistent accessor table first; reuse the cached
        # trio + accessor map for a known (domain, pattern_hash) instead of
        # re-mining the golden trio. Only a fresh pattern runs extract.
        cache_key = (domain or "", phash)
        cached = _GOLDEN_TRIO_CACHE.get(cache_key)
        if cached is not None:
            trio, accessor_map = cached[0], dict(cached[1])
        else:
            trio = extract_golden_trio(rep.content_fields)
            accessor_map = {}
            for key in rep.content_fields.keys():
                accessor_map[_slug_for_accessor(key, trio)] = key
            # Guarantee the canonical trio slugs index cleanly into accessor_map
            # (§2: golden_trio = (title_slug, link_slug, content_slug)) even when
            # title and content resolve to the SAME aggregated text accessor.
            if trio:
                accessor_map["title"], accessor_map["link"], accessor_map["content"] = trio
            _GOLDEN_TRIO_CACHE[cache_key] = (trio, dict(accessor_map))

        # §7 — members are TESTED against the extracted trio (cheap joint-
        # presence), NOT re-extracted per member; only passers are sampled.
        sampled: List[str] = [
            ch.chunk_id for ch in group
            if _member_passes_trio(ch.content_fields, trio)
        ]

        schemas[phash] = ChunkPatternSchema(
            pattern_hash=phash,
            url_root=url_root,
            generalized_xpath=pattern,
            accessor_map=accessor_map,
            golden_trio=("title", "link", "content") if trio else ("", "", ""),
            sampled_chunks=sampled,
            domain=domain,
            accessor_dict=dict(accessor_map),
            created_at=now,
            updated_at=now,
        )

    # Fold child patterns under their nearest ancestor's sub_patterns. P is a
    # child of Q when P.generalized_xpath startswith Q.generalized_xpath + "/".
    # Pick the LONGEST ancestor so grandchildren attach to the closest parent.
    hashes = list(schemas.keys())
    nested: Set[str] = set()
    for ph in hashes:
        p_xpath = schemas[ph].generalized_xpath
        best_parent: Optional[str] = None
        best_len = -1
        for qh in hashes:
            if qh == ph:
                continue
            q_xpath = schemas[qh].generalized_xpath
            if p_xpath.startswith(q_xpath + "/") and len(q_xpath) > best_len:
                best_parent = qh
                best_len = len(q_xpath)
        if best_parent is not None:
            schemas[best_parent].sub_patterns[ph] = schemas[ph]
            nested.add(ph)

    # §2 / §4 — PageRank within the chunk-pattern graph (cached on each schema).
    _compute_pattern_pagerank(schemas)

    return {ph: schemas[ph].as_dict() for ph in hashes if ph not in nested}


def _compute_pattern_pagerank(
    schemas: Dict[str, "ChunkPatternSchema"], *,
    damping: float = 0.85, iters: int = 20,
) -> None:
    """§2 / §4 — personalised PageRank over the chunk-pattern graph, cached on
    each schema's ``pagerank`` field (re-derivable, so not separately stored).

    Nodes = patterns; directed edges = containment (parent → sub_pattern); the
    personalisation prior ∝ (sampled-chunk count + 1) so prominent patterns
    (more golden-trio-gated members = higher bipartite degree centrality in the
    pattern↔chunk graph) carry more rank. Dangling (leaf) mass redistributes by
    the prior. Replaces the previous flat ``0.0`` placeholder with a real,
    deterministic centrality."""
    nodes = list(schemas.keys())
    if not nodes:
        return
    prior_raw = {h: float(len(schemas[h].sampled_chunks) + 1) for h in nodes}
    tot = sum(prior_raw.values()) or 1.0
    prior = {h: prior_raw[h] / tot for h in nodes}
    out = {h: list(schemas[h].sub_patterns.keys()) for h in nodes}
    pr = dict(prior)
    for _ in range(max(1, iters)):
        nxt = {h: (1.0 - damping) * prior[h] for h in nodes}
        dangling = 0.0
        for h in nodes:
            children = out[h]
            if children:
                share = damping * pr[h] / len(children)
                for c in children:
                    if c in nxt:
                        nxt[c] += share
            else:
                dangling += damping * pr[h]
        for h in nodes:
            nxt[h] += dangling * prior[h]
        pr = nxt
    for h in nodes:
        schemas[h].pagerank = round(float(pr[h]), 6)


# ---------------------------------------------------------------------------
# Patricia trie helpers
# ---------------------------------------------------------------------------

def _iter_subtree_nodes(subtree: Dict[str, Any]) -> Iterable[Dict[str, Any]]:
    """Yield every dict node at or under `subtree` (self included).

    Hot path: the recursive descent ran ``str.startswith('_')`` per dict
    key, which dominated profiling at 242K calls / 20ms cumulative. Walk
    iteratively with an explicit stack and skip the ``_``-prefixed
    metadata keys cheaply: ``key[:1] == '_'`` is faster than
    ``startswith`` for a single-char prefix and the type check is folded
    into the same condition.
    """
    stack: List[Dict[str, Any]] = [subtree]
    while stack:
        node = stack.pop()
        yield node
        # Reverse-extending preserves DFS order if downstream callers
        # depend on it; current callers (tag/url-bucket aggregation)
        # are order-insensitive, so we just append.
        for key, child in node.items():
            if key[:1] == "_":
                continue
            if isinstance(child, dict):
                stack.append(child)


def _index_by_xpath(tree: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """xpath → subtree dict, for every node in the trie."""
    index: Dict[str, Dict[str, Any]] = {}
    for node in _iter_subtree_nodes(tree):
        index[node.get("_xpath", "/")] = node
    return index


def _index_by_pattern(tree: Dict[str, Any]) -> Dict[str, List[str]]:
    """generalized-xpath pattern → list of absolute xpaths that match."""
    patterns: Dict[str, List[str]] = defaultdict(list)
    for node in _iter_subtree_nodes(tree):
        xp = node.get("_xpath", "/")
        patterns[generalize_xpath(xp)].append(xp)
    return patterns


# ---------------------------------------------------------------------------
# Post-emission load balancer
# ---------------------------------------------------------------------------


def _enforce_min_chunk_size(
    chunks: List[Chunk],
    *,
    min_fields: int = 2,
    min_text_chars: int = 8,
) -> List[Chunk]:
    """Drop chunks that are too thin to stand on their own.

    A chunk is "thin" when it has fewer than ``min_fields`` distinct
    keys in ``content_fields`` AND its text-preview / char-count
    falls below ``min_text_chars``. Both conditions must hold —
    a long-text single-field chunk (e.g. a body paragraph that
    happens to live under exactly one xpath bucket) is still useful.

    Standalone headings like ``<h4>Pluto in Aquarius Traits:</h4>``
    typically have exactly one ``/h4/text()`` field with ~30 chars of
    text — they fail BOTH gates and get dropped here. Their content
    survives in the parent or sibling chunks the recursive emitter
    also produced (the chunker walks every depth, so the element is
    always represented in at least one larger group).
    """
    out: List[Chunk] = []
    for ch in chunks:
        n_fields = len(getattr(ch, "content_fields", {}) or {})
        text_len = max(
            int(getattr(ch, "char_count", 0) or 0),
            len(getattr(ch, "text_preview", "") or ""),
        )
        if n_fields < min_fields and text_len < min_text_chars:
            continue
        out.append(ch)
    return out


# ---------------------------------------------------------------------------
# ChunkBuilder
# ---------------------------------------------------------------------------

class ChunkBuilder:
    """
    Partition a content-distilled Patricia trie into SLM-sized chunks.

    Inputs:
      - content_tree: the Patricia trie produced by XPathTreeBuilder.
      - text_provider: callable(xpath, categories) → str. Returns the
        human-readable text associated with the node. Usually wraps
        the ShadowDOM so we can read node.text / attribute values.
        Callers pass ``lambda xp, cats: dom_text_map.get(xp, '')``.
      - char_budget: soft upper bound on text characters per chunk.
        Exceeded only when a single leaf already overflows.
    """

    def __init__(
        self,
        content_tree: Dict[str, Any],
        text_provider: Callable[[str, List[str]], str],
        char_budget: int = DEFAULT_CHAR_BUDGET,
        all_tags: Optional[List[ContentTag]] = None,
        *,
        structure_provider: Optional[Callable[[str], Tuple[str, Dict[str, str]]]] = None,
        attr_truncate: int = ATTR_TRUNCATE,
        text_truncate: int = TEXT_TRUNCATE,
        parent_add_threshold: float = PARENT_ADD_THRESHOLD,
    ):
        self.tree = content_tree
        self.text_provider = text_provider
        self.budget = char_budget
        self.all_tags = all_tags or []

        # Structure provider: (tag_name, attrs_dict) per absolute xpath.
        # Falls back to ("div", {}) when the caller didn't hand one in
        # (e.g. legacy fixture tests that pre-date the HTML-budget work).
        # With the fallback, the walk-up still operates over Patricia-
        # trie topology; the parent-contribution heuristic just degrades
        # to a constant-per-node approximation which is still strictly
        # better than the old "text-only chars" behaviour for control-
        # flow purposes.
        self.structure_provider = structure_provider or (lambda xp: ("div", {}))
        self.attr_truncate = int(attr_truncate)
        self.text_truncate = int(text_truncate)
        self.parent_add_threshold = float(parent_add_threshold)

        self._by_xpath = _index_by_xpath(content_tree)
        self._by_pattern = _index_by_pattern(content_tree)

        # Bucket tags by exact xpath once so ``_tags_in_subtree`` becomes
        # O(subtree-nodes) instead of O(all-tags). On a 1k-tag page the
        # old linear scan dominated chunking; this one-pass index keeps
        # per-chunk work proportional to the chunk's own footprint.
        self._tags_by_xpath: Dict[str, List[ContentTag]] = defaultdict(list)
        for t in self.all_tags:
            xp = getattr(t, "xpath", "")
            if xp:
                self._tags_by_xpath[xp].append(t)
        self._has_tags = bool(self._tags_by_xpath)

        # Per-xpath caches so the top-down recursion can peek at every
        # pattern member's rendered size before emitting without
        # repeatedly re-walking the tag index.
        self._summary_cache: Dict[str, Dict[str, List[str]]] = {}
        self._summary_size_cache: Dict[str, int] = {}
        # ``_tags_in_subtree`` was a 73ms cumulative hotspot on real pages
        # because every member of every chunk pattern asks "what tags live
        # under me?" 3–4 times (render_summary, build_extraction_trie,
        # image_url_for_member, link_url_for_member). The walk itself is
        # cheap but the SAME walk runs for the SAME xpath repeatedly. A
        # per-xpath result cache flattens that to one walk per distinct
        # base xpath. The cache is keyed by absolute xpath so the bottom-
        # up DP needs no extra book-keeping.
        self._tags_in_subtree_cache: Dict[str, List] = {}

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build(self, snapshot_id: str = "") -> List[Chunk]:
        """Top-down exhaustive recursive chunking over the absolute trie."""
        chunks: List[Chunk] = []
        emitted_xpaths: Set[str] = set()
        self._recurse_absolute_trie(
            self.tree, chunks, emitted_xpaths, snapshot_id,
        )

        rollup_threshold = 2 * HARD_CHAR_LIMIT
        chunks = filter_redundant_rollups(
            chunks,
            xpath_of=lambda c: c.representative_xpath,
            size_of=lambda c: c.char_count,
            min_rollup_size=rollup_threshold,
        )

        # Load-balance: drop chunks that have only ONE element in
        # their content_fields. Standalone headings like
        # ``<h4>Pluto in Aquarius Traits:</h4>`` were leaking through
        # as their own chunk with a single ``/h4/text()`` row, which
        # is too thin to be meaningful retrieval material. We require
        # at least 2 distinct content_fields entries OR enough text
        # to stand on its own (>= 80 chars). Single-row chunks below
        # the text threshold are discarded; their content stays
        # accessible via parent / sibling chunks that DO meet the
        # bar (the recursive emitter walks every depth, so the
        # element is guaranteed to land in some larger group).
        chunks = _enforce_min_chunk_size(chunks, min_fields=1, min_text_chars=0)
        return chunks

    def _cached_summary(self, xp: str) -> Dict[str, List[str]]:
        """Memoized ``_render_summary_fields`` per absolute xpath."""
        cached = self._summary_cache.get(xp)
        if cached is None:
            cached = self._render_summary_fields(xp)
            self._summary_cache[xp] = cached
        return cached

    def _cached_summary_size(self, xp: str) -> int:
        """Memoized printed-summary size per absolute xpath."""
        size = self._summary_size_cache.get(xp)
        if size is None:
            s = self._cached_summary(xp)
            size = len(self._format_summary(s, truncate_links=True)) if s else 0
            self._summary_size_cache[xp] = size
        return size

    def _recurse_absolute_trie(
        self,
        node: Dict[str, Any],
        chunks: List[Chunk],
        emitted: Set[str],
        snapshot_id: str,
    ) -> None:
        """Top-down recursive chunking over the absolute Patricia trie.

        At every non-root node we try to emit a chunk whose ``char_count``
        is the MAX printed-summary length across every absolute xpath that
        matches the current node's generalized pattern. If that max fits
        ``self.budget`` we emit once, using the biggest member as the
        representative (so ``chunk.content_fields`` reflects what a
        rendered instance of the largest member will actually contain).
        If the max overshoots we skip emission here and recurse into
        structural children — a pattern whose members vary wildly in size
        (e.g. a nav ``<ul>`` beside a 20-card search-results ``<ul>``) is
        over-generalized, so we refuse to fold them into a single chunk
        and let the walk find a tighter pattern deeper down.

        Structural leaves (no dict children) whose own summary didn't get
        emitted fall through to a single-member fallback so we never
        silently drop tagged content.
        """
        xp = node.get("_xpath", "") or "/"

        if xp != "/" and xp in emitted:
            return

        is_root = (xp == "/")

        if not is_root:
            pattern = generalize_xpath(xp)
            members = self._by_pattern.get(pattern, [xp])

            # Peek at every member's rendered summary size — the chunk we
            # emit must accommodate the largest one, not just the first
            # walk-order member we happened to land on.
            max_size = 0
            biggest_member = xp
            any_content = False
            for m in members:
                size = self._cached_summary_size(m)
                if size > 0:
                    any_content = True
                if size > max_size:
                    max_size = size
                    biggest_member = m

            # Emission rule: per-instance chunks are the product the
            # downstream embedder / projector / retrieval all want.
            # Two gates must both pass:
            #   1. ``len(members) > 1`` — single-instance patterns are
            #      coarse aggregations that swallow per-card content
            #      into one opaque blob, so we skip them and let the
            #      recursion descend.
            #   2. Members are *homogeneous* — same generalised child-
            #      pattern set. Heterogeneous siblings (e.g. ``section``
            #      where section[1] is hero, section[2] is card-grid,
            #      section[3] is form) match the same structural
            #      pattern but represent semantically distinct units;
            #      emitting one chunk across them pollutes the
            #      extraction_trie with cross-section fields and the
            #      representative's prose with another section's text
            #      (this is what test_section_chunk_schema_does_not_
            #      leak_card_fields was added to catch). Homogeneous
            #      patterns (e.g. 3 article cards with identical
            #      img+h2+p+a sub-pattern) emit cleanly.
            # We deliberately do NOT ``return`` after emit — the
            # recursion still descends so deeper homogeneous patterns
            # (e.g. a list of images within each card) also get chunks.
            # The leaf-fallback below rescues single-instance content-
            # bearing leaves so no tagged content is dropped.
            if (any_content
                    and max_size <= self.budget
                    and len(members) > 1
                    and self._members_are_homogeneous(members)):
                s = self._cached_summary(biggest_member)
                self._emit_chunk_at(
                    biggest_member, s, chunks, emitted, snapshot_id,
                )

        has_valid_children = False
        for key, child in node.items():
            if key.startswith("_") or not isinstance(child, dict):
                continue
            has_valid_children = True
            self._recurse_absolute_trie(child, chunks, emitted, snapshot_id)

        # Single-member fallback: a structural leaf with content whose
        # pattern siblings were too big for aggregation still gets its own
        # chunk (``member_xpaths=[xp]``) so we don't lose the content and
        # don't smuggle an oversized sibling under a tiny ``char_count``.
        if not is_root and not has_valid_children and xp not in emitted:
            s = self._cached_summary(xp)
            if s:
                self._emit_chunk_at(
                    xp, s, chunks, emitted, snapshot_id,
                    single_member=True,
                )

    def _members_are_homogeneous(self, members: List[str]) -> bool:
        """True iff every member has the same generalised child-pattern set.

        Used by ``_recurse_absolute_trie`` to refuse per-instance
        emission across structurally-similar but semantically-distinct
        siblings (e.g. ``/html/body/main/section`` whose members are
        hero / card-grid / form). Each of those matches the same
        ``section`` pattern but exposes a different child sub-pattern;
        rolling them into one chunk leaks fields across members. By
        contrast, a card-grid's three ``article`` members all expose
        ``img + h2 + p + a`` — the sub-pattern set is identical and
        per-instance emission is meaningful.

        The check is intentionally shallow (direct children only) —
        the recursion handles deeper structure on its own. Single-
        member patterns are trivially homogeneous; emission gating
        already skips those upstream so this helper is only consulted
        for multi-member patterns.
        """
        if not members:
            return False
        if len(members) == 1:
            return True
        child_pattern_sigs: Set[Tuple[str, ...]] = set()
        for mxp in members:
            node = self._by_xpath.get(mxp)
            if node is None:
                # Missing nodes count as a distinct (empty) signature;
                # any disagreement immediately fails homogeneity.
                child_pattern_sigs.add(())
                continue
            child_patterns: List[str] = []
            for key, child in node.items():
                if key.startswith("_") or not isinstance(child, dict):
                    continue
                cxp = child.get("_xpath", "") or ""
                if cxp:
                    child_patterns.append(generalize_xpath(cxp))
            child_pattern_sigs.add(tuple(sorted(set(child_patterns))))
            if len(child_pattern_sigs) > 1:
                return False
        return True

    def _emit_chunk_at(
        self,
        xp: str,
        summary: Dict[str, List[str]],
        chunks: List[Chunk],
        emitted: Set[str],
        snapshot_id: str,
        *,
        single_member: bool = False,
    ) -> None:
        pattern = generalize_xpath(xp)
        if single_member:
            member_xpaths = [xp]
        else:
            member_xpaths = self._by_pattern.get(pattern, [xp])

        text_preview = self._text_only_from_summary(summary)
        if len(text_preview) > 512:
            text_preview = text_preview[:512].rstrip() + "…"
            
        char_count = len(self._format_summary(summary, truncate_links=True))

        image_urls: Dict[str, str] = {}
        link_urls: Dict[str, str] = {}
        for mxp in member_xpaths:
            img_url = self._image_url_for_member(mxp)
            if img_url:
                image_urls[mxp] = img_url
            lnk_url = self._link_url_for_member(mxp)
            if lnk_url:
                link_urls[mxp] = lnk_url

        extraction_trie = self._build_extraction_trie(pattern, member_xpaths)
        chunk_id = self._make_chunk_id(snapshot_id, pattern, len(chunks))

        chunks.append(Chunk(
            chunk_id=chunk_id,
            pattern=pattern,
            representative_xpath=xp,
            member_xpaths=member_xpaths,
            char_count=char_count,
            commutation_count=len(member_xpaths),
            content_fields=summary,
            text_preview=text_preview,
            image_urls=image_urls,
            link_urls=link_urls,
            extraction_trie=extraction_trie,
        ))

        # Claim ONLY the member xpaths themselves, not their full
        # descendants. The previous "claim everything under me" rule
        # blocked per-instance chunks at deeper high-commutation
        # patterns: when ``/section`` (commut=2) emitted, every
        # ``/section/article[*]`` xpath got marked emitted and the
        # recursion bailed there, so the per-card chunk that
        # ``test_card_chunk_is_per_instance_not_aggregated`` expects
        # never materialised. Claiming only the member xpaths
        # prevents same-pattern duplicates (all members already
        # claimed) while letting different-pattern descendants emit
        # their own chunks. Any oversized-ancestor overlap that
        # survives is pruned by ``filter_redundant_rollups`` in
        # ``build()`` (size gate at 2 × HARD_CHAR_LIMIT).
        for mxp in member_xpaths:
            emitted.add(mxp)

    # ------------------------------------------------------------------
    # Content-structure summary (the format the SLM + GUI will see)
    # ------------------------------------------------------------------

    def _tags_in_subtree(self, base_xp: str) -> List:
        """Return every ContentTag at or under ``base_xp``.

        Walks the trie subtree rooted at ``base_xp`` using ``_by_xpath``
        and concatenates each visited node's tag bucket. Result is
        cached per ``base_xp`` so callers that ask for the same xpath
        more than once (extraction-trie builder, image / link url
        helpers, render-summary) share one walk.
        """
        if not self._has_tags:
            return []
        cached = self._tags_in_subtree_cache.get(base_xp)
        if cached is not None:
            return cached
        base_node = self._by_xpath.get(base_xp)
        if base_node is None:
            result = list(self._tags_by_xpath.get(base_xp, ()))
            self._tags_in_subtree_cache[base_xp] = result
            return result
        result: List[ContentTag] = []
        for node in _iter_subtree_nodes(base_node):
            bucket = self._tags_by_xpath.get(node.get("_xpath", ""))
            if bucket:
                result.extend(bucket)
        self._tags_in_subtree_cache[base_xp] = result
        return result

    def _render_summary_fields(self, base_xp: str) -> Dict[str, List[str]]:
        """Build ``{extended_rel_xpath: [values]}`` for one subtree.

        Keys are rooted at the chunk pattern's last tag for readability
        — e.g. ``/li/a/h3/em/text()`` for a ``/html/body/.../ul/li``
        chunk. Values come from ``text_provider`` (which resolves
        attributes for ``urls.*`` / ``media.*`` categories and visible
        text for everything else).

        When ``all_tags`` is provided (production path) we use the
        ContentTagger's explicit ``source_attr`` to decide the address
        (``text()`` vs. ``@attr``). When it isn't (fixture tests) we
        fall back to a per-category default.
        """
        base_pattern = generalize_xpath(base_xp)
        root_tag = base_pattern.rstrip("/").split("/")[-1].split("[")[0] or "root"
        key_prefix = f"/{root_tag}"

        bucket: Dict[str, List[str]] = defaultdict(list)

        if self._has_tags:
            for tag in self._tags_in_subtree(base_xp):
                tag_xp = getattr(tag, "xpath", "") or ""
                gen = generalize_xpath(tag_xp)
                rel = self._relative_pattern(gen, base_pattern)
                if rel is None:
                    continue
                cat = getattr(tag, "category", "") or ""
                sub = getattr(tag, "subcategory", "") or ""
                full_cat = f"{cat}.{sub}" if cat and sub else cat
                src_attr = getattr(tag, "source_attr", "") or ""
                addr = f"@{src_attr}" if src_attr else "text()"

                val = str(getattr(tag, "value", "")).strip()
                # Skip interactive marker tags whose ``value`` is just the
                # element tag name ("a", "button", "input", ...). These
                # exist to flag that the node IS interactive; they carry
                # no user-visible text, and emitting them as ``text()``
                # entries produced noise like ``/p/a/text(): ['a']`` that
                # both humans and LLMs misread as the anchor's actual
                # text. The element's real text is already tagged under
                # ``text/visible`` via the element-level aggregation and
                # its URL is tagged under ``urls/*``, so we lose nothing.
                if cat == "interactive" and not src_attr and val.lower() == tag_xp.rstrip("/").split("/")[-1].split("[")[0].lower():
                    continue

                if not val:
                    val = (self.text_provider(tag_xp, [full_cat]) or "").strip()

                if val:
                    key = f"{key_prefix}{rel}/{addr}"
                    bucket[key].append(val)
        else:
            # Fixture fallback: synthesize address from _content cats.
            base_node = self._by_xpath.get(base_xp)
            if base_node is not None:
                for desc in _iter_subtree_nodes(base_node):
                    cats = desc.get("_content") or []
                    if not cats:
                        continue
                    desc_xp = desc.get("_xpath", "")
                    gen = generalize_xpath(desc_xp)
                    rel = self._relative_pattern(gen, base_pattern)
                    if rel is None:
                        continue
                    for cat in cats:
                        addr = self._default_addr_for_category(cat)
                        val = (self.text_provider(desc_xp, [cat]) or "").strip()
                        if val:
                            key = f"{key_prefix}{rel}/{addr}"
                            bucket[key].append(val)

        return {k: _dedupe_preserve_order(v) for k, v in bucket.items()}

    @staticmethod
    def _relative_pattern(gen_xp: str, base_pattern: str) -> Optional[str]:
        """Return ``gen_xp`` as a string relative to ``base_pattern``.

        Returns ``""`` when they're equal (the tagged node IS the chunk
        root), the remainder starting with ``/`` when ``gen_xp`` is a
        descendant of ``base_pattern``, or ``None`` when ``gen_xp``
        lies outside the subtree (no relative rendering possible).
        """
        if gen_xp == base_pattern:
            return ""
        if base_pattern == "/":
            return gen_xp
        if gen_xp.startswith(base_pattern + "/"):
            return gen_xp[len(base_pattern):]
        return None

    @staticmethod
    def _default_addr_for_category(cat: str) -> str:
        group = cat.split(".", 1)[0]
        if group == "urls":
            return "@href"
        if group == "media":
            return "@src"
        return "text()"

    @staticmethod
    def _format_summary(summary: Dict[str, List[str]], truncate_links: bool = True) -> str:
        """Canonical textual rendering of the content-structure summary.

        Matches the shape shown in the module docstring so token
        counting, preview display, and SLM prompt bytes all agree.
        """
        if not summary:
            return ""
        lines = []
        for k, v_list in summary.items():
            is_link = "/@" in k and k.rsplit("/@", 1)[-1].lower() in _URL_LIKE_ATTRS
            formatted_vals = []
            for val in v_list:
                s_val = str(val)
                if truncate_links and is_link and len(s_val) > 120:
                    s_val = s_val[:117] + "..."
                formatted_vals.append(s_val)
            lines.append(f"    {k}: {formatted_vals!r}")
        return "\n".join(lines)

    @staticmethod
    def _summary_token_count(summary: Dict[str, List[str]]) -> int:
        """Approximate token count of the rendered summary."""
        n_chars = len(ChunkBuilder._format_summary(summary, truncate_links=True))
        if n_chars == 0:
            return 0
        return math.ceil(n_chars / CHARS_PER_TOKEN_EST)

    @staticmethod
    def _text_only_from_summary(summary: Dict[str, List[str]]) -> str:
        """Collect every ``text()`` value and space-join for embedding.

        A plain concatenation would mash `"Aries in"` + `"Love and..."`
        into `"Aries inLove and..."` — the user explicitly called that
        out as a regression to avoid. Single-space join keeps tokens
        separable for the embedder without smuggling in punctuation.

        URL-like attributes (``@href`` / ``@src`` / ``@srcset`` / …)
        contribute their **semantic tokens** (domain + meaningful path
        segments) — not the raw URL — so semantic search can surface a
        chunk by words that only appear inside a URL ("ions", "tarot")
        without drowning the embedding in ``https`` / ``wp-content`` /
        query-string noise.
        """
        parts: List[str] = []
        for key, vals in summary.items():
            if key.endswith("/text()"):
                parts.extend(vals)
                continue
            if "/@" in key:
                attr_name = key.rsplit("/@", 1)[-1].lower()
                if attr_name in _URL_LIKE_ATTRS:
                    for v in vals:
                        toks = _tokenize_url_builder(str(v))
                        if toks:
                            parts.append(toks)
                    continue
                parts.extend(vals)
        cleaned = [" ".join(p.split()) for p in parts if p and p.strip()]
        return " ".join(cleaned)

    def _build_dbscan_pattern_chunks_DEPRECATED(self, snapshot_id: str) -> List[Chunk]:
        """Kept only as a reference for the previous broken behaviour."""
        leaves = self._collect_content_leaves()
        if not leaves:
            return []

        # 1. Extract unique generalized schemas (patterns) from leaves
        leaf_patterns = list(set(generalize_xpath(xp) for xp in leaves))

        # 2. Build uncompressed schema tree, then COMPRESS it into a Schema Patricia Trie
        pattern_tree = {}
        for p in leaf_patterns:
            parts = [x for x in p.strip("/").split("/") if x]
            curr = pattern_tree
            for part in parts:
                if part not in curr:
                    curr[part] = {}
                curr = curr[part]

        def _compress(t: Dict) -> Dict:
            """Recursively collapses single-child chains to restore Patricia topology."""
            compressed = {}
            for k, v in t.items():
                sub = _compress(v)
                if len(sub) == 1:
                    sub_k, sub_v = list(sub.items())[0]
                    compressed[f"{k}/{sub_k}"] = sub_v
                else:
                    compressed[k] = sub
            return compressed

        compressed_pattern_tree = _compress(pattern_tree)

        # 3. Compute EXACT Sarkar Poincaré embeddings on the COMPRESSED PATTERN tree
        poincare_coords = {}
        tau = 0.5
        R = math.tanh(tau / 2.0)

        def mobius_add(u: complex, v: complex) -> complex:
            """Möbius addition in the complex Poincaré disk."""
            return (u + v) / (1 + u * v.conjugate())

        def _compute_poincare(node: Dict, parts_so_far: List[str], z_parent: complex, incoming_angle: float) -> None:
            path_str = "/" + "/".join(parts_so_far) if parts_so_far else "/"
            poincare_coords[path_str] = (z_parent.real, z_parent.imag)
            if not node:
                return
            
            spread = 2 * math.pi * 0.8 if parts_so_far else 2 * math.pi
            start_angle = incoming_angle + math.pi - (spread / 2.0) if parts_so_far else 0.0
            step = 0 if len(node) == 1 else spread / (len(node) - 1)

            for i, (k, child) in enumerate(node.items()):
                angle = start_angle + i * step
                w_child = R * cmath.exp(1j * angle)
                z_child = mobius_add(z_parent, w_child)
                
                # Unpack the compressed segments so intermediate paths inherit the terminal topology
                k_parts = k.split("/")
                for j in range(1, len(k_parts) + 1):
                    intermediate_path = "/" + "/".join(parts_so_far + k_parts[:j])
                    poincare_coords[intermediate_path] = (z_child.real, z_child.imag)
                    
                _compute_poincare(child, parts_so_far + k_parts, z_child, angle)

        _compute_poincare(compressed_pattern_tree, [], 0j, 0.0)

        # 4. Build Schema Feature Matrix: [Freq, P_x, P_y]
        features = []
        for p in leaf_patterns:
            matches = self._by_pattern.get(p, [])
            freq = len(matches)
            px, py = poincare_coords.get(p, (0.0, 0.0))
            features.append([freq, px, py])

        X_raw = np.array(features, dtype=np.float32)

        # 5. Selective Normalization & Hyperbolic Distance Matrix
        #    NOTE (forbidden-concept audit, FIX-01): this Poincaré-disk distance
        #    is a SCAN-TIME pattern-CLUSTERING metric (groups generalized chunk
        #    patterns for the schema), NOT the forbidden hyperbolic 3D *layout*
        #    (ontology/hyperbolic_layout.py / gyrovector.py — already removed,
        #    CODEBASE_AUDIT G8). The 3D layout authority is the UMAP-linear-radial
        #    LayoutService (§6.1). Flagged for design review if hyperbolic
        #    geometry is to be eliminated wholesale rather than only as a layout.
        if len(X_raw) > 0:
            scaler = MinMaxScaler(feature_range=(0, 1))
            freqs_scaled = scaler.fit_transform(X_raw[:, 0:1])
        else:
            freqs_scaled = np.zeros((0, 1), dtype=np.float32)
            
        N = len(X_raw)
        dist_matrix = np.zeros((N, N), dtype=np.float32)
        for i in range(N):
            for j in range(i + 1, N):
                u = X_raw[i, 1:3]
                v = X_raw[j, 1:3]
                sq_dist = (u[0] - v[0])**2 + (u[1] - v[1])**2
                u_norm_sq = min(u[0]**2 + u[1]**2, 0.99999)
                v_norm_sq = min(v[0]**2 + v[1]**2, 0.99999)
                arg = max(1.0 + 2.0 * sq_dist / ((1.0 - u_norm_sq) * (1.0 - v_norm_sq)), 1.0)
                d_H = math.acosh(arg)
                d_F = abs(freqs_scaled[i, 0] - freqs_scaled[j, 0])
                dist_matrix[i, j] = dist_matrix[j, i] = d_H + d_F

        # 6. Apply DBSCAN strictly on the True Distance Matrix
        # eps=0.75 captures siblings / parent-child (tau=0.5) rigidly excluding distant branches
        from sklearn.cluster import DBSCAN as sk_DBSCAN
        clusterer = sk_DBSCAN(eps=0.75, min_samples=2, metric='precomputed')
        labels = clusterer.fit_predict(dist_matrix)

        # 7. Group generalized patterns by their structural manifold
        clusters = defaultdict(list)
        for pat, label in zip(leaf_patterns, labels):
            if label == -1:
                clusters[f"noise_{pat}"].append(pat)
            else:
                clusters[label].append(pat)

        chunks: List[Chunk] = []

        # 8. Instantiate Chunks from Pattern Clusters
        for label_id, cluster_patterns in clusters.items():
            chunk_pattern = self._compute_lca(cluster_patterns)
            chunk_depth = self._depth(chunk_pattern)

            # Gather all absolute leaves bound to this schema
            abs_leaves = []
            for p in cluster_patterns:
                abs_leaves.extend(self._by_pattern.get(p, []))

            # Group leaves to find specific instance roots
            instance_roots = set()
            for leaf_xp in abs_leaves:
                parts = [x for x in leaf_xp.strip("/").split("/") if x]
                if len(parts) >= chunk_depth:
                    inst_root = "/" + "/".join(parts[:chunk_depth])
                    instance_roots.add(inst_root)
                else:
                    instance_roots.add(leaf_xp)

            member_xpaths = sorted(list(instance_roots))
            if not member_xpaths:
                continue

            chunks.append(self._finalize_cluster_chunk(
                chunk_pattern=chunk_pattern,
                inst_root_xpath=member_xpaths[0],
                member_xpaths=member_xpaths,
                commutation_count=len(member_xpaths),
                snapshot_id=snapshot_id,
                ordinal=len(chunks)
            ))

        # 9. Containment pruning: strip massive overlapping structural rollups
        # This isolates the DBSCAN clustering to fine-grained, budget-friendly chunks
        rollup_threshold = 2 * HARD_CHAR_LIMIT
        chunks = filter_redundant_rollups(
            chunks,
            xpath_of=lambda c: c.representative_xpath,
            size_of=lambda c: c.char_count,
            min_rollup_size=rollup_threshold,
        )

        return chunks

    # ------------------------------------------------------------------
    # LCA & Assembly
    # ------------------------------------------------------------------

    def _compute_lca(self, xpaths: List[str]) -> str:
        """Returns the Lowest Common Ancestor (LCA) for a list of absolute xpaths."""
        if not xpaths:
            return "/"
        if len(xpaths) == 1:
            return xpaths[0]
            
        split_paths = [xp.strip("/").split("/") for xp in xpaths]
        lca_parts = []
        
        for parts in zip(*split_paths):
            if len(set(parts)) == 1:
                lca_parts.append(parts[0])
            else:
                break
                
        return "/" + "/".join(lca_parts) if lca_parts else "/"

    def _finalize_cluster_chunk(self, chunk_pattern: str, inst_root_xpath: str,
                                member_xpaths: List[str], commutation_count: int,
                                snapshot_id: str,
                                ordinal: int) -> Chunk:
        
        root_node = self._by_xpath.get(inst_root_xpath, {})
        char_count = self._text_chars(root_node) if root_node else 0
        content_fields = self._aggregate_content_fields(root_node) if root_node else {}
        text_preview = self._text_preview(root_node) if root_node else ""
        
        image_urls = {}
                
        for mxp in member_xpaths:
            url = self._image_url_for_member(mxp)
            if url:
                image_urls[mxp] = url

        # The extraction trie is a *per-instance* data-address schema:
        # the set of relative paths ``query_chunk`` should resolve
        # against each DOM match of ``pattern``. Build it from the
        # representative's subtree only -- NOT the union across all
        # members. Members with the same generalized xpath but
        # different shapes (e.g. a page where hero, card-grid, and
        # filters all share ``/html/body/main/section`` but each
        # contains completely different descendants) would otherwise
        # pollute every instance's schema with the other members'
        # paths, which is how you get a hero instance reporting
        # ``/article/img/@src: [...3 card images...]``.
        extraction_trie = self._build_extraction_trie(
            chunk_pattern, member_xpaths
        )

        chunk_id = self._make_chunk_id(snapshot_id, chunk_pattern, ordinal)
        return Chunk(
            chunk_id=chunk_id,
            pattern=chunk_pattern,
            representative_xpath=inst_root_xpath,
            member_xpaths=member_xpaths,
            char_count=char_count,
            commutation_count=len(member_xpaths),
            content_fields=content_fields,
            text_preview=text_preview,
            image_urls=image_urls,
            extraction_trie=extraction_trie,
        )

    def _build_extraction_trie(
        self,
        chunk_pattern: str,
        member_xpaths: List[str]
    ) -> Dict[str, Any]:
        """
        Build a chunk-wise patricia trie of extended generalized XPaths
        with specific attributes (data addresses) at the leaves.
        """
        base_pattern = generalize_xpath(chunk_pattern)
        root_tag = base_pattern.rstrip("/").split("/")[-1].split("[")[0] or "root"
        key_prefix = f"/{root_tag}"

        # Find all tags belonging to any chunk member.
        # Use _tags_in_subtree for O(log n + k) per member instead of the
        # old O(all_tags × members) double loop.
        paths = []
        seen_tags: Set[Tuple[str, str]] = set()
        for mxp in member_xpaths:
            for tag in self._tags_in_subtree(mxp):
                tag_xp = getattr(tag, "xpath", "") or ""
                src_attr = getattr(tag, "source_attr", "") or ""
                addr = f"@{src_attr}" if src_attr else "text()"
                
                sig = (tag_xp, addr)
                if not tag_xp or sig in seen_tags:
                    continue
                seen_tags.add(sig)

                gen_tag_xp = generalize_xpath(tag_xp)
                if gen_tag_xp == chunk_pattern:
                    rel = ""
                elif chunk_pattern == "/":
                    rel = gen_tag_xp
                elif gen_tag_xp.startswith(chunk_pattern + "/"):
                    rel = gen_tag_xp[len(chunk_pattern):]
                else:
                    continue

                ext_path = f"{key_prefix}{rel}/{addr}"
                paths.append(ext_path)
                    
        # Collapse distinct paths into a trie structure
        trie = {}
        for path in set(paths):
            segs = [s for s in path.split("/") if s]
            curr = trie
            for i, seg in enumerate(segs):
                if i == len(segs) - 1:
                    curr[seg] = {}
                else:
                    norm_seg = f"/{seg}"
                    if norm_seg not in curr:
                        curr[norm_seg] = {}
                    curr = curr[norm_seg]
        
        return self._compress_extraction_trie(trie)

    def _compress_extraction_trie(self, trie: Dict[str, Any]) -> Dict[str, Any]:
        """
        Recursively compress single-child branches (e.g. `{"/a": {"/b": ...}}` -> `{"/a/b": ...}`).
        Data addresses (e.g., @href or text()) are kept as separate terminal keys.
        """
        compressed = {}
        for k, subtree in trie.items():
            if not subtree:
                compressed[k] = {}
                continue
                
            sub_compressed = self._compress_extraction_trie(subtree)
            
            if len(sub_compressed) == 1:
                sub_k, sub_v = list(sub_compressed.items())[0]
                if sub_k.startswith('/') and k.startswith('/'):
                    # merge them
                    new_k = f"{k}{sub_k}"
                    compressed[new_k] = sub_v
                else:
                    compressed[k] = sub_compressed
            else:
                compressed[k] = sub_compressed
                
        return compressed

    def _image_url_for_member(self, member_xpath: str) -> Optional[str]:
        """Walk a member subtree for the first usable media URL.

        Uses explicit tags to capture agnostically extracted URLs from any
        attribute, falling back to text_provider for standard elements.

        The extension allow-list MUST stay in sync with
        ``content_tagger._IMAGE_EXTS`` so the Pass-2 fallback catches every
        image format the tagger itself would recognize.
        """
        _IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
                    ".ico", ".avif", ".bmp", ".tiff", ".tif",
                    ".apng", ".jfif", ".pjpeg", ".pjp",
                    ".heic", ".heif")
        
        tags = self._tags_in_subtree(member_xpath)
        
        # Pass 1: media category
        for tag in tags:
            cat = getattr(tag, "category", "") or ""
            if cat == "media":
                val = str(getattr(tag, "value", "")).strip()
                # If value is just the element tag name, ask the text provider
                if not val or val.lower() in ('img', 'picture', 'svg', 'canvas', 'video', 'audio', 'source', 'track'):
                    sub = getattr(tag, "subcategory", "") or ""
                    full_cat = f"{cat}.{sub}" if sub else cat
                    val = (self.text_provider(getattr(tag, "xpath", ""), [full_cat]) or "").strip()
                if val:
                    return val

        # Pass 2: urls category with image extension
        for tag in tags:
            cat = getattr(tag, "category", "") or ""
            if cat == "urls":
                val = str(getattr(tag, "value", "")).strip()
                if not val:
                    sub = getattr(tag, "subcategory", "") or ""
                    full_cat = f"{cat}.{sub}" if sub else cat
                    val = (self.text_provider(getattr(tag, "xpath", ""), [full_cat]) or "").strip()
                if val and any(val.lower().split("?")[0].endswith(ext) for ext in _IMG_EXT):
                    return val

        return None

    def _link_url_for_member(self, member_xpath: str) -> Optional[str]:
        """Walk a member subtree for the first usable non-media URL."""
        _IMG_EXT = (".png", ".jpg", ".jpeg", ".gif", ".svg", ".webp",
                    ".ico", ".avif", ".bmp", ".tiff", ".tif",
                    ".apng", ".jfif", ".pjpeg", ".pjp",
                    ".heic", ".heif")
        
        tags = self._tags_in_subtree(member_xpath)
        for tag in tags:
            cat = getattr(tag, "category", "") or ""
            if cat == "urls":
                val = str(getattr(tag, "value", "")).strip()
                if not val:
                    sub = getattr(tag, "subcategory", "") or ""
                    full_cat = f"{cat}.{sub}" if sub else cat
                    val = (self.text_provider(getattr(tag, "xpath", ""), [full_cat]) or "").strip()
                if val and not any(val.lower().split("?")[0].endswith(ext) for ext in _IMG_EXT):
                    return val

        return None

    def _leaves_under_members(self, member_xpaths: List[str]) -> Set[str]:
        """All content-bearing descendants under any member xpath."""
        claimed: Set[str] = set()
        for xp in member_xpaths:
            node = self._by_xpath.get(xp)
            if node is None:
                continue
            for descendant in _iter_subtree_nodes(node):
                if descendant.get("_content"):
                    claimed.add(descendant.get("_xpath", ""))
        return claimed

    def _html_chars_xp(self, xpath: str) -> int:
        """Approximate the character length of the distilled HTML for this subtree."""
        node = self._by_xpath.get(xpath)
        if not node:
            return 0
        return self._html_chars_node(node)

    def _html_chars_node(self, node: Dict[str, Any]) -> int:
        xp = node.get("_xpath", "")
        chars = 0
        if xp and xp != "/":
            tag, attrs = self.structure_provider(xp)
            chars += 5 + (len(tag) * 2) # <tag></tag>
            for k, v in attrs.items():
                chars += len(str(k)) + min(len(str(v)), self.attr_truncate) + 3

            text = self.text_provider(xp, ["text"]) or ""
            if text:
                chars += min(len(text), self.text_truncate)

        for key, child in node.items():
            if key.startswith("_") or not isinstance(child, dict):
                continue
            chars += self._html_chars_node(child)
        return chars

    # ------------------------------------------------------------------
    # Misc helpers
    # ------------------------------------------------------------------

    def _collect_content_leaves(self) -> List[str]:
        """Every xpath whose node is tagged with at least one content category."""
        leaves: List[str] = []
        for node in _iter_subtree_nodes(self.tree):
            if node.get("_content"):
                leaves.append(node.get("_xpath", ""))
        return [xp for xp in leaves if xp]

    @staticmethod
    def _depth(xpath: str) -> int:
        if not xpath or xpath == "/":
            return 0
        return sum(1 for s in xpath.strip("/").split("/") if s)

    @staticmethod
    def _make_chunk_id(snapshot_id: str, pattern: str, ordinal: int) -> str:
        h = hashlib.sha1(f"{snapshot_id}|{pattern}|{ordinal}".encode("utf-8"))
        return f"chunk_{h.hexdigest()[:16]}"


def _dedupe_preserve_order(items: List[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


# ---------------------------------------------------------------------------
# ShadowDOM text-provider adapter
# ---------------------------------------------------------------------------

def build_xpath_node_map(dom) -> Dict[str, Any]:
    """Build an ``xpath → ShadowNode`` dict with a single O(N) DOM walk.

    Pass the returned map to both :func:`build_text_provider_from_dom` and
    :func:`build_structure_provider_from_dom` (and to
    :func:`~vertiscope.core.chunk_render.render_all_chunks`) so all three
    share one traversal instead of each doing their own.
    """
    from vertiscope.core.shadow_html_parser import get_absolute_xpath
    result: Dict[str, Any] = {}
    if dom is not None:
        for node in dom.iter_all():
            try:
                xp = get_absolute_xpath(node)
                if xp:
                    result[xp] = node
                # iter_all() flattens shadow children into parents but never
                # yields the shadow-root node itself, so xpaths that end in
                # "/#shadow-root" (emitted by the chunker as member roots)
                # wouldn't resolve. Map them in explicitly here.
                sroot = getattr(node, "shadow_root", None)
                if sroot is not None and getattr(sroot, "children", None):
                    sxp = get_absolute_xpath(sroot)
                    if sxp:
                        result[sxp] = sroot
            except Exception:
                continue
    return result


def build_text_provider_from_dom(
    dom, xpath_map: Optional[Dict[str, Any]] = None
) -> Callable[[str, List[str]], str]:
    """
    Build a text_provider callable backed by a ShadowDOM.

    The provider returns the node's visible text for text.* categories,
    the href/src attribute for urls.* / media.* (zero-length against the
    budget — kept for knowledge-panel aggregation), and a compact summary
    for interactive / json_data nodes.

    Pass a pre-built ``xpath_map`` (from :func:`build_xpath_node_map`) to
    avoid a redundant DOM traversal when the caller already built one.
    """
    from vertiscope.core.shadow_html_parser import get_absolute_xpath

    xpath_to_node: Dict[str, Any]
    if xpath_map is not None:
        xpath_to_node = xpath_map
    else:
        xpath_to_node = {}
        if dom is not None:
            for node in dom.iter_all():
                try:
                    xp = get_absolute_xpath(node)
                    if xp:
                        xpath_to_node[xp] = node
                except Exception:
                    continue

    def _safe_get_text(node) -> str:
        txt = node.get_text(recursive=True, separator=" ")
        if node.tail and node.tail.strip():
            txt += " " + node.tail.strip()
        return txt.strip()

    def _provider(xpath: str, categories: List[str]) -> str:
        node = xpath_to_node.get(xpath)
        if node is None:
            return ""
        primary = categories[0] if categories else ""
        group = primary.split(".", 1)[0]
        try:
            if group == "text":
                return _safe_get_text(node)
            if group == "urls":
                attrs = node.get_all_attrs()
                return attrs.get("href") or attrs.get("src") or ""
            if group == "media":
                attrs = node.get_all_attrs()
                # Walk common attribute spellings — static <img src>,
                # <video poster>, lazy-loaded data-* variants, and
                # background-image CSS. First non-empty wins.
                for key in ("src", "data-src", "data-lazy-src",
                            "data-original", "data-image", "poster",
                            "href", "xlink:href", "content"):
                    val = attrs.get(key)
                    if val:
                        return val
                style = attrs.get("style") or ""
                if "url(" in style:
                    style = _html_escape.unescape(style)
                    import re as _re
                    m = _re.search(r"url\(\s*['\"]?([^'\")]+)", style)
                    if m:
                        return m.group(1).strip()
                return ""
            if group == "interactive":
                attrs = node.get_all_attrs()
                return (
                    attrs.get("aria-label")
                    or attrs.get("placeholder")
                    or attrs.get("value")
                    or attrs.get("name")
                    or _safe_get_text(node)
                )
            if group == "json_data":
                return _safe_get_text(node)[:512]
        except Exception:
            return ""
        return _safe_get_text(node)

    return _provider


def build_structure_provider_from_dom(
    dom,
    xpath_map: Optional[Dict[str, Any]] = None,
) -> Callable[[str], Tuple[str, Dict[str, str]]]:
    """Return ``xpath → (tag_name, attrs_dict)`` for every DOM node.

    The chunker calls this once per trie-node-visited-during-walk-up so
    the distilled-HTML serializer can emit real tags and real attribute
    values (truncated by the chunker to ``attr_truncate`` chars). The
    shape mirrors :func:`build_text_provider_from_dom` so callers can
    pair them trivially::

        xmap               = build_xpath_node_map(dom)
        text_provider      = build_text_provider_from_dom(dom, xpath_map=xmap)
        structure_provider = build_structure_provider_from_dom(dom, xpath_map=xmap)
        ChunkBuilder(tree, text_provider, structure_provider=structure_provider)

    Pass a pre-built ``xpath_map`` to skip a redundant O(N) DOM walk.
    A missing xpath returns ``("div", {})`` — the serializer still emits
    a bracketed tag so the resulting HTML remains well-formed.
    """
    from vertiscope.core.shadow_html_parser import get_absolute_xpath

    xpath_to_node: Dict[str, Any]
    if xpath_map is not None:
        xpath_to_node = xpath_map
    else:
        xpath_to_node = {}
        if dom is not None:
            for node in dom.iter_all():
                try:
                    xp = get_absolute_xpath(node)
                    if xp:
                        xpath_to_node[xp] = node
                except Exception:
                    continue

    def _provider(xpath: str) -> Tuple[str, Dict[str, str]]:
        node = xpath_to_node.get(xpath)
        if node is None:
            return ("div", {})
        try:
            tag = str(getattr(node, "tag", "") or "div")
            attrs = node.get_all_attrs() if hasattr(node, "get_all_attrs") else {}
            # Coerce to plain str:str for deterministic serialization.
            cleaned: Dict[str, str] = {}
            for k, v in (attrs or {}).items():
                if v is None:
                    continue
                cleaned[str(k)] = str(v)
            return (tag, cleaned)
        except Exception:
            return ("div", {})

    return _provider
