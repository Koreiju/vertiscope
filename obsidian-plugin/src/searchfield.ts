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
import { edgeResizable } from "./edgeresize";

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

export interface FieldHit { cid: string; url: string; score?: number; preview?: string }

/**
 * The results STRIP's scroll for the bar's (PLUGIN_GOAL 151: "a horizontal
 * overlay of retrieval results above the search bar that is linked to the
 * scroll bar below the search and matches the scrolling scale"): one
 * fraction drives both, so the strip stands where the bar stands.
 */
export function stripScrollFor(frac: number, scrollWidth: number, clientWidth: number): number {
  const span = Math.max(0, scrollWidth - clientWidth);
  const f = Number.isFinite(frac) ? Math.min(1, Math.max(0, frac)) : 0;
  return Math.round(f * span);
}

/** A strip item's light: its node's (`brightness`), dim but legible unshown. */
export function stripLight(rank: number, shown: number, soft: number): number {
  return rank < shown ? Math.max(0.25, brightness(rank, soft)) : 0.18;
}
/** The two tiers of a tiered search (G-210): url nodes, then each url's chunks. */
export interface FieldTiers {
  /** Tier 1: the pages, and (when the store says) the corpus-wide match count. */
  pages: (query: string, k: number) => Promise<{ url: string; score: number; n?: number | null }[] | null>;
  matching?: (query: string) => number | null;
  page: (query: string, url: string, k: number) => Promise<FieldAnswer | null>;
}
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

/** The ask's own ceiling (the sidecar's): a runaway request, not a limit the reader meets. */
const MAX_ASK = 20000;

/** What the k/n fields show: the reader's k and n, bounded by what MATCHES
 *  (`matching`, 0 before any answer) -- not a fixed 2000 (PLUGIN_GOAL 154). */
export function fieldBounds(k: number, total: number, matching: number, fixedCap = false): { k: number; n: number; cap: number } {
  const cap = fixedCap ? 2000 : (matching > 0 ? Math.min(MAX_ASK, matching) : MAX_ASK);
  const n = Math.max(1, Math.min(total, cap));
  return { k: Math.max(1, Math.min(k, n)), n, cap };
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
            added: 0, removed: 0, moved: 0, lastDiff: null as RankDiff | null, arrowSteps: 0, emptyHeld: 0 };
  private diffTimer = 0;
  private totalTimer = 0;

  private ask: (query: string, total: number) => Promise<FieldAnswer | null>;
  private onShow: (hits: FieldHit[], shown: number, soft: number) => void;
  private onClear: () => void;
  /** Told when the reader presses search: the web half (item 107). */
  onSubmit: (query: string) => void = () => {};
  /** Every query typed, whichever path answers it (tiered or single): the
   *  graph's per-query work. The tiered path (G-210) never reached the
   *  graph's `searchAsk`, so its plants and its store-following stopped
   *  running there -- G-167's and G-178's planted arms read exactly as clean
   *  (2026-11-14). */
  onAsked: (query: string) => void = () => {};
  /** The answer, whichever path: the graph may act on the hits. */
  onAnswered: (query: string, hits: FieldHit[]) => Promise<void> | void = () => {};
  /** Tiered retrieval (G-210), when the host provides it. */
  tiers: FieldTiers | null = null;
  /** Planted: one ranking of every chunk, as before. */
  plantSingleTier = false;
  /** Planted: `matching` is the sum over tier 2's pages (what the top pages hold). */
  plantPageSumMatching = false;
  /** Planted: tier 1's page count from n alone (6-40), each asked an even share. */
  plantFixedPages = false;
  /** Planted: a page counts (and is asked) for all it holds -- two pages took all of n. */
  plantUncappedShare = false;
  /** Planted (G-231): no pages asked past the count cut. */
  plantNoReserve = false;
  /** Planted (G-231): the share is per URL, so one page held under several
   *  fragments (Trie, Trie#, Trie#~v, Trie##~v) is asked for a share each. */
  plantShareByUrl = false;
  /** When the reader last scrolled the results (re-ranks wait for it to rest). */
  lastScrollAt = 0;
  tierStats = { runs: 0, pages: 0, pages_done: 0, first_ms: 0, last_ms: 0, single_ms: 0, reserve: 0 };

  /**
   * **Tiered retrieval** (2026-10-17, PLUGIN_GOAL 137/142: "retrieval new URL
   * nodes and re-rank, then retrieve their containing chunks and re-rank,
   * updating the current set of most recent retrieved chunks for all current
   * URLs"). Tier 1 ranks the url nodes; tier 2 ranks each url's own chunks,
   * three pages in flight, and after EVERY page the set retrieved so far is
   * re-ranked by score and shown -- the readout and the 3D lights follow the
   * most recent set (G-212) instead of waiting for one ranking of the corpus.
   * `keepScroll` for an update while the query stands (item 106).
   */
  private async tiered(q: string, seq: number, keepScroll: boolean): Promise<FieldHit[] | null> {
    const t0 = performance.now();
    const tiers = this.tiers!;
    // Enough pages to COVER n: tier 1 says how many matches each holds, and
    // pages are taken in rank order until their counts reach n -- twelve
    // pages of one or two matches each gave 18 of 5,000 asked (2026-10-18).
    // Planted `plantFixedPages`: a page count from n alone, as before.
    const asked = this.plantFixedPages ? Math.max(6, Math.min(40, Math.ceil(this.total / 6))) : 200;
    let pages = await tiers.pages(q, asked);
    if (seq !== this.seq || q !== this.input.value.trim()) return null;
    if (!pages || !pages.length) return null;
    // Each page counted (and asked) for at most a SIXTH of n: pages holding
    // thousands of matches (a search engine's result page) swallowed all of n
    // and every result came from two pages (2026-10-18, PLUGIN_GOAL 160).
    // Planted `plantUncappedShare`: a page counted for all it holds.
    const share = this.plantUncappedShare ? Infinity : Math.max(5, Math.ceil(this.total / 6));
    // The share is the DOCUMENT's, not the url's: the store can hold one page
    // under several fragments -- Trie, Trie#, Trie#~v and Trie##~v, 246
    // matches -- and a share each gave Trie four sixths of n and the hits five
    // pages (G-231, run 48). Each tier-1 entry is allotted what is left of
    // its document's share, in rank order; one with nothing left is skipped.
    // Planted `plantShareByUrl`: a share per url, as before.
    const docOf = (u: string) => this.plantShareByUrl ? u : String(u).split("#")[0];
    const allot = new Map<string, number>();
    let reserve: typeof pages = [];
    if (!this.plantFixedPages && pages.every((p) => typeof p.n === "number")) {
      const used = new Map<string, number>();
      pages = pages.filter((p) => {
        const d = docOf(p.url), left = share - (used.get(d) || 0);
        const a = Math.min(p.n!, left);
        if (!(a > 0)) return false;
        used.set(d, (used.get(d) || 0) + a);
        allot.set(p.url, a);
        return true;
      });
      let sum = 0, cut = pages.length;
      for (let i = 0; i < pages.length; i++) { sum += allot.get(pages[i].url)!; if (sum >= this.total) { cut = i + 1; break; } }
      // The cut is where the COUNTS reach n; a page can hand back fewer
      // chunks than it counted (G-231, 2026-11-08: 7 pages asked, 5 answered,
      // 174 of 200). The pages past the cut are kept in reserve and asked, in
      // rank order, while the set is still short of n. Planted
      // `plantNoReserve`: the cut is the end, as before.
      reserve = pages.slice(Math.max(1, cut));
      pages = pages.slice(0, Math.max(1, cut));
    }
    this.tierStats.runs++; this.tierStats.pages = pages.length; this.tierStats.pages_done = 0; this.tierStats.first_ms = 0;
    const per = Math.max(5, Math.ceil(this.total / pages.length) + 5);
    // Each page asked for what it HOLDS (bounded by n), not an even share.
    const perOf = (p: { url: string; n?: number | null }) => (!this.plantFixedPages && typeof p.n === "number") ? Math.max(1, Math.min(this.total, p.n, allot.get(p.url) ?? share)) : per;
    const byCid = new Map<string, FieldHit>();
    let first = true, matching = 0;
    // The corpus's own count when tier 1 gave one; the per-page sum only
    // counts what the top pages hold. Planted `plantPageSumMatching`.
    const corpus = !this.plantPageSumMatching && tiers.matching ? tiers.matching(q) : null;
    const apply = () => {
      const now = [...byCid.values()].sort((a, b) => (b.score ?? 0) - (a.score ?? 0)).slice(0, this.total);
      const left = this.scroller.scrollLeft;
      this.hits = now;
      this.matching = Math.max(corpus ?? matching, now.length);
      this.paint();
      this.scroller.scrollLeft = (first && !keepScroll) ? 0 : left;
      first = false;
      this.onScroll(true);
    };
    let next = 0;
    const worker = async () => {
      while (next < pages!.length) {
        const p = pages![next++];
        const got = await tiers.page(q, p.url, perOf(p));
        if (seq !== this.seq) return;
        for (const h of got?.hits || []) {
          const was = byCid.get(h.cid);
          if (!was || (h.score ?? 0) > (was.score ?? 0)) byCid.set(h.cid, h);
        }
        matching += got?.n || 0;
        this.tierStats.pages_done++;
        if (!this.tierStats.first_ms) this.tierStats.first_ms = Math.round(performance.now() - t0);
        apply();
      }
    };
    await Promise.all([worker(), worker(), worker()]);
    if (seq !== this.seq) return null;
    if (!this.plantNoReserve) {
      while (byCid.size < this.total && reserve.length) {
        pages = reserve.splice(0, 3); next = 0; this.tierStats.reserve = (this.tierStats.reserve || 0) + pages.length;
        await Promise.all([worker(), worker(), worker()]);
        if (seq !== this.seq) return null;
      }
    }
    this.tierStats.last_ms = Math.round(performance.now() - t0);
    return this.hits;
  }

  head!: HTMLElement;
  private unedge: (() => void) | null = null;
  panelStats = { panel: false, drags: 0, toggles: 0, last: "" };
  private static PLACE_KEY = "domvec-search-panel";
  private loadPlace(): { panel?: boolean; x?: number; y?: number; w?: number; h?: number } | null {
    try { return JSON.parse(window.localStorage.getItem(SearchField.PLACE_KEY) || "null"); } catch { return null; }
  }
  private savePlace(): void {
    const on = this.el.hasClass("is-panel");
    const rec: any = { panel: on };
    if (on) { rec.x = this.el.offsetLeft; rec.y = this.el.offsetTop; rec.w = this.el.offsetWidth; rec.h = this.el.offsetHeight; }
    try { window.localStorage.setItem(SearchField.PLACE_KEY, JSON.stringify({ ...(this.loadPlace() || {}), ...rec })); } catch { /* a convenience only */ }
  }
  /** Within the pane: the panel never leaves it. */
  private placeAt(x: number, y: number): void {
    const home = (this.el.offsetParent as HTMLElement | null) || this.el.parentElement;
    const W = home?.clientWidth || 800, H = home?.clientHeight || 600;
    const w = this.el.offsetWidth, h = this.el.offsetHeight;
    this.el.style.left = `${Math.round(Math.max(0, Math.min(W - w, x)))}px`;
    this.el.style.top = `${Math.round(Math.max(0, Math.min(H - h, y)))}px`;
  }
  /** The panel (true) or the naked bar (false). */
  setPanel(on: boolean): void {
    if ((window as any).__domvecPlantNakedSearch) on = false;
    const was = this.el.hasClass("is-panel");
    this.el.toggleClass("is-panel", on);
    this.panelStats.panel = on;
    if (on !== was) { this.panelStats.toggles++; this.panelStats.last = on ? "panel" : "bar"; }
    if (on) {
      const at = this.loadPlace();
      const home = (this.el.offsetParent as HTMLElement | null) || this.el.parentElement;
      const W = home?.clientWidth || 800, H = home?.clientHeight || 600;
      // A saved size never exceeds the pane it opens in (a 564 px panel was
      // saved, then opened in a 404 px pane and could not move at all).
      if (at && Number.isFinite(at.w) && Number.isFinite(at.h)) {
        this.el.style.width = `${Math.min(at.w!, W)}px`; this.el.style.height = `${Math.min(Math.max(150, at.h!), H)}px`;
      } else if (this.el.offsetWidth > W) this.el.style.width = `${W}px`;
      if (at && Number.isFinite(at.x) && Number.isFinite(at.y)) this.placeAt(at.x!, at.y!);
      else this.placeAt((W - this.el.offsetWidth) / 2, H - this.el.offsetHeight - 18);
    } else {
      this.el.style.left = ""; this.el.style.top = ""; this.el.style.width = ""; this.el.style.height = "";
      this.el.style.maxWidth = ""; this.el.style.maxHeight = "";
    }
    this.savePlace();
  }
  /** Carried by its header: the real pointer, captured so a drag that leaves the pane still ends. */
  private dragFrom(e: PointerEvent): void {
    if (e.button !== 0 || !this.el.hasClass("is-panel") || (e.target as HTMLElement).closest("button")) return;
    if (this.el.dataset.domvecEdge) return;                     // an edge: the resize has it
    e.preventDefault(); e.stopPropagation();
    const r = this.el.getBoundingClientRect(), home = ((this.el.offsetParent as HTMLElement | null) || this.el.parentElement)!.getBoundingClientRect();
    const dx = e.clientX - r.left, dy = e.clientY - r.top;
    const move = (m: PointerEvent) => this.placeAt(m.clientX - home.left - dx, m.clientY - home.top - dy);
    const up = () => {
      window.removeEventListener("pointermove", move, true); window.removeEventListener("pointerup", up, true);
      this.panelStats.drags++; this.savePlace();
    };
    window.addEventListener("pointermove", move, true);
    window.addEventListener("pointerup", up, true);
  }

  constructor(host: HTMLElement,
              ask: (query: string, total: number) => Promise<FieldAnswer | null>,
              onShow: (hits: FieldHit[], shown: number, soft: number) => void,
              onClear: () => void) {
    this.ask = ask; this.onShow = onShow; this.onClear = onClear;
    this.el = host.createDiv({ cls: "domvec-search3d" });
    // THE DATABASE RETRIEVAL CELL (PLUGIN_GOAL 159: "The search bar should be
    // expanded and become a draggable cell panel that is the database
    // retrieval function in our README"). A header names it and carries it;
    // any edge resizes it; its place is kept for this viewer. The header's
    // toggle folds it back to the naked bar (84-87). Planted
    // `window.__domvecPlantNakedSearch`: the naked bar only, as before.
    this.head = this.el.createDiv({ cls: "domvec-search3d-head" });
    this.head.createSpan({ cls: "domvec-search3d-title", text: "database retrieval" });
    this.head.createSpan({ cls: "domvec-search3d-sub", text: "frequency × PageRank × semantic" });
    const fold = this.head.createEl("button", { cls: "domvec-search3d-fold", text: "–" });
    fold.title = "fold to the bar";
    fold.addEventListener("click", (e) => { e.stopPropagation(); this.setPanel(false); });
    // The results strip, above the input (G-222). Scrolled by the bar below
    // and scrolling it back; each item lit as its node is; hovering one flies
    // to its node.
    this.strip = this.el.createDiv({ cls: "domvec-search3d-strip" });
    this.strip.addEventListener("scroll", () => {
      if (this.stripSyncing) return;
      const span = this.strip.scrollWidth - this.strip.clientWidth;
      const bar = this.scroller.scrollWidth - this.scroller.clientWidth;
      if (span <= 0 || bar <= 0) return;
      this.barSyncing = true;
      this.scroller.scrollLeft = Math.round((this.strip.scrollLeft / span) * bar);
      requestAnimationFrame(() => { this.barSyncing = false; });
    }, { passive: true });
    // A wheel over the strip scrolls it sideways, as over the bar.
    this.strip.addEventListener("wheel", (e) => {
      if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) { this.strip.scrollLeft += e.deltaY; e.preventDefault(); }
    }, { passive: false });
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
    const unfold = row.createEl("button", { cls: "domvec-search3d-unfold", text: "⤢" });
    unfold.title = "open as a panel";
    unfold.addEventListener("click", (e) => { e.stopPropagation(); this.setPanel(true); });
    this.head.addEventListener("pointerdown", (e) => this.dragFrom(e));
    this.unedge = edgeResizable(this.el, { band: 6, minW: 300, minH: 150,
      enabled: () => this.el.hasClass("is-panel"), onEnd: () => this.savePlace() });
    window.requestAnimationFrame(() => this.setPanel(!(window as any).__domvecPlantNakedSearch && this.loadPlace()?.panel !== false));

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
        const v = Math.max(1, Math.min(this.cap, read(el, isK ? this.k : this.total) + step));
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
      this.lastScrollAt = performance.now();
      this.scrollRaf = requestAnimationFrame(() => { this.scrollRaf = 0; this.onScroll(); });
    }, { passive: true });
  }

  /**
   * The fields' upper limit: the number of chunks that MATCH, once a ranking
   * has said (2026-10-17, PLUGIN_GOAL 154: "maxed out at 2000 rather than
   * the proper upper limit" -- "showing 2000 / 2000 results, 29 retrieved of
   * 587 matching"). Before any answer, the ask's own ceiling. Planted:
   * `plantFixedCap` (2000, as before).
   */
  get cap(): number { return fieldBounds(this.k, this.total, this.matching, this.plantFixedCap).cap; }
  plantFixedCap = false;

  /** The top-k window the slider spans: never more than n. */
  get window(): FieldHit[] { return this.hits.slice(0, Math.min(this.k, this.total)); }

  /** k from the field: the slider's window, from the very left. No new ask. */
  setK(k: number): void {
    this.k = Math.max(1, Math.min(MAX_ASK, Math.floor(k)));
    if (this.k > this.total) this.setTotal(this.k);
    // No query, nothing to render (2026-11-07, 137(5): "using arrow keys
    // triggers the search render even when the search input field wasn't even
    // interacted with and there is no text either"). Reproduced 2026-11-08:
    // Up/Down in the k box with the field empty fired onScroll twice -- the
    // frontier re-rendered. The number changes; nothing is drawn.
    // Planted `__domvecPlantArrowsEmptyRender`: it renders, as before.
    else if (!this.input.value.trim() && !(globalThis as any).__domvecPlantArrowsEmptyRender) { this.paint(); this.stats.emptyHeld = (this.stats.emptyHeld || 0) + 1; }
    else { this.scroller.scrollLeft = 0; this.paint(); this.onScroll(true); }
  }

  /** n from the field: the ranking asked again, that deep. */
  setTotal(n: number): void {
    this.total = Math.max(1, Math.min(MAX_ASK, Math.floor(n)));
    if (this.k > this.total) this.k = this.total;
    // The same for n (137(5)): with no query there is nothing to ask again --
    // it ran the search and cleared the scene on every arrow.
    if (!this.input.value.trim() && !(globalThis as any).__domvecPlantArrowsEmptyRender) { this.paint(); this.stats.emptyHeld = (this.stats.emptyHeld || 0) + 1; return; }
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
    this.onAsked(q);
    if (this.tiers && !this.plantSingleTier) {
      const done = await this.tiered(q, seq, false);
      if (seq !== this.seq) return;
      if (done) { await this.onAnswered(q, this.hits); this.stats.answered++; this.stats.lastMs = Math.round(performance.now() - t0); return; }
    }
    const got = await this.ask(q, this.total);
    this.tierStats.single_ms = Math.round(performance.now() - t0);
    if (seq !== this.seq) return;                 // a newer query is in flight
    this.stats.lastMs = Math.round(performance.now() - t0);
    if (!got) return;
    this.stats.answered++;
    this.hits = got.hits.slice(0, this.total);
    this.matching = Math.max(got.n || 0, this.hits.length);
    await this.onAnswered(q, this.hits);
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
    if (this.tiers && !this.plantSingleTier) {
      // The update, tiered too: new url nodes retrieved and re-ranked, then
      // their chunks -- the reader's scroll kept throughout.
      const was = this.hits;
      const done = await this.tiered(q, seq, true);
      if (!done || seq !== this.seq || q !== this.query) return null;
      const d = rankDiff(was, done);
      this.stats.updates++;
      if (d.added || d.removed || d.moved) { this.stats.changed++; this.stats.lastDiff = d; }
      return d;
    }
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
    this.paintStrip(win, frac, shown, soft);
    if (!force && shown === this.shown && Math.abs(soft - this.soft) < 1e-3) return;
    this.shown = shown;
    this.soft = soft;
    this.scroller.style.backgroundImage = barGradient(win.length, soft);
    this.onShow(win, shown, soft);
  }

  readonly strip: HTMLElement;
  private stripSyncing = false;
  private barSyncing = false;
  private stripKey = "";
  /** A result's label in the strip (the graph supplies the node's title). */
  labelOf: (hit: FieldHit) => string = (h) => { try { return new URL(h.url).hostname; } catch { return h.url; } };
  /** A strip item hovered (or left, with null): the graph flies to its node. */
  onHoverHit: (hit: FieldHit | null) => void = () => {};
  /** A strip item right-clicked: the graph opens its panel. */
  onRightHit: (hit: FieldHit) => void = () => {};
  stripStats = { renders: 0, hovers: 0, synced: 0, right: 0 };
  /** Planted: the strip stands still while the bar scrolls (not linked). */
  plantStripUnlinked = false;

  private paintStrip(win: FieldHit[], frac: number, shown: number, soft: number): void {
    const key = win.map((h) => h.cid).join("|");
    if (key !== this.stripKey) {
      this.stripKey = key;
      this.strip.empty();
      win.forEach((h, i) => {
        const it = this.strip.createDiv({ cls: "domvec-search3d-item" });
        it.createSpan({ cls: "domvec-search3d-item-rank", text: String(i + 1) });
        it.createSpan({ cls: "domvec-search3d-item-label", text: this.labelOf(h) });
        it.title = h.url;
        it.addEventListener("mouseenter", () => { this.stripStats.hovers++; this.onHoverHit(h); });
        it.addEventListener("mouseleave", () => this.onHoverHit(null));
        // Right-click: the result's panel (the right-click mode's open, G-232).
        it.addEventListener("contextmenu", (e) => { e.preventDefault(); this.stripStats.right++; this.onRightHit(h); });
      });
      this.stripStats.renders++;
    }
    const items = this.strip.children;
    for (let i = 0; i < items.length; i++) {
      const el = items[i] as HTMLElement;
      el.style.opacity = String(stripLight(i, shown, soft));
      el.toggleClass("is-front", i === Math.max(0, Math.round(soft) - 1));
    }
    if (this.barSyncing || this.plantStripUnlinked) return;
    this.stripSyncing = true;
    this.strip.scrollLeft = stripScrollFor(frac, this.strip.scrollWidth, this.strip.clientWidth);
    this.stripStats.synced++;
    requestAnimationFrame(() => { this.stripSyncing = false; });
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
    // ...bounded by what MATCHES: the request stays as the reader set it (a
    // later query with more matches gets it), the field shows what it can be.
    const got = this.hits.length;
    const { k, n } = fieldBounds(this.k, this.total, this.matching, this.plantFixedCap);
    if (document.activeElement !== this.kInput) this.kInput.value = String(k);
    if (document.activeElement !== this.nInput) this.nInput.value = String(n);
    this.kInput.max = this.nInput.max = String(this.cap);
    this.matchEl.setText(active ? ` · ${got} retrieved of ${this.matching} matching` : "");
    if (!active) { this.diffEl.setText(""); this.scroller.style.backgroundImage = "none"; }
    // One step of scroll per result, so a flick is a few results, not all.
    const w = this.scroller.clientWidth || 320;
    this.track.style.width = `${Math.round(w + Math.max(0, this.window.length - 1) * 28)}px`;
  }
}
