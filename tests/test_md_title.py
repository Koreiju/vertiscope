"""A tagged chunk's ego node is named by its title, not its cid (PLUGIN_GOAL
159: "not sure what 'beef' ego node is about, nothing shows when it's
clicked"). `md_title` is that name: the chunk's first line with words in it,
markdown taken off -- a link's TEXT, never its url."""

from domvec.obsidian.sidecar import md_title


def test_heading_link_text_not_url():
    assert md_title("![logo](a.png)\n## [Runic magic](https://x.y/r) at Duck") == "Runic magic at Duck"


def test_search_result_link_unwrapped():
    # The DuckDuckGo row from the 159 screenshot, both bracket styles.
    assert md_title("[[Only include results for this site]](?q=okapi%20giraffe)") == "Only include results for this site"
    assert md_title("[( Only include results for this site )](( ?q=john ))") == "Only include results for this site"


def test_no_words_is_empty_so_the_caller_falls_back():
    # A cid-like token, a table rule, a bare url, nothing: no title.
    for md in ("964b28677beeff1a", "| --- | --- |", "https://en.wikipedia.org/wiki/Trie", ""):
        assert md_title(md) == "", md


def test_long_titles_are_cut():
    t = md_title("word " * 40)
    assert len(t) == 60 and t.endswith("…")


def test_planted_the_url_would_be_the_name():
    # Non-vacuity: the rule that matters is link TEXT over url. A title that
    # kept the url would carry "https" -- assert the test can see that.
    raw = "[Trie](https://en.wikipedia.org/wiki/Trie)"
    assert "https" in raw and "https" not in md_title(raw)
