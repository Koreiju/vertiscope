"""R-C5: a single line longer than the window is split, not kept whole.

Approved 2026-11-08 ("Re-key chunk trie" ruling, "and split over-long single
lines"). The bar in PLUGIN_PRD is `worst_overflow_ratio` <= 1.5x; a run made
of one over-window line used to be its own chunk at any size.
"""
from domvec import markdown as md
from domvec import tokens
from domvec.address import ContentAddress


def _line(text, depth=1):
    return md.MarkdownLine(depth=depth, text=text,
                           address=ContentAddress("https://ex.test/", "/html/body/p", "text", "own"))


def _long_text(words=3000):
    return " ".join("word%d" % i for i in range(words)) + " [a link with spaces](https://ex.test/a) tail"


def test_an_over_window_line_becomes_pieces_within_the_window():
    window = 512
    line = _line(_long_text())
    assert tokens.budget(line.render()) > 4 * window
    chunk = md.MarkdownChunk(url="https://ex.test/", xpath="/html/body/p")
    chunk.lines.append(line)
    out = []
    md._emit_runs(chunk, window, out)
    worst = max(tokens.budget(c.render()) if hasattr(c, "render") else
                sum(tokens.budget(l.render()) for l in c.lines) for c in out)
    assert len(out) > 4
    assert worst <= window * 1.5, worst
    # Every piece keeps the line's address: each resolves to the element.
    assert all(l.address.whole() == line.address for c in out for l in c.lines)
    # ...and the pieces PARTITION: no address key in two places.
    keys = [k for c in out for k in c.anchors]
    assert len(keys) == len(set(keys))
    # Nothing lost, nothing reordered: the words read back in order.
    joined = " ".join(l.text for c in out for l in c.lines)
    assert joined.split() == line.text.split()
    # A link is never cut inside.
    assert any("[a link with spaces](https://ex.test/a)" in l.text for c in out for l in c.lines)


def test_planted_the_line_stays_whole():
    window = 512
    line = _line(_long_text())
    md.PLANT_NO_LINE_SPLIT = True
    try:
        assert md._split_long_line(line, window) == [line]
    finally:
        md.PLANT_NO_LINE_SPLIT = False
    assert len(md._split_long_line(line, window)) > 1


def test_a_line_within_the_window_is_untouched():
    line = _line("a short line of prose")
    assert md._split_long_line(line, 512) == [line]


def test_one_giant_atom_is_cut_by_characters():
    line = _line("data:" + "A" * 40000)
    pieces = md._split_long_line(line, 512)
    assert len(pieces) > 1
    assert "".join(p.text for p in pieces) == line.text
    assert max(tokens.budget(p.render()) for p in pieces) <= 512 * 1.5


def test_the_store_anchors_every_piece_in_line_order(tmp_path):
    """A piece has no trie leaf, so the store must write its sub-address, or
    its anchor edge is dropped and the chunk's lines pair with the wrong
    addresses (lines and anchors are zipped BY POSITION)."""
    from domvec.workspace import Workspace
    url = "https://ex.test/long"
    para = " ".join("word%d" % i for i in range(1500))
    html = "<html><body><h1>Title</h1><p>%s</p><p>after</p></body></html>" % para
    with Workspace(tmp_path / "ws", context_window=128) as ws:
        ws.index_html(html, url)
        ws.settle()
        chunks = list(ws.store.chunks(url))
        pieced = 0
        for c in chunks:
            got = ws.store.addresses_of(c.cid)
            lines = [l for l in (c.md or "").split("\n") if l.strip()]
            assert len(got) == len(lines), (c.cid, len(got), len(lines))
            pieced += sum(1 for a, _v in got if a.whole() != a)
        assert pieced > 0, "no piece reached the store"
