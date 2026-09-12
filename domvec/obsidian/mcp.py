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

    def __init__(self, workspace):
        self.ws = workspace
        self.handlers: Dict[str, Callable] = {
            "search": self._search,
            "chunk": self._chunk,
            "affordances": self._affordances,
            "resolve_address": self._resolve,
            "pages": self._pages,
        }

    # --- tools ---------------------------------------------------------------

    def _search(self, args: Dict) -> Dict:
        return search_payload(self.ws, args["query"], int(args.get("k") or 8))

    def _chunk(self, args: Dict) -> Dict:
        payload = chunk_payload(self.ws, args["cid"])
        if payload is None:
            raise KeyError("no chunk %s" % args["cid"])
        return payload

    def _affordances(self, args: Dict) -> Dict:
        payload = chunk_payload(self.ws, args["cid"])
        if payload is None:
            raise KeyError("no chunk %s" % args["cid"])
        acts = [ln for ln in payload["lines"] if ln.get("control")]
        return {"cid": payload["cid"], "url": payload["url"],
                "affordances": acts, "count": len(acts)}

    def _resolve(self, args: Dict) -> Dict:
        from ..address import ContentAddress
        address = ContentAddress.parse(args["address"])
        stored = self.ws.store.chunk_for_address(address.aid)
        if stored is None:
            return {"address": args["address"], "chunk": None}
        return {"address": args["address"], "chunk": {
            "cid": stored.cid, "url": stored.url, "xpath": stored.xpath,
            "preview": "\n".join(stored.md.splitlines()[:6])}}

    def _pages(self, args: Dict) -> Dict:
        return {"pages": list(self.ws.pages())}

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


def serve_stdio(workspace, stdin=None, stdout=None) -> None:
    """Read line-delimited JSON-RPC until stdin closes."""
    server = DomvecMCP(workspace)
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
    parser.add_argument("--workspace", required=True, type=Path)
    args = parser.parse_args(argv)

    from ..workspace import Workspace
    # Read-only is the whole point of this server, and asking kuzu for
    # it is what lets the server run BESIDE a sidecar on one workspace
    # rather than losing a race to whichever started first.
    with Workspace(args.workspace, read_only=True) as ws:
        print("domvec MCP: %d pages, read-only" % len(ws.pages()),
              file=sys.stderr)
        serve_stdio(ws)
    return 0


if __name__ == "__main__":
    sys.exit(main())
