"""Durable record of what a sweep did, and what it still owes.

Three separate concerns that kept getting conflated:

  record    the measurements themselves, one JSON object per run, flushed as
            they are produced so a killed process loses at most the run in
            flight. Already `runs.jsonl` / `compare.jsonl`.
  journal   a timestamped, human-readable line per event. The record says
            what was measured; the journal says what *happened* — including
            the things that produce no measurement, which are exactly the
            events you want when a process disappears without a completion.
  progress  what remains. Derived, never stored: a plan and a record are
            enough to compute the difference, and a third file that claims
            to know the remainder is a third file that can be wrong.

Resume keys on the **requested** url, not the settled one. A run that opens
`quotes.toscrape.com/page/1/` and scrolls ends up on `/page/5/`; recording
only where it ended means the next start cannot tell that page 1 was already
done, and re-runs it forever.
"""

from __future__ import annotations

import datetime
import json
import pathlib
from typing import Dict, Iterable, List, Set, Tuple

HOME = pathlib.Path("build_sweep")
JOURNAL = HOME / "journal.log"


def log(event: str, detail: str = "") -> None:
    """Append one timestamped line. Never raises — logging must not end a run."""
    try:
        HOME.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with JOURNAL.open("a", encoding="utf-8") as fh:
            fh.write(f"{stamp}  {event:<10}  {detail}\n")
    except Exception:
        pass


def tail(n: int = 40) -> str:
    if not JOURNAL.exists():
        return "  journal empty\n"
    lines = JOURNAL.read_text(encoding="utf-8", errors="replace").splitlines()
    return "\n".join("  " + x for x in lines[-n:]) + "\n"


def done_keys(rows: Iterable[dict]) -> Set[Tuple[str, str]]:
    """(requested url, variant) pairs already recorded.

    Falls back to the settled url for rows written before `requested` was
    kept, so an older record still resumes rather than starting over.
    """
    out: Set[Tuple[str, str]] = set()
    for r in rows:
        key = r.get("requested") or r.get("url")
        if key and r.get("variant"):
            out.add((key, r["variant"]))
    return out


def progress(plan_pages: List[str], plan_axes: List[str],
             rows: Iterable[dict]) -> Dict[str, object]:
    """What is done, what is left, and where the gaps are."""
    done = done_keys(rows)
    total = len(plan_pages) * len(plan_axes)
    have = sum(1 for p in plan_pages for a in plan_axes if (p, a) in done)
    per_page = []
    for p in plan_pages:
        n = sum(1 for a in plan_axes if (p, a) in done)
        per_page.append((p, n, len(plan_axes)))
    missing_axes: Dict[str, int] = {}
    for a in plan_axes:
        n = sum(1 for p in plan_pages if (p, a) not in done)
        if n:
            missing_axes[a] = n
    return {"total": total, "have": have, "left": total - have,
            "per_page": per_page, "missing_axes": missing_axes}


def status_table(plan_pages: List[str], plan_axes: List[str],
                 rows: Iterable[dict], secs_per_run: float = 0.0) -> str:
    p = progress(plan_pages, plan_axes, rows)
    pct = p["have"] / p["total"] if p["total"] else 0.0
    out = [f"  plan {len(plan_pages)} page(s) x {len(plan_axes)} axes "
           f"= {p['total']} run(s)",
           f"  done {p['have']}   left {p['left']}   ({pct:.0%})"
           + (f"   ~{p['left'] * secs_per_run / 60:.0f} min at "
              f"{secs_per_run:.1f}s/run" if secs_per_run else ""),
           "",
           f"  {'page':62s}{'done':>6s}{'of':>5s}"]
    for url, n, tot in p["per_page"]:
        mark = "" if n >= tot else "   <-- incomplete"
        out.append(f"  {url[:62]:62s}{n:6d}{tot:5d}{mark}")
    if p["missing_axes"]:
        worst = sorted(p["missing_axes"].items(), key=lambda x: -x[1])
        out += ["", "  axes with pages outstanding:",
                "  " + ", ".join(f"{a}:{n}" for a, n in worst)]
    return "\n".join(out) + "\n"


def load(path) -> List[dict]:
    p = pathlib.Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8", errors="replace").split("\n"):
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out
