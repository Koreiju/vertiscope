# Agent plan — 2026-11-02

How the remaining work is split across Sonnet agents. Drafted for the user's
review before any agent is started. Binding text stays `PLUGIN_GOAL.md` and
`AFFINE_MAP_GOAL.md`; this file is a work breakdown, not a requirement.

## Where things stand (computed, `design_state.md` at `47136aa`)

528 rows: Confirm 240, Done 146, Partly 92, Open 27, Defect 3 (`D-2`, `T-1`,
`G-21`), Superseded 9. Still to build: 88 G-rows, 8 P, 9 R, 6 M, 3 S, 2 D,
2 L, 1 T.

What could NOT be computed mechanically, and is therefore wave 0's job:

- The verbatim's older addenda restart their `(N)` numbering per addendum,
  and their rows cite them by date and quotation, not by number. A script
  matching numbers reports items 1-21 "uncovered" when they are not. Which
  prompts truly have no row cannot be read off the numbers.
- `design_state`'s "where the verbatim record ends" stops at Addendum XI
  (2026-10-18); items 65-117 (2026-11-01/02) sit under headings it does not
  recognise.
- Which earlier rows a LATER prompt changed. Known cases: item 107 (scaled
  map, "keep it simple") against `G-21` (Defect: "nodes never overlap" -- the
  scale leaves up to 2% overlapping), `G-17`/`G-18` (spherical fit,
  quaternion distance), `G-93`/`G-94`/`G-116` (streaming force layout) and
  `G-204` (adaptive scaling about each url's centroid).

## Constraints every agent works under

1. **One running Obsidian, one sidecar.** Live checks cannot run in parallel
   and agents do not run them. Each agent builds in its OWN git worktree,
   runs unit tests (`python -m pytest -q <files>`, `npx tsc --noEmit`), and
   writes its live checks to a scratch `.mjs` (one entry per row, a planted
   arm each). The integrator merges, deploys, reloads, and runs every check
   live, serially, at the end -- which is also what item 117 asks.
2. **File ownership** (merge conflicts are the real cost): each wave below
   names the files an agent may change. `graph.ts`, `main.ts`, `live.mjs`,
   `sidecar.py` and the PRD are shared: an agent edits them only inside the
   regions it owns, and never edits PRD statuses. Those are the integrator's,
   set from live evidence only.
3. **The repo's own rules** (`CLAUDE.md`): describe a change as reads/writes
   on the trie; a planted arm for every metric; name the denominator; nothing
   written into pages; closed shadow roots stay closed; no downloads,
   credentials or outward actions.
4. **Model:** `haiku`, up to ten at once (PLUGIN_GOAL 120), each with a
   strict, file-scoped brief and an explicit output contract.
5. **Ruled 2026-11-02 (PLUGIN_GOAL 119, 121):** the map's scale is STRICT --
   no two mapped nodes overlap, the closest pair just touching -- and no node
   is ever nudged off its fit. `G-21` stands and is met by the scale. Order:
   wave 0 review, the user rules, then the builds.

## Wave 0 — the review (read-only, 3 agents in parallel)

Each reads a third of `PLUGIN_GOAL.md` (by line range) and, for every
verbatim message in it, writes one row to `docs/PROMPT_COVERAGE.md`:

| prompt (file:line) | asks, in a line | rows that decompose it | implemented? (file:line) | evidence (check id / test / measurement) | later prompt that changes it | verdict |

Verdicts: `covered+confirmed`, `covered, unconfirmed`, `partly built`,
`not built`, `no row` (a prompt never decomposed), `superseded by <item>`,
`contradicted by <item>`. The integrator merges the three files and raises
every `no row`, `superseded` and `contradicted` for a ruling before wave 1
builds on them.

## Wave 1 — builds that barely touch `graph.ts` (5 agents, worktrees)

| agent | rows | owns |
|---|---|---|
| **E1 plane & panels** (the user's stated focus) | G-326/G-327 finish + tests, G-329 UI (unnest a selection or a cell into a box panel linked to its source), G-330 type-strict halo, G-325 the per-panel layout register, G-302, G-305, G-311, G-277, G-279 | `planepanels.ts`, `planehalo.ts`, `slatefold.ts`, `cockpit.ts`, new files; RESERVOIR_DESIGN §12 |
| **E2 craft & cockpit** | G-331 glow (pulse hop by hop, cell -> readout -> downstream, plane panels in step), G-333 non-holonomic vehicle + first/third person, G-334 keyboard boundary, G-272/G-273/G-274, G-320 rest | `craft.ts`, `useragent.ts`, the craft hooks in `graph.ts` only |
| **F code artifacts** | G-328 tests, G-233, G-234, G-235, G-236, G-241, G-318 rest (code nodes as an ego-UMAP network), G-317 rest (PageRank over the type graph) | `blackbox.py`, `codegraph.py`, `source.py`, their sidecar routes |
| **C stream & store** | G-195 regression (cause not found), D-40 latency, G-89 C8 intermittent, G-92, G-109, G-193, G-198, G-226, G-253, G-254, G-121, G-217, G-221, D-51, P-B5, S-2 | `browser.ts`, `projector.py`, `sensor.js`, the stream regions of `graph.ts` |
| **M markdown & panels** | M-1..M-6, M-11, P-W1, P-W4..P-W7, G-111, G-114, G-120, G-246, T-2, R-C1..R-C5 | `markdown.py`, `surface.ts`, `htmlform.py` |

## Wave 2 — `graph.ts`-heavy (2 agents, after wave 1 merges)

| agent | rows | owns |
|---|---|---|
| **L layout** | G-324 tests, then the rows wave 0 rules still stand under item 107: G-4, G-19, G-115, G-204, G-208, G-213, G-228, G-245, R-J2, D-12, G-21 | `graph.ts` layout regions |
| **R retrieval** | G-210, G-212, G-222, G-223, G-224, G-231, R-5, R-F2, G-215 | `search.py`, the search regions of `graph.ts` |

## Held for the user (not given to an agent)

Outward-facing or needing permission: `G-165` (rename, new repo, push),
`G-201` (uBlock: a download), `G-237`/`G-262` (model downloads), plus the
architecture and process rows `G-239`, `G-240`, `G-276`, `G-259`, `G-267`,
`G-205`, `G-88`, `G-103`, and RESERVOIR_DESIGN §9 questions 6-9.

## Integration (the integrator, serially)

Merge one worktree at a time -> build -> plugin reload -> sidecar restart if
Python changed -> splice that agent's checks -> run them live (reader idle)
-> Confirm only rows whose clean arm passes and planted arm fails -> commit
with the measurement -> regenerate `design_state.md`.
