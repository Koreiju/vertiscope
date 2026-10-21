"""The page's own account of itself, addressed the way the trie addresses it.

This is the *left* side of the affine map. `vertiscope.analytics.affine` compares
it against the right side -- the patricia trie and the two projections drawn
from it -- and every disagreement is a defect in the map rather than a
difference of opinion about wording.

Why addresses rather than text
------------------------------
Earlier coverage work matched page content against rendered content by
substring, and it was wrong four separate times in the same direction: hidden
content scored against a drawing, case-sensitive matching against a renderer
that uppercases bold, hrefs scored against a projection that strips hrefs by
design, and unwrapped strings scored against a wrapping layout. Each made a
*correct* renderer read as broken.

The trie is keyed on `url : xpath : markdown : content`, and the xpath is the
part that is supposed to be shared with the page. So the comparison is made on
that key. Text can be rewrapped, uppercased, joined with its label or given a
glyph -- all of which the projections are entitled to do -- without moving the
address it hangs from. An address that does not survive the map is a hole in
the map, and nothing else is.

Matching the fold's spelling
----------------------------
These addresses must be spelled exactly as `sensing.Sensor._xpath` spells
them, or every unit reads as lost:

* rooted at ``/html`` -- the fold starts at ``documentElement``;
* an element step is ``tag`` when its ordinal is 1 and ``tag[n]`` otherwise
  (`sensing._name_test`);
* a text child is ``text()[n]``, never ``#text[n]``, which is not a legal step;
* a shadow boundary is ``#shadow-root``, deliberately not legal XPath because
  no XPath crosses a shadow boundary;
* light and shadow children are **separate ordinal namespaces**
  (`sensor.js::stepFor`), and a skipped tag consumes no ordinal, because the
  skip test runs before the counter increments.

The composed-tree walk below is the third copy of a walk that also exists in
`sensor.js`. `invariants.c1_composed_walks_resolve_slots` parses them and
checks they agree, for the reason it has always checked: a ground truth that
repeats the fold's mistake agrees with it perfectly and measures nothing.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

__all__ = ["PageUnit", "PageTruth", "GROUND_TRUTH_JS", "read_page_truth"]


@dataclass(frozen=True)
class PageUnit:
    """One addressable thing the page holds."""

    xpath: str
    kind: str          # text | link | media | control
    value: str
    drawn: bool        # the page lays it out; a wireframe may show it
    shadow: bool       # reached only by crossing a shadow boundary

    def key(self) -> str:
        return f"{self.kind}\x00{self.xpath}"


@dataclass
class PageTruth:
    """Everything the page says about itself, plus how it was reached."""

    url: str
    units: List[PageUnit]
    elements: int = 0
    shadow_hosts: int = 0
    opaque_hosts: int = 0
    static_chars: int = 0

    def of_kind(self, kind: str) -> List[PageUnit]:
        return [u for u in self.units if u.kind == kind]

    @property
    def drawn(self) -> List[PageUnit]:
        return [u for u in self.units if u.drawn]


# The walk. Kept as one string so `invariants` can read it back out of the
# source and compare it with the fold's copy without a browser.
GROUND_TRUTH_JS = r"""
var units = [], hosts = 0, opaque = 0;
var SKIP = {SCRIPT:1, STYLE:1, NOSCRIPT:1, TEMPLATE:1, HEAD:1};
// Collapsed controls are leaves: a <select> draws the one value it holds and
// keeps the other eighty behind it. The fold folds them, so ground truth must
// too, or every option reads as content the render lost.
var FOLDED = {SELECT:1, DATALIST:1, OPTGROUP:1};
var MEDIA = {IMG:1, PICTURE:1, SVG:1, VIDEO:1, AUDIO:1, SOURCE:1, IFRAME:1,
             EMBED:1, OBJECT:1};
var MEDIA_ATTRS = ['src', 'srcset', 'poster', 'data', 'data-src'];
// AREA carries an href in an image map and is role=link in HTML-AAM: a
// clickable region of a picture is a place the page can be interacted with,
// and leaving it out charged weather.gov's 254 map regions to the renderer as
// invented affordances when the renderer had them right.
//
// LABEL is deliberately absent. A label is a *name* for a control, and
// clicking one activates the control it names -- which is counted in its own
// right. Counting both makes one affordance two, and the second is not
// somewhere a reader can do anything the first does not already offer.
var CONTROL_TAGS = {A:1, AREA:1, BUTTON:1, INPUT:1, SELECT:1, TEXTAREA:1,
                    SUMMARY:1, DETAILS:1, OPTION:1};
var CONTROL_ROLES = {button:1, link:1, checkbox:1, radio:1, textbox:1,
                     searchbox:1, combobox:1, listbox:1, slider:1, tab:1,
                     menuitem:1, switch:1, option:1, spinbutton:1};
// Attributes that carry content rather than describing presentation.
var ATTR_CONTENT = ['content', 'alt', 'aria-label', 'title', 'placeholder',
                    'itemtype', 'datetime', 'label', 'aria-description'];

// The composed tree, which is not childNodes: a light child of a shadow host
// is drawn at the slot that claims it, and a filled slot does not draw its
// fallback. Returns [children, whetherThoseChildrenAreShadowContent]. The
// flag is not simply inherited -- nodes assigned to a slot are drawn inside
// the shadow tree but ARE light DOM, and a static fetch reaches them.
function kidsOf(node, inShadow) {
  if (node.nodeType === 1 && node.shadowRoot)
    return [node.shadowRoot.childNodes, true];
  if (node.nodeType === 1 && node.tagName === 'SLOT' && node.assignedNodes) {
    var an = null;
    try { an = node.assignedNodes({flatten: true}); } catch (e) { an = null; }
    if (an && an.length) return [an, false];
  }
  return [node.childNodes || [], inShadow];
}

// `sensing._name_test`, and `sensor.js::stepFor` for the ordinal.
function step(tag, n) { return n > 1 ? tag + '[' + n + ']' : tag; }

// Whether a reader can actually see this, not whether it has layout.
//
// `getClientRects().length` was the test, and it is the wrong one: an element
// with `visibility: hidden` or `opacity: 0` is laid out and returns rects
// while showing nothing. github.com's collapsed mega-menu is exactly that --
// `rects=1, visibility=hidden` on every item of it -- so a wireframe that
// correctly declined to draw a menu the reader cannot see was scored as
// losing 213 units, and read 65.0% on a page it renders faithfully.
//
// `checkVisibility` is the predicate that answers the question asked, with
// the opacity and content-visibility checks turned on explicitly because they
// are off by default. Falls back to the rect test where it does not exist,
// which is the old behaviour and no worse than it was.
function drawnNow(el) {
  if (!el) return false;
  try {
    if (typeof el.checkVisibility === 'function'
        && !el.checkVisibility({
             opacityProperty: true,
             visibilityProperty: true,
             contentVisibilityAuto: true
           })) {
      return false;
    }
    // And it has to occupy space. `checkVisibility` answers "is this hidden",
    // which is not the same question as "can a reader see it": it ignores
    // geometry entirely, so an <img> that has not loaded reports visible at
    // 1366x0. salesforce.com carries nine of those, and counting them as
    // drawn charged the wireframe eleven losses for declining to place
    // pictures with no area -- media read 76.6% against markdown's 97.2% on
    // the same page, which is the shape of a denominator fault rather than a
    // renderer one.
    var r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  } catch (e) { return true; }
}

function sourceOf(el) {
  for (var i = 0; i < MEDIA_ATTRS.length; i++) {
    var v = el.getAttribute(MEDIA_ATTRS[i]);
    if (v !== null && String(v).trim() !== '') return String(v).trim();
  }
  return '';
}

function isControl(el) {
  if (CONTROL_TAGS[el.tagName]) {
    // An anchor or a map region without an href goes nowhere and does
    // nothing; it is a name, not an affordance.
    if (el.tagName === 'A' || el.tagName === 'AREA')
      return el.getAttribute('href') !== null;
    // An input the page never lays out cannot be reached by a reader, so it
    // is not an affordance the renderer is answerable for.
    if (el.tagName === 'INPUT') {
      var ty = (el.getAttribute('type') || 'text').toLowerCase();
      if (ty === 'hidden') return false;
    }
    return true;
  }
  var role = (el.getAttribute('role') || '').trim().toLowerCase();
  if (role && CONTROL_ROLES[role]) return true;
  if (el.hasAttribute('onclick')) return true;
  var ti = el.getAttribute('tabindex');
  return ti !== null && ti !== '-1';
}

// Two flags, and they are not the same flag.
//
// `boundary` is about the *address*: `sensor.js::stepFor` prefixes
// `#shadow-root` only onto the steps of a shadow root's **direct children**,
// because the boundary is crossed once and one step records it. Carrying it
// down inherited spells `#shadow-root` at every level, and on lit.dev that
// produced addresses like `.../#shadow-root/div/#shadow-root/h2/text()[1]`
// which match nothing the fold ever emitted -- so shadow content read as 63%
// lost when none of it was.
//
// `origin` is about *provenance*: whether this content sits inside a shadow
// tree at all, which is what the light/shadow split reports. It is inherited,
// and it is deliberately false for slotted nodes -- they are drawn inside the
// component but they are light DOM, and a static fetch reaches them.
function walk(node, path, origin, folded) {
  var region = kidsOf(node, origin);
  var kids = region[0];
  var boundary = node.nodeType === 1 && !!node.shadowRoot;
  var childOrigin = region[1];
  // Separate ordinal namespaces, exactly as stepFor keeps them: crossing into
  // a shadow root restarts the count, so a host's light and shadow children
  // never share a numbering.
  var counts = {}, i, kid, here, seg;
  for (i = 0; i < kids.length; i++) {
    kid = kids[i];
    if (kid.nodeType === 3) {
      var text = (kid.nodeValue || '').trim();
      // The ordinal counts every text child, empty or not, because
      // `text()[n]` is XPath and XPath counts them all. Skipping the count
      // for whitespace produced addresses that do not resolve: on
      // es.wikipedia truth claimed `.../p/text()[3]` held ", y este del"
      // while `document.evaluate` on that path returns an empty node, and
      // the sensor's `text()[16]` resolved to exactly the "y" it recorded.
      //
      // It cost 115 invented and 115 lost on that page alone -- the *same*
      // units, counted once on each side of the confusion matrix, because
      // both maps held the content and disagreed only about its index.
      // Roughly 230 of the corpus's ~1,290 capture errors were this.
      //
      // The rule above -- a skipped tag consumes no ordinal -- is about
      // elements the walk ignores entirely. A whitespace text node is not
      // ignored by XPath, so it is not the same case, and carrying the rule
      // across was the mistake.
      counts['#text'] = (counts['#text'] || 0) + 1;
      if (!text) continue;
      here = boundary
        ? path + '/#shadow-root/text()[' + counts['#text'] + ']'
        : path + '/text()[' + counts['#text'] + ']';
      units.push({p: here, k: 'text', v: text,
                  d: drawnNow(kid.parentElement), s: childOrigin});
      continue;
    }
    if (kid.nodeType !== 1) continue;
    // The skip test runs before the counter, so a skipped tag consumes no
    // ordinal. Counting it here would shift every following sibling.
    if (SKIP[kid.tagName]) continue;
    var tag = kid.tagName.toLowerCase();
    counts[tag] = (counts[tag] || 0) + 1;
    seg = step(tag, counts[tag]);
    here = boundary ? path + '/#shadow-root/' + seg : path + '/' + seg;

    // Inside a folded control nothing is laid out, whatever the box
    // model says about the option elements themselves.
    var drew = folded ? false : drawnNow(kid);
    if (kid.tagName === 'A' && kid.getAttribute('href') !== null) {
      units.push({p: here, k: 'link',
                  v: String(kid.getAttribute('href') || '').trim(),
                  d: drew, s: childOrigin});
    }
    if (MEDIA[kid.tagName]) {
      var src = sourceOf(kid);
      if (src) units.push({p: here, k: 'media', v: src, d: drew,
                           s: childOrigin});
    }
    // Content that lives in an attribute rather than in a text node. The
    // fold captures these -- an alt, an aria-label, a <meta content=...>
    // holding a page's keywords are all things a reader is entitled to --
    // so ground truth that collected only text nodes reported the trie as
    // inventing twenty addresses on a page where it invented none.
    // A baseline that does not know about content the sensor correctly
    // captures scores correct capture as a defect.
    for (var ai = 0; ai < ATTR_CONTENT.length; ai++) {
      var an2 = ATTR_CONTENT[ai];
      if (!kid.hasAttribute(an2)) continue;
      var av = String(kid.getAttribute(an2) || '').trim();
      if (!av) continue;
      units.push({p: here, k: 'attr', v: av, d: drew, s: childOrigin});
    }
    if (isControl(kid)) {
      var label = '';
      try {
        label = (kid.getAttribute('aria-label')
                 || kid.getAttribute('title')
                 || kid.getAttribute('value')
                 || (kid.textContent || '')).trim().slice(0, 120);
      } catch (e) { label = ''; }
      units.push({p: here, k: 'control', v: label, d: drew, s: childOrigin});
    }

    if (kid.shadowRoot) { hosts++; walk(kid, here, childOrigin, folded); continue; }
    // Unreachable by design (CONTENT_EXTRACTION_RULES 8.4): counted, never
    // read as an empty element, so the coverage figure stays honest about
    // what it could not see.
    var ln = kid.localName || '';
    if (ln.indexOf('-') > -1 && !kid.childNodes.length) {
      try { if (customElements.get(ln)) opaque++; } catch (e) {}
    }
    // Descend into a folded control, marking everything inside undrawn,
    // rather than skipping it.
    //
    // Skipping conflates "the page does not lay this out" with "the page does
    // not have it", and the two arrows need those apart. The trie *captures* a
    // select's options -- content the page holds -- while the render collapses
    // the select to the one value it shows, which is right. Omitted from
    // ground truth, those captured options read as addresses the sensor
    // invented: 2,960 of data.gov.uk's 2,962, on a page holding 1,511 options,
    // and a large share of 7,043 across the corpus.
    //
    // `drew` is exactly the flag for this distinction, and it already exists.
    walk(kid, here, childOrigin, folded || !!FOLDED[kid.tagName]);
  }
}

walk(document.documentElement, '/html', false);
var staticLen = 0;
try { staticLen = (document.documentElement.outerHTML || '').length; }
catch (e) { staticLen = 0; }
return {units: units, hosts: hosts, opaque: opaque, staticChars: staticLen,
        elements: document.getElementsByTagName('*').length};
"""


def read_page_truth(driver: Any, url: str) -> PageTruth:
    """Run the walk in the page and lift it into `PageTruth`.

    Reads layout (`getClientRects`) on purpose and safely: this is a
    measurement pass that runs once, outside the fold, and the fold's freedom
    from layout reads is a separate property enforced by `invariants.c2`.
    """
    payload: Optional[Dict[str, Any]] = driver.execute_script(GROUND_TRUTH_JS)
    payload = payload or {}
    units = [
        PageUnit(xpath=str(row.get("p") or ""),
                 kind=str(row.get("k") or "text"),
                 value=str(row.get("v") or ""),
                 drawn=bool(row.get("d")),
                 shadow=bool(row.get("s")))
        for row in (payload.get("units") or [])
        if row.get("p")
    ]
    return PageTruth(
        url=url,
        units=units,
        elements=int(payload.get("elements") or 0),
        shadow_hosts=int(payload.get("hosts") or 0),
        opaque_hosts=int(payload.get("opaque") or 0),
        static_chars=int(payload.get("staticChars") or 0),
    )
