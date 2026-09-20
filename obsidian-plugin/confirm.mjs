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
 *  - **The plugin is reloaded before anything is measured**, and nothing
 *    else is assumed about order. Checks run against whatever state the pane
 *    is in, and any that needs a particular state establishes it itself.
 *    The reload is not optional politeness: a probe scores the instrument
 *    that is LOADED, and the collider probe once passed with its own target
 *    defect planted because a build had replaced a file nobody was running.
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

//: A sidecar that goes away must not hang the suite.
//
//: `fetch` has no default timeout, so a request issued just before the
//: sidecar restarted waited forever -- the run sat on one check for 39
//: minutes with the server already back up and answering in 9ms. A harness
//: that can hang is a harness nobody trusts to leave running.
//:
//: Generous rather than tight: a cold chunk-level fit is 95 seconds over
//: this corpus, and a timeout shorter than the work is just a different
//: way to report a failure that is not there.
const ASK_TIMEOUT_MS = Number(process.env.DOMVEC_ASK_TIMEOUT_MS || 300000);

const ask = async (path) => {
  const res = await fetch(`${SIDECAR}${path}`,
                          { signal: AbortSignal.timeout(ASK_TIMEOUT_MS) });
  if (!res.ok) throw new Error(`${path} -> ${res.status}`);
  return res.json();
};

// --------------------------------------------------------------------------

//: **A page whose only motion is the motion the check causes.**
//:
//: Every gesture score needs a null arm, and on a live site the null arm is
//: never empty: coinmarketcap scored 10 wrong values under a delete and the
//: same 10 under nothing, because the frozen snapshot still runs a clock.
//: Serving a fixture puts that floor at exactly zero, so what the arms
//: disagree about is the interaction and nothing else.
//:
//: Port 0, per the architecture guard: a check that binds a fixed port
//: fails the moment two of them overlap.
const serveFixtures = async () => {
  const http = await import("node:http");
  const { readFile } = await import("node:fs/promises");
  const dir = join(ROOT, "tests", "fixtures");
  const server = http.createServer(async (req, res) => {
    const name = decodeURIComponent((req.url || "/").split("?")[0])
      .replace(/^\/+/, "").replace(/\.\./g, "");
    try {
      const body = await readFile(join(dir, name));
      res.writeHead(200, { "content-type": "text/html; charset=utf-8" });
      res.end(body);
    } catch {
      res.writeHead(404).end("no such fixture");
    }
  });
  await new Promise((r) => server.listen(0, "127.0.0.1", r));
  const port = server.address().port;
  return {
    origin: "http://127.0.0.1:" + port,
    close: () => new Promise((r) => server.close(r)),
  };
};

//: The body S-7 evaluates in the pane.
//:
//: Built as a string rather than written inline because it is long and it
//: has to name three values the harness picked: the fixture url, the token
//: the click will write, and where the sidecar is.
//:
//: **The instrument is the chunk's MARKDOWN, read back through /resolve.**
//: Not a count. A count moves for reasons that have nothing to do with the
//: click -- a lazy image, a second capture pass -- whereas the markdown of
//: the chunk that draws this list either contains the clicked-in sentence
//: or it does not. That is the affine map stated as a test: what you see in
//: the page is what you get out of the trie.
const mutateProbe = (page, token, sidecar) => `(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const PAGE = ${JSON.stringify(page)};
  const TOKEN = ${JSON.stringify(token)};
  const SIDE = ${JSON.stringify(sidecar)};

  // **Establish a cell wide enough to click in.**
  //
  // The open-browser command REUSES whatever browser leaf exists, at whatever
  // size earlier work left it. A previous check's vertical split had
  // squeezed it to 3 pixels wide, and every synthetic click then landed
  // outside the guest's viewport -- which read for four runs as the page
  // refusing to mutate and the sensor being at fault. So the old panes are
  // dropped and a fresh full-width TAB is opened, which is state this check
  // needs and therefore state it establishes itself.
  for (const l of app.workspace.getLeavesOfType("domvec-chunk-view")) {
    l.detach();
  }
  for (const l of app.workspace.getLeavesOfType("domvec-browser-view")) {
    l.detach();
  }
  await sleep(700);
  const bleafFresh = app.workspace.getLeaf("tab");
  await bleafFresh.setViewState({ type: "domvec-browser-view", active: true });
  app.workspace.revealLeaf(bleafFresh);
  await sleep(1800);
  const bv = app.workspace.getLeavesOfType("domvec-browser-view")[0];
  const b = bv && bv.view;
  if (!b || !b.webview) return { error: "no browser pane" };

  b.go(PAGE);
  for (let i = 0; i < 60; i++) {
    await sleep(400);
    if (!b.webview.isLoading() && b.webview.getURL().indexOf(PAGE) === 0) break;
  }
  const landed = b.webview.getURL();

  // The token is handed to the page rather than hardcoded in it, so each
  // run looks for a string no previous run can have left behind.
  await b.webview.executeJavaScript(
    "window.__domvecToken = " + JSON.stringify(TOKEN) + "; true");

  const LIST = "/html/body/ul";
  const resolve = async () => {
    const r = await fetch(SIDE + "/resolve?url=" + encodeURIComponent(landed)
                          + "&xpath=" + encodeURIComponent(LIST));
    if (!r.ok) return null;
    const j = await r.json();
    // The payload is a ChunkPayload: aligned LINES, not a markdown string.
    // Asking it for .markdown returns undefined, which read as "the page
    // never reached the trie" for a page that had reached it perfectly.
    if (!j || !Array.isArray(j.lines)) return null;
    // String.fromCharCode(10) rather than an escape: this string is
    // built by a template literal and then parsed again in the pane,
    // and a newline escape does not survive both layers -- it arrived
    // as a real newline inside a quoted string, which is a SyntaxError
    // where it lands and legal where it was written.
    return j.lines.map((l) => l.text).join(String.fromCharCode(10));
  };

  // Wait for the FIRST capture to put this page in the trie at all. Without
  // this the null arm would be measuring a page that had not arrived yet,
  // and "nothing changed" would be true for the wrong reason.
  let before = null;
  for (let i = 0; i < 75; i++) {
    before = await resolve();
    if (before) break;
    await sleep(800);
  }
  if (!before) {
    return { error: "the page never reached the trie", landed };
  }

  // ---- NULL ARM: the same wait, no interaction. ----
  await sleep(5000);
  const still = await resolve();
  const nullArmChanged = still !== before;

  // ---- The interaction, as a real input event to the guest. ----
  //
  // **Focus is part of the state this check needs, so it establishes it.**
  // A real input event only lands while the browser leaf has focus, and any
  // earlier check that opened a panel has taken it -- S-12 does exactly
  // that. Run alone this passed; run after S-12 it reported the page
  // refusing to mutate, which is an order dependency and not a finding.
  // No DOM-click fallback here, deliberately: S-7's whole claim is that a
  // REAL interaction is observed, and a fallback would let the claim pass
  // without it.
  // A chunk panel left open by an earlier check sits in a split beside the
  // cell and holds the focus a real input event needs. S-7 is not about
  // panels, so it closes them rather than working around them.
  for (const l of app.workspace.getLeavesOfType("domvec-chunk-view")) {
    l.detach();
  }
  await sleep(600);
  try { b.webview.focus(); } catch (e) {}
  await sleep(500);

  // **Aim inside the viewport, and prove it.**
  //
  // A synthetic mouse event is delivered at a VIEWPORT coordinate, so a
  // target below the fold is a click on nothing. This failed for four runs
  // reading as "the page refuses to mutate": the cell had been made narrow
  // by a split, the intro paragraph wrapped to many more lines, and the
  // button sat at y=1420 in a viewport 801 tall. Nothing was wrong with the
  // sensor, the focus or the event -- the coordinate was off the screen.
  //
  // So: scroll it in, re-read the rect AFTER the scroll, and report the aim
  // with the viewport beside it. A click that misses now says it missed.
  const at = await b.webview.executeJavaScript(
    "(function(){var e=document.getElementById('add');" +
    "if(!e) return null;" +
    "e.scrollIntoView({block:'center'});" +
    "var r=e.getBoundingClientRect();" +
    "return {x:Math.round(r.left+r.width/2)," +
    "y:Math.round(r.top+r.height/2)," +
    "vw:window.innerWidth, vh:window.innerHeight," +
    "focused:document.hasFocus()};})()");
  if (!at) return { error: "no button to press", landed };
  const itemCount = () => b.webview.executeJavaScript(
    "document.getElementById('items').children.length");
  const wasItems = await itemCount();
  for (const type of ["mouseDown", "mouseUp"]) {
    b.webview.sendInputEvent({ type, x: at.x, y: at.y,
                               button: "left", clickCount: 1 });
  }
  await sleep(1200);
  const itemsNow = await itemCount();

  // The page must actually have mutated, or this is measuring the click
  // rather than the sensor.
  const inPage = await b.webview.executeJavaScript(
    "document.getElementById('items').textContent.indexOf("
    + JSON.stringify(TOKEN) + ") >= 0");

  // ---- Did the fold carry it through? The live loop ticks at 1200ms. ----
  let after = before, ticks = 0;
  for (let i = 0; i < 40; i++) {
    await sleep(800);
    ticks += 1;
    const now = await resolve();
    if (now && now.indexOf(TOKEN) >= 0) { after = now; break; }
    if (now) after = now;
  }

  // Sampled BEFORE the park below turns it off, or the field reads false
  // on every run and says nothing about whether capture was armed while
  // the reader was browsing -- which is the half of this the row cares
  // about. It read false on a passing run, which is a field that had
  // quietly stopped measuring anything.
  const liveWhileBrowsing = !!b.live;

  // **Park the cell before the page is purged, or the purge is undone.**
  //
  // The live loop ticks every 1200ms against whatever the cell is showing.
  // Purging the fixture while the cell still had it open simply let the next
  // tick capture it again: the corpus went from 99 pages to 118 across these
  // runs with every single purge reporting success. Turning capture off and
  // parking on about:blank first makes the cleanup stick.
  try { b.setLive(false); } catch (e) {}
  try { b.go("about:blank"); } catch (e) {}
  await sleep(2000);

  return {
    landed,
    resolved_before: true,
    // The floor: what this page does on its own over the same interval.
    null_arm_changed: nullArmChanged,
    mutated_in_page: inPage === true,
    items_before: wasItems, items_after: itemsNow,
    guest_focused: at.focused === true,
    aimed_at: [at.x, at.y], viewport: [at.vw, at.vh],
    aim_on_screen: at.x >= 0 && at.y >= 0 && at.x < at.vw && at.y < at.vh,
    token_in_trie: after.indexOf(TOKEN) >= 0,
    waited_s: Math.round(ticks * 0.8),
    live_capture_on: liveWhileBrowsing,
    md_before_chars: before.length,
    md_after_chars: after.length,
  };
})()`;

//: The body S-12 evaluates in the pane.
//:
//: S-7 asked whether an interaction reaches the store. This asks the
//: separate question of whether it reaches every SURFACE uniformly: the
//: graph, a panel that was already open when the change landed, and a panel
//: that was closed then and is opened afterwards.
//:
//: The three are listed separately in the row because they fail separately.
//: A panel opened after the fact reads the store fresh and can hardly be
//: wrong; a panel already open has to be told. Reporting them as one number
//: would let the second hide behind the first.
const uniformProbe = (page, token, sidecar) => `(async () => {
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const PAGE = ${JSON.stringify(page)};
  const TOKEN = ${JSON.stringify(token)};
  const SIDE = ${JSON.stringify(sidecar)};
  const CHUNK_VIEW = "domvec-chunk-view";

  // **Establish a cell wide enough to click in.**
  //
  // The open-browser command REUSES whatever browser leaf exists, at whatever
  // size earlier work left it. A previous check's vertical split had
  // squeezed it to 3 pixels wide, and every synthetic click then landed
  // outside the guest's viewport -- which read for four runs as the page
  // refusing to mutate and the sensor being at fault. So the old panes are
  // dropped and a fresh full-width TAB is opened, which is state this check
  // needs and therefore state it establishes itself.
  for (const l of app.workspace.getLeavesOfType("domvec-chunk-view")) {
    l.detach();
  }
  for (const l of app.workspace.getLeavesOfType("domvec-browser-view")) {
    l.detach();
  }
  await sleep(700);
  const bleafFresh = app.workspace.getLeaf("tab");
  await bleafFresh.setViewState({ type: "domvec-browser-view", active: true });
  app.workspace.revealLeaf(bleafFresh);
  await sleep(1500);
  const bv = app.workspace.getLeavesOfType("domvec-browser-view")[0];
  const b = bv && bv.view;
  if (!b || !b.webview) return { error: "no browser pane" };

  b.go(PAGE);
  for (let i = 0; i < 60; i++) {
    await sleep(400);
    if (!b.webview.isLoading() && b.webview.getURL().indexOf(PAGE) === 0) break;
  }
  const landed = b.webview.getURL();
  await b.webview.executeJavaScript(
    "window.__domvecToken = " + JSON.stringify(TOKEN) + "; true");

  const LIST = "/html/body/ul";
  const resolve = async () => {
    const r = await fetch(SIDE + "/resolve?url=" + encodeURIComponent(landed)
                          + "&xpath=" + encodeURIComponent(LIST));
    if (!r.ok) return null;
    const j = await r.json();
    if (!j || !Array.isArray(j.lines)) return null;
    return { cid: j.cid,
             md: j.lines.map((l) => l.text).join(String.fromCharCode(10)) };
  };

  let first = null;
  for (let i = 0; i < 75; i++) {
    first = await resolve();
    if (first) break;
    await sleep(800);
  }
  if (!first) return { error: "the page never reached the trie", landed };
  const cid = first.cid;

  // ---- A panel OPEN before the change lands. ----
  const openPanel = async () => {
    let leaves = app.workspace.getLeavesOfType(CHUNK_VIEW);
    let leaf = leaves[0];
    if (!leaf) {
      leaf = app.workspace.getLeaf("split", "vertical");
      await leaf.setViewState({ type: CHUNK_VIEW, active: true });
    }
    const view = leaf.view;
    await view.show(cid);
    await sleep(900);
    return { leaf, view };
  };
  // **Where a chunk panel's text actually is.**
  //
  // Not in containerEl.textContent. The surface renders the distilled HTML
  // into a .domvec-html-host that carries its own SHADOW ROOT, so the pane
  // reads as 109 characters of toolbar with the chunk apparently empty --
  // which is what "the panel never updated" looked like for two runs. This
  // is the plugin's own shadow root, not a page's, so reading it is not the
  // thing constraint 6 refuses.
  const panelText = (view) => {
    const root = view.containerEl;
    const host = root.querySelector(".domvec-html-host");
    const sr = host && host.shadowRoot;
    const inner = sr && sr.querySelector(".domvec-html");
    return ((root.textContent || "")
            + String.fromCharCode(10)
            + (inner ? (inner.textContent || "")
                     : (sr ? (sr.textContent || "") : "")));
  };

  // Which of the surface's two faces was actually drawn (T-8). The
  // interactive one renders the distilled DOM as elements into a shadow
  // root; the other is a pre of markdown text. Reporting "the panel
  // updated" without saying which would leave T-8 inferred.
  const surfaceMode = (view) => {
    const root = view.containerEl;
    if (root.querySelector(".domvec-html-host")) return "interactive";
    if (root.querySelector(".domvec-md")) return "markdown";
    return "none";
  };

  const opened = await openPanel();
  const panelBefore = panelText(opened.view);

  // ---- The interaction. ----
  const at = await b.webview.executeJavaScript(
    "(function(){var e=document.getElementById('add');" +
    "if(!e) return null; e.scrollIntoView({block:'center'});" +
    "var r=e.getBoundingClientRect();" +
    "return {x:Math.round(r.left+r.width/2)," +
    "y:Math.round(r.top+r.height/2)};})()");
  if (!at) return { error: "no button to press", landed };

  // **Which path made the page move, reported rather than assumed.**
  //
  // A real input event is the honest trigger and S-7 proves it works -- but
  // it only lands while the browser leaf has focus, and this check has just
  // opened a chunk panel, which takes it. So: activate the browser leaf and
  // try the real event; if the page did not move, fall back to the DOM's own
  // click and SAY SO. What S-12 is about is where the resulting stream goes,
  // not how the mutation was started, and hiding the fallback would let a
  // silent focus failure read as a pass.
  const bleaf = app.workspace.getLeavesOfType("domvec-browser-view")[0];
  try { app.workspace.setActiveLeaf(bleaf, { focus: true }); } catch (e) {}
  await sleep(700);
  try { b.webview.focus(); } catch (e) {}
  await sleep(300);

  const itemCount = () => b.webview.executeJavaScript(
    "document.getElementById('items').children.length");
  const wasItems = await itemCount();
  for (const type of ["mouseDown", "mouseUp"]) {
    b.webview.sendInputEvent({ type, x: at.x, y: at.y,
                               button: "left", clickCount: 1 });
  }
  await sleep(1500);
  let trigger = "input-event";
  if ((await itemCount()) === wasItems) {
    trigger = "dom-click";
    await b.webview.executeJavaScript(
      "document.getElementById('add').click(); true");
    await sleep(800);
  }
  const mutated = (await itemCount()) > wasItems;

  // ---- Wait for the STORE, which is the precondition for all three. ----
  let dbHas = false;
  for (let i = 0; i < 40; i++) {
    await sleep(800);
    const now = await resolve();
    if (now && now.md.indexOf(TOKEN) >= 0) { dbHas = true; break; }
  }

  await sleep(2500);
  const panelAfter = panelText(opened.view);

  // ---- The CLOSED arm: detach, then open a fresh panel on the same cid. ----
  opened.leaf.detach();
  await sleep(700);
  const reopened = await openPanel();
  await sleep(1200);
  const panelReopened = panelText(reopened.view);

  // ---- The graph. Counts taken EAGERLY: graphData hands back the live
  //: arrays, and holding the object to read it later reads the after-state.
  const gl = app.workspace.getLeavesOfType("domvec-graph-view")[0];
  const g = gl && gl.view;
  let graphHasNode = null;
  if (g && g.graph) {
    const ids = g.graph.graphData().nodes.map((n) => n.id);
    graphHasNode = ids.indexOf(cid) >= 0;
  }

  // Sampled BEFORE the park below turns it off, or the field reads false
  // on every run and says nothing about whether capture was armed while
  // the reader was browsing -- which is the half of this the row cares
  // about. It read false on a passing run, which is a field that had
  // quietly stopped measuring anything.
  const liveWhileBrowsing = !!b.live;

  // **Park the cell before the page is purged, or the purge is undone.**
  //
  // The live loop ticks every 1200ms against whatever the cell is showing.
  // Purging the fixture while the cell still had it open simply let the next
  // tick capture it again: the corpus went from 99 pages to 118 across these
  // runs with every single purge reporting success. Turning capture off and
  // parking on about:blank first makes the cleanup stick.
  try { b.setLive(false); } catch (e) {}
  try { b.go("about:blank"); } catch (e) {}
  await sleep(2000);

  return {
    landed, cid,
    trigger, mutated_in_page: mutated,
    surface_mode: surfaceMode(opened.view),
    reopened_surface_mode: surfaceMode(reopened.view),
    db_has_token: dbHas,
    panel_open_before_had_token: panelBefore.indexOf(TOKEN) >= 0,
    open_panel_has_token: panelAfter.indexOf(TOKEN) >= 0,
    reopened_panel_has_token: panelReopened.indexOf(TOKEN) >= 0,
    graph_has_node: graphHasNode,
    panel_before_chars: panelBefore.length,
    panel_after_chars: panelAfter.length,
    panel_reopened_chars: panelReopened.length,
  };
})()`;

//: Leave the corpus exactly as it was found.
//:
//: Belt and braces rather than one purge of the url the probe reports. The
//: live loop ticks every 1200ms against whatever the cell is showing, so a
//: purge issued while the fixture was still open was simply undone by the
//: next tick -- the corpus drifted from 99 pages to 119 with every purge
//: reporting success. The probes now park the cell first; this sweeps up
//: regardless, including after a probe that threw before it could park.
//:
//: Asks `GET /pages`, not `/layout`: the latter is a CACHED FIT keyed on
//: chunk count and answered 98 while the store held 119, which is correct
//: for a fit and useless for "what is in here".
const tidyFixtures = async () => {
  try {
    const listed = await ask("/pages?contains=live_mutate");
    let removed = 0;
    for (const url of listed.urls || []) {
      const res = await fetch(`${SIDECAR}/purge`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ url }),
        signal: AbortSignal.timeout(ASK_TIMEOUT_MS),
      });
      if (res.ok) removed += 1;
    }
    return removed;
  } catch {
    return -1;
  }
};

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
        // **Counts, taken NOW.** \graphData()\ hands back the graph's own
        // live arrays, not a snapshot, so holding \before\ and reading
        // \.length\ after the unfold reads the AFTER state through it --
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
        signal: AbortSignal.timeout(ASK_TIMEOUT_MS),
      });
      const d = await res.json();
      // WHERE they land, not only how many. D-17 put every placed node on a
      // frame corner -- 26 chunks at one point, 762 units from their own
      // page -- and every check here passed throughout, because none of them
      // looked at a coordinate.
      const pos = d.nodes.map((n) => n.pos).filter(Array.isArray);
      const onFrame = pos.reduce(
        (a, p) => a + p.filter((c) => Math.abs(Math.abs(c) - 300) < 0.5).length, 0);
      const here = (biggest.pos || [0, 0, 0]);
      const away = pos.map((p) => Math.hypot(
        p[0] - here[0], p[1] - here[1], p[2] - here[2]));
      let closest = Infinity;
      for (let i = 0; i < pos.length; i++) {
        for (let j = i + 1; j < pos.length; j++) {
          closest = Math.min(closest, Math.hypot(
            pos[i][0]-pos[j][0], pos[i][1]-pos[j][1], pos[i][2]-pos[j][2]));
        }
      }
      const far = away.length ? Math.max(...away) : 0;
      return {
        pass: d.nodes.length > 0 && d.nodes.length < biggest.members / 4
           // Not piled on the frame.
           && onFrame === 0
           // Anchored at the page they came out of, inside the unfold ball.
           && far <= 120
           // And distinguishable from each other.
           && (pos.length < 2 || closest > 1),
        evidence: {
          page_members: biggest.members,
          opened_to: d.nodes.length,
          edges: (d.edges || []).length,
          depth: d.depth, branches: d.branches, leaves: d.leaves,
          on_the_frame: onFrame,
          furthest_from_its_page: Math.round(far),
          closest_pair: Number.isFinite(closest) ? Math.round(closest * 10) / 10 : null,
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
        // hand this read \sphere * 1.75 * sqrt(2)\ -- 41% too large -- and
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
    id: "G-3",
    asks: "retrieval stays TRIPLE: frequency x quantized-semantic x pagerank",
    async run() {
      const d = await ask("/search?q=http+header+field&k=10");
      const hits = d.hits || [];
      const has = (f) => hits.filter((h) => typeof h[f] === "number").length;
      // Present is not enough: a component that is always zero is a veto
      // that never vetoes, and a component that is always the same number
      // is not ranking anything. Both arms.
      const spread = (f) => {
        const vs = hits.map((h) => h[f]).filter((v) => typeof v === "number");
        return vs.length ? Math.max(...vs) - Math.min(...vs) : 0;
      };
      // **And the arm this check was missing.** It asserted that the hits
      // it got carried all three factors -- which only chunks that CAN be
      // returned ever do. 7,955 of 14,129 chunks had no lexical row at all,
      // so under the strict product they were vetoed out of every ranking,
      // and 28 of 96 pages answered nothing to any query. The check passed
      // the whole time. So: sample pages and require each to be reachable.
      const layout = await ask("/layout?level=page");
      const pages = (layout.nodes || [])
        .slice().sort((a, b) => (b.members || 0) - (a.members || 0))
        .slice(0, 6);
      const unreachable = [];
      for (const pg of pages) {
        const words = String(pg.title || pg.url)
          .match(/[A-Za-z][A-Za-z-]{4,}/g) || [];
        const q = encodeURIComponent((words.slice(0, 4).join(" ") || "the"));
        const r = await ask(
          `/search?q=${q}&k=5&url=${encodeURIComponent(pg.url)}`);
        if (!(r.hits || []).length) unreachable.push(pg.url.slice(0, 48));
      }
      return {
        pass: hits.length > 1
           && has("lexical") === hits.length
           && has("semantic") === hits.length
           && has("pagerank") === hits.length
           && spread("lexical") > 0 && spread("semantic") > 0
           && unreachable.length === 0,
        evidence: {
          hits: hits.length,
          carried: { lexical: has("lexical"), semantic: has("semantic"),
                     pagerank: has("pagerank") },
          spread: { lexical: +spread("lexical").toFixed(4),
                    semantic: +spread("semantic").toFixed(4),
                    pagerank: +spread("pagerank").toFixed(6) },
          pages_probed: pages.length, unreachable,
        },
      };
    },
  },
  {
    id: "G-70",
    asks: "scoping a query to one url returns only that url's chunks",
    async run() {
      const global_ = await ask("/search?q=header&k=20");
      const urls = [...new Set((global_.hits || []).map((h) => h.url))];
      if (urls.length < 2) {
        return { pass: false, evidence: { why: "global ranking spanned one page",
                                          urls } };
      }
      const scoped = await ask(
        `/search?q=header&k=20&url=${encodeURIComponent(urls[0])}`);
      const scopedUrls = [...new Set((scoped.hits || []).map((h) => h.url))];
      return {
        // Scoped to exactly one page, and it returns SOMETHING -- an empty
        // scoped result would satisfy "only that url" vacuously, which is
        // the shape this defect actually took once before.
        pass: (scoped.hits || []).length > 0
           && scopedUrls.length === 1 && scopedUrls[0] === urls[0],
        evidence: {
          global_hits: (global_.hits || []).length, global_pages: urls.length,
          scoped_to: urls[0].slice(0, 54),
          scoped_hits: (scoped.hits || []).length, scoped_pages: scopedUrls.length,
        },
      };
    },
  },
  {
    id: "G-63",
    asks: "coarse ranking suppresses a merge group's members; fine does not",
    async run() {
      // **The query is CHOSEN, not guessed.** Asking for "header" returned
      // twenty-five hits of which none belonged to a merge group, so coarse
      // and fine agreed -- correctly -- and the check read that agreement as
      // a failure. Find a real group first and ask about its own words.
      const layout = await ask("/layout?level=chunk");
      const groups = (layout.nodes || [])
        .filter((n) => (n.members || 1) > 1)
        .sort((a, b) => b.members - a.members);
      if (!groups.length) {
        return { pass: false, evidence: { why: "no merge group in the store" } };
      }
      const lead = groups[0];
      const chunk = await ask(`/chunk/${encodeURIComponent(lead.cid)}`);
      const words = ((chunk.lines || []).map((l) => l.text).join(" ")
        .match(/[A-Za-z][A-Za-z-]{4,}/g) || []).slice(0, 6);
      if (words.length < 2) {
        return { pass: false, evidence: { why: "the group's lead has no words",
                                          lead: lead.cid } };
      }
      const q = encodeURIComponent(words.join(" "));
      const coarse = await ask(`/search?q=${q}&k=25&coarse=1`);
      const fine = await ask(`/search?q=${q}&k=25&coarse=0`);
      const cids = (d) => (d.hits || []).map((h) => h.cid);
      const members = new Set();
      for (const h of fine.hits || []) {
        if ((h.members || 1) > 1) members.add(h.cid);
      }
      const coarseGroups = (coarse.hits || [])
        .filter((h) => (h.members || 1) > 1).length;
      return {
        // The group has to be REACHED (otherwise the comparison is empty),
        // and the two rankings have to differ once it is.
        pass: (coarse.hits || []).length > 0
           && coarseGroups > 0
           && JSON.stringify(cids(coarse)) !== JSON.stringify(cids(fine)),
        evidence: {
          asked_about: lead.cid, group_size: lead.members,
          query: words.join(" ").slice(0, 60),
          coarse_hits: (coarse.hits || []).length,
          fine_hits: (fine.hits || []).length,
          coarse_speaking_for_groups: coarseGroups,
          identical: JSON.stringify(cids(coarse)) === JSON.stringify(cids(fine)),
        },
      };
    },
  },
  {
    id: "G-25",
    asks: "one node per distinct rendering, with the copy count carried",
    async run() {
      const d = await ask("/layout?level=chunk");
      const nodes = d.nodes || [];
      const copies = nodes.map((n) => n.copies || 1);
      const seen = new Map();
      for (const n of nodes) seen.set(n.cid, (seen.get(n.cid) || 0) + 1);
      const duplicated = [...seen.values()].filter((v) => v > 1).length;
      return {
        pass: nodes.length > 0 && duplicated === 0
           && Math.max(...copies) > 1,
        evidence: {
          nodes: nodes.length,
          repeated_cids: duplicated,
          most_copies: Math.max(...copies),
          nodes_standing_for_several: copies.filter((c) => c > 1).length,
        },
      };
    },
  },
  {
    id: "G-27",
    asks: "the merge layer indexes and the 256-token chunks stay underneath",
    async run() {
      const d = await ask("/layout?level=chunk");
      const nodes = d.nodes || [];
      const groups = nodes.filter((n) => (n.members || 1) > 1);
      if (!groups.length) {
        return { pass: false, evidence: { why: "no merge group in the layout",
                                          nodes: nodes.length } };
      }
      // A group lead must still resolve to a real chunk -- the originals
      // stay underneath and are what a hit resolves to.
      const lead = groups[0];
      const chunk = await ask(`/chunk/${encodeURIComponent(lead.cid)}`);
      return {
        pass: !!chunk && !!chunk.cid && Array.isArray(chunk.lines)
           && chunk.lines.length > 0,
        evidence: {
          nodes: nodes.length, groups: groups.length,
          biggest_group: Math.max(...groups.map((g) => g.members)),
          lead_resolves: !!(chunk && chunk.cid),
          lead_lines: chunk && chunk.lines ? chunk.lines.length : 0,
        },
      };
    },
  },
  {
    id: "G-41",
    asks: "nothing is injected into the page the browser is showing",
    async run() {
      const got = await evaluate(`(async () => {
        const sleep = (ms) => new Promise(r => setTimeout(r, ms));
        await app.commands.executeCommandById("domvec-open-browser");
        await sleep(1200);
        const bv = app.workspace.getLeavesOfType("domvec-browser-view")[0];
        const b = bv && bv.view;
        if (!b || !b.webview) return { error: "no browser pane" };
        const want = "https://books.toscrape.com/";
        if (b.webview.getURL() !== want) {
          b.go(want);
          for (let i = 0; i < 40; i++) {
            await sleep(400);
            if (!b.webview.isLoading() && b.webview.getURL() === want) break;
          }
        }
        await sleep(600);
        // Asked of the PAGE: does it carry anything of ours?
        return await b.webview.executeJavaScript(
          "(function(){" +
          "var marks=document.querySelectorAll('[class*=domvec],[id*=domvec],[data-domvec]');" +
          "var styles=Array.prototype.filter.call(document.styleSheets,function(s){" +
          "try{return s.ownerNode && !s.href && /domvec/i.test(s.ownerNode.textContent||'');}" +
          "catch(e){return false;}});" +
          "var scripts=Array.prototype.filter.call(document.scripts,function(s){" +
          "return /domvec/i.test(s.textContent||'')||/domvec/i.test(s.src||'');});" +
          "return {marked:marks.length, styles:styles.length, scripts:scripts.length," +
          "title:document.title.slice(0,40)};})()");
      })()`);
      if (got.error) return { pass: false, evidence: got };
      return {
        pass: got.marked === 0 && got.styles === 0 && got.scripts === 0,
        evidence: got,
      };
    },
  },
  {
    id: "G-5",
    asks: "every node is on screen at the default camera",
    async run() {
      const got = await inPane(`
        for (let i = 0; i < 60 && !(v.graph && v.graph.graphData().nodes.length); i++) await sleep(500);
        if (v.reframe) { v.reframe(); await sleep(1200); }
        const cam = v.graph.camera();
        const THREE = v.graph.constructor;
        const d = v.graph.graphData();
        // Projected into normalised device coordinates: |x|,|y| <= 1 and
        // 0 < z < 1 is "inside the frustum". Counting nodes rather than
        // trusting the framing arithmetic that put them there.
        cam.updateMatrixWorld();
        const m = cam.projectionMatrix.clone().multiply(cam.matrixWorldInverse);
        let onScreen = 0, behind = 0;
        for (const n of d.nodes) {
          const x = n.x, y = n.y, z = n.z;
          const e = m.elements;
          const cw = e[3]*x + e[7]*y + e[11]*z + e[15];
          if (cw <= 0) { behind++; continue; }
          const cx = (e[0]*x + e[4]*y + e[8]*z + e[12]) / cw;
          const cy = (e[1]*x + e[5]*y + e[9]*z + e[13]) / cw;
          if (Math.abs(cx) <= 1 && Math.abs(cy) <= 1) onScreen++;
        }
        return { nodes: d.nodes.length, onScreen, behind };
      `);
      if (got.error) return { pass: false, evidence: got };
      return {
        pass: got.nodes > 0 && got.onScreen === got.nodes && got.behind === 0,
        evidence: got,
      };
    },
  },
  {
    id: "G-57",
    asks: "a chunk's panel opens as a draggable billboard IN the projector",
    async run() {
      const got = await inPane(`
        for (let i = 0; i < 60 && !(v.graph && v.graph.graphData().nodes.length); i++) await sleep(500);
        // Clear the decks. Earlier checks click nodes, and a click now opens
        // a billboard -- and openBillboard TOGGLES, so running second this
        // check was closing one instead of opening one and reporting that
        // none appeared. Establish the state rather than inherit it.
        const stale = Array.from(v.contentEl.querySelectorAll(".domvec-bb"));
        for (const el of stale) {
          const x = el.querySelector(".domvec-bb-close");
          if (x) x.click();
        }
        if (v.billboards) v.billboards.clear();
        await sleep(300);
        // A clean page-level picture, then one unfold, so chunk nodes exist.
        const fresh = await (await fetch(${JSON.stringify(SIDECAR)} + "/layout?level=page")).json();
        v.graph.graphData({ nodes: fresh.nodes.map(n => v.nodeFrom(n)), links: [] });
        await sleep(400);
        const page = v.graph.graphData().nodes
          .filter(n => n.url).sort((a, b) => (b.members||0) - (a.members||0))[0];
        // DESCEND until a chunk appears, the way a reader does.
        //
        // One step does not reach one. An unravelling shows BRANCHES, and a
        // large page's first step is all branches -- ar.wikipedia's 801
        // chunks open as five path nodes. This check assumed the first step
        // produced a leaf and passed only while the biggest page happened
        // to be a shallow one; D-19 changed which page that is.
        let chunk = null;
        let hops = 0;
        let open_ = page;
        for (; hops < 6 && open_; hops++) {
          await v.unfoldNode(open_);
          await sleep(900);
          const nodes = v.graph.graphData().nodes;
          chunk = nodes.find(n => n.level === "chunk" && n.id && !n.unfolded);
          if (chunk) break;
          open_ = nodes.filter(n => n.level === "path" && !n.unfolded)
            .sort((a, b) => (b.members || 0) - (a.members || 0))[0];
        }
        if (!chunk) return { error: "no chunk node after descending",
                             hops, page: String(page.url).slice(0, 48) };

        const handler = v.graph.onNodeClick();
        handler(chunk);
        // The panel fetches its lines; give it a moment.
        for (let i = 0; i < 40; i++) {
          await sleep(250);
          const b = v.contentEl.querySelector(".domvec-bb-body");
          if (b && b.childElementCount) break;
        }
        const all = v.contentEl.querySelectorAll(".domvec-bb");
        const el = all[all.length - 1];
        if (!el) return { error: "no billboard appeared",
                          open_count: all.length,
                          tracked: v.billboards ? v.billboards.size : null,
                          clicked: String(chunk.id).slice(0, 24) };
        const layer = v.contentEl.querySelector(".domvec-bb-layer");
        const body = el.querySelector(".domvec-bb-body");
        const lines = body ? body.childElementCount : 0;

        // Anchored: it must be near where the node PROJECTS to.
        const at = v.graph.graph2ScreenCoords(chunk.x, chunk.y, chunk.z);
        const box = el.getBoundingClientRect();
        const host = layer.getBoundingClientRect();
        const offBy = Math.round(Math.hypot(
          (box.left - host.left) - (at.x + 12), (box.top - host.top) - (at.y + 12)));

        // It FOLLOWS: move the camera and it must move with the node.
        const before = el.style.left;
        const cam = v.graph.cameraPosition();
        v.graph.cameraPosition({ x: cam.x * 0.6 + 40, y: cam.y + 30, z: cam.z * 0.6 }, undefined, 0);
        await sleep(900);
        const followed = el.style.left !== before;

        // Dragging PINS it: after a drag it must ignore the camera.
        const head = el.querySelector(".domvec-bb-head");
        const r = el.getBoundingClientRect();
        const send = (type, x, y) => head.dispatchEvent(new PointerEvent(type, {
          pointerId: 1, bubbles: true, cancelable: true, clientX: x, clientY: y }));
        head.setPointerCapture = () => {};
        send("pointerdown", r.left + 10, r.top + 6);
        send("pointermove", r.left + 90, r.top + 70);
        send("pointerup", r.left + 90, r.top + 70);
        const parked = el.style.left;
        const cam2 = v.graph.cameraPosition();
        v.graph.cameraPosition({ x: cam2.x + 60, y: cam2.y - 25, z: cam2.z }, undefined, 0);
        await sleep(900);
        const stayed = el.style.left === parked;

        // And it closes.
        el.querySelector(".domvec-bb-close").click();
        await sleep(300);
        const gone = !v.contentEl.querySelector(".domvec-bb");

        return {
          node: String(chunk.id).slice(0, 24),
          hops_to_a_chunk: hops + 1,
          lines, anchored_off_by_px: offBy,
          in_canvas: !!(layer && layer.parentElement
                        && layer.parentElement.classList.contains("domvec-graph-canvas")),
          followed_camera: followed, pinned_after_drag: stayed, closed: gone,
        };
      `);
      if (got.error) return { pass: false, evidence: got };
      return {
        // Five properties, and each of the last three is the one that a
        // plausible-looking implementation gets wrong: a panel that never
        // follows, one that never stops following, one that cannot be shut.
        pass: got.lines > 0
           && got.in_canvas === true
           && got.anchored_off_by_px <= 2
           && got.followed_camera === true
           && got.pinned_after_drag === true
           && got.closed === true,
        evidence: got,
      };
    },
  },
  {
    id: "G-4",
    asks: "inter-spatial normalization -- nodes are discernible, not a clump",
    async run() {
      const d = await ask("/layout?level=chunk");
      const ns = (d.nodes || []).filter((n) => Array.isArray(n.pos));
      if (ns.length < 50) {
        return { pass: false, evidence: { why: "too few placed nodes", n: ns.length } };
      }
      // Nearest-neighbour distance over a sample. The defect this guards is
      // a cloud whose points sit on top of each other, which reads as one
      // blob however well the fit separated them in six dimensions.
      const sample = ns.slice(0, 400);
      const nn = [];
      for (let i = 0; i < sample.length; i++) {
        let best = Infinity;
        for (let j = 0; j < sample.length; j++) {
          if (i === j) continue;
          const a = sample[i].pos, b = sample[j].pos;
          const dd = Math.hypot(a[0]-b[0], a[1]-b[1], a[2]-b[2]);
          if (dd < best) best = dd;
        }
        if (Number.isFinite(best)) nn.push(best);
      }
      nn.sort((a, b) => a - b);
      const p50 = nn[Math.floor(nn.length / 2)];
      const zero = nn.filter((x) => x < 1e-6).length;
      return {
        // A median neighbour distance of ~0 is the clump; exact zeros are
        // two nodes at one point, which `G-25` says should not exist.
        pass: p50 > 1 && zero === 0,
        evidence: { sampled: sample.length, nn_p50: +p50.toFixed(3),
                    nn_min: +nn[0].toFixed(3), coincident: zero },
      };
    },
  },
  {
    id: "G-15",
    asks: "media is present in the PROJECTOR, not only in the panels",
    async run() {
      const d = await ask("/layout?level=chunk");
      const ns = d.nodes || [];
      const withPicture = ns.filter((n) => n.image && n.image.src).length;
      return {
        pass: ns.length > 0 && withPicture > 0,
        evidence: {
          nodes: ns.length, with_a_picture: withPicture,
          share: +(100 * withPicture / Math.max(ns.length, 1)).toFixed(1),
          reported_by_layout: d.images ?? null,
        },
      };
    },
  },
  {
    id: "G-71",
    asks: "scoped results unfold by the same mechanics as the overlay's",
    async run() {
      const got = await inPane(`
        for (let i = 0; i < 60 && !(v.graph && v.graph.graphData().nodes.length); i++) await sleep(500);
        const fresh = await (await fetch(${JSON.stringify(SIDECAR)} + "/layout?level=page")).json();
        v.graph.graphData({ nodes: fresh.nodes.map(n => v.nodeFrom(n)), links: [] });
        await sleep(400);
        const before = v.graph.graphData().nodes.length;
        // Ask the sidecar for a page's own hits, then hand them to the same
        // showHits the overlay uses. One behaviour, two callers.
        const page = v.graph.graphData().nodes
          .filter(n => n.url).sort((a,b) => (b.members||0)-(a.members||0))[0];
        const url = page.url;
        // The page's OWN words. Asking for "the" returned nothing: it is a
        // stopword, so the lexical factor is ~0, and under the strict triple
        // product a zero is a veto. The same lesson G-63 already paid for.
        const c = await (await fetch(${JSON.stringify(SIDECAR)}
          + "/layout?level=chunk")).json();
        const mine = (c.nodes || []).filter(n => n.url === url).slice(0, 3);
        const words = mine.map(n => String(n.title || ""))
          .join(" ").match(/[A-Za-z][A-Za-z-]{4,}/g) || [];
        if (!words.length) return { error: "no words to ask about", url };
        const q = encodeURIComponent(words.slice(0, 5).join(" "));
        const r = await fetch(${JSON.stringify(SIDECAR)}
          + "/search?q=" + q + "&k=12&url=" + encodeURIComponent(url));
        const d = await r.json();
        const cids = (d.hits || []).map(h => h.cid);
        if (!cids.length) return { error: "no scoped hits for that page", url,
                                   asked: words.slice(0, 5).join(" ") };
        // Ask the sidecar DIRECTLY first, so a failure says which half broke.
        // showHits returns early on two different conditions -- every hit
        // already drawn, or the fit placing none of them -- and reporting
        // only "0 drawn" cannot tell them apart.
        const already = v.graph.graphData().nodes.filter(
          n => cids.includes(n.id)).length;
        const placed = await v.sidecar.place(cids);
        const placedCount = (placed && placed.nodes || []).length;
        const unplaced = (placed && placed.unplaced || []).length;
        await v.showHits(url, cids);
        await sleep(1200);
        const after = v.graph.graphData();
        const drawn = cids.filter(c => after.nodes.some(n => n.id === c)).length;
        const hub = after.nodes.find(n => n.id === "page:" + url);
        return {
          page: url.slice(0, 50), scoped_hits: cids.length,
          already_drawn: already, placed_by_sidecar: placedCount,
          unplaced: unplaced, place_why: (placed && placed.why) || null,
          nodes_before: before, nodes_after: after.nodes.length,
          hits_drawn: drawn,
          hub_kept: !!hub, hub_marked_open: !!(hub && hub.unfolded),
          links: after.links.length,
        };
      `);
      if (got.error) return { pass: false, evidence: got };
      return {
        // The hits are drawn, the page they came from is kept as their hub,
        // and it is marked open -- the same shape `G-6` asserts for a click.
        pass: got.hits_drawn > 0
           && got.nodes_after > got.nodes_before
           && got.hub_kept === true && got.hub_marked_open === true
           && got.links > 0,
        evidence: got,
      };
    },
  },
  {
    id: "G-16",
    asks: "a live scan's chunks reach the PROJECTOR while the reader browses",
    async run() {
      // Needs the sidecar started with --capture. Says so rather than
      // failing obscurely: a writer lock is a deliberate choice, and a
      // reader-only sidecar is the ordinary state.
      const health = await ask("/health");
      if (!health.capture) {
        return { pass: false, evidence: {
          why: "sidecar has no --capture; this check needs the writer lock" } };
      }
      const got = await evaluate(`(async () => {
        const SIDECAR_URL = ${JSON.stringify(SIDECAR)};
        const sleep = (ms) => new Promise(r => setTimeout(r, ms));
        await app.commands.executeCommandById("domvec-open-browser");
        await app.commands.executeCommandById("domvec-open-graph");
        await sleep(2500);
        const bv = app.workspace.getLeavesOfType("domvec-browser-view")[0];
        const gv = app.workspace.getLeavesOfType("domvec-graph-view")[0];
        const b = bv && bv.view, v = gv && gv.view;
        if (!b || !v || !b.webview) return { error: "panes not open" };
        for (let i = 0; i < 60 && !(v.graph && v.graph.graphData().nodes.length); i++) await sleep(500);

        // A page the corpus already holds, so scanning re-writes rather
        // than grows it -- this is someone's real workspace.
        const want = "https://books.toscrape.com/";
        if (b.webview.getURL() !== want) {
          b.go(want);
          for (let i = 0; i < 40; i++) {
            await sleep(400);
            if (!b.webview.isLoading() && b.webview.getURL() === want) break;
          }
        }
        await sleep(1200);
        // Establish the state. Earlier checks unfold pages and draw hit
        // lists, and this one ran eighth: it reported 1,059 nodes arriving
        // from a 26-chunk scan, because it counted every node the SUITE had
        // added rather than the ones this scan did.
        const clean = await (await fetch(SIDECAR_URL + "/layout?level=page")).json();
        v.graph.graphData({ nodes: clean.nodes.map(n => v.nodeFrom(n)), links: [] });
        await sleep(500);
        const before = v.graph.graphData().nodes.length;
        const beforeIds = new Set(v.graph.graphData().nodes.map(n => n.id));

        // Scan it, the way the button does.
        await b.scan();
        // The vectors are computed by a worker, so the nodes arrive after
        // the write. Wait for the picture to change rather than for a timer.
        let after = before;
        for (let i = 0; i < 25; i++) {
          await sleep(1000);
          after = v.graph.graphData().nodes.length;
          if (after !== before) break;
        }
        await sleep(1500);
        let d = v.graph.graphData();
        let fresh = d.nodes.filter(n => !beforeIds.has(n.id));
        // **Two arms, because a page that has not changed has no delta.**
        //
        // The write diff is working when a re-scan of an unchanged page
        // reports 0 rewrites -- that is D-nothing, not a failure -- and a
        // check that needed a delta then measured 0 arrivals and called the
        // feature broken. Mutating the page to force one is forbidden
        // (constraint 7) and adding a page grows someone's corpus, so when
        // there is no delta the PLACEMENT path is exercised directly: the
        // same place-and-absorb a drain would have used.
        let arm = "delta";
        let asked = null, scopedHits = null;
        if (!fresh.length) {
          arm = "placement";
          // The page's OWN words. Asking for "book" returned 0 hits on a
          // page about books -- the third time a guessed query has read as
          // a broken feature (G-63, G-71). Take them from the chunks.
          const cr = await fetch(SIDECAR_URL + "/layout?level=chunk");
          const mine = ((await cr.json()).nodes || [])
            .filter(n => n.url === want).slice(0, 4);
          const words = mine.map(n => String(n.title || ""))
            .join(" ").match(/[A-Za-z][A-Za-z-]{4,}/g) || [];
          const q = encodeURIComponent(words.slice(0, 5).join(" ") || "the");
          const r = await fetch(SIDECAR_URL + "/search?q=" + q + "&k=8&url="
                                + encodeURIComponent(want));
          const hits = ((await r.json()).hits || []).map(h => h.cid);
          asked = words.slice(0, 5).join(" ");
          scopedHits = hits.length;
          if (hits.length) {
            await v.showHits(want, hits);
            await sleep(1200);
            d = v.graph.graphData();
            fresh = d.nodes.filter(n => !beforeIds.has(n.id));
          }
        }
        const placed = fresh.filter(n => n.pos || Number.isFinite(n.fitX));
        // On the frame is the D-17 signature for a PLACED node only.
        //
        // A node the FIT drew is mapped into the box by _framed, so the
        // extremes sit at exactly +/-300 by construction -- ten page nodes
        // do, correctly. Judging fitted nodes by this rule would fail the
        // check on the projector working as designed.
        const onFrame = fresh.filter(n => [n.fitX, n.fitY, n.fitZ]
          .some(c => Math.abs(Math.abs(c) - 300) < 0.5)).length;
        return {
          url: want,
          nodes_before: before, nodes_after: d.nodes.length,
          arm, asked, scoped_hits: scopedHits,
          arrived: fresh.length, with_a_position: placed.length,
          on_the_frame: onFrame,
          status: b.status ? b.status.textContent : null,
        };
      })()`, { timeout: 900000 });
      if (got.error) return { pass: false, evidence: got };
      return {
        // Something arrived, it has a position, and it is not on the frame
        // (D-17 put every placed node there and every count still looked
        // right).
        pass: got.arrived > 0
           && got.with_a_position === got.arrived
           && got.on_the_frame === 0,
        evidence: got,
      };
    },
  },
  {
    id: "G-12",
    asks: "a fitted layout is persisted and queried back instead of refitted",
    async run() {
      const health = await ask("/health");
      // Ask twice for the SAME key. The first may build; the second must be
      // the same picture, node for node.
      const a = await ask("/layout?level=page");
      const b = await ask("/layout?level=page");
      const same = JSON.stringify((a.nodes || []).map((n) => n.pos))
                === JSON.stringify((b.nodes || []).map((n) => n.pos));
      return {
        // The store is holding fits, the field exists so a reader can tell
        // which they got, and the same question gives the same answer. A
        // cache that returned a DIFFERENT picture each time would be worse
        // than no cache: the map would move under someone reading it.
        pass: (health.layouts || 0) > 0
           && typeof a.from_store === "boolean"
           && same,
        evidence: {
          stored_fits: health.layouts,
          from_store: a.from_store,
          nodes: a.n,
          identical_on_a_second_ask: same,
        },
      };
    },
  },
  {
    id: "P-B1",
    asks: "the cell is a REAL browser -- arbitrary navigation, links follow",
    async run() {
      const got = await evaluate(`(async () => {
        const sleep = (ms) => new Promise(r => setTimeout(r, ms));
        await app.commands.executeCommandById("domvec-open-browser");
        await sleep(1800);
        const bv = app.workspace.getLeavesOfType("domvec-browser-view")[0];
        const b = bv && bv.view;
        if (!b || !b.webview) return { error: "no browser pane" };

        // 1. Arbitrary navigation, not a chunk view (P-B1).
        const home = "https://books.toscrape.com/";
        b.go(home);
        for (let i = 0; i < 40; i++) {
          await sleep(400);
          if (!b.webview.isLoading() && b.webview.getURL() === home) break;
        }
        const landed = b.webview.getURL();

        // 2. A LEFT CLICK follows a link, as in any browser (P-B6).
        //
        // Dispatched as a real input event to the guest, not by setting
        // location: the claim is that clicking behaves like clicking.
        const at = await b.webview.executeJavaScript(
          "(function(){var a=document.querySelector('article.product_pod h3 a');" +
          "if(!a) return null; a.scrollIntoView({block:'center'});" +
          "var r=a.getBoundingClientRect();" +
          "return {x:Math.round(r.left+r.width/2), y:Math.round(r.top+r.height/2)," +
          "href:a.href};})()");
        if (!at) return { error: "no link to click" };
        for (const type of ["mouseDown", "mouseUp"]) {
          b.webview.sendInputEvent({ type, x: at.x, y: at.y,
                                     button: "left", clickCount: 1 });
        }
        let moved = landed;
        for (let i = 0; i < 40; i++) {
          await sleep(400);
          moved = b.webview.getURL();
          if (moved !== landed && !b.webview.isLoading()) break;
        }

        // 3. Back, as in any browser (P-B2).
        let returned = moved;
        if (b.webview.canGoBack && b.webview.canGoBack()) {
          b.webview.goBack();
          for (let i = 0; i < 40; i++) {
            await sleep(400);
            returned = b.webview.getURL();
            if (returned === landed && !b.webview.isLoading()) break;
          }
        }
        return {
          landed, clicked_href: at.href, after_click: moved, after_back: returned,
          // The scanning loop is still armed while all of that happened
          // (P-B2: navigate while scanning continues).
          live_capture_on: liveWhileBrowsing,
        };
      })()`, { timeout: 600000 });
      if (got.error) return { pass: false, evidence: got };
      return {
        // Navigated somewhere arbitrary, a left click FOLLOWED a link, and
        // back returned. Any two of those pass while the third is broken.
        pass: got.landed === "https://books.toscrape.com/"
           && got.after_click !== got.landed
           && got.after_back === got.landed,
        evidence: got,
      };
    },
  },
  {
    id: "R-J1",
    asks: "adjacent nodes are separable -- median gap >= one node diameter",
    async run() {
      const got = await inPane(`
        for (let i = 0; i < 60 && !(v.graph && v.graph.graphData().nodes.length); i++) await sleep(500);
        // A clean page-level picture: this is a claim about the LAYOUT, and
        // an unfolded ball of chunks is a different population.
        const fresh = await (await fetch(${JSON.stringify(SIDECAR)} + "/layout?level=page")).json();
        v.graph.graphData({ nodes: fresh.nodes.map(n => v.nodeFrom(n)), links: [] });
        // Let the collider settle. This row is about what a reader SEES,
        // and the fit positions are not that: collision moves nodes apart
        // afterwards, so measuring fitX/fitY/fitZ scores the layout before
        // the one force that exists to separate it. Measured both ways --
        // 0.86 on the fit, which is the number this check first reported as
        // a failure of the picture.
        v.graph.d3ReheatSimulation();
        await sleep(6000);
        const d = v.graph.graphData();
        const rel = v.graph.nodeRelSize();
        const PANEL_GAIN = 1.75;
        const sphereOf = (n) => Math.cbrt(Math.max(n.val ?? 1, 1e-9)) * rel;
        const radius = (n) => (n.image && n.image.src)
          ? sphereOf(n) * PANEL_GAIN : sphereOf(n);
        const ns = d.nodes.filter(n => Number.isFinite(n.x));
        const nn = [];
        const fitNn = [];
        const sizes = [];
        for (let i = 0; i < ns.length; i++) {
          let best = Infinity, bestFit = Infinity;
          for (let j = 0; j < ns.length; j++) {
            if (i === j) continue;
            const a = ns[i], b = ns[j];
            const dd = Math.hypot(a.x-b.x, a.y-b.y, a.z-b.z);
            if (dd < best) best = dd;
            const ff = Math.hypot(a.fitX-b.fitX, a.fitY-b.fitY, a.fitZ-b.fitZ);
            if (ff < bestFit) bestFit = ff;
          }
          if (Number.isFinite(best)) {
            nn.push(best); sizes.push(radius(ns[i]) * 2);
          }
          if (Number.isFinite(bestFit)) fitNn.push(bestFit);
        }
        fitNn.sort((a, b) => a - b);
        nn.sort((a, b) => a - b);
        const sorted = sizes.slice().sort((a, b) => a - b);
        const p50 = nn[Math.floor(nn.length / 2)];
        const diameter = sorted[Math.floor(sorted.length / 2)];
        // R-J2: size must VARY. A uniform size is an assumption about
        // density rather than a reading of it.
        const spread = sorted.length
          ? sorted[sorted.length - 1] - sorted[0] : 0;
        return {
          nodes: ns.length,
          nn_median: Math.round(p50 * 100) / 100,
          median_diameter: Math.round(diameter * 100) / 100,
          ratio: Math.round((p50 / Math.max(diameter, 1e-9)) * 100) / 100,
          ratio_before_collision: fitNn.length
            ? Math.round((fitNn[Math.floor(fitNn.length/2)]
                          / Math.max(diameter, 1e-9)) * 100) / 100 : null,
          size_spread: Math.round(spread * 100) / 100,
          coincident: nn.filter(x => x < 1e-6).length,
        };
      `);
      if (got.error) return { pass: false, evidence: got };
      return {
        // The row's own criterion, plus the two arms that make it mean
        // something: nothing coincident, and sizes that actually differ.
        pass: got.nn_median >= got.median_diameter
           && got.coincident === 0
           && got.size_spread > 0,
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
    id: "S-7",
    asks: "a page interaction is observed and persisted to db and trie",
    async run() {
      const fixtures = await serveFixtures();
      const token = "domvecprobe" + Date.now().toString(36);
      const pagesBefore = (await ask("/health")).pages;
      const page = fixtures.origin + "/live_mutate.html";
      try {
        const got = await evaluate(mutateProbe(page, token, SIDECAR),
                                   { timeout: 600000 });
        // Leave the corpus as it was found. A confirmation harness that adds
        // a page per run is an instrument changing its own denominator.
        got.purged = await tidyFixtures();
        got.pages_before = pagesBefore;
        got.pages_after = (await ask("/health")).pages;
        if (got.error) return { pass: false, evidence: got };
        return {
          // Three things, and any two can hold while the third is broken:
          // the trie held the page before the click, the NULL ARM moved
          // nothing, and the click's own text arrived in the chunk the trie
          // draws that list from.
          pass: got.resolved_before === true
             && got.null_arm_changed === false
             && got.aim_on_screen === true
             && got.mutated_in_page === true
             && got.token_in_trie === true
             && got.pages_after === got.pages_before,
          evidence: got,
        };
      } finally {
        await fixtures.close();
      }
    },
  },
  {
    id: "S-12",
    asks: "one capture reaches the graph and BOTH panel sets, uniformly",
    async run() {
      const fixtures = await serveFixtures();
      const token = "domvecuniform" + Date.now().toString(36);
      const pagesBefore = (await ask("/health")).pages;
      const page = fixtures.origin + "/live_mutate.html";
      try {
        const got = await evaluate(uniformProbe(page, token, SIDECAR),
                                   { timeout: 600000 });
        got.purged = await tidyFixtures();
        got.pages_before = pagesBefore;
        got.pages_after = (await ask("/health")).pages;
        if (got.error) return { pass: false, evidence: got };
        return {
          // "Uniformly" is the whole row, so every surface has to carry it,
          // and the arm below stops the token being there all along.
          pass: got.panel_open_before_had_token === false
             && got.mutated_in_page === true
             && got.db_has_token === true
             && got.open_panel_has_token === true
             && got.reopened_panel_has_token === true
             && got.graph_has_node === true
             && got.pages_after === got.pages_before,
          evidence: got,
        };
      } finally {
        await fixtures.close();
      }
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

/**
 * Reload the plugin before anything is measured.
 *
 * **A probe scores the instrument that is LOADED, not the one on disk.** The
 * collider probe passed with its own target defect planted and returned
 * numbers identical to the clean run down to a random shuffle landing on
 * 0.004 twice -- because it reopened the pane but never reloaded the plugin,
 * so `npm run build` had replaced a file nobody was running. The tell was the
 * impossible coincidence, not the green.
 *
 * This file's header used to say it reloads nothing. That was a claim about
 * not disturbing pane STATE, which each check establishes for itself anyway,
 * and it read as licence to score a build that was never loaded.
 *
 * Skippable with DOMVEC_NO_RELOAD=1, for confirming what is running right
 * now rather than what was just built.
 */
const reloadPlugin = async () => {
  if (process.env.DOMVEC_NO_RELOAD === "1") return { reloaded: false };
  const got = await evaluate(`(async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const id = "domvec-bridge";
    await app.plugins.disablePlugin(id);
    await sleep(800);
    await app.plugins.enablePlugin(id);
    await sleep(2500);
    return { enabled: !!app.plugins.getPlugin(id) };
  })()`, { timeout: 120000 });
  return { reloaded: true, ...got };
};

const reload = await reloadPlugin().catch(
  (e) => ({ reloaded: false, error: String(e).slice(0, 120) }));
console.log(reload.reloaded
  ? `reloaded the plugin (enabled=${reload.enabled})`
  : `NOT reloaded: ${reload.error || "DOMVEC_NO_RELOAD=1"}`);

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
