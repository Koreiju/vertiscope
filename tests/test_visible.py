"""The only independent check on recall, and the four ways it was wrong.

`resolvable` asks the page whether the trie's addresses are real. It proves
nothing about completeness: content that never entered the trie is invisible
to it. Completeness otherwise comes only from the affine arrows, against a
ground truth that walks the way the fold does -- so content *neither* side
reaches was invisible to every check this project had, and that is exactly
what was found once one existed: a text node larger than the budget was
dropped rather than split, taking whole RFCs with it.

`visible` compares what a reader sees against what the trie holds **using no
addresses at all**, so an addressing mistake cannot hide a miss. `innerText`
is computed by layout rather than by anyone's walk.

Being independent did not make it right. Four corrections, each making the map
look broken, each caught by reading samples before a figure was reported:

    59% "missing"   a visible line required to appear contiguously in one
                    trie value -- but `innerText` lines are layout-joined runs
                    across several elements
    51% "missing"   an unseen *word* count divided by a *line* count
    ~4% "missing"   punctuation stripped inside a token rather than split on,
                    turning `Title:Language` into a word existing nowhere
    130 of 138      the concatenation check gated at 24 characters, a
                    Latin-shaped assumption: Arabic words are short and two
                    joined read as one ordinary word

All four are planted here, with the guards that keep the check able to fail.
"""

from vertiscope.analytics.visible import _run_blob, _tokens, score_visible


def blob_of(*values):
    return _run_blob(values)


# --- what a word is ----------------------------------------------------------


def test_punctuation_splits_a_token_rather_than_vanishing_from_it():
    """`innerText` joins a label span and a heading with no space. Stripping
    the colon *inside* the token made `titlelanguage`, which exists nowhere
    and is therefore missing by construction."""
    assert _tokens("Title:Language Models") == ["title", "language", "models"]


def test_short_words_are_dropped():
    """They occur in any haystack by chance and prove nothing either way."""
    assert _tokens("a an the of cat") == ["the", "cat"]


def test_case_is_not_content():
    assert _tokens("Physics") == _tokens("physics")


# --- lines are not the unit ---------------------------------------------------


def test_a_layout_joined_line_is_matched_word_by_word():
    """arxiv renders "Search Submit Donate Log in" as one line from four
    separate links. Requiring that line to appear contiguously in one trie
    value asks the trie to reproduce the browser's line breaking."""
    out = score_visible(["Search Submit Donate Login"],
                        ["Search", "Submit", "Donate", "Login"])
    assert out["unseen"] == 0


def test_the_report_counts_words_not_lines():
    """The summary divided an unseen word count by a line count and reported
    51% where the word figure was a few percent."""
    out = score_visible(["alpha beta gamma delta"], ["alpha beta"])
    assert out["lines"] == 1
    assert out["words"] == 4
    assert out["unseen"] == 2
    assert out["recall"] == 0.5


# --- concatenation without a separator ---------------------------------------


def test_a_run_of_joined_words_is_not_missing_content():
    """A navbox of links arrives from `innerText` as one run of letters."""
    assert "newtoneinsteinmaxwell" in blob_of("newton", "einstein", "maxwell")


def test_a_superscript_joined_to_its_unit_is_not_missing():
    """`km<sup>2</sup>` reads as `km2`. The trie holds `km` and `2` as
    separate text nodes, correctly. A word-set segmentation could not consume
    this, because a one-character token is not a word -- 246 misses on one
    page, every one the superscript in an area column."""
    assert "km2" in blob_of("Area (km", "2", "): 468.0")


def test_the_check_is_not_gated_on_length():
    """The gate was set at 24 characters on the reasoning that anything
    longer is not a word -- and Arabic words are short, so two joined make
    thirteen characters and read as one. 133 of 138 misses on one page were
    that shape and never reached the check written for them."""
    out = score_visible(["appliedphysics"], ["applied", "physics"])
    assert out["unseen"] == 0


def test_a_machine_value_does_not_join_a_readers_run():
    """The run is asked of what the page draws as text. A link's target sits
    between its own words and the next element's, so `Bookmarks Extensions`
    reads as one run for a reader and as
    `bookmarks` + `httpsxtestextension` + `extensions` in the trie -- 216 of
    one corpus page's 216 unseen words were an href wedged into a sentence."""
    values = ["Bookmarks", "https://x.test/extension", "Extensions"]
    drawn = ["Bookmarks", "Extensions"]
    assert score_visible(["BookmarksExtensions"], values,
                         drawn=drawn)["unseen"] == 0
    # ...and with the machine value spliced in, the run is not there.
    assert "bookmarksextensions" not in blob_of(*values)


def test_presence_is_still_asked_of_every_value():
    """Only adjacency narrows to drawn text. A word held in an attribute is
    still held, and reporting it missing would be a different error."""
    out = score_visible(["chromodynamics quantum"],
                        ["chromodynamics quantum"], drawn=[])
    assert out["unseen"] == 0


def test_a_run_with_a_part_the_trie_lacks_is_still_missing():
    """Or the check forgives everything and measures nothing."""
    assert "newtoneinsteinbohr" not in blob_of("newton", "einstein")


def test_the_run_must_appear_in_reading_order():
    """Order is what keeps this from matching letters scattered anywhere in
    the page. A run assembled backwards is not the same content."""
    assert "einsteinnewton" not in blob_of("newton", "einstein")


def test_a_word_the_trie_lacks_outright_is_missing():
    out = score_visible(["quantum chromodynamics"], ["quantum"])
    assert out["unseen"] == 1
    assert out["unseen_sample"][0][1] == ["chromodynamics"]


# --- the shape of the answer -------------------------------------------------


def test_a_page_fully_held_reports_perfect_recall():
    out = score_visible(["the quick brown fox"], ["the quick brown fox"])
    assert out["recall"] == 1.0 and out["unseen"] == 0


def test_a_page_with_nothing_visible_is_not_a_failure():
    """No words seen is no claim either way, not zero recall."""
    out = score_visible([], ["anything"])
    assert out["recall"] == 1.0 and out["words"] == 0


def test_the_sample_names_the_line_and_the_missing_words():
    """A count alone sent me chasing three phantom defects. The sample is
    what made each one identifiable."""
    out = score_visible(["alpha beta missingword"], ["alpha beta"])
    line, gone = out["unseen_sample"][0]
    assert "alpha beta" in line
    assert gone == ["missingword"]
