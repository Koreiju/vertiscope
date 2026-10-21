#!/usr/bin/env python
"""Freeze a benchmark corpus of structurally varied pages.

Every measurement in this workspace so far was taken against one hand-written
fixture and two archived pages, and several findings turned on that being too
narrow — ERRATA C7 records a defect the fixture *could not* exhibit, because it
has no duplicate siblings. `notes/questions/OPEN.md` has wanted a frozen corpus
since the first empirical pass.

Frozen, not live: a benchmark against the internet measures the internet's
variance rather than ours, and cannot be replayed. Pages are fetched once,
hashed, and committed to `tests/corpus/`.

Selection targets *structural* variety, not topical: wikis, documentation,
news, forums, standards, government, academic, deliberately-minimal pages,
right-to-left and CJK scripts, table-heavy and media-heavy layouts, and sites
built for scraping practice. Fetched without JavaScript execution, so
script-rendered pages appear thin — that is a real class of input and is kept
rather than excluded.

    python scripts/fetch_corpus.py            # fetch missing, keep existing
    python scripts/fetch_corpus.py --refresh  # re-fetch everything
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import hashlib
import json
import pathlib
import re
import sys
import time

import requests

ROOT = pathlib.Path(__file__).resolve().parent.parent
CORPUS = ROOT / "tests" / "corpus"
MANIFEST = CORPUS / "manifest.json"

UA = "Mozilla/5.0 (compatible; vertiscope-benchmark/0.1; +offline research corpus)"

# Chosen for structural variety. The label records why each is present, so a
# later reader can tell whether the corpus still covers a shape.
URLS: list[tuple[str, str]] = [
    ("https://example.com", "minimal static"),
    ("https://www.iana.org/domains/reserved", "minimal institutional"),
    ("https://en.wikipedia.org/wiki/Web_scraping", "wiki article"),
    ("https://en.wikipedia.org/wiki/List_of_largest_cities", "wiki, table-heavy"),
    ("https://simple.wikipedia.org/wiki/Physics", "wiki, simplified prose"),
    ("https://ar.wikipedia.org/wiki/فيزياء", "wiki, right-to-left script"),
    ("https://ja.wikipedia.org/wiki/物理学", "wiki, CJK script"),
    ("https://ru.wikipedia.org/wiki/Физика", "wiki, cyrillic"),
    ("https://docs.python.org/3/library/re.html", "docs, dense anchors"),
    ("https://docs.python.org/3/tutorial/index.html", "docs, index page"),
    ("https://developer.mozilla.org/en-US/docs/Web/HTML", "docs, SPA-ish"),
    ("https://doc.rust-lang.org/book/ch01-00-getting-started.html", "docs, book"),
    ("https://pkg.go.dev/net/http", "docs, generated API"),
    ("https://news.ycombinator.com", "forum, table layout"),
    ("https://news.ycombinator.com/newest", "forum, second page shape"),
    ("https://lobste.rs", "forum, semantic markup"),
    ("https://old.reddit.com/r/programming/", "forum, legacy layout"),
    ("https://stackoverflow.com/questions/tagged/python", "q&a listing"),
    ("https://www.bbc.com/news", "news, card grid"),
    ("https://text.npr.org", "news, text-only variant"),
    ("https://lite.cnn.com", "news, lite variant"),
    ("https://www.theguardian.com/international", "news, heavy"),
    ("https://apnews.com", "news, modern SPA"),
    ("https://arxiv.org/list/cs.IR/recent", "academic listing"),
    ("https://arxiv.org/abs/1706.03762", "academic abstract"),
    ("https://pubmed.ncbi.nlm.nih.gov/?term=machine+learning", "academic search"),
    ("https://www.ncbi.nlm.nih.gov/pmc/", "academic portal"),
    ("https://archive.org/search?query=university+library", "archive search"),
    ("https://archive.org/details/princetonuniver01librgoog", "archive detail"),
    ("https://openlibrary.org/search?q=telescope", "library search"),
    ("https://books.toscrape.com", "e-commerce practice site"),
    ("https://books.toscrape.com/catalogue/category/books/travel_2/index.html",
     "e-commerce category"),
    ("https://quotes.toscrape.com", "quotes practice site"),
    ("https://webscraper.io/test-sites/e-commerce/allinone", "scraping test site"),
    ("https://www.scrapethissite.com/pages/simple/", "scraping test site 2"),
    ("https://www.w3.org/TR/html52/", "standard, very long"),
    ("https://www.rfc-editor.org/rfc/rfc2616.html", "standard, pre-formatted"),
    ("https://www.gnu.org/licenses/gpl-3.0.html", "legal text"),
    ("https://www.usa.gov", "government portal"),
    ("https://www.gov.uk/browse/benefits", "government listing"),
    ("https://www.census.gov/topics/population.html", "government data"),
    ("https://www.who.int/news-room", "ngo news"),
    ("https://github.com/python/cpython", "code hosting"),
    ("https://gitlab.com/explore/projects", "code hosting 2"),
    ("https://pypi.org/project/requests/", "package registry"),
    ("https://crates.io/crates/serde", "package registry, SPA"),
    ("https://hub.docker.com/_/python", "registry, SPA"),
    ("https://www.imdb.com/chart/top/", "media listing"),
    ("https://openweathermap.org", "marketing page"),
    ("https://weather.gov", "data portal"),
    ("https://www.sec.gov/edgar/searchedgar/companysearch", "form-heavy"),
    ("https://xkcd.com/353/", "comic, image-centric"),
    ("https://motherfuckingwebsite.com", "deliberately unstyled"),
    ("https://bettermotherfuckingwebsite.com", "minimal styled"),
    ("https://danluu.com", "blog index, plain"),
    ("https://blog.codinghorror.com", "blog, themed"),
    ("https://sive.rs/blog", "blog, minimal"),
    ("https://www.rfc-editor.org/rfc/rfc8259.txt", "plain text served"),
    ("https://httpbin.org/html", "synthetic html"),
    ("https://www.wikidata.org/wiki/Q42", "structured data page"),

    # --- second tranche, for the ≥100-page quality audit --------------------
    # The first 55 were chosen for structural variety and that is still the
    # criterion; these widen it where the audit could otherwise generalise
    # from too few of a shape. Notably: more long-form prose (the extraction's
    # best case), more script-rendered shells (its worst), more non-Latin
    # scripts, and more list/table/form-heavy layouts.
    ("https://en.wikipedia.org/wiki/Python_(programming_language)", "wiki, long"),
    ("https://en.wikipedia.org/wiki/History_of_the_Internet", "wiki, prose-heavy"),
    ("https://en.wikipedia.org/wiki/Comparison_of_web_browsers", "wiki, wide tables"),
    ("https://de.wikipedia.org/wiki/Physik", "wiki, german"),
    ("https://fr.wikipedia.org/wiki/Physique", "wiki, french"),
    ("https://es.wikipedia.org/wiki/F%C3%ADsica", "wiki, spanish"),
    ("https://zh.wikipedia.org/wiki/物理学", "wiki, chinese"),
    ("https://ko.wikipedia.org/wiki/물리학", "wiki, korean"),
    ("https://he.wikipedia.org/wiki/פיזיקה", "wiki, hebrew rtl"),
    ("https://hi.wikipedia.org/wiki/भौतिक_शास्त्र", "wiki, devanagari"),
    ("https://el.wikipedia.org/wiki/Φυσική", "wiki, greek"),
    ("https://th.wikipedia.org/wiki/ฟิสิกส์", "wiki, thai no-spaces"),
    ("https://www.gutenberg.org/files/1342/1342-h/1342-h.htm", "book, very long prose"),
    ("https://standardebooks.org/ebooks", "catalogue, cards"),
    ("https://plato.stanford.edu/entries/computability/", "academic long-form"),
    ("https://www.nature.com/articles/d41586-024-00001-0", "journal article"),
    ("https://arxiv.org/abs/2005.14165", "preprint abstract"),
    ("https://arxiv.org/list/cs.CL/recent", "preprint listing"),
    ("https://openaccessbutton.org", "small js shell"),
    ("https://www.loc.gov/collections/", "library collections"),
    ("https://catalog.hathitrust.org/Search/Home?lookfor=library&type=all", "catalogue search"),
    ("https://www.worldcat.org/search?q=library", "catalogue, js shell"),
    ("https://openlibrary.org/subjects/history", "subject listing"),
    ("https://archive.org/details/texts", "archive collection"),
    ("https://www.gutenberg.org/browse/scores/top", "ranked list"),
    ("https://docs.djangoproject.com/en/stable/", "docs, index"),
    ("https://flask.palletsprojects.com/en/stable/", "docs, sidebar"),
    ("https://requests.readthedocs.io/en/latest/", "docs, rtd theme"),
    ("https://numpy.org/doc/stable/reference/generated/numpy.array.html", "docs, api"),
    ("https://developer.mozilla.org/en-US/docs/Web/CSS", "docs, index"),
    ("https://www.postgresql.org/docs/current/sql-select.html", "docs, reference"),
    ("https://man7.org/linux/man-pages/man1/grep.1.html", "man page, pre-heavy"),
    ("https://www.ietf.org/rfc/rfc791.txt", "plain text rfc"),
    ("https://www.rfc-editor.org/rfc/rfc9110.html", "standard, huge"),
    ("https://www.w3.org/TR/wai-aria-1.2/", "standard, dl-heavy"),
    ("https://html.spec.whatwg.org/multipage/", "standard, index"),
    ("https://www.unicode.org/reports/tr9/", "standard, bidi"),
    ("https://tools.ietf.org/html/rfc2119", "standard, short"),
    ("https://www.reuters.com/world/", "news, js shell"),
    ("https://www.aljazeera.com/news/", "news, mixed script"),
    ("https://www.france24.com/en/", "news, french site english"),
    ("https://www.dw.com/en/top-stories/s-9097", "news, german site"),
    ("https://www.cbc.ca/news", "news, canadian"),
    ("https://www.abc.net.au/news", "news, australian"),
    ("https://slashdot.org", "forum, classic"),
    ("https://tildes.net", "forum, minimal"),
    ("https://discourse.julialang.org/latest", "forum, js shell"),
    ("https://stackoverflow.com/questions/tagged/web-scraping", "qa listing"),
    ("https://superuser.com", "qa home"),
    ("https://serverfault.com/questions", "qa listing"),
    ("https://www.reddit.com/r/dataisbeautiful/", "js shell, heavy"),
    ("https://github.com/scrapy/scrapy", "repo, readme"),
    ("https://github.com/trending", "repo listing"),
    ("https://gitlab.com/gitlab-org/gitlab", "repo, js shell"),
    ("https://codeberg.org/explore/repos", "repo listing, small"),
    ("https://pypi.org/search/?q=scraping", "package search"),
    ("https://www.npmjs.com/package/cheerio", "package page, js"),
    ("https://crates.io/search?q=html", "package search, js"),
    ("https://hex.pm/packages", "package listing"),
    ("https://data.gov.uk/search", "gov search"),
    ("https://www.data.gov", "gov portal"),
    ("https://ec.europa.eu/eurostat/web/main/data/database", "gov, nested nav"),
    ("https://www.bls.gov/data/", "gov data index"),
    ("https://www.nasa.gov/news/", "gov news, media"),
    ("https://www.noaa.gov", "gov, media-heavy"),
    ("https://www.irs.gov/forms-instructions", "gov forms"),
    ("https://www.canada.ca/en/services/benefits.html", "gov services"),
    ("https://en.wikisource.org/wiki/Main_Page", "wiki, portal"),
    ("https://commons.wikimedia.org/wiki/Main_Page", "wiki, media portal"),
    ("https://www.wiktionary.org", "wiki, language portal"),
    ("https://stackexchange.com/sites", "site directory"),
    ("https://ftp.gnu.org/gnu/", "directory index"),
    ("https://ftp.debian.org/debian/", "directory index, apache"),
    ("https://neverssl.com", "minimal, no tls"),
    ("https://info.cern.ch/hypertext/WWW/TheProject.html", "the first web page"),
    ("https://www.textfiles.com", "plain, ancient html"),
    ("https://perl.org", "small marketing"),
    ("https://www.php.net/manual/en/function.array-map.php", "docs, user notes"),
    ("https://jsonplaceholder.typicode.com", "api demo page"),
    ("https://httpbin.org/forms/post", "form page"),
    ("https://www.w3schools.com/html/html_forms.asp", "tutorial, form-heavy"),
    ("https://the-internet.herokuapp.com", "test site, many shapes"),
    ("https://scrapethissite.com/pages/forms/", "scrape practice, table"),
    ("https://webscraper.io/test-sites/tables", "scrape practice, tables"),
    ("https://quotes.toscrape.com/scroll", "infinite scroll"),
    ("https://quotes.toscrape.com/js", "js-rendered"),
    ("https://books.toscrape.com/catalogue/page-2.html", "paged listing"),
    ("https://www.imdb.com/title/tt0111161/", "media detail, js"),
    ("https://letterboxd.com/films/popular/", "media listing"),
    ("https://musicbrainz.org/search?query=beatles&type=artist", "catalogue search"),
    ("https://openweathermap.org/city/2643743", "data detail"),
    ("https://finance.yahoo.com/quote/AAPL/", "finance, js heavy"),
    ("https://www.marketwatch.com", "finance news"),
    ("https://coinmarketcap.com", "table, js heavy"),
    ("https://news.google.com", "aggregator, js shell"),
    ("https://duckduckgo.com/?q=web+scraping", "search results, js"),
    ("https://search.marcia.dev", "tiny site"),
    ("https://sqlite.org/lang_select.html", "docs, railroad diagrams"),
    ("https://redis.io/docs/latest/commands/get/", "docs, js"),
    ("https://kubernetes.io/docs/concepts/", "docs, deep nav"),
]


def slug(url: str) -> str:
    s = re.sub(r"^https?://", "", url)
    s = re.sub(r"[^a-zA-Z0-9]+", "-", s).strip("-").lower()
    return s[:80]


def fetch(item: tuple[str, str]) -> dict:
    url, label = item
    rec = {"url": url, "label": label, "slug": slug(url)}
    try:
        r = requests.get(url, timeout=25, headers={"User-Agent": UA},
                         allow_redirects=True)
        rec["status"] = r.status_code
        rec["content_type"] = r.headers.get("Content-Type", "")
        # `requests` follows RFC 2616 and falls back to ISO-8859-1 whenever
        # the Content-Type header carries no charset — ignoring the document's
        # own <meta charset>. Most servers omit it, so `r.text` silently
        # decodes UTF-8 as latin-1 and every non-ASCII character arrives
        # doubly encoded: a price of "£51.33" is stored as "Â£51.33", and
        # since that re-encodes to valid UTF-8 nothing downstream complains.
        # Prefer the header when it is explicit, then the document's own
        # declaration, then chardet's guess.
        if "charset=" not in (rec["content_type"] or "").lower():
            declared = re.search(rb'charset=["\']?([\w-]+)', r.content[:4096])
            rec["encoding_source"] = "document" if declared else "detected"
            r.encoding = (declared.group(1).decode("ascii", "replace")
                          if declared else (r.apparent_encoding or "utf-8"))
        else:
            rec["encoding_source"] = "header"
        rec["encoding"] = r.encoding
        body = r.text
        rec["bytes"] = len(body.encode("utf-8", "replace"))
        rec["sha1"] = hashlib.sha1(body.encode("utf-8", "replace")).hexdigest()
        rec["ok"] = r.status_code == 200 and rec["bytes"] > 200
        if rec["ok"]:
            (CORPUS / f"{rec['slug']}.html").write_text(body, encoding="utf-8",
                                                        errors="replace")
    except Exception as exc:  # noqa: BLE001 — a failed fetch is data
        rec["ok"] = False
        rec["error"] = f"{type(exc).__name__}: {exc}"
    return rec


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--refresh", action="store_true", help="re-fetch existing pages")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    CORPUS.mkdir(parents=True, exist_ok=True)
    todo = [
        (u, l) for u, l in URLS
        if args.refresh or not (CORPUS / f"{slug(u)}.html").exists()
    ]
    print(f"{len(URLS)} urls, {len(todo)} to fetch, {len(URLS)-len(todo)} already frozen")

    records: list[dict] = []
    if todo:
        started = time.time()
        with cf.ThreadPoolExecutor(max_workers=args.workers) as pool:
            for rec in pool.map(fetch, todo):
                records.append(rec)
                mark = "ok " if rec.get("ok") else "FAIL"
                extra = rec.get("error", f"{rec.get('bytes',0):>8,}B  {rec.get('status','')}")
                print(f"  {mark} {rec['slug'][:52]:52s} {extra}")
        print(f"fetched in {time.time()-started:.1f}s")

    # merge with any existing manifest so partial refreshes accumulate
    existing = {}
    if MANIFEST.exists():
        existing = {r["url"]: r for r in json.loads(MANIFEST.read_text())["pages"]}
    for rec in records:
        existing[rec["url"]] = rec

    frozen = [r for r in existing.values()
              if r.get("ok") and (CORPUS / f"{r['slug']}.html").exists()]
    MANIFEST.write_text(json.dumps(
        {"fetched_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
         "note": "frozen benchmark corpus; fetched without JavaScript execution",
         "count": len(frozen),
         "pages": sorted(existing.values(), key=lambda r: r["slug"])},
        indent=2), encoding="utf-8")

    total = sum(r.get("bytes", 0) for r in frozen)
    print(f"\nfrozen: {len(frozen)} pages, {total/1e6:.1f} MB")
    if len(frozen) < 50:
        print(f"WARNING: {len(frozen)} < 50 — re-run, or extend URLS")
    return 0 if len(frozen) >= 50 else 1


if __name__ == "__main__":
    raise SystemExit(main())
