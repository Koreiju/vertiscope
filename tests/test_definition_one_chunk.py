"""A definition -- heading, lead, list -- is ONE chunk, and a formula is said once.

Reported by the user on 2026-09-26 from Wikipedia's *Suffix tree*: the
"Definition" heading, the first four list items and the fifth came out as
three separate chunks "despite being part of the same definition".
`fixtures/suffix_definition.html` is that section, taken from the live page in
the browser cell.

Two causes, both in the markdown projection, and one test each:

* **Math was said five times.** MediaWiki ships a formula as MathML glyphs, a
  TeX annotation and a fallback image with the TeX as alt text, plus its own
  ``data-mw`` JSON: one inline symbol became five or six lines and 40-60
  tokens, so a short list overflowed the window.
* **Prose passed as records.** The record rule's composite test ("holds an
  element") is true of any paragraph with a link in it, so a run of
  paragraphs -- and a list whose items carried inline math -- became one
  chunk per item, flushed apart from the heading they belong to.

Planted arms put each cause back and must split the definition again.
"""

from pathlib import Path

import vertiscope.markdown as md
from vertiscope import tokens
from vertiscope.markdown import render_trie
from vertiscope.stream import StreamingScan

HTML = (Path(__file__).parent / "fixtures" / "suffix_definition.html").read_text(encoding="utf-8")
URL = "https://en.wikipedia.org/wiki/Suffix_tree"
ITEMS = ("The tree has exactly", "Except for the root", "Each edge is labelled",
         "No two edges", "The string obtained by concatenating")


def _chunks():
    scan = StreamingScan(URL, context_window=256)
    return render_trie(scan.push(HTML, passno=0).trie, context_window=256)


def _holding(chunks, text):
    return [i for i, c in enumerate(chunks) if text in c.markdown]


def test_the_definition_is_one_chunk():
    chunks = _chunks()
    where = {t: _holding(chunks, t) for t in ("## Definition", "is defined as a tree such that") + ITEMS}
    assert all(len(v) == 1 for v in where.values()), where
    assert len({v[0] for v in where.values()}) == 1, where
    one = chunks[where["## Definition"][0]]
    assert tokens.budget(one.markdown) <= md.LENIENCY * 256


def test_a_formula_is_said_once():
    text = "\n".join(c.markdown for c in _chunks())
    assert "{\\displaystyle" not in text
    assert '"name":"math"' not in text
    assert "$S[i..n]$" in text


def test_planted_formula_noise_splits_it(monkeypatch):
    monkeypatch.setattr(md, "_collapse_math", lambda units: units)
    chunks = _chunks()
    holders = {i for t in ITEMS for i in _holding(chunks, t)}
    assert len(holders | set(_holding(chunks, "## Definition"))) > 1


def test_planted_loose_composite_test_splits_it(monkeypatch):
    monkeypatch.setattr(md, "_INLINE_TAGS", frozenset())
    chunks = _chunks()
    holders = {i for t in ("## Definition", "is defined as a tree such that") + ITEMS
               for i in _holding(chunks, t)}
    assert len(holders) > 1
