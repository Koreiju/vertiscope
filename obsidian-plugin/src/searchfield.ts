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

/** The scroll as a SOFT index, 1..k: continuous, so a result brightens in
 *  as the slider passes it rather than at an integer step (2026-10-11: "a
 *  soft brightness gradient to the scroll slider so that we can smoothly
 *  brighten on soft integer result nodes"). */
export function softIndex(frac: number, k: number): number {
  if (!(k > 0)) return 0;
  const f = Math.min(1, Math.max(0, Number.isFinite(frac) ? frac : 0));
  return 1 + f * (k - 1);
}

/** How many of the top-k results are shown at a scroll fraction 0..1: the
 *  very left shows the first result, the very right all k; the last of them
 *  may be part-way in (its `fade`). */
export function visibleCount(frac: number, k: number): number {
  if (!(k > 0)) return 0;
  return Math.max(1, Math.min(k, Math.ceil(softIndex(frac, k) - 1e-9)));
}

/** How far a result (0-based rank) has come in at soft index `s`, 0..1. */
export function fade(rank: number, s: number): number {
  return Math.min(1, Math.max(0, s - rank));
}

/**
 * A shown result's brightness, 0..1, from its rank (0-based) and the soft
 * index `s` (item 88: "The closer to the user's scrolled delta index, the
 * brighter"). The scrolled position is `s - 1`: a result there is 1, and the
 * brightness falls linearly with distance from it to 0.2 at the far end --
 * times how far the result has come in, so the frontier brightens smoothly.
 * At an integer `s` this is the integer rule exactly.
 */
export function brightness(rank: number, s: number): number {
  if (!(rank >= 0)) return 0;
  const f = fade(rank, s);
  if (f <= 0) return 0;
  const span = Math.max(s - 1, 1);
  return f * (1 - 0.8 * Math.min(1, Math.abs(s - 1 - rank) / span));
}

export interface FieldHit { cid: string; url: string }
export interface FieldAnswer { hits: FieldHit[]; n: number }

export class SearchField {
  readonly el: HTMLElement;
  readonly input: HTMLInputElement;
  readonly kInput: HTMLInputElement;
  /** n, the total results asked for: a field too (2026-10-11, item 97: "seems
   *  like youre thresholding on the number of total results. perhaps that
   *  could also be another user input field for total results"). */
  readonly nInput: HTMLInputElement;
  private matchEl: HTMLElement;
  private count: HTMLElement;
  readonly scroller: HTMLElement;
  private track: HTMLElement;
  private debounce = 0;
  private seq = 0;
  /** The current query and its answer. `total` (n) results are retrieved;
   *  the slider spans the top `k` of them. `matching` is the ranking's own
   *  count of chunks that match at all. */
  query = "";
  k = 20;
  total = 50;
  matching = 0;
  hits: FieldHit[] = [];
  shown = 0;
  /** The soft index the scroll stands at, 1..k. */
  soft = 0;
  private scrollRaf = 0;
  stats = { queries: 0, answered: 0, lastMs: 0 };

  private ask: (query: string, total: number) => Promise<FieldAnswer | null>;
  private onShow: (hits: FieldHit[], shown: number, soft: number) => void;
  private onClear: () => void;

  constructor(host: HTMLElement,
              ask: (query: string, total: number) => Promise<FieldAnswer | null>,
              onShow: (hits: FieldHit[], shown: number, soft: number) => void,
              onClear: () => void) {
    this.ask = ask; this.onShow = onShow; this.onClear = onClear;
    this.el = host.createDiv({ cls: "domvec-search3d" });
    const row = this.el.createDiv({ cls: "domvec-search3d-row" });
    this.input = row.createEl("input", { cls: "domvec-search3d-input" });
    this.input.type = "text";
    this.input.placeholder = "search";
    this.input.spellcheck = false;
    this.count = row.createDiv({ cls: "domvec-search3d-count" });
    const num = (v: number) => {
      const el = this.count.createEl("input", { cls: "domvec-search3d-k" });
      el.type = "number"; el.min = "1"; el.step = "1"; el.value = String(v);
      return el;
    };
    this.count.createSpan({ text: "showing " });
    this.kInput = num(this.k);
    this.count.createSpan({ text: "/" });
    this.nInput = num(this.total);
    this.count.createSpan({ text: " results" });
    this.matchEl = this.count.createSpan({ cls: "domvec-search3d-match", text: "" });
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
    const read = (el: HTMLInputElement, was: number) => { const v = Math.floor(Number(el.value)); return Number.isFinite(v) && v >= 1 ? v : was; };
    this.kInput.addEventListener("change", () => this.setK(read(this.kInput, this.k)));
    this.nInput.addEventListener("change", () => this.setTotal(read(this.nInput, this.total)));
    // Every scroll, once a frame: the soft index moves continuously.
    this.scroller.addEventListener("scroll", () => {
      if (this.scrollRaf) return;
      this.scrollRaf = requestAnimationFrame(() => { this.scrollRaf = 0; this.onScroll(); });
    }, { passive: true });
  }

  /** The top-k window the slider spans: never more than n. */
  get window(): FieldHit[] { return this.hits.slice(0, Math.min(this.k, this.total)); }

  /** k from the field: the slider's window, from the very left. No new ask. */
  setK(k: number): void {
    this.k = Math.max(1, Math.min(2000, Math.floor(k)));
    if (this.k > this.total) this.setTotal(this.k);
    else { this.scroller.scrollLeft = 0; this.paint(); this.onScroll(true); }
  }

  /** n from the field: the ranking asked again, that deep. */
  setTotal(n: number): void {
    this.total = Math.max(1, Math.min(2000, Math.floor(n)));
    if (this.k > this.total) this.k = this.total;
    void this.run();
  }

  async run(): Promise<void> {
    const q = this.input.value.trim();
    const seq = ++this.seq;
    this.query = q;
    if (!q) {
      this.hits = []; this.matching = 0; this.shown = 0;
      this.paint();
      this.onClear();
      return;
    }
    this.stats.queries++;
    const t0 = performance.now();
    const got = await this.ask(q, this.total);
    if (seq !== this.seq) return;                 // a newer query is in flight
    this.stats.lastMs = Math.round(performance.now() - t0);
    if (!got) return;
    this.stats.answered++;
    this.hits = got.hits.slice(0, this.total);
    this.matching = Math.max(got.n || 0, this.hits.length);
    this.scroller.scrollLeft = 0;                 // it begins at the very left
    this.paint();
    this.onScroll(true);
  }

  /** Merge results that arrived later (a second source) without moving the scroll. */
  extend(more: FieldHit[], n: number): void {
    const have = new Set(this.hits.map((h) => h.cid));
    for (const h of more) if (!have.has(h.cid) && this.hits.length < this.total) { this.hits.push(h); have.add(h.cid); }
    this.matching = Math.max(this.matching, n, this.hits.length);
    this.paint();
    this.onScroll(true);
  }

  private onScroll(force = false): void {
    const win = this.window;
    const span = this.scroller.scrollWidth - this.scroller.clientWidth;
    const frac = span > 0 ? this.scroller.scrollLeft / span : 0;
    const shown = visibleCount(frac, win.length);
    const soft = softIndex(frac, win.length);
    if (!force && shown === this.shown && Math.abs(soft - this.soft) < 1e-3) return;
    this.shown = shown;
    this.soft = soft;
    this.onShow(win, shown, soft);
  }

  private paint(): void {
    const active = this.hits.length > 0;
    this.el.toggleClass("is-active", active);
    // The fields say what is TRUE: k at most the results there are, n at most
    // what matched ("showing 12/11", 2026-10-11).
    const got = this.hits.length;
    if (document.activeElement !== this.kInput) this.kInput.value = String(active ? Math.min(this.k, got) : this.k);
    if (document.activeElement !== this.nInput) this.nInput.value = String(active ? got : this.total);
    this.matchEl.setText(active ? ` · ${this.matching} matching` : "");
    // One step of scroll per result, so a flick is a few results, not all.
    const w = this.scroller.clientWidth || 320;
    this.track.style.width = `${Math.round(w + Math.max(0, this.window.length - 1) * 28)}px`;
  }
}
