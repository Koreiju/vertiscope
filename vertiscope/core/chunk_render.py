"""
chunk_render.py — Per-instance HTML + structured-text rendering.

Downstream of :mod:`vertiscope.core.chunk_builder` and
:mod:`vertiscope.core.chunk_query`. For each ``Chunk`` produced by the
pipeline, this module walks the matching DOM subtrees and emits one
:class:`ChunkInstanceRender` per populated instance:

* ``html_raw``       — the full HTML of the instance subtree, with **all
  resources preserved** (anchors, images, scripts stripped only of
  inline handlers). This is the canonical "give me the bytes back"
  representation stored in Kuzu.
* ``rendered_text``  — a minimal markdown-lite flattening used for
  embedding. Hyperlinks collapse to their anchor text; structural
  whitespace is preserved so paragraphs survive; attributes are dropped.
* ``fields``         — the address→values dict from
  :func:`vertiscope.core.chunk_query.query_chunk`.

Separately, :func:`render_summary` reproduces the existing
"Instance N: /a/h3/text(): […]" human-readable view so debugging +
demo output can keep that presentation alongside the new render
objects.
"""

from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional

from vertiscope.core.shadow_html_parser import (
    ShadowDOM,
    ShadowNode,
    VOID_ELEMENTS,
    get_absolute_xpath,
)
from vertiscope.core.chunk_query import _evaluate_trie
from vertiscope.core.xpath_utils import generalize_xpath
from vertiscope.core.chunk_query import InstanceResult, query_chunk
from vertiscope.core.chunk_builder import Chunk


logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Render object
# ---------------------------------------------------------------------------


@dataclass
class ChunkInstanceRender:
    """One DOM-resolved instance of a chunk pattern, ready to embed/persist.

    A single :class:`vertiscope.core.chunk_builder.Chunk` produces N of
    these — one per ``member_xpaths`` entry that actually has tagged
    content. The embedder, persister, and retriever all consume this.
    """

    chunk_id: str
    instance_idx: int               # 0-based ordinal within the chunk
    pattern: str                    # generalized xpath (same as chunk.pattern)
    absolute_xpath: str             # concrete xpath of this instance root
    html_raw: str                   # full subtree HTML (resources preserved)
    rendered_text: str              # markdown-lite flattening (for embedding)
    fields: Dict[str, List[Any]] = field(default_factory=dict)
    embedding: Optional[List[float]] = None  # filled in by embedder
    image_url: Optional[str] = None
    link_url: Optional[str] = None

    # Deterministic, re-scan-stable per-instance id.
    #
    # Keyed on ``(url, generalized_xpath, html_content_hash)`` so that a
    # fresh scan of the same URL collapses identical cards onto the same
    # Kuzu row rather than minting a new one every visit. Including
    # ``html_content_hash`` keeps content changes distinct (edited card =
    # new row); including ``pattern`` instead of the concrete
    # ``absolute_xpath`` means reshuffles of siblings (common on
    # personalized feeds) don't fragment the identity.
    #
    # The legacy signature accepted a ``version_id`` — callers still pass
    # a string; we just reinterpret it as ``url``. Tests that used
    # ``"v1"`` / ``"v2"`` continue to pass because different inputs still
    # produce different hashes.
    def instance_id(self, url: str) -> str:
        content_hash = hashlib.sha1(
            (self.html_raw or "").encode("utf-8")
        ).hexdigest()[:8]
        return hashlib.sha1(
            f"inst|{url}|{self.pattern}|{content_hash}".encode("utf-8")
        ).hexdigest()[:20]


# ---------------------------------------------------------------------------
# HTML serialization
# ---------------------------------------------------------------------------


# Inline / flow tags whose internal text should stay on the same line.
# Anything NOT in here forces a paragraph break in rendered_text.
_INLINE_TAGS = frozenset({
    "a", "abbr", "b", "bdi", "bdo", "cite", "code", "dfn", "em", "i",
    "kbd", "mark", "q", "s", "samp", "small", "span", "strong", "sub",
    "sup", "time", "u", "var", "wbr",
})

# Tags whose content should be completely dropped during text rendering.
_DROP_TAGS = frozenset({
    "script", "style", "noscript", "template", "head", "meta", "link",
})

# Inline event handlers — strip from html_raw so saved HTML is inert.
_EVENT_ATTRS_RE = re.compile(r"^on[a-z]+$", re.IGNORECASE)


def _escape_attr(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace('"', "&quot;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _escape_text(value: str) -> str:
    return (
        str(value)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _serialize_html(node: ShadowNode) -> str:
    """Return the HTML of ``node`` with resources preserved.

    Differs from :py:meth:`ShadowNode.to_html` in that:
    * event-handler attributes (``onclick``, ``onerror``, …) are stripped
      so the saved HTML is inert when re-rendered in a browser shell;
    * indentation is omitted — the output is one contiguous string (we
      don't want whitespace drift polluting content hashes).

    Shadow-root children are flattened into the main output. ``VOID``
    elements (``img``, ``br``, …) are closed inline.
    """
    tag = node.tag
    if node.is_shadow_root:
        parts: List[str] = []
        for child in node.children:
            parts.append(_serialize_html(child))
        return "".join(parts)
    if tag.startswith("#") or tag.lower() in _DROP_TAGS:
        return ""

    attrs: List[str] = []
    for k, v in node.attributes.items():
        if _EVENT_ATTRS_RE.match(k):
            continue
        if v is None or v is True:
            attrs.append(k)
        else:
            attrs.append(f'{k}="{_escape_attr(v)}"')
    attrs_str = (" " + " ".join(attrs)) if attrs else ""
    opening = f"<{tag}{attrs_str}>"

    if tag.lower() in VOID_ELEMENTS:
        return opening

    body: List[str] = []
    if node.text:
        body.append(_escape_text(node.text))
    # Shadow root content is hoisted right after self's direct text.
    if node.shadow_root is not None:
        for shadow_child in node.shadow_root.children:
            body.append(_serialize_html(shadow_child))
    for child in node.children:
        body.append(_serialize_html(child))
        if child.tail:
            body.append(_escape_text(child.tail))

    return f"{opening}{''.join(body)}</{tag}>"


def extract_instance_html(dom: ShadowDOM, absolute_xpath: str) -> str:
    """Return the HTML for the subtree rooted at ``absolute_xpath``.

    Resources (``<img src>``, ``<a href>``) are preserved; only inline
    event handlers are stripped. Returns an empty string if the xpath
    doesn't resolve in ``dom``.
    """
    node = _find_by_absolute_xpath(dom, absolute_xpath)
    if node is None:
        logger.debug("extract_instance_html: xpath %r did not resolve", absolute_xpath)
        return ""
    return _serialize_html(node)


def _find_by_absolute_xpath(dom: ShadowDOM, absolute_xpath: str) -> Optional[ShadowNode]:
    """Lookup a node by its absolute xpath via full-tree scan.

    The DOM's :py:meth:`ShadowDOM.xpath` can handle absolute xpaths, but
    it walks the whole tree every time. For a batch of N instances we
    do one scan and resolve by string match — O(total_nodes) total, not
    O(N × total_nodes).
    """
    for node in dom.iter_all():
        if get_absolute_xpath(node) == absolute_xpath:
            return node
    return None


# ---------------------------------------------------------------------------
# Markdown-lite rendering
# ---------------------------------------------------------------------------


_WS_RE = re.compile(r"[ \t\r\f\v]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")


def html_to_rendered_text(html: str) -> str:
    """Flatten an HTML fragment to embed-friendly markdown-lite text.

    Rules (intentionally minimal — the user asked for "reasonable scope"):

    * **Anchor text inlined** — ``<a href="/x">Cards</a>`` → ``Cards``.
      No URL retained.
    * **Block tags separate paragraphs** — anything not in
      :data:`_INLINE_TAGS` forces a blank line between runs of text so
      paragraph structure survives.
    * **List items** (``<li>``) get ``- `` prefixes.
    * **Images / inputs / buttons** contribute their ``alt`` /
      ``placeholder`` / ``aria-label`` when present — that's the only
      text hint they carry.
    * **Scripts / styles / templates** — dropped entirely.
    """
    if not html:
        return ""
    # Parse the HTML fragment back into a ShadowDOM and walk.
    dom = ShadowDOM(html)
    buf: List[str] = []
    _render_node(dom.root, buf)
    text = "".join(buf)
    # Collapse runs of whitespace inside lines but preserve paragraph breaks.
    lines = [
        _WS_RE.sub(" ", line).strip() for line in text.split("\n")
    ]
    text = "\n".join(lines)
    text = _MULTI_NEWLINE_RE.sub("\n\n", text)
    return text.strip()


# Attributes whose VALUE is human-readable text when the node has no body
# text of its own (img, input, svg, etc.).
_TEXT_HINT_ATTRS = (
    "alt", "aria-label", "aria-describedby", "title",
    "placeholder", "aria-roledescription",
)


def _render_node(node: ShadowNode, buf: List[str]) -> None:
    tag = node.tag.lower()
    if tag.startswith("#"):
        # Root / text placeholder — recurse into children.
        for c in node.children:
            _render_node(c, buf)
            if c.tail:
                buf.append(c.tail)
                buf.append(" ")
        return

    if tag in _DROP_TAGS:
        return

    is_block = tag not in _INLINE_TAGS
    is_list_item = tag == "li"

    if is_block and buf and not buf[-1].endswith("\n\n"):
        # Open a new paragraph.
        if not buf[-1].endswith("\n"):
            buf.append("\n")
        buf.append("\n")
    if is_list_item:
        buf.append("- ")

    # Direct text.
    if node.text:
        buf.append(node.text)
        buf.append(" ")

    # Shadow root children hoisted.
    if node.shadow_root is not None:
        for c in node.shadow_root.children:
            _render_node(c, buf)
            if c.tail:
                buf.append(c.tail)
                buf.append(" ")

    # Light-DOM children.
    for c in node.children:
        _render_node(c, buf)
        if c.tail:
            buf.append(c.tail)
            buf.append(" ")

    # Attribute-text fallback for leaves (img alt, input placeholder…).
    no_text_children = not node.text and not node.children and not node.shadow_root
    if no_text_children:
        for attr in _TEXT_HINT_ATTRS:
            v = (node.get_attr(attr) or "").strip()
            if v and len(v) > 1:
                buf.append(v)
                buf.append(" ")
                break

    if is_block:
        if not buf or not buf[-1].endswith("\n"):
            buf.append("\n")
        buf.append("\n")


# ---------------------------------------------------------------------------
# Content-structure summary → embed-friendly text
# ---------------------------------------------------------------------------


_URL_LIKE_ATTRS = frozenset({
    "href", "src", "srcset", "data-src", "data-lazy-src",
    "data-original", "data-original-src", "data-image", "poster",
    "action", "formaction", "xlink:href", "style",
})


# Splits URLs into semantic tokens: domain parts, path segments, filename
# stems. Dropping query strings, fragments, and common junk (''.jpg'',
# ''wp-content'') keeps the embedder's attention on words that actually
# encode topic ("ions", "tarot", "product-launch") rather than the noise
# of raw URLs.
_URL_TOKEN_SPLIT = re.compile(r"[/?&#=.:_-]+")
_URL_TOKEN_STOP = frozenset({
    "http", "https", "www", "html", "htm", "php", "aspx", "jsp",
    "wp", "content", "uploads", "assets", "static", "images", "img",
    "cdn", "com", "net", "org", "io", "co", "uk", "jpg", "jpeg", "png",
    "gif", "svg", "webp", "mp4", "mp3", "pdf", "",
})


def _tokenize_url(raw: str, limit: int = 8) -> str:
    """Split a URL into semantic tokens suitable for semantic embedding.

    ``https://noetic.org/wp-content/uploads/2021/ions-study-result.jpg``
    becomes ``noetic ions study result``. Keeps the embedder from
    drowning in ``https``/``wp-content`` noise while still letting the
    domain + last meaningful path segments influence the vector.
    """
    if not raw:
        return ""
    # Strip query + fragment early so ``?utm=...`` never pollutes.
    core = raw.split("?", 1)[0].split("#", 1)[0]
    toks = [t.lower() for t in _URL_TOKEN_SPLIT.split(core) if t]
    keep: List[str] = []
    seen: set = set()
    for t in toks:
        if t in _URL_TOKEN_STOP:
            continue
        if t.isdigit():
            continue
        if len(t) < 3:
            continue
        if t in seen:
            continue
        seen.add(t)
        keep.append(t)
        if len(keep) >= limit:
            break
    return " ".join(keep)


_URL_ATTR_REGEX = re.compile(
    r"(?:src|href|srcset|poster|data-src|data-lazy-src|data-original|data-image|xlink:href)"
    r"\s*=\s*['\"]([^'\"]+)['\"]",
    re.IGNORECASE,
)


def _url_tokens_from_html(html: str, limit: int = 24) -> str:
    """Extract src/href URL tokens from raw HTML as a last-resort text source.

    Used when a chunk instance has no visible text or alt/title attributes —
    e.g. a widget logo `<img src="/widgetOL.png">` inside shadow DOM. Keeps
    the embedder's signal non-empty and lets the instance survive into
    storage so semantic search can still match on URL tokens.
    """
    if not html:
        return ""
    urls = _URL_ATTR_REGEX.findall(html)
    out: List[str] = []
    for u in urls:
        toks = _tokenize_url(u)
        if toks:
            out.append(toks)
        if len(out) >= limit:
            break
    return " ".join(out)


def _text_from_fields(fields: Dict[str, List[Any]]) -> str:
    """Render a ``{rel_xpath: [values]}`` summary as space-joined text.

    Rules:

    * ``.../text()`` entries contribute their values directly.
    * Attribute entries (``.../@alt``, ``.../@aria-label``, …)
      contribute if the attribute is human-readable.
    * URL-like attributes (``href`` / ``src`` / ``srcset`` / ``poster``)
      contribute their **semantic tokens** — domain + meaningful path
      segments — so the embedder sees ``noetic meditation`` instead of
      a raw ``https://...``. Query strings and common junk tokens are
      dropped.
    * Each value is whitespace-normalised; field values join with a
      single space so the embedder sees distinct tokens at field
      boundaries.
    """
    if not fields:
        return ""
    parts: List[str] = []
    for key, vals in fields.items():
        if not vals:
            continue
        if key.endswith("/text()"):
            parts.extend(str(v) for v in vals)
            continue
        if "/@" in key:
            attr = key.rsplit("/@", 1)[-1].lower()
            if attr in _URL_LIKE_ATTRS:
                for v in vals:
                    toks = _tokenize_url(str(v))
                    if toks:
                        parts.append(toks)
                continue
            parts.extend(str(v) for v in vals)
    cleaned = [" ".join(p.split()) for p in parts if p and p.strip()]
    return " ".join(cleaned)


# ---------------------------------------------------------------------------
# Orchestrator — Chunk → [ChunkInstanceRender]
# ---------------------------------------------------------------------------


def render_chunk_instances(
    chunk: Chunk,
    dom: ShadowDOM,
    xpath_map: Optional[Dict[str, ShadowNode]] = None,
    gen_xpath_map: Optional[Dict[int, str]] = None,
) -> List[ChunkInstanceRender]:
    if xpath_map is not None:
        return _render_chunk_instances_with_lookup(
            chunk, dom, xpath_map, gen_xpath_map,
        )
    xpath_to_node: Dict[str, ShadowNode] = {}
    for node in dom.iter_all():
        xp = get_absolute_xpath(node)
        if xp:
            xpath_to_node[xp] = node
        sroot = getattr(node, "shadow_root", None)
        if sroot is not None and getattr(sroot, "children", None):
            sxp = get_absolute_xpath(sroot)
            if sxp:
                xpath_to_node[sxp] = sroot
    return _render_chunk_instances_with_lookup(
        chunk, dom, xpath_to_node, gen_xpath_map,
    )

def _render_chunk_instances_with_lookup(
    chunk: Chunk,
    dom: ShadowDOM,
    xpath_to_node: Dict[str, ShadowNode],
    gen_xpath_map: Optional[Dict[int, str]] = None,
) -> List[ChunkInstanceRender]:
    """Produce one :class:`ChunkInstanceRender` per member xpath.

    When ``gen_xpath_map`` (``id(node) -> generalized_xpath``) is passed
    we skip the per-instance ``node.iter_all()`` / ``generalize_xpath``
    loop entirely — that work is identical for every chunk rooted in the
    same DOM, so a caller rendering all chunks at once should build the
    map once via :func:`build_gen_xpath_map` and share it.
    """
    renders = []
    for idx, mxp in enumerate(chunk.member_xpaths):
        node = xpath_to_node.get(mxp)
        html_raw = _serialize_html(node) if node else ""
        if not node:
            logger.debug("render_chunk_instances: xpath %r did not resolve", mxp)
            continue

        extracted: Dict[str, List[Any]] = {}
        if chunk.extraction_trie:
            base_gen_xp = generalize_xpath(mxp)
            if gen_xpath_map is not None:
                node_to_gen_xpath = gen_xpath_map
            else:
                node_to_gen_xpath = {}
                for descendant in node.iter_all():
                    abs_xp = get_absolute_xpath(descendant)
                    node_to_gen_xpath[id(descendant)] = generalize_xpath(abs_xp)

            _evaluate_trie(
                node, chunk.extraction_trie, "", base_gen_xp,
                node_to_gen_xpath, extracted
            )
        
        if not extracted and mxp == chunk.representative_xpath:
            extracted = dict(chunk.content_fields)

        text = _text_from_fields(extracted)
        if not text:
            text = html_to_rendered_text(html_raw)

        if not text:
            # Media-only fallback: preserve instances that have no text but
            # do carry URLs (img/video/link chrome). Pull src/href values
            # from the raw HTML and tokenize them so the embedder still sees
            # a semantic signal and the html_raw survives into storage.
            url_tokens = _url_tokens_from_html(html_raw)
            if url_tokens:
                text = url_tokens



        if not text:
            text = ""

        image_url = chunk.image_urls.get(mxp)
        link_url = getattr(chunk, "link_urls", {}).get(mxp)

        renders.append(
            ChunkInstanceRender(
                chunk_id=chunk.chunk_id,
                instance_idx=idx,
                pattern=chunk.pattern,
                absolute_xpath=mxp,
                html_raw=html_raw,
                rendered_text=text,
                fields=extracted,
                image_url=image_url,
                link_url=link_url,
            )
        )
    return renders


def build_gen_xpath_map(
    dom: ShadowDOM,
    xpath_map: Optional[Dict[str, ShadowNode]] = None,
) -> Dict[int, str]:
    """Return ``id(node) -> generalized_xpath`` for every node in ``dom``.

    Built once per page so every chunk's
    :func:`_render_chunk_instances_with_lookup` can skip rebuilding the
    same map for each instance it renders. The ``xpath_map`` shortcut
    lets us reuse an already-walked ``xpath -> node`` index instead of
    iterating the DOM again.
    """
    out: Dict[int, str] = {}
    if xpath_map is not None:
        for xp, node in xpath_map.items():
            if xp:
                out[id(node)] = generalize_xpath(xp)
        return out
    for node in dom.iter_all():
        xp = get_absolute_xpath(node)
        if xp:
            out[id(node)] = generalize_xpath(xp)
    return out


def render_all_chunks(
    chunks: Iterable[Chunk],
    dom: ShadowDOM,
    xpath_map: Optional[Dict[str, ShadowNode]] = None,
) -> List[ChunkInstanceRender]:
    """Flatten rendering across every chunk on a page.

    Pass a pre-built ``xpath_map`` (from
    :func:`~vertiscope.core.chunk_builder.build_xpath_node_map`) to skip the
    O(N) DOM walk when the caller already built one for the text/structure
    providers.
    """
    if xpath_map is None:
        xpath_map = {}
        for node in dom.iter_all():
            xp = get_absolute_xpath(node)
            if xp:
                xpath_map[xp] = node

    gen_xpath_map = build_gen_xpath_map(dom, xpath_map=xpath_map)

    out: List[ChunkInstanceRender] = []
    for chunk in chunks:
        out.extend(_render_chunk_instances_with_lookup(
            chunk, dom, xpath_map, gen_xpath_map,
        ))
    return out


# ---------------------------------------------------------------------------
# Legacy presentation — keep the "Instance N:" dict view available
# ---------------------------------------------------------------------------


def render_summary(
    chunk: Chunk,
    instances: Optional[List[ChunkInstanceRender]] = None,
    dom: Optional[ShadowDOM] = None,
) -> str:
    """Return the per-chunk summary in the *original* presentation format.

    Either pass in pre-rendered ``instances`` (fast path, reuses HTML)
    or pass ``dom`` to re-query. Matches the old demo output so existing
    debug expectations keep holding:

    ::

        [Chunk] Pattern: /html/body/main/section/article
        Found 3 non-empty instances.
          Instance 1 @ /html/body/main/section[2]/article[1]:
            /h2/text(): ['The Fool']
            /p/text(): ['New beginnings, spontaneity, a free spirit.']
            …
    """
    if instances is None:
        if dom is None:
            raise ValueError("render_summary needs either instances or dom")
        instances = render_chunk_instances(chunk, dom)

    lines: List[str] = []
    lines.append(f"[Chunk] Pattern: {chunk.pattern}")
    lines.append(f"Found {len(instances)} non-empty instance(s).")
    for inst in instances:
        lines.append(f"  Instance {inst.instance_idx + 1} @ {inst.absolute_xpath}:")
        for path, vals in inst.fields.items():
            lines.append(f"    {path}: {vals}")
    return "\n".join(lines)
