"""Which addresses does the metric actually disagree about?

Every capture class resolved today was found by diffing one page's trie
against its ground truth and reading the values: a select's options, hidden
inputs, `<link>` metadata, an empty placeholder. The diff was written ad hoc
each time, as a raw set difference, and that is where it went wrong.

`score_arrow` does not compare sets. It allows a match when `_owner(path)` is
in `page_owners` or in `page_ancestors` -- deliberately, because a render
addressing content one level up is standing for content the page really has,
and counting that as a phantom once charged 19 inventions for 19 logos
correctly drawn.

A raw diff has none of that tolerance, so it reports differences the metric
has already forgiven. Used to diagnose, it produced a confident account of 115
invented and 115 lost on one page and roughly 230 of the corpus's errors, for
a change that moved the corpus totals by nothing at all: 727 and 563 before
and after.

So this exists to stop the next diagnosis being written from scratch with the
tolerance left out. It reports two sets, and the difference between them is
the point:

  `charged`   what the metric counts -- the same test `score_arrow` applies.
              These are the numbers in the tables.
  `forgiven`  addresses the two sides genuinely disagree about, which the
              metric matched anyway through an owner or an ancestor. Worth
              reading, never worth quoting as a defect.

A defect hunt reads `charged`. A question about addressing conventions reads
`forgiven`. Confusing the two is what this module is for.
"""

from __future__ import annotations

from typing import Dict, List, Sequence, Set, Tuple

from .affine import _owner


def _ancestor_set(paths) -> Set[str]:
    """Every ancestor of every path, the way `score_arrow` builds them."""
    out: Set[str] = set()
    for path in paths:
        at = _owner(path)
        while "/" in at:
            at = at.rsplit("/", 1)[0]
            if not at:
                break
            out.add(at)
    return out


def diff_addresses(trie: Dict[str, str],
                   truth_units: Sequence) -> dict:
    """Split trie-vs-truth disagreement into what the metric charges and what
    it forgives.

    `trie` maps xpath to value. `truth_units` is `PageTruth.units`.
    """
    page_paths = {u.xpath for u in truth_units}
    page_owners = {_owner(u.xpath) for u in truth_units}
    page_ancestors = _ancestor_set(page_paths)

    charged: List[Tuple[str, str]] = []
    forgiven: List[Tuple[str, str]] = []
    for path, value in sorted(trie.items()):
        if path in page_paths:
            continue
        # The exact test `score_arrow` applies before calling something
        # invented. Anything it accepts is a difference in where the content
        # was addressed, not a claim that the page lacks it.
        if (_owner(path) in page_owners or _owner(path) in page_ancestors):
            forgiven.append((path, value))
        else:
            charged.append((path, value))

    # The other direction has no such tolerance in `score_arrow`: a truth unit
    # the trie does not hold is a miss, full stop. Kept separate anyway so a
    # caller cannot accidentally sum the two into one "error" figure, which is
    # how the same units came to be counted on both sides at once.
    missing = [(u.xpath, u.value) for u in truth_units
               if u.xpath not in trie]

    return {
        "charged": charged,
        "forgiven": forgiven,
        "missing": missing,
        "counts": {"charged": len(charged),
                   "forgiven": len(forgiven),
                   "missing": len(missing)},
    }


def render_diff(report: dict, limit: int = 6) -> str:
    counts = report["counts"]
    out = ["",
           "  charged  {:>6}   what the metric counts as invented".format(
               counts["charged"]),
           "  forgiven {:>6}   addressed elsewhere; matched by owner or "
           "ancestor".format(counts["forgiven"]),
           "  missing  {:>6}   in truth, not in the trie".format(
               counts["missing"]),
           ""]
    for name in ("charged", "forgiven", "missing"):
        rows = report[name][:limit]
        if not rows:
            continue
        out.append("  {}:".format(name))
        for path, value in rows:
            out.append("    {:<52} {}".format(
                path[-50:], repr(value)[:34]))
        out.append("")
    out.append("  Read `charged` when hunting a defect. `forgiven` is a")
    out.append("  question about addressing conventions, and quoting it as a")
    out.append("  defect count is how one change with no measurable effect")
    out.append("  came to be reported as fixing 230 corpus errors.")
    return chr(10).join(out)
