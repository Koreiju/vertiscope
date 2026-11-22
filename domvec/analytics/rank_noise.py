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

**2. Queries -- what does the rank term change?** The same search three
times, only ``rank=`` varied (none / flat / hier): each mode's top 10 against
the rank-free one, and the depth of what the rank term promotes versus what
it pushes out. A rank term that carries depth promotes deeper chunks.

**3. Known items** (`known_item`): a heading as the query, its page as
the answer, per rank mode, with ``shuffle`` (flat ranks permuted) as null.

**4. Levels** (`/rank_levels`): the hierarchy's page, host and domain counts,
and the similarity level audited -- the mean dual similarity of the pairs its
edges link, against the PLANTED layout-distance edges and a random pairing.

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


CHUNK_URL: Dict[str, str] = {}
PAGE_LINKS: List[Tuple[str, str]] = []


def read_graph(base: str) -> Tuple[List[str], List[Tuple[str, str]], List[Tuple[str, str]]]:
    """(chunk cids, Contains edges parent->child, LinksTo edges chunk->first chunk of page).
    Also fills CHUNK_URL and PAGE_LINKS for the hierarchical arm."""
    cids = [r[0] for r in _paged(base, "MATCH (c:Chunk)", "c.cid", "c.cid")]
    contains = [(a, b) for a, b in _paged(base, "MATCH (a:Chunk)-[:Contains]->(b:Chunk)", "a.cid, b.cid", "a.cid, b.cid")]
    first: Dict[str, str] = {}
    for cid, url in _paged(base, "MATCH (p:Page)-[:HasChunk]->(c:Chunk)", "c.cid, c.url", "c.url, c.xpath"):
        first.setdefault(url, cid)
        CHUNK_URL[cid] = url
    links = []
    for cid, url in _paged(base, "MATCH (c:Chunk)-[:LinksTo]->(p:Page)", "c.cid, p.url", "c.cid, p.url"):
        if CHUNK_URL.get(cid):
            PAGE_LINKS.append((CHUNK_URL[cid], url))
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
    """Tie-aware (average ranks): depth has 7 values over 10,975 chunks, and
    an argsort tie-break would rank equal depths by row order."""
    return _spearman_avg(x, y)


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


def _hits(base: str, q: str, rank: str, window: int) -> List[dict]:
    url = base + "/search?q=" + urllib.parse.quote(q) + "&k=%d&rank=%s" % (window, rank)
    with urllib.request.urlopen(url, timeout=300) as r:
        return (json.load(r) or {}).get("hits") or []


def hier_structure(cids: Sequence[str], depth: Dict[str, int], children: Dict[str, int]) -> dict:
    """The hierarchical rank (url levels + links; the similarity level needs
    the vectors and is audited by `/rank_levels` instead) against depth."""
    from ..hierank import chunk_ranks, page_ranks
    pr = page_ranks(sorted({CHUNK_URL.get(c, "") for c in cids} - {""}), PAGE_LINKS)
    r = chunk_ranks([CHUNK_URL.get(c, "") for c in cids], pr).astype(float)
    d = np.array([depth.get(c, 0) for c in cids], dtype=float)
    leaf = np.array([children.get(c, 0) == 0 for c in cids])
    top = np.argsort(-r, kind="stable")[: max(1, len(cids) // 100)]
    return {"spearman_rank_depth": round(_spearman_avg(r, d), 3),
            "top1pct_leaf_share": round(float(leaf[top].mean()), 3),
            "rank_spread_max_over_min": round(float(r.max() / max(r.min(), 1e-12)), 2),
            "pages": len(pr)}


def _spearman_avg(x, y) -> float:
    """Spearman with tied values sharing their average rank -- the hier rank
    is constant within a page, and an argsort tie-break would invent order."""
    from scipy.stats import spearmanr
    v = spearmanr(x, y).statistic
    return 0.0 if v != v else float(v)


def queries(base: str, qs: Sequence[str], depth: Dict[str, int], window: int = 10) -> dict:
    """Per query: the SAME search -- same fusion, same content factor, same
    collapse -- with only the rank term varied: ``none`` (the counterfactual),
    ``flat`` (today's chunk-graph PageRank) and ``hier`` (`domvec.hierank`).

    The first version of this arm re-sorted one window by lexical x semantic
    against the live score, which also differs by fusion (additive, not the
    product) and by the content factor: three changes scored as one. Each
    mode is now its own full ranking, so the top 10s compared are exact.
    """
    per, moved = [], {"flat": ([], []), "hier": ([], [])}
    for q in qs:
        base_ids = [h["cid"] for h in _hits(base, q, "none", window)]
        if len(base_ids) < window:
            continue
        row = {"q": q}
        for mode in ("flat", "hier"):
            ids = [h["cid"] for h in _hits(base, q, mode, window)]
            a, b = set(ids), set(base_ids)
            row[mode + "_overlap"] = len(a & b)
            moved[mode][0].extend(depth.get(c, 0) for c in a - b)   # promoted by the rank term
            moved[mode][1].extend(depth.get(c, 0) for c in b - a)   # pushed out by it
        per.append(row)
    out = {"queries": len(per), "top": window, "per_query": per}
    for mode in ("flat", "hier"):
        ov = [p[mode + "_overlap"] for p in per]
        pro, dem = moved[mode]
        out[mode] = {"mean_overlap_with_none": round(float(np.mean(ov)), 2) if ov else None,
                     "promoted_mean_depth": round(float(np.mean(pro)), 2) if pro else None,
                     "demoted_mean_depth": round(float(np.mean(dem)), 2) if dem else None,
                     "promoted": len(pro)}
    return out


MODES = ("none", "flat", "hier", "levels", "shuffle")


def known_item(base: str, n: int = 150, k: int = 10, seed: int = 177) -> dict:
    """Known-item retrieval: a section heading as the query, the page that
    holds it as the answer. Page-level, because the coarse collapse may
    return a merge group's lead rather than the heading's own chunk.

    The query set: headings of 3+ words, each heading text appearing on ONE
    page only (a heading two pages share has two right answers), sampled
    with a fixed seed. ``shuffle`` is the null arm: the flat ranks permuted.
    A relevance proxy, not judgements -- a heading is lexically close to its
    own chunk, so this favours the lexical factor in every mode alike; the
    comparison is between rank modes, never an absolute quality claim."""
    from ..hierank import page_of
    rows = _paged(base, "MATCH (c:Chunk)", "c.cid, c.url, c.md", "c.cid")
    seen: Dict[str, set] = {}
    for cid, url, md in rows:
        for line in (md or "").splitlines():
            t = line.strip()
            if t.startswith("#"):
                text = t.lstrip("#").strip()
                if len(text.split()) >= 3 and len(text) < 90 and "](" not in text:
                    seen.setdefault(text, set()).add(page_of(url))
    items = sorted((t, next(iter(us))) for t, us in seen.items() if len(us) == 1)
    random.Random(seed).shuffle(items)
    items = items[:n]
    rr = {m: [] for m in MODES}               # reciprocal rank per item, paired across modes
    for text, url in items:
        for m in MODES:
            got = [page_of(h.get("url") or "") for h in _hits(base, text, m, k)]
            rr[m].append(1.0 / (got.index(url) + 1) if url in got else 0.0)
    out = {}
    rng = np.random.default_rng(seed)
    n_items = len(items)
    boot = rng.integers(0, max(n_items, 1), size=(2000, max(n_items, 1))) if n_items else None
    for m in MODES:
        v = np.array(rr[m])
        out[m] = {"page_at_1": int((v == 1.0).sum()), "page_at_k": int((v > 0).sum()),
                  "mrr": round(float(v.mean()), 3) if n_items else None}
        if m != "none" and n_items:
            # Paired: the same items under both modes, so the interval is on
            # the DIFFERENCE, not two overlapping marginal intervals.
            d = v - np.array(rr["none"])
            bs = d[boot].mean(axis=1)
            out[m]["mrr_minus_none"] = round(float(d.mean()), 4)
            out[m]["ci95"] = [round(float(np.percentile(bs, 2.5)), 4), round(float(np.percentile(bs, 97.5)), 4)]
            out[m]["items_better_worse"] = [int((d > 0).sum()), int((d < 0).sum())]
    return {"items": n_items, "k": k, "unique_headings_available": sum(1 for us in seen.values() if len(us) == 1),
            "by_mode": out}


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
            "hier_levels_and_links": hier_structure(cids, depth, children),
            "queries": queries(base, qs, depth),
            "known_item": known_item(base),
            "levels": _get(base, "/rank_levels")}


def _get(base: str, path: str) -> dict:
    try:
        with urllib.request.urlopen(base + path, timeout=600) as r:
            return json.load(r)
    except Exception as e:                          # noqa: BLE001
        return {"error": str(e)}


#: Queries drawn from what this corpus is about (its pages: tries, wikis,
#: museums, recipes); fixed so two runs are comparable.
QUERIES = ["patricia trie", "radix tree insertion", "shadow DOM", "museum collection", "recipe ingredients",
           "search results", "dead sea scrolls", "privacy policy", "sign in", "navigation menu",
           "wikipedia references", "honey harbour", "browser comparison", "javascript array", "file system api",
           "open source", "contact us", "news headlines", "music album", "pagination"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m domvec.analytics.rank_noise")
    ap.add_argument("--base", default="http://127.0.0.1:8795")
    ap.add_argument("--known", type=int, default=0,
                    help="run ONLY the known-item arm over this many headings (0: the full report)")
    args = ap.parse_args(argv)
    if args.known:
        got = known_item(args.base.rstrip("/"), n=args.known)
        Path("build_analytics").mkdir(exist_ok=True)
        Path("build_analytics/rank_noise_known.json").write_text(json.dumps(got, indent=1), encoding="utf-8")
        print(json.dumps(got, indent=1))
        return 0
    out = run(args.base.rstrip("/"), QUERIES)
    Path("build_analytics").mkdir(exist_ok=True)
    Path("build_analytics/rank_noise.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    slim = {k: v for k, v in out.items() if k != "queries"}
    slim["queries"] = {k: v for k, v in out["queries"].items() if k != "per_query"}
    if isinstance(out.get("levels"), dict):
        slim["levels"] = {k: v for k, v in out["levels"].items() if k != "multi_host_domains"}
    print(json.dumps(slim, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
