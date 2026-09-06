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
}

export interface SearchHit {
  cid: string;
  url: string;
  score: number;
  /** The first few lines, for the suggestion list. */
  preview: string;
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
