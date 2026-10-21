"""What the store costs as it grows, and where that stops being answerable.

Every number this project holds is measured on 136 pages. That is the whole
evidentiary base, and "does it cover thousands" was never asked, so this file
exists to ask it rather than to assume either answer.

The question splits in two, and only one half is answerable without new
pages:

**Fidelity** -- does the fold still capture correctly across thousands of
DIFFERENT documents? Not answerable here. It needs thousands of pages nobody
has looked at, and the corpus is 136 chosen for structural variety. Re-reading
the same pages says nothing about the next one. What this file can do is
report how far the evidence actually reaches, which is `--fidelity`.

**Cost** -- do the graph, the frequency matrix, PageRank, the embeddings and
search still work when the store holds thousands? Answerable now, because the
store cannot tell a repeated page from a new one. Ingesting the corpus under
distinct urls grows every structure that scales with row count.

The second pass understates one thing on purpose and says so: a repeated page
adds no new vocabulary, so `freq_terms` grows more slowly than it would on
genuinely new documents. Everything keyed by row -- chunks, edges, PageRank,
embeddings -- is unaffected by that.

    python -m vertiscope.analytics --scale
    python -m vertiscope.analytics --scale --pages 5000
"""

from __future__ import annotations

import io
import json
import os
import pathlib
import sys
import time
from typing import Dict, List, Optional

DEFAULT_ARTIFACT_DIR = pathlib.Path("build_analytics")

#: Queries used to time retrieval. Three, so one lucky cache does not decide.
PROBE_QUERIES = ("glacier mass balance", "privacy browser settings",
                 "python programming language")


def _dir_bytes(path) -> float:
    total = 0
    for dirpath, _dirs, files in os.walk(str(path)):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, name))
            except OSError:
                pass
    return total / 1e6


def sample(ws, label: str) -> Dict[str, object]:
    """One measurement of a store at its current size."""
    started = time.perf_counter()
    ws.index.build()
    build_s = time.perf_counter() - started

    latencies = []
    for query in PROBE_QUERIES:
        at = time.perf_counter()
        try:
            ws.search(query, k=10)
        except Exception:                              # noqa: BLE001
            pass
        latencies.append(time.perf_counter() - at)

    stats = ws.stats()
    return {
        "label": label,
        "pages": stats.get("pages"),
        "chunks": stats.get("chunks"),
        "addresses": stats.get("addresses"),
        "freq_rows": stats.get("freq_rows"),
        "freq_terms": stats.get("freq_terms"),
        "build_s": round(build_s, 3),
        "search_ms": round(1000 * sum(latencies) / len(latencies), 1),
        "disk_mb": round(_dir_bytes(stats.get("path", ".")), 1),
    }


def measure_scale(corpus: List[pathlib.Path], workspace_root: str,
                  *, target: int = 2000,
                  marks: Optional[List[int]] = None) -> dict:
    """Grow a store to `target` pages, sampling as it goes."""
    from ..workspace import Workspace

    marks = sorted(set(marks or [len(corpus), 250, 500, 1000, target]))
    # Smaller pages, so the growth pass measures the STORE rather than the
    # cost of re-tagging one enormous document a thousand times.
    small = [p for p in corpus if p.stat().st_size < 120_000] or corpus
    rows: List[dict] = []
    per_page: List[float] = []

    ws = Workspace(workspace_root)
    try:
        n = 0
        while n < target:
            for page in small:
                if n >= target:
                    break
                n += 1
                html = io.open(page, encoding="utf-8", errors="replace").read()
                at = time.perf_counter()
                try:
                    ws.index_html(html, "https://p%06d.test/%s" % (n, page.stem))
                except Exception as exc:               # noqa: BLE001
                    print("  [%d] failed: %s" % (n, exc), file=sys.stderr)
                    continue
                per_page.append(time.perf_counter() - at)
                if n in marks:
                    row = sample(ws, "%d pages" % n)
                    row["ingest_ms_median"] = round(
                        1000 * sorted(per_page)[len(per_page) // 2], 1)
                    rows.append(row)
                    # Written as it goes, not at the end.
                    #
                    # The first run of this was killed by a timeout at ~500
                    # of 2000 pages and wrote nothing at all: the table and
                    # the artifact both came after the loop. A growth
                    # measurement is long by construction, so the samples it
                    # already has must survive it not finishing.
                    write_scale_artifact({"rows": [row], "t": time.time(),
                                          "corpus_pages": len(corpus)})
                    print("  %(label)-12s chunks=%(chunks)-8s "
                          "terms=%(freq_terms)-8s build=%(build_s)6.2fs "
                          "search=%(search_ms)6.1fms disk=%(disk_mb)6.1fMB"
                          % row, file=sys.stderr, flush=True)
    finally:
        ws.close()
    return {"rows": rows, "target": target, "t": time.time(),
            "corpus_pages": len(corpus), "grown_from": len(small)}


def fidelity_reach(corpus: List[pathlib.Path]) -> dict:
    """How far the fidelity evidence actually reaches. Not how good it is.

    Coverage, order, dedup and recall are all measured on this corpus and
    nowhere else. A number that holds on 136 documents is a claim about 136
    documents, and the honest way to report it at scale is to say how many
    distinct origins stand behind it.
    """
    hosts = set()
    for page in corpus:
        stem = page.stem
        # The corpus names pages after their url, dashed. The first two
        # segments are host-ish; exact recovery is not needed for a count of
        # how many different places these came from.
        hosts.add("-".join(stem.split("-")[:2]))
    total_mb = sum(p.stat().st_size for p in corpus) / 1e6
    return {"pages": len(corpus), "distinct_origins": len(hosts),
            "megabytes": round(total_mb, 1)}


def render_scale_table(report: dict) -> str:
    rows = report.get("rows", [])
    out = ["", "  what the store costs as it grows", ""]
    out.append("  %-12s %9s %9s %9s %9s %9s"
               % ("pages", "chunks", "terms", "build", "search", "disk"))
    for row in rows:
        out.append("  %-12s %9s %9s %8.2fs %8.1fms %8.1fMB"
                   % (row["label"], row["chunks"], row["freq_terms"],
                      row["build_s"], row["search_ms"], row["disk_mb"]))
    if len(rows) >= 2:
        first, last = rows[0], rows[-1]
        grew = (last["chunks"] or 1) / max(first["chunks"] or 1, 1)
        slower = (last["build_s"] or 0) / max(first["build_s"] or 1e-6, 1e-6)
        out.append("")
        out.append("  %.1fx the chunks cost %.1fx the index build"
                   % (grew, slower))
    out.append("")
    out.append("  Growth is measured by re-ingesting the corpus under")
    out.append("  distinct urls. That says nothing about capture fidelity on")
    out.append("  unseen pages -- see `--fidelity` for how far that evidence")
    out.append("  reaches -- and it understates vocabulary growth, because a")
    out.append("  repeated page brings no new words. Everything keyed by row")
    out.append("  is unaffected.")
    return chr(10).join(out)


def write_scale_artifact(report: dict,
                         out_dir: pathlib.Path = DEFAULT_ARTIFACT_DIR
                         ) -> pathlib.Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "scale.jsonl"
    with path.open("a", encoding="utf-8") as handle:
        for row in report.get("rows", []):
            record = dict(row)
            record["t"] = report.get("t")
            record["corpus_pages"] = report.get("corpus_pages")
            handle.write(json.dumps(record, separators=(",", ":")) + "\n")
    return path
