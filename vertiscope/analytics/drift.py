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
import sys
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
var kind = arguments[1] || 'insert';
var marker = 'VERTISCOPE-' + arguments[0] + '-' + Math.random().toString(36).slice(2, 6);

// Four gestures, not one.
//
// Everything here was proved against a single one -- a node inserted at the
// head of a repeated group -- and a map that tracks one kind of change is not
// a map that tracks change. These are the other things a page does to itself,
// each an O(1) edit the trie should absorb exactly:
//
//   insert   a new sibling at the head; every later address shifts
//   delete   the first sibling leaves; every later address shifts back
//   edit     one text node changes; no address moves at all
//   relocate a sibling moves to the end of its group; two shifts at once
//
// `edit` is the one with no structural component, so it isolates the value
// path from the address path; `delete` is `insert` run backwards, which the
// receiver has never been asked to do; `relocate` moves a node without
// changing how many there are.
if (kind === 'delete') {
  if (bestCount < 4) return {ok: false, reason: 'group too small to delete from'};
  var goneText = (first.textContent || '').trim().slice(0, 40);
  first.parentNode.removeChild(first);
  return {ok: true, kind: kind, tag: first.tagName, count: bestCount,
          marker: goneText};
}

if (kind === 'edit') {
  var walker = document.createTreeWalker(first, NodeFilter.SHOW_TEXT, null, false);
  var n, target = null;
  while ((n = walker.nextNode())) { if ((n.nodeValue || '').trim()) { target = n; break; } }
  if (!target) return {ok: false, reason: 'nothing to edit in the group'};
  target.nodeValue = marker;
  return {ok: true, kind: kind, tag: first.tagName, count: bestCount,
          marker: marker};
}

if (kind === 'relocate') {
  if (bestCount < 4) return {ok: false, reason: 'group too small to relocate in'};
  var last = best[bestCount - 1];
  last.parentNode.insertBefore(first, last.nextSibling);
  return {ok: true, kind: kind, tag: first.tagName, count: bestCount,
          marker: (first.textContent || '').trim().slice(0, 40)};
}

// insert
var fresh = document.createElement(first.tagName);
fresh.appendChild(document.createTextNode(marker));
first.parentNode.insertBefore(fresh, first);
return {ok: true, kind: 'insert', tag: first.tagName, count: bestCount,
        marker: marker};
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
    # Deliberately on the defaults, whatever the sensor under test is
    # running. This is the denominator: hand it the same variant and the
    # two agree by construction, and a variant that dropped half the page
    # would score perfectly against a truth map that dropped the same
    # half.
    sensor = Sensor(driver, url, budget=window,
                    handle="vertiscope_truth_{}".format(_truth.seq))
    sensor.boot()
    time.sleep(0.6)
    spine = StreamingScan(url, context_window=window)
    _settle(sensor, spine)
    return spine.trie


def _score(repaired, truth, before=None, unstable=frozenset()):
    """Address-for-address, plus the values where both agree on the address.

    `footprint` is how much of the page the gesture actually disturbed --
    addresses added or dropped, plus addresses whose value changed, measured
    between what the trie held beforehand and what the page holds now. It is
    the size of the change the trie was asked to track, and a page whose
    footprint is zero cannot fail whatever the sensor does.

    A plain count difference will not do this job. `edit` changes a value and
    no addresses at all, so its address count is unchanged by design; and a
    `relocate` that moves one sibling to the end changes which addresses exist
    without changing how many. Both would read as vacuous. The symmetric
    difference is the measure that is right for all four gestures.

    `www.w3schools.com/html/html_forms.asp` scored 0 stale and 0 wrong on one
    run and 9 stale and 4 wrong on the next, same gesture, same group tag. The
    first run had deleted a DIV holding no addresses at all -- truth came back
    equal to the starting count -- so there was nothing to vacate and nothing
    that could have failed. It was not a pass; it was a measurement of nothing,
    and it sat in the corpus total as evidence for five other pages too.

    `unstable` is the set of addresses the page moved by itself during a
    control window on this same load; the `_net` figures are the residue with
    those addresses removed by name. Counting a residue against a floor would
    not do: five stale addresses under a floor of eight can still be five real
    defects somewhere the page held still. Only what actually moved may be
    discounted, and only individually.

    A metric that can be vacuous has to report its own vacuity, which is the
    non-vacuity rule turned on the harness rather than on the sensor.
    """
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
        # Residue restricted to addresses the page did not move by itself.
        "fp_net": len([k for k in set(mine) - set(theirs) if k not in unstable]),
        "fn_net": len([k for k in set(theirs) - set(mine) if k not in unstable]),
        "value_wrong_net": sum(1 for k in shared
                               if mine[k] != theirs[k] and k not in unstable),
        "floor": len(unstable),
        "truth_addresses": len(theirs),
        "trie_addresses": len(mine),
        # None when the caller did not hand over the pre-gesture map.
        "footprint": None if before is None else (
            len(set(before) ^ set(theirs))
            + sum(1 for k in set(before) & set(theirs)
                  if before[k] != theirs[k])),
    }


def measure_drift(driver, urls: Sequence[str], *, mutations: int = 10,
                  context_window: int = 1200,
                  kind: str = "insert",
                  variants=None,
                  checkpoints: Sequence[int] = (1, 3, 5, 10)) -> dict:
    """Mutate a page repeatedly; score the repaired trie against a fresh map."""
    from ..sensing import Sensor
    from ..stream import StreamingScan

    rows: List[dict] = []
    for url in urls:
        row: Dict[str, object] = {"url": url, "mutations": mutations,
                                  "kind": kind, "checkpoints": []}
        try:
            driver.get("about:blank")
            driver.get(url)
            time.sleep(1.8)
            sensor = Sensor(driver, url, budget=context_window,
                            variants=variants or {})
            sensor.boot()
            time.sleep(0.8)
            spine = StreamingScan(url, context_window=context_window)
            row["settled"] = _settle(sensor, spine)
            if spine.trie is None:
                row["error"] = "nothing captured"
                rows.append(row)
                continue
            row["leaves_at_start"] = len(spine.trie)

            # What the page does when nothing is done to it, measured on this
            # same load and over the same window the gesture gets. Two full
            # walks by fresh readers; whatever they disagree about, the page
            # moved by itself and the sensor may not be charged for it.
            #
            # On this load rather than from `stability.jsonl` because ad-sync
            # iframes differ from one page load to the next: the floor is a
            # property of the document *and* the visit, and a floor imported
            # from another visit would discount the wrong addresses by name.
            control_a = {leaf.address.key(): (leaf.value or "")
                         for leaf in _truth(driver, url, context_window).leaves()
                         if leaf.address is not None}
            time.sleep(0.45)
            control_b = {leaf.address.key(): (leaf.value or "")
                         for leaf in _truth(driver, url, context_window).leaves()
                         if leaf.address is not None}
            unstable = (set(control_a) ^ set(control_b)) | {
                k for k in set(control_a) & set(control_b)
                if control_a[k] != control_b[k]}
            row["floor"] = len(unstable)

            for n in range(1, mutations + 1):
                # Copied, not referenced. `absorb` mutates the trie in place,
                # so a map held across it describes the page after the gesture
                # and reports every footprint as zero.
                before_map = {leaf.address.key(): (leaf.value or "")
                              for leaf in spine.trie.leaves()
                              if leaf.address is not None}
                # The arm that measures the page rather than the sensor.
                #
                # coinmarketcap scored 10 wrong values under `delete` and the
                # same 10 under no mutation at all: a frozen snapshot still
                # running a clock. A score taken against a moving page is that
                # page's motion plus ours, and the two are only separable by
                # measuring the page alone first. Without this arm those ten
                # were a defect in the delete path that did not exist.
                #
                # It needs no repeated group, so it also covers the pages no
                # gesture can be performed on.
                if kind == "none":
                    found = {"ok": True, "tag": None, "count": 0}
                else:
                    found = driver.execute_script(MUTATE_JS, n, kind)
                if not found or not found.get("ok"):
                    row["error"] = "mutation {}: {}".format(
                        n, (found or {}).get("reason", "?"))
                    break
                row.setdefault("group_tag", found.get("tag"))
                # Drain to quiescence, not for a fixed pause.
                #
                # A fixed 0.45s reads the answer before a reactive page has
                # finished writing it. On coinmarketcap one deleted row makes
                # the page's own framework re-render ~2,200 addresses, and
                # measured at 0.45s that scored 3 stale and 3 lost; at 1.5s,
                # zero and zero, with units still arriving -- 15, then 49, 85,
                # 203. Nothing was missing. The harness was early.
                #
                # It was reported as a sensor defect first, and the number it
                # produced -- "96% of the cascade captured" -- was a
                # measurement of the harness wearing the sensor's name.
                #
                # `_settle` is the same quiescence rule the initial scan uses,
                # so the gesture is now read the way the boot is. A page that
                # never goes quiet (a ticker) exits on `limit`, which is why
                # the value residue on such pages is irreducible and belongs
                # to the floor rather than to the gesture.
                row.setdefault("settle_after", [])
                row["settle_after"].append(
                    _settle(sensor, spine, quiet_passes=2, limit=12))
                snapshot = sensor.drain(100 + n)
                spine.absorb(snapshot.units, snapshot.passno,
                             removed=snapshot.removed_addresses,
                             moved=snapshot.moved_addresses)
                if n in checkpoints:
                    after_truth = _truth(driver, url, context_window)
                    # The tail of the exposure: what the page moved
                    # during and just after the truth walk itself. Both
                    # maps are post-gesture, so this cannot absorb the
                    # gesture and forgive a defect.
                    tail_a = {leaf.address.key(): (leaf.value or '')
                              for leaf in after_truth.leaves()
                              if leaf.address is not None}
                    tail_b = {leaf.address.key(): (leaf.value or '')
                              for leaf in _truth(driver, url,
                                                 context_window).leaves()
                              if leaf.address is not None}
                    tail = (set(tail_a) ^ set(tail_b)) | {
                        k for k in set(tail_a) & set(tail_b)
                        if tail_a[k] != tail_b[k]}
                    scored = _score(spine.trie, after_truth,
                                    before=before_map,
                                    unstable=unstable | tail)
                    scored["after"] = n
                    row["checkpoints"].append(scored)
        except Exception as exc:                       # noqa: BLE001
            row["error"] = "{}: {}".format(type(exc).__name__, exc)[:200]
        rows.append(row)
        # A corpus arm is twenty minutes of browser and prints nothing until
        # it ends, so an arm that has wedged and an arm that is working look
        # identical from outside. One line per page on stderr, which keeps the
        # table on stdout intact for anything parsing it.
        last = (row.get("checkpoints") or [{}])[-1]
        print("  [{}/{}] {} {}".format(
            len(rows), len(urls), kind,
            row.get("error") or "tp={} fn={} fp={} wrong={}".format(
                last.get("tp"), last.get("fn"), last.get("fp"),
                last.get("value_wrong"))),
            file=sys.stderr, flush=True)
    return {"rows": rows, "mutations": mutations, "kind": kind,
            "context_window": context_window, "t": time.time()}


def render_drift_table(report: dict) -> str:
    rows = report.get("rows", [])
    if not rows:
        return "  no drift measurements"

    out = ["", "  the repaired trie against a fresh map of the same document",
           ""]
    out.append("  {:<30}{:>6}{:>9}{:>8}{:>8}{:>8}{:>10}{:>8}".format(
        "page", "after", "truth", "recall", "stale", "lost", "wrong value",
        "moved"))
    for row in rows:
        label = row["url"].rsplit("/", 1)[-1]
        label = label[:-5] if label.endswith(".html") else label
        if row.get("error") and not row.get("checkpoints"):
            out.append("  {:<30}{}".format(label[:29], row["error"][:60]))
            continue
        for i, point in enumerate(row.get("checkpoints", [])):
            truth = point["truth_addresses"] or 1
            foot = point.get("footprint")
            out.append("  {:<30}{:>6}{:>9}{:>7.1f}%{:>8}{:>8}{:>10}{:>8}".format(
                label[:29] if i == 0 else "", point["after"],
                point["truth_addresses"],
                100.0 * point["tp"] / truth,
                point["fp"], point["fn"], point["value_wrong"],
                "-" if foot is None else foot))
        if row.get("error"):
            out.append("  {:<30}stopped: {}".format("", row["error"][:56]))
    scored = [pt for row in rows for pt in row.get("checkpoints", [])]
    footed = [pt for pt in scored if pt.get("footprint") is not None]
    vacuous = [pt for pt in footed if pt["footprint"] == 0]
    live = [pt for pt in footed if pt["footprint"] > 0]
    exact = [pt for pt in live
             if not (pt["fp"] or pt["fn"] or pt["value_wrong"])]
    # The same count with the page's own motion discounted by name.
    net = [pt for pt in live
           if not (pt.get("fp_net") or pt.get("fn_net")
                   or pt.get("value_wrong_net"))]
    still = [pt for pt in live if not pt.get("floor")]
    still_exact = [pt for pt in still
                   if not (pt["fp"] or pt["fn"] or pt["value_wrong"])]
    out.append("")
    if footed:
        out.append("  measurements scored          {:>5}".format(len(footed)))
        out.append("  gesture disturbed nothing    {:>5}   excluded: a page "
                   "that could not fail".format(len(vacuous)))
        out.append("  EXACT, of those it could     {:>5} of {}".format(
            len(exact), len(live)))
        out.append("  EXACT net of the page's own  {:>5} of {}   motion "
                   "discounted by address, not by count".format(
                       len(net), len(live)))
        out.append("  on pages that held still     {:>5} of {}   the subset "
                   "where exactness is claimable".format(
                       len(still_exact), len(still)))
        out.append("")
    out.append("  `moved` is the gesture's footprint: addresses added or")
    out.append("  dropped plus values changed, between what the trie held")
    out.append("  before and what the page holds now. A page whose footprint")
    out.append("  is zero cannot fail, so counting it as exact inflates the")
    out.append("  total with pages that were never asked anything. One page")
    out.append("  scored 0 stale on a run whose deletion removed no addresses")
    out.append("  and 9 stale on the next, same gesture, same group.")
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
