# Output format, dedup, and chunk identity — notes

Sources: `MORTEGON_INTEGRATION_SCHEME.md` §1.1/§1.6/§7, `HTML_DEDUP_CONTENT_TREE_GOAL.md`
(binding goal, §U golden I/O), `object_model/ChunkPatternSchema.md`,
`DOMAIN_MODEL.md` §1.2.1/§4.5/§8D.20/§O.19/§O.22, and the shipped
`wfh_chunk_engine.js`.

---

## 1. The output is a *deduplicated pure-text tree*, not a flat render

`HTML_DEDUP_CONTENT_TREE_GOAL.md` is marked **binding, build-exactly**, with a
byte-for-byte golden I/O (the archive.org card → 10 exact lines). Six phases:

1. **content-unit extraction** — each node yields TEXT (`node.text`), URL
   (`href/src/srcset/data-src/poster/action/xlink:href`), LABEL
   (`title/aria-label/alt/placeholder/aria-roledescription`). `alt=""` → nothing.
2. **structural collapse** — a node survives iff its subtree yields ≥1 unit; a
   node with no own units and exactly one surviving child is spliced out. All
   wrapper `<div>` chains, custom elements, shadow `<template>`s, `<ul>` vanish.
3. **dedup by token-set subsumption** (chunk-scoped) — see §2.
4. **inline combination** — inline-level siblings under one block parent join
   into one line with a single space.
5. **tree print** — one line per unit, `\t` per surviving level, document order,
   node's own units before children's. No markup, no blank padding, no escaped
   newlines. Round-trips through the slate parse/print.

Built from the **`fields` dict** (`{xpath: value}`), *not* by re-parsing
`html_raw` — the xpath key supplies depth, kind, and document order. That
decision is recorded as live-verified (2026-06-13, real archive.org scan).

**And `rendered_text` for embedding is derived from it** — "so retrieval embeds
clean content, not noisy flatten" (§4.1). Acceptance criterion 7 is explicit:
*"TF-IDF/nomic embed the clean content tree, not the noisy flatten."*

## 2. Dedup is a *subsumption partial order*, not an equivalence relation

The authoritative rule (§2.3):

- normalize each TEXT/LABEL unit to a **token multiset** (lowercase,
  punctuation-folded, whitespace-split);
- `tokens(A) ⊆ tokens(B)` → **drop A**;
- **equality between a TEXT and a LABEL** → prefer the **LABEL's surface form**
  (`450 all-time views`, not `all-time views: 450`);
- TEXT strictly-superset of LABEL → **TEXT wins**;
- **URL units dedupe only against identical URLs** — "URLs are data: kept
  verbatim, never collapsed against TEXT/LABEL".

And the sentence that answers "closer than sklearn" directly:

> the per-node content hash *"is a cheap **pre-filter** for identical-subtree
> dedup, but the token-set subsumption above is the **authoritative rule**
> (it catches the title/aria-label/`title`-attr permutations the hash misses)"*.

So the designed dedup is **hash as pre-filter, subsumption lattice as
semantics**. My THEORY.md §4 L1/L2/L3 lattice was the right shape but I had
L1 (exact hash) as authoritative and near-dup as a *tolerance* relation. The
corpus says: the authoritative relation is a **partial order** (⊆ on token
multisets) with a **surface-form tie-break by provenance kind** (LABEL > TEXT on
equality). That is strictly more informative than either hashing or MinHash,
because it is *directional* — it knows which of two units to keep.

## 3. The schema/instance split — and a 7.0× measured redundancy

`ChunkPatternSchema` is the per-pattern record:

```python
pattern_hash, url_root, generalized_xpath,
accessor_map: dict[field_slug, relative_xpath],   # {title: "h3/text()", link: "a/@href"}
golden_trio: tuple[str, str, str],                 # (title, link, content)
sampled_chunks: list[chunk_id], pagerank: float,
sub_patterns: dict[pattern_hash, ChunkPatternSchema],   # RECURSIVE
domain, accessor_dict, created_at, updated_at
```

Two properties matter for the output structure:

- **`sub_patterns` is recursive** — a card-grid pattern contains a card
  sub-pattern. The output is a tree of schemas, not a flat list.
- **`accessor_dict` is a persistent table keyed `(domain, pattern_hash)`** that
  is *consulted before rediscovery* and short-circuits re-mining across scans
  and across URLs of the same domain. §7 lists "re-running golden-trio
  extraction on every member" as an explicit anti-pattern.

**Measured on the live vertiscope store** (2 pages, Wikipedia + HN):

| | |
|---|---|
| instances | 1,414 |
| distinct patterns | 185 |
| `fields_json` total | 207,392 B |
| — of which xpath **keys** | 30,726 B (14.8%) |
| — keys if stored **per-pattern** | 4,415 B |
| **key redundancy factor** | **7.0×** |
| `html_raw` vs `rendered_text` | 264,491 B vs 120,289 B (**2.2×**) |

vertiscope stores the accessor keys on every instance. The design says they belong
on the schema. 7× on a 2-page corpus, and it grows with instances-per-pattern.

## 4. Chunk identity: three schemes, one production failure

| scheme | identity | consequence |
|---|---|---|
| `REAL_TIME_SCAN_UPDATE` §7.5 | `sha1(url\|pattern\|ordinal)[:16]` | stable across scrolls → enables `chunk_replaced`. **Failed in production.** |
| shipped `wfh_chunk_engine.js` | `djb2(url\|absoluteXpath)` | instance-unique by *position*; sibling reshuffle re-keys |
| vertiscope (`chunk_render.instance_id`) | `sha1(url\|pattern\|content_hash)` | instance-unique by *content*; content edit mints a new id → cannot express `replaced` |

The JS carries the war story in a comment:

> *"Originally hashed on pattern alone, which collided whenever a card had
> sibling `<p>` elements: both shared the same generalized pattern, the second
> emit clobbered the first via chunk_replaced, and **we lost 470+ chunks of
> content per scan**. Pattern is now metadata for grouping/commutation;
> identity is the xpath."*

So the spec's identity function was tried and lost data. None of the three is
right on its own: position-keyed fragments under reshuffle, content-keyed
cannot express replacement, pattern-keyed collides. The resolution is that
**identity and address are different fields** — see the revised THEORY.md §3.

## 5. Region anchoring — spec vs shipped

- Spec §7.8: **landmark anchoring** — prefix the pattern with the absolute
  xpath of the nearest `<main>/<nav>/<header>/<footer>/<aside>/<article>` (or
  `role` in a landmark set, or `<section>` with an accessible name). Explicitly
  chosen *over* a fixed `PATTERN_ANCHOR_DEPTH` because deep React trees hit
  generic wrapper divs at fixed depths.
- Shipped JS: **deepest-`ANCHOR_TAGS` anchoring** — keep segments at and above
  the deepest anchor tag verbatim (with indices), strip indices below.
- **vertiscope: neither.** `xpath_utils.generalize_xpath` strips *all* indices.

Consequence, and it matches what I saw in live retrieval: on Wikipedia the nav
`<ul>` and the citation `<ol>` collapse toward the same pattern family, and nav
fragments rank highly. This is the §7.8 collision, unmitigated.

## 6. Retrieval formula from the corpus (§O.22)

For **panels**: `pagerank · max(minmax(nomic_cos), minmax(tfidf_cos))` — each
cosine **min-max normalized over its own space before the max**, because "raw
cosine spaces at their independent scales can be biased". For **scan chunks**
the two axes stay separated (nomic over description, TF-IDF over rendering).

This is a different combiner from my THEORY.md §4 BM25 proposal. They are not in
conflict — BM25 is a *within-axis* scoring fix (length normalization), §O.22 is
a *cross-axis* combination rule. Both are needed; note it so the next iteration
doesn't treat them as alternatives.

## 7. Type detection: regex for primitives, named tree patterns for structures

§1.2.1 / DOMAIN_MODEL:1650 — the workspace tracks content patterns per
materialised type via **regex patterns for primitive types** (URL, date,
currency, email, hash, xpath) and **named tree patterns for structured types**,
where *"a chunk-pattern schema is itself a named tree pattern"*. Embedded-content
extraction (`ld+json`, `data-*` that parse as JSON) is the structured arm of the
same mechanism.

So "regex searches through embedded fields for URLs and JSON only" is not an ad
hoc filter — it is the primitive-type arm of a two-arm type detector, and the
named-tree arm is the pattern schema itself.

---

## Mistake to own

I deleted `content_tree.py` from `vertiscope/core` on the evidence of a runtime
reachability trace. It was unreachable because **the pipeline never wired it**,
not because it was dead. Per the binding goal, `rendered_text` — the thing we
actually index — is supposed to be *derived from* the content tree. Deleting it
removed the intended fix for exactly the retrieval noise I then reported as a
"known limitation" (citation junk, dropped href/src, nav fragments outranking
prose).

**Lesson: reachability ≠ intent.** A reachability trace prunes what the code
does; it cannot see what the design says the code *should* do. Any future
deletion pass has to be checked against the design corpus, not just the trace.

`content_tree.py` should be restored and wired.
