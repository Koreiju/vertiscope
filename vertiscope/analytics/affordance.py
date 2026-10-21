"""Is what the REPL offers to interact with what the page can be interacted with?

The goal asks that "what we see in the webpage is essentially what we get in
the REPL", and specifically that the REPL's interactive elements be the page's
own rather than a vocabulary of commands laid over it. That is a claim about
*affordances*, and it is not the claim the coverage arrows make.

`page->wireframe` scores whether the right addresses were drawn. It reports
`fp` only for **invented addresses** -- paths the composed tree does not
contain (`affine.py`, `path in page_paths`). So a `<div>` drawn as a button
passes it: the path exists, and only its class is wrong. The address is right
and the affordance is a fiction.

The two errors are not symmetric and are counted apart:

  missed      the page has a control and the REPL does not present one. The
              reader cannot reach it. Bad, and visible -- a reader looking for
              a button finds prose.

  phantom     the REPL presents a control the page does not have. Worse, and
              invisible: it invites an interaction that cannot exist, and the
              reader learns nothing from the failure except that the map lies.

Neither is a "detection percentage". They are the two ways the affine map can
misdescribe what can be *done* to the page, as against what it says.

The comparison is deliberately non-circular. The REPL's side is the sensor's
own `INTERACTIVE_KIND` -- the render classes it draws as interactable. The
page's side is `groundtruth.isControl`, which decides from CONTROL_TAGS,
CONTROL_ROLES, `onclick` and `tabindex` and knows nothing of the sensor's
RENDER_CLASS table. Scoring the sensor against its own table would prove only
that the table equals itself, which is the shape of every vacuous measurement
this project has produced.

    python -m vertiscope.analytics --affordance --corpus

Writes `build_analytics/affordance.jsonl`, one row per page.
"""

from __future__ import annotations

import json
import pathlib
import sys
import time
from typing import Dict, List, Sequence

from .runs import stamp

DEFAULT_ARTIFACT_DIR = pathlib.Path("build_analytics")

#: The render classes the sensor presents as interactable, from
#: `sensor.js::INTERACTIVE_KIND`. Mirrored rather than imported because it
#: lives in JavaScript; `test_affordance.py` asserts the two agree, so this
#: copy cannot drift silently.
INTERACTIVE_KINDS = frozenset(
    ("button", "check", "choice", "field", "link", "slider"))

#: Ground-truth unit kinds that mean "the page can be interacted with here".
PAGE_INTERACTIVE = frozenset(("control", "link"))


def _owner(xpath: str) -> str:
    """The element a unit belongs to.

    Addresses reach text nodes and attributes -- `.../a/text()[1]` and
    `.../a` are the same element wearing two hats -- and an affordance is a
    property of the element, so both sides are folded to it before comparing.
    """
    at = xpath
    while at.endswith(")]") or at.rsplit("/", 1)[-1].startswith("text()"):
        cut = at.rsplit("/", 1)
        if len(cut) < 2:
            break
        at = cut[0]
    return at


def _ancestors(xpath):
    """`xpath` and every ancestor of it, longest first."""
    at = xpath
    while True:
        yield at
        cut = at.rsplit("/", 1)
        if len(cut) < 2 or not cut[0]:
            return
        at = cut[0]


def score_affordance(truth, drawn) -> dict:
    """`drawn` is an iterable of (ContentAddress, value) from one drain.

    Matched by containment rather than by equality, because the two sides
    address an affordance at different depths and both are right to.

    Ground truth marks the `<a>`; the sensor addresses the `<span>` holding
    the link's words, which inherits the link class because that is what a
    reader sees -- one link, drawn once, wherever its text physically sits.
    Compared as equal paths, `.../a/span` matched no control and every link
    on the page scored as invented: 1,198 phantoms on ar.wikipedia, against
    roughly 1,326 anchors. The sensor was right and the comparison was wrong,
    which is the failure this file's own docstring warns about, arrived at
    from the other direction.

    So a drawn control is real when it, or any ancestor of it, is a control in
    the page; and a page control is presented when it, or anything inside it,
    is drawn as one.
    """
    # Two sets, because the two errors ask different questions and a single
    # `drawn` filter answers only one of them.
    #
    # `page_any` is every control the page has, drawn or not, and it decides
    # what counts as a **phantom**: the REPL invents an affordance only when
    # nothing on the drawn line's ancestor chain is a control at all. A link
    # inside a collapsed section is a real link; presenting it is not a
    # fiction. Filtering this set to drawn controls took phantoms from 8 to
    # 8,701 across the corpus, every one of them a control the page genuinely
    # has.
    #
    # `page_drawn` is what the page lays out, and it decides what counts as
    # **missed**: the reader is denied only an affordance they could have
    # reached. Options behind a closed dropdown are not that -- `OPTION` is a
    # control tag and ground truth marks them undrawn, and counting them put
    # 1,788 of them in the denominator and took missed from 279 to 2,066.
    page_any = {u.xpath for u in truth.units if u.kind in PAGE_INTERACTIVE}
    page_drawn = {u.xpath for u in truth.units
                  if u.kind in PAGE_INTERACTIVE and u.drawn}
    page_all = {_owner(u.xpath) for u in truth.units}

    repl_yes, repl_all = set(), set()
    for address, _value in drawn:
        if address is None:
            continue
        owner = _owner(address.xpath)
        repl_all.add(owner)
        if (address.tag or "") in INTERACTIVE_KINDS:
            repl_yes.add(owner)

    covered, phantom = set(), []
    for path in sorted(repl_yes):
        # *Every* control on the ancestor chain, not the nearest one.
        #
        # Controls nest. `<details>` and its `<summary>` are both controls in
        # the page, and the disclosure's affordance *is* the summary: a reader
        # who can act on the summary can open the details. Crediting only the
        # innermost left every `<details>` uncovered and reported 54 of them
        # as unreachable -- on a page where the sensor had classed all 100
        # lines under those summaries as `button`, correctly. The sensor was
        # right and this loop was wrong.
        hits = [at for at in _ancestors(path) if at in page_any]
        if not hits:
            phantom.append(path)
        else:
            covered.update(hits)
    missed = sorted(page_drawn - covered)

    universe = page_all | repl_all
    tn = len(universe) - len(covered) - len(missed) - len(phantom)

    return {
        "tp": len(covered),
        "missed": len(missed),
        "phantom": len(phantom),
        "tn": max(tn, 0),
        "universe": len(universe),
        "page_interactive": len(page_drawn),
        "repl_interactive": len(repl_yes),
        # Precision over affordances: of what the REPL offers, how much is
        # real. This is the number a phantom degrades and coverage cannot see.
        "precision": (len(covered) / (len(covered) + len(phantom)))
                     if (covered or phantom) else 1.0,
        # Recall: of what the page offers, how much the REPL presents.
        "recall": (len(covered & page_drawn) / len(page_drawn))
                  if page_drawn else 1.0,
        "missed_sample": missed[:8],
        "phantom_sample": phantom[:8],
    }


def measure_affordance(driver, urls: Sequence[str], *,
                       context_window: int = 1200) -> dict:
    from ..markdown import render_trie
    from ..sensing import Sensor
    from ..stream import StreamingScan
    from .drift import _settle
    from .groundtruth import read_page_truth

    rows: List[dict] = []
    for url in urls:
        row: Dict[str, object] = {"url": url}
        try:
            driver.get("about:blank")
            driver.get(url)
            time.sleep(1.6)
            sensor = Sensor(driver, url, budget=context_window)
            sensor.boot()
            time.sleep(0.6)
            spine = StreamingScan(url, context_window=context_window)
            _settle(sensor, spine)
            truth = read_page_truth(driver, url)
            # Two different questions, and this file used to ask only the
            # first while its report claimed to answer the second.
            #
            # `held` is the trie: did the fold *capture* the affordance.
            # `presented` is `render_trie`: does the REPL *draw* it. A reader
            # acts on what the projection puts in front of them, so the goal's
            # question -- are the page's interactive elements interactable in
            # the REPL -- is the second one. Scored on the trie, ja.wikipedia
            # reports recall 1.0 while a visible `カテゴリ` link has no
            # rendered line at its anchor or any ancestor of it.
            held = [(leaf.address, leaf.value)
                    for leaf in spine.trie.leaves() if leaf.address]
            out = render_trie(spine.trie, context_window=context_window)
            chunks = out[0] if isinstance(out, tuple) else out
            presented = [(line.address, line.text)
                         for chunk in chunks for line in chunk.lines
                         if line.address is not None]
            row.update(score_affordance(truth, held))
            for key, value in score_affordance(truth, presented).items():
                row["drawn_" + key] = value
        except Exception as exc:                       # noqa: BLE001
            row["error"] = "{}: {}".format(type(exc).__name__, exc)[:200]
        rows.append(row)
        print("  [{}/{}] {}".format(
            len(rows), len(urls),
            row.get("error") or "tp={} missed={} phantom={}".format(
                row.get("tp"), row.get("missed"), row.get("phantom"))),
            file=sys.stderr, flush=True)
    return {"rows": rows, "context_window": context_window, "t": time.time()}


def render_affordance_table(report: dict) -> str:
    rows = [r for r in report.get("rows", []) if not r.get("error")]
    if not rows:
        return "  no affordance measurements"

    out = ["", "  what the REPL offers to interact with, against what the page "
           "can be", ""]
    out.append("  {:<44}{:>7}{:>9}{:>9}{:>11}{:>9}".format(
        "page", "real", "missed", "phantom", "precision", "recall"))
    for row in sorted(rows, key=lambda r: -(r["missed"] + r["phantom"])):
        label = row["url"].rsplit("/", 1)[-1]
        label = label[:-5] if label.endswith(".html") else label
        out.append("  {:<44}{:>7}{:>9}{:>9}{:>10.1f}%{:>8.1f}%".format(
            label[:43], row["tp"], row["missed"], row["phantom"],
            100.0 * row["precision"], 100.0 * row["recall"]))

    tp = sum(r["tp"] for r in rows)
    missed = sum(r["missed"] for r in rows)
    phantom = sum(r["phantom"] for r in rows)
    clean = [r for r in rows if not r["missed"] and not r["phantom"]]
    out.append("")
    out.append("  pages measured              {:>6}".format(len(rows)))
    out.append("  exact both ways             {:>6}".format(len(clean)))
    dtp = sum(r.get("drawn_tp", 0) for r in rows)
    dmissed = sum(r.get("drawn_missed", 0) for r in rows)
    dphantom = sum(r.get("drawn_phantom", 0) for r in rows)
    out.append("  affordances the page has    {:>6}".format(tp + missed))
    out.append("  ...the fold captured        {:>6}".format(tp))
    out.append("  MISSED by capture           {:>6}".format(missed))
    out.append("  PHANTOM (invented)          {:>6}".format(phantom))
    out.append("")
    out.append("  ...the REPL actually draws  {:>6}".format(dtp))
    out.append("  MISSED by the projection    {:>6}   a reader cannot act on "
               "these".format(dmissed))
    out.append("  PHANTOM in the projection   {:>6}".format(dphantom))
    out.append("")
    out.append("  Capture and presentation are different questions and only")
    out.append("  the first was being asked: `drawn` was the trie's leaves.")
    out.append("  An affordance the fold holds and the renderer omits is one")
    out.append("  the reader cannot reach, and it scored as present.")
    out.append("")
    out.append("  A phantom is the worse error. A missed control is visible --")
    out.append("  a reader looking for a button finds prose. An invented one")
    out.append("  invites an interaction that cannot exist, and teaches the")
    out.append("  reader nothing except that the map lies.")
    out.append("")
    out.append("  The page's side is `groundtruth.isControl` -- tags, roles,")
    out.append("  onclick, tabindex -- which knows nothing of the sensor's")
    out.append("  RENDER_CLASS. Scored against the sensor's own table this")
    out.append("  would only show that the table equals itself.")
    return chr(10).join(out)


def write_affordance_artifact(report: dict,
                              out_dir: pathlib.Path = DEFAULT_ARTIFACT_DIR
                              ) -> pathlib.Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "affordance.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        for row in report.get("rows", []):
            record = stamp(dict(row))
            record["t"] = report.get("t")
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    return path
