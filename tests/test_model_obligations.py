"""Mechanical discharge of the obligations in notes/proposals/MODEL.md.

These are not regression tests. Each asserts a commuting condition or a
representation-invariant clause stated in MODEL, and cites the THEORY result it
rests on. A failure here means the interpretation is wrong, the implementation
diverged, or the theorem does not apply — and PROCESS §4.1 requires the
diagnosis to say which.
"""

import json

from vertiscope.core.global_tfidf_store import _tokens
from vertiscope.ingest import ingest
from vertiscope.pipeline import run_pipeline

URL = "https://riverside.example/catalog"
OTHER = "https://riverside.example/other"


def _ingest(store, html, url=URL):
    return ingest(store, run_pipeline(html, url))


# --- representation invariant (MODEL §4) --------------------------------------


def test_ri_shape_and_alignment(store, catalog_html):
    """RI clauses 1, 2, 4: matrix shape, identifier uniqueness, meta alignment."""
    _ingest(store, catalog_html)
    tf = store.tfidf

    rows, cols = tf._tf.shape
    assert rows == len(tf._chunk_ids), "RI-1: tf rows must equal identifier count"
    assert cols == len(tf._vocab), "RI-1: tf columns must equal vocabulary size"
    assert len(set(tf._chunk_ids)) == len(tf._chunk_ids), "RI-2: identifiers repeat"
    assert tf._chunk_id_to_row == {c: i for i, c in enumerate(tf._chunk_ids)}, \
        "RI-2: identifier-to-row map does not invert the identifier sequence"
    assert len(tf._chunk_meta) == len(tf._chunk_ids), "RI-4: meta misaligned"


def test_ri_df_is_derived_from_the_matrix(store, catalog_html):
    """RI clause 3 — the load-bearing one.

    claim: PROP-14.3

    MODEL §5a: df is *derived*, not independent abstract data. RI-3 is that
    constraint transported to the concrete side: df[j] must equal the number of
    rows nonzero in column j, recomputed from the matrix rather than trusted.
    """
    _ingest(store, catalog_html)
    tf = store.tfidf

    recomputed = (tf._tf > 0).sum(axis=0).A1
    stored = tf._df[: tf._tf.shape[1]]
    mismatches = [
        (j, int(stored[j]), int(recomputed[j]))
        for j in range(tf._tf.shape[1])
        if int(stored[j]) != int(recomputed[j])
    ]
    assert not mismatches, f"RI-3 violated in {len(mismatches)} column(s): {mismatches[:5]}"


def test_ri_digest_map_points_at_matching_rows(store, catalog_html):
    """RI clause 5: every digest entry resolves to a row carrying that digest."""
    _ingest(store, catalog_html)
    tf = store.tfidf
    for digest, row in tf._content_to_row.items():
        assert 0 <= row < len(tf._chunk_meta), f"digest {digest} points off the end"
        assert tf._chunk_meta[row].content_hash == digest, \
            f"digest {digest} points at a row carrying {tf._chunk_meta[row].content_hash}"


# --- O-2: retraction under partial token overlap (MODEL §6, open) -------------


def test_retraction_is_exact_under_partial_token_overlap(store, catalog_html):
    """O-2's open case.

    claim: PROP-14.2

    PROP-14.2 gives exact removal because multiset sum is cancellative. The
    discharged case removed documents with disjoint vocabulary. This exercises
    the case MODEL flagged as open: withdrawing a document whose tokens are
    *shared* with survivors, where df must decrement only for the tokens the
    removed document contributed and must not disturb the rest.
    """
    _ingest(store, catalog_html, url=URL)
    _ingest(store, catalog_html.replace("Echelle", "Grating"), url=OTHER)
    tf = store.tfidf

    before = {t: int(tf._df[c]) for t, c in tf._vocab.items()}
    store.purge_url(OTHER)
    tf = store.tfidf

    recomputed = (tf._tf > 0).sum(axis=0).A1
    bad = [
        (t, int(tf._df[c]), int(recomputed[c]))
        for t, c in tf._vocab.items()
        if c < len(recomputed) and int(tf._df[c]) != int(recomputed[c])
    ]
    assert not bad, f"RI-3 broken by retraction for {len(bad)} token(s): {bad[:5]}"

    # df must never exceed its pre-removal value, and never go negative.
    for token, col in tf._vocab.items():
        now = int(tf._df[col])
        assert now >= 0, f"df went negative for {token!r}"
        assert now <= before.get(token, now), f"df rose for {token!r} on removal"


# --- O-5: coherence between the two interpretations (MODEL §8) ---------------


def test_indexed_rows_all_have_records(store, catalog_html):
    """O-5. The index's identifier domain must be contained in the record store's.

    An indexed row with no backing record is unresolvable: retrieval returns an
    identifier that cannot be hydrated, which is observable (search yields
    identifiers, MODEL §5b).
    """
    _ingest(store, catalog_html)
    indexed = set(store.tfidf._chunk_ids)
    recorded = {
        r["instance_id"]
        for r in store.conn.execute("SELECT instance_id FROM instances")
    }
    orphans = indexed - recorded
    assert not orphans, f"{len(orphans)} indexed row(s) with no record: {list(orphans)[:5]}"


def test_domains_are_not_equal_and_the_gap_is_empty_text(store, catalog_html):
    """O-5, stated correctly.

    MODEL §8 asserts the two domains 'agree'. They do not, and the inequality is
    deliberate: `Store.index_instances` skips instances whose rendered text is
    empty, since an unindexable row would only dilute df. So containment holds in
    one direction only, and the residue must be exactly the empty-text rows.
    """
    _ingest(store, catalog_html)
    indexed = set(store.tfidf._chunk_ids)
    rows = list(store.conn.execute(
        "SELECT instance_id, rendered_text FROM instances"))
    recorded = {r["instance_id"] for r in rows}

    residue = recorded - indexed
    for r in rows:
        if r["instance_id"] in residue:
            assert not (r["rendered_text"] or "").strip(), (
                f"record {r['instance_id']} has text but was never indexed"
            )


# --- image of the abstraction (MODEL §7.2) -----------------------------------


def test_every_indexed_vector_is_coherent(store, catalog_html):
    """MODEL §7.2: im(alpha) is restricted to coherent vectors.

    claim: PROP-13.2

    theta emits unigrams and bigrams, so a bigram entails both its unigrams. A
    row containing a bigram column without the corresponding unigram columns
    would lie outside im(theta) and so outside im(alpha) — the abstraction would
    be claiming a state no text can produce.
    """
    _ingest(store, catalog_html)
    tf = store.tfidf
    col_to_token = {c: t for t, c in tf._vocab.items()}

    matrix = tf._tf.tocsr()
    for i in range(matrix.shape[0]):
        present = {col_to_token[c] for c in matrix[i].indices if c in col_to_token}
        for token in present:
            if " " not in token:
                continue
            left, right = token.split(" ", 1)
            assert left in present and right in present, (
                f"row {i}: bigram {token!r} present without its unigrams "
                f"({left!r} in={left in present}, {right!r} in={right in present})"
            )


def test_tokenizer_emits_unigrams_and_bigrams():
    """The premise §7.2 rests on, asserted directly rather than assumed.

    claim: PROP-13.2
    """
    assert _tokens("alpha beta gamma") == [
        "alpha", "beta", "gamma", "alpha beta", "beta gamma"
    ]


# --- stored redundancy (MODEL §4.3, THEORY §22.4) ----------------------------


def test_every_clause_but_one_polices_a_stored_redundancy(store, catalog_html):
    """MODEL §4.3: four of six stored components are functions of the others.

    claim: PROP-22.4

    PROP-22.4 says an invariant of this kind is incurred by storing what could be
    derived; COR-22.5 bounds the clause count below by the number of such
    components. This reconstructs each derivation from the other components and
    requires agreement — which is what makes the component redundant, and hence
    what makes its clause eliminable rather than fundamental.
    """
    _ingest(store, catalog_html)
    t = store.tfidf

    assert {c: i for i, c in enumerate(t._chunk_ids)} == t._chunk_id_to_row, \
        "RI-2 polices _chunk_id_to_row; it is not in fact derivable from _chunk_ids"

    recomputed = (t._tf > 0).sum(axis=0).A1
    assert all(int(t._df[j]) == int(recomputed[j]) for j in range(t._tf.shape[1])), \
        "RI-3 polices _df; it is not in fact derivable from _tf"

    assert [m.chunk_id for m in t._chunk_meta] == t._chunk_ids, \
        "RI-4 polices a duplication of the identifier; the copies disagree"

    derived_c2r = {}
    for i, m in enumerate(t._chunk_meta):
        derived_c2r.setdefault(m.content_hash, i)
    assert derived_c2r == t._content_to_row, \
        "RI-5 polices _content_to_row; it is not in fact derivable from _chunk_meta"


def test_a_unified_view_makes_alignment_undenotable(store, catalog_html):
    """PROP-22.6, demonstrated rather than argued.

    claim: PROP-22.6

    Two sequences corresponding by position can be misaligned; a single sequence
    of pairs cannot. Zipping the identifier and metadata sequences produces a
    representation in which RI-4 has no falsifying state — every element carries
    its own identifier, so there is no operation that moves one without the
    other. The test asserts the tautology holds under the same mutation that
    breaks the parallel form.
    """
    _ingest(store, catalog_html)
    t = store.tfidf

    unified = list(zip(t._chunk_ids, t._chunk_meta))

    # the mutation that breaks RI-4 in the parallel representation
    t._chunk_meta[0], t._chunk_meta[1] = t._chunk_meta[1], t._chunk_meta[0]
    from vertiscope import invariants as inv
    assert inv.ri4_meta_aligned(t), "control: the parallel form must be breakable"

    # the same reordering applied to the unified form permutes whole records,
    # and each still carries its own identifier -- nothing to misalign
    unified[0], unified[1] = unified[1], unified[0]
    assert all(cid == meta.chunk_id for cid, meta in unified), \
        "a sequence of pairs admitted a misalignment, refuting PROP-22.6"


def test_record_pattern_is_derived(store, catalog_html):
    """MODEL RI-R1: the record store's stored pattern agrees with its address.

    claim: PROP-22.4

    Detection, not prevention (COR-22.5.1): this reports a stale pattern, it
    does not stop one being written. It exists because the redundancy was
    previously unpoliced, which COR-22.5.2 identifies as the worst of the three
    regimes — and the generalization map is provisional (PROP-12.4), so
    staleness is expected rather than hypothetical.
    """
    from vertiscope import invariants as inv

    _ingest(store, catalog_html)
    violations = inv.rr1_pattern_derived(store.conn)
    assert not violations, (
        f"{len(violations)} record(s) carry a pattern that is not the "
        f"generalization of their address: {violations[:3]}"
    )


def test_record_pattern_clause_is_non_vacuous(store, catalog_html):
    """RI-R1 must be able to fail, or the test above proves nothing.

    claim: PROP-22.4

    PROP-22.4(1) says the illegal region is non-empty whenever the component's
    carrier is non-trivial. This exhibits a member of it, which is also the
    state COR-22.5.2 regime 2 predicts after a revision of the generalization
    map.
    """
    from vertiscope import invariants as inv

    _ingest(store, catalog_html)
    store.conn.execute(
        "UPDATE instances SET pattern = '/html/body/stale' "
        "WHERE instance_id = (SELECT instance_id FROM instances LIMIT 1)")
    store.conn.commit()
    violations = inv.rr1_pattern_derived(store.conn)
    assert len(violations) == 1, (
        f"expected exactly one divergent record, got {len(violations)} — "
        f"the clause does not localise"
    )


def test_identity_depends_on_the_provisional_map(store, catalog_html):
    """COR-22.5.5: instance_id's dependency closure reaches generalize_xpath.

    claim: PROP-22.5.4

    This asserts the *dependency*, not its absence. The dependency is the
    finding: `instance_id = sha1(url | pattern | content_hash)` and
    `pattern = generalize_xpath(address)`, so by PROP-22.5.4 a revision of the
    map invalidates every identifier whose pattern changes — measured at 65.4%
    in notes/observations/2026-08-09-identity-blast-radius.md.

    If identity is ever decoupled from the map (the remedy COR-22.5.5 implies),
    this test fails and the observation, MODEL §3.3 and ERRATA must be revisited
    rather than silently left stale.
    """
    import hashlib

    _ingest(store, catalog_html)
    row = store.conn.execute(
        "SELECT instance_id, pattern, html_raw FROM instances LIMIT 1").fetchone()

    content_hash = hashlib.sha1((row["html_raw"] or "").encode()).hexdigest()[:8]
    recomputed = hashlib.sha1(
        f"inst|{URL}|{row['pattern']}|{content_hash}".encode()).hexdigest()[:20]
    assert recomputed == row["instance_id"], (
        "instance_id is no longer sha1(url|pattern|content_hash) — the "
        "dependency on the generalization map may have changed; re-measure the "
        "blast radius before assuming COR-22.5.5 still applies"
    )

    # and it is injective in pattern, which is what makes 22.5.5 bite
    altered = hashlib.sha1(
        f"inst|{URL}|/html/body/other|{content_hash}".encode()).hexdigest()[:20]
    assert altered != row["instance_id"], "identity is not injective in pattern"


# --- identity collapse and multiplicity (THEORY §22.5.6) ---------------------


def test_written_count_equals_rows_actually_present(store, catalog_html):
    """The report must count rows, not records offered.

    claim: THM-22.5.7

    Records sharing an identifier collapse to one row — forced by THM-22.5.7,
    since a content-keyed identifier cannot distinguish content-identical
    siblings. `upsert_instances` previously returned len(records), which
    over-reported by exactly the collapse (9.2% on a real page).
    """
    report = _ingest(store, catalog_html)
    rows = store.conn.execute("SELECT COUNT(*) c FROM instances").fetchone()["c"]
    assert report.instances_written == rows, (
        f"report claims {report.instances_written} written, store holds {rows}"
    )
    assert (report.instances_rendered
            == report.instances_written + report.instances_collapsed), \
        "rendered must account for exactly written plus collapsed"


def test_collapse_is_currently_lossy(store, catalog_html):
    """REM-22.5.9: collapsing identical siblings is lossless iff count is kept.

    claim: REM-22.5.9

    It is not kept. This asserts the *absence* of a multiplicity column, so the
    day one is added the test fails and MODEL §8.3, the observation and ERRATA
    are revisited rather than left stale. Asserting the gap is how a known,
    unremedied loss stays visible.
    """
    _ingest(store, catalog_html)
    cols = {d[1] for d in store.conn.execute("PRAGMA table_info(instances)")}
    assert "multiplicity" not in cols and "occurrence_count" not in cols, (
        "a multiplicity column now exists — collapse may be lossless; "
        "update THEORY REM-22.5.9's application in MODEL §8.3"
    )


# --- the observation alphabet (DOMAIN §9.8.1, THEORY §10.4) -------------------


def test_position_escapes_through_exactly_one_surface(store, catalog_html):
    """DOMAIN §9.8.1: position is observable, and only via `vertiscope show`.

    claim: COR-10.7

    COR-10.7 says adding an output is a semantic change: enlarging the
    observation alphabet refines observational equivalence and can invalidate an
    equality that held. Position's observability is what makes content-identical
    siblings distinguishable, hence (COR-22.5.8) what makes stability and
    discrimination incompatible.

    So this asserts the *shape* of the alphabet, not merely that things work: if
    a future change prints `absolute_xpath` from search, the identity analysis in
    MODEL §8.3 changes and must be revisited rather than silently invalidated.
    """
    import io
    from contextlib import redirect_stdout

    from vertiscope import cli
    from vertiscope.retrieve import Retriever

    _ingest(store, catalog_html)
    hit = Retriever(store).search("echelle spectrograph", k=1)[0]
    rec = store.get_instance(hit.instance_id)
    assert rec is not None and rec.absolute_xpath

    def emitted(argv):
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                cli.main(["--home", str(store.cfg.home)] + argv)
        except SystemExit:
            pass
        return buf.getvalue()

    assert rec.absolute_xpath in emitted(["show", hit.instance_id]), \
        "`show` no longer exposes position — DOMAIN §9.8.1 is stale"

    for argv in (["search", "echelle", "-k", "3"],
                 ["search", "echelle", "-k", "3", "--json"],
                 ["ls"]):
        assert rec.absolute_xpath not in emitted(argv), (
            f"`{' '.join(argv)}` now exposes position. The observation alphabet "
            f"has grown (COR-10.7); re-derive MODEL §8.3 before accepting this."
        )


def test_ranking_is_independent_of_insertion_order(store, catalog_html):
    """MODEL §4.1's quotient by row permutation, enforced rather than assumed.

    claim: PROP-10.8

    Ordering by score alone leaves ties resolved by row index, which makes
    insertion order observable (COR-10.9) — the same corpus inserted in a
    different order returned equally-scoring hits in a different order, which
    falsified §4.1's quotient and with it every obligation stated up to it.

    Breaking ties on chunk_id makes the ranking factor through the quotient
    (PROP-10.8), so row order cannot leak. This constructs the tie deliberately:
    two documents with disjoint vocabulary and a query matching one term in
    each, which scores them identically by symmetry.
    """
    import tempfile

    from vertiscope.core.global_tfidf_store import ChunkMeta, GlobalTfidfStore

    A, B, query = "alpha beta gamma delta", "epsilon zeta eta theta", "alpha epsilon"

    def ranked(order):
        s = GlobalTfidfStore(tempfile.mkdtemp(prefix="tie_"))
        for cid, text in order:
            s.add_chunks([text], [ChunkMeta(chunk_id=cid, url=f"u/{cid}",
                                            snapshot_id="s")])
        return [(h.chunk_id, round(h.score, 9)) for h in s.search(query, k=5)]

    forward = ranked([("first", A), ("second", B)])
    reverse = ranked([("second", B), ("first", A)])

    assert len({sc for _, sc in forward}) == 1, (
        "the tie this test depends on no longer occurs; construct another or "
        "the test proves nothing"
    )
    assert forward == reverse, (
        f"ranking depends on insertion order: {forward} vs {reverse}. Row order "
        f"is observable, so MODEL §4.1's quotient is invalid and every "
        f"obligation stated up to it is unsound."
    )


def test_json_scores_do_not_expose_layout_precision(store, catalog_html):
    """COR-10.13: an output must not report more precision than it is stable to.

    claim: COR-10.12

    Scores are a float32 sum over rows and float addition is not associative
    (PROP-10.11), so the low bits depend on row order. Emitting full precision
    made layout observable; JSON now rounds to six places, above the observed
    ~3e-8 spread.

    Asserting the rounding rather than the invariance is deliberate: the
    invariance is measured by scripts/audit_layout_sensitivity.py over many
    permutations, which is too slow for the suite. This pins the mechanism that
    delivers it, so removing the rounding fails here.
    """
    import io
    import json as _json
    from contextlib import redirect_stdout

    from vertiscope import cli

    _ingest(store, catalog_html)
    buf = io.StringIO()
    try:
        with redirect_stdout(buf):
            cli.main(["--home", str(store.cfg.home), "search", "spectrograph",
                      "-k", "5", "--json"])
    except SystemExit:
        pass
    rows = _json.loads(buf.getvalue())
    assert rows, "no hits; the test cannot check anything"
    for r in rows:
        for field in ("score", "lexical"):
            value = r[field]
            if value is None:
                continue
            assert round(value, 6) == value, (
                f"{field}={value!r} carries more than 6 decimal places — full "
                f"float precision makes storage layout observable (COR-10.12)"
            )
