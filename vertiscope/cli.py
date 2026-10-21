"""``vertiscope`` command-line interface.

Two stores are reachable from here, and the commands say which one they mean.

**The workspace** — a directory (default ``./build``) holding the address
trie's graph, the frequency matrix and the markdown checkpoint. This is what
the streaming scan writes and what retrieval reads::

    vertiscope scan <url>...           live streaming scan into a workspace
    vertiscope index <file|dir>...     the same destination, offline
    vertiscope find "<query>"          pagerank x frequency x semantic
    vertiscope browse [url]            the interactive REPL
    vertiscope where <aid|key|xpath>   an address back to its chunk
    vertiscope status                  what a workspace holds
    vertiscope purge -w <ws> --all     clear one

**The home store** — SQLite under ``~/.vertiscope``, written by the earlier
single-snapshot pipeline::

    vertiscope scrape <url>...         scan, chunk, index
    vertiscope chunk <file.html>       offline, no browser
    vertiscope search "<query>"        ranked retrieval
    vertiscope shell                   interactive retrieval REPL
    vertiscope ls · show · info        pages, one instance, index stats
    vertiscope purge --home-store --all

The second family is not deprecated and must not be quietly deleted: it is the
observation alphabet that ``scripts/audit_observables.py`` measures and that
COR-10.7 reasons about, and ``tests/test_model_obligations.py`` asserts that
position escapes through ``show`` and through nothing else. Removing a surface
shrinks that alphabet, which is a semantic change to MODEL §8.3's identity
analysis rather than a tidy-up.

What each family reports about stored content goes to stdout, unchanged.
Which store it read goes to stderr, because that is advice.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
import textwrap
import time
from pathlib import Path
from typing import List, Optional, Sequence, Tuple

from .config import load_config
from .markdown import DEFAULT_CONTEXT_WINDOW
from .ingest import ingest
from .pipeline import run_pipeline, scrape_url
from .retrieve import Hit, Retriever, SemanticUnavailable
from .store import Store

# --- output helpers --------------------------------------------------------

_COLOR = sys.stdout.isatty()


def _c(text: str, code: str) -> str:
    return f"\033[{code}m{text}\033[0m" if _COLOR else text


def bold(t: str) -> str:
    return _c(t, "1")


def dim(t: str) -> str:
    return _c(t, "2")


def cyan(t: str) -> str:
    return _c(t, "36")


def green(t: str) -> str:
    return _c(t, "32")


def yellow(t: str) -> str:
    return _c(t, "33")


def red(t: str) -> str:
    return _c(t, "31")


def _note(text: str) -> None:
    """Guidance, on stderr — never part of what a command reports.

    `scripts/audit_layout_sensitivity.py` compares command output across ingest
    permutations, and `test_model_obligations.py` asserts what may appear in
    it (COR-10.7). Both capture stdout. A pointer to the other store is advice
    about the machine, not an observation of the store, so it goes where advice
    goes and those results stay about what they were about.
    """
    print(text, file=sys.stderr)


DEFAULT_WORKSPACE = "build"


def _name_the_store(cfg, *, empty: bool) -> None:
    """Say which store was read, and where the content is if it is elsewhere.

    An empty home store printed "nothing scraped yet" on machines holding
    twenty scanned pages and forty thousand addresses — true of the store,
    false of the machine, and indistinguishable from the outside.
    """
    _note(dim(f"  store: {cfg.home}  (single-snapshot pipeline)"))
    if not empty:
        return
    workspace = Path(DEFAULT_WORKSPACE)
    if not (workspace / "graph.kuzu").exists():
        return
    _note(yellow(
        f"  a workspace exists at ./{DEFAULT_WORKSPACE} — this command does "
        f"not read it."))
    _note(yellow(
        f"  try:  vertiscope status -w {DEFAULT_WORKSPACE}   "
        f"or   vertiscope find \"<query>\" -w {DEFAULT_WORKSPACE}"))


def _human_bytes(n: int) -> str:
    x = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if x < 1024 or unit == "GB":
            return f"{x:.0f}{unit}" if unit == "B" else f"{x:.1f}{unit}"
        x /= 1024
    return f"{x:.1f}GB"


def print_hits(hits: Sequence[Hit], *, verbose: bool = False) -> None:
    if not hits:
        print(dim("  no matches"))
        return
    for h in hits:
        score = f"{h.score:.4f}"
        extra = ""
        if h.semantic_score is not None:
            extra = dim(f"  (lex {h.lexical_score:.3f} · sem {h.semantic_score:.3f})")
        print(f"{bold(f'{h.rank:>3}.')} {green(score)}{extra}  {cyan(h.url)}")
        print(f"     {dim(h.instance_id)} {dim(h.pattern[:70])}")
        body = h.preview(400 if verbose else 200)
        for line in textwrap.wrap(body, width=96) or ["(empty)"]:
            print(f"     {line}")
        print()


# --- commands --------------------------------------------------------------


def _open_workspace(args: argparse.Namespace, *, must_exist: bool = False):
    """Open the workspace named by ``args``, with an embedder if asked for.

    ``must_exist`` guards the read commands. Opening a workspace creates it,
    so a mistyped path silently produced an empty one and every query came
    back "no results" — a wrong answer that looks exactly like a correct one.
    Writing commands still create on demand, which is what they are for.
    """
    from .workspace import Workspace

    if must_exist and not (Path(args.workspace) / "graph.kuzu").exists():
        print(red(f"  no workspace at {args.workspace!r}"))
        print(dim("  create one with:  vertiscope scan <url>   or   "
                  "vertiscope index <file.html>"))
        raise SystemExit(2)

    embedder = None
    if getattr(args, "semantic", False):
        from .core.embedding_service import get_default_service

        embedder = get_default_service()
        print(dim(f"embedder: {embedder.status()}"))
    # `DEFAULT_CONTEXT_WINDOW`, not a literal. The window is a DECISION
    # (PLUGIN_PRD 0b: 256, where every structural property holds and retrieval
    # still beats 512 by ten points of hit@1), and a second copy of it here as
    # `1200` meant `vertiscope scan <url>` chunked at 1200 while the library, the
    # docs and every measurement said 256. A re-cut was only correct because
    # --window was passed explicitly.
    return Workspace(args.workspace,
                     context_window=getattr(args, "window",
                                            DEFAULT_CONTEXT_WINDOW),
                     embedder=embedder)


# Named points in the design space. Adding one here is the whole cost of
# trying it: `vertiscope scan <url> --sensor --variant <name>` runs it, and every
# read command afterwards works on the result unchanged.
SENSOR_VARIANTS = {
    "base":   {"gate": True,  "dedup": False},
    "dedup":  {"gate": True,  "dedup": True},
    "nogate": {"gate": False, "dedup": False},
}


def _variants(name: str) -> dict:
    return SENSOR_VARIANTS.get(name, SENSOR_VARIANTS["base"])


def cmd_scan(args: argparse.Namespace) -> int:
    """Live streaming scan: drive each page and fold in every snapshot."""
    from .config import load_config
    from .stream import ScanUpdate

    cfg = load_config()

    def show(result) -> None:
        print(f"  {green(str(result.addresses))} addresses  "
              f"{green(str(result.chunks))} chunks  "
              f"{result.lines} lines  "
              f"{result.passes} passes  "
              # As a ratio, not a "saving". The saving framing only makes
              # sense when the deltas are smaller than the document, and on a
              # small page read in several passes they are not — a 10 KB page
              # drained four times carries more structured JSON than HTML.
              # Printed as "-87.6% saved" that read like a fault; printed as
              # "1.88x the document" it reads like what it is.
              + (cyan(f"{result.wire_bytes / result.document_bytes:.2f}x")
                 + " the document on the wire"
                 if result.document_bytes else dim("wire not measured")))
        if result.report.unaccounted:
            print(red(f"  UNACCOUNTED {result.report.summary()}"))

    def report(stage: str, detail: str) -> None:
        if stage == "page":
            print(bold(f"\n{detail}"))
            print(dim(ScanUpdate.header()))
        elif stage == "error":
            print(red(f"  {detail}"))
        else:
            print(dim(detail))

    # One unreachable page must not end a corpus run.
    #
    # The `--legacy` branch below has always caught per-page failures and
    # carried on; the live `sense` and `crawl` paths did not, so a single
    # navigation timeout aborted every remaining url. A 24-page re-cut died on
    # its first page -- apnews.com, which refuses automation (403 to curl, a
    # 40s nav timeout under Selenium) -- and wrote nothing for the other 23.
    # The superseded path was the robust one.
    #
    # Failures are collected rather than swallowed. A scan that skipped a
    # third of its corpus and then printed a tidy stats table is exactly the
    # quiet degradation this project refuses, so the summary at the end names
    # every url with its reason and the exit code is non-zero.
    failures: List[Tuple[str, str]] = []

    with _open_workspace(args) as ws:
        common = dict(duration=args.duration, pause=args.pause,
                      passes=args.passes, incremental=not args.full_transport)
        for url in args.urls:
            if not getattr(args, "legacy", False) and not args.follow:
                print(bold(f"\n{url}"))
                try:
                    result = ws.sense(
                        url, config=cfg, scrolls=args.passes,
                        pause=args.pause, headless=not args.headful,
                        variants=_variants(getattr(args, "variant", "base")),
                        progress=report)
                except Exception as exc:  # noqa: BLE001
                    print(red(f"  {type(exc).__name__}: {exc}"))
                    failures.append((url, f"{type(exc).__name__}: {exc}"))
                    continue
                show(result)
                continue
            if args.follow:
                try:
                    results = ws.crawl(
                        url, max_pages=args.follow + 1, depth=args.depth,
                        same_host=not args.any_host, config=cfg,
                        headless=not args.headful,
                        legacy=getattr(args, "legacy", False),
                        variants=_variants(getattr(args, "variant", "base")),
                        progress=report, **common)
                except Exception as exc:  # noqa: BLE001
                    print(red(f"  {type(exc).__name__}: {exc}"))
                    failures.append((url, f"{type(exc).__name__}: {exc}"))
                    continue
                print(f"\n  crawled {green(str(len(results)))} page(s)")
                for result in results:
                    show(result)
                continue

            print(bold(f"\n{url}"))
            print(dim(ScanUpdate.header()))
            try:
                result = ws.scan(url, config=cfg, headless=not args.headful,
                                 progress=report, **common)
            except Exception as exc:  # noqa: BLE001
                print(red(f"  {type(exc).__name__}: {exc}"))
                failures.append((url, f"{type(exc).__name__}: {exc}"))
                continue
            show(result)
        print()
        _print_stats(ws.stats())

    if failures:
        # After the stats, not before. The stats say what the workspace got;
        # this says what it did NOT get, which is otherwise a number the
        # reader has to infer from a url count they never saw.
        print(red(f"\n  {len(failures)} of {len(args.urls)} page(s) failed:"))
        for url, why in failures:
            print(red(f"    {url}  --  {why}"))
        return 1
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    """Offline: index local HTML files into the same workspace."""
    paths: List[Path] = []
    for raw in args.paths:
        path = Path(raw)
        if path.is_dir():
            paths.extend(sorted(path.glob("*.html")))
        else:
            paths.append(path)

    with _open_workspace(args) as ws:
        for path in paths:
            if not path.exists():
                print(red(f"  missing: {path}"))
                continue
            url = args.url or path.resolve().as_uri()
            html = path.read_text(encoding="utf-8", errors="replace")
            result = ws.index_html(html, url, title=path.stem)
            print(f"  {path.name[:44]:44s} {result.addresses:6d} addr "
                  f"{result.chunks:5d} chunks {result.lines:6d} lines")
        print()
        _print_stats(ws.stats())
    return 0


def cmd_notes(args: argparse.Namespace) -> int:
    """Offline: index vault notes into the same workspace (`T-5`).

    The sibling of `cmd_index`: no browser, one document at a time, into the
    trie the scan writes. A directory is walked recursively, because a vault is
    a tree of folders and indexing only its top level would silently cover a
    fraction of it.

    `.obsidian/` is skipped. It holds the app's own JSON -- settings, workspace
    layout, plugin data -- which is not the user's notes and would put this
    session's pane geometry in a retrieval index.
    """
    from .vault import note_url

    targets: List[Tuple[Path, str, str]] = []   # (file, vault name, rel path)
    for raw in args.paths:
        path = Path(raw)
        if path.is_dir():
            vault = args.vault or path.resolve().name
            for md in sorted(path.rglob("*.md")):
                if ".obsidian" in md.relative_to(path).parts:
                    continue
                targets.append((md, vault, str(md.relative_to(path))))
        else:
            vault = args.vault or path.resolve().parent.name
            targets.append((path, vault, path.name))

    if not targets:
        print(red("  no .md files found"))
        return 2

    failures: List[Tuple[str, str]] = []
    with _open_workspace(args) as ws:
        for file, vault, rel in targets:
            if not file.exists():
                print(red(f"  missing: {file}"))
                failures.append((str(file), "missing"))
                continue
            try:
                text = file.read_text(encoding="utf-8", errors="replace")
                result = ws.index_note(text, rel, vault=vault)
            except Exception as exc:                # noqa: BLE001
                # Per-note, for the reason `cmd_scan` learned: one unreadable
                # note in a vault of thousands must not end the run.
                print(red(f"  {rel[:44]:44s} {type(exc).__name__}: {exc}"))
                failures.append((rel, f"{type(exc).__name__}: {exc}"))
                continue
            print(f"  {rel[:44]:44s} {result.addresses:6d} addr "
                  f"{result.chunks:5d} chunks {result.lines:6d} lines")
        print()
        _print_stats(ws.stats())

    if failures:
        print(red(f"\n  {len(failures)} of {len(targets)} note(s) failed:"))
        for rel, why in failures:
            print(red(f"    {rel}  --  {why}"))
        return 1
    return 0


def cmd_find(args: argparse.Namespace) -> int:
    """Three-form retrieval: pagerank x frequency x semantic."""
    from .search import SearchDiagnostics

    query = " ".join(args.query)
    with _open_workspace(args, must_exist=True) as ws:
        if getattr(args, "semantic", False):
            counts = ws._hydrate_embeddings(
                progress=lambda _s, detail: print(dim(f"  embedding {detail}")))
            if counts["loaded"] or counts["embedded"]:
                print(dim(f"  vectors: {counts['loaded']} loaded, "
                          f"{counts['embedded']} computed"))
        diag = SearchDiagnostics()
        hits = ws.search(query, k=args.k, floor=args.floor, diagnostics=diag)
        print(dim(f"  {diag.summary()}"))
        if not hits:
            # Name the factor. "No hit" from a product of three vetoes is
            # ambiguous in a way that matters: no term overlap, no semantic
            # similarity and an empty index all look identical from outside,
            # and the fix for each is different.
            n = diag.candidates
            if not n:
                print(yellow("  the workspace is empty — scan or index a page first"))
            elif diag.zeroed_by_lexical >= n:
                print(yellow(
                    f"  no hit: not one of {n} chunks shares a term with "
                    f"{query!r}."))
                print(dim("  Terms are matched exactly — there is no stemming, "
                          "so 'book' does not match 'books'."))
                print(dim("  Try a term from the text, or --floor 1e-6 to let "
                          "the other factors rank."))
            elif diag.semantic_available and diag.zeroed_by_semantic >= n:
                print(yellow("  no hit: the semantic factor vetoed every "
                             "candidate."))
            else:
                print(yellow("  no hit — a factor vetoed every candidate. "
                             "Try --floor 1e-6 to soften the product."))
            return 1
        for i, hit in enumerate(hits):
            print(f"\n{bold(f'[{i}]')} {cyan(f'{hit.score:.3e}')} "
                  f"{dim(f'rank={hit.rank:.2e} lex={hit.lexical:.3f} '
                          f'sem={hit.semantic:.3f}')}")
            print(f"    {hit.url}")
            print(f"    {dim(hit.xpath)}")
            for line in hit.preview(4).split("\n"):
                print(f"    {line[:100]}")
            if args.addresses:
                # The aid is printed so the two surfaces join up: a hit's
                # address can be handed straight to `vertiscope where`. Without
                # it the addresses were readable and not usable.
                for address, _value in ws.addresses_for(hit.cid)[:5]:
                    print(dim(f"      {address.aid}  {address.tag:18s} "
                              f"{address.xpath[:60]}"))
    return 0


def cmd_browse(args: argparse.Namespace) -> int:
    """The interactive REPL over a workspace."""
    from .repl.app import Repl

    # A live session writes what it visits, so an empty workspace is a valid
    # place to start — it fills as you browse. Only an offline session needs
    # one that already holds pages, because it has no way to make any.
    with _open_workspace(args, must_exist=args.offline) as ws:
        repl = Repl(store=ws.store, index=ws.index, workspace=ws)
        repl.state.rows, repl.state.cols = args.rows, args.cols

        # A browser, so the session can navigate the live web rather than
        # only re-read what was scanned earlier. `open <url>` then drives the
        # real pipeline: the in-page sensor is booted into the page and every
        # navigation, click and scroll drains what changed.
        driver = None
        if not args.offline:
            from .browser import build_driver
            from .config import load_config
            try:
                driver = build_driver(load_config(), headless=args.headless)
                repl.nav.driver = driver
            except Exception as exc:  # noqa: BLE001
                print(dim(f"  no browser ({type(exc).__name__}); "
                          f"offline browsing only"))
        if args.target:
            repl.command(f"open {args.target}")
        elif ws.pages():
            repl.command(f"open {ws.pages()[0]}")
        for command in args.command:
            repl.command(command)
        if args.feed:
            repl.run_fed()
            print(repl.render())
            return 0
        if args.command:
            print(repl.render())
            return 0
        repl.run(mouse=not args.no_mouse)
    return 0


def cmd_where(args: argparse.Namespace) -> int:
    """Resolve an address back to the chunk it anchors.

    The address is the one output type this whole pipeline produces, and
    until now nothing accepted one *back*. `find --addresses` printed them,
    `browse`'s `where` printed them, and neither form could be handed to
    anything — so the singular output type was write-only, and a hit's
    provenance stopped at whatever happened to be on screen.

    Three spellings are taken, because three are what the tool emits: the
    `aid` (sixteen hex digits), the full injective key, and the absolute
    xpath — which is the only one a person can read off a page and type.
    """
    target = " ".join(args.address).strip()
    with _open_workspace(args, must_exist=True) as ws:
        found = _resolve_address(ws.store, target)
        if not found:
            print(red(f"  no address matching {target!r}"))
            print(dim("  give an aid, a full key (url|xpath|tag|accessor), "
                      "or an absolute xpath"))
            return 1
        if len(found) > 1:
            print(dim(f"  {len(found)} addresses at that element"))
        for address, value in found[:args.k]:
            _print_address(ws.store, address, value, lines=args.lines)
    return 0


def _resolve_address(store, target: str):
    """Whichever of the three spellings was given."""
    from .address import ContentAddress

    if not target:
        return []
    if "|" in target:
        try:
            address = ContentAddress.parse(target)
        except Exception:  # noqa: BLE001
            return []
        found = store.address(address.aid)
        return [found] if found else []
    if target.startswith("/"):
        return store.addresses_at(target)
    found = store.address(target)
    return [found] if found else []


def _print_address(store, address, value: str, *, lines: int = 12) -> None:
    print()
    for name, shown in (("url", address.url), ("xpath", address.xpath),
                        ("tag", address.tag), ("accessor", address.accessor),
                        ("aid", address.aid), ("value", value)):
        print(f"  {bold(f'{name:9s}')} {shown}")
    print(f"  {bold('key      ')} {dim(address.key())}")

    chunk = store.chunk_for_address(address.aid)
    if chunk is None:
        print(dim("\n  anchored by no chunk"))
        return
    anchors = store.addresses_of(chunk.cid)
    at = next((i for i, (a, _v) in enumerate(anchors)
               if a.aid == address.aid), None)
    print(f"\n  {bold('chunk')} {chunk.cid} "
          f"{dim(f'part {chunk.part}, {chunk.line_count} line(s)')}")
    body = chunk.md.split("\n")
    # Show the anchored line in context rather than the whole chunk: the
    # question "where did this come from" is answered by its neighbours.
    lo = max(0, (at or 0) - lines // 2)
    for i, text in enumerate(body[lo:lo + lines], start=lo):
        mark = cyan(">") if i == at else " "
        print(f"    {mark} {dim(f'{i:3d}')} {text[:96]}")


def cmd_status(args: argparse.Namespace) -> int:
    with _open_workspace(args, must_exist=True) as ws:
        _print_stats(ws.stats())
        pages = ws.pages()
        if pages:
            print(f"\n  {bold('pages')}")
            for url in pages[:40]:
                print(f"    {url}")
            if len(pages) > 40:
                print(dim(f"    ... and {len(pages) - 40} more"))
    return 0


def _print_stats(stats: dict) -> None:
    print(f"  {bold('workspace')} {stats.get('path', '')}")
    for key in ("pages", "chunks", "addresses", "anchors", "contains",
                "links", "freq_rows", "freq_terms"):
        if key in stats:
            print(f"    {key:12s} {stats[key]:>10,}")


def cmd_scrape(args: argparse.Namespace) -> int:
    cfg = load_config(args.home)
    urls: List[str] = args.urls
    failures = 0

    with Store(cfg) as store:
        for url in urls:
            print(bold(f"→ {url}"))
            started = time.perf_counter()

            def progress(stage: str, detail: str) -> None:
                if args.quiet:
                    return
                label = f"  {stage:<8}"
                print(f"{dim(label)} {detail}", flush=True)

            try:
                result = scrape_url(
                    url,
                    cfg,
                    single_pass=args.single_pass,
                    max_duration=args.max_duration,
                    pause=args.pause,
                    headless=not args.headful,
                    char_budget=args.char_budget,
                    detect_signal_fields=args.signals,
                    progress=progress,
                )
            except Exception as exc:  # noqa: BLE001
                print(red(f"  FAILED: {type(exc).__name__}: {exc}"))
                failures += 1
                continue

            report = ingest(store, result)
            elapsed = time.perf_counter() - started
            s = result.summary()
            print(
                f"  {green('ok')} {s['chunks']} chunks · "
                f"{report.instances_written} instances · "
                f"{report.rows_indexed} indexed · "
                f"{s['patterns']} patterns · "
                f"{_human_bytes(s['html_bytes'])} html · {elapsed:.1f}s"
            )
            if result.search_fields and not args.quiet:
                sf = result.search_fields[0]
                print(dim(f"  search box: {sf.generalized_xpath}"))
            print()

        stats = store.stats()
    print(
        dim(
            f"index: {stats['indexed_rows']:,} rows · "
            f"{stats['vocab_size']:,} terms · {stats['pages']} pages"
        )
    )
    return 1 if failures else 0


def cmd_chunk(args: argparse.Namespace) -> int:
    """Offline: run the pipeline over a local HTML file. No browser."""
    cfg = load_config(args.home)
    path = Path(args.file)
    if not path.exists():
        print(red(f"no such file: {path}"))
        return 1
    html = path.read_text(encoding="utf-8", errors="replace")
    url = args.url or path.resolve().as_uri()

    result = run_pipeline(
        html,
        url,
        char_budget=args.char_budget or cfg.char_budget,
        detect_signal_fields=args.signals,
    )
    s = result.summary()
    print(json.dumps(s, indent=2))
    if args.stages:
        print("\nstage timings (ms):")
        for stage, ms in result.stage_ms.items():
            print(f"  {stage:<8} {ms:8.1f}")

    if args.index:
        with Store(cfg) as store:
            report = ingest(store, result)
            print(f"\nindexed {report.rows_indexed} rows from {report.instances_written}")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    cfg = load_config(args.home)
    with Store(cfg) as store:
        empty = store.tfidf.doc_count == 0
        _name_the_store(cfg, empty=empty)
        if empty:
            print(yellow("index is empty — run `vertiscope scrape <url>` first"))
            return 1
        retriever = Retriever(store)
        try:
            hits = retriever.search(
                args.query,
                k=args.k,
                urls=[args.url] if args.url else None,
                semantic=args.semantic,
            )
        except SemanticUnavailable as exc:
            print(yellow(f"  {exc}"))
            hits = retriever.search(
                args.query, k=args.k, urls=[args.url] if args.url else None
            )
        if args.json:
            print(json.dumps(
                [
                    {
                        "rank": h.rank, "instance_id": h.instance_id, "url": h.url,
                        # Rounded deliberately (THEORY COR-10.11). Scores are a
                        # float32 sum over rows, and float addition is not
                        # associative, so the low bits depend on row order.
                        # Emitting full precision made storage layout observable:
                        # the same corpus ingested in a different order printed
                        # 0.25546887516975403 against 0.25546884536743164.
                        # Rounding to 6 places is above the observed spread
                        # (~3e-8) and below any meaningful difference, so the
                        # output factors through the layout quotient (PROP-10.8).
                        "score": round(h.score, 6),
                        "lexical": round(h.lexical_score, 6),
                        "semantic": (None if h.semantic_score is None
                                     else round(h.semantic_score, 6)),
                        "pattern": h.pattern,
                        "text": h.text,
                    }
                    for h in hits
                ],
                indent=2,
            ))
        else:
            print(bold(f'"{args.query}" — {len(hits)} hit(s)\n'))
            print_hits(hits, verbose=args.long_preview)
    return 0


def cmd_ls(args: argparse.Namespace) -> int:
    cfg = load_config(args.home)
    with Store(cfg) as store:
        pages = store.list_pages()
        _name_the_store(cfg, empty=not pages)
        if not pages:
            print(dim("nothing scraped yet"))
            return 0
        print(bold(f"{'instances':>9}  {'scans':>5}  {'last scraped':<20}  url"))
        for p in pages:
            ts = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(p["last_scraped"]))
            print(
                f"{p['instance_count']:>9}  {p['scrape_count']:>5}  {ts:<20}  "
                f"{cyan(p['url'])}"
            )
            if p["title"]:
                print(f"{'':>38}{dim(p['title'][:90])}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    cfg = load_config(args.home)
    with Store(cfg) as store:
        rec = store.get_instance(args.instance_id)
        if rec is None:
            print(red(f"no instance {args.instance_id}"))
            return 1
        print(bold("url       "), cyan(rec.url))
        print(bold("instance  "), rec.instance_id)
        print(bold("pattern   "), rec.pattern)
        print(bold("xpath     "), rec.absolute_xpath)
        print(bold("chars     "), rec.char_count)
        print()
        print(bold("rendered_text"))
        print(textwrap.indent(rec.rendered_text or "(empty)", "  "))
        if rec.fields:
            print()
            print(bold("fields"))
            print(textwrap.indent(json.dumps(rec.fields, indent=2)[:4000], "  "))
        if args.html:
            print()
            print(bold("html_raw"))
            print(textwrap.indent((rec.html_raw or "")[:8000], "  "))
    return 0


def cmd_info(args: argparse.Namespace) -> int:
    cfg = load_config(args.home)
    with Store(cfg) as store:
        stats = store.stats()
    _name_the_store(cfg, empty=not stats["instances"])
    print(bold("vertiscope index"))
    for key in ("home", "pages", "scans", "instances", "patterns",
                "indexed_rows", "vocab_size"):
        value = stats[key]
        shown = f"{value:,}" if isinstance(value, int) else value
        print(f"  {key:<14} {shown}")
    print(f"  {'db_size':<14} {_human_bytes(stats['db_bytes'])}")
    return 0


def cmd_purge(args: argparse.Namespace) -> int:
    """Delete stored content from the store the caller named.

    This used to reach only the home store while looking like the general
    command, so on a machine whose content lived in a workspace it printed
    "purged everything (0 instances)" and deleted nothing — the failure mode
    where someone believes a corpus is gone while it is still on disk. It now
    defaults to the workspace, which is where the current pipeline writes, and
    reaches the home store only when asked.
    """
    if not (args.all or args.url):
        print(red("  specify --url <U> or --all"))
        return 1
    if args.all and args.url:
        print(red("  --all and --url are alternatives, not a pair"))
        return 1
    if not args.yes:
        target = "everything" if args.all else args.url
        print(red(f"  refusing to purge {target} without --yes"))
        return 1

    if args.home_store:
        cfg = load_config(args.home)
        with Store(cfg) as store:
            n = store.purge_all() if args.all else store.purge_url(args.url)
        target = "everything" if args.all else args.url
        print(f"  purged {target} from {cfg.home} ({n} instances)")
        return 0

    with _open_workspace(args, must_exist=True) as ws:
        before = ws.stats()
        ws.purge("" if args.all else args.url)
        after = ws.stats()
    # Report the difference rather than "ok". A purge that removed nothing is
    # exactly the case this command got wrong, so the number is the point.
    for key in ("pages", "chunks", "addresses"):
        gone = int(before.get(key, 0)) - int(after.get(key, 0))
        print(f"    {key:12s} {gone:>10,} removed  "
              f"{dim(f'({after.get(key, 0):,} left)')}")
    return 0


def cmd_shell(args: argparse.Namespace) -> int:
    from .shell import run_shell

    return run_shell(load_config(args.home))


# --- parser ----------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="vertiscope",
        description="Scan pages into a content-address trie, render them as "
                    "markdown, index them three ways, browse the result.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=textwrap.dedent(
            f"""
            two stores, and every command says which one it means:

              the workspace   a directory (default ./{DEFAULT_WORKSPACE}) holding the address
                              trie's graph, the frequency matrix and the markdown
                              scan · index · find · browse · status · purge

              the home store  SQLite under ~/.vertiscope, written by the earlier
                              single-snapshot pipeline
                              scrape · chunk · search · shell · ls · show · info

            examples:
              vertiscope scan https://quotes.toscrape.com/scroll
              vertiscope scan https://books.toscrape.com --follow 8
              vertiscope find "einstein world" --addresses
              vertiscope browse
              vertiscope status -w {DEFAULT_WORKSPACE}
              vertiscope purge -w {DEFAULT_WORKSPACE} --all --yes
            """
        ),
    )
    p.add_argument("--home", help="data dir (default $VERTISCOPE_HOME or ~/.vertiscope)")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging")
    sub = p.add_subparsers(dest="command", required=True)

    # --- the address-trie pipeline ------------------------------------
    # These drive the current path end to end: streaming scan -> content
    # addresses -> markdown chunks -> kuzu + frequency matrix -> three-form
    # retrieval -> the interactive REPL. The `scrape`/`search`/`shell` trio
    # below them is the earlier single-snapshot path, kept working because it
    # is what the offline chunk inspection tooling still uses.
    sp = sub.add_parser("scan", help="live streaming scan into a workspace")
    sp.add_argument("urls", nargs="+")
    sp.add_argument("-w", "--workspace", default="build")
    sp.add_argument("--duration", type=int, default=25,
                    help="seconds to drive each page")
    sp.add_argument("--pause", type=float, default=1.2)
    sp.add_argument("--passes", type=int, default=6,
                    help="maximum snapshots per page")
    sp.add_argument("--window", type=int, default=DEFAULT_CONTEXT_WINDOW,
                    help="context window: the chunking hyperparameter")
    sp.add_argument("--headful", action="store_true")
    # The sensor is the scan path, not an opt-in. Detection, recursion,
    # delta-handling and shadow nodes belong in the page; the snapshot-per-pass
    # route is a second extraction implementation that can disagree with it,
    # and two implementations of one job is how a measurement of the wrong
    # pipeline gets reported as the design's property. `--legacy` keeps it
    # reachable only because `--follow` has no sensor equivalent yet.
    sp.add_argument("--legacy", action="store_true",
                    help="serialise a snapshot per pass instead of folding in "
                         "the page (superseded; kept to measure against)")
    sp.add_argument("--variant", default="base",
                    choices=sorted(SENSOR_VARIANTS),
                    help="which design-space point the sensor runs")
    sp.add_argument("--full-transport", action="store_true",
                    help="disable subtree pruning (to measure against it)")
    sp.add_argument("--semantic", action="store_true",
                    help="embed chunks (needs the nomic model)")
    sp.add_argument("--follow", type=int, default=0, metavar="N",
                    help="crawl: also scan up to N linked pages (same host). "
                         "Without this the link graph is empty and the "
                         "pagerank factor is near-uniform.")
    sp.add_argument("--depth", type=int, default=2,
                    help="crawl depth when --follow is used")
    sp.add_argument("--any-host", action="store_true",
                    help="crawl: follow links off the seed's host too")
    sp.set_defaults(func=cmd_scan)

    sp = sub.add_parser("index", help="index local HTML file(s), no browser")
    sp.add_argument("paths", nargs="+")
    sp.add_argument("-w", "--workspace", default="build")
    sp.add_argument("--url", help="url to attribute a single file to")
    sp.add_argument("--window", type=int, default=DEFAULT_CONTEXT_WINDOW)
    sp.add_argument("--semantic", action="store_true")
    sp.set_defaults(func=cmd_index)

    sp = sub.add_parser("notes", help="index vault note(s) into the trie, no browser")
    sp.add_argument("paths", nargs="+",
                    help="a .md file, or a vault directory to walk")
    sp.add_argument("-w", "--workspace", default="build")
    sp.add_argument("--vault", default="",
                    help="the vault's name, which becomes the url origin "
                         "(default: the directory's own name)")
    sp.add_argument("--window", type=int, default=DEFAULT_CONTEXT_WINDOW)
    sp.add_argument("--semantic", action="store_true")
    sp.set_defaults(func=cmd_notes)

    sp = sub.add_parser("find", help="three-form retrieval over a workspace")
    sp.add_argument("query", nargs="+")
    sp.add_argument("-w", "--workspace", default="build")
    sp.add_argument("-k", type=int, default=8)
    sp.add_argument("--floor", type=float, default=0.0,
                    help="soften the product's veto (0 = strict)")
    sp.add_argument("--addresses", action="store_true",
                    help="print each hit's source addresses")
    sp.add_argument("--semantic", action="store_true")
    sp.set_defaults(func=cmd_find)

    sp = sub.add_parser("browse", help="interactive REPL over a workspace")
    sp.add_argument("target", nargs="?", default="")
    sp.add_argument("-w", "--workspace", default="build")
    sp.add_argument("--no-mouse", action="store_true")
    sp.add_argument("--command", action="append", default=[],
                    help="run a command and exit (headless); repeatable")
    sp.add_argument("--feed", action="store_true",
                    help="read raw terminal bytes from stdin, render, exit "
                         "(drives the pointer path without a tty)")
    sp.add_argument("--rows", type=int, default=24)
    sp.add_argument("--cols", type=int, default=100)
    sp.add_argument("--offline", action="store_true",
                    help="browse only what is stored; do not open a browser")
    sp.add_argument("--headless", action="store_true", default=False,
                    help="run the browser without a window")
    sp.set_defaults(func=cmd_browse)

    sp = sub.add_parser("where", help="resolve an address to its chunk")
    sp.add_argument("address", nargs="+",
                    help="an aid, a full key, or an absolute xpath")
    sp.add_argument("-w", "--workspace", default=DEFAULT_WORKSPACE)
    sp.add_argument("-k", type=int, default=4,
                    help="how many addresses to show when an xpath has several")
    sp.add_argument("--lines", type=int, default=12,
                    help="lines of surrounding markdown")
    sp.set_defaults(func=cmd_where)

    sp = sub.add_parser("status", help="what a workspace holds")
    sp.add_argument("-w", "--workspace", default=DEFAULT_WORKSPACE)
    sp.set_defaults(func=cmd_status)

    # --- the earlier single-snapshot path ------------------------------
    sp = sub.add_parser("scrape", help="scan URL(s), chunk, and index")
    sp.add_argument("urls", nargs="+")
    sp.add_argument("--single-pass", action="store_true",
                    help="take only the first DOM emission (no scroll loop)")
    sp.add_argument("--max-duration", type=int, help="scan time box, seconds")
    sp.add_argument("--pause", type=float, help="settle pause between scrolls")
    sp.add_argument("--char-budget", type=int, help="per-chunk text budget")
    sp.add_argument("--headful", action="store_true", help="show the browser")
    sp.add_argument("--signals", action="store_true",
                    help="also detect search box / pagination (slow: pulls in "
                         "the structural miner + sklearn)")
    sp.add_argument("-q", "--quiet", action="store_true")
    sp.set_defaults(func=cmd_scrape)

    sp = sub.add_parser("chunk", help="chunk a local HTML file (no browser)")
    sp.add_argument("file")
    sp.add_argument("--url", help="URL to attribute the file to")
    sp.add_argument("--char-budget", type=int)
    sp.add_argument("--stages", action="store_true", help="print stage timings")
    sp.add_argument("--index", action="store_true", help="also write to the store")
    sp.add_argument("--signals", action="store_true",
                    help="also detect search box / pagination (slow)")
    sp.set_defaults(func=cmd_chunk)

    sp = sub.add_parser("search", help="ranked retrieval over the index")
    sp.add_argument("query")
    sp.add_argument("-k", type=int, default=10)
    sp.add_argument("--url", help="restrict to one URL")
    sp.add_argument("--semantic", action="store_true",
                    help="rerank with nomic embeddings")
    sp.add_argument("--json", action="store_true")
    # Was `--verbose`, which collided with the global debug-logging flag: one
    # name, two meanings, and whichever came last won.
    sp.add_argument("--long", action="store_true", dest="long_preview",
                    help="longer previews")
    sp.set_defaults(func=cmd_search)

    sp = sub.add_parser("shell", help="interactive retrieval REPL")
    sp.set_defaults(func=cmd_shell)

    sp = sub.add_parser("ls", help="list scraped pages")
    sp.set_defaults(func=cmd_ls)

    sp = sub.add_parser("show", help="print one instance in full")
    sp.add_argument("instance_id")
    sp.add_argument("--html", action="store_true", help="include raw HTML")
    sp.set_defaults(func=cmd_show)

    sp = sub.add_parser("info", help="index statistics")
    sp.set_defaults(func=cmd_info)

    sp = sub.add_parser("purge", help="delete stored content")
    sp.add_argument("-w", "--workspace", default=DEFAULT_WORKSPACE)
    sp.add_argument("--url", help="one page")
    sp.add_argument("--all", action="store_true", help="everything")
    sp.add_argument("--yes", action="store_true",
                    help="required: this deletes content")
    sp.add_argument("--home-store", action="store_true",
                    help="purge the single-snapshot store instead")
    sp.set_defaults(func=cmd_purge)

    # `-v` on every subcommand as well as before it. SUPPRESS is what makes
    # both positions work: argparse copies a subparser's defaults over the
    # namespace the parent already filled, so a plain `default=False` here
    # silently undid `vertiscope -v <cmd>`. Suppressed, the attribute is absent
    # unless the flag was actually given, and the parent's value survives.
    for name, sub_parser in sub.choices.items():
        sub_parser.add_argument("-v", "--verbose", action="store_true",
                                default=argparse.SUPPRESS,
                                help=argparse.SUPPRESS)

    return p


def _force_utf8_stdio() -> None:
    """Stop scraped text from crashing/mojibake-ing on a cp1252 console.

    Scraped pages are full of em-dashes, smart quotes and CJK; the Windows
    console defaults to cp1252, which turns those into '?' at best and
    raises UnicodeEncodeError at worst.
    """
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


def main(argv: Optional[Sequence[str]] = None) -> int:
    _force_utf8_stdio()
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )
    try:
        return int(args.func(args) or 0)
    except SystemExit as exc:
        # A command that bails out reports its code like every other command.
        # `_open_workspace` raises rather than returns, and callers driving
        # `main` as a library — the audit scripts, the obligation tests — had
        # to wrap every call in `except SystemExit` to survive it. Argparse's
        # own exits (usage errors, `--help`) still propagate, because those
        # happen before dispatch and mean something different.
        return int(exc.code or 0) if isinstance(exc.code, int) else 1
    except KeyboardInterrupt:
        print("\ninterrupted")
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
