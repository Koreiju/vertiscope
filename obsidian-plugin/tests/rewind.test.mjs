// L-2..L-9: the notebook chat's cells and rewind (src/rewind.ts).
import test from "node:test";
import assert from "node:assert/strict";
import { build } from "esbuild";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

const out = join(mkdtempSync(join(tmpdir(), "rewind-")), "rewind.mjs");
await build({ entryPoints: ["src/rewind.ts"], bundle: true, format: "esm", platform: "node", outfile: out, logLevel: "silent" });
const { cellsOf, cellAt, rewind, parseRewind } = await import(pathToFileURL(out).href);

const NOTE = [
  "---", "tags: [nb]", "---",
  "# Loading", "We read the table.", "",
  "```python", "import pandas as pd", "df = pd.read_csv('x.csv')", "```",
  "<!-- nb-output hash=ab count=1 status=error -->", "```", "FileNotFoundError: x.csv", "```", "<!-- /nb-output -->", "",
  "Then we plot it.", "",
  "```python", "df.plot()", "```",
].join("\n");

test("cells: a heading block, code WITH its output, a paragraph, code", () => {
  const cells = cellsOf(NOTE);
  assert.deepEqual(cells.map((c) => c.kind), ["markdown", "code", "markdown", "code"]);
  assert.match(cells[1].text, /FileNotFoundError/);          // the output rewinds with its code
  assert.ok(!cells.some((c) => /tags:/.test(c.text)));         // front matter is not a cell
});

test("the cell under the cursor, and the nearest above a blank line", () => {
  const cells = cellsOf(NOTE);
  assert.equal(cellAt(cells, 7), 1);                           // inside the code
  assert.equal(cellAt(cells, 12), 1);                          // inside its output
  assert.equal(cellAt(cells, 15), 1);                          // the blank line after
  assert.equal(cellAt(cells, 19), 3);
});

test("rewind ends at the selected cell and goes backwards, oldest first", () => {
  const cells = cellsOf(NOTE);
  const r = rewind(cells, 2, { nCtx: 8192, safety: 0.4 });
  assert.deepEqual(r.cells.map((c) => c.kind), ["markdown", "code", "markdown"]);
  assert.ok(!r.cells.some((c) => /df\.plot/.test(c.text)));    // nothing after the terminal cell
});

test("the prompt's count limits the rewind; the budget caps it", () => {
  const cells = cellsOf(NOTE);
  assert.equal(rewind(cells, 3, { nCtx: 8192, safety: 0.4, limit: 2 }).cells.length, 2);
  const tiny = rewind(cells, 3, { nCtx: 10, safety: 0.5 });     // 20 chars: only the terminal cell, cut
  assert.equal(tiny.cells.length, 1);
  assert.ok(tiny.cut && tiny.chars <= tiny.budget);
});

test("parseRewind takes @N out of the prompt", () => {
  assert.deepEqual(parseRewind("@3 why does this fail?"), { limit: 3, prompt: "why does this fail?" });
  assert.deepEqual(parseRewind("why? @12"), { limit: 12, prompt: "why?" });
  assert.deepEqual(parseRewind("email a@b.com"), { limit: null, prompt: "email a@b.com" });
});

test("a cell whose output changed is a new cell (its hash moves)", () => {
  const a = cellsOf(NOTE)[1].hash;
  const b = cellsOf(NOTE.replace("FileNotFoundError: x.csv", "   a  b\n0  1  2"))[1].hash;
  assert.notEqual(a, b);
});
