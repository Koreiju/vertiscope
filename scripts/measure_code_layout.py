"""G-241 (PLUGIN_GOAL 170): which layout serves the code property graph --
UMAP, force-directed, or the hybrid CODE_ARTIFACTS_DESIGN.md proposes --
decided by measurement, not argued.

Data from the running sidecar (`/cpg_vectors`, `/cpg`): every class and
function of `code://repo/`, the vector of the chunk holding its docstring
(`G-52`: only prose is embedded), and the CALLS / INHERITS / AST edges among
them.

Layouts (3D, the same nodes):
  umap    UMAP of the docstring vectors; a symbol with no docstring at its AST
          parent's point (a small offset)
  force   force-directed over the symbol graph (AST containment + CALLS +
          INHERITS as springs), no vectors at all
  hybrid  the proposal: UMAP points for documented symbols; an undocumented
          one at its AST parent's room; CALLS drawn, never a force -- so the
          positions are UMAP's, and the question is only what it costs the
          structure

Scores:
  semantic   k-NN recall@10 among documented symbols: of each one's 10
             nearest by cosine in embedding space, how many are among its 10
             nearest in the layout (1.0 = the layout keeps meaning's
             neighbourhoods)
  structure  median drawn length of the CALLS edges over the median
             distance between random symbol pairs (lower = calls drawn short,
             readable as structure)
  planted    the same structure score with the CALLS endpoints SHUFFLED --
             a layout must beat a structure it does not have, or its
             "structure" score measures nothing

    python scripts/measure_code_layout.py [prefix]
"""
import json
import random
import sys
import urllib.parse
import urllib.request

import networkx as nx
import numpy as np

SC = "http://127.0.0.1:8788"
prefix = sys.argv[1] if len(sys.argv) > 1 else "code://repo/"
get = lambda path: json.load(urllib.request.urlopen(SC + path, timeout=600))

data = get("/cpg_vectors?prefix=" + urllib.parse.quote(prefix, safe=""))
syms = data["symbols"]
idx = {s["key"]: i for i, s in enumerate(syms)}
urls = sorted({s["url"] for s in syms})
edges = {"CALLS": set(), "INHERITS": set(), "AST": set()}
parent = {}
for u in urls:
    g = get("/cpg?url=" + urllib.parse.quote(u, safe=""))
    for e in g["edges"]:
        a, b, k = e["src"], e["dst"], e["kind"]
        if k == "AST" and a in idx and b in idx:
            edges["AST"].add((a, b)); parent[b] = a
        elif k in ("CALLS", "INHERITS") and a in idx and b in idx and a != b:
            edges[k].add((a, b))
n = len(syms)
documented = [i for i, s in enumerate(syms) if s["vector"]]
V = np.array([syms[i]["vector"] for i in documented], dtype=np.float32)
print(json.dumps({"symbols": n, "documented": len(documented), "calls": len(edges["CALLS"]),
                  "inherits": len(edges["INHERITS"]), "ast": len(edges["AST"])}), flush=True)
rng = np.random.default_rng(0)


def place_undocumented(P, have):
    """A symbol without a docstring at its AST parent's point (or its
    parent's parent's...), offset a little; else at the centroid."""
    c = P[have].mean(axis=0)
    span = float(np.median(np.linalg.norm(P[have] - c, axis=1))) or 1.0
    for i in range(n):
        if have[i]:
            continue
        k = syms[i]["key"]; p = parent.get(k)
        while p is not None and not have[idx[p]]:
            p = parent.get(p)
        base = P[idx[p]] if p is not None else c
        P[i] = base + rng.normal(0, 0.03 * span, 3)
    return P


def umap_layout():
    import umap
    U = umap.UMAP(n_components=3, metric="cosine", random_state=0, n_neighbors=15, min_dist=0.1).fit_transform(V)
    P = np.zeros((n, 3)); have = np.zeros(n, bool)
    for j, i in enumerate(documented):
        P[i] = U[j]; have[i] = True
    return place_undocumented(P, have)


def force_layout():
    G = nx.Graph(); G.add_nodes_from(range(n))
    for k in ("AST", "CALLS", "INHERITS"):
        for a, b in edges[k]:
            G.add_edge(idx[a], idx[b])
    pos = nx.spring_layout(G, dim=3, seed=0, iterations=200)
    return np.array([pos[i] for i in range(n)])


def hybrid_layout(Pu):
    # UMAP's positions; the undocumented symbols already sit in their AST
    # parent's room (`place_undocumented`); CALLS move nothing.
    return Pu.copy()


def knn_recall(P, k=10):
    Vn = V / np.linalg.norm(V, axis=1, keepdims=True)
    S = Vn @ Vn.T
    np.fill_diagonal(S, -np.inf)
    Q = P[documented]
    D = np.linalg.norm(Q[:, None, :] - Q[None, :, :], axis=2)
    np.fill_diagonal(D, np.inf)
    rec = []
    for r in range(len(documented)):
        a = set(np.argsort(-S[r])[:k]); b = set(np.argsort(D[r])[:k])
        rec.append(len(a & b) / k)
    return round(float(np.mean(rec)), 3)


def structure(P, pairs):
    if not pairs:
        return None
    L = [np.linalg.norm(P[idx[a]] - P[idx[b]]) for a, b in pairs]
    R = [np.linalg.norm(P[i] - P[j]) for i, j in rng.integers(0, n, (4000, 2)) if i != j]
    return round(float(np.median(L) / np.median(R)), 3)


calls = sorted(edges["CALLS"])
keys = [s["key"] for s in syms]
shuffled = [(random.Random(1).choice(keys), random.Random(i + 7).choice(keys)) for i, _ in enumerate(calls)]
Pu = umap_layout()
layouts = {"umap": Pu, "force": force_layout(), "hybrid": hybrid_layout(Pu)}
for name, P in layouts.items():
    print(json.dumps({"layout": name, "semantic_knn_recall@10": knn_recall(P),
                      "calls_length_vs_random": structure(P, calls),
                      "planted_shuffled_calls": structure(P, shuffled)}), flush=True)
