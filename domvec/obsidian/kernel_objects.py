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

        def search(self, query, k=5, where=""):
            """Ranked chunks from the store: [{cid, url, text}]."""
            url = self._base + "/search?q=" + _up.quote(str(query)) + "&k=" + str(int(k))
            if where:
                url += "&where=" + _up.quote(str(where))
            with _ur.urlopen(url, timeout=120) as r:
                got = _json.load(r)
            return [{"cid": h.get("cid"), "url": h.get("url"), "text": h.get("preview") or ""}
                    for h in (got.get("hits") or [])]

        def cypher(self, query):
            """A read-only Cypher query over the store; writes are refused."""
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

    def search(query, db=True, duckduckgo=False, k=8, where=""):
        """search(query, db=True, duckduckgo=False, k=8, where=""): the database's ranking, the web's
        (through the browser cell), or both. `where` is "ego" (the computation graph's own artifacts
        and the chunks tagged into the ego), "web" (the world without them), or "" (everything).
        The web's results arrive in the store as the cell captures them."""
        out = []
        if db:
            out += [dict(h, source="db") for h in Database.search(query, k, where)]
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

if "WebBrowser" not in globals():
    class _WebBrowser:
        """WebBrowser: the browser cell, from a kernel. `url` -- what it shows now; `go(url)` -- asked of
        the cell, carried out when this cell ends; `chunks(url=None)` -- what the store holds of a page."""

        def __init__(self, base):
            self._base = base

        @property
        def url(self):
            """The url the browser cell shows now."""
            with _ur.urlopen(self._base + "/browser_state", timeout=30) as r:
                return (_json.load(r) or {}).get("url") or ""

        @property
        def title(self):
            """The title of the page the browser cell shows."""
            with _ur.urlopen(self._base + "/browser_state", timeout=30) as r:
                return (_json.load(r) or {}).get("title") or ""

        def go(self, url):
            """Ask the browser cell to open a url; carried out when the cell ends."""
            _domvec_asks.append({"go": str(url)})
            return {"asked": str(url), "pending": True}

        def chunks(self, url=None):
            """The chunk ids the store holds for a page (default: the one shown)."""
            u = url or self.url
            if not u:
                return []
            with _ur.urlopen(self._base + "/page_map?url=" + _up.quote(u, safe=""), timeout=60) as r:
                return sorted(((_json.load(r) or {}).get("chunks") or {}).keys())

        def __repr__(self):
            return "WebBrowser(url, title, go, chunks) at " + self._base

    WebBrowser = _WebBrowser(%(base)r)

if "Agent" not in globals():
    import uuid as _uuid

    class _Agent:
        """Agent: the local model, from a kernel. `ask(prompt, context=None)` -> its reply, one session
        per kernel (the model keeps the turns); `context` a list of strings or {markdown, url} dicts."""

        def __init__(self, base):
            self._base = base
            self._session = "kernel-" + _uuid.uuid4().hex[:12]
            self.model = ""

        def ask(self, prompt, context=None):
            """The local model's reply to a prompt, given chunks as context."""
            ctx = []
            for i, c in enumerate(context or []):
                if isinstance(c, str):
                    c = {"markdown": c}
                ctx.append({"cid": str(c.get("cid") or "kernel:%%d" %% i), "url": str(c.get("url") or ""),
                            "markdown": str(c.get("markdown") or c.get("text") or ""), "head": str(c.get("head") or "from the kernel")})
            req = _ur.Request(self._base + "/chat", data=_json.dumps({"session": self._session, "prompt": str(prompt),
                              "context": ctx}).encode(), headers={"content-type": "application/json"})
            with _ur.urlopen(req, timeout=300) as r:
                got = _json.load(r)
            if got.get("error") or not got.get("turn"):
                raise RuntimeError(got.get("error") or "the model did not answer")
            self.model = got.get("model") or self.model
            return got["turn"].get("reply") or ""

        def __repr__(self):
            return "Agent(ask) -- " + (self.model or "the sidecar's local model") + " at " + self._base

    Agent = _Agent(%(base)r)
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


#: The vault facade (P-N4): "a facade for [the vault interface] to expose local
#: jupyter terminals to the filestructure and space". Defined once per kernel;
#: each run sets `Vault.here` to the running note's folder and moves the
#: kernel's working directory there, so a cell's `open("data.csv")` reads the
#: file beside its note. Reads anywhere in the vault; writes only inside it and
#: never into `.obsidian` or `.git` -- Obsidian's own file watcher then shows
#: what a cell wrote, as it shows any file.
VAULT_BOOT = r'''
if "Vault" not in globals():
    import os as _os, fnmatch as _fn
    from pathlib import Path as _P

    class _Vault:
        """Vault: the notes' file structure. here, ls(path), read(path), write(path, text), glob(pattern)."""

        _GUARDED = (".obsidian", ".git")

        def __init__(self, root):
            self.root = _P(root).resolve()
            self.here = self.root

        def _at(self, path, writing=False):
            p = (self.here / str(path)).resolve() if not str(path).startswith("/") else (self.root / str(path).lstrip("/")).resolve()
            if p != self.root and self.root not in p.parents:
                raise PermissionError("outside the vault: %%s" %% path)
            rel = p.relative_to(self.root).parts
            if writing and rel and rel[0] in self._GUARDED:
                raise PermissionError("the vault's own settings are not written from a cell: %%s" %% path)
            return p

        def ls(self, path="."):
            """The entries of a vault folder."""
            p = self._at(path)
            return sorted((c.name + ("/" if c.is_dir() else "")) for c in p.iterdir() if c.name not in self._GUARDED)

        def read(self, path):
            """A vault file's text."""
            return self._at(path).read_text(encoding="utf-8")

        def write(self, path, text):
            """Write a vault file (inside the vault, never .obsidian or .git)."""
            p = self._at(path, writing=True)
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(str(text), encoding="utf-8")
            return p.relative_to(self.root).as_posix()

        def glob(self, pattern):
            """Vault paths matching a glob pattern."""
            return sorted(c.relative_to(self.root).as_posix() for c in self.root.rglob("*")
                          if c.is_file() and _fn.fnmatch(c.relative_to(self.root).as_posix(), pattern)
                          and c.relative_to(self.root).parts[0] not in self._GUARDED)

        def __repr__(self):
            return "Vault(here=%%r)" %% self.here.relative_to(self.root).as_posix()

    Vault = _Vault(%(root)r)
Vault.here = Vault._at("/" + %(folder)r) if %(folder)r else Vault.root
_os.chdir(Vault.here)
'''


def vault_boot(root: str, note: str) -> str:
    """The vault facade for a kernel running `note` (vault-relative) under `root`."""
    folder = note.rsplit("/", 1)[0] if "/" in note else ""
    return VAULT_BOOT % {"root": root, "folder": folder}

#: Run after each cell: back to the vault root, out of the note's folder.
VAULT_DONE = "_os.chdir(Vault.root)"
