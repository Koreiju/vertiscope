# vertiscope — standing instructions

**Read `docs/AFFINE_MAP_GOAL.md` before doing anything else in this repo.** It
holds the binding goal in the user's own words. This file is the short form;
that file wins wherever they differ.

**For the Obsidian plugin specifically, read `docs/PLUGIN_GOAL.md`** — the
user's verbatim statement of what the plugin is, which binds the same way and
is broader than the numbered requirements in `docs/PLUGIN_PRD.md`.

## The goal, in one paragraph

The sensor is a **generalized map of shadow DOMs**. The rendering is a full
**affine map** from the original shadow DOM to its distilled, traced,
interactable state in the REPL: what you see in the webpage is what you get in
the REPL. Build a **universal scrape-renderer**, with **chunking and
vectorization asynchronous** from the recursive algorithm that builds the
patricia trie on `url : xpath : markdown : content`. Markdown renders **as the
structure of the page**, embedding markdown and interactive wireframes as
ASCII; the two projections **fuse** to reconstruct the distilled full shadow
DOM — deduplicated, tracked, updated — in **millisecond range** and in
**O(delta)**. Work until it is **fully proven**, not until it looks right.

## Hard constraints

1. **Describe every code change in terms of the patricia trie.** It is the
   universal link structure joining the REPL's data-structure interfaces to
   the web page, and it is a central accessibility constraint on this
   codebase. A change that cannot be stated as "reads from / writes to the
   trie" has left the map, and that is the signal to stop and reconsider.

2. **The REPL is a browser, not a command surface.** Interactive elements are
   *fields* a reader acts on in place, rendered lo-fi and configurable for
   small-language-model context windows. A verb the reader must type is a
   failure of the map. Removing REPL surface that does not serve this is
   explicitly authorised, including things previously called "cool".

3. **Analytics live outside the REPL** (`invariants.c4`, enforced both ways), in `vertiscope/analytics/`, writing their
   own artifacts to `build_analytics/`. A measurement that lives inside the
   thing it measures cannot be trusted after that thing changes.

4. **Time the phases separately**: the in-page mutation-chunking fold
   (`repairMs`), the trie recursion, each projection, and the asynchronous
   embedding phase — plus the total.

5. **The fold reads no layout** (`invariants.c2`). Geometry is a peripheral
   keyed by address, never in the trie.

5b. **Two Merkles, two equivalences — do not confuse them.** `subtree_hash`
   folds in `content_hash` (a normalized token multiset) and answers *"is this
   the same content?"*; `apply` needs that blindness to recognise a paragraph
   that moved. `exact_hash` folds in the exact value and the full address and
   answers *"does this draw the same?"*; every projection memo must key on
   that one, because a projection prints values verbatim. Keying a render on
   `subtree_hash` serves a stale page after any reformatting edit.

5c. **A cached verdict must name what it is a function of.** `rec.tax` is a
   node's class, and the class is part of its address; but `numericFamily`
   decides it by walking four ancestors up and counting anchors, so it is a
   function of a *neighbourhood*, not of the node. Caches keyed on a node and
   invalidated when that node changes will hold such a verdict forever —
   deleting one `<li>` re-classified four Wikipedia links that nothing marked
   dirty, and the trie kept four addresses the page did not have. Before
   memoising anything on a record, write down its actual inputs; if any lie
   outside the node's own subtree, the invalidation has to reach them.

5d. **The classification scan is O(anchors), and it is the one exception to
   O(delta).** `reclassify` walks every anchor on the page when an anchor
   enters or leaves, because a link's class depends on a query over its fourth
   ancestor's subtree. Measured: 7.5ms on a 1,326-anchor page, 1.0ms on a
   55-anchor one. The mask filter keeps the *fold* delta-sized (21 verdicts
   invalidated where an unfiltered sweep would have re-folded ~8,000), so the
   cost is the scan alone. Do not quote O(delta) without this exception.

6. **Closed shadow roots stay closed.** Reaching in means patching
   `attachShadow`, which is detectable and is refused. Report them as
   unreachable so the coverage figure stays honest.

7. **Nothing is written into the page; nothing is transmitted.**

## How to know a measurement is real

Two rules earned the hard way here, both binding:

- **A green suite is not proof.** Detection rates structurally incapable of
  being non-zero, a `forget` that crashed when asked, a composed-tree walk
  that never composed, and a coverage number mixing capture with projection
  all passed a fully green suite.

- **Every metric gets a non-vacuity test.** Assert the *planted defect is
  caught*, not merely that the clean case passes. A check that cannot fail is
  not measuring.

- **Measure the page before blaming the sensor.** Every gesture score needs a
  null arm: the same measurement with no mutation at all. coinmarketcap scored
  10 wrong values under `delete` and the same 10 under nothing, because the
  frozen snapshot still runs a clock. `--drift --kind none` is that arm. A
  score against a moving page is the page's motion plus ours, and they only
  separate if the page alone is measured first.

- **Every page has a resolution limit; measure it before reading a residue.**
  Two independent maps of the same live page, seconds apart, no sensor between
  them — whatever they disagree about is the document moving. w3schools' nine
  stale addresses were all ad-sync iframes; coinmarketcap's were a ticker.
  `python -m vertiscope.analytics --stability --corpus` gives the floor per page,
  and `drift` subtracts it **by name, on the same page load** — a count-vs-count
  comparison would discount real defects, and a floor from another visit would
  discount the wrong addresses.

- **Name the denominator before reading the number, and check it is the one
  that question is answerable for.** Capture is answerable for everything the
  page holds; a projection for what the page lays out. Getting this wrong has
  produced, in one session: 7,043 "invented" capture addresses that were a
  select's options the trie correctly held; a markdown recall of 5.2% for
  collapsing a dropdown as a browser does; an over-dedup of 2,290 for the same;
  115 of 117 pages "exact" where five had been asked nothing; and 133 pages
  credited by a null arm for a question nobody put to them.

  **And the rule is not flat.** Where a measure has two error directions they
  may need different denominators, because they ask different questions. A
  phantom affordance asks *did the REPL invent this?* -- every control the page
  has, drawn or not. A missed one asks *was the reader denied something
  reachable?* -- only what the page draws. One filter for both took missed from
  279 to 2,066 in one direction and phantoms from 8 to 8,701 in the other.

- **A rendering claim must be measured against a corpus rendered by the code
  under test.** A store is not neutral evidence; it is a recording of what some
  past version of the renderer did, and its mtime is part of its meaning.
  `vaultws512` was written 34 minutes BEFORE the commit that fixed the very
  defect it was then used to report — `![images]` was filed as a fresh defect
  three days after `499fd6d` deleted it. The existing rules cover the page
  moving and the denominator being wrong; neither covers the INSTRUMENT having
  changed since the corpus was written. Cheap guard: compare the store's mtime
  against `git log -1 --format=%ad` for the module whose output is being
  scored, before quoting a number.

- **A probe scores the instrument that is LOADED, not the one on disk.** The
  collider probe passed with its own target defect planted, and returned
  numbers identical to the clean run down to a random shuffle landing on 0.004
  twice. It reopened the pane but never reloaded the plugin, so `npm run build`
  had replaced a file nobody was running. The tell was the impossible
  coincidence, not the green. Any probe run against a live app has to reload
  the code under test as its first act, and the cheap audit for one that does
  not is to plant its defect and check the numbers actually MOVE — a pass is
  not evidence, and neither is a fail that reports the same figures.

- **Before writing a measurement, check whether `vertiscope.analytics` already
  answers the question.** Two defects were filed and withdrawn within hours of
  each other on one shared cause: a metric invented for the occasion. One was
  scored against a store older than its own fix; the other used a
  discriminator that could not discriminate — blanking `[n]` from two xpaths
  and calling the collapse an index shift, when any two siblings collapse that
  way. `--resolvable` (does the PAGE hold every address the trie has) and
  `--drift` (mutate, repair, score against a fresh map) existed the whole time
  and were built for exactly these questions. A fresh metric has no
  non-vacuity arm, no null arm, and no history of having been wrong in a known
  way; the harness has all three.

And the specific trap this project keeps falling into: **a coverage number is
a claim about the renderer AND a claim about the denominator, and only one of
them tends to get checked.** Four separate times a correct renderer read as
broken because the denominator did not match what that renderer is for. Before
reporting any number, ask what it is scored against and whether that
denominator is what this component is answerable for.

## Where things are

- `docs/AFFINE_MAP_GOAL.md` — the binding goal, verbatim, plus the metric theory.
- `docs/PLUGIN_GOAL.md` — the plugin's binding goal, verbatim: the opening
  statement plus four dated addenda. II (2026-09-12) overrides I on the
  projector's embedding space, on deduplication and on the panel types; III
  (2026-09-13) poses the S²/S³ colour question and leaves it OPEN; IV
  (2026-09-13/14) adds the second chunking stage, the Electron browser cell,
  the retrieval overlay and the codebase corpus.
- `docs/NOTEBOOK_PANEL_DESIGN.md` — the notebook kernel panel, designed
  against `P-N`/`P-M` before code, per Addendum II's "nail it down
  correctly". Decides outputs-in-markdown over an `.ipynb` sidecar, and
  states the vault-note addressing scheme. Its §8 holds three open
  questions for the user.
- `docs/PLUGIN_PRD.md` — their decomposition, 128 numbered requirements. Part
  I is the contract; Part II is the measured evidence it cites. Read section 0
  first: five of them are DEFECTS, shipped code that contradicts the goal.
- `vertiscope/analytics/` — the affine-map confusion matrix, ground truth, phase
  timings. Run: `python -m vertiscope.analytics <url>`. Two scaling harnesses:
  `--delta` (live, a real insertion in a real browser) and `--projection`
  (browser-free, what a change costs the markdown read out of the trie, by
  change kind).
- `vertiscope/vault.py` — a vault note addressed like a page (`vault://`).
  `vertiscope/source.py` — a source file addressed like a page (`code://`),
  with Python's own tree as the xpath and JavaScript reduced to its
  comments. `G-52` lives one flag away, in `tokens.for_model`: the
  encoder gets docstrings and comments, never the code. 66.2% of this
  repository's rendered tokens are code and are dropped.
- `vertiscope/core/js/sensor.js` — the fold. `vertiscope/trie.py` — the map itself.
- `vertiscope/markdown.py`, `vertiscope/wireframe.py` — the two projections.
- `vertiscope/invariants.py` — `a1` (AAM tables agree), `c1` (three composed-tree
  walks agree), `c2` (the fold reads no layout).

## How a change is shown

Every change ends the same way, so that both sides are looking at one thing:

1. **Commit**, with the measurement in the message.
2. **Confirm it live**, against the running plugin and sidecar:
   `node obsidian-plugin/confirm.mjs`
3. **Regenerate** `build_analytics/design_state.md`:
   `python -m vertiscope.analytics.design_state`
4. **The diff of that file is the report.** It says which requirements moved,
   what evidence moved them, what has been SEEN working, and what is still
   waiting.

The status column is COMPUTED from the PRD, never hand-kept. It was hand-kept
and it drifted sixteen rows in one week -- forty-seven read "Open" while
thirty-one of them had shipped. The cost of computing it is that a verdict has
to say where its evidence is: a file, a probe, a test, or a measurement
section. `design_state.md` lists every "Done" that cites nothing, which is the
only pressure that makes the citation get written. It was 58 of 76 at the
first run.

**Five states, and `Confirm` is the one that was missing.** `Open`, `Partly`,
`Done`, `Defect` -- and `Confirm`, for a row that is built and verified by
test or probe but that no human has seen work in the running app. That gap
existed and was being filled with silence. Nothing leaves `Confirm` except a
person saying so.

**A status column can only drift from the DOCUMENT; the drift that matters
is from the APPLICATION.** `obsidian-plugin/confirm.mjs` holds live checks
keyed by requirement id and writes `build_analytics/live_confirmations.md`,
which `design_state.md` folds in. `G-6` sat in `Confirm` citing "31 nodes and
30 edges" for as long as the debug port was shut; live it was 26 and **0**.
A row absent from that file has not been seen working, whatever its status
says -- 75 done rows are in exactly that position, and the generated state
prints the number.

Two traps this cost, both worth knowing before writing a check:

- **A check that reimplements what it measures can be wrong in either
  direction.** `G-21`'s wrote `drawnRadius` as `sphere * 1.75 * sqrt(2)`
  where the pane uses `sphere * 1.75`, and invented 49 overlapping pairs.
  Call the application's own function.
- **`graphData()` hands back the graph's LIVE arrays, not a snapshot.**
  Holding the object and reading `.length` afterwards reads the after-state
  through it, which reported a working unfold as 122 nodes before and 122
  after. Take counts eagerly.

**A requirement is only as good as the verbatim behind it.** `PLUGIN_GOAL.md`
and `AFFINE_MAP_GOAL.md` hold the user's own words; every numbered row is a
decomposition of those. Where the verbatim record stops, the rows below it are
interpretation with nothing to be checked against -- so new direction is
transcribed into a dated addendum BEFORE it is decomposed into requirements,
and `design_state.md` prints where each record ends.

## Verification

`python -m pytest -q` from the repo root. Live-gated tests need
`VERTISCOPE_LIVE=1`. Always clean up browser processes: a previous session leaked
216 orphaned Firefox processes and took the machine to 1.8 GB free.

**Never run a long corpus while the sensor is being edited.** Doing so mixes
instruments and invalidates the corpus; it has cost four restarts.
