# NOTE (vertiscope): the Kuzu upserts and the concept-graph materialisation
# (compiled_from_scans / graph_editor / concept_index_service) were dropped
# in the extraction. This module is now pure *detection*: given a DOM and a
# URL it returns the search-input and pagination rows it found.
"""
signal_fields.py — Site-wide search + pagination detection.

Wraps the collectors in :mod:`vertiscope.core.signal_detect` and turns their
node hits into flat rows.

Two specialized field types live outside the generic trie/chunk
pipeline because they're *cross-URL* anchors rather than per-instance
content:

* **SearchInputField** — any ``<input>`` / ``role="searchbox"``-like
  element that the agent should treat as the site's primary search box.
* **PaginationField** — any button/link whose text or attribute tokens
  identify it as next/prev/page/load-more.

Tracking
--------
Per the design call in the plan, coalesce on
``(domain, generalized_xpath)``. Repeat scans of the same site update
``last_seen`` rather than inserting a new row. The ``last_seen_url`` /
``last_seen_absolute_xpath`` columns record the most recent instance we
saw, so agents can still point at a live target.
"""

from __future__ import annotations

import hashlib
import inspect
import json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple
from urllib.parse import urlparse

from vertiscope.core.shadow_html_parser import ShadowDOM, ShadowNode, get_absolute_xpath
from vertiscope.core.xpath_utils import generalize_xpath

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Row dataclasses
# ---------------------------------------------------------------------------


@dataclass
class SignalFieldRow:
    """Shared shape for SearchInputField / PaginationField rows."""

    field_id: str
    domain: str
    generalized_xpath: str
    last_seen_url: str
    last_seen_absolute_xpath: str
    tag: str
    text_hint: str
    attributes_json: str
    score: int
    first_seen: str
    last_seen: str


# ---------------------------------------------------------------------------
# Detection
# ---------------------------------------------------------------------------


def _domain_of(url: str) -> str:
    try:
        host = urlparse(url).hostname or ""
        return host.lower()
    except Exception:
        return url


def _now() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _text_hint(node: ShadowNode) -> str:
    """Short, human-readable hint for a field — used in dedup + UI.

    Prefers explicit labels: ``aria-label``, ``placeholder``, ``title``,
    ``alt``, and lastly the visible text. Capped at 120 chars.
    """
    for attr in ("aria-label", "placeholder", "title", "alt", "name"):
        v = (node.get_attr(attr) or "").strip()
        if v:
            return v[:120]
    visible = (node.get_text() or "").strip()
    return visible[:120]


def _attributes_snapshot(node: ShadowNode) -> Dict[str, str]:
    """Pick the top ~6 discriminative attributes for forensics."""
    keep = {}
    for k, v in node.attributes.items():
        if not v:
            continue
        keep[str(k)] = str(v)[:200]
        if len(keep) >= 8:
            break
    return keep


def _mk_field_id(domain: str, generalized_xpath: str, text_hint: str) -> str:
    h = hashlib.sha1(
        f"{domain}|{generalized_xpath}|{text_hint}".encode("utf-8")
    ).hexdigest()[:20]
    return h


def _to_row(
    node: ShadowNode,
    url: str,
    score: int,
) -> SignalFieldRow:
    abs_xp = get_absolute_xpath(node)
    gen_xp = generalize_xpath(abs_xp)
    domain = _domain_of(url)
    hint = _text_hint(node)
    now = _now()
    return SignalFieldRow(
        field_id=_mk_field_id(domain, gen_xp, hint),
        domain=domain,
        generalized_xpath=gen_xp,
        last_seen_url=url,
        last_seen_absolute_xpath=abs_xp,
        tag=node.tag.lower(),
        text_hint=hint,
        attributes_json=json.dumps(_attributes_snapshot(node), sort_keys=True),
        score=int(score),
        first_seen=now,
        last_seen=now,
    )


def _run_collector(dom: ShadowDOM, url: str, collector_cls: type) -> List[SignalFieldRow]:
    """Instantiate a detection collector and flatten its output.

    Arity is resolved by *inspecting* the signature, not by catching
    TypeError from a speculative call. The old probe swallowed genuine
    TypeErrors raised inside ``collect`` and then re-called it with the
    wrong arity, reporting a signature problem for what was actually a
    bug in the collector body.
    """
    collector = collector_cls()
    params = inspect.signature(collector.collect).parameters
    # PaginationCollector takes an optional structural_chunks list.
    chunk = collector.collect(dom, None) if len(params) > 1 else collector.collect(dom)
    if chunk is None:
        return []
    nodes = getattr(chunk, "_instance_nodes", []) or []
    # Scores are already ranked high→low.
    rows: List[SignalFieldRow] = []
    for i, node in enumerate(nodes):
        # Higher rank → higher score; use a descending small int for stability.
        score = len(nodes) - i
        rows.append(_to_row(node, url, score))
    return rows


def collect_signal_fields(
    dom: ShadowDOM,
    url: str,
) -> Tuple[List[SignalFieldRow], List[SignalFieldRow]]:
    """Return ``(search_fields, pagination_fields)`` for one page."""
    from vertiscope.core.signal_detect import (
        SearchInputCollector,
        PaginationCollector,
    )
    searches = _run_collector(dom, url, SearchInputCollector)
    paginates = _run_collector(dom, url, PaginationCollector)
    logger.info(
        "Signal fields on %s: %d search, %d pagination",
        url, len(searches), len(paginates),
    )
    return searches, paginates


