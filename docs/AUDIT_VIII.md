# Audit VIII — the app, used, against the verbatim

Addendum VIII (2026-09-26) asks for the app to be audited by USING it: the
interactions the design implies, performed in the running app, with their
records kept, including the peripheral changes each one causes; and every
finding traced from the verbatim to what the app actually did. This file is
that record. It is appended to by the audit loop; the newest pass is last.

## The chain

Each user story is one reading of a verbatim sentence. Each is served by
requirement rows, checked by live checks (run inside the plugin, `G-75`),
reachable by MCP tools, and backed by unit tests. The last column is what the
app DID when the story was performed, on a fresh store the run seeded itself
(`G-87`), unless it says otherwise.

| # | user story (verbatim source) | rows | live check · MCP | app, 2026-09-26 |
|---|---|---|---|---|
| U-1 | I see the scan pipeline's statistics as a small black box in the browser's bottom-right corner, and collapse or expand it; so can the MCP tools (VI: *"a simple open/closed scrollable readout"*) | G-76 | `G-76` · `ui_act pipebox` | passes |
| U-2 | Hovering anything on the page outlines the whole chunk that draws it, at its on-screen box, fast, and rings its node (VI: *"matches the cartesian coordinates"*; VII f/u: *"super super slow and inaccurate"*) | G-79, G-38 | `G-79` · `ui_act` | passes: p95 7 ms, extent 0.01 px (`fd09302`) |
| U-3 | Right-clicking pins the chunk: the outline stays, its markdown goes to a side panel beside the page, its billboard opens in the graph and persists with it (VI) | G-78, G-39, G-82 | `G-78`, `G-39` · `ui_act pin` | passes. **Fixed:** the check wanted the page to switch away (a retired design) |
| U-4 | What is pinned follows the page: a change on the page reaches the pinned markdown and the billboard (VI: *"full-span chunk persistence"*) | S-12, G-78 | `S-12` | **was broken, fixed**: the side panel stayed stale (F-3) |
| U-5 | A chunk node shows one picture and opens to the whole chunk (VI) | G-81, G-15 | `G-81`, `G-15` | passes |
| U-6 | Every test runs inside the app, driven by MCP, on real actions (VI: *"hardware in the loop"*) | G-75 | all · `confirm`, `verify_state` | passes; record now merges (F-1) |
| U-7 | Every test suite starts from a fresh, empty store (2026-09-26) | G-87 | `fresh` · `confirm {fresh:true}` | built; 12/12 pages seeded from 0 |
| U-8 | Pages are placed by UMAP of page centroids only (VII) | G-83 | — | gated off; not the default |
| U-9 | Left-click opens a page's whole tree, right-click closes it, links long (VII) | G-84, G-85 | — | not built in the pane |
| U-10 | A heading and the paragraph it heads are one chunk (VII f/u; decisions) | G-86 | — | not built |
| U-11 | O(delta) ms-profile traces, interlaced with the above (VI) | G-73, G-80 | `G-80`, `G-12` | `G-12` passes; `G-80` open |
| U-12 | Every node is on screen at the default camera | G-5 | `G-5` | **fails**: 33 of 41 (F-6) |

Stories U-8..U-10 have rows (added 2026-09-26, `G-82..G-88`) but no check
yet: the verbatim reached `DESIGN_VII.md` and stopped there, where no status
column could see it.

## Findings

**F-1. The record of what was SEEN working forgot on every run.**
`confirm.mjs` replaced `live_confirmations.json` each time, so a three-check
run on 2026-09-26 erased every earlier verdict, and `design_state.md` then
said 135 done rows had no live check. The in-app runners (MCP `confirm`, the
fresh-store runner) never wrote it at all. Fixed: one writer
(`domvec/obsidian/confirmations.py`) that merges by requirement and records,
per verdict, its date, commit and **which store it read**.
`tests/test_confirmations.py`, planted arm: the replace-style write loses the
rows.

**F-2. The checks read a store no current code wrote.** Every check ran
against `build/corpus123`, written over weeks by past sensors, chunkers and
drains, and damaged by each crash. Fixed: `python -m domvec.obsidian fresh`
seeds an empty store through the plugin (the browser cell lands on each page,
exactly the product's path) on a second sidecar, runs the checks, and puts the
plugin back. The working store is never opened. First full run: **29 of 36**;
after the fixes below, the 7 failures are down to 1.

**F-3. A pinned chunk's side panel went stale — a REGRESSION a stale check
hid.** Fixed in the old chunk pane on 2026-09-20; Addendum VI retired that
pane and moved a chunk's forms to a pin, and the refresh did not move with
them. S-12 kept opening the retired pane and failed on "view.show is not a
function", which reads as a harness fault, not a regression. Measured after
rewriting S-12 to the pinned forms, on the old build: side panel 364 chars
before and after the page added an item; billboard 4,873 -> 4,964. Fixed:
the capture's `dirty_cids` re-read each pinned chunk they name, and redraw
each open billboard they name (not only newly placed ones). New build: side
364 -> 455. **Lesson:** when a surface is retired, its checks move with its
DUTIES, or the duty is lost while its check keeps failing noisily.

**F-4. Clean-up deleted pages the check did not make.** S-7 and S-8 purged
fixture pages by FILE NAME, so they deleted the seeded
`shadow_catalogue.html` too and then failed their own "page count unchanged"
(13 -> 12). Invisible on the old store, which had no such page. Fixed: purge
by the check's own fixture origin (a port per check).

**F-5. Three checks asked questions the store could not answer.** G-70
searched the literal "header" (0 hits on a store about trees and tables); G-63
asked about the biggest merge group, a row of book covers with no words, then
about words taken from link targets ("ref-aho") that the lexical index never
held; G-39 demanded a retired face switch. All three now choose from the
store, or assert the current rule; all pass on the fresh store, and each still
fails on the defect it names (G-39: a face switch; G-63: identical rankings).

**F-6. Not every node is on screen (G-5, open).** 33 of 41 after earlier
checks opened pages. The earlier split was page level fine, chunk level 21%
off; the fresh run shows the mixed case. Next pass: reproduce by hand.

**F-7. Same page, same code, different chunk counts.** Seeding the same six
public pages twice, minutes apart, on empty stores: B-tree gave 227 new chunks
once and 205 the other time; every other page matched to the chunk. Either
the page moved or the seeder moves on before a page's capture has finished.
Next pass: two stability maps of B-tree (`--stability`), then compare against
the seeder's "held" signal.

**F-8. The crash does not happen on a fresh store.** D-23 (kuzu segfault in
relationship MERGE) hit `corpus123` every ~2 minutes this afternoon; three
fresh-store runs (seed + 36 checks, and two partial runs) crashed zero times.
A lead on the root cause: store size or state, not load alone.

**F-9. Citation metadata may be leaking into chunk text.** G-63's chosen
words on the fresh store included "Ajournal genre unknown jtitle", which
reads like COinS metadata (Wikipedia's hidden `Z3988` span). Next pass:
resolve that chunk and read its lines.

## Peripheral effects to watch

- A check that opens a view type the plugin no longer registers leaves a
  blank leaf behind (the old S-12 did this every run).
- `fresh` switches the plugin's `sidecar` setting for the run and restores it
  in a `finally`; a run killed from outside leaves the plugin pointed at a
  dead port. The restore is visible in `fresh_run.json` (`previous_sidecar`).
