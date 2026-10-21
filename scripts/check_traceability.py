#!/usr/bin/env python
"""Check the artifact edges defined in docs/PROCESS.md.

Fatal (exit 1) — a structural break:
  * a citation that resolves to no result       (broken link)
  * duplicate result identifiers                (ambiguous citation)
  * a proposal with no state header, or an unknown state

Reported (exit 0) — information, not error:
  * claims with no citing test    -> unverified
  * tests citing no claim         -> unjustified

The asymmetry is deliberate (PROCESS §7): a broken link is wrong, an absent
link is a fact worth knowing. Making absence fatal produces ceremonial
citations, which is worse than none.

    python scripts/check_traceability.py
    python scripts/check_traceability.py --verbose
"""

from __future__ import annotations

import argparse
import pathlib
import re
import sys
from collections import defaultdict

ROOT = pathlib.Path(__file__).resolve().parent.parent
THEORY = ROOT / "docs" / "THEORY.md"
METHOD = ROOT / "docs" / "METHOD.md"
PROPOSALS = ROOT / "notes" / "proposals"
TESTS = ROOT / "tests"

KIND_ABBREV = {
    "Definition": "DEF", "Proposition": "PROP", "Theorem": "THM",
    "Corollary": "COR", "Remark": "REM", "Lemma": "LEM",
}

# **Proposition 12.5 (name).**  /  **Theorem 17.3 (Kraft) (standard).**
RESULT_RE = re.compile(
    r"^\*\*(Definition|Proposition|Theorem|Corollary|Remark|Lemma)\s+"
    r"(\d+\.\d+(?:\.\d+)?)",
    re.MULTILINE,
)
# DEF-10.1 / PROP-12.5 / METHOD-A.14 / METHOD-B.2 / METHOD-C.7 / DOMAIN-§4.4
CITE_RE = re.compile(
    r"\b(DEF|PROP|THM|COR|REM|LEM)-(\d+\.\d+(?:\.\d+)?)\b"
    r"|\bMETHOD-([ABCD]\.\d+)\b"
    r"|\bDOMAIN-§?([\d.]+)\b"
)
STATE_RE = re.compile(r"^>?\s*\**\s*(?:STATE|Status)\s*:\s*\**\s*(\w+)", re.I | re.M)
VALID_STATES = {"DRAFT", "GROUNDED", "ACCEPTED", "REALISED", "REALIZED",
                "RETIRED", "HELD"}


def theory_claims() -> tuple[dict[str, str], list[str]]:
    """Identifier -> heading line; plus duplicates."""
    if not THEORY.exists():
        return {}, []
    text = THEORY.read_text(encoding="utf-8")
    claims: dict[str, str] = {}
    dupes: list[str] = []
    for match in RESULT_RE.finditer(text):
        kind, number = match.group(1), match.group(2)
        ident = f"{KIND_ABBREV[kind]}-{number}"
        line = text[match.start():text.find("\n", match.start())].strip()
        if ident in claims:
            dupes.append(ident)
        claims[ident] = line
    return claims, dupes


def method_ids() -> set[str]:
    if not METHOD.exists():
        return set()
    text = METHOD.read_text(encoding="utf-8")
    ids = set(re.findall(r"^##\s+([AB]\.\d+)", text, re.M))
    ids |= set(re.findall(r"^\*\*(C\.\d+)", text, re.M))
    ids |= set(re.findall(r"^\*\*(P\.\d+)", text, re.M))
    return ids


def citations_in(path: pathlib.Path) -> set[str]:
    found: set[str] = set()
    for m in CITE_RE.finditer(path.read_text(encoding="utf-8", errors="replace")):
        kind, num, meth, dom = m.groups()
        if kind:
            found.add(f"{kind}-{num}")
        elif meth:
            found.add(f"METHOD-{meth}")
        elif dom:
            found.add(f"DOMAIN-{dom}")
    return found


def main() -> int:
    ap = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--verbose", action="store_true",
                    help="list every unverified claim, not just the count")
    args = ap.parse_args()

    claims, dupes = theory_claims()
    methods = method_ids()
    fatal: list[str] = []

    print(f"THEORY results : {len(claims)}")
    print(f"METHOD ids     : {len(methods)}")

    if dupes:
        fatal.append(f"duplicate result identifiers: {sorted(set(dupes))}")

    # --- citations across proposals and tests -------------------------------
    citing: dict[str, set[str]] = defaultdict(set)   # ident -> citing files
    test_files = sorted(TESTS.glob("test_*.py")) if TESTS.exists() else []
    prop_files = sorted(PROPOSALS.rglob("*.md")) if PROPOSALS.exists() else []

    for path in test_files + prop_files:
        for ident in citations_in(path):
            citing[ident].add(path.name)

    known = set(claims) | {f"METHOD-{m}" for m in methods}
    broken = {
        ident: sorted(files) for ident, files in citing.items()
        if not ident.startswith("DOMAIN-") and ident not in known
    }
    if broken:
        for ident, files in sorted(broken.items()):
            fatal.append(f"citation resolves to nothing: {ident} (in {', '.join(files)})")

    # --- proposal states ----------------------------------------------------
    print(f"\nproposals      : {len(prop_files)}")
    for path in prop_files:
        text = path.read_text(encoding="utf-8", errors="replace")
        m = STATE_RE.search(text)
        state = (m.group(1).upper() if m else None)
        cites = {c for c in citations_in(path) if c in claims}
        if state is None:
            fatal.append(f"proposal has no state header: {path.name}")
            state_str = "MISSING"
        elif state not in VALID_STATES:
            fatal.append(f"proposal has unknown state {state!r}: {path.name}")
            state_str = state
        else:
            state_str = state
        print(f"  {state_str:10s} {path.name}   (cites {len(cites)} claim(s))")

    # --- coverage (reported, never fatal) -----------------------------------
    test_cites = {
        ident for path in test_files for ident in citations_in(path)
    }
    verified = {c for c in claims if c in citing and
                any(f.startswith("test_") for f in citing[c])}
    unverified = sorted(set(claims) - verified)
    uncited_tests = [p.name for p in test_files if not citations_in(p)]

    print(f"\nclaims cited by a test : {len(verified)} / {len(claims)}")
    print(f"claims unverified      : {len(unverified)}")
    if args.verbose:
        for ident in unverified:
            print(f"    {ident}  {claims[ident][:78]}")
    print(f"tests citing no claim  : {len(uncited_tests)} / {len(test_files)}")
    if args.verbose and uncited_tests:
        for name in uncited_tests:
            print(f"    {name}")

    if fatal:
        print("\nFATAL:")
        for line in fatal:
            print(f"  - {line}")
        return 1

    print("\nno structural breaks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
