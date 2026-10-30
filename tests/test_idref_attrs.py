"""ID-reference attributes are not text (M-11, 2026-10-30).

`aria-describedby="link-aria-description"` names the element whose words
describe this one; read as text, archive.org's tiles carried the id into
13,575 chunks' labels and embeddings. Planted `PLANT_IDREF_TEXT`: as before.
"""

from domvec.core import content_tagger as T
from domvec.pipeline import run_pipeline

HTML = ("<html><body><div><a href='/details/audio' aria-describedby='link-aria-description'"
        " aria-labelledby='logoTitleID'>Audio Books</a>"
        "<span id='link-aria-description'>Opens the collection</span></div></body></html>")


def _text(html):
    """What is DRAWN (the chunks' markdown) and ADDRESSED (the trie's values)
    -- not the result's repr, which carries the input html."""
    got = run_pipeline(html, "https://t.test/p", render=True)
    import json
    drawn = json.dumps([c.as_dict() for c in (got.chunks or [])], default=str)
    return drawn + chr(10) + repr(got.tagged)


def test_an_id_reference_is_not_drawn_as_words():
    out = _text(HTML)
    assert "link-aria-description" not in out and "logoTitleID" not in out
    assert "Audio Books" in out and "Opens the collection" in out      # the words, where they live


def test_planted_id_reference_read_as_text_again():
    T.PLANT_IDREF_TEXT[0] = True
    try:
        assert "link-aria-description" in _text(HTML)
    finally:
        T.PLANT_IDREF_TEXT[0] = False
