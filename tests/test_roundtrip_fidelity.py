"""A widget repaints to the line it was built from.

Everything the markdown renderer adds, `Document.from_chunks` removes and
`Widget.render` puts back. That round trip is the only thing binding the
artifact to the program that reads it, and it broke twice in one day — once
on inputs (`[ ] Quick search` parsed to label `] Quick search`), once on
headings (`##### ( Products )` repainted as `( ##### ( Products ) )`).

Both times the markdown was correct, so `test_corpus_quality` — which
compares the output to the *page* — could not see either one. Both times the
cause was the same: a renderer changed and its parser did not.

The invariant is exact, which is what makes it useful as a tripwire:

    widget.render() == "  " * line.depth + line.text

`test_the_invariant_would_have_caught_the_bug_that_prompted_it` is the reason
to trust the rest. An invariant nobody has watched fail is a decoration.
"""

from __future__ import annotations

import json
import pathlib
import tempfile

import pytest

from vertiscope.bench import run_pages
from vertiscope.fidelity import measure_page

CORPUS = pathlib.Path(__file__).parent / "corpus"
MANIFEST = CORPUS / "manifest.json"


def _corpus_pages():
    if not MANIFEST.exists():
        return []
    pages = [p for p in json.loads(MANIFEST.read_text())["pages"] if p.get("ok")]
    return [p for p in pages if (CORPUS / f"{p['slug']}.html").exists()]


PAGES = _corpus_pages()

pytestmark_corpus = pytest.mark.skipif(
    not PAGES, reason="frozen corpus absent; run scripts/fetch_corpus.py"
)


@pytest.fixture(scope="module")
def round_tripped():
    """Every page, the whole way, in parallel.

    Serially this took 218s, which is a third of the suite's runtime for one
    file — and a test that slow gets skipped, then deleted, then the invariant
    is unwatched again. The same measurement the audit script uses, fanned out
    over the runner, is 27s.

    Workers return counts and sample lines rather than live objects: what
    crosses a process boundary has to be picklable, and what a failure needs
    is the two strings that disagree.
    """
    work = [{"page": p["slug"], "path": str(CORPUS / f"{p['slug']}.html"),
             "url": p["url"], "window": 1200, "keep": 6} for p in PAGES]
    return list(run_pages(work, measure_page))


@pytestmark_corpus
def test_every_line_repaints_to_itself(round_tripped):
    """The tripwire. A parser that stops matching its renderer fails here.

    Measured 2026-08-15: 235,559 lines over 136 pages, all of them. The first
    run of this check found 495 that did not, across 24 pages — handler
    elements rendered `[div[onclick]]` by a fourth markdown form no widget
    kind knew about, and repainted `( [div[onclick]] )`.
    """
    total = sum(r["lines"] for r in round_tripped if "error" not in r)
    bad = sum(r["bad"] for r in round_tripped if "error" not in r)
    samples = [f"{r['page']} [{s['kind']}] {s['want']!r} -> {s['got']!r}"
               for r in round_tripped if "error" not in r
               for s in r.get("samples", [])]

    assert total > 100_000, f"only {total:,} lines; corpus shrank?"
    assert not bad, (f"{bad} of {total:,} lines do not repaint to themselves:"
                     + "\n" + "\n".join(samples[:15]))


@pytestmark_corpus
def test_no_page_failed_to_measure(round_tripped):
    """The runner reports failures as rows, so they must be looked at.

    Without this, a page that crashed the parser would leave the four checks
    below quietly computing over the pages that happened to work.
    """
    failed = [(r["page"], r["error"]) for r in round_tripped if "error" in r]
    assert not failed, f"{len(failed)} pages failed to measure: {failed[:5]}"
    assert len(round_tripped) == len(PAGES)


@pytestmark_corpus
def test_the_checkpoint_is_byte_identical(round_tripped):
    """Reading and re-writing the JSONL changes nothing.

    Without this, a perfect repaint score could be produced by a checkpoint
    that quietly dropped whatever it could not represent.
    """
    lossy = [r["page"] for r in round_tripped
             if "error" not in r and not r["identical"]]
    assert not lossy, f"{len(lossy)} pages changed on re-write: {lossy[:10]}"


@pytestmark_corpus
def test_no_line_is_lost_between_the_file_and_the_screen(round_tripped):
    for r in round_tripped:
        if "error" in r:
            continue
        assert r["reloaded_lines"] == r["lines"], (
            f"{r['page']}: {r['lines']} lines written, "
            f"{r['reloaded_lines']} read back")
        assert r["widgets"] == r["reloaded_lines"], (
            f"{r['page']}: {r['reloaded_lines']} lines, {r['widgets']} widgets")


@pytestmark_corpus
def test_addresses_survive_the_checkpoint(round_tripped):
    """A repainted line with a lost address is a line you cannot act on."""
    lost = [(r["page"], r["addresses"]) for r in round_tripped
            if "error" not in r and r["addresses"] < 1.0]
    assert not lost, f"{len(lost)} pages lost addresses: {lost[:5]}"


# --- non-vacuity ------------------------------------------------------------


def _parser_before_the_heading_fix(lines):
    """`Document.from_chunks` as it stood on 2026-08-15 before the fix.

    Every strip tests a *leading* mark, so a heading marker in front of a
    control silently disabled all of them.
    """
    from vertiscope.repl.model import Widget, WidgetKind, kind_for

    widgets = []
    for line in lines:
        kind = kind_for(line.address)
        label = line.text
        if kind is WidgetKind.BUTTON and label.startswith("( "):
            label = label[2:-2] if label.endswith(" )") else label[2:]
        elif kind is WidgetKind.FORM and label.startswith("=== "):
            label = label[4:-4] if label.endswith(" ===") else label[4:]
        elif kind is WidgetKind.INPUT and label.startswith("[ ] "):
            label = label[4:].strip()
        elif kind is WidgetKind.INPUT and label.startswith("[ "):
            label = label[2:].strip("] ").strip()
        widgets.append(Widget(line=len(widgets), kind=kind, label=label,
                              address=line.address, depth=line.depth))
    return widgets


# Measured 2026-08-15: a control inside a heading is rare — five lines across
# the first forty corpus pages, on these two — which is exactly why it reached
# the REPL. Named rather than searched for, so the check stays seconds long.
_HEADING_CONTROL_PAGES = [
    "archive-org-details-princetonuniver01librgoog",
    "ec-europa-eu-eurostat-web-main-data-database",
]


@pytest.mark.parametrize("slug", _HEADING_CONTROL_PAGES)
def test_the_invariant_would_have_caught_the_bug_that_prompted_it(slug):
    """Put the old parser back: the repaint check must fail, and only there.

    An invariant nobody has watched fail is a decoration. This one fails on
    every heading-control and on nothing else, so it cannot be passing by
    accident on unrelated drift.
    """
    from vertiscope.markdown import render_trie
    from vertiscope.pipeline import run_pipeline
    from vertiscope.repl.model import Document, WidgetKind
    from vertiscope.trie import AddressTrie

    path = CORPUS / f"{slug}.html"
    if not path.exists():
        pytest.skip(f"{slug} absent from the frozen corpus")
    url = next((p["url"] for p in PAGES if p["slug"] == slug), f"https://{slug}/")

    trie = AddressTrie.from_tagged(
        run_pipeline(path.read_text(encoding="utf-8", errors="replace"),
                     url).tagged, url)
    chunks = render_trie(trie, context_window=1200)
    lines = [ln for c in chunks for ln in c.lines]

    def repaint_failures(widgets):
        return [ln.text for w, ln in zip(widgets, lines)
                if w.render() != "  " * ln.depth + ln.text]

    heading_controls = [
        ln.text for w, ln in zip(Document.from_chunks(chunks).lines, lines)
        if ln.text.startswith("#") and w.kind is not WidgetKind.TEXT]
    assert heading_controls, (
        f"{slug} no longer contains a control inside a heading — this test is "
        "vacuous and the invariant it vouches for is unwatched")

    assert repaint_failures(Document.from_chunks(chunks).lines) == []
    assert (repaint_failures(_parser_before_the_heading_fix(lines))
            == heading_controls)
