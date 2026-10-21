// G-111: the page-side snapshot reader tags what the trie addresses, and only
// that, and leaves the rest of the controls inert. Run against a linkedom
// document with the three browser services the script reads stubbed (computed
// style, xpath evaluate, location) -- layout is not what is under test, the
// ADDRESSING is. Each rule has a planted arm: an element the table does not
// name must NOT come out live.
// Run: node --test tests/
import test from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import { parseHTML } from "linkedom";
import { snapshotScript } from "../src/snapshotscript.ts";

const HTML = `<!doctype html><html><body><div id="p">
  <p>some prose the chunk draws</p>
  <a href="http://x.test/next">Next page</a>
  <button type="button">Pick me</button>
  <button type="button">Unaddressed</button>
  <input type="text" value="hello">
  <input type="password" value="s3cret">
  <input type="checkbox" checked>
  <select><option value="a">A</option><option value="b" selected>B</option></select>
</div></body></html>`;

/** `/html/body/div/button[2]` -> the element (tag and tag[n] steps only). */
function xpathAt(document, x) {
  let node = document.documentElement;
  const steps = x.split("/").filter(Boolean);
  if (steps.shift() !== "html") return null;
  for (const s of steps) {
    const m = /^([a-z0-9]+)(?:\[(\d+)\])?$/.exec(s);
    if (!m) return null;
    const want = Number(m[2] || 1);
    node = [...node.children].filter((c) => c.tagName.toLowerCase() === m[1])[want - 1];
    if (!node) return null;
  }
  return node;
}

function run(table, xpaths) {
  const { document, window } = parseHTML(HTML);
  document.evaluate = (x) => ({ singleNodeValue: xpathAt(document, x) });
  const ctx = {
    document, location: { href: "http://x.test/page" }, Date, Math, Array, Set, Map, JSON, String,
    SVGElement: class {}, XMLSerializer: class { serializeToString() { return ""; } },
    getComputedStyle: () => ({ display: "block", visibility: "visible", backgroundColor: "rgb(255, 255, 255)",
                               color: "rgb(0, 0, 0)", fontSize: "16px", fontFamily: "serif",
                               getPropertyValue: () => "" }),
  };
  vm.createContext(ctx);
  void window;
  return vm.runInContext(snapshotScript(xpaths, table), ctx);
}

const P = "/html/body/div";
const key = (xp, tag) => ["http://x.test/page", xp, tag, "x"].join("|");
const ALL = [`${P}/p`, `${P}/a`, `${P}/button`, `${P}/button[2]`, `${P}/input`, `${P}/input[2]`, `${P}/input[3]`, `${P}/select`];

test("addressed elements carry their address, xpath and act; the rest do not", () => {
  const table = {
    [`${P}/p`]: [key(`${P}/p`, "text.visible"), 0],
    [`${P}/a`]: [key(`${P}/a`, "interactive.links"), 1],
    [`${P}/button`]: [key(`${P}/button`, "interactive.buttons"), 1],
    [`${P}/input`]: [key(`${P}/input`, "interactive.fields"), 1],
    [`${P}/input[3]`]: [key(`${P}/input[3]`, "interactive.fields"), 1],
    [`${P}/select`]: [key(`${P}/select`, "interactive.fields"), 1],
  };
  const snap = run(table, ALL);
  const html = snap.html;
  const tag = (re) => (html.match(re) || [""])[0];
  const open = (name, needle) => new RegExp(`<${name}[^>]*${needle}[^>]*>`);

  // The prose is addressed but not an action.
  assert.match(html, /<p [^>]*data-vertiscope-address="[^"]*text\.visible/);
  assert.doesNotMatch(tag(/<p [^>]*>/), /data-vertiscope-act/);
  // Link, button, text field, checkbox, select: each acts as what it is.
  assert.match(tag(open("a", "interactive\\.links")), /data-vertiscope-act="press"/);
  assert.match(tag(open("a", "interactive\\.links")), /data-vertiscope-xpath="\/html\/body\/div\/a"/);
  assert.match(tag(open("button", "interactive\\.buttons")), /data-vertiscope-act="press"/);
  assert.match(tag(open("input", "interactive\\.fields[^>]*value=\"hello\"")) || tag(/<input [^>]*value="hello"[^>]*>/),
               /data-vertiscope-act="type"/);
  assert.match(tag(/<input [^>]*type="checkbox"[^>]*>/), /data-vertiscope-act="toggle"/);
  assert.match(tag(/<select [^>]*>/), /data-vertiscope-act="choose"/);
  // A live control is not disabled.
  assert.doesNotMatch(tag(/<button [^>]*interactive\.buttons[^>]*>/), /disabled/);
});

test("planted: a control the table does not name stays inert and disabled", () => {
  const table = { [`${P}/button`]: [key(`${P}/button`, "interactive.buttons"), 1] };
  const html = run(table, ALL).html;
  const buttons = html.match(/<button [^>]*>/g);
  assert.equal(buttons.length, 2);
  assert.match(buttons[0], /data-vertiscope-act="press"/);
  assert.doesNotMatch(buttons[0], /disabled/);
  assert.match(buttons[1], /disabled/, "the unaddressed button is not live");
  assert.doesNotMatch(buttons[1], /data-vertiscope/);
  // And with an EMPTY table nothing is live at all (the pre-G-111 behaviour).
  const none = run({}, ALL).html;
  assert.doesNotMatch(none, /data-vertiscope/);
  assert.equal((none.match(/<button [^>]*disabled/g) || []).length, 2);
});

test("planted: a password field is never live, even when the trie holds its address", () => {
  const table = { [`${P}/input[2]`]: [key(`${P}/input[2]`, "interactive.fields"), 1] };
  const html = run(table, ALL).html;
  const pw = html.match(/<input [^>]*type="password"[^>]*>/)[0];
  assert.doesNotMatch(pw, /data-vertiscope-act/);
  assert.match(pw, /disabled/);
});

test("a select carries every option, with the chosen one marked", () => {
  const table = { [`${P}/select`]: [key(`${P}/select`, "interactive.fields"), 1] };
  const html = run(table, ALL).html;
  assert.match(html, /<option value="a">A<\/option>/);
  assert.match(html, /<option value="b" selected>B<\/option>/);
});
