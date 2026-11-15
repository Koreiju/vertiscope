"""A chunk's keyword anchors are its own distinctive words (PLUGIN_GOAL 159).

"add at least some headers or local semantic keyword anchors that go along
with the image previews on hovered nodes ... some nodes don't display enough
semantic relevance". `FreqMatrix.keywords` ranks a chunk's terms by tf-idf:
what it holds that the corpus rarely does. Planted (`plant_raw_tf`): by raw
count, where the words every chunk shares lead.
"""
from domvec.vectors import FreqMatrix

COMMON = "the results page shows the results for the page and the results " * 3


def _corpus():
    m = FreqMatrix()
    m.add("a", COMMON + " spectrograph echelle telescope dome spectrograph")
    m.add("b", COMMON + " giraffe okapi savanna")
    m.add("c", COMMON + " patricia trie radix")
    m.add("d", COMMON)
    return m


def test_keywords_are_the_chunks_own_distinctive_words():
    got = _corpus().keywords("a", 3)
    assert got[0] == "spectrograph"
    assert set(got) <= {"spectrograph", "echelle", "telescope", "dome"}


def test_planted_raw_counts_lead_with_shared_words():
    got = _corpus().keywords("a", 3, plant_raw_tf=True)
    assert "results" in got or "the" in got or "page" in got


def test_unknown_or_empty_chunk_has_none():
    m = _corpus()
    assert m.keywords("zzz") == [] and m.keywords("d", 3) != ["spectrograph"]


def test_a_pages_keywords_span_its_chunks():
    m = _corpus()
    got = m.keywords(["a", "b"], 6)
    assert {"spectrograph", "giraffe"} <= set(got) and "the" not in got
