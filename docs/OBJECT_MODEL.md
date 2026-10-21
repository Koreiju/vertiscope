# Object model

`PLUGIN_GOAL.md` binds this model to a wider trie than the web alone: the
local vault and every installed Python package are addressed in it too.

The trie is the ontology and the data. One address names a detected thing; its
leaf holds what was extracted. Chunks are a *window* over that trie, sized by
budget — not a unit of change. Markdown is a *rendering* of a chunk's subtree,
driven by the taxonomy segment of the address.

---

## 1. The address is one path

```
domain.com / tail/tail/tail / html/body/abs-xpath / @taxonomy / @regex-addr
└─ host ──┘ └─ url tails ─┘ └─ shadow-DOM node ─┘ └─ how it ┘ └─ what  ┘
                                                     renders     matched
```

Four spans, one string, one trie path.

| span | selects | belongs to |
|---|---|---|
| `domain.com` | the site | web |
| `/tail/tail` | the document | web |
| `/html/body/…` | the **shadow-DOM node** (absolute, shadow boundaries included) | web |
| `/@taxonomy` | `text` · `link` · `search` · `pagination` · `table` · `para+links` … | **markdown** |
| `/@regex-addr` | which entry in the detection bank matched | **detection** |

The tail is the join: the xpath says *which node*, the taxonomy says *what
markdown structure it becomes*, the regex address says *what recognised it*.
End-to-end provenance is readable from the path alone — DOM node to rendered
line to the rule that found it.

**Leaves hold the extracted HTML, and only leaves hold content.** Markdown is
*derived* from a chunk's leaves — never stored in the trie — and that derived
markdown is what gets vectorised. The trie is the canonical, addressable form;
markdown is the representation retrieval works over.

## 2. Two granularities, deliberately separate

```
MUTATION  →  leaf-level   a DOM change updates the leaves under its subtree
CHUNK     →  window-level a budget-sized subtree of the trie
```

A mutation does not create or destroy a chunk. It updates leaves. Chunk
boundaries move only when the **budget** says they must, and the budget is
evaluated by the up-down recursive chunker over the trie — up when a subtree
outgrows the window, down when siblings fit together.

```
op ∈ { create, destroy, grow, shrink }      governed by budget, not mutation
```

Token budgets are implicit to the JS side. Nothing in Python counts tokens.

## 3. Objects

```
── JS, in the page ─────────────────────────────────────────────────────

Sensor
  records : WeakMap<Node, Record>      state beside the DOM, never in it
  roots   : Map<Root, MutationObserver>
  dirty   : Set<Node>                  coalesced to ancestors
  trie    : PatriciaTrie               live, leaves = extracted HTML
  · observe(root)          attach; discover nested roots as they arrive
  · repair()               invalidate up, re-extract down  →  leaf deltas
  · rechunk(window)        up-down budget pass  →  chunk ops
  · drain() -> Payload

Detector                               the regex bank
  · match(el, attr) -> (taxonomy, regexAddr) | null
    covers every tag=attribute instance: text, href/src/srcset, JSON in
    data-*, media resources, embedded structures
  Each entry has an address, and that address is the `@regex-addr` tail of
  §1 — so a rendered line names the rule that found it.

  Two entries are load-bearing for navigation and carry negative vocabulary,
  because on a real page the positive signal is cheap and the false positive
  is what costs you:

  search      vocab   search · query · find · keyword · lookup · srch
                      buscar · recherche · suche
              tags    input · textarea · select, or role=search|searchbox|
                      combobox
              reject  type ∈ {hidden,email,checkbox,radio,file,image,color,
                      date,range,password}
                      name ~ first/last name · subscribe · newsletter ·
                      password · captcha · token · nonce · csrf · turnstile

  pagination  vocab   next · prev · previous · page · pager · load more ·
                      show more · see more · view more · read more · older ·
                      newer · additional · first · last · more · results ·
                      > < » « → ←
              tags    a · button
              guard   "More X" is pagination only when X ∈ {results, pages,
                      items, posts, stories, articles, entries, comments} —
                      "More Recipes" is a section heading, not a pager
              reject  player · volume · mute · fullscreen · pip · rewind ·
                      scrub · playback · cart · wishlist · reply · repost ·
                      bookmark · dropdown · haspopup · favorite · share
              deny    widget tags: slick-fab · soso-button · soso-icon…

  The rejects are the accumulated result of the false positives that a media
  player, a shopping cart and a social toolbar each produce, and they are the
  reason this bank is worth porting rather than re-deriving.

Chunker
  · fits(subtree) -> bool              budget, implicit
  · up(node)                           subtree outgrew the window
  · down(node)                         siblings fit together

Scroller                               scrolling and pagination are one loop
  seen : Map<pagerAddr, {fires, lastDelta}>
  · step()      one discrete scroll; drain; if a pagination control is in
                view, enact it in the same step
  · exhausted() two consecutive empty deltas
  Pagination is not an end-of-scroll fallback. A pager is enacted the moment
  it is first detected and again every time it re-enters view, because a feed
  that alternates lazy-load with an explicit "more" button only advances if
  both are driven. `seen` keeps the per-pager history so a control that stops
  producing deltas stops being pressed.

  Two kinds of pager, and they are not enacted alike.
    in-place    a button, or an anchor with no usable href. Appends. Pressed
                while scrolling, as above.
    navigating  an anchor with a real href. Replaces the document, so
                pressing it mid-read throws away the page being read. Enacted
                only once the scroll can go no further -- 7.6's "stepping off
                the bottom turns the page" -- and exactly one per step,
                because two navigations in a step race and the loser's delta
                is attributed to the winner.
  Only controls that advance are enacted. `< Previous` and `Last >` are
  pagination and are rendered as such; pressing them undoes progress or skips
  everything between, so detection finds them and enactment declines them.

  · refused(el) -> bool                  never enacted, whatever it was called
  Detection is a classifier, and a classifier is wrong sometimes. The
  scroller clicks a live page under a real session, so a misclassification is
  not a bad reading -- it is an action taken on the user's behalf. On one
  YouTube results page the pager detector offered up "Sign in". So a fixed
  set is refused independently of any classification: sign in/up/out, log
  in/out, register, subscribe, checkout, buy, add to cart, donate, pay,
  delete, remove, block, report, upload, publish, submit, send, reply,
  confirm, accept, consent, install, download; any href under an auth,
  cart, billing or payment path; any submit button; anything inside a form
  with an action or an open dialog. This list exists to be over-broad. A
  pager it wrongly refuses costs one page of results; a checkout it wrongly
  presses cannot be undone.

── the boundary ────────────────────────────────────────────────────────

Payload
  chunks : [ ChunkDelta ]
  dict   : string[]                    interned path segments, append-only

ChunkDelta                             ONE chunk, aggregate
  chunkId : int
  op      : create | destroy | grow | shrink | update
  trie    : { path -> extractedHtml }  the chunk's own patricia fragment
                                       leaves only; paths are §1 addresses

── Python ──────────────────────────────────────────────────────────────

PatternTrie                            apply, never derive
  · add(path, chunkId) / remove(path, chunkId)
  · instance_count / subtree_count     rollups, for ordering and scope
                                       (never rendered; see §7)
  · forward_truncate(path, n, attr)    ellipsis view

Workspace                              the store
  · ingest_chunks(url, deltas)         graph · freq · embeddings · mirror

MarkdownView                           the derived representation
  · render(chunk) -> markdown          leaf HTML → markdown, by @taxonomy
  · digest(markdown) -> str            gates re-vectorisation
  one derivation, two consumers: the REPL paints it, the vectoriser embeds it

VectorQueue                            streamed in, batched out
  pending : OrderedDict[chunkId, markdown]   deduped by id; last write wins
  · push(chunkId, markdown)            O(1), called per changed chunk
  · flush(batch) -> vectors            embed many at once
  Embedding is the one genuinely expensive step and the one that batches
  well, so it is decoupled from the delta stream by a queue rather than run
  per chunk. A chunk touched five times while the queue drains is embedded
  once, which is why the queue is keyed by id.

Repl
  · open(url)      DB first; scan only if unregistered (scroll limit: argv)
  · navigate(path) patricia walk — addressing, never drawn
  · view(chunkId)  one chunk in full; the rest collapsed
  · stats()        per-stage cost
```

## 4. Flow

```
 BROWSER          SENSOR (js)                 BOUNDARY      PYTHON
 ───────          ───────────                 ────────      ──────
 mutation ──────▶ observer
                  dirty ← target, coalesced
                     │  (idle, debounced)
                     ▼
                  repair()
                  ├ invalidate up the root path
                  ├ re-extract down (Detector)
                  └ LEAF DELTAS ──┐
                                  │
                  rechunk(window) ◀┘   budget: up/down recursion
                  └ CHUNK OPS         create · destroy · grow · shrink
                     │
                     ▼
                  aggregate per chunk:
                  { chunkId, op, trie{path→html} }
                     │
                     └─ drain() ─────────────▶ ChunkDelta[]
                                                  │
                                                  ├─▶ PatternTrie.add/remove
                                                  ├─▶ Workspace.ingest
                                                  └─▶ MarkdownView.render
                                                        leaf html → markdown
                                                        │
                                            ┌───────────┴───────────┐
                                            ▼                       ▼
                                     Repl paints it        VectorQueue.push
                                                                  │
                                                          (batched flush)
                                                                  ▼
                                                          embeddings → DB
 ◀──────────── enact(click/scroll) ◀──────────  affordance loop
                                          ▲
                        REPL context window drives rechunk demand
```

The dashed return is the point of §2: what the REPL has open determines which
subtrees are worth chunking finely. Rechunking is demand-driven, so the budget
pass runs where attention is, not uniformly over the document.

## 5. Sequence: a scroll adds ten articles

```
Repl          Sensor(js)              PatternTrie     Workspace   MarkdownView
 │ scroll ──────▶│
 │               │ observer: dirty={feed}
 │               │ repair: Detector re-extracts new subtrees
 │               │   → 70 leaf deltas, paths per §1
 │               │ rechunk: 10 subtrees fit the window
 │               │   → 10 × op=create
 │ drain() ─────▶│
 │ ◀─ ChunkDelta[10] ─
 │               │
 │ ──────────────────────▶ add(path, cid) ×70
 │ ──────────────────────────────────────▶ ingest
 │ ──────────────────────────────────────────────────▶ render(open chunk)
 │ paint: the page — headings, prose, tables, images; one section full
```

## 6. Sequence: the reader scrolls down the page

What the reader does is move down an article. What that costs is a trie walk
and, sometimes, a local rechunk — neither of which appears on screen.

```
Repl                      Sensor(js)            MarkdownView
 │ cursor moves to the next section
 │   ├ collapse the section above → heading + first line
 │   └ open the next
 │
 │ resolve(cursor) ── patricia walk, local ──┐   invisible
 │ ◀── the chunk holding it ─────────────────┘
 │
 │ chunk already held?  ──── yes ───▶ render(chunk) ─▶ fields, images
 │ no ─▶ rechunk(down, path) ─▶ finer chunks for this subtree only
 │                              (budget pass, demand-driven)
 │
 │ paint: the section reads as a page — headings, prose, bitmaps
```

## 7. The REPL is a low-fi web browser

One viewport. What it renders is the **database**, ranked — and what fills the
database is the live page, fed by every search and every scroll. Reading and
scanning are the same act, so there is no "results pane" beside a "page pane".
There is a page, assembled from what is known, ordered by what matters here.

```
┌ history ▾ ────────────────────────────────────────────────────────────┐
│ archive.org ▾                                                         │
│   /search?query=university+library                                    │
│   /details/icelossorbit                                               │
│   /details/tidewatermass                                              │
│ duckduckgo.com ▸                                                      │
│ quotes.toscrape.com ▸                                                 │
└───────────────────────────────────────────────────────────────────────┘
 ◀ ▶ ⟳  archive.org/search?query=university+library
┌ search ───────────────────────────────────────────────────────────────┐
│ 🔍 glacier retreat                         ⏎    Year ▾   Media ▾      │
└───────────────────────────────────────────────────────────────────────┘
 ▲
 ▏  # Search results
 ▏
 █   ## Ice loss measured from orbit
 █   ▄▄▀▀▄▄▄▀
 █   ▀▄▄▀▀▄▄▀   > Satellite gravimetry resolves mass change at basin
 █   ▄▀▀▄▄▀▀▄   > scale, with monthly solutions from 2002 onward.
 █
 █   | basin        | Gt yr⁻¹ | σ  |
 █   | Amundsen     |   -159  | 11 |
 █   | Totten       |    -18  |  6 |
 █
 █   [Read online]  [Download PDF]  [Cite]
 ▏
 ▏   ## Mass balance of tidewater glaciers
 ▏
 ▏   ## Glaciers of the Himalaya — survey plates
 ▼   [ Load more ]   ‹1› [2] [3] … [Next ›]
```

Everything in the content area came from the page: its heading, its image,
its blockquote, its table, its links, its pager. Nothing is added — no
scores, no counts, no badges, no section labels of our own invention. The
only marks that are ours are the browser's own furniture: history, address
bar, and the rail.

### 7.1 One viewport, assembled from the store

Every section is a **chunk** held in the database, rendered as the markdown of
what that chunk contained. Opening one renders it in full, in place — it does
not navigate away, because the chunk is already here.

The document is not a replay of one DOM. It is the domain's chunks in ranked
order, rendered as one continuous page: the site's search gave some, scrolling
gave others, a page read last week gave the rest. Order is the only thing
ranking contributes to the screen.

### 7.2 Search and scroll feed the store

```
    search ⏎ ─┐
              ├─▶ live page ─▶ deltas ─▶ trie + chunks ─▶ DB ─┐
    scroll ───┘                                               │
                                                              ▼
                 viewport ◀──── ranked chunks ◀──── retrieval ┘
```

Enacting the site's search submits it in the real page; the delta that comes
back is ingested and immediately eligible for ranking. Scrolling drives
`Scroller.step()`, which loads more of the page and folds pagination in as it
passes — every step contributing more chunks.

So the viewport improves as you use it. Search narrows what the site will
give; scroll extracts more of what it gave; both land in the same store the
ranking reads from. A second search on the same domain is answered partly
from chunks the first one contributed.

### 7.3 Ranking, anchored to where you are

One score per chunk, the triple product, over the **domain's** chunks:

```
    rank(c) = pagerank(c | here) · semantic(c, q) · tfidf(c, q)
```

- **pagerank** runs on the chunk-containment and link graph, *personalised to
  the current URL* — the restart vector favours the page you are on, so its
  own sections and what it links to outrank distant pages on the same domain.
  Move to another page and the same corpus reorders around it.
- **semantic** is cosine over the chunk's markdown embedding.
- **frequency** is tf-idf over the chunk's terms, with document frequency
  taken across the domain.

**None of this is drawn.** Ranking decides the order sections appear in and
nothing else — no bar, no score, no badge. A reader sees a page whose parts
happen to be in a useful sequence, which is what ranking is for. The numbers
exist and are inspectable on demand (`why <n>`), never on the page.

Scope is a prefix walk on §1's address, not a filter: `domain.com` is the
default, `domain.com/tail` narrows to one document, and dropping the prefix
widens to the whole corpus.

### 7.4 Markdown fields are the rendering vocabulary

`@taxonomy` selects the field, and the field is what a reader sees:

| taxonomy | renders as |
|---|---|
| `heading` | `#`…`######`, by depth within the chunk |
| `paragraph` | wrapped prose, inline links in place |
| `para+links` | prose with clickable `[label]` spans |
| `list` | `-` / `1.`, nested |
| `table` | aligned columns, `…` truncation to width |
| `quote` | `>` |
| `code` | fenced, unwrapped |
| `link` | `[label]`, underlined |
| `media` | colour bitmap, `alt` beneath on failure |
| `search` | the search bar |
| `pagination` | `‹1› [2] [3] … [Next ›]` |
| `filter` / `sort` | dropdowns beside search |

Recursion inside a chunk is markdown nesting — heading levels, list indent,
table rows — never an outline of the tree that produced it.

### 7.5 Images in colour

```
MarkdownView
  · bitmap(src, cols, rows) -> str[]
    kitty / sixel   full resolution inline, when the terminal advertises it
    half-block      `▀`, 24-bit fg = upper pixel, bg = lower — two pixels
                    per cell; the portable default
    alt text        when neither, or the fetch fails
```

Fetched through the session holding the page, so referer-gated and
authenticated images render like any other, and nothing is written to disk to
show one. Size follows the field: hero at chunk width, result thumbnail at
eight columns, icon at one cell.

### 7.6 Scrolling, the rail, and its arrows

Two motions, because they are not the same gesture:

**Continuous** — wheel, arrows, PgUp/PgDn. Moves by line; when the cursor
leaves the open chunk the next opens and the last collapses to heading and
first line.

**Sectional** — `[` and `]`, or the rail's `▲` `▼`, or a click on any
collapsed heading. Jumps a whole chunk.

The rail is a scrollbar whose stops are chunks — the only kind that means
anything once the document is chunked. Height-weighted by content, the open
chunk filled, click to jump, drag to scrub, hold an arrow to repeat.

**Past the end, `▼` becomes the page's `Next`.** Stepping off the bottom
paginates, so turning the page is the same gesture as reading down it. And
scrolling drives the *live page*, not the viewport: a step scrolls the real
document, waits for the debounce, drains, and ingests — which is why the
viewport grows as you read. Reading position never jumps when it does.

### 7.7 Search is the page's search

When a `[search]` control is detected, the bar **is** that control: typing
types into the real input, ⏎ submits it in the page. What returns is the
site's own delta, ingested and ranked with everything else.

Three bindings, in order, with the icon showing which:

| | when | icon |
|---|---|---|
| the page's control | a `[search]` field was detected | `🔍` |
| find | no control on this page | `/` |
| corpus | no page open | `▤` |

In every case the ranked viewport is the answer — the difference is only
whether the query also went to the site.

### 7.8 Controls are enacted, never simulated

| control | rendered | enacted |
|---|---|---|
| pager | `‹1› [2] [3] … [Next ›]` | click, or scroll past the end |
| load-more | `[ Load more ]` | pressed while scrolling; greys out after two empty deltas |
| sort | `Sort: relevance ▾` | same address set, new order confirms it |
| filter | `Year ▾  Media ▾` | subtree-scoped replacement confirms it |
| field | `[ text________ ]` | typing types |
| checkbox | `[x] Full text only` | toggling toggles |
| tab / accordion | `‹Overview› Details  Reviews` | additive-within-subtree |
| hover menu | `Browse ▾` | hover enacted, revealed subtree rendered |

Two rules hold across all of them:

- **Nothing is simulated.** The action happens in the live page and the REPL
  renders what came back. A filter that does nothing renders as a filter that
  did nothing — the truth about that page.
- **A control whose delta contradicts its label is relabelled.** A `Next`
  that appends is a load-more; a `Load more` that replaces is a pager. The
  label is a hint; the delta is the fact.

### 7.9 History and navigation

The top bar is every URL in the store, prefix-collapsed by domain. Not recent
pages — the whole corpus, navigable by prefix, which is what keeps a thousand
pages to one row. Domains, then their documents; no counts.

**Collapsible at every level, including itself.** `▾` on the bar's own title
folds the entire history to a single line, giving the page the full terminal;
`▸` unfolds it again. Each domain folds independently, and a domain with
nested paths folds at each path level, so a site with deep URLs collapses to
whatever depth is useful rather than all-or-nothing.

```
┌ history ▸ ─────────────────────────────────────────────────┐   folded
└────────────────────────────────────────────────────────────┘

┌ history ▾ ─────────────────────────────────────────────────┐   unfolded
│ archive.org ▾                                              │
│   /details ▾                                               │
│     /icelossorbit                                          │
│     /tidewatermass                                         │
│   /search?query=university+library                         │
│ duckduckgo.com ▸                                           │
└────────────────────────────────────────────────────────────┘
```

**Ordered by recency, nearest the domain.** Within a domain the most recently
visited URL sits directly beneath it, and older ones fall away downward; the
domains themselves order the same way, the most recently touched at the top.
So the row adjacent to a domain name is always where you last were on that
site, and the shape of the bar tracks the shape of the session — which is the
only ordering that makes a folded history useful, since a fold leaves the
most recent thing visible.

Fold state is per domain and persists across sessions: a site you keep folded
stays folded, and one you work in stays open.

| gesture | effect |
|---|---|
| click a domain | expand to its documents |
| click a document | open it; ranking re-anchors to that URL |
| address bar | store first; live scan only if unregistered, to a scroll limit given on the command line |
| `◀ ▶` | history stack |
| `⟳` | re-scan, delta only |
| click `[label]` | resolve the address; stored chunk if held, else scan |

Opening a stored chunk costs no fetch. That is the point of storing it.

## 8. Prohibitions

- **Python may not derive a delta.** It is told. `add`/`remove`/`ingest` only.
- **Python may not count tokens.** The budget is the JS chunker's.
- **The trie may not hold markdown.** Leaves are extracted HTML; markdown is
  produced by `MarkdownView` from `@taxonomy`, and that derived markdown is
  what gets vectorised.
- **A mutation may not move a chunk boundary.** Only the budget does.
- **A chunk may not span two documents.** Its paths share a `domain/tails`
  prefix by construction.
- **Vectorisation may not run per delta.** It is queued by chunk id and
  flushed in batches; a chunk that changed five times between flushes is
  embedded once.
- **A contrast is read against one page load, and resumed whole or not at
  all.** Comparing encodings across separate visits compares two documents:
  a live page differs between loads, pagination multiplies its content by
  however many pages a run reached, and a redirect ends one arm and not
  another. Two arms of the *same* configuration came out 235% apart that
  way. Every row therefore carries the id of the load it was read against,
  a page is only aggregated when all its rows share one, and a part-finished
  page is redone from scratch rather than stitched across an interruption.
  Resume is for coverage; it must never be allowed to become the contrast.
- **A measurement surface lives in the REPL, not beside it.** Anything that
  reports on the system -- a sweep, a comparison, a health readout -- is a
  REPL command that reads the underlying record when it is invoked. A
  generated page or a written-up table is a snapshot, and a snapshot labelled
  "live" is worse than one labelled honestly: it is only as fresh as the last
  time someone remembered to regenerate it, and nothing about looking at it
  says which time that was. The REPL is the test surface; the surface that
  reports on a test belongs there too, where it cannot be stale by
  construction.
- **Markdown whose digest is unchanged may not be re-vectorised.** A leaf can
  change without changing what the chunk renders to — a reordered attribute,
  a whitespace edit — and re-embedding on that would spend the most expensive
  step in the system on nothing.
- **The scroller may not enact a control it merely believes is a pager.** A
  detector's output is a hypothesis; a click is an act. Enactment is gated by
  a refusal set (§5) that no classification overrides.
- **A control may not be classified from its markup.** Class names and query
  strings are not evidence about what a control does. Judge it by its
  accessible name and by `rel` — searching an attribute soup for a bare
  substring made 37 controls on one YouTube page read as pagination, because
  their design system names a component `yt-spec-button-shape-next`.
- **A delta must be able to name what left.** Removal by omission is banned
  on the store side, which is only meaningful if the sensor can express a
  removal at all — it could not, so a chunk whose node was deleted stayed
  addressable forever and a page that re-renders its results accumulated dead
  addresses that all looked fine. Chunk roots are tracked alongside the
  WeakMap and swept for disconnection on every repair.
- **An address must resolve to the node it came from.** An address the page
  cannot evaluate cannot be enacted, so it is not an address — it is a label.
  Text nodes are `text()[n]`, the root step is `/html`, a malformed tag is
  selected by `name()`, and a shadow boundary is an explicit `#shadow-root`
  step because no XPath crosses one.
