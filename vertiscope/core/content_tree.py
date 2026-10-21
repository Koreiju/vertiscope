# NOTE (vertiscope): RESTORED 2026-08-09. Deleted in the extraction on the
# evidence of a runtime reachability trace, which was wrong: it was
# unreachable because the pipeline never wired it, not because it was
# dead. HTML_DEDUP_CONTENT_TREE_GOAL.md is binding and says rendered_text
# (what we index) must be DERIVED from this tree. Not yet wired — see
# docs/THEORY.md and notes/reading/02-output-format-and-identity.md.
"""content_tree.py — the §U deduplicated content tree.

Transforms a chunk's **existing** ``{rel_xpath: [values]}`` field extraction
(the output of the existing content-detection ruleset — V.2 / §U) into the
**deduplicated pure-text content tree** that the black-slate HTML chunk card
renders (``USER_REQUIREMENTS_VERBATIM.md`` §U,
``docs/HTML_DEDUP_CONTENT_TREE_GOAL.md``).

Design decision (verified live 2026-06-13, goal §1.5): build the tree from the
already-bookkept ``fields`` dict, **not** by re-parsing ``html_raw``. This is
the most faithful realisation of "use the existing ruleset" and it is purely
**additive** — it never alters chunk identity, counts, or ordering (V.1).

The transform (over ``fields``):

1. **Extract content units** — each ``fields`` leaf becomes a unit tagged
   ``URL`` (``@href``/``@src``/...), ``LABEL`` (``@title``/``@aria-label``/
   ``@alt``/...), or ``TEXT`` (``.../text()``). Structural attributes are
   dropped. Empty values are dropped (e.g. ``alt=""``).
2. **Deduplicate** (chunk-scoped, the core of §U) — a TEXT/LABEL unit whose
   normalised token-set is a **subset** of another TEXT/LABEL unit's token-set
   is dropped (the superset subsumes it); exact duplicates collapse to one.
   This is what turns the title's ``aria-label`` + ``h3@title`` + ``h3`` text
   (three identical copies) into one line, and what makes a ``<li title="450
   all-time views">`` win over its fragmentary ``all-time views:`` + ``450``.
   URL units never collapse against text; identical URLs dedupe.
3. **Order** — URL units first (the card's link/image identity), then
   TEXT/LABEL units, each in document order.
4. **Colon-join** — a label-style ``key:`` line (trailing colon) joins its
   following value into one line (``Mediatype:`` + ``Text`` → ``Mediatype:
   Text``).
5. **Print** — one unit per line, pure text, no markup. (A single card is a
   leaf of the page tree, so its content tree is a flat list; genuine
   hierarchy — sub-panels and ``{ref}`` expansions — introduces tab depth at
   the panel layer, ``BLACK_SLATE_GOAL.md`` §3/§6.)

The §U worked example is the binding golden I/O — see
``backend/tests/test_content_tree.py``.
"""

from __future__ import annotations

import re
from typing import Any, List, Mapping, Tuple

# Attribute classes ---------------------------------------------------------
# URL attributes whose value is content (the card's link / media), surfaced
# verbatim as their own line. Mirrors chunk_render._URL_LIKE_ATTRS.
_URL_ATTRS = frozenset({
    "href", "src", "srcset", "poster", "data-src", "data-lazy-src",
    "data-original", "data-original-src", "data-image", "xlink:href",
})
# Human-text attributes whose value is content (a curated label).
_LABEL_ATTRS = frozenset({
    "title", "aria-label", "alt", "placeholder", "aria-roledescription",
})

KIND_URL = "url"
KIND_LABEL = "label"
KIND_TEXT = "text"

_WS_RE = re.compile(r"\s+")
# Unicode-aware word runs (letters + digits across ALL scripts, minus '_'), so
# the §U subsumption dedup works on non-ASCII content too — CJK / accented /
# Cyrillic titles over the URL spectrum. The old `[a-z0-9]+` produced an EMPTY
# token-set for non-Latin text (so duplicate CJK titles never collapsed) and
# split accented words on the accent ("Amélie" → am, lie).
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


# An HTML tag: '<' followed by a letter / '!' / '/' then up to the next '>'.
# Requiring that first char keeps stray '<'/'>' in real text ("a < b", "x > y",
# "price <$5") intact while matching real markup (<iframe…>, <img…>, <style>,
# </p>, <!--…-->).
_HTML_TAG_RE = re.compile(r"<[a-zA-Z!/][^>]*>")


def _norm(value: Any) -> str:
    """Whitespace-collapse + trim a scalar value to a single clean string.

    Also STRIP embedded HTML tags: across a large spectrum of real sites some
    ``fields`` text leaves carry serialized markup (tracking ``<iframe>``/
    ``<img>`` pixels, ``<noscript>`` / ``<style>`` blobs) that the slate must
    never render verbatim (§T pure-text). Stripping reduces inline-tagged text
    to plain text and pure-markup elements to empty (then dropped by callers)."""
    s = _HTML_TAG_RE.sub(" ", str(value))
    return _WS_RE.sub(" ", s).strip()


def _first_value(vals: Any) -> str:
    """``fields`` values may be a list (the dataclass shape) or a scalar (the
    chunk_details payload). Return the first non-empty, normalised."""
    if isinstance(vals, (list, tuple)):
        for v in vals:
            s = _norm(v)
            if s:
                return s
        return ""
    return _norm(vals)


def _tokens(text: str) -> frozenset:
    """Normalised token-set for subsumption dedup (lowercase, Unicode word
    runs — letters+digits across scripts, so non-ASCII titles dedupe too)."""
    return frozenset(_TOKEN_RE.findall(text.lower()))


def _classify_leaf(leaf: str):
    """Return the content kind for an xpath leaf (``@attr`` / ``text()``), or
    ``None`` if the leaf is structural / non-content."""
    if leaf == "text()":
        return KIND_TEXT
    if leaf.startswith("@"):
        attr = leaf[1:].lower()
        if attr in _URL_ATTRS:
            return KIND_URL
        if attr in _LABEL_ATTRS:
            return KIND_LABEL
    return None


_DATA_URI_RE = re.compile(r"^data:([^;,]*)[;,]")


def _compact_data_uri(value: str) -> str:
    """A ``data:`` URI is inline content but not human-meaningful as full text;
    render it as a compact ``data:<mediatype>`` marker (the inline media is
    still represented, but the multi-hundred-char payload is dropped) — keeps
    the slate minimal (§T) without losing the fact that media is present."""
    m = _DATA_URI_RE.match(value)
    if m:
        mt = m.group(1) or "inline"
        return f"data:{mt}"
    return value


def _extract_units(fields: Mapping[str, Any]) -> List[Tuple[str, str]]:
    """Phase 1 — fields → ordered ``(kind, value)`` content units."""
    units: List[Tuple[str, str]] = []
    for key, vals in fields.items():
        value = _first_value(vals)
        if not value:
            continue
        parts = [p for p in str(key).strip("/").split("/") if p]
        if not parts:
            continue
        kind = _classify_leaf(parts[-1])
        if kind is None:
            continue
        if kind == KIND_URL:
            value = _compact_data_uri(value)
        units.append((kind, value))
    return units


def _dedupe(units: List[Tuple[str, str]]) -> List[Tuple[str, str]]:
    """Phase 2 — token-set subsumption over TEXT/LABEL; identical URL dedupe.

    A TEXT/LABEL unit is dropped when its token-set is a (strict) subset of
    another TEXT/LABEL unit's token-set, or an exact duplicate of one already
    kept. URL units only collapse on exact value equality.
    """
    tl = [(i, k, v, _tokens(v)) for i, (k, v) in enumerate(units)
          if k in (KIND_TEXT, KIND_LABEL)]

    dropped = set()
    seen_text = set()           # for exact-duplicate collapse
    for i, k, v, tk in tl:
        if not tk:              # numeric / punctuation-only value: keep (no token basis)
            continue
        # exact duplicate already kept?
        if tk in seen_text:
            dropped.add(i)
            continue
        subsumed = False
        for j, k2, v2, tk2 in tl:
            if j == i or j in dropped:
                continue
            if tk < tk2:        # strict subset → the other subsumes this one
                subsumed = True
                break
        if subsumed:
            dropped.add(i)
        else:
            seen_text.add(tk)

    kept: List[Tuple[str, str]] = []
    seen_url = set()
    for i, (k, v) in enumerate(units):
        if i in dropped:
            continue
        if k == KIND_URL:
            if v in seen_url:
                continue
            seen_url.add(v)
        kept.append((k, v))
    return kept


def _colon_join(lines: List[str]) -> List[str]:
    """Phase 4 — a trailing-colon label line absorbs the next line
    (``Mediatype:`` + ``Text`` → ``Mediatype: Text``)."""
    out: List[str] = []
    i = 0
    n = len(lines)
    while i < n:
        cur = lines[i]
        if cur.endswith(":") and i + 1 < n:
            out.append(cur + " " + lines[i + 1])
            i += 2
        else:
            out.append(cur)
            i += 1
    return out


def fields_to_content_tree(fields: Mapping[str, Any]) -> str:
    """The §U transform: existing ``{xpath: [values]}`` extraction →
    deduplicated pure-text content tree (one content unit per line)."""
    if not fields:
        return ""
    units = _extract_units(fields)
    kept = _dedupe(units)
    # Phase 3 — URL units first (link/image identity), then text/label, each
    # in document order.
    url_lines = [v for (k, v) in kept if k == KIND_URL]
    text_lines = [v for (k, v) in kept if k != KIND_URL]
    text_lines = _colon_join(text_lines)
    return "\n".join(url_lines + text_lines)
