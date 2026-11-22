# The browser centroid as a one-tool graph-RAG surface — design draft 1 (G-205)

*2026-11-22. A draft for the reader to correct, not a decision. G-205's own
row says it is "designed with the reader BEFORE it is built", so nothing
below is built yet. Every reading of the verbatim is marked as mine.*

## 0. The verbatim it answers (PLUGIN_GOAL, 2026-10-17, item 132)

> "an instantiated centroid node that represents the web browser as a minimal
> MCP surface with at most one tool call over the set of largely web browser
> interaction from a graph-RAG interface on the vectorized DB."

> "we could even differ the way the results are presented depending on which
> level of graph RAG query is set, whether at the web, domain, or in-page
> scopes. In any case, we organize and present chunk interactions as atomic
> units that enable their own per-page navigations as well as navigation over
> the rendered/retrieved set of rendered inter-web chunk results, where direct
> interactions with each chunk are enabled by selection and interactions."

> "going "up" to the results and "down" to their per-page traces are different
> somewhat from going 'back and forward', but effectively trace back to the
> origin of the retrieval artifact when going "up" from per-page trace
> navigations, which themselves stream and render on the interactive retrieval
> artifact as diffs."

## 1. What already exists, so the surface is a composition, not new machinery

| the verbatim asks for | what the repository already has | where |
|---|---|---|
| graph-RAG retrieval over the vectorised DB | three-form ranking (lexical x PageRank x semantic), a window over a ranked list | `search_payload` in `sidecar.py`, `/search` |
| the in-page scope | `url=` restricts the ranking to one shadow DOM (G-70) | `search_payload(url=...)` |
| the web scope | the unscoped ranking | `/search` |
| the domain scope | **missing**: no host-prefix scope exists | — |
| chunks as atomic interactive units | each chunk's lines carry trie addresses; a control acts through its address on the live page | `panelact.ts`, `browser.ts` `actOnAddress` (G-111, run 70; G-377b, run 65) |
| per-page navigation | the browser cell's `go`, `/resolve` from an address to its chunk | `browser.ts`, `/resolve` |
| a rendered page "from the perspective of the graph RAG database" | a chunk's snapshot card, its own page elements with addresses | `snapshot.ts`, `snapshotscript.ts` |
| results streaming as diffs | the sensor's fold streams drains as diffs into the trie and the graph | `sensor.js`, `/capture` |
| the centroid node itself | the url-node scaling about a browser centroid (131) | the projector's layout |
| an MCP surface for agents | the kernel's toolspace calls, one surface per README pane | `kernel_objects.py`, `tool_panels.py` (G-376, G-377) |

## 2. The one tool — a reading, mine

"At most one tool call" read as: an agent, or the reader clicking the
centroid, holds ONE call, and every move is that call with a different
argument. Everything it returns is one object, the **retrieval artifact**,
and every later call is relative to it.

```python
browse(query=None, scope="web", down=None, up=False, act=None)   # one tool; returns the artifact
```

| argument | meaning | reaches |
|---|---|---|
| `query`, `scope` | a new artifact: ranked chunks at `web`, `domain` (host prefix) or `page` scope | `/search` (+ the domain scope, §4) |
| `down=<cid>` | descend from a result into its page trace: the browser cell opens the chunk's page at the chunk; what streams in renders as diffs on the artifact | `go` + the fold's drains |
| `up=True` | return toward the ORIGIN of the artifact: from a page trace to its result list; from a result list to the query | the artifact's own stack (§3) |
| `act={address, value}` | act on a chunk's control in place, through its trie address | `actOnAddress` |

**back / forward stay the browser's.** They walk the page history inside one
trace. **up / down walk the artifact**: results above, traces below. Hence
"different somewhat from going 'back and forward'".

## 3. The artifact — what one call returns (a reading, mine)

A tree whose root is the query, with the trie's own addresses as its edges:

```
artifact
  query, scope
  results[]            -- atomic chunk units: cid, url, its lines with addresses, its controls
    trace[]            -- per-page navigations made under this result (url history, diffs streamed)
  cursor               -- where up/down currently is: the artifact, a result, or a trace step
```

Grouped by presentation per scope (the verbatim's "differ the way the results
are presented"), my proposal:

- **page:** results in document order, as the page draws them (one shadow DOM).
- **domain:** results grouped by url, pages ordered by their best chunk.
- **web:** results ranked across urls, each labelled with its domain.

## 4. What building it would need

1. **The domain scope.** A host-prefix filter in `search_payload`, beside
   `url=`. It is the only missing retrieval piece.
2. **The artifact's state** in the sidecar (one per session), so `up`, `down`
   and `act` are relative to it. Patricia-trie terms: the artifact reads
   results from the trie and writes nothing to it. Its trace steps are
   addresses the trie already holds.
3. **The centroid node** in 3D as the artifact's handle. Clicking it opens the
   artifact as a panel on the plane; results are drawn as rays from it to
   their chunk nodes, the way the halo draws retrieved nodes.
4. **The MCP tool:** `browse` in `mcp.py`, and as a kernel call in
   `kernel_objects.py`, so one surface serves the agent and the cell.

## 5. Questions for the reader

1. Is "at most one tool call" one tool with arguments, as above, or one call
   per user turn?
2. Should `down` drive the reader's own browser cell, or a separate headless
   view, so an agent browsing does not move the reader's page?
3. What does "domain" mean: the host (`en.wikipedia.org`), the registrable
   domain (`wikipedia.org`), or a cluster of the url nodes' layout?
4. Should the artifact persist as a vault note (a `vault://` page, searchable
   like a subgraph), or live only for the session?
