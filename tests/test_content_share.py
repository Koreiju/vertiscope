"""PLUGIN_GOAL 59: retrieval weighs boilerplate below content (`search.content_share`)."""

from domvec.search import content_share


def test_prose_is_content():
    assert content_share("The adaptive radix tree is a radix tree variant that integrates adaptive node sizes.") == 1.0


def test_language_lists_and_nav_links_are_boilerplate():
    md = ("- [Okapi – Malay Okapi Bahasa Melayu](https://ms.wikipedia.org/wiki/Okapi)\n"
          "- [Okapi – Dutch Okapi Nederlands](https://nl.wikipedia.org/wiki/Okapi)\n"
          "[View the content page [alt-c] Article](/wiki/Radix_tree)")
    assert content_share(md) == 0.0


def test_a_search_box_holding_the_query_is_boilerplate():
    # DuckDuckGo's own results page: its field echoes the query, its toolbar buttons.
    assert content_share("( button Private )\n[ ] patricia trie\n( Clear search input )\nSettings") == 0.0


def test_headings_and_images_count_neither_way():
    assert content_share("### Implementations\n![logo](a.png)\nA radix tree stores keys by their shared prefixes.") == 1.0


def test_mixed_chunks_score_between():
    s = content_share("Home\n[Books](/books)\nA tale of two cities is a historical novel published in 1859, by Charles Dickens.")
    assert 0.5 < s < 1.0


def test_nothing_is_not_boilerplate():
    assert content_share("") == 1.0


# --- the echo, end to end (2026-11-15, PLUGIN_GOAL 163) ----------------------
#
# The reader's screenshot: a search engine's results page holding the query in
# its field and its "related searches" ranked above the code that defines the
# word, at content share 0.0, because additive fusion made content a 0.25 term.

import pytest

from domvec import search as S
from domvec.obsidian.sidecar import search_payload
from domvec.workspace import Workspace

import re as _re

import numpy as np


class _WordsEmbedder:
    """Hashed bag of words: a page that repeats the query is nearest to it in
    meaning as in words, as the live encoder put the echo (semantic 0.78)."""

    dim = 768

    def embed_texts(self, texts, **_kw):
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for i, text in enumerate(texts):
            for word in _re.findall(r"[a-z]+", str(text).lower()):
                out[i, sum(map(ord, word)) * 7919 % self.dim] += 1.0
        return out

    def embed_query(self, text):
        return self.embed_texts([text])[0]


QUERY = "unionRect xpaths sensor resolver"

ECHO = ("<html><body><main><form><input type='text' value='%s'><button>Search</button></form>"
        "<ul><li><a href='/q1'>unionRect xpaths</a></li><li><a href='/q2'>sensor resolver</a></li>"
        "<li><a href='/q3'>unionRect sensor</a></li><li><a href='/q4'>xpaths resolver</a></li></ul>"
        "</main></body></html>") % QUERY

ARTICLE = ("<html><body><main><p>The pipeline box measures its panels with unionRect, which takes the "
           "bounding rectangle of every element the sensor resolver kept, so the outline covers the "
           "whole row and never a part of it.</p></main></body></html>")


@pytest.mark.parametrize("planted", [False, True])
def test_a_page_echoing_the_query_ranks_below_one_that_says_it(tmp_path, monkeypatch, planted):
    monkeypatch.setattr(S, "PLANT_ADDITIVE_CONTENT_TERM", [planted])
    with Workspace(tmp_path / "ws", embedder=_WordsEmbedder()) as w:
        w.index_html(ECHO, "https://search.test/?q=unionRect")
        w.index_html(ARTICLE, "https://notes.test/pipeline")
        w.flush_vectors()
        hits = search_payload(w, QUERY, 5, where="all")["hits"]
    urls = [h["url"] for h in hits]
    assert "https://search.test/?q=unionRect" in urls and "https://notes.test/pipeline" in urls, hits
    echo = next(h for h in hits if h["url"].startswith("https://search.test/"))
    assert echo["content"] < 0.2, echo
    if planted:
        assert urls[0] == "https://search.test/?q=unionRect", hits
    else:
        assert urls[0] == "https://notes.test/pipeline", hits


@pytest.mark.parametrize("planted", [False, True])
def test_the_trace_shows_each_stage_and_agrees_with_the_ranking(tmp_path, monkeypatch, planted):
    """G-372 step 1: `search_payload(trace=k)` returns each stage's own
    ranking. On the echo: lexical and semantic put the echo first, content
    puts the article first, and the trace's `fuse` order IS the hits' order
    in both arms -- planted, the old additive term flips both together."""
    monkeypatch.setattr(S, "PLANT_ADDITIVE_CONTENT_TERM", [planted])
    with Workspace(tmp_path / "ws", embedder=_WordsEmbedder()) as w:
        w.index_html(ECHO, "https://search.test/?q=unionRect")
        w.index_html(ARTICLE, "https://notes.test/pipeline")
        w.flush_vectors()
        got = search_payload(w, QUERY, 5, where="all", trace=5)
        url_of = {h["cid"]: h["url"] for h in got["hits"]}
        url_of.update({c: w.store.chunk(c).url for st in ("lexical", "semantic", "content", "fuse")
                       for c, _v in got["trace"][st] if w.store.chunk(c)})
    t = got["trace"]
    first = lambda stage: url_of[t[stage][0][0]]
    assert first("lexical") == first("semantic") == "https://search.test/?q=unionRect", t
    assert first("content") == "https://notes.test/pipeline", t
    assert [c for c, _v in t["fuse"]][:len(got["hits"])] == [h["cid"] for h in got["hits"]], (t["fuse"], got["hits"])
    assert t["overlap"]["shared"] >= 1 and t["shape"] == [h["cid"] for h in got["hits"]]
    assert first("fuse") == ("https://search.test/?q=unionRect" if planted else "https://notes.test/pipeline")


def test_no_trace_unless_asked(tmp_path):
    with Workspace(tmp_path / "ws", embedder=_WordsEmbedder()) as w:
        w.index_html(ARTICLE, "https://notes.test/pipeline")
        w.flush_vectors()
        assert "trace" not in search_payload(w, QUERY, 5)


SERP_Q = "radix trie lookup"
_FILL = ("Each node stores a label shared by every key below it, so a long run of keys with one "
         "prefix costs one edge instead of one node per character, and the walk compares whole "
         "labels against the remaining key before it descends. ") * 12
SERP = ("<html><body><main>"
        "<article><h2>Radix tree - Wikipedia</h2><p>In computer science a radix trie lookup walks one edge "
        "per key fragment. " + _FILL + "</p></article>"
        "<article><h2>Patricia trees explained</h2><p>" + _FILL + "</p></article>"
        "</main><footer><p>No more results found for radix trie lookup</p></footer></body></html>")


@pytest.mark.parametrize("planted", [False, True])
def test_a_results_page_saying_the_query_back_is_not_a_result(tmp_path, monkeypatch, planted):
    """Live 2026-11-15: DuckDuckGo's "No more results found for <query>" ranked
    first. The page was made from the query (every word in its url's `q`), the
    chunk says the query and little else: dropped at shape, counted. Its
    snippet, which quotes the phrase among real content, stays. Planted
    `PLANT_NO_ECHO_RULE`: the echo is kept."""
    import domvec.obsidian.sidecar as sc
    monkeypatch.setattr(sc, "PLANT_NO_ECHO_RULE", [planted])
    url = "https://duckduckgo.com/?q=radix+trie+lookup&ia=web"
    with Workspace(tmp_path / "ws", embedder=_WordsEmbedder()) as w:
        w.index_html(SERP, url)
        w.index_html(ARTICLE, "https://notes.test/pipeline")
        w.flush_vectors()
        got = search_payload(w, SERP_Q, 5, where="all")
    previews = [h["preview"] for h in got["hits"] if h["url"] == url]
    echo = [p for p in previews if "No more results" in p]
    snippet = [p for p in previews if "walks one edge" in p]
    assert snippet, got["hits"]
    if planted:
        assert echo and got["echoes"] == 0
    else:
        assert not echo and got["echoes"] == 1, got


def test_a_page_not_made_from_the_query_is_never_an_echo(tmp_path):
    """The same words on a page whose url does not carry them: kept."""
    with Workspace(tmp_path / "ws", embedder=_WordsEmbedder()) as w:
        w.index_html(SERP, "https://notes.test/radix")
        w.flush_vectors()
        got = search_payload(w, SERP_Q, 5, where="all")
    assert got["echoes"] == 0
    assert any("No more results" in h["preview"] for h in got["hits"]), got["hits"]


def test_a_prefix_typed_mid_word_is_still_an_echo(tmp_path):
    """The field searches per keystroke: "radix trie loo" against a page made
    from "radix trie lookup" is the same echo."""
    url = "https://duckduckgo.com/?q=radix+trie+lookup&ia=web"
    with Workspace(tmp_path / "ws", embedder=_WordsEmbedder()) as w:
        w.index_html(SERP, url)
        w.flush_vectors()
        got = search_payload(w, "radix trie loo", 5, where="all")
    assert got["echoes"] == 1, [h["preview"][:300] for h in got["hits"]]
    assert not any("No more results" in h["preview"] for h in got["hits"])


#: The live echo chunk, as the store holds it (cid 951dc741, 2026-11-15).
LIVE_ECHO_URL = "https://duckduckgo.com/?q=unionRect%20xpaths%20sensor%20resolver%20shadow%20roots&ia=web"
LIVE_ECHO_MD = "\n".join([
    "No more results found for unionRect xpaths sensor resolver shadow roots",
    "Suggestions: - Check spelling",
    "  - Try related keywords",
    "  Try asking Duck.ai , our private AI chat service: /?q=unionRect+xpaths+sensor+resolver+shadow+roots&ia=chat",
    "    [ ] Ask Duck.ai anything",
    "      [ ] unionRect xpaths sensor resolver shadow roots"])


@pytest.mark.parametrize("query,echo", [
    ("unionRect xpa", True),                         # the reader's keystroke query, live
    ("unionRect xpaths sensor resolver shadow roots", True),
    ("sensor resolver", True),                       # a phrase of the query the page was made from
    ("unionRect pipeline", False),                   # "pipeline" is not in the url's query
])
def test_the_live_echo_chunk(query, echo):
    from types import SimpleNamespace
    from domvec.obsidian.sidecar import _echoes
    assert _echoes(SimpleNamespace(url=LIVE_ECHO_URL, md=LIVE_ECHO_MD), query) is echo


def test_a_snippet_quoting_the_query_on_the_same_page_is_not_an_echo():
    from types import SimpleNamespace
    from domvec.obsidian.sidecar import _echoes
    md = ("unionRect - MDN. The unionRect xpaths sensor resolver shadow roots example computes the "
          "smallest rectangle containing two DOMRects; it is used to outline every element a selection "
          "covers, and the result is recomputed whenever the layout changes or an element scrolls.")
    assert not _echoes(SimpleNamespace(url=LIVE_ECHO_URL, md=md), "unionRect xpa")
