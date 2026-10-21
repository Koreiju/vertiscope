// "the patricia trie shown clearly and guaranteed tree-structured" (2026-10-04):
// the verdict over EVERY drawn edge, and one planted arm per defect it names.
import { test } from "node:test";
import assert from "node:assert/strict";
import { treeVerdict } from "../src/treeguard.ts";

const U = "https://a.test/p";
const page = { id: "page:a", level: "page", url: U };
const n = (id, url = U) => ({ id, level: "chunk", url });
const e = (source, target, extra = {}) => ({ source, target, ...extra });

function clean() {
  const nodes = [page, n("c1"), n("c2"), n("c3"), n("c4")];
  const links = [e("page:a", "c1"), e("page:a", "c2"), e("c1", "c3"), e("c3", "c4", { force: true })];
  return { nodes, links };
}

test("one page's trie, containment and streaming edges together, is a tree", () => {
  const { nodes, links } = clean();
  const v = treeVerdict(nodes, links);
  assert.equal(v.ok, true, JSON.stringify(v));
  assert.equal(v.edges, 4);
});

test("planted: a containment parent AND a streaming parent", () => {
  const { nodes, links } = clean();
  const v = treeVerdict(nodes, [...links, e("c2", "c4", { force: true })]);
  assert.equal(v.ok, false);
  assert.equal(v.multiParent, 1);
  assert.deepEqual(v.sample[0].parents.sort(), ["c2", "c3"]);
});

test("planted: a cycle", () => {
  const nodes = [page, n("c1"), n("c2")];
  const v = treeVerdict(nodes, [e("c1", "c2"), e("c2", "c1")]);
  assert.equal(v.ok, false);
  assert.equal(v.cyclic, 2);
});

test("planted: a chunk hung from another url's node", () => {
  const { nodes, links } = clean();
  const other = { id: "x1", level: "chunk", url: "https://b.test/" };
  const v = treeVerdict([...nodes, other], [...links, e("x1", "c2")]);
  assert.equal(v.crossUrl, 1);
  assert.equal(v.ok, false);
});

test("planted: a second root beside the page node (an orphaned chunk)", () => {
  const { nodes, links } = clean();
  const v = treeVerdict([...nodes, n("lost")], links);
  assert.equal(v.forests, 1);
  assert.equal(v.ok, false);
});

test("page-to-page edges are the corpus graph and are not judged", () => {
  const { nodes, links } = clean();
  const p2 = { id: "page:b", level: "page", url: "https://b.test/" };
  const v = treeVerdict([...nodes, p2], [...links, e("page:a", "page:b")]);
  assert.equal(v.ok, true, JSON.stringify(v));
});

test("a fragment is the same document", () => {
  const nodes = [page, { id: "c9", level: "chunk", url: U + "#sec" }];
  assert.equal(treeVerdict(nodes, [e("page:a", "c9")]).ok, true);
});
