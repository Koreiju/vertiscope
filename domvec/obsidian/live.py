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
        # Prefer the app window over any guest: the guest has no plugin on it.
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
      const l = app.workspace.getLeavesOfType('domvec-graph-view')[0];
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


    def reload_plugin(self, settle: float = 6.0) -> Dict:
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
        before = self.evaluate(
            "(()=>{const p=app.plugins.getPlugin('domvec-bridge');"
            " return p && p.manifest ? p.manifest.version : null;})()")
        self.evaluate(
            "(async()=>{await app.plugins.disablePlugin('domvec-bridge');"
            " await app.plugins.enablePlugin('domvec-bridge');"
            " return 1;})()")
        time.sleep(settle)
        gestures = self.evaluate(
            "(()=>{try{return !!(window.__domvec && window.__domvec.act);}"
            "catch(e){return false;}})()")
        drew = self.wait_for_projector()
        return {"version_before": before, "harness_installed": bool(gestures),
                "settled_s": settle, "projector": drew}

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

    def confirm(self, only=None) -> Dict:
        """Every observable requirement this harness can answer, with evidence.

        **Why the evidence travels with the verdict.** A bare PASS is the
        thing this project has been burned by most: three checks passed --
        "nodes are discernible", "nodes never overlap", "every node is on
        screen" -- while the pane showed a clump with a fifth of it off the
        canvas, because each one asked a JavaScript property rather than the
        picture. So every row below returns the numbers it decided on, and a
        reader can disagree with the threshold without rerunning anything.

        **The plugin is reloaded first.** A probe scores the instrument that
        is LOADED. One here passed with its own target defect planted,
        returning numbers identical to the clean run, because it reopened the
        pane and never reloaded the code.
        """
        checks = [
            ("G-53", "the projector draws PAGES by default, not chunks",
             self._c_pages_by_default),
            ("G-54", "unfolding unravels one patricia step, inside its page",
             self._c_unfold),
            ("G-6", "patricia links are drawn, with endpoints that resolve",
             self._c_links),
            ("G-4", "nodes are discernible, not a clump",
             self._c_spread),
            ("G-5", "every node is on screen at the default camera",
             self._c_on_screen),
            ("G-21", "nodes do not overlap, in world space",
             self._c_overlap),
            ("G-20", "relaxation is SEEDED from the fit, not replacing it",
             self._c_seeded),
            ("D-27", "the two layers nest: contents inside their container",
             self._c_nesting),
            ("G-39", "an address on the page resolves to the chunk that draws it",
             self._c_resolve),
            ("D-26", "the lines a reader sees carry their address",
             self._c_keys),
            ("G-40", "clicking a node takes the browser to that chunk",
             self._c_click),
            ("G-34", "live capture lands in the picture already on screen",
             self._c_absorb),
            ("G-3", "retrieval is stored and reachable from the pane",
             self._c_retrieve),
            ("G-15", "media is present in the projector, not only the panels",
             self._c_media),
        ]
        wanted = set(only or [])
        if wanted:
            checks = [c for c in checks if c[0] in wanted]
        out = {"woke": self.wake()}
        if not wanted:
            # Only on a full run: a reload costs ~10s and a caller asking for
            # one row usually wants it against what is already running.
            out["reloaded"] = self.reload_plugin()
        # **And the sidecar has to be answering**, or half of these score the
        # backend's absence as the plugin's failure. It segfaulted mid-run
        # once and the report read as ten broken features.
        try:
            out["sidecar"] = self.get("/health").get("ok", False)
        except Exception as exc:                    # noqa: BLE001
            return dict(out, sidecar=False, checks=[], **{
                "pass": 0, "fail": 0, "error": 0, "all_pass": False,
                "why": "the sidecar is not answering (%s); every backend "
                       "check would fail for that reason and a run that "
                       "reports it as broken features is worse than no run"
                       % str(exc)[:80]})
        rows = []
        for rid, what, fn in checks:
            try:
                verdict, evidence = fn()
            except Exception as exc:                # noqa: BLE001
                verdict, evidence = "ERROR", {"threw": str(exc)[:200]}
            rows.append({"id": rid, "what": what,
                         "verdict": verdict, "evidence": evidence})
        out["checks"] = rows
        out["pass"] = sum(1 for r in rows if r["verdict"] == "PASS")
        out["fail"] = sum(1 for r in rows if r["verdict"] == "FAIL")
        out["error"] = sum(1 for r in rows if r["verdict"] == "ERROR")
        out["all_pass"] = out["fail"] == 0 and out["error"] == 0
        return out

    # Each returns (verdict, evidence). A threshold that is argued about
    # belongs in the evidence, not hidden inside a boolean.

    def _graph(self) -> Dict:
        """The projector's state, waiting for it rather than catching it mid-draw.

        A check that reads the pane while it is still building reports the
        plugin as broken. Waiting once here is cheaper than every check
        learning to retry, and it cannot mask a real failure: the wait has a
        deadline and says so.
        """
        got = self.ui().get("graph") or {}
        if not got.get("nodes"):
            self.wait_for_projector()
            got = self.ui().get("graph") or {}
        if not got or got.get("error"):
            raise RuntimeError(got.get("error") or "projector not open")
        return got

    def _c_pages_by_default(self):
        g = self._graph()
        probe = self.graph_probe()
        sizes = probe.get("sizes") or {}
        pages = (sizes.get("page") or {}).get("n", 0)
        chunks = (sizes.get("chunk") or {}).get("n", 0)
        return ("PASS" if pages > chunks else "FAIL",
                {"page_nodes": pages, "chunk_nodes": chunks,
                 "status_line": g.get("status")})

    def _c_unfold(self):
        got = self.act("unfold")
        r = got.get("result") or {}
        if r.get("error"):
            return "FAIL", r
        ok = bool(r.get("branches")) and bool(r.get("stayed_inside"))
        return ("PASS" if ok else "FAIL",
                {k: r.get(k) for k in
                 ("page", "branches", "room", "reach_from_anchor",
                  "reach_from_hub", "gap_to_nearest_page", "stayed_inside",
                  "nodes_before", "nodes_after")})

    def _c_links(self):
        g = self._graph()                           # waits for the pane
        links = g.get("links") or 0
        # An endpoint that never resolved leaves a link with a string for a
        # source, and the renderer silently draws nothing.
        drawn = self.json_eval(
            "JSON.stringify((()=>{const v=app.workspace"
            ".getLeavesOfType('domvec-graph-view')[0].view;"
            "const g=(v.projector||v).graph;const d=g.graphData();"
            "return {links:d.links.length, resolved:d.links.filter("
            "l=>l.source&&typeof l.source==='object'&&l.target&&"
            "typeof l.target==='object').length};})())")
        return ("PASS" if links and drawn.get("resolved") == links else "FAIL",
                drawn)

    def _c_spread(self):
        g = self._graph()
        spread = g.get("spread_pct")
        return ("PASS" if spread and spread >= 20 else "FAIL",
                {"spread_pct": spread, "threshold": 20,
                 "gap_px_p50": g.get("gap_px_p50"),
                 "radius_px_p50": g.get("radius_px_p50")})

    def _c_on_screen(self):
        g = self._graph()
        off = g.get("off_screen")
        return ("PASS" if off == 0 else "FAIL",
                {"nodes": g.get("nodes"), "on_screen": g.get("on_screen"),
                 "off_screen": off, "behind_camera": g.get("behind_camera"),
                 "in_frustum": g.get("in_frustum")})

    def _c_overlap(self):
        probe = self.graph_probe()
        over = probe.get("world_overlapping_pairs")
        return ("PASS" if over == 0 else "FAIL",
                {"world_overlapping_pairs": over,
                 "pairs_tested": probe.get("pairs_tested"),
                 "note": "world space at the pane's own collider radius; "
                         "the screen-space count conflates depth"})

    def _c_seeded(self):
        g = self._graph()
        drift = g.get("fit_drift_p50")
        return ("PASS" if drift is not None and drift <= 5 else "FAIL",
                {"fit_drift_p50": drift, "fit_drift_max": g.get("fit_drift_max"),
                 "threshold": 5,
                 "note": "the fit is the starting point; collision may move a "
                         "node that overlaps, but the median must stay put"})

    def _c_nesting(self):
        probe = self.graph_probe()
        v = probe.get("verdict") or {}
        if not v.get("pages_opened"):
            self.act("unfold")
            v = (self.graph_probe().get("verdict") or {})
        return ("PASS" if v.get("nests") else "FAIL", v)

    def _c_resolve(self):
        from urllib.parse import quote
        # Any page with chunks, and an xpath a step BELOW a chunk root --
        # which is what a cursor actually lands on.
        hits = (self.get("/search?q=the&k=5").get("hits") or [])
        if not hits:
            return "ERROR", {"why": "no chunks to resolve against"}
        url = hits[0].get("url")
        lines = (self.get("/chunk/%s" % quote(str(hits[0]["cid"])))
                 .get("lines") or [])
        keyed = [ln for ln in lines if ln.get("key")]
        if not keyed:
            return "FAIL", {"url": url, "lines": len(lines), "keyed": 0,
                            "why": "no line carries an address to resolve"}
        # **Parse the key, do not split it.** A key is escaped
        # (`%7C` for a pipe, `%25` for a percent) and its xpath may name a
        # text node, which is not an element anything can be resolved from.
        # Handing the raw component to `/resolve` 404s, and reading that as
        # "no chunk draws it" blames the trie for a caller's string handling.
        from ..address import ContentAddress
        xpath = ContentAddress.parse(keyed[0]["key"]).xpath
        xpath = xpath.split("/text()")[0]
        try:
            got = self.get("/resolve?url=%s&xpath=%s"
                           % (quote(url, safe=""), quote(xpath, safe="")))
        except Exception as exc:                    # noqa: BLE001
            return "FAIL", {"url": url, "xpath": xpath,
                            "why": str(exc)[:120]}
        back = got.get("lines") or []
        return ("PASS" if got.get("cid") and back else "FAIL",
                {"url": url, "xpath": xpath, "cid": got.get("cid"),
                 "ancestors_walked": got.get("ancestors_walked"),
                 "lines": len(back),
                 "keyed": sum(1 for ln in back if ln.get("key")),
                 "controls": sum(1 for ln in back if ln.get("control"))})

    def _c_keys(self):
        got = self.key_coverage(sample=25)
        ok = got["pct"] >= 90 and got["store"].get("addresses_blank_key") == 0
        return ("PASS" if ok else "FAIL",
                {k: got[k] for k in ("pages_sampled", "fully_keyed",
                                     "partly_keyed", "zero_keyed", "lines",
                                     "keyed", "pct", "store")})

    def _c_click(self):
        g = self._graph()
        page = self.json_eval(
            "JSON.stringify((()=>{const v=app.workspace"
            ".getLeavesOfType('domvec-graph-view')[0].view;"
            "const d=(v.projector||v).graph.graphData();"
            "const p=d.nodes.filter(n=>n.level==='page');"
            "return p.length?p[0].url:null;})())")
        if not page:
            return "ERROR", {"why": "no page node to click"}
        got = self.act("click", page)
        r = got.get("result") or {}
        landed = (r.get("browser_url") or "")
        return ("PASS" if landed else "FAIL",
                {"clicked": r.get("clicked"), "browser_url": landed,
                 "reached_that_page": landed.startswith(page[:40]),
                 "billboards": r.get("billboards")})

    def _c_absorb(self):
        g0 = self._graph()
        got = self.act("scan")
        r = got.get("result") or {}
        scan = (r.get("scan") or {}) if isinstance(r, dict) else {}
        g1 = self._graph()
        calls = ((got.get("backend") or {}).get("calls") or 0)
        # **Backend calls are part of the claim.** This once passed on a
        # scan that reported addresses from a cached `lastScan` while the
        # sidecar was dead and nothing was captured at all.
        ok = (not r.get("error")) and scan.get("addresses") and calls > 0
        return ("PASS" if ok else "FAIL",
                {"addresses": scan.get("addresses"), "backend_calls": calls,
                 "rewrites": scan.get("rewrites"),
                 "settled": scan.get("settled"),
                 "nodes_before": g0.get("nodes"), "nodes_after": g1.get("nodes"),
                 "backend": got.get("backend")})

    def _c_retrieve(self):
        got = self.act("retrieve", "price")
        r = got.get("result") or {}
        if r.get("error"):
            return "FAIL", r
        return ("PASS" if r.get("hits") else "FAIL", r)

    def _c_media(self):
        g = self._graph()
        status = g.get("status") or ""
        with_picture = 0
        for part in status.split("\u00b7"):
            if "with a picture" in part:
                try:
                    with_picture = int(part.strip().split()[0])
                except Exception:                   # noqa: BLE001
                    pass
        return ("PASS" if with_picture > 0 else "FAIL",
                {"nodes_with_a_picture": with_picture,
                 "billboards": g.get("billboards"), "status": status})

    # -- the pipeline profile ------------------------------------------------

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
        self.evaluate("window.__domvec && window.__domvec.profile.reset()")
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
                    "'domvec-browser-view')[0];const wv=l&&l.view&&l.view.webview;"
                    "if(!wv)return 0;return await wv.executeJavaScript("
                    "'window.scrollBy(0, Math.round(window.innerHeight*0.9)); "
                    "window.scrollY');})()")
            except Exception:                       # noqa: BLE001
                pass
            time.sleep(step)
        # Let the in-flight listeners close; each waits up to 8s.
        time.sleep(max(0.0, min(9.0, deadline - time.time() + 9.0)))

        pane = self.json_eval(
            "JSON.stringify({summary: window.__domvec.profile.summary(),"
            " traces: window.__domvec.profile.traces(60)})") or {}
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
                "panes": ui.get("panes"),
            }
        except Exception as exc:                    # noqa: BLE001
            out["app"] = {"error": str(exc)[:160]}
        return out
