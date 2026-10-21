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
 *   node cdp.mjs "app.plugins.enabledPlugins.has('vertiscope-bridge')"
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
async function session() {
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
  await send("Emulation.setFocusEmulationEnabled", { enabled: true });
  await send("Page.setWebLifecycleState", { state: "active" });
  return { send, close: () => ws.close() };
}

/**
 * The interface as TEXT: roles, names and values, in tree order.
 *
 *   node cdp.mjs --ax
 *   node cdp.mjs --ax ".workspace-leaf-content[data-type='vertiscope-chunk-view']"
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
