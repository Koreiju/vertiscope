# Errata and revision history for `docs/THEORY.md`

Kept **outside** the paper deliberately. `docs/THEORY.md` is a technical
document; it states what is true, not what a previous draft got wrong.
Everything corrective lives here.

---

## Revision 1 → 2 (2026-08-09)

Revision 1 was written from first principles without reading the
`web_fiber_haptics` design corpus. Reading notes: `notes/reading/`.

### Substantive errors

**E1. Generalization was defined as plain index-stripping.**
Wrong. Stripping all indices makes the navigation list and the content list
congruent, so they share a pattern class. Observed live: navigation fragments
outranked prose in retrieval. Generalization must be *region-anchored* — the
nearest landmark ancestor's absolute path is retained verbatim and only the
remainder is stripped (`REAL_TIME_SCAN_UPDATE.md` §7.8). In revision 2 this is
Definition 3.2, and its transducer characterisation (Prop. 3.4) is new.

**E2. The incremental unit was given as the dirty node.**
The corpus fixes it at the dirty *pattern*: on any change, re-run the chunker
over the whole pattern's leaf set rather than patching member lists, because new
members can change which ancestor wins the budget test (§7.7). Revision 2 states
this as Theorem 7.6 with the failure of the finer granularity as its motivation.

**E3. The containment filter was presented as needing a new data structure.**
It does not; the corpus already specifies one (`_claimed` reverse index plus a
sorted xpath list with `bisect` prefix ranges, §6.1). Revision 2 treats the
whole thing more generally as antichain maintenance (§4), of which both the
sorted-list and the trie are implementations.

**E4. The cost model omitted its dominant term.**
Revision 1 counted fold operations. The measured bottleneck is the browser-to-
host payload: roughly 10 MB falling to a few KB when a hash-diff is applied
(§9.1). Revision 2 makes transport a first-class term in the cost model (§9) and
records that this optimisation is specified but unimplemented.

**E5. The dedup relation was inverted.**
Revision 1 made exact hashing authoritative and treated near-duplication as a
tolerance relation. The binding specification makes a *subsumption preorder* on
token multisets authoritative and the hash merely a pre-filter, because the hash
cannot see the title / aria-label / attribute permutations. Revision 2 develops
this as §6, where the directional tie-break (label surface form preferred on
token-equality) is what no hash-based scheme can express.

**E6. Missing concept: verified delta.**
Only deltas confirmed stable across consecutive observations may trigger
re-chunking. Revision 2 formalises this as a quiescence predicate (§8.3).

### Presentation errors

**E7. Angle-bracketed tag names were HTML-interpreted by the viewer**, e.g. a
code span containing the landmark tag list rendered as a column of bare slashes.
Revision 2 uses no angle brackets anywhere; element names are typeset
`\mathtt{...}` in mathematics and as bare words in prose.

**E8. The document was mostly corrections.** A technical paper should not carry
its own revision history inline. That material is now in this file.

### Scope change

Revision 1 mixed the emitted data structure with the algorithms that compute it.
The output contract now lives in `docs/OUTPUT_STRUCTURE.md` and is written to
survive replacement of every algorithm in the paper.

---

## Revision 2 → 3 (2026-08-09) — routed from MODEL

Not corrections of error. Three results were *missing* from THEORY, and their
absence was invisible until an interpretation was attempted. Raised in
`notes/proposals/MODEL.md`, routed under PROCESS §3, landed as theory.

**A1. `im(θ)` is a proper subset — now PROP-13.3.** THEORY quantified over
$\mathbb{N}^{(\Sigma_{\mathrm{tok}})}$ unrestricted. A tokenizer emitting
bigrams alongside unigrams cannot produce a vector holding a bigram without its
constituents, so statements ranging over the full carrier range over states no
value can produce. *Target: THEORY. Diagnosis: incomplete statement, not false.*

**A2. `df` is derived — now PROP-14.6.** THEORY treated the corpus and $df$ as
independent data. They are not: $df$ is a function of the corpus, so the pair
admits states denoting no corpus. *Target: THEORY.*

**A3. The carrier depends on the observation alphabet — now PROP-14.7.** THEORY
gave the corpus as a multiset. Retrieval returns identifiers, so a multiset does
not determine the observations and no abstraction to it is faithful. The carrier
must be an indexed family whenever identity is observed. *Target: THEORY.*

A3 is the one worth noting for method: it is not that the multiset was wrong,
but that whether it is right is settled by DOMAIN rather than by preference —
which is the grounding rule (PROCESS §2.1) doing work at the level of a carrier
choice.

## Open findings, routed but unresolved

**B1. Index insertion is grouping-sensitive — MODEL O-1.** *Target:
IMPLEMENTATION. Diagnosis: implementation divergence (PROCESS §4.1) — within a
call, candidates are deduplicated by content digest; across calls, dispatch is
on identifier and the digest map is written but never read.* Evidence:
`notes/observations/2026-08-09-index-batching.md`. Consequence: `df` depends on
batch size, hence `idf`, hence every score.

**Not yet actionable, deliberately.** The obvious repair — consult the digest
map across calls, as the module documents — makes `df` count distinct contents
rather than documents, at which point PROP-14.3 fails more deeply and the
abstract carrier itself would have to change. Which behaviour is *wanted* is a
design question that has never been asked, and answering it is a prerequisite to
the fix. Recorded here rather than fixed, so that the fix is not made by
accident.

**B2. DOMAIN is split — CONTENT_EXTRACTION_RULES §9.1.** *Target: DOMAIN, hence
IMPLEMENTATION.* The host and in-page detectors observe different spaces. MODEL
§11 is blocked on it: with two observation alphabets, the equality of MODEL §4.1
is undefined across the split, and the extraction stage cannot be interpreted.

**Downgraded 2026-08-09 on measurement.** Recorded first on set sizes — 81 skip
attributes against 15 — which implied an architectural fork. Measured
(`notes/observations/2026-08-09-domain-split-magnitude.md`), the disagreement is
**4.1% of detections and localised to five attributes**: `content` (22, host
only), `role` (9), `srcset` (6), `type` (1), `aria-description` (1). The two
detectors agree about 95.9% of what they actually find.

So B2 is a *reconciliation of five attributes*, not a decision about which
detector is authoritative — and the largest contributor, `content`, is page-level
metadata the in-page engine has no reason to see, which may be a scope
declaration rather than a code change. Still a precondition for interpreting
extraction; no longer a fork.

This is worth recording as a method point: the original entry cited a
*cardinality* where the load-bearing quantity was *yield*. METHOD A.12 says find
the dominant term before optimising; the same discipline applies to
prioritising a defect.

**B3. The invariant clauses are not independent — MODEL §4.2.** *Target: MODEL,
resolved by restatement.* Found by mutation-testing each clause in isolation and
failing: RI-2 ⟹ RI-4 ⟹ RI-5, all three keyed off row position. Not a defect in
the code or the theory — the invariant genuinely has this shape — but it was
undocumented, and it means a failure report does not localise its cause. Now
stated in MODEL §4.2 and asserted by a test.

**Explained 2026-08-09, and generalised.** B3 was recorded as a brute fact about
our five clauses. It is an instance of something general, now THEORY COR-22.7:
invariants arising from a chain of derivations inherit the chain's order, so the
set of violated clauses does not identify the origin. The measured order
RI-2 ⟹ RI-4 ⟹ RI-5 *is* the derivation order — identity duplicated into
metadata, digest map derived from metadata. The coupling was never a property of
the checks.

## Revision 11 → 12 (2026-08-10) — routed from the 54-page corpus benchmark

**A17. Identity separates only what its inputs separate — now PROP-22.5.10 and
COR-22.5.11.** Elementary, and the corollary is the one that bites: an input
that is a hash of a possibly-empty field is *maximally constant* exactly where
content is absent. A content digest looks like the most discriminating input
available and is degenerate on the class least likely to be inspected.
*Target: THEORY.*

**B10 (open, severe). The representation invariant fails on 50 of 54 real
pages.** Only RI-2 — identifier uniqueness. Mechanism: identity is
`sha1(url | pattern | sha1(html_raw))`, and **10.2% of instances render to empty
`html_raw`**; `sha1("")` is constant, so every empty-HTML instance sharing a
pattern gets one identifier. Largest observed class: **96 instances, 96 distinct
addresses, one identifier.** The index then admits duplicate identifiers because
`add_chunks` deduplicates new rows by content digest within a batch rather than
by identifier. *Target: IMPLEMENTATION, and it interacts with B6/B7.*

Distinct from THM-22.5.7's collapse, which is about content-*identical*
siblings. This is degeneracy, not indistinguishability, and the remedy is
different: an instance with no HTML and no text carries no content and arguably
should not be an instance at all — which would empty the degenerate class by
construction rather than repair identity.

**B11 (open). Instance sets are heavily nested.** 16,720 ancestor/descendant
pairs; only 6 of 54 pages clean. Content is therefore indexed both alone and
inside its ancestors, inflating `df` for nested terms. No live claim is
contradicted — the current THEORY does not assert our chunk sets are cuts — but
`chunk_containment` exists to enforce roughly this and on real pages does not.
*Target: unresolved between MODEL (state the obligation) and IMPLEMENTATION.*

**C13. Every previous verification was underpowered, and this is the proof.**
C5 and C7 flagged that the fixture might conceal defects. It did: RI-2 has held
on the fixture since it was written and mutation testing proved the check
non-vacuous — against a page that cannot exhibit the fault. **Non-vacuity on one
input is not adequacy.** The corpus turns 1 witness into 54 for the properties
that hold, and exposed two that do not.

## Revision 10 → 11 (2026-08-10) — routed from the layout-sensitivity audit

**A15. The generator shortcut for invariance testing is invalid as applied —
now PROP-10.10.** Adjacent transpositions generate the symmetric group, so
testing them ought to establish invariance under all permutations. The argument
requires invariance at *every* state; testing from one baseline gives it at one,
and the induction has no base. **Measured**: all 42 adjacent transpositions of a
baseline passed while random permutations of the same baseline found a real
leak. I had written the shortcut into the audit script's own docstring as
justification before the experiment refuted it. *Target: THEORY.*

**A16. Floating-point aggregates are not monoid homomorphisms — now
PROP-10.11, COR-10.12, COR-10.13.** THEORY treats aggregates as homomorphisms
out of free commutative monoids. Float addition is commutative with an identity
but **not associative**, so it is a magma, not a monoid, and a float aggregate is
a function of the enumeration *sequence* rather than of the collection. The
integer aggregates of §14 are unaffected; every real-valued one — scores, norms,
similarities — is an idealisation. *Target: THEORY. Diagnosis: unstated
hypothesis (exact arithmetic) present since the first draft.*

**C11 (fixed). Full-precision JSON scores made layout observable.** With
identifier order identical, the same corpus ingested in a different order printed
`0.25546887516975403` against `0.25546884536743164` — row order determines
summation order, which determines the low bits. The *text* output was unaffected
because it rounds to four places: **the leak was in the more faithful surface.**
Fixed by rounding JSON scores to six places (COR-10.13), above the ~3e-8 spread
and below any meaningful difference. Pinned by
`test_json_scores_do_not_expose_layout_precision`.

**C12. The audit's first run reported its own defects as leaks.** `ls` and
`info` differed under *every* permutation — wall-clock timestamps and a temporary
path, not layout. A probe reporting 100% of surfaces as leaking is reporting
itself; confounds are now scrubbed.

**B9 (open). One difference did not reproduce.** An intermediate run flagged
`search spectrograph --json` under a single permutation; a direct replay of the
same seed and permutation produced byte-identical output, and two further full
audits were clean. Unexplained. Non-reproducible nondeterminism is more
concerning than the reproducible kind, and it is recorded rather than treated as
noise. *Target: unknown, which is the problem.*

## Revision 9 → 10 (2026-08-09) — routed from the tie-ordering measurement

**A14. An equivalence can be enforced rather than asserted — now PROP-10.8 and
COR-10.9.** COR-10.7 described how an observation alphabet grows. The dual was
missing: an output cannot distinguish equivalent states **iff** it factors
through the quotient. An asserted equivalence is a standing claim about every
output; a factored one is a property of construction. COR-10.9 names the trap —
an output whose ordering is resolved by storage position makes storage position
observable, though it reports no index. *Target: THEORY. Diagnosis: missing
dual.*

**C9 (fixed). MODEL §4.1's quotient was false on ties.** §4.1 asserted that row
permutations are unobservable. Ranking resolved ties by row index, so the same
corpus inserted in a different order returned equally-scoring hits in a
different order — measured with two documents of disjoint vocabulary and a query
matching one term in each. Row order was observable, and every obligation stated
"up to observational equivalence" was stated up to a relation that did not hold.

Repaired **by construction**: ties now break on `chunk_id`, so the ranking is a
function of the multiset of (score, identifier) pairs and factors through the
quotient (PROP-10.8). Regression asserted by
`test_ranking_is_independent_of_insertion_order`.

**C10 (assessed, no change needed). Were the discharged obligations unsound?**
Re-read under the measured alphabet: no. Every obligation compares order-
invariant quantities — counts, per-column values, identifier sets, per-row
equalities — and none reads row *order*, so none depended on the false half of
the quotient (MODEL §4.1.1).

This is luck rather than design, and worth saying so. The obligations avoid the
broken equality because they were written against the store's internals rather
than its ranked output. **The one surface where order is the entire content —
retrieval — carries no obligation at all**, which is why the defect survived
every previous pass: nothing was looking there.

## Revision 8 → 9 (2026-08-09) — routed from the observability audit

**A12. Detection and observation are different alphabets — now DEF-10.4,
PROP-10.5, COR-10.6.** THEORY §0 grounds meaning in detectability, and MODEL
§4.1 then defined observational equivalence "relative to DOMAIN". That was a
category error. `CONTENT_EXTRACTION_RULES.md` enumerates what the extractor can
find *in a page*; equality of *stored states* needs what the system exposes
about them, and the two alphabets are incomparable — a fact may be detected and
never exposed, or exposed and never detected. *Target: THEORY and MODEL.
Diagnosis: conflation, present since MODEL was first drafted.*

The gap was specifically instance-level facts. Identity, position and
multiplicity are properties of an occurrence rather than of content, so none is
a content category and none appeared in DOMAIN — yet the identity design turns
entirely on whether they are exposed.

**A13. Observability is not free — now COR-10.7.** The observation alphabet is a
property of the output surfaces, so adding an output refines observational
equivalence and can invalidate an equality that held. **Adding a print statement
is a semantic change.** *Target: THEORY.*

**B8 (closed by measurement). Is position observable?** Yes — through
**exactly one surface**, `vertiscope show`. Measured by
`scripts/audit_observables.py`, now documented as DOMAIN §9.8.1 and asserted by
`test_position_escapes_through_exactly_one_surface`. Search, JSON search and
`ls` expose identity, pattern, content and url but not position.

Consequence: COR-22.5.8's condition fails, so stability and discrimination are
incompatible — and the three passes spent comparing identity functions were
doomed by one printed field. Conversely, by COR-10.7 removing that field would
dissolve the impasse. **The identity architecture hangs on whether `show`'s xpath
output is load-bearing or incidental.** Recorded, not decided.

**C8. DOMAIN's own completeness claim was scoped too narrowly to notice this.**
§9.7 already conceded the enumeration is verified only for the host detector. It
did not notice that the document answers a different question from the one MODEL
was asking of it. A completeness claim can be true and still be about the wrong
thing.

## Revision 7 → 8 (2026-08-09) — routed from the identity-collapse measurement

**A10. Stability and discrimination are incompatible — now THM-22.5.7 and
COR-22.5.8.** The previous pass framed identity as a search among candidates
constrained by three requirements, and reported that none satisfied all three.
The framing was wrong: *two* of the requirements are already jointly
unsatisfiable, and provisionality — the third — is not needed for the argument.
Transposing two content-identical siblings leaves the tree unchanged, so any
reshuffle-stable assignment gives them equal identifiers. *Target: THEORY.
Diagnosis: missing result; the search should never have been started.*

COR-22.5.8 relocates the decision to the observation alphabet: the two properties
are compatible iff content-identical siblings are indistinguishable. Ours are
distinguishable, because retrieval exposes position. So the identity question is
a DOMAIN question, which is where PROCESS §2.1 says it should have reduced.

**A11. Identity and multiplicity are separable — now REM-22.5.9.** The dichotomy
hides a third option: collapsing identical siblings is lossless iff their count
is retained, and PROP-10.2 already makes the extraction a multiset. *Target:
THEORY.*

**B7 (open). The store represents a multiset as a set.** Measured: 820 rendered
instances across three pages collapse to 746 rows — **74 lost, 9.0%** — with no
multiplicity column anywhere. This is the obligation MODEL never stated: that
$\alpha$ preserves multiplicity. It does not. *Target: unresolved between
IMPLEMENTATION (add the count) and MODEL (state the obligation).* Not remedied.

**C6 (fixed). `instances_written` over-reported by the collapse.**
`Store.upsert_instances` returned `len(records)` — records *offered* — rather
than rows written, so it claimed 672 where the store held 610. Every instance
figure this pipeline has ever reported, including in earlier summaries in this
workspace, was the rendered count. Now returns the distinct-identifier count;
`IngestReport` carries rendered, written and collapsed; a test requires
`rendered == written + collapsed` and `written` to equal the row count read back
from SQLite.

**C7. The offline suite cannot observe B7.** The fixture has no duplicate
siblings, so the collapse rate on it is 0% and every test passes on a page where
the phenomenon cannot arise. The finding needed a real page. This is the same
shape as C5 — a green suite that is silent rather than reassuring — and it argues
for the frozen corpus that `OPEN.md` has wanted since the first empirical pass.

## Revision 6 → 7 (2026-08-09) — routed from the identity blast-radius measurement

**A8. Provisionality is closed under depends-on — now DEF-22.5.3 and
PROP-22.5.4.** COR-22.5.2 treated a stored derived value as provisional when its
own map was. That is too narrow: a value depending on a provisional value is
provisional too, and the cost of a revision is measured over the *dependency
closure*, not over direct consumers. *Target: THEORY. Diagnosis: incomplete
result — the previous statement was true but did not compose.*

This is not academic. The previous pass audited direct consumers of
`generalize_xpath` and found `pattern`. The closure also contains `instance_id`,
which never mentions the map and is invalidated exactly as thoroughly.

**A9. An identifier reaching a provisional map is not an identifier — now
COR-22.5.5.** If identity is injective in a provisional component, revision
re-keys the state, so identity fails to persist at precisely the moment
continuity is most wanted: a correction. *Target: THEORY.*

**B6 (open, and the most consequential yet). `instance_id` is provisional.**
Measured by applying the §7.8 region-anchored map:
**427 / 653 identifiers re-keyed (65.4%)**, while distinct patterns rise 157→177
and 17→35 — the correction separates classes that are currently conflated, which
is PROP-12.4's prediction and the retrieval noise observed in the very first live
runs. *Target: unresolved between IMPLEMENTATION and THEORY.*

Why it is not simply a defect to fix: dropping `pattern` from the identity input
yields `sha1(url | content_hash)`, which collides for structurally distinct
instances with identical content — the sibling-`p` collision that cost 470+
chunks per scan in the production incident on record. The naive remedy
reintroduces the failure the pattern term exists to prevent. What is needed is a
*non-provisional structural discriminator*, and none is identified.

**C5. A passing test measured the wrong invariance.**
`test_instances_have_stable_ids_across_runs` asserts identifier stability and has
passed since it was written. It holds the generalization map fixed, so it
measures determinism across runs, not persistence across a revision — and the
latter is unobservable in any fixed-map experiment. Not a defect in the test; a
mismatch between what it measures and what its name suggests, which is how a
65% re-key could have landed unanticipated. Docstring corrected; the dependency
is now asserted separately.

## Revision 5 → 6 (2026-08-09) — routed from the unpoliced-redundancy finding

**A6. Detection is not prevention — now COR-22.5.1.** THEORY had 22.4 and 22.5
saying a stored derivation incurs an invariant and enlarges the illegal region,
but said nothing about what *checking* does. It does not shrink the region: a
predicate is a function on the state space and evaluating it changes nothing.
Adding a check is detection; removing the stored component is prevention; only
the second yields a tautology. *Target: THEORY. Diagnosis: missing result.*

**A7. A provisional derivation must not be stored — now COR-22.5.2.** Three
regimes under a revision of $f$: stored-unchecked goes stale silently;
stored-checked reports the staleness and requires a migration; derived is
unaffected. This is the decisive consideration whenever $f$ is expected to
change, and it converts a performance trade into a correctness one.
*Target: THEORY.*

A7 has immediate force here rather than being general advice. Our generalization
map is *known* to be provisional — PROP-12.4 requires region-anchoring, the
implementation is plain index-stripping (E1) — and `InstanceRecord.pattern`
stores its output. Correcting the map makes every stored pattern stale.

**B4 (closed). `pattern` was a redundancy with no invariant.** Raised in the
previous pass from a 43/43 measurement on one fixture, which was weak evidence.
Falsification attempted this pass over structurally varied inputs including a
shadow-DOM adversary: **758 instances, 0 divergent**. The redundancy is real.
*Target: MODEL, discharged.* Clause RI-R1 now exists
(`vertiscope/invariants.py::rr1_pattern_derived`), is asserted, and is shown
non-vacuous. This moves the record store from regime 1 to regime 2 of
COR-22.5.2 — an improvement, not a resolution.

**B5 (open). Eliminating `pattern` is the stronger remedy.** Measured: the
column is 9.9% of row payload plus a dedicated index; deriving costs 0.9 µs/row
cold and is effectively free warm. *Target: IMPLEMENTATION — schema and store
API.* Not made in this pass. The case does not rest on the 9.9%; it rests on
COR-22.5.2 and the map being provisional.

## Revision 4 → 5 (2026-08-09) — mathematical corrections to my own results

Three of the results added in revision 4 were wrong or ill-formed. Found by
re-reading the proofs adversarially rather than by any test. All are corrected in
place; the section numbers moved.

**C1. PROP-22.4's proof used the wrong hypothesis.** It concluded that violating
states exist "whenever $f$ is not constant". Constancy of $f$ is irrelevant: a
constant $f$ with $|C_i| \geq 2$ still admits a violating state (any value other
than the constant), and a singleton $C_i$ admits none regardless of $f$. The
correct hypothesis is $|C_i| \geq 2$ — the component's carrier is non-trivial.
The statement survives; the proof did not.

**C2. COR-22.5 counted something undefined.** It bounded "the number of
independent invariant clauses" below by the number of stored derivations. Clause
counts are not well defined — a single predicate may assert an arbitrary
conjunction, so the count depends on how one chooses to partition it. Replaced
with an exact statement about the state space: legal states are in bijection with
$C_{-i}$, so storing a derived component adds **no** legal states and exactly
$|C_{-i}| \cdot (|C_i| - 1)$ illegal ones. Cardinalities are well defined where
clause counts are not.

**C3. COR-22.7 was false.** It asserted that along a derivation chain
$c_2 = f(c_1)$, $c_3 = g(c_2)$, a violation of the first predicate propagates to
the second. Counterexample: take $c_2 \neq f(c_1)$ and $c_3 = g(c_2)$ — the first
fails, the second holds. The predicates constrain different pairs and nothing
links their truth values.

What is true is a statement about *reads*, now PROP-22.8: a mutation can falsify
only those predicates that read a mutated component, and the containment is
generally proper. COR-22.9 draws the honest conclusion — the firing set
identifies at most the components touched, and among predicates sharing a
read-set it does not discriminate at all. There is no "cause" to recover.

**Why this matters beyond the correction.** C3 was not a slip of notation; it was
a wrong *explanation* that fit the data. The measured firing sets are equally
consistent with a derivation chain and with a shared read, and I reached for the
first because the derivation structure was fresh from the redundancy analysis.
The two accounts diverge on a prediction — a chain has RI-5 fire when the
identifier sequence is perturbed — and the existing measurement already refuted
it. The evidence to distinguish them was in hand and unexamined.

Read-sets are now recorded in `vertiscope/invariants.py::READS` and the bound is
asserted by `test_firing_set_is_bounded_by_the_read_set`, including the proper
containment (RI-1 reads `_chunk_ids` and holds under the mutation). The
traceability checker caught the dangling `COR-22.7` citation in MODEL the moment
the renumbering landed, which is the mechanism working as designed.

**C4. PROP-14.7's proof omitted a hypothesis.** The two indexed families are
distinguishable only if $x \neq y$; with $x = y$ they are the same family. Added.

## Revision 3 → 4 (2026-08-09) — routed from the redundancy measurement

**A4. Invariants are incurred, not possessed — now PROP-22.4 and COR-22.5.**
THEORY treated representation invariants as given. Measuring which components of
the store are derivable from the others (four of six) against the clause count
(five) produced an exact correspondence: **every clause but one polices a stored
redundancy**. The general statement is that storing $c_i = f(c_{-i})$ makes the
agreement a nontrivial invariant, while not storing it makes the same predicate
a tautology. *Target: THEORY. Diagnosis: missing result, not false statement.*

**A5. Parallel indexing is the avoidable case — now PROP-22.6.** Two sequences
corresponding by position can be misaligned; one sequence of pairs cannot, since
no operation moves an element without its partner. Demonstrated rather than
argued by `test_a_unified_view_makes_alignment_undenotable`, which applies the
mutation that breaks the parallel form and shows it cannot be expressed in the
unified one. *Target: THEORY.*

Together A4 and A5 reframe the whole of MODEL §4: RI-1 is the only clause that
would survive de-duplicating the representation. The other four exist because
`_chunk_id_to_row`, `_df`, `_content_to_row` and the duplicated identifier are
stored rather than derived. That is recorded in MODEL §4.3 as analysis, not as a
proposal — the trade is real, and RI-3's derivation sits on the query path.

## Known unfinished business in revision 2

- §5's optimal-chunking dynamic program is new and is **not** what the shipped
  code does (the code performs the greedy leaf-up walk of §5.3). The claim that
  the greedy walk is a heuristic for the DP is proved only under Assumption 5.5;
  whether the shipped predicate satisfies it is unverified.
- Proposition 4.9's bound on antichain-metric computation assumes the ideal
  representation is materialised. For large pages a succinct representation is
  probably necessary; not worked out.
- §6.4's complexity for maximal-element extraction is the naive quadratic bound.
  The signature-based improvement is stated without proof.
- The corpus reading is incomplete (`notes/reading/COVERAGE.md`): 14,412 of
  21,770 lines unread, including `ontological_warp.md` in full.
