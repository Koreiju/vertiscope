"""The REPL: one surface for browsing, retrieval and navigation.

Runs from the command line (``python -m domvec.repl``) or as a package
(``Repl(...).run()``). The loop is deliberately thin — it reads input, decodes
it to events, hands them to :class:`~domvec.repl.model.ReplState`, and paints
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
  search <query>      three-form retrieval; results become the document
  goto <n>            jump to document line n
  find <text>         scroll to the next line containing text
  controls            list pagination / menu / filter / search controls
  click <n>           activate line n (same as clicking it)
  type <n> <text>     type into the field on line n
  check <n>           toggle the checkbox on line n
  stats               per-stage cost of this session
  sweep [scan|compare|passes|status|resume|variants|detect|failures]
                      run/resume the variant sweep and read its tables
  variant <name> <on|off>  switch a sensor mechanism, re-read the page
  targets [run]       the verification targets and whether they are reachable
  verify <target>     run the acceptance battery against one, print a verdict
  axes                the design space, and what is set right now
  compare [axis...]   read this page under each setting, side by side
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
        self._sweep_corpus = 'build_sweep/urls.txt'
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

    _COVERAGE_JS = r"""
    // Everything a reader could see or follow, counted from the COMPOSED
    // tree -- across shadow boundaries, after scripts have run. Two separate
    // questions get answered here: what content exists (so the render can be
    // checked for completeness), and where it came from (so "did we read the
    // live DOM or a static snapshot" stops being a matter of trust).
    var seenShadow = 0, shadowText = 0, hosts = 0;
    var text = [], links = [], media = [], headings = 0, tables = 0;
    var SKIP = {SCRIPT:1, STYLE:1, NOSCRIPT:1, TEMPLATE:1, HEAD:1};

    function walk(root, inShadow) {
      var kids = root.childNodes || [];
      for (var i = 0; i < kids.length; i++) {
        var n = kids[i];
        if (n.nodeType === 3) {
          var t = (n.nodeValue || '').trim();
          if (t) { text.push(t); if (inShadow) shadowText++; }
          continue;
        }
        if (n.nodeType !== 1) continue;
        if (SKIP[n.tagName]) continue;
        var tag = n.tagName;
        if (/^H[1-6]$/.test(tag)) headings++;
        if (tag === 'TABLE') tables++;
        if (tag === 'A' && n.getAttribute('href') !== null)
          links.push(n.getAttribute('href'));
        if (tag === 'IMG' || tag === 'VIDEO' || tag === 'AUDIO'
            || tag === 'SOURCE' || tag === 'IFRAME') {
          var src = n.getAttribute('src') || n.getAttribute('srcset')
                    || n.getAttribute('poster') || n.getAttribute('data-src');
          if (src) media.push(src);
        }
        if (n.shadowRoot) { hosts++; seenShadow++; walk(n.shadowRoot, true); }
        walk(n, inShadow);
      }
    }
    walk(document.documentElement, false);

    // Provenance. `documentElement.outerHTML` is what a static fetch would
    // have got; anything past that arrived because scripts ran.
    var staticLen = 0;
    try { staticLen = (document.documentElement.outerHTML || '').length; }
    catch (e) { staticLen = 0; }

    return {
      text: text, links: links, media: media,
      headings: headings, tables: tables,
      shadowHosts: hosts, shadowTextNodes: shadowText,
      liveChars: staticLen,
      elements: document.getElementsByTagName('*').length
    };
    """

    def _cmd_coverage(self, args) -> bool:
        """What the page holds, against what the render shows.

        Completeness is not something to be asserted. This walks the composed
        tree -- across shadow boundaries, after scripts have run -- collects
        every text run, hyperlink and media reference the page actually has,
        and checks each one against the rendered document. What is missing is
        listed, not summarised.

        It also answers where the tree came from, which is the other thing
        that cannot be taken on trust: shadow hosts crossed, and text nodes
        found inside shadow roots. A static fetch reaches neither.
        """
        if not args:
            self.state.buffers.note("coverage needs a url")
            return True
        url = args[0]
        driver = getattr(self.nav, "driver", None)
        if driver is None:
            self.state.buffers.note("coverage needs a live browser — run 'browser'")
            return True

        import time as _t

        from ..sensing import Sensor
        from ..stream import StreamingScan

        driver.set_page_load_timeout(45)
        driver.get(url)
        _t.sleep(1.0)
        sensor = Sensor(driver, url, budget=self.context_window)
        sensor.boot()
        _t.sleep(0.7)
        spine = StreamingScan(url, context_window=self.context_window)
        sp = sensor.drain(0)
        spine.absorb(sp.units, sp.passno, removed=sp.removed_addresses)

        page = driver.execute_script(self._COVERAGE_JS) or {}
        from ..markdown import render_trie
        chunks = render_trie(spine.trie, context_window=self.context_window)
        drawn = "\n".join(c.markdown for c in chunks)
        values = {n.value.strip() for n in (spine.trie.leaves() if spine.trie else [])
                  if n.value.strip()}
        blob = drawn + "\n" + "\n".join(values)

        def held(items):
            """An item counts as held when it survives into the render."""
            missing = []
            for item in items:
                probe = item.strip()
                if not probe:
                    continue
                if probe in blob:
                    continue
                # A long run is often split across inline elements; a
                # substantial head of it landing is the honest test.
                head = probe[:40]
                if len(probe) > 40 and head in blob:
                    continue
                missing.append(probe)
            return missing

        text_missing = held(page.get("text") or [])
        link_missing = held(page.get("links") or [])
        media_missing = held(page.get("media") or [])

        def row(name, total, missing):
            got = total - len(missing)
            pct = 100.0 * got / total if total else 100.0
            return f"  {name:<22}{got:>7,} / {total:<7,}{pct:>7.1f}%"

        rows = [
            "",
            f"  coverage  {url}",
            "",
            f"  {'':<22}{'in render':>9}{'on page':>10}{'':>8}",
            row("text runs", len(page.get("text") or []), text_missing),
            row("hyperlinks", len(page.get("links") or []), link_missing),
            row("media references", len(page.get("media") or []), media_missing),
            "",
            f"  {'headings on page':<22}{page.get('headings', 0):>7,}"
            f"   in render {drawn.count(chr(35) + ' '):>5,}",
            f"  {'tables on page':<22}{page.get('tables', 0):>7,}",
            "",
            "  provenance — where this tree came from",
            f"  {'elements walked':<22}{page.get('elements', 0):>7,}",
            f"  {'shadow hosts crossed':<22}{page.get('shadowHosts', 0):>7,}",
            f"  {'text inside shadow':<22}{page.get('shadowTextNodes', 0):>7,}"
            "   (a static fetch reaches none of this)",
            f"  {'rendered lines':<22}"
            f"{sum(len(c.lines) for c in chunks):>7,}",
        ]
        for name, missing in (("text", text_missing), ("links", link_missing),
                              ("media", media_missing)):
            if missing:
                rows.append("")
                rows.append(f"  {name} not in the render ({len(missing)}):")
                for item in missing[:6]:
                    rows.append(f"    {item[:84]}")
        rows.append("")
        print("\n".join(rows), flush=True)
        self.state.buffers.note(
            f"coverage: {len(text_missing)} text, {len(link_missing)} link, "
            f"{len(media_missing)} media not rendered")
        return True

    _FIDELITY_JS = r"""
    var out = [];
    function step(el) {
      var p = el.parentNode, n = 1, i;
      if (!p || !p.children) return el.tagName.toLowerCase();
      for (i = 0; i < p.children.length; i++) {
        var c = p.children[i];
        if (c === el) break;
        if (c.tagName === el.tagName) n++;
      }
      var t = el.tagName.toLowerCase();
      return n > 1 ? t + '[' + n + ']' : t;
    }
    function pathOf(el) {
      var parts = [], cur = el, guard = 0;
      while (cur && cur.nodeType === 1 && guard++ < 200) {
        parts.unshift(step(cur));
        var p = cur.parentNode;
        if (p && p.nodeType === 11) { parts.unshift('#shadow-root'); cur = p.host; }
        else cur = p;
      }
      return '/' + parts.join('/');
    }
    var NATIVE = {A:1, BUTTON:1, INPUT:1, SELECT:1, TEXTAREA:1, SUMMARY:1, AREA:1};
    function visit(root) {
      var els = root.querySelectorAll ? root.querySelectorAll('*') : [];
      for (var i = 0; i < els.length; i++) {
        var el = els[i];
        if (el.shadowRoot) visit(el.shadowRoot);
        var native = NATIVE[el.tagName];
        if (native === 1 && (el.tagName === 'A' || el.tagName === 'AREA')
            && el.getAttribute('href') === null) native = 0;
        if (el.tagName === 'INPUT'
            && (el.getAttribute('type') || '').toLowerCase() === 'hidden') native = 0;
        var role = (el.getAttribute('role') || '').toLowerCase();
        if (!native && !role && el.getAttribute('tabindex') === null) continue;
        // Only what a reader could act on. A rendered-away control is not a
        // missing affordance; it is not on the page.
        var r = el.getBoundingClientRect();
        if (!r.width && !r.height) continue;
        out.push([pathOf(el), el.tagName.toLowerCase(), role]);
      }
    }
    visit(document);
    return out;
    """

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
        update = spine.absorb(sp.units, sp.passno, removed=sp.removed_addresses)
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

    def _cmd_walk(self, args) -> bool:
        """The whole loop, run end to end, with the cost of each step.

        This exists because the trace was once *described* rather than run,
        and the description did not survive reading. So it is a command: ask
        a question, land on the results page, scroll to the bottom, press
        whatever control is there, and show the new rows arriving as a delta.

        Nothing in it knows what pagination is. The control at the bottom is
        pressed because it is a control, and the page answers or it does not.
        """
        import time as _t
        import urllib.parse

        from ..aam import INTERACTIVE
        from ..markdown import render_trie
        from ..sensing import Sensor
        from ..stream import StreamingScan

        driver = getattr(self.nav, "driver", None)
        if driver is None:
            self.state.buffers.note("walk needs a live browser — run 'browser'")
            return True
        question = " ".join(args) or "glacier retreat measurements"
        rows = ["", f"  walk  {question!r}", ""]
        rows.append(f"  {'step':<34}{'chunks':>8}{'lines':>8}{'bytes':>10}{'ms':>8}")

        def measure(label, spine, ms):
            chunks = render_trie(spine.trie, context_window=1200) if spine.trie else []
            lines = sum(len(c.lines) for c in chunks)
            size = sum(len(c.markdown) for c in chunks)
            rows.append(f"  {label:<34}{len(chunks):>8,}{lines:>8,}"
                        f"{size:>10,}{ms:>8.0f}")
            return chunks

        # 1. the question routes to the engine's own page
        engine = ("https://html.duckduckgo.com/html/?q="
                  + urllib.parse.quote_plus(question))
        t0 = _t.perf_counter()
        driver.set_page_load_timeout(45)
        driver.get(engine)
        _t.sleep(1.0)
        sensor = Sensor(driver, engine, budget=1200)
        sensor.boot()
        _t.sleep(0.6)
        spine = StreamingScan(engine, context_window=1200)
        sp = sensor.drain(0)
        spine.absorb(sp.units, sp.passno, removed=sp.removed_addresses)
        measure("visit + fold", spine, (_t.perf_counter() - t0) * 1000)

        shape, repeats = self._row_template(spine.trie, engine)
        rows.append(f"  {'row shape found':<34}"
                    f"{('x'.join(shape) if shape else 'none'):>26}"
                    f"  {repeats} repeats")

        # 2. scroll to the bottom
        t1 = _t.perf_counter()
        offered = []
        for _ in range(6):
            # `step`, not `scroll`: the latter reports milliseconds only,
            # and what the walk needs is what came into view.
            step = sensor.step()
            offered.extend(step.offered)
            _t.sleep(0.35)
            sp = sensor.drain(1)
            spine.absorb(sp.units, sp.passno, removed=sp.removed_addresses)
            if step.bottom:
                break
        before = measure("scroll to bottom", spine, (_t.perf_counter() - t1) * 1000)
        rows.append(f"  {'controls offered on the way':<34}{len(offered):>8,}")

        # 3. press whatever the bottom of the page puts there
        seen_xp: set = set()
        tail = []
        for leaf in (spine.trie.leaves() if spine.trie else []):
            a = leaf.address
            if a.tag not in INTERACTIVE:
                continue
            xp = a.xpath.split("/text()")[0]
            if xp in seen_xp:
                continue
            seen_xp.add(xp)
            tail.append(a)
        # The last *button*, not the last affordance. That is a reader's
        # gesture -- scroll down, press the button at the bottom -- expressed
        # in render classes, and it is not a claim about what the button
        # does. Taking the last affordance instead pressed a footer link,
        # because a page has a footer after its controls: on this results
        # page the pager sits in div[11] and the run reached into div[12].
        buttons = [a for a in tail if a.tag == "button"]
        target = (buttons[-1] if buttons else (tail[-1] if tail else None))
        if target is None:
            rows.append("  nothing at the bottom to press")
            rows.append("")
            print("\n".join(rows), flush=True)
            return True
        rows.append(f"  {'pressing':<34}{target.tag:>8}  {target.xpath[-46:]}")

        t2 = _t.perf_counter()
        was = sensor.url
        result = sensor.press(target)
        _t.sleep(1.0)
        sp = sensor.drain(2)
        update = spine.absorb(sp.units, sp.passno,
                              removed=sp.removed_addresses)
        after = measure("after the press", spine, (_t.perf_counter() - t2) * 1000)

        grew = len(after) - len(before)
        rows.append("")
        rows.append(f"  delta from the press: added={len(update.delta.added):,} "
                    f"changed={len(update.delta.changed):,} "
                    f"moved={len(update.delta.moved):,} "
                    f"removed={len(update.delta.removed):,}")
        rows.append(f"  chunks {'gained' if grew >= 0 else 'lost'}: {abs(grew):,}"
                    f"   navigated: {'yes' if sensor.url != was else 'no'}")
        if result["failed"]:
            rows.append("  chain reported: " + ", ".join(
                f"{k}:{v}" for k, v in result["failed"]))
        rows.append("")
        print("\n".join(rows), flush=True)
        self.state.buffers.note(
            f"walk: {len(after)} chunk(s) after the press, "
            f"delta {update.delta.touched}")
        return True

    def _cmd_enact(self, args) -> bool:
        """Do the affordances actually work? The other half of acceptance.

        Fidelity says every control is drawn. This says every drawn control
        can be acted on: its address still resolves to a live node, and
        pressing it produces a delta. Both are countable and neither asks
        what anything means.

        Nothing is filtered by what it might do. A control is pressed and
        the page answers -- if it navigated, that is the largest delta there
        is, and the page is reopened to carry on. Deciding in advance which
        controls were safe to press is the thing this design removed; what
        remains in front of every press, wherever it comes from, is
        `refused`, which is a safety denylist and not a classification.
        """
        if not args:
            self.state.buffers.note("enact needs a url")
            return True
        url = args[0]
        driver = getattr(self.nav, "driver", None)
        if driver is None:
            self.state.buffers.note("enact needs a live browser — run 'browser'")
            return True

        import time as _t

        from ..aam import INTERACTIVE
        from ..sensing import Sensor
        from ..stream import StreamingScan

        limit = int(args[1]) if len(args) > 1 else 8

        def fold(target):
            driver.set_page_load_timeout(45)
            driver.get(target)
            _t.sleep(0.7)
            sensor = Sensor(driver, target, budget=1200)
            sensor.boot()
            _t.sleep(0.5)
            spine = StreamingScan(target, context_window=1200)
            sp = sensor.drain(0)
            spine.absorb(sp.units, sp.passno, removed=sp.removed_addresses)
            return sensor, spine

        sensor, spine = fold(url)
        seen: dict = {}
        for leaf in (spine.trie.leaves() if spine.trie else []):
            if leaf.address.tag in INTERACTIVE:
                seen.setdefault(leaf.address.xpath, leaf.address)
        affordances = list(seen.values())
        resolved = sum(1 for a in affordances if sensor.resolves(a))

        pressed = delta_seen = navigated = refused_n = 0
        failures: list = []
        for address in affordances[:limit]:
            before = sensor.url
            result = sensor.press(address)
            pressed += 1
            if any(reason == "refused" for _, reason in result["failed"]):
                refused_n += 1
                continue
            if result["failed"]:
                failures.append(result["failed"][0])
                continue
            _t.sleep(0.6)
            after = sensor.drain(99)
            moved = bool(after.units) or bool(after.removed_addresses)
            # Navigation is learned from the drain, never from the chain's
            # own return. `perform` reads location.href in the same tick it
            # dispatched the click, and a navigation has not happened yet at
            # that point -- so the chain reports the old address, the next
            # press resolves against a page that has already gone, and the
            # run blames the executor for what is really the check reading
            # too early. The drain crosses afterwards and carries the URL
            # the page actually ended up at.
            if sensor.url and sensor.url != before:
                navigated += 1
                delta_seen += 1
                sensor, spine = fold(url)          # back to where we started
            elif moved:
                delta_seen += 1
            else:
                failures.append(("click", "no delta"))

        pct_r = 100.0 * resolved / max(len(affordances), 1)
        pct_d = 100.0 * delta_seen / max(pressed - refused_n, 1)
        rows = [
            "",
            f"  enactability  {url}",
            f"  {'affordances drawn':<32}{len(affordances):>8,}",
            f"  {'addresses that resolve':<32}{resolved:>8,}   {pct_r:>5.1f}%",
            "",
            f"  {'pressed':<32}{pressed:>8,}",
            f"  {'refused (safety denylist)':<32}{refused_n:>8,}",
            f"  {'produced a delta':<32}{delta_seen:>8,}   {pct_d:>5.1f}%",
            f"  {'of which navigated':<32}{navigated:>8,}",
        ]
        if failures:
            import collections as _c
            tally = _c.Counter(f"{k}:{v}" for k, v in failures)
            rows.append("")
            rows.append("  did not take: " + ", ".join(
                f"{k}={v}" for k, v in tally.most_common(6)))
        rows.append("")
        print("\n".join(rows), flush=True)
        self.state.buffers.note(
            f"enact: {pct_r:.0f}% resolve, {pct_d:.0f}% of presses moved the page")
        return True

    def _cmd_fidelity(self, args) -> bool:
        """Does every control on the page appear as an affordance? Stage 4's check.

        The acceptance question used to be "was search detected?", answered at
        70.1% after two rebuilds, with no way to tell a page that had no
        search box from one whose box we rejected. It is retired with the
        premise that produced it.

        This is the replacement, and it involves no judgement about meaning:
        walk the composed tree for everything a reader could act on, walk the
        rendered affordances, and report the difference. A miss is a control
        the reader cannot reach — countable, listable, and nobody has to
        decide whether it was "really" a pager.
        """
        if not args:
            self.state.buffers.note("fidelity needs a url")
            return True
        url = args[0]
        driver = getattr(self.nav, "driver", None)
        if driver is None:
            self.state.buffers.note("fidelity needs a live browser — run 'browser'")
            return True

        import time as _t

        from ..aam import INTERACTIVE
        from ..sensing import Sensor
        from ..stream import StreamingScan

        scrolls = int(args[1]) if len(args) > 1 else 2
        driver.set_page_load_timeout(45)
        driver.get(url)
        _t.sleep(0.8)
        sensor = Sensor(driver, url, budget=1200)
        sensor.boot()
        _t.sleep(0.6)
        spine = StreamingScan(url, context_window=1200)
        for passno in range(scrolls + 1):
            if passno:
                sensor.scroll()
                _t.sleep(0.5)
            sp = sensor.drain(passno)
            spine.absorb(sp.units, sp.passno, removed=sp.removed_addresses)

        dom = driver.execute_script(self._FIDELITY_JS) or []
        dom_paths = {row[0] for row in dom}

        drawn: dict = {}
        for leaf in (spine.trie.leaves() if spine.trie else []):
            if leaf.address.tag not in INTERACTIVE:
                continue
            xp = leaf.address.xpath
            # An affordance's text sits one step below the control; the
            # control is what a reader presses.
            if "/text()" in xp:
                xp = xp[:xp.index("/text()")]
            drawn.setdefault(xp, leaf.address.tag)

        hit = dom_paths & set(drawn)
        missed = dom_paths - set(drawn)
        extra = set(drawn) - dom_paths

        import collections as _c
        by_tag = _c.Counter(row[1] for row in dom if row[0] in missed)
        kinds = _c.Counter(drawn.values())

        pct = 100.0 * len(hit) / max(len(dom_paths), 1)
        rows = [
            "",
            f"  fidelity  {url}",
            f"  {'interactive in composed tree':<34}{len(dom_paths):>8,}",
            f"  {'rendered as an affordance':<34}{len(hit):>8,}   {pct:>5.1f}%",
            f"  {'missed':<34}{len(missed):>8,}",
            f"  {'drawn but not found in the DOM':<34}{len(extra):>8,}",
            "",
            "  affordances drawn, by render class",
        ]
        for kind, n in kinds.most_common():
            rows.append(f"    {kind:<12}{n:>7,}")
        if by_tag:
            rows.append("")
            rows.append("  missed, by element: " + ", ".join(
                f"{k}={v}" for k, v in by_tag.most_common(8)))
            for path in sorted(missed)[:5]:
                rows.append(f"    {path[:88]}")
        rows.append("")
        print("\n".join(rows), flush=True)
        self.state.buffers.note(
            f"fidelity {pct:.1f}% — {len(missed)} control(s) not reachable")
        return True

    def _cmd_shift(self, args) -> bool:
        """Cost of one insertion, against the size of what it lands in.

        The stage-2 acceptance check. An address is positional, so inserting
        a single node at the head of a list re-points every address after it
        — and before `AddressTrie.apply` re-anchored by content, the reported
        delta for that was measured at exactly `N + 1` for every N tried.
        Cost tracked the page rather than the change, which is the O(delta)
        property failing.

        What has to hold now: `delta` stays at 1 whatever N is. `moved` may
        grow with N, because N things genuinely did move; the point is that a
        move is not an edit and must not be counted or re-vectorised as one.
        """
        driver = getattr(self.nav, "driver", None)
        if driver is None:
            self.state.buffers.note("shift needs a live browser — run 'browser'")
            return True

        import time as _t

        from ..sensing import Sensor
        from ..stream import StreamingScan

        sizes = [int(a) for a in args] or [5, 20, 50, 100, 200]
        rows = ["", "  one node inserted at the head of an N-item list",
                "  %6s %8s %8s %9s %9s" % ("items", "delta", "moved",
                                           "apply_ms", "uid_kept")]
        for n in sizes:
            items = "".join("<li>item-%03d</li>" % i for i in range(n))
            url = ("data:text/html,<html><body><ul id='L'>%s</ul></body></html>"
                   % items)
            driver.get(url)
            _t.sleep(0.35)
            sensor = Sensor(driver, url, budget=100000)
            sensor.boot()
            _t.sleep(0.35)
            spine = StreamingScan(url)
            first = sensor.drain(0)
            spine.absorb(first.units, 0, removed=first.removed_addresses)
            before = {leaf.value: leaf.uid for leaf in spine.trie.leaves()}
            driver.execute_script(
                "var l=document.getElementById('L');"
                "var li=document.createElement('li');"
                "li.textContent='NEW';l.insertBefore(li,l.firstChild);")
            _t.sleep(0.45)
            second = sensor.drain(1)
            update = spine.absorb(second.units, 1,
                                  removed=second.removed_addresses)
            after = {leaf.value: leaf.uid for leaf in spine.trie.leaves()}
            kept = sum(1 for v, u in before.items()
                       if v.strip() and after.get(v) == u)
            rows.append("  %6d %8d %8d %9.2f %6d/%d"
                        % (len(before), update.delta.size,
                           len(update.delta.moved), update.trie_ms,
                           kept, sum(1 for v in before if v.strip())))
        rows.append("")
        print("\n".join(rows), flush=True)
        self.state.buffers.note("shift: delta must stay flat as N grows")
        return True

    def _cmd_spine(self, args) -> bool:
        """Compare the two paths over one page. The stage-1 acceptance check.

        `spine <url>` reads the page twice — once through the in-page sensor,
        once by snapshotting and tagging on this side — and reports how far
        apart the results are. Both now go through one trie and one renderer,
        so any divergence left is a difference in *what was detected*, never
        in how it was structured or serialised. That is the number stage 3
        has to drive to zero, and it cannot be read at all until both paths
        share a spine.

        Reported per path: leaves in the trie, chunks the renderer produced,
        and the size of the address-set difference in each direction.
        """
        if not args:
            self.state.buffers.note("spine needs a url")
            return True
        url = args[0]
        driver = getattr(self.nav, "driver", None)
        if driver is None:
            self.state.buffers.note("spine needs a live browser — run 'browser'")
            return True

        import time as _t

        from ..sensing import Sensor
        from ..stream import StreamingScan

        scrolls = int(args[1]) if len(args) > 1 else 3

        # --- the live path ------------------------------------------------
        sensor = Sensor(driver, url, budget=1200)
        driver.set_page_load_timeout(45)
        driver.get(url)
        _t.sleep(0.6)
        sensor.boot()
        _t.sleep(0.6)
        live = StreamingScan(url, context_window=1200)
        live_ms = 0.0
        for passno in range(scrolls + 1):
            if passno:
                sensor.scroll()
                _t.sleep(0.5)
            sp = sensor.drain(passno)
            started = _t.perf_counter()
            live.absorb(sp.units, sp.passno, removed=sp.removed_addresses)
            live_ms += (_t.perf_counter() - started) * 1000
        # The settled page, not the last delta. Rendering the final update's
        # dirty set reports zero whenever the last pass happened to change
        # nothing -- which is most of them, and is how this line first read
        # "0 chunks" under 188 leaves.
        from ..markdown import render_trie
        live_all = (render_trie(live.trie, context_window=1200)
                    if live.trie is not None else [])

        # --- the snapshot path, on the page as it now stands ---------------
        html = driver.page_source or ""
        snap = StreamingScan(url, context_window=1200)
        update = snap.push(html, 1)
        snap_all = (render_trie(snap.trie, context_window=1200)
                    if snap.trie is not None else [])

        live_keys = ({n.address.key() for n in live.trie.leaves()}
                     if live.trie else set())
        snap_keys = ({n.address.key() for n in snap.trie.leaves()}
                     if snap.trie else set())
        both = live_keys & snap_keys
        union = live_keys | snap_keys

        # The full key mixes two independent disagreements: what each path
        # *found*, and what each path *calls* it. Compared whole they cannot
        # be told apart, and 0% overlap reads as though the sensor sees
        # nothing the tagger sees -- which is false. Comparing at the node
        # and detector level strips the naming out, leaving only scope.
        def by(trie, f):
            return {f(n.address) for n in (trie.leaves() if trie else [])}
        live_x = by(live.trie, lambda a: a.xpath)
        snap_x = by(snap.trie, lambda a: a.xpath)
        live_d = by(live.trie, lambda a: (a.xpath, a.detector))
        snap_d = by(snap.trie, lambda a: (a.xpath, a.detector))

        rows = [
            "",
            f"  spine  {url}",
            f"  {'':<22}{'leaves':>9}{'chunks':>9}{'ms':>9}",
            f"  {'sensor (live)':<22}{len(live_keys):>9,}"
            f"{len(live_all):>9,}{live_ms:>9.1f}",
            f"  {'snapshot (tagger)':<22}{len(snap_keys):>9,}"
            f"{len(snap_all):>9,}{update.trie_ms + update.tag_ms:>9.1f}",
            "",
            f"  {'agreement':<22}{'shared':>9}{'union':>9}{'%':>8}",
            f"  {'full address':<22}{len(both):>9,}{len(union):>9,}"
            f"{100.0 * len(both) / max(len(union), 1):>7.1f}%",
            f"  {'node + detector':<22}{len(live_d & snap_d):>9,}"
            f"{len(live_d | snap_d):>9,}"
            f"{100.0 * len(live_d & snap_d) / max(len(live_d | snap_d), 1):>7.1f}%",
            f"  {'node (xpath)':<22}{len(live_x & snap_x):>9,}"
            f"{len(live_x | snap_x):>9,}"
            f"{100.0 * len(live_x & snap_x) / max(len(live_x | snap_x), 1):>7.1f}%",
            "",
            f"  nodes only the sensor sees   {len(live_x - snap_x):>7,}",
            f"  nodes only the tagger sees   {len(snap_x - live_x):>7,}",
            "",
        ]
        # What the divergence is *made of* — the tag vocabulary each path
        # uses. Stage 3 unifies these; naming them here is what makes that
        # stage's target concrete rather than a percentage.
        def tags(keys, trie):
            out = {}
            for n in (trie.leaves() if trie else []):
                if n.address.key() in keys:
                    out[n.address.tag] = out.get(n.address.tag, 0) + 1
            return out
        lt = tags(live_keys - snap_keys, live.trie)
        st = tags(snap_keys - live_keys, snap.trie)
        if lt:
            rows.append("  sensor-only tags:   " + ", ".join(
                f"{k}={v}" for k, v in sorted(lt.items(), key=lambda x: -x[1])[:6]))
        if st:
            rows.append("  snapshot-only tags: " + ", ".join(
                f"{k}={v}" for k, v in sorted(st.items(), key=lambda x: -x[1])[:6]))

        # Detection coverage, compared where the two paths can be compared:
        # one node, one accessor. Counting leaves instead reads as though the
        # sensor sees half the media on a page -- the tagger files an image
        # URL under `urls.external` *and* `media.images`, so it emits two
        # leaves for one detection where the sensor emits one. That is a
        # difference in filing, not in what was found.
        def families(trie):
            out = {}
            for n in (trie.leaves() if trie else []):
                a = n.address
                head = a.accessor.split("|", 1)[0].split("@", 1)[0]
                head = head.split("[", 1)[0] or a.accessor
                out.setdefault(head, set()).add((a.xpath, head))
            return out
        lf, sf = families(live.trie), families(snap.trie)
        rows.append("  detection coverage, by (node, accessor)")
        rows.append(f"  {'accessor':<20}{'sensor':>9}{'tagger':>9}")
        order = sorted(set(lf) | set(sf),
                       key=lambda k: -(len(lf.get(k, ())) + len(sf.get(k, ()))))
        for k in order[:12]:
            rows.append(f"  {k[:20]:<20}{len(lf.get(k, ())):>9,}"
                        f"{len(sf.get(k, ())):>9,}")
        rows.append("")
        print("\n".join(rows), flush=True)
        node_pct = 100.0 * len(live_x & snap_x) / max(len(live_x | snap_x), 1)
        self.state.buffers.note(
            f"spine: node agreement {node_pct:.1f}%, "
            f"{len(snap_x - live_x)} nodes tagger-only")
        return True

    def _cmd_browser(self, args) -> bool:
        """Attach a live browser to this REPL.

        Every measurement command needs one, and until now the only way to
        get a driver in was to construct the REPL from a script. That put the
        measurement outside the REPL exactly where it was supposed to be
        inside it: a headless `--command "sweep scan"` had no browser and
        reported "needs a live browser" instead of scanning. This is the one
        missing seam.

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

    def _cmd_sweep(self, args) -> bool:
        """Run the variant sweep and read its tables, from here.

        The whole measurement lives in the REPL: `sweep run` performs the
        batch, `sweep variants` / `sweep detect` / `sweep failures` read the
        tables it appends to. Driving it from a script outside meant two
        writers on one record, a driver that died with its launcher, and
        tables nobody could see without regenerating a web page. The REPL is
        the test surface; the thing being tested and the thing reporting on
        it belong on the same surface.

          sweep                 summary + every table, in full
          sweep run [pages] [scrolls]   batch: all configurations x pages
          sweep variants        the paired contrast, every configuration
          sweep detect [n]      per-page search / pagination outcome
          sweep failures        what did not produce a usable row

        Nothing here truncates. A table that shows the best ten hides the
        regressions, and the regressions are the findings.
        """
        from ..experiments import tables

        verb = args[0] if args else ""
        if verb in ("status", "resume", "journal"):
            return self._sweep_meta(verb, args)
        if verb == "passes":
            n = int(args[1]) if len(args) > 1 else 3
            return self._sweep_passes(n)
        if verb == "scan":
            n = int(args[1]) if len(args) > 1 else 100
            scrolls = int(args[2]) if len(args) > 2 else 10
            if len(args) > 3:
                self._sweep_corpus = args[3]
            return self._sweep_scan(n, scrolls)
        if verb in ("compare", "continue"):
            pages = int(args[1]) if len(args) > 1 else 5
            scrolls = int(args[2]) if len(args) > 2 else 10
            return self._sweep_compare(pages, scrolls)
        if verb == "run":
            pages = int(args[1]) if len(args) > 1 else 3
            scrolls = int(args[2]) if len(args) > 2 else 10
            return self._sweep_run(pages, scrolls)

        rows = tables.load()
        if verb == "variants":
            print(tables.variants_table(rows))
        elif verb == "detect":
            n = int(args[1]) if len(args) > 1 else 0
            print(tables.detection_table(rows, limit=n))
        elif verb == "failures":
            print(tables.failures_table(rows))
        else:
            print(tables.summary(rows))
            print("== variants ==")
            print(tables.variants_table(rows))
            print("== detection ==")
            print(tables.detection_table(rows))
            print("== failures ==")
            print(tables.failures_table(rows))
        return True

    def _sweep_passes(self, pages: int) -> bool:
        """The multi-pass contrast: cost across reads, not within one.

        `sweep compare` performs one drain per axis, so it can only see a
        mechanism that changes what a *single* payload looks like. Half the
        design space does not: `gate`, `subtreegate`, `deepgate`,
        `chunkdelta` and `coalesce` all pay on the second read and later, and
        measured one-shot they read -0.0% while `subtreegate` under a
        scrolling protocol read -56.9%.

        Scrolling would expose them and is not repeatable, so the page is
        held still and the change is supplied: a fixed, self-inverting
        mutation sequence (`experiments/mutate.py`) that appends, edits, then
        puts everything back. Every axis sees the same document and the same
        deltas; the mechanism is the only variable left.
        """
        import json as _json
        import random as _random
        import time as _t

        _rng = _random.Random(20260823)
        from ..experiments import journal, mutate, tables
        from ..experiments.run_sweep import CONFIGS
        from ..sensing import Sensor

        driver = getattr(self.nav, "driver", None)
        if driver is None:
            self.state.buffers.note("sweep passes needs a live browser")
            return True
        panel = Path("build_sweep/depth.txt")
        urls = [u.strip() for u in
                panel.read_text(encoding="utf-8").splitlines()
                if u.strip()][:pages] if panel.exists() else []
        if not urls:
            self.state.buffers.note("no panel")
            return True
        names = [n for n, v in CONFIGS.items() if not v.get("__original__")]
        out = Path("build_sweep/passes.jsonl")
        out.parent.mkdir(parents=True, exist_ok=True)
        fh = out.open("a", encoding="utf-8")
        journal.log("start", f"passes {len(urls)} page(s) x {len(names)} axes "
                             f"x {len(mutate.SEQUENCE)} mutations")
        try:
            for u in urls:
                print(chr(10) + "  " + u[:70], flush=True)
                driver.get(u)
                _t.sleep(2.5)
                load_id = f"{int(_t.time() * 1000):x}"
                driver.execute_script(mutate.SETUP, 0)
                # Shuffle, per page. Running the axes in declaration order
                # meant `default` always went first, on a page the browser
                # had just loaded, while every later axis ran warm — and the
                # identical `control` arm came out 4.3% cheaper than
                # `default` for no reason but its position. Order is a
                # variable like any other; randomise it or measure it.
                order = list(names)
                _rng.shuffle(order)
                for name in order:
                    try:
                        driver.execute_script(mutate.RESTORE)
                        sen = Sensor(driver, u, variants=dict(CONFIGS[name]))
                        sen.boot()
                        _t.sleep(0.8)
                        cold = sen.drain(0)
                        wire = cold.wire_bytes
                        ms = cold.drain_ms
                        lines = cold.lines
                        per = [cold.wire_bytes]
                        for label, script, arg in mutate.SEQUENCE:
                            driver.execute_script(script, arg)
                            _t.sleep(0.45)
                            d = sen.drain(1)
                            wire += d.wire_bytes
                            ms += d.drain_ms
                            lines += d.lines
                            per.append(d.wire_bytes)
                        driver.execute_script(mutate.RESTORE)
                        rep = (cold.stats or {}).get("variants") or {}
                        row = {"requested": u, "url": u, "variant": name,
                               "load": load_id, "wire_bytes": wire,
                               "lines": lines, "chunks": cold.changed,
                               "drain_ms": ms, "cold_bytes": per[0],
                               "warm_bytes": sum(per[1:]),
                               "per_pass": per,
                               "variants_reported": rep, "t": _t.time()}
                        fh.write(_json.dumps(row, separators=(",", ":"))
                                 + chr(10))
                        fh.flush()
                        print(f"    {name:14s} total={wire:8,d} "
                              f"cold={per[0]:8,d} warm={sum(per[1:]):8,d} "
                              f"lines={lines:5d}", flush=True)
                    except Exception as exc:  # noqa: BLE001
                        journal.log("passes", f"ERR {name} "
                                              f"{type(exc).__name__}: {exc}")
                        continue
        except KeyboardInterrupt:
            journal.log("stop", "passes interrupted")
        finally:
            fh.close()
            journal.log("end", "passes")
        print()
        print(tables.passes_table(tables.load("build_sweep/passes.jsonl")))
        return True

    def _sweep_scan(self, count: int, scrolls: int) -> bool:
        """Breadth: many pages, one configuration, the full end-to-end read.

        This is the tier that answers a *rate* — how often a search control
        or a pager is actually found on the open web, and how often enacting
        one advances the page. A rate needs pages, so this runs one
        configuration over as many as it is given, with pagination live and
        ten scrolls each, exactly as a reader would drive it.

        Resumable and journaled: killed at any point it loses at most the
        page in flight, and `sweep status` reads the remainder from the
        record rather than from a file that claims to know it.
        """
        import shutil
        import tempfile

        from ..experiments import journal
        from ..experiments.sweep import Recorder, run_page
        from ..workspace import Workspace

        driver = getattr(self.nav, "driver", None)
        if driver is None:
            self.state.buffers.note("sweep scan needs a live browser")
            return True
        corpus = Path(self._sweep_corpus)
        if not corpus.exists():
            self.state.buffers.note(f"no corpus: {corpus} missing")
            return True
        urls = [u.strip() for u in
                corpus.read_text(encoding="utf-8").splitlines() if u.strip()]
        rec = Recorder("build_sweep/runs.jsonl")
        todo = [u for u in urls if not rec.has(u, "default")][:count]
        journal.log("start", f"scan {len(todo)} page(s) of {len(urls)}, "
                             f"{scrolls} scroll(s) each")
        done = ok = 0
        # A dead browser does not announce itself: every page after it just
        # returns "no sensor", and a run that keeps going writes those into
        # the record as though they were readings. One run recorded 333 such
        # rows after Firefox died at page 67 — an 83% "failure rate" that was
        # really one failure repeated. Consecutive losses now rebuild the
        # browser, and if that cannot be done the run stops rather than
        # manufacturing data.
        consecutive = 0
        try:
            for u in todo:
                if consecutive >= 3:
                    journal.log("recover", f"browser lost after {done}; "
                                           "rebuilding")
                    try:
                        from ..browser import build_driver
                        from ..config import load_config
                        try:
                            driver.quit()
                        except Exception:
                            pass
                        driver = build_driver(load_config(), headless=True)
                        driver.set_page_load_timeout(45)
                        self.nav.driver = driver
                        consecutive = 0
                        journal.log("recover", "browser rebuilt")
                    except Exception as exc:  # noqa: BLE001
                        journal.log("abort", f"cannot rebuild: {exc}")
                        self.state.buffers.note(
                            f"scan aborted: browser unrecoverable after {done}")
                        break
                tmp = tempfile.mkdtemp(prefix="wfh_scan_")
                try:
                    with Workspace(tmp) as ws:
                        sub = Repl(store=ws.store, workspace=ws)
                        sub.state.rows, sub.state.cols = 40, 110
                        sub.nav.driver = driver
                        row = run_page(sub, u, "default", {}, scrolls)
                        row["tier"] = "breadth"
                        row["requested"] = u
                        rec.add(row)
                        done += 1
                        if row.get("ok"):
                            ok += 1
                            consecutive = 0
                        else:
                            consecutive += 1
                        journal.log(
                            "scan",
                            f"{'ok ' if row.get('ok') else 'ERR'} "
                            f"srch={row.get('search_found', 0)} "
                            f"pagr={row.get('pagination_found', 0)} "
                            f"pages={row.get('pages_reached', 0)} "
                            f"{row.get('elapsed_s', 0):.1f}s  {u[:58]}")
                        print(f"  {done:5d}/{len(todo)} "
                              f"{row.get('elapsed_s', 0):5.1f}s "
                              f"srch={row.get('search_found', 0):3d} "
                              f"pagr={row.get('pagination_found', 0):3d} "
                              f"pg={row.get('pages_reached', 0):2d} "
                              f"{u[:52]}", flush=True)
                finally:
                    shutil.rmtree(tmp, ignore_errors=True)
        except KeyboardInterrupt:
            journal.log("stop", f"scan interrupted after {done}")
        except Exception as exc:  # noqa: BLE001 - a crash must leave a trace
            journal.log("crash", f"scan: {type(exc).__name__}: {exc}")
            raise
        finally:
            rec.close()
            journal.log("end", f"scan {done} page(s), {ok} ok")
        from ..experiments import tables
        print()
        print(tables.detection_table(tables.load(), limit=0))
        return True

    def _sweep_meta(self, verb: str, args) -> bool:
        """`status`, `resume`, `journal` — the three questions after a crash.

        A sweep that dies leaves a record of what it measured and no account
        of what it owed. These answer that from the plan and the record
        alone: what remains is derived, never stored, because a third file
        claiming to know the remainder is a third file that can be wrong.
        """
        from ..experiments import journal
        from ..experiments.run_sweep import CONFIGS

        panel = Path("build_sweep/depth.txt")
        pages = ([u.strip() for u in
                  panel.read_text(encoding="utf-8").splitlines() if u.strip()]
                 if panel.exists() else [])
        axes = [n for n, v in CONFIGS.items() if not v.get("__original__")]
        rows = journal.load("build_sweep/compare.jsonl")

        if verb == "journal":
            n = int(args[1]) if len(args) > 1 else 40
            print(journal.tail(n))
            return True
        if verb == "status":
            secs = 0.0
            done = [r for r in rows if r.get("drain_ms")]
            if done:
                secs = 6.0        # measured median for one axis re-read
            print(journal.status_table(pages, axes, rows, secs))
            return True
        # resume: pick up whatever the plan still owes
        scrolls = int(args[1]) if len(args) > 1 else 10
        left = journal.progress(pages, axes, rows)["left"]
        if not left:
            self.state.buffers.note("nothing left: the plan is complete")
            print("  nothing left — the plan is complete")
            return True
        print(f"  resuming: {left} run(s) outstanding")
        return self._sweep_compare(len(pages), scrolls)

    def _sweep_compare(self, pages: int, scrolls: int) -> bool:
        """The encoding contrast, done the only way it can be done honestly.

        One page load, every axis read back-to-back against it. Visiting a
        page once per configuration cannot work: a live document differs
        between visits, pagination multiplies the content by however many
        pages a run reached, and a redirect ends one arm and not another.
        Two arms of the *same* configuration came out 235% apart that way,
        and holding the page still only brought it to 7.5% while leaving
        eleven configurations stuck on an identical truncated read.

        Here the page is loaded once and scrolled once; then each axis
        re-reads that settled document. The content is the same content for
        every arm by construction, so a difference is the encoding.
        """
        import json as _json
        import time as _t

        from ..experiments import journal, tables
        from ..experiments.run_sweep import CONFIGS

        driver = getattr(self.nav, "driver", None)
        if driver is None:
            self.state.buffers.note("sweep compare needs a live browser")
            return True
        panel = Path("build_sweep/depth.txt")
        if not panel.exists():
            self.state.buffers.note("no panel: build_sweep/depth.txt missing")
            return True
        urls = [u.strip() for u in
                panel.read_text(encoding="utf-8").splitlines()
                if u.strip()][:pages]
        names = [n for n, v in CONFIGS.items() if not v.get("__original__")]
        out = Path("build_sweep/compare.jsonl")
        out.parent.mkdir(parents=True, exist_ok=True)
        # Resume: skip work already recorded, keyed on the url that was
        # *requested*. A run that opens page 1 and scrolls ends on page 5,
        # and a record that remembers only where it ended cannot tell that
        # page 1 was done — it would re-run it every start, forever.
        done = journal.done_keys(journal.load(out))
        journal.log("start", f"compare {len(urls)} page(s) x {len(names)} "
                             f"axes, {len(done)} already recorded")
        fh = out.open("a", encoding="utf-8")
        try:
            for u in urls:
                # Skip a finished page before loading it. Resume was opening
                # and scrolling every page in the plan just to discover its
                # axes were done — three minutes of browser work to write
                # nothing, which on a short run consumed the whole budget
                # before reaching the pages that still owed rows.
                # A page is resumed whole or not at all. Every axis for a
                # page has to read the *same load*: resuming halfway means
                # the axes recorded before the interruption saw a different
                # document than the ones after it, and the contrast between
                # them is then a comparison of two pages. A part-finished
                # page is therefore redone from scratch, and its earlier
                # rows are superseded by the load id below.
                if all((u, n) in done for n in names):
                    print(chr(10) + "  " + u[:70] + "   [complete, skipped]",
                          flush=True)
                    continue
                print(chr(10) + "  " + u[:70], flush=True)
                load_id = f"{int(_t.time() * 1000):x}"
                self.command(f"open {u}")
                _t.sleep(1.5)
                # Scroll the live page once, with everything on, so the
                # document under test is a scrolled one — then measure the
                # axes against that same settled document.
                for _ in range(scrolls):
                    if not self.extend() or self._exhausted:
                        break
                settled = (self._sensor.url if self._sensor else u) or u

                # The original serializer, measured against the *same* loaded
                # page as every axis below it. It belongs in this table and
                # not in a command of its own: a baseline kept somewhere else
                # is a baseline nobody reads, and the whole question is how
                # the variants compare to where this design started.
                try:
                    from ..baseline import DeepSerializerBaseline
                    ob = DeepSerializerBaseline(driver, settled)
                    bp = ob.pass_once(0)
                    orow = {"requested": u, "url": settled,
                            "variant": "ORIGINAL", "load": load_id,
                            "wire_bytes": bp.wire_bytes,
                            "lines": bp.nodes_kept, "chunks": 0,
                            "drain_ms": bp.total_ms,
                            "variants_reported": {"original": True},
                            "t": _t.time()}
                    fh.write(_json.dumps(orow, separators=(",", ":")) + chr(10))
                    fh.flush()
                    done.add((u, "ORIGINAL"))
                    print(f"    {'ORIGINAL':14s} wire={bp.wire_bytes:8,d} "
                          f"kept={bp.nodes_kept:5d} of {bp.nodes_total:5d}",
                          flush=True)
                except Exception as exc:  # noqa: BLE001
                    journal.log("baseline", f"{type(exc).__name__}: {exc}")

                for name in names:
                    self.variants = dict(CONFIGS[name])
                    self._sensor = None
                    self._live_chunks.clear()
                    self._passes.clear()
                    if not self.sense(settled):
                        continue
                    p = self._passes[-1] if self._passes else None
                    if p is None:
                        continue
                    rep = (p.stats or {}).get("variants") or {}
                    row = {"requested": u, "url": settled, "variant": name,
                           "load": load_id,
                           "wire_bytes": p.wire_bytes, "lines": p.lines,
                           "chunks": p.changed, "drain_ms": p.drain_ms,
                           "variants_reported": rep, "t": _t.time()}
                    fh.write(_json.dumps(row, separators=(",", ":")) + chr(10))
                    fh.flush()
                    done.add((u, name))
                    journal.log("row", f"{name} {p.wire_bytes}B "
                                       f"{p.lines}ln  {u[:60]}")
                    print(f"    {name:14s} wire={p.wire_bytes:8,d} "
                          f"lines={p.lines:5d} chunks={p.changed:4d}",
                          flush=True)
        except KeyboardInterrupt:
            journal.log("stop", "compare interrupted")
            self.state.buffers.note("sweep compare interrupted")
        except Exception as exc:  # noqa: BLE001 - a crash must leave a trace
            journal.log("crash", f"{type(exc).__name__}: {exc}")
            raise
        finally:
            fh.close()
            journal.log("end", f"compare, {len(done)} row(s) recorded")
        print()
        print(tables.compare_table(tables.load("build_sweep/compare.jsonl")))
        return True

    def _sweep_run(self, pages: int, scrolls: int) -> bool:
        """Batch every configuration over the panel's first `pages` pages.

        Configurations are interleaved per page and shuffled, because running
        each as a block confounds it perfectly with time: every `default`
        visit would land minutes before every `pathdelta` visit, and a live
        page differs between visits.
        """
        import random
        import shutil
        import tempfile

        from ..experiments import tables
        from ..experiments.run_sweep import CONFIGS
        from ..experiments.sweep import Recorder, run_page
        from ..workspace import Workspace

        driver = getattr(self.nav, "driver", None)
        if driver is None:
            self.state.buffers.note("sweep run needs a live browser")
            return True
        panel = Path("build_sweep/depth.txt")
        if not panel.exists():
            self.state.buffers.note("no panel: build_sweep/depth.txt missing")
            return True
        urls = [u.strip() for u in
                panel.read_text(encoding="utf-8").splitlines() if u.strip()]
        urls = urls[:pages]
        names = [n for n, v in CONFIGS.items() if not v.get("__original__")]
        rec = Recorder("build_sweep/runs.jsonl")
        rng = random.Random(20260819)
        done = skipped = 0
        try:
            for u in urls:
                todo = [n for n in names if not rec.has(u, n)]
                rng.shuffle(todo)
                for name in todo:
                    tmp = tempfile.mkdtemp(prefix="wfh_sweep_")
                    try:
                        with Workspace(tmp) as ws:
                            sub = Repl(store=ws.store, workspace=ws)
                            sub.state.rows, sub.state.cols = 40, 110
                            sub.nav.driver = driver
                            # `stay=True`: the contrast holds the page
                            # still. Pagination is measured in the breadth
                            # tier, over many pages under one configuration.
                            row = run_page(sub, u, name, CONFIGS[name],
                                           scrolls, stay=True)
                            row["tier"] = "depth"
                            rec.add(row)
                            done += 1
                            if not row.get("ok"):
                                skipped += 1
                            print(f"  {name:14s}{row.get('elapsed_s', 0):6.1f}s "
                                  f"wire={row.get('wire_bytes', 0):8,d} "
                                  f"lines={row.get('lines', 0):5d} "
                                  f"{'ok' if row.get('ok') else row.get('error','')}"
                                  f"  {u[:44]}", flush=True)
                    finally:
                        shutil.rmtree(tmp, ignore_errors=True)
        except KeyboardInterrupt:
            self.state.buffers.note("sweep run interrupted")
        finally:
            rec.close()
        print()
        print(tables.variants_table(tables.load()))
        self.state.buffers.note(f"sweep run: {done} row(s), {skipped} failed")
        return True

    def _cmd_stats(self, args) -> bool:
        """What this session has cost, per stage, per pass.

        Reads the passes the sensor already produced — it measures the
        pipeline without knowing anything about which algorithms the sensor
        is running, so a new mechanism needs no change here and this cannot
        drift into a second reading of the same work.
        """
        import statistics as st

        if not self._passes:
            self.state.buffers.note("nothing sensed yet")
            return True
        moved = [p for p in self._passes if p.changed]
        still = [p for p in self._passes if not p.changed]
        lines = [f"{len(self._passes)} pass(es), {len(moved)} with a delta"]
        if moved:
            for label, vals in (
                    ("sense", [p.drain_ms for p in moved]),
                    ("decode", [p.decode_ms for p in moved]),
                    ("store", [p.store_ms for p in moved])):
                lines.append(f"  {label:7s} p50 {st.median(vals):8.1f} ms  "
                             f"max {max(vals):8.1f} ms")
            lines.append(f"  chunks {sum(p.changed for p in moved)}, "
                         f"lines {sum(p.lines for p in moved)}")
        if still:
            lines.append(f"  quiet   p50 "
                         f"{st.median([p.drain_ms for p in still]):8.1f} ms")
        last = self._passes[-1].stats or {}
        if last:
            lines.append(f"  in-page folds {last.get('folds', 0)}, "
                         f"chunks {last.get('chunks', 0)}, "
                         f"observers {last.get('observers', 0)}, "
                         f"deduped {last.get('deduped', 0)}, "
                         f"errors {last.get('errors', 0)}")
        if moved or still:
            lines.append(f"  wire    {sum(p.wire_bytes for p in self._passes)} B "
                         f"over {len(self._passes)} pass(es), "
                         f"{sum(p.wire_bytes for p in still)} B of it idle")
        # Printed, not noted. `note` keeps one status line, so a report sent
        # through it showed only its own last row — a stats command whose
        # output you could not read.
        for line in lines:
            print(line)
        self.state.buffers.note(lines[0])
        return True

    def _cmd_variant(self, args) -> bool:
        """Turn a sensor mechanism on or off, then re-read the live page.

        `variant` alone lists what is set; `variant dedup on` switches one.
        The sensor is rebooted so the next drain is a cold reading under the
        new setting, which makes two mechanisms comparable on the same page
        in the same session.
        """
        if not args:
            self.state.buffers.note(
                "variants: " + (", ".join(f"{k}={v}" for k, v in
                                          sorted(self.variants.items()))
                                or "none set"))
            return True
        name = args[0]
        value = True if len(args) < 2 else args[1].lower() in ("on", "true", "1")
        self.variants[name] = value
        self._sensor = None          # reboot under the new setting
        self._live_chunks.clear()
        self.state.buffers.note(f"variant {name} = {value}; re-reading")
        if self.nav.live:
            self.sense()
        return True

    # The axes, and what each one costs to turn off. Named here so `compare`
    # and `variant` agree about what the design space contains.
    AXES = {
        # settled mechanisms, on by default
        "gate": "II §10 emit only chunks whose digest moved",
        "cache": "II §6  clean-record early return (incrementality itself)",
        "dedup": "II §7  sketch-then-verify subsumption",
        "intern": "II §10 interned segments instead of raw strings",
        # transport: the payload is ~45% path, ~22% text, and drain time
        # tracks payload at ~0.9 ms/KB, so this is where a pass is spent
        "pathdelta": "path as (shared prefix, suffix) against the line before",
        "shape": "tag-sequence table sent once, lines carry id + ordinals",
        "valdict": "intern line values, not only path segments",
        "packed": "int runs as one delimited string, not a JSON array",
        # work avoided
        "subtreegate": "never descend a subtree whose digest has not moved",
        "spans": "re-aggregate only the dirty child range, invertibly",
        "fused": "one round trip per pass instead of step-then-drain",
        # chunking policy
        "merge": "gather tiny adjacent siblings back into one chunk",
        "semantic": "let a list item or row overrun rather than be cut",
        "rank": "heaviest subtree first, not document order",
        # observation
        "attrs": "every attribute is content, not the chosen ten",
        "charwatch": "watch text mutations (off = stop watching them)",
        "perchunk": "an observer per chunk root, not one per document",
        # scheduling
        "lazy": "no timer: fold only when drained",
        "eager": "fold inside the mutation callback, no debounce",
        # addressing
        "anchored": "erase ordinals below the deepest landmark",
        "idanchor": "root the path at the nearest id, so it survives edits",
        # suppression
        "simhash": "near-duplicate collapse instead of exact containment",
        "crosspage": "skip content the receiver already holds under another url",
        # semantics, not cost — judge with `verify`, not `compare`
        "viewport": "emit what is on or near the screen first",
        # proposed from what the sweep measured, not from the design space
        "chunkdelta": "send a chunk as a diff against the version held",
        "textdict": "intern prose word-by-word, where whole values never repeat",
        "coalesce": "hold a thin payload until it is worth the crossing",
        "deepgate": "stop the fold re-summing a branch whose digest has not moved",
    }

    # Axes that change *what is read*, not merely how it travels. Their
    # output is supposed to differ from the baseline, so an equivalence
    # check that flagged them would be reporting the design as a defect.
    LOSSY = {"dedup", "simhash", "viewport", "crosspage", "attrs"}
    # Axes that regroup or reorder the same lines rather than change them.
    REGROUPING = {"merge", "semantic", "rank"}
    # Axes that rewrite the address itself.
    READDRESSING = {"anchored", "idanchor"}

    # `shape` supersedes `pathdelta` in the page (both rewrite the same
    # field), so a sweep that reports both as independent wins is
    # double-counting. Named here so `compare` can say so rather than leave
    # it to be noticed.
    OVERLAPPING = [("shape", "pathdelta")]

    def _cmd_compare(self, args) -> bool:
        """Read the open page under each setting of an axis, side by side.

        `compare` sweeps every axis; `compare cache dedup` sweeps those. Each
        configuration re-boots the sensor, so every column is a cold reading
        of the same document and the numbers are comparable. This is the
        whole point of the variant machinery — a design space you cannot
        measure from the terminal is a list of opinions.
        """
        if not self.nav.live or getattr(self.nav, "driver", None) is None:
            self.state.buffers.note("compare needs a live page")
            return True
        names = [a for a in args if a in self.AXES] or list(self.AXES)
        restore = dict(self.variants)
        rows = []
        # The baseline goes first, and it is not one of our variants: it is
        # the original deep serializer, running its own code (see
        # domvec/baseline.py). Every axis below is a departure from it, so a
        # sweep that does not include it compares our choices only against
        # each other — which can show an improvement that is really a
        # regression from where we started.
        try:
            from ..baseline import DeepSerializerBaseline

            base = DeepSerializerBaseline(self.nav.driver,
                                          self.nav.current_url)
            cold = base.pass_once(0)
            idle = base.pass_once(1)      # same page, unchanged
            for label, b in (("cold", cold), ("idle", idle)):
                rows.append(("ORIGINAL", "--", label, b.nodes_kept,
                             b.nodes_total, 0, b.wire_bytes, b.total_ms))
        except Exception as exc:  # noqa: BLE001 - a missing baseline is a datum
            self.state.buffers.note(f"baseline: {type(exc).__name__}: {exc}")
        try:
            for axis in names:
                for value in (True, False):
                    self.variants = dict(restore)
                    self.variants[axis] = value
                    self._sensor = None
                    self._live_chunks.clear()
                    self._passes.clear()
                    if not self.sense():
                        continue
                    cold = self._passes[-1]
                    # A second reading of a page that has not changed. Half
                    # the design space is invisible without it: `gate` and
                    # `cache` cost nothing on a cold read by construction —
                    # everything is new and everything must be folded — and
                    # comparing them on one read would say they do nothing,
                    # which is exactly backwards. What they do is make the
                    # *next* read cheap.
                    self.sense()
                    idle = self._passes[-1] if len(self._passes) > 1 else cold
                    for label, p in (("cold", cold), ("idle", idle)):
                        s = p.stats or {}
                        rows.append((axis, "on" if value else "off", label,
                                     p.changed, p.lines,
                                     int(s.get("folds") or 0), p.wire_bytes,
                                     p.drain_ms))
        finally:
            self.variants = restore
            self._sensor = None
            self._live_chunks.clear()

        # `chunks`/`lines` are the sensor's units; for the baseline row the
        # same two columns carry nodes-kept and nodes-total, which are the
        # comparable quantities — what it decided to keep, out of what it
        # looked at. Labelled so the row cannot be misread as chunks.
        out = [f"{'axis':9s} {'':4s} {'pass':5s} {'kept/ch':>8s} {'seen/ln':>8s} "
               f"{'folds':>8s} {'wire B':>9s} {'total ms':>9s}"]
        for axis, on, label, ch, ln, folds, wire, drain in rows:
            out.append(f"{axis:9s} {on:4s} {label:5s} {ch:8d} {ln:8d} "
                       f"{folds:8d} {wire:9d} {drain:9.1f}")
        for line in out:
            print(line)
        self.state.buffers.note(
            f"compared {len(names)} axis/axes over {len(rows)} reading(s)")
        return True

    # The canonical verification targets, in the order they matter. Held here
    # rather than in a script because the REPL is the test surface: `targets`
    # says which are reachable right now, and `targets run` reads each one.
    TARGETS = [
        ("archive.org", "https://archive.org/search?query=university+library",
         "shadow-DOM search results, deep pagination"),
        ("ddg", "https://html.duckduckgo.com/html/?q=university+library",
         "generic search results, submit-button pager"),
        ("bing", "https://www.bing.com/search?q=university+library",
         "generic search results, anchor pager"),
        ("youtube", "https://www.youtube.com/results?search_query=university+library",
         "infinite scroll, adversarial control labels"),
        ("shadow", "", "local composed-tree fixture: nested shadow roots"),
        # Ground truth. Every other target is checked for self-consistency —
        # it grew, the pages differ — which cannot catch a pager that skips
        # page 3 or loops. This site has exactly 10 pages of 10 quotes, a
        # fact independent of anything we compute, so the trail can be
        # checked against the world instead of against itself.
        ("quotes", "https://quotes.toscrape.com/page/1/",
         "known ground truth: 10 pages x 10 quotes, sequential pager"),
    ]

    # `<target>` is the retrieval query; `<target>:site` is what gets typed
    # into the page's own search box. They differ because one interrogates
    # our store and the other interrogates the site.
    QUERIES = {"quotes": "life love inspirational",
               "quotes:site": "love",
               "shadow": "catalogue",
               "ddg:site": "glacier",
               "bing:site": "glacier",
               "archive.org:site": "glacier"}

    # url -> (expected page count, the url pattern pages must follow)
    GROUND_TRUTH = {
        "quotes": (10, "/page/{n}/"),
    }

    def _cmd_targets(self, args) -> bool:
        """Which verification targets are reachable, and optionally read them.

        archive.org leads the list deliberately. It is the demanding case —
        a results page carrying well over a thousand shadow roots — and when
        it is down there is nothing to substitute for it, so the honest thing
        is for the REPL to say so every time rather than for the gap to be
        remembered or not. `targets run` opens each reachable one.
        """
        from pathlib import Path as _P
        fixture = (_P(__file__).resolve().parents[2]
                   / "tests" / "fixtures" / "shadow_catalogue.html")
        rows = []
        for name, url, why in self.TARGETS:
            url = url or (fixture.as_uri() if fixture.exists() else "")
            if not url:
                rows.append((name, "missing", why, url))
                continue
            state = "unchecked"
            driver = getattr(self.nav, "driver", None)
            if driver is not None:
                try:
                    driver.get(url)
                    body = driver.execute_script(
                        "return (document.body && document.body.innerText"
                        " || '').slice(0, 200);") or ""
                    # Counted through the composed tree. `querySelectorAll`
                    # stops at every shadow boundary, so it under-reports
                    # exactly the pages this list exists to exercise — it
                    # called the nested-shadow fixture "thin(12)".
                    n = driver.execute_script("""
                        var n = 0;
                        (function walk(root) {
                          var els = root.querySelectorAll('*');
                          n += els.length;
                          for (var i = 0; i < els.length; i++) {
                            if (els[i].shadowRoot) walk(els[i].shadowRoot);
                          }
                        })(document);
                        return n;""")
                    if "Temporarily Offline" in body or "503" in body[:40]:
                        state = "OFFLINE"
                    elif int(n or 0) < 40:
                        state = f"thin({n})"
                    else:
                        state = f"up({n})"
                except Exception as exc:  # noqa: BLE001
                    state = type(exc).__name__
            rows.append((name, state, why, url))

        for name, state, why, _url in rows:
            print(f"  {name:11s} {state:12s} {why}")
        offline = [n for n, s, _w, _u in rows if s in ("OFFLINE", "missing")]
        if offline:
            print(f"  -- unreachable right now: {', '.join(offline)}")
        if args and args[0] == "run":
            for name, state, _why, url in rows:
                if state.startswith(("up", "thin")) and url:
                    print(f"\n> open {url}")
                    self.command(f"open {url}")
        self.state.buffers.note(
            f"{len(rows) - len(offline)}/{len(rows)} target(s) reachable")
        return True

    def _cmd_verify(self, args) -> bool:
        """Run the acceptance battery against a target and print a verdict.

        One command, so that verifying a target needs no script and no
        remembering what the checks were. `verify archive.org` is the whole
        of the archive.org requirement: when the service is down it reports
        UNREACHABLE and nothing else, and when it is back the same command
        answers it in full.
        """
        named = args or ["ddg"]
        from pathlib import Path as _P
        fixture = (_P(__file__).resolve().parents[2]
                   / "tests" / "fixtures" / "shadow_catalogue.html")
        table = {n: (u or (fixture.as_uri() if fixture.exists() else ""))
                 for n, u, _w in self.TARGETS}
        driver = getattr(self.nav, "driver", None)
        if driver is None:
            self.state.buffers.note("verify needs a live browser")
            return True

        overall = []
        for name in named:
            url = table.get(name, name)
            print(f"\n== verify {name} ==\n   {url[:96]}")
            checks = []
            self.command(f"open {url}")
            doc = self.state.document
            body = driver.execute_script(
                "return (document.body&&document.body.innerText||'').slice(0,90);") or ""
            if "Temporarily Offline" in body or "503" in body[:30] or not doc.lines:
                print("   UNREACHABLE — service is not serving content")
                overall.append((name, "UNREACHABLE"))
                continue

            start = len(doc.lines)
            checks.append(("sensed the page", start > 0, f"{start} lines"))

            # Let the page settle before reading addresses off it, and settle
            # means *stopped moving*, not "three passes". A first drain on a
            # page still building itself describes nodes about to be replaced
            # — Bing rewrites most of its result list after first paint — and
            # the delta stream corrects that on later passes. Measured cold
            # Bing scored 14%; measured once converged, 98%. A fixed count
            # scored whichever moment it happened to land on, which is a
            # measurement that reports the page's timing as the addressing's
            # quality.
            #
            # So: sense until the address set for the current URL is the same
            # twice running. Bounded, and if it never settles the check still
            # falls through and fails on the numbers rather than hanging.
            def _addr_set():
                here = (self._sensor.url if self._sensor else "") or url
                return here, {ln.address.xpath
                              for c in self._live_chunks.values()
                              if c.url == here for ln in c.lines}

            settled_after = 0
            here_url, previous = _addr_set()
            for attempt in range(1, 13):
                self.sense()
                here_url, current = _addr_set()
                if current and current == previous:
                    settled_after = attempt
                    break
                previous = current

            # Only the current document's addresses can be evaluated against
            # the current document. Once a pager has turned the page, the
            # previous page's addresses are not dead — they are correct for a
            # URL that is no longer loaded — and resolving them here counted
            # them as failures, which said 86/284 about a page that was fine.
            mine = [c for c in self._live_chunks.values() if c.url == here_url]
            other = len(self._live_chunks) - len(mine)
            addrs = [ln.address.xpath for c in mine for ln in c.lines]
            shadow = [a for a in addrs if "#shadow-root" in a]
            light = sorted({a for a in addrs if "#shadow-root" not in a})
            res = driver.execute_script(
                "var o=[];for(var i=0;i<arguments[0].length;i++){try{"
                "o.push(document.evaluate(arguments[0][i],document,null,9,null)"
                ".singleNodeValue?1:0);}catch(e){o.push(-1);}}return o;", light
            ) if light else []
            unresolved = sum(1 for v in res if v != 1)
            # Not 100%. A live page deletes its own nodes while being read —
            # Bing drops interstitial content moments after load — so an
            # address can be correct when taken and dead when checked, and a
            # later drain corrects it. Demanding perfection here demands the
            # page stop changing. 95% still fails loudly: the redirect bug
            # scored 30%, and a genuinely broken address scheme scores near 0.
            rate = (len(light) - unresolved) / max(1, len(light))
            checks.append(("addresses resolve in the page", rate >= 0.95,
                           f"{len(light) - unresolved}/{len(light)} light "
                           f"({rate:.0%}), "
                           f"{len(shadow)} shadow"
                           + (f", settled in {settled_after}"
                              if settled_after else ", NEVER SETTLED")
                           + (f", {other} chunk(s) from other pages skipped"
                              if other else "")))

            tax = {}
            for c in self._live_chunks.values():
                for ln in c.lines:
                    tax[ln.address.tag] = tax.get(ln.address.tag, 0) + 1
            checks.append(("taxonomy is populated", len(tax) >= 3,
                           ", ".join(f"{k}:{v}" for k, v in
                                     sorted(tax.items(), key=lambda kv: -kv[1])[:6])))

            self._exhausted = False
            self._trail = [(self._sensor.url if self._sensor else "") or url]
            self._fired = []
            self._capped = False
            self._idle = 0
            self._gates = {}
            # Read to the end of what is rendered, *then* drive the live page.
            # A fixed count of line-scrolls is not "read the page": 14 x 30
            # lines never reached the end of Bing's 743-line document, so the
            # live scroll never ran and the check reported no growth on a page
            # that had a working pager sitting at the bottom of it.
            for _ in range(400):
                before_top = self.state.top
                self.command(f"scroll {self.state.body_rows}")
                if self.state.top == before_top:
                    break
            self._capped = True
            for _ in range(12):
                if not self.extend() or self._exhausted:
                    self._capped = False
                    break
            grew = len(self.state.document.lines)
            # `grew >= start` was not a check — it cannot fail, and it passed
            # on a run where the document did not grow at all. A page either
            # yields more when read downward, or says it has no more to give.
            # "The document grows" is the infinite-scroll shape. Under
            # pagination the *corpus* grows while the open document is
            # replaced by one page — quotes went 169 -> 146 lines while
            # collecting seven pages, and reading that as a failure asks a
            # paginated site to behave like a scrolling one. Either kind of
            # growth counts; neither, on a page that has not said it is
            # finished, does not.
            pages_now = len(self.workspace.pages()) if self.workspace else 0
            checks.append((
                "reading downward yields more",
                grew > start or pages_now > 1 or self._exhausted,
                f"{start} -> {grew} lines, {pages_now} page(s) stored"
                + (" (exhausted)" if self._exhausted else "")))

            # --- pagination, as a property of the *sequence* ---------------
            # "Grew or said it was exhausted" is about one document. It cannot
            # tell a pager that turned three pages from one that did nothing
            # and declared itself finished, because both end with a document
            # that stopped changing. These check the trail instead.
            trail = list(self._trail)
            fired_nav = [l for k, l in self._fired if k == "navigate"]
            fired_inplace = [l for k, l in self._fired if k == "in-place"]

            # A page with no pager is a legitimate outcome and must not be
            # dressed up as a pass. It is reported as its own state.
            # Judged on the trail, not on whether we clicked. archive.org
            # advances by scrolling — the site paginates itself and rewrites
            # its own address — so keying this on our own enactment reported
            # "no pagination control was enacted" about a run that had just
            # collected four pages. What matters is that the pages advanced,
            # not who pressed what.
            if not self._fired and len(trail) <= 1:
                checks.append(("pagination advanced the page", None,
                               "no pager enacted and the address never moved"))
            else:
                checks.append((
                    "pagination advanced the page", len(trail) > 1,
                    f"{len(trail)} url(s): "
                    + " -> ".join(u.rsplit("/", 1)[-1][:24] or u[-24:]
                                  for u in trail[:4])
                    + (" ..." if len(trail) > 4 else "")))

            checks.append(("no page was visited twice",
                           len(trail) == len(set(trail)),
                           f"{len(trail)} visit(s), {len(set(trail))} distinct"))

            # Consecutive pages must actually differ. A pager that re-renders
            # page one under a new url advances the address and nothing else,
            # and every other check here would pass.
            worst, worst_pair = 0.0, ""
            for a, b in zip(trail, trail[1:]):
                # `.md` — the stored row's field. `.markdown` is the
                # in-flight MarkdownChunk's; reading the wrong one here
                # returns empty sets and the overlap check passes vacuously,
                # which is the failure mode this whole check exists to catch.
                sa = {c.md for c in self._page_chunks(a)}
                sb = {c.md for c in self._page_chunks(b)}
                if not sa or not sb:
                    continue
                # Jaccard over the union, not over the smaller side.
                # Normalising by the smaller set made a 25-chunk consent
                # interstitial look like an 80% duplicate of a 186-chunk
                # results page, because the handful of chunks it did have
                # were chrome the results page also has. Over the union, a
                # page that genuinely repeats another scores near 1 and a
                # page that is merely small scores low — which is the
                # distinction this check is for.
                overlap = len(sa & sb) / max(1, len(sa | sb))
                if overlap > worst:
                    worst, worst_pair = overlap, f"{a[-18:]} vs {b[-18:]}"
            if len(trail) > 1:
                checks.append(("consecutive pages differ", worst < 0.5,
                               f"worst overlap {worst:.0%}"
                               + (f" ({worst_pair})" if worst_pair else "")))

            # The refusal set is a claim about what will never be clicked, so
            # it is worth asserting rather than trusting. This reads the
            # labels actually enacted, not the ones the classifier declined.
            import re as _re
            banned = _re.compile(
                r"sign\s?(in|up|out)|log\s?(in|out)|register|subscribe"
                r"|checkout|buy|purchase|add to (cart|bag)|donate|delete"
                r"|remove|upload|publish|confirm|accept|consent|install", _re.I)
            bad = [l for _k, l in self._fired if l and banned.search(l)]
            checks.append(("no refused control was enacted", not bad,
                           f"{len(self._fired)} enacted"
                           + (f" — BANNED: {bad[:3]}" if bad else "")
                           + (f"; nav={len(fired_nav)} inplace={len(fired_inplace)}"
                              if self._fired else "")))

            # Against the world, where the world is known. Self-consistency
            # cannot catch a pager that skips a page or revisits one; a site
            # whose page numbering is a documented fact can.
            if name in self.GROUND_TRUTH and len(trail) > 1:
                import re as _re2
                expected, _pat = self.GROUND_TRUTH[name]
                nums = [int(m.group(1)) for u in trail
                        for m in [_re2.search(r"/page/(\d+)", u)] if m]
                sequential = nums == list(range(nums[0], nums[0] + len(nums)))                     if nums else False
                checks.append((
                    "pages arrive in order, none skipped",
                    sequential and len(nums) == len(trail),
                    f"page numbers {nums[:6]}"
                    + (" ..." if len(nums) > 6 else "")
                    + ("" if sequential else "  NOT SEQUENTIAL")))
                checks.append((
                    "stays within the site's real page count",
                    bool(nums) and max(nums) <= expected,
                    f"max page {max(nums) if nums else '-'} of {expected}"))

            # Termination is about looping, not about finishing. A run that
            # hits the cap while still turning fresh pages has more to give,
            # which is the opposite of broken; a run that hits the cap while
            # advancing nothing is stuck. Only the second is a failure.
            # Stuck is "the cap arrived and nothing had advanced", not
            # "the cap arrived". A 12-step run that collected seven pages and
            # would have collected more is bounded, not broken.
            stuck = self._capped and len(trail) <= 1
            checks.append((
                "pagination terminated cleanly", not stuck,
                "exhausted" if self._exhausted else
                (f"hit the 12-step cap after {len(trail)} page(s)"
                 if self._capped else "stopped")))

            # --- completeness -------------------------------------------
            # Without this every lossy axis looks free: `viewport` passed a
            # full battery while dropping 24 lines, because nothing compared
            # what was captured against what the page actually says. The
            # page's own innerText is the only reference available that we
            # did not produce ourselves.
            try:
                page_text = driver.execute_script(
                    "return (document.body && document.body.innerText || '');")
            except Exception:  # noqa: BLE001
                page_text = ""
            import re as _rc
            page_toks = set(_rc.findall(r"[A-Za-z0-9]{4,}", page_text.lower()))
            ours = " ".join(ln.text for c in self._live_chunks.values()
                            for ln in c.lines)
            our_toks = set(_rc.findall(r"[A-Za-z0-9]{4,}", ours.lower()))
            if page_toks:
                covered = len(page_toks & our_toks) / len(page_toks)
                checks.append((
                    "captured what the page says", covered >= 0.80,
                    f"{covered:.0%} of {len(page_toks):,} page token(s); "
                    f"missing {len(page_toks - our_toks):,}"))

            # --- address stability --------------------------------------
            # Addresses are stored and re-used in later sessions, so what
            # matters is not only that they resolve now but that they still
            # resolve after the page moves. Nothing measured this before.
            addrs = sorted({ln.address.xpath for c in self._live_chunks.values()
                            for ln in c.lines
                            if "#shadow-root" not in ln.address.xpath})[:400]
            if addrs:
                try:
                    # Shift an *indexed* step, not just any sibling. A
                    # first attempt inserted a div at the top of <body> and
                    # reported 100% survival — because `_xpath` omits the
                    # index when the ordinal is 1, and a bare `div` step
                    # matches any div child, so the union still found the
                    # real container. That measured nothing. Prepending a
                    # same-tag sibling inside the content container moves the
                    # ordinals the addresses actually depend on.
                    driver.execute_script(
                        "var c=document.body.firstElementChild;"
                        "while(c && c.children.length===1)"
                        " c=c.firstElementChild;"
                        "if(!c) return; var k=c.firstElementChild;"
                        "if(!k) return;"
                        "var n=document.createElement(k.tagName);"
                        "n.setAttribute('data-domvec-probe','1');"
                        "c.insertBefore(n,k);")
                    time.sleep(0.4)
                    res = driver.execute_script(
                        "var o=[];for(var i=0;i<arguments[0].length;i++){try{"
                        "o.push(document.evaluate(arguments[0][i],document,"
                        "null,9,null).singleNodeValue?1:0);}catch(e){"
                        "o.push(-1);}}return o;", addrs)
                    survived = sum(1 for v in res if v == 1) / len(addrs)
                    # Reported, not gated. 8.9% survival is the measured
                    # truth for absolute paths and gating on it would fail
                    # every target for a weakness we have only just made
                    # visible. The number is the point; the threshold is a
                    # decision for when an addressing axis can beat it.
                    checks.append((
                        "addresses survive a DOM edit", None,
                        f"{survived:.0%} of {len(addrs)} still resolve after "
                        "an element is inserted above them"))
                    driver.execute_script(
                        "var d=document.querySelector('[data-domvec-probe]');"
                        "if(d)d.remove();")
                except Exception as exc:  # noqa: BLE001
                    checks.append(("addresses survive a DOM edit", None,
                                   f"not measured: {type(exc).__name__}"))

            pages = self.workspace.pages() if self.workspace else []
            checks.append(("reached the database", bool(pages),
                           f"{len(pages)} page(s)"))
            if self.workspace:
                # --- search, checked the way pagination now is -------------
                # `bool(hits)` was the same shape as `grew >= start`: a
                # ranker that returned its first five rows for any question
                # passed it. Search is only working if the answer *depends on
                # the question*, so that is what these ask.
                #
                # The query has to exist in the corpus being verified — a
                # fixed "university library" found 0 hits on a quotes site
                # and reported the store as broken.
                query = self.QUERIES.get(name, "university library")
                hits = self.workspace.search(query, k=5)
                checks.append(("retrieval returns hits", bool(hits),
                               f"{len(hits)} hit(s) for {query!r}"))

                def _text(h):
                    return (getattr(h, "markdown", "")
                            or getattr(h, "md", "") or "").lower()

                # Responsiveness: hits must contain what was asked for.
                terms = [t for t in query.lower().split() if len(t) > 3]
                onterm = sum(1 for h in hits
                             if any(t in _text(h) for t in terms))
                checks.append((
                    "hits contain the query's terms", bool(hits) and onterm > 0,
                    f"{onterm}/{len(hits)} hit(s) mention {terms}"))

                # Discrimination: the falsifiable half. A corpus that answers
                # a word it has never seen is not ranking, it is listing.
                noise = "zzqxwv frobnicate quuxbaz"
                nhits = self.workspace.search(noise, k=5)
                checks.append((
                    "a query with no answer returns none", not nhits,
                    f"{len(nhits)} hit(s) for nonsense"))

                # Discrimination, the softer half: two different real
                # questions must not produce the same answer.
                other_q = "pagination next page results"
                ohits = self.workspace.search(other_q, k=5)
                top_a = _text(hits[0])[:120] if hits else ""
                top_b = _text(ohits[0])[:120] if ohits else ""
                checks.append((
                    "different queries rank differently",
                    not (top_a and top_b and top_a == top_b),
                    "same top hit" if (top_a and top_a == top_b)
                    else f"{len(ohits)} hit(s) for a second query"))

                # The page's own search control (OBJECT_MODEL 7.7). Detected
                # is not the same as working, so it is enacted and the answer
                # is read back.
                found = [ln for c in self._live_chunks.values()
                         for ln in c.lines
                         if ln.address is not None
                         and ln.address.tag == "search"]
                if not found:
                    checks.append(("the page's search is enactable", None,
                                   "no search control detected"))
                else:
                    before = self.nav.current_url
                    typed = self.QUERIES.get(name + ":site", "library")
                    res = self._gesture(found[0].address, "type", typed)
                    self._await_document(was=before)
                    self.sense()
                    now = self.nav.current_url
                    doc = self.state.document
                    # `.label` — a Widget's text is its label. Reading a
                    # `.text` that does not exist made the body empty for
                    # every line, so "the term is present" was false by
                    # construction and this check reported a working search
                    # as broken. Same shape as every other check that
                    # measured something other than what it claimed.
                    body = chr(10).join(
                        (w.label or "") for w in
                        (doc.lines[:400] if doc else [])).lower()
                    # The answer is what changed, not where. DuckDuckGo's
                    # html endpoint POSTs to the same path, so demanding a
                    # new url failed a search that had worked perfectly.
                    checks.append((
                        "the page's search is enactable",
                        bool(res.ok) and typed in body,
                        f"{typed!r} -> "
                        + ("term present" if typed in body else "term ABSENT")
                        + (", url changed" if now != before else ", same url")))

            # `None` is a third verdict, not a quiet pass. A page with no
            # pagination control has not demonstrated pagination and has not
            # failed at it either; folding that into PASS is how a check
            # starts reporting the absence of a feature as the presence of
            # one. It prints as N/A and does not affect the verdict.
            ok = all(c[1] for c in checks if c[1] is not None)
            for label, passed, detail in checks:
                mark = "N/A " if passed is None else ("PASS" if passed else "FAIL")
                print(f"   {mark}  {label:32s} {detail}")
            overall.append((name, "PASS" if ok else "FAIL"))

        print("\n   " + "  ".join(f"{n}={v}" for n, v in overall))
        self.state.buffers.note(
            "  ".join(f"{n}={v}" for n, v in overall))
        return True

    def _cmd_axes(self, args) -> bool:
        """What the design space contains, and what is set right now."""
        for name, why in self.AXES.items():
            state = self.variants.get(name, "default")
            print(f"  {name:7s} {str(state):8s} {why}")
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
        for hit in hits:
            chunk = MarkdownChunk(url=hit.url, xpath=hit.xpath)
            addresses = self.index.addresses_for(hit.cid)
            from ..markdown import MarkdownLine
            for text, (address, _value) in zip(hit.markdown.split("\n"), addresses):
                stripped = text.lstrip(" ")
                depth = (len(text) - len(stripped)) // 2
                chunk.lines.append(MarkdownLine(depth, stripped, address))
            chunks.append(chunk)
        self.load_chunks(chunks, title=f"search: {query}")
        self.state.buffers.note(f"{len(hits)} hit(s) for {query!r}")
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
        lines = [w for w in self.state.document.lines if w.address is not None]
        pairs = [(w.address, w.label) for w in lines if w.interactive]
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
        width = int(args[0]) if args and args[0].isdigit() else self.state.cols
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

        drawn = []
        for chunk in render_trie(spine.trie, context_window=self.context_window):
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

        lines = render_wireframe(drawn, styles, width=width,
                                 unicode=unicode_art)
        print()
        print(("=" if not unicode_art else "═") * width)
        print(f" {spine.url[:width - 2]}")
        print(("=" if not unicode_art else "═") * width)
        for line in lines[: self.state.rows * 3]:
            print(line.text)
        print()
        self.state.buffers.note(
            f"wireframe: {len(lines)} line(s) at {width} cols, "
            f"{len(styles)} box(es) measured")
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
        hits = [w for w in self.state.document.lines
                if w.interactive and needle in w.label.lower()]
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
        try:
            lines = int(args[0]) if args else self.state.body_rows
        except ValueError:
            self.state.buffers.note("scroll needs a number")
            return True
        before = self.state.top
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
                data = term.read()
                if not data:
                    break
                if not term.raw:
                    # No raw mode: the read is a typed line, so treat it as a
                    # command rather than as key events. This is the Windows
                    # and non-tty path, and it keeps the REPL usable there.
                    if not self.command(data.strip()):
                        break
                    continue
                if data == "\x03" or data == "q":
                    break
                if data == ":":
                    sys.stdout.write("\x1b[?25h\n:")
                    sys.stdout.flush()
                    if not self.command(sys.stdin.readline()):
                        break
                    sys.stdout.write("\x1b[?25l")
                    continue
                self.feed(data)


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
        prog="domvec-repl",
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
