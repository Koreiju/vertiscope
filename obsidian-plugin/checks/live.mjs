/**
 * The live checks, as a module both runners share (`G-75`).
 *
 * **Hardware in the loop.** Every check here drives the RUNNING plugin and
 * reads what it did back off the app -- the check bodies are JavaScript
 * evaluated in Obsidian's own window, plus reads of the sidecar. They used to
 * exist only inside `confirm.mjs`, a terminal script talking to the app over
 * CDP, so a check could only ever be run from outside. Split out and
 * parameterised by the few things a runner supplies, the same checks run:
 *
 *   * INSIDE the plugin (`src/verify.ts`) -- `evaluate` is the window's own
 *     eval, results appear live in the browser cell's corner box, and the
 *     MCP tools start runs and read results through `window.__domvec.verify`;
 *   * from a terminal (`confirm.mjs`) -- `evaluate` goes over CDP, as before,
 *     and the file is now a thin client of the same list.
 *
 * `env`: { evaluate(code, {timeout}?) -> value, SIDECAR, serveFixtures()
 *          -> {origin, close}, askTimeoutMs? }
 *
 * Nothing in a check body changed in the move; the text is the same.
 */

export function makeChecks(env) {
  const { evaluate, SIDECAR } = env;

  const GRAPH_VIEW = "domvec-graph-view";

  /**
   * Evaluate in the pane, with the graph view already resolved as `v`.
   *
   * **It opens the pane and WAITS for the fit, rather than assuming both.**
   * Every check below reads `v.graph`, and that object does not exist until a
   * layout has been fetched and `ForceGraph3D` constructed -- which is
   * seconds after the view opens, on a real corpus. That was invisible for as
   * long as nothing reloaded the plugin: the pane had been open since
   * whenever, so the graph was always already there. Adding the reload step
   * turned an implicit precondition into nine checks failing with
   * "Cannot read properties of undefined (reading 'graphData')", which reads
   * like a broken projector and was a harness not waiting.
   *
   * This is the file's own rule applied to itself: a check that needs a
   * particular state establishes that state.
   */
  const inPane = (body) => evaluate(`(async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const TYPE = ${JSON.stringify(GRAPH_VIEW)};
    if (!app.workspace.getLeavesOfType(TYPE).length) {
      await app.commands.executeCommandById("domvec-open-graph");
      await sleep(1500);
    }
    // **A leaf in a BACKGROUND tab hands back a deferred stub, not the view.**
    //
    // Obsidian defers a view until its leaf is shown, so leaf.view is a
    // placeholder with none of the methods on it. That is why nine checks
    // read "Cannot read properties of undefined (reading 'graphData')" and
    // G-39 read "view.highlightChunk is not a function" -- not a broken
    // projector, a stub. It only started happening because the new checks in
    // this file open their own tab, which pushes the graph pane into the
    // background where it had never been before.
    const leaf0 = app.workspace.getLeavesOfType(TYPE)[0];
    if (leaf0) {
      app.workspace.revealLeaf(leaf0);
      if (leaf0.loadIfDeferred) await leaf0.loadIfDeferred();
      await sleep(600);
    }

    let v = null;
    // Generous: a cold chunk-level fit over this corpus is tens of seconds,
    // and a timeout shorter than the work is just a different way of
    // reporting a failure that is not there.
    for (let i = 0; i < 120; i++) {
      const leaf = app.workspace.getLeavesOfType(TYPE)[0];
      if (leaf && leaf.loadIfDeferred) await leaf.loadIfDeferred();
      v = leaf && leaf.view;
      if (v && v.graph) break;
      await sleep(500);
    }
    if (!v) return { error: "graph pane would not open" };
    if (!v.graph) {
      return { error: "the graph pane never finished its fit",
               deferred: !!(app.workspace.getLeavesOfType(TYPE)[0] || {}).isDeferred,
               viewType: v.getViewType ? v.getViewType() : typeof v };
    }
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
  const ASK_TIMEOUT_MS = Number(env.askTimeoutMs || 300000);

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
  const serveFixtures = env.serveFixtures;

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
    const gFresh = app.workspace.getLeavesOfType("domvec-graph-view")[0];
    // A SPLIT of the graph, not a tab beside it: a tab in the graph's group
    // hid the graph for every check after this one (2026-10-07: G-94 read a
    // 0x0 canvas, G-107 picked 0 of 10).
    const bleafFresh = gFresh ? app.workspace.createLeafBySplit(gFresh, "vertical") : app.workspace.getLeaf("tab");
    await bleafFresh.setViewState({ type: "domvec-browser-view", active: true });
    app.workspace.revealLeaf(bleafFresh);
    await sleep(1800);
    // A leaf in a background tab hands back a DEFERRED stub with none of
    // the view's methods on it. Fronting the projector backgrounds the
    // browser cell, so this has to be forced before .view is read --
    // otherwise b.webview is undefined and it reads as no browser pane.
    for (const l of app.workspace.getLeavesOfType("domvec-browser-view")) {
      if (l.loadIfDeferred) await l.loadIfDeferred();
    }
    for (const l of app.workspace.getLeavesOfType("domvec-graph-view")) {
      if (l.loadIfDeferred) await l.loadIfDeferred();
    }
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
    // run looks for a string no previous run can have left behind. It travels
    // in the URL (PAGE carries ?token=): a global set from here lands in the
    // sensor's isolated world (D-43), where the page's handler never sees it --
    // the click appended "untokened" items and S-7 read as a sensor failure.

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
  //: graph, a chunk that was already pinned when the change landed (its side
  //: panel AND its billboard), and one pinned again afterwards.
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
    const gFresh = app.workspace.getLeavesOfType("domvec-graph-view")[0];
    // A SPLIT of the graph, not a tab beside it: a tab in the graph's group
    // hid the graph for every check after this one (2026-10-07: G-94 read a
    // 0x0 canvas, G-107 picked 0 of 10).
    const bleafFresh = gFresh ? app.workspace.createLeafBySplit(gFresh, "vertical") : app.workspace.getLeaf("tab");
    await bleafFresh.setViewState({ type: "domvec-browser-view", active: true });
    app.workspace.revealLeaf(bleafFresh);
    await sleep(1500);
    // A leaf in a background tab hands back a DEFERRED stub with none of
    // the view's methods on it. Fronting the projector backgrounds the
    // browser cell, so this has to be forced before .view is read --
    // otherwise b.webview is undefined and it reads as no browser pane.
    for (const l of app.workspace.getLeavesOfType("domvec-browser-view")) {
      if (l.loadIfDeferred) await l.loadIfDeferred();
    }
    for (const l of app.workspace.getLeavesOfType("domvec-graph-view")) {
      if (l.loadIfDeferred) await l.loadIfDeferred();
    }
    const bv = app.workspace.getLeavesOfType("domvec-browser-view")[0];
    const b = bv && bv.view;
    if (!b || !b.webview) return { error: "no browser pane" };

    b.go(PAGE);
    for (let i = 0; i < 60; i++) {
      await sleep(400);
      if (!b.webview.isLoading() && b.webview.getURL().indexOf(PAGE) === 0) break;
    }
    const landed = b.webview.getURL();
    // The token is in the URL (PAGE carries ?token=; see the mutate probe).

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

    // ---- The chunk PINNED before the change lands. ----
    //
    // Since Addenda VI and VII a chunk's two forms live in two places, and
    // both open from one right-click: its markdown as a side panel beside
    // the page, its shadow-DOM form as a billboard in the graph (G-78). This
    // asked the retired chunk PANE until 2026-09-26 -- it opened a view type
    // that no longer exists, got a blank leaf, and threw "view.show is not a
    // function". Pinned by address, exactly what a right-click produces.
    const gl0 = app.workspace.getLeavesOfType("domvec-graph-view")[0];
    const g0 = gl0 && gl0.view;
    // A panel's text as a reader sees it: its own text AND the page
    // snapshot's frame (D-36 draws the chunk as the page does, in a frame).
    const frameText = (root) => [...root.querySelectorAll("iframe.domvec-snapshot")].map((f) => {
      try { return f.contentDocument.body.innerText || ""; } catch (e) { return ""; }
    }).join(String.fromCharCode(10));
    const sideText = () => {
      const card = b.markdownWrap.querySelector('.domvec-pin-card[data-cid="' + cid + '"]');
      return card ? (card.innerText || card.textContent || "") + String.fromCharCode(10) + frameText(card) : "";
    };
    // The billboard renders into the plugin's OWN shadow root (a
    // .domvec-html-host); reading it is not what constraint 6 refuses.
    const boardText = () => {
      const e = g0 && g0.billboards && g0.billboards.get(cid);
      if (!e) return "";
      // The panel's BODY: its header is the chunk's trie address, "url :
      // xpath" (2026-10-06), and the url carries this run's token -- reading
      // the whole element found the token before the click (2026-10-07).
      const body = e.el.querySelector(".domvec-bb-body") || e.el;
      const host = body.querySelector(".domvec-html-host");
      const sr = host && host.shadowRoot;
      return (body.textContent || "") + String.fromCharCode(10) + (sr ? (sr.textContent || "") : "")
        + String.fromCharCode(10) + frameText(body);
    };
    const pin = async () => {
      const got = await b.pinXpath(LIST);
      for (let i = 0; i < 30 && !boardText(); i++) await sleep(300);
      await sleep(900);
      return got;
    };
    const pinned = await pin();
    if (!pinned || pinned.cid !== cid) return { error: "pinning did not hold the list's chunk", pinned, cid };
    const sideBefore = sideText();
    const boardBefore = boardText();

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
    // it only lands while the browser leaf has focus, and pinning has just
    // opened a billboard in the graph, which can take it. So: activate the browser leaf and
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
    const sideAfter = sideText();
    const boardAfter = boardText();

    // ---- The CLOSED arm: let it go, then pin it again. ----
    b.unpin(cid);
    await sleep(700);
    const boardGone = !boardText();
    await pin();
    const sideRepinned = sideText();
    const boardRepinned = boardText();
    b.unpin(cid);

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
      db_has_token: dbHas,
      side_before_had_token: sideBefore.indexOf(TOKEN) >= 0,
      board_before_had_token: boardBefore.indexOf(TOKEN) >= 0,
      side_has_token: sideAfter.indexOf(TOKEN) >= 0,
      board_has_token: boardAfter.indexOf(TOKEN) >= 0,
      unpin_closed_board: boardGone,
      repinned_side_has_token: sideRepinned.indexOf(TOKEN) >= 0,
      repinned_board_has_token: boardRepinned.indexOf(TOKEN) >= 0,
      graph_has_node: graphHasNode,
      side_chars: [sideBefore.length, sideAfter.length, sideRepinned.length],
      board_chars: [boardBefore.length, boardAfter.length, boardRepinned.length],
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
  //:
  //: **By ORIGIN, not by file name.** Each check serves its fixtures on its
  //: own port, so `origin` names exactly the pages that check made. Matching
  //: by file name purged ANY page called shadow_catalogue.html -- including
  //: the one a fresh-store run had seeded on its own port -- and S-7 and S-8
  //: then failed their own "pages_after === pages_before" on a page they had
  //: deleted themselves (13 -> 12, 2026-09-26).
  // The browser cell, fronted, attached and sized, with `land(url, ms)`
  // waiting for a load to finish at that url. Shared by the Addendum IX
  // checks, which drive the cell the way a reader does.
  // Points over the page's own chunks, the smallest chunk at each (G-125, G-124).
  const SCAN_POINTS = "(function(){var h=window.__domvecSensor;var a=[];for(var y=40;y<innerHeight-30;y+=30)for(var x=40;x<Math.min(innerWidth,760);x+=90){var st=document.elementsFromPoint(x,y),bb=null,ba=Infinity;for(var i=0;i<st.length&&i<12;i++){var c=null;try{c=h.at(st[i]);}catch(e){}if(c&&c.box){var ar=c.box[2]*c.box[3];if(ar>0&&ar<ba){ba=ar;bb=c;}}}if(bb)a.push({x:x,y:y,id:bb.id});}return JSON.stringify(a);})()";
  const PREP = `
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    await window.__domvec.act("open", "graph");
    await window.__domvec.act("open", "browser");
    for (const l of app.workspace.getLeavesOfType("domvec-graph-view")) { if (l.loadIfDeferred) await l.loadIfDeferred(); }
    const bl = app.workspace.getLeavesOfType("domvec-browser-view")[0];
    if (bl.loadIfDeferred) await bl.loadIfDeferred();
    app.workspace.revealLeaf(bl);
    // Both panes ON SCREEN: a browser left in the graph's tab group hides the
    // graph, and every check after that measured a 0x0 canvas (2026-10-07).
    {
      const gl0 = app.workspace.getLeavesOfType("domvec-graph-view")[0];
      if (gl0 && bl.parent === gl0.parent) {
        for (const l of app.workspace.getLeavesOfType("domvec-browser-view")) l.detach();
        app.workspace.revealLeaf(gl0);
        const nl = app.workspace.createLeafBySplit(gl0, "vertical");
        await nl.setViewState({ type: "domvec-browser-view", active: true });
        app.workspace.revealLeaf(nl);
        await sleep(1500);
      }
    }
    const bl2 = app.workspace.getLeavesOfType("domvec-browser-view")[0];
    if (bl2.loadIfDeferred) await bl2.loadIfDeferred();
    const b = bl2.view;
    for (let i = 0; i < 80; i++) {
      try { const sz = await b.webview.executeJavaScript("[innerWidth, innerHeight]"); if (sz[0] > 50 && sz[1] > 50) break; }
      catch (e) { /* not attached yet */ }
      await sleep(250);
    }
    const land = async (url, ms) => {
      if (b.webview.getURL() !== url) b.go(url);
      const t = performance.now();
      while (performance.now() - t < ms) {
        await sleep(150);
        let u = "", loading = true;
        try { u = b.webview.getURL(); loading = b.webview.isLoading(); } catch (e) { continue; }
        if (u === url && !loading) return true;
      }
      return false;
    };
  `;

  // Offline (`G-59`/`G-61`/`G-62`), the cell's own webContents taken offline
  // through Chromium's protocol with its cache off -- a session-level
  // emulation let pages load from the HTTP cache, so nothing failed. Okapi is
  // saved (by `scripts/check_offline.py` with "save offline" on) and holds
  // 0.875 of its trace; Axolotl is stored and was never saved. Always put back
  // online, and the cell returned to where it was.
  const OKAPI = "https://en.wikipedia.org/wiki/Okapi", AXOLOTL = "https://en.wikipedia.org/wiki/Axolotl";
  const offlineArm = (which) => evaluate(`(async () => {
    ${PREP}
    const start = b.webview.getURL();
    const wc = window.require("@electron/remote").webContents.fromId(b.webview.getWebContentsId());
    const emulate = async (off) => {
      const d = wc.debugger; if (!d.isAttached()) d.attach("1.3");
      await d.sendCommand("Network.enable");
      await d.sendCommand("Network.emulateNetworkConditions", { offline: off, latency: 0, downloadThroughput: -1, uploadThroughput: -1 });
      await d.sendCommand("Network.setCacheDisabled", { cacheDisabled: off });
      if (!off) d.detach();
    };
    const opened = async (url, ms) => {
      const t = performance.now();
      while (performance.now() - t < ms) {
        await sleep(500);
        try { if (b.offlineFor === url && b.webview.getURL().startsWith("file:") && !b.webview.isLoading()) return Math.round(performance.now() - t); } catch (e) {}
      }
      return null;
    };
    const look = () => b.webview.executeJavaScript("JSON.stringify({saved_layout: !!document.querySelector('#mw-content-text'), infill_chunks: document.querySelectorAll('.dv-infill .dv-chunk').length, traced_chunks: document.querySelectorAll('body > .dv-chunk').length, banner: ((document.querySelector('.dv-banner') || document.querySelector('.dv-infill-note') || {}).textContent || '').slice(0, 200), scrollable: document.documentElement.scrollHeight > innerHeight * 2})").then(JSON.parse);
    const visit = async (url) => {
      b.offlineFor = "";
      await land("about:blank", 8000);
      b.go(url);
      const ms = await opened(url, 90000);
      return { url, opened_ms: ms, form: b.offlineStats.last && b.offlineStats.last.form, open_ms: b.offlineStats.last && b.offlineStats.last.ms,
               ...(ms != null ? await look() : {}) };
    };
    try {
      await emulate(true);
      if (${JSON.stringify(which)} === "traced") {
        const nothing0 = b.offlineStats.nothing;
        const clean = await visit(${JSON.stringify(AXOLOTL)});
        b.offlineFor = "";
        await land("about:blank", 8000);
        const never = ${JSON.stringify(OKAPI)} + "?g62null=" + Date.now();
        b.go(never);
        for (let i = 0; i < 60 && b.offlineStats.nothing === nothing0; i++) await sleep(500);
        return { clean, null_arm: { url: never, nothing: b.offlineStats.nothing - nothing0, offlineFor: b.offlineFor } };
      }
      if (${JSON.stringify(which)} === "infilled") {
        return { clean: await visit(${JSON.stringify(OKAPI)}), null_arm: await visit(${JSON.stringify(AXOLOTL)}) };
      }
      // dock: offline, open a chunk's panel; then planted.
      await visit(${JSON.stringify(OKAPI)});
      const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
      const dock = async (plant) => {
        v.plantOfflineBillboard = plant;
        try {
          const d0 = v.docked;
          const cids = await v.sidecar.pageCids(${JSON.stringify(OKAPI)});
          let n = null;
          for (const id of cids.slice(0, 30)) {
            n = v.graph.graphData().nodes.find((x) => x.id === id);
            if (!n) { const g = await v.sidecar.place([id]); if (g && g.nodes) v.absorb(g.nodes, g.edges); n = v.graph.graphData().nodes.find((x) => x.id === id); }
            if (n) break;
          }
          if (!n) return { error: "no placeable chunk" };
          for (const bb of v.billboardState()) v.closeBillboard(bb.id);
          await v.openBillboard(n); await sleep(2500);
          const pane = app.workspace.getLeavesOfType("domvec-panel-view")[0];
          const sel = '.domvec-bb[data-cid="' + n.id + '"]';
          const inPane = !!(pane && pane.view.contentEl.querySelector(sel));
          const out = { docked: v.docked - d0, in_pane: inPane, in_graph: !!v.containerEl.querySelector(sel),
                        pane_chars: inPane ? pane.view.contentEl.innerText.trim().length : 0 };
          v.closeBillboard(n.id);
          return out;
        } finally { v.plantOfflineBillboard = false; }
      };
      return { offline: b.offlineFor === ${JSON.stringify(OKAPI)}, clean: await dock(false), planted: await dock(true) };
    } finally {
      await emulate(false);
      b.offlineFor = "";
      app.workspace.detachLeavesOfType("domvec-panel-view");
      if (start && /^https?:/.test(start)) await land(start, 30000);
    }
  })()`, { timeout: 300000 }).then((got) => {
    if (!got || got.error) return { pass: false, evidence: got };
    if (which === "traced") {
      const c = got.clean;
      return { pass: c.opened_ms != null && c.form === "traced" && c.traced_chunks > 0 && !c.saved_layout && c.scrollable
                     && /rebuilt from the scan trace/.test(c.banner) && got.null_arm.nothing >= 1 && !got.null_arm.offlineFor,
               evidence: got };
    }
    if (which === "infilled") {
      const c = got.clean, n = got.null_arm;
      return { pass: c.opened_ms != null && c.form === "infilled" && c.saved_layout && c.infill_chunks >= 1
                     && n.form === "traced" && !n.saved_layout && n.infill_chunks === 0,
               evidence: got };
    }
    return { pass: got.offline && got.clean.docked === 1 && got.clean.in_pane && !got.clean.in_graph && got.clean.pane_chars > 0
                   && got.planted.docked === 0 && !got.planted.in_pane && got.planted.in_graph,
             evidence: got };
  });

  // The page's own changes, timed by an observer OF THE CHECK'S (2026-09-27:
  // "Tests aren't validating on the original websites"). A live site cannot be
  // made to log its own writes, so the check watches for them: when content
  // (an element with 40+ chars of text) is delivered to any MutationObserver --
  // the earliest a script can know -- and which chunk it landed in, asked of
  // the sensor's `at` afterwards. Each is then matched to the drain that
  // CARRIED that chunk (its trace's `chunk_ids`), never merely the next drain.
  // Held in a closure under a random, non-enumerable name, and removed after:
  // nothing of it is left in the page.
  const STREAM_SEEN = `
    const qq = (xs, p) => { if (!xs.length) return null; const s = xs.slice().sort((a, c) => a - c); return Math.round(s[Math.min(s.length - 1, Math.floor(p * s.length))] * 10) / 10; };
    const observePage = async (KEY) => b.webview.executeJavaScript("(function () {" +
      "if (window[" + JSON.stringify(KEY) + "]) return 1;" +
      "var log = [];" +
      "var mo = new MutationObserver(function (recs) {" +
      "  var t = Date.now(), els = [];" +
      "  for (var i = 0; i < recs.length; i++) { var a = recs[i].addedNodes;" +
      "    for (var k = 0; k < a.length; k++) { var n = a[k];" +
      "      if (n.nodeType === 1 && (n.textContent || '').trim().length >= 40) els.push(n); } }" +
      "  if (els.length) log.push({ t: t, els: els.slice(0, 4) });" +
      "});" +
      "mo.observe(document.documentElement, { childList: true, subtree: true });" +
      "var moves = []; var pm = function () { moves.push(Date.now()); if (moves.length > 2000) moves.shift(); };" +
      "document.addEventListener('pointermove', pm, { capture: true, passive: true });" +
      "Object.defineProperty(window, " + JSON.stringify(KEY) + ", { value: { log: log, mo: mo, moves: moves, pm: pm }, enumerable: false, configurable: true });" +
      "return 1; })()");
    const collectPage = async (KEY) => b.webview.executeJavaScript("(function () {" +
      "var d = window[" + JSON.stringify(KEY) + "]; if (!d) return null; d.mo.disconnect();" +
      "document.removeEventListener('pointermove', d.pm, { capture: true });" +
      "var h = window.__domvecSensor;" +
      "var out = d.log.map(function (b) { var ids = [];" +
      "  b.els.forEach(function (e) { try { var g = h && h.at ? h.at(e) : null; if (g) ids.push(g.id); } catch (x) {} });" +
      "  return { t: b.t, ids: ids }; });" +
      "delete window[" + JSON.stringify(KEY) + "]; return { muts: out, moves: d.moves.slice() }; })()");
    const dropPage = async (KEY) => { try { await b.webview.executeJavaScript("(function(){var d=window[" + JSON.stringify(KEY) + "];if(d){d.mo.disconnect();document.removeEventListener('pointermove',d.pm,{capture:true});delete window[" + JSON.stringify(KEY) + "];}return 1;})()"); } catch (e) {} };
    const matchSeen = (seen, prefix, from, to) => {
      // Open traces too (listAll): a drain still waiting to be seen in 3D
      // has already carried its chunks to the host.
      const P = window.__domvecProfiler;
      const traces = (P.listAll ? P.listAll() : P.list()).filter((t) => t.url.startsWith(prefix) && t.kind === "live"
        && Array.isArray(t.facts.chunk_ids) && typeof t.facts.host_epoch === "number")
        .sort((a, c) => a.facts.host_epoch - c.facts.host_epoch);
      const rows = [];
      let unmapped = 0, unanswered = 0;
      for (const m of (seen || [])) {
        if (m.t < from || m.t > to) continue;
        if (!m.ids.length) { unmapped++; continue; }
        const hit = traces.find((t) => t.facts.host_epoch >= m.t && t.facts.chunk_ids.some((id) => m.ids.includes(id)));
        if (!hit || hit.facts.host_epoch - m.t > 10000) { unanswered++; continue; }
        const h = hit.facts.host_epoch - m.t;
        rows.push({ t: m.t, host: h,
                    to3d: typeof hit.stages.drain_to_3d === "number" ? h + hit.stages.drain_to_3d : null,
                    overlay: typeof hit.stages.drain_to_overlay === "number" ? h + hit.stages.drain_to_overlay : null });
      }
      return { rows, unmapped, unanswered };
    };
    // Null arm for hover (CLAUDE.md: measure the page before blaming the
    // sensor). A busy page delivers a pointer move late to EVERY listener --
    // its own hover styles included -- so each move is split into the page's
    // delay (sent -> the page's own listener got it) and ours (-> outline).
    const hoverSplit = (hovers, moves) => {
      const page = [], ours = [];
      for (const h of hovers) {
        if (h.ms === null) continue;
        const got = (moves || []).find((t) => t >= h.sent - 1);
        if (got === undefined || got - h.sent > 3000) continue;
        page.push(Math.max(0, got - h.sent));
        ours.push(Math.max(0, h.sent + h.ms - got));
      }
      return { n: ours.length, page_p50: qq(page, 0.5), page_p95: qq(page, 0.95), ours_p50: qq(ours, 0.5), ours_p95: qq(ours, 0.95) };
    };
    // Electron's MAIN process, sampled (D-40): every message from the page to
    // the host is routed through it, and \`webview.getURL()\` is a synchronous
    // call into it, so its round trip is how long main takes to answer.
    const mainRtt = [];
    let mainTimer = 0;
    const startMain = () => { const tick = () => { const t = performance.now(); try { b.webview.getURL(); } catch (e) {} mainRtt.push([performance.timeOrigin + t, performance.now() - t]); if (mainRtt.length > 20000) mainRtt.shift(); mainTimer = setTimeout(tick, 20); }; tick(); };
    const stopMain = () => clearTimeout(mainTimer);
    const mainIn = (lo, hi) => { let m = 0; for (const [t, ms] of mainRtt) if (t + ms >= lo && t <= hi) m = Math.max(m, ms); return Math.round(m * 10) / 10; };
    // OUR share, by part, from the sensor's own stamps (one epoch clock): the
    // handler in the page (began -> spoke), the crossing (spoke -> the host's
    // console-message event ran), and how much of the crossing the host was
    // busy absorbing pushed drains or in long tasks.
    const hoverParts = (from, to) => {
      const xs = (b.hoverStamps || []).filter((h) => h.began >= from && h.began <= to);
      const f = (k) => xs.map(k);
      const handler = f((h) => h.sent - h.began), crossing = f((h) => h.arrived - h.sent);
      const r1 = (x) => Math.round(x * 10) / 10;
      return { n: xs.length,
               handler_p50: qq(handler, 0.5), handler_p95: qq(handler, 0.95),
               crossing_p50: qq(crossing, 0.5), crossing_p95: qq(crossing, 0.95),
               host_handle_p95: qq(f((h) => h.handled - h.arrived), 0.95),
               drain_busy_p95: qq(f((h) => h.drain_busy), 0.95), long_busy_p95: qq(f((h) => h.long_busy), 0.95),
               worst: xs.slice().sort((a, c) => (c.arrived - c.began) - (a.arrived - a.began)).slice(0, 4)
                 .map((h) => ({ handler: r1(h.sent - h.began), crossing: r1(h.arrived - h.sent),
                                drain_busy: h.drain_busy, long_busy: h.long_busy,
                                drains_crossing: h.drains_crossing, drain_kb: h.drain_kb,
                                main_max: mainRtt.length ? mainIn(h.sent, h.arrived) : null })),
               main_rtt: mainRtt.length ? { n: mainRtt.length, p50: qq(mainRtt.map((x) => x[1]), 0.5),
                                            p95: qq(mainRtt.map((x) => x[1]), 0.95), max: qq(mainRtt.map((x) => x[1]), 1) } : null,
               // Hovers that shared their crossing with a drain, and those that did not.
               crossing_with_drain_p95: qq(xs.filter((h) => h.drains_crossing > 0).map((h) => h.arrived - h.sent), 0.95),
               crossing_alone_p95: qq(xs.filter((h) => !h.drains_crossing).map((h) => h.arrived - h.sent), 0.95),
               with_drain: xs.filter((h) => h.drains_crossing > 0).length };
    };
    // Pointer moves the way a reader makes them; each one that lands on
    // ANOTHER chunk is timed from the move to the outline.
    const hoverRun = async (n, tag) => {
      const pb = b.pipebox, wv = b.webview, r = wv.getBoundingClientRect(), out = [];
      for (let i = 0; i < n; i++) {
        const x = Math.round(40 + (i * 71) % Math.max(80, r.width - 80));
        const y = Math.round(60 + (i * 113) % Math.max(80, r.height - 120));
        const before = pb.hover ? pb.hover.at : 0, beforeCid = pb.hover ? pb.hover.cid : "";
        const pushedBefore = pb.pushedHovers || 0;
        const t0 = performance.now(), sent = Date.now();
        wv.sendInputEvent({ type: "mouseMove", x, y });
        let dt = null, source = null;
        while (performance.now() - t0 < 1500) {
          await sleep(1);
          // A push answers the move whether it drew an outline or cleared one.
          if ((pb.pushedHovers || 0) > pushedBefore && pb.pushedAt >= t0) {
            dt = pb.pushedAt - t0; source = pb.hover ? pb.hover.source : "cleared"; break;
          }
          if (pb.hover && pb.hover.at >= t0 && pb.hover.at > before) { dt = pb.hover.at - t0; source = pb.hover.source; break; }
        }
        if (dt !== null || !pb.hover || pb.hover.cid !== beforeCid) out.push({ tag, ms: dt, source, sent });
        await sleep(60);
      }
      return out;
    };
  `;

  // One real page's stream, run once and read by G-92, G-97 and G-98
  // (2026-09-28: "chase this processing sequence down"; "my suspicions here
  // about deduplication and duplicate nodes in the 3D graph view"). The
  // Julia forum's /latest, new to the store under a query string of its own
  // per arm, scrolled so new topics keep arriving; then the graph's own
  // lifecycle record for that page, stage by stage.
  let lifeRun = null;
  const streamLife = () => lifeRun || (lifeRun = (async () => {
    const arm = (plant) => evaluate(`(async () => {
      ${PREP}
      const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
      v.plantLateCollapse = ${JSON.stringify(plant)} === "late";
      v.plantScatter = ${JSON.stringify(plant)} === "scatter";
      const url = "https://discourse.julialang.org/latest?life=" + ${JSON.stringify(plant || "c")} + Date.now();
      try {
        b.go("about:blank"); await sleep(600);
        b.go(url);
        await land(url, 30000);
        await sleep(3000);
        const wv = b.webview;
        for (let i = 0; i < 20; i++) {
          wv.sendInputEvent({ type: "mouseWheel", x: 300, y: 300, deltaX: 0, deltaY: -500 });
          await sleep(250);
        }
        // Saves, vectors and placements trail the scroll.
        for (let i = 0; i < 70; i++) {
          await sleep(500);
          const st = v.lifecycleState(url);
          if (i > 16 && st.saved >= 10 && st.saved_to_placed_ms.n >= 10 && st.projected_drawn >= 10) break;
        }
        if (${JSON.stringify(plant)} === "dup") {
          // Planted: a streaming node drawn beside the stored node it became.
          const d = v.graph.graphData();
          const stored = d.nodes.find((n) => !n.force && n.level !== "page" && n.url === url);
          if (stored) {
            const id = "f:" + url + "#planted-duplicate";
            v.forceSpecs.set(id, { parent: "planted", url, title: "planted", lines: 1, cid: stored.id, born: Date.now() });
            d.nodes.push({ id, force: true, level: "chunk", url, x: stored.x, y: stored.y, z: stored.z, val: 1 });
            v.graph.graphData(d);
          }
          return { plant: "dup", url, life: v.lifecycleState(url) };
        }
        // The store's side: the same CONTENT under several of this page's chunks.
        let store = null;
        if (!${JSON.stringify(plant)}) {
          const base = app.plugins.plugins["domvec-bridge"].settings.sidecar.replace(/\\/+$/, "");
          const map = await (await fetch(base + "/page_map?url=" + encodeURIComponent(url))).json();
          const cids = Object.keys(map.chunks || {});
          const seen = new Map();
          let read = 0;
          for (let i = 0; i < cids.length; i += 8) {
            const got = await Promise.all(cids.slice(i, i + 8).map((c) => fetch(base + "/chunk/" + c).then((r) => r.json()).catch(() => null)));
            for (const ch of got) {
              if (!ch) continue;
              read++;
              // A line's TEXT only: its key carries the address, and with it
              // every chunk read as distinct (2026-09-28, a vacuous first run).
              const t = (ch.lines || []).map((l) => (l && typeof l === "object" && !Array.isArray(l)) ? String(l.text || "") : "")
                .join(" ").replace(/\\s+/g, " ").trim().toLowerCase();
              if (t) seen.set(t, (seen.get(t) || 0) + 1);
            }
          }
          const extra = [...seen.values()].reduce((a, k) => a + (k - 1), 0);
          store = { chunks: cids.length, read, distinct: seen.size, extra_copies: extra,
                    share_extra: read ? Math.round((extra / read) * 1000) / 1000 : null };
        }
        return { plant: ${JSON.stringify(plant)} || "clean", url, life: v.lifecycleState(url), store };
      } finally {
        v.plantLateCollapse = false;
        v.plantScatter = false;
      }
    })()`, { timeout: 150000 });
    return { clean: await arm(""), late: await arm("late"), scatter: await arm("scatter"), dup: await arm("dup") };
  })());

  const tidyFixtures = async (origin) => {
    try {
      if (!origin) return -1;
      const listed = await ask("/pages?contains=" + encodeURIComponent(origin + "/"));
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

  //: The body S-8 evaluates in the pane: the tuned scan against the fixed one.
  //:
  //: **A tuned scan that is merely faster is not an improvement.** It is only
  //: an improvement if it captures no less, so both arms run on the same page
  //: in the same session and the addresses are compared, not just the clock.
  //:
  //: **The tuned arm goes FIRST, deliberately.** Running it second would hand
  //: it a warm HTTP cache and a warm layout, which biases in favour of the
  //: thing being argued for. Any advantage left over from ordering now falls
  //: to the arm this check is trying to beat.
  //:
  //: **The url is purged between arms.** A re-scan of a page the trie already
  //: holds drains nothing, and the tuned arm stops when the trie stops
  //: changing -- so without the purge it would "win" by measuring nothing.
  const paceProbe = (pages, sidecar) => `(async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const PAGES = ${JSON.stringify(pages)};
    const SIDE = ${JSON.stringify(sidecar)};

    for (const l of app.workspace.getLeavesOfType("domvec-chunk-view")) {
      l.detach();
    }
    for (const l of app.workspace.getLeavesOfType("domvec-browser-view")) {
      l.detach();
    }
    await sleep(700);
    // A split of the graph, never a tab in its group (that hid the graph for
    // every later check, 2026-10-07).
    const gSplit = app.workspace.getLeavesOfType("domvec-graph-view")[0];
    const leaf = gSplit ? app.workspace.createLeafBySplit(gSplit, "vertical") : app.workspace.getLeaf("tab");
    await leaf.setViewState({ type: "domvec-browser-view", active: true });
    app.workspace.revealLeaf(leaf);
    await sleep(1500);
    const b = app.workspace.getLeavesOfType("domvec-browser-view")[0].view;
    if (!b || !b.webview) return { error: "no browser pane" };

    // Live capture off for the whole comparison: a background drain every
    // 1200ms would be a third scan running through both arms.
    try { b.setLive(false); } catch (e) {}

    const purge = async (url) => {
      try {
        await fetch(SIDE + "/purge", {
          method: "POST", headers: { "content-type": "application/json" },
          body: JSON.stringify({ url }),
        });
      } catch (e) {}
    };

    const arm = async (PAGE, fixed) => {
      b.go("about:blank");
      await sleep(700);
      b.go(PAGE);
      for (let i = 0; i < 60; i++) {
        await sleep(300);
        if (!b.webview.isLoading() && b.webview.getURL().indexOf(PAGE) === 0) {
          break;
        }
      }
      const url = b.webview.getURL();
      await purge(url);
      await sleep(400);
      await b.scan(fixed ? { fixed: true } : {});
      const got = b.lastScan;
      return {
        mode: got.mode, passes: got.passes, ms: got.elapsedMs,
        addresses: got.addresses, rewrites: got.rewrites,
        mean_pause_ms: got.meanPauseMs, settled: got.settled,
        pauses: got.pauses.slice(0, 12),
        steps: (got.steps || []).slice(0, 12),
      };
    };

    // **Two pages, because the row makes two claims that separate here.**
    //
    // A SHORT page is where "time-efficient" is visible: the tuned scan stops
    // as soon as it is at the bottom and the trie has stopped changing, while
    // the fixed one counts out seven passes at 700ms regardless -- 4.2
    // seconds spent being told six times that nothing has changed.
    //
    // A TALL page with lazy blocks is where "fine-grained" and "tuned to the
    // update rate" are visible, and where the fixed cadence is revealed not
    // to finish at all.
    const out = {};
    for (const key of Object.keys(PAGES)) {
      const page = PAGES[key];
      const tuned = await arm(page, false);
      const fixed = await arm(page, true);
      await purge(b.webview.getURL());
      out[key] = {
        tuned, fixed,
        faster_by_ms: fixed.ms - tuned.ms,
        addresses_delta: tuned.addresses - fixed.addresses,
      };
    }
    return out;
  })()`;

  //: The body T-3 evaluates in the pane.
  //:
  //: The row asks that a shadow node be localized to its ANCESTORS in the
  //: trie, which is a claim about the set of addresses and their prefixes --
  //: not about any single one. So it is asked of GET /addresses rather than
  //: of /resolve, whose question ("which chunk draws this point") is the
  //: reader's and the wrong one here.
  //:
  //: Run in the browser cell rather than under Firefox: the cell runs the
  //: same sensor, read from the sidecar at request time, and driving a second
  //: browser for this would leak processes for no extra evidence.
  const shadowProbe = (page, sidecar) => `(async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const PAGE = ${JSON.stringify(page)};
    const SIDE = ${JSON.stringify(sidecar)};
    const BOUND = "/#shadow-root";

    for (const l of app.workspace.getLeavesOfType("domvec-chunk-view")) {
      l.detach();
    }
    for (const l of app.workspace.getLeavesOfType("domvec-browser-view")) {
      l.detach();
    }
    await sleep(700);
    // A split of the graph, never a tab in its group (that hid the graph for
    // every later check, 2026-10-07).
    const gSplit = app.workspace.getLeavesOfType("domvec-graph-view")[0];
    const leaf = gSplit ? app.workspace.createLeafBySplit(gSplit, "vertical") : app.workspace.getLeaf("tab");
    await leaf.setViewState({ type: "domvec-browser-view", active: true });
    app.workspace.revealLeaf(leaf);
    await sleep(1500);
    const b = app.workspace.getLeavesOfType("domvec-browser-view")[0].view;
    if (!b || !b.webview) return { error: "no browser pane" };
    try { b.setLive(false); } catch (e) {}

    b.go(PAGE);
    for (let i = 0; i < 60; i++) {
      await sleep(300);
      if (!b.webview.isLoading() && b.webview.getURL().indexOf(PAGE) === 0) break;
    }
    const url = b.webview.getURL();
    await b.scan({});
    await sleep(600);

    const got = await (await fetch(
      SIDE + "/addresses?url=" + encodeURIComponent(url))).json();
    const all = (got.addresses || []).map((a) => a.xpath);
    const shadow = all.filter((x) => x.indexOf(BOUND) >= 0);

    // **Every shadow address must have its HOST in the trie.** Cutting the
    // path at the boundary leaves the host's own address; that address is
    // what "localized to its ancestors" means, and if it is absent the
    // distilled HTML has a subtree hanging off nothing.
    const held = new Set(all);
    const orphans = [];
    for (const x of shadow) {
      const host = x.slice(0, x.indexOf(BOUND));
      // The host element itself is addressed only when it carries content,
      // so the test is that SOME held address is the host or sits under it --
      // the boundary must not be the first thing on the path either way.
      if (!host) { orphans.push(x); continue; }
      let ok = held.has(host);
      if (!ok) {
        for (const cand of held) {
          if (cand === host || cand.indexOf(host + "/") === 0) { ok = true; break; }
        }
      }
      if (!ok) orphans.push(x);
    }

    // Nesting: a root inside a root gives TWO boundary steps, and the outer
    // path must be a prefix of the inner one.
    const nested = shadow.filter(
      (x) => x.split(BOUND).length - 1 >= 2);
    let nestingOk = true;
    for (const x of nested) {
      const first = x.indexOf(BOUND);
      const outer = x.slice(0, first + BOUND.length);
      if (x.indexOf(outer) !== 0) nestingOk = false;
    }

    // A boundary step may never be the whole of an address, nor sit at the
    // root: that would be a shadow subtree with no host at all.
    const rootless = shadow.filter((x) => x.indexOf(BOUND) === 0);

    return {
      url,
      addresses: all.length,
      shadow_addresses: shadow.length,
      nested_addresses: nested.length,
      orphans: orphans.length,
      orphan_sample: orphans.slice(0, 5),
      rootless: rootless.length,
      nesting_prefix_ok: nestingOk,
      deepest: shadow.length
        ? shadow.slice().sort((a, c) => c.length - a.length)[0].slice(0, 160)
        : "",
    };
  })()`;

  //: The body S-1 evaluates in the pane.
  //:
  //: **The shape of an O(delta) claim is a constant delta against a growing
  //: page.** Timing one mutation once says the fold is fast; it does not say
  //: the cost follows the CHANGE rather than the document. So the fixture's
  //: own pager is pressed repeatedly: each press appends six result-cards --
  //: each with its own nested shadow root -- into a shadow root, so the
  //: delta is the same size every round while the page it lands in doubles,
  //: then trebles. If repairMs tracked the page, it would climb.
  //:
  //: `repairMs` is the sensor's own number for the in-page fold, reported in
  //: the drain payload. Measured here rather than re-derived: a check that
  //: reimplements what it measures can be wrong in either direction.
  //:
  //: The 2026-08-29 delta artifacts cannot answer this -- sensor.js changed
  //: on 08-31, two days AFTER they were written, and a store is a recording
  //: of what some past version did.
  const deltaProbe = (page, sidecar) => `(async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const PAGE = ${JSON.stringify(page)};
    const SIDE = ${JSON.stringify(sidecar)};
    const HANDLE = "__domvecSensor";

    for (const l of app.workspace.getLeavesOfType("domvec-chunk-view")) {
      l.detach();
    }
    for (const l of app.workspace.getLeavesOfType("domvec-browser-view")) {
      l.detach();
    }
    await sleep(700);
    // A split of the graph, never a tab in its group (that hid the graph for
    // every later check, 2026-10-07).
    const gSplit = app.workspace.getLeavesOfType("domvec-graph-view")[0];
    const leaf = gSplit ? app.workspace.createLeafBySplit(gSplit, "vertical") : app.workspace.getLeaf("tab");
    await leaf.setViewState({ type: "domvec-browser-view", active: true });
    app.workspace.revealLeaf(leaf);
    await sleep(1500);
    const b = app.workspace.getLeavesOfType("domvec-browser-view")[0].view;
    if (!b || !b.webview) return { error: "no browser pane" };
    try { b.setLive(false); } catch (e) {}

    b.go(PAGE);
    for (let i = 0; i < 60; i++) {
      await sleep(300);
      if (!b.webview.isLoading() && b.webview.getURL().indexOf(PAGE) === 0) break;
    }
    const url = b.webview.getURL();
    await b.scan({});
    await sleep(500);

    const drain = () => b.webview.executeJavaScript(
      "(function(){var h=window[" + JSON.stringify(HANDLE) + "];" +
      "if(!h) return null; var p=h.drain();" +
      "return {repairMs:(p&&p.stats&&p.stats.repairMs)||0," +
      "chunks:(p&&p.chunks?p.chunks.length:0)," +
      "addresses:(p&&p.stats?(p.stats.addresses||0):0)};})()");

    // How many cards the page is holding, counted through the open roots the
    // fixture uses -- the same boundary the sensor crosses.
    const cardCount = () => b.webview.executeJavaScript(
      "(function(){var l=document.querySelector('result-list');" +
      "if(!l||!l.shadowRoot) return -1;" +
      "return l.shadowRoot.querySelectorAll('result-card').length;})()");

    const press = () => b.webview.executeJavaScript(
      "(function(){var l=document.querySelector('result-list');" +
      "if(!l||!l.shadowRoot) return false;" +
      "var n=l.shadowRoot.getElementById('next');" +
      "if(!n) return false; n.click(); return true;})()");

    // **repairMs is CUMULATIVE and drain() does not reset it.** The sensor
    // does stats.repairMs = (stats.repairMs || 0) + (t1 - t0), and drain
    // clears front, removedIds and moves but not the timer. Read as a
    // per-delta cost it gives a monotonically rising series -- 15.5, 18.7,
    // 21.9, 25.4 -- which looks like a fold getting steadily more expensive
    // and is actually a running total of four cheap ones. The first version
    // of this check PASSED on that series, which is a green that was not
    // proof: the ratio it computed was one lifetime total over another.
    let prev = 0;
    const first = await drain();
    prev = first ? first.repairMs : 0;

    // ---- the null arm: a drain with nothing changed. ----
    await sleep(400);
    const nullDrain = await drain();
    const nullMs = (nullDrain ? nullDrain.repairMs : 0) - prev;
    prev = nullDrain ? nullDrain.repairMs : prev;

    // ---- constant delta, growing page. ----
    const rounds = [];
    for (let r = 0; r < 4; r++) {
      const before = await cardCount();
      const ok = await press();
      if (!ok) return { error: "the pager is not reachable", url };
      await sleep(500);
      const got = await drain();
      const after = await cardCount();
      const total = got ? got.repairMs : prev;
      rounds.push({
        cards_before: before, cards_after: after,
        added: after - before,
        // The DIFFERENCE, which is this delta's own fold.
        repair_ms: Math.round((total - prev) * 100) / 100,
        cumulative_ms: Math.round(total * 100) / 100,
        chunks: got ? got.chunks : 0,
      });
      prev = total;
    }

    const ms = rounds.map((r) => r.repair_ms);
    const grew = rounds[rounds.length - 1].cards_after / (rounds[0].cards_before || 1);
    return {
      url,
      null_repair_ms: Math.round(nullMs * 100) / 100,
      null_chunks: nullDrain ? nullDrain.chunks : -1,
      rounds,
      page_grew_by: Math.round(grew * 100) / 100,
      first_ms: ms[0], last_ms: ms[ms.length - 1],
      worst_ms: Math.max.apply(null, ms),
      // How the LAST delta's cost compares to the first, over a page that
      // has grown by page_grew_by. This is the O(delta) statement: an
      // identically-sized change costing the same in a much larger document.
      cost_ratio: Math.round((ms[ms.length - 1] / Math.max(ms[0], 0.01)) * 100) / 100,
    };
  })()`;

  /**
   * Bring the projector to the front and make sure it is really loaded.
   *
   * For the checks that do not go through `inPane` but still end up touching
   * the graph view -- `G-39` reaches it through the plugin's own `eachGraph`,
   * which iterates leaves and calls methods on whatever `.view` is. A
   * deferred stub has no methods, so that read as the feature being missing.
   */
  const wakeProjector = () => evaluate(`(async () => {
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    const TYPE = ${JSON.stringify(GRAPH_VIEW)};
    if (!app.workspace.getLeavesOfType(TYPE).length) {
      await app.commands.executeCommandById("domvec-open-graph");
      await sleep(1500);
    }
    const leaf = app.workspace.getLeavesOfType(TYPE)[0];
    if (!leaf) return { ok: false };
    app.workspace.revealLeaf(leaf);
    if (leaf.loadIfDeferred) await leaf.loadIfDeferred();
    for (let i = 0; i < 120; i++) {
      if (leaf.view && leaf.view.graph) return { ok: true, waited: i * 0.5 };
      await sleep(500);
    }
    return { ok: false, deferred: !!leaf.isDeferred };
  })()`);

  const CHECKS = [
    {
      id: "G-99",
      asks: "a page's structured data is detected: a ld+json document's prose fields and the media it names, and media urls in an app-state JSON script, reach the store as addressed lines; a plain script, and the app state's ids and tokens, do not; planted (nojson) none of it",
      async run() {
        // A recipe page served locally: ld+json in HEAD (name, description,
        // an image, a VideoObject with a contentUrl and thumbnail), an
        // analytics script in HEAD, and an application/json state script in
        // the body carrying a session id beside a hero picture.
        const fixtures = await serveFixtures();
        const arm = (planted) => evaluate(`(async () => {
          ${PREP}
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
          b.plant.delete("nojson");
          if (${planted}) b.plant.add("nojson");
          try {
            const PAGE = ${JSON.stringify(fixtures.origin + "/structured_data.html?g99=")} + (${planted} ? "p" : "c") + Date.now();
            b.go("about:blank"); await sleep(800);
            if (!(await land(PAGE, 30000))) return { error: "did not land" };
            let cids = [], same = 0;
            for (let i = 0; i < 40 && same < 3; i++) {
              await sleep(1000);
              const now = await v.sidecar.pageCids(PAGE);
              same = now.length && now.join() === cids.join() ? same + 1 : 0;
              cids = now;
            }
            const lines = [];
            for (const c of cids) { const p = await v.chunkPayload(c); for (const l of (p && p.lines) || []) lines.push(String(l.text || "")); }
            const all = lines.join(String.fromCharCode(10));
            const has = (x) => all.includes(x);
            return { planted: ${planted}, chunks: cids.length, lines: lines.length,
                     ld_name: has("Brown butter sugar cookies") && lines.filter((l) => l.includes("Brown butter sugar cookies")).length >= 2,
                     ld_description: has("nutty browned butter"),
                     ld_image: has("Fronalpstock_big.jpg"),
                     ld_video: has("brown-butter.mp4"),
                     ld_video_thumb: has("brown-butter-thumb.jpg"),
                     app_hero: has("hero-cookies.webp"),
                     leaked: ["a1b2c3d4e5f6", "9f8e7d", "UA-0000-1", "rcp-7f3a9c", "window.analytics"].filter(has),
                     body_text: has("crisp at the edge") && has("smells like toffee"),
                     sample: lines.filter((l) => /cookies|butter|mp4|webp/i.test(l)).slice(0, 8) };
          } finally { b.plant.delete("nojson"); }
        })()`, { timeout: 120000 });
        try {
          const clean = await arm(false);
          const planted = await arm(true);
          const ok = (x) => !!x && !x.error && x.ld_name && x.ld_description && x.ld_image && x.ld_video
            && x.ld_video_thumb && x.app_hero && x.leaked.length === 0 && x.body_text;
          return { pass: ok(clean) && !ok(planted),
                   evidence: { clean, planted, bar: "ld+json name (beside the page's own h1), description, image, video url and thumbnail; the app-state script's picture; none of its ids, the analytics script, or a non-prose ld field; the page's own text intact" } };
        } finally { await fixtures.close(); }
      },
    },
    {
      id: "G-99-media",
      asks: "every media kind on a page reaches the store as addressed lines: a video's src and poster, a video's sources and caption track, audio sources, an embedded player, an embed, an object and a picture's source set -- the page's own text intact; planted (nomedia) none of them",
      async run() {
        // Addendum IX: "all content that could possibly be detected, whether
        // it be text; json; images; videos; media". The JSON half is G-99;
        // this is the media half, surveyed kind by kind on one fixture.
        const fixtures = await serveFixtures();
        const KINDS = { video_src: "okapi-walk.mp4", video_poster: "okapi-walk-poster.jpg",
          source_webm: "okapi-feeding.webm", source_mp4: "okapi-feeding.mp4", track_vtt: "okapi-feeding.en.vtt",
          audio_ogg: "okapi-call.ogg", audio_mp3: "okapi-call.mp3", iframe: "youtube-nocookie.com/embed/okapi",
          embed: "okapi-range-map.svg", object: "okapi-census.pdf", picture_source: "okapi-portrait.avif",
          picture_img: "okapi-portrait.jpg" };
        const arm = (planted) => evaluate(`(async () => {
          ${PREP}
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
          b.plant.delete("nomedia");
          if (${planted}) b.plant.add("nomedia");
          try {
            const PAGE = ${JSON.stringify(fixtures.origin + "/media_kinds.html?g99m=")} + (${planted} ? "p" : "c") + Date.now();
            b.go("about:blank"); await sleep(800);
            if (!(await land(PAGE, 30000))) return { error: "did not land" };
            let cids = [], same = 0;
            for (let i = 0; i < 40 && same < 3; i++) {
              await sleep(1000);
              const now = await v.sidecar.pageCids(PAGE);
              same = now.length && now.join() === cids.join() ? same + 1 : 0;
              cids = now;
            }
            const lines = [];
            for (const c of cids) { const p = await v.chunkPayload(c); for (const l of (p && p.lines) || []) lines.push(String(l.text || "")); }
            const all = lines.join(String.fromCharCode(10));
            const kinds = ${JSON.stringify(KINDS)};
            const found = {};
            for (const [k, s] of Object.entries(kinds)) found[k] = all.includes(s);
            return { planted: ${planted}, chunks: cids.length, lines: lines.length, found,
                     missing: Object.keys(found).filter((k) => !found[k]),
                     body_text: all.includes("Field recordings of the okapi") && all.includes("catalogued with its date"),
                     sample: lines.filter((l) => /okapi-|youtube/.test(l)).slice(0, 12) };
          } finally { b.plant.delete("nomedia"); }
        })()`, { timeout: 120000 });
        try {
          const clean = await arm(false);
          const planted = await arm(true);
          const n = (x) => x && x.found ? Object.values(x.found).filter(Boolean).length : 0;
          return { pass: !!clean && !clean.error && clean.missing.length === 0 && clean.body_text
                     && !!planted && !planted.error && planted.body_text && n(planted) < n(clean),
                   evidence: { clean, planted, purged: await tidyFixtures(fixtures.origin) } };
        } finally { await fixtures.close(); }
      },
    },
    {
      id: "G-102",
      asks: "a billboard does not fake live controls: in the page form of a chunk, a control the trie addresses stays live (it acts on the page), and a control it holds no address for is drawn inert -- dimmed, not-allowed, aria-disabled, with a title saying why; planted (plantInertLooksLive) the dead control looks as pressable as the live one",
      async run() {
        // A newsletter box served locally: a labelled button (a unit, so an
        // address) and an icon-only button with no words (no unit, so no
        // address). Opened from the GRAPH in page form, read in its frame.
        const fixtures = await serveFixtures();
        const arm = (planted) => evaluate(`(async () => {
          ${PREP}
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
          const cfg = window.__domvecSnapshotConfig;
          if (!cfg) return { error: "this build has no snapshot config" };
          cfg.plantInertLooksLive = ${planted};
          try {
            const PAGE = ${JSON.stringify(fixtures.origin + "/controls_inert.html?g102=")} + (${planted} ? "p" : "c") + Date.now();
            if (!(await land(PAGE, 30000))) return { error: "did not land" };
            let cids = [];
            for (let i = 0; i < 60 && !cids.length; i++) { await sleep(1000); cids = await v.sidecar.pageCids(PAGE); }
            if (!cids.length) return { error: "not stored" };
            await sleep(2500);
            const node = v.graph.graphData().nodes.find((n) => cids.includes(String(n.id)))
              || { id: cids[0], url: PAGE, level: "chunk", virtual: true, x: 0, y: 0, z: 0 };
            for (const bb of v.billboardState()) v.closeBillboard(bb.id);
            await v.openBillboard(node);
            const e = v.billboards.get(String(node.id));
            for (let i = 0; i < 6 && e && e.form !== "page"; i++) { await v.switchForm(e, "page"); await sleep(400); }
            await sleep(2500);
            const f = e && e.el.querySelector("iframe.domvec-snapshot");
            const d = f && f.contentDocument;
            if (!d) { v.closeBillboard(String(node.id)); return { error: "no page form", form: e ? e.form : null }; }
            // The clone keeps no ids: the controls are found by what they show.
            const ctl = [...d.querySelectorAll("button, input, [role=button]")];
            const pick = { "#go": ctl.find((x) => /subscribe/i.test(x.textContent || "")),
                           "#icon": ctl.find((x) => x.tagName === "BUTTON" && !(x.textContent || "").trim() && x.querySelector("svg")),
                           "#email": ctl.find((x) => x.tagName === "INPUT") };
            const read = (sel) => { const el = pick[sel]; if (!el) return null;
              const cs = getComputedStyle(el);
              return { live: !!el.closest("[data-domvec-act]"), inert_marked: el.hasAttribute("data-domvec-inert"),
                       aria_disabled: el.getAttribute("aria-disabled") === "true", cursor: cs.cursor,
                       opacity: Number(cs.opacity), title: el.getAttribute("title") || "" }; };
            // The frame clones the page's chunk: the controls by their page ids.
            const out = { planted: ${planted}, cid: String(node.id), inert_count: Number(f.dataset.inert || 0), controls: ctl.length,
                          subscribe: read("#go"), icon: read("#icon"), email: read("#email") };
            v.closeBillboard(String(node.id));
            return out;
          } finally { cfg.plantInertLooksLive = false; }
        })()`, { timeout: 150000 });
        try {
          const clean = await arm(false);
          const planted = await arm(true);
          const deadSays = (x) => !!x && x.inert_marked && x.aria_disabled && x.cursor === "not-allowed" && x.opacity < 0.9 && x.title.length > 10;
          const liveLooksLive = (x) => !!x && x.live && !x.inert_marked && x.cursor !== "not-allowed";
          const ok = (r) => !!r && !r.error && liveLooksLive(r.subscribe) && deadSays(r.icon);
          return { pass: ok(clean) && !ok(planted),
                   evidence: { clean, planted, bar: "the addressed button live and unmarked; the icon-only button (no address) marked inert: aria-disabled, cursor not-allowed, dimmed, a title" } };
        } finally { await fixtures.close(); }
      },
    },
    {
      id: "G-195",
      asks: "kept: hovering a browser chunk box drives the 3D billboards with good latency -- a real pointer move onto another chunk of a stored page opens that chunk's panel, with its text, p50 < 250 ms and p90 < 600 ms; planted poll-hover (the hover found by the poll) does not",
      async run() {
        // A guard, not a feature (PLUGIN_GOAL 122: "keep"): the path is the
        // pushed hover -> `onHover` -> `highlightChunk` -> the panel, timed
        // from the move the reader makes (`sendInputEvent`) to the panel
        // holding TEXT -- the address header is there at once and is not the
        // chunk. On a page the store holds, so the panel has content to show.
        // Panels in fly-to mode for the arm, the reader's mode put back.
        const PAGE = "https://en.wikipedia.org/wiki/Trie";
        const arm = (planted) => evaluate(`(async () => {
          ${PREP}
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
          const mode = v.panelsOn;
          b.plant.delete("poll-hover");
          try {
            if (!(await land(${JSON.stringify(PAGE)}, 30000))) return { error: "did not land" };
            await sleep(4000);
            v.setPanelsOn("flyto");
            if (${planted}) b.plant.add("poll-hover");
            const wv = b.webview, r = wv.getBoundingClientRect(), out = [];
            const texty = (e) => { const body = e && e.el && e.el.querySelector(".domvec-bb-body"); return !!body && (body.textContent || "").replace(/\\s+/g, " ").trim().length > 20; };
            for (let i = 0; i < 16; i++) {
              const x = Math.round(60 + (i * 97) % Math.max(100, r.width - 120));
              const y = Math.round(90 + (i * 131) % Math.max(100, r.height - 160));
              const prev = b.lastHovered ? b.lastHovered.cid : "";
              const had = new Set(v.billboards.keys());
              const t0 = performance.now();
              wv.sendInputEvent({ type: "mouseMove", x, y });
              let hovered = null, opened = null, ms = null;
              while (performance.now() - t0 < 2500) {
                await sleep(2);
                if (!hovered && b.lastHovered && b.lastHovered.cid && b.lastHovered.cid !== prev) hovered = performance.now() - t0;
                const fresh = [...v.billboards.entries()].find(([k, e]) => !had.has(k) && texty(e));
                if (fresh) { opened = fresh[0]; ms = performance.now() - t0; break; }
              }
              // Only moves that landed on ANOTHER chunk ask for a panel.
              if (hovered !== null || ms !== null) out.push({ ms: ms === null ? null : Math.round(ms), hovered_ms: hovered === null ? null : Math.round(hovered) });
              await sleep(500);
            }
            const ok = out.filter((o) => o.ms !== null).map((o) => o.ms).sort((a, c) => a - c);
            const q = (p) => ok.length ? ok[Math.min(ok.length - 1, Math.floor(p * ok.length))] : null;
            return { planted: ${planted}, moves_on_new_chunk: out.length, opened: ok.length, p50: q(0.5), p90: q(0.9), out };
          } finally {
            b.plant.delete("poll-hover");
            v.setPanelsOn(mode);
          }
        })()`, { timeout: 180000 });
        const clean = await arm(false);
        const planted = await arm(true);
        const ok = (x) => !!x && !x.error && x.moves_on_new_chunk >= 6 && x.opened >= 0.8 * x.moves_on_new_chunk
          && x.p50 !== null && x.p50 < 250 && x.p90 !== null && x.p90 < 600;
        return { pass: ok(clean) && !ok(planted),
                 evidence: { clean, planted, bar: ">= 6 moves onto another chunk, >= 80% open a panel with text, p50 < 250 ms, p90 < 600 ms from the move" } };
      },
    },
    {
      id: "G-197",
      asks: "a chunk panel shows every picture its chunk holds and none it does not: a lazy loader's photograph drawn, not its empty stand-in; an inline SVG's namespace never drawn as a picture; an inline picture that draws is kept -- read back through the panel the reader opens",
      async run() {
        // A recipe page as copykat draws one, served locally so the only
        // motion is the check's: a share bar of inline SVGs declaring
        // `xmlns:xlink`, a WP Rocket card (`src` an empty SVG, the photo in
        // `data-lazy-src`), a lazysizes card (a 1x1 GIF, the photo in
        // `data-src`), and a data-url SVG that DRAWS (a circle) -- which must
        // survive, or "no stand-ins" was bought by dropping pictures.
        // Planted, both halves of the old behaviour: the sensor's `xmlnsurl`
        // and the sidecar's `placeholder-target` (`POST /plant`).
        const fixtures = await serveFixtures();
        const plant = async (on) => {
          const res = await fetch(`${SIDECAR}/plant`, { method: "POST", headers: { "Content-Type": "application/json" },
                                                       body: JSON.stringify({ name: "placeholder-target", on }) });
          if (!res.ok) throw new Error("/plant -> " + res.status + " " + await res.text());
        };
        const arm = async (planted) => {
          await plant(planted);
          try {
            return await evaluate(`(async () => {
              ${PREP}
              const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
              b.plant.delete("xmlnsurl");
              if (${planted}) b.plant.add("xmlnsurl");
              try {
                const PAGE = ${JSON.stringify(fixtures.origin + "/recipe_images.html?g197=")} + (${planted} ? "p" : "c") + Date.now();
                // A fresh realm, so the sensor boots under this arm's variants.
                b.go("about:blank"); await sleep(800);
                if (!(await land(PAGE, 30000))) return { error: "did not land", PAGE };
                // Stored: the page's chunk set stops changing.
                let cids = [], same = 0;
                for (let i = 0; i < 60 && same < 4; i++) {
                  await sleep(1000);
                  const now = await v.sidecar.pageCids(PAGE);
                  same = now.length && now.join() === cids.join() ? same + 1 : 0;
                  cids = now;
                }
                const lines = [];
                for (const c of cids) { const p = await v.chunkPayload(c); for (const l of (p && p.lines) || []) lines.push({ cid: c, t: String(l.text || "") }); }
                const pics = lines.filter((l) => /!\\[[^\\]]*\\]\\(/.test(l.t));
                const has = (s) => pics.filter((l) => l.t.includes(s));
                const ant = has("Camponotus"), alp = has("Fronalpstock");
                const out = {
                  planted: ${planted}, PAGE, chunks: cids.length, picture_lines: pics.length,
                  namespace_pictures: has("w3.org/1999/xlink").length,
                  lazy_photo_drawn: ant.length > 0, data_src_photo_drawn: alp.length > 0,
                  standins_drawn: pics.filter((l) => /\\((data:image\\/svg\\+xml[^)]*viewBox='0%200%20171%20171'%3E%3C\\/svg%3E|data:image\\/gif;base64,R0lGODlhAQABAAAAACH5)/.test(l.t)).length,
                  drawing_svg_kept: has("%3Ccircle").length > 0,
                  captions_kept: ["Roasted brussels sprouts", "Feta dip with pita", "a drawn dot"].filter((c) => pics.some((l) => l.t.includes(c))).length,
                  panels: [],
                };
                // The panel the reader opens, for each card's chunk.
                for (const c of [...new Set([...ant, ...alp].map((l) => l.cid))]) {
                  const r = await v.panelCompleteness(c, PAGE);
                  out.panels.push({ cid: c, md: r.forms && r.forms.markdown });
                }
                return out;
              } finally { b.plant.delete("xmlnsurl"); }
            })()`, { timeout: 180000 });
          } finally { await plant(false); }
        };
        try {
          const clean = await arm(false);
          const planted = await arm(true);
          const ok = (x) => !!x && !x.error && x.namespace_pictures === 0 && x.lazy_photo_drawn && x.data_src_photo_drawn
            && x.standins_drawn === 0 && x.drawing_svg_kept && x.captions_kept === 3
            && x.panels.length >= 1 && x.panels.every((p) => p.md && p.md.drawn && p.md.images_broken === 0
                                                       && p.md.placeholders === 0 && p.md.missing.length === 0);
          return { pass: ok(clean) && !ok(planted),
                   evidence: { clean, planted,
                               bar: "0 namespace pictures; both lazy photos drawn; 0 stand-ins drawn; the drawing SVG kept; 3 captions kept; each card's panel (markdown form): 0 broken, 0 stand-ins, nothing missing" } };
        } finally { await fixtures.close(); }
      },
    },
    {
      id: "G-89",
      asks: "the pending diff is drawn force-directed at once; transformed chunks collapse into the page view",
      async run() {
        // The contracts are a SEQUENCE -- empty, force, fit, collapse -- and
        // only a store that starts empty passes through all of it. C1-C7 are
        // read off the phase trace the fresh-store run recorded while it
        // seeded (G-87); C8 is performed here, after the fit: a page new to
        // the store, then a mutation on it.
        const fixtures = await serveFixtures();
        const page = fixtures.origin + "/live_mutate.html";
        try {
          const got = await evaluate(`(async () => {
            const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
            const st = window.__domvec.verify.state();
            const gl = app.workspace.getLeavesOfType("domvec-graph-view")[0];
            if (gl && gl.loadIfDeferred) await gl.loadIfDeferred();
            const v = gl && gl.view;
            const b = (app.workspace.getLeavesOfType("domvec-browser-view")[0] || {}).view;
            if (!v || !b) return { error: "panes not open" };
            const PAGE = ${JSON.stringify(page)};
            const mine = () => v.graph ? v.graph.graphData().nodes.filter((n) => n.force && n.url === b.webview.getURL()).length : 0;
            // The page's own chunks drawn by the projector (it is expanded).
            const projectedPage = () => v.graph ? v.graph.graphData().nodes.some((n) => !n.force && n.level !== "page" && n.url === b.webview.getURL()) : false;
            // Every pending force node of the page hangs from something drawn
            // by the projector or from another force node -- none floating.
            const hungFromPage = () => {
              if (!v.graph) return null;
              const d = v.graph.graphData();
              const f = d.nodes.filter((n) => n.force && n.level !== "page" && n.url === b.webview.getURL());
              if (!f.length) return null;
              const parented = new Set(d.links.filter((l) => l.force).map((l) => l.target.id || l.target));
              return f.filter((n) => parented.has(n.id)).length / f.length;
            };
            // Wait for a condition, sampling: how long it took, and the peak.
            const until = async (cond, ms) => {
              const t0 = Date.now(); let peak = 0;
              while (Date.now() - t0 < ms) { peak = Math.max(peak, mine()); if (cond()) return { ok: true, ms: Date.now() - t0, peak }; await sleep(150); }
              return { ok: false, ms: Date.now() - t0, peak };
            };
            const mode_at_start = v.layoutMode;
            // C8a: a page the store does not hold yet -- after the fit.
            b.go(PAGE);
            const appeared = await until(() => mine() > 0, 20000);
            const collapsed = await until(() => mine() === 0 && projectedPage(), 60000);
            // C8b: a mutation on that page, now projected.
            let hung = null, mutated = false;
            const at = await b.webview.executeJavaScript("(function(){var e=document.getElementById('add');if(!e)return null;e.scrollIntoView({block:'center'});var r=e.getBoundingClientRect();return {x:Math.round(r.left+r.width/2),y:Math.round(r.top+r.height/2)};})()");
            const count = () => b.webview.executeJavaScript("document.getElementById('items').children.length");
            let second = null, secondGone = null, afterClick = null, framePeak = 0, hungSeen = null;
            if (at) {
              const was = await count();
              const clickedAt = Date.now();
              // Every frame, not every 150 ms: a force node that the store
              // answers for within a sample is drawn and gone unseen.
              let watching = true;
              // ...and whether it hangs from the page, in the frame it exists:
              // read after a 150 ms sample it was already gone (null).
              const watch = () => { if (!watching) return; const m = mine(); framePeak = Math.max(framePeak, m);
                if (m > 0) { const h = hungFromPage(); if (h !== null) hungSeen = hungSeen === null ? h : Math.min(hungSeen, h); }
                requestAnimationFrame(watch); };
              requestAnimationFrame(watch);
              b.webview.focus();
              for (const type of ["mouseDown", "mouseUp"]) b.webview.sendInputEvent({ type, x: at.x, y: at.y, button: "left", clickCount: 1 });
              await sleep(600);
              if ((await count()) === was) await b.webview.executeJavaScript("document.getElementById('add').click(); true");
              mutated = (await count()) > was;
              second = await until(() => mine() > 0, 20000);
              hung = hungFromPage();
              secondGone = await until(() => mine() === 0, 60000);
              if (hung === null) hung = hungSeen;
              watching = false;
              // What each drain after the click carried, and why it drew what it did.
              afterClick = window.__domvecProfiler.listAll()
                .filter((t) => t.url === b.webview.getURL() && (t.facts.host_epoch || 0) >= clickedAt)
                .slice(0, 8).map((t) => ({ chunks: t.facts.chunks_in_drain ?? null, why: t.facts.why ?? null,
                                           flash: t.facts.flash ?? null, outcome: t.facts.outcome ?? null }));
            }
            try { b.setLive(false); } catch (e) {}
            try { b.go("about:blank"); } catch (e) {}
            await sleep(1500);
            try { b.setLive(true); } catch (e) {}
            const ui = window.__domvec.ui();
            return { phases: st.phases || null, label: st.label, mode_at_start,
                     c8: { appeared, collapsed, mutated, second, hung_from_page: hung, second_gone: secondGone,
                           frame_peak: framePeak, after_click: afterClick },
                     force: (ui.graph || {}).force || null,
                     pending: v.pendingState ? v.pendingState() : null };
          })()`, { timeout: 300000 });
          got.purged = await tidyFixtures(fixtures.origin);
          if (got.error) return { pass: false, evidence: got };
          const tr = got.phases;
          if (!tr || !tr.length) {
            return { pass: false, evidence: { why: "no phase trace -- G-89 is checked inside a fresh-store run", label: got.label } };
          }
          const firstForce = tr.findIndex((r) => r.mode === "force");
          const firstProj = tr.findIndex((r) => r.mode === "projector");
          const forceRows = tr.filter((r) => r.mode === "force");
          const last = tr[tr.length - 1];
          const c = {
            C1_empty_first: tr[0].mode === "empty" && tr[0].force_nodes === 0,
            C2_force_before_fit: firstForce >= 0 && (firstProj < 0 || firstForce < firstProj),
            C2_tree: tr.every((r) => r.multi_parent === 0),
            C3_drain_p95_ms: got.force ? got.force.ms_p95 : null,
            C3_ms_per_node_p95: got.force ? got.force.ms_per_node_p95 : null,
            C3_small_drain_ms_p95: got.force ? got.force.small_drain_ms_p95 : null,
            C3_largest_drain: got.force ? got.force.largest_drain : null,
            C4_pages: forceRows.length ? Math.max(...forceRows.map((r) => r.force_pages)) : 0,
            C5_force_while_unfitted: forceRows.some((r) => r.fitted === false && r.force_nodes > 0),
            C6_projector_drawn: firstProj >= 0,
            C7_collapsed_to: last.force_nodes,
            // Reached 0 after the fit: the trace's last instant can hold a
            // drain the live page itself just made.
            C7_reached_zero: firstProj >= 0 && tr.slice(firstProj).some((r) => r.force_nodes === 0),
            C8: got.c8,
          };
          return {
            pass: c.C1_empty_first && c.C2_force_before_fit && c.C2_tree
               // O(delta): per node the drain touched, and on small drains.
               // The absolute per-drain p95 is reported, not judged: a page's
               // first drain carries hundreds of chunks (13-55 ms measured).
               && (c.C3_ms_per_node_p95 === null || c.C3_ms_per_node_p95 < 0.25)
               && (c.C3_small_drain_ms_p95 === null || c.C3_small_drain_ms_p95 < 20)
               && c.C4_pages >= 2 && c.C5_force_while_unfitted
               && c.C6_projector_drawn && c.C7_reached_zero
               && got.mode_at_start === "projector"
               && got.c8.appeared.ok && got.c8.collapsed.ok
               // Appeared: in a sample, or in a frame -- placed and collapsed
               // inside 150 ms it is drawn and gone between samples.
               && got.c8.mutated && ((got.c8.second && got.c8.second.ok) || got.c8.frame_peak >= 1)
               && got.c8.hung_from_page === 1 && got.c8.second_gone && got.c8.second_gone.ok,
            evidence: { ...c, pending: got.pending, rows: tr.length, trace: tr.slice(0, 40), label: got.label },
          };
        } finally {
          await fixtures.close();
        }
      },
    },
    {
      id: "G-90",
      asks: "one drain, two outputs, one clock: the diff outlined on the page and in the 3D graph, both fast",
      async run() {
        const got = await evaluate(`(async () => {
          const b = (app.workspace.getLeavesOfType("domvec-browser-view")[0] || {}).view;
          const v = (app.workspace.getLeavesOfType("domvec-graph-view")[0] || {}).view;
          const pb = b && b.pipebox;
          const q = (xs, p) => { if (!xs || !xs.length) return null; const s = xs.slice().sort((a, b) => a - b); return Math.round(s[Math.min(s.length - 1, Math.floor(p * s.length))] * 10) / 10; };
          // Frames here: a covered window is throttled to one a second, and a
          // paint time taken then measures the throttle (2026-09-27).
          const fr = [];
          for (let i = 0; i < 5; i++) {
            const f0 = performance.now();
            await Promise.race([new Promise((r) => requestAnimationFrame(r)), new Promise((r) => setTimeout(r, 2000))]);
            fr.push(performance.now() - f0);
          }
          fr.sort((a, b) => a - b);
          return {
            overlay: pb ? { n: pb.diffLatencies.length, p50: q(pb.diffLatencies, 0.5), p95: q(pb.diffLatencies, 0.95), last: pb.lastDiff } : null,
            // The overlay's own work: boxes placed, no frame waited for.
            placed: pb ? { n: pb.diffPlaced.length, p50: q(pb.diffPlaced, 0.5), p95: q(pb.diffPlaced, 0.95) } : null,
            scene: v && v.forceStats ? { n: v.forceStats.toScene.length, p50: q(v.forceStats.toScene, 0.5), p95: q(v.forceStats.toScene, 0.95) } : null,
            // The graph's own work per drain.
            graph_ms: v && v.forceStats ? { n: v.forceStats.ms.length, p50: q(v.forceStats.ms, 0.5), p95: q(v.forceStats.ms, 0.95) } : null,
            frame_ms_p50: Math.round(fr[2]),
            // Where the slowest placements spent their time, by phase.
            // The slowest PAINTS, and the renderer's long tasks they waited on.
            worst_overlay: (pb && pb.diffLatencyAt ? pb.diffLatencies.map((ms, i) => [ms, pb.diffLatencyAt[i]]) : [])
              .sort((a, c) => c[0] - a[0]).slice(0, 3)
              .map(([ms, at]) => ({ ms: Math.round(ms), long_tasks: window.__domvecProfiler.longTasksIn
                ? window.__domvecProfiler.longTasksIn(at, at + ms) : null })),
            // Of the drains SCORED above (\`diffPlaced\`), by their own trace: the
            // profiler holds every trace of the session, and the slowest of
            // those were a planted D-35 arm's 59 s queue (2026-10-19).
            worst_placed: (pb ? pb.diffPlaced.map((ms, i) => [ms, pb.diffPlacedTraces ? pb.diffPlacedTraces[i] : ""]) : [])
              .sort((a, c) => c[0] - a[0]).slice(0, 3)
              .map(([ms, id]) => { const t = id ? window.__domvecProfiler.listAll().find((x) => x.id === id) : null;
                return { placed: Math.round(ms * 10) / 10, url: t ? t.url.slice(0, 60) : null, chunks: t ? t.facts.chunks_in_drain : null,
                         stages: t ? Object.fromEntries(["pump_wait", "absorb.queued", "absorb.pre", "absorb.apply", "absorb.transient", "absorb.covers", "absorb.flash_prep", "overlay.place", "overlay_placed", "drain_to_overlay"]
                               .filter((k) => typeof t.stages[k] === "number").map((k) => [k, Math.round(t.stages[k] * 10) / 10])) : null }; }),
          };
        })()`);
        const flowing = got.frame_ms_p50 < 50;
        return {
          // Measured over every drain of the run -- the seeding and C8 -- from
          // the instant each drain came back from the page. The app's OWN
          // work is judged always; the paint (which waits for a frame) only
          // while frames flow -- otherwise it is reported, marked throttled.
          pass: !!got.overlay && !!got.scene && got.overlay.n >= 10 && got.scene.n >= 10
             && !!got.placed && got.placed.p95 !== null && got.placed.p95 < 20
             && !!got.graph_ms && got.graph_ms.p95 !== null && got.graph_ms.p95 < 100
             && (!flowing || (got.overlay.p95 !== null && got.overlay.p95 < 150
                              && got.scene.p95 !== null && got.scene.p95 < 150)),
          evidence: { ...got, paint_judged: flowing, window: flowing ? "frames flowing" : "window throttled (covered): paint not judged" },
        };
      },
    },
    {
      id: "G-91",
      asks: "landing on a stored page draws its projected chunks at once, with no pending diff; a page left collapses into its node",
      async run() {
        // The streaming contract from the timelines of 2026-09-26 (S-1..S-7,
        // H-1): sampled every 150 ms while the reader moves between two
        // pages the fresh store already holds and has projected.
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          await window.__domvec.act("open", "graph");
          await window.__domvec.act("open", "browser");
          const b = app.workspace.getLeavesOfType("domvec-browser-view")[0].view;
          const gl = app.workspace.getLeavesOfType("domvec-graph-view")[0];
          if (gl.loadIfDeferred) await gl.loadIfDeferred();
          const v = gl.view;
          const shown = (el) => !!el && el.style.display !== "none" && el.offsetWidth > 0;
          const sample = (url) => {
            const d = v.graph ? v.graph.graphData() : { nodes: [] };
            const mine = d.nodes.filter((n) => n.url === url);
            const proj = mine.filter((n) => !n.force && n.level !== "page");
            const drift = proj.filter((n) => typeof n.fitX === "number")
              .map((n) => Math.hypot(n.x - n.fitX, n.y - n.fitY, (n.z || 0) - (n.fitZ || 0)));
            drift.sort((x, y) => x - y);
            return { proj: proj.length, force: mine.filter((n) => n.force).length,
                     boxes: b.pipebox ? b.pipebox.diffEls.filter(shown).length : 0,
                     drift: drift.length ? Math.max(...drift) : 0,
                     drift95: drift.length ? drift[Math.floor(drift.length * 0.95)] : 0 };
          };
          const visit = async (url, ms) => {
            b.go("about:blank"); await sleep(600);
            const t0 = Date.now(); b.go(url);
            let first = -1, maxForce = 0, maxBoxes = 0, maxDrift = 0, maxDrift95 = 0, last = null;
            while (Date.now() - t0 < ms) {
              const s = sample(url); last = s;
              if (first < 0 && s.proj > 0) first = Date.now() - t0;
              maxForce = Math.max(maxForce, s.force); maxBoxes = Math.max(maxBoxes, s.boxes);
              maxDrift = Math.max(maxDrift, s.drift); maxDrift95 = Math.max(maxDrift95, s.drift95);
              await sleep(150);
            }
            return { url, first_projected_ms: first, projected: last.proj, max_force: maxForce,
                     max_diff_boxes: maxBoxes, max_drift: Math.round(maxDrift * 10) / 10,
                     // p95 across a sample's nodes: a node whose transform
                     // position just moved in the stream reads as "drift"
                     // until it arrives, so one node's transient is not the
                     // layout being pushed around; most of them moving is.
                     max_drift_p95: Math.round(maxDrift95 * 10) / 10,
                     // At the END of the visit: a fresh store refits as it
                     // grows (2x rule), and during a refit every node heads for
                     // its new transform position -- "drift" then is motion to
                     // the new fit, not the layout being pushed around.
                     end_drift_p95: Math.round((last ? last.drift95 : 0) * 10) / 10 };
          };
          const A = "https://en.wikipedia.org/wiki/Radix_tree", B = "https://en.wikipedia.org/wiki/Trie";
          // Once to let any re-chunking of this build settle, then measured.
          b.go(A); await sleep(6000); b.go(B); await sleep(6000);
          const a = await visit(A, 6000);
          const bb = await visit(B, 6000);
          // A was left for B: its chunk nodes collapse once B's landing
          // settled A (the settle is a capture; give it time).
          let collapsedMs = -1;
          const t1 = Date.now();
          while (Date.now() - t1 < 20000) {
            if (sample(A).proj === 0) { collapsedMs = Date.now() - t1; break; }
            await sleep(250);
          }
          try { b.go("about:blank"); } catch (e) {}
          return { a, b: bb, left_page_collapsed_after_ms: collapsedMs,
                   collapses: (v.collapsed || []).slice(-3) };
        })()`, { timeout: 180000 });
        const ok = (x) => x.first_projected_ms >= 0 && x.first_projected_ms < 1500
          // <= 3, not 0: a live page moves on its own between two loads
          // (CLAUDE.md: measure the page before blaming the sensor), and
          // the flash was 22-34 boxes / the force cloud 145-564 nodes when
          // stored content was drawn as pending.
          // Drift is REPORTED, not judged here: what remains is the collision
          // spacing G-20/G-21 apply on purpose, and G-20 owns that measure.
          // (The force-node shoving this once caught -- S-7 -- is gone.)
          && x.projected > 0 && x.max_force <= 3 && x.max_diff_boxes <= 3;
        return {
          pass: ok(got.a) && ok(got.b) && got.left_page_collapsed_after_ms >= 0,
          evidence: got,
        };
      },
    },
    // ---- Addendum IX defects, each with its planted arm run through the plugin ----
    {
      id: "D-35",
      asks: "navigating to a new page, the overlay and the stream keep going: while the new page's first capture is being stored, what the page changes still reaches the GUI in milliseconds, and hover answers from the page's own chunking before the store knows the page",
      async run() {
        // On real sites (2026-09-27: "Tests aren't validating on the original
        // websites"): from a page the store holds to the Julia forum's /latest,
        // new to the store (a query string of its own per arm), scrolled at
        // once, so topics keep arriving while its first capture is stored.
        // Under push a quiet page leaves no trace to count, so the question is
        // not "did drains continue" but "did what the page changed DURING the
        // capture reach the GUI" -- timed by the check's own observer.
        const FROM = "https://en.wikipedia.org/wiki/Radix_tree";
        const TO = "https://discourse.julialang.org/latest";
        const arm = (planted) => evaluate(`(async () => {
          ${PREP}
          ${STREAM_SEEN}
          const pb = b.pipebox;
          b.plant.clear(); pb.plantStoreOnly = false;
          if (${planted}) { b.plant.add("serial-capture"); pb.plantStoreOnly = true; }
          const KEY = "__domvecCheck" + Math.random().toString(36).slice(2);
          try {
            await land(${JSON.stringify(FROM)}, 25000);
            await sleep(3000);
            const to = ${JSON.stringify(TO)} + "?d35=" + (${planted} ? "p" : "c") + Date.now();
            const t0 = Date.now();
            b.go(to);
            let observed = false;
            for (let i = 0; i < 300 && !observed; i++) {
              await sleep(50);
              try { if (b.webview.getURL().startsWith(${JSON.stringify(TO)}) && await b.webview.executeJavaScript("document.readyState !== 'loading'")) observed = !!(await observePage(KEY)); } catch (e) {}
            }
            // Whether a capture was in flight, sampled on the host.
            const busy = [];
            const sampler = setInterval(() => busy.push([Date.now(), !!(b.capturing || (b.captureQueue || []).length)]), 25);
            const wv = b.webview;
            const hovers = [];
            for (let i = 0; i < 12; i++) {
              for (let k = 0; k < 5; k++) {
                wv.sendInputEvent({ type: "mouseWheel", x: 300, y: 300, deltaX: 0, deltaY: -500 });
                await sleep(200);
              }
              hovers.push(...(await hoverRun(2, "during")));
            }
            clearInterval(sampler);
            await sleep(2000);
            const got = await collectPage(KEY) || { muts: [], moves: [] };
            const seen = got.muts;
            // THIS arm's page only: a prefix also matched the other arm's traces.
            const m = matchSeen(seen, to, t0, Date.now());
            const capturingAt = (t) => { let v = false; for (const [bt, on] of busy) { if (bt > t) break; v = on; } return v; };
            const during = m.rows.filter((r) => capturingAt(r.t)).map((r) => r.host);
            const hv = hovers.filter((x) => x.ms !== null).map((x) => x.ms);
            const firstDrain = (window.__domvecProfiler.listAll ? window.__domvecProfiler.listAll() : window.__domvecProfiler.list()).filter((t) => t.kind === "live" && t.url === to
              && (t.facts.chunks_in_drain || 0) > 0).map((t) => t.facts.host_epoch).filter(Boolean).sort((a, c) => a - c)[0];
            return { planted: ${planted}, observed, url: wv.getURL(),
                     first_drain_ms: firstDrain ? firstDrain - t0 : -1,
                     capturing_share: busy.length ? Math.round(100 * busy.filter((x) => x[1]).length / busy.length) / 100 : 0,
                     seen: (seen || []).length, answered: m.rows.length, unmapped: m.unmapped, unanswered: m.unanswered,
                     during_capture_ms: { n: during.length, p50: qq(during, 0.5), p95: qq(during, 0.95) },
                     all_ms: { n: m.rows.length, p50: qq(m.rows.map((r) => r.host), 0.5), p95: qq(m.rows.map((r) => r.host), 0.95) },
                     hover_ms: { asked: hovers.length, answered: hv.length, p50: qq(hv, 0.5), p95: qq(hv, 0.95),
                                 split: hoverSplit(hovers, got.moves),
                                 parts: hoverParts(t0, Date.now()),
                                 sources: hovers.reduce((a, x) => { a[x.source || "none"] = (a[x.source || "none"] || 0) + 1; return a; }, {}) } };
          } finally {
            b.plant.clear(); pb.plantStoreOnly = false;
            await dropPage(KEY);
          }
        })()`, { timeout: 180000 });
        const clean = await arm(false);
        const planted = await arm(true);
        // What the page changed while its first capture was stored reached the
        // GUI fast (p95 < 150 ms over at least 3 such changes), and hover
        // answered from the page (our share p95 < 50 ms). The planted arm -- drains held
        // behind each capture, hover from the store only -- must fail it.
        // Hover judged on OUR share of each move (after the page got it); the
        // page's own delay is reported beside it.
        const ok = (x) => x.observed && x.first_drain_ms >= 0
          && x.during_capture_ms.n >= 3 && x.during_capture_ms.p95 !== null && x.during_capture_ms.p95 < 150
          && x.hover_ms.split.n >= 5 && x.hover_ms.split.ours_p95 !== null && x.hover_ms.split.ours_p95 < 50;
        return { pass: ok(clean) && !ok(planted), evidence: { clean, planted } };
      },
    },
    {
      id: "D-40",
      asks: "on the Julia forum's /latest, through a long scroll, hover and new topics reach the overlay and the 3D stream in milliseconds -- pushed from the page, never pulled behind its long tasks -- and stay that fast to the end",
      async run() {
        // Judged on the site the lag was SEEN on (2026-09-27: "Significant
        // chunk highlight-when-hovered lag after extensive scrolling on
        // https://discourse.julialang.org/latest"; "the measurement was from
        // the julia forums"). Timed by the check's own observer, each change
        // matched to the drain that carried it (STREAM_SEEN).
        const URL = "https://discourse.julialang.org/latest";
        const arm = (planted) => evaluate(`(async () => {
          ${PREP}
          ${STREAM_SEEN}
          b.plant.clear();
          if (${planted}) { b.plant.add("pull-drain"); b.plant.add("poll-hover"); }
          const KEY = "__domvecCheck" + Math.random().toString(36).slice(2);
          try {
            const fr = [];
            for (let i = 0; i < 5; i++) {
              const f0 = performance.now();
              await Promise.race([new Promise((r) => requestAnimationFrame(r)), new Promise((r) => setTimeout(r, 2000))]);
              fr.push(performance.now() - f0);
            }
            fr.sort((a, c) => a - c);
            // A fresh realm, so the handle boots under this arm's plant.
            b.go("about:blank"); await sleep(800);
            b.go(${JSON.stringify(URL)});
            await land(${JSON.stringify(URL)}, 30000);
            await sleep(5000);
            await observePage(KEY);
            const wv = b.webview;
            const phases = [], hovers = [];
            startMain();
            // Three thirds of a long scroll, hovers between the wheel steps.
            for (let ph = 0; ph < 3; ph++) {
              phases.push(Date.now());
              for (let i = 0; i < 5; i++) {
                for (let k = 0; k < 5; k++) {
                  wv.sendInputEvent({ type: "mouseWheel", x: 300, y: 300, deltaX: 0, deltaY: -500 });
                  await sleep(140);
                }
                hovers.push(...(await hoverRun(4, ph)));
              }
            }
            phases.push(Date.now());
            stopMain();
            // The console call's own time in the page, per hover (D-40).
            let sayInPage = null;
            try { sayInPage = await b.webview.executeJavaScript("(function(){var h=window.__domvecSensor;var s=h&&h.stats?h.stats():null;return s&&s.sayHover?s.sayHover.slice():null})()"); } catch (e) {}
            await sleep(3000);
            const got = await collectPage(KEY) || { muts: [], moves: [] };
            const seen = got.muts;
            const m = matchSeen(seen, "https://discourse.julialang.org/", phases[0], phases[3]);
            const third = (t) => t < phases[1] ? 0 : t < phases[2] ? 1 : 2;
            const host = (k) => m.rows.filter((r) => k === undefined || third(r.t) === k).map((r) => r.host);
            const to3d = m.rows.map((r) => r.to3d).filter((x) => x !== null);
            const ov = m.rows.map((r) => r.overlay).filter((x) => x !== null);
            const hv = (k) => hovers.filter((x) => (k === undefined || x.tag === k) && x.ms !== null).map((x) => x.ms);
            // The fold's own wait: first mutation -> the drain sent, less the
            // drain's in-page work, per pushed drain of this arm.
            const armTraces = (window.__domvecProfiler.listAll ? window.__domvecProfiler.listAll() : []).filter((t) => t.kind === "live"
                && t.url.startsWith("https://discourse.julialang.org/") && (t.facts.host_epoch || 0) >= phases[0] && (t.facts.host_epoch || 0) <= phases[3]
                && typeof t.stages.push_transit === "number" && typeof t.stages.mutation_to_host === "number");
            const foldWait = armTraces.map((t) => t.stages.mutation_to_host - t.stages.push_transit - (t.stages["drain.call"] || 0) - (t.stages["drain.boxes"] || 0) - (t.stages["drain.pictures"] || 0));
            // ...and the fold's own phases, per drain (\`repair_parts\`).
            const rp = armTraces.map((t) => t.facts.repair_parts).filter(Boolean);
            const part = (k) => ({ p50: qq(rp.map((x) => x[k] || 0), 0.5), p95: qq(rp.map((x) => x[k] || 0), 0.95) });
            const foldParts = rp.length ? { n: rp.length, fold_ms: { p50: qq(armTraces.map((t) => t.stages.fold || 0), 0.5), p95: qq(armTraces.map((t) => t.stages.fold || 0), 0.95) },
              reclassify: part("reclassify"), walk: part("walk"), walk_fold: part("fold"), walk_emit: part("emit"), sweep_roots: part("sweep_roots"), sweep_hosts: part("sweep_hosts"),
              repairs_per_drain: part("repairs"), chunk_roots: part("chunk_roots"), roots: part("roots") } : null;
            return {
              url: wv.getURL(), frame_ms_p50: Math.round(fr[2]),
              fold_wait_ms: { n: foldWait.length, p50: qq(foldWait, 0.5), p95: qq(foldWait, 0.95) },
              fold_parts: foldParts,
              seen: (seen || []).length, answered: m.rows.length, unmapped: m.unmapped, unanswered: m.unanswered,
              pushed_payloads: b.pushedPayloads,
              to_host_ms: { p50: qq(host(), 0.5), p95: qq(host(), 0.95),
                            first_third_p95: qq(host(0), 0.95), last_third_p95: qq(host(2), 0.95),
                            n_by_third: [0, 1, 2].map((k) => host(k).length) },
              to_3d_ms: { n: to3d.length, p50: qq(to3d, 0.5), p95: qq(to3d, 0.95) },
              to_overlay_painted_ms: { n: ov.length, p50: qq(ov, 0.5), p95: qq(ov, 0.95) },
              hover_ms: { asked: hovers.length, answered: hv().length, p50: qq(hv(), 0.5), p95: qq(hv(), 0.95),
                          last_third_p95: qq(hv(2), 0.95),
                          split: hoverSplit(hovers, got.moves),
                          parts: hoverParts(phases[0], phases[3]),
                          say_in_page_ms: sayInPage && sayInPage.length ? { n: sayInPage.length, p50: qq(sayInPage, 0.5), p95: qq(sayInPage, 0.95), max: qq(sayInPage, 1) } : null,
                          split_last_third: hoverSplit(hovers.filter((x) => x.tag === 2), got.moves) },
            };
          } finally {
            b.plant.clear();
            await dropPage(KEY);
          }
        })()`, { timeout: 180000 });
        const clean = await arm(false);
        const planted = await arm(true);
        // A live page moves on its own and its network decides how many topics
        // arrive; the bar asks for enough of them to judge, and for the LAST
        // third of the scroll to be as fast as the first.
        const bar = (x) => x.answered >= 10
          && x.to_host_ms.p95 !== null && x.to_host_ms.p95 < 100
          && x.to_host_ms.last_third_p95 !== null && x.to_host_ms.last_third_p95 < 100
          && x.to_3d_ms.p95 !== null && x.to_3d_ms.p95 < 150
          && x.hover_ms.split.n >= 20 && x.hover_ms.split.ours_p95 !== null && x.hover_ms.split.ours_p95 < 30
          && x.hover_ms.split_last_third.ours_p95 !== null && x.hover_ms.split_last_third.ours_p95 < 30;
        return {
          // The planted arm is the OLD path on the SAME site -- drains pulled,
          // the fold waiting for idle, hover found by the poll -- and the same
          // bar must catch it.
          pass: bar(clean) && !bar(planted),
          evidence: { clean, planted,
                      bar: "new topics: page-delivered -> host p95 < 100 ms (and in the last third), -> 3D p95 < 150 ms; hover: OUR share (page got the move -> outline) p95 < 30 ms (and in the last third); the page's own delay reported beside it" },
        };
      },
    },
    {
      id: "G-92",
      asks: "on a real page, the stream runs in Addendum IX's order: a diff node is drawn force-directed before the store, folds into its page's root the moment the store saves it, and its chunk is placed by the fit afterwards -- never out of order",
      async run() {
        const r = await streamLife();
        const ok = (x) => !!x && x.saved >= 5 && x.folded >= Math.floor(x.saved * 0.9)
          && x.out_of_order.folded_before_saved === 0 && x.out_of_order.saved_not_folded === 0
          && x.out_of_order.placed_before_saved === 0
          && x.saved_to_folded_ms.p95 !== null && x.saved_to_folded_ms.p95 <= 100;
        return { pass: ok(r.clean.life) && !ok(r.late.life),
                 evidence: { clean: r.clean, planted_late_collapse: r.late,
                             bar: ">= 5 saved, >= 90% folded, none out of order, saved -> folding starts p95 <= 100 ms" } };
      },
    },
    {
      id: "G-97",
      asks: "each projected chunk is drawn WHERE THE FIT PUT IT: the projection replaces the force position and only collision spacing moves it after",
      async run() {
        const r = await streamLife();
        const ok = (x) => !!x && x.projected_drawn >= 10 && x.off_fit_colliders.p90 !== null && x.off_fit_colliders.p90 <= 2;
        return { pass: ok(r.clean.life) && !ok(r.scatter.life),
                 evidence: { clean: r.clean, planted_scatter: r.scatter,
                             bar: ">= 10 projected chunks drawn, p90 distance from their fit position <= 2 colliders" } };
      },
    },
    {
      id: "G-98",
      asks: "nothing is drawn twice: no streaming node left beside the stored node it became, and the store holds each chunk's content once (measured on the page's stored chunks)",
      async run() {
        const r = await streamLife();
        const ok = (x) => !!x && x.life.force_beside_stored === 0;
        return { pass: ok(r.clean) && !ok(r.dup),
                 evidence: { clean: { life: r.clean.life, store: r.clean.store }, planted_duplicate: { life: r.dup.life },
                             bar: "no force node beside its stored node; the store's content duplicates reported" } };
      },
    },
    {
      id: "D-42",
      asks: "a diff reaches the store in about one capture's time however fast the page drains: queued drains of one page ride in one capture, and what the store holds is exactly what separate captures would have stored",
      async run() {
        // 2026-09-28: "the database ingests leave out so many diffed chunks
        // for *so long*". One capture per drain, one at a time, and a scroll
        // drains faster than a capture stores: the queue grew for as long as
        // the reader scrolled. The page below writes 40 batches 120 ms apart
        // (deterministic content); the planted arm stores them one capture
        // per drain (`serial-ingest`), the clean one merges. Same page, same
        // content: the store must hold the SAME element addresses either way.
        const fixtures = await serveFixtures();
        const arm = (serial) => evaluate(`(async () => {
          ${PREP}
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
          b.plant.clear();
          if (${serial}) b.plant.add("serial-ingest");
          const q = (xs, p) => { if (!xs.length) return null; const s = xs.slice().sort((a, c) => a - c); return Math.round(s[Math.min(s.length - 1, Math.floor(p * s.length))]); };
          try {
            const url = ${JSON.stringify(fixtures.origin)} + "/busy_feed.html?every=120&rounds=40&d42=" + (${serial} ? "s" : "m") + Date.now();
            const merged0 = b.mergedCaptures;
            b.go(url);
            await land(url, 25000);
            // 2.5 s to the first batch, 40 x 120 ms, then the store catches up.
            await sleep(2500 + 40 * 120);
            const t0 = Date.now();
            while (Date.now() - t0 < 40000 && (b.capturing || (b.captureQueue || []).length)) await sleep(250);
            const drained = Date.now() - t0;
            await sleep(1500);
            const T = (window.__domvecProfiler.listAll ? window.__domvecProfiler.listAll() : window.__domvecProfiler.list()).filter((t) => t.url === url && typeof t.stages.capture_queue_wait === "number");
            const waits = T.map((t) => t.stages.capture_queue_wait);
            const life = v.lifecycleState(url);
            const base = app.plugins.plugins["domvec-bridge"].settings.sidecar.replace(/\\/+$/, "");
            const map = await (await fetch(base + "/page_map?url=" + encodeURIComponent(url))).json();
            const addrs = new Set();
            for (const xs of Object.values(map.chunks || {})) for (const x of xs) addrs.add(x);
            return { serial: ${serial}, url, captures: T.length, merged: b.mergedCaptures - merged0,
                     queue_wait_ms: { p50: q(waits, 0.5), p95: q(waits, 0.95), max: q(waits, 1) },
                     drawn_to_saved_ms: life.drawn_to_saved_ms, backlog_drained_after_ms: drained,
                     stored_chunks: Object.keys(map.chunks || {}).length, addresses: [...addrs].sort() };
          } finally {
            b.plant.clear();
          }
        })()`, { timeout: 150000 });
        try {
          const merged = await arm(false);
          const serial = await arm(true);
          const A = new Set(merged.addresses), B = new Set(serial.addresses);
          const only = (X, Y) => [...X].filter((x) => !Y.has(x));
          const same = only(A, B).length === 0 && only(B, A).length === 0 && A.size > 0;
          const fast = (x) => x.queue_wait_ms.p95 !== null && x.drawn_to_saved_ms.p95 !== null && x.drawn_to_saved_ms.p95 <= 3000;
          const strip = (x) => ({ ...x, addresses: x.addresses.length });
          return {
            pass: same && merged.merged > 0 && fast(merged) && !fast(serial),
            evidence: { merged: strip(merged), serial: strip(serial), same_store: same,
                        only_merged: only(A, B).slice(0, 5), only_serial: only(B, A).slice(0, 5),
                        bar: "merged: drawn -> saved p95 <= 3 s and the store identical to serial ingest; serial (planted) slower" },
          };
        } finally {
          await fixtures.close();
        }
      },
    },
    {
      id: "G-109",
      asks: "every view applies the backend's one central diff: a chunk the store retired (a shift moved its address) is no longer drawn in the 3D view, and a renamed chunk's node is carried over rather than left behind",
      async run() {
        // 2026-10-04: after browsing duckduckgo.com then a search, 24 of 65
        // stored-chunk nodes had no chunk in the store (retired at settle,
        // never removed from the view). The page below PREPENDS each batch
        // and re-homes the feed in a container of the other tag every round
        // (`shift=1`), so every chunk already drawn changes its positional
        // cid while its content stays: the backend names those as `renamed`
        // (a pure prepend does not -- measured on the pipeline offline: 0
        // retired, 0 renamed), and the view must drop the old node and
        // carry its place to the new one. Clean: after the feed finishes and the
        // queue drains no drawn stored-chunk node lacks a chunk in the store
        // AND renames actually happened (non-vacuity of the clean arm).
        // Planted (`plantNoDiff`): the same page, the view ignores the diff --
        // it must read stale nodes, or the metric measures nothing.
        const fixtures = await serveFixtures();
        const arm = (planted) => evaluate(`(async () => {
          ${PREP}
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
          b.plant.clear();
          v.plantNoDiff = ${planted};
          try {
            const url = ${JSON.stringify(fixtures.origin)} + "/busy_feed.html?prepend=1&shift=1&words=120&every=4000&rounds=8&g109=" + (${planted} ? "p" : "c") + Date.now();
            const before = { ...v.diffStats };
            b.go(url);
            await land(url, 25000);
            // 2.5 s to the first batch, 8 x 4 s (slow enough for each
            // batch's chunks to be embedded and drawn before the next shift
            // retires them), then the store and the projector catch up.
            // Sampled THROUGH the run, every second: the fixture's shift flips
            // between two address sets, so a chunk retired this round is back
            // in the store next round, and a single read at the end could not
            // see a retired node the view had kept (the planted arm read 0).
            let staleMax = 0;
            const tRun = Date.now();
            while (Date.now() - tRun < 2500 + 8 * 4000 + 1500) {
              await sleep(1000);
              try { staleMax = Math.max(staleMax, await v.staleStored()); } catch (e) {}
            }
            const t0 = Date.now();
            while (Date.now() - t0 < 40000 && (b.capturing || (b.captureQueue || []).length)) await sleep(250);
            await sleep(4000);
            const drawn = v.graph.graphData().nodes.filter((n) => !n.force && n.level !== "page" && n.url === url).length;
            // The PLANTED defect, put in place outright: a node for a chunk the
            // central diff RETIRED, drawn as if nothing had told the view. The
            // view has three retirement roads (the diff, the projector's gone
            // log, folding on leave), so switching one off left nothing stale
            // to see -- the instrument must still catch this one.
            let plantedCid = "";
            if (${planted}) {
              const dl = await (await fetch(${JSON.stringify(SIDECAR)} + "/diffs?url=" + encodeURIComponent(url))).json().catch(() => ({ diffs: [] }));
              const retired = [...new Set((dl.diffs || []).flatMap((x) => x.retired || []))];
              const have = new Set(await v.sidecar.pageCids(url).catch(() => []));
              // A retired cid still absent, else one the store never held: either
              // way a drawn node the store does not hold (the fixture's shift
              // flips between two address sets, so retired cids come back).
              plantedCid = retired.find((c) => !have.has(c)) || ("0000" + Date.now().toString(16)).slice(-16);
              if (plantedCid) {
                const page = v.graph.graphData().nodes.find((n) => n.level === "page" && n.url === url);
                const d0 = v.graph.graphData();
                v.graph.graphData({ nodes: d0.nodes.concat([{ id: plantedCid, level: "chunk", url, name: "planted retired", val: 1,
                                    x: (page && page.x) || 0, y: (page && page.y) || 0, z: (page && page.z) || 0 }]), links: d0.links });
              }
            }
            const stale = await v.staleStored();
            const d = v.diffStats;
            return { planted: ${planted}, url, drawn_chunks: drawn, stale, stale_max: staleMax, planted_cid: plantedCid, detail: v.staleDetail,
                     diff: { applied: d.applied - before.applied, retired_removed: d.retired_removed - before.retired_removed,
                             renamed: d.renamed - before.renamed, carried: d.carried - before.carried, known: d.known - before.known },
                     browser: { ...b.diffsApplied } };
          } finally {
            v.plantNoDiff = false;
            b.plant.clear();
          }
        })()`, { timeout: 150000 });
        try {
          const clean = await arm(false);
          const planted = await arm(true);
          const cleanOk = !clean.error && clean.drawn_chunks > 0 && clean.stale === 0
            && clean.diff.applied > 0 && clean.diff.renamed > 0;
          const plantedBites = !planted.error && !!planted.planted_cid && planted.stale > 0;
          return {
            pass: cleanOk && plantedBites,
            evidence: { clean, planted,
                        bar: "clean: >= 1 drawn chunk, 0 drawn stored chunks missing from the store, diffs applied and renames seen; planted (plantNoDiff): stale > 0" },
          };
        } finally {
          await fixtures.close();
        }
      },
    },
    {
      id: "D-37",
      asks: "new diffs are outlined where the reader looks: a chunk that loaded off screen is outlined when the reader scrolls to it, until it is saved and has been seen",
      async run() {
        // On the site it was SEEN on (2026-09-27: "Total scan feature loss seen
        // at https://duckduckgo.com/?q=radix+trie+planted962&ia=web", the
        // Search Assist panels; then "Tests aren't validating on the original
        // websites"). A query string of its own per arm makes each a page new
        // to the store.
        const arm = (planted) => evaluate(`(async () => {
          ${PREP}
          const pb = b.pipebox;
          pb.plantFlashOnly = ${planted};
          const shown = (el) => !!el && el.style.display !== "none" && el.offsetWidth > 0;
          try {
            const target = "https://duckduckgo.com/?q=radix+trie+planted962&ia=web&d37=" + (${planted} ? "p" : "c") + Date.now();
            await land(target, 25000);
            await sleep(4000);
            await b.webview.executeJavaScript(
              "(function(){var e=document.getElementById('more-results');if(!e)return 0;e.scrollIntoView({block:'center',behavior:'instant'});return 1})()");
            await sleep(500);
            const at = await b.webview.executeJavaScript(
              "(function(){var r=document.getElementById('more-results').getBoundingClientRect();return [Math.round(r.left+r.width/2),Math.round(r.top+r.height/2)]})()");
            b.webview.sendInputEvent({ type: "mouseDown", x: at[0], y: at[1], button: "left", clickCount: 1 });
            b.webview.sendInputEvent({ type: "mouseUp", x: at[0], y: at[1], button: "left", clickCount: 1 });
            // The new results arrive below the button; the store saves them.
            await sleep(3000);
            const before = { streaming: pb.streaming.size, visible: pb.diffEls.filter(shown).length };
            // The reader scrolls to them.
            await b.webview.executeJavaScript("(function(){window.scrollBy(0, 700);return 1})()");
            let maxVisible = 0, maxShown = 0;
            const t1 = performance.now();
            while (performance.now() - t1 < 1500) {
              maxVisible = Math.max(maxVisible, pb.diffEls.filter(shown).length);
              maxShown = Math.max(maxShown, pb.streamingShown || 0);
              await sleep(100);
            }
            const flash = (window.__domvecProfiler.listAll ? window.__domvecProfiler.listAll() : window.__domvecProfiler.list()).filter((t) => t.url === target && t.facts.flash).map((t) => t.facts.flash);
            return { planted: ${planted}, before_scroll: before, max_visible_after_scroll: maxVisible,
                     max_following: maxShown, drains_with_new: flash.length, flash };
          } finally {
            pb.plantFlashOnly = false;
          }
        })()`, { timeout: 120000 });
        try {
          const clean = await arm(false);
          const planted = await arm(true);
          const ok = (x) => x.max_visible_after_scroll >= 3;
          return { pass: ok(clean) && !ok(planted), evidence: { clean, planted } };
        } finally { /* nothing served */ }
      },
    },
    {
      id: "D-36",
      asks: "a pinned chunk's two panels read and look like the page: the same text in the same order, no distilled marks, the page's own colours and decorations, pictures loaded",
      async run() {
        // On the site it was SEEN on (2026-09-27: "Total scan feature loss seen
        // at https://duckduckgo.com/?q=radix+trie+planted962&ia=web", the
        // Search Assist panels; then "Tests aren't validating on the original
        // websites"). A query string of its own per arm makes each a page new
        // to the store.
        const arm = (planted) => evaluate(`(async () => {
          ${PREP}
          if (${planted}) b.plant.add("distilled-panels");
          const words = (t) => String(t || "").replace(/\\s+/g, " ").trim().toLowerCase().split(" ").filter(Boolean);
          // Share of the page's words the panel says, IN ORDER (greedy subsequence).
          const inOrder = (page, panel) => {
            const a = words(page), p = words(panel);
            let j = 0, hit = 0;
            for (const w of a) { const k = p.indexOf(w, j); if (k >= 0) { hit++; j = k + 1; } }
            return a.length ? Math.round((hit / a.length) * 100) / 100 : 0;
          };
          const lofi = (t) => /\\(\\s[^)]{1,80}\\s\\)/.test(t) || /\\]\\(/.test(t) || /^\\s*- /m.test(t);
          try {
            for (const p of b.pinnedState()) b.unpin(p.cid);
            const target = "https://duckduckgo.com/?q=radix+trie&ia=web&d36=" + (${planted} ? "p" : "c") + Date.now();
            await land(target, 25000);
            // Stored first: a pin reads its chunk from the store.
            for (let i = 0; i < 60 && !(b.pipebox && b.pipebox.map.url === target && b.pipebox.map.size > 0); i++) await sleep(250);
            await sleep(1500);
            const page = await b.webview.executeJavaScript(
              "(function(){var li=document.querySelector('article[data-testid=\\\"result\\\"]');" +
              "var s=li.querySelector('[data-result=\\\"snippet\\\"]');s.scrollIntoView({block:'center',behavior:'instant'});" +
              "var t=li.querySelector('a[data-testid=\\\"result-title-a\\\"]'),c=li.querySelector('a[data-testid=\\\"result-extras-url-link\\\"]');" +
              "return {text:li.innerText,title:getComputedStyle(t).color,crumb_color:c?getComputedStyle(c).color:null," +
              "crumb_deco:c?getComputedStyle(c).textDecorationLine:null,title_text:t.innerText.trim()}})()");
            await sleep(400);
            const at = await b.webview.executeJavaScript(
              "(function(){var r=document.querySelector('article[data-testid=\\\"result\\\"] [data-result=\\\"snippet\\\"] b').getBoundingClientRect();return [Math.round(r.left+r.width/2),Math.round(r.top+r.height/2)]})()");
            b.lastGesture = "";
            for (let i = 0; i < 2; i++) {
              b.webview.sendInputEvent({ type: "mouseDown", x: at[0], y: at[1], button: "right", clickCount: 1 });
              b.webview.sendInputEvent({ type: "mouseUp", x: at[0], y: at[1], button: "right", clickCount: 1 });
              await sleep(120);
            }
            for (let i = 0; i < 40 && !b.pinnedState().length; i++) await sleep(200);
            await sleep(2500);
            // The PINNED chunk's own panels, by cid: since G-113 a hover panel
            // can be open beside the pinned one, and the first .domvec-bb in
            // the document was the hover panel (an empty board, 2026-10-07).
            const pinCid = (b.pinnedState()[0] || {}).cid || "";
            const boards = document.querySelectorAll(".domvec-bb").length;
            const read = (sel) => {
              const own = sel + '[data-cid="' + pinCid + '"]';
              const f = document.querySelector(own + " iframe.domvec-snapshot");
              if (!f || !f.contentDocument) {
                const md = document.querySelector(sel === ".domvec-pin-card" ? own + " .domvec-browser-mdbody" : own + " .domvec-bb-body");
                const t = md ? md.innerText : "";
                return { frame: false, text: t.slice(0, 600), in_order: inOrder(page.text, t), lofi: lofi(t) };
              }
              const d = f.contentDocument, t = d.body.innerText;
              const title = [...d.querySelectorAll("a")].find((a) => a.innerText.trim() === page.title_text);
              const crumb = [...d.querySelectorAll("a")].find((a) => /›/.test(a.innerText));
              const imgs = [...d.images];
              return { frame: true, text: t.slice(0, 600), in_order: inOrder(page.text, t), lofi: lofi(t),
                       title_color: title ? getComputedStyle(title).color : null,
                       crumb_color: crumb ? getComputedStyle(crumb).color : null,
                       crumb_deco: crumb ? getComputedStyle(crumb).textDecorationLine : null,
                       images: imgs.length, images_loaded: imgs.filter((i) => i.complete && i.naturalWidth > 0).length };
            };
            const card = read(".domvec-pin-card"), board = read(".domvec-bb");
            // A chunk of the open page opened from the GRAPH (not pinned): its
            // billboard asks the browser for the snapshot (2026-09-27: "the 3D
            // gui is not reflecting the same structure of panel as in the
            // clipboard").
            const gv = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
            for (const bb of gv.billboardState()) gv.closeBillboard(bb.id);
            const other = gv.graph.graphData().nodes.find((n) => !n.force && n.level !== "page" && n.url === target
              && !b.pinnedState().some((p) => p.cid === n.id));
            let fromGraph = null;
            if (other) {
              await gv.openBillboard(other);
              await sleep(2500);
              const st = gv.billboardState().find((x) => x.id === other.id);
              fromGraph = st ? { form: st.form, elements: st.elements } : { form: "none" };
              gv.closeBillboard(other.id);
            }
            return { planted: ${planted}, pins: b.pinnedState().length, pin_cid: pinCid, boards_open: boards,
                     snapshot: b.lastSnapshot, page, card, board, from_graph: fromGraph };
          } finally {
            for (const p of b.pinnedState()) b.unpin(p.cid);
            b.plant.clear();
          }
        })()`, { timeout: 120000 });
        try {
          const clean = await arm(false);
          const planted = await arm(true);
          const looks = (x, p) => x.frame && x.in_order >= 0.9 && !x.lofi
            && x.title_color === p.title && x.crumb_color === p.crumb_color && x.crumb_deco === p.crumb_deco;
          const ok = (r) => r.pins === 1 && looks(r.card, r.page) && looks(r.board, r.page)
            && r.card.images_loaded >= 1
            && !!r.from_graph && r.from_graph.form === "page" && r.from_graph.elements > 3;
          return { pass: ok(clean) && !ok(planted), evidence: { clean, planted } };
        } finally { /* nothing served */ }
      },
    },
    {
      id: "G-93",
      asks: "streaming nodes are translucent, spread out and CALM: no upper bound on link length, relaxed attraction, siblings a whole number of diameters apart -- not a ball -- and what is drawn holds still between updates while the page drains in rapid fire",
      async run() {
        // On the Julia forum, scrolled in rapid wheel steps (2026-09-28:
        // "Force-directed scans in rapid fire on the julia page are fast and
        // responsive, but the force directed layout in 3D is way too chaotic
        // between scan updates"). Two planted arms: the old spring (`legacy`,
        // a ball) and no hold (`nohold`, every update re-shakes the tree).
        const arm = (plant) => evaluate(`(async () => {
          ${PREP}
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
          const P = v.streamParams, saved = { ...P };
          // The spring this replaced: rest 12, pull 0.6, siblings apart inside 8.
          if (${JSON.stringify(plant)} === "legacy") P.LEGACY = true;
          v.plantNoHold = ${JSON.stringify(plant)} === "nohold";
          v.plantSoftHold = ${JSON.stringify(plant)} === "softhold";
          try {
            const target = "https://discourse.julialang.org/latest?g93=" + (${JSON.stringify(plant)} || "c") + Date.now();
            b.go("about:blank"); await sleep(500);
            b.go(target);
            await land(target, 30000);
            await sleep(1500);
            const jitter0 = v.forceStats.jitter.length;
            const held0 = v.forceStats.jitterHeld.length, glide0 = v.forceStats.glide.length;
            // Sample while the page streams under rapid scrolling: force nodes of THIS page only.
            let best = null;
            const t0 = performance.now();
            let step = 0;
            while (performance.now() - t0 < 9000) {
              for (let k = 0; k < 2; k++) {
                b.webview.sendInputEvent({ type: "mouseWheel", x: 300, y: 300, deltaX: 0, deltaY: -500 });
                await sleep(250);
              }
              step++;
              const ns = v.graph.graphData().nodes.filter((n) => n.force && n.url === target && n.level !== "page");
              if (ns.length < 20) continue;
              const nn = ns.map((a) => {
                let m = Infinity;
                for (const b of ns) if (b !== a) m = Math.min(m, Math.hypot(a.x - b.x, a.y - b.y, (a.z || 0) - (b.z || 0)));
                return m;
              }).sort((x, y) => x - y);
              const r = P.RADIUS;
              const snap = { nodes: ns.length,
                nn_p10_in_radii: Math.round((nn[Math.floor(nn.length * 0.1)] / r) * 10) / 10,
                nn_p50_in_radii: Math.round((nn[Math.floor(nn.length * 0.5)] / r) * 10) / 10,
                overlapping: nn.filter((d) => d < 2 * r).length,
                translucent: ns.filter((n) => { const a = v.drawnAs(n); return a.translucent && a.alpha < 0.6; }).length };
              if (!best || snap.nodes >= best.nodes) best = snap;
            }
            // How far the already-drawn streaming nodes moved between updates.
            // Calm reads the HELD motion: each node's one glide to its fit
            // (PLUGIN_GOAL 48) is reported beside it, not hidden and not
            // counted as re-shaking (2026-10-17).
            const sorted = (a) => a.map((x) => x / P.RADIUS).sort((x, y) => x - y);
            const q = (a, p) => a.length ? Math.round(a[Math.min(a.length - 1, Math.floor(p * a.length))] * 100) / 100 : null;
            const all = sorted(v.forceStats.jitter.slice(jitter0));
            const jit = sorted(v.forceStats.jitterHeld.slice(held0));
            const gl = sorted(v.forceStats.glide.slice(glide0));
            return { planted: ${JSON.stringify(plant)} || false, best,
                     calm: { updates: jit.length, move_p50_in_radii: q(jit, 0.5), move_p90_in_radii: q(jit, 0.9),
                             all_moves_p90_in_radii: q(all, 0.9), glides: gl.length, glide_max_in_radii: q(gl, 1),
                             roots_placed: v.projectStats.roots_placed } };
          } finally {
            Object.assign(P, saved);
            v.plantNoHold = false;
            v.plantSoftHold = false;
          }
        })()`, { timeout: 120000 });
        const clean = await arm("");
        const planted = await arm("legacy");
        // The hold as it was: a spring held nodes drifted against (2026-10-30:
        // move p90 7.2 radii). `nohold` is kept as evidence only -- it read
        // CALM (0.34) because it is a ball that does not spread.
        const plantedNoHold = await arm("nohold");
        const plantedSoft = await arm("softhold");
        // Spread: the closest tenth of nodes still >= 3 radii from their
        // nearest neighbour (a visible gap), under 5% touching; all translucent.
        const ok = (x) => !!x.best && x.best.nn_p10_in_radii >= 3
          && x.best.overlapping <= x.best.nodes * 0.05 && x.best.translucent === x.best.nodes;
        // Calm: between updates the drawn nodes move under one radius (p90).
        const calm = (x) => !!x.calm && x.calm.updates >= 5 && x.calm.move_p90_in_radii !== null && x.calm.move_p90_in_radii <= 1;
        return { pass: ok(clean) && calm(clean) && !ok(planted) && !calm(plantedSoft),
                 evidence: { clean, planted_legacy: planted, planted_nohold: plantedNoHold, planted_softhold: plantedSoft,
                             bar: "nn p10 >= 3 radii, <= 5% touching, all translucent; drawn nodes move <= 1 radius (p90) between updates" } };
      },
    },
    {
      id: "G-94",
      asks: "the COLLAPSED picture is legible as seen: on screen, drawn discs do not sit on top of each other -- on a page (its chunks drawn) and after leaving it (all collapsed)",
      async run() {
        // Two pages: Wikipedia's Radix_tree (a deep tree) and the Julia
        // forum's /latest -- 229 topic rows under one page, a flat star, where
        // the ring was SEEN (2026-09-28: "Ring layouts still showing instead
        // of force directed").
        const RADIX = "https://en.wikipedia.org/wiki/Radix_tree";
        const FORUM = "https://discourse.julialang.org/latest";
        const arm = (planted, page = RADIX) => evaluate(`(async () => {
          ${PREP}
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
          const recollide = () => {
            const f = v.graph.d3Force("collide");
            if (f) f.radius(f.radius());               // re-reads every radius
            v.graph.d3ReheatSimulation && v.graph.d3ReheatSimulation();
          };
          const recentre = async () => {
            const btn = [...document.querySelectorAll("button")].find((x) => (x.textContent || "").trim() === "recentre");
            if (btn) btn.click();
            await sleep(1500);
          };
          // Two planted defects, one per arm, each caught by its own measure:
          // "overlap" -- no collision room (discs on discs); "big" -- chunks at
          // full size, which the collision pushed out to 1.1-1.8x the nearest
          // page's distance (2026-09-27).
          v.plantNoCollide = ${JSON.stringify(planted)} === "overlap";
          v.plantBigChunks = ${JSON.stringify(planted)} === "big";
          v.plantWeb = ${JSON.stringify(planted)} === "web";

          recollide();
          const PAGE = ${JSON.stringify(page)};
          // The open page's tree AS SEEN (2026-09-27: "force-directed layouts
          // have incorrect geometries and constraints", over a screenshot of
          // edges crossing a clumped ring): its drawn edges projected to the
          // screen, and how many pairs of them cross; and how many of its
          // chunks sit on the page's own billboard.
          const treeSeen = () => {
            const g = v.graph, ns = g.graphData().nodes;
            const end = (x) => (typeof x === "object" && x ? x.id : x);
            const byId = new Map(ns.map((n) => [n.id, n]));
            const mine = (n) => !!n && !n.force && n.url === PAGE && Number.isFinite(n.x);
            const scr = (n) => g.graph2ScreenCoords(n.x, n.y, n.z || 0);
            const segs = [];
            for (const l of g.graphData().links) {
              if (l.force) continue;
              const a = byId.get(end(l.source)), b = byId.get(end(l.target));
              if (!mine(a) || !mine(b)) continue;
              segs.push([a.id, b.id, scr(a), scr(b)]);
            }
            const cross = (p1, p2, p3, p4) => {
              const d = (a, b, c) => (b.x - a.x) * (c.y - a.y) - (b.y - a.y) * (c.x - a.x);
              const d1 = d(p3, p4, p1), d2 = d(p3, p4, p2), d3 = d(p1, p2, p3), d4 = d(p1, p2, p4);
              return ((d1 > 0) !== (d2 > 0)) && ((d3 > 0) !== (d4 > 0));
            };
            let crossings = 0;
            for (let i = 0; i < segs.length; i++) for (let j = i + 1; j < segs.length; j++) {
              const [a1, b1, p1, p2] = segs[i], [a2, b2, p3, p4] = segs[j];
              if (a1 === a2 || a1 === b2 || b1 === a2 || b1 === b2) continue;   // sharing an end is not a crossing
              if (cross(p1, p2, p3, p4)) crossings++;
            }
            const page = ns.find((n) => !n.force && n.level === "page" && n.url === PAGE);
            let onBillboard = 0;
            if (page && Number.isFinite(page.x)) {
              const rel = g.nodeRelSize();
              const cam = g.camera(), e = cam.matrixWorld.elements, right = [e[0], e[1], e[2]];
              const rad = (n) => { const c = scr(n), r = v.drawnRadiusOf ? v.drawnRadiusOf(n) : Math.cbrt(n.val || 1) * rel;
                const q = g.graph2ScreenCoords(n.x + right[0] * r, n.y + right[1] * r, (n.z || 0) + right[2] * r);
                return [c, Math.hypot(q.x - c.x, q.y - c.y)]; };
              const [pc, pr] = rad(page);
              for (const n of ns) { if (!mine(n) || n.level === "page") continue;
                const [c, r] = rad(n); if (Math.hypot(c.x - pc.x, c.y - pc.y) < pr + r) onBillboard++; }
            }
            return { edges: segs.length, crossings, on_billboard: onBillboard, tree: page ? page.discTree || null : null };
          };
          // FORCE-DIRECTED, tested directly (2026-09-28: "Layouts still
          // collapsing to something likely non force directed. This is a flat
          // circle"): the page's biggest hub is moved three collider steps and
          // the simulation reheated; in a tree laid out by forces its children
          // FOLLOW it, in a pinned geometry they stay in their slots. Also the
          // spread of distances from the page -- a ring has almost none.
          const followTest = async () => {
            const g = v.graph, d = g.graphData();
            const end = (x) => (typeof x === "object" && x ? x.id : x);
            const byId = new Map(d.nodes.map((n) => [n.id, n]));
            const mine = (n) => !!n && !n.force && n.url === PAGE && n.level !== "page" && Number.isFinite(n.x);
            const kids = new Map();
            for (const l of d.links) {
              if (l.force) continue;
              const a = byId.get(end(l.source)), c = byId.get(end(l.target));
              if (mine(a) && mine(c)) { const k = kids.get(a.id) || []; k.push(c); kids.set(a.id, k); }
            }
            const page = d.nodes.find((n) => !n.force && n.level === "page" && n.url === PAGE);
            const dist = page ? d.nodes.filter(mine).map((n) => Math.hypot(n.x - page.x, n.y - page.y, (n.z || 0) - (page.z || 0))) : [];
            const mean = dist.length ? dist.reduce((a, c) => a + c, 0) / dist.length : 0;
            const cv = mean ? Math.sqrt(dist.reduce((a, c) => a + (c - mean) * (c - mean), 0) / dist.length) / mean : 0;
            const hub = [...kids.entries()].sort((a, c) => c[1].length - a[1].length)[0];
            if (!hub || hub[1].length < 2) return { children: 0, follow: null, radial_cv: Math.round(cv * 100) / 100 };
            const h = byId.get(hub[0]), D = 3 * (h.discStep || 4);
            const before = hub[1].map((c) => [c.x, c.y, c.z || 0]);
            const e = g.camera().matrixWorld.elements, r = [e[0], e[1], e[2]];
            h.x += r[0] * D; h.y += r[1] * D; h.z = (h.z || 0) + r[2] * D; h.vx = 0; h.vy = 0; h.vz = 0;
            g.d3ReheatSimulation();
            await sleep(2500);
            const moved = hub[1].map((c, i) => Math.hypot(c.x - before[i][0], c.y - before[i][1], (c.z || 0) - before[i][2]));
            return { children: hub[1].length, follow: Math.round((moved.reduce((a, c) => a + c, 0) / moved.length / D) * 100) / 100,
                     radial_cv: Math.round(cv * 100) / 100 };
          };
          // An orbit the way a reader makes one: the camera swung 70 degrees
          // round the page, then the controls' own "end".
          const orbit = async () => {
            const g = v.graph, page = g.graphData().nodes.find((n) => !n.force && n.level === "page" && n.url === PAGE);
            if (!page) return false;
            const c = g.camera().position, t = { x: page.x, y: page.y, z: page.z || 0 };
            const dx = c.x - t.x, dz = c.z - t.z, a = 70 * Math.PI / 180;
            g.cameraPosition({ x: t.x + dx * Math.cos(a) - dz * Math.sin(a), y: c.y + (c.y - t.y) * 0.3,
                               z: t.z + dx * Math.sin(a) + dz * Math.cos(a) }, t, 0);
            await sleep(100);
            g.controls().dispatchEvent({ type: "end" });
            await sleep(900);
            return true;
          };
          // How far an open page's chunks are drawn from their OWN page, in
          // units of the distance to the nearest other page (2026-09-27: "way
          // too far from the original set of nodes" -- spacing is not it).
          const nearPage = () => {
            const ns = v.graph.graphData().nodes;
            const pages = ns.filter((n) => !n.force && n.level === "page" && Number.isFinite(n.x));
            const byUrl = new Map(pages.map((p) => [p.url, p]));
            const nn = (p) => { let m = Infinity; for (const q of pages) { if (q === p) continue;
              m = Math.min(m, Math.hypot(p.x - q.x, p.y - q.y, (p.z || 0) - (q.z || 0))); } return m; };
            const r = [];
            for (const c of ns) {
              if (c.force || c.level === "page" || !Number.isFinite(c.x)) continue;
              const p = byUrl.get(c.url);
              if (p) r.push(Math.hypot(c.x - p.x, c.y - p.y, (c.z || 0) - (p.z || 0)) / nn(p));
            }
            r.sort((a, b) => a - b);
            const q = (f) => r.length ? Math.round(r[Math.min(r.length - 1, Math.floor(r.length * f))] * 100) / 100 : null;
            // A SIMPLE TREE: how many drawn nodes hang from more than one
            // parent (2026-09-27: an open page read as a web of links).
            const end = (x) => (typeof x === "object" && x ? x.id : x);
            const parents = new Map();
            for (const l of v.graph.graphData().links) {
              if (l.force) continue;
              const t = end(l.target);
              parents.set(t, (parents.get(t) || 0) + 1);
            }
            const multi = [...parents.values()].filter((k) => k > 1).length;
            return { chunks: r.length, p50: q(0.5), p90: q(0.9), max: q(1), multi_parent: multi };
          };
          try {
            await land(PAGE, 30000);
            await sleep(6000);
            await recentre(); await sleep(2500);
            const onPage = v.seenLayout();
            onPage.near_page = nearPage();
            onPage.tree_seen = treeSeen();
            onPage.follows = await followTest();
            await sleep(1500);
            const orbited = await orbit();
            const afterOrbit = orbited ? v.seenLayout() : null;
            if (afterOrbit) afterOrbit.tree_seen = treeSeen();
            b.go("about:blank");
            // Collapsed: the page's chunks fold into its node once it is settled.
            for (let i = 0; i < 40; i++) {
              await sleep(250);
              const left = v.graph.graphData().nodes.filter((n) => !n.force && n.level !== "page"
                && n.url === PAGE).length;
              if (!left) break;
            }
            await recentre(); await sleep(2500);
            return { planted: ${JSON.stringify(planted)}, page: PAGE, on_page: onPage, after_orbit: afterOrbit, collapsed: v.seenLayout() };
          } finally {
            v.plantNoCollide = false;
            v.plantBigChunks = false;
            v.plantWeb = false;

            recollide();
          }
        })()`, { timeout: 120000 });
        const clean = await arm(false);

        const planted = await arm("overlap");
        const plantedBig = await arm("big");
        const plantedWeb = await arm("web");
        // A reader sees a jumble when discs cover each other: at most 5% of
        // drawn nodes may overlap a neighbour, and the closest tenth must at
        // least touch (nearest neighbour >= r_a + r_b).
        // Legible = nothing mostly HIDDEN: a node whose centre sits within half
        // the radius-sum of another is buried behind it. Partial overlap of
        // spheres in a 3D view is a depth cue, not a jumble -- 150 discs on a
        // 800x850 canvas overlap ~10% even placed at random -- so it is
        // reported, and the bar is on burial (2026-09-27; was "<= 5%
        // overlapping", which no 3D cloud of this density can meet).
        const legible = (x) => !!x && x.drawn > 5 && x.buried <= Math.max(1, x.drawn * 0.05);
        // Near its page: an open page's chunks stay inside its neighbourhood
        // (the farthest nearer its own page than any other: under half the
        // distance to the nearest other page).
        const near = (x) => !!x && !!x.near_page && x.near_page.chunks > 0 && x.near_page.max <= 0.5;   // < D/2: nearer its own page than any other
        const tree = (x) => !!x && !!x.near_page && x.near_page.multi_parent === 0;
        // A tree drawn in 3D: the edges it projects to the screen are counted
        // and REPORTED (a 3D tree seen from any side crosses itself on screen;
        // nothing turns it to face the camera -- 2026-09-28: "this is an
        // unneeded addition that needs to be removed"). What is judged is that
        // the page's own billboard is not buried under its chunks.
        const planar = (x) => !!x && !!x.tree_seen && x.tree_seen.edges > 0
          && x.tree_seen.on_billboard <= Math.max(1, Math.round(x.tree_seen.edges * 0.05));
        // Projected chunks sit at their fit (G-97 judges that); the follow
        // test and the distance spread are reported, not judged -- an open
        // page is the fit's picture, not a force layout (2026-09-28).
        const ok = (r) => near(r.on_page) && tree(r.on_page) && legible(r.on_page) && planar(r.on_page)
          && legible(r.collapsed);
        return { pass: ok(clean) && !legible(planted.on_page) && !near(plantedBig.on_page) && !tree(plantedWeb.on_page),
                 evidence: { clean, planted_overlap: planted, planted_big: plantedBig, planted_web: plantedWeb } };
      },
    },
    {
      id: "G-101",
      asks: "the hard pages, browsed in the app: every one captured and stored, overlay in milliseconds, its first 3D node within seconds, pictures stored where it shows pictures",
      async run() {
        const PAGES = [
          "https://archive.org/", "https://www.youtube.com/", "https://www.instagram.com/",
          "https://www.amazon.com/", "https://www.facebook.com/", "https://www.netflix.com/",
          "https://www.imdb.com/", "https://duckduckgo.com/?q=patricia+trie&ia=web",
          "https://www.richardmille.com/", "https://bandcamp.com/",
        ];
        const visit = (url, planted) => evaluate(`(async () => {
          ${PREP}
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
          const P = window.__domvecProfiler;
          if (${planted}) b.setLive(false);
          try {
            const t0 = performance.now();
            b.go(${JSON.stringify(url)});
            // Watched FROM THE START, while the page loads: IMDb took ~16 s to
            // finish loading and Netflix never finished, and a watch begun
            // after the load saw their streaming nodes only after they had
            // been saved and collapsed -- or never (2026-09-27; the app had
            // drawn them 7-8 ms after the first drain).
            let here = "", first3d = -1;
            const seen = (async () => {
              while (performance.now() - t0 < 30000 && first3d < 0) {
                try { here = b.webview.getURL(); } catch (e) {}
                if (here && v.graph && v.graph.graphData().nodes.some((n) => n.url === here && n.level !== "page"))
                  first3d = performance.now() - t0;
                await sleep(100);
              }
            })();
            await land(${JSON.stringify(url)}, 30000);   // some pages never stop loading
            try { here = b.webview.getURL(); } catch (e) {}
            while (performance.now() - t0 < 16000) {
              await sleep(250);
              try { here = b.webview.getURL(); } catch (e) {}
              if (first3d < 0 && v.graph && v.graph.graphData().nodes.some((n) => n.url === here && n.level !== "page"))
                first3d = performance.now() - t0;
            }
            await seen;
            // Every drain SINCE THE VISIT BEGAN, whatever url it was for: a
            // page that routes itself mid-visit (YouTube -> a Shorts page) left
            // its drains filed under the url it started on (2026-09-27).
            const tr = (P.listAll ? P.listAll() : P.list()).filter((t) => t.kind === "live" && t.t0 >= t0 && t.url && !t.url.startsWith("about:"));
            const ov = tr.map((t) => t.stages.drain_to_overlay).filter((x) => typeof x === "number").sort((a, c) => a - c);
            // The overlay's OWN cost -- placing the boxes, no frame waited for.
            const placed = tr.map((t) => t.stages.overlay_placed).filter((x) => typeof x === "number").sort((a, c) => a - c);
            // And the frame rate here: Chromium throttles a covered window to
            // ONE frame a second (measured 2026-09-27: 984-1027 ms per frame,
            // visible and focused), so a paint time taken then is the
            // throttle, not the app.
            const fr = [];
            for (let i = 0; i < 5; i++) {
              const f0 = performance.now();
              await Promise.race([new Promise((r) => requestAnimationFrame(r)), sleep(2000)]);
              fr.push(performance.now() - f0);
            }
            fr.sort((a, c) => a - c);
            const d3 = tr.map((t) => t.stages.drain_to_3d).filter((x) => typeof x === "number").sort((a, c) => a - c);
            const pct = (xs, q) => xs.length ? Math.round(xs[Math.min(xs.length - 1, Math.floor(xs.length * q))] * 10) / 10 : null;
            const errs = tr.filter((t) => /error|failed/i.test(String(t.facts.why || ""))).length;
            let page = null;
            try {
              page = await b.webview.executeJavaScript("(function(){var vis=function(e){var r=e.getBoundingClientRect();return r.width>8&&r.height>8};" +
                "var t=(document.body&&document.body.innerText)||'';return {title:document.title.slice(0,60),text_chars:t.length," +
                "images:[].filter.call(document.images,vis).length,videos:document.querySelectorAll('video').length," +
                "json_scripts:document.querySelectorAll('script[type*=json]').length,iframes:document.querySelectorAll('iframe').length," +
                "shadow_hosts:[].filter.call(document.querySelectorAll('*'),function(e){return !!e.shadowRoot}).length," +
                "login_wall:/log ?in|sign ?in|create (new )?account/i.test(t.slice(0,4000))&&t.length<6000}})()");
            } catch (e) { page = { error: String(e).slice(0, 80) }; }
            // The page's own motion, no gesture: drains with chunks in 5 s idle.
            const before = (P.listAll ? P.listAll() : P.list()).filter((t) => t.kind === "live" && t.url === here && t.facts.chunks_in_drain).length;
            await sleep(5000);
            const idle = (P.listAll ? P.listAll() : P.list()).filter((t) => t.kind === "live" && t.url === here && t.facts.chunks_in_drain).length - before;
            return { url: ${JSON.stringify(url)}, landed: here, planted: ${planted},
                     drains: tr.length, drains_with_chunks: tr.filter((t) => t.facts.chunks_in_drain).length,
                     chunks_drained: tr.reduce((s, t) => s + (t.facts.chunks_in_drain || 0), 0),
                     overlay_p50: pct(ov, 0.5), overlay_p95: pct(ov, 0.95), to3d_p50: pct(d3, 0.5),
                     overlay_placed_p95: pct(placed, 0.95), frame_ms_p50: Math.round(fr[2]),
                     first_3d_ms: Math.round(first3d), capture_errors: errs, idle_drains_with_chunks: idle, page };
          } finally {
            if (${planted}) b.setLive(true);
          }
        })()`, { timeout: 90000 });
        const rows = [];
        for (const url of PAGES) {
          let r;
          try { r = await visit(url, false); } catch (e) { r = { url, error: String(e).slice(0, 120) }; }
          try {
            const st = await ask("/page_status?url=" + encodeURIComponent(r.landed || url));
            r.stored = { chunks: st.chunks, embedded: st.embedded, projected: st.projected, kinds: st.kinds,
                         over_window: st.over_window, tokens_max: st.tokens_max };
          } catch (e) { r.stored = { error: String(e).slice(0, 80) }; }
          rows.push(r);
        }
        const judge = (r) => {
          const why = [];
          if (r.error) why.push("error");
          if (!(r.stored && r.stored.chunks > 0)) why.push("nothing stored");
          // The overlay's own work, always; the paint only when frames flow.
          if (!(r.overlay_placed_p95 !== null && r.overlay_placed_p95 !== undefined && r.overlay_placed_p95 < 50)) why.push("overlay placement p95 >= 50 ms");
          if (r.frame_ms_p50 < 50 && !(r.overlay_p95 !== null && r.overlay_p95 < 100)) why.push("overlay paint p95 >= 100 ms at full frame rate");
          if (!(r.first_3d_ms >= 0 && r.first_3d_ms < 8000)) why.push("no 3D node within 8 s");
          if (r.page && r.page.images > 2 && !(r.stored && r.stored.kinds && r.stored.kinds.images > 0)) why.push("shows pictures, stores none");
          if (r.capture_errors) why.push("capture errors");
          return why;
        };
        for (const r of rows) r.failed = judge(r);
        // Non-vacuity: the same judgement on a visit with live capture OFF
        // must fail (a page-scoring check that could not see a dead stream
        // would pass everything).
        const plantedRow = await visit("https://duckduckgo.com/?q=radix+trie+planted" + Date.now() % 1000 + "&ia=web", true);
        plantedRow.stored = await ask("/page_status?url=" + encodeURIComponent(plantedRow.landed)).then((s) => ({ chunks: s.chunks, kinds: s.kinds })).catch(() => ({}));
        plantedRow.failed = judge(plantedRow);
        const passing = rows.filter((r) => !r.failed.length).length;
        return { pass: passing === rows.length && plantedRow.failed.length > 0,
                 evidence: { passing, of: rows.length, rows, planted: plantedRow } };
      },
    },
    {
      id: "G-108",
      asks: "while a page streams into the 3D view, nothing elsewhere moves, and what moves on the page glides: no node jumps across a frame, none vibrates",
      async run() {
        // 2026-09-29: "The force-directed methods are still throwing glitches."
        // The flight recorder (`motion.ts`) caught, on the live forum: 210
        // teleports and 257 vibrating nodes in 20 s, the worst on pages nobody
        // was touching; chunks assigned new fit coordinates outright (190-256
        // units in a frame); collide resolving whole overlaps at once. Three
        // fixes, three planted arms, one deterministic input: the busy feed
        // (40 batches, 120 ms apart), recorded with NO cameras -- screenshots
        // and inspection frames cut the frame rate from 197 to 57 fps and put
        // stalls into what they measured.
        const fixtures = await serveFixtures();
        const arm = (flags, tag) => evaluate(`(async () => {
          ${PREP}
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
          const flags = ${JSON.stringify(flags)};
          Object.assign(v, flags);
          try {
            const url = ${JSON.stringify(fixtures.origin)} + "/busy_feed.html?every=120&rounds=40&g108=" + ${JSON.stringify(tag)} + Date.now();
            b.go(url);
            await land(url, 25000);
            await sleep(800);
            v.motion.start({ seconds: 14 });
            await sleep(14500);
            let r = null;
            for (let i = 0; i < 20 && !r; i++) { r = v.motion.state().result; if (!r) await sleep(500); }
            if (!r) return { error: "the recorder returned nothing" };
            const here = (u) => String(u).split("#")[0] === url;
            const split = (k) => { let on = 0, off = 0; for (const [u, n] of (r.by_url && r.by_url[k]) || []) { if (here(u)) on += n; else off += n; } return { on, off }; };
            return { flags, url, frames: r.frames, fps: r.fps, counts: r.counts, teleports: split("teleports"),
                     vibrating: split("vibrating"), drifting: split("drifting"), stalls: { n: r.stalls.n, worst_ms: r.stalls.worst_ms },
                     events: (r.events || []).reduce((m, e) => (m[e.kind] = (m[e.kind] || 0) + 1, m), {}),
                     worst: (r.teleports || []).slice(0, 3).map((a) => ({ id: a.id.slice(0, 40), force: a.force, world_jump: a.world_jump,
                                                                           gap_ms: a.jump_gap_ms, forces: a.forces, near: a.near_event && a.near_event.kind })) };
          } finally {
            Object.assign(v, Object.fromEntries(Object.keys(flags).map((k) => [k, false])));
          }
        })()`, { timeout: 90000 });
        const clean = await arm({}, "c");
        const noCalm = await arm({ plantNoCalm: true }, "n");
        const noGovernor = await arm({ plantNoGovernor: true }, "g");
        const teleport = await arm({ plantTeleport: true }, "t");
        const still = (x) => !x.error && x.teleports.off === 0 && x.vibrating.off === 0 && x.drifting.off === 0;
        const smooth = (x) => !x.error && x.counts.teleports <= 5 && x.counts.vibrating <= 2;
        const streamed = (x) => !x.error && (x.events.drain || 0) >= 5;
        return {
          // Each fix answerable for its own bar: calm for "nothing elsewhere",
          // the governor and the glide for "no jumps" on the page.
          pass: streamed(clean) && still(clean) && smooth(clean)
            && !(still(noCalm) && smooth(noCalm)) && !smooth(noGovernor) && !smooth(teleport),
          evidence: { clean, no_calm: noCalm, no_governor: noGovernor, teleport },
        };
      },
    },
    {
      id: "G-110",
      asks: "right-click on a page (url) node folds its chunks into the node, and right-click again draws the page's whole stored chunk set at its UMAP positions; a folded page stays folded under placements",
      async run() {
        // 2026-10-04: "no right-click on central url nodes collapsing the
        // chunks into the node and expanding the full UMAPped chunk set."
        // The handler used to release the search scope whatever was clicked.
        //
        // One page of the working store, its right-click handler fired the way
        // the pane fires it (the graph's own `onNodeRightClick` callback, not
        // a method the check chose), and the claim read off the graph:
        //   1. chunk nodes drawn -> right-click -> none drawn, the page node
        //      stays, the scope was not released, and a placement of the
        //      page's chunks (what a browse produces) does not redraw them;
        //   2. right-click again -> every chunk the sidecar can place for the
        //      page is drawn, at the position `place` gave it (the UMAP fit),
        //      and nothing is drawn that the store does not hold.
        // "Can place" is asked of the sidecar independently of the pane, so a
        // pane that drew only the first unfold step (a handful) fails against
        // a page_map of dozens. The planted arm is the old handler
        // (`plantNoToggle`): the collapse half must fail.
        const arm = (planted) => evaluate(`(async () => {
          ${PREP}
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
          const g = v.graph;
          const base = app.plugins.plugins["domvec-bridge"].settings.sidecar.replace(/\\/+$/, "");
          const poll = async (cond, ms) => { const t = performance.now(); while (performance.now() - t < ms) { if (cond()) return true; await sleep(250); } return cond(); };
          // The handler the pane registered with the graph, fired as the graph
          // fires it (no handler registered fires nothing, and the arm fails).
          const click = (node) => { const h = g.onNodeRightClick(); if (typeof h === "function") h(node); };
          const origScope = v.onScope, scopeCalls = [];
          v.onScope = (u) => { scopeCalls.push(u); return origScope.call(v, u); };
          try {
            v.plantNoToggle = false;
            const pages = g.graphData().nodes.filter((n) => n.level === "page" && !n.force && /^https?:/.test(n.url || "")
              && n.members >= 3 && n.members <= 400).sort((x, y) => (x.members - y.members) || String(x.url).localeCompare(String(y.url)));
            let page = null, cids = [];
            for (const p of pages.slice(0, 6)) {
              const c = await v.sidecar.pageCids(p.url).catch(() => []);
              if (c.length >= 3) { page = p; cids = c; break; }
            }
            if (!page) return { planted: ${planted}, error: "no stored page with >= 3 chunks is drawn as a page node", pages: pages.length };
            const url = page.url;
            const chunks = () => g.graphData().nodes.filter((n) => n.url === url && n.level !== "page" && !n.force);
            const pageNodes = () => g.graphData().nodes.filter((n) => n.id === "page:" + url && !n.force).length;
            // The state under test: the page's chunks drawn, by the same path.
            if (!chunks().length) { await v.togglePage(page); await poll(() => chunks().length > 0, 30000); }
            await sleep(1500);
            const opened = chunks().length;
            const map = await (await fetch(base + "/page_map?url=" + encodeURIComponent(url))).json();
            const mapChunks = Object.keys(map.chunks || {}).length;
            // What the sidecar can place for this page, independent of the pane.
            const oracle = await v.sidecar.place(cids);
            const placeable = ((oracle && oracle.nodes) || []).filter((n) => n.level !== "page" && n.cid).map((n) => n.cid);
            v.plantNoToggle = ${planted};
            scopeCalls.length = 0;
            click(g.graphData().nodes.find((n) => n.id === "page:" + url && !n.force) || page);
            await poll(() => chunks().length === 0, 4000);
            const afterCollapse = chunks().length;
            const collapsed = { drawn: afterCollapse, page_node: pageNodes(), scope_calls: scopeCalls.length,
                                in_set: v.collapsedByReader.has(url) };
            // A placement of the page's chunks must not redraw the folded page.
            let stays = null;
            if (!${planted}) {
              const got = await v.sidecar.place(cids.slice(0, 8));
              if (got && got.nodes) v.absorb(got.nodes, got.edges);
              await sleep(1500);
              stays = chunks().length === 0;
            }
            scopeCalls.length = 0;
            click(g.graphData().nodes.find((n) => n.id === "page:" + url && !n.force) || page);
            let last = -1, steady = 0;
            await poll(() => { const k = chunks().length; steady = (k === last && k > 0) ? steady + 1 : 0; last = k; return steady >= 8; }, 40000);
            const drawn = chunks();
            const ids = new Set(drawn.map((n) => n.id));
            const have = new Set(cids);
            const missing = placeable.filter((c) => !ids.has(c));
            const phantom = [...ids].filter((i) => !have.has(i) && !String(i).startsWith("path:"));
            return { planted: ${planted}, url, stored: cids.length, page_map_chunks: mapChunks, placeable: placeable.length,
                     opened, collapsed, stays_collapsed: stays,
                     expanded: { drawn: drawn.length, missing: missing.length, missing_sample: missing.slice(0, 3),
                                 phantom: phantom.length, scope_calls: scopeCalls.length,
                                 in_collapsed_set: v.collapsedByReader.has(url) },
                     toggles: v.toggled.slice(-4) };
          } finally {
            v.onScope = origScope;
            v.plantNoToggle = false;
          }
        })()`, { timeout: 180000 });
        const clean = await arm(false);
        const planted = await arm(true);
        const foldsAndStays = (x) => !x.error && x.opened > 0 && x.collapsed.drawn === 0 && x.collapsed.page_node === 1
          && x.collapsed.scope_calls === 0 && x.collapsed.in_set && x.stays_collapsed === true;
        // The expansion is the whole stored set: nothing the sidecar can place
        // is absent, nothing the store lacks is drawn, and at least the page's
        // placeable chunks (not a first step's handful) are there.
        const expandsAll = (x) => !x.error && x.placeable >= 3 && x.expanded.drawn >= x.placeable
          && x.expanded.missing === 0 && x.expanded.phantom === 0 && !x.expanded.in_collapsed_set
          && x.expanded.scope_calls === 0;
        return {
          pass: foldsAndStays(clean) && expandsAll(clean) && !foldsAndStays(planted),
          evidence: { clean, planted },
        };
      },
    },
    {
      id: "G-113",
      asks: "hovering a chunk on the page flies the 3D camera to THAT chunk's node and opens its panel at once with content, the outline fits inside the page, and the panel closes when the hover ends -- a planted no-focus arm does none of it",
      async run() {
        // 2026-10-06: "hovering overlays should zoom-focus the camera in the
        // 3D editor on the specific chunk ... when this flying happens, this
        // also opens the panels on the 3D side, but closes them when the
        // hovering stops"; then "Billboards don't close, are *very slow* to
        // render, and don't show anything at all ... Please ensure you're
        // capturing this in our tests along with your fixes."
        //
        // Real pointer input in the guest (`webContents.sendInputEvent`), the
        // way the reader's mouse reaches the page. Each arm hovers a chunk the
        // store holds, reads the graph's own focus record and billboard log,
        // then leaves the page and reads whether the panel closed.
        const fixtures = await serveFixtures();
        const page = fixtures.origin + "/shadow_catalogue.html";
        const arm = (planted, given) => evaluate(`(async () => {
          ${PREP}
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
          const PAGE = ${JSON.stringify(page)};
          const out = { planted: ${planted} };
          const wc = window.require("@electron/remote").webContents.fromId(b.webview.getWebContentsId());
          try {
            b.plant.clear();
            try { b.setLive(true); } catch (e) {}
            out.landed = await land(PAGE, 30000);
            // The page's chunks in the store and placeable (vectorised).
            let cids = [];
            for (let i = 0; i < 80; i++) {
              cids = await v.sidecar.pageCids(PAGE).catch(() => []);
              if (cids.length >= 3) { const got = await v.sidecar.place(cids.slice(0, 3)); if (got && got.nodes && got.nodes.length) break; }
              await sleep(750);
            }
            out.stored = cids.length;
            if (cids.length < 3) return { ...out, error: "the page never reached the store" };
            // From the top: a check before this one may leave the page scrolled.
            await b.webview.executeJavaScript("window.scrollTo(0,0); 1"); await sleep(400);
            // A point over a chunk the browser can resolve to a stored cid.
            const pts = JSON.parse(await b.webview.executeJavaScript("(function(){var h=window.__domvecSensor;var vw=innerWidth,vh=innerHeight,a=[];for(var y=30;y<vh;y+=40)for(var x=30;x<vw;x+=60){var st=document.elementsFromPoint(x,y),bb=null,ba=Infinity;for(var i=0;i<st.length&&i<12;i++){var c=null;try{c=h.at(st[i]);}catch(e){}if(c&&c.box){var ar=c.box[2]*c.box[3];if(ar>0&&ar<ba){ba=ar;bb=c;}}}if(bb)a.push({x:x,y:y,id:bb.id,frac:ba/(vw*vh)});}return JSON.stringify(a);})()"));
            // The planted arm hovers the CLEAN arm's point: the same chunk, so a
            // difference is the plant's and not the pick's.
            let pick = ${JSON.stringify(given || null)};
            // The browser's chunk map loads a moment after the page does:
            // resolution is retried for up to 20 s, not judged on first sight.
            for (let tries = 0; !pick && tries < 40; tries++) {
              for (const p of pts) { const st = b.storedCidFor("f:" + b.session + "#" + p.id, b.session); if (st) { pick = { ...p, stored: st }; break; } }
              if (!pick) await sleep(500);
            }
            if (!pick) return { ...out, error: "no hovered chunk resolves to a stored chunk", points: pts.length };
            out.pick = pick;
            v.plantNoFocus = ${planted};
            const f0 = { ...v.focusStats }, n0 = v.billboardLog.length;
            wc.sendInputEvent({ type: "mouseMove", x: pick.x, y: pick.y });
            await sleep(40);
            wc.sendInputEvent({ type: "mouseMove", x: pick.x + 2, y: pick.y + 1 });
            await sleep(1600);
            const rect = b.pipebox.hover && b.pipebox.hover.rect;
            const vp = JSON.parse(await b.webview.executeJavaScript("JSON.stringify([innerWidth, innerHeight])"));
            out.outline = rect || null;
            out.outline_frac = rect ? Math.round(rect.w * rect.h / (vp[0] * vp[1]) * 1000) / 1000 : null;
            out.flown = v.focusStats.flown - f0.flown;
            out.flew_to = v.focusStats.last;
            const e = v.billboards.get(pick.stored);
            // Text where the reader sees it: the body, its shadow roots, and the
            // page form's frame (innerText does not reach into an iframe).
            const textOf = (el) => {
              if (!el) return 0;
              let n = (el.innerText || "").trim().length;
              el.querySelectorAll("*").forEach((x) => {
                if (x.shadowRoot) n += (x.shadowRoot.textContent || "").trim().length;
                if (x.tagName === "IFRAME") { try { n += ((x.contentDocument && x.contentDocument.body && x.contentDocument.body.innerText) || "").trim().length; } catch (z) {} }
              });
              return n;
            };
            out.panel = e ? { from_hover: !!e.fromHover, form: e.form, first_paint_ms: e.firstPaintMs ?? null,
                              text: textOf(e.el.querySelector(".domvec-bb-body")) } : null;
            out.log = v.billboardLog.slice(n0);
            // The pointer leaves the page the way a mouse does: moves past its
            // edge, then the window's leave.
            wc.sendInputEvent({ type: "mouseMove", x: -8, y: -8 });
            wc.sendInputEvent({ type: "mouseLeave", x: -8, y: -8 });
            const tLeave = performance.now();
            let closed = false;
            while (performance.now() - tLeave < 1500) { if (!v.billboards.has(pick.stored)) { closed = true; break; } await sleep(25); }
            out.closed_after_leave = closed;
            out.close_ms = closed ? Math.round(performance.now() - tLeave) : null;
            return out;
          } finally {
            v.plantNoFocus = false;
            for (const [id, e] of [...v.billboards.entries()]) if (e.fromHover) v.closeBillboard(id);
          }
        })()`, { timeout: 180000 });
        const clean = await arm(false);
        const planted = await arm(true, clean && clean.pick ? clean.pick : null);
        const works = (x) => !x.error && x.flown >= 1 && x.flew_to === x.pick.stored && !!x.panel
          && x.panel.from_hover && x.panel.text > 0 && (x.panel.first_paint_ms ?? 1e9) <= 500
          && x.outline_frac !== null && x.outline_frac < 1;
        // Closing on leave was REPLACED by G-125 (2026-10-10: "showing hovered panels ...
        // should persist, but disappear after a minute maybe"): the panel outlives the
        // hover, and G-125's check holds that. `closed_after_leave` stays as evidence.
        return {
          pass: works(clean) && !planted.error && planted.flown === 0 && !planted.panel,
          evidence: { clean, planted,
                      bar: "clean: the camera flew to the hovered chunk's stored node, its panel opened from the hover with text within 500 ms, the outline is smaller than the viewport (the panel then PERSISTS after leave, per G-125, which replaced close-on-leave); planted (plantNoFocus): no flight, no panel" },
        };
      },
    },
    // ---- 2026-10-10: the reader's day of practice (PLUGIN_GOAL 30-58) ------
    //
    // One fixture page, `practice_rows.html`: a forum-style table (cells the
    // page's chunking splits, rows the store keeps), a mostly hidden menu, a
    // picture drawn 700x200 and cropped to cover, and prose. Every check
    // drives the real app with real pointer input and reads the app's own
    // state; each has a planted arm that must fail it, or names the
    // precondition that makes it able to.
    {
      id: "G-122",
      asks: "the overlay outlines the STORED chunk -- one forum row is one card and one outline, though the page's own chunking cuts it into cells; planted (plantPageUnit): the cell",
      async run() {
        const fixtures = await serveFixtures();
        const page = fixtures.origin + "/practice_rows.html";
        try {
          const arm = (planted) => evaluate(`(async () => {
            ${PREP}
            const PAGE = ${JSON.stringify(page)};
            const wc = window.require("@electron/remote").webContents.fromId(b.webview.getWebContentsId());
            b.pipebox.plantPageUnit = ${planted};
            try {
              try { b.setLive(true); } catch (e) {}
              const landed = await land(PAGE, 30000);
              for (let i = 0; i < 90 && !(b.pipebox.map.url === PAGE && b.pipebox.map.chunks > 0); i++) await sleep(500);
              await b.webview.executeJavaScript("document.querySelectorAll('tbody tr')[1].scrollIntoView({block:'center'}); 1");
              await sleep(700);
              const geo = JSON.parse(await b.webview.executeJavaScript("(function(){var r=document.querySelectorAll('tbody tr')[1];var c=r.querySelectorAll('td')[2];var rb=r.getBoundingClientRect(),cb=c.getBoundingClientRect();return JSON.stringify({row_w:rb.width,cx:cb.x+cb.width/2,cy:cb.y+cb.height/2,cell_w:cb.width});})()"));
              // Off the page first: the sensor pushes only when the chunk under
              // the pointer CHANGES, so an arm hovering the point the last arm
              // left the pointer on read that arm's outline (2026-10-10).
              wc.sendInputEvent({ type: "mouseMove", x: -8, y: -8 });
              wc.sendInputEvent({ type: "mouseLeave", x: -8, y: -8 });
              await sleep(400);
              b.pipebox.hover = null;
              wc.sendInputEvent({ type: "mouseMove", x: Math.round(geo.cx), y: Math.round(geo.cy) });
              await sleep(40);
              wc.sendInputEvent({ type: "mouseMove", x: Math.round(geo.cx) + 1, y: Math.round(geo.cy) });
              let h = null;
              for (let i = 0; i < 25; i++) { await sleep(100); h = b.pipebox.hover; if (h && h.rect && (${planted} || h.stored)) break; }
              await sleep(300);
              h = b.pipebox.hover;
              return { planted: ${planted}, landed, map_chunks: b.pipebox.map.chunks, row_w: Math.round(geo.row_w), cell_w: Math.round(geo.cell_w),
                       outline_w: h && h.rect ? Math.round(h.rect.w) : null, stored: h ? (h.stored || null) : null,
                       stored_unit_ms: b.pipebox.storedUnitMs.slice(-3).map(Math.round) };
            } finally { b.pipebox.plantPageUnit = false; }
          })()`, { timeout: 120000 });
          const clean = await arm(false);
          const planted = await arm(true);
          const unit = (x) => x.outline_w !== null && x.outline_w >= 0.8 * x.row_w;
          return { pass: unit(clean) && !!clean.stored && !unit(planted),
                   evidence: { clean, planted, purged: await tidyFixtures(fixtures.origin),
                               bar: "clean: the outline is >= 0.8 of the row's width and names a stored chunk; planted: the cell" } };
        } finally { await fixtures.close(); }
      },
    },
    {
      id: "G-123",
      asks: "a scanned chunk's page form is SAVED and renders with its page gone -- no 'unavailable' banner anywhere; planted (plantNoSaved): nothing kept from the scan, so no page form",
      async run() {
        const fixtures = await serveFixtures();
        const page = fixtures.origin + "/practice_rows.html";
        try {
          const arm = (planted) => evaluate(`(async () => {
            ${PREP}
            const PAGE = ${JSON.stringify(page)};
            const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
            const SIDE = ${JSON.stringify(SIDECAR)};
            v.plantNoSaved = ${planted};
            try {
              try { b.setLive(true); } catch (e) {}
              await land(PAGE, 30000);
              let cov = null;
              for (let i = 0; i < 90; i++) {
                cov = await (await fetch(SIDE + "/snapshot_coverage?url=" + encodeURIComponent(PAGE))).json().catch(() => null);
                if (cov && cov.chunks > 0 && cov.saved >= cov.chunks) break;
                await sleep(1000);
              }
              const cids = await v.sidecar.pageCids(PAGE);
              let pick = null;
              for (const c of cids) { const p = await v.chunkPayload(c); const md = p && p.lines ? p.lines.map((l) => l.text).join(" ") : ""; if (/Monarch butterflies/.test(md)) { pick = c; break; } }
              if (!pick) return { planted: ${planted}, error: "no stored prose chunk", cov, stored: cids.length };
              // Placeable FIRST, while the page is still open: embedding is
              // asynchronous, and a fresh store's chunk had no vector yet the
              // moment its form was saved (2026-10-11: "not placeable").
              let n = v.graph.graphData().nodes.find((x) => x.id === pick);
              for (let i = 0; !n && i < 60; i++) {
                const got = await v.sidecar.place([pick]).catch(() => null);
                if (got && got.nodes && got.nodes.length) v.absorb(got.nodes, got.edges);
                n = v.graph.graphData().nodes.find((x) => x.id === pick);
                if (!n) await sleep(1000);
              }
              if (!n) return { planted: ${planted}, error: "not placeable in 60 s", cov };
              b.go("about:blank");
              await sleep(1500);
              for (const bb of v.billboardState()) v.closeBillboard(bb.id);
              await v.openBillboard(n);
              await sleep(3500);
              const e = v.billboards.get(pick);
              const f = e && e.el.querySelector("iframe.domvec-snapshot");
              const text = f && f.contentDocument ? (f.contentDocument.body.innerText || "") : "";
              const out = { planted: ${planted}, cov, form: e ? e.form : null, saved_form: !!(e && e.savedForm),
                            page_text_has: /Monarch butterflies/.test(text),
                            banners: document.querySelectorAll(".domvec-bb-note").length };
              v.closeBillboard(pick);
              return out;
            } finally { v.plantNoSaved = false; }
          })()`, { timeout: 200000 });
          const clean = await arm(false);
          const planted = await arm(true);
          return { pass: !clean.error && clean.cov && clean.cov.saved >= clean.cov.chunks && clean.form === "page" && clean.saved_form
                         && clean.page_text_has && clean.banners === 0 && planted.form !== "page" && planted.banners === 0,
                   evidence: { clean, planted, purged: await tidyFixtures(fixtures.origin) } };
        } finally { await fixtures.close(); }
      },
    },
    {
      id: "G-130",
      asks: "both panel forms are COMPLETE and match: a mostly hidden menu's page form shows every item the chunk holds (what the page drew, then what it did not); planted (plantNoComplement): only what the page drew",
      async run() {
        const fixtures = await serveFixtures();
        const page = fixtures.origin + "/practice_rows.html";
        try {
          const arm = (planted) => evaluate(`(async () => {
            ${PREP}
            const PAGE = ${JSON.stringify(page)};
            const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
            v.plantNoComplement = ${planted};
            try {
              try { b.setLive(true); } catch (e) {}
              await land(PAGE, 30000);
              for (let i = 0; i < 90 && !(b.pipebox.map.url === PAGE && b.pipebox.map.chunks > 0); i++) await sleep(500);
              const cids = await v.sidecar.pageCids(PAGE);
              let pick = null;
              for (const c of cids) { const p = await v.chunkPayload(c); const md = p && p.lines ? p.lines.map((l) => l.text).join(" ") : ""; if (/Aardvark/.test(md) && /Tapir/.test(md)) { pick = c; break; } }
              if (!pick) return { planted: ${planted}, error: "the hidden menu is not one stored chunk", stored: cids.length };
              for (const bb of v.billboardState()) v.closeBillboard(bb.id);
              let n = v.graph.graphData().nodes.find((x) => x.id === pick);
              if (!n) { const got = await v.sidecar.place([pick]); if (got && got.nodes) v.absorb(got.nodes, got.edges); n = v.graph.graphData().nodes.find((x) => x.id === pick); }
              if (!n) return { planted: ${planted}, error: "not placeable" };
              await v.openBillboard(n);
              await sleep(3000);
              const e = v.billboards.get(pick);
              if (e && e.form !== "page") await v.switchForm(e, "page");
              await sleep(1500);
              const f = e && e.el.querySelector("iframe.domvec-snapshot");
              const text = f && f.contentDocument ? (f.contentDocument.body.innerText || "") : "";
              const items = ["Aardvark", "Cassowary", "Hedgehog", "Pangolin", "Tapir"];
              const out = { planted: ${planted}, form: e ? e.form : null, items_shown: items.filter((w) => text.includes(w)).length, of: items.length,
                            complemented: e ? (e.complemented || 0) : 0, banners: document.querySelectorAll(".domvec-bb-note, .is-unavailable").length };
              v.closeBillboard(pick);
              return out;
            } finally { v.plantNoComplement = false; }
          })()`, { timeout: 150000 });
          const clean = await arm(false);
          const planted = await arm(true);
          return { pass: !clean.error && clean.form === "page" && clean.items_shown === clean.of && clean.banners === 0
                         && planted.items_shown < planted.of,
                   evidence: { clean, planted, purged: await tidyFixtures(fixtures.origin) } };
        } finally { await fixtures.close(); }
      },
    },
    {
      id: "G-129",
      asks: "the GLOBAL fit refits while the app is latent once the corpus has grown since the fit -- and not without the growth (null arm: latent, no growth, no refit)",
      async run() {
        const fixtures = await serveFixtures();
        try {
          const got = await evaluate(`(async () => {
            ${PREP}
            const base = b.sidecar.base().trim().replace(/[/]+$/, "");
            const proj = async () => (await (await fetch(base + "/projector")).json());
            try { b.setLive(true); } catch (e) {}
            // A fit to start from.
            let p0 = await proj();
            for (let i = 0; i < 120 && !(p0.fitted && !p0.fitting); i++) { await sleep(1000); p0 = await proj(); }
            if (!p0.fitted) return { error: "no fit", p0 };
            // NULL ARM: latent past the window with no growth -- no refit.
            await land("about:blank", 5000);
            await sleep((p0.latent_window_s || 20) * 1000 + 8000);
            const p1 = await proj();
            // GROWTH: distinct busy pages until the corpus passes the latent target.
            const target = p1.latent_refit_at || Math.ceil(1.25 * p1.fitted_chunks);
            const t0 = performance.now();
            let k = 0, pg = p1;
            while (pg.chunks_now < target && performance.now() - t0 < 120000) {
              const url = ${JSON.stringify(fixtures.origin)} + "/busy_feed.html?every=40&rounds=120&words=60&g129=" + (k++) + "-" + Date.now();
              await land(url, 20000);
              await sleep(7000);
              pg = await proj();
            }
            const grown = pg.chunks_now;
            // LATENT again: nothing streams.
            await land("about:blank", 5000);
            const refitsBefore = pg.latent_refits, epochBefore = pg.epoch;
            let p2 = pg;
            for (let i = 0; i < 90; i++) { await sleep(2000); p2 = await proj(); if (p2.latent_refits > refitsBefore && !p2.fitting) break; }
            return { fitted_chunks: p1.fitted_chunks, target, grown, pages_landed: k,
                     null_arm: { refits_before: p0.latent_refits, refits_after: p1.latent_refits, epoch_same: p1.epoch === p0.epoch },
                     latent: { refits: p2.latent_refits - refitsBefore, epoch_moved: p2.epoch !== epochBefore, fitted_after: p2.fitted_chunks } };
          })()`, { timeout: 400000 });
          const ok = got && !got.error && got.grown >= got.target
            && got.null_arm.refits_after === got.null_arm.refits_before && got.null_arm.epoch_same
            && got.latent.refits >= 1 && got.latent.epoch_moved;
          return { pass: !!ok, evidence: { ...got, purged: await tidyFixtures(fixtures.origin) } };
        } finally { await fixtures.close(); }
      },
    },
    {
      id: "G-154",
      asks: "a sidecar that lost its session under an open page refuses the stale delta, the sensor resends everything, and captures resume with addresses the page holds; planted (no-resync): every capture after the loss is refused",
      async run() {
        const fixtures = await serveFixtures();
        try {
          const arm = (planted) => evaluate(`(async () => {
            ${PREP}
            const URL = ${JSON.stringify(fixtures.origin)} + "/busy_feed.html?every=120&rounds=200&g154=" + (${planted} ? "p" : "c") + Date.now();
            if (${planted}) b.plant.add("no-resync");
            try {
              try { b.setLive(true); } catch (e) {}
              await land(URL, 30000);
              // A first capture, so the sidecar holds a session and the sensor's dictionary.
              for (let i = 0; i < 80 && !b.capturedAt.has(URL); i++) await sleep(250);
              if (!b.capturedAt.has(URL)) return { planted: ${planted}, error: "no first capture" };
              const resyncs0 = b.resyncs;
              // What a sidecar restart does to the session: gone. (The route's own
              // restart flag; an empty payload, so nothing is written.)
              await b.sidecar.capture(URL, { restart: true, payload: { v: 0, url: URL, dict: [], shapes: [], chunks: [], moves: [], removed: [], settled: false, stats: { dictSize: 0 } } });
              const lostWall = Date.now();
              await sleep(9000);
              // Captures the SIDECAR stored after the loss (the plugin stamps
              // its own clock before it reads the reply, refusals included).
              const prof = await (await fetch(b.sidecar.base().trim().replace(/[/]+$/, "") + "/profile")).json();
              const storedAfter = (prof.capture || []).filter((r) => r.url === URL && r.at * 1000 > lostWall).length;
              const refusedAfter = (prof.capture_refused || []).filter((r) => r.url === URL && r.at * 1000 > lostWall).length;
              const map = await b.sidecar.pageMap(URL);
              const xs = map && map.chunks ? Object.values(map.chunks).flat().slice(0, 300) : [];
              const held = xs.length ? JSON.parse(await b.webview.executeJavaScript("(function(xs){var h=window.__domvecSensor;var n=0;for(var i=0;i<xs.length;i++){try{if(h.node(xs[i]))n++;}catch(e){}}return JSON.stringify(n);})(" + JSON.stringify(xs) + ")")) : 0;
              return { planted: ${planted}, resyncs: b.resyncs - resyncs0, stored_after_loss: storedAfter, refused_after_loss: refusedAfter,
                       stored_addresses: xs.length, page_holds: held };
            } finally { b.plant.delete("no-resync"); }
          })()`, { timeout: 120000 });
          const clean = await arm(false);
          const planted = await arm(true);
          return {
            pass: !clean.error && clean.resyncs >= 1 && clean.refused_after_loss >= 1 && clean.stored_after_loss >= 1
                  && clean.stored_addresses > 0 && clean.page_holds >= 0.9 * clean.stored_addresses
                  && !planted.error && planted.resyncs === 0 && planted.refused_after_loss >= 1 && planted.stored_after_loss === 0,
            evidence: { clean, planted, purged: await tidyFixtures(fixtures.origin) },
          };
        } finally { await fixtures.close(); }
      },
    },
    {
      id: "P-B7",
      asks: "hovering a chunk on the page outlines, besides it, the other chunks it is embedded among (its trie node's parent): each box inside the container's own box on the page, none of them the hovered chunk, all gone when the pointer leaves; planted (plantNoStructure): only the hovered chunk",
      async run() {
        const fixtures = await serveFixtures();
        const page = fixtures.origin + "/shadow_catalogue.html";
        const arm = (planted, given, byId) => evaluate(`(async () => {
          ${PREP}
          const PAGE = ${JSON.stringify(page)};
          const out = { planted: ${planted} };
          const wc = window.require("@electron/remote").webContents.fromId(b.webview.getWebContentsId());
          const pb = b.pipebox;
          try {
            b.plant.clear();
            try { b.setLive(true); } catch (e) {}
            out.landed = await land(PAGE, 30000);
            let cids = [];
            for (let i = 0; i < 80; i++) { cids = await b.sidecar.pageCids(PAGE).catch(() => []); if (cids.length >= 3 && pb.map.url === PAGE && pb.map.chunks >= 3) break; await sleep(750); }
            out.stored = cids.length;
            if (pb.map.url !== PAGE) return { ...out, error: "the browser's chunk map never loaded" };
            // A result card, by its address: the cards are in shadow roots, which
            // elementsFromPoint does not pierce, so a point grid finds only the
            // light-DOM header -- whose chunk spans /html/body, with nothing around it.
            let pick = ${JSON.stringify(given || null)};
            for (let tries = 0; !pick && tries < 40; tries++) {
              const stored = pb.map.cids().find((c) => pb.map.xpaths(c).some((x) => x.includes("result-card[3]")));
              if (stored) {
                const x = pb.map.xpaths(stored)[0];
                const r = JSON.parse(await b.webview.executeJavaScript("(function(x){var n=window.__domvecSensor.node(x);if(n&&n.nodeType===3)n=n.parentElement;if(!n)return 'null';var q=n.getBoundingClientRect();return JSON.stringify({x:q.left+q.width/2,y:q.top+q.height/2});})(" + JSON.stringify(x) + ")"));
                if (r) pick = { x: Math.round(r.x), y: Math.round(r.y), stored };
              }
              if (!pick) await sleep(500);
            }
            if (!pick) return { ...out, error: "no result card in the chunk map" };
            out.pick = pick;
            pb.plantNoStructure = ${planted};
            pb.plantHoverById = ${!!byId};
            wc.sendInputEvent({ type: "mouseMove", x: pick.x, y: pick.y });
            await sleep(40);
            wc.sendInputEvent({ type: "mouseMove", x: pick.x + 2, y: pick.y + 1 });
            await sleep(1800);
            const st = pb.structure;
            const shown = [...b.containerEl.querySelectorAll(".domvec-chunk-struct")].filter((el) => el.style.display !== "none" && el.getBoundingClientRect().width > 0).length;
            out.structure = st ? { stored: st.stored, container: st.container, siblings: st.siblings.length, drawn: st.drawn, ms: st.ms } : null;
            out.shown = shown;
            out.hovered_outline = !!(pb.hover && pb.hover.rect);
            out.hovered_stored = pb.hover ? pb.hover.stored || null : null;
            out.by_address = !!(pb.hover && pb.hover.byAddress);
            if (st && st.container) {
              // The container's OWN box on the page, read independently through
              // the sensor's resolver -- each sibling must be embedded in it.
              const cb = JSON.parse(await b.webview.executeJavaScript("(function(x){var n=window.__domvecSensor.node(x);if(n&&n.nodeType===3)n=n.parentElement;if(!n)return 'null';var q=n.getBoundingClientRect();return JSON.stringify({x:q.left,y:q.top,w:q.width,h:q.height});})(" + JSON.stringify(st.container) + ")"));
              out.container_box = cb;
              const inside = (r) => r && cb && r.x >= cb.x - 2 && r.y >= cb.y - 2 && r.x + r.w <= cb.x + cb.w + 2 && r.y + r.h <= cb.y + cb.h + 2;
              out.inside = st.rects.filter((r) => r && inside(r)).length;
              out.measured = st.rects.filter((r) => r).length;
              out.hovered_among = st.siblings.includes(st.stored);
            }
            wc.sendInputEvent({ type: "mouseMove", x: -8, y: -8 });
            wc.sendInputEvent({ type: "mouseLeave", x: -8, y: -8 });
            await sleep(1200);
            out.shown_after_leave = [...b.containerEl.querySelectorAll(".domvec-chunk-struct")].filter((el) => el.style.display !== "none").length;
            return out;
          } finally { pb.plantNoStructure = false; pb.plantHoverById = false; }
        })()`, { timeout: 180000 });
        try {
          const clean = await arm(false);
          const planted = await arm(true, clean && clean.pick ? clean.pick : null);
          // The hover's own resolution, planted back to the in-page id alone.
          const byId = await arm(false, clean && clean.pick ? clean.pick : null, true);
          return {
            pass: !clean.error && clean.hovered_stored === clean.pick.stored && clean.by_address
                  && clean.structure && clean.structure.drawn >= 1 && clean.shown === clean.structure.drawn
                  && clean.measured >= 1 && clean.inside === clean.measured && clean.hovered_among === false
                  && clean.hovered_outline && clean.shown_after_leave === 0
                  && !planted.error && planted.shown === 0 && planted.hovered_outline
                  && !byId.error && byId.hovered_stored !== clean.pick.stored,
            evidence: { clean, planted, by_id: byId, purged: await tidyFixtures(fixtures.origin) },
          };
        } finally { await fixtures.close(); }
      },
    },
    {
      id: "R-3",
      asks: "typing `[query]()` in a note opens ranked results in a block UNDER the line: the line below moves down by the block's height and is not covered (R-2/R-3), scrolling to the bottom fetches more (G-69), and clicking a result infills its link between the parentheses (R-4); planted (plantOverlay): the floating shape, the line below does not move and is covered",
      async run() {
        const arm = (planted) => evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const pl = app.plugins.getPlugin("domvec-bridge");
          const g = pl.gesture;
          const path = "domvec-checks/R-gesture-" + Date.now() + ".md";
          if (!app.vault.getAbstractFileByPath("domvec-checks")) await app.vault.createFolder("domvec-checks");
          const file = await app.vault.create(path, "first line of the note\\n[patricia trie]()\\nthe line below the gesture\\nand one more");
          const leaf = app.workspace.getLeaf("tab");
          g.plantOverlay = ${planted};
          try {
            await leaf.openFile(file, { state: { mode: "source" } });
            await sleep(800);
            const cm = leaf.view.editor.cm;
            const below = () => cm.coordsAtPos(cm.state.doc.line(3).from);
            const top0 = below().top;
            const s0 = { ...g.stats };
            cm.focus();
            cm.dispatch({ selection: { anchor: cm.state.doc.line(2).to - 1 } });
            let hits = [];
            // Up to 60 s: after a plugin reload the sidecar is busy answering
            // the projector and the first search waits behind it (20 s+).
            for (let i = 0; i < 240; i++) { await sleep(250); hits = cm.dom.querySelectorAll(".domvec-linkgesture .domvec-lg-hit"); if (hits.length) break; }
            await sleep(300);
            const box = cm.dom.querySelector(".domvec-linkgesture");
            if (!box || !hits.length) return { planted: ${planted}, error: "no results", box: !!box, stats: g.stats };
            const r = box.getBoundingClientRect();
            const b1 = below();
            const lineRect = { top: b1.top, bottom: b1.bottom };
            const covered = r.bottom > lineRect.top + 1 && r.top < lineRect.bottom - 1;
            // More on scroll (G-69's paging, through this one interface).
            const list = box.querySelector(".domvec-lg-list");
            const n0 = hits.length, p0 = g.stats.pages;
            list.scrollTop = list.scrollHeight;
            list.dispatchEvent(new Event("scroll"));
            for (let i = 0; i < 160 && g.stats.pages === p0; i++) await sleep(250);
            await sleep(200);
            const n1 = box.querySelectorAll(".domvec-lg-hit").length;
            // Read BEFORE the click: an infill closes the block, and a detached
            // list has no height (the first run read "not scrollable" so).
            const scrollable = list.scrollHeight > list.clientHeight + 4;
            // Infill: click the first result.
            const first = box.querySelector(".domvec-lg-hit");
            const cid = first.dataset.cid;
            first.click();
            await sleep(300);
            const line2 = cm.state.doc.line(2).text;
            return { planted: ${planted}, query: s0.last && s0.last.query, results: n0, after_scroll: n1,
                     scrollable,
                     block_height: Math.round(r.height), moved_by: Math.round(lineRect.top - top0), covered,
                     line2, infilled: g.stats.infilled - s0.infilled, link: (g.stats.last || {}).dest || "",
                     closed: !cm.dom.querySelector(".domvec-linkgesture") };
          } finally {
            g.plantOverlay = false;
            // Save, close, THEN trash: the infill edited the note, and the
            // editor's save landing after the trash wrote it back -- eight
            // check notes were left in the vault that way (2026-10-11).
            try { await leaf.view.save(); } catch (e) {}
            leaf.detach();
            await sleep(2500);
            const f = app.vault.getAbstractFileByPath(path);
            if (f) await app.vault.trash(f, true);
            const dir = app.vault.getAbstractFileByPath("domvec-checks");
            if (dir && dir.children && dir.children.length === 0) await app.vault.trash(dir, true);
          }
        })()`, { timeout: 90000 });
        const clean = await arm(false);
        const planted = await arm(true);
        const ok = (x) => x && !x.error;
        return {
          pass: ok(clean) && clean.results > 0 && clean.scrollable && clean.after_scroll > clean.results
                && !clean.covered && clean.moved_by >= 0.9 * clean.block_height
                && clean.infilled === 1 && clean.link && clean.line2 === "[patricia trie](" + clean.link + ")" && clean.closed
                && ok(planted) && planted.covered && planted.moved_by < 0.25 * planted.block_height,
          evidence: { clean, planted },
        };
      },
    },
    {
      id: "G-62",
      asks: "with the cell offline (Chromium's own network emulation), a stored page that was never saved fails to load and opens rebuilt from the scan trace, as a local scrollable file; null arm: a url the store never traced opens nothing",
      async run() {
        const got = await offlineArm("traced");
        // And offline ENDS when the reader goes to a live page by any route, not
        // only the button (2026-10-11: a cell left "offline" docked and pinned
        // every hover panel after, so none ever expired -- found by G-125).
        // Planted (plantStickyOffline): only the button ends it.
        const fixtures = await serveFixtures();
        try {
          const leave = (planted) => evaluate(`(async () => {
            ${PREP}
            b.plantStickyOffline = ${planted};
            try {
              b.offlineFor = ${JSON.stringify(OKAPI)};
              const ok = await land(${JSON.stringify(fixtures.origin + "/shadow_catalogue.html")}, 30000);
              return { planted: ${planted}, landed: ok, offline_after: b.offlineFor };
            } finally { b.plantStickyOffline = false; b.offlineFor = ""; }
          })()`, { timeout: 60000 });
          const left = { clean: await leave(false), planted: await leave(true) };
          got.evidence = { ...got.evidence, leaving: left };
          got.pass = got.pass && left.clean.landed && left.clean.offline_after === "" && left.planted.offline_after !== "";
          return got;
        } finally { await fixtures.close(); }
      },
    },
    {
      id: "G-61",
      asks: "offline, a saved page holding too little of its trace opens INFILLED: its own saved layout kept AND the traced chunks it lacked drawn into it; the traced page (G-62) has neither",
      async run() { return offlineArm("infilled"); },
    },
    {
      id: "G-59",
      asks: "offline, a chunk's panel is docked into a main Obsidian pane, the same billboard element; planted (plantOfflineBillboard): it stays in the projector",
      async run() { return offlineArm("dock"); },
    },
    {
      id: "G-95",
      asks: "clicking a page root toggles its whole tree: the first click draws every stored chunk of the page, the second folds them all back; planted (plantUnfoldOnClick): the step-wise unfold, which never collapses",
      async run() {
        // Addendum IX: "When the roots are clicked, all nodes expand ... When
        // the roots that are uncollapsed are clicked again, all the chunks for
        // that page collapse back."
        const arm = (planted) => evaluate(`(async () => {
          ${PREP}
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
          for (let i = 0; i < 60 && !(v.graph && v.graph.graphData().nodes.length > 50); i++) await sleep(500);
          if (v.level === "chunk") return { error: "in chunk view" };
          const g = v.graph;
          const drawnOf = (u) => g.graphData().nodes.filter((n) => n.url === u && n.level !== "page" && !n.force).length;
          // A page with a moderate stored set, nothing of it drawn yet.
          let page = null, stored = 0;
          for (const n of g.graphData().nodes) {
            if (n.level !== "page" || !n.url || drawnOf(n.url)) continue;
            const k = (await v.sidecar.pageCids(n.url).catch(() => [])).length;
            if (k >= 20 && k <= 150) { page = n; stored = k; break; }
          }
          if (!page) return { error: "no page with 20-150 stored chunks" };
          const click = g.onNodeClick();
          v.plantUnfoldOnClick = ${planted};
          const scoped = v.onScope, revealed = v.onReveal;
          v.onScope = () => {}; v.onReveal = () => {};      // the browser cell is not driven by this check
          try {
            click(page, new MouseEvent("click"));
            let first = 0; for (let i = 0; i < 40; i++) { await sleep(250); first = drawnOf(page.url); if (first && i > 8) break; }
            click(page, new MouseEvent("click"));
            let second = first; for (let i = 0; i < 40; i++) { await sleep(250); second = drawnOf(page.url); if (second === 0) break; }
            return { planted: ${planted}, url: page.url.slice(0, 60), stored, first, second };
          } finally {
            v.plantUnfoldOnClick = false; v.onScope = scoped; v.onReveal = revealed;
            if (drawnOf(page.url)) await v.togglePage(page);
          }
        })()`, { timeout: 90000 });
        const clean = await arm(false), planted = await arm(true);
        return { pass: !clean.error && clean.first >= 0.8 * clean.stored && clean.second === 0
                       && !planted.error && planted.second > 0,
                 evidence: { clean, planted } };
      },
    },
    {
      id: "G-185",
      asks: "the idle turn (camera orbit and hue) runs with a query standing too -- the search's lights ride on the turning scene; planted (plantDriftStopsOnSearch): a standing query stops it, as it did",
      async run() {
        // 2026-10-11/12: "pls dont forget about the rotating xyzhsv"; "also
        // not sure if I'm seeing the xyzhsv rotations taking effect yet" --
        // measured then: 0 starts since the reload, a query standing.
        const arm = (planted) => evaluate(`(async () => {
          ${PREP}
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
          for (let i = 0; i < 60 && !(v.graph && v.batch && v.searchField); i++) await sleep(500);
          const f = v.searchField, g = v.graph;
          const stamp0 = window.__domvecReaderAt, after0 = v.idleDriftAfterMs;
          const was = v.onWebSearch; v.onWebSearch = () => {};
          const az = () => { const c = g.camera().position, t = g.controls().target; return Math.atan2(c.z - t.z, c.x - t.x); };
          const turn = (a, b) => { let d = b - a; while (d > Math.PI) d -= 2 * Math.PI; while (d < -Math.PI) d += 2 * Math.PI; return d; };
          const mine = [Date.now() - 60000];
          v.plantDriftStopsOnSearch = ${planted}; v.driftInCheck = true; v.idleDriftAfterMs = 3000;
          try {
            f.input.value = "wikipedia history"; await f.run();
            await sleep(400);
            const standing = !!v.searchState;
            window.__domvecReaderAt = mine[0];
            await sleep(400);
            const a0 = az(), h0 = v.batch.hue;
            await sleep(2500);
            return { planted: ${planted}, standing, turned: turn(a0, az()), hue_moved: v.batch.hue !== h0, active: v.driftStats.active,
                     lights: v.searchStats.lights };
          } finally {
            v.plantDriftStopsOnSearch = false; v.driftInCheck = false; v.idleDriftAfterMs = after0;
            if (mine.includes(window.__domvecReaderAt)) window.__domvecReaderAt = stamp0;
            v.onWebSearch = was; f.input.value = ""; await f.run();
          }
        })()`, { timeout: 60000 });
        const clean = await arm(false), planted = await arm(true);
        return { pass: clean.standing && clean.active && Math.abs(clean.turned) > 0.02 && clean.hue_moved
                       && planted.standing && !planted.active && Math.abs(planted.turned) < 0.005,
                 evidence: { clean, planted } };
      },
    },
    {
      id: "G-156",
      asks: "with no reader activity the scene turns -- the camera orbits its target and the colours turn about the grey axis -- drawn only (no node's colour or layout written); the reader acting stops the turn and the colours ease back to the fit's own; planted (plantNoDrift): nothing turns",
      async run() {
        // 2026-10-11, PLUGIN_GOAL 83: "a latent feature that rotates both
        // cartesian and color coordinates slowly but noticeably whenever there
        // is no user activity".
        const arm = (planted) => evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          await window.__domvec.act("open", "graph");
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
          for (let i = 0; i < 60 && !(v.graph && v.batch); i++) await sleep(500);
          const stamp0 = window.__domvecReaderAt;
          const after0 = v.idleDriftAfterMs;
          v.plantNoDrift = ${planted}; v.driftInCheck = true; v.idleDriftAfterMs = 3000;
          const g = v.graph;
          const az = () => { const c = g.camera().position, t = g.controls().target; return Math.atan2(c.z - t.z, c.x - t.x); };
          const turn = (a, b) => { let d = b - a; while (d > Math.PI) d -= 2 * Math.PI; while (d < -Math.PI) d += 2 * Math.PI; return d; };
          const colours = () => g.graphData().nodes.slice(0, 400).map((n) => n.color).join("|");
          const dist = () => { const c = g.camera().position, t = g.controls().target; return Math.hypot(c.x - t.x, c.y - t.y, c.z - t.z); };
          const mine = [Date.now() - 60000];
          try {
            window.__domvecReaderAt = mine[0];
            await sleep(500);
            const a0 = az(), c0 = colours(), d0 = dist();
            await sleep(3000);
            const idle = { turned: turn(a0, az()), hue: v.batch.hue, active: v.driftStats.active,
                           glass_hue: v.batch.glass.mesh.material.uniforms.uHue.value,
                           colours_written: colours() !== c0, distance_kept: Math.abs(dist() - d0) < 0.01 * d0 };
            mine.push(Date.now()); window.__domvecReaderAt = mine[1];   // the reader acts
            await sleep(200);
            const a1 = az();
            await sleep(1500);
            const acted = { turned: turn(a1, az()), hue: v.batch.hue, active: v.driftStats.active };
            return { planted: ${planted}, idle, acted };
          } finally {
            v.plantNoDrift = false; v.driftInCheck = false; v.idleDriftAfterMs = after0;
            // Put back only a stamp this check wrote: a real input meanwhile stays.
            if (mine.includes(window.__domvecReaderAt)) window.__domvecReaderAt = stamp0;
          }
        })()`, { timeout: 60000 });
        const clean = await arm(false), planted = await arm(true);
        const c = clean;
        return { pass: c.idle.active && Math.abs(c.idle.turned) > 0.1 && c.idle.hue > 0.08 && !c.idle.colours_written && c.idle.distance_kept && c.idle.glass_hue === c.idle.hue
                       && !c.acted.active && Math.abs(c.acted.turned) < 0.005 && c.acted.hue === 0
                       && !planted.idle.active && Math.abs(planted.idle.turned) < 0.005 && planted.idle.hue === 0,
                 evidence: { clean, planted } };
      },
    },
    {
      id: "G-166",
      asks: "with no search, every node is the same glowing glass (G-166, G-168): a plain node an orb in its own colour, a streaming node a dimmer orb, a REVEALED picture the picture alone (no orb over it) -- no non-picture node keeps the old material; planted (plantOpaqueOrbs): the old opaque spheres",
      async run() {
        // 2026-10-11: "lets standardize the latent glowing glass orbs as the
        // default, with the light sources adjusting per the query scroll window".
        const arm = (planted) => evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          await window.__domvec.act("open", "graph");
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
          for (let i = 0; i < 60 && !(v.graph && v.batch); i++) await sleep(500);
          if (v.searchField) { v.searchField.input.value = ""; await v.searchField.run(); }
          v.plantOpaqueOrbs = ${planted};
          try {
            await sleep(300); v.batchSync();
            const rs = v.graph.nodeRelSize(), d = v.graph.graphData();
            let plain = 0, orbs = 0, own = 0, pictures = 0, pictureGlass = 0, pictureOrbs = 0, streaming = 0, streamOrbs = 0, oldMaterial = 0;
            for (const n of d.nodes) {
              const base = v.baseLook(n, rs, v.drawnMedia), l = v.lookOf(n, rs, v.drawnMedia);
              if (n.hovered) continue;
              // Item 99: no node keeps the old material -- a picture is held in
              // an orb, a streaming node is a dimmer orb.
              if (base.picture) { pictures++; if (l.glass) pictureGlass++; if (l.orb !== undefined) pictureOrbs++; continue; }
              if (!l.glass) oldMaterial++;
              if (base.translucent) { streaming++; if (l.glass && l.alpha > 0 && l.alpha < 1) streamOrbs++; continue; }
              plain++;
              if (l.glass && l.alpha >= 1) { orbs++; if (l.color === base.color) own++; }
            }
            return { planted: ${planted}, plain, orbs, own_colour: own, pictures, picture_glass: pictureGlass, picture_orbs: pictureOrbs,
                     streaming, stream_orbs: streamOrbs, old_material: oldMaterial, batch: { ...v.batch.lastStats } };
          } finally { v.plantOpaqueOrbs = false; v.batchSync(); }
        })()`, { timeout: 60000 });
        const clean = await arm(false), planted = await arm(true);
        return { pass: clean.plain > 0 && clean.orbs === clean.plain && clean.own_colour === clean.plain && clean.picture_glass === 0
                       && clean.picture_orbs === 0 && clean.stream_orbs === clean.streaming && clean.old_material === 0
                       && clean.batch.glass >= clean.plain && clean.batch.spheres <= 1 && planted.orbs === 0 && planted.old_material > 0,
                 evidence: { clean, planted } };
      },
    },
    {
      id: "G-157",
      asks: "the naked search field on the 3D panel: typing a query shows 'showing k/n results' with k an editable top-k, a horizontal scroll from the very left governs how many results are drawn; while searching ONLY those are drawn as themselves, every other node is a colourless lens lit by the shown results' point lights, brightest at the scrolled index; the top result is flown to and its panel opened; the slider is SOFT (at s=1.5 the second result is a half-coloured orb); cleared, every node is its own glowing orb again; planted (plantNoGlass, plantNoTopFlight): no lens, no lights, no flight",
      async run() {
        // 2026-10-11, PLUGIN_GOAL 84/86/87/88.
        const arm = (planted) => evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          await window.__domvec.act("open", "graph");
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
          for (let i = 0; i < 60 && !(v.graph && v.searchField); i++) await sleep(500);
          const f = v.searchField;
          if (!f) return { error: "no search field" };
          // In CHUNK view: every result is its own drawn node there. In the url
          // view a closed page's chunks are not drawn, so its results light the
          // page node once (G-167) -- not what this check asks.
          const unit = [...v.containerEl.querySelectorAll(".domvec-graph-bar button")].find((b) => /^(pages|chunks)$/.test(b.textContent.trim()));
          const startLevel = v.level;
          const settle = async () => { let last = -1; for (let i = 0; i < 90; i++) { await sleep(500); const c = v.graph ? v.graph.graphData().nodes.length : 0; if (c && c === last) break; last = c; } };
          if (v.level !== "chunk" && unit) {
            unit.click();
            // Chunk view has ARRIVED: UMAP-only and its whole node set drawn, not
            // merely a count that held still while the old graph was up.
            for (let i = 0; i < 240 && !(v.level === "chunk" && v.umapOnly && v.graph && v.graph.graphData().nodes.length > 2000); i++) await sleep(500);
            await settle();
          }
          v.plantNoGlass = ${planted}; v.plantNoTopFlight = ${planted};
          // The web half (G-158) stays out of this check: it would take the browser cell.
          const bv = app.workspace.getLeavesOfType("domvec-browser-view")[0]?.view;
          if (bv) bv.plantNoWebSearch = true;
          const flown0 = v.searchStats.flown_top;
          try {
            const box = f.el.getBoundingClientRect(), cv = v.canvasEl.getBoundingClientRect();
            const placement = { centre_off: Math.round((box.left + box.width / 2) - (cv.left + cv.width / 2)),
                                bottom_gap: Math.round(cv.bottom - box.bottom), placeholder: f.input.placeholder,
                                naked: !f.el.classList.contains("is-active") };
            f.input.value = "protocol"; f.k = 12;
            await f.run();
            for (let i = 0; i < 20 && !v.searchState; i++) await sleep(250);
            await sleep(600); v.batchSync();
            const left = { shown: f.shown, k: f.k, n: f.n, hits: f.hits.length,
                           count_text: f.el.querySelector(".domvec-search3d-count").innerText.replace(/\\s+/g, " ").trim(),
                           ...v.batch.lastStats, lights: v.batch.lightStats.lights, scroll_left: f.scroller.scrollLeft };
            // Which nodes draw as themselves: the shown results, and nothing else.
            const rs = v.graph.nodeRelSize(), d = v.graph.graphData();
            const asSelf = d.nodes.filter((n) => { const l = v.lookOf(n, rs, v.drawnMedia); return !l.glass; }).map((n) => String(n.id));
            const shownIds = v.searchState.targets.slice(0, f.shown).filter(Boolean).map((n) => String(n.id));
            left.self_ids = asSelf.length; left.self_are_shown = asSelf.every((id) => shownIds.includes(id));
            // Colourless lenses: glass with no glow of its own -- what a search
            // turns every other node into (the default orb glows, alpha 1).
            const lensCount = () => d.nodes.filter((n) => { const l = v.lookOf(n, rs, v.drawnMedia); return l.glass && l.alpha === 0; }).length;
            left.colourless = lensCount();
            // The top result flown to and its panel opened, as a hover does (item 94).
            await sleep(700);
            left.flown_top = v.searchStats.flown_top - flown0;
            left.top_panel = !!(f.hits[0] && v.billboards.has(f.hits[0].cid));
            // The soft index: at s = 1.5 the second result is part-way in -- a
            // half-coloured orb, not yet lit (2026-10-11: "smoothly brighten on
            // soft integer result nodes").
            const span = f.scroller.scrollWidth - f.scroller.clientWidth;
            f.scroller.scrollLeft = Math.round(span * 0.5 / Math.max(1, f.window.length - 1));
            f.scroller.dispatchEvent(new Event("scroll"));
            await sleep(400);
            const second = v.searchState.targets[1];
            const sl = second ? v.lookOf(second, rs, v.drawnMedia) : null;
            left.soft = { s: Math.round(f.soft * 100) / 100, second_glass: sl ? !!sl.glass : null, second_alpha: sl ? Math.round(sl.alpha * 100) / 100 : null };
            // Scrolled to the right: more shown, the brightest at the scrolled index.
            f.scroller.scrollLeft = f.scroller.scrollWidth; f.scroller.dispatchEvent(new Event("scroll"));
            await sleep(500); v.batchSync();
            const glowOf = (n) => (n ? (v.lookOf(n, rs, v.drawnMedia).glow || 0) : null);
            const tg = v.searchState.targets;
            const right = { shown: f.shown, window: f.window.length, ...v.batch.lastStats, lights: v.batch.lightStats.lights,
                            glow_first: glowOf(tg[0]), glow_last: glowOf(tg[f.shown - 1]), distinct_last: tg.indexOf(tg[f.shown - 1]) === f.shown - 1 };
            f.input.value = ""; await f.run(); await sleep(300); v.batchSync();
            const cleared = { colourless: lensCount(), orbs: v.batch.lastStats.glass, lights: v.batch.lightStats.lights, state: !!v.searchState };
            return { planted: ${planted}, level: v.level, placement, left, right, cleared, stats: { ...v.searchStats } };
          } finally {
            v.plantNoGlass = false; v.plantNoTopFlight = false; if (bv) bv.plantNoWebSearch = false; f.input.value = ""; await f.run();
            if (v.level !== startLevel && unit) { unit.click(); await settle(); }
          }
        })()`, { timeout: 90000 });
        const clean = await arm(false), planted = await arm(true);
        const c = clean;
        const pass = !c.error && c.placement.naked && c.placement.placeholder === "search" && Math.abs(c.placement.centre_off) <= 4 && c.placement.bottom_gap < 60
          && c.left.hits >= 2 && c.left.shown === 1 && /^showing \/ results · \d+ matching$/.test(c.left.count_text)
          && c.left.colourless > 0 && c.left.lights === 1 && c.left.self_are_shown
          && c.right.shown === c.right.window && c.right.window === Math.min(12, c.left.hits) && c.right.lights >= 1 && c.right.lights <= 16
          && (!c.right.distinct_last || (c.right.glow_last === 1 && c.right.glow_first < c.right.glow_last))
          && c.cleared.colourless === 0 && c.cleared.orbs > 0 && !c.cleared.state
          && c.left.flown_top === 1 && c.left.top_panel && c.left.soft.second_glass === true && c.left.soft.second_alpha > 0.2 && c.left.soft.second_alpha < 0.8
          && !planted.error && planted.left.colourless === 0 && planted.left.lights === 0 && planted.left.flown_top === 0;
        return { pass, evidence: { clean, planted } };
      },
    },
    {
      id: "G-167",
      asks: "retrieval is a LOOK: in the url view a search adds, moves and removes no node -- the scene's node set is the same before, during and after, and results whose chunk is not drawn light their page node; planted (plantPlaceResults): the first version placed undrawn results and the node set changed",
      async run() {
        // 2026-10-11, PLUGIN_GOAL 96: "streaming and node layout pipelines
        // ... that work unaffected by the retrieval results (since that's just
        // a brightness and fly-to-node thing)".
        const arm = (planted) => evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          await window.__domvec.act("open", "graph");
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
          for (let i = 0; i < 60 && !(v.graph && v.searchField); i++) await sleep(500);
          const f = v.searchField;
          const bv = app.workspace.getLeavesOfType("domvec-browser-view")[0]?.view;
          if (bv) bv.plantNoWebSearch = true;
          const unit = [...v.containerEl.querySelectorAll(".domvec-graph-bar button")].find((b) => /^(pages|chunks)$/.test(b.textContent.trim()));
          const start = v.level;
          const settle = async () => { let last = -1; for (let i = 0; i < 60; i++) { await sleep(500); const n = v.graph ? v.graph.graphData().nodes.length : 0; if (n && n === last) break; last = n; } };
          if (v.level !== "" && unit) {
            unit.click();
            // The url view has ARRIVED: not UMAP-only, and the chunk view's
            // tens of thousands of nodes gone.
            for (let i = 0; i < 240 && !(v.level === "" && !v.umapOnly && v.graph && v.graph.graphData().nodes.length < 5000); i++) await sleep(500);
            await settle();
          }
          v.plantPlaceResults = ${planted};
          const ids = () => new Set(v.graph.graphData().nodes.map((n) => String(n.id)));
          const same = (a, b) => a.size === b.size && [...a].every((x) => b.has(x));
          try {
            await sleep(1500);
            const before = ids();
            f.input.value = "dril"; f.k = 12; await f.run(); await sleep(1200);
            f.scroller.scrollLeft = f.scroller.scrollWidth; f.scroller.dispatchEvent(new Event("scroll")); await sleep(400);
            const during = ids();
            const st = { ...v.searchStats }, glowing = v.graph.graphData().nodes.filter((n) => (v.lookOf(n, v.graph.nodeRelSize(), v.drawnMedia).glow || 0) > 0).length;
            f.input.value = ""; await f.run(); await sleep(800);
            const after = ids();
            return { planted: ${planted}, level: v.level, nodes: before.size, during_same: same(before, during), after_same: same(before, after),
                     added: [...during].filter((x) => !before.has(x)).length, resolved_page: st.resolved_page, resolved_chunk: st.resolved_chunk, glowing };
          } finally {
            v.plantPlaceResults = false; if (bv) bv.plantNoWebSearch = false;
            if (f.input.value) { f.input.value = ""; await f.run(); }
            if (v.level !== start && unit) { unit.click(); await settle(); }
          }
        })()`, { timeout: 120000 });
        const clean = await arm(false), planted = await arm(true);
        return { pass: clean.level === "" && clean.during_same && clean.after_same && clean.resolved_page >= 1 && clean.glowing >= 1
                       && planted.added > 0 && !planted.during_same,
                 evidence: { clean, planted } };
      },
    },
    {
      id: "G-170",
      asks: "chunk view runs ONE bounded collision relax after its layout lands: overlapping pairs fall, no node moves more than its leash (4 of its radii) from its UMAP point, the fit itself is unwritten, and the frames keep flowing; planted (plantNoChunkRelax): the UMAP points as they are",
      async run() {
        // 2026-10-11: "a little too clumped together ... perhaps *some* amount
        // of force-directed is still worth, but not to the extent that we have
        // to break our memory bank or see nodes exploding everywhere".
        const arm = (planted) => evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          await window.__domvec.act("open", "graph");
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
          for (let i = 0; i < 60 && !v.graph; i++) await sleep(500);
          const unit = [...v.containerEl.querySelectorAll(".domvec-graph-bar button")].find((b) => /^(pages|chunks)$/.test(b.textContent.trim()));
          const start = v.level;
          const chunkView = () => v.level === "chunk" && v.umapOnly && v.graph && v.graph.graphData().nodes.length > 2000;
          if (!chunkView() && unit) { unit.click(); for (let i = 0; i < 240 && !chunkView(); i++) await sleep(500); }
          if (!chunkView()) return { error: "chunk view did not arrive", level: v.level };
          v.plantNoChunkRelax = ${planted};
          // A hovered url SPREADS its chunks (G-230) -- a display state that
          // moves them off their fit; the relax is measured without it.
          v.unspread?.();
          // A FRESH relax: since PLUGIN_GOAL 108 a node with a stored drawn
          // place stays where the reader last saw it, so after any earlier
          // relax nearly every node is fixed and there is nothing to measure.
          v.plantNoDrawn = true;
          try {
            const ns = v.graph.graphData().nodes.filter((n) => Number.isFinite(n.fitX));
            const fit0 = ns.slice(0, 3000).map((n) => n.fitX + n.fitY);
            for (const n of ns) { n.x = n.fx = n.fitX; n.y = n.fy = n.fitY; n.z = n.fz = n.fitZ ?? 0; }
            const runs0 = v.chunkRelaxStats.runs;
            const gap0 = v.frameGaps.length;
            v.relaxChunkView();
            for (let i = 0; i < 120 && v.chunkRelaxStats.runs === runs0; i++) await sleep(250);
            await sleep(500);
            const gaps = v.frameGaps.slice(gap0).sort((a, b) => a - b);
            const rs = v.graph.nodeRelSize();
            let maxShift = 0;
            // In the radius each node had WHEN the relax measured its leash: the
            // spacing pass may shrink it afterwards.
            for (const n of ns) { const h = n.relaxHalf || v.lookOf(n, rs, v.drawnMedia).half || 1e-6; maxShift = Math.max(maxShift, Math.hypot(n.x - n.fitX, n.y - n.fitY, (n.z || 0) - (n.fitZ ?? 0)) / h); }
            const fitKept = ns.slice(0, 3000).every((n, i) => n.fitX + n.fitY === fit0[i]);
            return { planted: ${planted}, ran: v.chunkRelaxStats.runs - runs0, stats: { ...v.chunkRelaxStats }, max_shift_radii: Math.round(maxShift * 100) / 100,
                     fit_kept: fitKept, frames: gaps.length, frame_p99: gaps[Math.floor(gaps.length * 0.99)] ?? null, frame_max: gaps[gaps.length - 1] ?? null };
          } finally {
            v.plantNoChunkRelax = false;
            v.plantNoDrawn = false;
            if (${planted}) v.relaxChunkView();               // leave the reader the relaxed picture
            if (v.level !== start && unit) { unit.click(); }
          }
        })()`, { timeout: 240000 });
        const clean = await arm(false), planted = await arm(true);
        const c = clean;
        return { pass: !c.error && c.ran === 1 && c.stats.overlaps_after < 0.5 * c.stats.overlaps_before && c.max_shift_radii <= 4.05 && c.fit_kept
                       && (c.frame_max ?? 0) < 120 && (c.stats.worst_frame_ms ?? 99) < 40 && !planted.error && planted.ran === 0 && planted.max_shift_radii < 1e-6,
                 evidence: { clean, planted } };
      },
    },
    {
      id: "G-158",
      asks: "a query from the 3D field also searches DuckDuckGo in the browser cell: it lands on the results, scrolls and presses 'More results', and the page is captured into the store as it streams; planted (plantNoWebSearch): the cell never leaves its page",
      async run() {
        // 2026-10-11, PLUGIN_GOAL 85: "search duckduckgo automatically,
        // following a simple auto-scroll and clicking 'more results' each time".
        const arm = (planted) => evaluate(`(async () => {
          ${PREP}
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
          for (let i = 0; i < 60 && !(v.graph && v.searchField); i++) await sleep(500);
          const f = v.searchField;
          const start = b.webview.getURL();
          b.plantNoWebSearch = ${planted};
          try { b.setLive(true); } catch (e) {}
          const q = "okapi giraffe relative habitat " + (${planted} ? "b" : "a");
          const asked0 = b.webSearchStats.asked, clicked0 = b.webSearchStats.clicked;
          try {
            f.input.value = q; await f.run();
            let url = "";
            for (let i = 0; i < 360; i++) { await sleep(500); url = b.webview.getURL(); if (b.webSearchStats.asked > asked0 && b.webSearchStats.ms && b.webSearchStats.last === q) break; if (${planted} && i > 60) break; }
            await sleep(3000);
            url = b.webview.getURL();
            const onDdg = /duckduckgo\\.com/.test(url);
            let stored = 0;
            if (onDdg) for (let i = 0; i < 30; i++) { stored = (await v.sidecar.pageCids(url).catch(() => [])).length; if (stored) break; await sleep(1000); }
            return { planted: ${planted}, asked: b.webSearchStats.asked - asked0, clicked: b.webSearchStats.clicked - clicked0,
                     results: b.webSearchStats.results, stopped: b.webSearchStats.stopped, on_ddg: onDdg, url: url.slice(0, 80), stored_chunks: stored,
                     merged: v.searchStats.web_merged };
          } finally {
            b.plantNoWebSearch = false;
            f.input.value = ""; await f.run();
            if (b.webview.getURL() !== start && /^https?:/.test(start)) { b.go(start); await sleep(1500); }
          }
        })()`, { timeout: 300000 });
        const clean = await arm(false), planted = await arm(true);
        return { pass: clean.asked === 1 && clean.on_ddg && clean.results > 0 && clean.clicked >= 1 && clean.stored_chunks > 0
                       && planted.asked === 0 && !planted.on_ddg,
                 evidence: { clean, planted } };
      },
    },
    {
      id: "G-178",
      asks: "typing in the 3D search field ranks the store and never reaches the browser cell; the search button (and Enter) sends it to the web; planted (plantWebOnType): every typed query goes to the web",
      async run() {
        // 2026-10-11, PLUGIN_GOAL 107: "the search button should trigger web
        // search, not auto-updates piped also to the search browser".
        const arm = (planted) => evaluate(`(async () => {
          ${PREP}
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
          for (let i = 0; i < 60 && !(v.graph && v.searchField); i++) await sleep(500);
          const f = v.searchField;
          const web = () => v.searchStats.web_asked;
          v.plantWebOnType = ${planted};
          // Not actually sent: the cell's web half is swapped for a counter.
          const was = v.onWebSearch; let sent = 0; v.onWebSearch = () => { sent++; };
          try {
            const w0 = web();
            for (const q of ["ok", "oka", "okapi"]) { f.input.value = q; await f.run(); }
            const typed = sent;
            f.input.value = "okapi habitat"; await f.submit();
            const pressed = sent - typed;
            return { planted: ${planted}, typed_sent: typed, pressed_sent: pressed, button: !!f.button, web_asked: web() - w0 };
          } finally {
            v.onWebSearch = was; v.plantWebOnType = false;
            f.input.value = ""; await f.run();
          }
        })()`, { timeout: 60000 });
        const clean = await arm(false), planted = await arm(true);
        return { pass: clean.button && clean.typed_sent === 0 && clean.pressed_sent === 1 && planted.typed_sent === 3,
                 evidence: { clean, planted } };
      },
    },
    {
      id: "G-177",
      asks: "while a query stands, a re-ranking from the store is applied as a diff -- the new order shown, the reader's scroll kept, the change said -- and the bar carries the brightness gradient; planted (plantNoRerank): the ranking is asked once and never followed",
      async run() {
        // 2026-10-11, PLUGIN_GOAL 106: "i notice no diff update on retrieval
        // results and effects on the scroll bar".
        const arm = (planted) => evaluate(`(async () => {
          ${PREP}
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
          for (let i = 0; i < 60 && !(v.graph && v.searchField); i++) await sleep(500);
          const f = v.searchField;
          v.plantNoRerank = ${planted};
          const was = v.onWebSearch; v.onWebSearch = () => {};
          try {
            f.input.value = "wikipedia history"; await f.run();
            await sleep(300);
            const following = !!v.webTimer;
            // The store's answer is the truth; the field is given a stale
            // copy (reversed), as if the store had moved since it asked.
            const truth = f.hits.map((h) => h.cid);
            f.hits = f.hits.slice().reverse();
            f.scroller.scrollLeft = Math.min(56, f.scroller.scrollWidth);
            const left = f.scroller.scrollLeft;
            await v.rerank();
            const now = f.hits.map((h) => h.cid);
            const grad = String(f.scroller.style.backgroundImage || "");
            return { planted: ${planted}, following, hits: now.length, restored: JSON.stringify(now) === JSON.stringify(truth),
                     diff: f.stats.lastDiff, scroll_kept: f.scroller.scrollLeft === left,
                     gradient_stops: (grad.match(/rgba/g) || []).length };
          } finally {
            v.onWebSearch = was; v.plantNoRerank = false;
            f.input.value = ""; await f.run();
          }
        })()`, { timeout: 60000 });
        const clean = await arm(false), planted = await arm(true);
        return { pass: clean.following && clean.hits > 1 && clean.restored && clean.diff && clean.diff.moved > 0
                       && clean.scroll_kept && clean.gradient_stops >= 2 && !planted.following,
                 evidence: { clean, planted } };
      },
    },
    {
      id: "G-176",
      asks: "the web half of a search is exhaustive: it scrolls and presses 'More results' until a round adds nothing or the button is gone, and says which ended it; planted (plantFixedRounds = 3): it stops after three rounds with results still to come",
      async run() {
        // 2026-10-11, PLUGIN_GOAL 105: "scrolling and 'more results' in search
        // should be an exhaustive while loop until no deltas or something like
        // the more results button isn't there."
        // The same query in both arms, so the page's own supply is the
        // denominator: the planted arm only discriminates if its cap FIRED
        // (results were still coming), and then clean must hold more.
        const arm = (cap) => evaluate(`(async () => {
          ${PREP}
          const start = b.webview.getURL();
          b.plantFixedRounds = ${cap};
          const s = b.webSearchStats;
          try {
            const t0 = Date.now();
            const got = await b.searchWeb("okapi forest giraffe ecology");
            return { cap: ${cap}, ok: !!got, rounds: s.rounds, clicked: s.clicked, results: s.results, stopped: s.stopped,
                     deltas: s.deltas.slice(), ms: Date.now() - t0 };
          } finally {
            b.plantFixedRounds = 0;
            if (/^https?:/.test(start) && b.webview.getURL() !== start) { b.go(start); await sleep(1500); }
          }
        })()`, { timeout: 600000 });
        const clean = await arm(0), planted = await arm(3);
        const exhausted = clean.stopped === "no delta" || clean.stopped === "no more-results button";
        const capFired = planted.stopped === "fixed rounds (planted)" && planted.deltas.length && planted.deltas[planted.deltas.length - 1] > 0;
        return { pass: clean.ok && exhausted && clean.results > 0 && capFired && clean.results > planted.results,
                 evidence: { clean, planted, exhausted, cap_fired_with_results_coming: !!capFired } };
      },
    },
    {
      id: "G-172",
      asks: "nodes near the pointer's ray glow -- the same region that reveals pictures, graded by nearness: an orb glows brighter, a picture keeps its image and glows at its edge; planted (plantNoHoverGlow): nothing glows",
      async run() {
        // 2026-10-11, PLUGIN_GOAL 102: "there should be the glowing effect for
        // when nodes are hovered over. for images, keep the images but still
        // add the glow effect ... within a certain region of the mouse on the
        // camera normal".
        const arm = (planted) => evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          await window.__domvec.act("open", "graph");
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
          for (let i = 0; i < 60 && !(v.graph && v.batch); i++) await sleep(500);
          if (v.searchField && v.searchField.input.value) { v.searchField.input.value = ""; await v.searchField.run(); }
          v.plantNoHoverGlow = ${planted};
          try {
            // The pointer ON a drawn node near the panel's centre, the region
            // recomputed now. At the bare centre the nearest node's nearness
            // was whatever the scene left there (0.38), and "top === 1" -- a
            // node under the pointer glows fullest -- asked about no node.
            const W = v.canvasEl.clientWidth, H = v.canvasEl.clientHeight;
            const onScreen = v.graph.graphData().nodes.filter((n) => Number.isFinite(n.x) && !n.force)
              .map((n) => ({ n, s: v.graph.graph2ScreenCoords(n.x, n.y, n.z || 0) }))
              .filter((o) => o.s.x > 0.2 * W && o.s.x < 0.8 * W && o.s.y > 0.2 * H && o.s.y < 0.8 * H)
              .sort((a, c) => Math.hypot(a.s.x - W / 2, a.s.y - H / 2) - Math.hypot(c.s.x - W / 2, c.s.y - H / 2));
            const aim = onScreen[0] ? onScreen[0].s : { x: W / 2, y: H / 2 };
            v.pointerNdc = [aim.x / W * 2 - 1, -(aim.y / H * 2 - 1)]; v.detailDirty = true; v.detailAt = 0;
            v.refreshDetail(v.graph);
            v.batchSync();
            const rs = v.graph.nodeRelSize();
            const near = [...v.glowNear.entries()].sort((a, b) => b[1] - a[1]);
            let orbGlow = 0, picGlow = 0, picKept = 0;
            for (const [n] of near) {
              const l = v.lookOf(n, rs, v.drawnMedia);
              if (l.glass && l.alpha > 1) orbGlow++;
              if (l.picture) { picKept++; if ((l.glow || 0) > 0) picGlow++; }
            }
            const far = v.graph.graphData().nodes.filter((n) => !v.glowNear.has(n) && !n.hovered).slice(0, 2000)
              .filter((n) => { const l = v.lookOf(n, rs, v.drawnMedia); return (l.glass && l.alpha > 1) || (l.glow || 0) > 0; }).length;
            return { planted: ${planted}, aimed_at_node: !!onScreen[0], region: near.length, top: near[0] ? Math.round(near[0][1] * 100) / 100 : null,
                     edge: near.length ? Math.round(near[near.length - 1][1] * 100) / 100 : null,
                     orbs_glowing: orbGlow, pictures: picKept, pictures_glowing: picGlow, glowing_outside: far };
          } finally { v.plantNoHoverGlow = false; v.batchSync(); }
        })()`, { timeout: 60000 });
        const clean = await arm(false), planted = await arm(true);
        const c = clean;
        return { pass: c.region > 0 && c.top === 1 && c.edge < c.top && c.orbs_glowing + c.pictures_glowing > 0
                       && c.pictures_glowing === c.pictures && c.glowing_outside === 0
                       && planted.orbs_glowing === 0 && planted.pictures_glowing === 0,
                 evidence: { clean, planted } };
      },
    },
    {
      id: "G-164",
      asks: "a page never stored, streamed in: each stage -- drain, grey nodes, projected nodes, stored chunks drawn -- is marked the first time it reaches the 3D view, in order, with its provenance (the drain trace and the sidecar's phases); hovers throughout are timed hover-to-panel per stage; and the stage strip in the browser's readout shows it; planted (plantNoProjected): the projected stage never arrives and the clock says so",
      async run() {
        // 2026-10-11, PLUGIN_GOAL 91.
        const fixtures = await serveFixtures();
        const page = fixtures.origin + "/catalog.html";
        try {
          const arm = (planted, path) => evaluate(`(async () => {
            ${PREP}
            const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
            const wc = window.require("@electron/remote").webContents.fromId(b.webview.getWebContentsId());
            v.plantNoProjected = ${planted};
            try { b.setLive(true); } catch (e) {}
            const PAGE = ${JSON.stringify(page)} + ${JSON.stringify(path)};
            try {
              b.go(PAGE);
              // Hover over the page all the way through, so every stage gets hovers.
              const t0 = performance.now();
              let k = 0;
              while (performance.now() - t0 < 25000) {
                await sleep(400);
                const x = 60 + (k % 4) * 70, y = 90 + (Math.floor(k / 4) % 5) * 70; k++;
                try { wc.sendInputEvent({ type: "mouseMove", x, y }); wc.sendInputEvent({ type: "mouseMove", x: x + 1, y }); } catch (e) {}
                const vis = window.__domvec.profile.visits().slice(-1)[0];
                if (vis && vis.marks.stored !== undefined && performance.now() - t0 > 12000) break;
              }
              wc.sendInputEvent({ type: "mouseMove", x: -8, y: -8 }); wc.sendInputEvent({ type: "mouseLeave", x: -8, y: -8 });
              const vis = window.__domvec.profile.visits().find((x) => x.url === PAGE) || null;
              // The interface: the readout's stage strip, as drawn.
              // The box opened, as the reader opens it, and the strip read as drawn.
              const box = b.pipebox;
              const wasOpen = !!(box && box.userOpen);
              let strip = null;
              try {
                if (box) box.setExpanded(true);
                for (let i = 0; i < 20 && !strip; i++) {
                  await sleep(300);
                  try { box.readout && box.readout.draw(); } catch (e) {}
                  const stEl = box && box.el.querySelector(".domvec-profile-stages");
                  strip = stEl ? stEl.innerText.replace(/\\s+/g, " ").trim().slice(0, 300) : null;
                }
              } finally { if (box && !wasOpen) box.setExpanded(false); }
              return { planted: ${planted}, visit: vis, strip };
            } finally { v.plantNoProjected = false; }
          })()`, { timeout: 90000 });
          const clean = await arm(false, "?stages=" + Date.now().toString(36));
          const planted = await arm(true, "?stages=" + Date.now().toString(36) + "p");
          const m = (clean.visit && clean.visit.marks) || {};
          const ordered = ["drain", "grey", "projected", "stored"].every((k) => m[k] !== undefined)
            && m.drain <= m.grey && m.grey <= m.stored;
          const hovered = clean.visit ? Object.values(clean.visit.hover || {}).reduce((a, h) => a + h.n, 0) : 0;
          const prov = clean.visit && clean.visit.prov.stored && clean.visit.prov.stored.trace && clean.visit.prov.stored.sidecar_total !== null;
          return { pass: ordered && !!prov && hovered >= 1 && !!clean.strip && /stored/.test(clean.strip)
                         && planted.visit && planted.visit.marks.projected === undefined && planted.visit.marks.stored !== undefined,
                   evidence: { clean, planted, readout_seen: clean.strip, purged: await tidyFixtures(fixtures.origin) } };
        } finally { await fixtures.close(); }
      },
    },
    {
      id: "G-174",
      asks: "in chunk view, a pointer sweeping the 3D panel has its glow written within a frame or two (in-app pointer-to-glow p50 under 40 ms), the changed nodes patched and moved between meshes in place with every slot consistent afterwards; planted (plantSlowGlow, plantFullPick: the 80 ms throttle, a full re-sync per change, the full raycast) at least 1.5x the frame per move",
      async run() {
        // 2026-10-11, PLUGIN_GOAL 104: "node hover and image/glow features
        // seem to work but have a noticeably slow latency".
        const arm = (planted) => evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          await window.__domvec.act("open", "graph");
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
          for (let i = 0; i < 60 && !v.graph; i++) await sleep(500);
          const unit = [...v.containerEl.querySelectorAll(".domvec-graph-bar button")].find((b) => /^(pages|chunks)$/.test(b.textContent.trim()));
          const start = v.level;
          const chunkView = () => v.level === "chunk" && v.umapOnly && v.graph && v.graph.graphData().nodes.length > 2000;
          const runs0 = v.chunkRelaxStats.runs;
          let switched = false;
          if (!chunkView() && unit) { switched = true; unit.click(); for (let i = 0; i < 240 && !chunkView(); i++) await sleep(500); }
          if (!chunkView()) return { error: "chunk view did not arrive" };
          // THIS switch's relax done first (the counter outlives views): its
          // frame slices and the rebuild would be measured otherwise.
          if (switched) for (let i = 0; i < 160 && v.chunkRelaxStats.runs <= runs0; i++) await sleep(500);
          await sleep(1500);
          v.plantSlowGlow = ${planted}; v.plantFullPick = ${planted};
          try {
            const host = v.canvasEl, r = v.graph.renderer().domElement.getBoundingClientRect();
            v.glowLatency = [];
            const p0 = { ...v.batch.patchStats };
            const t0 = performance.now();
            for (let k = 0; k < 120; k++) {
              const x = r.left + r.width * (0.3 + 0.4 * ((k % 40) / 40)), y = r.top + r.height * (0.4 + 0.2 * (Math.floor(k / 40) % 2));
              host.dispatchEvent(new PointerEvent("pointermove", { clientX: x, clientY: y, bubbles: true }));
              await new Promise((res) => requestAnimationFrame(() => res(0)));
              await sleep(12);
            }
            // Each move waits for its frame: the sweep's time per move IS the
            // frame the reader waits for, which the pacing would otherwise hide.
            const perMove = (performance.now() - t0) / 120 - 12;
            await sleep(300);
            const a = v.glowLatency.slice().sort((x, y) => x - y);
            // Every node's slot holds that node, inside its mesh's count, in the
            // mesh its look routes it to.
            const b = v.batch, rs = v.graph.nodeRelSize(), ms = [b.opaque, b.clear, b.glass];
            let bad = 0, wrong = 0, outside = 0, checked = 0;
            for (const n of v.graph.graphData().nodes) {
              if (n.__bi === undefined) continue; checked++;
              if (n.__bi >= ms[n.__bm].geo.instanceCount) outside++;
              if (b.slots[n.__bm][n.__bi] !== n) bad++;
              const lk = v.lookOf(n, rs, v.drawnMedia);
              const cell = lk.picture ? b.cells.get(lk.picture) : undefined;
              const pending = !!lk.picture && cell === undefined && !lk.translucent;
              const want = (lk.glass || pending) ? 2 : lk.translucent ? 1 : 0;
              if (want !== n.__bm && !v.batchDirty) wrong++;
            }
            // Picking still lands: for nodes drawn on screen, the pointer put on
            // each one's own screen point, the ray there hits ITS proxy.
            const cam = v.graph.camera(), scene = v.graph.scene();
            const onScreen = v.graph.graphData().nodes.filter((nd) => nd.__threeObj && Number.isFinite(nd.x)).map((nd) => {
              const q = { x: nd.x, y: nd.y, z: nd.z || 0 }; const vv = cam.position.clone().set(q.x, q.y, q.z).project(cam);
              return { nd, x: vv.x, y: vv.y, z: vv.z };
            }).filter((o) => Math.abs(o.x) < 0.8 && Math.abs(o.y) < 0.8 && o.z < 1).slice(0, 400);
            let picked = 0, tried = 0;
            for (let t = 0; t < onScreen.length && tried < 10; t += Math.max(1, Math.floor(onScreen.length / 10))) {
              const o = onScreen[t]; tried++;
              v.pointerNdc = [o.x, o.y]; v.detailDirty = true; v.detailAt = 0; v.refreshDetail(v.graph);
              const rc = new window.__domvecRaycaster();
              rc.setFromCamera({ x: o.x, y: o.y }, cam);
              const hits = rc.intersectObjects(scene.children, true).filter((h) => h.object.__proxy);
              if (hits.some((h) => h.object === o.nd.__threeObj)) picked++;
            }
            return { planted: ${planted}, n: a.length, p50: a[a.length >> 1] ?? null, p90: a[Math.floor(a.length * 0.9)] ?? null,
                     picks: { tried, picked },
                     frame_per_move_ms: Math.round(perMove * 10) / 10,
                     patches: b.patchStats.patches - p0.patches, moved: b.patchStats.moved - p0.moved,
                     integrity: { checked, slot_mismatch: bad, outside, wrong_mesh: wrong } };
          } finally {
            v.plantSlowGlow = false; v.plantFullPick = false;
            if (v.level !== start && unit) unit.click();
          }
        })()`, { timeout: 300000 });
        const clean = await arm(false), planted = await arm(true);
        const c = clean, i = c.integrity || {};
        return { pass: !c.error && c.n >= 20 && c.p50 < 40 && c.patches > 0 && c.picks && c.picks.tried >= 5 && c.picks.picked === c.picks.tried && i.slot_mismatch === 0 && i.outside === 0 && i.wrong_mesh === 0
                       && !planted.error && planted.frame_per_move_ms >= 1.5 * c.frame_per_move_ms,
                 evidence: { clean, planted } };
      },
    },
    {
      id: "G-173",
      asks: "an opened page's chunks are linked along the patricia trie -- each to the chunk whose trie node is the longest proper prefix of its own, computed here from each chunk's own addresses -- not all to the url node: on RFC 9110 (placed in slices), Dril, Okapi and the two largest other stored pages, at least 95% of chunks hang from the trie's parent and no more hang from the url node than the trie roots there; planted (plantSliceContainment): RFC's url-node links come back",
      async run() {
        // 2026-10-11, PLUGIN_GOAL 103: "it looks like a shortcut where there's
        // just all the recursive chunks linked to their root URL node. Perhaps
        // investigate further, since this is a recurring item that needs
        // continuous clarity on its representations in the 3D graph viewer".
        const arm = (planted) => evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          await window.__domvec.act("open", "graph");
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
          for (let i = 0; i < 60 && !v.graph; i++) await sleep(500);
          const unit = [...v.containerEl.querySelectorAll(".domvec-graph-bar button")].find((b) => /^(pages|chunks)$/.test(b.textContent.trim()));
          const start = v.level;
          const urlView = () => v.level === "" && !v.umapOnly && v.graph && v.graph.graphData().nodes.length < 5000;
          if (!urlView() && unit) { unit.click(); for (let i = 0; i < 240 && !urlView(); i++) await sleep(500); }
          if (!urlView()) return { error: "url view did not arrive" };
          v.plantSliceContainment = ${planted};
          const id = (x) => String(typeof x === "object" && x ? x.id : x);
          const steps = (x) => String(x).split("/text()")[0].split("/@")[0].split("/").filter(Boolean);
          const pages = v.graph.graphData().nodes.filter((n) => n.level === "page" && /^https?:/.test(n.url || "") && !/127[.]0[.]0[.]1|localhost/.test(n.url));
          const want = ["https://www.rfc-editor.org/rfc/rfc9110.html", "https://en.wikipedia.org/wiki/Dril", "https://en.wikipedia.org/wiki/Okapi"];
          const others = pages.filter((n) => !want.includes(n.url)).sort((a, b) => (b.fullVal ?? b.val) - (a.fullVal ?? a.val)).slice(0, 2).map((n) => n.url);
          const urls = ${planted} ? [want[0]] : want.concat(others);
          const out = [];
          try {
            for (const U of urls) {
              const pg = pages.find((n) => n.url === U);
              if (!pg) { out.push({ url: U, missing: true }); continue; }
              const d0 = v.graph.graphData();
              const wasOpen = d0.nodes.some((n) => n.url === U && n.level !== "page" && !n.force);
              if (wasOpen) await v.togglePage(pg);          // folded first: measured from a fresh open
              await v.togglePage(pg);
              await sleep(1500);
              const d = v.graph.graphData();
              const mine = d.nodes.filter((n) => n.url === U && n.level !== "page" && !n.force).map((n) => String(n.id));
              const set = new Set(mine), parentOf = {};
              for (const l of d.links) { const s2 = id(l.source), t = id(l.target); if (set.has(t)) parentOf[t] = s2 === String(pg.id) ? "PAGE" : s2; }
              // The trie's verdict, from each chunk's own addresses.
              const nodeOf = {};
              for (const c of mine) {
                const pay = await v.sidecar.chunk(c).catch(() => null);
                const xs = ((pay && pay.lines) || []).map((ln) => String(ln.key || "").split("|")[1] || "").filter(Boolean);
                if (!xs.length) continue;
                let pre = steps(xs[0]);
                for (const x of xs.slice(1)) { const s2 = steps(x); let i = 0; while (i < pre.length && i < s2.length && pre[i] === s2[i]) i++; pre = pre.slice(0, i); }
                nodeOf[c] = pre.join("/");
              }
              const owner = {};
              for (const c of mine) if (nodeOf[c] !== undefined && owner[nodeOf[c]] === undefined) owner[nodeOf[c]] = c;
              const trieParent = {};
              for (const c of Object.keys(nodeOf)) {
                const st = nodeOf[c].split("/"); let par = "PAGE";
                for (let cut = st.length - 1; cut > 0; cut--) { const o = owner[st.slice(0, cut).join("/")]; if (o !== undefined && o !== c) { par = o; break; } }
                trieParent[c] = par;
              }
              const known = Object.keys(trieParent);
              // Same parent = same trie NODE: an element cut in parts is several
              // chunks on one node, and which part stands for it is a tie-break.
              const nodeAt = (x) => (x === "PAGE" || x === undefined ? x : nodeOf[x]);
              const agree = known.filter((c) => parentOf[c] === trieParent[c] || (parentOf[c] !== "PAGE" && nodeAt(parentOf[c]) !== undefined && nodeAt(parentOf[c]) === nodeAt(trieParent[c]))).length;
              const fromPage = mine.filter((c) => parentOf[c] === "PAGE").length;
              const trieRoots = known.filter((c) => trieParent[c] === "PAGE").length;
              out.push({ url: U, chunks: mine.length, resolved: known.length, agree, agree_share: known.length ? Math.round(agree / known.length * 1000) / 1000 : null,
                         from_page: fromPage, trie_roots: trieRoots });
              if (!wasOpen) await v.togglePage(pg);         // put back folded
            }
          } finally {
            v.plantSliceContainment = false;
            if (v.level !== start && unit) unit.click();
          }
          return JSON.stringify(out);
        })()`, { timeout: 600000 });
        const clean = JSON.parse(await arm(false)), planted = JSON.parse(await arm(true));
        const good = (r) => !r.missing && r.agree_share >= 0.95 && r.from_page <= r.trie_roots + Math.max(1, Math.round(r.chunks * 0.02));
        const rfcP = planted.find((r) => r.url.includes("rfc9110"));
        return { pass: Array.isArray(clean) && clean.length >= 3 && clean.filter((r) => !r.missing).every(good)
                       && !!rfcP && rfcP.from_page > (rfcP.trie_roots + 50),
                 evidence: { clean, planted } };
      },
    },
    {
      id: "G-162",
      asks: "a browser toggle hides the overlay's chunk boxes by ALPHA only: off, the hover outline is placed but drawn at opacity 0 and the hover still reaches the 3D view; on, opacity 1; planted (plantBoxesStopHover): off also stops the hover",
      async run() {
        // 2026-10-11 (PLUGIN_GOAL 89): "a toggle to the browser overlay that
        // *shows* the overlay chunk bounding boxes as on or off, while keeping
        // the regular functionality the same, just a difference basically of
        // the alpha-ing".
        const fixtures = await serveFixtures();
        const page = fixtures.origin + "/shadow_catalogue.html";
        try {
          const arm = (planted) => evaluate(`(async () => {
            ${PREP}
            const PAGE = ${JSON.stringify(page)};
            const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
            const wc = window.require("@electron/remote").webContents.fromId(b.webview.getWebContentsId());
            const was = b.boxesShown();
            b.plantBoxesStopHover = ${planted};
            try {
              try { b.setLive(true); } catch (e) {}
              await land(PAGE, 30000);
              for (let i = 0; i < 90 && !(b.pipebox.map.url === PAGE && b.pipebox.map.chunks > 0); i++) await sleep(500);
              await b.webview.executeJavaScript("window.scrollTo(0,0); 1"); await sleep(400);
              const outlineEl = b.pipebox.outline;
              const hoverOnce = async (x, y) => {
                const a0 = v.focusStats.asked, p0 = b.pipebox.pushedHovers;
                wc.sendInputEvent({ type: "mouseMove", x: -8, y: -8 }); wc.sendInputEvent({ type: "mouseLeave", x: -8, y: -8 }); await sleep(300);
                wc.sendInputEvent({ type: "mouseMove", x, y }); await sleep(30); wc.sendInputEvent({ type: "mouseMove", x: x + 1, y }); await sleep(900);
                return { pushed: b.pipebox.pushedHovers - p0, hovered: !!b.pipebox.hover, asked: v.focusStats.asked - a0,
                         shown: outlineEl.style.display !== "none" && !!b.pipebox.hover,
                         opacity: Number(getComputedStyle(outlineEl).opacity) };
              };
              await b.toggleBoxes(false);
              const off = await hoverOnce(60, 120);
              await b.toggleBoxes(true);
              const on = await hoverOnce(60, 120);
              return { planted: ${planted}, off, on };
            } finally {
              b.plantBoxesStopHover = false;
              await b.toggleBoxes(was);
              wc.sendInputEvent({ type: "mouseMove", x: -8, y: -8 }); wc.sendInputEvent({ type: "mouseLeave", x: -8, y: -8 });
            }
          })()`, { timeout: 90000 });
          const clean = await arm(false), planted = await arm(true);
          return { pass: clean.off.hovered && clean.off.asked >= 1 && clean.off.shown && clean.off.opacity === 0
                         && clean.on.hovered && clean.on.opacity === 1 && !planted.off.hovered && planted.off.asked === 0,
                   evidence: { clean, planted, purged: await tidyFixtures(fixtures.origin) } };
        } finally { await fixtures.close(); }
      },
    },
    {
      id: "G-125",
      asks: "ONE hover panel persists: hovering a second chunk replaces the first; after the pointer leaves it stays, and closes itself after its time-to-live; planted (plantCloseOnLeave): it closes when the hover ends",
      async run() {
        const fixtures = await serveFixtures();
        // A page the store cuts into SEVERAL chunks: `practice_rows` is two, and one
        // holds its heading, table and nav, so every hover there resolves to it
        // (2026-10-11, once hovers resolve by address). The catalogue is eight.
        const page = fixtures.origin + "/shadow_catalogue.html";
        try {
          const arm = (planted) => evaluate(`(async () => {
            ${PREP}
            const PAGE = ${JSON.stringify(page)};
            const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
            const wc = window.require("@electron/remote").webContents.fromId(b.webview.getWebContentsId());
            v.plantCloseOnLeave = ${planted};
            v.hoverPanelTtlMs = 2500;
            try {
              try { b.setLive(true); } catch (e) {}
              await land(PAGE, 30000);
              for (let i = 0; i < 90 && !(b.pipebox.map.url === PAGE && b.pipebox.map.chunks > 0); i++) await sleep(500);
              for (const bb of v.billboardState()) v.closeBillboard(bb.id);
              await b.webview.executeJavaScript("window.scrollTo(0,0); 1");
              await sleep(600);
              // Two points over two DIFFERENT stored chunks, by the page's own chunking.
              const pts = JSON.parse(await b.webview.executeJavaScript("(function(){var h=window.__domvecSensor;var a=[];for(var y=40;y<innerHeight-30;y+=30)for(var x=40;x<Math.min(innerWidth,760);x+=90){var st=document.elementsFromPoint(x,y),bb=null,ba=Infinity;for(var i=0;i<st.length&&i<12;i++){var c=null;try{c=h.at(st[i]);}catch(e){}if(c&&c.box){var ar=c.box[2]*c.box[3];if(ar>0&&ar<ba){ba=ar;bb=c;}}}if(bb)a.push({x:x,y:y,id:bb.id});}return JSON.stringify(a);})()"));
              let A = null, B = null;
              for (const p of pts) { const st = b.storedCidFor("f:" + b.session + "#" + p.id, b.session); if (!st) continue; if (!A) A = { ...p, st }; else if (st !== A.st) { B = { ...p, st }; break; } }
              if (!A) return { planted: ${planted}, error: "no point under the pointer resolves to a stored chunk", points: pts.length };
              const open = () => [...v.billboards.values()].filter((e) => e.fromHover).length;
              // The stored chunk a hover OPENS is the one the host resolved from the
              // hovered element's own address (P-B7, 2026-10-11) -- finer than the
              // in-page chunk's, so it is read from the hover, not predicted from
              // the id. B is the first point whose hover resolves elsewhere.
              const hoverAt = async (q) => { wc.sendInputEvent({ type: "mouseMove", x: q.x, y: q.y }); await sleep(30); wc.sendInputEvent({ type: "mouseMove", x: q.x + 1, y: q.y }); await sleep(250);
                                             return (b.pipebox.hover && b.pipebox.hover.stored) || q.st; };
              A = { ...A, st: await hoverAt(A) };
              await sleep(1050);
              const aOpen = v.billboards.has(A.st);
              B = null;
              // On a narrow pane one chunk can fill the viewport: the search scrolls
              // a viewport at a time (A's panel persists through it -- the point).
              const seen = [];
              for (let page = 0; page < 5 && !B; page++) {
                if (page) { await b.webview.executeJavaScript("window.scrollBy(0, Math.round(innerHeight * 0.8)); 1"); await sleep(500); }
                // elementsFromPoint stops at a shadow host, which has no chunk of its
                // own, so below the fold the scan finds nothing; the hover itself
                // resolves through shadow roots, so a plain grid is hovered there.
                const grid = []; for (let y = 60; y < 760; y += 120) for (let x = 60; x < 340; x += 120) grid.push({ x, y });
                const here = page ? grid : pts;
                seen.push({ page, points: here.length, stored: [] });
                for (const p of here) { const st = await hoverAt({ ...p, st: "" }); seen[seen.length - 1].stored.push(String(st).slice(0, 8)); if (st && st !== A.st) { B = { ...p, st }; break; } }
              }
              if (!B) return { planted: ${planted}, error: "no second point resolves to another stored chunk", a: A.st, seen };
              await sleep(1050);
              const bOpen = v.billboards.has(B.st), aAfter = v.billboards.has(A.st), afterB = open();
              wc.sendInputEvent({ type: "mouseMove", x: -8, y: -8 });
              wc.sendInputEvent({ type: "mouseLeave", x: -8, y: -8 });
              await sleep(1500);
              const at1500 = open();
              await sleep(2500);
              const afterTtl = open();
              return { planted: ${planted}, a_opened: aOpen, b_opened: bOpen, a_after_b: aAfter, open_after_b: afterB,
                       open_1500_after_leave: at1500, open_after_ttl: afterTtl };
            } finally { v.plantCloseOnLeave = false; v.hoverPanelTtlMs = 60000; }
          })()`, { timeout: 150000 });
          const clean = await arm(false);
          const planted = await arm(true);
          return { pass: !clean.error && clean.a_opened && clean.b_opened && !clean.a_after_b && clean.open_after_b === 1
                         && clean.open_1500_after_leave === 1 && clean.open_after_ttl === 0 && planted.open_1500_after_leave === 0,
                   evidence: { clean, planted, purged: await tidyFixtures(fixtures.origin) } };
        } finally { await fixtures.close(); }
      },
    },
    {
      id: "G-124",
      asks: "a navigation's first hover flight ZOOMS; later flights keep the reader's own zoom and only re-aim; planted (plantAlwaysZoom): every flight resets the distance",
      async run() {
        const fixtures = await serveFixtures();
        const page = fixtures.origin + "/practice_rows.html";
        try {
          const arm = (planted) => evaluate(`(async () => {
            ${PREP}
            const PAGE = ${JSON.stringify(page)};
            const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
            const wc = window.require("@electron/remote").webContents.fromId(b.webview.getWebContentsId());
            v.plantAlwaysZoom = ${planted};
            try {
              try { b.setLive(true); } catch (e) {}
              await land(PAGE, 30000);
              for (let i = 0; i < 90 && !(b.pipebox.map.url === PAGE && b.pipebox.map.chunks > 0); i++) await sleep(500);
              await b.webview.executeJavaScript("window.scrollTo(0,0); 1");
              await sleep(600);
              const pts = JSON.parse(await b.webview.executeJavaScript("(function(){var h=window.__domvecSensor;var a=[];for(var y=40;y<innerHeight-30;y+=30)for(var x=40;x<Math.min(innerWidth,760);x+=90){var st=document.elementsFromPoint(x,y),bb=null,ba=Infinity;for(var i=0;i<st.length&&i<12;i++){var c=null;try{c=h.at(st[i]);}catch(e){}if(c&&c.box){var ar=c.box[2]*c.box[3];if(ar>0&&ar<ba){ba=ar;bb=c;}}}if(bb)a.push({x:x,y:y,id:bb.id});}return JSON.stringify(a);})()"));
              let A = null, B = null;
              for (const p of pts) { const st = b.storedCidFor("f:" + b.session + "#" + p.id, b.session); if (!st) continue; if (!A) A = { ...p, st }; else if (st !== A.st) { B = { ...p, st }; break; } }
              if (!A || !B) return { planted: ${planted}, error: "two stored chunks under the pointer not found" };
              v.zoomState = { zoomedFor: "", zoomedAt: -1e9 };
              const g = v.graph, dist = () => { const c = g.camera().position, t = g.controls().target; return Math.hypot(c.x - t.x, c.y - t.y, c.z - t.z); };
              const f0 = { ...v.focusStats };
              wc.sendInputEvent({ type: "mouseMove", x: A.x, y: A.y }); await sleep(30); wc.sendInputEvent({ type: "mouseMove", x: A.x + 1, y: A.y });
              await sleep(1500);
              const d0 = dist();
              // The reader zooms out: three times as far along the view.
              const c = g.camera().position, t = g.controls().target;
              g.cameraPosition({ x: t.x + (c.x - t.x) * 3, y: t.y + (c.y - t.y) * 3, z: t.z + (c.z - t.z) * 3 }, { x: t.x, y: t.y, z: t.z }, 0);
              await sleep(400);
              const dUser = dist();
              wc.sendInputEvent({ type: "mouseMove", x: B.x, y: B.y }); await sleep(30); wc.sendInputEvent({ type: "mouseMove", x: B.x + 1, y: B.y });
              await sleep(1500);
              const d1 = dist();
              return { planted: ${planted}, flown: v.focusStats.flown - f0.flown, zoomed: v.focusStats.zoomed - f0.zoomed,
                       kept: v.focusStats.kept_zoom - f0.kept_zoom, d_first: Math.round(d0), d_user: Math.round(dUser), d_after: Math.round(d1) };
            } finally { v.plantAlwaysZoom = false; }
          })()`, { timeout: 150000 });
          const clean = await arm(false);
          const planted = await arm(true);
          const kept = (x) => x.d_user > 0 && Math.abs(x.d_after - x.d_user) / x.d_user < 0.15;
          return { pass: !clean.error && clean.flown >= 2 && clean.zoomed === 1 && kept(clean) && !planted.error && !kept(planted),
                   evidence: { clean, planted, purged: await tidyFixtures(fixtures.origin),
                               bar: "clean: two flights, one zoom, the second keeps the reader's distance within 15%; planted: the distance resets" } };
        } finally { await fixtures.close(); }
      },
    },
    {
      id: "G-132",
      asks: "a picture keeps its aspect ratio in the page form at a panel narrower than the page drew it (700x200, object-fit cover)",
      async run() {
        const fixtures = await serveFixtures();
        const page = fixtures.origin + "/practice_rows.html";
        try {
          const got = await evaluate(`(async () => {
            ${PREP}
            const PAGE = ${JSON.stringify(page)};
            const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
            try { b.setLive(true); } catch (e) {}
            await land(PAGE, 30000);
            for (let i = 0; i < 90 && !(b.pipebox.map.url === PAGE && b.pipebox.map.chunks > 0); i++) await sleep(500);
            const cids = await v.sidecar.pageCids(PAGE);
            let pick = null;
            for (const c of cids) { const p = await v.chunkPayload(c); const md = p && p.lines ? p.lines.map((l) => l.text).join(" ") : ""; if (/practice_hero|hero picture/.test(md)) { pick = c; break; } }
            if (!pick) return { error: "no stored chunk holds the hero picture", stored: cids.length };
            for (const bb of v.billboardState()) v.closeBillboard(bb.id);
            let n = v.graph.graphData().nodes.find((x) => x.id === pick);
            if (!n) { const got = await v.sidecar.place([pick]); if (got && got.nodes) v.absorb(got.nodes, got.edges); n = v.graph.graphData().nodes.find((x) => x.id === pick); }
            if (!n) return { error: "not placeable" };
            await v.openBillboard(n);
            await sleep(3500);
            const e = v.billboards.get(pick);
            if (e && e.form !== "page") await v.switchForm(e, "page");
            await sleep(1500);
            const f = e && e.el.querySelector("iframe.domvec-snapshot");
            const img = f && f.contentDocument ? [...f.contentDocument.images].find((i) => /practice_hero/.test(i.src)) : null;
            const r = img ? img.getBoundingClientRect() : null;
            const out = { form: e ? e.form : null, panel_w: f ? f.clientWidth : null, img: r ? [Math.round(r.width), Math.round(r.height)] : null,
                          ratio: r && r.height ? Math.round(r.width / r.height * 100) / 100 : null };
            v.closeBillboard(pick);
            return out;
          })()`, { timeout: 150000 });
          // Non-vacuity is the PRECONDITION: the panel is narrower than the
          // 700 px the page drew, so a fixed height under max-width would
          // squeeze it (the defect: ratio 1.6 at a 320 px panel).
          return { pass: !got.error && got.panel_w !== null && got.panel_w < 700 && got.ratio !== null && Math.abs(got.ratio - 3.5) / 3.5 < 0.06,
                   evidence: { ...got, page_ratio: 3.5, purged: await tidyFixtures(fixtures.origin) } };
        } finally { await fixtures.close(); }
      },
    },
    {
      id: "G-142",
      asks: "with the sensor's merge variant, every member of a re-rendered field list longer than the budget resolves to its merged chunk (at), stable across folds; planted (unseenmerged): the sweep untracks the merged run and its members resolve to nothing",
      async run() {
        const fixtures = await serveFixtures();
        const page = fixtures.origin + "/field_list.html";
        try {
          const arm = (planted) => evaluate(`(async () => {
            const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
            const v = app.workspace.getLeavesOfType("domvec-browser-view")[0].view;
            const src = (await v.sidecar.sensor()).source;
            const { BrowserWindow } = window.require("@electron/remote");
            const w = new BrowserWindow({ show: false, width: 1200, height: 900 });
            try {
              await w.loadURL(${JSON.stringify(page)});
              await sleep(900);                          // past the page's own re-render
              const wc = w.webContents;
              const variants = ${planted} ? "{merge:true,semantic:true,unseenmerged:true}" : "{merge:true,semantic:true}";
              await wc.executeJavaScriptInIsolatedWorld(1036, [{ code: "(function(){window.__g142=(" + src + ")({known:[],variants:" + variants + "});return 1;})()" }]);
              await sleep(600);
              const ask = "JSON.stringify((function(){var h=window.__g142;h.drain();var out=[];document.querySelectorAll('#meta dt, #meta dd').forEach(function(e){var c=null;try{c=h.at(e);}catch(z){}out.push(c?c.id:null);});return out;})())";
              const first = JSON.parse(await wc.executeJavaScriptInIsolatedWorld(1036, [{ code: ask }]));
              await sleep(800);
              const second = JSON.parse(await wc.executeJavaScriptInIsolatedWorld(1036, [{ code: ask }]));
              return { planted: ${planted}, first, second };
            } finally { w.destroy(); }
          })()`, { timeout: 90000 });
          const clean = await arm(false);
          const planted = await arm(true);
          const resolved = (x) => x.second.filter((i) => i !== null).length;
          const units = (x) => new Set(x.second.filter((i) => i !== null)).size;
          // A list longer than the budget is SEVERAL merged units, never one
          // per field: at most a quarter as many units as members.
          const ok = (x) => resolved(x) === x.second.length && units(x) <= Math.ceil(x.second.length / 4)
            && JSON.stringify(x.first) === JSON.stringify(x.second);
          return { pass: ok(clean) && resolved(planted) < planted.second.length / 2,
                   evidence: { clean, planted, members: clean.second.length,
                               bar: "clean: every field resolves, at most a quarter as many units as fields, the same across two folds; planted: fewer than half resolve" } };
        } finally { await fixtures.close(); }
      },
    },
    {
      id: "G-107",
      asks: "the 3D view draws every node and edge it holds in a bounded number of draw calls, each at the size the collider reserves, and the pointer still picks each node",
      async run() {
        // The check makes its own scale: a fresh store holds ~90 nodes, and
        // the claim is about the forum, where one open page drew 2,467. It
        // lands /latest (the page the render cost was measured on) and
        // scrolls it, so stored and streaming nodes are both in the graph.
        //
        // Then three arms on that one graph: the scene batch; the per-node
        // objects and per-link cylinders it replaced (planted -- must fail
        // the draw-call bar); and pick proxies the raycaster cannot hit
        // (planted -- must fail picking). Frame GAPS are reported, never
        // judged: a background window is throttled to ~1 Hz whatever is
        // drawn. The render call's own CPU time is what draw calls cost.
        const got = await evaluate(`(async () => {
          ${PREP}
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
          const target = "https://discourse.julialang.org/latest?g107=" + Date.now();
          const landed = await land(target, 30000);
          await sleep(6000);
          const r0 = b.webview.getBoundingClientRect();
          for (let i = 0; i < 12; i++) {
            b.webview.sendInputEvent({ type: "mouseWheel", x: Math.round(r0.width / 2), y: Math.round(r0.height / 2), deltaX: 0, deltaY: -900 });
            await sleep(700);
          }
          await sleep(12000);
          const g = v.graph, el = g.renderer().domElement;
          const arm = async (plant) => {
            v.plantNoPick = plant === "no-pick";
            v.setPerNode(plant === "per-node");
            try {
              await sleep(7000);
              const stats = v.renderStats();
              // Instances and nodes read in ONE turn, so neither is a frame
              // older than the other (the graph grows while the forum streams).
              const synced = v.batchSync();
              const d = g.graphData();
              const finite = d.nodes.filter((n) => Number.isFinite(n.x) && Number.isFinite(n.y)).length;
              // Every instance class the batch draws: the glass orbs (the
              // default look since 2026-10-11) are a third, and counting only
              // opaque + translucent read 543 of 792 drawn (2026-10-30).
              const drawn = synced ? synced.opaque + synced.translucent + (synced.glass || 0) : null;
              const streaming = d.nodes.filter((n) => n.force).length;
              // Demand 4: what is drawn is what collides -- the application's
              // own drawnRadius against the size the renderer drew.
              let sized = 0, off = 0;
              // The COLLIDER's own radius, read off the force the simulation
              // runs (safety and margin taken back out) -- not drawnRadiusOf,
              // which since 2026-10-30 IS the drawn size and would compare a
              // function with itself.
              const coll = g.d3Force("collide"), C = v.collider;
              const reserved = (n) => coll && coll.radius ? (coll.radius()(n) - C.margin) / C.safety : v.drawnRadiusOf(n);
              for (const n of d.nodes.filter((n) => !n.force && Number.isFinite(n.x)).slice(0, 800)) {
                const a = v.drawnAs(n), r = reserved(n);
                const drawnR = a.kind === "picture" ? a.half * Math.SQRT2 : a.half;
                sized++;
                if (Math.abs(drawnR - r) > 1e-6 * Math.max(1, r)) off++;
              }
              // Demand 3: a pointer over a node names THAT node, through the
              // graph's own hover path (the tooltip it writes a frame later).
              const cam = g.camera(), box = el.getBoundingClientRect();
              const label = g.nodeLabel();
              const text = (h) => { const e = document.createElement("div"); e.innerHTML = h; return (e.textContent || "").trim(); };
              const cands = [];
              for (const n of d.nodes.filter((n) => !n.force && n.__threeObj && Number.isFinite(n.x))) {
                const V3 = n.__threeObj.position.constructor;
                const p = new V3(n.x, n.y, n.z || 0).project(cam);
                if (Math.abs(p.x) > 0.9 || Math.abs(p.y) > 0.9 || p.z > 1) continue;
                cands.push({ n, sx: box.left + (p.x + 1) / 2 * box.width, sy: box.top + (1 - p.y) / 2 * box.height, z: p.z });
              }
              cands.sort((a, c) => a.z - c.z);
              let asked = 0, hit = 0;
              const misses = [];
              for (const c of cands.slice(0, 10)) {
                asked++;
                el.dispatchEvent(new PointerEvent("pointermove", { clientX: c.sx, clientY: c.sy, bubbles: true, pointerType: "mouse" }));
                await sleep(1300);
                const want = text(typeof label === "function" ? label(c.n) : String(c.n.name || ""));
                const tips = [...document.querySelectorAll(".float-tooltip-kap, .scene-tooltip, .graph-tooltip")].map((e) => (e.textContent || "").trim());
                if (want && tips.some((t) => t === want)) hit++;
                else misses.push({ want: want.slice(0, 50), got: tips.filter(Boolean).map((t) => t.slice(0, 50)) });
              }
              el.dispatchEvent(new PointerEvent("pointermove", { clientX: box.left + 2, clientY: box.top + 2, bubbles: true, pointerType: "mouse" }));
              return { planted: plant || false, stats, nodes: d.nodes.length, finite, streaming, drawn_instances: drawn,
                       sized, size_off: off, pick: { asked, hit, misses: misses.slice(0, 3) } };
            } finally {
              v.plantNoPick = false;
              v.setPerNode(false);
            }
          };
          const clean = await arm(false);
          const perNode = await arm("per-node");
          const noPick = await arm("no-pick");
          return { landed, url: b.webview.getURL(), clean, per_node: perNode, no_pick: noPick };
        })()`, { timeout: 300000 });
        if (!got || got.error) return { pass: false, evidence: got };
        const { clean, per_node: perNode, no_pick: noPick } = got;
        const draws = (x) => !!x.stats && x.stats.draw_calls_p50 != null && x.stats.draw_calls_p50 <= 10;
        const picks = (x) => !!x.pick && x.pick.asked >= 5 && x.pick.hit >= Math.ceil(x.pick.asked * 0.7);
        // A floor, not a scale claim: what shows the bound is the planted arm
        // paying at least one call per node on the SAME graph while the batch
        // pays two. (The 2,467-node figure is the working store's, in L5.)
        const ok = (x) => x.finite >= 150 && draws(x) && x.drawn_instances === x.finite
          && x.sized > 0 && x.size_off === 0 && picks(x);
        const scales = (x) => !!x.stats && x.stats.draw_calls_p50 >= x.finite;
        return {
          pass: ok(clean) && !draws(perNode) && scales(perNode) && !picks(noPick)
            && clean.pick.hit >= perNode.pick.hit - 1,
          evidence: got,
        };
      },
    },
    {
      id: "G-81",
      asks: "url-level nodes show their site's icon or a picture, and chunks that hold a picture show one -- loaded, on the node",
      async run() {
        const arm = (planted) => evaluate(`(async () => {
          ${PREP}
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
          v.plantNoIcons = ${planted};
          try {
            // Pages the fresh store holds, browsed so their icons are reported.
            for (const u of ["https://en.wikipedia.org/wiki/Trie", "https://books.toscrape.com/", "https://en.wikipedia.org/wiki/B-tree"]) {
              await land(u, 25000); await sleep(2500);
            }
            // Redraw the picture from the store (a fresh layout builds every node).
            const btn = [...document.querySelectorAll("button")].find((x) => (x.textContent || "").trim() === "pages");
            if (btn) { btn.click(); await sleep(600); btn.click(); }
            await sleep(8000);
            const ns = v.graph.graphData().nodes.filter((n) => !n.force);
            const web = (n) => /^https?:/.test(n.url || "") && !/127\.0\.0\.1|localhost/.test(n.url || "");
            const pages = ns.filter((n) => n.level === "page" && web(n));
            const chunksWithPic = ns.filter((n) => n.level !== "page" && n.image && n.image.src);
            return { planted: ${planted}, pages: pages.length,
                     pages_with_image: pages.filter((n) => n.image && n.image.src).length,
                     pages_image_loaded: pages.filter((n) => n.imgLoaded).length,
                     chunks_with_picture: chunksWithPic.length,
                     chunks_picture_loaded: chunksWithPic.filter((n) => n.imgLoaded).length,
                     missing: pages.filter((n) => !n.imgLoaded).map((n) => n.url).slice(0, 8) };
          } finally {
            v.plantNoIcons = false;
          }
        })()`, { timeout: 180000 });
        const clean = await arm(false);
        const planted = await arm(true);
        const ok = (x) => x.pages > 0 && x.pages_image_loaded >= Math.ceil(x.pages * 0.8)
          && (x.chunks_with_picture === 0 || x.chunks_picture_loaded >= Math.ceil(x.chunks_with_picture * 0.8));
        // The chunk half: a chunk that holds a picture is DRAWN as it, and
        // opens to the whole chunk. It makes its own state -- a fresh store
        // draws pages only, so it unfolds pages until a chunk with a picture
        // is on screen -- and its plant is the renderer ignoring chunk
        // pictures (the node keeps its image; nothing draws it).
        const chunkArm = (planted) => evaluate(`(async () => {
          ${PREP}
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
          v.plantNoPicture = ${planted};
          try {
            const pics = () => v.graph.graphData().nodes.filter((n) => n.level !== "page" && !n.force && n.image && n.image.src);
            const pages = v.graph.graphData().nodes.filter((n) => n.level === "page" && !n.force);
            pages.sort((x, y) => (/books|harbour|catalogue/i.test((y.url || "") + (y.name || "")) ? 1 : 0)
                               - (/books|harbour|catalogue/i.test((x.url || "") + (x.name || "")) ? 1 : 0));
            const tried = [];
            for (const p of pages.slice(0, 6)) {
              if (pics().length) break;
              tried.push(p.url);
              await v.unfoldNode(p);
              await sleep(4000);
            }
            const withPic = pics();
            if (!withPic.length) return { planted: ${planted}, error: "no chunk node with a picture is drawn", tried };
            await sleep(4000);             // pictures decode into the atlas
            const sample = withPic.slice(0, 40);
            const drawn = sample.filter((n) => v.drawnAs(n).kind === "picture").length;
            const node = withPic[0];
            for (const bb of v.billboardState()) v.closeBillboard(bb.id);
            await v.openBillboard(node);
            await sleep(3000);
            // What the panel SHOWS, in whichever form it opened: the page form's
            // frame, or the markdown Obsidian rendered. The shadow-DOM host this
            // read until 2026-10-07 was retired with the form switch
            // (2026-10-06: "rather than having this switching between markdown
            // and 'shadow DOM'"), and read 0 elements from a panel showing 40.
            const bb = v.containerEl.querySelector('.domvec-bb[data-cid="' + node.id + '"]');
            const frame = bb && bb.querySelector("iframe.domvec-snapshot");
            const fdoc = frame && frame.contentDocument;
            const root = fdoc ? fdoc.body : (bb && bb.querySelector(".domvec-bb-body"));
            const out = { planted: ${planted}, tried, node: node.id, with_picture: sample.length, drawn_as_picture: drawn,
                          panel_form: fdoc ? "page" : (root ? "markdown" : "none"),
                          shadow_elements: root ? root.querySelectorAll("*").length : 0,
                          shadow_images: root ? root.querySelectorAll("img").length : 0 };
            v.closeBillboard(node.id);
            return out;
          } finally {
            v.plantNoPicture = false;
          }
        })()`, { timeout: 120000 });
        const chunkClean = await chunkArm(false);
        const chunkPlanted = await chunkArm(true);
        const chunkOk = (x) => !x.error && x.with_picture > 0 && x.drawn_as_picture >= Math.ceil(x.with_picture * 0.8)
          && x.shadow_elements > 1;
        return { pass: ok(clean) && !ok(planted) && chunkOk(chunkClean) && !chunkOk(chunkPlanted),
                 evidence: { clean, planted, chunk: chunkClean, chunk_planted: chunkPlanted } };
      },
    },
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
          // Since the scene batch (G-107) every link is a segment of ONE
          // LineSegments mesh, not a line object of its own: counting
          // __lineObj read 0 drawn of 23 held (2026-10-07). The application's
          // own sync says how many segments it drew; the per-object count
          // stays for the per-node mode.
          const synced = v.batchSync();
          const lines = synced ? synced.lines
            : after.links.filter(l => l.__lineObj && l.__lineObj.parent && l.__lineObj.visible).length;
          return {
            reset,
            returned_edges: (reply && reply.edges || []).length,
            links_before: linksBefore, links_after: after.links.length,
            nodes_before: nodesBefore, nodes_after: after.nodes.length,
            unresolved, dangling, line_objects_in_scene: lines,
            drawn_by: synced ? "scene batch" : "per-link objects",
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
        // **Where they go is the chunk projector's answer (`G-72`).** This
        // gated on `far <= 120` -- inside the local ball `_local_positions`
        // fitted around the page. Addendum V replaced that layer ("Instead,
        // stream ... to a fitted UMAP projector"), so the claim to check is
        // that an unfolded chunk sits exactly where the projector put it; how
        // far that is from its page is reported, not gated, because it is
        // what the content says rather than a defect.
        const all = await ask("/layout?level=chunk");
        const at = new Map((all.nodes || []).map((n) => [n.cid, n.pos]));
        const chunks = d.nodes.filter((n) => n.level === "chunk" && at.has(n.cid));
        const offProjector = chunks.reduce((m, n) => Math.max(m, Math.hypot(
          n.pos[0] - at.get(n.cid)[0], n.pos[1] - at.get(n.cid)[1],
          n.pos[2] - at.get(n.cid)[2])), 0);
        return {
          pass: d.nodes.length > 0 && d.nodes.length < biggest.members / 4
             // Not piled on the frame.
             && onFrame === 0
             // Placed by the projector, not by a second computation.
             && d.source === "projector" && chunks.length > 0 && offProjector < 1e-3
             // And distinguishable from each other.
             && (pos.length < 2 || closest > 1),
          evidence: {
            page_members: biggest.members,
            opened_to: d.nodes.length,
            edges: (d.edges || []).length,
            depth: d.depth, branches: d.branches, leaves: d.leaves,
            on_the_frame: onFrame,
            source: d.source, chunks_checked: chunks.length,
            off_projector: Math.round(offProjector * 1000) / 1000,
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
          // **The picture this row is a claim about, established here.**
          //
          // "Seeded from the fit, not replacing it" is about the default
          // page-level view. Run against whatever an earlier check left on
          // screen it measured 1,192 chunk nodes under collision, where
          // everything is nudged by construction -- a different population
          // answering a different question.
          const SIDECAR_URL = ${JSON.stringify(SIDECAR)};
          const clean = await (await fetch(
            SIDECAR_URL + "/layout?level=page")).json();
          v.graph.graphData({ nodes: clean.nodes.map(n => v.nodeFrom(n)),
                              links: [] });
          await sleep(1500);

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
            extent: clean.extent || null,
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
          // The SETTLED picture: a freshly built view is sized to its room a
          // moment after it is drawn, and read at once (as this check runs
          // first after a reload) it scored 414 pairs that were gone 2 s later.
          // Waits until the overlap count stops falling, at most 15 s.
          {
            const quick = () => { const ns = v.graph.graphData().nodes.filter((n) => Number.isFinite(n.x) && !n.force).slice(0, 1200); let o = 0; for (let i = 0; i < ns.length; i++) for (let j = i + 1; j < ns.length; j++) { const a = ns[i], b = ns[j]; if (Math.hypot(a.x-b.x, a.y-b.y, a.z-b.z) < v.drawnRadiusOf(a) + v.drawnRadiusOf(b)) o++; } return o; };
            let last = quick();
            for (let i = 0; i < 15; i++) { await sleep(1000); const now = quick(); if (now >= last && i >= 2) break; last = now; }
          }
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
          // And the pane's own function where it has one: pictures are sized
          // by the media mode now, which the hand-kept formula above does not
          // know (it read 183 overlaps, every one of them a picture,
          // 2026-10-07). The formula stays only for a pane without it.
          const radius = (n) => v.drawnRadiusOf ? v.drawnRadiusOf(n)
            : (n.image && n.image.src) ? sphereOf(n) * PANEL_GAIN : sphereOf(n);
          // Projected nodes only: streaming (force) nodes are drawn as their
          // own small translucent spheres and spaced by G-93's rule, not by
          // this collider.
          const ns = d.nodes.filter(n => Number.isFinite(n.x) && !n.force);
          const sample = ns.slice(0, 1200);
          const C = v.collider || { safety: 1.25, margin: 0 };
          let pairs = 0, worst = 0, panels = 0, inBand = 0;
          for (let i = 0; i < sample.length; i++) {
            for (let j = i + 1; j < sample.length; j++) {
              const a = sample[i], b = sample[j];
              const d = Math.hypot(a.x-b.x, a.y-b.y, a.z-b.z);
              const ra = radius(a), rb = radius(b);
              if (d - ra - rb < 0) {
                pairs++; worst = Math.max(worst, ra + rb - d);
                if ((a.image&&a.image.src)||(b.image&&b.image.src)) panels++;
              } else if (d - (ra + rb) * C.safety - 2 * C.margin < 0) {
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
                   involving_a_panel: panels, inside_clearance_band: inBand,
                   radius_from: v.drawnRadiusOf ? "pane" : "formula" };
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
          // A leaf in a background tab hands back a DEFERRED stub with none of
          // the view's methods on it. Fronting the projector backgrounds the
          // browser cell, so this has to be forced before .view is read --
          // otherwise b.webview is undefined and it reads as no browser pane.
          for (const l of app.workspace.getLeavesOfType("domvec-browser-view")) {
            if (l.loadIfDeferred) await l.loadIfDeferred();
          }
          for (const l of app.workspace.getLeavesOfType("domvec-graph-view")) {
            if (l.loadIfDeferred) await l.loadIfDeferred();
          }
          // Loaded is not the same as USABLE. loadIfDeferred resolves before
          // the guest emits dom-ready, and every webview method then throws
          // "The WebView must be attached to the DOM and the dom-ready event
          // emitted". Poll the cheapest one until it stops throwing.
          for (let i = 0; i < 80; i++) {
            const l0 = app.workspace.getLeavesOfType("domvec-browser-view")[0];
            const w = l0 && l0.view && l0.view.webview;
            if (!w) break;
            try { w.getURL(); break; } catch (e) { await sleep(250); }
          }
          // And usable is still not VISIBLE. A leaf in a background tab has no
          // layout, so the guest reports innerWidth/innerHeight of 0 and every
          // click coordinate computed from a rect is meaningless -- the aim
          // came out at (15, 319) in a 0x0 viewport and read as the link not
          // being followed. Front the cell and wait for it to have a size.
          {
            const l0 = app.workspace.getLeavesOfType("domvec-browser-view")[0];
            if (l0) {
              app.workspace.revealLeaf(l0);
              for (let i = 0; i < 60; i++) {
                await sleep(250);
                try {
                  const size = await l0.view.webview.executeJavaScript(
                    "[window.innerWidth, window.innerHeight]");
                  if (size && size[0] > 50 && size[1] > 50) break;
                } catch (e) { /* not ready yet */ }
              }
            }
          }
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
      asks: "right-click is the browser's menu; DOUBLE right-click puts the markdown beside the page and rings the node",
      async run() {
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise(r => setTimeout(r, ms));
          await app.commands.executeCommandById("domvec-open-browser");
          await app.commands.executeCommandById("domvec-open-graph");
          await sleep(2000);
          // A leaf in a background tab hands back a DEFERRED stub with none of
          // the view's methods on it. Fronting the projector backgrounds the
          // browser cell, so this has to be forced before .view is read --
          // otherwise b.webview is undefined and it reads as no browser pane.
          for (const l of app.workspace.getLeavesOfType("domvec-browser-view")) {
            if (l.loadIfDeferred) await l.loadIfDeferred();
          }
          for (const l of app.workspace.getLeavesOfType("domvec-graph-view")) {
            if (l.loadIfDeferred) await l.loadIfDeferred();
          }
          // Loaded is not the same as USABLE. loadIfDeferred resolves before
          // the guest emits dom-ready, and every webview method then throws
          // "The WebView must be attached to the DOM and the dom-ready event
          // emitted". Poll the cheapest one until it stops throwing.
          for (let i = 0; i < 80; i++) {
            const l0 = app.workspace.getLeavesOfType("domvec-browser-view")[0];
            const w = l0 && l0.view && l0.view.webview;
            if (!w) break;
            try { w.getURL(); break; } catch (e) { await sleep(250); }
          }
          // And usable is still not VISIBLE. A leaf in a background tab has no
          // layout, so the guest reports innerWidth/innerHeight of 0 and every
          // click coordinate computed from a rect is meaningless -- the aim
          // came out at (15, 319) in a 0x0 viewport and read as the link not
          // being followed. Front the cell and wait for it to have a size.
          {
            const l0 = app.workspace.getLeavesOfType("domvec-browser-view")[0];
            if (l0) {
              app.workspace.revealLeaf(l0);
              for (let i = 0; i < 60; i++) {
                await sleep(250);
                try {
                  const size = await l0.view.webview.executeJavaScript(
                    "[window.innerWidth, window.innerHeight]");
                  if (size && size[0] > 50 && size[1] > 50) break;
                } catch (e) { /* not ready yet */ }
              }
            }
          }
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
          // Into view FIRST, then SETTLE, then read the rect.
          //
          // elementFromPoint answers null outside the viewport, which is a
          // position a real right-click cannot be made from. But reading the
          // rect in the same call as the scroll reads it BEFORE the scroll has
          // applied: with the cell left at scrollY 5000 by an earlier check,
          // this pointed at y=-5359 and reported "nothing under the cursor" --
          // a check blaming the feature for its own arithmetic.
          const SEL = "article.product_pod h3 a";
          await b.webview.executeJavaScript(
            "(function(){var e=document.querySelector('" + SEL + "');" +
            "if(e) e.scrollIntoView({block:'center',behavior:'instant'});" +
            "return true;})()");
          let at = null;
          for (let i = 0; i < 20; i++) {
            await sleep(250);
            at = await b.webview.executeJavaScript(
              "(function(){var e=document.querySelector('" + SEL + "');" +
              "if(!e) return null;" +
              "var r=e.getBoundingClientRect();" +
              "return {x:Math.round(r.left+r.width/2)," +
              "y:Math.round(r.top+r.height/2)," +
              "vw:window.innerWidth, vh:window.innerHeight," +
              "text:(e.textContent||'').slice(0,40)};})()");
            if (at && at.y >= 0 && at.y < at.vh && at.x >= 0 && at.x < at.vw) break;
          }
          if (!at) return { error: "the page has no product link to point at" };
          if (!(at.y >= 0 && at.y < at.vh && at.x >= 0 && at.x < at.vw)) {
            return { error: "the aim never came on screen", at };
          }
          // A REAL right-click, through the webview's own context-menu
          // event -- not a call to the handler with page coordinates, which
          // skipped the one step that was broken: the event reports the
          // point in window coordinates, and every right-click missed the
          // page while this check passed (2026-09-26).
          //
          // Two arms (2026-09-26: a DOUBLE right-click pins; a single one is
          // the browser's own menu). The single arm must open the menu with
          // the link's items and pin nothing.
          const rclick = () => {
            b.webview.sendInputEvent({ type: "mouseDown", x: at.x, y: at.y, button: "right", clickCount: 1 });
            b.webview.sendInputEvent({ type: "mouseUp", x: at.x, y: at.y, button: "right", clickCount: 1 });
          };
          // Loaded and focused first: a right-click sent while the guest is
          // still loading produced no context-menu event at all (a run on
          // 2026-09-26 read gesture "" with the page title still arriving).
          for (let i = 0; i < 40 && b.webview.isLoading(); i++) await sleep(250);
          // The browser leaf ACTIVE, not just its webview focused: with the
          // graph pane active the guest received no context-menu event at all.
          // And REVEALED: when the browser and the graph share a tab group
          // (a fresh run's layout), opening the graph last hides the browser,
          // and a hidden webview raises no context-menu event at all.
          const bl = app.workspace.getLeavesOfType("domvec-browser-view")[0];
          try { app.workspace.revealLeaf(bl); } catch (e) {}
          try { app.workspace.setActiveLeaf(bl, { focus: true }); } catch (e) {}
          await sleep(300);
          b.webview.focus();
          await sleep(200);
          const pinsBefore = b.pinnedState().length;
          b.lastGesture = "";
          rclick();
          // Waited FOR, not slept: under a fresh run's load the context-menu
          // event arrived after a fixed 0.9 s look and read as no event.
          for (let i = 0; i < 25 && !b.lastGesture; i++) await sleep(200);
          // Retried once, and SAID: a right-click that needs a second try is
          // a finding, not something to absorb silently.
          let rclickRetried = false;
          if (!b.lastGesture) {
            rclickRetried = true; b.webview.focus(); rclick();
            for (let i = 0; i < 25 && !b.lastGesture; i++) await sleep(200);
          }
          const single = { gesture: b.lastGesture, items: b.lastMenu.slice(), retried: rclickRetried,
                           menu_shown: !!document.querySelector(".menu"),
                           pinned: b.pinnedState().length - pinsBefore };
          document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }));
          document.querySelectorAll(".menu").forEach((m) => m.remove());
          await sleep(300);
          b.lastGesture = "";
          rclick();
          await sleep(120);
          rclick();
          for (let i = 0; i < 25 && b.lastGesture !== "pin"; i++) await sleep(200);
          // The ring, read as soon as the pin lands: the hover poll moves it
          // to whatever the pointer is over a moment later.
          let ringedAtPin = 0;
          for (let i = 0; i < 20 && !ringedAtPin; i++) {
            await sleep(100);
            const gv0 = app.workspace.getLeavesOfType("domvec-graph-view")[0];
            const g0 = gv0 && gv0.view && gv0.view.graph;
            ringedAtPin = g0 ? g0.graphData().nodes.filter((n) => n.hovered).length : 0;
          }
          await sleep(1200);
          const body = b.markdownWrap.querySelector(".domvec-browser-mdbody");
          const head = b.markdownWrap.querySelector(".domvec-browser-mdhead");
          // Let late input land, then let go of what this check pinned: a
          // right-click delivered after the check ended pinned chunks of the
          // NEXT check's page.
          await sleep(1500);
          const heldPins = b.pinnedState().length;
          return {
            held_pins_at_end: heldPins,
            pointed_at: at,
            single_right_click: single,
            double_gesture: b.lastGesture,
            // The page stays the surface: it is shown with a real size, and
            // there is no face toggle left to switch it away (G-82).
            page_shown: b.browserWrap.offsetWidth > 50 && b.browserWrap.offsetHeight > 50,
            face_toggle: [...b.containerEl.querySelectorAll(".domvec-browser-bar button")]
              .some((e) => /^(markdown|browser)$/.test((e.textContent || "").trim())),
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
            ringed: Math.max(ringedAtPin, v ? v.graph.graphData().nodes.filter(n => n.hovered).length : 0),
            ringed_level: v
              ? (v.graph.graphData().nodes.find(n => n.hovered) || {}).level || null
              : null,
          };
        })()`);
        if (got.error) return { pass: false, evidence: got };
        return {
          // Resolved to an address and produced RENDERED markdown -- not a
          // placeholder and not a blob of source text -- BESIDE the page.
          //
          // The face must NOT switch. This asked for face === "markdown"
          // until 2026-09-26, which is Addendum IV's "switchable second
          // view"; Addendum VII's follow-up replaced that with a side panel
          // ("the browser stays the main surface"), and right-click now pins
          // (G-78) with the page left showing. Scored the old way, a correct
          // app failed with rendered markdown and one ring in its evidence.
          pass: got.single_right_click && got.single_right_click.gesture === "menu"
             && got.single_right_click.menu_shown === true
             && got.single_right_click.items.includes("Open link in new tab")
             && got.single_right_click.pinned === 0
             && got.double_gesture === "pin"
             && got.page_shown === true && got.face_toggle === false
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
        // **The query is CHOSEN from the store**, a few words from each of
        // three pages, so the global ranking can span pages at all. It was
        // the literal "header", which a fresh store seeded with pages about
        // trees and tables does not contain: zero hits, reported as "spanned
        // one page" -- the fourth guessed query to read as a broken feature.
        const layout = await ask("/layout?level=chunk");
        const byUrl = new Map();
        for (const n of layout.nodes || []) {
          const w = String(n.title || "").match(/[A-Za-z][A-Za-z-]{4,}/g) || [];
          if (n.url && w.length >= 2 && !byUrl.has(n.url)) byUrl.set(n.url, w.slice(0, 2));
          if (byUrl.size >= 3) break;
        }
        const q = encodeURIComponent([...byUrl.values()].flat().join(" "));
        const global_ = await ask(`/search?q=${q}&k=20`);
        const urls = [...new Set((global_.hits || []).map((h) => h.url))];
        if (urls.length < 2) {
          return { pass: false, evidence: { why: "global ranking spanned one page",
                                            query: decodeURIComponent(q), urls } };
        }
        const scoped = await ask(
          `/search?q=${q}&k=20&url=${encodeURIComponent(urls[0])}`);
        const scopedUrls = [...new Set((scoped.hits || []).map((h) => h.url))];
        return {
          // Scoped to exactly one page, and it returns SOMETHING -- an empty
          // scoped result would satisfy "only that url" vacuously, which is
          // the shape this defect actually took once before.
          pass: (scoped.hits || []).length > 0
             && scopedUrls.length === 1 && scopedUrls[0] === urls[0],
          evidence: {
            query: decodeURIComponent(q),
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
        // The biggest group with WORDS to ask about. The biggest group alone
        // was a row of book covers on a fresh store -- a lead with no text
        // -- and the check reported that as a ranking failure. Which group is
        // asked about is the check's choice; the claim is about the ranking.
        let lead = null, words = [], tried = 0;
        for (const g of groups.slice(0, 12)) {
          tried++;
          const chunk = await ask(`/chunk/${encodeURIComponent(g.cid)}`);
          // LINK-FREE text, the string the index was built from: words
          // taken from link targets ("ref-aho" out of a citation anchor)
          // are not in the lexical index, so asking for them measured a
          // query nothing could answer, not the ranking.
          const text = (chunk.lines || []).map((l) => l.text).join(" ")
            .replace(/\]\([^)]*\)/g, "]").replace(/<[^>]*>/g, " ");
          const w = [...new Set(text.match(/[A-Za-z][A-Za-z-]{4,}/g) || [])].slice(0, 6);
          if (w.length >= 2) { lead = g; words = w; break; }
        }
        if (!lead) {
          return { pass: false, evidence: { why: "no group's lead has words",
                                            groups_tried: tried } };
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
          // A leaf in a background tab hands back a DEFERRED stub with none of
          // the view's methods on it. Fronting the projector backgrounds the
          // browser cell, so this has to be forced before .view is read --
          // otherwise b.webview is undefined and it reads as no browser pane.
          for (const l of app.workspace.getLeavesOfType("domvec-browser-view")) {
            if (l.loadIfDeferred) await l.loadIfDeferred();
          }
          for (const l of app.workspace.getLeavesOfType("domvec-graph-view")) {
            if (l.loadIfDeferred) await l.loadIfDeferred();
          }
          // Loaded is not the same as USABLE. loadIfDeferred resolves before
          // the guest emits dom-ready, and every webview method then throws
          // "The WebView must be attached to the DOM and the dom-ready event
          // emitted". Poll the cheapest one until it stops throwing.
          for (let i = 0; i < 80; i++) {
            const l0 = app.workspace.getLeavesOfType("domvec-browser-view")[0];
            const w = l0 && l0.view && l0.view.webview;
            if (!w) break;
            try { w.getURL(); break; } catch (e) { await sleep(250); }
          }
          // And usable is still not VISIBLE. A leaf in a background tab has no
          // layout, so the guest reports innerWidth/innerHeight of 0 and every
          // click coordinate computed from a rect is meaningless -- the aim
          // came out at (15, 319) in a 0x0 viewport and read as the link not
          // being followed. Front the cell and wait for it to have a size.
          {
            const l0 = app.workspace.getLeavesOfType("domvec-browser-view")[0];
            if (l0) {
              app.workspace.revealLeaf(l0);
              for (let i = 0; i < 60; i++) {
                await sleep(250);
                try {
                  const size = await l0.view.webview.executeJavaScript(
                    "[window.innerWidth, window.innerHeight]");
                  if (size && size[0] > 50 && size[1] > 50) break;
                } catch (e) { /* not ready yet */ }
              }
            }
          }
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
      asks: "every node is on screen at the default camera (2026-10-30: at BOTH levels -- the row was Partly because the check only ever saw the level that happened to be open; planted plantFrameBulk, a frame fitted to the median offset per axis instead of the extremes, puts nodes off screen and is caught)",
      async run() {
        const got = await inPane(`
          for (let i = 0; i < 60 && !(v.graph && v.graph.graphData().nodes.length); i++) await sleep(500);
          // Projected into normalised device coordinates: |x|,|y| <= 1 and
          // w > 0 is "inside the frustum". Counting nodes rather than
          // trusting the framing arithmetic that put them there.
          const census = () => {
            const cam = v.graph.camera();
            cam.updateMatrixWorld();
            const m = cam.projectionMatrix.clone().multiply(cam.matrixWorldInverse);
            const e = m.elements;
            const ns = v.graph.graphData().nodes.filter((n) => Number.isFinite(n.x));
            let onScreen = 0, behind = 0;
            for (const n of ns) {
              const x = n.x, y = n.y, z = n.z || 0;
              const cw = e[3]*x + e[7]*y + e[11]*z + e[15];
              if (cw <= 0) { behind++; continue; }
              const cx = (e[0]*x + e[4]*y + e[8]*z + e[12]) / cw;
              const cy = (e[1]*x + e[5]*y + e[9]*z + e[13]) / cw;
              if (Math.abs(cx) <= 1 && Math.abs(cy) <= 1) onScreen++;
            }
            const el = v.graph.renderer().domElement;
            return { level: v.level || "pages", nodes: ns.length, onScreen, behind,
                     pane: [el.clientWidth, el.clientHeight], dist: Math.round(v.fullViewDist) };
          };
          const toggle = () => [...v.contentEl.querySelectorAll("button")].find((x) => x.textContent === (v.level === "chunk" ? "chunks" : "pages"))?.click();
          const reframe = async () => { v.reframe(); await sleep(1500); };
          const out = {};
          try {
            if (v.level === "chunk") { toggle(); await sleep(6000); }
            await reframe();
            out.pages = census();
            // The planted arm: framing the bulk puts the outer nodes off screen.
            v.plantFrameBulk = true;
            await reframe();
            out.planted = census();
            v.plantFrameBulk = false;
            await reframe();
            toggle();
            for (let i = 0; i < 120; i++) { await sleep(500); if (v.level === "chunk" && v.graph && v.graph.graphData().nodes.length > 50) break; }
            await sleep(9000);
            await reframe();
            out.chunk = census();
          } finally {
            v.plantFrameBulk = false;
            await reframe();
            if (v.level === "chunk") { toggle(); await sleep(6000); }
          }
          return out;
        `);
        if (got.error) return { pass: false, evidence: got };
        const all = (c) => c && c.nodes > 0 && c.onScreen === c.nodes && c.behind === 0;
        return {
          pass: all(got.pages) && all(got.chunk) && !!got.planted && got.planted.onScreen < got.planted.nodes,
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
          //
          // **Measured in pixels, not as a CSS string, and moved decisively.**
          // The old move was x*0.6+40, y+30, z*0.6: with the camera
          // near the origin that is a small nudge, and a billboard whose node
          // sits near the centre of the screen can project to the same
          // rounded left either side of it. The check then read "the
          // billboard does not follow the camera" from a camera that had
          // barely moved. Orbit a long way instead and require real pixels.
          const px = () => [parseFloat(el.style.left) || 0,
                            parseFloat(el.style.top) || 0];
          const before = px();
          const cam = v.graph.cameraPosition();
          const dist = Math.hypot(cam.x, cam.y, cam.z) || 300;
          v.graph.cameraPosition(
            { x: cam.z * 0.9 + dist * 0.5, y: cam.y + dist * 0.4,
              z: -cam.x * 0.9 - dist * 0.3 }, undefined, 0);
          await sleep(1200);
          const after = px();
          const movedPx = Math.round(
            Math.hypot(after[0] - before[0], after[1] - before[1]));
          const followed = movedPx > 2;

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
            followed_camera: followed, followed_by_px: movedPx,
            pinned_after_drag: stayed, closed: gone,
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
      asks: "inter-spatial normalization -- nodes are discernible, not a clump (2026-10-30: scored on the DRAWN picture at both levels, at the pane's own radii -- at least 95% of nodes clear of their nearest neighbour's drawn sphere, no two different texts on one point; planted plantNoChunkRelax + plantNoDrawn, the raw UMAP points, is caught)",
      async run() {
        // The verbatim (PLUGIN_GOAL, opening): "inter-spatial normalization on
        // UMAP nodes since most are way too compressed together to see
        // anything discernable". This scored /layout's FIT coordinates against
        // a median neighbour distance of 1 -- a number in fit units with no
        // relation to what is drawn, and it failed at 0.806 while the drawn
        // picture held 0 overlaps (G-21). Discernible is a property of the
        // picture: a node is discernible when its drawn sphere is clear of its
        // nearest neighbour's. In WORLD space, so depth is not conflated
        // (D-25) and the bar holds at every zoom; "most" read as 95%.
        const got = await inPane(`
          const census = () => {
            const ns = v.graph.graphData().nodes.filter((n) => Number.isFinite(n.x) && !n.force);
            const rad = ns.map((n) => v.drawnRadiusOf(n));
            const rs = [...rad].sort((a, b) => a - b);
            if (!rs.length) return { nodes: 0 };
            const cell = Math.max(rs[Math.floor(rs.length * 0.99)] * 4, 1e-3);
            const grid = new Map();
            ns.forEach((n, i) => { const k = Math.floor(n.x / cell) + "," + Math.floor(n.y / cell) + "," + Math.floor(n.z / cell); (grid.get(k) || grid.set(k, []).get(k)).push(i); });
            let clear = 0, touching = 0, coincident = 0;
            const ratio = [];
            ns.forEach((n, i) => {
              const cx = Math.floor(n.x / cell), cy = Math.floor(n.y / cell), cz = Math.floor(n.z / cell);
              let best = Infinity, bj = -1;
              for (let dx = -1; dx <= 1; dx++) for (let dy = -1; dy <= 1; dy++) for (let dz = -1; dz <= 1; dz++)
                for (const j of grid.get((cx + dx) + "," + (cy + dy) + "," + (cz + dz)) || []) {
                  if (j === i) continue;
                  const o = ns[j];
                  const d = Math.hypot(o.x - n.x, o.y - n.y, o.z - n.z);
                  if (d < best) { best = d; bj = j; }
                }
              // Nothing within four of the largest radii: clear by construction.
              if (bj < 0) { clear++; return; }
              if (best < 1e-6) coincident++;
              const r = best / (rad[i] + rad[bj]);
              ratio.push(r);
              if (r >= 1) clear++; else touching++;
            });
            ratio.sort((a, b) => a - b);
            return { level: v.level || "pages", nodes: ns.length, clear, touching, coincident,
                     share: Math.round(clear / ns.length * 1000) / 1000,
                     gap_over_radii_p50: ratio.length ? Math.round(ratio[Math.floor(ratio.length / 2)] * 100) / 100 : null };
          };
          const toggle = () => [...v.contentEl.querySelectorAll("button")].find((x) => x.textContent === (v.level === "chunk" ? "chunks" : "pages"))?.click();
          const toChunk = async () => {
            if (v.level !== "chunk") toggle();
            for (let i = 0; i < 120; i++) { await sleep(500); if (v.level === "chunk" && v.graph && v.graph.graphData().nodes.length > 50) break; }
            await sleep(9000);
          };
          const toPages = async () => { if (v.level === "chunk") toggle(); await sleep(6000); };
          // The SETTLED picture: a rebuilt view glides its nodes to their
          // places for ~8 s, and overlaps come and go while they travel
          // (2026-10-30: 229 -> 712 -> 0 touching at 1.5, 6, 10 s). How long
          // settling took is reported with the verdict.
          const settled = async () => {
            const t0 = performance.now();
            let c = census();
            for (let i = 0; i < 20 && !(c.share >= 0.95); i++) { await sleep(1000); c = census(); }
            c.settle_s = Math.round((performance.now() - t0) / 100) / 10;
            return c;
          };
          const out = {};
          try {
            await toPages();
            out.pages = await settled();
            await toChunk();
            out.chunk = await settled();
            await toPages();
            out.pages_rebuilt = await settled();
            v.plantNoChunkRelax = true; v.plantNoDrawn = true;
            await toChunk();
            out.planted = await settled();
          } finally {
            v.plantNoChunkRelax = false; v.plantNoDrawn = false;
            await toPages();
          }
          return out;
        `);
        if (got.error) return { pass: false, evidence: got };
        // And the fit itself: two DIFFERENT texts at one point are two things
        // drawn as one whatever the relax does (the same text on several
        // pages belongs at one point).
        const d = await ask("/layout?level=chunk");
        const ns = (d.nodes || []).filter((n) => Array.isArray(n.pos)).slice(0, 400);
        let differentText = 0;
        for (let i = 0; i < ns.length; i++) for (let j = i + 1; j < ns.length; j++) {
          const a = ns[i].pos, b = ns[j].pos;
          if (Math.hypot(a[0]-b[0], a[1]-b[1], a[2]-b[2]) < 1e-6
              && String(ns[i].title || "") !== String(ns[j].title || "")) differentText++;
        }
        got.fit_coincident_different_text = differentText;
        const ok = (c) => c && c.nodes > 0 && c.share >= 0.95;
        return {
          pass: ok(got.pages) && ok(got.chunk) && ok(got.pages_rebuilt) && differentText === 0
             && !!got.planted && got.planted.share < got.chunk.share - 0.05,
          evidence: got,
        };
      },
    },
    {
      id: "G-13",
      asks: "re-projection batched in a queue whose latency adapts to the umap updates (2026-10-30: to the ARRIVALS as well as the cost) -- a trickle (a live page's mutations) waits up to one drain's cost and its drains carry more chunks than with no window; a burst (a fresh page) never waits; planted window-always: the burst waits",
      async run() {
        // The verbatim (PLUGIN_GOAL, opening): "Re-projections over umaps can
        // be batched in a queue at a latency that adapts to match the time
        // scaling of the umap updates." A window that waited on every wake
        // was measured on bursts (2026-10-24: 90 -> 95.6 chunks a drain, wait
        // p50 70 -> 314 ms) and switched off. The arrivals were the missing
        // input: a page's chunks come in one burst and are batched already;
        // a live page's mutations come a few at a time, and only there can
        // waiting gather company. Served fixtures, so nothing else streams.
        const fixtures = await serveFixtures();
        const plant = (name, on) => fetch(SIDECAR + "/plant", {
          method: "POST", headers: { "content-type": "application/json", "X-Domvec-Client": "obsidian-plugin" },
          body: JSON.stringify({ name, on }) });
        const batching = async () => (await ask("/projector")).batching;
        const visit = (url, ms) => evaluate(`(async () => {
          ${PREP}
          await land(${JSON.stringify(url)}, 20000);
          await sleep(${ms});
          return b.webview.getURL();
        })()`, { timeout: ms + 60000 });
        const arm = async (flags, url, ms) => {
          for (const [k, on] of Object.entries(flags)) await plant(k, on);
          // Settled first: a backlog (a restart's, the previous arm's tail)
          // drains in 256s and would be scored as this arm's batching.
          for (let i = 0; i < 60; i++) { if (!(await ask("/projector")).queue) break; await new Promise((r) => setTimeout(r, 1000)); }
          await new Promise((r) => setTimeout(r, 3000));
          const s0 = await batching();
          await visit(url, ms);
          const s1 = await batching();
          const drains = s1.drains - s0.drains, batched = s1.batched - s0.batched;
          const fresh = s1.waits_seen - s0.waits_seen;
          const waits = fresh > 0 ? s1.waits_tail.slice(-fresh).sort((a, b) => a - b) : [];
          const q = (p) => waits.length ? waits[Math.min(waits.length - 1, Math.floor(p * waits.length))] : null;
          return { flags, drains, batched, per_drain: drains ? Math.round(batched / drains * 100) / 100 : null,
                   windows: s1.windows - s0.windows, waited_ms: Math.round(s1.waited_ms - s0.waited_ms),
                   wait_p50_ms: q(0.5), wait_p95_ms: q(0.95), cost_ms: s1.cost_ms, trickling: s1.trickling,
                   recent_sizes: s1.recent_sizes,
                   regroups: (s1.regroups || 0) - (s0.regroups || 0),
                   regroup_queued: (s1.regroup_queued || 0) - (s0.regroup_queued || 0),
                   regroup_page_chunks: (s1.regroup_page_chunks || 0) - (s0.regroup_page_chunks || 0) };
        };
        const start = await evaluate(`(async () => { ${PREP} return b.webview.getURL(); })()`, { timeout: 60000 });
        const O = fixtures.origin, T = Date.now();
        const trickle = (tag) => O + "/busy_feed.html?every=600&rounds=40&words=120&g13=" + tag + T;
        const burst = (tag) => O + "/nav_heavy.html?g13=" + tag + T;
        const out = {};
        try {
          // A re-cluster follows every quiet gap of a live page; planted, it
          // re-queues the whole page (regroup_queued is then -1 a call: the
          // count is the delta path's, so the planted arm reads its drains).
          out.trickle_whole = await arm({ "project-whole-page": true, "adaptive-window": false, "window-always": false }, trickle("w"), 28000);
          await plant("project-whole-page", false);
          out.trickle_off = await arm({ "adaptive-window": false, "window-always": false }, trickle("off"), 28000);
          out.trickle_on = await arm({ "adaptive-window": true, "window-always": false }, trickle("on"), 28000);
          out.burst_on = await arm({ "adaptive-window": true, "window-always": false }, burst("on"), 12000);
          out.burst_planted = await arm({ "adaptive-window": true, "window-always": true }, burst("p"), 12000);
        } finally {
          await plant("window-always", false);
          await plant("adaptive-window", true);           // the default (2026-10-30)
          await plant("project-whole-page", false);
          await evaluate(`(async () => { ${PREP} await land(${JSON.stringify(start)}, 20000); return 1; })()`, { timeout: 60000 }).catch(() => 0);
          out.purged = await tidyFixtures(fixtures.origin);
          await fixtures.close();
        }
        const t0 = out.trickle_off, t1 = out.trickle_on;
        return {
          // The mechanism, which is what the verbatim asks: on a trickle the
          // window opens and the median chunk waits no longer than a drain
          // costs; a burst never waits; planted window-always, it does. NOT
          // the benefit: trickle arms stream different volumes from run to
          // run (514 vs 188 chunks), and chunks a drain went 3.95 -> 4.86 in
          // one run and 7.67 -> 3.69 in the next -- reported, not scored.
          pass: t1.windows > 0 && t1.wait_p50_ms <= Math.max(5, t1.cost_ms || 0)
             && out.burst_on.windows === 0 && out.burst_planted.windows > 0
             && out.burst_planted.wait_p50_ms > out.burst_on.wait_p50_ms,
          evidence: out,
        };
      },
    },
    {
      id: "G-14",
      asks: "graph linkage completeness across trie, web links and markdown links (2026-10-30): every page link the STORE holds between two pages the pane draws is in the layout and drawn, per axis -- web (http), markdown (vault notes), code -- and every directory (trie) edge the layout carries is drawn; planted plantTreeOnlyPages (the one-parent rule over page links) drops web links and is caught",
      async run() {
        // Two legs, each answerable on its own: store -> layout (did the
        // sidecar hand the pane every link it holds?) and layout -> drawn (did
        // the pane draw what it was handed?). The denominator is links whose
        // BOTH pages are drawn: a link to a page the corpus does not hold is
        // not one the picture can draw.
        const SIDE = SIDECAR.replace(/\/+$/, "");
        // The markdown axis made non-vacuous: the store may hold no linked
        // vault note at all (it held 0 the first time this ran), and an axis
        // with nothing in it cannot fail. A note linking two stored pages,
        // indexed as the [](...) gesture indexes it; removed afterwards.
        const note = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const plugin = app.plugins.getPlugin("domvec-bridge");
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0]?.view;
          const NL = String.fromCharCode(10);
          const A = "https://en.wikipedia.org/wiki/Radix_tree", B = "https://en.wikipedia.org/wiki/Trie";
          const folder = "domvec-checks";
          if (!app.vault.getAbstractFileByPath(folder)) await app.vault.createFolder(folder);
          const path = folder + "/g14-" + Date.now() + ".md";
          const f = await app.vault.create(path, "# Linkage" + NL + NL + "A [radix tree](" + A + ") compresses a [trie](" + B + ")." + NL);
          const url = "vault://" + app.vault.getName() + "/" + path;
          await plugin.indexNote(f, "check");
          let laid = 0;
          for (let i = 0; i < 30 && laid < 1; i++) {
            await sleep(2000);
            const lay = await (await fetch(plugin.settings.sidecar.replace(/[/]+$/, "") + "/layout?dims=3")).json();
            laid = (lay.edges || []).filter((e) => e.source === "page:" + url).length;
          }
          if (v && v.reload) { await v.reload(); await sleep(2500); }
          return { path, url, laid };
        })()`, { timeout: 120000 });
        try {
        const rows = (await (await fetch(SIDE + "/cypher", { method: "POST", headers: { "content-type": "application/json" },
          body: JSON.stringify({ query: "MATCH (c:Chunk)-[:LinksTo]->(p:Page) RETURN DISTINCT c.url, p.url" }) })).json()).rows || [];
        const lay = await ask("/layout?dims=3");
        const got = await inPane(`
          if (v.level === "chunk") {
            [...v.contentEl.querySelectorAll("button")].find((x) => x.textContent === "chunks")?.click();
            await sleep(6000);
          }
          for (let i = 0; i < 60 && !(v.graph && v.graph.graphData().nodes.length); i++) await sleep(500);
          const rows = ${JSON.stringify(rows)};
          const layEdges = ${JSON.stringify((lay.edges || []).map((e) => [e.source, e.target, e.kind || ""]))};
          const d = v.graph.graphData();
          const end = (x) => (typeof x === "object" && x ? x.id : x);
          const drawnNodes = new Set(d.nodes.map((n) => n.id));
          const drawn = new Set(d.links.map((l) => end(l.source) + " -> " + end(l.target)));
          const laid = new Set(layEdges.map((e) => e[0] + " -> " + e[1]));
          const axis = (s) => s.startsWith("page:vault://") ? "markdown" : s.startsWith("page:code://") ? "code" : "web";
          const out = { web: { stored: 0, laid: 0, drawn: 0 }, markdown: { stored: 0, laid: 0, drawn: 0 },
                        code: { stored: 0, laid: 0, drawn: 0 }, dir: { laid: 0, drawn: 0 }, missing: [] };
          for (const [a, b] of rows) {
            if (!a || !b || a === b) continue;
            const s = "page:" + a, t = "page:" + b;
            if (!drawnNodes.has(s) || !drawnNodes.has(t)) continue;
            const k = s + " -> " + t, o = out[axis(s)];
            o.stored++;
            if (laid.has(k)) o.laid++;
            if (drawn.has(k)) o.drawn++;
            else if (out.missing.length < 4) out.missing.push(k.slice(0, 160));
          }
          for (const [s, t, kind] of layEdges) {
            if (kind !== "dir" || !drawnNodes.has(s) || !drawnNodes.has(t)) continue;
            out.dir.laid++;
            if (drawn.has(s + " -> " + t)) out.dir.drawn++;
          }
          // The planted arm, on the pane's own transform: the edges it was
          // handed, through treeOnly, with and without the old rule.
          const kept = (planted) => {
            const copy = { nodes: d.nodes, links: layEdges.map((e) => ({ source: e[0], target: e[1], kind: e[2] })) };
            v.plantTreeOnlyPages = planted;
            try { v.treeOnly(copy); } finally { v.plantTreeOnlyPages = false; }
            return copy.links.filter((l) => !l.kind && axis(String(l.source)) === "web").length;
          };
          out.transform = { handed_web: layEdges.filter((e) => !e[2] && axis(e[0]) === "web").length,
                            kept_clean: kept(false), kept_planted: kept(true) };
          return out;
        `);
        if (got.error) return { pass: false, evidence: got };
        got.note = { laid_edges: note.laid };
        const whole = (o) => o.laid === o.stored && o.drawn === o.stored;
        return {
          pass: got.web.stored > 0 && got.markdown.stored > 0 && whole(got.web) && whole(got.markdown) && whole(got.code)
             && got.dir.laid > 0 && got.dir.drawn === got.dir.laid
             && got.transform.kept_clean === got.transform.handed_web
             && got.transform.kept_planted < got.transform.kept_clean,
          evidence: got,
        };
        } finally {
          await evaluate(`(async () => {
            const plugin = app.plugins.getPlugin("domvec-bridge");
            const f = app.vault.getAbstractFileByPath(${JSON.stringify(note.path)});
            try { if (f) await app.vault.delete(f); } catch (e) {}
            try { await fetch(plugin.settings.sidecar.replace(/[/]+$/, "") + "/purge", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ url: ${JSON.stringify(note.url)} }) }); } catch (e) {}
            plugin.settings.indexedNotes = (plugin.settings.indexedNotes || []).filter((p) => p !== ${JSON.stringify(note.path)});
            await plugin.saveSettings();
            await new Promise((r) => setTimeout(r, 1500));
            const fo = app.vault.getAbstractFileByPath("domvec-checks");
            try { if (fo && (!fo.children || !fo.children.length)) await app.vault.delete(fo, true); } catch (e) {}
            return 1;
          })()`, { timeout: 60000 }).catch(() => 0);
        }
      },
    },
    {
      id: "G-38",
      asks: "hovering a chunk in the browser highlights it minimally -- an outline in the cell with no text, no banner added to the cell -- and rings THAT chunk's node in the 3D projector (not its page's); planted plantPageUnit (the hover resolved to the page) rings the page node and is caught",
      async run() {
        // Was blocked (2026-09) on reading the pointer without writing into
        // the page; the sensor's passive, capturing pointermove listener now
        // pushes the hovered address and nothing is written into the
        // document. Real pointer moves (`sendInputEvent`), as G-195.
        const PAGE = "https://en.wikipedia.org/wiki/Trie";
        const arm = (planted) => evaluate(`(async () => {
          ${PREP}
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
          const box = b.pipebox;
          if (!box) return { error: "no pipeline box" };
          try {
            if (!(await land(${JSON.stringify(PAGE)}, 30000))) return { error: "did not land" };
            await sleep(4000);
            box.plantPageUnit = ${planted};
            const wv = b.webview, r = wv.getBoundingClientRect(), wrap = wv.parentElement;
            const outlineEl = wrap.querySelector(".domvec-chunk-outline");
            const text = () => (wrap.innerText || "").replace(/\\s+/g, " ").trim().length;
            const out = [];
            for (let i = 0; i < 16; i++) {
              const x = Math.round(60 + (i * 97) % Math.max(100, r.width - 120));
              const y = Math.round(90 + (i * 131) % Math.max(100, r.height - 160));
              const prev = b.lastHovered ? b.lastHovered.cid : "";
              const before = text();
              wv.sendInputEvent({ type: "mouseMove", x, y });
              const t0 = performance.now();
              while (performance.now() - t0 < 1500 && !(b.lastHovered && b.lastHovered.cid && b.lastHovered.cid !== prev)) await sleep(10);
              if (!(b.lastHovered && b.lastHovered.cid && b.lastHovered.cid !== prev)) { await sleep(300); continue; }
              await sleep(400);
              const h = b.lastHovered;
              const ringed = v.graph.graphData().nodes.filter((n) => n.hovered);
              const ring = ringed[0] || null;
              out.push({
                outline: !!outlineEl && outlineEl.offsetWidth > 0 && outlineEl.offsetHeight > 0,
                outline_text: outlineEl ? (outlineEl.textContent || "").trim().length : -1,
                cell_text_added: Math.max(0, text() - before),
                rings: ringed.length,
                // The chunk, or the lead that draws it when it is a copy.
                ring_is_chunk: !!ring && ring.level !== "page" && (ring.id === h.stored || ring.id === h.cid
                  || (v.hoverAliases && ring.id === v.hoverAliases.get(h.stored))),
                via_alias: !!(v.hoverAliases && v.hoverAliases.has(h.stored)),
                // A copy whose lead sits in a FOLDED page has no node to ring
                // (the page view draws chunks of open pages only): it rings
                // the hovered page, and is not in the chunk-ring denominator.
                lead_folded: !!(v.hoverAliases && v.hoverAliases.has(h.stored))
                  && !v.graph.graphData().nodes.some((n) => n.id === v.hoverAliases.get(h.stored)),
                ring_is_page_of_hover: !!ring && ring.level === "page" && ring.url === h.url,
                ring_level: ring ? (ring.level || "chunk") : null,
              });
              await sleep(300);
            }
            const n = out.length;
            const share = (f) => n ? Math.round(out.filter(f).length / n * 100) / 100 : 0;
            return { planted: ${planted}, hovers: n,
                     outlined_without_text: share((o) => o.outline && o.outline_text === 0),
                     banner_moves: out.filter((o) => o.cell_text_added > 0).length,
                     max_text_added: Math.max(0, ...out.map((o) => o.cell_text_added)),
                     one_ring: share((o) => o.rings === 1),
                     ring_is_chunk: (() => { const d = out.filter((o) => !o.lead_folded); return d.length ? Math.round(d.filter((o) => o.ring_is_chunk).length / d.length * 100) / 100 : 0; })(),
                     lead_folded: out.filter((o) => o.lead_folded).length,
                     lead_folded_ring_page: out.filter((o) => o.lead_folded && o.ring_is_page_of_hover).length,
                     via_alias: out.filter((o) => o.via_alias).length,
                     sample: out.slice(0, 4) };
          } finally {
            box.plantPageUnit = false;
          }
        })()`, { timeout: 120000 });
        const clean = await arm(false);
        const planted = await arm(true);
        const ok = (x) => !!x && !x.error && x.hovers >= 6 && x.outlined_without_text >= 0.8
          && x.banner_moves === 0 && x.one_ring >= 0.8 && x.ring_is_chunk >= 0.9
          && x.lead_folded_ring_page === x.lead_folded;
        return { pass: ok(clean) && !!planted && !planted.error && planted.ring_is_chunk < 0.2,
                 evidence: { clean, planted } };
      },
    },
    {
      id: "G-43",
      asks: "the browser cell's chat (G-43/G-44/G-45): a strip on the cell opens on hover; the chunks pinned since the last reply are pre-injected into the markdown and go with the next prompt, each AT MOST ONCE; the reply lands below the pinned markdown as markdown; planted: a panel that re-sends every pin has them dropped at the sidecar, and a sidecar that re-sends everything (chat-resend) grows the turn's delta",
      async run() {
        // The verbatim (PLUGIN_GOAL, O.2): "a hoverable chat panel on the
        // standalone browser window ... collects the right-click selected
        // *full* markdowns as context ... the same chunks are *never* re-sent
        // to the context window"; "the right-clicked elements after the most
        // previous response are included in the very next prompt
        // (pre-injected into the markdown obsidian panel ...)"; "Chat outputs
        // would be in a panel below the web-selected markdown". Pins are made
        // by the double right-click's own path (`portMarkdown`) on a stored
        // page; the model is L-1's Nous Hermes 2 DPO, local.
        const PAGE = "https://en.wikipedia.org/wiki/Trie";
        const plant = (name, on) => fetch(SIDECAR + "/plant", { method: "POST",
          headers: { "content-type": "application/json", "X-Domvec-Client": "obsidian-plugin" }, body: JSON.stringify({ name, on }) });
        try {
          const got = await evaluate(`(async () => {
            ${PREP}
            const chat = b.chat;
            if (!chat) return { error: "no chat panel on the cell" };
            for (const cid of [...b.pinned.keys()]) b.unpin(cid);
            await chat.reset();
            if (!(await land(${JSON.stringify(PAGE)}, 30000))) return { error: "did not land" };
            await sleep(3000);
            const r = b.webview.getBoundingClientRect();
            const pinAt = async (fx, fy) => { const before = b.pinned.size; await b.portMarkdown(Math.round(r.width * fx), Math.round(r.height * fy)); await sleep(400); return b.pinned.size > before; };
            const out = {};
            // Hover: the strip opens; leaving it closes it.
            chat.el.dispatchEvent(new MouseEvent("mouseenter"));
            out.opens_on_hover = chat.isOpen;
            chat.el.dispatchEvent(new MouseEvent("mouseleave"));
            out.closes_on_leave = !chat.isOpen;
            // Two pins, then the first prompt.
            let pins = 0;
            for (const [fx, fy] of [[0.35, 0.35], [0.35, 0.6], [0.5, 0.8], [0.3, 0.45]]) { if (pins >= 2) break; if (await pinAt(fx, fy)) pins++; }
            out.pinned_first = b.pinned.size;
            const side = b.markdownWrap;
            out.pre_injected = chat.pending().length === b.pinned.size
              && /Next prompt includes/.test(side.innerText || "") && /Next prompt includes/.test(chat.el.innerText || "");
            const t1 = await chat.send("In two sentences: what do the pinned passages say about tries?");
            if (!t1) return { error: "first turn failed: " + chat.lastError, ...out };
            await sleep(600);
            out.t1_heads = t1.context.map((c) => String(c.head || ""));
            out.t1 = { context: t1.context.length, delta: t1.delta_chars, dropped: t1.resent_dropped.length, reply_chars: t1.reply.length, ms: Math.round(t1.ms), reply: t1.reply.slice(0, 160) };
            out.sent_after_t1 = chat.sent.size;
            // The reply BELOW the pinned markdown, as markdown.
            const cards = [...side.querySelectorAll(".domvec-pin-card")];
            const tr = side.querySelector(".domvec-chat-transcript");
            out.reply_below_pins = !!tr && cards.length > 0 && !!(cards[cards.length - 1].compareDocumentPosition(tr) & Node.DOCUMENT_POSITION_FOLLOWING)
              && (tr.innerText || "").includes(t1.reply.slice(0, 30).trim());
            out.reply_rendered_as_markdown = !!tr && !!tr.querySelector("blockquote, p, strong");
            // One more pin: the next turn carries THAT one only.
            const firstSent = new Set(chat.sent);
            let third = false;
            for (const [fx, fy] of [[0.55, 0.5], [0.4, 0.7], [0.6, 0.3], [0.45, 0.9]]) { if (await pinAt(fx, fy)) { third = true; break; } }
            out.third_pinned = third;
            out.pending_before_t2 = chat.pending().length;
            const t2 = await chat.send("And what does the newest pinned passage add, in one sentence?");
            if (!t2) return { error: "second turn failed: " + chat.lastError, ...out };
            out.t2 = { context: t2.context.length, delta: t2.delta_chars, dropped: t2.resent_dropped.length, old_in_context: t2.context.filter((c) => firstSent.has(c.cid)).length, reply_chars: t2.reply.length };
            // A bare follow-up: the smallest delta, nothing re-sent.
            const t3 = await chat.send("Thanks -- one word: was that helpful?");
            out.t3 = t3 ? { context: t3.context.length, delta: t3.delta_chars, dropped: t3.resent_dropped.length } : null;
            // Planted: a panel that re-sends every pin -- the sidecar drops them.
            chat.plantSendAllPins = true;
            const t4 = await chat.send("One word: ok?");
            chat.plantSendAllPins = false;
            out.planted_panel = t4 ? { offered: b.pinned.size, context: t4.context.length, dropped: t4.resent_dropped.length } : null;
            out.turns = chat.turns.length;
            return out;
          })()`, { timeout: 300000 });
          if (!got || got.error) return { pass: false, evidence: got };
          // Planted at the sidecar: a stateless chat sending everything each
          // turn. Same pins, a fresh conversation; the bare follow-up's delta
          // grows by the pinned markdown.
          await plant("chat-resend", true);
          let resend = null;
          try {
            resend = await evaluate(`(async () => {
              const b = app.workspace.getLeavesOfType("domvec-browser-view")[0].view;
              const chat = b.chat;
              await chat.reset();
              const a = await chat.send("One word: ready?");
              const z = await chat.send("One word: still?");
              return a && z ? { first: a.delta_chars, follow_up: z.delta_chars } : { error: chat.lastError };
            })()`, { timeout: 200000 });
          } finally { await plant("chat-resend", false); }
          got.planted_sidecar = resend;
          const ok = got.opens_on_hover && got.closes_on_leave && got.pinned_first >= 2 && got.pre_injected
            && got.t1.context === got.pinned_first && got.t1.dropped === 0 && got.t1.reply_chars > 20
            && got.t1_heads.every((h) => h && !h.startsWith("/html") && h.includes(" · "))
            && got.reply_below_pins && got.reply_rendered_as_markdown
            && got.third_pinned && got.pending_before_t2 === 1
            && got.t2.context === 1 && got.t2.old_in_context === 0 && got.t2.dropped === 0
            && !!got.t3 && got.t3.context === 0 && got.t3.delta < got.t1.delta
            && !!got.planted_panel && got.planted_panel.context === 0 && got.planted_panel.dropped === got.planted_panel.offered
            && !!resend && !resend.error && resend.follow_up > got.t3.delta * 5;
          return { pass: !!ok, evidence: got };
        } finally {
          await evaluate(`(async () => {
            const b = app.workspace.getLeavesOfType("domvec-browser-view")[0].view;
            for (const cid of [...b.pinned.keys()]) b.unpin(cid);
            if (b.chat) { b.chat.plantSendAllPins = false; await b.chat.reset(); }
            return 1;
          })()`, { timeout: 60000 }).catch(() => 0);
        }
      },
    },
    {
      id: "L-2",
      asks: "the notebook chat (L-2..L-9, G-44's notebook half): a panel at the foot of the selected cell that follows the scroll; a new rewind only when the cursor lands on a new cell; the rewind ends at that cell, goes backwards over the note as it stands (outputs included), is injected ahead of the prompt, @N limits it, and it stays within a safety share of the model's window; each cell reaches the conversation once; planted rewind-on-scroll and no-budget are caught",
      async run() {
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const plugin = app.plugins.getPlugin("domvec-bridge");
          const chats = window.__domvecNbChats;
          if (!chats) return { error: "no notebook chats" };
          const NL = String.fromCharCode(10), F = String.fromCharCode(96).repeat(3);
          const folder = "domvec-checks";
          if (!app.vault.getAbstractFileByPath(folder)) await app.vault.createFolder(folder);
          const path = folder + "/l2-" + Date.now() + ".md";
          const para = (k) => "Paragraph " + k + ": " + "the okapi is a forest giraffe of the Congo basin, shy and striped. ".repeat(9);
          const lines = ["# Loading data", "We read the sightings table.", "",
            F + "python", "import pandas as pd", "df = pd.read_csv('sightings.csv')", F,
            "<!-- nb-output hash=ab12 count=1 status=error -->", F, "FileNotFoundError: [Errno 2] No such file or directory: 'sightings.csv'", F, "<!-- /nb-output -->", "",
            "Then we count sightings by year.", "",
            F + "python", "df.groupby('year').size()", F, ""];
          for (let k = 1; k <= 40; k++) lines.push(para(k), "");
          lines.push(F + "python", "print('end')", F);
          const f = await app.vault.create(path, lines.join(NL));
          const url = "vault://" + app.vault.getName() + "/" + path;
          const leaf = app.workspace.getLeaf("tab");
          await leaf.openFile(f);
          app.workspace.setActiveLeaf(leaf, { focus: true });
          await sleep(1500);
          const view = leaf.view, ed = view.editor;
          const out = {};
          try {
            chats.onCursor();
            const chat = chats.forActive();
            if (!chat) return { error: "no chat on a notebook note" };
            await chat.reset();
            // Land on the code cell (line 4), then inside its OUTPUT: same cell.
            ed.setCursor({ line: 4, ch: 0 }); await sleep(400);
            const r0 = chat.rewinds;
            out.landed_index = chat.landed && chat.landed.index;
            ed.setCursor({ line: 9, ch: 3 }); await sleep(400);
            out.same_cell_no_rewind = chat.rewinds === r0;
            // At the cell's foot.
            const cm = ed.cm, host = view.contentEl.getBoundingClientRect();
            const foot = cm.coordsAtPos(cm.state.doc.line(12).to);
            chat.place();
            const top = parseFloat(chat.el.style.top);
            out.at_cell_foot = !!foot && Math.abs((foot.bottom + 4 - host.top) - top) < 6;
            // Scroll: the panel follows (stays in view), and there is no new rewind.
            const r1 = chat.rewinds;
            cm.scrollDOM.scrollTop += 900; await sleep(400);
            const pr = chat.el.getBoundingClientRect(), vr = view.contentEl.getBoundingClientRect();
            out.in_view_after_scroll = pr.top >= vr.top - 1 && pr.bottom <= vr.bottom + 1;
            out.no_rewind_on_scroll = chat.rewinds === r1;
            cm.scrollDOM.scrollTop = 0; await sleep(300);
            // Hover opens it.
            chat.el.dispatchEvent(new MouseEvent("mouseenter"));
            out.opens_on_hover = chat.isOpen;
            // A new cell: the paragraph after the code -- a new rewind.
            ed.setCursor({ line: 13, ch: 2 }); await sleep(400);
            out.new_cell_rewinds = chat.rewinds === r1 + 1 && chat.landed.index === 2;
            // @2: the last two cells -- the code WITH its output, and this one.
            const t1 = await chat.send("@2 What went wrong in the code above, and how would you fix it? Two sentences.");
            if (!t1) return { error: "turn 1: " + chat.lastError, ...out };
            out.t1 = { rewound: t1.cells, sent: t1.sent, dropped: t1.dropped, chars: t1.chars, limit: chat.lastRewind.limit, ms: Math.round(t1.ms), reply: t1.reply.slice(0, 220) };
            out.output_in_context = /FileNotFoundError|sightings\\.csv|file/i.test(t1.reply);
            // The same cells again: nothing reaches the conversation twice.
            const t2 = await chat.send("@2 One word: is the file name the problem?");
            out.t2 = t2 ? { rewound: t2.cells, sent: t2.sent, dropped: t2.dropped, chars: t2.chars } : null;
            // The budget: the last paragraph -- 40 long cells above it.
            ed.setCursor({ line: lines.length - 5, ch: 0 }); await sleep(400);
            const full = chat.pendingRewind(null);
            out.budget = { cells: full.cells.length, chars: full.chars, budget: full.budget, note_cells: 44 };
            chat.plantNoBudget = true;
            const nob = chat.pendingRewind(null);
            chat.plantNoBudget = false;
            out.planted_no_budget = { cells: nob.cells.length, chars: nob.chars };
            // Planted: a rewind on every scroll.
            chat.plantRewindOnScroll = true;
            const r2 = chat.rewinds;
            cm.scrollDOM.scrollTop += 600; await sleep(300); cm.scrollDOM.scrollTop += 600; await sleep(300);
            chat.plantRewindOnScroll = false;
            out.planted_scroll_rewinds = chat.rewinds - r2;
            out.panel_in_view = chat.el.isConnected;
            return out;
          } finally {
            try { const c = chats.forActive(); if (c) await c.reset(); } catch (e) {}
            try { leaf.detach(); } catch (e) {}
            try { await app.vault.delete(f); } catch (e) {}
            try { await fetch(plugin.settings.sidecar.replace(/[/]+$/, "") + "/purge", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ url }) }); } catch (e) {}
            plugin.settings.indexedNotes = (plugin.settings.indexedNotes || []).filter((p) => p !== path);
            await plugin.saveSettings();
            await sleep(1200);
            const fo = app.vault.getAbstractFileByPath(folder);
            try { if (fo && (!fo.children || !fo.children.length)) await app.vault.delete(fo, true); } catch (e) {}
          }
        })()`, { timeout: 300000 });
        if (!got || got.error) return { pass: false, evidence: got };
        const ok = got.landed_index === 1 && got.same_cell_no_rewind && got.at_cell_foot
          && got.in_view_after_scroll && got.no_rewind_on_scroll && got.opens_on_hover && got.new_cell_rewinds
          && got.t1.rewound === 2 && got.t1.sent === 2 && got.t1.limit === 2 && got.t1.reply.length > 20
          && !!got.t2 && got.t2.sent === 0 && got.t2.dropped === 2
          && got.budget.chars <= got.budget.budget && got.budget.cells < got.budget.note_cells
          && got.planted_no_budget.chars > got.budget.budget
          && got.planted_scroll_rewinds >= 1;
        return { pass: !!ok, evidence: got };
      },
    },
    {
      id: "G-80",
      asks: "hover-first: the hovered chunk jumps the encoder's and projector's queues and reaches the 3D view before the page's other chunks -- the LAST chunk of a fresh 200-chunk page, hovered as the page lands, is drawn among the first; planted plantNoPushedFocus (the pushed hover never focused, as before) it is drawn among the last",
      async run() {
        // The verbatim (2026-09-22): "whichever element that is hovered is
        // recursively chunked first ... projected through our 3D graph as
        // fast as possible". The hover is fed to `pushedHover` with the
        // stored chunk's own address -- what the sensor pushes -- the moment
        // the page's chunk map knows its chunks; every chunk's first frame
        // in the graph is timed.
        const fixtures = await serveFixtures();
        const arm = (planted, tag) => evaluate(`(async () => {
          ${PREP}
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
          const box = b.pipebox;
          box.plantNoPushedFocus = ${planted};
          try {
            // Salted: the page's words are new to the embedder's cache, so its
            // queue really holds them when the hover arrives (unsalted, every
            // chunk was a cache hit and the whole page drained in one batch
            // before any hover could matter -- a test that could not fail).
            const salt = ${JSON.stringify(tag)} + Date.now().toString(36);
            const url = ${JSON.stringify(fixtures.origin)} + "/nav_heavy.html?g80=" + salt + "&salt=" + salt;
            b.go(url);
            let stored = [];
            const t0 = performance.now();
            while (performance.now() - t0 < 30000) {
              await sleep(15);
              // Every chunk the capture stored, with its addresses (the map's
              // byCid; its "stored" set is the projector-held subset).
              if (box.map && box.map.url === url && box.map.byCid && box.map.byCid.size >= 50) { stored = [...box.map.byCid.keys()]; break; }
            }
            if (!stored.length) return { error: "the page's chunk map never filled", url };
            const drawnAtStart = new Set(v.graph.graphData().nodes.filter((n) => !n.force).map((n) => n.id));
            const waiting = stored.filter((c) => !drawnAtStart.has(c));
            const target = waiting[waiting.length - 1];
            const xs = box.map.xpaths(target);
            if (!target || !xs.length) return { error: "no undrawn chunk with an address", waiting: waiting.length };
            const focus0 = box.focusCalls;
            // Placement read at the SIDECAR -- the projector's own log, polled
            // -- not the pane's frames: the pane draws the browsed page's
            // chunks in one wave whatever order they were placed in.
            const base = app.plugins.plugins["domvec-bridge"].settings.sidecar.replace(/[/]+$/, "");
            const d0 = await (await fetch(base + "/projector/delta?since=0&epoch=-1")).json();
            let since = d0.seq, epoch = d0.epoch;
            const want = new Set(waiting);
            const th = performance.now();
            box.pushedHover("9999 10,10,40,20 " + xs[0], url);
            const seen = new Map();
            while (performance.now() - th < 40000 && seen.size < waiting.length) {
              await sleep(25);
              const d = await (await fetch(base + "/projector/delta?since=" + since + "&epoch=" + epoch)).json();
              if (d.reload) { epoch = d.epoch; since = d.seq; continue; }
              const now = performance.now() - th;
              for (const c of Object.keys(d.chunks || {})) if (want.has(c) && !seen.has(c)) seen.set(c, now);
              since = d.seq;
            }
            const order = [...seen.entries()].sort((a, c) => a[1] - c[1]).map(([id]) => id);
            const rank = order.indexOf(target);
            const times = [...seen.values()].sort((a, c) => a - c);
            const first = times.length ? times[0] : null;
            return { planted: ${planted}, url, stored: stored.length, waiting: waiting.length, drawn: seen.size,
                     page_first_ms: first === null ? null : Math.round(first),
                     // The page arrives in waves (the embedder's batches); in
                     // the FIRST one is what hover-first can promise. A rank
                     // inside a wave is only the order of a tie.
                     target_in_first_wave: seen.has(target) && first !== null && seen.get(target) <= first + 60,
                     focus_calls: box.focusCalls - focus0,
                     target_ms: seen.has(target) ? Math.round(seen.get(target)) : null,
                     target_rank: rank, rank_share: rank >= 0 ? Math.round(rank / Math.max(1, order.length - 1) * 100) / 100 : null,
                     page_p50_ms: times.length ? Math.round(times[Math.floor(times.length / 2)]) : null,
                     page_last_ms: times.length ? Math.round(times[times.length - 1]) : null };
          } finally { box.plantNoPushedFocus = false; }
        })()`, { timeout: 90000 });
        try {
          // The planted arm FIRST, then purged: the same content stored twice
          // makes the second page's chunks copies of the first's (store-wide
          // dedup), and a copy is never drawn -- the first run's planted arm
          // drew 0 of 220.
          const planted = await arm(true, "p");
          const purged_between = await tidyFixtures(fixtures.origin);
          const clean = await arm(false, "c");
          const waves = (x) => !!x && !x.error && x.drawn >= 50 && x.page_last_ms - x.page_first_ms > 150;
          // Placed before half the page (hover-first), against near the end.
          const ok = !!clean && !clean.error && !!planted && !planted.error
            && clean.focus_calls >= 1 && planted.focus_calls === 0
            && clean.drawn >= 50 && planted.drawn >= 50
            && clean.rank_share !== null && clean.rank_share < 0.5
            && planted.rank_share !== null && planted.rank_share > 0.8;
          clean.purged_between = purged_between;
          return { pass: ok, evidence: { clean, planted, purged: await tidyFixtures(fixtures.origin) } };
        } finally { await fixtures.close(); }
      },
    },
    {
      id: "G-84",
      asks: "left-click on a folded page node opens its WHOLE tree -- every chunk the store can place for it -- drawn as a tree: each chunk exactly one parent, every chunk reaching the page node; right-click folds it whole; planted plantUnfoldOnClick (one patricia step per click, as the row recorded) draws less than the tree",
      async run() {
        // Addendum VII: "expands its FULL patricia TREE"; "intermediate path
        // nodes, if they go from one root to one leaf, as a single link";
        // one parent per node. The handlers are the pane's own, fired as the
        // graph fires them.
        const arm = (planted) => evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
          const g = v.graph;
          const poll = async (cond, ms) => { const t = performance.now(); while (performance.now() - t < ms) { if (cond()) return true; await sleep(250); } return cond(); };
          const left = (node) => { const h = g.onNodeClick(); if (typeof h === "function") h(node); };
          const right = (node) => { const h = g.onNodeRightClick(); if (typeof h === "function") h(node); };
          const end = (x) => (typeof x === "object" && x ? x.id : x);
          // A STABLE page: a search results page re-captured between the arms
          // (30 stored chunks, then 41) is a moving denominator.
          const pages = g.graphData().nodes.filter((n) => n.level === "page" && !n.force && /^https:[/][/]en[.]wikipedia[.]org[/]wiki[/]/.test(n.url || "")
            && n.members >= 30 && n.members <= 300).sort((x, y) => (x.members - y.members) || String(x.url).localeCompare(String(y.url)));
          let page = null, cids = [];
          let asked = 0, failed = 0;
          let rawMulti = 0;
          for (const p of pages.slice(0, 25)) {
            asked++;
            const c = await v.sidecar.pageCids(p.url).catch(() => { failed++; return []; });
            if (c.length < 30) continue;
            // A page that NESTS: some chunk with two or more containers in the
            // store's own edges -- the case the one-parent rule is for. On a
            // page without one, the raw edges are already a tree and the
            // planted arm had nothing to show (Knowledge_modeling: 0 and 0).
            const o = await v.sidecar.place(c).catch(() => null);
            // A chunk inside another chunk: drawn as a web it hangs from that
            // chunk AND from the page (the DuckDuckGo arm's 8 multi-parents).
            const ids0 = new Set(c);
            const inner = new Set();
            for (const e of (o && o.edges) || []) { const sId = end(e.source), t = end(e.target); if (ids0.has(sId) && ids0.has(t)) inner.add(t); }
            const multi = inner.size;
            if (multi >= 2) { page = p; cids = c; rawMulti = multi; break; }
          }
          if (!page) return { error: "no stored page with >= 30 chunks drawn as a page node", candidates: pages.length, asked, failed };
          const url = page.url, pid = "page:" + url;
          const chunks = () => g.graphData().nodes.filter((n) => n.url === url && n.level !== "page" && !n.force);
          v.plantUnfoldOnClick = ${planted};
          try {
            // Folded first, by the right-click.
            if (chunks().length) { right(g.graphData().nodes.find((n) => n.id === pid) || page); await poll(() => chunks().length === 0, 5000); }
            const foldedBefore = chunks().length;
            // The LEFT click opens it.
            left(g.graphData().nodes.find((n) => n.id === pid) || page);
            await poll(() => chunks().length >= Math.min(cids.length, 8), 30000);
            await sleep(2500);
            const oracle = await v.sidecar.place(cids);
            // THIS page's own placeable chunks: a copy is placed as its lead,
            // which may live on another page (store-wide dedup) -- not this tree.
            const placeable = new Set(((oracle && oracle.nodes) || []).filter((n) => n.level !== "page" && n.cid && n.url === url).map((n) => n.cid));
            const drawn = chunks();
            const ids = new Set(drawn.map((n) => n.id));
            const parents = new Map(drawn.map((n) => [n.id, []]));
            for (const l of g.graphData().links) {
              const s = end(l.source), t = end(l.target);
              if (!ids.has(t) || l.force) continue;
              if (s === pid || ids.has(s)) parents.get(t).push(s);
            }
            const counts = [...parents.values()].map((p) => p.length);
            const reaches = (id) => { const seen = new Set(); let cur = id; while (cur && cur !== pid && !seen.has(cur)) { seen.add(cur); cur = (parents.get(cur) || [])[0]; } return cur === pid; };
            const out = { url: url.slice(-60), raw_multi_parent: rawMulti, stored_cids: cids.length, placeable: placeable.size, folded_before: foldedBefore,
              drawn: drawn.length, drawn_placeable: drawn.filter((n) => placeable.has(n.id)).length,
              one_parent: counts.filter((c) => c === 1).length, many_parents: counts.filter((c) => c > 1).length,
              no_parent: counts.filter((c) => c === 0).length, reach_page: drawn.filter((n) => reaches(n.id)).length };
            right(g.graphData().nodes.find((n) => n.id === pid) || page);
            await poll(() => chunks().length === 0, 5000);
            out.after_right_click = chunks().length;
            return out;
          } finally { v.plantUnfoldOnClick = false; }
        })()`, { timeout: 120000 });
        const clean = await arm(false);
        const planted = await arm(true);
        const ok = !!clean && !clean.error && clean.folded_before === 0 && clean.placeable > 0
          && clean.drawn_placeable === clean.placeable
          && clean.many_parents === 0 && clean.no_parent === 0 && clean.reach_page === clean.drawn
          && clean.after_right_click === 0
          && !!planted && !planted.error && planted.drawn_placeable < planted.placeable;
        return { pass: ok, evidence: { clean, planted } };
      },
    },
    {
      id: "G-105",
      asks: "a package chunk goes into a notebook cell as a code prototype: the 'cell' control on a code chunk's billboard appends its function -- heading linked to its code:// address, docstring, python fence holding the def -- to the notebook the reader was last in, and that cell runs in the note's kernel in its home module's namespace (a later cell calls it); planted (prototype-no-code) nothing is appended",
      async run() {
        // Addendum IX: "bringing these chunks into code prototypes in jupyter
        // python cells on a notebook". json's detect_encoding uses `codecs`,
        // imported at module level, so a bare copy of the def would fail when
        // called: the call cell is what proves the prototype RUNS.
        const plant = (name, on) => fetch(SIDECAR + "/plant", { method: "POST",
          headers: { "content-type": "application/json", "X-Domvec-Client": "obsidian-plugin" }, body: JSON.stringify({ name, on }) });
        const arm = (planted) => evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const until = async (ok, ms) => { for (let t = 0; t < ms && !(await ok()); t += 250) await sleep(250); return !!(await ok()); };
          const plugin = app.plugins.getPlugin("domvec-bridge");
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0]?.view;
          if (!v || !v.graph) return { error: "no graph" };
          const NL = String.fromCharCode(10), F = String.fromCharCode(96).repeat(3);
          const URL = "code://pypi/json/__init__.py";
          const folder = "domvec-checks";
          if (!app.vault.getAbstractFileByPath(folder)) await app.vault.createFolder(folder);
          const path = folder + "/g105 notebook " + Date.now() + (${planted} ? "p" : "c") + ".md";
          const file = await app.vault.create(path, "# g105" + NL + NL + F + "python" + NL + "x = 1" + NL + F + NL);
          const leaf = app.workspace.getLeaf("tab");
          let cid = null, unfolded = null;
          try {
            await leaf.openFile(file, { state: { mode: "source", source: false } });
            app.workspace.setActiveLeaf(leaf, { focus: true });
            await sleep(600);
            const notebook = plugin.lastNotebook === path;
            for (const c of await v.sidecar.pageCids(URL)) {
              const p = await plugin.sidecar.prototype(c);
              if (p && p.name === "detect_encoding") { cid = c; break; }
            }
            if (!cid) return { error: "no detect_encoding chunk under " + URL };
            let n = v.graph.graphData().nodes.find((x) => x.id === cid);
            // In page view a chunk is reached the reader's way: its page unfolded.
            const page = v.graph.graphData().nodes.find((x) => x.id === "page:" + URL);
            if (!n && page) { await v.unfoldNode(page); unfolded = page; await until(() => !!v.graph.graphData().nodes.find((x) => x.id === cid), 8000); n = v.graph.graphData().nodes.find((x) => x.id === cid); }
            if (!n) { const g = await v.sidecar.place([cid]); if (g && g.nodes) v.absorb(g.nodes, g.edges); n = v.graph.graphData().nodes.find((x) => x.id === cid); }
            if (!n) return { error: "chunk not placeable", cid };
            for (const bb of v.billboardState()) v.closeBillboard(bb.id);
            await v.openBillboard(n);
            const sel = '.domvec-bb[data-cid="' + cid + '"] .domvec-bb-cell';
            await until(() => !!document.querySelector(sel), 8000);
            const btn = document.querySelector(sel);
            if (!btn) return { error: "no cell control on the billboard", cid };
            const made0 = plugin.prototypeStats.made;
            btn.click();
            await until(() => plugin.prototypeStats.made > made0, 8000);
            await sleep(400);
            const text = await app.vault.read(file);
            const out = { planted: ${planted}, cid, notebook, made: plugin.prototypeStats.made - made0,
                          heading: text.includes("### detect_encoding"), link: text.includes("(" + URL + ")"),
                          def: text.includes("def detect_encoding(b):"), home: text.includes("import_module("),
                          fences: text.split(F + "python").length - 1 };
            if (!out.def) return out;
            // The call cell, then run every cell with the real Run controls.
            await app.vault.process(file, (t) => t.replace(/\\s*$/, "") + NL + NL + F + "python" + NL
              + "print(detect_encoding(codecs.BOM_UTF8 + b'hi'))" + NL + F + NL);
            await until(() => leaf.view.containerEl.querySelectorAll(".domvec-run-fence").length >= 3, 8000);
            const outs = () => (leaf.view.editor.getValue().match(/nb-output/g) || []).length;
            for (let i = 0; i < 3; i++) {
              const before = outs();
              const run = leaf.view.containerEl.querySelectorAll(".domvec-run-fence")[i];
              if (!run) break;
              run.click();
              await until(() => outs() > before, 30000);
              await sleep(300);
            }
            const after = leaf.view.editor.getValue();
            const tail = after.slice(after.lastIndexOf("detect_encoding(codecs"));
            out.ran = tail.includes("utf-8-sig");
            out.errors = (after.match(/(NameError|Traceback)[^\\n]*/g) || []).slice(0, 3);
            out.tail = tail.slice(0, 240);
            return out;
          } finally {
            if (cid) v.closeBillboard(cid);
            if (unfolded) await v.unfoldNode(unfolded);
            leaf.detach();
            try { await app.vault.delete(file); } catch (e) { /* already gone */ }
          }
        })()`, { timeout: 180000 });
        const clean = await arm(false);
        await plant("prototype-no-code", true);
        let planted;
        try { planted = await arm(true); } finally { await plant("prototype-no-code", false); }
        return {
          pass: !!clean && !clean.error && clean.notebook && clean.made === 1 && clean.heading && clean.link
                && clean.def && clean.home && clean.ran
                && !!planted && !planted.error && planted.made === 0 && !planted.def,
          evidence: { clean, planted },
        };
      },
    },
    {
      id: "P-N6",
      asks: "a notebook is continuously diff-updated to the store: saving an edit to one cell re-indexes the note by itself and queues for a new vector ONLY the chunks whose text changed -- the rest are skipped by the embed gate -- and the same holds after a restart (the gate re-learned from the store's own embedded markdown); planted (no-seed) a restart re-embeds the whole note, planted (reembed-all) every edit does",
      async run() {
        // P-N5/P-N6: "our jupyter notebooks are dynamically recursively
        // chunked similarly to our webpages and continuously diff-updated to
        // the db (including re-vectorization and chunk assignment)".
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const until = async (ok, ms) => { for (let t = 0; t < ms && !(await ok()); t += 250) await sleep(250); return !!(await ok()); };
          const plugin = app.plugins.getPlugin("domvec-bridge");
          const SIDE = String(plugin.settings.sidecar).replace(/[/]+$/, "");
          const H = { "content-type": "application/json", "X-Domvec-Client": "obsidian-plugin" };
          const post = async (route, body) => (await fetch(SIDE + route, { method: "POST", headers: H, body: JSON.stringify(body) })).json();
          const vec = async () => (await fetch(SIDE + "/vectors")).json();
          const mdOf = async (url) => {
            const r = await post("/cypher", { query: "MATCH (c:Chunk {url: " + JSON.stringify(url) + "}) RETURN c.cid, c.md" });
            return Object.fromEntries((r.rows || []).map((x) => [x[0], x[1] || ""]));
          };
          const NL = String.fromCharCode(10), F = String.fromCharCode(96).repeat(3);
          const folder = "domvec-checks";
          if (!app.vault.getAbstractFileByPath(folder)) await app.vault.createFolder(folder);
          const stamp = Date.now();
          const path = folder + "/pn6 notebook " + stamp + ".md";
          const url = "vault://" + app.vault.getName() + "/" + path;
          // Five cells, each a heading, a paragraph of its own words and code:
          // big enough that each is its own chunk at the 256 window.
          const cell = (k) => "## Cell " + k + NL + NL + Array.from({ length: 70 }, (_, i) => "c" + k + "w" + i + "x" + stamp).join(" ") + "." + NL + NL
            + F + "python" + NL + "print(" + k + ")" + NL + F + NL;
          const file = await app.vault.create(path, "# pn6" + NL + NL + [1, 2, 3, 4, 5].map(cell).join(NL));
          const leaf = app.workspace.getLeaf("tab");
          const settle = async () => {
            let last = "", same = 0;
            await until(async () => {
              const v = await vec(); const k = [v.pending, v.queued, v.embedded, v.reused].join();
              same = v.pending === 0 && k === last ? same + 1 : 0; last = k; return same >= 3;
            }, 90000);
          };
          // One edit, saved; the note re-indexes ON ITS OWN (vault modify), and
          // the queue's counters say what was offered and what was skipped.
          const edit = async (from, to) => {
            const md0 = await mdOf(url), v0 = await vec(), n0 = plugin.noteStats.indexed;
            await app.vault.process(file, (t) => t.replace(from, to));
            const indexed = await until(() => plugin.noteStats.indexed > n0, 20000);
            await settle();
            const md1 = await mdOf(url), v1 = await vec();
            const changed = Object.keys(md1).filter((c) => md0[c] !== md1[c]).length;
            return { indexed, chunks: Object.keys(md1).length, changed,
                     queued: v1.queued - v0.queued, skipped: v1.skipped - v0.skipped,
                     embedded: v1.embedded - v0.embedded, reused: v1.reused - v0.reused };
          };
          const out = {};
          try {
            await leaf.openFile(file, { state: { mode: "source", source: false } });
            // Run cell 1 with the real Run control: the note becomes a notebook
            // that has run (a stored readout), which is what is indexed on save.
            // Scrolled to the first cell, as a reader would: a long paragraph is
            // one wrapped line and CodeMirror draws only what is in view.
            const ed = leaf.view.editor, at = ed.getValue().split(NL).indexOf(F + "python");
            ed.setCursor({ line: at, ch: 0 }); ed.scrollIntoView({ from: { line: at, ch: 0 }, to: { line: at + 2, ch: 0 } }, true);
            if (!(await until(() => !!leaf.view.containerEl.querySelector(".domvec-run-fence"), 8000))) return { error: "no Run control in view" };
            const n0 = plugin.noteStats.indexed;
            leaf.view.containerEl.querySelector(".domvec-run-fence").click();
            await until(() => leaf.view.editor.getValue().includes("nb-output"), 30000);
            out.first_index = await until(() => plugin.noteStats.indexed > n0, 20000);
            await settle();
            out.chunks = Object.keys(await mdOf(url)).length;
            out.clean = await edit("print(3)", "print(33)");
            await post("/vectors", { forget_url: url });
            out.restart = await edit("print(4)", "print(44)");
            await post("/plant", { name: "no-seed", on: true });
            try { await post("/vectors", { forget_url: url }); out.planted_no_seed = await edit("print(5)", "print(55)"); }
            finally { await post("/plant", { name: "no-seed", on: false }); }
            await post("/plant", { name: "reembed-all", on: true });
            try { out.planted_reembed_all = await edit("print(2)", "print(22)"); }
            finally { await post("/plant", { name: "reembed-all", on: false }); }
            return out;
          } finally {
            leaf.detach();
            try { await app.vault.delete(file); } catch (e) { /* gone */ }
          }
        })()`, { timeout: 420000 });
        const diffOnly = (a) => !!a && a.indexed && a.changed >= 1 && a.queued === a.changed && a.skipped >= a.chunks - a.changed;
        const whole = (a) => !!a && a.indexed && a.queued >= a.chunks - 1;
        return {
          pass: !got.error && got.first_index && got.chunks >= 5 && diffOnly(got.clean) && diffOnly(got.restart)
                && whole(got.planted_no_seed) && whole(got.planted_reembed_all),
          evidence: got,
        };
      },
    },
    {
      id: "P-N9",
      asks: "a selection over the RENDERED markdown (reading view) marks the chunks it covers as trie addresses and draws them highlighted -- only those blocks; the mark follows its address when a section is added above it; selecting it again unmarks it; planted (plantNoMarks) a selection marks nothing",
      async run() {
        // Addendum II: "exposing the chunk scanning and selection highlighting
        // for markdown rendering in the alternative panel by the user to
        // annotate the context fed to our small language model".
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const until = async (ok, ms) => { for (let t = 0; t < ms && !(await ok()); t += 200) await sleep(200); return !!(await ok()); };
          const plugin = app.plugins.getPlugin("domvec-bridge");
          const marks = plugin.marks;
          const NL = String.fromCharCode(10);
          const folder = "domvec-checks";
          if (!app.vault.getAbstractFileByPath(folder)) await app.vault.createFolder(folder);
          const stamp = Date.now();
          const path = folder + "/pn9 note " + stamp + ".md";
          const sec = (name) => "## " + name + NL + NL + Array.from({ length: 45 }, (_, i) => name.toLowerCase() + "w" + i).join(" ") + " " + name + "MARK." + NL;
          const file = await app.vault.create(path, "# pn9" + NL + NL + ["Alpha", "Beta", "Gamma", "Delta"].map(sec).join(NL));
          const leaf = app.workspace.getLeaf("tab");
          const view = () => leaf.view;
          const sections = () => (view().previewMode && view().previewMode.renderer.sections || []).filter((s) => s && s.el);
          const markedTexts = () => sections().filter((s) => s.el.classList.contains("domvec-marked")).map((s) => s.el.textContent || "");
          const which = () => { const t = markedTexts().join(" "); return ["Alpha", "Beta", "Gamma", "Delta", "Zeta"].filter((n) => t.includes(n + "MARK")); };
          // Select a few words inside the block holding NAME, then release the
          // mouse: the plugin's own mouseup handler takes it from there.
          const select = async (name) => {
            const s = sections().find((x) => (x.el.textContent || "").includes(name + "MARK") && x.el.querySelector("p"));
            if (!s) return false;
            const p = s.el.querySelector("p"), node = p.firstChild;
            const r = document.createRange(); r.setStart(node, 3); r.setEnd(node, 40);
            const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r);
            p.dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
            return true;
          };
          const out = {};
          try {
            await leaf.openFile(file, { state: { mode: "preview" } });
            app.workspace.setActiveLeaf(leaf, { focus: true });
            await until(() => sections().some((s) => (s.el.textContent || "").includes("DeltaMARK")), 8000);
            const m0 = marks.stats.marked;
            out.selected = await select("Gamma");
            await until(() => marks.stats.marked > m0 && which().length > 0, 8000);
            out.marked = { addresses: marks.byNote[path] || [], blocks: which() };
            // A section added ABOVE: line numbers move, the address does not.
            await app.vault.process(file, (t) => t.replace("## Alpha", sec("Zeta").trimEnd() + NL + NL + "## Alpha"));
            await until(() => sections().some((s) => (s.el.textContent || "").includes("ZetaMARK")), 8000);
            await until(() => which().includes("Gamma"), 6000);
            out.after_insert = { blocks: which() };
            const u0 = marks.stats.unmarked;
            await select("Gamma");
            await until(() => marks.stats.unmarked > u0, 8000);
            await sleep(300);
            out.unmarked = { addresses: (marks.byNote[path] || []).length, blocks: which() };
            // Planted: the ordinal address alone -- a section added above
            // carries the mark onto its neighbour.
            marks.plantAddressOnly = true;
            try {
              const m1 = marks.stats.marked;
              await select("Delta");
              await until(() => marks.stats.marked > m1 && which().includes("Delta"), 8000);
              await app.vault.process(file, (t) => t.replace("## Zeta", sec("Eta").trimEnd() + NL + NL + "## Zeta"));
              await until(() => sections().some((s) => (s.el.textContent || "").includes("EtaMARK")), 8000);
              await until(() => !which().includes("Delta"), 6000);
              out.planted_address_only = { blocks: which() };
            } finally { marks.plantAddressOnly = false; await marks.clear(path); }
            marks.plantNoMarks = true;
            try {
              await select("Beta");
              await sleep(1500);
              out.planted = { addresses: (marks.byNote[path] || []).length, blocks: which() };
            } finally { marks.plantNoMarks = false; }
            return out;
          } finally {
            await marks.clear(path);
            leaf.detach();
            try { await app.vault.delete(file); } catch (e) { /* gone */ }
          }
        })()`, { timeout: 120000 });
        const only = (blocks, name) => !!blocks && blocks.includes(name) && !blocks.some((b) => b === "Alpha" || b === "Delta" || b === "Zeta");
        return {
          pass: !got.error && got.selected && got.marked.addresses.length >= 1 && only(got.marked.blocks, "Gamma")
                && only(got.after_insert.blocks, "Gamma")
                && got.unmarked.addresses === 0 && got.unmarked.blocks.length === 0
                && !!got.planted_address_only && !got.planted_address_only.blocks.includes("Delta")
                && got.planted.addresses === 0 && got.planted.blocks.length === 0,
          evidence: got,
        };
      },
    },
    {
      id: "P-N10",
      asks: "what the reader marked IS the model's context: with a chunk marked in a notebook, the chat's turn is given exactly that chunk -- its store cid, its current text -- and not the rewind; planted (plantIgnoreMarks) the rewind's cells are sent instead",
      async run() {
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const until = async (ok, ms) => { for (let t = 0; t < ms && !(await ok()); t += 200) await sleep(200); return !!(await ok()); };
          const plugin = app.plugins.getPlugin("domvec-bridge");
          const SIDE = String(plugin.settings.sidecar).replace(/[/]+$/, "");
          const marks = plugin.marks;
          const NL = String.fromCharCode(10), F = String.fromCharCode(96).repeat(3);
          const folder = "domvec-checks";
          if (!app.vault.getAbstractFileByPath(folder)) await app.vault.createFolder(folder);
          const stamp = Date.now();
          const path = folder + "/pn10 notebook " + stamp + ".md";
          const url = "vault://" + app.vault.getName() + "/" + path;
          const sec = (name) => "## " + name + NL + NL + Array.from({ length: 45 }, (_, i) => name.toLowerCase() + "w" + i).join(" ") + " " + name + "MARK." + NL;
          const file = await app.vault.create(path, "# pn10" + NL + NL + ["Alpha", "Beta", "Gamma"].map(sec).join(NL) + NL + F + "python" + NL + "print(1)" + NL + F + NL);
          const leaf = app.workspace.getLeaf("tab");
          const sections = () => (leaf.view.previewMode && leaf.view.previewMode.renderer.sections || []).filter((s) => s && s.el);
          const chatTurns = async () => ((await (await fetch(SIDE + "/chat?session=" + encodeURIComponent("note:" + path))).json()).turns || []);
          const out = {};
          try {
            await leaf.openFile(file, { state: { mode: "preview" } });
            app.workspace.setActiveLeaf(leaf, { focus: true });
            await until(() => sections().some((s) => (s.el.textContent || "").includes("GammaMARK")), 8000);
            // The note in the store, so the marked address can be checked
            // against the store's own chunk for it.
            await plugin.indexNote(file, "check");
            const s = sections().find((x) => (x.el.textContent || "").includes("GammaMARK") && x.el.querySelector("p"));
            const node = s.el.querySelector("p").firstChild;
            const r = document.createRange(); r.setStart(node, 3); r.setEnd(node, 40);
            const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r);
            s.el.querySelector("p").dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
            await until(() => (marks.byNote[path] || []).length > 0, 8000);
            const resolved = await marks.resolve(file);
            const q = await (await fetch(SIDE + "/cypher", { method: "POST", headers: { "content-type": "application/json" },
              body: JSON.stringify({ query: "MATCH (c:Chunk {url: " + JSON.stringify(url) + "}) RETURN c.cid, c.md" }) })).json();
            const stored = Object.fromEntries((q.rows || []).map((x) => [x[0], x[1] || ""]));
            out.marked = resolved.map((m) => ({ cid: m.cid, in_store: m.cid in stored, store_has_gamma: (stored[m.cid] || "").includes("GammaMARK"), lines: [m.from, m.to] }));
            const chat = plugin.nbChats.forView(leaf.view);
            if (!chat) return { error: "no chat on the marked note" };
            await chat.reset();
            const t0 = await chat.send("Reply with the single word ok.");
            const turns = await chatTurns();
            const last = turns[turns.length - 1] || {};
            out.clean = { source: chat.lastSource, sent: (last.context || []).map((c) => c.cid), heads: (last.context || []).map((c) => c.head),
                          reply: String((t0 && t0.reply) || "").slice(0, 60) };
            chat.plantIgnoreMarks = true;
            try {
              await chat.reset();
              chat.land(true);
              const t1 = await chat.send("Reply with the single word ok.");
              const turns1 = await chatTurns();
              const l1 = turns1[turns1.length - 1] || {};
              out.planted = { source: chat.lastSource, sent: (l1.context || []).map((c) => c.cid), heads: (l1.context || []).map((c) => c.head) };
            } finally { chat.plantIgnoreMarks = false; }
            return out;
          } finally {
            await marks.clear(path);
            leaf.detach();
            try { await app.vault.delete(file); } catch (e) { /* gone */ }
          }
        })()`, { timeout: 300000 });
        const want = (got.marked || []).map((m) => m.cid).sort().join();
        return {
          pass: !got.error && got.marked.length >= 1 && got.marked.every((m) => m.in_store) && got.marked.some((m) => m.store_has_gamma)
                && got.clean.source === "marks" && got.clean.sent.slice().sort().join() === want
                && got.planted.source === "rewind" && got.planted.sent.length >= 1 && !got.planted.sent.some((c) => want.split(",").includes(c)),
          evidence: got,
        };
      },
    },
    {
      id: "P-M5",
      asks: "the hovering chat sits below the boundary of the scrollable markdown window: while the selected cell's foot is in view it is at that foot (L-2); scrolled away, and in a marked note's reading view, the collapsed strip rests in a band BELOW the scroller's bottom edge and the note's last line scrolls clear of it; planted (plantNoDock) the strip lies over the scroll window",
      async run() {
        // PLUGIN_GOAL: "the hovering chat is always below the boundary of the
        // scrollable markdown window".
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const plugin = app.plugins.getPlugin("domvec-bridge");
          const NL = String.fromCharCode(10), F = String.fromCharCode(96).repeat(3);
          const folder = "domvec-checks";
          if (!app.vault.getAbstractFileByPath(folder)) await app.vault.createFolder(folder);
          const stamp = Date.now();
          const cell = (k) => "## Cell " + k + NL + NL + "Prose line. ".repeat(30) + NL + NL + F + "python" + NL + "print(" + k + ")" + NL + F + NL;
          const nb = await app.vault.create(folder + "/pm5 notebook " + stamp + ".md", "# pm5" + NL + NL + [1, 2, 3, 4, 5, 6, 7, 8].map(cell).join(NL) + NL + "LAST LINE OF THE NOTE" + NL);
          const sec = (n) => "## " + n + NL + NL + (n + " words. ").repeat(60) + NL;
          const plain = await app.vault.create(folder + "/pm5 note " + stamp + ".md", "# pm5 plain" + NL + NL + ["Alpha", "Beta", "Gamma", "Delta", "Epsilon"].map(sec).join(NL));
          const box = (e) => { const b = e.getBoundingClientRect(); return { top: Math.round(b.top), bottom: Math.round(b.bottom) }; };
          const leaf = app.workspace.getLeaf("tab");
          const out = {};
          try {
            await leaf.openFile(nb, { state: { mode: "source", source: false } });
            app.workspace.setActiveLeaf(leaf, { focus: true });
            await sleep(800);
            leaf.view.editor.setCursor({ line: 6, ch: 0 });
            await sleep(500);
            const chat = plugin.nbChats.forView(leaf.view);
            if (!chat) return { error: "no chat on the notebook" };
            chat.land(true); await sleep(400);
            const sc = leaf.view.contentEl.querySelector(".cm-scroller");
            out.at_foot = { scroller: box(sc), chat: box(chat.el), docked: chat.docked };
            sc.scrollTop = 1e7; await sleep(600); chat.place();
            const last = Array.from(sc.querySelectorAll(".cm-line")).find((l) => (l.textContent || "").includes("LAST LINE"));
            out.scrolled = { scroller: box(sc), chat: box(chat.el), docked: chat.docked, last: last ? box(last) : null };
            chat.plantNoDock = true;
            try {
              chat.land(true); await sleep(300); sc.scrollTop = 1e7; await sleep(400); chat.place();
              out.planted = { scroller: box(sc), chat: box(chat.el) };
            } finally { chat.plantNoDock = false; chat.land(true); }
            // A native note, marked in reading view: no cells, the chat docked.
            await leaf.openFile(plain, { state: { mode: "preview" } });
            await sleep(1200);
            const secs = (leaf.view.previewMode.renderer.sections || []).filter((s) => s && s.el);
            const s = secs.find((x) => (x.el.textContent || "").includes("Gamma words") && x.el.querySelector("p"));
            const node = s.el.querySelector("p").firstChild;
            const r = document.createRange(); r.setStart(node, 0); r.setEnd(node, 20);
            const sel = window.getSelection(); sel.removeAllRanges(); sel.addRange(r);
            s.el.querySelector("p").dispatchEvent(new MouseEvent("mouseup", { bubbles: true }));
            for (let i = 0; i < 40 && !(plugin.marks.byNote[plain.path] || []).length; i++) await sleep(200);
            await sleep(500);
            const c2 = plugin.nbChats.forView(leaf.view);
            const rv = leaf.view.contentEl.querySelector(".markdown-reading-view");
            if (c2) c2.place();
            out.reading = { marked: (plugin.marks.byNote[plain.path] || []).length, scroller: rv ? box(rv) : null,
                            chat: c2 ? box(c2.el) : null, docked: c2 ? c2.docked : null };
            return out;
          } finally {
            await plugin.marks.clear(plain.path);
            leaf.detach();
            for (const f of [nb, plain]) { try { await app.vault.delete(f); } catch (e) { /* gone */ } }
          }
        })()`, { timeout: 120000 });
        const below = (x) => !!x && !!x.chat && !!x.scroller && x.chat.top >= x.scroller.bottom - 1;
        return {
          pass: !got.error
                && !got.at_foot.docked && got.at_foot.chat.bottom <= got.at_foot.scroller.bottom
                && got.scrolled.docked && below(got.scrolled) && !!got.scrolled.last && got.scrolled.last.bottom <= got.scrolled.chat.top
                && got.reading.marked >= 1 && got.reading.docked && below(got.reading)
                && got.planted.chat.top < got.planted.scroller.bottom - 1,
          evidence: got,
        };
      },
    },
    {
      id: "P-C1",
      asks: "a code module opens standalone in the code artifact panel -- its file on the source side, its chunks on the trie side -- editable for this repository: an edit through the editor, saved, is on disk; an installed package's module opens read-only with no save; planted (source-not-written) a save leaves the file as it was",
      async run() {
        // Addendum I: "Full code artifacts should be viewable and editable as
        // standalone as well. A terminal only below the artifact panel should
        // always accompany the artifact" -- "we can view live delta updates to
        // modules as well in both sides of their panels and their UMAP 3D
        // graph view". One scratch module of this repository, made, opened in
        // the code artifact panel, edited through its editor, then removed.
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const until = async (ok, ms) => { for (let t = 0; t < ms && !(await ok()); t += 200) await sleep(200); return !!(await ok()); };
          const plugin = app.plugins.getPlugin("domvec-bridge");
          const SIDE = String(plugin.settings.sidecar).replace(/[/]+$/, "");
          const H = { "content-type": "application/json", "X-Domvec-Client": "obsidian-plugin" };
          const plant = (name, on) => fetch(SIDE + "/plant", { method: "POST", headers: H, body: JSON.stringify({ name, on }) });
          const stamp = Date.now();
          const rel = "_pc_check_" + stamp + ".py", url = "code://repo/" + rel, vpath = "domvec/" + rel;
          const NL = String.fromCharCode(10), Q = String.fromCharCode(34).repeat(3);
          const src = [Q + "Probe module for the code artifact check." + Q, "", "", "def alpha(x):", "    " + Q + "Alpha doubles x." + NL + NL + "    " + "Alpha explains its doubling at length. ".repeat(24) + Q,
                       "    return 2 * x", "", "", "def beta(y):", "    " + Q + "Beta adds one." + NL + NL + "    " + "Beta explains its increment at length. ".repeat(24) + Q, "    return y + 1", ""].join(NL);
          await app.vault.adapter.write(vpath, src);
          await plugin.sidecar.saveSource(url, src);
          const view = await plugin.openCode(url);
          if (!view) return { error: "no code view" };
          await until(() => !!view.editor && view.text() === src, 8000);
          const edit = (from, to) => { const t = view.text(), i = t.indexOf(from); view.editor.dispatch({ changes: { from: i, to: i + from.length, insert: to } }); };
          const button = (v, label) => Array.from(v.contentEl.querySelectorAll(".domvec-code-head button")).find((b) => b.textContent === label);
          const save = async () => { const n = view.stats.saves; button(view, "save").click(); await until(() => view.stats.saves > n && !view.dirty, 20000); await sleep(300); };
          const out = {};
          try {

            out.open = { editable: view.editable, text_matches: view.text() === src,
                         trie_chunks: view.contentEl.querySelectorAll(".domvec-code-chunk").length,
                         trie_has_docstring: (view.contentEl.querySelector(".domvec-code-trie").textContent || "").includes("Alpha doubles") };
            edit("Beta adds one.", "Beta adds one, edited " + stamp + ".");
            out.dirty = view.dirty;
            await save();
            out.saved = { on_disk: (await app.vault.adapter.read(vpath)).includes("edited " + stamp), reply: view.stats.last };
            const ro = await plugin.openCode("code://pypi/json/__init__.py");
            await until(() => !!ro && !!ro.editor && ro.text().length > 0, 8000);
            out.pypi = { editable: ro.editable, read_only: ro.editor.state.readOnly, save_button: !!button(ro, "save"),
                         has_text: ro.text().includes("def dumps") };
            await plant("source-not-written", true);
            try {
              edit("edited " + stamp, "edited twice " + stamp);
              await save();
              out.planted = { on_disk: (await app.vault.adapter.read(vpath)).includes("twice " + stamp) };
            } finally { await plant("source-not-written", false); }
            return out;

          } finally {
            for (const l of app.workspace.getLeavesOfType("domvec-code-view")) l.detach();
            try { await app.vault.adapter.remove(vpath); } catch (e) { /* gone */ }
            await plugin.sidecar.purge(url);
          }
        })()`, { timeout: 120000 });
        return { pass: !got.error && got.open.editable && got.open.text_matches && got.open.trie_chunks >= 2 && got.open.trie_has_docstring
                && got.dirty && got.saved.on_disk && got.pypi.editable === false && got.pypi.read_only && !got.pypi.save_button
                && got.pypi.has_text && got.planted.on_disk === false, evidence: got };
      },
    },
    {
      id: "P-C2",
      asks: "a kernel run-and-output surface is always directly below the artifact, across its full width: run executes the module in a kernel of its own, and an expression typed below is evaluated in that namespace (alpha(21) -> 42); planted (plantOtherKernel) the expression meets another kernel -- NameError",
      async run() {
        // Addendum I: "Full code artifacts should be viewable and editable as
        // standalone as well. A terminal only below the artifact panel should
        // always accompany the artifact" -- "we can view live delta updates to
        // modules as well in both sides of their panels and their UMAP 3D
        // graph view". One scratch module of this repository, made, opened in
        // the code artifact panel, edited through its editor, then removed.
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const until = async (ok, ms) => { for (let t = 0; t < ms && !(await ok()); t += 200) await sleep(200); return !!(await ok()); };
          const plugin = app.plugins.getPlugin("domvec-bridge");
          const SIDE = String(plugin.settings.sidecar).replace(/[/]+$/, "");
          const H = { "content-type": "application/json", "X-Domvec-Client": "obsidian-plugin" };
          const plant = (name, on) => fetch(SIDE + "/plant", { method: "POST", headers: H, body: JSON.stringify({ name, on }) });
          const stamp = Date.now();
          const rel = "_pc_check_" + stamp + ".py", url = "code://repo/" + rel, vpath = "domvec/" + rel;
          const NL = String.fromCharCode(10), Q = String.fromCharCode(34).repeat(3);
          const src = [Q + "Probe module for the code artifact check." + Q, "", "", "def alpha(x):", "    " + Q + "Alpha doubles x." + NL + NL + "    " + "Alpha explains its doubling at length. ".repeat(24) + Q,
                       "    return 2 * x", "", "", "def beta(y):", "    " + Q + "Beta adds one." + NL + NL + "    " + "Beta explains its increment at length. ".repeat(24) + Q, "    return y + 1", ""].join(NL);
          await app.vault.adapter.write(vpath, src);
          await plugin.sidecar.saveSource(url, src);
          const view = await plugin.openCode(url);
          if (!view) return { error: "no code view" };
          await until(() => !!view.editor && view.text() === src, 8000);
          const edit = (from, to) => { const t = view.text(), i = t.indexOf(from); view.editor.dispatch({ changes: { from: i, to: i + from.length, insert: to } }); };
          const button = (v, label) => Array.from(v.contentEl.querySelectorAll(".domvec-code-head button")).find((b) => b.textContent === label);
          const save = async () => { const n = view.stats.saves; button(view, "save").click(); await until(() => view.stats.saves > n && !view.dirty, 20000); await sleep(300); };
          const out = {};
          try {

            const box = (sel) => { const b = view.contentEl.querySelector(sel).getBoundingClientRect(); return { top: Math.round(b.top), bottom: Math.round(b.bottom), left: Math.round(b.left), right: Math.round(b.right) }; };
            out.layout = { sides: box(".domvec-code-sides"), run: box(".domvec-code-run") };
            const ask = async (expr) => {
              const n = view.stats.runs, inp = view.contentEl.querySelector(".domvec-code-input");
              inp.value = expr; inp.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
              await until(() => view.stats.runs > n, 5000);
              await until(() => (view.contentEl.querySelector(".domvec-code-out").textContent || "").includes(">>> " + expr + NL), 20000);
              await sleep(800);
              const t = view.contentEl.querySelector(".domvec-code-out").textContent || "";
              return t.slice(t.lastIndexOf(">>> " + expr));
            };
            const n0 = view.stats.runs;
            button(view, "run").click();
            await until(() => view.stats.runs > n0, 5000);
            await sleep(2500);
            out.run_module = (view.contentEl.querySelector(".domvec-code-out").textContent || "").slice(0, 200);
            out.alpha = await ask("alpha(21)");
            view.plantOtherKernel = true;
            try { out.planted = await ask("beta(1)"); } finally { view.plantOtherKernel = false; }
            return out;

          } finally {
            for (const l of app.workspace.getLeavesOfType("domvec-code-view")) l.detach();
            try { await app.vault.adapter.remove(vpath); } catch (e) { /* gone */ }
            await plugin.sidecar.purge(url);
          }
        })()`, { timeout: 120000 });
        return { pass: !got.error && got.layout.run.top >= got.layout.sides.bottom - 1 && got.layout.run.top - got.layout.sides.bottom <= 3
                && got.layout.run.left <= got.layout.sides.left + 1 && got.layout.run.right >= got.layout.sides.right - 1
                && /\b42\b/.test(got.alpha) && !/Error/.test(got.alpha) && /NameError/.test(got.planted), evidence: got };
      },
    },
    {
      id: "P-C5",
      asks: "a saved edit to a module is a live delta in both halves and the 3D view: the trie side re-reads the store and marks exactly the chunk that changed (not its neighbour), and that chunk reaches the projector's delta stream; planted (plantNoTrieRefresh) the trie side keeps the old text, planted (source-not-projected) the chunk never reaches the stream",
      async run() {
        // Addendum I: "Full code artifacts should be viewable and editable as
        // standalone as well. A terminal only below the artifact panel should
        // always accompany the artifact" -- "we can view live delta updates to
        // modules as well in both sides of their panels and their UMAP 3D
        // graph view". One scratch module of this repository, made, opened in
        // the code artifact panel, edited through its editor, then removed.
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const until = async (ok, ms) => { for (let t = 0; t < ms && !(await ok()); t += 200) await sleep(200); return !!(await ok()); };
          const plugin = app.plugins.getPlugin("domvec-bridge");
          const SIDE = String(plugin.settings.sidecar).replace(/[/]+$/, "");
          const H = { "content-type": "application/json", "X-Domvec-Client": "obsidian-plugin" };
          const plant = (name, on) => fetch(SIDE + "/plant", { method: "POST", headers: H, body: JSON.stringify({ name, on }) });
          const stamp = Date.now();
          const rel = "_pc_check_" + stamp + ".py", url = "code://repo/" + rel, vpath = "domvec/" + rel;
          const NL = String.fromCharCode(10), Q = String.fromCharCode(34).repeat(3);
          const src = [Q + "Probe module for the code artifact check." + Q, "", "", "def alpha(x):", "    " + Q + "Alpha doubles x." + NL + NL + "    " + "Alpha explains its doubling at length. ".repeat(24) + Q,
                       "    return 2 * x", "", "", "def beta(y):", "    " + Q + "Beta adds one." + NL + NL + "    " + "Beta explains its increment at length. ".repeat(24) + Q, "    return y + 1", ""].join(NL);
          await app.vault.adapter.write(vpath, src);
          await plugin.sidecar.saveSource(url, src);
          const view = await plugin.openCode(url);
          if (!view) return { error: "no code view" };
          await until(() => !!view.editor && view.text() === src, 8000);
          const edit = (from, to) => { const t = view.text(), i = t.indexOf(from); view.editor.dispatch({ changes: { from: i, to: i + from.length, insert: to } }); };
          const button = (v, label) => Array.from(v.contentEl.querySelectorAll(".domvec-code-head button")).find((b) => b.textContent === label);
          const save = async () => { const n = view.stats.saves; button(view, "save").click(); await until(() => view.stats.saves > n && !view.dirty, 20000); await sleep(300); };
          const out = {};
          try {

            const delta0 = await (await fetch(SIDE + "/projector/delta?since=0&epoch=-1")).json();
            let since = delta0.seq, epoch = delta0.epoch;
            const watch = async (cids, ms) => {
              const want = new Set(cids), seen = new Set(), t0 = performance.now();
              while (performance.now() - t0 < ms && seen.size < want.size) {
                await sleep(250);
                const d = await (await fetch(SIDE + "/projector/delta?since=" + since + "&epoch=" + epoch)).json();
                if (d.reload) { epoch = d.epoch; since = d.seq; continue; }
                for (const c of Object.keys(d.chunks || {})) if (want.has(c)) seen.add(c);
                since = d.seq;
              }
              return { seen: seen.size, ms: Math.round(performance.now() - t0) };
            };
            const trieText = () => view.contentEl.querySelector(".domvec-code-trie").textContent || "";
            const marked = () => Array.from(view.contentEl.querySelectorAll(".domvec-code-chunk.is-changed")).map((e) => e.textContent || "");
            // Settle the first index's own projection before measuring.
            await sleep(4000);
            const d1 = await (await fetch(SIDE + "/projector/delta?since=" + since + "&epoch=" + epoch)).json();
            if (!d1.reload) since = d1.seq; else { epoch = d1.epoch; since = d1.seq; }
            edit("Alpha doubles x.", "Alpha doubles x, revised " + stamp + ".");
            await save();
            const changed = [...view.changed];
            out.clean = { reply: view.stats.last, changed: changed.length,
                          marked_has_revision: marked().some((t) => t.includes("revised " + stamp)),
                          beta_marked: marked().some((t) => t.includes("Beta adds one")),
                          delta: await watch(changed, 40000) };
            view.plantNoTrieRefresh = true;
            try {
              edit("revised " + stamp, "revised again " + stamp);
              await save();
              out.planted_no_refresh = { trie_has_new: trieText().includes("again " + stamp) };
            } finally { view.plantNoTrieRefresh = false; }
            await view.readTrie();
            await sleep(3000);
            const d2 = await (await fetch(SIDE + "/projector/delta?since=" + since + "&epoch=" + epoch)).json();
            if (!d2.reload) since = d2.seq; else { epoch = d2.epoch; since = d2.seq; }
            await plant("source-not-projected", true);
            try {
              edit("revised again " + stamp, "revised thrice " + stamp);
              await save();
              out.planted_not_projected = { changed: view.changed.size, delta: await watch([...view.changed], 20000) };
            } finally { await plant("source-not-projected", false); }
            return out;

          } finally {
            for (const l of app.workspace.getLeavesOfType("domvec-code-view")) l.detach();
            try { await app.vault.adapter.remove(vpath); } catch (e) { /* gone */ }
            await plugin.sidecar.purge(url);
          }
        })()`, { timeout: 240000 });
        return { pass: !got.error && got.clean.changed >= 1 && got.clean.marked_has_revision && !got.clean.beta_marked
                && got.clean.delta.seen >= 1 && got.planted_no_refresh.trie_has_new === false
                && got.planted_not_projected.changed >= 1 && got.planted_not_projected.delta.seen === 0, evidence: got };
      },
    },
    {
      id: "P-M3",
      asks: "code, kernel and terminal options are built ON TOP OF the native form: one note, opened as Obsidian's own 'markdown' view (no domvec view type for it), carries all of them in place -- a kernel run and a terminal on its code fence, the add-cell strip at its foot -- in live preview and in reading view; planted (__domvecPlantNoTermFence) the terminal option is gone from the native view",
      async run() {
        // PLUGIN_GOAL: "we build on this native form to include code, kernel,
        // and terminal options". P-N3 and P-M4 run each option; this asks
        // where they live.
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const NL = String.fromCharCode(10), F = String.fromCharCode(96).repeat(3);
          const folder = "domvec-checks";
          if (!app.vault.getAbstractFileByPath(folder)) await app.vault.createFolder(folder);
          const file = await app.vault.create(folder + "/pm3 note " + Date.now() + ".md", "# pm3" + NL + NL + "Prose." + NL + NL + F + "python" + NL + "print(3)" + NL + F + NL);
          const ours = () => { const n = []; app.workspace.iterateAllLeaves((l) => { const t = l.view.getViewType(); if (t.startsWith("domvec-") && l.view.file === file) n.push(t); }); return n; };
          const look = async (leaf, mode) => {
            await leaf.setViewState({ type: "markdown", state: { file: file.path, mode, source: false } });
            await sleep(1200);
            const el = leaf.view.containerEl;
            return { type: leaf.view.getViewType(), mode: leaf.view.getMode(),
                     run: !!el.querySelector(".domvec-run-fence"), terminal: !!el.querySelector(".domvec-term-fence"),
                     cells: !!el.querySelector(".domvec-cellbar"), cell_buttons: el.querySelectorAll(".domvec-cellbar-add").length };
          };
          const leaf = app.workspace.getLeaf("tab");
          const out = {};
          try {
            out.live = await look(leaf, "source");
            out.reading = await look(leaf, "preview");
            out.domvec_views_for_note = ours();
            window.__domvecPlantNoTermFence = true;
            try {
              await leaf.setViewState({ type: "markdown", state: { file: "", mode: "source" } });
              out.planted = await look(leaf, "source");
            } finally { window.__domvecPlantNoTermFence = false; }
            return out;
          } finally {
            leaf.detach();
            try { await app.vault.delete(file); } catch (e) { /* gone */ }
          }
        })()`, { timeout: 60000 });
        const all = (x) => !!x && x.type === "markdown" && x.run && x.terminal && x.cells && x.cell_buttons >= 2;
        return {
          pass: !got.error && all(got.live) && got.live.mode === "source" && all(got.reading) && got.reading.mode === "preview"
                && got.domvec_views_for_note.length === 0 && got.planted.type === "markdown" && got.planted.run && !got.planted.terminal,
          evidence: got,
        };
      },
    },
    {
      id: "G-36-notebook",
      asks: "the browser cell is ONE component with two hosts: a ```browser fence in a notebook renders the same domvec-browser-view the standalone pane is (outside the workspace's tree), loads its page, and its sensor puts that page in the store; dragging the cell's frame resizes the page's viewport, and so does narrowing the notebook's pane; closing the note detaches it; planted (__domvecPlantNoNotebookBrowser) the fence stays plain text",
      async run() {
        // Addendum IV: "the webbrowser notebook cells should be actual electron
        // browser cells, resizable within the notebook, as well as allowing it
        // to resize along with the rest of the notebook within its panel
        // window" -- "the completeness of functionalities are the same".
        const fixtures = await serveFixtures();
        try {
          const got = await evaluate(`(async () => {
            const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
            const until = async (ok, ms) => { for (let t = 0; t < ms && !(await ok()); t += 250) await sleep(250); return !!(await ok()); };
            const plugin = app.plugins.getPlugin("domvec-bridge");
            const NL = String.fromCharCode(10), F = String.fromCharCode(96).repeat(3);
            const folder = "domvec-checks";
            if (!app.vault.getAbstractFileByPath(folder)) await app.vault.createFolder(folder);
            const PAGE = ${JSON.stringify(fixtures.origin + "/media_kinds.html?g36nb=")} + Date.now();
            const path = folder + "/g36 notebook " + Date.now() + ".md";
            const file = await app.vault.create(path, "# g36" + NL + NL + "A notebook with a browser cell." + NL + NL + F + "browser" + NL + PAGE + NL + F + NL + NL + F + "python" + NL + "print(1)" + NL + F + NL);
            // The note's fence renders twice (reading view, and the live-preview
            // editor kept behind it); only the SEEN one holds a browser.
            const cellsOf = () => [...window.__domvecNotebookBrowsers].filter((c) => c.sourcePath === path);
            const cellOf = () => cellsOf().find((c) => c.containerEl.offsetWidth > 0 && c.view);
            const standalone0 = app.workspace.getLeavesOfType("domvec-browser-view").length;
            const leaf = app.workspace.getLeaf("tab");
            const out = {};
            try {
              await leaf.openFile(file, { state: { mode: "preview" } });
              app.workspace.setActiveLeaf(leaf, { focus: true });
              out.rendered = await until(() => !!cellOf() && !!cellOf().view && !!cellOf().view.webview, 10000);
              const cell = cellOf();
              if (!cell) return { error: "no browser cell in the note", cells: cellsOf().length };
              out.renders = { cells: cellsOf().length, live_browsers: cellsOf().filter((c) => !!c.leaf).length };
              const v = cell.view, wv = v.webview;
              out.same_component = { type: v.getViewType(), in_note: leaf.view.containerEl.contains(cell.containerEl),
                                     in_workspace_tree: app.workspace.getLeavesOfType("domvec-browser-view").length - standalone0,
                                     toolbar: [...v.contentEl.querySelectorAll("button")].map((b) => (b.textContent || "").trim()).filter(Boolean).slice(0, 8) };
              out.loaded = await until(() => { try { return wv.getURL() === PAGE && !wv.isLoading(); } catch (e) { return false; } }, 30000);
              out.url_now = (() => { try { return { url: cell.view.webview.getURL(), same_webview: cell.view.webview === wv, loading: cell.view.webview.isLoading(), mounts: cell.mounts, unmounts: cell.unmounts }; } catch (e) { return String(e.message); } })();
              // The sensor in the notebook's cell, writing the store.
              let cids = [];
              for (let i = 0; i < 40 && !cids.length; i++) { await sleep(1000); cids = await plugin.sidecar.pageCids(PAGE); }
              out.stored_chunks = cids.length;
              const size = async () => { try { return await wv.executeJavaScript("[innerWidth, innerHeight]"); } catch (e) { return null; } };
              const frame = cell.containerEl;
              frame.style.height = "300px"; await sleep(900); const small = await size();
              frame.style.height = "620px"; await sleep(900); const tall = await size();
              const pane = leaf.view.containerEl;
              const w0 = pane.style.width;
              pane.style.width = "55%"; await sleep(900); const narrow = await size();
              pane.style.width = w0; await sleep(900); const wide = await size();
              out.resize = { small, tall, narrow, wide };
              leaf.detach();
              await sleep(600);
              out.detached = cellsOf().length === 0;
              window.__domvecPlantNoNotebookBrowser = true;
              const leaf2 = app.workspace.getLeaf("tab");
              try {
                await leaf2.openFile(file, { state: { mode: "preview" } });
                await sleep(1500);
                out.planted = { cell: cellsOf().length > 0, webviews: leaf2.view.containerEl.querySelectorAll("webview").length,
                                plain_url: (leaf2.view.containerEl.textContent || "").includes(PAGE) };
              } finally { window.__domvecPlantNoNotebookBrowser = false; leaf2.detach(); }
              return out;
            } finally {
              try { leaf.detach(); } catch (e) { /* gone */ }
              try { await app.vault.delete(file); } catch (e) { /* gone */ }
            }
          })()`, { timeout: 180000 });
          const r = got.resize || {};
          const ok = (a) => Array.isArray(a) && a[0] > 50 && a[1] > 50;
          return {
            pass: !got.error && got.rendered && got.renders.live_browsers === 1 && got.same_component.type === "domvec-browser-view" && got.same_component.in_note
                  && got.same_component.in_workspace_tree === 0 && got.loaded && got.stored_chunks > 0
                  && ok(r.small) && ok(r.tall) && r.tall[1] > r.small[1] + 200 && ok(r.narrow) && ok(r.wide) && r.wide[0] > r.narrow[0] + 50
                  && got.detached && !!got.planted && !got.planted.cell && got.planted.webviews === 0 && got.planted.plain_url,
            evidence: { ...got, purged: await tidyFixtures(fixtures.origin) },
          };
        } finally { await fixtures.close(); }
      },
    },
    {
      id: "P-N4",
      asks: "a facade over the vault exposes a note's kernel to the file structure: run with the real Run control, a cell starts in its note's own folder, reads the file beside its note by name, and writes a note through Vault that Obsidian's vault then holds; planted (no-vault) a cell has no Vault and does not start beside its note",
      async run() {
        // Addendum I: "make the most of our vault interface that obsidian
        // already has that can be directly provided a facade for to expose
        // local jupyter terminals to the filestructure and space".
        const plant = (name, on) => fetch(SIDECAR + "/plant", { method: "POST",
          headers: { "content-type": "application/json", "X-Domvec-Client": "obsidian-plugin" }, body: JSON.stringify({ name, on }) });
        const arm = (planted) => evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const until = async (ok, ms) => { for (let t = 0; t < ms && !(await ok()); t += 250) await sleep(250); return !!(await ok()); };
          const NL = String.fromCharCode(10), F = String.fromCharCode(96).repeat(3);
          const folder = "domvec-checks/pn4 lab " + Date.now() + (${planted} ? "p" : "c");
          await app.vault.createFolder(folder);
          await app.vault.create(folder + "/data.csv", "species,count" + NL + "okapi,2" + NL);
          const code = ["import os", "print('cwd', os.path.basename(os.getcwd()))", "print('beside', open('data.csv').read().splitlines()[0])",
                        "print('wrote', Vault.write('made by a cell.md', '# Made by a cell'))"].join(NL);
          const file = await app.vault.create(folder + "/notebook.md", "# lab" + NL + NL + F + "python" + NL + code + NL + F + NL);
          const leaf = app.workspace.getLeaf("tab");
          try {
            await leaf.openFile(file, { state: { mode: "source", source: false } });
            await until(() => !!leaf.view.containerEl.querySelector(".domvec-run-fence"), 8000);
            leaf.view.containerEl.querySelector(".domvec-run-fence").click();
            await until(() => leaf.view.editor.getValue().includes("nb-output"), 30000);
            await sleep(400);
            const text = leaf.view.editor.getValue();
            const outBlock = text.slice(text.indexOf("nb-output"));
            const made = folder + "/made by a cell.md";
            const seen = await until(() => !!app.vault.getAbstractFileByPath(made), 6000);
            return { planted: ${planted}, folder,
                     cwd_is_note_folder: outBlock.includes("cwd " + folder.split("/").pop()),
                     read_beside: outBlock.includes("beside species,count"),
                     wrote: outBlock.includes("wrote " + made), vault_holds_it: seen,
                     error: (outBlock.match(/(NameError|FileNotFoundError|PermissionError)[^\\n]*/) || [""])[0],
                     output: outBlock.slice(0, 300) };
          } finally {
            leaf.detach();
            const f = app.vault.getAbstractFileByPath(folder);
            if (f) await app.vault.delete(f, true);
          }
        })()`, { timeout: 120000 });
        const clean = await arm(false);
        await plant("no-vault", true);
        let planted;
        try { planted = await arm(true); } finally { await plant("no-vault", false); }
        return {
          pass: !clean.error && clean.cwd_is_note_folder && clean.read_beside && clean.wrote && clean.vault_holds_it
                && !planted.cwd_is_note_folder && !planted.vault_holds_it && !!planted.error,
          evidence: { clean, planted },
        };
      },
    },
    {
      id: "P-N7",
      asks: "ONE interface centralizes retrieval and code research: in one notebook, search() run in a cell returns the database's hits; a package chunk from the 3D view becomes a running prototype cell; the same chunk panel is pulled into THIS note's chat and goes with its next prompt (its cid in the turn) while another notebook's chat never sees it; planted (plantDropPins) the pulled chunk is not sent",
      async run() {
        // Addendum I: "centralize retrieval and code research into one
        // interface where our chat contexts are localized to a panel, we can
        // pull existing chunk panels into a new chat ... and run code
        // experiments in the jupyter kernel terminals".
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const until = async (ok, ms) => { for (let t = 0; t < ms && !(await ok()); t += 250) await sleep(250); return !!(await ok()); };
          const plugin = app.plugins.getPlugin("domvec-bridge");
          const SIDE = String(plugin.settings.sidecar).replace(/[/]+$/, "");
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0]?.view;
          if (!v || !v.graph) return { error: "no graph" };
          const NL = String.fromCharCode(10), F = String.fromCharCode(96).repeat(3);
          const URL = "code://pypi/json/__init__.py";
          const folder = "domvec-checks";
          if (!app.vault.getAbstractFileByPath(folder)) await app.vault.createFolder(folder);
          const stamp = Date.now();
          const nb = await app.vault.create(folder + "/pn7 research " + stamp + ".md", "# research" + NL + NL + F + "python" + NL
            + "hits = search('radix tree', db=True, k=3)" + NL + "print('hits', len(hits), hits[0]['url'] if hits else '')" + NL + F + NL);
          const other = await app.vault.create(folder + "/pn7 other " + stamp + ".md", "# other" + NL + NL + F + "python" + NL + "print(2)" + NL + F + NL);
          const turnsOf = async (path) => ((await (await fetch(SIDE + "/chat?session=" + encodeURIComponent("note:" + path))).json()).turns || []);
          const leafO = app.workspace.getLeaf("tab");
          const leaf = app.workspace.getLeaf("tab");
          let cid = null, unfolded = null;
          const out = {};
          try {
            await leafO.openFile(other, { state: { mode: "source", source: false } });
            await leaf.openFile(nb, { state: { mode: "source", source: false } });
            app.workspace.setActiveLeaf(leaf, { focus: true });
            await sleep(700);
            out.notebook = plugin.lastNotebook === nb.path;
            const runs = () => leaf.view.containerEl.querySelectorAll(".domvec-run-fence");
            const outs = () => (leaf.view.editor.getValue().match(/nb-output/g) || []).length;
            // 1. Retrieval, in a cell.
            await until(() => runs().length >= 1, 8000);
            let n = outs(); runs()[0].click(); await until(() => outs() > n, 30000);
            const t1 = leaf.view.editor.getValue();
            const hitLine = (t1.match(/hits (\\d+) (\\S*)/) || []);
            out.retrieval = { hits: Number(hitLine[1] || 0), first: hitLine[2] || "" };
            // 2. Code research: a package chunk from the 3D view as a cell.
            for (const c of await v.sidecar.pageCids(URL)) { const p = await plugin.sidecar.prototype(c); if (p && p.name === "detect_encoding") { cid = c; break; } }
            if (!cid) return { error: "no detect_encoding chunk" };
            let node = v.graph.graphData().nodes.find((x) => x.id === cid);
            const page = v.graph.graphData().nodes.find((x) => x.id === "page:" + URL);
            if (!node && page) { await v.unfoldNode(page); unfolded = page; await until(() => !!v.graph.graphData().nodes.find((x) => x.id === cid), 8000); node = v.graph.graphData().nodes.find((x) => x.id === cid); }
            if (!node) return { error: "chunk not placeable" };
            for (const bb of v.billboardState()) v.closeBillboard(bb.id);
            await v.openBillboard(node);
            const ctl = (cls) => document.querySelector('.domvec-bb[data-cid="' + cid + '"] .' + cls);
            await until(() => !!ctl("domvec-bb-chat"), 8000);
            const made0 = plugin.prototypeStats.made;
            ctl("domvec-bb-cell").click();
            await until(() => plugin.prototypeStats.made > made0, 8000);
            await until(() => runs().length >= 2, 8000);
            n = outs(); runs()[1].click(); await until(() => outs() > n, 30000);
            const t2 = leaf.view.editor.getValue();
            out.prototype = { in_note: t2.includes("def detect_encoding(b):"), ran_ok: (t2.match(/status=ok/g) || []).length >= 2 };
            // 3. The same chunk panel pulled into THIS note's chat.
            const chat = plugin.nbChats.forView(leaf.view);
            await chat.reset();
            ctl("domvec-bb-chat").click();
            await until(() => chat.pins.some((p) => p.cid === cid), 5000);
            out.pinned = chat.pins.map((p) => p.cid);
            await chat.send("Reply with the single word ok.");
            const turns = await turnsOf(nb.path);
            const last = turns[turns.length - 1] || {};
            out.chat = { sent: (last.context || []).map((c) => c.cid), pins_after: chat.pins.length };
            out.other_chat_saw_it = (await turnsOf(other.path)).some((t) => (t.context || []).some((c) => c.cid === cid));
            // Planted: the pulled chunk is dropped.
            chat.plantDropPins = true;
            try {
              await chat.reset();
              ctl("domvec-bb-chat").click();
              await until(() => chat.pins.length > 0, 5000);
              await chat.send("Reply with the single word ok.");
              const tp = await turnsOf(nb.path);
              out.planted = { sent: ((tp[tp.length - 1] || {}).context || []).map((c) => c.cid) };
            } finally { chat.plantDropPins = false; chat.pins = []; }
            return out;
          } finally {
            if (cid) v.closeBillboard(cid);
            if (unfolded) await v.unfoldNode(unfolded);
            leaf.detach(); leafO.detach();
            for (const f of [nb, other]) { try { await app.vault.delete(f); } catch (e) { /* gone */ } }
          }
        })()`, { timeout: 300000 });
        return {
          pass: !got.error && got.notebook && got.retrieval.hits >= 1 && got.prototype.in_note && got.prototype.ran_ok
                && got.pinned.length === 1 && got.chat.sent.includes(got.pinned[0]) && got.chat.pins_after === 0
                && got.other_chat_saw_it === false && !got.planted.sent.includes(got.pinned[0]),
          evidence: got,
        };
      },
    },
    {
      id: "G-275",
      asks: "a flight plan is DRAWN in 3D -- a path through its targets in order, the leg being flown brighter -- and planned per mode with the throttle: in the map view the plan is drawn and holds (the camera does not move), in the ego view it flies leg by leg and the drawn leg follows, a throttle of 0 holds it where it is; planted (plantNoPlanDraw) the plan is flown but not drawn",
      async run() {
        // PLUGIN_GOAL items 8-9: "we can also draw flight plans for various
        // searches and anchored nodes within different modes. We will have a
        // throttle to set the speed, the pause, and be able to plan
        // efficiently that way." G-283 flies plans; this draws them.
        const got = await inPane(`
          for (let i = 0; i < 60 && !(v.graph && v.graph.graphData().nodes.length); i++) await sleep(500);
          app.workspace.revealLeaf(app.workspace.getLeavesOfType(TYPE)[0]);
          const a = v.agent, cam = () => v.graph.camera().position;
          const at = () => { const p = cam(); return [p.x, p.y, p.z]; };
          const moved = (p0) => { const p = cam(); return Math.round(Math.hypot(p.x - p0[0], p.y - p0[1], p.z - p0[2]) * 10) / 10; };
          const mode0 = a.mode, thr0 = a.throttle;
          const nodes = v.graph.graphData().nodes.filter((n) => n.url && Number.isFinite(n.x)).slice(0, 4);
          if (nodes.length < 4) return { error: "fewer than 4 placed nodes" };
          const out = {};
          try {
            // The switch to map recentres the camera itself: measured after.
            a.setMode("map"); a.setThrottle(1); await sleep(2500);
            a.setPlan(nodes); a.play(true);
            let p0 = at(); await sleep(2500);
            out.map = { points: v.planDrawn.points, visible: !!v.planGroup && v.planGroup.visible, plan_at: a.planAt, moved: moved(p0) };
            a.play(false); a.setMode("ego"); a.play(true);
            p0 = at();
            for (let i = 0; i < 80 && a.planAt < 1; i++) await sleep(250);
            await sleep(400);
            out.ego = { plan_at: a.planAt, drawn_leg: v.planDrawn.current, leg_visible: v.planGroup.children[1].visible, moved: moved(p0),
                        legs: a.planStats.legs };
            // Throttle 0: the craft brakes from its carried velocity (motion is
            // stateful, item 21), then holds -- measured once at rest.
            a.setThrottle(0);
            for (let i = 0; i < 40 && a.stats.speed > 0.05; i++) await sleep(100);
            const held = a.planAt; p0 = at(); await sleep(2500);
            out.throttle_zero = { plan_at_before: held, plan_at_after: a.planAt, moved: moved(p0) };
            v.plantNoPlanDraw = true;
            await sleep(400);
            out.planted = { points: v.planDrawn.points, visible: !!v.planGroup && v.planGroup.visible, still_planned: a.plan.length };
            return out;
          } finally {
            v.plantNoPlanDraw = false;
            a.play(false); a.setPlan([]); a.setThrottle(thr0); a.setMode(mode0);
          }
        `);
        return {
          pass: !got.error && got.map.points === 4 && got.map.visible && got.map.plan_at === -1 && got.map.moved < 0.5
                && got.ego.plan_at >= 1 && got.ego.drawn_leg === got.ego.plan_at && got.ego.leg_visible && got.ego.moved > 1
                && got.throttle_zero.plan_at_after === got.throttle_zero.plan_at_before && got.throttle_zero.moved < 1
                && got.planted.points === 0 && !got.planted.visible && got.planted.still_planned === 4,
          evidence: got,
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
          // The graph must GROW only when there was something new to place:
          // landing on a page now places all of it (whole-page placement), so
          // a scoped query on the page being read finds every hit already
          // drawn -- and correctly adds nothing. What must still happen is the
          // page opening around them.
          pass: got.hits_drawn > 0
             && (got.nodes_after > got.nodes_before
                 || got.already_drawn >= got.scoped_hits)
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
          // A leaf in a background tab hands back a DEFERRED stub with none of
          // the view's methods on it. Fronting the projector backgrounds the
          // browser cell, so this has to be forced before .view is read --
          // otherwise b.webview is undefined and it reads as no browser pane.
          for (const l of app.workspace.getLeavesOfType("domvec-browser-view")) {
            if (l.loadIfDeferred) await l.loadIfDeferred();
          }
          for (const l of app.workspace.getLeavesOfType("domvec-graph-view")) {
            if (l.loadIfDeferred) await l.loadIfDeferred();
          }
          // Loaded is not the same as USABLE. loadIfDeferred resolves before
          // the guest emits dom-ready, and every webview method then throws
          // "The WebView must be attached to the DOM and the dom-ready event
          // emitted". Poll the cheapest one until it stops throwing.
          for (let i = 0; i < 80; i++) {
            const l0 = app.workspace.getLeavesOfType("domvec-browser-view")[0];
            const w = l0 && l0.view && l0.view.webview;
            if (!w) break;
            try { w.getURL(); break; } catch (e) { await sleep(250); }
          }
          // And usable is still not VISIBLE. A leaf in a background tab has no
          // layout, so the guest reports innerWidth/innerHeight of 0 and every
          // click coordinate computed from a rect is meaningless -- the aim
          // came out at (15, 319) in a 0x0 viewport and read as the link not
          // being followed. Front the cell and wait for it to have a size.
          {
            const l0 = app.workspace.getLeavesOfType("domvec-browser-view")[0];
            if (l0) {
              app.workspace.revealLeaf(l0);
              for (let i = 0; i < 60; i++) {
                await sleep(250);
                try {
                  const size = await l0.view.webview.executeJavaScript(
                    "[window.innerWidth, window.innerHeight]");
                  if (size && size[0] > 50 && size[1] > 50) break;
                } catch (e) { /* not ready yet */ }
              }
            }
          }
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
          // The LANDING first: a page's projected chunks now arrive with its
          // chunk map (S-1), asynchronously -- reset before they land and they
          // count as the baseline, and the hits placed later were already
          // drawn ("0 arrived", 2026-09-27).
          for (let i = 0; i < 40; i++) {
            const m = b.pipebox && b.pipebox.map;
            if (m && m.url === want && m.loadedAt > 0) break;
            await sleep(200);
          }
          await sleep(800);
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
          //
          // **And the tolerance has to match the defect, not the neighbourhood.**
          // A PLACED chunk is extrapolated past the ends of a fit taken over
          // page means, so falling outside +/-300 is the ordinary case, not an
          // edge one: measured here, six placed nodes spanned -181 to -349.
          // Against that population a +/-0.5 window round 300 is a coin toss,
          // and it flagged a node at -300.40 whose neighbours sat at -289 and
          // -295. That is a detector reporting arithmetic, not a clamp.
          //
          // D-17's signature was EXACTNESS and PILE-UP: every node framed to
          // exactly -300 or +300, 26 of them at one point. So the test is
          // exactness, and the pile-up is counted beside it.
          const CLAMPED = 1e-3;
          const onFrame = fresh.filter(n => [n.fitX, n.fitY, n.fitZ]
            .some(c => Math.abs(Math.abs(c) - 300) < CLAMPED)).length;
          const seen = new Map();
          for (const n of fresh) {
            const key = [n.fitX, n.fitY, n.fitZ].map(
              c => Math.round(c * 100) / 100).join(",");
            seen.set(key, (seen.get(key) || 0) + 1);
          }
          const coincident = Array.from(seen.values())
            .filter(c => c > 1).reduce((a, c) => a + c, 0);
          return {
            url: want,
            nodes_before: before, nodes_after: d.nodes.length,
            arm, asked, scoped_hits: scopedHits,
            arrived: fresh.length, with_a_position: placed.length,
            on_the_frame: onFrame, coincident,
            fit_span: fresh.length
              ? [Math.round(Math.min(...fresh.flatMap(
                   n => [n.fitX, n.fitY, n.fitZ]))),
                 Math.round(Math.max(...fresh.flatMap(
                   n => [n.fitX, n.fitY, n.fitZ])))]
              : null,
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
             && got.on_the_frame === 0
             // The other half of D-17: 26 chunks at one point.
             && got.coincident === 0,
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
        // **Under the chunk projector (`G-72`, `G-74`)** the fit is persisted
        // as `projector.pkl` and answered from memory, never refitted per ask
        // -- and a page may move between two asks for one reason only: the
        // stream re-placed its chunks in between. So: same fit, and every page
        // that moved is one the stream NAMED between the two sequence numbers.
        // A page moving for any other reason is the map moving under a reader.
        const posA = new Map((a.nodes || []).map((n) => [n.url, n.pos]));
        const moved = (b.nodes || [])
          .filter((n) => posA.has(n.url)
            && JSON.stringify(posA.get(n.url)) !== JSON.stringify(n.pos))
          .map((n) => n.url);
        let named = new Set();
        if (a.source === "projector" && moved.length) {
          const d = await ask(`/projector/delta?since=${a.seq}&epoch=${a.epoch}`);
          named = new Set(Object.keys(d.pages || {}));
        }
        const unexplained = moved.filter((u) => !named.has(u));
        const sameFit = a.source === "projector"
          ? a.epoch === b.epoch
          : (health.layouts || 0) > 0;
        return {
          pass: typeof a.from_store === "boolean" && sameFit
             && unexplained.length === 0,
          evidence: {
            source: a.source, epoch_same: a.epoch === b.epoch,
            stored_fits: health.layouts, from_store: a.from_store,
            nodes: a.n, seq: [a.seq, b.seq],
            moved: moved.length, moved_by_the_stream: moved.length - unexplained.length,
            unexplained: unexplained.slice(0, 5),
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
          // A leaf in a background tab hands back a DEFERRED stub with none of
          // the view's methods on it. Fronting the projector backgrounds the
          // browser cell, so this has to be forced before .view is read --
          // otherwise b.webview is undefined and it reads as no browser pane.
          for (const l of app.workspace.getLeavesOfType("domvec-browser-view")) {
            if (l.loadIfDeferred) await l.loadIfDeferred();
          }
          for (const l of app.workspace.getLeavesOfType("domvec-graph-view")) {
            if (l.loadIfDeferred) await l.loadIfDeferred();
          }
          // Loaded is not the same as USABLE. loadIfDeferred resolves before
          // the guest emits dom-ready, and every webview method then throws
          // "The WebView must be attached to the DOM and the dom-ready event
          // emitted". Poll the cheapest one until it stops throwing.
          for (let i = 0; i < 80; i++) {
            const l0 = app.workspace.getLeavesOfType("domvec-browser-view")[0];
            const w = l0 && l0.view && l0.view.webview;
            if (!w) break;
            try { w.getURL(); break; } catch (e) { await sleep(250); }
          }
          // And usable is still not VISIBLE. A leaf in a background tab has no
          // layout, so the guest reports innerWidth/innerHeight of 0 and every
          // click coordinate computed from a rect is meaningless -- the aim
          // came out at (15, 319) in a 0x0 viewport and read as the link not
          // being followed. Front the cell and wait for it to have a size.
          {
            const l0 = app.workspace.getLeavesOfType("domvec-browser-view")[0];
            if (l0) {
              app.workspace.revealLeaf(l0);
              for (let i = 0; i < 60; i++) {
                await sleep(250);
                try {
                  const size = await l0.view.webview.executeJavaScript(
                    "[window.innerWidth, window.innerHeight]");
                  if (size && size[0] > 50 && size[1] > 50) break;
                } catch (e) { /* not ready yet */ }
              }
            }
          }
          const bv = app.workspace.getLeavesOfType("domvec-browser-view")[0];
          const b = bv && bv.view;
          if (!b || !b.webview) return { error: "no browser pane" };

          // **Arm capture here rather than hoping it is armed.**
          //
          // P-B2's claim is that scanning CONTINUES while the reader browses,
          // and the field read false because an earlier check had switched it
          // off -- so the run was asserting something about leftover state.
          // Switching it on makes the assertion at the end mean what the row
          // says: it was armed, the reader navigated, and it is armed still.
          try { if (!b.live) b.setLive(true); } catch (e) {}
          await sleep(400);

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
          // Scroll, settle, then read -- and check the aim is on screen.
          // A synthetic click is delivered at a VIEWPORT coordinate, so a
          // target left below the fold by an earlier check is a click on
          // nothing, which reads as the link not being followed.
          const SEL = "article.product_pod h3 a";
          await b.webview.executeJavaScript(
            "(function(){var a=document.querySelector('" + SEL + "');" +
            "if(a) a.scrollIntoView({block:'center',behavior:'instant'});" +
            "return true;})()");
          let at = null;
          for (let i = 0; i < 20; i++) {
            await sleep(250);
            at = await b.webview.executeJavaScript(
              "(function(){var a=document.querySelector('" + SEL + "');" +
              "if(!a) return null;" +
              "var r=a.getBoundingClientRect();" +
              "return {x:Math.round(r.left+r.width/2)," +
              "y:Math.round(r.top+r.height/2)," +
              "vw:window.innerWidth, vh:window.innerHeight," +
              "href:a.href};})()");
            if (at && at.y >= 0 && at.y < at.vh && at.x >= 0 && at.x < at.vw) break;
          }
          if (!at) return { error: "no link to click" };
          if (!(at.y >= 0 && at.y < at.vh && at.x >= 0 && at.x < at.vw)) {
            return { error: "the aim never came on screen", at };
          }
          // (The cell had two FACES until 2026-09-26 and this reset it to the
          // page; the page is now always shown -- G-82 -- so there is no face
          // for an earlier check to leave it on.)
          try { b.webview.focus(); } catch (e) {}
          await sleep(300);

          // Re-read the rect immediately before dispatching. Between the aim
          // loop and the click the page can still be settling -- lazy images
          // on this page shift the grid down as they arrive -- and a
          // coordinate a second old points at whatever moved into its place.
          const now = await b.webview.executeJavaScript(
            "(function(){var a=document.querySelector('" + SEL + "');" +
            "if(!a) return null; var r=a.getBoundingClientRect();" +
            "return {x:Math.round(r.left+r.width/2)," +
            "y:Math.round(r.top+r.height/2)," +
            "vw:window.innerWidth, vh:window.innerHeight, href:a.href};})()");
          if (now && now.y >= 0 && now.y < now.vh) { at = now; }
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
          // One retry, re-aimed. A synthetic click can miss for reasons that
          // have nothing to do with the browser being real -- the grid on
          // this page reflows as its cover images arrive, and a coordinate
          // read a second earlier then points between two tiles. Reported,
          // so a pass that needed the retry says so.
          let retried = false;
          if (moved === landed) {
            retried = true;
            const again = await b.webview.executeJavaScript(
              "(function(){var a=document.querySelector('" + SEL + "');" +
              "if(!a) return null; a.scrollIntoView({block:'center'," +
              "behavior:'instant'}); var r=a.getBoundingClientRect();" +
              "return {x:Math.round(r.left+r.width/2)," +
              "y:Math.round(r.top+r.height/2)};})()");
            if (again) {
              try { b.webview.focus(); } catch (e) {}
              await sleep(300);
              for (const type of ["mouseDown", "mouseUp"]) {
                b.webview.sendInputEvent({ type, x: again.x, y: again.y,
                                           button: "left", clickCount: 1 });
              }
              for (let i = 0; i < 40; i++) {
                await sleep(400);
                moved = b.webview.getURL();
                if (moved !== landed && !b.webview.isLoading()) break;
              }
            }
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
            live_capture_on: !!b.live, needed_a_retry: retried,
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
      id: "P-B2",
      asks: "the browser cell navigates as a browser does: address bar, back, forward, reload, scan, live, retrieval overlay",
      async run() {
        // Every control pressed as a reader presses it -- the toolbar's own
        // buttons and fields, not the view's methods -- and each step scored
        // on what the app then shows. Local fixtures for the navigation arms
        // (a page whose only motion is ours), the seeded store for retrieval.
        const fixtures = await serveFixtures();
        const A = fixtures.origin + "/inline_prose.html";
        const B = fixtures.origin + "/link_family.html";
        // Words the store holds, from a seeded page, for the retrieval arm.
        const layout = await ask("/layout?level=chunk");
        const words = [...new Set((layout.nodes || [])
          .filter((n) => String(n.url || "").indexOf("books.toscrape.com") >= 0)
          .map((n) => String(n.title || "")).join(" ")
          .match(/[A-Za-z][A-Za-z-]{4,}/g) || [])].slice(0, 3).join(" ") || "books";
        try {
          const got = await evaluate(`(async () => {
            const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
            await window.__domvec.act("open", "browser");
            const b = app.workspace.getLeavesOfType("domvec-browser-view")[0].view;
            const wv = b.webview, root = b.containerEl;
            const bar = root.querySelector(".domvec-browser-bar");
            const btn = (t) => [...bar.querySelectorAll("button")].find((e) => e.textContent.trim().indexOf(t) === 0);
            const url = () => wv.getURL();
            let starts = 0;
            const onStart = () => starts++;
            wv.addEventListener("did-start-loading", onStart);
            const settle = async (pred, ms = 20000) => {
              const t0 = Date.now();
              while (Date.now() - t0 < ms) { if (!wv.isLoading() && pred()) return Date.now() - t0; await sleep(150); }
              return -1;
            };
            const typeUrl = async (u, pred) => {
              const a = root.querySelector(".domvec-browser-url");
              a.focus(); a.value = u;
              a.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }));
              return settle(pred);
            };
            const mapFollows = () => !!(b.pipebox && b.pipebox.map && b.pipebox.map.url === url());
            const steps = {};
            steps.address_bar = { ms: await typeUrl(${JSON.stringify(A)}, () => url() === ${JSON.stringify(A)}), url: url() };
            await sleep(600); steps.address_bar.map_follows = mapFollows();
            steps.address_bar_2 = { ms: await typeUrl(${JSON.stringify(B)}, () => url() === ${JSON.stringify(B)}), url: url() };
            await sleep(600);
            btn("\\u2190").click();
            steps.back = { ms: await settle(() => url() === ${JSON.stringify(A)}), url: url(), address: root.querySelector(".domvec-browser-url").value };
            btn("\\u2192").click();
            steps.forward = { ms: await settle(() => url() === ${JSON.stringify(B)}), url: url() };
            const before = starts;
            btn("\\u27f3").click();
            await sleep(300);
            steps.reload = { ms: await settle(() => starts > before), url: url(), loads: starts - before };
            steps.bare_host = { ms: await typeUrl("books.toscrape.com", () => url().indexOf("https://books.toscrape.com") === 0), url: url() };
            await sleep(800); steps.bare_host.map_follows = mapFollows();
            // scan
            const scanBefore = JSON.stringify(b.lastScan || null);
            btn("scan").click();
            let scanned = false;
            for (let i = 0; i < 60 && !scanned; i++) { await sleep(250); scanned = JSON.stringify(b.lastScan || null) !== scanBefore; }
            steps.scan = { changed: scanned, last: b.lastScan ? { passes: b.lastScan.passes, addresses: b.lastScan.addresses, settled: b.lastScan.settled } : null };
            // live
            const live0 = !!b.live;
            btn("live").click(); await sleep(300);
            const live1 = !!b.live;
            btn("live").click(); await sleep(300);
            steps.live = { before: live0, toggled: live1, restored: !!b.live };
            // retrieval overlay
            const q = root.querySelector(".domvec-query");
            q.focus(); q.value = ${JSON.stringify(words)};
            q.dispatchEvent(new Event("input", { bubbles: true }));
            await sleep(1500);
            const hits = () => [...root.querySelectorAll(".domvec-hit")];
            const overlay = root.querySelector(".domvec-overlay");
            steps.query = { query: q.value, hits: hits().length, overlay_shown: !!overlay && overlay.style.display !== "none" };
            const list = root.querySelector(".domvec-overlay-list");
            const n0 = hits().length;
            if (list) { list.scrollTop = list.scrollHeight; list.dispatchEvent(new Event("scroll")); }
            await sleep(1500);
            steps.scroll_more = { before: n0, after: hits().length };
            const scope = [...root.querySelectorAll(".domvec-browser-search button")].find((e) => /everywhere|this page/.test(e.textContent));
            scope.click(); await sleep(1500);
            const scopedUrls = [...new Set(hits().map((h) => (h.querySelector(".domvec-hit-url") || {}).textContent))];
            steps.scope = { label: scope.textContent, hits: hits().length, urls: scopedUrls.length, only_here: scopedUrls.every((u) => u === url()) };
            scope.click(); await sleep(1200);
            const first = hits()[0];
            const want = first ? (first.querySelector(".domvec-hit-url") || {}).textContent : null;
            if (first) first.click();
            steps.hit_click = { want, ms: want ? await settle(() => url() === want) : -1, url: url(), status: b.status.textContent };
            const x = [...root.querySelectorAll(".domvec-browser-search button")].find((e) => e.textContent.trim() === "\\u00d7");
            x.click(); await sleep(400);
            steps.clear = { query: q.value, overlay_shown: !!overlay && overlay.style.display !== "none" };
            // G-41: nothing of ours was written into the page.
            steps.nothing_injected = await wv.executeJavaScript("document.querySelectorAll('[class*=domvec],[id*=domvec]').length === 0");
            wv.removeEventListener("did-start-loading", onStart);
            try { b.go("about:blank"); } catch (e) {}
            return steps;
          })()`, { timeout: 300000 });
          got.purged = await tidyFixtures(fixtures.origin);
          const s = got;
          const ok = {
            address_bar: s.address_bar.ms >= 0 && s.address_bar.map_follows,
            back: s.back.ms >= 0 && s.back.address === s.back.url,
            forward: s.forward.ms >= 0,
            reload: s.reload.ms >= 0 && s.reload.loads >= 1,
            bare_host: s.bare_host.ms >= 0 && s.bare_host.map_follows,
            scan: s.scan.changed && !!s.scan.last && s.scan.last.passes > 0,
            live: s.live.toggled !== s.live.before && s.live.restored === s.live.before,
            query: s.query.hits > 0 && s.query.overlay_shown,
            scroll_more: s.query.hits < 12 || s.scroll_more.after > s.scroll_more.before,
            scope: /this page/.test(s.scope.label) && s.scope.only_here,
            hit_click: s.hit_click.ms >= 0,
            clear: s.clear.query === "" && !s.clear.overlay_shown,
            nothing_injected: s.nothing_injected === true,
          };
          return { pass: Object.values(ok).every(Boolean), evidence: { ok, steps: s } };
        } finally {
          await fixtures.close();
        }
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
          // The pane's own drawn radius where it has one (pictures are sized
          // by the media mode, which this formula does not know -- G-21 read
          // 183 phantom overlaps from it, 2026-10-07).
          const radius = (n) => v.drawnRadiusOf ? v.drawnRadiusOf(n)
            : (n.image && n.image.src) ? sphereOf(n) * PANEL_GAIN : sphereOf(n);
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
      id: "G-111",
      asks: "a control in a chunk's panel acts on the LIVE page through its trie address: the cell navigates and scrolls to it, the action is performed in the page, the page's change comes back as the panel's new state -- and a refused control and a planted no-op change nothing",
      async run() {
        // 2026-10-04: "clicking a button or link on the chunk opens the
        // browser to first navigate and scroll to the chunk and then take the
        // action on the component in-silico that then performs the update
        // action/event on the browser".
        //
        // The page is a fixture whose only motion is the motion this check
        // causes (the null arm is read first, on the same page). The panel
        // is the browser side's pinned card; its controls are driven the way
        // a reader's events reach them -- dispatched in the card's own frame
        // -- and the page is read back with a plain read, never written.
        //
        // Four arms, and each can fail on its own: the CLEAN click and fill
        // must change the page and re-render the card; the REFUSED control
        // ("Sign in", the never-press set) must change nothing and say so;
        // the PLANTED no-op (`act-noop`) must change nothing; and the
        // NAVIGATION arm presses from a card while the cell is elsewhere.
        const health = await ask("/health");
        if (!health.enact) {
          return { pass: false, evidence: {
            blocked: "the sidecar was not started with --enact: panel gestures are adjudicated by it, and this check cannot run without the flag",
            enact: health.enact } };
        }
        const fixtures = await serveFixtures();
        const page = fixtures.origin + "/panel_act.html";
        try {
          const got = await evaluate(`(async () => {
            ${PREP}
            const PAGE = ${JSON.stringify(page)};
            const SIDE = ${JSON.stringify(SIDECAR)};
            const TOKEN = ${JSON.stringify("word" + Date.now().toString(36))};
            const out = { page: PAGE };
            const read = (id) => b.webview.executeJavaScript(
              "document.getElementById(" + JSON.stringify(id) + ").textContent");
            const xpathOf = (id) => b.webview.executeJavaScript(
              "(function(){var el=document.getElementById(" + JSON.stringify(id) + ");" +
              "if(!el) return '';var parts=[];" +
              "while(el && el.nodeType===1 && el.tagName){" +
              "var tag=el.tagName.toLowerCase(),i=1,sib=el.previousElementSibling;" +
              "while(sib){if(sib.tagName===el.tagName)i++;sib=sib.previousElementSibling;}" +
              "parts.unshift(i>1?tag+'['+i+']':tag);el=el.parentElement;}" +
              "return '/'+parts.join('/');})()");
            const until = async (fn, ms) => {
              const t = performance.now();
              while (performance.now() - t < ms) { if (await fn()) return true; await sleep(250); }
              return false;
            };
            let cid = "";
            try {
              b.plant.clear();
              try { b.setLive(true); } catch (e) {}
              out.landed = await land(PAGE, 30000);
              const xBtn = await xpathOf("go");
              out.xpath = xBtn;
              // The page must be IN the trie: the sidecar only adjudicates addresses it holds.
              let res = null;
              for (let i = 0; i < 75 && !res; i++) {
                const r = await fetch(SIDE + "/resolve?url=" + encodeURIComponent(PAGE) + "&xpath=" + encodeURIComponent(xBtn));
                if (r.ok) { const j = await r.json(); if (j && j.cid && Array.isArray(j.lines)) res = j; }
                if (!res) await sleep(800);
              }
              if (!res) return { ...out, error: "the page never reached the trie" };
              out.chunk_lines = res.lines.length;
              const pinned = await b.pinXpath(xBtn);
              cid = pinned && pinned.cid;
              out.pinned = cid || pinned;
              if (!cid) return { ...out, error: "nothing pinned" };

              const frameOf = () => {
                const card = b.markdownWrap.querySelector('.domvec-pin-card[data-cid="' + cid + '"]');
                const f = card && card.querySelector("iframe.domvec-snapshot");
                return f && f.contentDocument && f.contentDocument.getElementById("domvec-root") ? f : null;
              };
              const doc = () => frameOf().contentDocument;
              const readoutOf = () => { const f = frameOf(); const r = f && f.parentElement.querySelector(".domvec-act-readout"); return r ? r.textContent : ""; };
              const control = (act, text) => [...doc().querySelectorAll('[data-domvec-act="' + act + '"]')]
                .find((e) => !text || (e.textContent || "").trim() === text);
              const click = (el) => el.dispatchEvent(new (el.ownerDocument.defaultView.MouseEvent)(
                "click", { bubbles: true, cancelable: true }));

              out.card = await until(async () => { const f = frameOf(); return !!f && !!f.contentDocument.querySelector("[data-domvec-address]"); }, 25000);
              if (!out.card) return { ...out, error: "no card with addressed elements" };
              const first = frameOf();

              // ---- The card is LINKED to the trie: every addressed element names this page and resolves in it.
              const tagged = [...doc().querySelectorAll("[data-domvec-address]")];
              out.tagged = tagged.length;
              out.acts = [...doc().querySelectorAll("[data-domvec-act]")].map((e) =>
                e.tagName.toLowerCase() + ":" + e.getAttribute("data-domvec-act") + ":" + (e.textContent || "").trim().slice(0, 16));
              out.addresses_on_this_page = tagged.every((e) => e.getAttribute("data-domvec-address").split("|")[0] === PAGE);
              const xs = tagged.map((e) => e.getAttribute("data-domvec-xpath"));
              const alive = await b.webview.executeJavaScript(
                "(function(xs){var h=window.__domvecSensor;return h&&h.alive?h.alive(xs):null;})(" + JSON.stringify(xs) + ")");
              out.addresses_alive = Array.isArray(alive) && alive.length > 0 && alive.every(Boolean);
              out.has_press = !!control("press", "Pick me");
              out.has_type = !!control("type");
              out.has_gate = !!control("press", "Sign in");

              // ---- NULL ARM: the page alone, no gesture.
              out.before = { out: await read("out"), echo: await read("echo"), gated: await read("gated") };
              await sleep(3000);
              out.null_arm_changed = (await read("out")) !== out.before.out
                || (await read("echo")) !== out.before.echo || (await read("gated")) !== out.before.gated;

              // ---- CLEAN: click from the card.
              click(control("press", "Pick me"));
              out.clicked = await until(async () => (await read("out")) === "button pressed 1 times", 15000);
              out.after_click = await read("out");
              out.rerendered = await until(async () => { const f = frameOf(); return !!f && f.contentDocument.body.textContent.indexOf("button pressed 1 times") >= 0; }, 15000);
              out.frame_replaced = frameOf() !== first;

              // ---- CLEAN: fill from the card.
              const inp = control("type");
              if (inp) {
                inp.value = TOKEN;
                inp.dispatchEvent(new (inp.ownerDocument.defaultView.Event)("change", { bubbles: true }));
              }
              out.filled = await until(async () => (await read("echo")) === "echo: " + TOKEN, 15000);
              out.panel_shows_value = await until(async () => {
                const f = frameOf(); const i = f && f.contentDocument.querySelector('[data-domvec-act="type"]');
                return !!i && i.getAttribute("value") === TOKEN; }, 15000);

              // ---- REFUSED: the never-press control changes nothing, and says why.
              if (control("press", "Sign in")) click(control("press", "Sign in"));
              out.refusal_said = await until(async () => /^refused/.test(readoutOf()), 15000);
              await sleep(1500);
              out.gated_after = await read("gated");
              out.refusal_text = readoutOf().slice(0, 100);

              // ---- PLANTED: actOn does nothing; the page must not move.
              b.plant.add("act-noop");
              click(control("press", "Pick me"));
              await sleep(3500);
              out.planted_page = await read("out");
              out.planted_said = /planted/.test(readoutOf());
              b.plant.delete("act-noop");

              // ---- Planted arm lifted: the same click works again.
              click(control("press", "Pick me"));
              out.second = await until(async () => (await read("out")) === "button pressed 2 times", 15000);

              // ---- NAVIGATION: the cell is elsewhere; the card's click takes it to the page first.
              b.go("about:blank");
              await until(async () => { try { return b.webview.getURL() === "about:blank" && !b.webview.isLoading(); } catch (e) { return false; } }, 15000);
              await sleep(1500);
              out.card_after_leaving = !!frameOf();
              if (frameOf() && control("press", "Pick me")) {
                click(control("press", "Pick me"));
                out.arrived = await until(async () => { try { return b.webview.getURL() === PAGE; } catch (e) { return false; } }, 40000);
                out.nav_pressed = await until(async () => {
                  try { return (await read("out")) === "button pressed 1 times"; } catch (e) { return false; }
                }, 25000);
              }
            } finally {
              b.plant.clear();
              try { b.setLive(false); } catch (e) {}
              try { if (cid) b.unpin(cid); } catch (e) {}
              try { b.go("about:blank"); } catch (e) {}
              await sleep(2000);
            }
            return out;
          })()`, { timeout: 420000 });
          got.purged = await tidyFixtures(fixtures.origin);
          if (got.error) return { pass: false, evidence: got };
          const linked = got.tagged > 0 && got.addresses_on_this_page === true && got.addresses_alive === true
            && got.has_press === true && got.has_type === true && got.has_gate === true;
          const clean = got.null_arm_changed === false && got.clicked === true && got.rerendered === true
            && got.filled === true && got.panel_shows_value === true && got.second === true;
          const refused = got.refusal_said === true && got.gated_after === "still signed out";
          const planted = got.planted_page === "button pressed 1 times" && got.planted_said === true;
          const navigated = got.card_after_leaving === true && got.arrived === true && got.nav_pressed === true;
          return {
            pass: linked && clean && refused && planted && navigated,
            evidence: { ...got, arms: { linked, clean, refused, planted, navigated },
                        bar: "every addressed element names this page and resolves in it; a click and a fill from the card change the page and the card re-renders from it; the never-press control is refused with the page unchanged; the planted no-op leaves the page unchanged; a click with the cell elsewhere navigates first" },
          };
        } finally {
          await fixtures.close();
        }
      },
    },
    {
      id: "S-7",
      asks: "a page interaction is observed and persisted to db and trie",
      async run() {
        const fixtures = await serveFixtures();
        const token = "domvecprobe" + Date.now().toString(36);
        const pagesBefore = (await ask("/health")).pages;
        const page = fixtures.origin + "/live_mutate.html?token=" + token;
        try {
          const got = await evaluate(mutateProbe(page, token, SIDECAR),
                                     { timeout: 600000 });
          // Leave the corpus as it was found. A confirmation harness that adds
          // a page per run is an instrument changing its own denominator.
          got.purged = await tidyFixtures(fixtures.origin);
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
      asks: "one capture reaches the graph and BOTH forms of a pinned chunk, uniformly",
      async run() {
        const fixtures = await serveFixtures();
        const token = "domvecuniform" + Date.now().toString(36);
        const pagesBefore = (await ask("/health")).pages;
        const page = fixtures.origin + "/live_mutate.html?token=" + token;
        try {
          const got = await evaluate(uniformProbe(page, token, SIDECAR),
                                     { timeout: 600000 });
          got.purged = await tidyFixtures(fixtures.origin);
          got.pages_before = pagesBefore;
          got.pages_after = (await ask("/health")).pages;
          if (got.error) return { pass: false, evidence: got };
          return {
            // "Uniformly" is the whole row, so every surface has to carry it,
            // and the arm below stops the token being there all along.
            // Both forms of a pinned chunk -- the side panel and the
            // billboard -- while it is held, and again after it is let go
            // and pinned anew (a fresh read, which can hardly be wrong; the
            // held one has to be TOLD, and is the arm that fails).
            pass: got.side_before_had_token === false
               && got.board_before_had_token === false
               && got.mutated_in_page === true
               && got.db_has_token === true
               && got.side_has_token === true
               && got.board_has_token === true
               && got.unpin_closed_board === true
               && got.repinned_side_has_token === true
               && got.repinned_board_has_token === true
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
      id: "S-8",
      asks: "the scroll is tuned to the page, and captures no less for it",
      async run() {
        const fixtures = await serveFixtures();
        const pages = {
          short: fixtures.origin + "/live_mutate.html",
          tall: fixtures.origin + "/live_tall.html",
        };
        try {
          const pagesBefore = (await ask("/health")).pages;
          const got = await evaluate(paceProbe(pages, SIDECAR),
                                     { timeout: 900000 });
          got.purged = await tidyFixtures(fixtures.origin);
          got.pages_before = pagesBefore;
          got.pages_after = (await ask("/health")).pages;
          if (got.error) return { pass: false, evidence: got };
          return {
            // **Different criteria per page, because they answer different
            // halves of the row, and one criterion for both would be wrong
            // for one of them.**
            //
            // Short page -- time-efficient: strictly faster, same coverage.
            // Tall page -- fine-grained and tuned: it must actually SETTLE
            // where the fixed cadence does not, and must not buy that with
            // coverage. Not required to be faster there: reaching the bottom
            // of a page the other arm never finished is more work, and
            // scoring it on the clock alone would credit not finishing.
            pass: got.short.tuned.addresses >= got.short.fixed.addresses
               && got.short.tuned.ms < got.short.fixed.ms
               && got.short.tuned.settled === true
               && got.tall.tuned.addresses >= got.tall.fixed.addresses
               && got.tall.tuned.settled === true
               && got.tall.fixed.settled === false
               && got.pages_after === got.pages_before,
            evidence: got,
          };
        } finally {
          await fixtures.close();
        }
      },
    },
    {
      id: "T-3",
      asks: "a shadow node sits under its host in the trie, not beside it",
      async run() {
        const fixtures = await serveFixtures();
        const page = fixtures.origin + "/shadow_catalogue.html";
        try {
          const pagesBefore = (await ask("/health")).pages;
          const got = await evaluate(shadowProbe(page, SIDECAR),
                                     { timeout: 600000 });
          got.purged = await tidyFixtures(fixtures.origin);
          got.pages_before = pagesBefore;
          got.pages_after = (await ask("/health")).pages;
          if (got.error) return { pass: false, evidence: got };
          return {
            // The first clause is the non-vacuity arm and it is not optional:
            // a page that yielded no shadow addresses at all would satisfy
            // every other clause here perfectly. Every live site reachable
            // during development reported zero, which is why this fixture
            // exists.
            pass: got.shadow_addresses > 0
               && got.nested_addresses > 0
               && got.orphans === 0
               && got.rootless === 0
               && got.nesting_prefix_ok === true
               && got.pages_after === got.pages_before,
            evidence: got,
          };
        } finally {
          await fixtures.close();
        }
      },
    },
    {
      id: "G-119",
      asks: "johnwick.movie and archive.org, the reader's test pages, each run the core features live: the page captured into the store; hovering draws the outline on the page and opens the hovered chunk's panel with its own lines; panels show the page-original form on these dynamic renders",
      async run() {
        // 2026-10-06: "please use this and archive.org as pages to test all
        // of our current features on". The reader's own page is put back.
        const got = await evaluate(`(async () => {
          ${PREP}
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
          const pb = b.pipebox;
          const was = b.webview.getURL();
          const base = app.plugins.getPlugin("domvec-bridge").settings.sidecar.replace(/[/]+$/, "");
          const shown = (el) => !!el && el.style.display !== "none" && el.offsetWidth > 0;
          const txt = (p) => p && p.lines ? p.lines.map((l) => String(l.text || "").trim()).join("|") : "";
          const visit = async (PAGE) => {
            if (!(await land(PAGE, 45000))) return { page: PAGE, error: "did not land" };
            await sleep(9000);
            const r = b.webview.getBoundingClientRect();
            const rows = [];
            for (let i = 0; i < 10; i++) {
              const x = Math.round(90 + (i % 5) * Math.max(60, (r.width - 180) / 4)), y = Math.round(140 + Math.floor(i / 5) * Math.max(120, r.height / 3));
              b.webview.sendInputEvent({ type: "mouseMove", x, y });
              await sleep(1100);
              const h = pb && pb.hover;
              if (!h || !h.cid) continue;
              const bb = v.hoverBb;
              const e = bb ? v.billboards.get(bb) : null;
              const grey = String(bb || "").startsWith("f:");
              const panel = bb ? await v.chunkPayload(bb) : null;
              // RIGHT: the panel holds the words under the pointer (half or
              // more of the hovered element's own words; an element with
              // fewer than two words is not judged).
              let under = "";
              try { under = await b.webview.executeJavaScript("(function(){var x=" + x + ",y=" + y + ",e=document.elementFromPoint(x,y),g=0;while(e&&e.shadowRoot&&g++<20){var i=e.shadowRoot.elementFromPoint(x,y);if(!i||i===e)break;e=i;}if(!e)return '';var w=document.createTreeWalker(e,NodeFilter.SHOW_TEXT),t='',n;while((n=w.nextNode())&&t.length<400){var p=n.parentElement;if(p&&p.closest&&p.closest('svg,title,desc,script,style'))continue;t+=' '+n.nodeValue;}return t;})()"); } catch (err) {}
              const words = (t) => (String(t || "").toLowerCase().match(/[a-z0-9]{3,}/g) || []);
              const want = [...new Set(words(under))], have = new Set(words(txt(panel)));
              const judged = want.length >= 2;
              rows.push({ outline: shown(pb.outline), panel: !!bb, lines: panel && panel.lines ? panel.lines.length : 0,
                          judged, right: !!bb && judged && want.filter((w) => have.has(w)).length >= 0.5 * want.length,
                          grey, form: e ? e.form || "" : "" });
            }
            let stored = 0;
            try { const st = await (await fetch(base + "/page_status?url=" + encodeURIComponent(b.webview.getURL()))).json(); stored = st.chunks || 0; } catch (e) {}
            const n = rows.length;
            return { page: PAGE, hovers: n, outlines: rows.filter((x) => x.outline).length, panels: rows.filter((x) => x.panel).length,
                     judged: rows.filter((x) => x.judged).length, right: rows.filter((x) => x.right).length, grey: rows.filter((x) => x.grey).length,
                     page_form: rows.filter((x) => x.form === "page").length, stored };
          };
          try {
            const a = await visit("https://johnwick.movie/");
            const c = await visit("https://archive.org/");
            // Planted: grey panels without a page form, and shadow/slot paths
            // by XPath alone -- the page form must go.
            b.plant.add("no-grey-page-form"); b.snapshotPlants.xpathOnly = true;
            let p;
            try { p = await visit("https://archive.org/?g119p=" + Date.now()); }
            finally { b.plant.delete("no-grey-page-form"); b.snapshotPlants.xpathOnly = false; }
            return { johnwick: a, archive: c, planted_archive: p };
          } finally {
            if (was && /^https?:/.test(was)) await land(was, 45000);
          }
        })()`, { timeout: 300000 });
        if (!got || got.error) return { pass: false, evidence: got };
        const ok = (x) => !x.error && x.stored > 0 && x.hovers >= 4 && x.outlines >= 0.8 * x.hovers
          && x.panels >= 0.8 * x.hovers && x.right >= 0.8 * x.judged && x.page_form >= 1;
        return { pass: ok(got.johnwick) && ok(got.archive) && !!got.planted_archive && got.planted_archive.page_form === 0,
                 evidence: got };
      },
    },
    {
      id: "G-279",
      asks: "a cell is a function node: the {ref} on its fence line names a vault note, which is resolved through the store and bound into the kernel as a variable before the cell runs -- the cell reads the note's text; the run is recorded with that note as its input (GET /runs); planted (__domvecPlantNoRefs) the cell meets an unbound name",
      async run() {
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const until = async (ok, ms) => { for (let t = 0; t < ms && !ok(); t += 250) await sleep(250); return ok(); };
          const plugin = app.plugins.getPlugin("domvec-bridge");
          const SIDE = String(plugin.settings.sidecar).replace(/[/]+$/, "");
          const NL = String.fromCharCode(10), F = String.fromCharCode(96).repeat(3);
          const folder = "domvec-checks";
          if (!app.vault.getAbstractFileByPath(folder)) await app.vault.createFolder(folder);
          const stamp = Date.now();
          const srcName = "g279 source " + stamp;
          const src = await app.vault.create(folder + "/" + srcName + ".md", "# Source" + NL + NL + "A radix tree compresses single-child chains, marker " + stamp + "." + NL);
          const indexed = await plugin.indexNote(src, "check");
          const srcUrl = indexed && indexed.url;
          const v = srcName.replace(/[^A-Za-z0-9_]+/g, "_").replace(/^_+|_+$/g, "").toLowerCase();
          const arm = async (planted) => {
            window.__domvecPlantNoRefs = planted;
            const path = folder + "/g279-" + (planted ? "p" : "c") + stamp + ".md";
            const f = await app.vault.create(path, "# cell" + NL + NL + F + "python {" + srcName + "}" + NL + "print(len(" + v + ") > 0, '" + stamp + "' in " + v + ")" + NL + F + NL);
            const leaf = app.workspace.getLeaf("tab");
            const out = { planted };
            try {
              await leaf.openFile(f, { state: { mode: "source", source: false } });
              const view = leaf.view;
              await until(() => !!view.containerEl.querySelector(".domvec-run-fence"), 8000);
              view.containerEl.querySelector(".domvec-run-fence").click();
              await until(() => view.editor.getValue().includes("nb-output"), 20000);
              const text = view.editor.getValue();
              out.output = (text.split("nb-output")[1] || "").slice(0, 200);
              out.read_the_note = /True True/.test(text);
              out.unbound = /NameError/.test(text);
              const runs = await (await fetch(SIDE + "/runs?note=" + encodeURIComponent(path))).json();
              const r = (runs.runs || [])[0];
              out.recorded = !!r;
              out.input_urls = r ? [...new Set(r.inputs.map((i) => i.url))] : [];
            } finally {
              window.__domvecPlantNoRefs = false;
              try { leaf.detach(); } catch (e) {}
              try { await app.vault.delete(f); } catch (e) {}
            }
            return out;
          };
          // The Database base object in the kernel: search and read-only cypher.
          const dbArm = async (planted) => {
            await fetch(SIDE + "/plant", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: "no-base-objects", on: planted }) });
            const path = folder + "/g279db-" + (planted ? "p" : "c") + stamp + ".md";
            const code = ["hits = Database.search('radix tree', k=3)",
                          "pages = Database.cypher('MATCH (p:Page) RETURN count(p)')[0][0]",
                          "try:", "    Database.cypher('MATCH (c:Chunk) SET c.md = c.md')", "    wrote = 'WROTE'",
                          "except Exception as e:", "    wrote = 'refused' if 'read-only' in str(e) else str(e)",
                          "print(len(hits) > 0, pages > 0, wrote)"].join(NL);
            const f = await app.vault.create(path, "# db" + NL + NL + F + "python" + NL + code + NL + F + NL);
            const leaf = app.workspace.getLeaf("tab");
            const out = { planted };
            try {
              await leaf.openFile(f, { state: { mode: "source", source: false } });
              const view = leaf.view;
              await until(() => !!view.containerEl.querySelector(".domvec-run-fence"), 8000);
              view.containerEl.querySelector(".domvec-run-fence").click();
              await until(() => view.editor.getValue().includes("nb-output"), 30000);
              const text = view.editor.getValue();
              out.searched_counted_refused = /True True refused/.test(text);
              out.undefined = /NameError/.test(text);
            } finally {
              await fetch(SIDE + "/plant", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: "no-base-objects", on: false }) });
              try { leaf.detach(); } catch (e) {}
              try { await app.vault.delete(f); } catch (e) {}
            }
            return out;
          };
          try {
            return { src: srcUrl, clean: await arm(false), planted: await arm(true),
                     db: await dbArm(false), db_planted: await dbArm(true) };
          } finally {
            try { await app.vault.delete(src); } catch (e) {}
            if (srcUrl) { try { await fetch(SIDE + "/purge", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ url: srcUrl }) }); } catch (e) {} }
            plugin.settings.indexedNotes = (plugin.settings.indexedNotes || []).filter((p) => !p.includes("g279"));
            await plugin.saveSettings();
            await sleep(1500);
            const fo = app.vault.getAbstractFileByPath(folder);
            if (fo && (!fo.children || !fo.children.length)) await app.vault.delete(fo, true);
          }
        })()`, { timeout: 180000 });
        if (!got || got.error || !got.clean) return { pass: false, evidence: got };
        const c = got.clean, p = got.planted;
        return { pass: !!got.src && c.read_the_note && c.recorded && c.input_urls.includes(got.src)
                   && p.unbound && !p.read_the_note
                   && got.db.searched_counted_refused && got.db_planted.undefined && !got.db_planted.searched_counted_refused,
                 evidence: got };
      },
    },
    {
      id: "G-271",
      asks: "a hover starts a slow, STATEFUL flight: its speed is the throttle's whatever the distance (two starts 2x apart cruise within 15% of each other), it stops at the hard floor and never nearer, and a new hover BENDS the trajectory in flight -- the speed carries over (over half kept); planted (agent.plantRestart) a new hover starts from rest",
      async run() {
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0]?.view;
          if (!v || !v.graph || !v.agent) return { error: "no graph or agent" };
          const g = v.graph, cam = g.camera(), ctl = g.controls(), a = v.agent;
          const saved = { p: cam.position.clone(), t: ctl.target.clone(), up: cam.up.clone(), mode: a.mode, thr: a.throttle };
          const dist = (n) => Math.hypot(cam.position.x - n.x, cam.position.y - n.y, cam.position.z - (n.z || 0));
          const ns = g.graphData().nodes.filter((n) => Number.isFinite(n.x) && n.level !== "path");
          ns.sort((x, y) => dist(y) - dist(x));
          const n1 = ns[0], n2 = ns[Math.min(ns.length - 1, 5)];
          const reset = () => { cam.position.copy(saved.p); ctl.target.copy(saved.t); cam.up.copy(saved.up); ctl.update?.(); a.vel = { x: 0, y: 0, z: 0 }; a.target = null; };
          const hover = (n) => { v.focusNode = null; v.focusPending = null; v.focusOn(n); };
          const cruise = async (n, back) => {
            reset();
            cam.position.set(n.x + (saved.p.x - n.x) * back, n.y + (saved.p.y - n.y) * back, (n.z || 0) + (saved.p.z - (n.z || 0)) * back);
            // The flight itself, from rest (hover-to-flight is G-273's): spin
            // up, then one second of cruise.
            v.flyTo(n); await sleep(750);
            const d0 = dist(n); await sleep(1000); const d1 = dist(n);
            return Math.round((d0 - d1) * 10) / 10;      // world units in one second
          };
          const out = {};
          try {
            a.setMode("ego"); a.setThrottle(0.25); a.paused = false;
            out.speed_near = await cruise(n1, 1);
            out.speed_far = await cruise(n1, 2);
            // Zoomed in nearer than the floor (look point 8 units ahead): the
            // flight's standoff is then the floor itself (G-285 is the zoom).
            reset(); a.setThrottle(1);
            { const b = { x: ctl.target.x - cam.position.x, y: ctl.target.y - cam.position.y, z: ctl.target.z - cam.position.z }; const bl = Math.hypot(b.x, b.y, b.z) || 1;
              ctl.target.set(cam.position.x + b.x / bl * 8, cam.position.y + b.y / bl * 8, cam.position.z + b.z / bl * 8); }
            hover(n2);
            let minD = Infinity;
            for (let i = 0; i < 80; i++) { await sleep(250); minD = Math.min(minD, dist(n2)); }
            out.floor = Math.round(a.stopFloor(n2) * 10) / 10; out.hard_floor = a.floor; out.min_d = Math.round(minD * 10) / 10; out.end_d = Math.round(dist(n2) * 10) / 10;
            const bend = async (planted) => {
              reset(); a.setThrottle(0.5); a.plantRestart = planted;
              hover(n1); await sleep(250 + 2000);
              const sp = () => Math.round(Math.hypot(a.vel.x, a.vel.y, a.vel.z) * 10) / 10;
              const before = sp();
              v.flyTo(n2);                                // the new hover's flight, synchronously
              const after = sp();
              return { before, after, kept: Math.round(after / Math.max(1e-9, before) * 100) / 100 };
            };
            out.bend = await bend(false);
            out.bend_planted = await bend(true);
          } finally {
            a.plantRestart = false; reset(); v.focusNode = null;
            a.setThrottle(saved.thr); a.mode = saved.mode; a.draw();
          }
          return out;
        })()`, { timeout: 120000 });
        if (!got || got.error) return { pass: false, evidence: got };
        const ratio = got.speed_far / Math.max(1e-9, got.speed_near);
        return { pass: got.speed_near > 0 && ratio > 0.85 && ratio < 1.15
                   && got.min_d >= got.floor - 0.5 && Math.abs(got.end_d - got.floor) <= 2
                   && got.bend.kept > 0.5 && got.bend_planted.kept < 0.25,
                 evidence: got };
      },
    },
    {
      id: "G-285",
      asks: "ego motion is SELECTIVE and in step with the hover (2026-10-30, items 38-39, 46-48): (a) a flight stops at the reader's own zoom distance, not the floor -- planted (agent.plantIgnoreZoom) it closes to the floor; (b) the flight ENDS: arrived, the target is released and a look point moved off the node stays moved -- planted (agent.plantHoldTarget) the aim pulls it back; (c) a drag on the canvas stops the craft dead -- planted (plantHoldFlight) it flies on; (d) a hovered browser element, a fresh object on every poll, still gets its flight within the dwell -- planted (plantIdentityDwell) none; (e) the node flown to last is flown to again after its flight ended; (f) the wheel all the way in keeps the node in view -- planted (plantNoZoomFloor) the camera goes inside it",
      async run() {
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0]?.view;
          if (!v || !v.graph || !v.agent) return { error: "no graph or agent" };
          const g = v.graph, cam = g.camera(), ctl = g.controls(), a = v.agent;
          const saved = { p: cam.position.clone(), t: ctl.target.clone(), up: cam.up.clone(), mode: a.mode, thr: a.throttle };
          const dist = (n) => Math.hypot(cam.position.x - n.x, cam.position.y - n.y, cam.position.z - (n.z || 0));
          const reset = () => { cam.position.copy(saved.p); ctl.target.copy(saved.t); cam.up.copy(saved.up); ctl.update?.(); a.vel = { x: 0, y: 0, z: 0 }; a.target = null; v.focusNode = null; v.focusPending = null; };
          const ns = g.graphData().nodes.filter((n) => Number.isFinite(n.x) && n.level !== "path");
          if (ns.length < 3) return { error: "too few nodes" };
          // Nodes about 250 units from the camera, so a flight has room.
          ns.sort((x, y) => Math.abs(dist(x) - 250) - Math.abs(dist(y) - 250));
          const n1 = ns[0], n2 = ns[1];
          // The look point ZOOM units ahead, on the line to n: the reader zoomed to ZOOM.
          const zoomAt = (n, zoom) => {
            const b = { x: n.x - cam.position.x, y: n.y - cam.position.y, z: (n.z || 0) - cam.position.z }; const bl = Math.hypot(b.x, b.y, b.z) || 1;
            ctl.target.set(cam.position.x + b.x / bl * zoom, cam.position.y + b.y / bl * zoom, cam.position.z + b.z / bl * zoom);
          };
          const arrive = async (ms) => { for (let i = 0; i < ms / 100; i++) { await sleep(100); if (!a.target) return true; } return false; };
          const out = { n1: String(n1.id).slice(0, 60), d1: Math.round(dist(n1)) };
          try {
            a.setMode("ego"); a.setThrottle(1); a.paused = false;
            // (a) the standoff is the reader's zoom.
            const standoff = async (planted) => {
              reset(); a.plantIgnoreZoom = planted; zoomAt(n1, 90);
              v.flyTo(n1); const done = await arrive(15000);
              return { end_d: Math.round(dist(n1) * 10) / 10, arrived: done, standoff: Math.round(a.standoff * 10) / 10, stop_floor: Math.round(a.stopFloor(n1) * 10) / 10 };
            };
            out.zoom = await standoff(false);
            out.zoom_planted = await standoff(true);
            a.plantIgnoreZoom = false;
            // (b) arrived, released: a moved look point stays moved.
            const hold = async (planted) => {
              reset(); a.plantHoldTarget = planted; zoomAt(n1, 60);
              v.flyTo(n1);
              if (planted) await sleep(6000); else await arrive(15000);
              const t0 = ctl.target.clone(); ctl.target.set(t0.x + 6, t0.y, t0.z);
              await sleep(1200);
              return { target_held: !!a.target, off_after: Math.round(Math.hypot(ctl.target.x - n1.x, ctl.target.y - n1.y, ctl.target.z - (n1.z || 0)) * 10) / 10 };
            };
            out.hold = await hold(false);
            out.hold_planted = await hold(true);
            a.plantHoldTarget = false;
            // (c) a drag on the canvas: a hand on the stick.
            const drag = async (planted) => {
              reset(); v.plantHoldFlight = planted; zoomAt(n2, 20);
              v.flyTo(n2); await sleep(900);
              const sp0 = Math.hypot(a.vel.x, a.vel.y, a.vel.z);
              v.canvasEl.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, cancelable: true, button: 0 }));
              const p0 = cam.position.clone(); await sleep(600);
              return { speed_before: Math.round(sp0 * 10) / 10, moved_after: Math.round(Math.hypot(cam.position.x - p0.x, cam.position.y - p0.y, cam.position.z - p0.z) * 10) / 10 };
            };
            out.drag = await drag(false);
            out.drag_planted = await drag(true);
            v.plantHoldFlight = false;
            // (d) fresh objects, one id, polled every 30 ms: the dwell still ends in a flight.
            const poll = async (planted) => {
              reset(); v.plantIdentityDwell = planted; zoomAt(n2, 20);
              // Counted WHILE the polls go on, as a pointer resting on a
              // browser element keeps asking: a dwell that completes only
              // once the asking stops is the defect.
              const f0 = v.focusStats.flown;
              for (let i = 0; i < 34; i++) { v.focusOn({ id: n2.id + "|/html/body/x", level: "chunk", virtual: true, x: n2.x, y: n2.y, z: n2.z || 0 }); await sleep(30); }
              const flights = v.focusStats.flown - f0;
              v.focusOn(null);
              return { flights };
            };
            out.poll = await poll(false);
            out.poll_planted = await poll(true);
            v.plantIdentityDwell = false;
            // (e) flown again after its flight ended.
            reset(); zoomAt(n1, 40);
            v.focusOn(n1); await sleep(300); await arrive(15000);
            const f1 = v.focusStats.flown; ctl.target.set(ctl.target.x + 30, ctl.target.y, ctl.target.z);
            v.focusOn(n1); await sleep(400);
            out.again_flights = v.focusStats.flown - f1;
            // (f) the wheel all the way in.
            const wheel = async (planted) => {
              reset(); v.plantNoZoomFloor = planted; zoomAt(n1, 40);
              v.flyTo(n1); await arrive(15000); await sleep(100);
              const tx = ctl.target;
              cam.position.set(tx.x + (cam.position.x - tx.x) * 0.001, tx.y + (cam.position.y - tx.y) * 0.001, tx.z + (cam.position.z - tx.z) * 0.001);
              ctl.update(); cam.updateMatrixWorld();
              const r = v.proxyRadius(n1), d = dist(n1);
              const q = cam.position.clone().set(n1.x, n1.y, n1.z || 0).project(cam);
              return { d: Math.round(d * 100) / 100, r: Math.round(r * 100) / 100, outside: d > r, min_distance: Math.round(ctl.minDistance * 100) / 100,
                       in_view: Math.abs(q.x) <= 1 && Math.abs(q.y) <= 1 && q.z < 1 };
            };
            out.wheel = await wheel(false);
            out.wheel_planted = await wheel(true);
          } finally {
            a.plantIgnoreZoom = false; a.plantHoldTarget = false; v.plantHoldFlight = false; v.plantIdentityDwell = false; v.plantNoZoomFloor = false;
            reset(); a.setThrottle(saved.thr); a.mode = saved.mode;
          }
          return out;
        })()`, { timeout: 180000 });
        if (!got || got.error) return { pass: false, evidence: got };
        // Planted, the flight closes to the floor -- where the wheel's own
        // floor (the node's fit) holds it, if that is further.
        const zoomOk = got.zoom.arrived && Math.abs(got.zoom.end_d - Math.max(90, got.zoom.stop_floor)) <= 3
          && got.zoom_planted.end_d < got.zoom.end_d - 20;
        const holdOk = !got.hold.target_held && got.hold.off_after > 4 && got.hold_planted.off_after < 2;
        const dragOk = got.drag.speed_before > 1 && got.drag.moved_after < 0.5 && got.drag_planted.moved_after > 2;
        const pollOk = got.poll.flights >= 1 && got.poll_planted.flights === 0;
        const wheelOk = got.wheel.outside && got.wheel.in_view && !got.wheel_planted.outside;
        return { pass: zoomOk && holdOk && dragOk && pollOk && got.again_flights >= 1 && wheelOk,
                 evidence: { ...got, verdicts: { zoomOk, holdOk, dragOk, pollOk, again: got.again_flights >= 1, wheelOk } } };
      },
    },
    {
      id: "G-286",
      asks: "the full chunk view runs in real time while its layout moves (2026-10-30, item 44): over 12 s of a reheated chunk-view layout no frame pays a full sync of every node -- a tick writes positions only, a picture landing patches its own nodes, and the safety net rolls a slice a frame -- and a positions write costs under half a full sync; planted (plantFullSyncOnTick + plantNetFullSync + plantSyncPerPicture, the old paths) full syncs come back",
      async run() {
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0]?.view;
          if (!v || !v.graph || !v.batch) return { error: "no graph" };
          const wasChunk = v.level === "chunk";
          const toggle = () => [...v.contentEl.querySelectorAll("button")].find((x) => x.textContent === (v.level === "chunk" ? "chunks" : "pages"))?.click();
          if (!wasChunk) {
            toggle();
            for (let i = 0; i < 120; i++) { await sleep(500); if (v.level === "chunk" && v.graph && v.graph.graphData().nodes.length > 5000) break; }
            await sleep(8000);
          }
          const g = v.graph;
          const set = (on) => { v.plantFullSyncOnTick = on; v.plantNetFullSync = on; v.plantSyncPerPicture = on; };
          const arm = async (planted) => {
            set(planted);
            let full = 0, fullMs = 0;
            const orig = v.batch.sync.bind(v.batch);
            v.batch.sync = (...a) => { const t = performance.now(); const r = orig(...a); full++; fullMs += performance.now() - t; return r; };
            const s0 = { ...v.batchStats };
            try { g.d3ReheatSimulation(); await sleep(12000); }
            finally { v.batch.sync = orig; set(false); }
            return { full_syncs: full, full_ms_avg: full ? Math.round(fullMs / full * 10) / 10 : null,
                     moved: v.batchStats.moved - s0.moved, rolled: v.batchStats.rolled - s0.rolled };
          };
          const out = { nodes: g.graphData().nodes.length };
          try {
            out.clean = await arm(false);
            out.planted = await arm(true);
            // One full sync, then one positions write over the layout it laid
            // out, timed back to back (a node streamed in since the last sync
            // makes positions refuse -- correctly -- so the sync comes first).
            const t1 = performance.now(); v.batchDirty = true; v.batchSync(); out.full_ms = Math.round((performance.now() - t1) * 10) / 10;
            const t0 = performance.now(); const ok = v.batch.positions(g.graphData().nodes); out.positions_ms = Math.round((performance.now() - t0) * 10) / 10; out.positions_ok = ok;
          } finally {
            if (!wasChunk) toggle();
          }
          return out;
        })()`, { timeout: 180000 });
        if (!got || got.error) return { pass: false, evidence: got };
        return { pass: got.nodes > 5000 && got.clean.full_syncs === 0 && got.clean.rolled > 0 && got.positions_ok
                   && got.positions_ms < got.full_ms / 2 && got.planted.full_syncs >= 3,
                 evidence: got };
      },
    },
    {
      id: "G-287",
      asks: "with no result hovered, the camera goes to the top-most ranked result in view of the scroll (2026-10-29, item 31): scrolling the bar so a result (3, or the next whose node is not result 1's) stands at the front asks a flight to its node; with a strip item hovered the scroll asks none (the hover wins); planted (plantNoScrollFlight) the scroll asks none",
      async run() {
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0]?.view;
          if (!v || !v.graph || !v.searchField) return { error: "no graph or search field" };
          const f = v.searchField, g = v.graph, cam = g.camera(), ctl = g.controls();
          const saved = { p: cam.position.clone(), t: ctl.target.clone(), q: f.input.value };
          const asked = [];
          const orig = v.focusOn.bind(v);
          v.focusOn = (n) => { if (n) asked.push(String(n.id)); return orig(n); };
          const scrollTo = async (rank) => {
            const win = f.window.length, span = f.scroller.scrollWidth - f.scroller.clientWidth;
            // The soft index runs 1..k over the bar; put rank at the front.
            f.scroller.scrollLeft = Math.round(span * (rank - 1) / Math.max(1, win - 1));
            // The scroll's own handler, called now: its rAF runs at 1 Hz in a
            // minimized window, and the front did not move within the wait.
            f.onScroll();
            await sleep(250);
          };
          const out = {};
          try {
            f.input.value = "python"; await f.run(); await sleep(1500);
            const st = v.searchState;
            out.results = st ? st.targets.filter(Boolean).length : 0;
            if (!st || out.results < 4) return { error: "too few results", out };
            // A rank whose NODE is not result 1's: in page view several
            // results resolve to one page node, and the hover's own flight
            // to result 1 then counted as the scroll's.
            const r0 = String(st.targets[0]?.id);
            let rank = 3;
            while (rank <= st.targets.length && (!st.targets[rank - 1] || String(st.targets[rank - 1].id) === r0)) rank++;
            if (rank > st.targets.length) return { error: "every result is one node", out };
            const want = String(st.targets[rank - 1].id);
            out.rank = rank;
            asked.length = 0; await scrollTo(rank);
            out.front = f.strip.querySelector(".is-front")?.textContent?.slice(0, 40);
            out.clean_asked = asked.slice(); out.clean_hit = asked.includes(want);
            await scrollTo(1); asked.length = 0;
            v.searchField.onHoverHit(f.hits[0]);
            await scrollTo(rank);
            out.hovered_asked = asked.filter((id) => id === want).length;
            v.searchField.onHoverHit(null);
            await scrollTo(1); asked.length = 0;
            v.plantNoScrollFlight = true;
            await scrollTo(rank);
            out.planted_asked = asked.filter((id) => id === want).length;
          } finally {
            v.plantNoScrollFlight = false; v.focusOn = orig; v.focusOn(null);
            f.input.value = saved.q; await f.run();
            v.agent.release(); cam.position.copy(saved.p); ctl.target.copy(saved.t); ctl.update?.();
          }
          return out;
        })()`, { timeout: 60000 });
        if (!got || got.error) return { pass: false, evidence: got };
        return { pass: got.clean_hit && got.hovered_asked === 0 && got.planted_asked === 0, evidence: got };
      },
    },
    {
      id: "G-288",
      asks: "search is a function in every cell's kernel (item 32): a cell running search('radix tree', db=True, duckduckgo=True, k=3) gets the database's ranked hits and a pending web row, and the run's reply carries ONE web ask that the plugin hands to the browser cell's own searchWeb (stubbed here, so the reader's page is not navigated); planted (/plant no-asks) the ask is dropped and the browser cell is asked nothing",
      async run() {
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const until = async (ok, ms) => { for (let t = 0; t < ms && !ok(); t += 250) await sleep(250); return ok(); };
          const plugin = app.plugins.getPlugin("domvec-bridge");
          const SIDE = String(plugin.settings.sidecar).replace(/[/]+$/, "");
          const NL = String.fromCharCode(10), F = String.fromCharCode(96).repeat(3);
          const folder = "domvec-checks";
          if (!app.vault.getAbstractFileByPath(folder)) await app.vault.createFolder(folder);
          const stamp = Date.now();
          const bl = app.workspace.getLeavesOfType("domvec-browser-view")[0];
          const browser = bl && bl.view;
          if (!browser || typeof browser.searchWeb !== "function") return { error: "no browser cell" };
          const realSearch = browser.searchWeb;
          const plant = (on) => fetch(SIDE + "/plant", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: "no-asks", on }) });
          const arm = async (planted) => {
            await plant(planted);
            const asked = [];
            browser.searchWeb = async (q) => { asked.push(q); };
            const path = folder + "/g288-" + (planted ? "p" : "c") + stamp + ".md";
            const code = ["r = search('radix tree', db=True, duckduckgo=True, k=3)",
                          "print(sum(1 for h in r if h['source'] == 'db'), sum(1 for h in r if h.get('pending')))"].join(NL);
            const f = await app.vault.create(path, "# search" + NL + NL + F + "python" + NL + code + NL + F + NL);
            const leaf = app.workspace.getLeaf("tab");
            const out = { planted };
            const web0 = plugin.askStats.web;
            try {
              await leaf.openFile(f, { state: { mode: "source", source: false } });
              const view = leaf.view;
              await until(() => !!view.containerEl.querySelector(".domvec-run-fence"), 8000);
              view.containerEl.querySelector(".domvec-run-fence").click();
              await until(() => view.editor.getValue().includes("nb-output"), 30000);
              await sleep(300);
              const text = view.editor.getValue();
              const m = /([0-9]+) ([0-9]+)/.exec(text.split("nb-output")[1] || "");
              out.db_hits = m ? Number(m[1]) : null;
              out.pending = m ? Number(m[2]) : null;
              out.asked = asked.slice();
              out.ask_stats = plugin.askStats.web - web0;
              out.undefined = /NameError/.test(text);
            } finally {
              browser.searchWeb = realSearch;
              await plant(false);
              try { leaf.detach(); } catch (e) {}
              try { await app.vault.delete(f); } catch (e) {}
            }
            return out;
          };
          return { clean: await arm(false), planted: await arm(true) };
        })()`, { timeout: 120000 });
        if (!got || got.error) return { pass: false, evidence: got };
        const c = got.clean, p = got.planted;
        return { pass: c.db_hits >= 1 && c.pending === 1 && c.asked.length === 1 && c.asked[0] === "radix tree"
                   && p.pending === 1 && p.asked.length === 0,
                 evidence: got };
      },
    },
    {
      id: "G-289",
      asks: "only the reader's TRUSTED input marks the reader active: a check's synthetic pointer move and key leave the reader's last-active time where it was and are tallied as synthetic; planted (__domvecPlantSyntheticReader) they stamp the reader, as when G-174's own sweep paused its run for 'the reader is using the app' in a minimized window",
      async run() {
        const got = await evaluate(`(async () => {
          const canvas = document.querySelector(".domvec-graph-canvas") || document.body;
          const fire = () => {
            canvas.dispatchEvent(new PointerEvent("pointermove", { bubbles: true, clientX: 10, clientY: 10 }));
            window.dispatchEvent(new KeyboardEvent("keydown", { key: "F24", bubbles: true }));
          };
          const arm = (planted) => {
            window.__domvecPlantSyntheticReader = planted;
            const at0 = window.__domvecReaderAt = 1;            // a sentinel no real stamp equals
            const by0 = { ...(window.__domvecReaderBy || {}) };
            try { fire(); } finally { window.__domvecPlantSyntheticReader = false; }
            const by = window.__domvecReaderBy || {};
            return { stamped: window.__domvecReaderAt !== at0, synthetic: (by["synthetic:pointermove"] || 0) - (by0["synthetic:pointermove"] || 0) };
          };
          const saved = window.__domvecReaderAt;
          try { return { clean: arm(false), planted: arm(true) }; }
          finally { if (window.__domvecReaderAt === 1 || window.__domvecReaderAt > saved) window.__domvecReaderAt = saved; }
        })()`, { timeout: 15000 });
        if (!got || got.error) return { pass: false, evidence: got };
        return { pass: !got.clean.stamped && got.clean.synthetic === 1 && got.planted.stamped, evidence: got };
      },
    },
    {
      id: "G-280",
      asks: "the cockpit is a node (items 10, 24, 30-33, 36-37): the ego slate opens as a vault note in the slate class (black fill, serif white); its throttle text sets the agent and Shift writes the new throttle and the lit key back into the text; its search query runs the search with the slate's k; a right-click on {results} internalizes the rank-1 rows and a hover on a row asks a flight to its node; a click on db's value toggles it and off clears the store's ranking; the cockpit's title collapses it to its circle and the circle opens it; {keys} referenced from ANOTHER slate reveals the key samples (planted plantKeysCockpitOnly: no key samples -- the name goes to the store instead); planted (cockpit.plantUnbound) the text binds nothing either way",
      async run() {
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const p = app.plugins.getPlugin("domvec-bridge"), c = p.cockpit;
          const g = app.workspace.getLeavesOfType("domvec-graph-view")[0]?.view;
          if (!c || !g || !g.searchField) return { error: "no cockpit or graph" };
          const v = await c.open(); await sleep(1200);
          if (!v) return { error: "cockpit did not open" };
          const ed = v.editor, saved = ed.getValue(), thr0 = g.agent.throttle, over0 = g.pointerOver, fold0 = c.resultsOpen;
          const line = (k) => ed.getValue().split(String.fromCharCode(10)).findIndex((l) => l.trim().split(String.fromCharCode(9))[0] === k);
          const valOf = (k) => { const l = ed.getLine(line(k)); const i = l.lastIndexOf(String.fromCharCode(9)); return l.slice(i + 1); };
          const setVal = (k, val) => { const i = line(k), l = ed.getLine(i), at = l.lastIndexOf(String.fromCharCode(9)) + 1; ed.replaceRange(val, { line: i, ch: at }, { line: i, ch: l.length }); };
          const fieldOf = (k) => { const i = line(k), l = ed.getLine(i), at = l.lastIndexOf(String.fromCharCode(9)) + 1; return { line: i, valueFrom: at, value: l.slice(at), key: k }; };
          const arm = async (planted) => {
            c.plantUnbound = planted;
            const out = { planted };
            const leaf = c.leaf(), cs = getComputedStyle(leaf.view.contentEl.querySelector(".cm-content"));
            out.slate = leaf.containerEl.classList.contains("domvec-slate") && /Georgia|serif/.test(cs.fontFamily) && cs.color === "rgb(255, 255, 255)";
            g.agent.setThrottle(0.2); await sleep(600);
            setVal("throttle", "40"); await sleep(500);
            out.agent_throttle = Math.round(g.agent.throttle * 100);
            g.pointerOver = true;
            window.dispatchEvent(new KeyboardEvent("keydown", { key: "Shift", bubbles: true }));
            await sleep(700);
            out.text_throttle = valOf("throttle"); out.text_last = valOf("last");
            setVal("query", "radix tree"); await sleep(2500);
            out.query = g.searchField.query; out.k = g.searchField.k;
            c.resultsOpen = false; c.toggleResults(); await sleep(700);
            out.rows = c.resultRows().length;
            const f0 = g.focusStats.asked; c.hoverRow(2); await sleep(300); c.hoverRow(0);
            out.row_flight = g.focusStats.asked - f0;
            c.toggle(fieldOf("db")); await sleep(800);
            out.db = valOf("db"); out.query_db_off = g.searchField.query;
            return out;
          };
          // The cockpit collapses to its circle like any slate, and {keys} is
          // referenced from ANOTHER slate (item 22); planted: cockpit-only.
          const extra = async () => {
            const out = {};
            const cv = c.view(), cm = cv.editor.cm;
            const tpos = cm.state.doc.toString().indexOf(String.fromCharCode(10) + "ego") + 2;
            const at = cm.coordsAtPos(tpos);
            const rc = (el, x, y) => el.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: x, clientY: y, button: 2 }));
            rc(document.elementFromPoint((at.left + at.right) / 2, (at.top + at.bottom) / 2) || cv.contentEl, (at.left + at.right) / 2, (at.top + at.bottom) / 2);
            await sleep(500);
            const circ = cv.contentEl.querySelector(".domvec-slate-circle");
            out.cockpit_circle = circ ? circ.textContent : null;
            if (circ) { rc(circ, 1, 1); await sleep(500); }
            out.cockpit_reopened = !cv.contentEl.querySelector(".domvec-slate-circle");
            const NL2 = String.fromCharCode(10), TB2 = String.fromCharCode(9);
            const f = await app.vault.create("domvec-checks/g280 keys " + Date.now() + ".md", "---" + NL2 + "domvec: slate" + NL2 + "---" + NL2 + "listener" + NL2 + TB2 + "input" + TB2 + "{keys}" + NL2);
            const leaf = app.workspace.getLeaf("tab");
            try {
              g.pointerOver = true; window.dispatchEvent(new KeyboardEvent("keydown", { key: "Shift", bubbles: true })); g.pointerOver = over0;
              await leaf.openFile(f, { state: { mode: "source", source: false } }); await sleep(800); c.decorate(); await sleep(200);
              for (const planted of [true, false]) {
                c.plantKeysCockpitOnly = planted;
                const r = await c.slateGesture(leaf.view, ...(() => { const cm2 = leaf.view.editor.cm, p2 = cm2.state.doc.toString().indexOf("{keys}") + 2, a2 = cm2.coordsAtPos(p2); return [(a2.left + a2.right) / 2, (a2.top + a2.bottom) / 2]; })(), null);
                await sleep(400);
                const rv = leaf.view.contentEl.querySelector(".domvec-slate-reveal");
                out[planted ? "keys_planted" : "keys"] = { result: r, reveal: rv ? rv.textContent.slice(0, 60) : null };
                if (rv) { await c.slateGesture(leaf.view, ...(() => { const cm2 = leaf.view.editor.cm, p2 = cm2.state.doc.toString().indexOf("{keys}") + 2, a2 = cm2.coordsAtPos(p2); return [(a2.left + a2.right) / 2, (a2.top + a2.bottom) / 2]; })(), null); await sleep(300); }
              }
            } finally {
              c.plantKeysCockpitOnly = false;
              try { leaf.detach(); } catch (e) {}
              try { window.localStorage.removeItem("domvec.slate.folds:" + f.path); } catch (e) {}
              try { await app.vault.delete(f); } catch (e) {}
            }
            return out;
          };
          try {
            return { clean: await arm(false), planted: await arm(true), extra: await extra() };
          } finally {
            c.plantUnbound = false; g.pointerOver = over0; c.resultsOpen = fold0;
            c.hoverRow(0);
            ed.setValue(saved); await sleep(500);
            g.agent.setThrottle(thr0); g.searchField.input.value = ""; await g.searchField.run();
          }
        })()`, { timeout: 90000 });
        if (!got || got.error) return { pass: false, evidence: got };
        const c = got.clean, p = got.planted;
        return { pass: c.slate && c.agent_throttle === 40 && c.text_throttle === "45" && /throttle up/.test(c.text_last)
                   && c.query === "radix tree" && c.k === 8 && c.rows >= 1 && c.row_flight >= 1
                   && c.db === "false" && c.query_db_off === ""
                   && p.agent_throttle === 20 && p.text_throttle === "40"
                   && got.extra.cockpit_circle === "ego" && got.extra.cockpit_reopened
                   && /throttle up/.test(got.extra.keys.reveal || "") && !/throttle up/.test(got.extra.keys_planted.reveal || ""),
                 evidence: got };
      },
    },
    {
      id: "G-290",
      asks: "the full chunk view does not churn memory while the reader is away (item 44: 'memory degradation/latency lag'): over 12 s in chunk view with the hover ranking driven ten times a second (as a turning camera drives it), a heap sampling profile that keeps collected objects counts the MB allocated per rendered frame -- under a third of the old paths' (planted: plantDetailFromNodes + __domvecPlantPhotons + plantNetFullSync -- the hover ranking over node objects, the particle walk over every link, the 2 s net); the hover ranking and the particle walk each drop out of the top allocators",
      async run() {
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0]?.view;
          if (!v || !v.graph) return { error: "no graph" };
          const wasChunk = v.level === "chunk";
          const toggle = () => [...v.contentEl.querySelectorAll("button")].find((x) => x.textContent === (v.level === "chunk" ? "chunks" : "pages"))?.click();
          if (!wasChunk) { toggle(); for (let i = 0; i < 120; i++) { await sleep(500); if (v.level === "chunk" && v.graph && v.graph.graphData().nodes.length > 5000) break; } await sleep(8000); }
          const wc = require("@electron/remote").getCurrentWebContents(), d = wc.debugger;
          let attached = false;
          if (!d.isAttached()) { d.attach("1.3"); attached = true; }
          const set = (on) => { v.plantDetailFromNodes = on; globalThis.__domvecPlantPhotons = on; v.plantNetFullSync = on; };
          // The idle turn moves the camera, so the hover ranking runs each frame.
          const arm = async (planted) => {
            set(planted);
            const f0 = v.frameGaps.length;
            await d.sendCommand("HeapProfiler.startSampling", { samplingInterval: 16384, includeObjectsCollectedByMajorGC: true, includeObjectsCollectedByMinorGC: true });
            // The hover ranking driven ten times a second, as a moving camera
            // or pointer drives it (the idle turn pauses while checks run).
            const drive = setInterval(() => { v.detailDirty = true; v.detailAt = 0; v.refreshDetail(v.graph); }, 100);
            try { await sleep(12000); } finally { clearInterval(drive); }
            const { profile } = await d.sendCommand("HeapProfiler.stopSampling");
            set(false);
            const frames = Math.max(1, v.frameGaps.length - f0);
            const by = new Map();
            const walk = (n, stack) => {
              const name = n.callFrame.functionName || "(anon)";
              const st = stack.concat(name);
              if (n.selfSize) for (const fn of new Set(st)) by.set(fn, (by.get(fn) || 0) + n.selfSize);
              for (const c of n.children || []) walk(c, st);
            };
            walk(profile.head, []);
            const total = by.get("(root)") || 0;
            const mb = (x) => Math.round(x / 1e5) / 10;
            return { frames, total_mb: mb(total), mb_per_frame: Math.round(total / frames / 1e4) / 100,
                     refreshDetail_mb: mb(by.get("refreshDetail") || 0), updatePhotons_mb: mb(by.get("updatePhotons") || 0), patch_mb: mb(by.get("patch") || 0) };
          };
          try {
            await d.sendCommand("HeapProfiler.enable");
            return { nodes: v.graph.graphData().nodes.length, clean: await arm(false), planted: await arm(true) };
          } finally {
            set(false);
            try { await d.sendCommand("HeapProfiler.disable"); } catch (e) {}
            if (attached) d.detach();
            if (!wasChunk) toggle();
          }
        })()`, { timeout: 120000 });
        if (!got || got.error) return { pass: false, evidence: got };
        const c = got.clean, p = got.planted;
        return { pass: got.nodes > 5000 && c.mb_per_frame < p.mb_per_frame / 3
                   && c.refreshDetail_mb < p.refreshDetail_mb / 5 && c.updatePhotons_mb < p.updatePhotons_mb / 5,
                 evidence: got };
      },
    },
    {
      id: "G-291",
      asks: "UMAP places the ego reservoir (item 43): a slate note and a note with a python cell that has RUN (a stored readout), created in the vault, are indexed on their own and arrive in the 3D graph as vault:// pages with a UMAP place (finite fit); a plain note and a never-run python block (a design doc's illustration) are not indexed; planted (__domvecPlantNoReservoirIndex) neither computation-graph note arrives; a deleted reservoir note leaves the store even with an index pending (planted __domvecPlantKeepDeleted: it stays)",
      async run() {
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const plugin = app.plugins.getPlugin("domvec-bridge");
          const SIDE = String(plugin.settings.sidecar).replace(/[/]+$/, "");
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0]?.view;
          if (!v || !v.graph) return { error: "no graph" };
          const NL = String.fromCharCode(10), F = String.fromCharCode(96).repeat(3), TB = String.fromCharCode(9);
          const folder = "domvec-checks";
          if (!app.vault.getAbstractFileByPath(folder)) await app.vault.createFolder(folder);
          const vaultName = app.vault.getName();
          const urlOf = (path) => "vault://" + vaultName + "/" + path;
          const nodeOf = (url) => v.graph.graphData().nodes.find((n) => n.url === url && n.level === "page");
          const arm = async (planted) => {
            window.__domvecPlantNoReservoirIndex = planted;
            const stamp = Date.now() + (planted ? "p" : "c");
            const files = {
              slate: [folder + "/g291 slate " + stamp + ".md", "---" + NL + "domvec: slate" + NL + "---" + NL + "reservoir probe" + NL + TB + "marker" + TB + stamp + NL],
              cell: [folder + "/g291 cell " + stamp + ".md", "# cell" + NL + NL + F + "python" + NL + "x = 'reservoir " + stamp + "'" + NL + F + NL + "<!-- nb-output hash=0 count=1 status=ok -->" + NL + F + "text" + NL + "ok" + NL + F + NL + "<!-- /nb-output -->" + NL],
              plain: [folder + "/g291 plain " + stamp + ".md", "# plain" + NL + NL + "just prose " + stamp + NL],
              unrun: [folder + "/g291 unrun " + stamp + ".md", "# doc" + NL + NL + F + "python" + NL + "illustration = 1" + NL + F + NL],
            };
            const made = [];
            try {
              for (const [path, text] of Object.values(files)) made.push(await app.vault.create(path, text));
              const out = { planted };
              const t0 = performance.now();
              const want = Object.fromEntries(Object.entries(files).map(([k, [path]]) => [k, urlOf(path)]));
              for (let i = 0; i < 40; i++) {
                await sleep(1000);
                if (!planted && nodeOf(want.slate) && nodeOf(want.cell)) break;
              }
              await sleep(planted ? 0 : 3000);         // the plain note's chance to (wrongly) arrive
              for (const k of Object.keys(want)) {
                const n = nodeOf(want[k]);
                out[k] = n ? { placed: Number.isFinite(n.fitX) && Number.isFinite(n.fitY), at: [Math.round(n.x), Math.round(n.y), Math.round(n.z || 0)] } : null;
              }
              out.s = Math.round((performance.now() - t0) / 100) / 10;
              return out;
            } finally {
              window.__domvecPlantNoReservoirIndex = false;
              for (const f of made) {
                try { await fetch(SIDE + "/purge", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ url: urlOf(f.path) }) }); } catch (e) {}
                try { await app.vault.delete(f); } catch (e) {}
              }
            }
          };
          // Deleting a reservoir note takes it out of the store (and no late
          // index brings it back); planted __domvecPlantKeepDeleted: it stays.
          const inStore = async (url) => ((await (await fetch(SIDE + "/cypher", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ query: "MATCH (p:Page {url: '" + url.replace(/'/g, "") + "'}) RETURN count(p)" }) })).json()).rows || [[0]])[0][0];
          const delArm = async (planted) => {
            const path = folder + "/g291 del " + (planted ? "p" : "c") + Date.now() + ".md";
            const f = await app.vault.create(path, "---" + NL + "domvec: slate" + NL + "---" + NL + "deleted probe" + NL + TB + "x" + TB + "1" + NL);
            for (let i = 0; i < 40 && !nodeOf(urlOf(path)); i++) await sleep(1000);
            const before = await inStore(urlOf(path));
            window.__domvecPlantKeepDeleted = planted;
            try { await app.vault.modify(f, "---" + NL + "domvec: slate" + NL + "---" + NL + "deleted probe" + NL + TB + "x" + TB + "2" + NL); await app.vault.delete(f); }
            finally { window.__domvecPlantKeepDeleted = false; }
            await sleep(7000);                       // past the 4 s index debounce
            const after = await inStore(urlOf(path));
            if (after) await fetch(SIDE + "/purge", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ url: urlOf(path) }) });
            return { before, after };
          };
          return { clean: await arm(false), planted: await arm(true), del: await delArm(false), del_planted: await delArm(true) };
        })()`, { timeout: 240000 });
        if (!got || got.error) return { pass: false, evidence: got };
        const c = got.clean, p = got.planted;
        return { pass: !!(c.slate && c.slate.placed && c.cell && c.cell.placed) && !c.plain && !c.unrun && !p.slate && !p.cell
                   && got.del.before >= 1 && got.del.after === 0 && got.del_planted.after >= 1, evidence: got };
      },
    },
    {
      id: "G-292",
      asks: "the signal flow renders live (item 44): a cell whose fence names a vault note by {ref} is run with the real Run button; its run's input -> cell edge is drawn in 3D as a line from the source note's node to the cell note's node (placed by UMAP, G-291), PULSING when it first draws (alpha above its rest) and back at rest after the pulse; the store answers /signal with the edge; planted (plantNoSignal) no signal line is drawn",
      async run() {
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const until = async (ok, ms) => { for (let t = 0; t < ms && !ok(); t += 250) await sleep(250); return ok(); };
          const plugin = app.plugins.getPlugin("domvec-bridge");
          const SIDE = String(plugin.settings.sidecar).replace(/[/]+$/, "");
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0]?.view;
          if (!v || !v.graph) return { error: "no graph" };
          const NL = String.fromCharCode(10), F = String.fromCharCode(96).repeat(3);
          const folder = "domvec-checks";
          if (!app.vault.getAbstractFileByPath(folder)) await app.vault.createFolder(folder);
          const vaultName = app.vault.getName(), urlOf = (path) => "vault://" + vaultName + "/" + path;
          const stamp = Date.now();
          const srcName = "g292 source " + stamp;
          const src = await app.vault.create(folder + "/" + srcName + ".md", "# Source" + NL + NL + "Signal source, marker " + stamp + "." + NL);
          await plugin.indexNote(src, "check");
          const varName = srcName.replace(/[^A-Za-z0-9_]+/g, "_").replace(/^_+|_+$/g, "").toLowerCase();
          const cellPath = folder + "/g292 cell " + stamp + ".md";
          const cell = await app.vault.create(cellPath, "# cell" + NL + NL + F + "python {" + srcName + "}" + NL + "print(len(" + varName + "))" + NL + F + NL);
          const leaf = app.workspace.getLeaf("tab");
          const out = {};
          const edgeTo = () => {
            const ns = v.graph.graphData().nodes;
            const t = ns.find((n) => n.id === "page:" + urlOf(cellPath));
            const s = ns.find((n) => n.id === "page:" + urlOf(src.path));
            if (!t || !s) return null;
            // Direct, or through the cell's bisector (G-282).
            const bis = v.bisectors.get(cellPath);
            return v.drawableSignalEdges(ns).find((e) => e.source === s && (e.target === t || (bis && e.target === bis.at))) || null;
          };
          try {
            await leaf.openFile(cell, { state: { mode: "source", source: false } });
            const view = leaf.view;
            await until(() => !!view.containerEl.querySelector(".domvec-run-fence"), 8000);
            view.containerEl.querySelector(".domvec-run-fence").click();
            await until(() => view.editor.getValue().includes("nb-output"), 30000);
            const sig = await (await fetch(SIDE + "/signal?k=50")).json();
            out.store_edge = (sig.edges || []).some((e) => e.note === cellPath);
            // The cell note reaches 3D after its readout is stored and it is re-indexed.
            const t0 = performance.now();
            let first = null;
            for (let i = 0; i < 160 && !first; i++) { await sleep(250); first = edgeTo(); }
            out.drawn_after_s = first ? Math.round((performance.now() - t0) / 100) / 10 : null;
            out.alpha_first = first ? Math.round(first.alpha * 100) / 100 : null;
            await sleep(v.signalPulseMs + 600);
            const later = edgeTo();
            out.alpha_rest = later ? Math.round(later.alpha * 100) / 100 : null;
            out.line_colour = first ? first.color : null;
            v.plantNoSignal = true;
            out.planted_drawn = v.drawableSignalEdges(v.graph.graphData().nodes).length;
            v.plantNoSignal = false;
            out.stats = { ...v.signalStats };
          } finally {
            v.plantNoSignal = false;
            try { leaf.detach(); } catch (e) {}
            for (const f of [cell, src]) {
              try { await fetch(SIDE + "/purge", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ url: urlOf(f.path) }) }); } catch (e) {}
              try { await app.vault.delete(f); } catch (e) {}
            }
          }
          return out;
        })()`, { timeout: 120000 });
        if (!got || got.error) return { pass: false, evidence: got };
        return { pass: got.store_edge && got.drawn_after_s !== null && got.alpha_first > 0.6 && got.alpha_rest !== null
                   && got.alpha_rest < 0.5 && got.planted_drawn === 0,
                 evidence: got };
      },
    },
    {
      id: "G-283",
      asks: "a flight plan (items 8-9): in the cockpit, plan {results} and play true fly the craft through the search's results one leg at a time at the throttle, each leg ending on arrival -- at least two legs taken, the craft's look point on its last leg's node, and play written back false when the plan ends; a drag on the canvas stops the play and writes play false back into the slate; plan {Radix tree} -- an anchored target through the store -- flies too; planted (agent.plantNoAdvance) the play stops after its first leg",
      async run() {
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const p = app.plugins.getPlugin("domvec-bridge"), c = p.cockpit;
          const g = app.workspace.getLeavesOfType("domvec-graph-view")[0]?.view;
          if (!c || !g || !g.searchField) return { error: "no cockpit or graph" };
          const v = await c.open(); await sleep(1200);
          const ed = v.editor, saved = ed.getValue(), a = g.agent, thr0 = a.throttle;
          const cam = g.graph.camera(), ctl = g.graph.controls();
          const savedCam = { p: cam.position.clone(), t: ctl.target.clone() };
          const line = (k) => ed.getValue().split(String.fromCharCode(10)).findIndex((l) => l.trim().split(String.fromCharCode(9))[0] === k);
          const valOf = (k) => { const l = ed.getLine(line(k)); return l.slice(l.lastIndexOf(String.fromCharCode(9)) + 1); };
          const setVal = (k, val) => { const i = line(k), l = ed.getLine(i), at = l.lastIndexOf(String.fromCharCode(9)) + 1; ed.replaceRange(val, { line: i, ch: at }, { line: i, ch: l.length }); };
          const arm = async (planted) => {
            a.plantNoAdvance = planted;
            cam.position.copy(savedCam.p); ctl.target.copy(savedCam.t); ctl.update?.(); a.release();
            const s0 = { ...a.planStats };
            // The search changed from ANOTHER surface first (the 3D field):
            // the slate must still ask for its own query.
            setVal("query", "radix tree"); await sleep(800);
            g.searchField.input.value = ""; await g.searchField.run();
            // The engine changed LAST, so the slate's sync writes its query
            // back; only then is setting "radix tree" an edit (a fixed 600 ms
            // raced the sync, and the planted arm's search never ran).
            for (let i = 0; i < 40 && valOf("query") !== ""; i++) await sleep(150);
            setVal("throttle", "100"); setVal("query", "radix tree");
            // The tiered search takes 1-3 s cold: wait for its results, not a fixed time.
            for (let i = 0; i < 40 && (g.searchState?.targets || []).filter(Boolean).length < 3; i++) await sleep(250);
            const targets = (g.searchState?.targets || []).filter(Boolean);
            setVal("play", "true"); await sleep(400);
            const out = { planted, targets: targets.length, playing_at_start: a.playing };
            for (let i = 0; i < 80 && a.playing; i++) await sleep(500);
            out.legs = a.planStats.legs - s0.legs;
            out.plan_at = a.planAt;
            // Where the craft ended: on the last leg's node (its look point).
            const last = a.plan[a.planAt];
            out.on_last_leg = last ? Math.round(Math.hypot(ctl.target.x - last.x, ctl.target.y - last.y, ctl.target.z - (last.z || 0)) * 10) / 10 : null;
            // The agent's own arrival rule: aimed within 1% of the distance (UserAgent.tick).
            out.arrival_tolerance = last ? Math.round(Math.max(0.05, Math.hypot(cam.position.x - last.x, cam.position.y - last.y, cam.position.z - (last.z || 0)) * 0.01) * 10) / 10 + 0.1 : null;
            await sleep(700);                              // the slate's sync writes play back
            out.text_play_finished = valOf("play");
            if (!planted) {
              // A hand on the stick mid-plan: a fresh play, stopped by a drag.
              setVal("play", "true"); await sleep(700);
              out.replayed = a.playing;
              g.canvasEl.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, cancelable: true, button: 0 }));
              await sleep(800);
              out.playing_after_drag = a.playing; out.text_play_after_drag = valOf("play");
              // An anchored plan: any {ref}, resolved through the store.
              const l0 = a.planStats.legs;
              setVal("play", "false"); await sleep(400);
              setVal("plan", "{Radix tree}"); setVal("play", "true");
              for (let i = 0; i < 40 && (a.playing || a.planStats.legs === l0); i++) await sleep(500);
              out.anchored_resolved = c.planStats.resolved; out.anchored_legs = a.planStats.legs - l0;
              a.play(false); setVal("play", "false"); setVal("plan", "{results}"); await sleep(400);
            }
            a.play(false); setVal("play", "false"); await sleep(400);
            return out;
          };
          try {
            return { clean: await arm(false), planted: await arm(true) };
          } finally {
            a.plantNoAdvance = false; a.play(false); a.release();
            ed.setValue(saved); await sleep(500);
            a.setThrottle(thr0); g.searchField.input.value = ""; await g.searchField.run();
            cam.position.copy(savedCam.p); ctl.target.copy(savedCam.t); ctl.update?.();
          }
        })()`, { timeout: 120000 });
        if (!got || got.error) return { pass: false, evidence: got };
        const c = got.clean, p = got.planted;
        return { pass: c.targets >= 3 && c.playing_at_start && c.legs >= 2 && c.on_last_leg !== null && c.on_last_leg <= Math.max(2, c.arrival_tolerance)
                   && c.text_play_finished === "false" && c.replayed && !c.playing_after_drag && c.text_play_after_drag === "false"
                   && c.anchored_resolved >= 1 && c.anchored_legs >= 1
                   && p.legs === 1,
                 evidence: got };
      },
    },
    {
      id: "G-278",
      asks: "slate notes in the native editor (RESERVOIR_DESIGN §3.1-3.3): in a slate note, a right-click on a {ref} naming another slate note internalizes it -- the target's rank-1 lines shown under the line, the braces dropped -- and a second folds it back; the reveal is kept when the note is closed and reopened; a right-click on the title collapses the slate to its circle and one on the circle opens it; nothing is written into the note; planted (cockpit.plantNoFolds) the right-clicks do nothing",
      async run() {
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const until = async (ok, ms) => { for (let t = 0; t < ms && !ok(); t += 200) await sleep(200); return ok(); };
          const plugin = app.plugins.getPlugin("domvec-bridge"), c = plugin.cockpit;
          const SIDE = String(plugin.settings.sidecar).replace(/[/]+$/, "");
          const NL = String.fromCharCode(10), TB = String.fromCharCode(9);
          const folder = "domvec-checks";
          if (!app.vault.getAbstractFileByPath(folder)) await app.vault.createFolder(folder);
          const vaultName = app.vault.getName(), urlOf = (path) => "vault://" + vaultName + "/" + path;
          const stamp = Date.now();
          const tName = "g278 target " + stamp;
          const target = await app.vault.create(folder + "/" + tName + ".md", "---" + NL + "domvec: slate" + NL + "---" + NL + "target" + NL + TB + "marker" + TB + "m" + stamp + NL + TB + "depth" + NL + TB + TB + "hidden" + TB + "deep" + NL);
          await plugin.indexNote(target, "check");
          const slateText = "---" + NL + "domvec: slate" + NL + "---" + NL + "probe" + NL + TB + "input" + TB + "{" + tName + "}" + NL + TB + "note" + TB + "plain" + NL;
          const slate = await app.vault.create(folder + "/g278 slate " + stamp + ".md", slateText);
          const open = async () => {
            const leaf = app.workspace.getLeaf("tab");
            await leaf.openFile(slate, { state: { mode: "source", source: false } });
            await sleep(800); c.decorate(); await sleep(300);
            return leaf;
          };
          const right = (v, pos, el) => {
            const cm = v.editor.cm, at = cm.coordsAtPos(pos);
            const x = (at.left + at.right) / 2, y = (at.top + at.bottom) / 2;
            const t = el || document.elementFromPoint(x, y) || v.contentEl;
            t.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: x, clientY: y, button: 2 }));
          };
          const tokenPos = (v) => { const tx = v.editor.cm.state.doc.toString(); return tx.indexOf("{" + tName + "}") + 3; };
          const titlePos = (v) => v.editor.cm.state.doc.toString().indexOf("probe") + 2;
          const out = {};
          let leaf = null;
          try {
            for (const planted of [true, false]) {
              c.plantNoFolds = planted;
              leaf = await open();
              const v = leaf.view;
              const arm = {};
              right(v, tokenPos(v));
              await until(() => !!v.contentEl.querySelector(".domvec-slate-reveal"), planted ? 1500 : 8000);
              const rv = v.contentEl.querySelector(".domvec-slate-reveal");
              arm.revealed = !!rv;
              arm.reveal_text = rv ? rv.textContent.slice(0, 120) : null;
              const lineEl = [...v.contentEl.querySelectorAll(".cm-line")].find((l) => l.textContent.includes(tName));
              arm.braces_shown = lineEl ? lineEl.textContent.includes("{") : null;
              arm.text_unchanged = v.editor.getValue() === slateText;
              if (!planted) {
                // Kept across a close and reopen.
                leaf.detach(); leaf = await open();
                const v2 = leaf.view;
                arm.kept = !!v2.contentEl.querySelector(".domvec-slate-reveal");
                right(v2, tokenPos(v2)); await sleep(500);
                arm.folded = !v2.contentEl.querySelector(".domvec-slate-reveal");
                right(v2, titlePos(v2)); await sleep(500);
                const circ = v2.contentEl.querySelector(".domvec-slate-circle");
                arm.collapsed = !!circ && !v2.contentEl.querySelector(".cm-line") ? true : !!circ;
                arm.circle_text = circ ? circ.textContent : null;
                if (circ) { circ.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: 1, clientY: 1, button: 2 })); await sleep(500); }
                arm.reopened = !v2.contentEl.querySelector(".domvec-slate-circle");
                arm.text_unchanged_after = v2.editor.getValue() === slateText;
              }
              out[planted ? "planted" : "clean"] = arm;
              leaf.detach(); leaf = null;
            }
            out.stats = { ...c.foldStats };
          } finally {
            c.plantNoFolds = false;
            try { leaf && leaf.detach(); } catch (e) {}
            try { window.localStorage.removeItem("domvec.slate.folds:" + slate.path); } catch (e) {}
            for (const f of [slate, target]) {
              try { await fetch(SIDE + "/purge", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ url: urlOf(f.path) }) }); } catch (e) {}
              try { await app.vault.delete(f); } catch (e) {}
            }
          }
          return out;
        })()`, { timeout: 120000 });
        if (!got || got.error) return { pass: false, evidence: got };
        const c = got.clean, p = got.planted;
        return { pass: c.revealed && /m[0-9]+/.test(c.reveal_text || "") && !/deep/.test(c.reveal_text || "") && c.braces_shown === false
                   && c.text_unchanged && c.kept && c.folded && c.collapsed && c.reopened && c.text_unchanged_after
                   && !p.revealed,
                 evidence: got };
      },
    },
    {
      id: "G-281",
      asks: "graph form (UR M.7, O.16; item 37): a double left-click on a slate flips it to its graph form -- one circular node per field (node-count parity with the slate), one undirected line per non-root field to its parent, a {ref} field's node hollow -- and a second flips it back; the form is kept across a reopen; the note's text never changes by a flip; a left-drag from one node onto another WIRES them -- {target} written into the field, a solid link drawn (UR N.4; planted __domvecPlantNoWire: nothing written); planted (cockpit.plantNoGraphForm) the double-click flips nothing",
      async run() {
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const plugin = app.plugins.getPlugin("domvec-bridge"), c = plugin.cockpit;
          const NL = String.fromCharCode(10), TB = String.fromCharCode(9);
          const folder = "domvec-checks";
          if (!app.vault.getAbstractFileByPath(folder)) await app.vault.createFolder(folder);
          const stamp = Date.now();
          const text = "---" + NL + "domvec: slate" + NL + "---" + NL + "probe" + NL + TB + "query" + TB + "radix" + NL + TB + "source" + TB + "{somewhere}" + NL + TB + "search" + NL + TB + TB + "db" + TB + "true" + NL + TB + TB + "k" + TB + "8" + NL;
          const fields = 6, roots = 1;
          const f = await app.vault.create(folder + "/g281 slate " + stamp + ".md", text);
          const open = async () => { const leaf = app.workspace.getLeaf("tab"); await leaf.openFile(f, { state: { mode: "source", source: false } }); await sleep(800); c.decorate(); await sleep(300); return leaf; };
          const dbl = (v) => {
            const t = v.contentEl.querySelector(".domvec-slate-graph") || v.contentEl.querySelector(".cm-content");
            t.dispatchEvent(new MouseEvent("dblclick", { bubbles: true, cancelable: true, button: 0 }));
          };
          const read = (v) => {
            const g = v.contentEl.querySelector(".domvec-slate-graph");
            return g ? { graph: true, nodes: g.querySelectorAll("circle").length, lines: g.querySelectorAll("line").length,
                         hollow: g.querySelectorAll("circle.is-ref").length, labels: [...g.querySelectorAll("text")].map((x) => x.textContent) }
                     : { graph: false };
          };
          const out = { fields, roots };
          let leaf = null;
          try {
            for (const planted of [true, false]) {
              c.plantNoGraphForm = planted;
              leaf = await open();
              const v = leaf.view;
              dbl(v); await sleep(400);
              const arm = { flipped: read(v) };
              if (!planted) {
                leaf.detach(); leaf = await open();
                arm.kept = read(leaf.view).graph;
                dbl(leaf.view); await sleep(400);
                arm.back = !read(leaf.view).graph && !!leaf.view.contentEl.querySelector(".cm-line");
                arm.text_unchanged = leaf.view.editor.getValue() === text;
                // Wire: drag query's node onto db's (UR N.4), then planted.
                const wire = async (planted) => {
                  window.__domvecPlantNoWire = planted;
                  dbl(leaf.view); await sleep(400);
                  const gEl = leaf.view.contentEl.querySelector(".domvec-slate-graph");
                  const node = (k) => gEl && gEl.querySelector('circle[data-key="' + k + '"]');
                  node("query")?.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, cancelable: true, button: 0 }));
                  node("db")?.dispatchEvent(new MouseEvent("mouseup", { bubbles: true, cancelable: true, button: 0 }));
                  await sleep(400);
                  window.__domvecPlantNoWire = false;
                  const g2 = leaf.view.contentEl.querySelector(".domvec-slate-graph");
                  const res = { query_line: leaf.view.editor.getValue().split(NL).find((l) => l.trim().startsWith("query")),
                                links: g2 ? g2.querySelectorAll("line.domvec-slate-graph-link").length : null };
                  dbl(leaf.view); await sleep(300);                      // back to the panel
                  return res;
                };
                arm.wire_planted = await wire(true);
                arm.wire = await wire(false);
              }
              out[planted ? "planted" : "clean"] = arm;
              leaf.detach(); leaf = null;
            }
          } finally {
            c.plantNoGraphForm = false;
            try { leaf && leaf.detach(); } catch (e) {}
            try { window.localStorage.removeItem("domvec.slate.folds:" + f.path); } catch (e) {}
            try { await app.vault.delete(f); } catch (e) {}
          }
          return out;
        })()`, { timeout: 60000 });
        if (!got || got.error) return { pass: false, evidence: got };
        const c = got.clean, p = got.planted;
        return { pass: c.flipped.graph && c.flipped.nodes === got.fields && c.flipped.lines === got.fields - got.roots && c.flipped.hollow === 1
                   && c.kept && c.back && c.text_unchanged && !p.flipped.graph
                   && /\{db\}/.test(c.wire.query_line || "") && c.wire.links === 1
                   && !/\{db\}/.test(c.wire_planted.query_line || "") && c.wire_planted.links === 0,
                 evidence: got };
      },
    },
    {
      id: "G-282",
      asks: "readouts on the perimeter and the bisector (RESERVOIR_DESIGN §5, DM §6.6.4): a cell run with the real Run button puts its note -- the readout -- on the cloud's outer shell (1.05 x the 98th-percentile radius) along its own UMAP bearing, and ONE bisector node midway between its input and its readout, the signal drawn input -> bisector -> readout; a click on the bisector opens the cell in 2D graph form, a second closes it; a right-click on it folds what it dominates (its lines) and another unfolds (planted plantNoDominance: no fold); planted (plantNoPerimeter + plantNoBisector) the readout stays at its fit and no bisector is drawn",
      async run() {
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const until = async (ok, ms) => { for (let t = 0; t < ms && !ok(); t += 250) await sleep(250); return ok(); };
          const plugin = app.plugins.getPlugin("domvec-bridge");
          const SIDE = String(plugin.settings.sidecar).replace(/[/]+$/, "");
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0]?.view;
          if (!v || !v.graph) return { error: "no graph" };
          const NL = String.fromCharCode(10), F = String.fromCharCode(96).repeat(3);
          const folder = "domvec-checks";
          if (!app.vault.getAbstractFileByPath(folder)) await app.vault.createFolder(folder);
          const vaultName = app.vault.getName(), urlOf = (path) => "vault://" + vaultName + "/" + path;
          const made = [];
          const nodeOf = (path) => v.graph.graphData().nodes.find((n) => n.id === "page:" + urlOf(path));
          const runCell = async (tag) => {
            const stamp = Date.now() + tag;
            const srcName = "g282 source " + stamp;
            const src = await app.vault.create(folder + "/" + srcName + ".md", "# Source" + NL + NL + "Readout source " + stamp + "." + NL);
            made.push(src);
            await plugin.indexNote(src, "check");
            const varName = srcName.replace(/[^A-Za-z0-9_]+/g, "_").replace(/^_+|_+$/g, "").toLowerCase();
            const cellPath = folder + "/g282 cell " + stamp + ".md";
            const cell = await app.vault.create(cellPath, "# cell" + NL + NL + F + "python {" + srcName + "}" + NL + "print(len(" + varName + "))" + NL + F + NL);
            made.push(cell);
            const leaf = app.workspace.getLeaf("tab");
            await leaf.openFile(cell, { state: { mode: "source", source: false } });
            await until(() => !!leaf.view.containerEl.querySelector(".domvec-run-fence"), 8000);
            leaf.view.containerEl.querySelector(".domvec-run-fence").click();
            await until(() => leaf.view.editor.getValue().includes("nb-output"), 30000);
            leaf.detach();
            await until(() => !!nodeOf(cellPath) && !!nodeOf(src.path), 40000);
            await sleep(1500);                          // a few frames for the layout to apply
            v.batchDirty = true; v.batchSync(); await sleep(300);
            return { cellPath, src: src.path };
          };
          const out = {};
          try {
            // Planted first, on its own note.
            v.plantNoPerimeter = true; v.plantNoBisector = true;
            const pr = await runCell("p");
            const pt = nodeOf(pr.cellPath);
            out.planted = { at_fit: !!pt && Math.abs(pt.x - pt.fitX) + Math.abs(pt.y - pt.fitY) < 1, bisector: v.bisectors.has(pr.cellPath) };
            v.plantNoPerimeter = false; v.plantNoBisector = false;
            const cr = await runCell("c");
            v.batchDirty = true; v.batchSync(); await sleep(300);
            const t = nodeOf(cr.cellPath), s = nodeOf(cr.src);
            const sh = v.shell;
            const d = Math.hypot(t.x - sh.cx, t.y - sh.cy, (t.z || 0) - sh.cz);
            const b1 = [t.x - sh.cx, t.y - sh.cy, (t.z || 0) - sh.cz], b2 = [t.fitX - sh.cx, t.fitY - sh.cy, (t.fitZ || 0) - sh.cz];
            const cos = (b1[0]*b2[0] + b1[1]*b2[1] + b1[2]*b2[2]) / (Math.hypot(...b1) * Math.hypot(...b2));
            const b = v.bisectors.get(cr.cellPath);
            const mid = b ? Math.hypot(b.at.x - (s.x + t.x) / 2, b.at.y - (s.y + t.y) / 2, b.at.z - ((s.z || 0) + (t.z || 0)) / 2) : null;
            const es = v.drawableSignalEdges(v.graph.graphData().nodes);
            const clean = { shell_r: Math.round(sh.r), readout_r_ratio: Math.round(d / sh.r * 1000) / 1000, bearing_deg: Math.round(Math.acos(Math.min(1, cos)) * 1800 / Math.PI) / 10,
                            bisector: !!b, bisector_off_mid: mid === null ? null : Math.round(mid * 100) / 100,
                            src_to_bis: !!b && es.some((e) => e.source === s && e.target === b.at), bis_to_readout: !!b && es.some((e) => e.source === b.at && e.target === t) };
            // A real click on the bisector: aim at it, then pointerdown/up on the canvas at its screen point.
            if (b) {
              const g = v.graph, cam = g.camera(), ctl = g.controls();
              ctl.target.set(b.at.x, b.at.y, b.at.z);
              cam.position.set(b.at.x + 40, b.at.y + 10, b.at.z + 40); cam.lookAt(b.at.x, b.at.y, b.at.z); ctl.update?.(); cam.updateMatrixWorld();
              // Its screen point read afresh for each click: opening the cell in
              // a split resizes the 3D canvas and moves the bisector on screen.
              const pointOf = () => {
                const el = g.renderer().domElement, r = el.getBoundingClientRect();
                cam.updateMatrixWorld();
                const q = b.mesh.position.clone().project(cam);
                return [r.left + (q.x + 1) / 2 * r.width, r.top + (1 - q.y) / 2 * r.height];
              };
              const click = () => { const [x, y] = pointOf(); for (const type of ["pointerdown", "pointerup"]) v.canvasEl.dispatchEvent(new PointerEvent(type, { bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0 })); };
              clean.picked = v.bisectorAt(...pointOf());
              click(); await sleep(1500);
              const leaf = app.workspace.getLeavesOfType("markdown").find((l) => l.view?.file?.path === cr.cellPath);
              clean.opened = !!leaf;
              clean.graph_form = !!leaf && !!leaf.view.contentEl.querySelector(".domvec-slate-graph");
              click(); await sleep(600);
              clean.closed = !app.workspace.getLeavesOfType("markdown").some((l) => l.view?.file?.path === cr.cellPath);
              // Rank-dominance: a right-click on the bisector folds its lines; another unfolds.
              const lines = () => v.drawableSignalEdges(v.graph.graphData().nodes).filter((e) => e.source === b.at || e.target === b.at).length;
              const rclick = (planted) => { v.plantNoDominance = planted; const [x, y] = pointOf(); v.canvasEl.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: x, clientY: y, button: 2 })); v.plantNoDominance = false; };
              clean.lines_open = lines();
              rclick(true); clean.lines_planted_fold = lines();
              rclick(false); clean.lines_folded = lines();
              rclick(false); clean.lines_unfolded = lines();
            }
            out.clean = clean;
          } finally {
            v.plantNoPerimeter = false; v.plantNoBisector = false;
            for (const f of made) {
              try { await fetch(SIDE + "/purge", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ url: urlOf(f.path) }) }); } catch (e) {}
              try { await app.vault.delete(f); } catch (e) {}
            }
          }
          return out;
        })()`, { timeout: 180000 });
        if (!got || got.error) return { pass: false, evidence: got };
        const c = got.clean, p = got.planted;
        return { pass: c && Math.abs(c.readout_r_ratio - 1.05) < 0.02 && c.bearing_deg < 1 && c.bisector && c.bisector_off_mid < 0.5
                   && c.src_to_bis && c.bis_to_readout && c.picked && c.opened && c.graph_form && c.closed
                   && c.lines_open >= 2 && c.lines_planted_fold === c.lines_open && c.lines_folded === 0 && c.lines_unfolded === c.lines_open
                   && p.at_fit && !p.bisector,
                 evidence: got };
      },
    },
    {
      id: "G-283-rollout",
      asks: "the rollout (RESERVOIR_DESIGN §4): the ▶▶ play on a cell whose fence names a multi-chunk note by {ref} runs it once per sample -- one recorded run per chunk, each with that ONE chunk as its input, all chunks covered -- and the note keeps ONE readout block; ▶▶ again pauses it part-way; planted (__domvecPlantNoRollout) one run, no samples",
      async run() {
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const until = async (ok, ms) => { for (let t = 0; t < ms && !ok(); t += 250) await sleep(250); return ok(); };
          const plugin = app.plugins.getPlugin("domvec-bridge");
          const SIDE = String(plugin.settings.sidecar).replace(/[/]+$/, "");
          const NL = String.fromCharCode(10), F = String.fromCharCode(96).repeat(3);
          const folder = "domvec-checks";
          if (!app.vault.getAbstractFileByPath(folder)) await app.vault.createFolder(folder);
          const vaultName = app.vault.getName(), urlOf = (path) => "vault://" + vaultName + "/" + path;
          const stamp = Date.now();
          const srcName = "g283 samples " + stamp;
          // Each section well past the chunker's 256-token merge limit, so
          // each is its own chunk (short sections merge into one).
          const words = (topic) => Array.from({ length: 320 }, (_, i) => topic + i).join(" ");
          const body = ["# Samples " + stamp, "", "## One", "", words("radix"), "", "## Two", "", words("trie"), "", "## Three", "", words("patricia"), ""].join(NL);
          const src = await app.vault.create(folder + "/" + srcName + ".md", body);
          const made = [src];
          await plugin.indexNote(src, "check");
          const ref = await (await fetch(SIDE + "/ref?name=" + encodeURIComponent(srcName))).json();
          const varName = srcName.replace(/[^A-Za-z0-9_]+/g, "_").replace(/^_+|_+$/g, "").toLowerCase();
          const out = { chunks: (ref.cids || []).length };
          const mkCell = async (tag) => {
            const path = folder + "/g283 roll " + tag + " " + stamp + ".md";
            const f = await app.vault.create(path, "# roll" + NL + NL + F + "python {" + srcName + "}" + NL + "print(len(" + varName + "))" + NL + F + NL);
            made.push(f);
            const leaf = app.workspace.getLeaf("tab");
            await leaf.openFile(f, { state: { mode: "source", source: false } });
            await until(() => !!leaf.view.containerEl.querySelector(".domvec-play-fence"), 8000);
            return { f, leaf, path };
          };
          const runsOf = async (path) => (await (await fetch(SIDE + "/runs?note=" + encodeURIComponent(path))).json()).runs || [];
          try {
            // Clean: a whole rollout.
            const c = await mkCell("c");
            const f0 = plugin.rolloutStats.finished;
            c.leaf.view.containerEl.querySelector(".domvec-play-fence").click();
            await until(() => plugin.rolloutStats.finished > f0, 60000);
            const runs = await runsOf(c.path);
            out.clean = { runs: runs.length, one_input_each: runs.every((r) => r.inputs.length === 1),
                          distinct_inputs: new Set(runs.map((r) => r.inputs[0] && r.inputs[0].cid)).size,
                          readout_blocks: (c.leaf.view.editor.getValue().match(/<!-- nb-output /g) || []).length };
            c.leaf.detach();
            // Pause: play, then play again after the first sample.
            const pz = await mkCell("p");
            const s0 = plugin.rolloutStats.samples;
            pz.leaf.view.containerEl.querySelector(".domvec-play-fence").click();
            await until(() => plugin.rolloutStats.samples > s0, 30000);
            pz.leaf.view.containerEl.querySelector(".domvec-play-fence").click();
            await sleep(3000);
            out.paused_runs = (await runsOf(pz.path)).length;
            pz.leaf.detach();
            // Planted: one run.
            window.__domvecPlantNoRollout = true;
            const pl = await mkCell("x");
            pl.leaf.view.containerEl.querySelector(".domvec-play-fence").click();
            await until(() => pl.leaf.view.editor.getValue().includes("nb-output"), 30000);
            await sleep(1500);
            out.planted_runs = (await runsOf(pl.path)).length;
            out.planted_inputs = ((await runsOf(pl.path))[0] || { inputs: [] }).inputs.length;
            pl.leaf.detach();
          } finally {
            window.__domvecPlantNoRollout = false;
            for (const f of made) {
              try { await fetch(SIDE + "/purge", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ url: urlOf(f.path) }) }); } catch (e) {}
              try { await app.vault.delete(f); } catch (e) {}
            }
          }
          return out;
        })()`, { timeout: 180000 });
        if (!got || got.error) return { pass: false, evidence: got };
        const c = got.clean;
        return { pass: got.chunks >= 2 && c.runs === got.chunks && c.one_input_each && c.distinct_inputs === got.chunks
                   && c.readout_blocks === 1 && got.paused_runs >= 1 && got.paused_runs < got.chunks
                   && got.planted_runs === 1 && got.planted_inputs === got.chunks,
                 evidence: got };
      },
    },
    {
      id: "G-284",
      asks: "the halo's cone transport (UR O.18, O.3): the cursor on a stuck slate's literal-text field fires a halo -- its retrieved nodes transported onto the camera's cone (every node at the cone's half-angle from the axis, the more similar nearer the apex); orbiting the camera 25 deg, they slide and stay on the new cone; each node's similarity is the three-part score pagerank x max(minmax(nomic), minmax(tfidf)) (O.22; planted plantHaloSearchOrder: the retrieval's ranks instead); a double right-click on a halo node sends it home and transports in the next from the queue (O.14; planted plantNoHaloQueue: the halo shrinks); the cursor on a pure {ref} field ends it and every node is home again; planted (plantNoHaloTransport) nothing moves",
      async run() {
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const until = async (ok, ms) => { for (let t = 0; t < ms && !ok(); t += 250) await sleep(250); return ok(); };
          const plugin = app.plugins.getPlugin("domvec-bridge");
          const SIDE = String(plugin.settings.sidecar).replace(/[/]+$/, "");
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0]?.view;
          if (!v || !v.graph) return { error: "no graph" };
          const g = v.graph, cam = g.camera(), ctl = g.controls();
          const saved = { p: cam.position.clone(), t: ctl.target.clone() };
          const NL = String.fromCharCode(10), TB = String.fromCharCode(9);
          const folder = "domvec-checks";
          if (!app.vault.getAbstractFileByPath(folder)) await app.vault.createFolder(folder);
          const f = await app.vault.create(folder + "/g284 halo " + Date.now() + ".md", "---" + NL + "domvec: slate" + NL + "---" + NL + "halo probe" + NL + TB + "topic" + TB + "radix tree compression" + NL + TB + "source" + TB + "{somewhere}" + NL);
          const leaf = app.workspace.getLeaf("tab");
          await leaf.openFile(f, { state: { mode: "source", source: false } });
          app.workspace.setActiveLeaf(leaf, { focus: true });
          await sleep(600);
          const ed = leaf.view.editor;
          const lineOf = (k) => ed.getValue().split(NL).findIndex((l) => l.trim().startsWith(k));
          const onCone = () => {
            cam.updateMatrixWorld();
            const e = cam.matrixWorld.elements, P = cam.position;
            const fwd = [-e[8], -e[9], -e[10]];
            const apex = [P.x + fwd[0] * v.haloApex, P.y + fwd[1] * v.haloApex, P.z + fwd[2] * v.haloApex];
            return (v.halo ? v.halo.items : []).map((it) => {
              const d = [it.n.x - apex[0], it.n.y - apex[1], it.n.z - apex[2]];
              const along = d[0] * fwd[0] + d[1] * fwd[1] + d[2] * fwd[2], len = Math.hypot(...d);
              return { s: it.s, along, ang: Math.acos(Math.min(1, along / len)) * 180 / Math.PI, at: [it.n.x, it.n.y, it.n.z], home: it.home.slice(0, 3) };
            });
          };
          const out = { half_angle_deg: Math.round(v.haloHalfAngle * 1800 / Math.PI) / 10 };
          try {
            // Planted first.
            v.plantNoHaloTransport = true;
            ed.setCursor({ line: lineOf("topic"), ch: 3 }); await sleep(2500);
            out.planted = { halo: !!v.halo };
            ed.setCursor({ line: lineOf("source"), ch: 3 }); await sleep(800);
            v.plantNoHaloTransport = false;
            // Clean.
            ed.setCursor({ line: lineOf("topic"), ch: 3 });
            await until(() => !!v.halo && v.halo.items.length >= 3, 15000);
            await sleep(1500);
            const a = onCone();
            out.nodes = a.length;
            out.max_angle_err = a.length ? Math.round(Math.max(...a.map((x) => Math.abs(x.ang - out.half_angle_deg))) * 100) / 100 : null;
            const bySim = a.slice().sort((x, y) => y.s - x.s);
            out.nearer_when_similar = bySim.every((x, i) => i === 0 || x.along >= bySim[i - 1].along - 1e-6);
            out.moved_from_home = a.length ? Math.round(Math.min(...a.map((x) => Math.hypot(x.at[0] - x.home[0], x.at[1] - x.home[1], x.at[2] - x.home[2])))) : null;
            // Orbit the camera 25 deg about its target: the cone moves, the halo slides.
            const t = ctl.target, ang = 25 * Math.PI / 180;
            const rx = cam.position.x - t.x, rz = cam.position.z - t.z;
            cam.position.set(t.x + rx * Math.cos(ang) - rz * Math.sin(ang), cam.position.y, t.z + rx * Math.sin(ang) + rz * Math.cos(ang));
            cam.lookAt(t); ctl.update?.();
            await sleep(2500);
            const b = onCone();
            out.slid = a.length && b.length ? Math.round(Math.min(...b.map((x, i) => Math.hypot(x.at[0] - a[i].at[0], x.at[1] - a[i].at[1], x.at[2] - a[i].at[2])))) : null;
            out.max_angle_err_after = b.length ? Math.round(Math.max(...b.map((x) => Math.abs(x.ang - out.half_angle_deg))) * 100) / 100 : null;
            // The three-part similarity (O.22): each node's s is the app's own
            // haloScores over the same hits.
            // The very hits the halo scored (a second ask of /search can answer differently).
            const hits = v.halo.hits || [];
            const sc = v.constructor.haloScores(hits);
            const want = new Map();
            const ns2 = v.graph.graphData().nodes, byId = new Map(ns2.map((n) => [String(n.id), n]));
            hits.forEach((h, i) => { const n = byId.get(String(h.cid)) || byId.get("page:" + h.url); if (n && !want.has(n)) want.set(n, sc[i]); });
            out.score_err = Math.max(0, ...v.halo.items.map((it) => Math.abs((want.get(it.n) ?? -9) - it.s)));
            out.queued = v.halo.queue.length;
            // Delete the top node by a double right-click at its screen point.
            const drop = async (planted) => {
              v.plantNoHaloQueue = planted;
              const top = v.halo.items.slice().sort((x, y) => y.s - x.s)[0];
              const home = top.home.slice(0, 3), n0 = v.halo.items.length, q0 = v.halo.queue.length;
              cam.updateMatrixWorld();
              const el = g.renderer().domElement, r = el.getBoundingClientRect();
              const q = cam.position.clone().set(top.n.x, top.n.y, top.n.z || 0).project(cam);
              const x = r.left + (q.x + 1) / 2 * r.width, y = r.top + (1 - q.y) / 2 * r.height;
              for (let k = 0; k < 2; k++) v.canvasEl.dispatchEvent(new MouseEvent("contextmenu", { bubbles: true, cancelable: true, clientX: x, clientY: y, button: 2 }));
              await sleep(300);
              const res = { home_err: Math.hypot(top.n.x - home[0], top.n.y - home[1], (top.n.z || 0) - home[2]), in_halo: v.halo.items.some((it) => it.n === top.n),
                            items_delta: v.halo.items.length - n0, queue_delta: v.halo.queue.length - q0 };
              v.plantNoHaloQueue = false;
              return res;
            };
            out.drop = await drop(false);
            out.drop_planted = await drop(true);
            // Planted order: the retrieval's own ranks as similarity.
            v.haloEnd(); v.plantHaloSearchOrder = true;
            await v.haloFor("radix tree compression ");
            // The planted halo's own hits, scored the three-part way, against its ranks.
            const ph = v.halo.hits || [], psc = v.constructor.haloScores(ph), pwant = new Map();
            ph.forEach((h, i) => { const n = byId.get(String(h.cid)) || byId.get("page:" + h.url); if (n && !pwant.has(n)) pwant.set(n, psc[i]); });
            out.planted_score_err = Math.max(0, ...v.halo.items.map((it) => Math.abs((pwant.get(it.n) ?? -9) - it.s)));
            v.plantHaloSearchOrder = false; v.haloEnd();
            await v.haloFor("radix tree compression"); await sleep(400);
            // A pure {ref} field: no halo, every node home.
            const items = v.halo ? v.halo.items.map((it) => ({ n: it.n, home: it.home.slice(0, 3) })) : [];
            ed.setCursor({ line: lineOf("source"), ch: 3 }); await sleep(1200);
            out.ended = !v.halo;
            out.home_err = items.length ? Math.max(...items.map((it) => Math.hypot(it.n.x - it.home[0], it.n.y - it.home[1], (it.n.z || 0) - it.home[2]))) : null;
          } finally {
            v.plantNoHaloTransport = false; v.plantNoHaloQueue = false; v.plantHaloSearchOrder = false; v.haloEnd();
            cam.position.copy(saved.p); ctl.target.copy(saved.t); ctl.update?.();
            try { leaf.detach(); } catch (e) {}
            // The note was indexed as a reservoir node (G-291): out of the store too.
            try { await fetch(SIDE + "/purge", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ url: "vault://" + app.vault.getName() + "/" + f.path }) }); } catch (e) {}
            try { await app.vault.delete(f); } catch (e) {}
          }
          return out;
        })()`, { timeout: 90000 });
        if (!got || got.error) return { pass: false, evidence: got };
        return { pass: got.nodes >= 3 && got.max_angle_err < 0.5 && got.nearer_when_similar && got.moved_from_home > 1
                   && got.slid > 1 && got.max_angle_err_after < 0.5 && got.ended && got.home_err < 1e-3 && !got.planted.halo
                   && got.score_err < 1e-9 && got.planted_score_err > 1e-3
                   && got.drop.home_err < 1e-3 && !got.drop.in_halo && got.drop.items_delta === 0 && got.drop.queue_delta === -1
                   && got.drop_planted.items_delta === -1,
                 evidence: got };
      },
    },
    {
      id: "M-10",
      asks: "full structural preservation along content links in nested shadow DOM: on archive.org's search page (results inside shadow roots nested 3+ deep), every link the composed tree holds at shadow depth >= 2 is in the trie (by its href), and at its EXACT depth -- its address crosses as many #shadow-root boundaries as the link does; read from the page in the browser cell (read-only) and from the store the running sidecar wrote; planted: a trie view with one shadow step stripped fails the depth arm, one with the deep links dropped fails recall",
      async run() {
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const plugin = app.plugins.getPlugin("domvec-bridge");
          const SIDE = String(plugin.settings.sidecar).replace(/[/]+$/, "");
          const b = app.workspace.getLeavesOfType("domvec-browser-view")[0]?.view;
          if (!b || !b.webview) return { error: "no browser cell" };
          const was = String(b.webview.getURL());
          const url = "https://archive.org/search?query=radio+drama&m10=" + Date.now();
          const cy = async (q) => { const r = await fetch(SIDE + "/cypher", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ query: q }) }); return (await r.json()).rows || []; };
          let landed = url;
          try {
            b.go(url);
            await sleep(45000);
            landed = String(b.webview.getURL());
            // The page's own composed tree, read only: every <a href> and how
            // many shadow roots stand between it and the document.
            // The FLATTENED composed tree, the sensor's own model: a host's
            // shadow root stands in for its children, and a slot for the light
            // children assigned to it (at the slot's depth); light children
            // assigned to no slot are not rendered.
            const truth = await b.webview.executeJavaScript("(function(){var out=[],closed=0;" +
              "function one(e,d){if(e.tagName==='A'&&e.getAttribute('href'))out.push({href:e.getAttribute('href'),d:d,text:(e.textContent||'').trim().slice(0,40)});" +
              "if(e.shadowRoot)walk(e.shadowRoot,d+1);else{if(e.tagName&&e.tagName.indexOf('-')>0)closed++;walk(e,d);}}" +
              "function walk(n,d){var kids=n.children||[];for(var i=0;i<kids.length;i++){var e=kids[i];" +
              "if(e.tagName==='SLOT'){var as=e.assignedElements?e.assignedElements({flatten:true}):[];if(as.length){for(var j=0;j<as.length;j++)one(as[j],d);}else walk(e,d);}else one(e,d);}}" +
              "walk(document,0);return {links:out,custom_without_open_root:closed};})()");
            // Let the capture settle: the page's link addresses stop growing.
            // Settled: the count has grown past a first trickle and then held
            // for two reads in a row (a capture lands over tens of seconds).
            let addrs = [], prev = -1, held = 0;
            for (let i = 0; i < 30; i++) {
              // A link's href is in the drawn value: every [label](href) in it --
              // an inline link sits mid-sentence on its paragraph's text unit --
              // and a control's own href drawn ( href ) (a role=tab anchor).
              addrs = [];
              for (const [v, xp, acc] of await cy("MATCH (a:Address) WHERE a.url = '" + landed.replace(/'/g, "") + "' AND (a.tag IN ['link', 'text', 'button'] OR a.accessor STARTS WITH 'href') RETURN a.value, a.xpath, a.accessor")) {
                const s = String(v);
                const re = /\\]\\(([^)\\s]+)/g; let m;
                while ((m = re.exec(s))) addrs.push([m[1], xp]);
                if (String(acc).startsWith("href")) addrs.push([s.replace(/^\\(\\s*/, "").replace(/\\s*\\)$/, ""), xp]);
              }
              held = addrs.length === prev && addrs.length > 20 ? held + 1 : 0;
              if (held >= 3) break;
              prev = addrs.length; await sleep(5000);
            }
            // A link's address is often its label's text node, deeper inside
            // the anchor (even inside further shadow roots): its depth is
            // counted up to the anchor's own step.
            const steps = (xp) => { const x = String(xp); let cut = x.length; const re = /\\/a(\\[\\d+\\])?(?=\\/|$)/g; let m; while ((m = re.exec(x))) cut = m.index + m[0].length; return (x.slice(0, cut).match(/#shadow-root/g) || []).length; };
            const deep = truth.links.filter((l) => l.d >= 2);
            const score = (view) => {
              const byHref = new Map();
              for (const [v, xp] of view) { const k = String(v); if (!byHref.has(k)) byHref.set(k, []); byHref.get(k).push(steps(xp)); }
              let any = 0, exact = 0; const missing = [];
              for (const l of deep) {
                const ds = byHref.get(l.href);
                if (ds) { any++; if (ds.includes(l.d)) exact++; } else if (missing.length < 5) missing.push(l);
              }
              return { any, exact, missing };
            };
            const clean = score(addrs);
            const strip = score(addrs.map(([v, xp]) => [v, String(xp).replace("/#shadow-root", "")]));
            const dropped = score(addrs.filter(([v, xp]) => steps(xp) < 2));
            return { url: landed, links_total: truth.links.length, deep: deep.length, max_depth: Math.max(0, ...truth.links.map((l) => l.d)),
                     custom_without_open_root: truth.custom_without_open_root, trie_link_addresses: addrs.length,
                     clean, planted_strip: { any: strip.any, exact: strip.exact }, planted_drop: { any: dropped.any, exact: dropped.exact } };
          } finally {
            try { await fetch(SIDE + "/purge", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ url: landed }) }); } catch (e) {}
            b.go(was);
          }
        })()`, { timeout: 300000 });
        if (!got || got.error) return { pass: false, evidence: got };
        const c = got.clean;
        return { pass: got.deep >= 20 && c.any === got.deep && c.exact === got.deep
                   && got.planted_strip.exact < got.deep * 0.5 && got.planted_drop.any < got.deep * 0.5,
                 evidence: got };
      },
    },
    {
      id: "G-273",
      asks: "the user agent's views and keys: in MAP view a hover moves nothing and in EGO view it moves the camera; paused, no motion; Shift +5%, Ctrl -5%; Z, X and M do nothing (deprecated); arrows turn the camera about the focus (distance kept) and Q/R roll it about the view normal (view kept) -- 3-DOF rotation; each key held lit in the agent's state while pressed (its readout awaits the dialect card, G-274); planted (pointer away) the keys do nothing",
      async run() {
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0]?.view;
          if (!v || !v.graph || !v.agent) return { error: "no graph or agent" };
          const g = v.graph, cam = g.camera(), ctl = g.controls(), a = v.agent;
          const saved = { p: cam.position.clone(), t: ctl.target.clone(), up: cam.up.clone(), mode: a.mode, thr: a.throttle, over: v.pointerOver };
          const key = (k) => window.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true, cancelable: true }));
          const moved = () => Math.hypot(cam.position.x - saved.p.x, cam.position.y - saved.p.y, cam.position.z - saved.p.z);
          const reset = () => { cam.position.copy(saved.p); ctl.target.copy(saved.t); cam.up.copy(saved.up); ctl.update?.(); a.vel = { x: 0, y: 0, z: 0 }; a.target = null; };
          const n = g.graphData().nodes.filter((x) => Number.isFinite(x.x) && x.level !== "path")
            .sort((x, y) => Math.hypot(cam.position.x - y.x, cam.position.y - y.y) - Math.hypot(cam.position.x - x.x, cam.position.y - x.y))[0];
          const out = {};
          try {
            v.pointerOver = true;
            a.mode = "map"; a.draw(); a.setThrottle(0.5); reset();
            v.focusNode = null; v.focusPending = null; v.focusOn(n); await sleep(1500);
            out.map_moved = Math.round(moved() * 10) / 10;
            a.setMode("ego"); out.after_m = a.mode; reset();
            v.focusNode = null; v.focusPending = null; v.focusOn(n); await sleep(1500);
            out.ego_moved = Math.round(moved() * 10) / 10;
            const t0 = a.throttle; key("Shift"); out.shift = Math.round((a.throttle - t0) * 100);
            const t1 = a.throttle; key("Control"); out.ctrl = Math.round((a.throttle - t1) * 100);
            a.paused = true; out.paused = a.paused; reset(); a.target = n;
            await sleep(1000); out.paused_moved = Math.round(moved() * 10) / 10;
            a.paused = false; a.target = null;
            const tz = a.throttle; key("z"); key("x"); key("m"); out.zxm_ignored = a.throttle === tz && !a.paused && a.mode === "ego";
            // Rotation, from rest: arrows turn about the focus, Q/R roll.
            reset();
            const rel = () => ({ x: cam.position.x - ctl.target.x, y: cam.position.y - ctl.target.y, z: cam.position.z - ctl.target.z });
            const ang = (u, w) => { const d = (u.x*w.x + u.y*w.y + u.z*w.z) / (Math.hypot(u.x,u.y,u.z) * Math.hypot(w.x,w.y,w.z)); return Math.acos(Math.max(-1, Math.min(1, d))) * 180 / Math.PI; };
            const r0 = rel();
            for (let i = 0; i < 5; i++) key("ArrowLeft");
            const r1 = rel();
            out.yaw_deg = Math.round(ang(r0, r1) * 10) / 10;
            out.yaw_dist_kept = Math.abs(Math.hypot(r0.x, r0.y, r0.z) - Math.hypot(r1.x, r1.y, r1.z)) < 1e-3 * Math.hypot(r0.x, r0.y, r0.z);
            reset();
            const up0 = cam.up.clone(); cam.updateMatrixWorld(); const e0 = cam.matrixWorld.elements.slice(8, 11);
            for (let i = 0; i < 5; i++) key("q");
            cam.updateMatrixWorld(); const e1 = cam.matrixWorld.elements.slice(8, 11);
            out.roll_deg = Math.round(ang(up0, cam.up) * 10) / 10;
            out.roll_view_deg = Math.round(ang({ x: e0[0], y: e0[1], z: e0[2] }, { x: e1[0], y: e1[1], z: e1[2] }) * 10) / 10;
            // FRAME-respective (item 23): after the roll, a yaw turns about the
            // camera's CURRENT up -- the offset's component along it is kept --
            // and A moves along the camera's current left.
            cam.updateMatrixWorld();
            const m = cam.matrixWorld.elements, upC = { x: m[4], y: m[5], z: m[6] }, rightC = { x: m[0], y: m[1], z: m[2] };
            const dot = (u, w) => u.x*w.x + u.y*w.y + u.z*w.z;
            const ra = rel(); for (let i = 0; i < 5; i++) key("ArrowLeft"); const rb = rel();
            out.yaw_after_roll_deg = Math.round(ang(ra, rb) * 10) / 10;
            out.yaw_keeps_camera_up = Math.abs(dot(ra, upC) - dot(rb, upC)) < 1e-3 * Math.hypot(ra.x, ra.y, ra.z);
            cam.updateMatrixWorld();
            const m2 = cam.matrixWorld.elements, rightNow = { x: m2[0], y: m2[1], z: m2[2] };
            const pa = cam.position.clone(); key("a");
            const mv = { x: cam.position.x - pa.x, y: cam.position.y - pa.y, z: cam.position.z - pa.z };
            out.strafe_vs_camera_left_deg = Math.round(ang(mv, { x: -rightNow.x, y: -rightNow.y, z: -rightNow.z }) * 10) / 10;
            // Each key lit while pressed, and named.
            reset();
            key("w"); out.lit_held = a.litKeys().includes("w");
            window.dispatchEvent(new KeyboardEvent("keyup", { key: "w", bubbles: true })); await sleep(500);
            out.lit_after = a.litKeys().includes("w");
            v.pointerOver = false; const t2 = a.throttle; key("Control"); out.away_ctrl = Math.round((a.throttle - t2) * 100);
          } finally {
            v.pointerOver = saved.over; a.target = null; v.focusNode = null; a.paused = false;
            a.setThrottle(saved.thr); a.mode = saved.mode; a.draw(); reset(); cam.up.copy(saved.up); a.vel = { x: 0, y: 0, z: 0 };
          }
          return out;
        })()`, { timeout: 60000 });
        if (!got || got.error) return { pass: false, evidence: got };
        return { pass: got.map_moved < 0.5 && got.after_m === "ego" && got.ego_moved > 0.5 && got.shift === 5 && got.ctrl === -5
                   && got.paused === true && got.paused_moved < 0.5 && got.zxm_ignored
                   && got.yaw_deg > 3 && got.yaw_dist_kept && got.roll_deg > 3 && got.roll_view_deg < 0.5
                   && got.yaw_after_roll_deg > 3 && got.yaw_keeps_camera_up && got.strafe_vs_camera_left_deg < 2
                   && got.lit_held && !got.lit_after && got.away_ctrl === 0,
                 evidence: got };
      },
    },
    {
      id: "D-52",
      asks: "hovering a node with no image never makes it disappear: with the pointer on a picture-less node that stands in front of a picture node, the hovered node keeps its default look (not the 0.12 front-dim) -- the pane's own refreshDetail, aimed at it; planted (plantDimByRay, the old dim) it is dimmed",
      async run() {
        const got = await evaluate(`(async () => {
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0]?.view;
          if (!v || !v.graph) return { error: "no graph" };
          const g = v.graph, cam = g.camera();
          cam.updateMatrixWorld();
          const THREE = window.__domvecRaycaster ? null : null;
          const ns = g.graphData().nodes.filter((n) => Number.isFinite(n.x) && n.level !== "page" && n.level !== "path");
          const proj = (n) => { const p = cam.position.clone ? null : null; return null; };
          // NDC and view depth of a node through the camera's own matrices.
          const e = cam.matrixWorldInverse.elements, pe = cam.projectionMatrix.elements;
          const ndc = (n) => {
            const x = n.x, y = n.y, z = n.z || 0;
            const vx = e[0]*x + e[4]*y + e[8]*z + e[12], vy = e[1]*x + e[5]*y + e[9]*z + e[13], vz = e[2]*x + e[6]*y + e[10]*z + e[14];
            const cx = pe[0]*vx + pe[4]*vy + pe[8]*vz + pe[12], cy = pe[1]*vx + pe[5]*vy + pe[9]*vz + pe[13], cw = pe[3]*vx + pe[7]*vy + pe[11]*vz + pe[15];
            return cw > 0 ? [cx / cw, cy / cw, -vz] : null;
          };
          const pics = ns.filter((n) => n.image && n.image.src);
          const plain = ns.filter((n) => !(n.image && n.image.src));
          if (!pics.length || !plain.length) return { error: "no picture and plain nodes", pics: pics.length, plain: plain.length };
          // Built, not searched for: the camera on the line from a picture P
          // through its nearest plain node F, beyond F -- F stands in front of P.
          const P = pics[0];
          let F = plain[0], best = Infinity;
          for (const n of plain) { const d = Math.hypot(n.x - P.x, n.y - P.y, (n.z || 0) - (P.z || 0)); if (d > 1 && d < best) { best = d; F = n; } }
          const ux = (F.x - P.x) / best, uy = (F.y - P.y) / best, uz = ((F.z || 0) - (P.z || 0)) / best;
          const savedCam = { p: cam.position.clone(), t: g.controls().target.clone() };
          cam.position.set(F.x + ux * 60, F.y + uy * 60, (F.z || 0) + uz * 60);
          g.controls().target.set(P.x, P.y, P.z || 0); cam.lookAt(P.x, P.y, P.z || 0); cam.updateMatrixWorld();
          const qF = ndc(F);
          if (!qF) { cam.position.copy(savedCam.p); g.controls().target.copy(savedCam.t); return { error: "F behind the camera" }; }
          const pair = { P, F, qF };
          const aim = async (planted) => {
            v.plantDimByRay = planted;
            v.pointerNdc = [pair.qF[0], pair.qF[1]];
            v.detailDirty = true; v.detailAt = 0;
            v.refreshDetail(g);
            const look = v.lookOf(pair.F, g.nodeRelSize(), v.drawnMedia);
            return { dimmed: v.dimFront.has(pair.F), alpha: Math.round((look.alpha ?? 1) * 100) / 100, dim_count: v.dimFront.size };
          };
          let clean, planted;
          try { clean = await aim(false); planted = await aim(true); }
          finally { v.plantDimByRay = false; v.detailDirty = true; cam.position.copy(savedCam.p); g.controls().target.copy(savedCam.t); g.controls().update?.(); }
          return { F: String(pair.F.id).slice(0, 12), P: String(pair.P.id).slice(0, 12), clean, planted };
        })()`, { timeout: 60000 });
        if (!got || got.error) return { pass: false, evidence: got };
        return { pass: !got.clean.dimmed && got.clean.alpha > 0.12 && got.planted.dimmed, evidence: got };
      },
    },
    {
      id: "G-270",
      asks: "one content, one drawn chunk, store-wide: the store reports no content drawn twice, and the same text indexed under two pages adds COPIES, not drawn duplicates; the projector holds nothing the store calls a copy; planted (/plant page-scoped-dedup) the second page's text is drawn again",
      async run() {
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const plugin = app.plugins.getPlugin("domvec-bridge");
          const SIDE = String(plugin.settings.sidecar).replace(/[/]+$/, "");
          const NL = String.fromCharCode(10);
          const dup = async () => (await fetch(SIDE + "/duplicates")).json();
          const plant = (on) => fetch(SIDE + "/plant", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ name: "page-scoped-dedup", on }) });
          const purge = (url) => fetch(SIDE + "/purge", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ url }) });
          const before = await dup();
          const proj = await (await fetch(SIDE + "/projector?drawable=1")).json();
          const arm = async (planted) => {
            const stamp = Date.now();
            const text = "# Shared notes " + stamp + NL + NL + "A paragraph that two notes both hold, word for word, " + stamp + "." + NL + NL + "A second shared paragraph about tries and radix trees " + stamp + "." + NL;
            const urls = [];
            await plant(planted);
            try {
              const r0 = await dup();
              for (const name of ["one", "two"]) {
                const got = await plugin.sidecar.note("domvec-checks/g270-" + name + "-" + stamp + ".md", text, app.vault.getName());
                if (got && got.url) urls.push(got.url);
              }
              const r1 = await dup();
              return { planted, notes: urls.length, copies_added: r1.copies - r0.copies, extra_drawn_added: r1.extra_drawn_plain - r0.extra_drawn_plain };
            } finally {
              await plant(false);
              for (const u of urls) await purge(u);
            }
          };
          const clean = await arm(false);
          const planted = await arm(true);
          return { before,
                   projected_not_drawable: proj.projected_not_drawable, drawable_unprojected: proj.drawable_unprojected, clean, planted };
        })()`, { timeout: 300000 });
        if (!got || got.error || !got.clean) return { pass: false, evidence: got };
        return { pass: got.before.extra_drawn_plain === 0 && got.projected_not_drawable === 0
                   && got.clean.notes === 2 && got.clean.copies_added > 0 && got.clean.extra_drawn_added === 0
                   && got.planted.notes === 2 && got.planted.extra_drawn_added > 0,
                 evidence: got };
      },
    },
    {
      id: "P-N3",
      asks: "a code block opens a terminal or the kernel, or both at once: each runnable fence carries '▶ run' and '⌨ terminal' in live preview and reading view; '⌨ terminal' on a PowerShell cell opens a NEW terminal pane where the cell's command ran and printed; '▶ run' on a Python cell stores its output in place WHILE that terminal pane is open (both at once: two panes); planted (__domvecPlantNoTermFence) no terminal button",
      async run() {
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const until = async (ok, ms) => { for (let t = 0; t < ms && !ok(); t += 250) await sleep(250); return ok(); };
          const NL = String.fromCharCode(10), F = String.fromCharCode(96).repeat(3);
          const folder = "domvec-checks";
          if (!app.vault.getAbstractFileByPath(folder)) await app.vault.createFolder(folder);
          const terms = () => app.workspace.getLeavesOfType("domvec-terminal-view");
          const arm = async (planted) => {
            window.__domvecPlantNoTermFence = planted;
            const mark = "dvpn3" + Date.now();
            const path = folder + "/pn3-" + (planted ? "p" : "c") + Date.now() + ".md";
            const text = ["# cells", "", F + "powershell", "Write-Output " + mark, F, "", F + "python", "print(" + "6*7" + ")", F, ""].join(NL);
            const f = await app.vault.create(path, text);
            const leaf = app.workspace.getLeaf("tab");
            const t0 = terms().length;
            const out = { planted };
            try {
              await leaf.openFile(f, { state: { mode: "source", source: false } });
              const view = leaf.view;
              await until(() => view.containerEl.querySelectorAll(".domvec-run-fence").length >= 2, 8000);
              out.run_buttons = view.containerEl.querySelectorAll(".domvec-run-fence").length;
              out.term_buttons = view.containerEl.querySelectorAll(".domvec-term-fence").length;
              if (!planted) {
                view.containerEl.querySelectorAll(".domvec-term-fence")[0].click();
                const printed = () => terms().some((l) => (l.view.logText?.() || "").split(NL).some((x) => x.trim() === mark));
                await until(printed, 20000);
                out.terminal_pane = terms().length > t0;
                out.terminal_printed = printed();
                if (!out.terminal_printed) out.terminal_logs = terms().map((l) => (l.view.logText?.() || "").slice(-200));
                // Both at once: the kernel runs the python cell in place while the terminal pane stays open.
                view.containerEl.querySelectorAll(".domvec-run-fence")[1].click();
                let stored = false;
                for (let t = 0; t < 20000 && !stored; t += 500) { await sleep(500); stored = view.editor.getValue().includes("nb-output") && view.editor.getValue().includes("42"); }
                out.kernel_output_in_place = stored;
                out.both_open = stored && terms().length > t0;
                await leaf.setViewState({ type: "markdown", state: { file: path, mode: "preview" } });
                await until(() => leaf.view.containerEl.querySelectorAll(".markdown-reading-view .domvec-term-fence").length >= 2, 8000);
                out.reading_term_buttons = leaf.view.containerEl.querySelectorAll(".markdown-reading-view .domvec-term-fence").length;
              }
            } finally {
              window.__domvecPlantNoTermFence = false;
              for (const t of terms().slice(t0)) { try { t.detach(); } catch (e) {} }
              try { leaf.detach(); } catch (e) {}
              try { await app.vault.delete(f); } catch (e) {}
            }
            return out;
          };
          try {
            return { clean: await arm(false), planted: await arm(true) };
          } finally {
            try {
              await sleep(1500);
              const fo = app.vault.getAbstractFileByPath(folder);
              if (fo && (!fo.children || !fo.children.length)) await app.vault.delete(fo, true);
            } catch (e) {}
          }
        })()`, { timeout: 180000 });
        if (!got || got.error || !got.clean || !got.planted) return { pass: false, evidence: got };
        const c = got.clean, p = got.planted;
        return { pass: c.run_buttons >= 2 && c.term_buttons >= 2 && c.terminal_pane && c.terminal_printed
                   && c.kernel_output_in_place && c.both_open && c.reading_term_buttons >= 2
                   && p.run_buttons >= 2 && p.term_buttons === 0,
                 evidence: got };
      },
    },
    {
      id: "P-M4",
      asks: "the buttons that add new structural cells sit at the very bottom of the NATIVE markdown (P-M1: the view is still Obsidian's own 'markdown'), in live preview and reading view: '+ code' appends a python cell with the cursor inside, and that cell typed and run at once stores its output in the note while the reader keeps typing (written into the open editor, not under it); '+ terminal' opens a terminal in its own pane; '+ browser cell' shows the browser cell; planted: __domvecPlantNoCellBar draws no strip, __domvecPlantFileOutput (written to the file, not the editor) races the autosave",
      async run() {
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const until = async (ok, ms) => { for (let t = 0; t < ms && !ok(); t += 250) await sleep(250); return ok(); };
          const plugin = app.plugins.getPlugin("domvec-bridge");
          const NL = String.fromCharCode(10);
          const folder = "domvec-checks";
          if (!app.vault.getAbstractFileByPath(folder)) await app.vault.createFolder(folder);
          const bars = (view, sel) => [...view.containerEl.querySelectorAll(sel + " .domvec-cellbar")];
          const arm = async (planted) => {
            window.__domvecPlantNoCellBar = planted;
            window.__domvecPlantFileOutput = planted;
            const path = folder + "/pm4-" + (planted ? "p" : "c") + Date.now() + ".md";
            const f = await app.vault.create(path, "# A note" + NL + NL + "Some prose." + NL);
            const leaf = app.workspace.getLeaf("tab");
            const out = { planted };
            const terms0 = app.workspace.getLeavesOfType("domvec-terminal-view").length;
            try {
              await leaf.openFile(f, { state: { mode: "source", source: false } });
              const view = leaf.view;
              out.view_type = view.getViewType();
              await until(() => bars(view, ".markdown-source-view").length > 0, planted ? 3500 : 8000);
              const bar = bars(view, ".markdown-source-view")[0];
              out.source_strip = !!bar;
              if (bar) {
                const content = view.containerEl.querySelector(".cm-contentContainer").getBoundingClientRect();
                out.below_content = bar.getBoundingClientRect().top >= content.bottom - 1;
                out.labels = [...bar.querySelectorAll("button")].map((b) => b.textContent);
                [...bar.querySelectorAll("button")].find((b) => b.textContent === "+ code").click();
              } else {
                await plugin.addCodeCell(view);   // the same action, so the run arm still runs
              }
              await sleep(600);
              const ed = view.editor;
              out.cursor_in_cell = ed.getLine(ed.getCursor().line) === "" && ed.getLine(ed.getCursor().line - 1) === "${"`".repeat(3)}python";
              ed.replaceSelection("print(6*7)");
              await sleep(300);
              const run = view.containerEl.querySelector(".domvec-run-fence");
              out.run_button = !!run;
              if (run) run.click();
              // The reader keeps typing while the cell runs -- in the prose,
              // away from the cell. A write to the FILE then races the
              // editor's autosave; a write into the editor does not.
              for (let k = 0; k < 16; k++) {
                const line = 2;
                ed.replaceRange("x", { line, ch: ed.getLine(line).length });
                await sleep(400);
              }
              let stored = false;
              for (let t = 0; t < 20000 && !stored; t += 500) { await sleep(500); stored = (await app.vault.read(f)).includes("nb-output"); }
              await sleep(2500);    // past the editor's autosave, which is what overwrote it
              const text = await app.vault.read(f);
              out.output_stored = text.includes("nb-output") && text.includes("42");
              // Reading view.
              await leaf.setViewState({ type: "markdown", state: { file: path, mode: "preview" } });
              await until(() => bars(leaf.view, ".markdown-reading-view").length > 0, planted ? 3500 : 8000);
              const rbar = bars(leaf.view, ".markdown-reading-view")[0];
              out.reading_strip = !!rbar;
              if (rbar && !planted) {
                const sizer = rbar.parentElement;
                const after = [...sizer.children].slice([...sizer.children].indexOf(rbar) + 1).map((c) => c.className);
                out.reading_last = after.every((c) => /mod-footer/.test(c));
                [...rbar.querySelectorAll("button")].find((b) => b.textContent === "+ terminal").click();
                await until(() => app.workspace.getLeavesOfType("domvec-terminal-view").length > terms0, 5000);
                out.terminal_opened = app.workspace.getLeavesOfType("domvec-terminal-view").length > terms0;
                // '+ browser cell' appends a browser cell IN the note (G-36).
                [...rbar.querySelectorAll("button")].find((b) => b.textContent === "+ browser cell").click();
                await until(() => [...window.__domvecNotebookBrowsers].some((c) => c.sourcePath === f.path && c.view && c.view.webview), 8000);
                out.browser_shown = [...window.__domvecNotebookBrowsers].some((c) => c.sourcePath === f.path && c.view && c.view.webview
                  && c.containerEl.offsetWidth > 0);
              }
            } finally {
              window.__domvecPlantNoCellBar = false;
              window.__domvecPlantFileOutput = false;
              const terms = app.workspace.getLeavesOfType("domvec-terminal-view");
              for (const t of terms.slice(terms0)) { try { t.detach(); } catch (e) {} }
              try { leaf.detach(); } catch (e) {}
              try { await app.vault.delete(f); } catch (e) {}
            }
            return out;
          };
          try {
            return { clean: await arm(false), planted: await arm(true) };
          } finally {
            try {
              await sleep(1500);
              const fo = app.vault.getAbstractFileByPath(folder);
              if (fo && (!fo.children || !fo.children.length)) await app.vault.delete(fo, true);
            } catch (e) {}
          }
        })()`, { timeout: 240000 });
        if (!got || got.error || !got.clean || !got.planted) return { pass: false, evidence: got };
        const c = got.clean, p = got.planted;
        return { pass: c.view_type === "markdown" && c.source_strip && c.below_content && c.cursor_in_cell && c.run_button
                   && c.output_stored && c.reading_strip && c.reading_last && c.terminal_opened && c.browser_shown
                   && !p.source_strip && !p.reading_strip && !p.output_stored,
                 evidence: got };
      },
    },
    {
      id: "D-3",
      asks: "a chunk note's markdown half is the NATIVE, editable editor: in live preview the card half hides the note's body and draws the card; the switch's 'markdown' segment, clicked, folds the card to its bar (no read-only render in the fence) and shows the body as editable lines, and an edit typed there is saved to the note; reading view hides and shows the body the same way; planted (__domvecPlantNoHalves) the fence draws the read-only markdown and the body is never hidden",
      async run() {
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const plugin = app.plugins.getPlugin("domvec-bridge");
          const NL = String.fromCharCode(10);
          const FENCE = String.fromCharCode(96).repeat(3);
          const res = ((await plugin.sidecar.search("radix tree compressed trie edges labelled", 20)) || {}).hits || [];
          const hit = res.find((h) => String(h.url).includes("wikipedia.org/wiki/") && (h.tokens || 0) > 40) || res[0];
          if (!hit) return { error: "no chunk to write a note of" };
          const chunk = await plugin.sidecar.chunk(hit.cid);
          const md = ((chunk && chunk.lines) || []).map((l) => l.text).join(NL);
          const folder = "domvec-checks";
          if (!app.vault.getAbstractFileByPath(folder)) await app.vault.createFolder(folder);
          const visibleBody = (view) => [...view.editor.cm.contentDOM.querySelectorAll(".cm-line")]
            .filter((l) => l.offsetHeight > 0 && l.textContent.trim().length > 20).length;
          const readingShown = (view) => [...view.containerEl.querySelectorAll(".markdown-reading-view .markdown-preview-sizer > div")]
            .filter((d) => !d.querySelector(".block-language-domvec, code.language-domvec") && !d.classList.contains("mod-header")
                           && d.offsetHeight > 0 && d.textContent.trim().length > 20).length;
          const until = async (ok, ms) => { for (let t = 0; t < ms && !ok(); t += 250) await sleep(250); return ok(); };
          const arm = async (planted) => {
            window.__domvecPlantNoHalves = planted;
            const path = folder + "/d3-" + (planted ? "p" : "c") + Date.now() + ".md";
            const text = ["---", "domvec: chunk", "cid: " + hit.cid, "---", "", FENCE + "domvec", "cid: " + hit.cid, FENCE, "", md, ""].join(NL);
            const f = await app.vault.create(path, text);
            const leaf = app.workspace.getLeaf("tab");
            const out = { planted };
            try {
              await leaf.openFile(f, { state: { mode: "source", source: false } });
              for (let i = 0; i < 20 && !app.metadataCache.getFileCache(f)?.frontmatter; i++) await sleep(200);
              const view = leaf.view;
              await until(() => view.containerEl.querySelectorAll(".block-language-domvec .domvec-seg").length > 0, 15000);
              plugin.noteHalf.set(path, true);
              await sleep(800);
              out.card = { body_lines: visibleBody(view), placeholder: !!view.editor.cm.contentDOM.querySelector(".domvec-half-hidden"),
                           card_drawn: !!view.containerEl.querySelector(".block-language-domvec .domvec-body .domvec-html, .block-language-domvec .domvec-body [class]") };
              // Set from OUTSIDE the switch (the plugin, or another leaf of
              // the note): the fence follows, so only one half is on show.
              plugin.noteHalf.set(path, false);
              await sleep(800);
              out.external = { folded: !!view.containerEl.querySelector(".domvec-surface.domvec-folded"), body_lines: visibleBody(view) };
              plugin.noteHalf.set(path, true);
              await sleep(800);
              const seg = [...view.containerEl.querySelectorAll(".block-language-domvec .domvec-seg")].find((b) => b.textContent === "markdown");
              if (seg) seg.click();
              await sleep(1200);
              out.markdown = { clicked: !!seg, body_lines: visibleBody(view),
                               read_only_render: !!view.containerEl.querySelector(".block-language-domvec pre.domvec-md"),
                               folded: !!view.containerEl.querySelector(".domvec-surface.domvec-folded"),
                               editable: view.editor.cm.contentDOM.contentEditable === "true" };
              const mark = "typed in the native editor " + Date.now();
              view.editor.replaceRange(NL + mark, view.editor.offsetToPos(view.editor.cm.state.doc.length));
              let saved = false;
              for (let t = 0; t < 10000 && !saved; t += 500) { await sleep(500); saved = (await app.vault.read(f)).includes(mark); }
              out.markdown.saved = saved;
              // Reading view, both halves.
              await leaf.setViewState({ type: "markdown", state: { file: path, mode: "preview" } });
              await until(() => !!leaf.view.containerEl.querySelector(".markdown-reading-view .block-language-domvec .domvec-seg"), 15000);
              plugin.noteHalf.set(path, true); await sleep(800);
              out.reading = { card_body_sections: readingShown(leaf.view) };
              plugin.noteHalf.set(path, false); await sleep(600);
              out.reading.markdown_body_sections = readingShown(leaf.view);
            } finally {
              window.__domvecPlantNoHalves = false;
              plugin.noteHalves.delete(path);
              try { leaf.detach(); } catch (e) {}
              try { await app.vault.delete(f); } catch (e) {}
            }
            return out;
          };
          try {
            return { cid: hit.cid, clean: await arm(false), planted: await arm(true) };
          } finally {
            try {
              await sleep(1500);
              const fo = app.vault.getAbstractFileByPath(folder);
              if (fo && (!fo.children || !fo.children.length)) await app.vault.delete(fo, true);
            } catch (e) {}
          }
        })()`, { timeout: 180000 });
        if (!got || got.error || !got.clean || !got.planted) return { pass: false, evidence: got };
        const c = got.clean, p = got.planted;
        return { pass: c.card.body_lines === 0 && c.card.placeholder && c.card.card_drawn
                   && c.external.folded && c.external.body_lines > 0 && !p.external.folded
                   && c.markdown.clicked && c.markdown.body_lines > 0 && !c.markdown.read_only_render && c.markdown.folded
                   && c.markdown.editable && c.markdown.saved
                   && c.reading.card_body_sections === 0 && c.reading.markdown_body_sections > 0
                   && p.card.body_lines > 0 && !p.card.placeholder && p.markdown.read_only_render && p.reading.card_body_sections > 0,
                 evidence: got };
      },
    },
    {
      id: "G-7",
      asks: "a retrieval link written into a vault note is drawn in 3D: the note, indexed as the gesture's infill indexes it, becomes a page whose link to a stored page is a drawn edge; planted (__domvecPlantNoNoteIndex) no page and no edge",
      async run() {
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const plugin = app.plugins.getPlugin("domvec-bridge");
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0]?.view;
          if (!plugin || !v || !v.graph) return { error: "no plugin or graph" };
          const TARGET = "https://en.wikipedia.org/wiki/Radix_tree";
          const drawnTarget = () => v.graph && v.graph.graphData().nodes.some((n) => n.level === "page" && n.url === TARGET);
          for (let i = 0; i < 90 && !drawnTarget(); i++) await sleep(1000);      // a reloaded pane loads first
          if (!drawnTarget()) return { error: "target page not drawn" };
          const NL = String.fromCharCode(10);
          const folder = "domvec-checks";
          if (!app.vault.getAbstractFileByPath(folder)) await app.vault.createFolder(folder);
          const arm = async (planted) => {
            window.__domvecPlantNoNoteIndex = planted;
            const path = folder + "/g7-" + (planted ? "p" : "c") + Date.now() + ".md";
            const text = "# A retrieval note" + NL + NL + "What a [radix tree](" + TARGET + ") keeps of its keys." + NL;
            const f = await app.vault.create(path, text);
            const url = "vault://" + app.vault.getName() + "/" + path;
            let answered = null, drawn = false, inLayout = false, t0 = Date.now();
            try {
              answered = await plugin.indexNote(f, "check");
              for (let i = 0; i < 45 && !drawn; i++) {
                await sleep(2000);
                const lay = await (await fetch(plugin.settings.sidecar.replace(/[/]+$/, "") + "/layout?dims=3")).json();
                inLayout = (lay.edges || []).some((e) => e.source === "page:" + url && e.target === "page:" + TARGET);
                if (inLayout) {
                  await v.reload();   // the view's loader (Component.load is not it)
                  await sleep(1500);
                  drawn = v.graph.graphData().links.some((l) => l.source && l.target && l.source.url === url && l.target.url === TARGET);
                }
                if (planted && i >= 10) break;
              }
            } finally {
              window.__domvecPlantNoNoteIndex = false;
              try { await app.vault.delete(f); } catch (e) {}
              try { await fetch(plugin.settings.sidecar.replace(/[/]+$/, "") + "/purge", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ url }) }); } catch (e) {}
              plugin.settings.indexedNotes = (plugin.settings.indexedNotes || []).filter((p) => p !== path);
              await plugin.saveSettings();
            }
            return { planted, url: url.slice(-40), indexed: !!(answered && answered.url),
                     links: answered && answered.links ? answered.links.length : 0, in_layout: inLayout, drawn, s: Math.round((Date.now() - t0) / 1000) };
          };
          try {
            const clean = await arm(false);
            const planted = await arm(true);
            return { clean, planted };
          } finally {
            // The folder too, once the vault has seen its notes go (an empty
            // one was left behind when this ran at once).
            try {
              await sleep(1500);
              const fo = app.vault.getAbstractFileByPath(folder);
              if (fo && (!fo.children || !fo.children.length)) await app.vault.delete(fo, true);
              else if (!fo && await app.vault.adapter.exists(folder)) await app.vault.adapter.rmdir(folder, false);
            } catch (e) {}
            await v.reload();   // the view's loader (Component.load is not it)
          }
        })()`, { timeout: 300000 });
        if (!got || got.error) return { pass: false, evidence: got };
        return { pass: got.clean.indexed && got.clean.links >= 1 && got.clean.drawn && !got.planted.indexed && !got.planted.drawn,
                 evidence: got };
      },
    },
    {
      id: "G-85",
      asks: "an opened page's tree has MUCH longer links than the page layer's own spacing: the median tree link at least 3x the median gap between page nodes; the same tree drawn at the force tree's old 18-unit links fails that bar",
      async run() {
        // DESIGN_VII s6: "The link distance is set from the page layer's own
        // spacing (not a constant), and a check asserts the drawn tree's
        // median link length." The verbatim (VII): "max link lengths need to
        // be much longer" -- 3x the page gap here, not merely >= it.
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0]?.view;
          if (!v || !v.graph) return { error: "no graph" };
          if (v.level === "chunk") return { error: "in chunk view" };
          const d0 = v.graph.graphData();
          const dist = (a, b) => Math.hypot(a.x - b.x, a.y - b.y, (a.z || 0) - (b.z || 0));
          const pages = d0.nodes.filter((n) => n.level === "page" && Number.isFinite(n.x));
          const gaps = pages.map((p) => { let m = Infinity; for (const q of pages) if (q !== p) m = Math.min(m, dist(p, q)); return m; })
            .filter(Number.isFinite).sort((a, b) => a - b);
          const gap = gaps.length ? gaps[Math.floor(gaps.length / 2)] : null;
          // The stored page with the most chunks among a few known ones.
          const page = d0.nodes.find((n) => n.level === "page" && String(n.url).endsWith("/wiki/Radix_tree"))
            || d0.nodes.find((n) => n.level === "page" && String(n.url).includes("wikipedia.org/wiki/"));
          if (!page) return { error: "no wikipedia page node" };
          const url = page.url;
          const already = d0.nodes.some((x) => x.url === url && x.level !== "page");
          if (!already) await v.togglePage(page);
          let links = [];
          try {
            for (let i = 0; i < 40; i++) {
              await sleep(500);
              const d = v.graph.graphData();
              links = d.links.filter((l) => typeof l.source === "object" && typeof l.target === "object" && l.source.url === url && l.target.url === url);
              if (links.length > 5 && i > 6) break;
            }
          } finally { if (!already) await v.togglePage(page); }
          const lens = links.map((l) => dist(l.source, l.target)).sort((a, b) => a - b);
          const med = lens.length ? lens[Math.floor(lens.length / 2)] : null;
          // Non-vacuity: the same tree at the force tree's 18-unit links.
          const old = 18;
          return { url: url.slice(-40), links: lens.length, link_p50: med && Math.round(med * 100) / 100, page_gap_p50: gap && Math.round(gap * 100) / 100,
                   ratio: med && gap ? Math.round(med / gap * 100) / 100 : null,
                   ratio_at_old_18: gap ? Math.round(old / gap * 100) / 100 : null };
        })()`, { timeout: 60000 });
        if (!got || got.error) return { pass: false, evidence: got };
        return { pass: got.links > 5 && got.ratio >= 3 && got.ratio_at_old_18 < 3, evidence: got };
      },
    },
    {
      id: "G-2",
      asks: "chunk embeddings are UMAPped WITH their page's centroid -- two node kinds, one fit: the projector's model is the global scope, trained on page rows and chunk rows both; in the model's own coordinates (not the drawn ones, which put a chunk at its page by construction) a page's own chunks' centroid ranks near it -- median rank at most a fifth of the null arm's, where page positions are shuffled",
      async run() {
        // The user (2026-10-10): "the global map would be only on the chunks,
        // with centroids still at the center"; G-2: "two node kinds, one fit".
        // `page_frame` reads `raw_pos`, each chunk's own transform through the
        // model the page rows were trained in, and carries its own null arm.
        const got = await evaluate(`(async () => {
          const SIDE = String(app.plugins.getPlugin("domvec-bridge").settings.sidecar).replace(/[/]+$/, "");
          const d = await (await fetch(SIDE + "/projector?frame=1")).json();
          const f = d.page_frame || {};
          return { scope: d.scope, rows: d.global_rows, trained_pages: d.trained_pages, trained_chunks: d.trained_chunks,
                   pages: f.pages, fit: f.fit, null_shuffled: f.null_shuffled,
                   page_to_own_centroid_p50: f.page_to_own_centroid_p50 };
        })()`, { timeout: 300000 });
        if (!got || got.error || !got.fit || !got.null_shuffled) return { pass: false, evidence: got };
        return { pass: got.scope === "global" && got.trained_pages > 0 && got.trained_chunks > 0
                   && got.fit.own_rank_p50 * 5 <= got.null_shuffled.own_rank_p50,
                 evidence: got };
      },
    },
    {
      id: "G-269",
      asks: "url nodes are drawn MUCH larger than their chunks in the view as it is (2026-10-30, item 41), and the pick proxy with them: as the GPU is given them, page nodes pageScale (5x) what they were, and where chunks are drawn, at least four times the median chunk; planted (plantSmallPages) the old sizes",
      async run() {
        const got = await evaluate(`(async () => {
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0]?.view;
          if (!v || !v.graph || !v.batch) return { error: "no graph" };
          const read = () => {
            v.batchDirty = true; v.batchSync();
            const meshes = [v.batch.opaque, v.batch.clear, v.batch.glass];
            const pages = [], chunks = [], proxies = [];
            for (const n of v.graph.graphData().nodes) {
              const m = meshes[n.__bm];
              if (!m || typeof n.__bi !== "number" || n.__bi >= m.geo.instanceCount) continue;
              const sz = m.size.getX(n.__bi);
              if (n.level === "page") { pages.push([n.id, sz]); if (n.__threeObj && n.__threeObj.__proxy) proxies.push(sz); }
              else if (n.level !== "path") chunks.push(sz);
            }
            return { pages, chunks };
          };
          const med = (xs) => { if (!xs.length) return null; const s = xs.slice().sort((a, b) => a - b); return s[Math.floor(s.length / 2)]; };
          const now = read();
          v.plantSmallPages = true;
          let old;
          try { old = read(); } finally { v.plantSmallPages = false; v.batchDirty = true; v.batchSync(); }
          const oldBy = new Map(old.pages);
          const ratios = now.pages.map(([id, s]) => oldBy.get(id) > 0 ? s / oldBy.get(id) : null).filter((x) => x !== null);
          const pageMed = med(now.pages.map((p) => p[1])), chunkMed = med(now.chunks);
          // The pick proxy takes the drawn size (\`fitProxies\`): a page is
          // clicked at the size it is seen.
          const pn = v.graph.graphData().nodes.find((n) => n.level === "page" && n.__threeObj && n.__threeObj.__proxy);
          const lk = pn ? v.lookOf(pn, v.graph.nodeRelSize(), v.drawnMedia) : null;
          return { level: v.level || "pages", pages: now.pages.length, chunks: now.chunks.length,
                   scale: v.pageScale, page_vs_old_p50: med(ratios), page_vs_old_min: ratios.length ? Math.min(...ratios) : null,
                   page_vs_chunk: pageMed && chunkMed ? Math.round(pageMed / chunkMed * 100) / 100 : null,
                   proxy_half: pn ? Math.round(pn.__threeObj.scale.x * 100) / 100 : null, drawn_half: lk ? Math.round(lk.half * v.zoomScale * 100) / 100 : null, zoom_scale: v.zoomScale };
        })()`, { timeout: 60000 });
        if (!got || got.error) return { pass: false, evidence: got };
        return {
          pass: got.pages > 0 && got.scale >= 4 && Math.abs(got.page_vs_old_p50 - got.scale) < 0.05
             && (got.chunks < 20 || got.page_vs_chunk >= 4),
          evidence: got,
        };
      },
    },
    {
      id: "G-252",
      asks: "with a second browser cell open on the same page, hovering a fresh page's grey chunks in the visible cell opens their panels from THAT cell's own tree -- the hovered element's unit, its lines -- none skipped; planted (__domvecPlantLastBrowser) the last-built cell answers and the panels are not the hovered ones",
      async run() {
        // 2026-10-24, reported by the reader with three cells open: grey
        // nodes lit, panels missing (39 skipped) -- the cell built last
        // answered every grey-panel lookup.
        const fixtures = await serveFixtures();
        try {
          const got = await evaluate(`(async () => {
            ${PREP}
            const v = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
            const PAGE = ${JSON.stringify(fixtures.origin + "/result_cards.html?g252=")} + Date.now();
            // A second cell, built AFTER the visible one, in the visible one's
            // tab group as a background tab, on the same page.
            const leaf2 = app.workspace.createLeafInParent(bl2.parent, bl2.parent.children.length);
            await leaf2.setViewState({ type: "domvec-browser-view", active: false });
            if (leaf2.loadIfDeferred) await leaf2.loadIfDeferred();
            const b2 = leaf2.view;
            try {
              // A background tab's webview is not attached until shown once:
              // shown, loaded with the page, then put behind the visible cell.
              app.workspace.revealLeaf(leaf2);
              for (let i = 0; i < 80 && !(b2 && b2.webview && b2.domReady); i++) await sleep(250);
              b2.go(PAGE);
              for (let i = 0; i < 80 && !(b2.webview.getURL() === PAGE && !b2.webview.isLoading()); i++) await sleep(250);
              app.workspace.revealLeaf(bl2);
              await sleep(800);
              if (!(await land(PAGE, 30000))) return { error: "did not land" };
              for (let i = 0; i < 40 && !(b.forceTrees.get(PAGE) && b2.forceTrees && b2.forceTrees.get(PAGE)); i++) await sleep(500);
              await sleep(1500);
              const r = b.webview.getBoundingClientRect();
              const txt = (p) => p && p.lines ? p.lines.map((l) => String(l.text || "").trim()).join("|") : "";
              const arm = async (planted) => {
                window.__domvecPlantLastBrowser = planted;
                const before = v.hoverStats.empty_skipped, rows = [];
                try {
                  for (let i = 0; i < 8; i++) {
                    const x = 80 + (i % 4) * Math.max(60, (r.width - 160) / 3) + (planted ? 3 : 0), y = 90 + Math.floor(i / 4) * 160;
                    b.webview.sendInputEvent({ type: "mouseMove", x: Math.round(x), y: Math.round(y) });
                    await sleep(900);
                    const h = b.pipebox && b.pipebox.hover;
                    if (!h || !h.cid || !String(h.cid).startsWith("f:")) continue;
                    const bb = v.hoverBb;
                    const own = bb ? b.forcePayload(String(bb)) : null;
                    const panel = bb ? await v.chunkPayload(bb) : null;
                    rows.push({ hovered: String(h.cid).slice(-5), panel: bb ? String(bb).slice(-30) : "",
                                right: !!bb && !!own && txt(own).length > 0 && txt(own) === txt(panel) });
                  }
                } finally { window.__domvecPlantLastBrowser = false; }
                return { planted, hovers: rows.length, opened: rows.filter((x) => x.panel).length,
                         right: rows.filter((x) => x.right).length, skipped: v.hoverStats.empty_skipped - before, rows: rows.slice(0, 4) };
              };
              const clean = await arm(false);
              const planted = await arm(true);
              return { cells: app.workspace.getLeavesOfType("domvec-browser-view").length, clean, planted };
            } finally {
              try { leaf2.detach(); } catch (e) {}
              app.workspace.revealLeaf(bl2);
            }
          })()`, { timeout: 180000 });
          if (!got || got.error) return { pass: false, evidence: got };
          return {
            pass: got.cells >= 2 && got.clean.hovers >= 3 && got.clean.right === got.clean.hovers && got.clean.skipped === 0
               && got.planted.hovers >= 3 && got.planted.right < got.planted.hovers,
            evidence: got,
          };
        } finally {
          await tidyFixtures(fixtures.origin);
          await fixtures.close();
        }
      },
    },
    {
      id: "G-254",
      asks: "loading takes seconds: the spacing verdicts every chunk-view settle computes are the same node for node by the fast path and the old one, and the fast path is many times quicker on the graph as drawn; planted (plantSlowSpacing) the old path",
      async run() {
        // 2026-10-24: entering chunk view drew in 5-7 s and the window then
        // froze until 36-39 s -- \`fitRadiiToSpacing\` at 4.05 s a run,
        // three runs. The whole switch is timed outside the plugin
        // (scripts/check_loading.py: a reload would end this verifier).
        const got = await evaluate(`(async () => {
          const v = app.workspace.getLeavesOfType("domvec-graph-view")[0]?.view;
          if (!v || !v.graph) return { error: "no graph" };
          const nodes = v.graph.graphData().nodes;
          const rs = v.graph.nodeRelSize(), media = v.drawnMedia;
          const scale = v.nodeScale;
          const drawnOf = nodes.map((a) => { const lk = v.lookOf(a, rs, media); return lk ? lk.half / scale * scale : 0; });
          const t0 = performance.now(); const fast = v.spacingAllowed(nodes, drawnOf, false); const t1 = performance.now();
          const slow = v.spacingAllowed(nodes, drawnOf, true); const t2 = performance.now();
          let differ = 0, shrink = 0;
          for (let i = 0; i < nodes.length; i++) {
            const a = fast[i], b = slow[i];
            if (Number.isNaN(a) !== Number.isNaN(b)) { differ++; continue; }
            if (!Number.isNaN(a)) { shrink++; if (Math.abs(a - b) > 1e-9 * Math.max(1, Math.abs(b))) differ++; }
          }
          return { level: v.level || "pages", nodes: nodes.length, shrink, differ,
                   fast_ms: Math.round((t1 - t0) * 10) / 10, slow_ms: Math.round((t2 - t1) * 10) / 10,
                   last_run: v.spacingStats };
        })()`, { timeout: 120000 });
        if (!got || got.error) return { pass: false, evidence: got };
        return { pass: got.nodes > 100 && got.differ === 0 && got.fast_ms < got.slow_ms, evidence: got };
      },
    },
    {
      id: "G-188",
      asks: "nodes a little larger and brighter by default, links a little fainter but still visible: drawn 1.25x, the glow x1.4, links at 0.14 -- and in the rendered pixels, more lit area and brighter nodes than the old values give, links still drawn; planted (the old 1 / 1 / 0.25) the pixels fall back",
      async run() {
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const gl = app.workspace.getLeavesOfType("domvec-graph-view")[0];
          if (gl && gl.loadIfDeferred) await gl.loadIfDeferred();
          const v = gl && gl.view;
          if (!v || !v.graph || !v.batch) return { error: "no graph" };
          for (let i = 0; i < 60 && v.graph.graphData().nodes.length < 20; i++) await sleep(500);
          const d = v.graph.graphData();
          // The page with the most drawn nodes: one off-screen camera on it.
          const by = new Map();
          for (const n of d.nodes) if (n.url && Number.isFinite(n.x)) by.set(n.url, (by.get(n.url) || 0) + 1);
          const url = [...by.entries()].sort((a, b) => b[1] - a[1])[0]?.[0];
          if (!url) return { error: "nothing drawn" };
          const mat = v.batch.glass && v.batch.glass.mesh && v.batch.glass.mesh.material;
          const live = { nodeScale: v.nodeScale, nodeBright: v.batch.nodeBright,
                         uBright: mat && mat.uniforms && mat.uniforms.uBright ? mat.uniforms.uBright.value : null,
                         linkAlpha: v.batch.linkAlpha, links: d.links.length };
          // Rendered pixels: lit area, the nodes' mean brightness, and the
          // faint pixels where only links can be.
          const pixels = async () => {
            v.batchSync();
            await new Promise((r) => requestAnimationFrame(() => requestAnimationFrame(r)));
            // CLOSE: framed at the default pad every orb sits on its pixel
            // floor (uMinPx), and 1x and 1.25x draw the same (2026-10-24:
            // 32,209 vs 32,260 lit). At pad 0.15 the nodes are past it.
            const shot = v.inspect(url, 480, 0.15);
            if (!shot || !shot.png) return null;
            const img = new Image(); img.src = shot.png; await img.decode();
            const c = document.createElement("canvas"); c.width = img.width; c.height = img.height;
            const x = c.getContext("2d"); x.drawImage(img, 0, 0);
            const px = x.getImageData(0, 0, c.width, c.height).data;
            let lit = 0, bright = 0, faint = 0;
            for (let i = 0; i < px.length; i += 4) {
              const l = 0.2126 * px[i] + 0.7152 * px[i + 1] + 0.0722 * px[i + 2];
              if (l > 40) { lit++; bright += l; } else if (l > 6) faint++;
            }
            return { lit, mean_lit: lit ? Math.round(bright / lit) : 0, faint, nodes: shot.nodes };
          };
          // What the GPU is GIVEN: each node's instance size, each link's
          // alpha, the glass orbs' brightness uniform. (At the reader's own
          // distance a node is under a pixel, so the view's pixels cannot
          // tell 1x from 2x -- measured 2026-10-24: 3,286 lit pixels both.)
          const drawn = () => {
            const meshes = [v.batch.opaque, v.batch.clear, v.batch.glass];
            const sizes = new Map();
            for (const n of v.graph.graphData().nodes) {
              const m = meshes[n.__bm];
              if (m && typeof n.__bi === "number" && n.__bi < m.geo.instanceCount) sizes.set(n.id, m.size.getX(n.__bi));
            }
            const la = [];
            const lc = v.batch.lineCol;
            const nl = v.batch.lines && v.batch.lines.geometry.drawRange ? v.batch.lines.geometry.drawRange.count / 2 : 0;
            for (let i = 0; i < Math.min(nl, 400); i++) la.push(lc.getW(i * 2));
            la.sort((a, b) => a - b);
            const m2 = v.batch.glass.mesh.material;
            return { sizes, link_alpha: la.length ? la[Math.floor(la.length / 2)] : null, u: m2.uniforms.uBright.value };
          };
          const now = await pixels();
          const dNow = drawn();
          const keep = { s: v.nodeScale, b: v.batch.nodeBright, a: v.batch.linkAlpha };
          let old = null, dOld = null;
          try {
            v.nodeScale = 1; v.batch.setBright(1); v.batch.linkAlpha = 0.25;
            old = await pixels();
            dOld = drawn();
          } finally {
            v.nodeScale = keep.s; v.batch.setBright(keep.b); v.batch.linkAlpha = keep.a;
            v.batchSync();
          }
          const ratios = [];
          for (const [id, sz] of dNow.sizes) { const o = dOld.sizes.get(id); if (o > 0) ratios.push(sz / o); }
          ratios.sort((a, b) => a - b);
          const gpu = { nodes: ratios.length, size_ratio_p50: ratios.length ? Math.round(ratios[Math.floor(ratios.length / 2)] * 1000) / 1000 : null,
                        size_ratio_p5: ratios.length ? Math.round(ratios[Math.floor(ratios.length * 0.05)] * 1000) / 1000 : null,
                        link_alpha_now: dNow.link_alpha, link_alpha_old: dOld.link_alpha, bright_now: dNow.u, bright_old: dOld.u };
          return { url: url.slice(0, 70), live, gpu, now, old };
        })()`, { timeout: 60000 });
        if (!got || got.error || !got.now || !got.old) return { pass: false, evidence: got };
        const L = got.live;
        return {
          pass: Math.abs(L.nodeScale - 1.25) < 1e-9 && Math.abs(L.nodeBright - 1.4) < 1e-9 && L.uBright === L.nodeBright
             && Math.abs(L.linkAlpha - 0.14) < 1e-9
             // as the GPU is given them: 1.25x every node, x1.4 the glow, links 0.14 not 0.25
             && got.gpu.nodes > 0 && Math.abs(got.gpu.size_ratio_p50 - 1.25) < 0.01 && got.gpu.size_ratio_p5 > 1.2
             && Math.abs(got.gpu.bright_now - 1.4) < 1e-6 && Math.abs(got.gpu.bright_old - 1) < 1e-6
             && got.gpu.link_alpha_now !== null && got.gpu.link_alpha_now < got.gpu.link_alpha_old
             // and in the pixels of a page close enough to resolve: more lit area
             && got.now.lit > 1.03 * got.old.lit
             // links still visible: faint pixels remain where only links draw
             && (L.links === 0 || got.now.faint > 0),
          evidence: got,
        };
      },
    },
    {
      id: "G-66",
      asks: "the fold's own phases travel with every drain, and an unchanged merged run costs no lines: the same chunks are sent with the merged-run gate first or last, and the emit phase is cheaper; planted (mergedlines) every run's lines collected before its gate",
      async run() {
        // 2026-10-24, the page's own profile on discourse: 371 ms of 1,021 ms
        // of sensor time was \`makeMerged\` collecting the lines of every
        // merged run on the page, every repair, and dropping them at the gate.
        // A feed of 300 short siblings (merged into runs), five appends and
        // two edits; every pushed drain logged by its chunks' digests, sizes
        // and line counts, and its repair's phases.
        const fixtures = await serveFixtures();
        const arm = (planted) => evaluate(`(async () => {
          ${PREP}
          b.plant.delete("mergedlines");
          if (${planted}) b.plant.add("mergedlines");
          const log = [];
          const orig = b.onPushedDrain;
          b.onPushedDrain = function (p) {
            try { log.push({ chunks: (p.chunks || []).map((c) => [c.digest >>> 0, c.chars || 0, (c.lines || []).length]),
                             parts: (p.inpage && p.inpage.repair) || null }); } catch (e) {}
            return orig.call(this, p);
          };
          try {
            const PAGE = ${JSON.stringify(fixtures.origin + "/merged_runs.html?g66=")} + (${planted} ? "p" : "c") + Date.now();
            b.go("about:blank"); await sleep(800);
            if (!(await land(PAGE, 30000))) return { error: "did not land" };
            await sleep(2500);
            const landed = log.length;
            const click = (id) => b.webview.executeJavaScript("document.getElementById(" + JSON.stringify(id) + ").click(); true");
            for (let i = 0; i < 5; i++) { await click("add"); await sleep(450); }
            for (let i = 0; i < 2; i++) { await click("edit"); await sleep(450); }
            await sleep(1500);
            const after = log.slice(landed);
            const sum = (k) => Math.round(after.reduce((a, d) => a + ((d.parts && d.parts[k]) || 0), 0) * 10) / 10;
            // The chunks sent, as a multiset: two arms may split drains differently.
            const sent = log.flatMap((d) => d.chunks.map((c) => c.join(":"))).sort();
            return { planted: ${planted}, drains: log.length, after_landing: after.length, chunks_sent: sent.length,
                     sent_key: sent.join("|").length + ":" + sent.slice(0, 4).join(","), sent,
                     emit_ms: sum("emit"), fold_ms: sum("fold"), walk_ms: sum("walk"), reclassify_ms: sum("reclassify"),
                     parts_present: after.filter((d) => d.parts).length };
          } finally { b.onPushedDrain = orig; b.plant.delete("mergedlines"); }
        })()`, { timeout: 120000 });
        try {
          const clean = await arm(false);
          const planted = await arm(true);
          const same = !!clean.sent && !!planted.sent && clean.sent.length > 0 && clean.sent.join("|") === planted.sent.join("|");
          const strip = (x) => { const { sent, ...rest } = x || {}; return rest; };
          return {
            pass: !clean.error && !planted.error && clean.after_landing >= 5 && clean.parts_present === clean.after_landing
               && same && clean.emit_ms < planted.emit_ms,
            evidence: { same_chunks_sent: same, clean: strip(clean), planted: strip(planted) },
          };
        } finally {
          await tidyFixtures(fixtures.origin);
          await fixtures.close();
        }
      },
    },
    {
      id: "S-1",
      asks: "a shadow delta folds in milliseconds, and in O(delta)",
      async run() {
        const fixtures = await serveFixtures();
        const page = fixtures.origin + "/shadow_catalogue.html";
        try {
          const pagesBefore = (await ask("/health")).pages;
          const got = await evaluate(deltaProbe(page, SIDECAR),
                                     { timeout: 600000 });
          got.purged = await tidyFixtures(fixtures.origin);
          got.pages_before = pagesBefore;
          got.pages_after = (await ask("/health")).pages;
          if (got.error) return { pass: false, evidence: got };
          return {
            // Millisecond: the worst fold stays under 50ms.
            // O(delta): the page at least doubled while the cost of an
            // identically-sized delta did not.
            // And the null arm must be cheap AND empty, or the drains are
            // measuring a page that moves on its own.
            pass: got.worst_ms < 50
               && got.page_grew_by >= 2
               // Well BELOW proportional: O(page) would track the page's
               // growth; at 1-3 ms a fixed "< 2" failed on timer noise
               // (1.4 -> 3.0 ms while the page grew 5x, 2026-09-27).
               && got.cost_ratio < Math.max(2, got.page_grew_by / 2)
               && got.null_chunks === 0
               // The null arm must be CHEAP as well as empty. A page that
               // folds for 10ms while nothing happens is a page whose own
               // motion is inside every other number here.
               && got.null_repair_ms < 2
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
    // ---- Addendum VI: one place for each form of a chunk (G-76 .. G-81) ----
    //
    // Each drives the running plugin through its own harness (`__domvec.act`)
    // and reads the result off the DOM a person sees -- then compares it with
    // the PAGE, not with what the plugin says about itself: an outline is
    // checked against the element's own box in the guest, a billboard for a
    // real shadow root, a pin against the markdown side and the graph at once.
    {
      id: "G-76",
      asks: "scan statistics are the browser's corner box, not a pane -- and a tool can open it",
      async run() {
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const d = window.__domvec;
          await d.act("open", "browser");
          const closed = (await d.act("pipebox", "close")).result;
          const opened = (await d.act("pipebox", "open")).result;
          await sleep(2500);
          const ui = d.ui();
          const box = ui.pipebox || {};
          return { separate_panes: ui.separate_panes, closed, opened,
                   expanded: box.expanded, asked_open: box.asked_open,
                   corner: box.corner,
                   readout_drawn: !!(ui.profile && ui.profile.e2e_shown !== null
                                     && ui.profile.e2e_shown !== undefined) };
        })()`);
        const sp = got.separate_panes || {};
        return {
          pass: sp.chunk === 0 && sp.profile === 0 && !sp.status_bar_readout
             && got.closed && got.closed.expanded === false
             && got.expanded === true && got.asked_open === true
             && got.readout_drawn
             && got.corner && Math.abs(got.corner.right - 10) <= 2
             && Math.abs(got.corner.bottom - 10) <= 2,
          evidence: got,
        };
      },
    },
    {
      id: "G-78",
      asks: "a pin: outline on its box, markdown card beside the page, billboard in the graph; the billboard's x and minimize act on it alone, the card brings it back",
      async run() {
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const d = window.__domvec;
          await d.act("open", "graph");
          await d.act("open", "browser");
          await d.act("unpin", "all");
          await d.act("navigate", "https://en.wikipedia.org/wiki/Radix_tree");
          await sleep(4000);
          const view = app.workspace.getLeavesOfType("domvec-browser-view")[0].view;
          // From the TOP: returning to a page restores its old scroll, and the
          // paragraph pinned last time can be 1,800 px above the view.
          await view.webview.executeJavaScript("window.scrollTo({top:0,behavior:'instant'}); true");
          await sleep(300);
          // A paragraph in the article, and ITS box in the guest's viewport.
          const target = await view.webview.executeJavaScript(\`(function(){
            var ps = document.querySelectorAll('#mw-content-text p');
            var el = null;
            for (var i = 0; i < ps.length; i++) {
              var b = ps[i].getBoundingClientRect();
              if (b.height > 20 && b.top > 60 && b.bottom < innerHeight - 40) { el = ps[i]; break; }
            }
            if (!el) return null;
            var parts = [], n = el;
            while (n && n.nodeType === 1) {
              var t = n.tagName.toLowerCase(), i = 1, s = n.previousElementSibling;
              while (s) { if (s.tagName === n.tagName) i++; s = s.previousElementSibling; }
              parts.unshift(i > 1 ? t + '[' + i + ']' : t); n = n.parentElement;
            }
            return '/' + parts.join('/');
          })()\`);
          if (!target) return { error: "no paragraph on screen to pin" };
          const pinned = (await d.act("pin", target)).result || {};
          await sleep(1500);
          const ui = d.ui();
          const pin = (ui.pinned && ui.pinned.pins || [])[0] || null;
          // The chunk's own element box, as the page lays it out right now.
          const box = pin ? await view.webview.executeJavaScript(\`(function(){
            var n = document.evaluate(\${JSON.stringify(pin ? pin.matched : "")}, document, null,
              XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
            if (n && n.nodeType === 3) n = n.parentElement;
            if (!n) return null; var b = n.getBoundingClientRect();
            return {x: b.left, y: b.top, w: b.width, h: b.height, vw: innerWidth, vh: innerHeight};
          })()\`) : null;
          const wb = view.webview.getBoundingClientRect();
          const outline = ((ui.pipebox || {}).pins || [])[0] || null;
          const bbs = ui.billboards || [];
          const bb = pin ? bbs.find((b) => b.id === pin.cid) : null;
          const card = (ui.pinned && ui.pinned.side_cards || []).find((c) => pin && c.cid === pin.cid);
          // It must survive a REDRAW -- a refit, a new epoch, a store
          // switch all redraw the graph -- still on screen, with its x.
          // (Each redraw used to detach the billboard layer: the entry
          // stayed, the element left the document, and nothing could close
          // it. 2026-09-26.)
          let survived = null;
          if (pin) {
            const g0 = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
            if (typeof g0.reload === "function") { await g0.reload(); await sleep(1500); }
            const e0 = g0.billboards && g0.billboards.get(pin.cid);
            survived = { entry: !!e0, in_document: !!e0 && document.contains(e0.el),
                         has_close: !!e0 && !!e0.el.querySelector(".domvec-bb-close") };
          }
          // ... and closing it from the GRAPH side lets go of all three.
          let after = null, closed_via = null;
          if (pin) {
            const g = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
            // THIS pin's billboard, not the first one with an x.
            const own = g.billboards && g.billboards.get(pin.cid);
            const x = own && own.el.querySelector(".domvec-bb-close");
            closed_via = x ? "own billboard's x" : "no x on its billboard";
            const snap = () => {
              const u = d.ui();
              const own2 = g.billboards && g.billboards.get(pin.cid);
              return { pins: (u.pinned && u.pinned.pins || []).length,
                       card: !!view.markdownWrap.querySelector('.domvec-pin-card[data-cid="' + pin.cid + '"]'),
                       billboard: !!own2 && document.contains(own2.el),
                       minimized: !!own2 && !!own2.minimized,
                       outlines: ((u.pipebox || {}).pins || []).filter((o) => o.shown).length };
            };
            // (2026-09-26) The billboard's x removes it from the 3D view ONLY:
            // the pin, its card and its outline stay.
            if (x) x.click();
            await sleep(800);
            after = { x_on_billboard: snap() };
            // Clicking the card in the side panel brings it back, expanded.
            const card = () => view.markdownWrap.querySelector('.domvec-pin-card[data-cid="' + pin.cid + '"] .domvec-browser-mdbody');
            if (card()) card().click();
            await sleep(1500);
            after.card_click = snap();
            // Minimize collapses it to its title bar; the card expands it again.
            const own3 = g.billboards && g.billboards.get(pin.cid);
            const mn = own3 && own3.el.querySelector(".domvec-bb-min");
            if (mn) mn.click();
            await sleep(300);
            after.minimize = snap();
            if (card()) card().click();
            await sleep(800);
            after.card_click_again = snap();
            // The card's own x lets go of all three.
            const cx = view.markdownWrap.querySelector('.domvec-pin-card[data-cid="' + pin.cid + '"] .domvec-pin-close');
            if (cx) cx.click();
            await sleep(800);
            after.card_x = snap();
          }
          return { target, pinned, pin, box,
                   webview: [wb.left, wb.top, wb.width, wb.height],
                   outline, billboard: bb || null, card: card || null,
                   side_shown: ui.pinned && ui.pinned.side_shown, survived, closed_via, after };
        })()`, { timeout: 120000 });
        if (got.error) return { pass: false, evidence: got };
        // The outline must sit on the element's own box, clipped to the webview.
        let off = null;
        if (got.box && got.outline && got.outline.rect) {
          const [wl, wt, ww, wh] = got.webview;
          const left = wl + Math.max(0, got.box.x);
          const top = wt + Math.max(0, got.box.y);
          const right = wl + Math.min(ww, got.box.x + got.box.w);
          const bottom = wt + Math.min(wh, got.box.y + got.box.h);
          const [ol, ot, ow, oh] = got.outline.rect;
          // The outline is the whole CHUNK's extent (G-79's decision: hover
          // and pin outline the chunk, not the element under the pointer),
          // so it must CONTAIN the element's box; `off` is how far the box
          // pokes out of it, 0 when contained.
          off = Math.max(0, ol - left, ot - top, right - (ol + ow), bottom - (ot + oh));
        }
        return {
          pass: !!got.pin && got.side_shown === true
             && !!got.card && got.card.rendered_elements > 0
             && !!got.outline && got.outline.shown && off !== null && off <= 3
             && !!got.billboard && got.billboard.fromBrowser && got.billboard.shadow
             && !!got.survived && got.survived.in_document && got.survived.has_close
             && !!got.after
             && got.after.x_on_billboard.billboard === false && got.after.x_on_billboard.pins === 1
             && got.after.x_on_billboard.card === true
             && got.after.card_click.billboard === true && got.after.card_click.minimized === false
             && got.after.minimize.billboard === true && got.after.minimize.minimized === true
             && got.after.card_click_again.minimized === false
             && got.after.card_x.pins === 0 && got.after.card_x.billboard === false
             && got.after.card_x.card === false && got.after.card_x.outlines === 0,
          evidence: { ...got, outline_off_px: off },
        };
      },
    },
    {
      id: "G-77",
      asks: "a chunk's shadow-DOM form is a billboard in the graph; there is no chunk pane",
      async run() {
        const got = await inPane(`
          const d = window.__domvec;
          const data = v.graph.graphData();
          const node = data.nodes.find((n) => n.level === "chunk") ||
                       data.nodes.find((n) => n.level !== "page");
          if (!node) {
            // Nothing unfolded: open the biggest page one step and use a chunk.
            const page = data.nodes.slice().sort((a, b) => (b.members || 0) - (a.members || 0))[0];
            await d.act("unfold", page && page.url);
          }
          const again = v.graph.graphData().nodes.find((n) => n.level === "chunk");
          if (!again) return { error: "no chunk node to open" };
          for (const b of v.billboardState()) v.closeBillboard(b.id);
          await v.openBillboard(again);
          await sleep(2500);
          const bb = v.billboardState().find((b) => b.id === again.id) || null;
          const host = [...v.containerEl.querySelectorAll(".domvec-bb")]
            .map((e) => e.querySelector(".domvec-html-host")).find(Boolean);
          const inside = host && host.shadowRoot
            ? host.shadowRoot.querySelectorAll("*").length : (bb ? bb.elements : 0);
          v.closeBillboard(again.id);
          return { node: again.id, billboard: bb, shadow_elements: inside, form: bb ? bb.form : null,
                   chunk_panes: app.workspace.getLeavesOfType("domvec-chunk-view").length };
        `);
        return {
          pass: !!got.billboard && got.billboard.shadow && got.shadow_elements > 1
             && got.chunk_panes === 0,
          evidence: got,
        };
      },
    },
    {
      id: "G-82",
      asks: "the side panel is the only second view: page always shown, pins stack, closing one closes its three forms",
      async run() {
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const d = window.__domvec;
          await d.act("open", "graph");
          await d.act("open", "browser");
          await d.act("unpin", "all");
          await d.act("navigate", "https://en.wikipedia.org/wiki/Radix_tree");
          await sleep(4000);
          const view = app.workspace.getLeavesOfType("domvec-browser-view")[0].view;
          await view.webview.executeJavaScript("window.scrollTo({top:0,behavior:'instant'}); true");
          await sleep(300);
          const pageShown = () => view.browserWrap.offsetWidth > 50 && view.browserWrap.offsetHeight > 50;
          const toggle = () => [...view.containerEl.querySelectorAll(".domvec-browser-bar button")]
            .some((e) => /^(markdown|browser)$/.test((e.textContent || "").trim()));
          // Pins whose paragraph is in the viewport right now: an outline is
          // drawn for exactly those (a pin below the fold has nothing to
          // outline, and after navigating back the page starts at the top).
          const onScreen = async (xs) => view.webview.executeJavaScript(\`(function(xs){
            return xs.filter(function(x){
              var n = document.evaluate(x, document, null, XPathResult.FIRST_ORDERED_NODE_TYPE, null).singleNodeValue;
              if (!n) return false; var b = n.getBoundingClientRect();
              return b.bottom > 0 && b.top < innerHeight && b.width > 0;
            }).length; })(\` + JSON.stringify(xs) + ")").catch(() => null);
          let targetsHere = [];
          const state = async () => {
            const u = d.ui();
            const here = (view.webview.getURL() || "").indexOf("Radix_tree") >= 0;
            return {
              pins_on_screen: here ? await onScreen(targetsHere) : 0,
              page_shown: pageShown(),
              side_shown: !!(u.pinned && u.pinned.side_shown),
              cards: [...view.markdownWrap.querySelectorAll(".domvec-pin-card")].map((c) => c.dataset.cid),
              // A billboard shows its own chunk and any pinned chunk drawn
              // THROUGH it (a duplicate, a merge group's member).
              billboards: (u.billboards || []).filter((b) => b.fromBrowser).flatMap((b) => [b.id].concat(b.pins || [])),
              outlines_shown: ((u.pipebox || {}).pins || []).filter((o) => o.shown).length,
            };
          };
          // Two paragraphs on screen, as xpaths in the trie's convention.
          const allOnScreen = await view.webview.executeJavaScript(\`(function(){
            var ps = document.querySelectorAll('#mw-content-text p'), out = [];
            for (var i = 0; i < ps.length && out.length < 12; i++) {
              var b = ps[i].getBoundingClientRect();
              if (!(b.height > 20 && b.top > 60 && b.bottom < innerHeight - 40)) continue;
              var parts = [], n = ps[i];
              while (n && n.nodeType === 1) {
                var t = n.tagName.toLowerCase(), k = 1, s = n.previousElementSibling;
                while (s) { if (s.tagName === n.tagName) k++; s = s.previousElementSibling; }
                parts.unshift(k > 1 ? t + '[' + k + ']' : t); n = n.parentElement;
              }
              out.push('/' + parts.join('/'));
            }
            return out;
          })()\`);
          // Two paragraphs drawn by DIFFERENT chunks: the chunker now keeps a
          // heading, its lead and what follows together, so two neighbouring
          // paragraphs are often one chunk -- and pinning one chunk twice is
          // not two pins.
          const SIDE = String(app.plugins.getPlugin("domvec-bridge").settings.sidecar).replace(/[/]+$/, "");
          const targets = [], seen = new Set();
          for (const x of allOnScreen || []) {
            const r = await fetch(SIDE + "/resolve?url=" + encodeURIComponent(view.webview.getURL())
                                  + "&xpath=" + encodeURIComponent(x)).then((q) => q.json()).catch(() => null);
            if (r && r.cid && !seen.has(r.cid)) { seen.add(r.cid); targets.push(x); }
            if (targets.length === 2) break;
          }
          if (targets.length < 2) return { error: "fewer than two chunks' paragraphs on screen", candidates: allOnScreen };
          targetsHere = [];
          const before = await state();
          const a = (await d.act("pin", targets[0])).result || {};
          await sleep(1200);
          const b = (await d.act("pin", targets[1])).result || {};
          targetsHere = targets.slice();
          await sleep(1500);
          const two = await state();
          // Pins persist as side panels when the page is left; their
          // outlines belong to the page and leave with it.
          await d.act("navigate", "https://en.wikipedia.org/wiki/Trie");
          await sleep(3000);
          const away = await state();
          await d.act("navigate", "https://en.wikipedia.org/wiki/Radix_tree");
          await sleep(4000);
          const back = await state();
          // Close the NEWEST from the side panel: its three forms go, the
          // other pin's stay.
          const newest = two.cards[0];
          const x = view.markdownWrap.querySelector('.domvec-pin-card[data-cid="' + newest + '"] .domvec-pin-close');
          if (x) x.click();
          targetsHere = [targets[0]];
          await sleep(1000);
          const one = await state();
          await d.act("unpin", "all");
          await sleep(800);
          const none = await state();
          // Pins moved to the chunk that draws their address after a capture
          // retired theirs (G-82, 2026-10-17): the evidence the path ran.
          const now = (c) => { let k = 0; while (c && view.reanchored.has(c) && k++ < 8) c = view.reanchored.get(c); return c || null; };
          return { targets, pinned: [now(a.cid), now(b.cid)], pinned_as: [a.cid || null, b.cid || null], toggle: toggle(),
                   before, two, away, back, one, none, closed: newest,
                   reanchor: { reresolved: view.diffsApplied.pins_reresolved, lost: view.diffsApplied.pins_lost } };
        })()`, { timeout: 180000 });
        if (got.error) return { pass: false, evidence: got };
        const [a, b] = got.pinned;
        const distinct = !!a && !!b && a !== b;
        return {
          pass: got.toggle === false
             && [got.before, got.two, got.away, got.back, got.one, got.none].every((s) => s.page_shown)
             && got.before.side_shown === false
             // stacked, newest first, one billboard each
             && distinct && got.two.side_shown && got.two.cards.join() === [b, a].join()
             && got.two.billboards.includes(a) && got.two.billboards.includes(b)
             // one outline per pinned paragraph ON SCREEN -- both, just pinned
             && got.two.pins_on_screen === 2 && got.two.outlines_shown === 2
             // away: the side keeps both, the page's outlines go
             && got.away.cards.length === 2 && got.away.outlines_shown === 0
             && got.back.outlines_shown === got.back.pins_on_screen
             // closing one from the side closes its three forms only
             && got.one.cards.join() === a && !got.one.billboards.includes(b)
             && got.one.billboards.includes(a)
             && got.one.outlines_shown === got.one.pins_on_screen
             && got.none.side_shown === false && got.none.cards.length === 0,
          evidence: got,
        };
      },
    },
    {
      id: "G-79",
      asks: "hover outlines the 256 chunk's whole extent over the page, fast, and rings its node",
      async run() {
        // DESIGN_VII §1/§3. Navigated fresh, so the page's landing capture is
        // in flight while the hovers happen -- the condition under which the
        // old path (one store query per hover) took up to 5.6 s.
        //
        // Each heading/paragraph pair is scrolled into view, hovered, and its
        // outline compared at THAT moment with an oracle that is not the
        // overlay's code: the chunk's elements per the sidecar's own
        // /page_map, their boxes read in the page.
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const d = window.__domvec;
          const base = String(app.plugins.getPlugin("domvec-bridge").settings.sidecar || "").replace(/\\/+$/, "");
          await d.act("open", "browser");
          await d.act("navigate", "https://en.wikipedia.org/wiki/Radix_tree");
          const view = app.workspace.getLeavesOfType("domvec-browser-view")[0].view;
          const wv = view.webview, pb = view.pipebox;
          for (let i = 0; i < 40 && !(pb.map.url === wv.getURL() && pb.map.size); i++) await sleep(250);
          if (!pb.map.size) return { error: "the overlay's map never loaded" };
          let oracle = await fetch(base + "/page_map?url=" + encodeURIComponent(wv.getURL())).then((r) => r.json());
          pb.latencies.length = 0;
          const count = await wv.executeJavaScript(
            "document.querySelectorAll('#mw-content-text h2, #mw-content-text h3').length");
          const UNION = "(function(xs){var l=1e9,t=1e9,r=-1e9,b=-1e9,any=false;" +
            "for(var i=0;i<xs.length;i++){var n=document.evaluate(xs[i],document,null,9,null).singleNodeValue;" +
            "if(n&&n.nodeType===3)n=n.parentElement;if(!n)continue;var q=n.getBoundingClientRect();" +
            "if(q.width<=0&&q.height<=0)continue;any=true;" +
            "l=Math.min(l,q.left);t=Math.min(t,q.top);r=Math.max(r,q.right);b=Math.max(b,q.bottom);}" +
            "return any?[l,t,r,b]:null;})";
          const wb = wv.getBoundingClientRect();
          async function hoverAt(x, y) {
            // Move, let Chromium apply it, then wait out two of the overlay's
            // 80 ms polls, so the reading is of THIS position, not the last.
            // Chromium does not re-hit-test a move to where the pointer
            // already is, so after a scroll :hover can stay on the element
            // that USED to be there. Jiggle away and back until the page's
            // own :hover agrees with elementFromPoint -- the aim is then real.
            const AGREE = "(function(x,y){var e=document.elementFromPoint(x,y);" +
              "var hs=document.querySelectorAll(':hover');return !!e&&hs.length>0&&hs[hs.length-1]===e;})";
            for (let k = 0; k < 8; k++) {
              wv.sendInputEvent({ type: "mouseMove", x: x + 6 + k, y: y + 4 });
              await sleep(25);
              wv.sendInputEvent({ type: "mouseMove", x, y });
              await sleep(35);
              if (await wv.executeJavaScript(AGREE + "(" + x + "," + y + ")")) break;
            }
            const moved = performance.now();
            let h = null;
            for (let i = 0; i < 25; i++) {
              await sleep(40);
              h = pb.hover;
              if (h && h.at > moved + 90) break;
              if (!h && performance.now() - moved > 250) break;
            }
            const o = view.containerEl.querySelector(".domvec-chunk-outline");
            const r = o && o.style.display !== "none" ? o.getBoundingClientRect() : null;
            const outline = r ? [r.left, r.top, r.width, r.height] : null;
            let off = null;
            if (h && outline) {
              // The truth for THIS chunk: landing re-captures and re-partitions
              // the page for a few seconds, so a hover can resolve to a chunk
              // newer than the snapshot taken at the start -- read again then.
              if (!(oracle.chunks || {})[h.cid]) {
                oracle = await fetch(base + "/page_map?url=" + encodeURIComponent(wv.getURL())).then((r) => r.json());
              }
              const xs = (oracle.chunks || {})[h.cid] || [];
              const box = await wv.executeJavaScript(UNION + "(" + JSON.stringify(xs.slice(0, 400)) + ")");
              if (box) {
                const want = [wb.left + Math.max(0, box[0]), wb.top + Math.max(0, box[1]),
                              wb.left + Math.min(wb.width, box[2]), wb.top + Math.min(wb.height, box[3])];
                off = Math.max(Math.abs(outline[0] - want[0]), Math.abs(outline[1] - want[1]),
                               Math.abs(outline[0] + outline[2] - want[2]),
                               Math.abs(outline[1] + outline[3] - want[3]));
              }
            }
            const under = await wv.executeJavaScript("(function(x,y){var e=document.elementFromPoint(x,y);return e?e.tagName+(e.className?'.'+String(e.className).split(' ')[0]:''):null;})(" + x + "," + y + ")");
            return { cid: h && h.cid, outline, off, under, has_outline: !!outline };
          }
          const pairs = [];
          for (let j = 0; j < count && pairs.length < 6; j++) {
            // Jump -- the page scrolls smoothly, and coordinates read mid-
            // animation point at whatever was there before -- then measure
            // once it has settled.
            const ok = await wv.executeJavaScript("(function(j){" +
              "var h=document.querySelectorAll('#mw-content-text h2, #mw-content-text h3')[j];" +
              "var wrap=h.closest('.mw-heading')||h, p=wrap.nextElementSibling;" +
              "while(p&&p.tagName!=='P')p=p.nextElementSibling; if(!p) return false;" +
              "window.scrollTo({top: wrap.getBoundingClientRect().top + scrollY - 120, behavior: 'instant'});" +
              "return true;})(" + j + ")");
            if (!ok) continue;
            await sleep(200);
            const t = await wv.executeJavaScript("(function(j){" +
              "var h=document.querySelectorAll('#mw-content-text h2, #mw-content-text h3')[j];" +
              "var wrap=h.closest('.mw-heading')||h, p=wrap.nextElementSibling;" +
              "while(p&&p.tagName!=='P')p=p.nextElementSibling;" +
              "var hb=h.getBoundingClientRect(), q=p.getBoundingClientRect();" +
              "if(hb.top<0||q.top>innerHeight-30) return null;" +
              // Aimed INTO the heading's text, not 10 px from its edge: in a
              // narrower pane Wikipedia's floating contents button sits over
              // the left edge, and the pointer hovered the button.
              "var r=document.createRange();r.selectNodeContents(h);var tb=r.getBoundingClientRect();" +
              "var hx=Math.round(tb.left+Math.min(tb.width/2,40)),hy=Math.round(tb.top+tb.height/2);" +
              "return {h:[hx,hy]," +
              "p:[Math.round(q.left+Math.min(q.width/2,60)),Math.round(q.top+Math.min(20,q.height/2))]};})(" + j + ")");
            if (!t) continue;
            const a = await hoverAt(t.h[0], t.h[1]);
            const b = await hoverAt(t.p[0], t.p[1]);
            pairs.push({ heading: a, paragraph: b });
          }
          const lat = pb.latencies.slice().sort((x, y) => x - y);
          const g = app.workspace.getLeavesOfType("domvec-graph-view")[0];
          const last = pairs.length ? pairs[pairs.length - 1].paragraph : null;
          const node = g && g.view && g.view.graph && last && last.cid
            ? g.view.graph.graphData().nodes.find((n) => n.id === last.cid) : null;
          return { pairs, latency_p50: lat[lat.length >> 1] ?? null,
                   latency_p95: lat[Math.floor(lat.length * 0.95)] ?? null, samples: lat.length,
                   node_in_graph: !!node, node_ringed: !!(node && node.hovered) };
        })()`, { timeout: 150000 });
        if (got.error) return { pass: false, evidence: got };
        const offs = [];
        let sameChunk = 0, oneBox = 0;
        for (const pair of got.pairs) {
          for (const side of [pair.heading, pair.paragraph]) offs.push(side.off);
          if (pair.heading.cid && pair.heading.cid === pair.paragraph.cid) {
            sameChunk++;
            const a = pair.heading.outline, b = pair.paragraph.outline;
            if (a && b && a.every((v, i) => Math.abs(v - b[i]) <= 2)) oneBox++;
          }
        }
        const measured = offs.filter((v) => v !== null && v !== undefined);
        const worst = measured.length ? Math.max(...measured) : null;
        return {
          pass: got.pairs.length > 0 && measured.length === offs.length
             && worst !== null && worst <= 3
             && sameChunk > 0 && oneBox === sameChunk
             && got.latency_p95 !== null && got.latency_p95 < 100
             && (!got.node_in_graph || got.node_ringed),
          evidence: { pairs: got.pairs.length, measured: measured.length,
                      extent_off_px_worst: worst, same_chunk_pairs: sameChunk,
                      drawn_as_one_box: oneBox, latency_ms_p50: got.latency_p50,
                      latency_ms_p95: got.latency_p95, samples: got.samples,
                      node_in_graph: got.node_in_graph, node_ringed: got.node_ringed,
                      per_pair: got.pairs.map((p) => ({
                        heading: p.heading.cid, paragraph: p.paragraph.cid,
                        off: [p.heading.off, p.paragraph.off],
                        under: [p.heading.under, p.paragraph.under],
                        outline: [p.heading.has_outline, p.paragraph.has_outline] })) },
        };
      },
    },
    {
      id: "G-80-hover",
      asks: "hover-first, through a real pointer: a hover on a stored page calls /focus and is traced to the screen as its own kind",
      async run() {
        const before = await ask("/profile");
        const n0 = (before.focus || []).length;
        const got = await evaluate(`(async () => {
          ${PREP}
          const d = window.__domvec;
          // A FRESH document: a page loaded before the plugin's last reload
          // carries a sensor whose pushes the new load does not accept (its
          // nonce), and its hovers never arrive.
          await land("about:blank", 8000);
          if (!(await land("https://en.wikipedia.org/wiki/Trie", 30000))) return { error: "did not land" };
          await sleep(3000);
          const view = b;
          // A chunk already focused is not focused again: start clean.
          if (view.pipebox && view.pipebox.focused) view.pipebox.focused.clear();
          const at = await view.webview.executeJavaScript(\`(function(){
            var ps = document.querySelectorAll('#mw-content-text p');
            for (var i = 0; i < ps.length; i++) {
              var b = ps[i].getBoundingClientRect();
              if (b.height > 20 && b.top > 60 && b.bottom < innerHeight - 40)
                return {x: Math.round(b.left + 40), y: Math.round(b.top + b.height / 2)};
            }
            return null; })()\`);
          if (!at) return { error: "no paragraph on screen" };
          let hover = null;
          const f0 = view.pipebox ? view.pipebox.focusCalls : 0;
          for (let i = 0; i < 12 && !hover; i++) {
            // Across the page, as G-38 moves: the first moves after a page
            // lands are not always pushed (seen: 2 of 3 points silent).
            view.webview.sendInputEvent({ type: "mouseMove", x: at.x + (i * 97) % 500, y: at.y + (i % 4) * 45 });
            await sleep(250);
            hover = view.lastHovered;
          }
          await sleep(1500);
          const traces = d.profile.traces(500).filter((t) => t.kind === "hover" && t.url === "https://en.wikipedia.org/wiki/Trie");
          return { cid: hover && hover.cid, stored: hover && hover.stored, pane_focus_calls: view.pipebox.focusCalls - f0, hover_traces: traces.length,
                   last: traces.slice(-1)[0] || null };
        })()`, { timeout: 90000 });
        const after = await ask("/profile");
        const focus = (after.focus || []).slice(n0);
        return {
          // The pane's own count of /focus calls: the sidecar's profile list is
          // a capped buffer, and once full a count by length reads 0.
          pass: !!got.cid && got.pane_focus_calls > 0 && got.hover_traces > 0,
          evidence: { ...got, focus_calls: focus.length, focus: focus.slice(-3) },
        };
      },
    },
  ];

  return { CHECKS, wakeProjector, tidyFixtures, ask, inPane };
}
