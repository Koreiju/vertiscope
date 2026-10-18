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
