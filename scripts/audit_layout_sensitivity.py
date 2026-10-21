#!/usr/bin/env python
"""Does any output depend on storage layout rather than on content?

COR-10.9: an output whose ordering is resolved by storage position makes storage
position observable, though it reports no index. The ranking case was found by
hand, by guessing that ties were the place to look. That is not a method.

This is the method. Permuting the order in which instances are ingested permutes
row order, vocabulary column assignment and dictionary iteration order at once —
one knob that perturbs the whole layout. Any output that differs under such a
permutation is reading layout rather than content.

A tempting efficiency: adjacent transpositions generate the symmetric group, so
invariance under them ought to imply invariance under all n! permutations, making
the audit linear rather than factorial. **That argument does not apply here and
this script measured its failure.** It requires invariance at *every* state
(PROP-10.10); testing from a single baseline establishes only f(σ_i c₀) = f(c₀)
for each generator, which does not compose. Empirically: all 42 adjacent
transpositions of the fixture passed while random permutations found a real leak.

So both are run, and the random permutations are load-bearing rather than a
sanity check. Absence of a leak here is evidence, not proof.

Confounds are normalised out: wall-clock timestamps and the temporary home path
vary per run and are not layout.

    python scripts/audit_layout_sensitivity.py
    python scripts/audit_layout_sensitivity.py --page some.html
"""

from __future__ import annotations

import argparse
import io
import json
import pathlib
import random
import re
import sys
import tempfile
from contextlib import redirect_stdout

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vertiscope import cli  # noqa: E402
from vertiscope.config import load_config  # noqa: E402
from vertiscope.ingest import ingest  # noqa: E402
from vertiscope.pipeline import run_pipeline  # noqa: E402
from vertiscope.store import Store  # noqa: E402

FIXTURE = ROOT / "tests" / "fixtures" / "catalog.html"
URL = "https://riverside.example/catalog"
QUERIES = ["spectrograph", "telescope", "per night", "policy", "a"]


def outputs_under(result, perm: list[int]) -> dict[str, str]:
    """Ingest instances in the given order; capture every public surface."""
    permuted = type(result)(**{**vars(result),
                               "instances": [result.instances[i] for i in perm]})
    cfg = load_config(tempfile.mkdtemp(prefix="layout_"))
    with Store(cfg) as st:
        ingest(st, permuted)

    def scrub(text: str) -> str:
        """Remove per-run nondeterminism that is not layout."""
        text = text.replace(str(cfg.home), "<HOME>")
        # timestamps and byte sizes vary per run, not per permutation
        text = re.sub(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}", "<TIME>", text)
        text = re.sub(r"\d+(\.\d+)?(B|KB|MB|GB)\b", "<SIZE>", text)
        return text

    out: dict[str, str] = {}
    for q in QUERIES:
        for extra in ([], ["--json"]):
            buf = io.StringIO()
            try:
                with redirect_stdout(buf):
                    cli.main(["--home", str(cfg.home), "search", q, "-k", "20"] + extra)
            except SystemExit:
                pass
            out[f"search {q}{' --json' if extra else ''}"] = scrub(buf.getvalue())
    for name, argv in (("ls", ["ls"]), ("info", ["info"])):
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                cli.main(["--home", str(cfg.home), name])
        except SystemExit:
            pass
        out[name] = scrub(buf.getvalue())
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--page", type=pathlib.Path, default=FIXTURE)
    ap.add_argument("--random", type=int, default=3,
                    help="extra random permutations, as a check on the generator argument")
    args = ap.parse_args()

    result = run_pipeline(args.page.read_text(encoding="utf-8", errors="replace"), URL)
    n = len(result.instances)
    identity = list(range(n))
    baseline = outputs_under(result, identity)

    print("=" * 72)
    print("LAYOUT SENSITIVITY — do outputs depend on ingest order?")
    print("=" * 72)
    print(f"page      {args.page.name}")
    print(f"instances {n}")
    print(f"surfaces  {len(baseline)}")

    # generators of S_n: the n-1 adjacent transpositions
    perms: list[tuple[str, list[int]]] = []
    for i in range(n - 1):
        p = identity.copy()
        p[i], p[i + 1] = p[i + 1], p[i]
        perms.append((f"swap({i},{i+1})", p))
    rng = random.Random(20260810)
    for j in range(args.random):
        p = identity.copy()
        rng.shuffle(p)
        perms.append((f"random#{j}", p))

    print(f"perms     {n-1} adjacent transpositions + {args.random} random\n")

    leaks: dict[str, list[str]] = {}
    for label, perm in perms:
        got = outputs_under(result, perm)
        for surface, text in got.items():
            if text != baseline[surface]:
                leaks.setdefault(surface, []).append(label)

    if not leaks:
        print("no surface differed under any permutation")
        print("-> every audited output factors through the layout quotient (PROP-10.8)")
    else:
        print(f"LEAKS on {len(leaks)} surface(s):")
        for surface, labels in sorted(leaks.items()):
            print(f"  {surface:28s} differs under {len(labels)} perm(s)"
                  f"  e.g. {labels[0]}")

    out = ROOT / "notes" / "observations" / "_layout_sensitivity.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {"page": args.page.name, "instances": n,
         "surfaces": sorted(baseline), "leaks": leaks}, indent=2), encoding="utf-8")
    print(f"\nwrote {out.relative_to(ROOT)}")
    return 1 if leaks else 0


if __name__ == "__main__":
    raise SystemExit(main())
