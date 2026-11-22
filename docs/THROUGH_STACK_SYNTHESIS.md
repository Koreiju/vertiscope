# What the through-stack design leaves us — a synthesis against the running APIs

*2026-11-22. Asked for after PLUGIN_GOAL 179 deprecated the through-stack
idea: "try synthesizing the themes and ideas from the design to our current
design to see if we can make use of any of the findings as interlaced with
existing APIs, whether ones we've documented or not." Every claim below names
the code it was read from. Readings are marked as mine.*

The through-stack bundled six themes. Each one, read against what the
running system already exposes:

## 1. Theme by theme

### 1a. Typed calls with a promise: "type + check cell" (179, kept)

| half of the promise | what already exists | where | documented? |
|---|---|---|---|
| the declared **type** | every model ROLE fixes its input and output types and a parser; a parse failure is a `TypedResult` with `error`, never coerced | `domvec/models.py` `ROLES`, `TypedResult`, `parse_triplex`, `parse_chat` | GRAPH_WORKBENCH_DESIGN §4 |
| strict **data types** | pydantic models mined from trie-path patterns, `strict=True, extra="forbid"` | `domvec/typegen.py` (G-388) | yes |
| the **check** | a notebook cell's output carries the hash of its exact source; an edit marks it stale | `agent_step.py`, `outputs.ts` (`nb-output hash=`) | yes |
| **auto-update** | the cells a change makes stale, from the note's own text | `/dataflow` -> `dataflow.rerun_plan` (G-380) | yes |
| a **validated transformation** | a CPG mutation compiled back to source, compile-checked, applied as a unified diff | `cpg_mutate.py` (G-236), `/cpg_mutate` | yes |

**Gap (found here):** a kernel cell cannot reach the typed roles. `/model_run`
returns a role's type or the reason it is not, but no kernel call wraps it;
the cell's model call is `Agent.ask`, which returns untyped text
(`kernel_objects.py` `_Agent.ask`). The promise exists at the route and stops
short of the surface a cell uses.

### 1b. Models per role (179, kept: "Per role, when downloads allowed")

**Two registries, never reconciled (undocumented):**

| role | `models.ROLES` (typed, G-262/264) | `agent_model.TASK_MODELS` (smolagents, G-384) |
|---|---|---|
| chat | `deepseek-coder-6.7b-instruct.Q4_K_M` | `Nous-Hermes-2-Mistral-7B-DPO.Q4_0` |
| code | -- | `qwen2.5-coder-7b-instruct-q4_0` |
| plan | -- | `DeepSeek-R1-Distill-Qwen-7B-Q4_0` |
| triplex | `triplex-Q4_K_M` | -- |
| jev | `OpenJev-Flash-9B-Q4_K_M` | -- |

The two disagree on "chat", and each has roles the other lacks. "Per role"
can only mean one table.

### 1c. Every call an edge of the workspace's dependency graph

| call | recorded as an edge? | where |
|---|---|---|
| a kernel cell run | **yes**: `Run` + `RunInput`, `FORWARD_MAPPED_TO`; drawn live as the signal flow | `graphstore.record_run` (its one call site: `sidecar.py` after a cell), `/runs`, `/signal`, `/inverse_map` (G-279, G-292) |
| a `browse` move (G-205) | no: the session's own log, gone with it | `browse.Session.log` |
| a kernel ask carried by the plugin (`focus`, `act`, `reveal`, ...) | no: the plugin's last 20, in memory | `main.ts` `toolAskLog` |
| a model role run | no | `/model_run` |
| an MCP tool call | no | `mcp.py` |

So the "communication link on the dependency graph" exists for exactly one
kind of call.

### 1d. Propose, the reader approves (179, kept)

`create(name, body)` makes a card on the plane and `review(name, question)`
writes a `> [!question] review` callout onto it (`editorcalls.ts`
`do_review`). **Gap:** the question has no answer path. Nothing reads a
reader's reply, so an agent can ask and never learn the answer, and
"completes it only after you accept" has nothing to wait on.

### 1e. Reconstruction, skeleton and ephemerals

Already in place without the names: a note's cells are its skeleton and their
outputs its ephemerals (the output block is separate and hash-keyed);
`rerun_plan` says what to re-run; a kernel per note can be restarted (`POST /kernel` with `op: "restart"`, `kernel_pool.restart`)
and its cells replayed. Reading, mine: "reconstruction" needs no new
machinery, only a "replay this note in a fresh kernel" action, which is
`invoke(name)` (editor calls) against a restarted kernel.

### 1f. Recurrence detection

Two artifacts "the same recurring" = near-duplicates in the dual embedding:
`hierank.dual_similar` (G-390: tf-idf centroid x semantic centroid, measured
against the planted layout distance), `/duplicates`, `/dedupe`. Applies to
cards and tool surfaces as soon as they are vault pages, which they are
(G-382: tool panels and subgraphs are searchable pages).

### 1g. Everything a plugin, slots that may only tighten (G-240)

The kernel bootstrap already IS a slot table: every core call is installed
under `if "<name>" not in globals():` (`kernel_objects.py`). **Finding, read
from the code, not yet tested:** that guard lets a cell REPLACE a core call.
A cell that defines its own `search` keeps it for the rest of the kernel's
life, and the bootstrap never restores it. That is the opposite of "may only
tighten": nothing checks that a replacement keeps the core's signature or
type.

**Tested 2026-11-22** (`tests/test_kernel_slots.py`): confirmed -- a cell's
`def search(...)`, and even a plain `view = [...]`, replaces the core call
for the kernel's life. Enforcing "may only tighten" by re-installing the core
would clobber readers' ordinary variables (`view`, `check`, `types`, `pages`,
`chunk`, `focus` are core names). Options, for the reader: leave it; keep the
core calls also under one reserved name (`domvec.search`, never shadowed);
or warn when a cell shadows a core name.

## 2. Routes no document names (undocumented APIs)

Read from `sidecar.py`'s dispatch against every `docs/*.md`:
`checkpointing`, `code/sync`, `code_nodes`, `cpg_vectors`, `edges`,
`heal_anchors`, `lead_vectors`, `live_render`, `page_spread`, `page_status`,
`relink`. None of them bears on the themes above except `code_nodes` (the
retrieval bar's typed CPG nodes, the closest thing to a typed tool registry).

## 3. What we can use — ranked by what it releases

1. **Record every call as a run** (1c). `browse` moves, carried asks and model
   role runs written through `record_run`, so the 3D signal flow (G-292) and
   `/inverse_map` show agents' and the reader's tool use, not only cells.
   Uses: `record_run`, `/signal`. Cost: small; one call site becomes four.
2. **One model table, typed, reachable from a cell** (1a, 1b). Merge
   `TASK_MODELS` into `models.ROLES` (one role, one file, one parser) and add
   a kernel call `run_role(role, **inputs) -> TypedResult` over `/model_run`.
   That is "type + check" at the cell surface: a role's type, and a check cell
   below it. **Needs you: which file is "chat"?**
3. **Give `review` an answer path** (1d): the reader answers in the callout,
   and a kernel call `answer(name)` returns it, or None while unanswered. With
   it, "propose, you approve" is `create` + `review` + `answer` and nothing
   new.
4. **Slots that only tighten** (1g): the bootstrap re-installs a core call a
   cell has replaced, unless the replacement declares the same signature.
   Test first: a planted cell that redefines `search`.

The example agent architecture of 179 (b), "quantized language model
workflows ... assembled as an example of an intelligent agent architecture in
the graph editor" (held as a reading), would then be a NOTE built only from
these: `browse`/`search` -> `run_role` (typed) -> a check cell ->
`cpg_mutate` -> `create` + `review` for anything new, every step a recorded
run drawn in the signal flow. No new subsystem.

## 4. Done since (2026-11-22)

* **Item 1 -- every call a run:** G-391, live run 88 (`50e79b4`).
* **Item 3 -- review's answer path:** G-392, live run 90 (`caded6c`).
* **Item 4 -- slots:** tested, held for the reader (1g above).
* **Item 2 -- one model table:** waits on which file is "chat".
