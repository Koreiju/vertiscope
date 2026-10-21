"""The scrape → chunk → vectorize pipeline.

Derived from ``backend/dom/pipeline.py`` with the Kuzu persistence stages
(6 and 10) and the concept-graph materialisation removed. What remains is
the part that actually turns a page into retrievable chunks::

    html  ─1─> ShadowDOM
          ─2─> ContentTagger      -> tagged content xpaths (+ categories)
          ─3─> XPathTreeBuilder   -> collapsed content tree
          ─4─> build_trie_from_tree -> generalized patterns
          ─5─> ChunkBuilder       -> budgeted chunks
          ─6─> render_all_chunks  -> instances (html_raw + rendered_text)
          ─7─> collect_signal_fields (optional: search box / pagination)

Persistence and indexing are the caller's job (:class:`vertiscope.store.Store`)
so this module stays a pure function of its inputs.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from .config import Config
from .core.chunk_builder import (
    Chunk,
    ChunkBuilder,
    build_structure_provider_from_dom,
    build_text_provider_from_dom,
    build_xpath_node_map,
)
from .core.chunk_render import ChunkInstanceRender, render_all_chunks
from .core.content_tagger import ContentTagger, TaggedContent
from .core.shadow_html_parser import ShadowDOM
from .core.signal_fields import SignalFieldRow, collect_signal_fields
from .core.trie_persistence import BuiltTrie, build_trie_from_tree
from .core.xpath_tree_builder import XPathTreeBuilder

logger = logging.getLogger(__name__)

ProgressFn = Callable[[str, str], None]
"""``(stage, detail)`` progress callback."""


@dataclass
class PipelineResult:
    """Everything one pipeline run produced."""

    url: str
    snapshot_id: str
    html: str
    dom: ShadowDOM
    tagged: TaggedContent
    content_tree: Dict[str, Any]
    trie: BuiltTrie
    chunks: List[Chunk]
    instances: List[ChunkInstanceRender] = field(default_factory=list)
    search_fields: List[SignalFieldRow] = field(default_factory=list)
    pagination_fields: List[SignalFieldRow] = field(default_factory=list)
    stage_ms: Dict[str, float] = field(default_factory=dict)
    elapsed_ms: float = 0.0

    def summary(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "snapshot_id": self.snapshot_id,
            "html_bytes": len(self.html),
            "content_xpaths": len(self.tagged.all_content_xpaths()),
            "patterns": self.trie.version.pattern_count,
            "content_patterns": self.trie.version.content_pattern_count,
            "chunks": len(self.chunks),
            "instances": len(self.instances),
            "search_fields": len(self.search_fields),
            "pagination_fields": len(self.pagination_fields),
            "elapsed_ms": round(self.elapsed_ms, 1),
        }


def _snapshot_id(url: str) -> str:
    salt = uuid.uuid4().hex[:8]
    return hashlib.sha1(f"{url}|{salt}".encode("utf-8")).hexdigest()[:16]


def run_pipeline(
    html: str,
    url: str,
    *,
    snapshot_id: Optional[str] = None,
    char_budget: int = 1200,
    render: bool = True,
    detect_signal_fields: bool = False,
    progress: Optional[ProgressFn] = None,
) -> PipelineResult:
    """Run the full pipeline over a captured HTML string.

    Parameters
    ----------
    html:
        Raw HTML. For a live page use :func:`scrape_url`.
    url:
        Source URL — keys the store and seeds instance ids.
    char_budget:
        Per-chunk text budget. Smaller = more, tighter chunks.
    render:
        Produce per-instance ``html_raw`` + ``rendered_text``. Required
        for indexing; only turn it off to inspect chunk structure alone.
    detect_signal_fields:
        Also locate the page's search input and pagination controls. Off by
        default: it is the single most expensive stage (it pulls in the
        5,800-line ``web_distiller_freq`` miner and sklearn — ~6s cold,
        ~180ms warm, versus ~75ms for the entire rest of the pipeline) and
        nothing in the scrape → index → retrieve path consumes it.
    """
    started = time.perf_counter()
    snapshot_id = snapshot_id or _snapshot_id(url)
    stage_ms: Dict[str, float] = {}
    mark = time.perf_counter()

    def _stage(name: str, detail: str = "") -> None:
        nonlocal mark
        now = time.perf_counter()
        stage_ms[name] = (now - mark) * 1000.0
        mark = now
        if progress:
            progress(name, detail)

    if not (html or "").strip():
        raise ValueError(f"empty HTML for {url!r} — nothing to chunk")

    # 1. parse
    dom = ShadowDOM(html)
    _stage("parse", f"{len(html):,} bytes")

    # 2. content tagging
    tagged = ContentTagger(dom).tag()
    _stage("tag", f"{len(tagged.all_content_xpaths()):,} content xpaths")

    # 3. collapsed content tree
    builder = XPathTreeBuilder()
    builder.add_tagged_content(tagged)
    content_tree = builder.build()
    _stage("tree")

    # 4. generalized-pattern trie (in-memory; no DB)
    trie = build_trie_from_tree(
        tree=content_tree, url=url, snapshot_id=snapshot_id, parent_version_id=""
    )
    _stage("trie", f"{trie.version.pattern_count:,} patterns")

    # 5. chunking. One O(N) DOM walk shared by the text provider, the
    #    structure provider and render_all_chunks.
    xpath_map = build_xpath_node_map(dom)
    text_provider = build_text_provider_from_dom(dom, xpath_map=xpath_map)
    structure_provider = build_structure_provider_from_dom(dom, xpath_map=xpath_map)
    chunks = ChunkBuilder(
        content_tree,
        text_provider,
        char_budget=char_budget,
        # all_tags is what populates each chunk's extraction_trie; without
        # it query_chunk finds instances but extracts no fields.
        all_tags=tagged.all_tags,
        structure_provider=structure_provider,
    ).build(snapshot_id=snapshot_id)
    _stage("chunk", f"{len(chunks):,} chunks")

    # cross-fill measured char counts back onto the pattern rows
    for ch in chunks:
        row = trie.by_pattern_key.get(ch.pattern)
        if row is not None:
            row.char_count = int(ch.char_count)
    trie.version.total_char_count = sum(r.char_count for r in trie.patterns)

    # 6. per-instance render
    instances: List[ChunkInstanceRender] = []
    if render:
        try:
            instances = render_all_chunks(chunks, dom, xpath_map=xpath_map)
        except Exception:
            logger.exception("render_all_chunks failed for %s", url)
        _stage("render", f"{len(instances):,} instances")

    # 7. search + pagination detection
    search_fields: List[SignalFieldRow] = []
    pagination_fields: List[SignalFieldRow] = []
    if detect_signal_fields:
        try:
            search_fields, pagination_fields = collect_signal_fields(dom, url)
        except Exception:
            logger.exception("collect_signal_fields failed for %s", url)
        _stage("signals", f"{len(search_fields)} search / {len(pagination_fields)} page")

    return PipelineResult(
        url=url,
        snapshot_id=snapshot_id,
        html=html,
        dom=dom,
        tagged=tagged,
        content_tree=content_tree,
        trie=trie,
        chunks=chunks,
        instances=instances,
        search_fields=search_fields,
        pagination_fields=pagination_fields,
        stage_ms=stage_ms,
        elapsed_ms=(time.perf_counter() - started) * 1000.0,
    )


def fetch_html(
    url: str,
    cfg: Config,
    *,
    single_pass: bool = False,
    max_duration: Optional[int] = None,
    pause: Optional[float] = None,
    headless: Optional[bool] = None,
    progress: Optional[ProgressFn] = None,
) -> str:
    """Live-scan ``url`` with Selenium and return the settled DOM as HTML.

    ``single_pass`` stops after the first settle pass (fast, fine for pages
    that fit above the fold). Otherwise the scroll loop runs until the page
    stops changing or the time box expires. Either way the HTML comes from
    one deep serialization taken *after* the loop — see
    :mod:`vertiscope.capture` for why the scan loop's own payloads are ignored.
    """
    from .browser import browser_session
    from .capture import deep_serialize, drive_to_settled

    duration = cfg.max_duration if max_duration is None else max_duration
    settle = cfg.scan_pause if pause is None else pause

    with browser_session(cfg, headless=headless) as driver:
        drive_to_settled(
            driver,
            url,
            max_duration=duration,
            pause=settle,
            single_pass=single_pass,
            progress=progress,
        )
        html = deep_serialize(driver).html

    if not html.strip():
        raise RuntimeError(f"scan of {url} produced no HTML")
    if progress:
        progress("capture", f"{len(html):,} bytes")
    return html


def scrape_url(
    url: str,
    cfg: Config,
    *,
    single_pass: bool = False,
    max_duration: Optional[int] = None,
    pause: Optional[float] = None,
    headless: Optional[bool] = None,
    char_budget: Optional[int] = None,
    detect_signal_fields: bool = False,
    progress: Optional[ProgressFn] = None,
) -> PipelineResult:
    """Live-scan a URL, then run the pipeline over what came back."""
    html = fetch_html(
        url,
        cfg,
        single_pass=single_pass,
        max_duration=max_duration,
        pause=pause,
        headless=headless,
        progress=progress,
    )
    return run_pipeline(
        html,
        url,
        char_budget=char_budget or cfg.char_budget,
        detect_signal_fields=detect_signal_fields,
        progress=progress,
    )
