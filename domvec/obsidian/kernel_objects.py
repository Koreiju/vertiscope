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

if "create" not in globals():
    # The editor's own calls (G-386; PLUGIN_GOAL 172 [3]; mortegon §3A.7: the
    # agent authors with the user's primitives, "the cards are the API"). Each
    # records an ASK; the plugin carries it out on the plane when the cell ends,
    # by the same methods the gestures use -- the kernel never writes a card.

    def create(name, body="", kind="slate"):
        """Add a card to the plane: a slate (one typed row) or a notebook (a python cell)."""
        _domvec_asks.append({"create": {"name": str(name), "body": str(body), "kind": str(kind)}})
        return {"asked": "create", "name": str(name), "pending": True}

    def link(a, b):
        """Join two cards by an undirected link, as dragging one onto the other does."""
        _domvec_asks.append({"link": [str(a), str(b)]})
        return {"asked": "link", "cards": [str(a), str(b)], "pending": True}

    def invoke(name):
        """Run a card's cells in order, each lit as the run reaches it."""
        _domvec_asks.append({"invoke": str(name)})
        return {"asked": "invoke", "name": str(name), "pending": True}

    def commit(name, *members):
        """Keep a subgraph as one card that links each of its members."""
        _domvec_asks.append({"commit": {"name": str(name), "members": [str(m) for m in members]}})
        return {"asked": "commit", "name": str(name), "members": len(members), "pending": True}

    def review(name, question):
        """Ask the reader about a card before going on: the question is written onto it."""
        _domvec_asks.append({"review": [str(name), str(question)]})
        return {"asked": "review", "name": str(name), "pending": True}

if "similar" not in globals():
    # The toolspaces' calls (G-376, G-377; COMPUTATION_GRAPH_EDITOR_SPEC §8).
    # READS go to the sidecar's own routes, as `Database` does; calls that
    # change the world in place are ASKS the plugin carries out when the cell
    # ends, and each returns a value naming what it asked (G-380: invisible to
    # name dataflow otherwise).

    def _domvec_get(path, missing=None):
        try:
            with _ur.urlopen(%(base)r + path, timeout=120) as r:
                return _json.load(r)
        except _ue.HTTPError as e:
            if e.code == 404:
                return missing
            raise

    def similar(cid, k=8):
        """A chunk's nearest neighbours in the store: [{cid, url, text}]."""
        got = _domvec_get("/search?ref=" + _up.quote(str(cid), safe="") + "&k=" + str(int(k))) or {}
        return [{"cid": h.get("cid"), "url": h.get("url"), "text": h.get("preview") or ""}
                for h in (got.get("hits") or []) if h.get("cid") != cid]

    def chunk(cid):
        """A chunk's markdown, each line with its trie address: {cid, url, lines: [{text, key}]}."""
        got = _domvec_get("/chunk/" + _up.quote(str(cid), safe=""))
        if got is None:
            return None
        return {"cid": got.get("cid"), "url": got.get("url"),
                "lines": [{"text": l.get("text") or "", "key": l.get("key") or "", **({"control": l["control"]} if l.get("control") else {})}
                          for l in (got.get("lines") or [])]}

    def page_form(cid):
        """The saved page form of a chunk (its snapshot), or None."""
        return _domvec_get("/snapshot/" + _up.quote(str(cid), safe=""))

    def resolve(url, xpath):
        """The chunk that draws an address on a page."""
        return _domvec_get("/resolve?url=" + _up.quote(str(url), safe="") + "&xpath=" + _up.quote(str(xpath), safe=""))

    def pages(contains=""):
        """The page urls the store holds, optionally those containing a string."""
        got = _domvec_get("/pages" + ("?contains=" + _up.quote(str(contains), safe="") if contains else "")) or {}
        return list(got.get("urls") or [])

    def ego():
        """The ego: its notes and the chunks tagged into it."""
        return _domvec_get("/ego") or {}

    def types(q=""):
        """Types mined from trie-path patterns across pages (G-388): [{pattern, instances, pages, fields}]."""
        got = _domvec_get("/typegen?mine=1&limit=200") or {}
        s = str(q).lower()
        return [t for t in (got.get("types") or []) if not s or s in t["pattern"].lower() or any(s in f for f in t["fields"])]

    def check(slate):
        """The dialect's own errors over a slate's text: [{line, from, to, kind, message}]."""
        req = _ur.Request(%(base)r + "/slate_check", data=_json.dumps({"text": str(slate)}).encode(),
                          headers={"content-type": "application/json"})
        with _ur.urlopen(req, timeout=60) as r:
            return (_json.load(r) or {}).get("diagnostics") or []

    def focus(cid):
        """Fly the 3D view to a chunk's node."""
        _domvec_asks.append({"focus": str(cid)})
        return {"asked": "focus", "cid": str(cid), "pending": True}

    def unfold(url):
        """A page in the 3D view unfolded into every chunk the store holds of it."""
        _domvec_asks.append({"unfold": str(url)})
        return {"asked": "unfold", "url": str(url), "pending": True}

    def attach(cid):
        """Tag a chunk into the ego."""
        _domvec_asks.append({"attach": str(cid)})
        return {"asked": "attach", "cid": str(cid), "pending": True}

    def view(v):
        """The ego view in first or third person ("first" / "third")."""
        if str(v) not in ("first", "third"):
            raise ValueError("view is 'first' or 'third'")
        _domvec_asks.append({"view": str(v)})
        return {"asked": "view", "view": str(v), "pending": True}

if "run_role" not in globals():
    def run_role(role, prompt=None, cid=None, timeout=600, **inputs):
        """A local model ROLE run, TYPED (THROUGH_STACK_SYNTHESIS 1a-b): `chat`, `coder`,
        `code`, `plan`, `long` over a prompt -> {prose, code}; `triplex` over a chunk (cid)
        -> {entities, triples}. Returns {role, ok, value, error}: the role's type, or the
        reason it is not -- never coerced. The promise's TYPE half; check it in the next cell."""
        import time as _t
        body = dict(inputs, role=str(role), prompt=prompt, cid=cid)
        req = _ur.Request(%(base)r + "/model_run", data=_json.dumps(body).encode(),
                          headers={"content-type": "application/json"})
        try:
            with _ur.urlopen(req, timeout=60) as r:
                job = _json.load(r)
        except _ue.HTTPError as e:
            raise ValueError((_json.loads(e.read() or b"{}") or {}).get("error") or str(e))
        t0 = _t.time()
        while job.get("state") == "running" and _t.time() - t0 < timeout:
            _t.sleep(1.0)
            job = _domvec_get("/model_job?id=" + _up.quote(job["id"], safe="")) or job
        res = job.get("result") or {"role": role, "ok": False, "value": None, "error": job.get("error") or job.get("state")}
        return {k: res.get(k) for k in ("role", "ok", "value", "error")}

# Its own guard: a kernel already holding the calls above (`similar` defined)
# would otherwise never receive `browse` without a restart.
if "browse" not in globals():
    def browse(query=None, scope="web", of="", down=None, up=False, act=None, k=10):
        """The browser centroid's ONE tool (G-205): every move is this call.
        `query`+`scope` ("web" | "domain" | "page", `of` a page url) makes the
        retrieval artifact -- domain widens host -> registrable domain ->
        dual-embedding neighbours; `down=cid` opens that result's page in the
        browser cell at its address; `up=True` returns toward the query;
        `act={"address", "value"}` acts on a control in place. Returns the
        artifact; the cell's moves are carried out when this cell ends."""
        body = {"query": query, "scope": scope, "of": of, "down": down, "up": bool(up), "act": act, "k": int(k),
                "caller": globals().get("_domvec_note") or "kernel"}
        req = _ur.Request(%(base)r + "/browse", data=_json.dumps(body).encode(),
                          headers={"content-type": "application/json"})
        try:
            with _ur.urlopen(req, timeout=300) as r:
                got = _json.load(r) or {}
        except _ue.HTTPError as e:
            raise ValueError((_json.loads(e.read() or b"{}") or {}).get("error") or str(e))
        _domvec_asks.extend(got.get("asks") or [])
        return got.get("artifact")

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

        def pin(self, xpath):
            """Pin the element at an xpath of the page shown as a panel on the plane, as the right-click does."""
            _domvec_asks.append({"pin": str(xpath)})
            return {"asked": "pin", "xpath": str(xpath), "pending": True}

        def controls(self, cid=None):
            """The page's interactive fields by trie address: [{cid, key, text, control}]. One chunk, or
            the first 40 of the page shown."""
            out = []
            for c in ([cid] if cid else self.chunks()[:40]):
                got = chunk(c) or {}
                out += [{"cid": c, **l} for l in got.get("lines") or [] if l.get("control")]
            return out

        def act(self, address, value=None):
            """Act on a field in place through its trie address: press it, or type / choose `value`."""
            _domvec_asks.append({"act": {"address": str(address), "value": None if value is None else str(value)}})
            return {"asked": "act", "address": str(address), "pending": True}

        def __repr__(self):
            return "WebBrowser(url, title, go, chunks, pin, controls, act) at " + self._base

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

if "Chat" not in globals():
    class _Chat:
        """Chat: the chat note's turns as live state (G-412; spec 13h). `messages(note=None)` -- the
        turns of a note (default: this one) as [{role, content}], read from the note itself: the note
        is the record, this is its mirror. A cell that reads it re-runs when a turn is written."""
        def messages(self, note=None):
            """The note's turns, oldest first: [{role: user|assistant, content}]."""
            path = note or globals().get("_domvec_note") or ""
            text = (Vault.root / path).read_text(encoding="utf-8") if path else ""
            out, cur = [], None
            for line in text.split(chr(10)):
                if line.startswith("> **You** "):
                    if cur: out.append(cur)
                    cur = {"role": "user", "content": line[len("> **You** "):]}
                elif cur and cur["role"] == "user" and line.startswith("> "):
                    cur["content"] += chr(10) + line[2:]
                elif line.strip().startswith(chr(96) * 3 + "chat"):
                    break
                elif cur and cur["role"] == "user" and line.strip():
                    out.append(cur); cur = {"role": "assistant", "content": line}
                elif cur and cur["role"] == "assistant":
                    cur["content"] += chr(10) + line
            if cur: out.append(cur)
            for m in out: m["content"] = m["content"].strip()
            return out
        def __repr__(self):
            return "Chat(turns of the note)"
    Chat = _Chat()

if "answer" not in globals():
    import re as _re_answer

    def _domvec_card_path(name):
        """A card's vault path: the path itself, else `domvec/graph/<name>.md` (where
        `create` puts every card), else a card there whose name matches as the plane
        keys names (`editorcalls.ts` pathOf). Never a walk of the whole vault: run 89's
        first `answer` walked `build/` (250k+ files) and timed out at 60 s."""
        n = str(name)
        for cand in (n if n.endswith(".md") else n + ".md", "domvec/graph/" + (n if n.endswith(".md") else n + ".md")):
            if (Vault.root / cand).is_file():
                return cand
        key = lambda s: _re_answer.sub(r"\s+", "_", s.strip().lower())
        k = key(n[:-3] if n.endswith(".md") else n)
        folder = Vault.root / "domvec" / "graph"
        if folder.is_dir():
            for f in sorted(folder.glob("*.md")):
                if key(f.stem) == k:
                    return "domvec/graph/" + f.name
        return None

    def answer(name):
        """The reader's answer to the LAST review asked on a card (`review(name, question)`):
        the text after its `**answer:**`, or None while the reader has not written one.
        With `create` and `review`, the propose-and-approve loop (PLUGIN_GOAL 179, 180)."""
        p = _domvec_card_path(name)
        if not p:
            raise ValueError("no card %%s" %% name)
        text = Vault.read("/" + p)
        blocks = _re_answer.findall(r"(?m)^> \[!question\] review\n((?:>.*\n?)*)", text)
        if not blocks:
            return None
        m = _re_answer.search(r"(?m)^> \*\*answer:\*\*[ \t]*(.*(?:\n> (?!\*\*answer).*)*)", blocks[-1])
        got = "\n".join(l[2:] if l.startswith("> ") else l for l in (m.group(1) if m else "").split("\n")).strip()
        return got or None
'''


def vault_boot(root: str, note: str) -> str:
    """The vault facade for a kernel running `note` (vault-relative) under `root`."""
    folder = note.rsplit("/", 1)[0] if "/" in note else ""
    return VAULT_BOOT % {"root": root, "folder": folder}

#: Run after each cell: back to the vault root, out of the note's folder.
VAULT_DONE = "_os.chdir(Vault.root)"
