#!/usr/bin/env python
"""Measure the addressing scheme's claims over the frozen corpus.

Four questions, each with a number rather than an assurance:

    A1  uniqueness      does any address carry two different values?
    A2  completeness    is the address map a bijection onto detections?
    A3  order fidelity  does an in-order trie walk reproduce the DOM's own
                        child order, parent by parent?
    A4  identity        does address-keyed identity dissolve defect B10 --
                        the RI-2 failure caused by content-keyed ids
                        degenerating on empty payloads?

A3 is checked against the DOM's actual child lists rather than argued,
because ordered retrieval from the source is the reason the trie stores
absolute xpaths at all. An earlier ordering derived sibling position from
detection arrival and mis-ordered 15.9% of multi-label parents; the walk
position fixed it, and this is what says so.

    python scripts/audit_addressing.py
    python scripts/audit_addressing.py --limit 10
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
from collections import Counter, defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vertiscope.address import address_of, addresses_of, collisions  # noqa: E402
from vertiscope.pipeline import run_pipeline  # noqa: E402
from vertiscope.trie import AddressTrie, content_hash, diff  # noqa: E402

CORPUS = ROOT / "tests" / "corpus"
MANIFEST = CORPUS / "manifest.json"


def order_fidelity(trie, dom, url: str) -> tuple[int, int]:
    """(parents whose trie order differs from the DOM's, parents compared).

    Compares like with like: only the children the trie actually holds are
    lined up against the DOM's child list for that parent, in the DOM's
    order. A parent counts as mis-ordered when the two sequences differ.
    """
    from vertiscope.address import url_steps
    from vertiscope.core.shadow_html_parser import get_absolute_xpath

    truth: dict = {}
    stack = [dom.root]
    while stack:
        node = stack.pop()
        kids = [k for k in node.get_children(include_shadow=True)
                if k.tag and not k.tag.startswith("#")]
        if kids:
            truth[get_absolute_xpath(node)] = [get_absolute_xpath(k) for k in kids]
        stack.extend(kids)

    url_n = len(url_steps(url))
    checked = wrong = 0

    def walk(node, path):
        nonlocal checked, wrong
        kids = node.ordered_children()
        if len(path) >= url_n and kids:
            want_all = truth.get("/" + "/".join(path[url_n:]))
            if want_all:
                present = set(want_all)
                got = ["/" + "/".join(path[url_n:] + [k.segment]) for k in kids]
                got = [g for g in got if g in present]
                want = [x for x in want_all if x in set(got)]
                if want:
                    checked += 1
                    if got != want:
                        wrong += 1
        for k in kids:
            walk(k, path + [k.segment])

    walk(trie.root, [])
    return wrong, checked


def measure(path: pathlib.Path, url: str) -> dict:
    html = path.read_text(encoding="utf-8", errors="replace")
    t0 = time.perf_counter()
    result = run_pipeline(html, url, render=True)
    tags = result.tagged.all_tags

    addrs = addresses_of(tags, url)
    coll = collisions(tags, url)

    # A2: bijection between the deduplicated detection set and the addresses
    detected = {address_of(t, url).key() for t in tags}
    produced = {a.key() for a in addrs}

    t1 = time.perf_counter()
    trie = AddressTrie.from_tagged(result.tagged, url)
    t2 = time.perf_counter()

    misordered, compared = order_fidelity(trie, result.dom, url)

    # A4: identity. The shipped scheme keys on content, so instances whose
    # rendered payload is empty share one id (defect B10). The address keys
    # on position and provenance, so it cannot.
    shipped_ids = {i.instance_id(url) for i in result.instances}
    empty_payload = sum(1 for i in result.instances if not (i.html_raw or "").strip())

    # A one-leaf delta on a real page: the O(delta) cost in situ.
    other = AddressTrie.from_tagged(result.tagged, url)
    leaves = list(other.leaves())
    visited = 0
    if leaves:
        leaf = leaves[len(leaves) // 2]
        leaf.value = "CHANGED-BY-AUDIT"
        leaf.content_hash = content_hash("CHANGED-BY-AUDIT")
        other._dirty = True
        visited = diff(trie, other).visited

    stats = trie.stats()
    return {
        "page": path.stem,
        "bytes": len(html),
        "pipeline_ms": round((t1 - t0) * 1000, 1),
        "trie_ms": round((t2 - t1) * 1000, 1),
        "detections": len(tags),
        "addresses": len(addrs),
        "a1_collisions": len(coll),
        "a1_examples": [(str(a), v[:2]) for a, v in coll[:2]],
        "a2_invented": len(produced - detected),
        "a2_lost": len(detected - produced),
        "a3_misordered_parents": misordered,
        "a3_parents_compared": compared,
        "a4_instances": len(result.instances),
        "a4_shipped_distinct_ids": len(shipped_ids),
        "a4_empty_payload": empty_payload,
        "trie_nodes": stats["nodes"],
        "trie_leaves": stats["leaves"],
        "delta_visited": visited,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--json", type=pathlib.Path,
                    default=ROOT / "notes" / "observations" / "_addressing.json")
    args = ap.parse_args()

    pages = [p for p in json.loads(MANIFEST.read_text())["pages"] if p.get("ok")]
    if args.limit:
        pages = pages[: args.limit]

    header = (f"{'page':40s} {'det':>7s} {'addr':>7s} {'coll':>5s} "
              f"{'ilv':>6s} {'nodes':>7s} {'dlt':>5s}")
    print(f"corpus: {len(pages)} pages\n")
    print(header)
    print("-" * len(header))

    rows = []
    for p in pages:
        path = CORPUS / f"{p['slug']}.html"
        if not path.exists():
            continue
        try:
            m = measure(path, p["url"])
        except Exception as exc:  # noqa: BLE001 -- a failure is a result
            print(f"{p['slug'][:40]:40s} ERROR {type(exc).__name__}: {exc}")
            rows.append({"page": p["slug"], "error": f"{type(exc).__name__}: {exc}"})
            continue
        rows.append(m)
        ordr = (f"{m['a3_misordered_parents']}/{m['a3_parents_compared']}"
                if m["a3_parents_compared"] else "-")
        print(f"{m['page'][:40]:40s} {m['detections']:7d} {m['addresses']:7d} "
              f"{m['a1_collisions']:5d} {ordr:>8s} {m['trie_nodes']:7d} "
              f"{m['delta_visited']:5d}")

    good = [r for r in rows if "error" not in r]
    print("\n" + "=" * 72)
    if not good:
        print("no pages measured")
        return 1

    det = sum(r["detections"] for r in good)
    addr = sum(r["addresses"] for r in good)
    coll = sum(r["a1_collisions"] for r in good)
    print(f"pages                    {len(good)} / {len(rows)}")
    print(f"A1 detections            {det:,}")
    print(f"   distinct addresses    {addr:,}  "
          f"({det - addr:,} exact-duplicate detections collapsed)")
    print(f"   COLLIDING addresses   {coll}   "
          f"{'(uniqueness holds)' if coll == 0 else '<-- NOT A KEY'}")
    if coll:
        for r in good:
            for ex in r["a1_examples"]:
                print(f"     {r['page']}: {ex[0][:90]}")
                break

    inv = sum(r["a2_invented"] for r in good)
    lost = sum(r["a2_lost"] for r in good)
    print(f"A2 invented / lost       {inv} / {lost}   "
          f"{'(bijection holds)' if inv == lost == 0 else '<-- NOT A BIJECTION'}")

    wrong = sum(r["a3_misordered_parents"] for r in good)
    compared = sum(r["a3_parents_compared"] for r in good)
    pages_clean = sum(1 for r in good if r["a3_misordered_parents"] == 0)
    print(f"A3 mis-ordered parents   {wrong:,} of {compared:,} compared "
          f"({wrong / max(compared, 1) * 100:.2f}%)   "
          f"{'(walk order reproduces the DOM)' if wrong == 0 else '<-- OUT OF ORDER'}")
    print(f"   pages exact           {pages_clean} / {len(good)}")

    inst = sum(r["a4_instances"] for r in good)
    ids = sum(r["a4_shipped_distinct_ids"] for r in good)
    empty = sum(r["a4_empty_payload"] for r in good)
    print(f"A4 rendered instances    {inst:,}")
    print(f"   content-keyed ids     {ids:,}  "
          f"(collapse {inst - ids:,} = {(inst - ids) / max(inst, 1) * 100:.1f}%)")
    print(f"   empty payloads        {empty:,}  "
          f"({empty / max(inst, 1) * 100:.1f}%) -- the B10 mechanism")
    print(f"   address-keyed ids     {addr:,} for {addr:,} addresses "
          f"(collapse 0.0% by construction)")

    nodes = sum(r["trie_nodes"] for r in good)
    dv = [r["delta_visited"] for r in good if r["delta_visited"]]
    print(f"trie nodes               {nodes:,} for {addr:,} leaves "
          f"({nodes / max(addr, 1):.2f} nodes/leaf)")
    if dv:
        print(f"one-leaf delta visits    median {sorted(dv)[len(dv) // 2]}  "
              f"max {max(dv)}  of {nodes // max(len(good), 1):,} nodes/page avg")
    ms = sum(r["trie_ms"] for r in good)
    print(f"trie build               {ms / 1000:.1f}s total "
          f"({ms / max(len(good), 1):.0f} ms/page)")

    args.json.parent.mkdir(parents=True, exist_ok=True)
    args.json.write_text(json.dumps({"pages": rows}, indent=2), encoding="utf-8")
    # `Path.relative_to` raises when the argument is not under ROOT — which a
    # *relative* `--json` never is, since it resolves against the working
    # directory, not this file. So `audit_addressing.py --json notes/x.json`
    # did all its work, wrote the file, and then died with a traceback on the
    # last line, turning a passing audit into a non-zero exit. Cosmetic path
    # formatting is not worth an exception.
    try:
        shown = args.json.resolve().relative_to(ROOT)
    except ValueError:
        shown = args.json
    print(f"\nwrote {shown}")
    return 0 if coll == 0 and inv == 0 and lost == 0 and wrong == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
