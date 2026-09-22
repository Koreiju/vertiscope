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
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlsplit

from .. import tokens
from .export import _reflow, link_targets
from .htmlform import render_lines
from .layout import (build_layout, build_page_layout, place_into,
                     remember_page_positions, unfold as unfold_path)


#: Capture sessions, keyed by url: the stateful decoder and the trie spine
#: for a page the browser cell is scanning. Held for the life of the server
#: rather than evicted -- a drain's dictionary is append-only, so a session
#: dropped mid-page could not resolve the next drain's interned segments and
#: would fail in a way that looks like a page suddenly going empty.
_capture_sessions: Dict[str, Dict] = {}

#: Serialises everything that WRITES the workspace.
#:
#: The server is already threaded -- a vault opens many chunks at once -- and
#: adding a background embedder makes a writer concurrent with those readers
#: for the first time. A kuzu connection is not built to be used from several
#: threads at once, so every mutation goes through here. It is an `RLock`
#: because `ingest` reaches `flush_vectors`, which would otherwise deadlock
#: against itself.
_WORK_LOCK = threading.RLock()

#: Serialises LAYOUT FITTING, which `_WORK_LOCK` does not cover.
#:
#: `_WORK_LOCK` guards writes. A fit is a read, so it was taking nothing --
#: and this is a `ThreadingHTTPServer`, so two `/layout` requests arriving
#: together each ran UMAP on its own thread. The process segfaulted three
#: times under a full confirmation suite: native, no Python traceback,
#: always while layouts were being fitted and always with the pane and a
#: probe both asking. UMAP's numba kernels are not built to be entered
#: concurrently from one process.
#:
#: A separate lock rather than `_WORK_LOCK`, deliberately. A cold
#: chunk-level fit is 95 seconds, and holding the write lock for it would
#: stall every live capture behind it: fits wait for fits, captures do not
#: wait for fits.
_FIT_LOCK = threading.Lock()

#: Raised when there are chunks waiting for vectors.
_EMBED_WANTED = threading.Event()

#: The background embedder, started by `serve()` when a workspace has an
#: embedder to run. One thread, not a pool: the encoder is the bottleneck and
#: two of them would contend for the same GPU.
_EMBED_THREAD = None


def _aggregate_due(workspace) -> None:
    """Re-cluster the pages that have gone quiet (`G-65`).

    Runs on the embedding worker, after a flush, because the two are ordered:
    a page clustered before its new chunks have vectors would cluster the
    chunks it had a moment ago. Off the request path either way -- a capture
    returns without waiting for this, and the groups appear on the next one.
    """
    now = time.monotonic()
    due = [url for url, when in list(_AGGREGATE_AFTER.items()) if when <= now]
    for url in due:
        _AGGREGATE_AFTER.pop(url, None)
        try:
            with _WORK_LOCK:
                workspace.aggregate(url)
        except Exception:                           # noqa: BLE001
            # A page that failed to cluster is a page with the groups it had.
            # It must not stop the worker, or nothing would ever be embedded
            # again either -- they share this thread.
            pass


def _embed_forever(workspace, stop: threading.Event) -> None:
    """Embed what is queued, off the request path.

    In batches with the lock RELEASED between them. Holding it for a whole
    page would make the background worker exactly as blocking as the
    synchronous flush it replaces, just further from the caller -- a request
    arriving mid-flush would wait the same 13.9 seconds and have no way to
    know why.
    """
    while not stop.is_set():
        if not _EMBED_WANTED.wait(timeout=0.5):
            # Nothing to embed, but a page may still be due to re-cluster --
            # the last drain of a visit queues one and then no more arrive.
            _aggregate_due(workspace)
            continue
        _EMBED_WANTED.clear()
        while not stop.is_set():
            try:
                with _WORK_LOCK:
                    workspace.flush_vectors(limit=_EMBED_BATCH)
                    # The QUEUE's length, not the flush's return value.
                    # `flush_vectors` answers with `vectors.report()`, which
                    # is a set of cumulative counters -- pushed, queued,
                    # skipped, embedded -- and they are non-zero forever after
                    # the first flush. Reading them as "work done this call"
                    # gives a loop that never exits: a thread spinning on the
                    # encoder, taking and dropping the lock, starving every
                    # request behind it.
                    remaining = len(workspace.vectors)
            except Exception:                       # noqa: BLE001
                # A failed batch leaves its chunks queued and unembedded,
                # which the pane already reports as awaiting a vector. It must
                # not kill the worker: the next capture would queue into a
                # thread that is gone, and nothing would ever be embedded
                # again with no error anywhere to say so.
                break
            if not remaining:
                break
        _aggregate_due(workspace)


#: How many chunks one background batch embeds before yielding the lock.
#:
#: Small enough that a request arriving mid-flush waits for a batch and not a
#: page. 64 chunks is well under a second on this machine's GPU.
_EMBED_BATCH = 64

#: Pages whose chunks changed, and the earliest moment to re-cluster each.
#:
#: `G-65`: stage two ran only at the settle, so while a reader browsed, the
#: merge groups on screen described a page that had moved on.
_AGGREGATE_AFTER: Dict[str, float] = {}

#: How long a page must be quiet before it is re-clustered.
#:
#: Every drain pushes the deadline out, so this runs when the reader pauses
#: rather than while they scroll -- which is the behaviour wanted, because a
#: page mid-scroll is not a page anyone has finished looking at. A full page
#: aggregation is about 110ms now (33ms to read the vectors in one query,
#: ~80ms to cluster), so the debounce exists to avoid pointless work rather
#: than to hide an expensive one.
#:
#: NOT incremental, and deliberately not. An incremental DBSCAN -- union-find
#: over the eps-graph with component splits on change -- was designed and then
#: not built, because measuring first showed the clustering was never the
#: cost: an 835-chunk page spent 330ms reading its vectors one query at a time
#: and 78ms clustering them. Fixing the read made the whole thing cheap enough
#: that the machinery would have been bought to speed up the wrong half.
_AGGREGATE_DEBOUNCE = 1.5


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


def search_payload(workspace, query: str, k: int = 8, *,
                   offset: int = 0, url: str = "",
                   coarse: bool = True, budget: int = 0) -> Dict:
    """Ranked chunks for the overlay (`G-63`, `G-64`, `G-69`, `G-70`).

    Ranking is the store's own three-form retrieval; this adds nothing to it
    and reshapes what comes back.

    **A window over a ranked list, not a top-k.** `G-69`: rank is a total
    order over the corpus and the cutoff is a decision the reader makes by
    stopping. So the caller asks for a slice and keeps asking as it scrolls.
    The rank is recomputed for `offset + k` and sliced, because the index
    ranks rather than paginates -- which is honest but means a deep scroll
    costs more than a shallow one, and the cap is what keeps that bounded.

    **Scoped, or not** (`G-70`). `url` restricts to one shadow DOM, which is
    what clicking a page node means; without it the ranking is the corpus's.

    **Coarse first** (`G-63`). A merge group is represented by its LEAD and
    its members are suppressed, because the group is what the merge layer
    indexes and a reader scrolling results does not want the same passage
    eight times. `coarse=False` drops that and ranks the members themselves,
    which is what a click expansion inside one page wants.

    **Inside a budget** (`G-64`). `budget` in link-free tokens: results are
    taken until the next one would not fit, so a list handed to a model is a
    list that can be handed to a model.
    """
    want = max(1, offset + k)
    # Scoped means ranked WITHIN the page, and the index does that itself now
    # (`scope_url`). It used to be a post-filter over a widened global top-k,
    # bounded so that scoping a large page did not rank the corpus end to
    # end -- and that bound was the defect: RFC 9110's 1,173 chunks rank
    # below the bound globally, so scoping to the largest page in the store
    # returned 0 hits for every query.
    hits = workspace.search(query, k=want, scope_url=url or "")
    out = []
    spent = 0
    seen_groups = set()
    for hit in hits:
        cid = getattr(hit, "cid", None) or getattr(hit, "chunk", "")
        stored = workspace.store.chunk(cid) if cid else None
        if stored is None:
            continue
        if url and stored.url != url:
            continue
        if stored.redundant:
            # `G-24` settled this one: it draws what another chunk draws.
            continue
        if coarse:
            if stored.group_of and stored.group_of != stored.cid:
                # A member speaks through its lead, which ranks on its own.
                continue
            if stored.group_of in seen_groups:
                continue
            if stored.group_of:
                seen_groups.add(stored.group_of)
        out.append({
            "cid": stored.cid,
            "url": stored.url,
            "xpath": stored.xpath,
            "score": float(getattr(hit, "score", 0.0) or 0.0),
            # The three factors, not just their product. The product is a
            # multiplication of three small numbers and lands around 1e-5,
            # which reads as zero at any sane precision and tells a reader
            # nothing about WHY a result ranked -- whether the words matched,
            # the meaning did, or the page is simply well linked.
            "lexical": float(getattr(hit, "lexical", 0.0) or 0.0),
            "semantic": float(getattr(hit, "semantic", 0.0) or 0.0),
            "pagerank": float(getattr(hit, "rank", 0.0) or 0.0),
            "members": stored.group_n,
            "tokens": tokens.budget(stored.md or ""),
            # The first lines, LINK-FREE. The stored markdown is 52.5%
            # machine addressing by token (M.7), and a preview of it
            # reads as the same long path twice inside one `[](...)`,
            # filling the row and pushing the words that would say what
            # the result IS off the end. `for_model` is the string the
            # encoder ranked on, so a preview of it previews what
            # actually matched.
            "preview": "\n".join(
                tokens.for_model(stored.md or "").splitlines()[:6]),
        })

    out = out[offset:offset + k]
    if budget:
        kept = []
        for row in out:
            if spent + row["tokens"] > budget and kept:
                break
            kept.append(row)
            spent += row["tokens"]
        out = kept
    return {"query": query, "hits": out, "offset": offset,
            "scope": url or "", "coarse": bool(coarse),
            "tokens": spent if budget else sum(r["tokens"] for r in out),
            #: True while the ranking still had more to give at this depth,
            #: so a scrolling overlay knows whether to keep asking.
            "more": len(hits) >= want}


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
        # One step of unravelling a page's path (`G-54`). Read-only: it
        # fits nothing and stores nothing.
        if route == "unfold":
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
                # `space` so the anchors come from the fit the reader is
                # actually looking at. Without it an unfolding taken while
                # the pane showed S3 hung its chunks off euclidean page
                # positions, 378 units from the node they belong to.
                self._send(200, unfold_path(self.workspace,
                                            body.get("url") or "",
                                            body.get("path") or "",
                                            space=str(body.get("space") or "")))
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
            return

        # Rebuild `akey` for every address that lost it (`D-26`).
        #
        # A write, so it is a POST, but not a capture: it invents nothing and
        # reaches no page. The key is DERIVED from four columns already on
        # the row, so this is recomputation rather than repair in the sense
        # of guessing. A row missing its url or xpath is left alone and
        # counted, because a handle that points nowhere is worse than none.
        #
        # It is a route rather than a maintenance script because the store is
        # held open by this process: repairing it otherwise means stopping
        # the sidecar, which means the plugin loses its backend, which is how
        # a five-second fix became a restart every time.
        if route == "repair_keys":
            if self.workspace is None:
                self._send(503, {"error": "no workspace"})
                return
            try:
                self._send(200, self.workspace.store.repair_blank_keys())
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
            return

        # Recompute the page link graph over the whole corpus (`D-32`).
        # Same justification as `/repair_keys`: the store is held open by
        # this process, so doing it any other way means taking the plugin's
        # backend away to fix the plugin.
        # Containment among an arbitrary set of drawn chunks (`G-6`).
        #
        # Read-only. The pane sends what it is drawing and gets back the
        # edges the trie holds between those nodes -- including pairs that
        # arrived from different routes at different times, which is exactly
        # what every per-call edge computation misses.
        if route == "edges":
            if self.workspace is None:
                self._send(503, {"error": "no workspace"})
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception as exc:                # noqa: BLE001
                self._send(400, {"error": "bad body: %s" % exc})
                return
            cids = [c for c in (body.get("cids") or []) if c]
            if not cids:
                self._send(200, {"edges": [], "n": 0})
                return
            try:
                drawn = set(cids)
                urls = {c.url for c in self.workspace.store.chunks_by_cids(cids)} \
                    if hasattr(self.workspace.store, "chunks_by_cids") \
                    else {u for u in (body.get("urls") or [])}
                if not urls:
                    urls = set(self.workspace.pages())
                out, seen = [], set()
                for page in urls:
                    for a, b in self.workspace.store.contains_within(page):
                        if a in drawn and b in drawn and a != b \
                                and (a, b) not in seen:
                            seen.add((a, b))
                            out.append({"source": a, "target": b})
                self._send(200, {"edges": out, "n": len(out),
                                 "asked": len(cids), "pages": len(urls)})
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
            return

        if route == "relink":
            if self.workspace is None:
                self._send(503, {"error": "no workspace"})
                return
            try:
                self._send(200, self.workspace.store.relink_pages())
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
            return

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

        if route == "purge":
            # Drop one page, its chunks and its addresses (`store.purge_page`).
            #
            # **This exists so that a live check can clean up after itself.**
            # `S-7` serves a fixture, drives a real interaction in the browser
            # cell and reads the result back out of the trie -- which means it
            # captures a page into the reader's own corpus every time it runs,
            # on a fresh ephemeral port each time. A confirmation harness that
            # grows the corpus it is measuring is an instrument that changes
            # its own denominator, and this file already carries four separate
            # cases of a denominator being the thing that was wrong.
            #
            # Gated with `capture`, not with `enact`: it writes the workspace
            # and presses nothing on any page, which is the same size of
            # permission `capture` is.
            if not self.capture_allowed:
                self._send(403, {
                    "error": "purge is off",
                    "why": "the sidecar holds this workspace read-only. "
                           "Start it with --capture to let it be written.",
                })
                return
            try:
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length) or b"{}")
            except Exception as exc:                # noqa: BLE001
                self._send(400, {"error": "bad body: %s" % exc})
                return
            url = (body or {}).get("url") or ""
            if not url:
                self._send(400, {"error": "no url"})
                return
            try:
                removed = self.workspace.store.purge_page(url)
            except Exception as exc:                # noqa: BLE001
                self._send(500, {"error": "%s: %s" % (type(exc).__name__, exc)})
                return
            self._send(200, {"url": url, "chunks_removed": removed})
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
                # Chunks captured but not yet vectorised. Retried on every
                # later drain, so a chunk whose vector arrives while the
                # reader keeps browsing lands in the picture on its own --
                # the pane does not have to remember to ask again, and a
                # chunk cannot be lost between "captured" and "placed".
                "pending": [],
            }
            sessions[url] = session

        started = time.perf_counter()
        try:
            if body.get("settle"):
                spine = session["spine"]
                if spine.trie is not None and len(spine.trie):
                    with _WORK_LOCK:
                        self.workspace.ingest(
                            url, spine.trie, title=(body.get("title") or ""))
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

            # Every phase timed separately (`G-66`, and constraint 4 of
            # CLAUDE.md, which has said so all along for the fold and the
            # projections and was never extended to this path).
            #
            # A capture was one number -- 2.16 seconds -- covering decode,
            # absorb, render and store, and a single number cannot say which
            # of them to fix. Guessing which phase dominates is the mistake
            # this project keeps making; these four fields are what stops it
            # being guessed again.
            phases = {}
            mark = time.perf_counter()

            sense = session["sensor"]._as_pass(payload, 0.0, 0.0, passno)
            phases["decode"] = round((time.perf_counter() - mark) * 1000, 1)
            mark = time.perf_counter()

            spine = session["spine"]
            update = spine.absorb(sense.units, sense.passno,
                                  removed=sense.removed_addresses,
                                  moved=sense.moved_addresses)
            phases["absorb"] = round((time.perf_counter() - mark) * 1000, 1)
            mark = time.perf_counter()

            # `dirty_chunks` is where `render_trie` runs, so this is the
            # markdown projection's cost on the delta -- named as `render`
            # because that is what it is, whatever the method is called.
            dirty = spine.dirty_chunks(update)
            phases["render"] = round((time.perf_counter() - mark) * 1000, 1)
            mark = time.perf_counter()

            if dirty:
                with _WORK_LOCK:
                    _written, counts = self.workspace.ingest_chunks(
                        url, dirty, complete=False)
                # The store's own breakdown, carried up. `store` was 96% of a
                # capture and one number cannot say which statement it is.
                if isinstance(counts, dict):
                    phases.update({k: v for k, v in counts.items()
                                   if str(k).startswith("ms_")})
                # There are chunks without vectors now. The worker embeds
                # them; this request does not wait for it.
                _EMBED_WANTED.set()
                # And the page's merge groups are now out of date (`G-65`).
                # Each drain pushes the deadline out, so this lands when the
                # reader pauses rather than while they are still scrolling.
                _AGGREGATE_AFTER[url] = time.monotonic() + _AGGREGATE_DEBOUNCE
            phases["store"] = round((time.perf_counter() - mark) * 1000, 1)
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
            "phases": phases,
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
        place_mark = time.perf_counter()
        if body.get("place"):
            # Everything this drain touched, PLUS everything an earlier drain
            # could not place yet. A chunk embedded in the background while
            # the reader scrolled belongs on screen now, and this is the only
            # moment anyone asks.
            wanted = list(dict.fromkeys(
                list(session.get("pending") or []) + dirty_cids))
            try:
                placed = place_into(self.workspace, wanted) if wanted else {}
                reply.update(placed)
                session["pending"] = list(placed.get("unplaced") or [])
            except Exception as exc:                # noqa: BLE001
                # Named and non-fatal. The capture succeeded and is stored;
                # failing to say where the chunks go must not read to the
                # caller as failing to capture them.
                reply["place_error"] = "%s: %s" % (type(exc).__name__, exc)

        # What stage two currently makes of this page. It moves on its own,
        # after the reader pauses, so a pane watching this number is watching
        # live aggregation happen (`G-65`).
        try:
            reply["groups"] = self.workspace.store.group_count(url)
        except Exception:                           # noqa: BLE001
            pass
        phases["place"] = round((time.perf_counter() - place_mark) * 1000, 1)
        reply["ms"] = round((time.perf_counter() - started) * 1000, 1)
        self._send(200, reply)

    def _layout_count(self) -> int:
        """Stored fits, or 0 if the store cannot answer."""
        try:
            rows = self.workspace.store._rows(
                "MATCH (l:Layout) RETURN count(l)")
            return int(rows[0][0]) if rows and rows[0] else 0
        except Exception:                           # noqa: BLE001
            return 0

    def do_GET(self) -> None:                       # noqa: N802 (stdlib name)
        parts = urlsplit(self.path)
        segments = [unquote(s) for s in parts.path.strip("/").split("/") if s]

        if not segments or segments[0] == "health":
            # `enact` is advertised so the plugin can draw a read-only
            # surface as read-only rather than offering a button that 403s.
            # **Is the trie actually ANCHORED?**
            #
            # Addresses and anchors are different things and only one of them
            # was ever counted. A capture reported 320 addresses written for
            # a page while every line of every chunk on it came back with
            # `key: ""`, because the Anchors edges that bind a LINE to an
            # ADDRESS were not there. The address key is the identity
            # everything downstream is keyed on -- the retrieval gesture, the
            # affordance list, the click that names an element in the real
            # page -- so a store full of addresses and empty of anchors is a
            # store whose chunks cannot be acted on at all. Counting both,
            # cheaply, is what makes that visible instead of silent.
            def _one(q):
                try:
                    return self.workspace.store._rows(q)[0][0]
                except Exception:               # noqa: BLE001
                    return None
            self._send(200, {"ok": True,
                             "pages": len(self.workspace.pages()),
                             "addresses": _one(
                                 "MATCH (a:Address) RETURN count(a)"),
                             "anchors": _one(
                                 "MATCH ()-[r:Anchors]->() RETURN count(r)"),
                             # **An anchor whose address will not parse is
                             # worse than a missing one**, because the line
                             # still draws and simply has no handle on the
                             # page -- silently, since `addresses_of` skips
                             # it. Reported so the two causes of a keyless
                             # line can be told apart without guessing.
                             "anchors_blank_key": _one(
                                 "MATCH ()-[r:Anchors]->(a:Address) "
                                 "WHERE a.akey IS NULL OR a.akey = '' "
                                 "RETURN count(r)"),
                             "addresses_blank_key": _one(
                                 "MATCH (a:Address) "
                                 "WHERE a.akey IS NULL OR a.akey = '' "
                                 "RETURN count(a)"),
                             # The edge sets, because "the trie is drawn"
                             # is a claim about these and nothing else was
                             # counting them. A projector showing 89 of 144
                             # nodes isolated is either a layout that does
                             # not ask or a store that does not hold them,
                             # and only these two numbers tell them apart.
                             "contains_edges": _one(
                                 "MATCH (:Chunk)-[r:Contains]->(:Chunk) "
                                 "RETURN count(r)"),
                             "linksto_edges": _one(
                                 "MATCH (:Chunk)-[r:LinksTo]->(:Page) "
                                 "RETURN count(r)"),
                             "linksto_between_stored_pages": _one(
                                 "MATCH (c:Chunk)-[r:LinksTo]->(p:Page) "
                                 "WHERE c.url <> p.url RETURN count(r)"),
                             "unreadable_addresses":
                                 __import__("domvec.graphstore",
                                            fromlist=["GraphStore"])
                                 .GraphStore.unreadable_addresses,
                             "enact": bool(self.enact_allowed),
                             "capture": bool(self.capture_allowed),
                             # Advertised so the panel can draw a run button as
                             # disabled rather than offering one that 403s --
                             # the same reason `enact` is advertised.
                             "kernel": self.kernel_pool is not None,
                             # `G-12`: how many fits the store is holding.
                             # Advertised for the same reason `enact` and
                             # `kernel` are -- a feature nothing can observe
                             # is a feature nobody can confirm, and this one
                             # is invisible by design when it works.
                             "layouts": self._layout_count()})
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

        if segments[0] == "resolve":
            # An address on a live page -> the chunk that draws it (`G-39`).
            #
            # **Walking UP, and that is the whole difficulty.** The element
            # under a reader's cursor is almost never a chunk root -- it is a
            # span inside a paragraph inside a section, and only one of those
            # ancestors is a thing the trie holds. So the exact xpath is
            # tried, then each ancestor in turn, and the FIRST hit wins:
            # the nearest chunk containing what was pointed at, which is what
            # "this thing here" means to the person pointing.
            query = parse_qs(parts.query)
            xpath = (query.get("xpath") or [""])[0]
            url = (query.get("url") or [""])[0]
            if not xpath:
                self._send(400, {"error": "no xpath"})
                return
            #: A PREFIX match, not an equality one, and that is not an
            #: optimisation -- it is what the data requires. Chunks anchor to
            #: TEXT nodes: the element `.../ul/li/a` has no anchor and
            #: `.../ul/li/a/text()[1]` does. An equality test on what the
            #: cursor is over therefore finds nothing on almost every page.
            #:
            #: (`addresses_at` is the wrong instrument here for a second
            #: reason: it returns `(address, VALUE)`, not `(address, aid)`,
            #: so feeding its second element to `chunk_for_address` hands it
            #: an href and gets None every time.)
            steps = [s for s in xpath.split("/") if s]
            found = None
            walked = 0
            tried = []
            while steps and found is None:
                candidate = "/" + "/".join(steps)
                tried.append(candidate)
                rows = self.workspace.store._rows(
                    "MATCH (c:Chunk)-[:Anchors]->(a:Address) "
                    "WHERE c.url = $u AND (a.xpath = $x "
                    "OR starts_with(a.xpath, $p)) "
                    "RETURN c.cid LIMIT 1",
                    {"u": url, "x": candidate, "p": candidate + "/"})
                if rows and rows[0] and rows[0][0]:
                    chunk = self.workspace.store.chunk(rows[0][0])
                    if chunk is not None:
                        found = (candidate, chunk)
                if found is None:
                    steps.pop()
                    walked += 1
            if found is None:
                # Say what was tried. A bare "not found" over a walk of
                # seven candidates is not a diagnosis.
                self._send(404, {"error": "no chunk draws that address",
                                 "xpath": xpath, "url": url,
                                 "tried": tried})
                return
            at, chunk = found
            payload = chunk_payload(self.workspace, chunk.cid) or {}
            payload["matched_xpath"] = at
            #: How far up the document the answer was found. 0 means the
            #: reader pointed straight at a chunk root; a large number means
            #: they pointed at something deep inside one, and both are
            #: ordinary.
            payload["ancestors_walked"] = walked
            payload["asked_xpath"] = xpath
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

        if segments[0] == "pages":
            # Every page url the store holds, straight from the Page table.
            #
            # **Not the same question as /layout.** That one is a cached FIT,
            # keyed on chunk count and shared across requests so the 3D view
            # does not refit on every open -- it answered 98 nodes while the
            # store held 119 pages, which is correct for a fit and useless
            # for "what is in here". Cleanup after a live check needs the
            # second question, and asking the first was how 20 fixture pages
            # went unnoticed.
            #
            # Read-only, like every other GET here. `?contains=` filters by
            # substring, which is what a caller tidying up after itself has.
            query = parse_qs(parts.query)
            needle = (query.get("contains") or [""])[0]
            rows = self.workspace.store._rows(
                "MATCH (p:Page) RETURN p.url ORDER BY p.url")
            urls = [r[0] for r in rows if r and r[0]]
            if needle:
                urls = [u for u in urls if needle in u]
            self._send(200, {"urls": urls, "n": len(urls)})
            return

        if segments[0] == "addresses":
            # The xpaths one page holds, for a claim about STRUCTURE.
            #
            # `/resolve` answers "which chunk draws this point", which is the
            # reader's question and the wrong one here: a structural claim --
            # that a node inside a shadow root sits under its host in the
            # trie -- is about the set of addresses and their prefixes, not
            # about any one of them. `/pages` is its sibling for the same
            # reason.
            #
            # Read-only, like every other GET. `?contains=` filters by
            # substring, which is how a caller asks only for the shadow ones.
            query = parse_qs(parts.query)
            url = (query.get("url") or [""])[0]
            if not url:
                self._send(400, {"error": "no url"})
                return
            needle = (query.get("contains") or [""])[0]
            limit = int((query.get("limit") or ["4000"])[0])
            rows = self.workspace.store._rows(
                "MATCH (a:Address {url: $u}) RETURN a.xpath, a.tag, a.akey "
                "ORDER BY a.xpath", {"u": url})
            out = []
            blank_keys = 0
            for xpath, tag, akey in rows:
                if not akey:
                    blank_keys += 1
                if not xpath:
                    continue
                if needle and needle not in xpath:
                    continue
                # The KEY is the identity everything downstream is anchored
                # on. A row with a blank one cannot be parsed back, so the
                # line that points at it loses its handle on the page.
                out.append({"xpath": xpath, "tag": tag or "",
                            "akey": akey or ""})
                if len(out) >= limit:
                    break
            self._send(200, {"url": url, "n": len(out),
                             "rows_total": len(rows),
                             "blank_akeys": blank_keys, "addresses": out})
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
            query = parse_qs(parts.query)
            want = int((query.get("dims") or ["3"])[0])
            want = 3 if want not in (2, 3) else want
            # `?space=S3` asks for the quaternion embedding (`G-18`). A query
            # parameter rather than a startup flag, because the two fits are
            # a thing to COMPARE -- the pane can ask for either without
            # restarting the server, and the reply says which it got.
            spherical = (query.get("space") or [""])[0].lower() in (
                "s3", "spherical", "quaternion")
            # PAGES by default (`G-53`). 12,820 chunk nodes hold 3.3 fps
            # because each node and each link is its own draw call; 96 pages
            # is 96. `?level=chunk` still asks for every chunk, because the
            # two are a thing to compare and a small workspace has no reason
            # to collapse.
            level = (query.get("level") or ["page"])[0].lower()
            level = "chunk" if level == "chunk" else "page"
            # **Which corpus, not how big it is (`D-22`).**
            #
            # This was keyed on `chunk_count()` alone, and a count is not an
            # identity: purge twenty pages, capture twenty chunks elsewhere,
            # and the key is unchanged while the corpus is not. A stored fit
            # then comes back for documents it never saw -- measured, a
            # served page layout still held nodes for purged fixtures, and
            # unfolding anchored 643 units from the page against a ball of
            # radius 90.
            #
            # `corpus_fingerprint` is one ordered scan of the Page table,
            # hashed, on the same path that already pays for the count.
            fresh = (self.workspace.store.corpus_fingerprint(), want,
                     spherical, level)
            # A few slots, not one.
            #
            # A single slot is right when there is one question; there are
            # four here (page/chunk x euclidean/S3) and the pane has a button
            # for each axis. With one slot, toggling the space refit the
            # WHOLE corpus, then toggling back refit it again -- and the S3
            # fit is two UMAP runs since the warm start was wired, so a
            # reader pressing a button twice paid for four fits to see two
            # pictures it had already computed. Keyed identically; only the
            # number of remembered answers changes.
            cache = getattr(type(self), "_layouts", None)
            if cache is None:
                cache = type(self)._layouts = {}
            if fresh not in cache:
                # `G-12`: the store may already hold this exact fit. Keyed
                # on everything the fit is a function of, so a stored answer
                # comes back only to the question it answered. The
                # chunk-level fit is 95 seconds over this corpus and the
                # page-level one under a second, so what this buys is the
                # expensive picture surviving a restart.
                stored_key = "|".join(str(v) for v in fresh)
                kept = None
                try:
                    kept = self.workspace.store.load_layout(stored_key)
                except Exception:                   # noqa: BLE001
                    kept = None
                if kept:
                    try:
                        got = json.loads(kept)
                        got["from_store"] = True
                        cache[fresh] = got
                        # A stored layout skips `build_page_layout`, and with
                        # it the side effect that records where each page was
                        # drawn. Restore it, or an unfolding anchors on
                        # nothing (`D-21`).
                        if level == "page":
                            remember_page_positions(got, spherical)
                    except Exception:               # noqa: BLE001
                        pass
            if fresh not in cache:
              # Checked again INSIDE the lock: two threads can both miss,
              # and the point is that only one of them fits.
              with _FIT_LOCK:
                if fresh not in cache:
                    cache[fresh] = (
                        build_page_layout(self.workspace, dims=want,
                                          spherical_space=spherical)
                        if level == "page"
                        else build_layout(self.workspace, dims=want,
                                          spherical_space=spherical))
                    # Always present, true or false. It was set only when
                    # the answer CAME from the store, so a freshly built one
                    # had no such key -- and a caller asking "which did I
                    # get?" could not tell "built" from "not reported".
                    cache[fresh]["from_store"] = False
                    try:
                        self.workspace.store.save_layout(
                            stored_key, json.dumps(cache[fresh]),
                            n=int(cache[fresh].get("n") or 0))
                    except Exception:               # noqa: BLE001
                        # A fit that cannot be saved is still a fit: this
                        # store is opened read-only by most callers.
                        pass
                # Bounded, and evicting the OLDEST rather than the largest:
                # the chunk-level fits are the expensive ones and are exactly
                # what a reader toggling `pages` wants back.
                while len(cache) > 4:
                    cache.pop(next(iter(cache)))
            self._send(200, cache[fresh])
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
            try:
                offset = int((params.get("offset") or ["0"])[0])
            except ValueError:
                offset = 0
            # Bounded, for the reason `k` is: a scroll that never stops must
            # not become a request that ranks the whole corpus twice.
            offset = max(0, min(offset, 2000))
            scope = (params.get("url") or [""])[0]
            coarse = (params.get("coarse") or ["1"])[0] != "0"
            try:
                budget = int((params.get("budget") or ["0"])[0])
            except ValueError:
                budget = 0
            if not query:
                self._send(400, {"error": "missing q"})
            else:
                self._send(200, search_payload(
                    self.workspace, query, k, offset=offset,
                    url=scope, coarse=coarse, budget=budget))
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

    # The background embedder. Started only when there is an embedder to
    # run, so a read-only workspace does not carry a thread that can never
    # have anything to do.
    global _EMBED_THREAD
    stop = threading.Event()
    if getattr(workspace, "embedder", None) is not None:
        _EMBED_THREAD = threading.Thread(
            target=_embed_forever, args=(workspace, stop),
            name="domvec-embed", daemon=True)
        _EMBED_THREAD.start()

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
