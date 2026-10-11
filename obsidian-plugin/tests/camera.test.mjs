// The projector's chunk clouds and its camera (2026-10-10).
//
// centredTelescope: "Not sure why there's this clumping happening ... with
// centroids still at the center" -- the forum's 186 chunks drew as a ball 95
// units off their url node, because offsets were taken from the page point.
// zoomFor: "fly-to-node should zoom initially, but preserve user zoom while
// still tracking during fly-throughs"; "some kind of debounce on ...
// re-setting the zoom action for 'new navigations'".
import { test } from "node:test";
import assert from "node:assert/strict";
import { centredTelescope, zoomFor } from "../src/camera.ts";

const mean = (ps) => [0, 1, 2].map((i) => ps.reduce((a, p) => a + p[i], 0) / ps.length);
const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);

// A page's chunks sitting all to one side of their page point, as UMAP left
// the forum: the cloud's own centre is 95 units off.
const root = [0, 0, 0];
const raw = [];
for (let i = 0; i < 60; i++) {
  const a = i * 2.399, z = 1 - (2 * i + 1) / 60, r = Math.sqrt(1 - z * z);
  raw.push([95 + 20 * r * Math.cos(a), 20 * r * Math.sin(a), 20 * z]);
}

test("the cloud is centred on its url node, inside the bound, shape kept", () => {
  const t = centredTelescope(root, raw, 60, 5);
  const pos = t.pos;
  assert.ok(Math.abs(t.centreOff - 95) < 1, "reports how far off the cloud was");
  assert.ok(dist(mean(pos), root) < 3, "centre on the node: " + dist(mean(pos), root));
  assert.ok(pos.every((p) => dist(p, root) <= 60 + 1e-6), "inside the bound");
  // Shape: the order of distances from the cloud's own centre is kept.
  const c = mean(raw);
  const before = raw.map((p) => dist(p, c));
  const after = pos.map((p) => dist(p, root));
  for (let i = 1; i < raw.length; i++) {
    if (before[i] > before[i - 1] + 1e-6) assert.ok(after[i] >= after[i - 1] - 1e-6);
  }
});

test("planted: telescoping from the page point leaves the cloud off-centre", () => {
  const t = centredTelescope(root, raw, 60, 5, true);
  assert.ok(dist(mean(t.pos), root) > 30, "off-centre: " + dist(mean(t.pos), root));
});

test("zoom on a navigation's first flight, the reader's distance after", () => {
  const st = { zoomedFor: "", zoomedAt: -1e9 };
  const a = zoomFor(st, "https://a.test/", 10000, 120, 45);
  assert.deepEqual(a, { zoom: true, distance: 45 });
  const b = zoomFor(st, "https://a.test/", 12000, 300, 45);    // the reader zoomed out to 300
  assert.deepEqual(b, { zoom: false, distance: 300 });
  const c = zoomFor(st, "https://b.test/", 20000, 300, 45);    // a new navigation
  assert.deepEqual(c, { zoom: true, distance: 45 });
});

test("two navigations inside the debounce zoom once, and the second is absorbed", () => {
  const st = { zoomedFor: "", zoomedAt: -1e9 };
  zoomFor(st, "https://a.test/", 10000, 100, 45);
  const quick = zoomFor(st, "https://b.test/", 10500, 200, 45);
  assert.equal(quick.zoom, false);
  const later = zoomFor(st, "https://b.test/", 30000, 200, 45);
  assert.equal(later.zoom, false, "b was absorbed, not zoomed later");
});

test("planted: always-zoom resets the reader's distance on every flight", () => {
  const st = { zoomedFor: "", zoomedAt: -1e9 };
  zoomFor(st, "https://a.test/", 10000, 100, 45, { always: true });
  const again = zoomFor(st, "https://a.test/", 12000, 300, 45, { always: true });
  assert.deepEqual(again, { zoom: true, distance: 45 });
});

// relaxCloud: "the central URL node collision radius boundary was not
// enforced" -- ko.wikipedia/물리학 drew 285 chunks, 2,069 overlapping pairs,
// 68 inside its url node.
import { relaxCloud } from "../src/camera.ts";

const packed = [];
for (let i = 0; i < 200; i++) {
  const a = i * 2.399, z = 1 - (2 * i + 1) / 200, r = Math.sqrt(1 - z * z) * (3 + (i % 5));
  packed.push([r * Math.cos(a), r * Math.sin(a), z * 6]);
}
const radii = packed.map(() => 2.3);

test("relaxed: no overlapping spheres, none inside the url node, all inside the bound, near the phantoms", () => {
  const out = relaxCloud([0, 0, 0], packed, radii, 10.3 * 2, 134, { safety: 2, iterations: 200 });
  assert.ok(out.overlapsBefore > 100, "the start is packed: " + out.overlapsBefore);
  assert.equal(out.overlapsAfter, 0);
  assert.equal(out.insideAfter, 0);
  assert.ok(out.pos.every((p) => Math.hypot(...p) <= 134 + 1e-6));
  // The phantom: chunks stay on their side of the cloud (direction kept, coarse).
  let same = 0;
  for (let i = 0; i < packed.length; i++) {
    const a = packed[i], b = out.pos[i];
    const cos = (a[0] * b[0] + a[1] * b[1] + a[2] * b[2]) / (Math.hypot(...a) * Math.hypot(...b) || 1);
    if (cos > 0.5) same++;
  }
  assert.ok(same / packed.length > 0.8, "directions kept: " + same);
});

test("planted: no relaxation leaves the packed cloud overlapping and inside the url node", () => {
  const out = relaxCloud([0, 0, 0], packed, radii, 10.3 * 2, 134, { safety: 2, iterations: 0 });
  assert.ok(out.overlapsAfter > 100 && out.insideAfter > 10);
});

test("uniform radius spreads a dense core through the ball; planted raw radii keep the knot", () => {
  const core = [];
  for (let i = 0; i < 100; i++) { const a = i * 2.399, z = 1 - (2 * i + 1) / 100, r = Math.sqrt(1 - z * z);
    const s = i < 90 ? 1 : 30;                    // 90 in a tight core, 10 far out
    core.push([s * r * Math.cos(a), s * r * Math.sin(a), s * z]); }
  const nnMed = (ps) => { const nn = ps.map((a) => Math.min(...ps.filter((b) => b !== a).map((b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2])))); nn.sort((x, y) => x - y); return nn[nn.length >> 1]; };
  const u = centredTelescope([0, 0, 0], core, 100, 5, false, true).pos;
  const raw = centredTelescope([0, 0, 0], core, 100, 5, false, false).pos;
  assert.ok(nnMed(u) > 3 * nnMed(raw), "uniform " + nnMed(u) + " vs raw " + nnMed(raw));
});

test("coincident url nodes part, and only they move (G-21, 2026-10-11)", async () => {
  const far = [1e12, 1e12, 1e12];
  const pos = [[0, 0, 0], [0, 0, 0], [50, 0, 0], [0, 80, 0]];
  const r = relaxCloud(far, pos, [1, 1, 1, 1], 0, Infinity, { safety: 2, anchor: 0 });
  const d01 = Math.hypot(...r.pos[0].map((v, k) => v - r.pos[1][k]));
  assert.ok(d01 >= 3.99, "the coincident pair parted to the collider's spacing: " + d01);
  assert.deepEqual(r.pos[2], [50, 0, 0]);
  assert.deepEqual(r.pos[3], [0, 80, 0]);
});
