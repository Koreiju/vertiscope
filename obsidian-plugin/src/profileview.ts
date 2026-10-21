/**
 * The pipeline profile, as a readout inside the browser cell's corner box.
 *
 * **Not a pane (`G-76`).** It was one, and the reader asked for the opposite:
 * statistics are wanted -- "if you can see it and I can see it, it's
 * important" -- but not in a space of their own, separate from the rest of
 * the plugin. The scanning pipeline's numbers belong over the page being
 * scanned, in the collapsible box in its bottom-right corner, which the MCP
 * tools also read and toggle. Same drawing code, mounted there.
 *
 * **What this pane is for.** The profiler times every live drain from the
 * page to the pixels, but until now its answers were reachable only through
 * MCP tools and tests -- so the one person who watches the app work, the
 * reader, could not see where a slow moment went. This draws the same
 * numbers in the workspace, live, as they browse.
 *
 * **It displays; it does not measure.** Every figure here comes from a
 * component that is tested with a planted arm -- the renderer's profiler
 * (`profile.ts`, whose scene listener must refuse a hidden node) and the
 * sidecar's rings (`/profile`, whose store phases must blame a planted delay
 * on the right statement). A pane that computed its own numbers would be a
 * third instrument with no such test, which is the thing `CLAUDE.md`'s
 * "analytics outside the REPL" rule is guarding against.
 *
 * **And it shows the store's integrity beside the timings**, because a
 * timing is only meaningful over a store that holds what was captured. That
 * assumption was false for most of a session: 80.6% of chunk markdown was
 * silently empty and every number measured over it was measuring a hollow
 * corpus. The counters are here so that state is visible the moment it
 * returns, rather than found by someone counting by hand.
 */

import type { Sidecar } from "./sidecar";
import { profiler, VISIT_STAGES } from "./profile";

/** Pipeline order, grouped the way a drain passes through them. */
const GROUPS: { name: string; where: string; stages: [string, string][] }[] = [
  { name: "Page", where: "guest webview", stages: [
    ["drain", "pull the delta out of the page"],
    ["fold", "MutationObserver fold (inside drain)"],
  ]},
  { name: "Wire", where: "renderer to sidecar", stages: [
    ["capture", "round trip to /capture"],
    ["transport", "serialisation, socket, queue"],
  ]},
  { name: "Sidecar", where: "its own clock", stages: [
    ["sidecar.decode", "decode the drain"],
    ["sidecar.absorb", "patricia trie"],
    ["sidecar.render", "markdown projection"],
    ["sidecar.lock_wait", "waiting behind the embedder"],
    ["sidecar.store", "write the store"],
    ["sidecar.place", "UMAP placement"],
    ["sidecar.total", "all of the sidecar"],
  ]},
  { name: "Encoder", where: "background worker", stages: [
    ["vector_wait", "until the chunk has a vector"],
  ]},
  { name: "Graph", where: "this pane's neighbour", stages: [
    ["absorb", "graph takes the nodes"],
    ["visible", "until drawn in the frustum"],
  ]},
];

/** Children shown indented under their parent stage. */
const CHILDREN: Record<string, [string, string][]> = {
  "sidecar.store": [
    ["sidecar.ms_prequery", "pre-write reads"],
    ["sidecar.ms_reconcile", "retire stale rows"],
    ["sidecar.ms_addresses", "addresses"],
    ["sidecar.ms_chunks", "chunks"],
    ["sidecar.ms_anchors", "anchors"],
    ["sidecar.ms_contains", "containment edges"],
    ["sidecar.ms_links", "link edges"],
    ["sidecar.ms_freq", "frequency matrix"],
    ["sidecar.ms_mirror", "JSONL checkpoint"],
  ],
  "sidecar.place": [
    ["sidecar.place_ms_read", "read chunks and vectors"],
    // Placement reads positions the projector's stream already computed;
    // it transforms here only what the stream has not reached yet.
    ["sidecar.place_ms_transform", "transform (stream not there yet)"],
    ["sidecar.place_ms_edges", "containment among placed"],
  ],
};

/** Integrity counters, the value that means healthy, and what a bad one means. */
const INTEGRITY: { key: string; label: string; bad: (v: number, h: any) => boolean;
                   why: string }[] = [
  { key: "chunks_empty_md", label: "chunks with empty markdown",
    bad: (v) => v > 50,
    why: "content captured but not stored -- images, search and panels go blank" },
  { key: "addresses_blank_key", label: "addresses with no key",
    bad: (v) => v > 0,
    why: "a line cannot name its element in the page" },
  { key: "anchors_blank_key", label: "anchors to a keyless address",
    bad: (v) => v > 0, why: "right-click cannot resolve to the page" },
  { key: "chunks_without_vector", label: "chunks without a vector",
    bad: (v) => v > 500, why: "cannot be placed until the encoder catches up" },
  { key: "unreadable_addresses", label: "unreadable addresses",
    bad: (v) => v > 0, why: "rows dropped silently on read" },
];

export class ProfileReadout {
  private timer = 0;
  private body!: HTMLElement;
  private side: Record<string, any[]> | null = null;
  private health: any = null;
  private lastSidePoll = 0;

  /** Mounted into `host`, which the corner box owns and shows or hides. */
  constructor(private host: HTMLElement, private sidecar: Sidecar) {}

  async mount() {
    const root = this.host;
    root.empty();
    root.addClass("vertiscope-profile");
    const bar = root.createDiv({ cls: "vertiscope-profile-bar" });
    bar.createEl("span", { text: "Pipeline profile", cls: "vertiscope-profile-title" });
    const reset = bar.createEl("button", { text: "Reset" });
    reset.onclick = async () => {
      profiler().reset();
      await this.sidecar.resetProfile();
      this.side = null;
      await this.pollSidecar(true);
      this.draw();
    };
    this.body = root.createDiv({ cls: "vertiscope-profile-body" });
    await this.pollSidecar(true);
    this.draw();
    // A second is enough to watch drains land and cheap enough to leave
    // running. It does nothing while the pane is hidden -- `draw` checks.
    this.timer = window.setInterval(() => void this.tick(), 1000);
  }

  destroy() {
    window.clearInterval(this.timer);
    this.timer = 0;
  }

  private async tick() {
    // Nothing to redraw while the box is collapsed.
    if (!this.host.isShown()) return;
    await this.pollSidecar(false);
    this.draw();
  }

  /** The sidecar's rings and health, at most every 3 s: they cost a query. */
  private async pollSidecar(force: boolean) {
    const now = performance.now();
    if (!force && now - this.lastSidePoll < 3000) return;
    this.lastSidePoll = now;
    const [side, health] = await Promise.all([
      this.sidecar.profile().catch(() => null),
      this.sidecar.health().catch(() => null),
    ]);
    if (side) this.side = side;
    if (health) this.health = health;
  }

  private draw() {
    const body = this.body;
    if (!body) return;
    body.empty();
    const summary: any = profiler().summary();
    const stages: Record<string, any> = summary.stages || {};
    const e2e = stages["end_to_end"];

    // ---- headline -------------------------------------------------------
    const head = body.createDiv({ cls: "vertiscope-profile-head" });
    const big = head.createDiv({ cls: "vertiscope-profile-e2e" });
    big.createEl("div", { cls: "vertiscope-profile-e2e-value",
      text: e2e ? `${fmt(e2e.p50)}` : "—" });
    big.createEl("div", { cls: "vertiscope-profile-e2e-label",
      text: e2e ? `page to pixels, p50 of ${e2e.n}` : "no drain has reached the screen yet" });
    const outcomes = head.createDiv({ cls: "vertiscope-profile-outcomes" });
    const oc = summary.outcomes || {};
    for (const [k, label] of [["visible", "on screen"], ["nothing_placed", "nothing placed"],
                              ["not_seen", "not seen"], ["no_graph", "no graph"]]) {
      if (!oc[k]) continue;
      const pill = outcomes.createEl("span", { cls: `vertiscope-profile-pill is-${k}`,
        text: `${oc[k]} ${label}` });
      if (k === "not_seen") pill.title = "placed, but never drawn inside the camera frustum";
    }
    if (!summary.traces) {
      outcomes.createEl("span", { cls: "vertiscope-profile-muted",
        text: "browse in the browser cell to record drains" });
    }

    // ---- this page, by stage (PLUGIN_GOAL 91) ------------------------------
    // When each stage first reached the 3D view on the page being browsed, and
    // how long a hover took to paint its panel at each stage. The provenance
    // (the drain trace and the sidecar's own phases, the fit epoch) is on hover.
    const visits = profiler().visits();
    const cur = visits[visits.length - 1];
    if (cur) {
      const strip = body.createDiv({ cls: "vertiscope-profile-stages" });
      strip.createDiv({ cls: "vertiscope-profile-group", text: `this page, by stage · ${cur.url.replace(/^https?:\/\//, "").slice(0, 48)}` });
      const row = strip.createDiv({ cls: "vertiscope-profile-stage-row" });
      for (const st of VISIT_STAGES) {
        const at = cur.marks[st];
        const cell = row.createDiv({ cls: `vertiscope-profile-stage ${at === undefined ? "is-pending" : "is-done"}` });
        cell.createDiv({ cls: "vertiscope-profile-stage-name", text: st });
        cell.createDiv({ cls: "vertiscope-profile-stage-at", text: at === undefined ? "—" : fmt(at) });
        const h = cur.hover[st];
        cell.createDiv({ cls: "vertiscope-profile-stage-hover", text: h ? `hover→panel ${fmt(h.p50)} (${h.n})` : "" });
        const prov = cur.prov[st];
        if (prov) cell.title = Object.entries(prov).filter(([, v]) => v !== undefined && v !== null)
          .map(([k, v]) => `${k}: ${typeof v === "number" ? fmt(v as number) : String(v)}`).join("\n");
      }
    }

    // ---- waterfall --------------------------------------------------------
    const scale = Math.max(1, e2e ? e2e.p50 : this.largestP50(stages));
    const table = body.createDiv({ cls: "vertiscope-profile-waterfall" });
    const header = table.createDiv({ cls: "vertiscope-profile-row is-header" });
    for (const t of ["stage", "", "p50", "p90", "max", "n"]) header.createEl("span", { text: t });
    for (const group of GROUPS) {
      const present = group.stages.filter(([k]) => stages[k]);
      if (!present.length) continue;
      table.createDiv({ cls: "vertiscope-profile-group",
        text: `${group.name} · ${group.where}` });
      for (const [key, label] of present) {
        this.row(table, stages[key], label, scale, 0, key === "sidecar.total");
        for (const [ck, cl] of CHILDREN[key] || []) {
          if (stages[ck]) this.row(table, stages[ck], cl, scale, 1, false);
        }
      }
    }

    // ---- where the slowest stage is -------------------------------------
    const worst = this.slowest(stages);
    if (worst) {
      body.createDiv({ cls: "vertiscope-profile-note",
        text: `Largest single cost at the median: ${worst.label} — ` +
              `${fmt(worst.p50)}${e2e ? `, ${Math.round((worst.p50 / e2e.p50) * 100)}% of page-to-pixels` : ""}.` });
    }

    // ---- the sidecar's background work -----------------------------------
    const bg = body.createDiv({ cls: "vertiscope-profile-section" });
    bg.createEl("h4", { text: "Sidecar background" });
    const embed = this.ring("embed", "ms");
    const place = this.ring("place", "total");
    const layout = (this.side?.layout || []) as any[];
    const warm = ((this.side?.warmup || []) as any[]).slice(-1)[0];
    const lines: string[] = [];
    if (embed) lines.push(`encoder: ${embed.n} batches, p50 ${fmt(embed.p50)}, max ${fmt(embed.max)}`);
    if (place) lines.push(`placement queue: ${place.n} calls, p50 ${fmt(place.p50)}, max ${fmt(place.max)}`);
    // The chunk projector: its stream of batches, and its fits.
    const proj = this.ring("project", "ms");
    const batches = (this.side?.project || []) as any[];
    if (proj) {
      const placed = batches.reduce((a, b) => a + (b.placed || 0), 0);
      const tr = batches.map((b) => b.ms_transform || 0).sort((a, b) => a - b);
      lines.push(`projector stream: ${proj.n} batches, ${placed} chunks transformed, ` +
                 `batch p50 ${fmt(proj.p50)} (transform p50 ${fmt(tr[Math.floor(tr.length / 2)] || 0)})`);
    }
    const fits = (this.side?.projector_fit || []) as any[];
    const lastFit = fits[fits.length - 1];
    if (lastFit) lines.push(`projector fit ${lastFit.epoch}: UMAP on ${lastFit.sample} of ` +
      `${lastFit.chunks} chunks ${fmt(lastFit.ms_fit)}, the rest transformed ${fmt(lastFit.ms_transform)}`);
    if (layout.length) {
      const k: Record<string, number> = {};
      for (const e of layout) k[e.kind] = (k[e.kind] || 0) + 1;
      lines.push(`layout: ${Object.entries(k).map(([a, b]) => `${b} ${a}`).join(", ")}` +
                 (k.fit ? "" : " — no refit since start"));
    }
    if (warm) lines.push(warm.warmed
      ? `startup warmup paid ${fmt(warm.ms)} so no reader does`
      : `startup warmup did not run: ${warm.why || "?"}`);
    if (!lines.length) lines.push("no background work recorded yet");
    for (const l of lines) bg.createEl("div", { text: l, cls: "vertiscope-profile-line" });

    // ---- store integrity ----------------------------------------------------
    const integ = body.createDiv({ cls: "vertiscope-profile-section" });
    integ.createEl("h4", { text: "Store integrity" });
    if (!this.health) {
      integ.createEl("div", { cls: "vertiscope-profile-bad", text: "the sidecar is not answering" });
    } else {
      const h = this.health;
      const total = h.chunks_total;
      if (typeof total === "number") {
        integ.createEl("div", { cls: "vertiscope-profile-line",
          text: `${total.toLocaleString()} chunks, ${h.pages} pages, ` +
                `${(h.chunks_with_image ?? 0).toLocaleString()} chunks show an image` });
      }
      for (const c of INTEGRITY) {
        const v = h[c.key];
        if (typeof v !== "number") continue;
        const bad = c.bad(v, h);
        const row = integ.createDiv({ cls: `vertiscope-profile-integ ${bad ? "is-bad" : "is-ok"}` });
        row.createEl("span", { cls: "vertiscope-profile-dot", text: bad ? "●" : "○" });
        row.createEl("span", { text: `${v.toLocaleString()} ${c.label}` });
        if (bad) row.createEl("span", { cls: "vertiscope-profile-why", text: ` — ${c.why}` });
      }
    }

    // ---- recent drains ---------------------------------------------------
    const recent = profiler().list().slice(-8).reverse();
    if (recent.length) {
      const sec = body.createDiv({ cls: "vertiscope-profile-section" });
      sec.createEl("h4", { text: "Recent drains" });
      for (const t of recent) {
        const st = t.stages || {};
        const out = String((t.facts || {}).outcome || "?");
        const why = (t.facts || {}).why ? ` (${(t.facts || {}).why})` : "";
        const top = this.slowest(Object.fromEntries(
          Object.entries(st).map(([k, v]) => [k, { p50: v, n: 1 }])));
        sec.createEl("div", { cls: `vertiscope-profile-drain is-${out}`,
          text: `${shortUrl(t.url)} · ${out}${why}` +
                (st.end_to_end ? ` · ${fmt(st.end_to_end)}` : "") +
                (top ? ` · slowest ${top.label} ${fmt(top.p50)}` : "") });
      }
    }
  }

  private row(parent: HTMLElement, s: any, label: string, scale: number,
              depth: number, isTotal: boolean) {
    const r = parent.createDiv({ cls: `vertiscope-profile-row depth-${depth}${isTotal ? " is-total" : ""}` });
    r.createEl("span", { cls: "vertiscope-profile-label", text: label });
    const track = r.createEl("span", { cls: "vertiscope-profile-track" });
    const bar = track.createEl("span", { cls: "vertiscope-profile-barfill" });
    bar.style.width = `${Math.min(100, (s.p50 / scale) * 100)}%`;
    r.createEl("span", { text: fmt(s.p50) });
    r.createEl("span", { text: fmt(s.p90) });
    r.createEl("span", { text: fmt(s.max) });
    r.createEl("span", { cls: "vertiscope-profile-muted", text: String(s.n) });
  }

  /** The costliest leaf stage at the median; totals and containers excluded. */
  private slowest(stages: Record<string, any>): { label: string; p50: number } | null {
    const skip = new Set(["end_to_end", "sidecar.total", "capture", "sidecar.store",
                          "sidecar.place", "drain"]);
    let best: { label: string; p50: number } | null = null;
    const labels: Record<string, string> = {};
    for (const g of GROUPS) for (const [k, l] of g.stages) labels[k] = l;
    for (const kids of Object.values(CHILDREN)) for (const [k, l] of kids) labels[k] = l;
    for (const [k, v] of Object.entries(stages)) {
      if (skip.has(k) || !labels[k] || typeof v?.p50 !== "number") continue;
      if (!best || v.p50 > best.p50) best = { label: labels[k], p50: v.p50 };
    }
    return best;
  }

  private largestP50(stages: Record<string, any>): number {
    let m = 0;
    for (const v of Object.values(stages)) if (typeof v?.p50 === "number") m = Math.max(m, v.p50);
    return m;
  }

  private ring(name: string, field: string) {
    const rows = ((this.side?.[name] || []) as any[])
      .map((r) => r[field]).filter((x) => typeof x === "number").sort((a, b) => a - b);
    if (!rows.length) return null;
    return { n: rows.length, p50: rows[Math.floor((rows.length - 1) / 2)],
             max: rows[rows.length - 1] };
  }
}

function fmt(ms: number | null | undefined): string {
  if (typeof ms !== "number" || !Number.isFinite(ms)) return "—";
  if (ms >= 1000) return `${(ms / 1000).toFixed(2)} s`;
  if (ms >= 10) return `${Math.round(ms)} ms`;
  return `${ms.toFixed(1)} ms`;
}

function shortUrl(url: string): string {
  try {
    const u = new URL(url);
    const path = u.pathname.length > 28 ? "…" + u.pathname.slice(-27) : u.pathname;
    return u.host.replace(/^www\./, "") + path;
  } catch {
    return url.slice(0, 40);
  }
}
