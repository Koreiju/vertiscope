/**
 * The retrieval artifact's own view (G-205; BROWSER_CENTROID_DESIGN.md §3-4):
 * a card on the plane, NOT a note -- the artifact is session-only (PLUGIN_GOAL
 * 177 d), and a vault note would outlive it.
 *
 * The card is a VIEW of the sidecar's one `browse` session, never a second
 * copy of it: it renders what `GET /browse` holds and polls `?since=v` for
 * the diffs, so a move made by an agent (the MCP tool) or a kernel cell
 * (`browse(...)`) appears here as it happens, and a click here is the same
 * call they make. Every move goes through `POST /browse`; what the move asks
 * of the reader's browser cell goes through the plugin's own `carryToolAsk`.
 *
 * Patricia-trie terms: the card reads the artifact (whose results are trie
 * reads and whose trace steps are urls the trie holds or will hold) and
 * writes nothing to the trie.
 */

export interface BrowseHost {
  base(): string;
  carry(ask: any): Promise<string>;
  /** The page the browser cell shows: the `of` of a domain or page scope. */
  shownUrl(): string;
}

const LEVEL_ORDER = ["host", "domain", "similar", "page", "web"];

export class BrowseCard {
  card: HTMLElement | null = null;
  version = 0;
  stats = { opened: 0, moves: 0, polls: 0, diffs_applied: 0, renders: 0, errors: 0, last_error: "" };
  /** Planted: the card never polls -- moves made elsewhere never show. */
  plantNoPoll = false;
  private timer = 0;
  private body: HTMLElement | null = null;
  private status: HTMLElement | null = null;
  private artifact: any = null;

  constructor(private host: BrowseHost) {}

  open(plane: HTMLElement, query = "", scope = "web"): HTMLElement {
    if (this.card && plane.contains(this.card)) { this.card.style.display = ""; }
    else this.build(plane);
    this.stats.opened++;
    if (!this.timer) this.timer = window.setInterval(() => { void this.poll(); }, 1500);
    if (query) void this.move({ query, scope, of: scope === "web" ? "" : this.host.shownUrl(), k: 10 });
    else void this.poll(true);
    return this.card!;
  }

  close(): void {
    if (this.timer) { window.clearInterval(this.timer); this.timer = 0; }
    this.card?.remove();
    this.card = null;
  }

  private build(plane: HTMLElement): void {
    const card = plane.createDiv({ cls: "domvec-browse-card" });
    // At the plane's RIGHT edge: the top-left is the retrieval bar's, and its
    // list opened under the card (seen live, run 83's screenshot).
    card.style.left = Math.max(24, plane.clientWidth - 384) + "px"; card.style.top = "64px";
    const head = card.createDiv({ cls: "domvec-browse-head" });
    head.createSpan({ cls: "domvec-browse-title", text: "browse" });
    const q = head.createEl("input", { cls: "domvec-browse-q", attr: { placeholder: "query…" } });
    const scope = head.createEl("select", { cls: "domvec-browse-scope" });
    for (const s of ["web", "domain", "page"]) scope.createEl("option", { text: s, attr: { value: s } });
    const up = head.createEl("button", { cls: "domvec-browse-up", text: "up" });
    const x = head.createEl("button", { cls: "domvec-browse-close", text: "×" });
    for (const el of [q, scope, up, x] as HTMLElement[]) el.onmousedown = (e) => e.stopPropagation();
    q.onkeydown = (e) => {
      if (e.key !== "Enter") return;
      e.preventDefault();
      const sc = scope.value;
      void this.move({ query: q.value, scope: sc, of: sc === "web" ? "" : this.host.shownUrl(), k: 10 });
    };
    up.onclick = (e) => { e.preventDefault(); void this.move({ up: true }); };
    x.onclick = (e) => { e.preventDefault(); this.close(); };
    this.status = card.createDiv({ cls: "domvec-browse-status" });
    this.body = card.createDiv({ cls: "domvec-browse-body" });
    // Dragged by its head, as the plane's other cards are.
    head.onmousedown = (e) => {
      const sx = e.clientX, sy = e.clientY, l = card.offsetLeft, t = card.offsetTop;
      const mv = (m: MouseEvent) => { card.style.left = l + m.clientX - sx + "px"; card.style.top = t + m.clientY - sy + "px"; };
      const upf = () => { window.removeEventListener("mousemove", mv); window.removeEventListener("mouseup", upf); };
      window.addEventListener("mousemove", mv); window.addEventListener("mouseup", upf);
      e.preventDefault(); e.stopPropagation();
    };
    card.onwheel = (e) => e.stopPropagation();
    this.card = card;
  }

  /** One move: the same call an agent or a kernel cell makes. */
  async move(body: any): Promise<any> {
    this.stats.moves++;
    let got: any;
    try {
      const r = await fetch(this.host.base() + "/browse", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
      got = await r.json();
      if (!r.ok) throw new Error(got?.error || String(r.status));
    } catch (e) {
      this.stats.errors++; this.stats.last_error = String((e as any)?.message || e);
      if (this.status) this.status.setText("browse: " + this.stats.last_error);
      return null;
    }
    const said: string[] = [];
    for (const a of got.asks || []) said.push(await this.host.carry(a));
    this.render(got.artifact, got.version, said.join(" · "));
    return got;
  }

  /** The diffs since the version drawn; any change redraws from the artifact. */
  async poll(force = false): Promise<void> {
    if (!this.card || (this.plantNoPoll && !force)) return;
    this.stats.polls++;
    try {
      const got = await (await fetch(this.host.base() + "/browse?since=" + (force ? 0 : this.version))).json();
      if (force || (got.version || 0) > this.version) {
        this.stats.diffs_applied += (got.changes || []).length;
        this.render(got.artifact, got.version || 0, "");
      }
    } catch (e) { this.stats.errors++; this.stats.last_error = String(e); }
  }

  private render(art: any, version: number, said: string): void {
    this.artifact = art; this.version = version || this.version;
    this.stats.renders++;
    const body = this.body, status = this.status;
    if (!body || !status) return;
    body.empty();
    if (!art) { status.setText("no artifact yet: type a query"); return; }
    const cur = art.cursor || {};
    status.setText(`${art.scope}${art.of ? " of " + art.of : ""} · "${art.query}" · ${(art.results || []).length} results · at ${cur.at}${cur.cid ? " " + String(cur.cid).slice(0, 10) : ""} · v${this.version}${said ? " · " + said : ""}`);
    const groups = new Map<string, any[]>();
    for (const h of art.results || []) { const l = h.level || "web"; if (!groups.has(l)) groups.set(l, []); groups.get(l)!.push(h); }
    for (const level of [...groups.keys()].sort((a, b) => LEVEL_ORDER.indexOf(a) - LEVEL_ORDER.indexOf(b))) {
      const sec = body.createDiv({ cls: "domvec-browse-level" });
      sec.dataset.level = level;
      sec.createDiv({ cls: "domvec-browse-level-head", text: `${level} · ${groups.get(level)!.length}` });
      for (const h of groups.get(level)!) {
        const row = sec.createDiv({ cls: "domvec-browse-hit" });
        row.dataset.cid = h.cid;
        if (cur.at === "trace" && cur.cid === h.cid) row.addClass("is-down");
        row.createDiv({ cls: "domvec-browse-hit-host", text: h.host || "" });
        row.createDiv({ cls: "domvec-browse-hit-text", text: readable(h.preview || h.url || "").slice(0, 160) });
        row.onmousedown = (e) => { e.preventDefault(); e.stopPropagation(); void this.move({ down: h.cid }); };
        const steps = (h.trace || []).filter((s: any) => s.url || s.act);
        if (steps.length) {
          const tr = row.createDiv({ cls: "domvec-browse-trace" });
          for (const s of steps) tr.createDiv({ cls: "domvec-browse-step", text: (s.by === "act" ? "act " + s.act : "→ " + s.url) });
        }
      }
    }
  }
}

/** A preview as a reader reads it: heading marks and empty image
 *  placeholders (`[ ]`) dropped -- display only; the artifact keeps the
 *  markdown the trie holds. */
export function readable(md: string): string {
  return String(md).replace(/(^|\s)#{1,6}\s+/g, "$1").replace(/\[\s*\]\s*/g, "").replace(/\s+/g, " ").trim();
}
