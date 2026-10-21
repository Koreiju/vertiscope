"""The incremental transport: hash, prune, splice.

This is the code path where a bug silently *deletes content*. The browser
returns a document with unchanged subtrees replaced by placeholders, and
Python fills them back in from what it already had. If a fragment is indexed
under the wrong hash, or an element's extent is measured wrong, the spliced
document is missing a region and everything downstream — trie, chunks, index —
faithfully records a page that never existed.

So the property under test is not "splicing works" but **splicing is exact**:
the reconstructed document must equal the document that would have been sent
in full. Anything less is worse than not pruning at all, which is why
:func:`deep_serialize` refuses the saving and re-fetches whole when a
placeholder cannot be filled.
"""

import json
import pathlib

import pytest

from vertiscope.capture import Snapshot, _element_end, _splice, fragments_of

CORPUS = pathlib.Path(__file__).parent / "corpus"
MANIFEST = CORPUS / "manifest.json"


# --- measuring an element's extent -----------------------------------------


def test_element_end_finds_the_matching_close():
    html = '<div data-vertiscope-hash="aa">text</div><p>after</p>'
    assert html[:_element_end(html, 0, "div")] == '<div data-vertiscope-hash="aa">text</div>'


def test_element_end_handles_nesting_of_the_same_tag():
    """The reason a naive `find('</div>')` is wrong."""
    html = '<div data-vertiscope-hash="aa"><div>inner</div>outer</div>tail'
    end = _element_end(html, 0, "div")
    assert html[:end] == '<div data-vertiscope-hash="aa"><div>inner</div>outer</div>'


def test_element_end_handles_void_elements():
    html = '<img data-vertiscope-hash="aa" src="x.png"><p>after</p>'
    assert html[:_element_end(html, 0, "img")] == '<img data-vertiscope-hash="aa" src="x.png">'


def test_element_end_handles_self_closing():
    html = '<br data-vertiscope-hash="aa"/><p>after</p>'
    assert html[:_element_end(html, 0, "br")] == '<br data-vertiscope-hash="aa"/>'


def test_element_end_reports_failure_rather_than_guessing():
    """An unclosed element must not silently swallow the rest of the page."""
    assert _element_end('<div data-vertiscope-hash="aa">unclosed', 0, "div") == -1


# --- indexing fragments by hash ---------------------------------------------


def test_fragments_are_indexed_by_their_own_hash():
    html = ('<html data-vertiscope-hash="r">'
            '<body data-vertiscope-hash="b">'
            '<p data-vertiscope-hash="p1">one</p>'
            '<p data-vertiscope-hash="p2">two</p>'
            '</body></html>')
    frags = fragments_of(html)
    assert frags["p1"] == '<p data-vertiscope-hash="p1">one</p>'
    assert frags["p2"] == '<p data-vertiscope-hash="p2">two</p>'
    assert frags["b"].startswith('<body data-vertiscope-hash="b">')
    assert frags["b"].endswith("</body>")


def test_a_fragment_contains_its_descendants():
    """Pruning a subtree must restore the subtree, not just its root."""
    html = ('<div data-vertiscope-hash="d"><span data-vertiscope-hash="s">x</span></div>')
    frags = fragments_of(html)
    assert "<span" in frags["d"] and "x</span>" in frags["d"]


def test_elements_without_a_hash_are_not_indexed():
    frags = fragments_of('<div><p data-vertiscope-hash="p">x</p></div>')
    assert set(frags) == {"p"}


# --- splicing ----------------------------------------------------------------


def test_splice_restores_the_original_document_exactly():
    full = ('<html data-vertiscope-hash="r"><body data-vertiscope-hash="b">'
            '<p data-vertiscope-hash="p1">one</p>'
            '<p data-vertiscope-hash="p2">two</p></body></html>')
    frags = fragments_of(full)

    pruned = ('<html data-vertiscope-hash="r"><body data-vertiscope-hash="b">'
              '<template data-vertiscope-same="p1"></template>'
              '<p data-vertiscope-hash="p2">two</p></body></html>')
    spliced, missing = _splice(pruned, frags)
    assert missing == 0
    assert spliced == full


def test_splice_handles_several_placeholders():
    full = ('<ul data-vertiscope-hash="u">'
            '<li data-vertiscope-hash="a">a</li>'
            '<li data-vertiscope-hash="b">b</li>'
            '<li data-vertiscope-hash="c">c</li></ul>')
    frags = fragments_of(full)
    pruned = ('<ul data-vertiscope-hash="u">'
              '<template data-vertiscope-same="a"></template>'
              '<template data-vertiscope-same="b"></template>'
              '<template data-vertiscope-same="c"></template></ul>')
    spliced, missing = _splice(pruned, frags)
    assert missing == 0 and spliced == full


def test_splice_resolves_a_placeholder_inside_a_fragment():
    """A fragment cached from an earlier pass may itself hold a placeholder."""
    frags = {
        "outer": '<div data-vertiscope-hash="outer">'
                 '<template data-vertiscope-same="inner"></template></div>',
        "inner": '<p data-vertiscope-hash="inner">deep</p>',
    }
    spliced, missing = _splice('<template data-vertiscope-same="outer"></template>', frags)
    assert missing == 0
    assert spliced == '<div data-vertiscope-hash="outer"><p data-vertiscope-hash="inner">deep</p></div>'


def test_splice_counts_a_fragment_it_cannot_fill():
    """The count is what makes deep_serialize give up rather than lose content."""
    spliced, missing = _splice('<template data-vertiscope-same="gone"></template>', {})
    assert missing == 1
    assert "data-vertiscope-same" not in spliced


def test_splice_terminates_on_a_self_referential_fragment():
    """A fragment naming itself must not hang the scan."""
    frags = {"loop": '<div><template data-vertiscope-same="loop"></template></div>'}
    spliced, _missing = _splice('<template data-vertiscope-same="loop"></template>', frags)
    assert isinstance(spliced, str)


# --- round trip on a real page ---------------------------------------------


@pytest.mark.skipif(not MANIFEST.exists(), reason="frozen corpus absent")
def test_prune_and_splice_round_trips_a_real_page():
    """Simulate a second pass over a real document: prune everything, restore.

    Uses a real page rather than a fixture because the failure modes are all
    shape — deep nesting, same-tag nesting, void elements, attributes holding
    angle brackets — and a hand-written fixture exhibits none of them.
    """
    pages = [p for p in json.loads(MANIFEST.read_text())["pages"] if p.get("ok")]
    page = next((p for p in pages if p["slug"].startswith("books-toscrape")),
                pages[0])
    html = (CORPUS / f"{page['slug']}.html").read_text(
        encoding="utf-8", errors="replace")

    # The corpus is raw html with no hashes, so stamp some on: give every
    # <li> a hash, then prune each one and splice it back.
    import re

    stamped = re.sub(r"<li(?=[\s>])",
                     lambda m, c=[0]: (c.__setitem__(0, c[0] + 1)
                                       or f'<li data-vertiscope-hash="{c[0]:x}"'),
                     html)
    frags = fragments_of(stamped)
    assert len(frags) > 5, "the page has too few elements to test with"

    pruned = stamped
    for digest, fragment in frags.items():
        pruned = pruned.replace(
            fragment, f'<template data-vertiscope-same="{digest}"></template>', 1)

    spliced, missing = _splice(pruned, frags)
    assert missing == 0
    assert spliced == stamped, "splicing did not reproduce the document exactly"


def test_snapshot_reports_the_wire_cost():
    snap = Snapshot(html="x" * 100, stats={"bytes": 20, "pruned": 3,
                                           "prunedNodes": 40})
    assert snap.wire_bytes == 20
    assert snap.pruned_subtrees == 3
    assert snap.pruned_nodes == 40


def test_snapshot_without_stats_falls_back_to_the_html_length():
    """A serializer that returned bare html must not report a wire cost of 0."""
    assert Snapshot(html="x" * 100).wire_bytes == 100


# --- re-scanning must actually re-read ---------------------------------------


def test_stream_snapshots_forces_navigation_by_default():
    """A re-scan that reuses the loaded DOM can never see a change.

    The scanner skips navigation when already on the URL — right inside a
    settle loop, where re-navigating would reset the scroll it is driving, and
    fatal to a re-scan. `scripts/probe_live_mutation.py` caught this against a
    real browser: a page rewritten between scans reported no delta, and the
    index silently kept content that was gone.

    Checked with a stub rather than a browser so it runs in the suite; the
    live probe is what proved it end to end.
    """
    import vertiscope.capture as capture

    calls = []

    class FakeScanner:
        def __init__(self, driver):
            pass

        def scan(self, url, max_duration=0, pause=0.0, force_reload=False):
            calls.append(force_reload)
            yield []

    class FakeDriver:
        def execute_script(self, *_a):
            return '{"html": "<html><body><p>x</p></body></html>", ' \
                   '"hashes": {}, "stats": {"bytes": 40}}'

    import vertiscope.core.scanner as scanner_module
    original = scanner_module.ShadowDOMScanner
    scanner_module.ShadowDOMScanner = FakeScanner
    try:
        list(capture.stream_snapshots(FakeDriver(), "https://x.test/",
                                      max_duration=1, pause=0.0,
                                      max_snapshots=1))
        assert calls == [True], "stream_snapshots did not force a reload"

        calls.clear()
        list(capture.stream_snapshots(FakeDriver(), "https://x.test/",
                                      max_duration=1, pause=0.0,
                                      max_snapshots=1, reload=False))
        assert calls == [False], "reload=False was not honoured"
    finally:
        scanner_module.ShadowDOMScanner = original


def test_the_scanner_still_skips_navigation_when_asked():
    """The original behaviour must remain reachable.

    Inside a settle loop, re-navigating would reset the scroll position the
    loop is driving, so `force_reload=False` has to keep working.
    """
    import inspect

    from vertiscope.core.scanner import ShadowDOMScanner

    signature = inspect.signature(ShadowDOMScanner.scan)
    assert "force_reload" in signature.parameters
    assert signature.parameters["force_reload"].default is False
