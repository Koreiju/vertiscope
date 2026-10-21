"""What one page's diff costs ONE global parametric UMAP, and what it disturbs.

The user (2026-10-04): "a UMAP model applied to *all* scanned chunks from all
URLs ... but the re-fit update is only on the set of URL chunks. If re-update
latency is good, we will use this for 3D coordinate streaming".

This is the instrument for that sentence. It lives in `analytics/` because a
measurement inside the thing it measures cannot be trusted after that thing
changes (CLAUDE.md, constraint 3): the model under test is
`obsidian.pumap.ParametricUMAP` and the question is asked of it from outside.

Run (CUDA; keep a run under ~3 minutes -- the default is a short one)::

    python -m vertiscope.analytics.global_umap --sizes 2000,8000,15000 \
        --diffs 10,50,200 --trials 6

**Corpus.** Synthetic and clustered, 768-d: topics -> pages -> chunks, drawn
in a 32-d latent space and projected up, so neighbourhoods exist to be kept.
`pages x per_page` rows (default 100 chunks a page: 20 / 80 / 150 pages for
2k / 8k / 15k rows).

**A diff** on one page: `d` of its chunks are mutated (blended 60% toward a
chunk of ANOTHER page, so they must move) and, when `d` exceeds the page,
the surplus are appended as new chunks. The update then trains on the page's
rows -- `ParametricUMAP.update_subset`.

**What is scored, and against what denominator.**

* `latency` -- wall time of `update_subset` with the drift probe OFF (the
  probe is this module's, not the product's), p50 / p95 over trials, each a
  different page, applied in sequence to the same model as production does.
  The `copy_ms` of the deep copy the projector takes first is reported
  beside it, not hidden in it.
* `held_drift` -- every row NOT in the diff, the net's output now vs the
  position it had; absolute (p50 / p90 / max) and as a share of the median
  PAIRWISE distance of the held cloud ("the spacing", as the repo's page tests
  use it) and of its median 1-NN distance (the strictest reading). Denominator: held rows (what the update was
  promised not to disturb).
* `overlap10` -- for the page's rows (the ones whose vectors changed or were
  added), the share of each row's 10 nearest neighbours IN INPUT SPACE (new
  vectors, whole corpus) that are also among its 10 nearest in the embedding.
  Denominator: the page's rows. Scored in the model's 6 output dims
  (`overlap10`) and in the 3 the reader draws (`overlap10_3d`).

**Arms (a score with no arm that can fail is not a measurement).**

* `random`  -- the page's rows at random positions: the null. Overlap ~ k/N.
* `stale`   -- the page's rows through the net as it stood (no training):
  what streaming `transform` alone gives. The update has to beat this.
* `base`    -- the page's rows BEFORE the diff, on the base model: the
  ceiling a net this size and this short a fit can reach on that page.
* `full`    -- the existing `update()` (every row trained), only where it is
  affordable (<= `--full-max-rows`): what the scheme replaces.
* `planted` -- `update_subset` with the landmark pull off and no landmarks:
  held rows must DRIFT there, or `held_drift` could not have caught anything.
"""

from __future__ import annotations

import argparse
import copy
import json
import pathlib
import time
from typing import Dict, List, Optional, Tuple

import numpy as np


# -- the corpus ---------------------------------------------------------------

def make_corpus(pages: int, per_page: int = 100, dim: int = 768, *, latent: int = 32,
                seed: int = 0) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(X unit rows, page index per row, the latent->dim projection)."""
    rng = np.random.default_rng(seed)
    topics = max(2, pages // 8)
    T = rng.normal(size=(topics, latent)) * 3.0
    P = T[rng.integers(0, topics, pages)] + rng.normal(size=(pages, latent)) * 1.2
    page_of = np.repeat(np.arange(pages), per_page)
    Z = P[page_of] + rng.normal(size=(len(page_of), latent)) * 0.8
    proj = rng.normal(size=(latent, dim)) / np.sqrt(latent)
    X = Z @ proj + rng.normal(size=(len(page_of), dim)) * 0.05
    X /= np.linalg.norm(X, axis=1, keepdims=True)
    return X.astype(np.float32), page_of, proj.astype(np.float32)


def diff_page(X: np.ndarray, page_of: np.ndarray, page: int, d: int,
              rng: np.random.Generator) -> Tuple[np.ndarray, np.ndarray]:
    """(mutated rows' indices, their new vectors) + appended vectors.

    Returns (idx_mutated, X_mutated, X_appended)."""
    rows = np.flatnonzero(page_of == page)
    m = min(d, len(rows))
    mut = rng.choice(rows, m, replace=False)
    other = rng.choice(np.flatnonzero(page_of != page), m)
    new = 0.4 * X[mut] + 0.6 * X[other] + rng.normal(size=(m, X.shape[1])) * 0.01
    new /= np.linalg.norm(new, axis=1, keepdims=True)
    extra = d - m
    if extra > 0:
        base = X[rng.choice(rows, extra)]
        add = base + rng.normal(size=base.shape) * 0.03
        add /= np.linalg.norm(add, axis=1, keepdims=True)
    else:
        add = np.zeros((0, X.shape[1]), np.float32)
    return mut, new.astype(np.float32), add.astype(np.float32)


# -- the scores ---------------------------------------------------------------

def _torch():
    import torch
    return torch, torch.device("cuda" if torch.cuda.is_available() else "cpu")


def knn_overlap(Xin: np.ndarray, Y: np.ndarray, rows: np.ndarray, k: int = 10) -> float:
    """Mean share of each row's k input-space neighbours kept in the embedding."""
    torch, dev = _torch()
    A = torch.as_tensor(np.asarray(Xin, np.float32), device=dev)
    B = torch.as_tensor(np.asarray(Y, np.float32), device=dev)
    r = torch.as_tensor(np.asarray(rows), device=dev)
    ia = torch.topk(torch.cdist(A[r], A), k + 1, largest=False).indices
    ib = torch.topk(torch.cdist(B[r], B), k + 1, largest=False).indices
    hit = []
    for a, b, me in zip(ia.cpu().numpy(), ib.cpu().numpy(), rows):
        sa, sb = set(a.tolist()) - {int(me)}, set(b.tolist()) - {int(me)}
        hit.append(len(sa & sb) / float(k))
    return float(np.mean(hit))


def held_drift(model, held: np.ndarray, before: np.ndarray) -> Dict[str, float]:
    """The net's output on held rows now vs where they were, and vs spacing."""
    now = model.transform(model._raw[held])
    d = np.linalg.norm(now[:, :3] - before[held][:, :3], axis=1)
    sample = before[held][:, :3]
    pick = sample[np.random.default_rng(0).choice(len(sample), min(len(sample), 1500), replace=False)]
    torch, dev = _torch()
    P = torch.as_tensor(pick, device=dev)
    D = torch.cdist(P, P)
    D.fill_diagonal_(float("inf"))
    D2 = D.clone()
    D2[torch.isinf(D2)] = 0.0
    spread = float(D2.median())                 # median pairwise: "the spacing"
    nn1 = float(D.min(1).values.median())
    return {"p50": float(np.median(d)), "p90": float(np.percentile(d, 90)),
            "max": float(d.max()), "spread": spread, "nn1": nn1,
            "p50_of_spread": float(np.median(d)) / max(spread, 1e-9),
            "p90_of_spread": float(np.percentile(d, 90)) / max(spread, 1e-9),
            "p99": float(np.percentile(d, 99)), "over5pct": float((d > 0.05 * spread).mean()),
            "p50_of_nn1": float(np.median(d)) / max(nn1, 1e-9)}


def _fit_base(X: np.ndarray, fit_steps: int, seed: int = 0):
    from ..obsidian.pumap import ParametricUMAP
    m = ParametricUMAP(n_components=6, n_neighbors=15, min_dist=0.25, seed=seed)
    t = time.perf_counter()
    m.fit(X, max_steps=fit_steps)
    return m, time.perf_counter() - t


def _pct(v: List[float], q: float) -> float:
    return float(np.percentile(v, q)) if v else float("nan")


# -- one configuration --------------------------------------------------------

def run_config(base, X: np.ndarray, page_of: np.ndarray, d: int, trials: int,
               *, seed: int = 0, params: Optional[Dict] = None, arms: bool = True,
               full_max_rows: int = 2500) -> Dict:
    """`trials` diffs on different pages, applied in sequence to a copy of `base`."""
    params = dict(params or {})
    rng = np.random.default_rng(seed + d)
    model = copy.deepcopy(base)
    Xcur = X.copy()
    pages = rng.choice(np.unique(page_of), trials + 1, replace=False)
    lat, copy_ms, trained = [], [], []
    drift50, drift90, driftmax, drift_sp, drift_nn, drift_o5 = [], [], [], [], [], []
    ov = {"subset": [], "stale": [], "base": [], "random": [], "full": [], "planted": []}
    ov3 = {"subset": [], "stale": [], "base": [], "random": []}
    for t, page in enumerate(pages):
        rows = np.flatnonzero(page_of[: len(Xcur)] == page)
        mut, newv, add = diff_page(Xcur, page_of, page, d, rng)
        n0 = len(model._raw)
        idx = np.concatenate([mut, np.arange(n0, n0 + len(add))]).astype(np.int64)
        Xnew = np.vstack([newv, add]) if len(add) else newv
        before = model.embedding_.copy()
        t0 = time.perf_counter()
        scratch = copy.deepcopy(model)
        cms = (time.perf_counter() - t0) * 1000
        if arms and t > 0:
            ov["base"].append(knn_overlap(Xcur, before, rows))
            ov3["base"].append(knn_overlap(Xcur, before[:, :3], rows))
        # what streaming transform alone says about the new vectors
        stale = model.transform(Xnew)
        t0 = time.perf_counter()
        pos = model.update_subset(Xnew, idx, measure_drift=False, **params)
        secs = time.perf_counter() - t0
        # Grow the corpus mirror the model holds.
        if len(add):
            Xcur = np.vstack([Xcur, add])
            page_of = np.concatenate([page_of, np.full(len(add), page)])
        Xcur[mut] = newv
        if t == 0:
            continue                        # warm-up: kernels, allocator
        lat.append(secs * 1000)
        copy_ms.append(cms)
        trained.append(model.stats.get("trained_rows", 0))
        held = np.setdiff1d(np.arange(n0), np.unique(idx))
        hd = held_drift(model, held, before)
        drift50.append(hd["p50"]); drift90.append(hd["p90"]); driftmax.append(hd["max"])
        drift_sp.append(hd["p50_of_spread"]); drift_nn.append(hd["p50_of_nn1"]); drift_o5.append(hd["over5pct"])
        if arms:
            Y = model.embedding_
            act = np.unique(idx)
            ov["subset"].append(knn_overlap(Xcur, Y, act))
            ov3["subset"].append(knn_overlap(Xcur, Y[:, :3], act))
            Ys = Y.copy(); Ys[idx] = stale
            ov["stale"].append(knn_overlap(Xcur, Ys, act))
            ov3["stale"].append(knn_overlap(Xcur, Ys[:, :3], act))
            Yr = Y.copy()
            lo, hi = Y.min(0), Y.max(0)
            Yr[act] = rng.uniform(lo, hi, size=(len(act), Y.shape[1]))
            ov["random"].append(knn_overlap(Xcur, Yr, act))
            ov3["random"].append(knn_overlap(Xcur, Yr[:, :3], act))
    out = {
        "diff": d, "trials": len(lat), "rows": int(len(model._raw)),
        "latency_ms": {"p50": _pct(lat, 50), "p95": _pct(lat, 95), "max": max(lat) if lat else None},
        "copy_ms": {"p50": _pct(copy_ms, 50)},
        "trained_rows_p50": _pct(trained, 50),
        "held_drift": {"p50": float(np.mean(drift50)), "p90": float(np.mean(drift90)),
                       "max": float(np.max(driftmax)), "p50_of_spread": float(np.mean(drift_sp)),
                       "p50_of_nn1": float(np.mean(drift_nn)), "over5pct": float(np.mean(drift_o5))},
        "params": params,
    }
    if arms:
        out["overlap10"] = {k: (float(np.mean(v)) if v else None) for k, v in ov.items()}
        out["overlap10_3d"] = {k: (float(np.mean(v)) if v else None) for k, v in ov3.items()}
    return out


def run_full_arm(base, X, page_of, d: int, seed: int = 0) -> Dict:
    """The existing update(): every row trained, mutated rows APPENDED as new."""
    rng = np.random.default_rng(seed + d)
    model = copy.deepcopy(base)
    page = int(rng.choice(np.unique(page_of)))
    mut, newv, add = diff_page(X, page_of, page, d, rng)
    Xnew = np.vstack([newv, add]) if len(add) else newv
    t0 = time.perf_counter()
    model.update(Xnew)
    secs = time.perf_counter() - t0
    Xcur = np.vstack([X, Xnew])
    Xcur_eff = Xcur.copy()
    # score the appended rows (the page's new vectors) against the same corpus
    rows = np.arange(len(X), len(Xcur))
    return {"diff": d, "latency_ms": secs * 1000, "rows": int(len(Xcur)),
            "overlap10": knn_overlap(Xcur_eff, model.embedding_, rows),
            "overlap10_3d": knn_overlap(Xcur_eff, model.embedding_[:, :3], rows)}


class _Chunk:
    def __init__(self, url):
        self.url, self.redundant, self.group_of = url, False, None


class _Store:
    def __init__(self, rows):
        self.rows = rows

    def lead_vectors(self):
        return self.rows

    def chunk_count(self):
        return len(self.rows)

    def chunks_for_placement(self, cids):
        by = {c: (u, v) for c, u, v in self.rows}
        return [(c, _Chunk(by[c][0]), by[c][1]) if c in by else (c, None, None) for c in cids]


def run_projector(size: int, d: int, trials: int, per_page: int = 100, fit_steps: Optional[int] = None) -> Dict:
    """The whole path, not the model alone: `PageProjector(umap_scope="global")`
    fitted over the corpus, then page diffs of `d` mutated chunks through
    `enqueue` -> `drain` (the page is DRAWN here, by transform) -> the online
    worker (`update_subset`, then placing the page and its chunks), until the
    delta carries the trained positions. The 2 s debounce that holds the
    worker back in production is set to 0 and reported separately: it delays
    the retrain, never the drawing."""
    import threading
    from types import SimpleNamespace
    from ..obsidian.projector import PageProjector
    X, page_of, _ = make_corpus(size // per_page, per_page)
    rows = [("c%d" % i, "https://p%d.test/" % page_of[i], X[i].tolist()) for i in range(len(X))]
    ws = SimpleNamespace(store=_Store(rows), path=None)
    PageProjector.ONLINE_DEBOUNCE_S = 0.0
    if fit_steps:
        PageProjector.GLOBAL_FIT_STEPS = fit_steps
    proj = PageProjector(dims=3, centroid="semantic", seed=0, engine="parametric", umap_scope="global")
    t = time.perf_counter()
    fit = proj.fit(ws)
    out = {"size": size, "diff": d, "fit_s": round(time.perf_counter() - t, 1), "scope": proj.scope,
           "fit_ms": {k: fit.get(k) for k in ("ms_read", "ms_centroids", "ms_fit", "ms_chunks", "ms")}}
    rng = np.random.default_rng(0)
    cur = list(rows)
    Xc = X.copy()
    lat, drain_ms, train_ms, place_ms, seen_ms, moved = [], [], [], [], [], []
    for trial in range(trials + 1):
        page = int(rng.choice(np.unique(page_of)))
        mut, newv, add = diff_page(Xc, page_of, page, d, rng)
        for i, v in zip(mut, newv):
            cur[i] = (cur[i][0], cur[i][1], v.tolist())
            Xc[i] = v
        ws.store = _Store(cur)
        before = len(proj.online_updates)
        old_pos = list(proj.page_pos["https://p%d.test/" % page])
        seq0 = proj.seq
        t0 = time.perf_counter()
        proj.enqueue([cur[i][0] for i in mut])
        rec = proj.drain(ws)
        t_drain = (time.perf_counter() - t0) * 1000
        end = time.time() + 60
        while len(proj.online_updates) == before and time.time() < end:
            time.sleep(0.002)
        t_done = (time.perf_counter() - t0) * 1000
        if trial == 0:
            continue                              # warm-up
        u = proj.online_updates[-1]
        d_ = proj.delta(seq0, proj.epoch)
        lat.append(t_done); drain_ms.append(t_drain)
        train_ms.append(u["ms_train"]); place_ms.append(u["ms_place"])
        moved.append(float(np.linalg.norm(np.asarray(proj.page_pos["https://p%d.test/" % page]) - np.asarray(old_pos))))
        seen_ms.append(len(d_["chunks"]))
    out.update({"trials": len(lat),
                "edit_to_trained_in_delta_ms": {"p50": _pct(lat, 50), "p95": _pct(lat, 95)},
                "drain_ms_p50": _pct(drain_ms, 50), "ms_train_p50": _pct(train_ms, 50),
                "ms_place_p50": _pct(place_ms, 50), "page_moved_p50": _pct(moved, 50),
                "delta_chunks_p50": _pct(seen_ms, 50), "rows": int(proj.pumap._raw.shape[0])})
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="vertiscope.analytics.global_umap")
    ap.add_argument("--sizes", default="2000,8000,15000")
    ap.add_argument("--diffs", default="10,50,200")
    ap.add_argument("--trials", type=int, default=6)
    ap.add_argument("--per-page", type=int, default=100)
    ap.add_argument("--fit-steps", type=int, default=4000)
    ap.add_argument("--steps", type=int, default=300)
    ap.add_argument("--full-max-rows", type=int, default=2500)
    ap.add_argument("--no-arms", action="store_true")
    ap.add_argument("--projector", action="store_true",
                    help="measure the whole PageProjector path (scope global) instead of the model alone")
    ap.add_argument("--out", default="build_analytics/global_umap.json")
    args = ap.parse_args(argv)
    torch, dev = _torch()
    report = {"device": str(dev), "gpu": torch.cuda.get_device_name(0) if dev.type == "cuda" else None,
              "steps": args.steps, "configs": []}
    if args.projector:
        for size in [int(s) for s in args.sizes.split(",")]:
            for d in [int(v) for v in args.diffs.split(",")]:
                rec = run_projector(size, d, args.trials, args.per_page, args.fit_steps)
                report["configs"].append(rec)
                print(json.dumps(rec), flush=True)
        out = pathlib.Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        return 0
    for size in [int(s) for s in args.sizes.split(",")]:
        pages = size // args.per_page
        X, page_of, _ = make_corpus(pages, args.per_page)
        base, fit_s = _fit_base(X, args.fit_steps)
        print("rows=%d fit %.1fs (%d steps)" % (len(X), fit_s, args.fit_steps), flush=True)
        for d in [int(v) for v in args.diffs.split(",")]:
            rec = run_config(base, X, page_of, d, args.trials, params={"steps": args.steps},
                             arms=not args.no_arms)
            rec["corpus_rows"] = size
            rec["base_fit_s"] = round(fit_s, 1)
            if not args.no_arms:
                # landmark pull off: the planted defect for `held_drift`
                saved = base.landmark_weight
                base.landmark_weight = 0.0
                planted = run_config(base, X, page_of, d, 3, params={"steps": args.steps}, arms=False)
                base.landmark_weight = saved
                rec["planted_no_landmark_drift"] = planted["held_drift"]
            if size <= args.full_max_rows and not args.no_arms:
                rec["full_update"] = run_full_arm(base, X, page_of, d)
            report["configs"].append(rec)
            lt = rec["latency_ms"]
            print("  d=%-4d p50 %.0f ms  p95 %.0f ms  trained %d  drift p50 %.4f (%.2f%% of spread)  %s" % (
                d, lt["p50"], lt["p95"], rec["trained_rows_p50"], rec["held_drift"]["p50"],
                100 * rec["held_drift"]["p50_of_spread"],
                ("overlap " + json.dumps({k: round(v, 3) for k, v in rec["overlap10"].items() if v is not None}))
                if "overlap10" in rec else ""), flush=True)
    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
