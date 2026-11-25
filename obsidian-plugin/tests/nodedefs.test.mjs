// G-409 / B14: a widget edited in place rewrites that one default in the cell.
import test from "node:test";
import assert from "node:assert/strict";
import { setDefault, pyLiteral } from "../src/nodedefs.ts";

const F = "```";
const NOTE = ["# g", "", F + "python", "from typing import Literal",
  "def scan(url: str, k: int = 8, mode: Literal['fast', 'deep'] = 'fast', driver: object = None) -> list:",
  "    return [url] * k", "class Box:", "    def __init__(self, size: float = 1.0): self.size = size",
  "    def area(self) -> float: return self.size ** 2", F, ""].join("\n");

test("one default rewritten, nothing else", () => {
  const a = setDefault(NOTE, "scan", "k", "12");
  assert.ok(a.includes("k: int = 12, mode"));
  assert.equal(a.replace("k: int = 12", "k: int = 8"), NOTE);
  assert.ok(setDefault(NOTE, "scan", "mode", pyLiteral("deep")).includes(`= "deep", driver`));
  assert.ok(setDefault(NOTE, "Box", "size", "2.5").includes("size: float = 2.5)"));
});

test("a parameter with no default, or no such def, is refused", () => {
  assert.equal(setDefault(NOTE, "scan", "url", "1"), null);
  assert.equal(setDefault(NOTE, "nope", "k", "1"), null);
});

test("a trait's default: the first argument of its trait call", async () => {
  const { setTraitDefault } = await import("../src/nodedefs.ts");
  const T = "import traitlets\nclass Knob(traitlets.HasTraits):\n    level = traitlets.Int(3)\n    name = traitlets.Unicode('a', help='x')\n";
  assert.ok(setTraitDefault(T, "Knob", "level", "5").includes("level = traitlets.Int(5)\n"));
  assert.ok(setTraitDefault(T, "Knob", "name", '"b"').includes(`name = traitlets.Unicode("b", help='x')`));
  assert.equal(setTraitDefault(T, "Nope", "level", "5"), null);
});
