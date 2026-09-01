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

    >>> from domvec.live import *
    >>> Page("https://duckduckgo.com")
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
    "Page", "up", "top", "back", "here", "where", "attach", "close",
    "Refused", "Node",
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
        self.window = 1200

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
        self.cursor = _page_root(self.spine.trie)

    def refold(self) -> None:
        """After an enactment. The url may have changed under us."""
        driver = self.need_driver()
        try:
            now = driver.current_url
        except Exception:           # noqa: BLE001
            now = self.url
        self.fold(now)


_S = _Session()


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
        if real:
            # The first child carrying an xpath IS the document element.
            # Stopping one short of it made the cursor the url segment, so a
            # session opened onto a filename with one child under it.
            return real[0]
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


def _spoken_under(tnode) -> List[Tuple[object, str]]:
    """Every `text()` value in this subtree, in document order.

    Reader-facing text only. An `href`, a `title`, a `@control` annotation are
    all values the trie is right to hold and none of them is what the page
    shows in the place this node occupies.
    """
    out: List[Tuple[object, str]] = []

    def walk(node) -> None:
        mine = getattr(node, "_xpath_cache", None)
        for kid in node.ordered_children():
            if (getattr(kid, "_xpath_cache", None) or mine) != mine:
                walk(kid)                       # a DOM child
                continue
            if kid.is_leaf and (kid.value or "").strip():
                accessor = getattr(kid.address, "accessor", "") or ""
                if accessor.startswith("text()"):
                    out.append((kid.address, kid.value))
            else:
                walk(kid)                       # a taxonomy step

    walk(tnode)
    return out


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
    for _address, value in _spoken_under(tnode):
        value = " ".join((value or "").split())
        if value:
            parts.append(value)
        if sum(len(p) for p in parts) > width:
            break
    if not parts:
        for _address, value in _leaves_of(tnode):
            value = " ".join((value or "").split())
            if value:
                parts.append(value)
                break
    if not parts:
        return ""
    text = " ".join(parts)
    return text if len(text) <= width else text[:width - 3] + "..."


def _counts(tnode) -> str:
    """What is inside, counted by tag. Counted, not interpreted."""
    from collections import Counter

    seen = Counter()
    stack = list(_dom_children(tnode))
    while stack:
        node = stack.pop()
        tag = _tag_of(node)
        if tag in ("a", "input", "button", "img", "select", "textarea", "li"):
            seen[tag] += 1
        stack.extend(_dom_children(node))
    return " ".join("%d%s" % (n, t) for t, n in sorted(seen.items())
                    if n) or ""


_INTERACTIVE = {"a", "button", "input", "select", "textarea", "option",
                "summary", "label"}


class Node:
    """One node of the trie, and of the page.

    Calling a container focuses it and shows its children. Calling an
    affordance -- `a`, `button`, `input` -- acts on the page, after the
    refusal check.

        node()          focus, or press
        node << "text"  type into it
        node.text()     the full markdown of its subtree
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

    def text(self) -> str:
        """This subtree as markdown, through the one renderer everything uses."""
        from ..markdown import render_trie

        want = self.xpath
        lines = []
        for chunk in render_trie(_S.spine.trie, context_window=_S.window):
            for line in chunk.lines:
                if line.address is None:
                    continue
                if line.address.xpath.startswith(want):
                    lines.append(line.text)
        return "\n".join(lines)

    def interactive(self) -> bool:
        return self.tag in _INTERACTIVE

    # -- acting ----------------------------------------------------------
    def _target(self) -> str:
        for address, value in _leaves_of(self._t):
            if (getattr(address, "accessor", "") or "").startswith("href"):
                return value
        return ""

    def press(self) -> "Node":
        _refuse_check(_label_of(self._t, 80), self._target())
        driver = _S.need_driver()
        node = driver.find_element("xpath", self.xpath)
        node.click()
        _time.sleep(1.2)
        _S.refold()
        return Page()

    def type(self, text: str) -> "Node":
        _refuse_check(_label_of(self._t, 80), self._target())
        driver = _S.need_driver()
        node = driver.find_element("xpath", self.xpath)
        node.clear()
        node.send_keys(text)
        print('%s = %r' % (self.handle(), text))
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
        return "\n".join([head] + _tree_lines(kids))


def _chunk_count() -> int:
    from ..markdown import render_trie

    if _S.spine is None:
        return 0
    return len(render_trie(_S.spine.trie, context_window=_S.window))


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


def _ask(query: str):
    """Rank this page's chunks against a question.

    Scored on token overlap for now, over the same chunks the renderer
    produces. The three-form index -- pagerank times tfidf times nomic -- is
    what this becomes; it needs a workspace open, and wiring that in is the
    next slice rather than a thing to fake here.
    """
    from ..markdown import render_trie

    want = {w for w in _re.split(r"\W+", query.lower()) if len(w) > 2}
    scored = []
    for chunk in render_trie(_S.spine.trie, context_window=_S.window):
        body = chunk.markdown
        have = {w for w in _re.split(r"\W+", body.lower()) if len(w) > 2}
        hit = len(want & have)
        if hit:
            scored.append((hit, chunk))
    scored.sort(key=lambda pair: -pair[0])
    if not scored:
        return "no chunk on this page matches %r" % query
    out = ["%r - %d chunks match" % (query, len(scored))]
    for hit, chunk in scored[:8]:
        head = " ".join(chunk.markdown.split())[:66]
        out.append("|-- %-3d %s" % (hit, head))
    return "\n".join(out)


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
