"""The base API objects inside a note's kernel (G-279; the mothership's F.2).

`docs/RESERVOIR_DESIGN.md` §4: the three base objects are kernel objects,
typed and read-only. `Database` is the first: `search(query)` over this
workspace's retrieval, and `cypher(query)` READ-ONLY over its store. Both go
through the sidecar's own routes, so a cell sees exactly what the app sees
and cannot write the store behind the lifecycle's back.

`BOOT` runs in the kernel before each cell (idempotent: it defines the
objects once). WebBrowser waits on the browser cell; Agent on the local model.
"""

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
'''


def boot(base: str) -> str:
    """The bootstrap for a kernel talking to the sidecar at `base`."""
    return BOOT % {"base": base}
