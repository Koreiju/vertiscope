/**
 * Evaluate JavaScript inside a running Obsidian.
 *
 * Obsidian is Electron, so launching it with `--remote-debugging-port=9222`
 * exposes the renderer over the Chrome DevTools Protocol -- and the renderer
 * is where `app` lives: the plugin registry, the command list, the workspace,
 * the DOM. That is a far better instrument than a screenshot. A screenshot
 * shows what a pane looks like; this says whether the plugin loaded, which
 * commands exist, what the view rendered, and what threw.
 *
 * No dependencies: Node has a built-in `WebSocket`, and CDP is JSON over one.
 *
 *   node cdp.mjs "app.plugins.enabledPlugins.has('domvec-bridge')"
 *   node cdp.mjs --file probe.js
 *
 * The expression is evaluated with `awaitPromise`, so `await` works at the top
 * level of whatever is passed.
 */

import { readFileSync, writeFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

const PORT = process.env.OBSIDIAN_CDP_PORT || 9222;

async function pageTarget() {
  const res = await fetch(`http://127.0.0.1:${PORT}/json/list`);
  const targets = await res.json();
  const page = targets.find(
    (t) => t.type === "page" && String(t.url).startsWith("app://obsidian.md"));
  if (!page) {
    throw new Error("no Obsidian page target; is it running with " +
                    "--remote-debugging-port=" + PORT + "?");
  }
  return page.webSocketDebuggerUrl;
}

export async function evaluate(expression, { timeout = 180000 } = {}) {
  const ws = new WebSocket(await pageTarget());
  await new Promise((ok, no) => {
    ws.addEventListener("open", ok, { once: true });
    ws.addEventListener("error", () => no(new Error("CDP socket failed")),
                        { once: true });
  });

  // Render even when the window is covered.
  //
  // Chromium suspends layout in an occluded window: `document.visibilityState`
  // goes "hidden", `innerText` comes back empty and every
  // `getBoundingClientRect()` is zero. Obsidian is a Chromium renderer, so a
  // probe that measures anything sees zeros the moment a terminal is in front
  // of the app -- which, while driving it from a terminal, is most of the
  // time. It reads exactly like a plugin that failed to load, and it cost two
  // rounds of chasing before the cause was clear.
  //
  // These two are the supported override. `setFocusEmulationEnabled` makes
  // the page believe it is focused, and `setWebLifecycleState` puts it in the
  // "active" state; together the renderer keeps laying out and the
  // measurements are real. Nothing is moved on the user's screen to do it.
  for (const [id, method, params] of [
    [90, "Emulation.setFocusEmulationEnabled", { enabled: true }],
    [91, "Page.setWebLifecycleState", { state: "active" }],
  ]) {
    ws.send(JSON.stringify({ id, method, params }));
  }

  const result = await new Promise((resolve, reject) => {
    const timer = setTimeout(
      () => reject(new Error(`evaluate timed out after ${timeout}ms`)), timeout);
    ws.addEventListener("message", (event) => {
      const msg = JSON.parse(event.data);
      if (msg.id !== 1) return;              // ignore protocol events
      clearTimeout(timer);
      if (msg.error) return reject(new Error(JSON.stringify(msg.error)));
      const r = msg.result;
      // An exception inside the page is a RESULT with exceptionDetails, not a
      // protocol error. Surfaced as a rejection so a probe cannot pass by
      // throwing quietly.
      if (r.exceptionDetails) {
        return reject(new Error(
          "page threw: " + (r.exceptionDetails.exception?.description ||
                            r.exceptionDetails.text)));
      }
      resolve(r.result.value);
    });
    ws.send(JSON.stringify({
      id: 1,
      method: "Runtime.evaluate",
      params: {
        expression,
        awaitPromise: true,
        returnByValue: true,
        // Obsidian's `app` is a global in the renderer, but only outside a
        // module scope; `includeCommandLineAPI` also gives the probe `$$`.
        includeCommandLineAPI: true,
      },
    }));
  }).finally(() => ws.close());

  return result;
}

/**
 * A picture of the window, or of one pane.
 *
 *   node cdp.mjs --shot out.png
 *   node cdp.mjs --shot out.png ".workspace-leaf.mod-active"
 *
 * This does NOT change what counts as proof. `X-2` says verify over devtools,
 * never by screenshot, and it is right: a picture cannot say whether a plugin
 * loaded, which commands exist, or what threw. Every probe in `probes/` asserts
 * on structure and text and must keep doing so.
 *
 * What a picture is for is the complement of that: LAYOUT and COLOUR, which the
 * accessibility tree and `innerText` cannot show. A panel whose text is correct
 * while overlapping its neighbour, a theme whose contrast is unreadable, a canvas
 * drawing nothing where the node array is full — all pass every structural
 * assertion. So this exists to let a reader of the terminal SEE the thing, and
 * never to stand in for an assertion about it.
 *
 * `clip` is taken from a selector rather than by hand: the numbers that describe
 * a pane are in the page, and copying them into a command is how a screenshot
 * comes to be of the wrong region.
 */
export async function screenshot(outPath, selector = "") {
  const ws = new WebSocket(await pageTarget());
  await new Promise((ok, no) => {
    ws.addEventListener("open", ok, { once: true });
    ws.addEventListener("error", () => no(new Error("CDP socket failed")),
                        { once: true });
  });
  // The same occlusion override `evaluate` needs, and for a sharper reason
  // here: an occluded renderer does not repaint, so the capture is a stale
  // frame or an empty one.
  for (const [id, method, params] of [
    [90, "Emulation.setFocusEmulationEnabled", { enabled: true }],
    [91, "Page.setWebLifecycleState", { state: "active" }],
  ]) {
    ws.send(JSON.stringify({ id, method, params }));
  }

  const send = (id, method, params) => new Promise((resolve, reject) => {
    const onMessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.id !== id) return;
      ws.removeEventListener("message", onMessage);
      if (msg.error) return reject(new Error(JSON.stringify(msg.error)));
      resolve(msg.result);
    };
    ws.addEventListener("message", onMessage);
    ws.send(JSON.stringify({ id, method, params }));
  });

  try {
    let clip;
    if (selector) {
      const box = await send(2, "Runtime.evaluate", {
        expression: `(() => { const e = document.querySelector(${
          JSON.stringify(selector)}); if (!e) return null;
          const r = e.getBoundingClientRect();
          return {x: r.x, y: r.y, width: r.width, height: r.height}; })()`,
        returnByValue: true,
      });
      const r = box.result?.value;
      if (!r) throw new Error(`no element matches ${selector}`);
      if (!r.width || !r.height) {
        // A zero box is the occlusion symptom above, or a hidden pane. Both
        // produce a blank file, which looks like a rendering bug rather than a
        // measurement one.
        throw new Error(`${selector} has a zero-sized box (hidden pane?)`);
      }
      clip = { ...r, scale: 1 };
    }
    const shot = await send(3, "Page.captureScreenshot",
                            clip ? { format: "png", clip } : { format: "png" });
    writeFileSync(outPath, Buffer.from(shot.data, "base64"));
    return outPath;
  } finally {
    ws.close();
  }
}

/**
 * A CDP session, so several commands can share one socket.
 *
 * `evaluate` and `screenshot` each open and close their own, which is fine for
 * one shot and wrong for a walk: the accessibility tree is one command per
 * depth-limited fetch plus one per box, and paying a WebSocket handshake for
 * each turns a snapshot into a visible pause.
 */
async function session({ emulate = true } = {}) {
  const ws = new WebSocket(await pageTarget());
  await new Promise((ok, no) => {
    ws.addEventListener("open", ok, { once: true });
    ws.addEventListener("error", () => no(new Error("CDP socket failed")),
                        { once: true });
  });
  let next = 100;
  const send = (method, params = {}) => new Promise((resolve, reject) => {
    const id = next++;
    const onMessage = (event) => {
      const msg = JSON.parse(event.data);
      if (msg.id !== id) return;
      ws.removeEventListener("message", onMessage);
      if (msg.error) return reject(new Error(method + ": " + JSON.stringify(msg.error)));
      resolve(msg.result);
    };
    ws.addEventListener("message", onMessage);
    ws.send(JSON.stringify({ id, method, params }));
  });
  // The occlusion override, for the same reason `evaluate` needs it: a covered
  // renderer stops laying out, and an accessibility tree taken then is a tree
  // of zero-sized nodes with no names.
  if (emulate) {
    await send("Emulation.setFocusEmulationEnabled", { enabled: true });
    await send("Page.setWebLifecycleState", { state: "active" });
  }
  return { send, ws, close: () => ws.close() };
}

/**
 * The interface as TEXT: roles, names and values, in tree order.
 *
 *   node cdp.mjs --ax
 *   node cdp.mjs --ax ".workspace-leaf-content[data-type='domvec-chunk-view']"
 *   node cdp.mjs --ax --boxes
 *
 * This is the image-free way to see a pane, and it is a better instrument than
 * a screenshot for almost everything a screenshot gets used for. The
 * accessibility tree is what a screen reader consumes: every meaningful element
 * reduced to a ROLE and its ACCESSIBLE NAME. So it says what a control IS and
 * what it is called, which a picture only implies and which `innerText` loses
 * entirely -- a button and a div full of text read the same in `innerText` and
 * differently here.
 *
 * The shape follows Playwright's aria-snapshot, deliberately: `role "name"`,
 * one per line, indented by depth, with an optional `boxes` mode appending
 * geometry. That format exists because it is the one people already read, and
 * inventing a second spelling of it would make every example on the internet
 * not apply.
 *
 * `--boxes` is what closes the last gap a text tree leaves: a panel whose text
 * is right while it overlaps its neighbour is invisible to roles and names, and
 * obvious in four numbers.
 */
export async function axTree(selector = "", { boxes = false, depth = 0 } = {}) {
  const s = await session();
  try {
    await s.send("Accessibility.enable");
    let rootId = null;
    if (selector) {
      const { root } = await s.send("DOM.getDocument", { depth: -1, pierce: true });
      const found = await s.send("DOM.querySelector",
                                 { nodeId: root.nodeId, selector });
      if (!found.nodeId) throw new Error("no element matches " + selector);
      const described = await s.send("DOM.describeNode", { nodeId: found.nodeId });
      rootId = described.node.backendNodeId;
    }

    // Always the FULL tree, then scoped by walking down to the selector's node.
    //
    // `getPartialAXTree` looks like the scoped call and is not: with
    // `fetchRelatives:false` it returns the one node, and with it true it
    // returns ancestors as well as descendants. Either way the caller has to
    // rebuild a subtree, so it is simpler to take the whole thing once and
    // start the walk somewhere else in it.
    const { nodes } = await s.send("Accessibility.getFullAXTree",
                                   depth ? { depth } : {});

    const byId = new Map(nodes.map((n) => [n.nodeId, n]));
    const children = new Set();
    for (const n of nodes) for (const c of n.childIds || []) children.add(c);
    let roots = nodes.filter((n) => !children.has(n.nodeId));
    if (rootId !== null) {
      const scoped = nodes.find((n) => n.backendDOMNodeId === rootId);
      if (!scoped) {
        throw new Error(selector + " has no accessibility node " +
                        "(aria-hidden, or not rendered)");
      }
      roots = [scoped];
    }

    const box = async (n) => {
      if (!boxes || !n.backendDOMNodeId) return "";
      try {
        const { model } = await s.send("DOM.getBoxModel",
                                       { backendNodeId: n.backendDOMNodeId });
        const q = model.border;                     // x1,y1 x2,y2 x3,y3 x4,y4
        return `  [${Math.round(q[0])},${Math.round(q[1])} ${
          Math.round(q[2] - q[0])}x${Math.round(q[5] - q[1])}]`;
      } catch {
        // A node with no box is display:none or detached. That is information,
        // not an error: it is exactly the "present but not drawn" case a text
        // tree is otherwise blind to.
        return "  [not drawn]";
      }
    };

    const out = [];
    const walk = async (node, indent) => {
      if (!node) return;
      // `ignored` nodes are in the tree but hidden from assistive tech --
      // presentational wrappers, aria-hidden subtrees. Skipping them is what
      // keeps this readable; their CHILDREN are still walked, because Obsidian
      // wraps real controls in presentational divs several deep.
      const role = node.role?.value || "";
      const name = node.name?.value || "";
      const value = node.value?.value;
      // `InlineTextBox` is the layout box UNDER a `StaticText` and carries the
      // same string, so printing both doubles every word in the tree. The
      // parent is the meaningful node; this is its geometry.
      if (!node.ignored && role && role !== "none" && role !== "generic"
          && role !== "InlineTextBox") {
        out.push("  ".repeat(indent) + role +
                 (name ? ` "${name}"` : "") +
                 (value !== undefined && value !== "" ? ` = ${JSON.stringify(value)}` : "") +
                 await box(node));
        indent += 1;
      }
      for (const id of node.childIds || []) await walk(byId.get(id), indent);
    };
    for (const r of roots) await walk(r, 0);
    return out.join("\n");
  } finally {
    s.close();
  }
}

/**
 * Real input events, the kind the renderer marks trusted.
 *
 *   node cdp.mjs --click 771 787
 *   node cdp.mjs --drag 700 500 900 600
 *
 * `Input.dispatchMouseEvent` does NOT build a DOM MouseEvent and call
 * `dispatchEvent`. It hands the browser a `WebInputEvent` -- the same internal
 * representation the OS produces for a real mouse -- which enters the pipeline
 * UPSTREAM of where the renderer decides trust. So the resulting DOM events
 * carry `isTrusted: true`, where anything dispatched from page script carries
 * `false`.
 *
 * That difference is not cosmetic here. A `.click()` from script skips hover
 * state, skips the pointer capture a drag needs, and is refused outright by any
 * handler that checks `isTrusted`. It is why a script click can pick a node in
 * the 3D graph (the raycaster only reads coordinates) and yet cannot ORBIT it
 * (the camera controller tracks a real pointer across moves).
 */
export async function mouse(actions) {
  const s = await session();
  try {
    for (const a of actions) {
      await s.send("Input.dispatchMouseEvent", {
        type: a.type, x: a.x, y: a.y,
        button: a.button ?? "left",
        buttons: a.buttons ?? (a.type === "mouseMoved" ? 0 : 1),
        clickCount: a.clickCount ?? (a.type === "mousePressed" ? 1 : 0),
      });
      if (a.pause) await new Promise((r) => setTimeout(r, a.pause));
    }
    return "ok";
  } finally {
    s.close();
  }
}

/**
 * A TRUSTED hover sweep over the 3D graph's picture nodes (G-145).
 *
 *   node cdp.mjs --hover-sweep [count] [dwellMs] [--off] [--profile]
 *
 * Script-dispatched pointer events light a node's glow but never reach the
 * graph's own hover -- its tooltip and the image path the reader reported
 * freezing ("frozen again and image hovering stops working in chunk view").
 * `Input.dispatchMouseEvent` enters the input pipeline as a real mouse does.
 * The page records frame gaps, long tasks, tooltips seen and pictures loaded
 * while the sweep runs. `--off` is the null arm: the same moves 40 px outside
 * the canvas, which must register no hover at all. Refuses on a minimised
 * window, where rAF runs at 1 Hz and every timing is the window's.
 */
export async function hoverSweep({ count = 40, dwell = 400, off = false, profile = false } = {}) {
  const plan = JSON.parse(await evaluate(`(() => {
    const w = require("@electron/remote").getCurrentWindow();
    if (w.isMinimized()) return JSON.stringify({ refused: "window minimised" });
    const v = app.workspace.getLeavesOfType("domvec-graph-view")[0]?.view;
    if (!v || !v.graph) return JSON.stringify({ refused: "no graph view" });
    const g = v.graph, el = v.canvasEl || g.renderer().domElement, r = el.getBoundingClientRect();
    const pts = [];
    for (const n of g.graphData().nodes) {
      if (!n.image || !Number.isFinite(n.x)) continue;
      const s = g.graph2ScreenCoords(n.x, n.y, n.z || 0);
      if (s.x > 40 && s.y > 40 && s.x < r.width - 40 && s.y < r.height - 160) pts.push([Math.round(r.left + s.x), Math.round(r.top + s.y)]);
      if (pts.length > 4000) break;
    }
    const pick = [];
    for (let i = 0; i < ${count} && pts.length; i++) pick.push(pts[(i * 7919) % pts.length]);
    const rec = window.__domvecHoverSweep = { gaps: [], tasks: [], tips: new Set(), pics: new Set(), run: true, last: performance.now(),
      img0: g.graphData().nodes.filter((n) => n.imgLoaded).length, glow0: v.glowLatency.length };
    rec.obs = new PerformanceObserver((l) => { for (const e of l.getEntries()) rec.tasks.push(Math.round(e.duration)); });
    rec.obs.observe({ entryTypes: ["longtask"] });
    // The hover's PICTURES are drawn on the K nodes nearest the pointer's
    // ray (item 112, \`refreshDetail\`), not in the tooltip: counted per frame.
    rec.revealed = new Set(); rec.revealedLoaded = new Set(); rec.detail0 = v.detailStats.computes;
    rec.loads0 = v.batch && v.batch.loadStats ? v.batch.loadStats.started : null;
    const loop = () => { const now = performance.now(); rec.gaps.push(now - rec.last); rec.last = now;
      for (const n of (v.lastRevealed || [])) { if (n && n.image) { rec.revealed.add(n.id); if (n.__bpic) rec.revealedLoaded.add(n.id); } }
      const t = document.querySelector(".scene-tooltip, .float-tooltip-kap");
      const txt = t && t.offsetParent !== null ? (t.innerText || "").trim() : "";
      if (txt) { rec.tips.add(txt.slice(0, 80)); const im = t.querySelector("img, canvas");
        if (im) rec.pics.add(txt.slice(0, 80) + "|" + (im.complete === false ? "loading" : im.naturalWidth > 0 || im.tagName === "CANVAS" ? "drawn" : "broken")); }
      if (rec.run) requestAnimationFrame(loop); };
    requestAnimationFrame(loop);
    return JSON.stringify({ nodes: g.graphData().nodes.length, level: v.level || "pages", pictures: pts.length, pick,
                            canvas: [Math.round(r.left), Math.round(r.top), Math.round(r.right), Math.round(r.bottom)] });
  })()`));
  if (plan.refused) return plan;
  const moves = [];
  for (const [x, y] of plan.pick) {
    const at = off ? [plan.canvas[0] - 40, y] : [x, y];
    moves.push({ type: "mouseMoved", x: at[0], y: at[1], buttons: 0, pause: Math.round(dwell / 2) });
    moves.push({ type: "mouseMoved", x: at[0] + 1, y: at[1], buttons: 0, pause: Math.round(dwell / 2) });
  }
  // `--profile`: V8 samples the main thread for the length of the moves --
  // WHICH function each long task is, where the gaps only say how long.
  const prof = profile ? await session({ emulate: false }) : null;
  if (prof) { await prof.send("Profiler.enable"); await prof.send("Profiler.setSamplingInterval", { interval: 250 }); await prof.send("Profiler.start"); }
  await mouse(moves);
  let hot = null;
  if (prof) {
    try { hot = profileTop((await prof.send("Profiler.stop")).profile); }
    finally { try { await prof.send("Profiler.disable"); } catch {} prof.close(); }
  }
  const got = JSON.parse(await evaluate(`(() => {
    const rec = window.__domvecHoverSweep, v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
    rec.run = false; rec.obs.disconnect();
    const g = rec.gaps.slice(1).sort((a, b) => a - b), q = (f) => g.length ? Math.round(g[Math.min(g.length - 1, Math.floor(g.length * f))]) : null;
    return JSON.stringify({ frames: g.length, gap_p50: q(0.5), gap_p99: q(0.99), worst: q(1),
      over_200: g.filter((x) => x > 200).length, over_1s: g.filter((x) => x > 1000).length,
      longtasks: rec.tasks.length, longtask_ms: rec.tasks.reduce((a, b) => a + b, 0), top: rec.tasks.sort((a, b) => b - a).slice(0, 6),
      detail_computes: v.detailStats.computes - rec.detail0, pictures_revealed: rec.revealed.size, pictures_revealed_drawn: rec.revealedLoaded.size,
      decodes_started: rec.loads0 === null ? null : v.batch.loadStats.started - rec.loads0,
      tooltips: rec.tips.size, tooltips_with_picture: rec.pics.size,
      picture_states: [...rec.pics].reduce((o, k) => { const s = k.split("|").pop(); o[s] = (o[s] || 0) + 1; return o; }, {}), glows: v.glowLatency.length - rec.glow0,
      pictures_loaded: v.graph.graphData().nodes.filter((n) => n.imgLoaded).length - rec.img0 });
  })()`));
  return { off, count: plan.pick.length, dwell, nodes: plan.nodes, level: plan.level, pictures_on_screen: plan.pictures, ...got,
           ...(hot ? { profile: hot } : {}) };
}

/**
 * A V8 CPU profile reduced to where the time went: self ms and inclusive ms
 * per function (`name @ file:line`), the top `k` of each. Inclusive counts
 * a frame once per sample however often it recurs on that stack.
 */
export function profileTop(profile, k = 14) {
  const byId = new Map(profile.nodes.map((n) => [n.id, n]));
  const parent = new Map();
  for (const n of profile.nodes) for (const c of n.children || []) parent.set(c, n.id);
  const key = (n) => { const f = n.callFrame; return `${f.functionName || "(anon)"} @ ${String(f.url).split("/").pop()}:${f.lineNumber + 1}`; };
  const self = new Map(), incl = new Map();
  let total = 0;
  profile.samples.forEach((id, i) => {
    const dt = (profile.timeDeltas[i] || 0) / 1000;
    total += dt;
    const n = byId.get(id); if (!n) return;
    const k0 = key(n); self.set(k0, (self.get(k0) || 0) + dt);
    const seen = new Set();
    for (let at = id; at !== undefined; at = parent.get(at)) {
      const kk = key(byId.get(at)); if (seen.has(kk)) continue; seen.add(kk);
      incl.set(kk, (incl.get(kk) || 0) + dt);
    }
  });
  const top = (m) => [...m].filter(([kk]) => !/^\((root|program|idle)\)/.test(kk)).sort((a, b) => b[1] - a[1]).slice(0, k).map(([kk, ms]) => [kk, Math.round(ms)]);
  return { sampled_ms: Math.round(total), idle_ms: Math.round(self.get("(idle) @ :0") || 0), self: top(self), inclusive: top(incl) };
}

/** A trusted click: move there first, so hover state is real. */
export const click = (x, y) => mouse([
  { type: "mouseMoved", x, y, buttons: 0, pause: 60 },
  { type: "mousePressed", x, y },
  { type: "mouseReleased", x, y, buttons: 0 },
]);

/** A trusted drag, in steps, because a controller reading one jump is a click. */
export const drag = (x1, y1, x2, y2, steps = 12) => {
  const path = [{ type: "mouseMoved", x: x1, y: y1, buttons: 0, pause: 40 },
                { type: "mousePressed", x: x1, y: y1, pause: 40 }];
  for (let i = 1; i <= steps; i++) {
    path.push({ type: "mouseMoved", pause: 16,
                x: Math.round(x1 + (x2 - x1) * i / steps),
                y: Math.round(y1 + (y2 - y1) * i / steps) });
  }
  path.push({ type: "mouseReleased", x: x2, y: y2, buttons: 0 });
  return mouse(path);
};

/**
 * Attach BEFORE the hang, then catch it on the stack.
 *
 * `stack()` below cannot work on a renderer that is already wedged in JS:
 * `Debugger.pause` is delivered by interrupt, but `Debugger.enable` is not --
 * it queues behind the busy task, so the pause arrives with no debugger to
 * land in (2026-11-14: read as "native block", which it was not shown to be).
 * Here the debugger is enabled while the page still answers; a heartbeat
 * `Runtime.evaluate` then marks the hang, and pauses sample where it is.
 */
export async function watchHang({ seconds = 300, beatMs = 1500, hangMs = 4000, samples = 4 } = {}) {
  const s = await session({ emulate: false });
  const paused = [];
  s.ws.addEventListener("message", (ev) => {
    const m = JSON.parse(ev.data);
    if (m.method === "Debugger.paused") paused.push(m.params);
  });
  await s.send("Debugger.enable");
  const end = Date.now() + seconds * 1000;
  const out = { hung: false, samples: [] };
  try {
    while (Date.now() < end) {
      const t0 = Date.now();
      const beat = await Promise.race([s.send("Runtime.evaluate", { expression: "1" }).then(() => true),
                                       new Promise((r) => setTimeout(() => r(false), hangMs))]);
      if (beat) { await new Promise((r) => setTimeout(r, beatMs)); continue; }
      out.hung = true; out.hung_at = new Date(t0).toISOString();
      for (let i = 0; i < samples; i++) {
        paused.length = 0;
        const p0 = Date.now();
        s.ws.send(JSON.stringify({ id: 9100 + i, method: "Debugger.pause", params: {} }));
        while (!paused.length && Date.now() - p0 < 8000) await new Promise((r) => setTimeout(r, 25));
        if (!paused.length) { out.samples.push({ landed: false }); break; }
        out.samples.push({ landed: true, waited_ms: Date.now() - p0,
          frames: paused[0].callFrames.slice(0, 24).map((f) =>
            `${f.functionName || "(anon)"} @ ${String(f.url).split("/").pop()}:${f.location.lineNumber + 1}:${f.location.columnNumber + 1}`) });
        s.ws.send(JSON.stringify({ id: 9200 + i, method: "Debugger.resume", params: {} }));
        await new Promise((r) => setTimeout(r, 700));
      }
      break;
    }
    return out;
  } finally {
    try { s.ws.send(JSON.stringify({ id: 9300, method: "Debugger.disable", params: {} })); } catch {}
    s.close();
  }
}

/**
 * WHERE the renderer's main thread is, when it is not answering.
 *
 * A frozen app answers no `Runtime.evaluate` -- the probe and the reader wait
 * on the same thread -- so every other instrument here times out and says
 * nothing about why. `Debugger.pause` is delivered by V8's interrupt, not by
 * the event loop, so it lands inside a busy JS loop and the paused event
 * carries the stack. If it does NOT land within `ms`, the thread is not in JS
 * at all (a synchronous IPC, a native call, layout) -- which is a finding too.
 */
export async function stack(ms = 8000, samples = 3) {
  const s = await session({ emulate: false });  // emulation waits on the busy thread
  const out = [];
  try {
    const paused = [];
    s.ws.addEventListener("message", (ev) => {
      const m = JSON.parse(ev.data);
      if (m.method === "Debugger.paused") paused.push(m.params);
    });
    s.ws.send(JSON.stringify({ id: 9001, method: "Debugger.enable", params: {} }));
    for (let i = 0; i < samples; i++) {
      const t0 = Date.now();
      paused.length = 0;
      s.ws.send(JSON.stringify({ id: 9100 + i, method: "Debugger.pause", params: {} }));
      while (!paused.length && Date.now() - t0 < ms) await new Promise((r) => setTimeout(r, 25));
      if (!paused.length) { out.push({ sample: i, landed: false, waited_ms: Date.now() - t0 }); break; }
      const p = paused[0];
      out.push({ sample: i, landed: true, waited_ms: Date.now() - t0, reason: p.reason,
                 frames: p.callFrames.slice(0, 18).map((f) =>
                   `${f.functionName || "(anon)"} @ ${String(f.url).split("/").pop()}:${f.location.lineNumber + 1}:${f.location.columnNumber + 1}`) });
      s.ws.send(JSON.stringify({ id: 9200 + i, method: "Debugger.resume", params: {} }));
      await new Promise((r) => setTimeout(r, 400));
    }
    s.ws.send(JSON.stringify({ id: 9300, method: "Debugger.disable", params: {} }));
    return out;
  } finally {
    s.close();
  }
}

// `pathToFileURL` rather than string-building: on Windows the argv path is
// `C:\...`, and hand-rolling `file://` + that yields two slashes where Node
// produces three. The guard never matched, so every invocation exited 0 with
// no output and looked like an empty result rather than a script that never
// ran.
if (process.argv[1] &&
    import.meta.url === pathToFileURL(process.argv[1]).href) {
  const args = process.argv.slice(2);
  if (args[0] === "--ax") {
    const rest = args.slice(1).filter((a) => a !== "--boxes");
    console.log(await axTree(rest[0] || "",
                             { boxes: args.includes("--boxes") }));
    process.exit(0);
  }
  if (args[0] === "--hover-sweep") {
    const nums = args.slice(1).filter((x) => /^\d+$/.test(x)).map(Number);
    console.log(JSON.stringify(await hoverSweep({ count: nums[0] || 40, dwell: nums[1] || 400, off: args.includes("--off"),
                                                       profile: args.includes("--profile") }), null, 1));
    process.exit(0);
  }
  if (args[0] === "--watch-hang") {
    console.log(JSON.stringify(await watchHang({ seconds: Number(args[1]) || 300 }), null, 1));
    process.exit(0);
  }
  if (args[0] === "--reload") {
    // Recovery for a renderer whose main thread is wedged: `Page.reload` is
    // served by the BROWSER-side page handler (the navigation controller),
    // so it lands when nothing evaluated in the page can. Vault, workspace
    // layout and the sidecar are untouched; the plugin loads again.
    const s = await session({ emulate: false });
    try { console.log(JSON.stringify(await s.send("Page.reload", { ignoreCache: false }))); }
    finally { s.close(); }
    process.exit(0);
  }
  if (args[0] === "--stack") {
    console.log(JSON.stringify(await stack(Number(args[1]) || 8000, Number(args[2]) || 3), null, 1));
    process.exit(0);
  }
  if (args[0] === "--click" || args[0] === "--drag") {
    const n = args.slice(1).map(Number);
    await (args[0] === "--click" ? click(n[0], n[1])
                                 : drag(n[0], n[1], n[2], n[3]));
    console.log("ok");
    process.exit(0);
  }
  if (args[0] === "--shot") {
    try {
      const where = await screenshot(args[1], args[2] || "");
      console.log(where);
    } catch (err) {
      console.error(String(err.message));
      process.exit(1);
    }
    process.exit(0);
  }
  const expr = args[0] === "--file"
    ? readFileSync(args[1], "utf8")
    : args.join(" ");
  try {
    const value = await evaluate(expr);
    console.log(typeof value === "string" ? value
                                          : JSON.stringify(value, null, 2));
  } catch (err) {
    console.error(String(err.message));
    process.exit(1);
  }
}
