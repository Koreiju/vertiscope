// D-38: the octree trap, planted, and the guard that keeps the simulation out
// of it. Run: node --test tests/
import test from "node:test";
import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { fileURLToPath } from "node:url";
import { octreeVerdict } from "../src/octreeguard.ts";

const placed = (x, y, z) => ({ x, y, z, vx: 0, vy: 0, vz: 0 });
// Two placed nodes, both at positive coordinates (the extent excludes the
// origin), and two the simulation has not placed yet.
const trapped = () => [placed(10, 10, 10), placed(20, 30, 40), { id: "new-a", vx: 0, vy: 0, vz: 0 },
                       { id: "new-b", vx: 0, vy: 0, vz: 0 }];

/** Resolves "done" or "hung" -- still running after `ms`, or out of its
 *  128 MB heap, is a hang. JSON drops undefined fields, as unset ones are. */
function build(nodes, ms = 3000) {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, ["--max-old-space-size=128",
      fileURLToPath(new URL("./octree_build.mjs", import.meta.url))], { stdio: ["pipe", "pipe", "ignore"] });
    let out = "";
    const timer = setTimeout(() => { child.kill(); resolve("hung"); }, ms);
    child.stdout.on("data", (c) => { out += c; });
    child.on("exit", () => { clearTimeout(timer); resolve(out === "done" ? "done" : "hung"); });
    child.stdin.end(JSON.stringify(nodes));
  });
}

test("planted: two unplaced nodes hang d3-octree's build", async () => {
  assert.equal(await build(trapped()), "hung");
});

test("null arm: the same graph with every node placed builds", async () => {
  const ok = trapped().map((n, i) => ({ ...placed(12 + i, 14 + i, 16 + i), id: n.id }));
  assert.equal(await build(ok), "done");
});

test("the guard refuses the trapped graph and names the unplaced nodes", () => {
  const v = octreeVerdict(trapped());
  assert.equal(v.ok, false);
  assert.equal(v.bad, 2);
  assert.deepEqual(v.sample.map((s) => s.id), ["new-a", "new-b"]);
});

test("the guard passes a placed graph, and what it passes builds", async () => {
  const nodes = [placed(10, 10, 10), placed(20, 30, 40), placed(-5, 3, 9)];
  assert.equal(octreeVerdict(nodes).ok, true);
  assert.equal(await build(nodes), "done");
});

test("planted: placed nodes whose velocity was never set hang the build too", async () => {
  // x is a number; vx is undefined, so collide's x + vx is NaN.
  const nodes = [placed(10, 10, 10), placed(20, 30, 40), { x: 12, y: 12, z: 12 }, { x: 13, y: 13, z: 13 }];
  assert.equal(await build(nodes), "hung");
  const v = octreeVerdict(nodes);
  assert.equal(v.ok, false);
  assert.equal(v.bad, 2);
});

test("a node with no z is refused: the accessor reads d.z + d.vz", () => {
  assert.equal(octreeVerdict([{ x: 1, y: 1, vx: 0, vy: 0, vz: 0 }]).ok, false);
});

test("the guard also refuses Infinity, NaN velocity, and a runaway position", () => {
  assert.equal(octreeVerdict([{ ...placed(1, 1, 1), vx: Infinity }]).ok, false);
  assert.equal(octreeVerdict([{ ...placed(1, 1, 1), vy: NaN }]).ok, false);
  assert.equal(octreeVerdict([placed(2e7, 1, 1)]).ok, false);
  // many-body reads x, not x + vx
  assert.equal(octreeVerdict([{ ...placed(1, 1, 1), vx: NaN }], false).ok, true);
});
