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
from ..markdown import MarkdownChunk, read_jsonl
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
        delta = prefetched if prefetched is not None             else self._sensor.drain(self._sense_pass)
        self._sense_pass += 1
        # The drain is what learns the page has become a different page — an
        # enacted pager that navigates, a route change, a redirect. Reading
        # the address back afterwards is what keeps the new page's chunks
        # from being filed under the old page's URL.
        if self._sensor.url and self._sensor.url != url:
            url = self._sensor.url
            self._live_chunks.clear()
        self._seen_content.update(delta.contents)
        for chunk in delta.chunks:
            self._live_chunks[chunk.cid] = chunk
        # The sensor names removals by its own chunk id, which is the chunk's
        # `part`; the store and this map are keyed by `cid`, the hash of
        # (url, xpath, part). Popping by the raw id matched nothing, so a
        # removal would have been dropped on this side even once the sensor
        # started reporting one.
        gone = [c.cid for c in self._live_chunks.values()
                if c.part in set(delta.removed)]
        for cid in gone:
            self._live_chunks.pop(cid, None)

        # Straight to the database, as a delta. The workspace owns frequency
        # rows, embeddings, the graph and the markdown mirror together, so a
        # page becomes retrievable in the same motion that shows it.
        store_ms = 0.0
        if self.workspace is not None and (delta.chunks or gone):
            import time as _t
            started = _t.perf_counter()
            try:
                self.workspace.ingest_chunks(
                    url, delta.chunks, complete=False,
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
        if widget.kind in (WidgetKind.LINK, WidgetKind.IMAGE):
            from ..graphstore import canonical_url

            target = canonical_url(widget.label.strip("<>"),
                                   self.state.document.url)
            if target and self.load_url_from_store(target):
                self.state.buffers.note(f"opened {target} (from store)")
                return
            if target and self.nav.live:
                self.render_live(self.nav.visit(target))
                return
            self.state.buffers.note(f"no local copy of {target or widget.label}")
            return

        self.render_live(self.nav.click(address))

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
            self.state.buffers.note("need a line number")
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
                    res = self.nav.type_into(found[0].address, typed,
                                             submit=True)
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

    def _cmd_search(self, args) -> bool:
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
            self.render_live(
                self.nav.type_into(widget.address, text, submit=True))
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
    args = parser.parse_args(argv)

    repl = Repl()
    build = Path(args.build)
    if (build / "graph.kuzu").exists():
        from ..graphstore import GraphStore
        from ..search import ThreeFormIndex
        from ..vectors import FreqMatrix

        repl.store = GraphStore(build / "graph.kuzu")
        freq = FreqMatrix.load(build / "freq")
        repl.index = ThreeFormIndex(repl.store, freq).build()

    if args.target:
        repl.command(f"open {args.target}")

    if args.command:
        for command in args.command:
            repl.command(command)
        print(repl.render())
        return 0

    repl.run(mouse=not args.no_mouse)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
