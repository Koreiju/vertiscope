/**
 * The `[]()` gesture (`R-1`..`R-4`), in the reader's words: *"when the sequence
 * of four `[]()` symbols are typed, the entry in the square brackets acts as a
 * semantic retrieval feature, and the results are shown in some new
 * filled/scrollable whitespace immediately below the line such that the
 * remainder of the markdown panel editable lines are uninterrupted in
 * rendering as a cohesive unit. Once a scrolled result is clicked, the link is
 * infilled between the empty parentheses."*
 *
 * The design note (PLUGIN_GOAL, "trigger yes, layout no") settled the shape
 * before this was built: `EditorSuggest` has the right trigger but renders a
 * floating container that COVERS the lines below; a CodeMirror 6 **block
 * widget** is inserted into the document's flow, so the editor reflows around
 * it and every line below moves down by its height. Block decorations must
 * come from a state field (CM6 refuses them from a view plugin), so:
 *
 *   - `field` holds where the gesture is -- the line it sits under and the
 *     empty `()` to infill -- mapped through every edit;
 *   - a view plugin watches the cursor and opens or closes the gesture;
 *   - the widget's DOM is owned by a `Results` controller that survives
 *     re-decoration (its `eq` is identity), so results that arrive or are
 *     scrolled in are appended in place and the reader's scroll is kept.
 *
 * Retrieval is the workspace's one ranked list (`/search`, `G-69`'s offset
 * paging as the list nears its bottom): web pages, vault notes and source
 * files alike (`R-5`) -- this gesture adds no second index.
 *
 * Planted `plantOverlay`: the results are drawn as a floating overlay, the
 * `EditorSuggest` shape the design note rejected -- the live check must see
 * the line below NOT move and the results cover it.
 */
import { Extension, StateEffect, StateField, EditorState } from "@codemirror/state";
import {
  Decoration, DecorationSet, EditorView, ViewPlugin, ViewUpdate, WidgetType, keymap,
} from "@codemirror/view";

import { gestureIn } from "./gesture";
import { Sidecar } from "./sidecar";
import { SearchHit } from "./types";

export interface Gesture {
  /** Where `()`'s inside is: the link goes here. */
  at: number;
  query: string;
}

/** Where the cursor makes a gesture, if it does. */
export function gestureAt(state: EditorState): Gesture | null {
  const sel = state.selection.main;
  if (!sel.empty) return null;
  const line = state.doc.lineAt(sel.head);
  const got = gestureIn(line.text, sel.head - line.from);
  return got ? { at: line.from + got.ch, query: got.query } : null;
}

interface Open {
  at: number;
  query: string;
  results: Results;
}

const setGesture = StateEffect.define<Open | null>();

export interface GestureStats {
  opened: number;
  pages: number;
  infilled: number;
  last: any;
}

export interface GestureHost {
  sidecar: Sidecar;
  /** Where a hit's link points: its note in the vault when the page has one. */
  destination(hit: SearchHit): string;
  stats: GestureStats;
  plantOverlay: boolean;
  /** A gesture opened: a moment to learn which pages have notes. */
  onOpen?: () => void;
}

/** The results under one gesture: the DOM, the pages fetched so far, more on scroll. */
class Results {
  readonly dom: HTMLElement;
  private list: HTMLElement;
  private head: HTMLElement;
  private hits: SearchHit[] = [];
  private loading = false;
  private done = false;
  private token = 0;
  /** Where the server's ranked list resumes (its own count, not ours). */
  private offset = 0;
  private wanted = false;
  private static PAGE = 10;

  constructor(private host: GestureHost, private view: EditorView, readonly query: string,
              private infill: (hit: SearchHit) => void, overlay: boolean) {
    this.dom = document.createElement("div");
    this.dom.className = "vertiscope-linkgesture" + (overlay ? " vertiscope-linkgesture-overlay" : "");
    this.dom.setAttribute("contenteditable", "false");
    this.head = this.dom.createDiv({ cls: "vertiscope-lg-head", text: `retrieving “${query}”…` });
    this.list = this.dom.createDiv({ cls: "vertiscope-lg-list" });
    // The editor must not take a click in here for a cursor move.
    this.dom.addEventListener("mousedown", (e) => e.preventDefault());
    this.list.addEventListener("scroll", () => {
      if (this.list.scrollTop + this.list.clientHeight > this.list.scrollHeight - 40) void this.more();
    });
    void this.more();
  }

  get count(): number { return this.hits.length; }

  async more(): Promise<void> {
    if (this.done) return;
    // A scroll while a page is on its way is a request, not noise: it is
    // answered when that page lands. Dropped, the list sat at its first page
    // whenever the sidecar was slow (20 s+ after a plugin reload, live).
    if (this.loading) { this.wanted = true; return; }
    this.wanted = false;
    this.loading = true;
    const mine = ++this.token;
    const got = await this.host.sidecar.search(this.query, { k: Results.PAGE, offset: this.offset });
    this.loading = false;
    if (mine !== this.token) return;
    // The end of the list is the SERVER's word (`more`), never a page that did
    // not arrive: a search that timed out read as "no more", and the list
    // stopped at its first page (live, 2026-10-11).
    if (!got) { this.head.setText(`the sidecar did not answer -- scroll to ask again`); return; }
    this.offset += got.hits.length;
    if (!got.hits.length || got.more === false) this.done = true;
    const fresh = got.hits.filter((h) => !this.hits.some((x) => x.cid === h.cid));
    this.host.stats.pages++;
    for (const hit of fresh) this.row(hit);
    this.hits.push(...fresh);
    this.head.setText(this.hits.length
      ? `${this.hits.length}${this.done ? "" : "+"} for “${this.query}” · click one to link it`
      : `nothing for “${this.query}”`);
    this.view.requestMeasure();
    // Scrolling is how the reader asks for more, so the list has to be able
    // to scroll: fill it past its own height first.
    if (!this.done && ((this.dom.isConnected && this.list.scrollHeight <= this.list.clientHeight) || this.wanted)) void this.more();
  }

  private row(hit: SearchHit): void {
    const el = this.list.createDiv({ cls: "vertiscope-lg-hit" });
    el.dataset.cid = hit.cid;
    const first = (hit.preview || "").split("\n").find((l) => l.trim()) || hit.url;
    el.createDiv({ cls: "vertiscope-lg-title", text: first.slice(0, 120) });
    el.createDiv({ cls: "vertiscope-lg-sub", text: `${where(hit.url)} · ${hit.score.toFixed(3)}` });
    el.addEventListener("click", () => this.infill(hit));
  }
}

class ResultsWidget extends WidgetType {
  constructor(readonly results: Results) { super(); }
  eq(other: ResultsWidget): boolean { return other.results === this.results; }
  toDOM(): HTMLElement { return this.results.dom; }
  ignoreEvent(): boolean { return true; }
}

function where(url: string): string {
  if (url.startsWith("vault://")) return "vault · " + decodeURIComponent(url.replace(/^vault:\/\/[^/]*\//, ""));
  if (url.startsWith("code://")) return "code · " + url.slice(7);
  try { return new URL(url).host; } catch { return url; }
}

export function linkGesture(host: GestureHost): Extension {
  const field = StateField.define<Open | null>({
    create: () => null,
    update(open, tr) {
      for (const e of tr.effects) if (e.is(setGesture)) return e.value;
      if (open && tr.docChanged) return { ...open, at: tr.changes.mapPos(open.at) };
      return open;
    },
  });

  // Computed from the STATE (a block may not come from a view plugin), with
  // the document in hand to place the block at the end of the gesture's line.
  const blocks = EditorView.decorations.compute([field], (state): DecorationSet => {
    const open = state.field(field);
    if (!open) return Decoration.none;
    const pos = Math.min(open.at, state.doc.length);
    const line = state.doc.lineAt(pos);
    if (host.plantOverlay) {
      return Decoration.set([Decoration.widget({ widget: new ResultsWidget(open.results), side: 1 }).range(line.to)]);
    }
    return Decoration.set([Decoration.widget({ widget: new ResultsWidget(open.results), block: true, side: 1 }).range(line.to)]);
  });

  /** Gestures the reader dismissed, by place and query, so Esc stays dismissed. */
  let dismissed = "";

  const watch = ViewPlugin.fromClass(class {
    private timer = 0;
    constructor(private view: EditorView) { this.check(); }
    update(u: ViewUpdate) { if (u.docChanged || u.selectionSet) this.check(); }
    destroy() { window.clearTimeout(this.timer); }

    private check() {
      window.clearTimeout(this.timer);
      // Typing settles before a query is asked: one search per pause, not
      // one per keypress.
      this.timer = window.setTimeout(() => this.settle(), 250);
    }

    private settle() {
      const view = this.view;
      const now = gestureAt(view.state);
      const open = view.state.field(field, false) ?? null;
      const key = now ? `${now.at}:${now.query}` : "";
      if (now && key === dismissed) return;
      if (now && open && open.query === now.query && open.at === now.at) return;
      if (!now && !open) return;
      if (!now) { view.dispatch({ effects: setGesture.of(null) }); return; }
      const infill = (hit: SearchHit) => {
        const cur = view.state.field(field, false);
        if (!cur) return;
        const dest = host.destination(hit);
        // Between the parentheses -- whatever the reader had typed there is
        // empty by construction (the gesture needs `()`).
        view.dispatch({ changes: { from: cur.at, to: cur.at, insert: dest }, effects: setGesture.of(null),
                        selection: { anchor: cur.at + dest.length + 1 } });
        host.stats.infilled++;
        host.stats.last = { query: cur.query, cid: hit.cid, dest };
        view.focus();
      };
      const results = new Results(host, view, now.query, infill, host.plantOverlay);
      host.stats.opened++;
      host.onOpen?.();
      host.stats.last = { query: now.query, at: now.at };
      view.dispatch({ effects: setGesture.of({ at: now.at, query: now.query, results }) });
    }
  });

  const esc = keymap.of([{
    key: "Escape",
    run: (view) => {
      const open = view.state.field(field, false);
      if (!open) return false;
      dismissed = `${open.at}:${open.query}`;
      view.dispatch({ effects: setGesture.of(null) });
      return true;
    },
  }]);

  return [field, blocks, watch, esc];
}
