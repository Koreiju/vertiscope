"""How good is the extraction, judged against the page it came from?

Every other measurement here is *internal*: addresses are unique, chunks
partition the addresses, the accounting balances. All of that can hold
perfectly while the markdown is garbage, because none of it ever compares the
output to the input.

This does. For each page it builds a **reference** reading of the source —
the visible text, taken straight from the HTML with script/style/comments
removed and entities resolved — and asks what the pipeline did with it.

    recall        of the reference's content words, how many survive
    headings      of the source's h1-h6, how many appear as markdown headings
    links         of the source's anchors, how many are addressed
    plumbing      share of output lines that reference a resource
                  (a <head> asset or a <script>/<link>), rather than
                  being content — body links and images are content
    duplication   share of output lines that repeat an earlier line verbatim
    anchored      share of output lines carrying a resolvable address
    density       output characters per source character

None is a verdict on its own. Recall alone rewards dumping every byte;
plumbing alone rewards dropping everything. They are reported together, per
page, with the worst pages named, because that is where a reading is worth
making by eye.

The reference is deliberately crude — a regex strip, not a second extractor.
A sophisticated reference would encode its own opinions about boilerplate,
and then the audit would measure agreement between two opinions rather than
coverage of the page.

    python scripts/audit_quality.py                 # the whole corpus
    python scripts/audit_quality.py --worst 12      # name the worst pages
    python scripts/audit_quality.py --page wikipedia --show
"""

from __future__ import annotations

import argparse
import html as html_mod
import json
import pathlib
import re
import statistics as stats
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _force_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


_force_utf8_stdio()

from vertiscope.markdown import render_trie  # noqa: E402
from vertiscope.pipeline import run_pipeline  # noqa: E402
from vertiscope.trie import AddressTrie  # noqa: E402

CORPUS = ROOT / "tests" / "corpus"
MANIFEST = CORPUS / "manifest.json"

_DROP = re.compile(
    r"<(script|style|noscript|template|svg)\b.*?</\1>|<!--.*?-->",
    re.S | re.I)
# Deliberately naive, and the naivety is *diagnosed* rather than unnoticed.
#
# A quoted attribute value may contain `>`, and `<[^>]+>` stops at the first
# one. Wikipedia's `data-mw='{"parts":…}'` holds the article's raw wikitext,
# so 5,825 characters of it — editor comments, `\n` escapes and all — leak out
# of one `<span>` as "text". Those 69 words are the whole of the corpus's
# worst word recall, 97.6%: the extraction is right to ignore an attribute and
# this reference is wrong to read one.
#
# A quote-aware pattern was written and measured, and it is much worse: an
# apostrophe in ordinary prose ("Python's") opens a quote that swallows every
# character up to the next one. Corpus recall fell 97.6% -> 63.0% and
# books.toscrape.com's heading recall 100% -> 4.8%. Reverted.
#
# Getting this right needs a tokenizer, not a regex — and a tokenizer is a
# second HTML parser, which is exactly what this reference exists to avoid.
# The 2.4% is the price of that choice, now with a name on it.
_TAGS = re.compile(r"<[^>]+>")
_HEADING = re.compile(r"<h([1-6])\b[^>]*>(.*?)</h\1>", re.S | re.I)
# The value ends at the quote that *opened* it, captured and back-referenced.
# `[^"']+` stops at either, so a double-quoted href holding an apostrophe was
# truncated: `workers.html#the-worker's-lifetime` was read as
# `workers.html#the-worker`, and the whatwg and w3 specs — full of anchors
# like `#writing-a-form's-user-interface` — scored 82.1% link recall while
# every one of their links had been addressed in full.
#
# Unlike `_TAGS` above, this one is exactly fixable: an attribute value is
# delimited by its own opening quote, and a backreference says so.
_ANCHOR = re.compile(r"""<a\b[^>]*\shref\s*=\s*(["'])(.*?)\1""", re.I | re.S)
_WORD = re.compile(r"[^\W\d_]{3,}", re.UNICODE)

# Lines that are a url or an image rather than prose. Not "wrong" — an address
# to a stylesheet is a true fact about the page — but they are not what a
# reader came for, so their share is worth watching.
#
# Code spans were counted here at first and should not be: a `<pre>` block is
# the page's own content, and a text/plain document renders entirely as one
# (browsers wrap it in `<pre>`), so RFC 791 scored 100% "noise" while being
# 100% content. The metric was wrong, not the extraction.
_ASSET_LINE = re.compile(r"^\s*(<[^>]*>|!\[[^\]]*\]\(.*\))\s*$")


def visible_text(source: str) -> str:
    """The page's own words, with markup removed. The reference reading.

    **Known incomplete.** The corpus's worst word recall is 97.6%, on
    en.wikipedia.org's Python article, and the 69 "lost" words are things like
    `afaik`, `nalso` and `cygwin` — editor chatter out of raw wikitext that
    Wikipedia ships inside its config payload, with newlines as literal `\\n`.
    A browser renders none of it, so the extraction is right not to emit it
    and this function is wrong to ask for it.

    Two theories were tried before the right one. Stripping `&lt;!--…--&gt;`
    removes **0 characters** from that page. The payload is not in a comment
    and not in a `<script>` — it is in an *attribute*, `data-mw`, and it
    survives because `_TAGS` stops at the first `>` inside it. See the comment
    on `_TAGS`, including why the obvious quote-aware fix is worse.
    """
    stripped = _DROP.sub(" ", source)
    return html_mod.unescape(_TAGS.sub(" ", stripped))


def words(text: str) -> set:
    return {m.group(0).lower() for m in _WORD.finditer(text)}


def headings_of(source: str) -> list:
    out = []
    for _level, inner in _HEADING.findall(_DROP.sub(" ", source)):
        text = " ".join(html_mod.unescape(_TAGS.sub(" ", inner)).split())
        if text:
            out.append(text)
    return out


def measure(path: pathlib.Path, url: str, window: int = 1200) -> dict:
    source = path.read_text(encoding="utf-8", errors="replace")
    trie = AddressTrie.from_tagged(run_pipeline(source, url).tagged, url)
    chunks = render_trie(trie, context_window=window)

    lines = [line for chunk in chunks for line in chunk.lines]
    rendered = "\n".join(line.text for line in lines)

    ref_words = words(visible_text(source))
    got_words = words(rendered)
    recall = len(ref_words & got_words) / len(ref_words) if ref_words else 1.0

    # Containment, not equality. Two reasons, both of them the reference's
    # fault rather than the pipeline's:
    #
    #   * the pipeline reads `alt` and `aria-label`, so a heading whose only
    #     text is `{ix}` and whose word is in an `<img alt="PREFACE.">` comes
    #     out as "PREFACE. {ix}" — *better* than the source's visible text,
    #     and an exact match scored it a miss;
    #   * `<h([1-6])\b[^>]*>(.*?)</h\1>` over real markup occasionally spans
    #     from one heading to a distant close tag, so the reference itself
    #     produces fragments and run-ons.
    #
    # A source heading counts as found when its words are contained in some
    # rendered heading. That still fails if a heading is dropped or truncated,
    # which is what the metric is for.
    # One heading line, or a short run of consecutive ones. A heading built
    # from parts — `<h3><div>Technology</div><span>The backlash…</span></h3>`
    # — renders as two heading lines, in order, which is correct and which a
    # single-line test scored as a miss on 103 of the Guardian's 181 headings.
    # Three is the widest run allowed, so this cannot degenerate into "the
    # words appear somewhere".
    heads = headings_of(source)
    md_heads = [set(words(line.text.lstrip("#")))
                for line in lines if line.text.startswith("#")]
    found_heads = 0
    for heading in heads:
        want = words(heading)
        if not want:
            found_heads += 1
            continue
        for start in range(len(md_heads)):
            run: set = set()
            for span in range(3):
                if start + span >= len(md_heads):
                    break
                run |= md_heads[start + span]
                if want <= run:
                    break
            if want <= run:
                found_heads += 1
                break
    heading_recall = found_heads / len(heads) if heads else 1.0

    # Unescaped, because the extractor resolves entities and the source does
    # not: `skip=0&amp;show=50` on the page is `skip=0&show=50` once parsed.
    # Comparing the raw strings scored arxiv at 47% link recall while every
    # one of those links was addressed correctly — the metric was wrong, not
    # the extraction.
    hrefs = {html_mod.unescape(m.group(2))
             for m in _ANCHOR.finditer(_DROP.sub(" ", source))}
    hrefs = {h for h in hrefs if not h.startswith(("javascript:", "#"))}
    addressed = {node.value for node in trie.leaves()
                 if node.address is not None
                 and node.address.category == "urls"}
    link_recall = (len(hrefs & addressed) / len(hrefs)) if hrefs else 1.0

    # "Noise" counted every url and image line, which is 41% of the output and
    # was reported as a quality problem for most of a day. Decomposed over
    # five pages, 9,442 lines:
    #
    #     38.2%  a url in the page body        <- the payload
    #     13.2%  an image in the page body     <- the payload
    #      6.0%  a <script>/<link> in the body
    #      2.4%  an asset in <head>
    #
    # Body links and images are exactly what a content-addressing scraper
    # exists to capture. Only the last two are plumbing — a reference to a
    # resource rather than a fact about the content — and they are 8.4%, not
    # 41%. The metric was measuring the point of the system and calling it
    # noise.
    def _is_plumbing(line) -> bool:
        if not _ASSET_LINE.match(line.text):
            return False
        xpath = line.address.xpath if line.address else ""
        return ("/head/" in xpath or xpath.endswith("/head")
                or "/script" in xpath or "/link" in xpath)

    asset = sum(1 for line in lines if _is_plumbing(line))
    seen, dupes = set(), 0
    for line in lines:
        key = line.text.strip()
        if key and key in seen:
            dupes += 1
        seen.add(key)
    anchored = sum(1 for line in lines if line.address is not None)

    return {
        "page": path.stem,
        "source_chars": len(source),
        "ref_words": len(ref_words),
        "lines": len(lines),
        "chunks": len(chunks),
        "recall": recall,
        "heading_recall": heading_recall,
        "headings": len(heads),
        "link_recall": link_recall,
        "links": len(hrefs),
        "noise": asset / len(lines) if lines else 0.0,   # plumbing share
        "duplication": dupes / len(lines) if lines else 0.0,
        "anchored": anchored / len(lines) if lines else 1.0,
        "density": len(rendered) / len(source) if source else 0.0,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--page", help="substring of a corpus page stem")
    ap.add_argument("--window", type=int, default=1200)
    ap.add_argument("--worst", type=int, default=8,
                    help="how many worst-recall pages to name")
    ap.add_argument("--show", action="store_true",
                    help="print the words the reference has and the output lost")
    ap.add_argument("--json", type=pathlib.Path)
    args = ap.parse_args()

    urls = {}
    if MANIFEST.exists():
        urls = {p["slug"]: p["url"]
                for p in json.loads(MANIFEST.read_text(encoding="utf-8"))["pages"]}

    pages = sorted(CORPUS.glob("*.html"))
    if args.page:
        pages = [p for p in pages if args.page in p.stem]
    if not pages:
        print("no corpus pages")
        return 2

    print("=" * 100)
    print("EXTRACTION QUALITY — the output, against the page it came from")
    print("=" * 100)
    print(f"{'page':42s} {'KB':>5s} {'lines':>6s} {'recall':>7s} "
          f"{'head':>6s} {'links':>6s} {'noise':>6s} {'dup':>6s} {'anch':>6s} "
          f"{'dens':>6s}")
    print("-" * 100)

    rows = []
    for path in pages:
        url = urls.get(path.stem) or f"https://{path.stem}/"
        try:
            row = measure(path, url, window=args.window)
        except Exception as exc:  # noqa: BLE001
            print(f"{path.stem[:42]:42s} {type(exc).__name__}: {exc}")
            rows.append({"page": path.stem, "error": str(exc)})
            continue
        rows.append(row)
        print(f"{row['page'][:42]:42s} {row['source_chars']/1024:5.0f} "
              f"{row['lines']:6d} {row['recall']:7.1%} "
              f"{row['heading_recall']:6.0%} {row['link_recall']:6.0%} "
              f"{row['noise']:6.0%} {row['duplication']:6.0%} "
              f"{row['anchored']:6.0%} {row['density']:6.1%}")

        if args.show:
            source = path.read_text(encoding="utf-8", errors="replace")
            trie = AddressTrie.from_tagged(run_pipeline(source, url).tagged, url)
            got = words("\n".join(
                line.text for chunk in render_trie(trie, context_window=args.window)
                for line in chunk.lines))
            lost = sorted(words(visible_text(source)) - got)
            print(f"      lost {len(lost)} word(s); a sample: {lost[:24]}")

    ok = [r for r in rows if "error" not in r]
    if not ok:
        return 1

    print("-" * 100)
    print(f"pages {len(ok)}   failed {len(rows) - len(ok)}")
    for name in ("recall", "heading_recall", "link_recall", "noise",
                 "duplication", "anchored", "density"):
        values = [r[name] for r in ok]
        print(f"  {name:15s} median {stats.median(values):6.1%}   "
              f"mean {stats.mean(values):6.1%}   "
              f"min {min(values):6.1%}   max {max(values):6.1%}")

    print(f"\n  worst {args.worst} by word recall")
    for row in sorted(ok, key=lambda r: r["recall"])[:args.worst]:
        print(f"    {row['recall']:6.1%}  {row['page'][:44]:44s} "
              f"{row['ref_words']:6d} reference words, {row['lines']:5d} lines")

    empty = [r for r in ok if r["lines"] == 0]
    if empty:
        print(f"\n  produced NOTHING: {len(empty)}")
        for row in empty:
            print(f"    {row['page'][:50]:50s} {row['ref_words']} reference words")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
