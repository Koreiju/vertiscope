"""Does the token window hold *throughout processing*? -- `S-11`.

The chunker compares each subtree's render against ``context_window`` as it
cuts, and that has been measured. `S-11` asks something wider: that the
window still holds **after** the scan, through every later stage, and that
there is a **verification pass** which says so rather than a chunker that
believed itself.

The difference is not pedantic. Two stages after chunking produce strings
nobody re-measured:

* **Merge groups.** `G-26` assembles a group's members' markdown into one
  document-ordered string, and that string is what a reader is shown and
  what re-vectorisation embeds. It is by construction longer than any
  member. Nothing checked it against the window.
* **The encoder's own view.** `tokens.for_model` drops code spans, so a
  ``code://`` chunk spends a different number of tokens than its render
  suggests. ``budget_for`` is the function that knows this, and it is the
  one this pass uses -- a budget enforced on one string and spent on
  another is not a budget.

**Two denominators, because there are two questions.** The row says the
window is a target, not a ceiling, and that a single indivisible unit may
exceed it. So an over-window chunk is only a defect when it could have been
cut. A chunk of one line is a leaf the chunker was right to emit whole; a
chunk of several lines that is over the window is a cut that did not
happen. Reporting one number over both would either excuse the second or
condemn the first, and this file has a whole section of `CLAUDE.md` behind
it.

    python -m vertiscope.analytics --window --workspace build/corpus123
    python -m vertiscope.analytics --window --workspace build/corpus123 --plant
"""

from __future__ import annotations

import json
import pathlib
import statistics
from typing import Dict, List, Optional

from .. import tokens

DEFAULT_ARTIFACT_DIR = pathlib.Path("build_analytics")


def _summarise(costs: List[int], window: int) -> Dict[str, object]:
    if not costs:
        return {"n": 0, "over": 0, "pct_over": 0.0,
                "max": 0, "mean": 0.0, "p95": 0}
    ordered = sorted(costs)
    over = [c for c in costs if c > window]
    return {
        "n": len(costs),
        "over": len(over),
        "pct_over": round(100.0 * len(over) / len(costs), 2),
        "max": ordered[-1],
        "mean": round(statistics.mean(costs), 1),
        "p95": ordered[max(int(len(ordered) * 0.95) - 1, 0)],
    }


def measure_window(workspace_root: str, *, window: int = 256,
                   plant: bool = False,
                   limit: int = 0) -> Dict[str, object]:
    """Score every chunk, and every merge group, against the window.

    ``plant`` is the non-vacuity arm: it injects one synthetic record that
    is certainly over, so a pass reporting zero for the wrong reason -- an
    empty store, a budget function returning 0, a filter that excluded
    everything -- is caught by the planted defect NOT being caught.
    """
    from ..workspace import Workspace

    ws = Workspace(workspace_root, read_only=True)
    try:
        rows = ws.store._rows(
            "MATCH (c:Chunk) RETURN c.cid, c.url, c.md, c.line_count, "
            "c.group_of, c.group_n")
    finally:
        ws.close()

    records = []
    for cid, url, md, line_count, group_of, group_n in rows:
        records.append({
            "cid": cid, "url": url or "", "md": md or "",
            "lines": int(line_count or 0),
            "group_of": group_of or "", "group_n": int(group_n or 1),
        })
    if limit:
        records = records[:limit]

    if plant:
        # Multi-line, so it lands in the DIVISIBLE bucket -- the bucket that
        # is supposed to be empty. A single-line planting would be excused
        # by the rule the row itself states and would prove nothing.
        body = "\n".join("planted oversize line number %d, with enough words "
                         "in it to cost real tokens" % i for i in range(60))
        records.append({"cid": "planted", "url": "https://planted.test/over",
                        "md": body, "lines": 60,
                        "group_of": "", "group_n": 1})

    # ---- stage one: the chunks themselves --------------------------------
    divisible: List[int] = []
    indivisible: List[int] = []
    overs: List[Dict[str, object]] = []
    for rec in records:
        cost = tokens.budget_for(rec["md"], rec["url"])
        rec["cost"] = cost
        if rec["lines"] > 1:
            divisible.append(cost)
        else:
            indivisible.append(cost)
        if cost > window:
            overs.append({"cid": rec["cid"], "url": rec["url"],
                          "cost": cost, "lines": rec["lines"],
                          "divisible": rec["lines"] > 1})

    # ---- stage two: the merge groups -------------------------------------
    #
    # The stage that had never been checked. A group's assembled markdown is
    # a NEW string, longer than any member by construction.
    by_group: Dict[str, List[Dict]] = {}
    for rec in records:
        if rec["group_of"] and rec["group_n"] > 1:
            by_group.setdefault(rec["group_of"], []).append(rec)

    group_costs: List[int] = []
    group_overs: List[Dict[str, object]] = []
    for lead, members in by_group.items():
        assembled = "\n\n".join(m["md"] for m in members)
        cost = tokens.budget_for(assembled, members[0]["url"])
        group_costs.append(cost)
        if cost > window:
            group_overs.append({"group_of": lead, "url": members[0]["url"],
                                "members": len(members), "cost": cost})

    report: Dict[str, object] = {
        "workspace": str(workspace_root),
        "window": window,
        "planted": bool(plant),
        "chunks": {
            "divisible": _summarise(divisible, window),
            "indivisible": _summarise(indivisible, window),
        },
        "groups": _summarise(group_costs, window),
        "worst_chunks": sorted(overs, key=lambda r: -r["cost"])[:20],
        "worst_groups": sorted(group_overs, key=lambda r: -r["cost"])[:20],
    }

    if plant:
        report["plant_caught"] = any(o["cid"] == "planted" for o in overs)
        report["plant_cost"] = next(
            (o["cost"] for o in overs if o["cid"] == "planted"), None)
    return report


def render_window_table(report: Dict[str, object]) -> str:
    w = report["window"]
    out = ["", "  the token window, after the scan  (window = %d)" % w, ""]
    out.append("  %-16s %7s %7s %8s %7s %7s"
               % ("population", "n", "over", "% over", "max", "mean"))
    for name, key in (("chunks, cuttable", "divisible"),
                      ("chunks, leaves", "indivisible")):
        s = report["chunks"][key]
        out.append("  %-16s %7d %7d %8.2f %7d %7.1f"
                   % (name, s["n"], s["over"], s["pct_over"],
                      s["max"], s["mean"]))
    g = report["groups"]
    out.append("  %-16s %7d %7d %8.2f %7d %7.1f"
               % ("merge groups", g["n"], g["over"], g["pct_over"],
                  g["max"], g["mean"]))
    out.append("")
    out.append("  A leaf over the window is the record rule working: a single")
    out.append("  indivisible unit may exceed it. A CUTTABLE chunk over the")
    out.append("  window is a cut that did not happen.")
    if report.get("planted"):
        out.append("")
        out.append("  planted defect caught: %s (cost %s)"
                   % (report.get("plant_caught"), report.get("plant_cost")))
    return "\n".join(out)


def write_window_artifact(report: Dict[str, object],
                          out_dir: Optional[pathlib.Path] = None) -> str:
    out_dir = pathlib.Path(out_dir or DEFAULT_ARTIFACT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "window.json"
    path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    return str(path)
