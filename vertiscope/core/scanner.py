"""
scanner.py — Pure DOM scanner with merge-tree deduplication and delta streaming.

Extracts the full shadow DOM from a live Selenium WebDriver session,
incrementally merges snapshots into a master tree via structural
signature dedup, and returns the final complete HTML string.

Architecture (REAL_TIME_SCAN_UPDATE.md):
  - First iteration: full unified JS extraction (tree + _meta + leaves)
  - Subsequent iterations: MutationObserver-driven delta capture
  - Hash-diff transport: JS accepts prevHashes and only emits changed nodes
  - Scanner yields (master_tree, nodeMap, leaves, removedXPaths) per iteration

Merge-tree approach (ported from dom_deep_serializer backup):
  - Additive merging: new children are appended, existing recursed into
  - No subtree pruning — full DOM structure is preserved
  - Signatures based on tag + id + key attributes + text prefix

This module has NO database, layout, or GUI dependencies.
It is a pure scan → merge → serialize pipeline.
"""

from __future__ import annotations

import time
import json
import logging
import os
import threading
from typing import Optional, Set, Callable, Tuple, List, Dict, Iterator, Any
from copy import deepcopy

from selenium.webdriver.remote.webdriver import WebDriver

from vertiscope.core.pipeline_config import get_config
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.common.by import By

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# JavaScript: MutationObserver-based DOM settle detection.
#
# Installed once per page load.  The observer watches the entire subtree for
# childList mutations (content injection).  When a mutation fires it clears
# the "ready" flag and arms a 200 ms debounce timer; when the timer fires
# without further mutations the flag is reset to true.
#
# This is strictly faster than polling scrollHeight because:
#   - It resolves as soon as DOM mutations stop (≈200 ms after last injection)
#     rather than needing a fixed stable-window measured at coarse intervals.
#   - No-content scrolls (already at bottom, nothing new) resolve immediately
#     after a single poll, whereas scrollHeight polling always burns the full
#     stable_for window.
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# The names this scanner leaves on `window`.
#
# Everything below installs page-visible state: an observer, two configuration
# numbers, the chunk engine's handle, and the element the pagination probe
# picked. All of them used to be enumerable own properties under a fixed
# `_wfh` prefix, which is two separate problems.
#
# A fixed prefix is a *signature*: one regex over `Object.keys(window)` names
# the tool that is reading the page, and a reader who came here specifically
# not to be profiled is then profiled by the thing they read the page with.
# Enumerability is what makes that regex a one-liner rather than a diff
# against a clean profile.
#
# So the names are drawn per scan from the shapes ordinary pages leave on
# `window`, and every one is installed non-enumerable. The honest claim -- the
# same one `sensing.py` makes about the sensor handle -- is that this raises
# the cost of finding them, not that it makes them unfindable:
# `Object.getOwnPropertyNames` still lists a non-enumerable own property. What
# it removes is the cheap, targeted probe.
#
# The placeholders are kept literal in the JS below so the source stays
# greppable; `ShadowDOMScanner._js` substitutes the session's names on the way
# to the browser, including into the chunk engine's own source.
# ---------------------------------------------------------------------------
PAGE_GLOBALS = ("_wfhEngine", "_wfhCharBudget", "_wfhDebounceMs",
                "_wfhMO", "_wfhMOReady", "_wfhMOTimer", "_wfhPaginateTop")


def _new_page_globals() -> Dict[str, str]:
    """One unremarkable name per global, distinct within the session."""
    from ..sensing import Sensor

    chosen: Dict[str, str] = {}
    taken = set()
    for i, name in enumerate(PAGE_GLOBALS):
        candidate = Sensor._plausible_name(f"{name}{i}")
        while candidate in taken:
            candidate = Sensor._plausible_name(f"{name}{i}{len(taken)}")
        taken.add(candidate)
        chosen[name] = candidate
    return chosen


# Redefine an already-assigned global as non-enumerable. Used for the chunk
# engine's handle, which the engine's own source assigns to itself.
HIDE_GLOBAL_JS = (
    "var k = arguments[0];"
    "if (!Object.prototype.hasOwnProperty.call(window, k)) return false;"
    "var v = window[k];"
    "try { delete window[k]; } catch (e) { return false; }"
    "Object.defineProperty(window, k, "
    "{value: v, writable: true, configurable: true, enumerable: false});"
    "return true;"
)

# Remove one global entirely. A property that is gone cannot be found at all,
# which is strictly better than hidden wherever the value is no longer needed.
DROP_GLOBAL_JS = "try { delete window[arguments[0]]; } catch (e) {}"


INSTALL_OBSERVER_JS = """
(function() {
    if (window._wfhMO) return;
    window._wfhMOReady = true;
    window._wfhMOTimer = null;
    window._wfhMO = new MutationObserver(function() {
        window._wfhMOReady = false;
        if (window._wfhMOTimer) clearTimeout(window._wfhMOTimer);
        window._wfhMOTimer = setTimeout(function() {
            window._wfhMOReady = true;
        }, 80);
    });
    var target = document.body || document.documentElement;
    if (target) window._wfhMO.observe(target, {childList: true, subtree: true});
})();
"""

# Returns true only when the observer exists AND has been quiet for 200 ms.
# Resolves true when EITHER:
#   * the legacy ``_wfhMO`` settle observer says "no mutations in the last
#     200 ms" (non-JS-engine path), OR
#   * the chunk engine's own MutationObserver pipeline is quiescent
#     (``_wfhEngine.isSettled()`` flips true 80 ms after the last batch
#     of mutations).
# Previously this only consulted ``_wfhMO`` — which was never installed in
# JS-engine mode — so every quiet iter ate the full SETTLE_TIMEOUT
# ceiling (~250 ms). Consulting the engine's settle state lets quiet
# iters return in ~80 ms after the last mutation instead of always
# burning the ceiling.
CHECK_OBSERVER_JS = (
    "return ("
    " (!!window._wfhMO && window._wfhMOReady !== false) ||"
    " (!!window._wfhEngine && typeof window._wfhEngine.isSettled === 'function'"
    "  && window._wfhEngine.isSettled())"
    ");"
)

# ---------------------------------------------------------------------------
# JavaScript: Unified single-pass extraction — tree + _meta + leaves.
#
# Replaces the separate EXTRACT_DOM_JSON_JS + EXTRACT_CHUNK_DATA_JS with one
# recursive walk that produces:
#   1. A full tree (for merge-dedup and billboard serialization)
#   2. _meta properties on every element node (content metadata)
#   3. A flat nodeMap of changed nodes (hash-diff transport)
#   4. A flat leaves array of content-leaf xpaths
#
# Accepts arguments[0] = prevHashes: {xpath → content_hash} or {} on first call.
# Returns JSON string: { tree: {...}, nodeMap: {xpath: _meta}, leaves: [...] }
# ---------------------------------------------------------------------------
# ---------------------------------------------------------------------------
# Signature computation (matches backup architecture)
# ---------------------------------------------------------------------------


def compute_node_signature(node: dict) -> str:
    """
    Deterministic identity for a DOM node.

    Uses tag + id + key attributes (href, src, data-id, data-index,
    aria-label) + text content prefix for text nodes.
    """
    if not node:
        return ""

    if "_node_sig" in node:
        return node["_node_sig"]

    tag = node.get("tagName", node.get("nodeName", ""))
    parts = [tag]

    if "id" in node:
        parts.append(f"id:{node['id']}")

    # REMOVED: className. Classes change dynamically in SPAs (hover, focus, lazy-load)
    # which causes the node to be appended as a duplicate sibling instead of merged cleanly.

    attrs = node.get("attributes")
    if attrs:
        for key in ("href", "src", "data-id", "data-index", "name", "type", "role"):
            if key in attrs:
                parts.append(f"{key}:{str(attrs[key])[:50]}")

        # ADDED: data-content-hash. Strictly prevents Frankenstein merging of recycled DOM nodes
        # in virtualized lists by binding structural identity to actual content state.
        # Excluded from high-level skeletons to prevent entire-page ancestor duplication.
        if tag.lower() not in (
            "html",
            "body",
            "head",
            "main",
            "#document",
            "header",
            "footer",
            "nav",
        ):
            ch = attrs.get("data-content-hash")
            if ch:
                parts.append(f"ch:{ch}")

    if node.get("nodeType") == 3:  # Text node
        text = " ".join((node.get("textContent") or "").split())
        if text:
            parts.append(f"txt:{text[:30]}")

    sig = "|".join(parts)
    node["_node_sig"] = sig
    return sig


# ---------------------------------------------------------------------------
# Tree utilities
# ---------------------------------------------------------------------------


def count_nodes(node: dict) -> int:
    """Count total nodes in a JSON DOM tree."""
    if not node:
        return 0
    total = 1
    for child in node.get("children", []):
        total += count_nodes(child)
    shadow = node.get("shadowRoot")
    if shadow:
        for s_child in shadow.get("children", []):
            total += count_nodes(s_child)
    return total


def serialize_to_html(node: dict) -> str:
    """
    Convert a JSON DOM tree back to an HTML string with
    declarative shadow DOM (<template shadowrootmode>).
    """
    parts = []
    _serialize_node(node, parts)
    return "".join(parts)


def _serialize_node(node: dict, parts: list) -> None:
    if not node:
        return

    node_type = node.get("nodeType", 0)

    # Text
    if node_type == 3:
        text = node.get("textContent", "")
        parts.append(
            text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        )
        return

    # Comment
    if node_type == 8:
        parts.append(f"<!--{node.get('nodeValue', '')}-->")
        return

    # Doctype
    if node_type == 10:
        parts.append(f"<!DOCTYPE {node.get('name', 'html')}>")
        return

    # Element
    if node_type == 1:
        tag = node.get("tagName", "div")
        parts.append(f"<{tag}")

        attrs = node.get("attributes")
        if attrs:
            for k, v in attrs.items():
                parts.append(f' {k}="{str(v).replace(chr(34), "&quot;")}"')
        parts.append(">")

        # Void elements
        if tag in (
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        ):
            return

        # Shadow DOM
        shadow = node.get("shadowRoot")
        if shadow:
            mode = shadow.get("mode", "open")
            parts.append(f'<template shadowrootmode="{mode}">')
            for child in shadow.get("children", []):
                _serialize_node(child, parts)
            parts.append("</template>")

        # Light DOM children
        for child in node.get("children", []):
            _serialize_node(child, parts)

        parts.append(f"</{tag}>")


# ---------------------------------------------------------------------------
# Background Continuous Scroller
# ---------------------------------------------------------------------------


class BackgroundScroller:
    """Scrolls the page in tiny increments on a timer, giving a
    smooth continuous motion while mutation events are collected.
    """

    def __init__(
        self, driver: WebDriver, step_fraction: float = 0.03, interval_ms: int = 80
    ) -> None:
        self.driver = driver
        self.step_fraction = step_fraction
        self.interval = interval_ms / 1000.0
        self._timer: Optional[threading.Timer] = None
        self._running = False
        self._lock = threading.Lock()

    def start(self) -> None:
        with self._lock:
            if self._running:
                return
            self._running = True
        self._schedule()

    def _schedule(self) -> None:
        with self._lock:
            if not self._running:
                return
            self._scroll_step()
            self._timer = threading.Timer(self.interval, self._schedule)
            self._timer.start()

    def _scroll_step(self) -> None:
        try:
            self.driver.execute_script(
                f"window.scrollBy(0, Math.max(2, window.innerHeight * "
                f"{self.step_fraction}));"
            )
        except Exception:
            pass

    def stop(self) -> None:
        with self._lock:
            self._running = False
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None


# ---------------------------------------------------------------------------
# Core scanner — merge-tree architecture
# ---------------------------------------------------------------------------


class ShadowDOMScanner:
    """
    Pure DOM scanner using merge-tree deduplication.

    Instead of pruning seen subtrees (which causes truncation), we
    accumulate ALL content into a master tree via additive merging.
    This preserves the full DOM structure across scroll positions.

    No database, no layout, no GUI dependencies.

    Usage:
        scanner = ShadowDOMScanner(driver)
        html = scanner.scan('https://example.com', max_duration=60)
        # html is the fully merged, complete DOM as an HTML string
    """

    # Termination tuning -----------------------------------------------
    #
    # Two consecutive quiet iterations are enough to confirm the page has
    # no more lazy content — the legacy three-iteration limit was defensive
    # against slow React hydration, but with MutationObserver settling we
    # already wait until the DOM is truly quiescent before each capture,
    # so a second quiet iteration is genuine signal not noise.
    NO_CHANGE_LIMIT: int = 3

    # MutationObserver-based settling: wait at most SETTLE_TIMEOUT seconds
    # for the observer's 80 ms debounce to fire. The MO returns as soon as
    # mutations stop, so the timeout is only a ceiling for actively
    # mutating pages (animations, infinite scrollers, ad refresh cycles).
    # Dropped to 0.25s so per-iter wall clock stays close to the user's
    # --pause value. On archive.org/youtube the MO actually settles in
    # 100-180ms; this ceiling only fires for misbehaving pages and a
    # short ceiling there is correct (better to advance to the next
    # scroll than hang on a never-quiet feed).
    SETTLE_TIMEOUT: float = 0.25
    SETTLE_STABLE_FOR: float = 0.1
    # Poll cadence for the MO settle check. 15ms gives us roughly two
    # polls inside the 80ms debounce window — enough to catch the
    # transition without burning CPU on a tight spin.
    POLL_INTERVAL: float = 0.015
    MAX_SCROLLS: int = 60
    # Scroll step as a fraction of viewport height. A small step keeps content
    # in view long enough for lazy-load hooks (IntersectionObserver, infinite
    # scroll shims) to fire and for the next batch of tiles to render before
    # we move on. A full-viewport jump outran slow feeds and caused the
    # scanner to miss rows on pages with expensive row hydration.
    SCROLL_STEP_FRACTION: float = 0.4

    def __init__(self, driver: WebDriver):
        self.driver = driver
        # Fresh per scanner, so two sessions do not share a name a page could
        # correlate them by.
        self._globals = _new_page_globals()
        self.master_tree: Optional[dict] = None
        self._changes_detected: bool = False
        self._added_nodes: list = []
        self._sig_cache: dict = {}
        self._sig_cache_by_hash: dict = {}
        # O(1) billboard lookup: xpath → tree_node, populated during initial
        # capture and updated incrementally on each delta merge.
        self._xpath_node_index: Dict[str, dict] = {}

        # Hash-diff transport: maps xpath → content_hash from the previous
        # iteration. Passed to JS so only changed nodes are returned.
        self._prev_hashes: Dict[str, int] = {}

        # Delta observer state: whether the delta observer has been installed
        self._delta_observer_installed: bool = False

        # Adaptive scroll state: track settle duration and consecutive repeats
        # so we hold position on actively-mutating pages (e.g. slow feeds).
        self._last_settle_duration: float = 0.0
        self._consecutive_slow_settles: int = 0
        # Fraction of SETTLE_TIMEOUT that counts as "slow" (page still loading)
        self._ADAPTIVE_SLOW_THRESHOLD: float = 0.75
        # Max consecutive repeats at the same scroll position before advancing
        self._ADAPTIVE_MAX_REPEATS: int = 2

        cfg = get_config()
        # Auto-stop after 5 consecutive quiet iterations — matches the
        # original spec's "stop when scroll plateaus" rule. The end-of-
        # scroll pagination probe still fires once at the boundary; if
        # it injects fresh content the streak resets and the loop
        # continues, otherwise the scan exits cleanly. Previously 999
        # which meant the scan only ever stopped on max-duration.
        self.NO_CHANGE_LIMIT = 5
        # The legacy native-snapshot path (_capture_unified / _merge_trees;
        # the historical native impl was removed along with backend_slow/) was
        # removed when the JS chunk engine took over, but three call sites
        # in this file (search for ``_capture_unified`` below) still
        # branch on ``_use_js_engine``. Anything other than ``'js'`` would
        # hit AttributeError at runtime. Force the JS engine on with a
        # clear warning rather than crash later — the legacy path is
        # genuinely gone, not merely opt-out. Subclasses that bring their
        # own legacy helpers (test_scanner_scroll.py::_ScriptedScanner)
        # are detected via ``hasattr`` and keep their requested mode.
        _requested = getattr(cfg, 'live_chunking', 'js')
        _legacy_helpers_present = (
            hasattr(self, "_capture_unified") and hasattr(self, "_merge_trees")
        )
        if _requested != 'js' and not _legacy_helpers_present:
            logger.warning(
                "[Scanner] cfg.live_chunking=%r requested but the native "
                "snapshot path was removed; forcing JS chunk engine. Set "
                "live_chunking='js' to silence this warning.",
                _requested,
            )
            self._use_js_engine = True
        else:
            self._use_js_engine = _requested == 'js'

    @property
    def last_delta(self) -> Dict[str, Any]:
        """Return the last delta metadata from the most recent scan iteration.

        Used by the mapper's _process_delta to update indexes without
        re-walking the DOM. treeFragments is not needed by the mapper
        (it is consumed by the scanner internally for master tree merging)
        but is included for completeness / debugging.
        """
        return {}

    def _js(self, source: str) -> str:
        """This session's spelling of a script written against placeholders.

        Longest placeholder first, because `_wfhMO` is a prefix of
        `_wfhMOReady`: substituting the short one first would rewrite
        `window._wfhMOReady` into a name that belongs to neither.
        """
        for placeholder in sorted(self._globals, key=len, reverse=True):
            source = source.replace(placeholder, self._globals[placeholder])
        return source

    def _hide_global(self, name: str) -> None:
        """Make one already-assigned global non-enumerable. Never fatal."""
        try:
            self.driver.execute_script(HIDE_GLOBAL_JS, self._globals[name])
        except Exception as exc:  # noqa: BLE001 - a page that refuses still scans
            logger.debug("[Scanner] could not hide %s: %s", name, exc)

    def _drop_global(self, name: str) -> None:
        """Remove one global outright. Never fatal."""
        try:
            self.driver.execute_script(DROP_GLOBAL_JS, self._globals[name])
        except Exception as exc:  # noqa: BLE001
            logger.debug("[Scanner] could not drop %s: %s", name, exc)

    def _inject_chunk_engine(self):
        # Single canonical location. The upstream two-path fallback existed
        # only because the asset lived in the mapper package; here it ships
        # inside vertiscope.core.
        js_path = os.path.join(os.path.dirname(__file__), 'js', 'wfh_chunk_engine.js')
        if not os.path.exists(js_path):
            raise FileNotFoundError(
                f"in-page chunk engine missing at {js_path} — the vertiscope "
                "install is incomplete (core/js/wfh_chunk_engine.js)"
            )
        with open(js_path, 'r', encoding='utf-8') as f:
            engine_js = f.read()
        cfg = get_config()
        char_budget = int(getattr(cfg, 'hard_char_limit', 2048))
        # Hand the budget + a debounce window to the engine before it boots.
        # The engine reads window._wfhCharBudget and window._wfhDebounceMs
        # at startup. Without this prefix the engine fell back to its
        # hardcoded 2048 default, so --char-budget was a no-op in JS mode.
        # Non-enumerable from the moment they exist, rather than assigned and
        # hidden afterwards: between the two statements they would have been
        # listable, and a MutationObserver on the page runs in that gap.
        self.driver.execute_script(
            self._js(
                "Object.defineProperty(window, '_wfhCharBudget', "
                f"{{value: {char_budget}, writable: true, "
                "configurable: true, enumerable: false});"
                "Object.defineProperty(window, '_wfhDebounceMs', "
                "{value: 80, writable: true, configurable: true, "
                "enumerable: false});"
            )
        )
        self.driver.execute_script(self._js(engine_js))
        # The engine assigns its own handle, so it can only be hidden after
        # the fact. The two numbers it read at boot are not needed again and
        # are deleted rather than hidden.
        self._hide_global("_wfhEngine")
        self._drop_global("_wfhCharBudget")
        self._drop_global("_wfhDebounceMs")
        logger.info("JS chunk engine injected (char_budget=%d)", char_budget)

    # Combined fetch — pulls both the delta queue AND the engine stats in
    # a single Marionette round-trip. driver.execute_script costs ~5-10 ms
    # in fixed per-call overhead regardless of script size, so two
    # separate calls per iter spent a full extra round-trip we can
    # collapse into one. The deltas are returned in arr.deltas; stats
    # (used for the iter log line) in arr.stats.
    _FETCH_DELTAS_AND_STATS_JS = (
        "if (!window._wfhEngine) return { deltas: [], stats: null };"
        "return {"
        " deltas: window._wfhEngine.getDeltaQueue(),"
        " stats: (typeof window._wfhEngine.getStats === 'function')"
        "        ? window._wfhEngine.getStats() : null"
        "};"
    )

    def _fetch_deltas_and_stats(self):
        """Single round-trip for delta drain + instrumentation counters."""
        try:
            res = self.driver.execute_script(
                self._js(self._FETCH_DELTAS_AND_STATS_JS))
            return res or {"deltas": [], "stats": None}
        except Exception:
            return {"deltas": [], "stats": None}

    def _fetch_engine_stats(self):
        """Fetch the JS engine's instrumentation counters for diagnostics."""
        try:
            return self.driver.execute_script(self._js(
                "return window._wfhEngine && window._wfhEngine.getStats "
                "? window._wfhEngine.getStats() : null;"
            ))
        except Exception:
            return None

    def _fetch_js_deltas(self):
        return self.driver.execute_script(self._js(
            "return window._wfhEngine ? window._wfhEngine.getDeltaQueue() : [];"
        ))

    def scan(
        self, url: str, max_duration: int = 60, pause: float = 1.0,
        force_reload: bool = False
    ) -> Iterator[Tuple[dict, list, list]]:
        """
        Scan a URL, scrolling and merging incrementally.

        Args:
            url: Target URL to scan.
            max_duration: Max seconds to run the scroll loop.
            pause: Render-slack sleep after each scroll (seconds).
            force_reload: Navigate even when already on ``url``. Required to
                observe change over time — see the navigation block below.

        Yields:
            deltas: list of chunk events (add, replace, remove).
        """
        # Navigate (skip if already there)
        try:
            current = self.driver.current_url
        except Exception as e:
            logger.warning(f"Failed to get current URL (window closed?): {e}")
            try:
                handles = self.driver.window_handles
                if handles:
                    self.driver.switch_to.window(handles[0])
                    current = self.driver.current_url
                else:
                    logger.error("No windows available.")
                    return
            except Exception as inner_e:
                logger.error(f"Cannot recover driver window: {inner_e}")
                return

        # Skipping navigation when already on the URL is right *within* a scan
        # — re-navigating would reset the scroll position the settle loop is
        # driving. It is wrong for a re-scan: the whole point of scanning a URL
        # again is to see whether it changed, and reusing the loaded DOM
        # guarantees the answer is "no". Callers checking for change pass
        # force_reload=True.
        if force_reload or (current != url and current != url + "/"):
            logger.info(f"Navigating to {url}")
            try:
                self.driver.get(url)
            except Exception as e:
                logger.error(f"Failed to navigate to {url}: {e}")
                return
        else:
            logger.info(f"Already on {url}")

        # Wait for page load
        try:
            WebDriverWait(self.driver, 20).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )
        except Exception:
            logger.warning("Page load timeout, proceeding anyway.")

        # Install dom observer ONLY if we are not using the JS chunk engine.
        # The JS engine manages its own MutationObserver, and having two
        # causes double-handling and can destabilise the DOM.
        if not self._use_js_engine:
            self._install_dom_observer()
            time.sleep(0.15)
            self._wait_for_dom_settled(timeout=self.SETTLE_TIMEOUT)
        else:
            # Still wait for initial load without conflicting observer
            self._wait_for_scroll_height_stable(timeout=self.SETTLE_TIMEOUT)

        if self._use_js_engine:
            # Wait for the page's own JS to render content into the body
            # OR into any shadow root before injecting the chunk engine.
            #
            # Many SPAs (Angular, Lit, web components) hydrate their visible
            # content entirely inside open shadow roots, so a probe that
            # only reads `document.body.innerText` reports 0 forever and we
            # waste the full timeout. archive.org is the canonical example —
            # its <app-root> stays light-DOM-empty while 119+ shadow roots
            # populate with the actual cards. We poll a deep-walk text
            # length that pierces shadow boundaries, so the wait short-
            # circuits as soon as ANY content (light or shadow) appears.
            t_wait = time.time()
            deep_len = 0
            try:
                self.driver.execute_script(
                    "window.scrollBy(0, 100);"
                )  # nudge to trigger any IntersectionObserver fences
                deadline = time.time() + 8.0
                while time.time() < deadline:
                    deep_len = self.driver.execute_script(
                        """
                        var stack = [document.documentElement];
                        var total = 0;
                        while (stack.length && total < 400) {
                            var n = stack.pop();
                            if (!n || n.nodeType !== 1) continue;
                            for (var c = n.firstChild; c; c = c.nextSibling) {
                                if (c.nodeType === 3 && c.nodeValue) total += c.nodeValue.length;
                            }
                            if (n.shadowRoot) {
                                for (var i = 0; i < n.shadowRoot.children.length; i++) {
                                    stack.push(n.shadowRoot.children[i]);
                                }
                            }
                            for (var i = 0; i < n.children.length; i++) stack.push(n.children[i]);
                        }
                        return total;
                        """
                    )
                    # Real drivers return an int; defensive None / non-
                    # numeric handling so a fake harness or a Selenium
                    # edge case doesn't crash this poll with
                    # ``'>' not supported between NoneType and int``.
                    if isinstance(deep_len, (int, float)) and deep_len > 200:
                        break
                    time.sleep(0.1)
                logger.info(
                    "[Scanner] Pre-inject wait: %.2fs (deep text len=%d)",
                    time.time() - t_wait,
                    deep_len,
                )
            except Exception as exc:
                logger.warning("[Scanner] Pre-inject wait failed: %s", exc)

            self._inject_chunk_engine()
            time.sleep(0.5)
            # One-time page-state dump so we can tell the difference between
            # "page never rendered" and "engine missed the content" when no
            # chunks emit. Logged at INFO so it's visible under the user's
            # default --log-level INFO.
            try:
                # Diagnostic walks INTO shadow roots so we can tell the
                # difference between "Angular never bootstrapped" and
                # "Angular rendered but only into ShadowRoot, which our
                # naive innerHTML/innerText probes can't see".
                state = self.driver.execute_script("""
                    function deepStats(root, acc) {
                        if (!root) return;
                        var stack = [root];
                        while (stack.length) {
                            var n = stack.pop();
                            if (!n || n.nodeType !== 1) continue;
                            acc.elementCount++;
                            // Count text in direct text-node children
                            for (var c = n.firstChild; c; c = c.nextSibling) {
                                if (c.nodeType === 3) {
                                    var t = c.nodeValue;
                                    if (t) acc.textLen += t.length;
                                }
                            }
                            if (n.shadowRoot) {
                                acc.shadowRootCount++;
                                acc.shadowExamples.push({
                                    host: n.tagName.toLowerCase(),
                                    mode: n.shadowRoot.mode,
                                    childCount: n.shadowRoot.children.length,
                                });
                                for (var i = 0; i < n.shadowRoot.children.length; i++) {
                                    stack.push(n.shadowRoot.children[i]);
                                }
                            }
                            for (var i = 0; i < n.children.length; i++) {
                                stack.push(n.children[i]);
                            }
                        }
                    }
                    var acc = { elementCount: 0, textLen: 0,
                                shadowRootCount: 0, shadowExamples: [] };
                    deepStats(document.documentElement, acc);
                    var b = document.body;
                    var first = b && b.children[0];
                    return {
                        title: document.title,
                        url: window.location.href,
                        readyState: document.readyState,
                        bodyHtmlLen: b ? b.innerHTML.length : 0,
                        bodyTextLen: b ? (b.innerText || '').length : 0,
                        bodyChildrenCount: b ? b.children.length : 0,
                        scriptsCount: document.scripts.length,
                        firstChildTag: first ? first.tagName : null,
                        firstChildId: first ? first.id : null,
                        firstChildClass: first ? (first.className || '').slice(0, 80) : null,
                        firstChildHtmlPreview: first ? first.outerHTML.slice(0, 240) : null,
                        firstChildHasShadow: !!(first && first.shadowRoot),
                        deepElementCount: acc.elementCount,
                        deepTextLen: acc.textLen,
                        shadowRootCount: acc.shadowRootCount,
                        shadowExamples: acc.shadowExamples.slice(0, 6),
                        navWebdriver: navigator.webdriver,
                        userAgent: navigator.userAgent,
                    };
                """)
                logger.info("[Scanner] Page state @inject: %s", state)
            except Exception as exc:
                logger.warning("[Scanner] Page-state dump failed: %s", exc)
            initial_deltas = self._fetch_js_deltas()
            if initial_deltas:
                yield initial_deltas
        else:
            # Legacy native-snapshot path; see __init__ for why this is
            # normally unreachable. Tests monkeypatch the helpers onto
            # the instance, so we guard with hasattr rather than typing.
            if not (hasattr(self, "_capture_unified") and hasattr(self, "_merge_trees")):
                logger.warning(
                    "[Scanner] Non-JS path requested but native helpers "
                    "absent; bailing out of initial snapshot."
                )
            else:
                try:
                    self.master_tree = self._capture_unified()
                    initial_count = count_nodes(self.master_tree)
                    logger.info(f"Initial snapshot: {initial_count} nodes")
                    yield self.master_tree, [self.master_tree], []
                except Exception as e:
                    logger.error(f"Legacy capture failed: {e}")

        # Scroll + merge loop
        start = time.time()
        iteration = 0
        no_change_streak = 0
        # Reset per-scan so each scan() call gets its own end-of-scroll
        # pagination attempt. Persisting across scans would silently
        # disable Load-more clicking on every URL after the first.
        self._did_end_pagination = False
        logger.info("[Scanner] Beginning scroll loop (max %d iters, %ds timeout, "
                    "no_change_limit=%d)", self.MAX_SCROLLS, max_duration, self.NO_CHANGE_LIMIT)

        while time.time() - start < max_duration:
            if iteration >= self.MAX_SCROLLS:
                logger.info(f"Iter {iteration}: reached MAX_SCROLLS limit. Stopping.")
                break

            iteration += 1
            # Per-phase timing so the user can see exactly where the wall-clock
            # is being spent inside each iteration. Logged at INFO so it shows
            # up under --log-level INFO without enabling debug noise.
            t_iter = time.time()
            self._scroll(pause)
            t_scroll = time.time()

            if self._use_js_engine:
                # Single round-trip: drain deltas + read engine stats.
                # Was two separate execute_script calls = two Marionette
                # round-trips per iter.
                bundled = self._fetch_deltas_and_stats()
                deltas = bundled.get("deltas") or []
                eng_stats = bundled.get("stats") or {}
                t_fetch = time.time()
                # Always yield (possibly empty) so the mapper counts the
                # iteration in pipeline.note_iter and surfaces stats even
                # when JS produced nothing this scroll.
                logger.info(
                    "[Scanner] iter %d – scroll+settle %.3fs  fetch %.3fs  "
                    "deltas=%d  engine{runs=%s leaves=%s chunks=%s "
                    "body=%s deep=%s shadow=%s}",
                    iteration,
                    t_scroll - t_iter,
                    t_fetch - t_scroll,
                    len(deltas),
                    eng_stats.get("chunkSubtreeRuns"),
                    eng_stats.get("lastLeafCount"),
                    eng_stats.get("totalChunks"),
                    eng_stats.get("bodyTextLen"),
                    eng_stats.get("deepTextLen"),
                    eng_stats.get("shadowRoots"),
                )
                if deltas:
                    no_change_streak = 0
                else:
                    no_change_streak += 1
                yield deltas
                if not deltas and no_change_streak >= self.NO_CHANGE_LIMIT:
                    # End-of-scroll pagination probe. After NO_CHANGE_LIMIT
                    # consecutive quiet iterations we attempt ONE last
                    # paginate() click. If a Next/Load-more control fires,
                    # we explicitly scroll once more, settle, and yield the
                    # resulting deltas so the fresh page of content lands
                    # in the index before the scan exits. If nothing
                    # clicks, the scan exits cleanly.
                    if not getattr(self, "_did_end_pagination", False):
                        self._did_end_pagination = True
                        if self._paginate():
                            logger.info(
                                "[Scanner] End-of-scroll pagination fired — "
                                "performing one extra scroll-and-listen pass."
                            )
                            # One explicit scroll so newly injected content
                            # below the old viewport bottom gets revealed
                            # to any IntersectionObserver-gated tiles.
                            try:
                                self._scroll(pause)
                            except Exception as exc:
                                logger.debug("[Scanner] post-paginate scroll failed: %s", exc)
                            t_paginate = time.time()
                            paginate_deltas = self._fetch_js_deltas()
                            logger.info(
                                "[Scanner] paginate-pass fetched %d delta(s) in %.3fs",
                                len(paginate_deltas), time.time() - t_paginate,
                            )
                            if paginate_deltas:
                                yield paginate_deltas
                            # Reset streak so the loop can continue picking
                            # up any post-pagination lazy-loaded content
                            # for one more cycle, but cap remaining work
                            # so a bad pagination action can't extend the
                            # scan indefinitely.
                            no_change_streak = 0
                            continue
                    logger.info("[Scanner] Stopping – no new content after %d scrolls.", self.NO_CHANGE_LIMIT)
                    break
            else:
                # Legacy native-snapshot path; see __init__ for why this
                # is normally unreachable. Tests monkeypatch the helpers
                # onto the instance, so we guard with hasattr rather than
                # crash with a bare AttributeError mid-scroll.
                if not (hasattr(self, "_capture_unified") and hasattr(self, "_merge_trees")):
                    logger.warning(
                        "[Scanner] Non-JS scroll iter requested but native "
                        "helpers absent; stopping loop."
                    )
                    break
                try:
                    snapshot = self._capture_unified()
                    self._changes_detected = False
                    self._added_nodes = []
                    self._sig_cache.clear()
                    self._merge_trees(self.master_tree, snapshot)

                    if self._changes_detected:
                        logger.info(
                            "Iter %d: merged %d new node(s)",
                            iteration, len(self._added_nodes),
                        )
                        no_change_streak = 0
                        yield self.master_tree, self._added_nodes, []
                    else:
                        no_change_streak += 1
                        logger.info(
                            f"Iter {iteration}: no new content "
                            f"({no_change_streak}/{self.NO_CHANGE_LIMIT})."
                        )
                        if no_change_streak >= self.NO_CHANGE_LIMIT:
                            logger.info(
                                f"Iter {iteration}: {self.NO_CHANGE_LIMIT} quiet iterations. "
                                f"Stopping scan."
                            )
                            break
                except Exception as e:
                    logger.error(f"Legacy iteration failed: {e}")

        # Final full capture so the mapper can distill + layout.
        # When JS engine is active, disable it momentarily to run the native
        # unified extraction without observer interference.
        #
        # NOTE: _capture_unified / _merge_trees are not currently implemented
        # on this scanner — the legacy unified-snapshot path was removed when
        # the JS chunk engine took over. Skip the final-capture block when
        # the methods are absent so we don't log a confusing AttributeError
        # at the tail of every JS-mode scan. The mapper's no-DOM branch
        # already handles the JS-only case correctly.
        if not hasattr(self, "_capture_unified"):
            return

        if self._use_js_engine:
            # Deleted, not set to undefined. `window.x = undefined` leaves
            # the own property in place, so the page kept a name that said a
            # scanner had been here after the scanner had gone.
            self._drop_global("_wfhEngine")
            time.sleep(0.2)

        try:
            unified = self._capture_unified()
            if unified and unified.get("tree"):
                self.master_tree = unified["tree"]
                yield self.master_tree, [], []
                logger.info("[Scanner] Final unified tree captured (%d nodes)",
                            count_nodes(self.master_tree))
            else:
                logger.warning("[Scanner] Final unified capture returned empty tree")
        except Exception as e:
            logger.error("[Scanner] Final unified capture failed: %s", e)

        # Re-inject the chunk engine if needed (for future scans on the same driver)
        if self._use_js_engine:
            self._inject_chunk_engine()

    #def scan_continuous(
    #    self,
    #    url: str,
    #    max_duration: int = 60,
    #    step_fraction: float = 0.03,
    #    capture_interval_ms: int = 80,
    #) -> Iterator[Dict[str, Any]]:
    #    """Continuously scroll the page and yield deltas as they appear.
#
    #    Yields dicts with keys: ``nodeMap``, ``leaves``, ``removedXPaths``.
    #    The caller (mapper) feeds these directly to ``_process_delta``.
    #    """
    #    # Navigate (skip if already there)
    #    try:
    #        current = self.driver.current_url
    #    except Exception as e:
    #        logger.warning(f"Failed to get current URL (window closed?): {e}")
    #        try:
    #            handles = self.driver.window_handles
    #            if handles:
    #                self.driver.switch_to.window(handles[0])
    #                current = self.driver.current_url
    #            else:
    #                logger.error("No windows available.")
    #                return
    #        except Exception as inner_e:
    #            logger.error(f"Cannot recover driver window: {inner_e}")
    #            return
#
    #    if current != url and current != url + "/":
    #        logger.info(f"Navigating to {url}")
    #        try:
    #            self.driver.get(url)
    #        except Exception as e:
    #            logger.error(f"Failed to navigate to {url}: {e}")
    #            return
    #    else:
    #        logger.info(f"Already on {url}")
#
    #    # Wait for page load
    #    try:
    #        WebDriverWait(self.driver, 20).until(
    #            lambda d: d.execute_script("return document.readyState") == "complete"
    #        )
    #    except Exception:
    #        logger.warning("Page load timeout, proceeding anyway.")
#
    #    self._install_dom_observer()
    #    time.sleep(0.15)
    #    self._wait_for_dom_settled(timeout=self.SETTLE_TIMEOUT)
#
    #    if self._use_js_engine:
    #        self._inject_chunk_engine()
#
    #    scroller = BackgroundScroller(
    #        self.driver,
    #        step_fraction=step_fraction,
    #        interval_ms=capture_interval_ms,
    #    )
    #    scroller.start()
    #    start = time.time()
#
    #    try:
    #        while time.time() - start < max_duration:
    #            time.sleep(capture_interval_ms / 1000.0)
    #            if self._use_js_engine:
    #                deltas = self._fetch_js_deltas()
    #                if deltas:
    #                    yield deltas
    #            else:
    #                # Legacy native-snapshot path; __init__ now forces
    #                # _use_js_engine=True so this branch is dead in
    #                # production. Guard with hasattr so tests that
    #                # monkeypatch _capture_unified still work and we
    #                # don't AttributeError otherwise.
    #                if not hasattr(self, "_capture_unified"):
    #                    continue
    #                try:
    #                    snapshot = self._capture_unified()
    #                    yield snapshot
    #                except Exception:
    #                    pass
    #    finally:
    #        scroller.stop()
#
    def _scroll(self, pause: float) -> None:
        """Progressive, viewport-sized scroll with a real stabilization wait.

        The legacy serializer did two things per iteration that together
        caused content to be skipped:

        1. A viewport-sized ``scrollBy`` (fine, this progressively
           reveals items and triggers intersection-observer lazy loads).
        2. A blind ``window.scrollTo(0, document.body.scrollHeight)``
           jump to the bottom (aggressive; it skips past whatever the
           page was about to render at intermediate positions and, on
           virtualized lists, can recycle off-screen items before we've
           captured them).

        We keep #1 and drop #2 *entirely*. No bottom-jump runs per
        iteration and none runs later either — the steady progressive
        scroll is the only advancement mechanism. Footer-only lazy
        loads are reached the same way: the progressive scroll will
        eventually arrive at the bottom on its own, and the
        ``_try_click_load_more`` probe handles the "Load more" case.

        We also replace the legacy ``performance.getEntries().length > 0``
        "network idle" check — which is effectively always true after
        initial load — with a real ``scrollHeight`` stabilization wait.

        **Adaptive timing**: If the DOM settled slowly on the previous
        iteration (≥ 75 % of SETTLE_TIMEOUT), the page is still loading
        content.  We repeat the same scroll position (holding it) instead of
        advancing, giving the lazy-loader another window to inject rows.
        After _ADAPTIVE_MAX_REPEATS consecutive holds without change the
        no_change_streak counter terminates the scan normally.
        """
        # Decide whether to advance the scroll position or hold it.
        _slow_threshold = self._ADAPTIVE_SLOW_THRESHOLD * self.SETTLE_TIMEOUT
        _hold = (
            self._last_settle_duration >= _slow_threshold
            and self._consecutive_slow_settles < self._ADAPTIVE_MAX_REPEATS
        )

        if not _hold:
            # 1. Bite-sized step, container-aware for custom feeds.
            self.driver.execute_script(
                """
                const frac = arguments[0];
                let container = document.querySelector('[data-testid="feedScrollView"]');
                if (container) {
                    container.scrollBy(0, Math.max(40, container.clientHeight * frac));
                } else {
                    window.scrollBy(0, Math.max(40, window.innerHeight * frac));
                }
                """,
                self.SCROLL_STEP_FRACTION,
            )
        else:
            logger.debug(
                "Adaptive hold: last settle %.2fs ≥ threshold %.2fs "
                "(slow streak=%d/%d), holding scroll position.",
                self._last_settle_duration,
                _slow_threshold,
                self._consecutive_slow_settles,
                self._ADAPTIVE_MAX_REPEATS,
            )

        # 2. Render-slack sleep, then measure settle time for adaptive logic.
        time.sleep(pause)
        _t0 = time.time()
        self._wait_for_dom_settled(timeout=self.SETTLE_TIMEOUT)
        self._last_settle_duration = time.time() - _t0

        # Update adaptive streak counter.
        if self._last_settle_duration >= _slow_threshold:
            self._consecutive_slow_settles += 1
        else:
            self._consecutive_slow_settles = 0

        # NOTE: pagination ("Load more" / "Show more" / "See more") is now
        # ONLY attempted at scan-end (after the scroll loop's no-change
        # limit fires). Clicking inside the per-iteration scroll was
        # firing on sites like YouTube where "Show more …" appears in
        # sidebar tooltips and recommendation menus, hijacking the scan
        # into Shorts/video-player content before the homepage feed had
        # even finished hydrating. See _try_click_load_more().

    def _try_click_load_more(self) -> bool:
        """Backward-compatible alias for the unified paginate() probe."""
        return self._paginate()

    # JS that ranks every plausible pagination control on the page, scoring
    # by signal strength (most specific match wins), then visibility, then
    # vertical position (controls near the bottom are usually the "Next"
    # button). Runs in a single execute_script so we make exactly one
    # round-trip instead of N XPath queries.
    _PAGINATE_RANK_JS = r"""
        (function() {
          var EXACT_NEXT_TEXTS = [
            'next', 'next page', 'next »', 'next >', 'next ›',
            'more', 'show more', 'load more', 'see more',
            'load more results', 'show more results', 'see more results',
            'older', 'older posts', 'newer', 'continue', 'continue reading'
          ];
          var ARROW_TEXTS = ['>', '›', '»', '→', '❯', '➤'];
          var CLASS_HINTS = [
            'pagination-next', 'rc-pagination-next', 'paginate-next',
            'next-page', 'load-more', 'loadmore', 'load_more',
            'show-more', 'showmore', 'show_more',
            'more-results', 'more_results', 'older-posts'
          ];

          function txt(el) {
            // .innerText respects display; we still strip whitespace.
            var t = (el.innerText || el.textContent || '').replace(/\s+/g, ' ').trim();
            return t;
          }
          function tokenize(s) {
            if (!s) return [];
            // Drop punctuation, keep letters/digits.
            return s.toLowerCase().split(/[^a-z0-9>›»→❯➤]+/).filter(Boolean);
          }
          function visible(el) {
            try {
              if (!el.isConnected) return false;
              var r = el.getBoundingClientRect();
              if (r.width < 6 || r.height < 6) return false;
              var cs = window.getComputedStyle(el);
              if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') return false;
              if (el.hasAttribute('aria-disabled') &&
                  el.getAttribute('aria-disabled').toLowerCase() === 'true') return false;
              if (el.hasAttribute('disabled')) return false;
              return true;
            } catch (e) { return false; }
          }

          // Score 1..5 — higher is more specific. 0 means reject.
          function scoreCandidate(el) {
            var tag = el.tagName.toLowerCase();
            // Only acceptable hosts: <button>, <a>, <li> (sites like
            // rc-pagination put the click target on the <li> itself
            // with an empty inner <a>).
            if (tag !== 'button' && tag !== 'a' && tag !== 'li') return 0;

            var t = txt(el);
            var tlow = t.toLowerCase();
            var title = (el.getAttribute('title') || '').toLowerCase();
            var aria  = (el.getAttribute('aria-label') || '').toLowerCase();
            var cls   = (el.className && typeof el.className === 'string'
                          ? el.className : '').toLowerCase();
            var tokens = tokenize(tlow);

            // (1) Explicit title="Next Page" / aria-label="Next page" — strongest.
            if (title === 'next page' || aria === 'next page' ||
                title === 'next' || aria === 'next' ||
                aria === 'load more' || title === 'load more' ||
                aria === 'show more' || title === 'show more') {
              return 5;
            }
            // (2) Class hints — typical pagination libraries set these.
            for (var i = 0; i < CLASS_HINTS.length; i++) {
              if (cls.indexOf(CLASS_HINTS[i]) >= 0) return 4;
            }
            // (3) Exact-text match against the canonical phrases.
            for (var i = 0; i < EXACT_NEXT_TEXTS.length; i++) {
              if (tlow === EXACT_NEXT_TEXTS[i]) return 3;
            }
            // (4) Arrow-only text. A single arrow character is almost
            //     always a Next-button — match the *normalised* form.
            if (ARROW_TEXTS.indexOf(t) >= 0) return 2;
            // (5) Soft match: 'more' or 'next' appears as one of the
            //     ≤3 tokens of the trimmed text. This catches localised
            //     phrasing like "More videos" / "Load 5 more". We
            //     deliberately cap at 3 tokens so we don't grab a
            //     <button>Read more about our cookies policy</button>.
            if (tokens.length > 0 && tokens.length <= 3) {
              if (tokens.indexOf('more') >= 0 || tokens.indexOf('next') >= 0 ||
                  tokens.indexOf('load') >= 0) {
                return 1;
              }
            }
            return 0;
          }

          var winH = window.innerHeight || 800;
          var pageH = (document.documentElement && document.documentElement.scrollHeight) || winH;
          // Probe every button/a/li in the DOM (rare elements; sub-1ms).
          // Shadow DOM walk is necessary for component-tree pages.
          var stack = [document.documentElement];
          var candidates = [];
          while (stack.length) {
            var n = stack.pop();
            if (!n || n.nodeType !== 1) continue;
            var t = n.tagName.toLowerCase();
            if (t === 'button' || t === 'a' || t === 'li') {
              var s = scoreCandidate(n);
              if (s > 0 && visible(n)) {
                var r = n.getBoundingClientRect();
                // Bonus for controls in the lower half of the page
                // (typical Next-button position). Capped at +0.5.
                var posBonus = Math.min(0.5, Math.max(0, (r.top / winH) * 0.5));
                candidates.push({
                  score: s + posBonus,
                  text: txt(n).slice(0, 60),
                  tag: t,
                  cls: (n.className && typeof n.className === 'string'
                          ? n.className.slice(0, 60) : ''),
                  title: n.getAttribute('title') || '',
                  aria: n.getAttribute('aria-label') || '',
                  // Use the element itself as the click target. If <li>
                  // wraps an empty <a>, we click the <li> — both end up
                  // dispatching the page event on the wrapper handler.
                  _el: n
                });
              }
            }
            if (n.shadowRoot) {
              for (var i = 0; i < n.shadowRoot.children.length; i++)
                stack.push(n.shadowRoot.children[i]);
            }
            for (var i = 0; i < n.children.length; i++) stack.push(n.children[i]);
          }
          candidates.sort(function(a, b) { return b.score - a.score; });
          // Stash the top winner so a follow-up driver.execute_script can
          // click it without re-finding. Strip _el from JSON return.
          window._wfhPaginateTop = candidates.length > 0 ? candidates[0]._el : null;
          return candidates.slice(0, 5).map(function(c) {
            return { score: c.score, text: c.text, tag: c.tag,
                     cls: c.cls, title: c.title, aria: c.aria };
          });
        })();
    """

    def _paginate(self) -> bool:
        """End-of-scroll pagination probe.

        Ranks every visible <button>/<a>/<li> in the document (and across
        shadow boundaries) by specificity:

            5  explicit title= / aria-label= "Next page", "Load more", etc.
            4  className contains 'pagination-next', 'load-more', etc.
            3  exact text = canonical phrase ('Next', 'Load more', …)
            2  text is a single arrow glyph (>, ›, », →, ❯, ➤)
            1  'more' / 'next' / 'load' is one of ≤3 tokens in the text

        Ties broken by vertical position (closer to bottom wins). The
        <li title="Next Page"> rc-pagination edge case scores 5 and
        clicks the wrapper <li> directly — its inner <a> is often empty.

        Returns True iff a click was dispatched.
        """
        try:
            ranked = self.driver.execute_script(
                self._js(self._PAGINATE_RANK_JS))
            self._hide_global("_wfhPaginateTop")
        except Exception as exc:
            logger.debug("[Scanner] _paginate ranking failed: %s", exc)
            return False
        # Defensive shape check — the JS *should* always return a list
        # of candidate dicts (or an empty list), but a fake driver in a
        # test harness or an unusual Selenium edge case can return
        # something else (int, str, None). Reject anything that isn't
        # a non-empty list of dict-like records rather than crashing
        # with the cryptic ``'int' object is not subscriptable`` at
        # ``ranked[0]``.
        if not isinstance(ranked, list) or not ranked:
            logger.info(
                "[Scanner] _paginate: no usable candidates (got %r).",
                type(ranked).__name__,
            )
            return False
        top = ranked[0]
        if not isinstance(top, dict):
            logger.info(
                "[Scanner] _paginate: top candidate is %r, not a dict; skipping.",
                type(top).__name__,
            )
            return False
        logger.info(
            "[Scanner] _paginate top candidate: score=%.2f tag=%s text=%r "
            "title=%r aria=%r class=%r (out of %d candidates)",
            top.get("score", 0), top.get("tag", "?"), top.get("text", ""),
            top.get("title", ""), top.get("aria", ""), top.get("cls", ""),
            len(ranked),
        )
        # Reject very weak matches — score 1 alone is too noisy
        # (could be a "Read more" cookie banner). Require score >= 2.
        if top.get("score", 0) < 2.0:
            logger.info(
                "[Scanner] _paginate: top score %.2f below threshold, skipping.",
                top.get("score", 0),
            )
            return False
        try:
            ok = self.driver.execute_script(self._js(
                "if (window._wfhPaginateTop) { "
                "  try { window._wfhPaginateTop.scrollIntoView({block:'center'}); } catch(e) {} "
                "  window._wfhPaginateTop.click(); "
                "  return true; "
                "} return false;"
            ))
            # The probe holds a live element reference. Keeping it past the
            # click pins a DOM node the page has moved on from, and leaves a
            # global whose value is "the thing that was clicked".
            self._drop_global("_wfhPaginateTop")
            if not ok:
                logger.info("[Scanner] _paginate: target element was missing.")
                return False
            self._wait_for_dom_settled(timeout=self.SETTLE_TIMEOUT)
            return True
        except Exception as exc:
            logger.debug("[Scanner] _paginate click failed: %s", exc)
            return False

    def _install_dom_observer(self) -> None:
        """Install the MutationObserver used by _wait_for_dom_settled.

        Idempotent — the JS guard ``if (window._wfhMO) return`` makes
        repeated calls on the same page a no-op.  Safe to call after every
        page navigation; the previous observer is garbage-collected with the
        old document.
        """
        try:
            self.driver.execute_script(self._js(INSTALL_OBSERVER_JS))
            for name in ("_wfhMO", "_wfhMOReady", "_wfhMOTimer"):
                self._hide_global(name)
        except Exception as exc:
            logger.debug(
                "MutationObserver install failed (%s); "
                "falling back to scrollHeight polling.",
                exc,
            )

    def _wait_for_dom_settled(self, timeout: float = 2.0) -> None:
        """Block until the MutationObserver signals the DOM is quiescent.

        The observer's 200 ms debounce timer resets on every childList
        mutation, so this resolves as soon as content injection stops —
        typically much faster than the old scrollHeight-stable approach.

        Falls back to ``_wait_for_scroll_height_stable`` if the observer is
        not available (e.g. page navigated before install, or JS disabled).
        """
        start = time.time()
        while time.time() - start < timeout:
            time.sleep(self.POLL_INTERVAL)
            try:
                if self.driver.execute_script(self._js(CHECK_OBSERVER_JS)):
                    return
            except Exception:
                # Observer unavailable — degrade gracefully.
                remaining = max(0.1, timeout - (time.time() - start))
                self._wait_for_scroll_height_stable(
                    timeout=remaining,
                    stable_for=self.SETTLE_STABLE_FOR,
                )
                return
        # Timeout: DOM still mutating (live feed / animation) — proceed.

    def _wait_for_scroll_height_stable(
        self,
        timeout: float = 2.0,
        stable_for: float = 0.25,
        poll_interval: float = None,
    ) -> None:
        """Fallback settler: block until scrollHeight stops growing.

        Used when the MutationObserver is unavailable.  Prefer
        ``_wait_for_dom_settled`` for the primary settle path.
        """
        poll_interval = (
            poll_interval if poll_interval is not None else self.POLL_INTERVAL
        )
        start = time.time()
        try:
            last_h = self.driver.execute_script(
                "return document.documentElement.scrollHeight"
            )
        except Exception:
            return
        last_change = time.time()
        while time.time() - start < timeout:
            time.sleep(poll_interval)
            try:
                h = self.driver.execute_script(
                    "return document.documentElement.scrollHeight"
                )
            except Exception:
                return
            if h != last_h:
                last_h = h
                last_change = time.time()
                continue
            if time.time() - last_change >= stable_for:
                return
