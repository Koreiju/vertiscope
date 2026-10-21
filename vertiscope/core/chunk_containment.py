"""
chunk_containment.py — drop chunks whose xpath is a strict ancestor
of another chunk's xpath.

The chunker (backend/mapper/chunk_builder.py) walks bottom-up from
each content-bearing leaf until it either exceeds the char budget or
hits an "instance boundary" (the leaf's generalized pattern appears
more than once under the candidate frontier). Occasionally a seed
leaf belongs to a pattern that never repeats on its walk-up path, so
the walk steps all the way past the legitimate card/item boundary
and lands on a huge container that swallows every sibling card that
another walk already covered with a finer-grained chunk.

Empirically on a tarot.com love-reading index page we observed::

    #1 59235 bytes at /html/body/main/div/div/div[2]/div/div[2]   (MONSTER)
    #2  7673 bytes at /html/body/main/div/div/div[2]/div/div[1]
    #3..#22 ~2400 bytes each at
            /html/body/main/div/div/div[2]/div/div[2]/ul/li[i]/row/column[2]

The 59 KB monster is a strict xpath ancestor of the 20 per-card
chunks and contributes only redundant, context-exploding rollup.
Dropping it leaves the fine-grained per-card chunks intact.

This module exposes two pure helpers, :func:`is_ancestor_xpath` and
:func:`filter_redundant_rollups`. The filter is generic over any row
shape that carries an xpath — pass it ``ChunkInstanceRow`` lists for
the 3D projector fit, :class:`InstanceHit` lists for search
retrieval, and :class:`Chunk` lists for post-build persistence, so
all three stay consistent.
"""

from __future__ import annotations

import logging
from typing import Callable, List, Optional, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


def is_ancestor_xpath(ancestor: str, descendant: str) -> bool:
    """True when ``ancestor`` is a strict path prefix of ``descendant``.

    Absolute xpaths are compared as ``/``-delimited strings. The
    "strict" part matters — identical xpaths are not ancestors of one
    another. The ``+ "/"`` boundary guard avoids ``/html/body/div``
    masquerading as an ancestor of ``/html/body/divider/...``.
    """
    if not ancestor or not descendant:
        return False
    if ancestor == descendant:
        return False
    if len(ancestor) >= len(descendant):
        return False
    return descendant.startswith(ancestor + "/")


def filter_redundant_rollups(
    items: List[T],
    *,
    xpath_of: Callable[[T], str],
    size_of: Optional[Callable[[T], int]] = None,
    min_rollup_size: int = 0,
) -> List[T]:
    """Drop items whose xpath is a strict ancestor of another item's xpath.

    The caller supplies ``xpath_of`` so this works on any row-shape —
    ``ChunkInstanceRow``, :class:`~vertiscope.core.chunk_retrieval.InstanceHit`,
    projector node dicts, or :class:`~vertiscope.core.chunk_builder.Chunk`.
    Input order is preserved for the survivors.

    Size gate (important for not eating legitimate coarse chunks):
        When ``size_of`` is provided, an ancestor is dropped **only if**
        its size is strictly greater than ``min_rollup_size``. In
        practice we set ``min_rollup_size`` to the chunker's hard
        char ceiling — so a 400-char card chunk containing a 200-char
        title chunk is NOT pruned (both are legitimate finer/coarser
        views under budget), but the 59 KB monster rollup that
        empirically triggered this whole pass IS pruned. The default
        of 0 preserves the original "always drop ancestors" behavior.

    Implementation: sort indices by xpath lex order (ancestors precede
    descendants), then for each sorted xpath do a bounded forward scan
    checking whether any later xpath shares its prefix + ``/``. Worst
    case O(N log N + N·max_family_size); for realistic N (<1000) this
    is effectively linear.
    """
    if len(items) < 2:
        return list(items)

    paired = sorted(
        enumerate(items),
        key=lambda t: xpath_of(t[1]) or "",
    )

    drop_idx: set[int] = set()
    for ord_pos, (orig_idx, item) in enumerate(paired):
        xp = xpath_of(item) or ""
        if not xp:
            continue
        # Size gate: protect small / card-sized chunks from accidentally
        # being pruned just because they happen to have a deeper
        # finer-grained chunk under them. Only oversized rollups qualify.
        if size_of is not None:
            try:
                sz = int(size_of(item) or 0)
            except Exception:
                sz = 0
            if sz <= min_rollup_size:
                continue
        # Scan forward: sorted order guarantees every strict descendant
        # appears somewhere after us and starts with ``xp``. We bail as
        # soon as the shared-prefix family ends.
        for _, other in paired[ord_pos + 1:]:
            other_xp = xpath_of(other) or ""
            if not other_xp.startswith(xp):
                break  # left the prefix family, no more candidates.
            if is_ancestor_xpath(xp, other_xp):
                drop_idx.add(orig_idx)
                break

    if not drop_idx:
        return list(items)

    survivors = [it for idx, it in enumerate(items) if idx not in drop_idx]
    logger.info(
        "chunk containment: dropped %d strict-ancestor rollup chunk(s) "
        "from %d input(s) → %d survivors",
        len(drop_idx), len(items), len(survivors),
    )
    return survivors
