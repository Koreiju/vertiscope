"""Interactive retrieval REPL.

The index is loaded once and held, so queries after the first are instant —
which is the whole reason this exists next to ``vertiscope search``. Bare input
is treated as a query; everything else is a ``:command``.
"""

from __future__ import annotations

import shlex
import textwrap
import time
from typing import List, Optional

from .cli import bold, cyan, dim, green, print_hits, red, yellow
from .config import Config
from .ingest import ingest
from .pipeline import scrape_url
from .retrieve import Hit, Retriever, SemanticUnavailable
from .store import Store

HELP = """
  <text>            search the index
  :k <n>            result count            (default 5)
  :url <u|off>      restrict to one URL
  :semantic on|off  nomic embedding rerank  (default off)
  :open <n>         full text of result n
  :html <n>         raw HTML of result n
  :scrape <url>     scan and index a URL, then keep going
  :ls               scraped pages
  :info             index stats
  :help  :quit
"""


def run_shell(cfg: Config) -> int:
    with Store(cfg) as store:
        retriever = Retriever(store)
        stats = store.stats()
        print(bold("vertiscope shell") + dim(f"  ·  {cfg.home}"))
        print(
            dim(
                f"{stats['indexed_rows']:,} indexed rows · "
                f"{stats['vocab_size']:,} terms · {stats['pages']} pages"
            )
        )
        if stats["indexed_rows"] == 0:
            print(yellow("index is empty — try  :scrape https://example.com"))
        print(dim("':help' for commands, ':quit' to exit\n"))

        k = 5
        url_filter: Optional[str] = None
        semantic = False
        last: List[Hit] = []

        while True:
            try:
                raw = input(cyan("vertiscope> ")).strip()
            except (EOFError, KeyboardInterrupt):
                print()
                return 0
            if not raw:
                continue

            if not raw.startswith(":"):
                started = time.perf_counter()
                try:
                    last = retriever.search(
                        raw, k=k,
                        urls=[url_filter] if url_filter else None,
                        semantic=semantic,
                    )
                except SemanticUnavailable as exc:
                    print(yellow(f"  {exc}"))
                    semantic = False
                    last = retriever.search(
                        raw, k=k, urls=[url_filter] if url_filter else None
                    )
                took = (time.perf_counter() - started) * 1000
                print(dim(f"  {len(last)} hit(s) in {took:.0f}ms\n"))
                print_hits(last)
                continue

            parts = shlex.split(raw)
            cmd, cmd_args = parts[0][1:].lower(), parts[1:]

            if cmd in ("quit", "q", "exit"):
                return 0
            if cmd in ("help", "h", "?"):
                print(HELP)
            elif cmd == "k":
                if cmd_args and cmd_args[0].isdigit():
                    k = int(cmd_args[0])
                print(dim(f"  k = {k}"))
            elif cmd == "url":
                if cmd_args and cmd_args[0] not in ("off", "none", "-"):
                    url_filter = cmd_args[0]
                else:
                    url_filter = None
                print(dim(f"  url filter = {url_filter or 'off'}"))
            elif cmd == "semantic":
                semantic = bool(cmd_args) and cmd_args[0] in ("on", "true", "1", "yes")
                print(dim(f"  semantic = {'on' if semantic else 'off'}"))
            elif cmd in ("open", "html"):
                _show_result(store, last, cmd_args, raw_html=(cmd == "html"))
            elif cmd == "scrape":
                if not cmd_args:
                    print(red("  usage: :scrape <url>"))
                    continue
                _scrape_into(store, cfg, cmd_args[0])
            elif cmd == "ls":
                for p in store.list_pages():
                    print(f"  {p['instance_count']:>6}  {cyan(p['url'])}")
            elif cmd == "info":
                for key, value in store.stats().items():
                    shown = f"{value:,}" if isinstance(value, int) else value
                    print(f"  {key:<14} {shown}")
            else:
                print(red(f"  unknown command :{cmd}  (':help')"))


def _show_result(
    store: Store, last: List[Hit], cmd_args: List[str], *, raw_html: bool
) -> None:
    if not last:
        print(dim("  no results yet"))
        return
    if not cmd_args or not cmd_args[0].isdigit():
        print(red("  usage: :open <n>"))
        return
    idx = int(cmd_args[0])
    if not 1 <= idx <= len(last):
        print(red(f"  n must be 1..{len(last)}"))
        return
    hit = last[idx - 1]
    rec = hit.record or store.get_instance(hit.instance_id)
    print(bold(f"\n  [{idx}] ") + cyan(hit.url))
    print(dim(f"  {hit.instance_id}  {hit.pattern}\n"))
    body = (rec.html_raw if (raw_html and rec) else (rec.rendered_text if rec else hit.text))
    print(textwrap.indent((body or "(empty)")[:8000], "  "))
    print()


def _scrape_into(store: Store, cfg: Config, url: str) -> None:
    print(dim(f"  scanning {url} …"))
    started = time.perf_counter()
    try:
        result = scrape_url(url, cfg, single_pass=True)
    except Exception as exc:  # noqa: BLE001
        print(red(f"  scrape failed: {type(exc).__name__}: {exc}"))
        return
    report = ingest(store, result)
    print(
        f"  {green('ok')} {len(result.chunks)} chunks · "
        f"{report.instances_written} instances · "
        f"{report.rows_indexed} indexed · "
        f"{time.perf_counter() - started:.1f}s"
    )
