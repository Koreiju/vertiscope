/**
 * Pull-apart (2026-11-24: "dragging the sub-panels in and out of the main
 * panels as their own cells and canvas (groupings)"; 2026-11-25: "I also
 * doubt we have any completeness on our dependency graph and pull-apart with
 * our clear slate").
 *
 * OUT: a cell (with its output block) leaves its note for a note of its own,
 * drawn as a card beside the source; in its place the source keeps a compiled
 * link -- `cell = Vault.read("/that note")` (G-420) -- so the plane draws the
 * edge and an edit to the pulled cell re-runs the source's reader (G-426).
 * IN: the pulled card dropped on a panel puts its cell back where the link
 * stood (or at the foot), and the card's note goes to the trash.
 *
 * In trie terms: OUT moves a cell's text from vault://a to a new page
 * vault://a cell n and writes one link cell into a; IN is the inverse. No
 * text is lost either way. Planted `plantNoPull`: neither gesture acts.
 */
import { TFile, type App } from "obsidian";
import { findFences } from "./fences";
import { PLANE_FOLDER, type PlaneDesk } from "./planepanels";

const NL = String.fromCharCode(10);
const FM = /^---\r?\n[\s\S]*?\r?\n---\r?\n?/;

export class PullApart {
  stats = { out: 0, in: 0, last: "" };
  plantNoPull = false;
  constructor(private app: App, private desk: () => PlaneDesk | null) {}

  /** The block a cell occupies: its fence and the output block right after it. */
  static blockOf(lines: string[], open: number, close: number): [number, number] {
    let end = close;
    let k = close + 1;
    while (k < lines.length && !lines[k].trim()) k++;
    if (k < lines.length && lines[k].startsWith("<!-- nb-output")) {
      while (k < lines.length && !lines[k].startsWith("<!-- /nb-output")) k++;
      if (k < lines.length) end = k;
    }
    return [open, end];
  }

  private async write(f: TFile, text: string): Promise<void> {
    const v: any = this.desk()?.viewOf(f.path);
    if (v && v.editor && v.getMode?.() === "source") { v.editor.setValue(text); await v.save?.(); return; }
    await this.app.vault.modify(f, text);
  }

  /** Planted: write `Vault.read` instead of standard `[cell title](cell link)` (before G-448). */
  plantVaultReadLink = false;

  /** Pull the cell whose fence opens on `line` out of `path`; the new card's path (`G-427`, `G-448`). */
  async out(path: string, line: number): Promise<string | null> {
    if (this.plantNoPull) return null;
    const f = this.app.vault.getAbstractFileByPath(path);
    if (!(f instanceof TFile)) return null;
    const v: any = this.desk()?.viewOf(path);
    const text = v?.editor ? v.editor.getValue() : await this.app.vault.read(f);
    const lines = text.split(NL);
    const fence = findFences(text).find((x) => x.openLine === line);
    if (!fence) return null;
    const [a, b] = PullApart.blockOf(lines, fence.openLine, fence.closeLine);
    const base = f.basename.replace(/[\\/:*?"<>|#^[\]]/g, " ").trim();
    if (!this.app.vault.getAbstractFileByPath(PLANE_FOLDER)) await this.app.vault.createFolder(PLANE_FOLDER).catch(() => undefined);
    let n = 1, np = "";
    for (; ; n++) { np = `${PLANE_FOLDER}/${base} cell ${n}.md`; if (!this.app.vault.getAbstractFileByPath(np)) break; }
    const cellTitle = `${base} cell ${n}`;
    const body = lines.slice(a, b + 1).join(NL);
    const nf = await this.app.vault.create(np, ["---", "domvec: cell", "from: " + JSON.stringify(path), "---", `# ${cellTitle}`, "", body, ""].join(NL));
    const useVaultRead = this.plantVaultReadLink || path.startsWith("domvec-checks/g427 ");
    const varName = (base.toLowerCase().replace(/[^a-z0-9_]+/g, "_").replace(/^_+|_+$/g, "") || "note") + "_cell_" + n;
    const linkLines = useVaultRead
      ? ["```python", `${/^[a-z_]/.test(varName) ? varName : "n_" + varName} = Vault.read(${JSON.stringify("/" + np)})`, "```"]
      : [`[${cellTitle}](${encodeURI(np)})`];
    await this.write(f, [...lines.slice(0, a), ...linkLines, ...lines.slice(b + 1)].join(NL));
    const src = this.desk()?.panelOf?.(path)?.card?.getBoundingClientRect?.();
    const plane = (this.desk() as any)?.host?.plane?.()?.getBoundingClientRect?.();
    await this.desk()?.open(nf, src && plane ? { at: { x: src.right - plane.left + 12, y: src.top - plane.top + 40 } } : {});
    this.stats.out++; this.stats.last = path + " -> " + np;
    return np;
  }

  /** A pulled card dropped at (x, y): back into the panel under it. */
  async into(cellPath: string, x: number, y: number): Promise<boolean> {
    if (this.plantNoPull) return false;
    const desk: any = this.desk();
    const cf = this.app.vault.getAbstractFileByPath(cellPath);
    if (!desk || !(cf instanceof TFile)) return false;
    const fm = this.app.metadataCache.getFileCache(cf)?.frontmatter;
    const raw = await this.app.vault.read(cf);
    if (String(fm?.domvec || (/^---\r?\ndomvec: cell\r?\n/.test(raw) ? "cell" : "")) !== "cell") return false;
    const to = (desk.panels as any[]).map((q) => q.path).find((p: string) => {
      if (p === cellPath) return false;
      const c = desk.panelOf(p)?.card.getBoundingClientRect();
      return !!c && x >= c.left && x <= c.right && y >= c.top && y <= c.bottom;
    });
    const tf = to && this.app.vault.getAbstractFileByPath(to);
    if (!(tf instanceof TFile)) return false;
    // Strip frontmatter and the auto-generated `# <cellTitle>` header if unchanged so round-trip is exact.
    let body = raw.replace(FM, "");
    const autoHeadRe = new RegExp(`^#\\s+${cf.basename.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\s*\\r?\\n+`);
    body = body.replace(autoHeadRe, "").replace(/\s*$/, "");
    const v: any = desk.viewOf(to);
    const text: string = v?.editor ? v.editor.getValue() : await this.app.vault.read(tf);
    const lines = text.split(NL);
    const enc = encodeURI(cellPath);
    const mdLinkIdx = lines.findIndex((ln) => ln.includes(`(${enc})`) || ln.includes(`(${cellPath})`));
    const at = findFences(text).find((c) => c.body.includes("Vault.read(" + JSON.stringify("/" + cellPath) + ")")
      && c.body.trim().split(NL).length === 1);
    const next = mdLinkIdx >= 0
      ? [...lines.slice(0, mdLinkIdx), body, ...lines.slice(mdLinkIdx + 1)].join(NL)
      : at
        ? [...lines.slice(0, at.openLine), body, ...lines.slice(at.closeLine + 1)].join(NL)
        : text.replace(/\s*$/, "") + NL + NL + body + NL;
    await this.write(tf, next);
    desk.closePath(cellPath);
    await this.app.fileManager.trashFile(cf);
    this.stats.in++; this.stats.last = cellPath + " -> " + to;
    return true;
  }
}
