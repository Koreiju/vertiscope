// G-111: a chunk panel's gesture, as the record the browser cell carries out.
// Pure helpers only (no DOM): each rule has a PLANTED arm -- the input that
// must NOT become an action -- beside the clean one, because a mapping that
// turns every event into an action passes every "it acts" assertion.
// Run: node --test tests/
import test from "node:test";
import assert from "node:assert/strict";
import {
  parseAddressKey, actFromEvent, chainFor, addressTable, describeResult,
} from "../src/panelact.ts";

const URL = "http://127.0.0.1:5555/panel_act.html";
const key = (xpath, tag = "interactive.buttons", acc = "text()") =>
  [URL, xpath, tag, acc].join("|");

test("an address key gives back its page and its xpath, unescaped", () => {
  const k = key("/html/body/button");
  assert.deepEqual(parseAddressKey(k), { url: URL, xpath: "/html/body/button", tag: "interactive.buttons", accessor: "text()" });
  // `|` inside a field travels as %7C (ContentAddress._esc) and must come back.
  const piped = ["http://x.test/?a=1%7C2", "/html/body/*[@id='a%7Cb']", "t.x", "y"].join("|");
  const got = parseAddressKey(piped);
  assert.equal(got.url, "http://x.test/?a=1|2");
  assert.equal(got.xpath, "/html/body/*[@id='a|b']");
});

test("planted: things that are not an address key are not parsed", () => {
  assert.equal(parseAddressKey(""), null);
  assert.equal(parseAddressKey("not-an-address"), null);
  assert.equal(parseAddressKey(["u", "html/body", "t", "a"].join("|")), null, "xpath must be absolute");
  assert.equal(parseAddressKey(["u", "/a", "t"].join("|")), null, "three fields");
});

test("a click on a button or link is a press; on a checkbox, a toggle", () => {
  const press = actFromEvent("click", { address: key("/html/body/button"), act: "press" });
  assert.equal(press.action, "press");
  assert.equal(press.url, URL);
  assert.equal(press.xpath, "/html/body/button");
  assert.equal(press.value, undefined);
  const toggle = actFromEvent("click", { address: key("/html/body/input[2]"), act: "toggle" });
  assert.equal(toggle.action, "toggle");
});

test("a change on a text field is a type carrying the value; on a select, a choose", () => {
  const type = actFromEvent("change", { address: key("/html/body/input"), act: "type", value: "hello" });
  assert.deepEqual([type.action, type.value], ["type", "hello"]);
  const choose = actFromEvent("change", { address: key("/html/body/select"), act: "choose", value: "b" });
  assert.deepEqual([choose.action, choose.value], ["choose", "b"]);
  // An emptied field is still an entry: the page is told it is now empty.
  assert.equal(actFromEvent("change", { address: key("/html/body/input"), act: "type", value: "" }).value, "");
});

test("planted: an element the trie holds no address for is never an action", () => {
  assert.equal(actFromEvent("click", { act: "press" }), null, "no address -> inert");
  assert.equal(actFromEvent("click", { address: key("/html/body/p") }), null, "no act -> a paragraph");
  assert.equal(actFromEvent("click", { address: "garbage", act: "press" }), null, "unparseable address");
  assert.equal(actFromEvent("click", { address: key("/a"), act: "execute" }), null, "vocabulary is closed");
});

test("planted: the wrong gesture on an element does not act", () => {
  // Focusing a field with a click must not press it; the entry is what acts.
  assert.equal(actFromEvent("click", { address: key("/html/body/input"), act: "type", value: "x" }), null);
  assert.equal(actFromEvent("click", { address: key("/html/body/select"), act: "choose", value: "b" }), null);
  // A checkbox's change is the same click the page already received.
  assert.equal(actFromEvent("change", { address: key("/html/body/input[2]"), act: "toggle" }), null);
  assert.equal(actFromEvent("change", { address: key("/html/body/button"), act: "press" }), null);
});

test("the chain scrolls to the element, then acts on the SAME xpath", () => {
  const c = chainFor("click", "/html/body/button");
  assert.deepEqual(c.ticks.map((t) => t.kind), ["scrollIntoView", "click"]);
  assert.ok(c.ticks.every((t) => t.xpath === "/html/body/button"));
  const t = chainFor("type", "/html/body/input", "hi");
  assert.equal(t.ticks[1].text, "hi");
  assert.equal(chainFor("click", "/x").ticks[1].text, undefined, "a press carries no text");
});

test("the address table prefers a control's own address, and keeps the first otherwise", () => {
  const link = key("/html/body/a", "interactive.links", "href");
  const lineKey = key("/html/body/a/text()", "text.visible", "text()");
  const tab = addressTable([
    { key: lineKey, control_key: link, control: true },
    { key: key("/html/body/p", "text.visible", "text()") },
    { key: key("/html/body/p", "text.visible", "other") },     // same element: first stays
  ]);
  assert.equal(tab["/html/body/a"][0], link);
  assert.equal(tab["/html/body/a"][1], 1);
  assert.equal(tab["/html/body/a/text()"][1], 1, "the line's own element is a control line");
  assert.equal(tab["/html/body/p"][0], key("/html/body/p", "text.visible", "text()"));
  assert.equal(tab["/html/body/p"][1], 0);
});

test("a later control outranks an earlier plain line at one element", () => {
  const tab = addressTable([
    { key: key("/html/body/button", "text.visible", "text()") },
    { key: key("/html/body/button", "interactive.buttons", "text()"), control: true },
  ]);
  assert.equal(tab["/html/body/button"][1], 1);
  assert.match(tab["/html/body/button"][0], /interactive\.buttons/);
});

test("the table is bounded, and ignores keys that are not addresses", () => {
  const lines = Array.from({ length: 50 }, (_, i) => ({ key: key(`/html/body/p[${i + 1}]`) }));
  assert.equal(Object.keys(addressTable(lines, 10)).length, 10);
  assert.deepEqual(addressTable([{ key: "garbage" }, {}]), {});
});

test("a refusal and a failure read differently in the panel", () => {
  assert.match(describeResult({ ok: false, stage: "plan", refused: true, error: "label matches the never-press set" }), /^refused: /);
  assert.match(describeResult({ ok: false, stage: "perform", error: "click: unresolved" }), /^perform: /);
  assert.equal(describeResult(null), "no answer from the sidecar");
  assert.equal(describeResult({ ok: true, stage: "done", did: "press Go" }), "press Go");
});

// PLUGIN_GOAL 111: Enter in a typed field sends the page's own Enter after
// the typing, on the same element; never for a press, and not without Enter.
test("enter follows the typing on the same element", () => {
  const x = "/html/body/form/div/textarea";
  const plain = chainFor("type", x, "okapi");
  assert.deepEqual(plain.ticks.map((t) => t.kind), ["scrollIntoView", "type"]);
  const sent = chainFor("type", x, "okapi", true);
  assert.deepEqual(sent.ticks.map((t) => t.kind), ["scrollIntoView", "type", "key"]);
  assert.equal(sent.ticks[2].xpath, x);
  assert.equal(sent.ticks[2].text, "Enter");
  assert.deepEqual(chainFor("press", x, undefined, true).ticks.map((t) => t.kind), ["scrollIntoView", "press"]);
});
