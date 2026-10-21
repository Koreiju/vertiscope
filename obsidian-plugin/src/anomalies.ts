/**
 * What is WRONG in the app right now, measured where the reader meets it
 * (2026-10-06: "Please make sure the design of the mcp server is also just as
 * observant for these kinds of things").
 *
 * The reader reported, in one evening: phantom nodes and stale nodes and
 * links; streamed chunks on a sphere instead of a tree; a clicked panel
 * rendering nothing; pictures that do not load; duplicate pictures; the
 * tracked overlay sliding off the page; laggy overlays. Each is a number
 * here, computed by the app's own objects -- the graph view, the browser
 * cell, the store through the sidecar -- so the MCP server, a live check and
 * a probe all read the SAME instrument rather than re-implementing it (a
 * check that reimplements what it measures can be wrong in either direction).
 *
 * In trie terms: every count is a comparison between what is DRAWN and what
 * the trie holds -- a drawn node whose cid is not a leaf of its url's subtree
 * is a phantom; a streamed node whose trie parent is not drawn hangs from the
 * root instead (the sphere); a panel is the leaf's rendering.
 */
import { treeVerdict } from "./treeguard";
import { isolation } from "./isolate";

const cidCache = new Map<string, { at: number; cids: Set<string> }>();

function q(xs: number[], p: number): number | null {
  if (!xs.length) return null;
  const s = [...xs].sort((a, b) => a - b);
  return Math.round(s[Math.min(s.length - 1, Math.floor(p * s.length))] * 10) / 10;
}

function images(root: ParentNode): { total: number; broken: number; sample: string[] } {
  const out = { total: 0, broken: 0, sample: [] as string[] };
  root.querySelectorAll("img").forEach((i: any) => {
    out.total++;
    if (i.complete && !(i.naturalWidth > 0)) {
      out.broken++;
      if (out.sample.length < 3) out.sample.push(String(i.currentSrc || i.src || "").slice(-80));
    }
  });
  return out;
}

export async function anomalies(app: any, profile: () => any[]): Promise<any> {
  const g: any = app.workspace.getLeavesOfType("vertiscope-graph-view")[0]?.view;
  const b: any = app.workspace.getLeavesOfType("vertiscope-browser-view")[0]?.view;
  if (!g || !g.graph) return { error: "no graph view" };
  const d = g.graph.graphData();
  const end = (x: any) => (typeof x === "object" && x ? x.id : x);
  const ids = new Set<string>(d.nodes.map((n: any) => n.id));
  const now = Date.now();

  // ---- drawn vs stored: phantoms, orphans, dangling links ----------------
  const urls = [...new Set<string>(d.nodes.filter((n: any) => !n.force && n.level !== "page" && n.url
    && !String(n.id).startsWith("path:")).map((n: any) => n.url))];
  await Promise.all(urls.map(async (u) => {
    const c = cidCache.get(u);
    if (c && now - c.at < 2000) return;
    try { cidCache.set(u, { at: now, cids: new Set(await g.sidecar.pageCids(u)) }); } catch { /* no answer */ }
  }));
  const census = { page: 0, path: 0, force_pending: 0, force_orphan: 0, stored: 0, phantom: 0 };
  const phantoms: any[] = [];
  for (const n of d.nodes) {
    if (n.level === "page") { census.page++; continue; }
    if (String(n.id).startsWith("path:")) { census.path++; continue; }
    if (n.force) { if (g.forceSpecs.has(n.id)) census.force_pending++; else census.force_orphan++; continue; }
    let c = cidCache.get(n.url);
    if (c && !c.cids.has(n.id) && now - c.at > 0) {
      // A miss is re-asked once before it is called a phantom: a chunk
      // stored a moment ago is not one.
      try { c = { at: Date.now(), cids: new Set(await g.sidecar.pageCids(n.url)) }; cidCache.set(n.url, c); } catch { /* keep */ }
    }
    if (!c) continue;
    if (c.cids.has(n.id)) census.stored++;
    else { census.phantom++; if (phantoms.length < 5) phantoms.push({ id: n.id, url: String(n.url).slice(-60) }); }
  }
  const dangling = d.links.filter((l: any) => !ids.has(end(l.source)) || !ids.has(end(l.target))).length;
  const tree = treeVerdict(d.nodes, d.links);

  // ---- the streamed nodes of the browsed page: tree or sphere -------------
  let stream: any = null;
  const url = b ? String(b.webview?.getURL?.() || "").split("#")[0] : "";
  const page = d.nodes.find((n: any) => n.level === "page" && String(n.url || "").split("#")[0] === url);
  const fs = d.nodes.filter((n: any) => n.force && n.level !== "page" && String(n.url || "").split("#")[0] === url);
  if (page && fs.length) {
    const r = fs.map((n: any) => Math.hypot(n.x - page.x, n.y - page.y, (n.z || 0) - (page.z || 0))).filter(Number.isFinite);
    const m = r.reduce((a: number, x: number) => a + x, 0) / Math.max(1, r.length);
    const sd = Math.sqrt(r.reduce((a: number, x: number) => a + (x - m) ** 2, 0) / Math.max(1, r.length));
    const fsIds = new Set(fs.map((n: any) => n.id));
    const onPage = d.links.filter((l: any) => end(l.source) === page.id && fsIds.has(end(l.target))).length;
    const specs = [...g.forceSpecs.values()].filter((s: any) => String(s.url || "").split("#")[0] === url && s.parent);
    stream = { nodes: fs.length, hung_on_page: onPage, share_on_page: +(onPage / fs.length).toFixed(2),
               radius_cv: +(sd / (m || 1)).toFixed(3), specs_with_parent: specs.length,
               parent_drawn: specs.filter((s: any) => ids.has(s.parent)).length };
  }

  // ---- panels: what each open billboard shows ----------------------------
  const panels = [...g.billboards.values()].map((e: any) => {
    const body = e.el.querySelector(".vertiscope-bb-body") as HTMLElement | null;
    const im = body ? images(body) : { total: 0, broken: 0, sample: [] };
    // The page form renders in an iframe: its text and pictures count too
    // (innerText does not reach into a frame -- a filled page-form panel
    // read as empty, 2026-10-07).
    let frameText = 0;
    if (body) body.querySelectorAll("*").forEach((x: any) => {
      if (x.shadowRoot) { const s = images(x.shadowRoot); im.total += s.total; im.broken += s.broken; im.sample.push(...s.sample); }
      if (x.tagName === "IFRAME") {
        try {
          const doc = x.contentDocument;
          if (doc && doc.body) {
            frameText += (doc.body.innerText || "").trim().length;
            const s = images(doc); im.total += s.total; im.broken += s.broken; im.sample.push(...s.sample);
          }
        } catch { /* cross-origin frame */ }
      }
    });
    const text = (body ? (body.innerText || "").trim().length : 0) + frameText;
    const srcs = body ? Array.from(body.querySelectorAll("img")).map((i: any) => i.currentSrc || i.src) : [];
    return { id: e.node.id, form: e.form || (e.surface ? "surface" : "?"), empty: !text && !im.total,
             text, images: im.total, broken: im.broken, duplicate_images: srcs.length - new Set(srcs).size,
             address: (e.el.querySelector(".vertiscope-bb-addr")?.textContent || "").slice(0, 160) };
  });
  const log = (g.billboardLog || []).slice(-20);

  // ---- the overlay: boxes outside the cell -------------------------------
  let overlay: any = null;
  if (b) {
    const cell = (b.browserWrap || b.webview).getBoundingClientRect();
    const boxes = Array.from(document.querySelectorAll(".vertiscope-chunk-outline,.vertiscope-diff-box,.vertiscope-chunk-pin"))
      .filter((e: any) => e.offsetParent !== null && getComputedStyle(e).display !== "none");
    let outside = 0, partly = 0;
    for (const e of boxes) {
      const r = (e as HTMLElement).getBoundingClientRect();
      if (r.width < 1 || r.height < 1) continue;
      const fully = r.right < cell.left || r.left > cell.right || r.bottom < cell.top || r.top > cell.bottom;
      const over = r.left < cell.left - 2 || r.right > cell.right + 2 || r.top < cell.top - 2 || r.bottom > cell.bottom + 2;
      if (fully) outside++; else if (over) partly++;
    }
    overlay = { boxes: boxes.length, outside, partly };
  }

  // ---- latency, from the app's own traces --------------------------------
  const tr = profile().filter((x: any) => x.stages && x.stages.mutation_to_host !== undefined).slice(-60);
  const st = (k: string) => tr.map((x: any) => x.stages[k]).filter((v: any) => typeof v === "number");
  const latency = { traces: tr.length, pushed: tr.filter((x: any) => x.stages.push_transit !== undefined).length,
    mutation_to_host_p50: q(st("mutation_to_host"), .5), mutation_to_host_p90: q(st("mutation_to_host"), .9),
    fold_p50: q(st("fold"), .5), drain_to_overlay_p50: q(st("drain_to_overlay"), .5),
    drain_to_overlay_p90: q(st("drain_to_overlay"), .9), drain_to_3d_p50: q(st("drain_to_3d"), .5) };

  const pt = g.panelTimes || { first_paint: [], page_paint: [], close: [] };
  const panelSpeed = { opened: pt.first_paint.length,
    first_paint_p50: q(pt.first_paint, .5), first_paint_p90: q(pt.first_paint, .9),
    page_paint_p50: q(pt.page_paint, .5), page_paint_p90: q(pt.page_paint, .9),
    close_p50: q(pt.close, .5), close_p90: q(pt.close, .9),
    focus: g.focusStats || null };
  const problems: string[] = [];
  if (panelSpeed.opened >= 3 && (panelSpeed.first_paint_p90 ?? 0) > 300) problems.push(`panels slow to show: first paint p90 ${panelSpeed.first_paint_p90} ms`);
  if (pt.close.length >= 3 && (panelSpeed.close_p90 ?? 0) > 250) problems.push(`hover panels slow to close: p90 ${panelSpeed.close_p90} ms`);
  if (census.phantom) problems.push(`${census.phantom} phantom node(s): drawn, not in the store`);
  if (census.force_orphan) problems.push(`${census.force_orphan} streaming node(s) with no pending spec`);
  if (dangling) problems.push(`${dangling} link(s) to an undrawn node`);
  if (!tree.ok) problems.push(`not a tree: ${tree.multiParent} multi-parent, ${tree.cyclic} cyclic, ${tree.crossUrl} cross-url, ${tree.forests} second root(s)`);
  if (stream && stream.nodes >= 6 && stream.share_on_page > 0.8) problems.push(`stream is a STAR: ${stream.hung_on_page}/${stream.nodes} hang on the page node (${stream.parent_drawn}/${stream.specs_with_parent} trie parents drawn)`);
  for (const p of panels) {
    if (p.empty) problems.push(`panel ${p.id} is empty (${p.form})`);
    if (p.broken) problems.push(`panel ${p.id}: ${p.broken}/${p.images} image(s) failed to load`);
    if (p.duplicate_images) problems.push(`panel ${p.id}: ${p.duplicate_images} duplicate image(s)`);
  }
  const emptyOpened = log.filter((x: any) => x.empty).length;
  if (emptyOpened) problems.push(`${emptyOpened} of the last ${log.length} panels opened empty`);
  if (overlay && (overlay.outside || overlay.partly)) problems.push(`overlay: ${overlay.outside} box(es) outside the cell, ${overlay.partly} crossing its edge`);
  if (latency.traces >= 5 && (latency.drain_to_overlay_p50 ?? 0) > 16) problems.push(`overlay latency p50 ${latency.drain_to_overlay_p50} ms after the drain`);
  if (latency.traces >= 5 && latency.pushed === 0) problems.push("no drain was PUSHED: the overlay waits for the poll");

  return { at: now, browsing: url, nodes: d.nodes.length, links: d.links.length, census, phantoms, dangling,
           tree: { ok: tree.ok, multiParent: tree.multiParent, cyclic: tree.cyclic, crossUrl: tree.crossUrl,
                   forests: tree.forests, sample: tree.sample.slice(0, 3) },
           stream, panels, opened: log, panel_speed: panelSpeed, overlay, latency, isolation: { ...isolation },
           pushed_total: b ? b.pushedPayloads : null, problems };
}
