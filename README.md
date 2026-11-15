# vertiscope (domvec)

An **Obsidian plugin** that turns the web you browse into a navigable 3D
knowledge graph, with an "ego" that sits at the centre of view: a compact,
draggable 2D/3D computation graph of your own tool space -- your browsers,
the artifacts you attach, your notebooks and their runs, your database
queries.

Everything is driven by one data structure: a **patricia trie keyed on
`url : xpath : markdown line : content`**, built in-page by a recursive,
shadow-DOM-aware MutationObserver fold, and streamed as diffs into the graph.

## The plugin

| Pane | What it is |
|---|---|
| **3D graph** | Every scanned chunk a node, placed by a UMAP of its embedding (position and colour); pages unfold into their chunks; hover presents a chunk's picture, a click opens its panel. Plain scroll zooms the 3D view. Idle, the scene slowly turns (`drift` on the bar). |
| **The ego** | The tool space as one graph: the ego at the centre, browsers, slates, notebooks with their cells and readouts, tagged web chunks. In 2D it is a plane on the camera -- centred, a fixed distance from the lens in every view, so it never drifts with a pan -- and the 2D plane editor's cards place their nodes on it; `ego 2D` / `ego 3D` switches to its spatial layout. Drag any of its nodes to move it; shift+scroll zooms its plane; a click selects, and a tagged chunk's node opens that chunk's panel. The `? 2D`, `? 3D` and `? tools` buttons on the bar list every gesture. |
| **Browser cell** | An Electron webview in an Obsidian tab. As you browse, the sensor folds each DOM mutation (open shadow roots included, recursively) into the trie and streams the diff to the graph. uBlock Origin is bundled. |
| **Panels** | A chunk's markdown, each line carrying its trie address; controls in it act on the live page through that address. |
| **Notebook / slates** | Python cells in notes, run on a kernel; their inputs and outputs are wired into the ego graph. |
| **Search** | Retrieval over the store (frequency x PageRank x semantic), drawn as light in the 3D graph. |

Behind it runs a **sidecar** (Python): a supervisor with a front proxy and a
worker that holds the store (kuzu graph + vectors), the embedder and the UMAP
projector. The plugin starts it (the `sidecar` button) and every child process
is windowless.

### Build and run

```bash
cd obsidian-plugin && npm install && npm run build
```

`npm run build` type-checks, bundles, and installs into the vault's
`.obsidian/plugins/domvec-bridge/` -- by default this repository, which is
itself the vault; `DOMVEC_VAULT=<path>` installs elsewhere. Every build says
where it wrote.

The sidecar by hand, if you are not using the button:

```bash
python -m domvec.obsidian supervise --workspace build/<store> --port 8788 --semantic --capture --enact --kernel
```

### How it is verified

Not by a green suite alone. Each requirement has a **live check** that runs
inside the running plugin (`obsidian-plugin/checks/live.mjs`), reloads the
plugin first so the code under test is the code that is loaded, and carries a
**planted arm** -- the defect put back on purpose -- that must fail, so a
check that cannot fail is caught. They are run through the project's MCP
server (`domvec/obsidian/mcp.py`: `confirm`, `pipeline_profile`,
`app_anomalies`, `hang_watch`, ...), gated on the reader being idle.
`python -m pytest -q` covers the backend.

### Where the design lives

- `docs/PLUGIN_GOAL.md` -- the user's own words, verbatim and dated; binding.
- `docs/PLUGIN_PRD.md` -- those words decomposed into numbered requirements.
- `docs/OPEN_WORK.md` -- what is done, measured, and still open.
- `docs/AFFINE_MAP_GOAL.md` -- the sensor's goal: the affine map from the shadow DOM to the REPL.

---

## The distiller underneath

What follows is the backend the plugin is built on -- the scanner, the
content-address trie, the markdown renderer and the store -- usable on its
own from the command line.

Scan pages into a **universal content-address trie**, render them as markdown
that links back to the DOM, index them three ways, and browse the result in an
interactive terminal.

```bash
domvec scan https://quotes.toscrape.com/scroll     # live, streaming, incremental
domvec find "einstein world"                       # pagerank x frequency x semantic
domvec browse                                      # click, scroll, type, navigate
```

### The one output type

Everything the scanner finds is reported as a **content address**:

```
(url tree, absolute xpath, content tag, firing detector[sub])

https://x.test/p | /html/body/main[1]/ul/li[4]/a | urls.internal | href
```

The absolute xpath is what the trie is keyed on and what retrieval hands
back, so a hit is always a place in a document you can go to. The generalized
(landmark-anchored) and relative forms are *derived* — they are the input
boundaries to hashing and dedup, never the key.

The last component is why the address is a key at all. One accessor can hold
several values — `srcset` is a list, a `<style>` block holds many urls, an
`ld+json` script holds a whole document — so the address carries the position
*within* the accessor: a candidate index, a character offset, a JSON pointer.
Always intrinsic to the value, never an emission counter, so anyone holding
the address can re-resolve it.

Measured over the frozen corpus — **136 pages across 109 hosts**, 40 MB, from
minimal static pages to a 2.6 MB Wikipedia table, thirteen scripts, plain-text
RFCs and JavaScript shells: **344,876 detections, 342,939 addresses, zero
carrying two different values.** Walk order reproduces the DOM exactly on
every page.

The tool accepts its own output. `find --addresses` prints an id, and that id
goes straight back in — to `domvec where`, which resolves it to the chunk it
anchors with the line marked in context, or to the REPL's `open`, which loads
the page and scrolls to it. Three spellings work: the id, the full injective
key, and the absolute xpath, which is the one a person can read off a page.

### The three checkpoints

```
   live page
      │  streaming snapshots, unchanged subtrees pruned in-page
      ▼
1. universal content-address trie      absolute xpath, Merkle-hashed
      │  render, dedup, context-window chunking
      ▼
2. markdown as JSONL                   one line per unit, each anchored to an address
      │  ingest
      ▼
   kuzu graph + numpy frequency matrix
      │
      ▼
3. the interactive REPL                click · scroll · type · navigate
```

### O(delta), measured on a live scan

`domvec scan` drives the page and folds in each snapshot as it arrives. The
in-page walker hashes every subtree and is told which hashes the caller
already holds, so unchanged subtrees come back as placeholders and are spliced
locally.

```
pass      doc     wire   wire%   nodes  delta visited   pruned
   1       7K       7K  100.0%     250     76       0  100.00%
   2       7K       0K    2.1%     250      0       1   99.60%
   5      14K       8K   56.8%     464     68     101   78.23%
   6      14K       0K    1.0%     464      0       1   99.78%
```

An unchanged pass moves **2.1%** of its own document and costs **one**
subtree comparison. The pass where the page actually grew moves 57% and
visits 22% of the trie. Verified end to end by `scripts/probe_live_delta.py`,
which **fails** if the page under test does not actually change — a static
page yields a flattering number that proves nothing.

The same hashes make *extraction* incremental: a subtree whose `(xpath, hash)`
is unchanged is not re-examined, and its detections are reused. On a live
scan, one lookup covers an entire unchanged page; when the page grows, the
search descends only as far as the change and reuses the intact siblings.

```
pass   wire%  tag ms  reused  subtrees  delta
   1  100.0%       6       0         0     76
   2    2.1%       3      76         1      0     one lookup, whole page
   5   56.8%       7      76        14     68     grew: reuse fragments
   6    1.0%       8     144         1      0     settled: one again
```

Measured against re-tagging: **50–74% saved, byte-identical output.**

Incremental: transport, extraction, indexing, rendering. Not incremental:
parsing — the spliced document arrives as HTML and has to become a tree
before anything can look at it.

The cost of a change tracks the change *divided by the tree's branching
structure*, which is worth stating precisely because pruning skips subtrees
and a document without subtrees has none to skip:

```
trie shape (nodes/leaf)    pages   median share of trie visited for one leaf
nested   (> 2.2)             122                                      2.82%
flat     (< 1.5)               2                                    100.00%

27,534 leaves ->   110 nodes visited     a 2.6 MB Wikipedia table
   505 leaves ->   513                   a text/plain RFC
```

The two flat pages are plain-text documents, where every paragraph hangs off
one element. They are also static — nothing re-scans them — so the cost is
real and does not arise.

### Retrieval

The mortegon triple product, with the two vector axes kept apart:

```
score = pagerank · tfidf_cos · nomic_cos
```

Every factor keeps a veto, and `SearchDiagnostics` reports how many candidates
each one zeroed, so "no results" is never ambiguous — the message names which
factor did it, because the fix for each is different. `--floor` softens the
product; it is off by default so the softening is a decision someone made.

The rank factor needs a link graph, and a set of unrelated pages does not have
one. `domvec scan <url> --follow N` crawls the seed's host, taking the frontier
from the trie's own `urls.*` addresses:

```
                 unrelated pages    one crawled site
link edges                     6                  28
rank spread                 5.7x               11.3x
top-ranked                  n/a       the home page
```

With real edges, a chunk with `lex=0.163` beats one at `lex=0.289` because
nothing points at the second — which is the whole reason the factor is there.

Deduplication never touches embeddings and never needs the DOM — identical
renderings are identical strings, and the trie's content hashes are the
candidate filter with token-multiset subsumption deciding. Both are stated as
*cannot*, so both are held structurally: neither `markdown.py` nor `trie.py`
may name a vector or a document, and the retrieval-side collapse is checked by
running the same query with and without vectors loaded and comparing what
merged.

### Commands

```bash
domvec scan <url>...          live streaming scan into a workspace
    --follow N --depth D      crawl N more pages from the same host
domvec index <file|dir>...    offline, no browser
domvec find "<query>"         three-form retrieval  (--addresses to trace hits)
domvec where <aid|key|xpath>  an address back to the chunk it anchors
domvec browse [url]           the interactive REPL
domvec status                 what a workspace holds

-w, --workspace DIR           default: ./build
--window N                    context window: the chunking hyperparameter
--semantic                    embed chunks (needs the nomic model)
```

A workspace is a directory:

```
build/
  graph.kuzu      addresses, chunks, embeddings, and the edges between
  freq/           the frequency matrix, as raw numpy arrays
  chunks/*.jsonl  the markdown checkpoint, one file per page
```

The semantic vectors live with their chunks because a vector is a function of
that chunk's text. The frequency vectors do not, because their idf term is a
function of the whole corpus and would go stale on the next scan.

### The REPL

Clicks, drags, the wheel, cursor placement, text fields and checkboxes, over a
markdown rendering of the page — with every line still carrying the address it
came from, so `where 42` gives you the xpath and clicking a link opens the
stored copy without touching the network.

`controls` names the pagination, menus, filters and search boxes, read off the
addresses already extracted rather than from a second index. It reads a control
twice — what it says, joined to the link by xpath, and where it goes — because
plenty of pagers have only one of the two: `1-50  51-100` has no words, and
`More` at `?p=2` has no distinctive target. Measured over the corpus by
`scripts/audit_controls.py`, which asserts both that known controls are found
and that pages without them stay empty.

With a browser attached, every action that navigates — a link, a control, a
submitted search box, `back` — re-renders the page it landed on, so what is on
screen is where the browser is.

The interaction model is a pure state machine (events in, state out), so all
of it is proved without a terminal. The mouse arrives as xterm SGR escape
sequences, which is an ordinary parser over bytes, so that is proved too.
`scripts/mouse_probe.py` closes the remaining gap by piping real click bytes
into a separate `domvec browse` process and reading the tick back out of its
rendered output.

### Quality, against the pages themselves

Every other measurement here is internal — addresses unique, chunks
partitioning them, accounting balancing. All of that can be perfect while the
markdown is garbage, because none of it compares the output to the input.
`scripts/audit_quality.py` does, over the whole frozen corpus:

```
                 median    mean     min      max
recall           100.0%   99.9%    97.6%   100.0%   content words kept
heading recall   100.0%  100.0%   100.0%   100.0%   the source's h1-h6
link recall      100.0%   99.5%    83.3%   100.0%   anchors addressed
anchored         100.0%  100.0%   100.0%   100.0%   lines carrying an address
plumbing           3.2%    8.1%     0.0%    66.7%   lines referencing a resource
duplication       20.4%   22.8%     0.0%    85.6%   lines repeating an earlier
```

No page loses more than 2.4% of its words, and every line on every page
carries an address. The four numbers that are not 100% each have a recorded
cause rather than a mystery: json leaking out of an attribute past the
*reference's* tag regex; six urls over the 500-char cap; JavaScript shells with
no content to dilute their `<head>`; and a SQL grammar reference that repeats
`expr` three hundred times because the grammar does.

### Verifying

```bash
python -m pytest                          # 1140 tests, ~6 min
python scripts/audit_addressing.py        # uniqueness, completeness, order, identity
python scripts/build_index.py             # the whole corpus, end to end (-> build-corpus/)
python scripts/probe_live_delta.py        # live scan, real O(delta)  (needs Firefox)
python scripts/probe_live_mutation.py     # a page that changes: no stale content
python scripts/mouse_probe.py             # the pointer path
python scripts/audit_controls.py          # does `controls` find real controls?
python scripts/audit_quality.py           # the output, against the page it came from
python scripts/benchmark.py               # 9 metrics over 54 pages
```

Tests are split between properties that **hold** (a regression fails) and
defects **pinned** at their measured extent — a pinned bound is recorded, not
accepted, and fixing one forces its bound to be updated rather than passing
silently. `notes/ERRATA.md` carries the reasoning; `docs/THEORY.md` carries the
results the code cites.

### Documents

| file | what it is |
|---|---|
| `docs/THEORY.md` | the mathematics, background first |
| `docs/CONTENT_EXTRACTION_RULES.md` | the domain: every category, subcategory and constant |
| `docs/METHOD.md` | how the problems here are approached |
| `docs/PROCESS.md` | how theory, code and findings feed each other |
| `notes/ERRATA.md` | what earlier revisions got wrong, and why |
| `notes/observations/` | measurements, dated |

### Requirements

Python 3.10+, Firefox (for live scans), and `pip install -e .`.
`kuzu`, `numpy` and `scipy` are required; `gpt4all` for `--semantic`, `pynput`
only for the physical stage of the mouse probe.
