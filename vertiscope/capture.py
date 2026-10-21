"""Browser-side capture: drive a page to completion, then extract it once.

This is the seam where the original architecture leaked. ``ShadowDOMScanner``
does two jobs at once:

  * **signal flow** — scroll, watch MutationObserver traffic, decide when the
    page has stopped changing (and drive infinite scroll / pagination);
  * **data flow** — emit chunk events produced by the *in-browser* chunker.

A live GUI wants both. A batch scrape wants only the first: run the page to a
settled state, then take one complete snapshot and hand it to the Python
extraction pipeline. Keeping the two chunkers (JS and Python) both live is
what made the upstream contract inconsistent — ``scan()`` is typed
``Iterator[Tuple[dict, list, list]]`` but in JS-engine mode (the only mode
that still exists) it yields flat event lists, which is why upstream's
``run_pipeline_live`` cannot work.

So here the scanner is used strictly as a completeness controller, and
``deep_serialize`` is the single data-extraction point.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

_JS_DIR = Path(__file__).resolve().parent / "core" / "js"


def _load_js(name: str) -> str:
    path = _JS_DIR / name
    if not path.exists():
        raise FileNotFoundError(f"missing bundled script: {path}")
    return path.read_text(encoding="utf-8")


@dataclass
class Snapshot:
    """One serialization: the html, its subtree hashes, and what it cost."""

    html: str
    hashes: Dict[str, str] = field(default_factory=dict)
    stats: Dict[str, int] = field(default_factory=dict)

    @property
    def wire_bytes(self) -> int:
        """What actually crossed the bridge, before any splicing."""
        return int(self.stats.get("bytes", len(self.html)))

    @property
    def pruned_subtrees(self) -> int:
        return int(self.stats.get("pruned", 0))

    @property
    def pruned_nodes(self) -> int:
        return int(self.stats.get("prunedNodes", 0))


# Deliberately permissive in the hash: anything that is not a quote. The
# first version required `[0-9a-f]+`, matching what the walker happens to
# emit today. That is a silent content-loss bug waiting for the hash format to
# change — a placeholder the pattern does not recognise is simply left in the
# document, so the page keeps a `<template>` where its content should be and
# nothing reports a problem. The format is the walker's business; this side
# only needs to find the boundaries.
_PLACEHOLDER = re.compile(r'<template data-vertiscope-same="([^"]+)"></template>')


def deep_serialize(driver, known: Optional[Dict[str, str]] = None) -> Snapshot:
    """Serialize the composed DOM, optionally pruning subtrees already held.

    ``known`` maps subtree hash to the HTML fragment the caller already has.
    Any subtree whose hash is in it comes back as a placeholder and is spliced
    back in here, so what the caller receives is always the *complete*
    document — the saving is on the wire, not in the result.

    Keeping the splice on this side is what lets everything downstream stay
    unchanged: the tagger, the trie and the renderer all still see a whole
    page, and none of them needs to learn about placeholders. The alternative
    — teaching every consumer to resolve a placeholder — would spread an
    optimisation across the entire pipeline for no additional saving.
    """
    raw = driver.execute_script(
        _load_js("deep_serialize.js"),
        {h: 1 for h in known} if known else None,
    )
    if not raw:
        return Snapshot(html="")

    try:
        payload = json.loads(raw)
    except (TypeError, ValueError):
        # An older script (or a page that broke the walk) returns bare HTML.
        return Snapshot(html=str(raw))

    html = payload.get("html") or ""
    stats = payload.get("stats") or {}
    hashes = payload.get("hashes") or {}

    if known and "data-vertiscope-same" in html:
        html, missing = _splice(html, known)
        if missing:
            # A placeholder we cannot fill would silently delete content, so
            # the honest response is to give up on the saving and re-fetch in
            # full rather than hand back a document with holes in it.
            logger.warning(
                "%d placeholder(s) had no cached fragment; re-serializing whole",
                missing,
            )
            return deep_serialize(driver, known=None)

    return Snapshot(html=html, hashes=hashes, stats=stats)


def _splice(html: str, known: Dict[str, str]) -> Tuple[str, int]:
    """Replace placeholders with the caller's fragments. Returns (html, misses).

    Repeated until no placeholder remains, because a spliced-in fragment may
    itself contain placeholders from an earlier pass. Bounded, so a fragment
    that somehow refers to itself terminates instead of hanging the scan.
    """
    missing = 0

    def replace(match: "re.Match[str]") -> str:
        nonlocal missing
        fragment = known.get(match.group(1))
        if fragment is None:
            missing += 1
            return ""
        return fragment

    for _ in range(8):
        if "data-vertiscope-same" not in html:
            break
        html = _PLACEHOLDER.sub(replace, html)
    return html, missing


def fragments_of(html: str) -> Dict[str, str]:
    """Index a serialized document by subtree hash, for the next pass.

    Every emitted element carries ``data-vertiscope-hash``; this pulls out each
    one's full outer HTML so the next snapshot can prune it. Done with a
    bracket scan rather than a parser because it runs once per pass on
    multi-megabyte strings, and building a DOM to slice substrings out of it
    would cost more than the transfer being saved.
    """
    out: Dict[str, str] = {}
    for match in re.finditer(r'<([a-zA-Z][-\w:]*)([^>]*?)\sdata-vertiscope-hash="([^"]+)"',
                             html):
        tag, digest = match.group(1).lower(), match.group(3)
        start = match.start()
        end = _element_end(html, start, tag)
        if end > start:
            out[digest] = html[start:end]
    return out


_VOID_TAGS = frozenset({
    "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
    "meta", "param", "source", "track", "wbr",
})


def _element_end(html: str, start: int, tag: str) -> int:
    """End offset of the element opening at ``start``, or -1."""
    open_end = html.find(">", start)
    if open_end < 0:
        return -1
    if tag in _VOID_TAGS or html[open_end - 1] == "/":
        return open_end + 1

    open_re = re.compile(rf"<{re.escape(tag)}(?=[\s/>])", re.IGNORECASE)
    close_re = re.compile(rf"</{re.escape(tag)}\s*>", re.IGNORECASE)
    depth = 1
    pos = open_end + 1
    while depth and pos < len(html):
        nxt_open = open_re.search(html, pos)
        nxt_close = close_re.search(html, pos)
        if nxt_close is None:
            return -1
        if nxt_open is not None and nxt_open.start() < nxt_close.start():
            depth += 1
            pos = nxt_open.end()
            continue
        depth -= 1
        pos = nxt_close.end()
    return pos if depth == 0 else -1


def drive_to_settled(
    driver,
    url: str,
    *,
    max_duration: int,
    pause: float,
    single_pass: bool = False,
    progress: Optional[Callable[[str, str], None]] = None,
) -> int:
    """Navigate and run the scroll/settle loop. Returns iterations observed.

    The scanner's yielded payloads are deliberately ignored — we want the
    side effect (page fully rendered and scrolled), not the in-browser
    chunk events. Its yield arity differs between modes, so we never unpack.
    """
    from .core.scanner import ShadowDOMScanner

    scanner = ShadowDOMScanner(driver)
    iterations = 0
    for _payload in scanner.scan(
        url,
        max_duration=0 if single_pass else max_duration,
        pause=0.0 if single_pass else pause,
    ):
        iterations += 1
        if progress:
            progress("scan", f"settle pass {iterations}")
        if single_pass:
            break
    return iterations


def stream_snapshots(
    driver,
    url: str,
    *,
    max_duration: int,
    pause: float,
    max_snapshots: int = 0,
    incremental: bool = True,
    reload: bool = True,
    progress: Optional[Callable[[str, str], None]] = None,
):
    """Drive the settle loop, yielding ``(pass number, Snapshot)`` as it goes.

    :func:`drive_to_settled` deliberately discards what the scan loop yields
    and serialises once at the end, which is right for a batch scrape. It is
    wrong for anything that has to react *while* a page is still loading: a
    lazy feed's content arrives across many settle passes, and a single final
    snapshot cannot tell you what arrived when.

    This yields a full snapshot per settle pass instead, which is what makes
    an incremental scan measurable — consecutive snapshots are the input to
    the trie diff, and the diff's cost against the change between them is the
    O(delta) claim in its live form.

    The transport is incremental too: each pass tells the in-page walker which
    subtree hashes it already holds, and unchanged subtrees come back as
    placeholders that :func:`deep_serialize` splices from the previous
    snapshot. So on a page being scrolled, the second and later passes move a
    fraction of the first pass's bytes while yielding a complete document.

    Set ``incremental=False`` to measure against the naive transport.

    ``reload`` forces navigation even when the browser is already showing the
    URL. It defaults to True because this function's callers are asking *what
    does the page say now*, and the scanner's own default is to skip
    navigation when the URL matches — correct inside a settle loop, where
    re-navigating would reset the scroll it is driving, but fatal to a
    re-scan: it returns the DOM already in memory, so a page that changed
    reports no delta and the index silently keeps content that is gone.
    """
    from .core.scanner import ShadowDOMScanner

    scanner = ShadowDOMScanner(driver)
    iterations = 0
    fragments: Dict[str, str] = {}
    for _payload in scanner.scan(url, max_duration=max_duration, pause=pause,
                                 force_reload=reload):
        iterations += 1
        snapshot = deep_serialize(driver, known=fragments if incremental else None)
        if progress:
            progress(
                "snapshot",
                f"pass {iterations}: {snapshot.wire_bytes:,} on the wire, "
                f"{len(snapshot.html):,} spliced, "
                f"{snapshot.pruned_subtrees} subtree(s) pruned",
            )
        if snapshot.html.strip():
            if incremental:
                # Index the *spliced* document, so a fragment pruned two
                # passes ago is still available for the next one. Indexing
                # only what came over the wire would lose it and force a
                # re-fetch of content nothing had changed.
                fragments = fragments_of(snapshot.html)
            yield iterations, snapshot
        if max_snapshots and iterations >= max_snapshots:
            break
