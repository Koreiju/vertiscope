// G-221: going back to a page has its chunk map at once, before the store answers.
import test from "node:test";
import assert from "node:assert/strict";
import { ChunkMap } from "../src/chunkmap.ts";

const A = "https://a.test/p", B = "https://b.test/q";
function slowSidecar(maps, gate) {
  return { pageMap: async (url) => { await gate.promise; return maps[url] || null; } };
}
function deferred() { let r; const p = new Promise((res) => (r = res)); return { promise: p, resolve: r }; }

test("a page left and returned to has its map before the store answers", async () => {
  ChunkMap.plantNoCache = false;
  const m = new ChunkMap();
  const maps = { [A]: { chunks: { c1: ["/html/body/p[1]"], c2: ["/html/body/p[2]"] }, nodes: [] }, [B]: { chunks: { d1: ["/html/body/div"] }, nodes: [] } };
  let g = deferred(); g.resolve(); await m.load(slowSidecar(maps, g), A);
  g = deferred(); g.resolve(); await m.load(slowSidecar(maps, g), B);
  const slow = deferred();
  const back = m.load(slowSidecar(maps, slow), A);       // the store has not answered yet
  assert.deepEqual([...m.stored].sort(), ["c1", "c2"]);  // ...and the map is already A's
  assert.equal(m.cacheStats.hits, 1);
  slow.resolve(); assert.equal(await back, true);
  assert.deepEqual(m.cids().sort(), ["c1", "c2"]);
});

test("planted no cache: the returned-to page starts empty until the store answers", async () => {
  ChunkMap.plantNoCache = true;
  try {
    const m = new ChunkMap();
    const maps = { [A]: { chunks: { c1: ["/html/body/p[1]"] }, nodes: [] }, [B]: { chunks: {}, nodes: [] } };
    let g = deferred(); g.resolve(); await m.load(slowSidecar(maps, g), A);
    g = deferred(); g.resolve(); await m.load(slowSidecar(maps, g), B);
    const slow = deferred();
    const back = m.load(slowSidecar(maps, slow), A);
    assert.equal(m.stored.size, 0);
    slow.resolve(); await back;
  } finally { ChunkMap.plantNoCache = false; }
});
