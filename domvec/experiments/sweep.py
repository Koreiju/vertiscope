"""Run pages end-to-end through the real REPL, per variant, and record it all.

Two tiers, because the arithmetic forces a choice and pretending otherwise
would produce a number nobody should trust:

  breadth  many pages, one configuration. Answers "how often is a search box
           or a pager actually found, across the open web?" — a rate, and a
           rate needs pages, not configurations.
  depth    a stratified page sample, every variant, ten scrolls each. Answers
           "which mechanism is better?" — a contrast, and a contrast needs
           configurations held against the same pages, not more pages.

At ~25 s per page-variant, 24 variants x 5000 pages is ~35 days of wall
clock. The split buys the same two answers in hours instead.

Every run is the whole product: `open`, then real scrolls that drive the live
page and fold pagination in, then retrieval out of the store. Nothing is
stubbed, and the record says so per row.
"""

from __future__ import annotations

import json
import pathlib
import time
import traceback
from typing import Dict, List, Optional
from urllib.parse import urlsplit

SCROLLS = 10


def _tax(repl) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for c in repl._live_chunks.values():
        for ln in c.lines:
            if ln.address is not None:
                out[ln.address.tag] = out.get(ln.address.tag, 0) + 1
    return out


def _det(repl) -> Dict[str, int]:
    """What each line's *detecting rule* decided, counted by its family.

    `_tax` counts `address.tag`, which is the render class -- what to draw.
    Search and pagination are not render classes and never appear there, so
    `tax.get("search")` was 0 on every page ever measured, including the 38%
    where the detector had in fact resolved a search box. The verdict lives
    in the other half of the accessor, `"<detector>|<rule>"`, where the rule
    reads `search.urlparam`, `pagination.rel`, `text.visible` and so on.

    One number that is wrong in the same direction on every row is worse than
    no number, because it reads as a finding about the web.
    """
    out: Dict[str, int] = {}
    for c in repl._live_chunks.values():
        for ln in c.lines:
            if ln.address is None:
                continue
            accessor = ln.address.accessor or ""
            rule = accessor.split("|", 1)[1] if "|" in accessor else ""
            if not rule:
                continue
            out[rule.split(".", 1)[0]] = out.get(rule.split(".", 1)[0], 0) + 1
    return out


def run_page(repl, url: str, variant: str, variants: dict,
             scrolls: int = SCROLLS, stay: bool = False) -> dict:
    """One page, one configuration, end to end. Never raises.

    `stay` keeps the run on the page it opened. Two different questions were
    being asked of one protocol and it could answer neither: an encoding is a
    per-page property, while pagination multiplies content by however many
    pages a run happened to reach. Measured together, two arms of the *same*
    configuration differed by 235% — because one reached 8 pages and the
    other 11 — and that noise floor buried every effect in the table.

    So the contrast holds the page still, and detection is measured where it
    belongs: over many pages, one configuration, in the breadth tier.
    """
    row = {"url": url, "host": urlsplit(url).netloc, "variant": variant,
           "ok": False, "t": time.time()}
    t0 = time.perf_counter()
    try:
        repl.variants = dict(variants)
        repl._sensor = None
        repl._live_chunks.clear()
        repl._passes.clear()
        repl._trail = []
        repl._fired = []
        repl._exhausted = False
        repl._idle = 0
        repl._gates = {}

        repl.command(f"open {url}")
        time.sleep(1.2)
        if not repl._sensor:
            row["error"] = "no sensor"
            return row
        opened = len(repl.state.document.lines) if repl.state.document else 0
        repl._trail = [repl._sensor.url or url]

        # The cold read counts. Summing only the scroll passes excluded the
        # single largest payload of the run, and on a page that yields
        # nothing further every configuration then recorded the same handful
        # of idle bytes — seven encodings that cannot agree reported
        # byte-identical totals, because the only bytes being measured were
        # the ones with no lines in them to encode.
        # Every pass, summed at the end -- not `_passes[-1]`. Opening a page
        # can produce several passes: a redirect kills the injection, the
        # sensor re-boots, and the *last* pass is then a small trailing read
        # carrying no variants block at all. Taking it reported 2,759 bytes
        # for a page that cost 149,656, and did it only for whichever
        # configuration happened to hit a redirect -- so three unrelated
        # mechanisms appeared to save 98% of the wire.
        wire = drain_ms = store_ms = 0.0
        started_at = repl._sensor.url or url
        for _ in range(scrolls):
            if not repl.extend():
                break
            if stay and (repl._sensor.url or url) != started_at:
                # A pager turned the page. For a contrast that is the run
                # ending, not the run continuing: what follows is a different
                # document and belongs to a different measurement.
                row["navigated_away"] = True
                break
            if repl._exhausted:
                break
        for p in repl._passes:
            wire += p.wire_bytes
            drain_ms += p.drain_ms
            store_ms += p.store_ms
        # What the page said it ran, taken from a pass that actually carries
        # the block. An empty report is the signature of the bug above, so it
        # is worth being able to tell "no variants" from "never asked".
        row["variants_reported"] = {}
        row["passes"] = len(repl._passes)
        for p in repl._passes:
            v = (p.stats or {}).get("variants")
            if v:
                row["variants_reported"] = v
                break

        tax = _tax(repl)
        det = _det(repl)
        grown = len(repl.state.document.lines) if repl.state.document else 0
        row.update({
            "ok": True,
            "opened_lines": opened,
            "final_lines": grown,
            "chunks": len(repl._live_chunks),
            "lines": sum(len(c.lines) for c in repl._live_chunks.values()),
            "wire_bytes": int(wire),
            "drain_ms": round(drain_ms, 1),
            "store_ms": round(store_ms, 1),
            "elapsed_s": round(time.perf_counter() - t0, 1),
            "scrolls": scrolls,
            # the two detection rates the sweep exists to establish, read
            # from the rule that fired rather than from the class it drew as
            "search_found": int(det.get("search", 0)),
            "pagination_found": int(det.get("pagination", 0)),
            "detections": det,
            "controls_enacted": len(repl._fired),
            "pages_reached": len(repl._trail),
            "exhausted": bool(repl._exhausted),
            "taxonomy": tax,
            "gates": dict(repl._gates),
            "search_gates": ((repl._passes[-1].stats or {}).get("search", {})
                             if repl._passes else {}),
            "reboots": int(getattr(repl._sensor, "reboots", 0)),
            "errors": int((repl._passes[-1].stats or {}).get("errors", 0))
            if repl._passes else 0,
        })
    except Exception as exc:  # noqa: BLE001 - a failed page is a datum
        row["error"] = f"{type(exc).__name__}: {exc}"
        row["trace"] = traceback.format_exc()[-400:]
        row["elapsed_s"] = round(time.perf_counter() - t0, 1)
    return row


class Recorder:
    """Append-only JSONL, resumable by (url, variant)."""

    def __init__(self, path):
        self.path = pathlib.Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.done = set()
        if self.path.exists():
            for line in self.path.read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                    self.done.add((r.get("url"), r.get("variant")))
                except Exception:
                    continue
        self.fh = self.path.open("a", encoding="utf-8")

    def has(self, url, variant) -> bool:
        return (url, variant) in self.done

    def add(self, row: dict) -> None:
        self.fh.write(json.dumps(row, separators=(",", ":")) + "\n")
        self.fh.flush()
        self.done.add((row.get("url"), row.get("variant")))

    def close(self) -> None:
        try:
            self.fh.close()
        except Exception:
            pass


def scrub_temp(prefix: str = "wfh_") -> int:
    """Remove temp workspaces a previous run could not delete.

    `rmtree` fails while kuzu still holds the directory, so a killed run
    leaves one behind per page. They are harmless individually and a disk
    leak in aggregate — eleven were sitting in temp after one afternoon.
    """
    import shutil
    import tempfile

    root = pathlib.Path(tempfile.gettempdir())
    n = 0
    for d in root.glob(prefix + "*"):
        if not d.is_dir():
            continue
        try:
            shutil.rmtree(d)
            n += 1
        except Exception:
            continue      # still held; a later run will get it
    return n
