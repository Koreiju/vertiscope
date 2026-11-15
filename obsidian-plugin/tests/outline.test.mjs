// PLUGIN_GOAL 159: a note unfolds by its own recursion -- headings, cells,
// a cell's definitions. `outline.ts` mirrors `refs.py` by hand; both are held
// to ONE expected file, so the two spellings cannot drift apart unseen.
import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { outline } from "../src/outline.ts";

const fx = new URL("../../tests/fixtures/", import.meta.url);
const note = readFileSync(new URL("outline_note.md", fx), "utf-8");
const expected = JSON.parse(readFileSync(new URL("outline_expected.json", fx), "utf-8"));

test("every address unfolds exactly as the sidecar's outline does", () => {
  for (const [name, lines] of Object.entries(expected)) assert.deepEqual(outline(note, name), lines, name);
});

test("planted: a CRLF note and a flat first-lines reading are both caught", () => {
  // CRLF is the vault's own line ending on Windows: it must not change a rank.
  assert.deepEqual(outline(note.replace(/\n/g, "\r\n"), "Nb#cell 2"), expected["Nb#cell 2"]);
  // The pre-outline reading (first lines) does not reach a heading's section.
  const flat = note.split("\n").map((l) => l.trim()).filter((l) => l && !/^(<!--|```|~~~|\||---)/.test(l)).slice(0, 12);
  assert.notDeepEqual(flat, expected["Nb"]);
});

import { unfoldedOf, withUnfolded } from "../src/outline.ts";

const EGO = "---\ndomvec: slate\n---\nego\n\tview\tmap\n\tplay\tfalse\n\tsearch\n\t\tquery\t\n\t\tresults\n\t\t\t1\tx\n";

test("the ego's unfolded boxes are a field of its note, written and read back", () => {
  const a = withUnfolded(EGO, new Map([["notes/Nb", ["Nb", "Nb#cell 2"]]]));
  assert.match(a, /\tplay\tfalse\n\tunfolded\n\t\tnotes\/Nb\t\{Nb\} \{Nb#cell 2\}\n\tsearch\n/);
  assert.deepEqual([...unfoldedOf(a)], [["notes/Nb", ["Nb", "Nb#cell 2"]]]);
  // A second note joins; the first's row is replaced, not appended.
  const b = withUnfolded(a, new Map([["Other", ["Other#Intro"]], ["notes/Nb", ["Nb"]]]));
  assert.deepEqual([...unfoldedOf(b)], [["notes/Nb", ["Nb"]], ["Other", ["Other#Intro"]]]);
  // Folded shut: the row goes, the field stays, nothing else moved.
  const c = withUnfolded(b, new Map([["notes/Nb", []], ["Other", []]]));
  assert.equal(c, EGO.replace("\tplay\tfalse\n", "\tplay\tfalse\n\tunfolded\n"));
  // The search's rows were never touched.
  for (const s of [a, b, c]) assert.match(s, /\t\tresults\n\t\t\t1\tx\n$/);
});

test("planted: rows written under the wrong depth are not read as the ego's", () => {
  const wrong = EGO.replace("\tplay\tfalse\n", "\tplay\tfalse\n\tunfolded\n\tnotes/Nb\t{Nb}\n");
  assert.equal(unfoldedOf(wrong).size, 0);
  // CRLF in, CRLF out.
  const crlf = withUnfolded(EGO.replace(/\n/g, "\r\n"), new Map([["Nb", ["Nb"]]]));
  assert.ok(!/[^\r]\n/.test(crlf) && unfoldedOf(crlf).get("Nb")?.[0] === "Nb");
});
