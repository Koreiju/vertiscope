"""G-267 (PLUGIN_GOAL 184, 2026-10-18: "evaluate against obsidian, but each for
3D"): the 3D view's layout against Obsidian's graph layout, both in 3D, on
the same nodes.

Obsidian's graph view is a force simulation over the LINKS between notes --
springs on links, repulsion between all nodes, a pull to the centre -- with
no notion of what a note means. Run in 3D on this workspace's graph, its
links are the ones the store holds: a page to its chunks (HasChunk), a chunk
to the chunks it contains (Contains), a chunk to the pages it links
(LinksTo).

  ours      the projector's design: UMAP (3D, cosine) over the chunk vectors;
            each page at its chunks' centroid (G-106, G-245)
  obsidian  force-directed over those links (Fruchterman-Reingold, 3D --
            networkx `spring_layout`, Obsidian's model of springs + all-pairs
            repulsion + centring), no vectors
  hybrid    `obsidian` started FROM `ours` and relaxed a few steps: what links
            as springs do to a semantic layout

Scores (chunks only; distances in units of the layout's median pair distance):
  semantic   k-NN recall@10: of each chunk's 10 nearest by cosine, how many are
             among its 10 nearest in the layout -- does the layout keep meaning?
  structure  median drawn length of the link edges (lower = links read as
             structure); `planted` the same with the edges' ends shuffled --
             a layout must beat a structure it does not have
  pages      silhouette of chunks by page -- are pages kept apart?
  crowding   share of chunk pairs closer than 2% of the median pair distance
  ms         time to lay out

Reads a COPY of a store (never the live one, which the sidecar holds):

  python scripts/measure_layout_vs_obsidian.py <graph.kuzu copy> [pages=24] [max_chunks=150]
"""
import random, sys, time
sys.path.insert(0, r"<home>\Documents\vertiscope")
import numpy as np
import networkx as nx
from vertiscope.graphstore import GraphStore

path = sys.argv[1]
n_pages = int(sys.argv[2]) if len(sys.argv) > 2 else 24
max_chunks = int(sys.argv[3]) if len(sys.argv) > 3 else 150
rnd = random.Random(11)
g = GraphStore(path, read_only=True)

# Pages with 15..max_chunks embedded chunks, a spread of sites.
rows = g._rows("MATCH (p:Page)-[:HasChunk]->(c:Chunk) WHERE c.embedding IS NOT NULL "
               "RETURN p.url, count(c) AS n ORDER BY n DESC")
cand = [(u, n) for u, n in rows if 15 <= n <= max_chunks and not u.startswith(("code://", "vault://"))]
rnd.shuffle(cand)
seen_hosts, pages = set(), []
for u, n in cand:
    host = u.split("/")[2] if "//" in u else u
    if host in seen_hosts:
        continue
    seen_hosts.add(host); pages.append(u)
    if len(pages) >= n_pages:
        break
chunks = g._rows("MATCH (p:Page)-[:HasChunk]->(c:Chunk) WHERE list_contains($us, p.url) AND c.embedding IS NOT NULL "
                 "RETURN c.cid, p.url, c.embedding", {"us": pages})
cids = [r[0] for r in chunks]
page_of = {r[0]: r[1] for r in chunks}
X = np.array([r[2] for r in chunks], dtype=np.float32)
X /= np.linalg.norm(X, axis=1, keepdims=True) + 1e-9
idx = {c: i for i, c in enumerate(cids)}
cidset = set(cids)
contains = [(a, b) for a, b in g._rows("MATCH (a:Chunk)-[:Contains]->(b:Chunk) WHERE list_contains($cs, a.cid) "
                                       "RETURN a.cid, b.cid", {"cs": cids}) if b in cidset]
links = [(a, u) for a, u in g._rows("MATCH (a:Chunk)-[:LinksTo]->(p:Page) WHERE list_contains($cs, a.cid) AND list_contains($us, p.url) "
                                    "RETURN a.cid, p.url", {"cs": cids, "us": pages})]
g.close()
print("pages %d, chunks %d, Contains %d, LinksTo %d" % (len(pages), len(cids), len(contains), len(links)))

G = nx.Graph()
for u in pages:
    G.add_node("page:" + u)
for c in cids:
    G.add_edge("page:" + page_of[c], c)            # HasChunk
for a, b in contains:
    G.add_edge(a, b)
for a, u in links:
    G.add_edge(a, "page:" + u)
EDGES = [(a, b) for a, b in G.edges() if a in idx and b in idx] + \
        [(a, b) for a, b in G.edges() if (a in idx) != (b in idx)]


def ours():
    import umap
    t = time.perf_counter()
    P = umap.UMAP(n_components=3, metric="cosine", n_neighbors=15, min_dist=0.1, random_state=7).fit_transform(X)
    pos = {c: P[i] for i, c in enumerate(cids)}
    for u in pages:
        mine = [pos[c] for c in cids if page_of[c] == u]
        pos["page:" + u] = np.mean(mine, axis=0)
    return pos, (time.perf_counter() - t) * 1000


def obsidian(init=None, iterations=50):
    t = time.perf_counter()
    p0 = None if init is None else {k: np.asarray(v, dtype=float) for k, v in init.items()}
    pos = nx.spring_layout(G, dim=3, seed=7, pos=p0, iterations=iterations)
    return pos, (time.perf_counter() - t) * 1000


def scores(pos):
    P = np.array([pos[c] for c in cids], dtype=float)
    D = np.linalg.norm(P[:, None, :] - P[None, :, :], axis=2)
    iu = np.triu_indices(len(cids), 1)
    med = float(np.median(D[iu])) or 1.0
    S = X @ X.T
    k = 10
    rec = []
    for i in range(len(cids)):
        sem = set(np.argsort(-S[i])[1:k + 1]); lay = set(np.argsort(D[i])[1:k + 1])
        rec.append(len(sem & lay) / k)

    def elen(pairs):
        ls = [np.linalg.norm(np.asarray(pos[a]) - np.asarray(pos[b])) for a, b in pairs]
        return float(np.median(ls)) / med if ls else None
    nodes = list(pos)
    shuffled = [(rnd.choice(nodes), rnd.choice(nodes)) for _ in EDGES]
    from sklearn.metrics import silhouette_score
    labels = [pages.index(page_of[c]) for c in cids]
    return {"semantic_knn10": round(float(np.mean(rec)), 3), "structure": round(elen(EDGES), 3),
            "structure_planted": round(elen(shuffled), 3),
            "pages_silhouette": round(float(silhouette_score(P, labels)), 3),
            "crowding": round(float(np.mean(D[iu] < 0.02 * med)), 4)}


o, ms_o = ours()
f, ms_f = obsidian()
h, ms_h = obsidian(init=o, iterations=10)
for name, pos, ms in (("ours (UMAP, page at centroid)", o, ms_o), ("obsidian (force over links, 3D)", f, ms_f),
                      ("hybrid (force from UMAP, 10 steps)", h, ms_h)):
    print("%-36s %s ms=%d" % (name, scores(pos), ms))
