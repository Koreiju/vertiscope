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

// `pathToFileURL` rather than string-building: on Windows the argv path is
// `C:\...`, and hand-rolling `file://` + that yields two slashes where Node
// produces three. The guard never matched, so every invocation exited 0 with
// no output and looked like an empty result rather than a script that never
// ran.
if (process.argv[1] &&
    import.meta.url === pathToFileURL(process.argv[1]).href) {
  const args = process.argv.slice(2);
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
