/**
 * Unified vertical `[]()` retrieval UI (`R-1`..`R-5`, `G-454`; PLUGIN_GOAL 201 g).
 *
 * Matches the 3D `SearchField` (`searchfield.ts`) in representation and
 * controls -- `showing [k] / [n] results · X retrieved of Y matching`, web
 * `search` trigger, rank badges, `≈` similar-to-result pivot, soft scroll
 * brightness (`stripLight`), and live 3D graph hover fly-to / billboard preview
 * -- laid out as a vertically scrolled block widget inside the markdown editor.
 */
import { Extension, StateEffect, StateField, EditorState } from "@codemirror/state";
import {
  Decoration, DecorationSet, EditorView, ViewPlugin, ViewUpdate, WidgetType, keymap,
} from "@codemirror/view";

import { gestureIn } from "./gesture";
import { fieldBounds, softIndex, stripLight, visibleCount } from "./searchfield";
import { Sidecar } from "./sidecar";
import { SearchHit } from "./types";

export interface Gesture {
  at: number;
  query: string;
}

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
  hovers: number;
  similars: number;
  last: any;
}

export interface GestureHost {
  sidecar: Sidecar;
  destination(hit: SearchHit): string;
  stats: GestureStats;
  plantOverlay: boolean;
  onOpen?: () => void;
  onInfill?: () => void;
  onHoverHit?: (hit: SearchHit | null) => void;
  onRightHit?: (hit: SearchHit) => void;
  onWebSearch?: (query: string) => void;
}

class Results {
  readonly dom: HTMLElement;
  private list: HTMLElement;
  private head: HTMLElement;
  private kInput: HTMLInputElement;
  private nInput: HTMLInputElement;
  private matchEl: HTMLElement;
  private hits: SearchHit[] = [];
  private loading = false;
  private done = false;
  private token = 0;
  private offset = 0;
  private wanted = false;
  private k = 20;
  private total = 50;
  private matching = 0;
  private refCid = "";
  private activeQuery: string;
  private static PAGE = 12;

  constructor(
    private host: GestureHost,
    private view: EditorView,
    readonly query: string,
    private infill: (hit: SearchHit) => void,
    overlay: boolean,
  ) {
    this.activeQuery = query;
    this.dom = document.createElement("div");
    const legacy = !!(window as any).__domvecPlantUnunifiedRetrieval;
    this.dom.className = "domvec-linkgesture"
      + (overlay ? " domvec-linkgesture-overlay" : "")
      + (legacy ? "" : " domvec-search3d-vertical");
    this.dom.setAttribute("contenteditable", "false");

    this.head = this.dom.createDiv({ cls: "domvec-lg-head domvec-search3d-vbar" });
    const queryBadge = this.head.createSpan({ cls: "domvec-search3d-vquery", text: `“${query}”` });
    const webBtn = this.head.createEl("button", { cls: "domvec-search3d-go is-inline", text: "search" });
    webBtn.title = "search the web too";
    webBtn.addEventListener("click", (e) => {
      e.preventDefault(); e.stopPropagation();
      this.host.onWebSearch?.(this.activeQuery);
    });
    const countWrap = this.head.createSpan({ cls: "domvec-search3d-count" });
    const mkNum = (v: number, cls: string) => {
      const inp = countWrap.createEl("input", { cls: "domvec-search3d-k " + cls });
      inp.type = "number"; inp.min = "1"; inp.step = "1"; inp.value = String(v);
      inp.addEventListener("mousedown", (e) => e.stopPropagation());
      return inp;
    };
    countWrap.createSpan({ text: "showing " });
    this.kInput = mkNum(this.k, "is-k");
    countWrap.createSpan({ text: "/" });
    this.nInput = mkNum(this.total, "is-n");
    countWrap.createSpan({ text: " results" });
    this.matchEl = countWrap.createSpan({ cls: "domvec-search3d-match", text: "" });

    if (legacy) {
      countWrap.style.display = "none";
      webBtn.style.display = "none";
    }

    this.kInput.addEventListener("change", () => {
      const v = Math.max(1, Math.floor(Number(this.kInput.value) || this.k));
      this.k = v;
      if (this.k > this.total) this.total = this.k;
      this.updateLights();
    });
    this.nInput.addEventListener("change", () => {
      const v = Math.max(1, Math.floor(Number(this.nInput.value) || this.total));
      this.total = v;
      if (this.hits.length < this.total && !this.done) void this.more();
      this.updateLights();
    });

    this.list = this.dom.createDiv({ cls: "domvec-lg-list domvec-search3d-vstrip" });
    this.dom.addEventListener("mousedown", (e) => {
      if ((e.target as HTMLElement)?.tagName !== "INPUT") e.preventDefault();
    });
    this.list.addEventListener("scroll", () => {
      this.updateLights();
      if (this.list.scrollTop + this.list.clientHeight > this.list.scrollHeight - 48) void this.more();
    });
    this.list.addEventListener("mouseleave", () => this.host.onHoverHit?.(null));

    const pivotSimilar = (hit: SearchHit, title: string) => {
      this.refCid = hit.cid;
      this.activeQuery = `≈ ${title.slice(0, 48)}`;
      queryBadge.setText(this.activeQuery);
      this.hits = [];
      this.offset = 0;
      this.done = false;
      this.list.empty();
      this.host.stats.similars = (this.host.stats.similars || 0) + 1;
      void this.more();
    };
    (this as any)._pivotSimilar = pivotSimilar;

    void this.more();
  }

  get count(): number { return this.hits.length; }

  private updateLights(): void {
    if ((window as any).__domvecPlantUnunifiedRetrieval) return;
    const items = this.list.children;
    const winLen = Math.min(items.length, this.k);
    if (!winLen) return;
    const span = Math.max(0, this.list.scrollHeight - this.list.clientHeight);
    const frac = span > 0 ? this.list.scrollTop / span : 0;
    const shown = visibleCount(frac, winLen);
    const soft = softIndex(frac, winLen);
    for (let i = 0; i < items.length; i++) {
      const el = items[i] as HTMLElement;
      const light = i < winLen ? stripLight(i, shown, soft) : 0.16;
      el.style.opacity = String(Math.max(0.42, light));
      el.toggleClass("is-front", i === Math.max(0, Math.round(soft) - 1));
    }
    const { k, n } = fieldBounds(this.k, this.total, this.matching || this.hits.length);
    if (document.activeElement !== this.kInput) this.kInput.value = String(k);
    if (document.activeElement !== this.nInput) this.nInput.value = String(n);
    this.matchEl.setText(this.hits.length ? ` · ${this.hits.length} retrieved of ${Math.max(this.matching, this.hits.length)} matching` : "");
  }

  async more(): Promise<void> {
    if (this.done) return;
    if (this.loading) { this.wanted = true; return; }
    this.wanted = false;
    this.loading = true;
    const mine = ++this.token;
    const coarse = !!(globalThis as any).__domvecPlantGestureCoarse;
    const got: any = this.refCid
      ? await this.host.sidecar.similar(this.refCid, this.total)
      : await this.host.sidecar.search(this.query, { k: Results.PAGE, offset: this.offset, coarse });
    this.loading = false;
    if (mine !== this.token) return;
    if (!got || !Array.isArray(got.hits)) {
      this.matchEl.setText(" · sidecar did not answer");
      return;
    }
    if (this.refCid) this.done = true;
    this.offset += got.hits.length;
    if (typeof got.n === "number" && got.n > this.matching) this.matching = got.n;
    if (!got.hits.length || got.more === false || this.hits.length >= this.total) this.done = true;
    const fresh: SearchHit[] = got.hits.filter((h: SearchHit) => !this.hits.some((x) => x.cid === h.cid));
    this.host.stats.pages++;
    for (const hit of fresh) this.row(hit, this.hits.length + 1), this.hits.push(hit);
    this.updateLights();
    this.view.requestMeasure();
    if (!this.done && this.hits.length < this.total && ((this.dom.isConnected && this.list.scrollHeight <= this.list.clientHeight) || this.wanted)) {
      void this.more();
    }
  }

  private row(hit: SearchHit, rank1: number): void {
    const legacy = !!(window as any).__domvecPlantUnunifiedRetrieval;
    const el = this.list.createDiv({ cls: legacy ? "domvec-lg-hit" : "domvec-lg-hit domvec-search3d-item is-vertical" });
    el.dataset.cid = hit.cid;
    const first = ((hit.preview || "").split("\n").find((l) => l.trim()) || hit.url).replace(/^#+\s*/, "").trim();
    if (!legacy) {
      el.createSpan({ cls: "domvec-search3d-item-rank", text: String(rank1) });
    }
    const body = el.createDiv({ cls: "domvec-search3d-item-body" });
    body.createDiv({ cls: "domvec-lg-title domvec-search3d-item-label", text: first.slice(0, 120) });
    const scoreNum = typeof hit.score === "number" ? hit.score : 0;
    body.createDiv({ cls: "domvec-lg-sub", text: `${where(hit.url)} · ${scoreNum.toFixed(3)}` });
    if (!legacy) {
      const sim = el.createSpan({ cls: "domvec-search3d-item-similar", text: "≈" });
      sim.title = "similar to this result";
      sim.addEventListener("click", (e) => {
        e.preventDefault(); e.stopPropagation();
        (this as any)._pivotSimilar(hit, first);
      });
    }
    el.addEventListener("mouseenter", () => {
      this.host.stats.hovers = (this.host.stats.hovers || 0) + 1;
      this.host.onHoverHit?.(hit);
    });
    el.addEventListener("contextmenu", (e) => {
      if (!this.host.onRightHit) return;
      e.preventDefault(); e.stopPropagation();
      this.host.onRightHit(hit);
    });
    el.addEventListener("click", () => {
      this.host.onHoverHit?.(null);
      this.infill(hit);
    });
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

  let dismissed = "";

  const watch = ViewPlugin.fromClass(class {
    private timer = 0;
    constructor(private view: EditorView) { this.check(); }
    update(u: ViewUpdate) { if (u.docChanged || u.selectionSet) this.check(); }
    destroy() { window.clearTimeout(this.timer); }

    private check() {
      window.clearTimeout(this.timer);
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
      if (!now) { host.onHoverHit?.(null); view.dispatch({ effects: setGesture.of(null) }); return; }
      const infill = (hit: SearchHit) => {
        const cur = view.state.field(field, false);
        if (!cur) return;
        const dest = host.destination(hit);
        view.dispatch({
          changes: { from: cur.at, to: cur.at, insert: dest },
          effects: setGesture.of(null),
          selection: { anchor: cur.at + dest.length + 1 },
        });
        host.stats.infilled++;
        host.stats.last = { query: cur.query, cid: hit.cid, dest };
        view.focus();
        host.onInfill?.();
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
      host.onHoverHit?.(null);
      view.dispatch({ effects: setGesture.of(null) });
      return true;
    },
  }]);

  return [field, blocks, watch, esc];
}
