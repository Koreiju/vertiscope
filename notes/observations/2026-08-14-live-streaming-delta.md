# Live streaming scans and the incremental transport

`scripts/probe_live_delta.py` — real Firefox, real navigation, a snapshot per
settle pass, consecutive trie diffs, then store and retrieve.

## The measurement

`https://quotes.toscrape.com/scroll`, 8 passes:

```
pass      doc     wire   wire%   nodes  delta visited   pruned
   1       7K       7K  100.0%     250     76       0  100.00%
   2       7K       0K    2.1%     250      0       1   99.60%
   3       7K       0K    2.1%     250      0       1   99.60%
   4       7K       0K    2.1%     250      0       1   99.60%
   5      14K       8K   56.8%     464     68     101   78.23%
   6      14K       0K    1.0%     464      0       1   99.78%
```

* an unchanged pass moves **2.1%** of its own document and costs **one**
  subtree comparison, at any page size;
* the pass where the page grew moves **57%** and visits **22%** of the trie;
* across the stream, **88.4%** of bytes saved against a full transfer;
* 3 chunks of 8 re-rendered on the changed pass.

## What was wrong before

**The deep serializer was never fully ported.** The upstream
`backend/dom_deep_serializer.py` computes Merkle hashes and prunes identical
subtrees; the extracted `deep_serialize.js` did neither, so the transport was
a full DOM every pass. `stream.py` originally documented this as a known
limitation. It is now implemented — and implemented *in-page*, which the
upstream version is not: hashing after transfer identifies what changed but
has already paid to move everything, so the saving only exists if the
unchanged bytes never cross the bridge.

**The first probe proved the trivial case.** Pointed at Hacker News it
reported a 1,946x saving and printed all green. HN settles on the first pass,
so every later pass was unchanged and the "saving" was the cost of confirming
nothing had happened. The probe now *fails* if no pass changed anything: a run
that cannot observe a delta cannot verify the delta property. The second
default URL was dropped for the same reason — it did not actually scroll-load
under the driver, and the gate caught it.

**An IIFE swallowed the pruning silently.** The walker read `arguments[0]`
inside a closure, which sees the IIFE's own empty argument list rather than
Selenium's parameters. `known` came out null, nothing was ever pruned, and
every other number still looked right — the transport quietly stayed
full-size while the run reported success. Failure modes that leave all the
visible metrics intact are the argument for measuring the thing itself
(`wire%`) rather than its proxy.

**The transport assertion had the wrong baseline.** It compared a later pass
against pass one and failed on a page that *grew*, reporting "-106% saved".
Growth is the case the feature exists for; the baseline has to be the
document that pass would otherwise have moved.

**The retrieval assertion asked the wrong question.** Fixed queries
("software", "news") against a quotes site returned nothing, reported as an
end-to-end failure. Queries are now drawn from the frequency matrix itself —
mid-document-frequency terms, since a term in every chunk separates nothing
and a term in one tests only that nothing crashed.

## Two defects found by building the app around it

**`GraphStore.close()` never released the database.** It closed the
connection only, so kuzu kept an OS lock on the directory and reopening the
same workspace failed with "Could not set lock on file". Scan-then-search in
one process was impossible, and the error surfaced at the *second* open,
pointing away from the missing close.

**`FreqMatrix` was quadratic.** Writing into a growing `lil_matrix` re-copies
every row written so far whenever a new term widens it, so ingest over the
corpus never finished. Deferring the sparse build until something reads it
made 4,000 chunks index in 0.03 s, with identical similarity scores before and
after.

## Extraction made incremental, and the hole that opened under it

Tagging was the last stage still proportional to page size — 63% of the
post-transport cost on a large page. It is now incremental: a subtree whose
`(xpath, hash)` matches the previous pass is not re-examined and its
detections are spliced in.

```
                        cold     warm    saved
books-toscrape            4ms      1ms    73.9%
wikipedia (9,134 tags)   83ms     39ms    53.1%
apnews    (7,307 tags)  110ms     47ms    56.9%
guardian                 37ms     19ms    49.9%
```

Output is byte-identical to re-tagging, values included. The remaining ~50% is
the walk itself, which is kept deliberately: sibling order is not recoverable
from the addresses (THEORY Prop. 11.3.1), and the visit is what records it, so
skipping visits would silently degrade the trie's ordering to its fallback.
What is skipped is the attribute sweep, the URL regexes and the text
extraction — where the time actually goes.

Live, the granularity behaves as designed: one lookup covers an entire
unchanged page (76 tags, 1 subtree); a pass where the page grew fragments into
14 subtrees around the new content; the next settled pass collapses back to
one covering all 144.

**Reuse is keyed on `(xpath, hash)`, not on the hash alone.** A subtree that
*moved* has the same content and different addresses, so content-only keying
would splice in detections pointing at where the content used to be — a wrong
answer that looks entirely plausible.

### The soundness hole this opened

Reuse is only sound if the digest changes whenever anything the extractor
reads changes. It did not. The serializer hashed fifteen hand-picked
attributes, chosen for stability so that a framework rewriting a state flag
would not look like a content change. But the extractor reads far more than
fifteen — `style` (CSS urls), `cite`, `longdesc`, `formaction`,
`data-original`, and every JSON-bearing `data-*`. A subtree whose only change
was in one of those hashed **equal**, and the stale detections were spliced
back in with nothing reporting it.

The rule is now inverted: hash every attribute *except* those the extractor
provably ignores, with the skip list mirroring the tagger's own. That keeps
the original anti-churn property — state flags and layout attributes are still
excluded — without trading correctness for it. Attributes are sorted before
hashing, since attribute order is not part of a document's meaning and a
browser may report it differently between reads.

A test asserts the shape of the fix rather than restating the list a third
time: the hasher must work by exclusion, and its skip list must not exclude
anything the tagger treats as content.

**The bug was found by a broken test helper.** The helper stamped digests from
the opening tag and a counter rather than from content, so two documents with
different text got identical digests. The test that caught it —
"a changed subtree is re-examined" — was written to catch exactly this class
of failure in the production path, and caught it in the harness first.

## PageRank had nothing to rank until the crawl existed

The 54-page corpus is 47 distinct hosts, so it holds **six** resolvable
cross-page links in total. PageRank therefore ran over containment edges
alone — a function of how deeply the page happened to be wrapped in divs —
and came out near-uniform. It contributed nothing to ranking while appearing
to, which is the worst state for a factor to be in.

`vertiscope scan --follow N` crawls the seed's host breadth-first, taking the
frontier from the trie's own `urls.*` addresses rather than a second link
extractor. Eight pages of `quotes.toscrape.com`:

| | corpus (54 pages, 47 hosts) | crawl (8 pages, 1 host) |
|---|---|---|
| link edges | 6 | 28 |
| containment edges | 5,589 | 8 |
| rank spread | 5.7x | **11.3x** |
| top-ranked chunk | (arbitrary) | the site's home page |

The home page ranking first is the check that it works: every tag page links
back to it, and nothing else about the page says "important".

The interplay is visible in the product too. For "inspirational quotes" the
winning chunk scores `rank=0.121 lex=0.163`, beating one at `rank=0.011
lex=0.289` — a chunk with nearly twice the lexical match, outranked because
nothing points at it. That is the rank factor doing the job it exists for,
observed for the first time.

**The frontier needed a document filter.** The extractor is deliberately
attribute-agnostic — it takes URLs from *any* attribute, which is what lets
it survive sites that invent their own — so a stylesheet's `href` is a
`urls.internal` address exactly like an anchor's. Right for extraction, wrong
for crawling: the first run spent two of six pages on `main.css` and
`bootstrap.min.css`, which chunk to two lines of nothing. Filtered by
extension, and by exclusion rather than allowlist, since most real pages have
no extension at all (`/tag/life/`).

## Two more silent failures in the semantic path

**Stored vectors were never loaded.** Embeddings live on the Chunk nodes,
which is the entire reason for putting them there, but a freshly opened
workspace started with an empty matrix — and an empty matrix scores every row
zero, which the strict product treats as a veto. `--semantic` on an existing
workspace returned *nothing*, indistinguishable from "no match".

**Vectors were never computed for workspaces indexed without an embedder,**
with the same symptom. Both are now handled on the query path: load what is
stored, embed what is missing, write the result back so the cost is paid
once. The first search with all three factors alive:

```
[0] rank=3.81e-02  lex=0.059  sem=0.652   "I may not have gone where I
                                           intended to go, but I think I have
                                           ended up where I needed to be."
```

**A missing workspace was created rather than reported.** Opening a workspace
creates it, so a mistyped `-w` path produced an empty one and every query came
back "no results" — a wrong answer shaped exactly like a right one. The read
commands now require the workspace to exist.

**"No hit" now names the factor that vetoed.** Three vetoes produce one
symptom, and the fix for each is different. Searching `book` against a corpus
full of `books` returns nothing because terms are matched exactly; that is a
defensible choice, but it has to be said out loud rather than left as an
empty result.

## The new stores had no representation invariant, and it cost a bug

`FreqMatrix`, `GraphStore` and the `Workspace` coupling them arrived after
MODEL.md, so they had none — while the store they replaced had five clauses
and a mutation suite. The asymmetry was the gap: the newer components hold
more state, and more of it is derived, which by PROP-22.4 is exactly what
makes an invariant necessary rather than tautological.

Eleven clauses now, in `vertiscope/invariants.py`: **F-1..F-5** (the matrix),
**G-1..G-4** (the graph), **W-1..W-2** (the coupling). Each has a mutation
test proving it can fire, and the coupling's mutation test requires the
*exact* firing set — a clause that fires on everything is as useless as one
that never fires, and both look identical from a green suite.

**W-1 found a real bug on its first run.** `purge` dropped a page's chunks
from the graph and left its rows in the frequency matrix, so `idf` went on
counting documents that no longer existed. Every score shifted slightly and
nothing failed — the exact shape of defect an invariant exists to catch, and
the exact shape that a test suite written around happy paths never will.

Fixing it exposed a second one. Rows cannot simply be deleted, because the row
index is the key aligning the frequency matrix, the embedding matrix and the
PageRank vector; compacting would renumber everything after the hole and
silently re-point the other two. So removal tombstones the row instead — but
the first version never reclaimed tombstones, so a purge-and-rescan cycle (the
normal cycle for a crawler kept up to date) grew the matrix without bound.
Retired rows now go on a free list that `add` draws from, and the free list is
persisted with the matrix, since otherwise the leak returns on the next
reopen. Three purge/rescan cycles now leave the row count unchanged.

## A page that lost content kept it, and mis-attributed every line

The mutation probe covers content that *changes*. The other direction —
content that is **removed** — was broken worse, and in a way that corrupted
the one guarantee the address scheme exists to provide.

`GraphStore.ingest` wrote everything with `MERGE`, and its docstring said so
plainly: *"Nothing here deletes: a chunk that vanished between scans stays
until purge_page removes it."* That was a considered decision about *stale
rows*. What it missed is that anchors accumulate too.

Re-indexing a 30-item catalogue as a 3-item one:

```
                    before      after (broken)   after (fixed)
chunks                   5                   5               1
addresses               91                  91              10
chunk lines / anchors  ok        7 lines / 21      7 / 7
```

A chunk keeps every anchor it ever had. Both `MarkdownChunk.from_json` and the
REPL's `load_url_from_store` pair markdown lines with anchors **by position**,
so from the first stale anchor onward every line was attributed to the wrong
address. `where 42` in the REPL returned someone else's xpath; `find
--addresses` listed elements the chunk did not contain. Nothing raised, and
retrieval looked correct — the chunk's *markdown* was overwritten properly, so
only the addresses were wrong.

`GraphStore._reconcile` now runs before the writes and drops three things: the
anchors of every chunk this page currently has (the rewritten ones are about
to get fresh ones, and a chunk that merely got *shorter* has the same problem),
chunks the page no longer produces, and addresses for elements that no longer
exist. `Workspace.ingest` retires the matching frequency rows, so `idf` stops
counting chunks that are gone.

Checked to be non-destructive in the directions that matter: a page that grows
back recovers fully, re-indexing an unchanged page removes nothing, one page
shrinking leaves another alone, and a live re-scan of a four-page crawl is
byte-stable.

## Re-scanning a URL could never observe a change

`probe_live_delta.py` shows the saving on a page that **grows**, which is the
easy case: new content cannot be stale. The hard case is a page that changes
**in place**, where old and new content occupy the same addresses and a reuse
bug returns the old — silently, with correct-looking addresses and no error.

`scripts/probe_live_mutation.py` covers it: serve a page locally so it can be
rewritten between scans, drive a real browser at it across generations, and
assert that each generation's content is present and no earlier generation's
survives.

It failed immediately, and the cause was not either incremental mechanism.
`ShadowDOMScanner.scan` carried

```python
# Navigate (skip if already there)
if current != url and current != url + "/":
    self.driver.get(url)
```

so a second scan of the same URL never reloaded and read the DOM already in
memory. Every re-scan reported no delta — not because the page had not
changed, but because nothing had looked. For a crawler keeping an index
current, which is the whole point of incremental re-scanning, this is fatal:
the index would report itself up to date forever.

The skip is *correct inside a settle loop*, where re-navigating would reset
the scroll position the loop is driving, so the behaviour survives as
`force_reload=False`. `stream_snapshots` passes `reload=True` by default,
because its callers are asking what the page says now.

**The control flag is what identified it.** Re-running with
`--full-transport` — pruning disabled — showed the same stale content, which
ruled out the transport and the reuse in one step. A probe with no way to
disable the mechanism under test would have implicated the mechanism.

With the fix, across three generations of a page whose volatile section is
entirely rewritten each time:

```
deltas per pass       [0, 9, 0, 9, 0]      the change registers
tags reused per pass  [26, 15, 26, 15, 26] the stable section is not re-read
wire                  9.4%                 transport still prunes
```

and every generation's content is present with none of the previous
generation's surviving.

## Shadow DOM was untested, and turned out to be fine

The frozen corpus contains prose *about* shadow DOM and no declarative shadow
markup, so every stage from addressing to splicing was running shadow paths
nothing had exercised — while THEORY Def. 11.4 claims the address alphabet
absorbs the boundary and Prop. 11.2/Cor. 11.3 apply verbatim.

Driven through a real shadow tree, they do. `#shadow-root` is one more letter;
addresses round-trip; ancestry stays a prefix test; generalization keeps the
boundary (erasing it would merge a component's shadow content with its host's
light children); an edit inside a shadow root produces a delta; the bracket
scan measures a `<template shadowrootmode>` correctly and splices a pruned
shadow subtree back exactly; reuse carries shadow detections rather than
dropping them; and shadow content is retrievable with its addresses intact.
16 tests, all green on the first run.

**A speculative fix was written and then removed.** Shadow content sorts after
the host's light children, and that looked like the missing-`doc_pos` bug from
earlier — `#shadow-root` is synthetic, so it has no walk position. A
`settle_order` pass was added to give position-less nodes the earliest
position beneath them. Measured over eight real pages it settled 27 nodes and
re-ordered **zero** addresses: the only nodes taking that path are url-prefix
segments, each heading a single chain. The actual cause is that
`get_children(include_shadow=True)` yields light children first, which is a
defensible reading rather than an oversight — the composed order a browser
renders depends on `<slot>` placement, which the serialized form does not
preserve, so neither ordering is "the document's". The pass was removed and
the behaviour documented instead. Code that does nothing while claiming to fix
a bug is worse than no code.

## A corpus defect, pinned not fixed

8 of 54 frozen pages carry mojibake — 259 occurrences, worst on
`docs.python.org` (183). `requests` follows RFC 2616 and falls back to
ISO-8859-1 whenever the Content-Type header omits a charset, ignoring the
document's own `<meta charset>`; most servers omit it, so UTF-8 was decoded as
latin-1 and stored doubly encoded. `£51.33` is `Â£51.33` in the fixture, and
because that re-encodes to valid UTF-8 nothing downstream ever complained.

`scripts/fetch_corpus.py` now prefers the header's charset, then the
document's declaration, then chardet. The corpus is **not** re-fetched:
re-fetching changes every stored SHA-1 and moves every benchmark number
recorded against it, which is a decision rather than a side effect of a bug
fix. `tests/test_corpus_quality.py` pins the eight affected pages, so a ninth
fails and a re-fetch forces the pin to be updated.

## The floor resurrected the dead

Retiring a row keeps its slot (renumbering would re-point the embedding matrix
and the PageRank vector) and empties its counts, so it scores zero on the
lexical factor. Under the strict product a zero is a veto, so a tombstone
could never be returned — and that is the only reason it never was.

`--floor` adds a positive term to *every* factor, tombstones included. A
retired row then came back as a ranked hit with an empty cid, an empty url and
empty markdown: a phantom pointing at nothing, produced by exactly the option
a user reaches for when they are already getting too few answers.

Masked in `ThreeFormIndex.build` rather than filtered at the end, so the rows
are gone from every path at once instead of from the one that was noticed.

## Two silent `zip`s, made loud

The line/anchor misattribution above was possible because two places paired
markdown lines with anchors using `zip`, which stops at the shorter sequence.
Both were reading data that had just been proven capable of disagreeing.

`MarkdownChunk.from_json` now raises on a mismatch, and the REPL's
`load_url_from_store` skips the chunk and says so in the status line — a page
with one damaged chunk stays browsable, and a line silently pointing at
another element is not something to render. Neither would have prevented the
bug, but either would have located it in seconds rather than requiring the
comparison that found it.
