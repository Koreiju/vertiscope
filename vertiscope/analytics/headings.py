"""G-86: a heading heads what follows it; the 256 cut is lenient (< 1.5x).

Counted over the frozen corpus, rendered fresh by the code under test:
chunks that are a heading ALONE (every line a markdown heading -- nothing it
heads), and chunks whose model-facing cost passes the lenient bound (1.5x the
window) although they hold more than one line (a single indivisible line may,
by S-11). Two planted arms: `before` -- `PLANT_HEADING_APART_FROM_RECORD`
`PLANT_NO_RECUT` and `PLANT_LONE_HEADING_FLUSH`, the renderer as it was (43 heading-alone, 33 over);
`strict` -- `LENIENCY = 1.0` with `PLANT_TRAILING_HEADINGS`, headings merged
like any piece.

    python -m vertiscope.analytics.headings [--pages N]
"""

from __future__ import annotations

import argparse
import json
import pathlib

from vertiscope import tokens

REPO = pathlib.Path(__file__).resolve().parents[2]
CORPUS = REPO / "tests" / "corpus"
OUT = REPO / "build_analytics" / "headings.json"


def _pages(limit):
    manifest = json.loads((CORPUS / "manifest.json").read_text())
    pages = [p for p in manifest["pages"] if p.get("ok") and (CORPUS / ("%s.html" % p["slug"])).exists()]
    return pages[:limit] if limit else pages


def run(limit=0):
    from vertiscope import markdown
    from vertiscope.markdown import DEFAULT_CONTEXT_WINDOW, _HEADING_FORM, render_trie
    from vertiscope.pipeline import run_pipeline
    from vertiscope.trie import AddressTrie

    W = DEFAULT_CONTEXT_WINDOW
    ARMS = {"clean": {}, "before": {"PLANT_HEADING_APART_FROM_RECORD": True, "PLANT_NO_RECUT": True,
                       "PLANT_LONE_HEADING_FLUSH": True},
            "strict": {"LENIENCY": 1.0, "PLANT_TRAILING_HEADINGS": True,
                       "PLANT_HEADING_APART_FROM_RECORD": True, "PLANT_NO_RECUT": True,
                       "PLANT_LONE_HEADING_FLUSH": True}}
    tally = {arm: {"chunks": 0, "heading_alone": 0, "over_lenient_multiline": 0, "max_cost": 0}
             for arm in ARMS}
    for p in _pages(limit):
        html = (CORPUS / ("%s.html" % p["slug"])).read_text(encoding="utf-8", errors="replace")
        try:
            result = run_pipeline(html, p["url"], render=False)
        except Exception:
            continue
        trie = AddressTrie.from_tagged(result.tagged, p["url"])
        for arm, plants in ARMS.items():
            was = {k: getattr(markdown, k) for k in plants}
            for k, v in plants.items():
                setattr(markdown, k, v)
            try:
                chunks = render_trie(trie, context_window=W)
            finally:
                for k, v in was.items():
                    setattr(markdown, k, v)
            t = tally[arm]
            for c in chunks:
                if not c.lines:
                    continue
                t["chunks"] += 1
                if all(_HEADING_FORM.match((ln.text or "").lstrip()) for ln in c.lines):
                    t["heading_alone"] += 1
                cost = tokens.budget(c.markdown)
                t["max_cost"] = max(t["max_cost"], cost)
                if len(c.lines) > 1 and cost > 1.5 * W:
                    t["over_lenient_multiline"] += 1
    for t in tally.values():
        t["heading_alone_pct"] = round(100 * t["heading_alone"] / max(1, t["chunks"]), 2)
    return {"window": W, **tally}


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--pages", type=int, default=0)
    got = run(ap.parse_args(argv).pages)
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(got, indent=1))
    print(json.dumps(got, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
