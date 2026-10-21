/**
 * A chunk as the BROWSER draws it (D-36).
 *
 * Both chunk panels -- the billboard in the 3D view and the card in the
 * browser's side panel -- were rebuilt from the chunk's distilled lines, and
 * a panel rebuilt from markdown cannot look like the page because it is not
 * the page's HTML: "A **suffix trie** is ..." came out as three bullets,
 * buttons as `( label )`, a breadcrumb link as raw `[..](..)`, thumbnails as
 * "could not be found". The user, twice on 2026-09-27: the panels must match
 * how the chunk is rendered in the browser.
 *
 * So the panel shows the chunk's OWN elements, read from the live page:
 *
 * - **What is read.** The elements the chunk's lines draw (their xpaths, from
 *   the store's chunk), and the branches from their common ancestor down to
 *   them -- nothing else of the page. Each cloned element carries the
 *   computed styles that decide how it looks (font, colour, spacing, borders,
 *   flex/grid, backgrounds), and pseudo-element text (`::before` breadcrumb
 *   arrows, icon glyphs) becomes a span.
 * - **A read, on demand.** Called when a chunk is pinned or re-read, never
 *   inside the sensor's fold; nothing is written into the page (constraint 7).
 * - **Untrusted by construction.** No script, style sheet, iframe, object or
 *   handler is cloned; no id or class is copied; urls are made absolute and
 *   only http(s)/mailto survive. The result is shown in a sandboxed frame
 *   WITHOUT `allow-scripts`, so even a missed vector cannot run.
 * - **Linked to the trie (G-102, 2026-10-04).** An element the chunk's lines
 *   name carries the address the store holds for it (`data-vertiscope-address`,
 *   `data-vertiscope-xpath`), and the ones a reader acts on in place also carry
 *   `data-vertiscope-act`. Those controls are live: the panel intercepts the
 *   event, and the browser cell navigates to the page, scrolls to the element
 *   and performs the action there (`panelact.ts`, `BrowserView.actOn`). A
 *   control the trie holds no address for is still cloned DISABLED -- it is
 *   not live on its xpath, and must not pretend to be.
 * - **Offline.** The distilled form stays the fallback -- a chunk whose page
 *   is not open has no live elements to read.
 */

import type { ActRecord, ActResult, PanelEl } from "./panelact";
import { actFromEvent, describeResult } from "./panelact";

export interface Snapshot {
  html: string;
  /** The first opaque background above the chunk, so light text stays legible. */
  bg: string;
  color: string;
  font: string;
  /** Elements cloned, and the chunk's own elements found in the page. */
  elements: number;
  found: number;
  /** Where it was read from, and when. */
  url: string;
  at: number;
}

export { snapshotScript } from "./snapshotscript";

/** The xpaths a chunk's payload lines draw (`url|xpath|cls|accessor...` keys). */
export function xpathsOfLines(lines: { key?: string }[]): string[] {
  const out = new Set<string>();
  for (const l of lines || []) {
    const parts = String(l.key || "").split("|");
    if (parts.length > 1 && parts[1].startsWith("/")) out.add(parts[1]);
  }
  return [...out];
}

/**
 * Each page's favicon (2026-09-27: "missing .icon (micro icons usually seen in
 * the browser tab and search results) ... for the remainder of url-level
 * nodes"). Reported by the webview's own `page-favicon-updated` event --
 * nothing is read from the page for it -- and remembered per vault.
 */
const ICONS_KEY = "vertiscope-favicons";
let icons: Record<string, string> | null = null;
function iconTable(): Record<string, string> {
  if (icons) return icons;
  try { icons = JSON.parse(window.localStorage.getItem(ICONS_KEY) || "{}"); } catch { icons = {}; }
  return icons!;
}
export function putFavicon(pageUrl: string, icon: string): void {
  if (!pageUrl || !/^https?:/.test(icon || "")) return;
  const t = iconTable();
  const key = pageUrl.split("#")[0];
  if (t[key] === icon) return;
  t[key] = icon;
  try { window.localStorage.setItem(ICONS_KEY, JSON.stringify(t)); } catch { /* storage unavailable */ }
}
/** The page's icon: the one the webview reported, else the site's /favicon.ico. */
export function faviconFor(pageUrl: string): string {
  const t = iconTable();
  const key = String(pageUrl || "").split("#")[0];
  if (t[key]) return t[key];
  try {
    const u = new URL(key);
    if (!/^https?:$/.test(u.protocol)) return "";
    const same = Object.entries(t).find(([k]) => { try { return new URL(k).host === u.host; } catch { return false; } });
    return same ? same[1] : `${u.origin}/favicon.ico`;
  } catch { return ""; }
}

/**
 * Each chunk's most relevant picture: the LARGEST as the page renders it
 * (css-scaled, on screen), read by the sensor's picture peripheral with the
 * drain (2026-09-27: "show the most relevant image ... using css-scaled size
 * (so, post-rendered size)"). Remembered per vault, by stored chunk id.
 */
const PICS_KEY = "vertiscope-pictures";
let pics: Record<string, string> | null = null;
function picTable(): Record<string, string> {
  if (pics) return pics;
  try { pics = JSON.parse(window.localStorage.getItem(PICS_KEY) || "{}"); } catch { pics = {}; }
  return pics!;
}
export function putPictures(byCid: Record<string, string>): void {
  const t = picTable();
  let changed = false;
  for (const [cid, src] of Object.entries(byCid)) {
    if (!/^https?:/.test(src) || t[cid] === src) continue;
    t[cid] = src; changed = true;
  }
  const keys = Object.keys(t);
  if (keys.length > 20000) for (const k of keys.slice(0, keys.length - 20000)) delete t[k];
  if (changed) { try { window.localStorage.setItem(PICS_KEY, JSON.stringify(t)); } catch { /* full */ } }
}
export function pictureFor(cid: string): string {
  return picTable()[cid] || "";
}

/**
 * Each page's BASE url (`document.baseURI`), recorded when the page loads. A
 * relative destination resolves against the base, not the page url: johnwick
 * .movie sets <base href="/">, so `assets/img/x.png` on /film/... is
 * /assets/img/x.png -- resolved against the page it was /film/assets/...,
 * and every picture in the markdown form broke (2026-10-10).
 */
const BASE_KEY = "vertiscope-bases";
let bases: Record<string, string> | null = null;
function baseTable(): Record<string, string> {
  if (bases) return bases;
  try { bases = JSON.parse(window.localStorage.getItem(BASE_KEY) || "{}"); } catch { bases = {}; }
  return bases!;
}
const pageKey = (u: string) => String(u || "").split("#")[0];
export function putBase(url: string, base: string): void {
  if (!url || !/^https?:/.test(base) || pageKey(base) === pageKey(url)) return;
  const t = baseTable();
  if (t[pageKey(url)] === base) return;
  t[pageKey(url)] = base;
  const keys = Object.keys(t);
  if (keys.length > 5000) for (const k of keys.slice(0, keys.length - 5000)) delete t[k];
  try { window.localStorage.setItem(BASE_KEY, JSON.stringify(t)); } catch { /* full */ }
}
export function baseFor(url: string): string {
  return baseTable()[pageKey(url)] || url;
}

/** Snapshots by chunk id, shared by both panels for the life of the app. */
const STORE = new Map<string, Snapshot>();
export function putSnapshot(cid: string, s: Snapshot | null): void {
  if (cid && s && s.html) STORE.set(cid, s);
}
export function dropSnapshot(cid: string): void {
  STORE.delete(cid);
}
export function getSnapshot(cid: string): Snapshot | null {
  return STORE.get(cid) || null;
}

/**
 * Show a snapshot in `host`: a sandboxed frame (no scripts, no forms, no
 * navigation), reflowed to the panel's width and scaled down only if what the
 * page laid out is wider still. A click on a link is handed to `onLink` --
 * the browser cell navigates; the frame never does.
 */
/** Run-time plants for the snapshot frame (the harness flips them). */
export const snapshotConfig = { plantInertLooksLive: false };
try { (window as any).__vertiscopeSnapshotConfig = snapshotConfig; } catch { /* no window */ }

export function renderSnapshot(host: HTMLElement, snap: Snapshot,
                               opts: {
                                 maxHeight?: number;
                                 onLink?: (href: string) => void;
                                 /** A gesture on an element the trie addresses: carried out in the
                                  *  browser cell, on the live page. Absent -> controls stay inert. */
                                 onAct?: (rec: ActRecord) => Promise<ActResult | null>;
                                 /** The reader left a field of this panel: a redraw held while
                                  *  they typed may run now. */
                                 onFieldDone?: () => void;
                                 /** The chunk, so the last gesture's outcome survives a re-draw. */
                                 cid?: string;
                               } = {}): HTMLIFrameElement {
  const frame = document.createElement("iframe");
  frame.className = "vertiscope-snapshot";
  // allow-same-origin WITHOUT allow-scripts: the page's markup cannot run,
  // and the host can still read the frame's height and catch link clicks.
  frame.setAttribute("sandbox", "allow-same-origin");
  frame.setAttribute("referrerpolicy", "no-referrer");
  frame.style.width = "100%";
  frame.style.border = "0";
  frame.style.display = "block";
  frame.style.background = snap.bg;
  const css = "html,body{margin:0;padding:0;background:" + snap.bg + ";color:" + snap.color +
    ";font:" + snap.font + ";overflow-x:hidden;}body{padding:8px 10px;box-sizing:border-box;}" +
    // A reset FIRST: the snapshot leaves out values equal to their plain
    // default (margin 0, text-decoration none) to stay small, so the frame's
    // own UA styles must not fill them back in -- a grey breadcrumb inside an
    // <a> came out blue and underlined, and every <h2>/<p> gained margins.
    "*{margin:0;padding:0;border:0;font:inherit;color:inherit;text-decoration:none;list-style:none;" +
    "max-width:100%;box-sizing:border-box;background:transparent;}" +
    "b,strong{font-weight:bold;}img,svg,video{max-width:100%;}a{cursor:pointer;}";
  frame.srcdoc = "<!doctype html><html><head><meta charset=\"utf-8\"><style>" + css +
    "</style></head><body><div id=\"vertiscope-root\">" + snap.html + "</div></body></html>";
  const max = opts.maxHeight ?? 560;
  frame.addEventListener("load", () => {
    const doc = frame.contentDocument;
    if (!doc) return;
    const fit = () => {
      const root = doc.getElementById("vertiscope-root") as HTMLElement | null;
      if (!root) return;
      const w = frame.clientWidth || host.clientWidth || 320;
      const wide = root.scrollWidth;
      (doc.body.style as any).zoom = wide > w + 4 ? String(Math.max(0.4, w / wide)) : "1";
      const h = doc.documentElement.scrollHeight;
      frame.style.height = `${Math.min(max, h)}px`;
      doc.body.style.overflowY = h > max ? "auto" : "hidden";
    };
    fit();
    // A control that cannot act SAYS so (G-102, Addendum IX: "the buttons are
    // just stale"): a button, field or menu the trie holds no address for --
    // or any control when there is no cell to act through -- is drawn dimmed
    // with a not-allowed cursor and a title naming why, never as a live
    // control that does nothing when pressed. A link with no address still
    // opens its page, so links are not touched. Planted
    // `snapshotConfig.plantInertLooksLive`: drawn as the page drew it.
    if (!snapshotConfig.plantInertLooksLive) {
      const CONTROL = "button, input, select, textarea, [role=button], [role=checkbox], [role=switch], [role=tab], [role=menuitem], [role=combobox], [role=slider]";
      let inert = 0;
      doc.querySelectorAll(CONTROL).forEach((el) => {
        const h = el as HTMLElement;
        if (h.closest("a[data-href]") && !h.matches("button, input, select, textarea")) return;
        if (opts.onAct && h.closest("[data-vertiscope-act]")) return;
        h.setAttribute("aria-disabled", "true");
        h.setAttribute("data-vertiscope-inert", "");
        h.setAttribute("title", opts.onAct ? "not reachable from here: the page's map holds no address for this control"
                                           : "not live here: open the page in the browser cell to use it");
        h.style.cursor = "not-allowed";
        h.style.opacity = "0.55";
        h.tabIndex = -1;
        inert++;
      });
      frame.dataset.inert = String(inert);
    }
    // Pictures change the height as they arrive.
    doc.querySelectorAll("img").forEach((img) => img.addEventListener("load", fit));
    // The frame never navigates and no control acts on its own: every event
    // is stopped here, and one on an element the trie addresses becomes an
    // ActRecord handed to the browser cell. The panel is not re-drawn by the
    // gesture -- it is re-drawn when the page changes (the caller re-reads).
    const elOf = (t: EventTarget | null) =>
      (t as HTMLElement | null)?.closest?.("[data-vertiscope-act]") as HTMLElement | null;
    const asEl = (el: HTMLElement): PanelEl => ({
      address: el.getAttribute("data-vertiscope-address") || undefined,
      act: el.getAttribute("data-vertiscope-act") || undefined,
      value: (el as HTMLInputElement).value,
    });
    // Enter and the change it implies can both arrive for one entry: one act.
    let lastSent = { sig: "", at: 0 };
    const run = (rec: ActRecord | null): boolean => {
      if (!rec || !opts.onAct) return false;
      const sig = `${rec.action}|${rec.key}|${rec.value ?? ""}`;
      if (sig === lastSent.sig && Date.now() - lastSent.at < 400) return true;
      lastSent = { sig, at: Date.now() };
      // Only the LATEST gesture on this chunk may write the readout: a fill's
      // act resolves after its re-snapshot (up to 1.5 s), and its late
      // "type Your word" overwrote the refusal of a press made meanwhile
      // (G-111's refused arm, 2026-10-07).
      const key = opts.cid || "";
      const seq = (ACT_SEQ.get(key) || 0) + 1;
      ACT_SEQ.set(key, seq);
      const latest = () => ACT_SEQ.get(key) === seq;
      note(`${rec.action}…`);
      opts.onAct(rec).then((r) => { if (latest()) note(describeResult(r)); },
                           (err) => { if (latest()) note(`error: ${String(err).slice(0, 80)}`); });
      return true;
    };
    doc.addEventListener("click", (e) => {
      const hit = elOf(e.target);
      const a = (e.target as HTMLElement)?.closest?.("a[data-href]") as HTMLElement | null;
      e.preventDefault();
      if (hit && run(actFromEvent("click", asEl(hit)))) return;
      // No address, or no cell to act through: a link still opens its page.
      if (a && opts.onLink && !(hit && opts.onAct)) opts.onLink(a.getAttribute("data-href") || "");
    }, true);
    doc.addEventListener("change", (e) => {
      const hit = elOf(e.target);
      if (hit) run(actFromEvent("change", asEl(hit)));
    }, true);
    // A reader who types and presses Enter has finished the field; the page's
    // own form would submit, which this panel does not do -- the value lands
    // as the `change` it is, and that is all.
    // Enter in a field -- an <input> or a <textarea> (DuckDuckGo's search
    // box is one) -- sends the value AND the page's Enter, which is what the
    // reader's own keyboard does there (PLUGIN_GOAL 111). Shift+Enter in a
    // textarea stays a newline.
    doc.addEventListener("keydown", (e) => {
      const ke = e as KeyboardEvent;
      const t = ke.target as HTMLInputElement | null;
      typingAt = Date.now();
      if (ke.key === "Enter" && !ke.shiftKey && t && (t.tagName === "INPUT" || t.tagName === "TEXTAREA") && elOf(t)) {
        ke.preventDefault();
        const rec = actFromEvent("change", asEl(elOf(t)!));
        if (rec) rec.enter = true;
        typingAt = 0;
        run(rec);
      }
    }, true);
    doc.addEventListener("input", () => { typingAt = Date.now(); }, true);
    // Leaving the field is the end of typing: a redraw held meanwhile runs.
    doc.addEventListener("focusout", () => {
      typingAt = 0;
      window.setTimeout(() => { if (!fieldActive()) opts.onFieldDone?.(); }, 0);
    }, true);
  });
  // The panel is being typed in: a field of its own has the keyboard. A
  // redraw then would replace the field under the reader's fingers -- the
  // page streams, its chunk is rewritten, the panel re-mounts (2026-10-11:
  // "I can't enter things in the search bar").
  let typingAt = 0;
  const fieldActive = () => {
    const d = frame.contentDocument;
    const a = d && (d.activeElement as HTMLElement | null);
    return !!a && document.activeElement === frame && /^(INPUT|TEXTAREA|SELECT)$/.test(a.tagName);
  };
  (frame as any).vertiscopeTyping = () => fieldActive() || Date.now() - typingAt < 1500;
  host.appendChild(frame);
  const readout = document.createElement("div");
  readout.className = "vertiscope-act-readout";
  host.appendChild(readout);
  const note = (text: string) => {
    readout.textContent = text;
    readout.style.display = text ? "block" : "none";
    if (opts.cid) LAST_ACT.set(opts.cid, text);
  };
  note(opts.cid ? LAST_ACT.get(opts.cid) || "" : "");
  return frame;
}

/** What the last gesture on each chunk's panel said, kept across re-draws. */
const LAST_ACT = new Map<string, string>();
/** The newest gesture's number on each chunk's panel. */
const ACT_SEQ = new Map<string, number>();
