# Process

*How theory, application, findings and critique interface, and what makes the
loop closed rather than merely circular.*

`METHOD.md` standardizes how to *reason*. This document standardizes how the
*artifacts* relate: what each one is allowed to claim, which one wins when two
disagree, and what mechanically detects a break. It is deliberately small — the
only ceremony it adds is a citation, and the only enforcement is a script.

---

## 1. What goes wrong without this

Three failures, all observed in this workspace already:

1. **Theory drifts from code silently.** A proposition can be violated by an
   implementation with nothing failing, because no artifact links the two.
2. **Findings have nowhere to go.** A measurement that contradicts a belief gets
   mentioned in prose and then lost, because there is no artifact whose job is to
   hold it.
3. **Proposals neither graduate nor die.** `OUTPUT_STRUCTURE.md` sat as a
   "proposal" with no defined path to acceptance or rejection, so its status was
   a matter of memory.

Each is a *missing edge*, not a missing document. The fix is to name the
artifact kinds, fix the direction of authority between them, and make the edges
checkable.

---

## 2. Seven artifact kinds

Each answers exactly one question. An artifact that answers two should be split;
that is the single most useful rule here.

| kind | answers | authority derives from | lives in |
|---|---|---|---|
| **DOMAIN** | what can be observed at all | regeneration from the implementation | `docs/CONTENT_EXTRACTION_RULES.md` + `scripts/dump_extraction_rules.py` |
| **THEORY** | what is necessarily true of those observations | proof | `docs/THEORY.md` |
| **METHOD** | how to reason about them | convention | `docs/METHOD.md` |
| **MODEL** | how THEORY's symbols are realised by the implementation | an abstraction map and its discharged obligations | `notes/proposals/MODEL.md` |
| **PROPOSAL** | what to build, and on which results it rests | derivation from THEORY | `notes/proposals/` |
| **IMPLEMENTATION** | what exists | it runs | `vertiscope/`, `tests/`, `scripts/` |
| **OBSERVATION** | what happens when it runs | measurement | `notes/observations/` |
| **ERRATUM** | a diagnosed discrepancy between two of the above | — | `notes/ERRATA.md` |

### 2.0 Why MODEL is a kind and not a proposal

MODEL was added after the other seven, because its absence was the reason the
loop was open rather than closed. Without it, a citation of a THEORY result from
a test is an **analogy**: nothing establishes that the code's quotient is the
quotient the proposition speaks of. MODEL is what converts a citation into a
proof obligation, and it is the only artifact whose failure modes are *both*
directions at once — a mismatch it reports may be a defect in the code or a gap
in the theory, and PROCESS §4.1 is what decides.

It is also the only kind that has so far *produced* theory: PROP-13.3,
PROP-14.6 and PROP-14.7 exist because an interpretation was attempted. An
artifact that only consumed theory would not need to be a kind of its own.

### 2.1 The grounding rule

**No artifact may use a term that does not reduce to DOMAIN.** THEORY §0 already
states this ("meaning is bounded by detectability"); this section makes it a
process obligation rather than a stylistic preference. A proposal appealing to
"the article's main content" is ungrounded unless "main content" is definable
from the eighteen subcategories; if it is not, the correct move is to extend
DOMAIN first — which requires changing the implementation, since DOMAIN is
regenerated from it.

This is what "situated by first principles" means operationally: the ground is
not a philosophical commitment, it is a file with a generator.

### 2.2 What each kind may not do

- DOMAIN may not argue. It enumerates.
- THEORY may not recommend. It states what holds.
- PROPOSAL may not assert new mathematics. It cites THEORY results by identifier
  and derives.
- OBSERVATION may not explain. It records the measurement and the method.
- ERRATUM may not live inside a technical document. It names the target and the
  diagnosis.

---

## 3. The loop

```
                     ┌──────────────────────────────────────────┐
                     │                                          │
   DOMAIN ─────▶ THEORY ─────▶ PROPOSAL ─────▶ IMPLEMENTATION   │
      ▲            ▲   ▲          ▲                  │          │
      │            │   │          │                  ▼          │
      │            │   └── METHOD │             OBSERVATION     │
      │            │              │                  │          │
      │            └──────────────┴──────────────────┘          │
      │                        ERRATUM                          │
      └─────────────────────────────────────────────────────────┘
```

Read the edges as obligations, not suggestions:

| edge | obligation |
|---|---|
| DOMAIN → THEORY | every term in THEORY reduces to DOMAIN (§2.1) |
| THEORY → PROPOSAL | every proposal claim cites the results it rests on |
| PROPOSAL → IMPLEMENTATION | every accepted proposal names the code that realises it |
| IMPLEMENTATION → OBSERVATION | every claim about behaviour is measured, not argued |
| OBSERVATION → ERRATUM | every measurement contradicting an artifact raises one |
| ERRATUM → {DOMAIN, THEORY, PROPOSAL, IMPLEMENTATION} | every erratum is **routed to exactly one target** |
| IMPLEMENTATION → DOMAIN | changing what is detectable regenerates DOMAIN |

**The loop is closed iff every erratum has a routed target and a resolution.**
Circularity without routing is what produces the endless-revision failure; the
routing requirement is the difference.

---

## 4. Precedence: who wins

A disagreement is not automatically anyone's fault. Precedence says who is
*presumed* right, so the burden of proof is assigned rather than argued.

1. **DOMAIN over everything, about detectability.** It is regenerated from the
   implementation, so it cannot be wrong about what the code can observe. If it
   looks wrong, the implementation changed and the doc was not regenerated —
   which the generator detects.
2. **OBSERVATION over THEORY and PROPOSAL, about behaviour.** What the system
   did is not subject to argument.
3. **THEORY over PROPOSAL, about possibility.** A proposal contradicting a proved
   result is rejected without further discussion.
4. **PROPOSAL over IMPLEMENTATION, about intent.** Code that diverges from an
   accepted proposal is a defect in the code — *unless* an OBSERVATION shows the
   proposal is unrealisable, which routes the erratum upward instead.
5. **IMPLEMENTATION over nothing.** It is always the correctable party, never the
   authority — except through DOMAIN, where it is the sole authority.

### 4.1 The diagnosis obligation

When OBSERVATION contradicts THEORY, **at least one of three things is true**,
and the erratum must say which:

- the theorem's hypotheses do not hold in this system (most common);
- the implementation does not do what the theorem assumes;
- the theorem is wrong.

Recording only "theory disagreed with reality" is not a diagnosis and does not
close the loop. The three cases have different targets: hypothesis failure routes
to PROPOSAL or THEORY's statement of scope, implementation divergence routes to
code, and a false theorem routes to THEORY.

---

## 5. Citation discipline

The mechanism that makes the edges checkable rather than aspirational.

### 5.1 Claim identifiers

THEORY's numbered results are the identifiers; they already exist and are stable.
The canonical citation form is the kind abbreviation and the number:

```
DEF-10.1   PROP-12.5   THM-17.3   COR-21.7   REM-14.5
```

METHOD's stances and schemas are cited as `METHOD-A.14`, `METHOD-B.2`; its
failure modes as `METHOD-C.7`. DOMAIN sections as `DOMAIN-§4.4`.

### 5.2 Where citations are required

| artifact | requirement |
|---|---|
| PROPOSAL | every substantive claim carries the identifiers it rests on |
| test | a test asserting a theoretical property names it: `# claim: PROP-12.5` |
| ERRATUM | names the target identifier and the diagnosis (§4.1) |
| OBSERVATION | names what it measures and, if it bears on a claim, the identifier |

### 5.3 What the citations buy

Two orphan classes, both detectable, both meaningful:

- **A claim with no test is unverified.** It may be true and unimplemented, which
  is fine and should be visible; or it may be silently violated.
- **A test citing no claim is unjustified** in the narrow sense that it encodes a
  belief with no stated basis. This is acceptable for pure regression tests and
  should be explicit rather than accidental.

The point is not to drive either count to zero. It is that both counts are known.

---

## 6. State transitions for a proposal

The lifecycle that was missing.

```
DRAFT ──▶ GROUNDED ──▶ ACCEPTED ──▶ REALISED ──▶ RETIRED
   │           │            │
   └── every state may fall back to DRAFT on an erratum
```

| state | gate to enter |
|---|---|
| **DRAFT** | exists |
| **GROUNDED** | every term reduces to DOMAIN (§2.1); every claim cites THEORY identifiers; no claim contradicts a proved result |
| **ACCEPTED** | a decision is recorded, with the alternatives considered and the reason |
| **REALISED** | named code exists, and tests cite the claims the proposal rested on |
| **RETIRED** | superseded or rejected, with the erratum that killed it |

A proposal's state is written in its own header. `OUTPUT_STRUCTURE.md` is
currently **DRAFT** — it predates the theory it would need to cite.

---

## 7. What is mechanized

`scripts/check_traceability.py` reports, and fails on structural breaks:

- claim identifiers that do not resolve to a result in THEORY (broken citation);
- duplicate identifiers (ambiguous citation);
- claims with no citing test (**unverified** — reported, not fatal);
- tests citing no claim (**unjustified** — reported, not fatal);
- proposals whose state header is missing or whose gate is unmet;
- DOMAIN drift, by deferring to `dump_extraction_rules.py`.

Fatal versus reported is the whole design: a *broken* link is an error, an
*absent* link is information. Making absence fatal produces ceremonial citations,
which is worse than none.

---

## 8. Failure modes of this process

Stated so they can be recognised, in the style of `METHOD` Part C.

**P.1 Ceremonial citation.** Identifiers attached to claims they do not actually
support, to satisfy the checker. *Detection:* read the cited result and ask
whether the claim follows. No script catches this.

**P.2 Erratum as wastebasket.** Discrepancies recorded without routing, so
ERRATA grows and nothing closes. *Detection:* count errata with no target.

**P.3 Domain creep by prose.** A term entering THEORY or a proposal that is not
in DOMAIN, introduced gradually by natural language. *Detection:* §2.1 challenge
on any noun that sounds like it means something to a human reader.

**P.4 Proposal immortality.** A DRAFT that is neither advanced nor retired,
consulted informally and treated as if accepted. *Detection:* state headers with
old dates.

**P.5 Observation without method.** A number recorded without how it was
obtained, therefore unreproducible and unfalsifiable. *Detection:* every
observation must name the command that produced it.

**P.6 Precedence litigation.** Re-arguing §4 case by case instead of applying it.
The order exists to end the argument, not to start one.

---

## 9. The minimum viable instance

If this were reduced to what actually must happen, it is four sentences:

1. Every term traces to something the code can detect, and that list regenerates.
2. Every design claim cites a proved result by identifier.
3. Every behavioural claim cites a measurement, with its command.
4. Every discrepancy names one target and one diagnosis.

Everything above is scaffolding for those four.
