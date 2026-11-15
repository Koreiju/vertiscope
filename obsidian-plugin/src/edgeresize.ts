/**
 * Resize a panel from ANY edge or corner, found by hovering (PLUGIN_GOAL 159:
 * "panels should be resizable with regular hover on edges, since our current
 * displays are quite tight"). A band `band` px inside the panel's border shows
 * the edge's resize cursor; a press there drags that edge (two, at a corner).
 * Left and top edges move the panel's left / top with it, so the opposite
 * edge stays put. Once resized, the panel's CSS max-size no longer caps it.
 *
 * Used by the plane's cards and the chunk panels (billboards) alike: one
 * gesture for every panel.
 */
export interface EdgeResizeStats { hovers: number; resizes: number; last: string }

export const EDGE_STATS: EdgeResizeStats = { hovers: 0, resizes: 0, last: "" };

const CURSOR: Record<string, string> = {
  n: "ns-resize", s: "ns-resize", e: "ew-resize", w: "ew-resize",
  ne: "nesw-resize", sw: "nesw-resize", nw: "nwse-resize", se: "nwse-resize",
};

/** Which edge (n/s/e/w or a corner) the point is on, within `band` px inside `r`; "" if none. */
export function edgeAt(r: DOMRect, x: number, y: number, band: number): string {
  if (x < r.left || x > r.right || y < r.top || y > r.bottom) return "";
  const n = y - r.top < band, s = r.bottom - y < band, w = x - r.left < band, e = r.right - x < band;
  return (n ? "n" : s ? "s" : "") + (w ? "w" : e ? "e" : "");
}

export function edgeResizable(el: HTMLElement, opts: { band?: number; minW?: number; minH?: number; onEnd?: () => void; enabled?: () => boolean;
    /** A left / top edge moved the panel by (dl, dt) px: for a panel placed by
     *  something else each frame (a chunk panel following its node), the
     *  offset it is placed by moves with it. */
    shift?: (dl: number, dt: number) => void } = {}): () => void {
  const band = opts.band ?? 6, minW = opts.minW ?? 180, minH = opts.minH ?? 90;
  let over = "";
  const setOver = (edge: string) => {
    if (edge === over) return;
    over = edge;
    if (edge) { el.dataset.domvecEdge = CURSOR[edge]; EDGE_STATS.hovers++; } else delete el.dataset.domvecEdge;
  };
  // Planted `window.__domvecPlantNoEdgeResize`: no panel resizes from its edges, as before.
  const planted = () => !!(window as any).__domvecPlantNoEdgeResize;
  const hover = (e: PointerEvent) => {
    if (planted()) { setOver(""); return; }
    if (e.buttons || (opts.enabled && !opts.enabled())) { if (!e.buttons) setOver(""); return; }
    setOver(edgeAt(el.getBoundingClientRect(), e.clientX, e.clientY, band));
  };
  const leave = () => setOver("");
  const down = (e: PointerEvent) => {
    if (e.button !== 0 || planted() || (opts.enabled && !opts.enabled())) return;
    const edge = edgeAt(el.getBoundingClientRect(), e.clientX, e.clientY, band);
    if (!edge) return;
    e.preventDefault(); e.stopPropagation(); e.stopImmediatePropagation();
    const r0 = el.getBoundingClientRect();
    const left0 = el.offsetLeft, top0 = el.offsetTop, x0 = e.clientX, y0 = e.clientY;
    let lastL = left0, lastT = top0;
    el.style.maxWidth = "none"; el.style.maxHeight = "none";
    el.addClass?.("is-resizing");
    const move = (m: PointerEvent) => {
      const dx = m.clientX - x0, dy = m.clientY - y0;
      if (edge.includes("e")) el.style.width = `${Math.max(minW, r0.width + dx)}px`;
      if (edge.includes("s")) el.style.height = `${Math.max(minH, r0.height + dy)}px`;
      let L = lastL, T = lastT;
      if (edge.includes("w")) { const w = Math.max(minW, r0.width - dx); el.style.width = `${w}px`; el.style.right = "auto"; L = left0 + (r0.width - w); el.style.left = `${L}px`; }
      if (edge.includes("n")) { const h = Math.max(minH, r0.height - dy); el.style.height = `${h}px`; T = top0 + (r0.height - h); el.style.top = `${T}px`; }
      if ((L !== lastL || T !== lastT) && opts.shift) opts.shift(L - lastL, T - lastT);
      lastL = L; lastT = T;
    };
    const up = () => {
      window.removeEventListener("pointermove", move, true);
      window.removeEventListener("pointerup", up, true);
      el.removeClass?.("is-resizing");
      EDGE_STATS.resizes++; EDGE_STATS.last = edge;
      opts.onEnd?.();
    };
    window.addEventListener("pointermove", move, true);
    window.addEventListener("pointerup", up, true);
  };
  el.addEventListener("pointermove", hover, true);
  el.addEventListener("pointerleave", leave);
  el.addEventListener("pointerdown", down, true);
  return () => {
    el.removeEventListener("pointermove", hover, true);
    el.removeEventListener("pointerleave", leave);
    el.removeEventListener("pointerdown", down, true);
  };
}
