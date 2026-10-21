"""Build a workspace from the frozen corpus, with vectors in both spaces.

The Obsidian bridge reads a workspace; this makes one that exercises every
part of it -- chunks at the token window, media with fetchable sources,
frequency vectors, and SEMANTIC vectors, which is the half the 3D view has
never had.

The semantic half was missing for one reason: `Workspace.__init__` takes
`embedder=None` and sets `self.embeddings = EmbeddingMatrix() if embedder is
not None else None`, so a workspace built without one has no embedding matrix
at all and `build_layout` falls back to a frequency-only fit reporting
`equalised: False`. Nothing was broken; nobody had passed an embedder. Passing
one is this script's whole point, and `flush_vectors` -- the single write-side
call -- is what actually fills the matrix.

    python scripts/build_vault_workspace.py --out build/vaultws --embed cpu

`--embed off` skips the model, which is useful for a quick structural check
and produces exactly the frequency-only workspace this script exists to stop
being the default.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import shutil
import sys
import time

REPO = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from vertiscope import tokens                                   # noqa: E402
from vertiscope.workspace import Workspace                      # noqa: E402

CORPUS = REPO / "tests" / "corpus"


def _pages(limit: int):
    manifest = CORPUS / "manifest.json"
    if not manifest.exists():
        raise SystemExit("no frozen corpus; run scripts/fetch_corpus.py")
    pages = [p for p in json.loads(manifest.read_text())["pages"]
             if p.get("ok") and (CORPUS / f"{p['slug']}.html").exists()]
    return pages[:limit] if limit else pages


def _embedder(kind: str):
    """A real embedder, or None.

    Deliberately not the hash-deterministic fake. A layout fitted on fake
    vectors reports `semantic` in its spaces and `equalised: True` while
    carrying no semantics at all -- which is worse than reporting the
    frequency-only fit honestly, because it cannot be told apart from the
    real thing downstream.
    """
    if kind == "off":
        return None
    from vertiscope.core.embedding_service import EmbeddingService

    return EmbeddingService(device=kind)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", type=pathlib.Path, required=True)
    # gpu, matching `Config.embed_device`. Not a preference: a chunk at the
    # token window is a full-length forward pass for nomic, and on CPU that
    # measured 0.83s each against 0.27s on the GPU -- the difference between
    # half an hour and an hour and a half over this corpus. `flush_vectors`
    # runs once per completed page by design ("batch, not per-delta"), so the
    # embedder is on the ingest path and its speed is the build's speed.
    ap.add_argument("--embed", default="gpu",
                    help="device for the embedder ('gpu', 'cpu'), or 'off'")
    ap.add_argument("--limit", type=int, default=0, help="0 = every page")
    ap.add_argument("--window", type=int, default=0,
                    help="context window, in tokens; 0 = the default")
    ap.add_argument("--force", action="store_true",
                    help="replace an existing workspace at --out")
    args = ap.parse_args(argv)

    if args.out.exists():
        if not args.force:
            raise SystemExit("%s exists; pass --force to replace it" % args.out)
        shutil.rmtree(args.out)

    pages = _pages(args.limit)
    embedder = _embedder(args.embed)
    kw = {"embedder": embedder}
    if args.window:
        kw["context_window"] = args.window

    started = time.time()
    with Workspace(args.out, **kw) as ws:
        print("window %d %s   embedder %s   pages %d"
              % (ws.context_window, tokens.name(),
                 args.embed if embedder is not None else "none", len(pages)),
              flush=True)
        chunks = 0
        for i, page in enumerate(pages, 1):
            html = (CORPUS / f"{page['slug']}.html").read_text(
                encoding="utf-8", errors="replace")
            try:
                result = ws.index_html(html, page["url"])
            except Exception as exc:                        # noqa: BLE001
                print("  %3d/%d  %-38s FAILED %s: %s"
                      % (i, len(pages), page["slug"][:38],
                         type(exc).__name__, exc), flush=True)
                continue
            chunks += result.chunks
            print("  %3d/%d  %-38s %4d chunks"
                  % (i, len(pages), page["slug"][:38], result.chunks),
                  flush=True)

        ws.settle()
        print("\nindexed %d chunks in %.1fs" % (chunks, time.time() - started),
              flush=True)

        if embedder is not None:
            print("embedding…", flush=True)
            t = time.time()
            report = ws.flush_vectors()
            print("vectors: %s  in %.1fs" % (report, time.time() - t),
                  flush=True)

        index = ws.index
        have = (index.embeddings is not None
                and index.embeddings.matrix is not None)
        print("\nfrequency rows %d   embeddings %s"
              % (len(index.freq.rows),
                 index.embeddings.matrix.shape if have else "NONE"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
