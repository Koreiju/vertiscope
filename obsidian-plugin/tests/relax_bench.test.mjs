// Benchmark-shaped test for relaxCloud at the scale of the url view's page
// pass: ~1,150 page spheres with a long-tailed radius (a few big pages).
import { test } from "node:test";
import assert from "node:assert/strict";
import { relaxCloud, relaxConfig } from "../src/camera.ts";

function cloud(n, seed = 7) {
  let s = seed;
  const rnd = () => ((s = (s * 1103515245 + 12345) >>> 0) / 4294967296);
  const pos = [], radii = [];
  for (let i = 0; i < n; i++) {
    pos.push([(rnd() - 0.5) * 900, (rnd() - 0.5) * 900, (rnd() - 0.5) * 900]);
    radii.push(i % 97 === 0 ? 60 + rnd() * 60 : 2 + rnd() * 6);   // a few big pages
  }
  return { pos, radii };
}
function overlaps(p, R, S) {
  let o = 0;
  for (let i = 0; i < p.length; i++) for (let j = i + 1; j < p.length; j++)
    if (Math.hypot(p[i][0] - p[j][0], p[i][1] - p[j][1], p[i][2] - p[j][2]) < (R[i] + R[j]) * S * 0.999) o++;
  return o;
}
test("the page pass relaxes ~1,150 long-tailed spheres quickly and leaves none overlapping", () => {
  const { pos, radii } = cloud(1150);
  const t0 = performance.now();
  const rel = relaxCloud([1e12, 1e12, 1e12], pos, radii, 0, Infinity, { safety: 1.15, anchor: 0 });
  const ms = performance.now() - t0;
  console.log(`relaxCloud n=1150: ${ms.toFixed(0)} ms, ${rel.iterations} iterations`);
  assert.equal(overlaps(rel.pos, radii, 1.15), 0);
  assert.ok(ms < 250, `${ms.toFixed(0)} ms`);
});

test("planted (plantNoTouchTolerance): a touching pair pushed forever runs every iteration", () => {
  const { pos, radii } = cloud(1150);
  const time = (planted) => {
    relaxConfig.plantNoTouchTolerance = planted;
    try { const t0 = performance.now(); relaxCloud([1e12, 1e12, 1e12], pos, radii, 0, Infinity, { safety: 1.15, anchor: 0 }); return performance.now() - t0; }
    finally { relaxConfig.plantNoTouchTolerance = false; }
  };
  const clean = time(false), planted = time(true);
  console.log(`clean ${clean.toFixed(0)} ms vs planted ${planted.toFixed(0)} ms`);
  assert.ok(planted > 2 * clean, `${planted.toFixed(0)} vs ${clean.toFixed(0)}`);
});
