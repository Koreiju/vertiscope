"""G-248: a PDF is kept and chunked like a page, addressed by its own
structure (page section, heading, paragraph)."""
import fitz

from vertiscope.pdf import pdf_to_html
from vertiscope.workspace import Workspace

URL = "https://example.org/papers/tries.pdf"


def _pdf():
    doc = fitz.open()
    for p in range(3):
        page = doc.new_page()
        page.insert_text((72, 72), "Section %d: Patricia tries" % (p + 1), fontsize=20)
        y = 110
        for i in range(6):
            page.insert_text((72, y), "Paragraph %d.%d explains radix compression of keys in a trie node." % (p + 1, i + 1), fontsize=10)
            y += 40
    page.insert_link({"kind": fitz.LINK_URI, "from": fitz.Rect(72, 100, 400, 125), "uri": "https://en.wikipedia.org/wiki/Radix_tree"})
    doc.set_metadata({"title": "On Patricia tries"})
    return doc.tobytes()


def test_the_outline_is_pages_headings_and_paragraphs():
    html, info = pdf_to_html(_pdf(), URL)
    assert info["pages"] == 3 and info["headings"] == 3 and info["blocks"] >= 3 + 18 - 3
    assert html.count("<section>") == 3 and "<h2>Page 3</h2>" in html
    assert "On Patricia tries" in html and 'href="https://en.wikipedia.org/wiki/Radix_tree"' in html


def test_a_pdf_is_kept_and_chunked_like_a_page(tmp_path):
    data = _pdf()
    with Workspace(tmp_path) as ws:
        got = ws.index_pdf(data, URL)
        assert got["chunks"] > 0 and (tmp_path / got["kept"]).read_bytes() == data
        mds = [md for (md,) in ws.store._rows("MATCH (c:Chunk {url: $u}) RETURN c.md", {"u": got["url"]})]
        text = "\n".join(mds)
        assert "Paragraph 2.4 explains radix compression" in text and "Section 3: Patricia tries" in text
        xps = [x for (x,) in ws.store._rows("MATCH (c:Chunk {url: $u}) RETURN c.xpath", {"u": got["url"]})]
        assert any("section" in x for x in xps)


def test_non_vacuity_a_scanned_pdf_says_it_has_no_text():
    doc = fitz.open(); doc.new_page(); doc.new_page()
    html, info = pdf_to_html(doc.tobytes(), URL)
    assert info["pages_without_text"] == 2 and info["blocks"] == 0
