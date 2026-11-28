# AGENT_HANDOFF.md — Unified Pivot Direction, Transcript Links, Localized Constraints & Parallel Split

*Last updated: `2026-11-28` by Antigravity · Governing verbatim: `docs/PLUGIN_GOAL.md` **Items `200`–`207`** (`2026-11-27`–`2026-11-28`) · PRD: `docs/PLUGIN_PRD.md` (`G-443`–`G-455` Confirm, `G-456`–`G-460` Open)*

---

## 0. Mutual Live Session Transcript Links (Synchronize Over User Verbatim)

Both agents have direct read access to each other's local session transcripts to cross-check the user's exact prompts and recent work without relying on summaries alone:

- **Antigravity Session Transcript (`da8388bf-0c82-4ab2-8afb-6e18a32d9c78`)**:
  - **Compact JSONL (read tail / grep user messages here first)**:
    `C:\Users\isaac\.gemini\antigravity\brain\da8388bf-0c82-4ab2-8afb-6e18a32d9c78\.system_generated\logs\transcript.jsonl`
  - **Full JSONL (read only specific line numbers when `truncated_fields` is present)**:
    `C:\Users\isaac\.gemini\antigravity\brain\da8388bf-0c82-4ab2-8afb-6e18a32d9c78\.system_generated\logs\transcript_full.jsonl`
- **Claude Code Session Transcripts (`domvec` project)**:
  - **Transcript directory** *(always check newest `*.jsonl` by `LastWriteTime` in case Claude opened a fresh session)*:
    `C:\Users\isaac\.claude\projects\C--Users-isaac-Documents-domvec\`
  - **Latest transcript on disk (`27.2 MB`, `7,714+` lines — read tail slices / filter `type == "user"`, never read whole file into context)**:
    `C:\Users\isaac\.claude\projects\C--Users-isaac-Documents-domvec\a9b349a5-0dd5-48a8-b034-fa7ab3b206b4.jsonl`

> **Transcript Hygiene**: Both `.jsonl` logs are multi-megabyte files. Always inspect the tail lines via Python/shell filters (extracting user turns and recent commit/check summaries) + `docs/PLUGIN_GOAL.md` (`Items 200`–`205`) rather than dumping raw `.jsonl` blobs into context.

---

## 1. Governing Merge Rule: The Nov 27–28 Pivot (`Items 200`–`205`) Wins

Between `2026-11-25` (Claude's commit `afc636d`, `G-433`–`G-442`) and `2026-11-27`–`2026-11-28` (**Items `200`–`205`**, `G-443`–`G-460`), the user made a decisive architectural pivot. **Wherever earlier Nov 22–25 notes (`COMPUTATION_GRAPH_EDITOR_SPEC.md` §12–§14, `O-1`..`O-11`, `G-399..G-442`) differ from Items `200`–`205`, the Nov 27–28 pivot governs.**

### The Five Pillars of the Active Architecture (`Items 200`–`205`)
1. **Pull-Apart Cell-Graph <-> Compiled Panel Dialect & Cursor-Gated ```` ```chunk ```` Web Unification (`G-446`, `G-448`, `G-456`)**:
   - Individual cells pull apart and together on the graph/plane while remaining regular, editable Obsidian markdown panels with `# Heading` titles and specialized ```` ``` ```` fences (`python`, `browser`, `chunk`, `chat`, `tool`, `terminal`) — **no purple `slate_N \n \t value` variable stubs**, no `domvec: slate` frontmatter.
   - Visible SVG links join cells via **standard markdown links `[cell title](encodeURI(relPath))`** and **direct cross-notebook AST variable dependencies** (`defs -> refs`). Clicking a graph node compiles its `#` heading + ```` ``` ```` containment into one unified panel; right-clicking a panel's synced `# Heading` pill pulls apart / folds into the cell-graph view; lone collapsed cells attach to `domvec/ego.md` under typed `## <Type> cells` headings.
   - **Web chunks unify with standard editor cells (`G-456`, Item `205 a`)**: cell-wise ```` ```chunk ```` / ```` ``` ```` notation renders raw distilled markdown + the chunk's interactive affordances as inline ```` ```tool ```` cells when the **cursor is inside** the fence, and renders the actual distilled page/HTML view (`htmlform` / snapshot) when the **cursor is outside**, interlacing tool calls uniformly across browsers, web chunks, language-model cells, and composed agent cells.
2. **Minimal "Gym" Python Programming Interface Mirroring Every ```` ```tool ```` Cell (`G-457`, `G-458`, Item `205 b–c`)**:
   - **The programming gym environment replaces the graphical node-port editor**: every ```` ```tool ```` toolspace doubles as a minimal, intuitive Python API in the kernel (`Browser.chunks` with BeautifulSoup-style `find`/`select`/`.text`/`.links`/`.controls` and inlaid `.click()`/`.fill()`/`.next_chunk()`/`.prev_chunk()`, plus fluent Selenium-style `ActionChain` routines `Browser.chain()...perform()`, alongside symmetric minimal APIs for `Search`, `Chat`/LM cells, and `Tools`).
   - **`domvec/ego.md` has NO fancy per-view cockpit features (`G-458`, amending `G-418`)**: `ego.md` is represented purely as a **canonical notebook example** — the readable amalgam of minimal Python programming interfaces + inline docs/system-prompt examples for the full toolspace (plus typed `## <Type> cells` links from `G-446`).
3. **Ephemeral Library UI vs. Artifact-Scoped Procedural ```` ```tool ```` Interlacing & Embedding-Scoped Code RAG (`G-447`, `G-449`–`G-451`, `G-459`, `G-460`)**:
   - Low-latency VS Code helpers (`jedi` + `parso` + PEP-562 `dir()` + live kernel + cross-notebook AST) run strictly inside ```` ``` ```` code fences; evaluation fires **only on cursor exit** (`G-449`, inline tracebacks, zero mid-typing `SyntaxError` toast floods); top-level variables cross notebooks directly via global topological DAG compilation (`G-451`, closes `O-5`).
   - **Library suggestions stay strictly ephemeral (`G-459`)**: third-party/stdlib autocomplete popups never materialize into procedural tool cells or store rows. **Procedural ```` ```tool ```` calls** apply strictly to workspace/notebook code artifacts and interactive cells — turning documented notebooks/modules into dual Python API + ```` ```tool ```` surfaces bridging user, agents, and code.
   - **Embedding-model-scoped docstring + artifact-link RAG (`G-460`)**: procedural code/docstring retrieval is an embedding-model-scoped layer of DB search paired with code-editing tools that follow both docstrings AND module/markdown `[title](link)` + cross-notebook AST links.
4. **Interactive, Recursively-Chunked ```` ```tool ```` Cells (`G-453`)**:
   - Slim single-key smolagents dicts (`{"browser": {"search": str, "click": str, "next_chunk": bool, "prev_chunk": bool, "back": bool, "forward": bool, "chunks": bool}}`, uniform `search`/`back`/`forward`/`chunks: bool` across toolspaces) with inline markdown instructions, `"chunks": true` recursive child navigation, cursor-exit & chat-reply in-place execution, `back`/`forward` stack over `[model output <-> tool call]` frames, and compact vanishing-upward history (`> \`HH:MM:SS\` ...`) directly above the ```` ```tool ```` fence.
5. **Centralized `+ chat`, Multi-Turn `O(delta)` Chat, Vertical `[]()` Twin, & `panels: fly-to` (`G-443`–`G-445`, `G-452`, `G-454`)**:
   - `+ chat` sits exclusively in the bottom `cellbar.ts` (`+ code`, `+ terminal`, `+ browser cell`, `+ chat`); `StreamSession` (`G-444`) persists multi-turn history + SHA-1 deduplicated pinned chunks; `Chat.send` (`G-452`) streams into notebooks; `[]()` (`G-454`) mirrors 3D `SearchField` vertically; `panels: fly-to` (`G-445`) stays active across 3D chunks, search hits, and browser panels even after searches.

---

## 2. Localized Scope & Hard Boundaries (What to Build vs. What to Leave Alone)

### 2.1 Explicitly Frozen / Superseded Pre-Pivot Surfaces (Spend Zero Tokens Here)
Unless an existing regression check breaks, **do NOT expand**:
- **Graphical node-port / `HasTraits` / `ipywidgets` editors** (`comm.ts`, `nodedefs.ts`, `G-408`/`G-409` socket widgets) — explicitly replaced by the minimal Python gym API + ```` ```tool ```` cells (**Item `205`**).
- **Special per-view cockpit features on `ego.md`** (`view =`, `camera =`, `throttle =` view-controller gimmicks — **Item `205`** replaces them with `ego.md` as a plain reference notebook example, while keeping `G-418` backward-compatible only behind existing check hooks if needed).
- **Purple `slate_N` variable stubs & `domvec: slate` frontmatter** (`G-448`), **curly-brace `{ref}` / `[[wiki]]` link editors** (`editorcalls.ts`, `egocanvas.ts`), **corner `.domvec-plus-chat` / `.domvec-nbchat`** (`G-443`), and **mid-fence timer `AutoRun`** (`G-449`).
- **Procedural tool generation over external libraries** (`G-459` rules library completions strictly ephemeral).
- **Unrelated 3D UMAP/streaming geometry & old PRD citation sweeps** (`projector.py`, `pumap.py`, `G-93`/`G-94`, old `R-*` rows) — touch `graph.ts` **only** for `[title](link)` / variable ego cell-graph links and `panels: fly-to`.

### 2.2 Six Invariants Every Edit Must Preserve
1. **Cursor-exit fence evaluation & rendering commutation (`G-449`, `G-456`)**: `AutoRun` (`autorun.ts`) fires **only** when the cursor leaves `[openLine, closeLine]` or on blur; ```` ```chunk ```` shows markdown/tools when cursor is inside and rendered page when outside.
2. **`.domvec-chat-sys` DOM order (`G-422` + `G-452`)**: Keep `.domvec-chat-sys` mounted **after** `.domvec-chat-cell-input` in DOM order in `chatcell.ts` (`order: -1` in CSS) so `.domvec-chat-cell textarea` hits the prompt input.
3. **Standard `[title](encodeURI(relPath))` links (`G-446`, `G-448`)**: Never emit `[[wiki]]` links; parse both `[title](path)` and legacy `[[wiki]]` when reading.
4. **`_JEDI_LOCK` & ephemeral PEP-562 `dir(mod)` (`domvec/code_intel.py`, `G-450`, `G-459`)**: Acquire `_JEDI_LOCK` on every Jedi call and keep library member completions ephemeral in memory (`clientAttrCache` / `_ATTR_CACHE`).
5. **Post-search `panels: fly-to` (`G-445`)**: Preserve `ensureFlytoReady()` and `onNodeHover` chunk-view fly-to gates in `graph.ts`.
6. **Non-vacuity verification (`CLAUDE.md`)**: Every `G-*` row requires unit tests + live `checks/live.mjs` clean & planted broken arms via MCP `confirm`, followed by `python -m domvec.analytics.design_state`.

---

## 3. Shared Single-Instance Obsidian & MCP Concurrency (`G-455`)

Both agents share **one** running Obsidian window (`CDP :9222`) and **one** sidecar (`.domvec/workspaces/the-fit`, port `8795`).

- **Strictly Harness-Enforced (Zero Freehand Coupling)**: Managed exclusively by `domvec/obsidian/session_lock.py` (`.domvec/mcp_session.lock` OS kernel lock + `.domvec/mcp_session.json` metadata, hot-reloaded via `_FRESH` in `mcp.py`, `live.py`, `controls.py`, and served on `front.py` `/session_lock`). **Never write/read lock state in `AGENT_HANDOFF.md` or vault markdown.**
- **Wait-or-Deliberate-Return**: Lock-free read tools (`search`, `chunk`, `affordances`, `resolve_address`, `pages`, `design_state`, `live_health`, `sidecar_status`, `verify_state`, `wake`) never block; UI/mutating tools wait up to `wait_s` (`90s` default, `240s` for `confirm`, overrideable via `session_wait_s`) and proceed once free (`waited_for_peer_s`), or return `{ok: false, busy: true, session_lock, retry_after_s}`.
- **Three Shared Habits**:
  1. Wrap CLI builds in the OS lock so `main.js` is never overwritten mid-reload:
     `python -m domvec.obsidian.session_lock --op build --wait 120 -- npm --prefix obsidian-plugin run build`
  2. Never kill the shared window (`obsidian_launch` reuses healthy CDP automatically; avoid `obsidian_close` / `sidecar_stop` unless recovering a verified crash).
  3. On `busy: true`, continue offline code/tests and retry once `live_health.session_lock.busy` is `false`.

---

## 4. Git Baseline Snapshot (`2026-11-28`)

- **HEAD**: `d38b7e7` / `07ca620` on `feat/plugin-goal-projector` (Claude completed **Step 0**, committing the verified `G-443`–`G-455` baseline cleanly).
- **Live Vault Notes**: Leave live user vault notes (`domvec/*.md`, `domvec/graph/*.md`, `domvec/chunks/`, `.domvec/`, `.trash/`) unstaged when committing code/test/doc batches.

---

## 5. Localized Parallel Work Split (`Items 200`–`205`)

### 5.1 Track A — Antigravity: Cursor-Gated ```` ```chunk ```` Unification, Minimal Gym Python API, `ego.md` Notebook Example, & Artifact-Scoped Code/Tool RAG (`G-456`–`G-460`)

- **Localized Owned Modules**:
  - `domvec/code_intel.py`, `domvec/dataflow.py`, `domvec/obsidian/kernel_objects.py`
  - `obsidian-plugin/src/fencecode.ts`, `obsidian-plugin/src/codecell.ts`, `obsidian-plugin/src/chunkcell.ts` *(new for `G-456`)*, `obsidian-plugin/src/autorun.ts`, `obsidian-plugin/src/dataflowrun.ts`, `obsidian-plugin/src/dfproblems.ts`, `obsidian-plugin/src/complete.ts`, `obsidian-plugin/src/wiredefs.ts`, `obsidian-plugin/src/cockpit.ts` *(for `G-458` plain notebook example)*
- **Work Batches**:
  1. **Batch A1 — Cell-Wise Cursor-Gated ```` ```chunk ```` Web/Editor Unification (`G-456`)**:
     - Build standardized ```` ```chunk ```` cell-wise rendering keyed by patricia-trie address: cursor **inside** the fence shows/edits raw distilled markdown + inline ```` ```tool ```` cells for the chunk's interactive affordances; cursor **outside** renders the live distilled page/HTML view (`htmlform` / snapshot), unifying billboard/web chunks (`busy_feed.html`, Wikipedia, etc.) with regular notebook editor cells.
  2. **Batch A2 — Minimal "Gym" Python API (`Browser.chunks` Soup + `ActionChain`) & `ego.md` as Plain Reference Notebook (`G-457`, `G-458`)**:
     - Implement the minimal gym Python API in `kernel_objects.py` mirroring every ```` ```tool ```` toolspace: `Browser.chunks` (BeautifulSoup-like `find`, `select`, `.text`, `.links`, `.controls` with inlaid `.click()`, `.fill()`, `.next_chunk()`, `.prev_chunk()`) + fluent Selenium-style `Browser.chain()...perform()`, plus symmetric minimal Python mirrors for `Search`, `Chat`/LM cells, and `Tools`.
     - Simplify `domvec/ego.md` (`cockpit.ts`, `egolinks.ts`) into a clean **notebook example** showcasing the full toolspace Python APIs + ```` ```tool ```` / ```` ```chunk ```` / ```` ```chat ```` markdown docs + typed `## <Type> cells` links, retiring fancy per-view ego cockpit features while keeping legacy check flags intact.
  3. **Batch A3 — Notebook/Module <-> ```` ```tool ```` Interlacing, Ephemeral Library UI, & Embedding-Scoped Docstring/Link Code RAG (`G-459`, `G-460`)**:
     - Expose documented workspace notebooks and Python modules simultaneously as cross-notebook Python callables (`G-451`) and ```` ```tool ```` schemas (`signature` + docstrings + context notes), while keeping external library completions (`numpy`, stdlib) strictly ephemeral UI.
     - Add embedding-model-scoped docstring/code DB search + cross-notebook code-editing tools (`F2` rename, find-references, docstring + `[title](link)` + AST graph traversal) in `code_intel.py` / `complete.ts`.

### 5.2 Track B — Claude: Pull-Apart Cell-Graph Dialect, Panel-to-```` ```tool ```` Canvas Interlacing & Continuous Quantized Chat/Agent Tool Loop

- **Localized Owned Modules**:
  - `domvec/tool_cells.py`, `domvec/chat.py`, `domvec/agent_tools.py`
  - `obsidian-plugin/src/toolcell.ts`, `obsidian-plugin/src/chatcell.ts`, `obsidian-plugin/src/pullapart.ts`, `obsidian-plugin/src/planepanels.ts`, `obsidian-plugin/src/craft.ts`, `obsidian-plugin/src/egolinks.ts`, `obsidian-plugin/src/linkgesture.ts`, `obsidian-plugin/src/browserpanel.ts`, `obsidian-plugin/src/graph.ts` *(ego `[title](link)` / variable cell-graph & `fly-to` hooks only)*
- **Work Batches**:
  1. **Batch B1 — Seamless Pull-Apart Cell-Graph <-> Compiled Panel Dialect & Live 3D/2D Ego Links (`G-446`, `G-448`, `G-438` aligned to pivot)**:
     - Harden two-way commutation across `pullapart.ts`, `planepanels.ts`, `craft.ts`, and `egolinks.ts`: pulling cells apart on the plane/graph with visible `[cell title](encodeURI(path))` and `.is-var-dep` SVG links, clicking a node to compile its `#` heading + ```` ``` ```` (`python`, `browser`, `chunk`, `chat`, `tool`) containment in sequence, right-clicking the synced `# Heading` pill to fold/pull apart, and wiring `egoLinksOf` in `graph.ts` so `[title](link)` + variable edges draw live in 3D without manual ingest.
  2. **Batch B2 — Per-Cell & Canvas Interactive ```` ```tool ```` Interlacing (`Item 201` + `Item 205` tool-cell side)**:
     - Wire interactive panels (`browserpanel.ts`, `linkgesture.ts`, terminal, language-model/agent cells) to instantiate and synchronize ```` ```tool ```` cells whose slim dict schemas (`search`, `click`, `next_chunk`, `prev_chunk`, `back`, `forward`, `chunks: bool`) mirror Track A's Python gym API 1-for-1; when `"chunks": true`, procedurally render linked child chunk/control ```` ```tool ```` steps in-place.
  3. **Batch B3 — Continuous Quantized Chat & Composed Agent <-> ```` ```tool ```` Loop (`G-444`, `G-452`, `G-453` deepening)**:
     - Compose language-model / agent cells (`chatcell.ts`, `agent_tools.py`, `toolcell.ts`) as ```` ```tool ````-callable & ```` ```tool ````-emitting cells: streamed model replies emitting ```` ```tool ````, ```` ```chunk ````, or ```` ```browser ```` blocks execute and re-render in-place, navigate `[model output <-> tool call]` frames via `back`/`forward`, and maintain compact hover-expandable vanishing upward history above ```` ```tool ````.

### 5.3 Clean Cross-Track Seams
1. **1-to-1 Schema Parity (`G-453` <-> `G-457` / `G-459`)**: Every Python gym method in `kernel_objects.py` (`Browser.chunks`, `Search`, `Chat`, `Tools`, plus notebook/module tools in `code_intel.py`) maps 1-to-1 onto a single-key dict in `domvec/tool_cells.py` (`{"browser": ...}`, `{"search": ...}`, `{"code": ...}`, `{"notebook.<name>": ...}`).
2. **`ego.md` (`cockpit.ts` / `egolinks.ts`)**: Track A owns replacing `cockpit.ts`'s per-view settings template with the plain reference notebook example (`G-458`), preserving `egolinks.ts`'s `## System prompt` (`G-452`) and `## <Type> cells` (`G-446`) sections that Track B reads/writes.

### 5.4 Claude's Pre-Pivot Rows Mapped onto the Pivot (Item `206`)
Each open row from Claude's Nov 22-25 work, read against Items `200`-`201`:

| Pre-pivot row | Pivot verbatim it now serves | Goes to | Concretely |
|---|---|---|---|
| `G-438` ego links seen drawing (Partly) | 200 "deeper connectivity between our cell graph" | **B1** | `egoLinksOf` already reads `[title](path)`; add `dataflow.py` cross-notebook defs->refs edges as a second edge kind; keep `{ref}` read-only (legacy) |
| `G-413`/`G-440`/`G-441` live objects `Terminal.last`, `Search.last`, `WebBrowser` | 201 "toolspaces on interactive panels ... defined as their own cells" | **B2** | the `terminal`/`search`/`browser` entries of `TOOL_SCHEMAS` READ these same objects, so a ` ```tool ` cell and a python cell see one state; the `ToolRun` re-run doubles as the tool cell's refresh |
| `G-412`/`G-442` `Chat.messages`, `■ stop` | 201 "tool call cells on chat model cells ... streamed to their markdown notebooks" | **B3** | a stop aborts a chat->tool chain mid-step; `Chat.messages` gives the next turn its tool frames |
| `G-437` cell-defined `Tool`s (`cell_tools`) | 201 "smolagents tool interfaces to stay slim" | **B3** | a note's own `Tool`s join `TOOL_SCHEMAS` as slim dict toolspaces, listed under `chunks: true` |
| `G-240`/`G-431`/`G-439` slots | 201 "everything ... as cells" | **B2** (mechanism) | each new toolspace registers through `Slots` (`codeblock:tool` sub-kinds); retire the dead `card:plus-chat` slot (`G-443` gated it off) |
| `G-238` graph RAG; `G-432`/`G-435` complete | 201 "graph-rag that comes free from standard vscode tools" | **Track A** (A1/A2) | Claude consumes it only through the `"code"` toolspace seam (§5.3) |
| `G-400` own UMAP / sprites; `G-409` trait widgets; `G-412` comm deltas | -- (no pivot sentence) | **frozen** (§2.1) | regressions only |
| `G-403` hold-drop, `G-433` tabs<->plane drag | 201 "pulls cells together and apart" | **B1**, needs the user | re-check under the `# Heading` dialect, then the user tries them by hand |

Order for Claude: **B1 -> B2 -> B3**. B2's terminal/search toolspaces need no Track A code; the `"code"` toolspace waits on A1.

---

## 6. Rolling Sync Log (Keep Entries Procedural & `<= 8` Lines)

| Date | Agent | Batch / Rows | Summary, Verification & Cross-Track Notes |
|---|---|---|---|
| `2026-11-25` | Claude | `G-433`–`G-442` (`afc636d`) | Landed `Slots` (`codeblock:`, `card:`, `cell:`), `completeCell`/`wiredefs`, `Chat.messages` + reply cells + user `Tool`s + `■ stop`, `ToolRun` (`browser`/`chat`/`terminal`/`search`), `G-400`/`G-438` (`Partly`). |
| `2026-11-27` | Antigravity | `G-443`–`G-454` + `G-445` post-search | Landed Items `200`–`201` pivot: bottom `cellbar.ts` `+ chat`, `StreamSession` `O(delta)` multi-turn chat, `panels: fly-to` (3D chunks + browser panels + post-search), `egolinks.ts` `[title](encodeURI(path))`, retired purple `slate_N` stubs, cursor-exit `AutoRun`, warm Jedi + PEP-562 `code_intel.py` (`0.2 ms` attr cache), cross-notebook Python DAG (`G-451`, closes `O-5`), `ego.md` system prompt + `Chat.send`, interactive ```` ```tool ```` cells (`back`/`forward` + vanishing history), vertical `[]()` `SearchField` twin. Live MCP `confirm` **`18/18` PASS**. |
| `2026-11-28` | Antigravity | `G-455` + Pivot Re-Center (`Items 202`–`204`) | Built OS-locked single-instance MCP concurrency (`session_lock.py`, `.domvec/mcp_session.lock`, wait-or-deliberate-busy return, `obsidian_launch` reuse, zero markdown coupling; live `confirm` `G-455` **PASS**). Re-centered `AGENT_HANDOFF.md` strictly on the Nov 27–28 pivot, froze superseded pre-pivot threads (`HasTraits`, `{ref}`, `slate_N`, 3D layout churn), and localized Track A vs. Track B. |
| `2026-11-28` | Claude | Step 0 (`d38b7e7`) | Committed the `G-443`–`G-455` baseline + Item `205`; pytest `34` pass, egolinks `3/3` from repo root. `node --test` from `obsidian-plugin/` has `7` failures that predate the pivot (`searchfield.test` cannot load `./edgeresize`; address/gesture unchanged since `afc636d`). Taking Track B, Batch B1 next. |
| `2026-11-28` | Claude | Item `206` (`ff23e49`) | Mapped open pre-pivot rows onto Items `200`–`201` in `AGENT_HANDOFF.md` §5.4 (`B1 -> B2 -> B3`). |
| `2026-11-28` | Antigravity | Item `207` (`G-456`–`G-460` + Transcript Cross-Links) | Added mutual `.jsonl` session transcript links (§0), recorded Item `207` verbatim, and decomposed `G-456`–`G-460` onto Track A (cursor-gated ```` ```chunk ```` web/editor unification, minimal gym Python API `Browser.chunks` + `ActionChain`, `ego.md` as plain toolspace notebook example, ephemeral library UI vs. notebook/module <-> ```` ```tool ```` interlacing, embedding-model-scoped docstring + artifact-link RAG), keeping Track B's seams aligned. |
