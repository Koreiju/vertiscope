"""What a page does when nothing is done to it.

Every drift score is a difference between two maps of one document, and it is
only a statement about the sensor if the document held still while they were
taken. Twice now it did not, and both times the residue was read as a sensor
defect first:

* coinmarketcap scored 10 wrong values under `delete`, and 10 under no
  mutation at all -- a frozen snapshot still running a price ticker.
* `www.w3schools.com/html/html_forms.asp` scored 9 stale and 4 wrong, every
  one of them at `/html/iframe[N]` holding an ad-sync beacon URL. Its own
  scripts append and recycle those iframes on `<html>` continuously.

Neither was found by reasoning about the fold. Both were found by measuring
the page alone, which is what this module does and why it is separate from
`drift`: the floor is a property of the document, not of a gesture, and it has
to be measurable without one.

The measurement takes no sensor at all. Two independent truth maps of the same
live page, `settle` seconds apart, each a full walk by a freshly booted
reader. Their disagreement is the page moving, because nothing else is in the
room -- no incremental path, no mutation, no cached state carried between
them. That is the cleanest form the evidence can take, and it is why this is
worth a browser rather than an argument.

What it gives the rest of the analytics is a **resolution limit**: a page
whose floor is 8 addresses cannot evidence a 4-address defect, in either
direction. A residue at or below the floor is indistinguishable from the
page's own motion and must not be reported as a defect; a corpus total that
sums residues across pages without their floors is summing signal and noise
and calling it accuracy.

It also partitions the corpus, which is the more useful product. Pages with a
zero floor are where exactness can be claimed at all; the rest are where the
claim has to be "at the floor" and stop there.

    python -m vertiscope.analytics --stability --corpus

Writes `build_analytics/stability.jsonl`, one row per page.
"""

from __future__ import annotations

import json
import pathlib
import sys
import time
from typing import Dict, List, Sequence

DEFAULT_ARTIFACT_DIR = pathlib.Path("build_analytics")

# Long enough that a page with a timer or an ad-sync loop has a chance to
# move, short enough that a corpus sweep stays affordable. The gesture arms
# wait 0.45s between mutating and draining, so a floor measured over a much
# shorter window would understate what they are exposed to.
SETTLE_SECONDS = 3.0


def _map_of(driver, url: str, context_window: int) -> Dict[str, str]:
    """One full walk of the live page by a reader with no history."""
    from .drift import _truth

    return {leaf.address.key(): (leaf.value or "")
            for leaf in _truth(driver, url, context_window).leaves()
            if leaf.address is not None}


def _diff(first: Dict[str, str], second: Dict[str, str]) -> dict:
    addresses = set(first) ^ set(second)
    values = [key for key in set(first) & set(second)
              if first[key] != second[key]]
    moving = list(addresses) + values
    return {
        # Addresses present in one map and not the other.
        "address_churn": len(addresses),
        # Addresses in both, holding different content.
        "value_churn": len(values),
        # The floor itself: what a gesture score has to beat to mean anything.
        "floor": len(addresses) + len(values),
        # Where the motion is. Named because it has twice been the whole
        # answer -- ad iframes on one page, a price ticker on another -- and
        # a floor without a location invites the assumption that it is noise
        # spread evenly over the document.
        "iframe_share": sum(1 for key in moving if "/iframe" in key),
        "sample": sorted(moving)[:5],
    }


def measure_stability(driver, urls: Sequence[str], *,
                      context_window: int = 1200,
                      settle: float = SETTLE_SECONDS) -> dict:
    """Two independent maps per page, `settle` apart, and their disagreement."""
    rows: List[dict] = []
    for url in urls:
        row: Dict[str, object] = {"url": url, "settle": settle}
        try:
            driver.get("about:blank")
            driver.get(url)
            time.sleep(1.8)
            first = _map_of(driver, url, context_window)
            time.sleep(settle)
            second = _map_of(driver, url, context_window)
            row["addresses"] = len(first)
            row.update(_diff(first, second))
        except Exception as exc:                       # noqa: BLE001
            row["error"] = "{}: {}".format(type(exc).__name__, exc)[:200]
        rows.append(row)
        print("  [{}/{}] {}".format(
            len(rows), len(urls),
            row.get("error") or "floor={} addr={} val={}".format(
                row.get("floor"), row.get("address_churn"),
                row.get("value_churn"))),
            file=sys.stderr, flush=True)
    return {"rows": rows, "settle": settle,
            "context_window": context_window, "t": time.time()}


def render_stability_table(report: dict) -> str:
    rows = report.get("rows", [])
    if not rows:
        return "  no stability measurements"

    scored = [r for r in rows if not r.get("error")]
    still = [r for r in scored if r["floor"] == 0]
    moving = [r for r in scored if r["floor"] > 0]

    out = ["", "  the page against itself, {:.1f}s apart, with no sensor in "
           "between".format(report.get("settle", SETTLE_SECONDS)), ""]
    out.append("  {:<44}{:>8}{:>8}{:>8}{:>9}".format(
        "page", "addrs", "addr", "value", "floor"))
    for row in sorted(moving, key=lambda r: -r["floor"]):
        label = row["url"].rsplit("/", 1)[-1]
        label = label[:-5] if label.endswith(".html") else label
        out.append("  {:<44}{:>8}{:>8}{:>8}{:>9}".format(
            label[:43], row["addresses"], row["address_churn"],
            row["value_churn"], row["floor"]))
    for row in rows:
        if row.get("error"):
            label = row["url"].rsplit("/", 1)[-1]
            out.append("  {:<44}{}".format(label[:43], row["error"][:40]))

    out.append("")
    out.append("  pages measured               {:>5}".format(len(scored)))
    out.append("  hold still (floor 0)         {:>5}   exactness is claimable "
               "here".format(len(still)))
    out.append("  move on their own            {:>5}   residue at or below "
               "their floor proves nothing".format(len(moving)))
    if moving:
        floors = sorted(r["floor"] for r in moving)
        out.append("  floor among those: median {}, max {}".format(
            floors[len(floors) // 2], floors[-1]))
        frames = sum(r["iframe_share"] for r in moving)
        total = sum(r["floor"] for r in moving)
        out.append("  of all motion, {} of {} is inside an iframe".format(
            frames, total))
    out.append("")
    out.append("  No sensor takes part in this. Two readers walk the same live")
    out.append("  page whole, three seconds apart, and disagree: that is the")
    out.append("  document moving, and it is the strongest form the evidence")
    out.append("  can take, because there is nothing else in the room to")
    out.append("  blame. A gesture score on a page below its own floor is not")
    out.append("  a small defect -- it is not a measurement.")
    return chr(10).join(out)


def write_stability_artifact(report: dict,
                             out_dir: pathlib.Path = DEFAULT_ARTIFACT_DIR
                             ) -> pathlib.Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "stability.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        for row in report.get("rows", []):
            record = dict(row)
            record["t"] = report.get("t")
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    return path
