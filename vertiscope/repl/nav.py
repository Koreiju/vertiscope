"""Web navigation driven by the address.

Every widget on screen carries a :class:`~vertiscope.address.ContentAddress`, and
the address holds the element's **absolute xpath**. So acting on what the user
clicked needs no separate element registry, no CSS selector generation and no
text matching: the xpath is already the handle, and it is the same string the
trie is keyed on.

This is the payoff of storing the absolute form rather than the generalized
one. A generalized pattern identifies a *class* of elements and would need a
disambiguating index to click one of them; the absolute path identifies
exactly one node.

Every action returns a :class:`NavResult` rather than raising, because the
failure modes here are ordinary — an element scrolled out of the DOM, a page
that navigated under us, a stale handle — and a REPL that dies on a stale
click is unusable. The failure is reported into the status line instead.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import List, Optional, Tuple

from ..address import ContentAddress

__all__ = ["NavResult", "WebNav"]


@dataclass
class NavResult:
    ok: bool
    action: str
    detail: str = ""
    url: str = ""

    def __str__(self) -> str:
        mark = "ok" if self.ok else "!!"
        return f"[{mark}] {self.action}{': ' + self.detail if self.detail else ''}"


class WebNav:
    """Functional navigation actions over a Selenium driver.

    The driver is injected rather than created here so the REPL can run
    against a live browser, a stub, or nothing at all — offline browsing of an
    already-scanned page is the common case, and it must not require a
    browser to be running.
    """

    def __init__(self, driver=None) -> None:
        self.driver = driver

    @property
    def live(self) -> bool:
        return self.driver is not None

    @property
    def current_url(self) -> str:
        if not self.live:
            return ""
        try:
            return self.driver.current_url
        except Exception:
            return ""

    # -- element resolution ------------------------------------------------
    def _find(self, xpath: str):
        from selenium.webdriver.common.by import By

        return self.driver.find_element(By.XPATH, xpath)

    def _guard(self, action: str) -> Optional[NavResult]:
        if not self.live:
            return NavResult(False, action, "no browser attached")
        return None

    # -- actions -----------------------------------------------------------
    def visit(self, url: str) -> NavResult:
        blocked = self._guard("visit")
        if blocked:
            return blocked
        try:
            self.driver.get(url)
            return NavResult(True, "visit", url, url=self.current_url)
        except Exception as exc:
            return NavResult(False, "visit", f"{type(exc).__name__}: {exc}")

    def click(self, address: ContentAddress) -> NavResult:
        """Removed. Enactment lives in the page.

        This used to find the element with `find_element(By.XPATH, ...)` and
        call Selenium's `click`, which cannot see inside a shadow root: the
        selector engine stops at the boundary, so every control in a custom
        element was unreachable from here. Typing had the same ceiling.

        `Sensor.perform` replaces both. It resolves the target through the
        composed tree, where a shadow boundary is one more step rather than a
        wall, and dispatches with `composed: true` so a host-level listener
        actually receives the event. Keeping this alongside it would leave two
        dispatchers with different reach, and the one with less reach would be
        the one that quietly answered first.
        """
        return NavResult(False, "click",
                         "enactment moved to Sensor.perform (stage 5)")

    def type_into(self, address: ContentAddress, text: str,
                  *, submit: bool = False) -> NavResult:
        """Removed. See :meth:`click`."""
        return NavResult(False, "type",
                         "enactment moved to Sensor.perform (stage 5)")

    def scroll(self, amount: int = 600) -> NavResult:
        """Scroll the page. The signal that drives incremental re-scan."""
        blocked = self._guard("scroll")
        if blocked:
            return blocked
        try:
            self.driver.execute_script("window.scrollBy(0, arguments[0]);", amount)
            return NavResult(True, "scroll", str(amount), url=self.current_url)
        except Exception as exc:
            return NavResult(False, "scroll", f"{type(exc).__name__}: {exc}")

    def back(self) -> NavResult:
        blocked = self._guard("back")
        if blocked:
            return blocked
        try:
            self.driver.back()
            return NavResult(True, "back", url=self.current_url)
        except Exception as exc:
            return NavResult(False, "back", f"{type(exc).__name__}: {exc}")

    def html(self) -> str:
        """The settled DOM, for re-running the pipeline after an action."""
        if not self.live:
            return ""
        try:
            from ..capture import deep_serialize

            return deep_serialize(self.driver).html
        except Exception:
            try:
                return self.driver.page_source
            except Exception:
                return ""


# --- reading roles off the addresses ---------------------------------------
#
# Pagination, menus and filters are not new content categories — inventing one
# would be the special-cased-card-type anti-pattern. They are *readings* of the
# interactive addresses already present, and they live here rather than in the
# extractor so a bad guess costs a mislabelled REPL command and nothing more.

# Labels that are a pager control and nothing else. Matched against the whole
# label after stripping punctuation, because these words are far too common
# inside prose to match as substrings: "more" is "Read more" on every blog in
# the corpus, and "next" is a substring of `/_next/static/chunks/...`, which is
# how a Next.js page came to report eighty-four stylesheets as pagination.
_PAGER_EXACT = frozenset({
    "next", "prev", "previous", "older", "newer",
    "next page", "previous page", "prev page", "older posts", "newer posts",
    "»", "«", "›", "‹", "→", "←", ">>", "<<",
})

# Words that are a pager on some sites and ordinary navigation on others.
# Hacker News's pager is literally "More"; Associated Press's "MORE" is a
# section dropdown, and no amount of reading the label separates them. These
# fire only when the *target* also looks like paging — which is what the two
# readings are for.
_PAGER_AMBIGUOUS = frozenset({
    "more", "all", "first", "last", "back", "forward",
    "load more", "show more", "see more",
})

# Phrases where a direction word and a unit word appear together. Requiring
# both is what separates "next page" from "the next generation of tooling".
#
# `page` belongs in the unit set and NOT the direction set. Having it in both
# made every label containing the word satisfy "a direction word and a unit
# word" on its own, so "home page" classified as pagination — seen on a live
# page, three times, before the rule had been used in anger.
_PAGER_DIRECTION = frozenset({"next", "previous", "prev", "older", "newer"})
_PAGER_UNIT = frozenset({"page", "pages", "posts", "results", "entries",
                         "items", "articles", "comments"})

# Whole labels, not substrings, and short ones. As a substring search over the
# joined context these matched a news headline ("Todd Blanche is **narrow**ly
# confirmed…", 25 addresses) and a Go struct's doc comment (134). One word in
# one paragraph labelled every address that paragraph covered.
_FILTER_LEADS = frozenset({
    "filter", "filters", "sort", "refine", "narrow", "facet", "facets",
    "order",
})
# A filter control names its action first — "Filter by category", "Sort by
# price", "Refine search". Requiring the *leading* word rather than any word
# is what admits those while rejecting the prose that a substring search
# caught: "**narrowly** confirmed as attorney general" leads with a name, and
# "**filtering** out the noise" is not the word `filter`.
_FILTER_MAX_WORDS = 5
_SEARCH_WORDS = frozenset({"search", "query", "find", "keyword", "keywords"})

_PUNCT = " \t\r\n.,:;!?()[]{}'\"·|—–-"
# Arrows travel *with* a pager label as often as they stand alone: "Next →",
# "« Previous", "›". Stripped only after the whole-label check, so a bare arrow
# is still recognised rather than reduced to the empty string.
_ARROWS = "»«›‹→←⇒⇐<>"


def _words(text: str) -> set:
    """Alphanumeric runs. Word boundaries, without a regex."""
    out, word = set(), []
    for ch in text.lower():
        if ch.isalnum():
            word.append(ch)
        elif word:
            out.add("".join(word))
            word = []
    if word:
        out.add("".join(word))
    return out


# Pager rows arrive as one string. The extractor gives an element's text to the
# deepest element containing *all* of it, so a control's own words are often
# glued to its neighbours': reddit's next link reads "view more: next ›" and
# arxiv's page-size row reads "Showing up to 50 entries per page: fewer | more
# | all". Splitting on the separators such rows are built from recovers the
# individual controls without loosening the whole-label rule into a substring
# search.
_SEPARATORS = "|·:•/•"
_MAX_ROW = 120


def _is_pager(text: str) -> bool:
    stripped = text.strip(_PUNCT).lower()
    if not stripped or len(stripped) > _MAX_ROW:
        return False
    if _fragment_is_pager(stripped):
        return True
    if len(stripped) <= _MAX_ROW:
        for sep in _SEPARATORS:
            stripped = stripped.replace(sep, "\x00")
        if any(_fragment_is_pager(part) for part in stripped.split("\x00")):
            return True
    return False


def _fragment_is_pager(text: str) -> bool:
    text = text.strip(_PUNCT)
    if not text or len(text) > 40:
        return False
    if text in _PAGER_EXACT:
        return True
    core = text.strip(_ARROWS + _PUNCT)
    if core and core in _PAGER_EXACT:
        return True
    words = _words(text)
    if words & _PAGER_DIRECTION and words & _PAGER_UNIT:
        return True
    # "page 2", "next 30" — a paging word beside a number. "home page" has no
    # number and is correctly not a pager.
    if any(w.isdigit() for w in words):
        return bool(words & _PAGER_DIRECTION) or "page" in words
    return False


def _matches_whole_label(text: str, vocabulary) -> bool:
    """Whether the label, or one of the controls in a row, is in the set."""
    stripped = text.strip(_PUNCT).lower()
    if not stripped or len(stripped) > _MAX_ROW:
        return False
    if stripped in vocabulary:
        return True
    for sep in _SEPARATORS:
        stripped = stripped.replace(sep, "\x00")
    return any(part.strip(_ARROWS + _PUNCT) in vocabulary
               for part in stripped.split("\x00"))


def _is_ambiguous_pager(text: str) -> bool:
    """A label that is a pager on some sites and a menu item on others."""
    return _matches_whole_label(text, _PAGER_AMBIGUOUS)


def _is_filter(text: str) -> bool:
    """A short label whose first word names the action."""
    stripped = text.strip(_PUNCT).lower()
    if not stripped or len(stripped) > _MAX_ROW:
        return False
    for sep in _SEPARATORS:
        stripped = stripped.replace(sep, "\x00")
    for part in stripped.split("\x00"):
        part = part.strip(_ARROWS + _PUNCT)
        if not part or len(part) > 40:
            continue
        words = part.split()
        if (words and words[0].strip(_PUNCT) in _FILTER_LEADS
                and len(words) <= _FILTER_MAX_WORDS):
            return True
    return False


# Query parameters that mean "a different slice of the same listing". This is
# the structural half of the reading, and it is the half that survives a page
# whose pager has no words at all — arxiv's is "1-50  51-100  101-104", where
# every label is a number and only the target says what the links do.
#
# `p` is deliberately absent: `?p=123` is a WordPress permalink at least as
# often as it is page three. `count` likewise. Both of those pagers are caught
# by their labels instead, so including the ambiguous parameter would buy
# nothing and cost precision.
_PAGING_PARAMS = frozenset({
    "page", "paged", "pagenum", "pageno", "page_number", "pagenumber",
    "skip", "offset", "start", "after", "before", "cursor",
})

# Admitted only alongside an ambiguous *label* (see `_is_paging_target`).
_LOOSE_PAGING_PARAMS = frozenset({"p", "pg", "count", "n"})


#: `[words](target)` as the render now draws a link that has both.
_RENDERED_LINK = re.compile(r"^\[(?P<words>[^\]]*)\]\((?P<target>[^)]*)\)$")


def _split_rendered(label: str) -> Tuple[str, str]:
    """A drawn line -> (the words a reader sees, the target it points at).

    Three shapes reach the classifier and each answers differently:

        `[1-50](/list?skip=0)`  ->  ("1-50", "/list?skip=0")
        `<https://x/page/2>`    ->  ("",     "https://x/page/2")
        `Next page`             ->  ("Next page", "")

    The middle one is a target with no words -- returning it as a name is how
    a Next.js page came to report eighty-four stylesheets by their urls.
    """
    text = (label or "").strip()
    hit = _RENDERED_LINK.match(text)
    if hit:
        return hit.group("words").strip(), hit.group("target").strip()
    if text.startswith("<") and text.endswith(">"):
        return "", text[1:-1].strip()
    return text, ""


def _is_paging_target(url: str, base: str = "", *, loose: bool = False) -> bool:
    """Whether a link's target is the same listing at a different position.

    **Same listing** is the load-bearing half, and it was missing. Hacker
    News's "past" links go to `hn.algolia.com/?query=…&page=0` — a paging
    parameter, on somebody else's search results — so thirty-two story rows
    on one page classified as pagination. A parameter check alone asks "does
    this url page something", which is not the question.

    So the query-parameter reading requires the target to resolve to the same
    host *and* path as the page it was found on. The path-shaped reading
    (`/page/2/`, `/catalogue/page-2.html`) does not: it is specific enough on
    its own, and it is exactly the case where the path legitimately differs.

    ``loose`` admits the short ambiguous parameters (`p`, `pg`, `count`).
    They are not enough on their own — `?p=123` is a WordPress permalink at
    least as often as page 123 — but combined with a label like "More" they
    are what separates Hacker News's own pager from a nav dropdown spelled
    the same way.
    """
    from urllib.parse import parse_qs, urljoin, urlsplit

    url = (url or "").strip("<>")
    if not url or url.startswith(("javascript:", "mailto:", "#")):
        return False
    try:
        resolved = urljoin(base, url) if base else url
        parts = urlsplit(resolved)
    except ValueError:
        return False

    params = set(parse_qs(parts.query))
    if params & _PAGING_PARAMS or (loose and params & _LOOSE_PAGING_PARAMS):
        if not base:
            return True
        here = urlsplit(base)
        if (parts.netloc, parts.path.rstrip("/")) == (here.netloc,
                                                      here.path.rstrip("/")):
            return True
    # `/page/2/`, `/page-2.html` — the path-shaped spelling.
    #
    # The digits must be the whole segment. Without that boundary, `/p/` plus
    # anything starting with a number matched, and Substack's permalinks are
    # `/p/25-years-of-blogitude` — a story link on Hacker News classified as
    # pagination. `/p/` is gone entirely for the same reason: as a *path* it
    # is far more often "post" than "page", and `?p=N` is already covered,
    # ambiguously and deliberately, by the loose parameter set.
    path = parts.path.lower()
    for marker in ("/page/", "/page-", "/pagina/", "/seite/"):
        cut = path.find(marker)
        if cut < 0:
            continue
        tail = path[cut + len(marker):]
        digits = ""
        for ch in tail:
            if ch.isdigit():
                digits += ch
            else:
                break
        rest = tail[len(digits):]
        if digits and (not rest or rest[0] in "/.?#"):
            return True
    return False


def _ancestors(xpath: str, levels: int):
    """`xpath` and its ancestors, nearest first."""
    yield xpath
    for _ in range(levels):
        cut = xpath.rfind("/")
        if cut <= 0:
            return
        xpath = xpath[:cut]
        yield xpath


def attach_context(interactive, texts, *, levels: int = 3):
    """Give each interactive entry the visible text that labels it.

    An anchor's visible text is usually **not** attributed to the anchor. The
    extractor gives an element's text to the deepest element containing it, so

        <li class="next"><a href="/page/2/">Next &rarr;</a></li>

    yields ``text.visible`` at the ``li`` carrying "Next →" and
    ``urls.internal`` at the ``a`` carrying "/page/2/". They are a label and a
    target one level apart, and the classifier used to be handed only the
    second — so its input for every link on every page was a URL, while the
    words it looks for are words that appear in prose and not in hrefs. Every
    pager in the corpus read as an ordinary link.

    Preference is self, then descendant, then ancestor: text on the element is
    its own label, text below it is inside it, and text above it is the
    smallest enclosing thing that says what it is. The ancestor walk is capped
    because far enough up every element is inside ``<body>`` and would inherit
    the page's first paragraph.

    Returns ``(address, label, context)`` triples.
    """
    exact: dict = {}
    covering: dict = {}
    for xpath, text in texts:
        text = (text or "").strip()
        if not text:
            continue
        exact.setdefault(xpath, text)
        for prefix in _ancestors(xpath, levels):
            covering.setdefault(prefix, text)

    out = []
    for address, label in interactive:
        xpath = address.xpath
        context = covering.get(xpath, "")
        if not context:
            for ancestor in _ancestors(xpath, levels):
                if ancestor in exact:
                    context = exact[ancestor]
                    break
        out.append((address, label, context))
    return out


def classify_controls(entries) -> dict:
    """Group interactive addresses into the roles the REPL offers by name.

    ``entries`` are ``(address, label)`` pairs or ``(address, label, context)``
    triples; :func:`attach_context` builds the third element. Without it a
    link's label is its href, which is why this reads the context first and
    the label only as a fallback.

    Each bucket holds ``(address, label, context)``, so a caller can show the
    control by the name a reader would recognise rather than by its href.
    """
    roles = {"pagination": [], "menu": [], "filter": [], "search": [],
             "other": []}
    for entry in entries:
        address, label = entry[0], entry[1]
        context = entry[2] if len(entry) > 2 else ""
        row = (address, label, context)
        # An href is a target, not a name -- and a line can now carry both.
        #
        # A link used to reach here in one of two shapes: `<target>` when it
        # had no words the fold could see, or its words alone. So `label` was
        # read as the target whenever it looked like a url, and as a name
        # otherwise. Once `content_tagger` began carrying an anchor's own
        # words on its `interactive.links` detection, a third shape arrived --
        # `[1-50](/list?skip=0&show=50)` -- which is neither: it starts with
        # `[`, so it was taken as a NAME, and the paging test that needed the
        # href stopped seeing one. A numeric pager classified as nothing.
        #
        # Splitting the rendered form is strictly better than either branch:
        # the words become the name and the target stays the target, so a
        # pager identified only by its href is still found and now has a
        # label to show for it.
        words_of, target_of = _split_rendered(label or "")
        shown = context or words_of
        label = target_of or label
        text = shown.lower()
        target = address.xpath.lower()
        words = _words(text)
        accessor = (address.accessor or "").lower()

        # Two readings. Either is sufficient on its own for an unambiguous
        # label or a paging-shaped target; a label that is a pager on some
        # sites and a menu item on others needs both.
        links = address.category == "urls"
        here = address.url
        if (_is_pager(shown)
                or (links and _is_paging_target(label, here))
                or (links and _is_ambiguous_pager(shown)
                    and _is_paging_target(label, here, loose=True))):
            roles["pagination"].append(row)
        elif address.tag == "interactive.inputs" and (
                words & _SEARCH_WORDS
                or any(w in target for w in ("search", "query"))
                or any(w in accessor for w in ("search", "query"))):
            roles["search"].append(row)
        elif _is_filter(shown):
            roles["filter"].append(row)
        elif "/nav" in target or "menu" in target or "menu" in words:
            roles["menu"].append(row)
        else:
            roles["other"].append(row)
    for name in roles:
        if name != "other":
            roles[name] = _collapse_nested(roles[name])
    return roles


def _collapse_nested(rows):
    """One control, once — not once per address inside it.

    A link is several addresses: the anchor's own detection, its `<picture>`,
    its `<img>`, each `srcset` candidate. They share a label and nest inside
    one another, so a nav bar listed the same item eight times and Associated
    Press's front page reported **807 menu items**, which is not an answer
    anyone can use.

    Keeps the outermost of any run sharing a label, since that is the element
    a click should land on. Only the named roles are collapsed; `other` is a
    remainder, not a listing, and nothing reads it.
    """
    kept = []
    for address, label, context in rows:
        name = (context or label or "").strip()
        for i, (prev, plabel, pcontext) in enumerate(kept):
            if (pcontext or plabel or "").strip() != name:
                continue
            if address.xpath.startswith(prev.xpath + "/"):
                break                       # inside one already kept
            if prev.xpath.startswith(address.xpath + "/"):
                kept[i] = (address, label, context)   # this one is the parent
                break
        else:
            kept.append((address, label, context))
    return kept
