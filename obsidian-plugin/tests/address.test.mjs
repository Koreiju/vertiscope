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
