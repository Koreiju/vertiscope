/**
 * The contract between the plugin and the domvec sidecar.
 *
 * Kept in one file because it is a contract with a program in another
 * language: `domvec/obsidian/sidecar.py` builds exactly these shapes, and a
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
   * The same chunk as slim distilled HTML, built by `htmlform.py` from these
   * very lines.
   *
   * It travels WITH the lines rather than behind a second route, so a surface
   * cannot hold a markdown form and an HTML form fetched at different
   * moments -- two renderings of possibly two states. They are one
   * distillation.
   *
   * Every element in it carries `data-domvec-address`, so a click maps back
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

export interface SearchResult {
  query: string;
  hits: SearchHit[];
}

export interface DomvecSettings {
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
}

export const DEFAULTS: DomvecSettings = {
  sidecar: "http://127.0.0.1:8787",
  interactiveByDefault: true,
  loadRemoteMedia: false,
  retrievalLimit: 8,
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
export interface CaptureResult {
  url?: string;
  passno?: number;
  addresses?: number;
  chunks?: number;
  lines?: number;
  /** Chunks this drain actually rewrote -- the O(delta) number. */
  dirty?: number;
  /** Which ones, named. A count would leave the pane refetching the
   *  whole layout to find out which three nodes moved. */
  dirty_cids?: string[];
  changed?: number;
  wire_bytes?: number;
  settled?: boolean;
  ms?: number;
  /** Set instead of the rest when the capture did not land. A capture that
   *  fails quietly is indistinguishable from a page with nothing in it. */
  error?: string;
}

/** What `POST /place` says about chunks captured after the fit (`G-34`). */
export interface PlaceResult {
  /** Nodes in the same shape `/layout` returns, placed by `transform`. */
  nodes?: unknown[];
  /** Captured but not yet embedded -- the normal state for a chunk seconds
   *  old, since the embedding phase is asynchronous by design. */
  unplaced?: string[];
  /** The corpus has doubled since the fit; the pane should refit. */
  stale?: boolean;
  fitted_n?: number;
  n?: number;
  why?: string;
}
