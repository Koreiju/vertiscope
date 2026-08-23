# Method

*A standardization of the modes of reasoning used when an algorithmic
mathematician attacks a problem, written so that they can be invoked by name,
checked, and audited.*

This document is about **how to think**, not about what is true. It exists so
that a derivation elsewhere in this workspace can cite a move — "by §A.3, ask
what carrier this lives in" — and so that a reviewer can ask which move was
skipped. It is prescriptive about *process*, never about *conclusions*.

Three parts. **Part A** lists the *stances*: the standing questions, each with
its trigger, its move, what it yields, and how it fails. **Part B** gives
*schemas*: reusable derivation templates that chain stances into a complete
argument for a recurring class of question. **Part C** lists *failure modes*,
each stated as a specific false inference, because most errors in this field are
one of a small number of recognisable mistakes.

---

# Part A — Stances

Each stance is a question that can be asked of any problem, in roughly this
order. They are not steps: several may apply at once, and a stance that yields
nothing is still worth recording as having been tried.

## A.1 Name the datum

**Trigger.** Any new problem. **Move.** Identify the smallest object the problem
actually manipulates, before any structure is attributed to it. **Yields.** A
carrier set. **Fails when** the "datum" is really a composite and the problem
splits along its components; the symptom is a definition with an "and" in it that
is never used jointly.

The discipline is to resist naming the structure first. A datum is a member of a
set; everything else is a claim requiring justification.

## A.2 Ask what operations the datum genuinely supports

**Trigger.** After A.1. **Move.** For each candidate operation, check closure,
associativity, identity, commutativity, idempotence, inverses, cancellativity.
**Yields.** The weakest algebraic classification that is true: magma, semigroup,
monoid, commutative monoid, group; poset, lattice; vector space.

**The minimal-structure principle.** Attribute the *least* structure that
supports the argument. Every additional assumed property is a hypothesis that can
be false, and assuming a group where only a monoid holds is the single most
common source of an incorrect incremental algorithm.

**Fails when** a carrier supports two different operations and they are conflated
— see C.2.

## A.3 Ask whether the object is free

**Trigger.** The carrier is built from a generating set. **Move.** Ask whether it
is the free object on those generators. **Yields.** A universal property: maps out
of the object are determined by their values on generators. **Why it matters.**
Freeness converts "define a function on all of $X$" into "define a function on
generators", which is usually the whole difficulty. Sequences over an alphabet,
multisets over a token set, and terms over a signature are all free, and this is
the most reusable single observation in the subject.

## A.4 Ask whether a map preserves structure

**Trigger.** Any function between two carriers. **Move.** Check the homomorphism
equations. **Yields.** If yes: composition, factorisation, and the ability to move
results across the map. If no: identify exactly which equation fails, because that
failure is usually the phenomenon of interest.

**A useful reflex:** a map that *fails* to be a homomorphism is not a defect to be
repaired — it is a measurement of what the target forgets.

## A.5 Separate order from equivalence

**Trigger.** Any notion of "same" or "better". **Move.** Ask whether the relation
is symmetric. If it is, it can express only sameness; if it is a preorder, it can
also express direction, and the two capabilities should be tracked separately.
**Yields.** Clarity about whether a construction can *choose* between two related
objects. **Fails when** an equivalence is used where a choice is required; the
symptom is an arbitrary tie-break appearing in an implementation with no
justification in the theory.

## A.6 Quotient, then choose a representative

**Trigger.** A preorder, or any collapsing operation. **Move.** Factor the work
into three independent pieces: the order that ranks, the equivalence that
collapses, and the selection rule that picks within a class. **Yields.** Three
separable design surfaces, and an explicit place to put data that belongs to none
of the others. **Fails when** the three are fused, at which point changing the
tie-break requires changing the order.

## A.7 Ask what a value depends on

**Trigger.** Any computed quantity. **Move.** Determine the dependency set — the
part of the input whose change can change the value. **Yields.** Locality claims,
and with them incrementality. **Discipline.** State the dependency set as a
*theorem*, not an intuition; the proof is normally an induction over the
structure, and quantities defined on a quotient usually have a dependency set far
larger than they appear to.

## A.8 Ask what is invariant

**Trigger.** Any transformation or pipeline stage. **Move.** Name a quantity
preserved by the stage, and separately name a quantity destroyed. **Yields.**
Correctness conditions and a checklist for tests. **Note.** The destroyed quantity
is as informative as the preserved one, and is more often forgotten.

## A.9 Look for the dual

**Trigger.** Any statement about maxima, down-sets, sources, forward maps.
**Move.** State the dual and ask whether it is also true or also needed: minima,
up-sets, sinks, inverse maps; antichains against ideals; refinement against
coarsening. **Yields.** Either a second result for free, or the discovery that the
problem is asymmetric — which is itself a finding.

## A.10 Differentiate

**Trigger.** The input changes over time. **Move.** Ask for the derivative: given
the old output and a description of the change, what is the change to the output?
**Yields.** An incremental algorithm, and a correctness equation
(new $=$ old $\oplus$ derivative) that is checkable independently of efficiency.
**Discipline.** Correctness and cheapness are separate obligations; a derivative
that is correct but costs a full recomputation is still a derivative.

## A.11 Choose the cost parameter deliberately

**Trigger.** Any complexity claim. **Move.** Say which parameter the bound is in —
input size, output size, change size, depth, number of distinct classes — and
justify why that is the parameter of interest. **Yields.** Comparable claims.
**Fails when** stages are bounded in different parameters and the results are
composed as if commensurable.

## A.12 Find the dominant term before optimising

**Trigger.** Any performance question. **Move.** Enumerate every cost term
including those outside the algorithm — serialisation, transport, allocation —
and measure before ranking. **Yields.** A ranked cost model. **Fails when** the
model counts only the operations the author finds interesting.

## A.13 Reduce to a known problem

**Trigger.** A problem resembling a classical one. **Move.** Try to exhibit an
explicit reduction, and state what it costs. **Yields.** Inherited algorithms and
inherited lower bounds. **Discipline.** A reduction that is only an analogy should
be labelled as an analogy.

## A.14 Ask what is impossible

**Trigger.** A proposed capability. **Move.** Attempt a lower bound or an
impossibility argument before attempting a construction — a distinguishing-pair
argument, a counting argument, an adversary argument, or a structural obstruction
such as non-cancellativity. **Yields.** Either a proof that no design can succeed
— which saves the whole effort — or sharpened intuition about what a design must
do. **Note.** This stance is the most frequently skipped and the most valuable
when it fires.

## A.15 Specialise, then generalise

**Trigger.** Stuck. **Move.** Solve the smallest nontrivial instance completely —
one node, one token, one edit — then look for the general shape. **Yields.** The
statement to prove. **Discipline.** Record which features of the special case were
used, because those are the hypotheses of the general theorem.

## A.16 Enumerate the space before reasoning over it

**Trigger.** Any claim quantified over a domain ("every content type", "all
attributes"). **Move.** Produce the finite enumeration, from the source of truth,
and verify it mechanically. **Yields.** The right to quantify. **Fails when** the
enumeration is paraphrased rather than extracted, so that drift is invisible.

## A.17 Metrise by embedding

**Trigger.** A need to compare two objects quantitatively. **Move.** Find an
injection into a carrier already possessing a metric — usually finite sets — and
pull the metric back. **Yields.** A genuine metric with its axioms proved rather
than assumed. **Fails when** the map is not injective, giving a pseudometric that
silently identifies distinct objects.

## A.18 Distinguish the contract from the mechanism

**Trigger.** Designing anything with an interface. **Move.** State what is emitted
and what is guaranteed, separately from how it is produced, and check that the
contract survives replacing the mechanism. **Yields.** Freedom to change the
algorithm. **Fails when** contract statements mention algorithmic details, which
is detectable by trying to rewrite them without naming any procedure.

---

# Part B — Schemas

Chains of stances that answer a recurring question completely. Each is a template
to be instantiated, and each ends with a definite obligation.

## B.1 Is this computable by one bottom-up pass?

1. (A.1) Name the structure being traversed.
2. (A.3) Confirm it is an initial algebra — freely generated by its constructors.
3. (A.2) Exhibit the target carrier and its operation; confirm associativity and
   identity.
4. (A.4) Check the per-node combination is well defined from the label and the
   children's values *only*.
5. Conclude: the quantity is a catamorphism; uniqueness and the single-pass bound
   follow from initiality.

**Obligation.** Step 4 is the whole content. If the combination consults
anything outside the subtree, the schema does not apply and A.7 must be run
instead.

## B.2 Can this aggregate support deletion?

1. (A.2) Classify the aggregate's operation.
2. Check cancellativity on the carrier.
3. If cancellative, the group completion exists and embeds; deletion is exact.
4. If not, deletion from the aggregate alone is impossible; either retain the
   generators or change the statistic.

**Obligation.** State the classification for the *composite*, not per stage; the
property is not preserved by composition (A.4).

## B.3 Can this be computed in one streaming pass?

1. (A.1, A.3) Identify the input as words over an alphabet.
2. Ask whether the output for a prefix is determined by that prefix.
3. If a later symbol can change it, exhibit two continuations distinguishing the
   required outputs — this refutes sequentiality (A.14).
4. Ask whether the *reverse* is sequential; if so the function is rational and a
   two-pass or reversed implementation exists.

**Obligation.** Distinguish "finite-state" from "single forward pass"; they are
different claims and only the second constrains an implementation's shape.

## B.4 Is this family of objects non-nested, and what follows?

1. (A.1) Confirm the ambient order and that it is a forest order.
2. Check pairwise incomparability — the family is an antichain.
3. (A.9) Pass to the ideal representation; antichains and down-sets correspond.
4. (A.17) Pull back a set metric along that injection.

**Obligation.** Verify the correspondence's hypotheses (finiteness) before using
it.

## B.5 How should two structured objects be compared?

1. Decide what a difference *means*: omission, commission, or regrouping.
2. Separate coverage from structure; do not average them (A.8).
3. For coverage, use set-based indices; for grouping, use a partition metric; for
   nesting, embed first (A.17).
4. State for each number what value indicates success and what failure it
   diagnoses.

**Obligation.** Any statistic reported must have a named failure it detects. A
number nobody can act on is not a measurement.

## B.6 What does this rendering lose?

1. (A.4) Ask whether the rendering map is injective.
2. If not, characterise the fibres — the sets of inputs collapsed together.
3. (A.6) Decide whether downstream needs the fibre or a representative, and
   record that a representative is independent data.
4. (A.8) Name the invariant that survives the rendering and the one that does
   not.

**Obligation.** "Lossless" is a claim about a *sublanguage* of inputs; state it.

## B.7 Establishing a claim over a whole domain

1. (A.16) Extract the enumeration mechanically from the source of truth.
2. Verify it two ways — structurally and empirically — and reconcile.
3. Record the elements never observed, distinguishing "absent from the sample"
   from "no detector exists".
4. Provide a regenerator so drift is a test failure rather than a reading error.

**Obligation.** A domain claim without a regenerator decays silently.

---

# Part C — Failure modes

Each is a specific false inference. They are listed because recognising the shape
is faster than rediscovering the error.

**C.1 Structure inflation.** Assuming more structure than the datum carries — a
group where there is a monoid, a metric where there is a similarity, an order
where there is an equivalence. *Detection:* try to state the axiom that fails and
find the counterexample; if you cannot construct one quickly, you may be right.

**C.2 Operation conflation.** A carrier bearing two natural operations, used
interchangeably — multiset sum against multiset union, tree depth against
subtree size, concatenation against merge. *Detection:* check whether the two
agree on a two-element example.

**C.3 Symmetric tool, asymmetric job.** Using an equivalence — typically a hash —
where a choice between related objects is required. Guaranteed to surface later
as an unmotivated tie-break. (A.5.)

**C.4 Stagewise-to-composite.** Proving a property of each stage and asserting it
of the pipeline. Fails for every property not closed under composition, including
retractability, injectivity, and locality of dependence.

**C.5 Optimising a non-dominant term.** Improving a cost that measurement would
have shown to be negligible. Prevented only by A.12, and only if measurement
precedes ranking.

**C.6 Parameter substitution.** Proving a bound in one parameter and reporting it
in another — linear in the change, reported as linear overall, when an earlier
stage is linear in the input. (A.11.)

**C.7 Reachability mistaken for intent.** Concluding from "nothing calls this"
that "this is not needed". Execution traces observe what the code does, never
what it was specified to do. *Detection:* check the artifact against the
specification, not only against the call graph.

**C.8 Metric-shaped non-metrics.** Treating precision, recall, similarity scores
or chance-corrected indices as distances — averaging them, or assuming a triangle
inequality. *Detection:* verify the axioms; most such quantities fail at least
one.

**C.9 Enumeration by paraphrase.** Restating a domain in prose instead of
extracting it, so that the document and the artefact drift apart with no signal.
(A.16, B.7.)

**C.10 Proof by notation.** Introducing symbols that make a claim look derived
when no derivation occurred. *Detection:* delete the notation and check whether
an argument remains.

**C.11 Hypothesis amnesia.** Using a theorem whose hypotheses were checked in a
special case and never rechecked in the general one. (A.15's discipline exists to
prevent exactly this.)

**C.12 Premature construction.** Building before asking A.14 whether the thing is
possible, or before B.7 has fixed the domain being quantified over.

---

# Part D — Hygiene

Standing rules for anything written in this workspace.

1. **Mark provenance.** Every result is *standard* (cited), *proved here*, or
   *assumed*. No fourth category.
2. **State hypotheses at the point of use**, not only at the point of proof.
3. **Name the cost parameter** in every complexity claim.
4. **Separate contract from mechanism** into different documents (A.18).
5. **Keep corrections out of technical documents.** Errata belong in their own
   file; a paper states what is true.
6. **Make domain claims regenerable.** A script, not a paragraph (B.7).
7. **Record what was not done** — unread sources, unrun experiments, unchecked
   hypotheses — in the document that depends on them.
8. **Distinguish measured from argued.** A number without a stated method of
   measurement is an estimate and must say so.
