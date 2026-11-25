/**
 * The editor's own calls, carried out on the plane (G-386; PLUGIN_GOAL 172 [3];
 * mortegon §3A.7, DM §12.6.1: the agent authors with the user's primitives --
 * "the cards are the API").
 *
 * A kernel cell (a person's, or an agent step written as a cell, G-384) calls
 * `create`, `link`, `invoke`, `commit` or `review`; each records an ASK in the
 * kernel, the sidecar drains the asks after the cell and returns them in the
 * reply, and this carries them out by the SAME methods the gestures use:
 *
 *   create(name, body, kind) -> PlaneDesk.create, a card at domvec/graph/<name>.md
 *   link(a, b)               -> a markdown link appended to a, as a wire-drop does
 *   invoke(name)             -> each python cell of the card run in order, lit
 *   commit(name, *members)   -> a card that links each member: the subgraph as one node
 *   review(name, question)   -> a question callout written onto the card
 *
 * In trie terms: every call writes a vault note (a `vault://` page), and the
 * note's links and `{ref}`s are the edges the plane and the 3D graph draw --
 * nothing reaches the plane except through a note.
 */
import { Notice, TFile, type App } from "obsidian";
import { cellSource, findFences } from "./fences";
import { PLANE_FOLDER, type PlaneDesk } from "./planepanels";
import type { RunRequest } from "./runbutton";

export interface EditorHost {
  app: App;
  desk: PlaneDesk;
  onRunFence(req: RunRequest): Promise<any>;
}

const NL = String.fromCharCode(10);
/** A card's name as the plane keys it: basename, spaces as underscores, case-folded. */
const key = (n: string) => n.trim().toLowerCase().replace(/\s+/g, "_");
/** Characters a vault file name cannot hold. */
const UNSAFE = /[\\/:*?"<>|#^[\]]/g;

export class EditorCalls {
  stats = { create: 0, link: 0, invoke: 0, commit: 0, review: 0, refused: 0, last: null as any };
  /** Planted: a review written without its answer slot, as before 180. */
  plantNoAnswerSlot = false;
  /** Planted: the asks are recognised but not carried out. */
  plantNoCarry = false;
  /** Cards being invoked now: an invoke that reaches one again is a cycle (§3A.5). */
  private invoking = new Set<string>();

  constructor(private host: EditorHost) {}

  /** The card a name refers to: an exact path, or a note under the plane's
   *  folder (then anywhere) whose basename matches. */
  pathOf(name: string): string | null {
    const app = this.host.app;
    const direct = app.vault.getAbstractFileByPath(name.endsWith(".md") ? name : name + ".md");
    if (direct instanceof TFile) return direct.path;
    const k = key(name);
    const files = app.vault.getMarkdownFiles();
    const hit = files.find((f) => f.path.startsWith(PLANE_FOLDER + "/") && key(f.basename) === k)
      || files.find((f) => key(f.basename) === k);
    return hit ? hit.path : null;
  }

  /** Carry out one ask; the line for the run's notice, or null when it is not an editor ask. */
  async carry(a: any): Promise<string | null> {
    if (!a || typeof a !== "object") return null;
    const kind = ["create", "link", "invoke", "commit", "review"].find((k) => k in a);
    if (!kind) return null;
    if (this.plantNoCarry) return `${kind}: not carried out (planted)`;
    try {
      const got = await (this as any)["do_" + kind](a[kind]);
      (this.stats as any)[kind]++;
      this.stats.last = { kind, ...got };
      return `${kind}: ${got.said}`;
    } catch (e) {
      this.stats.refused++;
      this.stats.last = { kind, refused: String((e as Error).message || e) };
      return `${kind} refused: ${(e as Error).message || e}`;
    }
  }

  /** A block appended after a blank line. Into the card's EDITOR when it is
   *  open on the plane (its own save persists it), else into the file: a file
   *  write under an open editor races its autosave, and the editor's older
   *  text can land last (main.ts storeOutput, 2026-10-25). Planted
   *  `plantFileAppend`: always the file. */
  plantFileAppend = false;
  stats_append = { editor: 0, file: 0 };
  private async append(f: TFile, block: string): Promise<void> {
    const v = this.plantFileAppend ? null : this.host.desk.viewOf(f.path);
    if (v && v.editor && v.getMode() === "source") {
      const ed = v.editor, text = ed.getValue();
      const keep = text.replace(/\s*$/, "");
      const from = ed.offsetToPos(keep.length), to = ed.offsetToPos(text.length);
      ed.replaceRange(NL + NL + block + NL, from, to);
      this.stats_append.editor++;
      return;
    }
    await this.host.app.vault.process(f, (t) => t.replace(/\s*$/, "") + NL + NL + block + NL);
    this.stats_append.file++;
  }

  private async do_create(c: { name: string; body?: string; kind?: string }) {
    const name = String(c.name || "").replace(UNSAFE, " ").trim();
    if (!name) throw new Error("a card needs a name");
    const path = `${PLANE_FOLDER}/${name}.md`;
    if (this.host.app.vault.getAbstractFileByPath(path)) throw new Error(`${path} exists`);
    const kind = c.kind === "notebook" ? "notebook" : "slate";
    const body = String(c.body || "");
    // The same text a gesture's new card gets, with the body filled in: a
    // slate is its name over one indented row; a notebook one python cell.
    const text = kind === "slate"
      ? ["---", "domvec: slate", "---", name.replace(/\s+/g, "_"), "\t" + (body || "value") + "\t", ""].join(NL)
      : ["```python", body, "```", ""].join(NL);
    await this.host.desk.create(kind, { path, text });
    return { path, said: `${kind} card ${name}` };
  }

  /** Planted (O-7): `link` writes a wiki link, as before. */
  plantWikiLink = false;

  private async do_link(pair: [string, string]) {
    const [a, b] = (pair || []).map(String);
    const pa = this.pathOf(a), pb = this.pathOf(b);
    if (!pa) throw new Error(`no card ${a}`);
    if (!pb) throw new Error(`no card ${b}`);
    if (pa === pb) throw new Error("a card cannot link itself");
    if (this.host.desk.linkedTo(pa).has(pb)) return { from: pa, to: pb, said: `${a} and ${b} already linked` };
    const src = this.host.app.vault.getAbstractFileByPath(pa) as TFile, dst = this.host.app.vault.getAbstractFileByPath(pb) as TFile;
    // A COMPILED link (194; O-7): a code cell in a's note that reads b, which
    // the reservoir runs and the plane draws -- never a wiki link (T-4).
    // Planted `plantWikiLink`: the old wiki link.
    if (this.plantWikiLink) await this.append(src, this.host.app.fileManager.generateMarkdownLink(dst, src.path));
    else await this.append(src, ["```python", varOf(dst.basename) + " = Vault.read(" + JSON.stringify("/" + pb) + ")", "```"].join(NL));
    return { from: pa, to: pb, said: `${a} -- ${b}` };
  }

  private async do_invoke(name: string) {
    const p = this.pathOf(String(name));
    if (!p) throw new Error(`no card ${name}`);
    if (this.invoking.has(p)) throw new Error(`${name} is already running: a cycle`);
    const f = this.host.app.vault.getAbstractFileByPath(p) as TFile;
    const cells = findFences(await this.host.app.vault.read(f)).filter((x) => x.lang === "python" && x.body.trim());
    if (!cells.length) throw new Error(`${name} has no python cell`);
    this.invoking.add(p);
    let ok = 0;
    try {
      for (const c of cells) {
        // The source as the run button sends it (`cellSource`): storeOutput
        // places the output only at a fence whose source matches exactly.
        const r = await this.host.onRunFence({ path: p, lang: "python", code: cellSource(c.body), line: c.openLine, refs: c.refs });
        if (r && r.ok) ok++; else break;
      }
    } finally { this.invoking.delete(p); }
    return { path: p, cells: cells.length, ok, said: `${name}: ${ok} of ${cells.length} cells ran` };
  }

  private async do_commit(c: { name: string; members: string[] }) {
    const members = (c.members || []).map(String);
    if (!members.length) throw new Error("a subgraph needs members");
    const paths = members.map((m) => this.pathOf(m));
    const missing = members.filter((_, i) => !paths[i]);
    if (missing.length) throw new Error(`no card ${missing.join(", ")}`);
    // The group as a NEW thing (194 f): one code cell reading each member, so
    // the composite runs on the reservoir and its links are compiled (O-7).
    const body = paths.map((q) => varOf(q!.replace(/^.*\//, "").replace(/\.md$/, "")) + " = Vault.read(" + JSON.stringify("/" + q) + ")").join(NL);
    const got = await this.do_create({ name: c.name, kind: "notebook", body });
    return { path: got.path, members: paths, said: `${c.name} holds ${members.length}` };
  }

  private async do_review(pair: [string, string]) {
    const [name, question] = (pair || []).map(String);
    const p = this.pathOf(name);
    if (!p) throw new Error(`no card ${name}`);
    if (!question.trim()) throw new Error("a review needs a question");
    const f = this.host.app.vault.getAbstractFileByPath(p) as TFile;
    // The answer SLOT is the callout's last line: the reader writes after it,
    // and a cell's `answer(name)` reads it back (PLUGIN_GOAL 180; synthesis 1d).
    const callout = ["> [!question] review", ...question.trim().split(NL).map((l) => "> " + l),
      ...(this.plantNoAnswerSlot ? [] : ["> **answer:** "])].join(NL);
    await this.append(f, callout);
    new Notice(`domvec: review asked on ${name} -- ${question}`, 8000);
    return { path: p, said: `asked on ${name}` };
  }
}

/** A note name as a Python identifier, for the cell that reads it. */
function varOf(name: string): string { const v = name.toLowerCase().replace(/[^a-z0-9_]+/g, "_").replace(/^_+|_+$/g, ""); return /^[a-z_]/.test(v) ? v : "n_" + v; }
