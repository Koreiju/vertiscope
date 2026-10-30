"""Does a page still repeat itself INSIDE a chunk? -- `D-4`, `M-8`.

The verbatim: "full deduplication of repeat substrings that are essentially
structural redundancies of the web pages themselves"; the reading recorded
with it: "when a page repeats itself structurally, the chunk shows it once".
`markdown._fold_structural` folds three causes (punctuation cut off its text,
a link's own icon, a header's repeated control label). That was measured once,
by hand, on six pages (2026-10-11), and nothing was left that could measure it
again. This is that measurement, kept.

**What it counts.** A line that occurs more than once in its OWN chunk's
markdown (list markers and indentation stripped -- the same words at two depths
are the same words). Duplicate CHUNKS are `G-24`'s / `G-270`'s and are not
counted here.

**Two populations, because the row asks about one of them.** The rule the
fold was built under: data is never folded -- a table's "Yes" in every row is
the page's content, not its structure. So each repeat is classed:

* structural -- `punct` (no letters or digits), `image` (a picture alone),
  `icon_link` (a link around a picture alone), `label` (a short run of
  words with no digits: a control's repeated name, "Sort ascending");
* data -- `data` (digits, yes/no, a single symbol, a table row);
* `prose` -- a repeated sentence: the page saying the same thing twice.

The row is answerable for `structural` only. A `label` can be data too (a
column of "Active"), which is why the top lines are printed: the class is
a first cut, the reader of the report decides.

Reads the store through the sidecar's read-only `/cypher` (the sidecar holds
the writer lock); outside the REPL it measures (`CLAUDE.md` rule 3).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import urllib.request
from collections import Counter
from typing import Dict, Iterable, List, Tuple

_MARK = re.compile(r"^\s*(?:[-*+]\s+|\d+\.\s+|>\s*)*")
_IMAGE = re.compile(r"^!\[[^\]]*\]\([^)]*\)$")
_ICON_LINK = re.compile(r"^\[\s*!\[[^\]]*\]\([^)]*\)\s*\]\([^)]*\)$")
_YESNO = re.compile(r"^(yes|no|true|false|n/?a|none|\?|-|—|✓|✔|✗|×)$", re.I)


def norm(line: str) -> str:
    """A line as compared: markers and indentation off, inner space collapsed."""
    return re.sub(r"\s+", " ", _MARK.sub("", line)).strip()


def classify(line: str) -> str:
    t = norm(line)
    # Letters and digits of ANY script: an Arabic "أو" is a word, not punctuation.
    if not re.search(r"[^\W_]", t):
        return "punct"
    if _ICON_LINK.match(t):
        return "icon_link"
    if _IMAGE.match(t):
        return "image"
    if t.startswith("|") or re.search(r"\d", t) or _YESNO.match(t):
        return "data"
    words = re.findall(r"[^\W\d_][^\W\d_'’-]*", t)
    if len(words) <= 3 and len(t) <= 40:
        return "label"
    return "prose"


STRUCTURAL = ("punct", "image", "icon_link", "label")


def analyze(chunks: Iterable[Tuple[str, str, str]], top: int = 12) -> Dict:
    """`chunks`: (url, cid, markdown). Repeats within each chunk, by class."""
    lines_total = 0
    repeated = Counter()                  # class -> extra occurrences (beyond the first)
    tops: Dict[str, Counter] = {}
    chunks_n = 0
    pages = set()
    for url, _cid, md in chunks:
        chunks_n += 1
        pages.add(url)
        seen = Counter(norm(l) for l in (md or "").splitlines() if norm(l))
        lines_total += sum(seen.values())
        for text, n in seen.items():
            if n < 2:
                continue
            k = classify(text)
            repeated[k] += n - 1
            tops.setdefault(k, Counter())[text[:80]] += n - 1
    structural = sum(repeated[k] for k in STRUCTURAL)
    return {
        "pages": len(pages), "chunks": chunks_n, "lines": lines_total,
        "repeats": dict(repeated), "structural_repeats": structural,
        "structural_share_of_lines": round(structural / lines_total, 5) if lines_total else 0.0,
        "top": {k: tops[k].most_common(top) for k in tops},
    }


def _cypher(base: str, query: str) -> List[list]:
    req = urllib.request.Request(base.rstrip("/") + "/cypher", data=json.dumps({"query": query}).encode(),
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        got = json.load(r)
    if got.get("error"):
        raise RuntimeError(got["error"])
    return got.get("rows") or []


def from_sidecar(base: str, pages: int = 40) -> Iterable[Tuple[str, str, str]]:
    """The `pages` pages with the most chunks (web pages, not vault notes), their chunks."""
    urls = [r[0] for r in _cypher(base, "MATCH (c:Chunk) WHERE c.url STARTS WITH 'http' "
                                        "RETURN c.url, count(c) AS n ORDER BY n DESC LIMIT %d" % int(pages))]
    for u in urls:
        q = "MATCH (c:Chunk) WHERE c.url = '%s' RETURN c.url, c.cid, c.md LIMIT 1000" % u.replace("'", "\\'")
        for url, cid, md in _cypher(base, q):
            yield url, cid, md or ""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m domvec.analytics.repeats",
                                 description="In-chunk repetition by class (D-4 / M-8).")
    ap.add_argument("--sidecar", default="http://127.0.0.1:8788")
    ap.add_argument("--pages", type=int, default=40)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    rep = analyze(from_sidecar(a.sidecar, a.pages))
    if a.json:
        print(json.dumps(rep, indent=1, ensure_ascii=False))
        return 0
    print("%d pages, %d chunks, %d lines" % (rep["pages"], rep["chunks"], rep["lines"]))
    print("repeats by class:", rep["repeats"])
    print("structural: %d (%.3f%% of lines)" % (rep["structural_repeats"], 100 * rep["structural_share_of_lines"]))
    for k, rows in rep["top"].items():
        print("--", k)
        for text, n in rows:
            print("   %5d  %s" % (n, text))
    return 0


if __name__ == "__main__":
    sys.exit(main())
