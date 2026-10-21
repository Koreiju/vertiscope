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

// 2026-10-17 (PLUGIN_GOAL 149): a REMOVED element whose sensor id the page
// reuses must not take its kept version's node id -- lookups read the kept
// version first, and a tile opened its slot's former occupant.
function reused() {
  const t = new ForceTree(A);
  t.apply({ v: 1, dict: DICT, chunks: [chunk(7, at(1, 3), "Medical Heritage Library")], removed: [], stats: { dictSize: DICT.length } });
  t.apply({ v: 1, dict: [], chunks: [], removed: [7], stats: { dictSize: DICT.length } });
  t.apply({ v: 1, dict: [], chunks: [chunk(7, at(1, 3), "Archive Team: US Government")], removed: [], stats: { dictSize: DICT.length } });
  return t;
}
test("a removed-then-reused sensor id is a new node; the kept version keeps its own", () => {
  const t = reused();
  const live = t.held().map((h) => h.id);
  assert.equal(live.length, 1);
  assert.notEqual(live[0], `f:${A}#7`, "the live content has a new id");
  assert.deepEqual(t.linesOf(live[0]), ["Archive Team: US Government"]);
  assert.deepEqual(t.linesOf(`f:${A}#7`), ["Medical Heritage Library"]);
});
test("planted (plantGenOnRewriteOnly): the live content collides with the kept id and reads the old tile", () => {
  ForceTree.plantGenOnRewriteOnly = true;
  try {
    const t = reused();
    const id = t.held()[0].id;
    assert.equal(id, `f:${A}#7`);
    assert.deepEqual(t.linesOf(id), ["Medical Heritage Library"], "the defect: the kept version answers for the live id");
  } finally { ForceTree.plantGenOnRewriteOnly = false; }
});

// (max 2 below: a list too big to be one unit -- archive.org's grid, not a
// prose list, PLUGIN_GOAL 173.)
// 2026-10-18 (PLUGIN_GOAL 149): archive.org's search list rewrites a tile in
// place; a merged run still holds the tile's OLD line at that address while
// the tile's own new chunk holds the new one. The page draws the new one.
const multi = (id, parts) => ({ id, digest: digestOf(parts.map((p) => p[0]).join("|")), lines: parts.map(([t, k]) => line(t, at(k, 3))) });
function rewritten() {
  const t = new ForceTree(A);
  t.apply({ v: 1, dict: DICT, chunks: [multi(1, [["old A", 1], ["old B", 2], ["old C", 3]])], removed: [], stats: { dictSize: DICT.length } });
  t.apply({ v: 1, dict: [], chunks: [multi(2, [["new B", 2]])], removed: [], stats: { dictSize: DICT.length } });
  return t;
}
test("an address two live chunks hold resolves to the newest content", () => {
  const u = rewritten().chunkForElement("/html/body/main/section[2]/p", 3, 2);
  assert.equal(u && u.id, `f:${A}#2`);
  assert.equal(u.at, "/html/body/main/section[2]");
});
test("planted (plantMostLines): the stale run answers", () => {
  ForceTree.plantMostLines = true;
  try { assert.equal(rewritten().chunkForElement("/html/body/main/section[2]/p", 3, 2).id, `f:${A}#1`); }
  finally { ForceTree.plantMostLines = false; }
});
test("an item with no lines yet has no unit -- never its neighbours", () => {
  assert.equal(rewritten().chunkForElement("/html/body/main/section[4]/p", 3, 2), null);
});
test("planted (plantClimbPastList): the empty item opens the whole list", () => {
  ForceTree.plantClimbPastList = true;
  // max 3: the climb itself is what is planted (at max 2 the size cap stops it first)
  try { assert.equal(rewritten().chunkForElement("/html/body/main/section[4]/p", 3, 3).at, "/html/body/main"); }
  finally { ForceTree.plantClimbPastList = false; }
});

// 2026-10-18: "please ensure to resolve hyperlink tails to their domains" --
// a streamed chunk's link line arrived as the page wrote it
// (`/docs/transformers/...#transformers.Pipeline`) and its panel showed the tail.
test("a link's relative destination reads as an absolute url on the page's domain", () => {
  const D2 = ["body", "main", "p", "a", "#text"];
  const P = "https://huggingface.co/docs/transformers/quicktour";
  const drain = { v: 1, dict: D2, removed: [], stats: { dictSize: D2.length }, chunks: [{ id: 1, digest: 11, lines: [
    [0, "run inference with", [0, 1, 1, 1, 2, 1, 4, 1]],
    [0, "/docs/transformers/v5.20.1/en/main_classes/pipelines#transformers.Pipeline", [0, 1, 1, 1, 2, 1, 3, 1]],
    [0, "Pipeline", [0, 1, 1, 1, 2, 1, 3, 1, 4, 1]],
  ] }] };
  const t = new ForceTree(P); t.apply(drain);
  assert.deepEqual(t.linesOf(`f:${P}#1`), ["run inference with",
    "https://huggingface.co/docs/transformers/v5.20.1/en/main_classes/pipelines#transformers.Pipeline", "Pipeline"]);
  ForceTree.plantRelativeLinks = true;
  try {
    const u = new ForceTree(P); u.apply(drain);
    assert.equal(u.linesOf(`f:${P}#1`)[1], "/docs/transformers/v5.20.1/en/main_classes/pipelines#transformers.Pipeline");
  } finally { ForceTree.plantRelativeLinks = false; }
});

// G-251 (2026-10-18): one chunk per bandcamp track row; the row's title block
// holds three lines of its own. The image and the title are PARTS of the row:
// both resolve to the row, not to their own sub-blocks.
function rowsTree() {
  const t = new ForceTree(A);
  const row = (k) => {
    const S = [0, 1, 1, 1, 2, k];
    return { id: k, digest: digestOf("row" + k), lines: [
      line(`play ${k}`, [...S, 3, 1, 5, 1]),
      line(`cover ${k}`, [...S, 4, 2, 4, 1, 4, 1, 5, 1]),
      line(`title ${k}`, [...S, 4, 2, 4, 1, 3, 1, 5, 1]),
      line(`from ${k}`, [...S, 4, 2, 4, 1, 3, 2, 5, 1]),
      line(`by ${k}`, [...S, 4, 2, 4, 1, 3, 3, 5, 1]),
    ] };
  };
  t.apply({ v: 1, dict: DICT, chunks: [1, 2, 3, 4].map(row), removed: [], stats: { dictSize: DICT.length } });
  return t;
}
test("a row's cover and its title resolve to the same unit: the row", () => {
  const t = rowsTree();
  const addrs = t.addrsOf(t.held().find((h) => /#3$/.test(h.id)).id);
  const parent = (a) => a.slice(0, a.lastIndexOf("/"));
  const cover = parent(addrs[1]), title = parent(parent(addrs[2]));
  const a = t.chunkForElement(cover), b = t.chunkForElement(title + "/p");
  assert.ok(a && b, "both resolve");
  assert.equal(a.at, b.at);
  assert.ok(a.at.endsWith("/section[3]"), "the row itself: " + a.at);
  ForceTree.plantSubUnit = true;
  try { assert.notEqual(t.chunkForElement(title + "/p").at, a.at, "planted: the title block alone"); }
  finally { ForceTree.plantSubUnit = false; }
});
