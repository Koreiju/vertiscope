/**
 * The gesture guides (PLUGIN_GOAL 159: "there should be clearer instructions
 * on how gestures for the 2D editor work in some hoverable button that
 * expands into a full panel of instructions on the gestures on the 2D
 * computation graph. There can be another button for that which corresponds
 * to the 3D gestures like moving the camera with wasd+arrows etc, also simple
 * guides on the fundamental tool cell sets that we have outlined in our
 * README, where each row in the first table is a different cell-level tool").
 *
 * Three buttons on the graph's bar. Hovering one expands its panel; a click
 * pins it open (another click, or Escape, closes it). The 3D keys come from
 * the agent's own key table, and the tool rows from the README's first table
 * read at open time -- so neither list can drift from what they describe.
 */
import type { App } from "obsidian";

export type HelpRow = [string, string];

/** The 2D computation-graph plane: every gesture it answers, as built. */
export const GESTURES_2D: HelpRow[] = [
  ["drag a node", "moves the whole ego plane on screen"],
  ["click a node", "selects it (a ring); a note's halo of related notes opens a moment later"],
  ["click a tagged web chunk", "opens that chunk's panel -- the world node's own"],
  ["double-click a node with links", "the plane flies to what it links in 3D (several: their centre) and takes those chunks in"],
  ["double-click a note without links", "opens its panel on the plane, or closes it"],
  ["shift + scroll", "zooms the 2D plane (plain scroll zooms the 3D view)"],
  ["ego 2D / ego 3D (bar)", "the flat plane facing you, or the ego's 3D layout"],
  ["drag a card by its header node", "moves the card; its node moves with it in the ego"],
  ["hover a card's edge, drag", "resizes it from that edge or corner"],
  ["right-click a card's header", "minimizes it to its node; twice quickly deletes it"],
  ["alt + click a header node", "contains its linked collapsed nodes"],
  ["drag a node onto another", "wires a reference from one to the other"],
  ["click the codebase hub", "unfolds its modules, or folds them back"],
];

/** The 3D view's mouse gestures (the keys come from the agent's table). */
export const GESTURES_3D_MOUSE: HelpRow[] = [
  ["left-drag", "orbits the camera about its focus"],
  ["scroll", "zooms toward the focus; into the ego in the ego view"],
  ["right-drag", "pans the camera"],
  ["hover a node", "previews its panel after a short dwell"],
  ["click a node", "opens its panel; a page unfolds into its chunks"],
  ["hover a chunk in the browser", "the camera flies to its node and follows it"],
  ["right-click a link", "keeps it as a memory link, or lets it fade"],
  ["drift (bar)", "with no input, the scene slowly turns"],
];

/** The README's FIRST table, as rows: each a cell-level tool and what it is. */
export async function readmeTools(app: App): Promise<HelpRow[]> {
  let text = "";
  try { text = await app.vault.adapter.read("README.md"); } catch { return []; }
  const lines = text.split(/\r?\n/);
  const rows: HelpRow[] = [];
  let i = lines.findIndex((l) => /^\s*\|.*\|\s*$/.test(l));
  if (i < 0) return rows;
  i += 2;                                   // the header and its |---| rule
  for (; i < lines.length && /^\s*\|/.test(lines[i]); i++) {
    const cells = lines[i].split("|").slice(1, -1).map((c) => c.trim());
    if (cells.length < 2) continue;
    const name = cells[0].replace(/\*\*/g, "").trim();
    const what = cells[1].replace(/\*\*/g, "").replace(/`/g, "").trim();
    rows.push([name, what]);
  }
  return rows;
}

export interface HelpStats { opens: number; pins: number; last: string }
export const HELP_STATS: HelpStats = { opens: 0, pins: 0, last: "" };

/**
 * A button that expands into a panel of rows on hover and pins on click.
 * `rows` is called each time the panel opens.
 */
export function helpButton(bar: HTMLElement, label: string, title: string, rows: () => Promise<HelpRow[]> | HelpRow[]): HTMLElement {
  const btn = bar.createEl("button", { text: label, cls: "domvec-help-button" });
  btn.setAttr("aria-label", title);
  let panel: HTMLElement | null = null, pinned = false, hideTimer = 0;
  const close = () => { panel?.remove(); panel = null; pinned = false; btn.removeClass("is-pinned"); };
  const open = async () => {
    window.clearTimeout(hideTimer);
    // Planted `window.__domvecPlantNoHelp`: no guide opens, as before 159.
    if (panel || (window as any).__domvecPlantNoHelp) return;
    panel = document.body.createDiv({ cls: "domvec-help-panel" });
    panel.dataset.help = label;
    const r = btn.getBoundingClientRect();
    panel.style.left = `${Math.max(8, Math.min(window.innerWidth - 440, r.left))}px`;
    panel.style.top = `${r.bottom + 6}px`;
    panel.createDiv({ cls: "domvec-help-title", text: title });
    const table = panel.createEl("table", { cls: "domvec-help-table" });
    for (const [k, v] of await rows()) {
      const tr = table.createEl("tr");
      tr.createEl("td", { cls: "domvec-help-key", text: k });
      tr.createEl("td", { text: v });
    }
    panel.addEventListener("pointerenter", () => window.clearTimeout(hideTimer));
    panel.addEventListener("pointerleave", () => { if (!pinned) hideTimer = window.setTimeout(close, 250); });
    HELP_STATS.opens++; HELP_STATS.last = label;
  };
  btn.addEventListener("pointerenter", () => { void open(); });
  btn.addEventListener("pointerleave", () => { if (!pinned) hideTimer = window.setTimeout(close, 250); });
  btn.addEventListener("click", async () => {
    if (pinned) { close(); return; }
    await open(); pinned = true; btn.addClass("is-pinned"); HELP_STATS.pins++;
  });
  window.addEventListener("keydown", (e) => { if (e.key === "Escape" && panel) close(); });
  return btn;
}
