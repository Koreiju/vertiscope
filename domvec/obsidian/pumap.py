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
        from umap.umap_ import fuzzy_simplicial_set
        from sklearn.utils import check_random_state
        k = int(max(2, min(self.n_neighbors, len(X) - 1)))
        graph, _s, _r = fuzzy_simplicial_set(
            X, k, check_random_state(self.seed), "euclidean")
        graph = graph.tocoo()
        keep = graph.data > graph.data.max() / 200.0   # as umap drops weak edges
        return graph.row[keep], graph.col[keep], graph.data[keep]

    # -- training ------------------------------------------------------------
    def _train(self, X: np.ndarray, epochs: int, landmarks: Optional[np.ndarray] = None) -> float:
        """UMAP cross-entropy by edge sampling (+ a landmark pull on the first
        `len(landmarks)` rows). Returns the wall time."""
        import torch
        dev = _device()
        started = time.perf_counter()
        head, tail, w = self._graph(X)
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
        for _epoch in range(epochs):
            for _s in range(steps_per_epoch):
                e = torch.multinomial(p, self.batch_edges, replacement=True, generator=g)
                zi = self.net(Xt[H[e]])
                zj = self.net(Xt[T[e]])
                # UMAP's cross-entropy in its stable log form. With
                # u = a * d^(2b):  -log q = log1p(u);  -log(1-q) = log1p(u) - log(u).
                # Clamping q (the first version) zeroed the repulsion's gradient
                # once points met, and every page collapsed onto one point
                # (spacing 0.00, trustworthiness 0.535, 2026-09-27).
                d2 = ((zi - zj) ** 2).sum(1) + 1e-6
                u = a * d2 ** b
                attract = torch.log1p(u).mean()
                neg = torch.randint(0, n, (self.batch_edges * self.negative_rate,), device=dev, generator=g)
                zn = self.net(Xt[neg])
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
                    loss = loss + self.landmark_weight * ((self.net(Xt[idx]) - L[idx]) ** 2).sum(1).mean()
                opt.zero_grad()
                loss.backward()
                opt.step()
        if dev.type == "cuda":
            torch.cuda.synchronize()
        return time.perf_counter() - started

    def fit(self, X: np.ndarray) -> "ParametricUMAP":
        X = np.asarray(X, dtype=np.float32)
        self._build(X.shape[1])
        secs = self._train(X, self.epochs)
        self._raw = X
        self.embedding_ = self.transform(X)
        self.stats = {"rows": len(X), "fit_s": round(secs, 3), "device": str(_device())}
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
        self.W = vecs / np.sqrt(np.maximum(vals, 1e-9))
        return self.apply(Y)

    def apply(self, Y: np.ndarray) -> np.ndarray:
        Y = np.asarray(Y, dtype=np.float32).copy()
        if self.W is not None:
            Y[:, :self.dims] = ((Y[:, :self.dims] - self.mean) @ self.W).astype(np.float32)
        return Y

    def transform(self, X: np.ndarray) -> np.ndarray:
        return self.apply(self.model.transform(X))
