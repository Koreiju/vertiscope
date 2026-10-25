"""G-33: "Structure enters the pairwise metric ... MEASURE what a structural
term adds before adopting one."

The merge today is the embeddings alone. A structural term (`lca_distance`,
the lowest-common-ancestor distance between two xpaths, 0 = same node, 1 =
nothing shared) would change exactly the merges whose members sit FAR apart
in the page's tree. So: for a sample of the store's semantic groups
(`/layout?level=chunk`, members > 1, through `/chunk/<cid>`), every member
pair's lca distance and whether they share a page.

  near  (lca <= 0.25): siblings or cousins -- a structural term agrees.
  far   (lca >  0.50): the encoder joined chunks the tree keeps apart -- a
        structural term would split or down-weight these.

Written to build_analytics/group_structure.json (analytics live outside the
REPL). Reads the running sidecar.    python scripts/measure_group_structure.py [N]
"""
import json
import random
import sys
import urllib.parse
import urllib.request
from itertools import combinations
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from domvec.aggregate import lca_distance  # noqa: E402

B = "http://127.0.0.1:8788"


def get(path, timeout=120):
    with urllib.request.urlopen(B + path, timeout=timeout) as r:
        return json.load(r)


def main():
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    lay = get("/layout?dims=3&level=chunk", timeout=900)
    groups = [g for g in lay["nodes"] if (g.get("members") or 1) > 1]
    rng = random.Random(33)
    sample = rng.sample(groups, min(n, len(groups)))
    pairs, spreads, cross_page = [], [], 0
    examples = []
    for g in sample:
        try:
            lead = get("/chunk/" + urllib.parse.quote(g["cid"], safe=""))
        except Exception:                           # noqa: BLE001
            continue
        members = ((lead.get("group") or {}).get("members") or [])[:8]
        info = []
        for cid in members:
            try:
                p = lead if cid == g["cid"] else get("/chunk/" + urllib.parse.quote(cid, safe=""))
            except Exception:                       # noqa: BLE001
                continue
            info.append((cid, p.get("url"), p.get("xpath") or ""))
        if len(info) < 2:
            continue
        ds = []
        for (a, ua, xa), (b, ub, xb) in combinations(info, 2):
            if ua != ub:
                cross_page += 1
                continue
            d = lca_distance(xa, xb)
            ds.append(d)
            pairs.append(d)
        if ds:
            spreads.append(max(ds))
            if max(ds) > 0.5 and len(examples) < 5:
                far = max(((xa, xb) for (_, ua, xa), (_, ub, xb) in combinations(info, 2) if ua == ub),
                          key=lambda t: lca_distance(*t))
                examples.append({"url": info[0][1], "a": far[0], "b": far[1], "lca": round(lca_distance(*far), 3)})
    q = lambda xs, p: sorted(xs)[min(len(xs) - 1, int(p * len(xs)))] if xs else None  # noqa: E731
    res = {"groups_total": len(groups), "groups_sampled": len(sample), "groups_measured": len(spreads),
           "same_page_pairs": len(pairs), "cross_page_pairs": cross_page,
           "pair_lca_p50": q(pairs, .5), "pair_lca_p90": q(pairs, .9),
           "pairs_near_le_0_25": round(sum(d <= 0.25 for d in pairs) / max(1, len(pairs)), 3),
           "pairs_far_gt_0_5": round(sum(d > 0.5 for d in pairs) / max(1, len(pairs)), 3),
           "groups_with_a_far_pair": round(sum(s > 0.5 for s in spreads) / max(1, len(spreads)), 3),
           "far_examples": examples}
    out = Path(__file__).resolve().parents[1] / "build_analytics" / "group_structure.json"
    out.write_text(json.dumps(res, indent=1), encoding="utf-8")
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
