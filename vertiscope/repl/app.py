"""The REPL: one surface for browsing, retrieval and navigation.

Runs from the command line (``python -m vertiscope.repl``) or as a package
(``Repl(...).run()``). The loop is deliberately thin — it reads input, decodes
it to events, hands them to :class:`~vertiscope.repl.model.ReplState`, and paints
the result. All the behaviour lives in the state machine, which is why the
behaviour is testable and the loop barely is.

Two input modes share one state:

* **pointer** — clicks, drags and the wheel, decoded from the terminal;
* **command** — a typed line, for things a pointer cannot express (a query, a
  URL, a mode switch).

They are not alternatives. A session over a connection with no mouse reporting
loses the first and keeps everything, because every pointer gesture has a
keyboard equivalent (tab to focus, space to activate, arrows to scroll).
"""

from __future__ import annotations

import re
import shlex
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from ..address import ContentAddress
from ..markdown import (_RENDER_FORM, _looks_like_url,
                        MarkdownChunk, read_jsonl)
from .model import (
    Buffers,
    Document,
    KeyEvent,
    MouseEvent,
    ReplState,
    Widget,
    WidgetKind,
)
from .nav import NavResult, WebNav, attach_context, classify_controls
from .terminal import RawTerminal, decode_stream, paint

__all__ = ["Repl", "main"]

# Home the cursor and clear to end of screen. A live view redraws in
# place; one that scrolls away is a log, not a dashboard.
CLEAR = "[H[J"

HELP = """\
commands
  open <url|path|aid> load a page from the store, a jsonl file, an address
                      id (jumps to its line), or the web
  search <query>      three-form retrieval over every page ever folded;
                      each hit headed by its url and its r/l/s factors
  goto <n>            jump to document line n
  find <text>         scroll to the next line containing text
  controls            list pagination / menu / filter / search controls
  click <n>           activate line n (same as clicking it)
  type <n> <text>     type into the field on line n
  check <n>           toggle the checkbox on line n
  press <text>        press the control called <text>
  hover <n>           point at line n without pressing it
  wire [width]        draw the page as an ascii wireframe
  filter <text>       show only lines matching; `filter clear` to drop it
  resolution [chars]  how finely the page is cut, and drawn
  retrieve <url|q>    the one bar: a location is visited, anything else asked
  forget <url|here|all>  unrecord a page
  marks               show marked addresses
  where <n>           show the full address behind line n
  scroll <n>          scroll by n lines (negative to go up)
  back                browser back
  help / quit
"""


@dataclass
class Repl:
    """The interactive session. Buffers and state live here, not in globals."""

    state: ReplState = field(default_factory=ReplState)
    nav: WebNav = field(default_factory=WebNav)
    index: object = None          # ThreeFormIndex, optional
    store: object = None          # GraphStore, optional
    workspace: object = None      # Workspace — browsing writes through it
    colour: bool = True
    running: bool = True
    # The chunking hyperparameter, used when re-rendering a live DOM. Matches
    # the workspace default so a page browsed live chunks the way the same
    # page would have chunked if it had been scanned.
    context_window: int = 1200
    # Which design-space mechanisms the in-page sensor runs with. Switchable
    # from inside the session (`variant dedup on`), so two approaches can be
    # compared on the same live page rather than argued about.
    variants: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.state.on_activate = self._activate
        self._pending = ""      # an escape sequence split across two reads
        self._sensor = None
        self._live_chunks = {}
        self._sense_pass = 0
        # The page's trie, held across drains. One structure for the live
        # view, the store and the mirror -- see Workspace.sense, which holds
        # the same thing for the same reason.
        self._spine = None
        self._wire = None
        self._wire_top = 0
        self._filter = ""
        self._filter_kinds = frozenset()
        self._passes = []       # per-pass metrics, for `stats`
        self._exhausted = False  # the page said it has no more to give
        # The pagination trail. Verifying pagination means verifying a
        # *sequence*, and nothing was recording one: the checks measured the
        # document that happened to be open at the end, which is why a pager
        # that did nothing could pass by declaring itself exhausted.
        self._trail: List[str] = []      # page urls, in the order visited
        self._fired: List[tuple] = []    # (kind, label) actually enacted
        self._capped = False             # the extend loop hit its cap
        self._idle = 0                   # steps with no control and no move
        self._gates: dict = {}           # why pagers were not pressed
        # Content fingerprints seen anywhere this session. What makes
        # `crosspage` possible: a crawl re-sends the same nav and footer
        # on every page, and the receiver is the only party that knows.
        self._seen_content: set = set()

    # -- loading -----------------------------------------------------------
    def load_chunks(self, chunks: Sequence[MarkdownChunk], *,
                    url: str = "", title: str = "") -> None:
        self.state.document = Document.from_chunks(
            chunks, url=url or (chunks[0].url if chunks else ""), title=title)
        self.state.top = 0
        self.state.focus = None
        self.state.buffers.note(
            f"{len(self.state.document)} lines from {len(chunks)} chunk(s)")
        if self.state.document.url:
            self.state.buffers.visited(self.state.document.url)

    def load_jsonl(self, path) -> None:
        chunks = list(read_jsonl(path))
        self.load_chunks(chunks, title=Path(path).stem)

    def load_url_from_store(self, url: str) -> bool:
        """Rebuild a document from chunks already in the graph store.

        Browsing what has been scanned needs no browser, which is the point of
        keeping the markdown as a checkpoint rather than re-deriving it.
        """
        if self.store is None:
            return False
        # Through the stored spelling: a click resolves its target with
        # `canonical_url`, which turns `https://danluu.com` into
        # `https://danluu.com/` — and the page is on disk under the first.
        # Without this, clicking a link to a scanned site's home page said
        # "no local copy" and went to the network for a page already held.
        url = self.store.resolve_page(url) or url
        stored = [c for c in self.store.chunks(url)]
        if not stored:
            return False
        chunks = []
        for row in sorted(stored, key=lambda c: (c.xpath, c.part)):
            addresses = self.store.addresses_of(row.cid)
            texts = row.md.split("\n")
            if len(addresses) != len(texts):
                # Pairing is positional, so a mismatch attributes lines to the
                # wrong elements rather than merely dropping some. Skip the
                # chunk and say so: a page with one damaged chunk is still
                # browsable, and a line silently pointing at another element
                # is not something to render.
                self.state.buffers.note(
                    f"skipped {row.cid}: {len(texts)} line(s) vs "
                    f"{len(addresses)} anchor(s)")
                continue
            chunk = MarkdownChunk(url=row.url, xpath=row.xpath, part=row.part)
            from ..markdown import MarkdownLine
            for text, (address, _value) in zip(texts, addresses):
                stripped = text.lstrip(" ")
                depth = (len(text) - len(stripped)) // 2
                chunk.lines.append(MarkdownLine(depth, stripped, address))
            chunks.append(chunk)
        self.load_chunks(chunks, url=url, title=url)
        return True

    # -- live rendering ----------------------------------------------------
    def render_live(self, result: Optional[NavResult] = None) -> bool:
        """Rebuild the document from the browser's current DOM.

        Every live action used to report its result into the status line and
        leave the screen showing the page from before it: clicking "next"
        moved the browser and kept page one on screen, under a status line
        reading ``[ok] visit``. A correct-looking answer that is the wrong
        one — the same failure class as a purge that deletes nothing.

        ``WebNav.html()`` exists for exactly this ("the settled DOM, for
        re-running the pipeline after an action") and had no callers at all.

        It also stores. A page the session visits is scanned into the
        database and vectorised as it is read, because browsing and scanning
        are the same act: there is no second command that would have to be
        run afterwards to make what you just looked at retrievable.
        """
        if result is not None:
            self.state.buffers.note(str(result))
            if not result.ok:
                return False
        if not self.nav.live:
            return False
        html = self.nav.html()
        if not html:
            self.state.buffers.note("navigated, but the DOM came back empty")
            return False

        # Wait for the document to be the one we were asked for. Bing answers
        # `/search?q=…` with a redirect to `…&rdr=1&rdrig=…`; sensing straight
        # away read the pre-redirect document, filed its chunks under the
        # pre-redirect URL, and left every address pointing into a document
        # the browser had already replaced — 285 addresses of which 87
        # resolved, all of them correct for a page that no longer existed.
        self._await_document()
        url = self.nav.current_url or self.state.document.url
        return self.sense(url)

    # -- the live pipeline -------------------------------------------------
    def sense(self, url: str = "", prefetched=None) -> bool:
        """Fold the browser's current state through the in-page sensor.

        The REPL drives the real pipeline: the sensor is booted into the page
        the browser is actually on, and every navigation, click, scroll or
        keystroke drains whatever changed. Re-running a whole-document parse
        on this side after each action would cost the page on every keypress
        and would be a second reading of a document the sensor is already
        holding.

        The document accumulates. A drain returns what moved, and those chunks
        replace their previous versions by id, so scrolling a feed grows the
        view rather than replacing it — which is what a reader expects from
        scrolling, and what makes an infinite page browsable at all.
        """
        from ..sensing import Sensor

        driver = getattr(self.nav, "driver", None)
        if driver is None:
            return False
        url = url or self.nav.current_url

        if self._sensor is None or self._sensor.url != url:
            sensor = Sensor(driver, url, budget=self.context_window,
                            variants=self.variants,
                            known=self._known_digests())
            try:
                sensor.boot()
            except Exception as exc:  # noqa: BLE001
                # No script channel into the page — a driver whose CDP
                # connection has gone, or one that never had one. The sensor
                # is the only way to read a live DOM incrementally, so there
                # is nothing to degrade to here; the caller renders from
                # `page_source` instead. Reported, never silent.
                self.state.buffers.note(
                    f"sensor: {type(exc).__name__}: {exc}")
                self._sensor = None
                return False
            self._sensor = sensor
            self._live_chunks.clear()

        was = url
        if prefetched is not None:
            delta = prefetched
        else:
            delta = self._sensor.drain(self._sense_pass)
            # Look again if the first look came back empty.
            #
            # A gesture that navigates leaves the old handle in a document
            # that no longer exists; the next call re-boots into the new one,
            # and that boot's first drain arrives before the fold has run, so
            # it is empty. Reading that as "the page is empty" cleared the
            # view and left a click reporting `0 lines from 0 chunk(s)` on a
            # page that had 361 units in it.
            #
            # This is not the sensor waiting to be finished -- it never is,
            # and it is not asked to be. It is the reader looking again,
            # which is the only thing that ever decides when to look.
            import time as _t
            for _ in range(6):
                if delta.units or delta.removed_addresses:
                    break
                _t.sleep(0.35)
                delta = self._sensor.drain(self._sense_pass)
        self._sense_pass += 1
        # The drain is what learns the page has become a different page — an
        # enacted pager that navigates, a route change, a redirect. Reading
        # the address back afterwards is what keeps the new page's chunks
        # from being filed under the old page's URL.
        if self._sensor.url and self._sensor.url != url:
            url = self._sensor.url
            self._live_chunks.clear()
        self._seen_content.update(delta.contents)
        # Through the trie. The sensor supplies addressed units and the
        # renderer partitions them, so what the REPL shows is what the store
        # holds and what a full scan would have produced -- one structure,
        # one serialiser. Live rendering used to come from a separate JS
        # chunker, which is how the same page could read differently
        # depending on which path had opened it.
        if self._spine is None or self._spine.url != url:
            from ..stream import StreamingScan
            self._spine = StreamingScan(url, context_window=1200)
        update = self._spine.absorb(delta.units, delta.passno,
                                    moved=delta.moved_addresses,
                                    removed=delta.removed_addresses)
        dirty = self._spine.dirty_chunks(update)
        for chunk in dirty:
            self._live_chunks[chunk.cid] = chunk
        # A departed address can empty a chunk that still has a cid here.
        # Anything the renderer no longer produces for a touched subtree is
        # retired by cid, which is what the store is keyed by.
        gone = []
        if update.delta.removed:
            surviving = {c.cid for c in update.all_chunks}
            gone = [cid for cid, c in self._live_chunks.items()
                    if c.url == url and cid not in surviving]
        for cid in gone:
            self._live_chunks.pop(cid, None)

        # Straight to the database, as a delta. The workspace owns frequency
        # rows, embeddings, the graph and the markdown mirror together, so a
        # page becomes retrievable in the same motion that shows it.
        store_ms = 0.0
        if self.workspace is not None and (dirty or gone):
            import time as _t
            started = _t.perf_counter()
            try:
                self.workspace.ingest_chunks(
                    url, dirty, complete=False,
                    removed=gone, title=url)
            except Exception as exc:  # noqa: BLE001 - a write must not end a session
                self.state.buffers.note(f"store: {type(exc).__name__}: {exc}")
            store_ms = (_t.perf_counter() - started) * 1000
        delta.store_ms = store_ms
        self._passes.append(delta)

        self.state.buffers.note(
            f"+{delta.changed} chunk(s), {delta.lines} line(s), "
            f"{delta.drain_ms:.0f} ms sense, {store_ms:.0f} ms store"
            + (f", {delta.stats.get('deduped', 0)} deduped"
               if self.variants.get("dedup") else ""))
        # Reading position survives the re-render. The document grows beneath
        # the reader as they scroll, and a feed that appends must not yank
        # the view back to the top (OBJECT_MODEL 7.6) — which is exactly what
        # rebuilding the document did, so every extension undid the reading
        # it was supposed to enable. A genuine page change is the one case
        # where starting at the top is right.
        # The wireframe, if one is open, takes the same delta.
        if getattr(self, "_wire", None) is not None:
            touched = (update.delta.added + update.delta.changed
                       + update.delta.moved + update.delta.removed)
            redrawn = self._repaint_wire(touched)
            if redrawn:
                # Printed, not noted. The status line holds one message and
                # the gesture that caused the delta writes its own into it
                # immediately after, so a note here is written and then lost.
                print(f"  wireframe: {redrawn} band(s) redrawn of "
                      f"{len(self._wire.bands)}  "
                      f"({len(touched)} address(es) changed)", flush=True)

        keep_top = self.state.top if url == was else 0
        self.load_chunks(list(self._live_chunks.values()), url=url, title=url)
        if keep_top:
            self.state.top = min(keep_top, self.state.max_top)
        return True

    # -- activation --------------------------------------------------------
    def _activate(self, widget: Widget) -> None:
        """What a click on a link or button does.

        Order matters: a link whose target is already in the store opens from
        the store, and only otherwise touches the network. Browsing scanned
        content must never depend on the site still being up.
        """
        address = widget.address
        if address is None:
            return

        # A stored page opens from the store, so reading scanned content
        # never depends on the site still being up. The target comes from the
        # *address*, not from the label: a link's label used to be its href,
        # and is now the anchor's own words, so parsing the label as a url
        # sent `click` to `html.duckduckgo.com/html/[How%20should%20you...`
        # -- the title of the result, resolved as a relative path.
        if widget.kind in (WidgetKind.LINK, WidgetKind.IMAGE):
            from ..graphstore import canonical_url

            here = self.state.document.url
            raw = ""
            if self.store is not None:
                found = self.store.address(address.aid)
                if found is not None:
                    stored = (found[1] or "").strip()
                    # Only if it IS one. A link line's stored value is the
                    # anchor's words, not its href, and taking those as a
                    # target resolved the result's title against the current
                    # host and "opened" the empty page that came back -- so a
                    # click reported success and showed nothing.
                    if _looks_like_url(stored):
                        raw = stored
            if not raw and _looks_like_url(widget.label.strip("<>")):
                raw = widget.label.strip("<>")
            target = canonical_url(raw, here) if raw else ""
            if target and self.load_url_from_store(target):
                self.state.buffers.note(f"opened {target} (from store)")
                return

        # Otherwise the page decides. Pressing the real element is what makes
        # a redirect, a script-driven route change or a form submission behave
        # the way it does for anyone else reading the page -- and it is the
        # only path that reaches a control inside a shadow root.
        self.render_live(self._gesture(address, "click"))

    def _gesture(self, address, kind: str, text: str = "") -> "NavResult":
        """Every reader-initiated action goes through the page's own executor.

        One dispatcher, so there is no second path with different reach that
        might quietly answer first. `refused` sits inside it and applies to
        this exactly as it applies to anything else that asks.
        """
        from .nav import NavResult

        sensor = getattr(self, "_sensor", None)
        if sensor is None:
            return NavResult(False, kind, "no sensor attached")
        try:
            if kind == "click":
                out = sensor.press(address)
            elif kind == "type":
                out = sensor.fill(address, text, submit=True)
            elif kind == "check":
                out = sensor.toggle(address)
            else:
                return NavResult(False, kind, f"unknown gesture {kind!r}")
        except Exception as exc:  # noqa: BLE001 - a gesture must not end a session
            return NavResult(False, kind, f"{type(exc).__name__}: {exc}")
        if out["failed"]:
            why = ", ".join(f"{k}:{v}" for k, v in out["failed"])
            return NavResult(False, kind, why)
        return NavResult(True, kind, text or "pressed", url=out.get("url", ""))

    # -- commands ----------------------------------------------------------
    def command(self, line: str) -> bool:
        """Run one typed command. Returns False to exit."""
        line = line.strip()
        if not line:
            return True
        self.state.buffers.remember(line)
        try:
            parts = shlex.split(line)
        except ValueError:
            parts = line.split()
        verb, args = parts[0].lower(), parts[1:]
        handler = getattr(self, f"_cmd_{verb}", None)
        if handler is None:
            self.state.buffers.note(f"unknown command {verb!r} — try 'help'")
            return True
        try:
            return handler(args) is not False
        except Exception as exc:  # noqa: BLE001 — a REPL must not die on a typo
            self.state.buffers.note(f"{type(exc).__name__}: {exc}")
            return True

    def _line_arg(self, args: Sequence[str]) -> Optional[Widget]:
        if not args:
            # No number means "the line I am on". `find` moves the focus and
            # a gesture acts on it -- which is how a reader works a terminal,
            # and the only way to drive one without knowing in advance which
            # line a result will land on.
            if self.state.focus is not None and                     0 <= self.state.focus < len(self.state.document):
                return self.state.document.lines[self.state.focus]
            self.state.buffers.note("need a line number, or a focused line")
            return None
        try:
            n = int(args[0])
        except ValueError:
            self.state.buffers.note(f"not a line number: {args[0]!r}")
            return None
        if not 0 <= n < len(self.state.document):
            self.state.buffers.note(f"line {n} out of range")
            return None
        return self.state.document.lines[n]

    def _cmd_help(self, args) -> bool:
        self.state.buffers.note(HELP.strip().replace("\n", " | ")[:200])
        print(HELP)
        return True

    def _cmd_quit(self, args) -> bool:
        self.running = False
        return False

    _cmd_exit = _cmd_quit





    # A location, as opposed to a question. Deliberately generous about what
    # counts: guessing wrong toward a search is recoverable in one keystroke,
    # and guessing wrong toward a navigation is not, so the ambiguous middle
    # goes to the question and offers the location as the first row.
    _LOOKS_LIKE_LOCATION = __import__("re").compile(
        r"""^(?:
              [a-zA-Z][a-zA-Z0-9+.\-]*://\S+$      # a scheme
            | (?:www\.)?[a-zA-Z0-9\-]+(?:\.[a-zA-Z0-9\-]+)+(?:[/:?#]\S*)?$
            | localhost(?::\d+)?(?:[/?#]\S*)?$
            )""", __import__("re").X)

    @classmethod
    def looks_like_location(cls, text: str) -> bool:
        text = (text or "").strip()
        if not text or " " in text:
            return False
        return bool(cls._LOOKS_LIKE_LOCATION.match(text))

    @staticmethod
    def _row_template(trie, url: str):
        """The repeating shape a results page uses for one result.

        Not a template we wrote. A list page says what a row looks like by
        repeating it: group every element by the sequence of render classes
        hanging under it, and the shape that recurs is the row. Measured on
        real result pages, shapes collapse hard — 15 distinct shapes for 86
        lines, 29 for 290 — because that is what a list *is*.

        Taking it from the page rather than declaring it is what lets stored
        chunks be rendered in the site's own form instead of ours.
        """
        import collections

        leaves = [n.address for n in (trie.leaves() if trie else [])
                  if n.address is not None and n.address.url == url]
        if not leaves:
            return None, 0

        # Across ancestor depths, not at one. A row is a container, and how
        # far above its content that container sits is the site's business:
        # on one results page the row is the element holding the text, on
        # another it is three levels up with the title, the url and the
        # snippet each in their own child. Fixing the depth found the shape
        # on one page and nothing at all on the next, which is exactly the
        # per-site brittleness this design exists to avoid.
        best = (None, 0)
        for depth in range(2, 7):
            groups: dict = collections.defaultdict(list)
            for address in leaves:
                path = address.path()
                if len(path) <= depth + 2:
                    continue
                groups[path[:-(depth + 2)]].append(address.tag)
            shapes: collections.Counter = collections.Counter()
            for classes in groups.values():
                if 2 <= len(classes) <= 12:
                    shapes[tuple(classes)] += 1
            for shape, count in shapes.most_common(1):
                # More repeats wins; a tie goes to the longer shape, because
                # the longer one describes more of the row.
                if count >= 3 and (count, len(shape)) > (best[1], len(best[0] or ())):
                    best = (shape, count)
        return best

    @staticmethod
    def _through_template(shape, title: str, url: str, snippet: str,
                          mark: str, hit=None) -> "list":
        """One stored hit, drawn in the shape the live page uses for a row.

        The reader sees one results page. `mark` is the only thing added,
        because a reader has to be able to tell what came from where — but
        the *form* is the site's, not ours.
        """
        from ..markdown import MarkdownLine

        fields = [title, url, snippet]
        lines = []
        used = 0
        for cls in (shape or ("link", "link", "text")):
            value = fields[used] if used < len(fields) else ""
            used += 1
            if not value:
                continue
            form = _RENDER_FORM.get(cls, _RENDER_FORM["text"])
            drawn = form(value, value, "")
            if drawn is None:
                continue
            # Addressed, not decorative. A melded row names the stored node
            # it came from, so a reader can act on it exactly as on a live
            # one -- an unaddressed line would look like a result and behave
            # like prose, which is the worst of both.
            here = None
            if hit is not None:
                here = ContentAddress(hit.url, getattr(hit, "xpath", "/html"),
                                      cls, "meld|local")
            lines.append(MarkdownLine(1, drawn, here))
            if used >= len(fields):
                break
        if lines:
            lines[0] = MarkdownLine(1, lines[0].text + f"   {mark}",
                                    lines[0].address)
        return lines

    def _cmd_retrieve(self, args) -> bool:
        """The one bar. A location is visited; anything else is a question.

        `open` and `search` survive as aliases for scripting, but a reader
        has one input, because a browser needs one: the distinction between
        "go here" and "find this" is the machine's problem, not theirs.

        A question fires *both* retrievals — the triple product over stored
        chunks, and a live DuckDuckGo visit read structure-natively — and the
        stored hits are drawn into the live page's own row shape rather than
        stacked in a pane beside it.
        """
        if not args:
            self.state.buffers.note("retrieve: a url, or a question")
            return True
        text = " ".join(args).strip()

        if self.looks_like_location(text):
            return self._cmd_open([text])

        local = []
        self._refresh_index()
        if self.index is not None:
            try:
                local = self.index.search(text, k=8)
            except Exception as exc:  # noqa: BLE001
                self.state.buffers.note(f"local: {type(exc).__name__}: {exc}")

        driver = getattr(self.nav, "driver", None)
        if driver is None:
            self.state.buffers.note(
                f"{len(local)} local hit(s); no browser for the live half")
            return self._cmd_search(args)

        import time as _t
        import urllib.parse

        from ..sensing import Sensor
        from ..stream import StreamingScan

        engine = ("https://html.duckduckgo.com/html/?q="
                  + urllib.parse.quote_plus(text))
        driver.set_page_load_timeout(45)
        driver.get(engine)
        _t.sleep(0.9)
        sensor = Sensor(driver, engine, budget=1200)
        sensor.boot()
        _t.sleep(0.6)
        self._sensor = sensor
        spine = StreamingScan(engine, context_window=1200)
        sp = sensor.drain(0)
        update = spine.absorb(sp.units, sp.passno,
                              removed=sp.removed_addresses,
                              moved=sp.moved_addresses)
        chunks = list(update.all_chunks or spine.dirty_chunks(update))
        if not chunks:
            from ..markdown import render_trie
            chunks = render_trie(spine.trie, context_window=1200)

        shape, repeats = self._row_template(spine.trie, engine)

        # Interleaved, not appended. A separate pane would be a second
        # results list the reader has to reconcile; melded, there is one.
        melded = list(chunks)
        for rank, hit in enumerate(local):
            body = (hit.markdown or "").split("\n")
            title = body[0].strip() if body else hit.url
            snippet = " ".join(x.strip() for x in body[1:3]).strip()
            lines = self._through_template(shape, title, hit.url, snippet,
                                           "local", hit=hit)
            if not lines:
                continue
            from ..markdown import MarkdownChunk
            row = MarkdownChunk(url=hit.url, xpath=hit.xpath, part=900 + rank)
            row.lines = lines
            melded.insert(min(rank * 3 + 1, len(melded)), row)

        self._spine = spine
        self.load_chunks(melded, title=engine)
        self.state.buffers.note(
            f"{len(local)} local + {len(chunks)} live chunk(s); "
            f"row shape {'x'.join(shape) if shape else 'none'} "
            f"({repeats} repeats)")
        return True

    # `open` and `search` stay, for scripts and for muscle memory.
    _cmd_go = _cmd_retrieve






    def _cmd_browser(self, args) -> bool:
        """Attach a live browser to this REPL.

        The REPL is a browser, so it needs one. Until this existed the only
        way to get a driver in was to construct the REPL from a script, which
        left a headless `--command` session reporting "needs a live browser"
        instead of reading the page. This is the one missing seam.

        It reads nothing into the trie by itself: the driver it attaches is
        what `open` later folds a page through, and every address the session
        can reach afterwards arrives by that route.

        `browser` boots headless, `browser show` boots headful.
        """
        from ..browser import build_driver
        from ..config import load_config

        headless = not (args and args[0].lower() in ("show", "headful", "gui"))
        existing = getattr(self.nav, "driver", None)
        if existing is not None:
            try:
                existing.quit()
            except Exception:  # noqa: BLE001
                pass
        driver = build_driver(load_config(), headless=headless)
        driver.set_page_load_timeout(45)
        self.nav.driver = driver
        self.state.buffers.note(
            f"browser attached ({'headless' if headless else 'headful'})")
        print(f"browser attached ({'headless' if headless else 'headful'})",
              flush=True)
        return True


    def _cmd_open(self, args) -> bool:
        if not args:
            return True
        target = args[0]
        path = Path(target)
        if path.exists():
            self.load_jsonl(path)
            return True
        if self.load_url_from_store(target):
            self.state.buffers.note(f"opened {target} (from store)")
            return True
        if self._open_address(target):
            return True
        self.render_live(self.nav.visit(target))
        return True

    def _open_address(self, target: str) -> bool:
        """Open the page an address belongs to, focused on its line.

        `where` prints an `aid`, and until this existed the id could not be
        given back to anything — not even to the REPL that printed it. The
        address is the singular output type; a tool that emits one and
        accepts none has a one-way interface.
        """
        if self.store is None or not target:
            return False
        found = self.store.address(target)
        if found is None:
            return False
        address, _value = found
        if not self.load_url_from_store(address.url):
            self.state.buffers.note(f"{target}: no stored copy of {address.url}")
            return False
        for widget in self.state.document.lines:
            if widget.address is not None and widget.address.aid == target:
                self.state.scroll_to_line(widget.line)
                self.state.focus = widget.line
                self.state.buffers.note(
                    f"{target} -> line {widget.line} of {address.url}")
                return True
        self.state.buffers.note(f"{target}: in {address.url}, line not shown")
        return True

    def _refresh_index(self) -> None:
        """Rebuild the retrieval index when the store has grown under it.

        The index is built once, at start, from whatever the store held then.
        Browsing writes through the workspace, so a page read during a
        session lands in the store -- and stayed invisible to retrieval,
        because the index was a snapshot of the store as it was before the
        page existed. Asking for a word from a page visited two minutes
        earlier answered `no hit`, which is the store and the index
        disagreeing rather than the query failing.
        """
        if self.workspace is None or self.store is None:
            return
        try:
            count = len(list(self.store.chunks()))
        except Exception:  # noqa: BLE001 - a count must not end a session
            return
        if self.index is not None and count == getattr(self, "_indexed", -1):
            return
        try:
            from ..search import ThreeFormIndex

            self.workspace.flush_vectors()
            self.index = ThreeFormIndex(self.store, self.workspace.freq).build()
            self._indexed = count
        except Exception as exc:  # noqa: BLE001
            self.state.buffers.note(f"index: {type(exc).__name__}: {exc}")

    def _cmd_search(self, args) -> bool:
        self._refresh_index()
        if self.index is None:
            self.state.buffers.note("no index attached")
            return True
        query = " ".join(args)
        hits = self.index.search(query, k=20)
        if not hits:
            self.state.buffers.note(f"no hit for {query!r} (a factor vetoed all)")
            return True
        chunks = []
        from ..markdown import MarkdownLine

        for hit in hits:
            chunk = MarkdownChunk(url=hit.url, xpath=hit.xpath)
            addresses = self.index.addresses_for(hit.cid)
            # Every hit says where it came from, and why it ranked.
            #
            # This is store-wide retrieval: the hits are drawn from every page
            # ever folded, while `load_chunks` takes the document url from the
            # FIRST chunk alone. So the screen named one page and showed
            # results from twenty, and nothing on the screen said which line
            # belonged to which -- the reader could not tell a hit from their
            # own last scan from a hit from something read a week ago.
            #
            # The three factors travel with it because one score cannot say
            # why: all-standing-no-text and all-text-no-standing are different
            # answers to the same question.
            head = "%s   r%.2f l%.2f s%.2f" % (
                hit.url, hit.rank, hit.lexical, hit.semantic)
            chunk.lines.append(
                MarkdownLine(0, head, addresses[0][0] if addresses else None))
            for text, (address, _value) in zip(hit.markdown.split("\n"), addresses):
                stripped = text.lstrip(" ")
                depth = (len(text) - len(stripped)) // 2
                chunk.lines.append(MarkdownLine(depth + 1, stripped, address))
            chunks.append(chunk)
        self.load_chunks(chunks, title=f"search: {query}")
        pages = len({hit.url for hit in hits})
        self.state.buffers.note(
            "%d hit(s) for %r across %d page(s)" % (len(hits), query, pages))
        return True

    def _cmd_goto(self, args) -> bool:
        widget = self._line_arg(args)
        if widget is not None:
            self.state.scroll_to_line(widget.line)
            self.state.focus = widget.line
        return True

    def _cmd_find(self, args) -> bool:
        needle = " ".join(args).lower()
        if not needle:
            return True
        start = (self.state.focus or self.state.top) + 1
        lines = self.state.document.lines
        for offset in range(len(lines)):
            index = (start + offset) % len(lines)
            if needle in lines[index].label.lower():
                self.state.scroll_to_line(index)
                self.state.focus = index
                self.state.buffers.note(f"found at line {index}")
                return True
        self.state.buffers.note(f"{needle!r} not found")
        return True

    def _cmd_controls(self, args) -> bool:
        # `controls()`, not `lines`: a sentence with two links in it is one
        # line and three addresses, and the merged ones are hit targets on
        # that line rather than lines of their own. Reading `lines` here lost
        # every link the render folded into its prose.
        pairs = [(w.address, w.label) for w in self.state.document.controls()
                 if w.address is not None]
        # A link's own label is its href. The words that name a control live
        # on the surrounding text lines, so the two are joined by xpath before
        # anything is classified — see `attach_context`.
        texts = [(w.address.xpath, w.label) for w in lines if not w.interactive]
        roles = classify_controls(attach_context(pairs, texts))
        summary = " ".join(f"{name}={len(items)}"
                           for name, items in roles.items() if items)
        self.state.buffers.note(summary or "no controls on this page")
        for name, items in roles.items():
            if not items or name == "other":
                continue
            print(f"\n{name}:")
            for address, label, context in items[:10]:
                # The visible text names the control; the href only says where
                # it goes, and for a link the label *is* the href.
                print(f"  {(context or label)[:58]:58s} {address.xpath[:58]}")
        return True

    def _cmd_click(self, args) -> bool:
        widget = self._line_arg(args)
        if widget is not None:
            self.state.focus = widget.line
            self.state._activate(widget)
        return True

    def _cmd_resolution(self, args) -> bool:
        """`resolution [chars]` — how finely the page is cut, and drawn.

        One knob, because it is genuinely one thing. `context_window` is the
        chunk budget: it decides how much of the document each stored chunk
        holds, which decides what a retrieval hit returns, and it decides how
        much of the page a rendered unit covers. Coarser chunks mean coarser
        retrieval and a coarser picture, and that is not a coincidence to be
        hidden behind two settings that can disagree.

        Given no argument it reports. The page is re-read at the new setting
        so the change is visible rather than pending.
        """
        if not args:
            self.state.buffers.note(
                f"resolution {self.context_window} chars per chunk"
                f"  (wire width {getattr(self, '_wire_width', 0) or self.state.cols})")
            return True
        try:
            value = int(args[0])
        except ValueError:
            self.state.buffers.note("resolution needs a number of characters")
            return True
        self.context_window = max(120, min(20000, value))

        # Re-rendered, not re-scanned. The trie is resolution-independent --
        # it holds addresses and values, and how those are cut into chunks is
        # a decision made downstream of it. Clearing the spine and draining
        # again asked the sensor for deltas on a page that had not changed,
        # so it correctly reported nothing and the view went empty.
        #
        # This is the property of having one structure and many projections:
        # changing how finely the page is cut costs a render, not a visit.
        spine = getattr(self, "_spine", None)
        if spine is not None and spine.trie is not None:
            from ..markdown import render_trie

            spine.context_window = self.context_window
            chunks = render_trie(spine.trie,
                                 context_window=self.context_window,
                                 memo=getattr(spine, "render_memo", None))
            self._live_chunks = {c.cid: c for c in chunks}
            self._styles = None
            keep = self.state.top
            self.load_chunks(list(self._live_chunks.values()),
                             url=spine.url, title=spine.url)
            self.state.top = min(keep, self.state.max_top)
            if self.workspace is not None:
                try:
                    self.workspace.ingest_chunks(spine.url, chunks,
                                                 complete=True, title=spine.url)
                except Exception as exc:  # noqa: BLE001
                    self.state.buffers.note(f"store: {type(exc).__name__}: {exc}")
        self.state.buffers.note(
            f"resolution {self.context_window} chars per chunk"
            f" — {len(self._live_chunks)} chunk(s)")
        return True

    def _filtered(self, line):
        """A wireframe line, or None when the active filter excludes it.

        Applied at draw time rather than by rebuilding the page, so clearing
        a filter costs nothing and the underlying structure is never the
        filtered thing. A filter is a way of looking, not a way of storing.
        """
        active = getattr(self, "_filter", "")
        if not active:
            return line
        kinds = getattr(self, "_filter_kinds", frozenset())
        if kinds:
            tags = {a.tag for a in line.addresses if a is not None}
            return line if tags & kinds else None
        return line if active.lower() in line.text.lower() else None

    def _forget_session(self, url: str = "") -> None:
        """Drop the session's own copies of a page. `url` empty means all.

        The store is not the only place a visit is recorded. This process
        holds the chunks it is showing, the trie they were folded from, the
        content fingerprints it has seen and the trail of urls it walked --
        and every one of those answers "was this read?" for as long as the
        session lives. A `forget` that cleared the database and left them
        would be a `forget` that works until someone scrolls up.
        """
        if not url:
            self._live_chunks.clear()
            self._spine = None
            self._seen_content.clear()
            self._trail.clear()
            self._passes.clear()
            return
        gone = [cid for cid, c in self._live_chunks.items() if c.url == url]
        for cid in gone:
            self._live_chunks.pop(cid, None)
        if self._spine is not None and getattr(self._spine, "url", "") == url:
            self._spine = None
        self._trail = [u for u in self._trail if u != url]

    def _cmd_forget(self, args) -> bool:
        """`forget <url>` · `forget here` · `forget all` — unrecord a page.

        Browsing writes through the workspace, which is what makes a page
        read a page retrievable. The other half of that bargain is being
        able to take it back, and there was no way to: `Workspace.purge`
        existed and only the CLI could reach it, so the REPL could record a
        page and could not un-record one.

        A tool that keeps everything you look at and offers no way to forget
        is a tool you have to be careful in front of, which is the opposite
        of what this is for.
        """
        if self.workspace is None:
            self.state.buffers.note("no workspace attached")
            return True
        target = " ".join(args).strip()
        if not target:
            self.state.buffers.note(
                "forget <url> | forget here | forget all")
            return True
        if target in ("here", "this", "."):
            target = self.state.document.url or ""
            if not target:
                self.state.buffers.note("no page open")
                return True
        try:
            if target == "all":
                self.workspace.purge()
                self._forget_session()
                self.state.buffers.note("forgot everything in this workspace")
            else:
                # Resolve to the stored spelling *before* purging, because
                # purging is what makes it unresolvable. A url typed with its
                # campaign tag still attached, or with a trailing slash the
                # store does not have, reaches the same page -- and the
                # in-memory copies have to be dropped by the same key the
                # store was, or `forget` clears the database and leaves the
                # page on the screen.
                stored = self.workspace.page_url(target)
                self.workspace.purge(target)
                self._forget_session(stored)
                # Said out loud, because a promise with an exception in it is
                # only kept if the exception is stated. A page that was
                # already on disk when this session started is gone from
                # every index and still present as bytes in `graph.kuzu`
                # until the store is written out again -- kuzu has no
                # vacuum. `forget all` removes the directory and so has no
                # such gap.
                self.state.buffers.note(
                    f"forgot {target} — indexes clear; bytes may remain in "
                    "graph.kuzu until 'forget all'")
        except Exception as exc:  # noqa: BLE001
            self.state.buffers.note(f"forget: {type(exc).__name__}: {exc}")
            return True
        # The index still holds what was just dropped until it is rebuilt.
        self._indexed = -1
        self._refresh_index()
        return True

    def _cmd_filter(self, args) -> bool:
        """`filter <text>` · `filter kind link button` · `filter clear`.

        Narrows what the page shows without changing what it is. Text
        matches a line's content; `kind` matches render classes, so
        `filter kind link` is "show me what I can follow" and
        `filter kind field slider` is "show me what I can fill in".

        A browser's filters are the site's own controls, and those are still
        there to press -- this is the reader's own, over whatever is drawn.
        """
        if not args or args[0].lower() in ("clear", "off", "none"):
            self._filter = ""
            self._filter_kinds = frozenset()
            self.state.buffers.note("filter cleared")
            return True
        if args[0].lower() in ("kind", "kinds", "k"):
            from ..aam import RENDER_CLASS

            wanted = {a.lower() for a in args[1:]}
            known = set(RENDER_CLASS.values())
            unknown = wanted - known
            if unknown:
                self.state.buffers.note(
                    "unknown kind(s): " + ", ".join(sorted(unknown))
                    + " — known: " + ", ".join(sorted(known)))
                return True
            self._filter_kinds = frozenset(wanted)
            self._filter = "kind " + " ".join(sorted(wanted))
            self.state.buffers.note(f"filter: {self._filter}")
            return True
        self._filter_kinds = frozenset()
        self._filter = " ".join(args)
        self.state.buffers.note(f"filter: {self._filter!r}")
        return True

    def _repaint_wire(self, changed) -> int:
        """Redraw the bands a delta touched, and only those.

        The delta reaches the drawing. The fold emits what moved, the trie
        absorbs it, the renderer partitions it -- and the wireframe used to
        throw all of that away and draw the page again, which made the one
        view that is supposed to feel live the only stage whose cost tracked
        the page rather than the change.

        Two things are kept proportional. Geometry is re-measured for the
        touched elements only, which is the expensive part because it is a
        round trip that settles layout. And only the affected bands are
        rebuilt, by running the band pipeline over just those elements
        instead of over the page.

        Content that is *new* -- a menu opening, a feed appending -- has no
        band yet, so its band is built and placed by where it is on the page.
        Handling only changes and not arrivals was the first version's bug,
        and arrivals are the case a live view exists for.
        """
        frame = getattr(self, "_wire", None)
        sensor = getattr(self, "_sensor", None)
        spine = getattr(self, "_spine", None)
        if frame is None or sensor is None or spine is None or spine.trie is None:
            return 0
        owners = {a.xpath.split("/text()")[0] for a in changed if a is not None}
        if not owners:
            return 0

        from ..markdown import _RENDER_FORM
        from ..style import StyleMap
        from ..wireframe import render_wireframe

        styles = getattr(self, "_styles", None) or StyleMap()
        payload = sensor.styles([type("A", (), {"xpath": x})() for x in owners])
        styles.absorb(sorted(owners), payload)
        self._styles = styles

        # The drawn units for the touched elements, from the trie directly.
        # Going through `render_trie` here would re-chunk the page, which is
        # the cost this method exists to avoid.
        units = []
        for leaf in spine.trie.leaves():
            address = leaf.address
            if address is None:
                continue
            if address.xpath.split("/text()")[0] not in owners:
                continue
            form = _RENDER_FORM.get(address.tag)
            text = form(leaf.value, leaf.value, "", "") if form else leaf.value
            if text and text.strip():
                units.append((address, text, address.tag))
        if not units:
            return 0

        patch = render_wireframe(units, styles,
                                 width=getattr(self, "_wire_width", 0)
                                 or self.state.cols)
        if not patch.bands:
            return 0

        known = {owner: i for i, band in enumerate(frame.bands)
                 for owner in band.owners}
        redrawn = 0
        for band in patch.bands:
            index = next((known[o] for o in band.owners if o in known), None)
            if index is not None:
                frame.bands[index] = band
            else:
                # New content. Placed by where it sits, so a menu that opened
                # under its button appears under its button.
                box = next((styles.get(o) for o in band.owners
                            if styles.get(o) is not None), None)
                at = len(frame.bands)
                if box is not None:
                    for i, existing in enumerate(frame.bands):
                        other = next((styles.get(o) for o in existing.owners
                                      if styles.get(o) is not None), None)
                        if other is not None and other.y > box.y:
                            at = i
                            break
                frame.bands.insert(at, band)
                known = {owner: i for i, b in enumerate(frame.bands)
                         for owner in b.owners}
            redrawn += 1
        self._wire_lines = frame.lines
        return redrawn

    def _cmd_wire(self, args) -> bool:
        """Draw the current page as a wireframe. `wire [width]`.

        The other projection. `markdown` is what a chunk means, one unit per
        line, flattened for the index; this is what the page looks like, with
        rows drawn as rows at the widths the page gave them. Same trie, same
        addresses, same glyphs -- only the arrangement differs, which is the
        whole point of them being two renderers over one structure rather
        than one format asked to do both jobs.
        """
        from ..style import StyleMap
        from ..wireframe import render_wireframe

        spine = getattr(self, "_spine", None)
        sensor = getattr(self, "_sensor", None)
        if spine is None or spine.trie is None:
            self.state.buffers.note("wire needs an open page")
            return True
        # The canvas is as wide as the page wants; the terminal is a window
        # onto it. Squeezing a three-column layout into 80 columns until it
        # fits is not drawing the page, it is drawing a different page.
        canvas = int(args[0]) if args and args[0].isdigit() else             getattr(self, "_wire_width", 0) or self.state.cols
        self._wire_width = canvas
        unicode_art = any(a in ("unicode", "u") for a in args)

        # The *rendered* units, not the raw leaves.
        #
        # Both projections start from the same place or they are two
        # pipelines again. Reading leaves directly meant the wireframe missed
        # every merge markdown does -- an anchor's href and its words are two
        # leaves and one line -- so every link drew twice, once as
        # `[/tag/love/]` and once as `[love]`, side by side.
        #
        # `render_trie` is where a leaf becomes a drawn unit: glyphs applied,
        # wrappers suppressed, labels joined. What differs between the two
        # projections is the arrangement, and only that.
        from ..markdown import render_trie

        # Through the spine's memo: this runs on every draw, and a page the
        # user is only scrolling has not changed at all. The trie decides
        # what is stale (`exact_hash`), so the wireframe pays for the part of
        # the page that moved and not for the part it is looking at.
        drawn = []
        for chunk in render_trie(spine.trie,
                                 context_window=self.context_window,
                                 memo=getattr(spine, "render_memo", None)):
            for line in chunk.lines:
                if line.address is not None and line.text.strip():
                    drawn.append((line.address, line.text, line.address.tag))

        styles = self._styles = getattr(self, "_styles", None) or StyleMap()
        if sensor is not None:
            wanted = styles.missing(a.xpath for a, _t, _k in drawn)
            if wanted:
                import time as _t2
                started = _t2.perf_counter()
                # Measured in one crossing, for the page, once. Reading a rect
                # settles layout, so this is never done inside the fold.
                payload = sensor.styles(
                    [type("A", (), {"xpath": x})() for x in wanted])
                styles.absorb(wanted, payload)
                self.state.buffers.note(
                    f"measured {len(wanted)} box(es) in "
                    f"{(_t2.perf_counter() - started) * 1000:.0f} ms")

        frame = render_wireframe(drawn, styles, width=canvas,
                                 unicode=unicode_art)
        self._wire = frame
        lines = frame.lines
        self._wire_lines = lines

        view = min(self.state.cols, canvas)
        widest = max((len(l.text) for l in lines), default=0)
        left = max(0, min(self.state.left, max(0, widest - view)))
        self.state.left = left
        rule = ("=" if not unicode_art else "═") * view
        print()
        print(rule)
        print(f" {spine.url[:view - 2]}")
        print(rule)
        # The wireframe has its own line space -- a page drawn in columns is
        # not the same number of lines as the same page drawn one unit per
        # line -- so it keeps its own vertical position. Sharing `state.top`
        # scrolled the markdown document and left the drawing at the top.
        top = max(0, min(getattr(self, "_wire_top", 0),
                         max(0, len(lines) - self.state.rows)))
        self._wire_top = top
        shown = [self._filtered(line) for line in lines]
        shown = [l for l in shown if l is not None]
        for line in shown[top:top + self.state.rows]:
            print(line.text[left:left + view])
        print()
        more = "" if widest <= view else             f"  cols {left + 1}-{min(left + view, widest)}/{widest}"
        active = "" if not self._filter else f", filter {self._filter!r}"
        self.state.buffers.note(
            f"wireframe {len(shown)}/{len(lines)} line(s), canvas {canvas}"
            f"{more}{active}, {len(styles)} box(es), {len(frame.bands)} band(s)")
        return True

    def _cmd_press(self, args) -> bool:
        """Press the control called <text>. Controls only.

        `find` searches every line, which is right for reading and wrong for
        acting: asked for "Next" on a results page it landed on "over the
        next century" in a snippet, and the press that followed opened an
        article instead of page two. A reader saying "press Next" means the
        control, and the render already knows which lines are controls.

        The last match wins, because the control a reader wants by name is
        usually the one furthest down -- a pager sits below the results it
        pages through.
        """
        needle = " ".join(args).lower().strip()
        if not needle:
            self.state.buffers.note("press needs a control's name")
            return True
        hits = [w for w in self.state.document.controls()
                if needle in w.label.lower()]
        if not hits:
            self.state.buffers.note(f"no control named {needle!r}")
            return True
        widget = hits[-1]
        self.state.scroll_to_line(widget.line)
        self.state.focus = widget.line
        self.state.buffers.note(
            f"pressing {widget.label[:40]!r} at line {widget.line}")
        self.state._activate(widget)
        return True

    def _cmd_hover(self, args) -> bool:
        """Point at something without pressing it.

        A menu that opens on hover has no other way in from a terminal: there
        is no pointer, so the gesture has to be asked for by name. Everything
        it reveals arrives on the same delta stream as any other change --
        the page opened a menu, and the menu is now part of the page.
        """
        widget = self._line_arg(args)
        if widget is None or widget.address is None:
            return True
        sensor = getattr(self, "_sensor", None)
        if sensor is None:
            self.state.buffers.note("hover needs a live page")
            return True
        before = len(self.state.document)
        try:
            out = sensor.hover(widget.address)
        except Exception as exc:  # noqa: BLE001
            self.state.buffers.note(f"hover: {type(exc).__name__}: {exc}")
            return True
        if out["failed"]:
            self.state.buffers.note("hover: " + ", ".join(
                f"{k}:{v}" for k, v in out["failed"]))
            return True
        import time as _t
        _t.sleep(0.5)
        self.sense()
        grew = len(self.state.document) - before
        self.state.buffers.note(
            f"hovered {widget.label[:38]!r} — "
            + (f"the page revealed {grew} more line(s)" if grew > 0
               else "nothing opened"))
        return True

    def _cmd_check(self, args) -> bool:
        widget = self._line_arg(args)
        if widget is None:
            return True
        # Any line can be marked; turning it into a checkbox is how the REPL
        # keeps a selection without a parallel selection model.
        if widget.kind is not WidgetKind.CHECKBOX:
            widget.kind = WidgetKind.CHECKBOX
        widget.checked = not widget.checked
        if widget.checked and widget.address is not None:
            self.state.buffers.mark(widget.address)
        self.state.buffers.note(
            f"line {widget.line} {'checked' if widget.checked else 'unchecked'}")
        return True

    def _cmd_type(self, args) -> bool:
        widget = self._line_arg(args)
        if widget is None:
            return True
        text = " ".join(args[1:])
        widget.value = text
        widget.cursor = len(text)
        if widget.address is not None and self.nav.live:
            # Submitting a search box navigates, so the document that comes
            # back is the results page — the whole point of typing into it.
            self.render_live(self._gesture(widget.address, "type", text))
        else:
            self.state.buffers.note(f"line {widget.line} = {text!r}")
        return True

    def _cmd_where(self, args) -> bool:
        widget = self._line_arg(args)
        if widget is None or widget.address is None:
            return True
        address = widget.address
        print(f"\n  url       {address.url}\n  xpath     {address.xpath}\n"
              f"  pattern   {address.pattern}\n  tag       {address.tag}\n"
              f"  accessor  {address.accessor}\n  aid       {address.aid}\n")
        self.state.buffers.note(address.xpath)
        return True

    def _cmd_marks(self, args) -> bool:
        marks = self.state.buffers.marks
        for address in marks:
            print(f"  {address}")
        self.state.buffers.note(f"{len(marks)} mark(s)")
        return True

    def _cmd_scroll(self, args) -> bool:
        # `scroll left 20` / `scroll right 20` move the window sideways over
        # the wireframe canvas. A page wider than the terminal is the normal
        # case, not an edge one.
        if args and args[0].lower() in ("left", "right", "l", "r"):
            step = 20
            if len(args) > 1:
                try:
                    step = int(args[1])
                except ValueError:
                    pass
            if args[0].lower() in ("left", "l"):
                step = -step
            widest = max((len(l.text) for l in getattr(self, "_wire_lines", [])),
                         default=0)
            view = min(self.state.cols, getattr(self, "_wire_width", 0)
                       or self.state.cols)
            self.state.left = max(0, min(self.state.left + step,
                                         max(0, widest - view)))
            self.state.buffers.note(
                f"column {self.state.left + 1} of {max(1, widest)}")
            return True
        try:
            lines = int(args[0]) if args else self.state.body_rows
        except ValueError:
            self.state.buffers.note("scroll needs a number")
            return True
        before = self.state.top
        # Both views move. They count lines differently -- a page in columns
        # is fewer lines than the same page one unit per line -- so each keeps
        # its own position and a scroll advances both by the same amount.
        self._wire_top = max(0, getattr(self, "_wire_top", 0) + lines)
        self.state.scroll(lines)
        # Past the end of what is rendered, the scroll stops being a viewport
        # motion and becomes the page's (OBJECT_MODEL 7.6): the live document
        # is stepped, any pager it passes is enacted, and the delta extends
        # the view. That is why reading downward grows the document instead
        # of stopping at whatever the first paint happened to contain.
        if lines > 0 and self.state.top == before:
            self.extend()
        return True

    def _known_digests(self) -> List[str]:
        """Content fingerprints already stored for this host.

        Only gathered when `crosspage` is on, because collecting them costs a
        store read per boot and buys nothing otherwise. The digest is the
        sensor's own content fingerprint, so the page can compare against it
        without the receiver explaining what it means.
        """
        if not self.variants.get("crosspage"):
            return []
        return sorted(self._seen_content)

    def _page_chunks(self, url: str):
        """Chunks stored for one page url. Empty when there is no workspace."""
        if self.workspace is None:
            return []
        try:
            return list(self.workspace.store.chunks(url))
        except Exception:  # noqa: BLE001 - a read must not end a verification
            return []

    def _await_document(self, timeout: float = 5.0, was: str = "") -> bool:
        """Wait, briefly and with a cap, for a navigation to land.

        `was` is the address before the click, and it is what makes this
        correct. Waiting only for `readyState == "complete"` observed the
        *outgoing* document — which is still complete for a moment after a
        click — and returned instantly. The sensor then re-read the page it
        was leaving, learned the new address one drain later when the dead
        handle finally revealed it, and in the meantime the page looked
        empty: two idle steps, `exhausted` latched, and a site with eight
        pages left reported itself finished after one.
        """
        import time as _t

        driver = getattr(self.nav, "driver", None)
        if driver is None:
            return False
        deadline = _t.time() + timeout
        while _t.time() < deadline:
            try:
                here = driver.current_url
                ready = driver.execute_script("return document.readyState;")
                if ready == "complete" and (not was or here != was):
                    return True
            except Exception:  # noqa: BLE001 - mid-navigation, try again
                pass
            _t.sleep(0.1)
        return False

    def extend(self) -> bool:
        """One live scroll step, with pagination folded in. Returns success."""
        if self._sensor is None:
            return False
        was = self.nav.current_url
        # With `fused` on, the scroll and the drain cross the boundary
        # together. The drain is consumed here rather than by the `sense()`
        # below, which then has nothing left to fetch — so the axis is only
        # meaningful on a scrolling pass, not on a re-read.
        fused = bool(self.variants.get("fused"))
        prefetched = None
        if fused:
            step, prefetched = self._sensor.fused()
        else:
            step = self._sensor.step()
        for _tag, _label, _kind in step.fired:
            self._fired.append((_kind, _label))
        for _g, _n in (step.gates or {}).items():
            self._gates[_g] = self._gates.get(_g, 0) + _n
        if step.fired:
            self.state.buffers.note(
                "enacted " + ", ".join(f"{k}:{lbl}" for _t, lbl, k in step.fired))
            # A pager that navigates replaces the document, and draining
            # before the replacement exists reads the page being left. This
            # is a bounded wait on an action the reader just took, not a
            # poll of the fold.
            if any(kind == "navigate" for _t, _l, kind in step.fired):
                self._await_document(was=was)
        elif step.exhausted and step.bottom and self._idle >= 2:
            # Exhaustion means the document has no more to give, and a page
            # that has just been turned has plenty. The sensor learns the new
            # url one drain late (the dead handle is what reveals it), so for
            # a step or two after a page turn the fold looks empty and
            # `exhausted` fired on a site with eight pages left. Latch it only
            # after several consecutive steps that neither enacted a control
            # nor moved the address.
            self.state.buffers.note("end of the document")
            self._exhausted = True
            return False
        ok = self.sense(prefetched=prefetched) if fused else self.sense()
        # Record the sequence *after* sensing. Taken before the step, the url
        # is always the page being left, so three page turns read as one url:
        # the check reported "1 url" while the store held two pages, which
        # was the check being wrong, not the pagination.
        here = (self._sensor.url if self._sensor else "") or ""
        moved = bool(here) and (not self._trail or self._trail[-1] != here)
        if moved:
            self._trail.append(here)
        self._idle = 0 if (moved or step.fired) else self._idle + 1
        return ok

    def _cmd_back(self, args) -> bool:
        self.render_live(self.nav.back())
        return True

    # -- the loop ----------------------------------------------------------
    def render(self) -> str:
        return "\n".join(paint(self.state, colour=self.colour))

    def feed(self, data: str) -> None:
        """Decode raw terminal input and apply it. The pointer path.

        Stateful across calls, because input arrives in whatever chunks the
        terminal hands over and a click is a dozen bytes. `\\x1b[<0;10;5M`
        split after the fifth decoded as the keystrokes `;105M` and typed
        them into whatever field had focus; the unterminated tail is now
        carried to the next chunk.
        """
        events, self._pending = decode_stream(data, self._pending)
        for event in events:
            self.state.handle(event)

    def run_fed(self, stream=None) -> None:
        """Consume raw terminal bytes from a stream, then render once.

        The same path a real mouse takes — the terminal's escape sequences go
        through :meth:`feed` untouched — but driven from a pipe instead of a
        tty. That is what makes the pointer chain testable end to end on a
        machine with no pty and no desktop: everything from the bytes onward
        is exercised for real, and only the hardware that produces them is
        stubbed.
        """
        data = (stream or sys.stdin).read()
        if data:
            self.feed(data)

    def run(self, *, mouse: bool = True) -> None:
        """Full-screen loop. Everything it does is available headlessly too."""
        with RawTerminal(mouse=mouse) as term:
            self.state.rows, self.state.cols = term.size()
            while self.running:
                sys.stdout.write("\x1b[H\x1b[2J" + self.render())
                sys.stdout.flush()
                if not term.raw:
                    # No raw mode: read a whole LINE, because `term.read()`
                    # returns exactly one character here. `_drain` needs
                    # `select`, which does not work on a Windows console
                    # handle, so it returns "" and the read is a single char.
                    #
                    # This branch used to call `term.read()` and treat the
                    # result as a typed line -- the two comments contradicted
                    # each other, one file apart, and the code believed the
                    # wrong one. Every command on Windows was dispatched
                    # letter by letter: `help` became `h`, `e`, `l`, `p`,
                    # four unknown commands and no help. `quit` became `q`,
                    # `u`, `i`, `t`, so the session could not even be closed,
                    # and because it stayed open it kept the kuzu lock on the
                    # store and the *next* launch failed too.
                    line = sys.stdin.readline()
                    if not line:
                        break
                    if not self.command(line.strip()):
                        break
                    continue
                data = term.read()
                if not data:
                    break
                if data == "\x03":
                    break
                # A typed character opens the command line, seeded with it.
                #
                # Without this, raw mode is a trap: printable keys do nothing
                # unless a text field happens to hold focus (`model._key`
                # drops them), so a reader who typed `open ...` watched a
                # frozen screen and concluded the REPL was broken. It had
                # simply given them no way in. `:` still works and is what
                # the status line advertises; typing is the discoverable
                # path to the same prompt.
                if self._starts_a_command(data):
                    seed = "" if data == ":" else data
                    sys.stdout.write("\x1b[?25h\n:" + seed)
                    sys.stdout.flush()
                    # Through the terminal, not `sys.stdin`: on Windows the
                    # console is being read a keystroke at a time and mixing
                    # the two buffers drops characters.
                    line = seed + term.read_line()
                    sys.stdout.write("\x1b[?25l")
                    if not line.strip():
                        continue
                    if not self.command(line):
                        break
                    continue
                self.feed(data)

    def _starts_a_command(self, data: str) -> bool:
        """Should this keystroke open the command line rather than navigate?

        `:` always does. So does any single printable character -- unless a
        text field has focus, where it belongs to the field and typing into
        the page is the whole point.

        Escape sequences never do: an arrow key is navigation, and seeding a
        prompt with `\x1b[A` would put the sequence into the command instead
        of scrolling.
        """
        if data == ":":
            return True
        if len(data) != 1 or not data.isprintable():
            return False
        focus = self.state.focus
        if focus is not None:
            try:
                if self.state.document.lines[focus].kind is WidgetKind.INPUT:
                    return False
            except (IndexError, AttributeError):
                pass
        return True


def _shutdown(repl, workspace) -> None:
    """Give back what the session took: the browser, then the store.

    A headless `--command` run had no exit path for the driver, so every
    invocation left a Firefox behind. They are invisible one at a time and
    not at all in aggregate: a demonstration session ended with 216 of them
    holding all but 1.8 GB of memory, which slowed the machine enough that a
    test suite that runs in four minutes stopped finishing at all.

    Browser first. The workspace flushes vectors on close and that is the
    part worth protecting, so it goes last and runs even if the quit throws.
    """
    driver = getattr(getattr(repl, "nav", None), "driver", None)
    if driver is not None:
        try:
            driver.quit()
        except Exception:  # noqa: BLE001 - shutting down must not raise
            pass
        repl.nav.driver = None
    if workspace is not None:
        try:
            workspace.close()
        except Exception:  # noqa: BLE001
            pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="vertiscope-repl",
        description="Interactive markdown browsing over a scanned corpus.")
    parser.add_argument("target", nargs="?", default="",
                        help="a jsonl chunk file, or a url present in the store")
    parser.add_argument("--build", default="build",
                        help="directory written by scripts/build_index.py")
    parser.add_argument("--no-mouse", action="store_true")
    parser.add_argument("--command", action="append", default=[],
                        help="run a command and exit; repeatable (headless)")
    parser.add_argument("--snapshot", action="store_true",
                        help="print the screen after every --command, not "
                             "only at the end")
    args = parser.parse_args(argv)

    repl = Repl()
    build = Path(args.build)
    workspace = None
    if build.exists() or args.command:
        # One workspace, opened for the session. Browsing writes through it,
        # so a page read is a page stored -- there is no second command to
        # run afterwards to make what you just looked at retrievable, which
        # is the whole of "the database tracks pages while you navigate".
        # Without this the REPL read the store and never wrote to it, so
        # every page visited in a session was gone at the end of it.
        from ..search import ThreeFormIndex
        from ..workspace import Workspace

        workspace = Workspace(build)
        repl.workspace = workspace
        repl.store = workspace.store
        try:
            repl.index = ThreeFormIndex(workspace.store, workspace.freq).build()
        except Exception as exc:  # noqa: BLE001 - an empty store is not an error
            repl.state.buffers.note(f"index: {type(exc).__name__}: {exc}")

    if args.target:
        repl.command(f"open {args.target}")

    if args.command:
        # `--snapshot` prints the screen after each command instead of once
        # at the end. A terminal application's screen *is* its output, and a
        # single frame after a run of ten gestures says nothing about the
        # nine before it -- which is the whole of what a walkthrough has to
        # show.
        for command in args.command:
            if args.snapshot:
                print("\n" + "=" * 78)
                print(f"$ {command}")
                print("=" * 78)
            repl.command(command)
            if args.snapshot:
                print(repl.render())
        if not args.snapshot:
            print(repl.render())
        _shutdown(repl, workspace)
        return 0

    try:
        repl.run(mouse=not args.no_mouse)
    finally:
        _shutdown(repl, workspace)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
