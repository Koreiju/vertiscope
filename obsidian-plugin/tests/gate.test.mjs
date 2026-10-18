// G-249: an error response or a bot check is a page STATE, not the page.
import test from "node:test";
import assert from "node:assert/strict";
import { build } from "esbuild";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const out = join(mkdtempSync(join(tmpdir(), "gate-")), "gate.mjs");
await build({ entryPoints: ["src/gate.ts"], bundle: true, format: "esm", platform: "node", outfile: out, logLevel: "silent" });
const { pageGate, GATE_SMALL_LINES } = await import(pathToFileURL(out).href);

test("checks and errors are gated by title or status", () => {
  assert.equal(pageGate(200, "DDoS-Guard").kind, "check");
  assert.equal(pageGate(200, "Just a moment...").kind, "check");
  assert.equal(pageGate(502, "annas-archive.org").kind, "error");
  assert.equal(pageGate(200, "502 Bad Gateway").kind, "error");
  assert.equal(pageGate(403, "").kind, "check");
});
test("a check that answers 200 with a plain title is read from its few lines", () => {
  const v = pageGate(200, "annas-archive.pk", ["Checking your browser before accessing annas-archive.pk", "DDoS-Guard"]);
  assert.equal(v.kind, "check");
});
test("non-vacuity: the page itself, and pages ABOUT checks, are not gated", () => {
  assert.equal(pageGate(200, "Anna's Archive").why, "");
  assert.equal(pageGate(200, "DDoS-Guard - Wikipedia").why, "");       // anchored: about, not one
  assert.equal(pageGate(0, "Search").why, "");
  // a long article that quotes the phrase is not a check page
  const long = Array.from({ length: GATE_SMALL_LINES + 5 }, (_, i) => i === 3 ? "checking your browser before accessing" : "line " + i);
  assert.equal(pageGate(200, "How bot checks work", long).why, "");
});
