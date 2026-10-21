# OBSERVATION — auditing layout leaks mechanically, and what it found

**Date** 2026-08-10 · **Bears on** COR-10.9, PROP-10.10, COR-10.12, MODEL §4.1 ·
**Command** `python scripts/audit_layout_sensitivity.py --random 8`

## Method

The previous pass found a layout leak by guessing that ties were where to look.
This replaces the guess. Permuting the order in which instances are ingested
permutes row order, vocabulary column assignment and dictionary iteration order
at once — one knob perturbing the whole layout — and any output that differs is
reading layout rather than content. Wall-clock timestamps and the temporary home
path are scrubbed, being per-run rather than per-permutation.

## Result 1 — the generator shortcut is invalid, measured

43 instances, 12 surfaces, 42 adjacent transpositions plus random permutations.

```
search telescope --json      caught by: random#0, random#2
search per night --json      caught by: random#0, random#2
search spectrograph --json   caught by: random#2
```

**All 42 adjacent transpositions passed. Only random permutations found it.**
Adjacent transpositions generate the symmetric group, so it is tempting to test
only those and conclude invariance — PROP-10.10 shows why that fails: the
generator argument needs invariance at *every* state, and testing from one
baseline establishes it at one. A generator-only audit would have reported
invariance that does not hold.

## Result 2 — a float leak, distinct from the ordering leak

With identifier order identical, the *scores* differed:

```
0.25546887516975403   vs   0.25546884536743164
```

Row order determines summation order in the sparse matvec; float addition is not
associative (PROP-10.11); so the low bits of every score depend on layout, and
`--json` exposed them at full precision. The text output was unaffected because
it already rounds to four places — the leak was in the more "faithful" surface.

Fixed by rounding JSON scores to six places (COR-10.13), which exceeds the
observed spread (~3e-8) and is below any meaningful difference, so the output
factors through the layout quotient (PROP-10.8).

## Result 3 — two confounds that were not leaks

`ls` and `info` differed under **every** permutation, which is too uniform to be
layout: `ls` prints wall-clock times and `info` prints a temporary path and a
byte size. Scrubbed. Worth recording because a probe that reports 100% of
surfaces as leaking is reporting its own defect.

## Status after the fix

Two subsequent full runs: **no surface differed under any permutation.**

One caveat, recorded rather than smoothed over: an intermediate run reported a
single surviving difference on `search spectrograph --json` under one
permutation, and it did not reproduce — a direct replay of the same seed and
permutation produced byte-identical output, and two further full audits were
clean. Unexplained, and non-reproducible nondeterminism is more concerning than
the reproducible kind, not less. Not closed.

## Caveats

- One page, 43 instances. Layout leaks may be sparser or denser elsewhere.
- Absence under 50 permutations of one baseline is evidence, not proof
  (PROP-10.10).
- The audit covers CLI surfaces. Library returns (`Hit`, `InstanceRecord`) expose
  raw floats and are not covered; whether they count as system outputs is the
  same question DOMAIN §9.8.1 leaves open for `Store.get_instance`.
