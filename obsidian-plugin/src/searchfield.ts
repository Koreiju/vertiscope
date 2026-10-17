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

/** One step of a held arrow key (item 109): 1 at first, then faster the
 *  longer the hold -- doubling every 600 ms past the first 400, to 100. */
export function holdStep(heldMs: number): number {
  if (!(heldMs > 400)) return 1;
  return Math.min(100, Math.max(1, Math.floor(2 ** ((heldMs - 400) / 600))));
}

export interface FieldHit { cid: string; url: string }
export interface FieldAnswer { hits: FieldHit[]; n: number }

/** What a re-ranking changed, against the ranking shown (item 106). */
export interface RankDiff { added: number; removed: number; moved: number }
export function rankDiff(was: FieldHit[], now: FieldHit[]): RankDiff {
  const at = new Map(was.map((h, i) => [h.cid, i]));
  const keep = new Set(now.map((h) => h.cid));
  let added = 0, moved = 0;
  now.forEach((h, i) => { const j = at.get(h.cid); if (j === undefined) added++; else if (j !== i) moved++; });
  return { added, removed: was.filter((h) => !keep.has(h.cid)).length, moved };
}

/** The bar's gradient: one stop per result in the window, as bright as that
 *  result is at soft index `s` -- the light the scene shows, drawn where the
 *  reader's thumb is (items 97, 106). */
export function barGradient(k: number, s: number): string {
  if (!(k > 0)) return "none";
  const stops: string[] = [];
  for (let i = 0; i < k; i++) {
    const x = k === 1 ? 50 : (100 * i) / (k - 1);
    const a = 0.04 + 0.5 * brightness(i, s);
    stops.push(`rgba(255,255,255,${a.toFixed(3)}) ${x.toFixed(2)}%`);
  }
  if (stops.length === 1) stops.push(stops[0]);
  return `linear-gradient(90deg, ${stops.join(", ")})`;
}

export class SearchField {
  readonly el: HTMLElement;
  readonly input: HTMLInputElement;
  readonly kInput: HTMLInputElement;
  /** n, the total results asked for: a field too (2026-10-11, item 97: "seems
   *  like youre thresholding on the number of total results. perhaps that
   *  could also be another user input field for total results"). */
  readonly nInput: HTMLInputElement;
  private matchEl: HTMLElement;
  private diffEl: HTMLElement;
  /** The search button: the ONE thing that sends a query to the web (item 107). */
  readonly button: HTMLButtonElement;
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
  stats = { queries: 0, answered: 0, lastMs: 0, submitted: 0, updates: 0, changed: 0,
            added: 0, removed: 0, moved: 0, lastDiff: null as RankDiff | null, arrowSteps: 0 };
  private diffTimer = 0;
  private totalTimer = 0;

  private ask: (query: string, total: number) => Promise<FieldAnswer | null>;
  private onShow: (hits: FieldHit[], shown: number, soft: number) => void;
  private onClear: () => void;
  /** Told when the reader presses search: the web half (item 107). */
  onSubmit: (query: string) => void = () => {};

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
    this.button = row.createEl("button", { cls: "domvec-search3d-go", text: "search" });
    this.button.title = "search the web too";
    this.button.addEventListener("click", () => { void this.submit(); });
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
    this.diffEl = this.count.createSpan({ cls: "domvec-search3d-diff", text: "" });
    this.scroller = this.el.createDiv({ cls: "domvec-search3d-scroll" });
    this.track = this.scroller.createDiv({ cls: "domvec-search3d-track" });
    this.paint();

    this.input.addEventListener("input", () => {
      window.clearTimeout(this.debounce);
      this.debounce = window.setTimeout(() => { void this.run(); }, 250);
    });
    this.input.addEventListener("keydown", (e) => {
      if (e.key === "Escape") { this.input.value = ""; void this.run(); }
      else if (e.key === "Enter") { void this.submit(); }
    });
    const read = (el: HTMLInputElement, was: number) => { const v = Math.floor(Number(el.value)); return Number.isFinite(v) && v >= 1 ? v : was; };
    this.kInput.addEventListener("change", () => this.setK(read(this.kInput, this.k)));
    this.nInput.addEventListener("change", () => this.setTotal(read(this.nInput, this.total)));
    // Up/Down step the value; a held key steps faster the longer it is held
    // (item 109). k follows at once (no ask); n asks the store once the keys
    // rest, so a held key is not a query per repeat.
    const arrows = (el: HTMLInputElement, isK: boolean) => {
      let since = 0;
      el.addEventListener("keydown", (e) => {
        if (e.key !== "ArrowUp" && e.key !== "ArrowDown") return;
        e.preventDefault();
        const now = performance.now();
        if (!e.repeat || !since) since = now;
        const step = holdStep(now - since) * (e.key === "ArrowUp" ? 1 : -1);
        const v = Math.max(1, Math.min(2000, read(el, isK ? this.k : this.total) + step));
        el.value = String(v);
        this.stats.arrowSteps++;
        if (isK && v <= this.total) this.setK(v);
        else {
          // n, or k past n (which deepens n): one ask when the keys rest.
          const apply = isK ? () => this.setK(read(el, this.k)) : () => this.setTotal(read(el, this.total));
          window.clearTimeout(this.totalTimer);
          this.totalTimer = window.setTimeout(apply, 300);
        }
      });
      el.addEventListener("keyup", (e) => { if (e.key === "ArrowUp" || e.key === "ArrowDown") since = 0; });
    };
    arrows(this.kInput, true);
    arrows(this.nInput, false);
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

  /** The search button (and Enter): the store ranked now, and the web asked
   *  too. Typing alone never reaches the web (item 107). */
  async submit(): Promise<void> {
    window.clearTimeout(this.debounce);
    const q = this.input.value.trim();
    if (q && q !== this.query) await this.run();
    if (!q) { await this.run(); return; }
    this.stats.submitted++;
    this.onSubmit(q);
  }

  /**
   * The ranking asked again while the query stands -- what streamed into the
   * store since -- applied as a DIFF (item 106): the new order replaces the
   * old, the scroll stays where the reader put it, and the field says what
   * moved. Returns the diff, or null when the query changed meanwhile.
   */
  async update(): Promise<RankDiff | null> {
    const q = this.query;
    if (!q) return null;
    const seq = this.seq;
    const got = await this.ask(q, this.total);
    if (!got || seq !== this.seq || q !== this.query) return null;
    const now = got.hits.slice(0, this.total);
    const d = rankDiff(this.hits, now);
    const n = Math.max(got.n || 0, now.length);
    this.stats.updates++;
    if (!d.added && !d.removed && !d.moved && n === this.matching) return d;
    this.stats.changed++;
    this.stats.added += d.added; this.stats.removed += d.removed; this.stats.moved += d.moved;
    this.stats.lastDiff = d;
    const left = this.scroller.scrollLeft;
    this.hits = now;
    this.matching = n;
    this.paint();
    this.scroller.scrollLeft = left;              // the reader's place, kept
    const parts = [d.added ? `+${d.added}` : "", d.removed ? `−${d.removed}` : "", d.moved ? `⇅${d.moved}` : ""].filter(Boolean);
    this.diffEl.setText(parts.length ? ` · ${parts.join(" ")}` : "");
    this.diffEl.addClass("is-fresh");
    window.clearTimeout(this.diffTimer);
    this.diffTimer = window.setTimeout(() => { this.diffEl.removeClass("is-fresh"); }, 1500);
    this.onScroll(true);
    return d;
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
    this.scroller.style.backgroundImage = barGradient(win.length, soft);
    this.onShow(win, shown, soft);
  }

  private paint(): void {
    const active = this.hits.length > 0;
    this.el.toggleClass("is-active", active);
    // The fields say what is TRUE: k at most the results there are, n at most
    // what matched ("showing 12/11", 2026-10-11).
    // The fields hold what the READER set -- k shown of n asked -- and what
    // came back is said beside them. Writing the returned count into n made
    // an edit snap back whenever fewer came back (2026-10-17: "they don't
    // work for updates right").
    const got = this.hits.length;
    if (document.activeElement !== this.kInput) this.kInput.value = String(this.k);
    if (document.activeElement !== this.nInput) this.nInput.value = String(this.total);
    this.matchEl.setText(active ? ` · ${got} retrieved of ${this.matching} matching` : "");
    if (!active) { this.diffEl.setText(""); this.scroller.style.backgroundImage = "none"; }
    // One step of scroll per result, so a flick is a few results, not all.
    const w = this.scroller.clientWidth || 320;
    this.track.style.width = `${Math.round(w + Math.max(0, this.window.length - 1) * 28)}px`;
  }
}
