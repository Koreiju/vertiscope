/**
 * The chat INPUT CELL (2026-11-24: "the 'chat' bar that hovered on panels
 * should be replaced with a formal 'chat input' cell as a canvas that then
 * streams the chat output inline in the same obsidian panel").
 *
 * A ```chat block in any note draws an input. Enter streams the reply into the
 * cell as the model writes it; when it ends, the turn -- the prompt quoted,
 * then the reply -- is written into the note ABOVE the block, so the
 * conversation is the note's own markdown and the input stays at its foot.
 * The context is the note above the block: whatever is pinned, written or
 * answered there, nothing chosen elsewhere.
 *
 * In trie terms: the cell reads its vault:// page above the fence and writes
 * one section into it per turn; nothing reaches the model except through the
 * note. Planted `__domvecPlantChatStrip`: no cell (the block stays raw) and the
 * browser cell's hover strip returns.
 */
import type { App, MarkdownPostProcessorContext, TFile } from "obsidian";

const NL = String.fromCharCode(10);
/** Context sent with a turn, from the foot of the note above the cell. */
const CONTEXT_CHARS = 8000;

export const chatCellStats = { turns: 0, last: null as null | { prompt: string; context_chars: number; tokens: number; ms: number; written: boolean } };
(window as any).__domvecChatCell = chatCellStats;

export function chatCell(app: App, stream: (prompt: string, ctx: string[], on: (t: string) => void) => Promise<string>) {
  return (src: string, el: HTMLElement, ctx: MarkdownPostProcessorContext) => {
    if ((window as any).__domvecPlantChatStrip) { el.createEl("pre", { text: src }); return; }
    const box = el.createDiv({ cls: "domvec-chat-cell" });
    const out = box.createDiv({ cls: "domvec-chat-cell-out" });
    const input = box.createEl("textarea", { cls: "domvec-chat-cell-input" });
    input.rows = 2;
    input.placeholder = "Ask about this note -- Enter sends, Shift+Enter for a new line";
    let busy = false;
    input.addEventListener("keydown", async (e: KeyboardEvent) => {
      if (e.key !== "Enter" || e.shiftKey) return;
      e.preventDefault(); e.stopPropagation();
      const prompt = input.value.trim();
      if (!prompt || busy) return;
      busy = true; input.disabled = true; out.setText("");
      const f = app.vault.getAbstractFileByPath(ctx.sourcePath) as TFile | null;
      const info = ctx.getSectionInfo(el);
      const text = f ? await app.vault.read(f) : "";
      const above = info ? text.split(NL).slice(0, info.lineStart).join(NL) : text;
      const context = above.trim() ? [above.slice(-CONTEXT_CHARS)] : [];
      const t0 = performance.now(); let tokens = 0, reply = "";
      try {
        reply = await stream(prompt, context, (t) => { tokens++; out.appendText(t); });
      } catch (err) { reply = "*the chat did not answer: " + String((err as Error).message || err) + "*"; out.setText(reply); }
      // The turn into the note, above the cell: it stays at the foot.
      let written = false;
      if (f) {
        const turn = "> **You** " + prompt.split(NL).join(NL + "> ") + NL + NL + reply.trim() + NL + NL;
        await app.vault.process(f, (t) => {
          const lines = t.split(NL);
          const at = info && lines[info.lineStart] !== undefined && lines[info.lineStart].trim().startsWith("```") ? info.lineStart
            : lines.findIndex((l) => /^```chat\s*$/.test(l.trim()));
          if (at < 0) return t;
          written = true;
          return [...lines.slice(0, at), turn + lines.slice(at).join(NL)].join(NL);
        });
      }
      chatCellStats.turns++;
      chatCellStats.last = { prompt, context_chars: context.join("").length, tokens, ms: Math.round(performance.now() - t0), written };
      busy = false; input.disabled = false; input.value = "";
    });
  };
}
