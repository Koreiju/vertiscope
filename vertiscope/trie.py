"""The universal content-address trie.

One globally-defined trie holds every address of every scan. Its path is the
address path of :meth:`vertiscope.address.ContentAddress.path`::

    origin / url segments... / xpath steps... / content tag / accessor

so a single structure answers four different questions with one prefix test:

* same site                  — share the origin segment
* same page                  — share the whole url prefix
* DOM ancestry               — share the xpath prefix (THEORY Prop. 11.2)
* same node, other accessor  — differ only in the final two segments

That this is a trie rather than a design choice is THEORY Cor. 11.3: the
addresses of a document form a trie, ancestry is a prefix test, and any family
of pairwise non-nested addresses is a prefix code.

Ordering
--------
An in-order walk of the trie must be document order, so that reading content
back out of the source DOM in trie order is a single forward pass. That is
the reason for storing absolute rather than generalized addresses — but the
absolute xpath alone is not enough.

An xpath index counts siblings *of the same label*: ``div[2]`` is the second
``div``, not the second child. So ``/html/head`` and ``/html/body`` are both
index 1 and the xpath does not say which comes first; sorting on the label
puts ``body`` before ``head``, which is wrong, and no function of the two
xpaths can fix it because the information is not in them.

Order therefore comes from the scan, as ``TaggedContent.doc_pos``: the
position at which the DOM walk reached each node. The walk enqueues a
parent's children contiguously and in document order, so ordering a parent's
children by that counter reproduces the document exactly — including
``head`` before ``body`` and interleaved labels like ``p div p``.

Two things this is deliberately not:

* not per-*detection* arrival order. Detections are sparse — an element with
  no attributes and no direct text yields none — so a container div would
  take its position from whichever descendant happened to be reported first.
  Measured over the corpus, that mis-ordered 15.9% of multi-label parents.
* not derived from the xpath. The information is not there: ``/html/head``
  and ``/html/body`` are both index 1.

Where a position is unknown — a node reconstructed without one, or the url and
tag segments that have no DOM node behind them — the traversal falls back to
``(label group first seen, sibling index)``, which is deterministic and exact
within a label group. Measured over the corpus, the only nodes that ever take
this path are the url-prefix segments, each of which heads a single chain, so
the fallback never decides anything observable.

Shadow content
--------------
``#shadow-root`` is a path segment with no node behind it: the parser
synthesises it while addressing. Shadow content therefore sorts by the walk
positions of the nodes *inside* the shadow tree, and those come after the
host's light-DOM children, because ``get_children(include_shadow=True)``
yields light children first.

That ordering is the parser's, and it is a defensible reading rather than an
oversight — the composed order a browser renders depends on ``<slot>``
placement, which the serialized form does not preserve, so no ordering of the
two can be called the document's. What matters here is that it is total,
deterministic and stable across passes, which it is.

Delta
-----
Every node carries a Merkle ``subtree_hash`` over its own content and its
children's subtree hashes. :func:`diff` compares two tries and stops
descending wherever the hashes agree, so its cost is proportional to the
changed region plus the depth of each change, not to page size. This is the
O(delta) property the mutation-observer pipeline needs: a scroll that appends
twenty cards to a ten-thousand-node page touches twenty leaves and their
ancestors.

Deduplication
-------------
A leaf carries ``content_hash``, the hash of its *normalized token multiset*
rather than of its raw string. Equal hashes are duplicate **candidates**, and
that is all a hash can be: by THEORY Prop. 19.3 a hash gives an equivalence,
so it can say two units are the same but never which to keep. The keeping
decision is the subsumption partial order in
:mod:`vertiscope.core.content_tree`, which is directional. Layering the two —
hash to find candidates in O(1), subsumption to decide — is what lets
deduplication run against the trie alone, with no DOM access.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from .address import ContentAddress, url_steps
from .privacy import redact_url

__all__ = [
    "TrieNode",
    "AddressTrie",
    "TrieDelta",
    "diff",
    "content_hash",
    "token_multiset",
]

# Unicode word runs — letters and digits across all scripts, minus '_'. An
# ASCII-only tokenizer produces the empty multiset for CJK, Cyrillic and
# accented text, which would make every non-Latin unit hash alike and collapse
# a page's worth of distinct content into one candidate class.
_TOKEN_RE = re.compile(r"[^\W_]+", re.UNICODE)


def token_multiset(value: str) -> Tuple[Tuple[str, int], ...]:
    """Normalized token multiset, canonically ordered.

    A multiset, not a set: THEORY Prop. 2.6.1 makes multisets the free
    commutative monoid, and dropping multiplicity would equate "buy buy buy"
    with "buy". Sorted so the hash of the multiset is well defined —
    the tokenization forgets order (THEORY Prop. 13.2), so any order-dependent
    encoding of it would make the hash depend on something the value does not
    determine.
    """
    counts: Dict[str, int] = {}
    for tok in _TOKEN_RE.findall(value.lower()):
        counts[tok] = counts.get(tok, 0) + 1
    return tuple(sorted(counts.items()))


def content_hash(value: str) -> str:
    """Hash of the token multiset — a dedup *candidate* key, never a decision.

    With one fallback, for values the multiset cannot describe at all.

    Blindness to word order, case and punctuation is what lets a paragraph be
    recognised after it moved and was reformatted, and that is worth having.
    But a value made *only* of punctuation has an empty multiset, so `(`, `=>`,
    `,` and `->` all hashed alike — and this hash is what the re-anchor matches
    on, so it would hand one token's identity to a different token, and what
    the dedup filter groups by, so it pooled every such value together.

    There is nothing to be blind about in a value with no tokens: the multiset
    carries no information, and the only thing left that distinguishes them is
    the text. So those are keyed on the whitespace-normalized string instead —
    still blind to the reformatting the token path is blind to, since
    collapsing whitespace is exactly what that does.

    The two keyings live in separate namespaces, so a punctuation-only value
    can never collide with a tokenized one.
    """
    tokens = token_multiset(value)
    if tokens:
        payload = "\x1f".join(f"{t}:{n}" for t, n in tokens)
    else:
        payload = "\x00" + " ".join(value.split())
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


# --- ordering ---------------------------------------------------------------

_SEG_RE = re.compile(r"^([^\[\]]+)(?:\[(\d+)\])?$")


# An index of [1] on an element step, which the trie's own segments omit.
# The lookbehind keeps `text()[1]` intact: that bracket is an accessor's, not
# a sibling ordinal.
_INDEX_ONE = re.compile(r"(?<=[A-Za-z0-9_-])\[1\](?=/|$)")


def trie_doc_pos(mapping: Dict[str, int]) -> Dict[str, int]:
    """A scan's ``doc_pos`` map, re-keyed the way the trie names its paths.

    The tagger keys walk positions on absolute xpaths and writes an index
    wherever an element has same-tag siblings: `.../ul/li[1]`, `.../ul/li[2]`.
    The trie builds its path from `ContentAddress.path()`, which drops the
    index on the first of a group: `.../ul/li`, `.../ul/li[2]`.

    So the lookup missed for the first sibling of every repeated group, and
    only for that one. It got `doc_pos = -1`, `ordered_children` sorts unknown
    positions *after* known ones, and the first item of every list, table and
    card grid was drawn at the bottom of its group -- with every address
    correct and every unit present, so no coverage or dedup number could see
    it. Reading order is what an affine map is supposed to preserve, and this
    was the projection quietly not preserving it.

    Only the snapshot path was affected. The live path supplies no map at all,
    every position is unknown, and `_seg_key` then orders siblings by their
    index -- correctly. The two paths are meant to produce the same chunks,
    and one of them was wrong.

    Positions collide only if a map holds both spellings of one path; the
    earlier position wins, which is the one the walk reached first.
    """
    out: Dict[str, int] = {}
    for key, pos in mapping.items():
        plain = _INDEX_ONE.sub("", key)
        if plain not in out or pos < out[plain]:
            out[plain] = pos
    return out


def _seg_key(seg: str) -> Tuple[str, int]:
    """Sort key for one trie segment: label, then numeric sibling index."""
    m = _SEG_RE.match(seg)
    if m is None:
        return (seg, 0)
    return (m.group(1), int(m.group(2)) if m.group(2) else 1)


# --- nodes ------------------------------------------------------------------


@dataclass
class TrieNode:
    """One node. Internal nodes carry structure; leaves carry an address."""

    segment: str
    depth: int = 0
    children: Dict[str, "TrieNode"] = field(default_factory=dict)

    # Position of the underlying DOM node in the scan's document-order walk.
    # -1 means unknown (a url or tag segment, or a node restored without it),
    # in which case ``label_order`` decides.
    doc_pos: int = -1

    # Order of this node's *label group* among its siblings' label groups,
    # taken from the order in which the parent first saw the label. The
    # fallback when ``doc_pos`` is unknown.
    label_order: int = -1

    # Leaf payload — set only where an address terminates.
    address: Optional[ContentAddress] = None
    value: str = ""
    content_hash: str = ""

    # Identity that outlives this node's address. An address is positional,
    # so inserting one sibling re-points every later address at different
    # content: the fifth item in a list is not the same *thing* it was a
    # moment ago. Position therefore cannot be identity on a live page, and
    # anything that needs to survive a shift — a memoised binding, a
    # control's state, "the item I was reading" — has to hang off this
    # instead. Assigned on first arrival and inherited by whichever address
    # the content moves to.
    uid: int = 0

    # Merkle hash over this node and everything below it.
    subtree_hash: str = ""

    # A *second* Merkle, over the same subtree under a stricter equivalence.
    #
    # `subtree_hash` folds in `content_hash`, which is the hash of a value's
    # normalized token multiset -- deliberately blind to word order, case and
    # punctuation, because that blindness is what lets `apply` recognise a
    # paragraph that moved. Identity has to survive reformatting.
    #
    # A projection out of the trie cannot use that hash to decide "nothing
    # here changed", because it prints the value *verbatim*: "a b" and "b a"
    # share a content_hash and render differently. `exact_hash` folds in the
    # exact value and the full address instead, so equality of `exact_hash`
    # means the subtree renders byte-identically -- the guarantee a memoised
    # render needs, and one the trie is the right place to make.
    #
    # Two hashes for two equivalences, both maintained in one bottom-up pass:
    # `subtree_hash` answers "is this the same content?" (move detection),
    # `exact_hash` answers "does this draw the same?" (projection reuse).
    #
    # A Python `hash` rather than a digest: it is consulted in-process by the
    # renderer and never persisted or compared across processes, so the cost
    # matters and stability across runs does not.
    exact_hash: int = 0

    # label -> that label group's position among this node's children.
    _label_order: Dict[str, int] = field(default_factory=dict, repr=False)

    # `ordered_children()` memoised, with the child count it was built from.
    # Sorting is not free -- the key parses the segment with a regex -- and
    # every walk of the trie asks every node for its children in order, so on
    # a page of any size this was being paid tens of thousands of times per
    # read for an answer that had not changed.
    #
    # The count is the whole validity check, and that is sound rather than
    # convenient: children are only ever added (`insert`) or dropped
    # (`remove`), never replaced, and `doc_pos` and `label_order` are set when
    # a node is constructed and never assigned again. So nothing can reorder a
    # child list while its length stays the same.
    # A copy goes out, not the cached list. Handing out the internal one
    # measured 4% faster and would make every caller a potential corruption
    # of the trie's own view of its order -- `walk` holds the result across
    # yields, so the bug would surface as a traversal that skipped nodes,
    # which is the hardest kind of wrong answer to notice here.
    _ordered: Optional[List["TrieNode"]] = field(default=None, repr=False)
    _ordered_n: int = field(default=-1, repr=False)

    # Absolute xpath, assigned by `insert` when the node is created. Read by
    # the projections as a chunk's root address.
    _xpath_cache: Optional[str] = field(default=None, repr=False)

    @property
    def is_leaf(self) -> bool:
        return self.address is not None

    def ordered_children(self) -> List["TrieNode"]:
        """Children in document order: label group first, then sibling index.

        Nodes whose label ordinal is unknown sort after those that have one,
        by label, so a partially-restored trie still iterates deterministically
        instead of raising or shuffling.
        """
        if self._ordered is not None and self._ordered_n == len(self.children):
            return list(self._ordered)
        kids = list(self.children.values())
        kids.sort(key=lambda n: (
            n.doc_pos < 0, n.doc_pos,
            n.label_order < 0, n.label_order, _seg_key(n.segment)
        ))
        self._ordered = kids
        self._ordered_n = len(kids)
        return list(kids)

    def walk(self) -> Iterator["TrieNode"]:
        """Pre-order traversal in document order — self, then each subtree."""
        yield self
        for child in self.ordered_children():
            yield from child.walk()

    def leaves(self) -> Iterator["TrieNode"]:
        for node in self.walk():
            if node.is_leaf:
                yield node


def admitted(address: "ContentAddress", value: str) -> str:
    """The value an address is allowed to hold.

    One rule, and a narrow one: a value that *is* a url is stored redacted.
    Everything else is passed through untouched.

    The narrowness is the point. A link on a page is the page's own content,
    and a general "this looks like a secret" filter over content values was
    tried against the frozen corpus and rejected: the shape test that
    separates a token from a slug inside a query string cannot tell
    `//upload.wikimedia.org/.../Lock-green.svg` from a credential, and it
    flagged 123 perfectly ordinary values across eight pages. A rule that
    eats content to protect content is not a privacy improvement.

    What it does catch is the case that has no other reading:
    `<a href="https://alice:letmein@site.test/p?access_token=...">` puts a
    password and a session token into the database verbatim, and neither is
    what anyone came to read. Measured over the corpus this changes 2.1% of
    url values, and every one of them is a campaign tag, an api key or an
    ad-vendor identifier.

    Applied here rather than at the store, because here is where both
    extraction paths meet: the tagger's `from_tagged` and the sensor's
    `apply` are the trie's only two writers, so this is the one place the
    rule cannot be applied to one path and forgotten on the other.
    """
    if value and address is not None and address.is_url:
        return redact_url(value)
    return value


class AddressTrie:
    """A trie over content addresses, spanning any number of URLs."""

    def __init__(self) -> None:
        self.root = TrieNode(segment="", depth=0)
        self._leaf_count = 0
        # Insertion-ordered set of the urls present. See `urls()`.
        self._urls: Dict[str, None] = {}
        self._dirty = True
        # Issues leaf identities. Monotone and never reused, so a uid names
        # one piece of content for as long as it is on the page, however
        # often its address is re-pointed underneath it.
        self._uid_seq = 0
        # Where a node was met, when nobody supplied a map. `insert` hands
        # each newly created DOM node the next value, so a caller that
        # arrives in document order gets document order recorded rather
        # than re-derived. See `insert` for why derivation was not enough.
        self._arrival = 0

    # -- build ------------------------------------------------------------
    def insert(
        self,
        address: ContentAddress,
        value: str = "",
        doc_pos: Optional[Dict[str, int]] = None,
    ) -> TrieNode:
        """Add one address. Re-inserting an address overwrites its value.

        ``doc_pos`` maps trie path to walk position. A scan's map is keyed by
        the tagger's convention and must be put through `trie_doc_pos` first;
        `from_tags` does that.

        Without it, order is taken from **arrival**: each DOM node gets the
        next value of a monotone counter as it is first met. The live path
        hands units over in document order -- `sensing._decode` walks the
        fold's own recursive descent and says so -- so recording that order
        is observing it, not guessing.

        It used to be derived instead, by label group and then sibling index,
        and this docstring called that "also correct". It is correct only for
        siblings that share a label. A parent whose children *alternate* --
        which is what a sentence with a link in it is -- was emitted one
        label group at a time:

            page    Physics studies [matter] and [energy] across space
            trie    "Physics studies" / "and" / "across" ...
                    then [matter], [energy], then "space"

        Every address was right, every unit was present, and no coverage,
        dedup or drift number could see it, because not one of them looks at
        sequence. The reader-facing claim is that the REPL shows what the page
        shows, and word order is most of what that means. Measured on
        tests/fixtures/mixed_inline.html and on ko.wikipedia, where a lead
        paragraph's prose and its inline links came out as two separate runs.

        The snapshot path was never affected: it supplies the map.

        Overwrite rather than append is forced by the addressing being a key
        (see :mod:`vertiscope.address`): two values at one address would mean the
        address is not a key, and silently keeping both would hide that. A
        caller that wants to know instead of overwrite checks
        :func:`vertiscope.address.collisions` first.
        """
        value = admitted(address, value)
        node = self.root
        # path() and steps() each rebuild their tuples from scratch, and this
        # runs once per detection — hold them rather than recomputing.
        path = address.path()
        n_steps = len(address.steps())
        # The xpath steps occupy the middle of the path; the url prefix and
        # the trailing tag/accessor have no DOM node, hence no walk position.
        url_len = len(path) - n_steps - 2
        xpath_prefix = ""
        for i, seg in enumerate(path, start=1):
            in_dom = url_len < i <= url_len + n_steps
            if in_dom:
                xpath_prefix += "/" + seg
            child = node.children.get(seg)
            if child is None:
                # The label's first arrival fixes the group's position; the
                # xpath index orders within the group. Used only when the
                # walk position is unavailable.
                label = _seg_key(seg)[0]
                order = node._label_order.get(label)
                if order is None:
                    order = len(node._label_order)
                    node._label_order[label] = order
                pos = -1
                if in_dom:
                    if doc_pos is not None:
                        pos = doc_pos.get(xpath_prefix, -1)
                    else:
                        # First arrival fixes the position, and only the
                        # first: a node re-offered later has not moved, and
                        # re-stamping it would let a repair reorder a page
                        # that did not change.
                        pos = self._arrival
                        self._arrival += 1
                child = TrieNode(
                    segment=seg, depth=i, doc_pos=pos, label_order=order
                )
                # The node's absolute xpath, fixed here because it is fixed
                # for the node's life: a segment never changes and neither do
                # its ancestors, so content "moving" in this trie means
                # content arriving at a *different node*, not a node changing
                # address. The renderer used to derive this with a walk of
                # every element on the page, on every render, to avoid
                # recomputing it per candidate chunk -- an O(page) read of
                # something the write already knew.
                child._xpath_cache = xpath_prefix or "/"
                node.children[seg] = child
                node._ordered = None
            node = child
        if node.address is None:
            self._leaf_count += 1
        self._urls.setdefault(address.url, None)
        node.address = address
        node.value = value
        node.content_hash = content_hash(value) if value else ""
        self._dirty = True
        return node

    def extend(self, pairs: Iterable[Tuple[ContentAddress, str]]) -> int:
        n = 0
        for addr, value in pairs:
            self.insert(addr, value)
            n += 1
        return n

    def apply(self, units, removed=(), moved=()) -> "TrieDelta":
        """Repair in place from one drain. The live path's only mutator.

        An address is positional, so a structural shift is not reported to us
        as a shift — it arrives as every address after the insertion point
        holding somebody else's content. Absorbing that naively makes one
        node's arrival cost the whole span: inserting a single ``<li>`` at the
        head of a hundred-item list was measured at a delta of 101, and the
        figure was exactly ``N + 1`` at every length tried. Cost tracked the
        page, which is the O(delta) property failing rather than holding.

        The fix is to re-anchor by content. Before anything is written, the
        contents about to be displaced are indexed; an address whose new value
        was, a moment ago, some other address's value is then recognised as
        that content having *moved*. The moved leaf keeps its ``uid``, so
        whatever hangs off a leaf's identity survives the shift, and the delta
        reports one arrival rather than a hundred edits.

        Content is matched on ``content_hash``, which is a candidate key and
        not a decision (THEORY Prop. 19.3): two genuinely identical strings in
        one span are indistinguishable, so they may swap uids. That is
        harmless precisely because they are identical — nothing downstream can
        observe the difference — and it is why the match is scoped to a
        parent span rather than the page, so unrelated repetition elsewhere
        cannot claim a uid.
        """
        delta = TrieDelta()

        # What the fold *said* moved, read before anything is written.
        #
        # The content-hash re-anchor below recovers a shift the fold did not
        # report, and it is bounded to the spans this drain touches -- which
        # is what keeps it proportional to the change. A move out of one
        # parent and into another is therefore outside its reach: the old leaf
        # lives under a span no incoming unit names, so its uid is never
        # offered to the address that now holds its content.
        #
        # On a flat list that never matters, because a shift re-points
        # addresses within one parent and the old leaves are in the span. On a
        # real page it matters constantly, and it is the difference between an
        # address moving and an address being replaced by a stranger.
        #
        # So a reported move is taken as authoritative: the uid travels with
        # the content, and the address it left is vacated below.
        carried: Dict[Tuple, Tuple[int, ContentAddress]] = {}
        # A removal that is the far side of a reported move is movement, not
        # an edit. The fold now verifies these against the page before naming
        # them -- `sensor.alive` -- so they are real removals; but the content
        # did not leave the document, it changed address, and the destination
        # is already in `delta.moved`. Counted as edits they made one inserted
        # node read as a page rewriting itself: delta==1 held on 112 of 121
        # corpus pages and fell to 21 the moment these arrived.
        vacated_by_move = {old_address.key() for old_address, _new in moved}
        for old_address, new_address in moved:
            node = self.find(old_address)
            if node is None or not node.is_leaf or not node.uid:
                continue
            carried[new_address.key()] = (node.uid, old_address)

        # Redacted before the content index below is built, not after: the
        # re-anchoring matches on the value, so admitting one spelling and
        # indexing another would make a moved leaf look like a new one.
        units = [(address, admitted(address, value))
                 for address, value in units]

        # What each incoming address is about to hold.
        want: Dict[Tuple, Tuple[ContentAddress, str, str]] = {}
        for address, value in units:
            want[address.key()] = (address, value, content_hash(value))

        # The spans this drain touches. Bounding the re-anchor to them is what
        # keeps it proportional to the change: a page-wide index would be
        # rebuilt in full for a two-line edit.
        spans = {address.path()[:-3] for address, _ in units}

        # Snapshot the contents that are on their way out, before writing.
        # Only leaves whose value is actually being displaced are candidates:
        # a leaf that keeps its value has not moved, it has stayed.
        # Held as (uid, key) rather than as nodes. A node reference would be
        # read *after* the loop had already overwritten it, so the first
        # address to be rewritten would hand its brand-new uid to whoever
        # claimed its old content next, and one uid would spread down the
        # whole span. The snapshot has to be of values taken before any write.
        displaced: Dict[str, List[Tuple[int, Tuple, ContentAddress]]] = {}
        for span in spans:
            node = self.node_at(span)
            if node is None:
                continue
            for leaf in node.leaves():
                if leaf.address is None:
                    continue
                incoming = want.get(leaf.address.key())
                if incoming is not None and incoming[2] == leaf.content_hash:
                    continue        # unchanged — not displaced
                displaced.setdefault(leaf.content_hash, []).append(
                    (leaf.uid, leaf.address.key(), leaf.address))

        for address, value in units:
            key = address.key()
            digest = want[key][2]
            node = self.find(address)
            # The *exact* value, not the content hash.
            #
            # `content_hash` is the hash of a normalized token multiset, and
            # that blindness is deliberate: it is what lets the re-anchor
            # below recognise a paragraph that moved and was reformatted. It
            # is the wrong test for "is there anything to write", because a
            # value made only of punctuation has an empty multiset -- `(`,
            # `=>`, `,`, `->` and a bracketed line break all hash to
            # sha1("") -- so every
            # change between two of them looked like no change at all and was
            # dropped.
            #
            # Syntax-highlighted code is made of those: on php.net's manual
            # page, 30 addresses inside `<pre><code><span>` held one token
            # while the page held another, and the move channel had delivered
            # the right value to the right address every time. The write was
            # refused after it arrived.
            #
            # Same distinction the renderer needs between `subtree_hash` and
            # `exact_hash`, in a second place: matching is allowed to be
            # blind, deciding whether to write is not.
            if node is not None and node.value == value:
                # Already says this, so there is nothing to write -- but a
                # move reported into this address still has to hand its
                # identity over, because the fold has also verified the source
                # as gone and something must carry the uid off it.
                #
                # The case is a string that repeats down a list: every card
                # carries "by", "(about)", "Tags:", so on a shift the value
                # arriving is the value already there. Without this the uid is
                # dropped while its source is removed. Safe because every uid
                # is snapshotted before any write, so a chain of identical
                # values passes identities along it whatever order the units
                # arrive in; which of several identical strings carries which
                # identity is not observable (THEORY Prop. 19.3), a uid
                # vanishing is.
                reported = carried.get(key)
                if reported is not None and node.uid != reported[0]:
                    node.uid = reported[0]
                    delta.moved.append(address)
                # Already says this: nothing to write, and nothing to
                # re-identify either.
                #
                # I had this adopt the uid of a reported move whose
                # destination was already correct, on the grounds that the
                # identity should travel even when the value does not. It
                # travelled by *overwriting* the identity already sitting
                # there, and where the chain of identical values does not
                # close, the overwritten one simply vanishes. Arabic Wikipedia
                # lost 85 that way -- a page whose navigation lists repeat the
                # same link text many times over.
                #
                # Which of several identical strings carries which identity is
                # not observable (THEORY Prop. 19.3), so declining to swap
                # costs nothing; a uid vanishing is observable, and that is
                # what swapping cost.
                continue
            pool = displaced.get(digest)
            inherited = 0
            reported = carried.get(key)
            if reported is not None:
                inherited = reported[0]
            while not inherited and pool:
                uid, from_key, from_address = pool.pop()
                if not uid or from_key == key:
                    continue
                inherited = uid
                break
            fresh = self.insert(address, value)
            # Always re-issue. A leaf whose content changed is not the thing
            # it was, so keeping the uid already sitting on that address would
            # attach the departed content's identity to its replacement.
            if inherited:
                fresh.uid = inherited
                delta.moved.append(address)
            else:
                self._uid_seq += 1
                fresh.uid = self._uid_seq
                (delta.changed if node is not None else delta.added).append(address)

        # Nothing is vacated here, and that is a correction rather than an
        # omission.
        #
        # I had this deleting the address a move came from: content is written
        # at its new address, the DOM removed nothing so the fold reports no
        # removal, and the old address would otherwise keep a stale copy. On a
        # flat list it looked exactly right -- the trie stopped growing, no
        # identity was lost, and four real pages agreed.
        #
        # It is wrong, and Arabic Wikipedia is where that became visible: a
        # page of 11,793 leaves and 151 list items, where one inserted node
        # made the trie *shrink* by 84 addresses and lose 85 identities. Of
        # 60 sampled addresses the rule wanted to drop, **47 were still
        # present in the live DOM**.
        #
        # The premise was that an address whose content moved away, and which
        # this drain does not claim, is empty. The fold does not re-send
        # content the receiver already holds, so its silence about an address
        # is not evidence about that address -- it is the absence of evidence,
        # and on a page whose spans do not chain neatly the two are nothing
        # alike. The flat-list shift reoccupies every address it vacates,
        # which is why four pages agreed and the fifth did not.
        #
        # A stale address is a real defect: the trie grows while the page does
        # not, and `analytics/live_delta.py` reports it per page. Deleting
        # content the page still has is a worse one, and silent. Until the
        # fold can say "this address is now empty" -- which is what `removed`
        # is for and what it does not currently carry for a shift -- the trie
        # keeps what it was told and reports what it kept.
        #
        # What survives from that work is the identity carrying above, which
        # is sound and independent: it took news.ycombinator.com from 654
        # genuine changes for one inserted row to 1.

        for address in removed:
            # A removal this same drain contradicts is stale, and applying it
            # undoes the re-anchoring above.
            #
            # Chunk ids are keyed on position, so a node inserted at the head
            # of a list retires the id of every chunk below it: the fold
            # reports N removals for one arrival, naming the *old* layout.
            # Those addresses are also in `units`, holding the shifted
            # content, and the loop above has already given them their
            # previous leaves' uids. Deleting them afterwards destroyed the
            # very identities the re-anchor had just preserved -- one <li>
            # into a 400-item list measured 399 uids lost and a delta of 401,
            # while the same insertion applied without the removal list
            # measured a delta of 1 and lost none.
            #
            # `units` is authoritative for what exists now. A removal is only
            # a removal when this drain does not also say the address holds
            # something.
            if address.key() in want:
                continue
            if not self.remove(address):
                continue
            if address.key() in vacated_by_move:
                continue
            delta.removed.append(address)

        delta.visited = len(units)
        if delta.touched:
            self.rehash()
        return delta

    def remove(self, address: ContentAddress) -> bool:
        """Drop one address, and any ancestors it was the last leaf of.

        The trie was insert-only, which is sound for a snapshot — a snapshot
        is rebuilt whole, so a departed node simply never reappears. It is not
        sound for a live page, where the fold reports a node leaving the
        composed tree and nothing else ever will. Without this, a removed
        element's address stays in the trie forever and keeps rendering.

        Pruning the emptied ancestors matters as much as the leaf: leaving
        childless internal nodes behind would keep the *shape* of a departed
        subtree, so the root hash would never return to what it was before
        that subtree arrived, and no equality check over structure could work.
        """
        path = address.path()
        node = self.root
        chain = [node]
        for seg in path:
            node = node.children.get(seg)
            if node is None:
                return False
            chain.append(node)
        if node.address is None:
            return False
        node.address = None
        node.value = ""
        node.content_hash = ""
        self._leaf_count -= 1
        # Walk back up, dropping any node that is now neither a leaf nor an
        # ancestor of one.
        for i in range(len(chain) - 1, 0, -1):
            child = chain[i]
            if child.children or child.is_leaf:
                break
            parent = chain[i - 1]
            parent.children.pop(child.segment, None)
            parent._ordered = None
        # A url whose page node was pruned is no longer present. Checked here
        # rather than swept later: `render_trie` iterates `urls()` and asks for
        # each page node, and a stale entry would have it looking for one that
        # is gone.
        url = address.url
        if url in self._urls and self.node_at(url_steps(url)) is None:
            del self._urls[url]
        self._dirty = True
        return True

    # -- read -------------------------------------------------------------
    def __len__(self) -> int:
        return self._leaf_count

    def find(self, address: ContentAddress) -> Optional[TrieNode]:
        node = self.root
        for seg in address.path():
            node = node.children.get(seg)
            if node is None:
                return None
        return node if node.is_leaf else None

    def node_at(self, path: Sequence[str]) -> Optional[TrieNode]:
        """The node at an arbitrary path prefix — a page, a subtree, a node."""
        node = self.root
        for seg in path:
            node = node.children.get(seg)
            if node is None:
                return None
        return node

    def leaves(self) -> Iterator[TrieNode]:
        """Every addressed leaf, in document order."""
        return self.root.leaves()

    def addresses(self) -> List[ContentAddress]:
        return [n.address for n in self.leaves() if n.address is not None]

    def urls(self) -> List[str]:
        """Origins and pages present, in the order they first arrived.

        Kept as a set on the side rather than derived, because deriving it
        meant walking every leaf in the trie -- on a 6,400-row page, 25,601
        leaves visited to learn one string, once per render. Leaves arrive in
        document order, so first-arrival order is the order the walk produced.

        A url stays until its page node is gone, which `remove` checks when it
        prunes: an empty page is not a page, and a stale entry here would make
        `render_trie` look for a node that is not there.

        With more than one url the arrival order is not enough. The old walk
        met a page's leaves together, so it grouped pages under one origin;
        arrival order interleaves them when a scan visits two sites at once,
        which would reorder the chunks `render_trie` emits for no reason. So
        the set is put back into the trie's own order, which is what the walk
        was reporting. Pages are few and the path is short, so this costs
        nothing next to the leaf walk it replaces.
        """
        if len(self._urls) < 2:
            return list(self._urls)
        return sorted(self._urls, key=lambda u: self._path_rank(url_steps(u)))

    def _path_rank(self, steps: Sequence[str]) -> Tuple[int, ...]:
        """Where ``steps`` sits in a document-ordered traversal from the root."""
        rank: List[int] = []
        node = self.root
        for seg in steps:
            kids = node.ordered_children()
            for i, kid in enumerate(kids):
                if kid.segment == seg:
                    rank.append(i)
                    node = kid
                    break
            else:
                return tuple(rank)
        return tuple(rank)

    # -- hashing ----------------------------------------------------------
    def rehash(self) -> str:
        """Recompute every subtree hash bottom-up; returns the root hash.

        Iterative rather than recursive: real pages nest deeply enough
        (deeply-wrapped React trees, nested tables) that a recursive
        post-order hits CPython's recursion limit on a minority of pages, and
        a crash on 2% of a corpus is not a hashing scheme.
        """
        order: List[TrieNode] = list(self.root.walk())
        for node in reversed(order):  # children always follow parents in a
            self._hash_node(node)     # pre-order, so reversed is post-order
        self._dirty = False
        return self.root.subtree_hash

    @staticmethod
    def _hash_node(node: TrieNode) -> None:
        h = hashlib.sha1()
        h.update(node.segment.encode("utf-8"))
        h.update(b"\x1f")
        if node.is_leaf:
            h.update(node.content_hash.encode("utf-8"))
        h.update(b"\x1f")
        # Children in document order, not sorted-by-hash: reordering siblings
        # is a real change to a document and must change the hash.
        kids = node.ordered_children()
        for child in kids:
            h.update(child.subtree_hash.encode("utf-8"))
            h.update(b"\x1e")
        node.subtree_hash = h.hexdigest()[:16]
        # The strict twin. `address` is a frozen four-field dataclass, so
        # hashing it covers url/xpath/tag/accessor exactly; `value` is the raw
        # string the renderer prints; child order carries sibling order.
        # Together those are everything any projection reads off a node.
        node.exact_hash = hash((
            node.segment,
            node.address,
            node.value,
            tuple(child.exact_hash for child in kids),
        ))

    @property
    def root_hash(self) -> str:
        if self._dirty:
            self.rehash()
        return self.root.subtree_hash

    # -- construction from a scan ----------------------------------------
    @classmethod
    def from_tags(
        cls, tags: Iterable, url: str, doc_pos: Optional[Dict[str, int]] = None
    ) -> "AddressTrie":
        """Build from a tagger's detections. One leaf per distinct address."""
        from .address import address_of

        trie = cls()
        # Re-keyed once, here, rather than per insert: the map is the scan's
        # and its convention is not the trie's. See `trie_doc_pos`.
        positions = trie_doc_pos(doc_pos) if doc_pos else None
        for tag in tags:
            trie.insert(address_of(tag, url), tag.value, positions)
        trie.rehash()
        return trie

    @classmethod
    def from_tagged(cls, tagged, url: str) -> "AddressTrie":
        """Build from a whole :class:`TaggedContent`, walk positions included.

        Prefer this over :meth:`from_tags`: it is the only form that gets
        sibling order exactly right, because ``TaggedContent`` carries the
        walk positions and a bare tag list does not.
        """
        return cls.from_tags(
            tagged.all_tags, url, getattr(tagged, "doc_pos", None)
        )

    def stats(self) -> Dict[str, object]:
        nodes = sum(1 for _ in self.root.walk())
        return {
            "nodes": nodes,
            "leaves": self._leaf_count,
            "urls": len(self.urls()),
            "root_hash": self.root_hash,
        }


# --- delta ------------------------------------------------------------------


@dataclass
class TrieDelta:
    """What changed between two tries."""

    added: List[ContentAddress] = field(default_factory=list)
    removed: List[ContentAddress] = field(default_factory=list)
    changed: List[ContentAddress] = field(default_factory=list)
    # Content that is the same content, at a new address. Counted apart from
    # `changed` because conflating them makes one insertion look like an
    # edit to every element after it — the whole list re-vectorised, the
    # whole list reported as new, for a single node arriving.
    moved: List[ContentAddress] = field(default_factory=list)
    visited: int = 0
    """Nodes actually compared — the measured cost, for asserting O(delta)."""

    @property
    def size(self) -> int:
        """Genuine change. A move is not change; it is the same fact, re-placed."""
        return len(self.added) + len(self.removed) + len(self.changed)

    @property
    def touched(self) -> int:
        """Every address this delta re-points, movement included."""
        return self.size + len(self.moved)

    def summary(self) -> Dict[str, int]:
        return {
            "added": len(self.added),
            "removed": len(self.removed),
            "changed": len(self.changed),
            "visited": self.visited,
        }


def diff(old: AddressTrie, new: AddressTrie) -> TrieDelta:
    """Merkle diff. Cost is proportional to the change, not to page size.

    Where two subtrees hash equal the descent stops, so an unchanged region
    of any size costs one comparison. The soundness of that pruning is the
    usual Merkle argument: ``subtree_hash`` is a function of the subtree's
    full content, so equal hashes imply equal subtrees up to collision, and at
    16 hex digits a collision costs a missed update, not a corrupted one.

    ``visited`` records how many nodes were compared, which is what makes the
    O(delta) claim testable rather than asserted — see
    ``tests/test_trie.py::test_diff_cost_tracks_delta_not_page_size``.
    """
    if old._dirty:
        old.rehash()
    if new._dirty:
        new.rehash()

    delta = TrieDelta()

    def descend(a: Optional[TrieNode], b: Optional[TrieNode]) -> None:
        delta.visited += 1
        if a is not None and b is not None and a.subtree_hash == b.subtree_hash:
            return  # the whole subtree is unchanged — this is the pruning
        if a is None and b is not None:
            for leaf in b.leaves():
                if leaf.address:
                    delta.added.append(leaf.address)
                delta.visited += 1
            return
        if b is None and a is not None:
            for leaf in a.leaves():
                if leaf.address:
                    delta.removed.append(leaf.address)
                delta.visited += 1
            return
        assert a is not None and b is not None
        if a.is_leaf and b.is_leaf and a.content_hash != b.content_hash:
            if b.address:
                delta.changed.append(b.address)
        elif a.is_leaf and not b.is_leaf and a.address:
            delta.removed.append(a.address)
        elif b.is_leaf and not a.is_leaf and b.address:
            delta.added.append(b.address)
        for seg in sorted(set(a.children) | set(b.children), key=_seg_key):
            descend(a.children.get(seg), b.children.get(seg))

    descend(old.root, new.root)
    return delta
