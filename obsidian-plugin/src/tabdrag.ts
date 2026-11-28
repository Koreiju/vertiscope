/**
 * Panels move between Obsidian's tabs and the 2D plane, both ways
 * (2026-11-25: "please ensure all panels in regular obsidian tabs can be
 * dragged into the 2D editor plane, and from the 2D editor plane to the
 * obsidian tabs").
 *
 * IN: the plane is an Obsidian drop zone (`dragManager.handleDrop`). A tab's
 * header -- or a note from the file list -- dropped on it opens that note as a
 * card at the drop point; a tab it came from is closed, so the panel MOVED.
 * OUT: a card dropped on a tab bar opens as a tab in that group and leaves
 * the plane (`PlaneDesk.wireDrop` asks `toTabs` first). Planted
 * `__domvecPlantNoTabDrag`: neither way acts.
 *
 * In trie terms: nothing is written; a note's page is the same vault:// page
 * whichever host draws it.
 */
import { TFile, type App, type WorkspaceLeaf } from "obsidian";

export const tabDragStats = { in: 0, out: 0, last: "" };
(window as any).__domvecTabDragStats = tabDragStats;

/** The tab being dragged, from its header's dragstart (the draggable carries only the file). */
let dragged: { leaf: WorkspaceLeaf; at: number } | null = null;

export function watchTabDrags(app: App): () => void {
  const on = (e: DragEvent) => {
    const h = (e.target as HTMLElement)?.closest?.(".workspace-tab-header");
    if (!h) return;
    let hit: WorkspaceLeaf | null = null;
    app.workspace.iterateAllLeaves((l: any) => { if (l.tabHeaderEl === h) hit = l; });
    dragged = hit ? { leaf: hit, at: performance.now() } : null;
  };
  document.addEventListener("dragstart", on, true);
  return () => document.removeEventListener("dragstart", on, true);
}

/** Make `plane` accept notes dragged from tabs or the file list. */
export function acceptTabDrops(app: App, plane: HTMLElement, open: (f: TFile, at: { x: number; y: number }) => Promise<any>): void {
  // The plane element can outlive a plugin reload. A callback bound once would
  // keep calling the UNLOADED instance's `open` (tab drops did nothing after a
  // reload, 2026-11-28). So one trampoline is registered per plane and always
  // calls the handler the CURRENT instance installed below.
  const dm: any = (app as any).dragManager;
  const host = plane as any;
  const cb = (evt: DragEvent, draggable: any, isOver: boolean) => {
    if ((window as any).__domvecPlantNoTabDrag) return;
    const f: TFile | null = draggable?.file instanceof TFile ? draggable.file : null;
    if (!f || f.extension !== "md") return;
    if (isOver) return { action: "Open on the 2D plane", dropEffect: "move", hoverEl: plane, hoverClass: "is-being-dragged-over" };
    const r = plane.getBoundingClientRect();
    void open(f, { x: evt.clientX - r.left, y: evt.clientY - r.top }).then(() => {
      // From a tab: that tab closes -- the panel moved, it was not copied.
      if (dragged && performance.now() - dragged.at < 60000 && (dragged.leaf.view as any)?.file?.path === f.path) {
        try { dragged.leaf.detach(); } catch { /* gone */ }
      }
      dragged = null;
      tabDragStats.in++; tabDragStats.last = "in " + f.path;
    });
  };
  host.__domvecTabDropImpl = cb;
  if (!host.__domvecTabDropTramp) {
    host.__domvecTabDropTramp = (evt: DragEvent, draggable: any, isOver: boolean) => host.__domvecTabDropImpl?.(evt, draggable, isOver);
    dm?.handleDrop?.(plane, host.__domvecTabDropTramp);
  }
  host.__domvecTabDropCb = host.__domvecTabDropTramp;
}

/** A card dropped at (x, y): over a tab bar, it opens there as a tab; true when taken. */
export function toTabs(app: App, card: HTMLElement, path: string, x: number, y: number): boolean {
  if ((window as any).__domvecPlantNoTabDrag) return false;
  const was = card.style.pointerEvents; card.style.pointerEvents = "none";
  const under = document.elementFromPoint(x, y) as HTMLElement | null;
  card.style.pointerEvents = was;
  const bar = under?.closest?.(".workspace-tab-header-container");
  const group = bar?.closest(".workspace-tabs");
  const f = app.vault.getAbstractFileByPath(path);
  if (!group || !(f instanceof TFile)) return false;
  let sib: any = null;
  app.workspace.iterateAllLeaves((l: any) => { if (!sib && group.contains(l.containerEl)) sib = l; });
  if (!sib) return false;
  const leaf: any = (app.workspace as any).createLeafInParent(sib.parent, (sib.parent?.children?.length ?? 0));
  void leaf.openFile(f).then(() => { app.workspace.setActiveLeaf(leaf, { focus: true }); });
  tabDragStats.out++; tabDragStats.last = "out " + path;
  return true;
}
