# Prompt coverage — wave 0 of `docs/AGENT_PLAN.md`

Every verbatim message in `docs/PLUGIN_GOAL.md` (to line ~5140), checked by
five read-only Haiku reviewers against the PRD, the code and the recorded
evidence, 2026-11-02, at `542607b`. The full tables, one row per message,
are in `docs/coverage/part_1.md` .. `part_5.md` (line ranges 1-1030,
1031-2060, 2061-3090, 3091-4120, 4121-end).

These are a reviewer's readings, not verdicts the integrator has checked
one by one. A spot check of part 1 found the cited rows, files and check
dates real. `PLUGIN_GOAL.md` is not in date order past line ~4262 (a
recovered inventory of older messages), so "superseded by" can point at an
earlier line.

## Totals (364 messages)

| verdict | n |
|---|---|
| covered + confirmed (every row Confirm, a passing live check) | 46 |
| covered, unconfirmed | 167 |
| partly built | 99 |
| not built | 7 |
| no row | 28 |
| superseded | 11 |
| contradicted | 6 |

"Covered, unconfirmed" is mostly rows at Done -- built and tested, never
seen working in the running app.

## Verified by hand (2026-11-02, PLUGIN_GOAL 122-126)

Every finding below was read in its context, against the reader's own later
messages by DATE (the file is not in date order), with fixes counted as more
recent than a report when committed after it. The reviewers' verdicts were
wrong or incomplete in 5 of 20 cases.

**Contradicted -- 2 of the 4 stand:**

| case | verdict | why |
|---|---|---|
| freeze (G-145) | **reopened, Defect** | "obsidian froze" 05:58, "frozen again" 06:17 and 06:26 on 2026-10-11, all after the 02:46 Confirm; nothing since answers them |
| xyzhsv rotation (G-156, G-185) | **reopened, Defect** | "rotating xyzhsv stalls out after some time" 2026-10-17, after the 10-11/10-12 Confirms; nothing since |
| duplicates (G-109) | not contradicted | the 2026-10-29 report ("fixes duplication everywhere at the db level") was answered by G-270, Confirm 10-29 20:47 (99,448 -> 59,922 drawn, 0 plain duplicates); no later report |
| archive leakage (G-138, G-216) | not contradicted | the 10-17 leakage report was answered by G-216 at 19:01; the later "archive still not registering correctly" (10-17 23:13) by G-220 (10-18 00:22); the last archive.org messages (10-18: empty tile links, lists cut per bullet) by G-242/G-243/G-244, Confirm the same day; none since |

**No row -- none needs a new row:**

| line | verdict | why |
|---|---|---|
| 3118 arrow keys pan (2026-10-12) | superseded | 4527 (2026-10-29): "arrow keys for camera pan over the focus, coupled with q r for normal, gives full 3 DOF rotational motion control" -- built as orbit about the focus (`useragent.ts:58`) |
| 4413/4417 archive overlays oversized (2026-10-07) | answered, uncited | `da12f24` quotes "Still overlay oversizing": boxes clipped to their own elements, archive cards 258 -> 177 px; `7d14835` pierces shadow roots; G-163's hit test covers archive.org; no later size report |
| 4275 "Reverted to light mode for some reason" (2026-10-04 19:42) | no ask | a passing remark; nothing in the history says what reverted, and the reader never raised it again |

**Superseded -- 10 of 11 stand as stated; one is narrower:**

| ask | verdict |
|---|---|
| 810 drop spherical/quaternion | rescinded at 22:00 the same day (816-818): spherical UMAP STANDS |
| 1312 collapse once transformed | replaced by Addendum IX's order (2026-09-27): a node collapses when SAVED (G-92) -- not by 1462's own words |
| 2281 Voronoi repulsion | dropped as repulsion (2297: "I don't even think we need voronoi"), but 2297 keeps "maybe" a bounded radial telescoping per url that preserves the UMAP (G-115, G-204) -- whether item 107's one global scale replaces that is a question for the reader |
| 1393, 2574, 2577, 2640, 2804, 4366, 4377, 4725 | as the reviewers state; each later message dated after its ask |

## Contradicted — the reviewers' list, before verification

| earlier ask (line) | rows | later report (line) |
|---|---|---|
| dedup makes repeated images shared icons (2187) | G-109 | duplicate node chunks still appear (4472, 2026-10-24) |
| streaming leakage fixed on archive (2549) | G-138, G-216 | archive still throws chunk leakage (3456, 2026-10-17) |
| the app never freezes, fast at tens of thousands of nodes (2617, 2619) | G-145 | frozen again (4430, 2026-10-11) |
| xyzhsv rotation kept, runs with no reader activity (2837, 3058) | G-156, G-185 | rotation stalls after a time (3423, 2026-10-17) |

## No row — features or defects no requirement decomposes

| line | ask |
|---|---|
| 3118 | arrow keys pan the 3D camera |
| 4275 | reverted to light mode (the theme) |
| 4413 | archive overlays oversized |
| 816 | does spherical UMAP work? (a question) |
| 2294 | is a screenshot's "voronoi" look a test artefact or real degradation? (a question) |
| 1661, 4027, 4103 | capture every prompt -- `docs/PROMPT_LEDGER.md`, `docs/PROMPT_INVENTORY.md` exist; no row cites them |

The other 19 are process or logistics remarks ("Try again", "stick to all
tasks", "keep the app open", the agent plan itself), not requirements.

## Superseded — a later message replaced the ask

| ask (line) | replaced by (line) |
|---|---|
| drop spherical/quaternion work (810) | rescinded (818) |
| projected chunks collapse once transformed (1312) | collapse when the store saves (1462) |
| right-click on overlays (1393) | pin on double right-click (1396) |
| Voronoi repulsion (2281) | "probably not needed" (2297) |
| URL node collision sphere (2574, 2577, 2640) | the sphere removed (2664) |
| k never above n (2804) | k shown, n retrieved (3434) |
| hover panels close when hover stops (4366) | persist, expire after a minute (2435) |
| continuous fly-zoom-follow (4377) | zoom once, keep the reader's zoom (2413) |
| markdown trees as a third cell kind (4725) | the markdown cell extended instead (4743) |

## Not built (7)

| line | ask | rows |
|---|---|---|
| 1223 | audit the running app by using it, each finding traced | G-88 |
| 1872, 1902 | open-page layout: overlaps, ring layouts | G-21 (Defect) -- now answered by item 119's strict scale |
| 3840 | through-stack agents, plugin slots | G-239, G-240 |
| 3999 | annas-archive cards chunk on their own boundaries | G-246 |
| 4519 | many non-blocking sidecar micro-processes | G-276 |
| 4657 | docs only for every code artifact | G-52 |
