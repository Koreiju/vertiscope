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

**The excused set is a denominator, so getting it wrong flatters the render.**
The first version of this asked the FOLD whether any text existed at or under
the control, and excused it when none did. That over-excused, because
`content_tagger` emits a paragraph whose children are all inline as ONE text
unit at the paragraph and adds every descendant to `_skip_text_ids`. An `<a>`
inside prose has no text addressed at it even though the page plainly shows
its words, so it was filed as nothing-to-draw and dropped from a denominator
it belongs in. Of 164 undrawn controls on 12 pages, 104 were that and 59 were
genuinely empty -- so the reported figure moved from 99.98% to 98.42%, and
the higher number was the measure excusing the render its most common miss.

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

    python -m domvec.analytics --reach
    python -m domvec.analytics --reach --limit 20

Writes ``build_analytics/reach.jsonl``, one row per page.
"""

from __future__ import annotations

import collections
import io
import json
import pathlib
import sys
import time
from typing import Dict, List, Sequence

DEFAULT_ARTIFACT_DIR = pathlib.Path("build_analytics")


def _leaf_tag(xpath: str) -> str:
    step = xpath.rstrip("/").split("/")[-1]
    return step.split("[")[0].lower()


def _text_by_xpath(dom) -> Dict[str, bool]:
    """canon xpath -> does this element have text content in the document?

    Siblings are numbered the way an xpath numbers them, so the keys line up
    with the fold's addresses. This is the independent arbiter for `empty`:
    it is built from the parse and consults neither the fold's addressing nor
    the render's output.
    """
    out: Dict[str, bool] = {}

    def walk(node, path):
        kids = [k for k in node.get_children(include_shadow=True)
                if k.tag and not k.tag.startswith("#")]
        seen: collections.Counter = collections.Counter()
        for kid in kids:
            tag = kid.tag.lower()
            seen[tag] += 1
            here = "%s/%s[%d]" % (path, tag, seen[tag])
            try:
                words = kid.get_text(recursive=True, separator=" ") or ""
            except Exception:                           # noqa: BLE001
                words = ""
            out[here] = bool(words.strip())
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
        if tag.startswith("interactive"):
            captured[_canon(address.xpath)] = tag
        elif (tag.split(".")[0] in ("text", "media")
                and (leaf.value or "").strip()):
            labels.append(_canon(address.xpath))
    labels.sort()

    drawn = set()
    for chunk in chunks:
        for line in chunk.lines:
            if not line.text.strip():
                continue
            for address in (line.address,) + tuple(line.inline):
                if address is not None:
                    drawn.add(_canon(address.xpath))

    root = Node(_page_root(trie))
    reachable = {_canon(node.xpath) for node in root.acts()}
    shows_text = _text_by_xpath(dom) if dom is not None else {}

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
                    "empty", "collapsed"):
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
    out.append("  excused. Asking the fold instead excused 104 of 164 undrawn")
    out.append("  controls on 12 pages, because the tagger collapses an")
    out.append("  all-inline paragraph into one unit and skips its")
    out.append("  descendants -- so an anchor in prose had no text addressed")
    out.append("  at it while the page showed its words. That read 99.98%")
    out.append("  where the honest figure is 98.42%. The arbiter is the")
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
            record = dict(row)
            record["t"] = report.get("t")
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    return path
