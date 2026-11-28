import { test } from "node:test";
import assert from "node:assert/strict";
import { closeOpenFence } from "../src/streamtext.ts";
import { mdLink } from "../src/egolinks.ts";

const F = "`".repeat(3);

test("a partial reply inside a fence is closed; a closed one is left alone (G-462)", () => {
  assert.equal(closeOpenFence("code:\n" + F + "python\nx = 1"), "code:\n" + F + "python\nx = 1\n" + F);
  const whole = "a\n" + F + "python\nx\n" + F + "\nb";
  assert.equal(closeOpenFence(whole), whole);
  assert.equal(closeOpenFence("no fences"), "no fences");
});

test("mdLink writes [title](encodeURI(path)), never [[wiki]] (G-461)", () => {
  assert.equal(mdLink("domvec/graph/notebook 9.md"), "[notebook 9](domvec/graph/notebook%209.md)");
  assert.equal(mdLink("domvec/graph/x.md", "a [b] c"), "[a b c](domvec/graph/x.md)");
  assert.ok(!mdLink("domvec/graph/l2 chat 001 reply.md").includes("[["));
});
