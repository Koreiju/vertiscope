"""A parametric UMAP that learns ONLINE, on the local CUDA runtime.

Why this exists (2026-09-27, the user): "incrementally re-train online for
new embeddings ... train on just the diff updates and assume previous fits
are fixed ... training on subchunks happens only after they are first
projected through the previously fitted transform, before the re-fit with the
new diffs ... previous parameter persistence while also enabling for new fits
on new batches", and "whichever of your finds supports our local cuda
runtime, that should also be included in online updates".

Measured before building it (see PLUGIN_GOAL.md, Addendum IX): umap-learn's
`UMAP.update` warm-starts a refit on the new points but lets every old point
move (median 37% of the page spacing); a fresh fit moves them 95%. RAPIDS cuML
is not native on Windows and TensorFlow (umap-learn's ParametricUMAP) is not
installed; PyTorch 2.6 + CUDA 12.4 is. So: UMAP's own objective, trained as a
small network in PyTorch --

* **fit(X)** -- the fuzzy simplicial set of X (umap-learn's own
  `fuzzy_simplicial_set`, CPU), then the UMAP cross-entropy by edge and
  negative sampling, minimised over the NETWORK's parameters on the GPU.
* **transform(X)** -- the network's forward pass. A fitted point and a new
  point go through the same function, so the two can never disagree.
* **update(X_new)** -- the diff, after it has already been placed by
  `transform` (the reader sees it at once). The graph is rebuilt over old and
  new rows; training continues from the persisted weights with the UMAP loss
  plus a LANDMARK loss pinning every previously placed row to where it was
  (umap-learn's documented recipe for retraining a parametric UMAP on new
  data, "landmarked" training). Old positions stay put; new ones settle.

The fuzzy graph is built on the CPU by umap-learn (it is the same object the
non-parametric fit optimises); only the optimisation runs on CUDA, and the
module falls back to the CPU when no GPU is present.
"""
from __future__ import annotations

import time
from typing import Dict, Optional

import numpy as np


def _device():
    import torch
    return torch.device("cuda" if torch.cuda.is_available() else "cpu")


#: Called between optimiser steps when set: background training stands aside
#: for foreground work (the sidecar sets it to yield to searches).
TRAIN_YIELD = [None]

class ParametricUMAP:
    """A small MLP trained on UMAP's objective; `transform` is its forward pass."""

    def __init__(self, n_components: int = 6, *, n_neighbors: int = 15,
                 min_dist: float = 0.25, hidden: int = 256, seed: int = 0,
                 epochs: int = 200, update_epochs: int = 120,
                 landmark_weight: float = 10.0, negative_rate: int = 5,
                 batch_edges: int = 1024) -> None:
        self.n_components = n_components
        self.n_neighbors = n_neighbors
        self.min_dist = min_dist
        self.hidden = hidden
        self.seed = seed
        self.epochs = epochs
        self.update_epochs = update_epochs
        self.landmark_weight = landmark_weight
        self.negative_rate = negative_rate
        self.batch_edges = batch_edges
        self.net = None
        self.dim_in: Optional[int] = None
        self._raw: Optional[np.ndarray] = None          # every row trained on
        #: Rows `update_subset` has retired (a chunk its page no longer has);
        #: None while every row is live. Never a landmark, never an edge.
        self._alive: Optional[np.ndarray] = None
        #: Rows `update_subset` has retired (a chunk the page no longer has);
        #: None while every row is live. Never a landmark, never an edge.
        self._alive: Optional[np.ndarray] = None
        self.embedding_: Optional[np.ndarray] = None    # their positions
        self.stats: Dict[str, float] = {}
        from umap.umap_ import find_ab_params
        self._a, self._b = find_ab_params(1.0, min_dist)

    # -- the network ---------------------------------------------------------
    def _build(self, dim_in: int) -> None:
        import torch
        torch.manual_seed(self.seed)
        self.dim_in = dim_in
        h = self.hidden
        self.net = torch.nn.Sequential(
            torch.nn.Linear(dim_in, h), torch.nn.ReLU(),
            torch.nn.Linear(h, h), torch.nn.ReLU(),
            torch.nn.Linear(h, h), torch.nn.ReLU(),
            torch.nn.Linear(h, self.n_components),
        ).to(_device())

    def transform(self, X: np.ndarray) -> np.ndarray:
        import torch
        if self.net is None:
            raise RuntimeError("not fitted")
        self.net.eval()
        out = []
        with torch.no_grad():
            for lo in range(0, len(X), 8192):
                xb = torch.as_tensor(np.asarray(X[lo:lo + 8192], dtype=np.float32), device=_device())
                out.append(self.net(xb).cpu().numpy())
        return np.concatenate(out) if out else np.zeros((0, self.n_components), np.float32)

    # -- the graph -----------------------------------------------------------
    def _graph(self, X: np.ndarray):
        """UMAP's fuzzy simplicial set of X: on the GPU for the sizes a page
        layout has (exact kNN by `cdist`), umap-learn's otherwise.

        umap-learn builds it with numba-compiled code that compiles on first
        use in a process -- most of a 16-33 s first fit whose training steps
        took 4 ms each (2026-09-27). Same maths: rho = distance to the nearest
        neighbour, sigma by binary search so the memberships sum to log2(k),
        then the fuzzy union W + W' - W*W'."""
        if len(X) <= 20000:
            try:
                return self._graph_torch(X)
            except Exception:                        # noqa: BLE001
                pass
        return self._graph_umap(X)

    def _graph_torch(self, X: np.ndarray):
        import torch
        dev = _device()
        n = len(X)
        k = int(max(2, min(self.n_neighbors, n - 1)))
        Xt = torch.as_tensor(np.asarray(X, dtype=np.float32), device=dev)
        rows_i, rows_j, rows_d = [], [], []
        for lo in range(0, n, 4096):
            D = torch.cdist(Xt[lo:lo + 4096], Xt)
            D[torch.arange(D.shape[0], device=dev), torch.arange(lo, lo + D.shape[0], device=dev)] = float("inf")
            d, j = torch.topk(D, k, dim=1, largest=False)
            rows_d.append(d); rows_j.append(j)
        d = torch.cat(rows_d); j = torch.cat(rows_j)
        rho = d[:, 0:1]
        target = float(np.log2(k))
        lo_s = torch.zeros(n, 1, device=dev); hi_s = torch.full((n, 1), float("inf"), device=dev)
        sigma = torch.ones(n, 1, device=dev)
        excess = (d - rho).clamp_min(0)
        for _ in range(64):
            psum = torch.exp(-excess / sigma).sum(1, keepdim=True)
            above = psum > target
            hi_s = torch.where(above, sigma, hi_s)
            lo_s = torch.where(above, lo_s, sigma)
            sigma = torch.where(torch.isinf(hi_s), sigma * 2, (lo_s + hi_s) / 2)
        w = torch.exp(-excess / sigma.clamp_min(1e-6))
        i = torch.arange(n, device=dev).unsqueeze(1).expand(-1, k)
        W = torch.sparse_coo_tensor(torch.stack([i.reshape(-1), j.reshape(-1)]), w.reshape(-1), (n, n)).coalesce()
        Wt = W.transpose(0, 1).coalesce()
        S = (W + Wt - W * Wt).coalesce()
        idx, val = S.indices().cpu().numpy(), S.values().cpu().numpy()
        keep = val > val.max() / 200.0
        return idx[0][keep], idx[1][keep], val[keep]

    def _graph_umap(self, X: np.ndarray):
        from umap.umap_ import fuzzy_simplicial_set
        from sklearn.utils import check_random_state
        k = int(max(2, min(self.n_neighbors, len(X) - 1)))
        graph, _s, _r = fuzzy_simplicial_set(
            X, k, check_random_state(self.seed), "euclidean")
        graph = graph.tocoo()
        keep = graph.data > graph.data.max() / 200.0   # as umap drops weak edges
        return graph.row[keep], graph.col[keep], graph.data[keep]

    # -- training ------------------------------------------------------------
    def _train(self, X: np.ndarray, epochs: int, landmarks: Optional[np.ndarray] = None,
               max_steps: Optional[int] = None) -> float:
        """UMAP cross-entropy by edge sampling (+ a landmark pull on the first
        `len(landmarks)` rows). Returns the wall time. `max_steps` caps the
        optimiser steps (a first fit over thousands of rows would otherwise
        run epochs x edges/batch of them)."""
        import torch
        dev = _device()
        started = time.perf_counter()
        head, tail, w = self._graph(X)
        self.stats["graph_s"] = round(time.perf_counter() - started, 3)
        if not len(head):
            return 0.0
        Xt = torch.as_tensor(X, dtype=torch.float32, device=dev)
        p = torch.as_tensor(w / w.sum(), dtype=torch.float32, device=dev)
        H = torch.as_tensor(head, dtype=torch.long, device=dev)
        T = torch.as_tensor(tail, dtype=torch.long, device=dev)
        L = (torch.as_tensor(landmarks, dtype=torch.float32, device=dev)
             if landmarks is not None and len(landmarks) else None)
        opt = torch.optim.Adam(self.net.parameters(), lr=1e-3)
        a, b = float(self._a), float(self._b)
        n = len(X)
        g = torch.Generator(device=dev)
        g.manual_seed(self.seed)
        # One "epoch" draws as many edges as the graph holds.
        # At least a few steps per epoch: a small graph (a hundred pages)
        # holds under one batch of edges, and 200 steps did not converge.
        steps_per_epoch = max(4, int(np.ceil(len(head) / self.batch_edges)))
        self.net.train()
        # A page layout has a few hundred rows: run the network ONCE per step
        # over all of them and index into the result, instead of three forward
        # passes over thousands of sampled rows (the first fit took 15.7 s for
        # 146 pages that way, 2026-09-27).
        whole = n <= 8192
        done = 0
        for _epoch in range(epochs):
            if max_steps is not None and done >= max_steps:
                break
            for _s in range(steps_per_epoch):
                if max_steps is not None and done >= max_steps:
                    break
                done += 1
                # Steps aside while the reader is waiting on a search
                # (`TRAIN_YIELD`, set by the sidecar): an online update ran
                # 41-77 s back to back while pages streamed, and searches took
                # up to 17 s behind it (2026-10-18, PLUGIN_GOAL 152).
                if TRAIN_YIELD[0] is not None:
                    TRAIN_YIELD[0]()
                e = torch.multinomial(p, self.batch_edges, replacement=True, generator=g)
                Z = self.net(Xt) if whole else None
                zi = Z[H[e]] if whole else self.net(Xt[H[e]])
                zj = Z[T[e]] if whole else self.net(Xt[T[e]])
                # UMAP's cross-entropy in its stable log form. With
                # u = a * d^(2b):  -log q = log1p(u);  -log(1-q) = log1p(u) - log(u).
                # Clamping q (the first version) zeroed the repulsion's gradient
                # once points met, and every page collapsed onto one point
                # (spacing 0.00, trustworthiness 0.535, 2026-09-27).
                d2 = ((zi - zj) ** 2).sum(1) + 1e-6
                u = a * d2 ** b
                attract = torch.log1p(u).mean()
                neg = torch.randint(0, n, (self.batch_edges * self.negative_rate,), device=dev, generator=g)
                zn = Z[neg] if whole else self.net(Xt[neg])
                zi_rep = zi.repeat_interleave(self.negative_rate, 0)
                d2n = ((zi_rep - zn) ** 2).sum(1) + 1e-3
                un = a * d2n ** b
                repel = (torch.log1p(un) - torch.log(un)).mean()
                loss = attract + repel
                if L is not None:
                    # The previous fit held FIXED: every earlier row is pulled
                    # back to where it was placed.
                    m = len(L)
                    idx = torch.randint(0, m, (min(m, self.batch_edges),), device=dev, generator=g)
                    zl = Z[idx] if whole else self.net(Xt[idx])
                    loss = loss + self.landmark_weight * ((zl - L[idx]) ** 2).sum(1).mean()
                opt.zero_grad()
                loss.backward()
                opt.step()
        if dev.type == "cuda":
            torch.cuda.synchronize()
        return time.perf_counter() - started

    def fit(self, X: np.ndarray, max_steps: Optional[int] = None) -> "ParametricUMAP":
        X = np.asarray(X, dtype=np.float32)
        self._build(X.shape[1])
        secs = self._train(X, self.epochs, max_steps=max_steps)
        self._raw = X
        self._alive = None
        self.embedding_ = self.transform(X)
        self.stats = {"rows": len(X), "fit_s": round(secs, 3), "device": str(_device()),
                      "graph_s": self.stats.get("graph_s")}
        return self

    def fit_transform(self, X: np.ndarray) -> np.ndarray:
        return self.fit(X).embedding_

    def update(self, X_new: np.ndarray) -> np.ndarray:
        """Train on the diff with everything placed before held fixed.

        The new rows have ALREADY been drawn through `transform` by the caller
        (the stream shows the reader the diff at once); this is the re-fit
        that follows, from the persisted weights."""
        X_new = np.asarray(X_new, dtype=np.float32)
        if self.net is None:
            return self.fit_transform(X_new)
        if not len(X_new):
            return self.embedding_
        before = self.embedding_.copy()
        X = np.vstack([self._raw, X_new])
        secs = self._train(X, self.update_epochs, landmarks=before)
        self._raw = X
        self.embedding_ = self.transform(X)
        drift = np.linalg.norm(self.embedding_[:len(before), :3] - before[:, :3], axis=1)
        self.stats.update({"rows": len(X), "update_s": round(secs, 3),
                           "update_rows": len(X_new),
                           "old_drift_p50": float(np.median(drift)) if len(drift) else 0.0,
                           "old_drift_p90": float(np.percentile(drift, 90)) if len(drift) else 0.0})
        return self.embedding_[len(before):]

    def update_subset(self, X_rows: np.ndarray, idx, *, remove=None,
                      steps: int = 300, knn: int = 8, random_landmarks: int = 256,
                      max_landmarks: int = 1024, batch_edges: int = 512,
                      lr: float = 1e-3, measure_drift: bool = True,
                      use_graph: bool = True) -> np.ndarray:
        """Re-fit the rows `idx` of ONE global model; the rest are held by landmarks.

        The user (2026-10-04): "a UMAP model applied to *all* scanned chunks
        from all URLs ... but the re-fit update is only on the set of URL
        chunks." `update()` cannot be that: it trains on every row it has ever
        seen, so its cost is the corpus's (1.5 / 2.7 / 6.6 / 15.9 s at 160 /
        500 / 1,000 / 2,000 rows, `refitscope.SEED_CURVE`). This trains on a
        BOUNDED set:

        * the ACTIVE rows -- the page's chunks, with their new vectors. An
          `idx` below the model's row count REPLACES that row (a mutated
          chunk keeps its slot; nothing stale accumulates); an `idx` at or
          past it APPENDS (a new chunk), placed at once by the current net.
        * LANDMARK rows -- the `knn` nearest held rows of each active row in
          input space (the local context the page must stay consistent with)
          plus `random_landmarks` random held rows (the global frame), capped
          at `max_landmarks`. Each is pulled back to its stored position, so
          the net keeps drawing everything it does not train on where it was.
        * `remove` -- rows to retire (chunks the page no longer holds).

        The UMAP graph is built over active + landmarks only and edges are
        sampled from those touching an active row, for a FIXED number of
        `steps`: the cost scales with the page, not the corpus. Returns the
        new positions of `idx`, in order; `embedding_` rows outside `idx` are
        not rewritten (held)."""
        import torch
        if self.net is None or self._raw is None:
            raise RuntimeError("not fitted")
        dev = _device()
        started = time.perf_counter()
        X_rows = np.asarray(X_rows, dtype=np.float32)
        idx = np.asarray(idx, dtype=np.int64).reshape(-1)
        if len(X_rows) != len(idx):
            raise ValueError("one vector per index")
        n0 = len(self._raw)
        if not len(idx):
            # Only retirements: nothing to train, the rows just stop being landmarks.
            if self._alive is None:
                self._alive = np.ones(n0, dtype=bool)
            if remove is not None and len(remove):
                self._alive[np.asarray(remove, dtype=np.int64)] = False
            return np.zeros((0, self.embedding_.shape[1]), np.float32)
        append = np.sort(idx[idx >= n0])
        if len(append) and not np.array_equal(append, np.arange(n0, n0 + len(append))):
            raise ValueError("appended rows must be contiguous from %d" % n0)
        if self._alive is None:
            self._alive = np.ones(n0, dtype=bool)
        if len(append):
            k_new = len(append)
            self._raw = np.concatenate([self._raw, np.zeros((k_new, self._raw.shape[1]), np.float32)])
            self.embedding_ = np.concatenate(
                [self.embedding_, np.zeros((k_new, self.embedding_.shape[1]), np.float32)])
            self._alive = np.concatenate([self._alive, np.ones(k_new, dtype=bool)])
        self._raw[idx] = X_rows
        self._alive[idx] = True
        if remove is not None and len(remove):
            self._alive[np.asarray(remove, dtype=np.int64)] = False
        active = np.unique(idx)
        # An appended row is on screen the moment it exists: placed by the
        # net as it stands, before it is trained on.
        if len(append):
            self.embedding_[append] = self.transform(self._raw[append])
        held = np.flatnonzero(self._alive)
        held = held[~np.isin(held, active)]
        t = time.perf_counter()
        m = len(active)
        Xa = torch.as_tensor(self._raw[active], dtype=torch.float32, device=dev)
        picked = np.zeros(0, dtype=np.int64)
        if len(held):
            Xh = torch.as_tensor(self._raw[held], dtype=torch.float32, device=dev)
            D = torch.cdist(Xa, Xh)
            kk = int(min(knn, len(held)))
            _d, j = torch.topk(D, kk, dim=1, largest=False)
            near = torch.unique(j.reshape(-1))
            cap_near = int(max(0, max_landmarks - random_landmarks))
            if len(near) > cap_near:
                dmin = D.min(dim=0).values[near]
                near = near[torch.argsort(dmin)[:cap_near]]
            near = near.cpu().numpy()
            rest = np.setdiff1d(np.arange(len(held)), near)
            g = np.random.default_rng(self.seed + n0)
            rand = (g.choice(rest, int(min(random_landmarks, len(rest))), replace=False)
                    if len(rest) else rest)
            picked = held[np.concatenate([near, rand]).astype(np.int64)]
        ms_select = (time.perf_counter() - t) * 1000
        S = np.concatenate([active, picked])
        Xs = self._raw[S]
        t = time.perf_counter()
        head, tail, w = self._graph(Xs)
        ms_graph = (time.perf_counter() - t) * 1000
        keep = (head < m) | (tail < m)
        if keep.any():
            head, tail, w = head[keep], tail[keep], w[keep]
        if not len(head):
            return self.embedding_[idx]
        Xt = torch.as_tensor(Xs, dtype=torch.float32, device=dev)
        p = torch.as_tensor(w / w.sum(), dtype=torch.float32, device=dev)
        H = torch.as_tensor(head, dtype=torch.long, device=dev)
        T = torch.as_tensor(tail, dtype=torch.long, device=dev)
        L = (torch.as_tensor(self.embedding_[picked], dtype=torch.float32, device=dev)
             if len(picked) else None)
        cuda = dev.type == "cuda"
        opt = None
        for kw in (dict(fused=True, capturable=True), dict(capturable=True), {}) if cuda else ({},):
            try:
                opt = torch.optim.Adam(self.net.parameters(), lr=lr, **kw)
                break
            except Exception:                        # noqa: BLE001
                continue
        a, b = float(self._a), float(self._b)
        n = len(S)
        gen = torch.Generator(device=dev)
        gen.manual_seed(self.seed + n0)
        steps = int(steps)
        # Every random draw for every step, made at once: a step is a handful
        # of tiny kernels and the launches, not the arithmetic, were the time.
        E = torch.multinomial(p, steps * batch_edges, replacement=True, generator=gen).view(steps, batch_edges)
        Hs, Ts = H[E], T[E]
        NEG = torch.randint(0, n, (steps, batch_edges * self.negative_rate), device=dev, generator=gen)
        LI = (torch.randint(0, len(L), (steps, min(len(L), batch_edges)), device=dev, generator=gen)
              if L is not None else None)
        lw = float(self.landmark_weight)
        rep = self.negative_rate

        def loss_of(h, t_, ng, li):
            Z = self.net(Xt)
            zi, zj = Z.index_select(0, h), Z.index_select(0, t_)
            d2 = ((zi - zj) ** 2).sum(1) + 1e-6
            attract = torch.log1p(a * d2 ** b).mean()
            d2n = ((zi.repeat_interleave(rep, 0) - Z.index_select(0, ng)) ** 2).sum(1) + 1e-3
            un = a * d2n ** b
            loss = attract + (torch.log1p(un) - torch.log(un)).mean()
            if li is not None:
                loss = loss + lw * ((Z.index_select(0, li + m) - L.index_select(0, li)) ** 2).sum(1).mean()
            return loss

        self.net.train()
        t = time.perf_counter()
        done = 0
        graphed = False
        if cuda and steps >= 8 and use_graph:
            # One optimiser step as a CUDA graph, replayed: the step is ~40
            # tiny kernels and, eager, the launches were the cost (5.6 ms a
            # step against 0.2 ms of arithmetic). The first three steps run
            # eagerly on a side stream as torch's capture recipe requires,
            # and are real steps.
            try:
                sh, st_, sn = Hs[0].clone(), Ts[0].clone(), NEG[0].clone()
                sl = LI[0].clone() if LI is not None else None
                side = torch.cuda.Stream()
                side.wait_stream(torch.cuda.current_stream())
                with torch.cuda.stream(side):
                    for done in range(3):
                        opt.zero_grad(set_to_none=True)
                        loss_of(Hs[done], Ts[done], NEG[done], LI[done] if LI is not None else None).backward()
                        opt.step()
                    done = 3
                torch.cuda.current_stream().wait_stream(side)
                g = torch.cuda.CUDAGraph()
                opt.zero_grad(set_to_none=True)
                with torch.cuda.graph(g):
                    loss_of(sh, st_, sn, sl).backward()
                    opt.step()
                for done in range(3, steps):
                    sh.copy_(Hs[done]); st_.copy_(Ts[done]); sn.copy_(NEG[done])
                    if sl is not None:
                        sl.copy_(LI[done])
                    g.replay()
                done = steps
                graphed = True
            except Exception as exc:                 # noqa: BLE001
                self.stats["graph_error"] = "%s: %s" % (type(exc).__name__, exc)
        for s_ in range(done, steps):
            opt.zero_grad(set_to_none=True)
            loss_of(Hs[s_], Ts[s_], NEG[s_], LI[s_] if LI is not None else None).backward()
            opt.step()
        if dev.type == "cuda":
            torch.cuda.synchronize()
        ms_train = (time.perf_counter() - t) * 1000
        t = time.perf_counter()
        self.embedding_[idx] = self.transform(self._raw[idx])
        drift = None
        if measure_drift and len(held):
            now = self.transform(self._raw[held])
            drift = np.linalg.norm(now[:, :3] - self.embedding_[held][:, :3], axis=1)
        self.stats.update({
            "rows": int(self._alive.sum()), "update_s": round(time.perf_counter() - started, 3),
            "update_rows": int(m), "trained_rows": int(n), "landmarks": int(len(picked)),
            "steps": int(steps), "graphed": graphed, "ms_select": round(ms_select, 1), "ms_graph": round(ms_graph, 1),
            "ms_train": round(ms_train, 1),
            "ms_place": round((time.perf_counter() - t) * 1000, 1),
            "held_drift_p50": float(np.median(drift)) if drift is not None and len(drift) else None,
            "held_drift_p90": float(np.percentile(drift, 90)) if drift is not None and len(drift) else None,
            "held_drift_max": float(drift.max()) if drift is not None and len(drift) else None})
        return self.embedding_[idx]

    # -- persistence ---------------------------------------------------------
    def __getstate__(self):
        state = dict(self.__dict__)
        if self.net is not None:
            state["net"] = {k: v.detach().cpu() for k, v in self.net.state_dict().items()}
        return state

    def __setstate__(self, state):
        weights = state.pop("net", None)
        self.__dict__.update(state)
        self.net = None
        if weights is not None and self.dim_in:
            self._build(self.dim_in)
            self.net.load_state_dict(weights)


class Whitened:
    """A fitted model whose first `dims` outputs are decorrelated and scaled.

    The parametric page layout came out as a narrow diagonal RIBBON (2026-09-27,
    screenshot): its three drawn axes were correlated, so per-axis spreading
    evened each axis and kept the diagonal -- 34% of page discs overlapping on
    screen. A PCA rotation and per-axis scale of the drawn dimensions, fitted
    ONCE on the first fit and replayed for every later point (and after every
    online update), fills the volume without moving anything relative to
    anything else in a way a refit would.
    """

    def __init__(self, model, dims: int = 3) -> None:
        self.model = model
        self.dims = dims
        self.mean = None
        self.W = None

    def fit_whitening(self, Y: np.ndarray) -> np.ndarray:
        head = np.asarray(Y[:, :self.dims], dtype=np.float64)
        self.mean = head.mean(axis=0)
        cov = np.cov((head - self.mean).T)
        vals, vecs = np.linalg.eigh(cov)
        # PARTIAL: axes scaled by variance^(-1/4), not ^(-1/2). Full whitening
        # turned the ribbon into a structureless cloud ("scattered", the user,
        # 2026-09-27) and magnified the weakest axis (0.9% of the variance)
        # ~10x, so a landmark update's tiny drift there read as 8.5% movement.
        self.W = vecs / np.maximum(vals, 1e-9) ** 0.25
        return self.apply(Y)

    def apply(self, Y: np.ndarray) -> np.ndarray:
        Y = np.asarray(Y, dtype=np.float32).copy()
        if self.W is not None:
            Y[:, :self.dims] = ((Y[:, :self.dims] - self.mean) @ self.W).astype(np.float32)
        return Y

    def transform(self, X: np.ndarray) -> np.ndarray:
        return self.apply(self.model.transform(X))
