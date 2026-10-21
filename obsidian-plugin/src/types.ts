/**
 * The contract between the plugin and the vertiscope sidecar.
 *
 * Kept in one file because it is a contract with a program in another
 * language: `vertiscope/obsidian/sidecar.py` builds exactly these shapes, and a
 * field renamed on one side and not the other fails silently at runtime with
 * an empty surface. Anything added here has to be added there.
 */

/** One line of a chunk, as `chunk_payload` reports it. */
export interface ChunkLine {
  /** The drawn markdown, e.g. `( Add to basket )` or `![images](/a.png)`. */
  text: string;
  /** `url:xpath:taxonomy:content` -- the patricia trie address. */
  key: string;
  /** One of the eighteen render classes: link, button, field, image, text... */
  cls: string;
  /** True when this line is an affordance rather than prose. */
  control: boolean;
  /**
   * The address that NAMES the affordance, when it is not the line's own.
   *
   * An anchor's `interactive.links` address is suppressed by the render, so
   * the line is stored under its `urls.*` or `text.visible` address instead.
   * Enacting needs the control; navigating needs the line. The sidecar
   * reports both rather than making the caller guess which it has.
   */
  control_key?: string;
  /** Resolved href/src, when the address carries one. */
  target?: string;
}

export interface ChunkPayload {
  cid: string;
  url: string;
  xpath: string;
  lines: ChunkLine[];
  /** Addresses the chunk anchors; a short chunk and a misaligned one differ. */
  addresses: number;
  /** The chunk's size in the unit its window was measured in. */
  tokens?: number;
  /** The window it was cut against, so a surface can show fill. */
  window?: number;
  /**
   * The merge group this chunk belongs to, or null (`G-26`, `G-27`).
   *
   * The chunk is still served as ITSELF -- it is what a retrieval hit
   * resolves to and its addresses are its own. The group travels beside it so
   * a surface can offer the merged reading without pretending the parts are
   * gone.
   */
  group?: {
    lead: string;
    members: string[];
    /** This chunk's place in the group, 1-based, for "3 of 8". */
    position: number;
    /** Assembled from the members in document order, never stored. */
    markdown: string;
    /** The merged text's size, counted link-free like everything else. */
    tokens: number;
  } | null;
  /**
   * The same chunk as slim distilled HTML, built by `htmlform.py` from these
   * very lines.
   *
   * It travels WITH the lines rather than behind a second route, so a surface
   * cannot hold a markdown form and an HTML form fetched at different
   * moments -- two renderings of possibly two states. They are one
   * distillation.
   *
   * Every element in it carries `data-vertiscope-address`, so a click maps back
   * through the patricia trie to the element the sensor found. The tag set is
   * a closed whitelist and every text node is escaped on the Python side;
   * this is scraped web content going into a real unsanitised DOM.
   */
  html?: string;
}

export interface SearchHit {
  cid: string;
  url: string;
  score: number;
  /** The first few lines, for the suggestion list. */
  preview: string;
  /** Everything below is present on the overlay's richer payload and absent
   *  on the `/` gesture's, so it is optional rather than a second interface.
   *  Two interfaces of this name MERGE silently in TypeScript, which is how
   *  a second one sat here without an error and made every field of it
   *  mandatory on both surfaces. */
  xpath?: string;
  /** The three ranking factors. Their product lands near 1e-5 and reads as
   *  zero; which of them fired is what says WHY a result ranked. */
  lexical?: number;
  semantic?: number;
  pagerank?: number;
  /** How many chunks the result stands for, when it is a merge group. */
  members?: number;
  tokens?: number;
}

export interface Health {
  ok: boolean;
  pages: number;
  /**
   * Whether the SERVER will drive the live page.
   *
   * Advertised so the surface can draw a read-only chunk as read-only,
   * rather than offering a button that turns out to 403. The plugin does not
   * decide this and must not pretend to: the process that owns the browser
   * does, via `--enact`.
   */
  enact: boolean;
  /**
   * Whether the SERVER will run notebook cells.
   *
   * Advertised for the same reason `enact` is, and gated separately: running
   * code from a note is a larger permission than pressing a button in a
   * browser, and a reader who wanted one did not thereby ask for the other.
   * Absent from an older sidecar, so read it as optional and treat missing as
   * off -- the safe direction to be wrong in.
   */
  kernel?: boolean;
}

/** One cell's result, from `POST /kernel`. */
export interface KernelReply {
  ok?: boolean;
  stdout?: string;
  stderr?: string;
  /** `repr()` of a trailing expression, absent when the cell ended in a
   *  statement. `None` is deliberately not reported. */
  value?: string | null;
  /** A formatted traceback when the cell raised, or the server's own refusal. */
  error?: string;
  detail?: string;
  /** How many cells this kernel has run, which is the execution count. */
  count?: number;
  /** Said when the kernel was started, or died, or was killed on a timeout --
   *  i.e. whenever the namespace is not the one the previous cell left. */
  kernel?: string;
  /** Which note's kernel was retired to make room for this one. */
  evicted?: string;
}

export interface EnactResult {
  ok?: boolean;
  did?: string;
  detail?: string;
  address?: string;
  url?: string;
  error?: string;
  refused?: boolean;
}

/**
 * The sidecar's adjudication of a panel gesture (`/enact`, `mode: "plan"`):
 * what the browser cell is allowed to touch, taken from the TRIE's stored
 * address and not from the caller -- or the refusal.
 */
export interface EnactPlan {
  ok?: boolean;
  /** The in-page tick: click, type or choose. */
  kind?: string;
  action?: string;
  address?: string;
  url?: string;
  xpath?: string;
  label?: string;
  error?: string;
  refused?: boolean;
  detail?: string;
}

export interface SearchResult {
  query: string;
  hits: SearchHit[];
}

export interface VertiscopeSettings {
  /** Where the Python sidecar answers. Empty disables every lookup. */
  sidecar: string;
  /** Start in the interactive surface rather than the distilled markdown. */
  interactiveByDefault: boolean;
  /**
   * Load images from the network in the surface.
   *
   * Off by default, and that is a privacy decision rather than a performance
   * one: a distilled page can carry tracking pixels and per-user asset urls,
   * and fetching them from a vault announces to those hosts that the page was
   * read again, at a new time, from a new address. Opening a note should not
   * do that without being asked.
   */
  loadRemoteMedia: boolean;
  /** How many hits the `/` retrieval gesture offers. */
  retrievalLimit: number;
  /**
   * Save each page as the browser cell PRESENTS it, for offline use (`G-60`:
   * "toggle the option to save the full webpage as it is presented live").
   * Off by default: a saved page is a whole copy of the page on disk.
   */
  saveOffline: boolean;
  /**
   * The browser overlay's chunk outlines DRAWN or not (2026-10-11, PLUGIN_GOAL
   * 89: "a toggle to the browser overlay that *shows* the overlay chunk
   * bounding boxes as on or off, while keeping the regular functionality the
   * same, just a difference basically of the alpha-ing").
   */
  showBoxes: boolean;
  /**
   * Each query from the 3D search field ALSO searches DuckDuckGo in the
   * browser cell (2026-10-11, PLUGIN_GOAL 85: "search duckduckgo
   * automatically, following a simple auto-scroll and clicking 'more results'
   * each time"). This sends the query off the machine -- the one thing the
   * plugin transmits on its own -- so it is a setting, on as asked.
   */
  webSearch: boolean;
  /** uBlock Origin in the browser cell's own session (G-201). */
  adblock: boolean;
}

export const DEFAULTS: VertiscopeSettings = {
  sidecar: "http://127.0.0.1:8787",
  interactiveByDefault: true,
  loadRemoteMedia: false,
  retrievalLimit: 8,
  saveOffline: false,
  showBoxes: true,
  webSearch: true,
  adblock: true,
};

/** One command's result, from `POST /shell`. */
export interface ShellReply {
  ok?: boolean;
  output?: string;
  count?: number;
  /** Which shell ran it, by display name. */
  interpreter?: string;
  /** Said when the session is not the one the last command left. */
  shell?: string;
  /** Which pane's session was retired to make room. */
  evicted?: string;
  error?: string;
  detail?: string;
  /** True when the command was declined without touching the session -- a TUI
   *  program, which this runner has no terminal for. Distinct from `error`,
   *  because a refusal leaves the reader's `cd` and environment intact. */
  refused?: boolean;
}

/** What `GET /interpreters` found on this machine. */
export interface Interpreters {
  python: { name: string; path: string; version: string; runnable: boolean }[];
  shells: { name: string; exe: string; path: string; runnable: boolean }[];
  /** Installed, and NOT runnable by this sidecar -- it drives a subprocess,
   *  not the Jupyter protocol. Reported so the reader sees what exists. */
  jupyter_kernels: { name: string; key: string; runnable: boolean }[];
}

/** `POST /chunk_preview`: where the chunker would cut the text sent. */
export interface ChunkPreview {
  path?: string;
  chunks: {
    index: number;
    start_line: number;
    end_line: number;
    xpath: string;
    part: number;
    tokens: number;
    window: number;
    over_window: boolean;
  }[];
}

/** What `POST /capture` says the browser cell's scan produced (`G-47`). */
/**
 * One diff of the patricia trie's rendered chunks, keyed on the cid -- the
 * identity every consumer shares (store, projector, chunk map, 3D nodes,
 * pins). The backend computes it once; the browser's chunk map, its pins and
 * every graph view apply the SAME record, so none of them infers retirement.
 */
export interface CentralDiff {
  seq: number;
  kind: "capture" | "settle";
  url: string;
  passno: number | null;
  /** In this render, not in the session's previous one nor the store's. */
  added: string[];
  dirty: string[];
  /** Gone from the render: the store dropped them, views must too. */
  retired: string[];
  /** retired cid -> added cid with identical markdown (a shift, not a loss). */
  renamed: Record<string, string>;
  /** Rendered now and already stored before this visit: drawn, not spawned. */
  known?: string[];
  chunks: number;
  at: number;
}

export interface CaptureResult {
  url?: string;
  /** The sidecar's own per-phase timings for this capture, ms, its
   *  clock: decode, absorb, render, lock_wait, store and its ms_*
   *  parts, place. Durations only -- they cannot be subtracted from
   *  this renderer's clock, only checked against it. */
  phases?: Record<string, number>;
  /** Echo of the profiler trace id the drain was sent with. */
  trace?: string;
  passno?: number;
  addresses?: number;
  chunks?: number;
  lines?: number;
  /** Chunks this drain actually rewrote -- the O(delta) number. */
  dirty?: number;
  /** Which ones, named. A count would leave the pane refetching the
   *  whole layout to find out which three nodes moved. */
  dirty_cids?: string[];
  /** Placed nodes, when the capture was asked to place them -- the same
   *  shape `/layout` returns. Present instead of a second round trip. */
  nodes?: unknown[];
  /** Containment edges among them (`G-6`). */
  edges?: { source: string; target: string }[];
  /** Captured but not yet embedded; normal for a chunk seconds old. */
  unplaced?: string[];
  /** The corpus has doubled since the fit; the pane should refit. */
  stale?: boolean;
  /** Why nothing could be placed, when that is a fact about the FIT rather
   *  than about the chunks -- "no fit to place into yet". Distinct from
   *  `unplaced`, which means the chunks have no vector yet. */
  why?: string;
  /** Set when storing succeeded and placing did not. The two are reported
   *  apart because a capture that landed must not read as one that did not. */
  place_error?: string;
  changed?: number;
  wire_bytes?: number;
  /** The central diff (`_page_diff` / `_record_diff` in the sidecar): one
   *  record per capture and per settle, applied unchanged by every view. */
  diff?: CentralDiff | null;
  settled?: boolean;
  ms?: number;
  /** Set instead of the rest when the capture did not land. A capture that
   *  fails quietly is indistinguishable from a page with nothing in it. */
  error?: string;
}

/** A window over the ranked list (`G-69`). */
export interface SearchResults extends SearchResult {
  offset: number;
  /** The url the ranking was scoped to, or "" for the corpus. */
  scope: string;
  coarse: boolean;
  tokens: number;
  /** The ranking still had more at this depth, so scrolling should ask. */
  more: boolean;
}

/** One step of unravelling a page's patricia path (`G-54`). */
export interface UnfoldResult {
  nodes?: unknown[];
  /** Containment edges among the emitted nodes (`G-6`). */
  edges?: { source: string; target: string }[];
  url?: string;
  /** The path that was unravelled TO, after descending past single children. */
  path?: string;
  branches?: number;
  leaves?: number;
  why?: string;
}

/** What `POST /place` says about chunks captured after the fit (`G-34`). */
export interface PlaceResult {
  /** Nodes in the same shape `/layout` returns, placed by `transform`. */
  nodes?: unknown[];
  /** Containment edges among those nodes (`G-6`). Without them a page opens
   *  as a scatter of unconnected dots. */
  edges?: { source: string; target: string }[];
  /** Captured but not yet embedded -- the normal state for a chunk seconds
   *  old, since the embedding phase is asynchronous by design. */
  unplaced?: string[];
  /** The corpus has doubled since the fit; the pane should refit. */
  stale?: boolean;
  fitted_n?: number;
  n?: number;
  why?: string;
}
