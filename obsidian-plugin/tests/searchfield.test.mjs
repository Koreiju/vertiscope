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

// Item 109: a held arrow key steps faster the longer it is held.
{
  const { holdStep } = await import("../src/searchfield.ts");
  assert.equal(holdStep(0), 1);
  assert.equal(holdStep(400), 1);
  assert.ok(holdStep(1600) > holdStep(1000) && holdStep(1000) >= holdStep(400));
  assert.equal(holdStep(60000), 100);
  // Monotone: never slows while held.
  let last = 0;
  for (let t = 0; t < 8000; t += 50) { const s = holdStep(t); assert.ok(s >= last); last = s; }
}

// Item 106: a re-rank diff counts what was added, removed and moved.
{
  const { rankDiff, barGradient } = await import("../src/searchfield.ts");
  const h = (c) => ({ cid: c, url: "" });
  assert.deepEqual(rankDiff([h("a"), h("b"), h("c")], [h("a"), h("b"), h("c")]), { added: 0, removed: 0, moved: 0 });
  assert.deepEqual(rankDiff([h("a"), h("b"), h("c")], [h("d"), h("a"), h("c")]), { added: 1, removed: 1, moved: 1 });
  // The bar's gradient: brightest stop at the scrolled index.
  const g = barGradient(5, 3);
  const alphas = [...g.matchAll(/rgba\(255,255,255,([\d.]+)\)/g)].map((m) => Number(m[1]));
  assert.equal(alphas.length, 5);
  assert.equal(alphas.indexOf(Math.max(...alphas)), 2);
  assert.equal(barGradient(0, 0), "none");
}
console.log("searchfield: hold, diff, gradient ok");
