/**
 * The sensor runs in an ISOLATED WORLD of the browser cell's page, not in the
 * page's main world (2026-10-06).
 *
 * Two of the user's demands meet here. "Latency should be single digit
 * millisecond" (2026-10-06): the drain is PUSHED on `console.debug` from the
 * task that folded it, but only when that function is the browser's own --
 * a page that wraps it (error reporters do, and send what they log) gets no
 * signal, and its overlay waited for the 1.2 s poll. Wikipedia and DuckDuckGo
 * both wrap it: measured 0 pushed drains in a session spent on them, and
 * `mutation_to_host` 1,088-1,259 ms on the ddg results page. And "zero
 * contact with the page itself" (2026-10-04): the main world is the page's
 * own realm, where `window.__vertiscopeSensor` is listed by
 * `Object.getOwnPropertyNames(window)` and every builtin the sensor calls is
 * one the page may have patched (`.design/research/2026-10-04-sensor-contact.md`).
 *
 * An isolated world shares the page's DOM -- MutationObservers, shadow roots,
 * computed style, events dispatched to its nodes -- and nothing else: its own
 * `window` globals, its own `JSON`, `MutationObserver`, and `console`. Probed
 * live on he.wikipedia.org with the page's `console.debug` wrapped: in world
 * 999 `window.__vertiscopeSensor` read `undefined`, `console.debug` was native,
 * its message reached the cell's `console-message`, round trip 21 ms.
 *
 * <webview> offers `executeJavaScript` in the main world only; its
 * webContents (reached through `@electron/remote`, which Obsidian ships)
 * offers `executeJavaScriptInIsolatedWorld`. This routes the cell's
 * `executeJavaScript` there, once, so every reader of the sensor -- the drain,
 * the scan, panels, overlays, the checks -- reads the same handle in the same
 * world. `executeJavaScriptMain` keeps the page's own realm for the rare read
 * that wants the PAGE's state (a fixture's counter), and the plant
 * `main-world` restores the old routing for a check's planted arm.
 *
 * In trie terms: nothing about the map changes. The fold reads the same DOM
 * and writes the same addresses; what moves is WHERE the folding code lives,
 * which is out of the page's sight.
 */

/** One world for every reader of the sensor (any id other than 0, the main world). */
export const WORLD = 1029;

export interface IsolationStats {
  isolated: number;
  fallbacks: number;
  lastFallback: string;
}

export const isolation: IsolationStats = { isolated: 0, fallbacks: 0, lastFallback: "" };

let remote: any = undefined;
function remoteModule(): any {
  if (remote !== undefined) return remote;
  try { remote = (window as any).require("@electron/remote"); }
  catch { remote = null; }
  return remote;
}

/** Route `wv.executeJavaScript` into the isolated world; idempotent. */
export function isolate(wv: any, planted: () => boolean = () => false): void {
  if (!wv || wv.__vertiscopeIsolated) return;
  const main = wv.executeJavaScript.bind(wv);
  wv.executeJavaScriptMain = main;
  wv.executeJavaScript = (code: string, gesture?: boolean) => {
    if (planted()) return main(code, gesture);
    const r = remoteModule();
    if (!r) {
      // No remote at all: the old routing, counted, never silent.
      isolation.fallbacks++;
      isolation.lastFallback = "no @electron/remote";
      return main(code, gesture);
    }
    let wc: any = null;
    try {
      wc = r.webContents.fromId(wv.getWebContentsId());
    } catch (e) {
      // Not attached yet. NOT the main world: a sensor booted there and
      // another in the isolated world would be two folds of one page.
      isolation.lastFallback = String(e).slice(0, 120);
      return Promise.reject(new Error("webview not attached: " + isolation.lastFallback));
    }
    if (!wc || typeof wc.executeJavaScriptInIsolatedWorld !== "function") {
      isolation.fallbacks++;
      isolation.lastFallback = "no executeJavaScriptInIsolatedWorld";
      return main(code, gesture);
    }
    isolation.isolated++;
    return wc.executeJavaScriptInIsolatedWorld(WORLD, [{ code }], !!gesture);
  };
  wv.__vertiscopeIsolated = true;
}
