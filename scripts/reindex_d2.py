"""D-2 full re-index of a COPY of a store (PLUGIN_GOAL 155: "Full re-index of
the copy"). Every stored page is rebuilt from its stored addresses,
re-rendered by the current renderer at the markdown level, and written back
through `Workspace.ingest` (the one write path); then every queued chunk is
embedded. Resumable: pages already done are listed in `<ws>/d2_done.txt`.

    python scripts/reindex_d2.py build/corpus123_d2 [--limit N] [--no-embed]

Sibling order: the store keeps no scan walk order, so addresses are inserted
in natural xpath order (`p[2]` before `p[10]`) -- exact within a tag, an
approximation across tags. Recorded in the summary, not hidden.
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.getcwd())
os.environ["DOMVEC_D2"] = "1"

from domvec.address import ContentAddress  # noqa: E402
from domvec.trie import AddressTrie  # noqa: E402
from domvec.workspace import Workspace  # noqa: E402


def _natural(xpath: str):
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", xpath)]


def page_trie(store, url: str) -> AddressTrie:
    rows = store._rows("MATCH (a:Address) WHERE a.url = $u RETURN a.akey, a.value", {"u": url})
    addrs = []
    for k, v in rows:
        try:
            a = ContentAddress.parse(k)
        except ValueError:
            continue
        if a.md or "~" in a.accessor:          # rendered rows and pieces are not leaves
            continue
        addrs.append((a, v or ""))
    addrs.sort(key=lambda av: (_natural(av[0].xpath), av[0].tag, av[0].accessor))
    trie = AddressTrie()
    for a, v in addrs:
        trie.insert(a, v)
    trie.rehash()
    return trie


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("workspace")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--no-embed", action="store_true")
    ap.add_argument("--variants", action="store_true",
                    help="re-render chunk URL VARIANTS (fragments: wiki/Trie#...) that hold "
                         "addresses of their own; a page pass reads only the exact page URL")
    a = ap.parse_args(argv)
    if a.variants:
        return variants(a)
    embedder = None
    if not a.no_embed:
        from domvec.core.embedding_service import get_default_service
        embedder = get_default_service()
    done_f = os.path.join(a.workspace, "d2_done.txt")
    done = set(open(done_f, encoding="utf-8").read().split("\n")) if os.path.exists(done_f) else set()
    t0, n, chunks_total = time.time(), 0, 0
    with Workspace(a.workspace, embedder=embedder) as ws:
        print("md_level:", ws.store.md_level, flush=True)
        if not ws.store.md_level:
            return 2
        urls = [u for (u,) in ws.store._rows("MATCH (p:Page) RETURN p.url") if u]
        print("pages:", len(urls), "done already:", len(done & set(urls)), flush=True)
        with open(done_f, "a", encoding="utf-8") as log:
            for url in urls:
                if url in done:
                    continue
                if a.limit and n >= a.limit:
                    break
                try:
                    trie = page_trie(ws.store, url)
                    if len(trie) == 0:
                        log.write(url + "\n"); continue
                    chunks, _c = ws.ingest(url, trie)
                    ws.settle()
                    if embedder is not None and n % 10 == 9:
                        ws.flush_vectors()
                except Exception as exc:              # noqa: BLE001
                    print("FAIL", url[:80], type(exc).__name__, str(exc)[:120], flush=True)
                    continue
                n += 1
                chunks_total += len(chunks)
                log.write(url + "\n"); log.flush()
                if n % 25 == 0:
                    print("  %d pages, %d chunks, %.0f s" % (n, chunks_total, time.time() - t0), flush=True)
            if embedder is not None:
                print("embedding the rest...", flush=True)
                print("vectors:", ws.flush_vectors(), flush=True)
    print("done: %d pages, %d chunks, %.0f s" % (n, chunks_total, time.time() - t0), flush=True)
    return 0


def variants(a) -> int:
    """Every chunk URL that is not its page's URL and has Address rows of its
    own (a fragment capture) is rebuilt and ingested under that URL."""
    embedder = None
    if not a.no_embed:
        from domvec.core.embedding_service import get_default_service
        embedder = get_default_service()
    with Workspace(a.workspace, embedder=embedder) as ws:
        rows = ws.store._rows("MATCH (p:Page)-[:HasChunk]->(c:Chunk) WHERE c.url <> p.url "
                              "RETURN DISTINCT c.url")
        urls = [u for (u,) in rows if u]
        print("variant urls:", len(urls), flush=True)
        n = 0
        for url in urls:
            trie = page_trie(ws.store, url)
            if len(trie) == 0:
                print("  no addresses:", url[:90], flush=True)
                continue
            chunks, _c = ws.ingest(url, trie)
            ws.settle()
            n += 1
            print("  %s: %d chunks" % (url[:90], len(chunks)), flush=True)
        if embedder is not None:
            print("vectors:", ws.flush_vectors(), flush=True)
    print("variants re-rendered:", n, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
