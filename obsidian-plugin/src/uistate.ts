/**
 * The interface, as a data structure.
 *
 * **Why this exists.** Every live check in `confirm.mjs` read JavaScript
 * properties: `graphData().nodes.length`, `n.fitX`, `el.style.left`. Those
 * describe what the backend INTENDED. They passed -- G-4 "nodes are
 * discernible, not a clump", G-21 "nodes never overlap", G-5 "every node is
 * on screen" -- while the pane showed 558 nodes piled into the bottom-left
 * quadrant with a fifth of them off the canvas entirely. A fit can be
 * perfectly spread in fit space and still project to a blob.
 *
 * So the plugin reports its own surfaces, in the terms a READER meets them:
 * screen pixels, visibility, and what is actually drawn. It lives in the
 * plugin rather than in the harness for three reasons:
 *
 *   * the views know their own state, and the harness would have to guess
 *     at private fields to reconstruct it;
 *   * it stays version-controlled beside the UI it describes, so a renamed
 *     field breaks the build rather than silently reporting `undefined`;
 *   * it is ONE round trip. The harness was making a dozen `evaluate` calls
 *     per check and paying for each one.
 *
 * Exposed on `window.__vertiscopeUI` so anything that can reach the renderer --
 * `cdp.mjs`, `confirm.mjs`, an MCP server on the debug port -- can ask the
 * same question and get the same answer.
 */

import type { App } from "obsidian";

export const GRAPH_VIEW = "vertiscope-graph-view";
export const BROWSER_VIEW = "vertiscope-browser-view";
export const CHUNK_VIEW = "vertiscope-chunk-view";
export const TERMINAL_VIEW = "vertiscope-terminal-view";
export const PROFILE_VIEW = "vertiscope-profile-view";

/** Is this element actually drawn, and where? */
function drawn(el: HTMLElement | null | undefined) {
  if (!el) return { exists: false as const };
  const r = el.getBoundingClientRect();
  const cs = getComputedStyle(el);
  const win = el.ownerDocument?.defaultView;
  const vw = win?.innerWidth ?? 0;
  const vh = win?.innerHeight ?? 0;
  return {
    exists: true as const,
    // Rounded: a sub-pixel difference is not a fact anyone is asking about,
    // and it makes two snapshots comparable.
    rect: [Math.round(r.left), Math.round(r.top),
           Math.round(r.width), Math.round(r.height)] as number[],
    display: cs.display,
    visibility: cs.visibility,
    opacity: Number(cs.opacity),
    // **Drawn is not the same as present.** A leaf in a background tab has
    // a box of 0x0; a detached one has none at all. Both read as "exists"
    // to anything looking at the object graph.
    drawn: r.width > 1 && r.height > 1 &&
           cs.display !== "none" && cs.visibility !== "hidden" &&
           Number(cs.opacity) > 0.01 &&
           r.right > 0 && r.bottom > 0 && r.left < vw && r.top < vh,
  };
}

/**
 * The projector, measured where the reader sees it: SCREEN PIXELS.
 *
 * `fitX/fitY/fitZ` is the fit's own space and says nothing about the
 * picture; the renderer relaxes with forces into `x/y/z` and then projects
 * through a camera. This reports the end of that pipeline, and keeps the
 * fit-space drift beside it so the two can be told apart -- a clump whose
 * drift is zero is a bad FIT, and a clump whose drift is large is a bad
 * RELAXATION, and they need different fixes.
 */
function pct(xs: number[], q: number): number | null {
  if (!xs || !xs.length) return null;
  const s = xs.slice().sort((a, b) => a - b);
  return Math.round(s[Math.min(s.length - 1, Math.floor(q * s.length))] * 10) / 10;
}

/** Force-tree nodes with more than one parent link -- must be 0 (a tree). */
function multiParent(links: any[]): number {
  const seen = new Map<string, number>();
  for (const l of links || []) {
    if (!l.force) continue;
    const t = typeof l.target === "object" ? l.target.id : l.target;
    seen.set(t, (seen.get(t) || 0) + 1);
  }
  return [...seen.values()].filter((n) => n > 1).length;
}

function graphState(view: any) {
  const g = view?.graph;
  // The representation and its history (`G-89`): what the phase contracts
  // are checked against, present whether or not anything is drawn yet.
  const phase = {
    layout_mode: view?.layoutMode ?? null,
    phase_log: (view?.phaseLog || []).slice(-20),
    force: view?.forceStats ? {
      drains: view.forceStats.drains, added: view.forceStats.added,
      removed: view.forceStats.removed, reparented: view.forceStats.reparented,
      ms_p95: pct(view.forceStats.ms, 0.95), ms_max: Math.max(0, ...view.forceStats.ms),
      // O(delta), judged per node the drain touched, and on small drains.
      // Per node on LARGE drains only: on a one-node drain the fixed cost
      // is the whole cost and reads as "per node".
      ms_per_node_p95: pct((view.forceStats.sized || []).filter((x: any) => x[1] >= 50)
        .map((x: any) => x[0] / x[1]), 0.95),
      small_drain_ms_p95: pct((view.forceStats.sized || []).filter((x: any) => x[1] > 0 && x[1] < 50)
        .map((x: any) => x[0]), 0.95),
      largest_drain: Math.max(0, ...(view.forceStats.sized || []).map((x: any) => x[1])),
      // Calm between updates: how far the ALREADY-drawn streaming nodes moved
      // from one update to the next (scene units per node).
      jitter_p50: pct(view.forceStats.jitter || [], 0.5), jitter_p95: pct(view.forceStats.jitter || [], 0.95),
      nodes: g ? g.graphData().nodes.filter((n: any) => n.force).length : 0,
      multi_parent: g ? multiParent(g.graphData().links) : 0,
    } : null,
    // Addendum IX's stream, stage by stage: drawn -> saved -> folded into
    // the root -> placed by the fit; out-of-order counts; projected chunks'
    // distance from their fit position (G-92, G-97).
    lifecycle: typeof view?.lifecycleState === "function" ? view.lifecycleState() : null,
    render: typeof view?.renderStats === "function" ? view.renderStats() : null,
    // D-38: nodes caught with a non-finite / runaway position before an octree.
    octree_skips: view?.octreeSkips || null,
    // Right-click on a page node (G-110): which pages the reader folded into
    // their page node, which they opened, and every toggle so far.
    page_toggle: view ? {
      collapsedByReader: [...(view.collapsedByReader || [])],
      openedByReader: [...(view.openedByReader || [])],
      toggles: (view.toggled || []).slice(-10),
      planted: !!view.plantNoToggle,
    } : null,
    calm: view?.calmStats ? { ...view.calmStats, planted: !!view.plantNoCalm } : null,
    glide: view?.glideStats ? { ...view.glideStats, planted: !!view.plantTeleport } : null,
    // G-109: the central diff applied to this view (retired / renamed / known),
    // and the last stale-stored reading (drawn chunks the store no longer has).
    diff: view?.diffStats ? { ...view.diffStats, planted: !!view.plantNoDiff,
                              stale: view.staleDetail || null } : null,
    governor: view?.governorStats ? { ...view.governorStats, planted: !!view.plantNoGovernor } : null,
    non_finite: view ? { count: view.nonFiniteCount || 0, first: (view.nonFinite || []).slice(0, 5),
                         by_force: (view.nanBy || []).slice(0, 10) } : null,
  };
  if (!g) return { open: true, fitted: false, ...phase };

  const nodes = g.graphData().nodes as any[];
  const links = g.graphData().links as any[];
  const w = g.width(), h = g.height();
  const rel = g.nodeRelSize();

  // **A radius in GRAPH units cannot be compared to a gap in PIXELS.**
  //
  // The first version of this did exactly that: `cbrt(val) * nodeRelSize`
  // is a world-space radius, and it was tested against a screen-space
  // nearest-neighbour distance. The two differ by the projection, which is
  // a factor of several hundred here, so every node read as overlapping.
  // It is the cumulative-`repairMs` mistake wearing different clothes: two
  // numbers that look comparable and are not.
  //
  // A sphere of world radius r at distance d from a perspective camera
  // projects to a screen radius of `r * (H/2) / (d * tan(vfov/2))`. The
  // camera's own position and fov are used, not a guess.
  const cam: any = g.camera();
  const vfov = ((cam?.fov ?? 50) * Math.PI) / 180;
  const halfH = h / 2;
  const tanV = Math.tan(vfov / 2) || 1e-6;
  const camPos = cam?.position ?? { x: 0, y: 0, z: 0 };

  const pts: { x: number; y: number; on: boolean; r: number }[] = [];
  let noCoords = 0;
  for (const n of nodes) {
    let p: any = null;
    try { p = g.graph2ScreenCoords(n.x, n.y, n.z); } catch { /* not projectable */ }
    if (!p || !Number.isFinite(p.x) || !Number.isFinite(p.y)) { noCoords++; continue; }
    // The world radius, from the application's own sizing. Reimplementing
    // it is how G-21 once invented 49 overlapping pairs.
    const sphere = Math.cbrt(Math.max(n.val ?? 1, 1e-9)) * rel;
    const world = (n.image && n.image.src) ? sphere * 1.75 : sphere;
    const d = Math.hypot((n.x ?? 0) - camPos.x, (n.y ?? 0) - camPos.y,
                         (n.z ?? 0) - camPos.z) || 1e-6;
    pts.push({
      x: p.x, y: p.y,
      on: p.x >= 0 && p.y >= 0 && p.x < w && p.y < h,
      r: (world * halfH) / (d * tanV),
    });
  }

  // **In front of the camera, and inside the frustum.**
  //
  // `graph2ScreenCoords` projects happily through the camera plane: a node
  // BEHIND the viewer comes back with ordinary-looking pixel coordinates,
  // so `on_screen` counted 97 of 97 while the pane was blank. Normalised
  // device coordinates do not have that hole -- everything visible lands
  // in the unit cube, and z outside [-1, 1] is beyond the near or far
  // plane, which is exactly what "the camera ended up inside the cloud"
  // looks like in numbers.
  //
  // Done with the camera's own matrices rather than `THREE.Vector3`:
  // 3d-force-graph bundles three.js, so there is no global to construct
  // from and the tidy version reported -1 for "cannot tell".
  let inFrustum = 0;
  let behind = 0;
  try {
    const camera: any = g.camera();
    camera.updateMatrixWorld?.();
    const proj = camera.projectionMatrix?.elements;
    const view = camera.matrixWorldInverse?.elements;
    if (!proj || !view) throw new Error("no matrices");
    // Column-major, as three.js stores them: m[col * 4 + row].
    const mul = (m: number[], v: number[]) => [
      m[0]*v[0] + m[4]*v[1] + m[8]*v[2] + m[12]*v[3],
      m[1]*v[0] + m[5]*v[1] + m[9]*v[2] + m[13]*v[3],
      m[2]*v[0] + m[6]*v[1] + m[10]*v[2] + m[14]*v[3],
      m[3]*v[0] + m[7]*v[1] + m[11]*v[2] + m[15]*v[3],
    ];
    for (const n of nodes) {
      const eye = mul(view, [n.x ?? 0, n.y ?? 0, n.z ?? 0, 1]);
      const clip = mul(proj, eye);
      const w = clip[3];
      // w <= 0 is the whole point: the node is at or behind the camera,
      // and a screen projection still hands back tidy-looking pixels.
      if (!(w > 0)) { behind += 1; continue; }
      const x = clip[0] / w, y = clip[1] / w, z = clip[2] / w;
      if (Math.abs(x) <= 1 && Math.abs(y) <= 1 && z >= -1 && z <= 1) {
        inFrustum += 1;
      }
    }
  } catch { inFrustum = -1; behind = -1; }

  const on = pts.filter((p) => p.on);
  const xs = on.map((p) => p.x), ys = on.map((p) => p.y);
  const box = on.length
    ? [Math.round(Math.min(...xs)), Math.round(Math.min(...ys)),
       Math.round(Math.max(...xs)), Math.round(Math.max(...ys))]
    : null;

  // Nearest neighbour in pixels, over a sample. O(n^2) is fine at 400 and
  // the median is what tells a cloud from a clump.
  const sample = on.slice(0, 400);
  const gaps: number[] = [];
  let touching = 0;
  for (let i = 0; i < sample.length; i++) {
    let best = Infinity;
    let nearest_r = 0;
    for (let j = 0; j < sample.length; j++) {
      if (i === j) continue;
      const d = Math.hypot(sample[i].x - sample[j].x, sample[i].y - sample[j].y);
      if (d < best) { best = d; nearest_r = sample[j].r; }
    }
    if (Number.isFinite(best)) {
      gaps.push(best);
      // Both in pixels now. Closer than the sum of the two radii is an
      // overlap a reader sees as one shape.
      if (best < sample[i].r + nearest_r) touching++;
    }
  }
  gaps.sort((a, b) => a - b);
  const at = (q: number) => gaps.length
    ? Math.round(gaps[Math.min(gaps.length - 1, Math.floor(gaps.length * q))] * 10) / 10
    : null;

  const drift: number[] = [];
  for (const n of nodes) {
    if (n.fitX === undefined) continue;
    drift.push(Math.hypot(n.x - n.fitX, n.y - n.fitY, n.z - n.fitZ));
  }
  drift.sort((a, b) => a - b);

  // **Ground truth: what the renderer actually drew.**
  //
  // Everything above is computed from node coordinates, and
  // `graph2ScreenCoords` answers for nodes that are never rendered -- it
  // reported 97 of 97 "on screen" while the canvas was empty, which is the
  // same mistake as reading `fitX`, one level further in. Two independent
  // checks, because either alone can lie:
  //
  //   * the SCENE: how many objects three.js is actually carrying and how
  //     many are flagged visible. A layout that never built meshes shows up
  //     here as zero and nowhere else.
  //   * the PIXELS: a coarse sample of the drawn canvas. A scene full of
  //     meshes that the camera cannot see still paints nothing, and only
  //     the framebuffer knows.
  let scene_objects: number | null = null;
  let scene_visible: number | null = null;
  try {
    const root = g.scene ? g.scene() : null;
    if (root) {
      let total = 0, shown = 0;
      root.traverse((o: any) => {
        // Meshes, sprites and lines: the things a reader can see. Groups
        // and the scene itself are scaffolding.
        if (o.isMesh || o.isSprite || o.isLine || o.isPoints) {
          total += 1;
          if (o.visible !== false) shown += 1;
        }
      });
      scene_objects = total;
      scene_visible = shown;
    }
  } catch { /* no scene access in this build */ }

  // **Not the framebuffer.** Sampling the canvas was the obvious ground
  // truth and it does not work: a WebGL drawing buffer is not preserved
  // after presentation unless the context was created with
  // `preserveDrawingBuffer`, so `readPixels` returns zeroes on a pane that
  // is visibly full of nodes. It read 0% painted against a screenshot
  // showing 97 of them, which would have been a worse lie than the one it
  // was meant to catch.
  //
  // The frustum test below is the honest substitute, and it catches the
  // case that actually happened: a camera placed inside the cloud, with
  // nodes BEHIND it still getting plausible pixel coordinates.

  const status = view.containerEl?.querySelector(".vertiscope-graph-status");
  return {
    open: true,
    fitted: true,
    ...phase,
    canvas: [w, h],
    nodes: nodes.length,
    links: links.length,
    on_screen: on.length,
    off_screen: pts.length - on.length,
    unprojectable: noCoords,
    // The cloud's bounding box as a share of the canvas. A picture using a
    // third of its pane is not "normalized so nodes are discernible".
    spread_pct: box
      ? Math.round(((box[2] - box[0]) * (box[3] - box[1])) / (w * h) * 1000) / 10
      : 0,
    bbox: box,
    radius_px_p50: (() => {
      const rs = on.map((q) => q.r).sort((a, b) => a - b);
      return rs.length ? Math.round(rs[Math.floor(rs.length / 2)] * 10) / 10 : null;
    })(),
    gap_px_p10: at(0.10),
    gap_px_p50: at(0.50),
    overlapping: touching,
    sampled: sample.length,
    // Zero drift with a clumped picture means the FIT is the clump.
    fit_drift_p50: drift.length ? Math.round(drift[Math.floor(drift.length / 2)]) : null,
    fit_drift_max: drift.length ? Math.round(drift[drift.length - 1]) : null,
    // Computed-vs-drawn. When `on_screen` is high and these are zero, the
    // arithmetic is fine and the reader is looking at nothing.
    scene_objects, scene_visible, in_frustum: inFrustum, behind_camera: behind,
    status: status ? (status.textContent || "").trim() : null,
    billboards: view.containerEl
      ? view.containerEl.querySelectorAll(".vertiscope-billboard").length : 0,
  };
}

function browserState(view: any) {
  let url = "", guest: number[] | null = null;
  try { url = view.webview.getURL(); } catch { url = "not ready"; }
  return {
    open: true,
    url,
    live: !!view.live,
    // The page is always the surface (`G-82`); the side holds the pins.
    side_open: !!(view.markdownWrap && view.markdownWrap.style.display !== "none"),
    pins: view.pinnedState ? view.pinnedState().length : 0,
    webview: drawn(view.webview),
    guest_viewport: guest,
    last_scan: view.lastScan || null,
    status: view.status ? (view.status.textContent || "").trim() : null,
  };
}

function chunkPanelState(view: any) {
  const root = view?.containerEl as HTMLElement | undefined;
  const host = root?.querySelector(".vertiscope-html-host") as any;
  const sr = host?.shadowRoot;
  const inner = sr?.querySelector(".vertiscope-html");
  const pre = root?.querySelector(".vertiscope-md");
  return {
    open: true,
    cid: view?.cid || "",
    // Which FACE is drawn. "The panel updated" does not say which.
    surface: host ? "interactive" : (pre ? "markdown" : "none"),
    // Reached through the plugin's OWN shadow root, which is open. The
    // chunk's text is not in `containerEl.textContent` at all.
    rendered_chars: inner
      ? (inner.textContent || "").trim().length
      : (pre ? (pre.textContent || "").trim().length : 0),
    host: drawn(host),
  };
}

/** Everything a reader could be looking at, in one object. */
export function uiState(app: App) {
  const leavesOf = (type: string) => app.workspace.getLeavesOfType(type);
  const paneOf = (type: string) => {
    const leaf: any = leavesOf(type)[0];
    if (!leaf) return { open: false, deferred: false };
    return {
      open: true,
      // A deferred leaf hands back a STUB with none of the view's methods.
      // Nine checks once failed with "cannot read graphData of undefined"
      // and it was this, not a broken projector.
      deferred: !!leaf.isDeferred,
      active: app.workspace.getActiveViewOfType?.(leaf.view?.constructor) === leaf.view,
      container: drawn(leaf.view?.containerEl),
    };
  };

  const out: Record<string, any> = {
    at: Date.now(),
    window: [window.innerWidth, window.innerHeight],
    /**
     * **Whether the window was even awake when this was taken.**
     *
     * A minimised Obsidian throttles `requestAnimationFrame` to about one
     * tick every two seconds, so every liveness reading taken through it is
     * a reading of the window manager. Measured on the same pane, seconds
     * apart: **0 rendered frames in 2 s** while hidden, **407** once
     * `Emulation.setFocusEmulationEnabled` woke it. Without this field that
     * first number reads as a dead render loop, and it was very nearly
     * filed as one.
     *
     * Geometry is unaffected -- node positions are real either way -- so
     * this qualifies the rates and the frame counts, not the census.
     */
    awake: {
      hidden: document.hidden,
      visibility: document.visibilityState,
      focused: document.hasFocus(),
    },
    panes: {
      graph: paneOf(GRAPH_VIEW),
      browser: paneOf(BROWSER_VIEW),
      chunk: paneOf(CHUNK_VIEW),
      terminal: paneOf(TERMINAL_VIEW),
      profile: paneOf(PROFILE_VIEW),
    },
  };
  // What the profile readout is SHOWING, read off its DOM, so a check can
  // compare the displayed figures with the profiler's own summary instead
  // of trusting that it drew what it was given. It lives in the browser
  // cell's corner box now (`G-76`), not in a pane of its own.
  const bl0: any = leavesOf(BROWSER_VIEW)[0];
  const profileEl: HTMLElement | null = bl0 && !bl0.isDeferred && bl0.view?.pipebox
    ? bl0.view.pipebox.el.querySelector(".vertiscope-pipebox-profile") : null;
  if (profileEl) {
    const el: HTMLElement | undefined = profileEl;
    const val = el?.querySelector(".vertiscope-profile-e2e-value")?.textContent || null;
    const rows = el ? Array.from(el.querySelectorAll(".vertiscope-profile-row:not(.is-header)"))
      .map((r) => Array.from(r.children).map((c) => (c.textContent || "").trim())) : [];
    const integ = el ? Array.from(el.querySelectorAll(".vertiscope-profile-integ"))
      .map((r) => ({ bad: r.classList.contains("is-bad"), text: (r.textContent || "").trim() })) : [];
    out.profile = { e2e_shown: val, rows: rows.length, stage_rows: rows.slice(0, 40),
                    integrity: integ };
  }
  // The pipeline box over the browser cell, and the hovered chunk's outline,
  // read off the DOM the reader sees.
  const bl: any = leavesOf(BROWSER_VIEW)[0];
  const pb = bl && !bl.isDeferred && bl.view ? bl.view.pipebox : null;
  if (pb && pb.el) {
    const outline = bl.view.containerEl.querySelector(".vertiscope-chunk-outline") as HTMLElement | null;
    const box = pb.el.getBoundingClientRect();
    // The requirement is the bottom-right of the BROWSER, which is the
    // webview -- not the view container, which also holds the toolbar and
    // whatever sits beside the page.
    const host = (bl.view.webview || bl.view.containerEl).getBoundingClientRect();
    out.pipebox = {
      drawn: drawn(pb.el).drawn,
      expanded: !!pb.expanded,
      mini: (pb.el.querySelector(".vertiscope-pipebox-mini")?.textContent || "").trim(),
      lines: Array.from(pb.el.querySelectorAll(
        ".vertiscope-pipebox-full .vertiscope-pipebox-line, .vertiscope-pipebox-full .vertiscope-pipebox-h"))
        .map((e: any) => (e.textContent || "").trim()),
      // The check run AS THE BOX DRAWS IT: one row per verdict, read off
      // the rendered rows -- where a run is observed (`G-75`).
      checks: Array.from(pb.el.querySelectorAll(".vertiscope-pipebox-check")).map((e: any) => ({
        id: e.dataset.id || null, pass: e.dataset.pass === "1",
        text: (e.textContent || "").trim().slice(0, 400) })),
      chain: Array.from(pb.el.querySelectorAll(".vertiscope-pipebox-step")).map((e: any) => ({
        label: e.querySelector(".vertiscope-pipebox-l")?.textContent,
        value: e.querySelector(".vertiscope-pipebox-n")?.textContent,
        ok: e.classList.contains("is-ok") })),
      // Where the box sits relative to the cell: it must be the bottom-right.
      corner: { right: Math.round(host.right - box.right), bottom: Math.round(host.bottom - box.bottom) },
      hover: pb.hover ? { cid: pb.hover.cid, walked: pb.hover.walked, rect: pb.hover.rect } : null,
      // Open because someone asked (a click, or a tool) -- vs a hover peek.
      asked_open: pb.el.classList.contains("is-open"),
      // Each pinned chunk's outline, where it is drawn on screen (`G-78`).
      pins: Array.from(document.querySelectorAll(".vertiscope-chunk-pin")).map((e: any) => {
        const r = e.getBoundingClientRect();
        return { shown: e.style.display !== "none",
                 rect: [Math.round(r.left), Math.round(r.top), Math.round(r.width), Math.round(r.height)] };
      }),
      outline: outline && outline.style.display !== "none" ? {
        left: outline.style.left, top: outline.style.top,
        width: outline.style.width, height: outline.style.height } : null,
    };
  }
  // The plugin's own panes that are open. Statistics and a chunk's two forms
  // have no pane of their own any more (`G-76`, `G-77`); a pane of either
  // kind showing up here is a regression.
  out.separate_panes = {
    chunk: leavesOf(CHUNK_VIEW).length,
    profile: leavesOf(PROFILE_VIEW).length,
    status_bar_readout: !!document.querySelector(".vertiscope-profile-status"),
  };

  const g: any = leavesOf(GRAPH_VIEW)[0];
  if (g && !g.isDeferred && g.view) {
    try { out.graph = graphState(g.view); }
    catch (e) { out.graph = { open: true, error: String(e).slice(0, 160) }; }
  }
  const b: any = leavesOf(BROWSER_VIEW)[0];
  if (b && !b.isDeferred && b.view?.webview) {
    try { out.browser = browserState(b.view); }
    catch (e) { out.browser = { open: true, error: String(e).slice(0, 160) }; }
    // The pinned chunks and the markdown side that shows them (`G-78`).
    try {
      const md = b.view.containerEl.querySelector(".vertiscope-browser-md") as HTMLElement | null;
      out.pinned = {
        pins: typeof b.view.pinnedState === "function" ? b.view.pinnedState() : [],
        side_shown: !!md && md.style.display !== "none" && md.classList.contains("is-side"),
        side_cards: md ? Array.from(md.querySelectorAll(".vertiscope-pin-card"))
          .map((c: any) => ({ cid: c.dataset.cid,
                              rendered_elements: c.querySelectorAll(".vertiscope-browser-mdbody *").length })) : [],
      };
    } catch (e) { out.pinned = { error: String(e).slice(0, 160) }; }
  }
  // The billboards open in the graph, and whether each is the chunk's
  // shadow-DOM form (`G-77`) and held open by the browser (`G-78`).
  if (g && !g.isDeferred && g.view && typeof g.view.billboardState === "function") {
    out.billboards = g.view.billboardState();
  }
  const c: any = leavesOf(CHUNK_VIEW)[0];
  if (c && !c.isDeferred && c.view) {
    try { out.chunk = chunkPanelState(c.view); }
    catch (e) { out.chunk = { open: true, error: String(e).slice(0, 160) }; }
  }
  return out;
}
