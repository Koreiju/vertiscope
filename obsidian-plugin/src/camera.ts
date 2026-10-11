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
                                 offCentre = false): Telescoped {
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
  const pos = raw.map((r, i) => {
    const di = d[i];
    if (!Number.isFinite(di)) return null;
    let to = inner + k * di;
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
