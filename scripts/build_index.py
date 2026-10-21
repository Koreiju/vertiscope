#!/usr/bin/env python
"""Run the whole pipeline over the corpus and report what it built.

    html -> trie -> markdown chunks -> JSONL
                 -> kuzu (addresses + chunks + embeddings + edges)
                 -> numpy frequency matrix
                 -> PageRank
    then query it three ways.

The queries at the end are not a demo. The triple product gives every factor a
veto, and this is where that becomes a number: how many candidates each factor
zeroed, per query. A retrieval rule whose behaviour is only described is a rule
nobody has checked.

    python scripts/build_index.py
    python scripts/build_index.py --limit 10 --window 800
    python scripts/build_index.py --semantic          # needs the nomic GGUF
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
import time

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _force_utf8_stdio() -> None:
    """Scraped content is not ASCII and the Windows console default is cp1252.

    Without this the script dies partway through *printing its results*, after
    all the work is done — the most annoying possible place to lose a run.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


_force_utf8_stdio()

from vertiscope.graphstore import GraphStore  # noqa: E402
from vertiscope.markdown import RenderReport, render_trie, write_jsonl  # noqa: E402
from vertiscope.pipeline import run_pipeline  # noqa: E402
from vertiscope.search import SearchDiagnostics, ThreeFormIndex  # noqa: E402
from vertiscope.trie import AddressTrie  # noqa: E402
from vertiscope.vectors import EmbeddingMatrix, FreqMatrix  # noqa: E402

CORPUS = ROOT / "tests" / "corpus"
MANIFEST = CORPUS / "manifest.json"

QUERIES = [
    "university library catalogue",
    "web scraping with python",
    "climate change news",
    "open source software licence",
    "book prices in stock",
]


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--window", type=int, default=1200)
    ap.add_argument("--out", type=pathlib.Path, default=ROOT / "build-corpus")
    ap.add_argument("--force", action="store_true",
                    help="delete an existing workspace at --out first")
    ap.add_argument("--semantic", action="store_true",
                    help="embed chunks with the nomic model (slow, needs GGUF)")
    ap.add_argument("--floor", type=float, default=0.0)
    args = ap.parse_args()

    pages = [p for p in json.loads(MANIFEST.read_text())["pages"] if p.get("ok")]
    if args.limit:
        pages = pages[: args.limit]

    out = args.out
    # This used to default to `build/` — the directory `vertiscope` uses when no
    # `-w` is given — and `rmtree` it without a word. Running the script the
    # README lists under "Verifying" destroyed whatever the operator had
    # scanned, silently, and the only sign was that `vertiscope status` afterwards
    # described a different corpus. Same failure family as a purge that
    # reports success: destructive, and indistinguishable from harmless.
    if out.exists() and any(out.iterdir()):
        if not args.force:
            print(f"{out} already holds something:")
            for entry in sorted(out.iterdir())[:8]:
                print(f"    {entry.name}")
            print("\nrefusing to delete it. Pass --force, or --out <dir>.")
            return 2
        print(f"--force: deleting {out}")
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    jsonl_dir = out / "chunks"
    jsonl_dir.mkdir()

    embedder = None
    if args.semantic:
        from vertiscope.core.embedding_service import get_default_service
        embedder = get_default_service()
        print(f"embedder: {embedder.status()}\n")

    freq = FreqMatrix()
    embeddings = EmbeddingMatrix() if args.semantic else None
    totals = {"addresses": 0, "chunks": 0, "lines": 0, "bytes": 0}
    report = RenderReport()

    header = (f"{'page':40s} {'KB':>5s} {'addr':>6s} {'chunk':>6s} "
              f"{'line':>6s} {'ms':>7s}")
    print(header)
    print("-" * len(header))

    started = time.perf_counter()
    with GraphStore(out / "graph.kuzu") as store:
        # Two passes: every Page node must exist before hyperlink edges can be
        # resolved, since a link to a page we have not seen yet would either
        # dangle or force a second write later.
        scanned = []
        for p in pages:
            path = CORPUS / f"{p['slug']}.html"
            if not path.exists():
                continue
            t0 = time.perf_counter()
            html = path.read_text(encoding="utf-8", errors="replace")
            try:
                result = run_pipeline(html, p["url"], render=False)
            except Exception as exc:  # noqa: BLE001
                print(f"{p['slug'][:40]:40s} ERROR {type(exc).__name__}: {exc}")
                continue
            trie = AddressTrie.from_tagged(result.tagged, p["url"])
            chunks = render_trie(trie, context_window=args.window, report=report)
            addresses = [
                (n.address, n.value, n.content_hash)
                for n in trie.leaves() if n.address is not None
            ]
            rows = {c.cid: freq.add(c.cid, c.markdown) for c in chunks}
            write_jsonl(chunks, jsonl_dir / f"{p['slug']}.jsonl")
            scanned.append((p, trie, chunks, addresses, rows))

            totals["addresses"] += len(addresses)
            totals["chunks"] += len(chunks)
            totals["lines"] += sum(len(c.lines) for c in chunks)
            totals["bytes"] += len(html)
            print(f"{p['slug'][:40]:40s} {len(html)/1024:5.0f} "
                  f"{len(addresses):6d} {len(chunks):6d} "
                  f"{sum(len(c.lines) for c in chunks):6d} "
                  f"{(time.perf_counter()-t0)*1000:7.0f}")

        # Pass 1: pages, so link targets resolve. Pass 2: everything else.
        for p, trie, chunks, addresses, rows in scanned:
            store.conn.execute(
                "MERGE (pg:Page {url: $url}) SET pg.title = '', "
                "pg.scanned_at = 0.0, pg.root_hash = '', "
                "pg.chunk_count = 0, pg.address_count = 0",
                {"url": p["url"]},
            )

        vectors = {}
        if args.semantic and embedder is not None:
            print("\nembedding...", flush=True)
            for _p, _t, chunks, _a, _r in scanned:
                texts = [c.markdown for c in chunks]
                if not texts:
                    continue
                matrix = embedder.embed_texts(texts)
                for chunk, vec in zip(chunks, matrix):
                    vectors[chunk.cid] = vec.tolist()
                    embeddings.set(chunk.cid, vec)

        for p, trie, chunks, addresses, rows in scanned:
            store.ingest(
                p["url"], addresses, chunks, rows=rows,
                embeddings={c.cid: vectors[c.cid] for c in chunks
                            if c.cid in vectors} or None,
                root_hash=trie.root_hash,
            )

        elapsed = time.perf_counter() - started
        freq.save(out / "freq")

        print("\n" + "=" * 72)
        print(f"pages                 {len(scanned)}")
        print(f"addresses             {totals['addresses']:,}")
        print(f"chunks                {totals['chunks']:,}   "
              f"markdown lines {totals['lines']:,}")
        print(f"render accounting     {report.summary()}")
        print(f"graph                 {store.stats()}")
        print(f"frequency matrix      {freq.shape[0]:,} rows x "
              f"{freq.shape[1]:,} terms")
        nnz = freq.tfidf().nnz
        print(f"                      {nnz:,} nonzeros "
              f"({nnz / max(freq.shape[0] * freq.shape[1], 1) * 100:.4f}% dense)")
        print(f"elapsed               {elapsed:.1f}s "
              f"({totals['bytes']/1024/1024/max(elapsed,1e-9):.1f} MB/s)")

        index = ThreeFormIndex(store, freq, embeddings, embedder=embedder).build()
        ranks = index.ranks
        print(f"pagerank              n={len(ranks)} sum={ranks.sum():.4f} "
              f"min={ranks.min():.2e} max={ranks.max():.2e}")

        print("\n" + "-" * 72)
        print("three-form retrieval  (rank x lexical x semantic)\n")
        for query in QUERIES:
            diag = SearchDiagnostics()
            hits = index.search(query, k=3, floor=args.floor, diagnostics=diag)
            print(f"  {query!r}")
            print(f"    {diag.summary()}")
            for hit in hits:
                print(f"    {hit.score:.3e}  r={hit.rank:.2e} "
                      f"l={hit.lexical:.3f} s={hit.semantic:.3f}  "
                      f"{hit.url.split('//')[-1][:38]:38s} "
                      f"{hit.preview(1)[:44]}")
            if not hits:
                print("    (no hit — a factor vetoed every candidate)")
            print()

    print(f"wrote {out.relative_to(ROOT)}/  "
          f"(graph.kuzu, freq/, chunks/*.jsonl)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
