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
    const bleafFresh = app.workspace.getLeaf("tab");
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
    const bleafFresh = app.workspace.getLeaf("tab");
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
    const sideText = () => {
      const card = b.markdownWrap.querySelector('.domvec-pin-card[data-cid="' + cid + '"]');
      return card ? (card.innerText || card.textContent || "") : "";
    };
    // The billboard renders into the plugin's OWN shadow root (a
    // .domvec-html-host); reading it is not what constraint 6 refuses.
    const boardText = () => {
      const e = g0 && g0.billboards && g0.billboards.get(cid);
      if (!e) return "";
      const host = e.el.querySelector(".domvec-html-host");
      const sr = host && host.shadowRoot;
      return (e.el.textContent || "") + String.fromCharCode(10) + (sr ? (sr.textContent || "") : "");
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
    const leaf = app.workspace.getLeaf("tab");
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
    const leaf = app.workspace.getLeaf("tab");
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
    const leaf = app.workspace.getLeaf("tab");
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
      asks: "right-click puts the markdown beside the page AND rings the node",
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
          // Resolved to an address and produced RENDERED markdown -- not a
          // placeholder and not a blob of source text -- BESIDE the page.
          //
          // The face must NOT switch. This asked for face === "markdown"
          // until 2026-09-26, which is Addendum IV's "switchable second
          // view"; Addendum VII's follow-up replaced that with a side panel
          // ("the browser stays the main surface"), and right-click now pins
          // (G-78) with the page left showing. Scored the old way, a correct
          // app failed with rendered markdown and one ring in its evidence.
          pass: got.face === "browser"
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
          // The cell has two FACES, and an earlier check leaves it on the
          // other one: G-39 ports markdown into the panel, and a click aimed
          // at a webview that is not the face on display lands on nothing.
          // This is the state P-B1 needs, so P-B1 establishes it.
          try { b.show("browser"); } catch (e) {}
          await sleep(500);
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
        const page = fixtures.origin + "/live_mutate.html";
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
               && got.cost_ratio < 2
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
      asks: "right-click pins a chunk: outline on its box, markdown beside the page, billboard in the graph -- closed together",
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
          // ... and closing it from the GRAPH side lets go of all three.
          let after = null;
          if (pin) {
            const g = app.workspace.getLeavesOfType("domvec-graph-view")[0].view;
            const el = [...g.containerEl.querySelectorAll(".domvec-bb")]
              .find((e) => (e.querySelector(".domvec-bb-close")));
            if (el) el.querySelector(".domvec-bb-close").click();
            await sleep(800);
            const u2 = d.ui();
            after = { pins: (u2.pinned && u2.pinned.pins || []).length,
                      billboards: (u2.billboards || []).length,
                      outlines: ((u2.pipebox || {}).pins || []).filter((o) => o.shown).length };
          }
          return { target, pinned, pin, box,
                   webview: [wb.left, wb.top, wb.width, wb.height],
                   outline, billboard: bb || null, card: card || null,
                   side_shown: ui.pinned && ui.pinned.side_shown, after };
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
          off = Math.max(Math.abs(ol - left), Math.abs(ot - top),
                         Math.abs(ol + ow - right), Math.abs(ot + oh - bottom));
        }
        return {
          pass: !!got.pin && got.side_shown === true
             && !!got.card && got.card.rendered_elements > 0
             && !!got.outline && got.outline.shown && off !== null && off <= 3
             && !!got.billboard && got.billboard.fromBrowser && got.billboard.shadow
             && !!got.after && got.after.pins === 0 && got.after.billboards === 0
             && got.after.outlines === 0,
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
            ? host.shadowRoot.querySelectorAll("*").length : 0;
          v.closeBillboard(again.id);
          return { node: again.id, billboard: bb, shadow_elements: inside,
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
          const oracle = await fetch(base + "/page_map?url=" + encodeURIComponent(wv.getURL())).then((r) => r.json());
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
            return { cid: h && h.cid, outline, off };
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
              "return {h:[Math.round(hb.left+10),Math.round(hb.top+hb.height/2)]," +
              "p:[Math.round(q.left+10),Math.round(q.top+Math.min(20,q.height/2))]};})(" + j + ")");
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
                        off: [p.heading.off, p.paragraph.off] })) },
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
          const d = window.__domvec;
          await d.act("open", "browser");
          await d.act("navigate", "https://en.wikipedia.org/wiki/Trie");
          await sleep(3000);
          const view = app.workspace.getLeavesOfType("domvec-browser-view")[0].view;
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
    {
      id: "G-81",
      asks: "a chunk node shows one of its pictures and expands to the whole chunk",
      async run() {
        const got = await inPane(`
          const data = v.graph.graphData();
          const withPic = data.nodes.filter((n) => n.level === "chunk" && n.image);
          if (!withPic.length) return { error: "no chunk node with a picture is drawn",
                                        chunks: data.nodes.filter((n) => n.level === "chunk").length };
          const node = withPic[0];
          const obj = node.__threeObj;
          const sprite = !!obj && (obj.type === "Sprite" || !!(obj.children || []).find((c) => c.type === "Sprite"));
          for (const b of v.billboardState()) v.closeBillboard(b.id);
          await v.openBillboard(node);
          await sleep(3000);
          const host = [...v.containerEl.querySelectorAll(".domvec-bb")]
            .map((e) => e.querySelector(".domvec-html-host")).find(Boolean);
          const root = host && host.shadowRoot;
          const out = { node: node.id, sprite,
                        shadow_elements: root ? root.querySelectorAll("*").length : 0,
                        shadow_images: root ? root.querySelectorAll("img").length : 0 };
          v.closeBillboard(node.id);
          return out;
        `);
        return {
          pass: !got.error && got.sprite && got.shadow_elements > 1,
          evidence: got,
        };
      },
    },
  ];

  return { CHECKS, wakeProjector, tidyFixtures, ask, inPane };
}
