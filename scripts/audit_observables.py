#!/usr/bin/env python
"""What can an observer of this system actually distinguish?

MODEL §4.1 defines observational equivalence "relative to DOMAIN". But
`CONTENT_EXTRACTION_RULES.md` enumerates what the extractor can *detect in a
page* — it says nothing about what the system *exposes about an instance*.
Identity, position and multiplicity are instance-level facts, and whether they
are observable decides the identity design (COR-22.5.8).

That is not a matter of decree: an observation alphabet is a property of the
output surfaces, and it can be read off them. This enumerates every public
surface and reports which instance-level fields escape through each.

    python scripts/audit_observables.py
"""

from __future__ import annotations

import io
import json
import pathlib
import sys
import tempfile
from contextlib import redirect_stdout

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from vertiscope import cli  # noqa: E402
from vertiscope.config import load_config  # noqa: E402
from vertiscope.ingest import ingest  # noqa: E402
from vertiscope.pipeline import run_pipeline  # noqa: E402
from vertiscope.retrieve import Retriever  # noqa: E402
from vertiscope.store import Store  # noqa: E402

# Instance-level facts whose observability is in question.
FACTS = {
    "identity": "instance_id",
    "position": "absolute_xpath",
    "pattern": "pattern",
    "multiplicity": None,        # no field carries it
    "content": "rendered_text",
    "url": "url",
}

FIXTURE = ROOT / "tests" / "fixtures" / "catalog.html"
URL = "https://riverside.example/catalog"


def main() -> int:
    cfg = load_config(tempfile.mkdtemp(prefix="observe_"))
    with Store(cfg) as st:
        ingest(st, run_pipeline(FIXTURE.read_text(encoding="utf-8"), URL))
        hit = Retriever(st).search("echelle spectrograph", k=1)[0]
        an_id = hit.instance_id
        rec = st.get_instance(an_id)

    surfaces: dict[str, str] = {}

    # 1. library surface: what a Hit carries
    surfaces["Retriever.search -> Hit"] = " ".join(
        f"{k}={getattr(hit, k, None)!r}" for k in
        ("instance_id", "url", "pattern", "score", "text")
    )

    # 2. library surface: what a record carries
    surfaces["Store.get_instance -> InstanceRecord"] = " ".join(
        sorted(vars(rec).keys())
    )

    # 3-6. CLI surfaces, captured verbatim
    home = ["--home", str(cfg.home)]
    for name, argv in [
        ("cli: search", home + ["search", "echelle", "-k", "1"]),
        ("cli: search --json", home + ["search", "echelle", "-k", "1", "--json"]),
        ("cli: show", home + ["show", an_id]),
        ("cli: ls", home + ["ls"]),
        ("cli: info", home + ["info"]),
    ]:
        buf = io.StringIO()
        try:
            with redirect_stdout(buf):
                cli.main(argv)
        except SystemExit:
            pass
        surfaces[name] = buf.getvalue()

    print("=" * 74)
    print("OBSERVATION SURFACES — which instance-level facts escape?")
    print("=" * 74)
    print(f"{'surface':34s} " + " ".join(f"{f:9s}" for f in FACTS))
    print("-" * 74)

    exposure: dict[str, set[str]] = {f: set() for f in FACTS}
    for name, text in surfaces.items():
        marks = []
        for fact, field in FACTS.items():
            if field is None:
                present = False
            elif fact == "identity":
                present = an_id in text
            elif fact == "position":
                present = (rec.absolute_xpath in text) if rec else False
            elif fact == "pattern":
                present = rec.pattern in text and rec.absolute_xpath not in text
            elif fact == "content":
                present = (rec.rendered_text or "")[:20] in text
            else:
                present = rec.url in text
            if present:
                exposure[fact].add(name)
            marks.append("  yes    " if present else "   -     ")
        print(f"{name:34s} " + " ".join(marks))

    print("\n" + "=" * 74)
    print("VERDICT")
    print("=" * 74)
    for fact in FACTS:
        where = sorted(exposure[fact])
        verdict = "OBSERVABLE" if where else "not observable"
        print(f"  {fact:14s} {verdict:15s} {', '.join(where) if where else ''}")

    out = ROOT / "notes" / "observations" / "_observables.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(
        {f: sorted(v) for f, v in exposure.items()}, indent=2), encoding="utf-8")
    print(f"\nwrote {out.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
