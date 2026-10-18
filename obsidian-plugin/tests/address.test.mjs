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
  const u = unitOf(lines, "/g/section/article[2]/div/a/img");
  assert.equal(u.at, "/g/section/article[2]");
  assert.deepEqual(u.lines.map((l) => l.text), ["second tile"]);
  // a tile with its three lines: the tile
  assert.deepEqual(unitOf(lines, "/g/section/article[1]/div/b/span").lines.map((l) => l.text), ["first tile", "first count", "first pic"]);
});
