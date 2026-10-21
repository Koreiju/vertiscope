"""The result tables the REPL renders. Full, never truncated, always paired.

Three tables, because three different questions are being asked and one
table that answers all of them answers none of them well:

  variants   every configuration against every other, on the pages every one
             of them completed. The contrast.
  detection  per page: was a search control found, was a pager found, was it
             enacted, did the document grow, how many pages were reached.
             The rate.
  pages      per page under one configuration, so a page that behaves oddly
             can be found rather than averaged away.

Nothing here truncates. A table that shows the top ten configurations is a
table that hides the ones that regressed, and the regressions are the
findings.
"""

from __future__ import annotations

import collections
import json
import pathlib
import statistics
from typing import Dict, List
from urllib.parse import urlsplit

RUNS = pathlib.Path("build_sweep/runs.jsonl")

# Axes that are on in every configuration and so say nothing about which one
# a row was; excluded when reporting what a run actually ran.
_BASELINE_FLAGS = {"cache", "charwatch", "gate", "intern"}


def load(path=None) -> List[dict]:
    p = pathlib.Path(path) if path else RUNS
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
            continue          # a partial write from a killed process
    return out


def trustworthy(r: dict) -> bool:
    """Reject a row that cannot be describing the run it claims to.

    A row whose payload never carried a variants block came from a pass that
    was not the read — a small trailing drain after a redirect re-booted the
    sensor. Those rows reported 2% of the true wire, and because a redirect
    hits whichever configuration happens to be scheduled when it occurs, they
    scattered across unrelated mechanisms and made three of them look like
    80% wins. Dropping them is not tidying the data; it is refusing to
    average a measurement with a non-measurement.
    """
    return bool(r.get("ok")) and bool(r.get("variants_reported"))


def _fmt(n, width, comma=True):
    return f"{n:{width},}" if comma else f"{n:{width}}"


def variants_table(rows: List[dict]) -> str:
    d = [r for r in rows if r.get("tier") == "depth" and trustworthy(r)]
    dropped = sum(1 for r in rows if r.get("tier") == "depth"
                  and r.get("ok") and not trustworthy(r))
    if not d:
        return ("  no trustworthy depth rows yet"
                + (f" ({dropped} dropped: no variants block)" if dropped
                   else "") + "\n")
    by: Dict[str, Dict[str, dict]] = collections.defaultdict(dict)
    for r in d:
        by[r["variant"]][r["url"]] = r
    if "default" not in by:
        return "  no `default` rows yet — nothing to compare against\n"
    common = set(by["default"])
    for v in by.values():
        common &= set(v)
    if not common:
        counts = ", ".join(f"{n}:{len(v)}" for n, v in
                           sorted(by.items(), key=lambda x: -len(x[1]))[:6])
        return ("  no page completed under every configuration yet\n"
                f"  furthest along — {counts}\n")

    def agg(n):
        v = by[n]
        w = sum(v[u]["wire_bytes"] for u in common)
        ln = sum(v[u]["lines"] for u in common)
        return w, ln, w / max(1, ln)

    bw = agg("default")[2]
    out = [f"  paired on {len(common)} page(s) x {len(by)} configuration(s)"
           + (f"   [{dropped} row(s) dropped: no variants block]"
              if dropped else ""),
           "",
           f"  {'configuration':14s}{'B/line':>9s}{'vs def':>9s}"
           f"{'wire B':>12s}{'lines':>8s}{'chunks':>8s}{'ln/chunk':>9s}"
           f"{'ms/line':>9s}{'pages':>7s}{'search':>8s}{'pager':>7s}"
           f"{'enact':>7s}"]
    for name in sorted(by, key=lambda n: agg(n)[2] if common <= set(by[n])
                       else float("inf")):
        v = by[name]
        if not common <= set(v):
            continue
        w, ln, bpl = agg(name)
        ch = sum(v[u]["chunks"] for u in common)
        ms = sum(v[u]["drain_ms"] for u in common)
        pg = sum(v[u]["pages_reached"] for u in common)
        se = sum(1 for u in common if v[u]["search_found"])
        pa = sum(1 for u in common if v[u]["pagination_found"])
        en = sum(v[u]["controls_enacted"] for u in common)
        delta = (bpl - bw) / bw if bw else 0.0
        out.append(f"  {name:14s}{bpl:9.1f}{delta:+8.1%} {w:12,d}{ln:8,d}"
                   f"{ch:8,d}{ln / max(1, ch):9.2f}{ms / max(1, ln):9.3f}"
                   f"{pg:7d}{se:8d}{pa:7d}{en:7d}")
    return "\n".join(out) + "\n"


def detection_table(rows: List[dict], limit: int = 0) -> str:
    """Per-page detection outcome. The rate, and the pages behind it."""
    d = [r for r in rows if trustworthy(r) and r.get("variant") == "default"]
    if not d:
        return "  no default rows yet\n"
    d.sort(key=lambda r: r.get("t", 0))
    out = [f"  {len(d)} page(s) under `default`, newest last", "",
           f"  {'page':56s}{'lines':>7s}{'chunks':>7s}{'srch':>6s}"
           f"{'pagr':>6s}{'enact':>7s}{'pages':>7s}{'grew':>6s}{'s':>6s}"]
    shown = d[-limit:] if limit else d
    for r in shown:
        u = r["url"]
        out.append(
            f"  {u[:56]:56s}{r['lines']:7,d}{r['chunks']:7,d}"
            f"{r['search_found']:6d}{r['pagination_found']:6d}"
            f"{r['controls_enacted']:7d}{r['pages_reached']:7d}"
            f"{'yes' if r['final_lines'] > r['opened_lines'] else '-':>6s}"
            f"{r['elapsed_s']:6.1f}")
    se = sum(1 for r in d if r["search_found"])
    pa = sum(1 for r in d if r["pagination_found"])
    en = sum(1 for r in d if r["controls_enacted"])
    gr = sum(1 for r in d if r["final_lines"] > r["opened_lines"])
    mp = sum(1 for r in d if r["pages_reached"] > 1)
    hosts = len({r["host"] for r in d})
    el = [r["elapsed_s"] for r in d]
    out += ["",
            f"  hosts {hosts}   search {se}/{len(d)} ({se/len(d):.0%})"
            f"   pager {pa}/{len(d)} ({pa/len(d):.0%})"
            f"   enacted {en}/{len(d)} ({en/len(d):.0%})",
            f"  grew on scroll {gr}/{len(d)} ({gr/len(d):.0%})"
            f"   reached >1 page {mp}/{len(d)} ({mp/len(d):.0%})"
            f"   median {statistics.median(el):.1f}s"]
    return "\n".join(out) + "\n"


def failures_table(rows: List[dict]) -> str:
    bad = [r for r in rows if not r.get("ok")]
    untrusted = [r for r in rows if r.get("ok") and not trustworthy(r)]
    if not bad and not untrusted:
        return "  none\n"
    out = []
    for label, group in (("failed", bad), ("no variants block", untrusted)):
        if not group:
            continue
        c = collections.Counter((r.get("error") or label)[:56] for r in group)
        for e, n in c.most_common(8):
            out.append(f"  {n:5d}  {e}")
    return "\n".join(out) + "\n"


def summary(rows: List[dict]) -> str:
    d = [r for r in rows if r.get("tier") == "depth"]
    b = [r for r in rows if r.get("tier") == "breadth"]
    panel = pathlib.Path("build_sweep/depth.txt")
    urls = pathlib.Path("build_sweep/urls.txt")
    n_panel = (len(panel.read_text(encoding="utf-8").splitlines())
               if panel.exists() else 0)
    n_urls = (len(urls.read_text(encoding="utf-8").splitlines())
              if urls.exists() else 0)
    return (f"  corpus {n_urls:,} url(s)   panel {n_panel} page(s)   "
            f"rows {len(rows):,} (depth {len(d):,}, breadth {len(b):,})\n")


def compare_table(rows: List[dict]) -> str:
    """The encoding contrast: one page load, every axis against it.

    Pages are aggregated only over those every axis read, and the per-page
    line count is reported so a page whose content moved mid-run is visible
    rather than folded into the mean.
    """
    d = [r for r in rows if r.get("variants_reported") or r.get("variant") == "default"]
    if not d:
        return "  no comparison rows yet\n"
    by: Dict[str, Dict[str, dict]] = collections.defaultdict(dict)
    for r in d:
        by[r["variant"]][r["url"]] = r
    if "default" not in by:
        return "  no `default` rows yet\n"
    common = set(by["default"])
    for v in by.values():
        common &= set(v)
    if not common:
        return "  no page read by every axis yet\n"

    # One load per page, enforced. Rows carry the id of the page load they
    # were read against; a page whose rows span two loads was resumed across
    # an interruption, and comparing an axis read before the reload with one
    # read after is comparing two documents. Keep only the newest load.
    newest: Dict[str, str] = {}
    for r in d:
        u, lid = r.get("url"), r.get("load")
        if not lid:
            continue
        if u not in newest or lid > newest[u]:
            newest[u] = lid
    if newest:
        d = [r for r in d
             if r.get("url") not in newest
             or r.get("load") == newest[r["url"]]]
        by = collections.defaultdict(dict)
        for r in d:
            by[r["variant"]][r["url"]] = r
        common = set(by.get("default", {}))
        for v in by.values():
            common &= set(v)
        if not common:
            return "  no page has a single complete load yet" + chr(10)

    # The check that makes the rest meaningful: on one page load the line
    # count must be identical across axes that do not drop content. Where it
    # is not, the page moved and the row is not a contrast.
    spread = {}
    for u in common:
        counts = {by[n][u]["lines"] for n in by if u in by[n]}
        spread[u] = (min(counts), max(counts))
    moved = [u for u, (lo, hi) in spread.items() if hi and (hi - lo) / hi > 0.05]

    bw = (sum(by["default"][u]["wire_bytes"] for u in common)
          / max(1, sum(by["default"][u]["lines"] for u in common)))
    out = [f"  {len(common)} page(s) x {len(by)} axes, one load each"
           + (f"   [{len(moved)} page(s) moved mid-run]" if moved else ""),
           "",
           f"  {'axis':14s}{'B/line':>9s}{'vs def':>9s}{'wire B':>12s}"
           f"{'lines':>8s}{'chunks':>8s}{'ms':>9s}"]

    def bpl(n):
        v = by[n]
        return (sum(v[u]["wire_bytes"] for u in common)
                / max(1, sum(v[u]["lines"] for u in common)))

    for n in sorted((x for x in by if common <= set(by[x])), key=bpl):
        v = by[n]
        w = sum(v[u]["wire_bytes"] for u in common)
        ln = sum(v[u]["lines"] for u in common)
        ch = sum(v[u]["chunks"] for u in common)
        ms = sum(v[u]["drain_ms"] for u in common)
        out.append(f"  {n:14s}{bpl(n):9.1f}{(bpl(n)-bw)/bw:+8.1%} {w:12,d}"
                   f"{ln:8,d}{ch:8,d}{ms:9.0f}")
    return "\n".join(out) + "\n"


def passes_table(rows: List[dict]) -> str:
    """Cost across reads: the cold read, the warm reads, and the total.

    The split is the point. A mechanism that only shrinks the first payload
    and one that only shrinks every payload after it are different
    propositions, and a single total hides which is which — `subtreegate`
    costs nothing cold and is the largest saving warm.
    """
    d = [r for r in rows if r.get("variants_reported")]
    if not d:
        return "  no multi-pass rows yet\n"
    by: Dict[str, Dict[str, dict]] = collections.defaultdict(dict)
    for r in d:
        by[r["variant"]][r["url"]] = r
    if "default" not in by:
        return "  no `default` rows yet\n"
    common = set(by["default"])
    for v in by.values():
        common &= set(v)
    if not common:
        return "  no page read by every axis yet\n"

    def agg(n):
        v = by[n]
        return (sum(v[u]["wire_bytes"] for u in common),
                sum(v[u].get("cold_bytes", 0) for u in common),
                sum(v[u].get("warm_bytes", 0) for u in common),
                sum(v[u]["drain_ms"] for u in common))

    bt, bc, bw, _ = agg("default")
    out = [f"  {len(common)} page(s) x {len(by)} axes, "
           f"cold read + 5 scripted mutations each", "",
           f"  {'axis':14s}{'total B':>11s}{'vs def':>9s}"
           f"{'cold B':>11s}{'warm B':>11s}{'warm vs def':>13s}{'ms':>9s}"]
    for n in sorted((x for x in by if common <= set(by[x])),
                    key=lambda x: agg(x)[0]):
        t, c, w, ms = agg(n)
        dt = (t - bt) / bt if bt else 0.0
        dw = (w - bw) / bw if bw else 0.0
        out.append(f"  {n:14s}{t:11,d}{dt:+8.1%}{c:11,d}{w:11,d}"
                   f"{dw:+12.1%}{ms:9,.0f}")
    return "\n".join(out) + "\n"
