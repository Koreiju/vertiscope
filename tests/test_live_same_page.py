""""This page only" has to mean this page, including for a `file://` fixture.

`Page(query)` ranks through the three-form index and then keeps the hits that
belong to the page in front of you. The first version of that filter compared
`canonical_url(hit.url)` against `canonical_url(session.url)`.

`canonical_url` returns the EMPTY STRING for any scheme that is not http or
https. That is deliberate and documented -- it exists so link targets can
match, and a `file://` uri has no canonical http form. But it makes the
comparison `"" == ""`, which is true of every pair, so the filter returned
hits from every page in the store while claiming to be scoped to one.

The shape of the bug is the reason this file exists: it would have worked on
a live site and failed on every fixture, so it was broken exactly where the
tests run and correct exactly where they do not.

No browser needed. This is a question about two strings.
"""

from vertiscope.live import same_page


# --- the case that was broken ------------------------------------------------


def test_two_different_file_uris_are_two_pages():
    assert not same_page("file:///c:/x/live_start.html",
                         "file:///c:/x/live_target.html")


def test_the_same_file_uri_is_the_same_page():
    assert same_page("file:///c:/x/live_start.html",
                     "file:///c:/x/live_start.html")


def test_a_fragment_does_not_make_a_second_page():
    """The graph's Page node is the document; a fragment addresses a position
    inside one. `canonical_url` drops it for http, so the fallback must too or
    the two paths disagree about what a page is."""
    assert same_page("file:///c:/x/a.html#top", "file:///c:/x/a.html")


# --- and the case that already worked ----------------------------------------


def test_http_pages_still_compare_canonically():
    assert same_page("https://a.test/p", "https://a.test/p")
    assert not same_page("https://a.test/p", "https://a.test/q")


def test_a_campaign_tag_does_not_make_a_second_page():
    """What canonicalisation is for: the identifier whoever sent you attached
    changes nothing the page says."""
    assert same_page("https://a.test/p?utm_source=x", "https://a.test/p")


def test_a_query_that_names_the_document_does(  ):
    """And what it is not for. `?q=...` IS the document on a results page,
    which is the case this whole interface navigates through."""
    assert not same_page("https://duckduckgo.com/?q=ice",
                         "https://duckduckgo.com/?q=glaciers")


# --- non-vacuity -------------------------------------------------------------


def test_mixed_schemes_are_not_the_same_page():
    """One side canonicalises to "" and the other does not. Falling back on
    the raw strings has to keep them apart rather than let the empty side
    match anything."""
    assert not same_page("file:///c:/x/a.html", "https://a.test/a.html")


def test_empty_is_not_a_wildcard():
    assert not same_page("", "https://a.test/p")
    assert not same_page("file:///c:/x/a.html", "")
