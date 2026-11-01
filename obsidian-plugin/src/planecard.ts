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

const HANDLE = ".domvec-var-title, .domvec-slate-circle, .domvec-slate-circle-dot";

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

export function makeDraggable(card: HTMLElement, plane: HTMLElement, key: string, stats: PlaceStats): () => void {
  try {
    const saved = JSON.parse(window.localStorage.getItem(key) || "null");
    if (saved && Number.isFinite(saved.x) && Number.isFinite(saved.y)) {
      card.style.right = "auto"; card.style.left = `${saved.x}px`; card.style.top = `${saved.y}px`;
    }
  } catch { /* a convenience only */ }
  let start: { x: number; y: number; left: number; top: number } | null = null;
  const down = (e: MouseEvent) => {
    if (e.button !== 0 || !(e.target as HTMLElement)?.closest?.(HANDLE)) return;
    e.preventDefault(); e.stopPropagation();
    const r = card.getBoundingClientRect(), p = plane.getBoundingClientRect();
    start = { x: e.clientX, y: e.clientY, left: r.left - p.left, top: r.top - p.top };
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
  const up = () => {
    window.removeEventListener("mousemove", move, true);
    window.removeEventListener("mouseup", up, true);
    if (!start) return;
    start = null;
    stats.drags++;
    try { window.localStorage.setItem(key, JSON.stringify({ x: parseFloat(card.style.left) || 0, y: parseFloat(card.style.top) || 0 })); }
    catch { /* a convenience only */ }
  };
  card.addEventListener("mousedown", down, true);
  const sizes = new ResizeObserver(() => { if (clampToPlane(card, plane)) stats.clamped++; });
  sizes.observe(plane);
  return () => { card.removeEventListener("mousedown", down, true); sizes.disconnect(); };
}
