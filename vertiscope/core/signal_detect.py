"""Search-input and pagination detection.

Lifted verbatim (same classes, same vocabularies, same agnostic attribute
rules) out of the 5,835-line ``web_distiller_freq`` template miner, whose
other 88% — spectral cohort mining, PQ-trees, CIST, purity-dominance — no
part of the scrape → chunk → index → retrieve path ever called.

``AgnosticAttr`` is the interesting piece and the reason this is an
extraction rather than a rewrite: it inspects *every* attribute value rather
than a hardcoded allowlist, which is what lets detection survive sites that
name their search box ``data-testid="site-srch"``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from functools import lru_cache
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

from vertiscope.core.shadow_html_parser import ShadowDOM, ShadowNode, get_absolute_xpath

_XPATH_CACHE: dict[int, str] = {}

def cached_xpath(node: ShadowNode) -> str:
    """get_absolute_xpath with per-session memoization."""
    nid = id(node)
    if nid not in _XPATH_CACHE:
        _XPATH_CACHE[nid] = get_absolute_xpath(node)
    return _XPATH_CACHE[nid]

class ContentCategory(Enum):
    INPUT = "input"
    BUTTON = "button"
    TEXT = "text"
    LINK = "link"
    STRUCTURE = "structure"
    NAVIGATION = "navigation"

BUTTON_INPUT_TYPES = frozenset({'button', 'submit', 'reset', 'image'})

FORM_INPUT_TAGS = frozenset({'input', 'textarea', 'select'})

HEADING_TAGS = frozenset({'h1', 'h2', 'h3', 'h4', 'h5', 'h6'})

MEDIA_CONTAINER_TAGS = frozenset({'picture', 'video', 'audio'})

FALLBACK_COPY_TAGS = frozenset({'noscript', 'template'})

class AttributeTokenizer:
    @staticmethod
    def tokenize(value: str) -> list[str]:
        if not value:
            return []
        tokens = re.split(r'[\s\-_]+', value)
        final = []
        for t in tokens:
            parts = re.findall(
                r'([A-Z]?[a-z]+|[A-Z]+(?=[A-Z]|$|\d)|\d+)', t
            )
            final.extend(parts if parts else [t])
        return [f.lower() for f in final if len(f) > 1 and not f.isdigit()]

class AgnosticAttr:
    """
    Agnostic attribute inspection — no hardcoded attribute keys.

    Every method inspects ALL attributes on a node or subtree,
    discovering URLs, link text, and media sources by value heuristics
    rather than key assumptions.  This mirrors the tokenized-XPath
    predicate approach used by SiblingCohortMiner's spectral graph:
    attribute *keys* are metadata, attribute *values* carry the signal.

    URL heuristic:  a value is URL-like if it starts with ``/``,
    ``http://``, ``https://``, ``data:``, or ``//``, OR if it contains
    both ``/`` and ``.`` (path-like).  Inline CSS ``url(...)`` is also
    extracted.

    This replaces ~44 hardcoded ``get_attr('href'...)``,
    ``get_attr('src'...)``, ``get_attr('class'...)`` calls scattered
    throughout the pipeline with a single discoverable interface.
    """

    _URL_RE = re.compile(
        r'^(?:https?://|//|/|data:image/)',
        re.IGNORECASE,
    )
    _CSS_URL_RE = re.compile(r"url\(['\"]?([^'\")\s]+)['\"]?\)")

    # Attributes whose values are NEVER URLs (prevent false positives
    # from long class strings or JS event handlers).  Discovered
    # empirically, not assumed — keep minimal.
    _ATTR_DENYLIST = frozenset({
        'style', 'onclick', 'onload', 'onerror', 'onmouseover',
    })

    @classmethod
    def is_url(cls, value: str) -> bool:
        """Heuristic: does this string look like a URL?"""
        if not value:
            return False
        v = value.strip()
        if not v:
            return False
        # Accept bare root path '/'
        if v == '/':
            return True
        if len(v) < 2:
            return False
        if cls._URL_RE.match(v):
            return True
        # Path-like: has both / and . but isn't a sentence
        if '/' in v and '.' in v and ' ' not in v and len(v) < 500:
            return True
        return False

    @classmethod
    def urls_from_node(cls, node: ShadowNode) -> list[str]:
        """Extract all URL-like values from ALL attributes of a single node."""
        urls: list[str] = []
        for key, val in node.get_all_attrs().items():
            if key.lower() in cls._ATTR_DENYLIST:
                # But still check style for url()
                if key.lower() == 'style' and val and 'url(' in val:
                    for m in cls._CSS_URL_RE.finditer(val):
                        u = m.group(1).strip()
                        if u and not u.startswith('data:') or u.startswith('data:image/'):
                            urls.append(u)
                continue
            if not val or not isinstance(val, str):
                continue
            v = val.strip()
            if cls.is_url(v):
                urls.append(v)
            # Handle multi-value attrs like srcset: "img1.jpg 1x, img2.jpg 2x"
            elif ',' in v and '/' in v:
                for part in v.split(','):
                    candidate = part.strip().split()[0] if part.strip() else ''
                    if cls.is_url(candidate):
                        urls.append(candidate)
        return urls

    @classmethod
    def all_urls(cls, node: ShadowNode) -> list[str]:
        """Extract all URL-like values from a subtree (recursive)."""
        urls: list[str] = []
        for desc in node.iter_all():
            urls.extend(cls.urls_from_node(desc))
        return urls

    @classmethod
    def unique_urls(cls, node: ShadowNode) -> set[str]:
        """Deduplicated URL set from a subtree."""
        return set(cls.all_urls(node))

    @classmethod
    def primary_url(cls, node: ShadowNode) -> Optional[str]:
        """
        Extract the primary navigable URL from a node.

        Inspects all attributes agnostically; returns the first URL found
        on the node itself, or the first URL found on any descendant.
        Skips fragment-only (#) and javascript: pseudo-URLs.
        """
        def _valid(u: str) -> bool:
            return (u and not u.startswith('#')
                    and not u.startswith('javascript'))

        # Check node itself first
        for u in cls.urls_from_node(node):
            if _valid(u):
                return u
        # Then descendants
        for desc in node.iter_descendants():
            for u in cls.urls_from_node(desc):
                if _valid(u):
                    return u
        return None

    @classmethod
    def has_url_descendant(cls, node: ShadowNode) -> bool:
        """True if any descendant carries a URL-bearing attribute."""
        for desc in node.iter_descendants():
            if cls.urls_from_node(desc):
                return True
        return False

    @classmethod
    def node_has_url(cls, node: ShadowNode) -> bool:
        """True if this specific node has any URL-bearing attribute."""
        return bool(cls.urls_from_node(node))

    @classmethod
    def media_urls(cls, node: ShadowNode) -> list[str]:
        """Extract media-specific URLs (images, video, audio) from subtree.

        Uses the agnostic URL extractor but filters to common media
        extensions and data URIs.  No hardcoded attribute keys.
        """
        media_exts = ('.jpg', '.jpeg', '.png', '.gif', '.webp', '.svg',
                      '.mp4', '.webm', '.ogg', '.mp3', '.wav')
        result = []
        for url in cls.all_urls(node):
            u_lower = url.lower().split('?')[0]
            if (any(u_lower.endswith(ext) for ext in media_exts)
                    or 'image' in u_lower
                    or url.startswith('data:image/')):
                result.append(url)
        return result

    @classmethod
    def attr_token_vector(cls, node: ShadowNode) -> set[str]:
        """
        Build the tokenized XPath predicate vector for a node.

        Returns a set of strings in XPath predicate notation:
            ``@{key}:{token}``
        Identical to the spectral miner's feature extraction,
        ensuring consistency between mining and matching phases.
        """
        tokens: set[str] = set()
        tokens.add(f"tag:{node.tag.lower()}")
        for key, val in node.get_all_attrs().items():
            key_lower = key.lower()
            tokens.add(f"@{key_lower}")
            val_str = str(val or '')[:300]
            if val_str:
                for tok in AttributeTokenizer.tokenize(val_str):
                    tokens.add(f"@{key_lower}:{tok}")
        return tokens

    @classmethod
    def attr_has_token(cls, node: ShadowNode, token: str) -> bool:
        """Check if any attribute value on node contains a specific token."""
        token_lower = token.lower()
        for _key, val in node.get_all_attrs().items():
            if not val:
                continue
            for tok in AttributeTokenizer.tokenize(str(val)[:300]):
                if tok == token_lower:
                    return True
        return False

    @classmethod
    def is_button_like(cls, node: ShadowNode) -> bool:
        """
        Agnostic button detection.

        An element is button-like if:
        - Its tag is 'button' (structural HTML)
        - Any attribute value tokenizes to a button-type token
          (submit, button, reset, image) — catches ``<input type=submit>``,
          ``<div data-action=submit>``, ``<custom role=button>``, etc.

        Replaces hardcoded ``get_attr('type') in BUTTON_INPUT_TYPES``
        with agnostic attribute-value tokenization.
        """
        if node.tag.lower() == 'button':
            return True
        for _key, val in node.get_all_attrs().items():
            if not val:
                continue
            val_lower = str(val).lower().strip()
            if val_lower in BUTTON_INPUT_TYPES:
                return True
        return False

    @classmethod
    def is_input_like(cls, node: ShadowNode) -> bool:
        """
        Agnostic form-input detection.

        An element is input-like if:
        - Its tag is in FORM_INPUT_TAGS (input, textarea, select)
        - OR any attribute value tokenizes to an input-role token
          (textbox, searchbox, combobox, listbox, spinbutton)
        - OR it has contenteditable="true"

        This catches ``<div role="searchbox">``,
        ``<custom-input contenteditable="true">``, etc.
        """
        if node.tag.lower() in FORM_INPUT_TAGS:
            return True
        _INPUT_ROLE_TOKENS = frozenset({
            'textbox', 'searchbox', 'combobox', 'listbox', 'spinbutton',
        })
        for _key, val in node.get_all_attrs().items():
            if not val:
                continue
            val_lower = str(val).lower().strip()
            if val_lower in _INPUT_ROLE_TOKENS:
                return True
            if val_lower == 'true' and _key.lower() == 'contenteditable':
                return True
        return False

    @classmethod
    def is_heading_like(cls, node: ShadowNode) -> bool:
        """
        Agnostic heading detection.

        An element is heading-like if:
        - Its tag is in HEADING_TAGS (h1-h6)
        - OR any attribute value tokenizes to 'heading'
          (catches ``<div role="heading" aria-level="2">``)
        """
        if node.tag.lower() in HEADING_TAGS:
            return True
        for _key, val in node.get_all_attrs().items():
            if not val:
                continue
            if str(val).lower().strip() == 'heading':
                return True
        return False

    @classmethod
    def is_fallback_copy(cls, node: ShadowNode) -> bool:
        """
        Agnostic fallback-copy detection.

        Identifies elements whose content is a browser-fallback copy
        of richer content (noscript, template).  These should be masked
        in dedup to avoid double-counting.
        """
        return node.tag.lower() in FALLBACK_COPY_TAGS

    @classmethod
    def is_container_of_links(cls, node: ShadowNode) -> bool:
        """
        Agnostic container-of-links detection.

        True if this element has >=2 direct children that carry URLs.
        Used for molecule splitting: instead of hardcoding tag names
        like (ul, ol, nav, div), we test if the element structurally
        wraps multiple link atoms.
        """
        url_children = 0
        for child in node.get_children(include_shadow=True):
            if cls.node_has_url(child) or cls.has_url_descendant(child):
                url_children += 1
                if url_children >= 2:
                    return True
        return False

    @classmethod
    def is_media_container(cls, node: ShadowNode) -> bool:
        """
        Agnostic media-container detection.

        True if this element is a container that wraps media sources
        (picture, video, audio) or has ARIA/attribute indicating media.
        """
        if node.tag.lower() in MEDIA_CONTAINER_TAGS:
            return True
        for _key, val in node.get_all_attrs().items():
            if not val:
                continue
            val_lower = str(val).lower().strip()
            if val_lower in ('img', 'image', 'video', 'figure'):
                return True
        return False

    @classmethod
    def primary_media_key(cls, node: ShadowNode) -> str:
        """
        Extract a single dedup key for media elements (img, picture, video).

        Inspects ALL attributes agnostically.  Prefers non-placeholder URLs
        (skipping data: URIs) to handle lazy-load patterns where the real
        source lives in ``data-src``, ``data-lazy-src``, ``data-original``,
        or any vendor-specific attribute — without hardcoding any of them.

        Returns the first non-data-URI URL found, truncated to 120 chars.
        Falls back to empty string if no URL is discovered.
        """
        # Pass 1: find any non-data-URI URL on this node
        for _key, val in node.get_all_attrs().items():
            if not val or not isinstance(val, str):
                continue
            v = val.strip()
            if v.startswith('data:'):
                continue
            if cls.is_url(v):
                return v.split()[0][:120]
            # Handle srcset-style multi-value
            if ',' in v and '/' in v:
                for part in re.split(r',\s+', v):
                    candidate = part.strip().split()[0] if part.strip() else ''
                    if candidate and cls.is_url(candidate) and not candidate.startswith('data:'):
                        return candidate[:120]
        # Pass 2: last resort — any URL including data: images
        for _key, val in node.get_all_attrs().items():
            if not val or not isinstance(val, str):
                continue
            v = val.strip()
            if cls.is_url(v):
                return v.split()[0][:120]
        return ''

    @classmethod
    def primary_media_key_subtree(cls, node: ShadowNode) -> str:
        """
        Extract a dedup key from a container node (picture, video) by
        inspecting ALL descendants agnostically.

        Returns the first non-data-URI URL found on any descendant.
        """
        for desc in node.iter_descendants():
            key = cls.primary_media_key(desc)
            if key:
                return key
        return cls.primary_media_key(node)

    @classmethod
    def navigable_urls(cls, node: ShadowNode) -> list[str]:
        """
        Extract all navigable (non-fragment, non-javascript) URLs from subtree.

        Agnostic: inspects ALL attributes on ALL descendants.
        Filters out fragment-only (#...) and javascript: pseudo-URLs.
        """
        skip = ('#', 'javascript:', 'data:', 'about:', 'blob:')
        result: list[str] = []
        for url in cls.all_urls(node):
            if not any(url.startswith(p) for p in skip):
                result.append(url)
        return result

def iter_elements(root: ShadowNode) -> Iterator[ShadowNode]:
    queue = deque([root])
    while queue:
        node = queue.popleft()
        if not node.tag.startswith('#'):
            yield node
        if node.shadow_root:
            queue.extend(node.shadow_root.children)
        queue.extend(node.children)

@dataclass
class ChunkGroup:
    chunk_id: int
    selectors: list
    trie_paths: list
    frequency: int
    content_types: set
    subtree_root: str
    signature: str = ""
    samples: list = field(default_factory=list)
    # v11 additions for subsumption tracking
    _instance_nodes: list = field(default_factory=list, repr=False)
    _structural_sig: str = ""  # Tree-isomorphism signature for filtering
    _is_subsumed: bool = False
    _parent_chunk_id: int = -1
    _relative_xpath: str = ""  # Portable cross-page selector (string form)
    _tokenized_selector: dict = field(default_factory=dict, repr=False)  # Structured selector

class _VocabularyScorer:
    """
    Multi-channel vocabulary scorer using tokenized matching.

    Avoids raw substring matching (which causes 'load' to match
    'uploads' in URLs). Instead:

    - Attribute name/value: tokenized via AttributeTokenizer, then
      exact-match against vocabulary tokens.
    - Text content: word-boundary regex matching to catch multi-word
      phrases ('load more') while preventing partial matches.
    """

    def __init__(self, vocabulary: frozenset[str]):
        self.vocabulary = vocabulary
        # Pre-compile word-boundary patterns for text matching
        self._text_patterns = {
            term: re.compile(r'(?<!\w)' + re.escape(term) + r'(?!\w)',
                             re.IGNORECASE)
            for term in vocabulary if len(term) > 1
        }
        # Single-char terms (>, <, etc.) use direct containment
        self._char_terms = frozenset(
            term for term in vocabulary if len(term) <= 1
        )

    def score_node(self, node: ShadowNode) -> int:
        """
        Multi-channel vocabulary scoring (§13.1).

        Scores against three channels:
          1. Attribute names (tokenized)
          2. Attribute values (tokenized)
          3. Visible text content (word-boundary regex)

        Returns total match count across all channels.
        """
        total = 0
        for attr_name, attr_val in node.get_all_attrs().items():
            # Channel 1: attribute name tokens
            name_tokens = set(AttributeTokenizer.tokenize(attr_name))
            for term in self.vocabulary:
                if term in name_tokens:
                    total += 1

            # Channel 2: attribute value tokens
            val_str = str(attr_val or '')[:300]
            if val_str:
                val_tokens = set(AttributeTokenizer.tokenize(val_str))
                for term in self.vocabulary:
                    if term in val_tokens:
                        total += 1

        # Channel 3: visible text content (word-boundary matching)
        text = (node.get_text() or '').strip()
        if text:
            text_lower = text.lower()
            for term, pattern in self._text_patterns.items():
                if pattern.search(text_lower):
                    total += 1
            for ch in self._char_terms:
                if ch in text_lower:
                    total += 1
        return total

class SearchInputCollector:
    VOCABULARY = frozenset({
        'search', 'q', 'query', 'find', 'keyword', 'lookup',
        'srch', 'buscar', 'recherche', 'suche',
    })
    # Value tokens that indicate an input is NOT a search field.
    # Applied agnostically against ALL attribute values, not just
    # 'type', 'name', or 'id'.  Discovered via frequency-filter
    # failures across multiple test sites.
    _EXCLUDED_TYPE_TOKENS = frozenset({
        'hidden', 'email', 'checkbox', 'radio', 'file',
        'image', 'color', 'date', 'range', 'password',
    })
    _EXCLUDED_NAME_RE = re.compile(
        r'(first.?name|last.?name|subbox|subscribe|signup|newsletter|'
        r'password|captcha|token|nonce|csrf|turnstile)',
        re.IGNORECASE,
    )
    def __init__(self, vocabulary: frozenset[str] | None = None):
        self.scorer = _VocabularyScorer(vocabulary or self.VOCABULARY)

    def collect(self, dom: ShadowDOM) -> ChunkGroup | None:
        scored: list[tuple[int, ShadowNode]] = []
        for node in dom.iter_elements():
            # Agnostic: catches <input>, <textarea>, <select>,
            # <div role="searchbox">, <custom-input contenteditable>, etc.
            if not AgnosticAttr.is_input_like(node):
                continue

            # Agnostic exclusion: scan ALL attribute values for
            # excluded type tokens and name patterns.
            excluded = False
            for _key, val in node.get_all_attrs().items():
                if not val:
                    continue
                val_lower = str(val).lower().strip()
                # Check for excluded type values (exact match on
                # short values — prevents 'hidden' in a long class)
                if len(val_lower) < 30 and val_lower in self._EXCLUDED_TYPE_TOKENS:
                    excluded = True
                    break
                # Check for excluded name/id patterns
                if self._EXCLUDED_NAME_RE.search(val_lower):
                    excluded = True
                    break
            if excluded:
                continue

            score = self.scorer.score_node(node)
            scored.append((score, node))
        if not scored:
            return None
        scored.sort(key=lambda x: -x[0])
        nodes = [node for _, node in scored]
        xpaths = [cached_xpath(n) for n in nodes]
        chunk = ChunkGroup(
            chunk_id=-1, selectors=xpaths, trie_paths=xpaths,
            frequency=len(nodes), content_types={ContentCategory.INPUT},
            subtree_root='/html/body', signature='[search_inputs]', samples=[],
        )
        chunk._instance_nodes = nodes
        return chunk

class PaginationCollector:
    VOCABULARY = frozenset({
        'next', 'prev', 'previous', 'page', 'pagination', 'pager',
        'load more', 'show more', 'see more', 'view more', 'read more',
        'load', 'older', 'newer', 'additional',
        '>', '<', '\u00bb', '\u00ab', '\u2192', '\u2190',
        'forward', 'back', 'last', 'first', 'paginat', 'more', 'results'
    })
    _PAGINATION_RE = re.compile(r'pagination', re.IGNORECASE)
    # Taxonomy "More" guard: matches "More X..." (1+ words after "more")
    _MORE_TAXONOMY_RE = re.compile(r'(?i)^more\s+\w')
    # Words that legitimize a "more X" phrase as pagination
    _MORE_PAGINATION_WORDS = frozenset({
        'results', 'pages', 'items', 'posts', 'stories',
        'articles', 'entries', 'comments',
    })
    # Shadow DOM widget tags to exclude
    _WIDGET_TAG_DENYLIST = frozenset({
        'slick-fab', 'slick-heartbeat', 'soso-button',
        'soso-icon-button', 'soso-icon',
    })
    # Agnostic negative attribute-value tokens: if ANY attribute on a
    # node contains one of these tokens, it's NOT a pagination element.
    # Discovered via test failures across diverse sites — media player
    # controls, cart buttons, social sharing, feed interaction widgets.
    # Uses substring matching against lowercased attribute values.
    _NEGATIVE_ATTR_TOKENS = frozenset({
        # Media player controls
        'playable', 'player', 'volume', 'mute', 'fullscreen',
        'pip', 'rewind', 'scrub', 'playback',
        # Media container signals
        'audio', 'video',
        # E-commerce interaction
        'cart', 'wishlist', 'addtocart',
        # Social feed interaction
        'reply', 'repost', 'retweet', 'bookmark',
        'dropdown', 'haspopup',
        # Content item controls
        'favorite', 'share', 'social',
    })

    def __init__(self, vocabulary: frozenset[str] | None = None):
        self.scorer = _VocabularyScorer(vocabulary or self.VOCABULARY)

    def collect(
        self,
        dom: ShadowDOM,
        structural_chunks: list | None = None,
    ) -> ChunkGroup | None:
        # Build exclusion set: all node IDs inside structural instances
        structural_node_ids: set[int] = set()
        if structural_chunks:
            for chunk in structural_chunks:
                if getattr(chunk, '_structural_sig', ''):
                    for inst_node in getattr(chunk, '_instance_nodes', []):
                        structural_node_ids.add(id(inst_node))
                        for desc in inst_node.iter_descendants():
                            structural_node_ids.add(id(desc))

        # Pre-compute widget ancestor set for O(1) denylist check.
        # Walking ancestors per-node is O(N*D); pre-building is O(N).
        _widget_deny_ids: set[int] = set()
        for node in dom.iter_elements():
            if node.tag.lower() in self._WIDGET_TAG_DENYLIST:
                _widget_deny_ids.add(id(node))
                for desc in node.iter_descendants():
                    _widget_deny_ids.add(id(desc))

        seen_ids: set[int] = set()
        scored: list[tuple[int, ShadowNode]] = []
        for node in dom.iter_elements():
            nid = id(node)
            if nid in seen_ids:
                continue

            # ── O(1) widget denylist ──
            if nid in _widget_deny_ids:
                continue

            # ── O(1) structural exclusion (moved EARLY) ──
            if structural_node_ids and nid in structural_node_ids:
                continue

            # ── Cheap O(attrs) checks: determine candidacy BEFORE scoring ──
            is_button_like = AgnosticAttr.is_button_like(node)
            has_url = AgnosticAttr.node_has_url(node)
            has_pagination_attr = False
            for attr_name, attr_val in node.get_all_attrs().items():
                combined = attr_name.lower() + ' ' + str(attr_val or '').lower()
                if self._PAGINATION_RE.search(combined):
                    has_pagination_attr = True
                    break

            # Quick reject: if not button-like, no URL, no pagination attr
            # → this node can never be included. Skip expensive scoring.
            if not is_button_like and not has_url and not has_pagination_attr:
                continue

            # ── Expensive scoring (only for candidates) ──
            score = self.scorer.score_node(node)

            # ── Zero-score gating ──
            if score == 0 and not has_pagination_attr:
                continue

            # ── Inclusion decision ──
            include = is_button_like or has_pagination_attr
            if not include and has_url and score > 0:
                include = True
            if not include:
                continue

            # ── Content-weight guard (only for included candidates) ──
            text_len = len(node.get_text().strip())
            if text_len > 200:
                continue

            # ── Agnostic negative-token exclusion ──
            # Reject nodes whose attributes (or shallow descendant attrs)
            # contain tokens indicating non-pagination roles: media
            # controls, cart widgets, social sharing, etc.
            # Depth-limited to avoid O(N*D) on deep subtrees.
            excluded_by_token = False
            _check_nodes = [node]
            for child in node.get_children(include_shadow=True):
                _check_nodes.append(child)
                for gc in child.get_children(include_shadow=True):
                    _check_nodes.append(gc)
            for cn in _check_nodes:
                if AgnosticAttr.is_media_container(cn):
                    excluded_by_token = True
                    break
                for _key, val in cn.get_all_attrs().items():
                    if not val:
                        continue
                    val_lower = str(val).lower()[:200]
                    for neg in self._NEGATIVE_ATTR_TOKENS:
                        if neg in val_lower:
                            excluded_by_token = True
                            break
                    if excluded_by_token:
                        break
                if excluded_by_token:
                    break
            if excluded_by_token:
                continue

            # ── Taxonomy "More" false-positive guard ──
            # Links like "MORE I CHING INSIGHT" or "More Eastern Wisdom"
            # are taxonomy section headers, not pagination buttons.
            # A legitimate "More" pagination button is short (1-2 words).
            # Reject if text starts with "more" followed by 2+ content
            # words that aren't pagination vocabulary.
            if text_len > 0:
                text_stripped = node.get_text().strip()
                if self._MORE_TAXONOMY_RE.match(text_stripped):
                    # Starts with "more" + multi-word content → taxonomy
                    # Exception: "more results", "more pages" are pagination
                    words_after = text_stripped.split()[1:]
                    if words_after and not any(
                        w.lower() in self._MORE_PAGINATION_WORDS
                        for w in words_after[:2]
                    ):
                        continue

            seen_ids.add(nid)
            scored.append((score, node))
        if not scored:
            return None
        scored.sort(key=lambda x: -x[0])
        nodes = [node for _, node in scored]
        xpaths = [cached_xpath(n) for n in nodes]
        chunk = ChunkGroup(
            chunk_id=-1, selectors=xpaths, trie_paths=xpaths,
            frequency=len(nodes), content_types={ContentCategory.BUTTON},
            subtree_root='/html/body', signature='[pagination_buttons]', samples=[],
        )
        chunk._instance_nodes = nodes
        return chunk
