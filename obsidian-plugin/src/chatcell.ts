/**
 * The chat INPUT CELL (2026-11-24, 2026-11-27 `G-444`, `G-452`, `G-453`):
 *
 * A ```chat block in any note draws a collapsible system-prompt bar (defaulting
 * to `domvec/ego.md`'s `## System prompt`, editable per cell) and a prompt
 * input. Enter streams the reply into the cell as the model writes it; when it
 * ends, the turn -- the prompt quoted, then the reply -- is written into the
 * note ABOVE the block, so the conversation is the note's own markdown and the
 * input stays at its foot. Emitted ```tool blocks in replies execute in-place
 * (`G-453`), and `Chat.send(prompt, note=...)` from Python kernels streams
 * live into the target note (`streamPromptIntoNote`, `G-452`).
 *
 * In trie terms: the cell reads its `vault://` page above the fence (plus
 * `domvec/ego.md`'s system prompt) and writes one section into it per turn;
 * nothing reaches the model except through the note. Planted
 * `__domvecPlantChatStrip`: no cell (the block stays raw) and the browser
 * cell's hover strip returns.
 */
import { closeOpenFence } from "./streamtext";
import type { App, MarkdownPostProcessorContext, TFile } from "obsidian";
import { EditorView } from "@codemirror/view";
import { DEFAULT_EGO_SYSTEM_PROMPT } from "./cockpit";

const NL = String.fromCharCode(10);
/** Context sent with a turn, from the foot of the note above the cell. */
const CONTEXT_CHARS = 8000;

export interface ChatStreamMeta {
  session?: string;
  pins?: { cid: string; url: string; title?: string; markdown: string }[];
  history?: { user: string; assistant: string }[];
  system?: string;
}

export interface ChatCellHost {
  pins?: (path: string) => { cid: string; url: string; title?: string; markdown: string }[];
  extra?: (path: string) => Promise<string[]>;
  systemPrompt?: () => string;
  onToolReply?: (path: string, reply: string) => Promise<void>;
  markdownViews?: () => any[];
}

export const chatCellStats = {
  turns: 0,
  stopped: 0,
  programmatic: 0,
  tool_replies: 0,
  last: null as null | {
    prompt: string;
    context_chars: number;
    history_turns?: number;
    pins?: number;
    system_chars?: number;
    tokens: number;
    ms: number;
    written: boolean;
  },
};
(window as any).__domvecChatCell = chatCellStats;

/** Parse optional `system:` override inside a ```chat fence body (`G-452`). */
export function parseChatFenceSystem(src: string): string {
  const trimmed = String(src || "").trim();
  if (!trimmed) return "";
  const m = /^system:\s*([\s\S]*)$/i.exec(trimmed);
  return (m ? m[1] : trimmed).trim();
}

/** Extract ```tool blocks emitted in an assistant reply (`G-453`). */
export function extractReplyToolBodies(reply: string): string[] {
  const out: string[] = [];
  const re = /`{3,}tool[ \t]*\r?\n([\s\S]*?)`{3,}/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(reply || "")) !== null) {
    const body = (m[1] || "").trim();
    if (body) out.push(body);
  }
  return out;
}

/** Split markdown above a ```chat fence into base cells/prose and prior `> **You**` turns (G-444). */
export function splitInlineTurns(above: string): { base: string; history: { user: string; assistant: string }[] } {
  const lines = above.split(/\r?\n/);
  const baseLines: string[] = [];
  const history: { user: string; assistant: string }[] = [];
  let i = 0;
  while (i < lines.length) {
    if (lines[i].startsWith("> **You** ")) {
      const uLines = [lines[i].slice("> **You** ".length)];
      i++;
      while (i < lines.length && lines[i].startsWith(">")) {
        uLines.push(lines[i].replace(/^>\s?/, ""));
        i++;
      }
      while (i < lines.length && !lines[i].trim()) i++;
      const aLines: string[] = [];
      let inFence = false;
      while (i < lines.length) {
        if (!inFence && lines[i].startsWith("> **You** ")) break;
        if (/^\s*(`{3,}|~{3,})/.test(lines[i])) inFence = !inFence;
        aLines.push(lines[i]);
        i++;
      }
      const u = uLines.join(NL).trim(), a = aLines.join(NL).trim();
      if (u && a) history.push({ user: u, assistant: a });
      continue;
    }
    baseLines.push(lines[i]);
    i++;
  }
  return { base: baseLines.join(NL).trim(), history };
}

async function persistChatSystemToNote(
  app: App,
  file: TFile | null,
  lineStart: number | undefined,
  customSys: string,
): Promise<void> {
  if (!file) return;
  const F = "`".repeat(3);
  await app.vault.process(file, (t) => {
    const lines = t.split(NL);
    let open = lineStart !== undefined && lines[lineStart]?.trim().startsWith(F + "chat") ? lineStart : -1;
    if (open < 0) open = lines.findIndex((l) => /^```chat\b/.test(l.trim()));
    if (open < 0) return t;
    let close = open + 1;
    while (close < lines.length && !lines[close].trim().startsWith(F)) close++;
    if (close >= lines.length) return t;
    const body = customSys.trim() ? [`system: ${customSys.trim()}`] : [];
    return [...lines.slice(0, open + 1), ...body, ...lines.slice(close)].join(NL);
  });
}

export function chatCell(
  app: App,
  stream: (prompt: string, ctx: string[], on: (t: string) => void, signal?: AbortSignal, meta?: ChatStreamMeta) => Promise<string>,
  hostCtx?: ChatCellHost,
) {
  return (src: string, el: HTMLElement, ctx: MarkdownPostProcessorContext) => {
    if ((window as any).__domvecPlantChatStrip) { el.createEl("pre", { text: src }); return; }
    const box = el.createDiv({ cls: "domvec-chat-cell" });
    box.dataset.path = ctx.sourcePath || "";

    const egoDefault = () => (hostCtx?.systemPrompt ? hostCtx.systemPrompt() : DEFAULT_EGO_SYSTEM_PROMPT) || DEFAULT_EGO_SYSTEM_PROMPT;
    let customSys = parseChatFenceSystem(src);
    let sysInput: HTMLTextAreaElement | null = null;
    let sysBadge: HTMLElement | null = null;

    const out = box.createDiv({ cls: "domvec-chat-cell-out" });
    const input = box.createEl("textarea", { cls: "domvec-chat-cell-input" });
    input.rows = 2;
    input.placeholder = "Ask about this note -- Enter sends, Shift+Enter for a new line";
    let busy = false, stopper: AbortController | null = null;
    const stop = box.createEl("button", { cls: "domvec-chat-stop", text: "■ stop" });
    stop.hide();
    stop.onclick = () => { stopper?.abort(); };

    // Placed after `input` in DOM order (with CSS `order: -1` so it renders at the top)
    // so `.domvec-chat-cell textarea` queries (`G-422`, `G-436`, `G-442`) always hit `input` first!
    if (!(window as any).__domvecPlantNoChatSysUI) {
      const sysWrap = box.createDiv({ cls: "domvec-chat-sys" });
      const sysBar = sysWrap.createDiv({ cls: "domvec-chat-sys-bar" });
      sysBadge = sysBar.createSpan({
        cls: "domvec-chat-sys-toggle",
        text: customSys ? "⚙ system prompt · custom" : "⚙ system prompt · ego default",
      });
      const resetBtn = sysBar.createEl("button", { cls: "domvec-chat-sys-reset", text: "use ego default" });
      if (!customSys) resetBtn.hide();
      const sysBody = sysWrap.createDiv({ cls: "domvec-chat-sys-body" });
      sysBody.hide();
      sysInput = sysBody.createEl("textarea", { cls: "domvec-chat-sys-input" });
      sysInput.rows = 4;
      sysInput.value = customSys || egoDefault();
      let open = false;
      sysBadge.onclick = () => {
        open = !open;
        if (open && !customSys && sysInput) sysInput.value = egoDefault();
        if (open) sysBody.show(); else sysBody.hide();
      };
      sysInput.addEventListener("change", () => {
        const val = (sysInput?.value || "").trim();
        const def = egoDefault().trim();
        customSys = val && val !== def ? val : "";
        if (sysBadge) sysBadge.setText(customSys ? "⚙ system prompt · custom" : "⚙ system prompt · ego default");
        if (customSys) resetBtn.show(); else resetBtn.hide();
        const f = app.vault.getAbstractFileByPath(ctx.sourcePath) as TFile | null;
        const info = ctx.getSectionInfo(el);
        void persistChatSystemToNote(app, f, info?.lineStart, customSys);
      });
      resetBtn.onclick = (ev) => {
        ev.preventDefault();
        ev.stopPropagation();
        customSys = "";
        if (sysInput) sysInput.value = egoDefault();
        if (sysBadge) sysBadge.setText("⚙ system prompt · ego default");
        resetBtn.hide();
        const f = app.vault.getAbstractFileByPath(ctx.sourcePath) as TFile | null;
        const info = ctx.getSectionInfo(el);
        void persistChatSystemToNote(app, f, info?.lineStart, "");
      };
    }
    input.addEventListener("keydown", async (e: KeyboardEvent) => {
      if (e.key !== "Enter" || e.shiftKey) return;
      e.preventDefault(); e.stopPropagation();
      const prompt = input.value.trim();
      if (!prompt || busy) return;
      busy = true; input.disabled = true; out.setText("");
      stopper = new AbortController();
      if (!(window as any).__domvecPlantNoStop) stop.show();
      const f = app.vault.getAbstractFileByPath(ctx.sourcePath) as TFile | null;
      const info = ctx.getSectionInfo(el);
      const text = f ? await app.vault.read(f) : "";
      const above = info ? text.split(NL).slice(0, info.lineStart).join(NL) : text;
      const { base, history } = splitInlineTurns(above);
      const extra = hostCtx?.extra ? await hostCtx.extra(ctx.sourcePath).catch(() => []) : [];
      const context = [...(base ? [base.slice(-CONTEXT_CHARS)] : []), ...extra];
      const pins = hostCtx?.pins ? hostCtx.pins(ctx.sourcePath) : [];
      const effectiveSystem = (sysInput && customSys ? sysInput.value.trim() : customSys) || egoDefault();
      const t0 = performance.now(); let tokens = 0, reply = "";
      const live = f ? noteStream(app, f, info?.lineStart, prompt, hostCtx) : null;
      try {
        reply = await stream(prompt, context, (t) => { tokens++; if (live) live.push(t); else out.appendText(t); }, stopper.signal,
          { session: ctx.sourcePath || "default", pins, history, ...(effectiveSystem ? { system: effectiveSystem } : {}) });
        if (stopper.signal.aborted) { reply = reply.trimEnd() + " *(stopped)*"; chatCellStats.stopped++; }
      } catch (err) { reply = "*the chat did not answer: " + String((err as Error).message || err) + "*"; if (!live) out.setText(reply); }
      let written = false;
      if (f && live) { await live.end(reply); written = true; }
      chatCellStats.turns++;
      if (written) {
        window.dispatchEvent(new CustomEvent("domvec-tool-view", { detail: { tool: "chat", url: ctx.sourcePath } }));
        if (hostCtx?.onToolReply && extractReplyToolBodies(reply).length) {
          chatCellStats.tool_replies++;
          await hostCtx.onToolReply(ctx.sourcePath, reply);
        }
      }
      chatCellStats.last = {
        prompt,
        context_chars: above.trim() ? above.slice(-CONTEXT_CHARS).length : context.join("").length,
        history_turns: history.length,
        pins: pins.length,
        system_chars: effectiveSystem.length,
        tokens,
        ms: Math.round(performance.now() - t0),
        written,
      };
      busy = false; input.disabled = false; input.value = ""; stop.hide(); stopper = null;
    });
  };
}

/** The ONE place a reply lives is the note (2026-11-28: "stream everything into
 *  the markdown cell"): the turn is written above the ```chat fence on the first
 *  token and rewritten as tokens arrive (at most every STREAM_MS), so a ``` block
 *  in the reply renders as its own cell while it streams. The cell's box keeps
 *  no copy. Planted `__domvecPlantStreamAppend`: each rewrite is appended
 *  instead of replacing the stream's previous state -- the reply lands twice. */
const STREAM_MS = 150;
export const chatStreamStats = { writes: 0, turns: 0 };
(window as any).__domvecChatStream = chatStreamStats;
function noteStream(app: App, f: TFile, hintLine: number | undefined, prompt: string, hostCtx?: ChatCellHost) {
  const head = "> **You** " + prompt.split(NL).join(NL + "> ") + NL + NL;
  const turnOf = (said: string) => head + said.trim() + NL + NL;
  let acc = "", prev = "", timer = 0, chain: Promise<unknown> = Promise.resolve();
  const box = () => Array.from(document.querySelectorAll(`.domvec-chat-cell[data-path="${CSS.escape(f.path)}"] .domvec-chat-cell-out`)) as HTMLElement[];
  const flush = (said: string) => {
    const turn = turnOf(said), was = (window as any).__domvecPlantStreamAppend ? "" : prev; prev = turn;
    chain = chain.then(() => writeTurnAboveChatFence(app, f, hintLine, turn, hostCtx?.markdownViews, was)).then(() => { chatStreamStats.writes++; });
    return chain;
  };
  for (const b of box()) b.setText("");
  return {
    push(tok: string) {
      acc += tok;
      if (!timer) timer = window.setTimeout(() => { timer = 0; void flush(closeOpenFence(acc) + " …"); }, prev ? STREAM_MS : 0);
    },
    async end(reply: string): Promise<boolean> {
      if (timer) { window.clearTimeout(timer); timer = 0; }
      await chain;
      const said = (window as any).__domvecPlantReplyFlat ? reply.split("`".repeat(3)).join("'".repeat(3)) : reply;
      await flush(said);
      chatStreamStats.turns++;
      return true;
    },
  };
}

async function writeTurnAboveChatFence(
  app: App,
  f: TFile,
  hintLine: number | undefined,
  turn: string,
  markdownViews?: () => any[],
  prev = "",
): Promise<boolean> {
  const F = "`".repeat(3);
  const patch = (t: string): { next: string; ok: boolean } => {
    const lines = t.split(NL);
    // The fence moves down as the turn grows: find it again rather than trust the hint.
    let at = hintLine !== undefined && lines[hintLine] !== undefined && lines[hintLine].trim().startsWith(F + "chat") && !prev
      ? hintLine
      : lines.findIndex((l) => /^```chat\b/.test(l.trim()));
    if (at < 0) return { next: t, ok: false };
    let head = lines.slice(0, at).join(NL) + (at > 0 ? NL : "");
    const tail = lines.slice(at).join(NL);
    // A streamed turn replaces its own previous state, so it is in the note once.
    if (prev && head.endsWith(prev)) head = head.slice(0, head.length - prev.length);
    return { next: head + turn + tail, ok: true };
  };
  const openView = (markdownViews ? markdownViews() : app.workspace.getLeavesOfType("markdown").map((l) => l.view as any))
    .find((v: any) => v?.file?.path === f.path && v.getMode?.() === "source" && v.editor);
  if (openView?.editor) {
    const ed = openView.editor;
    const before = ed.getValue();
    const { next, ok } = patch(before);
    if (ok && next !== before) {
      let a = 0;
      while (a < before.length && a < next.length && before[a] === next[a]) a++;
      let b = 0;
      while (b < before.length - a && b < next.length - a && before[before.length - 1 - b] === next[next.length - 1 - b]) b++;
      ed.replaceRange(next.slice(a, next.length - b), ed.offsetToPos(a), ed.offsetToPos(before.length - b));
      if (typeof openView.save === "function") await openView.save();
      return true;
    }
  }
  let wrote = false;
  await app.vault.process(f, (t) => {
    const { next, ok } = patch(t);
    wrote = ok;
    return next;
  });
  return wrote;
}

/** Programmatically stream a prompt into `path`'s ```chat cell (`Chat.send` in Python, `G-452`). */
export async function streamPromptIntoNote(
  app: App,
  path: string,
  prompt: string,
  stream: (prompt: string, ctx: string[], on: (t: string) => void, signal?: AbortSignal, meta?: ChatStreamMeta) => Promise<string>,
  hostCtx?: ChatCellHost,
  systemOverride?: string,
): Promise<string> {
  const cleanPrompt = String(prompt || "").trim();
  if (!path || !cleanPrompt) return "";
  let f = app.vault.getAbstractFileByPath(path) as TFile | null;
  if (!f) {
    const slash = path.lastIndexOf("/");
    if (slash > 0 && !app.vault.getAbstractFileByPath(path.slice(0, slash))) {
      await app.vault.createFolder(path.slice(0, slash)).catch(() => undefined);
    }
    const base = path.split("/").pop()!.replace(/\.md$/i, "");
    f = await app.vault.create(path, `# ${base}${NL}${NL}\`\`\`chat${NL}\`\`\`${NL}`);
  } else {
    await ensureChatFence(app, null, path);
  }
  const text = await app.vault.read(f);
  const lines = text.split(NL);
  const openIdx = lines.findIndex((l) => /^```chat\b/.test(l.trim()));
  let closeIdx = openIdx >= 0 ? openIdx + 1 : -1;
  while (closeIdx >= 0 && closeIdx < lines.length && !lines[closeIdx].trim().startsWith("```")) closeIdx++;
  const fenceSrc = openIdx >= 0 && closeIdx > openIdx ? lines.slice(openIdx + 1, closeIdx).join(NL) : "";
  const above = openIdx >= 0 ? lines.slice(0, openIdx).join(NL) : text;
  const { base, history } = splitInlineTurns(above);
  const extra = hostCtx?.extra ? await hostCtx.extra(path).catch(() => []) : [];
  const context = [...(base ? [base.slice(-CONTEXT_CHARS)] : []), ...extra];
  const pins = hostCtx?.pins ? hostCtx.pins(path) : [];
  const egoSys = (hostCtx?.systemPrompt ? hostCtx.systemPrompt() : DEFAULT_EGO_SYSTEM_PROMPT) || DEFAULT_EGO_SYSTEM_PROMPT;
  const effectiveSystem = (systemOverride || "").trim() || parseChatFenceSystem(fenceSrc) || egoSys;

  const t0 = performance.now();
  let tokens = 0;
  let reply = "";
  const live = noteStream(app, f, openIdx >= 0 ? openIdx : undefined, cleanPrompt, hostCtx);
  try {
    reply = await stream(
      cleanPrompt,
      context,
      (tok) => { tokens++; live.push(tok); },
      undefined,
      { session: path, pins, history, ...(effectiveSystem ? { system: effectiveSystem } : {}) },
    );
  } catch (err) {
    reply = "*the chat did not answer: " + String((err as Error).message || err) + "*";
  }
  const written = await live.end(reply);
  chatCellStats.turns++;
  chatCellStats.programmatic++;
  if (written) {
    window.dispatchEvent(new CustomEvent("domvec-tool-view", { detail: { tool: "chat", url: path } }));
    if (hostCtx?.onToolReply && extractReplyToolBodies(reply).length) {
      chatCellStats.tool_replies++;
      await hostCtx.onToolReply(path, reply);
    }
  }
  chatCellStats.last = {
    prompt: cleanPrompt,
    context_chars: above.trim() ? above.slice(-CONTEXT_CHARS).length : context.join("").length,
    history_turns: history.length,
    pins: pins.length,
    system_chars: effectiveSystem.length,
    tokens,
    ms: Math.round(performance.now() - t0),
    written,
  };
  return reply;
}

/** Ensure `path` ends with a single ```chat cell, scroll it into view, and focus its input (G-424, G-443). */
export async function ensureChatFence(app: App, root: HTMLElement | null, path: string): Promise<boolean> {
  const f = app.vault.getAbstractFileByPath(path) as TFile | null;
  if (!f) return false;
  const has = (t: string) => new RegExp("(^|\n)" + "`".repeat(3) + "chat([ \t]*\r?\n|$)").test(t);
  const add = (t: string) => t.replace(/\s*$/, "") + NL + NL + "```chat" + NL + "```" + NL;
  const cmEl = root?.querySelector(".cm-editor") as HTMLElement | null;
  const cm = cmEl ? EditorView.findFromDOM(cmEl) : null;
  if (cm) {
    const t = cm.state.doc.toString();
    const keep = t.replace(/\s*$/, "").length;
    const ins = has(t) ? "" : add(t).slice(keep);
    cm.dispatch({ ...(ins ? { changes: { from: keep, to: t.length, insert: ins } } : {}),
                  effects: EditorView.scrollIntoView(ins ? keep + ins.length : t.length, { y: "end" }) });
    if (ins) {
      const mdView = app.workspace.getLeavesOfType("markdown")
        .map((l) => l.view as any)
        .find((v) => v?.file?.path === f.path && (!root || v.containerEl === root || root.contains(v.containerEl)));
      if (typeof mdView?.save === "function") await mdView.save();
      else await app.vault.modify(f, cm.state.doc.toString());
    }
  } else {
    await app.vault.process(f, (t) => has(t) ? t : add(t));
  }
  if (!root) return true;
  for (let i = 0; i < 40; i++) {
    const ta = root.querySelector(".domvec-chat-cell-input") as HTMLTextAreaElement | null;
    if (ta) { ta.scrollIntoView({ block: "nearest" }); ta.focus(); return true; }
    await new Promise((r) => setTimeout(r, 100));
  }
  return false;
}

/** G-424 superseded in placement by G-443 (2026-11-27): `+ chat` now lives in
 *  the standardized bottom cell bar (`cellbar.ts`). Planted
 *  `__domvecPlantCornerPlusChat` restores the corner badge. */
export function plusChat(app: App, card: HTMLElement, path: string): void {
  if (!(window as any).__domvecPlantCornerPlusChat || (window as any).__domvecPlantNoPlusChat || card.querySelector(":scope > .domvec-plus-chat")) return;
  const b = card.createDiv({ cls: "domvec-plus-chat", text: "+chat" });
  b.setAttr("aria-label", "add a chat cell to this note");
  b.addEventListener("mousedown", (e) => e.stopPropagation(), true);
  b.onclick = () => { void ensureChatFence(app, card, path); };
}
