"""What PageRank rewards in the three-form ranking (PLUGIN_GOAL 177 e).

The ranking is ``score = pagerank x tfidf_cos x nomic_cos`` (`search.py`), and
PageRank runs over the store's chunk graph (`GraphStore.edges`): `Contains`
edges parent -> child, plus `LinksTo` routed to a page's first chunk. The
reader's worry (177): "a poorly designed linking structure over the general
patricia trie" adds noise that impedes the dual embedding similarity.

Two questions, each with its arms (CLAUDE.md: every metric a non-vacuity arm):

**1. Structure -- what does a chunk's rank track?** Rank against containment
depth (Spearman), and the share of the top-1% rank mass held by leaves.
  * null arm: the same number of edges, rewired at random over the same
    nodes -- any depth effect must vanish;
  * planted arm: every `Contains` edge reversed (child -> parent) -- the
    depth relation must change sign. A measure that does not move under
    either is not measuring.

**2. Queries -- what does the rank factor change?** For each query, the
sidecar's top-``k`` window re-ordered by the dual embedding alone
(``lexical x semantic``) against the full product: overlap@10, and the depth
of what the rank factor promotes into the top 10 versus what it pushes out.
The window is the product's top-``window`` (candidates outside it cannot be
seen through the route), so overlap is an upper bound on agreement -- named
here so the number is not read as more than it is.

Reads the trie through the sidecar's read-only routes (`/cypher`, `/search`);
writes `build_analytics/rank_noise.json`. Changes nothing.
"""

from __future__ import annotations

import argparse
import json
import random
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import numpy as np

from ..vectors import pagerank

PAGE = 1000          # the /cypher route's row cap


def _post(base: str, query: str) -> List[list]:
    req = urllib.request.Request(base + "/cypher", data=json.dumps({"query": query}).encode(),
                                 headers={"content-type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        got = json.load(r)
    if got.get("error"):
        raise RuntimeError(got["error"])
    return got.get("rows") or []


def _paged(base: str, match: str, ret: str, order: str) -> List[list]:
    out, skip = [], 0
    while True:
        rows = _post(base, "%s RETURN %s ORDER BY %s SKIP %d LIMIT %d" % (match, ret, order, skip, PAGE))
        out += rows
        if len(rows) < PAGE:
            return out
        skip += PAGE


def read_graph(base: str) -> Tuple[List[str], List[Tuple[str, str]], List[Tuple[str, str]]]:
    """(chunk cids, Contains edges parent->child, LinksTo edges chunk->first chunk of page)."""
    cids = [r[0] for r in _paged(base, "MATCH (c:Chunk)", "c.cid", "c.cid")]
    contains = [(a, b) for a, b in _paged(base, "MATCH (a:Chunk)-[:Contains]->(b:Chunk)", "a.cid, b.cid", "a.cid, b.cid")]
    first: Dict[str, str] = {}
    for cid, url in _paged(base, "MATCH (p:Page)-[:HasChunk]->(c:Chunk)", "c.cid, c.url", "c.url, c.xpath"):
        first.setdefault(url, cid)
    links = []
    for cid, url in _paged(base, "MATCH (c:Chunk)-[:LinksTo]->(p:Page)", "c.cid, p.url", "c.cid, p.url"):
        t = first.get(url)
        if t and t != cid:
            links.append((cid, t))
    return cids, contains, links


def depths(cids: Sequence[str], contains: Sequence[Tuple[str, str]]) -> Dict[str, int]:
    """Containment depth: 0 for a chunk no chunk contains, parent + 1 below."""
    parent: Dict[str, str] = {}
    for a, b in contains:
        parent.setdefault(b, a)
    out: Dict[str, int] = {}

    def d(c: str) -> int:
        seen = []
        while c not in out and c in parent and c not in seen:
            seen.append(c)
            c = parent[c]
        base = out.get(c, 0)
        for k, x in enumerate(reversed(seen)):
            out[x] = base + k + 1
        out.setdefault(c, base)
        return out[seen[0]] if seen else base

    for c in cids:
        d(c)
    return out


def _spearman(x: Sequence[float], y: Sequence[float]) -> float:
    rx = np.argsort(np.argsort(x)).astype(float)
    ry = np.argsort(np.argsort(y)).astype(float)
    if rx.std() == 0 or ry.std() == 0:
        return 0.0
    return float(np.corrcoef(rx, ry)[0, 1])


def structure(cids: Sequence[str], edges: Sequence[Tuple[str, str]], depth: Dict[str, int],
              children: Dict[str, int]) -> dict:
    """What rank tracks over one edge set."""
    row = {c: i for i, c in enumerate(cids)}
    r = pagerank(len(cids), [(row[a], row[b]) for a, b in edges if a in row and b in row])
    d = np.array([depth.get(c, 0) for c in cids], dtype=float)
    leaf = np.array([children.get(c, 0) == 0 for c in cids])
    top = np.argsort(-r)[: max(1, len(cids) // 100)]
    by_depth = {}
    for k in sorted(set(d.astype(int)))[:8]:
        m = d == k
        by_depth[int(k)] = {"n": int(m.sum()), "mean_rank_x_n": round(float(r[m].mean() * len(cids)), 3)}
    return {"spearman_rank_depth": round(_spearman(r, d), 3),
            "top1pct_leaf_share": round(float(leaf[top].mean()), 3),
            "leaf_share_overall": round(float(leaf.mean()), 3),
            "rank_spread_max_over_min": round(float(r.max() / max(r.min(), 1e-12)), 1),
            "by_depth": by_depth}


def queries(base: str, qs: Sequence[str], depth: Dict[str, int], window: int = 50) -> dict:
    """Per query: what the rank factor changes inside the product's top-`window`."""
    per, promoted_d, demoted_d = [], [], []
    for q in qs:
        with urllib.request.urlopen(base + "/search?q=" + urllib.parse.quote(q) + "&k=%d" % window, timeout=300) as r:
            hits = (json.load(r) or {}).get("hits") or []
        if len(hits) < 10:
            continue
        full = [h["cid"] for h in hits]
        dual = [h["cid"] for h in sorted(hits, key=lambda h: -(float(h.get("lexical") or 0) * float(h.get("semantic") or 0)))]
        a, b = set(full[:10]), set(dual[:10])
        promoted = a - b              # in the top 10 only because of the rank factor
        demoted = b - a               # out of the top 10 only because of it
        promoted_d += [depth.get(c, 0) for c in promoted]
        demoted_d += [depth.get(c, 0) for c in demoted]
        per.append({"q": q, "overlap_at_10": len(a & b), "promoted": len(promoted)})
    ov = [p["overlap_at_10"] for p in per]
    return {"queries": len(per), "window": window,
            "mean_overlap_at_10": round(float(np.mean(ov)), 2) if ov else None,
            "promoted_mean_depth": round(float(np.mean(promoted_d)), 2) if promoted_d else None,
            "demoted_mean_depth": round(float(np.mean(demoted_d)), 2) if demoted_d else None,
            "per_query": per}


def run(base: str, qs: Sequence[str], seed: int = 7) -> dict:
    cids, contains, links = read_graph(base)
    depth = depths(cids, contains)
    children: Dict[str, int] = {}
    for a, _ in contains:
        children[a] = children.get(a, 0) + 1
    edges = contains + links
    rnd = random.Random(seed)
    null = [(rnd.choice(cids), rnd.choice(cids)) for _ in edges]
    planted = [(b, a) for a, b in contains] + links
    return {"graph": {"chunks": len(cids), "contains": len(contains), "links_to": len(links),
                      "max_depth": max(depth.values()) if depth else 0},
            "clean": structure(cids, edges, depth, children),
            "null_rewired": structure(cids, null, depth, children),
            "planted_reversed": structure(cids, planted, depth, children),
            "queries": queries(base, qs, depth)}


#: Queries drawn from what this corpus is about (its pages: tries, wikis,
#: museums, recipes); fixed so two runs are comparable.
QUERIES = ["patricia trie", "radix tree insertion", "shadow DOM", "museum collection", "recipe ingredients",
           "search results", "dead sea scrolls", "privacy policy", "sign in", "navigation menu",
           "wikipedia references", "honey harbour", "browser comparison", "javascript array", "file system api",
           "open source", "contact us", "news headlines", "music album", "pagination"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m domvec.analytics.rank_noise")
    ap.add_argument("--base", default="http://127.0.0.1:8795")
    args = ap.parse_args(argv)
    out = run(args.base.rstrip("/"), QUERIES)
    Path("build_analytics").mkdir(exist_ok=True)
    Path("build_analytics/rank_noise.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    slim = {k: v for k, v in out.items() if k != "queries"}
    slim["queries"] = {k: v for k, v in out["queries"].items() if k != "per_query"}
    print(json.dumps(slim, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
