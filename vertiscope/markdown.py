"""Trie -> markdown chunks -> JSONL. The second data checkpoint.

Retrieval happens first and rendering second: the trie is parsed as a
*detection* structure, and only then is its content rendered. So this module
takes the trie as given and never touches the DOM. Everything it needs —
structure, kind, provenance, value — is already in the addresses.

What it produces mirrors the trie:

* one markdown chunk per subtree that fits the context window;
* inside a chunk, one markdown line per surviving content unit, indented by
  its depth below the chunk root;
* an ``anchors`` array parallel to the lines, giving each line's address.

The anchors are the link back. A retrieval hit is a chunk; a chunk line is an
address; an address is an absolute xpath into the source document. Nothing in
the chain needs a second lookup structure.

Why indentation is enough
-------------------------
THEORY Thm. 17.3 gives the classical bijection between well-formed depth
sequences and ordered forests, and Cor. 17.4 concludes that indentation is a
**complete** encoding of ordered tree structure — the tree can be read back
off the markdown exactly. Prop. 17.5 states the precondition: the printing map
is faithful only when distinct nodes print distinctly. Here they do, because
each line carries its own anchor, so two identically-worded lines at the same
depth remain distinguishable even though their text is not.

The chunking hyperparameter
---------------------------
``context_window`` is the only knob. The descent is top-down: a subtree whose
rendered size fits becomes one chunk; otherwise it splits into its children
and each is tried in turn. A leaf that alone exceeds the window is emitted
whole rather than cut, because cutting it would produce a chunk whose address
does not describe its content — the address would over-claim.

This is deliberately the opposite direction from the leaf-up budget walk in
``core.chunk_builder``. Top-down keeps every chunk rooted at a real element,
so a chunk root is always something the address scheme can name and the REPL
can navigate to. Bottom-up merging produces chunks spanning sibling sets with
no common element root, which have no address.
"""

from __future__ import annotations

import hashlib
import json
import re
import zlib
from dataclasses import dataclass, field, replace
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from . import tokens
from .address import ContentAddress, url_steps
from .trie import AddressTrie, TrieNode, token_multiset

__all__ = [
    "MarkdownChunk",
    "MarkdownLine",
    "render_trie",
    "RenderMemo",
    "write_jsonl",
    "read_jsonl",
    "DEFAULT_CONTEXT_WINDOW",
]

DEFAULT_CONTEXT_WINDOW = 256
"""One chunk's budget, in whatever unit `tokens.name()` is currently in.

Its history is a history of getting the UNIT wrong and then the SIZE wrong.
It was 1200 *characters* -- about 400 tokens -- while everything downstream
measures in tokens, so it was a twentieth of any real budget and the chunks it
made filled 8% of one. It became 2048, the practical input of the local
embedder, then 512.

**256 now, and the number was chosen against two measurements that pull in
opposite directions.**

A chunk is a retrieval unit, so the first question is how well it can be
FOUND. Forty probes per page, real lines, the same probes at every window,
asking whether the chunk containing a line ranks first:

    window   web-scraping   python-lang   MDN CSS   over window   record tests
      64         85%            90%         83%        13.3%       nav AND
                                                                   prose split
     128         60%            75%         65%         7.8%       prose splits
     256         45%            48%         58%         2.5%       all pass
     512         48%            28%         45%         1.0%       all pass

Retrieval is monotone in favour of SMALL: a bigger chunk holds the answer
beside more unrelated text and its vector drifts toward the average of the
two. Structure is monotone the other way. At 64 a nav bar splits into three
chunks of menu labels -- `test_a_nav_bar_is_not_a_record_set` puts the reason
in its own assertion, "a menu item is not a retrievable unit" -- and adjacent
paragraphs stop merging.

256 is where those meet: every structural property holds, and it still beats
512 on retrieval by about ten points while filling half the window instead of
a third. **512 is dominated** -- there is no measurement on which it wins.

The 64 column is probably flattering itself. Those probes are verbatim lines,
which favours short chunks mechanically, so the gap to 256 is an upper bound.
The DIRECTION held on three unrelated pages, so 256-over-512 is safe; 64-over-
256 wants re-testing with paraphrased probes before anyone bets on it.

**A target, not a ceiling.** A page with less in it than the window emits one
chunk holding all of it, and a single leaf too big to fit is emitted whole
rather than cut -- cutting it would leave a chunk whose address over-claims.
So `chunks_over_window` counts, among other things, records doing exactly what
the record rule exists to make them do.
"""


# Element labels that carry markdown meaning. Everything else is a container
# and contributes indentation only.
_HEADINGS = {"h1": 1, "h2": 2, "h3": 3, "h4": 4, "h5": 5, "h6": 6}
_LIST_ITEMS = {"li", "dt", "dd"}
_QUOTES = {"blockquote", "q"}
_CODE = {"code", "pre", "kbd", "samp"}


# --- lines ------------------------------------------------------------------


@dataclass
class MarkdownLine:
    """One rendered content unit and the address it came from."""

    depth: int
    text: str
    address: ContentAddress
    #: Addresses merged into this line by `_inline_flow`, in reading order.
    #: A sentence with a link in it is one line for a reader and several
    #: addresses for anyone who wants to act on it, and dropping the second
    #: to get the first would make the prose read correctly at the cost of
    #: making the link unreachable.
    inline: Tuple[ContentAddress, ...] = ()
    #: Addresses this line SPEAKS FOR: other spellings of the same fact at
    #: the same element, which the collapse folded into it.
    #:
    #: `inline` and this both put an address on a line that is not its own,
    #: and they answer different questions. An inline address was MERGED --
    #: its words are visibly in this line and a reader can act on it there.
    #: An absorbed one was DROPPED -- an `aria-label` beside the text it
    #: duplicates, an href hidden because the anchor speaks. Its words are
    #: not separately visible; what it needs is to remain findable.
    #:
    #: Collapse was otherwise terminal. The surviving unit keeps the
    #: element's xpath so navigation holds, but the dropped address key was
    #: gone and nothing could say the render had accounted for it. That is
    #: what makes over-dedup the dangerous direction, and why the fold is
    #: tuned 17:1 toward leaving noise rather than risking loss. Once a
    #: collapse names what it collapsed, folding harder stops meaning losing.
    absorbed: Tuple[ContentAddress, ...] = ()

    def render(self) -> str:
        return "  " * self.depth + self.text


# --- chunks -----------------------------------------------------------------


@dataclass
class MarkdownChunk:
    """A subtree rendered as markdown, addressed by its root element."""

    url: str
    xpath: str          # the chunk root's absolute xpath
    lines: List[MarkdownLine] = field(default_factory=list)
    part: int = 0       # distinguishes several chunks sharing a root xpath

    @property
    def markdown(self) -> str:
        return "\n".join(line.render() for line in self.lines)

    @property
    def anchors(self) -> List[str]:
        """Address keys, ONE PER LINE, in line order.

        Positional by contract: the jsonl round-trip, the depth recovery and
        the REPL all zip this against `lines`. Widening it to include merged
        addresses broke four of those at once -- see `covered`, which is
        where that question belongs.
        """
        return [line.address.key() for line in self.lines]

    @property
    def covered(self) -> List[str]:
        """Every address this chunk accounts for, merged ones included.

        `anchors` is one per line and must stay that way. But a line that put
        a sentence's inline markup back together accounts for every address
        folded into it, and counting only the first made those look lost:
        the covered set then depended on where the chunker happened to cut,
        and moving the context window from 1200 to 200 moved 589 of them.

        Coverage is a property of the chunk. How many lines it took to draw
        is not.
        """
        out: List[str] = []
        for line in self.lines:
            out.append(line.address.key())
            out.extend(a.key() for a in line.inline)
        return out

    @property
    def accounted(self) -> List[str]:
        """Every address this chunk ACCOUNTS FOR, absorbed spellings included.

        `covered` answers "what did the render draw"; this answers "what can
        the system still resolve", and they are not the same question. The
        store already knows the difference: `graphstore` builds its
        `chunk_of` map from `address`, then `inline`, then a third pass over
        `absorbed` -- because reading only the first two "left 37,452
        addresses over the corpus with no chunk at all, 8,167 of them urls,
        and an edge they could not hang on".

        So an absorbed address has a chunk, hangs its edge and is findable.
        Reporting it as lost made every rendering cleanup look like data loss:
        measured on the nameless-media change, `covered` fell by 340 addresses
        that still existed, where `accounted` fell by 94. The gate was
        overstating the cost 3.6 times over, and a change was reverted partly
        on that.

        Over twelve corpus pages: `covered` reaches 89.4% of the trie's
        addresses, `accounted` 95.9%.

        **Cleanups are gated on this, not on `covered`.** Drawing fewer
        redundant lines is *supposed* to lower `covered` -- that is what it
        means -- and gating on the number a change is designed to move can
        only ever forbid the change.
        """
        out = list(self.covered)
        for line in self.lines:
            out.extend(a.key() for a in line.absorbed)
        return out

    # `absorbed` is deliberately not counted by `covered`, above.
    #
    # Coverage must not move with the context window --
    # `test_no_address_is_lost_when_the_window_changes` holds that -- and
    # whether an element draws a line at all is a chunking outcome. Counting
    # a collapse as covered therefore made the set window-dependent by four
    # addresses at window 200, twice: once collecting drops inside the
    # speculative descent, and again with the drops derived from the trie,
    # because the ATTACHMENT still needs a line to land on.
    #
    # Nothing is lost by leaving it out. `covered` asks what the chunk
    # accounted for; `absorbed` asks what a line speaks for, which is the
    # question the object model needs in order to reach a folded spelling.
    # Keeping them apart is what lets folding get more aggressive without
    # making a coverage figure move.

    @property
    def chars(self) -> int:
        return len(self.markdown)

    @property
    def cid(self) -> str:
        """Chunk id: the hash of (url, root xpath, part).

        Keyed on position rather than on content for the reason recorded in
        ERRATA B10 — a content-keyed id degenerates wherever content is
        absent, and empty chunks are exactly the ones nobody inspects.
        """
        return hashlib.sha1(
            f"{self.url}|{self.xpath}|{self.part}".encode("utf-8")
        ).hexdigest()[:16]

    def to_json(self) -> dict:
        return {
            "cid": self.cid,
            "url": self.url,
            "xpath": self.xpath,
            "part": self.part,
            "lines": len(self.lines),
            "chars": self.chars,
            "md": self.markdown,
            "anchors": self.anchors,
        }

    @staticmethod
    def from_json(obj: dict) -> "MarkdownChunk":
        md_lines = obj["md"].split("\n") if obj["md"] else []
        anchors = obj["anchors"]
        if len(anchors) != len(md_lines):
            # Lines and anchors are paired *by position*, so a length mismatch
            # does not lose the tail — it misattributes every line from the
            # first surplus anchor onward, and `zip` would do that silently.
            # This has happened: a re-scanned page that shrank kept its old
            # anchors, so a 7-line chunk carried 21 and every line pointed at
            # the wrong element. Fixed at the source (GraphStore._reconcile);
            # loud here so the next cause cannot hide.
            raise ValueError(
                f"chunk {obj.get('cid', '?')}: {len(md_lines)} markdown line(s) "
                f"but {len(anchors)} anchor(s) — lines are paired with anchors "
                f"by position, so this would misattribute addresses"
            )
        lines = []
        for raw, anchor in zip(md_lines, anchors):
            stripped = raw.lstrip(" ")
            depth = (len(raw) - len(stripped)) // 2
            lines.append(MarkdownLine(
                depth=depth, text=stripped, address=ContentAddress.parse(anchor)
            ))
        return MarkdownChunk(url=obj["url"], xpath=obj["xpath"],
                             lines=lines, part=obj.get("part", 0))


# --- rendering one node -----------------------------------------------------


def _label_of(segment: str) -> str:
    return segment.split("[", 1)[0].lower()


#: Prefixes that make a value a target rather than prose -- but only when
#: something follows them. See `_looks_like_url`.
_URL_LEADS = ("http://", "https://", "//", "/", "#", "mailto:", "tel:",
              "data:", "?")


def _looks_like_url(value: str) -> str:
    """Whether a value is a target rather than something a reader reads.

    A lone separator is not a target. `/` passed this test on its prefix
    alone, and a page that writes a character counter as `0` `/` `500` --
    three text nodes, which duckduckgo does -- had the middle one read as a
    root-relative path. `_join_inline` refuses to join a url to prose, quite
    rightly, so the counter stayed three lines of a document where a reader
    sees one.

    The rule is unchanged except that a prefix must lead somewhere: `/` is
    punctuation, `/docs` is a path.
    """
    v = value.strip()
    if not v:
        return False
    if "://" in v:
        return True
    for lead in _URL_LEADS:
        if v.startswith(lead) and len(v) > len(lead):
            return True
    return False


def _is_tag_name(value: str) -> bool:
    """Whether a detection's value is an element name rather than content.

    Some detections carry the tag as their value — `_add('media', cat, xpath,
    tag, '')` — because the element *is* the finding and there is nothing else
    to record. A url never looks like this: it has a slash, a dot or a colon.
    """
    value = value.strip()
    return bool(value) and len(value) <= 12 and value.isalpha()


# Interactive detections whose *value* is the element's tag name rather than
# any content — `_add('interactive', 'links', xpath, tag, '')`. For links that
# is pure noise: the same node already yields the href as a `urls.*` unit and
# its text as a `text.visible` one, so rendering it would print "[a]" beside
# them. Controls are different — an input or a button has no other
# representation, and the REPL has to be able to see it — so those survive,
# rendered with the element's own text when it has any.
_SUPPRESSED_TAGS = frozenset({"interactive.links", "interactive.elements"})

# Render classes that draw using the element's own text. Their text unit is
# consumed, so the words appear once, inside the control.
_CONSUMING_CLASSES = frozenset({"link", "button", "field", "choice",
                                "check", "slider"})


# Names the fold uses to say "a control is here". Matched exactly, against a
# closed set. Testing "short and alphabetic" instead -- which is the right
# test for a media value and the wrong one here -- deleted `Search` and
# `DuckDuckGo`, because those are also short and alphabetic. A label that is
# genuinely the element's name is a tiny set; a label that merely looks like
# one is most of the words on a page.
_CONTROL_TAGS = frozenset({
    "input", "button", "select", "textarea", "a", "form", "option",
    "optgroup", "label", "fieldset", "datalist", "output", "summary",
})


def _echoes_its_element(address: ContentAddress, value: str) -> bool:
    """Is this value the page's words, or the fold repeating the element name?

    `interactive.links` carries the anchor's own label, and falls back to the
    tag name when the anchor has none -- `<a name="chap01">`. Telling those
    apart with `_is_tag_name` does not work: that test is "short and
    alphabetic", which is right for a media value and wrong here. It ate
    `Espanol`, `China` and `Europe` -- every one-word nav label on AP's front
    page, 643 controls across ten corpus pages -- for the same reason the
    comment on `_CONTROL_TAGS` gives for not using it on a label.

    Compared against the address's OWN last step instead. A closed list would
    have to track the html spec; this asks whether the value repeats the name
    of the element it sits on, which is exactly what the fallback produces.
    """
    step = (address.xpath or "").rstrip("/").rsplit("/", 1)[-1].split("[")[0]
    return bool(step) and value.strip().lower() == step.lower()


def _media_alt(text: str, value: str) -> str:
    """What an image or a player is *of*, never its file name.

    An `alt` or a caption if the page gave one; otherwise nothing, because
    `![ /assets/hero-2x.webp ](...)` describes a path and not a picture.
    """
    for candidate in (text, value):
        candidate = (candidate or "").strip()
        if candidate and not _looks_like_url(candidate)                 and candidate.lower() not in _CONTROL_TAGS:
            return candidate
    return ""


def _control_label(text: str, value: str) -> str:
    """A control's visible label, never its element name.

    The fold records a control's existence as `@control -> "input"`, because
    for an input the element *is* the finding and there is nothing else to
    put there. Drawn literally that reads `( input )` and `[ ] select` on a
    results page, which says nothing and looks like a control called
    "input". The same trap the media renderer fell into with `![images](svg)`.
    """
    for candidate in (text, value):
        candidate = (candidate or "").strip()
        if candidate and candidate.lower() not in _CONTROL_TAGS:
            return candidate
    return ""


def _heading_mark(label: str) -> str:
    return "#" * _HEADINGS.get(label, 2) + " "


# One ASCII form per render class. Minimalist and structural: nothing here
# needs a colour, a box-drawing character, or anything markdown cannot say.
# The reader acts on these directly, so a control has to look like a control
# without anyone having decided what it is for.
_RENDER_FORM = {
    # Every form takes (value, text, label, target). Links and media carry
    # their target *in the line*, not only on the address: markdown that
    # leaves the REPL -- into a chunk, into the index, into a retrieval hit
    # -- used to arrive with no idea where anything pointed. The address
    # is how a reader enacts it; the markdown is how a reader reads it, and
    # both need to be true.
    "link":    lambda v, t, l, u="": (
        f"[{_control_label(t, v)}]({u})" if u and _control_label(t, v)
        else f"[{_control_label(t, v) or u}]"),
    "button":  lambda v, t, l, u="": f"( {_control_label(t, v) or chr(183)} )",
    "field":   lambda v, t, l, u="": f"[ ] {_control_label(t, v)}".rstrip(),
    "slider":  lambda v, t, l, u="": f"[ ] ={_control_label(t, v)}=",
    "choice":  lambda v, t, l, u="": f"[ ] {_control_label(t, v)}".rstrip(),
    "check":   lambda v, t, l, u="": f"[ ] {_control_label(t, v)}".rstrip(),
    "heading": lambda v, t, l, u="": _heading_mark(l) + (v or t),
    "item":    lambda v, t, l, u="": f"- {v or t}",
    "row":     lambda v, t, l, u="": f"| {v or t}",
    "cell":    lambda v, t, l, u="": (v or t),
    "quote":   lambda v, t, l, u="": f"> {v or t}",
    # A code BLOCK (a whole `pre`, G-233) is fenced; inline code stays ticked.
    "code":    lambda v, t, l, u="": (f"```\n{v or t}\n```" if "\n" in (v or t) else f"`{v or t}`"),
    # An image is its alt text and its source together, which is what makes
    # a stored chunk able to say what a picture showed.
    "image":   lambda v, t, l, u="": (
        f"![{_media_alt(t, v)}]({u or (v if _looks_like_url(v) else '')})"
        if (u or _looks_like_url(v)) else f"![{_media_alt(t, v)}]"),
    "media":   lambda v, t, l, u="": (
        f"({_media_alt(t, v) or 'media'})[{u or v}]"
        if (u or _looks_like_url(v)) else f"({_media_alt(t, v) or 'media'})"),
    "rule":    lambda v, t, l, u="": "---",
    "group":   lambda v, t, l, u="": (v or ""),
    "text":    lambda v, t, l, u="": ("\\" + v if v.startswith("#") else v),
    "none":    lambda v, t, l, u="": None,
}


def _render_unit(
    address: ContentAddress,
    value: str,
    label: str,
    text_at_node: str = "",
    target: str = "",
    alone: bool = False,
) -> Optional[str]:
    """One address plus its value as one markdown line, or None to suppress.

    The content tag decides the markdown form. That is the whole of the
    mapping: THEORY Def. 10.1's `K` is a flat eighteen-label set with no
    order and no operation, so a lookup is the only thing that can be done
    with it, and anything richer would be reading structure into a label set
    that does not carry any.
    """
    value = " ".join(value.split())
    cat = address.category

    if address.tag in _SUPPRESSED_TAGS:
        # ... unless it is the only unit the element has.
        #
        # `interactive.links` is suppressed because an anchor also yields its
        # href as a `urls.*` unit and its words as a `text.visible` one, so
        # drawing it too would print `[a]` beside them. That held while its
        # value WAS the tag name.
        #
        # It now carries the anchor's own label, and an anchor can have
        # nothing else: arxiv's `Disable MathJax` is an `<a>` with no href,
        # no handler, and its words folded into an all-inline parent, so this
        # unit is all there is and suppressing it drew the control nowhere.
        # 106 anchors over 16 corpus pages, each one words the page shows.
        #
        # `alone` is counted at the call site, which is the only place that
        # knows what else sits at this element. An anchor with an href still
        # has two units and still draws exactly one line.
        if (alone and address.tag == "interactive.links"
                and not _echoes_its_element(address, value)):
            return f"[{value}]"
        return None

    # A render class, from the live path. It is drawn as what it *is*, with
    # no branch anywhere below asking what it might have meant: a search box
    # is a field because it is a field, and a pager is links because they are
    # links. The tagger's category vocabulary follows underneath, unchanged,
    # for the offline path that still speaks it.
    # A line that carries a target is a link, whatever else it is.
    #
    # When an anchor's href is suppressed because something inside it speaks,
    # the words are drawn and the destination has to travel with them or the
    # affordance becomes unreachable. Hacker News votes with
    # `<a href="vote?id=..."><div title="upvote"></div></a>`: nothing in that
    # anchor is text, so the line that speaks is the div's title, and drawn
    # as plain text it has no slot for a destination. The reader could see the
    # arrow and not vote.
    #
    # `_target_of` already walks up to find the anchor; this is what makes the
    # answer visible. Only for classes with nowhere else to put it -- a link,
    # an image and a media unit each name their own target already.
    if (target and address.tag in _RENDER_FORM
            and address.tag not in ("link", "image", "media")):
        return _RENDER_FORM["link"](value, text_at_node or value, label,
                                    target)
    if address.tag in _RENDER_FORM:
        return _RENDER_FORM[address.tag](value, text_at_node or value, label,
                                         target)
    if cat == "media":
        # A media detection whose value is the element's *tag name* — an
        # inline `<svg>`, a `<source>` whose url was picked up elsewhere —
        # rendered as `![images](svg)`, which reads as an image located at
        # "svg". Associated Press's front page said it 384 times. There is no
        # target to name, so none is named.
        # The page's own words for the picture, when it gave any. An `<img>`
        # carries its `alt` as a separate `text.accessible` address at the
        # same element, which `text_at` already holds -- so "A Light in the
        # Attic" was sitting there while every picture on the page drew as
        # `![images]`, named after its taxonomy. `_media_alt` is the existing
        # rule for choosing between them and it refuses a value that is only
        # a file path, which is the thing that must not become a caption.
        # And NOTHING when the page gave none. `address.subcategory` was the
        # fallback, which draws the TAXONOMY as the caption: a page with
        # fifteen unnamed icons rendered `![images]` fifteen times, telling a
        # reader nothing except which detector fired. `![]` is the honest
        # form and markdown's own for an image whose alt is absent.
        alt = _media_alt(text_at_node, "")
        if _is_tag_name(value):
            return f"![{alt}]"
        return f"![{alt}]({value})"
    if cat == "urls":
        # The words and the destination on ONE line.
        #
        # The tagger path names an address by what it HELD (`urls.internal`)
        # where the sensor names it by what it IS (`link`), and every
        # link-shaped rule above keys on the sensor's spelling. So an anchor
        # the tagger folded drew twice --
        #
        #     </target>
        #     Glacial Retreat Calculator
        #
        # the href and its own words as two lines at one xpath, where a
        # reader wants `[Glacial Retreat Calculator](/target)`. 53.7% of the
        # corpus's `urls.*` addresses have their words at their own xpath and
        # every one of them was drawn this way.
        #
        # Not when the words ARE the url: `[https://x](https://x)` says the
        # same thing twice and `<https://x>` is the honest form for a bare
        # target.
        words = " ".join((text_at_node or "").split())
        if words and words != value:
            return _RENDER_FORM["link"](value, words, label, value)
        return f"<{value}>"
    if cat == "json_data":
        return f"`{value}`"
    if cat == "interactive":
        # A control renders as what it is, so the REPL can find it by reading
        # the markdown rather than by consulting a second index. The label is
        # the element's own text where it has one, since the detection's value
        # is only the tag name.
        shown = text_at_node or value
        # ... unless that value is only the element's own tag name.
        #
        # `_own_name` falls back to the tag when a page leaves a control
        # unnamed, so `shown` became the taxonomy's word for the element and
        # the render drew `[ ] input`, `( button )`, `=== form ===`. Measured
        # over the 3,135 exported notes: 136 lines named after their tag,
        # `form` x78, `label` x34, `input` x20.
        #
        # The mark already says a control is here. Adding the tag says it a
        # second time in the vocabulary of the detector rather than of the
        # page, which is exactly what the goal's quality bar rules out. The
        # bare mark under-claims, which is this renderer's standing direction.
        #
        # `_echoes_its_element` is the existing predicate for this question --
        # it compares the value against the address's own last step, so it
        # needs no list of tags to maintain.
        if _echoes_its_element(address, shown):
            shown = ""
        sub = address.subcategory
        # A control that *is* a heading keeps both facts. 34% of the corpus's
        # headings contain a control or a link, and where the control's own
        # rendering consumed the text — a footer accordion whose `<h5>` holds
        # a toggle — the heading marker was the casualty: `( Products )` with
        # nothing saying it heads a section. It is a level-N heading and it is
        # a button; the line can say so.
        mark = "#" * _HEADINGS[label] + " " if label in _HEADINGS else ""
        if sub == "inputs":
            return f"{mark}[ ] {shown}".rstrip()
        if sub in ("buttons", "event_handlers"):
            # An element carrying an `onclick` is a button in every way that
            # matters here: `kind_for` classifies it as one, and the REPL
            # clicks it like one. It used to fall through to the `[shown]`
            # form below, which meant two things, both bad. It read as an
            # empty input field — `[div[onclick]]` next to a real input's
            # `[ ] Search` — and because the widget repainted it as a button,
            # every one of them came back `( [div[onclick]] )`. That was 495
            # lines over 24 of the 136 corpus pages, and it is the third time
            # a renderer and this parser disagreed about a control's form, so
            # the fix is to have one form fewer rather than one kind more.
            return f"{mark}( {shown} )"
        if sub == "forms":
            return f"{mark}=== {shown} ==="
        return f"{mark}[{shown}]"

    # text.*
    if label in _HEADINGS:
        return "#" * _HEADINGS[label] + " " + value
    if label in _LIST_ITEMS:
        return "- " + value
    if label in _QUOTES:
        return "> " + value
    if label in _CODE:
        return f"`{value}`"
    # A value that opens with `#` *is* a markdown heading, and some are not:
    # `<meta name="theme-color" content="#14181C">` put two hex colours at the
    # top of letterboxd.com's output as `#14181C` and `#445566`, indexed and
    # rendered as headings. Hashtags, `#1 bestseller` and `#include` are the
    # same shape. Escaped so the line reads as text and the reader that keys
    # on `startswith("#")` is not fooled.
    if value.startswith("#"):
        return "\\" + value
    return value


def _drawn_as_control(text: str) -> bool:
    """Whether a line is already drawn as something a reader acts on.

    Tested on the *rendered form*, not on the tag. Both extraction paths are
    in play and they name controls differently -- `field` on the live path,
    `interactive.inputs` on the snapshot one -- so a check against either
    vocabulary passes the other straight through. It did: a label absorbed a
    control, the widget layer re-wrapped the result, and 135 lines across the
    corpus came back as `=== My Reading Lists: === label === ===` and
    `( compound-operator: ( show ) )`.

    The glyphs are the one thing both paths agree on, because there is one
    renderer.
    """
    stripped = text.strip()
    return stripped.startswith(("( ", "[ ] ", "=== ", "[", "!["))         or stripped.endswith((" )", " ==="))


def _target_of(owner: str, href_at: Dict[str, str]) -> str:
    """Where the element at ``owner`` points, or the nearest ancestor does.

    An anchor's href is on the anchor and its words are on a text node under
    it, and `href_at` is keyed by the element the href came from. When the
    words sit directly inside the anchor those are the same key and a direct
    lookup works, which is why this went unnoticed: `<a href>words</a>` is
    the common shape and it renders `[words](url)` correctly.

    A card does not have that shape. lit.dev writes
    `<a href><div><span>Spectrum Web Components</span></div></a>`, so the
    label's owner is `.../a/div/span`, the direct lookup misses, and the line
    renders `[Spectrum Web Components]` with nowhere to go. The href unit is
    separately suppressed -- correctly, the anchor speaks and a raw url
    beside its own label is noise -- so the target was not merely unrendered,
    it was gone from the markdown entirely. 16 of 41 distinct targets on one
    page, every one of them a link a reader can see and follow.

    Walking up by prefix is exact rather than heuristic: a descendant's
    xpath *is* its ancestors', and the nearest ancestor holding an href is
    the anchor that contains this text. The loop is bounded by depth, and
    the first hit wins so an outer anchor never overrides an inner one.
    """
    direct = href_at.get(owner)
    if direct:
        return direct
    at = owner
    while "/" in at:
        at = at.rsplit("/", 1)[0]
        if not at:
            break
        found = href_at.get(at)
        if found:
            return found
    return ""


def _join_labels(lines: List[MarkdownLine]) -> List[MarkdownLine]:
    """A label line ending in a colon absorbs the line it labels.

    `Tags:` and `change, deep-thoughts` are one fact split across two
    elements, and split across two lines they read as a heading with no
    content followed by content with no heading.

    The rule itself is `vertiscope.core.content_tree._colon_join`, which has been
    in the tree since the §U work and was never wired into anything -- the
    module carries a note saying so, and saying that what gets indexed is
    supposed to be derived from it. This is the part of that which applies
    here. Its `_dedupe` deliberately is not: that one is chunk-scoped, and
    the element-scoped rule above replaced it precisely because chunk scope
    collapsed every card in a grid sharing a placeholder image down to one,
    taking each card's address with it.

    A control is never absorbed. `Base retreat rate (m/yr)` labels an input,
    and folding the input into its label would leave a line a reader can read
    and cannot type into.
    """
    from .core.content_tree import _colon_join

    out: List[MarkdownLine] = []
    i = 0
    while i < len(lines):
        cur = lines[i]
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        joinable = (
            nxt is not None
            and cur.text.rstrip().endswith(":")
            and not _drawn_as_control(cur.text)
            and not _drawn_as_control(nxt.text)
        )
        if joinable:
            joined = _colon_join([cur.text.rstrip(), nxt.text.strip()])
            if len(joined) == 1:
                # Addressed at the label, not at what it absorbed.
                #
                # The merged line begins with the label, so the label's
                # position is where the line starts on the page -- and the
                # absorbed element is frequently one the page never draws.
                # quotes.toscrape.com writes `<div class=tags>Tags: <meta
                # class=keywords content=...><a>...` : the words come from a
                # `display:none` meta, and taking that element's address
                # filed a line the reader can see under an element the reader
                # cannot. The wireframe places a unit by its owner's box, so
                # every one of those lines was dropped from the drawing --
                # ten of them on one page -- while markdown showed them.
                #
                # No geometry is consulted to decide this, and none may be:
                # markdown is the semantic projection and the style map is a
                # peripheral. The label being the head of the line is reason
                # enough on its own.
                out.append(MarkdownLine(cur.depth, joined[0], cur.address,
                                       absorbed=cur.absorbed + nxt.absorbed))
                i += 2
                continue
        out.append(cur)
        i += 1
    return out


#: Planted (`G-197`): the first url at an element names it, stand-in or not.
PLANT_PLACEHOLDER_TARGET = False

_DRAWN_SVG = re.compile(r"<(path|image|circle|ellipse|rect|polygon|polyline|line|g|text|use)\b", re.I)


def _is_placeholder(url: str) -> bool:
    """A lazy loader's stand-in: an inline picture that draws nothing.

    An SVG data url with no shape in it (`<svg viewBox='0 0 171 171'></svg>`,
    sized to reserve the picture's box), or a raster data url too small to be
    a picture (the 1x1 transparent GIF, ~70 bytes). A data url that draws is
    content and stays.
    """
    u = (url or "").strip()
    if not u.startswith("data:image/"):
        return False
    if u.startswith("data:image/svg+xml"):
        body = u.split(",", 1)[1] if "," in u else ""
        if ";base64" in u.split(",", 1)[0]:
            try:
                import base64
                body = base64.b64decode(body + "===").decode("utf-8", "replace")
            except Exception:                       # noqa: BLE001
                return False
        else:
            from urllib.parse import unquote
            body = unquote(body)
        return not _DRAWN_SVG.search(body)
    return len(u) < 200


#: An image line, as `_RENDER["image"]` draws it: `![alt](url)` or `![alt]`.
_MEDIA_LINE = re.compile(r"^!\[(?P<alt>[^\]]*)\](?:\((?P<url>[^)]*)\))?$")


def _join_media(lines: List[MarkdownLine]) -> List[MarkdownLine]:
    """One `<img>` is one line, not one line per accessor.

    An image element yields TWO detections -- `src` and `alt` -- and that is
    correct at the index: `ContentTag`'s key is
    `(xpath, category, subcategory, source_attr, sub)`, so an attribute is part
    of what is being addressed and the two are genuinely different findings.
    The fault is in the projection, which drew each as its own line:

        ![](https://s2.coinmarketcap.com/.../34466.png)      <- from `src`
        ![PENGU logo](https://s2.coinmarketcap.com/.../34466.png)

    Measured on `vaultws256`: 365 of 835 media-bearing chunks carried a pair
    like that, and the harm is not only doubling. The line holding the URL is
    the one WITHOUT the caption, so an image whose page gave a perfectly good
    alt still reaches a reader as a bare url -- which is what "empty images
    with no text" was reporting.

    `_dedupe` cannot do this and should not be asked to. It collapses by token
    subsumption and says so: *"URLs never collapse against prose and dedupe
    only on exact equality: a link and its label are different data even when
    the strings coincide."* That rule is right -- and a url and its alt are
    exactly a link and its label, so the pair survives it by design. They are
    one PICTURE all the same, and that is a fact about media rather than about
    tokens.

    Scoped to a single ELEMENT, like `_dedupe` and for the same recorded
    reason: a chunk-scoped version "collapsed every card in a grid sharing a
    placeholder image down to one, taking each card's address with it". Two
    images are merged only when they are the same element, so a grid of cards
    keeps one line each.

    The surviving address is the one carrying the URL. The url is the media's
    identity -- it is what `is_url` reports, what a `target` is read from, and
    what a reader clicks -- where the alt is a caption of it. The dropped
    address goes into `absorbed`, which exists for precisely this: *"other
    spellings of the same fact at the same element... what it needs is to
    remain findable."*
    """
    out: List[MarkdownLine] = []
    i = 0
    while i < len(lines):
        cur = lines[i]
        nxt = lines[i + 1] if i + 1 < len(lines) else None
        merged = None
        if nxt is not None and cur.address.xpath and \
                cur.address.xpath == nxt.address.xpath:
            a, b = _MEDIA_LINE.match(cur.text.strip()), \
                   _MEDIA_LINE.match(nxt.text.strip())
            if a and b:
                url = (a.group("url") or "") or (b.group("url") or "")
                alt = (a.group("alt") or "").strip() or \
                      (b.group("alt") or "").strip()
                # Only when they are the same picture. Two DIFFERENT urls at
                # one element is a `<picture>` with its sources, and keeping
                # one would drop a file the page might actually serve.
                same = not (a.group("url") and b.group("url")
                            and a.group("url") != b.group("url"))
                if url and same:
                    keeps_url = cur if a.group("url") else nxt
                    other = nxt if keeps_url is cur else cur
                    # `inline`, not `absorbed`, and the difference is not
                    # bookkeeping. `MarkdownLine` defines absorbed as an
                    # address whose "words are not separately visible" and
                    # inline as one "MERGED -- its words are visibly in this
                    # line and a reader can act on it there". The alt's words
                    # ARE in the merged line: it reads `![PENGU logo](url)`.
                    #
                    # It also decides whether the render is honest about
                    # itself. `covered` -- what the render DREW -- counts
                    # inline and not absorbed, and
                    # `test_suppressed_units_are_a_deliberate_choice_not_a_leak`
                    # asks with `covered`. Filing a visibly-drawn address as
                    # absorbed made 20 units read as vanished when their text
                    # was on screen the whole time.
                    merged = MarkdownLine(
                        cur.depth, f"![{alt}]({url})", keeps_url.address,
                        inline=keeps_url.inline + other.inline
                               + (other.address,),
                        absorbed=keeps_url.absorbed + other.absorbed)
        if merged is not None:
            out.append(merged)
            i += 2
            continue
        out.append(cur)
        i += 1
    return out


#: Accessors that name a target -- a place, a resource -- never words.
_TARGET_ACCESSORS = frozenset({"href", "src", "srcset", "data-src", "data-srcset",
                               "poster", "action", "formaction", "cite", "data",
                               "xlink:href", "background",
                               # the lazy loaders' (G-197), as the sensor names them
                               "data-lazy-src", "data-lazy-srcset", "data-original",
                               "data-original-src", "data-image", "longdesc"})

#: Where a lazy loader keeps the real picture until it is scrolled to.
_LAZY_ACCESSORS = frozenset({"data-src", "data-srcset", "data-lazy-src", "data-lazy-srcset",
                             "data-original", "data-original-src", "data-image"})

#: Planted (`G-152`): a live-path href compared as prose, as before.
PLANT_URL_AS_PROSE = False


def _dedupe(units: List[Tuple[ContentAddress, str, str]],
            dropped_out: Optional[Dict[str, List[ContentAddress]]] = None
            ) -> List[Tuple[ContentAddress, str, str]]:
    """Token-multiset subsumption, scoped to a single element.

    A hash can only say two units are equal (THEORY Prop. 19.3), so it cannot
    choose between them. Subsumption is a *partial order*, so it can: when one
    unit's tokens are a strict subset of another's, the superset is the better
    rendering and the subset goes. That is what collapses an ``aria-label``,
    a ``title`` attribute and the element's own text — three spellings of one
    fact — into a single line, keeping the fullest.

    URLs never collapse against prose and dedupe only on exact equality: a
    link and its label are different data even when the strings coincide.

    **Scope.** The original rule was chunk-scoped, and that was right when a
    chunk was one card: the repeated spellings it targets all live on one
    element. Once chunks merge siblings, chunk scope starts deleting *distinct
    nodes* that happen to share a string — every card in a grid carrying the
    same placeholder image collapses to one line, and with it every card's
    image address but the first. Since the address is the only link back to
    the document, that loses navigation, not just repetition.

    So the scope is the element. Repeated spellings of one fact are the same
    element by construction; the same text appearing on two elements is two
    facts about two places, and removing cross-element repetition is
    boilerplate stripping — a different mechanism, deliberately kept separate
    so the two cannot compound into content loss.
    """
    by_node: Dict[str, List[int]] = {}
    for i, (addr, _v, _l) in enumerate(units):
        by_node.setdefault(addr.xpath, []).append(i)

    # A TARGET by its accessor as well as its category (`G-152`). The live
    # path files a link's href under `link.anchor` -- category `link`, not
    # `urls` -- so the href joined the prose comparison, its tokens (https en
    # wikipedia org wiki konqueror) a strict superset of the title's
    # (konqueror), and the title was "subsumed" by its own url. Every table
    # link whose title matched its text vanished: Konqueror, KDE, KHTML on
    # Comparison_of_web_browsers. The accessor is the same on both paths.
    def is_target(addr: ContentAddress) -> bool:
        if addr.category in ("urls", "media"):
            return True
        if PLANT_URL_AS_PROSE:
            return False
        head = (getattr(addr, "accessor", "") or "").split("|")[0].split("[")[0]
        return head in _TARGET_ACCESSORS

    dropped = set()
    for indices in by_node.values():
        if len(indices) < 2:
            continue
        textual = [
            (i, token_multiset(units[i][1]))
            for i in indices
            if not is_target(units[i][0])
        ]
        # multiset -> token set for the subset test; multiplicity stays in the
        # key so "buy buy" and "buy" are not merged by the exact-match branch.
        as_sets = {i: frozenset(t for t, _ in ms) for i, ms in textual}
        seen_exact: Dict[Tuple, int] = {}
        for i, ms in textual:
            if not ms:
                continue        # digits/punctuation only: no basis to compare
            if ms in seen_exact:
                dropped.add(i)
                continue
            seen_exact[ms] = i
            for j, other in textual:
                if j == i or j in dropped or not other:
                    continue
                if as_sets[i] < as_sets[j]:
                    dropped.add(i)
                    break

        # A media unit naming only the element's tag was dropped here when a
        # real url existed at the same element — the `<img>` yielding both
        # `![images](img)` and `![images](media/cache/…)` looked like one image
        # described twice. `test_suppressed_units_are_a_deliberate_choice_not_
        # a_leak` disagreed, on 20 units, and it is right: those are two
        # *addresses* with different accessors (`text()` and `src`), and a
        # url/media address disappearing from the output is the one thing that
        # guard exists to prevent. Making the rendering honest — `![images]`,
        # with no invented target — was the half that was actually wrong.
        seen_urls = set()
        for i in indices:
            addr, value, _ = units[i]
            if not is_target(addr):
                continue
            if value in seen_urls:
                dropped.add(i)
            else:
                seen_urls.add(value)

    if dropped_out is not None:
        # Element-scoped by construction -- `by_node` groups on the exact
        # xpath -- so a drop and the unit that kept it share an element and
        # the owner needs no search.
        for i in dropped:
            address = units[i][0]
            dropped_out.setdefault(address.xpath.split("/text()")[0],
                                   []).append(address)
    return [u for i, u in enumerate(units) if i not in dropped]


def _collect(node: TrieNode, url_depth: int) -> List[Tuple[ContentAddress, str, str, int]]:
    """Every content unit under ``node`` as (address, value, label, depth).

    Depth is measured in *element* steps, so the tag and accessor segments —
    which are addressing machinery, not document structure — do not indent.
    """
    out: List[Tuple[ContentAddress, str, str, int]] = []

    def walk(n: TrieNode, label: str, depth: int) -> None:
        if n.is_leaf and n.address is not None:
            # A cell's rowspan/colspan is layout for `_tabulate`, not a line.
            if _is_span(n.address):
                return
            out.append((n.address, n.value, label, depth))
            return
        for child in _own_units_first(n.ordered_children()):
            # A child two levels from a leaf is the tag segment; below that is
            # the accessor. Neither is an element, so neither adds depth.
            is_element = child.depth > url_depth and not _is_terminal_pair(child)
            child_label = _label_of(child.segment) if is_element else label
            # A heading whose text lives entirely in child elements produced
            # no heading line at all, because the branch that handles an
            # element with block children emits only that element's *own*
            # text. The Guardian's headlines are
            #
            #     <h3><div>Technology</div><span>The backlash…</span></h3>
            #
            # so 124 of its 181 headings arrived as ordinary text. The words
            # were never lost — every one of them was in the output — but the
            # structure was, which is what a heading is for.
            #
            # Everything inside a heading is part of that heading, so the
            # label carries down. A nested heading takes over, which is the
            # only case where the inner one is the truer answer.
            if is_element and label in _HEADINGS and child_label not in _HEADINGS:
                child_label = label
            walk(child, child_label, depth + 1 if is_element else depth)

    walk(node, _label_of(node.segment), 0)
    return out


def _own_units_first(children: List[TrieNode]) -> List[TrieNode]:
    """An element's own detections, then its element children.

    `TrieNode.ordered_children` sorts by `doc_pos` and puts anything without
    one LAST -- which is right for the trie, where a tag/accessor segment is
    addressing machinery rather than a position in the document, and wrong
    for reading order, because those segments carry the element's OWN text.

    So a `<dt>` was drawn after the `<a>` inside it. Measured over eight
    corpus pages: 23 of 96 chunks came out in an order the page does not
    present, and 27 of the 31 inversions were exactly this -- a child drawn
    above its own parent.

    An element begins before anything inside it. That is what document order
    means, and it is what a reader expects from a list where the row's own
    line introduces the links in it.

    Relative order inside each group is untouched, so two of an element's own
    units, and two of its children, keep the order `ordered_children` gave
    them.
    """
    own, elements = [], []
    for child in children:
        (own if _is_terminal_pair(child) else elements).append(child)
    return own + elements


def _is_terminal_pair(node: TrieNode) -> bool:
    """True for the tag and accessor segments at the bottom of a path."""
    if node.is_leaf:
        return True
    kids = list(node.children.values())
    return bool(kids) and all(k.is_leaf for k in kids)


# Render classes that are *things* rather than prose. Each carries its own
# identity and its own name, so a run of them is a row of objects and never a
# sentence to be reassembled -- see `_join_inline`.
_OBJECT_CLASSES = frozenset({"image", "media", "rule"})


def _flow_owner(xpath: str) -> str:
    """The block element a run of inline text belongs to.

    Walks up from the leaf past every inline element -- `span`, `b`, `em`,
    `a` -- and stops at the first thing that starts a new line on the page.
    Two units sharing a flow owner are two pieces of one sentence.

    The inline set is `core.content_tagger._INLINE_TAGS`, which
    CONTENT_EXTRACTION_RULES §8.3 describes as being "used to decide
    line-joining during rendering" -- the exact job, listed since the
    original extraction and used by nothing on this path until now.
    """
    from .core.content_tagger import _INLINE_TAGS

    steps = xpath.split("/")
    while steps:
        label = steps[-1].split("[", 1)[0]
        if label.startswith("text()") or label in _INLINE_TAGS:
            steps.pop()
            continue
        break
    return "/".join(steps)


_TEX_WRAP = re.compile(r"^\{\\displaystyle\s*(.*)\}\s*$", re.S)


def _collapse_math(units: List[Tuple[ContentAddress, str, str, int]]
                   ) -> List[Tuple[ContentAddress, str, str, int]]:
    """Each math element, drawn ONCE, inline, as ``$TeX$``.

    MediaWiki ships a formula three times over for three audiences -- MathML
    glyphs, a TeX annotation, and a fallback SVG image with the TeX as its alt
    text -- plus the extension's own ``data-mw`` JSON on the wrapper. Rendered
    as they came, one inline symbol became five or six markdown lines and
    40-60 tokens: Wikipedia's *Suffix tree* definition, a heading, one
    sentence and a five-item list, came out as three chunks whose text was
    mostly ``{\\displaystyle S}`` repeated (2026-09-26). A reader sees one
    formula; the chunk should say it once.

    Only the PROJECTION changes: the trie still holds every one of those
    addresses, and the formula's line is anchored at its annotation's own
    address, a real element in the page. Keyed on the structure MathML
    defines (``math/semantics/annotation``), not on a site's class names.
    """
    # MediaWiki's own ``data-mw`` attribute (Parsoid's round-trip metadata --
    # template names, reference ids, i18n keys) is never shown to a reader;
    # drawn as a JSON line it filled chunks with `{"name":"ref",...}` (M-2).
    # Dropped from the projection only; the trie still holds it.
    units = [u for u in units
             if not str(getattr(u[0], "accessor", "")).startswith("data-mw")]
    tex_at: Dict[str, Tuple[int, str]] = {}
    for i, (a, v, _l, _d) in enumerate(units):
        x = a.xpath
        k = x.find("/math/")
        if k < 0 or "/semantics/annotation" not in x:
            continue
        tex = v.strip()
        m = _TEX_WRAP.match(tex)
        tex_at[x[:k]] = (i, (m.group(1) if m else tex).strip())
    if not tex_at:
        return units
    # The wrapper of each formula: the element holding the <math>'s parent,
    # which is where the fallback image and the extension's JSON sit.
    wrappers = {}
    for parent in tex_at:
        cut = parent.rfind("/")
        wrappers[parent[:cut] if cut > 0 else parent] = parent
    out: List[Tuple[ContentAddress, str, str, int]] = []
    for i, (a, v, lbl, d) in enumerate(units):
        x = a.xpath
        k = x.find("/math/")
        if k >= 0 and x[:k] in tex_at:
            hit = tex_at[x[:k]]
            if hit[0] == i:
                tex = "$%s$" % hit[1]
                # INLINE, in the sentence it sits in: the formula's own address
                # is deep in MathML, so as a line of its own it shared neither
                # the sentence's flow nor its depth, and a list item read
                # "numbered from" / "$1$" / "to" / "$n$" / "." (M-1). Folded
                # into the text before it when that text is the same flow.
                wrapper = x[:k].rsplit("/", 1)[0]
                if out and _flow_owner(out[-1][0].xpath) == _flow_owner(wrapper)                         and out[-1][0].render_class not in _OBJECT_CLASSES:
                    pa, pv, pl, pd = out[-1]
                    out[-1] = (pa, (pv.rstrip() + " " + tex).strip(), pl, pd)
                else:
                    out.append((a, tex, lbl, d))
            continue                         # the MathML glyphs
        base = x.split("/text()")[0]
        wrapper = next((w for w in wrappers if base == w or base.startswith(w + "/img")), None)
        if wrapper is not None:
            if base.startswith(wrapper + "/img"):
                continue                     # the fallback image and its link
            if str(a.tag).startswith("json_data") and v.lstrip().startswith(("{", "`{")):
                continue                     # the extension's own data-mw
        out.append((a, v, lbl, d))
    return out


def _join_inline(units: List[Tuple[ContentAddress, str, str, int]]
                 ) -> List[Tuple[ContentAddress, str, str, int]]:
    """Sentences broken by inline markup are put back together.

    A page writes `<p>This data is crucial for <b>tracking</b> ice loss</p>`
    and the fold, correctly, sees three text nodes. Rendered one per line
    that reads as three fragments, and the wireframe then took the fragments
    for a row and drew them as columns -- so one sentence became three
    columns of a table that does not exist.

    Joined only within one flow: same block ancestor, same render class,
    adjacent. The first unit's address carries the line, which is right for
    enactment too -- every fragment of a sentence inside one anchor goes to
    the same place, so pressing any of it should.

    A unit that is its own block is untouched, and so is any run that
    crosses a class boundary: a link inside a paragraph stays a link.
    """
    if len(units) < 2:
        return units
    # Which flows are MIXED content: a block holding inline markup as well as
    # its own text.
    #
    # This is what separates a sentence from a document. `<p>text <b>b</b>
    # more</p>` interleaves text children with inline elements, and its
    # fragments are one sentence. A text/plain file addresses every paragraph
    # as a direct text child of one `<pre>` with nothing between them, and
    # those are sixty paragraphs, not one.
    #
    # Joining every direct text child merged all sixty into a single line AT
    # EVERY WINDOW SETTING -- the context-window hyperparameter, which is the
    # knob this whole project exists to offer, stopped having any effect on
    # that shape of document.
    mixed = {
        _flow_owner(a.xpath) for a, _v, _l, _d in units
        if _flow_owner(a.xpath) != a.xpath.split("/text()")[0]
    }
    out: List[Tuple[ContentAddress, str, str, int]] = []
    for unit in units:
        address, value, label, depth = unit
        if not out:
            out.append(unit)
            continue
        prev = out[-1]
        joinable = (
            prev[0].tag == address.tag
            # A picture is not a sentence fragment.
            #
            # Joining is for prose broken by markup, and it decides by render
            # class and flow owner -- which an inline <svg> satisfies exactly
            # as an <em> does. github.com sets its customer logos as a row of
            # twenty inline svgs in one block, so all twenty merged into a
            # single line whose alt read "American Airlines Duolingo Ernst and
            # Young Ford ...": one picture named after twenty, and nineteen
            # addresses gone from the map with it.
            #
            # Objects carry their own identity and their own name. Only prose
            # is reassembled.
            # Asked of `render_class`, not of the raw tag, because the two
            # vocabularies spell this differently and only one of them was
            # covered. `_OBJECT_CLASSES` holds the SENSOR's names -- `image`,
            # `media` -- while the tagger path names the same element
            # `media.images`, so this guard did not fire for anything the
            # tagger found. An `<img>` yields two units at one element: its
            # tag-name fallback (`img`) and its `src`, same tag, same flow
            # owner, and the src is a relative path so `_looks_like_url` says
            # no. They joined. Every tagger-found picture in the corpus drew
            # as `![images](img media/cache/....jpg)` -- an alt that names the
            # taxonomy and a target with the element's name glued to the
            # front, which is not a url and cannot be fetched.
            #
            # "Is this an object rather than prose" is exactly what the
            # eighteen classes answer, which is the case `render_class`'s
            # docstring says to use it for.
            and address.render_class not in _OBJECT_CLASSES
            and _flow_owner(prev[0].xpath) == _flow_owner(address.xpath)
            # A block's own text children join, but only inside a flow
            # that holds inline markup -- see `mixed` above.
            #
            # This used to require the text to sit inside an inline element,
            # so `<p>text <a>link</a> more</p>` rejoined the link's words and
            # left the paragraph's own two fragments as separate lines. On
            # duckduckgo a character counter written as three text nodes --
            # `0`, `/`, `500` -- drew as three lines of a document, which is
            # the shape a reader reads as three facts.
            #
            # The guard was there to stop a run joining across an intervening
            # block. Adjacency now does that instead: units arrive in
            # document order, so a block between two text children lands
            # between them here and breaks the run by having a different flow
            # owner. Before reading order was observed rather than derived,
            # that was not true and this guard was standing in for it.
            and (_flow_owner(address.xpath)
                 != address.xpath.split("/text()")[0]
                 or _flow_owner(address.xpath) in mixed)
            and not _looks_like_url(value)
            and not _looks_like_url(prev[1])
            # Depth is NOT asked (D-36). An inline element between two text
            # children adds an element step when the trie keeps it as its own
            # level -- the live capture's does; the Python scan's collapses
            # it -- so "A <span>suffix trie</span> is a trie ..." arrived at
            # depths 9, 10, 9 and stayed three bullets in both panel forms.
            # Same flow owner and adjacency already mean one block's text.
        )
        if joinable:
            # The same words twice is one spelling, not two (`G-152`): a link
            # whose title IS its text joined to "Konqueror Konqueror".
            if " ".join(value.split()).casefold() == " ".join(prev[1].split()).casefold():
                merged = prev[1].strip()
            else:
                merged = (prev[1].rstrip() + " " + value.lstrip()).strip()
            out[-1] = (prev[0], merged, prev[2], min(prev[3], depth))
            continue
        out.append(unit)
    return out


def _render_node(
    node: TrieNode,
    url: str,
    url_depth: int,
    memo: Optional["RenderMemo"] = None,
) -> MarkdownChunk:
    return _render_sized(node, url, url_depth, memo)[0]


def _draw_lines(kept: List[Tuple[ContentAddress, str, str]],
                *,
                text_at: Dict[str, str],
                href_at: Dict[str, str],
                depth_of: Dict[str, int],
                base: int) -> List[MarkdownLine]:
    """Everything decided AFTER `_dedupe`, and nothing decided before it.

    **`kept` is the only unit list this function receives, and that is the
    point.** Three defects in one session came from asking a DEFERENCE rule --
    one where a unit stands down because another will speak for it -- before
    `_dedupe` had said which units survive:

    * `alone` counted the units COLLECTED at an element, so an anchor whose
      words had already been collapsed still looked accompanied and suppressed
      itself: `<a>Disable MathJax</a>` drew nothing at all.
    * `consumed` was built the same way, so Wikimedia's
      `<button aria-label="Move Main menu to sidebar">` deferred its text to a
      button that subsumption had already dropped. That element drew nothing.
    * the url branch below had it too, and its comment is where the rule was
      first written down: "taken from `kept`, not from `units`, so the text is
      only dropped when the line that will speak for it actually survives."

    Three statements of one invariant, none of which stopped the next
    instance, because a comment is not a constraint. Taking only `kept` makes
    the wrong version unwriteable: `units` is not in scope here.

    **Which rules belong here.** A deference rule aimed at the SAME element
    must; one aimed at a DESCENDANT need not. `_dedupe` is element-scoped, so
    it can remove a competing spelling beside a unit but never the last
    speaker at a descendant -- which is why `hidden`/`spoken_below`, asking
    whether anything below speaks, has never had this bug and stays where it
    is, before `kept` exists and feeding it.

    `text_at` and `href_at` are lookups, not deference. They answer "what
    words are at this element" about the DOCUMENT, and a control is still
    named by the page's words even when the text unit carrying them lost its
    own line, so they are built from the collected units on purpose.
    """
    # A control speaks for the text at its element, so the bare repeat goes --
    # the `( Add to basket ) / Add to basket` duplication. Read from `kept`,
    # because a control that did not survive cannot consume anything.
    consumed = {
        a.xpath for a, _v, _lbl in kept
        if a.category == "interactive"
        and a.tag not in _SUPPRESSED_TAGS
        and text_at.get(a.xpath)
    }
    # The same rule in the render-class vocabulary, from the live path.
    # Recorded by element, because that is where the control is and the text
    # is one step below it.
    consumed |= {
        a.xpath.split("/text()")[0] for a, _v, _lbl in kept
        if a.tag in _CONSUMING_CLASSES
        and text_at.get(a.xpath.split("/text()")[0])
    }

    # A tagger-path link drawing its own words has said them, so the bare
    # repeat underneath goes -- the `( Add to basket ) / Add to basket`
    # duplication one vocabulary further on.
    #
    # Taken from `kept`, not from `units`, so the text is only dropped when
    # the line that will speak for it actually survives. This is the trap
    # `_dedupe` records above: the href hidden because the anchor speaks and
    # the words consumed because the link would draw them, so on a
    # search-results page both went and the result had no title at all.
    # Whichever is dropped, exactly one has to remain, and reading `kept`
    # is what makes that structural rather than hopeful.
    consumed |= {a.xpath for a, v, _lbl in kept
                 if a.category == "urls" and v.strip()
                 and " ".join((text_at.get(a.xpath) or "").split()) not in
                 ("", " ".join(v.split()))}

    # How many units still stand at each element, which is a different
    # question from how many arrived.
    #
    # `units_at` above counts what was COLLECTED, and `alone` -- the escape
    # that lets a suppressed `interactive.links` draw itself when nothing
    # else speaks for its element -- was asked of that. So an anchor whose
    # words `_dedupe` had already collapsed still looked accompanied: the
    # exact-tie branch keeps `interactive.links` and drops the `text.visible`
    # carrying the same string, then suppression fired on the survivor
    # because the count said two. Neither drew, and `<a>Disable MathJax</a>`
    # -- an anchor with no href, the very case the `alone` escape was added
    # for -- disappeared from the page entirely. Not merely unpressable:
    # the words were gone.
    #
    # This is the trap `consumed` records ten lines down, in the same
    # function, for the same reason: "taken from `kept`, not from `units`, so
    # the text is only dropped when the line that will speak for it actually
    # survives". `alone` needed the same treatment and did not get it.
    drawn_at: Dict[str, int] = {}
    for _a, _v, _lbl in kept:
        if (_v or "").strip():
            _owner = _a.xpath.split("/text()")[0]
            drawn_at[_owner] = drawn_at.get(_owner, 0) + 1

    lines = []
    # (element, drawn text) -> the line that already said it.
    #
    # `_dedupe` compares RAW values and cannot see this: a `<button onclick>`
    # yields an `interactive.buttons` detection valued by `_own_name` and an
    # `interactive.event_handlers` one valued `button[onclick]`, which share
    # no tokens, so both survive correctly on what that rule can see. The
    # duplication only appears here, where `_render_unit` draws BOTH from
    # `text_at[owner]` and numpy's docs print `( Go Back )` twice.
    #
    # This is the same shape as `consumed` -- "the duplication appears later,
    # when `_render_unit` draws the control using the text unit's value" --
    # which handles control-against-text and not control-against-control.
    # 208 lines over the corpus, 203 of them this exact pair.
    drawn_here: Dict[Tuple[str, str], int] = {}
    for a, v, lbl in kept:
        if not v.strip():
            continue
        owner = a.xpath.split("/text()")[0]
        if (a.category == "text" and a.xpath in consumed
                and " ".join(v.split()) == text_at.get(a.xpath)):
            continue
        if (a.tag in ("text", "heading") and owner in consumed
                and " ".join(v.split()) == text_at.get(owner)):
            continue
        target = _target_of(owner, href_at)
        rendered = _render_unit(a, v, lbl, text_at.get(owner, ""),
                                target=target,
                                alone=drawn_at.get(owner, 0) <= 1)
        if rendered is None:
            continue
        # A line drawn as a link is addressed as one.
        #
        # The address is what the REPL enacts through, and it finds controls
        # by render class. A line promoted to the link form because it carries
        # a target -- Hacker News's `<a href="vote?..."><div title="upvote">`
        # draws `[upvote](vote?id=...)` -- kept `text` as its class, so it read
        # as a link and could not be pressed. Visible and inert is worse than
        # absent: the reader is told an affordance is there and it is not.
        #
        # The trie is untouched; this is the class carried *out* of it on the
        # rendered line, which is the thing the REPL acts on.
        # Depth is keyed on the *original* address: the tag is part of an
        # address key, so promoting first loses the lookup.
        depth = depth_of[a.key()] - base
        if (target and a.tag in _RENDER_FORM
                and a.tag not in ("link", "image", "media")):
            a = replace(a, tag="link")

        # One element does not say the same thing twice. The second detection
        # keeps its ADDRESS, on the surviving line's `inline`, because it is a
        # real affordance -- the `onclick` half of that button is what makes
        # it pressable on the live path -- and dropping the line must not drop
        # the handle. This is the lesson `_carry_affordance` records one
        # commit earlier: suppressing a rendering is not licence to discard an
        # address.
        here = (owner, rendered)
        prior = drawn_here.get(here)
        if prior is not None:
            was = lines[prior]
            if a.key() != was.address.key():
                lines[prior] = replace(was, inline=was.inline + (a,))
            continue
        drawn_here[here] = len(lines)
        lines.append(MarkdownLine(depth=depth, text=rendered, address=a))
    return lines


def _render_sized(
    node: TrieNode,
    url: str,
    url_depth: int,
    memo: Optional["RenderMemo"] = None,
) -> Tuple[MarkdownChunk, int]:
    """Render ``node``, with its rendered length, possibly from the memo.

    Returns the memo's own object on a hit rather than a copy. The descent
    calls this speculatively -- to find out whether a subtree fits the window
    before deciding to keep or split it -- and every ancestor of a node asks
    the question about a render that contains it, so copying on each hit cost
    a copy of the page per level of nesting. Measured on a 1,600-item list:
    6,405 lines emitted, 25,619 lines served, four copies of the page to draw
    it once.

    The caller owns the clone instead, and does it once, at the point a chunk
    is committed to the output -- where the count is one copy per emitted
    line by construction. **A chunk returned from here must be treated as
    read-only until then**, because it may be the memo's.

    The length is carried alongside because `MarkdownChunk.chars` rebuilds the
    whole string to measure it, and the fit test asks for nothing else. It is
    the pre-levelling length, which is what the descent compares against the
    window; `_level_page` rewrites depths afterwards and does not consult it.
    """
    key = _memo_key(node, url, "node", 0) if memo is not None else None
    if key is not None:
        cached = memo.get(key)
        if cached is not None:
            memo.reused_lines += len(cached[0].lines)
            return cached

    units = _join_inline(_collapse_math(_collect(node, url_depth)))
    xpath = _xpath_of(node, url)
    if not units:
        empty = (MarkdownChunk(url=url, xpath=xpath, lines=[]), 0)
        if key is not None:
            memo.put(key, empty)
        return empty

    # Indentation is measured from the page, not from the chunk.
    #
    # Rebasing to each chunk's own shallowest unit made the margin jump at
    # every chunk boundary: a document assembled from fourteen chunks had
    # fourteen different left edges, and the reader saw the chunker's seams
    # instead of the page's nesting. The chunker's decisions are not
    # structure, and nothing on screen should say they are.
    # `_collect` measures depth from the chunk's own root, so every chunk
    # starts its content at zero however deep in the page that root sits.
    # Rebasing to the chunk's shallowest unit kept it that way, and a
    # document assembled from fourteen chunks had fourteen different left
    # edges -- the reader saw the chunker's seams instead of the page's
    # nesting. The chunker's decisions are not structure.
    #
    # Offsetting by the root's own depth puts every chunk on the page's
    # margin instead of its own.
    base = -(node.depth - url_depth)
    depth_of = {a.key(): d for a, _, _, d in units}

    # A control's own text, for labelling it. Taken before dedup so that a
    # label surviving only as part of a longer sibling still names its button.
    # element -> where it points. The mirror of `text_at`: an anchor's words
    # are on the text node below it and its target on the element, and a
    # markdown link needs both in one line. Dropping the href to the address
    # kept the link *enactable* and made the markdown lossy -- text carried
    # out of the REPL, into a chunk, into the index, arrived with no idea
    # where it pointed.

    href_at: Dict[str, str] = {}
    text_at: Dict[str, str] = {}
    for a, v, _lbl, _d in units:
        if a.tag in ("link", "image", "media") and a.is_url:
            if PLANT_PLACEHOLDER_TARGET and a.accessor.split("|", 1)[0].split("[", 1)[0] in _LAZY_ACCESSORS - {"data-src"}:
                continue
            # A lazy loader's stand-in never names the picture while the
            # element holds a real one: WP Rocket writes an empty SVG to
            # `src` and the photograph to `data-lazy-src`, and taking the
            # first url drew every recipe card on copykat as the empty SVG
            # -- 30 stand-ins on one page, the photographs' addresses kept
            # and their urls never drawn (G-197, 2026-10-18). Planted:
            # `PLANT_PLACEHOLDER_TARGET`.
            k, u = a.xpath.split("/text()")[0], v.strip()
            held = href_at.get(k)
            if held is None or (not PLANT_PLACEHOLDER_TARGET
                                and _is_placeholder(held) and not _is_placeholder(u)):
                href_at[k] = u
    for a, v, _lbl, _d in units:
        if not v.strip():
            continue
        # Keyed by the *element*, not by the text node. On the live path a
        # text child has its own address -- `.../a/text()[1]` -- while the
        # href sits on `.../a`, so keying by the text's own xpath meant a
        # link never found its own words. Every result on a search page drew
        # as its raw href: `[//duckduckgo.com/l/?uddg=https%3A%2F%2F...]`
        # where the page plainly says "Glacial Retreat Calculator".
        owner = a.xpath.split("/text()")[0]
        if a.category == "text" or a.tag in ("text", "heading"):
            text_at.setdefault(owner, " ".join(v.split()))
        elif a.tag == "interactive.links" and not _echoes_its_element(a, v):
            # A link's own words, carried on its interactive detection.
            #
            # An anchor inside all-inline prose has its text folded into the
            # paragraph's single unit, so there is no `text.visible` at the
            # anchor to label it with -- which is why links drew as bare
            # targets. `content_tagger` puts the label on the detection it
            # already emits for that element rather than adding a second one,
            # so `an inline-only subtree is still one detection` still holds:
            # that rule counts TEXT units and this is not one.
            #
            # `setdefault` is deliberate: a real text unit at the same
            # element always wins, so this only fills a gap.
            #
            # Guarded by `_is_tag_name` because the value falls back to the
            # tag when the anchor genuinely has no words -- `<a name=...>` --
            # and `[a](/x)` would be worse than `</x>`.
            text_at.setdefault(owner, " ".join(v.split()))


    # One anchor, one line.
    #
    # An anchor produces two units: its href, on the element, and its words,
    # on the text node below -- which inherits the link class and so also
    # draws as a link. Both drawn, every search result appeared twice, once
    # as its title and once as its raw redirect href, and the nested anchors
    # a results page wraps around each hit multiplied that to four.
    #
    # The words win. The href is not lost: it stays on the line's address,
    # which is what the reader enacts and what the link graph is built from.
    # A link with no words anywhere below it keeps its line and shows its
    # target, because nothing else will say where it goes.
    spoken = {
        a.xpath.split("/text()")[0]
        for a, v, _lbl, _d in units
        if v.strip() and not a.is_url
        and (a.tag in _CONSUMING_CLASSES or a.tag in ("text", "heading"))
    }

    def spoken_below(xpath: str) -> bool:
        if xpath in spoken:
            return True
        prefix = xpath + "/"
        return any(o.startswith(prefix) for o in spoken)

    hidden = {
        a.key() for a, v, _lbl, _d in units
        if a.tag == "link" and a.is_url
        and spoken_below(a.xpath.split("/text()")[0])
    }

    # A control with nothing to say, wrapped around one that has something,
    # is not a line either. A page's header renders its category button three
    # times -- the button, the span inside it, the text inside that -- and two
    # of those are blank. Measured on one page, 41 of 301 lines were `(  )`
    # or `[ ]`: one line in seven saying nothing at all.
    #
    # A control that is genuinely unlabelled still gets a line. It is a real
    # affordance and a reader has to be able to reach it; drawn as `( · )` it
    # is visibly a control rather than an empty pair of brackets.
    hidden |= {
        a.key() for a, v, _lbl, _d in units
        if a.tag in _CONSUMING_CLASSES
        and not _control_label(text_at.get(a.xpath.split("/text()")[0], ""), v)
        and spoken_below(a.xpath.split("/text()")[0])
    }

    # A control wrapped around a control saying the same thing is one
    # control. A number field rendered as `[ ] 15` and then `[ ] 15` again a
    # level deeper -- the element and the wrapper around it both carrying the
    # value -- so every input on a form appeared twice.
    #
    # The inner one wins: it is the element a reader acts on, and the outer
    # is the box drawn around it.
    labelled: Dict[str, List[str]] = {}
    for a, v, _lbl, _d in units:
        if a.tag not in _CONSUMING_CLASSES:
            continue
        shown = _control_label(text_at.get(a.xpath.split("/text()")[0], ""), v)
        if shown:
            labelled.setdefault(shown, []).append(a.xpath.split("/text()")[0])
    for shown, paths in labelled.items():
        if len(paths) < 2:
            continue
        for outer in paths:
            if any(inner != outer and inner.startswith(outer + "/")
                   for inner in paths):
                hidden |= {
                    a.key() for a, v, _lbl, _d in units
                    if a.tag in _CONSUMING_CLASSES
                    and a.xpath.split("/text()")[0] == outer
                    and _control_label(
                        text_at.get(outer, ""), v) == shown
                }

    # One target, one line. A results page wraps two or three anchors around
    # each hit, all pointing at the same redirect, and only one of them holds
    # the words. The others are not ancestors of it -- they are siblings in a
    # card -- so the "wrapped around something that speaks" rule never saw
    # them, and each result kept a line of raw redirect url beside its title.
    #
    # Sharing a target is what makes them one link. The one with words wins;
    # if none has words the first keeps its line, because something has to
    # say where it goes.
    speaks = {
        a.xpath.split("/text()")[0]
        for a, v, _lbl, _d in units
        if v.strip() and not a.is_url
    }
    by_target: Dict[str, List] = {}
    for a, v, _lbl, _d in units:
        if a.tag == "link" and a.is_url:
            by_target.setdefault(v.strip(), []).append(a)
    for target_url, addresses in by_target.items():
        if len(addresses) < 2:
            continue
        speaking = [a for a in addresses
                    if a.xpath.split("/text()")[0] in speaks]
        winner = speaking[0] if speaking else addresses[0]
        hidden |= {a.key() for a in addresses if a.key() != winner.key()}

    # Not done, and measured rather than argued: collapsing a name restated
    # down a *containment chain*.
    #
    # lit.dev's footer says "YouTube" three times for one link -- the anchor's
    # `aria-label`, the `lazy-svg` component inside it, and that component's
    # `<svg><title>` -- and all three draw. Neither rule above sees it:
    # `_dedupe` is scoped to a single element, and the `labelled` rule wants a
    # control inside a control. So a chain rule was written: keep the
    # interactive unit, or the outermost, and hide strict descendants that
    # repeat its name; consider only units already surviving, so it could
    # never empty a chain on its own.
    #
    # It still cost more than it bought.
    #
    #     lit.dev      dedup 90.4 -> 92.7%   wireframe 98.1 -> 96.8%
    #     salesforce   dedup 91.9 -> 92.0%   wireframe 95.5 -> 93.7%
    #                  markdown 99.2 -> 98.7%   over-dedup 0 -> 4
    #
    # About a point of deduplication for four units of *loss* and a point or
    # two of recall on both projections. Over-dedup is the dangerous
    # direction -- every spelling of a thing gone -- and a rule that trades
    # coverage for tidiness is the wrong trade at any exchange rate. Reverted.
    #
    # What the attempt showed: sameness of rendered text is not enough to
    # justify hiding, because two elements in one chain can carry the same
    # words and still be two things a reader needs -- a labelled control and
    # the picture that labels it. A future rule needs a reason beyond
    # "these strings match", and the measurement above is what it has to beat.

    kept = [t for t in _dedupe([(a, v, lbl) for a, v, lbl, _ in units])
            if t[0].key() not in hidden]




    lines = _draw_lines(kept, text_at=text_at, href_at=href_at,
                        depth_of=depth_of, base=base)
    if not PLANT_KEEP_CONTENTLESS:
        lines = _fold_contentless(lines)
    rendered = MarkdownChunk(url=url, xpath=xpath,
                             lines=_inline_flow(_join_labels(_join_media(lines))))
    # Measured in the window's unit, not in characters, and over the string
    # a MODEL is given rather than the one a reader is served. `.chars` is
    # still `.chars`; this is the number the descent compares against
    # `window`, and the two are only the same when the unit in force is
    # characters. `tokens.budget` drops link targets first: 52.5% of this
    # corpus's rendered tokens are addresses, so counting them made a
    # 256-token window a 121-token one for anything anyone would read.
    sized = (rendered, tokens.budget(rendered.markdown))
    if key is not None:
        memo.put(key, sized)
    return sized


#: A rendered link: `[words](target)`. Non-greedy on the label so a line
#: holding two of them yields two matches rather than one spanning both.
_LINK_RE = re.compile(r"\[([^\]]+)\]\(((?:[^()]|\((?:[^()]|\([^()]*\))*\))*)\)")


def _fold_links_into_prose(lines: List[MarkdownLine]) -> List[MarkdownLine]:
    """A link inside a sentence belongs in the sentence, not above it.

    `_inline_flow` solves this for the SENSOR path, where a paragraph arrives
    as a ladder of fragments and merging adjacent lines rebuilds it. The
    tagger path has the opposite shape: `content_tagger` emits an all-inline
    paragraph as ONE text unit holding every word, and each anchor as its own
    unit. Nothing is adjacent to merge, so a paragraph came out as

        [retreat rates](/rates)
        [mass balance](/mass)
        See the retreat rates and mass balance .

    -- the words twice, and the links stripped out above the prose they
    belong to. So the operation here is substitution rather than
    concatenation: put each link's markup back where its words already sit in
    the parent's text, and drop the line that was standing in for it.

    Only within one parent and only where the words are actually there. A
    link whose label does not appear in the prose keeps its own line, because
    that line is then the only place those words exist.

    The anchor's address rides on `inline`, which is what keeps it enactable:
    `read()` marks a control from the line that drew it, and after this the
    line that draws the link is the sentence.
    """
    if len(lines) < 2:
        return lines

    # Link lines, by the parent whose prose could hold them. Keyed on the
    # element's parent, since an anchor's words live in its parent's text.
    from collections import defaultdict

    candidates = defaultdict(list)
    for i, line in enumerate(lines):
        if line.address is None:
            continue
        match = _LINK_RE.fullmatch(line.text.strip())
        if not match:
            continue
        words = match.group(1).strip()
        if not words:
            continue
        parent = line.address.xpath.rstrip("/").rsplit("/", 1)[0]
        candidates[parent].append((i, words, line.text.strip(), line.address))

    if not candidates:
        return lines

    folded = {}                     # index -> new MarkdownLine
    folded_away = set()             # indices of link lines to drop
    # Not `consumed`: that name means the deference set in `_draw_lines`,
    # and one word for two ideas in one module is how a rule gets checked
    # in the wrong place.
    for i, line in enumerate(lines):
        if line.address is None or i in folded_away:
            continue
        kids = candidates.get(line.address.xpath.rstrip("/"))
        if not kids:
            continue
        text = line.text
        added = []
        # Document order, so two links with the same words land in the order
        # the page has them.
        for j, words, markup, address in sorted(kids):
            if j == i or j in folded_away:
                continue
            at = text.find(words)
            if at < 0:
                continue            # the prose does not say it; leave its line
            text = text[:at] + markup + text[at + len(words):]
            folded_away.add(j)
            added.append(address)
        if added:
            folded[i] = MarkdownLine(depth=line.depth, text=text,
                                     address=line.address,
                                     inline=line.inline + tuple(added),
                                     absorbed=line.absorbed)

    if not folded_away:
        return lines
    return [folded.get(i, line) for i, line in enumerate(lines)
            if i not in folded_away]


def _inline_flow(lines: List[MarkdownLine]) -> List[MarkdownLine]:
    """A sentence with a link in it is one line.

    `_join_inline` puts prose fragments back together on the *unit* side, but
    only where they agree on render class and depth. Real markup agrees on
    neither: text inside an `<a>` or an `<em>` is one level deeper than the
    paragraph's own text and carries the inline element's class. So a
    paragraph came out as a ladder --

        'Monthly solutions resolve basin-scale mass change, and'      depth 0
        '[the GRACE-FO record](https://nasa.gov/grace)'               depth 1
        'continues the series into'                                   depth 0
        '2024'                                                        depth 1
        'with better coverage of'                                     depth 0

    -- where a reader sees one sentence. This runs after rendering instead,
    which is the point: by here the anchor is already `[words](target)`, so
    folding it into the prose keeps the link *in* the sentence rather than
    stripping it to text.

    Merged only within one flow: same block ancestor, and only across the
    inline elements. Objects keep their own line -- an image is a thing on
    the page and not a word in a sentence -- and a run that crosses into
    another block stops, because that block is a different paragraph.

    The merged addresses are kept on the line rather than dropped. Reading
    and acting are different questions and this answers only the first; a
    caller that wants the link still has it.
    """
    if len(lines) < 2:
        return lines
    out: List[MarkdownLine] = []
    for line in lines:
        prev = out[-1] if out else None
        if prev is None or not _flows_together(prev, line):
            out.append(line)
            continue
        merged = (prev.text.rstrip() + " " + line.text.lstrip()).strip()
        out[-1] = MarkdownLine(
            depth=min(prev.depth, line.depth), text=merged,
            address=prev.address,
            inline=prev.inline + (line.address,),
            absorbed=prev.absorbed + line.absorbed)
    return out


#: Render classes that are their own thing on the page rather than a word in
#: a sentence. An image interrupting a paragraph is still an image.
_STANDALONE = frozenset({"image", "media", "rule", "heading", "control",
                         "button", "field", "check", "choice"})


def _flows_together(prev: MarkdownLine, line: MarkdownLine) -> bool:
    """Are these two rendered lines part of one run of prose?"""
    a, b = prev.address, line.address
    if a is None or b is None:
        return False
    # Prose only, decided by the ACCESSOR rather than the tag.
    #
    # `_STANDALONE` below is written in render-class vocabulary -- `image`,
    # `control` -- and the offline path speaks the tagger's instead:
    # `urls.internal`, `text.visible`, `media.tag`. So a pager's href line
    # passed the class check and was merged into the prose beside it, and
    # `classify_controls` then looked for "Next" in `</page/2/> - Next` and
    # found no label at all.
    #
    # An accessor is the same on both paths: `text()` is the words a reader
    # sees, `href` and `src` are targets. A sentence is made of the first
    # kind only, and an anchor's words are a `text()` accessor -- which is
    # why a link still folds in, carrying its target with it.
    if not (_is_text_accessor(a) and _is_text_accessor(b)):
        return False
    if a.tag in _STANDALONE or b.tag in _STANDALONE:
        return False
    # And by the rendered FORM, for the same reason: a heading is `# words`
    # and a control is `( words )` or `[ ] words` on both paths, whatever
    # either vocabulary calls them. Merging a heading into the prose under it
    # erased every "control inside a heading" on the eurostat page -- which a
    # non-vacuity guard noticed, because the test that watches that invariant
    # asserts the pattern still exists before testing it.
    if _drawn_as_its_own_thing(prev.text) or _drawn_as_its_own_thing(line.text):
        return False
    if _is_bare_target(prev.text) or _is_bare_target(line.text):
        return False
    # One flow: the same block once the inline elements are stripped off.
    owner = _flow_owner(a.xpath)
    if owner != _flow_owner(b.xpath):
        return False
    # At least one side is inline, OR the run has already begun.
    #
    # The first clause is what keeps sixty paragraphs of a text/plain file
    # apart: they are bare text children of one `<pre>` with no markup
    # between them, so no run ever starts. The second is what lets a
    # sentence finish: `<p>text <b>b</b> more</p>` merges the bold in, and
    # then `more` is a bare child again -- with the first clause alone the
    # sentence stopped dead after the markup it was interrupted by.
    started = bool(prev.inline)
    return (started
            or owner != a.xpath.split("/text()")[0]
            or owner != b.xpath.split("/text()")[0])


#: Rendered prefixes that mean "this line is a thing, not a word". A heading,
#: a control, a checkbox, a rule. Written as forms rather than as classes
#: because both the live and the offline path draw them the same way while
#: naming them differently.
_OWN_LINE_FORMS = ("#", "( ", "[ ] ", "[x] ", "===", "---", "- ", "* ")


def _drawn_as_its_own_thing(text: str) -> bool:
    stripped = (text or "").lstrip()
    return stripped.startswith(_OWN_LINE_FORMS)


def _is_text_accessor(address: ContentAddress) -> bool:
    """Does this address name words a reader sees, or a machine value?

    `text()` and `text()@<offset>` are the reader's; `href`, `src`, `title`,
    `aria-label` and `@control` are not. The accessor is the same on the
    offline and the live path, which the tag is not.
    """
    return (getattr(address, "accessor", "") or "").startswith("text()")


def _is_bare_target(text: str) -> bool:
    """Is this line a target, rather than a line with a target inside it?

    `_looks_like_url` answers the first question for a *value*, and it says
    yes to a rendered markdown link because `[words](https://x)` contains
    `://`. Used here unmodified it refused to fold any link into a sentence
    -- which is the one thing this merge exists to do, since by this point
    the anchor is already `[words](target)` and folding it in is what keeps
    the link inside the prose rather than stripped out of it.
    """
    stripped = (text or "").strip()
    if not stripped or stripped.startswith(("[", "![", "<")):
        return False
    # A target is one token. Testing "contains a url" instead poisoned every
    # line it had already merged a link into: once the prose held
    # `[words](https://x)`, the NEXT fragment of the same sentence was
    # refused because the line it would join now contained `://`. So a
    # paragraph merged its first link and then stopped dead.
    if len(stripped.split()) > 1:
        return False
    return bool(_looks_like_url(stripped))


def _xpath_of(node: TrieNode, url: str) -> str:
    """Reconstruct the chunk root's absolute xpath from its trie path."""
    return getattr(node, "_xpath_cache", "") or "/"


# --- the recursive descent --------------------------------------------------


@dataclass
class RenderReport:
    """Where every addressed unit went.

    Rendering silently losing units is the failure mode that a chunk count
    cannot show, so the accounting is returned rather than logged:
    ``rendered + deduped + suppressed + empty == addresses`` is an identity
    a caller can assert. Anything not in one of those four buckets is a bug,
    and ``unaccounted`` is what names it.
    """

    addresses: int = 0
    rendered: int = 0
    deduped: int = 0
    suppressed: int = 0
    empty: int = 0

    @property
    def unaccounted(self) -> int:
        return self.addresses - (
            self.rendered + self.deduped + self.suppressed + self.empty
        )

    def summary(self) -> Dict[str, int]:
        return {
            "addresses": self.addresses,
            "rendered": self.rendered,
            "deduped": self.deduped,
            "suppressed": self.suppressed,
            "empty": self.empty,
            "unaccounted": self.unaccounted,
        }


class RenderMemo:
    """Reuse of subtree renders across successive renders of a live page.

    The trie applies a mutation in O(delta); the projection read out of it
    was O(page), so the fused result was O(page) per change -- measured at
    27/128/405 ms of markdown for a *one node* insertion into a 100/400/1600
    item list. The descent re-rendered every subtree on the page to answer
    questions it had already answered.

    The invalidation signal is `TrieNode.exact_hash`, the trie's strict
    Merkle: equal hashes mean the subtree renders byte-identically, so a
    cached render may be handed out in place of doing the work. Note it is
    *not* `subtree_hash` -- that one is blind to word order and punctuation
    by design, and a projection prints values verbatim.

    Two generations, rotated per render. An entry survives a render only if
    it was consulted during it, which bounds the cache at roughly one page of
    live subtrees without needing a size cap or a clock. In steady state --
    the same page, edited repeatedly -- every clean sibling of the dirty path
    is consulted each render and so stays resident, while a subtree that has
    left the page falls out after one rotation.

    Cached chunks are cloned on both store and hit. `_level_page` and
    `_number_parts` rewrite depths and ordinals on the returned chunks after
    the descent, and a cache that handed out the same objects would let one
    render's levelling corrupt the next one's input.
    """

    __slots__ = ("_prev", "_cur", "hits", "misses", "reused_lines",
                 "peeks", "skipped_fit_tests")

    def __init__(self) -> None:
        self._prev: Dict[tuple, object] = {}
        self._cur: Dict[tuple, object] = {}
        self.hits = 0
        self.misses = 0
        self.reused_lines = 0
        self.peeks = 0
        # Ancestors whose own render was never needed, because a child was
        # already known to be too big. See `_overflows_by_a_child`.
        self.skipped_fit_tests = 0

    def get(self, key: tuple):
        entry = self._cur.get(key)
        if entry is None:
            entry = self._prev.get(key)
            if entry is None:
                self.misses += 1
                return None
            self._cur[key] = entry          # consulted, so it survives
        self.hits += 1
        return entry

    def peek(self, key: tuple):
        """A lookup that answers from cache or not at all.

        `get` is for a caller that will do the work on a miss; this is for one
        asking a question it can also decline to answer. Promotes on a hit, so
        the entry survives the rotation like any other consulted entry, and is
        counted separately: a `peek` that misses is not a cost the way a `get`
        that misses is.
        """
        entry = self._cur.get(key)
        if entry is None:
            entry = self._prev.get(key)
            if entry is None:
                return None
            self._cur[key] = entry
        self.peeks += 1
        return entry

    def put(self, key: tuple, value) -> None:
        self._cur[key] = value

    def rotate(self) -> None:
        self._prev, self._cur = self._cur, {}

    @property
    def resident(self) -> int:
        return len(self._prev) + len(self._cur)


def _clone_chunk(chunk: MarkdownChunk) -> MarkdownChunk:
    """A copy that the page-global passes may safely rewrite.

    Applied at every point a chunk is committed to the output, without asking
    whether a memo is in play. Skipping it when there is no memo would be
    correct and is not worth the second rule: measured at 0.33 ms of a 177 ms
    render at 1,600 lines and 1.67 ms of 734 ms at 6,400 -- 0.2% either way.
    One rule, "chunks are cloned on commit", is what keeps `_level_page` from
    rewriting the depths inside the memo.
    """
    return MarkdownChunk(
        url=chunk.url,
        xpath=chunk.xpath,
        # `inline` travels with the copy. Dropped here, a sentence that had
        # merged its links read correctly and arrived with no record of what
        # was folded into it -- the reading was right and the affordances
        # were gone, which is the half of the bargain this field exists to
        # keep.
        lines=[MarkdownLine(depth=l.depth, text=l.text, address=l.address,
                            absorbed=l.absorbed,
                            inline=l.inline)
               for l in chunk.lines],
        part=chunk.part,
    )


def _memo_key(node: TrieNode, url: str, kind: str, window: int) -> Optional[tuple]:
    """The cache key for ``node``, or None where the node cannot be keyed.

    A node with no `exact_hash` has never been through `rehash`, which means
    nothing can be said about whether its render is current. Refusing to key
    it degrades to the uncached path rather than serving a stale subtree.
    """
    if not node.exact_hash:
        return None
    # The unit is part of the key. A cached size is a number in whichever
    # unit was in force when it was taken, and serving a character count to a
    # token window silently makes every chunk three times too big.
    return (kind, url, getattr(node, "_xpath_cache", None), window,
            tokens.name(), node.exact_hash)


def _absorbed_by_element(trie: AddressTrie,
                         url: str) -> Dict[str, List[ContentAddress]]:
    """element -> the spellings the collapse drops there.

    Computed from the trie, not from render-time drops, and that distinction
    is the whole reason this exists as a separate pass.

    The first attempt collected drops inside `_render_sized` and attached
    them there. `_render_sized` runs SPECULATIVELY at every level `_size_of`
    and `_descend` consider, and is memoised, so which call observes a drop
    depends on how the chunker descended -- which is exactly what the context
    window changes. The covered set then moved with the window, and
    `test_no_address_is_lost_when_the_window_changes` exists for that
    property: 4 addresses differed at window 200.

    The trie does not move with the window. `_dedupe` is element-scoped, so
    running it over every unit at once gives each element the same verdict it
    would get in any subtree, and the answer is a property of the document.

    This is the same correction the prose fold needed: a pass whose result
    must not depend on the descent belongs outside it.
    """
    units: List[Tuple[ContentAddress, str, str]] = []
    for node in trie.leaves():
        address = node.address
        if address is None or not (node.value or "").strip():
            continue
        units.append((address, node.value, address.tag))
    out: Dict[str, List[ContentAddress]] = {}
    _dedupe(units, out)
    return out


def _suppressed_controls(trie: AddressTrie) -> Dict[str, ContentAddress]:
    """element -> an affordance address the render might not draw there.

    Every control, not only the suppressed tags. Suppression is one way an
    affordance address fails to reach a line and it is not the only one:
    `_dedupe` drops a control whose words another unit at the same element
    subsumes, and Wikimedia's `<button aria-label="Move Main menu to
    sidebar">move to sidebar</button>` is exactly that -- the aria-label wins
    on tokens and the line ends up addressed `text.accessible`. The words are
    drawn and the button is not pressable. Visible and inert, which this
    module elsewhere calls worse than absent.

    Whether the address is actually needed is decided by `_carry_affordance`,
    which only carries an element's control when no line at that element is
    addressed as one. Collecting them all here and filtering there keeps the
    reason for carrying in one place.

    `_SUPPRESSED_TAGS` was the original reason and remains the largest: an
    anchor also yields its href and its words, so drawing its
    `interactive.links` unit too would print `[a]` beside them. But
    `_render_unit` returns None to suppress, and a unit that draws no line
    leaves no address -- so suppressing the RENDERING silently discarded the
    ADDRESS, which is the only thing that says the line is pressable.

    Measured over the 136-page corpus before this existed: 71,866
    `interactive.links` addresses made, 7,325 surviving anywhere in the
    output -- 89.8% lost -- against 0.2% of inputs and 0.1% of forms, which
    have no competing unit to be suppressed in favour of. Anchors are 88% of
    every affordance on the corpus, so the interactive surface drew most
    hyperlinks as dead text.

    Derived from the trie rather than collected during the render, for the
    reason `_absorbed_by_element` records: `_render_sized` runs speculatively
    at every level the chunker considers, so anything gathered inside it
    moves with the context window. This does not.
    """
    out: Dict[str, ContentAddress] = {}
    for node in trie.leaves():
        address = node.address
        if address is None or not (node.value or "").strip():
            continue
        if address.is_control:
            out.setdefault(address.xpath.split("/text()")[0], address)
    return out


def _carry_affordance(chunks: List[MarkdownChunk],
                      controls: Dict[str, ContentAddress]) -> None:
    """Put the suppressed control on the line, in `inline`. Never in the slot.

    The first version of this promoted the control into `line.address` when
    the line WAS the anchor, which read well and broke the crawl.

    `line.address` is the only thing the store persists per line: the
    `Anchors` edge is one address per line by contract, keyed on `ord`, and
    `Workspace.links_from` reads it back through `addresses_of` to build the
    crawl frontier -- "no separate link extractor: a link is a `urls.*`
    address, which the trie already holds". Promoting the control therefore
    pushed the anchor's `urls.internal` address out of the store, and a page
    full of anchors produced an empty frontier.
    `test_links_come_from_the_stored_addresses` caught it, which is what it is
    for.

    So the address slot stays exactly as the render chose it, and the control
    rides in `inline` -- already defined as the addresses a line merged and a
    reader can act on there. That is enough for the two things that were
    actually missing: `covered` accounts for the affordance, and
    `graphstore._link_hyperlinks` gives it a chunk.

    It is NOT enough to make the affordance visible to a consumer reading the
    store, because `inline` is not persisted either. That consumer asks
    `addresses_at(element)` instead -- see `obsidian.sidecar.chunk_payload`.
    The alternative was widening the `Anchors` contract, and one address per
    line is depended on by the jsonl round-trip, the depth recovery and the
    REPL alike.

    One element is claimed once, in chunk and line order, because repeating a
    control down every line that mentions it says nothing extra.
    """
    # Elements the render already addressed as controls. Those need nothing:
    # a button drawn as `( Add to basket )` says so through its own address,
    # and adding a second control address beside it would claim two
    # affordances where the page has one.
    #
    # Checked across the whole address set, not just `line.address`, because
    # the duplicate-line rule already parks a second detection in `inline` --
    # a `<button onclick>` keeps its handler there, and that element is
    # served.
    drew_a_control: set = set()
    for chunk in chunks:
        for line in chunk.lines:
            if line.address is None:
                continue
            for held in (line.address,) + tuple(line.inline):
                if held.is_control:
                    drew_a_control.add(held.xpath.split("/text()")[0])

    claimed: set = set()
    for chunk in chunks:
        for i, line in enumerate(chunk.lines):
            if line.address is None:
                continue
            added = []
            # The line's own element, and every element folded into it: an
            # anchor inside a sentence rides here as its href, so its element
            # is reachable even though the line is addressed elsewhere.
            for carried in (line.address,) + tuple(line.inline) + tuple(line.absorbed):
                owner = carried.xpath.split("/text()")[0]
                control = controls.get(owner)
                if control is None or owner in claimed:
                    continue
                if owner in drew_a_control:
                    continue            # the render already said it is one
                claimed.add(owner)
                added.append(control)
            if added:
                chunk.lines[i] = replace(
                    line, inline=tuple(line.inline) + tuple(added))


def _name_the_collapse(chunks: List[MarkdownChunk],
                       absorbed: Dict[str, List[ContentAddress]]) -> None:
    """Give every line the spellings its element lost.

    Every line at an element claims them, not the first: which line is first
    depends on where the chunker cut, and coverage is a property of the
    chunk rather than of how many lines it took to draw. `covered` is asked
    as a set by every caller that asks it.
    """
    for chunk in chunks:
        given: set = set()
        for i, line in enumerate(chunk.lines):
            if line.address is None:
                continue
            owner = line.address.xpath.split("/text()")[0]
            if owner in given:
                # Once per element per chunk. Giving every line at an owner
                # the same set is correct for findability and costs 19x the
                # entries -- 121,398 tuple slots for 6,401 distinct facts
                # over twenty pages -- because memoisation and cloning leave
                # many lines sharing an element. One line carrying it is
                # enough for anything scanning the chunk.
                continue
            taken = absorbed.get(owner)
            if not taken:
                continue
            given.add(owner)
            # Never itself: a line does not speak for the address it IS.
            keep = tuple(a for a in taken if a.key() != line.address.key())
            if keep:
                chunk.lines[i] = replace(line, absorbed=keep)


def render_trie(
    trie: AddressTrie,
    *,
    context_window: int = DEFAULT_CONTEXT_WINDOW,
    report: Optional[RenderReport] = None,
    memo: Optional[RenderMemo] = None,
) -> List[MarkdownChunk]:
    """Render every page in the trie into context-window-sized chunks.

    The descent is top-down and greedy: take the largest subtree that fits.
    A subtree that does not fit splits into its children; a single leaf that
    does not fit is emitted whole, because a cut leaf would be described by
    an address that over-claims what the chunk contains.

    Pass a :class:`RenderReport` to find out where every unit went.
    """
    chunks: List[MarkdownChunk] = []

    for url in trie.urls():
        steps = url_steps(url)
        page = trie.node_at(steps)
        if page is None:
            continue
        # The one copy. Everything below hands back memo-owned objects, and
        # the two page-global passes that follow rewrite depths and ordinals
        # in place.
        chunks.extend(_clone_chunk(c) for c in
                      _descend(page, url, len(steps), context_window, memo))

    # Folded once per finished chunk, never inside the descent:
    # `_size_of` and `_descend` call `_render_sized` speculatively at
    # every level they consider, and an O(lines x links) pass there took
    # the 30-page render from 22.2s to past 500s.
    for chunk in chunks:
        chunk.lines = _fold_links_into_prose(chunk.lines)

    # Named after the fold, so a line that merged links still reports what
    # its element collapsed. Both are post-passes for the same reason.
    for url in trie.urls():
        _name_the_collapse(chunks, _absorbed_by_element(trie, url))
        break

    # Last, so it sees the lines the fold and the collapse-naming settled on:
    # an anchor folded into a sentence is a different line than the one that
    # entered those passes, and the affordance belongs on the line a reader
    # actually sees. It only ever appends to `inline`; the address slot is
    # what the store persists and the crawl reads back.
    _carry_affordance(chunks, _suppressed_controls(trie))

    # Tables as tables (`D-5`, `M-3`): after the affordances are carried, so a
    # row line holds every cell's addresses, and before the depths are levelled.
    if not PLANT_NO_TABLES:
        # Each table's header row, from wherever on the page it was drawn --
        # read before any chunk is rewritten (`D-9`).
        layouts = _table_layouts(chunks, {} if PLANT_NO_SPANS else _cell_spans(trie))
        for chunk in chunks:
            chunk.lines = _tabulate(chunk.lines, layouts)
    # The page repeating itself, drawn once (`D-4`, `M-8`).
    if not PLANT_STRUCTURAL_NOISE:
        for chunk in chunks:
            chunk.lines = _fold_structural(chunk.lines)

    _level_page(chunks)
    # The lenient bound, held after every pass that can grow a chunk (`G-86`);
    # a re-cut piece is levelled again on its own (R-K1: levels per chunk).
    recut = _recut(chunks, context_window)
    if len(recut) != len(chunks):
        fresh = [c for c in recut if not any(c is k for k in chunks)]
        _level_page(fresh)
        chunks[:] = recut
    _number_parts(chunks)
    if memo is not None:
        memo.rotate()

    if report is not None:
        # Computed after the fact rather than accumulated during the descent:
        # _render_node runs speculatively to test whether a subtree fits, so
        # counting inside it would tally the same unit at every level it was
        # considered at. The descent partitions the leaves, so comparing the
        # emitted anchors against the trie is exact.
        _fill_report(trie, chunks, report)
    return chunks


#: Planted (`D-5`): a table drawn one cell per line, as before.
PLANT_NO_TABLES = False

# The row key keeps its section: `thead/tr` and `tbody/tr` are different rows
# (one key merged a header with the first data row, 2026-10-11).
_CELL = re.compile(r"^(.*/table(?:\[\d+\])?)/((?:(?:thead|tbody|tfoot)(?:\[\d+\])?/)?"
                   r"tr(?:\[\d+\])?)/((?:td|th)(?:\[\d+\])?)(?:/|$)")


#: Planted (`D-9`): a row away from its header carries bare values, as before.
PLANT_NAKED_ROWS = False


def _cell_text(ls: List[MarkdownLine]) -> str:
    return " ".join(" ".join(l.text.split()) for l in ls)


_SPAN_ACCESSORS = frozenset({"rowspan", "colspan"})

#: Planted (`D-5`): spans ignored -- a cell under a rowspan lands in the
#: first free column, as it did ("Linux" under "Name").
PLANT_NO_SPANS = False


def _is_span(address: ContentAddress) -> bool:
    return (getattr(address, "accessor", "") or "").split("|")[0] in _SPAN_ACCESSORS


def _one_is_bare(xpath: str) -> str:
    """`td[1]` and `td` name one element; the two paths spell it both ways."""
    return re.sub(r"\[1\](?=/|$)", "", xpath)


def _ordinal(step: str) -> int:
    m = re.search(r"\[(\d+)\]$", step)
    return int(m.group(1)) if m else 1


def _cell_spans(trie: AddressTrie) -> Dict[str, Tuple[int, int]]:
    """Every spanned cell's (rowspan, colspan), by its element's xpath."""
    out: Dict[str, Tuple[int, int]] = {}
    for leaf in trie.leaves():
        a = leaf.address
        if a is None or not _is_span(a):
            continue
        try:
            v = max(1, int(str(leaf.value).strip()))
        except ValueError:
            continue
        key = _one_is_bare(a.xpath)
        rs, cs = out.get(key, (1, 1))
        if a.accessor.split("|")[0] == "rowspan":
            rs = v
        else:
            cs = v
        out[key] = (rs, cs)
    return out


def _table_layouts(chunks: List[MarkdownChunk],
                   spans: Dict[str, Tuple[int, int]]) -> Dict[str, Dict]:
    """Each table laid out once for the page, as a browser lays it out.

    A cell takes the first column its row has free; a rowspan/colspan holds
    the cells below and beside it (`D-5`: under a five-row span Konqueror's
    "Linux" went under "Name"). Read across every chunk of the page, because
    a fragment's rows sit under spans from rows another chunk holds. A row's
    cells are its `th`s then its `td`s by ordinal, so an empty cell -- which
    draws no line -- still takes its column.

    Returns table -> {width, pos: (row, cell) -> (column, colspan), names}:
    the column names from the first all-`th` row (`D-9`), a `colspan` header
    naming every column it covers.
    """
    rows_by_table: Dict[str, Dict[str, Dict[str, List[MarkdownLine]]]] = {}
    for chunk in chunks:
        for line in chunk.lines:
            m = _CELL.match(line.address.xpath) if line.address else None
            if not m:
                continue
            table, rowkey, cell = m.groups()
            cell = _one_is_bare(cell)
            rows_by_table.setdefault(table, {}).setdefault(rowkey, {}).setdefault(cell, []).append(line)
    out: Dict[str, Dict] = {}
    for table, rows in rows_by_table.items():
        held = set()
        pos: Dict[Tuple[str, str], Tuple[int, int]] = {}
        width = 0
        for ri, (rowkey, cells) in enumerate(rows.items()):
            nth = max((_ordinal(c) for c in cells if c.startswith("th")), default=0)
            ntd = max((_ordinal(c) for c in cells if c.startswith("td")), default=0)
            seq = ([("th" if k == 1 else "th[%d]" % k) for k in range(1, nth + 1)]
                   + [("td" if k == 1 else "td[%d]" % k) for k in range(1, ntd + 1)])
            col = 0
            for cell in seq:
                while (ri, col) in held:
                    col += 1
                rs, cs = spans.get(_one_is_bare(table + "/" + rowkey + "/" + cell), (1, 1))
                for dr in range(rs):
                    for dc in range(cs):
                        held.add((ri + dr, col + dc))
                pos[(rowkey, cell)] = (col, cs)
                col += cs
                width = max(width, col)
        names: Optional[List[str]] = None
        for rowkey, cells in rows.items():
            if len(cells) >= 2 and all(c.startswith("th") for c in cells):
                names = [""] * width
                for cell, ls in cells.items():
                    # A column's NAME is its cell's content, not the cell's own
                    # attributes: a sortable header's `th` carries "Sort ascending".
                    inner = [l for l in ls if not _one_is_bare(l.address.xpath).endswith("/" + cell)]
                    nm = re.sub(r"!?\[([^\]]*)\](\([^)]*\)|<[^>]*>)", r"\1", _cell_text(inner or ls))
                    col, cs = pos[(rowkey, cell)]
                    for dc in range(cs):
                        if col + dc < width:
                            names[col + dc] = nm
                break
        out[table] = {"width": width, "pos": pos, "names": names}
    return out


def _row_head(members: List[MarkdownLine]) -> Optional[MarkdownLine]:
    """The member whose address a row line carries: the first one drawn as
    content. A control's address names a control, and a row line carrying it
    repaints as one -- GitHub's file table drew `Name: ( View all files )` and
    read it back as `( Name: ( View all files ) )`. None when every member is
    a control or a picture: that row is not a row of values."""
    for l in members:
        t = l.text.strip()
        if t and not _is_control_glyph(t) and not t.startswith("!["):
            return l
    return None


_LINK_LINE = re.compile(r"^\[[^\]]*\]\(")


def _is_control_glyph(t: str) -> bool:
    """A row member drawn as a CONTROL -- a button `( label )`, a checkbox
    `[ ] `, a select `=== `, a field `[ text ]` -- not merely a line that
    starts with `[` or ends with ` )`. `_drawn_as_control`'s broad test took
    a LINK (`[Space complexity](...)`) and Big-O (`O( n )`) for controls, and
    Wikipedia's "Time complexity" table fell back to a cell per line
    (2026-10-18). Planted `PLANT_BROAD_ROW_CONTROL`: the broad test."""
    if PLANT_BROAD_ROW_CONTROL:
        return _drawn_as_control(t)
    if _LINK_LINE.match(t):
        return False
    return (t.startswith(("[ ] ", "[x] ", "=== ")) or t.endswith(" ===")
            or (t.startswith("( ") and t.endswith(" )"))
            or (t.startswith("[") and t.endswith("]")))


#: Planted: a row's head is chosen by the broad control test, as before.
PLANT_BROAD_ROW_CONTROL = False


def _row_line(members: List[MarkdownLine], text: str) -> MarkdownLine:
    head = _row_head(members) or members[0]
    extra: List[ContentAddress] = list(head.inline)
    for l in members:
        if l is head:
            continue
        extra.append(l.address)
        extra.extend(l.inline)
    # Depth 0: indented four spaces, a pipe table is a code block.
    row = replace(head, depth=0, text=text, inline=tuple(extra))
    if hasattr(head, "absorbed"):
        row = replace(row, absorbed=tuple(a for l in members for a in getattr(l, "absorbed", ())))
    return row


def _tabulate(lines: List[MarkdownLine],
              layouts: Optional[Dict[str, Dict]] = None) -> List[MarkdownLine]:
    """Draw a table's cells as a markdown table, one line per row (`D-5`).

    The goal names "a hierarchically-header-structured markdown document with
    tables, images, web links", and a table arrived as one line per cell. A
    run of one table's cell lines becomes pipe rows placed by the table's
    layout (`_table_layouts`): each value in the column the page shows it in,
    a column a span holds left blank. A fragment AWAY from its header names
    each value by its column instead (`D-9`): `Name: value · Name: value`.
    No separator row: lines pair one-to-one with addresses in the printed
    form, and it is drawn where markdown is displayed (`with_table_separators`).

    No address is lost: the row line keeps its first cell's address and every
    other cell's -- and everything they had inline -- rides on its `inline`.
    """
    out: List[MarkdownLine] = []
    i = 0
    n = len(lines)
    while i < n:
        m = _CELL.match(lines[i].address.xpath) if lines[i].address else None
        if not m:
            out.append(lines[i])
            i += 1
            continue
        table = m.group(1)
        run: List[Tuple[str, str, MarkdownLine]] = []
        j = i
        while j < n:
            a = lines[j].address
            mm = _CELL.match(a.xpath) if a else None
            if not mm or mm.group(1) != table:
                break
            run.append((mm.group(2), _one_is_bare(mm.group(3)), lines[j]))
            j += 1
        rows: List[Tuple[str, List[Tuple[str, List[MarkdownLine]]]]] = []
        for tr, cell, line in run:
            if not rows or rows[-1][0] != tr:
                rows.append((tr, []))
            cells = rows[-1][1]
            if not cells or cells[-1][0] != cell:
                cells.append((cell, []))
            cells[-1][1].append(line)
        lay = (layouts or {}).get(table)
        placed = lay is not None and all((tr, c) in lay["pos"] for tr, cells in rows for c, _ls in cells)
        if not placed:
            out.extend(line for _tr, _c, line in run)
            i = j
            continue
        width, names = lay["width"], lay["names"]
        has_header = all(c.startswith("th") for c, _ls in rows[0][1])
        if any(_row_head([l for _c, ls in cells for l in ls]) is None for _tr, cells in rows):
            out.extend(line for _tr, _c, line in run)
            i = j
            continue

        def text_of(c: str, ls: List[MarkdownLine]) -> str:
            # A cell's own-element label ("Sort ascending") is not its content.
            return _cell_text([l for l in ls if not _one_is_bare(l.address.xpath).endswith("/" + c)] or ls)

        if names and not has_header and not PLANT_NAKED_ROWS:
            for tr, cells in rows:
                pairs = []
                for c, ls in cells:
                    col, _cs = lay["pos"][(tr, c)]
                    pairs.append((col, names[col] if col < len(names) else "", text_of(c, ls)))
                pairs.sort(key=lambda t: t[0])
                text = " · ".join((h + ": " + v) if h else v for _col, h, v in pairs if v)
                out.append(_row_line([l for _c, ls in cells for l in ls], text))
            i = j
            continue
        if len(rows) < 2 or width < 2:
            out.extend(line for _tr, _c, line in run)
            i = j
            continue
        for tr, cells in rows:
            slots = [""] * width
            for c, ls in cells:
                col, _cs = lay["pos"][(tr, c)]
                if col < width:
                    slots[col] = text_of(c, ls).replace("|", "\\|")
            out.append(_row_line([l for _c, ls in cells for l in ls], "| " + " | ".join(slots) + " |"))
        i = j
    return out


#: Planted (`D-4`): punctuation, a link's own icon and a cell's repeated
#: label each drawn as a line of their own, as before.
PLANT_STRUCTURAL_NOISE = False

_PUNCT_ONLY = re.compile(r"^[\s*-]*([|.,:;?!·•–—/()\[\]]+)\s*$")
_LINK_LABEL = re.compile(r"^\[([^\]]*)\]\(")
_IMAGE_ALT = re.compile(r"^!\[([^\]]*)\]\(")
# HEADER cells only: a `td` whose one line sits on the element is DATA ("Yes"
# in a feature table -- 20 of them folded away on the first run).
_CELL_OWN = re.compile(r"/th(?:\[\d+\])?$")


def _absorb(into: MarkdownLine, line: MarkdownLine) -> MarkdownLine:
    # On `inline`, not `absorbed`: in every fold below the folded words ARE
    # visible in the line that takes them (the full stop appended, the icon's
    # alt that is the link's label, the label already drawn once) -- which is
    # what `inline` means. And `covered` then does not move with the window:
    # on `absorbed` it shifted 42 addresses between windows 1200 and 200,
    # because which neighbour a fold finds depends on where a chunk is cut.
    more = (line.address,) + tuple(line.inline)
    return replace(into, inline=tuple(into.inline) + more,
                   absorbed=tuple(getattr(into, "absorbed", ())) + tuple(getattr(line, "absorbed", ())))


def _fold_structural(lines: List[MarkdownLine]) -> List[MarkdownLine]:
    """Draw once what the page only repeats for its own structure (`D-4`).

    The goal: *"full deduplication of repeat substrings that are essentially
    structural redundancies of the web pages themselves"* -- settled in
    PLUGIN_GOAL as "when a page repeats itself structurally, the chunk shows
    it once". Measured 2026-10-11 over six stored pages, 1,855 of 20,535 lines
    repeated within their own chunk; three causes are structure, each folded
    here into a line that already speaks for it, its address kept on that
    line's `absorbed` (findable, its edge hung, `accounted` unchanged):

    * a line of punctuation alone (`- .`, `- |`, `- ,`: 335) -- a sentence's
      full stop or a navbox separator cut off from what it belongs to;
    * an `<img>` inside a link whose alt IS the link's text (Wikipedia's edit
      pencil, 42) -- one control drawn twice;
    * a cell's own label repeated on its siblings ("Sort ascending" on every
      sortable header, 67) -- drawn at the first.

    NOT folded, though it repeats: data. "Yes"/"No" cells (741) and API type
    links (`[<string>]`, 100+) are distinct facts at distinct places; a
    repeated value is not a repeated structure.
    """
    out: List[MarkdownLine] = []
    own_label: Dict[str, int] = {}
    for line in lines:
        text = " ".join(line.text.split())
        prev = out[-1] if out else None
        m = _PUNCT_ONLY.match(text)
        # Never inside a table cell: a cell's "?" or "–" is a VALUE ("unknown",
        # "none") -- folding them turned a feature table's "Yes" + "?" into
        # "Yes?" on the first run.
        in_cell = line.address is not None and _CELL.match(line.address.xpath) is not None
        # Words only: a picture drawn as `![]` is made of punctuation characters
        # and is not punctuation (it was glued onto apnews' "( More )").
        media = line.address is not None and (line.address.tag.split(".")[0] in ("image", "media")
                                              or text.startswith(("![", "[")))
        if m and not in_cell and not media and prev is not None and not prev.text.lstrip().startswith("|"):
            p = m.group(1)
            sep = "" if p[0] in ".,:;?!)]" else " "
            out[-1] = _absorb(replace(prev, text=prev.text.rstrip() + sep + p), line)
            continue
        mi = _IMAGE_ALT.match(text)
        if (mi and prev is not None and line.address is not None and prev.address is not None
                and line.address.xpath.rsplit("/", 1)[0] == prev.address.xpath):
            ml = _LINK_LABEL.match(" ".join(prev.text.split()))
            if ml and " ".join(ml.group(1).split()) == " ".join(mi.group(1).split()):
                out[-1] = _absorb(prev, line)
                continue
        if line.address is not None and _CELL_OWN.search(line.address.xpath) and text:
            first = own_label.get(text)
            if first is not None:
                out[first] = _absorb(out[first], line)
                continue
            own_label[text] = len(out)
        out.append(line)
    return out


def with_table_separators(markdown: str) -> str:
    """The chunk's markdown as a reader's renderer needs it: a `| --- |` row
    after the first row of every run of table rows (`_tabulate` leaves it out
    of the lines, which pair one-to-one with addresses)."""
    out: List[str] = []
    prev_cols = 0
    for raw in markdown.split("\n"):
        row = raw.lstrip().startswith("|") and raw.rstrip().endswith("|")
        cols = max(1, raw.strip().count("|") - raw.strip().count("\\|") - 1) if row else 0
        # A row of ANOTHER width is another table -- a nested one (Wikipedia's
        # infobox holds its "Time complexity" table in a cell): under one
        # delimiter a renderer drops the cells past the first table's width,
        # and "Worst case" vanished (2026-10-18). Planted `PLANT_ONE_TABLE_RUN`.
        if row and prev_cols and cols != prev_cols and not PLANT_ONE_TABLE_RUN:
            out.append("")
            prev_cols = 0
        # A table cannot interrupt a paragraph, and a plain line after one is
        # read as its next row: a blank line on each side (the panel showed
        # its rows as one paragraph of "| a | b |" text, 2026-10-18).
        if row and not prev_cols and out and out[-1].strip():
            out.append("")
        if not row and prev_cols and raw.strip():
            out.append("")
        out.append(raw)
        if row and not prev_cols:
            out.append("|" + "|".join([" --- "] * cols) + "|")
        prev_cols = cols
    return "\n".join(out)


#: Planted: rows of different widths share one table, as before.
PLANT_ONE_TABLE_RUN = False


def _number_parts(chunks: List[MarkdownChunk]) -> None:
    """Number the chunks that share a root xpath, 0..n, in emission order.

    `part` exists to keep two chunks rooted at one element from colliding on
    their id, and the descent satisfied that by handing out the chunk's
    *global* position -- which gave an ordinal to chunks that shared their
    root with nobody. Over the fixture pages at two window settings, 24 of 91
    chunks carried a nonzero ordinal and only 18 had a reason to.

    The reason to fix it is the render memo, not the ids. A cached subtree can
    only be spliced in at an arbitrary position if nothing inside it is a
    function of position, and a global ordinal is exactly that. Numbering
    within the (url, xpath) group makes `part` a property of the group.

    It should also stop an insertion near the top of a page from renaming
    chunks below it, which is what a store keyed on `cid` has to rewrite.
    That effect is expected rather than observed: over the fixture pages, at
    windows of 200/400/1200, an inserted paragraph produced the same surviving
    id set under both schemes. The pages available do not chunk finely enough
    to show it, so it is recorded here as a consequence and not as a result.

    Done after the descent, like `_level_page`, because it is a property of
    the page and not of any one chunk.
    """
    seen: Dict[Tuple[str, str], int] = {}
    for chunk in chunks:
        key = (chunk.url, chunk.xpath)
        chunk.part = seen.get(key, 0)
        seen[key] = chunk.part + 1


#: Planted (R-K1): depths compacted over the PAGE, as before -- empty indent
#: levels wherever a depth branches elsewhere on the page.
PLANT_PAGE_LEVELS = False

#: Planted (R-K2a): a line with no words and no target drawn on its own.
PLANT_KEEP_CONTENTLESS = False

#: What a bare mark is made of: nothing a reader can read, nowhere to go.
_WORDLESS = re.compile(r"[A-Za-z0-9\u00C0-\uFFFF]")


def _is_contentless(text: str) -> bool:
    """A line that is only marks: `![]`, `<#>`, `[ ]`, `=== ===`. A target is
    a word for this purpose (a url has letters), so `![](media/x.png)` stays."""
    return not _WORDLESS.search(text or "")


def _fold_contentless(lines: List[MarkdownLine]) -> List[MarkdownLine]:
    """R-K2a: a line with neither words nor a target is not drawn -- its address
    is FOLDED into a worded line of the SAME element, as an inline address.

    Dropping it was built and reverted (PLUGIN_PRD R-K2a): its address went to
    `absorbed`, which `covered` excludes, and 340 addresses that still exist
    stopped being accounted for. Folded, it is `inline` -- which `covered`
    counts -- so the line goes and the address stays accounted for. Scoped to
    the element, inside one rendered subtree, which always holds every unit of
    every element in it: the verdict is the same at every window. A bare mark
    whose element has no worded line (an inline `<svg>`, a nameless form) is
    the element's only address and is kept, as it is.
    """
    def element(line: MarkdownLine) -> str:
        return line.address.xpath.split("/text()")[0].split("/@")[0] if line.address else ""

    worded: Dict[str, MarkdownLine] = {}
    for line in lines:
        if not _is_contentless(line.text) and line.address is not None:
            worded.setdefault(element(line), line)
    out: List[MarkdownLine] = []
    for line in lines:
        host = worded.get(element(line)) if _is_contentless(line.text) and line.address is not None else None
        if host is None or host is line:
            out.append(line)
            continue
        host.inline = tuple(host.inline) + (line.address,) + tuple(line.inline or ())
        host.absorbed = tuple(host.absorbed) + tuple(line.absorbed or ())
    return out


def _level_page(chunks: List[MarkdownChunk]) -> None:
    """Put the page on the margin, and give each nesting level one step.

    Two separate problems, both of which read as bad indentation.

    The page sat at column ten, because absolute depth counts every layout
    wrapper between `<html>` and the content. A reader does not care that a
    site nests five divs to centre a header.

    And a run of single-child wrappers spent one indent level each, so
    columns of whitespace accumulated with no structure behind them. Mapping
    the depths that actually occur onto consecutive levels keeps every
    nesting relationship -- deeper stays deeper, siblings stay level -- while
    a chain of five wrappers costs one step instead of five.

    **Per chunk, from each line's own parent** (R-K1, 2026-10-11). Mapping
    the depths that occur ON THE PAGE onto consecutive integers removed a
    chain of wrappers only when its depths occurred nowhere else on the page;
    on a real page they do, so a depth that branches in one chunk still spent
    an empty indent in another -- 39.0% of exported chunks carried one, and a
    chunk deep in the page started indented. Now a line sits one step below
    the nearest preceding line drawn shallower than it, and a line with none
    sits at the margin. Deeper stays deeper along every ancestor chain, so an
    element inside another stays drawn inside it; siblings stay level.
    `vertiscope.analytics.levels` scores it. Planted: the page-wide mapping.
    """
    if not PLANT_PAGE_LEVELS:
        for chunk in chunks:
            stack: List[Tuple[int, int]] = []     # (original depth, new depth)
            for line in chunk.lines:
                d = line.depth
                while stack and stack[-1][0] >= d:
                    stack.pop()
                line.depth = stack[-1][1] + 1 if stack else 0
                stack.append((d, line.depth))
        return
    by_url: Dict[str, List[MarkdownChunk]] = {}
    for chunk in chunks:
        by_url.setdefault(chunk.url, []).append(chunk)
    for page in by_url.values():
        seen = sorted({line.depth for c in page for line in c.lines})
        if not seen:
            continue
        level = {d: i for i, d in enumerate(seen)}
        for chunk in page:
            for line in chunk.lines:
                line.depth = level[line.depth]


def _fill_report(
    trie: AddressTrie, chunks: Sequence[MarkdownChunk], report: RenderReport
) -> None:
    """Add this render's tallies to ``report``.

    Accumulates every field, including ``addresses`` and ``rendered``. An
    earlier version assigned those two and accumulated the rest, so a report
    reused across pages compared the last page's address count against every
    page's dedup count and reported a *negative* unaccounted figure — which is
    at least a loud way to fail, since the quantity is a count and cannot be
    negative for any real reason.
    """
    emitted = {key for chunk in chunks for key in chunk.anchors}
    report.addresses += len(trie)
    report.rendered += sum(len(c.lines) for c in chunks)
    for leaf in trie.leaves():
        if leaf.address is None or leaf.address.key() in emitted:
            continue
        if not (leaf.value or "").strip():
            report.empty += 1
        elif leaf.address.tag in _SUPPRESSED_TAGS:
            report.suppressed += 1
        else:
            report.deduped += 1


def _annotate_xpaths(page: TrieNode, url_path: Sequence[str], url: str) -> None:
    """Cache each element node's absolute xpath, for chunk roots.

    **No longer called by the renderer.** `AddressTrie.insert` assigns
    `_xpath_cache` when it creates a node, which is where the information
    already was: `insert` walks the path building the very prefix this
    function re-derives. Doing it here meant a walk of every element on the
    page on every render -- an O(page) read of something the write knew --
    and a node's xpath cannot change anyway, since a segment and its ancestors
    are fixed for the node's life. Content "moving" in this trie is content
    arriving at a *different node*, not a node changing address.

    Kept as the reference implementation that
    `tests/test_render_trie_reads.py` checks the trie's assignment against, so
    the two definitions cannot drift apart silently.
    """
    def walk(node: TrieNode, prefix: str) -> None:
        node._xpath_cache = prefix or "/"
        for child in node.ordered_children():
            if child.is_leaf or _is_terminal_pair(child):
                continue
            walk(child, f"{prefix}/{child.segment}")

    page._xpath_cache = "/"
    for child in page.ordered_children():
        if child.is_leaf or _is_terminal_pair(child):
            continue
        walk(child, f"/{child.segment}")


# Where a chunk ends: from a running total, or from the content itself.
#
# The running total is what the greedy merge has always done -- accumulate
# siblings until the window is crossed, then cut. It packs the window well and
# it has one bad property: a boundary is a function of everything before it, so
# inserting one sibling shifts every boundary after it and the phase never
# comes back. Measured by `analytics/projection.py`: an insertion re-embeds
# ~100% of a page's chunks at the head and ~53% in the middle, at every page
# size, for an O(1) change to the page.
#
# The alternative is to let the content decide, which is what content-defined
# chunking does for deduplicating storage. Kept as a switch rather than a
# replacement, because it changes what a chunk *is* -- chunk ids, chunk
# contents and window utilisation all move with it -- and because the
# comparison is worth being able to re-run.
#
# What settled it, measured over an N-row list, counting chunks that come out
# holding text no chunk held before, which is what the embedder is actually
# asked to do:
#
#     insertion at the head      N=1600   N=6400   N=25600
#     running total                177      711      2844
#     content-defined                3        3         3
#
# Constant in the page, against linear. Coverage and deduplication are
# untouched: over the fixture pages both modes emit the same 365 lines with
# the same 365 unique anchors and the same dedup tally, no chunk over the
# window and nothing addressed twice. What it costs is packing -- about 10%
# more chunks at a median a few percent smaller.
CONTENT_BOUNDARIES = True


def _piece_hash(chunk: MarkdownChunk) -> int:
    """A hash of what a piece *says*, with no trace of where it says it.

    The obvious oracle was `TrieNode.exact_hash`, which the trie already
    maintains. It is the wrong one, and measurably so: it folds in the node's
    address, so every sibling's hash changes when an insertion shifts the
    indices, every boundary decision changes with it, and the renders never
    re-align. Tried first, and the re-embed ratio did not move off 1.0.

    `subtree_hash` fails the same way for the same reason -- its Merkle folds
    in `segment`, and a segment carries the sibling ordinal.

    So the oracle is the rendered text, which is what a boundary is supposed
    to be a function of and what decides whether a chunk needs re-embedding at
    all. Line text only: depth is rewritten by `_level_page` afterwards, and a
    piece that moves keeps its words.

    A checksum rather than Python's `hash`, and the distinction is
    load-bearing. `hash` is randomised per process, so boundaries chosen with
    it fall in different places in two runs: the same page would chunk
    differently, under different ids, every time the process restarted, and a
    stored index would disagree with the next scan of the same page. It got as
    far as a test that passed alone and failed in the suite before the cause
    was clear. `TrieNode.exact_hash` may use `hash` because it is consulted
    in-process and never persisted; a boundary is persisted the moment a chunk
    id is written down.
    """
    joined = "\n".join(line.text for line in chunk.lines)
    return zlib.crc32(joined.encode("utf-8", "replace"))


# How full a chunk must be before a content boundary is allowed to end it.
#
# Without it the cut fires with probability `piece_chars / window` from the
# first sibling, so sizes come out exponentially distributed and the window
# goes half used: measured at 65 chunks of median 587 characters where the
# running total produced 46 of 755.
#
# The threshold reads the running total, so it is the one accumulation-
# dependent input in the decision and it does weaken the re-synchronisation
# argument from "at the first boundary" to "within a chunk". The window cap
# was already such an input, and the measurement is what settles it.
#
# 0.5 rather than higher, where the packing would be better: at 0.65 most cuts
# become window cuts again, and on a middle insertion into a page of
# variable-length rows the new-text count went from 1 to 30 -- worse than the
# running total it replaces. The threshold buys packing by spending
# re-synchronisation, and past this point it spends more than it buys.
MIN_FILL = 0.5

#: How far past the window a run may go to keep what belongs together (`G-86`).
#:
#: The user's rule, 2026-09-26: *"within a margin of error depending on the
#: percentage increase from the limit to the very next chunk merge. If this is
#: closer to 512 than 256 in the merge after the context limit, keep the
#: previous, otherwise include the merge as the final chunk. This should be
#: pretty lenient to edge cases where we include headings as well."* So a
#: piece that would take a run past the window is taken anyway while the run
#: stays nearer the window than twice it -- under 1.5x -- and the run ends
#: there; past that, the run ends before it, as before. The same bound lets a
#: buffered heading and lead join the first chunk of an oversized piece that
#: follows them, instead of standing alone.
LENIENCY = 1.5


#: Planted (`G-143`): headings merge like any other piece, so a section's
#: heading can close the chunk before it -- the culinarypedia defect.
PLANT_TRAILING_HEADINGS = False

#: Planted (`G-86`): a heading before a record set is flushed on its own.
PLANT_HEADING_APART_FROM_RECORD = False

#: Planted (`G-86`): a content boundary after a lone heading flushes it alone.
PLANT_LONE_HEADING_FLUSH = False

#: Planted (`G-86`): no last cut -- a chunk the post-passes grew past the
#: lenient bound (a table's rows given their column names, `D-9`) stays so.
PLANT_NO_RECUT = False


def _recut(chunks: List[MarkdownChunk], window: int) -> List[MarkdownChunk]:
    """The lenient bound held AFTER the post-passes (`G-86`).

    The descent sizes a subtree before the page-wide passes rewrite it, and
    some of those passes grow it: `_tabulate` gives every row its column names
    (`D-9`), so a table sized as bare cells came out 400-730 tokens against a
    256 window -- 33 multi-line chunks over 1.5x in the corpus, 26 of them
    one Wikipedia comparison table. Such a chunk is cut again here, by lines,
    by the descent's own rule: a run takes the next line past the window while
    it stays under 1.5x, never ends on a heading, and a single line longer
    than that stands alone (S-11). A chunk within the bound is returned as it
    is, so nothing the descent got right moves.
    """
    out: List[MarkdownChunk] = []
    for chunk in chunks:
        if (PLANT_NO_RECUT or len(chunk.lines) < 2
                or tokens.budget(chunk.markdown) < LENIENCY * window):
            out.append(chunk)
            continue
        runs: List[List[MarkdownLine]] = [[]]
        size = 0
        for line in chunk.lines:
            cost = tokens.budget(line.render()) + 1
            run = runs[-1]
            if run and size + cost > window:
                if size + cost < LENIENCY * window and not _HEADING_FORM.match(line.text or ""):
                    run.append(line)
                    runs.append([])
                    size = 0
                    continue
                # Never end on a heading: it opens the next run instead.
                carried: List[MarkdownLine] = []
                while len(run) > 1 and _HEADING_FORM.match(run[-1].text or ""):
                    carried.insert(0, run.pop())
                runs.append(carried)
                size = sum(tokens.budget(l.render()) + 1 for l in carried)
            runs[-1].append(line)
            size += cost
        for run in runs:
            if run:
                out.append(_part_of(chunk, run, 0))
    return out

_HEADING_FORM = re.compile(r"#{1,6} ")


def _only_heading(piece: object) -> bool:
    """Is this piece headings and nothing else -- nothing it heads yet?"""
    lines = getattr(piece, "lines", None)
    return bool(lines) and all(_HEADING_FORM.match(l.text or "") for l in lines)


def _content_boundary(piece_hash: int, piece_chars: int, window: int,
                      buffered: int = 0) -> bool:
    """Should the chunk end after this sibling, judged from the sibling alone?

    A boundary is a property of the piece's own content and of nothing else on
    the page, which is the whole point: an insertion cannot move a boundary it
    does not touch, so the two renders re-synchronise at the first boundary at
    or after the insertion.

    Self-normalising to the window, with no accumulated state. The cut fires
    with probability `piece_chars / window`, so the expected content between
    two cuts is one window's worth however large the siblings happen to be --
    no target count to tune, and nothing that has to be re-derived per page.

    Both inputs belong to the piece: its own hash and its own length. Neither
    changes when a sibling is inserted before it, which is what makes the
    re-synchronisation exact rather than probable.
    """
    if piece_chars <= 0 or buffered < window * MIN_FILL:
        return False
    return (piece_hash % window) < piece_chars


#: How many same-shaped siblings make a run a record set rather than a
#: coincidence. Two `<li>` could be anything; three is a list of things.
RECORD_MIN = 3

#: How much of the run has to share the majority tag. Real lists carry an
#: odd `<li class="ad">` or a trailing "load more", and demanding uniformity
#: would miss every list that has one.
RECORD_SHARE = 0.6


#: The smallest a typical record may be and still be worth a chunk of its
#: own, in the window's own unit.
#:
#: A nav bar, a tag cloud and a breadcrumb trail are all repeated composite
#: shapes -- `<li><a>Home</a></li>` passes every structural test a search
#: result passes -- and none of them is a record, because nobody retrieves
#: one. Structure cannot separate them; size can. Without this the rule fired
#: on every menu in the corpus and took the median chunk from 308 tokens to
#: 47.
#:
#: ABSOLUTE, not a share of the window, and that is the whole point. Expressed
#: as a fraction, "is this a record" became a function of the hyperparameter:
#: the same ten 92-token results were records at a window of 512 and were not
#: at 1024, so the boundary moved with a knob instead of sitting where the
#: page changes subject. Roughly a sentence's worth of content.
RECORD_MIN_SIZE = 48


#: Elements that sit INSIDE a line of text rather than making a block of their
#: own. Holding only these does not make an element a record (see
#: `_record_children`).
_INLINE_TAGS = frozenset({
    "a", "abbr", "b", "bdi", "bdo", "br", "cite", "code", "data", "del", "dfn",
    "em", "i", "img", "ins", "kbd", "mark", "math", "q", "s", "samp", "small",
    "span", "strong", "sub", "sup", "time", "u", "var", "wbr", "#text",
    # A TEXT NODE, however it is spelled. In the live capture's trie a text
    # node carries its taxonomy and detecting rule as two segments below it,
    # so it is not a leaf and read as a block child: every paragraph then
    # looked composite and the Suffix tree definition split into heading /
    # lead / list live while the same HTML rendered as one chunk offline.
    "text()",
})


def _record_children(sized: Sequence[Tuple[TrieNode, object, int]],
                     window: int) -> set:      # noqa: ARG001 (see RECORD_MIN_SIZE)
    """The children of a repeated record structure, by identity.

    The goal asks for "search results as singular chunks", and the window
    alone cannot deliver that. The window is a *cap*: the merge fills it with
    whatever adjacent siblings fit, so at 512 tokens five hundred-token
    results become one chunk, and at 128 one result would be split. Either
    way the chunk boundary falls where the arithmetic ran out rather than
    where the page changed subject. A retrieval hit then points at "the third
    through seventh results", which is not a thing anyone was looking for.

    What makes a search result a unit is not its size, it is that the page
    repeats a shape. So the rule is about shape:

    * at least `RECORD_MIN` siblings share a tag -- three is a list, two is a
      coincidence;
    * most of the run shares it (`RECORD_SHARE`), because real lists carry a
      stray promo row or a "load more" and demanding uniformity would miss
      every list that has one;
    * and those siblings are COMPOSITE -- each holds an element of its own.

    That last clause is what keeps prose out. A run of `<p>` in an article is
    a repeated tag and must keep merging: paragraphs are not records, and
    splitting them would give every paragraph its own chunk and bury each
    one's context. A search result holds a link, a title, a byline; a product
    card holds a picture, a price, a button. The composite test separates the
    two without a tag list to maintain.

    And the run has to be worth splitting. A nav bar, a breadcrumb trail and
    a tag cloud pass every structural test above -- `<li><a>Home</a></li>` is
    a composite repeated shape -- and none of them is a thing anyone
    retrieves. The separation that works is size: a record carries a
    sentence's worth of content, a menu item carries a word. Without
    `RECORD_MIN_FILL` the rule fired on every menu in the corpus and took the
    median chunk from 308 tokens to 47.

    Returns identities rather than a boolean so the merge can flush after
    each record while still merging the run's odd non-record neighbour.
    """
    if len(sized) < RECORD_MIN:
        return set()
    labels: Dict[str, List[Tuple[TrieNode, object, int]]] = {}
    for entry in sized:
        labels.setdefault(_label_of(entry[0].segment), []).append(entry)
    _label, run = max(labels.items(), key=lambda kv: len(kv[1]))
    if len(run) < RECORD_MIN or len(run) < RECORD_SHARE * len(sized):
        return set()
    # COMPOSITE means holding a BLOCK of its own -- a title, a byline, a
    # picture's box. An element that holds only inline elements is prose
    # with links in it: every Wikipedia paragraph has an <a> or a <span>, so
    # the looser test ("holds any element") made a run of paragraphs a record
    # set, one chunk per paragraph, flushed apart from the heading and list
    # they belong with (the Suffix tree definition, 2026-09-26). The same
    # held for a five-item list whose items carried inline math.
    composite = [e for e in run
                 if any(not k.is_leaf and not _is_terminal_pair(k)
                        and _label_of(k.segment) not in _INLINE_TAGS
                        for k in e[0].ordered_children())]
    if len(composite) < RECORD_SHARE * len(run):
        return set()
    # The TYPICAL record, not the largest: one long row among twenty short
    # ones is a menu with an announcement in it, not a result list.
    sizes = sorted(e[2] for e in composite)
    typical = sizes[len(sizes) // 2]
    if typical < RECORD_MIN_SIZE:
        return set()
    return {id(e[0]) for e in composite}


def _certainly_overflows(child_chars: Sequence[int], window: int) -> bool:
    """True when the children alone are already too big for the window.

    The lower bound, and the argument for it in full.

    Every rendering decision is scoped to a single element. `_dedupe` groups
    units by ``addr.xpath`` and compares only within a group; the rule that
    lets a control consume its own label is keyed the same way; suppression
    reads a unit's own tag. Nothing in one subtree can remove anything in
    another, so the parent's rendering contains every line each child renders.

    They sit at the same indentation from either root: `_collect` measures
    depth from the chunk root and `_render_node` offsets by
    ``-(node.depth - url_depth)`` to cancel it, so a line costs the same
    characters wherever the descent reached it from.

    `chars` is ``len("
".join(lines))``. A child holding L lines of total
    rendered length S measures ``S + L - 1``. The parent holding all of them
    measures at least ``sum(S) + sum(L) - 1``, which is
    ``sum(child_chars) + k - 1`` for k children.

    `_join_inline` merging a run across a child boundary does not threaten it:
    joining two lines costs one space and saves one newline. Heading label
    inheritance only adds characters. So the bound stands, and the descent can
    skip an ancestor's render whenever the children it has already measured
    exceed the window between them.

    `tests/test_render_bound.py` holds this from both sides -- the floor, the
    matching upper bound, the element scoping underneath, and the one case
    where the *upper* bound fails.
    """
    if not child_chars:
        return False
    return sum(child_chars) + len(child_chars) - 1 > window


def _size_of(
    node: TrieNode,
    url: str,
    url_depth: int,
    window: int,
    memo: Optional["RenderMemo"],
) -> Tuple[Optional[MarkdownChunk], int]:
    """``node``'s render and its length, or ``(None, window + 1)``.

    The second form means "this overflows the window, and finding that out did
    not require rendering it". A caller that only wants to know whether a
    subtree fits can act on it; a caller that wants the lines has to descend,
    which is what it was going to do with an overflowing subtree anyway.

    This is the recursive form of `_certainly_overflows`, and it exists
    because measuring a child used to mean rendering it. On the path from an
    edited leaf to the page root every ancestor measured its stale child, so
    the same subtree was rendered once per level -- profiled at five
    whole-page `_collect` walks to redraw a page after a one-word edit, which
    was the entire remaining cost.

    The recursion bottoms out on the memo: a clean subtree answers with its
    cached size, and a stale one asks its own children. Verdicts are cached
    too, so a probe repeated from each ancestor costs one lookup after the
    first.

    ``window + 1`` is a *lower* bound on an overflowing subtree's true length,
    so a sum of these stays a lower bound and `_certainly_overflows` stays
    sound when it is fed one.
    """
    if memo is None:
        # Nothing to lean on. The recursion below pays for itself only when
        # its base case is a cached size; without one it walks the subtree
        # computing sizes by rendering, at every level, and a render with no
        # memo got three times slower before this guard was here. `_descend`
        # still gets its floor from the children it measures directly, which
        # is where the speed-up on this path comes from.
        return _render_sized(node, url, url_depth, None)

    key = _memo_key(node, url, "node", 0)
    if key is not None:
        cached = memo.peek(key)
        if cached is not None:
            memo.reused_lines += len(cached[0].lines)
            return cached
        verdict = _memo_key(node, url, "overflows", window)
        if verdict is not None and memo.peek(verdict) is not None:
            return None, window + 1

    kids = [c for c in node.ordered_children()
            if not c.is_leaf and not _is_terminal_pair(c)]
    if kids:
        child_chars = []
        for child in kids:
            _chunk, chars = _size_of(child, url, url_depth, window, memo)
            child_chars.append(chars)
        if _certainly_overflows(child_chars, window):
            if memo is not None:
                memo.skipped_fit_tests += 1
                verdict = _memo_key(node, url, "overflows", window)
                if verdict is not None:
                    memo.put(verdict, True)
            return None, window + 1

    return _render_sized(node, url, url_depth, memo)


def _descend(
    node: TrieNode,
    url: str,
    url_depth: int,
    window: int,
    memo: Optional["RenderMemo"] = None,
) -> List[MarkdownChunk]:
    """The chunks for ``node``'s subtree. Leaves are partitioned, never shared.

    **The result is pristine and is not the caller's to modify.** It may be
    the memo's list, holding the memo's chunks, holding `MarkdownLine` objects
    shared with the entries of every node below. `render_trie` copies once, on
    the way out, and that single copy is what `_level_page` and
    `_number_parts` then rewrite.

    Cloning used to happen here instead, at each point a chunk was committed.
    That put one copy per emitted line at every level of the dirty path, so a
    one-word edit on a 6,400-row page copied 25,601 lines six times over --
    the largest single cost left in the render once the fit tests were gone.
    """
    # A subtree whose `exact_hash` is unchanged chunks the same way it did
    # last time, so the whole descent below this node can be skipped: the
    # trie's Merkle answers, in one comparison, a question that otherwise
    # costs a walk of everything underneath. This is where a clean page pays
    # nothing for an edit somewhere else on it.
    #
    # Sound only because nothing in a chunk is a function of its position any
    # more -- see `_number_parts`. Spliced chunks keep their own ordinals.
    key = _memo_key(node, url, "descend", window) if memo is not None else None
    if key is not None:
        cached = memo.get(key)
        if cached is not None:
            for c in cached:
                memo.reused_lines += len(c.lines)
            return cached

    out: List[MarkdownChunk] = []
    xpath = _xpath_of(node, url)
    element_children = [
        c for c in node.ordered_children()
        if not c.is_leaf and not _is_terminal_pair(c)
    ]

    if not element_children:
        chunk, chars = _render_sized(node, url, url_depth, memo)
        if not chunk.lines:
            if key is not None:
                memo.put(key, [])
            return []
        if chars <= window:
            out.append(chunk)
            if key is not None:
                memo.put(key, out)
            return out
        # No element to descend into. If the overflow is *one* unit, it is
        # genuinely indivisible: cutting a single value would leave a chunk
        # whose address over-claims, and that is the rule.
        #
        # Several units are a different case, and treating them the same made
        # the window stop meaning anything on a document whose content hangs
        # off one element. A `text/plain` RFC addresses every paragraph under
        # `/html/body/pre`, so 505 units came out as **one 65,890-character
        # chunk at every window setting**. Splitting them is safe by the same
        # argument the sibling merge already relies on: the chunk stays rooted
        # at this element and `anchors` says exactly which addresses are
        # inside, so it under-claims, never over-claims.
        if len(chunk.lines) <= 1:
            out.append(chunk)
            if key is not None:
                memo.put(key, out)
            return out
        _emit_runs(chunk, window, out)
        if key is not None:
            memo.put(key, out)
        return out

    # The children are measured before this node is, which is the whole point.
    #
    # The ancestors of an edited leaf reach the page root; each of them is
    # stale, and each used to ask whether its own subtree fits the window by
    # rendering that subtree -- at the root, the page. That was the projection
    # cost that would not go away no matter how much of the page the memo
    # could serve.
    #
    # The children answer it. They have to be measured anyway to be split or
    # merged, most of them come back from the memo, and by `_certainly_
    # overflows` their sizes put a floor under this node's. When that floor
    # clears the window, this node's own render is never needed.
    sized: List[Tuple[TrieNode, Optional[MarkdownChunk], int]] = []
    child_chars: List[int] = []
    for child in element_children:
        rendered, rendered_chars = _size_of(child, url, url_depth, window, memo)
        if rendered is not None and not rendered.lines:
            continue
        sized.append((child, rendered, rendered_chars))
        child_chars.append(rendered_chars)

    own = _own_units_chunk(node, url, url_depth, memo)
    has_own = own is not None and own[0].lines

    # Which of these children are records -- a repeated shape the page uses
    # for a list of things. Computed from the ELEMENT CHILDREN, not from the
    # pieces, because it is a property of the page's structure and not of what
    # happened to fit.
    #
    # Asked BEFORE the fits-shortcut below, and that ordering is the rule.
    # A list of ten results is about nine hundred tokens; at a window of 1024
    # the whole `<ol>` fits, this node returns one chunk, and the record rule
    # never runs -- so "one chunk per result" held at 512 and silently stopped
    # holding at 1024. A boundary that appears and disappears with a
    # hyperparameter is not a property of the page.
    records = _record_children(sized, window)

    if _certainly_overflows(child_chars, window):
        if memo is not None:
            memo.skipped_fit_tests += 1
    elif records:
        # Fits, and is a record set. Fall through to the merge, which emits
        # one chunk per record.
        pass
    else:
        chunk, chars = _render_sized(node, url, url_depth, memo)
        if not chunk.lines:
            if key is not None:
                memo.put(key, [])
            return []
        if chars <= window:
            out.append(chunk)
            if key is not None:
                memo.put(key, out)
            return out

    if not sized and not has_own:
        if key is not None:
            memo.put(key, [])
        return []

    # Split, then re-merge adjacent siblings up to the window. Without the
    # merge a page whose root overflows shatters into one chunk per child —
    # measured at 83 chunks averaging 40 characters against a 1200-character
    # window, which wastes the window and buries each line's context.
    #
    # A merged chunk is rooted at *this* element and holds a contiguous run of
    # its children. That under-claims — the root names more than the chunk
    # holds — which is safe, because `anchors` says exactly which addresses
    # are inside. The direction matters: a chunk that over-claimed would let a
    # retrieval hit point at content it does not contain.
    pieces: List[Tuple[str, object, int, int, bool]] = []
    if has_own:
        # No hash: these are the node's own units, always first in the run,
        # and a boundary before anything has accumulated says nothing.
        pieces.append(("fits", own[0], own[1], _piece_hash(own[0]), False))
    for child, rendered, rendered_chars in sized:
        # `rendered is None` is `_size_of` saying it proved the overflow
        # without drawing anything, which is exactly the case that splits.
        fits = rendered is not None and rendered_chars <= window
        pieces.append(("fits" if fits else "split",
                       rendered if fits else child, rendered_chars,
                       _piece_hash(rendered) if fits else 0,
                       id(child) in records))

    buffer: List[MarkdownChunk] = []
    sizes: List[int] = []
    buffered_chars = 0
    # The chunk this loop emitted last, if a run of its own siblings: a short
    # section tail may still go back to it when a heading arrives (`G-143`).
    last_run: List[int] = []                 # [its size] or empty

    def flush(final: bool = False) -> None:
        # A heading never CLOSES a chunk (`G-143`). When a run would end on
        # headings, they -- with nothing they head arrived yet -- are carried
        # into the next run rather than left as the last lines of the previous
        # section's chunk. `final` emits them as they are: at the end of this
        # node, or before a split or a record, there is nothing to carry to.
        nonlocal buffered_chars
        if not buffer:
            return
        keep = len(buffer)
        if not final and not PLANT_TRAILING_HEADINGS:
            while keep > 1 and _only_heading(buffer[keep - 1]):
                keep -= 1
            # A buffer of headings and nothing else is carried WHOLE (`G-86`):
            # a content boundary firing right after a lone heading flushed it
            # as a chunk of its own -- Python's `### Functions` over a 218-token
            # `<dl>`, RFC 9110's section headings (2026-10-12).
            if keep == 1 and _only_heading(buffer[0]) and not PLANT_LONE_HEADING_FLUSH:
                return
        out.append(_merge(buffer[:keep], url, xpath, len(out)))
        last_run[:] = [sum(sizes[:keep]) + keep - 1]
        del buffer[:keep]
        del sizes[:keep]
        buffered_chars = sum(sizes)

    def take(piece: MarkdownChunk, chars: int) -> None:
        nonlocal buffered_chars
        buffer.append(piece)
        sizes.append(chars)
        buffered_chars += chars

    for kind, piece, piece_chars, piece_hash, is_record in pieces:
        if kind == "split":
            sub = _descend(piece, url, url_depth, window, memo)  # type: ignore[arg-type]
            # A buffered heading and lead go WITH the first chunk of what they
            # head, when the two fit the lenient bound together (`G-86`).
            if buffer and sub:
                first_cost = tokens.budget(sub[0].markdown)
                if buffered_chars + len(buffer) + first_cost < LENIENCY * window:
                    buffer.append(sub[0])
                    sizes.append(first_cost)
                    flush(final=True)
                    out.extend(sub[1:])
                    if len(sub) > 1:
                        last_run.clear()
                    continue
            flush(final=True)
            out.extend(sub)
            last_run.clear()
            continue
        if is_record:
            # A record stands alone. Flushed BEFORE as well as after, so a
            # record never shares a chunk with the stray promo row that
            # happened to precede it -- the run is "one chunk per result",
            # not "one chunk per result except the first".
            #
            # A HEADING is the exception (`G-86`): "Highlights" over a run of
            # article cards heads them, and flushed on its own it was a chunk
            # that is a heading alone -- 27 of the corpus's 43. Headings and
            # nothing else in the buffer go with the first record, within the
            # lenient bound; the chunk still holds one result.
            if (buffer and not PLANT_HEADING_APART_FROM_RECORD
                    and all(_only_heading(b) for b in buffer)
                    and buffered_chars + len(buffer) + piece_chars < LENIENCY * window):
                take(piece, piece_chars)  # type: ignore[arg-type]
                flush(final=True)
                last_run.clear()
                continue
            flush(final=True)
            take(piece, piece_chars)  # type: ignore[arg-type]
            flush(final=True)
            last_run.clear()
            continue
        # A BARE heading -- a sibling that is nothing but the heading, as in a
        # flat `<h2><p><p><ul>` article. A piece that opens with its own
        # heading (`<li><h3>..</h3><p>..</p></li>`) already carries what it
        # heads, and cutting before every such piece turned the merge back
        # into a running total: 37 new chunks for one inserted row of 400.
        heads = not PLANT_TRAILING_HEADINGS and _only_heading(piece)
        # A heading OPENS a chunk (`G-143`): the run before it ends here. A
        # run shorter than a chunk's worth (`MIN_FILL`) -- a section's last
        # list, say -- goes back into the chunk before it when the two fit the
        # lenient bound, which is the leniency the rule asks for at the edges;
        # it stands alone only when they do not. The boundary is a property
        # of the heading itself, so an insertion elsewhere cannot move it.
        if heads and buffer:
            if (buffered_chars < window * MIN_FILL and last_run and out
                    and last_run[0] + buffered_chars + len(buffer) < LENIENCY * window):
                # A short tail of the section before: back into that
                # section's chunk, within the lenient bound, rather than
                # in front of this heading or standing alone.
                tail = [out.pop()] + buffer
                out.append(_merge(tail, url, xpath, len(out)))
                last_run[:] = [last_run[0] + buffered_chars + len(buffer)]
                buffer.clear(); sizes.clear(); buffered_chars = 0
            else:
                flush()
        # +len(buffer) for the newlines _merge inserts between parts. Omitting
        # them let a chunk exceed the window by one character per merged part,
        # which is small but is exactly the kind of drift that makes a
        # hyperparameter stop meaning what it says.
        size = buffered_chars + len(buffer) + piece_chars
        if buffer and size > window:
            if size < LENIENCY * window and not heads:
                # Nearer the window than twice it: take the piece, end the run.
                # Never a heading: it would end the run it should open.
                take(piece, piece_chars)  # type: ignore[arg-type]
                flush()
                continue
            flush()
        take(piece, piece_chars)  # type: ignore[arg-type]
        # The window stays a hard cap either way; what changes is whether a
        # chunk may end *before* it. The cap is still a running total, so a
        # perturbation can outlive one chunk -- but only until the next
        # content boundary, which is where the two renders re-align.
        if CONTENT_BOUNDARIES and _content_boundary(piece_hash, piece_chars,
                                                    window, buffered_chars):
            flush()
    flush(final=True)
    if key is not None:
        memo.put(key, out)
    return out


def _emit_runs(
    chunk: MarkdownChunk, window: int, out: List[MarkdownChunk]
) -> None:
    """Split one element's own units into window-sized runs, in order.

    Each run keeps the element's xpath and takes a distinct ``part``, which is
    what that field is for — several chunks sharing a root already collide on
    their id without it. A line longer than the window on its own becomes its
    own run rather than being cut.
    """
    run: List[MarkdownLine] = []
    size = 0
    for line in chunk.lines:
        # The line as it will be written, indentation included, measured the
        # same way the whole chunk was -- `budget`, not `count`, because the
        # descent above sized the whole chunk that way. Summing a
        # differently-measured per-line cost against a window set in tokens is
        # how a run ends up three times the size it was allowed, and mixing
        # the two counters here would do it again in the other direction.
        cost = tokens.budget(line.render())
        if run and size + cost + 1 > window:
            out.append(_part_of(chunk, run, len(out)))
            run, size = [], 0
        run.append(line)
        size += cost + 1
    if run:
        out.append(_part_of(chunk, run, len(out)))


def _part_of(
    chunk: MarkdownChunk, lines: Sequence[MarkdownLine], ordinal: int
) -> MarkdownChunk:
    piece = MarkdownChunk(url=chunk.url, xpath=chunk.xpath, part=ordinal)
    piece.lines.extend(lines)
    return piece


def _merge(
    parts: Sequence[MarkdownChunk], url: str, xpath: str, ordinal: int
) -> MarkdownChunk:
    """Join sibling chunks into one rooted at their parent.

    Several merged chunks can share a root xpath, so the chunk id mixes in an
    ordinal — otherwise two distinct chunks of one long article would collide
    on their identifier and the second would overwrite the first.
    """
    if len(parts) == 1:
        return parts[0]
    merged = MarkdownChunk(url=url, xpath=xpath)
    merged.part = ordinal
    for part in parts:
        merged.lines.extend(part.lines)
    return merged


def _own_units_chunk(
    node: TrieNode,
    url: str,
    url_depth: int,
    memo: Optional["RenderMemo"] = None,
) -> Optional[Tuple[MarkdownChunk, int]]:
    """The units hanging directly off ``node``, excluding element children.

    Sized like `_render_sized`, and read-only for the same reason: it may be
    the memo's copy.
    """
    direct = TrieNode(segment=node.segment, depth=node.depth)
    direct._xpath_cache = getattr(node, "_xpath_cache", "/")
    for seg, child in node.children.items():
        if child.is_leaf or _is_terminal_pair(child):
            direct.children[seg] = child
    if not direct.children:
        return None
    # The synthetic node is not in the trie, so `rehash` never gave it a hash
    # and it would be unkeyable. Compose one the same way `_hash_node` would,
    # over the children it actually has: the own-units render is a function of
    # this node's leaf children and nothing else, so keying it on the parent's
    # full hash would throw the entry away every time an element child moved.
    direct.exact_hash = hash((
        node.segment, None, "",
        tuple(c.exact_hash for c in direct.ordered_children()),
    ))
    return _render_sized(direct, url, url_depth, memo)


# --- JSONL ------------------------------------------------------------------


def write_jsonl(chunks: Iterable[MarkdownChunk], path) -> int:
    """Write chunks as JSON lines, one chunk per line, in document order.

    JSONL rather than one JSON document so the file is appendable and
    streamable: a scan that is still running can flush chunks as it produces
    them, and a reader can start before the scan finishes. A single JSON array
    would have to be closed before it parsed at all.
    """
    n = 0
    with open(path, "w", encoding="utf-8") as fh:
        for chunk in chunks:
            fh.write(json.dumps(chunk.to_json(), ensure_ascii=False) + "\n")
            n += 1
    return n


def read_jsonl(path) -> Iterator[MarkdownChunk]:
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield MarkdownChunk.from_json(json.loads(line))
