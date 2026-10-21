"""R-K2a: lines with neither words nor a target, and what folding them costs.

The bar: "no dedups ... appropriately and most simply matched". A line that is
only a mark -- `![]`, `<#>`, `[ ]` -- says "a detector fired here" and nothing
else. Dropping such lines was built and REVERTED (PLUGIN_PRD R-K2a): their
addresses went to `absorbed`, which `covered` excludes, and 340 addresses that
still exist stopped being accounted for. The fold moves them into a worded
line of the same element as INLINE addresses, which `covered` counts.

Two arms on the same tries, rendered fresh from the frozen corpus by the code
under test: the renderer as it is, and `markdown.PLANT_KEEP_CONTENTLESS`. The
fold passes only if contentless lines fall AND, per page, every address the
planted arm covers is still covered -- the coverage arithmetic that ruled the
drop out.

    python -m vertiscope.analytics.contentless [--pages N]
"""

from __future__ import annotations

import argparse
import json
import pathlib
from typing import Dict

REPO = pathlib.Path(__file__).resolve().parents[2]
CORPUS = REPO / "tests" / "corpus"
OUT = REPO / "build_analytics" / "contentless.json"


def _pages(limit: int):
    manifest = json.loads((CORPUS / "manifest.json").read_text())
    pages = [p for p in manifest["pages"] if p.get("ok") and (CORPUS / ("%s.html" % p["slug"])).exists()]
    return pages[:limit] if limit else pages


def run(limit: int = 0) -> Dict[str, object]:
    from vertiscope import markdown
    from vertiscope.markdown import DEFAULT_CONTEXT_WINDOW, _is_contentless, render_trie
    from vertiscope.pipeline import run_pipeline
    from vertiscope.trie import AddressTrie

    tally = {arm: {"lines": 0, "contentless": 0, "covered": 0} for arm in ("clean", "planted")}
    lost_pages, lost_addresses = 0, 0
    for p in _pages(limit):
        html = (CORPUS / ("%s.html" % p["slug"])).read_text(encoding="utf-8", errors="replace")
        try:
            result = run_pipeline(html, p["url"], render=False)
        except Exception:
            continue
        trie = AddressTrie.from_tagged(result.tagged, p["url"])
        covered = {}
        for arm, plant in (("clean", False), ("planted", True)):
            was = markdown.PLANT_KEEP_CONTENTLESS
            markdown.PLANT_KEEP_CONTENTLESS = plant
            try:
                chunks = render_trie(trie, context_window=DEFAULT_CONTEXT_WINDOW)
            finally:
                markdown.PLANT_KEEP_CONTENTLESS = was
            t = tally[arm]
            cov = set()
            for c in chunks:
                for ln in c.lines:
                    t["lines"] += 1
                    t["contentless"] += _is_contentless(ln.text)
                cov.update(c.covered)
            t["covered"] += len(cov)
            covered[arm] = cov
        lost = covered["planted"] - covered["clean"]
        if lost:
            lost_pages += 1
            lost_addresses += len(lost)
    return {**tally, "lost_pages": lost_pages, "lost_addresses": lost_addresses}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=0, help="0: every frozen page")
    args = ap.parse_args(argv)
    got = run(args.pages)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(got, indent=1))
    print(json.dumps(got, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
