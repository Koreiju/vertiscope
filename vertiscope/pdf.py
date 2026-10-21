"""A PDF into the trie like a page (G-248, 2026-10-18, PLUGIN_GOAL 177:
"there isnt a download process for pdfs and subsequent chunking for us and
there really should be").

A PDF has no DOM for the sensor to fold -- the browser draws it in its own
viewer -- so its text is laid out as the HTML a page would have been, and that
goes through `Workspace.index_html`, the same recursive descent, chunker,
vectoriser and graph as every page. The address is the PDF's own structure:

    <url> : /html/body/article/section[<page>]/(h3|p)[<n>]

one `section` per page (its `h2` says "Page N"), one `h3` per block set in a
larger type than the page's body text, one `p` per other text block, its link
targets kept as anchors. So "page 4, the third paragraph" is an address that
survives a re-download of the same file, and a hover, a panel or a search hit
names it the same way it names a paragraph on a web page.

Text only: a scanned PDF (no text layer) yields pages with nothing in them,
and the result says so (`pages_without_text`) rather than inventing any.
"""

from __future__ import annotations

import hashlib
import html as _html
from statistics import median
from typing import Dict, List, Tuple

#: A block whose largest span is this much bigger than the page's body text
#: is a heading.
HEADING_RATIO = 1.25


def pdf_to_html(data: bytes, url: str = "") -> Tuple[str, Dict]:
    """The PDF as addressable HTML, and what was found in it."""
    import fitz                                     # PyMuPDF

    doc = fitz.open(stream=data, filetype="pdf")
    meta = doc.metadata or {}
    title = (meta.get("title") or "").strip()
    sections: List[str] = []
    info = {"pages": doc.page_count, "blocks": 0, "headings": 0, "links": 0,
            "pages_without_text": 0, "sha1": hashlib.sha1(data).hexdigest(), "title": title}
    for pno in range(doc.page_count):
        page = doc.load_page(pno)
        d = page.get_text("dict")
        blocks = [b for b in d.get("blocks", []) if b.get("type") == 0]
        sizes = [s.get("size", 0) for b in blocks for l in b.get("lines", []) for s in l.get("spans", [])
                 if (s.get("text") or "").strip()]
        body = median(sizes) if sizes else 0
        links = [(fitz.Rect(l["from"]), l.get("uri")) for l in page.get_links() if l.get("uri")]
        parts = ['<h2>Page %d</h2>' % (pno + 1)]
        for b in blocks:
            text_lines, big = [], 0.0
            for l in b.get("lines", []):
                t = "".join(s.get("text") or "" for s in l.get("spans", [])).strip()
                if t:
                    text_lines.append(t)
                    big = max([big] + [s.get("size", 0) for s in l.get("spans", [])])
            text = " ".join(text_lines).strip()
            if not text:
                continue
            body_html = _html.escape(text)
            rect = fitz.Rect(b.get("bbox"))
            hrefs = [u for r, u in links if r.intersects(rect)]
            for u in hrefs[:3]:
                body_html += ' <a href="%s">%s</a>' % (_html.escape(u, quote=True), _html.escape(u))
                info["links"] += 1
            if body and big >= HEADING_RATIO * body and len(text) <= 200:
                parts.append("<h3>%s</h3>" % body_html)
                info["headings"] += 1
            else:
                parts.append("<p>%s</p>" % body_html)
            info["blocks"] += 1
        if len(parts) == 1:
            info["pages_without_text"] += 1
        sections.append("<section>%s</section>" % "".join(parts))
    if not title:
        title = (url.rstrip("/").rsplit("/", 1)[-1] or "document.pdf")
        info["title"] = title
    page_html = ('<!doctype html><html><head><meta charset="utf-8"><title>%s</title></head>'
                 '<body><article>%s</article></body></html>') % (_html.escape(title), "".join(sections))
    return page_html, info
