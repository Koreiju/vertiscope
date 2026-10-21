> **STATE: RETIRED** (PROCESS §6) — drafted 2026-08-09, retired 2026-08-14.
> Erratum: ERRATA A18/A19, which refutes its §10.1 premise.
>
> Most of this was built, but not from this document — the implementation went
> through `docs/THEORY.md` §10–§12 instead, which is why the built form differs
> in the places noted below. Kept because its measurements are reproducible and
> because the divergences are the interesting part.
>
> **Built, as proposed**
> - §2.1 landmark-anchored generalization → `address.anchored_pattern`
> - §4.1 token-multiset subsumption over a hash pre-filter → `markdown._dedupe`
> - §5's hash-diff transport ("the single largest unrealized performance
>   lever") → `core/js/deep_serialize.js`, measured at 88% of bytes saved
> - §6 shadow boundaries as ordinary address letters → THEORY Def. 11.4
>
> **Built differently**
> - §3.3 proposed splitting identity into `content_id` + `address` +
>   `generation`. What shipped keeps only the address, because THEORY
>   Prop. 10.2.1 makes it a key outright: `content_id` would be a second
>   identity for the same thing, and Cor. 22.5.11 says the content-derived one
>   degenerates exactly where content is absent.
> - §1's schema/instance split (keys on the schema, positional values on the
>   instance) is **not** built. The 7.0x redundancy it measures is real; the
>   trie addresses it differently, by sharing path prefixes structurally rather
>   than by normalizing into two tables. Whether that recovers the same factor
>   is unmeasured.
> - §3.1's positional values are not built, for the same reason.
>
> **Refuted by the implementation**
> - §10.1's premise that `(xpath, category, subcategory, source_attr)` keys a
>   detection. It does not — see THEORY Def. 10.1.1 and ERRATA A18/A19.

# The output data structure

Deliberately separated from `THEORY.md`. That document is about *how* the
pipeline computes (folds, O(Δ), incremental maintenance). This one is about
*what it emits*, and it is written so that it stands even if every algorithmic
choice in `THEORY.md` is replaced.

The distinction matters because the output is the contract with everything
downstream — retrieval, storage, rendering, re-scan diffing — while the
algorithm is an implementation detail we intend to keep changing.

Grounded in: `HTML_DEDUP_CONTENT_TREE_GOAL.md` (binding, byte-exact golden
I/O), `object_model/ChunkPatternSchema.md`, `REAL_TIME_SCAN_UPDATE.md` §4.6/§7.5,
`DOMAIN_MODEL.md` §1.2.1/§8D.20/§O.19. Divergences from those are marked
**[new]** and argued.

---

## 1. Three layers, three lifetimes

The single biggest structural claim: a scraped page is **not** a list of chunks.
It is three co-existing layers with genuinely different lifetimes, and
flattening them is what produces both the memory blowup and the identity
confusion.

| layer | keyed by | lifetime | cardinality |
|---|---|---|---|
| **Schema** — what a repeating structure *is* | `(domain, pattern_hash)` | across scans, across URLs, across sites of the same family | one per pattern |
| **Instance** — one occurrence's *values* | `(url, pattern_hash, occurrence)` | one scan generation | many per schema |
| **Unit** — one deduplicated content atom | position in the printed tree | derived, recomputable | many per instance |

Measured on the live vertiscope store (2 pages: Wikipedia + Hacker News):
1,414 instances over **185** distinct patterns — 7.6 instances per pattern. The
accessor keys (xpaths) are properties of the *schema*, yet vertiscope stores them on
every *instance*: 30,726 bytes of keys where 4,415 would do. **7.0× redundancy**,
and the factor grows linearly with instances-per-pattern, so it is worst exactly
on the pages that matter (large result grids).

This is the memory-efficiency answer, and it is structural rather than a
compression trick: **xpath keys are schema-level, values are instance-level.**

---

## 2. Schema

```python
@dataclass(frozen=True)
class PatternSchema:
    pattern_hash:      str        # sha1 of anchored_xpath, 16 hex
    anchored_xpath:    str        # region-anchored generalized xpath (§2.1)
    domain:            str
    url_root:          str        # URL of FIRST discovery; later URLs extend, never respawn

    accessor_map:      dict[str, str]      # field_slug -> relative xpath ("title" -> "h3/text()")
    kind_map:          dict[str, Kind]     # field_slug -> TEXT | URL | LABEL | JSON
    golden_trio:       tuple[str, str, str] | None    # (title, link, content) slugs

    sub_patterns:      dict[str, "PatternSchema"]     # RECURSIVE: grid -> card -> ...

    first_seen:        str
    last_seen:         str
```

### 2.1 `anchored_xpath` — the generalization must be region-anchored

vertiscope currently strips **all** indices (`xpath_utils.generalize_xpath`). That is
wrong and it is observable: on Wikipedia the nav `<ul>`, the citation `<ol>` and
the body list collapse toward one pattern family, which is why nav fragments
outrank prose in the retrieval I measured.

Two anchoring schemes exist in the corpus:

- **landmark anchoring** (`REAL_TIME_SCAN_UPDATE` §7.8) — prefix with the
  absolute xpath of the nearest `<main>/<nav>/<header>/<footer>/<aside>/<article>`
  ancestor (or `role ∈ {navigation, main, banner, contentinfo, complementary,
  region, search}`, or `<section>` with an accessible name). Chosen explicitly
  *over* a fixed depth because deep React trees hit generic wrapper `div`s at
  any fixed depth.
- **deepest-anchor-tag** (shipped `wfh_chunk_engine.js`) — keep segments at and
  above the deepest anchor tag verbatim *with indices*, strip indices below.

Both give the same essential property: **a pattern key is scoped to a semantic
region**. Adopt landmark anchoring; it degrades gracefully to `/html` and does
not depend on tag choice at a fixed depth.

```
/html/body/div[3]/nav[1]/ul[2]/li[7]/a[1]
  landmark = /html/body/div[3]/nav[1]
  anchored = /html/body/div[3]/nav[1]/ul/li/a      # nav links
/html/body/div[3]/main[1]/div[2]/ul[1]/li[4]/a[1]
  anchored = /html/body/div[3]/main[1]/div/ul/li/a  # body links — DISTINCT
```

### 2.2 The accessor map is the reusable asset

`accessor_map` is what makes a second scan cheap: consult
`(domain, pattern_hash)` before rediscovering. `ChunkPatternSchema.md` §7 lists
"re-running golden-trio extraction on every member" as an anti-pattern; the
trio is extracted on the first batch and later members are *tested against* it.

This is the "scan-mapping generalizability" property: the schema is what
transfers across URLs of a domain and across structurally-similar sites, and it
transfers because it is keyed on structure, not on content.

### 2.3 `sub_patterns` makes the output a tree of schemas

A card grid's schema contains the card's schema. Recursion terminates when a
pattern has no repeating sub-structure. This is the sense in which "the output
is informed by recursive structures themselves" — the *schema* layer is the
recursive one; instances are flat leaves hanging off it.

---

## 3. Instance

```python
@dataclass
class Instance:
    # --- identity (§3.3) ---
    content_id:   str          # sha1(pattern_hash | canonical_values)[:20]  — WHAT
    address:      str          # absolute xpath                              — WHERE
    generation:   int          # scan generation                             — WHEN

    # --- linkage ---
    pattern_hash: str          # -> PatternSchema. keys are NOT repeated here
    url:          str

    # --- payload ---
    values:       tuple[str, ...]     # positional, aligned to schema.accessor_map order
    content_tree: str                 # the printed dedup tree (§4) — the indexed text
    subtree_hash: int                 # 32-bit rolling hash, for delta detection

    # --- optional, lazily materialized ---
    html_raw:     str | None = None   # 2.2x the size of content_tree; see §5
```

### 3.1 Values are positional, not a dict

`values` aligns to the schema's `accessor_map` ordering. This is the concrete
form of the schema/instance split: the instance carries no keys at all. Rendering
`{slug: value}` is a join against the schema, done at read time.

### 3.2 `content_tree` is the indexed text

Not `html_raw`, and not the markdown-lite flatten. See §4.

### 3.3 Identity, address and revision are three fields **[new]**

The corpus has three mutually incompatible identity functions, and one of them
is recorded as having lost data in production:

| scheme | key | failure |
|---|---|---|
| `REAL_TIME_SCAN_UPDATE` §7.5 | `sha1(url\|pattern\|ordinal)` | sibling `<p>`s shared a pattern; second emit clobbered the first via `chunk_replaced`; **"we lost 470+ chunks of content per scan"** (comment in the shipped JS) |
| shipped JS | `djb2(url\|absoluteXpath)` | position-keyed: a prepended sibling re-keys every following instance |
| vertiscope | `sha1(url\|pattern\|content_hash)` | content-keyed: any edit mints a new id, so `replaced` is inexpressible |

They fail differently because they are each trying to be three things at once.
Separate them:

- **`content_id` — identity.** Content-keyed, so equal content is one row
  everywhere. This is what dedup and the index key on. Stable under sibling
  reshuffle, which is the common case on feeds and grids.
- **`address` — location.** The absolute xpath. Changes freely; never an
  identity. This is what "go to source" and re-extraction use.
- **`generation` — revision.** A scan counter. `replaced` becomes expressible
  without overloading identity: *same `(pattern_hash, address)`, different
  `content_id`, higher `generation`* **is** a replacement. No collision risk,
  because uniqueness comes from `content_id` and the replacement relation comes
  from the address.

This costs one integer per instance and dissolves the entire failure mode.

---

## 4. Unit — the deduplicated content tree

The binding spec (`HTML_DEDUP_CONTENT_TREE_GOAL.md`, byte-exact golden I/O).
Built from the `{xpath: value}` `fields` dict, **not** by re-parsing HTML: the
xpath key already carries depth, kind and document order.

Five phases:

1. **Extract units.** Each node yields zero or more units, kind-tagged:
   `TEXT` (`node.text`, whitespace-collapsed), `URL`
   (`href, src, srcset, data-src, poster, action, xlink:href`), `LABEL`
   (`title, aria-label, alt, placeholder, aria-roledescription`; `alt=""` → nothing),
   `JSON` (`<script type="application/ld+json">`, and any `data-*` that parses).
   Structural attributes (`id, class, style, aria-posinset, aria-setsize,
   data-cell-index, ...`) are never units.
2. **Collapse.** A node survives iff its subtree yields ≥1 unit. A node with no
   own units and exactly one surviving child is spliced out. Wrapper chains,
   custom elements, shadow `<template>`s and `<ul>` scaffolding vanish.
3. **Deduplicate — a subsumption partial order, not an equivalence.** §4.1.
4. **Inline-join.** Inline-level siblings under one block parent join into one
   line with a single space.
5. **Print.** One line per unit, one `\t` per surviving level, document order,
   a node's own units before its children's. No markup, no blank padding, no
   escaped newlines.

### 4.1 Dedup semantics — why this beats hashing

Normalize each TEXT/LABEL unit to a **token multiset** (lowercase,
punctuation-folded, whitespace-split). Then:

```
tokens(A) ⊆ tokens(B)                    ⟹  drop A
tokens(TEXT) == tokens(LABEL)            ⟹  keep LABEL's surface form
tokens(TEXT) ⊋ tokens(LABEL)             ⟹  keep TEXT
URL units                                ⟹  dedupe only on exact equality
```

Two things make this stronger than any hash-based scheme:

- **It is a partial order, so it is directional.** Hashing tells you two things
  are equal; subsumption tells you *which one to keep*. `450 all-time views`
  (the curated `title` attribute) beats `all-time views: 450` (the DOM text)
  because on token-equality the LABEL's surface form is the better rendering.
  No hash can express that preference.
- **URLs are data.** They never collapse against prose, only against identical
  URLs. A hash over normalized text would happily merge a link with its label.

The corpus is explicit that the per-node content hash *"is a cheap **pre-filter**
for identical-subtree dedup, but the token-set subsumption above is the
**authoritative rule** (it catches the title/aria-label/`title`-attr
permutations the hash misses)."*

So the layering is: **hash to find candidates in O(1); subsumption to decide.**
That is the answer to "closer than sklearn" — sklearn has no notion of either,
and MinHash/SimHash give you only the candidate half.

### 4.2 Scope

Dedup is **chunk-scoped** (within one instance). Cross-instance boilerplate
removal is a *different* mechanism operating upstream. Keeping them separate
prevents double-dedup and content loss.

---

## 5. Memory

Rules, with the measurement that motivates each.

1. **Keys live on the schema.** 7.0× measured redundancy; the factor is
   instances-per-pattern, so it worsens on exactly the large grids we care about.
2. **`html_raw` is not stored by default.** Measured at **2.2×** the size of the
   text we actually index (264KB vs 120KB on two pages), and nothing in
   retrieval reads it. Keep it addressable — re-derivable from the archived page,
   or opt-in per scan — but it is not part of the default record. The corpus
   agrees: raw HTML is reachable only by internalizing a `{raw html}` reference.
3. **Values truncate at extraction, full text stays in the tree.** The JS walk
   clips field values to 80 chars for *fingerprinting*; the printed tree keeps
   full values. Fingerprint and payload have different budgets on purpose.
4. **`subtree_hash` is 32 bits.** It exists for change detection, not identity —
   collisions cost a redundant re-chunk, not a wrong answer. Do not widen it.
5. **Interning.** Pattern hashes, field slugs and domains are small closed sets;
   intern them. Values are not.
6. **Per-snapshot indexes are per-snapshot.** `REAL_TIME_SCAN_UPDATE` §6.2 is
   explicit that every index is cleared at navigation. Nothing survives a scan
   except schemas (which are the point) and instances (which are the product).

The wire format has a separate rule: **hash-diff transport**. The in-page walk
receives `prevHashes` (`xpath → hash`) and emits only changed nodes —
specified as **~10 MB → a few KB** on subsequent scrolls. It is *specified and
never implemented*: the shipped `wfh_chunk_engine.js` has no `prevHashes`, and
`scanner.py` declares `self._prev_hashes` and never reads it (one reference in
the file — the declaration). This is the single largest unrealized performance
lever in the system.

---

## 6. Shadow DOM and embedded content

**Shadow DOM.** Open shadow roots are ordinary subtrees under a boundary
segment: `/host-xpath/#shadow-root/child-tag[N]`. Their text and budgets merge
upward into the host. One rule matters and is easy to get wrong: when the
upward walk hits a `#shadow-root` segment as a parent, **skip it transparently**
and use the shadow *host* as the effective ancestor — otherwise the literal
segment makes every pattern look unique (commutation count 1) and the walk stops
early. A representative xpath may then sit outside the shadow root; that is
valid, because the shadow subtree is already in the member set. Closed shadow
roots are unreachable from script, by definition, and are out of scope.

**Embedded content — URLs and JSON only.** These are the *primitive* and
*structured* arms of one type detector (`DOMAIN_MODEL` §1.2.1: "regex patterns
for primitive types, named tree patterns for structured types").

- **URLs**: a URL regex over **all** attribute values — not an allowlist — minus
  an explicit skip set (`style, class, id, width, height, viewbox, d, points,
  fill, stroke`), plus the always-URL attributes. `data:` / `blob:` classify as
  resource. Being attribute-agnostic is what survives `data-testid`-style sites.
- **JSON**: `<script type="application/ld+json">`, plus **any `data-*` attribute
  that parses as valid JSON**. Parsed JSON enters as a `JSON` unit whose subtree
  is *already* a named tree pattern — so it decomposes through the same
  recursive descent as everything else, rather than needing a JSON special case.

The symmetry is the point: a `PatternSchema` **is** a named tree pattern, and so
is a parsed `ld+json` blob. Both are structures discovered over the page; only
the discovery method differs (structural mining vs. a parser).

---

## 7. Serialized form

```jsonc
{ "schemas": {                                  // written once, reused across scans
    "a91f3c...": { "anchored_xpath": "/html/body/main[1]/section/article",
                   "domain": "archive.org",
                   "accessor_map": { "title": "h3/text()", "link": "a/@href",
                                     "img": "img/@src", "stats": "li/@title" },
                   "kind_map":     { "title": "TEXT", "link": "URL",
                                     "img": "URL",   "stats": "LABEL" },
                   "golden_trio":  ["title", "link", "content"],
                   "sub_patterns": { "b40e91...": { } } } },

  "instances": [                                // no keys — positional values
    { "content_id": "3f9a...", "address": "/html/body/main[1]/section/article[2]",
      "generation": 7, "pattern_hash": "a91f3c...",
      "url": "https://archive.org/search?query=university+library",
      "values": ["Princeton University Library ...",
                 "/details/princetonuniver01librgoog",
                 "https://archive.org/services/img/princeton...",
                 "450 all-time views"],
      "content_tree": "/details/princetonuniver01librgoog\nhttps://archive.org/...\nPrinceton University Library : American Library Association visit, June 29, 1916\nby Princeton University Library\n\tItem Stats\n\tMediatype: Text\n\t450 all-time views",
      "subtree_hash": 2743891204 } ] }
```

`content_tree` is the retrieval surface. `values` + `accessor_map` is the
structured surface. `address` + `generation` is the delta surface. Nothing is
duplicated between them.

---

## 8. What this changes in vertiscope

| current | target | evidence |
|---|---|---|
| `generalize_xpath` strips all indices | landmark-anchored | nav/citation collision, observed in live retrieval |
| `fields_json` per instance | `accessor_map` per schema, positional values | 7.0× measured |
| `html_raw` stored always | opt-in / re-derivable | 2.2× measured |
| `rendered_text` = markdown-lite flatten | `content_tree` (dedup tree) | binding goal §4.1 + acceptance criterion 7 |
| `instance_id = sha1(url\|pattern\|content_hash)` | `content_id` + `address` + `generation` | three failure modes, §3.3 |
| no schema layer at all | `PatternSchema`, persisted by `(domain, pattern_hash)` | `ChunkPatternSchema.md` |
| no `prevHashes` | hash-diff transport | ~10MB → KB, specified, unimplemented |

`content_tree.py` has been restored to `vertiscope/core/` (it was deleted on a
reachability trace — it was unwired, not dead) and is the starting point for the
§4 transform. It is not yet wired; the golden I/O in
`HTML_DEDUP_CONTENT_TREE_GOAL.md` §1 is the test to wire it against, and it is
the cheapest high-value test currently available to us.
