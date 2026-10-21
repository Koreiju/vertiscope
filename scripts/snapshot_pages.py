"""Freeze JavaScript pages as replayable fixtures — the T2 tier.

The frozen corpus fetches raw HTTP, so a single-page application contributes
`<div id="app"></div>` and a script tag. youtube.com, amazon.com and
portal.azure.com are all in the corpus today and all score well, because
there is nothing in them to get wrong. We are not testing those sites; we are
testing our handling of an empty div.

This drives a real browser once and stores what the browser *ended up with*:
the serialized DOM after hydration, shadow roots included, captured once per
settle pass. A page becomes a **sequence** of snapshots rather than one, which
is the point — consecutive snapshots are exactly the input the trie diff
takes, so replaying them exercises the O(delta) path with real mutations
(infinite scroll, lazily-loaded comments, live prices) and no browser in the
loop.

What that buys, per captured page:

    deterministic   same bytes every run, so it can assert, not just observe
    offline         no network, no rate limit, no site redesign mid-suite
    parallel        it is just files; the runner can fan it out
    delta-bearing   the mutation sequence is preserved, not flattened

Capture is slow and online. Replay is fast and offline. That asymmetry is the
whole design: pay once, assert forever.

    python scripts/snapshot_pages.py --url https://www.youtube.com --slug youtube
    python scripts/snapshot_pages.py --from-manifest tests/corpus/manifest.json --limit 20
    python scripts/snapshot_pages.py --list
"""

from __future__ import annotations

import argparse
import datetime as dt
import gzip
import json
import pathlib
import sys
import time

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

SNAPSHOTS = ROOT / "tests" / "snapshots"


def slug_for(url: str) -> str:
    keep = "".join(c if c.isalnum() else "-" for c in url.split("://", 1)[-1])
    return keep.strip("-").lower()[:80]


def capture(driver, url: str, slug: str, *, max_duration: int, pause: float,
            max_snapshots: int, stratum: str = "") -> dict:
    """Store one page's settle sequence under `tests/snapshots/<slug>/`.

    Gzipped, because a hydrated DOM is several megabytes and the interesting
    pages are the biggest ones. Compression is ~5x on markup and the cost is
    paid at capture time, not on every replay.
    """
    out = SNAPSHOTS / slug
    out.mkdir(parents=True, exist_ok=True)

    passes, started = [], time.perf_counter()
    seen_last = None
    repeats = 0
    for passno, snap in stream_snapshots(
            driver, url, max_duration=max_duration, pause=pause,
            max_snapshots=max_snapshots, incremental=False, reload=True):
        html = snap.html if isinstance(snap.html, str) else str(snap.html)
        # A settled page yields the same DOM every pass — quotes.toscrape.com
        # gave six byte-identical copies. Storing them is waste that scales
        # with the corpus, and worse, it makes a replay look like it exercised
        # five mutations when nothing changed. Only a pass that *differs* is a
        # snapshot; the repeat count is kept because "settled after two
        # passes" is itself a fact about the page.
        if html == seen_last:
            repeats += 1
            continue
        seen_last = html
        index = len(passes)
        path = out / f"{index:02d}.html.gz"
        with gzip.open(path, "wt", encoding="utf-8") as fh:
            fh.write(html)
        passes.append({"index": index, "pass": passno,
                       "chars": len(html), "gz_bytes": path.stat().st_size})
        print(f"    pass {index}: {len(html):>9,} chars "
              f"-> {path.stat().st_size:>8,} gz")

    meta = {
        "url": url,
        "slug": slug,
        "stratum": stratum,
        "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "seconds": round(time.perf_counter() - started, 1),
        "snapshots": passes,
        "repeated_passes": repeats,
        # Recorded so a replay can tell a page that genuinely stopped changing
        # from one that hit the cap mid-stream. Only the first can be treated
        # as a complete rendering.
        # A page that stopped changing before the cap genuinely settled; one
        # that was still producing new DOM when the cap hit did not, and only
        # the first can be read as a complete rendering.
        "settled": repeats > 0,
    }
    (out / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def load(slug: str):
    """Replay side: the snapshot sequence for a slug, decompressed in order."""
    folder = SNAPSHOTS / slug
    meta = json.loads((folder / "meta.json").read_text(encoding="utf-8"))
    htmls = []
    for entry in meta["snapshots"]:
        with gzip.open(folder / f"{entry['index']:02d}.html.gz",
                       "rt", encoding="utf-8") as fh:
            htmls.append(fh.read())
    return meta, htmls


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--url", action="append", default=[],
                    help="page to capture (repeatable)")
    ap.add_argument("--slug", help="name for a single --url capture")
    ap.add_argument("--stratum", default="", help="recorded on the fixture")
    ap.add_argument("--from-manifest", type=pathlib.Path,
                    help="capture the pages listed in a corpus manifest")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--max-duration", type=int, default=25,
                    help="seconds of settle loop per page")
    ap.add_argument("--pause", type=float, default=1.5)
    ap.add_argument("--max-snapshots", type=int, default=8,
                    help="cap on passes stored per page")
    ap.add_argument("--headless", action="store_true", default=True)
    ap.add_argument("--overwrite", action="store_true",
                    help="recapture pages already stored")
    ap.add_argument("--list", action="store_true",
                    help="show what is already captured and exit")
    args = ap.parse_args()

    if args.list:
        if not SNAPSHOTS.exists():
            print("nothing captured yet")
            return 0
        total = 0
        for folder in sorted(SNAPSHOTS.iterdir()):
            meta_path = folder / "meta.json"
            if not meta_path.exists():
                continue
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            size = sum(e["gz_bytes"] for e in meta["snapshots"])
            total += size
            print(f"{meta['slug'][:44]:44s} {len(meta['snapshots']):2d} passes "
                  f"{size/1024:8.0f} KB  {meta['stratum'] or '-'}")
        print(f"\n{total/1024/1024:.1f} MB total")
        return 0

    targets = []
    if args.url:
        if args.slug and len(args.url) == 1:
            targets.append((args.url[0], args.slug))
        else:
            targets += [(u, slug_for(u)) for u in args.url]
    if args.from_manifest:
        pages = json.loads(args.from_manifest.read_text(encoding="utf-8"))["pages"]
        targets += [(p["url"], p["slug"]) for p in pages if p.get("ok")]
    if args.limit:
        targets = targets[: args.limit]
    if not targets:
        ap.error("nothing to capture: pass --url or --from-manifest")

    if not args.overwrite:
        before = len(targets)
        targets = [(u, s) for u, s in targets
                   if not (SNAPSHOTS / s / "meta.json").exists()]
        if before != len(targets):
            print(f"skipping {before - len(targets)} already captured "
                  f"(--overwrite to redo)")

    print(f"capturing {len(targets)} pages")
    cfg = load_config()
    ok = failed = 0
    # One browser for the whole run. Each Firefox is ~400 MB, and the capture
    # is dominated by page settle time rather than CPU, so this is the tier
    # that does *not* want the parse pool's parallelism.
    with browser_session(cfg, headless=args.headless) as driver:
        for url, slug in targets:
            print(f"  {slug} <- {url}")
            try:
                meta = capture(driver, url, slug,
                               max_duration=args.max_duration, pause=args.pause,
                               max_snapshots=args.max_snapshots,
                               stratum=args.stratum)
                ok += 1
                print(f"    {len(meta['snapshots'])} passes in "
                      f"{meta['seconds']}s, settled={meta['settled']}")
            except Exception as exc:  # noqa: BLE001
                failed += 1
                print(f"    FAILED {type(exc).__name__}: {exc}")

    print(f"\ncaptured {ok}, failed {failed}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
