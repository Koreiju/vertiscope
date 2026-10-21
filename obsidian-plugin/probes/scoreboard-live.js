/**
 * The scoreboard rows that only exist in the running app.
 *
 *   node cdp.mjs --file probes/scoreboard-live.js
 *
 * Called by `scripts/scoreboard.py --live`, which parses this as JSON. Keys
 * here must match the keys the scoreboard prints.
 *
 * Everything measured here needs a renderer: how many billboards actually got
 * a texture on to them, and how many vault edges Obsidian resolved. Neither
 * can be answered from the store -- a picture's url being present says nothing
 * about whether the host served it, and a wikilink being in a file says
 * nothing about whether Obsidian parsed it out of the callout it now sits in.
 */
(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const out = {};

  // --- the graph the app actually built --------------------------------
  const resolved = app.metadataCache.resolvedLinks || {};
  let edges = 0;
  for (const [src, targets] of Object.entries(resolved)) {
    if (!src.startsWith("pages/")) continue;
    edges += Object.values(targets).reduce((a, b) => a + b, 0);
  }
  out.resolved_edges = edges;
  out.dangling_edges = Object.entries(app.metadataCache.unresolvedLinks || {})
    .filter(([src]) => src.startsWith("pages/"))
    .reduce((a, [, t]) => a + Object.keys(t).length, 0);

  // --- billboards ------------------------------------------------------
  let leaf = app.workspace.getLeavesOfType("vertiscope-graph-view")[0];
  if (!leaf) {
    app.commands.executeCommandById("vertiscope-bridge:vertiscope-open-graph");
    for (let i = 0; i < 90 && !leaf; i++) {
      await sleep(1000);
      leaf = app.workspace.getLeavesOfType("vertiscope-graph-view")[0];
    }
  }
  const view = leaf?.view;
  if (!view?.graph) {
    out.billboards_textured = null;
    return out;
  }
  // Textures arrive one HTTP request at a time; wait until the count stops
  // moving rather than after a fixed sleep, or the number reads as a failure
  // when it is only unfinished.
  let last = -1;
  for (let i = 0; i < 30; i++) {
    await sleep(3000);
    let sprites = 0;
    let textured = 0;
    view.graph.scene().traverse((o) => {
      if (o.type === "Sprite") {
        sprites++;
        if (o.material?.map) textured++;
      }
    });
    out.sprites = sprites;
    out.sprites_textured = textured;
    if (textured === last || textured >= sprites) break;
    last = textured;
  }
  out.billboards_textured = out.sprites
    ? out.sprites_textured / out.sprites : null;

  return out;
})()
