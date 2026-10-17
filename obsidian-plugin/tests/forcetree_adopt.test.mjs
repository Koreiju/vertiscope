// G-216/G-217 (2026-10-17): a page that begins INSIDE a running document
// (archive.org's search list rewriting its url as it scrolls) continues that
// document's stream. A fresh tree could decode none of its drains -- the
// sensor's dictionary belongs to the document -- and dropped the stream.
import { test } from "node:test";
import assert from "node:assert/strict";
import { ForceTree } from "../src/forcetree.ts";

const DICT = ["body", "main", "section", "p", "div", "#text"];
const line = (title, steps) => [0, title, steps];
// The sensor's digest changes with the content.
const digestOf = (s) => [...s].reduce((h, ch) => (h * 31 + ch.charCodeAt(0)) >>> 0, 7);
const chunk = (id, steps, text) => ({ id, digest: digestOf(text || "chunk " + id), lines: [line(text || "chunk " + id, steps)] });
const at = (k, leaf) => [0, 1, 1, 1, 2, k, leaf, 1, 5, 1];
const A = "https://archive.test/search?q=x", B = "https://archive.test/search?q=x&page=2";

function first() {
  const t = new ForceTree(A);
  t.apply({ v: 1, dict: DICT, chunks: [chunk(1, at(1, 3)), chunk(2, at(1, 4))], removed: [], stats: { dictSize: DICT.length } });
  return t;
}
// The document's NEXT drain: no new dictionary words, a new chunk, an old one gone.
const next = { v: 1, dict: [], chunks: [chunk(3, at(2, 3), "more results")], removed: [2], stats: { dictSize: DICT.length } };

test("the adopted tree decodes the document's next drain and keeps what is still on the page", () => {
  const b = new ForceTree(B);
  b.adopt(first());
  const d = b.apply(next);
  assert.ok(d, "decoded");
  const chunks = d.added.filter((a) => a.parent && !a.branch).map((a) => a.id).sort();
  assert.deepEqual(chunks, [B, B].map((u, i) => `f:${u}#${[1, 3][i]}`).sort());
  assert.deepEqual(b.linesOf(`f:${B}#3`), ["more results"]);
  // The page removed #2: retained, not forgotten (the union of what was seen).
  assert.deepEqual(b.linesOf(`f:${B}#2`), ["chunk 2"]);
  assert.equal(b.retainedCount(), 1);
});

test("planted (plantDropRemoved): a removed chunk is forgotten, as before", () => {
  ForceTree.plantDropRemoved = true;
  try {
    const b = new ForceTree(B);
    b.adopt(first());
    const d = b.apply(next);
    assert.ok(d.removed.includes(`f:${B}#2`));
    assert.equal(b.linesOf(`f:${B}#2`), null);
  } finally { ForceTree.plantDropRemoved = false; }
});

test("a reused element's new content is a new node; the old content stays", () => {
  const t = first();
  const d = t.apply({ v: 1, dict: [], chunks: [chunk(1, at(1, 3), "a different tile")], removed: [], stats: { dictSize: DICT.length } });
  const added = d.added.filter((a) => a.parent && !a.branch).map((a) => a.id);
  assert.deepEqual(added, [`f:${A}#1.1`]);
  assert.deepEqual(t.linesOf(`f:${A}#1`), ["chunk 1"]);           // retained
  assert.deepEqual(t.linesOf(`f:${A}#1.1`), ["a different tile"]);
  assert.equal(d.removed.length, 0);
  // The old content shown again elsewhere: one node per content.
  const d2 = t.apply({ v: 1, dict: [], chunks: [chunk(7, at(3, 3), "chunk 1")], removed: [], stats: { dictSize: DICT.length } });
  assert.ok(d2.removed.includes(`f:${A}#1`));
  assert.equal(t.linesOf(`f:${A}#1`), null);
});

test("null arm: a fresh tree cannot decode it (the dropped stream)", () => {
  assert.equal(new ForceTree(B).apply(next), null);
});
