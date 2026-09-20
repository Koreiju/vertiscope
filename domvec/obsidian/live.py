"""Full-stack observability for the MCP server: the running app, not a store.

**Why this is not the workspace.** `mcp.py` opened the store directly. Two
things are wrong with that, and both were measured rather than argued:

* It cannot run beside the plugin. kuzu's writer excludes readers, and the
  sidecar holds the workspace with ``--capture``, so an MCP server asking
  for the same directory either loses the race or takes the lock the plugin
  needs. The docstring claimed read-only made them coexist; the store's own
  error message says otherwise.
* It answers the wrong questions. Its five tools -- search, chunk,
  affordances, resolve_address, pages -- are all BACKEND. Nothing there can
  say whether a node is on screen, and that gap is how three requirements
  passed while the projector drew a clump.

So this talks to the two things that are actually running:

* the **sidecar**, over HTTP, for what the trie holds;
* **Obsidian**, over the debug port, for what the reader sees and for
  driving the interface.

The UI side is one evaluation of ``window.__domvec``, which the plugin
installs (`harness.ts`). The plugin reports its own state because the views
know it and because a snapshot that lives beside the UI breaks loudly when
the UI is renamed, instead of quietly returning ``undefined``.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Dict, Optional


class Live:
    """The running system, as two endpoints."""

    def __init__(self, sidecar: str = "http://127.0.0.1:8788",
                 cdp: str = "http://127.0.0.1:9222", timeout: float = 120.0):
        self.sidecar = sidecar.rstrip("/")
        self.cdp = cdp.rstrip("/")
        self.timeout = timeout

    # -- the sidecar ---------------------------------------------------------

    def get(self, path: str) -> Dict:
        req = urllib.request.Request(self.sidecar + path)
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.load(r)

    def post(self, path: str, payload: Dict) -> Dict:
        req = urllib.request.Request(
            self.sidecar + path, data=json.dumps(payload).encode(),
            headers={"content-type": "application/json"}, method="POST")
        with urllib.request.urlopen(req, timeout=self.timeout) as r:
            return json.load(r)

    # -- the app -------------------------------------------------------------

    def _page_target(self) -> str:
        """The renderer's websocket.

        Obsidian exposes several targets; the one with a `webSocketDebuggerUrl`
        and a page type is the window. A webview guest also shows up here,
        which is why the title is checked rather than taking the first.
        """
        with urllib.request.urlopen(self.cdp + "/json", timeout=10) as r:
            targets = json.load(r)
        pages = [t for t in targets
                 if t.get("type") == "page" and t.get("webSocketDebuggerUrl")]
        if not pages:
            raise RuntimeError("no debuggable page on " + self.cdp)
        # Prefer the app window over any guest: the guest has no plugin on it.
        for t in pages:
            if "obsidian" in (t.get("url") or "").lower() or \
               (t.get("url") or "").startswith("app://"):
                return t["webSocketDebuggerUrl"]
        return pages[0]["webSocketDebuggerUrl"]

    def evaluate(self, expression: str, timeout: Optional[float] = None) -> object:
        """Run an expression in the renderer and return its value.

        Uses `websocket-client` if present and falls back to a minimal frame
        writer otherwise, because adding a dependency to be able to ask a
        question is a poor trade for a diagnostic tool.
        """
        from websocket import create_connection      # websocket-client

        # **No Origin header.** Chrome refuses a CDP websocket that carries
        # one -- "Rejected an incoming WebSocket connection", a 403 at the
        # handshake -- and websocket-client sends one by default. Node's
        # WebSocket does not, which is why cdp.mjs never met this.
        ws = create_connection(self._page_target(),
                               timeout=timeout or self.timeout,
                               suppress_origin=True)
        try:
            ws.send(json.dumps({
                "id": 1,
                "method": "Runtime.evaluate",
                "params": {
                    "expression": expression,
                    "awaitPromise": True,
                    "returnByValue": True,
                    # The pane is often not the focused window, and an
                    # occluded renderer does not run timers the same way.
                    "userGesture": True,
                },
            }))
            while True:
                msg = json.loads(ws.recv())
                if msg.get("id") != 1:
                    continue                      # an event, not our reply
                res = msg.get("result", {})
                if "exceptionDetails" in res:
                    raise RuntimeError(
                        "page threw: %s" % res["exceptionDetails"]
                        .get("text", "?"))
                return res.get("result", {}).get("value")
        finally:
            ws.close()

    # -- the tools -----------------------------------------------------------

    def ui(self) -> Dict:
        """The interface as a data structure, in screen pixels."""
        got = self.evaluate(
            "JSON.stringify(window.__domvec ? window.__domvec.ui() "
            ": {error: 'harness not installed; reload the plugin'})")
        return json.loads(got) if isinstance(got, str) else {"error": "no value"}

    def act(self, gesture: str, arg: object = None, full: bool = False) -> Dict:
        """Do a thing, and report the UI either side plus the backend work.

        This is the whole point of the live server: a chained interaction --
        open a pane, navigate, scan, watch the trie fill -- used to be a
        dozen round trips and a guess about ordering.
        """
        expr = (
            "window.__domvec.act(%s, %s, {full: %s}).then(JSON.stringify)"
            % (json.dumps(gesture), json.dumps(arg),
               "true" if full else "false"))
        got = self.evaluate(expr)
        return json.loads(got) if isinstance(got, str) else {"error": "no value"}

    def health(self) -> Dict:
        """Both halves, in one answer, because either can be the problem."""
        out: Dict[str, object] = {}
        try:
            out["sidecar"] = self.get("/health")
        except Exception as exc:                    # noqa: BLE001
            out["sidecar"] = {"error": str(exc)[:160]}
        try:
            ui = self.ui()
            out["app"] = {
                "harness": "error" not in ui,
                "panes": ui.get("panes"),
            }
        except Exception as exc:                    # noqa: BLE001
            out["app"] = {"error": str(exc)[:160]}
        return out
