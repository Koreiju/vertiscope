"""What a change to the trie costs the projection read out of it.

The trie applies a mutation in O(delta) and the markdown is read back out of
it. If that read is O(page), the pair is O(page) and the O(delta) claim is
about a component rather than about the sensor, which is not the claim worth
making.

This measures the read, not the fold. It is deliberately browser-free: the
question is how render cost moves with page size and with the *kind* of
change, and a live page cannot be resized or edited in a controlled way. The
live counterpart -- what a real insertion costs end to end, drain included --
is `delta.py`, which uses a fixture in a real browser.

Three mutation classes, because they are not the same problem:

``redraw``
    Nothing changed. This is what an idle tick and a scroll cost, and on an
    interactive surface it is the common case by a wide margin.

``edit``
    One value changed, in place. Every address is where it was; one leaf and
    its ancestors are stale.

``insert``
    One node at the head of the list, which shifts the address of everything
    below it. The worst case for reuse *keyed by address*, and it is worth
    stating why that is not a defect: the trie keeps identity across the shift
    (`uid`), but the projection prints addresses -- a chunk's xpath, a line's
    anchor -- so a subtree that moved genuinely renders differently and has to
    be re-derived. An address-keyed memo cannot reuse it, and a memo that did
    would be wrong.

Every trial checks the memoised render against an unmemoised one and records
``identical``. A speed column means nothing without it.
"""

from __future__ import annotations

import json
import pathlib
import time
from typing import Dict, List, Sequence

DEFAULT_ARTIFACT_DIR = pathlib.Path("build_analytics")


def _page(n: int, *, edit: int = -1, head: bool = False) -> str:
    """An N-row list. One knob per mutation class, nothing else varies."""
    def body(i: int) -> str:
        return ("an edited body for row {}".format(i) if i == edit
                else "body text for row {} here".format(i))

    start = -1 if head else 0
    rows = "".join(
        '<li class="row"><h3>Item {}</h3><p>{}</p>'
        '<a href="https://example.test/{}">open {}</a></li>'.format(
            i, body(i), i, i)
        for i in range(start, n)
    )
    return (
        "<html><body><header><h1>Catalogue</h1></header>"
        "<main><ul>{}</ul></main>"
        "<footer><p>end of list</p></footer></body></html>"
    ).format(rows)


def _mutate(n: int, kind: str) -> str:
    if kind == "redraw":
        return _page(n)
    if kind == "edit":
        return _page(n, edit=n // 2)
    if kind == "insert":
        return _page(n, head=True)
    raise ValueError(kind)


KINDS = ("redraw", "edit", "insert")


def measure_projection_scaling(
    *,
    sizes: Sequence[int] = (100, 400, 1600),
    kinds: Sequence[str] = KINDS,
    repeats: int = 3,
    context_window: int = 1200,
) -> dict:
    """Render an N-row page, mutate it, and time the second render two ways.

    The memoised render runs first, on a memo primed by the first render --
    which is what the live path holds. The control runs second with no memo at
    all, on the same trie. Ordering them the other way would let the control
    warm every cache the memoised run then benefits from.
    """
    from ..markdown import RenderMemo, render_trie
    from ..stream import StreamingScan

    rows: List[dict] = []
    for n in sizes:
        for kind in kinds:
            for trial in range(max(1, repeats)):
                scan = StreamingScan("https://projection.test/page",
                                     context_window=context_window)
                memo = RenderMemo()

                started = time.perf_counter()
                scan.push(_page(n), passno=0)
                build_ms = (time.perf_counter() - started) * 1000.0

                started = time.perf_counter()
                render_trie(scan.trie, context_window=context_window,
                            memo=memo)
                cold_ms = (time.perf_counter() - started) * 1000.0
                primed = memo.reused_lines

                started = time.perf_counter()
                update = scan.push(_mutate(n, kind), passno=1)
                apply_ms = (time.perf_counter() - started) * 1000.0

                started = time.perf_counter()
                incr = render_trie(scan.trie, context_window=context_window,
                                   memo=memo)
                incr_ms = (time.perf_counter() - started) * 1000.0
                reused = memo.reused_lines - primed

                started = time.perf_counter()
                control = render_trie(scan.trie,
                                      context_window=context_window)
                full_ms = (time.perf_counter() - started) * 1000.0

                identical = (
                    [(c.cid, c.markdown) for c in incr]
                    == [(c.cid, c.markdown) for c in control]
                )
                rows.append({
                    "n": n,
                    "kind": kind,
                    "trial": trial,
                    "leaves": len(scan.trie) if scan.trie else 0,
                    "lines": sum(len(c.lines) for c in incr),
                    "chunks": len(incr),
                    "delta_size": update.delta.size,
                    "delta_moved": len(update.delta.moved),
                    "build_ms": build_ms,
                    "apply_ms": apply_ms,
                    "cold_ms": cold_ms,
                    "incr_ms": incr_ms,
                    "full_ms": full_ms,
                    "reused_lines": reused,
                    "identical": identical,
                })
    return {"sizes": list(sizes), "kinds": list(kinds), "repeats": repeats,
            "context_window": context_window, "rows": rows, "t": time.time()}


def _median(values: Sequence[float]) -> float:
    ordered = sorted(v for v in values if v is not None)
    if not ordered:
        return 0.0
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return float(ordered[mid])
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def render_projection_table(report: dict) -> str:
    rows = report.get("rows", [])
    if not rows:
        return "  no projection measurements"

    grouped: Dict[tuple, List[dict]] = {}
    for row in rows:
        grouped.setdefault((row["kind"], row["n"]), []).append(row)

    out = ["", "  what one change costs the markdown projection", ""]
    out.append("  {:>8}{:>7}{:>8}{:>9}{:>10}{:>10}{:>9}{:>9}  {}".format(
        "change", "N", "lines", "delta", "full ms", "incr ms", "saved",
        "reused", "same"))
    for kind in report.get("kinds", KINDS):
        for n in report.get("sizes", []):
            group = grouped.get((kind, n))
            if not group:
                continue
            full = _median([r["full_ms"] for r in group])
            incr = _median([r["incr_ms"] for r in group])
            out.append("  {:>8}{:>7}{:>8.0f}{:>9.0f}{:>10.1f}{:>10.1f}"
                       "{:>8.0f}%{:>9.0f}  {}".format(
                           kind, n,
                           _median([r["lines"] for r in group]),
                           _median([r["delta_size"] for r in group]),
                           full, incr,
                           (1.0 - incr / full) * 100.0 if full else 0.0,
                           _median([r["reused_lines"] for r in group]),
                           all(r["identical"] for r in group)))
        out.append("")

    wrong = [r for r in rows if not r["identical"]]
    if wrong:
        # A saving that draws a different page is not a saving.
        out.append("  ** the memoised render disagreed with the control on "
                   "{} of {} trials **".format(len(wrong), len(rows)))
        out.append("")

    out.append("  `saved` is against a render with no memo at all, on the same")
    out.append("  trie. `reused` counts lines served from the memo, including")
    out.append("  the speculative fit tests, so it exceeds `lines` on any page")
    out.append("  that nests -- an ancestor asks about a render that contains")
    out.append("  its descendants.")
    out.append("")
    out.append("  What the numbers say, and do not say. A redraw is cheap")
    out.append("  because the page root is clean and one lookup answers for")
    out.append("  the whole page. An edit is not, because the ancestors of the")
    out.append("  edited leaf reach the root, and the descent asks each of")
    out.append("  them whether its subtree fits the window -- a question")
    out.append("  currently answered by rendering it. That residual is O(page)")
    out.append("  per change and is the next thing to remove.")
    out.append("  An insertion at the head is the floor: it shifts every")
    out.append("  address below it, and a projection that prints addresses")
    out.append("  has to re-derive what moved. Its `delta` column reads as the")
    out.append("  whole page here because this harness pushes html rather than")
    out.append("  a sensor drain, so there is no move channel to tell the trie")
    out.append("  those addresses carried their content with them. `delta.py`")
    out.append("  measures the same insertion with the channel, where it reads")
    out.append("  as one change and N moves.")
    return "\n".join(out)


def write_projection_artifact(
    report: dict, out_dir: pathlib.Path = DEFAULT_ARTIFACT_DIR
) -> pathlib.Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "projection_scaling.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        for row in report.get("rows", []):
            record = dict(row)
            record["t"] = report.get("t")
            record["context_window"] = report.get("context_window")
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    return path
