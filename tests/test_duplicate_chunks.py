"""`G-24`/`G-25`: the same rendering at many addresses is one thing to look at.

archive.org renders each search result as a `<tile-dispatcher>` custom element
with its own shadow root, and every one of those roots carries the same
accessibility hint -- so 125 distinct addresses drew one string and the
projector drew 125 identical nodes. The trie is right to hold all 125; the
question is how many of them are *content*.

`_dedupe` cannot answer it. It is element-scoped: it groups units by
`addr.xpath` and compares only within a group, so identical content at
different xpaths has never been compared to itself.
"""

import pytest

from vertiscope.graphstore import StoredChunk, _same_content


class _Chunk:
    """Only what `_same_content` reads."""

    def __init__(self, cid, markdown):
        self.cid = cid
        self.markdown = markdown


HINT = "Press Down Arrow to preview item details"


def test_the_copies_point_at_one_chunk():
    tiles = [_Chunk("tile%d" % i, HINT) for i in range(125)]
    canonical, copies = _same_content(tiles)

    assert len(canonical) == 124, "every copy but the first is redundant"
    assert set(canonical.values()) == {"tile0"}, "they point at one chunk"
    assert copies == {"tile0": 125}, "and it knows how many it stands for"
    assert "tile0" not in canonical, "the canonical is nobody's copy"


def test_distinct_chunks_are_left_alone():
    """The non-vacuity arm: a rule that collapsed everything would pass above.

    Without this, `_same_content` could return "all one group" and the first
    test would read as a success.
    """
    chunks = [_Chunk("a", "one"), _Chunk("b", "two"), _Chunk("c", "three")]
    canonical, copies = _same_content(chunks)
    assert canonical == {}, "nothing here is a copy of anything"
    assert copies == {}, "and nothing stands for more than itself"


def test_a_near_miss_is_not_a_duplicate():
    """Exact bytes, which is the whole reason this stage needs no threshold.

    Two tiles differing by one character are two chunks here. Recognising them
    as one is `G-26`, over the embeddings, deliberately a separate stage.
    """
    chunks = [_Chunk("a", HINT), _Chunk("b", HINT + "."), _Chunk("c", HINT)]
    canonical, _ = _same_content(chunks)
    assert canonical == {"c": "a"}, "only the byte-identical pair merged"


def test_order_decides_which_one_keeps_the_content():
    """Document order, so the verdict does not move between two equal scans."""
    for _ in range(3):
        canonical, _ = _same_content(
            [_Chunk("x", HINT), _Chunk("y", HINT), _Chunk("z", HINT)])
        assert canonical == {"y": "x", "z": "x"}


@pytest.mark.parametrize("dup_of,expected", [("", False), ("other", True)])
def test_stored_chunk_reports_the_verdict(dup_of, expected):
    chunk = StoredChunk(cid="c", url="u", xpath="/x", part=0, md=HINT,
                        chars=len(HINT), line_count=1, row=0,
                        dup_of=dup_of, dup_n=1)
    assert chunk.redundant is expected


def test_a_store_written_before_the_columns_existed_reads_as_distinct():
    """The default matters: NULL must not make every old chunk a copy.

    Stores on disk predate `dup_of`/`dup_n`. Kuzu answers NULL for both, and a
    reader that took NULL at face value would give every chunk in them a copy
    count of None -- so the defaults are asserted rather than assumed.
    """
    chunk = StoredChunk(cid="c", url="u", xpath="/x", part=0, md=HINT,
                        chars=len(HINT), line_count=1, row=0)
    assert chunk.redundant is False
    assert chunk.dup_n == 1
