"""Purge every stored page under some address prefixes, through the running sidecar.

`python -m domvec.obsidian purge --port 8794 --prefix code://repo/ --prefix code://plugin/ [--dry-run]`

G-375 (PLUGIN_GOAL 166 a, 167 a) took the repository's code out of the
projector and the indexer; the reader then answered "yes" to deleting the
pages already stored (169, 2). This is that deletion, done by the sidecar
that holds the store -- `GET /pages` for the list, `POST /purge` per page,
which drops the page, its chunks and addresses and retires its projected
points at once -- so nothing here opens the store, and the trie loses each
page whole or not at all.

A prefix, not a substring: `code://repo/` must not take a browser page whose
URL merely mentions it. Planted `PLANT_SUBSTRING`: matches by substring.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Dict, Iterable, List

PLANT_SUBSTRING = [False]


def _get(base: str, path: str) -> dict:
    with urllib.request.urlopen(base + path, timeout=60) as r:
        return json.load(r)


def _post(base: str, path: str, body: dict) -> dict:
    req = urllib.request.Request(base + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return {"error": "HTTP %d" % e.code, **(json.load(e) if e.fp else {})}


def matching(urls: Iterable[str], prefixes: List[str]) -> List[str]:
    if PLANT_SUBSTRING[0]:
        return [u for u in urls if any(p in u for p in prefixes)]
    return [u for u in urls if u.startswith(tuple(prefixes))]


def purge(base: str, prefixes: List[str], dry_run: bool = False) -> Dict:
    before = _get(base, "/pages")
    targets = matching(before.get("urls") or [], prefixes)
    out = {"prefixes": prefixes, "pages_before": before.get("n"), "matched": len(targets),
           "by_prefix": {p: sum(1 for u in targets if u.startswith(p)) for p in prefixes},
           "dry_run": dry_run}
    if dry_run:
        out["sample"] = targets[:10]
        return out
    t0 = time.perf_counter()
    chunks = retired = 0
    failed = []
    for u in targets:
        got = _post(base, "/purge", {"url": u})
        if got.get("error"):
            failed.append({"url": u, "error": got.get("error")})
        else:
            chunks += int(got.get("chunks_removed") or 0)
            retired += int(got.get("projected_retired") or 0)
    after = _get(base, "/pages")
    left = matching(after.get("urls") or [], prefixes)
    out.update({"purged": len(targets) - len(failed), "chunks_removed": chunks,
                "projected_retired": retired, "failed": failed[:10], "failed_n": len(failed),
                "pages_after": after.get("n"), "left_under_prefixes": len(left),
                "s": round(time.perf_counter() - t0, 1)})
    return out


def main(argv: List[str]) -> int:
    import argparse
    ap = argparse.ArgumentParser(prog="python -m domvec.obsidian purge")
    ap.add_argument("--port", type=int, default=8794)
    ap.add_argument("--prefix", action="append", required=True)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args(argv)
    got = purge("http://127.0.0.1:%d" % a.port, a.prefix, a.dry_run)
    print(json.dumps(got, indent=1))
    return 1 if got.get("failed_n") else 0
