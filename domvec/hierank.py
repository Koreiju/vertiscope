"""Hierarchical PageRank over the trie's url levels (PLUGIN_GOAL 177 e, step 2).

What it replaces, measured (`domvec.analytics.rank_noise`, commit 3cbba5f):
PageRank ran over chunk -> chunk `Contains` edges (parent -> child) plus 31
cross-page links. Rank flowed DOWN the trie and pooled in leaves -- Spearman
+0.77 against nesting depth; +0.07 rewired at random; sign flipped with the
edges reversed. It was a depth score, and depth says nothing about a query.

**The levels.** The trie's key is ``url : xpath : ...``; the url itself is a
hierarchy, and the reader named its levels (177): the host, the registrable
domain, and the dual-embedding similarity. Each level is a NODE here and is
linked both ways -- a page up to its host and the host down to each of its
pages, the host up to its domain and back down. A walk can then leave a page
by its own hyperlinks, by climbing to its host or domain and descending to a
sibling, or by its similarity edges, and no direction is privileged by how
the trie happens to nest.

**The similarity level is computed from the two embeddings, never from a
layout.** Dual similarity of two pages = cos(their tf-idf centroids) x
cos(their semantic centroids): the frequency side and the semantic side, the
same two forms the ranking multiplies. A layout's spatial distance is a
projection of the semantic side alone (UMAP over the vectors), lossy by
design and blind to the frequency side; it is a picture of similarity, not
the similarity (177: "you also misinterpret our dual embedding similarity
with a layout cluster's spatial distances"). `dual_similar` takes the two
centroid matrices and nothing else, so a position cannot reach it.

**Within a page, every chunk carries its page's rank.** Containment is
structure, not endorsement: the dual embedding orders a page's chunks against
a query; the rank only says how central the PAGE is. A rank that varied with
nesting depth is exactly the noise being removed.

Patricia-trie terms: reads the trie's url prefixes (page, host, domain), its
`LinksTo` edges and the two embedding matrices; writes one rank per chunk row
into the index. Nothing is written to the trie.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Sequence, Tuple
from urllib.parse import urlsplit

import numpy as np

from .vectors import pagerank

#: Second-level labels under which a registrable domain takes three labels
#: (``bbc.co.uk``, ``abc.net.au``). No public-suffix list is installed, so
#: this is a stated approximation: a suffix missing here makes a domain one
#: label too short, which merges two registrants -- visible, not silent, in
#: `levels` output.
_SECOND_LEVEL = {"co", "com", "net", "org", "ac", "gov", "edu", "or", "ne", "go", "gob", "nic", "mil"}

#: Edge weights by level. Hyperlinks and the similarity level carry the
#: signal; the up/down links let rank flow across a host or domain.
W_LINK = 1.0
W_UP = 1.0
W_DOWN = 1.0
SIM_K = 5

#: Planted: the similarity level from the layout's page positions instead of
#: the two embeddings -- the confusion 177 names. `similarity_audit` must
#: report it as disagreeing with the dual similarity.
PLANT_LAYOUT_SIMILARITY = [False]


def host_of(url: str) -> str:
    """The host level: ``en.wikipedia.org``. A scheme with no network
    location (``vault://``, ``code://``) is its own host -- ``vault:`` -- so
    vault notes climb to one shared node rather than each to nothing."""
    try:
        p = urlsplit(url)
    except ValueError:
        return ""
    host = (p.hostname or "").lower()
    if p.scheme in ("http", "https") and host:
        return host
    return (p.scheme or "") + ":" + (host if p.scheme not in ("vault", "code", "tool") else "")


def registrable(host: str) -> str:
    """The registrable domain: ``en.wikipedia.org`` -> ``wikipedia.org``,
    ``www.bbc.co.uk`` -> ``bbc.co.uk``. A non-web host is its own domain."""
    if ":" in host or not host or host.replace(".", "").isdigit():
        return host
    labels = host.split(".")
    if len(labels) <= 2:
        return host
    # Under a country code, a listed second level (``co.uk``) or any
    # two-letter one (``on.ca``, a province: live, 2026-11-22, the first run
    # merged every Ontario host into one "on.ca" domain) is suffix.
    if len(labels[-1]) == 2 and (labels[-2] in _SECOND_LEVEL or len(labels[-2]) == 2):
        return ".".join(labels[-3:])
    return ".".join(labels[-2:])


def dual_similar(urls: Sequence[str], lexical_cent: np.ndarray, semantic_cent: np.ndarray,
                 k: int = SIM_K) -> List[Tuple[str, str, float]]:
    """Each page's ``k`` nearest pages by dual similarity, as weighted edges.

    Both centroid matrices are row-aligned with ``urls`` and L2-normalised;
    the similarity is the PRODUCT of the two cosines (each clipped at 0), so
    a pair must agree on vocabulary AND on meaning to be linked."""
    n = len(urls)
    if n < 2:
        return []
    lex = np.clip(np.asarray(lexical_cent @ lexical_cent.T, dtype=np.float64), 0.0, None)
    sem = np.clip(np.asarray(semantic_cent @ semantic_cent.T, dtype=np.float64), 0.0, None)
    return _knn(urls, lex * sem, k)


def layout_similar(urls: Sequence[str], positions: np.ndarray, k: int = SIM_K) -> List[Tuple[str, str, float]]:
    """The PLANTED similarity: nearness in a layout. Exists only so the audit
    has the confusion to catch."""
    pos = np.asarray(positions, dtype=np.float64)
    d = np.sqrt(((pos[:, None, :] - pos[None, :, :]) ** 2).sum(-1))
    return _knn(urls, 1.0 / (1.0 + d), k)


def _knn(urls, sim: np.ndarray, k: int) -> List[Tuple[str, str, float]]:
    sim = sim.copy()
    np.fill_diagonal(sim, -np.inf)
    out = []
    for i in range(len(urls)):
        for j in np.argsort(-sim[i])[:k]:
            w = float(sim[i, j])
            if w > 0 and np.isfinite(w):
                out.append((urls[i], urls[int(j)], w))
    return out


def similarity_audit(urls: Sequence[str], lexical_cent: np.ndarray, semantic_cent: np.ndarray,
                     edges: Iterable[Tuple[str, str, float]]) -> Dict[str, float]:
    """How much of the dual similarity an edge set captures: the mean dual
    similarity of the pairs it links, against the best ``k``-NN could do
    (the dual edges themselves) and a random pairing. The planted layout
    edges must land well below the dual ones -- otherwise the audit cannot
    tell the two sources apart."""
    idx = {u: i for i, u in enumerate(urls)}
    lex = np.clip(lexical_cent @ lexical_cent.T, 0.0, None)
    sem = np.clip(semantic_cent @ semantic_cent.T, 0.0, None)
    dual = lex * sem
    got = [float(dual[idx[a], idx[b]]) for a, b, _ in edges if a in idx and b in idx]
    n = len(urls)
    off = dual[~np.eye(n, dtype=bool)] if n > 1 else np.zeros(1)
    return {"edges": len(got), "mean_dual": round(float(np.mean(got)), 4) if got else 0.0,
            "random_pair_mean_dual": round(float(off.mean()), 4)}


def page_of(url: str) -> str:
    """The page a url's chunks belong to: a kept version (G-253,
    ``url#~v``) is its page's past, not a page of its own. Uncollapsed, the
    live store had 59 such pseudo-pages (2,358 chunks) hanging off real
    hosts with no links, each diluting its host's rank."""
    from .graphstore import VERSION_SUFFIX
    if PLANT_VERSIONS_AS_PAGES[0]:
        return url
    return url[: -len(VERSION_SUFFIX)] if url.endswith(VERSION_SUFFIX) else url


#: Planted: versions as pages of their own, as the first live run had them.
PLANT_VERSIONS_AS_PAGES = [False]


def levels(urls: Iterable[str]) -> Dict[str, Tuple[str, str]]:
    """url -> (host, registrable domain)."""
    out = {}
    for u in urls:
        h = host_of(u)
        out[u] = (h, registrable(h))
    return out


def page_ranks(urls: Sequence[str], page_links: Iterable[Tuple[str, str]],
               similar: Iterable[Tuple[str, str, float]] = (), *, damping: float = 0.85
               ) -> Dict[str, float]:
    """PageRank over page, host and domain nodes; returns each PAGE's rank,
    scaled so the pages' mean is 1."""
    pages = list(dict.fromkeys(page_of(u) for u in urls if u))
    lv = levels(pages)
    nodes: Dict[str, int] = {}

    def node(key: str) -> int:
        if key not in nodes:
            nodes[key] = len(nodes)
        return nodes[key]

    for u in pages:
        node("p:" + u)
    src, dst, w = [], [], []

    def edge(a: str, b: str, weight: float) -> None:
        src.append(node(a)); dst.append(node(b)); w.append(weight)

    for u in pages:
        host, dom = lv[u]
        if host:
            edge("p:" + u, "h:" + host, W_UP)
            edge("h:" + host, "p:" + u, W_DOWN)
    for host, dom in {v for v in lv.values() if v[0]}:
        if dom and dom != host:
            edge("h:" + host, "d:" + dom, W_UP)
            edge("d:" + dom, "h:" + host, W_DOWN)
    known = set(pages)
    for a, b in page_links:
        a, b = page_of(a), page_of(b)
        if a in known and b in known and a != b:
            edge("p:" + a, "p:" + b, W_LINK)
    for a, b, s in similar:
        a, b = page_of(a), page_of(b)
        if a in known and b in known and a != b and s > 0:
            edge("p:" + a, "p:" + b, float(s))
    r = pagerank(len(nodes), list(zip(src, dst)), weights=w, damping=damping)
    vals = np.array([r[nodes["p:" + u]] for u in pages], dtype=np.float64)
    mean = float(vals.mean()) if vals.size else 1.0
    return {u: float(v / mean) if mean > 0 else 1.0 for u, v in zip(pages, vals)}


def chunk_ranks(row_urls: Sequence[str], page_rank: Dict[str, float]) -> np.ndarray:
    """One rank per chunk row: its page's. A row with no page takes the mean
    (1.0) -- a zero would veto it under the product fusion."""
    return np.array([page_rank.get(page_of(u), 1.0) if u else 1.0 for u in row_urls], dtype=np.float32)
