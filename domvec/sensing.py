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
from typing import Dict, List, Optional, Tuple

from .address import ContentAddress
from .markdown import MarkdownChunk, MarkdownLine
from .privacy import redact_url
from .trie import content_hash

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
    # (old address -> new address) for chunks whose content is unchanged
    # and whose position moved. The values are not on the wire: the trie
    # holds them, so `StreamingScan.absorb` rebuilds the units from its
    # own store rather than from a payload that re-sent what it had.
    moved_addresses: List[Tuple[ContentAddress, ContentAddress]] = field(
        default_factory=list)
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
    fired: List[tuple] = field(default_factory=list)   # always empty now
    # Controls that came into view, reported for a reader to act on. The
    # scroller no longer presses anything: choosing which control to press
    # was ours to get wrong, and it did -- 37 false positives on one YouTube
    # results page, reaching for "Sign in". What is left is the observation.
    offered: List[tuple] = field(default_factory=list)  # (tag, label, kind)
    skipped: int = 0           # in view but not pressed, with reason held
    pagers: int = 0            # pagination controls still attached
    bottom: bool = False       # the scroll can go no further
    exhausted: bool = False    # two consecutive empty deltas
    errors: int = 0
    step_ms: float = 0.0
    # Why a detected pager was not pressed, one count per gate.
    gates: Dict[str, int] = field(default_factory=dict)




def _step_tag(step: str) -> str:
    """A path step without its sibling ordinal: ``li[3]`` -> ``li``."""
    cut = step.find("[")
    return step if cut < 0 else step[:cut]


#: Planted: a move is accepted only as a one-step re-index (a re-parented
#: chunk -- slot reassignment -- keeps its old addresses).
_PLANT_ONE_STEP_MOVES = [False]


def _shifted_xpath(xpath: str, new_root: str) -> Optional[str]:
    """``xpath`` re-addressed for the node at ``new_root``, or None.

    A move is the re-indexing of exactly one step: a node keeps its content,
    its parent and its tag, and takes a different ordinal among its siblings.
    Everything addressed inside it keeps its whole path below that step. So
    the rebuild is a prefix substitution at the depth of the moved node --
    and None wherever the address is not, in fact, inside it.

    Two defects lived in the previous form of this, both invisible to the
    flat-list fixture and both obvious on the first real page:

    * It took the old root from the *common prefix* of the chunk's addresses,
      cut back to the last "/" unconditionally. That is right when the shared
      prefix stops mid-step ("li[1]" against "li[12]") and wrong when it is
      already a whole step, which is what happens whenever a chunk has a unit
      addressed at its own root -- an href or an aria-label on the element
      itself. The root came out a step too shallow and every rebuilt address
      gained a spurious step. quotes.toscrape.com went from 176 leaves to 317
      on one inserted node, and every sampled new path matched zero nodes.
    * The move entry names the node that moved; a chunk's addresses hang off
      whatever is inside it. On books.toscrape.com the entry named the `li`
      and the addresses hung off the `article` within, so substituting one
      root for the other dropped the `article` step: 60 of 60 sampled paths
      matched nothing.

    Depth is what actually holds, and the guards below are what keep it
    honest -- without them an address in a different branch of the document
    would be rewritten onto the moved node, because a root derived from the
    address is always a prefix of it and `startswith` can never fail.
    """
    depth = new_root.count("/")
    steps = xpath.split("/")
    if len(steps) <= depth:
        return None                     # shallower than the node that moved
    old_root = "/".join(steps[:depth + 1])
    if not old_root or old_root == new_root:
        return None
    old_steps = old_root.split("/")
    new_steps = new_root.split("/")
    if len(old_steps) != len(new_steps):
        return None
    # Exactly one step differs, and it names the same element.
    #
    # This used to insist the differing step was the *last* one, which
    # quietly assumed the node that moved is the one whose ordinal changed.
    # It usually is not: when a block shifts, the ordinal that changes is on
    # an ancestor -- `.../section[3]/ul` becomes `.../section[4]/ul` -- and
    # the rest of the path rides along unchanged. Insisting on the last step
    # rejected those as "a different branch of the document", and rejected
    # nearly all of them: 560 of 560 addresses on slashdot.org and 1,598 of
    # 1,625 on theguardian.com, so the fold reported 160 and 596 moved chunks
    # and the receiver was handed 0 and 27. Everything downstream then held
    # the old addresses with the old content, which is where the wrong values
    # come from.
    #
    # One differing step is still the whole claim -- a move re-indexes one
    # element -- and the tag check still refuses a path that lands somewhere
    # genuinely else.
    differ = [i for i in range(len(old_steps))
              if old_steps[i] != new_steps[i]]
    if len(differ) != 1:
        return None
    at = differ[0]
    if _step_tag(old_steps[at]) != _step_tag(new_steps[at]):
        return None                     # not one element re-indexed
    return new_root + xpath[len(old_root):]


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
        # A per-session name holding only functions. Nothing is written into
        # the document itself -- that part was and remains true.
        #
        # What was NOT true, and was asserted here for a long time, is that
        # the page cannot find it. `enumerable: false` hides a property from
        # `for...in` and `Object.keys`; it is still an own property of
        # `window` and `Object.getOwnPropertyNames(window)` lists it. The
        # fixed `__s` prefix made it worse than merely findable -- one regex
        # isolated it -- so the prefix is gone and the name is drawn from
        # shapes that occur on ordinary pages. That raises the cost of
        # finding it from a regex to a diff against a clean profile. It does
        # not make it unfindable, and claiming otherwise is what this comment
        # is replacing.
        self.handle = handle or self._plausible_name(url)
        self._dict: List[str] = []
        self._shapes: List[List[int]] = []
        # sensor chunk id -> the addresses last seen under it. The sensor
        # names removals by its own grouping; the trie is keyed by address,
        # so the mapping has to be held on this side to translate one to the
        # other. Without it a departed node's address stayed in the trie and
        # went on rendering after the element was gone.
        self._chunk_addrs: Dict[int, List[Tuple[ContentAddress, str]]] = {}
        self.boot_ms = 0.0
        self.reboots = 0
        self.steps = 0
        self.enacted = 0

    @staticmethod
    def _plausible_name(url: str) -> str:
        """A property name that does not announce itself.

        Deliberately drawn from the shapes real libraries leave on `window`
        rather than from randomness alone: a page cannot tell `_k3f9a2` from
        the hundred other globals a modern site installs, whereas `__s` plus
        hex was a signature.
        """
        import random

        seed = random.Random(f"{url}{time.time()}")
        lead = seed.choice(("_", "__", ""))
        stem = seed.choice(("k", "q", "z", "n", "r", "v", "b", "j"))
        return f"{lead}{stem}{seed.randrange(0x100000, 0xFFFFFF):x}"

    # -- lifecycle --------------------------------------------------------
    def boot(self) -> float:
        source = _JS.read_text(encoding="utf-8")
        script = (
            "var h = (" + source + ")(arguments[0]);"
            # `configurable: false`: a page that finds the handle could
            # otherwise `delete` it and silently stop the fold, which reads
            # as the sensor breaking rather than as the page defending
            # itself.
            "Object.defineProperty(window, '" + self.handle + "', "
            "{value: h, enumerable: false, configurable: false});"
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

    # The address a page is filed under, and the one place it is decided.
    #
    # A url reaches this object four ways -- the constructor, a re-boot after
    # the document was replaced, the page stating its own address in a
    # payload, and a gesture that navigated -- and every one of them is a url
    # the browser hands over whole, session tokens and campaign tags
    # included. Whatever is set here becomes the url on every address the
    # sensor emits, so it is the last point before the store where a
    # credential can be turned away. A plain attribute would have needed the
    # same call written four times and correct in all four.
    @property
    def url(self) -> str:
        return self._url

    @url.setter
    def url(self, value: str) -> None:
        self._url = redact_url(value or "")

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
        flags = (payload.get("stats") or {}).get("variants") or {}
        units, by_chunk, lines = self._decode(
            payload.get("chunks") or [], flags)
        # A chunk the sensor now reports is the authority on what it holds;
        # anything it held on an earlier pass and no longer emits has left the
        # composed tree and must leave the trie too.
        gone: List[ContentAddress] = []
        for cid, addrs in by_chunk.items():
            previous = self._chunk_addrs.get(cid)
            if previous:
                fresh = {a.key() for a, _h in addrs}
                # A chunk's fresh address set is authoritative for that chunk:
                # those are the addresses it has now, so one it emitted last
                # time and does not emit this time is gone.
                #
                # This used to spare an address whose *content* reappeared
                # elsewhere in the chunk, because comparing address sets alone
                # once manufactured N phantom removals for one node arriving --
                # 400 on a 400-item list -- which the trie applied, destroying
                # 399 identities the re-anchor had just preserved.
                #
                # Two things have since made that guard unnecessary, and it is
                # measurably harmful without them. A shift within a chunk now
                # travels as a *move* rather than a re-emission, so the
                # 400-item case reports 400 moves and no removals at all, with
                # or without the guard. And `AddressTrie.apply` skips any
                # removal this same drain contradicts, which is the same
                # protection stated where the write happens.
                #
                # What the guard cost: on a re-emitted chunk whose addresses
                # shifted, every departed address was spared and the trie kept
                # it. doc.rust-lang.org held 54 stale addresses against a page
                # with 81, info.cern.ch 30 against 81, noaa.gov 28. Removing
                # it takes all three to zero, loses nothing and destroys no
                # identity.
                gone.extend(a for a, _h in previous if a.key() not in fresh)
            self._chunk_addrs[cid] = addrs
        for cid in payload.get("removed") or []:
            gone.extend(a for a, _h in self._chunk_addrs.pop(int(cid), []))

        # Chunks that moved without changing. The fold sent the new root path
        # and nothing else, because the receiver already holds every line of
        # an unchanged chunk; what it does not hold is where they went.
        #
        # The old addresses are the ones this chunk emitted last time, and
        # they all share the chunk's old root as a prefix, so the shift is one
        # prefix substitution applied across them. Rebuilding the addresses
        # here keeps `_chunk_addrs` true for the next pass, which is what the
        # removal comparison above is judged against.
        moved: List[Tuple[ContentAddress, ContentAddress]] = []
        for entry in payload.get("moves") or []:
            try:
                cid, raw_path = int(entry[0]), entry[1]
            except (TypeError, ValueError, IndexError):
                continue
            known = self._chunk_addrs.get(cid)
            if not known:
                continue
            self._paths([[0, "", list(raw_path), -1, 0]], flags)
            new_root = self._xpath(list(raw_path))
            if not new_root:
                continue
            rebuilt: List[Tuple[ContentAddress, str]] = []
            # A RE-PARENTED chunk (a slot reassignment: `main/slot/section`
            # drawn under `header/slot/section`) changes an ancestor's TAG,
            # which the one-step re-index rule refuses -- and the trie kept the
            # old addresses of a block the page drew elsewhere
            # (test_a_large_moved_subtree_is_re_addressed, 2026-10-18). When
            # every address this chunk holds shares ONE root at the move's
            # depth, and that root names the same element as the new one, the
            # chunk's own addresses define where it was: the whole root is
            # substituted. Planted `_PLANT_ONE_STEP_MOVES`: refused, as before.
            depth = new_root.count("/")
            roots = {"/".join(a.xpath.split("/")[:depth + 1]) for a, _d in known
                     if len(a.xpath.split("/")) > depth}
            whole = None
            if (not _PLANT_ONE_STEP_MOVES[0] and len(roots) == 1
                    and all(len(a.xpath.split("/")) > depth for a, _d in known)):
                old_root = next(iter(roots))
                tag = lambda step: step.split("[")[0]
                if old_root != new_root and tag(old_root.split("/")[-1]) == tag(new_root.split("/")[-1]):
                    whole = old_root
            for address, digest in known:
                if whole is not None:
                    moved_to = new_root + address.xpath[len(whole):]
                else:
                    moved_to = _shifted_xpath(address.xpath, new_root)
                if moved_to is None:
                    rebuilt.append((address, digest))
                    continue
                shifted = ContentAddress(address.url, moved_to,
                                         address.tag, address.accessor)
                moved.append((address, shifted))
                rebuilt.append((shifted, digest))
            self._chunk_addrs[cid] = rebuilt

        # A move's source that nothing else claims no longer holds anything.
        #
        # When a shift moves content out of an address, the receiver is told
        # where it went and nothing about what the address holds now. Where
        # some other chunk moved *into* it, the drain says so. Where nothing
        # did, the address is vacated -- and that is what the page agrees
        # with: on five corpus pages this takes staleness to zero and loses
        # nothing.
        #
        # This rule was written twice before and withdrawn twice, and both
        # refutations used the wrong oracle. The first checked the vacated
        # paths with `document.evaluate` and found them "still present" -- but
        # an unindexed XPath step matches *all* siblings and the trie writes
        # the first of a group without an index, so it was answering about
        # twenty nodes rather than one. The second asked the fold whether a
        # node still existed at the path, which is a different question again:
        # a node can exist without the fold emitting any unit at that address,
        # and it is the unit that the map is made of.
        #
        # The oracle that settles it is a fresh map of the page -- a second
        # sensor walked whole -- and against that, vacating is exactly right.
        #
        # It is also only *safe* now. Until moves were being delivered
        # correctly, orphaned sources included addresses whose moves had been
        # wrongly discarded, and vacating those did lose content. Correct
        # delivery had to come first; the rule was never the problem.
        if moved:
            claimed = {a.key() for a, _v in units}
            claimed.update(n.key() for _o, n in moved)
            orphans = [old_address for old_address, _new in moved
                       if old_address.key() not in claimed]
            gone.extend(orphans)
        decode_ms = (time.perf_counter() - started) * 1000

        return SensePass(
            passno=passno,
            units=units,
            removed=list(payload.get("removed") or []),
            removed_addresses=gone,
            moved_addresses=moved,
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
                # The value's digest travels with the address, because
                # "no longer emitted at this address" and "gone" are
                # different facts and only the second is a removal.
                mine.append((address, content_hash(str(text))))
                total_lines += 1
        return units, by_chunk, total_lines

    # -- enactment --------------------------------------------------------
    @staticmethod
    def path_of(address) -> List:
        """A ContentAddress's xpath as the [tag, ordinal, ...] the page reads.

        The same encoding the fold emits, run backwards. Nothing is
        reconstructed by guessing: an address that came out of the sensor
        resolves to the node it came from, including across shadow
        boundaries, because `#shadow-root` is a step on both sides.
        """
        out: List = []
        xpath = address.xpath if hasattr(address, "xpath") else str(address)
        for raw in xpath.split("/"):
            if not raw:
                continue
            if raw == _SHADOW:
                out.extend([_SHADOW, 1])
                continue
            label, ordinal = raw, 1
            if raw.endswith("]") and "[" in raw:
                label, _, rest = raw.partition("[")
                try:
                    ordinal = int(rest[:-1])
                except ValueError:
                    ordinal = 1
            if label.startswith("text()"):
                label = "#text"
            out.extend([label, ordinal])
        return out

    def perform(self, ticks: List[dict]) -> dict:
        """Run one action chain in the page.

        The whole chain crosses in a single call. Sending a tick at a time
        would pay the round-trip toll -- 1.46 ms measured here, against
        0.05-0.25 ms of actual work -- once per tick, so a three-tick gesture
        would cost more in crossings than in everything it does.

        Returns as soon as the last tick is dispatched. There is no wait for
        the page to settle, because there is no settling: the listeners are
        sensors that assume no terminal state, and whatever the gesture
        causes arrives on the same delta stream as everything the page does
        on its own. The caller drains when it wants to look.
        """
        raw = self._call("perform", {"ticks": ticks}) or {}
        if raw.get("url"):
            self.url = raw["url"]
        return {
            "done": list(raw.get("done") or []),
            "failed": [tuple(f) for f in (raw.get("failed") or [])],
            "url": raw.get("url") or "",
        }

    # The gestures a reader has, each one chain. Named for what the reader
    # does, not for what the control is presumed to be: `press` is the same
    # gesture whether the thing pressed turns out to be a pager, a filter or
    # a disclosure, and that is the point.
    def press(self, address) -> dict:
        return self.perform([{"kind": "click", "path": self.path_of(address)}])

    def fill(self, address, text: str, *, submit: bool = False) -> dict:
        path = self.path_of(address)
        ticks = [{"kind": "type", "path": path, "text": text}]
        if submit:
            ticks.append({"kind": "key", "path": path, "text": "Enter"})
            ticks.append({"kind": "submit", "path": path})
        return self.perform(ticks)

    def toggle(self, address) -> dict:
        return self.perform([{"kind": "check", "path": self.path_of(address)}])

    def choose(self, address, option: str) -> dict:
        return self.perform([{"kind": "choose", "path": self.path_of(address),
                              "text": option}])

    def hover(self, address) -> dict:
        return self.perform([{"kind": "hover", "path": self.path_of(address)}])

    def styles(self, addresses) -> dict:
        """Geometry and emphasis for a set of addresses, in one crossing.

        One call for the whole window. Per-address would pay the round-trip
        toll -- 1.46 ms here, against microseconds of actual work -- once per
        element, and a window holds hundreds.

        Deliberately not part of `drain`. Reading a rect forces the browser
        to settle layout, and doing that inside the fold would make every
        mutation pay for geometry nobody asked for.
        """
        paths = [self.path_of(a) for a in addresses]
        if not paths:
            return {"styles": [], "vw": 0, "vh": 0, "doc": 0}
        return self._call("styles", paths) or {
            "styles": [], "vw": 0, "vh": 0, "doc": 0}

    def resolves(self, address) -> bool:
        """Whether the address still names a live node."""
        return bool(self._call("resolve", self.path_of(address)))

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
            offered=[tuple(f) for f in (raw.get("offered") or [])],
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
