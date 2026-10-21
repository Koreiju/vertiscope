// G-116: the stream grows as the page's patricia trie, not a star on the page
// node (2026-10-06: "The lagging chunks initialized into a perfect sphere ...
// The diff should be sort of like a trickling effect over the emerging diff on
// the active and open tree structure"). Measured live before: 33/33 streamed
// nodes hung on the page node.
import { test } from "node:test";
import assert from "node:assert/strict";
import { ForceTree } from "../src/forcetree.ts";
import { treeVerdict } from "../src/treeguard.ts";

const URL = "https://a.test/p";
// dict: 0 body, 1 main, 2 section, 3 p, 4 div, 5 #text
const DICT = ["body", "main", "section", "p", "div", "#text"];
const line = (title, steps) => [0, title, steps];
const chunk = (id, steps) => ({ id, digest: id, lines: [line("chunk " + id, steps)] });
// /html/body/main/section[k]/(p|div)
const at = (k, leaf) => [0, 1, 1, 1, 2, k, leaf, 1, 5, 1];

function drain(chunks, first = true) {
  return { v: 1, dict: first ? DICT : [], chunks, removed: [], stats: { dictSize: DICT.length } };
}

function graphOf(delta) {
  const nodes = delta.added.map((a) => ({ id: a.id, level: !a.parent ? "page" : a.branch ? "path" : "chunk", url: URL }));
  const links = delta.added.filter((a) => a.parent).map((a) => ({ source: a.parent, target: a.id }));
  return { nodes, links };
}

test("four chunks in two sections hang on the trie's branches, not the page", () => {
  ForceTree.plantFlat = false;
  const t = new ForceTree(URL);
  const d = t.apply(drain([chunk(1, at(1, 3)), chunk(2, at(1, 4)), chunk(3, at(2, 3)), chunk(4, at(2, 4))]));
  const branches = d.added.filter((a) => a.branch);
  const chunks = d.added.filter((a) => a.parent && !a.branch);
  const page = ForceTree.pageId(URL);
  assert.equal(chunks.length, 4);
  // Every chunk hangs from a branch (its section), none from the page.
  assert.equal(chunks.filter((c) => c.parent === page).length, 0, JSON.stringify(chunks));
  // Branches: the two sections, and the main where they diverge.
  const addrs = branches.map((b) => b.id.split("@")[1]).sort();
  assert.deepEqual(addrs, ["/html/body/main", "/html/body/main/section", "/html/body/main/section[2]"]);
  const g = graphOf(d);
  const v = treeVerdict(g.nodes, g.links);
  assert.equal(v.ok, true, JSON.stringify(v));
});

test("planted flat: every chunk hangs on the page node (the star)", () => {
  ForceTree.plantFlat = true;
  try {
    const t = new ForceTree(URL);
    const d = t.apply(drain([chunk(1, at(1, 3)), chunk(2, at(1, 4)), chunk(3, at(2, 3)), chunk(4, at(2, 4))]));
    const chunks = d.added.filter((a) => a.parent && !a.branch);
    assert.equal(chunks.filter((c) => c.parent === ForceTree.pageId(URL)).length, 4);
    assert.equal(d.added.filter((a) => a.branch).length, 0);
  } finally { ForceTree.plantFlat = false; }
});

test("the trie trickles: a later chunk joins its branch, and a new divergence reparents", () => {
  const t = new ForceTree(URL);
  t.apply(drain([chunk(1, at(1, 3)), chunk(2, at(1, 4))]));
  const d2 = t.apply(drain([chunk(3, at(2, 3))], false));
  // A second section appears: main now diverges -> a branch arrives above both.
  const added = d2.added.map((a) => a.id.split("@")[1] || a.id);
  assert.ok(added.includes("/html/body/main"), JSON.stringify(d2));
  assert.ok(d2.reparented.length >= 1, "the first section's branch moves under main");
});
