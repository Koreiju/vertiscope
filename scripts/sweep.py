"""The wide sweep: thousands of live pages, run to find out what is wrong.

This is not the corpus audit with a bigger number. The audits ask "did the
output match the reference reading"; this asks two different questions, and
the second is the reason it exists:

1. **Where do the design's claimed properties break?** Uniqueness,
   completeness, repaint, checkpoint identity, partition, termination. Each
   is page-independent, so no page needs a golden file — which is what makes
   a hundred thousand of them affordable.

2. **What shape does the real web actually have?** Branching factor, xpath
   depth, delta ratio, chunk size, control density, text-to-markup ratio,
   shadow-root incidence. The design has no opinion about most of these, and
   that is exactly why they are worth measuring: a cost model built on an
   assumed distribution is wrong in whatever way the assumption was.

A property that fails at scale is ambiguous on purpose. "This property and
this web disagree" — which one gives is a design decision, and the sweep is
here to force it rather than to certify that the design was right.

Nothing is pinned as a threshold until the distribution has been looked at.
Pinning first is how an instrument gets reshaped to agree with what it
measures.

    python scripts/sweep.py --build-frame            # harvest urls from the corpus
    python scripts/sweep.py --limit 2000 --jobs 16   # fetch, process, measure
    python scripts/sweep.py --report                 # distributions, violations
"""

from __future__ import annotations

import argparse
import collections
import gzip
import hashlib
import json
import pathlib
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _force_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


_force_utf8_stdio()

from vertiscope.bench import default_jobs, run_pages, summarise  # noqa: E402

CORPUS = ROOT / "tests" / "corpus"
BUILD = ROOT / "build" / "sweep"
CACHE = BUILD / "pages"
FRAME = BUILD / "frame.json"
RESULTS = BUILD / "results.jsonl"

UA = ("Mozilla/5.0 (compatible; vertiscope-benchmark/1.0; "
      "+https://github.com/local/vertiscope) research crawler")

_HREF = re.compile(r"""<a\b[^>]*\shref\s*=\s*(["'])(.*?)\1""", re.I | re.S)


# --- the frame --------------------------------------------------------------


_DISCOVER_DRIVER = None


def _discover_driver():
    """One browser per worker, for parallel discovery.

    Discovery was single-browser and ~9 s a query; at the query volume a
    10,000-page frame needs that is most of a day before a single page is
    swept. Same browser-per-worker shape the live sweep uses.
    """
    global _DISCOVER_DRIVER
    if _DISCOVER_DRIVER is None:
        import atexit
        from vertiscope.browser import build_driver
        from vertiscope.config import load_config
        _DISCOVER_DRIVER = build_driver(load_config(), headless=True)

        def _quit():
            global _DISCOVER_DRIVER
            if _DISCOVER_DRIVER is not None:
                try:
                    _DISCOVER_DRIVER.quit()
                except Exception:
                    pass
                _DISCOVER_DRIVER = None
        atexit.register(_quit)
    return _DISCOVER_DRIVER


def discover_one(task: dict) -> dict:
    """One query -> its result urls. Runner entry point.

    Per-host capping happens when the frame is assembled, not here: a worker
    cannot see what the others found, and capping locally would let a host
    through once per worker.
    """
    import urllib.parse as _up
    from vertiscope.capture import deep_serialize, drive_to_settled
    from vertiscope.pipeline import run_pipeline

    query = task["page"]
    search = "https://duckduckgo.com/?q=" + _up.quote_plus(query)
    driver = _discover_driver()
    drive_to_settled(driver, search, max_duration=12, pause=1.0)
    html = deep_serialize(driver).html

    found = []
    for tag in run_pipeline(html, search).tagged.all_tags:
        if not str(getattr(tag, "category", "")).startswith("urls"):
            continue
        url = str(getattr(tag, "value", "")).strip()
        parsed = _up.urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            continue
        host = parsed.netloc.lower()
        if _is_engine_plumbing(host, url):
            continue
        found.append({"url": parsed._replace(fragment="").geturl(),
                      "host": host, "query": query})
    return {"page": query, "found": found}


def build_frame(per_host: int = 12, browsers: int = 4) -> list:
    """Discover pages by searching, in parallel, the way a person finds them.

    The first version harvested outbound hrefs from the frozen corpus. That is
    in-silico: the corpus links to what the corpus already links to, so the
    frame inherits precisely the taste it was meant to escape.

    Searching instead, through the project's own scraper against DuckDuckGo,
    reading the result page with the project's own tagger. The discovery step
    is therefore itself a live exercise of the component under test, on the
    result-page layout a user meets whenever they search.

    Capping is done here, on assembly, rather than inside a worker: a worker
    cannot see what its siblings found, so a local cap would admit each host
    once per worker.
    """
    queries = generate_queries()
    print(f"discovering from {len(queries)} queries, {browsers} browsers")

    tasks = [{"page": q} for q in queries]
    seen, by_host = set(), collections.Counter()
    frame = []
    done = failed = 0
    started = time.perf_counter()

    for row in run_pages(tasks, discover_one, jobs=browsers, timeout=180,
                         results_path=BUILD / "discovery.jsonl"):
        done += 1
        if "error" in row:
            failed += 1
            continue
        for entry in row.get("found", []):
            url, host = entry["url"], entry["host"]
            if url in seen or by_host[host] >= per_host:
                continue
            seen.add(url)
            by_host[host] += 1
            frame.append(entry)
        if done % 25 == 0:
            rate = done / (time.perf_counter() - started) * 60
            print(f"  {done:,}/{len(tasks):,} queries  {len(frame):,} urls  "
                  f"{rate:.0f} q/min  {failed} failed", flush=True)
            # Checkpointed: hours of live browsing should not be lost to one
            # dead driver, and the sweep can start on what is already there.
            FRAME.write_text(json.dumps(frame, indent=1), encoding="utf-8")

    # Assemble from the whole recorded log, not from this run's yields. A
    # resumed run is handed only the queries it still had to do, so building
    # the frame from what it yielded silently drops every url discovered
    # before the interruption — the frame would shrink each time it resumed.
    frame, seen, by_host = [], set(), collections.Counter()
    log = BUILD / "discovery.jsonl"
    if log.exists():
        for line in log.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            for entry in row.get("found") or []:
                url, host = entry.get("url"), entry.get("host")
                if not url or url in seen or by_host[host] >= per_host:
                    continue
                seen.add(url)
                by_host[host] += 1
                frame.append(entry)

    print(f"  {done:,} queries this run, {failed} failed; "
          f"{len(frame):,} urls over {len(by_host):,} hosts in the log")
    return frame


# Hosts that are the search engine talking to itself rather than a result.
# Kept narrow on purpose: over-filtering here would quietly re-impose the
# curation the search is meant to avoid.
_ENGINE = ("duckduckgo.com", "duck.com", "duck.ai", "spreadprivacy.com")


def _is_engine_plumbing(host: str, url: str = "") -> bool:
    """Reject the engine promoting itself, not merely the engine's own host.

    Measured on the first two queries: a host check alone let through the App
    Store and Play Store listings for the DuckDuckGo browser, its Substack,
    and `reddit.com/r/duckduckgo` — five of the first fifteen "results" were
    the search engine advertising itself, and every query would have
    contributed the same five, biasing the frame toward them enormously.

    So the product name anywhere in the url disqualifies it. That also drops
    any page genuinely *about* DuckDuckGo, which is a real if tiny loss, and
    the right trade: those pages are a rounding error, the promo links are on
    every single result page.
    """
    if any(host == h or host.endswith("." + h) for h in _ENGINE):
        return True
    return "duckduckgo" in url.lower() or "duck.ai" in url.lower()


def generate_queries() -> list:
    """Open-ended queries spanning genre, language, script and specificity.

    Deliberately not a topic list I would defend as balanced — the point is
    to hand the choice to a search engine over a wide spread of prompts, so
    the frame is not another exercise of my taste in example pages.
    """
    topics = [
        "municipal budget minutes", "protein folding review", "sourdough hydration",
        "railway timetable archive", "second hand tractor parts", "hurricane track model",
        "medieval manuscript catalogue", "tax residency rules", "guitar pedal schematic",
        "clinical trial results", "planning permission appeal", "bird migration atlas",
        "compiler optimisation pass", "shipping container tracking", "opera libretto",
        "soil moisture sensor", "insurance claim dispute", "mountain hut booking",
        "dialect survey map", "semiconductor shortage", "recipe fermented chili",
        "public transit gtfs feed", "patent claim construction", "glacier retreat data",
        "amateur radio propagation", "school district boundaries", "typography kerning",
        "fishing licence rules", "earthquake early warning", "museum accession record",
        "wildfire smoke forecast", "bicycle frame geometry", "census tract income",
        "antibiotic resistance surveillance", "film restoration process",
        "harbour tide tables", "beekeeping disease", "chess endgame tablebase",
        "solar inverter efficiency", "archaeological dig report",
        "court docket search", "building code egress", "seed bank catalogue",
        "tide mill restoration", "vaccine cold chain", "peat bog carbon",
        "orbital debris tracking", "sign language corpus", "ferry crossing fares",
        "hospital waiting times", "rare earth refining", "canal lock operation",
        "urban heat island", "textile dye process", "avalanche forecast",
        "watermill grain milling", "coral bleaching survey", "lighthouse automation",
        "prison population statistics", "wind farm noise", "aquifer depletion",
        "typeface licensing", "railway signalling interlocking", "cheese ripening cave",
        "asteroid spectral class", "landfill methane capture", "bus rapid transit",
        "herbarium specimen digitisation", "flood insurance mapping",
        "cathode material battery", "birdsong classification", "kelp forest restoration",
        "timber frame joinery", "radio telescope array", "permafrost thaw",
        "olive oil adulteration", "subway ventilation", "hedgerow biodiversity",
    ]
    languages = [
        "biblioteca universitaria historia", "bibliothèque nationale archives",
        "Universitätsbibliothek Bestand", "大学 図書館 蔵書", "도서관 소장 자료",
        "مكتبة جامعية أرشيف", "библиотека университета архив",
        "पुस्तकालय विश्वविद्यालय", "biblioteca universitária acervo",
        "kütüphane üniversite arşiv",
    ]
    shapes = [
        "site:gov.uk consultation", "filetype:pdf annual report",
        "forum thread troubleshooting", "documentation api reference",
        "product listing price comparison", "live scoreboard",
        "interactive dashboard data", "job listings remote",
        "conference proceedings 2024", "wiki disambiguation page",
    ]
    # Measured: 60 queries yielded 801 urls over 572 hosts, 8-24 per query and
    # never zero. So the frame's size is set by the number of queries, not by
    # anything about the extraction — and 801 is not a benchmark.
    #
    # Crossing the topics with modifiers is what gets to five figures. It also
    # improves the frame rather than merely enlarging it: "hurricane track
    # model dataset" and "hurricane track model forum" reach different corners
    # of the web, so the cross buys genre spread as well as volume.
    modifiers = [
        "", "dataset", "forum", "tutorial", "archive", "pdf", "api",
        "map", "statistics", "criticism", "history", "regulations",
        "prices", "schedule", "reviews", "glossary", "photos", "database",
        "case study", "specification", "manual", "comparison", "news",
        "research paper",
    ]
    crossed = [f"{topic} {modifier}".strip()
               for topic in topics for modifier in modifiers]
    return crossed + languages + shapes


# --- fetching ---------------------------------------------------------------


def cache_path(url: str) -> pathlib.Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()
    return CACHE / digest[:2] / f"{digest}.html.gz"


def fetch(url: str, timeout: float = 20.0,
          max_bytes: int = 8_000_000) -> tuple:
    """Fetch once, cache forever.

    The cache is what makes a sweep reproducible: a run is pinned to content
    hashes, so a regression is attributable to our code rather than to a site
    redesigning itself between runs. It is also what makes re-running free,
    which is what makes it get re-run.
    """
    path = cache_path(url)
    meta_path = path.with_suffix(".ct")
    if path.exists():
        with gzip.open(path, "rt", encoding="utf-8", errors="replace") as fh:
            text = fh.read()
        ctype = (meta_path.read_text(encoding="utf-8").strip()
                 if meta_path.exists() else "")
        return text, ctype

    request = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,text/plain;q=0.9,*/*;q=0.5",
        "Accept-Language": "en",
    })
    with urllib.request.urlopen(request, timeout=timeout) as response:
        raw = response.read(max_bytes)
        charset = response.headers.get_content_charset() or "utf-8"
        # Kept, because without it the sweep cannot tell a PDF from a page
        # except by guessing at the url, and plenty of documents are served
        # from extensionless paths. The first wide run could only say "6.3%
        # of the frame ends in .pdf", which is a fact about url spelling.
        ctype = (response.headers.get_content_type() or "").lower()
    text = raw.decode(charset, errors="replace")

    path.parent.mkdir(parents=True, exist_ok=True)
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        fh.write(text)
    path.with_suffix(".ct").write_text(ctype, encoding="utf-8")
    return text, ctype


# --- the measurement --------------------------------------------------------


def measure_url(page: dict) -> dict:
    """Everything one page can tell us, in one pass.

    Violations and distributions come back together because they are the same
    walk: separating them would double the cost of the expensive part for no
    gain, and would let the two drift out of step about which page they saw.
    """
    from vertiscope.address import collisions
    from vertiscope.fidelity import measure as fidelity_measure
    from vertiscope.markdown import render_trie
    from vertiscope.pipeline import run_pipeline
    from vertiscope.repl.model import Document
    from vertiscope.trie import AddressTrie

    url = page["url"]
    started = time.perf_counter()
    html, ctype = fetch(url)
    fetched = time.perf_counter() - started

    result = run_pipeline(html, url)
    tags = result.tagged.all_tags
    trie = AddressTrie.from_tagged(result.tagged, url)
    chunks = render_trie(trie, context_window=1200)
    lines = [ln for c in chunks for ln in c.lines]
    doc = Document.from_chunks(chunks)

    # --- violations: what the design claims -------------------------------
    collided = collisions(tags, url)
    repaint_bad = sum(1 for w, ln in zip(doc.lines, lines)
                      if w.render() != "  " * ln.depth + ln.text)
    addressed = sum(1 for ln in lines if ln.address is not None)

    # --- distributions: what the design has no opinion about --------------
    depths = [ln.address.xpath.count("/") for ln in lines if ln.address]
    chunk_sizes = [sum(len(ln.text) for ln in c.lines) for c in chunks]
    text_chars = sum(len(ln.text) for ln in lines)
    kinds = collections.Counter(w.kind.value for w in doc.lines)

    return {
        "page": url,
        "host": page.get("host", ""),
        "content_type": ctype,
        "bytes": len(html),
        "fetch_seconds": round(fetched, 2),
        # violations
        "collisions": len(collided),
        "repaint_bad": repaint_bad,
        "unaddressed": len(lines) - addressed,
        "detections": len(tags),
        # distributions
        "lines": len(lines),
        "chunks": len(chunks),
        "median_chunk_chars": (sorted(chunk_sizes)[len(chunk_sizes) // 2]
                               if chunk_sizes else 0),
        "max_chunk_chars": max(chunk_sizes) if chunk_sizes else 0,
        "median_xpath_depth": (sorted(depths)[len(depths) // 2]
                               if depths else 0),
        "max_xpath_depth": max(depths) if depths else 0,
        "branching": round(len(tags) / len(lines), 3) if lines else 0.0,
        "text_ratio": round(text_chars / len(html), 4) if html else 0.0,
        "control_density": round(
            sum(v for k, v in kinds.items() if k != "text") / len(lines), 4
        ) if lines else 0.0,
        "empty": len(lines) == 0,
    }


# --- reporting --------------------------------------------------------------


def report(rows: list) -> None:
    good = [r for r in rows if "error" not in r]
    print("=" * 78)
    print(f"SWEEP — {len(rows):,} pages, {len(good):,} processed, "
          f"{len(rows) - len(good):,} failed")
    print("=" * 78)

    print("\nVIOLATIONS — where the design's claims broke")
    for field, claim in [("collisions", "no address carries two values"),
                         ("repaint_bad", "every line repaints to itself"),
                         ("unaddressed", "every line carries an address")]:
        pages = [r for r in good if r.get(field)]
        total = sum(r[field] for r in pages)
        rate = len(pages) / len(good) if good else 0
        mark = "  <-- LOOK" if pages else ""
        print(f"  {field:14s} {len(pages):5d} pages ({rate:6.2%}), "
              f"{total:8,} instances   {claim}{mark}")

    # What kind of documents these actually are. The first wide run found
    # every extreme value — the RecursionErrors, the 208-deep xpath, the
    # 235k-character chunk — on PDFs being parsed as markup, so the share is
    # not a footnote: it is the population the tail is drawn from.
    kinds = collections.Counter(r.get("content_type", "") or "unknown"
                                for r in good)
    non_html = sum(n for ct, n in kinds.items()
                   if ct and not ct.startswith("text/html"))
    if good:
        print(f"\n  content types: {non_html:,} of {len(good):,} "
              f"({non_html/len(good):.1%}) are not text/html")
        for ctype, count in kinds.most_common(6):
            print(f"    {count:6,}  {ctype}")

    empty = [r for r in good if r.get("empty")]
    print(f"  {'empty output':14s} {len(empty):5d} pages "
          f"({len(empty)/len(good) if good else 0:6.2%})"
          f"{'  <-- LOOK' if empty else ''}")

    print("\nDISTRIBUTIONS — what the web is actually shaped like")
    stats = summarise(good, [
        "lines", "chunks", "branching", "median_xpath_depth", "max_xpath_depth",
        "median_chunk_chars", "max_chunk_chars", "text_ratio",
        "control_density", "bytes", "seconds"])
    print(f"  {'field':22s} {'p50':>12s} {'p90':>12s} {'p99':>12s} {'max':>12s}")
    for field, values in stats.items():
        if not isinstance(values, dict):
            continue
        print(f"  {field:22s} {values['p50']:12.3f} {values['p90']:12.3f} "
              f"{values['p99']:12.3f} {values['max']:12.3f}")

    errors = collections.Counter(
        r["error"].split(":")[0] for r in rows if "error" in r)
    if errors:
        print("\nFAILURES by kind")
        for kind, count in errors.most_common(12):
            print(f"  {count:6d}  {kind}")


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--build-frame", action="store_true")
    ap.add_argument("--per-host", type=int, default=12)
    ap.add_argument("--browsers", type=int, default=4,
                    help="parallel browsers for discovery")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--jobs", type=int, default=default_jobs())
    ap.add_argument("--timeout", type=float, default=120.0)
    ap.add_argument("--frame", type=pathlib.Path,
                    help="frame file to sweep (default: the discovered one). "
                         "Lets a sweep run against a finished frame while "
                         "discovery is still writing the live one.")
    ap.add_argument("--results", type=pathlib.Path)
    ap.add_argument("--report", action="store_true",
                    help="report over results already recorded")
    args = ap.parse_args()

    BUILD.mkdir(parents=True, exist_ok=True)

    if args.build_frame:
        frame = build_frame(per_host=args.per_host,
                            browsers=args.browsers)
        FRAME.write_text(json.dumps(frame, indent=1), encoding="utf-8")
        hosts = collections.Counter(f["host"] for f in frame)
        print(f"frame: {len(frame):,} urls across {len(hosts):,} hosts")
        for host, count in hosts.most_common(8):
            print(f"  {count:4d}  {host}")
        print(f"\nwrote {FRAME}")
        return 0

    if args.report:
        rows = [json.loads(l) for l in
                (args.results or RESULTS).read_text(
                    encoding="utf-8").splitlines() if l.strip()]
        report(rows)
        return 0

    frame_path = args.frame or FRAME
    results_path = args.results or RESULTS
    if not frame_path.exists():
        print("no frame yet; run --build-frame")
        return 2
    frame = json.loads(frame_path.read_text(encoding="utf-8"))
    # Seeded shuffle. The frame comes out grouped by the page that linked
    # each url, so consecutive entries share a host — and sixteen workers
    # marching through it in order would hit one host with sixteen concurrent
    # requests while the rest of the web sat idle. Spreading them is both the
    # polite thing and the one that keeps the sweep from measuring a single
    # site's rate limiter. Seeded so a run is reproducible.
    import random
    random.Random(20260815).shuffle(frame)
    if args.limit:
        frame = frame[: args.limit]
    work = [{"page": f["url"], "url": f["url"], "host": f["host"]} for f in frame]

    print(f"sweeping {len(work):,} pages with {args.jobs} workers")
    started = time.perf_counter()
    rows, done = [], 0
    for row in run_pages(work, measure_url, jobs=args.jobs,
                         timeout=args.timeout, results_path=results_path):
        rows.append(row)
        done += 1
        if done % 50 == 0:
            rate = done / (time.perf_counter() - started)
            print(f"  {done:,}/{len(work):,}  {rate:.1f} pages/s  "
                  f"{sum(1 for r in rows if 'error' in r):,} failed")

    all_rows = [json.loads(l) for l in
                results_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    report(all_rows)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
