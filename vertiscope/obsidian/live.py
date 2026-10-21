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

The UI side is one evaluation of ``window.__vertiscope``, which the plugin
installs (`harness.ts`). The plugin reports its own state because the views
know it and because a snapshot that lives beside the UI breaks loudly when
the UI is renamed, instead of quietly returning ``undefined``.
"""

from __future__ import annotations

import json
from pathlib import Path
import urllib.error
import urllib.request
from typing import Dict, Optional


class Live:
    """The running system, as two endpoints."""

    def __init__(self, sidecar: str = "http://127.0.0.1:8788",
                 cdp: str = "", timeout: float = 120.0):
        self.sidecar = sidecar.rstrip("/")
        # `VERTISCOPE_CDP` names the app's debug port when 9222 is taken (a Chrome
        # holding 9222 answered for the app on 2026-10-07).
        import os as _os
        self.cdp = (cdp or _os.environ.get("VERTISCOPE_CDP") or "http://127.0.0.1:9222").rstrip("/")
        self.timeout = timeout
        self._ws = None
        self._next_id = 0

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
        # The workspace window first: the vault picker is ALSO an app://
        # page (`starter.html`), has no plugin, and was taken whenever it was
        # listed first. Then the app window over any guest: the guest has no
        # plugin on it.
        for t in pages:
            if (t.get("url") or "").startswith("app://") and "/index.html" in t.get("url", ""):
                return t["webSocketDebuggerUrl"]
        for t in pages:
            if "obsidian" in (t.get("url") or "").lower() or \
               (t.get("url") or "").startswith("app://"):
                return t["webSocketDebuggerUrl"]
        return pages[0]["webSocketDebuggerUrl"]

    # **One session, held open and WOKEN, rather than a socket per call.**
    #
    # `Emulation.setFocusEmulationEnabled` lasts exactly as long as the CDP
    # session that set it, so a connect-evaluate-close cycle can never be
    # awake: the wake dies with the socket that asked for it. That is not a
    # detail. A minimised Obsidian throttles `requestAnimationFrame` to
    # roughly one tick every two seconds, and every liveness reading taken
    # through it is a reading of the window manager instead of the plugin.
    # Measured on the same pane seconds apart: 0 rendered frames in 2 s while
    # hidden, 407 once woken. The first number was very nearly filed as a
    # dead render loop.
    #
    # So the session is opened once, woken once, and reused. Geometry is
    # unaffected either way -- node positions are real in a hidden window --
    # but anything with time in it is not, and nothing in the tool surface
    # should require the caller to know which is which.

    def _session(self):
        if self._ws is not None:
            return self._ws
        from websocket import create_connection      # websocket-client

        # **No Origin header.** Chrome refuses a CDP websocket that carries
        # one -- "Rejected an incoming WebSocket connection", a 403 at the
        # handshake -- and websocket-client sends one by default. Node's
        # WebSocket does not, which is why cdp.mjs never met this.
        self._ws = create_connection(self._page_target(), timeout=self.timeout,
                                     suppress_origin=True)
        self._next_id = 0
        self.wake()
        return self._ws

    def _cdp(self, method: str, params: Optional[Dict] = None) -> Dict:
        ws = self._session()
        self._next_id += 1
        mine = self._next_id
        ws.send(json.dumps({"id": mine, "method": method,
                            "params": params or {}}))
        while True:
            msg = json.loads(ws.recv())
            if msg.get("id") == mine:
                return msg.get("result", {})
            # Anything else is an event on this session, not our reply.

    def wake(self) -> Dict:
        """Make the renderer behave as a focused, visible window.

        Reported rather than assumed: the caller gets `hidden` and `focused`
        either side, so a measurement can say whether it was taken through a
        window that was actually running.
        """
        def look():
            try:
                return json.loads(self._raw_eval(
                    "JSON.stringify({hidden: document.hidden,"
                    " visibility: document.visibilityState,"
                    " focused: document.hasFocus()})"))
            except Exception:                       # noqa: BLE001
                return {}
        before = look()
        notes = []
        for method, params in (("Page.enable", None),
                               ("Emulation.setFocusEmulationEnabled",
                                {"enabled": True}),
                               ("Page.setWebLifecycleState",
                                {"state": "active"})):
            try:
                self._cdp(method, params)
            except Exception as exc:                # noqa: BLE001
                notes.append("%s: %s" % (method, str(exc)[:60]))
        after = look()
        out = {"before": before, "after": after,
               "awake": bool(after) and not after.get("hidden", True)}
        if notes:
            out["notes"] = notes
        return out

    def close(self) -> None:
        if self._ws is not None:
            try:
                self._ws.close()
            finally:
                self._ws = None

    def _raw_eval(self, expression: str) -> object:
        res = self._cdp("Runtime.evaluate", {
            "expression": expression,
            "awaitPromise": True,
            "returnByValue": True,
            # The pane is often not the focused window, and an occluded
            # renderer does not run timers the same way.
            "userGesture": True,
        })
        if "exceptionDetails" in res:
            raise RuntimeError("page threw: %s" % res["exceptionDetails"]
                               .get("text", "?"))
        return res.get("result", {}).get("value")

    def evaluate(self, expression: str, timeout: Optional[float] = None) -> object:
        """Run an expression in the renderer and return its value.

        Retried once on a dead socket, because Obsidian reloading the plugin
        or the window is ordinary rather than exceptional here, and a tool
        that fails on the reload it just asked for is not usable.
        """
        try:
            return self._raw_eval(expression)
        except Exception:                           # noqa: BLE001
            self.close()
            return self._raw_eval(expression)

    def json_eval(self, expression: str) -> object:
        """`evaluate`, for an expression that returns a JSON string."""
        got = self.evaluate(expression)
        return json.loads(got) if isinstance(got, str) else got

    # -- the tools -----------------------------------------------------------

    def ui(self) -> Dict:
        """The interface as a data structure, in screen pixels."""
        got = self.evaluate(
            "JSON.stringify(window.__vertiscope ? window.__vertiscope.ui() "
            ": {error: 'harness not installed; reload the plugin'})")
        return json.loads(got) if isinstance(got, str) else {"error": "no value"}

    def act(self, gesture: str, arg: object = None, full: bool = False) -> Dict:
        """Do a thing, and report the UI either side plus the backend work.

        This is the whole point of the live server: a chained interaction --
        open a pane, navigate, scan, watch the trie fill -- used to be a
        dozen round trips and a guess about ordering.
        """
        expr = (
            "window.__vertiscope.act(%s, %s, {full: %s}).then(JSON.stringify)"
            % (json.dumps(gesture), json.dumps(arg),
               "true" if full else "false"))
        got = self.evaluate(expr)
        return json.loads(got) if isinstance(got, str) else {"error": "no value"}


    # -- probes ---------------------------------------------------------------
    #
    # **Why these live here and not in a script.** Every one of them was
    # written three or four times as a throwaway during one session, each
    # time slightly differently, and two of those versions were wrong in
    # ways that took a live measurement to catch: a screen-space overlap
    # count that conflated depth, and a "kids" query that counted an
    # inter-page link as an unfold branch. A probe rewritten per question
    # has no history of having been wrong, which is exactly what
    # `CLAUDE.md` says a fresh metric lacks.

    _GRAPH_NESTING = r"""
    (() => {
      const l = app.workspace.getLeavesOfType('vertiscope-graph-view')[0];
      const v = l && l.view; const p = v && (v.projector || v);
      const g = p && p.graph;
      if (!g) return JSON.stringify({error: 'no projector'});
      const d = g.graphData(), rel = g.nodeRelSize();
      const by = new Map(d.nodes.map(n => [n.id, n]));
      const D = (a, b) => Math.hypot(a.x-b.x, a.y-b.y, a.z-b.z);
      const R = n => Math.cbrt(Math.max(n.val ?? 1, 1e-9)) * rel;
      const q = (a, t) => { a = a.slice().sort((x,y)=>x-y);
        return a.length ? +a[Math.floor(t*(a.length-1))].toFixed(2) : null; };
      const pages = d.nodes.filter(n => n.level === 'page');
      const sizes = {};
      for (const n of d.nodes) {
        const k = n.unfolded ? 'page/unfolded' : (n.level || '?');
        (sizes[k] = sizes[k] || []).push(R(n));
      }
      for (const k of Object.keys(sizes))
        sizes[k] = {n: sizes[k].length, radius_p50: q(sizes[k], .5),
                    radius_max: q(sizes[k], 1)};
      const groups = [];
      for (const hub of d.nodes.filter(n => n.unfolded)) {
        // **Only the branches, not every out-edge.** An inter-page link
        // leaves the same hub, and counting it as a branch once read as a
        // 157-unit spill that was not one.
        const kids = d.links
          .filter(e => ((e.source && e.source.id) || e.source) === hub.id)
          .map(e => by.get((e.target && e.target.id) || e.target))
          .filter(k => k && k.level !== 'page' && k.url === hub.url);
        if (!kids.length) continue;
        let gap = Infinity;
        for (const o of pages) { if (o === hub) continue;
          const t = D(o, hub); if (t < gap) gap = t; }
        // **From the ANCHOR, which is what containment is defined against.**
        // The hub is an ordinary node and the collider moves it; measuring
        // from it reported a 341-unit spill while every branch was inside
        // its territory.
        const at = kids[0].anchorPos;
        const from = at ? {x: at[0], y: at[1], z: at[2]} : hub;
        const room = kids[0].room || null;
        const reach = Math.max.apply(null, kids.map(k => D(k, from)));
        const fromHub = Math.max.apply(null, kids.map(k => D(k, hub)));
        groups.push({page: hub.url, hub_radius: +R(hub).toFixed(2),
          branches: kids.length, branch_radius_p50: q(kids.map(R), .5),
          room: room ? +room.toFixed(1) : null,
          reach_from_anchor: +reach.toFixed(1),
          reach_from_hub: +fromHub.toFixed(1),
          hub_drift_from_anchor: at ? +D(hub, from).toFixed(1) : null,
          gap_to_nearest_page: +gap.toFixed(1),
          reach_over_gap: +(reach / gap).toFixed(3),
          outside_their_room: room
            ? kids.filter(k => D(k, from) > room * 1.05).length : null,
          bigger_than_container: kids.filter(k => R(k) > R(hub)).length,
          past_halfway: kids.filter(k => D(k, from) > gap * 0.5).length});
      }
      const nn = [];
      for (const a of pages) { let m = Infinity;
        for (const b of pages) { if (a === b) continue;
          const t = D(a, b); if (t < m) m = t; } nn.push(m); }
      // World-space overlap, at the pane's OWN collider radius. A
      // screen-space count conflates depth and reported 84 where this
      // reports 0.
      const c = g.d3Force('collide'); const rf = c && c.radius();
      let over = 0, pairs = 0;
      if (rf) { const N = d.nodes, RR = N.map(rf);
        for (let i = 0; i < N.length; i++) for (let j = i+1; j < N.length; j++) {
          pairs++; if (D(N[i], N[j]) < RR[i] + RR[j]) over++; } }
      const seen = new Set();
      for (const e of d.links) { seen.add((e.source&&e.source.id)||e.source);
        seen.add((e.target&&e.target.id)||e.target); }
      return JSON.stringify({
        nodes: d.nodes.length, links: d.links.length,
        opened: d.nodes.filter(n => n.unfolded).length,
        sizes,
        page_spacing_p10: q(nn, .1), page_spacing_p50: q(nn, .5),
        page_spacing_p90: q(nn, .9),
        world_overlapping_pairs: over, pairs_tested: pairs,
        orphan_non_page_nodes:
          d.nodes.filter(n => n.level !== 'page' && !seen.has(n.id)).length,
        groups});
    })()
    """

    def graph_probe(self) -> Dict:
        """Whether the two layers NEST: sizes, reach, and the room available.

        Answers in one call the four questions the projector kept failing
        silently: is a branch smaller than the page it came out of, does an
        unfolding stay inside that page's own territory, do any nodes
        genuinely interpenetrate in world space, and is anything drawn with
        no edge at all.
        """
        got = self.json_eval(self._GRAPH_NESTING)
        if isinstance(got, dict) and "groups" in got:
            groups = got["groups"]
            got["verdict"] = {
                "pages_opened": len(groups),
                "branches_bigger_than_their_page":
                    sum(g["bigger_than_container"] for g in groups),
                "branches_outside_their_room":
                    sum(g["outside_their_room"] or 0 for g in groups),
                "unfoldings_spilling_past_halfway":
                    sum(1 for g in groups if g["past_halfway"]),
                "worst_reach_over_gap":
                    max((g["reach_over_gap"] for g in groups), default=None),
                "worst_hub_drift":
                    max((g["hub_drift_from_anchor"] or 0 for g in groups),
                        default=None),
                "nests": bool(groups) and all(
                    not g["bigger_than_container"] and not g["past_halfway"]
                    and not (g["outside_their_room"] or 0)
                    for g in groups),
            }
        return got

    def key_coverage(self, sample: int = 40) -> Dict:
        """Do the lines a reader sees carry their address (`D-26`)?

        Per PAGE, because the failure is all-or-nothing per page and a
        corpus ratio hides it. The corpus-wide `addresses / anchors` ratio
        is NOT this question, and reading it as one is how `D-26` was first
        filed at 11.1% when the real figure was 60.1%.
        """
        from urllib.parse import quote
        health = self.get("/health")
        by_url = {}
        for query in ("the", "search", "price", "install", "reference",
                      "data", "image", "login", "news", "home"):
            for hit in (self.get("/search?q=%s&k=60"
                                 % quote(query)).get("hits") or []):
                cid, url = hit.get("cid"), hit.get("url")
                if cid and url and len(by_url.setdefault(url, [])) < 3:
                    by_url[url].append(cid)
            if len(by_url) >= sample:
                break
        rows = []
        for url, cids in list(by_url.items())[:sample]:
            lines = keyed = controls = 0
            for cid in cids:
                try:
                    payload = self.get("/chunk/%s" % quote(str(cid)))
                except Exception:                   # noqa: BLE001
                    continue
                for line in (payload.get("lines") or []):
                    lines += 1
                    if line.get("key"):
                        keyed += 1
                    if line.get("control"):
                        controls += 1
            if lines:
                rows.append({"url": url, "lines": lines, "keyed": keyed,
                             "controls": controls,
                             "pct": round(100.0 * keyed / lines, 1)})
        rows.sort(key=lambda r: r["pct"])
        total_l = sum(r["lines"] for r in rows)
        total_k = sum(r["keyed"] for r in rows)
        return {
            "pages_sampled": len(rows),
            "fully_keyed": sum(1 for r in rows if r["pct"] >= 99.9),
            "partly_keyed": sum(1 for r in rows if 0.1 < r["pct"] < 99.9),
            "zero_keyed": sum(1 for r in rows if r["pct"] <= 0.1),
            "lines": total_l, "keyed": total_k,
            "pct": round(100.0 * total_k / max(total_l, 1), 1),
            "controls_found": sum(r["controls"] for r in rows),
            "store": {k: health.get(k) for k in
                      ("addresses", "anchors", "addresses_blank_key",
                       "anchors_blank_key", "unreadable_addresses")},
            "worst": rows[:8],
        }


    def recover(self, settle: float = 12.0) -> Dict:
        """Bring back a window that stopped answering (2026-09-27).

        During a hard-page run the Obsidian renderer stopped answering even
        the debugger -- idle CPU, blocked -- and the browser cell went blank.
        A RELOAD is handled on the browser side, so it works on a page that
        cannot answer: through the browser-level endpoint, attach to the page
        target and `Page.reload`. Same as Ctrl+R; the vault is untouched."""
        import json as _json
        import time as _t
        import urllib.request as _u
        import websocket as _ws
        ver = _json.load(_u.urlopen(self.cdp + "/json/version", timeout=10))
        ws = _ws.create_connection(ver["webSocketDebuggerUrl"], timeout=15, suppress_origin=True)
        try:
            ws.send(_json.dumps({"id": 1, "method": "Target.getTargets"}))
            infos = _json.loads(ws.recv())["result"]["targetInfos"]
            page = [t for t in infos if t.get("type") == "page"][0]["targetId"]
            ws.send(_json.dumps({"id": 2, "method": "Target.attachToTarget",
                                 "params": {"targetId": page, "flatten": True}}))
            sid = None
            while sid is None:
                m = _json.loads(ws.recv())
                if m.get("id") == 2:
                    sid = m["result"]["sessionId"]
            ws.send(_json.dumps({"id": 3, "sessionId": sid, "method": "Page.reload", "params": {}}))
        finally:
            ws.close()
        self.close()
        _t.sleep(settle)
        return {"reloaded": True, "alive": self.evaluate("1+1", timeout=15) == 2}

    def reload_plugin(self, settle: float = 6.0, wait: bool = True, force: bool = False) -> Dict:
        """Reload the plugin, WITHOUT going through the harness.

        The harness is what a reload replaces, so asking it to perform one is
        circular: a build that adds a gesture cannot be loaded by that
        gesture, and the first run of this returned "unknown gesture:
        reload" for exactly that reason while every check below it scored the
        previous build. `CLAUDE.md`'s rule is that a probe scores the
        instrument that is LOADED; this is the one step that cannot assume
        the instrument is the current one.
        """
        import time
        # Reader-idle gate: a reload under the reader's hands tears their
        # panes down mid-gesture. `force` is for a probe the reader asked for.
        if not force:
            idle = self.evaluate(
                "(()=>{try{return window.__vertiscope.reader.idleMs();}catch(e){return null;}})()")
            if isinstance(idle, (int, float)) and idle < 60000:
                return {"reloaded": False, "refused": "reader active %.0f s ago" % (idle / 1000),
                        "hint": "pass force to reload anyway"}
        # The reload is not the reader: it rebuilds the views, which stamps
        # the reader clock, and the next idle-gated probe then aborted on it
        # (2026-10-17). The stamp is put back afterwards.
        stamp = self.evaluate("window.__vertiscopeReaderAt || 0")
        before = self.evaluate(
            "(()=>{const p=app.plugins.getPlugin('vertiscope-bridge');"
            " return p && p.manifest ? p.manifest.version : null;})()")
        self.evaluate(
            "(async()=>{await app.plugins.disablePlugin('vertiscope-bridge'); return 1;})()")
        # Enable is FIRED, not awaited: awaiting it over CDP hung for the
        # whole socket timeout more than once and left a half-loaded
        # instance behind (2026-10-12). Poll a flag it sets instead.
        self.evaluate(
            "(()=>{window.__dvReload='start'; app.plugins.enablePlugin('vertiscope-bridge')"
            ".then(()=>{window.__dvReload='done'},(e)=>{window.__dvReload='err '+e}); return 1;})()")
        enabled = "start"
        deadline = time.time() + 120
        while time.time() < deadline and enabled == "start":
            time.sleep(1.0)
            enabled = self.evaluate("String(window.__dvReload)")
        # Rebuild each view IN THE LEAF IT HAS. Disabling detaches the old
        # view, and a leaf left that way keeps running the OLD instance's
        # code or sits empty; never blank it and open another, which left
        # 13 empty leaves splitting the window (2026-10-12).
        views = self.evaluate(
            "(async()=>{const out={}; const race=(pr)=>Promise.race([pr,new Promise((r)=>setTimeout(r,15000))]);"
            " for (const [t,k] of [['vertiscope-graph-view','graph'],['vertiscope-browser-view','browser']]) {"
            "  const ls=app.workspace.getLeavesOfType(t);"
            "  for (const l of ls) await race(l.setViewState({type:t, active:false}));"
            "  if (!app.workspace.getLeavesOfType(t).length) await race(window.__vertiscope.act('open',k));"
            "  out[k]=app.workspace.getLeavesOfType(t).length; }"
            " return JSON.stringify(out);})()")
        time.sleep(settle)
        gestures = self.evaluate(
            "(()=>{try{return !!(window.__vertiscope && window.__vertiscope.act);}"
            "catch(e){return false;}})()")
        # `wait=False` for a store that has nothing to draw yet: a fresh
        # test workspace, before it is seeded, would sit out the whole timeout.
        drew = self.wait_for_projector() if wait else None
        try:
            views = json.loads(views) if isinstance(views, str) else views
        except ValueError:
            pass
        self.evaluate("(()=>{window.__vertiscopeReaderAt = %s; return 1})()" % json.dumps(stamp))
        return {"version_before": before, "enable": enabled, "views": views,
                "harness_installed": bool(gestures), "settled_s": settle, "projector": drew}

    def wait_for_projector(self, timeout: float = 90.0) -> Dict:
        """Wait until the pane has actually DRAWN something.

        **`enablePlugin` returning is not the pane being ready**, and the
        gap is not small: the view has to be constructed, ask the sidecar
        for a layout, and let the renderer put nodes in the scene. Checks
        run in that window see `ui().graph` missing and report "no
        projector", which reads exactly like a dead plugin -- seven
        requirements failed that way on one run, with the same pane showing
        815 nodes by the time the last check ran.

        Opens the pane if it is not open, because a reload can leave it
        closed and a harness that reports "not open" for something it could
        have opened is refusing to do its job.
        """
        import time
        deadline = time.time() + timeout
        opened = False
        last = {}
        while time.time() < deadline:
            try:
                got = self.ui().get("graph") or {}
            except Exception:                       # noqa: BLE001
                got = {}
            last = got
            if got.get("nodes"):
                return {"ready": True, "nodes": got.get("nodes"),
                        "waited_s": round(timeout - (deadline - time.time()), 1)}
            if not opened:
                opened = True
                try:
                    self.act("open", "graph")
                except Exception:                   # noqa: BLE001
                    pass
            time.sleep(2.0)
        return {"ready": False, "last": last,
                "why": "the projector drew nothing within %gs" % timeout}

    # -- requirement verdicts -------------------------------------------------

    def verify(self, only=None, *, wait: bool = True, timeout_s: float = 1200,
               reload: bool = True, store: str = "working",
               fresh: bool = False) -> Dict:
        """Run the live checks INSIDE the plugin and read them back (`G-75`).

        Hardware in the loop: the checks are `checks/live.mjs`, the same list
        the terminal client runs, executed by the plugin in its own window
        (`window.__vertiscope.verify`). This only reloads the plugin -- from
        outside, so the run scores the code on disk -- starts the run, and
        polls its state; progress and failures also show in the browser
        cell's corner box while it runs. `wait=False` returns once started.

        `fresh=True` asks the PLUGIN for a fresh-store run (`G-87`): the app
        starts a sidecar on an empty store, fills it by browsing, runs the
        checks and switches itself back -- all of it inside the app, shown
        in the corner box. Nothing here orchestrates it; this starts it and
        reads it.
        """
        import time as _time
        if reload:
            got = self.reload_plugin()
            if got.get("refused"):
                # Running anyway would score the build that was loaded
                # before, which is the trap this reload exists to close.
                return {"started": None, "refused": got["refused"]}
            _time.sleep(3)
        call = ("v.startFresh(%s)" % json.dumps(list(only or [])) if fresh
                else "v.start(%s, %s)" % (json.dumps(list(only or [])), json.dumps(store)))
        started = self.json_eval(
            "JSON.stringify((() => { const v = window.__vertiscope && window.__vertiscope.verify;"
            " if (!v) return {error: 'this plugin build has no in-app verifier'};"
            " %s; const s = v.state();"
            " return {run: s.run, total: s.total}; })())" % call)
        if not started or started.get("error") or not wait:
            return {"started": started}
        deadline = _time.time() + timeout_s
        state = {}
        while _time.time() < deadline:
            _time.sleep(3)
            state = self.json_eval("JSON.stringify(window.__vertiscope.verify.state())") or {}
            if not state.get("running"):
                break
        results = state.get("results") or []
        # And what the APP shows for the run: the verdicts as the corner box
        # draws them. A run the box does not show, or shows differently, is
        # a finding about the box.
        try:
            observed = self.observe_checks()
            # Read, then put the corner box back as the reader had it: the run
            # opened it to press its button, and left open it covers the page.
            try:
                self.act("pipebox", "restore")
            except Exception:                           # noqa: BLE001
                pass
        except Exception as err:                    # noqa: BLE001
            observed = {"error": str(err)[:200]}
        # Every finished run reaches the record of what has been SEEN working,
        # with the store it read (`confirmations`); a run still going does not.
        if results and not state.get("running"):
            from .confirmations import record
            record(results, store=state.get("label") or store,
                   runner="in-app verify")
        return {
            "run": state.get("run"), "running": bool(state.get("running")),
            "passed": sum(1 for r in results if r.get("pass")),
            "total": state.get("total"), "stopped_because": state.get("stoppedBecause"),
            "observed_in_app": observed,
            "label": state.get("label"), "seed": state.get("seed"),
            "teardown": state.get("teardown"),
            "results": results,
        }

    def observe_checks(self) -> Dict:
        """The run as the APP SHOWS it: the corner box's check list, read off
        the rendered box, not off the verifier's state object.

        2026-09-26: *"you observe the results within the app itself"*. The
        box is opened first (a collapsed box renders nothing to read), and
        what comes back is what a person looking at it would see -- summary
        line, one row per verdict, and each failure's evidence as drawn.
        """
        # Opened to be read -- remembered, so `restore` closes it again.
        self.evaluate("(()=>{const l=app.workspace.getLeavesOfType('vertiscope-browser-view')[0];"
                      "const pb=l&&l.view&&l.view.pipebox;if(pb&&!pb.expanded)pb.openedForChecks=true;return 1})()")
        self.act("pipebox", "open")
        import time as _time
        _time.sleep(1.2)          # the box redraws on its own tick
        return self.json_eval(r"""JSON.stringify((() => {
          const l = app.workspace.getLeavesOfType('vertiscope-browser-view')[0];
          const box = l && l.view && l.view.pipebox;
          if (!box) return {error: 'no corner box'};
          const root = box.wrap;
          const heads = [...root.querySelectorAll('.vertiscope-pipebox-h')];
          const h = heads.find(e => /Checks, run in this app/.test(e.textContent));
          const summary = h && h.nextElementSibling ? h.nextElementSibling.textContent.trim() : null;
          const rows = [...root.querySelectorAll('.vertiscope-pipebox-check')].map(e => ({
            id: e.dataset.id || null, pass: e.dataset.pass === '1',
            text: e.textContent.trim().slice(0, 400)}));
          const r = root.getBoundingClientRect();
          return {expanded: !!box.expanded, summary, rows,
                  box_px: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)],
                  visible: r.width > 0 && r.height > 0};
        })())""") or {}

    def screenshot(self, path: str = "") -> Dict:
        """The Obsidian window as a PNG, for a human-eye check of what the
        app shows (the corner box, the side panel, the graph)."""
        import base64
        import time as _time
        got = self._cdp("Page.captureScreenshot", {"format": "png"})
        data = got.get("data")
        if not data:
            return {"error": "no image", "got": list(got)}
        path = path or str(Path("build_analytics") / (
            "app_%s.png" % _time.strftime("%Y%m%d_%H%M%S")))
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        Path(path).write_bytes(base64.b64decode(data))
        return {"path": str(Path(path).resolve())}

    def verify_state(self) -> Dict:
        """The in-app run's state right now: progress, and results so far."""
        return self.json_eval("JSON.stringify(window.__vertiscope.verify.state())") or {}

    def pipeline_profile(self, url: str = "", seconds: float = 25.0,
                         scrolls: int = 6) -> Dict:
        """Drive live capture on a page and time every stage to the pixels.

        **A real workload, not a synthetic one.** It navigates the browser
        cell, lets the live drain loop run, and scrolls the page so the
        MutationObserver has something to fold -- which is what a reader
        does. The pane records each drain in its own clock and closes it when
        a listener sees the node drawn; the sidecar records its phases in its
        clock. This reads both back and joins them on the trace id.

        **Both halves are reset first**, so the numbers describe this run and
        not whatever the session did before it.

        Returns per-stage percentiles, the outcome of every drain, the
        sidecar's own view including the background embedder it never
        reported before, and the consistency checks that decide whether the
        numbers can be trusted at all.
        """
        import time
        self.wake()
        self.evaluate("window.__vertiscope && window.__vertiscope.profile.reset()")
        try:
            self.get("/profile?reset=1")
        except Exception:                           # noqa: BLE001
            pass

        if url:
            self.act("navigate", url)
        # Let the first drain land, then give the observer work to do.
        deadline = time.time() + seconds
        step = max(1.0, seconds / max(scrolls + 1, 1))
        time.sleep(min(step, 4.0))
        for i in range(scrolls):
            if time.time() > deadline:
                break
            try:
                self.evaluate(
                    "(async()=>{const l=app.workspace.getLeavesOfType("
                    "'vertiscope-browser-view')[0];const wv=l&&l.view&&l.view.webview;"
                    "if(!wv)return 0;return await wv.executeJavaScript("
                    "'window.scrollBy(0, Math.round(window.innerHeight*0.9)); "
                    "window.scrollY');})()")
            except Exception:                       # noqa: BLE001
                pass
            time.sleep(step)
        # Let the in-flight listeners close; each waits up to 8s.
        time.sleep(max(0.0, min(9.0, deadline - time.time() + 9.0)))

        pane = self.json_eval(
            "JSON.stringify({summary: window.__vertiscope.profile.summary(),"
            " traces: window.__vertiscope.profile.traces(60)})") or {}
        try:
            side = self.get("/profile")
        except Exception as exc:                    # noqa: BLE001
            side = {"error": str(exc)[:120]}

        def pct(values, q):
            v = sorted(x for x in values if isinstance(x, (int, float)))
            return v[min(len(v) - 1, int(q * (len(v) - 1)))] if v else None

        def ring(name, field):
            rows = side.get(name) or []
            vals = [r.get(field) for r in rows]
            return {"n": len(rows), "p50": pct(vals, .5), "p90": pct(vals, .9),
                    "max": pct(vals, 1.0)}

        traces = pane.get("traces") or []
        # **Consistency.** A sidecar total larger than the round trip that
        # contained it is impossible; if it happens the clocks or the join
        # are wrong and nothing below should be believed.
        inconsistent = [t["id"] for t in traces
                        if t.get("facts", {}).get("clock_inconsistent")]
        # Every traced drain must end in a named outcome. One left open means
        # a path through the code that the profiler does not close.
        unnamed = [t["id"] for t in traces if not t.get("facts", {}).get("outcome")]

        return {
            "page": url or "(current)",
            "pane": pane.get("summary"),
            "sidecar": {
                "captures": ring("capture", "total"),
                "capture_lock_wait": ring("capture", "lock_wait"),
                "embed_batches": ring("embed", "ms"),
                "embed_lock_wait": ring("embed", "lock_wait_ms"),
                "embedded_per_batch": ring("embed", "embedded"),
                "aggregate": ring("aggregate", "ms"),
            },
            "checks": {
                "traces": len(traces),
                "clock_inconsistent": inconsistent,
                "open_outcomes": unnamed,
                "trusted": not inconsistent and not unnamed and bool(traces),
            },
            "sample": traces[-3:],
        }

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
                # Before the layout is ready every pane reads "not open",
                # which looked like a broken plugin straight after a launch
                # (2026-10-17); this says which it is.
                "layout_ready": self.evaluate("!!(app.workspace && app.workspace.layoutReady)"),
                "panes": ui.get("panes"),
            }
        except Exception as exc:                    # noqa: BLE001
            out["app"] = {"error": str(exc)[:160]}
        return out
