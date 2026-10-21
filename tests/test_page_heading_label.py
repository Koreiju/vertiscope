"""A page with no stored title is labelled by its own H1 -- and says so.

121 of 130 pages lost their titles to a write path that blanked them (fixed;
titles return as pages are visited). The graph then labelled them with urls.
The fallback reads the page's first heading from its chunks, in document
order; the markdown carries structure as indentation, so headings are rarely
at column 0, and the first H2 in order is usually a sidebar's "Contents".
"""

from types import SimpleNamespace

from vertiscope.obsidian import layout as L


class _Store:
    def __init__(self, rows):
        self.rows = rows

    def chunk_count(self, url=""):
        return len(self.rows)

    def _rows(self, query, params=None):
        urls = set((params or {}).get("urls") or [])
        return [r for r in self.rows if r[0] in urls and "#" in (r[3] or "")]


def _headings(rows, urls):
    L._HEADING_MEMO.clear()
    return L._page_headings(SimpleNamespace(store=_Store(rows)), urls)


def test_the_indented_h1_wins_over_an_earlier_sidebar_h2():
    rows = [
        ("u1", "/html/body/div[1]", 0, "  ## Contents\n  - intro"),
        ("u1", "/html/body/div[3]", 0, "        # Persona (series)\n  text"),
    ]
    assert _headings(rows, ["u1"]) == {"u1": "Persona (series)"}


def test_with_no_h1_the_first_h2_is_used_and_links_are_unwrapped():
    rows = [("u2", "/html/body/main", 0, "    ## [Energy](https://x/energy)")]
    assert _headings(rows, ["u2"]) == {"u2": "Energy"}


def test_a_page_without_a_heading_gets_none_not_a_guess():
    rows = [("u3", "/html/body", 0, "no heading here, only a # in text")]
    assert _headings(rows, ["u3"]) == {}
