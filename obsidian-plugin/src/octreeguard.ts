/**
 * Is it safe to build an octree over these nodes this tick? (D-38, again.)
 *
 * d3-force-3d's collide builds its octree on the PREDICTED position, x + vx,
 * and many-body on x. d3-octree's `addAll` leaves a node whose coordinate is
 * NaN out of the bounds but still INSERTS it -- at 0,0,0, the Float64Array's
 * default -- and its leaf recomputes to NaN on every later comparison. The
 * split loop in `add` ends only when two points fall in different octants;
 * a NaN leaf reads octant 0 at every split, so a second such node, or a real
 * one pinned at the extent's lower corner, splits forever, allocating an
 * `Array(8)` each turn: the renderer runs out of memory. Caught paused on
 * 2026-09-28 (`add3` <- `addAll3` <- `octree` <- collide <- `gated`, heap
 * 1,067 MB and climbing) after 30 s of rapid scrolling on a forum page the
 * store had never seen, with ~1,000 streaming nodes arriving.
 *
 * A node the simulation has not placed yet (x undefined) is exactly this
 * case: `undefined + 0` is NaN. The pane's `sanitize` let those through on
 * the belief that "the octree skips it". It does not.
 *
 * Pure, so a module test can plant the hang without Obsidian.
 */
export interface OctreeVerdict {
  ok: boolean;
  /** Nodes whose predicted position is not finite, or runs past `limit`. */
  bad: number;
  /** Up to three of them, for the record. */
  sample: { id: string; x: unknown; vx: unknown; y: unknown; vy: unknown; z: unknown; vz: unknown }[];
}

export function octreeVerdict(nodes: any[], predicted = true, limit = 1e7): OctreeVerdict {
  let bad = 0;
  const sample: OctreeVerdict["sample"] = [];
  for (const n of nodes) {
    // EXACTLY the accessors d3-force-3d hands the octree -- `d.x + d.vx` for
    // collide, `d.x` for many-body -- with no defaults. The first version of
    // this guard wrote `n.vx ?? 0` and `n.z ?? 0`, passed a node whose
    // velocity was never set as finite, and the renderer hung in `add3`
    // again with the guard loaded: `x + undefined` is NaN to the octree.
    const px = predicted ? n.x + n.vx : n.x;
    const py = predicted ? n.y + n.vy : n.y;
    const pz = predicted ? n.z + n.vz : n.z;
    if (Number.isFinite(px) && Number.isFinite(py) && Number.isFinite(pz)
        && Math.abs(px) < limit && Math.abs(py) < limit && Math.abs(pz) < limit) continue;
    bad++;
    if (sample.length < 3) sample.push({ id: String(n.id ?? "").slice(0, 60), x: n.x, vx: n.vx,
                                         y: n.y, vy: n.vy, z: n.z, vz: n.vz });
  }
  return { ok: bad === 0, bad, sample };
}

/**
 * Velocities too small to matter, set to exactly zero. Returns how many.
 *
 * The OTHER road into the same hang, caught paused 2026-09-28 23:58 with the
 * octree's own input read out: two page nodes of one site at the IDENTICAL
 * position, velocities decayed toward zero but not to it (x 0.6 per tick).
 * d3's collide measures their separation as x_a + vx_a - x_b - vx_b: the
 * positions cancel, the velocities leave a component of ~1e-200, which is
 * not `=== 0` so d3 does not jiggle it, and whose square underflows to 0.
 * Then `(r - sqrt(0)) / 0` is Infinity: the pair flew apart at +-Infinity in
 * the force's first iteration, and its second iteration's octree could never
 * be built (bounds -Infinity and NaN). At exactly zero, d3's own jiggle takes
 * the pair apart finitely.
 */
export function flushTiny(nodes: any[], eps = 1e-100): number {
  let flushed = 0;
  for (const n of nodes) {
    for (const k of ["vx", "vy", "vz"]) {
      const v = n[k];
      if (typeof v === "number" && v !== 0 && Math.abs(v) < eps) { n[k] = 0; flushed++; }
    }
  }
  return flushed;
}
