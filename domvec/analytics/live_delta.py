"""What one node arriving costs on a page nobody wrote for the test.

`delta.py` and `projection.py` both measure an N-row list built to be measured.
That is the right way to see a *shape* — N is a parameter and nothing else
varies — and it is the wrong way to believe one. A list of identical rows is
the friendliest possible input to a chunker that cuts on content: every piece
is the same size, so any boundary rule looks well behaved. A real page is
ragged, deeply wrapped, part shadow DOM, and its "list" is a grid of cards with
images and controls in it.

So this asks the same question of real documents: **one node inserted at the
head of the page's largest repeated group, what does it cost?**

The mutation is found rather than scripted. No per-site selectors: the harness
walks the composed tree, takes the element with the most same-tag element
children — which on a search page is the results, on a catalogue the cards, on
a feed the posts — clones its first child, gives every text node in the clone a
unique marker, and puts it at the front. That is the adversarial position: it
shifts the positional address of every following sibling.

Two things are measured against the trie's own delta, in both chunking modes on
the *same* pair of tries, so the comparison is not confounded by a second visit
to the page:

``new_text``    chunks holding markdown no chunk held before -- what the
                embedder is asked to do, and what should not scale with the
                page.
``embedded``    the same question driven through `VectorQueue` against a
                counting embedder, so the number is the queue's behaviour and
                not a proxy for it.

The harness writes into the page, which the sensor never does. That is the
only way to obtain a *known* delta on a document that would otherwise change
on its own schedule or not at all, and it is the same device `delta.py` uses on
its fixture. Nothing is transmitted and the page is not reloaded afterwards.
"""

from __future__ import annotations

import json
import pathlib
import time
from typing import Dict, List, Optional, Sequence

__all__ = ["measure_live_delta", "render_live_delta_table",
           "write_live_delta_artifact"]

DEFAULT_ARTIFACT_DIR = pathlib.Path("build_analytics")

# Find the biggest repeated-sibling group and put a clone of its first item at
# the front. Composed tree, so a group inside a shadow root counts.
INSERT_AT_HEAD_JS = r"""
var best = null, bestCount = 0;

function kidsOf(node) {
  if (node.shadowRoot) return Array.prototype.slice.call(node.shadowRoot.children);
  return Array.prototype.slice.call(node.children || []);
}

var stack = [document.documentElement], seen = 0;
while (stack.length && seen < 20000) {
  var node = stack.pop(); seen++;
  var kids = kidsOf(node);
  var byTag = {};
  for (var i = 0; i < kids.length; i++) {
    var t = kids[i].tagName;
    (byTag[t] = byTag[t] || []).push(kids[i]);
    stack.push(kids[i]);
  }
  for (var tag in byTag) {
    var group = byTag[tag];
    // A group is only interesting if its items carry text; a row of <script>
    // or <br> is repeated structure with nothing in it to chunk.
    if (group.length > bestCount && (group[0].textContent || '').trim().length > 20) {
      bestCount = group.length; best = group;
    }
  }
}

if (!best || bestCount < 3) return {ok: false, reason: 'no repeated group', count: bestCount};

var first = best[0];

// A fresh element of the group's own tag carrying one short unique string.
//
// Cloning the first item was the obvious thing and is the wrong experiment:
// `cloneNode(true)` copies a whole subtree, so "one node inserted" became
// "one arbitrary subtree inserted" -- on quotes.toscrape.com it added 140
// leaves to a 176-leaf page, and the delta being measured was the harness's,
// not the page's. The mutation has to be minimal and known or the number
// means nothing.
var marker = 'DOMVEC-INSERTED-' + Math.random().toString(36).slice(2, 8);
var fresh = document.createElement(first.tagName);
fresh.appendChild(document.createTextNode(marker));
first.parentNode.insertBefore(fresh, first);
return {ok: true, tag: first.tagName, count: bestCount, marker: marker,
        texts: 1};
"""


def settle(sensor, spine, *, quiet_passes: int = 2, limit: int = 24,
           pause: float = 0.25) -> dict:
    """Drain until the page stops saying anything new, or give up saying so.

    A fixed number of passes is not enough on a real document. The first run
    of this harness used three, and on news.ycombinator.com the drain *after*
    the insertion carried 660 units of genuine change for one cloned row --
    most of the page arriving late, attributed to the mutation. The baseline
    render was then of a partial page, and `new_text` came out larger than the
    number of chunks on the page, which is impossible for one insertion and is
    how the mistake announced itself.

    So: keep draining until two consecutive passes report no change at all.
    Pages that never go quiet -- a ticker, a carousel, an ad slot -- are
    reported as such rather than measured, because a delta that includes the
    page's own churn is not a measurement of the insertion.
    """
    quiet = 0
    passno = 0
    while passno < limit and quiet < quiet_passes:
        snapshot = sensor.drain(passno)
        update = spine.absorb(snapshot.units, snapshot.passno,
                              removed=snapshot.removed_addresses,
                              moved=snapshot.moved_addresses)
        delta = update.delta
        moved = len(delta.moved)
        if delta.size == 0 and moved == 0:
            quiet += 1
        else:
            quiet = 0
        passno += 1
        time.sleep(pause)
    return {"passes": passno, "quiet": quiet >= quiet_passes}


class _Counting:
    """An embedder that counts, and whose output depends on its input.

    The dependence matters: a constant embedder would make the reuse check
    below pass on any cache at all.
    """

    def __init__(self):
        self.texts = 0

    def embed_texts(self, texts):
        import numpy as np

        self.texts += len(texts)
        return np.stack([np.full(4, float(len(t))) for t in texts])


class _Mode:
    """One chunking mode, rendered before and after the mutation.

    Held open across the insertion rather than rendering two tries at the end,
    because on the live path `StreamingScan.absorb` mutates the trie *in
    place* -- `AddressTrie.apply` is the live path's only mutator, by design.
    Keeping a reference to `spine.trie` before the drain and rendering it after
    therefore renders the *post*-insertion page twice, and the whole
    measurement reads zero. It did, on the first run.
    """

    def __init__(self, name: str, flag: bool, window: int):
        from ..markdown import RenderMemo
        from ..vectors import VectorQueue

        self.name = name
        self.flag = flag
        self.window = window
        self.memo = RenderMemo()
        self.queue = VectorQueue()
        self.embedder = _Counting()
        self.before: List = []
        self.cold_ms = 0.0

    def _render(self, trie):
        from .. import markdown as md

        previous = md.CONTENT_BOUNDARIES
        md.CONTENT_BOUNDARIES = self.flag
        try:
            started = time.perf_counter()
            chunks = md.render_trie(trie, context_window=self.window,
                                    memo=self.memo)
            return chunks, (time.perf_counter() - started) * 1000.0
        finally:
            md.CONTENT_BOUNDARIES = previous

    def capture(self, trie) -> None:
        self.before, self.cold_ms = self._render(trie)
        self.queue.extend(self.before)
        self.queue.flush(self.embedder)

    def score(self, trie) -> dict:
        cold_embedded = self.embedder.texts
        after, incr_ms = self._render(trie)
        held = {c.markdown for c in self.before}
        new_text = sum(1 for c in after if c.markdown not in held)
        self.queue.extend(after)
        self.queue.flush(self.embedder)
        sizes = sorted(c.chars for c in self.before)
        return {
            "chunks_before": len(self.before),
            "chunks_after": len(after),
            "lines": sum(len(c.lines) for c in self.before),
            "new_text": new_text,
            "embedded": self.embedder.texts - cold_embedded,
            "reused": self.queue.reused,
            "median_chars": sizes[len(sizes) // 2] if sizes else 0,
            "cold_ms": self.cold_ms,
            "incr_ms": incr_ms,
        }


def measure_live_delta(driver, urls: Sequence[str], *,
                       context_window: int = 1200,
                       settle_s: float = 1.2) -> dict:
    """Insert one node into each real page and score both chunking modes."""
    from ..sensing import Sensor
    from ..stream import StreamingScan

    rows: List[dict] = []
    for url in urls:
        row: Dict[str, object] = {"url": url}
        try:
            driver.get("about:blank")
            driver.get(url)
            time.sleep(settle_s)
            sensor = Sensor(driver, url, budget=context_window)
            sensor.boot()
            time.sleep(0.6)
            spine = StreamingScan(url, context_window=context_window)
            quiescence = settle(sensor, spine)
            row["settle_passes"] = quiescence["passes"]
            row["settled"] = quiescence["quiet"]
            if spine.trie is None:
                row["error"] = "nothing captured"
                rows.append(row)
                continue

            row["leaves_before"] = len(spine.trie)
            before_keys = {leaf.address.key() for leaf in spine.trie.leaves()
                           if leaf.address is not None}
            modes = [_Mode("content", True, context_window),
                     _Mode("running", False, context_window)]
            for mode in modes:
                mode.capture(spine.trie)

            found = driver.execute_script(INSERT_AT_HEAD_JS)
            if not found or not found.get("ok"):
                row["error"] = "no repeated group ({})".format(
                    (found or {}).get("reason", "?"))
                rows.append(row)
                continue
            row["group_tag"] = found.get("tag")
            row["group_size"] = found.get("count")
            time.sleep(0.5)

            snapshot = sensor.drain(99)
            started = time.perf_counter()
            update = spine.absorb(snapshot.units, snapshot.passno,
                                  removed=snapshot.removed_addresses,
                                  moved=snapshot.moved_addresses)
            row["apply_ms"] = (time.perf_counter() - started) * 1000.0
            row["fold_ms"] = (snapshot.stats or {}).get("repairMs")
            row["delta_size"] = update.delta.size
            if not row["settled"]:
                # Said plainly rather than folded into the numbers: whatever
                # this row measures, it is not one insertion.
                row["warning"] = ("page never went quiet; the delta includes "
                                  "its own churn")
            row["delta_moved"] = len(update.delta.moved)
            row["visited"] = update.delta.visited
            row["leaves_after"] = len(spine.trie)
            after_keys = {leaf.address.key() for leaf in spine.trie.leaves()
                          if leaf.address is not None}
            row["leaves_gained"] = len(after_keys - before_keys)
            row["leaves_dropped"] = len(before_keys - after_keys)
            # The check that would have caught two decoder defects on sight.
            #
            # One node arriving should add about as many addresses as it
            # carries. A trie that gains a page's worth is writing content at
            # paths the document does not have -- and since the DOM removed
            # nothing, nothing removes the originals, so it grows while the
            # page stays the same size. Reported as an anomaly rather than
            # folded into a rate, because a coverage or dedup number cannot
            # see it: every address present is still correct, there are simply
            # also addresses that are not.
            # Net, not gross. A shift re-addresses content wholesale -- 663
            # addresses gained and 662 dropped on news.ycombinator.com for one
            # inserted row -- and that is the mechanism working, not failing.
            # What must not happen is the trie ending up bigger than the page:
            # the first version of this check counted the gain alone and cried
            # anomaly on three pages that were behaving correctly.
            row["leaves_net"] = row["leaves_gained"] - row["leaves_dropped"]
            budget = max(8, 4 * max(row["delta_size"], 1))
            if row["leaves_net"] > budget:
                row["anomaly"] = (
                    "trie grew by {} addresses for a delta of {} "
                    "(gained {}, dropped {})".format(
                        row["leaves_net"], row["delta_size"],
                        row["leaves_gained"], row["leaves_dropped"]))

            # The trie must actually have seen the insertion, or everything
            # below is a measurement of nothing happening.
            row["saw_insertion"] = any(
                found["marker"] in (leaf.value or "")
                for leaf in spine.trie.leaves())

            for mode in modes:
                row[mode.name] = mode.score(spine.trie)
        except Exception as exc:                       # noqa: BLE001
            row["error"] = "{}: {}".format(type(exc).__name__, exc)[:200]
        rows.append(row)
    return {"rows": rows, "context_window": context_window, "t": time.time()}


def render_live_delta_table(report: dict) -> str:
    rows = report.get("rows", [])
    if not rows:
        return "  no live delta measurements"

    out = ["", "  one node inserted at the head of each page's largest "
                "repeated group", ""]
    out.append("  {:<34}{:>7}{:>7}{:>8}{:>9}{:>9}".format(
        "page", "chunks", "delta", "moved", "new text", "embedded"))
    for row in rows:
        name = row["url"].replace("https://", "").replace("http://", "")[:33]
        if row.get("error"):
            out.append("  {:<34}{}".format(name, row["error"]))
            continue
        content = row.get("content", {})
        running = row.get("running", {})
        out.append("  {:<34}{:>7}{:>7}{:>8}{:>9}{:>9}   content".format(
            name, content.get("chunks_before", 0), row.get("delta_size", 0),
            row.get("delta_moved", 0), content.get("new_text", 0),
            content.get("embedded", 0)))
        out.append("  {:<34}{:>7}{:>7}{:>8}{:>9}{:>9}   running".format(
            "", running.get("chunks_before", 0), row.get("delta_size", 0),
            row.get("delta_moved", 0), running.get("new_text", 0),
            running.get("embedded", 0)))
        if not row.get("saw_insertion"):
            out.append("  {:<34}** the trie did not record the inserted "
                       "node **".format(""))
        if row.get("warning"):
            out.append("  {:<34}** {} **".format("", row["warning"]))
        if row.get("anomaly"):
            out.append("  {:<34}** {} **".format("", row["anomaly"]))
    out.append("")
    scored = [r for r in rows if not r.get("error") and r.get("saw_insertion")
              and r.get("settled")]
    if scored:
        c_new = sum(r["content"]["new_text"] for r in scored)
        r_new = sum(r["running"]["new_text"] for r in scored)
        chunks = sum(r["content"]["chunks_before"] for r in scored)
        out.append("  across {} page(s), {:,} chunks: {} chunk(s) of new text "
                   "with content boundaries, {} with a running total"
                   .format(len(scored), chunks, c_new, r_new))
    out.append("")
    out.append("  A page that gains addresses while dropping none is the")
    out.append("  signature of a move the receiver did not honour: the content")
    out.append("  is written at its new address and left at the old one, and")
    out.append("  no coverage or dedup number can see it because every address")
    out.append("  present is still correct. Gaining and dropping in equal")
    out.append("  measure is the opposite -- a shift re-addressing content,")
    out.append("  which is the mechanism working.")
    out.append("")
    out.append("  `delta` is the trie's own count of genuine change and should")
    out.append("  read 1 for one node; `moved` is the addresses the insertion")
    out.append("  re-pointed, which grows with the group and is not an edit.")
    out.append("  `new text` is what the chunker hands the embedder that it")
    out.append("  has not seen. A page whose largest group is small has little")
    out.append("  to shift and will look good either way -- read the two rows")
    out.append("  against each other, not against zero.")
    return "\n".join(out)


def write_live_delta_artifact(
    report: dict, out_dir: pathlib.Path = DEFAULT_ARTIFACT_DIR
) -> pathlib.Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "live_delta.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        for row in report.get("rows", []):
            record = dict(row)
            record["t"] = report.get("t")
            record["context_window"] = report.get("context_window")
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    return path
