"""The chunk as slim HTML: the same distillation, with its widgets intact.

The vault has always had the markdown form. Markdown has no controls, so the
surface *reconstructed* them -- it read `( Add to basket )` off a line and drew
a `<button>` whose label was that text with the parentheses taken back off.
That works, and it is a reconstruction: the button exists because a regex
matched a rendering, not because the page had one.

This is the other form the goal asks for -- "a more pure html extension to
render original web content directly but still in distilled, organized, and
slim minimal-html chunks, where we can keep the interactive and the static/
media asset components". An `<input>` is an `<input>` here because the trie
says the element at that xpath is a control, and the element carries its own
address in `data-vertiscope-address`, so pressing it names the thing the sensor
found rather than the thing the render drew.

**Both forms are the same distillation.** This is not a second extractor: it
reads the very payload the markdown surface reads, line for line, address for
address, so a chunk cannot say one thing in one form and something else in the
other. What differs is only what a line becomes -- a string, or an element.

### Slim, and what that costs

Every wrapper the page used to centre a header is gone; nesting survives as
one `<div class="dv-n">` per level of the distilled tree, which is the depth
the markdown indents by. Classes are a fixed private vocabulary, not the
page's. No stylesheet, no script, no layout: the point is to keep the
*interface* -- headings, lists, links, fields, buttons, media -- not the
design.

### Untrusted by construction

The content is scraped from the open web and this HTML is inserted into a note
in the reader's own app, where Obsidian's code-block processor hands it a
real, unsanitised DOM. So nothing here is passed through: every text node is
escaped, the tag set is a closed whitelist, no attribute is copied from the
page, and `_safe_url` refuses every scheme but http/https/mailto and
site-relative paths -- which is what keeps a page's `javascript:` href from
becoming a link the reader can click inside their own vault.
"""

from __future__ import annotations

import html as _html
import re
from typing import Dict, List, Optional, Tuple

#: The render's own marks, as `markdown.py` draws them. Order matters: a
#: control inside a heading arrives as `##### ( Products )`, so the heading
#: comes off first and every test below stays a test of a LEADING mark. The
#: markdown surface strips the same marks in the same order for the same
#: reason; the trap is recorded in `surface.ts::words`.
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_MEDIA = re.compile(r"^!\[([^\]]*)\]\(((?:[^()\s]|\((?:[^()\s]|\([^()\s]*\))*\))*)\)\s*(.*)$")
#: The placeholder form: a picture the distiller found and could not locate.
#: `markdown.py` emits it deliberately -- see the comment on the `cat ==
#: "media"` branch, which stopped inventing a target rather than dropping the
#: line -- so a form that only matched `![alt](src)` sent every one of them
#: down the prose path and drew a picture as a sentence.
_MEDIA_BARE = re.compile(r"^!\[([^\]]*)\](?!\()\s*(.*)$")
_LINK = re.compile(r"^\[([^\]]*)\]\(((?:[^()\s]|\((?:[^()\s]|\([^()\s]*\))*\))*)\)\s*(.*)$")
_BARE_URL = re.compile(r"^<([^>\s]+)>$")
_FORM = re.compile(r"^===\s*(.*?)\s*===$")
_BUTTON = re.compile(r"^\(\s*(.*?)\s*\)$")
_FIELD = re.compile(r"^\[([ xX]?)\]\s*(.*)$")
_BULLET = re.compile(r"^[-*]\s+(.*)$")

#: Schemes a distilled link may carry. Anything else -- `javascript:`,
#: `data:`, `vbscript:`, a scheme nobody has thought of yet -- is dropped and
#: the words are kept as plain text, so the reader still sees what the page
#: said without being handed something to click.
_SAFE_SCHEMES = ("http://", "https://", "mailto:")

#: Drawn where a picture would be when there is no source, or the reader has
#: media switched off. A named constant because it is the one glyph in here.
_NO_IMAGE = "▣"


def _safe_url(raw: str) -> str:
    """``raw`` if it is safe to put in an href, else empty.

    Relative paths pass, because a path cannot carry a scheme; `_absolute`
    resolves them against the page afterwards. A value with a colon before its
    first slash is treated as scheme-bearing and has to be on the list --
    deliberately stricter than parsing, because the parsers are where the
    bypasses live.

    This runs BEFORE `_absolute`, and the order is the point: joining a value
    against a base and *then* asking whether it is safe is how a sanitiser
    gets walked past.
    """
    value = (raw or "").strip()
    if not value:
        return ""
    # Control characters first: `java&#9;script:` is a scheme to some parsers
    # and not a scheme to a naive prefix test.
    value = "".join(ch for ch in value if ord(ch) >= 0x20 and ch != "\x7f")
    lowered = value.lower()
    if lowered.startswith(_SAFE_SCHEMES):
        return value
    if lowered.startswith("//"):        # protocol-relative; inherits ours
        return value
    head = lowered.split("/")[0].split("?")[0].split("#")[0]
    if ":" in head:
        return ""
    return value


def _absolute(url: str, base: str) -> str:
    """``url`` resolved against the chunk's own page.

    The distiller writes what the page wrote, which is usually relative:
    `user_avatar/discourse.julialang.org/tamas_papp/25/25949_2.png`. Resolved
    by the surface instead of here, that base is whatever document the surface
    lives in -- and in Obsidian that is `app://obsidian.md`, so every relative
    picture in a note asked the *app* for a file it does not have. Verified in
    the running app: 1 of 11 images loaded, the ten failures all pointing at
    `app://obsidian.md/...`.

    Done here because this is where the page's url is in hand.
    `layout._first_image` absolutises for the same reason and against the same
    base, so a node's billboard and the picture inside its chunk are the same
    file.
    """
    if not url or not base:
        return url
    if url.lower().startswith(("http://", "https://", "mailto:")):
        return url
    try:
        from urllib.parse import urljoin

        return urljoin(base, url)
    except Exception:                                   # noqa: BLE001
        return url


def _esc(text: str) -> str:
    return _html.escape(text or "", quote=True)


def _attrs(pairs: List[Tuple[str, str]]) -> str:
    return "".join(' %s="%s"' % (k, _esc(v)) for k, v in pairs if v)


class _Builder:
    """Accumulates elements as a TREE, keeping the nesting stack honest.

    The depth comes from the line's own indentation, which `_reflow` has
    already mapped onto one step per nesting LEVEL. A level that jumps by more
    than one opens the levels between it rather than nesting straight through,
    so the output is well formed however the page nested.

    A tree rather than a flat string of open and close tags, because a group
    cannot be classified until its contents are known. The goal asks to keep
    the page's structures "localized enough still such that we can render them
    as their intended cohesive structures" -- a product card is a picture and
    a title and a price and a button that belong together, and drawing them as
    four stacked lines loses the one thing the layout was saying. Deciding
    that needs the whole group, and a string builder has already emitted the
    opening tag by then.
    """

    def __init__(self) -> None:
        self.root: List = []
        self.stack: List[List] = [self.root]

    @property
    def depth(self) -> int:
        return len(self.stack) - 1

    def at(self, depth: int) -> None:
        while self.depth < depth:
            group: List = []
            self.stack[-1].append(group)
            self.stack.append(group)
        while self.depth > depth:
            self.stack.pop()

    def add(self, markup: str) -> None:
        self.stack[-1].append(markup)

    def close(self) -> str:
        """The chunk, with the whole of it drawn as a card when it is one.

        The record rule made a chunk a single record -- one search result, one
        product, one row -- so the thing a card should be drawn around is
        usually the chunk itself, and there is no group wrapping it to hang
        that on. Asked here instead, of the root.
        """
        root = _collapse(self.root)
        if _is_card(root):
            return '<div class="dv-n dv-card">%s</div>' % "".join(
                _serialise(node, True) for node in root)
        return "".join(_serialise(node) for node in root)


def _collapse(nodes: List) -> List:
    """Drop wrappers that hold one group and nothing else.

    A page nests five divs to centre a header, and every one of those levels
    arrives here as a group that costs a border, an indent and a margin while
    saying nothing: a wrapper with a single child expresses no branching, so
    the indent it draws stands for a distinction that does not exist.

    `markdown.py::_level_page` already does exactly this on the markdown side
    -- "a chain of five wrappers costs one step instead of five" -- and the
    HTML form was not doing it, which is most of why the panel read as loose.
    Nesting RELATIONSHIPS all survive: deeper stays deeper, siblings stay
    level; what goes is a chain with nothing to tell apart.
    """
    out: List = []
    for node in nodes:
        if not isinstance(node, list):
            out.append(node)
            continue
        inner = _collapse(node)
        # Unwrap as long as this level holds exactly ONE thing, whatever that
        # thing is. `while`, not `if`: a chain of five collapses in one pass.
        #
        # It used to unwrap only when the single child was another group,
        # which left a wrapper around a lone element standing -- and that
        # wrapper does more than draw a needless border. It puts the element
        # in a group of its own, so a product card's picture was a sibling of
        # nothing while its title and price sat in the group next door, and
        # `_is_card` saw one figure with no words beside it. The card stopped
        # forming, and the grid that puts the picture in the left column
        # cannot reach a figure that is not a direct child.
        while len(inner) == 1:
            if isinstance(inner[0], list):
                inner = inner[0]
                continue
            out.extend(inner)         # a lone element belongs to its parent
            inner = None
            break
        if inner is not None:
            out.append(inner)
    return out


#: What a group needs before it is drawn as a card rather than as a stack.
#: A picture and something to say about it -- which is what a result row, a
#: product tile and a profile card all are, and what a run of paragraphs is
#: not.
def _is_card(group: List) -> bool:
    """True when this group is a picture with content beside it."""
    flat = list(_flatten(group))
    figures = sum(1 for m in flat if m.startswith("<figure"))
    others = sum(1 for m in flat if not m.startswith("<figure"))
    return figures == 1 and others >= 1


def _flatten(group: List):
    for node in group:
        if isinstance(node, list):
            for inner in _flatten(node):
                yield inner
        else:
            yield node


def _serialise(node, in_card: bool = False) -> str:
    """One group as a `<div>`, with the card class on the OUTERMOST card only.

    A card inside a card draws two borders and two paddings around one record.
    It happens whenever an outer group and the inner group that actually holds
    the picture both satisfy `_is_card` -- which is the common case, since the
    inner group is usually the picture and its caption and the outer is the
    whole row. Verified in the running app: two `dv-card` elements, the second
    with `nested: true`.

    The outer one wins, so the border sits around the whole record rather than
    around the picture inside it.
    """
    if not isinstance(node, list):
        return node
    card = not in_card and _is_card(node)
    inner = "".join(_serialise(child, in_card or card) for child in node)
    cls = "dv-n dv-card" if card else "dv-n"
    return '<div class="%s">%s</div>' % (cls, inner)


def _address_attrs(line: Dict) -> List[Tuple[str, str]]:
    """The address a click on this element should name.

    `control_key` first, and the reason is the one `surface.ts::press`
    records: an anchor's `interactive.links` address is suppressed by the
    render, so the LINE is stored under a `urls.*` or `text.visible` address,
    and enacting on that names the wrong thing. Both are emitted -- the
    control to act on, the line's own to say where it lives -- because the two
    answer different questions and a single attribute would have to pick one
    and be wrong for the other caller.
    """
    key = str(line.get("control_key") or line.get("key") or "")
    own = str(line.get("key") or "")
    pairs = [("data-vertiscope-address", key)]
    if own and own != key:
        pairs.append(("data-vertiscope-line", own))
    shape = str(line.get("shape") or "")
    if shape:
        # So a reader -- or a query -- can select every element the page drew
        # from one template, which an address cannot express: each repeat has
        # its own. `[data-vertiscope-shape="..."]` is one selector for all of
        # them.
        pairs.append(("data-vertiscope-shape", shape))
    also = str(line.get("also") or "")
    if also:
        # Addresses that named the same element and did not get their own
        # element here -- see `_one_picture_per_element`. Carried so the
        # rendered DOM still reaches every address the chunk holds.
        pairs.append(("data-vertiscope-also", also))
    return pairs


def _element_of(key: str) -> str:
    """The element an address names, without its accessor.

    Addresses are `url|xpath|taxonomy|accessor`, and a single `<img>` carries
    several: `media.images/src`, `media.images/text()`, `text.accessible/alt`.
    They differ only past the xpath.
    """
    parts = (key or "").split("|")
    if len(parts) < 2:
        return key or ""
    return parts[0] + "|" + parts[1].split("/text()")[0]


def _one_picture_per_element(lines: List[Dict]) -> List[Dict]:
    """Drop the placeholder when the same element also has a real picture.

    An `<img>` yields two media addresses -- its `src`, and a `text()` whose
    value falls back to the element's own tag name -- and the renderer keeps
    both on purpose: they are two addresses, and `_dedupe` dropping a url or
    media address is the one thing its guard exists to prevent. In markdown
    that costs a line: `![A Book]` above `![A Book](media/….jpg)`.

    In HTML it costs a picture. The placeholder draws as a grey tile and the
    real one draws as the photograph, so the reader sees the same image twice,
    once broken -- and the group then holds two figures, so it is not
    recognised as a card and the layout the page had is lost as well.

    An element is a thing; markdown had to spend a line per address because a
    line is all it has, and HTML does not. The dropped address is not lost:
    it rides on the surviving figure as `data-vertiscope-also`, so every address
    in the chunk is still reachable from the rendered DOM.
    """
    best: Dict[str, int] = {}
    for i, line in enumerate(lines):
        text = str(line.get("text") or "").strip()
        if not _MEDIA.match(text) and not _MEDIA_BARE.match(text):
            continue
        element = _element_of(str(line.get("key") or ""))
        if not element:
            continue
        located = bool(_MEDIA.match(text))
        held = best.get(element)
        if held is None or (located and not
                            _MEDIA.match(str(lines[held].get("text") or "").strip())):
            best[element] = i

    drop: Dict[int, str] = {}
    for i, line in enumerate(lines):
        text = str(line.get("text") or "").strip()
        if not _MEDIA.match(text) and not _MEDIA_BARE.match(text):
            continue
        element = _element_of(str(line.get("key") or ""))
        keeper = best.get(element)
        if keeper is not None and keeper != i:
            drop[i] = str(line.get("key") or "")

    if not drop:
        return lines
    out: List[Dict] = []
    carried: Dict[int, List[str]] = {}
    for i, key in drop.items():
        element = _element_of(str(lines[i].get("key") or ""))
        carried.setdefault(best[element], []).append(key)
    for i, line in enumerate(lines):
        if i in drop:
            continue
        if i in carried:
            line = dict(line, also=" ".join(carried[i]))
        out.append(line)
    return out


def _xpath_of(key: str) -> str:
    """The element part of an address, without the accessor."""
    parts = (key or "").split("|")
    if len(parts) < 2:
        return ""
    return parts[1].split("/text()")[0]


def _related(a: str, b: str) -> bool:
    """True when two elements are on one ancestor chain.

    A descendant's xpath IS its ancestors' with more on the end, so this is
    exact rather than heuristic. The guard matters: two lines can carry the
    same words and be two different things -- a list of people who share a
    name -- and folding those would lose one of them. On one chain they are
    the same thing described from two heights.
    """
    if not a or not b:
        return False
    if a == b:
        return True
    longer, shorter = (a, b) if len(a) > len(b) else (b, a)
    return longer.startswith(shorter + "/")


#: What a rendering carries, most to least. A line that names where it goes or
#: what it shows outranks one that only repeats the words, so folding keeps
#: the richest form of the thing rather than whichever came first.
def _rank(text: str, line: Dict) -> int:
    """What this rendering carries, most to least.

    The heading mark comes off FIRST, and that is the whole subtlety. A
    heading that links -- `### [Title](url)` -- is a heading AND a
    destination, but tested with the hashes still on it, `_LINK` cannot match
    and it scores as a bare heading. It then tied with the same title drawn
    from the anchor's `title` attribute, the tie went to whichever came
    first, and the version WITH the destination was the one folded away: the
    card's product name stopped linking to the product.

    That is the same trap `surface.ts::words` and `_element` record, for the
    same reason, in the third place in this codebase: a leading mark hides
    every other leading mark behind it.
    """
    stripped = text.strip()
    heading = _HEADING.match(stripped)
    inner = heading.group(2).strip() if heading else stripped

    if _MEDIA.match(inner):
        return 5                      # a picture with a source
    if _LINK.match(inner):
        return 4                      # words and a destination
    if heading:
        return 3
    if _control(inner, str(line.get("cls") or ""), []):
        return 3                      # a real control
    if _MEDIA_BARE.match(inner) or _BARE_URL.match(inner):
        return 1                      # a placeholder, or a naked url
    return 2


def _words(text: str) -> str:
    """The line's words, marks off and normalised FOR COMPARISON.

    Lowercased, so two spellings of one title match. Never use the result as
    a label: `_visible` is the same stripping without the case folding, and
    reusing this one printed a product called "1,000 places to see before you
    die".
    """
    out = text.strip()
    heading = _HEADING.match(out)
    if heading:
        out = heading.group(2).strip()
    for pattern in (_MEDIA, _LINK):
        hit = pattern.match(out)
        if hit:
            out = hit.group(1).strip()
            break
    else:
        bare = _MEDIA_BARE.match(out)
        if bare:
            out = bare.group(1).strip()
    for pattern in (_FORM, _BUTTON):
        hit = pattern.match(out)
        if hit:
            out = hit.group(1).strip()
            break
    field = _FIELD.match(out)
    if field:
        out = field.group(2).strip()
    return " ".join(out.split()).lower()


def _visible(text: str) -> str:
    """The same words `_words` compares, in the page's own casing."""
    out = text.strip()
    heading = _HEADING.match(out)
    if heading:
        out = heading.group(2).strip()
    for pattern in (_MEDIA, _LINK):
        hit = pattern.match(out)
        if hit:
            out = hit.group(1).strip()
            break
    else:
        bare = _MEDIA_BARE.match(out)
        if bare:
            out = bare.group(1).strip()
    for pattern in (_FORM, _BUTTON):
        hit = pattern.match(out)
        if hit:
            out = hit.group(1).strip()
            break
    field = _FIELD.match(out)
    if field:
        out = field.group(2).strip()
    return " ".join(out.split())


def _tokens(words: str) -> frozenset:
    """The words as a set, with a truncation mark taken off.

    A page writes a full title in an anchor's `title` and a shortened one in
    the heading it draws -- "1,000 Places to See Before You Die" against
    "1,000 Places to See ...". Those are one thing, and an equality test says
    they are two.
    """
    out = set()
    for token in words.split():
        token = token.strip(".,;:!?()[]{}\u2026").strip()
        if token and token != "...":
            out.add(token)
    return frozenset(out)


def _target_of_line(line: Dict, text: str) -> str:
    """Where this line points, if anywhere."""
    stripped = text.strip()
    heading = _HEADING.match(stripped)
    if heading:
        stripped = heading.group(2).strip()
    hit = _LINK.match(stripped) or _BARE_URL.match(stripped)
    if hit:
        return (hit.group(2) if hit.re is _LINK else hit.group(1)).strip()
    return str(line.get("target") or "").strip()


def _fold_repeats(lines: List[Dict]) -> List[Dict]:
    """Draw one element per thing, not one per address.

    A page's `<img>` inside an `<a>` inside a `<div>` yields the same words
    five times over: the image's alt, the picture's own caption, the wrapping
    div's visible text, the anchor's `title`, and the heading that links to
    it. Every one is a real address, and the markdown form has to spend a line
    on each because a line is all markdown has. Measured on one
    books.toscrape product card: eleven lines, seven distinct, the title five
    times.

    HTML does not have to. An element can hold several addresses, so the
    richest rendering survives -- the picture over its placeholder, the link
    over the bare words -- and the rest ride along in `data-vertiscope-also`, so
    every address stays reachable from the rendered DOM.

    Three ways one thing shows up twice, and all three are folded:

    * **The same words**, at two heights of one chain.
    * **Subsumed words.** A shortened label and its full form are one thing;
      an equality test says they are two. The fuller wording wins even when
      the shorter line is the one that survives, because the survivor is
      chosen for what it CARRIES -- a destination, a picture -- and there is
      no reason to keep its truncation as well.
    * **The same destination.** Two lines pointing at one url inside a single
      record are one link, even when they sit on unrelated branches: a card
      writes its href on the image's anchor and again on the heading's. A url
      is an identity, so this one does not need the chain test -- and since
      the record rule made a chunk a single record, "inside one chunk" is a
      tight enough scope for that to be true.

    Everything else is folded ALONG AN ANCESTOR CHAIN only. Two lines with
    the same words at unrelated elements are two things that happen to read
    alike, and merging those would lose one.
    """
    def key_of(i):
        return str(lines[i].get("key") or "")

    def text_of(i):
        return str(lines[i].get("text") or "")

    def words_of(i):
        return _words(text_of(i))

    def rank_of(i):
        return _rank(text_of(i), lines[i])

    n = len(lines)
    tokens = [_tokens(words_of(i)) for i in range(n)]
    targets = [_target_of_line(lines[i], text_of(i)) for i in range(n)]

    dropped = set()
    carried: Dict[int, List[str]] = {}
    label: Dict[int, str] = {}

    def fold(loser: int, keeper: int) -> None:
        dropped.add(loser)
        carried.setdefault(keeper, []).append(key_of(loser))
        # Keep the fuller wording. The survivor was chosen for what it
        # carries, not for how much of the title it printed.
        if tokens[loser] > tokens[keeper]:
            label[keeper] = _visible(text_of(loser))

    for i in range(n):
        if i in dropped or not tokens[i]:
            continue
        for j in range(i + 1, n):
            if j in dropped or not tokens[j]:
                continue
            same_thing = (
                (tokens[i] == tokens[j]
                 or tokens[i] < tokens[j] or tokens[j] < tokens[i])
                and _related(_xpath_of(key_of(i)), _xpath_of(key_of(j)))
            ) or (targets[i] and targets[i] == targets[j])
            if not same_thing:
                continue
            if rank_of(j) > rank_of(i):
                fold(i, j)
                break
            fold(j, i)

    out: List[Dict] = []
    for i, line in enumerate(lines):
        if i in dropped:
            continue
        extra = carried.get(i)
        if extra:
            line = dict(line,
                        also=" ".join(
                            [str(line.get("also") or "")] + extra).strip())
        fuller = label.get(i)
        if fuller:
            line = dict(line, text=_relabel(text_of(i), fuller))
        out.append(line)
    return out


def _relabel(text: str, words: str) -> str:
    """``text`` with its visible words replaced, structure untouched.

    Only the label moves. The mark that says what the line IS -- a heading's
    hashes, a link's target, a control's brackets -- is what the render
    decided, and rewriting that here would be this module overruling the
    renderer rather than tidying it.
    """
    stripped = text.strip()
    indent = text[:len(text) - len(text.lstrip(" "))]
    heading = _HEADING.match(stripped)
    prefix = ""
    if heading:
        prefix = heading.group(1) + " "
        stripped = heading.group(2).strip()

    link = _LINK.match(stripped)
    if link:
        return "%s%s[%s](%s)" % (indent, prefix, words, link.group(2))
    media = _MEDIA.match(stripped)
    if media:
        return "%s%s![%s](%s)" % (indent, prefix, words, media.group(2))
    button = _BUTTON.match(stripped)
    if button:
        return "%s%s( %s )" % (indent, prefix, words)
    return "%s%s%s" % (indent, prefix, words)


def _captions_to_drop(lines: List[Dict]) -> set:
    """Alt texts that some other line in this chunk already says.

    A product card names itself twice over: the picture is captioned with the
    `alt`, and the heading beside it carries the same words. Both are real and
    neither is redundant in the markdown form, where a caption is the only
    place the alt can go -- but drawn side by side in a card, it is the same
    sentence printed twice.

    The picture keeps its `alt`, so nothing is lost to a screen reader or to
    an image that fails to load; only the visible caption goes.
    """
    said = set()
    for line in lines:
        text = str(line.get("text") or "").strip()
        if _MEDIA.match(text) or _MEDIA_BARE.match(text):
            continue
        words = _words(text)
        if words:
            said.add(words)
    return said


#: The xpath step of an element whose siblings belong to one control.
_OPTION_STEP = re.compile(r"/(option|optgroup)(\[\d+\])?$")


def _xpath_of(key: str) -> str:
    """The xpath out of an `url|xpath|taxonomy|accessor` address."""
    parts = (key or "").split("|")
    return parts[1] if len(parts) > 1 else ""


def _owning_listbox(key: str) -> str:
    """The xpath of the control this option belongs to, or "".

    The parent of an `<option>` is a real element with a real address -- the
    `<select>` the page drew -- which is what makes gathering the options
    under one node different from gathering arbitrary siblings under an
    invented `<ul>`. The rule this module follows everywhere else is that a
    shared parent must not claim an address that is nobody's; here it claims
    the one the page already has.
    """
    xpath = _xpath_of(key)
    if not _OPTION_STEP.search(xpath):
        return ""
    return xpath[:xpath.rfind("/")]


def _listbox_runs(lines: List[Dict]) -> List[object]:
    """Consecutive options of one control, gathered; everything else as is.

    An `<option>` drawn on its own came out as `<input type="text" disabled
    placeholder="...">` -- a text field, which is not what an option is, and
    on a page that aggregates it produced a column of 1,509 fake text boxes
    where the page has one dropdown. The markdown form has no way to say
    "listbox" and this one does, which is the whole reason it exists beside
    it.

    Only CONSECUTIVE options of the SAME parent are gathered, so a chunk
    holding two selects draws two, and the reading order the lines arrived in
    is preserved.
    """
    out: List[object] = []
    run: List[Dict] = []
    owner = ""
    for line in lines:
        key = str(line.get("control_key") or line.get("key") or "")
        this = _owning_listbox(key)
        if this and this == owner:
            run.append(line)
            continue
        if run:
            out.append((owner, run))
        run, owner = ([line], this) if this else ([], "")
        if not this:
            out.append(line)
    if run:
        out.append((owner, run))
    return out


def _listbox(owner: str, run: List[Dict], base: str) -> str:
    """One `<select>` holding one `<option>` per line.

    `disabled` like every other widget here: the page is not present, and the
    surface enables what the enact gate allows. `size` opens it to its own
    height rather than collapsing it to one row, because the chunk's content
    IS the options -- a closed dropdown would draw a chunk as a single empty
    box.

    Each option keeps its own address, so pressing one still names exactly
    the element it came from, and the `<select>` carries the parent's.
    """
    url = str(run[0].get("key") or "").split("|")[0]
    parts = []
    for line in run:
        text = str(line.get("text") or "").strip()
        field = _FIELD.match(text)
        label = (field.group(2).strip() if field else text)
        attrs = _attrs(_address_attrs(line))
        parts.append('<option class="dv-opt"%s>%s</option>'
                     % (attrs, _esc(label)))
    holder = _attrs([("data-vertiscope-address",
                      "%s|%s|interactive.inputs|text()" % (url, owner))]) \
        if url and owner else ""
    return ('<select class="dv-select" disabled size="%d"%s>%s</select>'
            % (min(len(parts), 12), holder, "".join(parts)))


def _is_form_action(line: Dict, raw: str) -> bool:
    """A form's own line, whose text is its ``action`` url (D-36).

    The page draws nothing there -- a form is a container -- and the panel
    printed ``/?q=suffix+tree&ia=chat`` as a line of text in the middle of
    DuckDuckGo's answer. Hidden in the panel only: the line and its address
    stay in the payload, the trie and the markdown.
    """
    if str(line.get("cls") or "") != "group":
        return False
    key = str(line.get("key") or "")
    text = raw.strip()
    return ("|action" in key or "action%7C" in key) and (
        text.startswith(("/", "?", "http://", "https://")) or text == str(line.get("target") or ""))


def render_lines(lines: List[Dict], *, base: str = "") -> str:
    """The distilled elements for one chunk's payload lines.

    Takes the payload rather than the store so that the markdown surface and
    this one are provably reading the same thing: one alignment of lines to
    addresses, used twice.
    """
    builder = _Builder()
    kept = _fold_repeats(_one_picture_per_element(lines))
    said = _captions_to_drop(kept)
    for item in _listbox_runs(kept):
        if isinstance(item, tuple):
            owner, run = item
            raw = str(run[0].get("text") or "")
            builder.at((len(raw) - len(raw.lstrip(" "))) // 2)
            builder.add('<div class="dv-p">%s</div>'
                        % _listbox(owner, run, base))
            continue
        raw = str(item.get("text") or "")
        if not raw.strip() or _is_form_action(item, raw):
            continue
        depth = (len(raw) - len(raw.lstrip(" "))) // 2
        builder.at(depth)
        builder.add(_element(raw.strip(), item, base, said))
    return builder.close()


def _element(text: str, line: Dict, base: str,
             said: Optional[set] = None) -> str:
    """One distilled line as one element.

    The shape is decided by the render's mark, not by the taxonomy, and that
    is on purpose. `render_class` is a lossy projection -- `interactive.forms`
    and `role=article` both come out `group` -- and its own docstring says to
    key on the raw tag or on affordance where the distinction matters. The
    mark IS the renderer's decision about what this element is, made where the
    trie was still in hand, so it is the most specific thing that survives
    into the payload.
    """
    addr = _address_attrs(line)
    cls = str(line.get("cls") or "text")
    target = str(line.get("target") or "")

    heading = _HEADING.match(text)
    level, body = 0, text
    if heading:
        level = min(6, len(heading.group(1)))
        body = heading.group(2).strip()

    media = _MEDIA.match(body)
    if media:
        return _media(media.group(1),
                      _absolute(_safe_url(media.group(2) or target), base),
                      media.group(3), addr, said)
    placeholder = _MEDIA_BARE.match(body)
    if placeholder:
        return _media(placeholder.group(1), _absolute(_safe_url(target), base),
                      placeholder.group(2), addr, said)

    bullet = _BULLET.match(body)
    listed = bullet is not None
    if bullet:
        body = bullet.group(1).strip()

    inner = _control(body, cls, addr)
    if inner is None:
        inner = _prose(body, target, addr, base)

    if level:
        return '<h%d class="dv-h">%s</h%d>' % (level, inner, level)
    if _is_block(inner):
        # A `<fieldset>` is flow content and cannot sit inside a `<p>`: the
        # parser closes the paragraph at the opening tag and re-opens one
        # after the close, which puts the element's siblings in a different
        # place in the tree than the builder thinks they are. The nesting
        # `<div>`s then unwind against a structure nobody wrote. Wrapping
        # block widgets in a `<div>` instead keeps the tree the one this
        # module emitted.
        return '<div class="dv-p">%s</div>' % inner
    if listed:
        # One `<li>` per line inside its own `<ul>`. A run of siblings could be
        # gathered into a single list, and is not: the lines are addressed
        # individually and a shared parent would have to claim an address that
        # is nobody's. Under-claiming is the rule everywhere else here too.
        return '<ul class="dv-ul"><li class="dv-li">%s</li></ul>' % inner
    return '<p class="dv-p">%s</p>' % inner


#: Tags that may not appear inside a `<p>`. Kept as a tuple rather than
#: inferred, because "is this phrasing content" is a question about the HTML
#: spec and not about this module, and a wrong guess shows up as mysterious
#: mis-nesting rather than as an error.
_BLOCK_TAGS = ("<fieldset", "<div", "<ul", "<figure", "<table")


def _is_block(markup: str) -> bool:
    return markup.startswith(_BLOCK_TAGS)


def _prose(body: str, target: str, addr: List[Tuple[str, str]],
           base: str = "") -> str:
    """A line with no widget in it: a link, a bare url, or words.

    Hrefs are absolutised against the page for the same reason media srcs are:
    a relative one resolves against the document the surface lives in, which
    in a vault is the app itself.
    """
    link = _LINK.match(body)
    if link:
        href = _absolute(_safe_url(link.group(2) or target), base)
        words = _esc(link.group(1).strip()) or _esc(href)
        tail = _esc(link.group(3).strip())
        if href:
            out = ('<a class="dv-a" href="%s" rel="noreferrer noopener"%s>%s'
                   '</a>' % (_esc(href), _attrs(addr), words))
        else:
            # A refused scheme keeps its words and loses its href. The reader
            # still sees everything the page said.
            out = '<span class="dv-t"%s>%s</span>' % (_attrs(addr), words)
        return out + ((" " + tail) if tail else "")

    bare = _BARE_URL.match(body)
    if bare:
        url = _absolute(_safe_url(bare.group(1)), base)
        if url:
            return ('<a class="dv-a" href="%s" rel="noreferrer noopener"%s>%s'
                    '</a>' % (_esc(url), _attrs(addr), _esc(url)))
    return '<span class="dv-t"%s>%s</span>' % (_attrs(addr), _esc(body))


def _control(body: str, cls: str, addr: List[Tuple[str, str]]) -> Optional[str]:
    """A real widget for a line the render marked as one, or None.

    The element is genuine -- a `<button>`, an `<input>` -- rather than a
    styled `<span>`, because the whole reason this form exists beside the
    markdown one is that HTML has controls and markdown does not. Every one is
    `disabled` as emitted: the page is not here, and the surface enables what
    the server's enact gate allows. A field a reader can type into that goes
    nowhere is worse than one that says it is inert.
    """
    form = _FORM.match(body)
    if form:
        return ('<fieldset class="dv-form"%s><legend>%s</legend></fieldset>'
                % (_attrs(addr), _esc(form.group(1) or "form")))

    button = _BUTTON.match(body)
    if button:
        return ('<button class="dv-b" type="button" disabled%s>%s</button>'
                % (_attrs(addr), _esc(button.group(1))))

    field = _FIELD.match(body)
    if field:
        mark, label = field.group(1), field.group(2).strip()
        if mark.strip():
            # `[x]` is a checked box, drawn as one rather than as a text field
            # with an x in it.
            return ('<label class="dv-f"><input type="checkbox" checked '
                    'disabled%s><span>%s</span></label>'
                    % (_attrs(addr), _esc(label)))
        return ('<label class="dv-f"><input type="text" disabled '
                'placeholder="%s"%s><span>%s</span></label>'
                % (_esc(label), _attrs(addr), _esc(label)))

    if cls in ("button", "choice", "check", "slider") and body:
        # Marked a control by the taxonomy but drawn without a mark -- the
        # carried-affordance case `_carry_affordance` exists for. It still
        # gets a real widget.
        return ('<button class="dv-b dv-carried" type="button" disabled%s>%s'
                '</button>' % (_attrs(addr), _esc(body)))
    return None


def _media(alt: str, src: str, rest: str,
           addr: List[Tuple[str, str]], said: Optional[set] = None) -> str:
    """A picture or a player, as a figure that keeps its caption.

    The `src` is emitted; whether it is FETCHED is settled by the surface,
    which strips it when the reader has media off. Loading a page's assets
    from inside a vault tells those hosts the page was read again, and that is
    the reader's decision to make, not this module's.
    """
    # A caption the chunk already says elsewhere is the same sentence printed
    # twice once the two are drawn side by side in a card. The `alt` stays on
    # the image either way, so nothing is lost to a screen reader or to a
    # picture that fails to load.
    repeated = bool(said and alt and " ".join(alt.split()).lower() in said)
    caption = _esc(alt or "image")
    tail = (" " + _esc(rest.strip())) if rest.strip() else ""
    if not src:
        return ('<figure class="dv-fig dv-fig-off"%s><div class="dv-noimg">%s'
                '</div><figcaption>%s%s</figcaption></figure>'
                % (_attrs(addr), _NO_IMAGE, caption, tail))
    figcaption = ("" if repeated and not tail.strip()
                  else '<figcaption>%s%s</figcaption>' % (caption, tail))
    return ('<figure class="dv-fig"%s><img class="dv-img" src="%s" alt="%s" '
            'loading="lazy" referrerpolicy="no-referrer">%s</figure>'
            % (_attrs(addr), _esc(src), caption, figcaption))


def chunk_html(workspace, cid: str) -> Optional[str]:
    """The distilled HTML for one stored chunk, or None if there is no chunk."""
    from .sidecar import chunk_payload

    payload = chunk_payload(workspace, cid)
    if payload is None:
        return None
    return render_lines(payload["lines"], base=payload.get("url", ""))
