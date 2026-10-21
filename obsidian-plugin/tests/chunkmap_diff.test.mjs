// G-109: the browser's chunk map applies the central diff. It is a projection
// of the same trie keyed on the same cid, so a retired cid must stop resolving
// (hover would outline a chunk the store dropped) and a renamed one must
// resolve to its new cid. Run: node --test tests/
import test from "node:test";
import assert from "node:assert/strict";
import { ChunkMap } from "../src/chunkmap.ts";

const URL = "https://a.test/feed";
const X = (n) => `/html/body/section/article[${n}]/p/text()[1]`;
const diff = (over) => ({ seq: 1, kind: "capture", url: URL, passno: 1, added: [], dirty: [],
                          retired: [], renamed: {}, known: [], chunks: 0, at: 0, ...over });

function mapOf(chunks) {
  const m = new ChunkMap();
  m.url = URL;
  m.apply(chunks);
  return m;
}
const chainOf = (xpath) => {
  const out = [];
  for (let at = xpath; at.length > 1; at = at.slice(0, at.lastIndexOf("/"))) out.push(at);
  return out;
};

test("a retired chunk stops resolving; the others keep their answers", () => {
  const m = mapOf({ c1: [X(1)], c2: [X(2)], c3: [X(3)] });
  assert.equal(m.lookup(chainOf(X(2)))?.cid, "c2");
  const got = m.applyDiff(diff({ retired: ["c2"] }));
  assert.equal(got.dropped, 1);
  // (An ancestor another chunk holds may still answer: that is a live chunk.)
  assert.notEqual(m.lookup(chainOf(X(2)))?.cid, "c2", "hover must not resolve to a retired chunk");
  assert.deepEqual(m.xpaths("c2"), []);
  assert.equal(m.lookup(chainOf(X(1)))?.cid, "c1");
  assert.equal(m.lookup(chainOf(X(3)))?.cid, "c3");
  assert.equal(m.chunks, 2);
});

test("planted: with the diff not applied the retired chunk still resolves", () => {
  // The arm that proves the test above can fail.
  const m = mapOf({ c1: [X(1)], c2: [X(2)] });
  assert.equal(m.lookup(chainOf(X(2)))?.cid, "c2");   // nothing applied
  assert.equal(m.chunks, 2);
});

test("a renamed chunk's addresses follow it to the new cid", () => {
  const m = mapOf({ c1: [X(1)] });
  const got = m.applyDiff(diff({ retired: ["c1"], renamed: { c1: "d1" } }));
  assert.equal(got.renamed, 1);
  assert.equal(m.lookup(chainOf(X(1)))?.cid, "d1");
  assert.deepEqual(m.xpaths("d1"), [X(1)]);
  assert.deepEqual(m.xpaths("c1"), []);
});

test("an address the new chunk already took is not stolen back by the retirement", () => {
  const m = mapOf({ c1: [X(1)] });
  m.patch({ d1: [X(1)] });                           // the capture's map_delta
  m.applyDiff(diff({ retired: ["c1"], renamed: { c1: "d1" } }));
  assert.equal(m.lookup(chainOf(X(1)))?.cid, "d1");
  assert.equal(m.chunks, 1);
});

test("a stored chunk that is retired is no longer 'already transformed'", () => {
  const m = mapOf({ c1: [X(1)], c2: [X(2)] });
  m.stored = new Set(["c1", "c2"]);
  m.applyDiff(diff({ retired: ["c1", "c2"], renamed: { c1: "d1" } }));
  assert.deepEqual([...m.stored].sort(), ["d1"]);
});

test("a diff for another page is ignored", () => {
  const m = mapOf({ c1: [X(1)] });
  const got = m.applyDiff(diff({ url: "https://other.test/", retired: ["c1"] }));
  assert.deepEqual(got, { dropped: 0, renamed: 0 });
  assert.equal(m.lookup(chainOf(X(1)))?.cid, "c1");
});
