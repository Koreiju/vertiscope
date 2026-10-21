"""How much of a page's STRUCTURE survives into a chunk.

Every measurement in this repo so far has been about content: which addresses
were kept, how many controls were lost, how full the window is. None of them
asks the question the goal actually poses -- whether the distilled artifact
"reflects how it is supposed to be presented on a regular webpage", boxes and
nesting included.

That question has an answer here that it does not have anywhere else, because
a chunk carries the ABSOLUTE XPATH of every line, and the frozen corpus holds
the page those xpaths point into. So the original subtree can be fetched and
the two structures compared directly, rather than by eye.

Four things are compared, and they are separated on purpose because they fail
independently:

* **Reach** -- of the elements under a chunk's root that a reader would see,
  how many does the chunk address at all? A chunk that drops half a card is
  lossy however well the rest nests.
* **Order** -- do the addressed elements appear in document order? Reading
  order is the one structural property a reader notices immediately.
* **Depth agreement** -- the distilled tree indents by nesting LEVEL after
  `_level_page` collapses single-child chains, so it should not match the
  page's raw depth. What it should preserve is the *relation*: two elements
  the page nested at different depths should stay at different depths, and
  siblings should stay siblings. Measured as the rank correlation between
  page depth and distilled depth.
* **Containment** -- if element B is inside element A on the page, is B still
  inside A in the distilled tree? This is the property the goal is really
  asking about: a card's picture and its price belong together, and the
  distilled form should say so.

Run:

    python scripts/structural_fidelity.py --workspace build/vaultws512
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
import statistics
import sys
from collections import Counter
from html.parser import HTMLParser
from typing import Dict, List, Optional, Tuple

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

CORPUS = REPO / "tests" / "corpus"

#: Elements a reader never sees. Reach must not be scored against them, or a
#: page with a big `<head>` scores badly for distilling exactly what it should.
_INVISIBLE = {"script", "style", "head", "meta", "link", "title", "noscript",
              "template", "svg", "path", "defs", "g", "use", "symbol"}

#: Elements that carry no content of their own -- pure layout. A distiller
#: that drops them is doing its job, so they are excluded from reach too.
_WRAPPERS = {"div", "span", "section", "article", "main", "aside", "nav",
             "header", "footer", "figure", "picture", "form", "ul", "ol",
             "table", "tbody", "thead", "tr", "label", "center", "font",
             "b", "i", "em", "strong", "small", "abbr", "time", "br", "hr"}


class _Tree(HTMLParser):
    """Absolute xpaths for every element, the way `AddressTrie` spells them.

    Written here rather than reused from the pipeline on purpose: if the
    comparison used the pipeline's own walk, it would be checking the
    distiller against itself. This is an independent reading of the same
    file.
    """

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.stack: List[Tuple[str, Counter]] = []
        self.paths: Dict[str, dict] = {}
        self._text: Dict[str, List[str]] = {}

    # `<img>` and friends never close; without this every later element
    # nests inside them and the depths are nonsense.
    _VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input",
             "link", "meta", "param", "source", "track", "wbr"}

    def _path(self) -> str:
        return "/" + "/".join(seg for seg, _ in self.stack)

    def handle_starttag(self, tag, attrs):
        counts = self.stack[-1][1] if self.stack else self._root_counts()
        counts[tag] += 1
        n = counts[tag]
        seg = tag if n == 1 and self._only_child(tag, counts) else "%s[%d]" % (tag, n)
        self.stack.append((seg, Counter()))
        path = self._path()
        self.paths[path] = {"tag": tag, "depth": len(self.stack),
                            "order": len(self.paths)}
        if tag in self._VOID:
            self.stack.pop()

    def _root_counts(self):
        if not hasattr(self, "_roots"):
            self._roots = Counter()
        return self._roots

    @staticmethod
    def _only_child(tag, counts):
        # An index is written whenever a sibling of the same tag exists, which
        # is decided after the fact; both spellings are recorded so a lookup
        # cannot miss on the bracket.
        return False

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, -1, -1):
            if self.stack[i][0].split("[")[0] == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        if data.strip() and self.stack:
            self._text.setdefault(self._path(), []).append(data.strip())


def _page_tree(html: str) -> Dict[str, dict]:
    parser = _Tree()
    try:
        parser.feed(html)
    except Exception:                                   # noqa: BLE001
        pass
    for path, texts in parser._text.items():
        if path in parser.paths:
            parser.paths[path]["text"] = " ".join(texts)[:200]
    return parser.paths


def _canon(xpath: str) -> str:
    """One spelling for one element, so two walks can be compared.

    `AddressTrie` omits the index when an element is the only one of its tag
    among its siblings; the parser in this file always writes one. So `div`
    and `div[1]` are the same element under two spellings, and the comparison
    has to see that.

    ONLY `[1]` is dropped. An earlier version of this dropped EVERY index --
    "the shape, not the position" -- and that is wrong in a way that quietly
    invents a result: `div[1]/div[1]` and `div[3]/div` both flatten to
    `div/div`, so a chunk rooted at one branch collected the visible elements
    of every sibling branch on the page. The chunk then appeared to have
    dropped them, and reach came out at 16.5% when the elements were never
    under that root at all.
    """
    return re.sub(r"\[1\](?=/|$)", "", xpath or "")


def _shape(xpath: str) -> str:
    """An xpath with every index dropped -- the shape, not the position.

    Kept for the index-agnostic question, where flattening is the POINT.
    Never for locating an element.
    """
    return re.sub(r"\[\d+\]", "", xpath or "")


def _under(paths: Dict[str, dict], root: str) -> Dict[str, dict]:
    root_n = _canon(root)
    return {p: v for p, v in paths.items()
            if _canon(p) == root_n or _canon(p).startswith(root_n + "/")}


def _visible_content(paths: Dict[str, dict]) -> Dict[str, dict]:
    return {p: v for p, v in paths.items()
            if v["tag"] not in _INVISIBLE
            and v["tag"] not in _WRAPPERS
            and v.get("text")}


def _spearman(pairs: List[Tuple[int, int]]) -> Optional[float]:
    """Rank correlation, without scipy.

    Ranks rather than values because the two depths are not meant to be
    equal: `_level_page` collapses single-child chains deliberately, so a
    page depth of 11 becoming a distilled depth of 2 is correct. What has to
    survive is the ORDER of the depths.
    """
    n = len(pairs)
    if n < 3:
        return None

    def ranks(values):
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            mean = (i + j) / 2.0 + 1
            for k in range(i, j + 1):
                out[order[k]] = mean
            i = j + 1
        return out

    xr = ranks([a for a, _ in pairs])
    yr = ranks([b for _, b in pairs])
    mx, my = sum(xr) / n, sum(yr) / n
    num = sum((a - mx) * (b - my) for a, b in zip(xr, yr))
    dx = sum((a - mx) ** 2 for a in xr) ** 0.5
    dy = sum((b - my) ** 2 for b in yr) ** 0.5
    return None if dx == 0 or dy == 0 else num / (dx * dy)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workspace", type=pathlib.Path, required=True)
    ap.add_argument("--pages", type=int, default=8)
    ap.add_argument("--chunks-per-page", type=int, default=25)
    args = ap.parse_args(argv)

    from vertiscope.obsidian.sidecar import chunk_payload
    from vertiscope.workspace import Workspace

    manifest = json.loads((CORPUS / "manifest.json").read_text())
    by_url = {p["url"]: p["slug"] for p in manifest["pages"] if p.get("ok")}

    reach, order_ok, order_all = [], 0, 0
    depth_rho, containment_ok, containment_all = [], 0, 0
    per_page = []

    with Workspace(args.workspace) as ws:
        urls = [u for u in ws.pages() if u in by_url][:args.pages]
        for url in urls:
            path = CORPUS / ("%s.html" % by_url[url])
            if not path.exists():
                continue
            html = path.read_text(encoding="utf-8", errors="replace")
            paths = _page_tree(html)

            page_reach, page_rho = [], []
            chunks = [c for c in ws.store.chunks(url)][:args.chunks_per_page]
            for chunk in chunks:
                payload = chunk_payload(ws, chunk.cid)
                if not payload or not payload["lines"]:
                    continue
                addressed = []
                for line in payload["lines"]:
                    key = str(line.get("key") or "")
                    parts = key.split("|")
                    if len(parts) > 1:
                        addressed.append(parts[1].split("/text()")[0])

                subtree = _under(paths, chunk.xpath)
                want = _visible_content(subtree)
                if not want:
                    continue

                got = {p for p in want
                       if any(_canon(a) == _canon(p)
                              or _canon(a).startswith(_canon(p) + "/")
                              for a in addressed)}
                page_reach.append(len(got) / len(want))

                # Order: are the addressed elements in document order?
                seen = [want[p]["order"] for p in sorted(
                    got, key=lambda p: [want[q]["order"] for q in [p]][0])]
                positions = []
                for a in addressed:
                    for p, v in want.items():
                        if _canon(a) == _canon(p):
                            positions.append(v["order"])
                            break
                order_all += 1
                if positions == sorted(positions):
                    order_ok += 1

                # Depth: rank correlation between page depth and drawn depth.
                pairs = []
                for i, line in enumerate(payload["lines"]):
                    key = str(line.get("key") or "")
                    parts = key.split("|")
                    if len(parts) < 2:
                        continue
                    el = parts[1].split("/text()")[0]
                    hit = next((v for p, v in subtree.items()
                                if _canon(p) == _canon(el)), None)
                    if hit is None:
                        continue
                    text = line["text"]
                    drawn = (len(text) - len(text.lstrip(" "))) // 2
                    pairs.append((hit["depth"], drawn))
                rho = _spearman(pairs)
                if rho is not None:
                    page_rho.append(rho)

                # Containment: if B is inside A on the page, is B still drawn
                # deeper than A?
                els = [(parts[1].split("/text()")[0], i)
                       for i, line in enumerate(payload["lines"])
                       for parts in [str(line.get("key") or "").split("|")]
                       if len(parts) > 1]
                drawn_depth = {}
                for el, i in els:
                    text = payload["lines"][i]["text"]
                    drawn_depth[_canon(el)] = (
                        len(text) - len(text.lstrip(" "))) // 2
                names = list(drawn_depth)
                for a in names:
                    for b in names:
                        if a == b or not b.startswith(a + "/"):
                            continue
                        containment_all += 1
                        if drawn_depth[b] > drawn_depth[a]:
                            containment_ok += 1

            if page_reach:
                per_page.append((by_url[url], len(chunks),
                                 statistics.mean(page_reach),
                                 statistics.mean(page_rho) if page_rho else None))
                reach.extend(page_reach)
                depth_rho.extend(page_rho)

    print("structural fidelity of the distilled chunks against the source pages")
    print("=" * 74)
    print("%-34s %6s %8s %8s" % ("page", "chunks", "reach", "depth rho"))
    for slug, n, r, rho in per_page:
        print("%-34s %6d %7.1f%% %8s"
              % (slug[:34], n, 100 * r, "-" if rho is None else "%.2f" % rho))
    print("-" * 74)
    if reach:
        print("reach          median %.1f%%   mean %.1f%%   (visible, non-wrapper "
              "elements under the chunk root that the chunk addresses)"
              % (100 * statistics.median(reach), 100 * statistics.mean(reach)))
    if depth_rho:
        print("depth rho      median %.2f    mean %.2f   (page nesting order vs "
              "drawn nesting order)"
              % (statistics.median(depth_rho), statistics.mean(depth_rho)))
    if order_all:
        print("reading order  %d of %d chunks in document order (%.1f%%)"
              % (order_ok, order_all, 100 * order_ok / order_all))
    if containment_all:
        print("containment    %d of %d ancestor pairs still nested (%.1f%%)"
              % (containment_ok, containment_all,
                 100 * containment_ok / containment_all))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
