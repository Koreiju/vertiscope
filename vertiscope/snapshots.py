"""Captured browser snapshots, replayed offline.

`scripts/snapshot_pages.py` drives a real browser and stores what it ended up
with: the serialized DOM after hydration, once per settle pass that actually
differed. This is the reading side, in the library rather than in the script,
because the tests are the main consumer and importing a script from a test is
a way to make both harder to move later.

The point of storing a *sequence* is that consecutive snapshots are exactly
the input `StreamingScan` takes. Replaying them exercises the delta path
against real mutations — a feed loading, comments arriving, a price ticking —
with no browser, no network and no flake, which is the only way that path
gets asserted rather than merely observed.

A page that settled immediately stores one snapshot. That is a complete
recording of a page which does not mutate, and it is worth being explicit
that it exercises the *first-pass* path only: a delta claim needs a fixture
that actually changed.
"""

from __future__ import annotations

import gzip
import json
import pathlib
from typing import Dict, List, Tuple

__all__ = ["SNAPSHOTS", "available", "load", "load_meta", "mutating"]

SNAPSHOTS = pathlib.Path(__file__).resolve().parent.parent / "tests" / "snapshots"


def available() -> List[str]:
    """Slugs that have a complete capture, sorted."""
    if not SNAPSHOTS.exists():
        return []
    return sorted(p.name for p in SNAPSHOTS.iterdir()
                  if (p / "meta.json").exists())


def load_meta(slug: str) -> Dict:
    return json.loads((SNAPSHOTS / slug / "meta.json").read_text(
        encoding="utf-8"))


def load(slug: str) -> Tuple[Dict, List[str]]:
    """Return `(meta, htmls)` — the capture's metadata and its DOM sequence."""
    meta = load_meta(slug)
    folder = SNAPSHOTS / slug
    htmls = []
    for entry in meta["snapshots"]:
        with gzip.open(folder / f"{entry['index']:02d}.html.gz",
                       "rt", encoding="utf-8") as fh:
            htmls.append(fh.read())
    return meta, htmls


def mutating() -> List[str]:
    """Slugs whose capture holds more than one distinct DOM.

    The delta path needs a page that changed. Separated out so a test can say
    it is skipping for want of a mutating fixture, rather than passing over a
    single-snapshot capture and appearing to have checked something.
    """
    return [slug for slug in available()
            if len(load_meta(slug)["snapshots"]) > 1]
