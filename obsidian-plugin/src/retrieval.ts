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
 *
 * And the passage's own links are rewritten into wikilinks wherever the page
 * they point at was exported -- see `VaultLinks`. Without that the passage
 * reads correctly and contributes nothing to the graph, which is exactly the
 * state the export was in before its first defect was found.
 */

import {
  App,
  Editor,
  EditorPosition,
  EditorSuggest,
  EditorSuggestContext,
  EditorSuggestTriggerInfo,
  Notice,
  TFile,
} from "obsidian";

import { Sidecar } from "./sidecar";
import { ChunkPayload, VertiscopeSettings, SearchHit } from "./types";
import { VaultLinks } from "./vaultlinks";

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
    private settings: () => VertiscopeSettings,
    private links: VaultLinks,
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
    const result = await this.sidecar.search(context.query, { k: limit });
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
    el.addClass("vertiscope-suggestion");
    if (item.kind === "all") {
      el.createDiv({
        cls: "vertiscope-suggestion-title",
        text: `Insert all ${item.hits.length} passages`,
      });
      el.createDiv({
        cls: "vertiscope-suggestion-sub",
        text: `for “${item.query}”`,
      });
      return;
    }
    const first = item.hit.preview.split("\n").find((l) => l.trim()) || "";
    el.createDiv({ cls: "vertiscope-suggestion-title", text: first.slice(0, 90) });
    el.createDiv({
      cls: "vertiscope-suggestion-sub",
      text: `${host(item.hit.url)} · ${item.hit.score.toFixed(3)}`,
    });
  }

  async selectSuggestion(item: Suggestion) {
    const context = this.context;
    if (!context) return;
    const hits = item.kind === "all" ? item.hits : [item.hit];

    // Which pages are in the vault, learned once per insertion. The vault
    // scan is the expensive half, and a note created between two hits of one
    // gesture is not a case worth a second pass for.
    await this.links.refresh();

    // Fetched one at a time rather than trusting the preview: the preview is
    // the first few lines and this is meant to inset the passage, not a
    // teaser of it.
    const blocks: string[] = [];
    let edges = 0;
    for (const hit of hits) {
      const payload = await this.sidecar.chunk(hit.cid);
      const raw = passage(hit, payload);
      const rewritten = this.links.rewrite(raw, hit.url);
      edges += rewritten.edges;
      blocks.push(rewritten.text);
    }

    const text = [`/${context.query}`, RULE, blocks.join(`\n${RULE}\n`), RULE]
      .join("\n") + "\n";
    context.editor.replaceRange(text, context.start, context.end);
    this.close();
    if (edges) {
      new Notice(`vertiscope: ${edges} link${edges === 1 ? "" : "s"} ` +
                 "became vault edges");
    }
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
 * the note keeps a way back to the page. It is written as ordinary link
 * markup like every other link in the body, so `VaultLinks.rewrite` picks it
 * up too: when the page it names was exported, the provenance line becomes an
 * edge rather than a footnote.
 */
function passage(hit: SearchHit, payload: ChunkPayload | null): string {
  const body = payload
    ? payload.lines.map((l) => l.text).filter((t) => t.trim()).join("\n")
    : hit.preview;
  const source = `\n— [${host(hit.url)}](${hit.url})`;
  return `${body}${source}`;
}
