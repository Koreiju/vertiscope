"""Drive the in-page sensor and turn its deltas into the store's vocabulary.

`sensor.js` maintains the fold in the page and emits, per drain, only the
chunks whose digest changed. This module is the whole Python side of that
path: boot the sensor, drain it, and translate integer-interned paths into the
`ContentAddress` / `MarkdownChunk` values the store, retrieval and REPL
already speak.

Deliberately thin. Nothing here re-parses, re-tags, re-chunks or re-derives an
xpath — those are the sensor's outputs, and recomputing them on this side is
how a second pipeline starts.
"""

from __future__ import annotations

import json
import pathlib
import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .address import ContentAddress
from .markdown import MarkdownChunk, MarkdownLine

_JS = (pathlib.Path(__file__).parent / "core" / "js" / "sensor.js")

__all__ = ["Sensor", "SensePass", "ScrollStep"]

# The composed-tree boundary marker, spelled identically on both sides.
_SHADOW = "#shadow-root"
# The `idanchor` marker, spelled identically on both sides.
_ID = "#id"

# A tag name usable as an XPath name test. Real pages routinely contain
# elements the parser named from malformed markup — `<ahref="/x">` with the
# space missing becomes an element whose tagName *is* `AHREF="/x`, and no
# name test can spell that.
_QNAME = re.compile(r"^[A-Za-z_][\w.\-]*$")
_UPPER = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"
_LOWER = "abcdefghijklmnopqrstuvwxyz"


def _name_test(tag: str, ordinal: int) -> str:
    """One xpath step that selects `tag`, whatever the tag is called.

    Well-formed names use the ordinary form. Anything else is selected by
    predicate on ``name()``, which is legal for any string — degrading to a
    bare ``*`` only when the name contains both quote characters and so
    cannot be written as an XPath 1.0 literal at all.
    """
    if _QNAME.match(tag):
        return f"{tag}[{ordinal}]" if ordinal > 1 else tag
    # Case-folded, because a name the HTML parser never normalised can come
    # back from `name()` in either case depending on the engine, and this
    # path only runs for malformed markup where verbosity costs nothing.
    fold = f"translate(name(),'{_UPPER}','{_LOWER}')"
    if "'" not in tag:
        test = f"*[{fold}='{tag}']"
    elif '"' not in tag:
        test = f'*[{fold}="{tag}"]'
    else:
        test = "*"
    return f"{test}[{ordinal}]"


@dataclass
class SensePass:
    """One drain: what changed, and what each stage of handling it cost."""

    passno: int
    # (ContentAddress, value) in document order — what the trie is fed. The
    # sensor no longer hands over rendered chunks; the renderer partitions.
    units: List[tuple] = field(default_factory=list)
    removed: List[int] = field(default_factory=list)
    # Addresses that left the composed tree, resolved from the sensor's own
    # chunk ids. The store is keyed by address, not by the sensor's grouping.
    removed_addresses: List[ContentAddress] = field(default_factory=list)
    addresses: int = 0
    lines: int = 0
    settled: bool = False
    stats: dict = field(default_factory=dict)
    wire_bytes: int = 0        # what this delta cost to carry, measured
    contents: List[str] = field(default_factory=list)   # content fingerprints

    # timings, in the order the work happens
    scroll_ms: float = 0.0
    drain_ms: float = 0.0      # the round trip, including in-page repair
    decode_ms: float = 0.0     # payload -> chunks + addresses
    store_ms: float = 0.0      # persistence of this delta
    repl_ms: float = 0.0       # applying this delta to the open document

    @property
    def total_ms(self) -> float:
        return (self.scroll_ms + self.drain_ms + self.decode_ms
                + self.store_ms + self.repl_ms)

    @property
    def changed(self) -> int:
        return len(self.units)


@dataclass
class ScrollStep:
    """What one discrete scroll did, including any pager it enacted."""

    scrolled: int = 0          # pixels actually moved
    delta: int = 0             # chunks the *previous* step produced
    fired: List[tuple] = field(default_factory=list)   # (tag, label, kind)
    skipped: int = 0           # in view but not pressed, with reason held
    pagers: int = 0            # pagination controls still attached
    bottom: bool = False       # the scroll can go no further
    exhausted: bool = False    # two consecutive empty deltas
    errors: int = 0
    step_ms: float = 0.0
    # Why a detected pager was not pressed, one count per gate.
    gates: Dict[str, int] = field(default_factory=dict)


class Sensor:
    """A booted in-page sensor for one driver."""

    def __init__(self, driver, url: str, *, budget: int = 1200,
                 debounce: int = 80, handle: Optional[str] = None,
                 variants: Optional[Dict[str, bool]] = None,
                 known: Optional[List[str]] = None):
        self.driver = driver
        self.url = url
        self.budget = budget
        self.variants = variants or {}
        # Content fingerprints the receiver already holds. The `crosspage`
        # axis gates emission on these, which is the original serializer's
        # `known_hashes` prune moved to the side of the boundary where it
        # saves the crossing instead of the storage.
        self.known = list(known or [])
        # A per-session random name, non-enumerable, holding only functions.
        # Nothing about it is guessable from the page and nothing is written
        # into the document itself.
        self.handle = handle or ("__s" + format(abs(hash((url, time.time())))
                                                % 0xFFFFFFFF, "x"))
        self._dict: List[str] = []
        self._shapes: List[List[int]] = []
        # sensor chunk id -> the addresses last seen under it. The sensor
        # names removals by its own grouping; the trie is keyed by address,
        # so the mapping has to be held on this side to translate one to the
        # other. Without it a departed node's address stayed in the trie and
        # went on rendering after the element was gone.
        self._chunk_addrs: Dict[int, List[ContentAddress]] = {}
        self.boot_ms = 0.0
        self.reboots = 0
        self.steps = 0
        self.enacted = 0

    # -- lifecycle --------------------------------------------------------
    def boot(self) -> float:
        source = _JS.read_text(encoding="utf-8")
        script = (
            "var h = (" + source + ")(arguments[0]);"
            "Object.defineProperty(window, '" + self.handle + "', "
            "{value: h, enumerable: false, configurable: true});"
            "return typeof window." + self.handle + ".drain === 'function';"
        )
        started = time.perf_counter()
        ok = self.driver.execute_script(
            script, {"budget": self.budget, "debounce": 80,
                     "variants": self.variants, "known": self.known})
        self.boot_ms = (time.perf_counter() - started) * 1000
        if not ok:
            raise RuntimeError("sensor did not install a drain handle")
        return self.boot_ms

    def _call(self, method: str, *args):
        """Invoke one of the handle's functions, re-booting if it is gone.

        Every call across this boundary needs the same recovery, because
        every one of them can be the first to notice the realm went away. It
        lived only in `drain` until the scroller started enacting pagers that
        navigate — then `step` was the call that hit the dead handle first,
        and having no recovery of its own it threw on every step thereafter.
        """
        script = ("return window['" + self.handle + "']." + method
                  + "(" + ("arguments[0]" if args else "") + ");")
        try:
            return self.driver.execute_script(script, *args)
        except Exception:  # noqa: BLE001
            # The injection is gone. A navigation destroys it — a redirect
            # after load, a meta refresh, an enacted pager, or an SPA route
            # change that swaps documentElement — and the handle vanishes
            # with the realm that held it.
            #
            # The URL is re-read first, because a re-boot is *caused by* the
            # document becoming a different document, and the address is
            # exactly the thing most likely to have changed. Keeping the old
            # one filed the new page's chunks under the previous page's URL.
            #
            # The new sensor starts from an empty fold, so the first drain
            # after a re-boot is a cold description of the *current*
            # document, which is the correct reading of a page that has
            # become a different page. `reboots` counts them, because a page
            # that re-boots every pass is telling us something about itself
            # that a silent recovery would hide.
            self.url = self._current_url() or self.url
            self.boot()
            self._dict = []
            self._shapes = []
            self.reboots += 1
            return self.driver.execute_script(script, *args)

    def _current_url(self) -> str:
        try:
            return self.driver.current_url or ""
        except Exception:  # noqa: BLE001 - a driver without one is fine
            return ""

    def alive(self) -> bool:
        return bool(self.driver.execute_script(
            "return !!(window['" + self.handle + "'] && "
            "typeof window['" + self.handle + "'].drain === 'function');"))

    # -- the one round trip ----------------------------------------------
    def drain(self, passno: int = 0) -> SensePass:
        started = time.perf_counter()
        payload = self._call("drain") or {}
        drain_ms = (time.perf_counter() - started) * 1000
        return self._as_pass(payload, drain_ms, 0.0, passno)

    def _as_pass(self, payload: dict, drain_ms: float, step_ms: float = 0.0,
                 passno: int = 0) -> SensePass:
        """One payload -> one SensePass. Shared by `drain` and `fused`, so
        the two cannot drift into decoding the same bytes differently."""
        # The page states its own address in the payload. A route change that
        # rewrites it without reloading leaves the handle intact, so nothing
        # would otherwise notice, and the chunks would go on being filed
        # under wherever the session happened to start.
        here = str(payload.get("url") or "")
        if here and here != self.url:
            self.url = here

        started = time.perf_counter()
        # What this delta actually cost to carry. Measured here rather than
        # estimated, because the transport axis (interned segments vs raw
        # strings) is only comparable against a real number.
        try:
            wire = len(json.dumps(payload, separators=(",", ":")))
        except (TypeError, ValueError):
            wire = 0
        # The dictionary is append-only, so a payload carries only entries
        # added since the last drain and the receiver never needs prior state
        # beyond its own length.
        self._dict.extend(payload.get("dict") or [])
        self._shapes.extend(payload.get("shapes") or [])
        contents = [str(c.get("content")) for c in (payload.get("chunks") or [])
                    if c.get("content") is not None]
        units, by_chunk, lines = self._decode(
            payload.get("chunks") or [],
            (payload.get("stats") or {}).get("variants") or {})
        # A chunk the sensor now reports is the authority on what it holds;
        # anything it held on an earlier pass and no longer emits has left the
        # composed tree and must leave the trie too.
        gone: List[ContentAddress] = []
        for cid, addrs in by_chunk.items():
            previous = self._chunk_addrs.get(cid)
            if previous:
                fresh = {a.key() for a in addrs}
                gone.extend(a for a in previous if a.key() not in fresh)
            self._chunk_addrs[cid] = addrs
        for cid in payload.get("removed") or []:
            gone.extend(self._chunk_addrs.pop(int(cid), []))
        decode_ms = (time.perf_counter() - started) * 1000

        return SensePass(
            passno=passno,
            units=units,
            removed=list(payload.get("removed") or []),
            removed_addresses=gone,
            addresses=len(units),
            lines=lines,
            settled=bool(payload.get("settled")),
            stats=payload.get("stats") or {},
            drain_ms=drain_ms,
            decode_ms=decode_ms,
            scroll_ms=step_ms,
            wire_bytes=wire,
            contents=contents,
        )

    # -- decoding ---------------------------------------------------------
    def _seg(self, ident) -> str:
        # With the interning axis off the segment arrives as itself, so the
        # receiver holds no dictionary and this side needs no other change.
        if isinstance(ident, str):
            return ident
        return self._dict[ident] if 0 <= ident < len(self._dict) else "?"

    def _xpath(self, path: List[int]) -> str:
        """Interned [tagId, ordinal, ...] -> an absolute composed-tree xpath.

        Three spellings matter, because these addresses are not decoration:
        the REPL resolves them to enact a control (OBJECT_MODEL §7.8), so an
        address that no engine can evaluate is a dead address.

        * The fold starts at ``documentElement``, so the accumulated path is
          relative to ``<html>`` and the root step has to be restored here.
        * A text child is ``text()[n]``. ``#text[n]`` is not a legal step and
          made every text address unevaluable.
        * A shadow boundary stays ``#shadow-root`` — deliberately *not* legal
          XPath, because no XPath crosses a shadow boundary. Such an address
          is resolvable only through the sensor, which is where resolution of
          shadow content belongs anyway.
        """
        out = ["html"]
        for i in range(0, len(path) - 1, 2):
            tag = self._seg(path[i])
            ordinal = path[i + 1]
            if tag == _ID:
                # `idanchor` re-roots the address at an id, so the absolute
                # prefix is not merely unnecessary — it is wrong. Everything
                # accumulated so far is discarded and the path restarts from
                # the anchor, which is what makes it survive an insertion
                # above it.
                out = [f"/*[@id={self._seg(ordinal)!r}]".replace("'", "'")]
                continue
            if tag == _SHADOW:
                out.append(_SHADOW)
            elif tag == "#text":
                out.append(f"text()[{ordinal}]")
            else:
                out.append(_name_test(tag, ordinal))
        return "/" + "/".join(out)

    def _paths(self, lines: List[list], flags: dict) -> None:
        """Undo the transport encodings, in the reverse of the order applied.

        Driven by what the payload *reports* ran, never by what was asked
        for: `shape` disables `pathdelta` in the page, and a decoder that
        trusted the request would silently mis-read every path — which reads
        as a page whose addresses have all moved, not as a decoding bug.
        """
        packed = bool(flags.get("packed"))
        shaped = bool(flags.get("shape"))
        delta = bool(flags.get("pathdelta"))
        # `valdict` rides on the same dictionary as the path segments, so it
        # does nothing when `intern` is off — the page hands back the string
        # itself and `_seg` passes it through. Reported rather than hidden:
        # a variant that silently no-ops is a variant that looks free.
        vals = bool(flags.get("valdict"))
        if vals:
            for line in lines:
                if not isinstance(line[1], str):
                    line[1] = self._seg(line[1])
        # `textdict` sends prose as a run of word ids behind a -1 marker.
        # Without this the line would arrive as the repr of a list, which is
        # not a decoding bug that announces itself — it is a page whose text
        # silently became "[3, 91, 12]".
        if flags.get("textdict"):
            for line in lines:
                v = line[1]
                if isinstance(v, list) and v and v[0] == -1:
                    line[1] = " ".join(self._seg(w) for w in v[1:])
        if not (packed or shaped or delta):
            return
        prev: List[int] = []
        for line in lines:
            path = line[2]
            if packed and isinstance(path, str):
                path = [int(t) for t in path.split(",")] if path else []
            if shaped:
                # [shapeId, ord, ord, ...] -> [tag, ord, tag, ord, ...]
                shape = (self._shapes[path[0]]
                         if path and 0 <= path[0] < len(self._shapes) else [])
                out: List[int] = []
                for i, tag in enumerate(shape):
                    out.append(tag)
                    out.append(path[i + 1] if i + 1 < len(path) else 1)
                path = out
            elif delta:
                keep = path[0] if path else 0
                path = list(prev[:keep]) + list(path[1:])
                prev = path
            line[2] = path

    def _decode(self, raw: List[dict], flags: Optional[dict] = None):
        """Sensor payload -> addressed units, in document order.

        Returns ``(units, by_chunk)``: the flat ``(address, value)`` sequence
        the trie is fed, and the map from the sensor's own chunk id to the
        addresses that came out of it — which is what lets a removal named by
        chunk id be turned into the address-level removals the trie needs.

        This used to assemble :class:`MarkdownChunk` here, which made the
        sensor's chunk grouping authoritative and bypassed the trie and
        ``render_trie`` entirely. The grouping is now the renderer's, so both
        paths partition the same way; the sensor still supplies every fact it
        always did, because each line already carries its own xpath, taxonomy
        and detecting rule.
        """
        flags = flags or {}
        units: List[tuple] = []
        by_chunk: Dict[int, List[ContentAddress]] = {}
        total_lines = 0
        for entry in raw:
            self._paths(entry.get("lines") or [], flags)
            cid = int(entry.get("id", 0))
            mine = by_chunk.setdefault(cid, [])
            for line in entry.get("lines") or []:
                depth, text, path, attr, seq = line[:5]
                if not text:
                    continue
                # §1: …/abs-xpath/@taxonomy/@regex-addr. The tag carries the
                # taxonomy — which markdown field this becomes — and the
                # accessor carries the rule that detected it, so provenance
                # from DOM node to rendered line to matching rule is readable
                # from the address alone.
                taxonomy = self._seg(line[5]) if len(line) > 5 else "paragraph"
                rule = self._seg(line[6]) if len(line) > 6 else "text.visible"
                # `attr >= 0`, not truthiness: id 0 is a real interned name.
                accessor = (self._seg(attr) if isinstance(attr, str)
                            or (attr is not None and attr >= 0)
                            else f"text()[{seq}]")
                address = ContentAddress(
                    self.url, self._xpath(path),
                    taxonomy, f"{accessor}|{rule}")
                units.append((address, str(text)))
                mine.append(address)
                total_lines += 1
        return units, by_chunk, total_lines

    # -- driving ----------------------------------------------------------
    def step(self, pixels: int = 0) -> "ScrollStep":
        """One discrete scroll, with pagination folded in (OBJECT_MODEL 5).

        Scrolling and pagination are one loop, and the loop lives in the page:
        the scroll, the decision about which controls are on screen, and the
        clicks all happen inside a single `execute_script`. Doing it from here
        would mean one round trip to scroll, another to look for controls, and
        one per click — and the round trip costs 5-11 ms regardless of what it
        carries, so a chatty scroller is slower than the page it is reading.
        """
        started = time.perf_counter()
        raw = self._call("step", int(pixels)) or {}
        elapsed = (time.perf_counter() - started) * 1000
        self.steps += 1
        return self._as_step(raw, elapsed)

    def _as_step(self, raw: dict, elapsed: float) -> ScrollStep:
        fired = [tuple(f) for f in (raw.get("fired") or [])]
        self.enacted += len(fired)
        return ScrollStep(
            scrolled=int(raw.get("scrolled") or 0),
            delta=int(raw.get("delta") or 0),
            fired=fired,
            skipped=int(raw.get("skipped") or 0),
            pagers=int(raw.get("pagers") or 0),
            bottom=bool(raw.get("bottom")),
            exhausted=bool(raw.get("exhausted")),
            errors=int(raw.get("errors") or 0),
            step_ms=elapsed,
            gates={k[3:]: int(raw.get(k) or 0) for k in raw
                   if k.startswith("sk_")}
            | {"seen": int(raw.get("seen_pagers") or 0)},
        )

    def fused(self, pixels: int = 0):
        """One round trip that both scrolls and drains.

        `step` then `drain` is two crossings of a boundary that costs the
        same whatever it carries. Returns the same pair the two calls would
        have, so callers can switch on the axis and nothing else changes.
        """
        started = time.perf_counter()
        raw = self._call("pass", int(pixels)) or [None, None]
        elapsed = (time.perf_counter() - started) * 1000
        rawstep, payload = (raw + [None, None])[:2]
        self.steps += 1
        return (self._as_step(rawstep or {}, elapsed),
                self._as_pass(payload or {}, elapsed, 0.0))

    def scroll(self) -> float:
        """Back-compat: one step, reported as milliseconds."""
        return self.step().step_ms
