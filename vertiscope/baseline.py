"""The original deep serializer, run against the same harness as the sensor.

`vertiscope/reference/dom_deep_serializer.py` is the mothership's scanner, copied
byte-identical. This module drives its algorithm — the extraction JS, the
Merkle hashing, the subtree pruning — through the same measurements the
in-page sensor is measured by, so the two can be compared on one page instead
of argued about.

It calls the original's own methods rather than re-implementing them. That
matters: a baseline you paraphrase is a baseline you can accidentally
flatter, and the whole point of a baseline is that it is not on your side.

What is deliberately *not* carried over is everything after the algorithm —
the Kuzu store, the 3D radial layout, the HTML re-serialisation. Those are
storage and presentation; comparing them would compare two products rather
than two approaches to reading a page.

The comparison is per pass:

    wire      bytes crossing the browser boundary
    extract   time inside the page
    process   time on this side (merkle + prune)
    kept      nodes surviving the prune

The sensor's counterparts are the drain payload, `drain_ms`, `decode_ms`,
and chunks. The interesting axis is not one pass but the *shape across
passes* on a page that grows: the original re-serialises the document every
time by construction, the sensor sends what moved.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .reference.dom_deep_serializer import EXTRACT_DOM_JSON_JS, ShadowDOMScanner

__all__ = ["DeepSerializerBaseline", "BaselinePass"]


@dataclass
class BaselinePass:
    """One full-document pass of the original serializer."""

    passno: int
    wire_bytes: int = 0
    nodes_total: int = 0
    nodes_kept: int = 0
    extract_ms: float = 0.0     # the JS, inside the page
    parse_ms: float = 0.0       # JSON -> dict on this side
    merkle_ms: float = 0.0      # bottom-up signature computation
    prune_ms: float = 0.0       # subtree dedup against everything seen
    errors: int = 0

    @property
    def process_ms(self) -> float:
        return self.parse_ms + self.merkle_ms + self.prune_ms

    @property
    def total_ms(self) -> float:
        return self.extract_ms + self.process_ms


class DeepSerializerBaseline:
    """Drive the original algorithm over a live driver, and time it.

    `seen` persists across passes exactly as `ShadowDOMScanner.seen_signatures`
    does, so the second pass over an unchanged page prunes to nothing — which
    is the original's own incrementality and the thing worth measuring it on.
    """

    def __init__(self, driver, url: str = ""):
        self.driver = driver
        self.url = url
        # Skip __init__: it builds a Kuzu store and a Firefox profile, neither
        # of which is the algorithm. The instance exists only to carry the
        # original's methods, which take everything they need as arguments.
        self.impl = object.__new__(ShadowDOMScanner)
        self.seen: set = set()
        self.passes: List[BaselinePass] = []

    @staticmethod
    def count_nodes(node: Optional[dict]) -> int:
        if not node:
            return 0
        total = 1
        for child in node.get("children", []) or []:
            total += DeepSerializerBaseline.count_nodes(child)
        shadow = node.get("shadowRoot")
        if shadow:
            for s in shadow.get("children", []) or []:
                total += DeepSerializerBaseline.count_nodes(s)
        return total

    def step(self, pixels: int = 0) -> float:
        """One discrete scroll, matching what the sensor's scroller does."""
        started = time.perf_counter()
        self.driver.execute_script(
            "window.scrollBy(0, arguments[0] || Math.max(200,"
            "(window.innerHeight||600)-60));", int(pixels))
        return (time.perf_counter() - started) * 1000

    def pass_once(self, passno: int = 0) -> BaselinePass:
        out = BaselinePass(passno=passno)
        try:
            started = time.perf_counter()
            raw = self.driver.execute_script(EXTRACT_DOM_JSON_JS) or "null"
            out.extract_ms = (time.perf_counter() - started) * 1000
            out.wire_bytes = len(raw)

            started = time.perf_counter()
            snapshot = json.loads(raw)
            out.parse_ms = (time.perf_counter() - started) * 1000
            out.nodes_total = self.count_nodes(snapshot)

            started = time.perf_counter()
            self.impl._compute_merkle_hashes(snapshot)
            out.merkle_ms = (time.perf_counter() - started) * 1000

            started = time.perf_counter()
            pruned = self.impl._process_node(snapshot, self.seen, None)
            out.prune_ms = (time.perf_counter() - started) * 1000
            out.nodes_kept = self.count_nodes(pruned)
        except Exception:  # noqa: BLE001 - a failed pass is a datum
            out.errors += 1
        self.passes.append(out)
        return out

    def report(self) -> Dict[str, float]:
        if not self.passes:
            return {}
        first, rest = self.passes[0], self.passes[1:]
        return {
            "passes": len(self.passes),
            "wire_first": first.wire_bytes,
            "wire_total": sum(p.wire_bytes for p in self.passes),
            "wire_steady": (sum(p.wire_bytes for p in rest) / len(rest)
                            if rest else 0.0),
            "ms_first": round(first.total_ms, 1),
            "ms_steady": (round(sum(p.total_ms for p in rest) / len(rest), 1)
                          if rest else 0.0),
            "kept_total": sum(p.nodes_kept for p in self.passes),
            "errors": sum(p.errors for p in self.passes),
        }
