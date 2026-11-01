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
