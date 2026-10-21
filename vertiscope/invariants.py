"""Representation invariants as executable predicates.

`notes/proposals/MODEL.md` §4 states the representation invariant that carves
out the legal concrete states — the states on which the abstraction map is
defined. Stating it in prose and asserting it inline in tests has two costs:
the invariant cannot be checked against live state (MODEL §7.4 use 2), and the
assertions cannot themselves be tested for vacuity.

Each function here returns a list of violations, empty when the clause holds.
Returning violations rather than a boolean matters: a predicate that can only
say "false" cannot say *how many* rows are wrong, and a mutation test needs the
count to confirm it perturbed what it intended to.

These are cheap enough to call on live state. They are not called automatically;
doing so is a policy decision, not a property of the invariant.
"""

from __future__ import annotations

from typing import Any, List

Violation = str


def ri1_matrix_shape(tfidf: Any) -> List[Violation]:
    """MODEL RI-1: tf has |ids| rows and |vocab| columns."""
    out: List[Violation] = []
    rows, cols = tfidf._tf.shape
    if rows != len(tfidf._chunk_ids):
        out.append(f"tf has {rows} rows, identifier count is {len(tfidf._chunk_ids)}")
    if cols != len(tfidf._vocab):
        out.append(f"tf has {cols} columns, vocabulary size is {len(tfidf._vocab)}")
    return out


def ri2_identifiers_unique(tfidf: Any) -> List[Violation]:
    """MODEL RI-2: identifiers do not repeat and the row map inverts them."""
    out: List[Violation] = []
    ids = tfidf._chunk_ids
    if len(set(ids)) != len(ids):
        seen, dupes = set(), set()
        for i in ids:
            (dupes if i in seen else seen).add(i)
        out.append(f"repeated identifiers: {sorted(dupes)[:5]}")
    expected = {c: i for i, c in enumerate(ids)}
    if tfidf._chunk_id_to_row != expected:
        wrong = [
            k for k in set(expected) | set(tfidf._chunk_id_to_row)
            if expected.get(k) != tfidf._chunk_id_to_row.get(k)
        ]
        out.append(f"row map disagrees for {len(wrong)} identifier(s): {wrong[:5]}")
    return out


def ri3_df_derived(tfidf: Any) -> List[Violation]:
    """MODEL RI-3 (PROP-14.6): df[j] equals the number of rows nonzero in j.

    The load-bearing clause: it is the only one tying the maintained aggregate
    to the matrix it summarises. Recomputed, never trusted.
    """
    out: List[Violation] = []
    cols = tfidf._tf.shape[1]
    recomputed = (tfidf._tf > 0).sum(axis=0).A1
    for j in range(cols):
        stored = int(tfidf._df[j]) if j < len(tfidf._df) else None
        actual = int(recomputed[j])
        if stored != actual:
            out.append(f"column {j}: df={stored}, rows nonzero={actual}")
    return out


def ri4_meta_aligned(tfidf: Any) -> List[Violation]:
    """MODEL RI-4: metadata is index-aligned with the identifier sequence."""
    if len(tfidf._chunk_meta) != len(tfidf._chunk_ids):
        return [f"meta has {len(tfidf._chunk_meta)} entries, "
                f"identifiers {len(tfidf._chunk_ids)}"]
    return [
        f"row {i}: meta.chunk_id={m.chunk_id!r}, ids[{i}]={cid!r}"
        for i, (m, cid) in enumerate(zip(tfidf._chunk_meta, tfidf._chunk_ids))
        if m.chunk_id != cid
    ]


def ri5_digest_map_sound(tfidf: Any) -> List[Violation]:
    """MODEL RI-5: every digest entry resolves to a row carrying that digest."""
    out: List[Violation] = []
    for digest, row in tfidf._content_to_row.items():
        if not 0 <= row < len(tfidf._chunk_meta):
            out.append(f"digest {digest} points at row {row}, out of range")
        elif tfidf._chunk_meta[row].content_hash != digest:
            out.append(
                f"digest {digest} points at row {row} carrying "
                f"{tfidf._chunk_meta[row].content_hash}"
            )
    return out


def rr1_pattern_derived(conn: Any) -> List[Violation]:
    """MODEL RI-R1: the record store's `pattern` agrees with its address.

    `pattern` is a function of `absolute_xpath` under the generalization map
    (PROP-12.2), so storing it is a redundancy in the sense of PROP-22.4 — and
    until now one with no clause policing it, which by COR-22.5.1 means the
    illegal states were reachable and unreportable.

    This is *detection*, not prevention (COR-22.5.1): the check reports a stale
    pattern, it does not stop one being written. See MODEL §8.1 for the
    elimination analysis and its measured cost.
    """
    from vertiscope.core.xpath_utils import generalize_xpath

    rows = conn.execute(
        "SELECT instance_id, pattern, absolute_xpath FROM instances"
    ).fetchall()
    return [
        f"{r['instance_id']}: stored {r['pattern']!r}, "
        f"derived {generalize_xpath(r['absolute_xpath'])!r}"
        for r in rows
        if r["pattern"] != generalize_xpath(r["absolute_xpath"])
    ]


ALL_CLAUSES = {
    "RI-1": ri1_matrix_shape,
    "RI-2": ri2_identifiers_unique,
    "RI-3": ri3_df_derived,
    "RI-4": ri4_meta_aligned,
    "RI-5": ri5_digest_map_sound,
}

#: Clauses over the record store. Kept separate because they take a connection
#: rather than the index, and because MODEL treats the two interpretations as
#: distinct (§8) with their own coherence obligation between them.
RECORD_CLAUSES = {
    "RI-R1": rr1_pattern_derived,
}

#: The components each clause reads, in the sense of THEORY Definition 22.7: a
#: clause is invariant under changes to every component outside its read-set.
#:
#: PROP-22.8 then bounds which clauses a mutation can falsify — those whose
#: read-set meets the mutated components — and COR-22.9 says that is all the
#: firing set identifies. Recording read-sets is what makes the bound usable;
#: the clause statements alone do not carry them.
READS = {
    "RI-1": {"_tf", "_chunk_ids", "_vocab"},
    "RI-2": {"_chunk_ids", "_chunk_id_to_row"},
    "RI-3": {"_tf", "_df"},
    "RI-4": {"_chunk_meta", "_chunk_ids"},
    "RI-5": {"_content_to_row", "_chunk_meta"},
}


def clauses_reading(components: set[str]) -> set[str]:
    """The clauses PROP-22.8 permits a mutation of ``components`` to falsify."""
    return {
        name for name, reads in READS.items()
        if reads & components
    }


def check_all(tfidf: Any) -> dict[str, List[Violation]]:
    """Every clause, keyed by name. Empty lists throughout means RI holds."""
    return {name: fn(tfidf) for name, fn in ALL_CLAUSES.items()}


def holds(tfidf: Any) -> bool:
    return not any(check_all(tfidf).values())


# ---------------------------------------------------------------------------
# The address-trie stores
# ---------------------------------------------------------------------------
#
# `FreqMatrix`, `GraphStore` and the `Workspace` coupling them arrived after
# MODEL.md was written, so they had no representation invariant at all — while
# the store they replaced had five clauses and a mutation suite. The asymmetry
# was the gap: the newer components hold more state and more of it is derived,
# which by PROP-22.4 is exactly what makes an invariant necessary rather than
# tautological.
#
# Named F-* (frequency), G-* (graph) and W-* (the coupling), so a violation
# report says which representation is wrong without needing the clause text.


def f1_rows_and_index_agree(freq: Any) -> List[Violation]:
    """F-1: `rows` and `_row_of` are mutual inverses.

    Two encodings of one bijection. Keeping both is a stored redundancy
    (PROP-22.4) and this clause is what pays for it: a disagreement means a
    chunk id resolves to another chunk's vector, and every score computed from
    it is silently attributed to the wrong page.
    """
    out: List[Violation] = []
    # An empty entry is a tombstone: a retired row, kept so that the rows
    # after it are not renumbered. It is legal and is not in `_row_of`.
    expected = {cid: i for i, cid in enumerate(freq.rows) if cid}
    if freq._row_of != expected:
        wrong = [k for k in set(expected) | set(freq._row_of)
                 if expected.get(k) != freq._row_of.get(k)]
        out.append(f"{len(wrong)} identifier(s) map to the wrong row: {wrong[:5]}")
    live = [cid for cid in freq.rows if cid]
    if len(set(live)) != len(live):
        out.append("repeated chunk identifiers in `rows`")
    return out


def f2_counts_align_with_rows(freq: Any) -> List[Violation]:
    """F-2: exactly one term-count dict per row."""
    if len(freq._counts) != len(freq.rows):
        return [f"{len(freq._counts)} count dict(s) for {len(freq.rows)} row(s)"]
    return []


def f3_vocabulary_is_a_contiguous_range(freq: Any) -> List[Violation]:
    """F-3: the vocabulary's column indices are exactly 0..n-1.

    A gap leaves an all-zero column that idf still divides by; a duplicate
    makes two terms share a column, merging their evidence without merging
    the terms.
    """
    out: List[Violation] = []
    columns = sorted(freq.vocab.values())
    if columns != list(range(len(columns))):
        out.append(f"vocabulary columns are not 0..{len(columns) - 1}")
    if len(set(freq.vocab.values())) != len(freq.vocab):
        out.append("two terms share a column")
    return out


def f4_counts_stay_inside_the_vocabulary(freq: Any) -> List[Violation]:
    """F-4: every column named by a row exists in the vocabulary."""
    ceiling = len(freq.vocab)
    for i, counts in enumerate(freq._counts):
        stray = [c for c in counts if not 0 <= c < ceiling]
        if stray:
            return [f"row {i} names column(s) outside the vocabulary: {stray[:5]}"]
    return []


def f5_document_frequency_is_derivable(freq: Any) -> List[Violation]:
    """F-5: cached `df` equals the count recomputed from the rows.

    `df` is a corpus aggregate (PROP-14.6), so the cache is a redundancy.
    Stale `df` does not raise; it quietly rescales every idf.
    """
    if freq._df is None:
        return []
    cached = list(freq._df)
    freq._df = None
    fresh = list(freq.document_frequency())
    freq._df = None
    if len(cached) != len(fresh):
        return [f"cached df has {len(cached)} entries, recomputed has {len(fresh)}"]
    differing = [i for i, (a, b) in enumerate(zip(cached, fresh)) if a != b]
    if differing:
        return [f"{len(differing)} stale df entry/entries: columns {differing[:5]}"]
    return []


FREQ_CLAUSES = {
    "F-1": f1_rows_and_index_agree,
    "F-2": f2_counts_align_with_rows,
    "F-3": f3_vocabulary_is_a_contiguous_range,
    "F-4": f4_counts_stay_inside_the_vocabulary,
    "F-5": f5_document_frequency_is_derivable,
}


def g1_every_chunk_belongs_to_a_page(store: Any) -> List[Violation]:
    """G-1: no chunk is orphaned from the page it was scanned from."""
    known = {r[0] for r in store._rows(
        "MATCH (:Page)-[:HasChunk]->(c:Chunk) RETURN c.cid")}
    orphans = [r[0] for r in store._rows("MATCH (c:Chunk) RETURN c.cid")
               if r[0] not in known]
    return [f"{len(orphans)} chunk(s) with no page: {orphans[:5]}"] if orphans else []


def g2_anchors_resolve(store: Any) -> List[Violation]:
    """G-2: every anchored address carries a key.

    An anchor pointing at an empty address is a retrieval hit that cannot be
    traced back to the document — the one thing the address scheme exists to
    guarantee.
    """
    dangling = store._rows(
        "MATCH (c:Chunk)-[:Anchors]->(a:Address) WHERE a.akey = '' "
        "RETURN c.cid LIMIT 6")
    return [f"{len(dangling)} anchor(s) to an empty address"] if dangling else []


def g3_chunk_rows_are_unique(store: Any) -> List[Violation]:
    """G-3: two chunks never claim the same frequency-matrix row.

    The row is the join key across all three vector factors, so a collision
    scores one chunk with another's vector — and both look plausible.
    """
    seen: dict = {}
    clashes = []
    for cid, row in store._rows("MATCH (c:Chunk) RETURN c.cid, c.row"):
        if row is None or int(row) < 0:
            continue
        if int(row) in seen:
            clashes.append((int(row), seen[int(row)], cid))
        seen[int(row)] = cid
    return [f"{len(clashes)} row(s) claimed by several chunks: {clashes[:3]}"] \
        if clashes else []


def g4_addresses_agree_with_their_keys(store: Any) -> List[Violation]:
    """G-4: an address's stored parts match its canonical key.

    The key is the authority and the parts are its decomposition, so storing
    both is a redundancy this clause polices (PROP-22.4).
    """
    from .address import ContentAddress

    for aid, akey, url, xpath, tag, accessor in store._rows(
            "MATCH (a:Address) RETURN a.aid, a.akey, a.url, a.xpath, a.tag, "
            "a.accessor LIMIT 500"):
        try:
            parsed = ContentAddress.parse(akey)
        except ValueError:
            return [f"{aid}: stored key does not parse"]
        if (parsed.url, parsed.xpath, parsed.tag, parsed.accessor) != \
                (url, xpath, tag, accessor):
            return [f"{aid}: stored parts disagree with the key"]
        if parsed.aid != aid:
            return [f"{aid}: identifier is not the digest of its key"]
    return []


GRAPH_CLAUSES = {
    "G-1": g1_every_chunk_belongs_to_a_page,
    "G-2": g2_anchors_resolve,
    "G-3": g3_chunk_rows_are_unique,
    "G-4": g4_addresses_agree_with_their_keys,
}


def w1_graph_and_matrix_hold_the_same_chunks(workspace: Any) -> List[Violation]:
    """W-1: the graph's chunks and the matrix's rows are the same set.

    The coupling invariant, and the reason `Workspace.ingest` is the only
    write path: a chunk in the graph with no row is unrankable, and a row with
    no chunk ranks something that cannot be displayed.
    """
    out: List[Violation] = []
    in_graph = {c.cid for c in workspace.store.chunks()}
    # Tombstones are retired rows and belong to neither side.
    in_matrix = {cid for cid in workspace.freq.rows if cid}
    missing, extra = in_graph - in_matrix, in_matrix - in_graph
    if missing:
        out.append(f"{len(missing)} chunk(s) with no frequency row: "
                   f"{sorted(missing)[:3]}")
    if extra:
        out.append(f"{len(extra)} frequency row(s) with no chunk: "
                   f"{sorted(extra)[:3]}")
    return out


def w2_stored_rows_match_the_matrix(workspace: Any) -> List[Violation]:
    """W-2: the row each chunk records is the row the matrix issued."""
    out: List[Violation] = []
    for chunk in workspace.store.chunks():
        actual = workspace.freq.row_of(chunk.cid)
        if actual is not None and chunk.row != actual:
            out.append(f"{chunk.cid}: graph says row {chunk.row}, matrix {actual}")
            if len(out) >= 5:
                break
    return out


WORKSPACE_CLAUSES = {
    "W-1": w1_graph_and_matrix_hold_the_same_chunks,
    "W-2": w2_stored_rows_match_the_matrix,
}


def check_freq(freq: Any) -> dict[str, List[Violation]]:
    return {name: fn(freq) for name, fn in FREQ_CLAUSES.items()}


def check_graph(store: Any) -> dict[str, List[Violation]]:
    return {name: fn(store) for name, fn in GRAPH_CLAUSES.items()}


def check_workspace(workspace: Any) -> dict[str, List[Violation]]:
    """Every clause over a workspace: the matrix, the graph, and the coupling."""
    out = check_freq(workspace.freq)
    out.update(check_graph(workspace.store))
    out.update({name: fn(workspace) for name, fn in WORKSPACE_CLAUSES.items()})
    return out


# --- the two copies of the HTML-AAM tables -----------------------------------


def a1_aam_tables_agree(_: Any = None) -> List[Violation]:
    """`vertiscope/aam.py` and `sensor.js` classify identically.

    The mapping has to exist on both sides of the bridge: Python renders and
    the fold classifies in the page, and neither can call the other. Two
    copies of a table is tolerable where two copies of *logic* is not —
    provided the copies are checked rather than trusted, which is what this
    is. Parsed out of the JS source rather than executed, so it costs nothing
    and needs no browser.

    A divergence here is the failure mode that would be hardest to see
    otherwise: the sensor would draw a control one way, the offline path
    another, and every comparison between them would silently measure the
    disagreement instead of the thing under test.
    """
    import json
    import pathlib
    import re

    from . import aam

    src = (pathlib.Path(__file__).parent / "core" / "js" / "sensor.js")
    try:
        text = src.read_text(encoding="utf-8")
    except OSError as exc:  # noqa: BLE001
        return [f"cannot read sensor.js: {exc}"]

    out: List[Violation] = []
    for name, expected in (("IMPLICIT_ROLE", aam.IMPLICIT_ROLE),
                           ("INPUT_ROLE", aam.INPUT_ROLE),
                           ("RENDER_CLASS", aam.RENDER_CLASS)):
        m = re.search(r"var %s = (\{.*?\});" % name, text, re.S)
        if m is None:
            out.append(f"{name} missing from sensor.js")
            continue
        try:
            found = json.loads(m.group(1))
        except ValueError as exc:  # noqa: BLE001
            out.append(f"{name} in sensor.js is not readable json: {exc}")
            continue
        for key in sorted(set(expected) | set(found)):
            if expected.get(key) != found.get(key):
                out.append(
                    f"{name}[{key!r}]: python={expected.get(key)!r} "
                    f"js={found.get(key)!r}")
    return out


# --- the two copies of the composed-tree walk --------------------------------

# Where each walk lives, and the pattern that isolates it. Two copies of a
# *table* is tolerable when they are checked; two copies of a *walk* is worse,
# so this is the check.
_COMPOSED_WALKS = {
    "sensor.js/composedKids": (("core", "js", "sensor.js"),
                               r"function composedKids\(.*?\n  \}"),
    # The independent copy. Ground truth exists to say what the fold missed, so a
    # ground truth that repeats the fold's mistake agrees with it perfectly
    # and measures nothing -- precisely the failure this invariant was
    # written for, now with one more place for it to occur.
    "analytics/groundtruth kidsOf": (("analytics", "groundtruth.py"),
                                     r"function kidsOf\(.*?\n\}"),
}


def c1_composed_walks_resolve_slots(sources: Any = None) -> List[Violation]:
    """Both walks descend the tree the browser draws, not ``childNodes``.

    There are two of them — the fold in ``sensor.js`` and the analytics
    ground truth — and they are checked against each other for the same
    reason the AAM tables are. (A third lived in the REPL's `coverage`
    command; that was measurement rather than browsing and moved out to
    `vertiscope/analytics`, which is where its walk lives now.) The coverage walk exists to say what the fold missed, so a
    coverage walk that repeats the fold's mistake reports 100% of a page that
    neither of them read; the agreement is the measurement, and two walks that
    are wrong in the same way agree perfectly.

    Three properties, each naming a bug that was there:

    * assignment is resolved (``assignedNodes({flatten: true})``) — without it
      a light child of a shadow host is read where it is *written* rather than
      where it is *drawn*, which reorders every component on the page;
    * assigned nodes displace the fallback instead of joining it — without it
      every filled slot contributes text no reader can ever see;
    * a shadow host's own ``childNodes`` are not walked beside its shadow root
      — they are reached through the slot that claims them, and walking both
      emits the same content twice.

    Read out of the sources rather than executed, like ``a1``: it needs no
    browser, and the regression it guards is a walk being quietly returned to
    the simple one, which is a textual change. Pass ``sources`` as a
    ``{name: text}`` mapping to check something other than the files on disk.

    claim: CONTENT_EXTRACTION_RULES 8.4 — shadow content is addressable in the
    same space as light content, which requires it to be in the same *order*.
    """
    import pathlib
    import re

    here = pathlib.Path(__file__).parent
    given = dict(sources or {})
    out: List[Violation] = []
    text_of: dict = {}

    for name, (parts, pattern) in _COMPOSED_WALKS.items():
        if name in given:
            text = given[name]
        else:
            path = here.joinpath(*parts)
            try:
                text = path.read_text(encoding="utf-8")
            except OSError as exc:  # noqa: BLE001
                out.append(f"cannot read {path.name}: {exc}")
                continue
        text_of[name] = text
        m = re.search(pattern, text, re.S)
        if m is None:
            out.append(f"{name}: the composed-children walk is gone")
            continue
        body = m.group(0)
        if "assignedNodes" not in body:
            out.append(f"{name}: does not resolve slot assignment")
        if "flatten" not in body:
            out.append(f"{name}: assignedNodes without flatten — a slot "
                       f"assigned to a slot resolves to the slot itself")
        # Assigned or fallback, never both. Both copies spell it the same
        # way: return the assigned nodes when there are any, fall through to
        # childNodes when there are not.
        if not re.search(r"if \(an && an\.length\)", body):
            out.append(f"{name}: does not prefer assigned nodes over fallback")

    text = text_of.get("sensor.js/composedKids")
    if text is None:
        return out
    m = re.search(r"function childrenOf\(.*?\n  \}", text, re.S)
    if m is None:
        out.append("sensor.js: childrenOf is gone")
        return out
    body = m.group(0)
    if "composedKids(" not in body:
        out.append("sensor.js/childrenOf: does not go through composedKids, "
                   "so it is walking childNodes directly")
    # The shadow branch has to *return*. Falling out of it into the host's own
    # light children is the original bug: they were appended after the shadow
    # root's children, so slotted content came back a second time, in a
    # position the page never draws it in.
    _head, marker, tail = body.partition("if (node.shadowRoot)")
    if not marker:
        out.append("sensor.js/childrenOf: no shadow-root branch at all")
    else:
        ret = tail.find("return kids;")
        light = min((i for i in (tail.find("node.childNodes"),
                                 tail.find("composedKids(")) if i >= 0),
                    default=-1)
        if ret < 0 or (0 <= light < ret):
            out.append("sensor.js/childrenOf: the shadow branch falls through "
                       "to the host's own children — slotted content is "
                       "emitted twice, once where the page never draws it")
    return out


# Functions in sensor.js allowed to read layout, and why each one is not the
# fold. Anything else that measures is a violation by construction.
_LAYOUT_READERS = {
    # The style peripheral. Reading geometry is its entire job, it is called
    # from Python with an explicit address list, and it never runs during a
    # drain -- which is what keeps geometry out of the trie.
    "styles",
    # The box peripheral (G-90): the host calls it after a drain, in the same
    # round trip, for the chunks that drain named -- never during the fold.
    "boxes",
    # The hover peripheral (D-35): which chunk draws the element under the
    # pointer, and its box -- on a hover, never during a drain.
    "at",
    "runBox",
    # The picture peripheral: the largest rendered image in a chunk's run.
    "pictures",
    # The pushed hover: a passive pointer listener reading the box of the
    # chunk under the pointer, once a frame -- never the fold.
    "onPointer",
    # The actuator. `step` has to know what is on screen before it scrolls,
    # and it runs once per step rather than once per node.
    "inView",
    "atBottom",
    # The `viewport` variant, and only under its flag. This one is on the
    # emission walk, so it is listed here rather than allowed silently -- see
    # the docstring below for what that costs and what it does not.
    "emitChunks",
}

_LAYOUT_CALLS = (
    r"getBoundingClientRect|getClientRects|getComputedStyle"
    r"|\.offset(?:Top|Left|Width|Height)"
    r"|\.client(?:Top|Left|Width|Height)"
    r"|\.scroll(?:Top|Left|Width|Height)"
)


def c2_fold_reads_no_layout(source: Any = None) -> List[Violation]:
    """The fold measures nothing. Geometry is a peripheral, not a field.

    The load-bearing claim is that folding a mutation costs a digest and a map
    write -- never a measurement. A single ``getBoundingClientRect`` inside
    ``fold`` forces synchronous layout per mutated node, and the O(delta)
    number stops being about the fold and starts being about the browser's
    layout engine.

    This asserts it textually rather than trusting it, because the regression
    is one line long and looks harmless at the call site. Every layout-reading
    call in ``sensor.js`` must sit in one of ``_LAYOUT_READERS``; anything
    else -- most of all ``fold`` itself or a helper it calls -- is reported.

    A correction is recorded here, because the wrong version of this claim was
    believed for a while: ``fold`` does *not* read layout and never did. The
    read that was mistaken for it is in ``emitChunks``, on the emission walk
    that follows the fold, under the ``viewport`` flag alone. That is a real
    cost -- with ``eager`` scheduling the emission walk runs inside the
    MutationObserver callback, so ``viewport + eager`` measures layout, not
    folding -- but it is not this invariant being broken, and "the fold reads
    no layout" holds as written.

    Pass ``source`` to check text other than the file on disk.

    claim: the O(delta) fold is a catamorphism over content, and content is
    what the DOM says, not what the layout engine computes from it.
    """
    import pathlib
    import re

    if source is None:
        path = pathlib.Path(__file__).parent / "core" / "js" / "sensor.js"
        try:
            source = path.read_text(encoding="utf-8")
        except OSError as exc:  # noqa: BLE001
            return [f"cannot read sensor.js: {exc}"]

    out: List[Violation] = []
    calls = re.compile(_LAYOUT_CALLS)
    where = re.compile(r"^  function (\w+)", re.M)

    current = "<module scope>"
    seen_any = False
    for line in source.splitlines():
        named = where.match(line)
        if named:
            current = named.group(1)
        if not calls.search(line):
            continue
        seen_any = True
        if current not in _LAYOUT_READERS:
            out.append(f"sensor.js/{current}: reads layout — "
                       f"{line.strip()[:60]}")

    # Non-vacuity: a pattern that matches nothing would pass this silently
    # forever, and a renamed API is exactly how that happens.
    if not seen_any:
        out.append("sensor.js: no layout call found at all — either the "
                   "peripheral is gone or the pattern no longer matches it")
    return out


# ---------------------------------------------------------------------------
# C-3: a projection may not key reuse on the move-tolerant hash
# ---------------------------------------------------------------------------

_PROJECTIONS = ("markdown.py", "wireframe.py")


def code_tokens(source: str) -> List[Tuple[int, str]]:
    """(line, name) for every identifier in ``source``, comments and strings
    dropped.

    A clause of the form "this module may not reach X" is a claim about
    *capability*, and capability lives in code. Scanning raw text made two
    such clauses fire on documentation instead: one on a docstring explaining
    which of the two Merkles a projection must not key on, another on the word
    "re-embedding" in a sentence about why a boundary matters. Both were
    correct sentences and neither granted anything.

    Dropping strings as well as comments is deliberate and does not weaken the
    check: a banned name inside a string literal cannot be called or imported.
    What survives is exactly what the module can reach.
    """
    import io as _io
    import tokenize

    out: List[Tuple[int, str]] = []
    try:
        for tok in tokenize.generate_tokens(_io.StringIO(source).readline):
            if tok.type == tokenize.NAME:
                out.append((tok.start[0], tok.string))
            elif tok.type == tokenize.OP:
                out.append((tok.start[0], tok.string))
    except (tokenize.TokenError, IndentationError, SyntaxError):
        # An unparseable module cannot be cleared by this clause, but it also
        # cannot be scanned; fall back to the raw text so a violation is
        # reported rather than silently passed.
        return [(i, line) for i, line in enumerate(source.splitlines(), 1)]
    return out


def c3_projections_key_on_exact_hash(sources: Any = None) -> List[Violation]:
    """A projection memo keys on ``exact_hash``, never on ``subtree_hash``.

    The trie carries two Merkles over every subtree because two consumers ask
    two different questions of it:

    * ``subtree_hash`` folds in ``content_hash``, the hash of a normalized
      token multiset. It is blind to word order, case and punctuation, and
      that blindness is the point -- it is what lets ``apply`` recognise a
      paragraph that moved rather than minting a new identity for it.
    * ``exact_hash`` folds in the exact value and the full address. Equality
      means the subtree *draws* identically.

    A projection prints values verbatim, so it must key reuse on the second.
    Keyed on the first, ``"gamma beta"`` edited to ``"beta gamma"`` leaves the
    hash unchanged and the reader is served the old word order indefinitely --
    a wrong page, which is worse than a slow one, and one that no timing or
    coverage number would show.

    Asserted textually because the failure is a one-word substitution at a
    call site where either name reads as plausible.

    Pass ``sources`` as ``{filename: text}`` to check text other than disk.

    claim: reuse is sound exactly when the equivalence it is keyed on refines
    the equality the consumer needs.
    """
    import pathlib

    if sources is None:
        here = pathlib.Path(__file__).parent
        sources = {}
        for name in _PROJECTIONS:
            try:
                sources[name] = (here / name).read_text(encoding="utf-8")
            except OSError:
                continue          # wireframe may draw without its own memo
        if not sources:
            return ["no projection source readable"]

    out: List[Violation] = []
    seen_exact = False
    for name, text in sources.items():
        for number, token in code_tokens(text):
            if token == "subtree_hash":
                out.append(f"{name}:{number}: projection reads subtree_hash")
            elif token == "exact_hash":
                seen_exact = True

    # Non-vacuity: if no projection keys on anything, this clause is checking
    # that an absent memo is absent, which is not a property worth asserting.
    if not seen_exact:
        out.append("no projection keys reuse on exact_hash — either the memo "
                   "is gone or this clause no longer finds it")
    return out


def c4_repl_and_analytics_stay_apart(sources: Any = None) -> List[Violation]:
    """The REPL is a browser; the analytics measure it. Neither imports the other.

    The standing constraint is that analytics live in ``vertiscope/analytics/`` and
    write their own artifacts, separately from the REPL. It was stated, and it
    was quietly not holding: ``vertiscope/repl/app.py`` carried eight class-level
    catalogues -- ``AXES``, ``LOSSY``, ``REGROUPING``, ``READDRESSING``,
    ``OVERLAPPING``, ``TARGETS``, ``QUERIES``, ``GROUND_TRUTH``, 109 lines --
    naming a design space and a benchmark corpus. Every one was defined exactly
    once and referenced nowhere, residue from removing the ``compare`` /
    ``variant`` / ``sweep`` / ``verify`` commands: deleting a command and
    deleting its vocabulary are two edits, and only the first is obvious.

    Nothing detected that for however long it sat there, because a constraint
    with no check is a preference. This is the check.

    The rule asserted here is the import boundary rather than the vocabulary,
    because the boundary is what the constraint is actually about and it is
    decidable. A REPL that needs to measure something is a REPL growing a
    second concern; an analytics module that reaches into the REPL is measuring
    the instrument instead of the page. Either direction is the same mistake.

    Vocabulary is not asserted: a word list would fail on any comment
    mentioning a mechanism, and the REPL has to be able to *describe* what it
    does. What it must not do is depend.

    Pass ``sources`` as ``{filename: text}`` to check text other than disk.

    claim: a separation of concerns is only enforced where it is decidable, and
    for two packages that is which one may name the other.
    """
    import ast
    import pathlib

    if sources is None:
        here = pathlib.Path(__file__).parent
        sources = {}
        for package in ("repl", "analytics"):
            folder = here / package
            if not folder.is_dir():
                continue
            for path in sorted(folder.glob("*.py")):
                try:
                    sources["{}/{}".format(package, path.name)] = \
                        path.read_text(encoding="utf-8")
                except OSError:
                    continue
        if not sources:
            return ["neither repl nor analytics source is readable"]

    # Which package must not be named, from inside which.
    forbidden = {"repl": "analytics", "analytics": "repl"}

    out: List[Violation] = []
    for name, text in sorted(sources.items()):
        package = name.split("/", 1)[0]
        other = forbidden.get(package)
        if other is None:
            continue
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            out.append("{}: will not parse: {}".format(name, exc))
            continue
        for node in ast.walk(tree):
            # `import vertiscope.analytics`, and its dotted forms.
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if other in alias.name.split("."):
                        out.append("{}:{} imports {}".format(
                            name, node.lineno, alias.name))
            # `from ..analytics import x`, `from vertiscope.analytics import x`,
            # and the relative forms the package actually uses.
            elif isinstance(node, ast.ImportFrom):
                if node.module and other in node.module.split("."):
                    out.append("{}:{} imports from {}".format(
                        name, node.lineno, node.module))
                elif node.module is None or node.level:
                    for alias in node.names:
                        if alias.name == other:
                            out.append("{}:{} imports {} itself".format(
                                name, node.lineno, other))
    return out
