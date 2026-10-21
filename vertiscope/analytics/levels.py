"""R-K1: does every level of indentation in a chunk hold a line?

The bar, verbatim (PLUGIN_GOAL.md): *"headers and structures within markdown
structures are appropriately and most simply matched without things like
intermediated hierarchical fields when a singular path node of some form of
structure like that is rendered"*. Read as a property of a drawn chunk: a line
indented two steps under its parent leaves a level of whitespace with no line
on it -- a wrapper the page had and the reader cannot see. And a chunk whose
first line already sits indented spends levels on ancestors it does not hold.

Two counts per chunk, kept apart because they fail for different reasons:

* **gap** -- a line deeper than its parent line plus one. Its parent is the
  nearest preceding line drawn shallower.
* **lead** -- the chunk's shallowest line is not at the margin.

And the two properties a fix must not move, scored on the same chunks:

* **containment** -- element B inside element A on the page (A's xpath a
  prefix of B's), both drawn in one chunk, B drawn deeper than A;
* **depth rho** -- per chunk, the rank correlation of page depth (xpath steps)
  with drawn depth.

Rendered FRESH from the frozen corpus by the code under test, never read from a
store (a store records what some past renderer did). Two arms on the same
tries: the renderer as it is, and `markdown.PLANT_PAGE_LEVELS` -- the
page-wide compaction R-K1 was filed against.

    python -m vertiscope.analytics.levels [--pages N]
"""

from __future__ import annotations

import argparse
import json
import pathlib
import statistics
from typing import Dict, List, Optional, Sequence, Tuple

REPO = pathlib.Path(__file__).resolve().parents[2]
CORPUS = REPO / "tests" / "corpus"
OUT = REPO / "build_analytics" / "levels.json"


def gaps(depths: Sequence[int]) -> Tuple[int, int]:
    """(lines drawn under an empty level, the chunk's leading indent).

    A line's parent is the nearest preceding line drawn shallower; a line with
    none is a root and its parent depth is the chunk's own margin, -1.
    """
    if not depths:
        return 0, 0
    lead = min(depths)
    stack: List[int] = []
    under = 0
    for d in depths:
        while stack and stack[-1] >= d:
            stack.pop()
        parent = stack[-1] if stack else lead - 1
        if d - parent > 1:
            under += 1
        stack.append(d)
    return under, lead


def _spearman(pairs: Sequence[Tuple[int, int]]) -> Optional[float]:
    if len(pairs) < 3:
        return None

    def ranks(values):
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            for k in range(i, j + 1):
                out[order[k]] = (i + j) / 2.0 + 1
            i = j + 1
        return out

    xr, yr = ranks([a for a, _ in pairs]), ranks([b for _, b in pairs])
    mx, my = sum(xr) / len(xr), sum(yr) / len(yr)
    num = sum((a - mx) * (b - my) for a, b in zip(xr, yr))
    dx = sum((a - mx) ** 2 for a in xr) ** 0.5
    dy = sum((b - my) ** 2 for b in yr) ** 0.5
    return None if dx == 0 or dy == 0 else num / (dx * dy)


def _steps(xpath: str) -> int:
    return xpath.split("/text()")[0].count("/")


def score(chunks) -> Dict[str, float]:
    """The four figures over a list of rendered chunks."""
    n = with_gap = with_lead = under = 0
    c_ok = c_all = 0
    rhos: List[float] = []
    for chunk in chunks:
        if not chunk.lines:
            continue
        n += 1
        depths = [ln.depth for ln in chunk.lines]
        u, lead = gaps(depths)
        under += u
        with_gap += u > 0
        with_lead += lead > 0
        # One drawn depth per element: the shallowest line it drew.
        drawn: Dict[str, int] = {}
        for ln in chunk.lines:
            el = ln.address.xpath.split("/text()")[0]
            drawn[el] = min(drawn.get(el, ln.depth), ln.depth)
        els = sorted(drawn)
        for i, a in enumerate(els):
            for b in els[i + 1:]:
                if not b.startswith(a + "/"):
                    if b > a + "/￿":
                        break
                    continue
                c_all += 1
                c_ok += drawn[b] > drawn[a]
        rho = _spearman([(_steps(e), d) for e, d in drawn.items()])
        if rho is not None:
            rhos.append(rho)
    return {
        "chunks": n,
        "with_gap": with_gap, "with_gap_pct": round(100 * with_gap / n, 2) if n else 0.0,
        "lines_under_empty_level": under,
        "with_lead": with_lead, "with_lead_pct": round(100 * with_lead / n, 2) if n else 0.0,
        "containment": [c_ok, c_all],
        "containment_pct": round(100 * c_ok / c_all, 2) if c_all else None,
        "depth_rho_mean": round(statistics.mean(rhos), 4) if rhos else None,
    }


def _pages(limit: int):
    manifest = json.loads((CORPUS / "manifest.json").read_text())
    pages = [p for p in manifest["pages"] if p.get("ok")
             and (CORPUS / ("%s.html" % p["slug"])).exists()]
    return pages[:limit] if limit else pages


def run(limit: int = 0) -> Dict[str, Dict[str, float]]:
    from vertiscope import markdown
    from vertiscope.markdown import DEFAULT_CONTEXT_WINDOW, render_trie
    from vertiscope.pipeline import run_pipeline
    from vertiscope.trie import AddressTrie

    arms: Dict[str, list] = {"clean": [], "planted": []}
    for p in _pages(limit):
        html = (CORPUS / ("%s.html" % p["slug"])).read_text(encoding="utf-8", errors="replace")
        try:
            result = run_pipeline(html, p["url"], render=False)
        except Exception:
            continue
        trie = AddressTrie.from_tagged(result.tagged, p["url"])
        for arm, plant in (("clean", False), ("planted", True)):
            was = markdown.PLANT_PAGE_LEVELS
            markdown.PLANT_PAGE_LEVELS = plant
            try:
                arms[arm].extend(render_trie(trie, context_window=DEFAULT_CONTEXT_WINDOW))
            finally:
                markdown.PLANT_PAGE_LEVELS = was
    return {arm: score(chunks) for arm, chunks in arms.items()}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=0, help="0: every frozen page")
    args = ap.parse_args(argv)
    got = run(args.pages)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(got, indent=1))
    print(json.dumps(got, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
