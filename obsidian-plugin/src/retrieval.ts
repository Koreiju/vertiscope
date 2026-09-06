/**
 * The `/` gesture: retrieval interlaced with writing.
 *
 * Typing `/some query` on its own line offers the vault's own chunks, ranked
 * by the workspace's three-form retrieval, and drops the chosen passages
 * inline -- rules between them, the way a Kindle or Kobo sets an excerpt off
 * from the page around it.
 *
 * What it inserts is ordinary markdown. That is the whole point of doing this
 * through `EditorSuggest` rather than through a panel: the passage becomes
 * part of the note, the note is a file, and every link in it is a link
 * Obsidian's graph already understands. Retrieval that renders into a side
 * panel leaves nothing behind.
 */

import {
  App,
  Editor,
  EditorPosition,
  EditorSuggest,
  EditorSuggestContext,
  EditorSuggestTriggerInfo,
  TFile,
} from "obsidian";

import { Sidecar } from "./sidecar";
import { ChunkPayload, DomvecSettings, SearchHit } from "./types";

/**
 * `/` at the start of a line, then the query.
 *
 * Anchored to the line start so it cannot fire on a path or a date typed
 * mid-sentence. `onTrigger` runs on every keypress, so this is one regex and
 * an early return and nothing else.
 */
const GESTURE = /^\/(.+)$/;

/** The rule a Kindle puts between excerpts. */
const RULE = "____________________________________________";

type Suggestion =
  | { kind: "all"; query: string; hits: SearchHit[] }
  | { kind: "hit"; query: string; hit: SearchHit };

export class RetrievalSuggest extends EditorSuggest<Suggestion> {
  constructor(
    app: App,
    private sidecar: Sidecar,
    private settings: () => DomvecSettings,
  ) {
    super(app);
    this.setInstructions([
      { command: "↵", purpose: "insert passage" },
      { command: "esc", purpose: "dismiss" },
    ]);
  }

  onTrigger(
    cursor: EditorPosition,
    editor: Editor,
    _file: TFile | null,
  ): EditorSuggestTriggerInfo | null {
    const before = editor.getLine(cursor.line).slice(0, cursor.ch);
    const match = GESTURE.exec(before);
    if (!match) return null;
    // Two characters is not a query; firing on `/a` would search the whole
    // workspace on the way to every real one.
    if (match[1].trim().length < 3) return null;
    return {
      start: { line: cursor.line, ch: 0 },
      end: cursor,
      query: match[1].trim(),
    };
  }

  async getSuggestions(context: EditorSuggestContext): Promise<Suggestion[]> {
    const limit = this.settings().retrievalLimit;
    const result = await this.sidecar.search(context.query, limit);
    if (!result || !result.hits.length) return [];
    const hits = result.hits.slice(0, limit);
    // The "all" entry first, because the shape this gesture is for is a
    // sequence of passages with rules between them, not a single quote.
    return [
      { kind: "all", query: context.query, hits },
      ...hits.map((hit) => ({ kind: "hit" as const, query: context.query, hit })),
    ];
  }

  renderSuggestion(item: Suggestion, el: HTMLElement) {
    el.addClass("domvec-suggestion");
    if (item.kind === "all") {
      el.createDiv({
        cls: "domvec-suggestion-title",
        text: `Insert all ${item.hits.length} passages`,
      });
      el.createDiv({
        cls: "domvec-suggestion-sub",
        text: `for “${item.query}”`,
      });
      return;
    }
    const first = item.hit.preview.split("\n").find((l) => l.trim()) || "";
    el.createDiv({ cls: "domvec-suggestion-title", text: first.slice(0, 90) });
    el.createDiv({
      cls: "domvec-suggestion-sub",
      text: `${host(item.hit.url)} · ${item.hit.score.toFixed(3)}`,
    });
  }

  async selectSuggestion(item: Suggestion) {
    const context = this.context;
    if (!context) return;
    const hits = item.kind === "all" ? item.hits : [item.hit];

    // Fetched one at a time rather than trusting the preview: the preview is
    // the first few lines and this is meant to inset the passage, not a
    // teaser of it. The sidecar being unreachable mid-gesture is possible, so
    // a hit that will not load is skipped rather than inserted empty.
    const blocks: string[] = [];
    for (const hit of hits) {
      const payload = await this.sidecar.chunk(hit.cid);
      blocks.push(passage(hit, payload));
    }

    const text = [`/${context.query}`, RULE, blocks.join(`\n${RULE}\n`), RULE]
      .join("\n") + "\n";
    context.editor.replaceRange(text, context.start, context.end);
    this.close();
  }
}

function host(url: string): string {
  try {
    return new URL(url).host;
  } catch {
    return url;
  }
}

/**
 * One retrieved chunk as markdown a reader can keep.
 *
 * The source line is a real link, so the passage says where it came from and
 * the note keeps a way back to the page. Its own internal links are left
 * exactly as the distiller drew them: rewriting those into wikilinks is the
 * exporter's job, and it can only do it for pages that were exported, which
 * this gesture has no way to know.
 */
function passage(hit: SearchHit, payload: ChunkPayload | null): string {
  const body = payload
    ? payload.lines.map((l) => l.text).filter((t) => t.trim()).join("\n")
    : hit.preview;
  const source = `\n— [${host(hit.url)}](${hit.url})`;
  return `${body}${source}`;
}
