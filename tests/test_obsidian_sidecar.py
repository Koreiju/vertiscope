"""The sidecar's payload, and the two things every consumer depends on.

Both the interactive surface and the `/` retrieval gesture read these lines,
and the gesture puts them straight into a note. So the payload has to be
markdown a note can hold, and its lines have to stay aligned with the
addresses that name them.
"""

import pytest

from vertiscope.obsidian.sidecar import chunk_payload, search_payload


HOME = ("<html><body><div><div><div><ul>"
        "<li><a href='https://a.test/sub.html'>go on</a></li>"
        "<li><button>Add to basket</button></li>"
        "<li><img src='/hero.png' alt='A hero picture'></li>"
        "</ul></div></div></div>"
        "<p>the front page</p></body></html>")
SUB = "<html><body><h1>Sub</h1><p>second page about glaciers</p></body></html>"


@pytest.fixture()
def ws(tmp_path):
    from vertiscope.workspace import Workspace
    with Workspace(tmp_path / "ws") as workspace:
        workspace.index_html(SUB, "https://a.test/sub.html")
        workspace.index_html(HOME, "https://a.test")
        yield workspace


def _lines(ws, cid):
    return chunk_payload(ws, cid)["lines"]


def test_no_line_arrives_indented_into_a_code_block(ws):
    """The gesture inserts these lines into a note verbatim.

    The renderer indents by depth in the DOM, so a chunk rooted a few elements
    down opens at column 10 -- and four or more leading spaces is an indented
    CODE BLOCK in CommonMark. The export learned this the hard way: 82 of 98
    notes parsed as code and every wikilink in them was unreachable. Reflowing
    in the sidecar is what stops the retrieval gesture reintroducing it.

    Asserted through a real CommonMark parser rather than by measuring
    indentation: "indent >= 4" is not the question. Four spaces INSIDE a list
    is nesting -- `    ( Add to basket )` at nesting level two is perfectly
    fine -- and only four spaces STARTING a block is code. A hand-rolled
    indent check called reachable lines buried once already.
    """
    from markdown_it import MarkdownIt

    parser = MarkdownIt("commonmark")
    for chunk in ws.store.chunks("https://a.test"):
        body = "\n".join(l["text"] for l in _lines(ws, chunk.cid))
        buried = [tok.content for tok in parser.parse(body)
                  if tok.type == "code_block"]
        assert not buried, "lines parse as an indented code block: %r" % buried


def test_lines_stay_aligned_with_their_addresses(ws):
    """Reflowing must map one line to one line.

    The payload zips the markdown against `addresses_of`, which is positional
    by the `anchors` contract. A reflow that dropped or merged a line would
    silently mislabel every line after it.
    """
    for chunk in ws.store.chunks("https://a.test"):
        payload = chunk_payload(ws, chunk.cid)
        assert len(payload["lines"]) == len(chunk.md.splitlines())
        keyed = [l for l in payload["lines"] if l["key"]]
        assert len(keyed) <= payload["addresses"]


def test_a_control_is_reported_as_one(ws):
    """The surface draws a button only if the payload says it is one."""
    found = [l for chunk in ws.store.chunks("https://a.test")
             for l in _lines(ws, chunk.cid) if l["control"]]
    assert found, "no control reported on a page with a button and a link"


def test_media_carries_a_target_the_surface_can_show(ws):
    """A billboard needs a source; `![alt](src)` or `target` will do."""
    media = [l for chunk in ws.store.chunks("https://a.test")
             for l in _lines(ws, chunk.cid)
             if l["cls"] in ("image", "media") or l["text"].startswith("![")]
    assert media, "the image was not reported as media"
    assert any(m.get("target") or "](" in m["text"] for m in media), \
        "media reported with no source at all: %s" % media


def test_search_honours_its_limit(ws):
    """`k` reaches the ranking rather than being decoration."""
    one = search_payload(ws, "glaciers", 1)
    assert len(one["hits"]) <= 1
    assert one["query"] == "glaciers"
    for hit in one["hits"]:
        assert hit["cid"] and hit["url"] and "preview" in hit
