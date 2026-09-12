# The notebook kernel panel — design

Addendum II puts this before the hovering SLM bar and asks that it be nailed
down *first*: *"we move onward to the notebook kernel panel design first to nail
it down correctly. This is where we bring in our electron sensor when ready,
exposing the chunk scanning and selection highlighting for markdown rendering
in the alternative panel by the user to annotate the context fed to our small
language model."*

This is the design, stated against the requirements it answers — `P-N1..P-N10`,
`P-M1..P-M5`, `T-5`, `X-6`/`X-7` — and against the one constraint that decides
most of it.

---

## 0. The constraint that decides the architecture

`CLAUDE.md`, hard constraint 1: **describe every change in terms of the
patricia trie**. A change that cannot be stated as reading from or writing to
the trie has left the map.

So the question is not "how do we run code in Obsidian". Three plugins already
do that. The question is: **where does a cell's output live such that it is
trie content?** `P-N5` and `P-N6` answer it as requirements — notebooks are
*"dynamically recursively chunked like webpages"* and *"continuously
diff-updated to the db, re-vectorized and re-assigned to chunks"* — and those
two sentences rule out most of the design space before any code is written.

A notebook whose outputs live anywhere but in the markdown cannot satisfy them
without a second ingest path.

## 1. Prior art, read before designing (X-1)

Two architectures exist and they differ exactly where it matters.

| | [obsidian-markdown-notebook](https://github.com/lextoumbourou/obsidian-markdown-notebook) | [JupyMD](https://github.com/d-eniz/jupymd) |
|---|---|---|
| where outputs live | **in the `.md`**, inside HTML comment markers | in a paired `.ipynb`, synced by Jupytext |
| kernel | persistent **subprocess** per language, per note | real Jupyter kernels via `jupyter_client` |
| cell identity | **SHA-256 of the cell source** in the marker | notebook cell ids |
| external deps | the interpreter only | Python + Jupytext + jupyter_client + ipykernel |
| invisible to renderers | yes — comments survive PDF, GitHub, reading view | n/a |

Also surveyed: [tillahoffmann/obsidian-jupyter](https://github.com/tillahoffmann/obsidian-jupyter)
(`jupyter` fences executed as notebooks), [MaelImhof/obsidian-jupyter](https://github.com/MaelImhof/obsidian-jupyter)
(opens `.ipynb` in an embedded Jupyter Lab), and the `Notebooks` community
plugin (embeds a `jupyter lab` server in a pane).

### The choice, and why it is not close

**Outputs live in the markdown, in comment markers. Kernels are subprocesses
first, with the Jupyter protocol as a later switch behind `P-N2`.**

Three reasons, in order of weight:

1. **It is the only option that makes `P-N5`/`P-N6` free rather than new
   work.** Output in the `.md` *is* markdown the trie already holds. The
   existing recursive chunker reads it, the existing vectoriser embeds it,
   and `T-5` (the vault in the trie) covers a notebook the moment it covers a
   note. A `.ipynb` sidecar needs a second parser, a second chunker, and a
   second answer to "what address is this output at".
2. **A sidecar file is two sources of truth for one document**, which is the
   objection `domvec/obsidian/mcp.py` already makes in its own docstring about
   note editing — *"a second one would be two sources of truth for the same
   files"*. Jupytext's bidirectional sync is a merge problem we would own
   forever, and it fights `S-12`'s uniform delta stream: a change would arrive
   twice, from the `.md` watcher and from the `.ipynb` watcher, and the trie
   would have to guess which was the edit.
3. **Fewer moving parts under `S-14`** — *"staying slim on web interfaces"* is
   said of the browser, but the reasoning carries: the subprocess route needs
   the interpreter and nothing else, where the Jupyter route needs four
   packages before a cell runs.

What we take from JupyMD anyway: **kernel discovery**. `P-N2` wants switching
between Jupyter kernels and PowerShell terminals, and enumerating installed
kernels is the right way to populate that list even when we execute via
subprocess.

## 2. The panel, as an object

`P-N` is not a peer of `P-M` — `X-6` settles that: *P-N is P-M grown*, and the
native markdown panel survives beside it. So there is no new view type. There
is a **native Obsidian markdown editor** with three things added to it:

```
┌─ native markdown editor (P-M1) ───────────────────────────────┐
│                                                               │
│   # Analysis                                                  │
│   Some prose, edited natively. Nothing intercepts this.       │
│                                                               │
│   ```python                                    [▶ run] [P-N3] │
│   df.describe()                                               │
│   ```                                                         │
│   <!-- nb-output hash=a91f… format=html -->                   │
│   | col | mean |                        ← trie content (P-N5) │
│   | --- | ---- |                                              │
│   <!-- /nb-output -->                                         │
│                                                               │
│   [[]]  ← retrieval gesture, unchanged (P-M2, R-1)            │
│                                                               │
│  ─────────────────────────────────────────────  P-M4: bottom  │
│   [+ code]  [+ terminal]  [+ browser cell]                    │
└───────────────────────────────────────────────────────────────┘
┌─ kernel RUN surface, directly below (P-C2) ───────────────────┐
│  kernel: python3 ▾      ← interpreter only, NOT a             │
│  [cell 3] ok  0.4s        shell-vs-kernel chooser (§4a)       │
└───────────────────────────────────────────────────────────────┘

        ...and a command terminal is a SEPARATE PANE (§4a):

┌─ separate pane ───────────────────────────────────────────────┐
│  PS domvec>                                                   │
└───────────────────────────────────────────────────────────────┘
```

Three claims in that sketch are load-bearing:

- **The output block is markdown**, so the chunker sees a table as a table.
  This is where `D-5` (no tables rendered) stops being only a web-scraping
  defect: a notebook that computes a dataframe emits a markdown table, and if
  the projection drops tables the panel loses its own output.
- **The buttons are at the very bottom** (`P-M4`), not floating per-cell.
- **The kernel's run surface is directly below the artifact, always**
  (`P-C2`) — not a toggle, not a tab. It is a run-and-output region, *not* a
  shell prompt; a command terminal is a separate pane (§4a), which is why
  `[+ terminal]` at the bottom opens one rather than growing this strip.

## 3. Addresses: what a notebook looks like in the trie

The trie is keyed `domain / url-tail / xpath / markdown / content-detection`
(`T-1`, currently a `D-2` defect at four levels). A vault note has no domain
and no xpath, so the scheme has to be stated rather than assumed:

| level | a web page | a vault notebook |
|---|---|---|
| domain | `apnews.com` | `vault://<vault>` |
| url-tail | `/article/x` | the vault-relative path, `notes/analysis.md` |
| xpath | `/html/body/div[2]/p` | `/section[1]/section[2]/p[1]` — see below |
| markdown | the rendered form | the same |
| content-detection | `paragraph`, `nav`, … | `text.visible`, `text.code`, `text.metadata`, `urls.*`, `media.images` |

**Built 2026-09-12** as `domvec/vault.py` + `Workspace.index_note` +
`domvec notes`. Two rows above changed under contact with the code, and both
changes are the interesting part.

**The xpath is not "the heading path plus an ordinal".** That was this
document's guess and it is wrong. Hanging blocks under the heading step —
`/h1[1]/p[1]` — renders **every paragraph as a heading**, because
`markdown.py`'s walk carries a heading's label down to its children:

```python
if is_element and label in _HEADINGS and child_label not in _HEADINGS:
    child_label = label
```

That rule is correct, for HTML: `<h3><div>Technology</div></h3>` means the div
*is* heading text, and 124 of the Guardian's 181 headings depend on it. But
markdown's heading does not **contain** the section it opens — it **names** it.
The two models disagree, HTML's is the one the trie implements, and the guess
asserted containment markdown never meant.

The fix is HTML5's own answer: an explicit **`section` wrapper**, with the
heading and its blocks as *siblings* inside it.

```
# Analysis        ->  /section[1]/h1[1]
prose             ->  /section[1]/p[1]
## Method         ->  /section[1]/section[1]/h2[1]
prose             ->  /section[1]/section[1]/p[1]
```

Measured before and after on one note: prose drawn as `# Prose about…` at every
level, versus prose drawn as prose. `tests/test_vault_addressing.py::
test_prose_is_not_drawn_as_a_heading` is the non-vacuity arm — it asserts
against the real renderer's output and fails on the obvious scheme, while every
structural test still passes. Remove the wrapper as a simplification and only
that test notices.

**Inline links get their own element step** (`…/p[1]/a[1]`) for the same
reason: an anchor is an element with its own xpath in HTML, and a `urls.*`
detection sharing its block's address made the renderer consume the whole
paragraph as one link label — `[see [[Vortex Lattice]]](Vortex Lattice)`.

**The taxonomy uses existing categories only.** `address._CLASS_BY_CATEGORY`
classifies by *category*, so a new subcategory (`text.code`) degrades correctly
and a new category would not. One imperfection recorded rather than papered
over: `text.code` gets class `text`, because `_CANONICAL_CLASS` reaches class
`code` only through `json_data`.

**Verified against the real vault**: `domvec notes docs/` indexed 18 documents
into 786 chunks / 2,697 addresses, and retrieval answers from them —
"notebook kernel panel" returns this PRD's own X-7 build order, "closed shadow
roots" returns `CONTENT_EXTRACTION_RULES` §8.4.

Two consequences worth stating because they are easy to get wrong:

- **A cell's output is its own address, not part of the cell's.** They have
  different `content-detection` classes and they change independently — an
  output changes when the cell *runs*, the cell changes when it is *edited*.
  Folding them into one address makes the re-run of an unedited cell look like
  an edit.
- **The heading path is a `subtree_hash` question and the ordinal is an
  `exact_hash` one.** `CLAUDE.md` 5b: the projection memo must key on
  `exact_hash` because it prints values verbatim. And `CLAUDE.md` 5c applies
  directly — a cell's ordinal is a function of its *siblings*, so inserting a
  cell renumbers every later one, and the invalidation has to reach them.
  **That is `D-6` in a new location**: §M.1 found 36 duplicate-chunk groups
  differing only by a positional index because a shifted sibling's old address
  was never popped. A notebook is a document where the user inserts siblings
  constantly. Fix `D-6` before this ships, or reproduce it here.

## 4. Execution, and the two hashes

The marker carries a digest of the cell source, and *which* digest matters:

- `exact_hash` semantics — the exact source text. A cell whose whitespace
  changed *is* a different cell for execution purposes, because the user may
  have changed a string literal.
- Never `subtree_hash` semantics. That hash is deliberately blind to exact
  values so `apply` can recognise moved content, and a cell marked clean on a
  content-blind hash would serve a stale output after any edit that a token
  multiset cannot see.

State is **per note**, as in obsidian-markdown-notebook: variables shared
between cells in one note, isolated across notes. Two reasons — a note is the
unit a reader thinks in, and it makes the kernel's lifetime match a leaf's.

Status lives in the marker (`running`, `error`, `timeout`) so a crash mid-cell
leaves a document that says so rather than one that looks finished.

## 4a. What the switch switches — kernel here, terminal there

Answered by the user, 2026-09-12: *"A switch to a kernel run and then a command
terminal when switching to a separate pane."*

So `P-N2` is **not a dropdown over interpreters**, and it is not two panes side
by side by default. The two modes are distinguished by **where the thing
lives**:

| where | what it is | what it is for |
|---|---|---|
| **in the panel**, below the artifact | a **kernel run** — the cell executes, output lands in the markdown per §4 | the edit-run loop, inside the document |
| **a separate pane** | a **command terminal** | shell work that is not a cell — PowerShell, a build, a git command |

The switch's first position is therefore the kernel, and the terminal is what
you get by taking it out of the document.

**What this settles that was open.** §2's sketch drew a persistent terminal
strip under the editor with a `kernel / pwsh` selector in it. That was the
dropdown reading and it is wrong. The strip under the artifact is the kernel's
run surface — `P-C2`'s *"terminal always directly below"* in the sense of a run
and output region, not a shell prompt. A shell prompt is a separate pane.

**And it reconciles `P-N3`.** *"A toggle on a code block opens terminal or
kernel — possibly both at once"* now has a coherent reading: both at once is
the notebook panel running its kernel **while** a separate pane holds a command
terminal. They are not competing for one region, so "both" needs no special
layout — it is two panes, which Obsidian already does.

**Consequence for §3's addressing.** A kernel run writes into the document, so
its output is trie content under the note's address (`content-detection:
output`). **A command terminal in a separate pane is not in a document, and so
by default it has no address.** That is a decision rather than an oversight: a
shell session is a stream, not a leaf, and giving it a trie address would put
untracked command history into a store whose point is addressable page content.
If terminal transcripts should be retrievable, that is a separate requirement
needing its own `content-detection` class — it does not arrive with this one.

**Kernel discovery is still borrowed from JupyMD**, but it now populates a
*smaller* control: which interpreter the in-panel kernel runs, not a chooser
between a kernel and a shell.

---

## 5. The sensor, the chunk overlay, and the SLM selection

This is the part with no prior art, and it is `P-N8`/`P-N9`/`P-N10`.

*"Exposing the chunk scanning and selection highlighting for markdown
rendering in the alternative panel by the user to annotate the context fed to
our small language model."*

Read as three separate mechanisms:

1. **`P-N8` — chunk boundaries are visible.** The panel draws where the
   chunker cut. Not decoration: it is the only way a reader can tell why
   retrieval returned half a section, and at a 256-token window the cuts are
   frequent enough to matter. Rendered as a gutter mark, keyed on the chunk's
   address, read straight from the trie.
2. **`P-N9` — selection over rendered markdown.** In the *alternative* panel —
   the rendered side, not the editor — because a selection over source text
   would select markers and fences, and the reader is selecting **content**.
3. **`P-N10` — the selection is the SLM's context.** The reader marks what the
   model gets. This inverts the usual default: the model does not take the
   panel, it takes what was handed to it.

`P-N10` needs a decision the goal does not make, so it is flagged rather than
assumed: **a selection is a set of trie addresses, not a string.** Addresses
survive the page changing under them and can be re-resolved later, which is
what makes an annotation durable and what lets the same mechanism work over a
browser cell whose page moved. A string would be a snapshot with no way back
to what it referred to.

The Electron sensor (`S-13`) enters *here* and not before — the verbatim says
*"when ready"*. What it is needed for is the browser cell's chunk overlay
(`P-B7`), where the boundaries must be drawn over a live page's own cartesian
layout. A markdown notebook's chunk overlay needs no browser at all, which is
why this panel can be nailed down first.

## 6. Build order inside this panel

Each step ends somewhere verifiable over CDP (`X-2`), never a screenshot.

| # | step | done when |
|---|---|---|
| 1 | ~~Note addressing~~ **DONE** — `domvec/vault.py`, `Workspace.index_note`, `domvec notes` | `T-5`: 18 docs -> 786 chunks / 2,697 addresses, and retrieval answers from them. 13 tests, one of them the renderer arm |
| 2 | Fence detection + `▶ run` in both views | a button appears per fence, in reading *and* live preview |
| 3 | Subprocess kernel, python only, per-note state | two cells share a variable; two notes do not |
| 4 | Output markers written, read, re-rendered | output survives a restart and renders in reading view |
| 5 | Outputs are chunked and vectorised (`P-N5`/`P-N6`) | an output is *retrievable* by `[[]]` — the proof that it is trie content |
| 6 | Kernel run surface below the artifact; command terminal in a *separate pane* (§4a); interpreter discovery | a cell runs in-panel AND a separate pane gives a pwsh prompt; discovery lists installed kernels |
| 7 | `P-N8` chunk overlay | gutter marks match `/chunk` addresses from the sidecar |
| 8 | `P-N9`/`P-N10` selection → address set → SLM context | the SLM's prompt contains exactly the selected addresses' content |

**Step 5 is the acceptance gate for the whole design.** If an output is not
retrievable, the markdown-marker choice bought nothing and the architecture in
§1 was decided wrongly. That is the test to write first and the one that would
send us back to JupyMD's sidecar if it fails.

## 7. What this design does not do

Named so the omissions are not read as oversights. `PLUGIN_GOAL.md` Addendum I
defers by name: *"cell and code navigation, running things in the terminal, and
writing updates back to notebooks are explicitly 'later on'"*. Accordingly:

- No cell reordering, folding, or navigation UI.
- No writing back into `.ipynb` files.
- No interactive components inside browser cells (`P-B9` — deferred to tool
  calls in much later iterations).
- The hovering SLM bar is the *next* deliverable (`X-7` step 5), not this one.
  This design only has to hand it a context: an address set from `P-N10`.

## 8. Open questions for the user

1. ~~`P-N2` — what does "switchable" switch?~~ **Answered** — see §4a. The
   switch selects a kernel run in place; a command terminal is what a
   *separate pane* holds.
2. **Does a notebook output belong in retrieval by default?** Making outputs
   trie content (§1) means a `[[]]` query can return a dataframe the reader
   computed. That is either the best feature here or noise in every result set,
   and it should be chosen rather than discovered.
3. **Which interpreter is the default kernel?** The repo runs Python 3.13 from
   the Windows Store package; a notebook inheriting that environment gets
   `domvec` itself on its path, which is useful and also a way to hold the
   kuzu lock from inside a note.
