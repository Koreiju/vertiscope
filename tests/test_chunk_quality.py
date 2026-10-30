"""`domvec.analytics.chunk_quality` (M-11): self-retrieval, interactive vs prose.

Non-vacuity: a search that returns the asked chunk scores 1.0; one that
returns something else scores 0; the null arm (a random other chunk) stays 0
when the search is right; a copy is answered by its lead.
"""

from domvec.analytics.chunk_quality import is_interactive, query_of, score

PROSE = "A radix tree compresses chains of single children into one edge labelled with a string."
INTER = "- [Download the data set](https://x/data.csv)\n( Sort ascending )\n[ ] Search the catalogue by title or author name"


def test_classes_and_queries():
    assert is_interactive(INTER) and not is_interactive(PROSE)
    q = query_of(INTER)
    assert "https" not in q and len(q.split()) >= 5            # the encoder's words, targets dropped
    assert query_of(PROSE).startswith("A radix tree compresses")


def test_scoring_both_arms_and_the_null():
    samples = [{"cid": "c1", "md": PROSE, "lead": ""}, {"cid": "c2", "md": INTER, "lead": "c9"}]
    right = {query_of(PROSE): ["c1"], query_of(INTER): ["c9"]}       # c2 answered by its lead
    good = score(samples, lambda q, k: right[q], null_pool=["c1", "c2", "c7"])
    assert good["recall"] == 1.0 and good["null_recall"] <= 0.5
    bad = score(samples, lambda q, k: ["zz"])
    assert bad["recall"] == 0.0


def test_an_equivalent_chunk_counts_as_equivalent_not_strict():
    samples = [{"cid": "c1", "md": PROSE, "lead": ""}]
    other = {"c8": PROSE}                                   # the same words on another page
    got = score(samples, lambda q, k: ["c8"], text_of=lambda cids: [other.get(c, "") for c in cids])
    assert got["recall"] == 0.0 and got["equivalent_recall"] == 1.0
    wrong = score(samples, lambda q, k: ["c9"], text_of=lambda cids: ["something else entirely"])
    assert wrong["equivalent_recall"] == 0.0
