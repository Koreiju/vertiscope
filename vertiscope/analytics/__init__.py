"""Analytics for the affine map, kept apart from the REPL.

The REPL is the browser; this is the instrument that measures it. They are
separate packages because a measurement that lives inside the thing it
measures cannot be re-read after that thing changes, and because the goal
(docs/AFFINE_MAP_GOAL.md) requires the analytics to be their own artifacts.

Everything here is scored through the patricia trie, which is the universal
link structure joining the REPL's data-structure interfaces to the page:
the sensor writes addressed units into it, both projections are read out of
it, and every arrow measured is one of those crossings.
"""

from .affine import (AffineReport, ArrowScore, Confusion, DedupScore,
                     score_arrow, score_dedup)
from .groundtruth import PageTruth, PageUnit, read_page_truth
from .run import measure_page, render_table, write_artifact

__all__ = ["AffineReport", "ArrowScore", "Confusion", "DedupScore",
           "PageTruth", "PageUnit", "measure_page", "read_page_truth",
           "render_table", "score_arrow", "score_dedup", "write_artifact"]
