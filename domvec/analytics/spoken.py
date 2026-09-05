"""Words the fold captured that the render never says.

Every other measure in this package grades an ADDRESS: reach asks whether an
affordance was captured, drawn, reachable, markable; the dedup matrix asks
whether a spelling was collapsed rightly or wrongly. All of them are
bookkeeping over addresses, and all of them can be perfectly satisfied while
the page's words go missing.

That is not hypothetical. `<a>Disable MathJax</a>` yields two addresses with
the same string; `_dedupe` kept one and `_render_unit` suppressed the other,
and each of those is a legitimate, counted outcome with a bucket to sit in.
Between the two of them the element drew no line at all and the words a
reader can see on the page were absent from the output. Nothing noticed,
because nothing was asking about WORDS -- only about addresses, and both
addresses were accounted for.

So this asks the one question the address ledger cannot:

``captured``
    a trie leaf holding text a reader can see. Urls and media values are
    excluded -- a destination is not something a reader reads, and the render
    deliberately draws it as `](target)` rather than as words.

``said``
    every one of its words appears somewhere in the rendered markdown, with
    link targets stripped so a url slug cannot stand in for the label it was
    built from.

``mute``
    at least one does not. Unlike `collapsed` in `reach`, this is scoped to
    the RENDER rather than to the fold, and to all content rather than to
    controls.

`mute` is broken down by tag, because the interesting question after "how
much" is always "what kind" -- the defect above would have shown as a spike
in `interactive.links` and nowhere else.

Over the 136-page corpus at the default window:

    captured  137,427
    mute          751        99.45% said

    text.visible            421
    interactive.links       165
    interactive.buttons     161
    interactive.inputs        4

The survivors are real. AP's `Cookie Settings` button is one: a control a
reader can press whose label the output never says, with `settings` present
and `cookie` absent.

An earlier reading of this table said `interactive.inputs` dominated at 1,487
and concluded that placeholders were going missing. That was the measure's
own scope error, not a defect -- see `_DESCRIPTOR_DETECTORS`. Real input
labels were never the problem, and they are 4 now.

**Why words and not the string.** The first version asked whether the value
appeared in the output as a substring, and was almost entirely false
positives: arxiv's `Authors: Ashish Vaswani , Noam Shazeer , ...` was called
mute with all twenty-five of its tokens present, and `[Submitted on 12 Jun
2017 ...]` with all sixteen. The render redistributes an element's words
across lines -- `_inline_flow`, `_join_labels` and the prose fold all do this
deliberately -- so a contiguous match tests line layout, not content
survival. It reported 94.51% and meant nothing.

Set containment is the conservative direction: it cannot be fooled by
reordering, and it under-reports rather than over-reports, because a value
whose words all happen to occur elsewhere on the page reads as said. That
trade is the right way round for a measure whose purpose is to find real
losses -- a number that is quietly too good is still a number you can act on
when it moves, and one that is loudly too bad is not.
"""

from __future__ import annotations

import collections
import pathlib
import re
import time
from typing import Dict, List, Sequence

from .reach import _visible_words
from .runs import stamp

DEFAULT_ARTIFACT_DIR = pathlib.Path("build_analytics")

#: Values shorter than this are punctuation, digits or single letters, where
#: a containment test says nothing: "a" is in almost any page.
_MIN_WORDS = 3

#: Categories whose value is a destination, not a reading.
_NOT_WORDS = ("urls", "media")


def _is_reader_text(address) -> bool:
    """Is this value words a reader SEES on the page?

    The scope has to be stated, because the first version did not state it
    and counted everything the trie held. `text.metadata` (`app-id=364677107,
    app-argument=...`), `json_data.ld_json` (`application/ld+json`) and
    `text.attributes` are machine data that the render drops deliberately, so
    including them measured the render doing its job and called it loss: mute
    read 4,324 over six pages, and its top examples were a viewport
    declaration and a mime type.

    `text.accessible` is excluded for a subtler reason. An `aria-label` IS
    words, but it is usually a second spelling of text the page already
    shows, and the collapse folds it away on purpose -- counting it here
    would re-measure dedup under a name that promises something else.

    What is left is what the question was about: visible prose, and the
    labels on things a reader can press.
    """
    tag = address.tag or ""
    return tag == "text.visible" or address.category == "interactive"


#: Detections whose value DESCRIBES the element rather than reading it.
#:
#: `content_tagger` emits two kinds of interactive detection and they look
#: alike from here. Three carry the element's words -- inputs, buttons and
#: anchors all pass `_own_name`/`_own_label`. The rest pass a selector:
#: `f'{tag}[role={role}]'`, `f'{tag}[contenteditable]'`, `f'{tag}[{attr}]'`.
#:
#: A selector's words are never on the page, so scoring it against the
#: rendered text is arithmetic, not measurement: `interactive.inputs|role`
#: read 1,479 mute of 1,618 captured, 91%, and `interactive.buttons|role`
#: 277 of 304. Together they were 59% of every loss the measure reported and
#: made `interactive.inputs` look like the worst class in the corpus. The
#: real input labels, `interactive.inputs|text()`, are 7 mute of 3,577.
_DESCRIPTOR_DETECTORS = frozenset({"role", "contenteditable",
                                   "data-wfh-interactive"})


def _describes_rather_than_reads(address, value: str) -> bool:
    """True when the value names the element instead of quoting the page."""
    detector = address.detector or ""
    if detector in _DESCRIPTOR_DETECTORS:
        return True
    if detector.startswith("on") and len(detector) > 2:
        return True                      # onclick, onsubmit, onfocus, ...
    # `interactive.forms` and `interactive.elements` pass the bare tag, and
    # `_own_name` falls back to it when an element genuinely has no words.
    # Both are the element's name, not the page's words, and there is already
    # a predicate for exactly that question.
    from ..markdown import _echoes_its_element
    return _echoes_its_element(address, value)


_LETTERS = re.compile(r"[^\W\d_]", re.UNICODE)

#: A value that IS a url, whatever category carries it. `interactive.links`
#: holds the anchor's label most of the time and the bare href when the
#: anchor has no words, and the second is a destination -- the render draws
#: it as a target, so looking for it among the visible words finds nothing
#: and every such value scored as a loss.
_IS_URL = re.compile(r"^(?:https?:)?//|^(?:mailto|tel|javascript):", re.I)


#: Word characters only, so the two sides are tokenised the SAME way.
#:
#: They were not, and it cost the measure its meaning. The render draws a
#: link as `[Sports](/hub/sports)`; `_visible_words` strips the target and
#: leaves `[sports]`, brackets attached, so splitting on whitespace yields the
#: token `[sports]` while the value yields `sports`. Every drawn link scored
#: as mute -- 1,932 of them over six pages, the largest category by far, all
#: of them words plainly visible in the output.
_TOKEN = re.compile(r"[^\W_]+", re.UNICODE)


def _tokens(text: str) -> List[str]:
    return _TOKEN.findall((text or "").lower())


def _words_of(value: str) -> List[str]:
    """The value's distinct words, or [] when there is nothing to match on."""
    text = " ".join((value or "").split())
    if len(text) < _MIN_WORDS or not _LETTERS.search(text):
        return []
    if _IS_URL.match(text):
        return []
    return list({w for w in _tokens(text) if _LETTERS.search(w)})


def score_page(trie, chunks) -> dict:
    """One page: how much captured text the render says, and what it drops."""
    # One set for the whole page, because the render is free to say an
    # element's words on any line -- folding a child's words into an
    # ancestor's sentence is the render working, not failing.
    spoken: set = set()
    for chunk in chunks:
        for line in chunk.lines:
            if line.text.strip():
                spoken.update(_tokens(_visible_words(line.text)))

    counts: Dict[str, int] = {"captured": 0, "said": 0, "mute": 0}
    mute_by_tag: collections.Counter = collections.Counter()
    examples: List[dict] = []

    for node in trie.leaves():
        address = node.address
        if address is None or address.category in _NOT_WORDS:
            continue
        if not _is_reader_text(address):
            continue
        if _describes_rather_than_reads(address, node.value or ""):
            continue
        words = _words_of(node.value or "")
        if not words:
            continue
        counts["captured"] += 1
        missing = [w for w in words if w not in spoken]
        if not missing:
            counts["said"] += 1
            continue
        counts["mute"] += 1
        mute_by_tag[address.tag] += 1
        if len(examples) < 5:
            examples.append({"tag": address.tag,
                             "xpath": address.xpath,
                             "words": (node.value or "")[:80],
                             "missing": missing[:6]})

    return {"captured": counts["captured"], "said": counts["said"],
            "mute": counts["mute"], "mute_by_tag": dict(mute_by_tag),
            "examples": examples}


def measure_spoken(pages: Sequence[pathlib.Path], *,
                   window: int = 1200) -> dict:
    """Every corpus page, folded and rendered offline."""
    from ..core.content_tagger import ContentTagger
    from ..core.shadow_html_parser import ShadowDOM
    from ..markdown import render_trie
    from ..trie import AddressTrie

    rows: List[dict] = []
    for path in pages:
        try:
            html = path.read_text(encoding="utf-8", errors="replace")
            trie = AddressTrie.from_tagged(
                ContentTagger(ShadowDOM(html)).tag(),
                "https://corpus.test/%s" % path.stem)
            chunks = render_trie(trie, context_window=window)
        except Exception as exc:                        # noqa: BLE001
            rows.append({"page": path.name, "error": str(exc)[:120]})
            continue
        row = score_page(trie, chunks)
        row["page"] = path.name
        rows.append(row)
    return {"rows": rows, "t": time.time(), "context_window": window}


def render_spoken_table(report: dict) -> str:
    rows = [r for r in report.get("rows", []) if not r.get("error")]
    if not rows:
        return "  no spoken measurements"

    total: collections.Counter = collections.Counter()
    by_tag: collections.Counter = collections.Counter()
    for row in rows:
        for key in ("captured", "said", "mute"):
            total[key] += row.get(key, 0)
        for tag, n in (row.get("mute_by_tag") or {}).items():
            by_tag[tag] += n

    out = ["  %-46s %8s %8s %7s" % ("page", "captured", "mute", "said%")]
    worst = sorted(rows, key=lambda r: -r.get("mute", 0))[:12]
    for row in worst:
        captured = row.get("captured", 0)
        out.append("  %-46s %8d %8d %6.2f%%" % (
            row["page"][:46], captured, row.get("mute", 0),
            100.0 * row.get("said", 0) / captured if captured else 100.0))

    captured = total["captured"] or 1
    out.append("")
    out.append("  %-46s %8d %8d %6.2f%%" % (
        "TOTAL (%d pages)" % len(rows), total["captured"], total["mute"],
        100.0 * total["said"] / captured))
    if by_tag:
        out.append("")
        out.append("  mute by tag:")
        for tag, n in by_tag.most_common(8):
            out.append("    %-28s %6d" % (tag, n))
    return "\n".join(out)


def write_spoken_artifact(report: dict,
                          directory: pathlib.Path = DEFAULT_ARTIFACT_DIR
                          ) -> pathlib.Path:
    import json

    directory = pathlib.Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "spoken.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        for row in report.get("rows", []):
            record = stamp(dict(row))
            record["t"] = report.get("t")
            record["context_window"] = report.get("context_window")
            handle.write(json.dumps(record) + "\n")
    return path
