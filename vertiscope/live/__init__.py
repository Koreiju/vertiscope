"""The page as callable objects: the Python REPL is the browser.

See docs/CALLABLE_INTERFACE.md. The short of it:

* **The object tree IS the trie.** Not a projection of it, not a grouping over
  it -- the same nodes, in the same order, with the same addresses. Nothing
  here decides what a thing is *for*, so nothing here can decide wrongly. A
  `form` is called `form` because the page wrote `<form>`.
* **The repr is the API.** Every line printed is an expression you can type
  back. `div(2)` is the tag plus its xpath ordinal, which is a slice of the
  address the trie already holds.
* **Calling is descent.** A container focuses; an affordance acts. That is
  expand-collapse without a screen to redraw, which is the whole reason this
  is cheaper than a TUI for a small context window.
* **The markdown carries its handles.** `read()` is `text()` with every
  affordance marked `act(n)` in reading order, so what a reader sees and what
  a reader can press are one surface. A mark names a trie address, the
  address names an xpath, the xpath names the element -- the arrow back to
  the live document, along the same `url : xpath : taxonomy : content` key
  the fold is built on.

    >>> from vertiscope.live import *
    >>> Page("https://duckduckgo.com")
    >>> read()
    >>> input(1) << "glacier retreat"
    >>> button(1)()
    >>> ol(1)
    >>> li(1)
    >>> up()

`help(obj)` on any node says what it is, where it is, and what can be done
with it -- which is the point of hosting this in the REPL at all.
"""

from __future__ import annotations

import keyword as _keyword
import re as _re
import time as _time
from typing import List, Optional, Sequence, Tuple

__all__ = [
    "Page", "Browser", "workspace", "up", "top", "back", "here", "where",
    "attach", "close", "acts", "act", "wire", "read", "Refused", "Node",
    "Drawing", "Reading",
]

#: Every HTML tag, exported as a selector. Static, so `import *` works and so
#: the names in a repr are the names in the namespace. A tag is only ever a
#: tag: there is no table mapping it to what it might mean.
_TAGS = (
    "a abbr address area article aside audio b bdi bdo blockquote body button "
    "canvas caption cite code col colgroup data datalist dd del details dfn "
    "dialog div dl dt em embed fieldset figcaption figure footer form h1 h2 "
    "h3 h4 h5 h6 head header hgroup hr html i iframe img input ins kbd label "
    "legend li link main map mark menu meta meter nav noscript object ol "
    "optgroup option output p param picture pre progress q rp rt ruby s samp "
    "script section select slot small source span strong style sub summary "
    "sup svg table tbody td template textarea tfoot th thead time title tr "
    "track u ul var video wbr"
).split()

__all__ += _TAGS


class Refused(Exception):
    """An enactment the safety rules will not perform.

    Raised, never returned as a silent no-op: a model that cannot tell a
    refusal from a completed action will believe it signed in.
    """


# --- the refusal set, mirrored from the sensor --------------------------------
# `sensor.js` holds the original and applies it to the autonomous scroller.
# This surface is driven by a model, which is the case the denylist was
# written for, so the same rules have to be answerable here in Python.
# `tests/test_live_refusal.py` asserts the two copies still agree.

_NEVER_LABEL = _re.compile(
    r"sign\s?(in|up|out)|log\s?(in|out)|register|subscribe|unsubscribe"
    r"|checkout|buy|purchase|order|add to (cart|bag)|donate|pay\b|upgrade"
    r"|delete|remove|discard|clear all|unfollow|block\b|report\b|flag\b"
    r"|upload|publish|submit|send\b|reply|confirm|accept|agree|consent"
    r"|install|download", _re.I)

_NEVER_HREF = _re.compile(
    r"(^|\.|/)(accounts?|auth|login|signin|signup|register|logout|signout"
    r"|checkout|cart|basket|billing|payment|donate|subscribe)(/|\.|\?|$)"
    r"|[?&](sign|log)in=", _re.I)


def _refuse_check(label: str, href: str) -> None:
    """Raise `Refused` naming the rule that matched, or return."""
    hit = _NEVER_LABEL.search(label or "")
    if hit:
        raise Refused(
            "label matches the never-press set (%r)" % hit.group(0).strip())
    hit = _NEVER_HREF.search(href or "")
    if hit:
        raise Refused("target matches the never-visit set (%r)" % hit.group(0))


# --- the session --------------------------------------------------------------


class _Session:
    """Driver, fold and cursor. One per interpreter, like a browser window."""

    def __init__(self) -> None:
        self.driver = None
        self.url = ""
        self.spine = None
        self.sensor = None
        self.cursor = None          # a TrieNode
        self.acts = []              # the last acts() listing, for act(n)
        self.workspace = None       # opened by `workspace()`; None = no index
        self.clicked_via_href = False   # last press fell back to the target
        self.window = 1200
        # The rendered chunks for the fold now in hand. Cleared by `fold`,
        # which is the only thing that can invalidate them: within one page
        # the trie does not change under us, so re-rendering per repr was
        # paying a page-sized cost to print eight lines. See `rendered`.
        self._chunks = None
        # Geometry for this fold, measured lazily by `wire`. Layout is a
        # peripheral keyed by address and never part of the fold.
        self.styles = None

    # -- browser ---------------------------------------------------------
    def attach(self, *, headless: bool = True):
        from ..browser import build_driver
        from ..config import load_config

        if self.driver is not None:
            self.close()
        self.driver = build_driver(load_config(), headless=headless)
        self.driver.set_page_load_timeout(45)
        return self.driver

    def close(self) -> None:
        if self.workspace is not None:
            try:
                self.workspace.close()
            except Exception:       # noqa: BLE001
                pass
            self.workspace = None
        if self.driver is not None:
            try:
                self.driver.quit()
            except Exception:       # noqa: BLE001 - shutting down must not raise
                pass
            self.driver = None

    def need_driver(self):
        if self.driver is None:
            self.attach()
        return self.driver

    # -- the fold --------------------------------------------------------
    def fold(self, url: str) -> None:
        """Sense the page now loaded, and point the cursor at its root.

        Re-folded from scratch on every navigation rather than repaired,
        because a new document shares nothing with the old one. Within a page
        the sensor's own delta path does the work.
        """
        from ..sensing import Sensor
        from ..stream import StreamingScan

        driver = self.need_driver()
        self.url = url
        self.sensor = Sensor(driver, url, budget=self.window)
        self.sensor.boot()
        _time.sleep(0.5)
        self.spine = StreamingScan(url, context_window=self.window)
        for _ in range(12):
            delta = self.sensor.drain(0)
            self.spine.absorb(delta.units, delta.passno,
                              removed=delta.removed_addresses,
                              moved=delta.moved_addresses)
            if delta.settled and not delta.units:
                break
            _time.sleep(0.25)
        self._chunks = None         # a new page: whatever was cached is gone
        self.styles = None          # and its geometry with it
        self.cursor = _page_root(self.spine.trie)
        self._record()

    def rendered(self):
        """This fold's chunks, rendered once.

        `_chunk_count` and `Node.text` both went through `render_trie` over
        the whole trie, with no memo, on every call. Printing the page object
        therefore cost a full re-render: 9.83s to produce 490 characters on a
        2.6MB page, and 9.54s again for any childless node, because its repr
        is its text.

        That is the opposite of the argument this interface is built on --
        that a reader pays for the eight children in front of them and pays
        again only when they descend. They were paying for the page, every
        time, and the token cost being small hid a latency cost that was not.

        Cleared by `fold`, which is the only event that can invalidate it.
        """
        if self._chunks is None:
            from ..markdown import render_trie

            if self.spine is None:
                return []
            self._chunks = list(
                render_trie(self.spine.trie, context_window=self.window))
        return self._chunks

    def _record(self) -> None:
        """Write this fold into the workspace, if one is open.

        The chunks the index ranks are the chunks the object tree shows --
        the same `render_trie` output, ingested through the same path a scan
        uses. Folding once and ingesting is what keeps retrieval answering
        about the page you are actually looking at.

        A failure here must not take the browsing session with it: reading a
        page is useful even when recording it is not possible.
        """
        if self.workspace is None or self.spine is None:
            return
        try:
            # The same render the reader sees, not a second one.
            self.workspace.ingest_chunks(self.url, list(self.rendered()))
        except Exception as exc:                # noqa: BLE001
            print("  (not recorded: %s: %s)" % (type(exc).__name__, exc))

    def refold(self) -> None:
        """After an enactment. The url may have changed under us."""
        driver = self.need_driver()
        try:
            now = driver.current_url
        except Exception:           # noqa: BLE001
            now = self.url
        self.fold(now)


_S = _Session()


#: A positional xpath step already carrying its index.
_STEP_INDEXED = _re.compile(r"\[\d+\]$")


def _canon(xpath: str) -> str:
    """One spelling per position.

    A trie node spells the first of its kind `/p/a`, while the address the
    renderer carries spells the same element `/p/a[1]`. Two strings, one
    position, and every comparison between the object model and the markdown
    crosses that seam.

    It cost two things, both silent. `read()` could not mark the first link,
    the first input or the first button on a page -- which on most pages is
    the one meant. And `text()` compared with `startswith`, where
    `"/p/a[2]"` starts with `"/p/a"`: asking the first paragraph what it said
    returned the second paragraph as well, with nothing in the answer to say
    so. Indexing every step makes the two vocabularies one, and makes the
    prefix test mean ancestry again.
    """
    steps = []
    for step in xpath.split("/"):
        if step and not step.startswith("@") and not _STEP_INDEXED.search(step):
            step += "[1]"
        steps.append(step)
    return "/".join(steps)


def _under(xpath: str, root: str) -> bool:
    """Is `xpath` at or below `root`? A step boundary, never a substring.

    `/html/body/nav` is not under `/html/body/na`, and no amount of
    `startswith` knows that.
    """
    if root in ("", "/"):
        # The whole document. A page with no single root element is held by
        # the url node, whose xpath is "/" -- and "/x" does not start with
        # "//", so the general test answers no for every node on such a page.
        return True
    xpath, root = _canon(xpath), _canon(root)
    return xpath == root or xpath.startswith(root + "/")


def _page_root(trie):
    """Descend past the url path segments to the document node.

    The url occupies the first levels of the trie -- `https:`, the host, each
    path segment -- and none of them is part of the page. The document node is
    the first that carries an xpath of its own.
    """
    node = trie.root
    while True:
        kids = node.ordered_children()
        real = [k for k in kids
                if (getattr(k, "_xpath_cache", "/") or "/") != "/"]
        if len(real) == 1:
            # The one child carrying an xpath IS the document element.
            # Stopping one short of it made the cursor the url segment, so a
            # session opened onto a filename with one child under it.
            return real[0]
        if real:
            # Several. There is no document element to descend to, and
            # taking the first is how `Page("https://danluu.com")` came to
            # open onto a `<meta>` tag: its top level is
            # `/meta /meta[2] /ul /footer /script`, so the walk visited one
            # node and the whole page -- 203 links included -- was invisible
            # to the object model. Three corpus pages are shaped this way,
            # all of them hand-written or very old html that never had one
            # root. The node holding them all is the honest cursor.
            return node
        if len(kids) != 1:
            return node
        node = kids[0]


def _dom_children(tnode) -> list:
    """A node's DOM children, in document order.

    A trie node's children are of two kinds: the elements and text nodes under
    it, and the taxonomy/accessor segments that carry its own values. The two
    are told apart by the xpath -- a DOM child has one of its own, while an
    accessor shares its parent's, because only DOM steps extend the path.
    """
    mine = getattr(tnode, "_xpath_cache", None)
    return [k for k in tnode.ordered_children()
            if (getattr(k, "_xpath_cache", None) or mine) != mine]


def _leaves_of(tnode) -> List[Tuple[object, str]]:
    """The values addressed AT this node, not below it."""
    mine = getattr(tnode, "_xpath_cache", None)
    out = []
    stack = [tnode]
    while stack:
        node = stack.pop()
        for kid in node.ordered_children():
            if (getattr(kid, "_xpath_cache", None) or mine) != mine:
                continue            # a DOM child: its values are its own
            if kid.is_leaf and (kid.value or "").strip():
                out.append((kid.address, kid.value))
            stack.append(kid)
    return out


def _spoken_under(tnode, limit: Optional[int] = None) -> List[Tuple[object, str]]:
    """Every `text()` value in this subtree, in document order.

    Reader-facing text only. An `href`, a `title`, a `@control` annotation are
    all values the trie is right to hold and none of them is what the page
    shows in the place this node occupies.

    `limit` stops the walk once that many characters have been gathered.
    Without it a label was produced by collecting every text leaf under a
    node and *then* keeping 46 characters of it -- so labelling the `<div>`
    that holds a whole page walked the whole page: 9.4 seconds to print one
    line of a tree listing, with the answer decided by the first few nodes
    visited.
    """
    out: List[Tuple[object, str]] = []
    seen = [0]

    def walk(node) -> bool:
        """False to stop: enough has been gathered."""
        mine = getattr(node, "_xpath_cache", None)
        for kid in node.ordered_children():
            if (getattr(kid, "_xpath_cache", None) or mine) != mine:
                if not walk(kid):               # a DOM child
                    return False
                continue
            if kid.is_leaf and (kid.value or "").strip():
                accessor = getattr(kid.address, "accessor", "") or ""
                if (accessor.startswith("text()")
                        and not _echoes_its_element(kid.address, kid.value)):
                    out.append((kid.address, kid.value))
                    seen[0] += len(kid.value or "")
                    if limit is not None and seen[0] >= limit:
                        return False
            elif not walk(kid):                 # a taxonomy step
                return False
        return True

    walk(tnode)
    return out


def _echoes_its_element(address, value: str) -> bool:
    """Is this value the page's words, or the fold repeating the element name?

    `_add('interactive', 'links', xpath, tag, '')` stores `'a'` at the `<a>`
    and `_add('media', 'images', ...)` stores `'img'` at the `<img>`, because
    for those the element IS the finding and there is nothing else to record.

    The guard that already existed skipped accessors beginning `@` --
    `@control`, `@role` -- which is how the SENSOR spells its synthetic
    annotations. The tagger spells the same thing with an empty accessor,
    which the trie normalises to `text()`, so on the snapshot path every one
    of these passed the "reader-facing text" test. Hacker News listed its
    `<body>` as `"img a a a a a a a a a new | past | comments"` and all 228
    of its links as `'a'`: the fold's bookkeeping printed in the one column a
    reader looks at to tell two links apart.

    Compared against the address's OWN last step, not against a list of tag
    names. A list would have to be kept in step with the html spec, and the
    "short and alphabetic" test `markdown._is_tag_name` uses -- right for a
    media value -- deletes `Search`, `Home` and `DuckDuckGo` when used on a
    label. A page whose link text is literally "a" loses its label, which is
    the same trade `_control_label` already makes.
    """
    xpath = getattr(address, "xpath", "") or ""
    step = xpath.rstrip("/").rsplit("/", 1)[-1].split("[")[0]
    return bool(step) and value.strip().lower() == step.lower()


def _tag_of(tnode) -> str:
    return (tnode.segment or "").split("[", 1)[0]


def _ordinal_of(tnode) -> int:
    seg = tnode.segment or ""
    if "[" in seg:
        try:
            return int(seg.split("[", 1)[1].rstrip("]"))
        except ValueError:
            return 1
    return 1


def _label_of(tnode, width: int = 46) -> str:
    """The page's own words for this node, truncated. Never our name for it."""
    # The reader's words, from anywhere below; machine values only if there
    # are none at all.
    #
    # An anchor's own leaf is its href, and its words live one level deeper
    # under a `text()` node. Labelling from the nearest leaf therefore named
    # every link after its target: three list items reading
    # "live_target.html" where the page says "Go to the target page". The TUI
    # made this exact mistake once -- a label is what a reader sees, a target
    # is where it goes.
    parts = []
    # Gather only a little more than the label can show.
    for _address, value in _spoken_under(tnode, limit=width * 3):
        value = " ".join((value or "").split())
        if value:
            parts.append(value)
        if sum(len(p) for p in parts) > width:
            break
    if not parts:
        for address, value in _leaves_of(tnode):
            # Never a synthetic annotation.
            #
            # `@control` and `@role` are the fold's own classification, not
            # anything the page displays -- `resolvable` calls them synthetic
            # for exactly this reason and scores them neither right nor
            # wrong. Their value is the tag name, so every `<input>` on every
            # page labelled itself `'input'`: machine bookkeeping printed
            # where a reader looks for words, in the one column that says
            # what a control is.
            #
            # A control with genuinely nothing to say gets an empty label,
            # which is the truth. On a real page it rarely happens -- the
            # placeholder, the aria-label or the title is content the page
            # does show, and duckduckgo's search box reads "Search with
            # DuckDuckGo" from one of them.
            if (getattr(address, "accessor", "") or "").startswith("@"):
                continue
            if _echoes_its_element(address, value or ""):
                continue
            value = " ".join((value or "").split())
            if value:
                parts.append(value)
                break
    if not parts:
        return ""
    text = " ".join(parts)
    return text if len(text) <= width else text[:width - 3] + "..."


#: How many nodes `_counts` will visit before saying "and more". A tree
#: listing calls it once per child, so an uncapped walk is quadratic in the
#: page.
_COUNT_CAP = 6000


def _counts(tnode) -> str:
    """What is inside, counted by tag. Counted, not interpreted."""
    from collections import Counter

    seen = Counter()
    stack = list(_dom_children(tnode))
    # Capped, for the same reason the label is: a tree listing calls this for
    # every child, and one of those children is often the div that holds the
    # entire page. An exact tally of a hundred thousand nodes is not worth
    # nine seconds when the line has room for `102a 37button`.
    visited, capped = 0, False
    while stack:
        if visited >= _COUNT_CAP:
            capped = True
            break
        node = stack.pop()
        visited += 1
        tag = _tag_of(node)
        if tag in ("a", "input", "button", "img", "select", "textarea", "li"):
            seen[tag] += 1
        stack.extend(_dom_children(node))
    out = " ".join("%d%s" % (n, t) for t, n in sorted(seen.items()) if n)
    return (out + "+") if (out and capped) else out


#: Tags that are affordances no matter what the fold said about them. A
#: fallback, not the authority: see `_is_affordance`.
_INTERACTIVE = {"a", "button", "input", "select", "textarea", "option",
                "summary", "label"}

#: How the fold says "a control is here", in both of its vocabularies. The
#: snapshot path names an address by what it HELD (`interactive.inputs`); the
#: sensor path names it by what it IS (`field`, `button`). Anything reading
#: only one of them is right on one path and blind on the other -- the same
#: split that made the projection gap look like a 19% loss when it was a
#: comparison keyed on the wrong component.
#: The classes a reader can act on, in the one vocabulary. Membership only,
#: which is all `K` supports.
_CONTROL_CLASSES = frozenset({"link", "button", "field", "choice", "check",
                              "slider"})


def _is_affordance(tnode) -> bool:
    """Can this element be acted on?

    Asked of the fold, not of a tag whitelist. The tagger marks a control
    from four routes -- the tag, `role=`, `contenteditable`, and any `on*`
    handler -- and a whitelist of eight tag names sees only the first. On the
    corpus that whitelist misses controls at `div`, `span` and `script`
    elements that the markdown had already drawn as buttons, so a reader
    could see an affordance in the text and find nothing in `acts()` to press
    it with. The generalisation the whitelist cannot express is exactly the
    one the distiller already computes.

    The tag set stays as a fallback for nodes carrying no address of their
    own, which happens when a control's detections all hang off a child.
    """
    for address, _value in _leaves_of(tnode):
        # One vocabulary. `ContentAddress.render_class` maps the tagger's
        # `interactive.*` and the sensor's `button`/`field` onto the same
        # eighteen classes, so this rule no longer has to know which pipeline
        # produced the address -- which is the question that cost five bugs.
        if getattr(address, "is_control", False):
            return True
    return _tag_of(tnode) in _INTERACTIVE


def _drawn_at() -> dict:
    """Address xpath -> the markdown line drawn from it. Built once per fold.

    An anchor inside prose has no words of its own in the fold. The tagger
    emits a paragraph whose children are all inline as ONE text unit at the
    paragraph and skips every descendant, deliberately, so the words are not
    counted twice -- `content_tagger` says so at the point it does it. The
    cost is that `<a href="/rates">retreat rates</a>` holds an href and
    nothing else, so a label taken from the fold reads `/rates`.

    The renderer already solved this: `_inline_flow` puts the sentence back
    together and keeps every address that went into it. So the label a reader
    should see is the line the render drew -- one derivation, two views,
    rather than a second guess at what the words were.
    """
    at = {}
    for chunk in _S.rendered():
        for line in chunk.lines:
            text = line.text.strip()
            if not text:
                continue
            for address in (line.address,) + tuple(line.inline):
                if address is not None:
                    at.setdefault(_canon(address.xpath), text)
    return at


class Node:
    """One node of the trie, and of the page.

    Calling a container focuses it and shows its children. Calling an
    affordance -- `a`, `button`, `input` -- acts on the page, after the
    refusal check.

        node()          focus, or press
        node << "text"  type into it
        node.text()     the markdown of its subtree
        node.read()     the same markdown, affordances marked `act(n)`
        node.wire()     the same lines, placed where the page puts them
        node.where()    its address
    """

    def __init__(self, tnode) -> None:
        self._t = tnode

    # -- identity --------------------------------------------------------
    @property
    def tag(self) -> str:
        return _tag_of(self._t)

    @property
    def xpath(self) -> str:
        return getattr(self._t, "_xpath_cache", "") or ""

    def where(self) -> str:
        return self.xpath

    def handle(self) -> str:
        return "%s(%d)" % (self.tag, _ordinal_of(self._t))

    # -- reading ---------------------------------------------------------
    def children(self) -> List["Node"]:
        return [Node(k) for k in _dom_children(self._t)]

    #: How much text a bare `text()` hands back, as a multiple of the
    #: session's context window. Tied to that knob rather than to a constant,
    #: so it scales with what the reader actually configured.
    BUDGET_WINDOWS = 8

    def text(self, budget: Optional[int] = -1) -> str:
        """This subtree as markdown, through the one renderer everything uses.

        Windowed by default. Unwindowed it returned 366,005 characters for
        one Wikipedia page -- on an interface whose whole premise is a small
        context window, which makes it the most expensive possible way to
        answer "what does this say".

        `budget=None` gives all of it, deliberately. A truncation says how
        much was left and how to ask for it, because a reader who cannot tell
        a short page from a truncated one has been given the wrong answer
        twice.
        """
        if budget == -1:
            budget = _S.window * self.BUDGET_WINDOWS
        want = self.xpath
        lines = []
        for chunk in _S.rendered():
            for line in chunk.lines:
                if line.address is None:
                    continue
                if _under(line.address.xpath, want):
                    lines.append(line.text)
        body = "\n".join(lines)
        if budget is None or len(body) <= budget:
            return body
        return "%s\n... [%d of %d characters; text(None) for all of it]" % (
            body[:budget].rstrip(), budget, len(body))

    def interactive(self) -> bool:
        return _is_affordance(self._t)

    def read(self, budget: Optional[int] = -1) -> "Reading":
        """This subtree as markdown, with every affordance carrying its handle.

        `text()` gives the page's words and `acts()` gives the page's
        controls, and until now nothing gave both at once. A reader who saw
        `[ ] Search` in the text had to run a second listing and match it
        back by label -- which fails exactly where it matters, because a page
        with eight `( More )` buttons has eight identical labels and one of
        them is the one meant.

        So the marks go on the markdown itself. A line drawn from an
        affordance's address gets ` act(n)` appended, where n is that
        control's position in READING ORDER -- the same n `act(n)` takes,
        because both come from the same document-ordered walk. A sentence
        carrying three links gets three marks, since `_inline_flow` put three
        addresses on that one line and all three are still enactable.

        The markdown stays markdown: a handle is trailing text, so the
        structure, the heading levels and the control forms are untouched and
        the whole thing still round-trips. What it adds is the arrow back --
        a mark names a trie address, the address names an xpath, and the
        xpath names the element in the live document. That is the only path
        by which something read in the terminal can be pressed in the page.
        """
        if budget == -1:
            budget = _S.window * self.BUDGET_WINDOWS

        controls = self.acts()
        at = {}
        for n, node in enumerate(controls):
            at.setdefault(_canon(node.xpath), []).append(n)

        want = self.xpath
        lines, marked = [], set()
        for chunk in _S.rendered():
            for line in chunk.lines:
                if line.address is None:
                    continue
                if not _under(line.address.xpath, want):
                    continue
                hits = []
                for address in (line.address,) + tuple(line.inline):
                    for n in at.get(_canon(address.xpath), ()):
                        if n not in marked:
                            marked.add(n)
                            hits.append(n)
                text = line.text
                if hits:
                    text = "%s  %s" % (
                        text, " ".join("act(%d)" % n for n in hits))
                lines.append(text)

        # Controls the render never drew. Reported rather than dropped: a
        # count of what is missing is the difference between a reader who
        # knows to call `acts()` and one who believes the page has nothing
        # else on it.
        return Reading("\n".join(lines), len(controls),
                       len(marked), budget)

    def wire(self, width: int = 100) -> "Drawing":
        """This subtree drawn where the page puts it.

        The tree view answers "what is inside what"; this answers "what is
        beside what". Both are the same trie -- the drawing is built from the
        same rendered lines, positioned by geometry read from the page.
        """
        from ..wireframe import render_wireframe

        want = self.xpath
        drawn = []
        for chunk in _S.rendered():
            for line in chunk.lines:
                if line.address is None or not line.text.strip():
                    continue
                if _under(line.address.xpath, want):
                    drawn.append((line.address, line.text, line.address.tag))
        if not drawn:
            return Drawing(_EmptyFrame(), width)
        styles = _geometry(drawn)
        return Drawing(render_wireframe(drawn, styles, width=width), width)

    def acts(self, tag: Optional[str] = None) -> List["Node"]:
        """Everything below here that can be acted on, in document order.

        The answer to "find the search box on the page", and the reason it
        has to be complete: an earlier version stopped at fourteen and the
        page's only `<textarea>` -- which is what duckduckgo's search box is
        -- fell off the end, so the listing said there was nothing writable
        on a page with a search box in the middle of it. A truncated list
        that does not say it is truncated is a display telling a lie.

        Filter by tag to narrow it: `acts("textarea")`. By tag, because a tag
        is a fact; nothing here decides which control is *for* searching.
        """
        out: List[Node] = []
        # Pre-order, depth first. This walk used to be breadth first while
        # its docstring said document order, so on
        # `<a>one</a><div><a>two</a></div><a>four</a>` it listed `four`
        # second -- the last link on the page, offered as the second thing
        # under it. Nothing downstream could recover the real order, and
        # `act(n)` is a promise about position, so the promise was false for
        # every page whose controls sit at more than one depth.
        stack = list(reversed(_dom_children(self._t)))
        while stack:
            node = stack.pop()
            if _is_affordance(node) and (tag is None or _tag_of(node) == tag):
                out.append(Node(node))
            stack.extend(reversed(_dom_children(node)))
        _S.acts = out
        return out

    def act(self, n: int) -> "Node":
        """The nth thing from the last `acts()` listing, by position.

        A handle like `button(1)` is an ordinal *within its own parent*, so a
        flat list of affordances repeats it -- duckduckgo's front page shows
        five separate `button(1)`. Position in the listing is the only
        unambiguous way to name one of them, and `.where()` still gives the
        real address.
        """
        if not _S.acts:
            self.acts()
        return _S.acts[n]

    # -- acting ----------------------------------------------------------
    def _target(self) -> str:
        for address, value in _leaves_of(self._t):
            if (getattr(address, "accessor", "") or "").startswith("href"):
                return value
        return ""

    def press(self) -> "Node":
        """Press this, then read whatever the press produced.

        Scrolled into view first. A page that has not been scrolled to has
        most of its links outside the viewport, and Marionette refuses to
        click what it cannot reach: driving a real results page, the first
        candidate raised "could not be scrolled into view" and a caller got a
        stack trace where it wanted a page. The fold reads no layout, but an
        actuator has to -- the same split the scroller already makes.
        """
        _refuse_check(_label_of(self._t, 80), self._target())
        driver = _S.need_driver()
        node = driver.find_element("xpath", self.xpath)
        try:
            driver.execute_script(
                "arguments[0].scrollIntoView({block: 'center'});", node)
            _time.sleep(0.2)
        except Exception:           # noqa: BLE001 - a click may still work
            pass
        _S.clicked_via_href = False
        try:
            node.click()
        except Exception as exc:    # noqa: BLE001
            _S.clicked_via_href = True
            # Still unreachable: an overlay, a zero-sized anchor, a consent
            # wall. Say so, and follow the target if there is one, because a
            # link's job is its destination and the click was only the means.
            #
            # Resolved against the page first. Most hrefs on a real page are
            # relative -- `live_target.html`, `/topics/glaciers` -- and an
            # earlier version tested `startswith("http")` and re-raised on
            # every one of them, so the fallback worked only for the outbound
            # links that needed it least.
            from urllib.parse import urljoin

            target = urljoin(_S.url, self._target())
            if not target or target == _S.url:
                raise
            print("  (click blocked: %s; following the target instead)"
                  % type(exc).__name__)
            _refuse_check("", target)
            driver.get(target)
        _time.sleep(1.2)
        _S.refold()
        return Page()

    #: `input` types that accept typing. A radio or a checkbox is pressed,
    #: not written into, and a colour or a file picker is neither.
    _WRITABLE = frozenset({
        "", "text", "search", "email", "url", "tel", "number", "date",
        "datetime-local", "month", "week", "time",
    })

    def type(self, text: str) -> "Node":
        """Write into this node, if it is a thing that can be written into.

        Checked before the driver is asked. duckduckgo's first `<input>` in
        document order is `<input name="chip-select" type="radio">`, and
        sending it `clear()` produced a Marionette stack trace ending in
        "Unable to clear element that cannot be edited" -- true, and useless
        to anyone deciding what to do next. A caller is told what the element
        is and what to do with it instead.
        """
        driver = _S.need_driver()
        node = driver.find_element("xpath", self.xpath)
        kind = (node.get_attribute("type") or "").lower()
        if self.tag == "input" and kind == "password":
            raise Refused("a password field is never typed into")
        if self.tag not in ("input", "textarea") or (
                self.tag == "input" and kind not in self._WRITABLE):
            what = "%s type=%r" % (self.tag, kind) if kind else self.tag
            hint = " -- press it instead" if kind in ("radio", "checkbox",
                                                      "submit", "button") else ""
            raise TypeError("%s is not writable (%s)%s"
                            % (self.handle(), what, hint))
        _refuse_check(_label_of(self._t, 80), self._target())
        node.clear()
        node.send_keys(text)
        print("%s = %r" % (self.handle(), text))
        return self

    def enter(self) -> "Node":
        from selenium.webdriver.common.keys import Keys

        driver = _S.need_driver()
        driver.find_element("xpath", self.xpath).send_keys(Keys.RETURN)
        _time.sleep(1.5)
        _S.refold()
        return Page()

    def __lshift__(self, text: str) -> "Node":
        return self.type(text)

    def __call__(self, *args) -> "Node":
        if self.interactive() and self.tag != "input":
            return self.press()
        _S.cursor = self._t
        return self

    # -- display ---------------------------------------------------------
    def __repr__(self) -> str:
        kids = _dom_children(self._t)
        if not kids:
            body = self.text().strip()
            return body or "%s  (no content)" % self.handle()
        if self.xpath in ("/html", "/"):
            head = "Page(%r) - %d chunks" % (_S.url, _chunk_count())
        else:
            head = "%s - %d children" % (self.handle(), len(kids))
        lines = [head] + _tree_lines(kids)
        # What can be acted on, drawn apart from what can be read. This is the
        # half the TUI never separated, and the reason a reader could not tell
        # what any box was for.
        acts = self.acts()
        if acts:
            from collections import Counter

            tally = Counter(a.tag for a in acts)
            lines.append("act: %d - %s" % (
                len(acts),
                " ".join("%d%s" % (n, t) for t, n in sorted(tally.items()))))
            drawn = _drawn_at()
            for n, a in enumerate(acts[:6]):
                # The line the render drew for it, when there is one. A
                # listing that showed `act(1) a 'news'` for a link the page
                # labels "Hacker News" is naming links after their targets,
                # which is the one thing `_label_of` exists to avoid and
                # cannot do alone.
                shown = drawn.get(_canon(a.xpath)) or _label_of(a._t, 40)
                if len(shown) > 40:
                    shown = shown[:37] + "..."
                lines.append("  act(%d) %-9s %r" % (n, a.tag, shown))
            if len(acts) > 6:
                lines.append("  ... %d more; acts('textarea') to narrow"
                             % (len(acts) - 6))
        return "\n".join(lines)


def _chunk_count() -> int:
    return len(_S.rendered())


class Reading:
    """Markdown with its affordances marked, and the count of those it could not mark.

    A value rather than a string so the shortfall travels with the text.
    `str(reading)` is the markdown alone, for anything that wants to write it
    to a file or hand it to a model.
    """

    def __init__(self, body: str, controls: int, marked: int,
                 budget: Optional[int]) -> None:
        self.body = body
        self.controls = controls
        self.marked = marked
        self.budget = budget

    @property
    def unmarked(self) -> int:
        return self.controls - self.marked

    def __str__(self) -> str:
        return self.body

    def __len__(self) -> int:
        return len(self.body)

    def __repr__(self) -> str:
        body = self.body
        cut = ""
        if self.budget is not None and len(body) > self.budget:
            cut = ("\n... [%d of %d characters; read(None) for all of it]"
                   % (self.budget, len(body)))
            body = body[:self.budget].rstrip()
        note = "\n\n%d controls, %d marked" % (self.controls,
                                                   self.marked)
        if self.unmarked:
            note += ("; %d the render did not draw -- acts() reaches them"
                     % self.unmarked)
        return body + cut + note


class _EmptyFrame:
    """Nothing to draw: a node with no rendered text under it."""

    lines: list = []


class Drawing:
    """The page as its layout puts it, with every box still addressable.

    The tree says what contains what. This says what sits beside what, which
    is a different fact about the same page and the one the indented view
    cannot express: a sidebar reads as a column here and as a deep branch
    there, and only one of those is what a reader sees.

    Geometry is read from the page, once, at the moment of drawing -- never
    during the fold. `invariants.c2` holds the fold to reading no layout, and
    an actuator is exactly where that rule stops applying: the scroller makes
    the same crossing for the same reason.

    Addressable by row. `wire()[3]` is the nodes drawn on row 3, in the order
    they are drawn, so a box on the picture is a `Node` with everything a
    node has -- `.where()`, `.press()`, `.text()`.
    """

    def __init__(self, frame, width: int) -> None:
        self._frame = frame
        self.width = width

    @property
    def rows(self) -> List[str]:
        return [line.text for line in self._frame.lines]

    def __len__(self) -> int:
        return len(self._frame.lines)

    def __getitem__(self, row: int) -> List["Node"]:
        """The nodes drawn on one row, left to right."""
        line = self._frame.lines[row]
        out, seen = [], set()
        for address in line.addresses:
            owner = (address.xpath or "").split("/text()")[0]
            if owner in seen:
                continue
            seen.add(owner)
            found = _find_by_xpath(_page_root(_S.spine.trie), owner)
            if found is not None:
                out.append(Node(found))
        return out

    def acts(self) -> List["Node"]:
        """Everything on the drawing a reader can act on, row by row."""
        out = []
        for n in range(len(self)):
            out.extend(node for node in self[n] if node.interactive())
        _S.acts = out
        return out

    def __repr__(self) -> str:
        head = "%s  %d rows x %d cols" % (_S.url, len(self), self.width)
        body = []
        for n, line in enumerate(self._frame.lines):
            # The row number is the handle. `wire()[7]` is what is on row 7,
            # which is how a picture becomes something you can act on rather
            # than only look at.
            body.append("%3d| %s" % (n, line.text))
        return "\n".join([head, "=" * min(self.width + 5, 100)] + body)


def _geometry(drawn) -> object:
    """Layout for these addresses, measured once and kept for the fold.

    Reading a rect settles style, so it is done in one crossing for the whole
    page rather than per box, and only for addresses not already measured.
    """
    from ..style import StyleMap

    if _S.styles is None:
        _S.styles = StyleMap()
    sensor = _S.sensor
    if sensor is None:
        return _S.styles
    wanted = _S.styles.missing(a.xpath for a, _t, _k in drawn)
    if wanted:
        try:
            payload = sensor.styles(
                [type("A", (), {"xpath": x})() for x in wanted])
            _S.styles.absorb(wanted, payload)
        except Exception as exc:            # noqa: BLE001
            print("  (no geometry: %s: %s)" % (type(exc).__name__, exc))
    return _S.styles


def _tree_lines(kids: Sequence) -> List[str]:
    out = []
    for n, kid in enumerate(kids):
        stem = "'--" if n == len(kids) - 1 else "|--"
        handle = "%s(%d)" % (_tag_of(kid), _ordinal_of(kid))
        label = _label_of(kid)
        counts = _counts(kid)
        out.append("%s %-12s %-48s %s" % (
            stem, handle, '"%s"' % label if label else "", counts))
    return out


class _Tag:
    """A tag name, resolving against the cursor's children.

    `div(2)` is the second `div` among the current node's children, which is
    the xpath ordinal and therefore a slice of the address. `div("Protection")`
    finds the same node by the page's own words, for typing convenience.
    """

    def __init__(self, name: str) -> None:
        self._name = name
        self.__doc__ = (
            "Select a <%s> among the current node's children.\n\n"
            "    %s(1)          the first one, by xpath ordinal\n"
            "    %s(\"words\")    the one whose text starts with those words\n"
            % (name, name, name))

    def __call__(self, which=1) -> Node:
        if _S.cursor is None:
            raise RuntimeError("no page: call Page(url) first")
        kids = [k for k in _dom_children(_S.cursor)
                if _tag_of(k) == self._name]
        if not kids:
            raise LookupError("no <%s> among the children of %s"
                              % (self._name, getattr(_S.cursor, "segment", "?")))
        if isinstance(which, int):
            for kid in kids:
                if _ordinal_of(kid) == which:
                    return Node(kid)()
            raise LookupError("no %s(%d) here; found %s"
                              % (self._name, which,
                                 [_ordinal_of(k) for k in kids]))
        want = str(which).lower()
        for kid in kids:
            if _label_of(kid, 200).lower().startswith(want):
                return Node(kid)()
        raise LookupError("no <%s> here whose text starts %r"
                          % (self._name, which))

    def __repr__(self) -> str:
        return "<selector %s(n)>" % self._name


#: Tags that are Python keywords cannot be names. `del` is the only one.
_UNUSABLE = tuple(t for t in _TAGS if _keyword.iskeyword(t))

#: Tags that shadow a builtin when star-imported. This is deliberate -- the
#: sketch this came from writes `input(...)` for an `<input>` -- but a REPL
#: session that needs the builtin back can reach it through `builtins`.
SHADOWED = tuple(t for t in _TAGS if hasattr(__import__("builtins"), t))

for _name in _TAGS:
    if _name in _UNUSABLE:
        continue
    globals()[_name] = _Tag(_name)

__all__ = [n for n in __all__ if n not in _UNUSABLE] + ["SHADOWED"]


# --- the top-level verbs ------------------------------------------------------

_LOCATION = _re.compile(r"^(https?://|file://|www\.)|^[\w-]+(\.[\w-]+)+(/|$)")


def Page(what: Optional[str] = None):
    """The page: navigate to one, ask it a question, or show where you are.

    * `Page()` -- redraw the current node.
    * `Page("https://...")` -- visit, fold, and show the document.
    * `Page("some words")` -- rank this page's chunks against the words.

    Which of the last two you get is decided the way the one bar decides it
    (BROWSER_PIVOT section 4): it looks like a location, so it is one.
    """
    if what is None:
        if _S.cursor is None:
            return "no page: Page('https://...') to open one"
        return Node(_S.cursor)
    text = what.strip()
    if _LOCATION.search(text):
        url = text if "://" in text else "https://" + text.lstrip("/")
        _refuse_check("", url)
        driver = _S.need_driver()
        driver.get(url)
        _time.sleep(1.4)
        _S.fold(driver.current_url or url)
        return Node(_S.cursor)
    return _ask(text)


def _rank_str(rank: float) -> str:
    """PageRank as a multiple of the average chunk, not as a raw share.

    PageRank sums to one over the corpus, so a chunk's raw value is a
    function of how many chunks there are and not only of its standing. On
    256 chunks every hit printed `r0.00` at two decimals -- while the factor
    was ranking perfectly well, spread 0.0034 to 0.0097 across 21 distinct
    values. The number was alive and the display said it was dead, which is
    the same failure this project keeps finding in its own instruments.

    More decimals would only postpone it: at a hundred thousand chunks the
    mean is 1e-5 and any fixed width goes blank again. Dividing by the mean
    is scale-free, and it says the thing a reader wants: `x2.5` is two and a
    half times the standing of an average chunk, on a corpus of any size.
    """
    ranks = None
    if _S.workspace is not None:
        try:
            ranks = _S.workspace.index.ranks
        except Exception:           # noqa: BLE001
            ranks = None
    if ranks is None or not len(ranks):
        return "%.2f" % rank
    mean = float(ranks.mean()) or 1.0
    return "x%.1f" % (rank / mean)


def same_page(a: str, b: str) -> bool:
    """Are these two spellings the same document?

    `canonical_url` returns the EMPTY STRING for any scheme that is not http
    or https, which is deliberate -- it exists to make link targets match and
    a `file://` uri has no canonical http form. Comparing two canonicalised
    file uris therefore compares "" with "", which is true of every pair, and
    a "this page only" filter built on it silently returned hits from every
    page in the store.

    Worse than wrong: it would have worked on the live site and failed on
    every fixture, so it was broken exactly where the tests run.

    The rule here is `Workspace.page_url`'s: prefer the canonical form when
    there is one, fall back to the url as given when there is not.
    """
    from ..graphstore import canonical_url

    left, right = canonical_url(a), canonical_url(b)
    if left and right:
        return left == right
    return (a or "").split("#", 1)[0] == (b or "").split("#", 1)[0]


def _ask(query: str, *, everywhere: bool = False, k: int = 8):
    """Rank chunks by the triple product: pagerank, tf-idf, nomic.

    The same `ThreeFormIndex` the rest of the project retrieves through, over
    the same chunks the object tree shows -- because `Page(url)` ingests the
    fold it already has, rather than folding a second time for the index.

    Scoped to the current page unless `everywhere`, which is what `Browser`
    passes: the question is the same, the corpus is not.

    Without a workspace open there is nothing to rank against, and this says
    so rather than quietly falling back to counting shared words. A retrieval
    that is secretly a word count is the kind of thing this project spends
    its time discovering it had.
    """
    if _S.workspace is None:
        return ("no workspace: open one with workspace('build') to retrieve.\n"
                "  the index needs somewhere to keep frequency rows, "
                "embeddings and the graph")
    # Embed anything read but not yet vectorised.
    #
    # Here rather than in `_record`, because navigation should not pay for
    # retrieval that may never be asked for: `ingest_chunks` queues the
    # chunks and this is where the queue is worth draining. A page opened and
    # never questioned costs nothing.
    try:
        _S.workspace.flush_vectors()
    except Exception as exc:        # noqa: BLE001
        print("  (embedding failed: %s: %s)" % (type(exc).__name__, exc))

    hits = _S.workspace.search(query, k=k * 3)
    if not everywhere:
        hits = [h for h in hits if same_page(h.url, _S.url)]
    hits = hits[:k]
    if not hits:
        where_ = "anywhere in the store" if everywhere else "on this page"
        return "nothing %s matches %r" % (where_, query)

    out = ["%r - %d hits" % (query, len(hits))]
    for hit in hits:
        head = " ".join((hit.markdown or "").split())[:58] or hit.xpath[-58:]
        if everywhere:
            out.append("|-- %-58s  %s" % (head, hit.url[:34]))
        else:
            # The three factors, because a single score cannot say WHY: a hit
            # that is all pagerank and no text is a different answer from one
            # that is all text and no standing.
            out.append("|-- %-58s  r%s l%.2f s%.2f"
                       % (head, _rank_str(hit.rank), hit.lexical,
                          hit.semantic))
    return "\n".join(out)


def Browser(query: str, k: int = 8):
    """Ask the whole store, not just the page in front of you.

    Every trace ever folded into this workspace, ranked by the same triple
    product, with the url on each row because a hit from somewhere else is
    only useful if you can tell where it came from.
    """
    return _ask(query, everywhere=True, k=k)


def workspace(path: str = "build", *, semantic: bool = True):
    """Open a workspace, so folds are recorded and can be retrieved.

    Without one the session still browses -- the fold, the tree, the
    affordances all work -- but nothing is indexed and `Page(query)` has
    nothing to rank. With one, every page opened is written through the same
    path a scan uses, so what you read becomes what you can search.

    `semantic` loads the nomic embedder, and it is on by default because the
    ranking is a product of three factors and a missing one is not a smaller
    answer, it is a different one. `Workspace` takes `embedder=None` and then
    builds no embedding matrix at all, so every hit scored s0.00 and the
    "three-form" index was ranking on two.

    Say `semantic=False` to skip it deliberately -- it costs a model load and
    a few seconds -- and the sessions says which it got either way, because
    "s0.00 on every row" is not something a reader should have to notice.
    """
    from ..workspace import Workspace

    if _S.workspace is not None:
        try:
            _S.workspace.close()
        except Exception:           # noqa: BLE001
            pass

    embedder, note = None, "lexical + pagerank only (semantic=False)"
    if semantic:
        try:
            from ..core.embedding_service import get_default_service

            embedder = get_default_service()
            status = embedder.status()
            note = "semantic on: %s on %s" % (
                status.get("model", "?"), status.get("device", "?"))
        except Exception as exc:    # noqa: BLE001
            # Loud, not silent. A retrieval quietly missing a third of itself
            # is the failure this whole file keeps rediscovering.
            note = ("semantic UNAVAILABLE (%s: %s) -- ranking on two factors"
                    % (type(exc).__name__, str(exc)[:60]))

    _S.workspace = Workspace(path, context_window=_S.window, embedder=embedder)
    return "workspace open at %s (%s chunks)\n  %s" % (
        path, _S.workspace.stats().get("chunks", "?"), note)


def acts(tag: Optional[str] = None) -> List[Node]:
    """Everything actionable below the current node, in document order.

    At module level as well as on `Node`, because this is the answer to "what
    can I do here" and having to write `Node(cursor).acts()` to ask it is a
    worse question than the one being asked.

        acts()             everything
        acts("textarea")   narrowed by tag -- a tag is a fact
    """
    if _S.cursor is None:
        return []
    return Node(_S.cursor).acts(tag)


def act(n: int) -> Node:
    """The nth affordance from the last listing, by position.

    `button(1)` is an ordinal within its own parent, so a flat list repeats
    it: duckduckgo's front page shows five separate `button(1)`. Position is
    the only unambiguous handle across such a list.
    """
    if _S.cursor is None:
        raise RuntimeError("no page: call Page(url) first")
    return Node(_S.cursor).act(n)


def read(budget: Optional[int] = -1) -> Reading:
    """The markdown here, with its affordances marked. See `Node.read`.

    At module level for the same reason as `acts`: this is the answer to
    "what does this page say, and what can I press", and it should be
    askable without naming the cursor.
    """
    if _S.cursor is None:
        raise RuntimeError("no page: call Page(url) first")
    return Node(_S.cursor).read(budget)


def wire(width: int = 100) -> Drawing:
    """Draw the page where the page puts it, from the current node down.

    `wire()[7]` is the nodes on row 7, so a box in the picture is a `Node`:
    it can be pressed, read, or asked for its address. A drawing you can only
    look at is a screenshot.
    """
    if _S.cursor is None:
        raise RuntimeError("no page: call Page(url) first")
    return Node(_S.cursor).wire(width)


def up():
    """Ascend to the parent node."""
    if _S.cursor is None:
        return "no page"
    parent = getattr(_S.cursor, "parent", None)
    if parent is None:
        # The trie does not carry parent pointers; find it by xpath.
        here_path = getattr(_S.cursor, "_xpath_cache", "") or ""
        want = here_path.rsplit("/", 1)[0] or "/"
        found = _find_by_xpath(_page_root(_S.spine.trie), want)
        parent = found or _page_root(_S.spine.trie)
    _S.cursor = parent
    return Node(_S.cursor)


def _find_by_xpath(node, want: str):
    if (getattr(node, "_xpath_cache", "") or "") == want:
        return node
    for kid in _dom_children(node):
        got = _find_by_xpath(kid, want)
        if got is not None:
            return got
    return None


def top():
    """Back to the document node."""
    if _S.spine is None:
        return "no page"
    _S.cursor = _page_root(_S.spine.trie)
    return Node(_S.cursor)


def back():
    """The browser's back button, then re-fold what it landed on."""
    driver = _S.need_driver()
    driver.back()
    _time.sleep(1.2)
    _S.refold()
    return Node(_S.cursor)


def here() -> str:
    """The url and the node currently in focus."""
    if _S.cursor is None:
        return "no page"
    return "%s  %s" % (_S.url, getattr(_S.cursor, "_xpath_cache", "/"))


def where(node: Optional[Node] = None) -> str:
    """The address behind a node -- the real one, not the handle."""
    if node is not None:
        return node.where()
    return here()


def attach(*, headless: bool = True):
    """Open a browser. Called for you by `Page(url)` if you have not."""
    _S.attach(headless=headless)
    return "browser attached (%s)" % ("headless" if headless else "headful")


def close():
    """Give the browser back."""
    _S.close()
    return "closed"
