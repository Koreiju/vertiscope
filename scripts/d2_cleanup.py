"""D-2 cleanup of a re-indexed COPY, against the live store (read-only).

    python scripts/d2_cleanup.py build/corpus123_d2/graph.kuzu build/corpus123/graph.kuzu [--apply]

1. Version chunks the re-index created: versions in the copy that the live
   store does not have. A migration is not page history -- they go.
   Versions the live store already had are kept.
2. The leaf question: how many anchors in the LIVE store point at an
   address that is not a trie leaf either (renderer-synthesized lines),
   against the copy's count -- so a gap is migration loss, a match is not.

Without --apply it only reports. The live store must not be open elsewhere.
"""
from __future__ import annotations

import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.getcwd())
os.environ["DOMVEC_D2"] = "1"

from domvec.graphstore import GraphStore  # noqa: E402


def versions(s):
    return {c for (c,) in s._rows("MATCH (c:Chunk)-[:VersionOf]->(:Chunk) RETURN DISTINCT c.cid")}


def synth_anchor_share(s, limit=200000):
    """Anchors whose Address has no trie-leaf twin: tag/accessor composites."""
    rows = s._rows("MATCH (p:Page)-[:HasChunk]->(c:Chunk)-[:Anchors]->(a:Address) "
                   "RETURN a.accessor LIMIT $n", {"n": limit})
    comp = sum(1 for (acc,) in rows if acc and "|" in acc)
    return {"anchors_read": len(rows), "composite_accessor": comp,
            "share": round(comp / max(1, len(rows)), 4)}


def main(argv=None) -> int:
    copy_path, live_path = sys.argv[1], sys.argv[2]
    apply = "--apply" in sys.argv
    with GraphStore(live_path, read_only=True) as live:
        live_versions = versions(live)
        live_synth = synth_anchor_share(live)
    print("live versions:", len(live_versions), "live composite anchors:", live_synth, flush=True)
    with GraphStore(copy_path, read_only=not apply) as cp:
        copy_versions = versions(cp)
        made = sorted(copy_versions - live_versions)
        print("copy versions:", len(copy_versions), "created by the re-index:", len(made),
              "kept (live had them):", len(copy_versions & live_versions), flush=True)
        print("copy composite anchors:", synth_anchor_share(cp), flush=True)
        if apply and made:
            for i in range(0, len(made), 2000):
                cp._batch("UNWIND $rows AS r MATCH (c:Chunk {cid: r.cid}) DETACH DELETE c",
                          [{"cid": c} for c in made[i:i + 2000]])
            print("deleted:", len(made), "remaining versions:", len(versions(cp)), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
