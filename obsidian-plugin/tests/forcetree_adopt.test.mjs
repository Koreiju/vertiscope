// G-216/G-217 (2026-10-17): a page that begins INSIDE a running document
// (archive.org's search list rewriting its url as it scrolls) continues that
// document's stream. A fresh tree could decode none of its drains -- the
// sensor's dictionary belongs to the document -- and dropped the stream.
import { test } from "node:test";
import assert from "node:assert/strict";
import { ForceTree } from "../src/forcetree.ts";

const DICT = ["body", "main", "section", "p", "div", "#text"];
const line = (title, steps) => [0, title, steps];
const chunk = (id, steps, text) => ({ id, digest: id, lines: [line(text || "chunk " + id, steps)] });
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
  assert.equal(b.linesOf(`f:${B}#2`), null);
});

test("null arm: a fresh tree cannot decode it (the dropped stream)", () => {
  assert.equal(new ForceTree(B).apply(next), null);
});
