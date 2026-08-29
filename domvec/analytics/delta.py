"""What one mutation costs, against the size of the document it lands in.

This is the central claim of the design stated as a measurement: **inserting a
single node costs work proportional to the insertion, not to the page.** It is
a property of the write side of the patricia trie -- `AddressTrie.apply` is the
live path's only mutator -- and it is only observable against a *varying* N. A
single page showing a small delta says nothing about whether it stays small.

Insertion at the **head** of a list is the adversarial position on purpose. It
shifts the positional address of every following sibling, so a scheme keying
identity on position re-points all N and reports N+1 changes for one node
arriving. `TrieNode.uid` is what survives that: `apply` re-anchors by content
hash, so the arrival is one `added` and the shifted siblings are `moved` --
"the same fact, re-placed" -- rather than N edits.

Three numbers, and they answer different questions:

  ``added/removed/changed``  genuine change. Should be 1 for one insertion,
                             at every N. If this grows with N the map is not
                             compositional and the trie is re-deriving the
                             document rather than editing it.
  ``moved``                  addresses re-pointed by the shift. Expected to
                             grow with N -- the addresses genuinely did move --
                             but a move is not a re-vectorisation, which is
                             why the two are counted apart.
  ``visited``                nodes actually compared. The *cost*, as opposed
                             to the result. This is what must not scale.

Reported per N so the shape is visible rather than asserted. A constant
`size` with a growing `visited` is still a failure of the claim, and one that
a delta count alone would hide.
"""

from __future__ import annotations

import json
import pathlib
import statistics
import time
from typing import Dict, List, Optional, Sequence

__all__ = ["measure_delta_scaling", "render_delta_table", "FIXTURE"]

FIXTURE = (pathlib.Path(__file__).resolve().parent.parent.parent
           / "tests" / "fixtures" / "delta_scaling.html")


def _settle(sensor, spine, passes: int = 3):
    """Drain until the fold has nothing left to say about the initial page."""
    last = None
    for passno in range(passes):
        snapshot = sensor.drain(passno)
        last = spine.absorb(snapshot.units, snapshot.passno,
                            removed=snapshot.removed_addresses,
                            moved=snapshot.moved_addresses)
        time.sleep(0.15)
    return last


def measure_delta_scaling(driver, *, sizes: Sequence[int] = (100, 400, 1600),
                          repeats: int = 3,
                          context_window: int = 1200) -> dict:
    """Insert one node at the head of an N-item list, for several N.

    Uses a local fixture so N is a parameter and nothing varies but N: a live
    page cannot be resized, and comparing two different live pages confounds
    size with everything else about them.
    """
    from ..sensing import Sensor
    from ..stream import StreamingScan

    rows: List[dict] = []
    for n in sizes:
        url = f"{FIXTURE.as_uri()}#{n}"
        for trial in range(max(1, repeats)):
            # A hash-only change is a *same-document* navigation: the browser
            # does not reload and the build script never re-runs, so every N
            # after the first measured whatever the previous one left behind.
            # Read as 102 / 105 / 108 leaves for N of 100 / 400 / 1600, which
            # is the fixture never being rebuilt rather than the trie holding
            # a hundred items for a page of sixteen hundred.
            driver.get("about:blank")
            driver.get(url)
            time.sleep(0.5)
            sensor = Sensor(driver, url, budget=context_window)
            sensor.boot()
            time.sleep(0.4)
            spine = StreamingScan(url, context_window=context_window)
            _settle(sensor, spine)
            before = {leaf.uid for leaf in spine.trie.leaves()} \
                if spine.trie else set()
            baseline_leaves = len(before)

            # Prime the render memo on the settled page, and time that first
            # render: it is the honest cost of drawing a page from cold, and
            # the denominator the incremental figure is claimed against.
            from ..markdown import RenderMemo, render_trie
            memo = RenderMemo()
            started_cold = time.perf_counter()
            render_trie(spine.trie, context_window=context_window, memo=memo)
            markdown_cold_ms = (time.perf_counter() - started_cold) * 1000.0
            primed = memo.reused_lines

            # The mutation under test. One node, at the position that shifts
            # every address after it.
            driver.execute_script("return window.__insertHead(arguments[0]);",
                                  f"{n}-{trial}")
            time.sleep(0.35)

            snapshot = sensor.drain(99)
            fold_ms = (snapshot.stats or {}).get("repairMs")
            started = time.perf_counter()
            update = spine.absorb(snapshot.units, snapshot.passno,
                                  removed=snapshot.removed_addresses,
                                  moved=snapshot.moved_addresses)
            apply_ms = (time.perf_counter() - started) * 1000.0

            # The projections, timed after the same one-node insertion.
            #
            # The trie is O(delta) by construction; the projections are read
            # back out of it wholesale, so this is where an O(page) cost would
            # hide behind an O(delta) claim.
            #
            # Both are timed, on the same trie, in this order:
            #
            #   markdown_incr_ms  -- with the memo primed on the pre-insert
            #                        page, which is what the live path does
            #   markdown_ms       -- with no memo at all, the old cost, kept
            #                        as the control the claim is made against
            #
            # The ratio between them is the result. Reporting only the
            # incremental figure would say nothing: what matters is how it
            # moves with N against a cost known to be O(page).
            started_incr = time.perf_counter()
            chunks = render_trie(spine.trie, context_window=context_window,
                                 memo=memo)
            markdown_incr_ms = (time.perf_counter() - started_incr) * 1000.0
            md_reused_lines = memo.reused_lines - primed

            started_md = time.perf_counter()
            control = render_trie(spine.trie, context_window=context_window)
            markdown_ms = (time.perf_counter() - started_md) * 1000.0
            md_lines = sum(len(c.lines) for c in chunks)

            # A memo is only worth timing if it draws the same page.
            md_identical = (
                [(c.cid, c.markdown) for c in chunks]
                == [(c.cid, c.markdown) for c in control]
            )

            delta = update.delta
            after = {leaf.uid for leaf in spine.trie.leaves()} \
                if spine.trie else set()
            rows.append({
                "n": n,
                "trial": trial,
                "leaves_before": baseline_leaves,
                "units_in": len(snapshot.units),
                "added": len(delta.added),
                "removed": len(delta.removed),
                "changed": len(delta.changed),
                "moved": len(delta.moved),
                "size": delta.size,
                "touched": delta.touched,
                "visited": delta.visited,
                # Identity survival: the uids present before must still be
                # present after. A shift that re-mints identities is exactly
                # the failure `uid` exists to prevent.
                "uids_kept": len(before & after),
                "uids_lost": len(before - after),
                "apply_ms": apply_ms,
                # What the shift cost to carry. The fold re-emits every
                # chunk whose path moved, so this is where an O(page)
                # payload would show up even when the delta is O(1).
                "wire_bytes": int(snapshot.wire_bytes or 0),
                "decode_ms": float(snapshot.decode_ms or 0.0),
                "markdown_ms": markdown_ms,
                "markdown_incr_ms": markdown_incr_ms,
                "markdown_cold_ms": markdown_cold_ms,
                "md_reused_lines": md_reused_lines,
                "md_identical": md_identical,
                "md_lines": md_lines,
                "fold_ms": float(fold_ms) if isinstance(
                    fold_ms, (int, float)) else None,
            })
    return {"sizes": list(sizes), "repeats": repeats, "rows": rows,
            "t": time.time()}


def _median(values: Sequence[float]) -> float:
    live = [v for v in values if v is not None]
    return statistics.median(live) if live else 0.0


def render_delta_table(report: dict) -> str:
    rows = report["rows"]
    by_n: Dict[int, List[dict]] = {}
    for row in rows:
        by_n.setdefault(row["n"], []).append(row)

    out = ["", "  one insertion at the head of an N-item list", ""]
    out.append(f"  {'N':>6}{'leaves':>9}{'size':>7}{'moved':>8}{'visited':>9}"
               f"{'uids lost':>11}{'apply ms':>10}{'fold ms':>9}"
               f"{'wire KB':>9}{'decode':>8}{'md full':>9}{'md incr':>9}{'reused':>8}")
    for n in sorted(by_n):
        group = by_n[n]
        out.append(
            f"  {n:>6}{_median([r['leaves_before'] for r in group]):>9.0f}"
            f"{_median([r['size'] for r in group]):>7.0f}"
            f"{_median([r['moved'] for r in group]):>8.0f}"
            f"{_median([r['visited'] for r in group]):>9.0f}"
            f"{_median([r['uids_lost'] for r in group]):>11.0f}"
            f"{_median([r['apply_ms'] for r in group]):>10.2f}"
            f"{_median([r['fold_ms'] for r in group]):>9.1f}"
            f"{_median([r['wire_bytes'] for r in group]) / 1024:>9.1f}"
            f"{_median([r['decode_ms'] for r in group]):>8.1f}"
            f"{_median([r['markdown_ms'] for r in group]):>9.1f}"
            f"{_median([r['markdown_incr_ms'] for r in group]):>9.1f}"
            f"{_median([r['md_reused_lines'] for r in group]):>8.0f}")
    out.append("")
    wrong = [r for r in rows if not r.get("md_identical", True)]
    if wrong:
        # The incremental column is meaningless unless it drew the same page,
        # so a mismatch is reported here rather than left to a test elsewhere.
        out.append(f"  ** memoised render disagreed with the control on "
                   f"{len(wrong)} of {len(rows)} trials **")
    sizes = sorted(by_n)
    if len(sizes) >= 2:
        small, large = sizes[0], sizes[-1]
        s_size = _median([r["size"] for r in by_n[small]])
        l_size = _median([r["size"] for r in by_n[large]])
        s_vis = _median([r["visited"] for r in by_n[small]])
        l_vis = _median([r["visited"] for r in by_n[large]])
        growth = (large / small) if small else 0.0
        out.append(f"  page grew {growth:.0f}x   "
                   f"genuine change {s_size:.0f} -> {l_size:.0f}   "
                   f"nodes compared {s_vis:.0f} -> {l_vis:.0f}")
        out.append("")
        out.append("  O(delta) holds when `size` stays flat AND `visited`")
        out.append("  does not scale with the page. `moved` may grow: those")
        out.append("  addresses genuinely moved, and a move is not an edit.")
    out.append("")
    return "\n".join(out)


def write_delta_artifact(report: dict,
                         directory: Optional[pathlib.Path] = None
                         ) -> pathlib.Path:
    directory = pathlib.Path(directory or "build_analytics")
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "delta_scaling.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(report, separators=(",", ":")) + "\n")
    return path
