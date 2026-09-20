/**
 * Live confirmation, keyed by requirement id.
 *
 *   node confirm.mjs                 # every registered check
 *   node confirm.mjs G-6 G-53        # just these
 *
 * **Why this exists rather than more one-off probes.** `design_state.py`
 * computes each row's status from the PRD, which catches a status that drifts
 * from what the document says. It cannot catch a status that drifts from what
 * the APPLICATION does -- and that is the drift that matters. `G-6` sat in
 * `Confirm` citing "31 nodes and 30 edges"; live it was 26 and **0**, and the
 * row had been wrong for as long as the debug port had been shut.
 *
 * So a row is confirmed by a check that RUNS, against the loaded plugin and
 * the running sidecar, and can be run again. A row with no check here is
 * visible as `no live check` rather than quietly assumed -- which is the same
 * denominator discipline `CLAUDE.md` asks for everywhere else.
 *
 * Two rules every check follows:
 *
 *  - **It reloads nothing and assumes nothing about order.** Checks run
 *    against whatever state the pane is in, and any that needs a particular
 *    state establishes it itself.
 *  - **It reports EVIDENCE, not a boolean.** `pass` is derived from numbers
 *    that are written out, so a reader can disagree with the verdict without
 *    re-running anything.
 */

import { writeFileSync, mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { evaluate } from "./cdp.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..");
const SIDECAR = process.env.DOMVEC_SIDECAR || "http://127.0.0.1:8788";

const GRAPH_VIEW = "domvec-graph-view";

/** Evaluate in the pane, with the graph view already resolved as `v`. */
const inPane = (body) => evaluate(`(async () => {
  const leaves = app.workspace.getLeavesOfType(${JSON.stringify(GRAPH_VIEW)});
  const v = leaves[0] && leaves[0].view;
  if (!v) return { error: "graph pane not open" };
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  ${body}
})()`);

const ask = async (path) => {
  const res = await fetch(`${SIDECAR}${path}`);
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
};

// --------------------------------------------------------------------------

const CHECKS = [
  {
    id: "G-53",
    asks: "the projector draws PAGES by default, not chunks",
    async run() {
      const d = await ask("/layout");
      return {
        pass: d.level === "page" && d.n > 0 && d.chunks > d.n,
        evidence: { level: d.level, nodes: d.n, chunks: d.chunks },
      };
    },
  },
  {
    id: "D-11",
    asks: "`?space=S3` reaches the DEFAULT level and says which fit it gave",
    async run() {
      const [eu, s3] = await Promise.all([
        ask("/layout?level=page"),
        ask("/layout?level=page&space=S3"),
      ]);
      return {
        // Both arms: the field exists, and it actually CHANGES. A reply that
        // always said "euclidean" would pass a presence check while the
        // defect stood.
        pass: eu.space === "euclidean" && s3.space === "S3",
        evidence: { euclidean: eu.space, requested_s3: s3.space, n: s3.n },
      };
    },
  },
  {
    id: "G-6",
    asks: "patricia-trie links are DRAWN, with endpoints that resolve",
    async run() {
      const got = await inPane(`
        for (let i = 0; i < 60 && !(v.graph && v.graph.graphData().nodes.length); i++) await sleep(500);
        // Establish the state this check is about, rather than inheriting
        // whatever the last run left. Run twice in a row without this, the
        // second run picks an already-unfolded node, adds nothing, and
        // reports a failure that is the harness's and not the app's.
        const fresh = await (await fetch(${JSON.stringify(SIDECAR)} + "/layout?level=page")).json();
        const priorNodes = v.graph.graphData().nodes.length;
        v.graph.graphData({ nodes: fresh.nodes.map(n => v.nodeFrom(n)), links: [] });
        await sleep(400);
        const before = v.graph.graphData();
        // **Counts, taken NOW.** \`graphData()\` hands back the graph's own
        // live arrays, not a snapshot, so holding \`before\` and reading
        // \`.length\` after the unfold reads the AFTER state through it --
        // this check reported 122 nodes before and 122 after, and called a
        // working unfold a failure.
        const nodesBefore = before.nodes.length;
        const linksBefore = before.links.length;
        const reset = { prior: priorNodes, fetched: fresh.nodes.length,
                        after_reset: nodesBefore };
        const target = before.nodes.filter(n => n.url && !n.unfolded)
          .sort((a, b) => (b.members || 0) - (a.members || 0))[0];
        if (!target) return { error: "no foldable node" };
        const reply = await v.sidecar.unfold(target.url, target.path || "");
        await v.unfoldNode(target);
        await sleep(1200);
        const after = v.graph.graphData();
        const byId = new Map(after.nodes.map(n => [n.id, n]));
        let unresolved = 0, dangling = 0;
        for (const l of after.links) for (const e of [l.source, l.target]) {
          if (typeof e === "string" || typeof e === "number") unresolved++;
          else if (!e || !byId.has(e.id)) dangling++;
        }
        // "Drawn" is the word in the requirement, and endpoint resolution is
        // not it -- a link can resolve and still never reach the canvas.
        const lines = after.links.filter(l => l.__lineObj && l.__lineObj.parent
                                           && l.__lineObj.visible).length;
        return {
          reset,
          returned_edges: (reply && reply.edges || []).length,
          links_before: linksBefore, links_after: after.links.length,
          nodes_before: nodesBefore, nodes_after: after.nodes.length,
          unresolved, dangling, line_objects_in_scene: lines,
        };
      `);
      if (got.error) return { pass: false, evidence: got };
      return {
        pass: got.returned_edges > 0
           && got.links_after > got.links_before
           && got.unresolved === 0 && got.dangling === 0
           && got.line_objects_in_scene === got.links_after,
        evidence: got,
      };
    },
  },
  {
    id: "G-54",
    asks: "unfolding UNRAVELS a path -- one step is O(depth), not the subtree",
    async run() {
      const pages = await ask("/layout?level=page");
      const biggest = pages.nodes
        .slice().sort((a, b) => (b.members || 0) - (a.members || 0))[0];
      const res = await fetch(`${SIDECAR}/unfold`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: biggest.url, path: "" }),
      });
      const d = await res.json();
      return {
        // The whole cost argument: a page of 1,173 chunks must not open into
        // 1,173 nodes. If it ever does, the unravelling has become an
        // expansion and `G-53`'s frame rate goes with it.
        pass: d.nodes.length > 0 && d.nodes.length < biggest.members / 4,
        evidence: {
          page_members: biggest.members,
          opened_to: d.nodes.length,
          edges: (d.edges || []).length,
          depth: d.depth, branches: d.branches, leaves: d.leaves,
        },
      };
    },
  },
  {
    id: "G-20",
    asks: "force-directed relaxation is SEEDED from the fit, not replacing it",
    async run() {
      const got = await inPane(`
        const d = v.graph.graphData();
        let unmoved = 0, drift = [];
        for (const n of d.nodes) {
          if (n.fitX === undefined) continue;
          const dx = (n.x - n.fitX), dy = (n.y - n.fitY), dz = (n.z - n.fitZ);
          const m = Math.hypot(dx, dy, dz);
          drift.push(m);
          if (m < 1e-6) unmoved++;
        }
        drift.sort((a, b) => a - b);
        const forces = ["charge", "link", "center", "collide"]
          .map(f => [f, !!v.graph.d3Force(f)]);
        return {
          nodes: d.nodes.length, unmoved,
          drift_p50: drift.length ? drift[Math.floor(drift.length * 0.5)] : null,
          drift_max: drift.length ? drift[drift.length - 1] : null,
          forces,
        };
      `);
      if (got.error) return { pass: false, evidence: got };
      const on = Object.fromEntries(got.forces);
      return {
        // Collision only. A charge or a link force would turn a UMAP of two
        // vector spaces into a spring layout that happened to start there.
        pass: on.collide === true && on.charge === false && on.center === false
           && got.unmoved > 0,
        evidence: got,
      };
    },
  },
  {
    id: "G-21",
    asks: "nodes never overlap, with billboards sized as panels not spheres",
    async run() {
      const got = await inPane(`
        const d = v.graph.graphData();
        const rel = v.graph.nodeRelSize();
        // The pane's own arithmetic, not a paraphrase of it. Written out by
        // hand this read \`sphere * 1.75 * sqrt(2)\` -- 41% too large -- and
        // invented 49 overlapping pairs that were not there. A check that
        // reimplements what it measures can fail in either direction.
        //   billboardEdge = sphere * PANEL_GAIN * SQRT2
        //   drawnRadius   = billboardEdge * SQRT1_2 = sphere * PANEL_GAIN
        const PANEL_GAIN = 1.75;
        const sphereOf = (n) => Math.cbrt(Math.max(n.val ?? 1, 1e-9)) * rel;
        const radius = (n) => (n.image && n.image.src)
          ? sphereOf(n) * PANEL_GAIN
          : sphereOf(n);
        const ns = d.nodes.filter(n => Number.isFinite(n.x));
        const sample = ns.slice(0, 1200);
        let pairs = 0, worst = 0, panels = 0, inBand = 0;
        for (let i = 0; i < sample.length; i++) {
          for (let j = i + 1; j < sample.length; j++) {
            const a = sample[i], b = sample[j];
            const d = Math.hypot(a.x-b.x, a.y-b.y, a.z-b.z);
            const ra = radius(a), rb = radius(b);
            if (d - ra - rb < 0) {
              pairs++; worst = Math.max(worst, ra + rb - d);
              if ((a.image&&a.image.src)||(b.image&&b.image.src)) panels++;
            } else if (d - (ra + rb) * 1.25 < 0) {
              // The quarter-distance safety factor the collider actually
              // runs at. Reported apart from real overlap: a pair inside the
              // band is the requirement's margin being used, not a defect.
              inBand++;
            }
          }
        }
        return { sampled: sample.length,
                 checked: sample.length * (sample.length - 1) / 2,
                 overlapping: pairs, worst: Math.round(worst * 100) / 100,
                 involving_a_panel: panels, inside_clearance_band: inBand };
      `);
      if (got.error) return { pass: false, evidence: got };
      return { pass: got.overlapping === 0, evidence: got };
    },
  },
  {
    id: "G-40",
    asks: "clicking a node takes the BROWSER to that chunk, same session",
    async run() {
      const got = await evaluate(`(async () => {
        const sleep = (ms) => new Promise(r => setTimeout(r, ms));
        await app.commands.executeCommandById("domvec-open-browser");
        await app.commands.executeCommandById("domvec-open-graph");
        await sleep(2500);
        const gv = app.workspace.getLeavesOfType("domvec-graph-view")[0];
        const bv = app.workspace.getLeavesOfType("domvec-browser-view")[0];
        const v = gv && gv.view, b = bv && bv.view;
        if (!v || !b) return { error: "panes not open",
                               types: app.workspace.getLeavesOfType("domvec-browser-view").length };
        for (let i = 0; i < 60 && !(v.graph && v.graph.graphData().nodes.length); i++) await sleep(500);

        // A node with a real address to scroll to, from a page that is
        // cheap to load. Unfold once so chunk-level nodes exist at all.
        const page = v.graph.graphData().nodes
          .filter(n => n.url && n.url.startsWith("https://books.toscrape.com/"))
          .sort((a, b) => (b.members||0) - (a.members||0))[0];
        if (!page) return { error: "no books.toscrape page in the corpus" };
        await v.unfoldNode(page);
        await sleep(1200);
        // The DEEPEST address, not the first. /html/body/div is the whole
        // page and is trivially in view, so a check that accepted it would
        // pass on a browser that scrolled nowhere at all.
        // (No backticks in here: this comment lives inside a template
        // literal, and one backtick closes it.)
        const target = v.graph.graphData().nodes
          .filter(n => n.url === page.url && n.path && n.path !== "" && !n.unfolded)
          .sort((a, b) => String(b.path).split("/").length
                        - String(a.path).split("/").length)[0];
        if (!target) return { error: "unfold produced no addressed node" };

        // The real click path, not a direct call to the callback: whatever
        // the pane does when a reader clicks is what is under test.
        const handler = v.graph.onNodeClick();
        if (typeof handler !== "function") return { error: "no click handler" };
        const urlBefore = b.webview ? b.webview.getURL() : null;
        // Start from a deliberately WRONG place, so the scroll has to happen.
        //
        // Without this the check was vacuous: the addressed node is a page
        // container 3,000px tall, so its box spans the viewport and reads
        // "in view" at any scroll position, including none. Park the page at
        // the bottom first and the click has to move it.
        let parked = null;
        if (urlBefore === target.url) {
          try {
            parked = await b.webview.executeJavaScript(
              "(function(){window.scrollTo(0, document.body.scrollHeight);" +
              "return Math.round(window.scrollY);})()");
            await sleep(400);
          } catch (e) { parked = null; }
        }
        handler(target);
        for (let i = 0; i < 60; i++) {
          await sleep(500);
          if (b.webview && b.webview.getURL() === target.url && !b.webview.isLoading()) break;
        }
        await sleep(1500);
        // Measured in the PAGE, not read off a status string. The status bar
        // is shared with the live-capture loop, which overwrites it about
        // once a second -- asserting on it tested which message won the race.
        let seen = null;
        try {
          // Built by concatenation on purpose. This was a template literal
          // nested inside the one evaluate already wraps everything in,
          // and the escaping collapsed: the xpath interpolated as bare
          // html, and the page answered 'html is not defined'.
          const xp = JSON.stringify(target.path);
          seen = await b.webview.executeJavaScript(
            "(function(){var r=document.evaluate(" + xp + ",document,null," +
            "XPathResult.FIRST_ORDERED_NODE_TYPE,null);" +
            "var n=r.singleNodeValue; if(!n) return {found:false};" +
            "if(n.nodeType===3) n=n.parentElement; if(!n) return {found:false};" +
            "var box=n.getBoundingClientRect();" +
            "return {found:true, top:Math.round(box.top)," +
            "height:Math.round(window.innerHeight)," +
            "in_view: box.top < window.innerHeight && box.bottom > 0," +
            "page_scrolled: Math.round(window.scrollY)};})()");
        } catch (e) { seen = { threw: String(e).slice(0, 80) }; }
        return {
          clicked: { url: target.url.slice(0, 60), xpath: String(target.path).slice(0, 60) },
          url_before: urlBefore,
          url_after: b.webview ? b.webview.getURL() : null,
          parked_at: parked,
          element: seen,
        };
      })()`);
      if (got.error) return { pass: false, evidence: got };
      const el = got.element || {};
      // Three things, because any two of them pass while broken:
      //   the browser is on the right page,
      //   the addressed element is in the viewport,
      //   and the viewport MOVED off where it was parked.
      const moved = got.parked_at === null || got.parked_at === undefined
        ? true                                   // it had to navigate anyway
        : el.page_scrolled !== got.parked_at;
      return {
        pass: got.url_after === got.clicked.url
           && !!(el.found && el.in_view) && moved,
        evidence: got,
      };
    },
  },
  {
    id: "G-39",
    asks: "right-click ports the markdown AND rings the node in the projector",
    async run() {
      const got = await evaluate(`(async () => {
        const sleep = (ms) => new Promise(r => setTimeout(r, ms));
        await app.commands.executeCommandById("domvec-open-browser");
        await app.commands.executeCommandById("domvec-open-graph");
        await sleep(2000);
        const bv = app.workspace.getLeavesOfType("domvec-browser-view")[0];
        const gv = app.workspace.getLeavesOfType("domvec-graph-view")[0];
        const b = bv && bv.view, v = gv && gv.view;
        if (!b || !b.webview) return { error: "no browser pane" };
        if (v) { for (let i = 0; i < 60 && !(v.graph && v.graph.graphData().nodes.length); i++) await sleep(500); }
        const want = "https://books.toscrape.com/";
        if (b.webview.getURL() !== want) {
          b.go(want);
          for (let i = 0; i < 40; i++) {
            await sleep(400);
            if (!b.webview.isLoading() && b.webview.getURL() === want) break;
          }
        }
        await sleep(800);
        // A real element's centre, read from the page. Picking coordinates
        // by hand would test whatever happened to be at 200,300.
        const at = await b.webview.executeJavaScript(
          "(function(){var e=document.querySelector('article.product_pod h3 a');" +
          "if(!e) return null;" +
          // Into view FIRST. The element sat at y=1779 on an unscrolled
          // page and elementFromPoint answers null outside the viewport,
          // which is a position a real right-click cannot be made from.
          "e.scrollIntoView({block:'center'});" +
          "var r=e.getBoundingClientRect();" +
          "return {x:Math.round(r.left+r.width/2), y:Math.round(r.top+r.height/2)," +
          "text:(e.textContent||'').slice(0,40)};})()");
        if (!at) return { error: "the page has no product link to point at" };
        b.show("browser");
        await b.portMarkdown(at.x, at.y);
        await sleep(1200);
        const body = b.markdownWrap.querySelector(".domvec-browser-mdbody");
        const head = b.markdownWrap.querySelector(".domvec-browser-mdhead");
        return {
          pointed_at: at,
          face: b.face,
          heading: head ? head.textContent : null,
          rendered_chars: body ? (body.innerText || "").length : 0,
          // Rendered, not dumped: a code block would have no elements.
          rendered_elements: body ? body.querySelectorAll("*").length : 0,
          // Relative targets must have been resolved against the PAGE.
          // Rendered as-written they ask Obsidian for a vault file and
          // come back "could not be found".
          links: body ? Array.from(body.querySelectorAll("a[href], img[src]"))
            .map(e => e.getAttribute("href") || e.getAttribute("src"))
            .slice(0, 4) : [],
          status: b.status ? b.status.textContent : null,
          // The other half of the correspondence (G-38, as far as it is
          // built): the same chunk is ringed in the projector.
          ringed: v ? v.graph.graphData().nodes.filter(n => n.hovered).length : null,
          ringed_level: v
            ? (v.graph.graphData().nodes.find(n => n.hovered) || {}).level || null
            : null,
        };
      })()`);
      if (got.error) return { pass: false, evidence: got };
      return {
        // Switched face, resolved to an address, and produced RENDERED
        // markdown -- not a placeholder and not a blob of source text.
        pass: got.face === "markdown"
           && !!got.heading && got.heading.startsWith("/html")
           && got.rendered_chars > 0 && got.rendered_elements > 0
           && (got.links || []).every(
                (u) => !u || /^[a-z][a-z0-9+.-]*:/i.test(u))
           && got.ringed === 1,
        evidence: got,
      };
    },
  },
  {
    id: "G-69",
    asks: "retrieval is a scrolled ranking, not top-k",
    async run() {
      const first = await ask("/search?q=http+header&limit=12");
      const next = await ask("/search?q=http+header&limit=12&offset=12");
      const ids = new Set((first.hits || []).map((h) => h.cid));
      const fresh = (next.hits || []).filter((h) => !ids.has(h.cid)).length;
      return {
        // The offset has to yield NEW hits. A backend that ignored it would
        // return the same twelve and a scrolling list would stutter forever.
        pass: (first.hits || []).length > 0 && fresh > 0,
        evidence: { first: (first.hits || []).length,
                    second_page: (next.hits || []).length, new_in_second: fresh },
      };
    },
  },
  {
    id: "G-64",
    asks: "a cross-page ranking fits the 256 pure-text window",
    async run() {
      const d = await ask("/search?q=http+header&budget=256");
      const total = (d.hits || []).reduce((a, h) => a + (h.tokens || 0), 0);
      return {
        pass: (d.hits || []).length > 0 && total <= 256,
        evidence: { hits: (d.hits || []).length, tokens: total, budget: 256 },
      };
    },
  },
];

// --------------------------------------------------------------------------

const wanted = process.argv.slice(2);
const chosen = wanted.length
  ? CHECKS.filter((c) => wanted.includes(c.id))
  : CHECKS;

const results = [];
for (const check of chosen) {
  let got;
  try {
    got = await check.run();
  } catch (err) {
    got = { pass: false, evidence: { threw: String(err && err.message || err) } };
  }
  results.push({ id: check.id, asks: check.asks, ...got });
  const mark = got.pass ? "PASS" : "FAIL";
  console.log(`${mark}  ${check.id}  ${check.asks}`);
  if (!got.pass) console.log("      " + JSON.stringify(got.evidence));
}

const when = new Date().toISOString().slice(0, 10);
const passed = results.filter((r) => r.pass).length;

const lines = [
  "# Live confirmations",
  "",
  "*Generated by `obsidian-plugin/confirm.mjs` against the RUNNING plugin and",
  "sidecar. Do not edit.*",
  "",
  `Run ${when} — **${passed} of ${results.length} pass**.`,
  "",
  "A row here has been seen to work in the application. A requirement absent",
  "from this file has not been, whatever its status column says — which is the",
  "distinction `G-6` cost: it sat in `Confirm` citing 31 nodes and 30 edges,",
  "and live it was 26 and 0.",
  "",
  "| id | asks | verdict | evidence |",
  "|---|---|---|---|",
];
for (const r of results) {
  lines.push(`| \`${r.id}\` | ${r.asks} | ${r.pass ? "**pass**" : "**FAIL**"} | `
    + "`" + JSON.stringify(r.evidence) + "`" + " |");
}
lines.push("");

mkdirSync(join(ROOT, "build_analytics"), { recursive: true });
writeFileSync(join(ROOT, "build_analytics", "live_confirmations.md"),
              lines.join("\n"), "utf8");
writeFileSync(join(ROOT, "build_analytics", "live_confirmations.json"),
              JSON.stringify({ when, results }, null, 2), "utf8");

console.log(`\n${passed} of ${results.length} pass ` +
            `-> build_analytics/live_confirmations.md`);
process.exitCode = passed === results.length ? 0 : 1;
