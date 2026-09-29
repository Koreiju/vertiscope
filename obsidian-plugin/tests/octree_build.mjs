// Child process: build d3-octree the way d3-force-3d's collide does (on
// x + vx) over the nodes on stdin, and print "done". A separate process, so a
// build that never ends -- or runs the heap out -- is the test's finding
// rather than the test runner's death.
import { octree } from "d3-octree";

let raw = "";
process.stdin.on("data", (c) => { raw += c; });
process.stdin.on("end", () => {
  // Non-finite numbers travel as strings: JSON would make Infinity null (0).
  const nodes = JSON.parse(raw, (k, v) =>
    v === "Infinity" ? Infinity : v === "-Infinity" ? -Infinity : v === "NaN" ? NaN : v);
  octree(nodes, (d) => d.x + d.vx, (d) => d.y + d.vy, (d) => d.z + d.vz);
  process.stdout.write("done");
});
