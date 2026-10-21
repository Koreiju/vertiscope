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

// PLUGIN_GOAL 154 (2026-10-17): "showing 2000 / 2000 results, 29 retrieved of
// 587 matching" -- the fields' bound is what matches, not a fixed 2000.
{
  const { fieldBounds } = await import("../src/searchfield.ts");
  test("k/n are bounded by the number matching", () => {
    assert.deepEqual(fieldBounds(2000, 2000, 587), { k: 587, n: 587, cap: 587 });
    assert.deepEqual(fieldBounds(20, 50, 587), { k: 20, n: 50, cap: 587 });
    // more than 2000 match: n may go past 2000
    assert.equal(fieldBounds(3000, 5000, 4200).n, 4200);
    // before any answer: the ask's ceiling, never 2000
    assert.equal(fieldBounds(20, 3000, 0).n, 3000);
  });
  test("planted (fixed cap): 2000 / 2000 over 587 matching, as the reader saw", () => {
    assert.deepEqual(fieldBounds(2000, 2000, 587, true), { k: 2000, n: 2000, cap: 2000 });
    assert.equal(fieldBounds(3000, 5000, 4200, true).n, 2000);
  });
}

// G-222 (PLUGIN_GOAL 151): the strip stands where the bar stands, and is lit
// as the nodes are.
{
  const { stripScrollFor, stripLight, brightness } = await import("../src/searchfield.ts");
  test("the strip's scroll follows the bar's fraction", () => {
    assert.equal(stripScrollFor(0, 2000, 500), 0);
    assert.equal(stripScrollFor(1, 2000, 500), 1500);
    assert.equal(stripScrollFor(0.5, 2000, 500), 750);
    assert.equal(stripScrollFor(0.5, 400, 500), 0);         // nothing to scroll
    assert.equal(stripScrollFor(NaN, 2000, 500), 0);
  });
  test("a strip item is lit as its node: brightest at the frontier, dim past it", () => {
    assert.equal(stripLight(4, 5, 5), brightness(4, 5));
    assert.ok(stripLight(0, 5, 5) < stripLight(4, 5, 5));
    assert.equal(stripLight(7, 5, 5), 0.18);
  });
}
