// PLUGIN_GOAL 87/88: the scroll's position -> how many results are shown, and
// a shown result's brightness by its distance from the scrolled index.
import test from "node:test";
import assert from "node:assert/strict";
import { visibleCount, brightness, softIndex, fade } from "../src/searchfield.ts";

test("the very left shows the first result, the very right all k", () => {
  assert.equal(visibleCount(0, 20), 1);
  assert.equal(visibleCount(1, 20), 20);
  assert.equal(visibleCount(0.5, 21), 11);
  assert.equal(visibleCount(0.3, 0), 0);
  assert.equal(visibleCount(NaN, 5), 1);
});

test("the scrolled index is brightest and the far end dimmest; unshown is dark", () => {
  assert.equal(brightness(4, 5), 1);
  assert.ok(Math.abs(brightness(0, 5) - 0.2) < 1e-9);
  assert.ok(brightness(2, 5) > brightness(1, 5));
  assert.equal(brightness(5, 5), 0);
  assert.equal(brightness(0, 1), 1);
});

test("the soft index brightens the frontier smoothly", () => {
  assert.equal(softIndex(0, 5), 1);
  assert.equal(softIndex(1, 5), 5);
  assert.equal(visibleCount(0.125, 5), 2);          // s = 1.5: the second is part-way in
  assert.equal(fade(1, 1.5), 0.5);
  assert.ok(brightness(1, 1.5) > 0 && brightness(1, 1.5) < brightness(1, 2));
  let last = -1;
  for (let s = 1; s <= 3.0001; s += 0.05) { const b = brightness(2, s); assert.ok(b >= last - 1e-9); last = b; }
});
