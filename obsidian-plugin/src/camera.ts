/**
 * The two decisions behind the projector's chunk clouds and its camera, kept
 * pure so they are tested without a renderer (`tests/camera.test.mjs`).
 *
 * In the trie's terms: a url node is the root of its `url : xpath` subtree,
 * and its chunks are the leaves the local fit placed. `centredTelescope`
 * decides where those leaves are drawn around their root; `zoomFor` decides
 * how far the camera stands from a hovered leaf.
 */

export type V3 = [number, number, number];

export interface Telescoped {
  /** Drawn positions, one per input, in input order (null: not finite). */
  pos: (V3 | null)[];
  /** The local fit's p90 radius, the scale factor, how many hit the bound. */
  p90: number;
  k: number;
  clamped: number;
  /** How far the chunks' own centroid was from the root, before centring. */
  centreOff: number;
}

/**
 * A page's chunks telescoped radially into `bound` around their url node.
 *
 * Offsets are taken from the chunks' OWN centroid, so the local fit's shape
 * is kept and its centre lands on the url node (2026-10-10: the forum's 186
 * chunks were drawn as a ball 95 units off their node, because the offsets
 * were taken from the page point and UMAP's transform of a mean is not the
 * mean of its transforms). `offCentre` is the planted old behaviour.
 */
export function centredTelescope(root: V3, raw: V3[], bound: number, inner: number,
                                 offCentre = false, uniform = false): Telescoped {
  const ok = raw.filter((r) => r.every(Number.isFinite));
  const c: V3 = offCentre || !ok.length ? [root[0], root[1], root[2]]
    : [0, 1, 2].map((i) => ok.reduce((a, r) => a + r[i], 0) / ok.length) as V3;
  const centreOff = Math.hypot(c[0] - root[0], c[1] - root[1], c[2] - root[2]);
  const d = raw.map((r) => Math.hypot(r[0] - c[0], r[1] - c[1], r[2] - c[2]));
  const sorted = d.filter(Number.isFinite).sort((a, b) => a - b);
  if (!sorted.length || !(bound > 0)) return { pos: raw.map(() => null), p90: 0, k: 0, clamped: 0, centreOff };
  const p90 = Math.max(1e-6, sorted[Math.min(sorted.length - 1, Math.floor(sorted.length * 0.9))]);
  const k = Math.max(0, (0.85 * bound - inner) / p90);
  let clamped = 0;
  // `uniform`: the radius by RANK, cube-rooted, so the ball fills evenly and a
  // dense UMAP core is not drawn as a knot; direction and radial order kept.
  const rank = new Map<number, number>();
  if (uniform) d.map((x, i) => [x, i]).filter((t) => Number.isFinite(t[0])).sort((a, b) => a[0] - b[0])
    .forEach((t, r) => rank.set(t[1], r));
  const m = rank.size;
  const pos = raw.map((r, i) => {
    const di = d[i];
    if (!Number.isFinite(di)) return null;
    let to = uniform && m ? inner + (0.85 * bound - inner) * Math.cbrt(((rank.get(i) ?? 0) + 0.5) / m) : inner + k * di;
    if (to > bound) { to = bound; clamped++; }
    const f = di > 1e-9 ? to / di : 0;
    return [root[0] + (r[0] - c[0]) * f, root[1] + (r[1] - c[1]) * f, root[2] + (r[2] - c[2]) * f] as V3;
  });
  return { pos, p90, k, clamped, centreOff };
}

/**
 * Does this flight ZOOM, or keep the reader's distance?
 *
 * 2026-10-10: "fly-to-node should zoom initially, but preserve user zoom
 * while still tracking during fly-throughs"; "some kind of debounce on ...
 * re-setting the zoom action for 'new navigations'". It zooms on the first
 * flight of a navigation (the browser cell's page) and keeps the reader's
 * distance after; two navigations within `debounceMs` zoom once.
 */
export function zoomFor(state: { zoomedFor: string; zoomedAt: number }, nav: string, now: number,
                        userDistance: number, zoomDistance: number,
                        opts: { debounceMs?: number; always?: boolean } = {}): { zoom: boolean; distance: number } {
  const debounce = opts.debounceMs ?? 1500;
  const newNav = state.zoomedFor !== nav;
  const fresh = newNav && now - state.zoomedAt > debounce;
  const zoom = !!opts.always || fresh || !Number.isFinite(userDistance) || userDistance <= 0;
  if (zoom) { state.zoomedFor = nav; state.zoomedAt = now; }
  // A navigation inside the debounce is ABSORBED: it is not zoomed for later.
  else if (newNav) state.zoomedFor = nav;
  return { zoom, distance: zoom ? zoomDistance : userDistance };
}

export interface Relaxed {
  pos: V3[];
  /** Overlapping pairs and chunks inside the root's sphere, before and after. */
  overlapsBefore: number; overlapsAfter: number;
  insideBefore: number; insideAfter: number;
  iterations: number;
}

/**
 * A page's chunk TARGETS relaxed after the fit (2026-10-10: "force-directed
 * post-umap is warranted, but done with the original residual coordinates as
 * phantom coordinates to keep the nodes closer to their original locations
 * while enforcing collision and attraction constraints with a radius/diameter
 * safety factor on collision spheres"; "Phantom links and clumping tells me
 * the central URL node collision radius boundary was not enforced").
 *
 * Each target is anchored to where the fit put it (the phantom); spheres of
 * radius `radii[i] * safety` do not overlap; none enters the root's sphere
 * `rootR`; none leaves `bound`. On targets, not on the simulation: the home
 * force then glides each node there, so calm pins and dragging are untouched.
 * A grid one sphere wide keeps a pass O(n).
 */
/** Planted (G-90): a touching pair counts as overlapping, so the relax never stops early, as before. */
export const relaxConfig = { plantNoTouchTolerance: false };

export function relaxCloud(root: V3, start: V3[], radii: number[], rootR: number, bound: number,
                           opts: { safety?: number; iterations?: number; anchor?: number } = {}): Relaxed {
  const S = opts.safety ?? 2, iters = opts.iterations ?? 60, anchor = opts.anchor ?? 0.04;
  const n = start.length;
  const p: V3[] = start.map((q) => [q[0], q[1], q[2]] as V3);
  const R = radii.map((r) => Math.max(1e-6, r * S));
  const maxR = Math.max(1e-6, ...R);
  const cell = 2 * maxR;
  const count = () => {
    let o = 0, ins = 0;
    for (let i = 0; i < n; i++) {
      if (Math.hypot(p[i][0] - root[0], p[i][1] - root[1], p[i][2] - root[2]) < rootR + R[i] / S) ins++;
      for (let j = i + 1; j < n; j++) {
        if (Math.hypot(p[i][0] - p[j][0], p[i][1] - p[j][1], p[i][2] - p[j][2]) < (R[i] + R[j]) / S) o++;
      }
    }
    return [o, ins];
  };
  const [o0, i0] = n <= 600 ? count() : [-1, -1];
  const pushApart = (i: number, j: number, tolerance: number): number => {
    let dx = p[j][0] - p[i][0], dy = p[j][1] - p[i][1], dz = p[j][2] - p[i][2];
    let d = Math.hypot(dx, dy, dz);
    const want = R[i] + R[j];
    if (d >= want * tolerance) return 0;
    if (d < 1e-9) { dx = Math.cos(i * 2.399); dy = Math.sin(i * 2.399); dz = ((i % 7) - 3) / 7; d = Math.hypot(dx, dy, dz); }
    const push = (want - d) / d * 0.5;
    p[i][0] -= dx * push; p[i][1] -= dy * push; p[i][2] -= dz * push;
    p[j][0] += dx * push; p[j][1] += dy * push; p[j][2] += dz * push;
    return 1;
  };
  // **The page pass** (no phantom: `anchor` 0) takes a fast grid -- integer
  // keys, each sphere entered in every cell its box touches (two overlapping
  // spheres share one), each pair stamped once -- and a pair that TOUCHES is
  // apart (0.1%). A string per lookup and a touching pair pushed again every
  // pass ran all 60 iterations: 445 ms on ~1,150 pages, 1.2 s of a 1.5 s
  // absorb (2026-10-18, G-90); now ~11 iterations, ~25 ms. A chunk cloud
  // keeps the original pass: its iterations are its pull toward the fit, and
  // its direction-keeping is measured on that order (camera.test).
  // Planted `plantNoTouchTolerance`: the original pass everywhere.
  const fast = anchor === 0 && !relaxConfig.plantNoTouchTolerance;
  const seen = fast ? new Int32Array(n).fill(-1) : null;
  const hk = (x: number, y: number, z: number) => ((x * 73856093) ^ (y * 19349663) ^ (z * 83492791)) | 0;
  let it = 0;
  for (; it < iters; it++) {
    let moved = 0;
    if (fast && seen) {
      const grid = new Map<number, number[]>();
      const lo = new Int32Array(n * 3), hi = new Int32Array(n * 3);
      for (let i = 0; i < n; i++) {
        for (let a = 0; a < 3; a++) { lo[i * 3 + a] = Math.floor((p[i][a] - R[i]) / cell); hi[i * 3 + a] = Math.floor((p[i][a] + R[i]) / cell); }
        for (let x = lo[i * 3]; x <= hi[i * 3]; x++) for (let y = lo[i * 3 + 1]; y <= hi[i * 3 + 1]; y++) for (let z = lo[i * 3 + 2]; z <= hi[i * 3 + 2]; z++) {
          const k = hk(x, y, z); const l = grid.get(k); if (l) l.push(i); else grid.set(k, [i]);
        }
      }
      seen.fill(-1);
      for (let i = 0; i < n; i++) {
        for (let x = lo[i * 3]; x <= hi[i * 3]; x++) for (let y = lo[i * 3 + 1]; y <= hi[i * 3 + 1]; y++) for (let z = lo[i * 3 + 2]; z <= hi[i * 3 + 2]; z++) {
          const l = grid.get(hk(x, y, z));
          if (!l) continue;
          for (const j of l) {
            if (j <= i || seen[j] === i) continue;
            seen[j] = i;
            moved += pushApart(i, j, 0.999);
          }
        }
      }
    } else {
      const grid = new Map<string, number[]>();
      const key = (x: number, y: number, z: number) => `${Math.floor(x / cell)},${Math.floor(y / cell)},${Math.floor(z / cell)}`;
      for (let i = 0; i < n; i++) { const k = key(p[i][0], p[i][1], p[i][2]); const l = grid.get(k); if (l) l.push(i); else grid.set(k, [i]); }
      for (let i = 0; i < n; i++) {
        const cx = Math.floor(p[i][0] / cell), cy = Math.floor(p[i][1] / cell), cz = Math.floor(p[i][2] / cell);
        for (let ox = -1; ox <= 1; ox++) for (let oy = -1; oy <= 1; oy++) for (let oz = -1; oz <= 1; oz++) {
          for (const j of grid.get(`${cx + ox},${cy + oy},${cz + oz}`) || []) {
            if (j <= i) continue;
            moved += pushApart(i, j, 1);
          }
        }
      }
    }
    for (let i = 0; i < n; i++) {
      // The phantom: back toward where the fit put it.
      p[i][0] += (start[i][0] - p[i][0]) * anchor; p[i][1] += (start[i][1] - p[i][1]) * anchor; p[i][2] += (start[i][2] - p[i][2]) * anchor;
      let dx = p[i][0] - root[0], dy = p[i][1] - root[1], dz = p[i][2] - root[2];
      let d = Math.hypot(dx, dy, dz);
      const inner = rootR + R[i];
      if (d < inner) {
        if (d < 1e-9) { dx = Math.cos(i * 2.399); dy = Math.sin(i * 2.399); dz = 0.3; d = Math.hypot(dx, dy, dz); }
        const f = inner / d; p[i] = [root[0] + dx * f, root[1] + dy * f, root[2] + dz * f]; moved++;
      } else if (d > bound) {
        const f = bound / d; p[i] = [root[0] + dx * f, root[1] + dy * f, root[2] + dz * f];
      }
    }
    if (!moved) { it++; break; }
  }
  const [o1, i1] = n <= 600 ? count() : [-1, -1];
  return { pos: p, overlapsBefore: o0, overlapsAfter: o1, insideBefore: i0, insideAfter: i1, iterations: it };
}

/**
 * The similarity that carries one set of points onto another with KNOWN
 * correspondences: dst ~= s * R * src + t (G-194, 2026-10-17: "apply
 * efficient scale-aware ICP over the URL nodes so that we render the 3D
 * coordinates from their closest most previous registered camera pose").
 * The url nodes are matched by url, so the ICP's correspondence step is
 * exact and one closed-form solve is the whole registration: Horn's
 * quaternion method for R (the top eigenvector of a 4x4 symmetric matrix,
 * found by shifted power iteration -- no SVD library), Umeyama's scale.
 * `rms` is the residual, in dst units, so a caller can tell a real
 * registration from a fit that changed shape.
 */
export interface Similarity { s: number; R: number[][]; t: V3; rms: number; n: number }
export function similarityFit(src: V3[], dst: V3[]): Similarity | null {
  const n = Math.min(src.length, dst.length);
  if (n < 3) return null;
  const ms: V3 = [0, 0, 0], md: V3 = [0, 0, 0];
  for (let i = 0; i < n; i++) for (let k = 0; k < 3; k++) { ms[k] += src[i][k] / n; md[k] += dst[i][k] / n; }
  // Cross-covariance S = sum (src - ms)(dst - md)^T, and the source spread.
  const S = [[0, 0, 0], [0, 0, 0], [0, 0, 0]];
  let varS = 0;
  for (let i = 0; i < n; i++) {
    const a = [src[i][0] - ms[0], src[i][1] - ms[1], src[i][2] - ms[2]];
    const b = [dst[i][0] - md[0], dst[i][1] - md[1], dst[i][2] - md[2]];
    varS += a[0] * a[0] + a[1] * a[1] + a[2] * a[2];
    for (let r = 0; r < 3; r++) for (let c = 0; c < 3; c++) S[r][c] += a[r] * b[c];
  }
  if (!(varS > 1e-12)) return null;
  const [[Sxx, Sxy, Sxz], [Syx, Syy, Syz], [Szx, Szy, Szz]] = S;
  const N = [
    [Sxx + Syy + Szz, Syz - Szy, Szx - Sxz, Sxy - Syx],
    [Syz - Szy, Sxx - Syy - Szz, Sxy + Syx, Szx + Sxz],
    [Szx - Sxz, Sxy + Syx, -Sxx + Syy - Szz, Syz + Szy],
    [Sxy - Syx, Szx + Sxz, Syz + Szy, -Sxx - Syy + Szz],
  ];
  // Shift so the wanted (largest) eigenvalue is also the largest in size.
  let shift = 0;
  for (const row of N) for (const v of row) shift += Math.abs(v);
  let q = [1, 0.01, 0.02, 0.03];
  for (let it = 0; it < 200; it++) {
    const nq = [0, 0, 0, 0];
    for (let r = 0; r < 4; r++) { for (let c = 0; c < 4; c++) nq[r] += N[r][c] * q[c]; nq[r] += shift * q[r]; }
    const len = Math.hypot(nq[0], nq[1], nq[2], nq[3]) || 1;
    q = nq.map((v) => v / len);
  }
  const [w, x, y, z] = q;
  const R = [
    [w * w + x * x - y * y - z * z, 2 * (x * y - w * z), 2 * (x * z + w * y)],
    [2 * (x * y + w * z), w * w - x * x + y * y - z * z, 2 * (y * z - w * x)],
    [2 * (x * z - w * y), 2 * (y * z + w * x), w * w - x * x - y * y + z * z],
  ];
  const rot = (v: number[]): V3 => [R[0][0] * v[0] + R[0][1] * v[1] + R[0][2] * v[2],
                                   R[1][0] * v[0] + R[1][1] * v[1] + R[1][2] * v[2],
                                   R[2][0] * v[0] + R[2][1] * v[1] + R[2][2] * v[2]];
  let dot = 0;
  for (let i = 0; i < n; i++) {
    const a = rot([src[i][0] - ms[0], src[i][1] - ms[1], src[i][2] - ms[2]]);
    dot += a[0] * (dst[i][0] - md[0]) + a[1] * (dst[i][1] - md[1]) + a[2] * (dst[i][2] - md[2]);
  }
  const s = dot / varS;
  const rm = rot(ms);
  const t: V3 = [md[0] - s * rm[0], md[1] - s * rm[1], md[2] - s * rm[2]];
  let sq = 0;
  for (let i = 0; i < n; i++) {
    const p = rot(src[i]);
    sq += (s * p[0] + t[0] - dst[i][0]) ** 2 + (s * p[1] + t[1] - dst[i][1]) ** 2 + (s * p[2] + t[2] - dst[i][2]) ** 2;
  }
  return { s, R, t, rms: Math.sqrt(sq / n), n };
}

/** A point of the DST frame carried back into the SRC frame: R^T (p - t) / s. */
export function similarityInverse(f: Similarity, p: V3): V3 {
  const d = [p[0] - f.t[0], p[1] - f.t[1], p[2] - f.t[2]];
  const R = f.R;
  return [(R[0][0] * d[0] + R[1][0] * d[1] + R[2][0] * d[2]) / f.s,
          (R[0][1] * d[0] + R[1][1] * d[1] + R[2][1] * d[2]) / f.s,
          (R[0][2] * d[0] + R[1][2] * d[1] + R[2][2] * d[2]) / f.s];
}
/** A direction carried back (no scale, no translation): R^T v. */
export function rotateInverse(f: Similarity, v: V3): V3 {
  const R = f.R;
  return [R[0][0] * v[0] + R[1][0] * v[1] + R[2][0] * v[2],
          R[0][1] * v[0] + R[1][1] * v[1] + R[2][1] * v[2],
          R[0][2] * v[0] + R[1][2] * v[1] + R[2][2] * v[2]];
}
