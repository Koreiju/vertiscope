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
 *     MCP tools start runs and read results through `window.__vertiscope.verify`;
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

  const GRAPH_VIEW = "vertiscope-graph-view";

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
      await app.commands.executeCommandById("vertiscope-open-graph");
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
    for (const l of app.workspace.getLeavesOfType("vertiscope-chunk-view")) {
      l.detach();
    }
    for (const l of app.workspace.getLeavesOfType("vertiscope-browser-view")) {
      l.detach();
    }
    await sleep(700);
    const gFresh = app.workspace.getLeavesOfType("vertiscope-graph-view")[0];
    // A SPLIT of the graph, not a tab beside it: a tab in the graph's group
    // hid the graph for every check after this one (2026-10-07: G-94 read a
    // 0x0 canvas, G-107 picked 0 of 10).
    const bleafFresh = gFresh ? app.workspace.createLeafBySplit(gFresh, "vertical") : app.workspace.getLeaf("tab");
    await bleafFresh.setViewState({ type: "vertiscope-browser-view", active: true });
    app.workspace.revealLeaf(bleafFresh);
    await sleep(1800);
    // A leaf in a background tab hands back a DEFERRED stub with none of
    // the view's methods on it. Fronting the projector backgrounds the
    // browser cell, so this has to be forced before .view is read --
    // otherwise b.webview is undefined and it reads as no browser pane.
    for (const l of app.workspace.getLeavesOfType("vertiscope-browser-view")) {
      if (l.loadIfDeferred) await l.loadIfDeferred();
    }
    for (const l of app.workspace.getLeavesOfType("vertiscope-graph-view")) {
      if (l.loadIfDeferred) await l.loadIfDeferred();
    }
    const bv = app.workspace.getLeavesOfType("vertiscope-browser-view")[0];
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
    for (const l of app.workspace.getLeavesOfType("vertiscope-chunk-view")) {
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
    for (const l of app.workspace.getLeavesOfType("vertiscope-chunk-view")) {
      l.detach();
    }
    for (const l of app.workspace.getLeavesOfType("vertiscope-browser-view")) {
      l.detach();
    }
    await sleep(700);
    const gFresh = app.workspace.getLeavesOfType("vertiscope-graph-view")[0];
    // A SPLIT of the graph, not a tab beside it: a tab in the graph's group
    // hid the graph for every check after this one (2026-10-07: G-94 read a
    // 0x0 canvas, G-107 picked 0 of 10).
    const bleafFresh = gFresh ? app.workspace.createLeafBySplit(gFresh, "vertical") : app.workspace.getLeaf("tab");
    await bleafFresh.setViewState({ type: "vertiscope-browser-view", active: true });
    app.workspace.revealLeaf(bleafFresh);
    await sleep(1500);
    // A leaf in a background tab hands back a DEFERRED stub with none of
    // the view's methods on it. Fronting the projector backgrounds the
    // browser cell, so this has to be forced before .view is read --
    // otherwise b.webview is undefined and it reads as no browser pane.
    for (const l of app.workspace.getLeavesOfType("vertiscope-browser-view")) {
      if (l.loadIfDeferred) await l.loadIfDeferred();
    }
    for (const l of app.workspace.getLeavesOfType("vertiscope-graph-view")) {
      if (l.loadIfDeferred) await l.loadIfDeferred();
    }
    const bv = app.workspace.getLeavesOfType("vertiscope-browser-view")[0];
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
    const gl0 = app.workspace.getLeavesOfType("vertiscope-graph-view")[0];
    const g0 = gl0 && gl0.view;
    // A panel's text as a reader sees it: its own text AND the page
    // snapshot's frame (D-36 draws the chunk as the page does, in a frame).
    const frameText = (root) => [...root.querySelectorAll("iframe.vertiscope-snapshot")].map((f) => {
      try { return f.contentDocument.body.innerText || ""; } catch (e) { return ""; }
    }).join(String.fromCharCode(10));
    const sideText = () => {
      const card = b.markdownWrap.querySelector('.vertiscope-pin-card[data-cid="' + cid + '"]');
      return card ? (card.innerText || card.textContent || "") + String.fromCharCode(10) + frameText(card) : "";
    };
    // The billboard renders into the plugin's OWN shadow root (a
    // .vertiscope-html-host); reading it is not what constraint 6 refuses.
    const boardText = () => {
      const e = g0 && g0.billboards && g0.billboards.get(cid);
      if (!e) return "";
      // The panel's BODY: its header is the chunk's trie address, "url :
      // xpath" (2026-10-06), and the url carries this run's token -- reading
      // the whole element found the token before the click (2026-10-07).
      const body = e.el.querySelector(".vertiscope-bb-body") || e.el;
      const host = body.querySelector(".vertiscope-html-host");
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
    const bleaf = app.workspace.getLeavesOfType("vertiscope-browser-view")[0];
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
    const gl = app.workspace.getLeavesOfType("vertiscope-graph-view")[0];
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
  const SCAN_POINTS = "(function(){var h=window.__vertiscopeSensor;var a=[];for(var y=40;y<innerHeight-30;y+=30)for(var x=40;x<Math.min(innerWidth,760);x+=90){var st=document.elementsFromPoint(x,y),bb=null,ba=Infinity;for(var i=0;i<st.length&&i<12;i++){var c=null;try{c=h.at(st[i]);}catch(e){}if(c&&c.box){var ar=c.box[2]*c.box[3];if(ar>0&&ar<ba){ba=ar;bb=c;}}}if(bb)a.push({x:x,y:y,id:bb.id});}return JSON.stringify(a);})()";
  const PREP = `
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    await window.__vertiscope.act("open", "graph");
    await window.__vertiscope.act("open", "browser");
    for (const l of app.workspace.getLeavesOfType("vertiscope-graph-view")) { if (l.loadIfDeferred) await l.loadIfDeferred(); }
    const bl = app.workspace.getLeavesOfType("vertiscope-browser-view")[0];
    if (bl.loadIfDeferred) await bl.loadIfDeferred();
    app.workspace.revealLeaf(bl);
    // Both panes ON SCREEN: a browser left in the graph's tab group hides the
    // graph, and every check after that measured a 0x0 canvas (2026-10-07).
    {
      const gl0 = app.workspace.getLeavesOfType("vertiscope-graph-view")[0];
      if (gl0 && bl.parent === gl0.parent) {
        for (const l of app.workspace.getLeavesOfType("vertiscope-browser-view")) l.detach();
        app.workspace.revealLeaf(gl0);
        const nl = app.workspace.createLeafBySplit(gl0, "vertical");
        await nl.setViewState({ type: "vertiscope-browser-view", active: true });
        app.workspace.revealLeaf(nl);
        await sleep(1500);
      }
    }
    const bl2 = app.workspace.getLeavesOfType("vertiscope-browser-view")[0];
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
      const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
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
          const pane = app.workspace.getLeavesOfType("vertiscope-panel-view")[0];
          const sel = '.vertiscope-bb[data-cid="' + n.id + '"]';
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
      app.workspace.detachLeavesOfType("vertiscope-panel-view");
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
      "var h = window.__vertiscopeSensor;" +
      "var out = d.log.map(function (b) { var ids = [];" +
      "  b.els.forEach(function (e) { try { var g = h && h.at ? h.at(e) : null; if (g) ids.push(g.id); } catch (x) {} });" +
      "  return { t: b.t, ids: ids }; });" +
      "delete window[" + JSON.stringify(KEY) + "]; return { muts: out, moves: d.moves.slice() }; })()");
    const dropPage = async (KEY) => { try { await b.webview.executeJavaScript("(function(){var d=window[" + JSON.stringify(KEY) + "];if(d){d.mo.disconnect();document.removeEventListener('pointermove',d.pm,{capture:true});delete window[" + JSON.stringify(KEY) + "];}return 1;})()"); } catch (e) {} };
    const matchSeen = (seen, prefix, from, to) => {
      // Open traces too (listAll): a drain still waiting to be seen in 3D
      // has already carried its chunks to the host.
      const P = window.__vertiscopeProfiler;
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
      const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
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
          const base = app.plugins.plugins["vertiscope-bridge"].settings.sidecar.replace(/\\/+$/, "");
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

    for (const l of app.workspace.getLeavesOfType("vertiscope-chunk-view")) {
      l.detach();
    }
    for (const l of app.workspace.getLeavesOfType("vertiscope-browser-view")) {
      l.detach();
    }
    await sleep(700);
    // A split of the graph, never a tab in its group (that hid the graph for
    // every later check, 2026-10-07).
    const gSplit = app.workspace.getLeavesOfType("vertiscope-graph-view")[0];
    const leaf = gSplit ? app.workspace.createLeafBySplit(gSplit, "vertical") : app.workspace.getLeaf("tab");
    await leaf.setViewState({ type: "vertiscope-browser-view", active: true });
    app.workspace.revealLeaf(leaf);
    await sleep(1500);
    const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
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

    for (const l of app.workspace.getLeavesOfType("vertiscope-chunk-view")) {
      l.detach();
    }
    for (const l of app.workspace.getLeavesOfType("vertiscope-browser-view")) {
      l.detach();
    }
    await sleep(700);
    // A split of the graph, never a tab in its group (that hid the graph for
    // every later check, 2026-10-07).
    const gSplit = app.workspace.getLeavesOfType("vertiscope-graph-view")[0];
    const leaf = gSplit ? app.workspace.createLeafBySplit(gSplit, "vertical") : app.workspace.getLeaf("tab");
    await leaf.setViewState({ type: "vertiscope-browser-view", active: true });
    app.workspace.revealLeaf(leaf);
    await sleep(1500);
    const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
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
    const HANDLE = "__vertiscopeSensor";

    for (const l of app.workspace.getLeavesOfType("vertiscope-chunk-view")) {
      l.detach();
    }
    for (const l of app.workspace.getLeavesOfType("vertiscope-browser-view")) {
      l.detach();
    }
    await sleep(700);
    // A split of the graph, never a tab in its group (that hid the graph for
    // every later check, 2026-10-07).
    const gSplit = app.workspace.getLeavesOfType("vertiscope-graph-view")[0];
    const leaf = gSplit ? app.workspace.createLeafBySplit(gSplit, "vertical") : app.workspace.getLeaf("tab");
    await leaf.setViewState({ type: "vertiscope-browser-view", active: true });
    app.workspace.revealLeaf(leaf);
    await sleep(1500);
    const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
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
      await app.commands.executeCommandById("vertiscope-open-graph");
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
      id: "G-102",
      asks: "a billboard does not fake live controls: in the page form of a chunk, a control the trie addresses stays live (it acts on the page), and a control it holds no address for is drawn inert -- dimmed, not-allowed, aria-disabled, with a title saying why; planted (plantInertLooksLive) the dead control looks as pressable as the live one",
      async run() {
        // A newsletter box served locally: a labelled button (a unit, so an
        // address) and an icon-only button with no words (no unit, so no
        // address). Opened from the GRAPH in page form, read in its frame.
        const fixtures = await serveFixtures();
        const arm = (planted) => evaluate(`(async () => {
          ${PREP}
          const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
          const cfg = window.__vertiscopeSnapshotConfig;
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
            const f = e && e.el.querySelector("iframe.vertiscope-snapshot");
            const d = f && f.contentDocument;
            if (!d) { v.closeBillboard(String(node.id)); return { error: "no page form", form: e ? e.form : null }; }
            // The clone keeps no ids: the controls are found by what they show.
            const ctl = [...d.querySelectorAll("button, input, [role=button]")];
            const pick = { "#go": ctl.find((x) => /subscribe/i.test(x.textContent || "")),
                           "#icon": ctl.find((x) => x.tagName === "BUTTON" && !(x.textContent || "").trim() && x.querySelector("svg")),
                           "#email": ctl.find((x) => x.tagName === "INPUT") };
            const read = (sel) => { const el = pick[sel]; if (!el) return null;
              const cs = getComputedStyle(el);
              return { live: !!el.closest("[data-vertiscope-act]"), inert_marked: el.hasAttribute("data-vertiscope-inert"),
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
          const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
          const mode = v.panelsOn;
          b.plant.delete("poll-hover");
          try {
            if (!(await land(${JSON.stringify(PAGE)}, 30000))) return { error: "did not land" };
            await sleep(4000);
            v.setPanelsOn("flyto");
            if (${planted}) b.plant.add("poll-hover");
            const wv = b.webview, r = wv.getBoundingClientRect(), out = [];
            const texty = (e) => { const body = e && e.el && e.el.querySelector(".vertiscope-bb-body"); return !!body && (body.textContent || "").replace(/\\s+/g, " ").trim().length > 20; };
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
              const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
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
            const st = window.__vertiscope.verify.state();
            const gl = app.workspace.getLeavesOfType("vertiscope-graph-view")[0];
            if (gl && gl.loadIfDeferred) await gl.loadIfDeferred();
            const v = gl && gl.view;
            const b = (app.workspace.getLeavesOfType("vertiscope-browser-view")[0] || {}).view;
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
            let second = null, secondGone = null;
            if (at) {
              const was = await count();
              b.webview.focus();
              for (const type of ["mouseDown", "mouseUp"]) b.webview.sendInputEvent({ type, x: at.x, y: at.y, button: "left", clickCount: 1 });
              await sleep(600);
              if ((await count()) === was) await b.webview.executeJavaScript("document.getElementById('add').click(); true");
              mutated = (await count()) > was;
              second = await until(() => mine() > 0, 20000);
              hung = hungFromPage();
              secondGone = await until(() => mine() === 0, 60000);
            }
            try { b.setLive(false); } catch (e) {}
            try { b.go("about:blank"); } catch (e) {}
            await sleep(1500);
            try { b.setLive(true); } catch (e) {}
            const ui = window.__vertiscope.ui();
            return { phases: st.phases || null, label: st.label, mode_at_start,
                     c8: { appeared, collapsed, mutated, second, hung_from_page: hung, second_gone: secondGone },
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
               && got.c8.mutated && got.c8.second && got.c8.second.ok
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
          const b = (app.workspace.getLeavesOfType("vertiscope-browser-view")[0] || {}).view;
          const v = (app.workspace.getLeavesOfType("vertiscope-graph-view")[0] || {}).view;
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
            worst_placed: (window.__vertiscopeProfiler.listAll ? window.__vertiscopeProfiler.listAll() : window.__vertiscopeProfiler.list()).filter((t) => typeof t.stages.overlay_placed === "number")
              .sort((a, c) => c.stages.overlay_placed - a.stages.overlay_placed).slice(0, 3)
              .map((t) => ({ url: t.url.slice(0, 60), chunks: t.facts.chunks_in_drain,
                             stages: Object.fromEntries(["pump_wait", "force_tree", "absorb.covers", "absorb.flash_prep", "overlay_placed", "drain_to_overlay"]
                               .filter((k) => typeof t.stages[k] === "number").map((k) => [k, Math.round(t.stages[k] * 10) / 10])) })),
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
          await window.__vertiscope.act("open", "graph");
          await window.__vertiscope.act("open", "browser");
          const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
          const gl = app.workspace.getLeavesOfType("vertiscope-graph-view")[0];
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
          const KEY = "__vertiscopeCheck" + Math.random().toString(36).slice(2);
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
            const firstDrain = (window.__vertiscopeProfiler.listAll ? window.__vertiscopeProfiler.listAll() : window.__vertiscopeProfiler.list()).filter((t) => t.kind === "live" && t.url === to
              && (t.facts.chunks_in_drain || 0) > 0).map((t) => t.facts.host_epoch).filter(Boolean).sort((a, c) => a - c)[0];
            return { planted: ${planted}, observed, url: wv.getURL(),
                     first_drain_ms: firstDrain ? firstDrain - t0 : -1,
                     capturing_share: busy.length ? Math.round(100 * busy.filter((x) => x[1]).length / busy.length) / 100 : 0,
                     seen: (seen || []).length, answered: m.rows.length, unmapped: m.unmapped, unanswered: m.unanswered,
                     during_capture_ms: { n: during.length, p50: qq(during, 0.5), p95: qq(during, 0.95) },
                     all_ms: { n: m.rows.length, p50: qq(m.rows.map((r) => r.host), 0.5), p95: qq(m.rows.map((r) => r.host), 0.95) },
                     hover_ms: { asked: hovers.length, answered: hv.length, p50: qq(hv, 0.5), p95: qq(hv, 0.95),
                                 split: hoverSplit(hovers, got.moves),
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
          const KEY = "__vertiscopeCheck" + Math.random().toString(36).slice(2);
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
            await sleep(3000);
            const got = await collectPage(KEY) || { muts: [], moves: [] };
            const seen = got.muts;
            const m = matchSeen(seen, "https://discourse.julialang.org/", phases[0], phases[3]);
            const third = (t) => t < phases[1] ? 0 : t < phases[2] ? 1 : 2;
            const host = (k) => m.rows.filter((r) => k === undefined || third(r.t) === k).map((r) => r.host);
            const to3d = m.rows.map((r) => r.to3d).filter((x) => x !== null);
            const ov = m.rows.map((r) => r.overlay).filter((x) => x !== null);
            const hv = (k) => hovers.filter((x) => (k === undefined || x.tag === k) && x.ms !== null).map((x) => x.ms);
            return {
              url: wv.getURL(), frame_ms_p50: Math.round(fr[2]),
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
          const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
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
            const T = (window.__vertiscopeProfiler.listAll ? window.__vertiscopeProfiler.listAll() : window.__vertiscopeProfiler.list()).filter((t) => t.url === url && typeof t.stages.capture_queue_wait === "number");
            const waits = T.map((t) => t.stages.capture_queue_wait);
            const life = v.lifecycleState(url);
            const base = app.plugins.plugins["vertiscope-bridge"].settings.sidecar.replace(/\\/+$/, "");
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
          const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
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
            const flash = (window.__vertiscopeProfiler.listAll ? window.__vertiscopeProfiler.listAll() : window.__vertiscopeProfiler.list()).filter((t) => t.url === target && t.facts.flash).map((t) => t.facts.flash);
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
            // can be open beside the pinned one, and the first .vertiscope-bb in
            // the document was the hover panel (an empty board, 2026-10-07).
            const pinCid = (b.pinnedState()[0] || {}).cid || "";
            const boards = document.querySelectorAll(".vertiscope-bb").length;
            const read = (sel) => {
              const own = sel + '[data-cid="' + pinCid + '"]';
              const f = document.querySelector(own + " iframe.vertiscope-snapshot");
              if (!f || !f.contentDocument) {
                const md = document.querySelector(sel === ".vertiscope-pin-card" ? own + " .vertiscope-browser-mdbody" : own + " .vertiscope-bb-body");
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
            const card = read(".vertiscope-pin-card"), board = read(".vertiscope-bb");
            // A chunk of the open page opened from the GRAPH (not pinned): its
            // billboard asks the browser for the snapshot (2026-09-27: "the 3D
            // gui is not reflecting the same structure of panel as in the
            // clipboard").
            const gv = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
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
          const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
          const P = v.streamParams, saved = { ...P };
          // The spring this replaced: rest 12, pull 0.6, siblings apart inside 8.
          if (${JSON.stringify(plant)} === "legacy") P.LEGACY = true;
          v.plantNoHold = ${JSON.stringify(plant)} === "nohold";
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
          }
        })()`, { timeout: 120000 });
        const clean = await arm("");
        const planted = await arm("legacy");
        const plantedNoHold = await arm("nohold");
        // Spread: the closest tenth of nodes still >= 3 radii from their
        // nearest neighbour (a visible gap), under 5% touching; all translucent.
        const ok = (x) => !!x.best && x.best.nn_p10_in_radii >= 3
          && x.best.overlapping <= x.best.nodes * 0.05 && x.best.translucent === x.best.nodes;
        // Calm: between updates the drawn nodes move under one radius (p90).
        const calm = (x) => !!x.calm && x.calm.updates >= 5 && x.calm.move_p90_in_radii !== null && x.calm.move_p90_in_radii <= 1;
        return { pass: ok(clean) && calm(clean) && !ok(planted) && !calm(plantedNoHold),
                 evidence: { clean, planted_legacy: planted, planted_nohold: plantedNoHold,
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
          const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
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
          const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
          const P = window.__vertiscopeProfiler;
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
          const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
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
          const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
          const g = v.graph;
          const base = app.plugins.plugins["vertiscope-bridge"].settings.sidecar.replace(/\\/+$/, "");
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
          const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
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
            const pts = JSON.parse(await b.webview.executeJavaScript("(function(){var h=window.__vertiscopeSensor;var vw=innerWidth,vh=innerHeight,a=[];for(var y=30;y<vh;y+=40)for(var x=30;x<vw;x+=60){var st=document.elementsFromPoint(x,y),bb=null,ba=Infinity;for(var i=0;i<st.length&&i<12;i++){var c=null;try{c=h.at(st[i]);}catch(e){}if(c&&c.box){var ar=c.box[2]*c.box[3];if(ar>0&&ar<ba){ba=ar;bb=c;}}}if(bb)a.push({x:x,y:y,id:bb.id,frac:ba/(vw*vh)});}return JSON.stringify(a);})()"));
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
                              text: textOf(e.el.querySelector(".vertiscope-bb-body")) } : null;
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
            const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
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
              const f = e && e.el.querySelector("iframe.vertiscope-snapshot");
              const text = f && f.contentDocument ? (f.contentDocument.body.innerText || "") : "";
              const out = { planted: ${planted}, cov, form: e ? e.form : null, saved_form: !!(e && e.savedForm),
                            page_text_has: /Monarch butterflies/.test(text),
                            banners: document.querySelectorAll(".vertiscope-bb-note").length };
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
            const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
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
              const f = e && e.el.querySelector("iframe.vertiscope-snapshot");
              const text = f && f.contentDocument ? (f.contentDocument.body.innerText || "") : "";
              const items = ["Aardvark", "Cassowary", "Hedgehog", "Pangolin", "Tapir"];
              const out = { planted: ${planted}, form: e ? e.form : null, items_shown: items.filter((w) => text.includes(w)).length, of: items.length,
                            complemented: e ? (e.complemented || 0) : 0, banners: document.querySelectorAll(".vertiscope-bb-note, .is-unavailable").length };
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
              const held = xs.length ? JSON.parse(await b.webview.executeJavaScript("(function(xs){var h=window.__vertiscopeSensor;var n=0;for(var i=0;i<xs.length;i++){try{if(h.node(xs[i]))n++;}catch(e){}}return JSON.stringify(n);})(" + JSON.stringify(xs) + ")")) : 0;
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
                const r = JSON.parse(await b.webview.executeJavaScript("(function(x){var n=window.__vertiscopeSensor.node(x);if(n&&n.nodeType===3)n=n.parentElement;if(!n)return 'null';var q=n.getBoundingClientRect();return JSON.stringify({x:q.left+q.width/2,y:q.top+q.height/2});})(" + JSON.stringify(x) + ")"));
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
            const shown = [...b.containerEl.querySelectorAll(".vertiscope-chunk-struct")].filter((el) => el.style.display !== "none" && el.getBoundingClientRect().width > 0).length;
            out.structure = st ? { stored: st.stored, container: st.container, siblings: st.siblings.length, drawn: st.drawn, ms: st.ms } : null;
            out.shown = shown;
            out.hovered_outline = !!(pb.hover && pb.hover.rect);
            out.hovered_stored = pb.hover ? pb.hover.stored || null : null;
            out.by_address = !!(pb.hover && pb.hover.byAddress);
            if (st && st.container) {
              // The container's OWN box on the page, read independently through
              // the sensor's resolver -- each sibling must be embedded in it.
              const cb = JSON.parse(await b.webview.executeJavaScript("(function(x){var n=window.__vertiscopeSensor.node(x);if(n&&n.nodeType===3)n=n.parentElement;if(!n)return 'null';var q=n.getBoundingClientRect();return JSON.stringify({x:q.left,y:q.top,w:q.width,h:q.height});})(" + JSON.stringify(st.container) + ")"));
              out.container_box = cb;
              const inside = (r) => r && cb && r.x >= cb.x - 2 && r.y >= cb.y - 2 && r.x + r.w <= cb.x + cb.w + 2 && r.y + r.h <= cb.y + cb.h + 2;
              out.inside = st.rects.filter((r) => r && inside(r)).length;
              out.measured = st.rects.filter((r) => r).length;
              out.hovered_among = st.siblings.includes(st.stored);
            }
            wc.sendInputEvent({ type: "mouseMove", x: -8, y: -8 });
            wc.sendInputEvent({ type: "mouseLeave", x: -8, y: -8 });
            await sleep(1200);
            out.shown_after_leave = [...b.containerEl.querySelectorAll(".vertiscope-chunk-struct")].filter((el) => el.style.display !== "none").length;
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
          const pl = app.plugins.getPlugin("vertiscope-bridge");
          const g = pl.gesture;
          const path = "vertiscope-checks/R-gesture-" + Date.now() + ".md";
          if (!app.vault.getAbstractFileByPath("vertiscope-checks")) await app.vault.createFolder("vertiscope-checks");
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
            for (let i = 0; i < 240; i++) { await sleep(250); hits = cm.dom.querySelectorAll(".vertiscope-linkgesture .vertiscope-lg-hit"); if (hits.length) break; }
            await sleep(300);
            const box = cm.dom.querySelector(".vertiscope-linkgesture");
            if (!box || !hits.length) return { planted: ${planted}, error: "no results", box: !!box, stats: g.stats };
            const r = box.getBoundingClientRect();
            const b1 = below();
            const lineRect = { top: b1.top, bottom: b1.bottom };
            const covered = r.bottom > lineRect.top + 1 && r.top < lineRect.bottom - 1;
            // More on scroll (G-69's paging, through this one interface).
            const list = box.querySelector(".vertiscope-lg-list");
            const n0 = hits.length, p0 = g.stats.pages;
            list.scrollTop = list.scrollHeight;
            list.dispatchEvent(new Event("scroll"));
            for (let i = 0; i < 160 && g.stats.pages === p0; i++) await sleep(250);
            await sleep(200);
            const n1 = box.querySelectorAll(".vertiscope-lg-hit").length;
            // Read BEFORE the click: an infill closes the block, and a detached
            // list has no height (the first run read "not scrollable" so).
            const scrollable = list.scrollHeight > list.clientHeight + 4;
            // Infill: click the first result.
            const first = box.querySelector(".vertiscope-lg-hit");
            const cid = first.dataset.cid;
            first.click();
            await sleep(300);
            const line2 = cm.state.doc.line(2).text;
            return { planted: ${planted}, query: s0.last && s0.last.query, results: n0, after_scroll: n1,
                     scrollable,
                     block_height: Math.round(r.height), moved_by: Math.round(lineRect.top - top0), covered,
                     line2, infilled: g.stats.infilled - s0.infilled, link: (g.stats.last || {}).dest || "",
                     closed: !cm.dom.querySelector(".vertiscope-linkgesture") };
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
            const dir = app.vault.getAbstractFileByPath("vertiscope-checks");
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
          const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
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
          const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
          for (let i = 0; i < 60 && !(v.graph && v.batch && v.searchField); i++) await sleep(500);
          const f = v.searchField, g = v.graph;
          const stamp0 = window.__vertiscopeReaderAt, after0 = v.idleDriftAfterMs;
          const was = v.onWebSearch; v.onWebSearch = () => {};
          const az = () => { const c = g.camera().position, t = g.controls().target; return Math.atan2(c.z - t.z, c.x - t.x); };
          const turn = (a, b) => { let d = b - a; while (d > Math.PI) d -= 2 * Math.PI; while (d < -Math.PI) d += 2 * Math.PI; return d; };
          const mine = [Date.now() - 60000];
          v.plantDriftStopsOnSearch = ${planted}; v.driftInCheck = true; v.idleDriftAfterMs = 3000;
          try {
            f.input.value = "wikipedia history"; await f.run();
            await sleep(400);
            const standing = !!v.searchState;
            window.__vertiscopeReaderAt = mine[0];
            await sleep(400);
            const a0 = az(), h0 = v.batch.hue;
            await sleep(2500);
            return { planted: ${planted}, standing, turned: turn(a0, az()), hue_moved: v.batch.hue !== h0, active: v.driftStats.active,
                     lights: v.searchStats.lights };
          } finally {
            v.plantDriftStopsOnSearch = false; v.driftInCheck = false; v.idleDriftAfterMs = after0;
            if (mine.includes(window.__vertiscopeReaderAt)) window.__vertiscopeReaderAt = stamp0;
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
          await window.__vertiscope.act("open", "graph");
          const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
          for (let i = 0; i < 60 && !(v.graph && v.batch); i++) await sleep(500);
          const stamp0 = window.__vertiscopeReaderAt;
          const after0 = v.idleDriftAfterMs;
          v.plantNoDrift = ${planted}; v.driftInCheck = true; v.idleDriftAfterMs = 3000;
          const g = v.graph;
          const az = () => { const c = g.camera().position, t = g.controls().target; return Math.atan2(c.z - t.z, c.x - t.x); };
          const turn = (a, b) => { let d = b - a; while (d > Math.PI) d -= 2 * Math.PI; while (d < -Math.PI) d += 2 * Math.PI; return d; };
          const colours = () => g.graphData().nodes.slice(0, 400).map((n) => n.color).join("|");
          const dist = () => { const c = g.camera().position, t = g.controls().target; return Math.hypot(c.x - t.x, c.y - t.y, c.z - t.z); };
          const mine = [Date.now() - 60000];
          try {
            window.__vertiscopeReaderAt = mine[0];
            await sleep(500);
            const a0 = az(), c0 = colours(), d0 = dist();
            await sleep(3000);
            const idle = { turned: turn(a0, az()), hue: v.batch.hue, active: v.driftStats.active,
                           glass_hue: v.batch.glass.mesh.material.uniforms.uHue.value,
                           colours_written: colours() !== c0, distance_kept: Math.abs(dist() - d0) < 0.01 * d0 };
            mine.push(Date.now()); window.__vertiscopeReaderAt = mine[1];   // the reader acts
            await sleep(200);
            const a1 = az();
            await sleep(1500);
            const acted = { turned: turn(a1, az()), hue: v.batch.hue, active: v.driftStats.active };
            return { planted: ${planted}, idle, acted };
          } finally {
            v.plantNoDrift = false; v.driftInCheck = false; v.idleDriftAfterMs = after0;
            // Put back only a stamp this check wrote: a real input meanwhile stays.
            if (mine.includes(window.__vertiscopeReaderAt)) window.__vertiscopeReaderAt = stamp0;
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
          await window.__vertiscope.act("open", "graph");
          const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
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
          await window.__vertiscope.act("open", "graph");
          const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
          for (let i = 0; i < 60 && !(v.graph && v.searchField); i++) await sleep(500);
          const f = v.searchField;
          if (!f) return { error: "no search field" };
          // In CHUNK view: every result is its own drawn node there. In the url
          // view a closed page's chunks are not drawn, so its results light the
          // page node once (G-167) -- not what this check asks.
          const unit = [...v.containerEl.querySelectorAll(".vertiscope-graph-bar button")].find((b) => /^(pages|chunks)$/.test(b.textContent.trim()));
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
          const bv = app.workspace.getLeavesOfType("vertiscope-browser-view")[0]?.view;
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
                           count_text: f.el.querySelector(".vertiscope-search3d-count").innerText.replace(/\\s+/g, " ").trim(),
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
          await window.__vertiscope.act("open", "graph");
          const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
          for (let i = 0; i < 60 && !(v.graph && v.searchField); i++) await sleep(500);
          const f = v.searchField;
          const bv = app.workspace.getLeavesOfType("vertiscope-browser-view")[0]?.view;
          if (bv) bv.plantNoWebSearch = true;
          const unit = [...v.containerEl.querySelectorAll(".vertiscope-graph-bar button")].find((b) => /^(pages|chunks)$/.test(b.textContent.trim()));
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
          await window.__vertiscope.act("open", "graph");
          const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
          for (let i = 0; i < 60 && !v.graph; i++) await sleep(500);
          const unit = [...v.containerEl.querySelectorAll(".vertiscope-graph-bar button")].find((b) => /^(pages|chunks)$/.test(b.textContent.trim()));
          const start = v.level;
          const chunkView = () => v.level === "chunk" && v.umapOnly && v.graph && v.graph.graphData().nodes.length > 2000;
          if (!chunkView() && unit) { unit.click(); for (let i = 0; i < 240 && !chunkView(); i++) await sleep(500); }
          if (!chunkView()) return { error: "chunk view did not arrive", level: v.level };
          v.plantNoChunkRelax = ${planted};
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
          const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
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
          const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
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
          const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
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
          await window.__vertiscope.act("open", "graph");
          const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
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
            const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
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
                const vis = window.__vertiscope.profile.visits().slice(-1)[0];
                if (vis && vis.marks.stored !== undefined && performance.now() - t0 > 12000) break;
              }
              wc.sendInputEvent({ type: "mouseMove", x: -8, y: -8 }); wc.sendInputEvent({ type: "mouseLeave", x: -8, y: -8 });
              const vis = window.__vertiscope.profile.visits().find((x) => x.url === PAGE) || null;
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
                  const stEl = box && box.el.querySelector(".vertiscope-profile-stages");
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
          await window.__vertiscope.act("open", "graph");
          const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
          for (let i = 0; i < 60 && !v.graph; i++) await sleep(500);
          const unit = [...v.containerEl.querySelectorAll(".vertiscope-graph-bar button")].find((b) => /^(pages|chunks)$/.test(b.textContent.trim()));
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
              const rc = new window.__vertiscopeRaycaster();
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
          await window.__vertiscope.act("open", "graph");
          const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
          for (let i = 0; i < 60 && !v.graph; i++) await sleep(500);
          const unit = [...v.containerEl.querySelectorAll(".vertiscope-graph-bar button")].find((b) => /^(pages|chunks)$/.test(b.textContent.trim()));
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
            const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
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
            const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
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
              const pts = JSON.parse(await b.webview.executeJavaScript("(function(){var h=window.__vertiscopeSensor;var a=[];for(var y=40;y<innerHeight-30;y+=30)for(var x=40;x<Math.min(innerWidth,760);x+=90){var st=document.elementsFromPoint(x,y),bb=null,ba=Infinity;for(var i=0;i<st.length&&i<12;i++){var c=null;try{c=h.at(st[i]);}catch(e){}if(c&&c.box){var ar=c.box[2]*c.box[3];if(ar>0&&ar<ba){ba=ar;bb=c;}}}if(bb)a.push({x:x,y:y,id:bb.id});}return JSON.stringify(a);})()"));
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
            const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
            const wc = window.require("@electron/remote").webContents.fromId(b.webview.getWebContentsId());
            v.plantAlwaysZoom = ${planted};
            try {
              try { b.setLive(true); } catch (e) {}
              await land(PAGE, 30000);
              for (let i = 0; i < 90 && !(b.pipebox.map.url === PAGE && b.pipebox.map.chunks > 0); i++) await sleep(500);
              await b.webview.executeJavaScript("window.scrollTo(0,0); 1");
              await sleep(600);
              const pts = JSON.parse(await b.webview.executeJavaScript("(function(){var h=window.__vertiscopeSensor;var a=[];for(var y=40;y<innerHeight-30;y+=30)for(var x=40;x<Math.min(innerWidth,760);x+=90){var st=document.elementsFromPoint(x,y),bb=null,ba=Infinity;for(var i=0;i<st.length&&i<12;i++){var c=null;try{c=h.at(st[i]);}catch(e){}if(c&&c.box){var ar=c.box[2]*c.box[3];if(ar>0&&ar<ba){ba=ar;bb=c;}}}if(bb)a.push({x:x,y:y,id:bb.id});}return JSON.stringify(a);})()"));
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
            const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
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
            const f = e && e.el.querySelector("iframe.vertiscope-snapshot");
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
            const v = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
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
          const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
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
              const drawn = synced ? synced.opaque + synced.translucent : null;
              const streaming = d.nodes.filter((n) => n.force).length;
              // Demand 4: what is drawn is what collides -- the application's
              // own drawnRadius against the size the renderer drew.
              let sized = 0, off = 0;
              for (const n of d.nodes.filter((n) => !n.force && Number.isFinite(n.x)).slice(0, 800)) {
                const a = v.drawnAs(n), r = v.drawnRadiusOf(n);
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
          const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
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
          const v = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
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
            const bb = v.containerEl.querySelector('.vertiscope-bb[data-cid="' + node.id + '"]');
            const frame = bb && bb.querySelector("iframe.vertiscope-snapshot");
            const fdoc = frame && frame.contentDocument;
            const root = fdoc ? fdoc.body : (bb && bb.querySelector(".vertiscope-bb-body"));
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
          await app.commands.executeCommandById("vertiscope-open-browser");
          await app.commands.executeCommandById("vertiscope-open-graph");
          await sleep(2500);
          // A leaf in a background tab hands back a DEFERRED stub with none of
          // the view's methods on it. Fronting the projector backgrounds the
          // browser cell, so this has to be forced before .view is read --
          // otherwise b.webview is undefined and it reads as no browser pane.
          for (const l of app.workspace.getLeavesOfType("vertiscope-browser-view")) {
            if (l.loadIfDeferred) await l.loadIfDeferred();
          }
          for (const l of app.workspace.getLeavesOfType("vertiscope-graph-view")) {
            if (l.loadIfDeferred) await l.loadIfDeferred();
          }
          // Loaded is not the same as USABLE. loadIfDeferred resolves before
          // the guest emits dom-ready, and every webview method then throws
          // "The WebView must be attached to the DOM and the dom-ready event
          // emitted". Poll the cheapest one until it stops throwing.
          for (let i = 0; i < 80; i++) {
            const l0 = app.workspace.getLeavesOfType("vertiscope-browser-view")[0];
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
            const l0 = app.workspace.getLeavesOfType("vertiscope-browser-view")[0];
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
          const gv = app.workspace.getLeavesOfType("vertiscope-graph-view")[0];
          const bv = app.workspace.getLeavesOfType("vertiscope-browser-view")[0];
          const v = gv && gv.view, b = bv && bv.view;
          if (!v || !b) return { error: "panes not open",
                                 types: app.workspace.getLeavesOfType("vertiscope-browser-view").length };
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
          await app.commands.executeCommandById("vertiscope-open-browser");
          await app.commands.executeCommandById("vertiscope-open-graph");
          await sleep(2000);
          // A leaf in a background tab hands back a DEFERRED stub with none of
          // the view's methods on it. Fronting the projector backgrounds the
          // browser cell, so this has to be forced before .view is read --
          // otherwise b.webview is undefined and it reads as no browser pane.
          for (const l of app.workspace.getLeavesOfType("vertiscope-browser-view")) {
            if (l.loadIfDeferred) await l.loadIfDeferred();
          }
          for (const l of app.workspace.getLeavesOfType("vertiscope-graph-view")) {
            if (l.loadIfDeferred) await l.loadIfDeferred();
          }
          // Loaded is not the same as USABLE. loadIfDeferred resolves before
          // the guest emits dom-ready, and every webview method then throws
          // "The WebView must be attached to the DOM and the dom-ready event
          // emitted". Poll the cheapest one until it stops throwing.
          for (let i = 0; i < 80; i++) {
            const l0 = app.workspace.getLeavesOfType("vertiscope-browser-view")[0];
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
            const l0 = app.workspace.getLeavesOfType("vertiscope-browser-view")[0];
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
          const bv = app.workspace.getLeavesOfType("vertiscope-browser-view")[0];
          const gv = app.workspace.getLeavesOfType("vertiscope-graph-view")[0];
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
          const bl = app.workspace.getLeavesOfType("vertiscope-browser-view")[0];
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
            const gv0 = app.workspace.getLeavesOfType("vertiscope-graph-view")[0];
            const g0 = gv0 && gv0.view && gv0.view.graph;
            ringedAtPin = g0 ? g0.graphData().nodes.filter((n) => n.hovered).length : 0;
          }
          await sleep(1200);
          const body = b.markdownWrap.querySelector(".vertiscope-browser-mdbody");
          const head = b.markdownWrap.querySelector(".vertiscope-browser-mdhead");
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
            face_toggle: [...b.containerEl.querySelectorAll(".vertiscope-browser-bar button")]
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
          await app.commands.executeCommandById("vertiscope-open-browser");
          await sleep(1200);
          // A leaf in a background tab hands back a DEFERRED stub with none of
          // the view's methods on it. Fronting the projector backgrounds the
          // browser cell, so this has to be forced before .view is read --
          // otherwise b.webview is undefined and it reads as no browser pane.
          for (const l of app.workspace.getLeavesOfType("vertiscope-browser-view")) {
            if (l.loadIfDeferred) await l.loadIfDeferred();
          }
          for (const l of app.workspace.getLeavesOfType("vertiscope-graph-view")) {
            if (l.loadIfDeferred) await l.loadIfDeferred();
          }
          // Loaded is not the same as USABLE. loadIfDeferred resolves before
          // the guest emits dom-ready, and every webview method then throws
          // "The WebView must be attached to the DOM and the dom-ready event
          // emitted". Poll the cheapest one until it stops throwing.
          for (let i = 0; i < 80; i++) {
            const l0 = app.workspace.getLeavesOfType("vertiscope-browser-view")[0];
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
            const l0 = app.workspace.getLeavesOfType("vertiscope-browser-view")[0];
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
          const bv = app.workspace.getLeavesOfType("vertiscope-browser-view")[0];
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
            "var marks=document.querySelectorAll('[class*=vertiscope],[id*=vertiscope],[data-vertiscope]');" +
            "var styles=Array.prototype.filter.call(document.styleSheets,function(s){" +
            "try{return s.ownerNode && !s.href && /vertiscope/i.test(s.ownerNode.textContent||'');}" +
            "catch(e){return false;}});" +
            "var scripts=Array.prototype.filter.call(document.scripts,function(s){" +
            "return /vertiscope/i.test(s.textContent||'')||/vertiscope/i.test(s.src||'');});" +
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
          const stale = Array.from(v.contentEl.querySelectorAll(".vertiscope-bb"));
          for (const el of stale) {
            const x = el.querySelector(".vertiscope-bb-close");
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
            const b = v.contentEl.querySelector(".vertiscope-bb-body");
            if (b && b.childElementCount) break;
          }
          const all = v.contentEl.querySelectorAll(".vertiscope-bb");
          const el = all[all.length - 1];
          if (!el) return { error: "no billboard appeared",
                            open_count: all.length,
                            tracked: v.billboards ? v.billboards.size : null,
                            clicked: String(chunk.id).slice(0, 24) };
          const layer = v.contentEl.querySelector(".vertiscope-bb-layer");
          const body = el.querySelector(".vertiscope-bb-body");
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
          const head = el.querySelector(".vertiscope-bb-head");
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
          el.querySelector(".vertiscope-bb-close").click();
          await sleep(300);
          const gone = !v.contentEl.querySelector(".vertiscope-bb");

          return {
            node: String(chunk.id).slice(0, 24),
            hops_to_a_chunk: hops + 1,
            lines, anchored_off_by_px: offBy,
            in_canvas: !!(layer && layer.parentElement
                          && layer.parentElement.classList.contains("vertiscope-graph-canvas")),
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
        let sameText = 0, differentText = 0;
        const examples = [];
        for (let i = 0; i < sample.length; i++) {
          let best = Infinity, at = -1;
          for (let j = 0; j < sample.length; j++) {
            if (i === j) continue;
            const a = sample[i].pos, b = sample[j].pos;
            const dd = Math.hypot(a[0]-b[0], a[1]-b[1], a[2]-b[2]);
            if (dd < best) { best = dd; at = j; }
          }
          if (Number.isFinite(best)) nn.push(best);
          if (best < 1e-6 && at >= 0) {
            // The SAME text on several pages (a navbox every tree page carries)
            // embeds identically and belongs at one point of the fit; what
            // this guards is DIFFERENT content collapsed together.
            const same = String(sample[i].title || "") === String(sample[at].title || "");
            if (same) sameText++; else differentText++;
            if (examples.length < 4) examples.push([sample[i].url, sample[at].url, String(sample[i].title || "").slice(0, 40), same]);
          }
        }
        nn.sort((a, b) => a - b);
        const p50 = nn[Math.floor(nn.length / 2)];
        const zero = nn.filter((x) => x < 1e-6).length;
        return {
          // A median neighbour distance of ~0 is the clump; exact zeros
          // between DIFFERENT texts are two things drawn as one.
          pass: p50 > 1 && differentText === 0,
          evidence: { sampled: sample.length, nn_p50: +p50.toFixed(3),
                      nn_min: +nn[0].toFixed(3), coincident: zero,
                      coincident_same_text: sameText, coincident_different_text: differentText,
                      examples },
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
          await app.commands.executeCommandById("vertiscope-open-browser");
          await app.commands.executeCommandById("vertiscope-open-graph");
          await sleep(2500);
          // A leaf in a background tab hands back a DEFERRED stub with none of
          // the view's methods on it. Fronting the projector backgrounds the
          // browser cell, so this has to be forced before .view is read --
          // otherwise b.webview is undefined and it reads as no browser pane.
          for (const l of app.workspace.getLeavesOfType("vertiscope-browser-view")) {
            if (l.loadIfDeferred) await l.loadIfDeferred();
          }
          for (const l of app.workspace.getLeavesOfType("vertiscope-graph-view")) {
            if (l.loadIfDeferred) await l.loadIfDeferred();
          }
          // Loaded is not the same as USABLE. loadIfDeferred resolves before
          // the guest emits dom-ready, and every webview method then throws
          // "The WebView must be attached to the DOM and the dom-ready event
          // emitted". Poll the cheapest one until it stops throwing.
          for (let i = 0; i < 80; i++) {
            const l0 = app.workspace.getLeavesOfType("vertiscope-browser-view")[0];
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
            const l0 = app.workspace.getLeavesOfType("vertiscope-browser-view")[0];
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
          const bv = app.workspace.getLeavesOfType("vertiscope-browser-view")[0];
          const gv = app.workspace.getLeavesOfType("vertiscope-graph-view")[0];
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
          await app.commands.executeCommandById("vertiscope-open-browser");
          await sleep(1800);
          // A leaf in a background tab hands back a DEFERRED stub with none of
          // the view's methods on it. Fronting the projector backgrounds the
          // browser cell, so this has to be forced before .view is read --
          // otherwise b.webview is undefined and it reads as no browser pane.
          for (const l of app.workspace.getLeavesOfType("vertiscope-browser-view")) {
            if (l.loadIfDeferred) await l.loadIfDeferred();
          }
          for (const l of app.workspace.getLeavesOfType("vertiscope-graph-view")) {
            if (l.loadIfDeferred) await l.loadIfDeferred();
          }
          // Loaded is not the same as USABLE. loadIfDeferred resolves before
          // the guest emits dom-ready, and every webview method then throws
          // "The WebView must be attached to the DOM and the dom-ready event
          // emitted". Poll the cheapest one until it stops throwing.
          for (let i = 0; i < 80; i++) {
            const l0 = app.workspace.getLeavesOfType("vertiscope-browser-view")[0];
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
            const l0 = app.workspace.getLeavesOfType("vertiscope-browser-view")[0];
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
          const bv = app.workspace.getLeavesOfType("vertiscope-browser-view")[0];
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
            await window.__vertiscope.act("open", "browser");
            const b = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
            const wv = b.webview, root = b.containerEl;
            const bar = root.querySelector(".vertiscope-browser-bar");
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
              const a = root.querySelector(".vertiscope-browser-url");
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
            steps.back = { ms: await settle(() => url() === ${JSON.stringify(A)}), url: url(), address: root.querySelector(".vertiscope-browser-url").value };
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
            const q = root.querySelector(".vertiscope-query");
            q.focus(); q.value = ${JSON.stringify(words)};
            q.dispatchEvent(new Event("input", { bubbles: true }));
            await sleep(1500);
            const hits = () => [...root.querySelectorAll(".vertiscope-hit")];
            const overlay = root.querySelector(".vertiscope-overlay");
            steps.query = { query: q.value, hits: hits().length, overlay_shown: !!overlay && overlay.style.display !== "none" };
            const list = root.querySelector(".vertiscope-overlay-list");
            const n0 = hits().length;
            if (list) { list.scrollTop = list.scrollHeight; list.dispatchEvent(new Event("scroll")); }
            await sleep(1500);
            steps.scroll_more = { before: n0, after: hits().length };
            const scope = [...root.querySelectorAll(".vertiscope-browser-search button")].find((e) => /everywhere|this page/.test(e.textContent));
            scope.click(); await sleep(1500);
            const scopedUrls = [...new Set(hits().map((h) => (h.querySelector(".vertiscope-hit-url") || {}).textContent))];
            steps.scope = { label: scope.textContent, hits: hits().length, urls: scopedUrls.length, only_here: scopedUrls.every((u) => u === url()) };
            scope.click(); await sleep(1200);
            const first = hits()[0];
            const want = first ? (first.querySelector(".vertiscope-hit-url") || {}).textContent : null;
            if (first) first.click();
            steps.hit_click = { want, ms: want ? await settle(() => url() === want) : -1, url: url(), status: b.status.textContent };
            const x = [...root.querySelectorAll(".vertiscope-browser-search button")].find((e) => e.textContent.trim() === "\\u00d7");
            x.click(); await sleep(400);
            steps.clear = { query: q.value, overlay_shown: !!overlay && overlay.style.display !== "none" };
            // G-41: nothing of ours was written into the page.
            steps.nothing_injected = await wv.executeJavaScript("document.querySelectorAll('[class*=vertiscope],[id*=vertiscope]').length === 0");
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
                const card = b.markdownWrap.querySelector('.vertiscope-pin-card[data-cid="' + cid + '"]');
                const f = card && card.querySelector("iframe.vertiscope-snapshot");
                return f && f.contentDocument && f.contentDocument.getElementById("vertiscope-root") ? f : null;
              };
              const doc = () => frameOf().contentDocument;
              const readoutOf = () => { const f = frameOf(); const r = f && f.parentElement.querySelector(".vertiscope-act-readout"); return r ? r.textContent : ""; };
              const control = (act, text) => [...doc().querySelectorAll('[data-vertiscope-act="' + act + '"]')]
                .find((e) => !text || (e.textContent || "").trim() === text);
              const click = (el) => el.dispatchEvent(new (el.ownerDocument.defaultView.MouseEvent)(
                "click", { bubbles: true, cancelable: true }));

              out.card = await until(async () => { const f = frameOf(); return !!f && !!f.contentDocument.querySelector("[data-vertiscope-address]"); }, 25000);
              if (!out.card) return { ...out, error: "no card with addressed elements" };
              const first = frameOf();

              // ---- The card is LINKED to the trie: every addressed element names this page and resolves in it.
              const tagged = [...doc().querySelectorAll("[data-vertiscope-address]")];
              out.tagged = tagged.length;
              out.acts = [...doc().querySelectorAll("[data-vertiscope-act]")].map((e) =>
                e.tagName.toLowerCase() + ":" + e.getAttribute("data-vertiscope-act") + ":" + (e.textContent || "").trim().slice(0, 16));
              out.addresses_on_this_page = tagged.every((e) => e.getAttribute("data-vertiscope-address").split("|")[0] === PAGE);
              const xs = tagged.map((e) => e.getAttribute("data-vertiscope-xpath"));
              const alive = await b.webview.executeJavaScript(
                "(function(xs){var h=window.__vertiscopeSensor;return h&&h.alive?h.alive(xs):null;})(" + JSON.stringify(xs) + ")");
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
                const f = frameOf(); const i = f && f.contentDocument.querySelector('[data-vertiscope-act="type"]');
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
        const token = "vertiscopeprobe" + Date.now().toString(36);
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
        const token = "vertiscopeuniform" + Date.now().toString(36);
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
    // Each drives the running plugin through its own harness (`__vertiscope.act`)
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
          const d = window.__vertiscope;
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
          const d = window.__vertiscope;
          await d.act("open", "graph");
          await d.act("open", "browser");
          await d.act("unpin", "all");
          await d.act("navigate", "https://en.wikipedia.org/wiki/Radix_tree");
          await sleep(4000);
          const view = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
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
            const g0 = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
            if (typeof g0.reload === "function") { await g0.reload(); await sleep(1500); }
            const e0 = g0.billboards && g0.billboards.get(pin.cid);
            survived = { entry: !!e0, in_document: !!e0 && document.contains(e0.el),
                         has_close: !!e0 && !!e0.el.querySelector(".vertiscope-bb-close") };
          }
          // ... and closing it from the GRAPH side lets go of all three.
          let after = null, closed_via = null;
          if (pin) {
            const g = app.workspace.getLeavesOfType("vertiscope-graph-view")[0].view;
            // THIS pin's billboard, not the first one with an x.
            const own = g.billboards && g.billboards.get(pin.cid);
            const x = own && own.el.querySelector(".vertiscope-bb-close");
            closed_via = x ? "own billboard's x" : "no x on its billboard";
            const snap = () => {
              const u = d.ui();
              const own2 = g.billboards && g.billboards.get(pin.cid);
              return { pins: (u.pinned && u.pinned.pins || []).length,
                       card: !!view.markdownWrap.querySelector('.vertiscope-pin-card[data-cid="' + pin.cid + '"]'),
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
            const card = () => view.markdownWrap.querySelector('.vertiscope-pin-card[data-cid="' + pin.cid + '"] .vertiscope-browser-mdbody');
            if (card()) card().click();
            await sleep(1500);
            after.card_click = snap();
            // Minimize collapses it to its title bar; the card expands it again.
            const own3 = g.billboards && g.billboards.get(pin.cid);
            const mn = own3 && own3.el.querySelector(".vertiscope-bb-min");
            if (mn) mn.click();
            await sleep(300);
            after.minimize = snap();
            if (card()) card().click();
            await sleep(800);
            after.card_click_again = snap();
            // The card's own x lets go of all three.
            const cx = view.markdownWrap.querySelector('.vertiscope-pin-card[data-cid="' + pin.cid + '"] .vertiscope-pin-close');
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
          const d = window.__vertiscope;
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
          const host = [...v.containerEl.querySelectorAll(".vertiscope-bb")]
            .map((e) => e.querySelector(".vertiscope-html-host")).find(Boolean);
          const inside = host && host.shadowRoot
            ? host.shadowRoot.querySelectorAll("*").length : (bb ? bb.elements : 0);
          v.closeBillboard(again.id);
          return { node: again.id, billboard: bb, shadow_elements: inside, form: bb ? bb.form : null,
                   chunk_panes: app.workspace.getLeavesOfType("vertiscope-chunk-view").length };
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
          const d = window.__vertiscope;
          await d.act("open", "graph");
          await d.act("open", "browser");
          await d.act("unpin", "all");
          await d.act("navigate", "https://en.wikipedia.org/wiki/Radix_tree");
          await sleep(4000);
          const view = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
          await view.webview.executeJavaScript("window.scrollTo({top:0,behavior:'instant'}); true");
          await sleep(300);
          const pageShown = () => view.browserWrap.offsetWidth > 50 && view.browserWrap.offsetHeight > 50;
          const toggle = () => [...view.containerEl.querySelectorAll(".vertiscope-browser-bar button")]
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
              cards: [...view.markdownWrap.querySelectorAll(".vertiscope-pin-card")].map((c) => c.dataset.cid),
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
          const SIDE = String(app.plugins.getPlugin("vertiscope-bridge").settings.sidecar).replace(/[/]+$/, "");
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
          const x = view.markdownWrap.querySelector('.vertiscope-pin-card[data-cid="' + newest + '"] .vertiscope-pin-close');
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
          const d = window.__vertiscope;
          const base = String(app.plugins.getPlugin("vertiscope-bridge").settings.sidecar || "").replace(/\\/+$/, "");
          await d.act("open", "browser");
          await d.act("navigate", "https://en.wikipedia.org/wiki/Radix_tree");
          const view = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
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
            const o = view.containerEl.querySelector(".vertiscope-chunk-outline");
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
          const g = app.workspace.getLeavesOfType("vertiscope-graph-view")[0];
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
      id: "G-80",
      asks: "hover-first: the hovered chunk jumps the encoder and projector queues, and is traced to the screen",
      async run() {
        const before = await ask("/profile");
        const n0 = (before.focus || []).length;
        const got = await evaluate(`(async () => {
          const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
          const d = window.__vertiscope;
          await d.act("open", "browser");
          await d.act("navigate", "https://en.wikipedia.org/wiki/Trie");
          await sleep(3000);
          const view = app.workspace.getLeavesOfType("vertiscope-browser-view")[0].view;
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
          for (let i = 0; i < 12 && !hover; i++) {
            view.webview.sendInputEvent({ type: "mouseMove", x: at.x, y: at.y });
            await sleep(250);
            hover = view.pipebox && view.pipebox.hover;
          }
          await sleep(1500);
          const traces = d.profile.traces(50).filter((t) => t.kind === "hover");
          return { cid: hover && hover.cid, hover_traces: traces.length,
                   last: traces.slice(-1)[0] || null };
        })()`, { timeout: 90000 });
        const after = await ask("/profile");
        const focus = (after.focus || []).slice(n0);
        return {
          pass: !!got.cid && focus.length > 0 && got.hover_traces > 0,
          evidence: { ...got, focus_calls: focus.length, focus: focus.slice(-3) },
        };
      },
    },
  ];

  return { CHECKS, wakeProjector, tidyFixtures, ask, inPane };
}
