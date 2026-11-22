"""`browse` -- the browser centroid's one tool (G-205; PLUGIN_GOAL 132, 177).

    browse(query=None, scope="web", of="", down=None, up=False, act=None, k=10)

One tool, many arguments (177 a): every move is the same call, and every call
returns the same object, the **retrieval artifact** -- a tree whose root is
the query, whose children are ranked chunk results, and whose grandchildren
are the per-page navigations made under a result (its trace).

* ``query`` / ``scope`` / ``of`` -- a new artifact. ``web`` ranks the corpus;
  ``page`` ranks within ``of`` (one shadow DOM) and presents in document
  order; ``domain`` is HIERARCHICAL (177 c): the host of ``of`` first, then
  its registrable domain, then its dual-embedding neighbours -- EVERY level
  contributes up to ``k`` results of its own, in that order, each labelled
  with the level that found it. (Draft 1 widened only when the narrower level
  held fewer than ``k``; live, run 80, one four-page host filled k=30 and the
  other two levels never ran -- "all three options are used" was not.) The similarity level is the
  two embeddings' product (`hierank.dual_similar`), never a layout cluster
  (177: "the dual embedding similarity aspect is what the "cluster" label
  confuses").
* ``down=<cid>`` -- descend into a result: the reader's own browser cell is
  asked to open that chunk's page at its address (177 b), and the cursor
  moves into the result's trace. Where the cell goes next is observed
  (`observe`, fed by the plugin's 2-second `browser_state`) and streams into
  the trace as steps, each a diff on the artifact's version.
* ``up=True`` -- toward the ORIGIN: from a trace back to its result, from a
  result back to the result list. Back/forward stay the browser's own.
* ``act={address, value}`` -- act on a chunk's control in place through its
  trie address, as `WebBrowser.act` does.

Session-only (177 d): the artifact lives in the sidecar's memory and is gone
with it. Patricia-trie terms: results are trie reads (`search`); trace steps
are urls the trie holds or will hold once the cell's fold drains; nothing is
written to the trie by this module.
"""

from __future__ import annotations

import re
import time
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple

from . import hierank

SCOPES = ("web", "domain", "page")

#: Planted: the domain scope from the host alone -- one level, no widening
#: and no similarity level -- the flat reading 177 c rejects.
PLANT_DOMAIN_HOST_ONLY = [False]


def _xpath_order(xpath: str) -> Tuple:
    """Document order of an xpath: its steps' indices, compared as numbers
    (``div[10]`` after ``div[9]``), so a page's results read as it draws them."""
    out = []
    for step in str(xpath or "").split("/"):
        m = re.match(r"(.*?)\[(\d+)\]$", step)
        out.append((int(m.group(2)) if m else 1, m.group(1) if m else step))
    return tuple(out)


def domain_tiers(of: str, urls: Iterable[str], similar: Iterable[Tuple[str, str, float]] = ()
                 ) -> List[Tuple[str, List[str]]]:
    """The domain scope's levels around a page, narrowest first, each holding
    only what the narrower ones did not: [("host", ...), ("domain", ...),
    ("similar", ...)]. ``similar`` is the dual-similarity edge list."""
    page = hierank.page_of(of)
    host = hierank.host_of(page)
    dom = hierank.registrable(host)
    pages = sorted({hierank.page_of(u) for u in urls if u})
    seen = set()
    tiers = []
    host_pages = [u for u in pages if hierank.host_of(u) == host]
    tiers.append(("host", host_pages)); seen.update(host_pages)
    if PLANT_DOMAIN_HOST_ONLY[0]:
        return tiers
    dom_pages = [u for u in pages if u not in seen and hierank.registrable(hierank.host_of(u)) == dom]
    tiers.append(("domain", dom_pages)); seen.update(dom_pages)
    near = []
    for a, b, w in sorted(similar, key=lambda e: -e[2]):
        for x, y in ((a, b), (b, a)):
            if hierank.page_of(x) in seen and hierank.page_of(y) not in seen and hierank.page_of(y) not in near:
                near.append(hierank.page_of(y))
    tiers.append(("similar", [u for u in near if u in set(pages)]))
    return tiers


class Session:
    """One reader's retrieval artifact and its cursor. ``search(query, k,
    urls)`` returns ranked hits ``[{cid, url, xpath, preview, score}]``
    (``urls`` None: the corpus); ``forms()`` returns the page urls and the
    dual-similarity edges the domain scope widens by."""

    def __init__(self, search: Callable[..., List[dict]],
                 forms: Callable[[], Tuple[List[str], List[Tuple[str, str, float]]]]):
        self._search = search
        self._forms = forms
        self.artifact: Optional[dict] = None
        self.version = 0
        self.log: List[dict] = []          # one entry per version: what changed

    # -- the moves ---------------------------------------------------------
    def call(self, query: Optional[str] = None, scope: str = "web", of: str = "",
             down: Optional[str] = None, up: bool = False, act: Optional[dict] = None,
             k: int = 10) -> dict:
        """The one tool. Exactly one move per call; returns {artifact, asks,
        moved} -- ``asks`` are what the reader's cell must carry out."""
        moves = [m for m, on in (("query", query is not None), ("down", down is not None),
                                 ("up", bool(up)), ("act", act is not None)) if on]
        if len(moves) > 1:
            raise ValueError("one move per call: got " + ", ".join(moves))
        if not moves:
            return {"artifact": self.artifact, "asks": [], "moved": "none"}
        return getattr(self, "_" + moves[0])(**{"query": dict(query=query, scope=scope, of=of, k=k),
                                                 "down": dict(cid=down), "up": {},
                                                 "act": dict(act=act)}[moves[0]])

    def _query(self, query: str, scope: str, of: str, k: int) -> dict:
        if scope not in SCOPES:
            raise ValueError("scope is one of " + ", ".join(SCOPES))
        if scope in ("page", "domain") and not of:
            raise ValueError(scope + " scope needs `of`: the page it is relative to")
        k = max(1, min(int(k), 200))
        results: List[dict] = []
        levels: List[dict] = []
        if scope == "web":
            results = [dict(h, level="web") for h in self._search(query, k, None)]
        elif scope == "page":
            got = self._search(query, k, [hierank.page_of(of)])
            results = [dict(h, level="page") for h in sorted(got, key=lambda h: _xpath_order(h.get("xpath")))]
        else:
            urls, sim = self._forms()
            rank_of = {"host": 0, "domain": 1, "similar": 2}
            for name, pages in domain_tiers(of, urls, sim):
                have = {h["cid"] for h in results}
                got = [dict(h, level=name) for h in self._search(query, k, pages) if h["cid"] not in have] if pages else []
                levels.append({"level": name, "pages": len(pages), "results": len(got)})
                results += got
            # Level first; within a level grouped by page, pages ordered by
            # their best result (§3).
            best: Dict[str, int] = {}
            for i, h in enumerate(results):
                best.setdefault(hierank.page_of(h.get("url", "")), i)
            results = sorted(results, key=lambda h: (rank_of.get(h["level"], 3), best[hierank.page_of(h.get("url", ""))]))
        for h in results:
            u = hierank.page_of(h.get("url", ""))
            h["host"] = hierank.host_of(u)
            h["domain"] = hierank.registrable(h["host"])
            h["trace"] = []
        self.artifact = {"query": query, "scope": scope, "of": of, "k": k, "levels": levels,
                         "results": results, "cursor": {"at": "results"}, "made": time.time()}
        return self._moved("query", {"results": len(results)}, [])

    def _result(self, cid: str) -> dict:
        for h in (self.artifact or {}).get("results") or []:
            if h.get("cid") == cid:
                return h
        raise KeyError("no result %r in the artifact" % cid)

    def _down(self, cid: str) -> dict:
        if not self.artifact:
            raise ValueError("no artifact: ask a query first")
        h = self._result(str(cid))
        self.artifact["cursor"] = {"at": "trace", "cid": h["cid"]}
        h["trace"].append({"url": h.get("url"), "xpath": h.get("xpath"), "at": time.time(), "by": "down"})
        return self._moved("down", {"cid": h["cid"], "url": h.get("url")},
                           [{"reveal": {"url": h.get("url"), "xpath": h.get("xpath") or "", "cid": h["cid"]}}])

    def _up(self) -> dict:
        if not self.artifact:
            raise ValueError("no artifact: ask a query first")
        cur = self.artifact["cursor"]
        if cur.get("at") == "trace":
            self.artifact["cursor"] = {"at": "results"}
            return self._moved("up", {"from": "trace", "to": "results", "cid": cur.get("cid")}, [])
        self.artifact["cursor"] = {"at": "query"}
        return self._moved("up", {"from": "results", "to": "query"}, [])

    def _act(self, act: dict) -> dict:
        if not isinstance(act, dict) or not act.get("address"):
            raise ValueError("act is {address, value}")
        value = act.get("value")
        cur = (self.artifact or {}).get("cursor") or {}
        if cur.get("at") == "trace":
            self._result(cur["cid"])["trace"].append({"act": str(act["address"]), "value": value,
                                                      "at": time.time(), "by": "act"})
        return self._moved("act", {"address": str(act["address"])},
                           [{"act": {"address": str(act["address"]), "value": None if value is None else str(value)}}])

    # -- the stream ----------------------------------------------------------
    def observe(self, url: str) -> Optional[dict]:
        """The browser cell is at ``url`` (the plugin's `browser_state`). In a
        trace, a url different from the trace's last step is a new step -- a
        diff on the artifact. Anywhere else nothing is recorded: navigation
        outside a descended result is the reader's own browsing."""
        cur = (self.artifact or {}).get("cursor") or {}
        if cur.get("at") != "trace" or not url:
            return None
        h = self._result(cur["cid"])
        last = next((s.get("url") for s in reversed(h["trace"]) if s.get("url")), None)
        if url == last:
            return None
        step = {"url": url, "at": time.time(), "by": "browser"}
        h["trace"].append(step)
        return self._moved("trace", {"cid": h["cid"], "url": url}, [])

    def since(self, version: int) -> dict:
        """What changed after ``version``: the diffs a panel applies."""
        return {"version": self.version, "changes": [c for c in self.log if c["version"] > int(version)]}

    def _moved(self, kind: str, what: dict, asks: List[dict]) -> dict:
        self.version += 1
        self.log.append({"version": self.version, "move": kind, **what})
        if len(self.log) > 500:
            del self.log[:-500]
        return {"artifact": self.artifact, "asks": asks, "moved": kind, "version": self.version}
