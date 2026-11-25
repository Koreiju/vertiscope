/**
 * Named extension slots over a stable core (G-240; PLUGIN_GOAL Addendum XI
 * (169), a reading of "the 'everything is a plugin' framework"): an extension
 * fills ONE named slot -- `codeblock:<lang>` (a block it draws), `card:<name>`
 * (a decoration on every plane card: `decorateCard`, below) or `cell:<name>`
 * (a control on every code cell beside run: `cellControls`, below) -- and may
 * only tighten the core: a slot the core owns (`domvec`, `browser`, `python`)
 * is refused, so an extension can add a block but never replace one. Loading
 * is isolated: an extension that throws is recorded and skipped, the rest and
 * the core load regardless; switched off (settings or the plant), it is not
 * loaded at all and its blocks stay plain code. The core runs without any.
 *
 * In trie terms: no extension writes the trie here; each block it draws reads
 * and writes vault:// pages through the core's own paths.
 */
export interface Ext {
  id: string;
  /** e.g. "codeblock:chat". */
  slot: string;
  register(): void;
}

export const CORE_SLOTS = new Set(["codeblock:domvec", "codeblock:browser", "codeblock:python", "codeblock:py", "codeblock:python3"]);

/** The `card:` slot kind: decorations every plane card gets as it is drawn.
 *  Each runs isolated -- one that throws is recorded and the card is drawn
 *  regardless. */
const decorators = new Map<string, (card: HTMLElement, path: string) => void>();
export const cardStats = { failed: [] as string[] };
export function registerDecorator(name: string, fn: (card: HTMLElement, path: string) => void): void { decorators.set(name, fn); }
export function unregisterDecorator(name: string): void { decorators.delete(name); }
export function decorateCard(card: HTMLElement, path: string): void {
  for (const [name, fn] of decorators) {
    try { fn(card, path); } catch (err) { cardStats.failed.push(name); console.warn("domvec: card decoration " + name + " failed; the card is drawn", err); }
  }
}

/** The `cell:` slot kind (G-240): a control a code cell carries beside its core
 *  ones (run, terminal, open, unnest). Each may decline a cell (null) and runs
 *  isolated -- one that throws is recorded and the cell keeps the rest. */
export type CellReq = { lang: string; code: string; line: number; path: string; refs?: string[] };
const cellCtl = new Map<string, (req: () => CellReq, doc: Document) => HTMLElement | null>();
export function registerCellControl(name: string, fn: (req: () => CellReq, doc: Document) => HTMLElement | null): void { cellCtl.set(name, fn); }
export function unregisterCellControl(name: string): void { cellCtl.delete(name); }
export function cellControls(req: () => CellReq, doc: Document): HTMLElement[] {
  const out: HTMLElement[] = [];
  for (const [name, fn] of cellCtl) {
    try { const el = fn(req, doc); if (el) { el.dataset.slot = "cell:" + name; out.push(el); } }
    catch (err) { cardStats.failed.push("cell:" + name); console.warn("domvec: cell control " + name + " failed; the cell keeps the rest", err); }
  }
  return out;
}

export class Slots {
  exts: Ext[] = [];
  stats = { loaded: [] as string[], refused: [] as string[], failed: [] as string[], off: [] as string[] };
  constructor(private disabled: () => string[]) {}

  add(e: Ext): void { this.exts.push(e); }

  private taken = new Map<string, string>();

  load(): void { for (const e of this.exts) this.loadOne(e, false); }

  /** One extension, by the same rules; also how one is added while running. */
  loadOne(e: Ext, add = true): "loaded" | "off" | "refused" | "failed" {
    if (add) this.exts.push(e);
    const off = new Set([...this.disabled(), ...(((window as any).__domvecDisableExtensions as string[]) || [])]);
    if (off.has(e.id) || off.has("*")) { this.stats.off.push(e.id); return "off"; }
    // May only tighten: never a core slot, never a slot another extension holds.
    // Planted `__domvecPlantNoSlotGuard`: any slot is taken, a core one too.
    if (!(window as any).__domvecPlantNoSlotGuard && (CORE_SLOTS.has(e.slot) || this.taken.has(e.slot))) { this.stats.refused.push(e.id); return "refused"; }
    try { e.register(); this.taken.set(e.slot, e.id); this.stats.loaded.push(e.id); return "loaded"; }
    catch (err) { this.stats.failed.push(e.id); console.warn("domvec: extension " + e.id + " failed; the core runs on", err); return "failed"; }
  }

  /** Release a slot (a `card:` decoration is unregistered with it). */
  unload(id: string): void {
    for (const [slot, who] of this.taken) if (who === id) {
      this.taken.delete(slot);
      if (slot.startsWith("card:")) unregisterDecorator(slot.slice(5));
      if (slot.startsWith("cell:")) unregisterCellControl(slot.slice(5));
    }
    this.exts = this.exts.filter((e) => e.id !== id);
    this.stats.loaded = this.stats.loaded.filter((x) => x !== id);
  }
}
(window as any).__domvecCardSlot = { registerDecorator, unregisterDecorator, decorateCard, cardStats, decorators, registerCellControl, unregisterCellControl, cellCtl };
