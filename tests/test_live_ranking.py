"""All three forms have to rank, and the display has to show that they do.

Two separate faults, found together, and only one of them was in the ranking.

**Semantic was genuinely dead.** `Workspace` takes `embedder=None` and then
builds no embedding matrix at all, so `live.workspace()` -- which never passed
one -- produced an index whose third factor was zero on every row. A
"three-form" index was ranking on two, and the row said `s0.00` in a column
nobody reads twice.

**PageRank was never dead; the display was.** Every row printed `r0.00`, which
is `%.2f` of 0.0034 -- while the factor was ranking perfectly well, spread
0.0034 to 0.0097 over 256 chunks across 21 distinct values, on 255 edges. More
decimals only postpone it: pagerank sums to one over the corpus, so the mean
falls as 1/N and at a hundred thousand chunks any fixed width blanks again.
Shown as a multiple of the average chunk instead, which is scale-free.

The pair is worth keeping together because they look identical on the screen
and are opposite underneath: one number was lying about being alive, the other
about being dead.
"""

import numpy as np
import pytest

from vertiscope.workspace import Workspace

ICE = """<!doctype html><html><body>
<h1>Glacier mass balance</h1>
<p>Accumulation and ablation together decide whether the ice advances or
retreats over a year of measurement.</p>
</body></html>"""

BREAD = """<!doctype html><html><body>
<h1>Sourdough method</h1>
<p>The starter is fed with flour and water until it doubles, then folded
into the dough and left to prove overnight.</p>
</body></html>"""


# --- the display, which needs nothing ----------------------------------------


class _FakeIndex:
    def __init__(self, ranks):
        self.ranks = np.asarray(ranks, dtype=np.float32)


class _FakeWorkspace:
    def __init__(self, ranks):
        self.index = _FakeIndex(ranks)


@pytest.fixture
def ranked(monkeypatch):
    """Install a corpus of known pagerank values."""
    import vertiscope.live as live

    def install(ranks):
        monkeypatch.setattr(live._S, "workspace", _FakeWorkspace(ranks))
        return live._rank_str
    return install


def test_an_average_chunk_reads_as_one(ranked):
    rank_str = ranked([0.01] * 100)
    assert rank_str(0.01) == "x1.0"


def test_standing_above_average_reads_above_one(ranked):
    rank_str = ranked([0.01] * 100)
    assert rank_str(0.025) == "x2.5"


def test_a_big_corpus_does_not_blank_the_column(ranked):
    """The defect. At 256 chunks the raw mean is 0.0039 and `%.2f` prints
    0.00 for every row; at a hundred thousand it is 1e-5 and any fixed width
    does the same. The ratio is unchanged by corpus size."""
    small = ranked([1.0 / 256] * 256)(2.0 / 256)
    big = ranked([1.0 / 100000] * 100000)(2.0 / 100000)
    assert small == big == "x2.0"


def test_it_still_says_something_with_no_workspace(monkeypatch):
    """No index open: fall back to the raw share rather than dividing by a
    mean that does not exist."""
    import vertiscope.live as live

    monkeypatch.setattr(live._S, "workspace", None)
    assert live._rank_str(0.25) == "0.25"


# --- the ranking, which needs the model --------------------------------------


@pytest.fixture(scope="module")
def embedder():
    try:
        from vertiscope.core.embedding_service import get_default_service

        return get_default_service()
    except Exception as exc:                          # noqa: BLE001
        pytest.skip("nomic embedder unavailable: %s" % exc)


def _store(tmp_path, embedder=None):
    ws = Workspace(tmp_path / "ws", embedder=embedder)
    ws.index_html(ICE, "https://ice.test/mass-balance")
    ws.index_html(BREAD, "https://bread.test/sourdough")
    ws.flush_vectors()
    ws.index.build()
    return ws


def test_without_an_embedder_the_third_factor_is_zero(tmp_path):
    """What `live.workspace()` used to produce every time, and the reason
    semantic is now on by default: a missing factor is not a smaller answer,
    it is a different one."""
    ws = _store(tmp_path)
    try:
        hits = ws.search("ice", k=5)
        assert hits
        assert all(h.semantic == 0 for h in hits), [h.semantic for h in hits]
    finally:
        ws.close()


def test_with_an_embedder_the_third_factor_ranks(tmp_path, embedder):
    ws = _store(tmp_path, embedder)
    try:
        hits = ws.search("glacier ice", k=5)
        assert hits
        sem = [h.semantic for h in hits]
        assert any(s > 0 for s in sem), sem
    finally:
        ws.close()


def test_meaning_finds_what_words_cannot(tmp_path, embedder):
    """The claim the third form exists to make. The query shares no content
    word with either page; only the embedding can tell them apart."""
    ws = _store(tmp_path, embedder)
    try:
        hits = ws.search("frozen water losing volume each year", k=5)
        assert hits, "no hit at all"
        best = max(hits, key=lambda h: h.semantic)
        assert "ice.test" in best.url, [(h.url, h.semantic) for h in hits]
        assert best.lexical < 0.5, best.lexical
    finally:
        ws.close()


def test_the_embedder_is_the_real_one(embedder):
    """Not a hash-shaped stand-in. The no-mocks contract this project holds
    everywhere else applies to the factor that was missing entirely."""
    status = embedder.status()
    assert status.get("backend") == "nomic", status
    assert not status.get("fake_env"), status


# --- and the change that was actually made -----------------------------------


def test_live_workspace_loads_the_embedder_by_default(tmp_path, embedder):
    """The fix itself. `live.workspace()` called `Workspace(path)` with no
    embedder, so the session's index had no embedding matrix and every hit it
    ever returned scored zero on the third factor.

    Tested through the session rather than through `Workspace`, because
    `Workspace` was never wrong -- it does exactly what it is asked. What was
    wrong was what it was asked for.
    """
    import vertiscope.live as live

    try:
        note = live.workspace(str(tmp_path / "ws"))
        assert "semantic on" in note, note
        assert live._S.workspace.embedder is not None
        assert live._S.workspace.embeddings is not None
    finally:
        live.close()


def test_it_can_be_turned_off_deliberately(tmp_path):
    """A model load costs seconds, so refusing it must be possible -- and the
    session says which it got, because `s0.00` on every row is not something
    a reader should have to notice for themselves."""
    import vertiscope.live as live

    try:
        note = live.workspace(str(tmp_path / "ws"), semantic=False)
        assert "semantic=False" in note, note
        assert live._S.workspace.embedder is None
    finally:
        live.close()
