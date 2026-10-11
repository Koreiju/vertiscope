// R-1: typing the four symbols `[]()` makes the bracket contents a retrieval
// query; the link goes between the parentheses. Not on a short bracket, not
// on a link already filled, not on an image.
import test from "node:test";
import assert from "node:assert/strict";
import { gestureIn } from "../src/gesture.ts";

test("[query]( with the paired ) after the cursor is a gesture", () => {
  const line = "see [patricia trie]()";
  const ch = line.length - 1;                     // between ( and )
  assert.deepEqual(gestureIn(line, ch), { ch, query: "patricia trie" });
});

test("[query]() with the cursor after it is a gesture; the link goes inside", () => {
  const line = "see [patricia trie]()";
  assert.deepEqual(gestureIn(line, line.length), { ch: line.length - 1, query: "patricia trie" });
});

test("what is not a gesture", () => {
  assert.equal(gestureIn("[ab]()", 5), null);                         // two characters
  assert.equal(gestureIn("[radix tree](https://x)", 13), null);         // already a link
  assert.equal(gestureIn("![an okapi]()", 12), null);                   // an image
  assert.equal(gestureIn("[radix tree] ()", 14), null);                 // not the four symbols
  assert.equal(gestureIn("[radix tree](", 13), null);                   // no ) yet
});
