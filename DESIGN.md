# domvec — the visual contract

Binding for any UI work in `obsidian-plugin/`, by hand or by a design skill
(Impeccable, emil-design-eng, ui-ux-pro-max). **No skill invents a palette,
a font, or a third register.** A skill may critique, simplify, harden and
time motion; it may not restyle. Values here are the ones `styles.css`
ships (read 2026-11-15); where this file and `styles.css` disagree, the
disagreement is a defect to report, not a choice to make.

## Register 1 — the surface (`.domvec-surface`)

Reads as part of the note, not as an embedded app. It follows the reader's
Obsidian theme and defines no colours of its own.

| role | token |
|---|---|
| border | `var(--background-modifier-border)`, 1px, radius 6px |
| bar fill | `var(--background-secondary)` |
| body text | `var(--text-normal)` |
| secondary text | `var(--text-muted)`, `var(--text-faint)` |
| warning (unreachable sidecar) | `var(--text-warning, var(--text-muted))` |
| code / addresses (cid) | `var(--font-monospace)` |
| small text | `var(--font-smaller)` |

Applies to panels, cards, the retrieval cell, chunk views and billboards
(a billboard is a panel at a trie address, NOT a slate —
`docs/GRAPH_WORKBENCH_DESIGN.md`).

## Register 2 — the black slate (`.domvec-slate`, G-278)

Any note with `domvec: slate`. Structure is text: tabs and newlines are the
only markup (`docs/RESERVOIR_DESIGN.md`).

| role | value |
|---|---|
| fill | `#000` |
| border | `1px solid #b8b8b8` (silver) |
| text | `#fff`, `Georgia, "Times New Roman", serif` |
| chrome | none: no inline title, properties, frontmatter or cell bar |
| active line | transparent |
| layout | `tab-size: 3`, `white-space: pre`, no wrapping |
| its one control | the number slider: `#000` fill, `#b8b8b8` border, appears over a hovered number and is gone when left |

## Signal colours (both registers, used sparingly)

Meaning, never decoration: `#7fd0ff` lit / agent-active, `#3fb950` pass,
`#d29922` / `#e3b341` warn, `#ffd27a` / `#fff1a8` highlight. A new signal
needs a stated meaning before it gets a colour.

## Motion

Short and earned: state changes 80-220 ms (`transition` on background,
colour, shadow; glides 220-450 ms in the 3D pane). No decorative motion.
Interruptible gestures (drag, pan, hover-spread) never wait on an
animation to finish.

## What a design skill may and may not do here

- **May**: critique hierarchy and clarity; remove chrome (`distill`); fix
  overflow, z-index collisions, focus traps, empty and error states
  (`harden`); justify and tune easing and timing; check spacing against the
  tokens above.
- **May not**: add colours, fonts, gradients, shadows-as-style or a third
  register; restyle a slate; use a generated score as a pass/fail check.
  A check here is a live probe with a planted defect and a null arm
  (`CLAUDE.md`), never a model's opinion.

## The installed design skills, and where each one stops

Installed 2026-11-15, project-level, copied (`skills-lock.json` pins the
source and hash of each; the copies themselves are not committed).

- **impeccable** (4.9.1). Its Setup step runs `scripts/impeccable context`,
  a launcher that **downloads a platform binary on first run**. That is a
  download needing the user's go-ahead; until it is given, use the skill's
  own "Launcher unavailable" path: read this file directly. Its `live` and
  `generate` modes inject `live-browser.js` into the page -- refused here
  (nothing is written into a page). Its `hooks` detector is not enabled.
  Usable as reading: `distill`, `harden`, `clarify`, `layout`, `audit`,
  `critique` (opinion only, never a gate). The surfaces here are **Operate**.
- **emil-design-eng**: one SKILL.md, motion craft. Bound by the Motion
  section above; it tunes and justifies easing, it does not add motion.
- **ui-ux-pro-max**: local search over CSV/JSON (`scripts/search.py`, no
  network calls found on review). Token-constrained: query one `--domain`
  at a time for a specific check (contrast, touch target, reduced motion);
  never take its palettes, fonts or style picks -- the registers above are
  fixed.
