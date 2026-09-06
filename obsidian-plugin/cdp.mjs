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

import { readFileSync } from "node:fs";
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

// `pathToFileURL` rather than string-building: on Windows the argv path is
// `C:\...`, and hand-rolling `file://` + that yields two slashes where Node
// produces three. The guard never matched, so every invocation exited 0 with
// no output and looked like an empty result rather than a script that never
// ran.
if (process.argv[1] &&
    import.meta.url === pathToFileURL(process.argv[1]).href) {
  const args = process.argv.slice(2);
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
