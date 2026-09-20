"""An MCP server over the distiller, for agents working inside the vault.

MCP is JSON-RPC 2.0 over stdio, so this needs no SDK -- which suits a project
that keeps its dependency list short, and means the server runs anywhere the
package does.

**What it deliberately does not expose.** Note reading and writing already
have an MCP server, and a second one would be two sources of truth for the
same files. This exposes only what nothing else can: the
`url:xpath:taxonomy:content` address trie, the three-form retrieval, and the
affordances at a chunk. The vault's own MCP edits notes; this one answers
questions about the pages behind them.

**Read-only, again on purpose.** There is no tool here that enacts an
affordance. Driving a real browser from an agent loop is a different kind of
act from answering a question about a stored page, and it should be an
explicit choice with its own gate rather than a capability that arrives
quietly alongside search. `affordances` reports what COULD be pressed and the
address that names it; pressing is not wired.

**stdout carries the protocol and nothing else.** A stray print corrupts the
stream and the client reports a parse error with no clue where it came from,
so diagnostics go to stderr.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Callable, Dict, List, Optional

from .sidecar import chunk_payload, search_payload

#: Echoed back when the client asks for it; otherwise the client's version is
#: returned when we can speak it. Version negotiation is a handshake, not a
#: constant, and pinning one here would refuse clients we can serve.
PROTOCOL = "2025-11-25"
SUPPORTED = {"2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"}

SERVER = {
    "name": "domvec",
    "title": "domvec distiller",
    "version": "0.1.0",
    "description": "Addressed web chunks, three-form retrieval, and the "
                   "affordances a page offers.",
}

TOOLS: List[Dict] = [
    {
        "name": "ui_state",
        "description":
            "The plugin's interface as a data structure, in SCREEN pixels: "
            "which panes are open and actually DRAWN (not merely present), "
            "and for the projector a node census on screen -- how many are "
            "off the canvas, how many overlap at the drawn radius, what "
            "share of the canvas the cloud uses, and how far the render "
            "drifted from the fit. Use this instead of a screenshot.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "ui_act",
        "description":
            "Perform a gesture through the application's own code paths and "
            "return the UI before, the UI after, and the BACKEND calls it "
            "caused, with timings by route. Gestures: open (graph|browser|"
            "terminal), reveal, navigate <url>, scan, level (page|chunk).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "gesture": {"type": "string"},
                "arg": {},
                "full": {"type": "boolean",
                         "description": "every captured call, not the shape"},
            },
            "required": ["gesture"],
        },
    },
    {
        "name": "live_health",
        "description":
            "Is the sidecar answering, is the plugin's harness installed, "
            "and which panes are open. Either half can be the problem and "
            "this says which.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "search",
        "title": "Search distilled chunks",
        "description": "Rank stored web chunks against a query using the "
                       "workspace's three-form retrieval. Returns each hit's "
                       "chunk id, source url, score and a short preview.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to look for"},
                "k": {"type": "integer", "description": "How many hits (default 8)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "chunk",
        "title": "Read a chunk",
        "description": "Every line of one chunk with its content address, "
                       "render class, and whether it is an affordance.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cid": {"type": "string", "description": "Chunk id"},
            },
            "required": ["cid"],
        },
    },
    {
        "name": "affordances",
        "title": "What a chunk offers",
        "description": "Only the pressable things in a chunk -- links, "
                       "buttons, fields -- each with the address that names "
                       "it in the page. Reports; does not press.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cid": {"type": "string", "description": "Chunk id"},
            },
            "required": ["cid"],
        },
    },
    {
        "name": "resolve_address",
        "title": "Address to chunk",
        "description": "Given a `url:xpath:taxonomy:content` address key, the "
                       "chunk that draws it. This is the navigational step: "
                       "an address found in one chunk names a place, and this "
                       "returns the place.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "address": {"type": "string", "description": "Address key"},
            },
            "required": ["address"],
        },
    },
    {
        "name": "pages",
        "title": "Pages in the workspace",
        "description": "Every page the workspace holds.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


class DomvecMCP:
    """Dispatch for the handful of methods a tools-only server must answer."""

    def __init__(self, workspace=None, sidecar_url="http://127.0.0.1:8788", cdp_url="http://127.0.0.1:9222"):
        self.ws = workspace
        # Where the running system is. Defaults match the plugin's own.
        self.sidecar_url = sidecar_url
        self.cdp_url = cdp_url
        self.handlers: Dict[str, Callable] = {
            "search": self._search,
            "chunk": self._chunk,
            "affordances": self._affordances,
            "resolve_address": self._resolve,
            "pages": self._pages,
            "ui_state": self._ui_state,
            "ui_act": self._ui_act,
            "live_health": self._live_health,
        }
        # Built lazily: the live endpoints may not be up, and a server that
        # refuses to start because the app is closed is useless for finding
        # out that the app is closed.
        self._live = None

    # --- the running system --------------------------------------------------

    def live(self):
        if self._live is None:
            from .live import Live
            self._live = Live(sidecar=self.sidecar_url, cdp=self.cdp_url)
        return self._live

    def _ui_state(self, args: Dict) -> Dict:
        return self.live().ui()

    def _ui_act(self, args: Dict) -> Dict:
        return self.live().act(args["gesture"], args.get("arg"),
                               bool(args.get("full")))

    def _live_health(self, args: Dict) -> Dict:
        return self.live().health()

    # --- tools ---------------------------------------------------------------

    # **Through the sidecar when there is no store, which is the usual
    # case.** `--workspace` was made optional so this server could stop
    # fighting the plugin for kuzu's writer lock, and these five handlers
    # were left calling a workspace that is now None -- every one of them
    # answered "'NoneType' object has no attribute ...". The sidecar already
    # serves each of these questions over HTTP, from the store the plugin is
    # actually using, which is the one worth asking about.

    def _search(self, args: Dict) -> Dict:
        query, k = args["query"], int(args.get("k") or 8)
        if self.ws is not None:
            return search_payload(self.ws, query, k)
        from urllib.parse import quote
        got = self.live().get("/search?q=%s&k=%d" % (quote(query), k))
        # The sidecar answers with full chunk payloads; a search result is a
        # ranked list and a preview, not a transcript.
        # The sidecar already sends a `preview`; rebuilding one from a
        # `lines` key it does not send produced an empty string on every hit.
        hits = []
        for h in (got.get("hits") or []):
            hits.append({
                "cid": h.get("cid"), "url": h.get("url"),
                "xpath": h.get("xpath"),
                "score": h.get("score"),
                "lexical": h.get("lexical"), "semantic": h.get("semantic"),
                "pagerank": h.get("pagerank"),
                "preview": (h.get("preview") or "")[:240],
            })
        return {"query": query, "hits": hits, "count": len(hits)}

    def _chunk(self, args: Dict) -> Dict:
        if self.ws is not None:
            payload = chunk_payload(self.ws, args["cid"])
            if payload is None:
                raise KeyError("no chunk %s" % args["cid"])
            return payload
        from urllib.parse import quote
        return self.live().get("/chunk/%s" % quote(str(args["cid"])))

    def _affordances(self, args: Dict) -> Dict:
        payload = self._chunk(args)
        acts = [ln for ln in (payload.get("lines") or []) if ln.get("control")]
        return {"cid": payload.get("cid"), "url": payload.get("url"),
                "affordances": acts, "count": len(acts)}

    def _resolve(self, args: Dict) -> Dict:
        from ..address import ContentAddress
        address = ContentAddress.parse(args["address"])
        if self.ws is not None:
            stored = self.ws.store.chunk_for_address(address.aid)
            if stored is None:
                return {"address": args["address"], "chunk": None}
            return {"address": args["address"], "chunk": {
                "cid": stored.cid, "url": stored.url, "xpath": stored.xpath,
                "preview": "\n".join(stored.md.splitlines()[:6])}}
        # `/resolve` walks UP from an address to the nearest chunk the trie
        # holds, which is the same question this tool asks.
        from urllib.parse import quote
        try:
            got = self.live().get(
                "/resolve?url=%s&xpath=%s"
                % (quote(address.url), quote(address.xpath)))
        except Exception as exc:                    # noqa: BLE001
            return {"address": args["address"], "chunk": None,
                    "why": str(exc)[:160]}
        lines = got.get("lines") or []
        return {"address": args["address"], "chunk": {
            "cid": got.get("cid"), "url": got.get("url"),
            "xpath": got.get("xpath"),
            "matched_xpath": got.get("matched_xpath"),
            "ancestors_walked": got.get("ancestors_walked"),
            "preview": "\n".join(
                str(ln.get("text", "")) for ln in lines[:6])}}

    def _pages(self, args: Dict) -> Dict:
        if self.ws is not None:
            return {"pages": list(self.ws.pages())}
        got = self.live().get("/pages")
        return {"pages": got.get("urls") or [], "count": got.get("n")}

    # --- protocol ------------------------------------------------------------

    def handle(self, message: Dict) -> Optional[Dict]:
        """One request in, at most one response out.

        A notification carries no `id` and MUST NOT be answered -- replying to
        one is a protocol error that some clients report only as a hang.
        """
        method = message.get("method")
        mid = message.get("id")
        is_notification = mid is None

        try:
            if method == "initialize":
                asked = (message.get("params") or {}).get("protocolVersion")
                result = {
                    "protocolVersion": asked if asked in SUPPORTED else PROTOCOL,
                    "capabilities": {"tools": {"listChanged": False}},
                    "serverInfo": SERVER,
                    "instructions":
                        "Addressed web chunks from the domvec distiller. "
                        "Search first, then read a chunk by its cid. Every "
                        "line carries a content address; `resolve_address` "
                        "turns one back into the chunk that draws it. "
                        "Read-only: affordances are reported, never pressed.",
                }
            elif method in ("notifications/initialized", "notifications/cancelled"):
                return None
            elif method == "ping":
                result = {}
            elif method == "tools/list":
                result = {"tools": TOOLS}
            elif method == "tools/call":
                params = message.get("params") or {}
                name = params.get("name")
                handler = self.handlers.get(name)
                if handler is None:
                    return _error(mid, -32602, "no such tool: %s" % name)
                try:
                    payload = handler(params.get("arguments") or {})
                except Exception as exc:
                    # A tool that fails is a RESULT with isError, not a
                    # protocol error: the model is meant to see the message
                    # and choose again, which a transport error denies it.
                    return _ok(mid, {
                        "content": [{"type": "text", "text": str(exc)}],
                        "isError": True,
                    })
                result = {
                    "content": [{"type": "text",
                                 "text": json.dumps(payload, indent=2)}],
                    "isError": False,
                }
            else:
                if is_notification:
                    return None
                return _error(mid, -32601, "no such method: %s" % method)
        except Exception as exc:                    # pragma: no cover
            if is_notification:
                return None
            return _error(mid, -32603, str(exc))

        return None if is_notification else _ok(mid, result)


def _ok(mid, result: Dict) -> Dict:
    return {"jsonrpc": "2.0", "id": mid, "result": result}


def _error(mid, code: int, message: str) -> Dict:
    return {"jsonrpc": "2.0", "id": mid,
            "error": {"code": code, "message": message}}


def serve_stdio(workspace=None, stdin=None, stdout=None, *, sidecar_url="http://127.0.0.1:8788", cdp_url="http://127.0.0.1:9222") -> None:
    """Read line-delimited JSON-RPC until stdin closes."""
    server = DomvecMCP(workspace, sidecar_url=sidecar_url, cdp_url=cdp_url)
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout

    for raw in stdin:
        raw = raw.strip()
        if not raw:
            continue
        try:
            message = json.loads(raw)
        except json.JSONDecodeError as exc:
            reply = _error(None, -32700, "parse error: %s" % exc)
        else:
            reply = server.handle(message)
        if reply is None:
            continue
        stdout.write(json.dumps(reply) + "\n")
        stdout.flush()


def main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        prog="python -m domvec.obsidian.mcp",
        description="MCP server over a domvec workspace (stdio, read-only).")
    parser.add_argument("--workspace", type=Path, default=None,
                        help="optional: open a store DIRECTLY for the "
                             "backend tools. Usually wrong -- the sidecar "
                             "holds the live workspace and a kuzu writer "
                             "excludes readers, so this loses the race or "
                             "takes the lock the plugin needs. Left unset, "
                             "the backend tools ask the sidecar instead.")
    parser.add_argument("--sidecar", default="http://127.0.0.1:8788")
    parser.add_argument("--cdp", default="http://127.0.0.1:9222")
    args = parser.parse_args(argv)

    ws = None
    if args.workspace is not None:
        from ..workspace import Workspace
        try:
            ws = Workspace(args.workspace, read_only=True)
        except Exception as exc:                    # noqa: BLE001
            # A corrupt freq matrix used to kill this server at import time
            # and the only symptom the client showed was CONNECTION_CLOSED.
            # Degrade to the live tools and SAY so.
            print("domvec MCP: no store (%s); live tools only"
                  % str(exc)[:120], file=sys.stderr)
            ws = None

    print("domvec MCP: sidecar %s, app %s%s"
          % (args.sidecar, args.cdp, ", store open" if ws else ""),
          file=sys.stderr)
    try:
        serve_stdio(ws, sidecar_url=args.sidecar, cdp_url=args.cdp)
    finally:
        if ws is not None:
            ws.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
