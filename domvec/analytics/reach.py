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
    from ..live import _canon, _is_affordance, _page_root, Node

    captured: Dict[str, str] = {}
    for leaf in trie.leaves():
        address = leaf.address
        if address is None:
            continue
        if not (address.tag or "").startswith("interactive"):
            continue
        captured[_canon(address.xpath)] = address.tag

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
            by_label[label]["undrawn"] += 1
            undrawn_tags[_leaf_tag(xpath)] += 1
        if not is_reach:
            by_label[label]["unreachable"] += 1

    return {
        "captured": counts["captured"],
        "drawn": counts["drawn"],
        "reachable": counts["reachable"],
        "markable": counts["markable"],
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
        for key in ("captured", "drawn", "reachable", "markable"):
            total[key] += row.get(key, 0)
        for label, counts in (row.get("by_label") or {}).items():
            for key, n in counts.items():
                by_label[label][key] += n
        for tag, n in (row.get("undrawn_tags") or {}).items():
            undrawn_tags[tag] += n

    cap = total["captured"] or 1
    out = ["", "  from a control in the page to a caller who can press it", ""]
    out.append("  pages                          %7d" % len(rows))
    out.append("  captured by the fold           %7d" % total["captured"])
    for key, what in (("drawn", "drawn in the markdown"),
                      ("reachable", "reachable from acts()"),
                      ("markable", "markable by read()")):
        out.append("  %-30s %7d  (%.2f%%)"
                   % (what, total[key], 100.0 * total[key] / cap))
    out.append("")
    out.append("  %-26s %9s %9s %11s" % ("taxonomy label", "captured",
                                         "undrawn", "unreachable"))
    for label, counts in sorted(by_label.items(),
                                key=lambda kv: -kv[1]["captured"]):
        out.append("  %-26s %9d %9d %11d"
                   % (label, counts["captured"], counts["undrawn"],
                      counts["unreachable"]))
    if undrawn_tags:
        out.append("")
        out.append("  elements the render did not draw:")
        for tag, n in undrawn_tags.most_common(10):
            out.append("    %-16s %7d" % (tag or "(none)", n))
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
