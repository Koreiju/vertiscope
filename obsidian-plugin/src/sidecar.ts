/**
 * The client for the vertiscope sidecar.
 *
 * Every method answers `null` rather than throwing when the sidecar is not
 * there. Offline is a supported mode for this plugin, not a failure: the
 * exported notes are complete markdown and a vault has to keep working with
 * no process running and no network. Callers say so on the surface instead of
 * rendering an empty chunk, because an unreachable sidecar and a chunk with
 * nothing in it look identical otherwise, and that is how a dead pipeline
 * goes unnoticed.
 */

import { CaptureResult, ChunkPayload, ChunkPreview, EnactPlan, EnactResult, Health,
         SearchResults, UnfoldResult,
         PlaceResult,
         Interpreters,
         KernelReply, SearchResult, ShellReply } from "./types";

export class Sidecar {
  constructor(private base: () => string) {}

  private url(path: string): string | null {
    const base = this.base().trim().replace(/\/+$/, "");
    return base ? `${base}${path}` : null;
  }

  private async get<T>(path: string): Promise<T | null> {
    const url = this.url(path);
    if (!url) return null;
    // Retried once, and only on a THROWN error.
    //
    // A thrown fetch is a connection that never happened -- refused, reset,
    // the socket gone -- and those are transient here: a vault opens many
    // chunks at once and a burst can outrun the server's listen backlog. One
    // refused connection used to make that surface say "sidecar unreachable"
    // and keep saying it until the note was edited, while every other surface
    // on screen worked. Measured: one refusal in a burst of nine.
    //
    // A RESPONSE that is not ok is not retried. A 404 for a cid the store does
    // not have is an answer, and asking twice makes it no truer.
    for (let attempt = 0; attempt < 2; attempt++) {
      try {
        const res = await fetch(url);
        if (!res.ok) return null;
        return (await res.json()) as T;
      } catch {
        if (attempt === 0) continue;
        return null;
      }
    }
    return null;
  }

  chunk(cid: string): Promise<ChunkPayload | null> {
    return this.get<ChunkPayload>(`/chunk/${encodeURIComponent(cid)}`);
  }

  /** Streamed chunks placed through the fit before the store holds them (`/project`). */
  async project(url: string, items: { id: string; text: string }[]): Promise<any | null> {
    const u = this.url("/project");
    if (!u || !items.length) return null;
    try {
      const res = await fetch(u, { method: "POST", headers: { "Content-Type": "application/json" },
                                   body: JSON.stringify({ url, items }), signal: AbortSignal.timeout(8000) });
      return res.ok ? await res.json() : null;
    } catch {
      return null;
    }
  }

  /** A PDF's bytes (base64), kept and chunked like a page (`/pdf`, G-248). */
  async pdf(url: string, b64: string): Promise<any | null> {
    const u = this.url("/pdf");
    if (!u || !b64) return null;
    try {
      const res = await fetch(u, { method: "POST", headers: { "Content-Type": "application/json" },
                                   body: JSON.stringify({ url, b64 }), signal: AbortSignal.timeout(180000) });
      return await res.json();
    } catch (e) {
      return { error: String(e).slice(0, 120) };
    }
  }

  /** A chunk's page form as SAVED at scan time (`snapshots.py`), or null. */
  savedSnapshot(cid: string): Promise<any | null> {
    return this.get<any>(`/snapshot/${encodeURIComponent(cid)}`);
  }

  /** A picture from the workspace's media store by `sha1(url)` (G-100), or null. */
  async media(key: string): Promise<{ bytes: Uint8Array; type: string } | null> {
    const u = this.url("/media/" + encodeURIComponent(key));
    if (!u) return null;
    try {
      const res = await fetch(u, { signal: AbortSignal.timeout(5000) });
      if (!res.ok) return null;
      const buf = new Uint8Array(await res.arrayBuffer());
      return buf.byteLength ? { bytes: buf, type: (res.headers.get("content-type") || "").split(";")[0] } : null;
    } catch {
      return null;
    }
  }

  /** Save one picture a saved page form draws: its bytes, as the page loaded them. */
  async saveMedia(url: string, data: ArrayBuffer, contentType: string): Promise<any | null> {
    const u = this.url("/media?url=" + encodeURIComponent(url));
    if (!u || !data.byteLength) return null;
    try {
      const res = await fetch(u, { method: "POST", headers: { "Content-Type": contentType || "application/octet-stream" },
                                   body: data, signal: AbortSignal.timeout(30000) });
      return res.ok ? await res.json() : null;
    } catch {
      return null;
    }
  }

  /** What there is to show for `url` with no connection (`G-59`..`G-62`). */
  async offlineInfo(url: string): Promise<any | null> {
    return this.get("/offline?url=" + encodeURIComponent(url));
  }

  /** One offline form of `url`: the saved page's MHTML (as saved, or infilled), or the traced page's HTML. */
  async offlineForm(url: string, which: "saved" | "infilled" | "traced"): Promise<ArrayBuffer | null> {
    const u = this.url(`/offline/${which}?url=` + encodeURIComponent(url));
    if (!u) return null;
    try {
      // Never from the HTTP cache: the store moves under these forms.
      const res = await fetch(u, { cache: "no-store", signal: AbortSignal.timeout(60000) });
      return res.ok ? await res.arrayBuffer() : null;
    } catch {
      return null;
    }
  }

  /** Keep a page as the cell presented it (`G-60`). */
  async saveOfflinePage(url: string, mhtmlB64: string, text: string): Promise<any | null> {
    const u = this.url("/offline?url=" + encodeURIComponent(url));
    if (!u) return null;
    try {
      const res = await fetch(u, { method: "POST", headers: { "Content-Type": "application/json" },
                                   body: JSON.stringify({ mhtml_b64: mhtmlB64, text }),
                                   signal: AbortSignal.timeout(120000) });
      return res.ok ? await res.json() : null;
    } catch {
      return null;
    }
  }

  /** Save page forms taken from the live page: `[{cid, snap}]`. */
  async saveSnapshots(items: { cid: string; snap: any }[]): Promise<any | null> {
    const url = this.url("/snapshots");
    if (!url || !items.length) return null;
    try {
      const res = await fetch(url, { method: "POST", headers: { "Content-Type": "application/json" },
                                     body: JSON.stringify({ items }), signal: AbortSignal.timeout(30000) });
      return res.ok ? await res.json() : null;
    } catch {
      return null;
    }
  }

  /**
   * Where a link to each stored page should land.
   *
   * The rule lives in `export.py` next to the export that established it, so
   * the gesture and the export write the SAME edge for one link rather than
   * two implementations drifting apart.
   */
  links(): Promise<unknown | null> {
    return this.get("/links");
  }

  /**
   * The containment the trie holds among a set of nodes the pane is drawing.
   *
   * Asked for the WHOLE drawn set rather than per arrival, because an edge
   * has two ends and they routinely arrive from different calls: 9,257
   * edges in the store against 99 drawn, with 110 of 189 nodes isolated.
   */
  async edgesAmong(cids: string[], urls: string[] = []) {
    const base = this.base().trim().replace(/\/+$/, "");
    if (!base) return null;
    try {
      const res = await fetch(`${base}/edges`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cids, urls }),
      });
      return (await res.json()) as
        { edges: { source: string; target: string }[]; n: number };
    } catch {
      return null;
    }
  }

  /**
   * The fitted 3D placement. Seconds on a first call, cached after.
   *
   * Fitted in Python, where the vectors, numpy and UMAP already are. A
   * projection fitted twice in two languages is two projections.
   */
  layout(dims = 3, space = "", level = "", refit = false): Promise<unknown | null> {
    // `space=S3` asks for the quaternion embedding (`G-18`). The two fits
    // are a thing to compare rather than a setting to choose once, so the
    // pane can ask for either and the reply says which it got.
    // `level=chunk` asks for every chunk instead of the collapsed page view
    // (`G-53`). Empty means the server's default, which is pages.
    const which = space ? `&space=${encodeURIComponent(space)}` : "";
    const deep = level ? `&level=${encodeURIComponent(level)}` : "";
    // `refit` asks the chunk projector to refit in the background; the reply
    // is still the current picture.
    const again = refit ? "&refit=1" : "";
    return this.get(`/layout?dims=${dims}${which}${deep}${again}`);
  }

  /** Whether the sidecar answers at all, and what it will allow. */
  health(): Promise<Health | null> {
    return this.get<Health>("/health");
  }

  /** The chunk projector: its fit, its queue, what it has placed. */
  async projector(url = ""): Promise<any | null> {
    return this.get("/projector" + (url ? "?url=" + encodeURIComponent(url) : ""));
  }

  /** What the projector placed after `since`, or `reload` on a new fit. */
  async projectorDelta(since: number, epoch: number): Promise<any | null> {
    return this.get(`/projector/delta?since=${since}&epoch=${epoch}`);
  }

  /** Where one page is in the pipeline: stored, embedded, windowed, fitted. */
  async pageStatus(url: string): Promise<any | null> {
    return this.get("/page_status?url=" + encodeURIComponent(url));
  }

  /** Every chunk id the store holds for a page. */
  async pageCids(url: string): Promise<string[]> {
    const got: any = await this.get(
      "/page_status?cids=1&url=" + encodeURIComponent(url));
    return (got && Array.isArray(got.cids)) ? got.cids : [];
  }

  /** The sidecar's half of the pipeline profile: its own timing rings. */
  async profile(): Promise<Record<string, any[]> | null> {
    return this.get<Record<string, any[]>>("/profile");
  }

  /** Empty the sidecar's per-run rings (the startup warmup is kept). */
  async resetProfile(): Promise<unknown> {
    return this.get("/profile?reset=1");
  }

  async alive(): Promise<boolean> {
    return (await this.health()) !== null;
  }

  /**
   * Drive the live page. The ONLY write this plugin makes.
   *
   * POST, and deliberately not routed through `get`: that retries once on a
   * thrown error, which is right for reading a chunk and wrong for an action.
   * A press that failed halfway may already have navigated, and pressing
   * again is not the same as pressing once.
   */
  async enact(address: string, action = "press",
              text?: string): Promise<EnactResult | null> {
    const base = this.base().trim().replace(/\/+$/, "");
    if (!base) return null;
    try {
      const res = await fetch(`${base}/enact`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ address, action, text }),
      });
      return (await res.json()) as EnactResult;
    } catch {
      return null;
    }
  }

  /**
   * Ask whether a panel gesture on a stored address may be carried out in the
   * browser cell -- and on what (`G-111`). Drives NOTHING: the sidecar runs
   * the gates that need no browser (the `--enact` flag, the address being one
   * the trie holds, the refusal set) and answers with the stored `url`,
   * `xpath` and in-page `kind`, or with `{error, refused}`.
   *
   * POST and not retried, for the reason `enact` is not. The answer for a
   * refusal is a 409 body, returned, not thrown: a refusal is the system
   * working and the panel says so.
   */
  async enactPlan(address: string, action: string,
                  text?: string): Promise<EnactPlan | null> {
    const base = this.base().trim().replace(/\/+$/, "");
    if (!base) return null;
    try {
      const res = await fetch(`${base}/enact`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: "plan", address, action, text }),
      });
      return (await res.json()) as EnactPlan;
    } catch {
      return null;
    }
  }

  /**
   * Where the chunker would cut this text (`P-N8`).
   *
   * A POST because the body IS the note: newlines, and tens of kilobytes on a
   * long one, neither of which belongs in a query string. Not retried, not
   * because it acts -- it is a pure function of the text -- but because the
   * caller re-asks on the next idle anyway, and a retry would only delay a
   * mark the reader has already outrun by typing.
   */
  async chunkPreview(text: string, path: string,
                     vault = "vault"): Promise<ChunkPreview | null> {
    const base = this.base().trim().replace(/\/+$/, "");
    if (!base) return null;
    try {
      const res = await fetch(`${base}/chunk_preview`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text, path, vault }),
      });
      if (!res.ok) return null;
      return (await res.json()) as ChunkPreview;
    } catch {
      return null;
    }
  }

  /**
   * The sensor source, read from the one file the Selenium path reads.
   *
   * Fetched rather than bundled on purpose. A copy compiled into the plugin
   * is a SECOND sensor, and the moment the two differ every comparison
   * between a browser-cell capture and a corpus scan measures the drift
   * rather than the page.
   */
  sensor(): Promise<{ source: string } | null> {
    return this.get<{ source: string }>("/sensor");
  }

  /**
   * Ranked chunks for the browser's overlay (`G-63`, `G-69`, `G-70`).
   *
   * A window over a ranked list rather than a top-k: `offset` is what a
   * continuous scroll moves, and `more` says whether the ranking still had
   * something at that depth. `url` scopes to one shadow DOM; `coarse` false
   * ranks a merge group's members instead of the group.
   */
  /** Tier 1 of a tiered search (G-210): the url nodes nearest the query. */
  async searchPages(query: string, k = 12): Promise<{ pages: { url: string; score: number }[]; ms: number } | null> {
    if (!query.trim()) return null;
    return this.get<any>(`/search_pages?${new URLSearchParams({ q: query, k: String(k) }).toString()}`);
  }

  async search(query: string, options: {
    k?: number; offset?: number; url?: string;
    coarse?: boolean; budget?: number;
  } = {}): Promise<SearchResults | null> {
    if (!query.trim()) return null;
    const q = new URLSearchParams({ q: query });
    if (options.k) q.set("k", String(options.k));
    if (options.offset) q.set("offset", String(options.offset));
    if (options.url) q.set("url", options.url);
    if (options.coarse === false) q.set("coarse", "0");
    if (options.budget) q.set("budget", String(options.budget));
    return this.get<SearchResults>(`/search?${q.toString()}`);
  }

  /**
   * One step of unravelling a page's patricia path (`G-54`).
   *
   * A step, not an expansion: the server descends the shared path until it
   * branches and returns the branches, so a 1,173-chunk page opens as 31
   * nodes rather than as 1,173.
   */
  async unfold(url: string, path = "", space = "",
               anchor?: number[], room?: number):
      Promise<UnfoldResult | null> {
    const base = this.base().trim().replace(/\/+$/, "");
    if (!base || !url) return null;
    try {
      const res = await fetch(`${base}/unfold`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        // Which space the pane is drawing. The anchors an unfolding hangs
        // off are per space, and a euclidean page sits nowhere near where
        // the S3 fit puts the same page.
        // `anchor`/`room` carry the territory a RECURSIVE step inherits
        // from the branch that revealed it. Omitted on a first step,
        // where the page's own room is the right answer.
        body: JSON.stringify({ url, path, space, anchor, room }),
      });
      if (!res.ok) return null;
      return (await res.json()) as UnfoldResult;
    } catch {
      return null;
    }
  }

  /**
   * An address on a live page -> the chunk that draws it (`G-39`).
   *
   * The sidecar walks UP from the xpath, so what comes back is the nearest
   * chunk CONTAINING what was pointed at; `ancestors_walked` says how far it
   * had to go. Null on any failure, like every other call here: a browser
   * pane with no sidecar is a browser, not a broken plugin.
   */
  async resolve(url: string, xpath: string): Promise<any | null> {
    const base = this.base().trim().replace(/\/+$/, "");
    if (!base || !xpath) return null;
    try {
      const q = `url=${encodeURIComponent(url)}`
              + `&xpath=${encodeURIComponent(xpath)}`;
      const res = await fetch(`${base}/resolve?${q}`);
      if (!res.ok) return null;
      return await res.json();
    } catch {
      return null;
    }
  }

  /**
   * Where chunks captured after the fit belong in the picture on screen.
   *
   * Read-only: it fits nothing and stores nothing, it asks the existing fit
   * where these points land. `stale` coming back true means the corpus has
   * doubled since that fit and the pane should ask for a real layout.
   */
  /** A code file's CALLS / INHERITS edges, mapped to the nodes that draw them (G-241). */
  async cpgEdges(url: string): Promise<any | null> {
    return this.get("/cpg_edges?url=" + encodeURIComponent(url));
  }

  /** Run a model role (G-262/G-264): returns the job, followed by `modelJob`. */
  async modelRun(body: Record<string, unknown>): Promise<any | null> {
    const base = this.base().trim().replace(/\/+$/, "");
    if (!base) return null;
    try {
      const res = await fetch(`${base}/model_run`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body), signal: AbortSignal.timeout(15000),
      });
      return await res.json();
    } catch { return null; }
  }
  async modelJob(id: string): Promise<any | null> {
    return this.get("/model_job?id=" + encodeURIComponent(id));
  }
  /** A `code://` module's compact code knowledge graph (G-260). */
  async codeKg(url: string): Promise<any | null> {
    return this.get("/code_kg?url=" + encodeURIComponent(url));
  }

  /** Special files a page links to (PLUGIN_GOAL 186k). */
  async files(url: string): Promise<any | null> {
    return this.get("/files?url=" + encodeURIComponent(url));
  }
  /** A file's size and type, asked of its server without fetching it. */
  async fileHead(href: string): Promise<any | null> {
    return this.get("/file_head?href=" + encodeURIComponent(href));
  }
  /** A confirmed download's progress. */
  async downloadStatus(href: string): Promise<any | null> {
    return this.get("/download_status?href=" + encodeURIComponent(href));
  }
  /** Fetch a special file -- sent only after the reader confirmed it in its panel. */
  async download(href: string, kind: string, name: string): Promise<any | null> {
    const base = this.base().trim().replace(/\/+$/, "");
    if (!base) return null;
    try {
      const res = await fetch(`${base}/download`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ href, kind, name, confirmed: true }), signal: AbortSignal.timeout(15000),
      });
      return await res.json();
    } catch { return null; }
  }

  /** The page's element -> chunk map, for the overlay (DESIGN_VII §3). */
  async pageMap(url: string): Promise<any | null> {
    return this.get("/page_map?url=" + encodeURIComponent(url));
  }

  /** Hover-first (`G-80`): move these chunks to the front of the sidecar's
   *  encoder and projector queues. */
  async focus(cids: string[]): Promise<any | null> {
    const base = this.base().trim().replace(/\/+$/, "");
    if (!base || !cids.length) return null;
    try {
      const res = await fetch(`${base}/focus`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cids }),
      });
      return res.ok ? await res.json() : null;
    } catch {
      return null;
    }
  }

  /** Chunk view's drawn places, kept on the chunks (PLUGIN_GOAL 108):
   *  rows of [cid, x, y, z, fit x, fit y, fit z], in the layout's frame. */
  async saveDrawn(rows: (string | number)[][]): Promise<number> {
    const base = this.base().trim().replace(/\/+$/, "");
    if (!base || !rows.length) return 0;
    try {
      const res = await fetch(`${base}/drawn`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ rows }), signal: AbortSignal.timeout(60000),
      });
      if (!res.ok) return 0;
      return Number((await res.json())?.saved || 0);
    } catch { return 0; }
  }

  /** Told once a minute while the reader is idle: the sidecar may compact
   *  its store then (a supervised exit 76 -- `_compact_due`). */
  async maintenance(readerIdleMs: number): Promise<any> {
    const base = this.base().trim().replace(/\/+$/, "");
    if (!base) return null;
    try {
      const res = await fetch(`${base}/maintenance`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ reader_idle_ms: Math.round(readerIdleMs) }), signal: AbortSignal.timeout(10000),
      });
      return res.ok ? await res.json() : null;
    } catch { return null; }
  }

  async place(cids: string[]): Promise<PlaceResult | null> {
    const base = this.base().trim().replace(/\/+$/, "");
    if (!base || !cids.length) return null;
    try {
      // Bounded: a busy store answered never, and every hover that needed a
      // node placed waited on it (2026-10-10). A caller that still wants the
      // node asks again (the pin retries; the next hover re-asks).
      const res = await fetch(`${base}/place`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ cids }),
        signal: AbortSignal.timeout(5000),
      });
      if (!res.ok) return null;
      return (await res.json()) as PlaceResult;
    } catch {
      return null;
    }
  }

  /**
   * Hand the sidecar one drain from the page the browser cell is showing.
   *
   * A session, not a one-shot: the sensor keeps the fold in the page and each
   * drain carries only what changed, so the sidecar holds the decoder state
   * between calls. `settle: true` closes the page out with one complete write
   * from the finished trie.
   *
   * `place: true` asks for the placed nodes in the SAME reply. Fold, store
   * and place are one question per drain, and asking them separately spent a
   * round trip carrying a list of cids the server had just computed.
   *
   * POST and not retried: it writes the workspace, and a half-written page
   * re-sent is not the same as one sent once -- the same reasoning as
   * `enact` and `runCommand`.
   */
  async capture(url: string,
                what: { payload?: unknown; settle?: boolean;
                        restart?: boolean; title?: string;
                        place?: boolean;
                        /** The profiler's trace id, echoed back in the
                         *  reply so a capture can be matched to its drain. */
                        trace?: string },
               ): Promise<CaptureResult | null> {
    const base = this.base().trim().replace(/\/+$/, "");
    if (!base) return null;
    try {
      const res = await fetch(`${base}/capture`, {
        method: "POST",
        // The reader's sidecar takes captures from the plugin only (D-39).
        headers: { "Content-Type": "application/json", "X-Vertiscope-Client": "obsidian-plugin" },
        body: JSON.stringify({ url, ...what }),
      });
      const body = await res.json();
      // `resync`: the sidecar cannot complete this sensor's dictionary (it
      // restarted under the page) and wants everything sent again.
      if (!res.ok) return { error: body.error || `HTTP ${res.status}`, resync: !!body.resync } as
        CaptureResult;
      return body as CaptureResult;
    } catch (e) {
      // Unreachable (down, restarting): said so, so the stream waits and
      // retries instead of reading it as a refusal and dropping the drain.
      return { error: String(e), unreachable: true } as CaptureResult;
    }
  }

  /** What this machine can run. A GET, so the retry in `get` is right here:
   *  discovery is idempotent and a burst can outrun the listen backlog. */
  interpreters(): Promise<Interpreters | null> {
    return this.get<Interpreters>("/interpreters");
  }

  /**
   * Run one command in a pane's shell.
   *
   * POST and not retried, for the reason `enact` is not: a command that failed
   * halfway may already have written a file or pushed a branch, and running it
   * again is not the same as running it once.
   */
  async runCommand(pane: string, command: string,
                   shell = ""): Promise<ShellReply | null> {
    const base = this.base().trim().replace(/\/+$/, "");
    if (!base) return null;
    try {
      const res = await fetch(`${base}/shell`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pane, command, shell }),
      });
      return (await res.json()) as ShellReply;
    } catch {
      return null;
    }
  }

  /**
   * Drop a note's kernel. The next cell starts a fresh one.
   *
   * Called when the note is deleted or renamed, because at that moment the
   * kernel is unreachable: it is keyed by path, and no path reaches it any
   * more. Without this it waits for the LRU while holding an interpreter --
   * the same leak the terminal had until a closed pane began releasing its
   * shell.
   */
  async restartKernel(note: string): Promise<boolean> {
    const base = this.base().trim().replace(/\/+$/, "");
    if (!base) return false;
    try {
      const res = await fetch(`${base}/kernel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note, op: "restart" }),
      });
      return !!(await res.json()).restarted;
    } catch {
      return false;
    }
  }

  /** Drop a pane's shell. The next command starts a fresh one. */
  async restartShell(pane: string): Promise<boolean> {
    const base = this.base().trim().replace(/\/+$/, "");
    if (!base) return false;
    try {
      const res = await fetch(`${base}/shell`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ pane, op: "restart" }),
      });
      return !!(await res.json()).restarted;
    } catch {
      return false;
    }
  }

  /**
   * Run one notebook cell in its note's kernel.
   *
   * POST, and for the same reason `enact` is not routed through `get`: that
   * retries once on a thrown error, which is right for reading a chunk and
   * wrong for an ACTION. A cell that failed halfway may already have written a
   * file or mutated state, and running it again is not the same as running it
   * once.
   *
   * A non-ok response is returned rather than swallowed. The server answers 403
   * when the kernel is off and 400 when the request is wrong, and both carry a
   * `detail` the reader needs -- turning either into `null` would make "not
   * enabled" indistinguishable from "no sidecar".
   */
  async runCell(note: string, code: string,
                lang = "python"): Promise<KernelReply | null> {
    const base = this.base().trim().replace(/\/+$/, "");
    if (!base) return null;
    try {
      const res = await fetch(`${base}/kernel`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ note, code, lang }),
      });
      return (await res.json()) as KernelReply;
    } catch {
      return null;
    }
  }
}
