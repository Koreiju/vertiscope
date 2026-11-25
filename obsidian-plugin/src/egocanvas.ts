/**
 * The ego canvas (PLUGIN_GOAL 183-186; spec §12c, G-401).
 *
 * The canvas IS the ego slate (54: "one ego, not two"). Its component fields
 * -- one per record of the ego's tool space (158), in compile order (142) --
 * sit beside the cockpit's own fields, each `name {ref}`. Revealing a field
 * draws the record inline in the same grammar (the slate's own `{ref}`
 * reveal, UR O.1a "revealed-internal"); nothing here draws anything.
 *
 * In trie terms: the ego slate is a `vault://` page, a component field one of
 * its lines, and the record that line's `{ref}` names is the page it links
 * to. This class only keeps those lines in step with the tool space.
 */
import { TFile, type App } from "obsidian";

import { EGO_PATH, OLD_CANVAS_PATH, componentFieldsOf, oldSectionsOf, withFields, type Field } from "./canvasparse";
export { EGO_PATH };
export type { Field };

export interface CanvasDesk {
  app: App;
  /** The ego's members as the craft knows them (G-291's rule). */
  members(): string[];
}

export class EgoCanvas {
  /** Planted (G-401): fields written once, never followed -- a record made
   *  after the seed gets no field. */
  static plantSeedOnce = false;
  stats = { joined: 0, migrated: 0, skipped_names: 0 };
  private seeded = false;

  constructor(private desk: CanvasDesk) {}

  private get app(): App { return this.desk.app; }

  /** A note that is the ego's only while a check runs, or is not a tool-space
   *  record (158: not the repository's code) -- never a field. */
  static scratch(p: string): boolean {
    return p === EGO_PATH || p === OLD_CANVAS_PATH || p.startsWith("domvec-checks/") || p.startsWith("code:")
      || /^domvec\/graph\/(g\d+|pg\d+|t\d+|flip )/i.test(p);
  }

  /** The note a `{ref}` names, resolved the way the slate's reveal resolves it
   *  (by note name, from the ego slate). */
  pathOf(ref: string): string | null {
    const f = this.app.metadataCache.getFirstLinkpathDest(ref.split("#")[0].trim(), EGO_PATH);
    return f ? f.path : null;
  }

  /** The ego slate's component fields, in order. */
  async fields(): Promise<Field[]> {
    const f = this.app.vault.getAbstractFileByPath(EGO_PATH);
    if (!(f instanceof TFile)) return [];
    return componentFieldsOf(await this.app.vault.read(f), (r) => !!this.pathOf(r));
  }

  /** Bring the fields up to date with the tool space: every member without a
   *  field gets one, at the end. The 183 canvas note's order is read first
   *  (once) and that note retired to the vault's trash. Returns fields added. */
  async sync(): Promise<number> {
    const ego = this.app.vault.getAbstractFileByPath(EGO_PATH);
    if (!(ego instanceof TFile)) return 0;
    if (EgoCanvas.plantSeedOnce && this.seeded) return 0;
    let order = this.desk.members();
    const old = this.app.vault.getAbstractFileByPath(OLD_CANVAS_PATH);
    if (old instanceof TFile) {
      order = [...oldSectionsOf(await this.app.vault.read(old)), ...order];
    }
    const have = new Set((await this.fields()).map((x) => this.pathOf(x.ref)));
    const names: string[] = [], taken = new Set<string>();
    for (const p of order) {
      if (have.has(p) || EgoCanvas.scratch(p) || !(this.app.vault.getAbstractFileByPath(p) instanceof TFile)) continue;
      const name = p.replace(/^.*\//, "").replace(/\.md$/, "");
      // A name must resolve back to THIS note, and be bound once (62).
      if (taken.has(name) || this.pathOf(name) !== p) { this.stats.skipped_names++; continue; }
      taken.add(name); have.add(p); names.push(name);
    }
    if (names.length) await this.app.vault.process(ego, (t) => withFields(t, names));
    this.stats.joined += names.length;
    this.seeded = true;
    if (old instanceof TFile) { await this.app.vault.trash(old, false); this.stats.migrated++; }
    return names.length;
  }
}
