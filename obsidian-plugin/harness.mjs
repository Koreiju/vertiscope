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
import Module from "node:module";

// --- a DOM element with the helpers Obsidian adds -----------------------------

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
    constructor(app) { super(); this.app = app; this._blocks = {}; this._cmds = []; this._suggests = []; }
    async loadData() { return {}; }
    async saveData() {}
    registerMarkdownCodeBlockProcessor(lang, fn) { this._blocks[lang] = fn; }
    registerEditorSuggest(s) { this._suggests.push(s); }
    registerView(type, factory) { this._view = { type, factory }; }
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
const fakeNode = () => ({
  style: {}, dataset: {}, childNodes: [], firstChild: null,
  getContext: () => null, setAttribute: () => {}, appendChild: () => {},
  insertBefore: () => {}, addEventListener: () => {}, removeChild: () => {},
});
globalThis.document = {
  head: fakeNode(),
  body: fakeNode(),
  documentElement: { style: {} },
  createElement: fakeNode,
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
const DomvecPlugin = mod.default?.default ?? mod.default;
const plugin = new DomvecPlugin(app);
await plugin.onload();
plugin.settings.sidecar = "http://127.0.0.1:8788";

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
  await plugin._blocks.domvec(`cid: ${cid}`, el, {
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
  await plugin._blocks.domvec("nonsense", el, { addChild: (c) => c.onload() });
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

check("commands are registered", async () => {
  const names = plugin._cmds.map((c) => c.id);
  assert.ok(names.includes("domvec-open-graph"), "graph command missing");
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
