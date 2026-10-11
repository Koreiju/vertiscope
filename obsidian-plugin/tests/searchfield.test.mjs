// PLUGIN_GOAL 87/88: the scroll's position -> how many results are shown, and
// a shown result's brightness by its distance from the scrolled index.
import test from "node:test";
import assert from "node:assert/strict";
import { visibleCount, brightness } from "../src/searchfield.ts";

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
