// mergePayloads: queued drains of one page merged into one capture, replayed
// in drain order (2026-10-17: "persist chunk streams no matter how fast
// interactions are on the page"). Planted bug it guards: removals applied
// after everything, which dropped a chunk removed and later re-added.
import { test } from "node:test";
import assert from "node:assert/strict";
import { mergePayloads } from "../src/mergepayloads.ts";

const ids = (p) => p.chunks.map((c) => String(c.id)).sort();

test("a chunk removed then re-added survives the merge", () => {
  const m = mergePayloads([
    { dict: ["a"], chunks: [{ id: 1, v: "x" }, { id: 2, v: "y" }], removed: [] },
    { dict: [], chunks: [], removed: [1] },
    { dict: ["b"], chunks: [{ id: 1, v: "x2" }], removed: [] },
  ]);
  assert.deepEqual(ids(m), ["1", "2"]);
  assert.equal(m.chunks.find((c) => c.id === 1).v, "x2");
  assert.deepEqual(m.removed, []);
  assert.deepEqual(m.dict, ["a", "b"]);
});

test("a chunk added then removed is gone, and its removal is reported", () => {
  const m = mergePayloads([
    { chunks: [{ id: 3, v: "z" }], removed: [] },
    { chunks: [], removed: [3, 9] },
  ]);
  assert.deepEqual(ids(m), []);
  assert.deepEqual(m.removed.map(String).sort(), ["3", "9"]);
});

test("the latest content of a rewritten chunk wins", () => {
  const m = mergePayloads([{ chunks: [{ id: 5, v: "old" }] }, { chunks: [{ id: 5, v: "new" }] }]);
  assert.deepEqual(m.chunks, [{ id: 5, v: "new" }]);
});

import { removesCarried } from "../src/mergepayloads.ts";
test("a drain removing what a queued job carries is not merged into it", () => {
  assert.equal(removesCarried({ removed: [3] }, { chunks: [{ id: 3 }] }), true);
  assert.equal(removesCarried({ removed: [4] }, { chunks: [{ id: 3 }] }), false);
  assert.equal(removesCarried({ removed: [] }, { chunks: [{ id: 3 }] }), false);
});
