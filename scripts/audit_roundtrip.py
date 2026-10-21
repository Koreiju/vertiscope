"""Does the artifact survive the trip to the thing that reads it?

The quality audit compares the markdown to the page. It cannot see the class
of defect that cost the most time on 2026-08-15, because that defect leaves
the markdown *correct*:

    renderer:  `##### ( Products )`     — right
    JSONL:     `##### ( Products )`     — right, byte for byte
    widget:    label='##### ( Products )'
    repaint:   `( ##### ( Products ) )` — wrong

`Document.from_chunks` strips the control marks by testing what the line
*starts with*. Add a heading marker in front, and every strip silently stops
firing. The markdown is fine; the corruption exists only downstream, in the
REPL, after a parser and its renderer have drifted apart. That happened twice
in one day in the same function — once on inputs (`] Quick search`), once on
headings — and the second time I introduced it hours after fixing the first.

So this walks the whole chain the REPL actually takes,

    page -> chunks -> JSONL -> chunks' -> widgets -> render

and asserts the one invariant that binds the ends together:

    widget.render() == "  " * line.depth + line.text

A widget repaints to the line it was built from. Everything a renderer adds,
its parser removes, and puts back. If that holds for every line of every page,
a renderer cannot change without its parser noticing.

    identical   JSONL round-trips byte for byte
    widgets     one widget per line, no lines lost
    repaint     share of lines that repaint to themselves
    addresses   share of lines whose address survives the checkpoint

`repaint` is the one that matters. The others are there because a chain is
only as trustworthy as its weakest hop, and a checkpoint that quietly drops a
line would make a perfect repaint score meaningless.

What this cannot see: whether the line was worth rendering. A wrong line that
repaints faithfully passes here and is caught, if at all, by audit_quality.
The two audits are deliberately blind in opposite directions.

    python scripts/audit_roundtrip.py               # the whole corpus
    python scripts/audit_roundtrip.py --page apnews --show
"""

from __future__ import annotations

import argparse
import json
import pathlib
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _force_utf8_stdio() -> None:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass


_force_utf8_stdio()

from vertiscope.bench import default_jobs, run_pages  # noqa: E402
from vertiscope.fidelity import measure_page  # noqa: E402

CORPUS = ROOT / "tests" / "corpus"
MANIFEST = CORPUS / "manifest.json"


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--page", help="substring of a corpus page stem")
    ap.add_argument("--window", type=int, default=1200)
    ap.add_argument("--show", action="store_true",
                    help="print the lines that failed to repaint")
    ap.add_argument("--json", type=pathlib.Path)
    ap.add_argument("--jobs", type=int, default=default_jobs(),
                    help="worker processes (default: half the cores)")
    ap.add_argument("--resume", type=pathlib.Path,
                    help="append results here and skip pages already in it")
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

    print("=" * 92)
    print("ROUND TRIP — page -> chunks -> JSONL -> widgets -> repaint")
    print("=" * 92)
    print(f"{'page':42s} {'lines':>7s} {'ident':>6s} {'widgets':>8s} "
          f"{'repaint':>8s} {'addrs':>7s}")
    print("-" * 92)

    work = [{"page": p.stem, "path": str(p),
             "url": urls.get(p.stem) or f"https://{p.stem}/",
             "window": args.window} for p in pages]

    rows, failed = [], []
    for row in run_pages(work, measure_page, jobs=args.jobs,
                         results_path=args.resume, resume=bool(args.resume)):
        rows.append(row)
        if "error" in row:
            print(f"{row['page'][:42]:42s} {row['error']}")
            failed.append(row["page"])
            continue
        flag = "" if (row["identical"] and row["bad"] == 0
                      and row["widgets"] == row["reloaded_lines"]) else "  <-"
        print(f"{row['page'][:42]:42s} {row['lines']:7d} "
              f"{'yes' if row['identical'] else 'NO':>6s} "
              f"{row['widgets']:8d} {row['repaint']:8.4%} "
              f"{row['addresses']:7.1%}{flag}")
        if row["bad"]:
            failed.append(row["page"])
            if args.show:
                for s in row["samples"]:
                    print(f"      {s['kind']:9s} want {s['want']!r}")
                    print(f"      {'':9s}  got {s['got']!r}")

    good = [r for r in rows if "error" not in r]
    total = sum(r["lines"] for r in good)
    bad = sum(r["bad"] for r in good)
    print("-" * 92)
    print(f"{len(good)} pages, {total:,} lines")
    print(f"  identical checkpoints  {sum(1 for r in good if r['identical'])}/{len(good)}")
    print(f"  lines that repaint     {total - bad:,}/{total:,} "
          f"({(total - bad) / total:.4%})" if total else "  no lines")
    print(f"  addresses preserved    "
          f"{sum(1 for r in good if r['addresses'] == 1.0)}/{len(good)} pages intact")

    if args.json:
        args.json.write_text(json.dumps(rows, indent=2), encoding="utf-8")
        print(f"\nwrote {args.json}")

    if failed:
        print(f"\nFAILED on {len(failed)}: {', '.join(failed[:10])}")
        return 1
    print("\nEvery line repaints to itself.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
