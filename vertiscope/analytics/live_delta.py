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

// Tags that hold text but are not content: inserting into them measures the
// sensor against something no reader will ever see. The harness picked a
// group of 17 <script> elements on salesforce.com before this list existed,
// and a group of <pre> code samples on lit.dev -- neither is the page's
// "list", and the numbers they produced were about whatever happened to have
// the most same-tag children.
var NOT_CONTENT = {SCRIPT: 1, STYLE: 1, TEMPLATE: 1, NOSCRIPT: 1, HEAD: 1,
                   META: 1, LINK: 1, TITLE: 1, SVG: 1, PATH: 1, DEFS: 1};

function kidsOf(node) {
  if (node.shadowRoot) return Array.prototype.slice.call(node.shadowRoot.children);
  return Array.prototype.slice.call(node.children || []);
}

function drawn(el) {
  try {
    if (typeof el.checkVisibility === 'function'
        && !el.checkVisibility({opacityProperty: true, visibilityProperty: true,
                                contentVisibilityAuto: true})) {
      return false;
    }
    var r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  } catch (e) { return false; }
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
    if (NOT_CONTENT[tag]) continue;
    var group = byTag[tag];
    // Carrying text is not enough -- it has to be text the page shows.
    if (group.length > bestCount
        && (group[0].textContent || '').trim().length > 20
        && drawn(group[0])) {
      bestCount = group.length; best = group;
    }
  }
}

if (!best || bestCount < 3) return {ok: false, reason: 'no drawn repeated group', count: bestCount};

var first = best[0];

// A fresh element of the group's own tag carrying one short unique string.
//
// Cloning the first item was the obvious thing and is the wrong experiment:
// `cloneNode(true)` copies a whole subtree, so "one node inserted" became
// "one arbitrary subtree inserted" -- on quotes.toscrape.com it added 140
// leaves to a 176-leaf page, and the delta being measured was the harness's,
// not the page's. The mutation has to be minimal and known or the number
// means nothing.
var marker = 'VERTISCOPE-INSERTED-' + Math.random().toString(36).slice(2, 8);
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
                       settle_s: float = 1.2,
                       repeats: int = 1) -> dict:
    """Insert one node into each real page and score both chunking modes.

    Repeated, because one run of a live page is evidence of nothing. Measured
    the hard way: www.salesforce.com reported 341 of 346 chunks holding new
    text in one run and 10 in the next, for the same mutation on the same
    page. A marketing site rotates its own content between two visits a minute
    apart, and a single number from it is a number about that visit.

    The spread is reported alongside the median so a page that does not
    reproduce says so instead of contributing a figure that looks like a
    measurement.
    """
    from ..sensing import Sensor
    from ..stream import StreamingScan

    rows: List[dict] = []
    for url in urls:
      for attempt in range(max(1, repeats)):
          row: Dict[str, object] = {"url": url, "attempt": attempt}
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

              # What the page does on its own, before anything is done to it.
              #
              # Without this arm a page that hydrates late is indistinguishable
              # from a sensor that mishandles an insertion, and I spent an
              # iteration believing the wrong one of those about lit.dev. A
              # control drain -- same wait, no mutation -- settles it: 0
              # addresses gained there, so the growth was the insertion's and
              # the sensor's to answer for.
              control_before = len(spine.trie)
              time.sleep(0.7)
              control_snap = sensor.drain(98)
              control_update = spine.absorb(
                  control_snap.units, control_snap.passno,
                  removed=control_snap.removed_addresses,
                  moved=control_snap.moved_addresses)
              row["control_delta"] = control_update.delta.size
              row["control_net"] = len(spine.trie) - control_before

              row["leaves_before"] = len(spine.trie)
              uids_before = {leaf.uid for leaf in spine.trie.leaves()}
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
              row["uids_lost"] = len(
                  uids_before - {leaf.uid for leaf in spine.trie.leaves()})
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
    return {"rows": rows, "context_window": context_window,
            "repeats": repeats, "t": time.time()}


def _median(values):
    ordered = sorted(v for v in values if v is not None)
    if not ordered:
        return 0
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2.0


def render_live_delta_table(report: dict) -> str:
    rows = report.get("rows", [])
    if not rows:
        return "  no live delta measurements"

    by_url: Dict[str, List[dict]] = {}
    for row in rows:
        by_url.setdefault(row["url"], []).append(row)

    out = ["", "  one node inserted at the head of each page's largest drawn "
                "repeated group", ""]
    out.append("  {:<26}{:>9}{:>7}{:>7}{:>8}{:>16}".format(
        "page", "group", "chunks", "delta", "moved", "new text"))
    for url, attempts in by_url.items():
        name = url.replace("https://", "").replace("http://", "")[:25]
        usable = [r for r in attempts
                  if not r.get("error") and r.get("saw_insertion")]
        if not usable:
            reason = attempts[0].get("error") or "insertion not recorded"
            out.append("  {:<26}{}".format(name, reason))
            continue
        first = usable[0]
        group = "{}x{}".format(str(first.get("group_tag", "?")).lower(),
                              first.get("group_size", 0))
        for mode in ("content", "running"):
            fresh = [r[mode]["new_text"] for r in usable if mode in r]
            spread = ("{:.0f}".format(_median(fresh)) if len(fresh) < 2
                      else "{:.0f}  [{}-{}]".format(_median(fresh), min(fresh),
                                                    max(fresh)))
            out.append("  {:<26}{:>9}{:>7.0f}{:>7.0f}{:>8.0f}{:>16}   {}".format(
                name if mode == "content" else "",
                group if mode == "content" else "",
                _median([r[mode]["chunks_before"] for r in usable]),
                _median([r["delta_size"] for r in usable]),
                _median([r["delta_moved"] for r in usable]),
                spread, mode))
        # A page that does not give the same answer twice is not measured.
        fresh = [r["content"]["new_text"] for r in usable if "content" in r]
        if len(fresh) > 1 and max(fresh) > 4 * max(min(fresh), 1) + 4:
            out.append("  {:<26}** did not reproduce across {} runs: new text "
                       "{} **".format("", len(fresh), fresh))
        for row in usable:
            if row.get("anomaly"):
                out.append("  {:<26}** {} **".format("", row["anomaly"]))
                break
        moved_on_own = [r for r in usable
                        if r.get("control_delta") or r.get("control_net")]
        if moved_on_own:
            r = moved_on_own[0]
            out.append("  {:<26}(the page moved on its own: delta {}, {:+d} "
                       "addresses, before anything was inserted)".format(
                           "", r["control_delta"], r["control_net"]))
    out.append("")
    out.append("  `group` is what was mutated: the largest group of same-tag")
    out.append("  siblings the page actually draws. Shown because it decides")
    out.append("  what the row means -- an insertion into a page's card grid")
    out.append("  and one into a run of <script> tags are not the same test,")
    out.append("  and before the tag filter existed this harness chose the")
    out.append("  second on two of five pages.")
    out.append("")
    out.append("  `new text` is chunks holding markdown no chunk held before:")
    out.append("  what the embedder is asked to do. With more than one run the")
    out.append("  range follows the median, because one run of a live page is")
    out.append("  evidence of nothing -- salesforce.com answered 341 and then")
    out.append("  10 for the same mutation a minute apart.")
    out.append("")
    out.append("  Every page is drained once without being touched first, so")
    out.append("  a page that hydrates late cannot be mistaken for a sensor")
    out.append("  that mishandles an insertion. A control line appears only")
    out.append("  when the page did something on its own.")
    out.append("")
    out.append("  `delta` is the trie's own count of genuine change and should")
    out.append("  read 1 for one node; `moved` is the addresses the insertion")
    out.append("  re-pointed, which grows with the group and is not an edit.")
    out.append("  A page that gains addresses while dropping none is the")
    out.append("  signature of a move the receiver did not honour. Gaining and")
    out.append("  dropping in equal measure is the opposite -- a shift")
    out.append("  re-addressing content, which is the mechanism working.")
    return chr(10).join(out)


def render_corpus_summary(report: dict) -> str:
    """A distribution, not 130 rows.

    The claim being tested is that one node arriving costs work proportional
    to the insertion and not to the page, on documents nobody wrote for the
    test. A table of every page answers a different question -- "what did
    page 74 do" -- and buries the one that matters, which is how often the
    property holds and where it fails.

    So: how many pages were measurable at all, how many gave a delta of 1,
    what the spread of new text looks like, and every page that lost an
    identity or grew the trie, named.
    """
    rows = [r for r in report.get("rows", [])]
    if not rows:
        return "  no corpus measurements"

    def name(row):
        text = row["url"].rsplit("/", 1)[-1]
        return text[:-5] if text.endswith(".html") else text

    errored = [r for r in rows if r.get("error")]
    no_group = [r for r in errored if "repeated group" in str(r.get("error"))]
    other_err = [r for r in errored if r not in no_group]
    ok = [r for r in rows if not r.get("error") and r.get("saw_insertion")]
    missed = [r for r in rows
              if not r.get("error") and not r.get("saw_insertion")]

    out = ["", "  the frozen corpus: one node into each page's largest drawn "
                "repeated group", ""]
    out.append("  {:<34}{:>6}".format("pages in corpus", len(rows)))
    out.append("  {:<34}{:>6}".format("  measured", len(ok)))
    out.append("  {:<34}{:>6}   {}".format(
        "  no drawn repeated group", len(no_group),
        "nothing to insert into; not a failure"))
    out.append("  {:<34}{:>6}".format("  insertion not observed", len(missed)))
    out.append("  {:<34}{:>6}".format("  errored", len(other_err)))
    if not ok:
        return chr(10).join(out)

    deltas = [r["delta_size"] for r in ok]
    fresh = [r["content"]["new_text"] for r in ok if "content" in r]
    running = [r["running"]["new_text"] for r in ok if "running" in r]
    lost = [r for r in ok if r.get("uids_lost")]
    grew = [r for r in ok if r.get("anomaly")]
    moved_alone = [r for r in ok
                   if r.get("control_delta") or r.get("control_net")]

    out.append("")
    out.append("  {:<34}{:>6}   of {}".format(
        "delta == 1 (one node, one change)",
        sum(1 for d in deltas if d == 1), len(deltas)))
    out.append("  {:<34}{:>6}".format("delta <= 3", sum(1 for d in deltas
                                                        if d <= 3)))
    out.append("  {:<34}{:>6}".format("worst delta", max(deltas)))
    out.append("")
    out.append("  new text, content boundaries   median {:.0f}   p90 {:.0f}   "
               "max {:.0f}".format(_median(fresh), _pct(fresh, 0.9),
                                   max(fresh)))
    if running:
        out.append("  new text, running total        median {:.0f}   p90 {:.0f}"
                   "   max {:.0f}".format(_median(running),
                                          _pct(running, 0.9), max(running)))
    out.append("")
    out.append("  {:<34}{:>6}".format("pages that lost an identity", len(lost)))
    for r in lost[:8]:
        out.append("     {:<40} {} uid(s), delta {}".format(
            name(r)[:40], r["uids_lost"], r["delta_size"]))
    out.append("  {:<34}{:>6}".format("pages where the trie grew", len(grew)))
    for r in grew[:8]:
        out.append("     {:<40} {}".format(name(r)[:40], r["anomaly"]))
    if moved_alone:
        out.append("  {:<34}{:>6}   (excluded from nothing; just noted)".format(
            "pages that moved on their own", len(moved_alone)))
    out.append("")
    out.append("  A frozen page is loaded from disk and mutated in a real")
    out.append("  browser, so the fold and the MutationObserver path are the")
    out.append("  live ones; only the document is fixed. That is deliberate --")
    out.append("  a benchmark against the internet measures the internet's")
    out.append("  variance rather than ours, and cannot be replayed.")
    out.append("  These pages were fetched without running their JavaScript,")
    out.append("  so script-rendered ones are thin. That is a real class of")
    out.append("  input and is kept rather than excluded.")
    return chr(10).join(out)


def _pct(values, q):
    ordered = sorted(values)
    if not ordered:
        return 0
    i = min(len(ordered) - 1, int(q * (len(ordered) - 1) + 0.5))
    return ordered[i]


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
