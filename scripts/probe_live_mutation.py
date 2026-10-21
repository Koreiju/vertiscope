#!/usr/bin/env python
"""LIVE correctness: does an incremental re-scan ever serve stale content?

Two mechanisms now skip work when a subtree's hash is unchanged — the
transport prunes it in-page, and the extractor reuses its detections. Both
trust the same thing: **equal hash implies equal subtree**. If that ever fails,
the result is not a slow scan, it is a *wrong* one, and the wrongness is
invisible: the index simply keeps content that no longer exists on the page,
with correct-looking addresses and no error anywhere.

`probe_live_delta.py` shows the saving on a page that grows. Growth is the
easy case — new content cannot be stale. This probe covers the hard one: a
page that **changes in place**, where the old and new content occupy the same
addresses, and a reuse bug would return the old.

It serves a page locally so it can be mutated between scans, which a public
site cannot be. Everything else is real: real Firefox, real navigation, real
serialization, real pruning, real splicing, real reuse.

    python scripts/probe_live_mutation.py
    python scripts/probe_live_mutation.py --headful --port 8push
"""

from __future__ import annotations

import argparse
import functools
import http.server
import pathlib
import socketserver
import sys
import tempfile
import threading

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _force_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


_force_utf8_stdio()

from vertiscope.browser import browser_session  # noqa: E402
from vertiscope.capture import stream_snapshots  # noqa: E402
from vertiscope.config import load_config  # noqa: E402
from vertiscope.stream import StreamingScan  # noqa: E402

PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><title>mutation probe</title></head>
<body><main>
  <section id="stable">
    <h1>This heading never changes</h1>
    <p>Neither does this paragraph, on any pass.</p>
    <ul>{stable_items}</ul>
  </section>
  <section id="volatile">
    <h2>{heading}</h2>
    <p title="{label}">{body}</p>
    <a href="{href}">{link_text}</a>
    <img src="{image}" alt="{alt}">
  </section>
</main></body></html>
"""


def render(generation: int) -> str:
    """A page whose `volatile` section is entirely different per generation."""
    return PAGE.format(
        stable_items="".join(f"<li>fixed item {i}</li>" for i in range(12)),
        heading=f"GENERATION-{generation}-HEADING",
        label=f"GENERATION-{generation}-LABEL",
        body=f"GENERATION-{generation}-BODY text that is wholly replaced.",
        href=f"/generation-{generation}-link",
        link_text=f"GENERATION-{generation}-LINKTEXT",
        image=f"/generation-{generation}.png",
        alt=f"GENERATION-{generation}-ALT",
    )


class ProbeFailure(AssertionError):
    pass


def check(condition: bool, message: str, detail: str = "") -> None:
    print(f"  [{'PASS' if condition else 'FAIL'}] {message}"
          + (f"  ({detail})" if detail else ""))
    if not condition:
        raise ProbeFailure(f"{message}: {detail}")


def serve(directory: pathlib.Path, port: int):
    handler = functools.partial(_QuietHandler, directory=str(directory))
    httpd = socketserver.TCPServer(("127.0.0.1", port), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args):    # keep the probe's output readable
        pass

    def end_headers(self):
        # Without this the browser serves the first generation from cache and
        # the probe measures nothing — a false pass that looks like a real one.
        self.send_header("Cache-Control", "no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()


def values_of(trie) -> set:
    return {(leaf.value or "").strip() for leaf in trie.leaves() if leaf.value}


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--port", type=int, default=8731)
    ap.add_argument("--generations", type=int, default=3)
    ap.add_argument("--headful", action="store_true")
    ap.add_argument("--full-transport", action="store_true",
                    help="disable pruning, to check the probe itself")
    args = ap.parse_args()

    workdir = pathlib.Path(tempfile.mkdtemp(prefix="vertiscope_mutation_"))
    page = workdir / "index.html"
    page.write_text(render(0), encoding="utf-8")

    httpd = serve(workdir, args.port)
    url = f"http://127.0.0.1:{args.port}/index.html"
    print(f"serving {workdir} at {url}\n")

    cfg = load_config()
    scan = StreamingScan(url)
    seen_by_generation = {}

    try:
        with browser_session(cfg, headless=not args.headful) as driver:
            for generation in range(args.generations):
                page.write_text(render(generation), encoding="utf-8")
                print(f"generation {generation}")

                update = None
                for passno, snapshot in stream_snapshots(
                    driver, url, max_duration=6, pause=0.4, max_snapshots=2,
                    incremental=not args.full_transport,
                ):
                    update = scan.push(snapshot, passno)
                if update is None:
                    raise ProbeFailure(f"generation {generation} produced no snapshot")

                values = values_of(update.trie)
                seen_by_generation[generation] = values
                print(f"  wire {update.wire_ratio * 100:5.1f}%  "
                      f"delta {update.changed:4d}  "
                      f"reused {update.reused_tags:4d} tag(s) from "
                      f"{update.reused_subtrees} subtree(s)")

                marker = f"GENERATION-{generation}-"
                current = {v for v in values if marker in v}
                check(bool(current),
                      f"generation {generation}'s own content is present",
                      f"{len(current)} value(s) carrying {marker}")

                stale = {
                    v for v in values
                    if "GENERATION-" in v and marker not in v
                }
                check(not stale,
                      f"no content from an earlier generation survives",
                      f"{len(stale)} stale value(s): {sorted(stale)[:3]}"
                      if stale else "index holds only the current page")

                check("This heading never changes" in values,
                      "the unchanged section is still present",
                      "reuse must not drop what it skipped")

        print("\nsummary")
        for generation, values in seen_by_generation.items():
            markers = {v.split("-")[1] for v in values if v.startswith("GENERATION-")}
            print(f"  generation {generation}: markers present = {sorted(markers)}")

        # Growth is not what this probe tests, so the page size is constant;
        # a delta on every generation after the first is the thing to confirm.
        deltas = [u.changed for u in scan.updates[1:]]
        check(any(d > 0 for d in deltas),
              "an in-place change registered as a delta",
              f"deltas per pass: {deltas}")

        reused = [u.reused_tags for u in scan.updates[1:]]
        check(any(r > 0 for r in reused),
              "the unchanged section was reused rather than re-examined",
              f"tags reused per pass: {reused}")

    except ProbeFailure as exc:
        print(f"\nPROBE FAILED: {exc}")
        return 1
    except Exception as exc:  # noqa: BLE001
        print(f"\nPROBE ERROR: {type(exc).__name__}: {exc}")
        import traceback
        traceback.print_exc()
        return 2
    finally:
        httpd.shutdown()

    print("\nPROBE PASSED — incremental re-scanning never served stale content")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
