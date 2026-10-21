"""Element type to ARIA role to render class. The one classification we keep.

Two rebuilds of search-and-pagination detection settled at the same ceiling —
70.1% and 41.3% across 890 pages on 605 hosts — one lexical, one structural.
The ceiling was not the classifier. It was the premise: "a search box" and "a
pager" name *intentions*, and a page expresses intention however its author
chose, so there is nothing stable to learn.

What a page does declare, and declares in HTML, is what each element *is*.
Measured across five unrelated pages — a search engine, an archive, a news
site, an encyclopedia, a scraping fixture — 9,315 elements yielded 2,392
affordances, of which

    natively semantic (a/button/input/select/textarea/summary)   98.6%
    explicit role=                                                3.8%
    any aria-*                                                    7.0%
    opaque: no semantic tag, no role                              0.3%

So the mapping below is load-bearing for essentially everything, and the part
we genuinely cannot know is seven elements in two thousand.

This is HTML-AAM's table, not a heuristic of ours. It is finite, published,
does not grow with the web, needs no per-site maintenance, and is the same
computation every browser already performs to drive assistive technology —
which is the strongest evidence available that it survives contact with real
pages, because screen readers have run on it for twenty years.

The render class is then a function of the role alone: what to *draw*, never
what it means. A search box renders as a field because it is a field; a pager
renders as links because they are links. Both work without being named, which
is the whole point — a control we could not name used to be a control the
reader never saw.

`sensor.js` carries the same tables so the in-page fold classifies
identically. They are data, not logic, and `invariants.a1_aam_tables_agree`
parses them back out of the JS and compares — checked rather than trusted,
because a silent divergence would make every comparison between the two paths
measure the disagreement instead of the thing under test.
"""

from __future__ import annotations

from typing import Dict, Mapping, Optional, Tuple

__all__ = [
    "role_of",
    "kind_of",
    "render_class",
    "IMPLICIT_ROLE",
    "RENDER_CLASS",
    "INTERACTIVE",
    "GLYPH",
]


# --- element type -> implicit ARIA role (HTML-AAM) ---------------------------
# Tag names lowercased. Entries needing an attribute test are handled in
# `role_of` and deliberately left out of the plain table.
IMPLICIT_ROLE: Dict[str, str] = {
    "article": "article",
    "aside": "complementary",
    "blockquote": "blockquote",
    "button": "button",
    "caption": "caption",
    "code": "code",
    "datalist": "listbox",
    "dd": "definition",
    "del": "deletion",
    "details": "group",
    "dfn": "term",
    "dialog": "dialog",
    "dt": "term",
    "em": "emphasis",
    "fieldset": "group",
    "figcaption": "caption",
    "figure": "figure",
    "footer": "contentinfo",
    "form": "form",
    "h1": "heading", "h2": "heading", "h3": "heading",
    "h4": "heading", "h5": "heading", "h6": "heading",
    "header": "banner",
    "hgroup": "group",
    "hr": "separator",
    "ins": "insertion",
    "li": "listitem",
    "main": "main",
    "mark": "mark",
    "math": "math",
    "menu": "list",
    "meter": "meter",
    "nav": "navigation",
    "ol": "list",
    "optgroup": "group",
    "option": "option",
    "output": "status",
    "p": "paragraph",
    "pre": "code",
    "progress": "progressbar",
    "samp": "code",
    "search": "search",
    "strong": "strong",
    "sub": "subscript",
    "summary": "button",
    "sup": "superscript",
    "svg": "graphics-document",
    "table": "table",
    "tbody": "rowgroup",
    "textarea": "textbox",
    "tfoot": "rowgroup",
    "thead": "rowgroup",
    "time": "time",
    "tr": "row",
    "ul": "list",
    "video": "video",
    "audio": "audio",
    "iframe": "document",
    "picture": "image",
}

# input[type] -> role. An input's type is the whole of its identity, and an
# unrecognised or absent type is `text` per the HTML parser, not "unknown".
INPUT_ROLE: Dict[str, str] = {
    "button": "button",
    "checkbox": "checkbox",
    "color": "textbox",
    "date": "textbox",
    "datetime-local": "textbox",
    "email": "textbox",
    "file": "button",
    "hidden": "none",
    "image": "button",
    "month": "textbox",
    "number": "spinbutton",
    "password": "textbox",
    "radio": "radio",
    "range": "slider",
    "reset": "button",
    "search": "searchbox",
    "submit": "button",
    "tel": "textbox",
    "text": "textbox",
    "time": "textbox",
    "url": "textbox",
    "week": "textbox",
}


# --- role -> render class ----------------------------------------------------
# What to draw. Every entry is decidable from the role with no ambiguity and
# no knowledge of the author's intent.
RENDER_CLASS: Dict[str, str] = {
    # interactive
    "link": "link",
    "button": "button",
    "checkbox": "check",
    "radio": "check",
    "switch": "check",
    "menuitemcheckbox": "check",
    "menuitemradio": "check",
    "combobox": "choice",
    "listbox": "choice",
    "textbox": "field",
    "searchbox": "field",
    "spinbutton": "field",
    "slider": "slider",
    "option": "item",
    "menuitem": "button",
    "tab": "button",
    # structure
    "heading": "heading",
    "listitem": "item",
    "row": "row",
    "cell": "cell",
    "gridcell": "cell",
    "columnheader": "cell",
    "rowheader": "cell",
    "table": "group",
    "grid": "group",
    "rowgroup": "group",
    "list": "group",
    "group": "group",
    "form": "group",
    "search": "group",
    "navigation": "group",
    "region": "group",
    "main": "group",
    "article": "group",
    "complementary": "group",
    "banner": "group",
    "contentinfo": "group",
    "dialog": "group",
    "figure": "group",
    "tablist": "group",
    "separator": "rule",
    # media
    "img": "image",
    "image": "image",
    "graphics-document": "image",
    "video": "media",
    "audio": "media",
    "document": "media",
    # text
    "paragraph": "text",
    "blockquote": "quote",
    "code": "code",
    "emphasis": "text",
    "strong": "text",
    "mark": "text",
    "caption": "text",
    "term": "text",
    "definition": "text",
    "status": "text",
    "time": "text",
    "meter": "text",
    "progressbar": "text",
    "math": "text",
    "insertion": "text",
    "deletion": "text",
    "subscript": "text",
    "superscript": "text",
    "none": "none",
    "presentation": "none",
}

# The classes a reader can act on. Stage 5 dispatches against exactly these.
INTERACTIVE = frozenset({"link", "button", "check", "choice", "field",
                         "slider"})

# Minimalist ASCII, one form per class. Structure only — no colour, no box
# drawing, nothing markdown cannot say.
GLYPH: Dict[str, str] = {
    "link": "[{label}]",
    "button": "<{label}>",
    "field": "[{value}]",
    "slider": "[={value}=]",
    "choice": "{label} v",
    "check": "[{mark}] {label}",
    "heading": "{hashes} {label}",
    "item": "- {label}",
    "row": "| {label}",
    "cell": "{label}",
    "quote": "> {label}",
    "code": "`{label}`",
    "image": "![{label}]({value})",
    "media": "({label}) {value}",
    "rule": "---",
    "text": "{label}",
    "group": "{label}",
    "none": "",
}


def role_of(tag: str, attrs: Optional[Mapping[str, str]] = None) -> str:
    """The implicit ARIA role of one element, per HTML-AAM.

    An explicit ``role=`` wins, because the page saying what a thing is
    outranks us inferring it — that is tier 2 evidence and the author is
    entitled to it. Everything else comes from the element type and, where
    the type alone does not decide, from the attributes the spec names.
    """
    attrs = attrs or {}
    tag = (tag or "").lower()

    explicit = (attrs.get("role") or "").strip().lower()
    if explicit:
        # A role list is legal; the first token that is a role wins.
        for token in explicit.split():
            if token in RENDER_CLASS:
                return token

    if tag == "a" or tag == "area":
        return "link" if attrs.get("href") is not None else "generic"
    if tag == "input":
        kind = (attrs.get("type") or "text").strip().lower()
        role = INPUT_ROLE.get(kind, "textbox")
        # A text input bound to a datalist is a combobox, which is the one
        # place an input's type is not the whole story.
        if role == "textbox" and attrs.get("list") is not None:
            return "combobox"
        return role
    if tag == "select":
        multiple = attrs.get("multiple") is not None
        try:
            size = int(attrs.get("size") or "0")
        except ValueError:
            size = 0
        return "listbox" if (multiple or size > 1) else "combobox"
    if tag == "img":
        # alt="" is an explicit statement that the image is decorative, and
        # is not the same as a missing alt.
        return "none" if attrs.get("alt") == "" else "img"
    if tag == "th":
        scope = (attrs.get("scope") or "").strip().lower()
        return "rowheader" if scope == "row" else "columnheader"
    if tag == "td":
        return "cell"
    if tag == "section":
        # A section is a region only when it has an accessible name; without
        # one it is a plain grouping and claiming otherwise invents landmarks.
        named = attrs.get("aria-label") or attrs.get("aria-labelledby")
        return "region" if named else "group"

    return IMPLICIT_ROLE.get(tag, "generic")


def render_class(role: str) -> str:
    """What to draw for a role. Unmapped roles are text, never invisible."""
    return RENDER_CLASS.get(role, "text")


# Elements whose whole purpose is to carry a resource, and the attributes
# that carry it. Mirrored by `MEDIA_TAGS` / `hasSource` in sensor.js.
MEDIA_TAGS = frozenset({"img", "picture", "svg", "video", "audio",
                        "source", "iframe", "embed", "object"})
MEDIA_SRC_ATTRS = ("src", "srcset", "poster", "data", "data-src", "href")
_STILL = frozenset({"img", "picture", "svg"})


def has_source(attrs: Optional[Mapping[str, str]] = None) -> bool:
    """Whether an element carries a resource reference."""
    attrs = attrs or {}
    return any((attrs.get(name) or "").strip() for name in MEDIA_SRC_ATTRS)


def kind_of(tag: str, attrs: Optional[Mapping[str, str]] = None) -> Tuple[str, str]:
    """``(render class, role)`` for one element.

    A picture with no alt text is still a picture. ``role_of`` is faithful to
    HTML-AAM, where ``<img alt="">`` is presentational -- an empty alt is the
    author saying "do not announce this", which is a statement about
    announcement and not about whether the file exists. Using the role as the
    render class turned it into the second thing and dropped the reference:
    every illustration on lit.dev carries ``alt=""``, and the page rendered
    with none of its images.

    So the role is left exactly as the standard has it and the class is
    corrected here. The tables stay honest for invariant ``a1``; what a
    reader is shown is a separate decision, made in this function.
    """
    role = role_of(tag, attrs)
    kind = render_class(role)
    tag = (tag or "").lower()
    if kind == "none" and tag in MEDIA_TAGS and has_source(attrs):
        return ("image" if tag in _STILL else "media"), role
    return kind, role


def is_interactive(kind: str) -> bool:
    return kind in INTERACTIVE
