"""What the online UMAP trains on: every chunk, or page centroids (G-106).

The user's words (2026-09-28): "Depending on GPU runtimes, perhaps update with
the full set of chunks, or just the centroided pages, or the former for few
pages and the latter for tens to hundreds." So the scope is decided by what an
`update()` COSTS on this GPU, not by a page count.

`ParametricUMAP.update` trains on every row it has ever trained on (the old
ones pulled back to where they were), so the scope sets the cost of every
later update, not just the next one. Measured 2026-09-28 on this machine
(RTX 4070 laptop, 768-d vectors, an update of 10 new rows):

    rows trained   160    500    1,000   2,000
    update()       1.5 s  2.7 s  6.6 s   15.9 s

The working store (159 pages, 16,189 chunks) is page scope by a wide margin;
a fresh store of a dozen pages and a few hundred chunks is chunk scope.

Pure: no torch, no store -- the decision is unit-testable with planted
budgets, and the projector feeds the cost model what its GPU actually took.
"""

from typing import Dict, List, Optional, Tuple

#: The curve above, as (rows, ms). The cost model starts here and is replaced
#: by this machine's own updates as they happen.
SEED_CURVE: Tuple[Tuple[int, float], ...] = ((160, 1510.0), (500, 2730.0),
                                             (1000, 6580.0), (2000, 15850.0))

#: `pumap._train` runs the whole set forward per step up to this many rows and
#: samples batches beyond it, where the cost per row jumps. No interactive
#: budget reaches past it, so chunk scope stops here whatever the line says.
WHOLE_FORWARD_ROWS = 8192


class RefitCost:
    """Milliseconds an online `update()` takes, as a function of rows trained."""

    def __init__(self) -> None:
        self.observed: List[Tuple[int, float]] = []

    def observe(self, rows: int, ms: float) -> None:
        if rows > 0 and ms > 0:
            self.observed.append((int(rows), float(ms)))
            del self.observed[:-40]

    @property
    def seeded(self) -> bool:
        """True while the prediction still rests on the 2026-09-28 curve."""
        return len({r for r, _ms in self.observed}) < 2

    def _line(self) -> Tuple[float, float]:
        pts = list(SEED_CURVE) if self.seeded else self.observed
        n = len(pts)
        mx = sum(r for r, _ in pts) / n
        my = sum(m for _, m in pts) / n
        sxx = sum((r - mx) ** 2 for r, _ in pts)
        slope = (sum((r - mx) * (m - my) for r, m in pts) / sxx) if sxx else 0.0
        slope = max(slope, 0.0)
        return my - slope * mx, slope

    def predict(self, rows: int) -> float:
        base, per_row = self._line()
        return max(0.0, base + per_row * rows)

    def summary(self) -> Dict:
        base, per_row = self._line()
        return {"seeded": self.seeded, "base_ms": round(base, 1),
                "ms_per_row": round(per_row, 3), "observed": self.observed[-8:]}


def choose_scope(page_rows: int, chunk_rows: int, cost: RefitCost, budget_ms: float,
                 engine: str = "parametric", centroid: str = "semantic",
                 want_global: bool = False) -> Dict:
    """Chunks when an update over pages AND chunks fits the budget, pages when
    it does not -- and why, in words a reader of the status can check.

    `want_global` (VERTISCOPE_UMAP_SCOPE=global, 2026-10-04): one model over every
    chunk whose update trains only the changed page's rows plus a bounded
    landmark sample (`pumap.ParametricUMAP.update_subset`). Its cost does not
    grow with the rows, so neither the budget nor `WHOLE_FORWARD_ROWS` applies;
    it still needs the parametric engine and a centroid chunks can join."""
    rows = page_rows + chunk_rows
    predicted = cost.predict(rows)
    out = {"rows_if_chunks": rows, "rows_if_pages": page_rows,
           "predicted_ms": round(predicted, 1),
           "predicted_pages_ms": round(cost.predict(page_rows), 1),
           "budget_ms": float(budget_ms), "cost": cost.summary()}
    if engine != "parametric":
        return dict(out, scope="pages", why="umap-learn cannot update(); refits are whole, over pages")
    if centroid != "semantic":
        return dict(out, scope="pages", why="the triple centroid has no chunk-vector counterpart")
    if want_global:
        return dict(out, scope="global",
                    why="one model over %d pages + %d chunks; an update trains the changed page's "
                        "rows and a bounded landmark sample, not the corpus" % (page_rows, chunk_rows))
    if rows > WHOLE_FORWARD_ROWS:
        return dict(out, scope="pages",
                    why="%d rows is past the %d the trainer runs whole; per-row cost jumps there"
                        % (rows, WHOLE_FORWARD_ROWS))
    if predicted <= budget_ms:
        return dict(out, scope="chunks",
                    why="an update over %d pages + %d chunks is predicted at %.0f ms, within %.0f"
                        % (page_rows, chunk_rows, predicted, budget_ms))
    return dict(out, scope="pages",
                why="an update over %d pages + %d chunks is predicted at %.0f ms, over %.0f"
                    % (page_rows, chunk_rows, predicted, budget_ms))
