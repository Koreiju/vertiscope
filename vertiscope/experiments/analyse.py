"""Tabulate the sweep. Every configuration against every other, on one page set.

Depth rows are paired: a configuration is only compared on pages the default
also completed, so a variant that failed a hard page cannot look cheap by
having skipped it. Unpaired means are how a sweep flatters whichever run
crashed most.
"""

from __future__ import annotations

import collections
import json
import pathlib
import statistics
from typing import Dict, List


def load(path="build_sweep/runs.jsonl") -> List[dict]:
    p = pathlib.Path(path)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            out.append(json.loads(line))
        except Exception:
            continue
    return out


def _trustworthy(r: dict) -> bool:
    """Reject a row that cannot be describing the run it claims to.

    A row whose payload never carried a variants block came from a pass that
    was not the read -- a small trailing drain after a redirect re-booted the
    sensor. Such rows reported 2% of the true wire, and because a redirect
    hits whichever configuration happens to be scheduled when it happens,
    they scattered across unrelated mechanisms and made three of them look
    like 80% wins. Dropping them is not tidying the data; it is refusing to
    average a measurement with a non-measurement.
    """
    if not r.get("ok"):
        return False
    # A row without the key at all predates the fix and was measured with
    # `_passes[-1]`; absence of evidence is not evidence here, because the
    # rows that lacked it are exactly the ones measured wrongly.
    if not r.get("variants_reported"):
        return False
    return True


def depth_table(rows: List[dict]) -> str:
    d = [r for r in rows if r.get("tier") == "depth" and _trustworthy(r)]
    dropped = sum(1 for r in rows if r.get("tier") == "depth"
                  and r.get("ok") and not _trustworthy(r))
    if not d:
        return "  (no completed depth rows yet)\n"
    by = collections.defaultdict(dict)
    for r in d:
        by[r["variant"]][r["url"]] = r
    if "default" not in by:
        return "  (no default rows yet)\n"
    base = by["default"]
    common = set(base)
    for v in by.values():
        common &= set(v)
    if not common:
        return "  (no page completed under every configuration yet)\n"

    lines = [f"  paired on {len(common)} page(s) completed by every "
             f"configuration ({len(by)} configurations)"
             + (f"  [{dropped} row(s) dropped: no variants block]"
                if dropped else ""),
             f"  {'config':13s} {'B/line':>8s} {'vs def':>8s} "
             f"{'wire B':>10s} {'lines':>7s} {'chunks':>7s} {'ms/ln':>8s} "
             f"{'pages':>6s} {'search':>7s} {'pager':>6s}"]
    bw = (sum(base[u]["wire_bytes"] for u in common)
          / max(1, sum(base[u]["lines"] for u in common)))
    def per_line(n):
        v = by[n]
        return (sum(v[u]["wire_bytes"] for u in common)
                / max(1, sum(v[u]["lines"] for u in common)))

    for name in sorted((n for n in by if common <= set(by[n])), key=per_line):
        v = by[name]
        w = sum(v[u]["wire_bytes"] for u in common)
        ln = sum(v[u]["lines"] for u in common)
        ch = sum(v[u]["chunks"] for u in common)
        ms = sum(v[u]["drain_ms"] for u in common)
        pg = sum(v[u]["pages_reached"] for u in common)
        se = sum(1 for u in common if v[u]["search_found"])
        pa = sum(1 for u in common if v[u]["pagination_found"])
        bpl = per_line(name)
        delta = (bpl - bw) / bw if bw else 0.0
        lines.append(f"  {name:13s} {bpl:8.1f} {delta:+7.1%} {w:10,d} "
                     f"{ln:7d} {ch:7d} {ms / max(1, ln):8.2f} {pg:6d} "
                     f"{se:7d} {pa:6d}")
    return "\n".join(lines) + "\n"


def breadth_table(rows: List[dict]) -> str:
    b = [r for r in rows if r.get("tier") == "breadth"]
    ok = [r for r in b if r.get("ok")]
    if not ok:
        return "  (no completed breadth rows yet)\n"
    hosts = {r["host"] for r in ok}
    se = sum(1 for r in ok if r["search_found"])
    pa = sum(1 for r in ok if r["pagination_found"])
    en = sum(1 for r in ok if r["controls_enacted"])
    grew = sum(1 for r in ok if r["final_lines"] > r["opened_lines"])
    multi = sum(1 for r in ok if r["pages_reached"] > 1)
    el = [r["elapsed_s"] for r in ok]
    return (
        f"  pages scanned end-to-end : {len(b):,}  ({len(ok):,} ok, "
        f"{len(b)-len(ok):,} failed)\n"
        f"  distinct hosts           : {len(hosts):,}\n"
        f"  search control detected  : {se:,} / {len(ok):,}  "
        f"({se/len(ok):.1%})\n"
        f"  pagination detected      : {pa:,} / {len(ok):,}  "
        f"({pa/len(ok):.1%})\n"
        f"  a control was enacted    : {en:,} / {len(ok):,}  "
        f"({en/len(ok):.1%})\n"
        f"  document grew on scroll  : {grew:,} / {len(ok):,}  "
        f"({grew/len(ok):.1%})\n"
        f"  reached >1 page          : {multi:,} / {len(ok):,}  "
        f"({multi/len(ok):.1%})\n"
        f"  seconds per page         : median {statistics.median(el):.1f}, "
        f"mean {statistics.mean(el):.1f}, max {max(el):.0f}\n"
        f"  total wire               : "
        f"{sum(r['wire_bytes'] for r in ok):,} B\n")


def failures(rows: List[dict]) -> str:
    bad = [r for r in rows if not r.get("ok")]
    if not bad:
        return "  none\n"
    c = collections.Counter((r.get("error") or "?")[:60] for r in bad)
    return "".join(f"  {n:5d}  {e}\n" for e, n in c.most_common(8))


def report(path="build_sweep/runs.jsonl") -> str:
    rows = load(path)
    return (f"rows: {len(rows):,}\n\n== breadth ==\n{breadth_table(rows)}\n"
            f"== depth ==\n{depth_table(rows)}\n== failures ==\n"
            f"{failures(rows)}")


if __name__ == "__main__":
    print(report())
