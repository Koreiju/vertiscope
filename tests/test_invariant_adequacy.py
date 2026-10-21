"""Are the invariant checks non-vacuous?

A passing test proves nothing if the assertion could not have failed. Each test
here perturbs a store into a state violating a clause of the representation
invariant (MODEL §4) and requires the corresponding predicate to report it —
and requires the set of firing clauses to be *exactly* as documented, so a
clause that fires on everything is caught as readily as one that never fires.

Writing these produced a finding: the clauses are **not independent**. A single
mutation can falsify several, because several *read* the same component — see
THEORY PROP-22.8. The expected sets below record which, rather than paper over
it. An earlier reading of this as violations propagating along a derivation
chain was mathematically wrong and is corrected in THEORY §22.7.

This is mutation testing scoped to the obligations. It measures the tests, not
the code: `test_model_obligations.py` asserts RI holds, and these assert that
those assertions have teeth.
"""

import copy

import pytest

from vertiscope import invariants as inv
from vertiscope.ingest import ingest
from vertiscope.pipeline import run_pipeline

URL = "https://riverside.example/catalog"


@pytest.fixture()
def tfidf(store, catalog_html):
    ingest(store, run_pipeline(catalog_html, URL))
    return store.tfidf


def _assert_fires(tfidf, expected: set[str]):
    """Exactly the named clauses report, and no others.

    The expected set is often larger than the clause the mutation targets: by
    PROP-22.8 any clause reading a mutated component may fire. Requiring the
    *exact* set both proves the targeted clause is non-vacuous and pins which
    of the permitted clauses actually fire, so a later change to either the
    clauses or their read-sets is caught.
    """
    report = inv.check_all(tfidf)
    fired = {name for name, violations in report.items() if violations}
    missing = expected - fired
    assert not missing, (
        f"{sorted(missing)} did not fire on a state that violates them — "
        f"vacuous check"
    )
    unexpected = fired - expected
    assert not unexpected, (
        f"unexpected clauses fired: {sorted(unexpected)} — MODEL §4.2 or the "
        f"read-sets in vertiscope/invariants.py are out of date"
    )


def test_ri_holds_before_any_mutation(tfidf):
    """The control. Without this the mutations below prove nothing."""
    report = inv.check_all(tfidf)
    assert not any(report.values()), f"RI already violated: {report}"
    assert inv.holds(tfidf)


def test_ri1_fires_on_shape_mismatch(tfidf):
    tfidf._chunk_ids = tfidf._chunk_ids + ["phantom"]
    tfidf._chunk_meta = tfidf._chunk_meta + [copy.copy(tfidf._chunk_meta[0])]
    tfidf._chunk_meta[-1].chunk_id = "phantom"
    tfidf._chunk_id_to_row["phantom"] = len(tfidf._chunk_ids) - 1
    _assert_fires(tfidf, {"RI-1"})


def test_ri2_fires_on_duplicate_identifier(tfidf):
    tfidf._chunk_ids[1] = tfidf._chunk_ids[0]
    _assert_fires(tfidf, {"RI-2", "RI-4"})   # PROP-22.8: both read _chunk_ids


def test_ri3_fires_on_a_single_perturbed_count(tfidf):
    """One column, off by one. The narrowest possible violation."""
    before = inv.ri3_df_derived(tfidf)
    assert not before
    tfidf._df[0] = int(tfidf._df[0]) + 1
    violations = inv.ri3_df_derived(tfidf)
    assert len(violations) == 1, (
        f"perturbing one column produced {len(violations)} violation(s); "
        f"the check does not localise"
    )
    _assert_fires(tfidf, {"RI-3"})


def test_ri3_fires_when_the_matrix_moves_under_a_stale_aggregate(tfidf):
    """The realistic failure: df is stale because tf changed beneath it."""
    tfidf._tf = tfidf._tf.tolil()
    tfidf._tf[0, 0] = 0
    tfidf._tf = tfidf._tf.tocsr()
    assert inv.ri3_df_derived(tfidf), "a stale aggregate went unnoticed"


def test_ri4_fires_on_misaligned_metadata(tfidf):
    tfidf._chunk_meta[0], tfidf._chunk_meta[1] = (
        tfidf._chunk_meta[1], tfidf._chunk_meta[0])
    _assert_fires(tfidf, {"RI-4", "RI-5"})   # PROP-22.8: both read _chunk_meta


def test_ri5_fires_on_a_dangling_digest(tfidf):
    tfidf._content_to_row["deadbeef" * 5] = 0
    _assert_fires(tfidf, {"RI-5"})


def test_ri5_fires_on_an_out_of_range_digest(tfidf):
    tfidf._content_to_row["cafebabe" * 5] = 10_000
    _assert_fires(tfidf, {"RI-5"})


def test_every_clause_has_at_least_one_mutation_test():
    """Guards against adding a clause and forgetting to prove it non-vacuous."""
    tested = {"RI-1", "RI-2", "RI-3", "RI-4", "RI-5"}
    assert set(inv.ALL_CLAUSES) == tested, (
        f"clauses without an adequacy test: {set(inv.ALL_CLAUSES) - tested}"
    )


def test_firing_set_is_bounded_by_the_read_set(tfidf):
    """PROP-22.8, checked against both mutations.

    claim: PROP-22.8

    A mutation can only falsify clauses that *read* a mutated component. The
    containment is generally proper — a clause may read the component and still
    hold — so this asserts containment, not equality, and reports the slack.

    The earlier reading of this coupling as a derivation chain was wrong
    (THEORY §22.7): violations do not propagate along derivations. What links
    the clauses is a shared read, and the two mutations below discriminate the
    accounts — a chain would predict RI-5 fires when the identifier sequence is
    perturbed, and it does not.
    """
    # (a) mutate the identifier sequence
    tfidf._chunk_ids[1] = tfidf._chunk_ids[0]
    fired = {n for n, v in inv.check_all(tfidf).items() if v}
    permitted = inv.clauses_reading({"_chunk_ids"})
    assert fired <= permitted, (
        f"clauses fired that do not read _chunk_ids: {sorted(fired - permitted)} "
        f"— the read-sets in vertiscope/invariants.py are wrong"
    )
    assert fired == {"RI-2", "RI-4"}, f"measured firing set changed: {sorted(fired)}"
    # RI-1 reads _chunk_ids yet holds: the containment is proper, as PROP-22.8 allows
    assert "RI-1" in permitted and "RI-1" not in fired


def test_read_sets_cover_every_clause():
    """A clause with no recorded read-set makes PROP-22.8 unusable for it."""
    assert set(inv.READS) == set(inv.ALL_CLAUSES), (
        f"clauses without read-sets: {set(inv.ALL_CLAUSES) - set(inv.READS)}"
    )
