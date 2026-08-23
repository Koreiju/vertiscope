# Detection · Evaluation · Enaction

A formalisation of the loop that governs how the system interacts with a page,
and of the trie/markdown/REPL structure it operates over.

---

## §1 The sentence, unpacked

> *"the remainder of the full patricia-trie-to-markdown from html+pdf+json
> with ontologically defined content links to the shadow DOM scanned in
> O(delta) with pagination detection-evaluation-and-enaction"*

Four claims are stacked here. Taken apart:

1. **One structure, three sources.** HTML, PDF and JSON all land in the same
   patricia trie and render as the same markdown. The source is a property of
   a node, not a separate pipeline.
2. **The markdown is a view, not a copy.** Every trie node carries an
   ontologically typed link — the content-detection tag — back to the live
   shadow-DOM element it came from. Rendering is a projection of an addressed
   structure, so anything visible can be acted on.
3. **The trie is maintained under O(delta).** The view is not re-derived; it
   is repaired from mutations.
4. **Interaction is a three-phase loop**, and this is the load-bearing part.

## §2 The loop, formally

For a candidate control `c` observed on page `P`:

```
detect   : c ↦ k          a hypothesis about what c is
expect   : (k, rules(P)) ↦ σ̂     the delta signature k should produce
enact    : c ↦ Δ          perform the action; observe the delta stream
evaluate : (Δ, σ̂) ↦ {confirm, refute}
```

`k` ranges over an affordance kind: `next-page`, `page-n`, `load-more`,
`search-submit`, `filter`, `menu`, `sort`, `expand`.

**The crucial move: enaction *is* the experiment.** Detection alone is a
guess — a `<button>` reading "More" could be pagination, a disclosure widget,
or a footer link. What settles it is what happens to the document when you
press it, and the O(delta) stream already measures exactly that. So the
detector does not need to be clever; it needs to be *falsifiable*.

## §3 Delta signatures

Each affordance kind predicts a characteristic shape in the delta stream.
These are the post-conditions `evaluate` checks:

| kind | predicted signature |
|---|---|
| `load-more` | pure **append**: chunks added, none removed, existing prefix byte-identical, url unchanged |
| `next-page` | **replacement**: substantial removals *and* additions, prefix does not survive, url or query may change |
| `page-n` | replacement, plus the pager's own active-marker moves to *n* |
| `search-submit` | replacement, url gains or changes a query parameter, result count changes |
| `filter` | **partial replacement** confined to one subtree; siblings outside it untouched |
| `menu` / `expand` | **additive within a subtree**, no url change, reversible by re-enacting |
| `sort` | same address set, different order — content fingerprints stable, structure digest changed |
| *refuted* | empty delta, or a signature belonging to a different kind |

The `sort` row is why the dual fingerprint matters: a reorder is precisely the
case where the commutative content hash holds while the positional structure
digest moves, so the pair distinguishes "rearranged" from "replaced" without
comparing text.

## §4 What evaluation buys

- **Detection becomes self-correcting.** A refuted hypothesis is retracted and
  the control is re-labelled from the signature it actually produced. The
  system learns a site's controls by pressing them, not by pattern-matching
  their markup.
- **Rules become per-URL and learnable.** `rules(P)` starts as a generic prior
  and is specialised by outcome: once `example.com/search?p=2` is confirmed as
  `next-page`, the URL shape itself predicts the affordance on that host.
- **Exhaustion is detectable.** `load-more` that yields an empty delta twice
  is exhausted, which is the honest termination condition for infinite scroll
  — not a scroll count.
- **It is provable from the REPL alone.** Every step — hypothesis, prediction,
  action, observed delta, verdict — is an event on the same stream the REPL
  already logs. No external harness can be needed, because the evidence *is*
  the interaction.

## §5 Where it sits

`evaluate` consumes the same delta stream the store consumes. Nothing about
the affordance loop belongs inside the sensor: the sensor reports what
changed, and this loop interprets change as evidence about a hypothesis. That
separation is what lets a new detection heuristic be swapped without touching
the fold, and a new fold variant be swapped without touching detection.

## §6 The navigation surface it implies

- One chunk is viewable **in full** at any time; everything else is the
  patricia trie collapsed with ellipsis truncation.
- Collapsing and expanding are moves on the trie, not a separate outline —
  the same structure the database stores and the same one addresses resolve
  against.
- A search bar sits above the trie and serves both retrieval
  (pagerank × semantic × tf-idf) and live web search — where "search" is
  itself an affordance, detected, evaluated and enacted by §2 on the engine's
  own page.
- A URL typed in the REPL resolves against the database first; only an
  unregistered URL triggers a live scan, bounded by a scroll limit given as a
  command-line integer.
