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
    "name": "vertiscope",
    "title": "vertiscope distiller",
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
        "name": "wake",
        "description": (
            "Force the Obsidian window to behave as focused and visible, and "
            "say whether it was. A minimised window throttles the render loop "
            "to about one frame every two seconds, so any reading with time in "
            "it -- frame rates, settling, whether a simulation moved -- is a "
            "reading of the window manager rather than the plugin. Measured on "
            "one pane: 0 frames in 2 s hidden, 407 awake. Geometry is "
            "unaffected. Every other tool here wakes the window first; this is "
            "for asking what state it was in."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "graph_probe",
        "description": (
            "Whether the projector's two layers NEST, measured in world units "
            "with the pane's own sizing and collider functions. Reports node "
            "radius by layer, how far each unfolding reaches against the gap "
            "to the nearest other page, how many branches draw larger than the "
            "page they came out of, genuinely interpenetrating pairs, and "
            "nodes drawn with no edge at all. Use instead of reading "
            "ui_state's screen-space overlap count, which conflates depth."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "key_coverage",
        "description": (
            "Do the markdown lines a reader sees carry their address? "
            "Reported PER PAGE, because the failure is all-or-nothing per page "
            "and a corpus-wide ratio hides it. Also returns the store's blank-"
            "key counters. A line with no key has no handle on the page: no "
            "affordances, and nothing for resolve_address to resolve."),
        "inputSchema": {
            "type": "object",
            "properties": {"sample": {"type": "integer",
                                      "description": "How many pages (default 40)"}},
        },
    },
    {
        "name": "repair_keys",
        "description": (
            "Rebuild the address key for every stored address that lost one, "
            "in place and without re-scanning: the key is derived from four "
            "columns already on the row. A line whose address has no key has "
            "no handle on the page -- no affordances, nothing for "
            "resolve_address. Returns how many were blank, repaired, and "
            "unrepairable. Idempotent; check key_coverage first to see "
            "whether it is needed."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "relink",
        "description": (
            "Recompute the page-to-page link graph across the whole corpus. "
            "A link edge is written at ingest against the pages that existed "
            "then, and nothing revisits it, so a corpus built one page at a "
            "time ends with almost none. Nothing is re-scanned: every "
            "outgoing link is already a url-valued address in the store. "
            "Idempotent."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "pipeline_profile",
        "description": (
            "Time every stage of the live pipeline from the page to the "
            "pixels: the guest's fold, the drain bridge, the capture round "
            "trip, the sidecar's own phases (decode, trie absorb, markdown "
            "render, lock wait, store and its parts, UMAP placement), "
            "transport, the graph's absorb, and the moment a listener SEES "
            "the node drawn in the 3D view. Drives a real workload: navigates "
            "the browser cell and scrolls so the MutationObserver folds. "
            "Returns percentiles per stage, each drain's outcome, the "
            "background embedder's own timings, and consistency checks."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string",
                        "description": "Page to drive; blank = current page"},
                "seconds": {"type": "number",
                            "description": "How long to drive it (default 25)"},
                "scrolls": {"type": "integer",
                            "description": "Scroll steps (default 6)"},
            },
        },
    },
    {
        "name": "confirm",
        "description": (
            "Run the live requirement checks INSIDE the running plugin -- "
            "hardware in the loop -- and return a verdict per requirement id "
            "with the evidence each measured. The checks are the plugin's own "
            "(checks/live.mjs, the same list the terminal runs); the plugin "
            "is reloaded first so the loaded code is the code on disk, and "
            "progress shows in the browser cell's corner box while it runs. "
            "`only` runs a subset; `wait:false` returns once started (then "
            "poll verify_state)."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "only": {"type": "array", "items": {"type": "string"},
                         "description": "Requirement ids, e.g. [\"G-54\", \"G-6\"]"},
                "wait": {"type": "boolean", "description": "Wait for the run (default true)"},
                "timeout_s": {"type": "number", "description": "Give up waiting after (default 1200)"},
                "fresh": {"type": "boolean", "description": (
                    "Run against a NEW, EMPTY store: the PLUGIN starts a "
                    "second sidecar, fills it by browsing a fixed page list, "
                    "runs the checks and switches itself back -- all inside "
                    "the app, shown in the corner box. The working store is "
                    "untouched. Minutes of seeding before the checks.")},
            },
        },
    },
    {
        "name": "checks_box",
        "description": (
            "The check run AS THE APP SHOWS IT: opens the browser cell's "
            "corner box and reads its check list off the rendered box -- the "
            "summary line, one row per verdict, each failure's evidence as "
            "drawn. This is where a run is observed; verify_state is the "
            "state object behind it."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "app_screenshot",
        "description": (
            "A PNG of the Obsidian window, written to build_analytics/ (or "
            "`path`); returns the file path. For seeing what a person sees: "
            "the corner box, the side panel, billboards, the graph."),
        "inputSchema": {"type": "object", "properties": {
            "path": {"type": "string", "description": "Where to write it (optional)"}}},
    },
    {
        "name": "graph_motion",
        "description": (
            "Film the 3D graph while the pipeline feeds it. Records every node's "
            "world and screen motion per rendered frame, the velocity each force "
            "added to it, and the pipeline's events (drains, placements, folds, "
            "graphData swaps, reheats); optionally drives rapid scroll+hover in the "
            "browser cell meanwhile. Returns the anomalies -- teleports, vibration, "
            "drift, runaways, flicker, pulsing sizes, page churn, long links, and "
            "why nodes are not visible -- each with the forces that moved it and "
            "the event just before; writes an annotated overview, contact sheets "
            "of the overview and of a zoomed off-screen film of the open page, and "
            "the full JSON."),
        "inputSchema": {"type": "object", "properties": {
            "seconds": {"type": "number", "description": "Recording window (default 16, max 60)"},
            "drive_seconds": {"type": "number", "description": "Rapid scroll+hover seconds (default 8; 0 = only watch)"},
            "url": {"type": "string", "description": "Page to drive and film (default: the one browsed)"},
            "reload": {"type": "boolean", "description": "Reload the plugin first so the build on disk is what runs"}}},
    },
    {
        "name": "app_anomalies",
        "description": (
            "What is WRONG in the running app right now, measured by the app's "
            "own objects: drawn nodes the store does not hold (phantoms), "
            "streaming nodes with no pending spec, links to undrawn nodes, the "
            "tree verdict over every drawn edge, whether the browsed page's "
            "stream is a tree or a star hung on its page node, every open panel "
            "(form, empty, images loaded/broken/duplicated, its trie address), "
            "the last panels opened and whether they rendered, overlay boxes "
            "outside the browser cell, and latency (pushed drains, "
            "mutation->host, drain->overlay, drain->3D). `problems` lists each "
            "anomaly in words. Read-only."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "panel_completeness",
        "description": (
            "Is a chunk's panel COMPLETE against the stored chunk (G-197)? Opens "
            "its panel, draws each form (markdown, page) and reports: the pictures "
            "the chunk's lines name, how many each form rendered, loaded and broke, "
            "which are missing, and the share of the chunk's text the form shows. "
            "Closes what it opened."),
        "inputSchema": {"type": "object", "properties": {
            "cid": {"type": "string", "description": "The chunk id"},
            "url": {"type": "string", "description": "Its page (optional)"}}, "required": ["cid"]},
    },
    {
        "name": "graph_inspect",
        "description": (
            "An off-screen camera framed on one page (default: the one browsed), "
            "from the reader's viewing direction, rendered to a PNG without moving "
            "the reader's camera -- the page at the scale its glitches live."),
        "inputSchema": {"type": "object", "properties": {
            "url": {"type": "string"}, "size": {"type": "integer"},
            "path": {"type": "string", "description": "Where to write the PNG (optional)"}}},
    },
    {
        "name": "verify_state",
        "description": (
            "The in-app check run's state right now: whether it is running, "
            "which check, how many done, and every result so far with its "
            "evidence. Read-only; does not start anything."),
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "design_state",
        "description": (
            "The computed status of every numbered requirement: how many are "
            "done, open, partly, defect, and which done rows cite no evidence. "
            "Computed from the PRD, never hand-kept -- it drifted sixteen rows "
            "in a week when it was."),
        "inputSchema": {
            "type": "object",
            "properties": {"status": {"type": "string",
                                      "description": "Filter: done|open|partly|defect"},
                           "prefix": {"type": "string",
                                      "description": "Filter by id prefix, e.g. G- or D-"}},
        },
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
    {
        "name": "sidecar_start",
        "title": "Start vertiscope sidecar",
        "description": "Start the vertiscope sidecar server on a workspace with the full feature set (semantic, capture, enact, kernel, supervise).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace": {"type": "string", "description": "Path to workspace (default: build/corpus123)"},
                "stop_existing": {"type": "boolean", "default": False, "description": "Replace a sidecar already on the port (otherwise it is left running and reported)"},
                "force": {"type": "boolean", "default": False, "description": "Start or stop even with the store's WAL over 8 MB"},
                "port": {"type": "integer", "description": "Port to serve on (default: 8788)"},
                "semantic": {"type": "boolean", "default": True},
                "capture": {"type": "boolean", "default": True},
                "enact": {"type": "boolean", "default": True},
                "kernel": {"type": "boolean", "default": True},
                "supervise": {"type": "boolean", "default": True},
            },
        },
    },
    {
        "name": "sidecar_stop",
        "title": "Stop vertiscope sidecar",
        "description": "Stop any running sidecar and supervisor processes on the specified port. Refused while the store's WAL is over 8 MB unless forced.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "port": {"type": "integer", "default": 8788},
                "force": {"type": "boolean", "default": False},
            },
        },
    },
    {
        "name": "sidecar_status",
        "title": "Status of vertiscope sidecar",
        "description": "Check if the sidecar process is running and whether its HTTP endpoint is healthy.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "port": {"type": "integer", "default": 8788},
            },
        },
    },
    {
        "name": "workspace_open",
        "title": "Open workspace in vault",
        "description": "Prepare a fresh workspace and vault, configure the vertiscope-bridge plugin, launch the sidecar with full powers, and open Obsidian with CDP debugging.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "workspace": {"type": "string", "description": "Path to workspace directory"},
                "vault": {"type": "string", "description": "Path to Obsidian vault directory"},
                "port": {"type": "integer", "default": 8788},
                "cdp_port": {"type": "integer", "default": 9222},
                "launch_obsidian": {"type": "boolean", "default": True},
            },
            "required": ["workspace", "vault"],
        },
    },
    {
        "name": "obsidian_launch",
        "title": "Launch Obsidian with CDP",
        "description": "Launch Obsidian with remote debugging enabled (--remote-debugging-port) and unthrottling flags, pointing to the vault.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "vault": {"type": "string", "description": "Path to vault directory"},
                "cdp_port": {"type": "integer", "default": 9222},
                "close_existing": {"type": "boolean", "default": True},
            },
        },
    },
    {
        "name": "obsidian_close",
        "title": "Close Obsidian",
        "description": "Terminate any running Obsidian processes cleanly.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "obsidian_eval",
        "title": "Evaluate JavaScript in Obsidian",
        "description": "Evaluate an arbitrary JavaScript expression in the Obsidian renderer window via CDP and return the evaluated result.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "expression": {"type": "string", "description": "JavaScript expression to evaluate"},
            },
            "required": ["expression"],
        },
    },
    {
        "name": "plugin_reload",
        "title": "Reload vertiscope-bridge plugin",
        "description": "Reload the vertiscope-bridge plugin inside the running Obsidian window without restarting Obsidian.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "settle": {"type": "number", "default": 3.0, "description": "Settling time in seconds after reload"},
                "wait": {"type": "boolean", "default": False, "description": "Wait for projector to draw"},
                "force": {"type": "boolean", "default": False, "description": "Reload even though the reader was active in the last minute"},
            },
        },
    },
    {
        "name": "graph_reframe",
        "title": "Reframe 3D graph camera",
        "description": "Trigger the camera reframe/recenter in the 3D graph view to frame the entire cloud and report new camera coordinates.",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


class VertiscopeMCP:
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
            "wake": self._wake,
            "pipeline_profile": self._pipeline_profile,
            "repair_keys": self._repair_keys,
            "relink": self._relink,
            "graph_probe": self._graph_probe,
            "key_coverage": self._key_coverage,
            "confirm": self._confirm,
            "checks_box": lambda a: self.live().observe_checks(),
            "app_screenshot": lambda a: self.live().screenshot(str(a.get("path") or "")),
            "graph_motion": self._graph_motion,
            "app_anomalies": lambda a: self.live().json_eval(
                "(async () => JSON.stringify(await window.__vertiscope.anomalies()))()"),
            "panel_completeness": lambda a: self.live().json_eval(
                "(async () => JSON.stringify(await app.workspace.getLeavesOfType('vertiscope-graph-view')[0].view"
                ".panelCompleteness(%s, %s)))()" % (json.dumps(str(a.get("cid") or "")), json.dumps(str(a.get("url") or "")))),
            "graph_inspect": lambda a: __import__("vertiscope.obsidian.motionfilm", fromlist=["inspect"]).inspect(
                self.live(), str(a.get("url") or ""), int(a.get("size") or 480), str(a.get("path") or "")),
            "verify_state": self._verify_state,
            "design_state": self._design_state,
            "sidecar_start": lambda a: __import__("vertiscope.obsidian.controls", fromlist=["start_sidecar"]).start_sidecar(
                workspace=a.get("workspace") or "build/corpus123",
                stop_existing=bool(a.get("stop_existing", False)),
                force=bool(a.get("force", False)),
                port=int(a.get("port") or 8788),
                semantic=bool(a.get("semantic", True)),
                capture=bool(a.get("capture", True)),
                enact=bool(a.get("enact", True)),
                kernel=bool(a.get("kernel", True)),
                supervise=bool(a.get("supervise", True)),
            ),
            "sidecar_stop": lambda a: __import__("vertiscope.obsidian.controls", fromlist=["stop_sidecar"]).stop_sidecar(
                port=int(a.get("port") or 8788),
                force=bool(a.get("force", False)),
            ),
            "sidecar_status": lambda a: __import__("vertiscope.obsidian.controls", fromlist=["sidecar_status"]).sidecar_status(
                port=int(a.get("port") or 8788),
            ),
            "workspace_open": lambda a: __import__("vertiscope.obsidian.controls", fromlist=["open_workspace"]).open_workspace(
                workspace=a["workspace"],
                vault_path=a["vault"],
                port=int(a.get("port") or 8788),
                cdp_port=int(a.get("cdp_port") or 9222),
                launch_app=bool(a.get("launch_obsidian", True)),
            ),
            "obsidian_launch": lambda a: __import__("vertiscope.obsidian.controls", fromlist=["launch_obsidian"]).launch_obsidian(
                vault_path=a.get("vault"),
                cdp_port=int(a.get("cdp_port") or 9222),
                close_existing=bool(a.get("close_existing", True)),
            ),
            "obsidian_close": lambda a: __import__("vertiscope.obsidian.controls", fromlist=["close_obsidian"]).close_obsidian(),
            "obsidian_eval": lambda a: {
                "result": self.live().evaluate(str(a["expression"]))
            },
            "plugin_reload": lambda a: self.live().reload_plugin(
                settle=float(a.get("settle") or 3.0),
                wait=bool(a.get("wait", False)),
                force=bool(a.get("force", False)),
            ),
            "graph_reframe": lambda a: self.live().json_eval(
                "(async () => { const l = app.workspace.getLeavesOfType('vertiscope-graph-view')[0];"
                " if (!l || !l.view) return { error: 'no graph view' };"
                " l.view.reframe?.();"
                # The reframe is a 400 ms camera flight; reading the camera
                # straight after it reported the halfway point (2026-10-17).
                " await new Promise((r) => setTimeout(r, 700));"
                " const c = l.view.graph?.cameraPosition?.();"
                " return { ok: true, camera: c }; })()"
            ),
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

    def _wake(self, args: Dict) -> Dict:
        return self.live().wake()

    def _pipeline_profile(self, args: Dict) -> Dict:
        return self.live().pipeline_profile(
            url=str(args.get("url") or ""),
            seconds=float(args.get("seconds") or 25.0),
            scrolls=int(args.get("scrolls") or 6))

    def _repair_keys(self, args: Dict) -> Dict:
        return self.live().post("/repair_keys", {})

    def _relink(self, args: Dict) -> Dict:
        return self.live().post("/relink", {})

    def _graph_probe(self, args: Dict) -> Dict:
        return self.live().graph_probe()

    def _key_coverage(self, args: Dict) -> Dict:
        return self.live().key_coverage(int(args.get("sample") or 40))

    def _confirm(self, args: Dict) -> Dict:
        """Live requirement verdicts, from the app that is actually running.

        **Why this is a tool and not a script to run.** The checks existed --
        `confirm.mjs` -- but reaching them meant a shell, a node process, a
        ten-minute wait and a text file to read back. So they were run once
        or twice a session and the requirement space was argued about in
        between. A verdict that is one call away can be the first thing
        asked rather than the last.
        """
        if args.get("fresh"):
            return self.live().verify(args.get("only") or None, fresh=True,
                                      timeout_s=float(args.get("timeout_s") or 2400))
        return self.live().verify(args.get("only") or None,
                                  wait=args.get("wait", True) is not False,
                                  timeout_s=float(args.get("timeout_s") or 1200))

    def _graph_motion(self, args: Dict) -> Dict:
        from .motionfilm import film
        return film(self.live(), seconds=min(60.0, float(args.get("seconds") or 16)),
                    drive_seconds=float(args.get("drive_seconds") if args.get("drive_seconds") is not None else 8),
                    url=str(args.get("url") or ""), reload=bool(args.get("reload")))

    def _verify_state(self, args: Dict) -> Dict:
        """Progress of the in-app run, without starting one."""
        return self.live().verify_state()

    def _design_state(self, args: Dict) -> Dict:
        """The computed status column, read rather than regenerated.

        Regenerating needs the analytics package and a repo checkout; this
        reads the artifact that `python -m vertiscope.analytics.design_state`
        writes, and says how old it is so a stale answer cannot pass as a
        fresh one.
        """
        import os
        import re
        import time
        path = os.path.join("build_analytics", "design_state.md")
        if not os.path.exists(path):
            return {"error": "no design_state.md; run "
                             "python -m vertiscope.analytics.design_state"}
        text = open(path, encoding="utf-8").read()
        want_status = (args.get("status") or "").lower()
        want_prefix = (args.get("prefix") or "")
        rows, counts = [], {}
        for line in text.splitlines():
            m = re.match(r"^\|\s*([A-Z]+-\d+)\s*\|", line)
            if not m:
                continue
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            rid = cells[0]
            status = ""
            for cell in cells[1:]:
                low = cell.lower()
                for name in ("defect", "done", "partly", "open", "confirm",
                             "standing", "superseded"):
                    if low.startswith(name) or low == name:
                        status = name
                        break
                if status:
                    break
            counts[status or "?"] = counts.get(status or "?", 0) + 1
            if want_status and status != want_status:
                continue
            if want_prefix and not rid.startswith(want_prefix):
                continue
            rows.append({"id": rid, "status": status or "?",
                         "what": cells[1][:150] if len(cells) > 1 else ""})
        return {
            "generated": time.strftime(
                "%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(path))),
            "age_minutes": round((time.time() - os.path.getmtime(path)) / 60),
            "counts": counts, "matched": len(rows), "rows": rows[:120],
        }

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
                        "Addressed web chunks from the vertiscope distiller. "
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
    server = VertiscopeMCP(workspace, sidecar_url=sidecar_url, cdp_url=cdp_url)
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
        prog="python -m vertiscope.obsidian.mcp",
        description="MCP server over a vertiscope workspace (stdio, read-only).")
    parser.add_argument("--workspace", type=Path, default=None,
                        help="optional: open a store DIRECTLY for the "
                             "backend tools. Usually wrong -- the sidecar "
                             "holds the live workspace and a kuzu writer "
                             "excludes readers, so this loses the race or "
                             "takes the lock the plugin needs. Left unset, "
                             "the backend tools ask the sidecar instead.")
    parser.add_argument("--sidecar", default="http://127.0.0.1:8788")
    parser.add_argument("--cdp", default=__import__("os").environ.get("VERTISCOPE_CDP", "http://127.0.0.1:9222"))
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
            print("vertiscope MCP: no store (%s); live tools only"
                  % str(exc)[:120], file=sys.stderr)
            ws = None

    print("vertiscope MCP: sidecar %s, app %s%s"
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
