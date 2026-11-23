/**
 * The ego canvas (PLUGIN_GOAL 183; G-396, design `docs/EGO_CANVAS_DESIGN.md`).
 *
 * "the central consolidated panel that can be pulled apart into a graph of
 * panels ... every component about the ego contained/containable within a
 * common and central artifact canvas representation".
 *
 * The canvas is ONE note, `domvec/ego canvas.md`. Each line of its body is a
 * section: `![[note]]` a component CONTAINED (drawn in the canvas, live and
 * editable with its own tools), `[[note]]` a component PULLED OUT (its own
 * panel; the link kept). The line order is the compile order a model reads
 * (item 142). The canvas sits at the plane's centre.
 *
 * In trie terms: the canvas is a vault:// page, a section one of its lines,
 * and the component the page that line links to -- every operation here is a
 * write of one line of that page.
 */
import { TFile, type App } from "obsidian";

import { CANVAS_PATH, sectionsOf, lineFor, type Section } from "./canvasparse";
export { CANVAS_PATH, sectionsOf, lineFor };
export type { Section };
const NL = "\n";

export interface CanvasDesk {
  app: App;
  plane(): HTMLElement | null;
  /** The ego's members as the craft knows them (G-291's rule). */
  members(): string[];
}

export class EgoCanvas {
  /** Sections the reader has unfolded (the cockpit is, by default). */
  unfolded = new Set<string>(["domvec/ego.md"]);
  private leaves = new Map<string, any>();
  stats = { seeded: 0, rendered: 0, mounted_editors: 0 };
  /** Planted (G-396, seen 2026-11-22): a section's editor at automatic
   *  height -- an Obsidian leaf's content is absolutely positioned, so the
   *  unfolded section drew nothing. */
  static plantAutoHeight = false;
  el: HTMLElement | null = null;
  private file: TFile | null = null;

  constructor(private desk: CanvasDesk) {}

  private get app(): App { return this.desk.app; }

  /** The canvas note, seeded once from the craft's membership: the cockpit
   *  first, then every other member, contained. */
  async ensure(): Promise<TFile> {
    const got = this.app.vault.getAbstractFileByPath(CANVAS_PATH);
    if (got instanceof TFile) return got;
    const members = this.desk.members().filter((p) => p !== "domvec/ego.md" && !EgoCanvas.scratch(p));
    const body = ["---", "domvec: canvas", "---", "", lineFor("domvec/ego.md", true), ...members.map((p) => lineFor(p, true)), ""].join(NL);
    this.stats.seeded = members.length + 1;
    return this.app.vault.create(CANVAS_PATH, body);
  }

  /** Mount into a plane card (the desk's `open` hands the card over). */
  async mount(card: HTMLElement, file: TFile): Promise<() => void> {
    this.file = file;
    card.addClass("is-canvas");
    this.el = card.createDiv({ cls: "domvec-canvas" });
    this.centre(card);
    const ref = this.app.vault.on("modify", (f) => { if (f.path === file.path) void this.render(); });
    await this.sync();
    await this.render();
    return () => { this.app.vault.offref(ref); for (const l of this.leaves.values()) { try { l.detach(); } catch { /* gone */ } } this.leaves.clear(); this.el?.remove(); this.el = null; };
  }

  /** At the plane's centre, always (183: "plane center"). */
  centre(card: HTMLElement): void {
    const plane = this.desk.plane();
    if (!plane) return;
    const w = Math.min(560, Math.round(plane.clientWidth * 0.62));
    card.style.width = w + "px";
    card.style.right = "auto";
    card.style.left = Math.round((plane.clientWidth - w) / 2) + "px";
    card.style.top = Math.max(8, Math.round(plane.clientHeight * 0.08)) + "px";
  }

  /** A note that is the ego's but only while a check runs -- never the canvas's. */
  static scratch(p: string): boolean {
    return p === CANVAS_PATH || p.startsWith("domvec-checks/") || /^domvec\/graph\/(g\d+|pg\d+|t\d+|flip )/i.test(p);
  }

  /** The canvas FOLLOWS the ego (183: "every component about the ego
   *  contained/containable"): a member the canvas does not hold yet joins it,
   *  contained, at the end. A section the reader pulled out stays out; a
   *  check's scratch note never joins. Planted `plantSeedOnce`: seeded once,
   *  never followed -- a note made after the seed is not in the canvas. */
  static plantSeedOnce = false;
  syncStats = { joined: 0 };
  async sync(): Promise<number> {
    if (!this.file || EgoCanvas.plantSeedOnce) return 0;
    const have = new Set((await this.sections()).map((s) => s.path));
    const add = this.desk.members().filter((p) => !have.has(p) && !EgoCanvas.scratch(p));
    if (!add.length) return 0;
    await this.app.vault.process(this.file, (t) => t.replace(/\s*$/, "") + NL + add.map((p) => lineFor(p, true)).join(NL) + NL);
    this.syncStats.joined += add.length;
    return add.length;
  }

  async sections(): Promise<Section[]> {
    return this.file ? sectionsOf(await this.app.vault.read(this.file)) : [];
  }

  async render(): Promise<void> {
    if (!this.el || !this.file) return;
    const secs = await this.sections();
    const keep = new Set<string>();
    this.el.empty();
    this.el.toggleClass("plant-autoheight", EgoCanvas.plantAutoHeight);
    for (const s of secs) {
      const f = this.app.vault.getAbstractFileByPath(s.path);
      const name = s.path.replace(/^.*\//, "").replace(/\.md$/, "");
      const sec = this.el.createDiv({ cls: "domvec-canvas-section" + (s.embedded ? "" : " is-out") });
      sec.dataset.path = s.path;
      const head = sec.createDiv({ cls: "domvec-canvas-head" });
      const open = s.embedded && this.unfolded.has(s.path);
      head.createSpan({ cls: "domvec-canvas-fold", text: s.embedded ? (open ? "▾" : "▸") : "↗" });
      head.createSpan({ cls: "domvec-canvas-name", text: name });
      if (!(f instanceof TFile)) head.createSpan({ cls: "domvec-canvas-missing", text: "  (no such note)" });
      head.onclick = (e) => {
        e.stopPropagation();
        if (!s.embedded) return;
        if (this.unfolded.has(s.path)) this.unfolded.delete(s.path); else this.unfolded.add(s.path);
        void this.render();
      };
      head.addEventListener("mousedown", (e) => e.stopPropagation());
      if (open && f instanceof TFile) {
        keep.add(s.path);
        const body = sec.createDiv({ cls: "domvec-canvas-body" });
        let leaf = this.leaves.get(s.path);
        if (!leaf) {
          const ws: any = this.app.workspace;
          const Leaf: any = ws.activeLeaf?.constructor ?? ws.getMostRecentLeaf()?.constructor;
          if (!Leaf) continue;
          leaf = new Leaf(this.app);
          await leaf.openFile(f, { state: { mode: "source", source: false } } as any);
          this.leaves.set(s.path, leaf);
          this.stats.mounted_editors++;
        }
        body.appendChild(leaf.containerEl);
        body.addEventListener("mousedown", (e) => e.stopPropagation());
      }
    }
    // An editor for a section folded or removed is released.
    for (const [p, l] of [...this.leaves]) if (!keep.has(p)) { try { l.detach(); } catch { /* gone */ } this.leaves.delete(p); }
    this.stats.rendered++;
  }

  /** One section's line rewritten (contained <-> pulled out), or a section
   *  added at `index` -- every graph operation is one line of the note. */
  async setLine(path: string, embedded: boolean, index?: number): Promise<void> {
    if (!this.file) return;
    await this.app.vault.process(this.file, (t) => {
      const L = t.split(NL);
      const at = sectionsOf(t).find((s) => s.path === path);
      if (at) L.splice(at.line, 1);
      const secs = sectionsOf(L.join(NL));
      // No index: the line stays where it was (a pull-out keeps its order).
      const ins = index === undefined && at ? at.line
        : index === undefined || index >= secs.length ? (secs.length ? secs[secs.length - 1].line + 1 : L.length) : secs[index].line;
      L.splice(ins, 0, lineFor(path, embedded));
      return L.join(NL);
    });
  }
}
