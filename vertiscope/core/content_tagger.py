"""
content_tagger.py — Comprehensive DOM content detection and xpath extraction.

Given a ShadowDOM object, scans every node and every attribute value for:
  - URLs (internal, external, resource/data)
  - Media links (image, video, audio, archive) embedded as substrings
  - Human-readable text (visible, accessible, metadata)
  - Interactive elements (inputs, buttons, forms)
  - Embedded JSON (ld+json, data-* attrs, inline script blocks)

Returns categorized arrays of absolute xpaths.
"""

from __future__ import annotations

import re
import json as _json
import html
from typing import Dict, List, Set, Optional, Tuple
from dataclasses import dataclass, field

try:
	from .shadow_html_parser import ShadowDOM, ShadowNode, get_absolute_xpath
except ImportError:
	from shadow_html_parser import ShadowDOM, ShadowNode, get_absolute_xpath


# ---------------------------------------------------------------------------
# Regex patterns — compiled once, reused across all calls
# ---------------------------------------------------------------------------

# URL detection: matches anything that looks like a URL embedded as a substring
# Covers http(s), protocol-relative, absolute paths, data URIs, blob URIs
#
# The absolute-path branch requires the leading `/` not to follow a letter or
# digit. Without that, the `/` in a MIME type is a path root:
#
#     <meta http-equiv="Content-Type" content="text/html; charset=UTF-8">
#       -> urls.internal '/html;'
#
# which is a non-url in the address space, a `</html;>` line in the markdown,
# and — found this way — a junk page in the crawl frontier, since
# `canonical_url('/html;', base)` is a perfectly well-formed url that costs a
# page of a four-page budget to discover is nothing.
_URL_PATTERN = re.compile(
	r"""(?:
	     https?://[^\s"'<>(){}\[\]]+            # http or https
	   | //[^\s"'<>(){}\[\]]+                    # protocol-relative
	   | data:[a-zA-Z0-9+/\.-]+;[^\s"'<>]+      # data URI
	   | blob:[^\s"'<>]+                         # blob URI
	   | (?<![A-Za-z0-9])                        # ...not mid-word: see below
	     /[a-zA-Z0-9_.~:/?#@!$&'()*+,;=%-]+     # absolute path (starts with /)
	 )""",
	re.VERBOSE,
)

_CSS_URL_PATTERN = re.compile(r'''url\s*\(\s*['"]?([^'"\)]+)['"]?\s*\)''', re.IGNORECASE)

# Media file extensions — each category as a frozenset for O(1) lookup
_IMAGE_EXTS = frozenset({
	'.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico', '.avif',
	'.bmp', '.tiff', '.tif', '.apng', '.jfif', '.pjpeg', '.pjp',
})
_VIDEO_EXTS = frozenset({
	'.mp4', '.webm', '.ogg', '.ogv', '.mov', '.avi', '.mkv', '.flv',
	'.wmv', '.m4v', '.3gp', '.ts', '.m3u8',
})
_AUDIO_EXTS = frozenset({
	'.mp3', '.wav', '.flac', '.ogg', '.oga', '.aac', '.wma', '.opus',
	'.m4a', '.mid', '.midi',
})
_ARCHIVE_EXTS = frozenset({
	'.zip', '.rar', '.7z', '.tar', '.gz', '.bz2', '.xz', '.tar.gz',
	'.tar.bz2', '.tar.xz', '.tgz', '.cab', '.iso', '.dmg',
})

_ALL_MEDIA_EXTS = _IMAGE_EXTS | _VIDEO_EXTS | _AUDIO_EXTS | _ARCHIVE_EXTS

# Extension extraction from a URL-like string
_EXT_PATTERN = re.compile(r'\.([a-zA-Z0-9]{2,5})(?:[?#]|$)')

# Attributes known to carry human-readable text
_TEXT_ATTRS = frozenset({
	'alt', 'title', 'placeholder', 'aria-label', 'aria-labelledby',
	'aria-describedby', 'aria-description', 'aria-placeholder',
	'aria-valuetext', 'aria-roledescription', 'aria-errormessage',
	'label', 'summary', 'caption', 'abbr', 'acronym',
})

# Metadata text attributes (less visible but still content).
# ``datetime`` (ISO-8601 on <time>, <ins>, <del>) carries machine-
# parseable content that's still valuable for retrieval — without it
# the only trace of a ``<time datetime="2024-03-15">Published last
# week</time>`` in the embedding stream was the noisy surface text.
# We intentionally do NOT include ``value`` here: it's a form-input
# key on <input>/<option>/<button> and would fold CSRF tokens, hidden
# IDs, and form keys into the embedding.
_META_TEXT_ATTRS = frozenset({
	'content', 'data-tooltip', 'data-title', 'data-caption',
	'data-description', 'data-alt', 'data-label', 'data-placeholder',
	'data-text', 'data-name', 'data-value',
	'datetime',
})

# Interactive element tags
_INPUT_TAGS = frozenset({
	'input', 'textarea', 'select', 'option', 'optgroup', 'datalist',
	'output', 'progress', 'meter',
})
_BUTTON_TAGS = frozenset({'button'})
_FORM_TAGS = frozenset({'form', 'fieldset', 'legend', 'label'})

# Interactive roles (WAI-ARIA)
_INTERACTIVE_ROLES = frozenset({
	'button', 'checkbox', 'combobox', 'grid', 'gridcell', 'link',
	'listbox', 'menu', 'menubar', 'menuitem', 'menuitemcheckbox',
	'menuitemradio', 'option', 'radio', 'radiogroup', 'searchbox',
	'slider', 'spinbutton', 'switch', 'tab', 'tablist', 'textbox',
	'tree', 'treegrid', 'treeitem',
})

# Tags that signal embedded JSON or structured data
_JSON_SCRIPT_TYPES = frozenset({
	'application/ld+json', 'application/json', 'importmap',
})

# JSON-like heuristic pattern for attribute values
_JSON_HEURISTIC = re.compile(r'^\s*[\[{]')

# Attributes to skip entirely (styling, dimensions, structural, implementation)
_SKIP_ATTRS = frozenset({
	# CSS / Styling
	'style', 'class', 'width', 'height',
	# SVG drawing attributes
	'viewbox', 'xmlns', 'xmlns:xlink', 'xmlns:svg', 'version',
	'd', 'points', 'transform', 'fill', 'stroke', 'clip-path',
	'stroke-width', 'stroke-linecap', 'stroke-linejoin',
	'fill-rule', 'clip-rule', 'opacity', 'filter',
	# Structural / identity attributes (never content)
	'id', 'name', 'for', 'type', 'method', 'enctype', 'target',
	'tabindex', 'dir', 'lang', 'translate', 'slot', 'is',
	'autocomplete', 'autocorrect', 'autocapitalize', 'spellcheck',
	# ARIA state/relationship attributes (boolean/id-ref, not text)
	'aria-controls', 'aria-owns', 'aria-flowto', 'aria-activedescendant',
	'aria-expanded', 'aria-haspopup', 'aria-hidden', 'aria-disabled',
	'aria-selected', 'aria-checked', 'aria-pressed', 'aria-live',
	'aria-atomic', 'aria-relevant', 'aria-busy', 'aria-current',
	'aria-modal', 'aria-multiline', 'aria-multiselectable',
	'aria-orientation', 'aria-readonly', 'aria-required', 'aria-sort',
	'aria-invalid', 'aria-level', 'aria-colcount', 'aria-colindex',
	'aria-colspan', 'aria-rowcount', 'aria-rowindex', 'aria-rowspan',
	'aria-setsize', 'aria-posinset', 'aria-valuemin', 'aria-valuemax',
	'aria-valuenow',
	# Framework / test / automation IDs (never content)
	'data-testid', 'data-cy', 'data-qa', 'data-automation-id',
	'data-component', 'data-reactid',
})

# Tags that do not break a text block's flow.
# The HTML element vocabulary, for telling a page from a text file that
# happens to contain an angle bracket. Deliberately the *standard* names only:
# a custom element (`<bsp-header>`) never appears alone, so a document holding
# nothing but unknown tags is prose, not markup.
_HTML_TAG_NAMES = frozenset({
	"html", "head", "body", "title", "meta", "link", "base", "style",
	"script", "noscript", "template", "slot",
	"div", "span", "p", "br", "hr", "pre", "blockquote", "figure",
	"figcaption", "main", "section", "article", "aside", "nav", "header",
	"footer", "address", "details", "summary", "dialog",
	"h1", "h2", "h3", "h4", "h5", "h6", "hgroup",
	"ul", "ol", "li", "dl", "dt", "dd", "menu",
	"table", "thead", "tbody", "tfoot", "tr", "th", "td", "caption",
	"colgroup", "col",
	"form", "input", "textarea", "select", "option", "optgroup", "button",
	"label", "fieldset", "legend", "datalist", "output", "progress", "meter",
	"a", "img", "picture", "source", "svg", "canvas", "video", "audio",
	"track", "map", "area", "iframe", "embed", "object", "param",
	"em", "strong", "b", "i", "u", "s", "small", "sub", "sup", "mark",
	"code", "kbd", "samp", "var", "cite", "q", "abbr", "dfn", "time",
	"data", "bdi", "bdo", "ruby", "rt", "rp", "wbr", "ins", "del",
	"font", "center", "big", "strike", "tt", "frame", "frameset", "marquee",
})

_INLINE_TAGS = frozenset({
	"a", "abbr", "b", "bdi", "bdo", "br", "cite", "code", "data", "dfn",
	"em", "i", "kbd", "mark", "q", "rp", "rt", "ruby", "s", "samp",
	"small", "span", "strong", "sub", "sup", "time", "u", "var", "wbr",
	"img", "svg", "picture", "canvas", "video", "audio"
})

# Prefixes for attribute names to skip entirely — catches variants like
# data-testid-*, data-cy-*, data-reactid-*, etc.
_SKIP_ATTR_PREFIXES = (
	'data-testid', 'data-cy-', 'data-qa-', 'data-automation',
	'data-react', 'data-radix', 'data-state', 'data-orientation',
	'data-side', 'data-align', 'data-disabled',
	# Our own serializer's subtree digests. Without this they would be tagged
	# as content and hex strings would enter the index — and worse, the index
	# would then change on every pass for pages that had not changed at all.
	'data-vertiscope-',
)


# ---------------------------------------------------------------------------
# Data classes for tagged results
# ---------------------------------------------------------------------------

@dataclass
class ContentTag:
	"""A single piece of detected content at a specific xpath.

	``(xpath, category, subcategory, source_attr, sub)`` is intended to be a
	**key**: at most one detection per node per accessor position. THEORY
	Prop. 10.2 asserts the four-component version is already a key ("a single
	node and attribute yields at most one"), and that is false as measured —
	one accessor can carry an ordered sequence of values:

	    srcset="a.jpg 1x, b.jpg 2x"      two URLs, one attribute
	    <style>url(x); url(y)</style>    two URLs, one text node
	    <script ld+json>                 many URLs, one text node

	``sub`` restores the key by naming the position *within* the accessor.
	It is deliberately **intrinsic** — derived from the accessor's own value
	(a list index, a character offset, a JSON pointer) — never an emission
	counter. An extrinsic counter would make the address depend on detector
	execution order, so a detector refactor would silently re-key every stored
	address, and by THEORY Cor. 10.9 the ordering would leak into any output
	that exposed it. An intrinsic sub-path is re-resolvable against the source
	DOM by anyone holding the address, which is what makes DOM-free dedup and
	stable graph keys possible.
	"""
	xpath: str
	category: str # 'url', 'media', 'text', 'interactive', 'json'
	subcategory: str # e.g. 'image', 'accessible', 'input', 'ld_json'
	value: str # the extracted value
	source_attr: str # which attribute it came from ('' for text nodes)
	sub: str = '' # position within the accessor; '' when the accessor holds one value

	@property
	def accessor(self) -> str:
		"""The firing detection mechanism, sub-variable included.

		``srcset`` + ``[1]`` -> ``srcset[1]``; ``text()`` + ``@412`` ->
		``text()@412``; ``ld_json:url`` + ``/itemListElement/3/url`` ->
		``ld_json:url/itemListElement/3/url``. Empty ``source_attr`` (a text
		node) renders as ``text()`` so every detection names a mechanism.
		"""
		return (self.source_attr or 'text()') + self.sub


@dataclass
class TaggedContent:
	"""Complete categorized extraction result for a DOM snapshot."""
	urls: Dict[str, List[str]] = field(default_factory=lambda: {
		'internal': [], 'external': [], 'resource': [],
	})
	media: Dict[str, List[str]] = field(default_factory=lambda: {
		'images': [], 'video': [], 'audio': [], 'archives': [],
	})
	text: Dict[str, List[str]] = field(default_factory=lambda: {
		'visible': [], 'accessible': [], 'metadata': [],
	})
	interactive: Dict[str, List[str]] = field(default_factory=lambda: {
		'inputs': [], 'buttons': [], 'links': [], 'forms': [],
		'event_handlers': [],
	})
	json_data: Dict[str, List[str]] = field(default_factory=lambda: {
		'ld_json': [], 'data_attrs': [], 'inline': [],
	})

	# Flat list of all individual tags for detailed access
	all_tags: List[ContentTag] = field(default_factory=list)

	# xpath -> the position at which the walk reached that node.
	#
	# An xpath index counts siblings of the same label, so it cannot say
	# whether <head> or <body> comes first. This does: the walk enqueues a
	# parent's children contiguously and in document order, so ordering any
	# parent's children by this counter reproduces the document's own order.
	#
	# It is recorded per *node visited*, not per detection. Detections are
	# sparse — a div with no attributes and no direct text yields none — so
	# ordering by detection arrival mis-sorts exactly the elements that only
	# contain other elements, which on real pages is most of them.
	doc_pos: Dict[str, int] = field(default_factory=dict)

	def all_content_xpaths(self) -> Set[str]:
		"""Return the union of all xpaths across every category."""
		xpaths = set()
		for group in (self.urls, self.media, self.text,
			self.interactive, self.json_data):
			for arr in group.values():
				xpaths.update(arr)
		return xpaths


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def _classify_url(url: str) -> str:
	"""Classify a URL as internal, external, or resource."""
	stripped = url.strip()
	if stripped.startswith('data:') or stripped.startswith('blob:'):
		return 'resource'
	if stripped.startswith('//') or stripped.startswith('http'):
		return 'external'
	# Absolute path — treat as internal
	return 'internal'


def _classify_media(url: str) -> Optional[str]:
	"""Return media subcategory if URL ends with a known media extension."""
	if url.startswith('data:image/'):
		return 'images'
	if url.startswith('data:video/'):
		return 'video'
	if url.startswith('data:audio/'):
		return 'audio'

	# Strip query/fragment and check extension
	clean = url.split('?')[0].split('#')[0].lower()
	m = _EXT_PATTERN.search(clean)
	if not m:
		return None
	ext = '.' + m.group(1)
	if ext in _IMAGE_EXTS:
		return 'images'
	if ext in _VIDEO_EXTS:
		return 'video'
	if ext in _AUDIO_EXTS:
		return 'audio'
	if ext in _ARCHIVE_EXTS:
		return 'archives'
	return None


def _extract_urls_with_offsets(value: str) -> List[Tuple[str, int]]:
	"""Extract URL-like substrings paired with their character offset.

	The offset is the intrinsic sub-address (see :class:`ContentTag`): several
	URLs can share one accessor, and the offset is what tells them apart in a
	way the holder of the address can re-resolve without replaying the scan.
	``_URL_PATTERN`` uses only non-capturing groups, so ``m.group(0)`` is the
	same string ``findall`` used to return.
	"""
	valid: List[Tuple[str, int]] = []
	for m in _URL_PATTERN.finditer(value):
		u = m.group(0)
		if u.startswith('/') and not u.startswith('//'):
			# Reject extremely short generic paths unless it is the root
			if len(u) < 2 and u != '/':
				continue
			# Reject common non-content developer paths that cause massive false positives
			if any(junk in u.lower() for junk in ['/track', '/log', '/ping', '/chunk', '/static/', '/wp-json/', '/api/']):
				continue
		valid.append((u, m.start()))
	return valid


def _extract_urls_from_value(value: str) -> List[str]:
	"""Extract all URL-like substrings from an arbitrary attribute value."""
	return [u for u, _ in _extract_urls_with_offsets(value)]


def _ptr_escape(token: str) -> str:
	"""RFC 6901 JSON-pointer token escape, so a pointer parses unambiguously.

	Without it a key containing ``/`` would forge an extra pointer segment and
	two different fields could produce the same sub-address.
	"""
	return token.replace('~', '~0').replace('/', '~1')


def _looks_like_json(value: str) -> bool:
	"""Heuristic check if a string value is likely embedded JSON."""
	if len(value) < 20 or len(value) > 5000: # Ignore tiny IDs and block massive strings from hanging the parser
		return False
	if not _JSON_HEURISTIC.match(value):
		return False
	try:
		_json.loads(value)
		return True
	except (ValueError, TypeError):
		return False

def _has_real_text(text: str) -> bool:
	"""Require at least 1 alphanumeric char to filter out icon fonts and stray punctuation."""
	return any(c.isalnum() for c in text)


# Translation table that strips zero-width / NBSP noise out of visible text.
# Hoisted out of the per-node hot path; ``str.maketrans`` was being rebuilt
# 3× per node (text node, leaf element text, mixed-children text) and on a
# 20K-node page that's 60K table allocations for an unchanging table.
# Zero-width characters are deleted; U+00A0 is *not* one of them.
#
# A non-breaking space is a space \u2014 it is what `&nbsp;` produces, and it is
# everywhere in real markup. Deleting it fuses the words on either side:
# letterboxd.com's `Upgrade to remove\xa0ads` came out as
# `Upgrade to removeads`, which is not merely untidy \u2014 "ads" stops being a
# term, so the line cannot be found by searching for it, and the page's word
# recall reads 99.6% instead of 100%.
#
# The other five are genuinely invisible (zero-width space, non-joiner,
# joiner, BOM) and deleting them is right. NBSP maps to a real space, after
# which the caller's `" ".join(value.split())` collapses runs as usual.
_INVISIBLE_TRANS = str.maketrans({
	'\u200b': None, '\u200c': None, '\u200d': None, '\ufeff': None,
	'\u00a0': ' ',
})

# URL-attribute whitelist — used when extracting URLs from ``href``/``src``-
# style attributes. Frozenset gives O(1) ``in`` checks vs. the previous
# ~13-element tuple ``in`` (linear scan).
_URL_BEARING_ATTRS = frozenset({
	'href', 'src', 'data-src', 'data-lazy-src', 'action', 'formaction',
	'poster', 'data-original', 'data-original-src', 'data-image',
	'data', 'cite', 'longdesc',
})

# Attributes whose values are NEVER worth a generic URL regex sweep —
# they're booleans, ARIA hooks, or pure-text. Letting the URL regex chew
# on every ``aria-label`` / ``placeholder`` / ``alt`` value showed up as
# a measurable hotspot on real pages (avg 5+ attrs/node × 20K nodes).
_NON_URL_ATTR_PREFIXES = ('aria-',)
_NON_URL_ATTRS = frozenset({
	'class', 'id', 'name', 'type', 'role', 'title', 'alt', 'placeholder',
	'value', 'label', 'lang', 'dir', 'tabindex', 'maxlength', 'minlength',
	'min', 'max', 'step', 'pattern', 'autocomplete', 'autocapitalize',
	'autocorrect', 'spellcheck', 'inputmode', 'enterkeyhint', 'rows',
	'cols', 'wrap', 'size', 'multiple', 'readonly', 'required', 'disabled',
	'checked', 'selected', 'hidden', 'draggable', 'contenteditable',
	'translate', 'colspan', 'rowspan', 'headers', 'scope', 'abbr',
	'datetime', 'pubdate', 'reversed', 'start',
})


# ---------------------------------------------------------------------------
# Core tagger
# ---------------------------------------------------------------------------

def _own_label(node) -> str:
	"""An element's own words, WITHOUT its tail.

	The tail belongs to the parent's prose, not to this element:
	`get_text(recursive=True)` walks `iter_all()`, which yields self
	first and appends each node's text AND tail, so using it here
	labelled `<a href=/rates>retreat rates</a> and ...` as
	"retreat rates and", swallowing the clause after the link.
	"""
	parts = [node.text or ""]
	if hasattr(node, "iter_descendants"):
		for desc in node.iter_descendants():
			if desc.text:
				parts.append(desc.text)
			if desc.tail:
				parts.append(desc.tail)
	out = " ".join(p.strip() for p in parts if p and p.strip())
	return out.translate(_INVISIBLE_TRANS).strip()


#: What a page calls a control when the control has no words of its own.
#: `placeholder` first: it is what a reader sees in an empty field.
_NAME_ATTRS = ("placeholder", "aria-label", "title", "alt", "value")

#: Controls whose descendants are their OPTIONS, not their words.
#:
#: `_own_label` walks every descendant, which is right for a button wrapping
#: a span and wrong here: a `<select>` holds one option per choice, each of
#: which this tagger already emits as its own `interactive.inputs` detection
#: at its own xpath. Reading the descendants as the select's label therefore
#: records the whole option list a second time, as one value.
#:
#: Measured on the frozen corpus: data.gov.uk's publisher filter has 1,511
#: options, and its select's own value came out at 43,542 characters --
#: 7,745 tokens against a 512-token window, fifteen times over, in a chunk
#: whose single line no reader can navigate and whose content is already
#: covered by the 1,509 option chunks beside it. A user found it by opening
#: the note and called it under-chunking, which is exactly what it is.
#:
#: The browser is the authority on what these draw. `select.value` is the
#: SELECTED option, and a collapsed select paints that one label -- the rule
#: `analytics/groundtruth.py` already states ("a <select> draws the one value
#: it holds"). This makes the tagger agree with it.
_LISTBOX_TAGS = frozenset({"select", "datalist", "optgroup"})


def _chosen_option(node) -> str:
    """The one option a collapsed listbox shows.

    Only an option that claims `selected`. Falling back to the first option
    was tried and is a fabrication: data.gov.uk's publisher filter opens on
    an empty `<option value="">`, so the box a reader sees is blank, and
    naming it after the first real entry would report a filter as applied
    when it is not. "" instead, and `_own_name` falls through to the naming
    attributes -- the control stays detected, and the `<label for=publisher>`
    beside it is tagged separately and still says `Publisher`.
    """
    try:
        options = [d for d in node.iter_descendants()
                   if (d.tag or "").lower() == "option"]
    except Exception:  # noqa: BLE001
        return ""
    for option in options:
        try:
            chosen = option.has_attr("selected")
        except Exception:  # noqa: BLE001
            chosen = False
        if not chosen:
            continue
        return _own_label(option) or (option.get_attr("value") or "").strip()
    return ""


def _own_name(node, tag: str) -> str:
	"""A control's label: its own words, else what an attribute calls it.

	An `<input>` is void -- it has no text to fold -- so `_own_label`
	returns nothing and the detection fell back to the tag, drawing
	`[ ] input` on a page whose field says `Search`. The placeholder,
	`aria-label` or `title` is what the page shows there.

	The tag is the last resort and stays meaningful: `[ ] input` for a
	field the page genuinely leaves unnamed.

	A listbox is the exception and takes `_chosen_option` instead: its
	descendants are its options, each already detected separately, so
	`_own_label` would record the entire list as one value. See
	`_LISTBOX_TAGS`.
	"""
	own = (_chosen_option(node) if tag in _LISTBOX_TAGS
	       else _own_label(node))
	if own:
		return own
	for attr in _NAME_ATTRS:
		try:
			value = (node.get_attr(attr) or "").strip()
		except Exception:  # noqa: BLE001
			continue
		if value:
			return value.translate(_INVISIBLE_TRANS).strip()
	return tag


class ContentTagger:
	"""
	Walks a ShadowDOM tree and extracts all contentful xpaths.
	
	Usage:
	    dom = ShadowDOM(html_string)
	    tagger = ContentTagger(dom)
	    result = tagger.tag()
	    # result.urls['internal'] → list of xpaths
	    # result.all_content_xpaths() → set of all xpaths with content
	"""

	# The serializer stamps this on every element it emits; it is machinery,
	# not content, and tagging it would put hex digests into the index.
	HASH_ATTR = 'data-vertiscope-hash'

	def __init__(self, dom: ShadowDOM, mask: Optional[Set[int]] = None,
		reuse: Optional[Dict[Tuple[str, str], List[ContentTag]]] = None):
		"""``reuse`` maps ``(xpath, subtree hash)`` to that subtree's detections.

		Supplying it makes tagging incremental: a subtree whose hash and
		position both match is not re-examined, and its cached detections are
		spliced in instead. Keyed on the pair rather than the hash alone
		because a subtree that *moved* has the same content and different
		addresses — reusing on content alone would emit detections pointing at
		where the content used to be.

		The walk itself still visits every node, cheaply, so that ``doc_pos``
		stays complete: sibling order is not recoverable from the addresses
		(THEORY Prop. 11.3.1), so skipping the visits would silently degrade
		the trie's ordering to its fallback.
		"""
		self.dom = dom
		self._result: Optional[TaggedContent] = None
		self._seen_xpaths: Set[str] = set()
		self.mask = mask or set()
		self._skip_text_ids: Set[int] = set()
		self.reuse = reuse or {}
		self._reused_ids: Set[int] = set()
		self.reuse_stats = {"subtrees": 0, "nodes_skipped": 0, "tags_reused": 0}

	def tag(self) -> TaggedContent:
		"""Run the full content extraction pass. Results are cached."""
		if self._result is not None:
			return self._result

		self._result = TaggedContent()
		self._seen_xpaths = set()
		self._plan_reuse()

		if not self._looks_like_markup():
			# Checked *before* the walk, not after. Running the walk first and
			# appending plain text to its results kept the accidental
			# elements too, so an RFC yielded detections at `/douglas` and
			# `/douglas/http:` beside the real ones. Those are artifacts of
			# parsing prose as markup; there is nothing to merge with.
			self._tag_plain_text()
			return self._result

		for node in self.dom.iter_all():
			if id(node) in self.mask:
				continue
			self._process_node(node)

		return self._result

	def _looks_like_markup(self) -> bool:
		"""Whether this document contains any recognised HTML element.

		Not "any element": `html.parser` happily produces one from any angle
		bracket, so RFC 8259's prose — `<Douglas Crockford>`, `<http://…>` —
		parsed as elements named `douglas` and `http:`, and 28KB of text came
		out as 18 lines of accidental markup. Testing the tag *names* against
		the real HTML vocabulary separates a page from a text file that
		mentions a bracket.
		"""
		for node in self.dom.iter_elements():
			if (node.tag or '').lower() in _HTML_TAG_NAMES:
				return True
		return False

	# Paragraphs of a text/plain document: a run of non-blank lines.
	_PARAGRAPH_SPLIT = re.compile(r'\n[ \t]*\n')

	def _tag_plain_text(self) -> None:
		"""A document with no markup at all still has content.

		`text/plain` is served on the web — the corpus carries two RFCs as
		`.txt` — and the walk above only visits *elements*, so a document with
		none emitted nothing at all while holding the whole text on the root.
		Measured: RFC 791, **1,020 reference words, zero lines out**. RFC 8259
		did marginally worse than nothing, producing 18 "elements" named
		`douglas`, `iesg` and `http:` because its prose contains angle
		brackets, so the output depended on whether the text happened to look
		like markup.

		The xpath is `/html/body/pre`, which is not an invention: browsers wrap
		a `text/plain` response in exactly that, so the address resolves in a
		live scan the same way it resolves here. Paragraphs are separated by
		blank lines and carry their character offset as the intrinsic
		sub-address — the same `@<offset>` spelling a stylesheet's several urls
		use — so a paragraph is individually addressable rather than the whole
		file being one indivisible chunk.
		"""
		# The *source*, not the parsed root. `html.parser` has already
		# swallowed any angle-bracketed prose as a tag by the time a tree
		# exists — `<Douglas Crockford>` in an RFC's byline is not markup, and
		# reading the tree here recovered "See for the grammar, and for the
		# process", with the missing spans and the order both wrong.
		raw = getattr(self.dom, 'source', None) or (self.dom.root.text or '')
		text = raw.strip()
		if not text or not _has_real_text(text):
			return

		xpath = '/html/body/pre'
		offset = 0
		for part in self._PARAGRAPH_SPLIT.split(raw):
			start = raw.find(part, offset)
			offset = (start + len(part)) if start >= 0 else offset
			cleaned = ' '.join(part.split()).translate(_INVISIBLE_TRANS).strip()
			if cleaned and _has_real_text(cleaned):
				self._add('text', 'visible', xpath, cleaned, 'text()',
					f'@{max(start, 0)}')

	def _plan_reuse(self) -> None:
		"""Find subtrees whose detections can be taken from the last pass.

		One pass over the tree, top-down: a node whose ``(xpath, hash)`` is
		known is a reuse root, its whole subtree is marked, and the search
		does not descend into it — an unchanged subtree cannot contain a
		changed one, since the hash covers everything below it.
		"""
		if not self.reuse:
			return

		stack = [self.dom.root]
		while stack:
			node = stack.pop()
			tag = (node.tag or '').lower()
			# A non-element node carries no hash, but its children do — the
			# root is a `#document`, so returning here instead of descending
			# emptied the stack immediately and reuse never fired at all. The
			# only symptom was that nothing got faster.
			if not tag.startswith('#'):
				digest = (node.get_attr(self.HASH_ATTR)
					if hasattr(node, 'get_attr') else None)
				cached = (self.reuse.get((get_absolute_xpath(node), digest))
					if digest else None)
				if cached is not None:
					self._mark_subtree(node)
					self._result.all_tags.extend(cached)
					for entry in cached:
						self._register_bucket(entry)
					self.reuse_stats["subtrees"] += 1
					self.reuse_stats["tags_reused"] += len(cached)
					continue
			stack.extend(node.get_children(include_shadow=True))

	def _mark_subtree(self, node) -> None:
		"""Record a node and everything under it as already accounted for."""
		stack = [node]
		while stack:
			current = stack.pop()
			self._reused_ids.add(id(current))
			self.reuse_stats["nodes_skipped"] += 1
			stack.extend(current.get_children(include_shadow=True))

	def reuse_cache(self) -> Dict[Tuple[str, str], List[ContentTag]]:
		"""Build the map the *next* pass should be given.

		Every hashed element becomes an entry holding the detections of its
		whole subtree, so the next pass can stop at the highest node that
		still matches. Entries overlap by construction — a detection appears
		in its own element's entry and in every ancestor's — which is what
		makes the top-down search in :meth:`_plan_reuse` able to reuse a large
		subtree in one step instead of thousands of small ones.
		"""
		result = self.tag()
		by_xpath: Dict[str, List[ContentTag]] = {}
		for entry in result.all_tags:
			by_xpath.setdefault(entry.xpath, []).append(entry)

		cache: Dict[Tuple[str, str], List[ContentTag]] = {}

		# Pre-order first, then accumulate in reverse. Reversing a pre-order
		# visits every child before its parent, which is what the accumulation
		# needs, and does it without recursion — real pages nest deeply enough
		# (wrapped React trees, nested tables) to reach CPython's limit, and a
		# cache that silently gives up on the deepest pages is worse than none.
		#
		# The root is not skipped for being a `#document`: an earlier version
		# returned at the first non-element node, which is the root, so the
		# walk never descended and the cache came out empty — reuse then never
		# fired, and the only symptom was that nothing got faster.
		order = []
		stack = [self.dom.root]
		while stack:
			node = stack.pop()
			order.append(node)
			stack.extend(node.get_children(include_shadow=True))

		gathered_by_id: Dict[int, List[ContentTag]] = {}
		for node in reversed(order):
			tag = (node.tag or '').lower()
			gathered: List[ContentTag] = []
			if not tag.startswith('#'):
				gathered = list(by_xpath.get(get_absolute_xpath(node), ()))
			for child in node.get_children(include_shadow=True):
				gathered.extend(gathered_by_id.pop(id(child), ()))
			gathered_by_id[id(node)] = gathered
			if tag.startswith('#'):
				continue
			digest = node.get_attr(self.HASH_ATTR) if hasattr(node, 'get_attr') else None
			if digest:
				cache[(get_absolute_xpath(node), digest)] = gathered
		return cache

	def _register_bucket(self, tag: ContentTag) -> None:
		"""Put a reused detection back in its category bucket."""
		self._seen_xpaths.add(tag.xpath)
		group = getattr(self._result, tag.category, None)
		if isinstance(group, dict):
			arr = group.get(tag.subcategory)
			if arr is not None and tag.xpath not in arr:
				arr.append(tag.xpath)

	def _process_node(self, node: ShadowNode) -> None:
		"""Classify a single node and all its attribute values."""
		tag = node.tag.lower() if node.tag else ''

		# Skip non-structural nodes
		if tag.startswith('#') and tag not in ('#text', '#comment'):
			return

		xpath = get_absolute_xpath(node)

		# Record the visit position before any early return, so elements that
		# yield no detection of their own still order their descendants. A
		# #text node shares its parent's xpath, so setdefault keeps the
		# element's own (earlier) position rather than overwriting it.
		self._result.doc_pos.setdefault(xpath, len(self._result.doc_pos))

		# An unchanged subtree's detections were spliced in by _plan_reuse.
		# The visit still happened — the line above — because sibling order is
		# not recoverable from the addresses, so skipping it would degrade the
		# trie's ordering. What is skipped is the detection work: the
		# attribute sweep, the URL regexes and the text extraction, which is
		# where the time goes.
		if id(node) in self._reused_ids:
			return

		# --- 1. Visible text (text nodes) ---
		# DOMAIN_MODEL §4.1: all human-readable text content.
		# Filter: strip whitespace + zero-width chars, require ≥1 alphanumeric.
		if tag == '#text':
			if id(node) not in self._skip_text_ids:
				text_parts = []
				if node.text and node.text.strip(): text_parts.append(node.text.strip())
				if node.tail and node.tail.strip(): text_parts.append(node.tail.strip())
				text = " ".join(text_parts).translate(_INVISIBLE_TRANS).strip()
				if text and _has_real_text(text):
					self._add('text', 'visible', xpath, text, '')
			return

		# --- 2. Interactive elements ---
		# DOMAIN_MODEL §4.1: inputs, textareas, selects, buttons, <a>,
		# forms, role-based, contenteditable, and event-handler elements.
		is_interactive = node.get_attr('data-wfh-interactive') == 'true'
		if is_interactive or tag in _INPUT_TAGS or tag in _BUTTON_TAGS or tag == 'a' or tag in _FORM_TAGS:
			if tag in _INPUT_TAGS:
				self._add('interactive', 'inputs', xpath,
					_own_name(node, tag), '')
			elif tag in _BUTTON_TAGS:
				# The button's own words, for the same reason as the
				# anchor below: `_render_unit` draws `( shown )` where
				# `shown = text_at_node or value`, so a button whose text
				# was folded into an all-inline parent fell back to the
				# tag and drew `( button )` on a page that says `Menu`.
				# A button with genuinely no words still yields the tag,
				# which is what `( button )` should mean.
				self._add('interactive', 'buttons', xpath,
					_own_name(node, tag), '')
			elif tag == 'a':
				# The link's own words, not the string 'a'.
				#
				# This detection recorded the TAG NAME as its value, because
				# for a control the element is the finding. But an anchor
				# inside all-inline prose has its words folded into the
				# paragraph's single text unit and skipped here, so nothing
				# downstream could say what the link was called: the render
				# drew `</rates>` and the REPL named links by their targets.
				#
				# Carrying the label on the detection that already exists
				# adds NO detection. `an inline-only subtree is still one
				# detection` counts TEXT units, and this is the interactive
				# one, emitted for this element either way.
				self._add('interactive', 'links', xpath,
					_own_label(node) or tag, '')
			elif tag in _FORM_TAGS:
				self._add('interactive', 'forms', xpath, tag, '')
			else:
				self._add('interactive', 'elements', xpath, tag, 'data-wfh-interactive')

		# Check role attribute for interactive
		role = (node.get_attr('role') or '').lower()
		if role in _INTERACTIVE_ROLES:
			subcat = 'buttons' if role == 'button' else 'inputs'
			self._add('interactive', subcat, xpath, f'{tag}[role={role}]', 'role')

		# contenteditable
		if node.get_attr('contenteditable') in ('true', ''):
			self._add('interactive', 'inputs', xpath, f'{tag}[contenteditable]',
				'contenteditable')

		# Event handler attributes (onclick, onsubmit, etc.). Iterate the
		# underlying dict directly — ``get_all_attrs`` returns a fresh copy
		# each call, and on a 24k-node page this hot loop was copying the
		# attribute dict twice per node for a pure read.
		for attr_name in node.attributes:
			if attr_name.lower().startswith('on') and len(attr_name) > 2:
				self._add('interactive', 'event_handlers', xpath,
					f'{tag}[{attr_name}]', attr_name)
				break # One event handler is enough to mark interactive

		# --- 2.5 Media elements ---
		is_media = node.get_attr('data-wfh-media') == 'true'
		if is_media or tag in ('img', 'picture', 'svg', 'canvas', 'video', 'source', 'track', 'audio'):
			if tag in ('img', 'picture', 'svg', 'canvas'):
				self._add('media', 'images', xpath, tag, '')
			elif tag in ('video', 'source', 'track'):
				self._add('media', 'video', xpath, tag, '')
			elif tag == 'audio':
				self._add('media', 'audio', xpath, tag, '')
			else:
				self._add('media', 'assets', xpath, tag, 'data-wfh-media')
		elif tag == 'input':
			# ``<input type="image" src="...">`` is an image-button submit;
			# the ``src`` attribute carries a real image resource URL,
			# same semantics as ``<img>``. Without this branch, the
			# element was only tagged interactive so its image never
			# reached the chunker's media buckets or the frontend's
			# billboard spawner. All other input types (text, checkbox,
			# submit, hidden, ...) remain purely interactive.
			input_type = (node.get_attr('type') or '').lower().strip()
			if input_type == 'image':
				self._add('media', 'images', xpath, tag, '')

		# --- 2.6 <style> blocks: pull out background-image URLs ---
		# Inline ``style="..."`` is already scanned further down via the
		# generic attribute pass, but ``<style>...</style>`` children
		# are CDATA that the HTMLParser hands us as ``.text`` on the
		# style node. Without this pass, stylesheet-declared images
		# (e.g. ``body { background: url(bg.jpg); }``) never enter the
		# media tag stream and the chunker / billboard spawner can't
		# surface them.
		if tag == 'style' and node.text:
			style_text = html.unescape(node.text)
			# finditer, not findall: the match offset is the intrinsic
			# sub-address distinguishing several urls in one stylesheet.
			for m in _CSS_URL_PATTERN.finditer(style_text):
				u = (m.group(1) if m.groups() else m.group(0)).strip()
				if not u:
					continue
				at = f'@{m.start()}'
				url_class = _classify_url(u)
				self._add('urls', url_class, xpath, u[:500], 'text()', at)
				media_cat = _classify_media(u)
				if media_cat:
					self._add('media', media_cat, xpath, u[:500], 'text()', at)

		# --- 3. Embedded JSON (ld+json scripts) ---
		if tag == 'script':
			script_type = (node.get_attr('type') or '').lower().strip()
			if script_type in _JSON_SCRIPT_TYPES:
				self._add('json_data', 'ld_json', xpath,
					script_type, 'type')

				# Full structured pass: parse the payload (JSON-LD often
				# contains VideoObject / ImageObject / Product schemas
				# with thumbnailUrl / contentUrl / embedUrl / image /
				# logo fields that drive SEO previews). We walk the
				# parsed tree and emit one tag per text field and one
				# per URL-bearing field so the chunker and renderer see
				# them individually instead of a single opaque blob.
				if node.text:
					self._scan_json_ld_payload(node.text, xpath)

					# Even when JSON parsing fails (malformed payload),
					# still run the flat-regex URL sweep so nothing that
					# looks like a media URL slips through.
					for url, off in _extract_urls_with_offsets(node.text):
						at = f'@{off}'
						url_class = _classify_url(url)
						self._add('urls', url_class, xpath, url[:500], 'text()', at)
						media_cat = _classify_media(url)
						if media_cat:
							self._add('media', media_cat, xpath, url[:500], 'text()', at)
				return # Don't scan script contents for URLs etc.

		# --- 4. Scan ALL attribute values ---
		# Iterate ``node.attributes`` directly to avoid the per-node dict
		# copy inside ``get_all_attrs``.
		for attr_name, attr_value in node.attributes.items():
			if not isinstance(attr_value, str) or not attr_value.strip():
				continue

			# Avoid blocking the main thread with massive regex searches on base64 images or inline SVGs
			if len(attr_value) > 2000:
				continue

			attr_lower = attr_name.lower()

			# Special check for inline CSS background images
			if attr_lower == 'style':
				style_val = html.unescape(attr_value)
				for m in _CSS_URL_PATTERN.finditer(style_val):
					u = (m.group(1) if m.groups() else m.group(0)).strip()
					if not u: continue
					at = f'@{m.start()}'
					url_class = _classify_url(u)
					self._add('urls', url_class, xpath, u[:500], 'style', at)
					media_cat = _classify_media(u)
					if media_cat:
						self._add('media', media_cat, xpath, u[:500], 'style', at)

			# A table cell's SPAN is layout the markdown table needs (`D-5`):
			# which column a cell under a rowspan fills. Above 1 only -- a span
			# of one says nothing. Ahead of `_SKIP_ATTRS`, which drops it.
			if tag in ('td', 'th') and attr_lower in ('rowspan', 'colspan'):
				v = attr_value.strip()
				if v.isdigit() and int(v) > 1:
					self._add('text', 'metadata', xpath, str(int(v)), attr_lower)
				continue

			if attr_lower in _SKIP_ATTRS:
				continue
			# Prefix-based skip for framework/test/state attrs. ``str.startswith``
			# accepts a tuple of prefixes natively at C-speed — faster than a
			# Python-level ``any(...)`` genexpr over the same tuple.
			if attr_lower.startswith(_SKIP_ATTR_PREFIXES):
				continue

			val = attr_value.strip()

			# 4a. Text attributes (accessible, metadata)
			# DOMAIN_MODEL §4.1: "The full set of 20+ text-bearing
			# attributes tracked comprehensively." No length threshold
			# beyond non-empty + has alphanumeric.
			if attr_lower in _TEXT_ATTRS and val and _has_real_text(val):
				self._add('text', 'accessible', xpath, val, attr_name)
			elif attr_lower in _META_TEXT_ATTRS and val and _has_real_text(val):
				self._add('text', 'metadata', xpath, val, attr_name)

			# 4b. JSON embedded in data-* attributes
			if attr_lower.startswith('data-') and _looks_like_json(val):
				self._add('json_data', 'data_attrs', xpath, val, attr_name)
				# We do not `continue` here because embedded JSON often contains
				# valuable CDN image URLs and deep links that we want to extract!

			# 4c. URL extraction
			# ``data`` is <object>'s resource URL (legacy Flash/PDF
			# embed, also used for modern <object type="image/svg+xml"
			# data="...">). ``cite`` points at the source of a quote on
			# <blockquote> and <q>. ``longdesc`` is the long-description
			# URL for <img>/<iframe> (still valid HTML4 and occasionally
			# used by archive.org snapshots). Without these three
			# spellings, those URLs only surfaced if they happened to
			# match the generic URL regex — which missed relative paths
			# that don't start with ``/``.
			# (url, sub) pairs. ``sub`` is empty when the attribute holds
			# exactly one URL and names the position within it otherwise —
			# a candidate index for srcset, a character offset for the
			# regex sweep. See ContentTag for why it must be intrinsic.
			found_urls: List[Tuple[str, str]] = []
			if attr_lower in _URL_BEARING_ATTRS:
				if not val.lower().startswith(('javascript:', 'mailto:', 'tel:')):
					# ``data`` is only a URL on <object>; on other
					# elements it's rarely a URL and often a text-like
					# value. Gate by tag so we don't mis-tag generic
					# ``data`` attributes as URLs.
					if attr_lower == 'data' and tag != 'object':
						pass
					else:
						found_urls = [(val, '')]
			elif attr_lower == 'srcset':
				# One attribute, an ordered candidate list. The index is
				# part of the document, so it is a legitimate sub-address.
				found_urls = [
					(p.strip().split()[0], f'[{i}]')
					for i, p in enumerate(val.split(','))
					if p.strip()
				]
			elif (
				attr_lower in _NON_URL_ATTRS
				or attr_lower.startswith(_NON_URL_ATTR_PREFIXES)
			):
				# Skip the generic regex sweep for attributes that
				# structurally never carry URLs (ARIA hooks, booleans,
				# size/length/index attributes, etc.). On a real-world
				# page the regex sweep dominated content_tag — rejecting
				# obviously-non-URL attributes by name first lets the
				# remaining catch-all path stay focused on data-* and
				# other extension attrs that occasionally hide URLs.
				pass
			else:
				found_urls = [
					(u, f'@{off}') for u, off in _extract_urls_with_offsets(val)
				]

			# A one-element sweep result needs no sub-address: the accessor
			# already determines it. Keeping it empty means the common case
			# produces the same address it did before this change.
			if len(found_urls) == 1:
				found_urls = [(found_urls[0][0], '')]

			for url, sub in found_urls:
				url_class = _classify_url(url)
				self._add('urls', url_class, xpath, url[:500], attr_name, sub)

				# 4d. Media classification from URL extension
				media_cat = _classify_media(url)
				if media_cat:
					self._add('media', media_cat, xpath, url[:500], attr_name, sub)

		# --- 5. Element-level text (direct .text on element) ---
		# DOMAIN_MODEL §4.1: "All human-readable text content collected
		# from direct text nodes (visible content)."
		# Filter: strip whitespace + zero-width chars, require ≥1 alphanumeric.
		# No tag-dependent length thresholds per the spec.
		if tag not in ('script', 'style') and id(node) not in self._skip_text_ids:
			# Through inline children, not just across the direct ones. The
			# whole-card-is-a-link pattern —
			#
			#     <a><div class="card"><h2>Server Fault</h2><p>…</p></div></a>
			#
			# is an *inline* element wrapping block content, so looking one
			# level down saw only `<a>`, judged the subtree text-like, and
			# swallowed the card whole: 189 headings on stackexchange.com/sites
			# became 6 rendered heading lines, and the same on every news site
			# built from cards (BBC 12.5% heading recall, Guardian 18.8%). The
			# words survived — recall stayed at 98% — but the structure did
			# not, and structure is what makes the markdown navigable.
			#
			# Descends only through inline elements: once a block child is
			# found the answer is yes, and a block subtree is somebody else's
			# problem to walk.
			has_block_children = False
			stack = list(node.get_children(include_shadow=True)) if hasattr(node, 'get_children') else list(getattr(node, 'children', []))
			while stack:
				child = stack.pop()
				ctag = child.tag.lower() if child.tag else ''
				if not ctag or ctag.startswith('#'):
					continue
				if ctag not in _INLINE_TAGS:
					has_block_children = True
					break
				grand = child.get_children(include_shadow=True) if hasattr(child, 'get_children') else getattr(child, 'children', [])
				stack.extend(grand)

			if not has_block_children:
				text_parts = []
				# `get_text(recursive=True)` walks `iter_all()`, which yields
				# **self** first and appends each node's text *and tail* — so
				# this node's own tail is already in `text_val`. Appending it
				# again duplicated it, and the duplicate is a whole clause:
				#
				#   <h1>World Wide Web</h1>The W3 is a wide-area…
				#   -> 'World Wide Web The W3 is a wide-area The W3 is a wide-area'
				#
				# Any element with a tail was affected, which is any inline
				# element followed by text — the ordinary shape of prose with
				# links in it. The other branch below builds from `node.text`,
				# which does *not* include the tail, so it adds it there.
				text_val = node.get_text(recursive=True, separator=" ")
				if text_val and text_val.strip(): text_parts.append(text_val.strip())
				if text_parts:
					final_val = " ".join(text_parts).translate(_INVISIBLE_TRANS).strip()
					if final_val and _has_real_text(final_val):
						self._add('text', 'visible', xpath, final_val, '')
						# Prevent inline children from being tagged individually and duplicating text
						if hasattr(node, 'iter_descendants'):
							for desc in node.iter_descendants():
								self._skip_text_ids.add(id(desc))
			else:
				text_parts = []
				if node.text and node.text.strip(): text_parts.append(node.text.strip())
				if node.tail and node.tail.strip(): text_parts.append(node.tail.strip())
				if text_parts:
					text_val = " ".join(text_parts).translate(_INVISIBLE_TRANS).strip()
					if text_val and _has_real_text(text_val):
						self._add('text', 'visible', xpath, text_val, '')

		# Meta tag content
		if tag == 'meta':
			content = (node.get_attr('content') or '').strip()
			if content:
				self._add('text', 'metadata', xpath, content, 'content')
				# Also scan meta content for URLs. A single ``content``
				# attribute can hold several (e.g. a CSP or a link header),
				# so carry the offset as the sub-address — but only when
				# there is more than one, so the common single-URL meta
				# keeps its bare accessor.
				hits = _extract_urls_with_offsets(content)
				for url, off in hits:
					url_class = _classify_url(url)
					self._add('urls', url_class, xpath, url, 'content',
						'' if len(hits) == 1 else f'@{off}')

	# JSON-LD fields whose VALUE is a URL or list of URLs. Schema.org
	# uses ``url``-suffixed keys broadly; we special-case well-known
	# media-bearing ones so the media classifier gets the right
	# subcategory (images vs. video vs. audio) rather than a generic
	# "external URL" tag.
	_JSONLD_IMAGE_FIELDS = frozenset({
		'image', 'logo', 'thumbnail', 'thumbnailurl', 'photo',
		'primaryimageofpage', 'icon',
	})
	_JSONLD_VIDEO_FIELDS = frozenset({
		'contenturl', 'embedurl', 'video', 'trailer',
	})
	_JSONLD_AUDIO_FIELDS = frozenset({'audio'})
	_JSONLD_TEXT_FIELDS = frozenset({
		'name', 'headline', 'description', 'alternatename',
		'abstract', 'articlebody', 'caption', 'disambiguatingdescription',
		'keywords', 'text',
	})

	def _scan_json_ld_payload(self, raw: str, script_xpath: str) -> None:
		"""Parse a ``<script type="application/ld+json">`` body and tag fields.

		Tolerates malformed payloads (returns silently) and nested
		arrays. Each field we recognise is emitted under its best
		category — text fields as ``text/metadata`` with the JSON key
		as ``source_attr``, URL fields as ``urls/*`` plus the matching
		``media/*`` subcategory so the chunker's
		:meth:`_image_url_for_member` / ``extractMediaFromHtml`` pick
		them up alongside direct ``<img>`` / ``<video>`` tags.
		"""
		try:
			payload = _json.loads(raw)
		except (ValueError, TypeError):
			return

		# One <script> node holds an entire JSON document, so the node
		# address alone cannot separate its fields. The JSON pointer
		# (RFC 6901 shape: /mainEntity/itemListElement/3/url) is the
		# intrinsic sub-address — re-resolvable by parsing the same script
		# body, and stable under any reordering of the emit sites.
		def _emit_url_like(field: str, value: str, ptr: str) -> None:
			val = (value or "").strip()
			if not val:
				return
			url_class = _classify_url(val)
			self._add('urls', url_class, script_xpath, val[:500], f'ld_json:{field}', ptr)
			key = field.lower()
			# Explicit-field classification first — covers cases like
			# ``embedUrl`` pointing at a YouTube page URL with no .mp4
			# extension.
			if key in self._JSONLD_IMAGE_FIELDS:
				self._add('media', 'images', script_xpath, val[:500], f'ld_json:{field}', ptr)
			elif key in self._JSONLD_VIDEO_FIELDS:
				self._add('media', 'video', script_xpath, val[:500], f'ld_json:{field}', ptr)
			elif key in self._JSONLD_AUDIO_FIELDS:
				self._add('media', 'audio', script_xpath, val[:500], f'ld_json:{field}', ptr)
			else:
				# Fall back to extension-based classification for
				# generic ``url`` / ``sameAs`` keys so a .jpg URL there
				# still surfaces as an image.
				mcat = _classify_media(val)
				if mcat:
					self._add('media', mcat, script_xpath, val[:500], f'ld_json:{field}', ptr)

		def _walk(obj, parent_key: str = "", ptr: str = "") -> None:
			if isinstance(obj, dict):
				for k, v in obj.items():
					k_str = str(k)
					_walk(v, k_str, f'{ptr}/{_ptr_escape(k_str)}')
			elif isinstance(obj, list):
				for i, item in enumerate(obj):
					_walk(item, parent_key, f'{ptr}/{i}')
			elif isinstance(obj, str):
				key = parent_key.lower()
				# Text-bearing prose fields — emit as metadata so the
				# chunker's text budget sees them.
				if key in self._JSONLD_TEXT_FIELDS and _has_real_text(obj):
					self._add('text', 'metadata', script_xpath, obj[:500],
						f'ld_json:{parent_key}', ptr)
				# URL-bearing fields: heuristic matches either an
				# explicit key name or a URL-like value anywhere.
				if (
					key in self._JSONLD_IMAGE_FIELDS
					or key in self._JSONLD_VIDEO_FIELDS
					or key in self._JSONLD_AUDIO_FIELDS
					or key in ('url', 'sameas', 'mainentityofpage', 'identifier')
					or obj.startswith(('http://', 'https://', '//'))
				):
					_emit_url_like(parent_key, obj, ptr)
			# ints/floats/bools/None carry no extractable content.

		_walk(payload)

	def _add(self, category: str, subcategory: str, xpath: str,
		value: str, source_attr: str, sub: str = '') -> None:
		"""Register a content finding.

		``sub`` names the position within the accessor for the accessors that
		hold more than one value; see :class:`ContentTag`. Callers that emit at
		most one value per node per accessor leave it empty.
		"""
		tag = ContentTag(
			xpath=xpath,
			category=category,
			subcategory=subcategory,
			value=value,
			source_attr=source_attr,
			sub=sub,
		)
		self._result.all_tags.append(tag)
		self._seen_xpaths.add(xpath)

		# Add xpath to the right bucket (deduplicate within bucket)
		group = getattr(self._result, category)
		arr = group[subcategory]
		if xpath not in self._seen_xpaths or True:
			# We allow duplicate xpaths across categories but only add
			# to a specific bucket once per xpath
			if xpath not in arr:
				arr.append(xpath)
