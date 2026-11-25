// G-238: a multi-component wireframe, its components and their order.
import test from "node:test";
import assert from "node:assert/strict";
import { defsOf, orderDefs, isWireframe } from "../src/wiredefs.ts";

const Q = '"""';
const CELL = [
  "def sum_squares(xs):", "    " + Q + "Sum of square(x) for each x in xs." + Q, "    ...", "",
  "def square(x):", "    " + Q + "Return x squared." + Q, "    ...", "",
  "def done(a):", "    " + Q + "Already written." + Q, "    return a",
].join("\n");

test("components: two wireframes, one written function", () => {
  assert.deepEqual(defsOf(CELL).map((x) => [x.name, x.wire]), [["sum_squares", true], ["square", true], ["done", false]]);
  assert.ok(isWireframe(CELL));
  assert.ok(!isWireframe("def f(x):\n    return x\n"));
});

test("order: a component after the ones its docstring names", () => {
  assert.deepEqual(orderDefs(defsOf(CELL)).map((x) => x.name), ["square", "sum_squares"]);
});
