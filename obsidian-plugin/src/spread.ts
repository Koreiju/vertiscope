/**
 * The scale about a page's centre at which none of its nodes overlap: every
 * pair clears the sum of its drawn radii times `gap` (PLUGIN_GOAL 159: "hovered
 * urls are temporarily re-scaled so that their image overlays/billboards don't
 * overlap with each other within an increased separation distance"). 1 when
 * nothing overlaps; capped, so one coincident pair cannot fling the page.
 */
export function spreadFactor(pos: number[][], radii: number[], gap = 1.15, cap = 6): number {
  let k = 1;
  for (let i = 0; i < pos.length; i++) {
    for (let j = i + 1; j < pos.length; j++) {
      const d = Math.hypot(pos[i][0] - pos[j][0], pos[i][1] - pos[j][1], (pos[i][2] || 0) - (pos[j][2] || 0));
      const need = (radii[i] + radii[j]) * gap;
      if (d < 1e-6) { k = cap; continue; }
      if (need > d * k) k = Math.min(cap, need / d);
    }
  }
  return k;
}

/**
 * Adaptive, bounded hover spread factor: ignores near-coincident duplicate
 * points that radial scaling around the cluster centroid cannot separate, uses
 * the 75th percentile of overlapping pair ratios rather than a single outlier
 * pair, and scales the ceiling down as the cluster grows so hovering never
 * flings a page's 3D cloud across the scene.
 */
export function adaptiveSpreadFactor(pos: number[][], radii: number[], gap = 1.12, maxCap = 1.55): number {
  const n = pos.length;
  if (n < 2) return 1;
  const ratios: number[] = [];
  for (let i = 0; i < n; i++) {
    for (let j = i + 1; j < n; j++) {
      const d = Math.hypot(pos[i][0] - pos[j][0], pos[i][1] - pos[j][1], (pos[i][2] || 0) - (pos[j][2] || 0));
      if (d < 1e-2) continue;
      const need = (radii[i] + radii[j]) * gap;
      if (need > d) ratios.push(need / d);
    }
  }
  if (!ratios.length) return 1;
  ratios.sort((a, b) => a - b);
  const q = ratios[Math.min(ratios.length - 1, Math.floor(ratios.length * 0.75))];
  const cap = Math.max(1.15, Math.min(maxCap, 1 + (maxCap - 1) / Math.pow(Math.max(1, n / 10), 0.3)));
  const damped = 1 + (q - 1) * 0.6;
  return Math.min(cap, Math.max(1, damped));
}
