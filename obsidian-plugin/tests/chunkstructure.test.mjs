// P-B7: the chunks a hovered chunk is embedded among, read from the trie --
// its node's parent, and the other chunks under it.
import test from "node:test";
import assert from "node:assert/strict";
import { chunkNode, embedded } from "../src/chunkstructure.ts";

const X = {
  a: ["/html/body/main/ul/li[1]/h3/text()[1]", "/html/body/main/ul/li[1]/p/text()[1]"],
  b: ["/html/body/main/ul/li[2]/h3/text()[1]", "/html/body/main/ul/li[2]/p/text()[1]"],
  c: ["/html/body/main/ul/li[3]/p/text()[1]"],
  nav: ["/html/body/nav/a[1]/text()[1]", "/html/body/nav/a[2]/text()[1]"],
  frame: ["/html/body/main/h1/text()[1]", "/html/body/main/ul/li[1]/@title"],
};
const of = (c) => X[c] || [];

test("a chunk's node is the element run its addresses share", () => {
  assert.deepEqual(chunkNode(X.a), ["html", "body", "main", "ul", "li[1]"]);
  assert.deepEqual(chunkNode(X.c), ["html", "body", "main", "ul", "li[3]", "p"]);
});

test("the other items of the same list are the structure; the nav is not", () => {
  const got = embedded("a", Object.keys(X), of);
  assert.equal(got.container, "/html/body/main/ul");
  assert.deepEqual(got.siblings.sort(), ["b", "c"]);
});

test("a chunk whose node holds the hovered one is its frame, not a sibling", () => {
  const got = embedded("a", ["a", "frame", "b"], of);
  assert.ok(!got.siblings.includes("frame"));
});

test("alone in its container, the walk goes up; alone in the page, nothing", () => {
  const solo = { s: ["/html/body/main/section/div/p/text()[1]"], t: ["/html/body/main/aside/p/text()[1]"] };
  const got = embedded("s", ["s", "t"], (c) => solo[c] || []);
  assert.equal(got.container, "/html/body/main");
  assert.deepEqual(got.siblings, ["t"]);
  assert.deepEqual(embedded("s", ["s"], (c) => solo[c] || []), { container: "", siblings: [] });
});
