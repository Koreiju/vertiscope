"""Drive the REAL app the way a reader does, on pages new to the store
(2026-10-10, PLUGIN_GOAL items 30-34). Every reading is the app's own state.

It never runs over the reader (G-135, 2026-10-10: it once cycled panels for
minutes while the reader used the app). It marks itself as a stress run so its
own synthetic hovers are not taken for the reader, records the reader's last
input at the start, and every stage and every loop step stops the moment that
stamp moves.

  python practice.py <url> [<url> ...]      -> practice_<host>.json + screenshots
"""
import json, sys, time, re
from pathlib import Path
sys.path.insert(0, r"<home>\Documents\vertiscope")
from vertiscope.obsidian.live import Live

OUT = Path(r"<home>\Documents\vertiscope\build_analytics\practice")
OUT.mkdir(parents=True, exist_ok=True)
L = Live()

PRE = r"""
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const gl = app.workspace.getLeavesOfType("vertiscope-graph-view")[0];
  const bl = app.workspace.getLeavesOfType("vertiscope-browser-view")[0];
  if (gl.loadIfDeferred) await gl.loadIfDeferred();
  if (bl.loadIfDeferred) await bl.loadIfDeferred();
  const v = gl.view, b = bl.view, wv = b.webview;
  const wc = window.require("@electron/remote").webContents.fromId(wv.getWebContentsId());
  const nodesOf = (u) => v.graph.graphData().nodes.filter((n) => n.url === u);
  window.__vertiscopeStressing = true;
  const R0 = %READER0%;
  const readerBack = () => (window.__vertiscopeReaderAt || 0) !== R0;
"""


READER0 = [0]


class ReaderBack(Exception):
    pass


def js(body, timeout=240):
    got = L.evaluate("(async () => {" + PRE.replace("%READER0%", str(READER0[0])) + body + "})()", timeout=timeout)
    if isinstance(got, str) and '"stopped": "reader"' in got.replace('"stopped":"reader"', '"stopped": "reader"'):
        raise ReaderBack()
    return got


def stage_land(url):
    return json.loads(js(r"""
      const URL0 = %s;
      const out = { url: URL0, samples: [] };
      b.plant && b.plant.clear && b.plant.clear();
      try { b.setLive(true); } catch (e) {}
      const d0 = b.pipebox ? (b.pipebox.drains || 0) : 0;
      b.go(URL0);
      const t0 = performance.now();
      while (performance.now() - t0 < 30000) { await sleep(200); try { if (!wv.isLoading() && wv.getURL().startsWith(URL0.split('#')[0])) break; } catch (e) {} }
      out.landed = wv.getURL(); out.load_ms = Math.round(performance.now() - t0);
      const U = b.session || out.landed;
      out.session = U;
      await sleep(2500);
      const vp = JSON.parse(await wv.executeJavaScript("JSON.stringify([innerWidth, innerHeight, scrollY, document.documentElement.scrollHeight])"));
      out.viewport = vp;
      const r = wv.getBoundingClientRect();
      // Real wheel steps down the page, sampling the stream as it arrives.
      for (let i = 0; i < 14; i++) {
        if (readerBack()) return JSON.stringify({ stopped: "reader" });
        wc.sendInputEvent({ type: "mouseWheel", x: Math.round(r.width / 2), y: Math.round(r.height / 2), deltaX: 0, deltaY: -700 });
        await sleep(650);
        const ns = nodesOf(U);
        out.samples.push({ t: Math.round(performance.now() - t0), scrollY: JSON.parse(await wv.executeJavaScript("String(scrollY)")),
                           force: ns.filter((n) => n.force && n.level !== "page" && !n.branch).length,
                           branches: ns.filter((n) => n.branch).length,
                           stored: ns.filter((n) => !n.force && n.level !== "page").length,
                           page_node: ns.some((n) => n.level === "page") });
      }
      out.scrolled_to = out.samples[out.samples.length - 1].scrollY;
      return JSON.stringify(out);
    """ % json.dumps(url), timeout=120))


def stage_store(session, wait_s=90):
    return json.loads(js(r"""
      const U = %s;
      const t0 = performance.now();
      let cids = [], placed = [], stable = 0, last = -1;
      while (performance.now() - t0 < %d * 1000) {
        // G-135: every poll, not once a stage -- this wait ran 90 s blind.
        if (readerBack()) return JSON.stringify({ stopped: "reader" });
        cids = await v.sidecar.pageCids(U).catch(() => []);
        if (cids.length && cids.length === last) stable++; else stable = 0;
        last = cids.length;
        if (stable >= 4) break;
        await sleep(1500);
      }
      if (readerBack()) return JSON.stringify({ stopped: "reader" });
      // Placed by the fit: ask for every stored chunk, and draw what comes back
      // -- once they are PLACEABLE. Stored is not placeable: a chunk needs its
      // vector first, and asking at "the count held" (11 s on a new Axolotl
      // page) placed 0 of 232 that a minute later all placed.
      let got = null;
      const t1 = performance.now();
      while (cids.length && performance.now() - t1 < 120000) {
        if (readerBack()) return JSON.stringify({ stopped: "reader" });
        got = await v.sidecar.place(cids);
        if (got && got.nodes && got.nodes.length >= 0.9 * cids.length) break;
        await sleep(3000);
      }
      if (got && got.nodes && got.nodes.length) v.absorb(got.nodes, got.edges);
      await sleep(3000);
      const all = v.graph.graphData().nodes;
      const pageNodes = all.filter((n) => n.level === "page" && !n.force && Number.isFinite(n.x));
      const own = pageNodes.find((n) => n.url === U);
      const mine = all.filter((n) => n.url === U && !n.force && n.level !== "page" && Number.isFinite(n.x));
      const dist = (a, c) => Math.hypot(a.x - c.x, a.y - c.y, (a.z || 0) - (c.z || 0));
      let nearerOwn = 0; const dOwn = [], dOther = [];
      for (const c of mine) {
        if (!own) break;
        const a = dist(c, own);
        let o = Infinity; for (const p of pageNodes) if (p !== own) o = Math.min(o, dist(c, p));
        dOwn.push(a); dOther.push(o); if (a < o) nearerOwn++;
      }
      const q = (xs, p) => { const s = xs.slice().sort((a, c) => a - c); return s.length ? Math.round(s[Math.floor(p * (s.length - 1))] * 10) / 10 : null; };
      return JSON.stringify({ stored: cids.length, waited_ms: Math.round(performance.now() - t0), placeable_after_ms: Math.round(performance.now() - t1),
        placed_returned: got && got.nodes ? got.nodes.length : 0, drawn_placed: mine.length,
        page_node: !!own, nearer_own_page: nearerOwn,
        d_own_p50: q(dOwn, 0.5), d_own_p90: q(dOwn, 0.9), d_other_p10: q(dOther, 0.1), d_other_p50: q(dOther, 0.5),
        tele: v.teleStats.get(U) || null,
        spread_ratio: (() => { const ns = mine.filter((n) => Number.isFinite(n.fitX)); if (ns.length < 3) return null;
          const rms = (f) => { const c = [0,1,2].map((i) => ns.reduce((a, n) => a + f(n)[i], 0) / ns.length); return Math.sqrt(ns.reduce((a, n) => { const p = f(n); return a + (p[0]-c[0])**2 + (p[1]-c[1])**2 + (p[2]-c[2])**2; }, 0) / ns.length); };
          return Math.round(rms((n) => [n.x, n.y, n.z || 0]) / rms((n) => [n.fitX, n.fitY, n.fitZ || 0]) * 100) / 100; })(),
        centroid_to_page: own && mine.length ? Math.round(Math.hypot(mine.reduce((a,n)=>a+n.x,0)/mine.length - own.x, mine.reduce((a,n)=>a+n.y,0)/mine.length - own.y, mine.reduce((a,n)=>a+(n.z||0),0)/mine.length - (own.z||0))) : null });
    """ % (json.dumps(session), wait_s), timeout=wait_s + 60))


def stage_hover(session):
    return json.loads(js(r"""
      const U = %s;
      const r = wv.getBoundingClientRect();
      const vp = JSON.parse(await wv.executeJavaScript("JSON.stringify([innerWidth, innerHeight])"));
      const out = [];
      const f0 = { ...v.focusStats };
      for (let i = 0; i < 12; i++) {
        if (readerBack()) return JSON.stringify({ stopped: "reader" });
        const x = Math.round(60 + (i * 137) %% Math.max(100, vp[0] - 120));
        const y = Math.round(80 + (i * 211) %% Math.max(100, vp[1] - 160));
        const flown0 = v.focusStats.flown;
        wc.sendInputEvent({ type: "mouseMove", x, y });
        await sleep(30);
        wc.sendInputEvent({ type: "mouseMove", x: x + 2, y: y + 1 });
        await sleep(900);
        const h = b.pipebox.hover;
        const el = b.pipebox.outlineEl || null;
        const hb = [...v.billboards.entries()].find(([id, e]) => e.fromHover);
        let panelText = 0;
        if (hb) {
          const e = hb[1], body = e.el.querySelector(".vertiscope-bb-body");
          const fr = e.el.querySelector("iframe.vertiscope-snapshot");
          panelText = ((body && body.innerText) || "").trim().length;
          try { if (fr && fr.contentDocument) panelText += (fr.contentDocument.body.innerText || "").trim().length; } catch (z) {}
        }
        out.push({ x, y, cid: h ? String(h.cid).slice(-20) : null, source: h ? h.source : null, stored: h ? (h.stored || null) : null,
                   outline_frac: h && h.rect ? Math.round(h.rect.w * h.rect.h / (vp[0] * vp[1]) * 1000) / 1000 : null,
                   outline_in_view: h && h.rect ? (h.rect.x >= -2 && h.rect.y >= -2 && h.rect.x + h.rect.w <= vp[0] + 2) : null,
                   flew: v.focusStats.flown - flown0, focus_last: String(v.focusStats.last || "").slice(-16),
                   panel: hb ? { id: String(hb[0]).slice(-16), form: hb[1].form, text: panelText } : null });
      }
      wc.sendInputEvent({ type: "mouseMove", x: -8, y: -8 });
      wc.sendInputEvent({ type: "mouseLeave", x: -8, y: -8 });
      await sleep(600);
      const stillOpen = [...v.billboards.values()].filter((e) => e.fromHover).length;
      return JSON.stringify({ hovers: out, focus_delta: { asked: v.focusStats.asked - f0.asked, flown: v.focusStats.flown - f0.flown, zoomed: v.focusStats.zoomed - f0.zoomed, kept_zoom: v.focusStats.kept_zoom - f0.kept_zoom }, stored_unit_ms: b.pipebox.storedUnitMs.slice(-10).map(Math.round),
                              hover_panels_open_after_leave: stillOpen });
    """ % json.dumps(session), timeout=120))


def stage_pin(session):
    return json.loads(js(r"""
      const U = %s;
      for (const p of b.pinnedState()) b.unpin(p.cid);
      const vp = JSON.parse(await wv.executeJavaScript("JSON.stringify([innerWidth, innerHeight])"));
      // A point over a chunk with a PICTURE, by the page's own chunking and the
      // store's markdown; else the first chunk with text.
      const pts = JSON.parse(await wv.executeJavaScript("(function(){var h=window.__vertiscopeSensor;var a=[];for(var y=60;y<innerHeight-40;y+=50)for(var x=40;x<innerWidth-40;x+=80){var st=document.elementsFromPoint(x,y),bb=null,ba=Infinity;for(var i=0;i<st.length&&i<12;i++){var c=null;try{c=h.at(st[i]);}catch(e){}if(c&&c.box){var ar=c.box[2]*c.box[3];if(ar>0&&ar<ba){ba=ar;bb=c;}}}if(bb)a.push({x:x,y:y,id:bb.id});}return JSON.stringify(a);})()"));
      let pick = null, fallback = null;
      for (const p of pts) {
        const st = b.storedCidFor("f:" + b.session + "#" + p.id, b.session);
        if (!st) continue;
        const pay = await v.chunkPayload(st);
        const md = pay && pay.lines ? pay.lines.map((l) => l.text).join("\n") : "";
        if (!fallback && md.trim().length > 40) fallback = { ...p, stored: st, image: false };
        if (/!\[/.test(md)) { pick = { ...p, stored: st, image: true }; break; }
      }
      pick = pick || fallback;
      if (!pick) return JSON.stringify({ error: "no point resolves to a stored chunk", points: pts.length });
      // G-135: never press anything once the reader is back.
      if (readerBack()) return JSON.stringify({ stopped: "reader" });
      try { app.workspace.setActiveLeaf(bl, { focus: true }); } catch (e) {}
      wv.focus(); await sleep(300);
      wc.sendInputEvent({ type: "mouseMove", x: pick.x, y: pick.y }); await sleep(400);
      for (let i = 0; i < 2; i++) {
        wc.sendInputEvent({ type: "mouseDown", x: pick.x, y: pick.y, button: "right", clickCount: 1 });
        wc.sendInputEvent({ type: "mouseUp", x: pick.x, y: pick.y, button: "right", clickCount: 1 });
        await sleep(120);
      }
      for (let i = 0; i < 40 && !b.pinnedState().length; i++) { if (readerBack()) return JSON.stringify({ stopped: "reader" }); await sleep(200); }
      const pinned = b.pinnedState();
      const cid = pinned.length ? pinned[0].cid : null;
      // The 3D half arrives once the chunk is placeable (pinChunk retries).
      let board = null;
      for (let i = 0; i < 40 && cid; i++) { if (readerBack()) return JSON.stringify({ stopped: "reader" }); board = v.containerEl.querySelector('.vertiscope-bb[data-cid="' + cid + '"]'); if (board) break; await sleep(250); }
      await sleep(3000);
      const readPanel = (root, mdSel) => {
        if (!root) return null;
        const fr = root.querySelector("iframe.vertiscope-snapshot");
        let text = "", imgs = [];
        try { if (fr && fr.contentDocument) { text = fr.contentDocument.body.innerText || ""; imgs = [...fr.contentDocument.images]; } } catch (z) {}
        if (!text) { const md = root.querySelector(mdSel); text = md ? md.innerText : ""; imgs = md ? [...md.querySelectorAll("img")] : []; }
        return { form: fr ? "page" : "markdown", chars: text.trim().length, images: imgs.length,
                 images_loaded: imgs.filter((i) => i.complete && i.naturalWidth > 0).length, head: text.trim().slice(0, 120) };
      };
      const card = cid ? b.markdownWrap.querySelector('.vertiscope-pin-card[data-cid="' + cid + '"]') : null;
      const node = cid ? v.graph.graphData().nodes.find((n) => n.id === cid) : null;
      return JSON.stringify({ pick, pins: pinned.length, cid, matches_pick: cid === pick.stored,
        card: readPanel(card, ".vertiscope-browser-mdbody"), board: readPanel(board, ".vertiscope-bb-body"),
        board_head: board ? (board.querySelector(".vertiscope-bb-addr") || {}).textContent : null,
        node: node ? { picture: !!(node.image && node.image.src), loaded: !!node.imgLoaded, drawn_as: v.drawnAs(node).kind } : null });
    """ % json.dumps(session), timeout=120))


def stage_panels(session, cap=40):
    return json.loads(js(r"""
      const U = %s;
      for (const p of b.pinnedState()) b.unpin(p.cid);
      for (const bb of v.billboardState()) v.closeBillboard(bb.id);
      const cids = (await v.sidecar.pageCids(U).catch(() => [])).slice(0, %d);
      // What a reader can SEE of a line: a link's text, never its destination.
      // `](dest)` is dropped whatever the label holds -- a footnote nests its
      // brackets (`[[ 33 ]](#cite_note-Bodmer-12)`) and the old pattern let
      // "cite note bodmer" through as words the panel "missed" (Okapi,
      // 2026-10-11: 24 of 40 panels read incomplete on destination words).
      // The same rule as the panel's own complement (graph.ts `words`).
      const words = (t) => String(t || "")
        .replace(/!\[[^\]]*\]\([^)]*\)/g, " ")          // images
        .replace(/\]\([^)]*\)/g, "] ")                  // any destination
        .replace(/<[^>]+>/g, " ").replace(/(?:https?:)?\/\/\S+/g, " ")
        .toLowerCase().match(/[\p{L}\p{N}]{3,}/gu) || [];
      const rows = [];
      for (const cid of cids) {
        if (readerBack()) return JSON.stringify({ stopped: "reader" });
        const pay = await v.chunkPayload(cid);
        const md = pay && pay.lines ? pay.lines.map((l) => l.text).join("\n") : "";
        const want = words(md);
        const mdImgs = (md.match(/!\[[^\]]*\]\(([^)\s]+)/g) || []).length;
        let node = v.graph.graphData().nodes.find((n) => n.id === cid);
        if (!node) { const got = await v.sidecar.place([cid]).catch(() => null); if (got && got.nodes && got.nodes.length) v.absorb(got.nodes, got.edges); node = v.graph.graphData().nodes.find((n) => n.id === cid); }
        if (!node) { rows.push({ cid, md_words: want.length, md_images: mdImgs, error: "not placeable" }); continue; }
        const t0 = performance.now();
        await v.openBillboard(node);
        let text = "", imgs = [], form = "none";
        while (performance.now() - t0 < 6000) {
          await sleep(200);
          const e = v.billboards.get(cid); if (!e) continue;
          const fr = e.el.querySelector("iframe.vertiscope-snapshot");
          text = ""; imgs = [];
          try { if (fr && fr.contentDocument && fr.contentDocument.body) { text = fr.contentDocument.body.innerText || ""; imgs = [...fr.contentDocument.images]; form = "page"; } } catch (z) {}
          if (!text.trim()) { const body = e.el.querySelector(".vertiscope-bb-md, .vertiscope-bb-body"); text = body ? body.innerText : ""; imgs = body ? [...body.querySelectorAll("img")] : []; form = fr ? "page(empty)" : "markdown"; }
          const have = new Set(words(text));
          if (want.length && want.filter((w) => have.has(w)).length / want.length > 0.95 && (imgs.length >= Math.min(1, mdImgs))) break;
        }
        await sleep(400);
        const have = new Set(words(text));
        const missing = want.filter((w) => !have.has(w));
        rows.push({ cid, ms: Math.round(performance.now() - t0), form, md_words: want.length,
                    coverage: want.length ? Math.round((1 - missing.length / want.length) * 1000) / 1000 : null,
                    missing: [...new Set(missing)].slice(0, 8), md_images: mdImgs, panel_images: imgs.length,
                    panel_images_loaded: imgs.filter((i) => i.complete && i.naturalWidth > 0).length,
                    node_picture: !!(node.image && node.image.src), node_drawn_as: v.drawnAs(node).kind, node_img_loaded: !!node.imgLoaded });
        v.closeBillboard(cid);
        await sleep(150);
      }
      return JSON.stringify({ asked: cids.length, rows });
    """ % (json.dumps(session), cap), timeout=cap * 12 + 60))


def projector():
    try:
        return L.get("/projector")
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)}


if __name__ == "__main__":
    idle = L.evaluate("window.__vertiscope.reader.idleMs()") or 0
    if idle < 30000 and "--force" not in sys.argv:
        print("reader active (%d ms) -- not driving the app" % idle); sys.exit(2)
    urls = [u for u in sys.argv[1:] if not u.startswith("--")]
    READER0[0] = int(L.evaluate("window.__vertiscopeReaderAt || 0") or 0)
    try:
      for url in urls:
          host = re.sub(r"[^a-z0-9]+", "_", url.lower())[8:60]
          rec = {"url": url, "at": time.strftime("%Y-%m-%d %H:%M:%S"), "projector_before": {k: projector().get(k) for k in ("epoch", "fitted_chunks", "chunks_now", "queue", "pages", "trained_pages")}}
          print("==", url, flush=True)
          rec["land"] = stage_land(url); print(" land", json.dumps(rec["land"]["samples"][-1]), rec["land"]["landed"], flush=True)
          sess = rec["land"]["session"]
          rec["store"] = stage_store(sess); print(" store", json.dumps(rec["store"]), flush=True)
          rec["shot_graph"] = L.screenshot(str(OUT / ("%s_1_graph.png" % host)))
          rec["hover"] = stage_hover(sess)
          hv = rec["hover"]["hovers"]
          print(" hover", json.dumps({"n": len(hv), "with_cid": sum(1 for h in hv if h["cid"]), "flew": rec["hover"]["focus_delta"], "panels": sum(1 for h in hv if h["panel"]), "panel_text>0": sum(1 for h in hv if h["panel"] and h["panel"]["text"] > 0), "open_after_leave": rec["hover"]["hover_panels_open_after_leave"]}), flush=True)
          rec["pin"] = stage_pin(sess); print(" pin", json.dumps(rec["pin"])[:700], flush=True)
          rec["shot_pin"] = L.screenshot(str(OUT / ("%s_2_pin.png" % host)))
          rec["panels"] = stage_panels(sess)
          rows = rec["panels"]["rows"]
          cov = [r["coverage"] for r in rows if r.get("coverage") is not None]
          withimg = [r for r in rows if r.get("md_images")]
          print(" panels", json.dumps({"asked": rec["panels"]["asked"], "opened": len(cov), "coverage_min": min(cov) if cov else None,
                "full(>=0.98)": sum(1 for c in cov if c >= 0.98), "chunks_with_images": len(withimg),
                "panel_shows_image": sum(1 for r in withimg if r.get("panel_images_loaded", 0) >= 1),
                "node_drawn_as_picture": sum(1 for r in withimg if r.get("node_drawn_as") == "picture")}), flush=True)
          rec["projector_after"] = {k: projector().get(k) for k in ("epoch", "fitted_chunks", "chunks_now", "queue", "pages", "trained_pages", "last_online")}
          (OUT / ("practice_%s.json" % host)).write_text(json.dumps(rec, indent=1, default=str))
    except ReaderBack:
        print("STOPPED: the reader is using the app", flush=True)
    finally:
        L.evaluate("window.__vertiscopeStressing = false")
