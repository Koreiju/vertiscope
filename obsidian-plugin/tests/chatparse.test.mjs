// G-394 (PLUGIN_GOAL 182): a conversation note -> turns -> typed blocks ->
// addresses; a selection inside a code block -> its line range.
import test from "node:test";
import assert from "node:assert/strict";
import { parseConversation, blocksOf, addressOf, rangeOf } from "../src/chatparse.ts";

const F = "```";
const NOTE = ["---", "domvec: chat", "---", "", "## You", "", "add two numbers", "",
  "## Nous Hermes 2 Mistral DPO", "", "Here:", "", F + "python", "def add(a, b):", "    ## not a heading", "    return a + b", F, "", "Done.", ""].join("\n");

test("turns are the ## headings; a heading-like line INSIDE a fence is code", () => {
  const { turns, draft } = parseConversation(NOTE);
  assert.equal(draft, "");
  assert.deepEqual(turns.map((t) => [t.who, t.label]), [["you", "You"], ["model", "Nous Hermes 2 Mistral DPO"]]);
  assert.deepEqual(turns[1].blocks.map((b) => [b.kind, b.lang]), [["prose", ""], ["code", "python"], ["prose", ""]]);
  assert.ok(turns[1].blocks[1].text.includes("## not a heading"));
});

test("an old chat note's body is the input box's draft, not a turn", () => {
  const { turns, draft } = parseConversation("---\ndomvec: chat\n---\n\nAsk here; snap cells.\n");
  assert.equal(turns.length, 0);
  assert.equal(draft, "Ask here; snap cells.");
});

test("a reply still streaming keeps its open fence as a code block", () => {
  assert.deepEqual(blocksOf("Sure:\n\n" + F + "js\nlet x = 1").map((b) => b.kind), ["prose", "code"]);
});

test("addresses name the turn, the block and a pulled line range", () => {
  assert.equal(addressOf("a/c.md", 1, 1), "vault://a/c.md#turn2/block2");
  assert.equal(addressOf("a/c.md", 1, 1, [2, 3]), "vault://a/c.md#turn2/block2/L2-3");
});

test("a selection -> its lines; one that is not in the code -> null", () => {
  const code = "def add(a, b):\n    total = a + b\n    print(total)\n    return total";
  assert.deepEqual(rangeOf(code, "    total = a + b\n    print(total)"), [2, 3]);
  assert.deepEqual(rangeOf(code, "\n    return total\n"), [4, 4]);
  assert.equal(rangeOf(code, "nowhere"), null);
});

test("a code block knows its fence's line in the WHOLE note -- the kernel's cell identity (182)", () => {
  const { turns } = parseConversation(NOTE);
  const code = turns[1].blocks[1];
  assert.equal(code.line, 12);
  assert.equal(NOTE.split("\n")[code.line], F + "python");
  // The same block twice: two cells, two lines -- never one identity.
  const twice = NOTE + "\n## You\n\nagain\n\n## Nous Hermes 2 Mistral DPO\n\n" + F + "python\ndef add(a, b):\n    ## not a heading\n    return a + b\n" + F + "\n";
  const lines = parseConversation(twice).turns.flatMap((t) => t.blocks).filter((b) => b.kind === "code").map((b) => b.line);
  assert.equal(lines.length, 2);
  assert.notEqual(lines[0], lines[1]);
  for (const l of lines) assert.equal(twice.split("\n")[l], F + "python");
});
