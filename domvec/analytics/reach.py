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

``labelless``
    the fold holds no text and no media at or under the element, so there was
    never anything to draw. `<a name="chap01">` and `<a href="#section"></a>`
    are affordances the fold is right to record and a reader cannot be shown.

**`labelless` is a denominator, not a result.** Counting a label-less anchor
against the render is the mistake `affordance.py` documents at length, and it
dominates here: of 179 undrawn controls on 25 pages, 177 have no label
anywhere and 2 are real. Reported against every captured control the render
draws 98.66%; against the controls that could be drawn at all, 99.98%.

The test comes from the FOLD and not from the render, because "not a miss
because it was not drawn" is circular. It asks whether any text or media
value exists at or under the element -- a question the render has no part in.

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


def score_page(trie, chunks) -> dict:
    """One page's four counts, and the taxonomy labels behind each loss."""
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
            if any(_under(at, xpath) for at in labels):
                by_label[label]["undrawn"] += 1
                undrawn_tags[_leaf_tag(xpath)] += 1
            else:
                counts["labelless"] += 1
                by_label[label]["labelless"] += 1
        if not is_reach:
            by_label[label]["unreachable"] += 1

    return {
        "captured": counts["captured"],
        "drawn": counts["drawn"],
        "reachable": counts["reachable"],
        "markable": counts["markable"],
        "labelless": counts["labelless"],
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
            row.update(score_page(trie, render_trie(trie,
                                                    context_window=window)))
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
                    "labelless"):
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
    drawable = max(cap - total["labelless"], 1)
    out = ["", "  from a control in the page to a caller who can press it", ""]
    out.append("  pages                          %7d" % len(rows))
    out.append("  captured by the fold           %7d" % total["captured"])
    out.append("  of those, nothing to draw      %7d  (no text or media at "
               "or under it)" % total["labelless"])
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
               % ("taxonomy label", "captured", "undrawn", "labelless",
                  "unreachable"))
    for label, counts in sorted(by_label.items(),
                                key=lambda kv: -kv[1]["captured"]):
        out.append("  %-26s %9d %9d %10d %11d"
                   % (label, counts["captured"], counts["undrawn"],
                      counts["labelless"], counts["unreachable"]))
    if undrawn_tags:
        out.append("")
        out.append("  elements the render did not draw:")
        for tag, n in undrawn_tags.most_common(10):
            out.append("    %-16s %7d" % (tag or "(none)", n))
    out.append("")
    out.append("  `undrawn` is now the real losses only. A control with no")
    out.append("  text and no media at or under it -- `<a name=\'chap01\'>`,")
    out.append("  an empty permalink anchor -- could not have been drawn, and")
    out.append("  counting it against the render measures the corpus rather")
    out.append("  than the render. The test is asked of the FOLD, since")
    out.append("  \'not a miss because it was not drawn\' is circular.")
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
