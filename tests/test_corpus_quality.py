"""Is the corpus itself sound enough to draw conclusions from?

Every other suite treats the frozen corpus as ground truth. That is only safe
if the corpus is what the sites actually served, so this checks the fixture
rather than the code — the one place where a silent defect would corrupt every
downstream measurement at once without failing anything.
"""

import json
import pathlib
import re

import pytest

CORPUS = pathlib.Path(__file__).parent / "corpus"
MANIFEST = CORPUS / "manifest.json"

pytestmark = pytest.mark.skipif(
    not MANIFEST.exists(),
    reason="frozen corpus absent; run scripts/fetch_corpus.py",
)

# A UTF-8 sequence that decodes to a latin-1 reading of UTF-8: lead byte
# U+00C2/U+00C3 plus a continuation codepoint, or the smart-quote triple.
# "£" mis-decoded becomes "Â£", which re-encodes to valid UTF-8 — so nothing
# downstream raises, and the corruption is invisible until someone reads it.
MOJIBAKE = re.compile(
    "[ÂÃ][-¿]"
    "|â[]"
)


def _pages():
    pages = [p for p in json.loads(MANIFEST.read_text())["pages"] if p.get("ok")]
    return [p for p in pages if (CORPUS / f"{p['slug']}.html").exists()]


def _mojibake_counts():
    counts = {}
    for page in _pages():
        text = (CORPUS / f"{page['slug']}.html").read_text(
            encoding="utf-8", errors="replace")
        hits = len(MOJIBAKE.findall(text))
        if hits:
            counts[page["slug"]] = hits
    return counts


def test_mojibake_is_pinned_at_its_known_extent():
    """PINNED DEFECT — a fetch-time encoding bug, since fixed at source.

    `requests` follows RFC 2616 and falls back to ISO-8859-1 whenever the
    Content-Type header omits a charset, ignoring the document's own
    `<meta charset>`. Most servers omit it, so the fetcher decoded UTF-8 as
    latin-1 and every non-ASCII character was stored doubly encoded: a price
    of "£51.33" is "Â£51.33" in the fixture.

    `scripts/fetch_corpus.py` now prefers the header's charset, then the
    document's declaration, then chardet — so a re-fetch fixes these. The
    pages are pinned rather than re-fetched because re-fetching changes every
    stored SHA-1 and moves every benchmark number recorded against this
    corpus; that is a deliberate decision, not a side effect of a bug fix.

    A *new* page with mojibake fails here, which is the point.
    """
    counts = _mojibake_counts()
    known = {
        "docs-python-org-3-library-re-html",
        "books-toscrape-com",
        "developer-mozilla-org-en-us-docs-web-html",
        "books-toscrape-com-catalogue-category-books-travel-2-index-html",
        "docs-python-org-3-tutorial-index-html",
        "www-gnu-org-licenses-gpl-3-0-html",
        "doc-rust-lang-org-book-ch01-00-getting-started-html",
        "www-usa-gov",
    }
    new = set(counts) - known
    assert not new, f"mojibake appeared on page(s) not previously affected: {new}"
    assert len(counts) <= 8, (
        f"mojibake spread to {len(counts)} pages, was 8 — regression"
    )


def test_most_of_the_corpus_is_clean():
    """The bound that makes the rest of the suite's conclusions usable.

    A rate, not a count. As `>= 45 clean pages` it was written against a
    54-page corpus and would have passed at 136 pages with **91** of them
    mangled — the same shape of mistake as `test_ri2_failure_is_pinned`, where
    a count silently stopped meaning anything once the denominator moved.
    """
    counts = _mojibake_counts()
    pages = len(_pages())
    clean = pages - len(counts)
    assert clean / pages >= 0.90, (
        f"only {clean} of {pages} pages are clean ({clean / pages:.0%})")


def test_the_fetcher_no_longer_trusts_the_requests_default():
    """The fix must stay in place, or a re-fetch silently reintroduces it."""
    source = (pathlib.Path(__file__).parent.parent
              / "scripts" / "fetch_corpus.py").read_text(encoding="utf-8")
    assert "apparent_encoding" in source, (
        "fetch_corpus.py no longer overrides the ISO-8859-1 fallback"
    )
    assert "charset=" in source


def test_every_ok_page_has_a_file_and_a_hash():
    for page in _pages():
        assert page.get("sha1"), f"{page['slug']}: no recorded hash"
        assert page.get("bytes", 0) > 200, f"{page['slug']}: implausibly small"


def test_the_corpus_is_structurally_varied():
    """The claim the corpus exists to support.

    Floors, deliberately: the corpus grows, and a bound that had to be edited
    on every addition would be edited without being thought about. Raised from
    50/35 when it reached 136 pages across 100 hosts, because a floor a corpus
    has doubled past has stopped constraining anything.
    """
    pages = _pages()
    hosts = {p["url"].split("/")[2] for p in pages}
    assert len(pages) >= 100, f"only {len(pages)} pages"
    assert len(hosts) >= 70, f"only {len(hosts)} distinct hosts"
