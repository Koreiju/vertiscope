// G-230 (PLUGIN_GOAL 159): the per-hover spread factor.
import { test } from "node:test";
import assert from "node:assert/strict";
import { spreadFactor } from "../src/spread.ts";

test("no overlap: no spread", () => {
  assert.equal(spreadFactor([[0, 0, 0], [10, 0, 0]], [1, 1]), 1);
});
test("overlapping pictures: the scale that clears every pair, with the gap", () => {
  const k = spreadFactor([[0, 0, 0], [1, 0, 0], [0, 4, 0]], [1, 1, 1], 1.15);
  assert.ok(Math.abs(k - 2.3) < 1e-9);          // the 1-apart pair needs 2.3
  // after scaling, every pair clears
  const P = [[0, 0, 0], [k, 0, 0], [0, 4 * k, 0]];
  for (let i = 0; i < 3; i++) for (let j = i + 1; j < 3; j++) assert.ok(Math.hypot(P[i][0] - P[j][0], P[i][1] - P[j][1]) >= 2 * 1.15 - 1e-9);
});
test("coincident nodes: capped, not infinite", () => {
  assert.equal(spreadFactor([[1, 1, 1], [1, 1, 1]], [1, 1], 1.15, 6), 6);
});
