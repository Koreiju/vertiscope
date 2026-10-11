"""Tables render as markdown tables (`D-5`, `M-3`; the goal: "a
hierarchically-header-structured markdown document with tables, images, web
links"). A table used to arrive one line per cell. Planted: PLANT_NO_TABLES."""

import domvec.markdown as md
from domvec.markdown import render_trie
from domvec.stream import StreamingScan

ROWS = [("Konqueror", "KHTML"), ("Firefox", "Gecko"), ("Safari", "WebKit")]
HTML = ("<html><body><main><h2>Browsers</h2><table><tr><th>Name</th><th>Engine</th><th>Licence</th></tr>"
        + "".join("<tr><td><a href='https://x.test/%s'>%s</a></td><td>%s</td><td>a|b %d</td></tr>" % (n, n, e, i)
                  for i, (n, e) in enumerate(ROWS))
        + "</table><p>after the table</p></main></body></html>")


def _lines():
    chunks = render_trie(StreamingScan("https://t.test/p", context_window=512).push(HTML, passno=0).trie,
                         context_window=512)
    return [l for c in chunks for l in c.lines]


def test_a_table_is_a_pipe_table_with_a_header_and_every_address_kept():
    lines = _lines()
    rows = [l for l in lines if l.text.startswith("|")]
    assert len(rows) == 4, [l.text for l in lines]
    assert rows[0].text == "| Name | Engine | Licence |"
    # The separator is drawn for a reader, never stored as a line of its own.
    shown = md.with_table_separators("\n".join(l.text for l in rows)).splitlines()
    assert shown[:2] == ["| Name | Engine | Licence |", "| --- | --- | --- |"] and len(shown) == 5
    assert rows[1].text == r"| [Konqueror](https://x.test/Konqueror) | KHTML | a\|b 0 |"
    # Every cell's address is on its row: the first as the line's own, the rest inline.
    held = {a.xpath for l in rows for a in (l.address, *l.inline)}
    for r in range(2, 5):
        for c in ("td", "td[2]", "td[3]"):
            assert any(("tr[%d]/%s" % (r, c)) in x for x in held), (r, c)
    assert any(l.text.strip() == "after the table" for l in lines)


def test_planted_no_tables_draws_a_cell_per_line(monkeypatch):
    monkeypatch.setattr(md, "PLANT_NO_TABLES", True)
    lines = _lines()
    assert not any(l.text.startswith("|") for l in lines)
    assert sum(1 for l in lines if l.text.strip() in ("KHTML", "Gecko", "WebKit")) == 3


def _span_table():
    html = ("<html><body><table><tr><th>Name</th><th>OS</th><th>Licence</th></tr>"
            "<tr><td rowspan='3'>Konqueror</td><td>BSD</td><td rowspan='3'>GPL</td></tr>"
            "<tr><td>Linux</td></tr><tr><td>macOS</td></tr>"
            "<tr><td>Firefox</td><td>Windows</td><td>MPL</td></tr>"
            "</table></body></html>")
    return [l for c in render_trie(StreamingScan("https://t.test/s", context_window=512).push(html, passno=0).trie,
                                   context_window=512) for l in c.lines]


def test_a_cell_under_a_rowspan_lands_in_its_own_column():
    """`D-5`: the sensor and the tagger report spans, and the table is laid out
    as a browser lays it out. "Linux" sits under "OS", not under "Name"."""
    rows = [l.text for l in _span_table() if l.text.startswith("|")]
    assert rows[0] == "| Name | OS | Licence |", rows
    assert "| Konqueror | BSD | GPL |" in rows
    assert "|  | Linux |  |" in rows and "|  | macOS |  |" in rows
    assert "| Firefox | Windows | MPL |" in rows
    # The span itself is layout, never a line of its own.
    assert not any(l.text.strip() in ("3",) for l in _span_table())


def test_planted_no_spans_puts_linux_under_name(monkeypatch):
    monkeypatch.setattr(md, "PLANT_NO_SPANS", True)
    rows = [l.text for l in _span_table() if l.text.startswith("|")]
    assert any(r.startswith("| Linux |") for r in rows), rows


def _long_table(window):
    rows = "".join("<tr><td>Browser %d</td><td>Engine %d</td><td>%d.%d%%</td></tr>" % (i, i % 4, i, i % 10) for i in range(80))
    html = ("<html><body><main><table><tr><th>Name</th><th>Engine</th><th>Share</th></tr>" + rows
            + "</table></main></body></html>")
    return render_trie(StreamingScan("https://t.test/long", context_window=window).push(html, passno=0).trie,
                       context_window=window)


def test_rows_away_from_their_header_carry_its_names():
    """`D-9`: a chunk of rows without the header row named nothing -- `0.14%`
    with no subject. Each value is now named by the header at its position."""
    chunks = _long_table(64)
    assert len(chunks) > 3
    away = [c for c in chunks if not any(l.text.startswith("| Name") for l in c.lines)
            and any("Browser" in l.text for l in c.lines)]
    assert away, "the table never split from its header"
    for c in away:
        for l in c.lines:
            if "Browser" in l.text:
                assert l.text.startswith("Name: Browser") and "Engine: Engine" in l.text and "Share: " in l.text, l.text
                assert len(l.inline) >= 2      # every cell's address still on the line


def test_planted_naked_rows_carry_bare_values(monkeypatch):
    monkeypatch.setattr(md, "PLANT_NAKED_ROWS", True)
    chunks = _long_table(64)
    texts = [l.text for c in chunks for l in c.lines]
    assert not any("Engine: " in t for t in texts)
