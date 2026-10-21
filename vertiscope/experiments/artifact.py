"""Render the sweep's current state as a self-contained page.

Generated from runs.jsonl rather than written by hand, so the tables cannot
drift from the measurements they claim to report.
"""

from __future__ import annotations

import collections
import datetime
import html
import pathlib
import statistics
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))
from vertiscope.experiments.analyse import load  # noqa: E402

CSS = """
:root{
  --ground:#F7F8FA; --surface:#FFFFFF; --sunken:#EEF1F5;
  --ink:#12161C; --ink-2:#454E5C; --ink-3:#6B7686; --rule:#DDE3EA;
  --accent:#2D7D8A; --accent-soft:#E4F1F3;
  --good:#2F7D4F; --warn:#A9791C; --bad:#A6392F;
}
@media (prefers-color-scheme:dark){
  :root:not([data-theme="light"]){
    --ground:#0E1116; --surface:#161B22; --sunken:#1B222B;
    --ink:#E6EAF0; --ink-2:#A7B2C0; --ink-3:#78838F; --rule:#252D38;
    --accent:#5FB3C0; --accent-soft:#123034;
    --good:#5FBF87; --warn:#D6A445; --bad:#E0776B;
  }
}
:root[data-theme="dark"]{
  --ground:#0E1116; --surface:#161B22; --sunken:#1B222B;
  --ink:#E6EAF0; --ink-2:#A7B2C0; --ink-3:#78838F; --rule:#252D38;
  --accent:#5FB3C0; --accent-soft:#123034;
  --good:#5FBF87; --warn:#D6A445; --bad:#E0776B;
}
*{box-sizing:border-box}
body{
  margin:0; background:var(--ground); color:var(--ink);
  font-family:"IBM Plex Sans",-apple-system,BlinkMacSystemFont,sans-serif;
  font-size:16px; line-height:1.6;
}
.wrap{max-width:1080px; margin:0 auto; padding:48px 24px 96px;
  display:flex; flex-direction:column; gap:40px}
h1{font-family:Bitter,Georgia,serif; font-size:2.1rem; line-height:1.15;
  margin:0; letter-spacing:-.01em; text-wrap:balance; font-weight:600}
h2{font-family:Bitter,Georgia,serif; font-size:1.3rem; margin:0 0 4px;
  font-weight:600; text-wrap:balance}
p{margin:0; max-width:68ch; color:var(--ink-2)}
.eyebrow{font-family:"IBM Plex Mono",monospace; font-size:.72rem;
  letter-spacing:.14em; text-transform:uppercase; color:var(--accent);
  margin:0 0 10px}
section{display:flex; flex-direction:column; gap:14px}
.strip{display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr));
  gap:1px; background:var(--rule); border:1px solid var(--rule);
  border-radius:3px; overflow:hidden}
.cell{background:var(--surface); padding:14px 16px}
.cell .k{font-size:.7rem; letter-spacing:.09em; text-transform:uppercase;
  color:var(--ink-3); margin-bottom:4px}
.cell .v{font-family:"IBM Plex Mono",monospace; font-size:1.35rem;
  font-variant-numeric:tabular-nums; color:var(--ink)}
.cell .s{font-family:"IBM Plex Mono",monospace; font-size:.72rem;
  color:var(--ink-3)}
.scroll{overflow-x:auto; border:1px solid var(--rule); border-radius:3px;
  background:var(--surface)}
table{border-collapse:collapse; width:100%;
  font-family:"IBM Plex Mono",monospace;
  font-size:.8rem; font-variant-numeric:tabular-nums}
th{text-align:right; padding:9px 12px; background:var(--sunken);
  color:var(--ink-3); font-weight:600; font-size:.7rem;
  letter-spacing:.07em; text-transform:uppercase; white-space:nowrap;
  border-bottom:1px solid var(--rule)}
th:first-child,td:first-child{text-align:left}
td{padding:8px 12px; border-bottom:1px solid var(--rule); white-space:nowrap}
tr:last-child td{border-bottom:0}
tbody tr:hover td{background:var(--sunken)}
.win{color:var(--good)} .lose{color:var(--bad)} .flat{color:var(--ink-3)}
.base td{background:var(--accent-soft)}
.note{border-left:2px solid var(--accent); padding:2px 0 2px 16px;
  color:var(--ink-2); max-width:68ch}
.pill{display:inline-block; font-family:"IBM Plex Mono",monospace;
  font-size:.68rem; padding:2px 8px; border-radius:2px; letter-spacing:.05em;
  text-transform:uppercase; background:var(--accent-soft); color:var(--accent)}
footer{color:var(--ink-3); font-size:.8rem; border-top:1px solid var(--rule);
  padding-top:20px}
ul{margin:0; padding-left:20px; color:var(--ink-2); max-width:68ch}
li{margin-bottom:6px}
code{font-family:"IBM Plex Mono",monospace; font-size:.85em}
"""


def _cells(items):
    out = []
    for k, v, s in items:
        out.append('<div class="cell"><div class="k">' + html.escape(k)
                   + '</div><div class="v">' + html.escape(str(v))
                   + '</div><div class="s">' + html.escape(s) + "</div></div>")
    return '<div class="strip">' + "".join(out) + "</div>"


def _depth_table(rows):
    d = [r for r in rows if r.get("tier") == "depth" and r.get("ok")]
    by = collections.defaultdict(dict)
    for r in d:
        by[r["variant"]][r["url"]] = r
    if "default" not in by:
        return ("<p class='note'>No configuration has completed a shared page "
                "set yet.</p>")
    common = set(by["default"])
    for v in by.values():
        common &= set(v)
    if not common:
        return ("<p class='note'>No page has yet completed under every "
                "configuration; the paired table appears once one has.</p>")
    base = sum(by["default"][u]["wire_bytes"] for u in common)
    head = ("<tr><th>configuration</th><th>wire</th><th>vs default</th>"
            "<th>lines</th><th>chunks</th><th>drain ms</th>"
            "<th>pages</th><th>search</th><th>pager</th></tr>")
    order = sorted((n for n in by if common <= set(by[n])),
                   key=lambda n: sum(by[n][u]["wire_bytes"] for u in common))
    body = []
    for n in order:
        v = by[n]
        w = sum(v[u]["wire_bytes"] for u in common)
        dl = (w - base) / base if base else 0.0
        cls = "win" if dl < -0.01 else ("lose" if dl > 0.01 else "flat")
        row_cls = "base" if n == "default" else ""
        body.append(
            '<tr class="' + row_cls + '"><td>' + html.escape(n) + "</td>"
            + "<td>{:,}</td>".format(w)
            + '<td class="' + cls + '">{:+.1%}</td>'.format(dl)
            + "<td>{:,}</td>".format(sum(v[u]["lines"] for u in common))
            + "<td>{:,}</td>".format(sum(v[u]["chunks"] for u in common))
            + "<td>{:,.0f}</td>".format(sum(v[u]["drain_ms"] for u in common))
            + "<td>{}</td>".format(sum(v[u]["pages_reached"] for u in common))
            + "<td>{}</td>".format(
                sum(1 for u in common if v[u]["search_found"]))
            + "<td>{}</td></tr>".format(
                sum(1 for u in common if v[u]["pagination_found"])))
    return ("<p class='note'>Paired on the {} page(s) every one of {} "
            "configurations completed &mdash; an unpaired mean flatters "
            "whichever run skipped the hard pages.</p>"
            "<div class='scroll'><table>{}{}</table></div>").format(
        len(common), len(order), head, "".join(body))


def render(rows, out_path="build_sweep/sweep.html") -> str:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    b = [r for r in rows if r.get("tier") == "breadth"]
    bok = [r for r in b if r.get("ok")]

    urls = pathlib.Path("build_sweep/urls.txt")
    n_urls = (len(urls.read_text(encoding="utf-8").splitlines())
              if urls.exists() else 0)

    se = sum(1 for r in bok if r["search_found"])
    pa = sum(1 for r in bok if r["pagination_found"])
    el = [r["elapsed_s"] for r in bok] or [0]
    strip = _cells([
        ("Corpus", "{:,}".format(n_urls), "urls harvested"),
        ("Scanned", "{:,}".format(len(bok)),
         "{:,} failed".format(len(b) - len(bok))),
        ("Hosts", "{:,}".format(len({r["host"] for r in bok})), "distinct"),
        ("Search found", "{:.0%}".format(se / max(1, len(bok))),
         "{:,} pages".format(se)),
        ("Pager found", "{:.0%}".format(pa / max(1, len(bok))),
         "{:,} pages".format(pa)),
        ("Per page", "{:.1f}s".format(statistics.median(el)),
         "median, 10 scrolls"),
    ])

    doc = (
        "<title>Recursive Chunking Sweep</title>\n"
        '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>\n'
        '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?'
        "family=Bitter:wght@500;600&family=IBM+Plex+Mono:wght@400;600"
        '&family=IBM+Plex+Sans:wght@400;600&display=swap">\n'
        "<style>" + CSS + "</style>\n"
        '<div class="wrap">\n'
        "<header>\n"
        '  <p class="eyebrow">Snapshot &middot; taken '
        + html.escape(now) + "</p>\n"
        "  <h1>Shadow-DOM recursive chunking, measured against itself</h1>\n"
        "  <p>Every configuration of the in-page sensor, run end-to-end "
        "through the real REPL over a corpus harvested by scoping DuckDuckGo "
        "searches. Ten scrolls per page, live pagination, retrieval out of "
        'the store. Nothing stubbed. <span class="pill">sweep running</span>'
        "</p>\n</header>\n\n"
        "<section>\n  <h2>Where it stands</h2>\n  " + strip + "\n</section>\n\n"
        "<section>\n  <h2>Configurations, paired</h2>\n  "
        + _depth_table(rows) + "\n</section>\n\n"
        "<section>\n  <h2>How this is measured</h2>\n"
        "  <p>The arithmetic forces a two-tier design, and pretending "
        "otherwise would produce a number nobody should trust. At the "
        "measured throughput, running every configuration across five "
        "thousand pages is weeks of wall clock.</p>\n"
        "  <ul>\n"
        "    <li><strong>Breadth</strong> &mdash; many pages, one "
        "configuration. A detection <em>rate</em> needs pages, not "
        "configurations.</li>\n"
        "    <li><strong>Depth</strong> &mdash; a host-stratified page "
        "sample, every configuration, ten scrolls each. A <em>contrast</em> "
        "needs configurations held against the same pages.</li>\n"
        "  </ul>\n"
        "  <p>The corpus caps each host at twelve pages, so one large site "
        "cannot stand in for the open web.</p>\n</section>\n\n"
        "<footer>Generated from <code>build_sweep/runs.jsonl</code> &mdash; "
        "the tables are rendered from the measurements, never transcribed."
        "</footer>\n</div>")
    p = pathlib.Path(out_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(doc, encoding="utf-8")
    return str(p)


if __name__ == "__main__":
    print(render(load()))
