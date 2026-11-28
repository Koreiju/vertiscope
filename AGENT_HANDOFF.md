# AGENT_HANDOFF.md — Unified Pivot Direction, Localized Constraints & Parallel Split

*Last updated: `2026-11-28` by Antigravity · Governing verbatim: `docs/PLUGIN_GOAL.md` **Items `200`–`204`** (`2026-11-27`–`2026-11-28`) · PRD: `docs/PLUGIN_PRD.md` (`G-443`–`G-455` Confirm)*

---

## 1. Governing Merge Rule: The Nov 27–28 Pivot Wins

Between `2026-11-25` (Claude's commit `afc636d`, `G-433`–`G-442`) and `2026-11-27`–`2026-11-28` (**Items `200`–`204`**, `G-443`–`G-455`), the user made a decisive architectural pivot. **Wherever earlier Nov 22–25 spec notes (`COMPUTATION_GRAPH_EDITOR_SPEC.md` §12–§14, `O-1`..`O-11`, `G-399..G-442`) differ from Items `200`–`204`, the Nov 27–28 pivot governs.**

### The Four Pillars of the Active Architecture (`Items 200`–`201`)
1. **Pull-Apart Cell-Graph <-> Compiled Panel Dialect (Keep Both Views)**:
   - Individual cells pull apart and together on the graph/plane while remaining regular, editable Obsidian markdown panels with `# Heading` titles and specialized ```` ``` ```` fences (`python`, `browser`, `chat`, `tool`, `terminal`) — **no special purple `slate_N \n \t value` variable stubs**, no `domvec: slate` frontmatter, no custom widget chrome.
   - Visible SVG links join cells via **standard Obsidian markdown links `[cell title](encodeURI(relPath))`** and **direct cross-notebook AST variable dependencies** (`defs -> refs`).
   - **Dialect rule**: Clicking a graph node compiles its containment in sequence (`#` headers containing text chunks + specialized ```` ``` ```` fences) into one unified panel; right-clicking a panel's top header pill (which dynamically mirrors its `# Heading`) pulls apart / folds into the recursive cell-graph view. Collapsing a lone cell attaches it to `domvec/ego.md` under typed `## <Type> cells` headings (`- [title](encodeURI(relPath))`).
2. **Low-Latency VS Code Fenced Interface + "Free" Graph-RAG Small-Model Coding Harness**:
   - All VS Code capabilities (`jedi` + `parso` + PEP-562 module `dir()` + live kernel + cross-notebook AST/CPG) operate strictly **inside ```` ``` ```` code fences** (`fencecode.ts`, `codecell.ts`, `code_intel.py`), leaving markdown prose untouched.
   - Code and tool fences evaluate **only when the cursor exits `[openLine, closeLine]`** (`autorun.ts` `G-449`, zero mid-typing `SyntaxError` runs or `Notice` toast floods; tracebacks render inline in `<!-- nb-output -->`).
   - Top-level variables in one notebook are referenced **directly** in other notebooks without `Vault.read` or `{ref}` syntax, compiled and executed in global topological DAG order (`dataflow.py` + `sidecar.py` `_post_kernel`, `G-451`, closing `O-5`).
   - Standard VS Code static/live symbol resolution + CPG/DAG edges serve as **zero-indexing-cost Graph-RAG** for small local coding models.
3. **Interactive, Recursively-Chunked ```` ```tool ```` Cells & Panel Toolspaces**:
   - Interactive panels (browsers, vertical `[]()` retrieval blocks, terminals, code cells, external toolspaces) expose their actions as **markdown-pure ```` ```tool ```` cells** using slim single-key smolagents dicts:
     `{"browser": {"search": str, "click": str, "next_chunk": bool, "prev_chunk": bool, "back": bool, "forward": bool, "chunks": bool}}`
     with uniform `search`, `back`, `forward`, and `chunks: bool` across toolspaces (`tool_cells.py`, `toolcell.ts`, `G-453`).
   - Setting `"chunks": true` navigates recursively into linked child tool chunks/controls (balancing tool width and depth for quantized context windows).
   - Exiting a ```` ```tool ```` fence or streaming a chat reply executes the tool call in-place, pushes onto a navigable `back`/`forward` stack of model outputs + tool calls, embeds inline markdown instructions for continuous agent steps, and appends compact history directly **above** the ```` ```tool ```` fence inside a vanishing upward scroll (`.domvec-tool-history-fade`) that expands on hover.
4. **Centralized `+ chat`, `ego.md` Default System Prompt, & Multi-Turn `O(delta)` Chat Loop**:
   - `+ chat` lives exclusively in the standardized bottom `+ cell` bar (`cellbar.ts`: `+ code`, `+ terminal`, `+ browser cell`, `+ chat`).
   - `domvec/ego.md` (`## System prompt`) holds the default instructions on instantiating base fences and primary tool calls; each ```` ```chat ```` cell displays/edits its system prompt (defaulting to `ego.md`'s), persists multi-turn history + `O(delta)` SHA-1 deduplicated pinned chunks (`StreamSession`, `G-444`), and supports programmatic streaming into notebooks via `Chat.send(prompt, note=...)` (`G-452`).
   - Inline `[]()` retrieval (`linkgesture.ts`, `G-454`) is a vertical-scroll twin of the 3D `SearchField`, and `panels: fly-to` (`G-445`) flies smoothly to hovered 3D chunk nodes, search hits, and browser panels even after searches and view transitions.

---

## 2. Localized Scope & Hard Boundaries (What to Build vs. What to Leave Alone)

To prevent effort dilution into pre-pivot directions, **both Antigravity and Claude restrict active development to the localized module set in §5** under these rules:

### 2.1 Explicitly Frozen / Superseded Pre-Pivot Threads (Do NOT Expand)
Unless an existing regression check breaks, **spend zero tokens** extending:
- **Purple `slate_N` variable stubs & `domvec: slate` frontmatter** (`G-448` retired them in favor of `# Heading` + ```` ``` ```` fences).
- **`HasTraits` / `traitlets` / `ipywidgets` socket widgets** (`comm.ts`, `nodedefs.ts`, `G-408`/`G-409` "not yet" tails): the active interactive surface is markdown-pure ```` ```tool ```` / ```` ```python ```` / ```` ```chat ```` fences, not custom widget protocols.
- **Curly-brace `{ref}` & `[[wiki]]` link editors** (`editorcalls.ts`, `egocanvas.ts`, `O-3`/`O-6`/`O-7` curly-brace wiring): all cell-to-cell and ego links now use standard `[cell title](encodeURI(relPath))` + direct cross-notebook AST variable names (`egolinks.ts`, `pullapart.ts`, `dataflow.py`).
- **Read-only Python class stub panels as the primary agent surface** (`G-382`): keep `G-421` passing when a bare class name (`Database`, `WebBrowser`) is written in ```` ```tool ````, but build all new agent/panel toolspaces on `G-453`'s interactive dict ```` ```tool ```` schema.
- **Corner `.domvec-plus-chat` badges & floating `.domvec-nbchat` overlays** (`notebookchat.ts`, retired by `G-443`) and **mid-fence timer `AutoRun`** (`G-419` amended to cursor-exit by `G-449`).
- **Unrelated 3D UMAP/streaming geometry & old PRD citation sweeps** (`projector.py`, `pumap.py`, `G-93`/`G-94`, old `R-*` rows) — touch `graph.ts` **only** where it serves `[title](link)` / variable cell-graph links (`G-438` aligned to the new dialect) and `panels: fly-to` (`G-445`).

### 2.2 What Carries Forward Cleanly from Claude's `afc636d` (`G-431`–`G-442`)
- **Named Extension Slots (`slots.ts`, `G-431`/`G-434`/`G-439`)**: Keep registering block/cell features (`codeblock:tool`, `codeblock:chat`, `cell:pull-out`, `cell:complete`) cleanly through `Slots`.
- **Live Kernel Objects & Reactive `ToolRun` (`kernel_objects.py`, `autorun.ts`, `G-412`/`G-413`/`G-437`/`G-440`/`G-441`/`G-442`)**: `WebBrowser`, `Chat.messages` + `Chat.send` + `■ stop`, `Terminal.last`, `Search.last`, and cell-defined smolagents `Tool`s (`agent_tools.py` `cell_tools`) remain first-class building blocks inside fenced Python/chat/agent workflows.
- **Wireframe Docstring Completion (`complete.ts`, `wiredefs.ts`, `G-432`/`G-435`)**: Directly feeds Track A's VS Code Graph-RAG small-model coding harness.

### 2.3 Six Invariants Every Edit Must Preserve
1. **Cursor-exit fence evaluation (`G-449`)**: `AutoRun` (`autorun.ts`) fires **only** when the cursor leaves `[openLine, closeLine]` or on blur. Checks testing reactive runs must move the CM6 cursor outside the fence after editing.
2. **`.domvec-chat-sys` DOM order (`G-422` + `G-452`)**: Keep `.domvec-chat-sys` mounted **after** `.domvec-chat-cell-input` in DOM order in `chatcell.ts` (styled visually first via CSS `order: -1`) so `.domvec-chat-cell textarea` selectors hit the prompt box.
3. **Standard `[title](encodeURI(relPath))` links (`G-446`, `G-448`)**: Never emit `[[wiki]]` links; parse both `[title](path)` and legacy `[[wiki]]` when reading.
4. **`_JEDI_LOCK` & PEP-562 `dir(mod)` (`domvec/code_intel.py`)**: Every Jedi call acquires `_JEDI_LOCK`; keep `_imported_module_attrs` so lazy exports (`np.zeros`, `np.linalg`) resolve in `< 1 ms` without buffer-word pollution.
5. **Post-search `panels: fly-to` (`G-445`)**: Preserve `ensureFlytoReady()` and `onNodeHover` chunk-view fly-to gates in `graph.ts`.
6. **Non-vacuity verification (`CLAUDE.md`)**: Every new/updated `G-*` row gets unit tests + a live check in `obsidian-plugin/checks/live.mjs` with both clean and planted broken arms (`confirm`), followed by `python -m domvec.analytics.design_state`.

---

## 3. Shared Single-Instance Obsidian & MCP Concurrency (`G-455`)

Both agents share **one** running Obsidian window (`CDP :9222`) and **one** sidecar (`.domvec/workspaces/the-fit`, port `8795`) to stay within GPU/RAM limits.

- **Strictly Harness-Enforced (Zero Freehand Coupling)**: Concurrency is managed exclusively by `domvec/obsidian/session_lock.py` (`.domvec/mcp_session.lock` OS kernel byte-range lock + `.domvec/mcp_session.json` process metadata, hot-reloaded via `_FRESH` in `mcp.py`, `live.py`, `controls.py`, and served on `front.py` `/session_lock`). **Never coordinate lock ownership in `AGENT_HANDOFF.md` or any vault markdown file.**
- **Automatic Wait-or-Deliberate-Return**:
  - Read-only tools (`search`, `chunk`, `affordances`, `resolve_address`, `pages`, `design_state`, `live_health`, `sidecar_status`, `verify_state`, `wake`) never block and report `session_lock: {busy, holder_pid, client, op, elapsed_s}`.
  - UI/mutating tools (`confirm`, `plugin_reload`, `ui_act`, `obsidian_eval`, `ui_state`, `app_anomalies`, `graph_probe`, `app_screenshot`, `pipeline_profile`, `graph_motion`, mutating `browse`, lifecycle tools) automatically wait up to `wait_s` (`90s` default, `240s` for `confirm`, overrideable via `session_wait_s`) and run once free (`waited_for_peer_s`), or deliberately return `{ok: false, busy: true, session_lock, retry_after_s}` if still busy.
- **Three Practical Habits**:
  1. **Serialize `npm run build` with the same OS lock** so `main.js` is never overwritten mid-reload of the sibling agent:
     `python -m domvec.obsidian.session_lock --op build --wait 120 -- npm --prefix obsidian-plugin run build`
  2. **Never kill the shared session**: `obsidian_launch` reuses a healthy CDP window automatically (`already_running: true, shared_instance: true`). Avoid `obsidian_close`, `obsidian_launch(force=True)`, or `sidecar_stop` unless recovering a verified crash.
  3. **On `busy: true`**: Continue offline code edits / `pytest` / `node --test`, then check `live_health` and run `confirm` once `session_lock.busy` is `false`.

---

## 4. Git Baseline Snapshot (`2026-11-28`)

- **HEAD**: `afc636d` on `feat/plugin-goal-projector`.
- **Uncommitted Verified Baseline (`G-443`–`G-455`)**: Working tree holds the complete, live-confirmed `G-443`–`G-455` implementation (`19/19` live `confirm` checks green, `33` pytest + `3` node tests green, `0` broken citations in `design_state.md`).
- **Immediate Step 0 (First Agent Up)**: Commit ONLY the `G-443`–`G-455` code/test/doc files cleanly before starting Track A / Track B edits (**do not `git checkout` / `git reset` modified files**, and leave live user vault notes `domvec/ego.md`, `domvec/browser.md`, `domvec/clipboard.md`, `domvec/chunks/`, `domvec/graph/*.md`, `.domvec/`, `.trash/` unstaged):
  - *Docs*: `AGENT_HANDOFF.md`, `docs/PLUGIN_GOAL.md`, `docs/COMPUTATION_GRAPH_EDITOR_SPEC.md`, `docs/PLUGIN_PRD.md`, `build_analytics/design_state.md`, `build_analytics/live_confirmations.md`
  - *Python*: `domvec/agent_tools.py`, `domvec/chat.py`, `domvec/chat_cuda.py`, `domvec/code_intel.py`, `domvec/dataflow.py`, `domvec/tool_cells.py`, `domvec/obsidian/controls.py`, `domvec/obsidian/front.py`, `domvec/obsidian/kernel_objects.py`, `domvec/obsidian/live.py`, `domvec/obsidian/mcp.py`, `domvec/obsidian/session_lock.py`, `domvec/obsidian/sidecar.py`
  - *Plugin TS/CSS*: `obsidian-plugin/src/{autorun,browser,browserpanel,cellbar,chatcell,chatui,cockpit,codecell,codeview,craft,dataflowrun,dfproblems,egolinks,fencecode,graph,linkgesture,main,notebookchat,planepanels,pullapart,runbutton,searchfield,sidecar,slatefold,toolcell}.ts`, `obsidian-plugin/styles.css`
  - *Tests/Checks*: `obsidian-plugin/checks/live.mjs`, `obsidian-plugin/tests/egolinks_fencecode.test.mjs`, `tests/test_chat_sessions.py`, `tests/test_code_intel.py`, `tests/test_cross_notebook_and_tools.py`, `tests/test_mcp_session_lock.py`

---

## 5. Localized Parallel Work Split (100% Centered on the Nov 27–28 Pivot)

Both tracks build directly on `G-443`–`G-455` with clean module ownership and one explicit integration seam (§5.3).

### 5.1 Track A — Antigravity: Fenced VS Code Graph-RAG Coding Harness & Cross-Notebook DAG Engine
*Focus: Item `200 e` + Item `201 b, c, d` ("maximize on vscode helpers for our code interface to properly realize a good small language model coding harness that hacks the graph-rag that comes free from standard vscode tools" + cross-notebook compilation).*

- **Localized Owned Modules**:
  - `domvec/code_intel.py`, `domvec/dataflow.py`
  - `obsidian-plugin/src/fencecode.ts`, `obsidian-plugin/src/codecell.ts`, `obsidian-plugin/src/autorun.ts`, `obsidian-plugin/src/dataflowrun.ts`, `obsidian-plugin/src/dfproblems.ts`, `obsidian-plugin/src/complete.ts`, `obsidian-plugin/src/wiredefs.ts`
- **Work Batches**:
  1. **Batch A1 — VS Code Helper Completeness & Free Graph-RAG Slice Extractor**:
     - Extend `code_intel.py` + `fencecode.ts` + `codecell.ts` with fenced `F2` symbol rename (across cells/notebooks via LibCST/`dataflow.py`), find-references/call-hierarchy lookup, quick-fix missing-import actions, and a `< 10 ms` `graph_rag_context` op harvesting exact definitions, caller/callee neighborhoods, docstrings, and live kernel types across notebooks without any vector re-indexing.
  2. **Batch A2 — Small-Model Fenced Coding & Traceback Self-Repair Harness (Pivot over `G-238`)**:
     - Upgrade `complete.ts` (`wiredefs.ts`) and fenced code actions to feed `code_intel.py`'s free VS Code + CPG/DAG Graph-RAG slice + inline `<!-- nb-output -->` tracebacks into the local quantized coding model for low-latency wireframe completion, inline edit/fix-traceback actions, and cross-notebook symbol reuse.
  3. **Batch A3 — Cross-Notebook Computation Graph Hardening (`G-451` follow-through)**:
     - Extend cross-notebook symbol transfer (`dataflow.py` + `sidecar.py` `_post_kernel`) beyond picklable scalars/arrays to cross-notebook functions/classes (`def`/`class` source/callable binding), add cross-notebook duplicate-definition/cycle markers in `dfproblems.ts`, and skip re-running upstream notebooks whose cell digests + exported bindings are already fresh.

### 5.2 Track B — Claude: Pull-Apart Cell-Graph Dialect, Panel-to-```` ```tool ```` Compilation & Quantized Chat/Tool Loop
*Focus: Item `200 b, c, d` + Item `201 a, e, f, g` ("pulling apart individual cells in their interactive form... recursive compilation over markdown fields... toolspaces on interactive panels defined as their own ```` ```tool ```` cells... continuous call workflows with back/forward stack & vanishing upward history").*

- **Localized Owned Modules**:
  - `domvec/tool_cells.py`, `domvec/chat.py`, `domvec/agent_tools.py`
  - `obsidian-plugin/src/toolcell.ts`, `obsidian-plugin/src/chatcell.ts`, `obsidian-plugin/src/pullapart.ts`, `obsidian-plugin/src/planepanels.ts`, `obsidian-plugin/src/craft.ts`, `obsidian-plugin/src/egolinks.ts`, `obsidian-plugin/src/cockpit.ts`, `obsidian-plugin/src/linkgesture.ts`, `obsidian-plugin/src/browserpanel.ts`, `obsidian-plugin/src/graph.ts` *(ego cell-link & `fly-to` hooks only)*
- **Work Batches**:
  1. **Batch B1 — Seamless Pull-Apart Cell-Graph <-> Compiled Panel Dialect & 3D/2D Ego Links (`G-446`, `G-448`, `G-438` aligned to pivot)**:
     - Harden the two-way commutation across `pullapart.ts`, `planepanels.ts`, `craft.ts`, and `egolinks.ts`: pulling cells apart and clicking a node to compile its `#` heading + ```` ``` ```` containment in sequence; right-clicking the synced `# Heading` pill to fold/pull apart while keeping panels editable in-place with visible `[cell title](encodeURI(path))` and `.is-var-dep` links.
     - Update `egoLinksOf` in `graph.ts` (`G-438`) to read `[cell title](encodeURI(path))` links + cross-notebook variable edges and auto-register/project `vault://` ego cell notes so ego cell-graph links draw live in 3D as well as on the 2D plane.
  2. **Batch B2 — Interactive Panel Toolspaces Instantiated as ```` ```tool ```` Cells (`Item 201` adaptive panel-toolspace bridge)**:
     - Allow open interactive panels (`BrowserView` / `browserpanel.ts`, vertical `[]()` retrieval in `linkgesture.ts`, terminal, notebook cells) to instantiate or bind a live ```` ```tool ```` cell exposing that panel's real actions (`next_chunk`, `prev_chunk`, `search`, `click` on distilled chunk affordances, `back`, `forward`, `chunks: bool`).
     - When `"chunks": true`, procedurally render the active page/panel's interactive chunk controls as linked child ```` ```tool ```` steps navigable via uniform `search` / `back` / `forward` / `chunks`.
  3. **Batch B3 — Continuous Quantized Chat <-> ```` ```tool ```` In-Place Loop & Stack Navigation (`G-444`, `G-452`, `G-453` deepening)**:
     - Tighten continuous multi-step execution between `chatcell.ts` (`ego.md` `## System prompt`, `Chat.send`, `StreamSession`) and `toolcell.ts`: model outputs emitting ```` ```tool ```` or ```` ```browser ```` blocks render and execute in-place, optionally feeding tool markdown + inline tracebacks back for the next turn, with full `back`/`forward` stack inspection over `[model output <-> tool call]` frames and hover-expandable vanishing upward history above the ```` ```tool ```` cell.

### 5.3 Clean Cross-Track Seam (How Track A & Track B Connect)
- **Code Graph-RAG as a Slim ```` ```tool ```` Toolspace**:
  - Track A (`domvec/code_intel.py`) exposes a pure Python helper `code_toolspace_call(action: dict) -> dict` implementing `{"code": {"search": str, "defs": str, "refs": str, "back": bool, "forward": bool, "chunks": bool}}`.
  - Track B (`domvec/tool_cells.py`) plugs `"code"` into `TOOL_SCHEMAS` as one 10-line adapter call once `A1` lands — zero overlapping file edits!
- **Shared Spine Files (Brief Atomic Edits Only, Under `session_lock` Build Wrapper)**:
  - `obsidian-plugin/src/main.ts`, `domvec/obsidian/sidecar.py`, `obsidian-plugin/styles.css`, `obsidian-plugin/checks/live.mjs`, `docs/PLUGIN_PRD.md`, `docs/PLUGIN_GOAL.md`, `AGENT_HANDOFF.md`.

---

## 6. Rolling Sync Log (Keep Entries Procedural & `<= 8` Lines)

| Date | Agent | Batch / Rows | Summary, Verification & Cross-Track Notes |
|---|---|---|---|
| `2026-11-25` | Claude | `G-433`–`G-442` (`afc636d`) | Landed `Slots` (`codeblock:`, `card:`, `cell:`), `completeCell`/`wiredefs`, `Chat.messages` + reply cells + user `Tool`s + `■ stop`, `ToolRun` (`browser`/`chat`/`terminal`/`search`), `G-400`/`G-438` (`Partly`). |
| `2026-11-27` | Antigravity | `G-443`–`G-454` + `G-445` post-search | Landed Items `200`–`201` pivot: bottom `cellbar.ts` `+ chat`, `StreamSession` `O(delta)` multi-turn chat, `panels: fly-to` (3D chunks + browser panels + post-search), `egolinks.ts` `[title](encodeURI(path))`, retired purple `slate_N` stubs, cursor-exit `AutoRun`, warm Jedi + PEP-562 `code_intel.py` (`0.2 ms` attr cache), cross-notebook Python DAG (`G-451`, closes `O-5`), `ego.md` system prompt + `Chat.send`, interactive ```` ```tool ```` cells (`back`/`forward` + vanishing history), vertical `[]()` `SearchField` twin. Live MCP `confirm` **`18/18` PASS**. |
| `2026-11-28` | Antigravity | `G-455` + Pivot Re-Center (`Items 202`–`204`) | Built OS-locked single-instance MCP concurrency (`session_lock.py`, `.domvec/mcp_session.lock`, wait-or-deliberate-busy return, `obsidian_launch` reuse, zero markdown coupling; live `confirm` `G-455` **PASS**). Re-centered `AGENT_HANDOFF.md` strictly on the Nov 27–28 pivot, froze superseded pre-pivot threads (`HasTraits`, `{ref}`, `slate_N`, 3D layout churn), and localized Track A (Fenced VS Code Graph-RAG & DAG) vs. Track B (Pull-Apart Cell-Graph, Panel ```` ```tool ```` Cells & Quantized Chat Loop). |
| `2026-11-28` | Claude | Step 0 (`d38b7e7`) | Committed the `G-443`–`G-455` baseline + Item `205`; pytest `34` pass, egolinks `3/3` from repo root. `node --test` from `obsidian-plugin/` has `7` failures that predate the pivot (`searchfield.test` cannot load `./edgeresize`; address/gesture unchanged since `afc636d`). Taking Track B, Batch B1 next. |
