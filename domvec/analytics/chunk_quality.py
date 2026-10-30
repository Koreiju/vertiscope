"""Does retrieval quality hold at the INTERACTIVE chunk level? -- `M-11`.

The row: "Quality holds at the interactive chunk level, because the chunk is
what gets embedded and its structure decides how representative the vectors
are." An interactive chunk -- links, controls, fields -- renders as much
machine address and bracket as words; if its vector is dominated by that, it
is retrieved worse than prose. So the question, asked the way a reader asks
it: given a span of a chunk's OWN words, does the app's search return that
chunk?

**Self-retrieval@k.** For a sample of chunks, a query is taken from the
chunk's own text as the encoder sees it (`tokens.for_model`: link targets
dropped, labels kept) -- its longest line of at least five words, its first
eight words -- and `/search` is asked. A hit is the chunk itself, or the
chunk that stands for it (`dup_of`, `group_of`: a copy is answered by its
lead). Reported for interactive chunks and for prose chunks separately; the
row holds when the interactive rate is close to the prose rate.

**Null arm** (`CLAUDE.md`): the same queries scored against a RANDOM chunk of
the same population -- it must come out near zero, or the measure is
crediting something other than the chunk.

Reads through the running sidecar (`/cypher`, `/search`); outside the REPL
it measures (`CLAUDE.md` rule 3).
"""

from __future__ import annotations

import argparse
import json
import random
import re
import sys
import urllib.parse
import urllib.request
from typing import Dict, List, Optional

from .. import tokens

_INTERACTIVE = re.compile(r"\]\(|^\s*(?:[-*]\s+)?\(\s.*\s\)\s*$|\[ \]", re.M)


def is_interactive(md: str) -> bool:
    """A chunk with a link, a control `( … )` or a field `[ ]` in it."""
    return bool(_INTERACTIVE.search(md or ""))


def query_of(md: str, words: int = 8) -> str:
    """The chunk's own words, as the encoder sees them: its longest line of
    five words or more (targets dropped), first `words` words of it."""
    text = tokens.for_model(md or "")
    best = ""
    for line in text.splitlines():
        line = re.sub(r"[#>*`|()\[\]]+", " ", line)
        ws = re.findall(r"[^\W_][^\s]*", line)
        if len(ws) >= 5 and len(" ".join(ws)) > len(best):
            best = " ".join(ws)
    return " ".join(best.split()[:words])


def _norm(t: str) -> str:
    return " ".join(re.findall(r"[^\W_][^\s]*", re.sub(r"[#>*`|()\[\]]+", " ", t or ""))).casefold()


def score(samples: List[Dict], search, k: int = 5, null_pool: Optional[List[str]] = None,
          rng: Optional[random.Random] = None, text_of=None) -> Dict:
    """`samples`: {cid, md, lead}; `search(q, k)` -> list of cids.

    Two rates. STRICT: the chunk (or its lead) came back. EQUIVALENT: a
    returned chunk holds the query's words verbatim (`text_of(cids)` -> their
    markdown) -- a tagline on fifty pages is answered correctly by any of
    them, and strict scoring counts that as the vector failing."""
    rng = rng or random.Random(0)
    asked = hit = equiv = null_hit = 0
    misses: List[Dict] = []
    for s in samples:
        q = query_of(s["md"])
        if not q:
            continue
        asked += 1
        got = search(q, k)
        want = {s["cid"], s.get("lead") or s["cid"]}
        if want & set(got):
            hit += 1
            equiv += 1
        else:
            nq = _norm(q)
            if text_of and nq and any(nq in _norm(tokens.for_model(md or "")) for md in text_of(got)):
                equiv += 1
            elif len(misses) < 5:
                misses.append({"cid": s["cid"], "q": q, "got": got[:3]})
        if null_pool:
            other = rng.choice(null_pool)
            if other not in want and other in got:
                null_hit += 1
    return {"asked": asked, "hit": hit, "recall": round(hit / asked, 3) if asked else None,
            "equivalent_recall": round(equiv / asked, 3) if asked else None,
            "null_recall": round(null_hit / asked, 3) if asked and null_pool else None, "misses": misses}


def _cypher(base: str, q: str) -> List[list]:
    req = urllib.request.Request(base.rstrip("/") + "/cypher", data=json.dumps({"query": q}).encode(),
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        got = json.load(r)
    if got.get("error"):
        raise RuntimeError(got["error"])
    return got.get("rows") or []


def _search(base: str):
    def go(q: str, k: int) -> List[str]:
        url = base.rstrip("/") + "/search?q=" + urllib.parse.quote(q) + "&k=" + str(int(k))
        with urllib.request.urlopen(url, timeout=300) as r:
            return [h.get("cid") for h in (json.load(r).get("hits") or [])]
    return go


def measure(base: str, n: int = 150, k: int = 5, seed: int = 0, exclude: str = "") -> Dict:
    rows = _cypher(base, "MATCH (c:Chunk) WHERE c.url STARTS WITH 'http' AND (c.dup_of IS NULL OR c.dup_of = '') "
                         "AND c.chars > 120 RETURN c.cid, c.md, c.group_of ORDER BY c.cid LIMIT 6000")
    if exclude:
        # A diagnostic, not the claim: drop chunks a stale render left a
        # known defect in (e.g. an id read as text), to see what remains.
        bad = re.compile(exclude)
        rows = [r for r in rows if not bad.search(r[1] or "")]
    rng = random.Random(seed)
    rng.shuffle(rows)
    inter = [{"cid": c, "md": m, "lead": g} for c, m, g in rows if is_interactive(m or "")][:n]
    prose = [{"cid": c, "md": m, "lead": g} for c, m, g in rows if not is_interactive(m or "")][:n]
    pool = [r[0] for r in rows]
    s = _search(base)

    def text_of(cids: List[str]) -> List[str]:
        ids = [c for c in cids if c]
        if not ids:
            return []
        q = "MATCH (c:Chunk) WHERE c.cid IN [%s] RETURN c.md" % ", ".join("'%s'" % c.replace("'", "") for c in ids)
        return [r[0] for r in _cypher(base, q)]
    out = {"k": k, "interactive": score(inter, s, k, pool, random.Random(seed + 1), text_of),
           "prose": score(prose, s, k, pool, random.Random(seed + 2), text_of)}
    i, p = out["interactive"]["recall"], out["prose"]["recall"]
    out["gap"] = round(p - i, 3) if i is not None and p is not None else None
    ie, pe = out["interactive"]["equivalent_recall"], out["prose"]["equivalent_recall"]
    out["equivalent_gap"] = round(pe - ie, 3) if ie is not None and pe is not None else None
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m domvec.analytics.chunk_quality",
                                 description="Self-retrieval@k, interactive vs prose chunks (M-11).")
    ap.add_argument("--sidecar", default="http://127.0.0.1:8788")
    ap.add_argument("--n", type=int, default=150)
    ap.add_argument("--k", type=int, default=5)
    ap.add_argument("--exclude", default="", help="regex: chunks matching it are left out (diagnostic)")
    a = ap.parse_args(argv)
    print(json.dumps(measure(a.sidecar, a.n, a.k, exclude=a.exclude), indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
