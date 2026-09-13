"""A local read-only window onto the store, for the Obsidian plugin.

The plugin runs in Electron and the store is embedded Kuzu behind Python, so
something has to sit between them. This is the smallest thing that can: a
stdlib HTTP server, bound to the loopback interface, that answers GET requests
and holds no write path at all.

Three decisions worth stating.

It binds 127.0.0.1 and nothing else. The store holds a browsing history --
the reason `Workspace.mirror_path` names its files by digest -- and a server
that answered on 0.0.0.0 would publish it to the local network.

It is read-only BY DEFAULT, and the exception is a door with a lock. No GET
route mutates anything, so a page rendered in a vault cannot alter the store
or touch the web no matter what it contains. `POST /enact` drives the live
browser and exists only when the process was started with `enact=True` --
otherwise it answers 403 and says so. The flag lives on the SERVER because a
plugin setting is a client asserting something about itself, and the client is
a page renderer in an app the user installs plugins into.

It sends the line's ADDRESS, not just its text. The address key is the
`url:xpath:taxonomy:content` identity everything downstream is keyed on, and
it is what lets a click in Obsidian name an element in the real page. Sending
rendered text alone would make the surface a picture of the page rather than
a handle on it.
"""

from __future__ import annotations

import json
import time
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlsplit

from .. import tokens
from .export import _reflow, link_targets
from .htmlform import render_lines
from .layout import build_layout, place_into


#: Capture sessions, keyed by url: the stateful decoder and the trie spine
#: for a page the browser cell is scanning. Held for the life of the server
#: rather than evicted -- a drain's dictionary is append-only, so a session
#: dropped mid-page could not resolve the next drain's interned segments and
#: would fail in a way that looks like a page suddenly going empty.
_capture_sessions: Dict[str, Dict] = {}


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
    self_window = getattr(workspace, "context_window", 0)

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
            # The template this line belongs to, beside the address that
            # identifies it. Two result rows share a shape and never share an
            # address, which is the whole point of carrying both.
            entry["shape"] = address.shape
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

    # The merge layer (`G-27`). A chunk that belongs to a group is still
    # served as itself -- it is what a retrieval hit resolves to, and its
    # addresses are its own -- with the group named beside it so the surface
    # can offer the merged reading without pretending the parts are gone.
    group: Optional[Dict] = None
    if stored.group_of:
        members = workspace.store.group_members(stored.group_of)
        if len(members) > 1:
            group = {
                "lead": stored.group_of,
                "members": [m.cid for m in members],
                "position": [m.cid for m in members].index(stored.cid) + 1,
                # Assembled, never stored: a member rewritten by the next
                # drain would otherwise leave a stale copy of itself inside
                # the merged text.
                "markdown": _reflow(workspace.merged_markdown(stored.group_of)),
                "tokens": tokens.budget(
                    workspace.merged_markdown(stored.group_of)),
            }

    return {
        "cid": stored.cid,
        "url": stored.url,
        "xpath": stored.xpath,
        "lines": lines,
        #: Null unless stage two put this chunk with others (`G-26`).
        "group": group,
        # Reported so a caller can tell a genuinely short chunk from a
        # misaligned one instead of guessing from the render.
        "addresses": len(addresses),
        # The chunk's size in the unit its window was measured in, and the
        # window it was cut against, so a surface can show fill rather than
        # leaving "are these chunks the right size" a question nobody can
        # answer from the vault.
        # What the chunk spends of the WINDOW, which is what the badge
        # beside it is a fraction of. `count` here would report a number the
        # window was never compared against.
        "tokens": tokens.budget(stored.md or ""),
        "window": int(self_window),
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
    enact_allowed = False       # set by serve(); the write path's gate
    #: Set by `serve()`. Separate from `enact_allowed` because they are
    #: different permissions: enact presses controls on live pages, capture
    #: only writes down what the browser cell read.
    capture_allowed = False
    kernel_pool = None          # set by serve(); None means --kernel was off
    shell_pool = None           # set by serve(); shares --kernel's gate

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

    def do_OPTIONS(self) -> None:                   # noqa: N802 (stdlib name)
        """Answer the CORS preflight, or every POST fails before it is sent.

        Obsidian renders from `app://obsidian.md`, so a fetch to loopback is
        cross-origin. A GET with no custom headers is "simple" and goes
        straight through -- which is why reading chunks worked from the first
        day -- but a POST with `Content-Type: application/json` is not, and
        the browser sends an OPTIONS preflight first. `BaseHTTPRequestHandler`
        answers 501 to a verb it has no handler for, the preflight fails, and
        `fetch` REJECTS: the plugin saw a thrown error and reported "no answer
        from the sidecar" while the server was healthy and the 403 it had
        written was never read.

        Invisible to the Node harness, which has no origin and no preflight.
        Only the real app could show it.
        """
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.send_header("Access-Control-Max-Age", "600")
        self.send_header("Content-Length", "0")
        self.end_headers()

    def do_POST(self) -> None:                      # noqa: N802 (stdlib name)
        """The acting routes, each only when the server was asked for one.

        Two now, and they are gated separately on purpose. `enact` presses a
        control in a real browser; `kernel` runs arbitrary Python with this
        process's privileges. Those are different sizes of permission and a
        reader who wanted a notebook did not thereby ask for a vault that can
        drive the web, nor the reverse.
        """
        parts = urlsplit(self.path)
        route = parts.path.strip("/")
        if route == "chunk_preview":
            self._post_chunk_preview()
            return

        # The browser cell handing over what it captured (`G-47`).
        #
        # Ungated for the same reason `chunk_preview` is: it writes only the
        # workspace, runs no process, and presses nothing on any page. It is
        # the scan the reader is watching, arriving from the pane they are
        # watching it in.
        # Where the chunks a live capture produced belong in the picture
        # already on screen (`G-34`). Read-only: it fits nothing and stores
        # nothing, it asks the existing fit where a point lands.
        if route == "place":
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception as exc:                # noqa: BLE001
                self._send(400, {"error": "bad body: %s" % exc})
                return
            if self.workspace is None:
                self._send(503, {"error": "no workspace"})
                return
            try:
                self._send(200, place_into(self.workspace,
                                           body.get("cids") or []))
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
            return

        if route == "capture":
            if not self.capture_allowed:
                # Named, because the alternative is what actually happened:
                # a raw "Cannot execute write operations in a read-only
                # database" from kuzu, which tells a reader about a lock and
                # nothing about a permission they can grant.
                self._send(403, {
                    "error": "capture is off",
                    "why": "the sidecar holds this workspace read-only. "
                           "Start it with --capture to let the browser cell "
                           "scan into it; that takes the store's writer lock "
                           "and excludes other readers.",
                })
                return
            self._post_capture()
            return

        if route not in ("enact", "kernel", "shell"):
            self._send(404, {"error": "no such route", "path": parts.path})
            return

        if route == "kernel":
            self._post_kernel()
            return

        if route == "shell":
            self._post_shell()
            return

        if not self.enact_allowed:
            # Named rather than a bare 403: a caller that cannot tell "off" from
            # "failed" will retry forever, and a reader of the surface deserves
            # to know the difference between refused and unavailable.
            self._send(403, {
                "error": "enact is off",
                "detail": "start the sidecar with --enact to let the vault "
                          "drive the live page"})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception as exc:                    # noqa: BLE001
            self._send(400, {"error": "bad body: %s" % exc})
            return

        from .enact import EnactError, enact
        try:
            self._send(200, enact(self.workspace,
                                  body.get("address") or "",
                                  body.get("action") or "press",
                                  body.get("text")))
        except EnactError as exc:
            # A refusal is a 409, not a 500: the request was understood and
            # deliberately not carried out, and the surface should say which.
            self._send(409, {"error": str(exc), "refused": True})
        except Exception as exc:                    # noqa: BLE001
            self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})

    def _post_kernel(self) -> None:
        """Run one cell in its note's kernel.

        Body: ``{"note": "<vault path>", "code": "...", "op": "restart"?}``.

        `note` is required and is not defaulted. It is the isolation boundary —
        `NOTEBOOK_PANEL_DESIGN` §4, variables shared within a note and isolated
        across notes — so a missing one would silently put every cell in the
        vault into one shared namespace, which is the failure this design exists
        to avoid and would look like a mysterious name collision rather than a
        missing field.
        """
        if self.kernel_pool is None:
            # Named, not a bare 403: a caller that cannot tell "off" from
            # "failed" retries forever, and the panel should be able to draw the
            # button as unavailable rather than broken.
            self._send(403, {
                "error": "kernel is off",
                "detail": "start the sidecar with --kernel to run cells from "
                          "the vault. It executes arbitrary Python with this "
                          "process's privileges, so it is off by default."})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception as exc:                    # noqa: BLE001
            self._send(400, {"error": "bad body: %s" % exc})
            return

        note = (body.get("note") or "").strip()
        if not note:
            self._send(400, {"error": "missing note",
                             "detail": "the note path is the isolation "
                                       "boundary; without it every cell would "
                                       "share one namespace"})
            return

        if body.get("op") == "restart":
            self._send(200, {"restarted": self.kernel_pool.restart(note),
                             "note": note})
            return

        code = body.get("code")
        if not isinstance(code, str) or not code.strip():
            self._send(400, {"error": "missing code"})
            return

        lang = (body.get("lang") or "python").lower()
        if lang not in ("python", "py", "python3"):
            # Step 3 is python only, and says so rather than running python and
            # pretending it ran bash.
            self._send(400, {
                "error": f"unsupported language {lang!r}",
                "detail": "this kernel runs python; a shell is P-N2's separate "
                          "pane and is not built yet"})
            return

        try:
            self._send(200, self.kernel_pool.run(note, code))
        except Exception as exc:                    # noqa: BLE001
            self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})

    def _post_chunk_preview(self) -> None:
        """Where the chunker would cut this text (`P-N8`).

        A POST because the BODY is the note, and a note is not a query string;
        it carries newlines, and on a long one it is tens of kilobytes.

        **Ungated, and that is not an oversight.** Every other POST here acts on
        the world -- `enact` presses a control in a real browser, `kernel` and
        `shell` run code. This one is a pure function of the text it was handed:
        it writes nothing, reads no workspace, and touches no process. Gating it
        behind `--kernel` would mean a reader could not see why their note
        splits unless they had first enabled code execution, which is a
        permission that has nothing to do with the question.
        """
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception as exc:                    # noqa: BLE001
            self._send(400, {"error": "bad body: %s" % exc})
            return

        text = body.get("text")
        if not isinstance(text, str):
            self._send(400, {"error": "missing text"})
            return
        try:
            from ..vault import chunk_preview
            window = body.get("window")
            self._send(200, {
                "path": body.get("path") or "",
                "chunks": chunk_preview(
                    text, body.get("path") or "untitled.md",
                    vault=(body.get("vault") or "vault"),
                    # The WORKSPACE's window when the caller did not name one,
                    # so a preview cannot disagree with the store about how big
                    # a chunk is -- which is the one way this could mislead.
                    context_window=int(window) if window else getattr(
                        self.workspace, "context_window", None)),
            })
        except Exception as exc:                    # noqa: BLE001
            self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})

    def _post_shell(self) -> None:
        """Run one command in a pane's shell.

        Body: ``{"pane": "<id>", "command": "...", "shell": "pwsh"?, "cwd": ""?,
        "op": "restart"?}``.

        Gated on the KERNEL's flag, deliberately and not by oversight. A second
        flag would imply a distinction that does not exist: a Python kernel can
        already call `subprocess.run`, so a reader who turned that on has shell
        access whether or not a terminal pane exists. A permission that looks
        meaningful and is not is worse than no permission.
        """
        if self.shell_pool is None:
            self._send(403, {
                "error": "shell is off",
                "detail": "start the sidecar with --kernel; the terminal shares "
                          "that gate because a python kernel already grants "
                          "shell access."})
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception as exc:                    # noqa: BLE001
            self._send(400, {"error": "bad body: %s" % exc})
            return

        pane = (body.get("pane") or "").strip()
        if not pane:
            # As with the kernel's note: the pane IS the session boundary, and
            # defaulting it would put every terminal in the vault into one
            # shell -- one reader's `cd` moving another reader's prompt.
            self._send(400, {"error": "missing pane",
                             "detail": "the pane id is the session boundary"})
            return

        if body.get("op") == "restart":
            self._send(200, {"restarted": self.shell_pool.restart(pane),
                             "pane": pane})
            return

        command = body.get("command")
        if not isinstance(command, str) or not command.strip():
            self._send(400, {"error": "missing command"})
            return
        try:
            self._send(200, self.shell_pool.run(
                pane, command, shell=(body.get("shell") or ""),
                cwd=(body.get("cwd") or "")))
        except Exception as exc:                    # noqa: BLE001
            self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})

    def _post_capture(self) -> None:
        """Take one drain from the browser cell into the trie (`G-47`).

        The scan migrates from Selenium to the Electron browser the reader is
        watching, and what crosses this boundary is what crossed the Selenium
        one: **a drain payload**, not a serialisation. The sensor maintains
        the fold in the page and emits, per drain, only what changed -- which
        is the O(delta) contract, and the reason this is a SESSION rather than
        a one-shot post.

        The decoder is stateful and has to be. The payload's dictionary and
        shape table are append-only: a drain carries only the entries added
        since the last one, so a decoder that forgot between calls would fail
        to resolve every interned segment from the first drain onward. That
        state lives in `Sensor`, so `Sensor(None, url)` is constructed here as
        a decoder -- it stores the driver and never touches it unless asked to
        boot, and booting is the browser cell's job now.

        `settle` asks for the one complete write from the finished trie. The
        per-drain writes keep the store current while the reader is still on
        the page, but they are deltas and never retire a chunk that
        re-partitioning replaced -- the Selenium path settles at the same
        point, for the same reason.

        Ungated, like `chunk_preview`: it writes the workspace, runs no
        process, and presses nothing on any page.
        """
        try:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length) or b"{}")
        except Exception as exc:                    # noqa: BLE001
            self._send(400, {"error": "bad body: %s" % exc})
            return

        url = (body.get("url") or "").strip()
        if not url:
            self._send(400, {"error": "capture needs a url"})
            return
        if self.workspace is None:
            self._send(503, {"error": "no workspace"})
            return

        from ..sensing import Sensor
        from ..stream import StreamingScan

        sessions = _capture_sessions
        session = sessions.get(url)
        if session is None or body.get("restart"):
            session = {
                "sensor": Sensor(None, url),
                "spine": StreamingScan(
                    url, context_window=self.workspace.context_window),
                "passno": 0,
            }
            sessions[url] = session

        started = time.perf_counter()
        try:
            if body.get("settle"):
                spine = session["spine"]
                if spine.trie is not None and len(spine.trie):
                    self.workspace.ingest(url, spine.trie,
                                          title=(body.get("title") or ""))
                stored = list(self.workspace.store.chunks(url))
                sessions.pop(url, None)
                self._send(200, {
                    "settled": True, "url": url,
                    "addresses": len(spine.trie) if spine.trie else 0,
                    "chunks": len(stored),
                    "ms": round((time.perf_counter() - started) * 1000, 1),
                })
                return

            payload = body.get("payload") or {}
            if not payload:
                self._send(400, {"error": "capture needs a drain payload"})
                return
            passno = int(session["passno"])
            session["passno"] = passno + 1
            sense = session["sensor"]._as_pass(payload, 0.0, 0.0, passno)
            spine = session["spine"]
            update = spine.absorb(sense.units, sense.passno,
                                  removed=sense.removed_addresses,
                                  moved=sense.moved_addresses)
            dirty = spine.dirty_chunks(update)
            if dirty:
                self.workspace.ingest_chunks(url, dirty, complete=False)
            # Named, not counted. The pane asks `place` about exactly these,
            # and a count would leave it re-fetching the whole layout to find
            # out which three nodes moved.
            dirty_cids = [c.cid for c in dirty]
        except Exception as exc:                    # noqa: BLE001
            # Named rather than swallowed. A capture that fails quietly is
            # indistinguishable from a page with nothing in it, and that
            # confusion has cost this project whole measurement runs.
            self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
            return

        reply = {
            "url": url,
            "passno": passno,
            "addresses": sense.addresses,
            "lines": sense.lines,
            "changed": sense.changed,
            "dirty": len(dirty),
            "dirty_cids": dirty_cids,
            "wire_bytes": sense.wire_bytes,
        }

        # Placed HERE, in the same reply, when the caller asks.
        #
        # The browser cell wants three things per drain and they are one
        # question: fold the page, store what changed, and say where the
        # changed chunks go. Asking them separately cost a round trip whose
        # only content was a list of cids the server had just computed and
        # was about to be handed back -- and each trip is a fetch from a
        # renderer, a thread from the pool, and a kuzu read that has to
        # re-find the same chunks.
        #
        # `POST /place` stays, because "where would these go" is a real
        # question on its own -- a pane that already has cids from somewhere
        # else has no drain to attach them to.
        if body.get("place") and dirty_cids:
            try:
                reply.update(place_into(self.workspace, dirty_cids))
            except Exception as exc:                # noqa: BLE001
                # Named and non-fatal. The capture succeeded and is stored;
                # failing to say where the chunks go must not read to the
                # caller as failing to capture them.
                reply["place_error"] = "%s: %s" % (type(exc).__name__, exc)

        reply["ms"] = round((time.perf_counter() - started) * 1000, 1)
        self._send(200, reply)

    def do_GET(self) -> None:                       # noqa: N802 (stdlib name)
        parts = urlsplit(self.path)
        segments = [unquote(s) for s in parts.path.strip("/").split("/") if s]

        if not segments or segments[0] == "health":
            # `enact` is advertised so the plugin can draw a read-only
            # surface as read-only rather than offering a button that 403s.
            self._send(200, {"ok": True,
                             "pages": len(self.workspace.pages()),
                             "enact": bool(self.enact_allowed),
                             "capture": bool(self.capture_allowed),
                             # Advertised so the panel can draw a run button as
                             # disabled rather than offering one that 403s --
                             # the same reason `enact` is advertised.
                             "kernel": self.kernel_pool is not None})
            return

        if segments[0] == "chunk" and len(segments) == 2:
            payload = chunk_payload(self.workspace, segments[1])
            if payload is None:
                self._send(404, {"error": "no such chunk", "cid": segments[1]})
            else:
                # Both forms, from one payload, in one response.
                #
                # Two round trips would let the surface hold a markdown form
                # and an HTML form fetched at different moments, which is two
                # renderings of possibly two states. They are one
                # distillation; they travel together.
                payload["html"] = render_lines(payload["lines"],
                                               base=payload.get("url", ""))
                self._send(200, payload)
            return

        if segments[0] == "sensor":
            # The browser cell runs the SAME sensor the Selenium path runs,
            # read from the same file at request time. Bundling a copy into
            # the plugin would create a second sensor that drifts from the
            # first, and every capture comparison after that would be
            # measuring the drift instead of the page.
            from .. import sensing
            try:
                source = sensing._JS.read_text(encoding="utf-8")
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "sensor unreadable: %s" % exc})
                return
            self._send(200, {"source": source})
            return

        if segments[0] == "links":
            # Where a link to each page should land. The gesture needs the
            # SAME cid the export uses, or the two would write different
            # edges for one link and the graph would show both.
            self._send(200, {"targets": link_targets(self.workspace)})
            return

        if segments[0] == "layout":
            # Cached on the handler CLASS, so every request in this process
            # shares one fit. UMAP over a real workspace is seconds, and the
            # 3D view asks on every open; refitting per request would make
            # opening the pane feel broken. Keyed on the chunk count so an
            # ingest invalidates it without anyone having to remember to.
            want = int((parse_qs(parts.query).get("dims") or ["3"])[0])
            want = 3 if want not in (2, 3) else want
            fresh = (len(self.workspace.store.chunks()), want)
            if getattr(type(self), "_layout_key", None) != fresh:
                type(self)._layout_key = fresh
                type(self)._layout = build_layout(self.workspace, dims=want)
            self._send(200, type(self)._layout)
            return

        if segments[0] == "kernel":
            # What is running, so a reader can tell a lost namespace from a
            # kernel that never started.
            if self.kernel_pool is None:
                self._send(200, {"enabled": False, "kernels": []})
            else:
                self._send(200, dict(self.kernel_pool.status(), enabled=True))
            return

        if segments[0] == "shell":
            if self.shell_pool is None:
                self._send(200, {"enabled": False, "shells": []})
            else:
                self._send(200, dict(self.shell_pool.status(), enabled=True))
            return

        if segments[0] == "interpreters":
            # Discovery, not a fixed list: what can be run is a property of the
            # machine, and a hardcoded list is wrong on every machine but the
            # author\'s. Answered whether or not the kernel is on, because a
            # panel should be able to say what WOULD be available.
            from .shell import interpreters
            self._send(200, interpreters())
            return

        if segments[0] == "search":
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


def serve(workspace, port: int = 8787, *, block: bool = True,
          enact: bool = False, capture: bool = False, kernel: bool = False,
          kernel_timeout: Optional[float] = None):
    """Answer on loopback until stopped.

    Returns the server so a caller that passed ``block=False`` can shut it
    down; a test that leaks one wedges the port for the next run.

    ``kernel`` starts a pool of per-note Python subprocesses and opens
    ``POST /kernel``. It is off by default because it runs arbitrary code with
    this process's privileges, which is a larger permission than anything else
    here, and it is a SEPARATE flag from ``enact`` because a reader who wanted a
    notebook did not thereby ask for a vault that can drive the web.
    """
    pool = None
    shells = None
    if kernel:
        from .kernel import DEFAULT_TIMEOUT, KernelPool
        from .shell import ShellPool
        pool = KernelPool(timeout=kernel_timeout or DEFAULT_TIMEOUT)
        # One flag for both: see `_post_shell` for why a second would be a
        # permission that looks meaningful and is not.
        shells = ShellPool()

    handler = type("_Bound", (_Handler,),
                   {"workspace": workspace, "enact_allowed": bool(enact),
                    "capture_allowed": bool(capture),
                    "kernel_pool": pool, "shell_pool": shells})

    class _Server(ThreadingHTTPServer):
        # A vault opens many chunks at once -- a note with several `domvec`
        # blocks, or the graph view beside a handful of surfaces -- and every
        # one is its own connection, arriving together.
        #
        # `socketserver` defaults `request_queue_size` to 5, so the sixth
        # connection of a burst is REFUSED rather than queued. Measured with
        # nine simultaneous requests: exactly one came back ECONNREFUSED and
        # the rest were fine, which is the worst possible shape -- the plugin
        # answers null on a failed fetch, the surface then says "sidecar
        # unreachable", and it stays saying that until the note is edited. One
        # surface in nine looked broken while the sidecar was healthy.
        request_queue_size = 128
        daemon_threads = True

    server = _Server(("127.0.0.1", port), handler)
    # The pool hangs off the server so a `block=False` caller can reach it, and
    # so nothing else has to remember it exists.
    server.kernel_pool = pool
    server.shell_pool = shells
    if block:
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            pass
        finally:
            # Kernels are child PROCESSES, and they go before the socket does.
            # A Ctrl-C that left them running would leak an interpreter per
            # note, and the next run would find the machine slower for reasons
            # nothing on screen explains.
            if pool is not None:
                pool.shutdown()
            if shells is not None:
                shells.shutdown()
            server.server_close()
        return server
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server
