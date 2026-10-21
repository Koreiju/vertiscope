"""Benchmark invariants over the frozen corpus of 54 structurally varied pages.

Every property here was previously checked against one hand-written fixture.
ERRATA C7 records the consequence: the fixture cannot exhibit phenomena real
pages do, so a green suite was silent rather than reassuring. These run the same
theory-grounded metrics as `scripts/benchmark.py` over the whole corpus.

Two kinds of assertion, deliberately distinguished:

* **holds** — the property is true on every page, and a regression fails.
* **pinned** — the property is *false* on real pages and the current extent is
  fixed, so neither a regression nor an unnoticed improvement passes silently.
  A pinned bound is a recorded defect, not an accepted one; each names its
  ERRATA entry.

Marked slow: the corpus is 13.7 MB and a full pass takes ~30 s.
"""

import json
import pathlib
import tempfile

import pytest

from vertiscope import invariants as inv
from vertiscope.config import load_config
from vertiscope.ingest import ingest
from vertiscope.pipeline import run_pipeline
from vertiscope.store import Store

CORPUS = pathlib.Path(__file__).parent / "corpus"
MANIFEST = CORPUS / "manifest.json"

pytestmark = pytest.mark.skipif(
    not MANIFEST.exists(),
    reason="frozen corpus absent; run scripts/fetch_corpus.py",
)


def _pages():
    pages = [p for p in json.loads(MANIFEST.read_text())["pages"] if p.get("ok")]
    return [p for p in pages if (CORPUS / f"{p['slug']}.html").exists()]


SLUGS = [p["slug"] for p in _pages()]


@pytest.fixture(scope="module")
def corpus_metrics():
    """Run the pipeline once per page; every test reads these."""
    out = []
    for p in _pages():
        html = (CORPUS / f"{p['slug']}.html").read_text(
            encoding="utf-8", errors="replace")
        result = run_pipeline(html, p["url"])
        cfg = load_config(tempfile.mkdtemp(prefix="corpus_"))
        with Store(cfg) as st:
            report = ingest(st, result)
            ri = {k: len(v) for k, v in inv.check_all(st.tfidf).items() if v}
            rr1 = len(inv.rr1_pattern_derived(st.conn))
            indexed = set(st.tfidf._chunk_ids)
            recorded = {r["instance_id"] for r in
                        st.conn.execute("SELECT instance_id FROM instances")}
            col = {c: t for t, c in st.tfidf._vocab.items()}
            matrix = st.tfidf._tf.tocsr()
            incoherent = 0
            for i in range(matrix.shape[0]):
                present = {col[c] for c in matrix[i].indices if c in col}
                for tok in present:
                    if " " in tok:
                        left, right = tok.split(" ", 1)
                        if left not in present or right not in present:
                            incoherent += 1
                            break
        out.append({
            "page": p["slug"], "url": p["url"],
            "rendered": len(result.instances),
            "stored": report.instances_written,
            "collapsed": report.instances_collapsed,
            "ri": ri, "rr1": rr1, "incoherent": incoherent,
            "containment": indexed <= recorded,
            "empty_html": sum(1 for i in result.instances
                              if not (i.html_raw or "").strip()),
        })
    return out


@pytest.fixture(scope="module")
def by_slug(corpus_metrics):
    return {m["page"]: m for m in corpus_metrics}


def test_corpus_is_large_and_varied(corpus_metrics):
    """The corpus must be big enough for the claims made over it.

    Raised from 50/35 when the corpus reached 136 pages across 109 hosts. A
    floor the corpus has doubled past constrains nothing, and would go on
    passing through a fetch that quietly lost half of it.
    """
    assert len(corpus_metrics) >= 100, (
        f"only {len(corpus_metrics)} pages; re-run scripts/fetch_corpus.py"
    )
    domains = {m["url"].split("/")[2] for m in corpus_metrics}
    assert len(domains) >= 70, f"only {len(domains)} distinct hosts"


# --- properties that hold ----------------------------------------------------


def test_m4_every_indexed_vector_is_coherent(corpus_metrics):
    """claim: PROP-13.3 — im(alpha) is restricted to coherent vectors."""
    bad = [(m["page"], m["incoherent"]) for m in corpus_metrics if m["incoherent"]]
    assert not bad, f"incoherent rows on {len(bad)} page(s): {bad[:3]}"


def test_m6_pattern_is_derivable_on_every_page(corpus_metrics):
    """claim: PROP-22.4 — RI-R1 over 54 pages, not one fixture."""
    bad = [(m["page"], m["rr1"]) for m in corpus_metrics if m["rr1"]]
    assert not bad, f"stored pattern diverged from address on: {bad[:3]}"


def test_m7_containment_holds_on_every_page(corpus_metrics):
    """MODEL O-5: indexed identifiers are a subset of recorded ones."""
    bad = [m["page"] for m in corpus_metrics if not m["containment"]]
    assert not bad, f"indexed rows without records on: {bad[:5]}"


def test_ingest_accounting_balances_on_every_page(corpus_metrics):
    """rendered == stored + collapsed, everywhere (ERRATA C6)."""
    bad = [m["page"] for m in corpus_metrics
           if m["rendered"] != m["stored"] + m["collapsed"]]
    assert not bad, f"accounting does not balance on: {bad[:5]}"


# --- defects, pinned at their measured extent --------------------------------


def test_ri2_failure_is_pinned(corpus_metrics):
    """PINNED DEFECT — ERRATA B10.

    The representation invariant fails on most real pages, and only clause RI-2
    (identifier uniqueness) fails. Cause: identity degenerates when `html_raw`
    is empty, since sha1("") is constant, so every empty-HTML instance sharing a
    pattern gets one identifier — and `add_chunks` appends duplicates within a
    batch rather than merging them.

    This pins both the rate and the clause. A fix must lower the rate and
    update this test; a regression that breaks a *different* clause fails here
    rather than hiding inside an existing failure.

    **Pinned as a rate, not a count.** It was `<= 50 pages`, taken against a
    54-page corpus. Growing the corpus to 136 failed the test while the defect
    was unchanged — 50/54 and 126/136 are both 92.6% — so the bound was
    measuring the corpus size. A count is the wrong shape for a pin whose
    denominator can move.
    """
    failing = [m for m in corpus_metrics if m["ri"]]
    clauses = {c for m in failing for c in m["ri"]}
    assert clauses <= {"RI-2"}, (
        f"a clause other than RI-2 now fails: {sorted(clauses - {'RI-2'})}"
    )
    rate = len(failing) / len(corpus_metrics)
    assert rate <= 0.93, (
        f"RI-2 now fails on {rate:.1%} of pages "
        f"({len(failing)}/{len(corpus_metrics)}), was 92.6% — regression"
    )
    clean = len(corpus_metrics) - len(failing)
    assert clean >= 4, f"only {clean} pages RI-clean, was 4 — regression"


def test_collapse_rate_is_pinned(corpus_metrics):
    """PINNED DEFECT — ERRATA B7/B10.

    Instances lost to shared identity. The fixture shows 0%, which is why this
    went unseen; real pages reach 87%.
    """
    rates = sorted(m["collapsed"] / max(m["rendered"], 1) for m in corpus_metrics)
    median = rates[len(rates) // 2]
    assert median <= 0.20, f"median collapse rate {median:.3f} rose above 0.20"
    assert max(rates) <= 0.90, f"worst collapse rate {max(rates):.3f} rose above 0.90"


def test_empty_html_instances_are_pinned(corpus_metrics):
    """PINNED DEFECT — ERRATA B10.

    Instances rendering to empty `html_raw` are the mechanism behind the
    identity degeneracy. They carry no content yet occupy an identifier.
    """
    total_empty = sum(m["empty_html"] for m in corpus_metrics)
    total = sum(m["rendered"] for m in corpus_metrics)
    rate = total_empty / max(total, 1)
    assert rate <= 0.15, f"empty-html instance rate {rate:.3f} rose above 0.15"


# --- per-URL metrics: one case per page, so a bad page is named ---------------
#
# The aggregate tests above catch corpus-wide regressions. These catch a single
# page regressing while the median absorbs it — "formalized metrics over each"
# means each URL carries its own verdict, not a contribution to a summary.


@pytest.mark.parametrize("slug", SLUGS)
def test_per_url_coherence(by_slug, slug):
    """M4 per page. claim: PROP-13.3"""
    m = by_slug[slug]
    assert m["incoherent"] == 0, (
        f"{slug}: {m['incoherent']} rows hold a bigram without its unigrams"
    )


@pytest.mark.parametrize("slug", SLUGS)
def test_per_url_pattern_derivable(by_slug, slug):
    """M6 per page. claim: PROP-22.4"""
    m = by_slug[slug]
    assert m["rr1"] == 0, f"{slug}: {m['rr1']} records whose pattern is stale"


@pytest.mark.parametrize("slug", SLUGS)
def test_per_url_containment_and_accounting(by_slug, slug):
    """M7 per page, plus the ingest accounting identity (ERRATA C6)."""
    m = by_slug[slug]
    assert m["containment"], f"{slug}: indexed identifiers not contained in recorded"
    assert m["rendered"] == m["stored"] + m["collapsed"], (
        f"{slug}: {m['rendered']} rendered != {m['stored']} stored "
        f"+ {m['collapsed']} collapsed"
    )


@pytest.mark.parametrize("slug", SLUGS)
def test_per_url_ri_failure_is_only_ri2(by_slug, slug):
    """PINNED per page — ERRATA B10.

    RI-2 fails on most real pages. Any *other* clause failing on any page is a
    new defect and must not hide inside the known one.
    """
    m = by_slug[slug]
    other = set(m["ri"]) - {"RI-2"}
    assert not other, f"{slug}: clause(s) {sorted(other)} failing besides RI-2"


@pytest.mark.parametrize("slug", SLUGS)
def test_per_url_collapse_within_bound(by_slug, slug):
    """PINNED per page — ERRATA B7/B10. Worst observed is 0.873."""
    m = by_slug[slug]
    rate = m["collapsed"] / max(m["rendered"], 1)
    assert rate <= 0.90, f"{slug}: collapse rate {rate:.3f} exceeds the pinned 0.90"
