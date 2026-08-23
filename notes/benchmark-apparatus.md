# A benchmark that scales to 100,000 live pages

*Proposal, 2026-08-15. Supersedes nothing; extends `tests/corpus` and the
`scripts/audit_*.py` family.*

## The problem with the apparatus we have

136 frozen pages, parsed serially, compared against a regex reference. It has
been worth every minute — it found nine real defects today — but it has four
limits, and all four bind at once:

1. **The pages are frozen HTML, so JavaScript never runs.** youtube.com,
   amazon.com and portal.azure.com are, as raw HTML, a `<div id="app">` and a
   script tag. The corpus contains such shells today and they score fine,
   because there is nothing in them to get wrong. We are not testing those
   sites; we are testing our handling of an empty div.
2. **136 is not a distribution.** It is a hand-picked list, so every metric is
   a statement about my taste in example pages.
3. **It is serial**, and it is now the slowest thing in the suite.
4. **It measures the parse, not the loop.** The O(delta) claim, the mutation
   observers, the webnav gestures — the parts that make this a *streaming*
   scraper rather than a batch one — are exercised by two live probes on a
   handful of pages.

## The insight that makes 100,000 pages affordable

You cannot curate 100,000 expected outputs, and you should not try.

But nearly everything we need to assert is **page-independent**. These are
properties of the algorithm, true of any input, checkable with no golden file:

| property | what it says |
|---|---|
| uniqueness | no address carries two values |
| completeness | every detection is addressable, every address resolves |
| repaint | `widget.render() == "  " * depth + text` |
| checkpoint | JSONL write→read→write is byte-identical |
| partition | chunks partition the address set exactly |
| delta | work is proportional to change, not to page size |
| termination | finishes inside a time and memory budget |
| liveness | produces *something* on a page with visible text |

A page needs no expected output to test any of these. That is what a
hundred-thousand-page tier is for: **not** "is this page extracted well" but
"does the algorithm's contract survive contact with the real web". Quality
against a reference reading stays where it belongs — on a curated tier small
enough to look at by eye.

Two tiers, two questions, and the expensive one needs no labels.

### The properties are hypotheses, not axioms

The table above is a list of things the design currently *claims*. The sweep's
job is to try to break them, and a break is ambiguous by construction:

> When a property fails on 3% of the real web, the finding is "this property
> and this web disagree". Which one gives is a design decision, and the sweep
> exists to force it — not to certify that the design was right all along.

Concretely, this has already happened twice today at 136 pages. Uniqueness
held; repaint did not, and the second failure was a *form* the design had
never reconciled between renderer and parser. A confirmatory reading would
have recorded 99.79% and moved on.

So the sweep reports two kinds of number, and the second matters more:

- **violations** — where a claimed property broke, with the page attached
- **distributions the design does not yet have an opinion about** — branching
  factor, delta ratio, subtree fanout, chunk sizes, tag frequencies, control
  density, text-to-markup ratio, xpath depth, shadow-root incidence

The second list is where a design change comes from. If real xpath depth has a
fat tail we never modelled, or the delta ratio bimodal because half the web
mutates by wholesale subtree replacement, that is a fact about the algorithm's
cost model that no invariant would ever have surfaced. Those get plotted, not
asserted.

**Nothing here is pinned at scale until the distribution has been looked at.**
Pinning a threshold before seeing the shape is how a measuring instrument gets
quietly reshaped to agree with the thing it measures.

## The tiers

| | tier | N | source | asserts | when |
|---|---|---|---|---|---|
| T0 | fixtures | ~60 | hand-written | unit semantics | every run, ms |
| T1 | frozen corpus | 136 → 1,000 | raw HTTP | quality + invariants | every commit, parallel |
| T2 | **rendered snapshots** | 200 → 2,000 | headless browser, post-JS | quality + invariants **on real SPAs** | every commit, parallel |
| T3 | live sessions | 10–100 | real browser, live | delta, mutation, webnav | nightly |
| T4 | scale sweep | 10k–100k | sampled frame | invariants + distributions | batch |

### T2 is the one that unlocks JavaScript sites

Drive a headless browser once per page, wait for the network to settle, then
serialize `document.documentElement.outerHTML` **after** hydration — plus, for
pages that keep mutating, a recorded trace of the mutations that arrived after
first paint. Store that as a fixture.

A YouTube watch page then becomes an ordinary deterministic input: the same
bytes every run, no network, no flake, fully parallel, and it contains the
actual rendered DOM with its thousands of nodes. The mutation trace replays
into the observer pipeline so `apply_delta` is exercised against real
mutations — infinite scroll, lazy-loaded comments, price updates — without a
browser in the loop.

This is the highest-value single piece of work in the proposal. It converts
the sites we most need to handle from untestable into ordinary fixtures, and
it makes the O(delta) claim testable deterministically instead of only in a
live probe.

### T4 is a sweep, not a suite

Fetch, process, assert the eight universal properties, record a metrics row,
discard the page. Report distributions per stratum. Its output is not
pass/fail per page but a **profile**: where the p99 lives, which strata fail,
what the failure modes are. A single page failing an invariant is a bug
report with a URL attached — which is exactly the input the frozen corpus
wants next.

## Sampling: how the pages are chosen

A hand-picked list measures the picker. Sampling is stratified, and the strata
are the things we believe change the algorithm's behaviour:

- **rendering regime** — static · progressive hydration · full SPA · infinite scroll
- **DOM size** — decile of node count (the delta claim is about this axis)
- **genre** — commerce · video · docs · news · forum · gov · dashboard · social · search
- **script** — Latin · CJK · Arabic/Hebrew (RTL) · Cyrillic · Devanagari
- **framework** — React · Vue · Angular · Svelte · none *(detected, not assumed)*

Frame: a published top-sites list (Tranco is the right one — open, versioned,
manipulation-resistant) for the head, plus a curated hard-case list for the
tail we already know hurts. Quota per stratum rather than proportional
sampling, because the interesting strata are rare: proportional sampling of
the web gives you 90% static pages and the SPA cell stays empty.

**Every result row carries its stratum.** A mean over 100,000 pages is a
number that cannot be acted on; "p90 repaint is 100% everywhere except
infinite-scroll commerce, where it is 96%" is a morning's work.

## Parallelism

The machine has 32 cores. The work is CPU-bound parsing with no shared state
between pages, which is the easy case.

- `ProcessPoolExecutor`, `--jobs` defaulting to **`cpu_count // 2`** (16 here).
  Half, not all: the user is on this machine, and a benchmark that makes the
  desktop unusable will not be run. Today's lesson is relevant — I misread the
  suite as slow when it was contending with my own background jobs.
- **Per-page timeout**, enforced by the pool, so one pathological page cannot
  hang the sweep.
- **Crash isolation**: a worker that segfaults marks its page failed and the
  run continues. At 100k pages, something will crash, and losing the run to it
  is unacceptable.
- **Append-only JSONL results**, so a killed sweep resumes by skipping
  completed urls rather than starting over.
- The browser tiers get a **separate, much smaller knob** (`--browsers`,
  default 4). Each Firefox is ~400 MB; this is memory-bound, not CPU-bound,
  and sizing it like the parse pool would swap the machine to death.

## Fetching politely

At this scale the harness is a crawler, and it should behave like one:
`robots.txt` honoured, one connection per host at a time with a delay,
identifying user-agent, and **a content-addressed cache** so a re-run costs
nothing. The cache is also what makes the sweep reproducible — a run is
pinned to a manifest of content hashes, so a regression is attributable to our
code and not to a site's redesign.

Cache lives in `build/pagecache/<sha[:2]>/<sha>.html.gz`, outside git. What
gets committed is the manifest and the baseline metrics — kilobytes, not the
~100 GB the pages themselves would be.

## Regression gating

Baseline metrics stored per stratum. A run is compared against it and fails on
a p90 regression beyond threshold, not on any individual page moving.

Defects are pinned **as rates**, never counts — today `test_ri2_failure_is_pinned`
failed purely because the corpus grew from 54 pages to 136 while the defect
was unchanged at 92.6%. A count of failures secretly measures the corpus size.

## Order of work

1. `scripts/bench/` package: parallel runner, resumable JSONL results, per-page
   timeout, crash isolation. Retarget `audit_quality` and `audit_roundtrip`
   onto it — they are the first two consumers, and a runner with two real
   consumers is designed better than one with none.
2. T2 snapshotter: headless capture of post-hydration DOM + mutation trace.
   Seed with 200 pages across the strata; the SPA cell first, since that is
   the cell we currently cannot test at all.
3. Stratified sampler over Tranco + hard cases; the manifest gains a
   `stratum` field.
4. T4 sweep with the politeness layer and the content-addressed cache.
5. Baselines and the regression gate.

Steps 1 and 2 pay for themselves immediately at 1,000 pages; 3–5 are what
make 100,000 meaningful rather than merely large.

**Revised 2026-08-15, on instruction: do not stage this timidly.** The
design is being matured now, and a decision to change it has to be made
against large-scale evidence rather than deferred until the apparatus feels
finished. So the sweep runs wide first and the tiers get tidy afterwards.
The staging above describes dependency order, not permission to sample 200
pages and call it a benchmark.

---

## First wide result (801 pages, search-discovered, 2026-08-15)

Violations of the three properties the sweep can currently check: **zero**.
Uniqueness, repaint and addressability held on all 464 pages that processed.

The distributions are where the finding is, exactly as argued above.

```
                      p50       p90       p99       max
max_xpath_depth        15        23        41       208
max_chunk_chars     1,169     1,290    13,185   234,996   (window = 1,200)
branching           1.449     1.694     2.029     9.752
```

Every extreme is the same kind of document:

- all 5 `RecursionError` failures are PDFs
- both pathological xpath depths (208, 182) are PDFs
- both monstrous chunks (234,996 and 191,380 chars) are PDFs

**The design has no content-type handling.** It is handed PDF bytes, treats
them as markup, produces a chunk 195x the context window, and blows the
interpreter stack on the deep ones. The frozen corpus never showed this
because I picked its pages; a search engine hands back PDFs constantly, and
`filetype:pdf` is one of the query shapes precisely because that is what the
real web returns.

This is a design change, not a bug fix. The "singular output type" assumed an
element tree. A PDF is a real document a user will point this at, and the
options — reject by content type, extract text properly, or address a PDF's
own structure — are three different answers about what the address space *is*.
Recorded here rather than patched, because that choice is not mine to make
quietly.

### And a defect in the instrument itself

The same run reported **279 timeouts of 801**. They were not timeouts. The
runner computed each future's deadline at *submit* time, so pages queued
behind 300 others burned their entire budget waiting for a worker. The failure
distribution was mostly an artifact of the sweep's own scheduling — a
measuring instrument reporting its own queue as a property of the web.

Fixed: a page's clock starts when the runner begins waiting on it. The failure
numbers above are therefore **not yet trustworthy** and the sweep needs a
re-run; the distributions, which come only from pages that processed, are.

### The instrument's own defect, quantified

Re-running with the deadline fixed settles what those 279 "timeouts" were:

```
                 pre-fix (801 pages)   post-fix (491 pages)
timeout            279   (34.8%)          4   (0.8%)
```

They were the sweep measuring its own queue and reporting it as a property of
the web. A page waiting behind three hundred others is not a slow page.

The same partial run also puts a better number on the crash: `RecursionError`
on **11 of 491 (2.2%)**, not the 5 of 801 the first sample suggested.

### Fixed: chain-following is a loop

`_collapse_node` recursed once per link of a single-child chain, so chain
length — the one thing in that walk that is unbounded — was charged against
the stack. Now a `while` loop follows chains and only genuine branch points
recurse, and those are bounded by how nested the document really is.

Measured before: depth 600 fine, 1200 fatal. After: depth 6000 in 0.1s.

Worth being clear that this is *not* the PDF question. A plain tower of
`<div>`s crashed identically, and deep wrapper chains are ordinary in real
markup — the PDFs were just the most reliable way to find one. The PDF policy
question is still open and still the user's to make.

### Two limits of the runner, stated rather than discovered later

**`timeout` bounds waiting, not work.** The parent waits up to `timeout` for
each future as it reaches it; it cannot interrupt CPU-bound work already
running in a worker, and total wait across a batch can exceed it. A smoke run
recorded a page at 72.8s under a 45s timeout for exactly this reason. Killing
a running worker is possible but costs the batch it shares, so the current
answer is: the timeout protects the run from *stalling*, not from a slow page.

**Per-page `seconds` is measured under load.** With 14 workers on 32 cores it
is contended wall-clock, not isolated cost. Fine for spotting a pathological
tail, wrong for anything claiming to be a per-page benchmark figure.

---

## T2 built, and it found a correctness bug on its first real page

Six captures now exist (`scripts/snapshot_pages.py` → `tests/snapshots/`),
replayed by `tests/test_snapshot_replay.py`. The tier justified itself
immediately.

**What it unlocked.** On `quotes.toscrape.com/js`, whose content is entirely
JavaScript-written:

```
frozen HTTP     5,806 chars ->  14 lines   (nav chrome and stylesheets)
rendered DOM    6,964 chars ->  43 lines   (the quotes, authors and tags)
```

Fourteen lines of furniture, scored as fine by every audit we had.

**The O(delta) claim, now deterministic.** Replaying the infinite-scroll
capture, where the page roughly doubles between passes:

```
pass  chars    changed  visited  nodes  pruned
0     7,022         76        0    250    100%
1    14,518         68      101    464     78%
```

101 nodes walked out of 464 to find 68 changed addresses. That is the claim,
asserted offline and repeatably instead of observed in a live probe.

Note the first version of that test asserted `changed <= first.changed`
(68 <= 76). It passed, but for no principled reason — `changed` is the delta's
size and has no reason to shrink when a page grows — and it would have stayed
green while the diff walked every node, which is the failure it existed to
catch. The quantity that carries the claim is `visited` against `nodes`.

### The open bug: incremental reuse loses content

Replaying `archive.org/search?query=university+library` — a web-components app
four `#shadow-root` levels deep — loses **44 of 3,310 addresses** that a cold
parse of the same final snapshot finds.

Established:

* the loss is from incremental reuse: pushing *only* the final snapshot finds
  all 3,310, while replaying all five passes finds 3,266;
* all 44 missing addresses sit beneath an ancestor whose stamped Merkle hash
  is unchanged across the final two passes;
* the DOM grew 1,420 → 5,213 hashed nodes over that step, 1,112 keeping their
  hash.

**Not** established, and not to be guessed at: the mechanism. The obvious
story — that the hash misses shadow-DOM changes — is wrong on inspection.
`hashOf` in `deep_serialize.js` does fold `shadowRoot` children in, and the
deepest unchanged-hash ancestor of a missing address is byte-identical between
the two passes (same hash, same text, same child count). So the stale entry
was seeded by an earlier pass, for a reason not yet found.

A first attempt at this diagnosis used a string prefix to test ancestry, which
matches `/div[1]` against `/div[11]`; redone with segment boundaries, the
finding held at 44/44, but the first number was luck rather than method.

Marked `xfail` in the suite rather than deleted or weakened. It is a real
defect in the delta path on exactly the kind of site the design is aimed at.

---

## End-to-end delta latency — and what it falsifies

Added on instruction, because every delta measurement so far was in *work*
(nodes visited, prune ratio, wire bytes) and none in *time*. `ScanUpdate` now
carries `chunk_ms` alongside `tag_ms`/`trie_ms`/`diff_ms`, plus `total_ms`
(snapshot in, re-rendered chunks out) and `ms_per_changed`. Reported by
`scripts/audit_delta_latency.py` and asserted in `tests/test_snapshot_replay.py`.

Over 12 passes that changed something:

```
where the time goes
  chunk render  79.8%      diff  0.7%      tag+trie  19.5%

what latency tracks   (1.0 = moves exactly with it)
  page size (nodes)   +0.992
  change   (changed)  +0.929

ms per changed address    p50 0.26    max 69.44
  worst: 3 addresses changed, 208 ms, over 2,628 nodes
```

**The loop is O(page) end to end.** The diff is genuinely incremental and
costs 0.7% of the time it takes to use it; everything wrapped around it scales
with the document. `dirty_chunks` is the clearest case — its docstring says
filtering by the delta's addresses "keeps it proportional to the change", but
it calls `render_trie` over the *whole* trie and filters afterwards, so the
render is proportional to page size and the filtering only decides what to
return. Tagging and trie construction are full-document passes too; reuse
makes tagging cheaper by a constant, not by an order.

Three addresses changed and the loop spent 208 milliseconds. That is the
design claim failing in the units a user feels, and no work-based metric could
have shown it: prune ratio on that pass was excellent.

This is deliberately **not** patched. Making the re-render incremental means
deciding what a chunk *is* across a mutation — whether chunk boundaries are
stable under insertion, and what a stored chunk's identity is when the content
around it shifts. That is the same class of question as the PDF policy: an
answer about the design, not a faster function.

Pinned as `xfail` (`test_latency_tracks_the_change_and_not_the_page`) beside a
passing `test_the_diff_itself_is_a_small_share_of_latency`, so the good half
is protected from regression while the gap stays visible.

---

## The live sweep: ten scrolls per page, on instruction

`scripts/sweep.py` fetches static HTML once per url, so it has exactly one
state per page and can never diff anything. Every delta number so far came
from six captures. `scripts/sweep_live.py` drives each page in a real browser
and **scrolls it at least ten times**, serializing after each scroll and
folding every snapshot through `StreamingScan`.

Ten is a floor enforced by the script, not a default: below it a page that
lazy-loads in two or three steps looks settled when it is not, and its passes
get recorded as no-change — which biases the latency distribution toward the
cheap case by dropping exactly the pages that were still working.

Parallelism here is by **browser**, not by core: one Firefox per worker
process, built lazily and reused across pages, closed by an atexit hook when
`max_tasks_per_child` recycles the process. Four is the default. A browser
costs ~400 MB and seconds to start, so a per-page driver would spend the sweep
in startup, and sizing this pool like the 14-worker parse pool would swap the
machine.

### First result (4 pages, all of which grew while scrolling)

```
                              p50        p90        max
  cold total ms             142.2      297.0      297.0
  cold nodes               2237.5     4650.0     4650.0
  scroll total ms           138.8      339.5      339.5
  scroll ms/changed          42.7      334.9      334.9

scroll latency as a fraction of the cold build
  p50 0.99    p90 1.14    max 1.14
```

**A scroll costs a whole page rebuild.** Ten scrolls is eleven full builds.

This is the same O(page) finding the six captures gave, now measured live with
real scrolling on real pages, and stated in the form that makes it impossible
to read as anything else: the ratio of an incremental update's latency to a
from-scratch build's is 0.99. The diff being 0.7% of that time is not a
consolation — it is the measurement of how little the incremental machinery
buys once the stages around it re-do the page anyway.
