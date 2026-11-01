/**
 * The code artifact panel -- `P-C1`, `P-C2`, `P-C5`.
 *
 * "Full code artifacts should be viewable and editable as standalone as well.
 * A terminal only below the artifact panel should always accompany the
 * artifact." And: "we can view live delta updates to modules as well in both
 * sides of their panels and their UMAP 3D graph view."
 *
 * One `code://` module, three parts:
 *  - the SOURCE side: the file in a CodeMirror editor, editable for this
 *    repository's modules (`code://repo/`), read-only for an installed
 *    package; Ctrl/Cmd+S or `save` writes the file and re-indexes it
 *    (`POST /source`);
 *  - the TRIE side: the module's chunks as the store holds them -- names,
 *    docstrings, comments, the addresses the encoder sees (`G-52`) -- re-read
 *    after every save, the chunks that changed marked;
 *  - the RUN surface directly below both (`NOTEBOOK_PANEL_DESIGN` §4a: a
 *    kernel run-and-output surface, not a shell prompt): `run` executes the
 *    module's text (or the selection) in a kernel of its own, keyed by the
 *    url, with `__package__` set so a relative import resolves; the line
 *    below evaluates expressions in that same namespace.
 * The 3D half of P-C5 is the projector's: a save queues the module's page,
 * and the graph's delta stream redraws what moved.
 */
import { ItemView, MarkdownRenderer, type WorkspaceLeaf } from "obsidian";
import { EditorState } from "@codemirror/state";
import { EditorView, keymap } from "@codemirror/view";
import type { Sidecar } from "./sidecar";

export const CODE_VIEW = "domvec-code-view";

interface SideChunk { cid: string; xpath: string; md: string }

export class CodeView extends ItemView {
  url = "";
  module = "";
  editable = false;
  editor: EditorView | null = null;
  private savedText = "";
  private chunks: SideChunk[] = [];
  /** The chunks the last save changed or added (by cid), drawn marked. */
  changed = new Set<string>();
  stats = { saves: 0, runs: 0, last: null as any };
  /** Planted (P-C2): the run surface asks some OTHER kernel, not the module's. */
  plantOtherKernel = false;
  /** Planted (P-C5): a save does not re-read the trie side. */
  plantNoTrieRefresh = false;
  private head!: HTMLElement;
  private sourceEl!: HTMLElement;
  private trieEl!: HTMLElement;
  private outEl!: HTMLElement;
  private input!: HTMLInputElement;

  constructor(leaf: WorkspaceLeaf, private sidecar: Sidecar) { super(leaf); }

  getViewType(): string { return CODE_VIEW; }
  getDisplayText(): string { return this.url ? this.url.replace(/^code:\/\/[^/]+\//, "") : "code artifact"; }
  getIcon(): string { return "file-code"; }
  getState(): any { return { url: this.url }; }

  async setState(state: any, result: any): Promise<void> {
    if (state && state.url && state.url !== this.url) await this.openUrl(String(state.url));
    return super.setState(state, result);
  }

  async onOpen(): Promise<void> {
    const root = this.contentEl;
    root.empty();
    root.addClass("domvec-code");
    this.head = root.createDiv({ cls: "domvec-code-head" });
    const sides = root.createDiv({ cls: "domvec-code-sides" });
    this.sourceEl = sides.createDiv({ cls: "domvec-code-source" });
    this.trieEl = sides.createDiv({ cls: "domvec-code-trie markdown-rendered" });
    const run = root.createDiv({ cls: "domvec-code-run" });
    this.outEl = run.createEl("pre", { cls: "domvec-code-out" });
    this.input = run.createEl("input", { cls: "domvec-code-input", attr: { placeholder: "an expression in this module's kernel -- Enter runs" } });
    this.input.addEventListener("keydown", (e) => {
      e.stopPropagation();
      if (e.key === "Enter" && this.input.value.trim()) { const q = this.input.value; this.input.value = ""; void this.run(q); }
    });
  }

  async onClose(): Promise<void> { this.editor?.destroy(); this.editor = null; }

  get dirty(): boolean { return !!this.editor && this.text() !== this.savedText; }
  text(): string { return this.editor ? this.editor.state.doc.toString() : ""; }

  /** Open a module: its file on the source side, its chunks on the trie side. */
  async openUrl(url: string): Promise<boolean> {
    if (!this.sourceEl) await this.onOpen();
    const got = await this.sidecar.source(url);
    this.url = url;
    if (!got || got.error) { this.head.setText((got && got.error) || "the sidecar did not answer"); return false; }
    this.module = got.module || "";
    this.editable = !!got.editable;
    this.savedText = got.text || "";
    this.renderHead();
    this.editor?.destroy();
    this.sourceEl.empty();
    this.editor = new EditorView({
      parent: this.sourceEl,
      state: EditorState.create({
        doc: this.savedText,
        extensions: [
          EditorView.editable.of(this.editable),
          EditorState.readOnly.of(!this.editable),
          EditorView.lineWrapping,
          keymap.of([{ key: "Mod-s", preventDefault: true, run: () => { void this.save(); return true; } }]),
          EditorView.updateListener.of((u) => { if (u.docChanged) this.renderHead(); }),
        ],
      }),
    });
    this.changed.clear();
    await this.readTrie();
    (this.leaf as any).updateHeader?.();
    return true;
  }

  private renderHead(): void {
    this.head.empty();
    this.head.createSpan({ cls: "domvec-code-url", text: this.url });
    this.head.createSpan({ cls: "domvec-code-badge", text: this.editable ? (this.dirty ? "edited" : "saved") : "read-only" });
    if (this.editable) {
      const save = this.head.createEl("button", { text: "save" });
      save.disabled = !this.dirty;
      save.onclick = () => void this.save();
    }
    const run = this.head.createEl("button", { text: "run" });
    run.onclick = () => {
      const sel = this.editor?.state.selection.main;
      void this.run(sel && !sel.empty ? this.editor!.state.sliceDoc(sel.from, sel.to) : this.text(), true);
    };
  }

  /** The trie side: every chunk the store holds for the module, in order. */
  async readTrie(): Promise<SideChunk[]> {
    const before = new Map(this.chunks.map((c) => [c.cid, c.md]));
    const cids = await this.sidecar.pageCids(this.url);
    const next: SideChunk[] = [];
    for (const cid of cids) {
      const p: any = await this.sidecar.chunk(cid);
      if (p) next.push({ cid, xpath: p.xpath || "", md: (p.lines || []).map((l: any) => l.text || "").join("\n") });
    }
    next.sort((a, b) => a.xpath.localeCompare(b.xpath, undefined, { numeric: true }));
    if (before.size) {
      this.changed = new Set(next.filter((c) => before.get(c.cid) !== c.md).map((c) => c.cid));
    }
    this.chunks = next;
    this.trieEl.empty();
    for (const c of next) {
      const box = this.trieEl.createDiv({ cls: "domvec-code-chunk", attr: { "data-cid": c.cid } });
      box.toggleClass("is-changed", this.changed.has(c.cid));
      box.createDiv({ cls: "domvec-code-xpath", text: c.xpath });
      await MarkdownRenderer.render(this.app, c.md, box.createDiv(), "", this);
    }
    return next;
  }

  /** Write the file and re-index it; both sides and the 3D view follow. */
  async save(): Promise<any> {
    if (!this.editable || !this.editor) return null;
    const text = this.text();
    const got = await this.sidecar.saveSource(this.url, text);
    this.stats.saves++;
    this.stats.last = got;
    if (got && !got.error) {
      this.savedText = text;
      if (!this.plantNoTrieRefresh) await this.readTrie();
    }
    this.renderHead();
    return got;
  }

  /** Run in the module's own kernel; output appended below. */
  async run(code: string, whole = false): Promise<any> {
    const pkg = this.module.includes(".") ? this.module.slice(0, this.module.lastIndexOf(".")) : "";
    const pre = whole && pkg ? `__package__ = ${JSON.stringify(pkg)}\n` : "";
    this.stats.runs++;
    const r: any = await this.sidecar.runCell(this.plantOtherKernel ? "code:elsewhere" : "code:" + this.url, pre + code);
    const lines: string[] = [`>>> ${whole ? `run ${this.getDisplayText()}` : code}`];
    if (!r) lines.push("(the sidecar did not answer)");
    else {
      if (r.stdout) lines.push(r.stdout.replace(/\n$/, ""));
      if (r.value != null) lines.push(String(r.value));
      if (r.stderr) lines.push(r.stderr.replace(/\n$/, ""));
      if (r.error) lines.push(String(r.error).replace(/\n$/, ""));
    }
    this.outEl.appendText(lines.join("\n") + "\n");
    this.outEl.scrollTop = this.outEl.scrollHeight;
    return r;
  }
}
