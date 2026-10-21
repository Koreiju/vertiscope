# Theory: efficient JavaScript extraction and algorithm injection

The algorithm lives in the page. Python receives deltas and vectorises them.
This document is about the boundary between those two facts: what it costs to
put an algorithm into a live page, what it costs to get data out, and which
injection patterns survive contact with a mutating shadow DOM.

Everything here is measured on this project unless marked otherwise.

---

## 1. The boundary is a fixed toll, not a pipe

`driver.execute_script` costs **5–11 ms of fixed overhead per call**, measured,
independent of payload size. Two round-trips per pass cost more than one call
returning twice the data.

Consequences, in order of size:

1. **Never poll.** A settle loop that asks "are you done yet?" every 100 ms
   spends its entire budget on tolls. The page must *decide* it is settled and
   report it in the same call that drains the data.
2. **Collapse calls.** `scanner.py` already merges the delta drain and the
   stats read into one script for exactly this reason. Any new read must join
   that call rather than add a third.
3. **Payload size is second-order** until it is large. Getting 20 KB out in one
   call is cheaper than getting 2 KB out in two.

The corollary that governs the whole design: **work belongs on the side of the
boundary that has the information**, because moving information to the work
costs a toll and moving the work costs nothing.

## 2. Three injection patterns, and what each can hold

| pattern | state | cost per read | when it is right |
|---|---|---|---|
| **one-shot IIFE** | none | O(page) — re-walks everything | a single settled snapshot |
| **persistent global** | on `window` | O(delta) — drains a buffer | a live observer loop |
| **re-injected stateless** | passed in and back | O(state) transfer | small state only |

Selenium gives no scope continuity: every `execute_script` is a fresh scope.
A closure cannot survive between calls on its own — **something reachable must
hold it**. That is the whole reason a persistent injection needs a foothold,
and it is why the "pure passive sensor" ideal has a floor.

### 2.1 The minimal foothold

A `MutationObserver` keeps its callback alive, and the callback closes over
the state — so the *state* needs no global. What needs a name is the **drain
handle**: Python must be able to call in and take the buffer.

The minimal footprint is therefore exactly one property, and it can be made
nearly invisible:

- non-enumerable (`Object.defineProperty`, `enumerable: false`) — absent from
  `Object.keys`, `for…in`, and devtools' default listing;
- randomly named per session, so page scripts cannot collide with or detect it
  by a known key;
- holding only functions, never data — the buffer stays in the closure.

This is the honest boundary of "does not modify the page": **no DOM mutation,
no attributes, no layout effect, no observable behaviour change** — one hidden
property on `window`. The current engine fails this on two counts: it uses a
fixed public name (`window._wfhEngine`), and the serializer stamps
`data-vertiscope-hash` attributes, which *is* DOM modification and is visible to
the page's own scripts and CSS selectors.

### 2.2 Why not `execute_async_script`

It lets the page signal completion instead of being polled, which removes the
poll toll. But its callback is per-call, not persistent, and Selenium's script
timeout bounds it. It is right for *"tell me when settled"*, wrong for *"keep
telling me forever"*.

## 3. Observing a shadow DOM is not one observer

`MutationObserver` does not cross shadow boundaries. `{subtree: true}` on
`documentElement` sees nothing inside any shadow root. So:

- one observer per shadow root, attached when the root is discovered;
- **there is no event for `attachShadow`** — a shadow root becoming available
  is not itself a mutation. It can only be found by inspecting added element
  nodes for `.shadowRoot` as they arrive, which means the `childList` handler
  must probe every added subtree for new roots;
- closed roots are unreachable from script, by definition. They are not a bug
  to work around; they are outside the observable state.

This is the single largest source of accidental O(page) work: a naive
"re-scan for new shadow roots" on every mutation walks the whole tree. The
probe must be scoped to the added nodes the record already names.

### 3.1 Scope the observer, not the handler

`attributeFilter` is the cheapest filter available — the browser never calls
back for attributes outside it. Filtering inside the callback has already paid
for the call. Content-bearing attributes only (`href`, `src`, `srcset`,
`alt`, `aria-label`, `title`, `value`, `data-*` that carry JSON) cuts the
callback rate on a live feed by an order of magnitude compared with observing
all attributes.

`characterData: true` without `characterDataOldValue` is materially cheaper;
old values are only needed if the algorithm diffs text rather than recomputing
it from the node.

## 4. Batching: the page decides when it is worth speaking

Mutations arrive in bursts — a framework render is hundreds of records in one
microtask. The observer callback is already batched by the browser (one call,
many records), but *bursts of callbacks* still need coalescing.

- **Debounce** on a short window (80 ms is what the current engine uses) turns
  a render storm into one repair.
- **`requestIdleCallback`** performs the repair without competing with the
  page's own rendering; falls back to a timeout where unsupported. This is
  what makes the sensor *passive* in the performance sense, not just the
  mutation sense.
- The debounce timer is also the settle signal: no pending timer means
  settled, which Python reads in the same call as the drain (§1).

## 5. Getting data out: shape the payload at the source

The original `dom_deep_serializer.py` returned
`JSON.stringify(extract(document.documentElement))` — the entire DOM as a JSON
tree, every pass, then hashed and pruned it in **Python**. Two costs, both
avoidable:

1. the whole document crosses the boundary every pass;
2. the hashing that decides what is *new* happens after everything has already
   moved, so it saves nothing on transport.

`deep_serialize.js` fixes exactly this by hashing in-page and replacing known
subtrees with `<template data-vertiscope-same=HASH>` placeholders — **measured
85.7% of bytes never crossing the wire** on a scrolling page, 99% on a settled
pass. The rule generalises:

> Any decision about what to send must be made on the sending side. A filter
> that runs after transport is not a filter, it is a report.

### 5.1 Payload encoding

- Return **primitives and flat arrays**, never `WebElement`s — element handles
  are individually expensive to marshal and pin objects in memory.
- Return **one JSON string** rather than a nested object graph; Marionette's
  serialisation of deep structures is markedly slower than `JSON.parse` on the
  Python side of a single string.
- Prefer **integer ids and interned strings** in deltas over repeated absolute
  xpaths. An absolute xpath through four shadow roots is ~200 bytes; a delta
  naming fifty of them is 10 KB of mostly-identical prefixes.

## 6. What the injected algorithm should compute, and what it must not

The page has the located change. It should therefore compute everything whose
repair is *local to that location*: subtree digests, chunk membership under a
char budget, xpath assembly, per-element content detection, and the dedup
bookkeeping that decides whether a node's text is already represented by an
ancestor.

It must **not** compute anything defined across the whole document — pattern
classes over generalised xpaths, IDF, PageRank. Those change arbitrarily far
from the edit, cannot be repaired locally at any cost, and belong in the
batched Python half where a stale value is acceptable and declared.

That split — local repair in JS, global aggregation in Python — is the whole
architecture, and it is dictated by where the information is (§1), not by
preference about languages.

## 7. Failure modes specific to this boundary

- **The silent no-op.** `deep_serialize.js` reads `arguments[0]` outside its
  IIFE precisely because an IIFE has its own `arguments`; reading it inside
  yields `undefined`, nothing is ever pruned, and the transport quietly
  degrades to full with no error. Injection bugs fail silently by default and
  must be asserted against a counter, never assumed.
- **Re-injection on navigation.** A page load destroys the injection. Any
  navigation, including SPA history changes that replace `documentElement`,
  must re-inject and re-attach observers. A stale handle returns an empty
  buffer, which is indistinguishable from a quiet page.
- **Observer starvation under `display:none`.** Content in hidden subtrees
  still mutates and still reports; content lazily rendered only on scroll does
  not exist to observe until scrolled. Scrolling is therefore part of the
  sensor, not part of the test harness.
- **Detached-node records.** A record's `target` may already be removed from
  the document by the time the callback runs. `getRootNode().isConnected`
  before computing an xpath, or the path assembly walks into nothing.

---

## 8. What this says to do next

1. Replace the fixed `window._wfhEngine` name with a random non-enumerable
   property, and stop stamping `data-vertiscope-hash` into the live DOM — those are
   the two places the sensor is currently not passive.
2. Consume the delta queue that `stream_snapshots` currently discards; it is
   the located change the whole design wants and it is already being computed.
3. Move chunk-membership and xpath assembly into the same in-page fold that
   produces the digest, so one traversal serves all three instead of Python
   re-deriving them from a re-parsed document.
4. Keep vectorisation, frequency, PageRank and retrieval in Python, batched.
5. Assert every injection against a counter returned in the same call, because
   the default failure of this boundary is silence.
