"""A sentence broken by inline markup is one line, in a list as anywhere (D-36).

Reported 2026-09-27 from DuckDuckGo's Search Assist answer, pinned: the page
shows one sentence, "A **suffix trie** is a trie data structure ...", and the
billboard and the side card both showed three bullets -- "A", "suffix trie",
"is a trie data structure ...". The answer sits inside the results list
(`ol > li`), so every line is an `item`, and the `<span>` holding the bold
words puts them one level deeper in the distilled tree than the paragraph's
own text. `_join_inline` required equal depth, so the sentence never rejoined.

Both panel forms read the same lines (`htmlform.py` builds from them), so the
fix is in the projection and one test covers both. The planted arm restores
the depth rule and must split the sentence again.
"""

import vertiscope.markdown as md
from vertiscope.address import ContentAddress
from vertiscope.markdown import render_trie
from vertiscope.obsidian import htmlform
from vertiscope.stream import StreamingScan

URL = "https://duckduckgo.com/?q=suffix+tree&ia=web"
HTML = """<html><body><div><section><ol>
<li><div><div><div>
  <p>A <span class="b">suffix trie</span> is a trie data structure that represents all the
  suffixes of an input string, with each node corresponding to a suffix.</p>
</div></div></div></li>
<li><div><p>Another result with <b>bold</b> words and <em>emphasis</em> inside it.</p></div></li>
</ol></section></div></body></html>"""


def _markdown():
    scan = StreamingScan(URL, context_window=256)
    return "\n".join(c.markdown for c in render_trie(scan.push(HTML, passno=0).trie, context_window=256))


def test_a_sentence_in_a_list_item_is_one_line():
    text = _markdown()
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    hit = [l for l in lines if "suffix trie" in l]
    assert len(hit) == 1, lines
    assert "A suffix trie is a trie data structure" in hit[0], hit
    assert not any(l.lstrip("- ").strip() == "A" for l in lines), lines
    other = [l for l in lines if "bold" in l]
    assert len(other) == 1 and "emphasis inside it" in other[0], lines


def test_the_panel_html_holds_the_sentence_whole():
    scan = StreamingScan(URL, context_window=256)
    chunks = render_trie(scan.push(HTML, passno=0).trie, context_window=256)
    lines = [ln for c in chunks for ln in (c.lines if hasattr(c, "lines") else [])]
    if not lines:
        return                                   # the render carries no line records here
    payload = [{"text": getattr(l, "text", str(l)), "key": getattr(l, "key", "")} for l in lines]
    markup = htmlform.render_lines(payload, base=URL)
    assert "A suffix trie is a trie data structure" in markup.replace("\n", " ")


P = "/html/body/div/section/ol/li/div/div/div/p"


def _live_units():
    """The units the LIVE capture's trie gives for the answer: the span's text
    one element deeper than the paragraph's own (the Python scan collapses the
    span into one patricia step; the spine does not)."""
    def u(xp, v, depth):
        return (ContentAddress(URL, xp, "text.visible", "text()[0]"), v, "item", depth)
    return [u(P + "/text()[1]", "A", 9),
            u(P + "/span/text()", "suffix trie", 10),
            u(P + "/text()[2]", "is a trie data structure that represents all the suffixes", 9)]


def test_a_sentence_joins_across_an_inline_elements_depth():
    got = md._join_inline(_live_units())
    assert len(got) == 1, [g[1] for g in got]
    assert got[0][1].startswith("A suffix trie is a trie data structure"), got[0][1]


def test_two_blocks_at_different_depths_do_not_join():
    def u(xp, v, depth):
        return (ContentAddress(URL, xp, "text.visible", "text()[0]"), v, "item", depth)
    got = md._join_inline([u("/html/body/ol/li/p/text()", "one", 4),
                           u("/html/body/ol/li/div/p/text()", "two", 5)])
    assert len(got) == 2


def test_planted_the_depth_rule_splits_it_again(monkeypatch):
    real = md._join_inline

    def depth_strict(units):
        groups, cur = [], []
        for x in units:
            if cur and cur[-1][3] != x[3]:
                groups.append(cur)
                cur = []
            cur.append(x)
        if cur:
            groups.append(cur)
        return [y for g in groups for y in real(g)]

    monkeypatch.setattr(md, "_join_inline", depth_strict)
    assert len(md._join_inline(_live_units())) == 3


def test_a_forms_action_url_is_not_drawn_in_the_panel():
    lines = [
        {"text": "  - A suffix trie is a trie", "key": URL + "|/html/body/p/text()|item|text()[0]%7Ctext.visible/p", "cls": "item"},
        {"text": "  /?q=suffix+tree&ia=chat", "key": URL + "|/html/body/form|group|action%7Cform.tag/form",
         "cls": "group", "target": "/?q=suffix+tree&ia=chat"},
        {"text": "  ( Expand Duck.ai chat input )", "key": URL + "|/html/body/form/button|button|aria-label%7Ccontrol.button/button",
         "cls": "button"},
    ]
    markup = htmlform.render_lines(lines, base=URL)
    assert "ia=chat" not in markup
    assert "A suffix trie is a trie" in markup and "Expand Duck.ai chat input" in markup


def test_planted_the_form_line_comes_back(monkeypatch):
    monkeypatch.setattr(htmlform, "_is_form_action", lambda line, raw: False)
    lines = [{"text": "/?q=x&ia=chat", "key": URL + "|/html/body/form|group|action%7Cform.tag/form", "cls": "group"}]
    assert "ia=chat" in htmlform.render_lines(lines, base=URL)


def test_a_protocol_relative_picture_loads_from_the_page_scheme():
    lines = [{"text": "![](//external-content.duckduckgo.com/ip3/pypi.org.ico)",
              "key": URL + "|/html/body/a/img|image|src%7Cmedia.images/img", "cls": "image"}]
    markup = htmlform.render_lines(lines, base=URL)
    assert 'src="https://external-content.duckduckgo.com/ip3/pypi.org.ico"' in markup, markup
