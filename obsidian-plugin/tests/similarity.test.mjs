// G-194 (2026-10-17): "apply efficient scale-aware ICP over the URL nodes so
// that we render the 3D coordinates from their closest most previous
// registered camera pose".
import { test } from "node:test";
import assert from "node:assert/strict";
import { similarityFit, similarityInverse } from "../src/camera.ts";

const rand = (k) => { let x = Math.sin(k * 12.9898) * 43758.5453; return x - Math.floor(x); };
const pts = Array.from({ length: 40 }, (_, i) => [rand(i) * 600 - 300, rand(i + 99) * 400 - 200, rand(i + 7) * 200 - 100]);
const rotZ = (a) => [[Math.cos(a), -Math.sin(a), 0], [Math.sin(a), Math.cos(a), 0], [0, 0, 1]];
const rotX = (a) => [[1, 0, 0], [0, Math.cos(a), -Math.sin(a)], [0, Math.sin(a), Math.cos(a)]];
const mul = (A, B) => A.map((r) => B[0].map((_, c) => r.reduce((s, v, k) => s + v * B[k][c], 0)));
const apply = (s, R, t, p) => [0, 1, 2].map((r) => s * (R[r][0] * p[0] + R[r][1] * p[1] + R[r][2] * p[2]) + t[r]);

test("a refit that rotated, scaled and moved the cloud is registered exactly", () => {
  const R = mul(rotZ(0.9), rotX(-0.4)), s = 1.7, t = [120, -40, 300];
  const moved = pts.map((p) => apply(s, R, t, p));
  // new -> old: src is the NEW fit, dst the OLD
  const f = similarityFit(moved, pts);
  assert.ok(f && f.rms < 1e-6, "rms " + (f && f.rms));
  assert.ok(Math.abs(f.s - 1 / s) < 1e-6, "scale " + f.s);
  // the camera carried into the new frame sees the new points where it saw the old
  const cam = [50, 20, 1500];
  const camNew = similarityInverse(f, cam);
  const back = apply(s, R, t, cam);
  assert.ok(Math.hypot(camNew[0] - back[0], camNew[1] - back[1], camNew[2] - back[2]) < 1e-6);
});

test("a refit that changed shape reports its residual", () => {
  const noisy = pts.map((p, i) => [p[0] + (rand(i + 3) - 0.5) * 80, p[1], p[2]]);
  const f = similarityFit(noisy, pts);
  assert.ok(f.rms > 5 && f.rms < 40, "rms " + f.rms);
});

test("null arm: too few matched pages is no registration", () => {
  assert.equal(similarityFit(pts.slice(0, 2), pts.slice(0, 2)), null);
});
