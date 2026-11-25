/**
 * Named extension slots over a stable core (G-240; PLUGIN_GOAL Addendum XI
 * (169), a reading of "the 'everything is a plugin' framework"): an extension
 * fills ONE named slot -- `codeblock:<lang>` is the only kind so far -- and may
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

export class Slots {
  exts: Ext[] = [];
  stats = { loaded: [] as string[], refused: [] as string[], failed: [] as string[], off: [] as string[] };
  constructor(private disabled: () => string[]) {}

  add(e: Ext): void { this.exts.push(e); }

  load(): void {
    const off = new Set([...this.disabled(), ...(((window as any).__domvecDisableExtensions as string[]) || [])]);
    const taken = new Set<string>();
    for (const e of this.exts) {
      if (off.has(e.id) || off.has("*")) { this.stats.off.push(e.id); continue; }
      // May only tighten: never a core slot, never a slot another extension holds.
      // Planted `__domvecPlantNoSlotGuard`: any slot is taken, a core one too.
      if (!(window as any).__domvecPlantNoSlotGuard && (CORE_SLOTS.has(e.slot) || taken.has(e.slot))) { this.stats.refused.push(e.id); continue; }
      try { e.register(); taken.add(e.slot); this.stats.loaded.push(e.id); }
      catch (err) { this.stats.failed.push(e.id); console.warn("domvec: extension " + e.id + " failed; the core runs on", err); }
    }
  }
}
