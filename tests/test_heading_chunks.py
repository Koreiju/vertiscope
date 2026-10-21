"""A section heading opens the chunk of what it heads (`G-143`).

2026-10-11, culinarypedia: a flat article -- `<h2><p><p><ul><table>` repeated
under one `<div>` -- chunked so that each `<h2>` and its first paragraph were
the LAST lines of the previous section's chunk, and the rest of the section
started a chunk with no heading. Planted: headings merge like any other piece.
"""

import re

import vertiscope.markdown as md
from vertiscope.markdown import render_trie
from vertiscope.stream import StreamingScan

WINDOW = 256
URL = "https://heads.test/article"


def _article(sections=8):
    body = []
    for s in range(sections):
        body.append("<h2>Section %d heading words</h2>" % s)
        for p in range(3):
            body.append("<p>%s</p>" % " ".join("word%d_%d_%d" % (s, p, w) for w in range(38)))
        body.append("<ul>%s</ul>" % "".join("<li>item %d %d of the list</li>" % (s, i) for i in range(4)))
    return "<html><body><main><article><div>%s</div></article></main></body></html>" % "".join(body)


def _chunks():
    scan = StreamingScan(URL, context_window=WINDOW)
    return render_trie(scan.push(_article(), passno=0).trie, context_window=WINDOW)


def _heading(line):
    return bool(re.match(r"#{1,6} ", line.text or ""))


def test_no_chunk_ends_on_a_heading_and_each_opens_its_section():
    chunks = _chunks()
    assert len(chunks) >= 6
    assert not any(_heading(c.lines[-1]) for c in chunks if len(c.lines) > 1)
    heads = [(i, j) for i, c in enumerate(chunks) for j, l in enumerate(c.lines) if _heading(l)]
    assert len(heads) == 8
    # Every heading but one that merged into a small preceding run opens its chunk.
    assert sum(1 for _i, j in heads if j == 0) >= 7


def test_planted_trailing_headings_is_caught(monkeypatch):
    monkeypatch.setattr(md, "PLANT_TRAILING_HEADINGS", True)
    chunks = _chunks()
    trailing = [c for c in chunks if len(c.lines) > 1 and any(_heading(l) for l in c.lines[1:])]
    # The defect: headings in the MIDDLE or at the END of another section's chunk.
    assert trailing, "the planted merge put no heading after a chunk's first line"
