/**
 * `G-20` / `G-21`: do the nodes stop overlapping WITHOUT the simulation
 * rewriting the embedding underneath them?
 *
 *   node cdp.mjs --file probes/collider.js
 *
 * Two claims that only mean something together, which is why one probe asserts
 * both. A layout can reach zero overlap trivially by ceasing to be the fit --
 * a spring layout overlaps nothing and has thrown the vector space away -- so
 * "no overlap" alone is passable by the exact failure the design fears. And
 * "the embedding is intact" alone is passed by doing nothing at all.
 *
 * Asserted, with the non-vacuity arms marked:
 *
 *   1. no pair of nodes overlaps, scored at the radius each node DRAWS at
 *   2. no pair sits inside the quarter-distance clearance `G-21` asks for
 *   3. panels are scored as PANELS -- the non-vacuity arm for 1 and 2. A
 *      collider that sizes every node as a sphere reaches zero by the sphere
 *      measure while 96 pairs of a 1,200 sample still overlap on screen, every
 *      one of them involving a picture node. The arm asserts the sample
 *      actually contains panels, so a corpus with media off cannot pass this
 *      by having nothing to get wrong.
 *   4. neighbourhood retention beats a null arm by a wide margin -- of a
 *      node's ten nearest neighbours in the fit, how many are still its ten
 *      nearest. The null shuffles the final positions between nodes: same
 *      cloud, no correspondence. It scores ~0.001 here, so retention is being
 *      read against a measured floor rather than a hoped-for one.
 *   5. a large minority of nodes did not move AT ALL. Collision acts only on a
 *      node with something inside its radius, so a node with room must keep
 *      the fit's coordinates exactly. If this reaches zero, some force other
 *      than collision is running and the layout is no longer the projection.
 *   6. every link resolves to node objects. `forceLink` is also d3's id
 *      resolver, so removing it -- rather than zeroing its strength -- leaves
 *      2,961 links holding strings, and every patricia and inter-note edge
 *      silently stops drawing with nothing reporting a failure.
 *
 * Needs the graph pane's sidecar fit. Opens its own pane and leaves it open.
 */
(async () => {
  const K = 10, SAMPLE = 300, SETTLE_MS = 25000, GAIN = 1.75, SAFETY = 1.25;
  const out = { ok: true, checks: [], failures: [] };
  const check = (name, pass, detail) => {
    out.checks.push({ name, pass, detail });
    if (!pass) { out.ok = false; out.failures.push(`${name}: ${detail}`); }
  };

  const plugin = app.plugins.plugins["vertiscope-bridge"];
  if (!plugin) return JSON.stringify({ ok: false, error: "plugin not loaded" });
  if (!(await plugin.sidecar.health())) {
    return JSON.stringify({ ok: false, error: "no sidecar" });
  }

  // The PLUGIN is reloaded, not just the pane -- and that distinction is the
  // difference between this probe measuring the build and measuring nothing.
  // Reopening the view re-runs the old module that is still resident, so a
  // probe run straight after a build scores the code the build replaced. Found
  // by planting the panel-blind collider and watching every number come back
  // identical to the clean run, down to a random shuffle landing on 0.004
  // twice -- a green that was reporting on a file nobody had loaded.
  app.workspace.getLeavesOfType("vertiscope-graph-view").forEach((l) => l.detach());
  await app.plugins.disablePlugin("vertiscope-bridge");
  await app.plugins.enablePlugin("vertiscope-bridge");
  await new Promise((r) => setTimeout(r, 800));
  app.commands.executeCommandById("vertiscope-bridge:vertiscope-open-graph");

  let view = null;
  for (let i = 0; i < 90; i++) {
    view = app.workspace.getLeavesOfType("vertiscope-graph-view")[0]?.view;
    const st = view?.contentEl?.querySelector(".vertiscope-graph-status")?.textContent;
    if (st && st !== "fitting…" && !/no sidecar/.test(st) && view.graph) break;
    await new Promise((r) => setTimeout(r, 1000));
  }
  if (!view?.graph) return JSON.stringify({ ok: false, error: "graph never built" });
  const fg = view.graph;
  // One cooling cycle, run to completion. Measuring before the simulation
  // stops scores a moment, not a layout.
  await new Promise((r) => setTimeout(r, SETTLE_MS));

  const rel = fg.nodeRelSize();
  const media = fg.nodeThreeObject() != null;
  const isPanel = (n) => !!(media && n.image && n.image.src);
  // The radius the RENDERER uses, restated here on purpose: a probe that
  // imported the plugin's own function would agree with it by construction
  // and could not catch the two disagreeing.
  const sphere = (n) => Math.cbrt(Math.max(n.val ?? 1, 1e-9)) * rel;
  const drawn = (n) => isPanel(n) ? sphere(n) * GAIN : sphere(n);

  const nodes = fg.graphData().nodes;
  const N = Math.min(nodes.length, 1200);
  const s = nodes.slice(0, N);
  let over = 0, clear = 0, worst = 0, panelPairs = 0;
  for (let i = 0; i < N; i++) for (let j = i + 1; j < N; j++) {
    const a = s[i], b = s[j];
    const d = Math.hypot(a.x - b.x, a.y - b.y, a.z - b.z);
    const need = drawn(a) + drawn(b);
    if (d < need * SAFETY) clear++;
    if (d < need) { over++; worst = Math.max(worst, need - d); }
    if (isPanel(a) || isPanel(b)) panelPairs++;
  }
  check("no overlapping pairs", over === 0,
        `${over} of ${(N * (N - 1)) / 2}, worst penetration ${worst.toFixed(2)}`);
  check("clearance respected", clear === 0,
        `${clear} pairs inside ${SAFETY}x the drawn radius`);
  check("panels are in the sample [non-vacuity]", panelPairs > 0,
        `${s.filter(isPanel).length} panels, ${panelPairs} pairs involving one`);

  const step = Math.max(1, Math.floor(nodes.length / SAMPLE));
  const probe = nodes.filter((n, i) => n.fitX !== undefined && i % step === 0)
                     .slice(0, SAMPLE);
  const near = (self, get) => {
    const [px, py, pz] = get(self); const best = [];
    for (const o of nodes) {
      if (o === self) continue;
      const [x, y, z] = get(o);
      const d = (x - px) ** 2 + (y - py) ** 2 + (z - pz) ** 2;
      if (best.length < K) { best.push([d, o]); best.sort((a, b) => a[0] - b[0]); }
      else if (d < best[K - 1][0]) { best[K - 1] = [d, o]; best.sort((a, b) => a[0] - b[0]); }
    }
    return new Set(best.map((b) => b[1]));
  };
  const FIT = (n) => [n.fitX, n.fitY, n.fitZ];
  const NOW = (n) => [n.x, n.y, n.z];
  const perm = nodes.map((n) => [n.x, n.y, n.z]);
  for (let i = perm.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    [perm[i], perm[j]] = [perm[j], perm[i]];
  }
  const shuffled = new Map(nodes.map((n, i) => [n, perm[i]]));
  const SHUF = (n) => shuffled.get(n);

  const retention = (set, get) => {
    if (!set.length) return 0;
    let t = 0;
    for (const p of set) {
      const a = near(p, FIT), b = near(p, get);
      let h = 0; for (const x of a) if (b.has(x)) h++;
      t += h / K;
    }
    return t / set.length;
  };
  const kept = retention(probe, NOW);
  const nul = retention(probe, SHUF);
  check("embedding survives relaxation", kept > 0.6,
        `retention ${kept.toFixed(3)} (panels ` +
        `${retention(probe.filter(isPanel), NOW).toFixed(3)}, spheres ` +
        `${retention(probe.filter((n) => !isPanel(n)), NOW).toFixed(3)})`);
  check("null arm scores near zero [non-vacuity]", nul < 0.05,
        `shuffled retention ${nul.toFixed(3)} -- if this were high the ` +
        `measure would be reading the cloud's shape, not its correspondence`);

  const still = nodes.filter((n) => n.fitX !== undefined &&
    Math.hypot(n.x - n.fitX, n.y - n.fitY, n.z - n.fitZ) < 1e-6).length;
  check("nodes with room did not move [non-vacuity]", still > nodes.length * 0.1,
        `${still} of ${nodes.length} exactly where the fit put them`);

  const links = fg.graphData().links;
  const resolved = links.filter((l) => typeof l.source === "object" &&
                                       l.source.x !== undefined).length;
  check("every link resolves to nodes", links.length > 0 && resolved === links.length,
        `${resolved} of ${links.length}`);

  return JSON.stringify(out, null, 1);
})()
