# MODEL — the interpretation of THEORY in the implementation

> **STATE: DRAFT** — 2026-08-09. Scope: the index and the record store. The
> extraction stage is deliberately excluded (§12). This draft also proposes a
> new artifact kind; PROCESS §2 names seven and none does this job.

---

## 1. Genre, and what it obliges

A document relating theory to code can be written in at least four ways, and the
choice determines what it must contain. Naming it first is what keeps the result
from degenerating into a list of assertions.

**Chosen: abstract interpretation for the spine, data refinement for the
per-operation obligations, model-theoretic interpretation at the leaves.**

- The **spine** is a pair of maps between a concrete semantics and an abstract
  one: $\alpha$ from concrete to abstract, $\gamma$ from abstract to concrete.
  This is the only one of the four framings that is natively *bidirectional*:
  $\alpha$ is code-to-theory, $\gamma$ is theory-to-code, and whether they form
  an adjunction $\alpha \dashv \gamma$ is the precise form of "are the two
  directions compatible". [Cousot and Cousot 1977.]
- The **obligations** are per-operation commuting conditions: a representation
  invariant carving out legal concrete states, and for each operation a required
  relationship between doing it concretely then abstracting, versus abstracting
  then doing it abstractly. [Hoare 1972; Liskov and Guttag.]
- The **leaves** are a symbol-by-symbol interpretation of THEORY's signature.

**The genre obliges six contents:** a signature (§2); a concrete universe (§3);
a representation invariant (§4); an abstraction map with its domain and fibres
(§5); a commuting condition per operation (§6); and an equality (§4.1). Anything
not serving one of those is out of scope.

### 1.1 Excluded

A denotational semantics of the host language; mechanized proof; categorical
generality beyond naming the adjunction. The failure modes here are hypothesis
mismatch and silent drift, not subtle proof error, and the apparatus should
match the failure mode.

---

## 2. The signature to be interpreted

| symbol | THEORY | kind |
|---|---|---|
| $\Sigma_{\mathrm{tok}}$ | §13.1 | carrier — token alphabet |
| $\theta$ | DEF-13.1 | operation — tokenization $\mathrm{Str} \to \mathbb{N}^{(\Sigma)}$ |
| $\mathbb{N}^{(\Sigma)}$ | DEF-14.1 | carrier — frequency vectors |
| $\uplus$, $\subseteq_m$ | §2.6 | operation, relation |
| $\mathcal{D}$ | §14 | carrier — the corpus |
| $df$ | PROP-14.3 | operation — $\mathbb{N}^{(\mathcal{D})} \to \mathbb{Z}^{(\Sigma)}$ |
| $\mathrm{idf}$ | REM-14.5 | derived quantity, *not* an aggregate |
| $\mathrm{Gr}$ | THM-2.8.1 | construction — group completion |

Two notes before mapping. $\mathcal{D}$ is a **multiset**, and PROP-14.3's
homomorphism is out of the *free commutative* monoid on it, so neither order nor
grouping of insertions may matter. And $\mathrm{idf}$ is explicitly not in the
image of any per-document homomorphism, so it must not appear in the concrete
state; if it does, that is a finding.

---

## 3. The concrete universe

A state of the index is what `GlobalTfidfStore` holds:

$$c \;=\; (\mathrm{vocab},\ \mathrm{tf},\ \mathrm{df}_c,\ \mathrm{ids},\ \mathrm{meta},\ \mathrm{c2r})$$

with $\mathrm{vocab}$ a token-to-column injection, $\mathrm{tf}$ a sparse
non-negative integer matrix, $\mathrm{df}_c$ a vector over columns,
$\mathrm{ids}$ a sequence of identifiers indexing rows, $\mathrm{meta}$ the
index-aligned per-row metadata, $\mathrm{c2r}$ a digest-to-row map.

A state of the record store is the `instances` relation: a finite set of tuples
keyed by identifier, carrying pattern, address, rendered text, fields and
provenance.

The system state is the pair. §11 treats their interaction.

---

## 4. Representation invariant

$\mathrm{RI}(c)$ holds when:

1. $\mathrm{tf}$ has $|\mathrm{ids}|$ rows and $|\mathrm{vocab}|$ columns;
2. $\mathrm{ids}$ has no repeats and the identifier-to-row map inverts it;
3. $\mathrm{df}_c[j]$ is the number of rows nonzero in column $j$;
4. $\mathrm{meta}$ is index-aligned with $\mathrm{ids}$;
5. every digest in $\mathrm{c2r}$ points at a row whose stored digest matches.

$\alpha$ is defined only where $\mathrm{RI}$ holds. Clause 3 is load-bearing: it
is the only clause tying the maintained aggregate to the matrix it summarises,
and every retraction path must re-establish it.

The clauses are executable — `vertiscope/invariants.py` — so $\mathrm{RI}$ can be
evaluated against live state, which is $\gamma$'s second use (§7.4).

### 4.1.1 Re-examining the obligations under the measured equality

Each obligation is re-read against the alphabet of DOMAIN §9.8.1 and the repaired
quotient. The question is whether its verdict *depended* on the equality being
what §4.1 claimed.

| obligation | depended on the quotient? | status |
|---|---|---|
| O-1 insertion is a homomorphism | no — it compares `doc_count` and `df`, both order-invariant scalars | **unaffected**; still fails |
| O-2 retraction is exact | no — compares `df` recomputed from the matrix, per column | **unaffected**; still discharged |
| O-3 tokenization is not a homomorphism | no — a statement about $\theta$ alone | unaffected |
| O-4 upsert idempotent | no — compares row counts and contents by identifier | unaffected |
| O-5 domain containment | no — compares identifier sets | unaffected |
| RI-1 … RI-5 | no — all quantify over rows or columns without ordering them | unaffected |
| RI-R1 pattern derived | no — per-row equality | unaffected |

**Verdict: no discharged obligation was resting on the false half of the
quotient.** Every one compares order-invariant quantities — counts, per-column
values, sets of identifiers, per-row equalities — and none reads the *order* of
rows. The falsity of the row-permutation claim would have mattered to an
obligation stated over *ranked output*, and there is none.

This is a better outcome than it looks, and worth being explicit about why it is
luck rather than design: the obligations avoid the broken equality because they
were written against the store's internals, not against its ranked output. The
one surface where order is the whole content — retrieval — has no obligation
stated over it at all. §11 records that gap.

### 4.2 The clauses are not independent

Measured, not assumed (`notes/observations/2026-08-09-test-adequacy.md`):

| mutation touches | clauses that fired |
|---|---|
| `_chunk_ids` | RI-2, RI-4 |
| `_chunk_meta` | RI-4, RI-5 |

**The reason is a shared read, not a derivation chain.** The first account of
this — that a violation of RI-2 *propagates* to RI-4 and thence to RI-5 — was
mathematically wrong, and THEORY §22.7 now says so explicitly: violations do not
propagate along derivations, since $c_2 \neq f(c_1)$ is entirely compatible with
$c_3 = g(c_2)$. What actually links the clauses is PROP-22.8: a mutation can
falsify only those clauses that *read* a mutated component. RI-2 and RI-4 both
read `_chunk_ids`; RI-4 and RI-5 both read `_chunk_meta`.

The two accounts make different predictions and the measurement discriminates
them: a chain would have RI-5 fire when the identifier sequence is perturbed. It
does not.

Read-sets are recorded in `vertiscope/invariants.py::READS`, since PROP-22.8 is
unusable without them — the clause statements do not carry them. The containment
is proper, as the proposition allows: RI-1 reads `_chunk_ids` and holds under a
mutation that duplicates an identifier without changing the sequence length.

Operational consequence, restated correctly under COR-22.9: **the set of firing
clauses identifies at most the components that were mutated, and among clauses
sharing a read-set it does not discriminate at all.** There is no "cause" to
recover — the notion is not expressible in these terms.

The coupling is asserted by `test_the_coupling_map_is_as_documented`, so a later
restatement of the clauses that changed it would be caught rather than silently
invalidating this section.

### 4.3 Every clause but one is a stored redundancy

PROP-22.4 says an invariant of this kind is *incurred* by storing what could be
derived, and COR-22.5 bounds the clause count below by the number of derived
components stored. Applied here, and measured — each derivation was reconstructed
from the other components and compared:

| clause | the redundancy it polices | derivable from | agrees |
|---|---|---|---|
| RI-2 | `_chunk_id_to_row` | `enumerate(_chunk_ids)` | yes |
| RI-3 | `_df` | column nonzero counts of `_tf` | yes |
| RI-4 | `_chunk_ids` duplicated in `_chunk_meta[i].chunk_id` | either copy | yes |
| RI-5 | `_content_to_row` | `_chunk_meta[i].content_hash` | yes |
| RI-1 | — | — | **not a redundancy** |

Four of six stored components are functions of the others; four of five clauses
police exactly those four. The correspondence is not approximate.

**RI-1 is the only genuine invariant.** It relates the matrix's dimensions to the
two naming structures, and asserts well-formedness of the primary data rather
than agreement between a cache and its source. It would survive any
de-duplication of the representation; the other four would not exist.

**The redundancy structure and the read structure are different things**, and
§4.2 concerns the second. The derivations above say which clauses are
*eliminable*; PROP-22.8's read-sets say which can fire *together*. They are
related — a clause policing $c_i = f(c_{-i})$ necessarily reads both sides, so a
derivation induces a shared read — but the induced relation is symmetric, which
is why the firing sets are symmetric while the derivations are directed.

**What laminarity would cost and buy here.** By PROP-22.6, folding `_chunk_ids`
and `_chunk_meta` into one sequence of records makes RI-4 undenotable — there is
no operation that moves an identifier without its metadata. RI-2 and RI-5 fall to
derivation at the cost of building a lookup per query; RI-3 falls at the cost of
a column scan, which is the one with a real price since it is on the query path.
The end state has one clause where it now has five, no coupling, and no mutation
tests to write because nothing remains that could be misaligned.

This is *analysis, not a proposal* — it is recorded so that the trade is explicit
if the representation is ever revisited, and so that anyone adding a sixth cached
component knows they are adding a sixth clause.

### 4.1 The equality

Two concrete states are equivalent when no observation distinguishes them.

**Corrected 2026-08-09.** This section previously said that
`CONTENT_EXTRACTION_RULES.md` "enumerates the observation alphabet". It does
not: by THEORY PROP-10.5 that document is a *detection* alphabet — what the
extractor can find in a page — and the two are incomparable. Equivalence of
stored states needs the observation alphabet, which is a property of the output
surfaces. The equality below was resting on the wrong alphabet.

The observation alphabet is now measured (`scripts/audit_observables.py`) and
documented at DOMAIN §9.8.1, so *observational equivalence* is a definite
relation rather than a gesture —

**And the quotient it defines was, until this pass, false.** §4.1 asserted that
column and row permutations are unobservable "and must be quotiented out". Column
permutation is indeed unobservable. **Row permutation was not**: ranking resolved
ties by row index, so the same corpus inserted in a different order returned
equally-scoring hits in a different order. Measured directly — two documents with
disjoint vocabulary and a query matching one term in each score identically, and
the returned order followed insertion order.

By COR-10.9 an output whose ordering is resolved by storage position makes
storage position observable, even though it reports only scores and identifiers
and never an index. The order *is* the leak.

**Repaired by construction, not by restating the claim.** Ties now break on
`chunk_id`, so the ranking is a function of the multiset of (score, identifier)
pairs and factors through the quotient (PROP-10.8). Row order cannot leak. The
equivalence is now enforced rather than asserted, and
`test_ranking_is_independent_of_insertion_order` fails if that regresses.

**Status of everything stated up to this equality.** Every obligation in §6 and
§8 was stated "up to observational equivalence" while that relation was both
undefined in practice and, where defined, false on ties. They were checked
against a notion of sameness nobody had written down. They are re-examined in
§4.1.1 rather than left implicitly revalidated. Column permutations of $\mathrm{vocab}$ and row permutations of
$\mathrm{tf}$ are unobservable and are quotiented out; without this, every
obligation in §6 fails for uninteresting reasons and the real failures are
buried. Write $C/{\approx}$ for the quotient.

---

## 5. The abstraction map

Two features of the abstract object are dictated by the observation alphabet,
and both are now theory rather than local corrections — they were raised here,
routed to THEORY, and returned as results this section cites.

**(a) $df$ is derived, not independent · PROP-14.6.** The corpus determines
$df$, so carrying both as independent abstract components admits states in which
they disagree. Clause 3 of $\mathrm{RI}$ is exactly PROP-14.6's constraint
transported to the concrete side — and PROP-14.6's closing sentence, that
agreement is an invariant to be checked and never inferred from the type, is why
`test_ri_df_is_derived_from_the_matrix` recomputes rather than trusts.

**(b) A bare multiset is too coarse · PROP-14.7.** Retrieval returns
identifiers — `search` yields `(chunk_id, score)`, measured — so identity is
observable, and PROP-14.7 then forces the carrier. The abstract object is an
**indexed family**, not a multiset:

$$A \;=\; \bigl\{\, a : I \rightharpoonup_{\mathrm{fin}} \mathbb{N}^{(\Sigma)} \,\bigr\},
\qquad
\alpha(c) \;=\; \bigl[\, \mathrm{ids}[i] \mapsto \theta(\text{row } i) \,\bigr]_i .$$

THEORY §14 states the corpus as a multiset; the implementation shows the index
requires an indexed family. This is a refinement of the abstract object, not a
defect in either side, and it should be routed to THEORY as a scope correction.

**$\alpha$ is a function.** Given $c$ satisfying $\mathrm{RI}$, $\alpha(c)$ is
uniquely determined. The consequence for the document's shape is real:
obligations may be stated as *equalities between abstract values*, and the
apparatus of simulation relations is unnecessary. Had $\alpha$ been relational,
every obligation below would weaken to a refinement inequality.

**$\alpha$ is injective on $C/{\approx}$.** After quotienting by §4.1 the only
concrete freedom remaining is column and row ordering, both quotiented; and
identifiers and token multisets are preserved. So distinct classes have distinct
images.

---

## 6. Commuting obligations

For $\mathrm{op}$ with abstract counterpart $\mathrm{op}^{\sharp}$, the
obligation is $\alpha(\mathrm{op}(c)) = \mathrm{op}^{\sharp}(\alpha(c))$.

### O-1 — insertion is a homomorphism · claim: PROP-14.3 · **FAILS**

A homomorphism out of a free commutative monoid is insensitive to order *and
grouping* of generators. Measured
(`notes/observations/2026-08-09-index-batching.md`):

```
ONE batch,  two identical texts  ->  doc_count = 1
TWO batches, two identical texts ->  doc_count = 2
```

The images differ, so **O-1 fails**: grouping is observable.

**Diagnosis (PROCESS §4.1): implementation divergence.** Within one call the
code deduplicates candidates by content digest; across calls it dispatches on
identifier only, and $\mathrm{c2r}$ — written on every insertion — is never read
for that decision. The module documents cross-corpus content deduplication; what
is realised is batch-local deduplication.

**Consequence.** $df$ depends on grouping, so $\mathrm{idf}$ does, so every score
does. Two runs indexing identical content in different batch sizes rank
differently.

**The repair is a trap.** Making deduplication consult $\mathrm{c2r}$ across
calls — as documented — would make $df$ count *distinct contents* rather than
*documents*, and O-1 would then fail more deeply: no grouping of operations
could recover the abstract value, and $A$ would have to change from an indexed
family of documents to one of contents carrying URL multiplicities. Surfacing
this before the change is made is the document's purpose.

### O-2 — retraction is exact · claim: PROP-14.2 · **discharged**

Discharged at store level by `test_purge_url_clears_both_stores`, and for the
case previously flagged open — removal of a document whose tokens are *shared*
with survivors — by
`test_retraction_is_exact_under_partial_token_overlap`. That test recomputes
$df$ from the matrix after retraction and requires clause 3 to hold token by
token, additionally checking that no count rises and none goes negative. It
passes, so cancellativity is realised on the overlap case and not merely on the
disjoint one.

### O-3 — tokenization is not a homomorphism · claim: PROP-13.2 · holds

A negative result; the implementation agrees. Recorded because §9's image
characterisation depends on it.

---

## 7. Concretization

$\gamma$ is the theory-to-code direction and is what makes the pair
bidirectional rather than a one-way abstraction.

### 7.1 The orders

$A$ is ordered by graph inclusion: $a_1 \sqsubseteq a_2$ iff $a_1$'s graph is
contained in $a_2$'s — "$a_2$ knows at least what $a_1$ knows". $C/{\approx}$ is
ordered by row inclusion. Both are partial orders with least element (empty
index, empty family), and both are finite-height in any bounded corpus.

$\alpha$ is monotone: adding rows adds graph entries.

### 7.2 $\alpha$ is not surjective — the tokenizer constrains the image

PROP-13.3 establishes that a tokenizer emitting $n$-grams alongside unigrams has
a proper image $\mathcal{K} = \mathrm{im}(\theta)$, the **coherent** vectors.
Our $\theta$ satisfies its hypothesis; measured:

```
theta("alpha beta gamma") = [alpha, beta, gamma, alpha beta, beta gamma]
```

asserted directly by `test_tokenizer_emits_unigrams_and_bigrams`, so PROP-13.3's
hypothesis is discharged rather than assumed. Its conclusion instantiates here
as: the family $\{\text{"alpha beta"} \mapsto 1\}$ with no unigrams lies in $A$
but in no $\mathrm{im}(\alpha)$.

Hence $\mathrm{im}(\alpha) = A_{\mathcal{K}}$, the families valued in
$\mathcal{K}$, and every claim about $\alpha$ below is restricted accordingly.
PROP-13.3 leaves the exact characterisation of $\mathcal{K}$ open; that openness
is inherited here (§11) rather than independently ours.

### 7.3 The connection

Define
$$\gamma(a) \;=\; \bigsqcup\ \{\, c \in C/{\approx} \;:\; \alpha(c) \sqsubseteq a \,\},$$
the most complete concrete state whose abstraction is permitted by $a$. Then for
all $c, a$:
$$\alpha(c) \sqsubseteq a \iff c \sqsubseteq \gamma(a),$$
which is a **Galois connection** $\alpha \dashv \gamma$. Because $\alpha$ is
injective (§5) it is a **Galois insertion** on $A_{\mathcal{K}}$:
$\alpha \circ \gamma = \mathrm{id}$ there, so the abstraction loses nothing
except representation detail — sparse encoding and column numbering.

That is a stronger result than expected and worth stating plainly: **for the
index, the abstract domain is not a lossy abstraction but a faithful
re-description**, modulo observational equivalence and restricted to
$A_{\mathcal{K}}$. Every obligation therefore reduces to checking that
operations commute; none can fail merely because the abstraction discarded
something.

### 7.4 What $\gamma$ is for

Three uses, and they are the concrete payoff of the theory-to-code direction:

1. **Generating test inputs.** For an abstract property $P$, $\gamma$ identifies
   the concrete states that must satisfy it — a generator for property-based
   tests rather than a hand-chosen fixture.
2. **Runtime assertions.** $\gamma$ of an abstract invariant is a predicate on
   live state; $\mathrm{RI}$ clause 3 is exactly $\gamma$ applied to "$df$ is
   derived from $\mathcal{D}$" (§5a).
3. **Rejecting designs before implementation.** A proposal whose abstract
   postcondition lies outside $A_{\mathcal{K}}$ is unrealisable, and $\gamma$
   says so without writing code.

---

## 8. The record store, and coherence between interpretations

$\alpha_R$ sends the `instances` relation to an indexed family
$I \rightharpoonup_{\mathrm{fin}} (\text{pattern}, \text{address}, \text{text})$,
keyed by the same identifier set $I$. It is a function by the same argument as
§5, the primary key supplying uniqueness.

**O-4 — upsert is idempotent · holds.** Discharged by
`test_ingest_is_idempotent`.

### 8.1 RI-R1 — `pattern` is a stored redundancy, now policed

`InstanceRecord` stores `pattern` alongside `absolute_xpath`, and pattern is a
function of address (PROP-12.2). By PROP-22.4 this incurs an invariant. Until
this pass **no clause stated it and no test checked it** — by COR-22.5.1 the
illegal states were reachable and unreportable, which is the worst of the three
regimes in COR-22.5.2.

**Falsification attempted before treating it as a redundancy.** Earlier evidence
was 43/43 on a hand-written fixture, which is weak. Re-run over structurally
varied inputs, including a synthetic adversary combining declarative shadow DOM,
sibling cards and doubly-nested wrappers:

| input | instances | divergent |
|---|---:|---:|
| fixture | 43 | 0 |
| Wikipedia article | 610 | 0 |
| a form-heavy page | 93 | 0 |
| shadow-DOM adversary | 12 | 0 |
| **total** | **758** | **0** |

The clause is now `vertiscope/invariants.py::rr1_pattern_derived`, asserted by
`test_record_pattern_is_derived`.

**Elimination is the stronger remedy, and nearly free.** COR-22.5.1 distinguishes
detection from prevention: the check reports a stale pattern, it does not stop
one being written. Only not storing it empties the illegal region. Measured on
the Wikipedia page:

| | |
|---|---|
| `pattern` column | 37,126 bytes — **9.9%** of row payload |
| plus | one dedicated index, `idx_instances_pattern` |
| deriving all 610 | 0.54 ms cold (**0.9 µs/row**), 0.03 ms warm |

**COR-22.5.2 is decisive here.** The generalization map is *known to be
provisional*: PROP-12.4 requires region-anchoring and the implementation is plain
index-stripping (ERRATA E1). Under regime 2 — stored and checked, which is where
this pass leaves it — correcting `generalize_xpath` makes every stored `pattern`
stale, RI-R1 reports all 610, and legality is restored only by a migration. Under
regime 3 — derived — the correction propagates with no state affected and no
migration.

So the case for elimination does not rest on the 9.9%; it rests on the
derivation being provisional. Recorded as analysis; the change touches the
schema and the store API and is not made here.

### 8.2 Identity itself reaches the provisional map

The previous pass flagged `instance_id` as *possibly* dependent on the same map.
It is, and the dependency is transitive:
$$\texttt{instance\_id} = \mathrm{sha1}(\texttt{url} \mid \texttt{pattern} \mid \texttt{content\_hash}),
\qquad \texttt{pattern} = g(\texttt{address}).$$

By DEF-22.5.3 provisionality is closed under *depends-on*, and $g$ is provisional
(PROP-12.4 requires region-anchoring; the implementation strips all indices,
ERRATA E1). So `instance_id` is provisional, and COR-22.5.5 says it is not a
persistent identifier across the correction.

Measured (`notes/observations/2026-08-09-identity-blast-radius.md`) by applying
the §7.8 region-anchored map:

| | wikipedia | fixture |
|---|---:|---:|
| `instance_id` re-keyed | 397 / 610 (65.1%) | 30 / 43 (69.8%) |
| distinct patterns | 157 → 177 | 17 → 35 |

Both columns matter and they point the same way. The rise in distinct patterns is
the correction *working* — it separates the classes PROP-12.4 predicts are
conflated, observed in retrieval as navigation fragments outranking prose. The
re-key figure is what that costs under the present identity scheme.

Note the shape of the dependency: `instance_id` never mentions the generalization
map. It reaches it through `pattern`, and by PROP-22.5.4 is invalidated exactly
as thoroughly as if it had named it directly. The cost of a provisional map is
its closure, not its callers — which is why the previous pass's audit of direct
consumers was the wrong audit.

**The remedy is not obvious.** Dropping `pattern` from the identity input gives
`sha1(url | content_hash)`, which collides for structurally distinct instances
carrying identical content — precisely the sibling-`p` collision that cost 470+
chunks per scan in the production incident recorded in
`notes/reading/02-output-format-and-identity.md`. The naive fix reintroduces the
failure the pattern term was added to prevent. The real question is what
*non-provisional* structural discriminator exists, and it is open.

### 8.3 The search for a fourth identity function was misconceived

§8.2 ended by asking what non-provisional structural discriminator exists.
THM-22.5.7 answers that the search was the wrong activity: **no reshuffle-stable
identity assignment can discriminate content-identical siblings at all**, because
transposing two equal subtrees leaves the tree literally unchanged, so stability
forces equal identifiers. Provisionality never enters the argument.

COR-22.5.8 then relocates the decision: stability and discrimination are jointly
satisfiable **iff** content-identical siblings are observationally
indistinguishable. Our observation alphabet exposes position — retrieval returns
`absolute_xpath` — so they are distinguishable and no candidate has both
properties. The identity question is therefore downstream of a DOMAIN question,
which is where PROCESS §2.1 says such questions reduce.

**Measured** (`notes/observations/2026-08-09-identity-collapse.md`): the case is
live, not hypothetical.

| page | rendered | rows | collapsed |
|---|---:|---:|---:|
| wikipedia | 672 | 610 | 62 (9.2%) |
| census | 105 | 93 | 12 (11.4%) |
| fixture | 43 | 43 | 0 |

**The condition of COR-22.5.8 is now measured, and it fails — narrowly.**
Position is observable through **exactly one surface**, `vertiscope show`
(DOMAIN §9.8.1). Search, `--json` search and `ls` expose identity, pattern,
content and url but not position. So content-identical siblings are
distinguishable, stability and discrimination are incompatible, and the
three-pass search for a better identity function was doomed by a single printed
field.

That narrowness is the actionable part. By COR-10.7 the observation alphabet is
changeable by removing a surface, and removing position from `show` would make
content-identical siblings indistinguishable, at which point content-keying
satisfies both properties and the impasse dissolves. **So the identity
architecture currently hangs on whether `show`'s xpath output is load-bearing or
incidental** — a small, concrete, answerable question standing in for what looked
like a deep design problem.

Recorded, not decided: `show` is the "inspect one instance" command, and an
xpath is plausibly its point. The question belongs to whoever owns that surface.

REM-22.5.9 supplies the only escape that does not change what is observable:
identity and *multiplicity* are different questions, and collapsing is lossless
iff the count is retained. PROP-10.2 already says the extraction is a multiset.
**The store represents it as a set** — there is no multiplicity column — so 9% of
cardinality is discarded rather than recorded.

So the obligation MODEL should have carried, and did not, is that $\alpha$
preserves multiplicity. It does not, and the failure is measurable. This is not
the identity scheme being wrong; it is the *carrier* being a set where the theory
says multiset.

**Why the offline suite never saw it.** The fixture has no duplicate siblings, so
the phenomenon cannot occur on it and every test passes on a page where the
question does not arise. The finding required a real page.

**Test-adequacy note.** `test_instances_have_stable_ids_across_runs` passes
throughout and always would: it holds the map fixed, so it measures determinism.
The invariance at issue is stability across a *change* of map, unobservable in
any fixed-map experiment. The test is not wrong — it measures a different
property from the one its name suggests, and the two are easy to conflate. Its
docstring now says so, and `test_identity_depends_on_the_provisional_map`
asserts the dependency so that decoupling identity from the map is detected
rather than silently invalidating this section.

**O-5 — coherence of the two domains · restated · discharged.**

Stated first as $\mathrm{dom}(\alpha(c)) = \mathrm{dom}(\alpha_R(r))$. **That is
false**, and writing the test is what showed it: `Store.index_instances` skips
instances whose rendered text is empty, on the grounds that an unindexable row
would only dilute $df$. So equality does not hold and was never intended.

The true obligation is containment with a characterised residue:

$$\mathrm{dom}(\alpha(c)) \subseteq \mathrm{dom}(\alpha_R(r)),
\qquad
\mathrm{dom}(\alpha_R(r)) \setminus \mathrm{dom}(\alpha(c)) = \{\, i : \text{text}(i) = \varepsilon \,\}.$$

Containment is the direction that carries observable weight: retrieval yields
identifiers (§5b), so an indexed row with no backing record would return an
identifier that cannot be hydrated. The reverse residue is benign and now
pinned to its cause rather than merely tolerated. Both halves are discharged by
`test_indexed_rows_all_have_records` and
`test_domains_are_not_equal_and_the_gap_is_empty_text`.

This is the first obligation in the draft that neither structure could discharge
alone, and the first whose *statement* was corrected by attempting to discharge
it — which is the argument for mechanising obligations rather than asserting
them.

---

## 9. What the draft establishes about the document's shape

1. **$\alpha$ is a function and is injective**, so obligations are equalities and
   simulation relations are unnecessary.
2. **§4.1's equality must precede §6**, or obligations fail on representation
   detail and real failures are buried.
3. **$\alpha \dashv \gamma$ holds, as a Galois insertion.** The bidirectionality
   asked for is established, not asserted.
4. **The genre earns its keep on the first obligation.** O-1 is a live defect —
   ranking depends on batch size — found by writing a commuting condition, not by
   reading code. Its repair analysis is the load-bearing paragraph, and a
   pass/fail checklist would have missed it.
5. **Concretization corrected the theory three times, and the corrections have
   landed.** $df$ is derived, the corpus must be an indexed family, and the
   image is restricted. All three were raised here, routed to THEORY under
   PROCESS §3, and returned as PROP-14.6, PROP-14.7 and PROP-13.3 — which this
   document now cites rather than argues. The code-to-theory edge is therefore
   demonstrated, not asserted: three results exist in THEORY that would not
   exist had the interpretation not been attempted.

## 10. Discharged mechanically

`tests/test_model_obligations.py`, eight checks, all passing:

| check | discharges |
|---|---|
| `test_ri_shape_and_alignment` | RI clauses 1, 2, 4 |
| `test_ri_df_is_derived_from_the_matrix` | RI clause 3, recomputed not trusted |
| `test_ri_digest_map_points_at_matching_rows` | RI clause 5 |
| `test_retraction_is_exact_under_partial_token_overlap` | O-2, overlap case |
| `test_indexed_rows_all_have_records` | O-5, containment |
| `test_domains_are_not_equal_and_the_gap_is_empty_text` | O-5, residue |
| `test_every_indexed_vector_is_coherent` | §7.2, $\mathrm{im}(\alpha) \subseteq A_{\mathcal{K}}$ |
| `test_tokenizer_emits_unigrams_and_bigrams` | the premise §7.2 rests on |

Two of these changed the document rather than confirming it: O-2's open case
turned out to hold, and O-5's statement turned out to be false.

O-1 is deliberately **not** among them. It fails, and a test asserting a
condition known to fail would be a regression test for a defect, not a
discharge. It stays an open finding routed to the implementation.

## 11. Open

- An exact characterisation of $\mathcal{K}$ (§7.2).
- The **extraction stage is not interpretable yet**: DOMAIN §9.1 records that the
  host and in-page implementations detect different spaces, so there are two
  candidate concrete structures with no agreed observation alphabet between them.
  An interpretation cannot be written against a split domain, and resolving it is
  a precondition rather than a refinement.
- Whether $\gamma$'s three uses in §7.4 are realised anywhere yet; currently
  only use 2 is, via $\mathrm{RI}$.
