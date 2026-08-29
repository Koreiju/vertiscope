# domvec — standing instructions

**Read `docs/AFFINE_MAP_GOAL.md` before doing anything else in this repo.** It
holds the binding goal in the user's own words. This file is the short form;
that file wins wherever they differ.

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

3. **Analytics live outside the REPL**, in `domvec/analytics/`, writing their
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

And the specific trap this project keeps falling into: **a coverage number is
a claim about the renderer AND a claim about the denominator, and only one of
them tends to get checked.** Four separate times a correct renderer read as
broken because the denominator did not match what that renderer is for. Before
reporting any number, ask what it is scored against and whether that
denominator is what this component is answerable for.

## Where things are

- `docs/AFFINE_MAP_GOAL.md` — the binding goal, verbatim, plus the metric theory.
- `domvec/analytics/` — the affine-map confusion matrix, ground truth, phase
  timings. Run: `python -m domvec.analytics <url>`. Two scaling harnesses:
  `--delta` (live, a real insertion in a real browser) and `--projection`
  (browser-free, what a change costs the markdown read out of the trie, by
  change kind).
- `domvec/core/js/sensor.js` — the fold. `domvec/trie.py` — the map itself.
- `domvec/markdown.py`, `domvec/wireframe.py` — the two projections.
- `domvec/invariants.py` — `a1` (AAM tables agree), `c1` (three composed-tree
  walks agree), `c2` (the fold reads no layout).

## Verification

`python -m pytest -q` from the repo root. Live-gated tests need
`DOMVEC_LIVE=1`. Always clean up browser processes: a previous session leaked
216 orphaned Firefox processes and took the machine to 1.8 GB free.

**Never run a long corpus while the sensor is being edited.** Doing so mixes
instruments and invalidates the corpus; it has cost four restarts.
