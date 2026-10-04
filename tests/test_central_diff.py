"""The central diff: one record per capture, keyed on the cid.

`_page_diff` reads the render the patricia trie produced (`all_chunks`, each
with a `.cid` and `.markdown`) against what the session rendered before and
what the store's trie already held when the visit began (`session["stored"]`),
and says what is ADDED, what is RETIRED, which retired cids were only RENAMED
(same markdown at a new cid: a shift moved the address, not the content) and
which are KNOWN (stored before this visit, so drawn from the store and never
re-spawned).

Every view -- the chunk map, the pins, the 3D and 2D representations --
applies this one record, so a mistake here is every view's mistake. The
planted cases are the other half of each claim: a session that ignores the
store re-spawns known chunks, a rename with different content is no rename.
"""

from domvec.obsidian import sidecar
from domvec.obsidian.sidecar import _page_diff, _record_diff

URL = "https://a.test/feed"


class Chunk:
    """The two attributes `_page_diff` reads, and nothing else."""

    def __init__(self, cid, markdown):
        self.cid = cid
        self.markdown = markdown


def render(**by_cid):
    return [Chunk(cid, md) for cid, md in by_cid.items()]


def diff(session, chunks, dirty=(), passno=0):
    return _page_diff(session, URL, passno, chunks, list(dirty))


def test_a_first_render_over_a_stored_page_adds_only_what_the_store_lacks():
    session = {"stored": {"c1", "c2", "c3"}}
    d = diff(session, render(c1="one", c2="two", c3="three", c4="four"))
    assert d["added"] == ["c4"]
    assert sorted(d["known"]) == ["c1", "c2", "c3"]
    assert d["retired"] == [] and d["renamed"] == {}
    assert d["chunks"] == 4 and d["kind"] == "capture" and d["url"] == URL


def test_known_is_named_once_then_it_is_simply_the_previous_render():
    session = {"stored": {"c1", "c2"}}
    diff(session, render(c1="one", c2="two"))
    again = diff(session, render(c1="one", c2="two", c3="three"), passno=1)
    assert again["known"] == [], "a chunk drawn last capture is not newly known"
    assert again["added"] == ["c3"]


def test_planted_a_session_that_ignores_the_store_respawns_known_chunks():
    """The arm that proves the test above can fail: with no `stored` the same
    render reads every chunk as new -- the revisit bug the diff exists to
    stop ("re-navigating back to a previous page re-spawns existing nodes")."""
    chunks = render(c1="one", c2="two", c3="three", c4="four")
    seeded = diff({"stored": {"c1", "c2", "c3"}}, chunks)
    planted = diff({}, chunks)
    assert planted["added"] == ["c1", "c2", "c3", "c4"] and planted["known"] == []
    assert seeded["added"] != planted["added"]
    assert len(planted["added"]) - len(seeded["added"]) == 3


def test_a_shift_retires_the_old_cids_and_renames_them_to_the_new_ones():
    session = {"stored": set()}
    diff(session, render(c1="alpha", c2="beta", c3="gamma"))
    # The container changed: every address is new, the content is not.
    d = diff(session, render(d1="alpha", d2="beta", d3="gamma", d4="delta"), passno=1)
    assert d["retired"] == ["c1", "c2", "c3"]
    assert d["renamed"] == {"c1": "d1", "c2": "d2", "c3": "d3"}
    assert d["added"] == ["d1", "d2", "d3", "d4"]


def test_planted_a_rename_needs_the_same_content_not_just_a_vanished_cid():
    """Retired with DIFFERENT content at the new cid is a loss and an
    arrival, never a rename -- or a view would glide one chunk's node onto
    another's meaning."""
    session = {"stored": set()}
    diff(session, render(c1="alpha", c2="beta"))
    d = diff(session, render(d1="something else", d2="and another"), passno=1)
    assert d["retired"] == ["c1", "c2"]
    assert d["renamed"] == {}
    assert d["added"] == ["d1", "d2"]


def test_identical_content_pairs_off_one_to_one():
    session = {"stored": set()}
    diff(session, render(c1="same", c2="same"))
    d = diff(session, render(d1="same", d2="same", d3="same"), passno=1)
    assert d["renamed"] == {"c1": "d1", "c2": "d2"}, "each new cid is claimed once"
    assert d["added"] == ["d1", "d2", "d3"]


def test_a_removal_retires_without_renaming_or_adding():
    session = {"stored": set()}
    diff(session, render(c1="alpha", c2="beta", c3="gamma"))
    d = diff(session, render(c1="alpha", c3="gamma"), passno=1)
    assert d["retired"] == ["c2"]
    assert d["renamed"] == {} and d["added"] == []


def test_a_rewrite_in_place_is_dirty_not_retired():
    session = {"stored": set()}
    first = render(c1="alpha", c2="beta")
    diff(session, first)
    rewritten = render(c1="alpha", c2="beta, edited")
    d = diff(session, rewritten, dirty=[rewritten[1]], passno=1)
    assert d["dirty"] == ["c2"]
    assert d["retired"] == [] and d["added"] == [] and d["renamed"] == {}


def test_a_capture_that_rendered_nothing_leaves_the_session_alone():
    session = {"stored": set()}
    diff(session, render(c1="alpha"))
    before = dict(session["render"])
    assert diff(session, [], passno=1) is None
    assert session["render"] == before, "an empty render must not erase what was drawn"
    # And the next real render still diffs against the last real one.
    d = diff(session, render(c1="alpha", c2="beta"), passno=2)
    assert d["added"] == ["c2"] and d["retired"] == []


def test_the_diff_is_recorded_with_a_rising_sequence(monkeypatch):
    monkeypatch.setattr(sidecar, "_DIFFS", sidecar._collections.deque(maxlen=10))
    a = _record_diff({"kind": "capture", "url": URL, "added": [], "retired": []})
    b = _record_diff({"kind": "settle", "url": URL, "added": [], "retired": ["c9"]})
    assert b["seq"] == a["seq"] + 1
    assert [x["seq"] for x in sidecar._DIFFS] == [a["seq"], b["seq"]]
    assert b["kind"] == "settle" and "at" in b
