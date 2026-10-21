/**
 * `G-6`: does unfolding a node actually DRAW the links it returns?
 *
 *   node cdp.mjs --file probes/unfold-edges.js
 *
 * This row has sat in `Confirm` because the server side was verified and the
 * pane was not: `layout.unfold` returns containment edges, and RFC 9110 opens
 * as 31 nodes and 30 edges when asked over HTTP. None of that says a link
 * reached the canvas.
 *
 * **Two ways this fails, and only one of them is visible.** A missing edge is
 * obvious. An edge whose endpoints are still STRINGS is not: `forceLink` is
 * d3's id resolver and it runs once at boot, so a link pushed in afterwards
 * keeps `source: "cid"` instead of `source: {…}`, draws nothing, and throws
 * nothing. That is exactly what removing the link force did to all 2,961
 * edges, and nothing reported it. So the assertion here is not "links went
 * up" -- it is "links went up AND every new link resolved to a node object
 * that is in the graph".
 *
 * Non-vacuity: the unfold has to produce edges at all. A node that unfolds
 * into a flat list of leaves has no containment to draw, and counting that as
 * a pass would make this probe green on a build where `addEdges` did nothing.
 * So the probe fails if the sidecar returned no edges to draw.
 */
(async () => {
  const GRAPH_VIEW = "vertiscope-graph-view";
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

  // Open the pane if it is not already open, and let the fit arrive.
  let leaves = app.workspace.getLeavesOfType(GRAPH_VIEW);
  if (!leaves.length) {
    const leaf = app.workspace.getLeaf("tab");
    await leaf.setViewState({ type: GRAPH_VIEW, active: true });
    leaves = app.workspace.getLeavesOfType(GRAPH_VIEW);
  }
  const view = leaves[0] && leaves[0].view;
  if (!view) return { error: "no graph view" };

  for (let i = 0; i < 60 && !(view.graph && view.graph.graphData().nodes.length); i++) {
    await sleep(500);
  }
  const g = view.graph;
  if (!g) return { error: "graph never initialised" };

  const before = g.graphData();
  const beforeNodes = before.nodes.length;
  const beforeLinks = before.links.length;

  // A node that HAS something under it. At page level every node is a page,
  // so take the one with the most chunks -- the deepest trie to unravel.
  const target = before.nodes
    .filter((n) => n.url)
    .sort((a, b) => (b.members || 0) - (a.members || 0))[0];
  if (!target) return { error: "no node carrying a url" };

  const got = await view.sidecar.unfold(target.url, target.path || "");
  const returnedEdges = (got && got.edges && got.edges.length) || 0;
  const returnedNodes = (got && got.nodes && got.nodes.length) || 0;

  await view.unfoldNode(target);
  await sleep(1200);

  const after = g.graphData();
  const byId = new Map(after.nodes.map((n) => [n.id, n]));

  // The quiet failure: an endpoint that never resolved.
  let unresolved = 0;
  let dangling = 0;
  for (const l of after.links) {
    for (const end of [l.source, l.target]) {
      if (typeof end === "string" || typeof end === "number") unresolved++;
      else if (!end || !byId.has(end.id)) dangling++;
    }
  }

  return {
    requirement: "G-6",
    target: { url: String(target.url).slice(0, 60), members: target.members || 0 },
    sidecar_returned: { nodes: returnedNodes, edges: returnedEdges },
    nodes: { before: beforeNodes, after: after.nodes.length },
    links: { before: beforeLinks, after: after.links.length },
    links_added: after.links.length - beforeLinks,
    unresolved_endpoints: unresolved,
    dangling_endpoints: dangling,
    // The verdict, spelled out so a reader does not have to re-derive it.
    pass: returnedEdges > 0
       && after.links.length > beforeLinks
       && unresolved === 0
       && dangling === 0,
  };
})()
