# The three-form index over the 54-page corpus

`python scripts/build_index.py` — html → trie → markdown chunks → JSONL →
kuzu → frequency matrix → PageRank → triple product.

```
pages                 54
addresses             106,098
chunks                6,229      markdown lines 75,715
render accounting     rendered 75,715 + deduped 7,243 + suppressed 23,140
                      + empty 0 = 106,098      unaccounted 0
graph                 chunks 6,229 · addresses 106,098 · anchors 75,715
                      · contains 5,589 · links 6
frequency matrix      6,229 x 202,268 terms, 648,826 nonzeros (0.05% dense)
pagerank              sum 1.0000  min 1.28e-04  max 7.29e-04
elapsed               114 s
```

## 1. PageRank has nothing to rank

**6 link edges across 54 pages.** The corpus was assembled for *structural*
variety — 47 distinct hosts — so almost nothing links to anything else in it.
`LinksTo` only fires when a link resolves to a page already in the store, and
across 47 hosts it essentially never does.

What remains is 5,589 containment edges, so the PageRank being computed is a
function of nesting depth. Its spread is 1.28e-04 to 7.29e-04 against a
uniform 1.61e-04 — a factor of 5.7, entirely structural.

The consequence for the ranking rule is worth stating plainly: **on this
corpus the triple product is effectively a single product.** The rank factor
varies by 5.7x, the lexical factor by everything, and the semantic factor is
absent. Any claim that the three-form ranking works cannot be supported by
this corpus.

This is a corpus limitation, not a code defect, and it is not fixable by
tuning: exercising a link-graph prior needs a crawl of one site with real
internal linking. The corpus should gain such a crawl, kept separate from the
structural-variety set so the two purposes do not compromise each other.

## 2. Two ranking defects found by reading the output

Both were visible in the first run's top hits and neither would have shown up
in an aggregate metric.

**Query strings were being indexed as vocabulary.** `_url_words` expanded the
whole URL including the query, so `ctx_ver`, `rft_val_fmt` and tracking-widget
parameters became terms. The top hit for "university library catalogue" was a
Tumblr share widget's URL. Fixed by expanding host and path only — query
strings are machine parameters, and the words in them that matter are in the
page's visible text anyway.

**Identical content ranked repeatedly.** The top three hits for "book prices
in stock" were three copies of `<https://schema.org/Book>` at three addresses,
with identical scores — correctly, since they are identical text. Retrieval
now collapses on the rendering's content hash, which is the constraint the
spec sets: deduplication may not use embeddings, and here it does not need to,
because identical renderings are identical strings. 19 duplicates collapsed on
that one query.

## 3. One residual that should not be "fixed"

The top hit for "web scraping with python" is still a COinS blob:

```
ctx_ver=Z39.88-2004&rft_val_fmt=info%3Aofi%2Ffmt%3Akev%3Amtx%3Abook&...
```

This is not tokenizer noise. Wikipedia embeds machine-readable citation
metadata in a `title` attribute, and the citation is *for a book called "Web
Scraping with Python"* — so the lexical match is real and the chunk is
genuinely about the query. What is wrong is the rendering, not the ranking.

Suppressing COinS specifically would be a special case for one site's
convention, which is the anti-pattern this codebase already names. Left as is
and recorded; the address says exactly where it came from, so anyone who wants
to filter it can.

## 4. Performance findings

**`FreqMatrix` was quadratic.** Writing into a growing `lil_matrix` re-copies
every row written so far whenever a new term widens it, so ingest never
finished on the corpus. Deferring the sparse build until something reads it
made 4,000 chunks index in 0.03 s. Behaviour is unchanged — the similarity
scores are identical before and after.

**Kuzu row-by-row insert was 104 rows/s.** Batched through `UNWIND`, 27,000/s
— 17 minutes to 4 seconds for the corpus. Idempotence is unaffected, since
each statement is still a single `MERGE`; only the round-trip count changed.

## 5. An accounting bug that surfaced as a negative count

`RenderReport` accumulated `deduped`/`suppressed` across pages but *assigned*
`addresses`/`rendered`, so a report reused across a corpus compared the last
page's totals against every page's dedup count and reported

```
unaccounted: -7346
```

A count that cannot be negative for any real reason going negative is the
loudest possible form of this bug, which is the argument for the identity
existing at all. Now accumulates all five.
