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
   objection `vertiscope/obsidian/mcp.py` already makes in its own docstring about
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
│   [query]()  ← retrieval gesture, unchanged (P-M2, R-1)       │
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
│  PS vertiscope>                                                   │
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

**Built 2026-09-12** as `vertiscope/vault.py` + `Workspace.index_note` +
`vertiscope notes`. Two rows above changed under contact with the code, and both
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

**Verified against the real vault**: `vertiscope notes docs/` indexed 18 documents
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
| 1 | ~~Note addressing~~ **DONE** — `vertiscope/vault.py`, `Workspace.index_note`, `vertiscope notes` | `T-5`: 18 docs -> 786 chunks / 2,697 addresses, and retrieval answers from them. 13 tests, one of them the renderer arm |
| 2 | ~~Fence detection + `▶ run` in both views~~ **DONE** — `src/fences.ts`, `src/runbutton.ts` | both paths draw one button per runnable fence and none on a `json` fence; both fire with the same lang, line and byte-identical source. `probes/run-buttons.js`, 9 checks |
| 3 | ~~Subprocess kernel, python only, per-note state~~ **DONE** — `vertiscope/obsidian/kernel.py`, `_kernel_driver.py`, `POST /kernel` | two cells share a variable and two notes do not, asserted through the button in the running app. 14 pytest + `probes/kernel-run.js` (6 checks) |
| 4 | ~~Output markers written, read, re-rendered~~ **DONE** — `src/outputs.ts` | written after the fence, replaced on re-run, markers invisible in reading view, survives a close and re-read. `probes/cell-outputs.js`, 11 checks |
| 5 | Outputs are chunked and vectorised (`P-N5`/`P-N6`) | **GATE PASSED** — a stored output is addressed `…/output[n]` and retrieves on its own words; the markers do NOT (§4b). Live `[[]]` wiring still to do |
| 6 | ~~Kernel run surface; command terminal in a *separate pane* (§4a); interpreter discovery~~ **DONE** — `vertiscope/obsidian/shell.py`, `src/terminal.ts`, `POST /shell`, `GET /interpreters` | a pwsh prompt in its own pane, `cd` persisting per pane and isolated across them, picker filled from discovery. 11 pytest + `probes/terminal-pane.js` (7 checks) |
| 7 | ~~`P-N8` chunk overlay~~ **DONE** — `vault.chunk_preview`, `POST /chunk_preview`, `src/chunkgutter.ts` | marks match the sidecar's own answer for the same text, and the preview matches what indexing STORES (39 = 39, identical address sets). 5 pytest + `probes/chunk-gutter.js` (6 checks) |
| 8 | `P-N9`/`P-N10` selection → address set → SLM context | the SLM's prompt contains exactly the selected addresses' content |

**What step 7 settled that the design had not.**

- **§5 said "read straight from the trie", and that is wrong for the note on
  screen.** A stored boundary is stale from the first keystroke, and a mark
  confidently in the wrong place answers *"why did my section split"* with last
  week's answer — worse than no mark. So `chunk_preview` computes from the text
  in hand. What makes that safe is that it is the SAME pipeline
  `Workspace.index_note` runs — `tag_note`, `AddressTrie.from_tags`,
  `render_trie` — with the store write left out, so the two agree by
  construction. `test_preview_agrees_with_what_indexing_stores` is the arm that
  holds it there; measured on this document, 39 chunks each side with identical
  `(xpath, part)` sets.
- **A chunk knows its addresses and not its lines.** Only the parse knows both,
  because only the parse is looking at the text — so `tag_note` gained an
  optional `lines_at` out-parameter rather than a second return value, which
  leaves every existing caller unchanged. A paragraph is the one block whose
  extent is unknown when it starts, so its first line is carried rather than
  derived.
- **An inline address has no line of its own.** `…/p[1]/a[1]` is a link written
  inside a paragraph; only blocks are marked. The lookup walks UP a step at a
  time rather than giving up, or every chunk whose first line happened to be a
  link would be dropped.
- **`/chunk_preview` is ungated, deliberately.** Every other POST here acts on
  the world; this one is a pure function of the text it was handed — no write,
  no workspace, no process. Gating it behind `--kernel` would mean a reader
  could not see why their note splits unless they had first enabled code
  execution, a permission with nothing to do with the question.
- **A CM6 gutter renders only the VIEWPORT, and that cost a wrong failure.**
  Counting gutter elements counts what is on screen, not what the editor knows:
  6 starts visible against 9 chunks, with the viewport covering 4,515 of 7,715
  characters, and scrolling changed the count to 5. The probe filters the
  sidecar's chunks to the visible line range before comparing. Nothing was wrong
  with the code.
- **`editor-change` is a reader typing, not a file changing.** The probe's
  "marks follow the text" arm first edited through `vault.modify`, saw nothing
  move, and reported a failure against code behaving correctly for the path it
  is wired to. A note changed on disk by something else does NOT refresh its
  marks — recorded here as a real limitation rather than fixed by widening the
  trigger, since the reader in front of the note is who the gutter is for.
- **Debounced to the pause between words, not throttled.** The boundaries are a
  round trip and a full re-chunk; a throttle would answer *during* typing, which
  is exactly when the answer is worth least.

**What step 6 settled that the design had not.**

- **It is a command RUNNER, not a pty, and that is a choice with a price.** A
  real terminal means ConPTY — `pywinpty` in Python, or `node-pty` plus ~50MB of
  xterm.js in the plugin, which is what every Obsidian terminal plugin carries.
  §4a asks for *"shell work that is not a cell — PowerShell, a build, a git
  command"*, and a persistent shell behind pipes does that with no new
  dependency on a project that guards a four-package runtime list. What it costs
  is stated in `shell.py` rather than left to be met: no cursor control, so a
  progress bar arrives as many lines; no interactive prompts, so `git commit`
  without `-m` waits for input that cannot come; no TUI. `pywinpty` is the
  upgrade path and nothing is shaped to block it — a pty replaces `_Shell`'s
  pipes and keeps the pool and the routes.
- **A sentinel the shell echoes is what says a command finished.** There is no
  other end-of-output signal on a pipe: the process does not close its stdout,
  and a quiet moment is not the same as being done — a slow command would be
  truncated the first time it paused.
- **Refusing is not dying, and the first version conflated them.** The
  `needs-a-terminal` check was raised as `ShellError` from inside the shell's
  own `run()`; the pool treats every `ShellError` as a dead shell, so asking for
  `vim` silently threw away a session holding the reader's `cd`. The check moved
  to the pool, before the command reaches a shell, and returns `refused: true`
  with the session untouched.
- **One gate for the kernel and the terminal, deliberately.** A second flag
  would imply a distinction that does not exist: a Python kernel can already
  call `subprocess.run`, so a reader who enabled it has shell access whether or
  not a terminal pane exists. A permission that looks meaningful and is not is
  worse than no permission.
- **Discovery, never a fixed list.** What can be run is a property of the
  machine, and a hardcoded list is wrong on every machine but the author's —
  wrong *silently*, offering a shell that is not installed and failing at the
  first command. `GET /interpreters` answers even when the kernel is off, so a
  panel can say what *would* be available rather than making "off" and "empty"
  look the same. Jupyter kernels are reported when installed and marked
  `runnable: false`, because this sidecar drives a subprocess and not the
  Jupyter protocol — which is the claim `P-N1` is still `Partial` for.
- **The pane is the session boundary**, as the note is the kernel's. Two
  terminals are two shells and neither moves the other's prompt.
- **A closed pane releases its shell**, and the comment that said otherwise was
  false. `pane` is a fresh random id per view instance, so a reopened pane asks
  for a session that never existed while the old one waits on the LRU — four
  idle PowerShells accumulated across one afternoon. Either the id survives a
  close or the shell does not; releasing is honest about what closing a pane
  means.
- **A standing caveat does not belong in scrollback.** The "no pty" note began
  as a three-line banner in the log, and in a narrow bottom split that is most
  of the viewport: it wrapped, the log overflowed on the first command, and
  every scroll left a half-line against an edge — which reads as a rendering
  fault rather than as scrolled text. It now sits on the bar and on the input's
  tooltip, where it cannot scroll away. Measured after: `scrollHeight` equals
  `clientHeight` in the same pane that overflowed by 10px before.
- **Follow the tail only when already at it.** A reader scrolled up is reading
  something, and yanking them down because a build printed a line takes it away
  mid-sentence.

**What step 4 settled that the design had not — including the gate.**

The gate first, because it is what step 4 was for. §1 chose outputs-in-markdown
over an `.ipynb` sidecar on the argument that an output written into the `.md`
*is* trie content. Tested rather than assumed, on a note carrying a stored
output:

```
/section[1]/h1[1]      text.visible   'Superconductivity notes'
/section[1]/p[1]       text.visible   'Flux pinning measurements.'
/section[1]/code[1]    text.code      'print("critical current density 4.2e6")'
/section[1]/output[1]  text.output    'critical current density 4.2e6'
```

and `vertiscope find "critical current density"` retrieves the note at 0.534.
**§1 was decided correctly.** An `.ipynb` sidecar would have needed a second
parser, a second chunker and a second answer to what address an output has.

- **The markers must be HTML comments, and it was verified before being built
  on.** Obsidian hides them in reading view while rendering what sits between,
  so a note shows its output and not its bookkeeping — and so does GitHub, and a
  PDF export. That property is the whole reason this shape is possible.
- **But comments are not content, and tagging them as prose poisoned the index.**
  The first pass made each marker a paragraph, so `hash=`, `count=` and
  `status=ok` entered the chunk's own text: a search for `"nb-output hash
  status"` retrieved the note, and every notebook note's vector carried the same
  bookkeeping tokens — exactly the in-chunk quality `M-11` says decides how
  representative an embedding is. `vault.py` now skips comments. The output's
  score *rose* from 0.429 to 0.534 once they stopped diluting it.
- **Skipping them then went too far, and the renderer said so.** With the markers
  gone, the output's fence became an immediate `code` sibling of the cell's own
  fence, and `markdown.py` merges adjacent same-label runs — so source and result
  came out as ONE line: `` `print("…") critical current density 4.2e6` ``. The
  markers had been separators as well as metadata. The fix is the label §3
  already named: an output is `text.output` at `…/output[n]`, which separates it
  *and* says what it is, so a reader and an SLM can tell what was run from what
  came back.
- **An unclosed marker costs its line, not the note.** Consuming to the end of
  the document is the tempting reading and it would silently delete every
  address below a truncated write — the note indexed as its first paragraph and
  nothing else. `outputs.ts` takes the same view of an unclosed block.
- **`hash` is `exact_hash`, not `subtree_hash`** (`CLAUDE.md` 5b). An output is a
  projection and prints values verbatim, so it keys on the exact source; a
  content-blind digest would serve the old output for a cell whose string
  literal changed. This is why step 2 had to make both rendering paths agree on
  `cellSource` byte for byte — that agreement is what makes the digest mean one
  thing.
- **The cell is re-found from the file at write time, not trusted from the
  click.** A cell can run for a minute and the reader keeps typing; `req.line`
  was true when the button was pressed. Re-reading under `Vault.process` — one
  read-modify-write lock — is what stops an output landing under the wrong cell
  and what stops a slow cell eating a keystroke.
- **`format=text` is written even though nothing varies it yet**, so a richer
  format arrives without migrating notes already on disk. `text` is also the
  right default rather than a placeholder: stdout is preformatted, and a cell
  printing aligned columns must not have them reflowed.

**Known limitation, stated rather than discovered later:** a cell that prints
markdown gets it stored as `format=text` and shown preformatted, so a dataframe
rendered as a markdown table appears as a table's *source*. Rich formats are
what the `format` field is for.

**What step 3 settled that the design had not.**

- **The kernel lives in the sidecar, and that was the user's call.** The
  alternative was the plugin spawning processes, which means they outlive a
  pane, a plugin reload leaks them, and nothing holds a list of what is running.
  The sidecar is already the one long-lived process, already has a gate for its
  dangerous route, and already answers only on loopback — one door instead of
  two. `GET /kernel` is that list.
- **Two permissions, gated separately.** `--enact` presses a control in a real
  browser; `--kernel` runs arbitrary Python with the sidecar's privileges. One
  flag for both would grant whichever the reader did not want, so there are two,
  both off by default, both advertised on `/health` so the panel can draw a
  button unavailable rather than offering one that 403s. Startup names whichever
  is on, loudly.
- **A blocking `readline` cannot enforce a timeout.** The first version checked
  the clock between reads, and `while True: pass` produces exactly one read that
  never returns — it hung indefinitely with a 2s limit set. `select` does not
  take pipes on Windows, so a watchdog thread kills the process instead, which is
  what we wanted anyway: the cell has to die, and killing it makes `readline`
  return EOF. Two events, not one, because a single flag cannot tell a timeout's
  EOF from a cell that called `os._exit`.
- **A killed sidecar does not orphan kernels**, and the reason is the driver
  reading stdin to EOF: the pipe closes with the parent and the loop ends.
  Measured — four live kernels, `Stop-Process -Force`, zero four seconds later.
  This is why the driver must not block on a socket or poll a queue instead.
- **Replies are marked, because they share stdout with the cell.** `print` is the
  point of a notebook, so a reply on the same stream could not be told from user
  output. Every reply carries a unit-separator prefix and unmarked lines are
  dropped as noise — without that, a cell writing to `sys.__stdout__` kills the
  kernel.
- **Whenever the namespace is not the one the last cell left, the reply says so**
  — started, died, killed on timeout, or evicted, naming which note's kernel was
  retired. A silently-empty variable reads as a bug in the reader's own code.
- **The note is required and never defaulted.** It is the isolation boundary, so
  a default would put every cell in the vault into one namespace — surfacing as a
  mysterious collision between unrelated notes rather than as a missing field.

**What step 2 settled that the design had not.**

- **Two renderers, two implementations, one shared rule.** Reading view gets a
  `MarkdownPostProcessor`; live preview is CodeMirror 6 and needs a widget
  decoration from a `ViewPlugin`. Only *where the fences are* can be shared, and
  it lives in `fences.ts` — mirroring `vertiscope/vault.py`'s `_FENCE` by hand, so
  the editor and the trie cannot disagree about what a fence is. Two spellings
  of one rule is a known defect class here; it is accepted because one side is
  Python in a backend and the other TypeScript in a renderer, and each is stated
  in exactly one place with a comment naming the other.
- **CodeMirror must be `external` in the bundle.** `@codemirror/state` and
  `/view` are obsidian's peer dependencies, so esbuild will happily inline them
  — producing a second CM6 instance whose `Decoration` objects the editor
  silently ignores. No error, no warning, a `ViewPlugin` that never draws.
  `esbuild.config.mjs` now externalises the whole CM6 family, not just the two
  imported today.
- **`syntaxTree` was not used**, because `@codemirror/language` is not among
  obsidian's peer deps and adding a CM6 package of our own is the exact thing
  the externals list exists to prevent. A text scan needs no dependency and
  agrees with the backend by construction.
- **The run button is an allow-list, not a deny-list.** A button on a `json`
  fence promises execution that cannot happen, which is the phantom affordance
  `PLUGIN_PRD` scores against. `vertiscope` fences are excluded by name too: that
  fence already renders an interactive surface.
- **One normalisation of the cell source, found by measurement.** Reading view
  reads `code.textContent` and gets a trailing newline; the live-preview scanner
  joins body lines and does not. The same cell came back `"x = 1
print(x)
"`
  through one path and `"x = 1
print(x)"` through the other. Step 4 keys a
  stored output on a digest of the source, so two spellings mean **switching
  view modes silently invalidates the output and re-runs the cell**. `cellSource`
  is that one spelling, and the probe asserts the two paths agree byte for byte
  rather than merely both firing.

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
   `vertiscope` itself on its path, which is useful and also a way to hold the
   kuzu lock from inside a note.
