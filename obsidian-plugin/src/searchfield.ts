/**
 * The naked search field on the 3D panel (PLUGIN_GOAL 84, 86, 87).
 *
 * 2026-10-11: "bring our retrieval bar as instead a middle-bottom field/panel
 * that is 'naked' meaning just showing the search box itself with maybe a
 * translucent "search" prompt"; "showing {k}/{n} results" beside it, k a field
 * the reader edits; and "a horizontal scroll bar ... below the user search
 * input ... It begins at the very left ... as the user scrolls horizontally,
 * that governs how many chunks in the top-k results are actually visible".
 *
 * The field owns its DOM and nothing else. What a query returns and what the
 * scroll position means for the scene are told to the graph view through two
 * callbacks; the two rules that turn a scroll into a picture are pure
 * functions below, so a test can hold them without a DOM.
 */

/** How many of the top-k results are shown at a scroll fraction 0..1: the
 *  very left shows the first result, the very right all k. */
export function visibleCount(frac: number, k: number): number {
  if (!(k > 0)) return 0;
  const f = Math.min(1, Math.max(0, Number.isFinite(frac) ? frac : 0));
  return Math.max(1, Math.min(k, Math.round(1 + f * (k - 1))));
}

/**
 * A shown result's brightness, 0..1, from its rank (0-based) and the number
 * shown `d` (item 88: "The closer to the user's scrolled delta index, the
 * brighter"). The scrolled index is the last one shown, `d - 1`: it is 1, and
 * the brightness falls linearly with distance from it to 0.2 at the far end.
 * A result not shown is 0.
 */
export function brightness(rank: number, d: number): number {
  if (!(rank >= 0) || rank >= d) return 0;
  if (d <= 1) return 1;
  return 1 - 0.8 * Math.abs(d - 1 - rank) / (d - 1);
}

export interface FieldHit { cid: string; url: string }
export interface FieldAnswer { hits: FieldHit[]; n: number }

export class SearchField {
  readonly el: HTMLElement;
  readonly input: HTMLInputElement;
  readonly kInput: HTMLInputElement;
  private nEl: HTMLElement;
  private count: HTMLElement;
  readonly scroller: HTMLElement;
  private track: HTMLElement;
  private debounce = 0;
  private seq = 0;
  /** The current query, its answer, and how many are shown. */
  query = "";
  k = 20;
  n = 0;
  hits: FieldHit[] = [];
  shown = 0;
  stats = { queries: 0, answered: 0, lastMs: 0 };

  private ask: (query: string, k: number) => Promise<FieldAnswer | null>;
  private onShow: (hits: FieldHit[], shown: number) => void;
  private onClear: () => void;

  constructor(host: HTMLElement,
              ask: (query: string, k: number) => Promise<FieldAnswer | null>,
              onShow: (hits: FieldHit[], shown: number) => void,
              onClear: () => void) {
    this.ask = ask; this.onShow = onShow; this.onClear = onClear;
    this.el = host.createDiv({ cls: "domvec-search3d" });
    const row = this.el.createDiv({ cls: "domvec-search3d-row" });
    this.input = row.createEl("input", { cls: "domvec-search3d-input" });
    this.input.type = "text";
    this.input.placeholder = "search";
    this.input.spellcheck = false;
    this.count = row.createDiv({ cls: "domvec-search3d-count" });
    this.count.createSpan({ text: "showing " });
    this.kInput = this.count.createEl("input", { cls: "domvec-search3d-k" });
    this.kInput.type = "number";
    this.kInput.min = "1";
    this.kInput.step = "1";
    this.kInput.value = String(this.k);
    this.count.createSpan({ text: "/" });
    this.nEl = this.count.createSpan({ text: "0" });
    this.count.createSpan({ text: " results" });
    this.scroller = this.el.createDiv({ cls: "domvec-search3d-scroll" });
    this.track = this.scroller.createDiv({ cls: "domvec-search3d-track" });
    this.paint();

    this.input.addEventListener("input", () => {
      window.clearTimeout(this.debounce);
      this.debounce = window.setTimeout(() => { void this.run(); }, 250);
    });
    this.input.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { this.input.value = ""; void this.run(); }
      else if (e.key === "Enter") { window.clearTimeout(this.debounce); void this.run(); }
    });
    this.kInput.addEventListener("change", () => {
      const v = Math.floor(Number(this.kInput.value));
      this.setK(Number.isFinite(v) && v >= 1 ? v : this.k);
    });
    this.scroller.addEventListener("scroll", () => this.onScroll(), { passive: true });
  }

  /** k from the field: a new top-k asks again, from the very left. */
  setK(k: number): void {
    this.k = Math.max(1, Math.min(500, Math.floor(k)));
    this.kInput.value = String(this.k);
    void this.run();
  }

  async run(): Promise<void> {
    const q = this.input.value.trim();
    const seq = ++this.seq;
    this.query = q;
    if (!q) {
      this.hits = []; this.n = 0; this.shown = 0;
      this.paint();
      this.onClear();
      return;
    }
    this.stats.queries++;
    const t0 = performance.now();
    const got = await this.ask(q, this.k);
    if (seq !== this.seq) return;                 // a newer query is in flight
    this.stats.lastMs = Math.round(performance.now() - t0);
    if (!got) return;
    this.stats.answered++;
    this.hits = got.hits.slice(0, this.k);
    this.n = Math.max(got.n || 0, this.hits.length);
    this.scroller.scrollLeft = 0;                 // it begins at the very left
    this.paint();
    this.onScroll(true);
  }

  /** Merge results that arrived later (a second source) without moving the scroll. */
  extend(more: FieldHit[], n: number): void {
    const have = new Set(this.hits.map((h) => h.cid));
    for (const h of more) if (!have.has(h.cid) && this.hits.length < this.k) { this.hits.push(h); have.add(h.cid); }
    this.n = Math.max(this.n, n, this.hits.length);
    this.paint();
    this.onScroll(true);
  }

  private onScroll(force = false): void {
    const span = this.scroller.scrollWidth - this.scroller.clientWidth;
    const frac = span > 0 ? this.scroller.scrollLeft / span : 0;
    const shown = visibleCount(frac, this.hits.length);
    if (!force && shown === this.shown) return;
    this.shown = shown;
    this.onShow(this.hits, shown);
  }

  private paint(): void {
    const active = this.hits.length > 0;
    this.el.toggleClass("is-active", active);
    this.nEl.setText(String(this.n));
    // k as asked, but never more than there are ("showing 12/11", 2026-10-11).
    if (document.activeElement !== this.kInput) this.kInput.value = String(active ? Math.min(this.k, Math.max(this.n, this.hits.length)) : this.k);
    // One step of scroll per result, so a flick is a few results, not all.
    const w = this.scroller.clientWidth || 320;
    this.track.style.width = `${Math.round(w + Math.max(0, this.hits.length - 1) * 28)}px`;
  }
}
