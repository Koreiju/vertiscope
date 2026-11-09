"""D-2 stage 3: move a store's anchors to the MARKDOWN level, in place.

PLUGIN_GOAL 154 ("Markdown line in the key"): domain / url-tail / xpath /
markdown / content-detection. Run against a COPY first (PLUGIN_GOAL 153,
"migrate into a copy"), compare, and only then against the live store.

    python scripts/migrate_d2.py build/corpus123_d2/graph.kuzu [--limit N] [--check]

For each chunk, its stored markdown lines pair with its Anchors BY POSITION
(the store's contract). Line i's anchor A becomes A at md_hash(line i)'s
markdown level: a five-part Address row (the leaf's value) and the edge
re-pointed to it. A chunk whose line count differs from its anchor count is
left as it is and counted -- it is not guessed at.

`--check` re-reads the store and verifies, per chunk: anchor count unchanged,
every anchor at the markdown level, its leaf an Address row that exists, its
md the hash of its line; and no two chunks share a five-part key.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

sys.path.insert(0, os.getcwd())
os.environ["DOMVEC_D2"] = "1"

from domvec.address import ContentAddress, md_hash  # noqa: E402
from domvec.graphstore import GraphStore  # noqa: E402


def _lines(md: str):
    """A chunk's markdown as the lines it was rendered from: one per anchor,
    the indentation (`"  " * depth`) the render added taken off."""
    return [l.lstrip(" ") for l in (md or "").split("\n")]


def migrate(store: GraphStore, limit: int = 0, batch: int = 2000) -> dict:
    rows = store._rows("MATCH (c:Chunk)-[:Anchors]->(:Address) WITH DISTINCT c RETURN c.cid, c.md")
    out = {"chunks": 0, "migrated": 0, "already": 0, "mismatch": 0, "anchors": 0, "new_rows": 0}
    edges, new_rows = [], {}
    t0 = time.time()
    for cid, md in rows:
        if limit and out["chunks"] >= limit:
            break
        out["chunks"] += 1
        anchors = store._rows(
            "MATCH (c:Chunk {cid: $cid})-[r:Anchors]->(a:Address) "
            "RETURN r.ord, a.aid, a.akey, a.value, a.content_hash ORDER BY r.ord", {"cid": cid})
        if not anchors:
            continue
        lines = _lines(md)
        if len(lines) != len(anchors):
            out["mismatch"] += 1
            continue
        if all(ContentAddress.parse(k).md for _o, _aid, k, _v, _c in anchors if k):
            out["already"] += 1
            continue
        for (ordinal, aid, key, value, ch), text in zip(anchors, lines):
            if not key:
                continue
            a = ContentAddress.parse(key)
            if a.md:
                continue
            r = a.rendered(text)
            new_rows[r.aid] = {"aid": r.aid, "akey": r.key(), "url": r.url, "xp": r.xpath, "tag": r.tag,
                               "acc": r.accessor, "md": r.md, "val": value or "", "ch": ch or ""}
            edges.append({"cid": cid, "old": aid, "new": r.aid, "ord": ordinal})
        out["migrated"] += 1
        if len(edges) >= batch:
            _flush(store, new_rows, edges, out)
            print("  %d chunks, %d anchors, %.0f s" % (out["chunks"], out["anchors"], time.time() - t0), flush=True)
    _flush(store, new_rows, edges, out)
    out["seconds"] = round(time.time() - t0, 1)
    return out


def _flush(store, new_rows, edges, out):
    if new_rows:
        store._batch(
            "UNWIND $rows AS r MERGE (a:Address {aid: r.aid}) "
            "SET a.akey = r.akey, a.url = r.url, a.xpath = r.xp, a.tag = r.tag, "
            "a.accessor = r.acc, a.md = r.md, a.value = r.val, a.content_hash = r.ch",
            list(new_rows.values()))
        out["new_rows"] += len(new_rows)
    if edges:
        store._batch(
            "UNWIND $rows AS r MATCH (c:Chunk {cid: r.cid})-[e:Anchors {ord: r.ord}]->(o:Address {aid: r.old}) "
            "DELETE e", edges)
        store._batch(
            "UNWIND $rows AS r MATCH (c:Chunk {cid: r.cid}), (a:Address {aid: r.new}) "
            "CREATE (c)-[:Anchors {ord: r.ord}]->(a)", edges)
        out["anchors"] += len(edges)
    new_rows.clear()
    edges.clear()


def check(store: GraphStore, limit: int = 0) -> dict:
    rows = store._rows("MATCH (c:Chunk)-[:Anchors]->(:Address) WITH DISTINCT c RETURN c.cid, c.md")
    leaves = set()
    out = {"chunks": 0, "checked": 0, "bad_count": 0, "not_md": 0, "md_wrong": 0, "leaf_missing": 0, "collisions": 0}
    seen = {}
    for cid, md in rows:
        if limit and out["chunks"] >= limit:
            break
        out["chunks"] += 1
        keys = [k for (k,) in store._rows(
            "MATCH (c:Chunk {cid: $cid})-[r:Anchors]->(a:Address) RETURN a.akey ORDER BY r.ord", {"cid": cid})]
        if not keys:
            continue
        lines = _lines(md)
        if len(lines) != len(keys):
            out["bad_count"] += 1
            continue
        out["checked"] += 1
        for k, text in zip(keys, lines):
            a = ContentAddress.parse(k)
            if not a.md:
                out["not_md"] += 1
                continue
            if a.md != md_hash(text):
                out["md_wrong"] += 1
            leaves.add(a.leaf().aid)
            if k in seen and seen[k] != cid:
                out["collisions"] += 1
            seen[k] = cid
    have = set()
    lv = list(leaves)
    for i in range(0, len(lv), 5000):
        have |= {x for (x,) in store._rows("UNWIND $a AS x MATCH (a:Address {aid: x}) RETURN a.aid", {"a": lv[i:i + 5000]})}
    out["leaf_missing"] = len(leaves - have)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("store")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--check", action="store_true")
    a = ap.parse_args(argv)
    with GraphStore(a.store) as store:
        print("md column:", store.md_level, flush=True)
        if not store.md_level:
            return 2
        if not a.check:
            print("migrate:", migrate(store, a.limit), flush=True)
        print("check:", check(store, a.limit), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
