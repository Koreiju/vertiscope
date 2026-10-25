"""R-J3: "The tightest crowding is duplicate content, not projection, and is
answerable to `duplicate_chunks` -- not to a spatial fix."

Measured on the running sidecar's chunk view (`/layout?level=chunk`): every
chunk's nearest neighbour; the tightest 1% of pairs against a random sample
of the same size. For each pair, the two chunks' texts (`/chunk/<cid>`) are
compared by token Jaccard. If the tightest pairs are near-identical text far
more often than random pairs are, crowding IS duplication; if not, it is the
projection.

    python scripts/check_crowding.py
"""
import json
import random
import re
import sys
import urllib.parse
import urllib.request

import numpy as np
from scipy.spatial import cKDTree

B = "http://127.0.0.1:8788"


def get(path, timeout=300):
    with urllib.request.urlopen(B + path, timeout=timeout) as r:
        return json.load(r)


def text_of(cid):
    try:
        got = get("/chunk/" + urllib.parse.quote(cid, safe=""), timeout=60)
    except Exception:                               # noqa: BLE001
        return None
    lines = got.get("lines") or []
    return " ".join(str(l.get("text") or "") for l in lines) or got.get("markdown") or ""


def toks(s):
    return set(re.findall(r"\w+", (s or "").lower()))


def jac(a, b):
    a, b = toks(a), toks(b)
    return len(a & b) / len(a | b) if (a or b) else 0.0


def main():
    lay = get("/layout?dims=3&level=chunk", timeout=600)
    nodes = [n for n in lay["nodes"] if n.get("pos")]
    P = np.asarray([n["pos"][:3] for n in nodes], dtype=float)
    tree = cKDTree(P)
    d, j = tree.query(P, k=2)
    nn_d, nn_j = d[:, 1], j[:, 1]
    order = np.argsort(nn_d)
    k = max(50, len(nodes) // 100)
    k = min(k, 150)                                  # each pair costs two reads
    rng = random.Random(7)
    tight = [(int(i), int(nn_j[i])) for i in order[:k]]
    rand = [(i, rng.randrange(len(nodes))) for i in rng.sample(range(len(nodes)), k)]
    def score(pairs):
        out = []
        for a, b in pairs:
            ta, tb = text_of(nodes[a]["cid"]), text_of(nodes[b]["cid"])
            if ta is None or tb is None:
                continue
            out.append({"j": jac(ta, tb), "same_url": nodes[a].get("url") == nodes[b].get("url")})
        return out
    st, sr = score(tight), score(rand)
    q = lambda xs, p: sorted(xs)[min(len(xs) - 1, int(p * len(xs)))] if xs else None  # noqa: E731
    res = {"chunks": len(nodes), "pairs": k,
           "nn_dist_p1": float(nn_d[order[k - 1]]), "nn_dist_p50": float(np.median(nn_d)),
           "tight": {"n": len(st), "jaccard_p50": q([x["j"] for x in st], .5),
                     "near_dup_share": sum(x["j"] >= 0.8 for x in st) / max(1, len(st)),
                     "same_page_share": sum(x["same_url"] for x in st) / max(1, len(st))},
           "random": {"n": len(sr), "jaccard_p50": q([x["j"] for x in sr], .5),
                      "near_dup_share": sum(x["j"] >= 0.8 for x in sr) / max(1, len(sr)),
                      "same_page_share": sum(x["same_url"] for x in sr) / max(1, len(sr))}}
    t, r = res["tight"], res["random"]
    res["crowding_is_duplication"] = bool(t["near_dup_share"] >= 0.5 and t["near_dup_share"] > 5 * max(r["near_dup_share"], 0.01))
    print(json.dumps(res, indent=1))
    return 0


if __name__ == "__main__":
    sys.exit(main())
