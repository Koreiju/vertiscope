/**
 * A panel on the 2D plane is DRAGGABLE and CONTAINED (PLUGIN_GOAL 57,
 * 2026-11-01: "the panels should still be draggable and contained within the
 * 2D computation graph plane").
 *
 * The handle is the panel's header node -- the slate's title node when open,
 * its circle when minimized (items 54-55) -- so there is no chrome to add. A
 * press on it is taken before CodeMirror sees it (a drag never selects text);
 * the right-click that folds the slate is left alone. The card is clamped to
 * the plane on every move and whenever the plane resizes, and its place is
 * remembered per card.
 */

// The graph form's empty ground drags too (150: "I can't drag the computation
// graph"); its nodes do not -- they wire (UR N.4) and fold.
const HANDLE = ".domvec-var-title, .domvec-slate-circle, .domvec-slate-circle-dot, .domvec-plane-head-node, .domvec-slate-graph";

export interface PlaceStats { drags: number; clamped: number }

export function clampToPlane(card: HTMLElement, plane: HTMLElement): boolean {
  const pw = plane.clientWidth, ph = plane.clientHeight, cw = card.offsetWidth, ch = card.offsetHeight;
  if (!pw || !ph || !card.style.left) return false;
  const x = parseFloat(card.style.left) || 0, y = parseFloat(card.style.top) || 0;
  const nx = Math.max(0, Math.min(x, pw - cw)), ny = Math.max(0, Math.min(y, ph - ch));
  if (nx === x && ny === y) return false;
  card.style.left = `${nx}px`; card.style.top = `${ny}px`;
  return true;
}

/** How near, in px, a dropped card's edge must come to another's to snap. */
export const SNAP_PX = 14;

/**
 * MAGNETIC bare edges (PLUGIN_GOAL 134: "drag to snap on magnetic naked edges
 * without any additional visual elements"): a card dropped with an edge within
 * `SNAP_PX` of another card's opposite edge, the two overlapping along it,
 * moves flush against it and remembers whom it is attached to on that side
 * (`data-magnet-left/right/top/bottom` = the neighbour's path) -- the cells a
 * chat cell's context is read from. Nothing is drawn. Planted
 * `__domvecPlantNoMagnet`: dropped where released, as before.
 */
export function snapToNeighbour(card: HTMLElement, plane: HTMLElement, stats: any): string {
  for (const side of ["left", "right", "top", "bottom"]) delete card.dataset["magnet" + side[0].toUpperCase() + side.slice(1)];
  if ((window as any).__domvecPlantNoMagnet) return "";
  const p = plane.getBoundingClientRect(), r = card.getBoundingClientRect();
  let best: { d: number; dx: number; dy: number; side: string; other: HTMLElement } | null = null;
  for (const o of Array.from(plane.querySelectorAll(".domvec-plane-card")) as HTMLElement[]) {
    if (o === card || !o.isConnected || o.offsetParent === null) continue;
    const q = o.getBoundingClientRect();
    const vOverlap = Math.min(r.bottom, q.bottom) - Math.max(r.top, q.top) > 0;
    const hOverlap = Math.min(r.right, q.right) - Math.max(r.left, q.left) > 0;
    const cands: [number, number, number, string][] = [];
    if (vOverlap) { cands.push([Math.abs(r.left - q.right), q.right - r.left, 0, "left"]); cands.push([Math.abs(r.right - q.left), q.left - r.right, 0, "right"]); }
    if (hOverlap) { cands.push([Math.abs(r.top - q.bottom), 0, q.bottom - r.top, "top"]); cands.push([Math.abs(r.bottom - q.top), 0, q.top - r.bottom, "bottom"]); }
    for (const [d, dx, dy, side] of cands) if (d <= SNAP_PX && (!best || d < best.d)) best = { d, dx, dy, side, other: o };
  }
  if (!best) return "";
  card.style.right = "auto";
  card.style.left = `${(parseFloat(card.style.left) || (r.left - p.left)) + best.dx}px`;
  card.style.top = `${(parseFloat(card.style.top) || (r.top - p.top)) + best.dy}px`;
  card.dataset["magnet" + best.side[0].toUpperCase() + best.side.slice(1)] = best.other.dataset.path || "";
  stats.snapped = (stats.snapped || 0) + 1;
  return best.side;
}

/** The pane under (x, y) a card may live on: the 3D view's plane itself, or
 *  another workspace leaf's content (the browser cell, a note). Planted
 *  `__domvecPlantNoCrossPane`: none, the card stays on its plane. */
export function paneUnder(card: HTMLElement, x: number, y: number, home: HTMLElement): HTMLElement | null {
  if ((window as any).__domvecPlantNoCrossPane) return null;
  const was = card.style.pointerEvents; card.style.pointerEvents = "none";
  const under = document.elementFromPoint(x, y) as HTMLElement | null;
  card.style.pointerEvents = was;
  if (!under) return null;
  if (home.contains(under) || under === home) return home;
  const leaf = under.closest(".workspace-leaf-content") as HTMLElement | null;
  return leaf && !leaf.contains(home) ? leaf : null;
}

/** Re-parent `card` onto `to`, keeping it where it was dropped on screen. */
export function moveToPane(card: HTMLElement, from: HTMLElement, to: HTMLElement, x: number, y: number): void {
  const r = card.getBoundingClientRect();
  if (getComputedStyle(to).position === "static") to.style.position = "relative";
  to.appendChild(card);
  const t = to.getBoundingClientRect();
  card.style.position = "absolute"; card.style.right = "auto"; card.style.zIndex = "30";
  // At the DROP point (the header grabbed near its left end), not where the
  // drag left it clamped to the pane it came from.
  card.style.left = `${Math.round(Math.max(0, x - t.left - 6))}px`; card.style.top = `${Math.round(Math.max(0, y - t.top - Math.min(12, r.height / 2)))}px`;
  card.dataset.pane = to === from ? "" : (to.closest(".workspace-leaf")?.querySelector(".view-header-title")?.textContent || "pane");
}

export function makeDraggable(card: HTMLElement, home: HTMLElement, key: string, stats: PlaceStats,
                              onClick?: () => void, onDrop?: (x: number, y: number) => boolean): () => void {
  // The pane the card is on NOW: the 3D view's plane, or another pane it was
  // carried to (PLUGIN_GOAL 133: "move the computational graph editor
  // nodes/panels *across* panes like the 3D world viewer and the browser").
  let plane = home;
  try {
    const saved = JSON.parse(window.localStorage.getItem(key) || "null");
    if (saved && Number.isFinite(saved.x) && Number.isFinite(saved.y)) {
      card.style.right = "auto"; card.style.left = `${saved.x}px`; card.style.top = `${saved.y}px`;
    }
  } catch { /* a convenience only */ }
  let start: { x: number; y: number; left: number; top: number } | null = null;
  const down = (e: MouseEvent) => {
    const tg = e.target as HTMLElement;
    if (e.button !== 0 || !tg?.closest?.(HANDLE)) return;
    if (tg.closest?.(".domvec-slate-graph") && (tg.closest?.(".domvec-slate-graph-node") || tg.getAttribute?.("data-path") != null)) return;
    e.preventDefault(); e.stopPropagation();
    const r = card.getBoundingClientRect(), p = plane.getBoundingClientRect();
    start = { x: e.clientX, y: e.clientY, left: r.left - p.left, top: r.top - p.top };
    (card as any).__dragFrom = { left: start.left, top: start.top };
    window.addEventListener("mousemove", move, true);
    window.addEventListener("mouseup", up, true);
  };
  const move = (e: MouseEvent) => {
    if (!start) return;
    e.preventDefault(); e.stopPropagation();
    card.style.right = "auto";
    card.style.left = `${start.left + e.clientX - start.x}px`;
    card.style.top = `${start.top + e.clientY - start.y}px`;
    if (clampToPlane(card, plane)) stats.clamped++;
  };
  const up = (e?: MouseEvent) => {
    window.removeEventListener("mousemove", move, true);
    window.removeEventListener("mouseup", up, true);
    if (!start) return;
    // Pressed and released in place: a CLICK on the header node, not a drag
    // (PLUGIN_GOAL 81: the halo opens on it).
    const still = !e || Math.hypot(e.clientX - start.x, e.clientY - start.y) < 3;
    start = null;
    if (still && onClick) { onClick(); return; }
    stats.drags++;
    // A drop the desk consumes (graph form's wiring): the card goes back.
    if (e && onDrop) {
      const back = { left: card.style.left, top: card.style.top };
      const s0 = (card as any).__dragFrom as { left: number; top: number } | undefined;
      if (onDrop(e.clientX, e.clientY)) {
        if (s0) { card.style.left = `${s0.left}px`; card.style.top = `${s0.top}px`; } else { card.style.left = back.left; card.style.top = back.top; }
        return;
      }
    }
    if (e) { const to = paneUnder(card, e.clientX, e.clientY, home); if (to && to !== plane) { moveToPane(card, plane, to, e.clientX, e.clientY); plane = to; (stats as any).crossed = ((stats as any).crossed || 0) + 1; } }
    snapToNeighbour(card, plane, stats);
    try { window.localStorage.setItem(key, JSON.stringify({ x: parseFloat(card.style.left) || 0, y: parseFloat(card.style.top) || 0 })); }
    catch { /* a convenience only */ }
  };
  card.addEventListener("mousedown", down, true);
  const sizes = new ResizeObserver(() => { if (clampToPlane(card, plane)) stats.clamped++; });
  sizes.observe(plane);
  return () => { card.removeEventListener("mousedown", down, true); sizes.disconnect(); };
}
