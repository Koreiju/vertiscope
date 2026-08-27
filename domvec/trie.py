"""The universal content-address trie.

One globally-defined trie holds every address of every scan. Its path is the
address path of :meth:`domvec.address.ContentAddress.path`::

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
:mod:`domvec.core.content_tree`, which is directional. Layering the two —
hash to find candidates in O(1), subsumption to decide — is what lets
deduplication run against the trie alone, with no DOM access.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from .address import ContentAddress
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
    """Hash of the token multiset — a dedup *candidate* key, never a decision."""
    payload = "\x1f".join(f"{t}:{n}" for t, n in token_multiset(value))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]


# --- ordering ---------------------------------------------------------------

_SEG_RE = re.compile(r"^([^\[\]]+)(?:\[(\d+)\])?$")


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

    # label -> that label group's position among this node's children.
    _label_order: Dict[str, int] = field(default_factory=dict, repr=False)

    @property
    def is_leaf(self) -> bool:
        return self.address is not None

    def ordered_children(self) -> List["TrieNode"]:
        """Children in document order: label group first, then sibling index.

        Nodes whose label ordinal is unknown sort after those that have one,
        by label, so a partially-restored trie still iterates deterministically
        instead of raising or shuffling.
        """
        kids = list(self.children.values())
        kids.sort(key=lambda n: (
            n.doc_pos < 0, n.doc_pos,
            n.label_order < 0, n.label_order, _seg_key(n.segment)
        ))
        return kids

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
        self._dirty = True
        # Issues leaf identities. Monotone and never reused, so a uid names
        # one piece of content for as long as it is on the page, however
        # often its address is re-pointed underneath it.
        self._uid_seq = 0

    # -- build ------------------------------------------------------------
    def insert(
        self,
        address: ContentAddress,
        value: str = "",
        doc_pos: Optional[Dict[str, int]] = None,
    ) -> TrieNode:
        """Add one address. Re-inserting an address overwrites its value.

        ``doc_pos`` maps absolute xpath to walk position (the scan's
        ``TaggedContent.doc_pos``). Supplying it makes sibling order exact;
        omitting it falls back to label-group order.

        Overwrite rather than append is forced by the addressing being a key
        (see :mod:`domvec.address`): two values at one address would mean the
        address is not a key, and silently keeping both would hide that. A
        caller that wants to know instead of overwrite checks
        :func:`domvec.address.collisions` first.
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
                if in_dom and doc_pos is not None:
                    pos = doc_pos.get(xpath_prefix, -1)
                child = TrieNode(
                    segment=seg, depth=i, doc_pos=pos, label_order=order
                )
                node.children[seg] = child
            node = child
        if node.address is None:
            self._leaf_count += 1
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

    def apply(self, units, removed=()) -> "TrieDelta":
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
        displaced: Dict[str, List[Tuple[int, Tuple]]] = {}
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
                    (leaf.uid, leaf.address.key()))

        for address, value in units:
            key = address.key()
            digest = want[key][2]
            node = self.find(address)
            if node is not None and node.content_hash == digest:
                continue            # already says this; costs nothing
            pool = displaced.get(digest)
            inherited = 0
            while pool:
                uid, from_key = pool.pop()
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

        for address in removed:
            if self.remove(address):
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
        """Origins and pages present, ordered."""
        seen: List[str] = []
        for leaf in self.leaves():
            if leaf.address and leaf.address.url not in seen:
                seen.append(leaf.address.url)
        return seen

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
        for child in node.ordered_children():
            h.update(child.subtree_hash.encode("utf-8"))
            h.update(b"\x1e")
        node.subtree_hash = h.hexdigest()[:16]

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
        for tag in tags:
            trie.insert(address_of(tag, url), tag.value, doc_pos)
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
