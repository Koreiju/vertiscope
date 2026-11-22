"""Why the 3D layout is a long stick, and what would open it up (2026-11-22).

The user: "Why are our UMAP clusters so long and clumpy? is it perplexity or
another parameter? For more widely varied web content that is more
self-similar and uniform, how could we see more of the detail being clumped
together? Making more of the 3D aspect and less linear?"

Measured live first (the drawn graph, 6,132 nodes): principal spreads
5201 : 653 : 245 between the 10th and 90th percentiles -- a robust aspect of
21 : 1. This asks, of the store's own vectors, which stage of the pipeline
makes that shape, by running the pipeline's stages with one thing changed per
arm:

* `shipped`    -- what the projector does: unit rows, TruncatedSVD WITHOUT
                  centering (`layout._reduce`, the projector's `svd_f`), unit
                  rows, UMAP(n_neighbors=15, min_dist=0.25).
* `centered`   -- the same with the mean subtracted before the SVD.
* `abtt`       -- centered, and the top 2 principal directions removed
                  ("all-but-the-top": encoder vectors share a few dominant
                  directions, strongest on self-similar text).
* `local`      -- `abtt` with n_neighbors=8, min_dist=0.05: local detail.
* `densmap`    -- `abtt` with UMAP's densMAP, which keeps local density.

Scored per arm, at the PAGE level (page means, as the default view is fitted)
and the CHUNK level (a sample):

* `aspect`     -- robust (p10..p90) spread along the 3 principal axes of the
                  3D output, longest over shortest. 1 is a ball, 21 the stick.
* `kept10`     -- share of each point's 10 nearest neighbours in the INPUT
                  (cosine over the encoder's vectors, before any reduction)
                  that are among its 10 nearest in 3D. Denominator: every
                  point. Detail a reader can see is detail kept here.
* `svd1_share` -- energy of the first SVD component of the rows the arm feeds
                  UMAP: the "one shared direction" the uncentered SVD keeps.

Arms that can fail (a check that cannot fail is not measuring):

* `planted_stick` -- a synthetic line in 3D: aspect must read high.
* `planted_ball`  -- isotropic points: aspect must read near 1.
* `null_random`   -- the input's points at random 3D positions: kept10 ~ 10/N.

UMAP here is umap-learn on the CPU, not the projector's parametric net; the
preprocessing under test is shared by both, and the report says which ran.

Run::

    python -m domvec.analytics.layout_shape --workspace .domvec/workspaces/project-noumen

Writes `build_analytics/layout_shape.json`.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np

ARMS = ("shipped", "centered", "abtt", "local", "densmap")


def _unit(m: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(m, axis=1, keepdims=True)
    n[n == 0] = 1.0
    return m / n


def aspect(Y: np.ndarray) -> Dict[str, object]:
    """Robust spreads along the principal axes of a 3D cloud, longest first."""
    Y = np.asarray(Y, dtype=np.float64)[:, :3]
    c = Y - Y.mean(axis=0)
    _vals, vecs = np.linalg.eigh(np.cov(c.T))
    proj = c @ vecs
    spread = sorted((float(np.percentile(proj[:, k], 90) - np.percentile(proj[:, k], 10)) for k in range(3)), reverse=True)
    return {"spreads": [round(s, 3) for s in spread], "aspect": round(spread[0] / max(spread[2], 1e-12), 2)}


def kept10(X: np.ndarray, Y: np.ndarray, k: int = 10) -> float:
    """Share of input-space (cosine) 10-NN kept among the 3D 10-NN."""
    Xu = _unit(np.asarray(X, dtype=np.float32))
    S = Xu @ Xu.T
    np.fill_diagonal(S, -np.inf)
    nin = np.argsort(-S, axis=1)[:, :k]
    Y = np.asarray(Y, dtype=np.float32)[:, :3]
    D = ((Y[:, None, :] - Y[None, :, :]) ** 2).sum(-1)
    np.fill_diagonal(D, np.inf)
    nout = np.argsort(D, axis=1)[:, :k]
    return round(float(np.mean([len(set(a) & set(b)) / k for a, b in zip(nin, nout)])), 4)


def prepare(X: np.ndarray, arm: str, width: int, seed: int) -> np.ndarray:
    from sklearn.decomposition import TruncatedSVD
    Z = _unit(np.asarray(X, dtype=np.float32))
    if arm != "shipped":
        Z = Z - Z.mean(axis=0)
    if arm in ("abtt", "local", "densmap"):
        # all-but-the-top: the 2 dominant directions out
        _u, _s, vt = np.linalg.svd(Z, full_matrices=False)
        top = vt[:2]
        Z = Z - (Z @ top.T) @ top
    k = int(min(width, Z.shape[0] - 1, Z.shape[1] - 1))
    if Z.shape[1] > width and k >= 2:
        Z = TruncatedSVD(n_components=k, random_state=seed).fit_transform(Z)
    return _unit(Z)


def svd1_share(Z: np.ndarray) -> float:
    s = np.linalg.svd(np.asarray(Z, dtype=np.float64), compute_uv=False)
    return round(float(s[0] ** 2 / (s ** 2).sum()), 4)


def embed(Z: np.ndarray, arm: str, seed: int) -> np.ndarray:
    import umap
    n = Z.shape[0]
    nn = 8 if arm == "local" else 15
    md = 0.05 if arm == "local" else 0.25
    kw = {"densmap": True} if arm == "densmap" else {}
    r = umap.UMAP(n_components=3, n_neighbors=int(max(2, min(nn, n - 1))), min_dist=md, random_state=seed, **kw)
    return np.asarray(r.fit_transform(Z), dtype=np.float32)


def pumap_arm(X: np.ndarray, debias, seed: int, steps: int = 4000) -> np.ndarray:
    """The projector's own model on unit rows, as it is fitted live (no SVD)."""
    from ..obsidian.pumap import ParametricUMAP, Whitened
    m = ParametricUMAP(n_components=6, n_neighbors=int(max(2, min(15, len(X) - 1))), min_dist=0.25,
                       seed=seed, debias=debias)
    raw = np.asarray(m.fit(_unit(X), max_steps=steps).embedding_, dtype=np.float32)
    return Whitened(m, dims=3).fit_whitening(raw)


def level(X: np.ndarray, name: str, seed: int, width: int, parametric: bool = False) -> Dict:
    out: Dict[str, Dict] = {}
    if parametric:
        for arm, k in (("pumap", None), ("pumap_debias", 2)):
            t = time.perf_counter()
            Y = pumap_arm(X, k, seed)
            out[arm] = {**aspect(Y), "kept10": kept10(X, Y), "ms": round((time.perf_counter() - t) * 1000)}
    for arm in ARMS:
        t = time.perf_counter()
        Z = prepare(X, arm, width, seed)
        Y = embed(Z, arm, seed)
        out[arm] = {**aspect(Y), "kept10": kept10(X, Y), "svd1_share": svd1_share(Z),
                    "ms": round((time.perf_counter() - t) * 1000)}
    rng = np.random.default_rng(seed)
    out["null_random"] = {"kept10": kept10(X, rng.normal(size=(X.shape[0], 3)))}
    return {"level": name, "n": int(X.shape[0]), "arms": out}


def planted(seed: int = 0) -> Dict:
    rng = np.random.default_rng(seed)
    t = rng.uniform(-1, 1, size=(600, 1))
    stick = np.hstack([t * 20, rng.normal(scale=0.5, size=(600, 2))])
    ball = rng.normal(size=(600, 3))
    return {"planted_stick": aspect(stick), "planted_ball": aspect(ball)}


def load(workspace: str):
    if workspace.startswith("http://") or workspace.startswith("https://"):
        # A store a running sidecar holds (a writer excludes readers): its rows
        # through `GET /lead_vectors`.
        import urllib.request
        with urllib.request.urlopen(workspace.rstrip("/") + "/lead_vectors", timeout=600) as r:
            return [tuple(x) for x in json.load(r)["rows"]]
    from ..workspace import Workspace
    ws = Workspace(workspace, read_only=True)
    try:
        rows = ws.store.lead_vectors()
    finally:
        ws.close()
    return rows


def run(workspace: str, chunk_sample: int = 2500, seed: int = 0, width: int = 64, parametric: bool = False) -> Dict:
    rows = load(workspace)
    vec = np.asarray([r[2] for r in rows], dtype=np.float32)
    urls = [r[1] for r in rows]
    by: Dict[str, List[int]] = {}
    for i, u in enumerate(urls):
        by.setdefault(u, []).append(i)
    pages = np.asarray([_unit(vec[ix]).mean(axis=0) for ix in by.values()], dtype=np.float32)
    rng = np.random.default_rng(seed)
    take = np.sort(rng.choice(len(vec), min(chunk_sample, len(vec)), replace=False))
    report = {"workspace": workspace, "engine": "umap-learn (CPU)", "chunks": len(vec), "pages": len(by),
              "drawn_live": {"spreads_p10_90": [5201, 653, 245], "aspect": 21.2, "n": 6132,
                             "source": "obsidian_eval on the graph pane, 2026-11-22"},
              "planted": planted(seed),
              "page": level(pages, "page", seed, width, parametric),
              "chunk": level(vec[take], "chunk", seed, width, parametric)}
    p = report["planted"]
    report["arms_discriminate"] = bool(p["planted_stick"]["aspect"] > 5 and p["planted_ball"]["aspect"] < 2)
    return report


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="domvec.analytics.layout_shape")
    ap.add_argument("--workspace", required=True, help="a workspace path, or a running sidecar's url")
    ap.add_argument("--chunks", type=int, default=2500)
    ap.add_argument("--width", type=int, default=64)
    ap.add_argument("--parametric", action="store_true", help="also the projector's own model (CUDA): pumap and pumap_debias")
    ap.add_argument("--out", default="build_analytics/layout_shape.json")
    a = ap.parse_args(argv)
    rep = run(a.workspace, a.chunks, width=a.width, parametric=a.parametric)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(rep, indent=1))
    for lv in ("page", "chunk"):
        print(lv, rep[lv]["n"])
        for arm, v in rep[lv]["arms"].items():
            print("  %-12s %s" % (arm, json.dumps(v)))
    print("planted", json.dumps(rep["planted"]), "discriminates:", rep["arms_discriminate"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
