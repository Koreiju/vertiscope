// G-202 (2026-10-17): "please default natural-text inputs to the web-browser
// url bar as duckduckgo search inputs (no need to scroll)".
import { test } from "node:test";
import assert from "node:assert/strict";
import { addressTarget } from "../src/address.ts";

const ddg = (q) => "https://duckduckgo.com/?q=" + encodeURIComponent(q) + "&ia=web";

test("words are a DuckDuckGo search", () => {
  for (const q of ["patricia trie", "how do radix trees work?", "zucchini", "c++ templates", "what is arxiv.org"]) {
    const got = addressTarget(q);
    assert.equal(got.search, true, q);
    assert.equal(got.url, ddg(q), q);
  }
});

test("places are places: schemes, hosts, ports, paths", () => {
  const cases = {
    "https://www.imdb.com/": "https://www.imdb.com/",
    "about:blank": "about:blank",
    "arxiv.org": "https://arxiv.org",
    "en.wikipedia.org/wiki/Radix_tree": "https://en.wikipedia.org/wiki/Radix_tree",
    "localhost:8788/health": "http://localhost:8788/health",
    "127.0.0.1:9222/json": "http://127.0.0.1:9222/json",
    "duckduckgo.com/?q=okapi": "https://duckduckgo.com/?q=okapi",
  };
  for (const [typed, url] of Object.entries(cases)) {
    const got = addressTarget(typed);
    assert.equal(got.search, false, typed);
    assert.equal(got.url, url, typed);
  }
});

test("null arm: empty is nothing, not a search for nothing", () => {
  assert.deepEqual(addressTarget("   "), { url: "", search: false });
});

import { canonAddr } from "../src/address.ts";
test("a slotted element has one spelling: composed and light paths agree", () => {
  const composed = "/html/body/app-root/#shadow-root/main/div/router-slot/#shadow-root/slot/home-page/#shadow-root/div[2]/article[25]";
  const light = "/html/body/app-root/#shadow-root/main/div/router-slot/home-page/#shadow-root/div[2]/article[25]";
  assert.equal(canonAddr(composed), canonAddr(light));
  assert.ok(canonAddr(light + "/a").startsWith(canonAddr(composed) + "/"));
  // null arm: a shadow root that is NOT a slot step is kept
  assert.equal(canonAddr("/html/body/x-app/#shadow-root/div"), "/html/body/x-app/#shadow-root/div");
  assert.equal(canonAddr("/a/#shadow-root/slot[2]/b"), "/a/b");
});

import { unitOf, isListAbove } from "../src/address.ts";
test("a unit stops below a list: an item with one streamed line is still the item", () => {
  const L = (a, t) => ({ text: t, key: "u|" + a });
  const lines = [
    L("/g/section/article[1]/div/a", "first tile"), L("/g/section/article[1]/div/b", "first count"), L("/g/section/article[1]/div/c", "first pic"),
    L("/g/section/article[2]/div/a", "second tile"),
  ];
  assert.equal(isListAbove("/g/section", lines.map((l) => l.key.slice(2))), true);
  // max 3: a grid too big to be one unit (the tile case, not a prose list)
  const u = unitOf(lines, "/g/section/article[2]/div/a/img", 3, 3);
  assert.equal(u.at, "/g/section/article[2]");
  assert.deepEqual(u.lines.map((l) => l.text), ["second tile"]);
  // a tile with its three lines: the tile
  assert.deepEqual(unitOf(lines, "/g/section/article[1]/div/b/span").lines.map((l) => l.text), ["first tile", "first count", "first pic"]);
});

import { inUnit } from "../src/address.ts";
test("a unit inside a link carries the link (archive.org tiles, PLUGIN_GOAL 171)", () => {
  const L = (a, t) => ({ text: t, key: "u|" + a });
  const lines = [
    L("/g/section/article[2]/a", "/details/oneman"),
    L("/g/section/article[2]/a/item-tile/#shadow-root/div/h3", "One Man's Family"),
    L("/g/section/article[2]/a/item-tile/#shadow-root/div/span", "17K"),
    L("/g/section/article[2]/a/item-tile/#shadow-root/div/span[2]", "31"),
    L("/g/section/article[2]/div", "loose text of the dispatcher"),
  ];
  const u = unitOf(lines, "/g/section/article[2]/a/item-tile/#shadow-root/div/h3");
  assert.equal(u.at, "/g/section/article[2]/a/item-tile/#shadow-root/div");
  const texts = u.lines.map((l) => l.text);
  assert.ok(texts.includes("/details/oneman"), "the wrapping anchor's href is in the unit");
  assert.ok(!texts.includes("loose text of the dispatcher"));
  globalThis.__vertiscopePlantNoWrapLink = true;
  try { assert.ok(!unitOf(lines, "/g/section/article[2]/a/item-tile/#shadow-root/div/h3").lines.map((l) => l.text).includes("/details/oneman")); }
  finally { globalThis.__vertiscopePlantNoWrapLink = false; }
  assert.equal(inUnit("/x/a[3]", "/x/a[3]/b"), true);
  assert.equal(inUnit("/x/div", "/x/div/b"), false);
});

test("a prose list that fits is ONE unit; a list too big for one keeps the item (PLUGIN_GOAL 173)", () => {
  const L = (a, t) => ({ text: t, key: "u|" + a });
  const bullets = [L("/r/ul/li", "Familiarity with the terminal"), L("/r/ul/li[2]", "Ability to read and write code"),
                   L("/r/ul/li[3]", "Basic software debugging"), L("/r/ul/li[4]", "Enough time to commit")];
  assert.equal(unitOf(bullets, "/r/ul/li[2]").at, "/r/ul");
  globalThis.__vertiscopePlantItemAlways = true;
  try { assert.equal(unitOf(bullets, "/r/ul/li[2]").at, "/r/ul/li[2]"); }
  finally { globalThis.__vertiscopePlantItemAlways = false; }
  // a grid of 30 tiles x 3 lines (90 > 60): the tile stays the unit
  const grid = [];
  for (let i = 1; i <= 30; i++) for (const s of ["a", "b", "c"]) grid.push(L(`/g/section/article[${i}]/${s}`, `t${i}${s}`));
  assert.equal(unitOf(grid, "/g/section/article[7]/b").at, "/g/section/article[7]");
});

// G-244 (2026-10-18, fastapi's README): an item made three lines by inline
// code reached the line minimum by itself and opened alone. A list that fits
// is the unit; a list too big for one (archive.org's grid) keeps its items.
test("a short list whose items are several lines each is one unit", () => {
  const lines = [], addrs = [];
  for (let i = 1; i <= 4; i++) for (const part of ["text()[1]", "code", "text()[2]"]) {
    lines.push({ text: `item ${i} ${part}` }); addrs.push(`/html/body/article/ol/li[${i}]/${part}`);
  }
  const got = unitOf(lines.map((l, i) => ({ ...l, key: "u|" + addrs[i] })), "/html/body/article/ol/li[2]/code");
  assert.equal(got && got.at, "/html/body/article/ol");
  assert.equal(got.lines.length, 12);
  globalThis.__vertiscopePlantItemAlways = true;
  try {
    const planted = unitOf(lines.map((l, i) => ({ ...l, key: "u|" + addrs[i] })), "/html/body/article/ol/li[2]/code");
    // Planted: the bullet (or less), never the list.
    assert.ok(planted && planted.at.startsWith("/html/body/article/ol/li[2]") && planted.lines.length < 12);
  } finally { globalThis.__vertiscopePlantItemAlways = false; }
  // Too big to be one: 30 items x 3 lines > 60 -- the item stays the unit.
  const big = [], bigA = [];
  for (let i = 1; i <= 30; i++) for (const part of ["text()[1]", "code", "text()[2]"]) { big.push({ text: "x" }); bigA.push(`/html/body/ol/li[${i}]/${part}`); }
  const g2 = unitOf(big.map((l, i) => ({ ...l, key: "u|" + bigA[i] })), "/html/body/ol/li[5]/code");
  assert.equal(g2 && g2.at, "/html/body/ol/li[5]");
});

// ...and a small row of TILES stays one tile per panel (G-220): their items
// hold images and headings, not inline prose.
test("a small list of tiles keeps each tile its own unit", () => {
  const lines = [], addrs = [];
  for (let i = 1; i <= 4; i++) for (const part of ["a/img", "a/h3/text()", "div/span"]) {
    lines.push({ text: `tile ${i} ${part}` }); addrs.push(`/html/body/section/ul/li[${i}]/${part}`);
  }
  const got = unitOf(lines.map((l, i) => ({ ...l, key: "u|" + addrs[i] })), "/html/body/section/ul/li[2]/a/h3/text()");
  assert.equal(got && got.at, "/html/body/section/ul/li[2]");
});

// G-251: a part of an item is not the unit. A bandcamp track row holds its
// title, "from", "by" (three lines) inside a sub-block; the row's image and
// its title opened two panels (2026-10-18).
test("a track row's image and its title open the same unit -- the row", () => {
  const lines = [], addrs = [];
  for (let i = 1; i <= 5; i++) {
    const li = `/html/body/ol/li${i > 1 ? `[${i}]` : ""}`;
    for (const part of ["div/button/text()", "div/a", "div[2]/button/div/div/img", "div[2]/button/div/div[2]/text()[1]",
                        "div[2]/button/div/div[2]/text()[2]", "div[2]/button/div/div[2]/text()[3]"]) {
      lines.push({ text: `row ${i} ${part}` }); addrs.push(`${li}/${part}`);
    }
  }
  const keyed = lines.map((l, i) => ({ ...l, key: "u|" + addrs[i] }));
  const img = unitOf(keyed, "/html/body/ol/li[3]/div[2]/button/div/div/img");
  const title = unitOf(keyed, "/html/body/ol/li[3]/div[2]/button/div/div[2]");
  assert.equal(img && img.at, "/html/body/ol/li[3]");
  assert.equal(title && title.at, "/html/body/ol/li[3]");
  assert.equal(title.lines.length, 6);
  // A chunk that IS one row (no list among its lines) is whole.
  const one = keyed.filter((_l, i) => addrs[i].startsWith("/html/body/ol/li[2]/"));
  assert.equal(unitOf(one, "/html/body/ol/li[2]/div[2]/button/div/div[2]").lines.length, 6);
  // Planted: the first level with three lines -- the title block alone.
  globalThis.__vertiscopePlantSubUnit = true;
  try { assert.equal(unitOf(keyed, "/html/body/ol/li[3]/div[2]/button/div/div[2]").at, "/html/body/ol/li[3]/div[2]/button/div/div[2]"); }
  finally { globalThis.__vertiscopePlantSubUnit = false; }
});
