# Open questions / follow-ups

Things I could not resolve from the corpus or the code, or deliberately
deferred. Ordered by how much they'd change the design.

---

## Closed by the 2026-08-09 loop pass

**Is the correspondence between code and theory functional or relational?**
Functional, and injective on the observational quotient (MODEL §5). Obligations
are equalities; simulation relations are unnecessary. This had been blocking the
shape of the model document.

**Does the theory-to-code direction have a formal counterpart, or only prose?**
It has one: $\alpha \dashv \gamma$ is a Galois *insertion* for the index
(MODEL §7.3), so the abstraction is faithful up to representation detail. Its
three concrete uses are in §7.4.

**Is the index's `df` the homomorphism THEORY describes?** No — grouping is
observable (MODEL O-1, `notes/observations/2026-08-09-index-batching.md`).
Routed to IMPLEMENTATION as ERRATA B1, deliberately not repaired: the obvious
repair is worse than the defect.

**Does exact retraction hold when removed and surviving documents share tokens?**
Yes, discharged by `test_retraction_is_exact_under_partial_token_overlap`.

**Do the index and record store agree on their identifier domains?** No, and
they were never meant to — containment holds one way and the residue is exactly
the empty-text rows (MODEL O-5). The original statement of the obligation was
false and was corrected by attempting to discharge it.

---

## Opened by the same pass

**What behaviour is actually wanted from cross-corpus deduplication?** ERRATA B1
cannot be resolved without it. Counting *documents* keeps PROP-14.3 and lets
boilerplate dominate `df`; counting *distinct contents* suppresses boilerplate
but changes the abstract carrier from documents to contents-with-multiplicities.
This has never been asked, and the code currently does neither consistently — it
does the second within a batch and the first across batches. **This is the
highest-value open question in the workspace.**

**Is $\mathcal{K}$ exactly characterisable?** PROP-13.3 gives coherence as
necessary and notes a counting identity as a second necessary condition;
sufficiency is unproven. Until it is, $\gamma$'s use as a test-input generator
(MODEL §7.4.1) cannot be mechanised, because generating a *realisable* abstract
state requires deciding membership in $\mathcal{K}$.

**Which of the two detectors is DOMAIN?** ERRATA B2. Still a precondition for
interpreting extraction, but **downgraded on measurement**: the split is 4.1% of
detections across five attributes, not an architectural fork. The question is now
"reconcile these five", and for the largest (`content`, page-level metadata) the
answer may be a scope declaration rather than a code change.

---

## Opened by the 2026-08-09 empirical pass

**Is the detectable-content space complete for the *in-page* detector?**
`CONTENT_EXTRACTION_RULES` is verified complete for the host and silent about the
engine, which has no enumeration at all. Until one exists, DOMAIN describes one
of two detectors and the grounding rule (PROCESS §2.1) rests on half the system.
Extracting it is mechanical — the constants are in the JS — and is a
precondition for B2.

**Do the commuting obligations have teeth?** Mutation testing has been applied to
the five RI clauses only. O-2, O-4 and O-5 are asserted by tests that have never
been shown capable of failing. The technique is now in place
(`tests/test_invariant_adequacy.py`); extending it is cheap.

**Would generated inputs find what examples miss?** Every test is example-based
over one synthetic fixture and one archived page. `hypothesis` is not installed.
The claims most exposed to this are the universally quantified ones — chunk
roots forming an antichain, identifier stability under re-scan — where a single
fixture proves nearly nothing.

**Why is `core/scanner.py` at 12% coverage?** The live-scrape path is verified
only by manual runs against the internet. It is also the path with no frozen
corpus, so its behaviour has never been reproducibly measured.

---

## Closed by the redundancy pass

**Why are the invariant clauses coupled?** ~~Because they are ordered by a
derivation chain.~~ **That answer was wrong** and is corrected in ERRATA C3:
violations do not propagate along derivations. They are coupled because several
clauses *read the same component* — PROP-22.8. RI-2 and RI-4 both read
`_chunk_ids`; RI-4 and RI-5 both read `_chunk_meta`. The two accounts make
different predictions and the existing measurement already discriminated them.

**How many invariants does the store actually need?** One. RI-1 alone asserts
well-formedness of the primary data; the other four police stored redundancies
(MODEL §4.3), measured four-of-six derivable against five clauses.

## Opened by the redundancy pass

**Is RI-3's cache worth its invariant?** It is the only one of the four whose
elimination has a real price — deriving `df` means a column scan on the query
path. The other three are cheap to derive and buy nothing but an invariant, a
check, a mutation test and a way to be wrong. Worth measuring the actual query
cost before treating the cache as settled.

> **Answered.** See "Closed by the unpoliced-redundancy pass" below. The
> question stands as written because the *general* form — are there others? —
> remains open for the pipeline stages.

**Are there redundancies with no invariant?** Yes — one found immediately.
COR-22.5 bounds clauses below by redundancies, so redundancies may *exceed*
clauses, and any excess is a cached value nothing checks. The index happened to
have a clause per redundancy; the record store does not.

`InstanceRecord` stores `pattern` alongside `absolute_xpath`, and pattern is a
function of address (PROP-12.2). Measured: `pattern == generalize_xpath(
absolute_xpath)` for **43/43** instances — so it is derivable, and therefore a
stored redundancy. MODEL states no clause for it and no test checks it. This is
the worse case of PROP-22.4: the invariant is incurred but not paid, so the two
can diverge silently.

It also matters more than the index's four, because generalization is the map
whose definition is contested — if `generalize_xpath` is ever corrected to be
region-anchored (PROP-12.4, currently plain index-stripping), every stored
`pattern` becomes stale with nothing to detect it. **Route: MODEL should state
the clause; a test should police it.** Not done in this pass.

## Blocking the algorithm

1. **Which identity function wins?** Three exist (§4 of notes/02) and each fails
   somewhere: pattern-keyed lost 470+ chunks/scan in production; position-keyed
   fragments under sibling reshuffle; content-keyed cannot express
   `chunk_replaced`. My proposal (THEORY §3.3) splits *identity* from *address*
   from *revision*, but that is my synthesis, not the corpus's — needs a ruling.

2. **Is `chunk_replaced` needed at all for a batch CLI?** The whole
   stable-id requirement exists to update a 3D sphere in place. vertiscope has no
   scene. If we never emit `replaced`, content-keyed identity is strictly
   better. Decide before building `Ingest`.

3. **Landmark anchoring vs deepest-anchor-tag.** Spec §7.8 argues landmark
   (nearest semantic ancestor, prefix verbatim); shipped JS does deepest
   ANCHOR_TAGS. Are these known to differ in practice, or did the JS just
   simplify? Affects every pattern key, so it affects dedup and retrieval.

4. **`ontological_warp.md` — 2,091 lines, untriaged.** Largest unread doc. Name
   suggests it may bear on the embedding/projection space. Must triage.

## Design questions I formed while reading

5. **Does token-set subsumption compose with TF-IDF?** Subsumption drops
   subsumed units *before* indexing, so `df` no longer counts them. That is the
   intent (clean rendering), but it means the index's notion of document
   frequency is over deduplicated text — retrieval scores are not comparable to
   a non-deduped baseline. Should the benchmark hold dedup fixed?

6. **Golden trio as a retrieval prior.** `(title, link, content)` joint-presence
   already filters nav/footer/sidebar. That is *exactly* the noise I measured
   ranking too highly. Cheaper and more principled than my BM25 length prior?
   Or complementary — trio gates *membership*, BM25 fixes *scoring*.

7. **Is `subtree_text_budget` a monoid under the collapse phase?** Structural
   collapse splices nodes out *after* budgets are computed. If collapse changes
   which units survive, the budget that drove chunk-boundary selection is not
   the budget of the printed tree. Possible inconsistency between the boundary
   decision and the output. Check against the golden I/O.

8. **Regex-for-primitives arm.** §1.2.1 lists URL/date/currency/email/hash/xpath
   as regex-detected primitive types. vertiscope only does URL + JSON. Is the rest
   in scope for a retrieval CLI, or is it editor-side typing?

## Verification gaps

9. No frozen corpus yet — every live number I have is one-shot against the
   live internet and is not reproducible.

10. The §10.1 index invariants (5 of them) are stated as "unit tests should
    assert these after every `_process_delta`". We have no `_process_delta`, but
    those invariants are the correctness spec for when we build one. Lift them
    verbatim into the test suite at that point.

11. Golden I/O test from `HTML_DEDUP_CONTENT_TREE_GOAL` §1 (archive.org card →
    exactly 10 lines) is a *free, binding* regression test we are not running.
    Cheapest high-value test available. Do this early.

---

## Closed by the unpoliced-redundancy pass

**Is `pattern` genuinely derivable, or was 43/43 a coincidence of the fixture?**
Genuinely derivable. Falsification attempted over four structurally varied
inputs including a synthetic shadow-DOM adversary: **758 instances, 0
divergent**. The clause RI-R1 now polices it and is shown non-vacuous.

**Does adding a check resolve an unpoliced redundancy?** No — COR-22.5.1. A
check is *detection*; the illegal states remain reachable. Only not storing the
component empties the region. The record store moved from regime 1 (stale
silently) to regime 2 (stale detectably), which is an improvement and not a
resolution.

**Is RI-3's cache worth its invariant?** Reframed rather than answered. The
question was posed as a performance trade; COR-22.5.2 says that is the wrong
frame whenever the derivation is provisional. `df`'s derivation — column
nonzero counts — is *not* provisional, so for RI-3 the performance framing is
correct and the query-path cost still needs measuring. For `pattern` it is not,
because the generalization map is under revision.

## Opened by the same pass

**Should `pattern` be eliminated rather than checked?** ERRATA B5. Measured at
9.9% of row payload plus an index against 0.9 µs/row to derive, so the cost
favours elimination — but the decisive argument is COR-22.5.2: correcting
`generalize_xpath` to be region-anchored (PROP-12.4) turns every stored pattern
into a migration. **Sequencing question: eliminate `pattern` before correcting
the map, or accept one migration?** Doing it in the wrong order pays the
migration cost for nothing.

**Which other stored values are outputs of provisional derivations?**
~~Only `pattern` audited.~~ **Answered for `instance_id`: it is provisional, and
correcting the map re-keys 65.4% of identifiers** (ERRATA B6). The audit method
was also wrong — I checked direct consumers of `generalize_xpath`, but
provisionality is closed under depends-on (DEF-22.5.3), so the closure is what
must be audited. `Chunk.char_count` and the `content_hash` digests remain
unaudited; `content_hash` derives from `html_raw` and looks non-provisional, but
that has not been checked against the closure.

**Does the read-set model extend to the record clauses?** `READS` covers the
five index clauses; RI-R1 lives in a separate family over a different carrier
and has no read-set recorded. PROP-22.8 is therefore unusable for it.

---

## Opened by the identity blast-radius pass

> **Dissolved, not answered.** THM-22.5.7 shows the search was misconceived:
> reshuffle stability alone already forbids discriminating content-identical
> siblings, so no discriminator — provisional or not — can satisfy both. See
> "Closed by the identity-collapse pass" below.

**What non-provisional structural discriminator can identity use?** ~~The central
open question now.~~ Identity currently uses `pattern`, which is provisional
(COR-22.5.5). Dropping it collides on structurally distinct instances with equal
content — the sibling-`p` failure that cost 470+ chunks/scan in production. So
neither keeping nor dropping is right, and what is wanted is a discriminator
that separates structure without depending on a map still under revision. The
*absolute address* is one candidate — it is not derived from anything
provisional — but it re-keys under sibling reshuffle, which is the failure the
content-keyed scheme was chosen to avoid. **No option currently satisfies all
three constraints, which suggests the constraint set is what needs examining.**

**Should the map be corrected before or after identity is decoupled?** Doing it
in the wrong order pays a 65% re-key that a later decoupling would have avoided.
This is now a sequencing problem across three changes — correct the map,
eliminate stored `pattern` (ERRATA B5), decouple identity (B6) — and their order
determines how many migrations are paid.

**Are there other tests measuring a different invariance from their name?** C5
found one by accident, while chasing something else. The class of error is
"passing test, wrong property", which no coverage or mutation metric detects —
mutation testing confirms a test can fail, not that it fails for the right
reason. Worth an explicit audit of the assertion set against what each property
is meant to guarantee.

---

## Closed by the identity-collapse pass

**What non-provisional structural discriminator can identity use?** None, and
the question was malformed. THM-22.5.7: transposing two content-identical
siblings leaves the tree unchanged, so any reshuffle-stable identity gives them
equal identifiers. Provisionality is irrelevant to the argument. COR-22.5.8
moves the decision to the observation alphabet — the two properties are
compatible iff such siblings are indistinguishable, and ours are distinguishable
because retrieval exposes position.

**Is the constraint set satisfiable?** No. Two of the three constraints are
already incompatible; the third was never the obstacle. This is why comparing
candidate identity functions produced no winner over three passes.

## Opened by the identity-collapse pass

**Should the record store carry a multiplicity column?** ERRATA B7. REM-22.5.9
says collapse is lossless iff the count is retained, PROP-10.2 says the
extraction is a multiset, and the store is a set — 9.0% of cardinality
discarded. Adding an integer is trivial; deciding whether two identical cards
*are* two things is not, and that is a DOMAIN question (COR-22.5.8) rather than
a schema one.

**Is position observable, or merely exposed?** COR-22.5.8 turns the identity
design on this, so it now needs a ruling rather than an assumption.
`absolute_xpath` is returned by retrieval and stored per row — but "we currently
return it" is not the same as "it is part of the observation alphabet".
CONTENT_EXTRACTION_RULES enumerates *content* categories and says nothing about
whether an instance's position is itself observable. **This is the smallest
unanswered question with the largest downstream reach.**

**How many other properties hold only on the fixture?** C7 is the second case
(after C5) of a green suite that is silent rather than reassuring: the fixture's
collapse rate is 0%, so no test could have seen B7. The frozen corpus has been
wanted since the first empirical pass and each subsequent pass has produced
another reason for it.

---

## Closed by the observability audit

**Is position observable, or merely exposed?** Observable — through exactly one
surface, `vertiscope show` (DOMAIN §9.8.1, measured). The question was well posed and
the answer was mechanically determinable all along: an observation alphabet is a
property of output surfaces, not a matter for decree.

**What alphabet does MODEL §4.1's equality rest on?** It had been resting on the
detection alphabet, which is the wrong one (ERRATA A12). Corrected: DOMAIN now
carries the observation alphabet as §9.8.1, generated by
`scripts/audit_observables.py`.

## Opened by the observability audit

**Is `vertiscope show`'s xpath output load-bearing or incidental?** The whole
identity architecture hangs on it. With position observable, stability and
discrimination are incompatible (COR-22.5.8) and the 9% collapse is lossy.
Without it, content-keying satisfies both and the impasse dissolves. `show` is
the inspect-one-instance command and an xpath is plausibly its point — so this
is a genuine product question, not a technicality, and it belongs to whoever owns
that surface.

**Should the observation alphabet be regenerated in CI like DOMAIN is?**
`scripts/audit_observables.py` produces §9.8.1 and a test pins the shape, but
nothing regenerates the table itself. By COR-10.7 any new output can change it,
and the failure mode is a silently stale alphabet under which equalities are
asserted — the same class of decay `dump_extraction_rules.py` exists to prevent.

**Which other invariants are stated up to an equality that was never pinned?**
COR-10.7 says equalities depend on the alphabet. MODEL's obligations are stated
up to observational equivalence, which until this pass was undefined in
practice. They were checked against a *specific* notion of sameness that nobody
had written down; whether each remains true under the measured alphabet has not
been rechecked.

---

## Closed by the tie-ordering pass

**Which invariants are stated up to an equality that was never pinned?** All of
them were, and the equality was false on ties. Re-examined: none of the
discharged obligations depended on the false half, because all compare
order-invariant quantities (MODEL §4.1.1). Repaired by making the ranking factor
through the quotient rather than by restating the claim.

**Is row permutation unobservable?** It was not — ranking resolved ties by row
index. It is now, by construction (PROP-10.8).

## Opened by the tie-ordering pass

**Retrieval has no obligation stated over it.** This is the gap that let C9
survive every previous pass: MODEL interprets the store's *state* and says
nothing about its *ranked output*, which is the surface users actually see and
the only one where order is the entire content. A commuting condition over
ranking — what abstract object is a ranking, and what must it commute with? — is
absent. **This is now the largest structural hole in MODEL.**

**Where else is an order imposed that the data does not determine?** COR-10.9
generalises beyond ranking: iteration over dictionaries (`_content_to_row`,
`_vocab`), enumeration of `fields_json` keys, the order of `member_xpaths`. Each
is a candidate leak of storage layout into observable output, and none has been
audited. The ranking case was found only because ties were the obvious place to
look.

**Should `audit_observables.py` also probe *order* sensitivity?** It currently
answers "which fields escape", not "does the output depend on storage layout".
The second question is what caught C9, and it was asked by hand.

---

## Closed by the layout-sensitivity pass

**Where else is an order imposed that the data does not determine?** Audited
mechanically rather than by guesswork: `scripts/audit_layout_sensitivity.py`
permutes ingest order — which permutes rows, vocabulary columns and dict
iteration at once — and diffs every CLI surface. Found one real leak (float
precision in JSON scores, C11) and two probe confounds. Two subsequent full runs
clean.

**Should `audit_observables.py` also probe order sensitivity?** Answered by
building a separate probe for it. The two ask different questions — *which
fields escape* versus *does output depend on layout* — and keeping them separate
kept each interpretable.

## Opened by the layout-sensitivity pass

**What is the unexplained non-reproducible difference?** ERRATA B9. It appeared
once and has not recurred under replay or two further audits. Until explained,
every "no leak" result carries an asterisk, because the same unknown could
suppress a real leak as easily as it produced a phantom one.

**Are library returns part of the observation alphabet?** `Hit` and
`InstanceRecord` expose raw floats and were not audited. DOMAIN §9.8.1 left the
same question open for `Store.get_instance` on the grounds that returning an
object is not rendering it. But a library consumer *is* an observer, and if they
count, the float leak is unfixed at that surface — rounding was applied only to
the CLI.

**Which other real-valued aggregates are idealised as homomorphisms?**
COR-10.12 says none of them is one. The abstraction map α (MODEL §5) treats the
index as exact; `_row_norms_cache` and the cosine computation are float
aggregates over rows. Whether α is well defined on them — whether two layouts of
the same corpus abstract to the *same* abstract state — has not been rechecked
under PROP-10.11.

---

## Closed by the corpus benchmark

**Is the frozen corpus worth building?** Yes, decisively. 54 pages, first run,
exposed two defects invisible to the fixture — RI-2 failing on 93% of real pages
(B10) and pervasive instance nesting (B11) — and gave 54 witnesses to the four
properties that do hold. Wanted since the first empirical pass; every subsequent
pass produced another reason.

**How many other properties hold only on the fixture?** At least one, and it was
the representation invariant itself. Answered by measurement rather than
speculation.

## Opened by the corpus benchmark

**Should an instance with no HTML and no text be an instance at all?** 10.2% of
rendered instances have empty `html_raw`, and they are the mechanism behind B10.
Filtering them at the source empties the degenerate class *by construction*
(PROP-22.4(2)) rather than repairing identity — the laminar remedy. But it
changes what the pipeline emits, and whether such instances carry information in
their `fields` has not been checked.

**Why is `add_chunks` deduplicating new rows by content rather than identifier?**
Within a batch it merges on content digest; across batches it dispatches on
identifier (ERRATA B1). Neither path merges *new* rows sharing an identifier,
which is what admits the RI-2 violation. The two dedup keys were chosen
independently and their interaction was never stated.

**What is the intended relationship between instances and the containment
filter?** B11 shows nesting is pervasive. `chunk_containment` filters chunks by
ancestry, but instances are rendered per member xpath and are not filtered the
same way — so the property the filter establishes for chunks does not survive to
instances. MODEL states no obligation over instance nesting.

**Should the corpus be sampled twice to measure temporal variation?** Every page
is a single snapshot, so re-scan stability — the property `instance_id` exists to
provide — is still untested against real change.
