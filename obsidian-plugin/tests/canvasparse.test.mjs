// G-401 (spec §12c): the ego slate's component fields -- `\tname\t{ref}` naming a note.
import test from "node:test";
import assert from "node:assert/strict";
import { componentFieldsOf, fieldLine, oldSectionsOf, withFields } from "../src/canvasparse.ts";

const NOTES = new Set(["outline_note", "notebook 3", "browser"]);
const isNote = (r) => NOTES.has(r);
const EGO = ["---", "domvec: slate", "---", "ego\t{unfolded} {view}", "\tview\tmap", "\tkeys\t{keys}", "\tplan\t{search.results}",
             "\tsearch", "\t\tquery\t", "\toutline_note\t{outline_note}", "\t\tnested\t{browser}", "\tnotebook 3\t{notebook 3}", ""].join("\n");

test("only rank-1 fields whose one {ref} names a note are components", () => {
  assert.deepEqual(componentFieldsOf(EGO, isNote).map((f) => [f.name, f.ref, f.line]),
    [["outline_note", "outline_note", 9], ["notebook 3", "notebook 3", 11]]);
});

test("non-vacuous: with every ref taken for a note, the cockpit's own fields WOULD count", () => {
  // keys, plan, outline_note, notebook 3 -- the rank-2 `nested {browser}` line is never a component
  assert.deepEqual(componentFieldsOf(EGO, () => true).map((f) => f.name), ["keys", "plan", "outline_note", "notebook 3"]);
});

test("frontmatter is never a field", () => {
  assert.equal(componentFieldsOf("---\n\tx\t{browser}\n---\nego\n", isNote).length, 0);
});

test("a field line round-trips, and withFields appends at the tree's end", () => {
  const t = withFields("ego\n\tview\tmap\n\n", ["notebook 3"]);
  assert.equal(t, "ego\n\tview\tmap\n" + fieldLine("notebook 3") + "\n");
  assert.deepEqual(componentFieldsOf(t, isNote).map((f) => f.name), ["notebook 3"]);
});

test("the 183 canvas note's order is read as paths", () => {
  assert.deepEqual(oldSectionsOf("---\ndomvec: canvas\n---\n![[domvec/ego]]\n[[a/b c]]\n![[x|alias]]\nprose\n"), ["domvec/ego.md", "a/b c.md", "x.md"]);
});
