import { test } from "node:test";
import assert from "node:assert/strict";
import { browserCellUrl, toolCellFor } from "../src/toolbind.ts";

const F = "`".repeat(3);
const body = (s) => JSON.parse(s.split("\n")[1]);

test("+ tool binds to the note's own browser cell, chunks on (Item 201)", () => {
  const note = "# n\n\n" + F + "browser\nhttps://example.org/page\n" + F + "\n";
  assert.equal(browserCellUrl(note), "https://example.org/page");
  const t = toolCellFor(note, "https://pane.example/");
  assert.ok(t.startsWith(F + "tool\n") && t.trimEnd().endsWith(F));
  assert.deepEqual(body(t).browser.url, "https://example.org/page");
  assert.equal(body(t).browser.chunks, true);
});

test("no browser cell: the pane's page; neither: the search toolspace", () => {
  assert.equal(body(toolCellFor("# n\n", "https://pane.example/")).browser.url, "https://pane.example/");
  assert.ok("search" in body(toolCellFor("# n\n", "")));
  assert.ok("search" in body(toolCellFor("# n\n", "about:blank")));
});
