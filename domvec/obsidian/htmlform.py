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
address in `data-domvec-address`, so pressing it names the thing the sensor
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
_MEDIA = re.compile(r"^!\[([^\]]*)\]\(([^)\s]*)\)\s*(.*)$")
#: The placeholder form: a picture the distiller found and could not locate.
#: `markdown.py` emits it deliberately -- see the comment on the `cat ==
#: "media"` branch, which stopped inventing a target rather than dropping the
#: line -- so a form that only matched `![alt](src)` sent every one of them
#: down the prose path and drew a picture as a sentence.
_MEDIA_BARE = re.compile(r"^!\[([^\]]*)\](?!\()\s*(.*)$")
_LINK = re.compile(r"^\[([^\]]*)\]\(([^)\s]*)\)\s*(.*)$")
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
    """Accumulates elements, keeping the nesting stack honest.

    The depth comes from the line's own indentation, which `_reflow` has
    already mapped onto one step per nesting LEVEL. A level that jumps by more
    than one opens the levels between it rather than nesting straight through,
    so the output is well formed however the page nested.
    """

    def __init__(self) -> None:
        self.out: List[str] = []
        self.depth = 0

    def at(self, depth: int) -> None:
        while self.depth < depth:
            self.out.append('<div class="dv-n">')
            self.depth += 1
        while self.depth > depth:
            self.out.append("</div>")
            self.depth -= 1

    def add(self, markup: str) -> None:
        self.out.append(markup)

    def close(self) -> str:
        self.at(0)
        return "".join(self.out)


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
    pairs = [("data-domvec-address", key)]
    if own and own != key:
        pairs.append(("data-domvec-line", own))
    return pairs


def render_lines(lines: List[Dict], *, base: str = "") -> str:
    """The distilled elements for one chunk's payload lines.

    Takes the payload rather than the store so that the markdown surface and
    this one are provably reading the same thing: one alignment of lines to
    addresses, used twice.
    """
    builder = _Builder()
    for line in lines:
        raw = str(line.get("text") or "")
        if not raw.strip():
            continue
        depth = (len(raw) - len(raw.lstrip(" "))) // 2
        builder.at(depth)
        builder.add(_element(raw.strip(), line, base))
    return builder.close()


def _element(text: str, line: Dict, base: str) -> str:
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
                      media.group(3), addr)
    placeholder = _MEDIA_BARE.match(body)
    if placeholder:
        return _media(placeholder.group(1), _absolute(_safe_url(target), base),
                      placeholder.group(2), addr)

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
           addr: List[Tuple[str, str]]) -> str:
    """A picture or a player, as a figure that keeps its caption.

    The `src` is emitted; whether it is FETCHED is settled by the surface,
    which strips it when the reader has media off. Loading a page's assets
    from inside a vault tells those hosts the page was read again, and that is
    the reader's decision to make, not this module's.
    """
    caption = _esc(alt or "image")
    tail = (" " + _esc(rest.strip())) if rest.strip() else ""
    if not src:
        return ('<figure class="dv-fig dv-fig-off"%s><div class="dv-noimg">%s'
                '</div><figcaption>%s%s</figcaption></figure>'
                % (_attrs(addr), _NO_IMAGE, caption, tail))
    return ('<figure class="dv-fig"%s><img class="dv-img" src="%s" alt="%s" '
            'loading="lazy" referrerpolicy="no-referrer">'
            '<figcaption>%s%s</figcaption></figure>'
            % (_attrs(addr), _esc(src), caption, caption, tail))


def chunk_html(workspace, cid: str) -> Optional[str]:
    """The distilled HTML for one stored chunk, or None if there is no chunk."""
    from .sidecar import chunk_payload

    payload = chunk_payload(workspace, cid)
    if payload is None:
        return None
    return render_lines(payload["lines"], base=payload.get("url", ""))
