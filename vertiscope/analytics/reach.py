"""Does everything the fold captured reach a reader, and can the reader act on it?

Three surfaces stand between a control in the page and a caller who can press
it, and each loses things for its own reason:

``captured``
    the fold recorded an ``interactive.*`` address at that xpath.

``drawn``
    a rendered markdown line was drawn from that element -- from ANY of its
    addresses.

``reachable``
    ``live.Node.acts()`` would hand it to a caller.

``markable``
    ``live.Node.read()`` can put an ``act(n)`` handle on the line that drew
    it, which is the only thing that makes what a reader SEES and what a
    reader can PRESS the same surface.

``empty``
    the element has no text content IN THE DOCUMENT, so there was never
    anything to draw. `<a name="chap01">` and an empty permalink anchor are
    affordances the fold is right to record and a reader cannot be shown.

``collapsed``
    the page shows words for it and the fold did not address them there. A
    real miss, and the interesting one.

``labelled``
    of the controls that WERE drawn, the ones whose line carries the page's
    own words for them rather than only a destination.

Over the whole corpus, 136 pages and 79,186 captured affordances:

    empty        164   nothing to draw, excused
    collapsed     25   the page shows words the fold does not address
    drawn      99.50% of captured, 99.71% of drawable
    reachable 100.00%
    labelled   88.44% of those drawn with words to show

`labelled` is the one to read carefully, and any subset of this corpus
flatters it: the first ten pages score 92.99% because they are link-rich
news front pages. Quote the 136-page figure.

These moved a long way in one session and the history says why, because each
step was a defect rather than a tuning:

    labelled   45.35 -> 77.38   links carry their own words, not the tag name
               77.38 -> 87.08   a one-word label is a label -- the guard had
                                been `_is_tag_name`, "short and alphabetic",
                                which discarded `Espanol`, `China`, `Europe`
               87.08 -> 88.44   buttons and inputs the same way (a field is
                                named by its placeholder), and a container is
                                no longer marked down for declining to repeat
                                its contents
    collapsed  1,173 ->    786  the first two changes
                786 ->     25  a link that is its element's ONLY unit draws
                                instead of being suppressed -- arxiv's
                                `Disable MathJax` is an `<a>` with no href and
                                no handler, so suppression drew it nowhere

Earlier figures in this file's own history read 99.98% drawn and 9.6% drawn,
both wrong, both from asking with the wrong key. Numbers here are only worth
what the question behind them is worth.

**`drawn` cannot see whether a control arrived with its label**, and that is
worth stating because it hid a real defect for as long as this file existed.
A tagger-path anchor used to draw as two lines at one xpath -- `</target>`
and `Glacial Retreat Calculator` -- and `drawn` counted the xpath either way,
so merging them into `[Glacial Retreat Calculator](/target)` moved this
measure by exactly nothing while changing what a reader sees. `labelled` is
the column that moves.

**The excused set is a denominator, so getting it wrong flatters the render.**
The first version of this asked the FOLD whether any text existed at or under
the control, and excused it when none did. That over-excused, because
`content_tagger` emits a paragraph whose children are all inline as ONE text
unit at the paragraph and adds every descendant to `_skip_text_ids`. An `<a>`
inside prose has no text addressed at it even though the page plainly shows
its words, so it was filed as nothing-to-draw and dropped from a denominator
it belongs in. Over the whole corpus the old test excused 1,340 controls and
only 165 deserved it: 1,175 real misses were being written off, and the
reported figure moved from 99.98% to 98.50%.

Those 1,175 are the largest remaining loss in the pipeline before
vectorisation, and they are one defect with one cause -- the all-inline
collapse -- rather than a long tail.

So the arbiter is the PARSE, which knows nothing of `_skip_text_ids` and
nothing of the render: does this element have non-whitespace text content?
Not the fold, which is the thing under test on this exact point, and not the
render, since "not a miss because it was not drawn" is circular.

`affordance.py` asks a different and complementary question -- whether the
REPL invents controls or misses ones the page lays out -- against JS ground
truth in a live browser. This one is browser-free and asks about the stretch
between the distiller and the object model, which is where a control is lost
without anything outside the process being able to tell.

**Why this is keyed on xpath and not on the address key.** A link is captured
as ``interactive.links`` and DRAWN from its ``urls.*`` address, because the
renderer suppresses the interactive one as noise beside the href it already
has. Keyed on the full address key those are two different strings, so every
anchor on every page scores as captured-and-not-drawn: the same measurement
run that way reported 9.6% drawn, and the 90% it called a loss was entirely
the question's fault. What a caller needs to know is whether the control AT
THIS POSITION reached the page. Which of its several addresses carried it
there is the renderer's business.

    python -m vertiscope.analytics --reach
    python -m vertiscope.analytics --reach --limit 20

Writes ``build_analytics/reach.jsonl``, one row per page.
"""

from __future__ import annotations

import collections
import io
import json
import pathlib
import re
import sys
import time
from typing import Dict, List, Sequence

from .runs import stamp

DEFAULT_ARTIFACT_DIR = pathlib.Path("build_analytics")


def _leaf_tag(xpath: str) -> str:
    step = xpath.rstrip("/").split("/")[-1]
    return step.split("[")[0].lower()


#: Attributes a page uses to name a control when its words are a picture.
_LABEL_ATTRS = ("aria-label", "title", "alt", "placeholder", "value")

#: How far below an element to look for something it could be called. Three
#: covers `<a><div><img alt><h2>Headline</h2></div></a>`, which is the shape
#: this exists for, and keeps the walk linear in the page.
_LABEL_DEPTH = 3

#: Shorter than this and a match proves nothing -- "AP" appears inside
#: hundreds of unrelated lines.
_MIN_LABEL = 4

#: What a reader can act on, in the one vocabulary.
_CONTROL_CLASSES = frozenset({"link", "button", "field",
                              "choice", "check", "slider"})


#: A markdown link's target, and a bare target line. Stripped before a label
#: is looked for, because a target is not something a reader can read.
_TARGET_RE = re.compile(r"\]\([^)]*\)")
_BARE_RE = re.compile(r"<[^>]*>")


def _visible_words(text: str) -> str:
    """A line with its destinations removed -- what a reader actually sees.

    Matching against the whole line counted a url slug as a label. AP's
    `<https://apnews.com/hub/tennis>` is a bare target with no words in it,
    and the candidate `Tennis` matched because the word is in the path: the
    line said nothing to a reader and scored as labelled. Slugs are built
    from labels, so this is not a rare coincidence -- it is systematic, and
    it flatters exactly the bare-target lines the column exists to count.
    """
    without = _TARGET_RE.sub("]", text)
    without = _BARE_RE.sub(" ", without)
    return " ".join(without.split()).lower()


def _labels_by_xpath(dom) -> Dict[str, List[str]]:
    """canon xpath -> every string the page could reasonably be calling it.

    The independent arbiter, built from the parse: it consults neither the
    fold's addressing nor the render's output, which is what lets it decide
    `empty` and `labelled` without either grading its own work.

    **Several candidates, not one string.** The first version returned
    `get_text(recursive=True)` and compared its first 40 characters. That
    walks `iter_all()` and folds in `alt` and `aria-label` for childless
    nodes, so an anchor wrapping a photo and a headline answered with the
    photo's caption -- and a line correctly drawn as
    `[Western Europe sets new temperature record...]` scored as unlabelled
    because the caption came first. Roughly 2,000 cases, all of them
    reporting the render as worse than it is.

    A control has more than one true name: its words, the words of anything
    inside it, and whatever `aria-label`, `title` or `alt` calls it. Any of
    them appearing in the drawn line means the reader can tell what it is,
    which is the question being asked.

    `out[xpath][0]` is the whole text when there is any, so truthiness still
    answers `empty` exactly as before.
    """
    out: Dict[str, List[str]] = {}

    def names(node) -> List[str]:
        found: List[str] = []
        frontier = [(node, 0)]
        while frontier:
            here, depth = frontier.pop()
            own = " ".join((getattr(here, "text", "") or "").split())
            if len(own) >= _MIN_LABEL:
                found.append(own)
            for attr in _LABEL_ATTRS:
                try:
                    value = " ".join((here.get_attr(attr, "") or "").split())
                except Exception:                       # noqa: BLE001
                    continue
                if len(value) >= _MIN_LABEL:
                    found.append(value)
            if depth < _LABEL_DEPTH:
                try:
                    kids = here.get_children(include_shadow=True)
                except Exception:                       # noqa: BLE001
                    kids = []
                frontier.extend((k, depth + 1) for k in kids
                                if k.tag and not k.tag.startswith("#"))
        return found

    def walk(node, path):
        kids = [k for k in node.get_children(include_shadow=True)
                if k.tag and not k.tag.startswith("#")]
        seen: collections.Counter = collections.Counter()
        for kid in kids:
            tag = kid.tag.lower()
            seen[tag] += 1
            here = "%s/%s[%d]" % (path, tag, seen[tag])
            try:
                whole = " ".join(
                    (kid.get_text(recursive=True, separator=" ") or "").split())
            except Exception:                           # noqa: BLE001
                whole = ""
            candidates = [whole] if whole else []
            candidates.extend(names(kid))
            out[here] = candidates
            walk(kid, here)

    walk(getattr(dom, "root", dom), "")
    return out


def score_page(trie, chunks, dom=None) -> dict:
    """One page's counts, and the taxonomy labels behind each loss."""
    from ..live import _canon, _page_root, _under, Node

    captured: Dict[str, str] = {}
    labels: List[str] = []
    for leaf in trie.leaves():
        address = leaf.address
        if address is None:
            continue
        tag = address.tag or ""
        # `render_class`, so this counts controls on BOTH pipelines. Asking
        # `tag.startswith("interactive")` counted only the tagger's, which is
        # why every figure in this file describes the snapshot path.
        if address.is_control:
            captured[_canon(address.xpath)] = tag
        elif (address.render_class in ("text", "image", "media")
                and (leaf.value or "").strip()):
            labels.append(_canon(address.xpath))
    labels.sort()

    # xpath -> the line that drew it. A set of xpaths answers "did it reach
    # the page"; the text is what answers "did it arrive with its label".
    drawn: Dict[str, List[str]] = collections.defaultdict(list)
    for chunk in chunks:
        for line in chunk.lines:
            if not line.text.strip():
                continue
            for address in (line.address,) + tuple(line.inline):
                if address is not None:
                    drawn[_canon(address.xpath)].append(line.text)

    root = Node(_page_root(trie))
    reachable = {_canon(node.xpath) for node in root.acts()}
    shows_text = _labels_by_xpath(dom) if dom is not None else {}

    # xpaths that hold another control. Built once from the captured set,
    # sorted so the ancestry test is a prefix scan rather than a product.
    _control_paths = sorted(captured)

    def contains_a_control(xpath: str) -> bool:
        prefix = xpath + "/"
        return any(other.startswith(prefix) for other in _control_paths)

    def carries_label(xpath: str, lines: Sequence[str]) -> bool:
        """Does the line a control was drawn on say what the page calls it?

        The arbiter is the PARSE, as it is for `empty`: the element's own
        text content, which neither the fold's addressing nor the render's
        output has a say in. Compared on a bounded prefix, since a long
        label is wrapped or truncated by the render and the question is
        whether the words are there at all, not whether they are complete.
        """
        candidates = shows_text.get(xpath) or ()
        if not candidates:
            return False
        # A container is not unlabelled because it does not repeat its
        # contents.
        #
        # `<form>` draws as `=== form ===`, which is the right line for it --
        # the fields inside are drawn as their own controls. But this
        # arbiter's first candidate is `get_text(recursive=True)`, so the
        # form was being asked to show "Keyword Search... Search Query
        # Submit Search" on its own line, and scored unlabelled for not
        # doing it. 51 of ~80 residual cases on ten pages were this, plus
        # every `<label>` wrapping an input.
        #
        # A control with interactive DESCENDANTS is a container: whatever
        # words it has belong to the things inside it, and those are counted
        # in their own right. Judged from the parse, like everything else
        # here -- `contains` is built from the same walk.
        if contains_a_control(xpath):
            return True
        # ANY line that carries this control's address, against ANY name
        # the page has for it.
        #
        # Keeping only the first line read a later experiment as a
        # 10.6-point regression it was not. An anchor can be on several
        # lines -- its own, and its `title` tooltip -- and once a link is
        # merged into its sentence, taking the first hands back the tooltip:
        # Arabic Wikipedia scored `[the main page](/wiki/...)` as unlabelled
        # because the line it looked at said "main page button [z]".
        drawn_text = [_visible_words(one) for one in lines]
        for name in candidates:
            head = name[:40].strip().lower()
            if len(head) < _MIN_LABEL:
                continue
            if any(head in one for one in drawn_text):
                return True
        return False

    by_label: Dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter)
    undrawn_tags: collections.Counter = collections.Counter()
    counts = collections.Counter()
    for xpath, label in captured.items():
        counts["captured"] += 1
        is_drawn = xpath in drawn
        is_reach = xpath in reachable
        counts["drawn"] += is_drawn
        counts["reachable"] += is_reach
        counts["markable"] += (is_drawn and is_reach)
        if is_drawn:
            if carries_label(xpath, drawn.get(xpath, ())):
                counts["labelled"] += 1
                by_label[label]["labelled"] += 1
            elif shows_text.get(xpath):
                counts["unlabelled"] += 1
                by_label[label]["unlabelled"] += 1
        by_label[label]["captured"] += 1
        if not is_drawn:
            # Asked only of the undrawn, because it is a question about them
            # and the scan is the expensive part of this measure.
            in_fold = any(_under(at, xpath) for at in labels)
            if in_fold or shows_text.get(xpath):
                # The page shows words for it. A real miss either way: the
                # `in_fold` case is one the render dropped, the other one the
                # fold never addressed here.
                by_label[label]["undrawn"] += 1
                undrawn_tags[_leaf_tag(xpath)] += 1
                if not in_fold:
                    counts["collapsed"] += 1
                    by_label[label]["collapsed"] += 1
            else:
                counts["empty"] += 1
                by_label[label]["empty"] += 1
        if not is_reach:
            by_label[label]["unreachable"] += 1

    return {
        "captured": counts["captured"],
        "drawn": counts["drawn"],
        "reachable": counts["reachable"],
        "markable": counts["markable"],
        "empty": counts["empty"],
        "collapsed": counts["collapsed"],
        "labelled": counts["labelled"],
        "unlabelled": counts["unlabelled"],
        "by_label": {k: dict(v) for k, v in by_label.items()},
        "undrawn_tags": dict(undrawn_tags.most_common(8)),
    }


def measure_reach(pages: Sequence[pathlib.Path], *,
                  window: int = 1200) -> dict:
    """Every corpus page, folded and rendered offline."""
    from ..core.content_tagger import ContentTagger
    from ..core.shadow_html_parser import ShadowDOM
    from ..markdown import render_trie
    from ..trie import AddressTrie

    rows: List[dict] = []
    for page in pages:
        row: Dict[str, object] = {"page": page.name}
        try:
            html = io.open(page, encoding="utf-8", errors="replace").read()
            tagged = ContentTagger(ShadowDOM(html)).tag()
            trie = AddressTrie.from_tagged(tagged, "https://x.test/" + page.stem)
            # A second parse for the arbiter. The tagger keeps state across
            # its walk and the point of this check is to be downstream of
            # none of it, so the extra parse is the price of independence.
            row.update(score_page(trie, render_trie(trie,
                                                    context_window=window),
                                  dom=ShadowDOM(html)))
        except Exception as exc:                        # noqa: BLE001
            row["error"] = "%s: %s" % (type(exc).__name__, exc)[:160]
        rows.append(row)
        print("  %-46s %s" % (
            page.name[:46],
            row.get("error") or "captured=%(captured)-6d drawn=%(drawn)-6d "
                                "markable=%(markable)-6d" % row),
            file=sys.stderr, flush=True)
    return {"rows": rows, "t": time.time(), "context_window": window}


def render_reach_table(report: dict) -> str:
    rows = [r for r in report.get("rows", []) if not r.get("error")]
    if not rows:
        return "  no reach measurements"

    total = collections.Counter()
    by_label: Dict[str, collections.Counter] = collections.defaultdict(
        collections.Counter)
    undrawn_tags: collections.Counter = collections.Counter()
    for row in rows:
        for key in ("captured", "drawn", "reachable", "markable",
                    "empty", "collapsed", "labelled", "unlabelled"):
            total[key] += row.get(key, 0)
        for label, counts in (row.get("by_label") or {}).items():
            for key, n in counts.items():
                by_label[label][key] += n
        for tag, n in (row.get("undrawn_tags") or {}).items():
            undrawn_tags[tag] += n

    cap = total["captured"] or 1
    # Every control that had a label to draw. The rest were never drawable,
    # and holding the render to them measures the corpus's `<a name=...>`
    # anchors rather than the render.
    drawable = max(cap - total["empty"], 1)
    out = ["", "  from a control in the page to a caller who can press it", ""]
    out.append("  pages                          %7d" % len(rows))
    out.append("  captured by the fold           %7d" % total["captured"])
    out.append("  of those, empty in the page    %7d  (no text content at "
               "all -- excused)" % total["empty"])
    out.append("  of those, words not addressed  %7d  (the page shows them; "
               "COUNTED as a miss)" % total["collapsed"])
    out.append("")
    # `drawable` is the denominator for the two questions the render
    # answers. It is NOT one for `reachable`: a label-less anchor is as
    # reachable as any other, and dividing it out gave 101.35%.
    for key, what, against_drawable in (
            ("drawn", "drawn in the markdown", True),
            ("reachable", "reachable from acts()", False),
            ("markable", "markable by read()", True)):
        line = "  %-30s %7d  (%.2f%% of captured" % (
            what, total[key], 100.0 * total[key] / cap)
        if against_drawable:
            line += ", %.2f%% of drawable" % (100.0 * total[key] / drawable)
        out.append(line + ")")

    # Of the ones that reached the page, how many arrived with their name.
    # `drawn` counts an xpath however its line reads, so a control drawn as
    # a bare destination scores the same as one drawn as `[words](target)`.
    # This is the column that separates them.
    shown = total["labelled"] + total["unlabelled"]
    if shown:
        out.append("")
        out.append("  %-30s %7d  (%.2f%% of those drawn with words to show)"
                   % ("drawn WITH the page's words", total["labelled"],
                      100.0 * total["labelled"] / shown))
        out.append("  %-30s %7d  (drawn, but only as a destination)"
                   % ("drawn WITHOUT them", total["unlabelled"]))
    out.append("")
    out.append("  %-26s %9s %9s %10s %11s"
               % ("taxonomy label", "captured", "undrawn", "empty",
                  "unreachable"))
    for label, counts in sorted(by_label.items(),
                                key=lambda kv: -kv[1]["captured"]):
        out.append("  %-26s %9d %9d %10d %11d"
                   % (label, counts["captured"], counts["undrawn"],
                      counts["empty"], counts["unreachable"]))
    if undrawn_tags:
        out.append("")
        out.append("  elements the render did not draw:")
        for tag, n in undrawn_tags.most_common(10):
            out.append("    %-16s %7d" % (tag or "(none)", n))
    out.append("")
    out.append("  Only a control with NO text content in the document is")
    out.append("  excused. Asking the fold instead excused 1,340 over the")
    out.append("  corpus where 165 deserved it, because the tagger collapses an")
    out.append("  all-inline paragraph into one unit and skips its")
    out.append("  descendants -- so an anchor in prose had no text addressed")
    out.append("  at it while the page showed its words. That read 99.98%")
    out.append("  where the honest figure is 98.50%. The arbiter is the")
    out.append("  PARSE: not the fold, which is under test on this point, and")
    out.append("  not the render, since \'not a miss because it was not")
    out.append("  drawn\' is circular.")
    out.append("")
    out.append("  Keyed on POSITION, never on the address key. A link is")
    out.append("  captured as `interactive.links` and drawn from its `urls.*`")
    out.append("  address, so comparing keys reports every anchor on every")
    out.append("  page as lost -- 9.6% drawn, and the 90% gap the question's")
    out.append("  own fault. See this module's docstring.")
    return chr(10).join(out)


def write_reach_artifact(report: dict,
                         out_dir: pathlib.Path = DEFAULT_ARTIFACT_DIR
                         ) -> pathlib.Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "reach.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        for row in report.get("rows", []):
            record = stamp(dict(row))
            record["t"] = report.get("t")
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    return path
