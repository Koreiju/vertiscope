"""Does `vertiscope browse`'s `controls` command find the controls?

The REPL offers pagination, menus, filters and search boxes by name. They are
not new content categories — they are *readings* of the interactive addresses
already extracted, made in `vertiscope/repl/nav.py::classify_controls` from the
element label and the xpath.

The unit test for that function feeds it five hand-written labels ("Next
page", "Previous", "Search", "Filter by category", "ordinary text") and checks
that they land in the buckets those words name. That proves the words are
spelled the same in the test and the implementation. It does not prove the
function is any use on a page.

This runs the real path over the frozen corpus —

    html -> pipeline -> trie -> markdown -> Document -> classify_controls

— and reports, per page, what was classified and what a human would have
wanted. The `EXPECTED` table below is the part that carries information: pages
whose pagination or search box is known from the HTML, named here so the audit
can say *missed* rather than only *found*.

    python scripts/audit_controls.py
    python scripts/audit_controls.py --page news-ycombinator-com --show
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vertiscope.markdown import render_trie  # noqa: E402
from vertiscope.pipeline import run_pipeline  # noqa: E402
from vertiscope.repl.model import Document  # noqa: E402
from vertiscope.repl.nav import attach_context, classify_controls  # noqa: E402
from vertiscope.trie import AddressTrie  # noqa: E402

CORPUS = ROOT / "tests" / "corpus"

# Pages whose controls are known from the HTML, by inspection.
#
# A role mapped to a non-empty list asserts those controls are *found*; a role
# mapped to an empty list asserts the bucket is *empty*, which is the only
# check that can catch a classifier that has become generous. A role left out
# asserts nothing.
#
# The strings are what a *user* would recognise, matched case-insensitively
# against the visible text the REPL shows — not against the href, and not
# against the words `classify_controls` keys on, or this would be the same
# tautology one level up.
#
# Three entries here were wrong when first written, and the corrections are
# left visible because they are the more useful half of the exercise:
#
#   archive.org, gitlab   asserted a search box. Both frozen pages are
#                         JavaScript shells — zero `<input>`, zero `<form>`
#                         in the file. Nothing could have found a control
#                         that is not there, and "fixing" the classifier to
#                         satisfy this would have been fitting to a mistake.
#   arxiv "all"           the only "all" in the source is
#                         `<input type="hidden" name="searchtype" value="all">`
#                         — part of the search form, not a pager.
EXPECTED: dict[str, dict[str, list[str]]] = {
    "news-ycombinator-com": {"pagination": ["More"]},
    "news-ycombinator-com-newest": {"pagination": ["More"]},
    "books-toscrape-com": {"pagination": ["next"]},
    "quotes-toscrape-com": {"pagination": ["Next"]},
    "old-reddit-com-r-programming": {"pagination": ["next"]},
    "arxiv-org-list-cs-ir-recent": {"pagination": ["more"]},
    "openlibrary-org-search-q-telescope": {"search": ["search"]},
    # No pager in the source: single-page listings.
    "www-scrapethissite-com-pages-simple": {"pagination": []},
    "webscraper-io-test-sites-e-commerce-allinone": {"pagination": []},
    "example-com": {"pagination": [], "search": []},
    "xkcd-com-353": {"search": []},
    "motherfuckingwebsite-com": {"pagination": [], "search": []},
    # A JavaScript shell: no form, no input, no anchor pager in the file.
    "archive-org-search-query-university-library": {"search": [],
                                                    "pagination": []},
    "gitlab-com-explore-projects": {"search": []},
}

ROLES = ("pagination", "search", "filter", "menu")


MANIFEST = CORPUS / "manifest.json"
_URLS = {p["slug"]: p["url"]
         for p in json.loads(MANIFEST.read_text(encoding="utf-8"))["pages"]}


def controls_of(path: pathlib.Path) -> dict:
    """Run the real REPL path and return the classified roles.

    The page's *real* url, from the manifest — not one synthesised from the
    filename. Pagination is partly a question about where a link goes
    relative to where it was found, so a made-up base url makes the answer
    made up too.
    """
    html = path.read_text(encoding="utf-8", errors="replace")
    url = _URLS.get(path.stem) or f"https://{path.stem.replace('-', '.')}/"
    result = run_pipeline(html, url)
    trie = AddressTrie.from_tagged(result.tagged, url)
    chunks = render_trie(trie, context_window=1200)
    document = Document.from_chunks(chunks, url=url)
    lines = [w for w in document.lines if w.address is not None]
    pairs = [(w.address, w.label) for w in lines if w.interactive]
    texts = [(w.address.xpath, w.label) for w in lines if not w.interactive]
    entries = attach_context(pairs, texts)
    return classify_controls(entries), len(document.lines), len(pairs)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--page", help="one corpus page (stem), else all")
    ap.add_argument("--show", action="store_true",
                    help="print every classified control, not just counts")
    ap.add_argument("--json", type=pathlib.Path)
    args = ap.parse_args()

    pages = sorted(CORPUS.glob("*.html"))
    if args.page:
        pages = [p for p in pages if args.page in p.stem]

    print("=" * 92)
    print("CONTROL CLASSIFICATION — what `controls` finds on real pages")
    print("=" * 92)
    header = f"{'page':52s} {'lines':>6s} {'inter':>6s} " + \
             " ".join(f"{r[:4]:>5s}" for r in ROLES) + f" {'other':>6s}"
    print(header)
    print("-" * 92)

    rows = []
    misses: list[str] = []
    for path in pages:
        try:
            roles, lines, interactive = controls_of(path)
        except Exception as exc:  # noqa: BLE001
            print(f"{path.stem[:52]:52s} {type(exc).__name__}: {exc}")
            continue
        counts = {r: len(roles[r]) for r in ROLES}
        print(f"{path.stem[:52]:52s} {lines:6d} {interactive:6d} " +
              " ".join(f"{counts[r]:5d}" for r in ROLES) +
              f" {len(roles['other']):6d}")
        rows.append({"page": path.stem, "lines": lines,
                     "interactive": interactive, **counts,
                     "other": len(roles["other"])})

        if args.show:
            for role in ROLES:
                for address, label, context in roles[role][:8]:
                    print(f"      {role:10s} {(context or label or '')[:40]:40s} "
                          f"{address.xpath[-42:]}")

        want = EXPECTED.get(path.stem)
        if want is None:
            continue
        for role, needles in want.items():
            # Match on the *context* — the visible text — because the label
            # of a link is its href, and a needle found there would mean the
            # audit was reading the URL rather than what a user reads.
            labels = " ".join((context or label or "").lower()
                              for _a, label, context in roles[role])
            if not needles:
                # An empty list asserts the bucket is empty. Without this the
                # audit could only reward finding things, and a classifier
                # that labelled everything would score perfectly.
                if roles[role]:
                    misses.append(
                        f"{path.stem}: {role} should be empty, has "
                        f"{len(roles[role])} "
                        f"(e.g. {(roles[role][0][2] or roles[role][0][1])[:40]!r})")
                continue
            for needle in needles:
                if needle.lower() not in labels:
                    misses.append(f"{path.stem}: {role} missing {needle!r}")

    print("-" * 92)
    checked = sum(1 for p in pages if p.stem in EXPECTED)
    print(f"pages {len(rows)}   with a known control {checked}   "
          f"misses {len(misses)}")
    for miss in misses:
        print(f"  MISS  {miss}")

    if rows:
        total_inter = sum(r["interactive"] for r in rows)
        total_named = sum(sum(r[x] for x in ROLES) for r in rows)
        share = 100.0 * total_named / total_inter if total_inter else 0.0
        print(f"\n{total_named:,} of {total_inter:,} interactive lines "
              f"({share:.1f}%) were given a role; the rest are 'other'.")

    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(
            {"rows": rows, "misses": misses}, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")

    return 1 if misses else 0


if __name__ == "__main__":
    raise SystemExit(main())
