// G-396 (PLUGIN_GOAL 183): the ego canvas note -> its sections, in order.
import test from "node:test";
import assert from "node:assert/strict";
import { sectionsOf, lineFor } from "../src/canvasparse.ts";

const NOTE = ["---", "domvec: canvas", "---", "", "![[domvec/ego]]", "the reader's own words", "[[domvec/graph/notebook 3]]", "![[domvec/graph/chat 1|alias]]", ""].join("\n");

test("embeds are contained, links are pulled out, prose is kept and is no section", () => {
  assert.deepEqual(sectionsOf(NOTE).map((s) => [s.path, s.embedded, s.line]),
    [["domvec/ego.md", true, 4], ["domvec/graph/notebook 3.md", false, 6], ["domvec/graph/chat 1.md", true, 7]]);
});

test("frontmatter lines are never sections", () => {
  assert.equal(sectionsOf("---\nx: ![[no]]\n---\n![[yes]]\n").length, 1);
});

test("a section's line round-trips", () => {
  for (const e of [true, false]) assert.deepEqual(sectionsOf(lineFor("a/b c.md", e)).map((s) => [s.path, s.embedded]), [["a/b c.md", e]]);
});
