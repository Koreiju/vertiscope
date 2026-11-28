/**
 * Interactive, recursively chunked ` ```tool ` cells, `back`/`forward` stack
 * navigation, cursor-exit execution, and vanishing upward history (`G-453`;
 * extends `G-421`, PLUGIN_GOAL 201 f).
 *
 * In trie terms:
 * - Each ` ```tool ` cell at `vault://<vault>/<note>#tool <k>` renders an
 *   interactive projection over `tool://`, `https://`, or `vault://` chunks and
 *   controls (`url|xpath`), driven by slim single-key dictionaries:
 *     `{"browser": {"search": "...", "click": "", "next_chunk": false, "prev_chunk": false, "back": false, "forward": false, "chunks": true}}`
 * - Navigating (`back`, `forward`, `search`, `chunks: true`, or clicking a
 *   linked chunk/control) updates the cell in place and appends a compact
 *   timestamped markdown history line (`> \`HH:MM:SS\` ...`) directly above the
 *   ` ```tool ` fence.
 * - Consecutive tool-call history lines above a ` ```tool ` fence render inside
 *   a compact vanishing upward-scroll strip that expands smoothly on hover.
 */

import { RangeSetBuilder, type Extension } from "@codemirror/state";
import { Decoration, EditorView, ViewPlugin, type DecorationSet, type ViewUpdate } from "@codemirror/view";
import { MarkdownPostProcessorContext, TFile, type App } from "obsidian";
import { findFences, type Fence } from "./fences";

const NL = "\n";

export const toolCellStats = {
  rendered: 0,
  calls: 0,
  back_navs: 0,
  forward_navs: 0,
  chunk_drills: 0,
  history_written: 0,
  exit_runs: 0,
  last_tool: "",
};
(window as any).__domvecToolCell = toolCellStats;

export interface ToolCellHost {
  sidecarBase: () => string;
  carryAsk: (ask: any) => Promise<any>;
}

/** Insert `historyLine` directly above the ` ```tool ` fence at `openLine`, and optionally update its body to `newFenceBody`. */
export async function writeToolStepToNote(
  app: App,
  file: TFile,
  openLineHint: number,
  newFenceBody: string | null,
  historyLine: string | null,
): Promise<boolean> {
  let wrote = false;
  await app.vault.process(file, (raw) => {
    const lines = raw.replace(/\r\n/g, NL).split(NL);
    const fences = findFences(lines.join(NL)).filter((f) => f.lang.toLowerCase() === "tool");
    if (!fences.length) return raw;
    const f = fences.find((x) => x.openLine === openLineHint) || fences[fences.length - 1];
    if (newFenceBody !== null && newFenceBody.trim()) {
      const bodyLines = newFenceBody.replace(/\r\n/g, NL).split(NL);
      lines.splice(f.openLine + 1, Math.max(0, f.closeLine - f.openLine - 1), ...bodyLines);
      wrote = true;
    }
    if (historyLine && !(window as any).__domvecPlantNoToolHistory) {
      // Avoid duplicating identical consecutive history line.
      let aboveIdx = f.openLine - 1;
      while (aboveIdx >= 0 && !lines[aboveIdx].trim()) aboveIdx--;
      if (aboveIdx < 0 || lines[aboveIdx].trim() !== historyLine.trim()) {
        lines.splice(f.openLine, 0, historyLine, "");
        toolCellStats.history_written++;
        wrote = true;
      }
    }
    return lines.join(NL);
  });
  return wrote;
}

/** Execute a ` ```tool ` fence when the user's cursor exits the fence (`G-453`). */
export async function executeToolFenceOnExit(
  app: App,
  host: ToolCellHost,
  file: TFile,
  fence: Fence,
): Promise<any> {
  if ((window as any).__domvecPlantNoToolPanel) return null;
  const base = host.sidecarBase().trim().replace(/[/]+$/, "");
  if (!base) return null;
  const session = `${file.path}#tool`;
  let res: any = null;
  try {
    const r = await fetch(base + "/tool_cell", {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Domvec-Client": "obsidian-plugin" },
      body: JSON.stringify({ session, source: fence.body }),
    });
    res = await r.json();
  } catch {
    return null;
  }
  if (!res || !res.ok || res.mode === "app_tool" || res.mode === "root") return res;
  toolCellStats.exit_runs++;
  toolCellStats.calls++;
  toolCellStats.last_tool = String(res.tool || "");
  for (const a of res.asks || []) await host.carryAsk(a);
  await writeToolStepToNote(app, file, fence.openLine, res.fence || null, res.history_line || null);
  return res;
}

/** Markdown code-block processor for ` ```tool ` (`G-421` + `G-453`). */
export function toolBlockProcessor(app: App, host: ToolCellHost) {
  return async (src: string, el: HTMLElement, ctx: MarkdownPostProcessorContext) => {
    if ((window as any).__domvecPlantNoToolPanel) {
      el.createEl("pre", { text: src });
      return;
    }
    toolCellStats.rendered++;
    const base = host.sidecarBase().trim().replace(/[/]+$/, "");
    const info = ctx.getSectionInfo(el);
    const openLine = info?.lineStart ?? -1;
    const session = `${ctx.sourcePath || "note"}#tool`;

    const paint = async (payload: { source?: string; call?: any }) => {
      el.empty();
      let res: any = null;
      try {
        const r = await fetch(base + "/tool_cell", {
          method: "POST",
          headers: { "Content-Type": "application/json", "X-Domvec-Client": "obsidian-plugin" },
          body: JSON.stringify({ session, ...payload }),
        });
        res = await r.json();
      } catch {
        res = null;
      }

      // Fallback to GET /tool_panel if /tool_cell unreachable and bare app-tool name given (`G-421`).
      const bareName = src.trim().split(/\s+/)[0] || "";
      if ((!res || !res.ok) && bareName && !bareName.startsWith("{")) {
        let text = "";
        try {
          const j = await (await fetch(base + "/tool_panel")).json();
          text = (j.panels || {})[bareName] || "";
        } catch { /* sidecar down */ }
        const box = el.createDiv({ cls: "domvec-tool-panel" });
        box.createDiv({ cls: "domvec-tool-panel-head", text: "\u{1F512} " + bareName + " -- app tool, read-only" });
        box.createEl("pre", { text: text || "no app tool named " + bareName });
        return;
      }

      if (!res || !res.ok) {
        el.createDiv({ cls: "domvec-tool-panel", text: res?.error || "tool cell unavailable" });
        return;
      }

      // Mode 1: `G-421` read-only app-tool surface (`Database`, `WebBrowser`, `Vault`, etc.)
      if (res.mode === "app_tool") {
        const box = el.createDiv({ cls: "domvec-tool-panel" });
        box.createDiv({ cls: "domvec-tool-panel-head", text: "\u{1F512} " + res.tool + " -- app tool, read-only" });
        box.createEl("pre", { text: res.panel_text || ("no app tool named " + res.tool) });
        return;
      }

      // Mode 2 & 3: Interactive root / recursive toolspace cell (`G-453`)
      const card = el.createDiv({ cls: "domvec-tool-cell" });
      const bar = card.createDiv({ cls: "domvec-tool-bar" });
      const stack = res.stack || { index: 0, total: 0, can_back: false, can_forward: false };

      const backBtn = bar.createEl("button", { cls: "domvec-tool-nav is-back", text: "‹ back" });
      backBtn.disabled = !stack.can_back;
      const fwdBtn = bar.createEl("button", { cls: "domvec-tool-nav is-forward", text: "forward ›" });
      fwdBtn.disabled = !stack.can_forward;
      if (stack.total > 0) {
        bar.createSpan({ cls: "domvec-tool-step", text: `${stack.index}/${stack.total}` });
      }
      const badge = bar.createSpan({ cls: "domvec-tool-badge", text: `tool · ${res.tool || "root"}` });
      badge.title = "Interactive toolspace";

      const curTool = String(res.tool || "browser");
      const curArgs = { ...(res.args || {}) };

      const runInteractive = async (nextCall: any, recordNote = true) => {
        toolCellStats.calls++;
        const tName = Object.keys(nextCall)[0] || curTool;
        toolCellStats.last_tool = tName;
        if (nextCall[tName]?.back) toolCellStats.back_navs++;
        if (nextCall[tName]?.forward) toolCellStats.forward_navs++;
        if (nextCall[tName]?.chunks) toolCellStats.chunk_drills++;
        await paint({ call: nextCall });
      };

      backBtn.onclick = (e) => {
        e.preventDefault(); e.stopPropagation();
        void runInteractive({ [curTool]: { ...curArgs, back: true, forward: false } }, false);
      };
      fwdBtn.onclick = (e) => {
        e.preventDefault(); e.stopPropagation();
        void runInteractive({ [curTool]: { ...curArgs, back: false, forward: true } }, false);
      };

      if (res.mode === "call") {
        const chunksToggle = bar.createEl("button", {
          cls: "domvec-tool-chunks-toggle" + (curArgs.chunks ? " is-on" : ""),
          text: curArgs.chunks ? "chunks: on" : "chunks: off",
        });
        chunksToggle.onclick = (e) => {
          e.preventDefault(); e.stopPropagation();
          void runInteractive({ [curTool]: { ...curArgs, chunks: !curArgs.chunks, back: false, forward: false } });
        };
      }

      if (res.instructions) {
        card.createDiv({ cls: "domvec-tool-instructions", text: res.instructions });
      }

      // Controls row (`search` / `query` / `run` + browser `prev chunk` / `next chunk` / `click`)
      if (res.mode === "call") {
        const ctlRow = card.createDiv({ cls: "domvec-tool-controls" });
        const fieldKey = curTool === "search" ? "query" : curTool === "terminal" ? "run" : "search";
        const inp = ctlRow.createEl("input", {
          cls: "domvec-tool-input",
          attr: { type: "text", placeholder: `${curTool} ${fieldKey}…`, value: String(curArgs[fieldKey] || "") },
        });
        inp.addEventListener("keydown", (e) => {
          e.stopPropagation();
          if (e.key === "Enter") {
            e.preventDefault();
            void runInteractive({ [curTool]: { ...curArgs, [fieldKey]: inp.value, back: false, forward: false } });
          }
        });
        const goBtn = ctlRow.createEl("button", { cls: "domvec-tool-go", text: "call" });
        goBtn.onclick = (e) => {
          e.preventDefault(); e.stopPropagation();
          void runInteractive({ [curTool]: { ...curArgs, [fieldKey]: inp.value, back: false, forward: false } });
        };

        if (curTool === "browser") {
          const prevB = ctlRow.createEl("button", { cls: "domvec-tool-chunk-step is-prev", text: "‹ prev chunk" });
          const nextB = ctlRow.createEl("button", { cls: "domvec-tool-chunk-step is-next", text: "next chunk ›" });
          prevB.onclick = (e) => { e.preventDefault(); void runInteractive({ browser: { ...curArgs, prev_chunk: true, next_chunk: false } }); };
          nextB.onclick = (e) => { e.preventDefault(); void runInteractive({ browser: { ...curArgs, next_chunk: true, prev_chunk: false } }); };
        }
      }

      if (res.markdown) {
        card.createDiv({ cls: "domvec-tool-out", text: res.markdown });
      }

      const kids: any[] = res.children || [];
      if (kids.length) {
        const tree = card.createDiv({ cls: "domvec-tool-children" });
        for (const k of kids) {
          const item = tree.createEl("button", { cls: "domvec-tool-child", text: k.title || k.tool || "node" });
          if (k.instructions) item.title = k.instructions;
          item.onclick = (e) => {
            e.preventDefault(); e.stopPropagation();
            if (k.call) void runInteractive(k.call);
          };
        }
      }

      // Carry asks and persist history line when triggered by an interactive `payload.call`
      if (payload.call && res.mode === "call" && !res.navigated) {
        for (const a of res.asks || []) await host.carryAsk(a);
        const f = ctx.sourcePath ? app.vault.getAbstractFileByPath(ctx.sourcePath) : null;
        if (f instanceof TFile) {
          await writeToolStepToNote(app, f, openLine, res.fence || null, res.history_line || null);
        }
      }
    };

    // Drawing the cell PEEKS; only leaving the fence (or the call button) calls.
    await paint({ source: src, peek: !(window as any).__domvecPlantNoPeek } as any);
  };
}

/** Vanishing upward-scroll decoration on consecutive `> \`HH:MM:SS\`` tool-call history lines above ` ```tool ` (`G-453`). */
export function toolHistoryExtension(): Extension {
  const build = (view: EditorView): DecorationSet => {
    if ((window as any).__domvecPlantNoToolHistory) return Decoration.none;
    const b = new RangeSetBuilder<Decoration>();
    const doc = view.state.doc;
    const text = doc.toString();
    const toolFences = findFences(text).filter((f) => f.lang.toLowerCase() === "tool");
    for (const tf of toolFences) {
      let endLn = tf.openLine; // 0-based line before ```tool
      while (endLn > 0 && !doc.line(endLn).text.trim()) endLn--;
      let startLn = endLn;
      let count = 0;
      while (startLn >= 1) {
        const lt = doc.line(startLn).text.trim();
        if (/^>\s*`\d{2}:\d{2}:\d{2}`/.test(lt)) {
          count++;
          startLn--;
        } else if (!lt && startLn > 1 && /^>\s*`\d{2}:\d{2}:\d{2}`/.test(doc.line(startLn - 1).text.trim())) {
          startLn--;
        } else {
          break;
        }
      }
      startLn++;
      if (count >= 2 && startLn <= endLn) {
        for (let ln = startLn; ln <= endLn; ln++) {
          const isOld = ln < endLn - 1;
          const cls = "domvec-tool-history-line" + (isOld ? " is-vanished" : " is-latest") + (ln === startLn ? " is-first" : "");
          b.add(doc.line(ln).from, doc.line(ln).from, Decoration.line({ class: cls }));
        }
      }
    }
    return b.finish();
  };

  return ViewPlugin.fromClass(class {
    decorations: DecorationSet;
    constructor(view: EditorView) { this.decorations = build(view); }
    update(u: ViewUpdate) {
      if (u.docChanged || u.viewportChanged) this.decorations = build(u.view);
    }
  }, { decorations: (v) => v.decorations });
}
