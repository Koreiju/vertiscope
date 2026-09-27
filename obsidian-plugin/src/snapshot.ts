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
 *   only http(s)/mailto survive; controls are cloned DISABLED -- they are not
 *   live on their xpaths, and must not pretend to be (`G-102`). The result is
 *   shown in a sandboxed frame WITHOUT `allow-scripts`, so even a missed
 *   vector cannot run.
 * - **Offline.** The distilled form stays the fallback -- a chunk whose page
 *   is not open has no live elements to read.
 */

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

/** The page-side reader. `xs` is the chunk's element xpaths. */
export function snapshotScript(xpaths: string[]): string {
  return `(function (xs) {
  var MAX = 2500, count = 0;
  var PROPS = ["display","position","box-sizing","color","background-color","background-image",
    "background-size","background-position","background-repeat","font-family","font-size","font-weight",
    "font-style","line-height","letter-spacing","text-transform","text-decoration-line","text-decoration-color",
    "text-align","vertical-align","white-space","word-break","overflow-wrap",
    "margin-top","margin-right","margin-bottom","margin-left",
    "padding-top","padding-right","padding-bottom","padding-left",
    "border-top-width","border-right-width","border-bottom-width","border-left-width",
    "border-top-style","border-right-style","border-bottom-style","border-left-style",
    "border-top-color","border-right-color","border-bottom-color","border-left-color",
    "border-top-left-radius","border-top-right-radius","border-bottom-left-radius","border-bottom-right-radius",
    "flex-direction","flex-wrap","justify-content","align-items","align-self","gap","column-gap","row-gap",
    "flex-grow","flex-shrink","flex-basis","grid-template-columns","grid-auto-flow",
    "list-style-type","object-fit","opacity","box-shadow","overflow-x","overflow-y",
    "-webkit-line-clamp","-webkit-box-orient","text-overflow","fill","stroke"];
  var SKIP = {"0px":1,"none":1,"normal":1,"auto":1,"rgba(0, 0, 0, 0)":1,"static":1,"visible":1,
              "start":1,"baseline":1,"repeat":1,"0% 0%":1,"content-box":1,"1":1,"0":1,"nowrap":1,
              "row":1,"stretch":1,"currentcolor":1};
  var KEEP_ZERO = {"flex-shrink":1,"flex-grow":1,"opacity":1};
  var DROP = {SCRIPT:1,STYLE:1,NOSCRIPT:1,TEMPLATE:1,IFRAME:1,OBJECT:1,EMBED:1,LINK:1,META:1,BASE:1,FORM:0};
  function esc(t) { return String(t).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;"); }
  function attr(t) { return esc(t).replace(/"/g,"&quot;"); }
  function safe(u) { u = String(u || ""); return /^(https?:|mailto:)/i.test(u) ? u : ""; }
  function styleOf(el, cs) {
    var s = "";
    for (var i = 0; i < PROPS.length; i++) {
      var p = PROPS[i], v = cs.getPropertyValue(p);
      if (!v || (SKIP[v] && !KEEP_ZERO[p]) ) continue;
      if (p === "background-image" && !/url\\(/.test(v) && !/gradient/.test(v)) continue;
      if (p.indexOf("border-") === 0 && p.slice(-6) === "-color" && !/solid|dashed|dotted|double/.test(
          cs.getPropertyValue(p.replace("-color", "-style")))) continue;
      s += p + ":" + v.replace(/"/g, "'") + ";";
    }
    return s;
  }
  function pseudo(el, which) {
    var cs = getComputedStyle(el, which), c = cs.getPropertyValue("content");
    if (!c || c === "none" || c === "normal" || !/^["']/.test(c)) return "";
    var text = c.slice(1, -1);
    if (!text.trim()) return "";
    return '<span style="' + attr(styleOf(el, cs)) + '">' + esc(text) + "</span>";
  }
  function at(x) {
    try {
      var n = document.evaluate(x, document, null, 9, null).singleNodeValue;
      if (n && n.nodeType === 3) n = n.parentElement;
      return n && n.nodeType === 1 ? n : null;
    } catch (e) { return null; }
  }
  // A line joined from inline fragments keeps its FIRST fragment's address --
  // "<b>Trie</b> implementation based on ..." is addressed at the <b> -- so
  // each element found is widened to the block the browser lays its run out
  // in: up past every ancestor whose computed display is inline.
  function flow(n) {
    while (n.parentElement && n.parentElement !== document.body
           && /^inline/.test(getComputedStyle(n).display)) n = n.parentElement;
    return n;
  }
  var own = new Set(), path = new Set(), found = 0;
  for (var i = 0; i < xs.length; i++) { var n = at(xs[i]); if (n) { own.add(flow(n)); found++; } }
  if (!own.size) return null;
  var list = Array.from(own);
  function chain(n) { var a = []; while (n) { a.unshift(n); n = n.parentElement; } return a; }
  var first = chain(list[0]), depth = first.length;
  for (i = 1; i < list.length; i++) {
    var a = chain(list[i]), k = 0;
    while (k < depth && k < a.length && a[k] === first[k]) k++;
    depth = k;
  }
  var root = first[Math.max(0, depth - 1)];
  for (i = 0; i < list.length; i++) {
    for (var p = list[i]; p && p !== root; p = p.parentElement) path.add(p);
  }
  function kids(el) {
    if (el.shadowRoot) return Array.from(el.shadowRoot.childNodes);
    if (el.tagName === "SLOT" && el.assignedNodes) {
      var got = el.assignedNodes({ flatten: true });
      if (got.length) return got;
    }
    return Array.from(el.childNodes);
  }
  function svg(el) {
    var c = el.cloneNode(true);
    var bad = c.querySelectorAll("script,foreignObject,a");
    for (var i = 0; i < bad.length; i++) bad[i].remove();
    var all = [c].concat(Array.from(c.querySelectorAll("*")));
    for (i = 0; i < all.length; i++) {
      for (var j = all[i].attributes.length - 1; j >= 0; j--) {
        var nm = all[i].attributes[j].name;
        if (/^on/i.test(nm) || /href$/i.test(nm)) all[i].removeAttribute(nm);
      }
    }
    var r = el.getBoundingClientRect(), cs = getComputedStyle(el);
    c.setAttribute("width", Math.round(r.width)); c.setAttribute("height", Math.round(r.height));
    c.setAttribute("style", "color:" + cs.color + ";fill:" + cs.fill + ";vertical-align:middle;");
    return new XMLSerializer().serializeToString(c);
  }
  function clone(el, whole) {
    if (count++ > MAX) return "";
    if (el.nodeType === 3) return whole ? esc(el.nodeValue) : "";
    if (el.nodeType !== 1) return "";
    var tag = el.tagName;
    if (DROP[tag]) return "";
    var cs = getComputedStyle(el);
    if (cs.display === "none" || cs.visibility === "hidden") return "";
    if (el instanceof SVGElement) return tag.toLowerCase() === "svg" ? svg(el) : "";
    var name = tag.toLowerCase();
    if (name.indexOf("-") > 0 || name === "slot") name = /inline/.test(cs.display) ? "span" : "div";
    if (name === "form") name = "div";
    var s = styleOf(el, cs), extra = "";
    if (name === "a") { var h = safe(el.href); if (h) extra += ' href="' + attr(h) + '" data-href="' + attr(h) + '"'; }
    if (name === "img") {
      var src = safe(el.currentSrc || el.src), r = el.getBoundingClientRect();
      if (!src) return "";
      extra += ' src="' + attr(src) + '" alt="' + attr(el.alt || "") + '"';
      s += "width:" + Math.round(r.width) + "px;height:" + Math.round(r.height) + "px;max-width:100%;";
    }
    if (name === "picture" || name === "source") { if (name === "source") return ""; }
    if (name === "video") {
      var poster = safe(el.poster), vr = el.getBoundingClientRect();
      return '<img src="' + attr(poster) + '" alt="video" style="' + attr(s + "width:" + Math.round(vr.width) +
             "px;height:" + Math.round(vr.height) + "px;max-width:100%;background:#000;") + '">';
    }
    if (name === "input" || name === "textarea" || name === "select" || name === "button") {
      extra += " disabled";
      if (name === "input") {
        extra += ' type="' + attr(el.type || "text") + '"';
        if (el.type === "checkbox" || el.type === "radio") { if (el.checked) extra += " checked"; }
        else extra += ' value="' + attr(el.value || "") + '" placeholder="' + attr(el.placeholder || "") + '"';
      }
    }
    if (el.title) extra += ' title="' + attr(el.title) + '"';
    if (el.colSpan > 1) extra += ' colspan="' + el.colSpan + '"';
    if (el.rowSpan > 1) extra += ' rowspan="' + el.rowSpan + '"';
    if (name === "img" || name === "input" || name === "br" || name === "hr") {
      return "<" + name + ' style="' + attr(s) + '"' + extra + ">";
    }
    var inner = pseudo(el, "::before");
    if (name === "select") {
      var o = el.options[el.selectedIndex];
      inner += "<option>" + esc(o ? o.text : "") + "</option>";
    } else if (name === "textarea") {
      inner += esc(el.value || "");
    } else {
      var ks = kids(el);
      for (var i = 0; i < ks.length; i++) {
        var c = ks[i];
        if (whole || own.has(c)) inner += clone(c, true);
        else if (path.has(c)) inner += clone(c, false);
      }
    }
    inner += pseudo(el, "::after");
    return "<" + name + ' style="' + attr(s) + '"' + extra + ">" + inner + "</" + name + ">";
  }
  var html = clone(root, own.has(root));
  var bg = "", q = root;
  while (q && q.nodeType === 1) {
    var b = getComputedStyle(q).backgroundColor;
    if (b && b !== "rgba(0, 0, 0, 0)" && b !== "transparent") { bg = b; break; }
    q = q.parentElement;
  }
  if (!bg) bg = getComputedStyle(document.body).backgroundColor || "rgb(255, 255, 255)";
  if (bg === "rgba(0, 0, 0, 0)") bg = "rgb(255, 255, 255)";
  var rc = getComputedStyle(root);
  return { html: html, bg: bg, color: rc.color, font: rc.fontSize + " " + rc.fontFamily,
           elements: count, found: found, url: location.href, at: Date.now() };
})(${JSON.stringify(xpaths.slice(0, 600))})`;
}

/** The xpaths a chunk's payload lines draw (`url|xpath|cls|accessor...` keys). */
export function xpathsOfLines(lines: { key?: string }[]): string[] {
  const out = new Set<string>();
  for (const l of lines || []) {
    const parts = String(l.key || "").split("|");
    if (parts.length > 1 && parts[1].startsWith("/")) out.add(parts[1]);
  }
  return [...out];
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
export function renderSnapshot(host: HTMLElement, snap: Snapshot,
                               opts: { maxHeight?: number; onLink?: (href: string) => void } = {}): HTMLIFrameElement {
  const frame = document.createElement("iframe");
  frame.className = "domvec-snapshot";
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
    "</style></head><body><div id=\"domvec-root\">" + snap.html + "</div></body></html>";
  const max = opts.maxHeight ?? 560;
  frame.addEventListener("load", () => {
    const doc = frame.contentDocument;
    if (!doc) return;
    const fit = () => {
      const root = doc.getElementById("domvec-root") as HTMLElement | null;
      if (!root) return;
      const w = frame.clientWidth || host.clientWidth || 320;
      const wide = root.scrollWidth;
      (doc.body.style as any).zoom = wide > w + 4 ? String(Math.max(0.4, w / wide)) : "1";
      const h = doc.documentElement.scrollHeight;
      frame.style.height = `${Math.min(max, h)}px`;
      doc.body.style.overflowY = h > max ? "auto" : "hidden";
    };
    fit();
    // Pictures change the height as they arrive.
    doc.querySelectorAll("img").forEach((img) => img.addEventListener("load", fit));
    doc.addEventListener("click", (e) => {
      const a = (e.target as HTMLElement)?.closest?.("a[data-href]") as HTMLElement | null;
      e.preventDefault();
      if (a && opts.onLink) opts.onLink(a.getAttribute("data-href") || "");
    }, true);
  });
  host.appendChild(frame);
  return frame;
}
