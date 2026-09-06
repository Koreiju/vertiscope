"""A local read-only window onto the store, for the Obsidian plugin.

The plugin runs in Electron and the store is embedded Kuzu behind Python, so
something has to sit between them. This is the smallest thing that can: a
stdlib HTTP server, bound to the loopback interface, that answers GET requests
and holds no write path at all.

Three decisions worth stating.

It binds 127.0.0.1 and nothing else. The store holds a browsing history --
the reason `Workspace.mirror_path` names its files by digest -- and a server
that answered on 0.0.0.0 would publish it to the local network.

It is read-only. There is no route that mutates the workspace, so a page
rendered in a vault cannot alter the store no matter what it contains.

It sends the line's ADDRESS, not just its text. The address key is the
`url:xpath:taxonomy:content` identity everything downstream is keyed on, and
it is what lets a click in Obsidian name an element in the real page. Sending
rendered text alone would make the surface a picture of the page rather than
a handle on it.
"""

from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional
from urllib.parse import unquote, urlsplit

from .export import _reflow


def chunk_payload(workspace, cid: str) -> Optional[Dict]:
    """One chunk as the plugin's `ChunkPayload`.

    The markdown's lines and `addresses_of` are aligned by the positional
    `anchors` contract -- one address per line, in line order -- so they are
    zipped rather than matched. That contract is asserted in the store's own
    tests; if it ever breaks, this silently mislabels every line, which is why
    the zip is strict about length rather than truncating.
    """
    stored = workspace.store.chunk(cid)
    if stored is None:
        return None

    addresses = workspace.addresses_for(cid)
    # Re-indented by nesting LEVEL before anyone sees it.
    #
    # The renderer indents by depth in the DOM, so a chunk rooted a few
    # elements down opens at column 10 -- and both consumers of this payload
    # put the lines into a markdown note, where four or more leading spaces is
    # an indented CODE BLOCK. The export learned this the hard way: 82 of 98
    # notes parsed as code and every wikilink in them was unreachable.
    #
    # Done here rather than in each caller so the `/` retrieval gesture, which
    # inserts these lines into a note directly, cannot reintroduce it.
    # `_reflow` maps one line to one line, so the positional `anchors`
    # alignment below is untouched.
    texts = _reflow(stored.md).splitlines()

    # An affordance is usually not the address the line is stored under.
    #
    # `interactive.links` is suppressed by the render, so the line an anchor
    # draws is stored under its `urls.*` or `text.visible` address instead --
    # and the store keeps ONE address per line, so the control is simply not
    # in `addresses_for`. Asking only that list reported 105 controls on a
    # six-page workspace, every one a button or a form, and not a single link
    # on a site that is almost entirely anchors.
    #
    # `addresses_at` is the lookup that answers this: every address at one
    # element, which is where the anchor's affordance actually sits. Cached
    # per element because a chunk draws the same element on several lines.
    control_cache: Dict[str, Optional[object]] = {}

    def control_at(element: str):
        if element not in control_cache:
            found = None
            for address, _value in workspace.store.addresses_at(
                    element, stored.url):
                if address.is_control:
                    found = address
                    break
            control_cache[element] = found
        return control_cache[element]

    lines: List[Dict] = []
    for i, text in enumerate(texts):
        entry: Dict[str, object] = {"text": text, "key": "", "cls": "text",
                                    "control": False}
        if i < len(addresses):
            address, value = addresses[i]
            entry["key"] = address.key()
            entry["cls"] = address.render_class
            entry["control"] = bool(address.is_control)
            if address.is_url:
                entry["target"] = value
            if not entry["control"]:
                found = control_at(address.xpath.split("/text()")[0])
                if found is not None:
                    entry["control"] = True
                    # The address that names the affordance, reported beside
                    # the line's own so a caller can still say where the line
                    # is stored. Enacting needs the control; navigating needs
                    # the line.
                    entry["control_key"] = found.key()
                    entry["cls"] = found.render_class
        lines.append(entry)

    return {
        "cid": stored.cid,
        "url": stored.url,
        "xpath": stored.xpath,
        "lines": lines,
        # Reported so a caller can tell a genuinely short chunk from a
        # misaligned one instead of guessing from the render.
        "addresses": len(addresses),
    }


def search_payload(workspace, query: str, k: int = 8) -> Dict:
    """The `/` retrieval gesture's answer: ranked chunks, with their notes.

    Ranking is the store's own three-form retrieval; this adds nothing to it.
    """
    hits = workspace.search(query, k=k)
    out = []
    for hit in hits:
        cid = getattr(hit, "cid", None) or getattr(hit, "chunk", "")
        stored = workspace.store.chunk(cid) if cid else None
        if stored is None:
            continue
        out.append({
            "cid": stored.cid,
            "url": stored.url,
            "score": float(getattr(hit, "score", 0.0) or 0.0),
            # The first lines only. The panel renders a preview and asks for
            # the rest when a reader opens it.
            "preview": "\n".join(stored.md.splitlines()[:6]),
        })
    return {"query": query, "hits": out}


class _Handler(BaseHTTPRequestHandler):
    workspace = None            # set by serve()

    # Silence the default stderr access log: it prints the requested path, and
    # the path carries the cid of whatever the reader is looking at.
    def log_message(self, *args) -> None:
        return

    def _send(self, code: int, body: Dict) -> None:
        raw = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        # Obsidian renders from app://obsidian.md, so the fetch is
        # cross-origin. Loopback-only binding is what limits reach here; the
        # header just makes the plugin's own fetch legal.
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self) -> None:                       # noqa: N802 (stdlib name)
        parts = urlsplit(self.path)
        segments = [unquote(s) for s in parts.path.strip("/").split("/") if s]

        if not segments or segments[0] == "health":
            self._send(200, {"ok": True, "pages": len(self.workspace.pages())})
            return

        if segments[0] == "chunk" and len(segments) == 2:
            payload = chunk_payload(self.workspace, segments[1])
            if payload is None:
                self._send(404, {"error": "no such chunk", "cid": segments[1]})
            else:
                self._send(200, payload)
            return

        if segments[0] == "search":
            from urllib.parse import parse_qs
            params = parse_qs(parts.query)
            query = (params.get("q") or [""])[0]
            # `k` is clamped rather than trusted: the caller is a plugin in
            # another process and an absent or absurd value must not turn a
            # keystroke into a full-workspace scan.
            try:
                k = int((params.get("k") or ["8"])[0])
            except ValueError:
                k = 8
            k = max(1, min(k, 50))
            if not query:
                self._send(400, {"error": "missing q"})
            else:
                self._send(200, search_payload(self.workspace, query, k))
            return

        self._send(404, {"error": "no such route", "path": parts.path})


def serve(workspace, port: int = 8787, *, block: bool = True):
    """Answer on loopback until stopped.

    Returns the server so a caller that passed ``block=False`` can shut it
    down; a test that leaks one wedges the port for the next run.
    """
    handler = type("_Bound", (_Handler,), {"workspace": workspace})
    server = ThreadingHTTPServer(("127.0.0.1", port), handler)
    if block:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            server.server_close()
        return server
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
