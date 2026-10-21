"""The content address — the pipeline's singular output type.

Everything the scanner finds is reported as one kind of value: a
:class:`ContentAddress`. It is THEORY Definition 10.1's detection with the
*value* projected out, prefixed by the document, and with the accessor
extended by its sub-variable::

    (url tree, absolute xpath, content tag, firing detector[sub])

Four components, four jobs:

``url``
    Which document. Decomposed into a path (`host`, then path segments) so
    that a trie over addresses is global across a crawl rather than per-page.

``xpath``
    **Absolute**, indices intact. This is the ordered-retrieval form: THEORY
    Prop. 11.2 gives injectivity and makes ancestry a prefix test, and
    Cor. 11.3 concludes the addresses of a document form a trie. Sorting
    children in document order therefore *is* sorting the trie.

``tag``
    ``category.subcategory`` from the extraction rules — one of eighteen
    labels (THEORY Def. 10.1's set `K`). A flat label set: the only
    operations on it are equality and membership.

``accessor``
    The detection mechanism that fired, plus the intrinsic sub-path within it
    (``srcset[1]``, ``text()@412``, ``ld_json:url/itemListElement/3/url``).
    THEORY Remark 10.3 makes provenance a primal: it is the only component
    recording *how* a value was observed, so it is the only thing that can
    break a tie between two identical strings.

The generalized form is derived, not stored: :func:`anchored_pattern` is the
input boundary to hashing and duplication measures, while the absolute form
stays canonical for retrieval.

Why the address rather than a content hash is the identity
----------------------------------------------------------
A content-keyed identifier cannot separate content-identical siblings
(THEORY Thm. 22.5.7), which is what pinned defect B10 records: identity
degenerates whenever the rendered payload is empty, since `sha1("")` is
constant. An address is a property of *position and provenance*, not of
payload, so it separates whatever the document separates and never collapses
on empty content.

Measured over the 54-page corpus: 106,789 detections, **0** addresses
carrying two different values. See ``scripts/audit_addressing.py``.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Iterable, List, Optional, Sequence, Tuple
from urllib.parse import urlsplit

from .aam import RENDER_CLASS as _AAM_RENDER_CLASS

#: The canonical eighteen, from the authority rather than restated here.
_SENSOR_CLASSES = frozenset(_AAM_RENDER_CLASS.values())

__all__ = [
    "ContentAddress",
    "RENDER_CLASSES",
    "address_of",
    "addresses_of",
    "anchored_pattern",
    "split_steps",
    "url_steps",
    "LANDMARK_TAGS",
    "LANDMARK_ROLES",
]

# --- canonical key encoding -------------------------------------------------
#
# The key must be injective: two addresses may never produce one string, or
# the trie and every store keyed on it would silently merge content. Escaping
# the separator out of each component makes `split(SEP)` recover exactly the
# original components, so `parse(key(a)) == a` for every address.

_SEP = "|"
_ESCAPES = {"%": "%25", _SEP: "%7C"}
_UNESCAPE_RE = re.compile(r"%([0-9A-Fa-f]{2})")


def _esc(s: str) -> str:
    return s.replace("%", "%25").replace(_SEP, "%7C")


def _unesc(s: str) -> str:
    # Single pass, so an escaped escape ("%2525") decodes to "%25" and not to
    # "%". Sequential str.replace calls would get that wrong.
    return _UNESCAPE_RE.sub(lambda m: chr(int(m.group(1), 16)), s)


# --- xpath steps ------------------------------------------------------------

_STEP_RE = re.compile(r"^([^\[\]]+)(?:\[(\d+)\])?$")


@lru_cache(maxsize=65536)
def split_steps(xpath: str) -> Tuple[Tuple[str, int], ...]:
    """Absolute xpath -> the address word of THEORY Def. 11.1.

    Each letter is ``(label, sibling index)``; a step written without an index
    is index 1, which is what the xpath spec means by it. Returning the index
    separately is what lets callers order siblings numerically —
    ``div[10]`` sorts after ``div[2]``, which lexicographic order gets wrong,
    and document order is the whole point of keeping the absolute form.
    """
    out: List[Tuple[str, int]] = []
    for raw in xpath.strip("/").split("/"):
        if not raw:
            continue
        m = _STEP_RE.match(raw)
        if m is None:  # a step we cannot parse stays whole, index 1
            out.append((raw, 1))
            continue
        label, idx = m.group(1), m.group(2)
        out.append((label, int(idx) if idx else 1))
    return tuple(out)


def _join_steps(steps: Sequence[Tuple[str, int]]) -> str:
    return "/" + "/".join(
        lbl if i == 1 else f"{lbl}[{i}]" for lbl, i in steps
    ) if steps else "/"


# --- generalization ---------------------------------------------------------

# Landmark elements and ARIA roles. A generalized pattern is scoped to the
# semantic region it sits in, so a nav list and a body list never share a
# pattern. Stripping *all* indices — what `core.xpath_utils.generalize_xpath`
# does — collapses them, and that collapse is observable: nav fragments
# outrank prose in retrieval because their pattern absorbs the body's.
LANDMARK_TAGS = frozenset({
    "main", "nav", "header", "footer", "aside", "article", "section", "form",
})
LANDMARK_ROLES = frozenset({
    "navigation", "main", "banner", "contentinfo", "complementary",
    "region", "search", "article", "form",
})

_INDEX_RE = re.compile(r"\[\d+\]")


def anchored_pattern(xpath: str) -> str:
    """Landmark-anchored generalized xpath — the hashing input boundary.

    Everything at and above the *deepest* landmark ancestor is kept verbatim
    with its indices; below it, indices are erased::

        /html/body/div[3]/nav[1]/ul[2]/li[7]/a[1]
          -> /html/body/div[3]/nav[1]/ul/li/a
        /html/body/div[3]/main[1]/div[2]/ul[1]/li[4]/a[1]
          -> /html/body/div[3]/main[1]/div/ul/li/a        (distinct)

    This is THEORY Def. 12.1's generalization map with a designated anchor.
    Prop. 12.4 gives what we need from it: the retained prefix is recoverable
    from the output — index-bearing letters cannot appear in the erased
    region — so nodes under different landmarks are never equivalent.
    Prop. 12.5 notes the cost: anchoring at the deepest qualifying ancestor is
    right-sequential but not sequential, i.e. it needs a right-to-left pass
    (or a lookahead), which is why this works on the whole path rather than
    streaming left to right.

    Degrades to erasing everything when the page has no landmark at all,
    which is exactly the old behaviour.
    """
    steps = split_steps(xpath)
    anchor = -1
    for i, (label, _idx) in enumerate(steps):
        base = label.split(":")[-1].lower()
        if base in LANDMARK_TAGS:
            anchor = i
    if anchor < 0:
        return _INDEX_RE.sub("", xpath)
    kept = _join_steps(steps[: anchor + 1])
    rest = [lbl for lbl, _ in steps[anchor + 1:]]
    return kept + ("/" + "/".join(rest) if rest else "")


def relative_to(xpath: str, ancestor_xpath: str) -> str:
    """The part of ``xpath`` below ``ancestor_xpath``, or ``xpath`` unchanged.

    The relative form is the other hashing input boundary: it is what makes a
    field accessor reusable across every instance of a pattern, since it drops
    the part of the path that is the instance rather than the field.
    """
    if ancestor_xpath and xpath.startswith(ancestor_xpath.rstrip("/") + "/"):
        return xpath[len(ancestor_xpath.rstrip("/")) + 1:]
    return xpath


# --- url decomposition ------------------------------------------------------


@lru_cache(maxsize=4096)
def url_steps(url: str) -> Tuple[str, ...]:
    """URL -> its trie path: origin first, then path segments, then query.

    Origin leads so that a global trie groups a crawl by site before it
    groups by page — the ordering a "url tree" implies. The query survives as
    one final segment because on search pages it is the only thing separating
    two otherwise identical paths.
    """
    parts = urlsplit(url)
    origin = f"{parts.scheme}://{parts.netloc}" if parts.netloc else url
    steps = [origin]
    steps += [seg for seg in parts.path.split("/") if seg]
    if parts.query:
        steps.append("?" + parts.query)
    return tuple(steps)


# --- the address ------------------------------------------------------------


#: The taxonomy slot carries two label sets, and that has cost five bugs.
#:
#: The SENSOR names an address by what the thing IS -- `link`, `button`,
#: `field` -- and the TAGGER by what the detection HELD -- `urls.internal`,
#: `interactive.links`. Both are legitimate; `K` in THEORY Def. 10.1 is a
#: flat label set whose only operations are equality and membership, and
#: there are simply two of them in play.
#:
#: The cost lands on every consumer, which must either handle both or
#: silently work on one path only. This session alone:
#:
#:   * `markdown._is_tag_name` deleted `Espanol`, `China`, `Europe` -- 643
#:     controls -- because "short and alphabetic" is the right test for a
#:     media value and the wrong one for a label
#:   * `href_at` is built only from sensor classes, so `target` is always
#:     empty on the tagger path; a guard reading `not target` would have
#:     added a spurious line to every anchor on every page
#:   * `text_at` accepted only `category == "text"`, so a label carried on
#:     an interactive detection was invisible to it
#:   * `_echoes_its_element` had to be written twice, in two modules
#:   * `repl._KIND_BY_TAG` records the same shape: "after the address's
#:     taxonomy slot became the render class every one of these fell through
#:     to TEXT -- so the page drew its controls and the REPL treated them as
#:     prose"
#:
#: The fix is not to rename what either side emits -- the tag is part of the
#: address key and therefore of every stored row -- but to give consumers ONE
#: vocabulary to key on. `render_class` is that: a total function onto the
#: eighteen classes `aam.RENDER_CLASS` already defines, so a rule can ask
#: what a thing IS without asking which pipeline said so.
_CANONICAL_CLASS: Dict[str, str] = {
    # -- the tagger's vocabulary: what the detection held -------------------
    "text.visible": "text",
    "text.metadata": "text",
    "text.attributes": "text",
    "interactive.inputs": "field",
    "interactive.buttons": "button",
    "interactive.links": "link",
    # A form is a container, not a control: mapping it to `button` made the
    # widget re-wrap a line the renderer had already marked up, printing
    # "( === form === )".
    "interactive.forms": "group",
    "interactive.elements": "button",
    "interactive.event_handlers": "button",
    "media.images": "image",
    "media.video": "media",
    "media.audio": "media",
    "media.assets": "media",
    "urls.internal": "link",
    "urls.external": "link",
}

#: When neither table knows the tag, its category still does. Total by
#: construction: an address always has a class, because a consumer that has
#: to ask "and what if it is none of these" is back to branching on the
#: pipeline.
_CLASS_BY_CATEGORY: Dict[str, str] = {
    "text": "text",
    "urls": "link",
    "media": "media",
    "json_data": "code",
    "interactive": "button",
}


#: A positional index in an xpath step: the `[11]` of `li[11]`.
_INDEX = re.compile(r"\[\d+\]")

@dataclass(frozen=True)
class ContentAddress:
    """One detected content unit's address. Immutable, hashable, ordered."""

    url: str
    xpath: str
    tag: str        # 'urls.external' — category.subcategory
    accessor: str   # 'srcset[1]' — detector with its intrinsic sub-path

    # -- derived forms -----------------------------------------------------
    @property
    def shape(self) -> str:
        """The xpath with its positions dropped: the template, not the instance.

        `.../ol/li[11]/article/h3` becomes `.../ol/li/article/h3`, so every
        repeat of one template -- a search result, a menu item, a paragraph
        in a run -- collapses onto one string. That is what makes it useful:
        it groups repeats, it names a template for retrieval ("every result
        row"), and it survives an inserted sibling, which shifts every index
        below it and no shape at all.

        **It is not an identity, and it must never be used as one.** The
        goal asked whether the address itself could go index-agnostic, and
        the corpus answers no. Measured over 23,654 addresses:

            distinct with indices   23,654
            distinct by shape        2,831   (88.0% fewer)
            shapes covering >1        1,290   median 5, p90 31, max 1511
            of those, covering elements with DIFFERENT content
                                      1,022   (79.2%)

        Four shapes in five cover elements that say different things --
        `/html/head/script` alone covers three unrelated script urls. An
        address is a POINTER: `enact` presses it, the REPL resolves it
        against a live DOM, the store keys chunks on it. A shape cannot
        point at either of two siblings, so it sits BESIDE the xpath and
        never replaces it.

        Derived, never stored, for the same reason `render_class` is: the
        xpath stays exactly what the pipeline emitted, so no key changes and
        no row migrates.
        """
        return _INDEX.sub("", self.xpath or "")

    @property
    def category(self) -> str:
        return self.tag.split(".", 1)[0]

    @property
    def subcategory(self) -> str:
        return self.tag.split(".", 1)[1] if "." in self.tag else ""

    @property
    def render_class(self) -> str:
        """What this address IS, in one vocabulary, whoever named it.

        The sensor already speaks it, so a sensor tag passes through; a
        tagger tag is translated; anything unknown falls back to its
        category. See `_CANONICAL_CLASS` for why this exists.

        Derived, never stored: the tag stays exactly what the pipeline
        emitted, so no key changes and no row migrates.

        **It is a projection, and it is lossy where the tagger is more
        specific than the sensor's role vocabulary.** `interactive.forms`
        becomes `group`, and so do `role=article`, `nav`, `main`, `list`,
        `table`, `region` and nine others -- the sensor simply does not
        distinguish a form from a section, because ARIA does not.

        So a consumer needing that distinction must NOT key on this.
        `repl._KIND_BY_TAG` is the live example: it maps `interactive.forms`
        to FORM, which draws `=== form ===`, and a sensor `group` to TEXT,
        because a section is not a control. Migrating it to `render_class`
        would make every `<article>` and `<nav>` a FORM widget -- a
        regression that looks exactly like an obvious cleanup.

        The rule: use `render_class` where the eighteen classes are the whole
        question, `is_control` for affordance, and the raw `tag` where a
        pipeline's extra specificity is what you need.
        """
        tag = self.tag or ""
        hit = _CANONICAL_CLASS.get(tag)
        if hit is not None:
            return hit
        if tag in _SENSOR_CLASSES:
            return tag
        return _CLASS_BY_CATEGORY.get(self.category, "text")

    #: The classes a reader can act on, of the eighteen.
    _CONTROL_CLASSES = frozenset({"link", "button", "field", "choice",
                                  "check", "slider"})

    @property
    def is_control(self) -> bool:
        """Is this address an AFFORDANCE, not merely drawn like one?

        Distinct from `render_class`, and the distinction is load-bearing.
        `render_class` says how a thing is DRAWN -- a `urls.*` value draws as
        a link, correctly, because the render turns it into `[words](target)`.
        But a url is a value the element carries, not an element a reader can
        press: `<link rel=stylesheet>` in `<head>` is a `urls.*` address and
        nothing anyone can click.

        Keying affordance on `render_class` therefore over-counts. Measured:
        it took `--reach`'s captured set from 6,447 to 7,565 over ten pages,
        the difference being head links and other url values that are not
        controls.

        So the two questions get two predicates. This one is still a
        two-vocabulary test -- the tagger says `interactive.*`, the sensor
        says `button` -- but it is that test in ONE place, which is the point:
        a consumer asks the address and never asks which pipeline spoke.
        """
        tag = self.tag or ""
        if tag.startswith("interactive"):
            return True
        return tag in self._CONTROL_CLASSES

    @property
    def detector(self) -> str:
        """The mechanism name without its sub-path (``srcset``, ``text()``)."""
        head = self.accessor
        for cut in ("[", "@", "/"):
            i = head.find(cut)
            if i > 0:
                head = head[:i]
        return head

    # Attributes whose value is a URL. The sensor names an address by what it
    # *is* (`link`, `media`, `pagination`) where the old tagger named it by
    # what it held (`urls.internal`), so "is this a link?" cannot be answered
    # from the tag any more — it is answered from the attribute the value came
    # out of, which is true on both paths.
    #: Mirrors the sensor's `URL_ATTRS` (`sensor.js`) plus the srcset forms.
    #: The lazy loaders' attributes were missing, so a WP Rocket photo
    #: (`data-lazy-src`) was held and never read as a url -- its card drew
    #: the empty stand-in from `src` (G-197, 2026-10-18).
    _URL_ATTRS = frozenset({"href", "src", "srcset", "action", "poster",
                            "data-src", "data-href", "cite", "formaction",
                            "data-lazy-src", "data-lazy-srcset", "data-srcset",
                            "data-original", "data-original-src", "data-image",
                            "longdesc"})

    @property
    def is_url(self) -> bool:
        """Whether this address's value is a URL, on either extraction path.

        Both the crawl frontier and the `LinksTo` edges hung off
        ``category == "urls"``, which only the old tagger ever produced. On
        the sensor path that silently emptied the link graph: PageRank then
        ran over containment edges alone and came out near-uniform, which is
        the exact failure `crawl` was written to fix — a ranking factor that
        contributes nothing while appearing to.
        """
        if self.category == "urls":
            return True
        return self.accessor.split("|", 1)[0].split("[", 1)[0] in self._URL_ATTRS

    @property
    def pattern(self) -> str:
        """Landmark-anchored generalized xpath."""
        return anchored_pattern(self.xpath)

    def steps(self) -> Tuple[Tuple[str, int], ...]:
        return split_steps(self.xpath)

    def path(self) -> Tuple[str, ...]:
        """The full trie path: url tree, then xpath steps, then tag, accessor.

        This is the sequence the universal trie is keyed on. Ancestry in the
        DOM is a prefix of this path (THEORY Cor. 11.3), and so is
        same-site-ness, so one trie answers both.
        """
        return (
            url_steps(self.url)
            + tuple(lbl if i == 1 else f"{lbl}[{i}]" for lbl, i in self.steps())
            + (self.tag, self.accessor)
        )

    # -- ordering ----------------------------------------------------------
    def sort_key(self) -> Tuple:
        """Document order: url path, then step-by-step with numeric indices.

        Comparing ``(label, index)`` pairs is what keeps ``div[10]`` after
        ``div[2]``. Depth breaks ties so an ancestor precedes its descendants,
        which makes an ordered walk of a sorted address list a pre-order
        traversal of the trie — no tree needs to be materialized to iterate it
        in order.
        """
        return (url_steps(self.url), self.steps(), self.tag, self.accessor)

    # -- canonical key -----------------------------------------------------
    def key(self) -> str:
        """Injective string form. ``parse(a.key()) == a`` for every ``a``.

        Computed once per address, then remembered on the instance.

        The key is the identity everything downstream is keyed on -- chunk
        anchors, the store's rows, every dict the render builds -- so it is
        asked for far more often than there are addresses to ask about:
        profiling one render measured 322,858 calls across 24 pages, roughly
        25 per address, each escaping and joining four strings. `_esc` alone
        ran 1.29 million times.

        `object.__setattr__` because the dataclass is frozen. The cache is
        not a field, so it takes no part in `__eq__`, `__hash__` or `parse`,
        and it cannot outlive the address it belongs to.
        """
        cached = self.__dict__.get("_key_cache")
        if cached is None:
            cached = _SEP.join(
                _esc(p) for p in (self.url, self.xpath, self.tag, self.accessor)
            )
            object.__setattr__(self, "_key_cache", cached)
        return cached

    @staticmethod
    def parse(key: str) -> "ContentAddress":
        parts = key.split(_SEP)
        if len(parts) != 4:
            raise ValueError(f"not an address key: {key!r}")
        url, xpath, tag, accessor = (_unesc(p) for p in parts)
        return ContentAddress(url=url, xpath=xpath, tag=tag, accessor=accessor)

    @property
    def aid(self) -> str:
        """Compact 16-hex id over the canonical key, for foreign keys.

        Derived, never authoritative: anything holding an ``aid`` can be
        checked against the address it claims to abbreviate. Sixteen hex
        digits is 64 bits — at the corpus scale (10^5 addresses) the birthday
        collision probability is under 10^-9, and a collision costs a merged
        row, not a wrong answer, because the full key is stored alongside.
        """
        return hashlib.sha1(self.key().encode("utf-8")).hexdigest()[:16]

    def __str__(self) -> str:  # readable, not parsed back
        return f"{self.url}#{self.xpath}~{self.tag}:{self.accessor}"


# --- construction from the tagger ------------------------------------------


def address_of(tag, url: str) -> ContentAddress:
    """Build the address of one :class:`~vertiscope.core.content_tagger.ContentTag`."""
    return ContentAddress(
        url=url,
        xpath=tag.xpath,
        tag=f"{tag.category}.{tag.subcategory}",
        accessor=tag.accessor,
    )


def addresses_of(tags: Iterable, url: str) -> List[ContentAddress]:
    """Address every detection, in document order, duplicates collapsed.

    Exact duplicate detections — same address *and* same value — are the
    tagger re-reporting one fact through two rules; collapsing them is
    lossless. Two different values at one address would not be, so callers
    that need to know use :func:`vertiscope.address.collisions`.
    """
    seen = set()
    out: List[ContentAddress] = []
    for t in tags:
        a = address_of(t, url)
        k = a.key()
        if k in seen:
            continue
        seen.add(k)
        out.append(a)
    out.sort(key=ContentAddress.sort_key)
    return out


def collisions(tags: Iterable, url: str) -> List[Tuple[ContentAddress, List[str]]]:
    """Addresses carrying more than one distinct value.

    The completeness-uniqueness check in executable form: a non-empty result
    means the addressing scheme is not a key on this page, and every consumer
    downstream — trie, store, dedup — is unsound for those addresses. Kept
    here rather than in the test suite so any caller can assert it on live
    input, not only on the frozen corpus.
    """
    from collections import OrderedDict

    buckets: "OrderedDict[str, Tuple[ContentAddress, List[str]]]" = OrderedDict()
    for t in tags:
        a = address_of(t, url)
        entry = buckets.setdefault(a.key(), (a, []))
        if t.value not in entry[1]:
            entry[1].append(t.value)
    return [(a, vs) for a, vs in buckets.values() if len(vs) > 1]


#: The one vocabulary, for consumers that want to enumerate it.
RENDER_CLASSES = _SENSOR_CLASSES
