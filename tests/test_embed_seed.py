"""P-N6: an edited note is re-embedded by its DIFF -- across a restart too.

The embed gate (`VectorQueue.digests`) is memory only and a cid is keyed on
position, so a fresh queue knew nothing and re-embedded every chunk of the
first note edited after a restart. `seed` teaches it the store's own embedded
markdown; `PLANT_REEMBED_ALL` takes the gate away.
"""

from domvec import vectors
from domvec.vectors import VectorQueue


def test_seeded_unchanged_chunk_is_skipped():
    q = VectorQueue()
    assert q.seed([("a", "# Cell\n\nprint(1)", "vault://v/n.md"), ("b", "two", "vault://v/n.md")]) == 2
    assert q.push("a", "# Cell\n\nprint(1)", url="vault://v/n.md") is False
    assert q.push("b", "two, edited", url="vault://v/n.md") is True
    assert (q.skipped, q.queued) == (1, 1)


def test_seed_learns_only_unknown_cids():
    q = VectorQueue()
    q.push("a", "pending text")
    assert q.seed([("a", "other", ""), ("c", "x", "")]) == 1


def test_seed_compares_the_text_the_model_is_given():
    # A code chunk is embedded without its code (G-52): the digest must be
    # taken the same way, or a seeded code chunk never matches.
    q = VectorQueue()
    md = "Docstring words.\n\n```python\ndef f():\n    return 1\n```"
    q.seed([("k", md, "code://repo/x.py")])
    assert q.push("k", md, url="code://repo/x.py") is False


def test_planted_gate_off_reembeds_everything():
    q = VectorQueue()
    q.seed([("a", "same", "")])
    vectors.PLANT_REEMBED_ALL[0] = True
    try:
        assert q.push("a", "same") is True
    finally:
        vectors.PLANT_REEMBED_ALL[0] = False
