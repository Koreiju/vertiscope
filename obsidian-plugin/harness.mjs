/**
 * Run the built plugin outside Obsidian, against a live sidecar.
 *
 * The plugin typechecked and bundled for a whole session without one line of
 * it ever executing, and this project's record on that is unambiguous: every
 * defect found in the Python half needed the code to RUN, and none of them
 * would have been caught by types. This closes the gap for everything that
 * does not need Obsidian's own UI -- the code-block processor, the retrieval
 * gesture's trigger and insertion, the link rewrite, the sidecar contract.
 *
 * What it cannot check: rendering, layout, the WebGL scene, and whether
 * Obsidian's real API behaves as its documentation says. Those still need the
 * app. The stubs below are a reading of the docs, so a stub that is wrong
 * hides exactly the bug it was meant to catch -- they are kept as thin as
 * possible for that reason, and every one models only what the plugin calls.
 */

import assert from "node:assert";
import { parseHTML } from "linkedom";
import Module from "node:module";

// --- a DOM element with the helpers Obsidian adds -----------------------------

/** A parsed DOM node, wrapped so `El.all()` and `El.text()` can walk it. */
function domChildren(node) {
  return Array.from(node.children).map((child) => {
    const el = new El(child.tagName.toLowerCase());
    el.textContent = child.textContent || "";
    el.children = domChildren(child);
    for (const attr of Array.from(child.attributes || [])) {
      el.attrs[attr.name] = attr.value;
    }
    return el;
  });
}

class El {
  constructor(tag = "div") {
    this.tagName = tag;
    this.children = [];
    this.classList = new Set();
    this.attrs = {};
    this.textContent = "";
    this.onclick = null;
    this.hidden = false;
    this.style = {};
  }
  _add(tag, o = {}) {
    const el = new El(tag);
    if (typeof o === "string") o = { text: o };
    if (o.cls) String(o.cls).split(/\s+/).forEach((c) => el.classList.add(c));
    if (o.text) el.textContent = o.text;
    this.children.push(el);
    return el;
  }
  createEl(tag, o) { return this._add(tag, o); }
  createDiv(o) { return this._add("div", o); }
  createSpan(o) { return this._add("span", o); }
  empty() { this.children = []; this.textContent = ""; }
  addClass(c) { this.classList.add(c); }
  removeClass(c) { this.classList.delete(c); }
  setText(t) { this.textContent = t; }
  setAttr(k, v) { this.attrs[k] = v; }
  remove() {}
  querySelector() { return null; }

  /**
   * A REAL element, parsed, when the plugin assigns markup.
   *
   * The distilled-HTML surface assigns `innerHTML` and then walks the result
   * with `querySelectorAll` to strip media and wire addresses -- so a stub
   * that stores the string and answers `querySelectorAll` with nothing is
   * not exercising that code, it is skipping it. `linkedom` parses the same
   * markup a browser would and gives back the same API, which is what makes
   * this check able to fail.
   */
  set innerHTML(markup) {
    this._html = markup;
    this._dom = parseHTML(`<body>${markup}</body>`).document.body;
    // The parsed tree is the children from here on, so `text()` and `all()`
    // see what was actually drawn.
    this.children = domChildren(this._dom);
  }
  get innerHTML() { return this._html || ""; }

  querySelectorAll(selector) {
    if (this._shadow) return Array.from(this._shadow.querySelectorAll(selector));
    return this._dom ? Array.from(this._dom.querySelectorAll(selector)) : [];
  }

  /**
   * A real shadow root, backed by linkedom.
   *
   * The surface renders the distilled HTML into one, so a stub that answered
   * `attachShadow` with a bag that swallows `appendChild` would skip the
   * whole path rather than test it -- the same trap `querySelectorAll` was in
   * before linkedom went in here.
   *
   * `mode` is accepted and ignored: an open root is what the plugin asks for
   * and a closed one would only hide the elements from this file.
   */
  attachShadow() {
    const doc = parseHTML("<body></body>").document;
    this._shadow = doc.body;
    const self = this;
    return {
      appendChild(node) {
        // The plugin builds `<style>` and a `<div>` whose innerHTML is the
        // distilled markup. Only the second carries anything to assert on.
        if (node && typeof node.innerHTML === "string" && node.innerHTML) {
          self._shadow.innerHTML += node.innerHTML;
          self.children = domChildren(self._shadow);
        }
        return node;
      },
    };
  }
  matches(selector) {
    return this._dom ? this._dom.matches(selector) : false;
  }
  addEventListener() {}
  /** Everything drawn under here, flattened, for assertions. */
  all() {
    return this.children.flatMap((c) => [c, ...c.all()]);
  }
  text() {
    return [this.textContent, ...this.children.map((c) => c.text())]
      .filter(Boolean).join(" | ");
  }
}

// --- the obsidian module, as far as the plugin uses it ------------------------

const notices = [];

class Component {
  constructor() { this._cbs = []; }
  register(cb) { this._cbs.push(cb); }
  registerEvent() {}
  onload() {}
  onunload() {}
}
class MarkdownRenderChild extends Component {
  constructor(containerEl) { super(); this.containerEl = containerEl; }
}
class ItemView extends Component {
  constructor(leaf) { super(); this.leaf = leaf; this.containerEl = new El(); }
}
class PluginSettingTab { constructor(app, plugin) { this.app = app; this.plugin = plugin; } }
class Setting {
  constructor(el) { this.el = el; }
  setName() { return this; } setDesc() { return this; }
  addText(f) { f({ setPlaceholder: () => ({ setValue: () => ({ onChange: () => {} }) }) }); return this; }
  addToggle(f) { f({ setValue: () => ({ onChange: () => {} }) }); return this; }
  addSlider(f) { f({ setLimits: () => ({ setDynamicTooltip: () => ({ setValue: () => ({ onChange: () => {} }) }) }) }); return this; }
}
class EditorSuggest extends Component {
  constructor(app) { super(); this.app = app; this.context = null; }
  setInstructions() {}
  close() { this.closed = true; }
}

const stub = {
  Component,
  MarkdownRenderChild,
  ItemView,
  PluginSettingTab,
  Setting,
  EditorSuggest,
  Notice: class { constructor(msg) { notices.push(String(msg)); } },
  Plugin: class extends Component {
    constructor(app) {
      super();
      this.app = app; this._blocks = {}; this._cmds = [];
      this._suggests = []; this._views = {};
    }
    async loadData() { return {}; }
    async saveData() {}
    registerMarkdownCodeBlockProcessor(lang, fn) { this._blocks[lang] = fn; }
    registerEditorSuggest(s) { this._suggests.push(s); }
    // A map, not a slot. Registering a second view overwrote the first,
    // so the harness could only ever see whichever was registered last
    // -- and would have reported the chunk pane missing while it was
    // registered perfectly well.
    registerView(type, factory) {
      this._views = this._views || {};
      this._views[type] = factory;
      this._view = { type, factory };
    }
    registerEvent() {}
    addCommand(c) { this._cmds.push(c); }
    addRibbonIcon() { return new El(); }
    addSettingTab() {}
  },
};

// `obsidian` on npm is types-only, so requiring it at runtime fails. Intercept.
const load = Module._load;
Module._load = function (request, parent, isMain) {
  if (request === "obsidian") return stub;
  return load.call(this, request, parent, isMain);
};

// --- browser globals three.js touches at import time --------------------------
//
// Not a plugin defect: Obsidian is an Electron renderer and `window` is real
// there. But it does say the whole 3.2 MB of three.js is parsed the moment the
// plugin loads, whether or not the 3D view is ever opened.

globalThis.window = globalThis;
globalThis.self = globalThis;
// `navigator` is a getter-only global in modern Node, so it is defined rather
// than assigned.
if (!globalThis.navigator?.userAgent) {
  Object.defineProperty(globalThis, "navigator",
                        { value: { userAgent: "node" }, configurable: true });
}
/**
 * `document.createElement`, for real.
 *
 * The surface builds a `<style>` and a `<div>` through it and then sets
 * `innerHTML` on the div, so a node whose innerHTML goes nowhere makes the
 * shadow path untestable. linkedom gives back something that actually parses.
 */
const realDoc = parseHTML("<body></body>").document;

const fakeNode = () => ({
  style: {}, dataset: {}, childNodes: [], firstChild: null,
  getContext: () => null, setAttribute: () => {}, appendChild: () => {},
  insertBefore: () => {}, addEventListener: () => {}, removeChild: () => {},
});
globalThis.document = {
  head: fakeNode(),
  body: fakeNode(),
  documentElement: { style: {} },
  // Real for the tags the plugin builds by hand (the shadow root and
  // its stylesheet); the fake node stays for everything three.js pokes
  // at during import, which only needs to not throw.
  // Only `div`, which is the one element whose innerHTML the shadow path
  // actually parses. Making `style` real too broke three.js at import: its
  // styleInject appends a text node to a detached <style>, and linkedom's
  // mutation observer wants an ownerDocument that a detached node has not
  // got. The fake node is fine for that -- nothing reads it back.
  createElement: (tag) => (/^div$/i.test(tag)
    ? realDoc.createElement(tag) : fakeNode()),
  createElementNS: fakeNode,
  createTextNode: fakeNode,
  // `3d-force-graph` injects its stylesheet into `document.head` at IMPORT
  // time, before anything opens the view -- another eager side effect of
  // bundling it at the top level.
  getElementsByTagName: () => [fakeNode()],
  addEventListener: () => {},
};

// --- a vault of the notes the export actually wrote ---------------------------

import { readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";

const PAGES = process.argv[2] || "../pages";
const files = readdirSync(PAGES).filter((f) => f.endsWith(".md"));
const vaultFiles = files.map((f) => {
  const raw = readFileSync(join(PAGES, f), "utf8");
  const head = raw.split("---")[1] || "";
  const front = {};
  for (const line of head.split("\n")) {
    const m = /^(\w+):\s*"?([^"]*)"?\s*$/.exec(line.trim());
    if (m) front[m[1]] = m[2];
  }
  return { basename: f.replace(/\.md$/, ""), path: f, front, raw };
});

const app = {
  vault: { getMarkdownFiles: () => vaultFiles },
  metadataCache: { getFileCache: (f) => ({ frontmatter: f.front }) },
  workspace: {
    on: () => ({}),
    getLeavesOfType: () => [],
    getLeaf: () => ({ setViewState: async () => {}, openFile: async () => {} }),
    revealLeaf: () => {},
  },
};

// Every fetch the plugin makes, and what happened to it. `Sidecar.get`
// answers null on any failure -- right for a vault that must work offline,
// blind when something is actually wrong.
const calls = [];
const realFetch = globalThis.fetch;
globalThis.fetch = async (...args) => {
  const started = Date.now();
  try {
    const res = await realFetch(...args);
    calls.push(`${res.status} ${String(args[0])} (${Date.now() - started}ms)`);
    return res;
  } catch (e) {
    calls.push(`THREW ${String(args[0])}: ${e.name} ${e.message} ` +
               `${e.cause?.code || e.cause?.message || ""}`);
    throw e;
  }
};

// --- run ----------------------------------------------------------------------

// esbuild's cjs output is `module.exports = __toCommonJS(exports)`, so the
// class sits at `.default` of what ESM hands back as `default`. Obsidian
// loads the file with its own CommonJS require and reads the same field.
const mod = await import("./main.js");
const VertiscopePlugin = mod.default?.default ?? mod.default;
const plugin = new VertiscopePlugin(app);
await plugin.onload();
plugin.settings.sidecar = "http://127.0.0.1:8788";

// The first UMAP fit over a real workspace is tens of seconds, and the checks
// below all start at once. A search issued while the server is inside that fit
// times out, `Sidecar.get` answers null on any failure by design, and the
// retrieval check then reports "no suggestions: 0" -- a passing feature
// failing for a reason that has nothing to do with it. Warmed once, here,
// where waiting costs nothing and confuses nobody.
await fetch("http://127.0.0.1:8788/layout")
  .then((r) => r.json())
  .then((l) => console.log(`warmed: layout has ${l.n ?? 0} nodes`))
  .catch((e) => console.log(`warm-up failed: ${e.message}`));

const results = [];
const check = (name, fn) => results.push(
  Promise.resolve().then(fn).then(
    (detail) => ({ name, ok: true, detail }),
    (err) => ({ name, ok: false, detail: err.message })));

check("sidecar answers", async () => {
  assert.ok(await plugin.sidecar.alive(), "sidecar not reachable");
  return "alive";
});

check("code block renders a chunk", async () => {
  const cid = vaultFiles[0].front.cid;
  const el = new El();
  // `onload` is async and does the fetch, so the draw has not happened when
  // the processor returns. Obsidian awaits the child's lifecycle itself; the
  // harness has to as well or it asserts on an empty element.
  let child = null;
  await plugin._blocks.vertiscope(`cid: ${cid}`, el, {
    addChild: (c) => { child = c; },
  });
  await child.onload();
  // Diagnosis, kept: the surface reports "offline" for ANY null, so when this
  // check fails the useful question is whether the client or the route said no.
  const direct = await plugin.fetchChunk(cid);
  const raw = await fetch(`${plugin.settings.sidecar}/chunk/${cid}`)
    .then((r) => r.status).catch((e) => e.message);
  const text = el.text();
  if (!direct) {
    throw new Error(`fetchChunk(${cid}) -> null; raw status ${raw}; ` +
                    `sidecar setting ${JSON.stringify(plugin.settings.sidecar)}`);
  }
  assert.ok(!text.includes("carries no cid"), "cid was not parsed");
  assert.ok(!text.includes("sidecar unreachable"), "surface says offline: " + text);
  assert.ok(text.length > 20, "surface drew almost nothing: " + text);
  return `${el.all().length} elements, cid ${cid.slice(0, 8)}`;
});

check("a bad cid is reported, not thrown", async () => {
  const el = new El();
  await plugin._blocks.vertiscope("nonsense", el, { addChild: (c) => c.onload() });
  assert.ok(el.text().includes("carries no cid"));
  return "reported";
});

check("link map resolves through frontmatter", async () => {
  const n = await plugin.links.refresh();
  assert.ok(n > 0, "no page resolved to a note");
  return `${n} url spellings mapped`;
});

check("a web link becomes a wikilink", async () => {
  await plugin.links.refresh();
  const withLink = vaultFiles.find((f) => /\]\(https?:/.test(f.raw));
  if (!withLink) return "skipped: no absolute link in the export";
  const { text, edges } = plugin.links.rewrite(withLink.raw, withLink.front.url);
  return edges > 0 ? `${edges} rewritten` : "0 rewritten (targets not exported)";
});

check("the / gesture triggers and searches", async () => {
  const suggest = plugin._suggests[0];
  const editor = { getLine: () => "/books travel", replaceRange: (t) => (editor.wrote = t) };
  const none = suggest.onTrigger({ line: 0, ch: 2 }, editor, null);
  assert.strictEqual(none, null, "fired on a two-character query");
  const info = suggest.onTrigger({ line: 0, ch: 13 }, editor, null);
  assert.ok(info && info.query === "books travel", "did not trigger: " + JSON.stringify(info));
  const items = await suggest.getSuggestions(info);
  assert.ok(items.length > 1, "no suggestions: " + items.length);
  assert.strictEqual(items[0].kind, "all");
  return `${items.length - 1} hits`;
});

check("selecting inserts a passage with rules", async () => {
  const suggest = plugin._suggests[0];
  let wrote = "";
  const editor = { getLine: () => "/books travel", replaceRange: (t) => (wrote = t) };
  const info = suggest.onTrigger({ line: 0, ch: 13 }, editor, null);
  suggest.context = { ...info, editor, query: info.query };
  const items = await suggest.getSuggestions(info);
  await suggest.selectSuggestion(items[1]);
  assert.ok(wrote.includes("____"), "no rule between passages");
  assert.ok(wrote.split("\n").length > 3, "passage is one line: " + wrote);
  const buried = wrote.split("\n").filter((l) => /^ {4,}\S/.test(l));
  assert.strictEqual(buried.length, 0,
    "inserted lines would parse as a code block: " + buried[0]);
  return `${wrote.length} chars, ${wrote.split("\n").length} lines`;
});

check("layout answers with placed nodes", async () => {
  // The first fit is tens of seconds through the server, and `Sidecar.get`
  // answers null on ANY failure by design -- right for the UI, blind for a
  // diagnosis. Warm it with a raw fetch first so a null here means something.
  await fetch("http://127.0.0.1:8788/layout").catch(() => {});
  const layout = await plugin.sidecar.layout();
  assert.ok(layout, "no layout");
  assert.ok(layout.nodes.length > 0, "no nodes placed");
  const bad = layout.nodes.filter((n) => n.pos.some((v) => !Number.isFinite(v)));
  assert.strictEqual(bad.length, 0, "non-finite coordinates");
  return `${layout.nodes.length} nodes, ${layout.edges.length} edges, ` +
         `${layout.spaces.join("+")}`;
});

check("the interactive form is the distilled HTML, with addresses", async () => {
  // The point of the HTML form: a <button> that exists because the trie said
  // the element is a control, not because a regex matched a rendering. If the
  // sidecar stops sending `html` the surface silently falls back to
  // reconstructing widgets from markdown, which looks almost identical and is
  // a different claim -- so this asserts on the markup, not on the picture.
  const cid = vaultFiles[0].front.cid;
  const payload = await plugin.fetchChunk(cid);
  assert.ok(payload, "no payload");
  assert.ok(payload.html && payload.html.length > 20,
            "sidecar sent no distilled HTML");
  assert.ok(/data-vertiscope-address="[^"]+"/.test(payload.html),
            "no element carries an address");
  // Nothing executable can have come through. The Python side whitelists and
  // escapes; this is the client-side check that it actually did, because this
  // markup goes into an UNSANITISED DOM.
  assert.ok(!/<script/i.test(payload.html), "script tag in distilled HTML");
  assert.ok(!/\son[a-z]+=/i.test(payload.html), "event handler in distilled HTML");
  assert.ok(!/href="javascript:/i.test(payload.html), "javascript: href");
  const elements = (payload.html.match(/<[a-z]/g) || []).length;
  return `${elements} elements, ` +
         `${(payload.html.match(/data-vertiscope-address/g) || []).length} addressed`;
});

check("the layout is six-dimensional and colours from the fit", async () => {
  const layout = await plugin.sidecar.layout();
  assert.ok(layout, "no layout");
  assert.strictEqual(layout.hsv, true, "colour is not from the fit");
  assert.strictEqual(layout.fitted_dims, 6,
                     `fitted ${layout.fitted_dims} dims, expected 6`);
  const coloured = layout.nodes.filter(
    (n) => Array.isArray(n.hsv) && n.hsv.length === 3
           && n.hsv.every((v) => Number.isFinite(v)));
  assert.strictEqual(coloured.length, layout.nodes.length,
                     "some nodes have no colour from the fit");
  // Non-vacuity: a constant hue would satisfy every assertion above and would
  // mean the colour carries nothing.
  const hues = new Set(layout.nodes.map((n) => Math.round(n.hsv[0])));
  assert.ok(hues.size > 1, "every node got the same hue");
  return `${layout.nodes.length} nodes, ${hues.size} distinct hues, ` +
         `${layout.images ?? 0} with a picture`;
});

check("a node click opens the chunk pane, not the note", async () => {
  const names = plugin._views ? Object.keys(plugin._views) : [];
  assert.ok(names.includes("vertiscope-chunk-view"),
            "no chunk view registered: " + names.join(", "));
  return names.join(", ");
});

check("commands are registered", async () => {
  const names = plugin._cmds.map((c) => c.id);
  assert.ok(names.includes("vertiscope-open-graph"), "graph command missing");
  return names.join(", ");
});

const done = await Promise.all(results);
let failed = 0;
for (const r of done) {
  if (!r.ok) failed++;
  console.log(`${r.ok ? "PASS" : "FAIL"}  ${r.name}\n        ${r.detail}`);
}
if (notices.length) console.log("\nnotices: " + notices.join(" / "));
if (failed) {
  console.log("\nfetch log (Sidecar.get answers null on any failure, so this");
  console.log("is the only place a swallowed error is visible):");
  for (const c of calls) console.log("  " + c);
}
console.log(`\n${done.length - failed} passed, ${failed} failed`);
process.exit(failed ? 1 : 0);
