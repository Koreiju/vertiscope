"""G-86: a heading heads what follows it; the 256 cut is lenient (< 1.5x).

Counted over the frozen corpus, rendered fresh by the code under test:
chunks that are a heading ALONE (every line a markdown heading -- nothing it
heads), and chunks whose model-facing cost passes the lenient bound (1.5x the
window) although they hold more than one line (a single indivisible line may,
by S-11). Two planted arms: `before` -- `PLANT_HEADING_APART_FROM_RECORD`
`PLANT_NO_RECUT` and `PLANT_LONE_HEADING_FLUSH`, the renderer as it was (43 heading-alone, 33 over);
`strict` -- `LENIENCY = 1.0` with `PLANT_TRAILING_HEADINGS`, headings merged
like any piece.

    python -m domvec.analytics.headings [--pages N]
"""

from __future__ import annotations

import argparse
import json
import pathlib

from domvec import tokens

REPO = pathlib.Path(__file__).resolve().parents[2]
CORPUS = REPO / "tests" / "corpus"
OUT = REPO / "build_analytics" / "headings.json"


def _pages(limit):
    manifest = json.loads((CORPUS / "manifest.json").read_text())
    pages = [p for p in manifest["pages"] if p.get("ok") and (CORPUS / ("%s.html" % p["slug"])).exists()]
    return pages[:limit] if limit else pages


def _level(text: str) -> int:
    s = (text or "").lstrip()
    n = len(s) - len(s.lstrip("#"))
    return n if 1 <= n <= 6 and s[n:n + 1] == " " else 0


def _why_alone(chunk, nxt, window: int) -> str:
    """A heading-alone chunk is RIGHT when it heads nothing -- the page ends,
    or the next chunk opens a section at its level or above -- or when the
    user's rule keeps it apart: joined to what follows it would pass the
    lenient bound, nearer 512 than 256 ("keep the previous"). Otherwise it is
    a heading cut from what it heads."""
    if nxt is None:
        return "heads_nothing"
    mine = min((_level(ln.text) for ln in chunk.lines if _level(ln.text)), default=0)
    first = _level(nxt.lines[0].text) if nxt.lines else 0
    if first and mine and first <= mine:
        return "heads_nothing"
    if tokens.budget(chunk.markdown + "\n" + nxt.markdown) > 1.5 * window:
        return "kept_by_rule"
    return "unexplained"


def run(limit=0):
    from domvec import markdown
    from domvec.markdown import DEFAULT_CONTEXT_WINDOW, _HEADING_FORM, render_trie
    from domvec.pipeline import run_pipeline
    from domvec.trie import AddressTrie

    W = DEFAULT_CONTEXT_WINDOW
    ARMS = {"clean": {}, "before": {"PLANT_HEADING_APART_FROM_RECORD": True, "PLANT_NO_RECUT": True,
                       "PLANT_LONE_HEADING_FLUSH": True, "PLANT_LONE_HEADING_KEPT_APART": True},
            "kept_apart": {"PLANT_LONE_HEADING_KEPT_APART": True},
            "strict": {"LENIENCY": 1.0, "PLANT_TRAILING_HEADINGS": True,
                       "PLANT_HEADING_APART_FROM_RECORD": True, "PLANT_NO_RECUT": True,
                       "PLANT_LONE_HEADING_FLUSH": True, "PLANT_LONE_HEADING_KEPT_APART": True}}
    tally = {arm: {"chunks": 0, "heading_alone": 0, "over_lenient_multiline": 0, "max_cost": 0,
                   "heads_nothing": 0, "kept_by_rule": 0, "unexplained": 0, "unexplained_examples": []}
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
            live = [c for c in chunks if c.lines]
            for i, c in enumerate(live):
                t["chunks"] += 1
                if all(_HEADING_FORM.match((ln.text or "").lstrip()) for ln in c.lines):
                    t["heading_alone"] += 1
                    # WHY it stands alone (2026-10-30): the residue is a claim
                    # about the rule, so each one is classified, not argued.
                    why = _why_alone(c, live[i + 1] if i + 1 < len(live) else None, W)
                    t[why] += 1
                    if why == "unexplained" and len(t["unexplained_examples"]) < 5:
                        t["unexplained_examples"].append([p["slug"], c.markdown[:80]])
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
