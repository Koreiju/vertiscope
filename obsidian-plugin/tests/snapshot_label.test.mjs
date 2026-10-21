// G-111: a <label> the trie holds passes its address to the control it labels.
// The store draws "Your word [ ]" as one line keyed at the label, so the empty
// input of tests/fixtures/panel_act.html had no address and its card was inert
// (the fill arm found no field, 2026-10-07).
import test from "node:test";
import assert from "node:assert/strict";
import vm from "node:vm";
import { parseHTML } from "linkedom";
import { snapshotScript } from "../src/snapshotscript.ts";

const HTML = `<!doctype html><html><body><div>
  <label for="word">Your word</label>
  <input id="word" type="text" value="">
  <label>Plain label, no control</label>
</div></body></html>`;

function xpathAt(document, x) {
  let node = document.documentElement;
  const steps = x.split("/").filter(Boolean);
  if (steps.shift() !== "html") return null;
  for (const s of steps) {
    const m = /^([a-z0-9]+)(?:\[(\d+)\])?$/.exec(s);
    if (!m) return null;
    node = [...node.children].filter((c) => c.tagName.toLowerCase() === m[1])[Number(m[2] || 1) - 1];
    if (!node) return null;
  }
  return node;
}

function run(table, xpaths) {
  const { document } = parseHTML(HTML);
  document.evaluate = (x) => ({ singleNodeValue: xpathAt(document, x) });
  const ctx = { document, location: { href: "http://x.test/page" }, Date, Math, Array, Set, Map, JSON, String,
    SVGElement: class {}, XMLSerializer: class { serializeToString() { return ""; } },
    getComputedStyle: () => ({ display: "block", visibility: "visible", backgroundColor: "rgb(255, 255, 255)",
      color: "rgb(0, 0, 0)", fontSize: "16px", fontFamily: "serif", getPropertyValue: () => "" }) };
  vm.createContext(ctx);
  return vm.runInContext(snapshotScript(xpaths, table), ctx);
}

const P = "/html/body/div";
const key = (xp, tag) => ["http://x.test/page", xp, tag, "x"].join("|");

test("the labelled input takes its label's address and is a field to type into", () => {
  const table = { [`${P}/label`]: [key(`${P}/label`, "interactive.forms"), 0] };
  const html = run(table, [`${P}/label`, `${P}/input`]).html;
  assert.match(html, /<input[^>]*data-vertiscope-act="type"/, html);
  assert.doesNotMatch(html, /<input[^>]*disabled/);
});

test("planted: a label with no control, or an unaddressed label, makes nothing live", () => {
  const plain = { [`${P}/label[2]`]: [key(`${P}/label[2]`, "interactive.forms"), 0] };
  const html = run(plain, [`${P}/label`, `${P}/input`, `${P}/label[2]`]).html;
  assert.doesNotMatch(html, /data-vertiscope-act="type"/);
  assert.match(html, /<input[^>]*disabled/);
});
