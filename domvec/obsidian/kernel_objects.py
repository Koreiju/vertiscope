"""The base API objects inside a note's kernel (G-279; the mothership's F.2).

`docs/RESERVOIR_DESIGN.md` §4: the three base objects are kernel objects,
typed and read-only. `Database` is the first: `search(query)` over this
workspace's retrieval, and `cypher(query)` READ-ONLY over its store. Both go
through the sidecar's own routes, so a cell sees exactly what the app sees
and cannot write the store behind the lifecycle's back.

`BOOT` runs in the kernel before each cell (idempotent: it defines the
objects once). WebBrowser waits on the browser cell; Agent on the local model.

`search(query, db=True, duckduckgo=False, k=8)` is the first computation-graph
artifact's Python (RESERVOIR_DESIGN §6b; PLUGIN_GOAL item 32: "the minimal most
python code representation for calling a "search" function either in the db or
also in duckduckgo or just duckduckgo"). `db` is `Database.search`. DuckDuckGo
is the BROWSER CELL's web search, never a scraper of the kernel's own: the
kernel cannot reach the plugin, so it records an ASK, the sidecar drains the
asks after the cell (`DRAIN`, `asks`) and returns them in the reply, and the
plugin hands the query to the browser cell -- whose captured results reach
the store, and so `db`, like any page.
"""

import ast
import json

import re

#: Cypher that would write, or call a procedure (a checkpoint, an install),
#: is refused: the kernel reads the store, it does not edit it.
WRITES = re.compile(r"\b(CREATE|MERGE|SET|DELETE|DETACH|REMOVE|DROP|ALTER|COPY|INSTALL|LOAD|CALL|IMPORT|EXPORT)\b", re.I)

BOOT = r'''
if "Database" not in globals():
    import json as _json, urllib.error as _ue, urllib.parse as _up, urllib.request as _ur

    class _Database:
        """Database (read-only): search(query, k=5) and cypher(query) over this workspace."""

        def __init__(self, base):
            self._base = base

        def search(self, query, k=5):
            url = self._base + "/search?q=" + _up.quote(str(query)) + "&k=" + str(int(k))
            with _ur.urlopen(url, timeout=120) as r:
                got = _json.load(r)
            return [{"cid": h.get("cid"), "url": h.get("url"), "text": h.get("preview") or ""}
                    for h in (got.get("hits") or [])]

        def cypher(self, query):
            req = _ur.Request(self._base + "/cypher", data=_json.dumps({"query": str(query)}).encode(),
                              headers={"content-type": "application/json"})
            try:
                with _ur.urlopen(req, timeout=120) as r:
                    got = _json.load(r)
            except _ue.HTTPError as e:              # the route's refusal, said in words
                got = _json.loads(e.read() or b"{}") or {"error": str(e)}
            if got.get("error"):
                raise RuntimeError(got["error"])
            return got.get("rows") or []

        def __repr__(self):
            return "Database(search, cypher) at " + self._base

    Database = _Database(%(base)r)

if "search" not in globals():
    _domvec_asks = []

    def search(query, db=True, duckduckgo=False, k=8):
        """search(query, db=True, duckduckgo=False, k=8): the database's ranking, the web's (through
        the browser cell), or both. The web's results arrive in the store as the cell captures them."""
        out = []
        if db:
            out += [dict(h, source="db") for h in Database.search(query, k)]
        if duckduckgo:
            _domvec_asks.append({"web": str(query)})
            out.append({"cid": None, "source": "duckduckgo", "pending": True,
                        "url": "https://duckduckgo.com/?q=" + _up.quote(str(query)),
                        "text": "asked of the browser cell; its results reach the store as it captures them"})
        return out[:max(int(k), 1) + (1 if duckduckgo else 0)]

    def _domvec_drain_asks():
        got = list(_domvec_asks)
        _domvec_asks.clear()
        return _json.dumps(got)
'''

#: Run after each cell: the asks its calls recorded, as the repr of a JSON string.
DRAIN = "_domvec_drain_asks()"


def parse_asks(reply) -> list:
    """The asks out of `DRAIN`'s reply; [] for anything else."""
    try:
        v = (reply or {}).get("value")
        got = json.loads(ast.literal_eval(v)) if v else []
        return [a for a in got if isinstance(a, dict)]
    except Exception:                               # noqa: BLE001
        return []


def boot(base: str) -> str:
    """The bootstrap for a kernel talking to the sidecar at `base`."""
    return BOOT % {"base": base}
