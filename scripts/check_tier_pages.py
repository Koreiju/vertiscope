"""Tier 1 picks pages that HOLD matches (PLUGIN_GOAL 154; G-210/G-223).
For each query, the top pages by each tier-1 ranking (`centroid=1` planted:
the semantic centroids) and how many hits tier 2 then returns on them. Talks
to the sidecar only; reads, never writes."""
import json, sys, time, urllib.parse, urllib.request
B = "http://127.0.0.1:8788"
def get(path):
    t = time.perf_counter()
    d = json.load(urllib.request.urlopen(B + path, timeout=600))
    return d, round((time.perf_counter() - t) * 1000)
for q in sys.argv[1:] or ["the", "cowboy", "radio drama", "patricia trie"]:
    for centroid in ("0", "1"):
        d, ms = get("/search_pages?q=%s&k=12&centroid=%s" % (urllib.parse.quote(q), centroid))
        pages = [p["url"] for p in d.get("pages") or []]
        hits, empty, t2 = 0, 0, 0
        for u in pages:
            r, m = get("/search?q=%s&k=60&url=%s" % (urllib.parse.quote(q), urllib.parse.quote(u, safe="")))
            n = len(r.get("hits") or []); hits += n; empty += (n == 0); t2 += m
        print(json.dumps({"q": q, "tier1": "centroid (planted)" if centroid == "1" else "held", "pages": len(pages),
                          "empty_pages": empty, "tier2_hits": hits, "matching": d.get("matching"), "tier1_ms": ms, "tier2_ms": t2}))
