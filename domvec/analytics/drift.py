"""How far the incrementally-repaired trie drifts from the page it maps.

The trie is repaired in place: `AddressTrie.apply` is the live path's only
mutator, and it writes what each drain reports. One insertion costs one change
on 112 of 121 corpus pages, which is the O(delta) property holding. But the
trie also *grows* on two-thirds of them — content is written at its new address
and the old one is never vacated, because neither the receiver nor the fold can
presently say "this address is gone" without deleting addresses the page still
has. Both attempts at that rule did exactly that, verified against the DOM.

So the honest question is not whether the map is exact. It is not. The question
is **how wrong it gets, how fast, and in which direction** — and that is
answerable, because the same sensor can produce a *fresh* map of the page as it
now stands, and the two can be compared address for address.

That comparison is the confusion matrix the goal asks for, over the map's own
totality of coverage:

``tp``          addresses the repaired trie holds and the page has
``fn``          addresses the page has and the repaired trie lost  (**loss**)
``fp``          addresses the repaired trie holds and the page does not
                (**staleness** — the accumulation described above)
``value_wrong`` addresses both hold, where the repaired trie's value is stale

Loss and staleness are separated on purpose. They are not the same defect and
they do not have the same cost: a lost address is content the reader can no
longer reach, and a stale one is content the reader reaches twice or reaches
wrongly. A single "accuracy" number would average them into something that
sounds fine and says nothing.

The ground truth is a second sensor booted on the same live document, which
walks it whole. That is a real measurement of the page as it stands, not a
replay of what was reported — the whole point is to catch what the incremental
path never heard about.
"""

from __future__ import annotations

import json
import pathlib
import time
from typing import Dict, List, Sequence

__all__ = ["measure_drift", "render_drift_table", "write_drift_artifact"]

DEFAULT_ARTIFACT_DIR = pathlib.Path("build_analytics")

# One mutation, applied repeatedly: a fresh element at the head of the page's
# largest drawn repeated group. Same shape as `live_delta`, deliberately, so
# the two artifacts measure the same gesture.
MUTATE_JS = r"""
var best = null, bestCount = 0;
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
                                contentVisibilityAuto: true})) return false;
    var r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0;
  } catch (e) { return false; }
}

var stack = [document.documentElement], seen = 0;
while (stack.length && seen < 20000) {
  var node = stack.pop(); seen++;
  var kids = kidsOf(node), byTag = {};
  for (var i = 0; i < kids.length; i++) {
    var t = kids[i].tagName;
    (byTag[t] = byTag[t] || []).push(kids[i]);
    stack.push(kids[i]);
  }
  for (var tag in byTag) {
    if (NOT_CONTENT[tag]) continue;
    var group = byTag[tag];
    // Qualified on the *last* member, not the first.
    //
    // Each mutation inserts a short marker at the head of the group it
    // chooses, so on the next round `group[0]` is that marker -- a dozen
    // characters, failing the text test, and the group stops being found at
    // all. The run then ends after one mutation, which is where the drift
    // curve becomes interesting rather than before it.
    var probe = group[group.length - 1];
    if (group.length > bestCount
        && (probe.textContent || '').trim().length > 20
        && drawn(probe)) { bestCount = group.length; best = group; }
  }
}
if (!best || bestCount < 3) return {ok: false, reason: 'no drawn repeated group'};

var first = best[0];
var marker = 'DOMVEC-' + arguments[0] + '-' + Math.random().toString(36).slice(2, 6);
var fresh = document.createElement(first.tagName);
fresh.appendChild(document.createTextNode(marker));
first.parentNode.insertBefore(fresh, first);
return {ok: true, tag: first.tagName, count: bestCount, marker: marker};
"""


def _settle(sensor, spine, quiet_passes=2, limit=20, pause=0.25):
    quiet = passno = 0
    while passno < limit and quiet < quiet_passes:
        snapshot = sensor.drain(passno)
        update = spine.absorb(snapshot.units, snapshot.passno,
                              removed=snapshot.removed_addresses,
                              moved=snapshot.moved_addresses)
        if update.delta.size == 0 and not update.delta.moved:
            quiet += 1
        else:
            quiet = 0
        passno += 1
        time.sleep(pause)
    return quiet >= quiet_passes


def _truth(driver, url, window):
    """A fresh map of the document as it now stands.

    A second sensor, booted on the same live page, walking it whole. Not a
    replay of what was reported: what the incremental path never heard about
    is exactly what this is for.
    """
    from ..sensing import Sensor
    from ..stream import StreamingScan

    # A distinct handle each time. The sensor installs its drain with
    # `configurable: false` so a page cannot redefine it, which also means the
    # same name cannot be booted twice on one document: the second truth map
    # died with "can't redefine" and the run stopped at the first checkpoint.
    _truth.seq = getattr(_truth, "seq", 0) + 1
    sensor = Sensor(driver, url, budget=window,
                    handle="domvec_truth_{}".format(_truth.seq))
    sensor.boot()
    time.sleep(0.6)
    spine = StreamingScan(url, context_window=window)
    _settle(sensor, spine)
    return spine.trie


def _score(repaired, truth):
    """Address-for-address, plus the values where both agree on the address."""
    mine = {leaf.address.key(): (leaf.value or "")
            for leaf in repaired.leaves() if leaf.address is not None}
    theirs = {leaf.address.key(): (leaf.value or "")
              for leaf in truth.leaves() if leaf.address is not None}
    shared = set(mine) & set(theirs)
    return {
        "tp": len(shared),
        "fn": len(set(theirs) - set(mine)),
        "fp": len(set(mine) - set(theirs)),
        "value_wrong": sum(1 for k in shared if mine[k] != theirs[k]),
        "truth_addresses": len(theirs),
        "trie_addresses": len(mine),
    }


def measure_drift(driver, urls: Sequence[str], *, mutations: int = 10,
                  context_window: int = 1200,
                  checkpoints: Sequence[int] = (1, 3, 5, 10)) -> dict:
    """Mutate a page repeatedly; score the repaired trie against a fresh map."""
    from ..sensing import Sensor
    from ..stream import StreamingScan

    rows: List[dict] = []
    for url in urls:
        row: Dict[str, object] = {"url": url, "mutations": mutations,
                                  "checkpoints": []}
        try:
            driver.get("about:blank")
            driver.get(url)
            time.sleep(1.8)
            sensor = Sensor(driver, url, budget=context_window)
            sensor.boot()
            time.sleep(0.8)
            spine = StreamingScan(url, context_window=context_window)
            row["settled"] = _settle(sensor, spine)
            if spine.trie is None:
                row["error"] = "nothing captured"
                rows.append(row)
                continue
            row["leaves_at_start"] = len(spine.trie)

            for n in range(1, mutations + 1):
                found = driver.execute_script(MUTATE_JS, n)
                if not found or not found.get("ok"):
                    row["error"] = "mutation {}: {}".format(
                        n, (found or {}).get("reason", "?"))
                    break
                row.setdefault("group_tag", found.get("tag"))
                time.sleep(0.45)
                snapshot = sensor.drain(100 + n)
                spine.absorb(snapshot.units, snapshot.passno,
                             removed=snapshot.removed_addresses,
                             moved=snapshot.moved_addresses)
                if n in checkpoints:
                    scored = _score(spine.trie, _truth(driver, url,
                                                       context_window))
                    scored["after"] = n
                    row["checkpoints"].append(scored)
        except Exception as exc:                       # noqa: BLE001
            row["error"] = "{}: {}".format(type(exc).__name__, exc)[:200]
        rows.append(row)
    return {"rows": rows, "mutations": mutations,
            "context_window": context_window, "t": time.time()}


def render_drift_table(report: dict) -> str:
    rows = report.get("rows", [])
    if not rows:
        return "  no drift measurements"

    out = ["", "  the repaired trie against a fresh map of the same document",
           ""]
    out.append("  {:<30}{:>6}{:>9}{:>8}{:>8}{:>8}{:>10}".format(
        "page", "after", "truth", "recall", "stale", "lost", "wrong value"))
    for row in rows:
        label = row["url"].rsplit("/", 1)[-1]
        label = label[:-5] if label.endswith(".html") else label
        if row.get("error") and not row.get("checkpoints"):
            out.append("  {:<30}{}".format(label[:29], row["error"][:60]))
            continue
        for i, point in enumerate(row.get("checkpoints", [])):
            truth = point["truth_addresses"] or 1
            out.append("  {:<30}{:>6}{:>9}{:>7.1f}%{:>8}{:>8}{:>10}".format(
                label[:29] if i == 0 else "", point["after"],
                point["truth_addresses"],
                100.0 * point["tp"] / truth,
                point["fp"], point["fn"], point["value_wrong"]))
        if row.get("error"):
            out.append("  {:<30}stopped: {}".format("", row["error"][:56]))
    out.append("")
    out.append("  `truth` is a second sensor booted on the same live document")
    out.append("  and walked whole -- a real map of the page as it stands, not")
    out.append("  a replay of what was reported, which is the point: what the")
    out.append("  incremental path never heard about is what this catches.")
    out.append("")
    out.append("  `stale` is addresses the trie holds and the page does not;")
    out.append("  `lost` is addresses the page has and the trie does not.")
    out.append("  They are kept apart because they are different defects with")
    out.append("  different costs -- a lost address is content the reader")
    out.append("  cannot reach, a stale one is content reached twice or")
    out.append("  wrongly -- and one accuracy figure would average them into")
    out.append("  something that sounds fine and says nothing.")
    return chr(10).join(out)


def write_drift_artifact(report: dict,
                         out_dir: pathlib.Path = DEFAULT_ARTIFACT_DIR
                         ) -> pathlib.Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "drift.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        for row in report.get("rows", []):
            record = dict(row)
            record["t"] = report.get("t")
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    return path
