#!/usr/bin/env python
"""Benchmark the pipeline over the frozen corpus with theory-grounded metrics.

Every metric here is the measurable form of a numbered result. A metric with no
result behind it would be a number nobody can act on (METHOD B.5), so each row
names what it would falsify.

    M1  coverage          fraction of tagged content xpaths reaching a chunk
    M2  antichain         are chunk roots pairwise non-nested?   (THEORY §4.1)
    M3  collapse          rendered instances lost to shared identity (THM-22.5.7)
    M4  coherence         every indexed vector in K              (PROP-13.3)
    M5  RI                representation invariant, all clauses  (MODEL §4)
    M6  RI-R1             pattern derivable from address         (PROP-22.4)
    M7  containment       indexed identifiers subset of recorded (MODEL O-5)
    M8  determinism       same input, same output
    M9  domain exercise   which of the 18 subcategories occur    (DOMAIN §2)

    python scripts/benchmark.py
    python scripts/benchmark.py --limit 10 --json out.json
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import tempfile
import time
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vertiscope import invariants as inv  # noqa: E402
from vertiscope.config import load_config  # noqa: E402
from vertiscope.core.xpath_utils import generalize_xpath  # noqa: E402
from vertiscope.ingest import ingest  # noqa: E402
from vertiscope.pipeline import run_pipeline  # noqa: E402
from vertiscope.store import Store  # noqa: E402

CORPUS = ROOT / "tests" / "corpus"
MANIFEST = CORPUS / "manifest.json"


def is_ancestor(a: str, b: str) -> bool:
    """Strict prefix in the address order (THEORY PROP-1.3/11.2)."""
    return b.startswith(a + "/")


def antichain_violations(xpaths: list[str]) -> int:
    """Pairs (a, b) with a a strict ancestor of b. Zero iff the set is a cut."""
    ordered = sorted(set(xpaths))
    bad = 0
    for i, a in enumerate(ordered):
        for b in ordered[i + 1:]:
            if not b.startswith(a):
                break
            if is_ancestor(a, b):
                bad += 1
    return bad


def measure(path: pathlib.Path, url: str) -> dict:
    html = path.read_text(encoding="utf-8", errors="replace")
    t0 = time.perf_counter()
    result = run_pipeline(html, url)
    elapsed = (time.perf_counter() - t0) * 1000

    tagged = set(result.tagged.all_content_xpaths())
    covered = set()
    for inst in result.instances:
        a = inst.absolute_xpath
        covered |= {x for x in tagged if x == a or x.startswith(a + "/")}

    ids = [i.instance_id(url) for i in result.instances]
    roots = [i.absolute_xpath for i in result.instances]

    cfg = load_config(tempfile.mkdtemp(prefix="bench_"))
    with Store(cfg) as st:
        report = ingest(st, result)
        ri = inv.check_all(st.tfidf)
        rr1 = inv.rr1_pattern_derived(st.conn)
        indexed = set(st.tfidf._chunk_ids)
        recorded = {r["instance_id"] for r in
                    st.conn.execute("SELECT instance_id FROM instances")}
        # M4 coherence
        col_to_tok = {c: t for t, c in st.tfidf._vocab.items()}
        matrix = st.tfidf._tf.tocsr()
        incoherent = 0
        for i in range(matrix.shape[0]):
            present = {col_to_tok[c] for c in matrix[i].indices if c in col_to_tok}
            for tok in present:
                if " " in tok:
                    l, r = tok.split(" ", 1)
                    if l not in present or r not in present:
                        incoherent += 1
                        break

    # M8 determinism: re-run and compare identifiers + rendered text
    again = run_pipeline(html, url)
    deterministic = (
        [i.instance_id(url) for i in again.instances] == ids
        and [i.rendered_text for i in again.instances]
           == [i.rendered_text for i in result.instances]
    )

    subcats = set()
    for field in ("urls", "media", "text", "interactive", "json_data"):
        bucket = getattr(result.tagged, field, None)
        if isinstance(bucket, dict):
            subcats |= {f"{field}.{k}" for k, v in bucket.items() if v}

    return {
        "page": path.stem,
        "bytes": len(html),
        "ms": round(elapsed, 1),
        "chunks": len(result.chunks),
        "rendered": len(result.instances),
        "stored": report.instances_written,
        "indexed": report.rows_indexed,
        "tagged_xpaths": len(tagged),
        "m1_coverage": round(len(covered) / len(tagged), 4) if tagged else None,
        "m2_antichain_violations": antichain_violations(roots),
        "m3_collapse": report.instances_collapsed,
        "m3_collapse_rate": round(report.instances_collapsed / max(len(ids), 1), 4),
        "m4_incoherent_rows": incoherent,
        "m5_ri_violations": {k: len(v) for k, v in ri.items() if v},
        "m6_rr1_violations": len(rr1),
        "m7_containment_ok": indexed <= recorded,
        "m8_deterministic": deterministic,
        "m9_subcategories": sorted(subcats),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--json", type=pathlib.Path,
                    default=ROOT / "notes" / "observations" / "_benchmark.json")
    args = ap.parse_args()

    pages = json.loads(MANIFEST.read_text())["pages"]
    pages = [p for p in pages if p.get("ok")]
    if args.limit:
        pages = pages[:args.limit]

    print(f"corpus: {len(pages)} pages\n")
    header = (f"{'page':44s} {'KB':>6s} {'ms':>7s} {'chunk':>6s} {'inst':>6s} "
              f"{'cov':>6s} {'anti':>5s} {'clps':>6s} {'RI':>4s} {'det':>4s}")
    print(header)
    print("-" * len(header))

    rows = []
    for p in pages:
        path = CORPUS / f"{p['slug']}.html"
        if not path.exists():
            continue
        try:
            m = measure(path, p["url"])
        except Exception as exc:  # noqa: BLE001 — a failure is a result
            print(f"{p['slug'][:44]:44s} ERROR {type(exc).__name__}: {exc}")
            rows.append({"page": p["slug"], "error": f"{type(exc).__name__}: {exc}"})
            continue
        rows.append(m)
        ri_ok = "ok" if not m["m5_ri_violations"] else "FAIL"
        print(f"{m['page'][:44]:44s} {m['bytes']/1024:6.0f} {m['ms']:7.1f} "
              f"{m['chunks']:6d} {m['rendered']:6d} "
              f"{(m['m1_coverage'] if m['m1_coverage'] is not None else 0):6.3f} "
              f"{m['m2_antichain_violations']:5d} {m['m3_collapse']:6d} "
              f"{ri_ok:>4s} {'ok' if m['m8_deterministic'] else 'FAIL':>4s}")

    good = [r for r in rows if "error" not in r]
    print("\n" + "=" * 72)
    print(f"pages measured        {len(good)} / {len(rows)}")
    if good:
        cov = [r["m1_coverage"] for r in good if r["m1_coverage"] is not None]
        print(f"M1 coverage           min {min(cov):.3f}  median "
              f"{sorted(cov)[len(cov)//2]:.3f}  max {max(cov):.3f}")
        print(f"M2 antichain          {sum(1 for r in good if r['m2_antichain_violations'] == 0)}"
              f" / {len(good)} pages clean;"
              f" total violations {sum(r['m2_antichain_violations'] for r in good):,}")
        cl = [r["m3_collapse_rate"] for r in good]
        print(f"M3 collapse rate      min {min(cl):.3f}  median "
              f"{sorted(cl)[len(cl)//2]:.3f}  max {max(cl):.3f}")
        print(f"M4 incoherent rows    {sum(r['m4_incoherent_rows'] for r in good)}")
        print(f"M5 RI clean           {sum(1 for r in good if not r['m5_ri_violations'])} / {len(good)}")
        print(f"M6 RI-R1 clean        {sum(1 for r in good if r['m6_rr1_violations'] == 0)} / {len(good)}")
        print(f"M7 containment        {sum(1 for r in good if r['m7_containment_ok'])} / {len(good)}")
        print(f"M8 deterministic      {sum(1 for r in good if r['m8_deterministic'])} / {len(good)}")
        seen: Counter[str] = Counter()
        for r in good:
            seen.update(r["m9_subcategories"])
        print(f"M9 subcategories seen {len(seen)} / 18")
        missing = {f"{c}.{s}" for c, subs in {
            "urls": ["internal", "external", "resource"],
            "media": ["images", "video", "audio", "archives"],
            "text": ["visible", "accessible", "metadata"],
            "interactive": ["links", "buttons", "inputs", "forms", "event_handlers"],
            "json_data": ["ld_json", "data_attrs", "inline"],
        }.items() for s in subs} - set(seen)
        print(f"   never exercised    {sorted(missing) if missing else 'none'}")
        tot_ms = sum(r["ms"] for r in good)
        tot_kb = sum(r["bytes"] for r in good) / 1024
        print(f"throughput            {tot_kb/1024:.1f} MB in {tot_ms/1000:.1f}s "
              f"({tot_kb/max(tot_ms,1)*1000:.0f} KB/s)")

    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps({"pages": rows}, indent=2), encoding="utf-8")
    print(f"\nwrote {args.json.relative_to(ROOT)}")

    # --- per-URL report card -------------------------------------------------
    report = ROOT / "notes" / "observations" / "BENCHMARK_REPORT.md"
    lines = [
        "# Benchmark report card — per URL",
        "",
        f"Generated by `scripts/benchmark.py` over {len(good)} frozen pages.",
        "Regenerate after any pipeline change; a stale report is worse than none.",
        "",
        "`cov` M1 coverage · `anti` M2 nesting violations · `clps` M3 collapse rate",
        "· `coh` M4 incoherent rows · `RI` M5 · `rr1` M6 · `cont` M7 · `det` M8",
        "",
        "| page | KB | ms | chunks | rendered | cov | anti | clps | coh | RI | rr1 | cont | det |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|:--:|---:|:--:|:--:|",
    ]
    for r in sorted(good, key=lambda r: r["page"]):
        ri = "ok" if not r["m5_ri_violations"] else \
             ",".join(sorted(r["m5_ri_violations"]))
        lines.append(
            f"| `{r['page']}` | {r['bytes']/1024:.0f} | {r['ms']:.0f} | "
            f"{r['chunks']} | {r['rendered']} | "
            f"{(r['m1_coverage'] if r['m1_coverage'] is not None else 0):.3f} | "
            f"{r['m2_antichain_violations']} | {r['m3_collapse_rate']:.3f} | "
            f"{r['m4_incoherent_rows']} | {ri} | {r['m6_rr1_violations']} | "
            f"{'ok' if r['m7_containment_ok'] else 'FAIL'} | "
            f"{'ok' if r['m8_deterministic'] else 'FAIL'} |"
        )
    errs = [r for r in rows if "error" in r]
    if errs:
        lines += ["", "## Pages that raised", ""]
        lines += [f"- `{r['page']}` — {r['error']}" for r in errs]
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote {report.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
