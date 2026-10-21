# Chunk panels: what is there, what acted on pages before, shortest path to interactive

Read-only research, 2026-10-04, branch `feat/plugin-goal-projector` (HEAD 2fcc022). Nothing was run;
every claim is from reading source or `git show`. "UNVERIFIED" marks anything not read directly or not
exercised in the running app.

User requirement under study (docs/PLUGIN_GOAL.md, uncommitted 2026-10-04 addendum, diff +95 lines):
> "Interactive components of our shadow DOM views and panels must be linked to the patricia trie and also
> interface directly with the webpage itself (i.e. clicking a button or link on the chunk opens the browser
> to first navigate and scroll to the chunk and then take the action on the component in-silico that then
> performs the update action/event on the browser)."
It restates an older verbatim in Addendum IV (PLUGIN_GOAL.md ~L650-662): "through the patricia-trie, we can
click on interactive components in the shadow DOM view and see effects in the browser." PRD rows `G-46`,
`G-68` (Open, docs/PLUGIN_PRD.md:243, :265) and `G-102` (Open, :298) are this requirement. PRD :2312 notes
the absence of the trie-to-browser mapping is the one unanswered Addendum IV question.

---

## 1. Current implementation

There are THREE renderings of a chunk panel, and which one the reader sees is decided by a precedence rule.

### 1a. Page snapshot (D-36): sandboxed iframe, markup cloned from the live page. This is what is shown.

- `obsidian-plugin/src/snapshot.ts:47-216` `snapshotScript(xpaths)`: page-side script, run in the webview via
  `wv.executeJavaScript` (browser.ts:776). Clones the chunk's elements (found by `document.evaluate(xpath)`,
  snapshot.ts:91-97, widened to the enclosing block by `flow()` :102) with computed styles inlined (PROPS :50).
- Neutralised here:
  - `DROP` tags (script/style/iframe/object/embed/link/meta/base...) :68; svg stripped of `on*`, `href`, `<a>` :130-145.
  - Controls forced inert: `input/textarea/select/button` get ` disabled` (:172-173); `<form>` becomes `<div>` (:157);
    `<select>` collapses to the selected option (:187-189).
  - Only `http(s):`/`mailto:` hrefs survive (`safe` :71); links keep `href` plus `data-href` (:159).
  - No `id`, `class`, handler or `data-*` copied. **No xpath or address is emitted on any cloned element.**
  - Shadow roots: `kids()` descends into `el.shadowRoot` and slot assignments (:122-129) when cloning, BUT the entry
    lookup `at()` uses `document.evaluate` (:91-97), which cannot spell `#shadow-root` steps, so chunks inside shadow
    trees likely resolve fewer elements than asked (`found` < `asked`; `lastSnapshot` records both, browser.ts:751). UNVERIFIED.
- `snapshot.ts:308-356` `renderSnapshot`: `<iframe sandbox="allow-same-origin">` (no `allow-scripts`) with `srcdoc`.
  The only live behaviour is one capture-phase `click` listener on the frame document (:348-352): `preventDefault()`
  always; if the target is inside `a[data-href]`, calls `opts.onLink(href)`. Nothing else is wired.
- Store: `STORE` Map by cid (snapshot.ts:291), shared by both panels.
- Where used:
  - 3D billboard: `graph.ts:2713-2741` `mountSnapshot` -> `renderSnapshot(body, snap, {maxHeight: 420, onLink: h => this.onNavigate(h)})`.
    `onNavigate` is set to `browser.go(href)` (main.ts:270-273), i.e. a bare navigation to the href. No scroll, no action, no address.
  - Side card: `browser.ts:866-879` (`renderSide`) -> `renderSnapshot(body, snap, {maxHeight: 640, onLink: h => this.go(h)})`.
    The markdown is tucked under `<details class="vertiscope-pin-md">` and rendered by `MarkdownRenderer.render` (:876).

### 1b. ChunkSurface shadow DOM (distilled HTML from the sidecar): the only form that carries addresses

- `obsidian-plugin/src/surface.ts:130-593` `ChunkSurface extends MarkdownRenderChild`.
  - `drawInteractive` (:403) prefers `payload.html` (from the sidecar) -> `drawDistilledHtml` (:215): `host.attachShadow({mode:"open"})`
    (:241), a private stylesheet `SHADOW_CSS` (:30-114), `holder.innerHTML = markup` (:247). Falls back to line-by-line
    DOM (:413-422) for a sidecar that sent no html.
  - `wireDistilled` (:260-308): strips `<img>` when `loadRemoteMedia` is off (:261-273); for every
    `[data-vertiscope-address]` that is a control (`button,input,a,fieldset,select,option` or contains one, :280-282) it
    - removes `disabled` and adds `.vertiscope-live` ONLY if `host.canEnact()` (:275-297),
    - attaches `click` -> `preventDefault; stopPropagation` (:298-306); live -> `pressAddress(key,label)`, else prints
      `"<class>  <key>"` into a readout (:305).
  - `pressAddress` (:320) -> `host.enact(key, "press")` -> `Sidecar.enact` -> `POST /enact` (sidecar.ts:161-173). Result
    shown as text in `.vertiscope-readout` (:526-531). **Press only: no `type`, no choose/toggle.** `<input>` text fields get a click
    handler that presses, they cannot be filled.
  - Merged-group view (:180-194) is plain `<pre>` with no addresses, deliberately.
- Sidecar side: `vertiscope/obsidian/htmlform.py` builds the HTML from the very `lines` that `chunk_payload` returns.
  - Closed tag whitelist, all text escaped, no page attribute copied, `_safe_url` http/https/mailto/site-relative (htmlform.py:1-45, :79).
  - `_address_attrs` (:282-311): `data-vertiscope-address` = `control_key` else `key` (the control's own address, e.g. an anchor's
    `interactive.links` address that the render suppresses), `data-vertiscope-line` = the line's own key if different,
    `data-vertiscope-shape`, `data-vertiscope-also`.
  - `_control` (:913-952): `<button class="dv-b" disabled>`, `<input type=text|checkbox disabled>`, `<fieldset>` for forms.
    `_listbox` (:739-764): real `<select disabled>` with per-option addresses.
  - `/chunk/<cid>` route attaches `payload["html"] = render_lines(...)` (sidecar.py:1507-1520); `chunk_payload` (sidecar.py:401-)
    gives every line `{text,key,cls,control,shape,target,control_key}` (control_key via `addresses_at`, :433-466).
    Address key format `url|xpath|taxonomy|accessor` (htmlform.py:314-325).
- Where used:
  - 3D billboard: `graph.ts:2054-2058` only when no snapshot exists (offline, or the chunk's page is not the one open
    in the cell), or through the billboard header toggle (`graph.ts:2719-2738`, label flips "md"/"page"; the "md" label
    actually leads to the ChunkSurface shadow DOM, not to markdown, which is confusing).
  - `refreshBillboards` (graph.ts:2748-2762) redraws it on capture.
  - Notes: `main.ts:575` code-block fence `ChunkSurface(el, cid, this)`.
  - `obsidian-plugin/src/chunkview.ts` also constructs one (:108); it is apparently dead (no `registerView` in main.ts; PRD G-77 says the
    chunk pane is gone). UNVERIFIED (only grep).

So the user's observation "shadow DOM is not interactive" is explained by two facts, both read in source:
1. The billboard MOUNTS THE SNAPSHOT FIRST (graph.ts:2047-2054). The snapshot has no addresses and disabled controls. The
   address-carrying ChunkSurface appears only as fallback.
2. Even in ChunkSurface, "live" means `POST /enact`, which drives a separate headless Selenium Firefox (section 2), not the
   Electron browser cell the reader is looking at.

### 1c. Markdown (native Obsidian render)

- `browser.ts:880-883`: `MarkdownRenderer.render(this.app, pin.markdown, body, ...)` when no snapshot. `readPin` (browser.ts:1078-1122)
  fetches `/resolve`, drops form-action lines, and absolutises relative link/image targets against the page. Link clicks are
  ordinary Obsidian link clicks; `card.onclick` explicitly ignores `a` (:854). Addresses are not in the DOM.
- `surface.ts:533-538` `drawMarkdown`: `<pre><code>` of line text.

### 1d. Pin / open plumbing (all keyed by cid and xpath)

- `browser.ts:1044-1064` `portMarkdown(x,y)`: in-page `elementFromPoint` -> xpath built as `tag[i]` by same-tag element siblings, **no
  `#shadow-root` steps, no `*[@id=...]` anchors** -> `pinXpath`.
- `browser.ts:1151-1180` `pinXpath(xpath)`: `readPin` (-> `sidecar.resolve(url,xpath)`, sidecar.ts:276, `/resolve` walks UP ancestors,
  sidecar.py ~1911+) -> `takeSnapshot` -> `pinned` map -> `renderSide` -> `keepInView(read.matched)` -> `onHover(cid,url)` + `onPin(cid)`.
- `main.ts:262-270`: `browser.onPin = cid => graph.pinChunk(cid)`; `graph.ts:2790-2801` `pinChunk` places the node if absent then
  `openBillboard(node, true)` (graph.ts:1964-2059). `openBillboard` sets `entry.surface` or `entry.snapshot`, header drag/min/close.
- `browser.ts:809-820` `snapshotChunk(cid,url)`: for a billboard opened from the 3D view; only works if the cell's current URL
  `docKey`-equals the chunk's url (:813); fetches `/chunk/<cid>` for the xpaths (`xpathsOfLines`, snapshot.ts:219-226).
- `browser.ts:729-741` `keepInView(xpath)` and `browser.ts:993-1030` `reveal(url,xpath)` / `goToHit(hit)`: navigate if
  `wv.getURL() !== hit.url` (polls `isLoading()` up to ~16s), then `document.evaluate(xpath)` + `scrollIntoView({block:"center"})`
  via `executeJavaScript`. `main.ts:185-193` wires `graph.onReveal -> browser.reveal` (G-40, clicking a node in 3D).
- `graph.ts:3588` node click calls `openBillboard(n)`.

### 1e. Sidecar routes (vertiscope/obsidian/sidecar.py)

`GET /chunk/<cid>` (:1507, md lines+addresses+html), `GET /resolve?url&xpath` (xpath -> chunk, ancestor walk), `GET /addresses`
(:1910, xpaths of a page), `GET /health` (advertises `enact`, `capture`, `kernel`, :1492-1500), `POST /enact` (:933-975, gated),
`POST /capture` (gated by `--capture`), `POST /kernel`, `/shell`. No route serves snapshot HTML; snapshots are produced entirely
client-side (snapshotScript) and held in memory per app session (snapshot.ts:291), not persisted.

---

## 2. Earlier iterations of acting on a page

Timeline (commit shas verified via `git show`):

| sha | date | what |
|---|---|---|
| 74ac210 | 2026-08-24 | "stage 5: action chains, in the page": `sensor.js` `perform(chain)` + `resolvePath`; `Sensing.press/fill/toggle/choose/hover` (vertiscope/sensing.py:717-736). Quote: "Enactment was Selenium's: find_element(By.XPATH, ...)... The selector engine stops at a shadow boundary, so every control inside a custom element was unreachable". Chains resolve targets through the composed tree, events carry `composed: true`, value writes use the prototype setter. "One dispatcher, no second path." |
| 9c7871b | 2026-08-24 | REPL made drivable end to end; `press <name>` searches controls only, `hover`. |
| 5d8ae8f | 2026-08-24 | stage 6: "one bar"; `walk` presses the last *button*. |
| 206a66d | 2026-08-27 | "repl: the browser, and only the browser". Removed 13 of 35 commands (coverage walk enact fidelity ...), 3,905 -> 1,771 lines; "Twenty-two commands remain and every one of them is something a reader does to a page". The `enact` REPL check moved to `vertiscope/analytics`. "In trie terms: nothing that reads from or writes to the patricia trie was touched." |
| e03c936 / e0aff10 | 2026-08-30/31 | Affordance analytics: score what the REPL DRAWS, not what the fold holds; phantom and missed take different denominators (vertiscope/analytics/affordance.py). |
| 4954618 | 2026-09-05 | The bridge. Sidecar "read-only... Each line with its address key... the address, not just the text, is what lets a click name an element in the real page"; MCP "affordances are reported, never pressed". |
| 3914925 | 2026-09-06 | "the Selenium port, behind four gates": creates `vertiscope/obsidian/enact.py` + `/enact`. |
| f80d4d4 | 2026-09-06 | `htmlform.py`: "An <input> is an <input> because the trie says the element is a control, and every element carries its own url:xpath:taxonomy:content address in data-vertiscope-address." |
| 9a01909 | 2026-09-09 | listbox draws as a real `<select>`; "surface.ts had to learn the element too". |
| 235be6f | 2026-09-26 | Right-click pins a chunk (`G-78`); billboard = ChunkSurface forced interactive, open shadow root (`G-77`). Constraint stated "In trie terms: a pin is a chunk -- a url : xpath span". |
| a0f3a31 | 2026-09-27 | D-36 snapshot.ts: clone of the live page's elements, "controls are cloned DISABLED -- they are not live on their xpaths, and must not pretend to be (G-102)". Distilled form kept as "offline fallback" (billboard "md" toggle). |

### 2a. REPL (vertiscope/repl/app.py, vertiscope/live/__init__.py)

- Python REPL "is the browser": `vertiscope.live` (live/__init__.py:1-30) "The object tree IS the trie ... The markdown carries its
  handles ... A mark names a trie address, the address names an xpath, the xpath names the element".
- `app.py:420-446` `_gesture(kind, address, text)`: click -> `sensor.press(address)`, type -> `sensor.fill(address, text, submit=True)`,
  check -> `sensor.toggle(address)`. This is the **Selenium** `Sensor` (sensing.py), calling the in-page `perform`. Failure ->
  `NavResult(False, ...)` naming `failed` ticks (`refused`, `unresolved`).
- `live.Node.press()` (live/__init__.py:~790-830): `_refuse_check`, `driver.find_element("xpath", ...)`, scrollIntoView, click, falls
  back to following the href if the click is blocked (refusal-checked), `_S.refold()`.
- CLAUDE.md constraint 2: "The REPL is a browser, not a command surface. Interactive elements are fields a reader acts on in
  place... A verb the reader must type is a failure of the map." AFFINE_MAP_GOAL.md:76-78 says the same. The chunk-panel
  requirement is the same rule applied to the Obsidian panel: the field is clicked in place, no `enact` verb.

### 2b. vertiscope/obsidian/enact.py (3914925)

- `enact(workspace, address_key, action, text, allow_navigation=True)`; `ACTIONS = ("press","type","read")` (:41).
- Order of operations (enact.py:60-144): validate action and text -> `ContentAddress.parse` -> `workspace.store.address(address.aid)` must exist
  ("only scanned pages can be enacted on") -> `live._refuse_check` on stored value/href/url BEFORE any driver is acquired -> `live._S.need_driver()`
  -> if browser URL is not the address's page, refusal-check and `driver.get` + `_S.fold` -> `_find(address.xpath)` in the FOLD (not the live DOM)
  -> refusal-check live label -> `target.press()` / `target.type(text)` -> `_report` (ok, did, detail, address, url).
- It acts on **`live._S.driver`**, a headless Selenium Firefox (`live._S.need_driver` -> `build_driver`, live/__init__.py:154-159,
  browser.py:77), booting it if absent. It never touches the Electron `<webview>`. So with `--enact` ON, a ChunkSurface click navigates and clicks
  inside an invisible Firefox. The cell does not move. (This is the half of PRD R-G2 that was "answered the other way": the scan moved into
  Electron (PRD :732 says "There is no remote browser to drive"), but the enact path was never moved with it.)
- Four gates (module docstring :10-31, commit 3914925): (1) server flag; (2) refusal set `live._refuse_check`; (3) address must be one the store
  holds (the trie is the vocabulary of what can be touched); (4) found in the fold, not by a fresh live selector; plus "same page only" navigation, refusal-checked.
  "NOTHING DECIDABLE FROM THE REQUEST ALONE MAY HAVE A SIDE EFFECT."
- Tests: `tests/test_obsidian_enact.py` (refusals, no browser needed), `tests/test_live_refusal.py` (Python copy agrees with sensor.js copy).
  Neither covers the Electron path.

### 2c. Gate: `--enact`

- `vertiscope/obsidian/__main__.py:78-85` flag; `serve(..., enact=...)` -> `enact_allowed` class attr (sidecar.py:626; route gate :945-952 returns 403
  `{"error":"enact is off"}`). Advertised via `/health.enact` (sidecar.py:1492) -> `main.ts:155,307` `serverEnact` -> `SurfaceHost.canEnact()`
  (main.ts:553).
- Side effect: `--enact` or `--capture` forces the writer lock (`read_only = not (enact or capture)`, __main__.py:102). So enabling enact excludes other readers
  (MCP server) unless capture is already on. Capture mode is what the cell uses anyway. UNVERIFIED which flags the user's normal launch has.
- CORS preflight lesson (3914925): POST with `application/json` from `app://obsidian.md` preflights; sidecar had to answer OPTIONS.
- `confirm.mjs` and `checks/live.mjs` hold NO enact check (grep). No live evidence that any panel press ever worked in the running plugin after the Electron move. G-68 and G-46 remain Open.

### 2d. Kernel (vertiscope/obsidian/kernel.py, 641e491)

Not an enactment path. One Python subprocess per note, `POST /kernel`, gated by separate `--kernel` ("a reader who wanted a notebook did not thereby
ask for a vault that can drive the web"). Relevant only as the precedent for separate gates per capability: do NOT widen `--kernel` or reuse it.

### 2e. Affordance analytics and MCP

- `vertiscope/analytics/affordance.py` (e03c936, e0aff10): scores "is what the REPL offers to interact with what the page can be interacted with"; phantom
  (REPL invents a control) vs missed (reader denied something reachable), separate denominators. Relevant to the new work as the non-vacuity framework:
  a panel's clickable elements should be scored as phantom (element in panel with no live counterpart at its address) and missed (control on page not
  clickable in panel).
- `vertiscope/obsidian/mcp.py` `affordances` tool (:300, :530): read-only listing; "affordances are reported, never pressed" (:595). The agent-side
  `mcp__vertiscope__affordances` is the same. `ui_act` is a UI harness (harness.ts), not an enactment of page elements.

### 2f. In-page `perform` is already shipped to the cell and unused there

- The cell injects the sensor as `window.__vertiscopeSensor` (`HANDLE`, browser.ts:60) through `executeJavaScript` (browser.ts:1408-1425) on the first drain of
  each document. Source is fetched from the sidecar (`sidecar.sensor()`). The handle exposes `perform`, `resolve(path)`, `alive(xpaths)`, `at(el)`
  (sensor.js:3105-3142). `grep perform obsidian-plugin/src/browser.ts` finds only `performance.now`; **nothing in the plugin calls `perform`.**
- `perform` tick takes `path: [tag, ordinal, ...]` (sensor.js:2754 `resolvePath`), not an xpath string. `resolveXPath` (sensor.js:2688, composed-tree
  spelling, handles `#shadow-root`, `text()[n]`, `*[@id=...]`) is exposed only through `alive()`. Python converts with `Sensor.path_of` (sensing.py:662-688):
  tiny, pure. No `*[@id=...]` handling in `path_of`. UNVERIFIED whether the trie's re-rooted `*[@id=]` addresses reach `perform` correctly.
- `perform` gates every tick by `refused(el)` (sensor.js:2757; NEVER_LABEL/NEVER_HREF/RISKY_FIELD/dialog[open], :1973-2008): a third copy of the refusal set
  (Python `live._refuse_check` + `sensor.js` + any TS copy would be a fourth; do not write one).
- Events are synthetic (`isTrusted: false`), dispatched with `composed: true`; `click` calls `el.click()` after scrollIntoView+focus (sensor.js:2776-2780). Sites
  that check `isTrusted` will not respond. UNVERIFIED how often this matters; alternative is Electron `webContents.sendInputEvent` / CDP `Input.dispatchMouseEvent` (cdp.mjs exists in obsidian-plugin/, not read).
- Tension to flag: PLUGIN_GOAL addendum says the electron sensor "attempts to completely avoid any detectable injection except for required mutationobservers,
  but with zero contact with the page itself". The sensor already lives in the page main world, so `perform` adds no new injection, but it is the first WRITE-like
  behaviour (events dispatched into page JS). Constraint 7 "Nothing is written into the page" is about DOM writes, and a reader's click is the reader's act, but
  this should be said out loud in the design.

---

## 3. Shortest path: panel click -> trie address -> cell navigates, scrolls, acts

### Chain

```
panel element (click / change / Enter)
  -> its patricia-trie address key  (url|xpath|taxonomy|accessor)            [needs: element carries it]
  -> sidecar adjudication: address in store? refusal set? -> {xpath, url}     [needs: new read-only plan route, gated by --enact]
  -> browser.reveal(url, xpath)  (navigate if elsewhere, scrollIntoView)       [EXISTS: browser.ts:993]
  -> ensure window.__vertiscopeSensor on the (new) document                        [needs: factor out of drain, browser.ts:1408-1425]
  -> sensor.perform({ticks:[{kind:"click"|"type"|..., path}]})  in the webview [EXISTS in sensor.js:2838; path_of port needed]
  -> result {done, failed:[kind, 'refused'|'unresolved'], url} back to the panel
  -> the drain stream carries the page's resulting delta into the trie         [EXISTS, unchanged: O(delta)]
```

### What to reuse (file:line)

| Need | Reuse |
|---|---|
| Element -> address | `htmlform._address_attrs` (htmlform.py:282): `data-vertiscope-address` (control key) and `data-vertiscope-line`. ChunkSurface.wireDistilled (surface.ts:276-307) already iterates them and has the click handler plus `canEnact()` gate plus `labelOf`. |
| Navigate + scroll | `BrowserView.reveal(url, xpath)` / `goToHit` (browser.ts:993-1030); plugin brokers via `onReveal` (main.ts:185). `keepInView` (:729) for re-centering after the side panel reflows. |
| Pin/open | `pinXpath` (browser.ts:1151), `pinChunk` (graph.ts:2790). |
| Gate state | `/health.enact` -> `main.ts serverEnact` -> `SurfaceHost.canEnact()` (main.ts:553); server flag `--enact` (__main__.py:78). |
| Refusal set | `live._refuse_check` (live/__init__.py:93) server-side, plus `refused(el)` inside `perform` (sensor.js:2757). Do not add a TS copy. |
| Address-in-store gate | `workspace.store.address(address.aid)` (enact.py:82), `ContentAddress.parse` (address.py:501). |
| Actuator | `perform` in-page (sensor.js:2838), already injected as `window.__vertiscopeSensor`. |
| Xpath-to-path | `Sensor.path_of` (sensing.py:662); port its ~20 lines to TS, or have the sidecar return the path array. |
| Click-capture in the iframe | `renderSnapshot` already attaches a capture-phase listener to `frame.contentDocument` (snapshot.ts:348), possible because `allow-same-origin` and the parent owns the document; no `allow-scripts` needed. |
| Chunk -> its control addresses | `chunk_payload` `lines[].control_key / key` (sidecar.py:433-466, types.ts ChunkLine). |
| Stale check | `sensor.alive(xpaths)` / `resolve(path)` (sensor.js:3112-3142) to say "page no longer has this" instead of acting. |
| Measurement frame | `vertiscope.analytics` affordance phantom/miss; `harness.ts` `pin`, `click` gestures (harness.ts:360, :507) for non-vacuity checks. |

### What is missing

1. **Address on the snapshot's elements.** snapshot.ts emits no xpath/address. Choose one:
   - (A, smallest) Make the billboard and card use the ChunkSurface/shadow-DOM form (it already carries addresses) and make it page-faithful by styling.
     Regresses D-36 (the user twice said panels must look like the page).
   - (B, recommended) Keep the page-faithful clone and tag it. In `snapshotScript` build a Map `liveElement -> controlKey` from the payload lines (resolve each
     `control_key` xpath to its actual element, NOT the `flow()`-widened block) and emit `data-vertiscope-address="<key>"` on that clone element, and stop
     emitting ` disabled` when the panel is live. Then `renderSnapshot` (snapshot.ts:348) gets `onAct(key, kind, text)`: widen the click handler from `a[data-href]` to
     `closest("[data-vertiscope-address]")`. Needs the payload lines passed in (`snapshotScript(xpaths)` currently receives only xpaths; browser.ts:776 and :818 can
     pass `{xpath,key}` pairs; `xpathsOfLines` snapshot.ts:219 already reads the keys). This satisfies "linked to the patricia trie" literally and matches the
     user's note that the shadow DOM view "may be more apt to direct HTML representations on the distilled chunk samples".
   - Either way shadow-hosted controls need a composed-tree resolver in the clone step (use `__vertiscopeSensor` or port `resolveXPath`); `document.evaluate` will not find them.
2. **Fill / choose / toggle.** `surface.ts` only presses (:320); `ACTIONS` has `type` but no toggle/choose; `perform` supports click, type, check, choose, hover, key, submit (sensor.js:2750+).
   A text input in a panel needs `change`/Enter -> `type`; a `<select>` option -> `choose`; checkbox -> `check`.
3. **An actuator on the cell, not on Selenium.** `POST /enact` drives `live._S.driver` (enact.py:107). Add a read-only adjudication route that runs the same gates
   (action valid, address parse, `store.address(aid)`, `_refuse_check` on stored label/href and on the page URL, returns `{xpath, path, url, label}`)
   and drives nothing. The renderer then does reveal + `perform` in the webview. Keep the `--enact` gate, 403 text and `/health.enact` advertisement. Do NOT let the
   plugin decide permission (enact.py docstring: "a plugin setting cannot be the gate"). Keep the old Selenium `/enact` untouched or retire it deliberately.
4. **`ensureSensor()` in BrowserView.** The handle is only installed inside the drain snippet (browser.ts:1408-1425). After `go()` navigates, `window.__vertiscopeSensor` may not exist
   yet; `perform` needs it. Factor the install into a method and await it after `goToHit`'s load wait. Also wait for `dom-ready` (browser.ts has `domReady`, :801).
5. **Act-after-scroll ordering and result path.** `goToHit` returns void and swallows a missing xpath into a `say()` (browser.ts:1022-1028). Needs a return value
   `{found:boolean}` so the act is skipped when the page no longer has the address, and the result (`done`/`failed`/`url`) routed back to the panel's readout (`ChunkSurface.say` equivalent).
6. **Link semantics.** Today a snapshot link click is `browser.go(href)` (graph.ts:2718, browser.ts:872): it opens the href but does not scroll to the chunk or press the link
   in-page. Under the new rule the click should be the pressed anchor on the live page (SPA routers and `onclick` handlers fire), with `go(href)` only as fallback for an
   unresolved element (mirrors live `Node.press` fallback, live/__init__.py:~810).
7. **Selecting the page.** `snapshotChunk` only works when the cell is already on the chunk's page (browser.ts:813). For billboards of other pages the click path must navigate first; the panel
   is then showing a stale (offline) rendering until a new snapshot is taken after load. Re-snapshot after the act (the drain's `onDirty` -> `refreshPins`, browser.ts:1134, already does this for
   captured changes).
8. **Tests / measurement (per CLAUDE.md "non-vacuity").** None exist for the Electron path. Needed: a planted-defect arm (address that is not in the store; a "Sign in" link must be refused with `failed:refused`
   and the page URL unchanged; stale xpath must say unresolved), a null arm (click with `--enact` off changes nothing), and `confirm.mjs` live check keyed `G-68`, `G-102`. The harness `click`/`pin` gestures
   (harness.ts:360, :507) show the pattern. `test_live_refusal.py` already pins the Python-vs-sensor.js refusal parity.
9. **PRD/docs.** CLAUDE.md requires new direction transcribed into a dated addendum before decomposition. The 2026-10-04 text is in PLUGIN_GOAL.md but uncommitted. G-68, G-46, G-102 are the existing rows.

### Safety gates, summarised

| Gate | Where | Status for the new path |
|---|---|---|
| Server `--enact` flag | `__main__.py:78`, `sidecar.py:626,945`, `/health.enact` | Reuse as-is. The adjudication route must 403 identically when off. |
| Address must be in the store | `enact.py:82` | Reuse; stops any xpath the trie never held. |
| Refusal set (sign-in, checkout, delete, send, consent...) | `live._refuse_check` (:93), sensor.js `refused` (:2003), `perform` tick gate (:2757); parity test `tests/test_live_refusal.py` | Reuse both: server pre-check before navigating (refusal before side effects), in-page gate at press time. |
| Same page / navigation refusal-checked | `enact.py:113-121` | Reuse the URL check in the plan route; the cell's `reveal` itself does not currently refuse-check a URL (browser.ts:993). Add. |
| Fold, not live selector | `enact.py:147-169` | Differs: `perform` resolves against the live composed tree (not the sidecar's Selenium fold). Cheap equivalent: verify `sensor.resolve(path)` and that element's label passes `refused` (already in `perform`). The Selenium fold no longer represents the cell's page. |
| Synthetic events | sensor.js `fire` | Weak against `isTrusted` checks; acceptable for first cut. UNVERIFIED on target sites. |

### Open question for the user (not decided here)

Whether clicks in the panel should always act (when `--enact` is on) or only after an explicit per-panel "live" state, given that the cell is the reader's real logged-in session
(shared `persist:vertiscope` partition, browser.ts:50). The refusal set exists for exactly this, but the old design assumed a disposable headless Firefox. UNVERIFIED relevance.
