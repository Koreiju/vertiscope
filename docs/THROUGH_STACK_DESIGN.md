# Through-stack agents — design draft 1 (G-239, with G-238 and G-240)

*2026-11-22. A draft for the reader to correct, not a decision. G-239's row
says "Design with the reader first", so nothing below is built. Every reading
of the verbatim is marked as mine. The other assistant's names pasted on
2026-10-18 ("nine-layer through-stack", `Promise<T>`, `PluginRegistry`, ...)
are NOT used as authority here (PLUGIN_GOAL, the note under 168).*

## 0. The verbatim it answers (PLUGIN_GOAL, 2026-10-18, items 167-169)

> "a primary mcp tool surface that calls and experiments through development
> terminals as well. so each agent debugs its local feature/functionality
> within its context and still aggregates global knowledge through
> self-discoverable queries."

> "recursive graph rag tool calls enforce feedback promises on finalized
> artifacts ... back to the base promise type/structure that signifies
> feedback on a validated discovery of code transformation on datatypes."

> "each recursive graph rag node call is part of the forward-propagating
> workflow on interconnecting through-stacks within their localized contexts
> of their agents; it's a communication link on the knowledge-based
> dependency graph ... of the overall code workspace itself."

> "a prompt is just another input to the same recursive tool call that holds
> the through-stack's context and enables recursive calls to the same tool
> over different graph RAG surfaces on through-stacks, both existing and newly
> constructed. reconstruction and self-repair are also part of the same
> meta-harness"

> "promises live at the local through-stack mcp tool surface and
> auto-update. They represent components of the tool call's I/O that are
> built-in to the local code modules and also propagate as new features
> through the through-stack graph."

## 1. What already exists — the through-stack is mostly a composition

| the verbatim asks for | what the repository already has | where | live evidence |
|---|---|---|---|
| a quantized model per agent | a smolagents `Model` over a local GGUF (llama-cpp, grammar-constrained steps), task -> file by header | `agent_model.py` | G-384/G-385: Qwen2.5-Coder-7B on CUDA, 56 tok/s |
| a bounded context | one kernel per NOTE (`kernel_pool.run(note, ...)`) -- a note's cells share it, another note's do not | `sidecar.py` | G-279, G-377 |
| its own isolated terminal | the shell pool; a terminal cell per note | `shell.py`, `TERMINAL_TEXT` | P-C2, item 142 |
| its local code artifact | the note's code cells, addressed `vault://<note>#cell <n>`; a step of the agent IS a cell | `agent_step.py` | G-384 |
| MCP tools generated from its code | the kernel's tool panels, read from the bootstrap, as smolagents `Tool`s and as `tool://kernel/` pages | `agent_tools.py`, `tool_panels.py`, `tool_surface.py` | G-376, G-382 |
| graph-RAG over web, code, docs | `search` (three-form), `browse` (web / domain / page), the code graph, `similar` | `search.py`, `browse.py`, `code_kg.py` | G-205, G-318 |
| each call an edge of the workspace's dependency graph | every cell run records `FORWARD_MAPPED_TO` inputs -> output (`Run`, `RunInput`) | `graphstore.py` (G-279) | G-292 draws them live |
| a validated code transformation on a datatype | a change as a CPG mutation (ADD_NODE / MODIFY_PROPERTY / ...), compiled back to source, compile-checked, applied as a unified diff | `cpg_mutate.py` (G-236) | tests |
| the datatype | strict pydantic types mined from trie-path patterns | `typegen.py` (G-388) | run 56 |

**What does not exist:** a *stack* as one object; a *promise*; a call from
one stack to another; a new stack made when a query does not resolve; the
meta-harness (reconstruct, repair, detect recurrence); and the
skeleton/ephemeral split.

## 2. A through-stack — a reading, mine

A **vault note** is the stack. It already holds the four things the verbatim
lists, by existing machinery:

```
note  domvec/stacks/<name>.md
  frontmatter   domvec: stack, model: <gguf>, promise: <type pattern or pydantic name>
  cells         its code artifact (agent_step writes the agent's steps here)
  kernel        its bounded context (one per note, already)
  terminal      its development terminal (a terminal cell in the note)
  surface       the MCP tools its code exposes: every top-level def in its
                cells with a docstring, read the way tool_surface reads the
                bootstrap
```

**The skeleton** is the note's frozen part: cells marked `#| skeleton`
(or the frontmatter list) — the base the stack is reconstructed from.
**Ephemerals** are everything else: steps an agent wrote, outputs, messages
received. Reconstruction = new kernel + replay the skeleton cells only.

## 3. The one recursive call — a reading, mine

```python
ask(stack, prompt, surface="web"|"code"|"stacks", **inputs)   # one tool, like browse
```

1. Graph-RAG over `surface` for the prompt (`search` / `browse` / the code
   graph / the stacks' own surfaces).
2. If a stack's surface answers it (a tool whose docstring and promise
   match), call that tool **in that stack's kernel** — the call is an edge
   `stack A -> stack B`, recorded as a `Run` with its inputs (G-279's table
   already holds exactly this shape).
3. If none does (the query "does not resolve"), **construct** a new stack
   note: its skeleton a docstring-and-signature wireframe for the missing
   tool (G-238: natural-language first), its model asked to complete it
   (`cpg_mutate` ADD_NODE on the wireframe, compile-checked).
4. The prompt is just another input in `inputs` — the same call, from the
   reader or from another stack.

## 4. The promise — a reading, mine

A promise is a stack's tool's **declared output type** (a pydantic model,
`typegen` style) plus a **check** — a test cell. It is "validated" when the
check passes on the tool's real output; a stack's promise "rolls up" when
every call it made returned a validated value. The base promise is a
`cpg_mutate` diff that compiles and whose check passes — "a validated code
transformation on a datatype". Auto-update: the surface is re-read whenever
the note's cells change (the ingest already re-reads notes).

## 5. The meta-harness — a reading, mine

* **repair:** a promise check fails -> the stack's skeleton is replayed in a
  fresh kernel, the failing tool re-asked of the model with the failure as
  input;
* **recurrence:** two stacks whose surfaces' docstrings are near-duplicates
  in the dual embedding (G-390's similarity, not a layout) are the same
  stack recurring — flagged, merged on the reader's word;
* everything it does is a cell in a `domvec/stacks/_harness.md` note, so
  the reader sees it in panel and graph form (spec §11b).

## 6. G-240 — everything is a plugin (a reading, mine)

The stack note IS the plugin unit: its surface fills named slots (`search`,
`browse`, a typed tool) and may only tighten them (a stricter promise type);
removing the note leaves the core running. Nothing in the core imports a
stack.

## 7. Questions for the reader

1. Is a **vault note** the right unit for a stack (its kernel, cells, terminal
   already per note), or should a stack be a code module on disk?
2. A **promise**: a declared output type plus a check cell — or something you
   meant differently?
3. When a query does not resolve, should a new stack be **made automatically**,
   or proposed to you first?
4. The models: which GGUF drives a stack by default, given G-237 still holds
   downloads (Qwen2.5-Coder-7B is on disk and measured)?
